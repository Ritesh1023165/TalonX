"""
tests/test_significance_fixture_matrix.py
----------------------------------------
Task 96E -- Phase 22: a representative fixture matrix. Each case asserts
the band AND the presence of the specific reason codes that justify it.
"""
from __future__ import annotations

from datetime import timedelta

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.rarity import RarityResult
from _significance_helpers import NOW, mk_comparison, mk_event, mk_insider_activity


def _codes(sig):
    return {r.code for r in sig.reasons}


def test_case_a_routine_low_change_event():
    ev = mk_event(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=100)
    sig = evaluate_significance(ev, now=NOW)
    assert sig.band is SignificanceBand.LOW
    assert sig.score <= 1


def test_case_b_earnings_8k_with_moderate_facts():
    ev = mk_event(event_type=EventType.EARNINGS_RESULTS, items=("2.02", "9.01"), age_hours=1)
    sig = evaluate_significance(
        ev,
        comparison=None,
        on_watchlist=True,
        rarity_result=RarityResult("COMMON", 0, "d", 4, 8, NOW),
        now=NOW,
    )
    assert sig.band in (SignificanceBand.MEDIUM, SignificanceBand.HIGH)
    assert "EVENT_TYPE_BASE" in _codes(sig)
    assert "RECENT_ARRIVAL" in _codes(sig)
    assert "ON_WATCHLIST" in _codes(sig)


def test_case_c_large_10q_risk_factors_change():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(), age_hours=30)
    fc = mk_comparison(event=ev, rf_diff=0.70, mdna_diff=0.30, neg_kw_delta=20)
    sig = evaluate_significance(ev, comparison=fc, now=NOW)
    assert sig.band is SignificanceBand.HIGH
    assert "SECTION_CHANGE_DECILE" in _codes(sig)
    assert "RISK_TERM_COUNT_ROSE" in _codes(sig)


def test_case_d_material_agreement_plus_debt_multi_item_8k():
    ev = mk_event(
        event_type=EventType.MATERIAL_AGREEMENT,
        items=("1.01", "2.03", "2.05", "9.01"),
        age_hours=1,
    )
    sig = evaluate_significance(
        ev,
        rarity_result=RarityResult("RARE", 2, "rare for filer", 0, 0, NOW),
        simultaneous_type_count=2,
        now=NOW,
    )
    assert sig.band in (SignificanceBand.HIGH, SignificanceBand.CRITICAL)
    assert "MULTI_ITEM_8K" in _codes(sig)
    assert "HIGH_BASE_RAW_ITEM" in _codes(sig)  # 2.01/2.05 lift
    assert "EVENT_RARE_FOR_FILER" in _codes(sig)


def test_case_e_large_insider_cluster():
    ev = mk_event(event_type=EventType.INSIDER_TRANSACTION, form_type="4", items=(), age_hours=5)
    act = mk_insider_activity(largest_value=4_200_000.0, cluster=True)
    sig = evaluate_significance(ev, insider_activity=act, now=NOW)
    assert sig.band in (SignificanceBand.MEDIUM, SignificanceBand.HIGH)
    assert "LARGE_OPEN_MARKET_TRANSACTION" in _codes(sig)
    assert "INSIDER_CLUSTER" in _codes(sig)
    # the insider parent event itself also scored (open-market activity present)
    assert "EVENT_TYPE_BASE" in _codes(sig)


def test_case_f_incomplete_ambiguous_data_capped():
    ev = mk_event(
        event_type=EventType.ANNUAL_FILING,
        form_type="10-K",
        items=(),
        quality_flags=("missing_acceptance_timestamp",),
        age_hours=1,
    )
    fc = mk_comparison(
        event=ev, rf_diff=0.70, mdna_diff=0.30, whole_diff=0.5,
        quality_flags=("ambiguous_section", "xbrl_unavailable"),
    )
    sig = evaluate_significance(ev, comparison=fc, now=NOW)
    # lots of raw change, but incomplete evidence holds the band down
    assert sig.band in (SignificanceBand.LOW, SignificanceBand.MEDIUM)
    assert any("MEDIUM" in c for c in sig.band_caps_applied)
    assert any(r.code in ("EVENT_DATA_INCOMPLETE", "FILING_COMPARISON_INCOMPLETE")
               for r in sig.reasons)
    assert all(r.points >= 0 or r.code.startswith(("EVENT_DATA", "FILING_COMPARISON",
               "INSIDER_DATA", "SOURCE_", "QUALITY", "SCORE_", "FILING_CHANGE_CONTRIBUTION"))
               for r in sig.reasons)
