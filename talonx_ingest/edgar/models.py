"""
talonx_ingest.edgar.models
---------------------------
Typed data structures shared between the EDGAR client, the cleaner,
and the chunker. Keeping these as explicit dataclasses (rather than
passing raw dicts around) keeps the boundary between "structured
numerical" and "unstructured text" data streams clean, per project
constraints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class FormType(str, Enum):
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_10K_A = "10-K/A"
    FORM_10Q_A = "10-Q/A"


@dataclass(frozen=True)
class CompanyRef:
    """Resolved identity of a target company on EDGAR."""
    ticker: str
    cik: str  # zero-padded 10-digit CIK, e.g. "0000320193"
    name: str

    @property
    def cik_int(self) -> int:
        return int(self.cik)


@dataclass(frozen=True)
class FilingMetadata:
    """Metadata describing one filing, before its document body is fetched."""
    company: CompanyRef
    accession_number: str  # e.g. "0000320193-24-000123"
    form_type: str
    filing_date: date
    report_date: date | None
    primary_document: str  # filename of the primary doc, e.g. "aapl-20240928.htm"
    primary_doc_description: str = ""

    @property
    def accession_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    def primary_document_url(self, archives_base: str) -> str:
        return (
            f"{archives_base}/{self.company.cik_int}/"
            f"{self.accession_no_dashes}/{self.primary_document}"
        )


@dataclass
class FilingDocument:
    """A fetched filing with raw + cleaned text populated progressively."""
    metadata: FilingMetadata
    raw_html: str | None = None
    cleaned_text: str | None = None
    fetch_error: str | None = None

    @property
    def is_ready_for_chunking(self) -> bool:
        return self.cleaned_text is not None and not self.fetch_error


@dataclass
class TextChunk:
    """A single embeddable unit produced by the chunker."""
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)
