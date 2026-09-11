"""
tests/test_delivery_escape.py
-----------------------------
Task 96F -- HTML escaping / markup safety (Phase 18).
"""
from __future__ import annotations

from talonx_ingest.intelligence.delivery.escape import (
    bold,
    clean,
    esc,
    esc_attr,
    link,
)


def test_escapes_html_metacharacters():
    assert esc("AT&T <Class A> shares") == "AT&amp;T &lt;Class A&gt; shares"


def test_underscores_and_brackets_pass_through_unescaped_in_html_mode():
    # HTML mode does not treat _ * [ ] specially -- unlike legacy Markdown
    assert esc("Q3_2026 [draft] *final*") == "Q3_2026 [draft] *final*"


def test_control_characters_stripped():
    assert "\x00" not in esc("bad\x00name")
    assert "\x07" not in clean("bell\x07here")


def test_whitespace_collapsed_but_newlines_kept():
    assert clean("a   b\t\tc\nd") == "a b c\nd"


def test_link_only_emits_for_http_urls():
    assert link("SEC filing", "https://sec.gov/x").startswith('<a href="https://sec.gov/x">')
    assert link("bad", "javascript:alert(1)") == "bad"
    assert link("none", None) == "none"


def test_link_escapes_label_and_href():
    out = link("A&B <x>", "https://sec.gov/?q=a&b")
    assert "A&amp;B &lt;x&gt;" in out
    assert 'href="https://sec.gov/?q=a&amp;b"' in out


def test_attr_escaping_quotes():
    assert esc_attr('x"y') == "x&quot;y"


def test_bold_wraps_escaped():
    assert bold("A & B") == "<b>A &amp; B</b>"


def test_malformed_company_name_does_not_raise():
    weird = 'Ácme Corp. <<>> & "Sons" \x01 _underscore_ [b]'
    esc(weird)  # must not raise
    bold(weird)
