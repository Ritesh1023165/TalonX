"""
Task 131 Remediation Directive 4 -- atomic multi-table paper-ledger
mutations (``V2Store.transaction()``, used by ``talonx_v2.paper.
enter_position``/``close_position``) and the hard admission gate at
intent-creation time (``V2Service._capacity_rejection_reason``).

Proves, under real failure conditions, using a real temporary SQLite
file (not mocks): a crash partway through a multi-write sequence leaves
NOTHING committed -- never a position without its cash debit, never a
debit without a trade record.
"""
from __future__ import annotations

from datetime import date

import pytest

from talonx_v2 import paper
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.store import V2Store


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id="sig1", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


# --------------------------------------------------------------------- #
# V2Store.transaction() -- generic atomicity
# --------------------------------------------------------------------- #
def test_transaction_commits_everything_together(tmp_path):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    with store.transaction():
        store.set_cash(250_000.0)
        store.set_cooldown("AAA", date(2026, 9, 10))
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.cash() == 250_000.0
    assert fresh.cooldown_until("AAA") == date(2026, 9, 10)


def test_transaction_rolls_back_nothing_partial_on_exception(tmp_path):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.set_cash(1_000.0)          # would-be first write
            raise RuntimeError("simulated crash mid-transaction")
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.cash() == 300_000.0        # the partial cash write never committed


def test_transaction_is_not_reentrant_across_two_blocks(tmp_path):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    with store.transaction():
        with pytest.raises(RuntimeError):
            with store.transaction():
                pass


# --------------------------------------------------------------------- #
# paper.enter_position / close_position -- real atomicity under failure
# --------------------------------------------------------------------- #
def test_enter_position_leaves_nothing_partial_if_append_trade_fails(tmp_path, monkeypatch):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0)

    real_append_trade = store.append_trade

    def _boom(*a, **k):
        raise RuntimeError("simulated crash between cash debit and trade record")
    monkeypatch.setattr(store, "append_trade", _boom)

    with pytest.raises(RuntimeError):
        paper.enter_position(store, _decision(), entry_price=100.0,
                             entry_session=date(2026, 9, 8), config=cfg)

    # a genuinely fresh connection against the same file -- nothing
    # partial survives: no position, cash untouched, no disposition.
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.all_positions() == []
    assert fresh.cash() == 300_000.0
    assert fresh.episode_disposition("ep1") is None
    assert fresh.trades() == []


def test_enter_position_commits_all_four_writes_together_on_success(tmp_path):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0)
    outcome = paper.enter_position(store, _decision(), entry_price=100.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered is True
    fresh = V2Store(str(tmp_path / "v.db"))
    assert len(fresh.all_positions()) == 1
    assert fresh.cash() == 290_000.0
    assert len(fresh.trades()) == 1
    assert fresh.episode_disposition("ep1") == "ENTERED"


def test_close_position_leaves_nothing_partial_if_set_cooldown_fails(tmp_path, monkeypatch):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0)
    paper.enter_position(store, _decision(), entry_price=100.0,
                         entry_session=date(2026, 9, 8), config=cfg)
    pos = store.all_positions()[0]
    cash_before_close = store.cash()

    def _boom(*a, **k):
        raise RuntimeError("simulated crash before cooldown write")
    monkeypatch.setattr(store, "set_cooldown", _boom)

    with pytest.raises(RuntimeError):
        paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)

    fresh = V2Store(str(tmp_path / "v.db"))
    # nothing from the close sequence committed -- position still OPEN,
    # cash unchanged, no SELL trade, no cooldown.
    assert fresh.all_positions()[0]["status"] == "OPEN"
    assert fresh.cash() == cash_before_close
    assert [t["action"] for t in fresh.trades()] == ["BUY"]
    assert fresh.cooldown_until("AAA") is None


# --------------------------------------------------------------------- #
# Hard admission gate at intent CREATION time
# --------------------------------------------------------------------- #
def test_intent_creation_rejected_when_cash_would_be_over_reserved(tmp_path):
    from talonx_v2.service import V2Service
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=15_000.0,
                   per_position_allocation_usd=10_000.0)
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    # first intent reserves $10,000 of the $15,000 starting cash --
    # leaving only $5,000 unreserved, below the $10,000 requirement.
    store = svc.store
    reason1 = svc._capacity_rejection_reason()
    assert reason1 is None  # nothing reserved yet -- room for one
    store.upsert_entry_intent(
        type("Ep", (), {"episode_id": "e1", "symbol": "AAA", "issuer_cik": "x",
                        "eligible_entry_session": date(2026, 9, 8),
                        "activation_filing_date": date(2026, 9, 4)})(),
        _decision(), type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})(),
        horizon=10, planned_exit_session="2026-09-22")
    reason2 = svc._capacity_rejection_reason()
    assert reason2 is not None
    assert "unreserved cash" in reason2


def test_intent_creation_rejected_at_the_21st_competing_slot(tmp_path):
    from talonx_v2.service import V2Service
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=10_000_000.0,
                   per_position_allocation_usd=10_000.0)
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    store = svc.store
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    for i in range(20):
        ep = type("Ep", (), {"episode_id": f"e{i}", "symbol": f"S{i}", "issuer_cik": "x",
                             "eligible_entry_session": date(2026, 9, 8),
                             "activation_filing_date": date(2026, 9, 4)})()
        assert svc._capacity_rejection_reason() is None
        store.upsert_entry_intent(ep, _decision(episode_id=f"e{i}", symbol=f"S{i}"),
                                  liq, horizon=10, planned_exit_session="2026-09-22")
    reason = svc._capacity_rejection_reason()
    assert reason is not None
    assert "capacity slots" in reason
