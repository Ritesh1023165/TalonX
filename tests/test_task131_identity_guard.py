"""
Task 131 Directive 4 -- CIK/accession-level identity validation in the
LIVE ingest pipeline (``talonx_ingest.intelligence.service._insider
.ingest_form_ownership``'s ``enforce_issuer_identity`` guard).

Offline: reuses the same ``FakeEdgarClient``/fixtures as the Task 96B
poller tests (no network). Proves a filing whose OWN declared issuerCik
does not match the caller's authoritative, resolved CIK for that symbol
is DROPPED (never persisted) -- and that a genuinely matching filing is
unaffected.
"""
from __future__ import annotations

import asyncio

from talonx_ingest.intelligence.service._insider import ingest_form_ownership
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.stores import StoreBundle

from tests._service_helpers import FORM4_XML, FakeEdgarClient

MISMATCHED_ISSUER_XML = FORM4_XML.replace(
    "<issuerCik>0000012345</issuerCik>", "<issuerCik>0000099999</issuerCik>")


def _bundle(tmp_path):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state")
    return cfg, StoreBundle.open(cfg.ledger())


def test_mismatched_issuer_cik_is_dropped_not_persisted(tmp_path):
    # the XML itself declares issuerCik 0000099999, but the caller
    # (matching production's own poller.py: cik=rs.cik from the
    # authoritative CikDirectory resolution) expects 0000012345 for this
    # symbol -- a real-world case of one ticker's Section 16 filings
    # ever referencing an unrelated/incorrect issuer.
    cfg, stores = _bundle(tmp_path)
    url = "https://www.sec.gov/Archives/edgar/data/12345/000001234526000008/form4.xml"
    client = FakeEdgarClient(documents={url: MISMATCHED_ISSUER_XML})

    outcome = asyncio.run(ingest_form_ownership(
        client, stores.insider, stores.events,
        cik="0000012345", accession="0000012345-26-000008", symbol="FAKE",
        form_type="4", accepted_at_utc=None, primary_document="xslF345X05/form4.xml",
        cache_dir=tmp_path / "cache",
    ))
    assert outcome.ok is False
    assert outcome.identity_check == "DROPPED_MISMATCH"
    assert "ISSUER_CIK_MISMATCH" in (outcome.error or "")
    # nothing was persisted under the mismatched filing
    assert stores.insider.query_transactions(symbol="FAKE") == []


def test_matching_issuer_cik_ingests_normally(tmp_path):
    cfg, stores = _bundle(tmp_path)
    url = "https://www.sec.gov/Archives/edgar/data/12345/000001234526000008/form4.xml"
    client = FakeEdgarClient(documents={url: FORM4_XML})

    outcome = asyncio.run(ingest_form_ownership(
        client, stores.insider, stores.events,
        cik="0000012345", accession="0000012345-26-000008", symbol="FAKE",
        form_type="4", accepted_at_utc=None, primary_document="xslF345X05/form4.xml",
        cache_dir=tmp_path / "cache",
    ))
    assert outcome.ok is True
    assert outcome.identity_check == "MATCHED"
    assert outcome.transactions_new >= 1
    assert stores.insider.query_transactions(symbol="FAKE") != []


def test_identity_enforcement_can_be_explicitly_disabled(tmp_path):
    # an explicit, non-default opt-out -- never the default behaviour.
    cfg, stores = _bundle(tmp_path)
    url = "https://www.sec.gov/Archives/edgar/data/12345/000001234526000008/form4.xml"
    client = FakeEdgarClient(documents={url: MISMATCHED_ISSUER_XML})

    outcome = asyncio.run(ingest_form_ownership(
        client, stores.insider, stores.events,
        cik="0000012345", accession="0000012345-26-000008", symbol="FAKE",
        form_type="4", accepted_at_utc=None, primary_document="xslF345X05/form4.xml",
        cache_dir=tmp_path / "cache", enforce_issuer_identity=False,
    ))
    assert outcome.ok is True
    assert outcome.identity_check == "NOT_ENFORCED"
