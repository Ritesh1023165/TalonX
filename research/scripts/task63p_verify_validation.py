"""Recompute Task 63P accounting/correctness checks without any strategy replay."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.scripts.task62_freeze_candidate import (  # noqa: E402
    PROTECTED_CURRENT_FILES,
    implementation_fingerprint,
)
from research.scripts.task63p_readiness import FROZEN_DATA_NOT_READY  # noqa: E402


OUT = ROOT / "results/task63p_orpb_v1_readiness_correction"
EXPECTED_FINGERPRINT = "b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f"
BASE = "4e082779505378b7c6da7c254b85971c137532e4"
ET = "America/New_York"


def metrics(values: pd.Series) -> dict[str, float | int]:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return {
        "trades": len(values),
        "total_R": float(values.sum()),
        "expectancy_R": float(values.mean()),
        "profit_factor": gains / losses,
    }


def bootstrap(values: np.ndarray) -> list[float]:
    rng = np.random.default_rng(62)
    means = np.empty(10_000)
    for start in range(0, 10_000, 1000):
        indices = rng.integers(0, len(values), size=(1000, len(values)))
        means[start:start + 1000] = values[indices].mean(axis=1)
    return [float(item) for item in np.percentile(means, [2.5, 97.5])]


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0, abs_tol=1e-12)


def main() -> int:
    trades = pd.read_csv(OUT / "trades.csv")
    aggregate = json.loads((OUT / "aggregate_economics.json").read_text(encoding="utf-8"))
    criteria = json.loads((OUT / "criteria.json").read_text(encoding="utf-8"))
    gates = json.loads((OUT / "pre_replay_gates.json").read_text(encoding="utf-8"))
    replay = json.loads((OUT / "replay_manifest.json").read_text(encoding="utf-8"))
    gross = metrics(trades.gross_r)
    net = metrics(trades.net_r_5bps)
    ci = bootstrap(trades.net_r_5bps.to_numpy(float))
    trade_keys = {
        (
            str(row.window), str(row.ticker),
            pd.Timestamp(row.entry_timestamp).tz_convert(ET).date().isoformat(),
        )
        for row in trades.itertuples()
    }
    protected_diff = subprocess.run(
        ["git", "diff", "--name-only", BASE, "--", *PROTECTED_CURRENT_FILES,
         "talonx_quant/orpb_v1.py", "talonx_quant/orpb_v1_shadow.py"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    historical_diff = subprocess.run(
        ["git", "diff", "--name-only", BASE, "--",
         "results/task62_new_alpha_candidate",
         "results/task63_orpb_v1_independent_validation_1",
         "results/task63r_orpb_v1_feed_remediation"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    checks = {
        "alpha_fingerprint_unchanged": implementation_fingerprint() == EXPECTED_FINGERPRINT,
        "all_pre_replay_gates_passed": gates["all_mandatory_gates_passed"],
        "replay_started_only_after_gates": gates["replay_started"],
        "single_replay_manifest": replay["single_replay"] and replay["total_trades"] == len(trades),
        "identical_0bps_5bps_trade_accounting": bool(np.allclose(
            trades.net_r_5bps, trades.gross_r - trades.actual_cost_r_5bps,
            rtol=0, atol=1e-12,
        )),
        "gross_metrics_reproduced": all((
            gross["trades"] == aggregate["gross_0bps"]["trades"],
            close(gross["total_R"], aggregate["gross_0bps"]["total_R"]),
            close(gross["expectancy_R"], aggregate["gross_0bps"]["expectancy_R"]),
            close(gross["profit_factor"], aggregate["gross_0bps"]["profit_factor"]),
        )),
        "net_metrics_reproduced": all((
            net["trades"] == aggregate["net_5bps"]["trades"],
            close(net["total_R"], aggregate["net_5bps"]["total_R"]),
            close(net["expectancy_R"], aggregate["net_5bps"]["expectancy_R"]),
            close(net["profit_factor"], aggregate["net_5bps"]["profit_factor"]),
        )),
        "bootstrap_reproduced": bool(np.allclose(
            ci, criteria["bootstrap"]["ci_95"], rtol=0, atol=1e-12
        )),
        "no_data_not_ready_trades": trade_keys.isdisjoint(FROZEN_DATA_NOT_READY),
        "every_actual_fill_cost_feasible": bool(
            (trades.actual_fill_feasibility_cost_r_5bps <= 0.20 + 1e-12).all()
        ),
        "mandatory_rejection_reproduced": not criteria["mandatory_criteria_pass"],
        "protected_code_zero_drift": not protected_diff,
        "task62_63_63r_history_unchanged": not historical_diff,
    }
    payload = {
        "task": "63P",
        "analysis_only_no_replay": True,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "reproduced": {"gross": gross, "net_5bps": net, "bootstrap_95_ci": ci},
    }
    (OUT / "post_validation_checks.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
