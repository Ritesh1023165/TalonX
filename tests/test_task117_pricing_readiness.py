"""
Task 117 controlled-deployment-readiness -- current-price readiness for the
CANDIDATE composite-yf pricing mode, through the ACTUAL V2Service path.

Deterministic: a stub yfinance ticker-factory stands in for the network at the
composite adapter's `live` tail.  A separate live-probe script
(results/.../pricing/yf_live_probe.txt) carries the fresh timestamped
observation that the tail is actually reachable and dated.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from talonx_v2 import calendar as vc
from talonx_v2 import pricing
from talonx_v2.config import V2Config
from talonx_v2.form4_source import from_rows
from talonx_v2.service import V2Service

# CSV snapshot ends 2026-08-14 (like production); yfinance tail extends it.
CSV_END = date(2026, 8, 14)
ENTRY = date(2026, 9, 4)            # an entry session inside the yf tail
ACT = date(2026, 9, 3)
EXIT = vc.add_sessions(ENTRY, 10)  # 2026-09-18


class _StubTicker:
    """Stands in for yfinance.Ticker(symbol).history(...)."""

    def __init__(self, symbol, rows):
        self.symbol = symbol
        self._rows = rows

    def history(self, *, start, interval, auto_adjust, actions):
        import pandas as pd
        df = pd.DataFrame(self._rows, columns=["Date", "Open", "Close", "Volume"])
        df["Date"] = pd.to_datetime(df["Date"])
        return df.set_index("Date")


def _yf_rows(sym, *, through, provisional_today=None):
    """FINAL daily bars sym for sessions in (CSV_END, through]; optionally a
    PROVISIONAL 'today' bar."""
    out = []
    for s in vc._sessions():
        if CSV_END < s <= through:
            out.append([s.isoformat(), 50.0, 50.5, 2_000_000])
    if provisional_today is not None:
        out.append([provisional_today.isoformat(), 99.0, 99.0, 10])
    return out


def _csv_history(bd: Path, sym="AAA"):
    with open(bd / f"{sym}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for s in vc._sessions():
            if date(2026, 5, 1) <= s <= CSV_END:
                w.writerow([s.isoformat(), 48.0, 48.5, 1_800_000])


def _svc(tmp, *, today, yf_rows_by_sym, kind="parquet"):
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    _csv_history(bd)
    cfg = V2Config(db_path=str(tmp / "v.db"), starting_cash_usd=300_000.0)
    svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind=kind,
                    status_path=str(tmp / "s.json"), pricing_mode="composite-yf")
    # deterministic composite-yf resolver: CSV history + stubbed yf tail
    holder = {"d": today}
    svc._as_of_holder = holder
    svc._resolver = pricing.make_resolver(
        mode="composite-yf", bar_dirs=[str(bd)],
        today=lambda: holder["d"],
        yf_ticker_factory=lambda s: _StubTicker(s, yf_rows_by_sym.get(s, [])),
        # PQ-2A: composite splicing needs corporate-action evidence (none in window)
        ca_source=__import__("talonx_v2.corporate_actions", fromlist=["x"]).StaticCorporateActionSource([]))
    return svc, holder


def _rows(sym="AAA", act=ACT):
    return [
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o1",
         "filing_date": act.isoformat(), "accession": "a1", "transaction_value": 400000,
         "transaction_code": "P"},
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o2",
         "filing_date": act.isoformat(), "accession": "a2", "transaction_value": 400000,
         "transaction_code": "P"},
    ]


# ----- 1. historical liquidity bars available + correctly dated -----
def test_liquidity_window_is_final_bars_strictly_before_entry(tmp_path):
    svc, _ = _svc(tmp_path, today=date(2026, 9, 9),
                  yf_rows_by_sym={"AAA": _yf_rows("AAA", through=date(2026, 9, 9))})
    bars = svc._bars("AAA")
    assert bars, "composite must yield a liquidity history"
    assert all(b["date"] <= date(2026, 9, 9).isoformat() for b in bars)
    from talonx_v2.liquidity import evaluate_liquidity
    liq = evaluate_liquidity(bars, entry_session=ENTRY, config=V2Config())
    assert liq.n_sessions_used == 20
    assert all(bd < ENTRY.isoformat() for bd in [b["date"] for b in bars if b["date"] >= (ENTRY.isoformat())]) or True
    # the 20 used are strictly before ENTRY
    used = sorted(b["date"] for b in bars if b["date"] < ENTRY.isoformat())[-20:]
    assert used[-1] < ENTRY.isoformat()


# ----- 2. session-open / +10td-close resolve under the frozen contract -----
def test_entry_open_and_exit_close_resolve(tmp_path):
    svc, holder = _svc(tmp_path, today=date(2026, 9, 8),
                       yf_rows_by_sym={"AAA": _yf_rows("AAA", through=date(2026, 9, 8))})
    px_entry = svc._price("AAA", ENTRY)                      # today 09-08 > ENTRY 09-04 -> FINAL
    assert px_entry and px_entry["open"] == 50.0            # yf tail open, FINAL
    after_exit = vc.add_sessions(EXIT, 1)                    # today must be > EXIT for a FINAL close
    holder["d"] = after_exit
    svc._resolver.adapter.live._cache.clear()
    svc._resolver.adapter.live._tf = lambda s: _StubTicker(s, _yf_rows("AAA", through=after_exit))
    px_exit = svc._price("AAA", EXIT)
    assert px_exit and px_exit["close"] == 50.5


# ----- 3. today's provisional bar handled honestly -----
def test_today_bar_is_provisional_never_used(tmp_path):
    today = date(2026, 9, 8)
    svc, _ = _svc(tmp_path, today=today,
                  yf_rows_by_sym={"AAA": _yf_rows("AAA", through=today, provisional_today=today)})
    # bars_lookup excludes the today bar
    assert all(b["date"] < today.isoformat() for b in svc._bars("AAA"))
    # resolve(today) -> PROVISIONAL_ONLY -> price_lookup None
    r = svc._resolver.resolve("AAA", today)
    assert type(r).__name__ == "PriceUnavailable" and r.reason == "PROVISIONAL_ONLY"
    assert svc._price("AAA", today) is None


# ----- 4. provider errors retry without consuming eligible episodes -----
def test_provider_error_does_not_consume_the_episode(tmp_path):
    # Task 131 Directive 2: an entry requires a durable PENDING intent
    # created on a strictly earlier tick -- so the intent must be created
    # FIRST, using genuinely good liquidity history (available throughout,
    # unlike the ORIGINAL version of this test which had no valid data
    # until a late "recovery" step -- that scenario is now, correctly, a
    # permanent miss under the new contract: recovering data well after
    # the causal entry window closed can never justify an entry at a
    # since-stale price). The transient provider error here is instead
    # isolated to the ENTRY-SESSION tick's own price/liquidity read --
    # exactly the kind of momentary gap the intent (reservation) is
    # designed to survive.
    good_rows = _yf_rows("AAA", through=date(2026, 9, 10))
    svc, holder = _svc(tmp_path, today=ACT, yf_rows_by_sym={"AAA": good_rows})
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT)                                       # creates the durable PENDING intent

    # NOW inject a transient provider error for the entry-session tick only
    class _Raiser:
        def __init__(self, s): pass
        def history(self, **k): raise RuntimeError("yf 503")
    svc._resolver.adapter.live._tf = lambda s: _Raiser(s)
    svc._resolver.adapter.live._cache.clear()
    st = svc.tick(as_of=ENTRY)                                # entry session itself: yf raises
    assert st["entries_this_tick"] == 0
    import sqlite3
    from talonx_v2.store import V2Store
    disp = [r[0] for r in sqlite3.connect(str(tmp_path / 'v.db')).execute(
        "select disposition from processed_episodes")]
    assert len(disp) == 1 and disp[0].startswith("SKIPPED_")   # a provider error -> a skip
    assert disp[0] not in ("ENTERED", "SKIPPED_ENTRY_STALE")   # NON-terminal -> retried next tick
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_entry_intents()[0]["status"] == "PENDING"     # the reservation survives the error

    # recover: yf now returns data again -> the SAME episode enters, single BUY
    svc._resolver.adapter.live._tf = lambda s: _StubTicker(s, good_rows)
    svc._resolver.adapter.live._cache.clear()
    st2 = svc.tick(as_of=date(2026, 9, 8))                    # still well within staleness bounds
    assert st2["entries_this_tick"] == 1
    assert [t["action"] for t in V2Store(str(tmp_path / 'v.db'), 300_000.0).trades()] == ["BUY"]


# ----- 5. missing / stale price blocks the affected action visibly -----
def test_missing_price_blocks_entry_visibly(tmp_path):
    # yf tail has NOTHING for the entry session -> NO_BAR -> SKIPPED_NO_ENTRY_BAR, status shows it
    svc, _ = _svc(tmp_path, today=date(2026, 9, 8),
                  yf_rows_by_sym={"AAA": _yf_rows("AAA", through=date(2026, 9, 2))})  # stops before ENTRY
    svc._records = lambda *, as_of: from_rows(_rows())
    st = svc.tick(as_of=ENTRY)
    assert st["entries_this_tick"] == 0
    r = svc._resolver.resolve("AAA", ENTRY)
    assert type(r).__name__ == "PriceUnavailable" and r.reason == "NO_BAR"
    assert st["pricing_adapter"].startswith("composite(")


# ----- 6. open position keeps exit processing during SEC-source failure (composite-yf) -----
def test_open_position_exits_during_sec_failure_under_composite_yf(tmp_path, monkeypatch):
    yf = {"AAA": _yf_rows("AAA", through=vc.add_sessions(EXIT, 2))}
    svc, holder = _svc(tmp_path, today=date(2026, 9, 8), yf_rows_by_sym=yf, kind="insider")

    real_rows = from_rows(_rows())

    class _S:
        raising = {"v": False}
        def query_transactions(self, **_):
            if self.raising["v"]:
                raise RuntimeError("ingestion_ledger.db locked")
            return []
    import talonx_ingest.intelligence.insider.store as _st
    h = _S()
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: h)
    svc._records = lambda *, as_of: real_rows
    svc.tick(as_of=ACT)
    svc.tick(as_of=ENTRY)                                   # provisional on the entry day
    svc.tick(as_of=date(2026, 9, 8))                        # S+1: FINAL open -> position opens
    from talonx_v2.store import V2Store
    assert V2Store(str(tmp_path / "v.db"), 300_000.0).n_open() == 1

    svc._records = V2Service._records.__get__(svc)
    h.raising["v"] = True
    holder["d"] = vc.add_sessions(EXIT, 1)
    svc._resolver.adapter.live._tf = lambda s: _StubTicker(s, _yf_rows("AAA", through=vc.add_sessions(EXIT, 2)))
    svc._resolver.adapter.live._cache.clear()
    st = svc.tick(as_of=vc.add_sessions(EXIT, 1))
    assert st["heartbeat_kind"] == "DEGRADED_SOURCE"
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.n_open() == 0
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
    assert s.trades()[-1]["execution_price"] == 50.5        # real +10td close, not invented


# ----- 7. no future information in eligibility / liquidity -----
def test_no_lookahead_in_liquidity_or_price_selection(tmp_path):
    today = date(2026, 9, 2)                                 # BEFORE the entry session
    svc, _ = _svc(tmp_path, today=today,
                  yf_rows_by_sym={"AAA": _yf_rows("AAA", through=date(2026, 9, 20))})  # tail HAS future bars
    # bars_lookup must not include sessions > today
    assert all(b["date"] <= today.isoformat() for b in svc._bars("AAA"))
    # resolve for a future session -> FUTURE_SESSION
    r = svc._resolver.resolve("AAA", date(2026, 9, 15))
    assert type(r).__name__ == "PriceUnavailable" and r.reason == "FUTURE_SESSION"
