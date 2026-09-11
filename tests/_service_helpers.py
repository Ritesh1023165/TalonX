"""
tests/_service_helpers.py
-------------------------
Shared offline fixtures for the Task 96B ingestion-service tests. No
network: a ``FakeEdgarClient`` serves canned submissions / documents /
filing indexes / XBRL from in-memory dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# a minimal but real-shaped Form 4 <ownershipDocument>
# ---------------------------------------------------------------------------
FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2026-06-10</periodOfReport>
  <issuer>
    <issuerCik>0000012345</issuerCik>
    <issuerName>Fake Industries Inc.</issuerName>
    <issuerTradingSymbol>FAKE</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Financial Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-10</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
        <equitySwapInvolved>0</equitySwapInvolved>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>50.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_TENQ_HTML_A = (
    "<html><body>"
    "<h2>Item 1A. Risk Factors</h2>"
    "<p>" + ("our business faces competition and regulation. " * 40) + "</p>"
    "<h2>Item 2. Management's Discussion and Analysis</h2>"
    "<p>" + ("revenue was flat and liquidity is adequate. " * 40) + "</p>"
    "<h2>Liquidity and Capital Resources</h2>"
    "<p>" + ("cash on hand supports operations. " * 30) + "</p>"
    "</body></html>"
)
_TENQ_HTML_B = _TENQ_HTML_A.replace("competition and regulation", "material litigation risk and default")


def _company_tickers() -> dict:
    return {
        "0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."},
        "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "2": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }


def make_submissions(
    *,
    cik: int = 12345,
    name: str = "Fake Industries Inc.",
    ticker: str = "FAKE",
    rows: list[dict] | None = None,
) -> dict:
    """`rows` = list of {form, accn, accepted, filed, report, primary, items}."""
    rows = rows or default_rows()
    recent = {
        "form": [r["form"] for r in rows],
        "accessionNumber": [r["accn"] for r in rows],
        "acceptanceDateTime": [r.get("accepted", "") for r in rows],
        "filingDate": [r.get("filed", "") for r in rows],
        "reportDate": [r.get("report", "") for r in rows],
        "primaryDocument": [r.get("primary", "d.htm") for r in rows],
        "items": [r.get("items", "") for r in rows],
        "primaryDocDescription": [r.get("desc", "") for r in rows],
    }
    return {
        "cik": cik,
        "name": name,
        "tickers": [ticker],
        "filings": {"recent": recent, "files": []},
    }


def default_rows() -> list[dict]:
    return [
        {"form": "8-K", "accn": "0000012345-26-000010",
         "accepted": "2026-06-12T20:30:00.000Z", "filed": "2026-06-12",
         "primary": "8k.htm", "items": "2.02,9.01"},
        {"form": "10-Q", "accn": "0000012345-26-000009",
         "accepted": "2026-06-11T11:00:00.000Z", "filed": "2026-06-11",
         "report": "2026-03-31", "primary": "10q.htm", "items": ""},
        {"form": "10-Q", "accn": "0000012345-26-000004",
         "accepted": "2026-03-05T11:00:00.000Z", "filed": "2026-03-05",
         "report": "2025-12-31", "primary": "10q_prior.htm", "items": ""},
        {"form": "4", "accn": "0000012345-26-000008",
         "accepted": "2026-06-11T13:00:00.000Z", "filed": "2026-06-11",
         "primary": "xslF345X05/form4.xml"},
    ]


@dataclass
class _Cfg:
    ticker_map_url: str = "https://www.sec.gov/files/company_tickers.json"
    max_requests_per_second: float = 8.0
    max_concurrent_requests: int = 4


@dataclass
class FakeEdgarClient:
    """Async, offline. Records every call for assertions."""

    submissions: dict = field(default_factory=dict)     # cik(str/int) -> submissions dict
    documents: dict = field(default_factory=dict)       # url -> text
    indexes: dict = field(default_factory=dict)         # (cik, accession) -> index json
    concepts: dict = field(default_factory=dict)        # (cik, tax, concept) -> json | None
    company_tickers: dict = field(default_factory=_company_tickers)
    fail_submissions_for: set = field(default_factory=set)   # ciks that raise
    raise_text: str = "HTTP 429 Too Many Requests"
    calls: list = field(default_factory=list)

    config: _Cfg = field(default_factory=_Cfg)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_document(self, url: str) -> str:
        self.calls.append(("fetch_document", url))
        if url == self.config.ticker_map_url:
            import json

            return json.dumps(self.company_tickers)
        if url in self.documents:
            return self.documents[url]
        # default: a 10-Q-ish body for any archives html, the form4 xml for .xml
        if url.endswith(".xml"):
            return FORM4_XML
        return _TENQ_HTML_A

    async def get_submissions(self, company) -> dict:
        cik = (
            company
            if isinstance(company, str)
            else getattr(company, "cik", str(company))
        )
        cik = str(cik).lstrip("CIK").zfill(10)
        self.calls.append(("get_submissions", cik))
        if int(cik) in self.fail_submissions_for or cik in self.fail_submissions_for:
            raise RuntimeError(self.raise_text)
        for key, val in self.submissions.items():
            if str(key).lstrip("CIK").zfill(10) == cik:
                return val
        raise RuntimeError(f"no canned submissions for {cik}")

    async def fetch_filing_index(self, cik, accession) -> dict:
        self.calls.append(("fetch_filing_index", str(cik), accession))
        key = (str(int(str(cik).lstrip("CIK"))), accession)
        if key in self.indexes:
            return self.indexes[key]
        return {
            "directory": {
                "item": [
                    {"name": "form4.xml", "type": "4", "size": "3000"},
                    {"name": f"{accession}-index.htm", "type": "index", "size": "1000"},
                ]
            }
        }

    async def get_company_concept(self, cik, taxonomy, concept) -> dict:
        self.calls.append(("get_company_concept", str(cik), taxonomy, concept))
        return self.concepts.get((str(cik), taxonomy, concept), {"units": {}})


class FakeWatchlistStore:
    """Just enough of TickerWatchlistStore for watchlist_source."""

    def __init__(self, rows: list[dict], path: str = "<fake>"):
        self._rows = rows
        self.path = path

    def list_tickers(self) -> list[dict]:
        return [dict(r) for r in self._rows]

    def list_symbols(self) -> list[str]:
        return [r["symbol"] for r in self._rows]

    def list_active_symbols(self) -> list[str]:
        return [r["symbol"] for r in self._rows if r.get("status", "active") == "active"]

    def close(self) -> None:
        pass


def wl_row(symbol: str, *, status: str = "active", name: str | None = None) -> dict:
    return {"symbol": symbol, "name": name or symbol, "exchange": "NASDAQ",
            "status": status, "strategy_horizon": "DUAL_HORIZON", "added_at": "2026-01-01T00:00:00Z"}
