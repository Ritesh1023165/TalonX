from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research" / "scripts" / "task61_fprc_v1_validation.py"
SPEC = importlib.util.spec_from_file_location("task61_validation", SCRIPT)
assert SPEC and SPEC.loader
task61 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task61)


def test_task61_windows_are_mechanically_resolved() -> None:
    windows = task61.resolve_windows()
    assert [(item["name"], item["evaluation_start"], item["evaluation_end"]) for item in windows] == [
        ("N1", "2026-07-10", "2026-08-06"),
        ("N2", "2026-08-07", "2026-09-03"),
        ("N3", "2026-09-04", "2026-10-02"),
    ]
    assert [(item["warmup_start"], item["warmup_end"]) for item in windows] == [
        ("2026-06-25", "2026-07-09"),
        ("2026-07-24", "2026-08-06"),
        ("2026-08-21", "2026-09-03"),
    ]
    assert all(len(item["evaluation_sessions"]) == 20 for item in windows)
    assert all(len(item["warmup_sessions"]) == 10 for item in windows)
    flattened = [session for item in windows for session in item["evaluation_sessions"]]
    assert len(flattened) == len(set(flattened)) == 60


def test_task61_stops_at_temporal_gate_without_provider_or_replay() -> None:
    payloads = task61.build_payloads()
    windows = payloads["manifest"]["windows"]
    assert [item["complete_evaluation_sessions_as_of_attempt"] for item in windows] == [20, 11, 0]
    assert [item["complete_warmup_sessions_as_of_attempt"] for item in windows] == [10, 10, 1]
    assert payloads["gates"]["overall"] == "FAIL"
    assert payloads["gates"]["alpaca_requests_made"] == 0
    assert payloads["gates"]["strategy_replays_run"] == 0
    assert payloads["gates"]["outcomes_unblinded"] is False
    assert payloads["summary"]["classification"] == "VALIDATION_BLOCKED"
    assert payloads["summary"]["replay_started"] is False


def test_task61_frozen_identity_and_universe() -> None:
    payloads = task61.build_payloads()
    manifest = payloads["manifest"]
    assert manifest["git_checkpoint"] == "4a5923d9150283febf50d1b8c3634ba7735992ee"
    assert manifest["frozen_implementation_fingerprint"] == (
        "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"
    )
    assert manifest["current_candidate_strategy_fingerprint"] == "2ae6216bca70"
    assert manifest["universe_count"] == 35
    assert len(manifest["universe"]) == len(set(manifest["universe"])) == 35
