"""Task 99A -- construct the EXPERIMENTAL_RELAXED_V1 QuantScanner config as a
dataclasses.replace() of the frozen QuantConfig(), and prove the frozen
default is never mutated.

`PRODUCTION_STRATEGY_UNCHANGED`: this module imports QuantConfig read-only and
only ever produces NEW instances. It changes exactly three gate-threshold
fields (RELAXED_OVERRIDES) plus the isolated Redis/SQLite bindings; every
other field -- including volatility_gate_mode (CURRENT_1M) and
confluence_contract (LEGACY), which the live QuantScanner.__init__ hard-locks
-- is carried through byte-identical.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from talonx_quant.config import ConfluenceContract, QuantConfig, VolatilityGateMode

from talonx_signals.config import RELAXED_OVERRIDES, ExperimentalConfig

# Fields legitimately rebound for lane isolation (NOT strategy semantics).
_BINDING_FIELDS: frozenset[str] = frozenset({
    "redis_url",
    "market_stream_channel",
    "signals_channel",
    "rejected_candidates_channel",
    "news_events_channel",
    "paper_trades_channel",
    "db_path",
})

# Fields the relaxed profile is allowed to change (strategy thresholds).
_RELAXED_FIELDS: frozenset[str] = frozenset(RELAXED_OVERRIDES)


def frozen_quant_config_snapshot() -> dict[str, Any]:
    """Every QuantConfig() field value at import of the frozen default,
    EXCLUDING the isolation-binding fields. Used as the immutable reference
    the CONTROL profile must always match."""
    base = QuantConfig()
    return {
        f.name: getattr(base, f.name)
        for f in fields(base)
        if f.name not in _BINDING_FIELDS
    }


# Captured once, at first import, from a pristine default.
_FROZEN_SNAPSHOT: dict[str, Any] = frozen_quant_config_snapshot()


def assert_control_profile_unchanged() -> None:
    """Raise if a freshly-constructed QuantConfig() no longer matches the
    frozen snapshot -- i.e. something (a shared-mutable default, a monkeypatch,
    an errant import side effect) has altered the production strategy config.
    Call this after the experimental lane is constructed and in the test suite
    (test area 1)."""
    current = frozen_quant_config_snapshot()
    drift = {
        k: (_FROZEN_SNAPSHOT[k], current[k])
        for k in _FROZEN_SNAPSHOT
        if current[k] != _FROZEN_SNAPSHOT[k]
    }
    if drift:
        raise AssertionError(
            f"CONTROL (frozen) QuantConfig has drifted from its snapshot: {drift}"
        )


def build_experimental_quant_config(exp: ExperimentalConfig) -> QuantConfig:
    """Return a QuantConfig for the EXPERIMENTAL_RELAXED_V1 scanner:
    frozen defaults, with RELAXED_OVERRIDES applied and every output binding
    pointed at the isolated talonx:exp:* channels / exp_quant.db. The market
    and news INPUT channels are left at CONTROL's values (shared input)."""
    cfg = replace(
        QuantConfig(),
        # --- relaxed strategy thresholds (the whole point) ---
        **RELAXED_OVERRIDES,
        # --- isolated output bindings ---
        redis_url=exp.redis_url,
        market_stream_channel=exp.market_stream_channel,   # shared with CONTROL
        news_events_channel=exp.news_events_channel,        # shared with CONTROL
        signals_channel=exp.signals_channel,               # talonx:exp:*
        rejected_candidates_channel=exp.rejected_candidates_channel,
        paper_trades_channel=exp.paper_trades_channel,
        db_path=str(exp.quant_db_path),
    )

    # Contract guards -- the experimental profile must never flip a MODE.
    if cfg.volatility_gate_mode != VolatilityGateMode.CURRENT_1M:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep volatility_gate_mode=CURRENT_1M")
    if cfg.confluence_contract != ConfluenceContract.LEGACY:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep confluence_contract=LEGACY")

    # Prove ONLY the whitelisted fields differ from frozen.
    diffs = {
        f.name
        for f in fields(cfg)
        if f.name not in _BINDING_FIELDS and getattr(cfg, f.name) != _FROZEN_SNAPSHOT[f.name]
    }
    unexpected = diffs - _RELAXED_FIELDS
    if unexpected:
        raise ValueError(
            f"experimental config changes fields outside the relaxed whitelist: {sorted(unexpected)}"
        )

    # And that constructing it didn't mutate the frozen default.
    assert_control_profile_unchanged()
    return cfg


def relaxation_summary(cfg: QuantConfig) -> list[dict[str, Any]]:
    """[{field, frozen, experimental}] for the three relaxed thresholds --
    for the EOD attribution report and the dashboard."""
    return [
        {"field": name, "frozen": _FROZEN_SNAPSHOT[name], "experimental": getattr(cfg, name)}
        for name in sorted(_RELAXED_FIELDS)
    ]
