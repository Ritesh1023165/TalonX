"""
talonx_ingest.intelligence.service._insider
===========================================
Shared Form 3/4/5 ownership-XML fetch + ingest, used by both the poller and
the backfill.

``ingest_form_ownership`` resolves a filing's primary ownership XML (via the
accession ``index.json``), fetches it through ``EdgarClient`` (shared SEC
rate-limit path), caches the raw XML by accession on local disk so a
restart never re-downloads it, and hands it to the already-qualified 96D
``ingest_form4_xml`` (which creates the ``INSIDER_TRANSACTION`` parent
event on the 96A store and persists transactions idempotently).

Bulk quarterly datasets (96D ``ingest_bulk_rows``) remain the deeper
historical path; per-filing XML converges with them by the 96D store's
content-addressed ``transaction_id`` merge.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.insider.pipeline import ingest_form4_xml

logger = logging.getLogger("talonx_ingest.intelligence.service._insider")

# Task 131 Directive 4: CIK/accession-level identity validation. Reused
# lazily (deferred import) to keep this module's import graph unchanged
# for every existing caller that does not pass a ``directory``.


def _cache_dir() -> Path:
    return Path(settings.raw_cache_dir).parent / "form_ownership_xml_cache"


def _pick_xml(index_json: dict) -> str | None:
    items = ((index_json or {}).get("directory") or {}).get("item") or []
    best, best_size = None, -1
    for it in items:
        if not isinstance(it, dict):
            continue
        n = it.get("name") or ""
        low = n.lower()
        if not low.endswith(".xml"):
            continue
        if low.startswith("r") and low[1:2].isdigit():
            continue
        if any(m in low for m in ("metalinks", "_cal", "_def", "_lab", "_pre")):
            continue
        try:
            sz = int(it.get("size") or 0)
        except (TypeError, ValueError):
            sz = 0
        if best is None or (0 < sz < best_size) or best_size < 0:
            best, best_size = n, sz if sz else 1
    return best


@dataclass
class OwnershipIngestOutcome:
    accession: str
    symbol: str
    ok: bool
    transactions_new: int = 0
    transactions_total: int = 0
    parent_event_created: bool = False
    from_cache: bool = False
    error: str | None = None
    xml_url: str | None = None
    identity_check: str | None = None  # Task 131 Directive 4 -- outcome, when enforced


def _candidate_xml_names(primary_document: str | None) -> list[str]:
    """Order to try the ownership XML without an index.json round-trip.

    The submissions feed's ``primaryDocument`` for a Form 3/4/5 is usually
    ``xslF345X05/<name>.xml`` (the styled view) or ``<name>.xml``. The raw
    XML lives at the same directory under ``<name>.xml`` (no ``xsl`` prefix)
    and, failing that, the canonical ``<accession>.xml``.
    """
    out: list[str] = []
    pd = (primary_document or "").strip()
    if pd:
        base = pd.split("/")[-1]
        if base.lower().endswith(".xml"):
            if base not in out:
                out.append(base)
        if pd not in out:
            out.append(pd)  # try the styled path too (some agents only file that)
    return out


async def ingest_form_ownership(
    client,
    insider_store,
    event_store,
    *,
    cik: str,
    accession: str,
    symbol: str,
    form_type: str,
    accepted_at_utc: datetime | None,
    primary_document: str | None = None,
    cache_dir: Path | None = None,
    enforce_issuer_identity: bool = True,
    filing_date: date | None = None,
) -> OwnershipIngestOutcome:
    """``enforce_issuer_identity`` (Task 131 Directive 4, default ON): once
    the ownership XML is retrieved, its OWN declared ``issuerCik`` is
    compared against ``cik`` (the caller's authoritative, currently-
    resolved CIK for ``symbol`` -- the same identity this call's own SEC
    Archives URL was already built from). A mismatch means this specific
    filing's own declared issuer does not match the entity currently,
    authoritatively associated with ``symbol`` -- it is DROPPED (never
    persisted), not silently force-mapped. Every check outcome (pass or
    drop) is returned explicitly in ``OwnershipIngestOutcome.identity_check``,
    never silently swallowed."""
    acc_nd = accession.replace("-", "")
    cik_int = int(str(cik).lstrip("CIK"))
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nd}"
    cdir = Path(cache_dir) if cache_dir is not None else _cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cpath = cdir / f"{accession}.xml"

    xml: str | None = None
    from_cache = False
    xml_url: str | None = None
    if cpath.is_file():
        try:
            xml = cpath.read_text(encoding="utf-8", errors="replace")
            from_cache = True
        except OSError:
            xml = None

    if xml is None:
        # 1) try the primaryDocument-derived name(s) directly (no index.json)
        for name in _candidate_xml_names(primary_document):
            try:
                candidate = await client.fetch_document(f"{base_url}/{name}")
            except Exception:  # noqa: BLE001 - fall through to the index lookup
                continue
            if candidate.lstrip().startswith("<"):
                xml, xml_url = candidate, f"{base_url}/{name}"
                break
        # 2) fall back to the accession index.json
        if xml is None:
            try:
                idx = await client.fetch_filing_index(cik_int, accession)
                name = _pick_xml(idx)
            except Exception as exc:  # noqa: BLE001
                return OwnershipIngestOutcome(accession, symbol, False, error=f"index: {exc}")
            if not name:
                return OwnershipIngestOutcome(
                    accession, symbol, False, error="no ownership xml in filing"
                )
            xml_url = f"{base_url}/{name}"
            try:
                xml = await client.fetch_document(xml_url)
            except Exception as exc:  # noqa: BLE001
                return OwnershipIngestOutcome(accession, symbol, False,
                                             error=f"xml fetch: {exc}", xml_url=xml_url)
        try:
            cpath.write_text(xml, encoding="utf-8")
        except OSError:
            pass

    identity_check_result = "NOT_ENFORCED"
    if enforce_issuer_identity:
        from talonx_ingest.intelligence.insider.ownership_xml import parse_ownership_xml
        from talonx_ingest.intelligence.service.identity_guard import (
            check_filing_issuer_identity, log_identity_check)
        try:
            probe_filing, _probe_txns = parse_ownership_xml(
                xml, accession=accession, accepted_at_utc=accepted_at_utc,
                symbol_hint=symbol, form_type_hint=form_type, source_reference=xml_url,
                filing_date=filing_date)
        except Exception as exc:  # noqa: BLE001
            return OwnershipIngestOutcome(accession, symbol, False, from_cache=from_cache,
                                         error=f"identity pre-parse: {exc}", xml_url=xml_url,
                                         identity_check="PARSE_FAILED")
        check = check_filing_issuer_identity(
            symbol=symbol, accession=accession,
            filing_issuer_cik=probe_filing.issuer_cik or "", expected_cik=cik)
        log_identity_check(check)
        if not check.ok:
            return OwnershipIngestOutcome(accession, symbol, False, from_cache=from_cache,
                                         error=check.reason, xml_url=xml_url,
                                         identity_check="DROPPED_" + (
                                             "NO_CIK" if not check.filing_issuer_cik else "MISMATCH"))
        identity_check_result = "MATCHED"

    try:
        r1 = ingest_form4_xml(
            insider_store, xml, accession=accession, accepted_at_utc=accepted_at_utc,
            event_store=event_store, symbol_hint=symbol, form_type_hint=form_type,
            source_url=xml_url, filing_date=filing_date,
        )
    except Exception as exc:  # noqa: BLE001
        return OwnershipIngestOutcome(accession, symbol, False, from_cache=from_cache,
                                     error=f"parse/ingest: {exc}", xml_url=xml_url,
                                     identity_check=identity_check_result)

    return OwnershipIngestOutcome(
        accession=accession,
        symbol=symbol,
        ok=True,
        identity_check=identity_check_result,
        transactions_new=r1.transactions_new,
        transactions_total=r1.transactions_built,
        parent_event_created=bool(r1.parent_events_created),
        from_cache=from_cache,
        xml_url=xml_url,
    )
