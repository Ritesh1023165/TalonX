"""
tests/test_task140_exit_eligibility_after_scope_change.py
===========================================================
Task 140 (A4 closure): "existing positions remain eligible for exit
after scope changes" -- the one genuine gap left open in
docs/research/evidence/task139/completion_map.md ("never isolated-
tested -- no open position has existed this campaign to exercise it").

Verified by direct code inspection first (see that file's own note),
now backed by an isolated test: an OPEN position for a symbol NOT in
the current execution_allowlist (simulating a position opened before a
scope change, now outside the reduced/changed allowlist) must still be
closed normally when its exit becomes due. `_apply_execution_allowlist`
is only ever called on NEW-entry candidate paths (records/episodes);
`pipeline.settle_due_exits` reads `store.open_positions()` /
`paper.due_exits()` directly, with no allowlist parameter at all --
this test proves that holds in practice, not just by reading the
source.

Uses a fully isolated tmp_path V2Store/V2Config -- no live campaign
ledger touched, no position manufactured in the real system.
"""
from __future__ import annotations

from datetime import date

from talonx_v2.config import V2Config
from talonx_v2.pipeline import ProcessResult, settle_due_exits
from talonx_v2.store import V2Store


def _cfg(tmp_path, **kw):
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", 300_000.0)
    kw.setdefault("db_path", str(tmp_path / "v2.db"))
    return V2Config(**kw)


def test_open_position_outside_the_current_allowlist_still_exits_normally(tmp_path):
    cfg = _cfg(tmp_path)
    store = V2Store(cfg.db_path)
    store.set_cash(cfg.starting_cash_usd)

    entry_session = date(2026, 8, 20)
    target_exit = date(2026, 9, 3)          # +10 trading sessions, already due
    pos_id = store.insert_open_position(
        episode_id="ep-scope-changed-1", symbol="ZZZZ", issuer_cik="zzzzc",
        entry_session=entry_session, target_exit_session=target_exit,
        entry_price=50.0, shares=200, position_cost=10_000.0,
    )
    assert store.position_for_symbol("ZZZZ") is not None
    assert store.n_open() == 1

    # ZZZZ is deliberately NOT in the current execution allowlist --
    # simulating a scope change (e.g. broad-discovery toggled off, or the
    # 626-name manifest revised) after this position was opened under an
    # earlier, wider scope. settle_due_exits() takes no allowlist
    # parameter at all -- there is no code path by which it even COULD
    # filter on one.
    def price_lookup(symbol, session):
        assert symbol == "ZZZZ"
        return {"close": 55.0}

    res = ProcessResult()
    as_of = date(2026, 9, 4)   # a session on/after the target exit
    settle_due_exits(store=store, as_of_session=as_of, price_lookup=price_lookup,
                     config=cfg, result=res)

    assert len(res.exits) == 1
    assert res.exits[0]["symbol"] == "ZZZZ"
    assert store.position_for_symbol("ZZZZ") is None      # closed, no longer open
    assert store.n_open() == 0
    # cash increased by the exit proceeds -- the exit had a genuine
    # economic effect, not a silent no-op
    assert store.cash() > 300_000.0 - 10_000.0


def test_execution_allowlist_only_ever_gates_new_candidates_not_open_positions(tmp_path):
    """Structural confirmation via V2Service itself: constructing it with
    an allowlist that excludes an already-open position's symbol must not
    raise, drop, or otherwise touch that position -- the allowlist filter
    is applied to freshly-detected episodes/records only."""
    from talonx_v2.service import V2Service

    cfg = _cfg(tmp_path)
    store = V2Store(cfg.db_path)
    store.set_cash(cfg.starting_cash_usd)
    store.insert_open_position(
        episode_id="ep-scope-changed-2", symbol="YYYY", issuer_cik="yyyyc",
        entry_session=date(2026, 8, 20), target_exit_session=date(2026, 9, 3),
        entry_price=20.0, shares=100, position_cost=2_000.0,
    )

    # YYYY is excluded from the allowlist below on purpose
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"),
                    execution_allowlist=["AAPL", "MSFT"])
    assert svc.execution_allowlist is not None
    assert "YYYY" not in svc.execution_allowlist
    # the position is still visible/open via the store -- construction
    # alone never touches it
    s2 = V2Store(cfg.db_path)
    assert s2.position_for_symbol("YYYY") is not None
