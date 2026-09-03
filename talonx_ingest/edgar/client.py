"""
talonx_ingest.edgar.client
---------------------------
Async SEC EDGAR client.

Responsibilities:
  - Resolve ticker -> CIK via the official company_tickers.json map.
  - Pull a company's filing history (submissions JSON) and filter to
    target forms (10-K / 10-Q) within a lookback window.
  - Fetch the primary document body for each filing.
  - Respect SEC's 10 req/sec cap via a token-bucket limiter, retry
    transient failures (429/5xx/connection errors) with exponential
    backoff + jitter, and fail fast on non-retryable errors (403/404).

This module deliberately does NOT parse/clean the document body -- that's
processing.cleaner's job. The client's contract is "give me the raw bytes
for a known URL, reliably."
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import aiohttp

from talonx_ingest.config import EdgarConfig, settings
from talonx_ingest.edgar.models import CompanyRef, FilingDocument, FilingMetadata

logger = logging.getLogger("talonx_ingest.edgar.client")


class EdgarClientError(Exception):
    """Non-retryable EDGAR client error (bad ticker, 403, 404, malformed data)."""


class _TokenBucket:
    """Simple async token-bucket rate limiter, safe under asyncio concurrency."""

    def __init__(self, rate_per_second: float, capacity: float | None = None):
        self.rate = rate_per_second
        self.capacity = capacity or rate_per_second
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


class EdgarClient:
    """
    Usage:
        async with EdgarClient() as client:
            company = await client.resolve_ticker("AAPL")
            filings = await client.get_recent_filings(company)
            docs = await client.fetch_documents(filings)
    """

    def __init__(self, config: EdgarConfig | None = None):
        self.config = config or settings.edgar
        self._session: aiohttp.ClientSession | None = None
        self._bucket = _TokenBucket(self.config.max_requests_per_second)
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        self._ticker_map_cache: dict[str, CompanyRef] | None = None

    async def __aenter__(self) -> "EdgarClient":
        # connect timeout separate from total: on a blocked/proxied network,
        # TCP connect can hang far longer than we want before aiohttp's
        # overall timeout kicks in -- fail fast on connect specifically.
        timeout = aiohttp.ClientTimeout(
            total=self.config.request_timeout_seconds,
            connect=min(10.0, self.config.request_timeout_seconds),
        )
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": self.config.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=timeout,
            # trust_env=True makes aiohttp honor HTTP_PROXY / HTTPS_PROXY /
            # NO_PROXY environment variables. Without this, aiohttp connects
            # directly and silently hangs on networks that require a proxy
            # for outbound internet access (common on corporate machines).
            trust_env=True,
        )
        logger.info(
            "EDGAR session opened (User-Agent=%r, trust_env=True, connect_timeout=%.0fs)",
            self.config.user_agent, timeout.connect,
        )
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Low-level request plumbing: rate limit + retry/backoff
    # ------------------------------------------------------------------

    async def _get(self, url: str, *, as_json: bool) -> Any:
        if self._session is None:
            raise RuntimeError("EdgarClient must be used as an async context manager")

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            await self._bucket.acquire()
            try:
                async with self._semaphore:
                    async with self._session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.json() if as_json else await resp.text()

                        if resp.status in (403, 404):
                            # Non-retryable: bad UA / missing resource.
                            body_preview = (await resp.text())[:200]
                            raise EdgarClientError(
                                f"GET {url} -> {resp.status}: {body_preview}"
                            )

                        if resp.status == 429 or resp.status >= 500:
                            retry_after = resp.headers.get("Retry-After")
                            wait = (
                                float(retry_after)
                                if retry_after
                                else self._backoff_delay(attempt)
                            )
                            logger.warning(
                                "EDGAR %s on %s (attempt %d/%d); retrying in %.1fs",
                                resp.status, url, attempt, self.config.max_retries, wait,
                            )
                            await asyncio.sleep(wait)
                            continue

                        # Unexpected status: treat as non-retryable.
                        raise EdgarClientError(f"GET {url} -> unexpected {resp.status}")

            except EdgarClientError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                wait = self._backoff_delay(attempt)
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s; retrying in %.1fs",
                    url, attempt, self.config.max_retries, exc, wait,
                )
                await asyncio.sleep(wait)

        raise EdgarClientError(
            f"Exhausted {self.config.max_retries} retries for {url}"
        ) from last_exc

    def _backoff_delay(self, attempt: int) -> float:
        base = self.config.backoff_base_seconds * (2 ** (attempt - 1))
        capped = min(base, self.config.backoff_max_seconds)
        return capped * (0.5 + random.random())  # full jitter in [0.5x, 1.5x]

    # ------------------------------------------------------------------
    # Ticker -> CIK resolution
    # ------------------------------------------------------------------

    async def _load_ticker_map(self) -> dict[str, CompanyRef]:
        if self._ticker_map_cache is not None:
            return self._ticker_map_cache

        data = await self._get(self.config.ticker_map_url, as_json=True)
        mapping: dict[str, CompanyRef] = {}
        for entry in data.values():
            ticker = entry["ticker"].upper()
            cik = str(entry["cik_str"]).zfill(10)
            mapping[ticker] = CompanyRef(ticker=ticker, cik=cik, name=entry["title"])

        self._ticker_map_cache = mapping
        return mapping

    async def resolve_ticker(self, ticker: str) -> CompanyRef:
        mapping = await self._load_ticker_map()
        company = mapping.get(ticker.upper())
        if company is None:
            raise EdgarClientError(f"Ticker '{ticker}' not found in SEC ticker map")
        return company

    # ------------------------------------------------------------------
    # Filing discovery
    # ------------------------------------------------------------------

    async def get_recent_filings(
        self, company: CompanyRef, forms: tuple[str, ...] | None = None,
    ) -> list[FilingMetadata]:
        """Fetch the submissions feed and filter to target forms/lookback
        window. `forms` overrides self.config.target_forms for just this
        call -- e.g. the Earnings Radar's fast-track poller passing
        `("8-K", "10-Q")` without touching the GLOBAL target_forms (which
        stays 10-K/10-Q only, so the regular periodic ingestion loop
        doesn't start pulling every unrelated 8-K for every ticker)."""
        target_forms = forms if forms is not None else self.config.target_forms
        url = f"{self.config.submissions_base}/CIK{company.cik}.json"
        data = await self._get(url, as_json=True)

        recent = data.get("filings", {}).get("recent", {})
        forms_list = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])
        primary_descs = recent.get("primaryDocDescription", [])

        counts: dict[str, int] = {form: 0 for form in target_forms}
        results: list[FilingMetadata] = []

        for i, form in enumerate(forms_list):
            if form not in target_forms:
                continue
            if counts[form] >= self.config.lookback_filings_per_form:
                continue
            counts[form] += 1

            results.append(
                FilingMetadata(
                    company=company,
                    accession_number=accession_numbers[i],
                    form_type=form,
                    filing_date=_parse_date(filing_dates[i]),
                    report_date=_parse_date(report_dates[i]) if report_dates[i] else None,
                    primary_document=primary_docs[i],
                    primary_doc_description=(
                        primary_descs[i] if i < len(primary_descs) else ""
                    ),
                )
            )

        results.sort(key=lambda f: f.filing_date, reverse=True)
        logger.info(
            "Resolved %d target filings for %s (%s)",
            len(results), company.ticker, company.cik,
        )
        return results

    # ------------------------------------------------------------------
    # Structured financials (Phase 2 LONG_TERM path) -- XBRL company facts
    # ------------------------------------------------------------------

    async def get_company_facts(self, company: CompanyRef) -> dict[str, Any]:
        """Fetches the FULL XBRL "company facts" JSON for a company --
        every concept it has ever tagged, across every filing. Raw dict,
        unparsed -- see edgar/financials.py's parse_company_facts for
        turning this into structured FinancialStatementFacts rows. Reuses
        self._get() for the exact same auth/rate-limit/retry/error
        handling as every other EDGAR endpoint this client talks to;
        `company_facts_base` was already defined in EdgarConfig before
        this method existed, just never called."""
        url = f"{self.config.company_facts_base}/CIK{company.cik}.json"
        return await self._get(url, as_json=True)

    # ------------------------------------------------------------------
    # Raw passthroughs for the event-intelligence layer
    # (talonx_ingest.intelligence.edgar_normalize). These return the
    # UNPARSED SEC JSON; normalization/classification lives entirely in
    # that package. Kept here only so every SEC call shares this client's
    # one auth/rate-limit/retry/backoff path -- no new transport.
    # ------------------------------------------------------------------

    async def get_submissions(self, company: CompanyRef | str) -> dict[str, Any]:
        """Raw `data.sec.gov/submissions/CIK##########.json` document.

        Unlike `get_recent_filings` (which filters to target forms and
        drops `acceptanceDateTime`/`items`), this returns the whole feed
        so the event layer can read every field it needs, including the
        causal `acceptanceDateTime` and 8-K `items` arrays. Accepts a
        `CompanyRef` or a bare CIK string/int."""
        cik = (
            company.cik
            if isinstance(company, CompanyRef)
            else str(company).lstrip("CIK").zfill(10)
        )
        url = f"{self.config.submissions_base}/CIK{cik}.json"
        return await self._get(url, as_json=True)

    async def fetch_filing_index(self, cik: str | int, accession: str) -> dict[str, Any]:
        """Raw accession `index.json` -- the `directory.item` list of every
        document in a filing (primary doc + exhibits). Used to populate a
        filing's exhibit references."""
        cik_int = int(str(cik).lstrip("CIK"))
        acc_nodash = accession.replace("-", "")
        url = f"{self.config.archives_base}/{cik_int}/{acc_nodash}/index.json"
        return await self._get(url, as_json=True)

    # ------------------------------------------------------------------
    # Document fetch
    # ------------------------------------------------------------------

    async def fetch_documents(
        self, filings: list[FilingMetadata]
    ) -> list[FilingDocument]:
        """Fetch raw HTML for each filing concurrently (bounded by semaphore)."""

        async def _fetch_one(meta: FilingMetadata) -> FilingDocument:
            url = meta.primary_document_url(self.config.archives_base)
            try:
                raw_html = await self._get(url, as_json=False)
                return FilingDocument(metadata=meta, raw_html=raw_html)
            except EdgarClientError as exc:
                logger.error("Failed to fetch %s: %s", url, exc)
                return FilingDocument(metadata=meta, fetch_error=str(exc))

        return await asyncio.gather(*(_fetch_one(m) for m in filings))


def _parse_date(value: str):
    from datetime import date as _date
    return _date.fromisoformat(value)
