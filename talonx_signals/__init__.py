"""talonx_signals -- Task 99A informational + experimental signal layer.

Additive, isolated. Contains:
  - config              ExperimentalConfig + relaxed-override whitelist
  - relaxed_profile     build_experimental_quant_config / frozen-snapshot guard
  - (later phases)       directional / premarket / telemetry / experimental_paper /
                         eod_attribution / schemas / run

Nothing in this package mutates talonx_quant / talonx_core / talonx_paper.
CONTROL (the frozen production strategy) is never touched -- the experimental
QuantScanner config is a dataclasses.replace() of QuantConfig(), which
physically cannot alter the frozen default. See
results/task99a_alert_restoration/.
"""

from __future__ import annotations

__all__ = [
    "ExperimentalConfig",
    "RELAXED_OVERRIDES",
    "build_experimental_quant_config",
    "frozen_quant_config_snapshot",
    "assert_control_profile_unchanged",
    "validate_experimental_isolation",
    "DirectionalAlert",
    "DirectionalAlertEngine",
    "AlertDirection",
    "TradeGateStatus",
    "PremarketWatchEngine",
    "PremarketSymbolInput",
    "PremarketBundle",
]

from talonx_signals.config import (
    RELAXED_OVERRIDES,
    ExperimentalConfig,
    validate_experimental_isolation,
)
from talonx_signals.relaxed_profile import (
    assert_control_profile_unchanged,
    build_experimental_quant_config,
    frozen_quant_config_snapshot,
)
from talonx_signals.schemas import AlertDirection, DirectionalAlert, TradeGateStatus
from talonx_signals.directional import DirectionalAlertEngine
from talonx_signals.premarket import PremarketBundle, PremarketSymbolInput, PremarketWatchEngine
from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.dispatcher import (
    ExperimentalDispatcher,
    NullSender,
    RecordingSender,
    TelegramSenderAdapter,
)
from talonx_signals.reply import make_reply_resolver
from talonx_signals.telemetry import (
    ForwardOutcomeRecorder,
    ForwardOutcomeStore,
    classify_admission,
)
from talonx_signals.dashboard import ExperimentalDashboard, make_app as make_dashboard_app
from talonx_signals.experimental_paper import ExperimentalPaperEngine
from talonx_signals.intelligence_bridge import (
    BridgeMetrics,
    EarningsRadarBridge,
    PostEarningsBridge,
    bridge_health,
    overnight_event_labels,
)

__all__ += [
    "ExperimentalAlertStore",
    "ExperimentalDispatcher",
    "RecordingSender",
    "NullSender",
    "TelegramSenderAdapter",
    "make_reply_resolver",
    "ForwardOutcomeStore",
    "ForwardOutcomeRecorder",
    "classify_admission",
    "ExperimentalDashboard",
    "make_dashboard_app",
    "ExperimentalPaperEngine",
    "EarningsRadarBridge",
    "PostEarningsBridge",
    "BridgeMetrics",
    "bridge_health",
    "overnight_event_labels",
]
