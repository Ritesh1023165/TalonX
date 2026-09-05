"""
tests/test_intelligence_identity.py
-----------------------------------
Task 96A -- deterministic, restart-stable logical identity.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.domain import EventType, SourceType
from talonx_ingest.intelligence.identity import (
    AccessionFormatError,
    alert_id,
    card_id,
    event_id,
    normalize_accession,
    source_hash,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0000320193-26-000070", "0000320193-26-000070"),
        ("000032019326000070", "0000320193-26-000070"),
        ("  0000320193-26-000070  ", "0000320193-26-000070"),
    ],
)
def test_normalize_accession_accepts_dashed_and_undashed(raw, expected):
    assert normalize_accession(raw) == expected


@pytest.mark.parametrize("bad", ["", "not-an-accession", "123", None, "0000320193-26-00007"])
def test_normalize_accession_rejects_malformed(bad):
    with pytest.raises(AccessionFormatError):
        normalize_accession(bad)


def test_event_id_is_deterministic_and_stable():
    a = event_id(SourceType.SEC_EDGAR_SUBMISSIONS, "000032019326000070", EventType.EARNINGS_RESULTS)
    b = event_id(SourceType.SEC_EDGAR_SUBMISSIONS, "0000320193-26-000070", EventType.EARNINGS_RESULTS)
    assert a == b == "SEC:0000320193-26-000070:EARNINGS_RESULTS"


def test_event_id_distinguishes_event_type_within_one_accession():
    acc = "0000320193-26-000050"
    exec_id = event_id(SourceType.SEC_EDGAR_SUBMISSIONS, acc, EventType.EXECUTIVE_CHANGE)
    agr_id = event_id(SourceType.SEC_EDGAR_SUBMISSIONS, acc, EventType.MATERIAL_AGREEMENT)
    assert exec_id != agr_id
    assert exec_id.rsplit(":", 1)[0] == agr_id.rsplit(":", 1)[0]  # same accession segment


def test_card_id_matches_alert_card_spec_shape():
    assert (
        card_id("aapl", "0000320193-26-000070", EventType.EARNINGS_RESULTS)
        == "AAPL:0000320193-26-000070:EARNINGS_RESULTS"
    )


def test_alert_id_is_pure_function_of_event_id():
    eid = "SEC:0000320193-26-000070:EARNINGS_RESULTS"
    assert alert_id(eid) == alert_id(eid) == f"card:{eid}"


def test_source_hash_is_lf_normalised_and_order_sensitive():
    assert source_hash("a\r\nb", "c") == source_hash("a\nb", "c")
    assert source_hash("a", "b") != source_hash("b", "a")
    assert len(source_hash("x")) == 64
