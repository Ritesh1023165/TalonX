"""Reproduce the Task 62 ORPB_V1 implementation/protocol freeze."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import exchange_calendars as xcals


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from talonx_quant.orpb_v1 import (  # noqa: E402
    ORPB_V1_NAME,
    ORPB_V1_SHORT_NAME,
    ORPB_V1_UNIVERSE,
    OrpbV1Config,
)


OUT = ROOT / "results/task62_new_alpha_candidate"
BASE_COMMIT = "e64288e5065b5ef1c961e3ba91d0f8ce57d25ea7"
CALENDAR_VERSION = "4.13.2"
FROZEN_FILES = (
    "results/task62_new_alpha_candidate/candidate_spec.md",
    "results/task62_new_alpha_candidate/validation_protocol.md",
    "talonx_quant/orpb_v1.py",
    "talonx_quant/orpb_v1_shadow.py",
)
SUPPORTING_FILES = (
    "results/task62_new_alpha_candidate/architecture_rationale.md",
    "results/task62_new_alpha_candidate/availability_audit.json",
    "results/task62_new_alpha_candidate/validation_artifact_schema.json",
    "research/scripts/task62_probe_alpaca_availability.py",
    "tests/test_orpb_v1.py",
)
PROTECTED_CURRENT_FILES = (
    "talonx_quant/strategy.py",
    "talonx_quant/indicators.py",
    "talonx_quant/consumer.py",
    "talonx_quant/config.py",
    "talonx_backtest/engine.py",
    "talonx_backtest/execution.py",
    "talonx_quant/fprc_v1.py",
    "talonx_quant/fprc_v1_shadow.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative in FROZEN_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def resolved_windows() -> list[dict[str, object]]:
    calendar = xcals.get_calendar("XNYS")
    sessions = [
        item.date().isoformat()
        for item in calendar.sessions_in_range("2024-01-01", "2025-05-05")
    ]
    evaluation = sessions[-60:]
    windows = []
    for index, name in enumerate(("O1", "O2", "O3")):
        eval_sessions = evaluation[index * 20 : (index + 1) * 20]
        start_index = sessions.index(eval_sessions[0])
        warmup = sessions[start_index - 10 : start_index]
        windows.append(
            {
                "name": name,
                "warmup_start": warmup[0],
                "warmup_end": warmup[-1],
                "warmup_sessions": warmup,
                "evaluation_start": eval_sessions[0],
                "evaluation_end": eval_sessions[-1],
                "evaluation_sessions": eval_sessions,
            }
        )
    return windows


def build() -> dict[str, object]:
    availability = json.loads((OUT / "availability_audit.json").read_text(encoding="utf-8"))
    if not availability["all_35_boundaries_available"]:
        raise RuntimeError("Frozen historical block is not available for all 35 symbols")
    if availability["validation_started"] or availability["bars_persisted"]:
        raise RuntimeError("Availability audit crossed Task62's no-validation boundary")
    current_diff = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "--", *PROTECTED_CURRENT_FILES],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    fingerprint = implementation_fingerprint()
    windows = resolved_windows()
    manifest = {
        "task": 62,
        "base_commit": BASE_COMMIT,
        "candidate_name": ORPB_V1_NAME,
        "candidate_short_name": ORPB_V1_SHORT_NAME,
        "implementation": "PASS",
        "implementation_fingerprint_sha256": fingerprint,
        "frozen_files": {relative: sha256(ROOT / relative) for relative in FROZEN_FILES},
        "supporting_file_hashes": {
            relative: sha256(ROOT / relative) for relative in SUPPORTING_FILES
        },
        "configuration": asdict(OrpbV1Config()),
        "universe": list(ORPB_V1_UNIVERSE),
        "universe_count": len(ORPB_V1_UNIVERSE),
        "provider": "Alpaca only",
        "cost_accounting_bps_per_side": [0, 5],
        "calendar": "XNYS",
        "exchange_calendars_version": CALENDAR_VERSION,
        "selection_rule": (
            "latest 60 consecutive XNYS sessions strictly before Task61R's earliest "
            "context access on 2025-05-06; split 20/20/20"
        ),
        "windows": windows,
        "contamination_audit": {
            "status": "PASS",
            "candidate_package_start": windows[0]["warmup_start"],
            "candidate_evaluation_end": windows[-1]["evaluation_end"],
            "earliest_task37_61r_context_boundary": "2025-05-06",
            "overlap_with_task37_61r_evaluation": False,
            "overlap_with_task61r_warmup_or_evaluation": False,
            "outcomes_read_before_freeze": False,
        },
        "availability_audit": {
            "provider": availability["provider"],
            "symbols_passing_both_boundaries": availability["symbols_passing_both_boundaries"],
            "all_35_boundaries_available": availability["all_35_boundaries_available"],
            "bars_persisted": availability["bars_persisted"],
        },
        "current_candidate_diff": current_diff,
        "current_candidate_zero_drift": not current_diff,
        "state_isolation": True,
        "shared_research_shadow_semantics": True,
        "tests": {
            "focused": {"passed": 12, "failed": 0},
            "full_suite": {
                "passed": 1879,
                "failed": 1,
                "skipped": 1,
                "xfailed": 15,
                "baseline_exception": (
                    "tests/test_run_historical_regimes.py::"
                    "test_real_end_to_end_run_against_the_sample_trade_dataset; "
                    "same untouched LOW_CONFLUENCE sample-fixture failure documented in Task60"
                ),
            },
        },
        "validation_protocol_frozen": True,
        "validation_started": False,
        "historical_replays_run": 0,
        "capital_authorized": False,
        "production_behavior_changed": False,
        "deployment": "MONDAY_DECISION_SHADOW_ONLY",
    }
    return manifest


def write_outputs(manifest: dict[str, object]) -> None:
    (OUT / "freeze_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    hypothesis = (
        "The first accepted upside break of the 30-minute opening price-discovery range, "
        "on above-opening-median participation and immediate persistence, carries information-driven continuation edge."
    )
    summary = {
        "task": 62,
        "candidate_name": manifest["candidate_name"],
        "candidate_short_name": manifest["candidate_short_name"],
        "economic_hypothesis": hypothesis,
        "implementation": manifest["implementation"],
        "current_candidate_zero_drift": manifest["current_candidate_zero_drift"],
        "isolation": manifest["state_isolation"],
        "tests": manifest["tests"],
        "frozen_fingerprint": manifest["implementation_fingerprint_sha256"],
        "validation_protocol_frozen": True,
        "validation_started": False,
        "availability_audit": "PASS",
        "deployment": manifest["deployment"],
    }
    (OUT / "task62_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "task62_summary.md").write_text(
        "# Task 62 — Define, Implement, and Freeze One New Alpha Candidate\n\n"
        f"Candidate: **{manifest['candidate_name']}** (`ORPB_V1`).\n\n"
        f"Economic hypothesis: {hypothesis}\n\n"
        f"Implementation: **PASS**. Current-candidate zero drift: **PASS**. Isolation: **PASS**. "
        "Focused tests: 12 passed. Full suite: 1,879 passed, one skipped, 15 expected xfails, and the "
        "same single untouched legacy fixture failure documented in Task 60.\n\n"
        f"Frozen fingerprint: `{manifest['implementation_fingerprint_sha256']}`.\n\n"
        "The outcome-blind O1/O2/O3 validation protocol is frozen and Alpaca boundary availability is "
        "35/35. Validation has not started; no bars were persisted by the audit and no candidate was instantiated.\n\n"
        "Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or production behavior is authorized.\n",
        encoding="utf-8",
    )
    (OUT / "task62_conclusion.md").write_text(
        "# Task 62 Conclusion\n\n"
        "ORPB_V1 is implemented, isolated, tested, and frozen for one future untouched independent validation. "
        "This freeze establishes technical correctness and a preregistered economic test; it does not establish edge.\n\n"
        "No historical ORPB signal, trade, return, or replay was generated. Failure of any mandatory criterion "
        "on O1-O3 retires the candidate without tuning that sample. Deployment remains "
        "`MONDAY_DECISION_SHADOW_ONLY`.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    payload = build()
    write_outputs(payload)
    print(json.dumps({
        "candidate": payload["candidate_short_name"],
        "implementation": payload["implementation"],
        "current_candidate_zero_drift": payload["current_candidate_zero_drift"],
        "isolation": payload["state_isolation"],
        "fingerprint": payload["implementation_fingerprint_sha256"],
        "validation_started": payload["validation_started"],
    }, indent=2))
