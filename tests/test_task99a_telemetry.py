"""Task 99A S5 -- forward-outcome telemetry. Focused areas: creation, pending
state, +30m/+60m/EOD updates, +1D pending, bullish/bearish direction
correctness, no short P&L, idempotent update, admission attribution, restart
safety. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_signals.schemas import (
    AlertDirection, DirectionalAlert, MarketSession, SetupEvidence, TradeGateStatus, make_alert_id,
)
from talonx_signals.telemetry import (
    ForwardOutcomeRecorder, ForwardOutcomeStore, classify_admission,
)

T0 = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = ForwardOutcomeStore(tmp_path / "forward_outcomes.db")
    yield s
    s.close()


def _alert(direction=AlertDirection.BULLISH, price=100.0):
    return DirectionalAlert(
        alert_id=make_alert_id(symbol="AAPL", direction=direction.value, setup_type="macd_bullish_cross",
                               session="regular", episode_ts=T0),
        symbol="AAPL", direction=direction, profile="FROZEN_CONTROL", setup_type="macd_bullish_cross",
        setup_score=1, session=MarketSession.REGULAR, price=price,
        trade_gate_status=TradeGateStatus.WOULD_REJECT, trade_gate_reject_reason="LOW_CONFLUENCE",
        evidence=SetupEvidence(atr_pct=0.12), bar_timestamp=T0, generated_at=T0,
    )


def test_open_creates_pending_row(store):
    rec = ForwardOutcomeRecorder(store)
    obs_id = rec.open_from_directional(_alert())
    row = store._get(obs_id)
    assert row["status"] == "PENDING_30M"
    assert row["reference_price"] == 100.0
    assert row["r_30m"] is None and row["r_eod"] is None


def test_open_is_idempotent(store):
    rec = ForwardOutcomeRecorder(store)
    a = _alert()
    id1 = rec.open_from_directional(a)
    id2 = rec.open_from_directional(a)
    assert id1 == id2
    assert len(store.all_rows()) == 1


def test_30m_and_60m_resolve_when_window_elapses(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_price(obs, T0 + timedelta(minutes=10), 101.0)   # too early
    assert store._get(obs)["r_30m"] is None
    rec.on_price(obs, T0 + timedelta(minutes=31), 102.0)   # +2%
    row = store._get(obs)
    assert row["r_30m"] == pytest.approx(2.0)
    assert row["hit_30m"] == 1                              # bullish + up = favourable
    assert row["status"] == "PENDING_60M"
    rec.on_price(obs, T0 + timedelta(minutes=61), 103.0)
    assert store._get(obs)["r_60m"] == pytest.approx(3.0)
    assert store._get(obs)["status"] == "PENDING_EOD"


def test_eod_then_1d_pending_then_complete(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_price(obs, T0 + timedelta(minutes=31), 101.0)
    rec.on_price(obs, T0 + timedelta(minutes=61), 101.0)
    rec.resolve_eod(obs, 104.0)
    row = store._get(obs)
    assert row["r_eod"] == pytest.approx(4.0)
    assert row["status"] == "PENDING_1D"          # +1D can't be known today
    assert obs in [r["obs_id"] for r in store.pending_backfill()]
    rec.resolve_next_day(obs, 99.0)
    row = store._get(obs)
    assert row["r_1d"] == pytest.approx(-1.0)
    assert row["hit_1d"] == 0
    assert row["status"] == "COMPLETE"


def test_bearish_direction_correctness_no_short_pnl(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(direction=AlertDirection.BEARISH, price=100.0))
    rec.on_price(obs, T0 + timedelta(minutes=31), 98.0)    # -2% -> favourable for BEARISH
    row = store._get(obs)
    assert row["r_30m"] == pytest.approx(-2.0)
    assert row["hit_30m"] == 1
    # BEARISH row carries no trade economics at all -> no simulated short P&L
    assert row["kind"] == "directional"
    assert row["gross_pnl"] is None and row["net_pnl"] is None and row["r_multiple"] is None


def test_horizon_resolution_is_idempotent(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.resolve_eod(obs, 104.0)
    rec.resolve_eod(obs, 999.0)   # second call ignored
    assert store._get(obs)["r_eod"] == pytest.approx(4.0)


def test_mfe_mae_track_running_extremes(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    for mins, px in ((5, 103.0), (10, 96.0), (20, 101.0)):
        rec.on_price(obs, T0 + timedelta(minutes=mins), px)
    row = store._get(obs)
    assert row["mfe"] == pytest.approx(3.0)
    assert row["mae"] == pytest.approx(-4.0)


def test_trade_observation_records_economics_and_attribution(store):
    rec = ForwardOutcomeRecorder(store)
    trade = dict(trade_id="Xdeadbeef00000001", symbol="AAPL", profile="EXPERIMENTAL_RELAXED_V1",
                 entry=100.0, stop=98.0, target=104.0, quantity=25, setup_score=1,
                 risk_reward_ratio=1.1, opened_at=T0.isoformat())
    obs = rec.open_from_trade(trade, atr_pct=0.12)
    row = store._get(obs)
    assert row["admitted_by"] == "multiple:volatility+confluence+rr"
    rec.close_trade(obs, exit_price=103.0, exit_reason="target_exit", gross_pnl=75.0,
                    est_costs=3.0, net_pnl=72.0, r_multiple=1.44, mfe=4.0, mae=-1.0)
    row = store._get(obs)
    assert row["net_pnl"] == 72.0 and row["r_multiple"] == 1.44


def test_classify_admission_variants():
    assert classify_admission(atr_pct=0.5, confluence_score=3, risk_reward_ratio=2.0) == "would_also_pass_control"
    assert classify_admission(atr_pct=0.12, confluence_score=3, risk_reward_ratio=2.0) == "relaxed_volatility"
    assert classify_admission(atr_pct=0.5, confluence_score=1, risk_reward_ratio=2.0) == "relaxed_confluence"
    assert classify_admission(atr_pct=0.5, confluence_score=3, risk_reward_ratio=1.1) == "relaxed_rr"
    assert classify_admission(atr_pct=0.1, confluence_score=1, risk_reward_ratio=2.0).startswith("multiple:")


def test_restart_safety_store_reopens_with_pending_rows(tmp_path):
    path = tmp_path / "fo.db"
    s1 = ForwardOutcomeStore(path)
    rec = ForwardOutcomeRecorder(s1)
    obs = rec.open_from_directional(_alert())
    rec.resolve_eod(obs, 104.0)
    s1.close()

    s2 = ForwardOutcomeStore(path)
    pend = s2.pending_backfill()
    assert len(pend) == 1 and pend[0]["obs_id"] == obs
    ForwardOutcomeRecorder(s2).resolve_next_day(obs, 105.0)
    assert s2._get(obs)["status"] == "COMPLETE"
    s2.close()
