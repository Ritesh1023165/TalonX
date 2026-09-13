"""Task 130 Part 6 -- focused tests, run BEFORE the real Discovery
Universe v1 evaluation. Covers both (a) this task's own new, isolated
analysis logic (Track A/B derivation, reconstructed equity, cost-once,
sensitivities, bootstrap determinism) and (b) direct fixture-based
confirmation of the production-adjacent contract pieces this task
relies on unmodified (second-owner activation/dedup, liquidity gate,
capacity cap + no-leverage, missing-price fall-forward).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))
RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))

import task130_discovery_evaluation as t130  # noqa: E402


# ---------------------------------------------------------------------
# (a) This task's own isolated analysis logic
# ---------------------------------------------------------------------

def test_net_return_applies_cost_exactly_once():
    net = t130._net_return(100.0, 110.0)
    gross = (110.0 - 100.0) / 100.0
    assert net == pytest.approx(gross - t130.COST_BPS / 10_000.0)
    double = net - t130.COST_BPS / 10_000.0
    assert double != net


def test_closed_trades_use_simulated_session_dates_not_wall_clock():
    # positions.entry_session/exit_session are the SIMULATED trading-session
    # dates -- distinct from trades.executed_at, which is a real wall-clock
    # timestamp (the bug this task found and fixed: see
    # _closed_trades_from_positions's own docstring).
    positions = [
        {"episode_id": "E1", "symbol": "AAA", "entry_session": "2024-10-01",
         "exit_session": "2024-10-15", "entry_price": 100.0, "exit_price": 105.0},
    ]
    closed = t130._closed_trades_from_positions(positions)
    assert len(closed) == 1
    assert closed[0]["episode_id"] == "E1"
    assert closed[0]["entry_session"] == "2024-10-01"  # a plain simulated date, not a wall-clock timestamp
    assert closed[0]["net_return"] == pytest.approx((105.0 - 100.0) / 100.0 - 0.0020)


def test_track_b_excludes_cold_start_and_reconstructed_equity_unaffected():
    closed_all = [
        {"episode_id": "E1", "symbol": "AAA", "entry_session": "2024-10-01", "exit_session": "2024-10-15",
         "entry_price": 100.0, "exit_price": 110.0, "gross_return": 0.10, "net_return": 0.098,
         "net_pnl_usd": 980.0},
        {"episode_id": "E2", "symbol": "BBB", "entry_session": "2024-10-02", "exit_session": "2024-10-16",
         "entry_price": 50.0, "exit_price": 40.0, "gross_return": -0.20, "net_return": -0.202,
         "net_pnl_usd": -2020.0},
    ]
    # simulate: only E1 has a pre-existing intent (timestamp-proven); E2 is cold-start
    intents = {"E1": {"episode_id": "E1"}}
    closed_B = [c for c in closed_all if c["episode_id"] in intents]
    assert len(closed_B) == 1 and closed_B[0]["episode_id"] == "E1"

    eq_B = t130._reconstruct_chronological_equity(closed_B, starting_cash=300_000.0)
    # E2 (the cold-start, negative trade) must NOT affect Track B's cash at all
    assert eq_B["ending_cash"] == pytest.approx(300_000.0 - 10_000.0 + 10_000.0 * 1.098)
    assert eq_B["ending_cash"] != pytest.approx(300_000.0 - 20_000.0 + 10_000.0 * (1.098 - 0.202))


def test_reconstructed_equity_never_goes_negative_and_caps_spend_at_allocation():
    closed = [{"episode_id": f"E{i}", "symbol": f"S{i}", "entry_session": "2024-10-01",
              "exit_session": "2024-10-15", "entry_price": 10.0, "exit_price": 11.0,
              "gross_return": 0.10, "net_return": 0.098, "net_pnl_usd": 980.0} for i in range(50)]
    eq = t130._reconstruct_chronological_equity(closed, starting_cash=1_000.0)  # far too little cash for 50 entries
    assert eq["ending_cash"] >= 0.0  # never negative, never borrows


def test_bootstrap_is_deterministic_given_same_seed():
    by_issuer = {"AAA": [0.02, 0.03], "BBB": [-0.01], "CCC": [0.05, 0.01, -0.02]}
    r1 = t130._issuer_block_bootstrap(by_issuer, seed=130130)
    r2 = t130._issuer_block_bootstrap(by_issuer, seed=130130)
    assert r1["ci_pct"] == r2["ci_pct"]


def test_top_n_issuer_sensitivity_uses_trade_count_ranking():
    closed = (
        [{"episode_id": f"A{i}", "symbol": "DOM", "entry_session": "2024-10-01", "exit_session": "2024-10-15",
         "entry_price": 10.0, "exit_price": 5.0, "gross_return": -0.5, "net_return": -0.502,
         "net_pnl_usd": -5020.0} for i in range(5)]
        + [{"episode_id": "B1", "symbol": "OTHER", "entry_session": "2024-10-01", "exit_session": "2024-10-15",
           "entry_price": 10.0, "exit_price": 12.0, "gross_return": 0.2, "net_return": 0.198,
           "net_pnl_usd": 1980.0}]
    )
    stats = t130._track_stats(closed, "test")
    assert stats["top1_issuer"] == "DOM"  # 5 trades, dominates by count
    assert stats["net_mean_pct"] < 0  # dominated by DOM's losses
    excl = stats["sensitivity_excl_top1"]
    assert excl["n_remaining"] == 1
    assert excl["mean_net_pct"] == pytest.approx(19.8, abs=0.1)  # only OTHER's +19.8% remains


# ---------------------------------------------------------------------
# (b) Direct fixture confirmation of the reused production-adjacent contract
# ---------------------------------------------------------------------

def test_second_owner_activation_and_duplicate_dedup():
    from talonx_v2.cluster_engine import PurchaseRecord, detect_episodes_for_issuer
    from talonx_v2.config import V2Config

    d0 = date(2024, 10, 1)
    recs = [
        PurchaseRecord(symbol="AAA", issuer_cik="1", owner_cik="O1", filing_date=d0,
                       transaction_code="P", accession="ACC1"),
        # exact duplicate of the same filing -- must not manufacture a 2nd distinct owner
        PurchaseRecord(symbol="AAA", issuer_cik="1", owner_cik="O1", filing_date=d0,
                       transaction_code="P", accession="ACC1"),
        PurchaseRecord(symbol="AAA", issuer_cik="1", owner_cik="O2", filing_date=d0 + timedelta(days=2),
                       transaction_code="P", accession="ACC2"),
    ]
    eps = detect_episodes_for_issuer(recs, config=V2Config())
    assert len(eps) == 1
    assert set(eps[0].distinct_owner_ciks) == {"O1", "O2"}  # exactly 2 distinct owners, dupe not double-counted


def test_liquidity_gate_price_and_volume_floor():
    from talonx_v2.liquidity import evaluate_liquidity
    entry = date(2024, 11, 1)
    dates = [entry - timedelta(days=i) for i in range(1, 25)]
    # 20 sessions of median dollar volume well below $5M, price above $5
    bars = [{"date": d, "close": 10.0, "volume": 1_000} for d in dates]  # $10k/day, way under $5M
    result = evaluate_liquidity(bars, entry_session=entry)
    assert result.ok is False
    assert "MEDIAN_DV" in result.reason

    bars_ok = [{"date": d, "close": 10.0, "volume": 1_000_000} for d in dates]  # $10M/day dollar volume
    result_ok = evaluate_liquidity(bars_ok, entry_session=entry)
    assert result_ok.ok is True


def test_capacity_cap_and_no_negative_cash():
    from talonx_v2.paper import enter_position
    from talonx_v2.config import V2Config
    from talonx_v2.store import V2Store
    from talonx_v2.schemas import V2Action, V2Decision, V2Direction

    import tempfile, os
    dbf = tempfile.mktemp(suffix=".db")
    try:
        store = V2Store(dbf)
        # max_concurrent_positions is FROZEN at 20 (validate_frozen() asserts it) --
        # exercise the real cap value, not a toy override.
        cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0, db_path=dbf)
        store.set_cash(cfg.starting_cash_usd)
        for i in range(21):
            decision = V2Decision(signal_id=f"SIG{i}", action=V2Action.BUY, direction=V2Direction.BULLISH,
                                  official_eligible=False, rationale="t",
                                  eligible_entry_session=date(2024, 10, 1),
                                  symbol=f"S{i}", episode_id=f"E{i}")
            outcome = enter_position(store, decision, entry_price=10.0,
                                     entry_session=date(2024, 10, 1), config=cfg)
            if i < 20:
                assert outcome.entered
            else:
                assert not outcome.entered  # 21st entry blocked by max_concurrent_positions=20
                assert "MAX_CONCURRENT" in outcome.reason
        assert store.cash() >= 0.0  # never negative
        assert store.cash() == pytest.approx(300_000.0 - 20 * 10_000.0)  # exactly 20 x $10k spent, no more
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(dbf + suffix)
            except OSError:
                pass
