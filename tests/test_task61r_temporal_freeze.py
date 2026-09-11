from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research" / "scripts" / "task61r_freeze_temporal_protocol.py"
SPEC = importlib.util.spec_from_file_location("task61r_freeze", SCRIPT)
assert SPEC and SPEC.loader
task61r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task61r)


def test_corrected_windows_are_exact_and_complete() -> None:
    payloads = task61r.build()
    windows = payloads["manifest"]["windows"]
    assert [(item["name"], item["evaluation_start"], item["evaluation_end"]) for item in windows] == [
        ("V1", "2025-05-20", "2025-06-17"),
        ("V2", "2025-06-18", "2025-07-17"),
        ("V3", "2025-07-18", "2025-08-14"),
    ]
    assert [(item["warmup_start"], item["warmup_end"]) for item in windows] == [
        ("2025-05-06", "2025-05-19"),
        ("2025-06-04", "2025-06-17"),
        ("2025-07-03", "2025-07-17"),
    ]
    assert all(len(item["evaluation_sessions"]) == 20 for item in windows)
    assert all(len(item["warmup_sessions"]) == 10 for item in windows)
    evaluation = [session for item in windows for session in item["evaluation_sessions"]]
    assert len(evaluation) == len(set(evaluation)) == 60


def test_block_is_strictly_pre_exposure_and_uncontaminated() -> None:
    payloads = task61r.build()
    audit = payloads["audit"]
    assert audit["status"] == "PASS"
    assert audit["strictly_before_earliest_documented_exposure"] is True
    assert audit["task37_58_overlap"] is False
    assert audit["task53_58_design_evidence_overlap"] is False
    assert not any(row["evaluation_overlap"] for row in audit["rows"])
    assert payloads["manifest"]["outcome_access_before_freeze"] is False
    assert payloads["manifest"]["alpaca_requests_before_freeze"] == 0
    assert payloads["manifest"]["fprc_replays_before_freeze"] == 0


def test_only_temporal_contract_changed() -> None:
    manifest = task61r.build()["manifest"]
    assert manifest["temporal_correction_only"] is True
    assert manifest["universe_count"] == 35
    assert len(manifest["universe"]) == len(set(manifest["universe"])) == 35
    assert manifest["frozen_candidate"]["implementation_fingerprint"] == (
        "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"
    )
    assert manifest["frozen_candidate"]["cost_accounting_bps_per_side"] == [0, 5]
    assert manifest["frozen_candidate"]["max_estimated_and_actual_fill_cost_R_5bps"] == 0.20
