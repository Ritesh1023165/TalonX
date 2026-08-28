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

    Mints a genuinely FRESH identity (build_session_identity) in every
    other case, including any missing file or read/parse failure --
    fails closed toward minting a new, unambiguous identity rather than
    resuming something uncertain."""
    now = now or datetime.now(timezone.utc)
    identity_path = config.state_dir / "session_identity.json"
    lifecycle_path = config.state_dir / "lifecycle_state.json"
    if identity_path.exists() and lifecycle_path.exists():
        try:
            saved = json.loads(identity_path.read_text(encoding="utf-8"))
            lifecycle_state = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = lifecycle_state = None
        if isinstance(saved, dict) and isinstance(lifecycle_state, dict) and all(k in saved for k in _SESSION_IDENTITY_REQUIRED_FIELDS):
            today_et = now.astimezone(ET).date().isoformat()
            if (
                saved.get("trading_date_et") == today_et
                and lifecycle_state.get("session_enabled") is True
                and lifecycle_state.get("kill_switch") is not True
            ):
                return SessionIdentity(
                    session_id=saved["session_id"], trading_date_et=saved["trading_date_et"],
                    runtime_start_utc=saved["runtime_start_utc"], runtime_sha=saved["runtime_sha"],
                    config_hash=saved["config_hash"], feed_mode=saved["feed_mode"],
                )
    return build_session_identity(config, now=now)
