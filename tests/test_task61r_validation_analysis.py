from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research" / "scripts" / "task61r_validate_fprc_v1.py"
SPEC = importlib.util.spec_from_file_location("task61r_validation", SCRIPT)
assert SPEC and SPEC.loader
task61r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task61r)


def test_bootstrap_is_frozen_and_deterministic() -> None:
    values = np.array([-1.0, 0.5, 1.5, 2.0])
    assert task61r.bootstrap_ci(values) == task61r.bootstrap_ci(values)
    low, high = task61r.bootstrap_ci(values)
    assert low < values.mean() < high


def test_economics_uses_declared_trade_order_drawdown_and_pf() -> None:
    frame = pd.DataFrame({"net_r_5bps": [1.0, -0.5, -0.25, 2.0]})
    result = task61r.metrics(frame, "net_r_5bps")
    assert result["expectancy_R"] == pytest.approx(0.5625)
    assert result["profit_factor"] == pytest.approx(4.0)
    assert result["max_drawdown_R"] == pytest.approx(0.75)


def test_time_slicing_is_regular_session_only() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2025-05-20T13:29:00Z", "2025-05-20T13:30:00Z", "2025-05-20T19:59:00Z", "2025-05-20T20:00:00Z"],
                utc=True,
            ),
            "symbol": ["AAPL"] * 4,
            "open": [1.0] * 4,
            "high": [1.0] * 4,
            "low": [1.0] * 4,
            "close": [1.0] * 4,
            "volume": [1.0] * 4,
        }
    )
    observed = task61r.rth(frame)
    assert observed.timestamp.dt.strftime("%H:%M").tolist() == ["13:30", "19:59"]


def test_frozen_replay_artifacts_reconcile_exactly() -> None:
    out = ROOT / "results" / "task61r_fprc_v1_independent_validation_1"
    trades = pd.read_csv(out / "trades.csv")
    summary = json.loads((out / "task61r_summary.json").read_text(encoding="utf-8"))
    criteria = json.loads((out / "criteria.json").read_text(encoding="utf-8"))
    risk = trades.entry_price - trades.stop_price
    reconstructed_gross = (trades.exit_price - trades.entry_price) / risk
    reconstructed_cost = (trades.entry_price * 0.0005 + trades.exit_price * 0.0005) / risk
    assert len(trades) == 205
    assert trades.groupby("window").size().to_dict() == {"V1": 68, "V2": 72, "V3": 65}
    assert trades.ticker.nunique() == 32
    assert not trades.duplicated(["window", "ticker", "entry_timestamp"]).any()
    assert np.allclose(trades.gross_r, reconstructed_gross, atol=1e-12)
    assert np.allclose(trades.cost_r_5bps, reconstructed_cost, atol=1e-12)
    assert np.allclose(trades.net_r_5bps, trades.gross_r - trades.cost_r_5bps, atol=1e-12)
    assert trades.actual_fill_feasibility_cost_R_5bps.max() <= 0.20 + 1e-12
    assert set(trades.exit_reason) <= {"STOP", "THESIS_FAILURE", "END_OF_SESSION"}
    assert summary["validation_classification"] == "FPRC_V1_REJECTED"
    assert criteria["mandatory_criteria_pass"] is False
