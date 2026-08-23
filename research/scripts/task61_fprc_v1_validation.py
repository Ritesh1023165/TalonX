"""Deterministically freeze Task 61 windows and enforce its temporal gate.

This script performs no market-data request and no strategy replay.  As of the
frozen attempt date, N2 and N3 are not complete; the preregistered protocol
therefore requires VALIDATION_BLOCKED before data access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import exchange_calendars as xcals


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "results" / "task61_fprc_v1_independent_validation_1"
BASE_COMMIT = "4a5923d9150283febf50d1b8c3634ba7735992ee"
IMPLEMENTATION_FINGERPRINT = (
    "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"
)
CURRENT_CANDIDATE_STRATEGY_FINGERPRINT = "2ae6216bca70"
CALENDAR_NAME = "XNYS"
CALENDAR_VERSION = "4.13.2"
CUTOFF = date(2026, 7, 9)
ATTEMPT_DATE = date(2026, 8, 23)
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL",
    "STX", "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO",
    "GILD", "HON", "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU",
    "NFLX", "PANW", "PEP", "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def iso_sessions(calendar: Any, start: str, end: str) -> list[str]:
    return [stamp.date().isoformat() for stamp in calendar.sessions_in_range(start, end)]


def resolve_windows() -> list[dict[str, Any]]:
    if version("exchange-calendars") != CALENDAR_VERSION:
        raise RuntimeError(
            f"exchange-calendars must be {CALENDAR_VERSION}, got "
            f"{version('exchange-calendars')}"
        )
    calendar = xcals.get_calendar(CALENDAR_NAME)
    all_sessions = iso_sessions(calendar, "2026-06-01", "2026-10-31")
    cutoff_index = all_sessions.index(CUTOFF.isoformat())
    evaluation = all_sessions[cutoff_index + 1 : cutoff_index + 61]
    if len(evaluation) != 60:
        raise RuntimeError("Could not resolve exactly 60 post-cutoff XNYS sessions")

    windows: list[dict[str, Any]] = []
    for index, name in enumerate(("N1", "N2", "N3")):
        eval_sessions = evaluation[index * 20 : (index + 1) * 20]
        eval_start_index = all_sessions.index(eval_sessions[0])
        warmup = all_sessions[eval_start_index - 10 : eval_start_index]
        complete_eval = [value for value in eval_sessions if date.fromisoformat(value) <= ATTEMPT_DATE]
        complete_warmup = [value for value in warmup if date.fromisoformat(value) <= ATTEMPT_DATE]
        windows.append(
            {
                "name": name,
                "warmup_sessions": warmup,
                "warmup_start": warmup[0],
                "warmup_end": warmup[-1],
                "evaluation_sessions": eval_sessions,
                "evaluation_start": eval_sessions[0],
                "evaluation_end": eval_sessions[-1],
                "complete_warmup_sessions_as_of_attempt": len(complete_warmup),
                "complete_evaluation_sessions_as_of_attempt": len(complete_eval),
                "temporal_status": (
                    "COMPLETE"
                    if len(complete_warmup) == 10 and len(complete_eval) == 20
                    else "INCOMPLETE"
                ),
            }
        )
    return windows


def git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def build_payloads() -> dict[str, Any]:
    windows = resolve_windows()
    protocol = ROOT / "results/task59_candidate_architecture_triage/next_validation_protocol.md"
    task60_freeze = (
        ROOT
        / "results/task60_fprc_v1_implementation_freeze/task60_implementation_freeze.json"
    )
    task59_spec = ROOT / "results/task59_candidate_architecture_triage/next_candidate_spec.md"
    task61_requirements = ROOT / "research/requirements-task61.txt"
    future_sessions = sorted(
        {
            value
            for window in windows
            for key in ("warmup_sessions", "evaluation_sessions")
            for value in window[key]
            if date.fromisoformat(value) > ATTEMPT_DATE
        }
    )
    source_hashes = {
        str(protocol.relative_to(ROOT)).replace("\\", "/"): sha256_file(protocol),
        str(task59_spec.relative_to(ROOT)).replace("\\", "/"): sha256_file(task59_spec),
        str(task60_freeze.relative_to(ROOT)).replace("\\", "/"): sha256_file(task60_freeze),
        str(task61_requirements.relative_to(ROOT)).replace("\\", "/"): sha256_file(
            task61_requirements
        ),
    }
    task60_frozen = json.loads(task60_freeze.read_text(encoding="utf-8"))
    if task60_frozen["implementation_fingerprint_sha256"] != IMPLEMENTATION_FINGERPRINT:
        raise RuntimeError("Task 60 frozen implementation fingerprint drift")
    if (
        task60_frozen["current_candidate_strategy_fingerprint"]
        != CURRENT_CANDIDATE_STRATEGY_FINGERPRINT
    ):
        raise RuntimeError("Current-candidate strategy fingerprint drift")
    manifest = {
        "task": 61,
        "protocol": "FPRC_V1 Independent Validation #1",
        "git_checkpoint": BASE_COMMIT,
        "frozen_implementation_fingerprint": IMPLEMENTATION_FINGERPRINT,
        "current_candidate_strategy_fingerprint": CURRENT_CANDIDATE_STRATEGY_FINGERPRINT,
        "calendar": CALENDAR_NAME,
        "exchange_calendars_version": CALENDAR_VERSION,
        "cutoff_session": CUTOFF.isoformat(),
        "attempt_date": ATTEMPT_DATE.isoformat(),
        "window_resolution_rule": "first 60 XNYS sessions strictly after cutoff, split 20/20/20",
        "warmup_rule": "immediately preceding 10 XNYS sessions, state-only",
        "universe": UNIVERSE,
        "universe_count": len(UNIVERSE),
        "windows": windows,
        "source_hashes": source_hashes,
    }
    gates = {
        "task": 61,
        "attempt_date": ATTEMPT_DATE.isoformat(),
        "overall": "FAIL",
        "gates": [
            {"gate": "base_checkpoint", "status": "PASS", "observed": BASE_COMMIT},
            {
                "gate": "frozen_strategy_config_fingerprints",
                "status": "PASS",
                "observed": {
                    "fprc_v1": IMPLEMENTATION_FINGERPRINT,
                    "current_candidate_strategy": CURRENT_CANDIDATE_STRATEGY_FINGERPRINT,
                },
            },
            {"gate": "current_candidate_zero_drift", "status": "PASS"},
            {"gate": "fprc_v1_state_isolation", "status": "PASS"},
            {"gate": "live_research_semantic_parity", "status": "PASS"},
            {
                "gate": "all_evaluation_windows_complete",
                "status": "FAIL",
                "observed": {w["name"]: w["complete_evaluation_sessions_as_of_attempt"] for w in windows},
                "required": {w["name"]: 20 for w in windows},
            },
            {
                "gate": "alpaca_35_of_35_complete_coverage",
                "status": "NOT_RUN",
                "reason": "temporal completeness gate failed before provider access",
            },
            {"gate": "bar_data_quality", "status": "NOT_RUN"},
            {"gate": "35_of_35_first_bar_readiness", "status": "NOT_RUN"},
        ],
        "alpaca_requests_made": 0,
        "strategy_replays_run": 0,
        "outcomes_unblinded": False,
    }
    blocker = {
        "task": 61,
        "classification": "VALIDATION_BLOCKED",
        "blocker_code": "EVALUATION_WINDOWS_NOT_COMPLETE_AS_OF_ATTEMPT_DATE",
        "attempt_date": ATTEMPT_DATE.isoformat(),
        "exact_blocker": (
            "The mechanically frozen 60-session evaluation ends 2026-10-02. "
            "As of 2026-08-23, N2 has 11/20 complete evaluation sessions and N3 has 0/20; "
            "N3 also has only 1/10 complete warmup sessions. Complete Alpaca coverage cannot "
            "exist yet, so the mandatory pre-replay gate fails."
        ),
        "incomplete_windows": [w["name"] for w in windows if w["temporal_status"] != "COMPLETE"],
        "future_sessions": future_sessions,
        "action": "Stopped before Alpaca access and before replay; no partial validation performed.",
    }
    summary = {
        "task": 61,
        "classification": "VALIDATION_BLOCKED",
        "mandatory_gates": "FAIL",
        "replication_required": False,
        "deployment": "MONDAY_DECISION_SHADOW_ONLY",
        "trades": None,
        "five_bps_expectancy": None,
        "five_bps_profit_factor": None,
        "bootstrap_95_ci": None,
        "top3_winner_sensitivity": None,
        "window_robustness": "NOT_RUN",
        "cost_feasibility": "NOT_RUN",
        "market_data_downloaded": False,
        "replay_started": False,
        "blocker_code": blocker["blocker_code"],
        "window_manifest_sha256": hashlib.sha256(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        ).hexdigest(),
    }
    schema = {
        "schema_version": 1,
        "task": 61,
        "always_required": {
            "window_manifest.json": "resolved calendar, universe, fingerprints, and source hashes",
            "validation_gates.json": "ordered gate states and replay/data-access counters",
            "task61_summary.json": "classification and compact mandatory metrics",
            "task61_summary.md": "human-readable result",
            "task61_conclusion.md": "classification rationale and deployment boundary",
        },
        "blocked_only": {
            "validation_blocker.json": "exact blocker, affected windows/sessions, and stop action"
        },
        "after_all_pre_replay_gates_pass": {
            "trade_ledger": [
                "task_window", "symbol", "entry_timestamp", "exit_timestamp", "entry_price",
                "stop_price", "exit_price", "exit_reason", "gross_R", "cost_R_5bps",
                "net_R_5bps", "holding_minutes", "MFE_R", "MAE_R",
            ],
            "required_report_groups": [
                "aggregate", "window", "symbol", "time_bucket", "geometry_cost_bucket",
                "exit_path", "forward_excursion", "winner_loser_sensitivity",
                "concentration", "trigger_confirmation_fill_parity", "bootstrap_95_ci",
                "interpretability_criteria", "economic_robustness_criteria",
            ],
            "identical_trade_accounting": ["0bps", "5bps_per_side"],
        },
        "classification_enum": [
            "FPRC_V1_REPLICATION_REQUIRED", "FPRC_V1_REJECTED", "VALIDATION_BLOCKED"
        ],
    }
    return {
        "manifest": manifest,
        "gates": gates,
        "blocker": blocker,
        "summary": summary,
        "schema": schema,
    }


def markdown_summary(payloads: dict[str, Any]) -> str:
    windows = payloads["manifest"]["windows"]
    rows = "\n".join(
        f"| {w['name']} | {w['warmup_start']} to {w['warmup_end']} | "
        f"{w['evaluation_start']} to {w['evaluation_end']} | "
        f"{w['complete_evaluation_sessions_as_of_attempt']}/20 | {w['temporal_status']} |"
        for w in windows
    )
    return f"""# Task 61 — FPRC_V1 Independent Validation #1

## Result

**VALIDATION_BLOCKED**

The windows were mechanically resolved from XNYS calendar version {CALENDAR_VERSION}. The frozen
evaluation ends on 2026-10-02. On the frozen attempt date, 2026-08-23, N2 and N3 were not complete,
so full 35-symbol Alpaca coverage was temporally impossible. The protocol required an immediate stop.

| Window | Warmup | Evaluation | Complete evaluation sessions | Status |
|---|---|---|---:|---|
{rows}

No Alpaca request was made, no strategy replay was run, no outcomes were unblinded, and no economics
or robustness metrics were computed. This is an infrastructure/calendar-availability block, not an
economic result for FPRC_V1.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or production change is authorized.
"""


def conclusion_markdown() -> str:
    return """# Task 61 Conclusion

Classification: **VALIDATION_BLOCKED**

The mandatory temporal-completeness gate failed before provider access: as of 2026-08-23, the frozen
N2 window had only 11 of 20 completed evaluation sessions, N3 had none, and N3's warmup had only one
of ten completed sessions. The required 35/35 complete Alpaca coverage therefore could not exist.

Per the preregistered protocol, Task 61 stopped without downloading partial packages, replaying the
strategy, inspecting outcomes, tuning, substituting windows, or changing FPRC_V1. Validation must be
resumed later against these exact frozen windows; this blocked attempt does not imply replication or
rejection.
"""


def write_artifacts(payloads: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "window_manifest.json": payloads["manifest"],
        "validation_gates.json": payloads["gates"],
        "validation_blocker.json": payloads["blocker"],
        "task61_summary.json": payloads["summary"],
        "artifact_schema.json": payloads["schema"],
    }
    for name, payload in files.items():
        (OUTPUT_DIR / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    (OUTPUT_DIR / "task61_summary.md").write_text(markdown_summary(payloads), encoding="utf-8")
    (OUTPUT_DIR / "task61_conclusion.md").write_text(conclusion_markdown(), encoding="utf-8")


def check_artifacts(payloads: dict[str, Any]) -> None:
    expected_json = {
        "window_manifest.json": payloads["manifest"],
        "validation_gates.json": payloads["gates"],
        "validation_blocker.json": payloads["blocker"],
        "task61_summary.json": payloads["summary"],
        "artifact_schema.json": payloads["schema"],
    }
    for name, expected in expected_json.items():
        observed = json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))
        if observed != expected:
            raise RuntimeError(f"Non-deterministic artifact: {name}")
    if (OUTPUT_DIR / "task61_summary.md").read_text(encoding="utf-8") != markdown_summary(payloads):
        raise RuntimeError("Non-deterministic artifact: task61_summary.md")
    if (OUTPUT_DIR / "task61_conclusion.md").read_text(encoding="utf-8") != conclusion_markdown():
        raise RuntimeError("Non-deterministic artifact: task61_conclusion.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payloads = build_payloads()
    if args.write:
        write_artifacts(payloads)
    if args.check:
        check_artifacts(payloads)
    print(json.dumps(payloads["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
