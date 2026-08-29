"""Task 83-R1 §5 -- durable, session-scoped PIV notification telemetry.

Authoritative evidence that PIV attempted zero outbound Telegram sends and
started zero inbound pollers -- persisted at the ACTUAL boundaries
(EventBus send path, inbound poller start), not inferred from optional
event-payload fields. Missing telemetry is UNVERIFIED, never zero.

The file (``<state_dir>/piv_notification_telemetry.json``) is updated by an
atomic read-merge-write so the EventBus (outbound) and the CLI runtime
(ownership + inbound) can both contribute without clobbering each other.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

TELEMETRY_NAME = "piv_notification_telemetry.json"


def _empty(session_id: str | None, trading_date_et: str | None) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "trading_date_et": trading_date_et,
        "ownership": {
            "outbound_enabled": False,
            "sender_constructed": False,
            "inbound_poller_constructed": False,
            "inbound_poller_started": False,
        },
        "outbound": {"attempts": 0, "successes": 0, "failures": 0, "last_attempt_at": None},
        "inbound": {"poll_starts": 0, "poll_attempts": 0, "last_start_at": None},
        "updated_at": None,
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def load_telemetry(state_dir: Path) -> dict[str, Any] | None:
    p = Path(state_dir) / TELEMETRY_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def merge_telemetry(
    state_dir: Path,
    *,
    session_id: str | None = None,
    trading_date_et: str | None = None,
    ownership: dict[str, Any] | None = None,
    outbound: dict[str, Any] | None = None,
    inbound: dict[str, Any] | None = None,
    outbound_delta: dict[str, int] | None = None,
    inbound_delta: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Atomic read-merge-write. ``*_delta`` args ADD to the existing
    counters; ``ownership``/``outbound``/``inbound`` replace fields."""
    path = Path(state_dir) / TELEMETRY_NAME
    current = load_telemetry(state_dir) or _empty(session_id, trading_date_et)
    if session_id is not None:
        current["session_id"] = session_id
    if trading_date_et is not None:
        current["trading_date_et"] = trading_date_et
    if ownership:
        _deep_merge(current.setdefault("ownership", {}), ownership)
    if outbound:
        _deep_merge(current.setdefault("outbound", {}), outbound)
    if inbound:
        _deep_merge(current.setdefault("inbound", {}), inbound)
    for section, delta in (("outbound", outbound_delta), ("inbound", inbound_delta)):
        if not delta:
            continue
        tgt = current.setdefault(section, {})
        for k, n in delta.items():
            tgt[k] = int(tgt.get(k, 0) or 0) + int(n)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(path, current)
    return current
