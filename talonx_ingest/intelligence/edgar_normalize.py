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

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from talonx_ingest.intelligence.domain import DataQualityFlag, ExhibitRef

# SEC EDGAR renders every acceptance wall-clock in US Eastern (the 5:30 PM ET
# cutoff that rolls a filing to the next business day is an Eastern rule).
# The ``data.sec.gov/submissions`` feed nonetheless stamps ``acceptanceDateTime``
# with a bare ``...Z`` -- a UTC *marker* on an Eastern *wall-clock*. Treating
# that ``Z`` literally puts every acceptance instant 4h (EDT) / 5h (EST) in the
# past, which mis-buckets after-close filings as RTH and biases as-of replay
# causal cutoffs. When True, a bare ``Z`` / ``+00:00`` / naive value is
# localized to America/New_York and converted to true UTC (explicit non-zero
# offsets, e.g. from ``efts.sec.gov``, are always trusted as-is). Flip to False
# only to reproduce the historical (pre-fix) ingestion exactly.
EDGAR_ACCEPTANCE_ASSUMES_EASTERN = True
_EDGAR_ET = ZoneInfo("America/New_York")
_EXPLICIT_OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")
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


def parse_acceptance_datetime_ex(
    raw: str | None,
) -> tuple[datetime | None, tuple[str, ...]]:
    """Parse EDGAR ``acceptanceDateTime`` to a tz-aware **true-UTC** datetime,
    returning ``(dt, flags)``.

    Seen formats: ``2026-07-29T16:04:53.000Z``, ``2026-07-29T16:04:53Z``,
    ``2026-07-29T16:04:53-04:00``, ``2026-07-29T16:04:53+00:00`` and (rarely)
    ``2026-07-29 16:04:53``.

    - An explicit **non-zero** UTC offset (``-04:00`` / ``+05:30`` ...) is
      trusted verbatim and converted to UTC. No flag.
    - A bare ``Z``, a literal ``+00:00``, or no offset at all is the SEC
      ``submissions`` convention: an **Eastern** wall-clock wearing a UTC
      marker. When ``EDGAR_ACCEPTANCE_ASSUMES_EASTERN`` it is localized to
      ``America/New_York`` (DST-correct) and converted to true UTC, and
      ``acceptance_tz_assumed_eastern`` is flagged. When the switch is off the
      old behaviour (assume the marker is real UTC) is kept.

    Returns ``(None, ())`` for missing/empty/unparseable input -- the caller
    then flags ``missing_acceptance_timestamp``.
    """
    if not raw:
        return None, ()
    s = str(raw).strip()
    if not s:
        return None, ()
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)

    explicit_offset = bool(_EXPLICIT_OFFSET_RE.search(s)) and not s.endswith(
        ("+00:00", "-00:00", "+0000", "-0000")
    )
    s_iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s_iso)
    except ValueError:
        return None, ()

    if explicit_offset:
        # a real offset (efts.sec.gov / RSS) -- trust it
        return dt.astimezone(timezone.utc), ()

    # bare Z / +00:00 / naive -> EDGAR Eastern wall-clock convention
    if EDGAR_ACCEPTANCE_ASSUMES_EASTERN:
        naive = dt.replace(tzinfo=None)
        return (
            naive.replace(tzinfo=_EDGAR_ET).astimezone(timezone.utc),
            (DataQualityFlag.ACCEPTANCE_TZ_ASSUMED_EASTERN.value,),
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), ()


def parse_acceptance_datetime(raw: str | None) -> datetime | None:
    """Back-compat thin wrapper over :func:`parse_acceptance_datetime_ex`
    that drops the data-quality flags. New callers that persist provenance
    should use the ``_ex`` form so the Eastern-assumption is auditable."""
    return parse_acceptance_datetime_ex(raw)[0]


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
        acc_dt, acc_flags = parse_acceptance_datetime_ex(
            acc_dt_list[i] if i < len(acc_dt_list) else None
        )
        flags.extend(acc_flags)
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
