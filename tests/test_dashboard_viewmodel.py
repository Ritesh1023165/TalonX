"""
tests/test_dashboard_viewmodel.py
---------------------------------
Task 96G -- pure presentation transforms.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.dashboard import viewmodel as V
from talonx_ingest.intelligence.dashboard.claim_safety import scan_text

_NOW = datetime(2026, 9, 3, 20, 0, 0, tzinfo=timezone.utc)


def test_fmt_ts_utc_et_and_relative():
    d = V.fmt_ts("2026-09-03T18:00:00+00:00", now=_NOW)
    assert d["utc"] == "2026-09-03 18:00 UTC"
    assert d["et"].endswith("ET")
    assert d["rel"] == "2h ago"
    assert V.fmt_ts(None)["utc"] == "[time unavailable]"


def test_band_chip_always_carries_text_not_colour_alone():
    for band in ("LOW", "MEDIUM", "HIGH", "CRITICAL", None):
        c = V.band_chip(band)
        assert c["label"]                       # human text always present
        assert c["short"]
        assert c["css"].startswith("band-")
    assert "NOT" in V.band_chip(None)["label"].upper()


def test_quality_notes_friendly_and_deduped():
    notes = V.quality_notes(("missing_prior_filing", "missing_prior_filing", "xbrl_unavailable"))
    assert len(notes) == 2
    assert all("_" not in n or " " in n for n in notes)  # humanised


def test_what_changed_facts_are_neutral_no_direction():
    wc = {
        "sections": {"risk_factors": {"status": "FOUND", "diff_ratio": 0.44,
                                      "exceeds_material_threshold": True, "pct_char_delta": 18.0}},
        "whole_document": {"diff_ratio": 0.3, "exceeds_material_threshold": True},
        "keywords": {"by_category": {"negative_risk": {"prior_total": 10, "current_total": 16,
                                                       "total_delta": 6, "terms_increased": ["impairment"]}}},
        "xbrl": [{"field": "revenue", "comparison": "YOY", "relative_delta": -0.35, "status": "FOUND"}],
        "notable_changes": [{"kind": "new_material_passages", "value": 3}],
    }
    facts = V.what_changed_facts(wc)
    joined = " ".join(facts)
    assert "Risk Factors: changed above the frozen material threshold (change magnitude 44%)" in facts
    assert "Reported revenue YoY change -35%" in facts
    assert "3 new multi-sentence passage(s) in Risk Factors / MD&A" in facts
    assert scan_text(joined) == []
    for bad in ("bearish", "bullish", "buy", "sell"):
        assert bad not in joined.lower()


def test_insider_facts_descriptive():
    act = {
        "open_market_aggregates": [
            {"window_calendar_days": 30, "transaction_count": 3, "distinct_purchasers": 1,
             "distinct_sellers": 2, "largest_single_transaction_value": 2_300_000.0,
             "value_coverage_note": None}
        ],
        "clusters": [{"kind": "MULTIPLE_OPEN_MARKET_SELLERS", "distinct_owners": 2,
                      "window_calendar_days": 30}],
        "role_subsets": [{"subset": "CEO", "window_calendar_days": 30, "purchase_count": 0, "sale_count": 1}],
    }
    facts = V.insider_facts(act)
    assert "Largest single open-market transaction: $2.30m" in facts
    assert any("distinct insiders reported open-market sales" in f for f in facts)
    assert scan_text(" ".join(facts)) == []
    assert "smart money" not in " ".join(facts).lower()


def test_evidence_links_http_only_and_deduped():
    row = {
        "filing_index_url": "https://sec.gov/a",
        "primary_document_url": "javascript:alert(1)",
        "evidence": [{"transform": "t", "source_url": "https://sec.gov/a"},
                     {"transform": "t2", "source_url": "https://sec.gov/b"}],
        "exhibits": [{"document_type": "EX-99.1", "source_url": "ftp://sec.gov/c"}],
    }
    links = V.evidence_links(row)
    urls = [l["url"] for l in links]
    assert urls == ["https://sec.gov/a", "https://sec.gov/b"]
