"""
tests/test_comparison_identity.py
---------------------------------
Task 96C -- deterministic comparison_id.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.config import COMPARISON_SCHEMA_VERSION
from talonx_ingest.intelligence.comparison.identity import comparison_id, content_hash


def test_comparison_id_is_deterministic_and_normalised():
    a = comparison_id("000000000026000002", "000000000026000001")
    b = comparison_id("0000000000-26-000002", "0000000000-26-000001")
    assert a == b
    assert a == f"CMP:0000000000-26-000002:0000000000-26-000001:{COMPARISON_SCHEMA_VERSION}"


def test_comparison_id_without_prior():
    cid = comparison_id("0000000000-26-000002", None)
    assert cid == f"CMP:0000000000-26-000002:NONE:{COMPARISON_SCHEMA_VERSION}"


def test_schema_version_changes_the_id():
    a = comparison_id("0000000000-26-000002", "0000000000-26-000001")
    b = comparison_id("0000000000-26-000002", "0000000000-26-000001", schema_version="filing_comparison@v2")
    assert a != b


def test_content_hash_is_lf_normalised_and_stable():
    assert content_hash("a\r\nb") == content_hash("a\nb")
    assert len(content_hash("x")) == 64
