"""Task 69Q Part 2 -- canonical live-session identity.

Task69P's review found piv_events.jsonl is a single append-only file with
no session_id/trading_date field, spanning multiple trading dates (2026-08-
23/24/25 all in one file) with no built-in way to scope a report to exactly
one session. Rather than rewriting the storage layout (risky, out of scope
for this task -- see results/task69q_evidence_upgrade/production_readiness_
gaps.json), every event is now stamped with session_id/trading_date_et (see
events.py's EventBus.emit) and reporting.build_session_report can filter the
shared file down to one trading_date_et before counting anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import subprocess

from .config import PivConfig
from .events import ET


def compute_config_hash(config: PivConfig) -> str:
    """Stable hash of the config fields that affect what a session actually
    does -- feed mode, universe, and cutoff times. Deliberately excludes
    secrets (key_id/secret_key/telegram_token) and paths."""
    material = "|".join((
        config.feed_mode, ",".join(config.universe), config.entry_cutoff_et,
        config.eod_flatten_et, str(config.decision_path_enabled), str(config.paper_trading),
        str(config.real_capital),
    ))
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def runtime_sha(cwd: str | None = None) -> str:
    """Best-effort git HEAD sha; never raises -- a health/identity stamp
    must not block session startup if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        sha = result.stdout.strip()
        return sha if result.returncode == 0 and sha else "unknown"
    except Exception:  # noqa: BLE001 -- identity stamping must never crash a session
        return "unknown"


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    trading_date_et: str
    runtime_start_utc: str
    runtime_sha: str
    config_hash: str
    feed_mode: str

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id, "trading_date_et": self.trading_date_et,
            "runtime_start_utc": self.runtime_start_utc, "runtime_sha": self.runtime_sha,
            "config_hash": self.config_hash, "feed_mode": self.feed_mode,
        }


def build_session_identity(config: PivConfig, now: datetime | None = None) -> SessionIdentity:
    now = now or datetime.now(timezone.utc)
    trading_date_et = now.astimezone(ET).date().isoformat()
    config_hash = compute_config_hash(config)
    session_id = f"piv_{trading_date_et}_{now.astimezone(ET):%H%M%S}_{config_hash[:8]}"
    return SessionIdentity(
        session_id=session_id, trading_date_et=trading_date_et,
        runtime_start_utc=now.isoformat(), runtime_sha=runtime_sha(),
        config_hash=config_hash, feed_mode=config.feed_mode,
    )


_SESSION_IDENTITY_REQUIRED_FIELDS = ("session_id", "trading_date_et", "runtime_start_utc", "runtime_sha", "config_hash", "feed_mode")

_TERMINAL_ORDER_STATUSES_FOR_RECOVERY = frozenset({"filled", "rejected", "canceled", "expired"})
_UNRESOLVED_INTENT_STATUSES = frozenset({"ORDER_INTENT", "SUBMIT_FAILED_UNCERTAIN"})

RESUME_SAME_SESSION = "RESUME_SAME_SESSION"
FRESH_SESSION_CLEAN = "FRESH_SESSION_CLEAN"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class SessionRecoveryRequired(RuntimeError):
    """Task 81 §3: raised by resolve_session_identity when a genuinely new
    process invocation must NOT silently create a replacement session --
    runtime/config/feed/account bindings changed, the persisted identity is
    corrupt, or EOD state is incomplete, AND exposure or submissions remain
    unresolved. The caller must preserve recovery context (never overwrite
    session_identity.json), block new entries, and surface `required_action`
    to the operator. A fresh session is permitted only through the defined,
    verified transition described in `required_action`."""

    def __init__(self, *, reasons, required_action: str, preserved_identity):
        self.reasons = tuple(reasons)
        self.required_action = required_action
        self.preserved_identity = preserved_identity
        super().__init__(f"SESSION_RECOVERY_REQUIRED :: {required_action} :: " + "; ".join(self.reasons))


@dataclass(frozen=True)
class SessionRecoveryAssessment:
    mode: str
    identity: SessionIdentity | None
    reasons: tuple[str, ...]
    required_action: str | None
    unresolved_exposure: bool
    binding_changes: tuple[str, ...]
    preserved_identity: dict | None


def _safe_load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _unresolved_exposure_reasons(lifecycle_state: dict) -> list[str]:
    """Every kind of still-open exposure / unresolved submission / pending
    exit obligation that must survive a restart -- if any of these exist, a
    genuinely NEW session must not be minted around them without an
    explicit, verified recovery transition."""
    reasons: list[str] = []
    for position in (lifecycle_state.get("positions") or {}).values():
        if position.get("status") == "OPEN":
            reasons.append(f"OPEN_POSITION:{position.get('symbol')}")
            if position.get("triggered_exit_reason"):
                reasons.append(f"UNRESOLVED_EXIT_OBLIGATION:{position.get('symbol')}:{position.get('triggered_exit_reason')}")
            if float(position.get("remaining_quantity", position.get("quantity") or 0.0) or 0.0) > 1e-9 and float(position.get("exit_quantity") or 0.0) > 1e-9:
                reasons.append(f"PARTIAL_EXIT_IN_PROGRESS:{position.get('symbol')}")
    for order_id, order in (lifecycle_state.get("orders") or {}).items():
        if order.get("status") not in _TERMINAL_ORDER_STATUSES_FOR_RECOVERY:
            reasons.append(f"OUTSTANDING_ORDER:{order_id}:{order.get('status')}")
    for intent_id, intent in (lifecycle_state.get("intents") or {}).items():
        if intent.get("status") in _UNRESOLVED_INTENT_STATUSES:
            reasons.append(f"UNRESOLVED_SUBMISSION:{intent_id}:{intent.get('status')}")
    if (lifecycle_state.get("reconciliation_flags") or {}).get("entry_admission_blocked"):
        reasons.append("RECONCILIATION_ENTRY_BLOCK_ACTIVE")
    return reasons


def _eod_incomplete_reason(eod_state, today_et: str) -> str | None:
    if not isinstance(eod_state, dict):
        return None
    status = eod_state.get("status")
    if eod_state.get("trading_date_et") != today_et:
        return None if status == "PASSED" else f"PRIOR_DAY_EOD_NOT_COMPLETE:{status}"
    return None if status == "PASSED" else f"EOD_NOT_COMPLETE:{status}"


def assess_session_recovery(config: PivConfig, *, now: datetime | None = None) -> SessionRecoveryAssessment:
    """Task 81 §3: classify how a new process invocation should treat any
    persisted session state -- RESUME_SAME_SESSION (unchanged verified
    bindings, still-live session), FRESH_SESSION_CLEAN (nothing unresolved
    to recover -- the prior session, if any, is flat and EOD-complete), or
    RECOVERY_REQUIRED (bindings changed / identity corrupt / EOD incomplete
    while exposure or submissions remain unresolved -- must be surfaced, not
    silently replaced)."""
    now = now or datetime.now(timezone.utc)
    today_et = now.astimezone(ET).date().isoformat()
    current_config_hash = compute_config_hash(config)
    current_runtime_sha = runtime_sha()
    sd = config.state_dir
    identity_path = sd / "session_identity.json"
    lifecycle_path = sd / "lifecycle_state.json"
    eod_path = sd / "eod_state.json"

    saved = _safe_load_json(identity_path) if identity_path.exists() else None
    lifecycle_state = _safe_load_json(lifecycle_path) if lifecycle_path.exists() else None
    eod_state = _safe_load_json(eod_path) if eod_path.exists() else None

    identity_wellformed = isinstance(saved, dict) and all(k in saved for k in _SESSION_IDENTITY_REQUIRED_FIELDS)
    identity_corrupt = identity_path.exists() and not identity_wellformed
    lifecycle_corrupt = lifecycle_path.exists() and not isinstance(lifecycle_state, dict)
    eod_corrupt = eod_path.exists() and not isinstance(eod_state, dict)

    exposure_reasons = _unresolved_exposure_reasons(lifecycle_state) if isinstance(lifecycle_state, dict) else []
    if lifecycle_corrupt:
        exposure_reasons.append("LIFECYCLE_STATE_UNREADABLE")
    eod_reason = _eod_incomplete_reason(eod_state, today_et)

    binding_changes: list[str] = []
    if identity_wellformed:
        if saved.get("trading_date_et") != today_et:
            binding_changes.append(f"trading_date_et:{saved.get('trading_date_et')}->{today_et}")
        if saved.get("config_hash") != current_config_hash:
            binding_changes.append("config_hash")
        if saved.get("feed_mode") != config.feed_mode:
            binding_changes.append(f"feed_mode:{saved.get('feed_mode')}->{config.feed_mode}")
        if saved.get("runtime_sha") != current_runtime_sha:
            binding_changes.append(f"runtime_sha:{saved.get('runtime_sha')}->{current_runtime_sha}")

    session_live = (
        isinstance(lifecycle_state, dict)
        and lifecycle_state.get("session_enabled") is True
        and lifecycle_state.get("kill_switch") is not True
    )

    # 1. Clean, verified resume of a still-live same-day session.
    if identity_wellformed and not binding_changes and session_live and not eod_reason and not eod_corrupt:
        identity = SessionIdentity(**{k: saved[k] for k in _SESSION_IDENTITY_REQUIRED_FIELDS})
        return SessionRecoveryAssessment(
            RESUME_SAME_SESSION, identity, (), None, bool(exposure_reasons), (), dict(saved),
        )

    reasons: list[str] = []
    if identity_corrupt:
        reasons.append("SESSION_IDENTITY_CORRUPT")
    if binding_changes:
        reasons.append("BINDINGS_CHANGED:" + ",".join(binding_changes))
    if identity_wellformed and not session_live:
        reasons.append("PRIOR_SESSION_NOT_LIVE")
    if eod_reason:
        reasons.append(eod_reason)
    if eod_corrupt:
        reasons.append("EOD_STATE_UNREADABLE")
    reasons.extend(exposure_reasons)

    unresolved = bool(exposure_reasons) or bool(eod_reason) or eod_corrupt

    # 2. Something changed AND there is unresolved exposure/EOD state ->
    #    never silently replace. Preserve context, block, report.
    if unresolved and (binding_changes or identity_corrupt or eod_reason or eod_corrupt or (identity_wellformed and not session_live)):
        action = (
            "Recover the preserved session before starting a new one: resolve every outstanding "
            "order / uncertain submission / open position, run `python -m talonx_piv.cli eod` to "
            "completion for the preserved session (EOD status PASSED), then start a fresh session. "
            "Do not switch runtime/config/feed/account bindings until that transition is complete."
        )
        return SessionRecoveryAssessment(
            RECOVERY_REQUIRED, None, tuple(reasons), action, bool(exposure_reasons),
            tuple(binding_changes), dict(saved) if isinstance(saved, dict) else None,
        )

    # 3. Nothing unresolved -> a fresh session is the defined, verified
    #    transition (prior session flat / EOD-complete / absent).
    identity = build_session_identity(config, now=now)
    return SessionRecoveryAssessment(
        FRESH_SESSION_CLEAN, identity, tuple(reasons), None, False,
        tuple(binding_changes), dict(saved) if isinstance(saved, dict) else None,
    )


def write_session_recovery_marker(state_dir, exc: "SessionRecoveryRequired", *, command: str, now: datetime | None = None) -> None:
    """Task 81 §3: durably record that a recovery-required condition was
    hit, WITHOUT overwriting session_identity.json or any other live state.
    Purely additive evidence for the operator / a later diagnostic read."""
    now = now or datetime.now(timezone.utc)
    path = state_dir / "session_recovery_required.json"
    payload = {
        "detected_at_utc": now.isoformat(),
        "command": command,
        "required_action": exc.required_action,
        "reasons": list(exc.reasons),
        "preserved_identity": exc.preserved_identity,
    }
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # evidence best-effort; the raised exception is the hard signal


def resolve_session_identity(config: PivConfig, *, now: datetime | None = None) -> SessionIdentity:
    """Task 79E-R2-2 Requirement 3: "finish the full-process recovery
    contract -- not merely an in-memory EventBus reconstruction test."
    A genuinely NEW process invocation previously ALWAYS minted a brand
    new session_id via build_session_identity, even when resuming what is
    genuinely THE SAME still-live trading session on the SAME day -- an
    in-process supervised restart (supervisor.run_with_bounded_restart)
    reuses the SAME SessionIdentity object in memory without ever calling
    either function again, but a FULL process restart (the operator's own
    CLI re-invoked after a crash) had no equivalent mechanism at all,
    which meant "permit same-session recovery" (Requirement 3) could only
    ever be demonstrated in-process, not truly end to end.

    Reuses the PERSISTED identity from session_identity.json when ALL of:
    - the file exists and parses as a complete, well-formed identity
      record;
    - its `trading_date_et` matches TODAY's real ET date (never a stale
      prior-day session -- mirrors eod_lifecycle.py's own cross-date
      rejection posture elsewhere in this codebase);
    - lifecycle_state.json exists, parses, and shows
      `session_enabled=True` and `kill_switch=False` -- the actual "is
      this session still genuinely live" signal; a session that has
      already been EOD-flattened or kill-switched must NEVER be silently
      resumed, only ever a still-open one.
    - the saved config hash, feed mode, and runtime SHA match the current
      invocation. A same-day restart under changed operating bindings is a
      new session, so any session-scoped permission must be re-authorized.

    Mints a genuinely FRESH identity (build_session_identity) in every
    other case, including any missing file or read/parse failure --
    fails closed toward minting a new, unambiguous identity rather than
    resuming something uncertain.

    Task 81 §3: when a genuinely new invocation has CHANGED bindings (or a
    corrupt persisted identity, or incomplete EOD state) AND exposure or
    submissions remain unresolved, this no longer silently mints a
    replacement -- it raises SessionRecoveryRequired so the caller preserves
    recovery context, blocks new entries, and reports the operator action.
    A same-session resume under unchanged verified bindings, and a clean
    fresh session when nothing is unresolved, both still return normally."""
    assessment = assess_session_recovery(config, now=now)
    if assessment.mode == RECOVERY_REQUIRED:
        raise SessionRecoveryRequired(
            reasons=assessment.reasons,
            required_action=assessment.required_action,
            preserved_identity=assessment.preserved_identity,
        )
    return assessment.identity
