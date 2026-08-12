"""
talonx_ingest.pipeline
------------------------
Orchestrates the unstructured-text ingestion path end-to-end:

    tickers -> CIK resolution -> recent 10-K/10-Q filings
            -> [ledger check: skip already-ingested filings]
            -> raw HTML fetch -> clean -> chunk -> embed -> ChromaDB
            -> [ledger: mark each filing complete once its chunks land]

This module only touches the unstructured/text side of TalonX. The
structured market-data stream (WebSocket/yfinance polling) is a separate
module -- see talonx_ingest.market_data.

Incremental ingestion: a filing is only re-fetched/re-processed if it's
NOT already recorded as fully ingested in the local ledger (SQLite, see
talonx_ingest.storage.ledger). Since SEC filings are immutable once filed,
this is a safe permanent skip -- no staleness/TTL logic needed. Use
--force-refresh to bypass the ledger and reprocess everything anyway
(e.g. after a chunking/embedding config change you want reflected).
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from talonx_ingest.config import settings
from talonx_ingest.edgar.client import EdgarClient, EdgarClientError
from talonx_ingest.edgar.financials import parse_company_facts
from talonx_ingest.edgar.models import FilingDocument
from talonx_ingest.events.publisher import RedisEventPublisher
from talonx_ingest.events.schemas import NewFilingIngestedEvent, NewFundamentalsIngestedEvent
from talonx_ingest.processing.chunker import DocumentChunker
from talonx_ingest.processing.cleaner import clean_filing_html
from talonx_ingest.storage.ledger import IngestionLedger
from talonx_ingest.storage.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_ingest.pipeline")


async def ingest_ticker(
    ticker: str,
    edgar_client: EdgarClient,
    chunker: DocumentChunker,
    vector_store: VectorStore,
    ledger: IngestionLedger,
    publisher: RedisEventPublisher,
    force_refresh: bool = False,
) -> int:
    """
    Run the full text ingestion path for a single ticker, skipping any
    filing already recorded as fully ingested (unless force_refresh).
    Returns the number of NEW chunks written this run (not the ticker's
    total chunk count in the store).
    """
    logger.info("[%s] Resolving ticker -> CIK...", ticker)
    try:
        company = await edgar_client.resolve_ticker(ticker)
    except EdgarClientError as exc:
        logger.error("Skipping %s: %s", ticker, exc)
        return 0

    all_filings = await edgar_client.get_recent_filings(company)
    if not all_filings:
        logger.warning("No target filings found for %s", ticker)
        return 0

    if force_refresh:
        target_filings = all_filings
        logger.info(
            "[%s] --force-refresh set: reprocessing all %d filings "
            "regardless of ledger state", ticker, len(target_filings),
        )
    else:
        target_filings = ledger.filter_unseen(all_filings)

    if not target_filings:
        logger.info(
            "[%s] Up to date -- all %d recent filings already ingested",
            ticker, len(all_filings),
        )
        return 0

    documents = await edgar_client.fetch_documents(target_filings)
    _clean_documents_inplace(documents)

    total_written = 0
    for document in documents:
        chunks = chunker.chunk_document(document)
        if not chunks:
            # Either the fetch/clean failed (fetch_error set -- don't mark
            # ledger, allow retry next run) or the filing genuinely produced
            # no usable text. Either way, nothing to write or record.
            continue

        written = vector_store.upsert_chunks(chunks)
        if written == len(chunks):
            ledger.mark_ingested(document.metadata, chunk_count=written)
            total_written += written
            await _publish_filing_event(publisher, document.metadata, written)
        else:
            # Partial upsert -- don't mark as ingested so it's retried
            # cleanly next run rather than left in an inconsistent state.
            logger.error(
                "[%s] Partial upsert for %s (%d/%d chunks written) -- "
                "NOT marking ledger complete, will retry next run",
                ticker, document.metadata.accession_number, written, len(chunks),
            )

    logger.info(
        "[%s] Ingested %d new chunks across %d filing(s) this run",
        ticker, total_written, len(target_filings),
    )
    return total_written


async def _publish_filing_event(
    publisher: RedisEventPublisher, metadata, chunk_count: int
) -> None:
    event = NewFilingIngestedEvent(
        ticker=metadata.company.ticker,
        cik=metadata.company.cik,
        company_name=metadata.company.name,
        form_type=metadata.form_type,
        accession_number=metadata.accession_number,
        filing_date=metadata.filing_date.isoformat(),
        report_date=metadata.report_date.isoformat() if metadata.report_date else None,
        source_document=metadata.primary_document,
        chunk_count=chunk_count,
        vector_collection=settings.vector_store.collection_name,
    )
    await publisher.publish_filing_ingested(event)


async def ingest_long_term_financials(
    ticker: str,
    edgar_client: EdgarClient,
    ledger: IngestionLedger,
    publisher: RedisEventPublisher,
) -> int:
    """
    Phase 2's LONG_TERM path -- fetches SEC XBRL structured financials
    (numbers, not filing text) for a ticker, parses up to 10 years of
    annual facts, and publishes them as ONE NewFundamentalsIngestedEvent
    if a fiscal year newer than the ledger's last-known one is found.
    Deliberately independent of ingest_ticker()'s text-ingestion path --
    same EdgarClient session, same CIK resolution, but a completely
    separate data source (XBRL company facts vs. raw filing HTML) with
    its own idempotency tracking (ledger.latest_ingested_fiscal_year,
    keyed by CIK+fiscal_year, not accession number).

    Returns the number of new fiscal years published this run (0 if
    already up to date, or if the ticker/facts couldn't be resolved).
    """
    logger.info("[%s] Resolving ticker -> CIK for financials...", ticker)
    try:
        company = await edgar_client.resolve_ticker(ticker)
    except EdgarClientError as exc:
        logger.error("Skipping financials for %s: %s", ticker, exc)
        return 0

    try:
        raw_facts = await edgar_client.get_company_facts(company)
    except EdgarClientError as exc:
        logger.error("Failed to fetch company facts for %s (%s): %s", ticker, company.cik, exc)
        return 0

    facts = parse_company_facts(raw_facts, ticker=ticker, cik=company.cik)
    if not facts:
        logger.warning("No usable annual financial facts found for %s (%s)", ticker, company.cik)
        return 0

    latest_known = ledger.latest_ingested_fiscal_year(company.cik)
    latest_available = facts[0].fiscal_year
    if latest_known is not None and latest_available <= latest_known:
        logger.info(
            "[%s] Financials up to date -- latest available FY%d already ingested",
            ticker, latest_available,
        )
        return 0

    await publisher.publish_fundamentals_ingested(
        NewFundamentalsIngestedEvent(ticker=ticker.upper(), cik=company.cik, facts=facts)
    )
    ledger.mark_financials_ingested(ticker, company.cik, [f.fiscal_year for f in facts])
    logger.info(
        "[%s] Published fresh financials: FY%d (and %d prior year(s) of context)",
        ticker, latest_available, len(facts) - 1,
    )
    return 1


def _clean_documents_inplace(documents: list[FilingDocument]) -> None:
    """Cleaning is CPU-bound and synchronous; run it after all I/O completes."""
    for doc in documents:
        if doc.fetch_error or doc.raw_html is None:
            continue
        try:
            doc.cleaned_text = clean_filing_html(doc.raw_html)
        except Exception as exc:  # malformed HTML shouldn't kill the batch
            doc.fetch_error = f"clean_failed: {exc}"
            logger.error(
                "Failed to clean %s (%s): %s",
                doc.metadata.company.ticker, doc.metadata.accession_number, exc,
            )


async def run_ingestion(
    tickers: list[str], force_refresh: bool = False
) -> dict[str, int]:
    """Entrypoint: ingest a batch of tickers concurrently (bounded by EdgarClient)."""
    logger.info("Starting ingestion for tickers: %s", tickers)

    logger.info("Initializing chunker...")
    chunker = DocumentChunker()

    logger.info(
        "Initializing vector store (first run downloads the embedding "
        "model, ~90MB, from huggingface.co -- this can take a while and "
        "shows its own progress bar, not our log lines)..."
    )
    vector_store = VectorStore()
    logger.info("Vector store ready. Existing chunk count: %d", vector_store.count())

    ledger = IngestionLedger(settings.ledger.path)
    logger.info("Ingestion ledger ready at %s", settings.ledger.path)

    publisher = RedisEventPublisher()
    await publisher.connect()  # logs a warning and continues if Redis is unavailable

    logger.info("Opening SEC EDGAR session...")
    results: dict[str, int] = {}

    try:
        async with EdgarClient() as edgar_client:
            tasks = {
                ticker: asyncio.create_task(
                    ingest_ticker(
                        ticker, edgar_client, chunker, vector_store, ledger, publisher,
                        force_refresh=force_refresh,
                    )
                )
                for ticker in tickers
            }
            for ticker, task in tasks.items():
                try:
                    results[ticker] = await task
                except Exception as exc:  # noqa: BLE001 -- isolate per-ticker failures
                    logger.error("Unhandled error ingesting %s: %s", ticker, exc)
                    results[ticker] = 0
    finally:
        ledger.close()
        await publisher.close()

    return results


async def run_long_term_financials_ingestion(tickers: list[str]) -> dict[str, int]:
    """Phase 2's batch entrypoint for the structured-financials path --
    same shape as run_ingestion() above (own EdgarClient session, own
    ledger/publisher, per-ticker task with isolated failure handling),
    calling ingest_long_term_financials() instead of ingest_ticker().
    Deliberately a separate function, not a branch inside run_ingestion:
    the two paths share only the EdgarClient/ledger/publisher plumbing,
    not the actual per-ticker work (text ingestion vs. XBRL facts)."""
    logger.info("Starting long-term financials ingestion for tickers: %s", tickers)

    ledger = IngestionLedger(settings.ledger.path)
    publisher = RedisEventPublisher()
    await publisher.connect()  # logs a warning and continues if Redis is unavailable

    results: dict[str, int] = {}
    try:
        async with EdgarClient() as edgar_client:
            tasks = {
                ticker: asyncio.create_task(
                    ingest_long_term_financials(ticker, edgar_client, ledger, publisher)
                )
                for ticker in tickers
            }
            for ticker, task in tasks.items():
                try:
                    results[ticker] = await task
                except Exception as exc:  # noqa: BLE001 -- isolate per-ticker failures
                    logger.error("Unhandled error ingesting financials for %s: %s", ticker, exc)
                    results[ticker] = 0
    finally:
        ledger.close()
        await publisher.close()

    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TalonX SEC filing ingestion")
    parser.add_argument(
        "tickers", nargs="*", default=["AAPL", "MSFT", "NVDA"],
        help="Ticker symbols to ingest (default: AAPL MSFT NVDA)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Bypass the ledger and reprocess all filings even if already ingested",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    summary = asyncio.run(run_ingestion(args.tickers, force_refresh=args.force_refresh))
    print("Ingestion summary (new chunks written this run):", summary)
