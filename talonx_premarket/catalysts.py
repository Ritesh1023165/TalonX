"""
Causal SEC catalyst evidence for pre-market candidates.

Sources (free, already used by TalonX):
* SEC submissions JSON per CIK (``data.sec.gov/submissions/CIK##########.json``) -- fetched only
  for gap candidates (bounded), cached per scan cycle.
* TalonX insider ledger (``insider_transactions``, read-only URI) -- code-P open-market purchases
  for the symbols TalonX already ingests.

Causality: a filing counts only if its filing date is the previous session or the scan day AND
its true acceptance instant is <= the scan's decision time. Acceptance comes from
``talonx_ingest.intelligence.sec_time.resolve_acceptance`` (SEC serves fresh filings as ET wall
clock labelled Z). A same-day filing whose acceptance cannot be resolved is EXCLUDED in replay
(conservative) -- in live mode its presence in the feed at decision time proves availability.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from talonx_ingest.intelligence.sec_time import resolve_acceptance

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
STRONG_FORMS = {"8-K", "8-K/A", "6-K", "S-1", "S-1/A", "S-3", "F-1", "F-3", "424B1", "424B2", "424B3",
                "424B4", "424B5", "SC 13D", "SC 13D/A", "425", "DEFM14A", "SC TO-T", "SC 14D9"}


@dataclass(frozen=True)
class Filing:
    form: str
    accession: str
    filing_date: date
    accepted_utc: datetime | None
    acceptance_basis: str
    items: str = ""


@dataclass
class CatalystEvidence:
    strength: str = "NONE"             # STRONG | OTHER | NONE
    labels: list[str] = field(default_factory=list)
    filings: list[Filing] = field(default_factory=list)
    excluded_unverified: int = 0

    def summary(self) -> str:
        return "; ".join(self.labels) if self.labels else "none found"


def _label(f: Filing) -> str:
    if f.form.startswith("8-K") and "2.02" in f.items:
        return f"8-K earnings (item 2.02) filed {f.filing_date}"
    if f.form.startswith("8-K"):
        return f"8-K items {f.items or '?'} filed {f.filing_date}"
    if f.form.startswith("424B") or f.form.startswith(("S-1", "S-3", "F-1", "F-3")):
        return f"offering-related {f.form} filed {f.filing_date}"
    return f"{f.form} filed {f.filing_date}"


def parse_submissions(subs: dict, *, observed_at: datetime) -> list[Filing]:
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form", [])
    out: list[Filing] = []
    for i, form in enumerate(forms):
        try:
            fd = date.fromisoformat(rec["filingDate"][i])
        except (KeyError, IndexError, ValueError):
            continue
        raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
        raw_dt = None
        if raw:
            try:
                raw_dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                raw_dt = None
        res = resolve_acceptance(raw_dt, observed_at=observed_at, filing_date=fd)
        items = rec.get("items", [""] * len(forms))[i] if i < len(rec.get("items", [])) else ""
        out.append(Filing(str(form), rec["accessionNumber"][i], fd, res.utc, res.basis, str(items or "")))
    return out


def evaluate(filings: list[Filing], *, prev_session: date, scan_day: date, decision_utc: datetime,
             live: bool, insider_owners: int = 0, insider_label: str = "") -> CatalystEvidence:
    ev = CatalystEvidence()
    for f in filings:
        if f.filing_date < prev_session or f.filing_date > scan_day:
            continue
        if f.accepted_utc is None:
            if live or f.filing_date < scan_day:
                pass                      # visible in the feed now / accepted on a prior day
            else:
                ev.excluded_unverified += 1
                continue
        elif f.accepted_utc > decision_utc:
            continue
        ev.filings.append(f)
    strong = [f for f in ev.filings if f.form in STRONG_FORMS]
    other = [f for f in ev.filings if f.form not in STRONG_FORMS]
    ev.labels = [_label(f) for f in strong] + ([f"{len(other)} other SEC filing(s): "
                                                 + ", ".join(sorted({f.form for f in other}))] if other else [])
    if insider_owners >= 2:
        ev.labels.append(insider_label or f"{insider_owners} distinct insiders bought (open market, 30d)")
    elif insider_owners == 1:
        ev.labels.append(insider_label or "1 insider open-market purchase (30d)")
    if strong or insider_owners >= 2:
        ev.strength = "STRONG"
    elif other or insider_owners == 1:
        ev.strength = "OTHER"
    return ev


def insider_open_market_owners(ledger_path: str, symbol: str, *, scan_day: date, decision_utc: datetime,
                               lookback_days: int = 30) -> int:
    """Distinct owners with code-P purchases filed in the lookback window, causally: TalonX must have RECEIVED the
    filing by the decision time (replay-safe), and a same-day filing also needs a resolvable acceptance <= decision.
    Read-only URI connection. Returns None when the ledger cannot be read (unknown, not zero)."""
    try:
        con = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        rows = con.execute(
            "SELECT owner_cik, filing_date, accepted_at_utc, accession FROM insider_transactions "
            "WHERE symbol = ? AND transaction_code = 'P' AND filing_date >= ? AND filing_date <= ?",
            (symbol, (scan_day - timedelta(days=lookback_days)).isoformat(), scan_day.isoformat())).fetchall()
        ingested = {a: t for a, t in con.execute(
            "SELECT accession, ingested_at_utc FROM insider_filings WHERE issuer_cik IN "
            "(SELECT DISTINCT issuer_cik FROM insider_transactions WHERE symbol = ?)", (symbol,)).fetchall()}
    except sqlite3.Error:
        return None
    finally:
        con.close()
    owners = set()
    for owner, fd, acc_raw, accession in rows:
        fdd = date.fromisoformat(fd)
        obs = ingested.get(accession)
        if obs and datetime.fromisoformat(obs) > decision_utc:
            continue                                    # TalonX did not have it yet at decision time
        if fdd < scan_day:
            owners.add(owner)
            continue
        res = resolve_acceptance(datetime.fromisoformat(acc_raw) if acc_raw else None,
                                 observed_at=datetime.fromisoformat(obs) if obs else None, filing_date=fdd)
        # causal: TalonX must also have HAD it -- receipt <= decision time
        if res.utc is not None and res.utc <= decision_utc and obs and datetime.fromisoformat(obs) <= decision_utc:
            owners.add(owner)
    return len(owners)


class SecSubmissions:
    """Bounded SEC fetcher (<= ~5 req/s, declared User-Agent). Cache TTL applies in live mode."""

    def __init__(self, *, user_agent: str, http_get: Callable[[str, dict], dict] | None = None,
                 ttl_s: float = 600.0, clock: Callable[[], float] = time.monotonic):
        self._ua = user_agent
        self._get = http_get or self._default_get
        self.ttl_s, self.clock = ttl_s, clock
        self._cache: dict[str, tuple[float, dict, datetime]] = {}
        self._last = 0.0
        self.requests = 0
        self.errors: list[str] = []
        self.backoff_s = 60.0
        self._backoff_until = 0.0
        self.throttled = 0          # lookups skipped while backing off after a 429

    def _default_get(self, url: str, headers: dict) -> dict:  # pragma: no cover - network
        wait = 0.21 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return json.loads(r.read())

    def get(self, cik: str) -> tuple[dict | None, datetime | None]:
        """(submissions, observed_at) or (None, None) when the lookup could not complete (-> CATALYST UNKNOWN).
        A stale cached copy is preferred over no data if a refresh fails. After a 429 all lookups pause for
        ``backoff_s`` (fair access) instead of hammering SEC."""
        hit = self._cache.get(cik)
        if hit and self.clock() - hit[0] < self.ttl_s:
            return hit[1], hit[2]
        if self.clock() < self._backoff_until:
            self.throttled += 1
            return (hit[1], hit[2]) if hit else (None, None)
        try:
            self.requests += 1
            j = self._get(SUBMISSIONS_URL.format(cik=str(cik).zfill(10)),
                          {"User-Agent": self._ua, "Accept-Encoding": "identity"})
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{cik}: {type(exc).__name__}: {str(exc)[:80]}")
            if "429" in str(exc):
                self._backoff_until = self.clock() + self.backoff_s
            return (hit[1], hit[2]) if hit else (None, None)
        observed = datetime.now(timezone.utc)
        self._cache[cik] = (self.clock(), j, observed)
        return j, observed
