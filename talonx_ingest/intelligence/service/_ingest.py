"""
talonx_ingest.intelligence.service._ingest
==========================================
Shared low-level ingest helpers used by both the live poller and the
historical backfill.

* ``ingest_symbol_filings`` — normalise the filings in a submissions
  document, filter to the configured forms + date window, build 96A
  ``TextEvent`` rows and upsert them idempotently, returning exactly which
  ``event_id``\\ s were newly created.
* ``load_submissions_window`` — fetch a company's submissions feed AND any
  older shards under ``filings.files`` whose date range overlaps the
  backfill window, merged into one submissions-shaped dict.

Neither helper delivers, scores, or diffs anything — that is
``enrichment``'s job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from talonx_ingest.intelligence.domain import FreshnessStatus, utc_now
from talonx_ingest.intelligence.edgar_normalize import iter_normalized_filings
from talonx_ingest.intelligence.pipeline import build_events_from_filing

logger = logging.getLogger("talonx_ingest.intelligence.service._ingest")

_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"


@dataclass
class SymbolIngestResult:
    symbol: str
    filings_seen: int = 0
    events_built: int = 0
    events_new: int = 0
    events_existing: int = 0
    new_event_ids: list[str] = field(default_factory=list)
    all_event_ids: list[str] = field(default_factory=list)
    earliest_filing_date: date | None = None
    latest_filing_date: date | None = None
    latest_acceptance_utc: datetime | None = None
    last_accession: str | None = None


def _in_window(d: date | None, since: date | None, until: date | None) -> bool:
    if d is None:
        return since is None  # undated filing kept only when no lower bound
    if since is not None and d < since:
        return False
    if until is not None and d > until:
        return False
    return True


def ingest_symbol_filings(
    events_store,
    submissions_json: dict,
    *,
    symbol: str,
    forms,
    since_date: date | None = None,
    until_date: date | None = None,
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN,
    now: datetime | None = None,
    limit: int | None = None,
) -> SymbolIngestResult:
    now = now or utc_now()
    out = SymbolIngestResult(symbol=symbol.upper())
    forms_tuple = tuple(forms)

    for nf in iter_normalized_filings(submissions_json, symbol=symbol, forms=forms_tuple):
        fdate = nf.filing_date or (
            nf.acceptance_datetime.date() if nf.acceptance_datetime else None
        )
        if not _in_window(fdate, since_date, until_date):
            continue
        out.filings_seen += 1
        if fdate is not None:
            if out.earliest_filing_date is None or fdate < out.earliest_filing_date:
                out.earliest_filing_date = fdate
            if out.latest_filing_date is None or fdate > out.latest_filing_date:
                out.latest_filing_date = fdate
        if nf.acceptance_datetime and (
            out.latest_acceptance_utc is None
            or nf.acceptance_datetime > out.latest_acceptance_utc
        ):
            out.latest_acceptance_utc = nf.acceptance_datetime
        out.last_accession = nf.accession

        for event in build_events_from_filing(nf, freshness=freshness, now=now):
            out.events_built += 1
            out.all_event_ids.append(event.event_id)
            if events_store.upsert_event(event):
                out.events_new += 1
                out.new_event_ids.append(event.event_id)
            else:
                out.events_existing += 1

        if limit is not None and out.filings_seen >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# windowed submissions loader (recent + overlapping older shards)
# ---------------------------------------------------------------------------
def _shard_overlaps(shard_meta: dict, since_date: date | None) -> bool:
    if since_date is None:
        return True
    to_raw = shard_meta.get("filingTo") or shard_meta.get("filingsTo")
    if not to_raw:
        return True  # unknown range -> fetch it, be safe
    try:
        return date.fromisoformat(str(to_raw)[:10]) >= since_date
    except ValueError:
        return True


def _merge_recent(base_json: dict, shard_json: dict) -> None:
    recent = base_json.setdefault("filings", {}).setdefault("recent", {})
    for key, vals in (shard_json or {}).items():
        if isinstance(vals, list):
            recent.setdefault(key, [])
            recent[key].extend(vals)


async def load_submissions_window(
    client,
    cik: str,
    *,
    since_date: date | None = None,
    max_shards: int = 6,
) -> dict:
    """Return a submissions-shaped dict whose ``filings.recent`` arrays hold
    every filing from the base feed PLUS every older shard whose range
    reaches ``since_date``. Shards are fetched through ``client`` (shared
    SEC rate-limit path). Bounded by ``max_shards``."""
    base = await client.get_submissions(cik)
    files = ((base.get("filings") or {}).get("files")) or []
    fetched = 0
    for meta in files:
        if fetched >= max_shards:
            logger.warning("cik=%s: hit max_shards=%d; older history truncated", cik, max_shards)
            break
        name = meta.get("name")
        if not name or not _shard_overlaps(meta, since_date):
            continue
        try:
            raw = await client.fetch_document(f"{_SUBMISSIONS_BASE}/{name}")
            import json as _json

            _merge_recent(base, _json.loads(raw))
            fetched += 1
        except Exception as exc:  # noqa: BLE001 - a missing shard just bounds history
            logger.warning("cik=%s shard %s fetch failed: %s", cik, name, exc)
    return base
