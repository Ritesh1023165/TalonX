"""
tests/test_comparison_normalize.py
----------------------------------
Task 96C -- deterministic HTML -> comparable-text normalisation.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.normalize import (
    normalize_filing_text,
    normalize_plaintext,
)

_HTML = """
<html><head><style>.x{color:red}</style></head><body>
  <p>Table of Contents</p>
  <p>Item&nbsp;1A.  Risk   Factors</p>
  <div>The Company faces <b>COMPETITION</b> and regulatory risk.</div>
  <p>- 12 -</p>
  <p>us-gaap:Revenues contextref="c-1"</p>
  <table><tr><td>Revenue</td><td>100</td></tr></table>
  <p>Page 5 of 42</p>
</body></html>
"""


def test_repeated_normalisation_is_identical():
    a = normalize_filing_text(_HTML)
    b = normalize_filing_text(_HTML)
    assert a.text == b.text
    assert a.text_hash == b.text_hash
    assert a.word_count == b.word_count


def test_lowercased_single_spaced_no_html():
    doc = normalize_filing_text(_HTML)
    assert "<" not in doc.text and ">" not in doc.text
    assert doc.text == doc.text.lower()
    assert "  " not in doc.text            # collapsed
    assert "item 1a. risk factors" in doc.text


def test_page_furniture_and_inline_xbrl_removed():
    doc = normalize_filing_text(_HTML)
    assert "table of contents" not in doc.text
    assert "page 5 of 42" not in doc.text
    assert "- 12 -" not in doc.text
    assert "us-gaap:revenues" not in doc.text
    assert "contextref" not in doc.text


def test_disclosure_content_preserved():
    doc = normalize_filing_text(_HTML)
    assert "competition and regulatory risk" in doc.text
    assert "revenue" in doc.text and "100" in doc.text   # table content survives


def test_empty_and_garbage_html():
    assert normalize_filing_text("").text == ""
    assert normalize_filing_text(None).word_count == 0
    frag = normalize_filing_text("<p>hello <world")
    assert "hello" in frag.text


def test_normalize_plaintext_matches_shape():
    d = normalize_plaintext("  Hello   WORLD\n\npage 3\n")
    assert d.text == "hello world"
    assert d.words == ("hello", "world")
