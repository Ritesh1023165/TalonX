"""
tests/test_intel_identity_drop_health.py
----------------------------------------
2026-10-07 incident: an ownership filing listed in a watched CIK's submissions but declaring a DIFFERENT, parseable
issuer CIK (the watched entity is the filer / reporting owner) was correctly dropped by the Task 131 identity guard
-- and then counted as a poll error on every cycle, so the Intelligence health predicate raised POLL_ERRORS every
~3 min (37 hourly Operations alerts) while every symbol was FRESH.

Fix under test: that specific, verified-content drop is telemetry (``identity_drops``), not a poll error. Every
genuine failure (submissions fetch, ownership XML fetch, a filing with no parseable issuer CIK) still counts, and
genuine freshness degradation still alerts. Offline (FakeEdgarClient); no network.
"""
from __future__ import annotations

import asyncio

from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.poll_history import read as read_history, record as record_history
from talonx_ingest.intelligence.service.poller import EdgarPoller
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ops.notify.producers import intelligence_health_causes
from tests._service_helpers import FORM4_XML, FakeEdgarClient, FakeWatchlistStore, make_submissions, wl_row

FORM4_ACCN = "0000012345-26-000008"            # the only Form 4 in default_rows()
OTHER_ISSUER_XML = FORM4_XML.replace("<issuerCik>0000012345</issuerCik>", "<issuerCik>0001083839</issuerCik>")
NO_ISSUER_CIK_XML = FORM4_XML.replace("<issuerCik>0000012345</issuerCik>", "")


class _Client(FakeEdgarClient):
    """Serves a chosen ownership XML for the Form 4 accession (or raises for it)."""

    def __init__(self, *, form4_xml: str | None = FORM4_XML, form4_raises: bool = False, **kw):
        super().__init__(**kw)
        self._form4_xml, self._form4_raises = form4_xml, form4_raises

    async def fetch_document(self, url: str) -> str:
        if FORM4_ACCN.replace("-", "") in url and url.endswith(".xml"):
            self.calls.append(("fetch_document", url))
            if self._form4_raises:
                raise RuntimeError("HTTP 503 Service Unavailable")
            return self._form4_xml
        return await super().fetch_document(url)


def _setup(tmp_path, **client_kw):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state", history_days=3650)
    stores = StoreBundle.open(cfg.ledger())
    client = _Client(submissions={"0000012345": make_submissions()}, **client_kw)
    directory = CikDirectory.from_company_tickers(
        {"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."}})
    scope = resolve_scope(config=cfg, watchlist_store=FakeWatchlistStore([wl_row("FAKE")]), directory=directory)
    return cfg, stores, EdgarPoller(stores, client, config=cfg, scope=scope, enrichment=None)


def _causes(res):
    return intelligence_health_causes(symbols_failed=res.symbols_failed, poll_errors=len(res.errors),
                                      recovery=None, delivery_ok=True, freshness=res.submissions_freshness)


def test_other_issuer_filing_is_telemetry_not_a_poll_error(tmp_path):
    cfg, stores, poller = _setup(tmp_path, form4_xml=OTHER_ISSUER_XML)
    res = asyncio.run(poller.poll_once())
    assert res.identity_drops == 1
    assert res.errors == [] and res.symbols_failed == 0
    assert res.submissions_freshness == "FRESH"
    assert _causes(res) == []                                   # no Operations health incident
    assert stores.insider.count_transactions() == 0             # still dropped: never persisted / force-mapped
    stores.close()


def test_persistent_other_issuer_filing_never_raises_poll_errors(tmp_path):
    """The live failure mode: the same dropped accession is re-seen every cycle."""
    cfg, stores, poller = _setup(tmp_path, form4_xml=OTHER_ISSUER_XML)
    for _ in range(4):
        res = asyncio.run(poller.poll_once())
        assert res.identity_drops == 1 and res.errors == [] and _causes(res) == []
    stores.close()


def test_filing_without_parseable_issuer_cik_still_counts_as_error(tmp_path):
    cfg, stores, poller = _setup(tmp_path, form4_xml=NO_ISSUER_CIK_XML)
    res = asyncio.run(poller.poll_once())
    assert res.identity_drops == 0
    assert len(res.errors) == 1 and FORM4_ACCN in res.errors[0]
    assert "POLL_ERRORS" in _causes(res)
    stores.close()


def test_ownership_xml_fetch_failure_still_counts_as_error(tmp_path):
    cfg, stores, poller = _setup(tmp_path, form4_raises=True)
    res = asyncio.run(poller.poll_once())
    assert res.identity_drops == 0
    assert len(res.errors) == 1 and "POLL_ERRORS" in _causes(res)
    stores.close()


def test_submissions_outage_still_degrades(tmp_path):
    cfg, stores, poller = _setup(tmp_path, form4_xml=OTHER_ISSUER_XML)
    poller.client.fail_submissions_for = {12345}
    res = asyncio.run(poller.poll_once())
    assert res.symbols_failed == 1 and res.identity_drops == 0
    causes = _causes(res)
    assert "POLL_SYMBOL_FAILURES" in causes and "POLL_ERRORS" in causes
    stores.close()


def test_matching_issuer_unchanged(tmp_path):
    cfg, stores, poller = _setup(tmp_path)
    res = asyncio.run(poller.poll_once())
    assert res.identity_drops == 0 and res.errors == [] and res.new_form4_filings == 1
    stores.close()


def test_stale_or_down_source_still_alerts_without_any_error():
    assert intelligence_health_causes(symbols_failed=0, poll_errors=0, recovery=None, delivery_ok=True,
                                      freshness="STALE") == ["SOURCE_STALE"]
    assert intelligence_health_causes(symbols_failed=0, poll_errors=0, recovery=None, delivery_ok=True,
                                      freshness="DOWN") == ["SOURCE_DOWN"]


def test_poll_history_records_identity_drops(tmp_path):
    record_history(tmp_path, cycle=1, summary={"at_utc": "2026-10-07T09:00:00+00:00", "errors": [],
                                              "identity_drops": 1, "health_causes": []})
    record_history(tmp_path, cycle=2, summary={"at_utc": "2026-10-07T09:03:00+00:00", "errors": ["x"]})
    h = read_history(tmp_path)
    assert h[0]["identity_drops"] == 1 and h[0]["error_count"] == 0
    assert h[1]["identity_drops"] == 0 and h[1]["error_count"] == 1
