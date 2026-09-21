"""
Task 113 -- P1 regression: the live staleness guard must skip a stale
insider-cluster episode on EVERY tick, not just the first.

Incident TASK113_P1_ABCL_HISTORICAL_REPLAY_CONTAMINATION (2026-09-08):
the frozen release entered a ~3-week-old historical ABCL cluster into the
fresh Day-1 prospective ledger.  Root cause: the guard condition was
``e.eligible_entry_session < stale_cut AND not episode_seen(id)`` -- the
first-tick SKIPPED_ENTRY_STALE disposition marked the episode "seen", so
on the next tick the guard's own precondition was false and the stale
episode fell through to process_episode and was entered at the historical
price.  Backstop hole: process_episode only treated "ENTERED" as terminal.

Fix: a stale episode is ALWAYS excluded from the entry set (every tick,
seen or not); only the disposition write is guarded.  process_episode
also treats a prior SKIPPED_ENTRY_STALE as terminal.

No strategy semantics change -- max_entry_staleness_sessions stays 3.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from talonx_v2 import calendar as v2cal
from talonx_v2 import form4_source, pipeline
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

TUESDAY = date(2026, 9, 8)
BALANCE = 300_000.0


def _cfg(tmp_path, **kw):
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", BALANCE)
    kw.setdefault("db_path", str(tmp_path / "v2.db"))
    return V2Config(**kw)


def _bars(a="2026-06-01", b="2026-10-15", close=100.0, vol=500_000):
    sess = [s for s in v2cal._sessions()
            if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol}
            for s in sess]


def _cluster_rows(sym, d1, d2):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
             accession=sym + "a1", transaction_value=500_000, is_officer=True,
             transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
             accession=sym + "a2", transaction_value=700_000, is_director=True,
             transaction_code="P"),
    ]


def _svc(cfg, tmp_path, rows, bars):
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"))
    recs = form4_source.from_rows(rows)
    svc._records = lambda *, as_of: recs           # noqa: SLF001
    svc._bars = lambda sym: bars                   # noqa: SLF001
    svc._price = lambda sym, session: next(         # noqa: SLF001
        (b for b in bars if b["date"] == (session.isoformat()
                                          if isinstance(session, date) else str(session)[:10])), None)
    return svc


# --------------------------------------------------------------------------

def test_stale_episode_skipped_every_tick(tmp_path):
    """The ABCL-shaped scenario: eligible entry ~2026-08-17, tick 2026-09-08.
    10 consecutive ticks -> never entered, cash never moves."""
    cfg = _cfg(tmp_path)
    rows = _cluster_rows("STALE", "2026-08-12", "2026-08-14")
    bars = _bars()
    svc = _svc(cfg, tmp_path, rows, bars)

    ep = detect_episodes(form4_source.from_rows(rows), config=cfg)[0]
    # sanity: this scenario really is stale by the frozen threshold
    assert ep.eligible_entry_session < date(2026, 8, 25)

    store = V2Store(cfg.db_path)

    def _row():
        with store._conn() as c:  # noqa: SLF001
            return c.execute(
                "SELECT disposition, first_seen_at, updated_at FROM processed_episodes "
                "WHERE episode_id=?", (ep.episode_id,)).fetchone()

    for i in range(10):
        st = svc.tick(as_of=TUESDAY)
        assert st["ripe_episodes_this_tick"] == 0, f"tick {i}: episode leaked into entry set"
        assert st["stale_entry_skipped_this_tick"] == 1, \
            f"tick {i}: guard should hold the stale episode out every tick"
        assert st["entries_this_tick"] == 0, f"tick {i}: STALE ENTRY"
        assert st["open_positions"] == 0
        assert store.cash() == BALANCE, f"tick {i}: cash mutated to {store.cash()}"
        assert store.n_open() == 0
        assert store.trades() == []

    row = _row()
    assert row["disposition"] == "SKIPPED_ENTRY_STALE"
    # disposition write is guarded -- recorded once on tick 0, never re-written
    assert row["first_seen_at"] == row["updated_at"], "SKIPPED_ENTRY_STALE row churned every tick"


def test_process_episode_treats_prior_stale_skip_as_terminal(tmp_path):
    """Even if something routes a stale episode to process_episode, a prior
    SKIPPED_ENTRY_STALE disposition stops it from entering."""
    cfg = _cfg(tmp_path)
    rows = _cluster_rows("TERM", "2026-08-12", "2026-08-14")
    bars = _bars()
    ep = detect_episodes(form4_source.from_rows(rows), config=cfg)[0]
    store = V2Store(cfg.db_path, starting_cash=BALANCE)
    store.record_disposition(
        episode_id=ep.episode_id, symbol=ep.symbol, disposition="SKIPPED_ENTRY_STALE",
        issuer_cik=ep.issuer_cik, eligible_entry_session=ep.eligible_entry_session.isoformat())

    res = pipeline.ProcessResult()
    bl = lambda s: bars                                              # noqa: E731
    pl = lambda s, d: next((b for b in bars if b["date"] == (d.isoformat() if isinstance(d, date) else str(d)[:10])), None)  # noqa: E731
    pipeline.process_episode(ep, store=store, bars_lookup=bl, price_lookup=pl,
                             config=cfg, result=res)
    assert res.entries == []
    assert any(s["reason"] == "ALREADY_PROCESSED" for s in res.skipped)
    assert store.n_open() == 0
    assert store.cash() == BALANCE
    assert store.trades() == []


def test_fresh_episode_still_enters(tmp_path):
    """The fix must not over-block: a non-stale episode (eligible entry
    within max_entry_staleness_sessions of the tick) still enters --
    given a durable PENDING intent was created on the strictly-earlier
    tick (Task 131 Directive 2: an entry is never admitted cold)."""
    cfg = _cfg(tmp_path)
    # filings on the two sessions immediately before the tick -> eligible
    # entry is the tick session itself (0 sessions stale).
    rows = _cluster_rows("FRESH", "2026-09-03", "2026-09-04")
    bars = _bars()
    svc = _svc(cfg, tmp_path, rows, bars)
    store = V2Store(cfg.db_path)

    # a tick on the session strictly before TUESDAY creates the durable
    # PENDING intent (activation 09-04, eligible entry 09-08 == TUESDAY).
    st0 = svc.tick(as_of=date(2026, 9, 4))
    assert st0["entry_intents_created_this_tick"] == 1
    assert st0["entries_this_tick"] == 0

    st = svc.tick(as_of=TUESDAY)
    assert st["ripe_episodes_this_tick"] == 1
    assert st["stale_entry_skipped_this_tick"] == 0
    assert st["no_prior_intent_skipped_this_tick"] == 0
    assert st["entries_this_tick"] == 1
    assert store.n_open() == 1
    assert store.cash() == BALANCE - 10_000.0


@pytest.mark.skipif(not (Path.home() / ".talonx" / "ingestion_ledger.db").exists(),
                    reason="live ingestion_ledger.db not present")
def test_live_abcl_episode_never_contaminates_day1_ledger(tmp_path):
    """Regression against the real incident: the live insider store contains
    the ABCL cluster (activation 2026-08-14, eligible entry 2026-08-17).
    Over several ticks dated 2026-09-08 it must be SKIPPED_ENTRY_STALE and
    never touch cash."""
    cfg = _cfg(tmp_path)
    svc = V2Service(
        config=cfg,
        bar_dirs=[Path("results/task95g_broad_cross_sectional/_daily"),
                  Path("results/task107a_form4_feasibility/_prices")],
        form4_kind="insider", status_path=str(tmp_path / "status.json"),
        live_lookback_days=45)
    store = V2Store(cfg.db_path)
    abcl_id = "07242bc857569f60"
    for i in range(3):
        st = svc.tick(as_of=TUESDAY)
        assert st["entries_this_tick"] == 0, f"tick {i}: a live episode entered on Day 1"
        assert store.cash() == BALANCE, f"tick {i}: cash mutated"
        assert store.n_open() == 0
        assert store.trades() == []
    disp = store.episode_disposition(abcl_id)
    assert disp == "SKIPPED_ENTRY_STALE", f"ABCL disposition = {disp!r}, expected SKIPPED_ENTRY_STALE"
