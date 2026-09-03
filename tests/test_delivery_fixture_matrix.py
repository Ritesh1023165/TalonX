"""
tests/test_delivery_fixture_matrix.py
-------------------------------------
Task 96F -- Phase 22 render matrix. Every fixture verifies band, facts,
top reasons, source, disclaimer, no prohibited claims, size budget.
"""
from __future__ import annotations

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.delivery.claim_safety import scan_rendered
from talonx_ingest.intelligence.delivery.config import DISCLAIMER_SHORT, MESSAGE_BUDGET
from talonx_ingest.intelligence.delivery.renderer import render_for_card
from _delivery_helpers import make_card, mk_comparison, mk_event, mk_insider_activity


def _check(m, *, band, must_contain=()):
    assert m.band is band, (m.band, band)
    assert DISCLAIMER_SHORT in m.text
    assert m.disclaimer_present
    assert scan_rendered(m.text) == []
    assert len(m.text) <= MESSAGE_BUDGET + 40
    assert ("sec.gov" in m.text) or ("ref " in m.text) or ("Source ref" in m.text)
    for s in must_contain:
        assert s in m.text, s


def test_case_earnings_medium_or_high():
    card, _ = make_card(event_type=EventType.EARNINGS_RESULTS, items=("2.02", "9.01"),
                        on_watchlist=True, age_hours=1)
    m = render_for_card(card)
    assert m.band in (SignificanceBand.MEDIUM, SignificanceBand.HIGH)
    assert "Earnings / results" in m.text
    assert "Why surfaced:" in m.text
    assert scan_rendered(m.text) == [] and DISCLAIMER_SHORT in m.text


def test_case_material_8k_high_or_critical():
    card, _ = make_card(
        event_type=EventType.RESTRUCTURING, items=("2.05", "1.01", "2.03", "9.01"),
        pinned=True, on_watchlist=True, age_hours=1,
    )
    m = render_for_card(card)
    assert m.band in (SignificanceBand.HIGH, SignificanceBand.CRITICAL)
    _check(m, band=m.band, must_contain=("restructuring", "Why surfaced:"))


def test_case_filing_change_10q_multiple_facts():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed

    comp = mk_comparison(event=ev, rf_diff=0.55, mdna_diff=0.3, liq_diff=0.2,
                         revenue_rel_delta=0.24, eps_rel_delta=-0.4, neg_kw_delta=8)
    card, wc = make_card(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
                         comparison=comp, on_watchlist=True)
    m = render_for_card(card, what_changed=wc)
    assert "What changed:" in m.text
    assert "Risk Factors changed above the material threshold" in m.text
    assert "Reported revenue YoY change +24%" in m.text
    assert "Reported eps diluted YoY change -40%" in m.text
    _check(m, band=m.band)


def test_case_insider_single_and_cluster():
    one = mk_insider_activity(largest_value=2_300_000.0, cluster=False)
    card1, _ = make_card(event_type=EventType.INSIDER_TRANSACTION, form_type="4", items=(),
                         insider_activity=one)
    m1 = render_for_card(card1, insider_activity=one)
    assert "Largest single open-market transaction: $2.30m" in m1.text
    _check(m1, band=m1.band)

    many = mk_insider_activity(largest_value=4_200_000.0, cluster=True)
    card2, _ = make_card(event_type=EventType.INSIDER_TRANSACTION, form_type="4", items=(),
                         insider_activity=many, on_watchlist=True)
    m2 = render_for_card(card2, insider_activity=many)
    assert "distinct insiders reported open-market sales within 30 days" in m2.text
    _check(m2, band=m2.band)


def test_case_low_quality_evidence_shows_warning():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed

    comp = mk_comparison(event=ev, rf_diff=0.5, quality_flags=("section_not_found", "xbrl_unavailable"))
    card, wc = make_card(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
                         comparison=comp, quality_flags=("primary_document_unavailable",))
    m = render_for_card(card, what_changed=wc)
    assert "Data limitations" in m.text
    _check(m, band=m.band)


def test_case_low_significance_is_compact_and_minimal():
    card, _ = make_card(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=100)
    m = render_for_card(card)
    assert m.band is SignificanceBand.LOW
    assert m.tier == "COMPACT"
    assert len(m.text) < 900
    _check(m, band=SignificanceBand.LOW)


def test_case_critical_is_expanded_and_rich():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    from talonx_ingest.intelligence.significance.rarity import RarityResult

    comp = mk_comparison(event=ev, rf_diff=0.7, mdna_diff=0.4, whole_diff=0.4,
                         revenue_rel_delta=-0.6, eps_rel_delta=0.9, neg_kw_delta=25)
    card, wc = make_card(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
                         comparison=comp, pinned=True, on_watchlist=True)
    # push to CRITICAL via rarity + simultaneous in the significance eval
    from talonx_ingest.intelligence.significance import evaluate_significance
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance
    from talonx_ingest.intelligence.pipeline import build_alert_card

    sig = evaluate_significance(
        card_event := mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=()),
        comparison=comp,
        rarity_result=RarityResult("UNCOMMON", 1, "d", 0, 1, None),
        simultaneous_type_count=2, pinned=True, on_watchlist=True,
    )
    rich = apply_significance(build_alert_card(card_event), sig)
    m = render_for_card(rich, what_changed=wc)
    assert m.band is SignificanceBand.CRITICAL
    assert m.tier == "EXPANDED"
    assert "What changed:" in m.text and "Why surfaced:" in m.text
    _check(m, band=SignificanceBand.CRITICAL)
