"""Freeze Task 61R's outcome-blind temporal correction before data access."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import exchange_calendars as xcals


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task61r_fprc_v1_independent_validation_1"
BASE_COMMIT = "24afb118f913b3c9bd64e4c01f095bcc46800324"
FPRC_FINGERPRINT = "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"
CURRENT_STRATEGY_FINGERPRINT = "2ae6216bca70"
CALENDAR = "XNYS"
CALENDAR_VERSION = "4.13.2"
AS_OF_DATE = date(2026, 8, 23)
EXPOSURE_BOUNDARY = date(2025, 8, 15)
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL",
    "STX", "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO",
    "GILD", "HON", "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU",
    "NFLX", "PANW", "PEP", "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]

# Conservatively includes evaluation and context bars read by Tasks 37-58.
# Reuse-only tasks point at their canonical source interval rather than silently
# appearing outcome-free.
EXPOSURE_GROUPS = [
    ("37-38,41", "Task37 A/B/C reused for volatility development", "2025-08-29", "2026-07-31"),
    ("39-45", "design/implementation; any empirical inputs reuse Task37 or recent 2026 startup data", "2025-08-29", "2026-08-23"),
    ("46-53", "X/Y/Z evaluation plus Task53 causal warmups; reused by Tasks47-52", "2025-10-13", "2026-06-09"),
    ("54", "W1/W2/W3 warmup and evaluation packages", "2025-09-15", "2026-05-18"),
    ("55", "Task53/54 trade evidence only", "2025-09-29", "2026-05-18"),
    ("56", "H1/H2/H3 warmup and independent evaluation packages", "2025-12-11", "2026-07-09"),
    ("57", "Task53/54/56 trade evidence only", "2025-09-29", "2026-07-09"),
    ("58", "Task53/54/56 trades and corresponding entry/exit bar context", "2025-09-29", "2026-07-09"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sessions(calendar: Any, start: str, end: str) -> list[str]:
    return [item.date().isoformat() for item in calendar.sessions_in_range(start, end)]


def resolve() -> dict[str, Any]:
    observed_version = version("exchange-calendars")
    if observed_version != CALENDAR_VERSION:
        raise RuntimeError(f"Expected exchange-calendars {CALENDAR_VERSION}, got {observed_version}")
    calendar = xcals.get_calendar(CALENDAR)
    eligible = sessions(calendar, "2024-01-01", (EXPOSURE_BOUNDARY.replace(day=14)).isoformat())
    evaluation = eligible[-60:]
    if len(evaluation) != 60 or evaluation[-1] >= EXPOSURE_BOUNDARY.isoformat():
        raise RuntimeError("Could not resolve a 60-session block strictly before exposure")
    all_sessions = sessions(calendar, "2024-01-01", evaluation[-1])
    windows: list[dict[str, Any]] = []
    for index, name in enumerate(("V1", "V2", "V3")):
        evaluation_sessions = evaluation[index * 20 : (index + 1) * 20]
        start_index = all_sessions.index(evaluation_sessions[0])
        warmup_sessions = all_sessions[start_index - 10 : start_index]
        windows.append(
            {
                "name": name,
                "warmup_start": warmup_sessions[0],
                "warmup_end": warmup_sessions[-1],
                "warmup_sessions": warmup_sessions,
                "evaluation_start": evaluation_sessions[0],
                "evaluation_end": evaluation_sessions[-1],
                "evaluation_sessions": evaluation_sessions,
            }
        )
    return {
        "evaluation": evaluation,
        "windows": windows,
        "download_start": windows[0]["warmup_start"],
        "download_end": windows[-1]["evaluation_end"],
    }


def build() -> dict[str, Any]:
    resolved = resolve()
    evaluation_start = date.fromisoformat(resolved["evaluation"][0])
    evaluation_end = date.fromisoformat(resolved["evaluation"][-1])
    audit_rows = []
    for tasks, description, start, end in EXPOSURE_GROUPS:
        overlap = not (
            evaluation_end < date.fromisoformat(start)
            or evaluation_start > date.fromisoformat(end)
        )
        audit_rows.append(
            {
                "tasks": tasks,
                "exposure_description": description,
                "conservative_start": start,
                "conservative_end": end,
                "evaluation_overlap": overlap,
            }
        )
    if any(row["evaluation_overlap"] for row in audit_rows):
        raise RuntimeError("Temporal correction overlaps Task37-58 exposure")

    protocol = ROOT / "results/task59_candidate_architecture_triage/next_validation_protocol.md"
    task61_manifest = ROOT / "results/task61_fprc_v1_independent_validation_1/window_manifest.json"
    task60_freeze = ROOT / "results/task60_fprc_v1_implementation_freeze/task60_implementation_freeze.json"
    task60 = json.loads(task60_freeze.read_text(encoding="utf-8"))
    if task60["implementation_fingerprint_sha256"] != FPRC_FINGERPRINT:
        raise RuntimeError("FPRC_V1 implementation fingerprint mismatch")

    manifest = {
        "task": "61R",
        "base_commit": BASE_COMMIT,
        "as_of_date": AS_OF_DATE.isoformat(),
        "calendar": CALENDAR,
        "exchange_calendars_version": CALENDAR_VERSION,
        "temporal_correction_only": True,
        "selection_rule": (
            "Identify 2025-08-15 as the earliest documented TalonX canonical strategy-development/"
            "evaluation data exposure (Task7B). From XNYS sessions strictly before that boundary, "
            "select the chronologically latest 60 consecutive sessions, maximizing proximity and "
            "Alpaca availability while remaining entirely pre-exposure; split 20/20/20."
        ),
        "earliest_documented_talonx_exposure": {
            "date": EXPOSURE_BOUNDARY.isoformat(),
            "evidence": "Research ledger Task7B requested range begins 2025-08-15 and feeds Tasks8-22",
        },
        "windows": resolved["windows"],
        "download_package": {
            "provider": "Alpaca",
            "start": resolved["download_start"],
            "end": resolved["download_end"],
            "symbols": 35,
        },
        "universe": UNIVERSE,
        "universe_count": len(UNIVERSE),
        "frozen_candidate": {
            "name": "FPRC_V1",
            "implementation_fingerprint": FPRC_FINGERPRINT,
            "current_candidate_strategy_fingerprint": CURRENT_STRATEGY_FINGERPRINT,
            "provider": "Alpaca only",
            "cost_accounting_bps_per_side": [0, 5],
            "max_estimated_and_actual_fill_cost_R_5bps": 0.20,
            "all_non_temporal_rules": "unchanged from Task59 next_validation_protocol.md",
        },
        "source_hashes": {
            "results/task59_candidate_architecture_triage/next_validation_protocol.md": sha256(protocol),
            "results/task60_fprc_v1_implementation_freeze/task60_implementation_freeze.json": sha256(task60_freeze),
            "results/task61_fprc_v1_independent_validation_1/window_manifest.json": sha256(task61_manifest),
        },
        "outcome_access_before_freeze": False,
        "alpaca_requests_before_freeze": 0,
        "fprc_replays_before_freeze": 0,
    }
    audit = {
        "task": "61R",
        "status": "PASS",
        "candidate_evaluation_start": resolved["evaluation"][0],
        "candidate_evaluation_end": resolved["evaluation"][-1],
        "strictly_before_earliest_documented_exposure": evaluation_end < EXPOSURE_BOUNDARY,
        "task37_58_overlap": False,
        "task53_58_design_evidence_overlap": False,
        "rows": audit_rows,
        "audit_boundary_note": (
            "The candidate block ends one XNYS session before the Task7B canonical dataset begins; "
            "therefore it also precedes every Task37-58 evaluation/context interval."
        ),
    }
    schema = {
        "schema_version": 1,
        "always": [
            "corrected_window_manifest.json", "contamination_audit.json",
            "contamination_audit.csv", "artifact_schema.json", "pre_replay_gates.json",
            "task61r_summary.json", "task61r_summary.md", "task61r_conclusion.md",
        ],
        "if_blocked": ["validation_blocker.json"],
        "if_replayed": [
            "trades.csv", "rejections.csv", "aggregate_economics.json",
            "window_economics.csv", "symbol_economics.csv", "time_bucket_economics.csv",
            "geometry_cost_economics.csv", "exit_path_economics.csv", "excursion.csv",
            "winner_loser_sensitivity.csv", "concentration.json", "parity_diagnostics.json",
            "criteria.json", "replay_manifest.json",
        ],
        "classification_enum": [
            "FPRC_V1_REPLICATION_REQUIRED", "FPRC_V1_REJECTED", "VALIDATION_BLOCKED"
        ],
    }
    return {"manifest": manifest, "audit": audit, "schema": schema}


def write(payloads: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("corrected_window_manifest.json", payloads["manifest"]),
        ("contamination_audit.json", payloads["audit"]),
        ("artifact_schema.json", payloads["schema"]),
    ):
        (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (OUT / "contamination_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payloads["audit"]["rows"][0]))
        writer.writeheader()
        writer.writerows(payloads["audit"]["rows"])


def check(payloads: dict[str, Any]) -> None:
    for name, key in (
        ("corrected_window_manifest.json", "manifest"),
        ("contamination_audit.json", "audit"),
        ("artifact_schema.json", "schema"),
    ):
        observed = json.loads((OUT / name).read_text(encoding="utf-8"))
        if observed != payloads[key]:
            raise RuntimeError(f"Non-deterministic artifact: {name}")


if __name__ == "__main__":
    payloads = build()
    write(payloads)
    check(payloads)
    print(json.dumps({
        "temporal_correction": "PASS",
        "untouched_data_audit": payloads["audit"]["status"],
        "windows": [
            {
                "name": item["name"],
                "warmup": [item["warmup_start"], item["warmup_end"]],
                "evaluation": [item["evaluation_start"], item["evaluation_end"]],
            }
            for item in payloads["manifest"]["windows"]
        ],
    }, indent=2))
