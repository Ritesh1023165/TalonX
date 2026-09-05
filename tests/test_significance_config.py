"""
tests/test_significance_config.py
--------------------------------
Task 96E -- the frozen ruleset constants and the band mapping.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.domain import SignificanceBand
from talonx_ingest.intelligence.significance import config as C


def test_ruleset_version_is_frozen_string():
    assert C.RULESET_VERSION == "information-significance-v1"
    assert isinstance(C.SIGNIFICANCE_SCHEMA_VERSION, str)


def test_band_thresholds_match_the_binding_design():
    # INFORMATION_SIGNIFICANCE_SPEC.md: >=7 CRITICAL, 4-6 HIGH, 2-3 MEDIUM, 0-1 LOW
    assert C.band_for_score(0) is SignificanceBand.LOW
    assert C.band_for_score(1) is SignificanceBand.LOW
    assert C.band_for_score(2) is SignificanceBand.MEDIUM
    assert C.band_for_score(3) is SignificanceBand.MEDIUM
    assert C.band_for_score(4) is SignificanceBand.HIGH
    assert C.band_for_score(6) is SignificanceBand.HIGH
    assert C.band_for_score(7) is SignificanceBand.CRITICAL
    assert C.band_for_score(99) is SignificanceBand.CRITICAL


def test_min_band():
    assert C.min_band(SignificanceBand.CRITICAL, SignificanceBand.MEDIUM) is SignificanceBand.MEDIUM
    assert C.min_band(SignificanceBand.LOW, SignificanceBand.HIGH) is SignificanceBand.LOW
    assert C.min_band(SignificanceBand.HIGH, SignificanceBand.HIGH) is SignificanceBand.HIGH


def test_tercile_thresholds_are_reused_verbatim_from_96c():
    from talonx_ingest.intelligence.comparison.config import MATERIAL_CHANGE_THRESHOLDS

    assert C.TERCILE_CHANGE_THRESHOLDS == dict(MATERIAL_CHANGE_THRESHOLDS)


def test_decile_thresholds_are_above_tercile_thresholds():
    for k, tercile in C.TERCILE_CHANGE_THRESHOLDS.items():
        assert C.DECILE_CHANGE_THRESHOLDS[k] > tercile, k


def test_every_capped_component_has_a_cap():
    # every component the engine emits must be in COMPONENT_CAPS or be the
    # quality penalty (which has its own floor)
    expected = {
        "event_type_base", "material_items", "filing_change", "risk_language",
        "xbrl_magnitude", "insider_activity", "rarity", "recency",
        "watchlist_priority", "simultaneous_events",
    }
    assert set(C.COMPONENT_CAPS) == expected


def test_substantive_set_excludes_recency_and_watchlist():
    assert "recency" not in C.SUBSTANTIVE_COMPONENTS
    assert "watchlist_priority" not in C.SUBSTANTIVE_COMPONENTS
    assert "quality_penalty" not in C.SUBSTANTIVE_COMPONENTS
    assert "event_type_base" in C.SUBSTANTIVE_COMPONENTS


def test_total_cap_is_above_critical_threshold():
    assert C.SCORE_TOTAL_CAP >= 7


@pytest.mark.parametrize("item", ["1.05", "2.01", "2.05", "2.06", "3.01"])
def test_high_base_raw_items(item):
    assert item in C.HIGH_BASE_RAW_ITEMS
