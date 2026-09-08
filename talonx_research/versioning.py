"""
Immutable strategy-version identity + registry (Task 115.A / R1 / R7).

A strategy version is identified by (strategy_family, version) and carries
an implementation *fingerprint* computed only over the files that define
its semantics.  Metadata / documentation / plumbing changes MUST NOT move
the fingerprint.  A FROZEN/VALIDATED/ACTIVE version cannot be mutated in
place -- registering a changed fingerprint under the same (family,
version) raises.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = _ROOT / "results" / "task115_validation_framework" / "strategy_registry.json"

# The frozen live release under validation lives in the PRIMARY worktree.
# Fingerprints MUST be computed over exactly those bytes (line endings and
# all) -- Task 116 validates that release, not this framework's own
# checkout.  Override with TALONX_FROZEN_STRATEGY_ROOT.
FROZEN_STRATEGY_ROOT = Path(os.environ.get("TALONX_FROZEN_STRATEGY_ROOT", r"C:/workspace/TalonX"))
if not (FROZEN_STRATEGY_ROOT / "talonx_v2" / "config.py").exists():
    FROZEN_STRATEGY_ROOT = _ROOT   # fallback: this worktree


class LifecycleState(str, Enum):
    RESEARCH = "RESEARCH"            # hypothesis / discovery, freely tunable
    FROZEN = "FROZEN"               # immutable impl + fingerprint; holdout not yet run
    VALIDATING = "VALIDATING"       # 2-year replay in progress
    FAILED = "FAILED"              # validation verdict FAIL
    VALIDATED = "VALIDATED"        # validation verdict PASS / PASS_WITH_FINDINGS
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"
    SHADOW = "SHADOW"             # running as a live internal shadow lane
    ACTIVE = "ACTIVE"             # the live-paper strategy
    BASELINE = "BASELINE"          # preserved reference (e.g. Original V1)
    RETIRED = "RETIRED"


class PromotionStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"
    PROMOTION_PENDING_DECISION = "PROMOTION_PENDING_DECISION"
    PROMOTED = "PROMOTED"


# Files whose bytes define V2's SEMANTICS.  Anything else (service.py,
# pipeline.py, run.py, dispatch plumbing, dashboards) is operational and
# does not move the fingerprint.  This mirrors
# research/scripts/task112_v2_release_fingerprint.py exactly.
_V2_STRATEGY_FILES = (
    "talonx_v2/config.py",
    "talonx_v2/cluster_engine.py",
    "talonx_v2/liquidity.py",
    "talonx_v2/quant_bridge.py",
    "talonx_v2/brain_bridge.py",
)


def v2_fingerprint(root: Path | None = None) -> str:
    """16-hex fingerprint of the FROZEN V2 strategy semantics -- byte-exact
    to research/scripts/task112_v2_release_fingerprint.py:
        sha256( json(config, sort_keys) + V2_VERSION + concat(5 file bytes) ).
    The scalar config + V2_VERSION are read from THIS worktree's
    talonx_v2.config (identical to the frozen release); the 5 semantic file
    BYTES are read from ``root`` (the frozen release worktree) so line
    endings match exactly.  No import of talonx_v2 package code from
    ``root`` -- keeps sys.modules isolated."""
    root = Path(root) if root else FROZEN_STRATEGY_ROOT
    from talonx_v2.config import V2_VERSION, V2Config
    c = V2Config()
    cfg = {
        "cluster_window_trading_days": c.cluster_window_trading_days,
        "min_distinct_owners": c.min_distinct_owners,
        "transaction_code": c.transaction_code,
        "direction": c.direction,
        "entry_offset_sessions": c.entry_offset_sessions,
        "hold_trading_days": c.hold_trading_days,
        "stop_loss_enabled": c.stop_loss_enabled,
        "max_concurrent_positions": c.max_concurrent_positions,
        "reentry_cooldown_trading_days": c.reentry_cooldown_trading_days,
        "liquidity_lookback_sessions": c.liquidity_lookback_sessions,
        "liquidity_min_median_dollar_volume": c.liquidity_min_median_dollar_volume,
        "liquidity_min_close": c.liquidity_min_close,
        "exit_fallforward_max_sessions": c.exit_fallforward_max_sessions,
        "max_entry_staleness_sessions": c.max_entry_staleness_sessions,
    }
    h = hashlib.sha256()
    h.update(json.dumps(cfg, sort_keys=True).encode())
    h.update(V2_VERSION.encode())
    for rel in _V2_STRATEGY_FILES:
        p = root / rel
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"MISSING:" + str(p).encode())
    return h.hexdigest()[:16]


_V1_STRATEGY_FILES = ("talonx_quant/strategy.py", "talonx_quant/indicators.py",
                      "talonx_quant/config.py", "talonx_quant/session.py",
                      "talonx_quant/consumer.py")


def v1_fingerprint(root: Path | None = None) -> str:
    """12-hex fingerprint of the FROZEN Original V1 strategy source --
    byte-exact to talonx_backtest.reproducibility.get_strategy_version()."""
    root = Path(root) if root else FROZEN_STRATEGY_ROOT
    h = hashlib.sha256()
    for rel in _V1_STRATEGY_FILES:
        p = root / rel
        h.update(p.read_bytes() if p.exists() else (b"MISSING:" + str(p).encode()))
    return h.hexdigest()[:12]


@dataclass
class StrategyVersion:
    strategy_family: str
    version: int
    fingerprint: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    lifecycle_state: str = LifecycleState.RESEARCH.value
    promotion_status: str = PromotionStatus.NOT_ELIGIBLE.value
    validation_status: str | None = None          # VALIDATION_PASS / ... / FAIL
    validation_window: dict[str, str] | None = None
    discovery_window: dict[str, str] | None = None
    holdout_window: dict[str, str] | None = None
    primary_cost_bps: int = 20
    implementation_files: tuple[str, ...] = _V2_STRATEGY_FILES
    runtime_reference: str = ""                    # e.g. "talonx_v2.service.V2Service"
    notes: str = ""

    @property
    def id(self) -> str:
        return f"{self.strategy_family}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["implementation_files"] = list(self.implementation_files)
        d["id"] = self.id
        return d

    @property
    def is_immutable(self) -> bool:
        return self.lifecycle_state in (
            LifecycleState.FROZEN.value, LifecycleState.VALIDATING.value,
            LifecycleState.VALIDATED.value, LifecycleState.SHADOW_ELIGIBLE.value,
            LifecycleState.SHADOW.value, LifecycleState.ACTIVE.value,
            LifecycleState.BASELINE.value, LifecycleState.RETIRED.value)


class StrategyRegistry:
    """JSON-backed registry of immutable strategy versions."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DEFAULT_REGISTRY)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    # ---- reads ----
    def get(self, version_id: str) -> StrategyVersion | None:
        d = self._data.get(version_id)
        if d is None:
            return None
        d = dict(d)
        d.pop("id", None)
        d["implementation_files"] = tuple(d.get("implementation_files", _V2_STRATEGY_FILES))
        return StrategyVersion(**d)

    def all(self) -> list[StrategyVersion]:
        return [self.get(k) for k in sorted(self._data)]

    def active(self) -> StrategyVersion | None:
        for k, d in self._data.items():
            if d.get("lifecycle_state") == LifecycleState.ACTIVE.value:
                return self.get(k)
        return None

    # ---- writes (immutability-enforcing) ----
    def register(self, sv: StrategyVersion, *, allow_update: bool = False) -> StrategyVersion:
        existing = self._data.get(sv.id)
        if existing is not None:
            ex = self.get(sv.id)
            if ex.is_immutable and ex.fingerprint != sv.fingerprint:
                raise ValueError(
                    f"{sv.id} is {ex.lifecycle_state} and immutable -- its fingerprint "
                    f"{ex.fingerprint} cannot be changed to {sv.fingerprint}. "
                    "A semantic change requires a NEW version (R1).")
            if not allow_update and ex.fingerprint == sv.fingerprint:
                # metadata-only refresh is fine; a state change goes through transition()
                pass
        self._data[sv.id] = sv.to_dict()
        self._flush()
        return sv

    def transition(self, version_id: str, new_state: LifecycleState | str, *,
                   reason: str = "") -> StrategyVersion:
        sv = self.get(version_id)
        if sv is None:
            raise KeyError(version_id)
        new_state = LifecycleState(new_state).value if not isinstance(new_state, str) else new_state
        _assert_transition_allowed(sv.lifecycle_state, new_state)
        d = self._data[version_id]
        d["lifecycle_state"] = new_state
        if reason:
            d["notes"] = (d.get("notes", "") + f" | {new_state}: {reason}").strip(" |")
        self._flush()
        return self.get(version_id)

    def set_validation(self, version_id: str, *, status: str,
                       validation_window: dict, discovery_window: dict,
                       holdout_window: dict, primary_cost_bps: int) -> StrategyVersion:
        d = self._data[version_id]
        d["validation_status"] = status
        d["validation_window"] = validation_window
        d["discovery_window"] = discovery_window
        d["holdout_window"] = holdout_window
        d["primary_cost_bps"] = primary_cost_bps
        self._flush()
        return self.get(version_id)

    def promote_to_active(self, version_id: str, *, decided_by: str, note: str) -> StrategyVersion:
        """EXPLICIT promotion only (R6).  Requires VALIDATED + SHADOW history
        recorded in notes; demotes the current ACTIVE to BASELINE."""
        sv = self.get(version_id)
        if sv is None:
            raise KeyError(version_id)
        if sv.lifecycle_state not in (LifecycleState.SHADOW.value,
                                      LifecycleState.SHADOW_ELIGIBLE.value,
                                      LifecycleState.VALIDATED.value):
            raise ValueError(f"{version_id} is {sv.lifecycle_state}; only a VALIDATED/SHADOW "
                             "version can be promoted (R6).")
        cur = self.active()
        if cur is not None:
            self._data[cur.id]["lifecycle_state"] = LifecycleState.BASELINE.value
            self._data[cur.id]["notes"] = (self._data[cur.id].get("notes", "")
                                           + f" | demoted to BASELINE for {version_id}").strip(" |")
        self._data[version_id]["lifecycle_state"] = LifecycleState.ACTIVE.value
        self._data[version_id]["promotion_status"] = PromotionStatus.PROMOTED.value
        self._data[version_id]["notes"] = (
            self._data[version_id].get("notes", "")
            + f" | PROMOTED by {decided_by}: {note}").strip(" |")
        self._flush()
        return self.get(version_id)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True, default=str))
        tmp.replace(self.path)


_ALLOWED = {
    LifecycleState.RESEARCH.value: {LifecycleState.FROZEN.value, LifecycleState.RETIRED.value},
    LifecycleState.FROZEN.value: {LifecycleState.VALIDATING.value, LifecycleState.RETIRED.value},
    LifecycleState.VALIDATING.value: {LifecycleState.VALIDATED.value, LifecycleState.FAILED.value},
    LifecycleState.VALIDATED.value: {LifecycleState.SHADOW_ELIGIBLE.value, LifecycleState.RETIRED.value},
    LifecycleState.SHADOW_ELIGIBLE.value: {LifecycleState.SHADOW.value, LifecycleState.RETIRED.value},
    LifecycleState.SHADOW.value: {LifecycleState.ACTIVE.value, LifecycleState.RETIRED.value},
    LifecycleState.ACTIVE.value: {LifecycleState.BASELINE.value, LifecycleState.RETIRED.value},
    LifecycleState.FAILED.value: {LifecycleState.RESEARCH.value, LifecycleState.RETIRED.value},
    LifecycleState.BASELINE.value: {LifecycleState.RETIRED.value},
}


def _assert_transition_allowed(cur: str, new: str) -> None:
    if new == cur:
        return
    if new not in _ALLOWED.get(cur, set()):
        raise ValueError(f"illegal lifecycle transition {cur} -> {new} (R6)")


def seed_known_versions(registry: StrategyRegistry, *, root: Path | None = None) -> None:
    """Idempotently record the two versions that already exist:
    INSIDER_BUY_CLUSTER_V2@1 (ACTIVE) and ORIGINAL_V1 (BASELINE)."""
    if registry.get("INSIDER_BUY_CLUSTER_V2@1") is None:
        registry.register(StrategyVersion(
            strategy_family="INSIDER_BUY_CLUSTER_V2", version=1,
            fingerprint=v2_fingerprint(root),
            lifecycle_state=LifecycleState.ACTIVE.value,
            promotion_status=PromotionStatus.PROMOTED.value,
            validation_status="VALIDATION_PASS_WITH_FINDINGS",
            validation_window={"note": "Task 107B in-panel + Task 112R runtime re-eval"},
            discovery_window={"start": "2019-06-03", "end": "2023-07-01"},
            holdout_window={"start": "2023-07-01", "end": "2026-08-14"},
            primary_cost_bps=20,
            runtime_reference="talonx_v2.service.V2Service / talonx_v2.pipeline",
            notes="Task 107B paper candidate; Task 109 freeze; Task 110-113 integration + "
                  "Tuesday 2026-09-08 full-day live-paper qualification "
                  "(TASK113_FULL_DAY_PASS_WITH_FINDINGS). Immutable."))
    if registry.get("ORIGINAL_V1@1") is None:
        registry.register(StrategyVersion(
            strategy_family="ORIGINAL_V1", version=1,
            fingerprint="2ae6216bca70",
            lifecycle_state=LifecycleState.BASELINE.value,
            promotion_status=PromotionStatus.NOT_ELIGIBLE.value,
            implementation_files=("talonx_quant/strategy.py", "talonx_quant/indicators.py",
                                  "talonx_quant/config.py", "talonx_quant/session.py",
                                  "talonx_quant/consumer.py"),
            runtime_reference="talonx_backtest.reproducibility.get_strategy_version",
            notes="ARCHIVED_BASELINE / REPRODUCIBLE (Task 109 v1_preservation_contract). Immutable."))
