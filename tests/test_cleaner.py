"""
tests/test_cleaner.py
------------------------
Tests processing.cleaner.clean_filing_html -- the HTML/XBRL -> plain text
normalization step. Uses real bs4/lxml (no mocking needed; this is a pure
function over HTML strings).
"""
from __future__ import annotations

from talonx_ingest.processing.cleaner import clean_filing_html


def test_empty_input_returns_empty_string():
    assert clean_filing_html("") == ""
    assert clean_filing_html("   ") == ""


def test_strips_script_and_style_tags():
    html = """
    <html><head><style>.foo{color:red}</style></head>
    <body>
        <script>alert('hi')</script>
        <p>Real content here.</p>
    </body></html>
    """
    result = clean_filing_html(html)
    assert "alert" not in result
    assert "color:red" not in result
    assert "Real content here." in result


def test_collapses_excess_whitespace():
    html = "<p>Hello    world</p>\n\n\n\n<p>Next paragraph</p>"
    result = clean_filing_html(html)
    assert "Hello    world" not in result  # inner whitespace collapsed
    assert "Hello world" in result
    assert "\n\n\n" not in result  # no more than one blank line between paragraphs


def test_table_rendered_as_pipe_delimited_rows():
    html = """
    <table>
        <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
        <tr><td>Revenue</td><td>$94.9B</td><td>$89.5B</td></tr>
    </table>
    """
    result = clean_filing_html(html)
    assert "Metric | 2024 | 2023" in result
    assert "Revenue | $94.9B | $89.5B" in result
    # no leftover HTML table markup
    assert "<table>" not in result
    assert "<td>" not in result


def test_empty_table_rows_are_dropped():
    html = "<table><tr><td></td><td></td></tr><tr><td>Real</td></tr></table>"
    result = clean_filing_html(html)
    assert "Real" in result
    # the fully-empty row shouldn't produce a stray " | " line
    assert " |  | " not in result


def test_handles_malformed_html_without_raising():
    malformed = "<div><p>Unclosed paragraph<div>Nested badly</p></div>"
    # Should not raise -- lxml's parser is tolerant of malformed markup.
    result = clean_filing_html(malformed)
    assert "Unclosed paragraph" in result
    assert "Nested badly" in result
