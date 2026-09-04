"""Task 99A S3 -- DirectionalAlertEngine. Focused test areas: bullish alert,
bearish alert, gate-independent informational alert, deterministic dedup, no
short execution, no production mutation, session distinction, control vs
experimental input equality. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import IndicatorSnapshot
from talonx_quant.schemas import QuantSignal
from talonx_signals.directional import DirectionalAlertEngine, build_evidence
from talonx_signals.relaxed_profile import assert_control_profile_unchanged
from talonx_signals.schemas import AlertDirection, MarketSession, TradeGateStatus

RTH = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)      # 11:00 ET -> regular
PRE = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)      # 08:00 ET -> pre_market
NOW = datetime(2026, 8, 7, 15, 0, 30, tzinfo=timezone.utc)


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        price=100.0, bar_timestamp=RTH,
        rsi=None, rsi_prev=None,
        macd=None, macd_signal_line=None, macd_prev=None, macd_signal_line_prev=None,
        sma_fast=None, sma_slow=None, sma_fast_prev=None, sma_slow_prev=None,
        volume=None, volume_avg=None, volume_surge_ratio=None, dollar_volume_avg=None,
        atr=1.0, bar_true_range=2.0,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _macd_bullish(**kw) -> IndicatorSnapshot:
    return _snapshot(macd_prev=-0.5, macd_signal_line_prev=0.0, macd=0.5, macd_signal_line=0.0, **kw)


def _macd_bearish(**kw) -> IndicatorSnapshot:
    return _snapshot(macd_prev=0.5, macd_signal_line_prev=0.0, macd=-0.5, macd_signal_line=0.0, **kw)


# ---------------------------------------------------------------------------

def test_bullish_directional_alert_emitted():
    eng = DirectionalAlertEngine()
    alerts = eng.evaluate("AAPL", _macd_bullish(), now=NOW)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.direction == AlertDirection.BULLISH
    assert a.symbol == "AAPL"
    assert a.setup_type == "macd_bullish_cross"
    assert a.setup_score is not None
    assert a.setup_score_label == "setup_score"
    assert a.session == MarketSession.REGULAR
    assert a.price == 100.0


def test_bearish_directional_alert_emitted_but_carries_no_order_semantics():
    eng = DirectionalAlertEngine()
    alerts = eng.evaluate("MSFT", _macd_bearish(), now=NOW)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.direction == AlertDirection.BEARISH
    # A DirectionalAlert is informational only -- it has no order/quantity/side
    # fields at all, so it cannot represent a short (or any) execution.
    dumped = a.model_dump()
    for forbidden in ("order_type", "side", "quantity", "qty", "short", "sell"):
        assert forbidden not in dumped


def test_informational_alert_is_independent_of_trade_gate():
    """A setup that the trade gate WOULD reject still produces the alert."""
    eng = DirectionalAlertEngine()

    def always_reject(sig: QuantSignal, snap: IndicatorSnapshot):
        return TradeGateStatus.WOULD_REJECT, "LOW_CONFLUENCE"

    alerts = eng.evaluate("NVDA", _macd_bullish(), now=NOW, gate_probe=always_reject)
    assert len(alerts) == 1
    assert alerts[0].trade_gate_status == TradeGateStatus.WOULD_REJECT
    assert alerts[0].trade_gate_reject_reason == "LOW_CONFLUENCE"
    # low setup_score (no confluence legs) -- still emitted.
    assert alerts[0].setup_score == 0


def test_low_confluence_setup_still_emits_without_a_probe():
    eng = DirectionalAlertEngine()
    # bare MACD cross, no RSI extreme, no volume surge -> confluence 0 under LEGACY
    alerts = eng.evaluate("NVDA", _macd_bullish(), now=NOW)
    assert len(alerts) == 1
    assert alerts[0].setup_score == 0
    assert alerts[0].trade_gate_status == TradeGateStatus.NOT_EVALUATED


def test_dedup_suppresses_recross_within_cooldown_and_id_is_deterministic():
    eng = DirectionalAlertEngine(informational_cooldown_seconds=900)
    first = eng.evaluate("AAPL", _macd_bullish(bar_timestamp=RTH), now=NOW)
    second = eng.evaluate(
        "AAPL", _macd_bullish(bar_timestamp=RTH + timedelta(minutes=3)),
        now=NOW + timedelta(minutes=3),
    )
    assert len(first) == 1
    assert second == []  # re-cross of the same setup inside the window -> suppressed

    # deterministic id: same episode minute -> same alert_id from a fresh engine
    again = DirectionalAlertEngine().evaluate("AAPL", _macd_bullish(bar_timestamp=RTH), now=NOW)
    assert again[0].alert_id == first[0].alert_id
    assert first[0].alert_id.startswith("D")


def test_dedup_allows_new_alert_after_cooldown_expires():
    eng = DirectionalAlertEngine(informational_cooldown_seconds=300)
    a1 = eng.evaluate("AAPL", _macd_bullish(bar_timestamp=RTH), now=NOW)
    a2 = eng.evaluate(
        "AAPL", _macd_bullish(bar_timestamp=RTH + timedelta(minutes=10)),
        now=NOW + timedelta(minutes=10),
    )
    assert len(a1) == 1 and len(a2) == 1
    assert a1[0].alert_id != a2[0].alert_id


def test_dedup_bypassed_by_a_real_price_move():
    eng = DirectionalAlertEngine(informational_cooldown_seconds=900, retrigger_price_delta_pct=1.0)
    eng.evaluate("AAPL", _macd_bullish(price=100.0, bar_timestamp=RTH), now=NOW)
    moved = eng.evaluate(
        "AAPL", _macd_bullish(price=102.0, bar_timestamp=RTH + timedelta(minutes=2)),
        now=NOW + timedelta(minutes=2),
    )
    assert len(moved) == 1


def test_no_production_mutation_after_running_engine():
    eng = DirectionalAlertEngine()
    eng.evaluate("AAPL", _macd_bullish(), now=NOW)
    eng.evaluate("MSFT", _macd_bearish(), now=NOW)
    assert_control_profile_unchanged()
    # the engine's own config is a pristine default
    assert eng.config == QuantConfig()


def test_session_distinction_premarket_vs_regular():
    eng = DirectionalAlertEngine()
    # RSI curl needs volume under LEGACY; use it in both sessions.
    rth = eng.evaluate(
        "AAPL", _snapshot(bar_timestamp=RTH, rsi_prev=28.0, rsi=32.0, volume_surge_ratio=3.0),
        now=NOW,
    )
    pre = eng.evaluate(
        "AAPL", _snapshot(bar_timestamp=PRE, rsi_prev=28.0, rsi=32.0, volume_surge_ratio=5.0),
        now=NOW,
    )
    assert rth and rth[0].session == MarketSession.REGULAR
    assert pre and pre[0].session == MarketSession.PRE_MARKET
    # distinct episode keys / ids by session
    assert rth[0].alert_id != pre[0].alert_id


def test_control_and_experimental_engines_agree_on_the_same_bar():
    """S3 / S7.2 -- fed the SAME snapshot, the two profiles' informational
    reads are identical except for the profile label (evaluate_signals is
    gate-free; the relaxed thresholds only affect the downstream trade gate,
    not the directional read)."""
    snap = _macd_bullish(rsi_prev=28.0, rsi=32.0, volume_surge_ratio=3.0)
    control = DirectionalAlertEngine(config=QuantConfig()).evaluate(
        "AAPL", snap, now=NOW, profile="FROZEN_CONTROL",
    )
    from talonx_signals import ExperimentalConfig, build_experimental_quant_config

    exp_cfg = build_experimental_quant_config(ExperimentalConfig())
    experimental = DirectionalAlertEngine(config=exp_cfg).evaluate(
        "AAPL", snap, now=NOW, profile="EXPERIMENTAL_RELAXED_V1",
    )
    assert [x.alert_id for x in control] == [x.alert_id for x in experimental]
    assert [x.setup_type for x in control] == [x.setup_type for x in experimental]
    assert [x.setup_score for x in control] == [x.setup_score for x in experimental]
    assert control[0].profile == "FROZEN_CONTROL"
    assert experimental[0].profile == "EXPERIMENTAL_RELAXED_V1"


def test_evidence_is_carried_from_the_quant_signal():
    eng = DirectionalAlertEngine()
    snap = _macd_bullish(rsi=25.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=1.0, price=100.0)
    a = eng.evaluate("AAPL", snap, now=NOW)[0]
    assert a.evidence.rsi == 25.0
    assert a.evidence.volume_surge_ratio == 3.0
    assert a.evidence.atr == 1.0
    assert a.evidence.atr_pct == pytest.approx(1.0)  # 1.0 / 100 * 100
    assert a.evidence.macd_cross == "bullish"


def test_from_wire_builds_alert_from_quant_signal_payload():
    eng = DirectionalAlertEngine()
    payload = {
        "ticker": "AAPL", "direction": "bullish", "signal_type": "macd_bullish_cross",
        "session": "regular", "price": 100.0, "confluence_score": 1, "atr": 1.0,
        "risk_reward_ratio": 1.1, "stop_price": 98.0, "target_price": 104.0,
        "message": "MACD crossed above", "bar_timestamp": RTH.isoformat(),
    }
    a = eng.from_wire(payload, profile="EXPERIMENTAL_RELAXED_V1")
    assert a is not None
    assert a.direction == AlertDirection.BULLISH
    assert a.profile == "EXPERIMENTAL_RELAXED_V1"
    assert a.setup_score == 1
    assert a.evidence.atr_pct == pytest.approx(1.0)
    assert a.alert_id.startswith("D")


def test_from_wire_builds_alert_from_rejection_payload():
    eng = DirectionalAlertEngine()
    rej = {
        "ticker": "MSFT", "direction": "bearish", "reason": "LOW_CONFLUENCE",
        "gate": "confluence_gate", "price": 50.0, "session": "regular",
        "confluence_score": 0, "rejected_at": RTH.isoformat(),
    }
    a = eng.from_wire(rej, profile="FROZEN_CONTROL", trade_gate_status=TradeGateStatus.WOULD_REJECT,
                      trade_gate_reject_reason="LOW_CONFLUENCE")
    assert a and a.direction == AlertDirection.BEARISH
    assert a.trade_gate_status == TradeGateStatus.WOULD_REJECT
    assert a.trade_gate_reject_reason == "LOW_CONFLUENCE"


def test_from_wire_rejects_non_directional_payload():
    eng = DirectionalAlertEngine()
    assert eng.from_wire({"ticker": "AAPL", "direction": "neutral", "price": 1.0}) is None
    assert eng.from_wire({"direction": "bullish", "price": 1.0}) is None  # no symbol


def test_catalyst_lookup_failure_never_blocks_an_alert():
    def boom(sym, ts):
        raise RuntimeError("intelligence store down")

    eng = DirectionalAlertEngine(catalyst_lookup=boom)
    alerts = eng.evaluate("AAPL", _macd_bullish(), now=NOW)
    assert len(alerts) == 1
    assert alerts[0].evidence.nearby_catalyst is None
