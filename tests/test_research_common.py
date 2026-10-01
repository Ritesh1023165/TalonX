"""research/common: byte-identical research_stats, and the generalized per-program LockedRangeGuard (EVENT_RESPONSE_MAP_V1
locks all of 2024 and 2025-01-02 onward; the Task75 state is isolated and cannot be touched)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.common import locked_range_guard as G

ROOT = Path(__file__).resolve().parents[1]


def test_research_stats_is_byte_identical_to_task75b_source():
    p = ROOT / "research" / "common" / "research_stats.py"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == \
        "79ae73bf8082c8fa70f97f8b2e3277b00e64f3a4a98fe5b165ed1ee2b78c243d"
    from research.common.research_stats import DEFAULT_SEED, bootstrap_ci_clustered  # noqa: F401
    assert DEFAULT_SEED == 670067


def g(tmp_path):
    return G.LockedRangeGuard(G.EVENT_RESPONSE_MAP_V1, root=tmp_path)


@pytest.mark.parametrize("layer", ["DOWNLOAD", "LOAD"])
@pytest.mark.parametrize("s,e", [("2024-01-01", "2024-01-01"), ("2023-12-20", "2024-01-05"), ("2024-07-01", "2024-07-02"),
                                 ("2024-12-31", "2025-01-01"), ("2025-01-02", "2025-01-02"), ("2023-06-01", "2026-09-30"),
                                 ("2030-01-01", "2030-02-01")])
def test_erm_guard_refuses_all_2024_and_2025_onward(tmp_path, layer, s, e):
    with pytest.raises(G.HoldoutViolation):
        g(tmp_path).check_range(s, e, layer=layer)


def test_erm_guard_allows_development_period(tmp_path):
    g(tmp_path).check_range("2018-11-01", "2023-12-29", layer="DOWNLOAD")
    g(tmp_path).check_range("2023-12-29", "2023-12-31", layer="LOAD")       # weekend before 2024 is still 2023


def test_frame_guard_rejects_interior_locked_rows(tmp_path):
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2023-12-29 21:00", "2024-03-01 15:00", "2023-11-01 15:00"],
                                                   utc=True)})
    with pytest.raises(G.HoldoutViolation):
        g(tmp_path).check_frame(df)
    g(tmp_path).check_frame(df.iloc[[0, 2]])


def test_program_cannot_load_or_write_another_programs_state(tmp_path):
    other = tmp_path / "results" / "event_response_map_v1" / "guard_state.json"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"program": "TASK75B", "locked": [], "audit": []}))
    with pytest.raises(G.HoldoutViolation):
        g(tmp_path)


def test_task75_state_is_isolated_and_untouched(tmp_path):
    t75 = tmp_path / "results" / "task75b_preflight" / "holdout_state.json"
    t75.parent.mkdir(parents=True)
    t75.write_text(json.dumps({"state": "PREFLIGHT", "audit": [{"event": "x"}]}))
    before = t75.read_bytes()
    gd = g(tmp_path)
    gd.record({"event": "design_lock"})
    assert gd.path != t75 and t75.read_bytes() == before
    assert not hasattr(gd, "transition")          # EVENT_RESPONSE_MAP_V1 has no state machine to move anything


def test_locked_ranges_are_immutable_once_registered(tmp_path):
    gd = g(tmp_path)
    gd.record({"event": "registered"})
    loosened = replace(G.EVENT_RESPONSE_MAP_V1, locked=(("YEAR_2024_EXCLUDED", date(2024, 6, 1), date(2024, 6, 30)),))
    with pytest.raises(G.HoldoutViolation):
        G.LockedRangeGuard(loosened, root=tmp_path)


def test_live_worktree_paths_refused():
    with pytest.raises(G.HoldoutViolation):
        G.assert_research_path(Path("C:/workspace/TalonX/results/opportunity/market.db"))
