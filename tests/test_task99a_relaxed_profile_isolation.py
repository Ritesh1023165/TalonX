"""Task 99A -- EXPERIMENTAL_RELAXED_V1 config isolation + frozen-profile
immutability. Covers focused test areas 1 (frozen profile unchanged), 2
(experimental profile config isolation), and the config-level parts of 3, 11,
17. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from talonx_quant.config import ConfluenceContract, QuantConfig, VolatilityGateMode
from talonx_signals.config import (
    PROFILE_ID,
    RELAXED_OVERRIDES,
    ExperimentalConfig,
    validate_experimental_isolation,
)
from talonx_signals.relaxed_profile import (
    assert_control_profile_unchanged,
    build_experimental_quant_config,
    frozen_quant_config_snapshot,
    relaxation_summary,
)


# ----------------------------------------------------------------------------
# Area 1 -- frozen CONTROL profile is never mutated
# ----------------------------------------------------------------------------

def test_frozen_snapshot_matches_pristine_quantconfig():
    snap = frozen_quant_config_snapshot()
    base = QuantConfig()
    for k, v in snap.items():
        assert getattr(base, k) == v


def test_building_experimental_config_does_not_mutate_frozen_default():
    before = frozen_quant_config_snapshot()
    for _ in range(3):
        build_experimental_quant_config(ExperimentalConfig())
    after = frozen_quant_config_snapshot()
    assert before == after
    # And a brand-new default is still pristine.
    assert_control_profile_unchanged()


def test_assert_control_profile_unchanged_detects_drift(monkeypatch):
    import talonx_signals.relaxed_profile as rp

    monkeypatch.setitem(rp._FROZEN_SNAPSHOT, "confluence_score_min", 999)
    with pytest.raises(AssertionError, match="drifted"):
        assert_control_profile_unchanged()


# ----------------------------------------------------------------------------
# Area 2 -- experimental profile config isolation
# ----------------------------------------------------------------------------

def test_relaxed_overrides_are_exactly_the_three_documented_values():
    assert RELAXED_OVERRIDES == {
        "min_atr_pct": 0.10,
        "confluence_score_min": 1,
        "min_risk_reward_ratio": 1.0,
    }


def test_experimental_quant_config_changes_only_whitelisted_thresholds():
    exp = ExperimentalConfig()
    cfg = build_experimental_quant_config(exp)
    snap = frozen_quant_config_snapshot()

    binding = {
        "redis_url", "market_stream_channel", "signals_channel",
        "rejected_candidates_channel", "news_events_channel",
        "paper_trades_channel", "db_path",
    }
    changed = {
        name for name, v in snap.items()
        if name not in binding and getattr(cfg, name) != v
    }
    assert changed == set(RELAXED_OVERRIDES)
    assert cfg.min_atr_pct == 0.10
    assert cfg.confluence_score_min == 1
    assert cfg.min_risk_reward_ratio == 1.0


def test_experimental_config_preserves_locked_modes():
    cfg = build_experimental_quant_config(ExperimentalConfig())
    assert cfg.volatility_gate_mode == VolatilityGateMode.CURRENT_1M
    assert cfg.confluence_contract == ConfluenceContract.LEGACY


def test_experimental_config_preserves_all_session_and_risk_controls():
    cfg = build_experimental_quant_config(ExperimentalConfig())
    base = QuantConfig()
    for name in (
        "atr_stop_multiplier", "atr_reward_multiplier", "atr_move_multiplier",
        "assumed_stop_loss_pct", "rsi_period", "rsi_oversold", "rsi_overbought",
        "macd_fast", "macd_slow", "macd_signal", "ma_fast_period", "ma_slow_period",
        "volume_avg_period", "volume_surge_ratio_threshold",
        "premarket_volume_surge_ratio_threshold", "min_ma_spread_pct",
        "min_bars_required", "cooldown_seconds", "loss_lockout_seconds",
        "throttle_window_seconds", "throttle_max_signals",
        "max_candidate_age_seconds", "atr_period", "htf_sma_period",
        "htf_bar_interval_minutes", "trend_gate_enabled",
    ):
        assert getattr(cfg, name) == getattr(base, name), name


def test_build_rejects_non_whitelisted_field_change(monkeypatch):
    import talonx_signals.relaxed_profile as rp

    monkeypatch.setitem(rp.RELAXED_OVERRIDES, "rsi_oversold", 40.0)
    with pytest.raises(ValueError, match="outside the relaxed whitelist"):
        build_experimental_quant_config(ExperimentalConfig())


def test_build_rejects_mode_flip(monkeypatch):
    import talonx_signals.relaxed_profile as rp

    monkeypatch.setitem(
        rp.RELAXED_OVERRIDES, "volatility_gate_mode",
        VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL,
    )
    with pytest.raises(ValueError):
        build_experimental_quant_config(ExperimentalConfig())


# ----------------------------------------------------------------------------
# Isolation validator -- fail-closed on every collision
# ----------------------------------------------------------------------------

def test_default_experimental_isolation_passes(monkeypatch):
    for var in (
        "TALONX_REDIS_SIGNALS_CHANNEL", "TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL",
        "TALONX_REDIS_ALERTS_CHANNEL", "TALONX_REDIS_PAPER_TRADES_CHANNEL",
        "TALONX_REDIS_MARKET_CHANNEL", "TALONX_REDIS_NEWS_EVENTS_CHANNEL",
        "TALONX_QUANT_DB_PATH", "TALONX_PAPER_DB",
    ):
        monkeypatch.delenv(var, raising=False)
    ok, detail = validate_experimental_isolation(ExperimentalConfig())
    assert ok, detail


def test_isolation_fails_when_output_channel_overlaps_control():
    exp = replace(ExperimentalConfig(), signals_channel="talonx:signals:quant")
    ok, detail = validate_experimental_isolation(exp)
    assert not ok
    assert "namespace" in detail or "CONTROL output channel" in detail


def test_isolation_fails_when_output_channel_not_namespaced():
    exp = replace(ExperimentalConfig(), paper_trades_channel="talonx:paper:trades")
    ok, detail = validate_experimental_isolation(exp)
    assert not ok


def test_isolation_fails_when_output_collides_with_piv_namespace():
    exp = replace(
        ExperimentalConfig(),
        exp_namespace="talonx:piv",
        signals_channel="talonx:piv:signals:quant",
        rejected_candidates_channel="talonx:piv:quant:rejected",
        alerts_channel="talonx:piv:alerts",
        paper_trades_channel="talonx:piv:paper:trades",
    )
    ok, detail = validate_experimental_isolation(exp)
    assert not ok
    assert "PIV" in detail


def test_isolation_fails_when_input_channels_differ_from_control(monkeypatch):
    monkeypatch.delenv("TALONX_REDIS_MARKET_CHANNEL", raising=False)
    exp = replace(ExperimentalConfig(), market_stream_channel="talonx:exp:market:stream")
    ok, detail = validate_experimental_isolation(exp)
    assert not ok
    assert "same normalized market inputs" in detail


def test_isolation_fails_when_quant_db_overlaps_control(tmp_path, monkeypatch):
    exp = replace(ExperimentalConfig(), state_dir=tmp_path)

    # Distinct by default (exp_quant.db under our tmp state_dir).
    monkeypatch.setenv("TALONX_QUANT_DB_PATH", str(tmp_path / "quant.db"))
    ok, _ = validate_experimental_isolation(exp)
    assert ok

    # Force the collision.
    monkeypatch.setenv("TALONX_QUANT_DB_PATH", str(exp.quant_db_path))
    ok2, detail2 = validate_experimental_isolation(exp)
    assert not ok2
    assert "quant DB" in detail2


def test_isolation_fails_when_paper_db_overlaps_control(monkeypatch):
    exp = ExperimentalConfig()
    monkeypatch.setenv("TALONX_PAPER_DB", str(exp.paper_db_path))
    ok, detail = validate_experimental_isolation(exp)
    assert not ok
    assert "paper DB" in detail


def test_isolation_fails_when_not_paper_only():
    exp = replace(ExperimentalConfig(), paper_only=False)
    ok, detail = validate_experimental_isolation(exp)
    assert not ok
    assert "paper_only" in detail


# ----------------------------------------------------------------------------
# Defaults / plumbing
# ----------------------------------------------------------------------------

def test_experimental_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TALONX_EXPERIMENTAL_ENABLED", raising=False)
    assert ExperimentalConfig().enabled is False


def test_experimental_enabled_via_env(monkeypatch):
    monkeypatch.setenv("TALONX_EXPERIMENTAL_ENABLED", "true")
    assert ExperimentalConfig().enabled is True


def test_profile_id_stamped():
    assert ExperimentalConfig().profile_id == PROFILE_ID == "EXPERIMENTAL_RELAXED_V1"


def test_isolated_db_paths_all_distinct():
    exp = ExperimentalConfig()
    paths = {exp.quant_db_path, exp.paper_db_path, exp.telemetry_db_path}
    assert len(paths) == 3


def test_relaxation_summary_shape():
    cfg = build_experimental_quant_config(ExperimentalConfig())
    rows = relaxation_summary(cfg)
    assert {r["field"] for r in rows} == set(RELAXED_OVERRIDES)
    for r in rows:
        assert r["frozen"] != r["experimental"]
