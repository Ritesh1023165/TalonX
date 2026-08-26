"""Task74B -- search budget / hypothesis-count / provider-classification
enforcement tests against the locked research_design_lock_v2.json."""
from __future__ import annotations

import json
from pathlib import Path

from research.task74_alpha_discovery_v2 import family_a_catalyst, family_b_multiday

LOCK_PATH = Path(__file__).resolve().parents[1] / "results" / "task74_alpha_discovery_v2" / "research_design_lock_v2.json"


def _load_lock():
    return json.loads(LOCK_PATH.read_text())


def test_lock_declares_budget_within_cap():
    lock = _load_lock()
    budget = lock["search_budget"]
    assert budget["predeclared_cells"]["total"] <= budget["budget_cap"]
    assert len(lock["families"]) <= 3


def test_family_a_matches_locked_grid():
    n_hyp = len(family_a_catalyst.HYPOTHESES)
    n_bands = len(family_a_catalyst.THRESHOLD_BANDS)
    n_horizons = len(family_a_catalyst.HORIZONS_MINUTES)
    assert n_hyp == 2
    assert n_hyp * n_bands * n_horizons == 8


def test_family_b_matches_locked_grid():
    n_hyp = len(family_b_multiday.HYPOTHESES)
    n_bands = len(family_b_multiday.THRESHOLD_BANDS)
    n_horizons = len(family_b_multiday.HORIZONS_TRADING_DAYS)
    assert n_hyp == 2
    assert n_hyp * n_bands * n_horizons == 12


def test_total_predeclared_cells_is_20():
    a = len(family_a_catalyst.HYPOTHESES) * len(family_a_catalyst.THRESHOLD_BANDS) * len(family_a_catalyst.HORIZONS_MINUTES)
    b = len(family_b_multiday.HYPOTHESES) * len(family_b_multiday.THRESHOLD_BANDS) * len(family_b_multiday.HORIZONS_TRADING_DAYS)
    assert a + b == 20


def test_family_a_marked_provider_sensitive_in_lock():
    lock = _load_lock()
    fam_a = next(f for f in lock["families"] if f["family_id"] == "FAMILY_A")
    assert "PROVIDER_SENSITIVE" in fam_a["provider_note"]
