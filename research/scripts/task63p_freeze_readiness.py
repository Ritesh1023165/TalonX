"""Freeze Task 63P's timestamp-only fail-closed readiness before ORPB replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.scripts.task62_freeze_candidate import implementation_fingerprint  # noqa: E402
from research.scripts.task63p_readiness import (  # noqa: E402
    FROZEN_DATA_NOT_READY,
    build_readiness_table,
    data_not_ready_set,
)
from talonx_backtest.data import load_ohlcv_directory  # noqa: E402
from talonx_quant.orpb_v1 import ORPB_V1_UNIVERSE  # noqa: E402


OUT = ROOT / "results/task63p_orpb_v1_readiness_correction"
DATA = ROOT / "data/historical_1m/task63_orpb_v1_validation"
TASK62 = ROOT / "results/task62_new_alpha_candidate/freeze_manifest.json"
TASK63R_FEED = ROOT / "results/task63r_orpb_v1_feed_remediation/uniform_feed_manifest.json"
EXPECTED_ALPHA_FINGERPRINT = "b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f"
ET = "America/New_York"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    task62 = json.loads(TASK62.read_text(encoding="utf-8"))
    feed = json.loads(TASK63R_FEED.read_text(encoding="utf-8"))
    universe = list(ORPB_V1_UNIVERSE)
    if universe != task62["universe"] or len(universe) != 35:
        raise RuntimeError("Frozen universe drift")
    if feed["feed"] != "sip" or not feed["uniform_35_symbol_dataset"]:
        raise RuntimeError("Task 63P requires the proven uniform Alpaca SIP package")
    if implementation_fingerprint() != EXPECTED_ALPHA_FINGERPRINT:
        raise RuntimeError("ORPB alpha implementation fingerprint drift")

    frame = load_ohlcv_directory(DATA, symbols=universe)
    local = frame.timestamp.dt.tz_convert(ET)
    minute = local.dt.hour * 60 + local.dt.minute
    regular = frame[(minute >= 570) & (minute < 960)].copy()
    readiness = build_readiness_table(regular, universe, task62["windows"])
    observed_blocked = data_not_ready_set(readiness)
    if observed_blocked != FROZEN_DATA_NOT_READY:
        raise RuntimeError(
            f"Readiness exceptions differ from the pre-outcome freeze: {sorted(observed_blocked)}"
        )
    expected = len(universe) * sum(len(window["evaluation_sessions"]) for window in task62["windows"])
    blocked = len(observed_blocked)
    clean = expected - blocked
    if len(readiness) != expected:
        raise RuntimeError("Readiness table does not cover every frozen symbol-session")

    exclusions = readiness[readiness.status == "DATA_NOT_READY"].copy()
    exclusions.to_csv(OUT / "readiness_exclusions.csv", index=False)
    readiness.to_csv(OUT / "readiness_manifest.csv", index=False)
    source_hashes = {symbol: sha256(DATA / f"{symbol}.csv") for symbol in universe}
    payload = {
        "task": "63P",
        "base_commit": "4e082779505378b7c6da7c254b85971c137532e4",
        "correction_frozen_before_outcomes": True,
        "validation_started": False,
        "orpb_signal_generation_started": False,
        "outcomes_inspected": False,
        "alpha_implementation_fingerprint": implementation_fingerprint(),
        "alpha_fingerprint_unchanged": True,
        "provider": "Alpaca",
        "feed": "sip",
        "universe_count": len(universe),
        "evaluation_sessions": 60,
        "expected_symbol_sessions": expected,
        "clean_symbol_sessions": clean,
        "data_not_ready_symbol_sessions": blocked,
        "clean_coverage_percent": 100.0 * clean / expected,
        "exact_data_not_ready": [
            {"window": window, "symbol": symbol, "session": session}
            for window, symbol, session in sorted(observed_blocked)
        ],
        "readiness_inputs": "timestamp presence from 09:30 through 09:59 ET only",
        "readiness_can_inspect_future_bars_or_outcomes": False,
        "bars_synthesized_interpolated_or_filled": False,
        "fail_closed_behavior": (
            "DATA_NOT_READY removes only that symbol-session from controller input; "
            "all other clean symbol-sessions continue"
        ),
        "source_file_sha256": source_hashes,
        "source_download_summary_sha256": feed["download_summary_sha256"],
        "uniform_feed_manifest_sha256": sha256(TASK63R_FEED),
        "readiness_protocol_sha256": sha256(OUT / "readiness_protocol.md"),
        "readiness_code_sha256": sha256(ROOT / "research/scripts/task63p_readiness.py"),
        "readiness_tests_sha256": sha256(ROOT / "tests/test_task63p_orpb_readiness.py"),
    }
    (OUT / "readiness_freeze.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "task": "63P_PRE_OUTCOME_FREEZE",
        "alpha_fingerprint_unchanged": "PASS",
        "readiness_correction_frozen_before_outcomes": "PASS",
        "expected_symbol_sessions": expected,
        "clean_symbol_sessions": clean,
        "data_not_ready_symbol_sessions": blocked,
        "clean_coverage_percent": payload["clean_coverage_percent"],
        "no_fabrication_interpolation": "PASS",
        "validation_started": False,
    }
    (OUT / "preoutcome_freeze_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "preoutcome_freeze_summary.md").write_text(
        "# Task 63P Pre-Outcome Readiness Freeze\n\n"
        f"Expected symbol-sessions: {expected}; clean: {clean}; DATA_NOT_READY: {blocked}; "
        f"clean coverage: {payload['clean_coverage_percent']:.6f}%.\n\n"
        "ORPB alpha fingerprint unchanged: **PASS**. Causal timestamp-only readiness: **PASS**. "
        "No fabrication/interpolation: **PASS**. Validation started: **NO**.\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
