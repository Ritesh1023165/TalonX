"""
talonx_ingest.processing.cleaner
----------------------------------
Normalizes raw SEC filing HTML into clean plain text suitable for chunking
and embedding. 10-K/10-Q filings are typically messy HTML with inline
styling, XBRL tags, and heavy tables -- this strips that down to readable
prose while preserving paragraph/table boundaries the chunker relies on.
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger("talonx_ingest.processing.cleaner")

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Tags whose contents are never useful prose (scripts, styles, hidden XBRL).
_STRIP_TAGS = ("script", "style", "head", "noscript", "ix:header")


def clean_filing_html(raw_html: str) -> str:
    """
    Convert raw filing HTML to normalized plain text.

    Strategy:
      1. Parse with BeautifulSoup (lxml parser for speed/robustness on
         malformed SEC HTML).
      2. Drop non-content tags entirely.
      3. Render tables as pipe-delimited rows so numeric structure survives
         into the text stream without dragging in HTML markup.
      4. Collapse excess whitespace while preserving paragraph breaks.
    """
    if not raw_html or not raw_html.strip():
        return ""

    soup = BeautifulSoup(raw_html, "lxml")

    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for table in soup.find_all("table"):
        table.replace_with(_render_table_as_text(table))

    text = soup.get_text(separator="\n")
    return _normalize_whitespace(text)


def _render_table_as_text(table) -> str:
    """Flatten an HTML table into newline-delimited, pipe-separated rows."""
    rows_out = []
    for row in table.find_all("tr"):
        cells = [
            cell.get_text(strip=True)
            for cell in row.find_all(["td", "th"])
        ]
        cells = [c for c in cells if c]
        if cells:
            rows_out.append(" | ".join(cells))
    return "\n" + "\n".join(rows_out) + "\n" if rows_out else ""


def _normalize_whitespace(text: str) -> str:
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()
