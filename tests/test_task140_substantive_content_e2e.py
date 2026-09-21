"""
tests/test_task140_substantive_content_e2e.py
================================================
Task 140 -- end-to-end proof (real significance engine, real comparison
object, real renderer -- not mocked classify_disposition) that the
substantive-content requirement holds through the actual pipeline, not
just at the classify_disposition unit level (see
tests/test_task138_notification_policy.py for that).

Covers the validation cases explicitly required:
- Generic high-band event lacking substantive evidence -> no immediate push.
- Document-change score alone without supported change details -> no
  immediate push (the SAME real rules.py-computed reasons a genuine
  qualifying event would carry, just below threshold).
- Supported substantive event -> concise message containing its
  qualifying facts (not hidden behind a reply).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.delivery.notification_policy import (
    DISPOSITION_DIGEST,
    DISPOSITION_IMMEDIATE,
    classify_disposition,
)
from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
from talonx_ingest.intelligence.delivery.renderer import render_concise
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.pipeline import build_alert_card
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.alert_integration import apply_significance
from _significance_helpers import mk_comparison, mk_event

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)


def _sig_and_card(*, symbol, accession, comparison=None, on_watchlist=True, now=NOW):
    ev = mk_event(symbol=symbol, accession=accession, event_type=EventType.QUARTERLY_FILING,
                  now=now)
    ev = ev.model_copy(update={
        "filing_index_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession}-index.htm",
    })
    sig = evaluate_significance(ev, comparison=comparison, on_watchlist=on_watchlist, now=now)
    card = apply_significance(build_alert_card(ev), sig)
    return sig, card


def test_high_band_generic_event_no_comparison_data_does_not_push_immediate(tmp_path):
    """A HIGH-band event (watchlist + a filed-form signal only, no
    comparison data at all -- e.g. a routine 10-Q with nothing to compare
    against) must never reach IMMEDIATE, regardless of its band label."""
    sig, card = _sig_and_card(symbol="DXCM", accession="0001093557-26-000175",
                              comparison=None, on_watchlist=True)
    decision = classify_disposition(band=sig.band, reasons=sig.reasons)
    assert decision.disposition != DISPOSITION_IMMEDIATE
    assert decision.evidence_text is None


def test_document_change_below_threshold_does_not_push_immediate(tmp_path):
    """A real FilingComparison exists, but its risk-factors diff_ratio is
    BELOW both the tercile and decile thresholds -- rules.py computes a
    genuine score for it, but no SECTION_CHANGE_DECILE/TERCILE reason
    code is emitted, so there is no substantive trigger and no immediate
    push, exactly matching real production behavior for a routine
    quarterly update with only cosmetic wording changes."""
    ev = mk_event(symbol="ACME", accession="0000320193-26-000200",
                  event_type=EventType.QUARTERLY_FILING, now=NOW)
    comparison = mk_comparison(event=ev, rf_diff=0.02)   # well below tercile (~0.1x territory)
    sig, card = _sig_and_card(symbol="ACME", accession="0000320193-26-000200",
                              comparison=comparison, on_watchlist=True)
    codes = [r.code for r in sig.reasons]
    assert "SECTION_CHANGE_DECILE" not in codes and "SECTION_CHANGE_TERCILE" not in codes
    decision = classify_disposition(band=sig.band, reasons=sig.reasons)
    assert decision.disposition != DISPOSITION_IMMEDIATE


def test_genuine_decile_change_produces_a_concise_message_with_the_real_fact(tmp_path):
    """A real FilingComparison whose risk-factors diff_ratio crosses the
    frozen decile threshold (0.6466) -- rules.py emits a genuine
    SECTION_CHANGE_DECILE reason with a real computed percentage baked
    into its own description. classify_disposition must reach IMMEDIATE
    with that EXACT text as evidence_text, and render_concise's actual
    OUTPUT MESSAGE must contain the qualifying fact itself -- not a
    generic label, not something hidden behind a reply."""
    ev = mk_event(symbol="RFCO", accession="0001193125-26-000300",
                  event_type=EventType.QUARTERLY_FILING, now=NOW)
    comparison = mk_comparison(event=ev, rf_diff=0.75)   # above the 0.6466 decile threshold
    sig, card = _sig_and_card(symbol="RFCO", accession="0001193125-26-000300",
                              comparison=comparison, on_watchlist=True)
    assert "SECTION_CHANGE_DECILE" in [r.code for r in sig.reasons]

    decision = classify_disposition(band=sig.band, reasons=sig.reasons)
    assert decision.disposition == DISPOSITION_IMMEDIATE
    assert decision.evidence_text is not None
    assert "Risk Factors" in decision.evidence_text
    assert "75%" in decision.evidence_text

    msg = render_concise(card, disposition_reason=decision.evidence_text, now=NOW)
    # the ACTUAL sent message text contains the qualifying fact directly
    assert "Risk Factors" in msg.text
    assert "75%" in msg.text
    assert "top decile" in msg.text
    # never a generic placeholder
    assert "significant filing" not in msg.text.lower()


def test_enqueue_card_end_to_end_stores_the_real_evidence_in_the_outbox_row(tmp_path):
    """Through the real enqueue_card path (not just render_concise in
    isolation): the persisted delivery row's own text contains the real
    fact, addressable later via reply-details."""
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox

    ev = mk_event(symbol="RFCO", accession="0001193125-26-000301",
                  event_type=EventType.QUARTERLY_FILING, now=NOW)
    comparison = mk_comparison(event=ev, rf_diff=0.80)
    sig, card = _sig_and_card(symbol="RFCO", accession="0001193125-26-000301",
                              comparison=comparison, on_watchlist=True)
    decision = classify_disposition(band=sig.band, reasons=sig.reasons)
    assert decision.disposition == DISPOSITION_IMMEDIATE

    ob = DeliveryOutbox(tmp_path / "l.db")
    result = enqueue_card(card, outbox=ob, now=NOW, route_override=decision.disposition,
                          tier="CONCISE", disposition_reason=decision.evidence_text)
    row = ob.get(result.row.delivery_id)
    assert row.route == "IMMEDIATE"
    assert row.tier == "CONCISE"
    assert "Risk Factors" in row.text and "80%" in row.text
