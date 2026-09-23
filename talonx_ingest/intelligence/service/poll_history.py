"""
talonx_ingest.intelligence.service.poll_history -- durable, bounded, append-only poll history
=========================================================================================
Closes the prospective-validation observability gap behind ``FULL_PROSPECTIVE_COVERAGE = YES_WITH_INFERENCE``:
the service heartbeat/progress files are overwritten every cycle, so there was no durable per-poll record.

One JSON line per completed poll cycle in ``<state_dir>/poll_history.jsonl``. Bounded: when the file exceeds
``max_bytes`` it is rotated to ``poll_history.jsonl.1`` (one generation kept). Pure telemetry -- nothing reads it
for a decision (V2 admission and Intelligence delivery never consult it), it holds no secrets (counts, freshness
and cause codes only; never error text), and any failure to write is swallowed by the caller.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE_NAME = "poll_history.jsonl"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024       # ~15-20k cycles; one rotated generation kept


def record(state_dir: Path, *, cycle: int, summary: dict, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
    rec = {
        "at_utc": summary.get("at_utc"),
        "cycle": cycle,
        "symbols_polled": summary.get("symbols_polled"),
        "symbols_failed": summary.get("symbols_failed"),
        "new_form4": summary.get("new_form4"),
        "new_events": summary.get("new_events"),
        "freshness": summary.get("freshness"),
        "error_count": len(summary.get("errors") or []),
        "recovery_timed_out": (summary.get("recovery") or {}).get("timed_out"),
        "recovery_failed": (summary.get("recovery") or {}).get("failed"),
        "delivery_ok": summary.get("delivery_ok"),
        "health_causes": summary.get("health_causes") or [],
    }
    path = Path(state_dir) / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_bytes:
        path.replace(path.with_name(FILE_NAME + ".1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def read(state_dir: Path) -> list[dict]:
    out: list[dict] = []
    for p in (Path(state_dir) / (FILE_NAME + ".1"), Path(state_dir) / FILE_NAME):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
    return out
