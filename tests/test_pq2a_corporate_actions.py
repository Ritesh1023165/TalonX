"""PQ-2A corporate-action safety & accounting contract -- deterministic tests.

No network, broker, production DB or provider activation.  Every ledger is a
tmp_path SQLite file; every provider is an in-memory fixture.

Scenario (used throughout): entry open 25.00 -> 400 whole shares -> cost
$10,000 (frozen $10k allocation).  A pure split must leave that economic
position unchanged; only the price BASIS differs.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from fractions import Fraction

import pytest

from talonx_v2 import calendar as v2cal, corporate_actions as ca, paper, pipeline
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.corporate_actions import (
    CorporateActionGuard, StaticCorporateActionSource, make_dividend_event, make_split_event,
    make_unsupported_event)
from talonx_v2.pricing import (
    CompositeBarAdapter, IncompatibleAdjustmentBasis, PricingResolver)
from talonx_v2.sizing import size_whole_shares_fee_inclusive
from talonx_v2.store import V2Store
from datetime import datetime, timezone

ENTRY = date(2026, 9, 8)
TARGET = v2cal.add_sessions(ENTRY, 10)
ENTRY_BASIS = "2026-09-08"           # entry open fetched on the entry session
CFG = V2Config(starting_cash_usd=300_000.0)


class MemAdapter:
    def __init__(self, name, rows=None):
        self.name, self.rows = name, rows or []

    def history(self, symbol):
        return list(self.rows)

    def session(self, symbol, session):
        return next((r for r in self.rows if r["date"] == session.isoformat()), None)


def row(session, open_=20.0, close=20.5, volume=1_000_000, **extra):
    return {"date": session.isoformat(), "open": open_, "close": close, "volume": volume, **extra}


def episode(entry=ENTRY):
    act = date(2026, 8, 14)
    return ClusterEpisode(
        episode_id="pq2a-episode", symbol="PQX", issuer_cik="1",
        distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
        first_filing_date=act, activation_filing_date=act, last_filing_date=act,
        aggregate_purchase_value=1.0, any_officer=False, any_director=False,
        any_ten_percent=False, causal_event_ts=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        eligible_entry_session=entry)


def _prior(entry=ENTRY, n=20):
    return [s for s in v2cal._sessions() if s < entry][-n:]


class _World:
    """One position opened through the REAL pipeline entry path, with a
    mutable price fixture so tests can stage exit bars / bases."""

    def __init__(self, tmp_path, *, entry_open=25.0, entry_basis=ENTRY_BASIS, name="w"):
        self.rows = [row(s, close=20.0, volume=1_000_000, _basis_as_of=entry_basis)
                     for s in _prior()]
        self.rows.append(row(ENTRY, open_=entry_open, close=entry_open + 0.5, _basis_as_of=entry_basis))
        self.adapter = MemAdapter("fixture", self.rows)
        self.resolver = PricingResolver(self.adapter, today=lambda: date(2026, 12, 31))
        self.db = str(tmp_path / f"{name}.db")
        self.store = V2Store(self.db, starting_cash=300_000.0)
        res = pipeline.process_episode(
            episode(), store=self.store, bars_lookup=self.resolver.bars_lookup,
            price_lookup=self.resolver.price_lookup, config=CFG)
        assert len(res.entries) == 1
        self.pos = self.store.all_positions()[0]

    def add_exit_bar(self, session, close, *, basis, open_=None):
        self.rows.append(row(session, open_=open_ or close, close=close, _basis_as_of=basis))

    def settle(self, guard, *, as_of=None):
        return pipeline.settle_due_exits(
            store=self.store, as_of_session=as_of or TARGET,
            price_lookup=self.resolver.price_lookup, config=CFG, corporate_actions=guard)

    def position(self):
        return self.store.all_positions()[0]


def guard_with(*events, **kw):
    return CorporateActionGuard(StaticCorporateActionSource(list(events), **kw))


SPLIT_10_1 = make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 10, 1, provider_id="alp-1")


# =========================================================================== #
# root cause (characterization of the PRE-FIX / unguarded path) + PQ-1 gap
# =========================================================================== #
def test_root_cause_unguarded_settlement_books_split_as_loss(tmp_path):
    """ROOT CAUSE, reproduced: entry shares/cost persisted on the pre-split
    basis, exit close served post-split, shares never re-expressed.  Only the
    guard-less (REPLAY/TEST) path behaves this way; live always passes a guard."""
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(None)
    pos = w.position()
    assert pos["status"] == "CLOSED"
    assert pos["realized_pnl_pct"] < -80.0            # the false ~-89% "loss"
    assert w.store.effective_shares_exact(pos["position_id"]) == 400


def test_pq1_known_gap_is_now_a_correctness_test_10_to_1_split_during_hold(tmp_path):
    """The PQ-1 KNOWN_GAP fixture (10:1 during hold, exit ~2.7) with the guard:
    10:1 -> 4000 economic shares, cost $10,000 unchanged, exit $10,800 -> +$800."""
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(SPLIT_10_1))
    pos = w.position()
    assert pos["status"] == "CLOSED"
    assert pos["position_cost"] == 10_000.0
    assert pos["realized_pnl_usd"] == pytest.approx(800.0, abs=1e-6)
    assert pos["realized_pnl_pct"] == pytest.approx(8.0, abs=1e-6)
    sell = [t for t in w.store.trades() if t["action"] == "SELL"][0]
    assert sell["shares"] == 4000.0                   # ACTUAL post-action quantity
    assert w.store.cash() == pytest.approx(300_000.0 + 800.0)


# =========================================================================== #
# 1-13: economics
# =========================================================================== #
def test_01_no_action_position_is_unchanged(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 27.0, basis="2026-09-23")
    w.settle(guard_with())
    pos = w.position()
    assert pos["realized_pnl_usd"] == pytest.approx(400 * 27.0 - 10_000.0)
    assert w.store.position_action_trail(pos["position_id"]) == []
    assert w.store.effective_shares_exact(pos["position_id"]) == 400


def test_02_forward_split_2_to_1(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 13.0, basis="2026-09-23")       # ~26 / 2
    w.settle(guard_with(make_split_event("PQX", v2cal.add_sessions(ENTRY, 3), 2, 1)))
    pos = w.position()
    assert w.store.trades()[-1]["shares"] == 800.0
    assert pos["realized_pnl_usd"] == pytest.approx(800 * 13.0 - 10_000.0)


def test_03_forward_split_10_to_1(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(SPLIT_10_1))
    assert w.position()["realized_pnl_usd"] == pytest.approx(800.0)


def test_04_reverse_split_exact_whole_result_and_13_settlement(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 270.0, basis="2026-09-23")      # ~27 x 10
    w.settle(guard_with(make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 1, 10)))
    pos = w.position()
    sell = [t for t in w.store.trades() if t["action"] == "SELL"][0]
    assert sell["shares"] == 40.0                           # 400 x 1/10 -- whole, exact
    assert pos["realized_pnl_usd"] == pytest.approx(40 * 270.0 - 10_000.0)   # +800, NOT a manufactured gain
    assert pos["realized_pnl_pct"] == pytest.approx(8.0)


def test_05_reverse_split_fractional_entitlement_retained_exactly(tmp_path):
    """333 shares (open 30.0) with a 1:10 reverse split = 33.3 shares.  Never
    rounded to 33/34/0, no cash-in-lieu invented; settled EXACTLY."""
    w = _World(tmp_path, entry_open=30.0)
    assert w.pos["shares"] == 333.0 and w.pos["position_cost"] == pytest.approx(9_990.0)
    w.add_exit_bar(TARGET, 330.0, basis="2026-09-23")
    g = guard_with(make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 1, 10))
    w.settle(g)
    pid = w.pos["position_id"]
    trail = w.store.position_action_trail(pid)
    assert [(t["shares_before"], t["shares_after"], t["status"]) for t in trail] == [("333", "333/10", "APPLIED")]
    sell = [t for t in w.store.trades() if t["action"] == "SELL"][0]
    assert sell["shares"] == pytest.approx(33.3)
    assert w.position()["realized_pnl_usd"] == pytest.approx(33.3 * 330.0 - 9_990.0)   # +999 exactly
    assert w.store.cash() == pytest.approx(300_000.0 + 999.0)


def test_06_split_during_hold_is_applied_by_the_sweep_and_marks_are_economic(tmp_path):
    w = _World(tmp_path)
    mid = v2cal.add_sessions(ENTRY, 5)
    g = guard_with(SPLIT_10_1)
    out = pipeline.sweep_corporate_actions(store=w.store, as_of=mid, guard=g)
    assert out[0]["status"] == "ADJUSTED" and out[0]["applied"] == [SPLIT_10_1.action_key]
    assert w.store.effective_shares_exact(w.pos["position_id"]) == 4000
    assert w.position()["shares"] == 400.0            # original entry row NEVER rewritten
    assert w.position()["entry_price"] == 25.0


def test_07_split_on_target_exit_session(tmp_path):
    w = _World(tmp_path)
    ev = make_split_event("PQX", TARGET, 10, 1)       # ex_date == target exit session
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(ev))
    assert w.position()["realized_pnl_usd"] == pytest.approx(800.0)


def test_08_split_during_exit_recovery_window(tmp_path):
    """Target-session bar missing; first available close is +2; the split's ex_date
    (+1) lies inside the recovery window.  Still exactly-once, still Session +10/+5."""
    w = _World(tmp_path)
    ff2 = v2cal.add_sessions(TARGET, 2)
    ev = make_split_event("PQX", v2cal.add_sessions(TARGET, 1), 10, 1)
    w.add_exit_bar(ff2, 2.7, basis=ff2.isoformat())
    w.settle(guard_with(ev), as_of=ff2)
    pos = w.position()
    assert pos["status"] == "CLOSED" and pos["exit_session"] == ff2.isoformat()
    assert pos["realized_pnl_usd"] == pytest.approx(800.0)


def test_08b_exit_price_basis_predating_an_applied_split_holds_then_unresolves(tmp_path):
    w = _World(tmp_path)
    ev = make_split_event("PQX", v2cal.add_sessions(TARGET, 1), 10, 1)
    g = guard_with(ev)
    nxt = v2cal.add_sessions(TARGET, 1)
    pipeline.sweep_corporate_actions(store=w.store, as_of=nxt, guard=g)      # applied on discovery
    w.add_exit_bar(TARGET, 27.0, basis=TARGET.isoformat())                    # STALE pre-split basis
    res = w.settle(g, as_of=nxt)
    assert w.position()["status"] == "OPEN"
    assert res.skipped[-1]["reason"] == "EXIT_HOLD_CORPORATE_ACTION"
    last_ff = v2cal.add_sessions(TARGET, 5)
    w.settle(g, as_of=last_ff)                                                # window exhausted
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert [t["action"] for t in w.store.trades()] == ["BUY"]


def test_split_already_reflected_in_the_entry_price_basis_is_recorded_not_applied(tmp_path):
    """Entry price fetched AFTER the ex-date (basis strictly later): the fill is already on
    the post-split basis (S5-22 'before-entry splits use post-split entry basis').  The
    action is recorded for audit but shares/cost are untouched -- no double adjustment."""
    ex = v2cal.add_sessions(ENTRY, 1)
    w = _World(tmp_path, entry_open=2.5, entry_basis=v2cal.add_sessions(ENTRY, 3).isoformat())
    assert w.pos["shares"] == 4000.0 and w.pos["position_cost"] == 10_000.0
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(make_split_event("PQX", ex, 10, 1)))
    pos = w.position()
    tr = w.store.position_action_trail(pos["position_id"])
    assert [t["status"] for t in tr] == ["REFLECTED_IN_ENTRY_BASIS"]
    assert w.store.effective_shares_exact(pos["position_id"]) == 4000            # NOT 40,000
    assert pos["realized_pnl_usd"] == pytest.approx(4000 * 2.7 - 10_000.0)       # +800


def test_split_on_the_entry_price_basis_date_is_ambiguous_and_fails_closed(tmp_path):
    """ex_date == the date the entry price was fetched: the provider may or may not have
    rebased history yet -> cannot prove which basis the entry price is on -> no settlement."""
    ex = v2cal.add_sessions(ENTRY, 1)
    w = _World(tmp_path, entry_basis=ex.isoformat())
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(make_split_event("PQX", ex, 10, 1)))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert w.store.blocked_action_rows(pos["position_id"])[0]["status"] == "BLOCKED_CA_PRICE_BASIS_AMBIGUOUS"


def test_a_previously_applied_split_that_disappears_from_the_evidence_fails_closed(tmp_path):
    w = _World(tmp_path)
    asof = v2cal.add_sessions(ENTRY, 6)
    pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=guard_with(SPLIT_10_1))
    out = pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=guard_with())     # provider dropped it
    assert out[0]["status"] == "BLOCK" and out[0]["code"] == ca.C_CONFLICT
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with())
    assert w.position()["status"] == "EXIT_UNRESOLVED" and w.position()["realized_pnl_usd"] is None


# =========================================================================== #
# 9-11: idempotency, restart, cost basis
# =========================================================================== #
def test_09_duplicate_split_is_idempotent_even_under_a_new_provider_id(tmp_path):
    w = _World(tmp_path)
    dup = make_split_event("PQX", SPLIT_10_1.ex_date, 10, 1, provider_id="alp-DUPLICATE-ID")
    g = guard_with(SPLIT_10_1, dup)
    asof = v2cal.add_sessions(ENTRY, 6)
    for _ in range(3):
        pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=g)
    pid = w.pos["position_id"]
    assert w.store.effective_shares_exact(pid) == 4000               # NOT 40,000 / 400,000
    assert len(w.store.position_action_trail(pid)) == 1
    assert len(w.store.corporate_action_registry()) == 1


def test_10_restart_does_not_reapply_the_split(tmp_path):
    w = _World(tmp_path)
    asof = v2cal.add_sessions(ENTRY, 6)
    pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=guard_with(SPLIT_10_1))
    restarted = V2Store(w.db)                                         # new process, same ledger
    pipeline.sweep_corporate_actions(store=restarted, as_of=asof, guard=guard_with(SPLIT_10_1))
    pipeline.sweep_corporate_actions(store=restarted, as_of=asof, guard=guard_with(SPLIT_10_1))
    assert restarted.effective_shares_exact(w.pos["position_id"]) == 4000
    assert len(restarted.position_action_trail(w.pos["position_id"])) == 1


def test_11_aggregate_cost_basis_is_preserved_across_a_pure_split(tmp_path):
    w = _World(tmp_path)
    pipeline.sweep_corporate_actions(store=w.store, as_of=v2cal.add_sessions(ENTRY, 6),
                                     guard=guard_with(SPLIT_10_1))
    pos = w.position()
    assert pos["position_cost"] == 10_000.0
    tr = w.store.position_action_trail(pos["position_id"])[0]
    assert tr["cost_basis"] == 10_000.0
    eff = w.store.effective_shares_exact(pos["position_id"])
    assert float(pos["position_cost"] / eff) == pytest.approx(2.5)   # per-share basis 25 / 10


# =========================================================================== #
# 14-16, 27: fail closed
# =========================================================================== #
def test_14_evidence_unavailable_holds_inside_window_then_unresolves_without_pnl(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    down = guard_with(status="UNAVAILABLE", detail="provider outage")
    res = w.settle(down, as_of=TARGET)
    assert w.position()["status"] == "OPEN" and w.store.cash() == 300_000.0 - 10_000.0
    assert res.skipped[-1]["reason"] == "EXIT_HOLD_CORPORATE_ACTION"
    w.settle(down, as_of=v2cal.add_sessions(TARGET, 5))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED"
    assert pos["exit_price"] is None and pos["realized_pnl_usd"] is None
    assert "CORPORATE_ACTION" in json.loads(pos["source_meta"])["exit_unresolved_detail"]


def test_14b_unknown_entry_basis_with_a_split_in_window_blocks(tmp_path):
    w = _World(tmp_path, entry_basis=None)               # snapshot-style row: basis unknown
    assert json.loads(w.pos["entry_price_provenance"])["basis_as_of"] is None
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(SPLIT_10_1))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert w.store.blocked_action_rows(pos["position_id"])[0]["status"] == "BLOCKED_CA_PRICE_BASIS_UNKNOWN"


def test_15_conflicting_evidence_fails_closed_across_sources_and_within_a_source(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    a = StaticCorporateActionSource([SPLIT_10_1], name="src-A")
    b = StaticCorporateActionSource([make_split_event("PQX", SPLIT_10_1.ex_date, 5, 1)], name="src-B")
    w.settle(CorporateActionGuard([a, b]))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert w.store.blocked_action_rows(pos["position_id"])[0]["status"] == "BLOCKED_CA_CONFLICTING_EVIDENCE"
    # within one source: same ex_date, two ratios
    w2 = _World(tmp_path, name="w2")
    w2.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w2.settle(guard_with(SPLIT_10_1, make_split_event("PQX", SPLIT_10_1.ex_date, 5, 1)))
    assert w2.position()["status"] == "EXIT_UNRESOLVED"
    # a witness that cannot answer never counts as agreement
    r = ca.combine_sources([StaticCorporateActionSource([SPLIT_10_1]).fetch("PQX", ENTRY, TARGET),
                            StaticCorporateActionSource(status="UNAVAILABLE").fetch("PQX", ENTRY, TARGET)])
    assert not r.ok
    # presence conflict: one source sees a split the other does not
    only = ca.combine_sources([StaticCorporateActionSource([SPLIT_10_1], name="A").fetch("PQX", ENTRY, TARGET),
                               StaticCorporateActionSource([], name="B").fetch("PQX", ENTRY, TARGET)])
    assert only.ok and only.conflicts


@pytest.mark.parametrize("etype", ["spin_offs", "cash_mergers", "name_changes", "unit_splits", "stock_dividends"])
def test_unsupported_actions_block_settlement_without_fabricating_pnl(tmp_path, etype):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 27.0, basis="2026-09-23")
    w.settle(guard_with(make_unsupported_event("PQX", v2cal.add_sessions(ENTRY, 3), etype)))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert [t["action"] for t in w.store.trades()] == ["BUY"]


def test_malformed_split_event_is_unsupported_not_a_split():
    e = ca.classify_alpaca_record("PQX", "forward_splits", {"id": "x", "ex_date": "2026-09-10",
                                                            "new_rate": 1, "old_rate": 10},
                                  source="t", received_at_utc="t")
    assert e.kind == ca.KIND_UNSUPPORTED and "direction disagrees" in e.malformed
    e2 = ca.classify_alpaca_record("PQX", "forward_splits", {"id": "x", "new_rate": 10, "old_rate": 1},
                                   source="t", received_at_utc="t")
    assert e2.kind == ca.KIND_UNSUPPORTED and e2.malformed == "split has no ex_date"


def test_16_exit_unresolved_cannot_fabricate_pnl_and_keeps_occupying_capacity(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 27.0, basis="2026-09-23")
    w.settle(guard_with(make_unsupported_event("PQX", v2cal.add_sessions(ENTRY, 3))))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED"
    assert pos["exit_price"] is None and pos["realized_pnl_usd"] is None and pos["realized_pnl_pct"] is None
    assert w.store.n_open() == 1 and w.store.position_for_symbol("PQX") is not None   # capacity + symbol held
    assert w.store.cash() == 290_000.0                                                # nothing credited
    assert w.store.blocked_reason() is not None                                       # operator-visible account block
    # defense in depth: even a direct settlement call is refused while a block row exists
    out = paper.close_position(w.store, pos, exit_price=27.0, exit_session=TARGET, config=CFG)
    assert out.settled is False


def test_27_legacy_rows_are_not_fabricated_and_no_events_means_no_change(tmp_path):
    store = V2Store(str(tmp_path / "legacy.db"), starting_cash=300_000.0)
    pid = store.insert_open_position(
        episode_id="legacy", symbol="OLD", issuer_cik="", entry_session=ENTRY,
        target_exit_session=TARGET, entry_price=10.0, shares=100, position_cost=1_000.0)
    store.set_cash(299_000.0)
    p = store.all_positions()[0]
    assert p["entry_price_provenance"] is None and p["exit_price_provenance"] is None
    g = guard_with()
    v = g.assess_position(store, p, as_of=TARGET, exit_basis_as_of=None, settlement=True)
    assert v.status == ca.V_CLEAR                                # no evidence of any action -> unchanged
    assert store.position_action_trail(pid) == []
    assert store.all_positions()[0]["entry_price_provenance"] is None     # NEVER back-filled
    # a legacy row WITH a split in the window cannot be adjusted (basis unknown)
    g2 = guard_with(make_split_event("OLD", v2cal.add_sessions(ENTRY, 2), 2, 1))
    v2 = g2.assess_position(store, p, as_of=TARGET, exit_basis_as_of=TARGET, settlement=True)
    assert v2.status == ca.V_BLOCK and v2.code == ca.C_BASIS_UNKNOWN


# =========================================================================== #
# 17-19: reconciliation + operator projection
# =========================================================================== #
def _reconcile(tmp_path, monkeypatch, db):
    from talonx_ops.prospective import close
    monkeypatch.setattr(close, "V2_DB_PATH", db)
    monkeypatch.setattr(close, "V2_STATUS_PATH", str(tmp_path / "no_status.json"))
    return close._v2_reconcile()


def test_17_reconciliation_accepts_a_valid_adjusted_position(tmp_path, monkeypatch):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(SPLIT_10_1))
    rec, asserts, findings = _reconcile(tmp_path, monkeypatch, w.db)
    for k in ("corporate_action_adjustments_consistent", "cash_plus_open_cost_reconciles",
              "buys_eq_sells_plus_open_plus_unresolved", "whole_share_positions", "no_negative_cash",
              "no_duplicate_position_episode_id"):
        assert asserts[k] == "PASS", (k, findings)
    # the adjusted OPEN position (mid-hold) also reconciles: no cash creation, no missing position
    w2 = _World(tmp_path, name="w2")
    pipeline.sweep_corporate_actions(store=w2.store, as_of=v2cal.add_sessions(ENTRY, 5), guard=guard_with(SPLIT_10_1))
    _, asserts2, _ = _reconcile(tmp_path, monkeypatch, w2.db)
    assert asserts2["corporate_action_adjustments_consistent"] == "PASS"
    assert asserts2["cash_plus_open_cost_reconciles"] == "PASS"


def test_18_reconciliation_detects_inconsistent_adjustment_state(tmp_path, monkeypatch):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w.settle(guard_with(SPLIT_10_1))
    con = sqlite3.connect(w.db)
    con.execute("UPDATE position_corporate_actions SET shares_after='40000'")     # corrupt the chain
    con.commit(); con.close()
    _, asserts, findings = _reconcile(tmp_path, monkeypatch, w.db)
    assert asserts["corporate_action_adjustments_consistent"] == "FAIL"
    assert any("corporate_action_adjustments_consistent" in f for f in findings)
    # a SELL that used the wrong (entry) quantity after a split is also caught
    w2 = _World(tmp_path, name="w2")
    w2.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    w2.settle(guard_with(SPLIT_10_1))
    con = sqlite3.connect(w2.db)
    con.execute("UPDATE trades SET shares=400 WHERE action='SELL'")
    con.commit(); con.close()
    assert any("SELL shares" in p for p in ca.consistency_problems(sqlite3.connect(w2.db)))
    # and the restart ledger-guard surfaces it as a problem (fail closed)
    from talonx_ops.prospective import ledger_guard
    bad = ledger_guard.check_ledger_continuity(w2.db)
    assert any("corporate-action adjustment inconsistent" in p for p in bad.problems)
    good = ledger_guard.check_ledger_continuity(_World(tmp_path, name="w3").db)
    assert not any("corporate-action" in p for p in good.problems)


def test_19_operator_projection_is_read_only_and_shows_the_action(tmp_path):
    w = _World(tmp_path)
    pipeline.sweep_corporate_actions(store=w.store, as_of=v2cal.add_sessions(ENTRY, 5), guard=guard_with(SPLIT_10_1))
    before = sqlite3.connect(w.db).execute("SELECT COUNT(*), SUM(id) FROM position_corporate_actions").fetchone()
    ro = sqlite3.connect(f"file:{w.db}?mode=ro", uri=True)
    rows = ca.trail_rows(ro)
    assert [(r["symbol"], r["kind"], r["ex_date"], r["ratio_num"], r["ratio_den"], r["status"]) for r in rows] == [
        ("PQX", "FORWARD_SPLIT", SPLIT_10_1.ex_date.isoformat(), "10", "1", "APPLIED")]
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM position_corporate_actions")            # projection connection cannot write
    ro.close()
    assert sqlite3.connect(w.db).execute("SELECT COUNT(*), SUM(id) FROM position_corporate_actions").fetchone() == before
    assert ca.effective_shares_map(sqlite3.connect(f"file:{w.db}?mode=ro", uri=True)) == {w.pos["position_id"]: 4000.0}


# =========================================================================== #
# 20-22: provenance
# =========================================================================== #
def test_20_21_22_provenance_is_retained(tmp_path):
    w = _World(tmp_path)
    entry_prov_before = w.pos["entry_price_provenance"]
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    a = StaticCorporateActionSource([SPLIT_10_1], name="src-A")
    b = StaticCorporateActionSource([make_split_event("PQX", SPLIT_10_1.ex_date, 10, 1, provider_id="B-9")],
                                    name="src-B")
    w.settle(CorporateActionGuard([a, b]))
    pos = w.position()
    # 20: corporate-action provenance (every corroborating source, ids, receipt time)
    reg = w.store.corporate_action_registry()[0]
    refs = json.loads(reg["sources_json"])
    assert {r["source"] for r in refs} == {"src-A", "src-B"} and {r["provider_id"] for r in refs} >= {"alp-1", "B-9"}
    assert all(r["received_at_utc"] for r in refs) and reg["ex_date"] == SPLIT_10_1.ex_date.isoformat()
    assert (reg["ratio_num"], reg["ratio_den"]) == ("10", "1")
    # 21: original entry provenance untouched
    assert pos["entry_price_provenance"] == entry_prov_before
    ep = json.loads(pos["entry_price_provenance"])
    assert (ep["provider"], ep["field"], ep["basis_as_of"]) == ("fixture", "open", ENTRY_BASIS)
    # 22: exit provenance + trade provenance
    xp = json.loads(pos["exit_price_provenance"])
    assert (xp["provider"], xp["field"], xp["basis_as_of"]) == ("fixture", "close", "2026-09-23")
    assert [json.loads(t["price_provenance"])["field"] for t in w.store.trades()] == ["open", "close"]


# =========================================================================== #
# 23-24: composite adapter adjustment-basis safety
# =========================================================================== #
def _composite_rows():
    sessions = _prior(ENTRY, 20)
    ex = ENTRY                                                   # split effective on the live tail's first day
    hist = MemAdapter("snapshot", [row(s, open_=250.0, close=250.0, volume=100_000) for s in sessions[:14]])
    live = MemAdapter("live", [row(s, open_=25.0, close=25.0, volume=1_000_000,
                                   _basis_as_of="2026-09-08") for s in sessions[14:]])
    return hist, live, sessions[13], ex


def test_23_unguarded_splice_would_mix_bases_and_the_composite_now_refuses():
    hist, live, last_hist, _ = _composite_rows()
    # PRE-FIX behaviour (raw merge, what history() used to do): ~$250 rows next to ~$25 rows
    spliced = hist.rows + live.rows
    closes = {r["close"] for r in spliced}
    assert closes == {250.0, 25.0}                               # incompatible bases in one window
    split = make_split_event("PQX", v2cal.add_sessions(last_hist, 1), 10, 1)
    # (a) evidence shows a split between the snapshot and the tail -> refuse
    comp = CompositeBarAdapter(hist, live, ca_source=StaticCorporateActionSource([split]),
                               today=lambda: date(2026, 9, 9))
    with pytest.raises(IncompatibleAdjustmentBasis):
        comp.history("PQX")
    resolver = PricingResolver(comp, today=lambda: date(2026, 9, 9))
    assert resolver.bars_lookup("PQX") == []
    assert resolver.last["PQX|history"].reason == "REJECTED_INCOMPATIBLE_ADJUSTMENT_BASIS"
    # (b) no evidence source at all -> cannot prove compatibility -> refuse
    with pytest.raises(IncompatibleAdjustmentBasis):
        CompositeBarAdapter(hist, live).history("PQX")
    # (c) evidence outage -> refuse (never "no evidence == no split")
    with pytest.raises(IncompatibleAdjustmentBasis):
        CompositeBarAdapter(hist, live, ca_source=StaticCorporateActionSource(status="UNAVAILABLE"),
                            today=lambda: date(2026, 9, 9)).history("PQX")
    # (d) unsupported action in the interval -> refuse
    with pytest.raises(IncompatibleAdjustmentBasis):
        CompositeBarAdapter(hist, live, ca_source=StaticCorporateActionSource(
            [make_unsupported_event("PQX", v2cal.add_sessions(last_hist, 1))]),
            today=lambda: date(2026, 9, 9)).history("PQX")


def test_24_normal_composite_fallback_stays_valid_when_bases_are_compatible():
    hist, live, last_hist, _ = _composite_rows()
    hist2 = MemAdapter("snapshot", [row(r["date"] and date.fromisoformat(r["date"]), open_=25.0, close=25.0,
                                        volume=1_000_000, _basis_as_of="2026-09-08") for r in hist.rows])
    merged = CompositeBarAdapter(hist2, live).history("PQX")                 # same basis date -> compatible
    assert len(merged) == 20 and {r["_source_adapter"] for r in merged} == {"snapshot", "live"}
    # different/unknown bases but PROVEN no split between them -> also valid
    merged2 = CompositeBarAdapter(hist, live, ca_source=StaticCorporateActionSource(
        [make_dividend_event("PQX", v2cal.add_sessions(last_hist, 1), "0.10")]),
        today=lambda: date(2026, 9, 9)).history("PQX")
    assert len(merged2) == 20
    # a split BEFORE the snapshot's last row (already in both bases) is not in the ambiguity interval
    old = make_split_event("PQX", v2cal.add_sessions(last_hist, -3), 10, 1)
    assert len(CompositeBarAdapter(hist, live, ca_source=StaticCorporateActionSource([old]),
                                   today=lambda: date(2026, 9, 9)).history("PQX")) == 20
    # a composite whose two sources do NOT overlap-mix (only one contributes) is untouched
    only_live = CompositeBarAdapter(MemAdapter("snapshot", []), live).history("PQX")
    assert len(only_live) == 6 and {r["_source_adapter"] for r in only_live} == {"live"}


# =========================================================================== #
# 25-26: dividend policy
# =========================================================================== #
def test_25_26_dividend_is_observed_never_credited_and_never_double_counted(tmp_path):
    w = _World(tmp_path)
    div = make_dividend_event("PQX", v2cal.add_sessions(ENTRY, 3), "0.50")
    w.add_exit_bar(TARGET, 27.0, basis="2026-09-23")
    cash_before = w.store.cash()
    pipeline.sweep_corporate_actions(store=w.store, as_of=v2cal.add_sessions(ENTRY, 5), guard=guard_with(div))
    assert w.store.cash() == cash_before                                     # 26: no dividend cash mutation
    trail = w.store.position_action_trail(w.pos["position_id"])
    assert [(t["kind"], t["status"]) for t in trail] == [("CASH_DIVIDEND", "DIVIDEND_OBSERVED_NOT_CREDITED")]
    assert w.store.effective_shares_exact(w.pos["position_id"]) == 400       # shares unchanged
    w.settle(guard_with(div))
    pos = w.position()
    assert pos["realized_pnl_usd"] == pytest.approx(400 * 27.0 - 10_000.0)   # PRICE RETURN only
    assert w.store.cash() == pytest.approx(300_000.0 + pos["realized_pnl_usd"])
    assert [t["action"] for t in w.store.trades()] == ["BUY", "SELL"]        # no dividend trade/credit row


# =========================================================================== #
# 28-32: strategy integrity, sizing, idempotent settlement, recovery
# =========================================================================== #
def test_28_29_strategy_thresholds_and_fingerprint_unchanged():
    cfg = V2Config()
    assert (cfg.min_distinct_owners, cfg.hold_trading_days, cfg.entry_offset_sessions,
            cfg.liquidity_lookback_sessions, cfg.liquidity_min_median_dollar_volume,
            cfg.liquidity_min_close, cfg.exit_fallforward_max_sessions,
            cfg.max_entry_staleness_sessions) == (2, 10, 1, 20, 5_000_000.0, 5.0, 5, 3)
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "research" / "scripts" / "task112_v2_release_fingerprint.py"
    spec = importlib.util.spec_from_file_location("pq2a_fp", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.v2_release_fingerprint()["fingerprint"] == "e2acf6454789217e"


def test_30_new_entry_sizing_stays_whole_share_and_reverse_split_does_not_change_it(tmp_path):
    s = size_whole_shares_fee_inclusive(price=25.0, allocation_usd=10_000.0, available_cash=300_000.0)
    assert (s.shares, s.entry_total) == (400, 10_000.0)
    s2 = size_whole_shares_fee_inclusive(price=30.0, allocation_usd=10_000.0, available_cash=300_000.0)
    assert s2.shares == 333                                       # truncated, never rounded up
    w = _World(tmp_path, entry_open=30.0)
    pipeline.sweep_corporate_actions(store=w.store, as_of=v2cal.add_sessions(ENTRY, 5),
                                     guard=guard_with(make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 1, 10)))
    assert w.position()["shares"] == 333.0                        # ENTRY quantity stays whole & untouched
    assert float(w.store.effective_shares_exact(w.pos["position_id"])) == pytest.approx(33.3)


def test_31_settlement_idempotency_still_holds_with_a_split(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 2.7, basis="2026-09-23")
    g = guard_with(SPLIT_10_1)
    w.settle(g)
    cash1, trades1 = w.store.cash(), w.store.trades()
    w.settle(g)                                                   # a second run finds nothing due
    out = paper.close_position(w.store, w.pos, exit_price=2.7, exit_session=TARGET, config=CFG)
    assert out.settled is False                                   # stale-snapshot duplicate is a no-op
    assert w.store.cash() == cash1 and w.store.trades() == trades1
    assert len(w.store.position_action_trail(w.pos["position_id"])) == 1


def test_32_session_10_plus_5_recovery_is_unchanged_with_a_guard(tmp_path):
    ff2 = v2cal.add_sessions(TARGET, 2)
    w = _World(tmp_path)
    w.add_exit_bar(ff2, 28.0, basis=ff2.isoformat())
    w.settle(guard_with(), as_of=ff2)
    pos = w.position()
    assert pos["status"] == "CLOSED" and pos["exit_session"] == ff2.isoformat()
    w2 = _World(tmp_path, name="w2")
    too_late = v2cal.add_sessions(TARGET, 6)
    w2.add_exit_bar(too_late, 28.0, basis=too_late.isoformat())
    w2.settle(guard_with(), as_of=too_late)
    assert w2.position()["status"] == "EXIT_UNRESOLVED"
    assert [t["action"] for t in w2.store.trades()] == ["BUY"]


# =========================================================================== #
# source adapters (no network): Alpaca + yfinance parsing against the REAL
# payload shapes recorded in the PQ-2A probe evidence
# =========================================================================== #
def test_alpaca_source_parses_real_payload_shapes_and_marks_outage_unavailable():
    payload = {"corporate_actions": {
        "forward_splits": [{"id": "50199fac", "symbol": "NVDA", "ex_date": "2024-06-10", "new_rate": 10, "old_rate": 1}],
        "reverse_splits": [{"id": "f0b65529", "symbol": "GNS", "ex_date": "2024-08-16", "new_rate": 1, "old_rate": 10}],
        "cash_dividends": [{"id": "d1", "symbol": "NVDA", "ex_date": "2024-06-11", "rate": 0.01, "special": False}],
        "spin_offs": [{"id": "s1", "source_symbol": "GE", "ex_date": "2023-01-04", "new_rate": 0.33333}],
        "name_changes": [{"id": "n1", "old_symbol": "DWAC", "new_symbol": "DJT", "process_date": "2024-03-26"}],
    }, "next_page_token": None}
    src = ca.AlpacaCorporateActionSource(key_id="k", secret="s", http_get=lambda url, params: payload)
    res = src.fetch("NVDA", date(2024, 6, 1), date(2024, 6, 30))
    kinds = {e.kind for e in res.events}
    assert res.ok and kinds == {ca.KIND_FORWARD_SPLIT, ca.KIND_REVERSE_SPLIT, ca.KIND_CASH_DIVIDEND, ca.KIND_UNSUPPORTED}
    fwd = next(e for e in res.events if e.kind == ca.KIND_FORWARD_SPLIT)
    rev = next(e for e in res.events if e.kind == ca.KIND_REVERSE_SPLIT)
    assert (fwd.ratio, rev.ratio) == (Fraction(10), Fraction(1, 10))
    assert fwd.provider_id == "50199fac" and fwd.source == "alpaca:v1/corporate-actions"
    # provider fault / bad shape are UNAVAILABLE, never "no actions"
    def boom(url, params):
        raise TimeoutError("timeout")
    assert not ca.AlpacaCorporateActionSource(key_id="k", secret="s", http_get=boom).fetch(
        "NVDA", date(2024, 6, 1), date(2024, 6, 30)).ok
    assert not ca.AlpacaCorporateActionSource(key_id="k", secret="s", http_get=lambda u, p: {"x": 1}).fetch(
        "NVDA", date(2024, 6, 1), date(2024, 6, 30)).ok


def test_alpaca_source_never_calls_a_broker_endpoint():
    seen = []
    def get(url, params):
        seen.append(url)
        return {"corporate_actions": {}, "next_page_token": None}
    ca.AlpacaCorporateActionSource(key_id="k", secret="s", http_get=get).fetch("X", date(2026, 1, 1), date(2026, 1, 5))
    assert seen == ["https://data.alpaca.markets/v1/corporate-actions"]


def test_yfinance_witness_agrees_with_alpaca_on_a_split_and_conflicts_when_it_does_not():
    import pandas as pd
    class T:
        def __init__(self, splits):
            self.splits = pd.Series(splits); self.dividends = pd.Series(dtype=float)
    yf = ca.YFinanceCorporateActionSource(ticker_factory=lambda s: T({pd.Timestamp("2024-06-10"): 10.0}))
    alp = StaticCorporateActionSource([make_split_event("NVDA", date(2024, 6, 10), 10, 1)], name="alpaca")
    ok = ca.combine_sources([alp.fetch("NVDA", date(2024, 6, 1), date(2024, 6, 30)),
                             yf.fetch("NVDA", date(2024, 6, 1), date(2024, 6, 30))])
    assert ok.ok and not ok.conflicts
    yf_bad = ca.YFinanceCorporateActionSource(ticker_factory=lambda s: T({pd.Timestamp("2024-06-10"): 5.0}))
    bad = ca.combine_sources([alp.fetch("NVDA", date(2024, 6, 1), date(2024, 6, 30)),
                              yf_bad.fetch("NVDA", date(2024, 6, 1), date(2024, 6, 30))])
    assert bad.conflicts


# =========================================================================== #
# service / entry-point wiring
# =========================================================================== #
def test_service_sweeps_settles_and_marks_on_economic_shares(tmp_path):
    from talonx_v2.service import V2Service
    bars = tmp_path / "bars"
    bars.mkdir()
    import csv
    mid = v2cal.add_sessions(ENTRY, 5)
    with open(bars / "PQX.csv", "w", newline="") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["date", "open", "close", "volume"])
        wtr.writerow([mid.isoformat(), 2.6, 2.7, 1_000_000])
        wtr.writerow([TARGET.isoformat(), 2.65, 2.7, 1_000_000])
    guard = CorporateActionGuard(StaticCorporateActionSource([SPLIT_10_1]))
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "svc.db"), starting_cash_usd=300_000.0),
                    bar_dirs=[bars], status_path=str(tmp_path / "s.json"), corporate_actions=guard)
    # a position opened on a KNOWN basis, as a live adapter would record it
    prov = {"provider": "live", "field": "open", "session": ENTRY.isoformat(), "basis_as_of": ENTRY_BASIS}
    svc.store.insert_open_position(episode_id="e", symbol="PQX", issuer_cik="", entry_session=ENTRY,
                                   target_exit_session=TARGET, entry_price=25.0, shares=400, position_cost=10_000.0,
                                   price_provenance=prov)
    svc.store.set_cash(290_000.0)
    svc._phase_corporate_actions(mid)
    marks = svc._phase_mark(mid)
    assert marks[0]["economic_shares"] == 4000.0
    assert marks[0]["unrealized_pnl_usd"] == pytest.approx(4000 * 2.7 - 10_000.0)      # +$800, not -$8,900
    assert svc._last_ca_sweep[0]["status"] == "ADJUSTED"


def test_live_entry_point_refuses_to_start_without_a_corporate_action_source(tmp_path, monkeypatch):
    from talonx_v2 import run
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(run, "_load_env", lambda *a, **k: None, raising=False)
    with pytest.raises(SystemExit) as ei:
        run.main(["--mode", "live", "--db", str(tmp_path / "x.db"), "--once", "--as-of", "2026-09-08"])
    assert "corporate-action source" in str(ei.value)


def test_guard_caches_sweep_lookups_but_settlement_is_always_fresh(tmp_path):
    calls = []
    class Counting(StaticCorporateActionSource):
        def fetch(self, symbol, start, end):
            calls.append((symbol, start, end))
            return super().fetch(symbol, start, end)
    g = CorporateActionGuard(Counting([]), cache_ttl_s=900.0, clock=lambda: 1000.0)
    w = _World(tmp_path)
    asof = v2cal.add_sessions(ENTRY, 3)
    for _ in range(3):
        pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=g)
    assert len(calls) == 1                                       # sweeps hit the cache
    w.add_exit_bar(TARGET, 27.0, basis="2026-09-23")
    w.settle(g)
    assert len(calls) == 2                                       # settlement never uses the cache
    down = CorporateActionGuard(StaticCorporateActionSource(status="UNAVAILABLE"), clock=lambda: 1000.0)
    assert not down.fetch("PQX", ENTRY, TARGET).ok and not down._cache      # outages are never cached
