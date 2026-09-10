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

# --------------------------------------------------------------------------- #
# Acceptance-timestamp source contract  (see timestamp_source_contract.md)
#
# VERIFIED by a 10-accession cross-reference of the raw Form-4 SGML header
# ``<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`` (US/Eastern, naive) against the
# ``data.sec.gov/submissions`` JSON ``acceptanceDateTime`` (``...000Z``) for the
# same filings, all in EDT:
#
#   SGML 2026-08-27T18:30:30  ==  JSON 2026-08-27T22:30:30.000Z   (18:30 EDT = 22:30 UTC)
#   ... 10/10 show JSON = SGML-Eastern + 4h  ==>  the submissions JSON
#   ``acceptanceDateTime`` is a GENUINE UTC instant. The ``Z`` is correct.
#
# So a ``Z`` / ``+00:00`` value FROM THE SUBMISSIONS FEED means UTC -- it is NOT
# reinterpreted. Only the raw SGML ``<ACCEPTANCE-DATETIME>`` field (which this
# pipeline does not currently parse) is Eastern-naive; a caller that parses it
# passes ``source="sgml_header"`` to get Eastern localization.
# --------------------------------------------------------------------------- #
_ET = ZoneInfo("America/New_York")
_EXPLICIT_OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")

#: which raw source field a value came from -> how to read a value that carries
#: no usable UTC offset. "submissions" (the wired path) == UTC.
ACCEPTANCE_SOURCE_TZ: dict[str, str] = {
    "submissions": "UTC",        # data.sec.gov/submissions acceptanceDateTime -- VERIFIED UTC
    "sgml_header": "US/Eastern",  # Archives *.hdr.sgml <ACCEPTANCE-DATETIME> -- VERIFIED Eastern-naive
    "fulltext": "UTC",           # efts.sec.gov -- carries an explicit offset anyway
}
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
    raw: str | None, *, source: str = "submissions",
) -> tuple[datetime | None, tuple[str, ...]]:
    """Parse a SEC acceptance timestamp to a tz-aware **true-UTC** datetime,
    returning ``(dt, flags)``.

    Seen formats: ``2026-07-29T16:04:53.000Z``, ``2026-07-29T16:04:53Z``,
    ``2026-07-29T16:04:53-04:00``, ``2026-07-29T16:04:53+00:00``,
    ``2026-07-29 16:04:53`` and the raw SGML ``20260729160453``.

    Rules (see ``timestamp_source_contract.md``):

    - An explicit **non-zero** UTC offset (``-04:00`` / ``+05:30`` ...) is
      trusted verbatim and converted to UTC. No flag.
    - A bare ``Z`` / ``+00:00`` marker is read per the ``source`` contract:
      ``"submissions"`` (the wired path) -> **genuine UTC** (VERIFIED: the
      submissions JSON already converts the SGML-Eastern wall-clock to UTC).
    - A **naive** value (no offset at all) is read per the ``source``
      contract: ``"submissions"``/``"fulltext"`` -> UTC (+ an
      ``acceptance_offset_absent`` flag, since naive is technically
      ambiguous); ``"sgml_header"`` -> **US/Eastern**, localized DST-correct
      (+ ``acceptance_tz_source_sgml_eastern``). A non-existent spring-forward
      wall-clock is pushed forward one hour; an ambiguous fall-back one is
      taken as the earlier (pre-transition) instant -- both flagged
      ``acceptance_dst_wallclock_adjusted``.

    Returns ``(None, ())`` for missing/empty/unparseable input.
    """
    if not raw:
        return None, ()
    s = str(raw).strip()
    if not s:
        return None, ()

    # raw SGML compact form: 14 digits, no separators
    if len(s) == 14 and s.isdigit():
        s = f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}"
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

    if explicit_offset or dt.tzinfo is not None:
        # a real offset, or a bare Z / +00:00 marker -> that IS the instant.
        # (submissions JSON is VERIFIED-UTC; efts.sec.gov carries a real offset.)
        return dt.astimezone(timezone.utc), ()

    # ---- naive value: read per the source contract ----------------------
    contract = ACCEPTANCE_SOURCE_TZ.get(source, "UTC")
    if contract == "US/Eastern":
        from datetime import timedelta

        adjusted = False
        local0 = dt.replace(tzinfo=_ET, fold=0)
        local1 = dt.replace(tzinfo=_ET, fold=1)
        roundtrips = local0.astimezone(timezone.utc).astimezone(_ET).replace(tzinfo=None) == dt
        if not roundtrips:
            # spring-forward GAP: the wall-clock does not exist -> +1h.
            local = (dt + timedelta(hours=1)).replace(tzinfo=_ET)
            adjusted = True
        elif local0.utcoffset() != local1.utcoffset():
            # fall-back OVERLAP: the wall-clock occurs twice -> earlier (fold=0).
            local = local0
        else:
            local = local0
        flags = (DataQualityFlag.ACCEPTANCE_TZ_SOURCE_SGML_EASTERN.value,)
        if adjusted:
            flags += (DataQualityFlag.ACCEPTANCE_DST_WALLCLOCK_ADJUSTED.value,)
        return local.astimezone(timezone.utc), flags

    # default: naive == UTC, but note the missing offset
    return (
        dt.replace(tzinfo=timezone.utc),
        (DataQualityFlag.ACCEPTANCE_OFFSET_ABSENT.value,),
    )


def parse_acceptance_datetime(raw: str | None, *, source: str = "submissions") -> datetime | None:
    """Back-compat thin wrapper over :func:`parse_acceptance_datetime_ex`
    that drops the data-quality flags. New callers that persist provenance
    should use the ``_ex`` form."""
    return parse_acceptance_datetime_ex(raw, source=source)[0]


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
            acc_dt_list[i] if i < len(acc_dt_list) else None, source="submissions"
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
