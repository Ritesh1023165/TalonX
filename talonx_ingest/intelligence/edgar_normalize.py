"""
talonx_ingest.intelligence.edgar_normalize
==========================================
Turn a raw SEC EDGAR *submissions* JSON document into ``NormalizedFiling``
records: one per filing, carrying every field the event store needs and
nothing interpreted.

The submissions feed (``data.sec.gov/submissions/CIK##########.json``)
stores its filing history as parallel arrays under ``filings.recent``.
Older history lives in additional shards listed under ``filings.files`` --
out of 96A scope (the live poller only needs ``recent``; historical
backfill is Task 96B). ``iter_normalized_filings`` reads ``recent`` only
and is explicit about it.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from talonx_ingest.intelligence.domain import DataQualityFlag, ExhibitRef
from talonx_ingest.intelligence.identity import AccessionFormatError, normalize_accession
from talonx_ingest.intelligence.taxonomy import is_amendment, normalize_items

_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True)
class NormalizedFiling:
    cik: str                      # zero-padded 10-digit
    symbol: str
    company_name: str
    accession: str                # canonical dashed
    form: str
    acceptance_datetime: datetime | None   # tz-aware UTC -- the event instant
    filing_date: date | None
    report_date: date | None
    primary_document: str | None
    primary_document_url: str | None
    filing_index_url: str
    items: tuple[str, ...] = ()
    is_amendment: bool = False
    exhibits: tuple[ExhibitRef, ...] = ()
    flags: tuple[str, ...] = field(default_factory=tuple)


def parse_acceptance_datetime(raw: str | None) -> datetime | None:
    """Parse EDGAR ``acceptanceDateTime`` to a tz-aware UTC datetime.

    Seen formats: ``2026-07-29T16:04:53.000Z``, ``2026-07-29T16:04:53Z``,
    ``2026-07-29T16:04:53-04:00``, and (rarely) ``2026-07-29 16:04:53``.
    Returns ``None`` for missing/empty/unparseable input -- the caller
    then flags ``missing_acceptance_timestamp``.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        return None


def build_urls(cik: str, accession: str) -> tuple[str, str]:
    """Return ``(filing_index_url, accession_directory_url)``."""
    cik_int = int(cik)
    acc_nodash = accession.replace("-", "")
    directory = f"{_ARCHIVES_BASE}/{cik_int}/{acc_nodash}"
    return f"{directory}/{accession}-index.htm", directory


def _primary_doc_url(cik: str, accession: str, primary_document: str | None) -> str | None:
    if not primary_document:
        return None
    _, directory = build_urls(cik, accession)
    return f"{directory}/{primary_document}"


def normalize_exhibits(index_json: dict, cik: str, accession: str) -> tuple[ExhibitRef, ...]:
    """Parse the accession ``index.json`` (``directory.item`` list) into
    ``ExhibitRef`` records. Returns ``()`` on any structural surprise --
    the caller flags ``exhibit_fetch_failed`` when it expected exhibits."""
    if not isinstance(index_json, dict):
        return ()
    directory = index_json.get("directory") or {}
    items = directory.get("item") or []
    _, base = build_urls(cik, accession)
    out: list[ExhibitRef] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        seq = entry.get("sequence")
        try:
            seq_int = int(seq) if seq not in (None, "", "0") else None
        except (TypeError, ValueError):
            seq_int = None
        out.append(
            ExhibitRef(
                filename=str(name),
                source_url=f"{base}/{name}",
                sequence=seq_int,
                document_type=(entry.get("type") or None),
                description=(entry.get("description") or None),
            )
        )
    return tuple(out)


def _cik_padded(raw) -> str:
    return str(raw).zfill(10)


def iter_normalized_filings(
    submissions_json: dict,
    *,
    symbol: str | None = None,
    forms: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> Iterator[NormalizedFiling]:
    """Yield ``NormalizedFiling`` for each filing in ``filings.recent``.

    ``forms`` filters by base or exact form (``"8-K"`` also matches
    ``"8-K/A"``). ``symbol`` overrides the ticker taken from the feed.
    """
    cik = _cik_padded(submissions_json.get("cik", "0"))
    company_name = submissions_json.get("name") or ""
    feed_tickers = submissions_json.get("tickers") or []
    sym = (symbol or (feed_tickers[0] if feed_tickers else "") or "").upper()

    recent = (submissions_json.get("filings") or {}).get("recent") or {}
    forms_list = recent.get("form", [])
    acc_list = recent.get("accessionNumber", [])
    acc_dt_list = recent.get("acceptanceDateTime", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])
    items_list = recent.get("items", [])

    want_forms = None
    if forms:
        want_forms = set()
        for f in forms:
            fu = f.strip().upper()
            want_forms.add(fu)
            want_forms.add(fu + "/A")

    yielded = 0
    for i, form in enumerate(forms_list):
        if want_forms is not None and form.strip().upper() not in want_forms:
            continue
        raw_acc = acc_list[i] if i < len(acc_list) else None
        try:
            accession = normalize_accession(raw_acc)
        except AccessionFormatError:
            continue  # a filing we cannot address by id is not a usable event

        flags: list[str] = []
        acc_dt = parse_acceptance_datetime(
            acc_dt_list[i] if i < len(acc_dt_list) else None
        )
        if acc_dt is None:
            flags.append(DataQualityFlag.MISSING_ACCEPTANCE_TIMESTAMP.value)

        primary_document = primary_docs[i] if i < len(primary_docs) else None
        if not primary_document:
            flags.append(DataQualityFlag.PRIMARY_DOCUMENT_UNAVAILABLE.value)

        raw_items = items_list[i] if i < len(items_list) else ""
        items = normalize_items(raw_items)

        report_end = _parse_date(report_dates[i] if i < len(report_dates) else None)
        if report_end is None and form.strip().upper().startswith(("10-Q", "10-K")):
            flags.append(DataQualityFlag.MISSING_REPORT_PERIOD_END.value)

        index_url, _ = build_urls(cik, accession)
        yield NormalizedFiling(
            cik=cik,
            symbol=sym,
            company_name=company_name,
            accession=accession,
            form=form,
            acceptance_datetime=acc_dt,
            filing_date=_parse_date(filing_dates[i] if i < len(filing_dates) else None),
            report_date=report_end,
            primary_document=primary_document,
            primary_document_url=_primary_doc_url(cik, accession, primary_document),
            filing_index_url=index_url,
            items=items,
            is_amendment=is_amendment(form),
            exhibits=(),
            flags=tuple(flags),
        )
        yielded += 1
        if limit is not None and yielded >= limit:
            return
