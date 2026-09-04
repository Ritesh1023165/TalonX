"""Task 99A -- EXPERIMENTAL_RELAXED_V1 runtime configuration + fail-closed
isolation validation.

Design (see results/task99a_alert_restoration/EXPERIMENTAL_RELAXED_V1_SPEC.md
and TASK99A_IMPLEMENTATION_PLAN.md):

  - The experimental lane CONSUMES the same normalized market inputs as
    CONTROL (talonx:market:stream, talonx:news:events) -- "both profiles must
    receive the same normalized market inputs".
  - It PUBLISHES only to isolated talonx:exp:* channels and writes only to
    isolated SQLite files, so it can never feed the CONTROL decision/paper
    path or be mistaken for a production signal.
  - It is opt-in (disabled by default) and paper-only.

This mirrors talonx_piv/isolation.py's posture, adapted: PIV isolates the
INPUT too (its own Redis DB + namespaced market channel); Task 99A
deliberately SHARES the input so the two profiles are genuinely comparable,
and isolates every OUTPUT instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# The ONLY QuantConfig fields EXPERIMENTAL_RELAXED_V1 is permitted to change
# relative to the frozen default, and their relaxed values. Evidence:
# results/task99a_alert_restoration/RELAXATION_EVIDENCE.md.
#
#   min_atr_pct          0.25 -> 0.10   (candidate-median ATR%, Task 38/93)
#   confluence_score_min 2    -> 1      (task-authorised; LEGACY math unchanged)
#   min_risk_reward_ratio 1.5 -> 1.0    (geometry unchanged, acceptance ratio only)
#
# volatility_gate_mode (CURRENT_1M) and confluence_contract (LEGACY) are NOT
# in this dict and MUST NOT be -- the live QuantScanner.__init__ hard-refuses
# anything else, and changing the contract would make the experiment
# un-attributable.
# ---------------------------------------------------------------------------
RELAXED_OVERRIDES: dict[str, float | int] = {
    "min_atr_pct": 0.10,
    "confluence_score_min": 1,
    "min_risk_reward_ratio": 1.0,
}

# Conservative dial-backs documented for the gatekeeper (not applied here).
RELAXED_OVERRIDES_CONSERVATIVE: dict[str, float | int] = {
    "min_atr_pct": 0.15,
    "confluence_score_min": 2,
    "min_risk_reward_ratio": 1.0,
}

PROFILE_ID = "EXPERIMENTAL_RELAXED_V1"

_HOME_TALONX = Path.home() / ".talonx"


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


@dataclass(frozen=True)
class ExperimentalConfig:
    """Runtime bindings for the EXPERIMENTAL_RELAXED_V1 lane. Frozen; construct
    a new one with dataclasses.replace() for tests."""

    profile_id: str = PROFILE_ID

    # Opt-in. Absent flag -> the lane is never constructed by run_talonx.py.
    enabled: bool = field(default_factory=lambda: _truthy("TALONX_EXPERIMENTAL_ENABLED"))

    # Paper-only, structurally. No broker fields exist on this dataclass.
    paper_only: bool = True

    # --- SHARED input channels (must equal CONTROL's) ---
    redis_url: str = field(default_factory=lambda: os.getenv("TALONX_REDIS_URL", "redis://localhost:6379/0"))
    market_stream_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"
    ))
    news_events_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_REDIS_NEWS_EVENTS_CHANNEL", "talonx:news:events"
    ))

    # --- ISOLATED output channels (talonx:exp:*) ---
    exp_namespace: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_REDIS_NAMESPACE", "talonx:exp"
    ).strip().rstrip(":"))
    signals_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_SIGNALS_CHANNEL", "talonx:exp:signals:quant"
    ))
    rejected_candidates_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_REJECTED_CHANNEL", "talonx:exp:quant:rejected"
    ))
    directional_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_DIRECTIONAL_CHANNEL", "talonx:signals:directional"
    ))
    alerts_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_ALERTS_CHANNEL", "talonx:exp:alerts"
    ))
    paper_trades_channel: str = field(default_factory=lambda: os.getenv(
        "TALONX_EXPERIMENTAL_PAPER_TRADES_CHANNEL", "talonx:exp:paper:trades"
    ))

    # --- ISOLATED SQLite files ---
    state_dir: Path = field(default_factory=lambda: _resolved(os.getenv(
        "TALONX_EXPERIMENTAL_STATE_DIR", str(_HOME_TALONX / "experimental")
    )))

    @property
    def quant_db_path(self) -> Path:
        return _resolved(self.state_dir / "exp_quant.db")

    @property
    def paper_db_path(self) -> Path:
        return _resolved(self.state_dir / "experimental_paper.db")

    @property
    def telemetry_db_path(self) -> Path:
        return _resolved(self.state_dir / "forward_outcomes.db")

    @property
    def isolated_output_channels(self) -> set[str]:
        return {
            self.signals_channel,
            self.rejected_candidates_channel,
            self.alerts_channel,
            self.paper_trades_channel,
        }


# ---------------------------------------------------------------------------
# CONTROL / PIV binding identities the experimental lane must NOT collide with.
# ---------------------------------------------------------------------------
def _control_output_channels() -> set[str]:
    return {
        os.getenv("TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"),
        os.getenv("TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL", "talonx:quant:rejected"),
        os.getenv("TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"),
        os.getenv("TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"),
    }


def _control_input_channels() -> set[str]:
    return {
        os.getenv("TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"),
        os.getenv("TALONX_REDIS_NEWS_EVENTS_CHANNEL", "talonx:news:events"),
    }


def _control_quant_db() -> Path:
    return _resolved(os.getenv("TALONX_QUANT_DB_PATH", str(_HOME_TALONX / "quant.db")))


def _control_paper_db() -> Path:
    return _resolved(os.getenv("TALONX_PAPER_DB", str(_HOME_TALONX / "paper_trading.db")))


def _piv_namespace_prefix() -> str:
    ns = os.getenv("TALONX_PIV_REDIS_NAMESPACE", "talonx:piv").strip().rstrip(":")
    return f"{ns}:" if ns else "talonx:piv:"


def validate_experimental_isolation(config: ExperimentalConfig) -> tuple[bool, str]:
    """Prove EXPERIMENTAL_RELAXED_V1 cannot feed or corrupt CONTROL/PIV.

    Returns (ok, human_detail). Detail contains no credentials/URLs beyond
    channel names, mirroring talonx_piv.isolation.validate_piv_isolation.
    """
    failures: list[str] = []

    exp_out = config.isolated_output_channels
    if len(exp_out) != 4:
        failures.append("experimental output channels must be four mutually distinct names")

    prefix = f"{config.exp_namespace}:" if config.exp_namespace else ""
    if not prefix or any(not ch.startswith(prefix) for ch in exp_out):
        failures.append(
            "every experimental OUTPUT channel must use the configured non-empty "
            f"experimental namespace ({config.exp_namespace!r})"
        )

    control_out = _control_output_channels()
    if exp_out & control_out:
        failures.append("an experimental output channel overlaps a CONTROL output channel")

    piv_prefix = _piv_namespace_prefix()
    if any(ch.startswith(piv_prefix) for ch in exp_out):
        failures.append("an experimental output channel collides with the PIV namespace")

    # Input channels MUST match CONTROL -- the two profiles are only comparable
    # if fed identical normalized bars.
    exp_in = {config.market_stream_channel, config.news_events_channel}
    if exp_in != _control_input_channels():
        failures.append(
            "experimental INPUT channels must exactly equal CONTROL's "
            "(both profiles must receive the same normalized market inputs)"
        )

    if config.quant_db_path == _control_quant_db():
        failures.append("experimental quant DB path overlaps the CONTROL quant DB")
    if config.paper_db_path == _control_paper_db():
        failures.append("experimental paper DB path overlaps the CONTROL paper DB")
    if config.quant_db_path == config.paper_db_path:
        failures.append("experimental quant and paper DB paths must differ")

    if not config.paper_only:
        failures.append("EXPERIMENTAL_RELAXED_V1 must be paper_only")

    if failures:
        return False, "; ".join(failures)
    return True, (
        "shared CONTROL market/news input; isolated talonx:exp:* output channels; "
        "isolated exp_quant.db / experimental_paper.db; paper-only"
    )
