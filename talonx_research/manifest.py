"""
Machine-readable validation / promotion manifest (Task 115.F).

A VALIDATION_PASS never sets ``promotion_allowed`` -- promotion is an
explicit separate action (R6).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_manifest(*, strategy: str, version: int, fingerprint: str,
                   validation_window: dict, discovery_window: dict, holdout_window: dict,
                   primary_cost_bps: int, verdict: str, shadow_eligible: bool,
                   runtime_parity: str, gate_checks: dict, metrics_summary: dict,
                   extra: dict | None = None) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "version": version,
        "version_id": f"{strategy}@{version}",
        "fingerprint": fingerprint,
        "validation_window": validation_window,
        "discovery_window": discovery_window,
        "holdout_window": holdout_window,
        "primary_cost_bps": primary_cost_bps,
        "verdict": verdict,
        "shadow_eligible": bool(shadow_eligible),
        "runtime_parity": runtime_parity,
        "promotion_allowed": False,           # ALWAYS false here -- R6
        "promotion_note": "Validation PASS does NOT equal ACTIVE promotion. Promotion is an "
                          "explicit, separately-authorised decision (HYPOTHESIS -> DISCOVERY -> "
                          "FREEZE -> HOLDOUT -> 2-YEAR REPLAY -> VERDICT -> SHADOW_ELIGIBLE -> "
                          "LIVE SHADOW -> PROMOTION DECISION -> ACTIVE).",
        "gate_checks": gate_checks,
        "metrics_summary": metrics_summary,
        "extra": extra or {},
    }


def write_manifest(manifest: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, default=str))
    tmp.replace(p)
    return p
