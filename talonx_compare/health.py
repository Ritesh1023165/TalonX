"""Task 83 §3 -- the explicit health-state contract shared by the browser
dashboard, the Streamlit dashboard, and the collector's own diagnostics.

The whole point of this module: a missing / unreadable / stale / not-run
source is NEVER allowed to render as a plausible-looking zero. Each of the
nine states below is a distinct, named condition, and every classifier
here returns one of them plus a human-readable detail string and the
timestamp/age it was judged against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

# --- the nine explicit health states (Task 83 §3) ---
RUNNING = "RUNNING"            # process/loop is live right now
HEALTHY = "HEALTHY"            # present, fresh, internally consistent
DEGRADED = "DEGRADED"          # present but with recorded problems / partial data
STALE = "STALE"               # present, but newest record older than the freshness bound
MISSING = "MISSING"           # a required source is absent
DISCONNECTED = "DISCONNECTED" # a live transport (Redis) could not be reached
NOT_RUN = "NOT_RUN"           # nothing has run for this scope yet (NOT "zero activity")
UNREADABLE = "UNREADABLE"     # present but corrupt / unparseable
WRONG_SESSION = "WRONG_SESSION"  # present, but belongs to another session/date

HEALTH_STATES = (
    RUNNING, HEALTHY, DEGRADED, STALE, MISSING, DISCONNECTED, NOT_RUN, UNREADABLE, WRONG_SESSION,
)

# States that mean "you may read a count off this source and trust it as
# genuine". Anything else must be surfaced as its named condition, and a
# UI must not print a bare 0 next to it.
_TRUSTWORTHY = frozenset({RUNNING, HEALTHY})


@dataclass(frozen=True)
class SourceHealth:
    state: str
    detail: str
    last_update: str | None = None      # ISO-8601, if the source carries one
    age_seconds: float | None = None    # now - last_update, if computable
    scope: str | None = None            # session_id / date this judgement is bound to

    @property
    def trustworthy_zero(self) -> bool:
        """True iff a 0 read from this source is a *real* zero (not an
        artefact of the source being absent/stale/wrong-session)."""
        return self.state in _TRUSTWORTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "detail": self.detail,
            "last_update": self.last_update,
            "age_seconds": self.age_seconds,
            "scope": self.scope,
            "trustworthy_zero": self.trustworthy_zero,
        }


def _age(last_update_iso: str | None, now: datetime) -> float | None:
    if not last_update_iso:
        return None
    try:
        ts = datetime.fromisoformat(last_update_iso)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds()


def classify_json_file(
    path: Path,
    *,
    required: bool,
    now: datetime | None = None,
    stale_seconds: int | None = None,
    expected_session_id: str | None = None,
    session_id_field: str = "session_id",
    last_update_field: str | None = None,
    run_corroborated: bool = True,
) -> SourceHealth:
    """Classify one JSON state file.

    - absent + required   -> MISSING
    - absent + optional   -> NOT_RUN
    - present, unparseable -> UNREADABLE
    - present, wrong session_id -> WRONG_SESSION
    - present, newest record older than stale bound -> STALE
    - present, empty, no run corroborated -> NOT_RUN
    - present, empty, run corroborated     -> HEALTHY (a real, verified zero)
    - otherwise -> HEALTHY (or DEGRADED if the payload flags problems)
    """
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return SourceHealth(MISSING if required else NOT_RUN,
                            f"{path.name} does not exist")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return SourceHealth(UNREADABLE, f"{path.name}: {type(exc).__name__}: {exc}")
    stripped = text.strip()
    if not stripped:
        if required and not run_corroborated:
            return SourceHealth(NOT_RUN, f"{path.name} is empty and no run is corroborated")
        return SourceHealth(HEALTHY if run_corroborated else NOT_RUN,
                            f"{path.name} is empty" + (" (verified zero)" if run_corroborated else ""))
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return SourceHealth(UNREADABLE, f"{path.name}: JSON error: {exc}")

    last_update = None
    if last_update_field and isinstance(data, dict):
        last_update = data.get(last_update_field)
    age = _age(last_update, now)

    if expected_session_id is not None and isinstance(data, dict):
        found = data.get(session_id_field)
        if found is not None and found != expected_session_id:
            return SourceHealth(WRONG_SESSION,
                                f"{path.name} belongs to session {found!r}, expected {expected_session_id!r}",
                                last_update, age, expected_session_id)

    if age is not None and stale_seconds is not None and age > stale_seconds:
        return SourceHealth(STALE,
                            f"{path.name} newest record is {age:.0f}s old (> {stale_seconds}s)",
                            last_update, age, expected_session_id)

    if isinstance(data, dict) and (data.get("errors") or data.get("diagnostics")):
        return SourceHealth(DEGRADED, f"{path.name} present with recorded diagnostics",
                            last_update, age, expected_session_id)

    empty = (isinstance(data, (list, dict)) and len(data) == 0)
    if empty and not run_corroborated:
        return SourceHealth(NOT_RUN, f"{path.name} has no records and no run is corroborated",
                            last_update, age, expected_session_id)
    return SourceHealth(HEALTHY, f"{path.name} present with records" if not empty
                        else f"{path.name} present, verified zero records",
                        last_update, age, expected_session_id)


def classify_jsonl_stream(
    path: Path,
    *,
    now: datetime | None = None,
    stale_seconds: int | None = None,
    timestamp_field: str = "timestamp",
    scope_field: str | None = None,
    expected_scope: str | None = None,
) -> SourceHealth:
    """Classify an append-only ``.jsonl`` stream (e.g. piv_events.jsonl).
    STALE if the newest parseable line is older than the bound; UNREADABLE
    if any line fails to parse; WRONG_SESSION if none of the lines match
    the expected scope while some other scope is present."""
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return SourceHealth(MISSING, f"{path.name} does not exist")
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return SourceHealth(UNREADABLE, f"{path.name}: {type(exc).__name__}: {exc}")
    if not lines:
        return SourceHealth(NOT_RUN, f"{path.name} is present but empty")
    newest_ts: str | None = None
    scopes_seen: set[str] = set()
    in_scope = 0
    for ln in lines:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as exc:
            return SourceHealth(UNREADABLE, f"{path.name}: unparseable line: {exc}")
        ts = row.get(timestamp_field)
        if ts and (newest_ts is None or ts > newest_ts):
            newest_ts = ts
        if scope_field is not None:
            sc = row.get(scope_field)
            if sc is not None:
                scopes_seen.add(sc)
                if expected_scope is not None and sc == expected_scope:
                    in_scope += 1
    if expected_scope is not None and scope_field is not None and in_scope == 0 and scopes_seen:
        return SourceHealth(WRONG_SESSION,
                            f"{path.name} has {len(lines)} record(s), none for {expected_scope!r} "
                            f"(present: {sorted(scopes_seen)})", newest_ts,
                            _age(newest_ts, now), expected_scope)
    age = _age(newest_ts, now)
    if age is not None and stale_seconds is not None and age > stale_seconds:
        return SourceHealth(STALE, f"{path.name} newest record is {age:.0f}s old (> {stale_seconds}s)",
                            newest_ts, age, expected_scope)
    return SourceHealth(HEALTHY, f"{path.name}: {len(lines)} record(s), newest {newest_ts}",
                        newest_ts, age, expected_scope)


def classify_redis(ping_ok: bool | None, *, detail: str = "") -> SourceHealth:
    """ping_ok is None when no attempt was made (offline rehearsal)."""
    if ping_ok is None:
        return SourceHealth(NOT_RUN, detail or "Redis not contacted (offline)")
    if ping_ok:
        return SourceHealth(RUNNING, detail or "Redis reachable")
    return SourceHealth(DISCONNECTED, detail or "Redis unreachable")


def classify_pipeline_run(
    *,
    corroborated: bool,
    live: bool,
    stale: bool = False,
    degraded: bool = False,
    detail: str = "",
) -> SourceHealth:
    """Top-level "did this pipeline run at all / is it running now" verdict.
    ``NOT_RUN`` is explicitly distinct from a zero-count healthy run."""
    if live:
        return SourceHealth(RUNNING, detail or "pipeline loop is live")
    if not corroborated:
        return SourceHealth(NOT_RUN, detail or "no session/run corroborated for this scope")
    if stale:
        return SourceHealth(STALE, detail or "run corroborated but no recent activity")
    if degraded:
        return SourceHealth(DEGRADED, detail or "run corroborated with recorded problems")
    return SourceHealth(HEALTHY, detail or "run corroborated and consistent")


# --- Known capability limitation (Task 83 §6) -------------------------------

QUANT_STATE_STORE_LIMITATION = {
    "capability": "piv_durable_quant_state_store",
    "state": "NOT_IMPLEMENTED",
    "detail": (
        "The reused in-process PIV QuantScanner runs WITHOUT a durable "
        "QuantStateStore: rolling bar buffers and funnel counters live in "
        "memory only and do not survive a PIV restart. Task 82 reserved an "
        "isolated path (<piv state_dir>/piv_quant.db) so a future enablement "
        "cannot select Original's database -- but that reserved, isolated "
        "path DOES NOT mean persistence exists today. Any PIV Quant counter "
        "shown in a dashboard is session-lifetime-only."
    ),
    "isolated_path_reserved": True,
    "persistence_exists": False,
}
