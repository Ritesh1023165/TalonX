"""
talonx_v2.corporate_actions -- PQ-2A: corporate-action safety & accounting
========================================================================
Closes the PQ-1 finding that a split during a hold was booked as a trading
loss (10 sh @ $100 -> 10:1 split -> exit @ ~$11 was "-89%").

ROOT CAUSE (see docs/research/evidence/provider_qualification_pq2a/):
entry price / shares / cost are persisted on the price basis the provider
served *at entry time*; the exit close is served on the (post-split) basis
*at exit time*; shares and cost were never re-expressed, so
``shares * exit_price - position_cost`` compared two different bases.

CONTRACT (first release, deterministic, machine-tested):

* Split evidence is an EXPLICIT provider event (id, ex-date, ratio), never
  inferred from a price move.
* Pure split: ``economic_shares = entry_shares * R`` (``R = new/old``, exact
  ``Fraction``); AGGREGATE cost basis is unchanged; the original entry row is
  never rewritten -- an append-only ``position_corporate_actions`` trail is.
* Adjustment is applied iff the entry price was served on a basis that
  predates the split (``entry_basis_as_of < ex_date``); ``ex_date <
  entry_basis_as_of`` => already reflected (recorded, no share change);
  ``ex_date == entry_basis_as_of`` or an unknown basis => fail closed.  A split
  after the exit fill session additionally needs an exit basis strictly later
  than its ex_date (else HOLD/fail closed).
* Application is idempotent: keyed ``(position_id, action_key)`` where
  ``action_key`` is content-derived (symbol, ex-date, ratio) so a restart, a
  replay or a duplicate provider event (different provider id) applies once.
* Reverse-split fractional entitlement is retained EXACTLY (no rounding, no
  invented cash-in-lieu); see DECISION_LOG S5-26 / PQ-2A evidence.
* Ordinary cash dividends are TOTAL-RETURN accounted (PQ-2A closure): explicit
  provider event; entitled iff ``entry_session < ex_date <= exit_fill_session``;
  quantity = economic shares AT the ex-date (split trail); recorded atomically
  with settlement as an ACCRUED receivable and CREDITED to cash on/after the
  payable date after a fresh provider re-confirmation (``talonx_v2.dividends``).
  Price fills must be on a dividend-UNADJUSTED basis (RAW/SPLIT_ADJUSTED) or the
  position fails closed -- one coherent model, no double count.  Special,
  foreign, malformed, zero/negative/NaN dividends are unsupported => fail closed.
* Unsupported action types, conflicting evidence, unavailable evidence and
  unknown basis NEVER produce a fabricated settlement: they hold (transient)
  or move the position to the existing ``EXIT_UNRESOLVED`` state (deterministic).

No network is performed at import; the Alpaca source is read-only market-data
(``/v1/corporate-actions``) and never touches a broker/order endpoint.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Protocol, Sequence

logger = logging.getLogger(__name__)

# ---- event kinds -----------------------------------------------------------
KIND_FORWARD_SPLIT = "FORWARD_SPLIT"
KIND_REVERSE_SPLIT = "REVERSE_SPLIT"
KIND_CASH_DIVIDEND = "CASH_DIVIDEND"
KIND_UNSUPPORTED = "UNSUPPORTED"
SPLIT_KINDS = frozenset({KIND_FORWARD_SPLIT, KIND_REVERSE_SPLIT})

# ---- trail statuses --------------------------------------------------------
TRAIL_APPLIED = "APPLIED"
TRAIL_REFLECTED = "REFLECTED_IN_ENTRY_BASIS"
TRAIL_DIVIDEND_OBSERVED = "DIVIDEND_OBSERVED"
TRAIL_BLOCKED_PREFIX = "BLOCKED_"
ECONOMIC_TRAIL_STATUSES = frozenset({TRAIL_APPLIED})

# ---- verdict statuses ------------------------------------------------------
V_CLEAR = "CLEAR"            # no relevant action; settle on persisted economics
V_ADJUSTED = "ADJUSTED"      # >=1 split applied/verified; settle on economic shares
V_HOLD = "HOLD"              # transient (evidence unavailable / stale exit basis): retry inside window
V_BLOCK = "BLOCK"            # deterministic: EXIT_UNRESOLVED

# ---- verdict codes ---------------------------------------------------------
C_EVIDENCE_UNAVAILABLE = "CA_EVIDENCE_UNAVAILABLE"
C_CONFLICT = "CA_CONFLICTING_EVIDENCE"
C_UNSUPPORTED = "CA_UNSUPPORTED_ACTION"
C_BASIS_UNKNOWN = "CA_PRICE_BASIS_UNKNOWN"
C_EXIT_BASIS_STALE = "CA_EXIT_BASIS_PREDATES_SPLIT"
C_MALFORMED = "CA_MALFORMED_EVENT"
C_DIVIDEND_BASIS = "CA_DIVIDEND_PRICE_BASIS_NOT_UNADJUSTED"
C_DIVIDEND_SPLIT_SAME_DAY = "CA_DIVIDEND_SPLIT_SAME_EX_DATE"
# price-fill adjustment states that carry NO dividend adjustment (safe for explicit dividend cash)
DIVIDEND_SAFE_BASES = frozenset({"RAW", "SPLIT_ADJUSTED"})
C_BASIS_AMBIGUOUS = "CA_PRICE_BASIS_AMBIGUOUS"

DEFAULT_ALPACA_URL = "https://data.alpaca.markets/v1/corporate-actions"
_ALPACA_WIDEN_DAYS = 10          # provider filter date field is not documented -> widen, then filter ourselves
_ALPACA_MAX_PAGES = 20

# Alpaca response key -> (kind, date fields in preference order)
_ALPACA_TYPES = {
    "forward_splits": KIND_FORWARD_SPLIT,
    "reverse_splits": KIND_REVERSE_SPLIT,
    "cash_dividends": KIND_CASH_DIVIDEND,
}
_ALPACA_DATE_FIELDS = ("ex_date", "effective_date", "process_date")


def _d(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _fraction(x) -> Fraction | None:
    try:
        f = Fraction(str(x))
    except (ValueError, ZeroDivisionError, TypeError):
        return None
    return f


def fraction_to_decimal(f: Fraction) -> Decimal:
    """Exact-as-possible Decimal view (28-digit context) for settlement math."""
    return Decimal(f.numerator) / Decimal(f.denominator)


# --------------------------------------------------------------------------- #
# event model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CorporateActionEvent:
    action_key: str                    # content-derived idempotency key
    symbol: str
    kind: str
    provider_type: str
    ex_date: date | None               # effective session = first session on the new basis
    ratio: Fraction | None             # new_shares / old_shares (splits only)
    cash_rate: str | None              # dividend rate as provider string (never a float)
    source: str
    provider_id: str
    received_at_utc: str
    raw: dict = field(default_factory=dict, compare=False, hash=False)
    malformed: str | None = None
    payable_date: date | None = None       # dividends: provider payable_date (None = unknown)
    record_date: date | None = None

    def source_ref(self) -> dict:
        return {"source": self.source, "provider_id": self.provider_id,
                "received_at_utc": self.received_at_utc}


def split_key(symbol: str, ex_date: date, ratio: Fraction) -> str:
    return f"SPLIT|{symbol.upper()}|{ex_date.isoformat()}|{ratio.numerator}/{ratio.denominator}"


def classify_alpaca_record(symbol: str, provider_type: str, rec: dict, *, source: str,
                           received_at_utc: str) -> CorporateActionEvent:
    """One provider record -> one typed event.  Anything not explicitly
    supported (or malformed) becomes ``UNSUPPORTED``/``malformed`` -- never
    silently dropped, never coerced into a split."""
    sym = symbol.upper()
    pid = str(rec.get("id") or "")
    ex = None
    for f in _ALPACA_DATE_FIELDS:
        ex = _d(rec.get(f))
        if ex is not None:
            break
    kind = _ALPACA_TYPES.get(provider_type)
    base = dict(symbol=sym, provider_type=provider_type, source=source, provider_id=pid,
                received_at_utc=received_at_utc, raw=dict(rec))
    if kind is None:
        return CorporateActionEvent(action_key=f"UNSUPPORTED|{sym}|{provider_type}|{ex}|{pid}",
                                    kind=KIND_UNSUPPORTED, ex_date=ex, ratio=None, cash_rate=None, **base)
    if kind in SPLIT_KINDS:
        new, old = _fraction(rec.get("new_rate")), _fraction(rec.get("old_rate"))
        ex_split = _d(rec.get("ex_date"))          # a split's effective session is its ex_date, never process_date
        bad = None
        if ex_split is None:
            bad = "split has no ex_date"
        elif new is None or old is None or new <= 0 or old <= 0:
            bad = "split has missing/non-positive new_rate/old_rate"
        else:
            ratio = new / old
            if ratio == 1:
                bad = "split ratio == 1"
            elif (kind == KIND_FORWARD_SPLIT) != (ratio > 1):
                bad = f"{provider_type} direction disagrees with ratio {ratio}"
        if bad:
            return CorporateActionEvent(action_key=f"MALFORMED|{sym}|{provider_type}|{ex}|{pid}",
                                        kind=KIND_UNSUPPORTED, ex_date=ex, ratio=None, cash_rate=None,
                                        malformed=bad, **base)
        return CorporateActionEvent(action_key=split_key(sym, ex_split, ratio), kind=kind,
                                    ex_date=ex_split, ratio=ratio, cash_rate=None, **base)
    # CASH_DIVIDEND -- ordinary cash only.  Anything the provider flags special/foreign, or
    # with a non-finite / non-positive amount, is UNSUPPORTED (fail closed), never coerced.
    rate = rec.get("rate")
    ex_div = _d(rec.get("ex_date"))
    r = _fraction(rate)
    bad = None
    if ex_div is None:
        bad = "dividend has no ex_date"
    elif r is None or r <= 0:
        bad = f"dividend rate missing/non-finite/non-positive ({rate!r})"
    elif rec.get("special"):
        bad = "special dividend (unsupported)"
    elif rec.get("foreign"):
        bad = "foreign dividend (unsupported: withholding/FX not modelled)"
    if bad:
        return CorporateActionEvent(action_key=f"MALFORMED|{sym}|{provider_type}|{ex}|{pid}",
                                    kind=KIND_UNSUPPORTED, ex_date=ex, ratio=None, cash_rate=None,
                                    malformed=bad, **base)
    rate_s = format(Decimal(str(rate)).normalize(), "f")
    return CorporateActionEvent(action_key=f"DIV|{sym}|{ex_div.isoformat()}|{rate_s}", kind=kind,
                                ex_date=ex_div, ratio=None, cash_rate=rate_s,
                                payable_date=_d(rec.get("payable_date")),
                                record_date=_d(rec.get("record_date")), **base)


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CASourceResult:
    source: str
    status: str                                   # OK | UNAVAILABLE
    events: tuple[CorporateActionEvent, ...] = ()
    detail: str = ""
    conflicts: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "OK"


class CorporateActionSource(Protocol):
    name: str

    def fetch(self, symbol: str, start: date, end: date) -> CASourceResult:
        """Events for ``symbol`` whose effective date could fall in ``[start, end]``."""


class AlpacaCorporateActionSource:
    """Alpaca Market Data ``/v1/corporate-actions`` (READ-ONLY, market-data
    credentials only; no broker/order endpoint).  Every provider record
    carries a stable id, ex-date and old/new rate; splits, dividends, mergers,
    spin-offs, name changes etc. are all returned so unsupported classes are
    SEEN (and blocked), not silently missing."""
    name = "alpaca:v1/corporate-actions"

    def __init__(self, *, key_id: str | None = None, secret: str | None = None,
                 http_get: Callable[[str, dict], dict] | None = None,
                 now: Callable[[], datetime] | None = None):
        self._kid = key_id or os.environ.get("APCA_API_KEY_ID", "")
        self._sec = secret or os.environ.get("APCA_API_SECRET_KEY", "")
        self._get = http_get or self._default_get
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _default_get(self, url: str, params: dict) -> dict:  # pragma: no cover - network
        import urllib.parse
        import urllib.request
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}",
            headers={"APCA-API-KEY-ID": self._kid, "APCA-API-SECRET-KEY": self._sec})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)

    def fetch(self, symbol: str, start: date, end: date) -> CASourceResult:
        sym = symbol.upper()
        received = self._now().isoformat()
        events: list[CorporateActionEvent] = []
        token = None
        try:
            for _ in range(_ALPACA_MAX_PAGES):
                params = {"symbols": sym, "limit": "1000",
                          "start": (start - timedelta(days=_ALPACA_WIDEN_DAYS)).isoformat(),
                          "end": (end + timedelta(days=_ALPACA_WIDEN_DAYS)).isoformat()}
                if token:
                    params["page_token"] = token
                body = self._get(DEFAULT_ALPACA_URL, params)
                ca = body.get("corporate_actions") if isinstance(body, dict) else None
                if not isinstance(ca, dict):
                    return CASourceResult(self.name, "UNAVAILABLE", detail="unexpected response shape")
                for ptype, recs in ca.items():
                    for rec in recs or []:
                        if isinstance(rec, dict):
                            events.append(classify_alpaca_record(sym, ptype, rec, source=self.name,
                                                                 received_at_utc=received))
                token = body.get("next_page_token")
                if not token:
                    break
            else:
                return CASourceResult(self.name, "UNAVAILABLE", detail="pagination bound exceeded")
        except Exception as exc:  # noqa: BLE001 -- any provider fault is UNAVAILABLE, never "no actions"
            return CASourceResult(self.name, "UNAVAILABLE", detail=f"{type(exc).__name__}: {exc}"[:200])
        return _finalize(self.name, events)


class YFinanceCorporateActionSource:
    """OPTIONAL independent SPLIT witness (``Ticker.splits``).  No provider id,
    float ratios: usable only to cross-check, never as the sole authority.  NOT
    wired by default.  Dividends are deliberately NOT read: yfinance dividend
    amounts are split-normalised to today's share basis (NVDA 2024-03-05 = 0.004
    vs the raw 0.04 per share actually paid), so they cannot be compared to, or
    used instead of, the provider's per-share-as-of-ex-date rate."""
    name = "yfinance:actions"

    def __init__(self, *, ticker_factory: Callable[[str], object] | None = None,
                 now: Callable[[], datetime] | None = None):
        self._tf = ticker_factory
        self._now = now or (lambda: datetime.now(timezone.utc))

    def fetch(self, symbol: str, start: date, end: date) -> CASourceResult:
        sym = symbol.upper()
        received = self._now().isoformat()
        try:
            if self._tf is not None:
                tk = self._tf(sym)
            else:  # pragma: no cover - network
                import yfinance as yf
                tk = yf.Ticker(sym)
            splits = tk.splits
            events: list[CorporateActionEvent] = []
            for idx, val in (splits.items() if splits is not None else []):
                ex = _d(str(idx)[:10])
                if ex is None or not (start <= ex <= end):
                    continue
                ratio = Fraction(float(val)).limit_denominator(10_000)
                if ratio <= 0 or ratio == 1:
                    events.append(CorporateActionEvent(
                        action_key=f"MALFORMED|{sym}|yf_split|{ex}|", symbol=sym, kind=KIND_UNSUPPORTED,
                        provider_type="yf_split", ex_date=ex, ratio=None, cash_rate=None, source=self.name,
                        provider_id="", received_at_utc=received, raw={"value": float(val)},
                        malformed="yfinance split ratio invalid"))
                    continue
                kind = KIND_FORWARD_SPLIT if ratio > 1 else KIND_REVERSE_SPLIT
                events.append(CorporateActionEvent(
                    action_key=split_key(sym, ex, ratio), symbol=sym, kind=kind, provider_type="yf_split",
                    ex_date=ex, ratio=ratio, cash_rate=None, source=self.name, provider_id="",
                    received_at_utc=received, raw={"value": float(val)}))
        except Exception as exc:  # noqa: BLE001
            return CASourceResult(self.name, "UNAVAILABLE", detail=f"{type(exc).__name__}: {exc}"[:200])
        return _finalize(self.name, events)


class StaticCorporateActionSource:
    """Deterministic fixture/replay source (also the way a caller with an
    audited, offline event list runs the guard).  ``status='UNAVAILABLE'``
    models an outage."""
    def __init__(self, events: Sequence[CorporateActionEvent] = (), *, name: str = "static",
                 status: str = "OK", detail: str = ""):
        self.name, self._events, self._status, self._detail = name, tuple(events), status, detail

    def fetch(self, symbol: str, start: date, end: date) -> CASourceResult:
        if self._status != "OK":
            return CASourceResult(self.name, self._status, detail=self._detail or "static outage")
        # stamp THIS source's name so combined evidence keeps per-source provenance
        return _finalize(self.name, [CorporateActionEvent(**{**e.__dict__, "source": self.name})
                                     for e in self._events if e.symbol.upper() == symbol.upper()])


def make_split_event(symbol: str, ex_date: date, new_rate, old_rate, *, source: str = "static",
                     provider_id: str = "", received_at_utc: str | None = None) -> CorporateActionEvent:
    """Test/fixture helper: a well-formed split event (direction inferred from the ratio)."""
    ratio = Fraction(str(new_rate)) / Fraction(str(old_rate))
    return CorporateActionEvent(
        action_key=split_key(symbol, ex_date, ratio), symbol=symbol.upper(),
        kind=KIND_FORWARD_SPLIT if ratio > 1 else KIND_REVERSE_SPLIT,
        provider_type="forward_splits" if ratio > 1 else "reverse_splits", ex_date=ex_date, ratio=ratio,
        cash_rate=None, source=source, provider_id=provider_id or f"{symbol}-{ex_date}",
        received_at_utc=received_at_utc or datetime.now(timezone.utc).isoformat(),
        raw={"new_rate": str(new_rate), "old_rate": str(old_rate), "ex_date": ex_date.isoformat()})


def make_dividend_event(symbol: str, ex_date: date, rate: str, *, source: str = "static",
                        provider_id: str = "", payable_date: date | None = None,
                        record_date: date | None = None) -> CorporateActionEvent:
    rate_s = format(Decimal(str(rate)).normalize(), "f")
    return CorporateActionEvent(
        action_key=f"DIV|{symbol.upper()}|{ex_date.isoformat()}|{rate_s}", symbol=symbol.upper(),
        kind=KIND_CASH_DIVIDEND, provider_type="cash_dividends", ex_date=ex_date, ratio=None,
        cash_rate=rate_s, source=source, provider_id=provider_id or f"div-{symbol}-{ex_date}",
        received_at_utc=datetime.now(timezone.utc).isoformat(),
        raw={"rate": rate_s, "payable_date": payable_date.isoformat() if payable_date else None},
        payable_date=payable_date, record_date=record_date)


def make_unsupported_event(symbol: str, effective: date, provider_type: str = "spin_offs", *,
                           source: str = "static", provider_id: str = "") -> CorporateActionEvent:
    return CorporateActionEvent(
        action_key=f"UNSUPPORTED|{symbol.upper()}|{provider_type}|{effective}|{provider_id}",
        symbol=symbol.upper(), kind=KIND_UNSUPPORTED, provider_type=provider_type, ex_date=effective,
        ratio=None, cash_rate=None, source=source, provider_id=provider_id,
        received_at_utc=datetime.now(timezone.utc).isoformat(), raw={})


def _finalize(source: str, events: list[CorporateActionEvent]) -> CASourceResult:
    """Dedupe by content key (a provider re-listing the same split under a new
    id is ONE action) and flag same-(symbol, ex_date) splits with different
    ratios as CONFLICTS."""
    by_key: dict[str, CorporateActionEvent] = {}
    for e in events:
        by_key.setdefault(e.action_key, e)
    uniq = sorted(by_key.values(), key=lambda e: (e.ex_date or date.min, e.action_key))
    conflicts: list[str] = []
    seen: dict[tuple[str, date], set[Fraction]] = {}
    for e in uniq:
        if e.kind in SPLIT_KINDS and e.ex_date is not None:
            seen.setdefault((e.symbol, e.ex_date), set()).add(e.ratio)
    for (sym, ex), ratios in sorted(seen.items()):
        if len(ratios) > 1:
            conflicts.append(f"CONFLICT|{sym}|{ex.isoformat()}|" +
                             ",".join(sorted(f"{r.numerator}/{r.denominator}" for r in ratios)))
    # two ordinary dividends on the same (symbol, ex_date) with different amounts: a provider
    # correction re-listed under a new id (or an undeclared special) -- never credit both.
    divs: dict[tuple[str, date], set[str]] = {}
    for e in uniq:
        if e.kind == KIND_CASH_DIVIDEND and e.ex_date is not None:
            divs.setdefault((e.symbol, e.ex_date), set()).add(e.cash_rate)
    for (sym, ex), rates in sorted(divs.items()):
        if len(rates) > 1:
            conflicts.append(f"CONFLICT|{sym}|{ex.isoformat()}|dividend_rates:" + ",".join(sorted(rates)))
    return CASourceResult(source, "OK", tuple(uniq), conflicts=tuple(conflicts))


def combine_sources(results: Sequence[CASourceResult]) -> CASourceResult:
    """Merge N source results.  Any UNAVAILABLE source => UNAVAILABLE (a witness
    that cannot answer must not be treated as agreeing).  Splits/unsupported
    events present in one OK source but absent in another => CONFLICT."""
    if not results:
        return CASourceResult("none", "UNAVAILABLE", detail="no corporate-action source configured")
    names = "+".join(r.source for r in results)
    down = [r for r in results if not r.ok]
    if down:
        return CASourceResult(names, "UNAVAILABLE",
                              detail="; ".join(f"{r.source}: {r.detail}" for r in down))
    conflicts = [c for r in results for c in r.conflicts]
    merged: dict[str, CorporateActionEvent] = {}
    refs: dict[str, list[dict]] = {}
    for r in results:
        for e in r.events:
            merged.setdefault(e.action_key, e)
            refs.setdefault(e.action_key, []).append(e.source_ref())
    if len(results) > 1:
        for key, e in merged.items():
            if e.kind in SPLIT_KINDS:
                present = {r.source for r in results if any(x.action_key == key for x in r.events)}
                if len(present) != len(results):
                    conflicts.append(f"CONFLICT|{e.symbol}|{e.ex_date}|split_presence:{key}|"
                                     f"missing_in:{sorted({r.source for r in results} - present)}")
    events = tuple(sorted(merged.values(), key=lambda e: (e.ex_date or date.min, e.action_key)))
    # carry every corroborating source ref on the surviving event
    out = tuple(_with_refs(e, refs[e.action_key]) for e in events)
    return CASourceResult(names, "OK", out, conflicts=tuple(dict.fromkeys(conflicts)))


def _with_refs(e: CorporateActionEvent, refs: list[dict]) -> CorporateActionEvent:
    raw = dict(e.raw)
    raw["_source_refs"] = refs
    return CorporateActionEvent(**{**e.__dict__, "raw": raw})


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Verdict:
    status: str
    code: str = ""
    detail: str = ""
    applied: tuple[str, ...] = ()
    effective_shares: Fraction | None = None
    dividends: tuple = ()                  # ELIGIBLE ordinary dividends to accrue at settlement

    @property
    def settle_ok(self) -> bool:
        return self.status in (V_CLEAR, V_ADJUSTED)

    def text(self) -> str:
        return f"{self.code}: {self.detail}" if self.code else self.status


def _parse_basis(provenance) -> date | None:
    """``basis_as_of`` from a persisted price-provenance JSON (or dict)."""
    if provenance is None:
        return None
    try:
        p = json.loads(provenance) if isinstance(provenance, str) else provenance
    except (TypeError, ValueError):
        return None
    return _d(p.get("basis_as_of")) if isinstance(p, dict) else None


def _parse_adjustment_state(provenance) -> str | None:
    if provenance is None:
        return None
    try:
        p = json.loads(provenance) if isinstance(provenance, str) else provenance
    except (TypeError, ValueError):
        return None
    v = p.get("adjustment_state") if isinstance(p, dict) else None
    return str(v) if v else None


# --------------------------------------------------------------------------- #
# guard
# --------------------------------------------------------------------------- #
class CorporateActionGuard:
    """Evidence + accounting for one V2 ledger.  ``assess_position`` is the
    ONLY writer of the corporate-action trail.  Network I/O (``source.fetch``)
    happens BEFORE any write transaction is opened."""

    def __init__(self, sources: CorporateActionSource | Sequence[CorporateActionSource], *,
                 cache_ttl_s: float = 900.0, clock: Callable[[], float] | None = None):
        import time as _time
        self.sources: list[CorporateActionSource] = (
            list(sources) if isinstance(sources, (list, tuple)) else [sources])
        # Non-settlement lookups (per-tick sweep, composite-history proof) are cached
        # briefly so a 20-position book / few-hundred-symbol watchlist does not hit the
        # provider every tick.  Only OK results are cached; SETTLEMENT-time assessment
        # ALWAYS bypasses the cache (fresh=True).
        self._ttl = float(cache_ttl_s)
        self._clock = clock or _time.monotonic
        self._cache: dict[tuple, tuple[float, CASourceResult]] = {}

    @property
    def source_names(self) -> list[str]:
        return [getattr(s, "name", type(s).__name__) for s in self.sources]

    def fetch(self, symbol: str, start: date, end: date, *, fresh: bool = False) -> CASourceResult:
        key = (symbol.upper(), start, end)
        now = self._clock()
        if not fresh and self._ttl > 0:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
        res = combine_sources([s.fetch(symbol, start, end) for s in self.sources])
        if res.ok and self._ttl > 0:
            self._cache[key] = (now, res)
        return res

    def assess_position(self, store, position: dict, *, as_of: date,
                        exit_basis_as_of: date | None = None, exit_session: date | None = None,
                        exit_adjustment_state: str | None = None,
                        settlement: bool = False) -> Verdict:
        row = store.position_by_id(position["position_id"])
        if row is None or row["status"] != "OPEN":
            return Verdict(V_CLEAR, detail="position not OPEN -- no corporate-action mutation")
        pid = int(row["position_id"])
        entry_session = _d(row["entry_session"])
        entry_basis = _parse_basis(row.get("entry_price_provenance"))
        end = max(as_of, exit_basis_as_of) if (settlement and exit_basis_as_of) else as_of

        res = self.fetch(row["symbol"], entry_session, end, fresh=settlement)

        # ---- evidence unavailable: transient ------------------------------
        if not res.ok:
            return self._persist_block(store, pid, Verdict(V_HOLD, C_EVIDENCE_UNAVAILABLE, res.detail),
                                       key=None)
        # ---- conflicting evidence: deterministic --------------------------
        rel_conflicts = [c for c in res.conflicts if self._conflict_in_window(c, entry_session, end)]
        if rel_conflicts:
            return self._persist_block(store, pid, Verdict(V_BLOCK, C_CONFLICT, "; ".join(rel_conflicts)),
                                       key=rel_conflicts[0])

        # an UNDATED event cannot be proven outside the window -> treated as inside (fail closed)
        in_window = [e for e in res.events
                     if e.ex_date is None or (entry_session < e.ex_date <= end)]
        # ---- unsupported / malformed / undated: deterministic -------------
        fill_for_div = (exit_session or as_of) if settlement else None
        bad = [e for e in in_window if (e.kind == KIND_UNSUPPORTED or e.ex_date is None)
               # a malformed/unsupported DIVIDEND effective after the exit fill session is irrelevant
               # to this position (it was not held through that ex-date)
               and not (fill_for_div is not None and e.provider_type == "cash_dividends"
                        and e.ex_date is not None and e.ex_date > fill_for_div)]
        if bad:
            e = bad[0]
            why = e.malformed or f"unsupported action type {e.provider_type}"
            return self._persist_block(
                store, pid, Verdict(V_BLOCK, C_MALFORMED if e.malformed else C_UNSUPPORTED,
                                    f"{why} ex/effective={e.ex_date} id={e.provider_id}"),
                key=e.action_key)

        splits = [e for e in in_window if e.kind in SPLIT_KINDS]
        dividends = [e for e in in_window if e.kind == KIND_CASH_DIVIDEND]

        # ---- basis proof ---------------------------------------------------
        # ENTRY side.  The entry price was served on basis B_e (fetch date).  A split
        # with ex < B_e is safely reflected in it (provider history rebased); ex == B_e
        # is AMBIGUOUS (the provider may not have rebased that morning) -> fail closed;
        # ex > B_e was not reflected -> must be applied to the share count.
        applicable: list[CorporateActionEvent] = []
        reflected: list[CorporateActionEvent] = []
        for e in splits:
            if entry_basis is None:
                return self._persist_block(
                    store, pid, Verdict(V_BLOCK, C_BASIS_UNKNOWN,
                                        f"entry price basis_as_of unknown; split in window "
                                        f"({e.action_key})"), key=e.action_key)
            if e.ex_date < entry_basis:
                reflected.append(e)
            elif e.ex_date == entry_basis:
                return self._persist_block(
                    store, pid, Verdict(V_BLOCK, C_BASIS_AMBIGUOUS,
                                        f"split ex_date {e.ex_date} == entry price basis date; cannot "
                                        f"prove the entry price was rebased ({e.action_key})"),
                    key=e.action_key)
            else:
                applicable.append(e)
        # a split that was applied earlier but is no longer reported is CHANGED evidence
        if any(a["status"] == TRAIL_APPLIED and a["action_key"] not in {e.action_key for e in splits}
               for a in store.position_action_trail(pid)):
            return self._persist_block(
                store, pid, Verdict(V_BLOCK, C_CONFLICT,
                                    "a previously applied split is no longer reported by the evidence "
                                    "source(s)"), key=f"CONFLICT|{row['symbol']}|applied_not_reported")
        # EXIT side (settlement only).  An exit bar dated >= ex_date is post-split raw by
        # construction; a split AFTER the exit fill session is only economically consistent
        # if the exit price was served on a basis strictly later than the ex_date.
        if settlement:
            fill = exit_session or as_of
            for e in splits:
                if e.ex_date > fill:
                    if exit_basis_as_of is None:
                        return self._persist_block(
                            store, pid, Verdict(V_BLOCK, C_BASIS_UNKNOWN,
                                                f"exit price basis_as_of unknown with a split ex_date "
                                                f"{e.ex_date} after the exit fill session {fill}"),
                            key=e.action_key)
                    if e.ex_date >= exit_basis_as_of:
                        return self._persist_block(
                            store, pid, Verdict(V_HOLD, C_EXIT_BASIS_STALE,
                                                f"exit price basis {exit_basis_as_of} does not yet include "
                                                f"split ex_date {e.ex_date} (fill session {fill})"), key=None)

        # ---- dividend entitlement (settlement only) ------------------------
        # Entitled iff entry_session < ex_date <= exit fill session (T+1-era convention: a buyer
        # on/after the ex-date is NOT entitled; a seller on/after it keeps the dividend).
        eligible_divs: list[CorporateActionEvent] = []
        if settlement:
            fill = exit_session or as_of
            eligible_divs = [e for e in dividends if entry_session < e.ex_date <= fill]
            if eligible_divs:
                entry_state = _parse_adjustment_state(row.get("entry_price_provenance"))
                bad_basis = [(w, st) for w, st in (("entry", entry_state), ("exit", exit_adjustment_state))
                             if st not in DIVIDEND_SAFE_BASES]
                if bad_basis:
                    return self._persist_block(
                        store, pid, Verdict(
                            V_BLOCK, C_DIVIDEND_BASIS,
                            f"eligible dividend {eligible_divs[0].action_key} but fill price basis is "
                            f"not dividend-unadjusted: {bad_basis} (allowed {sorted(DIVIDEND_SAFE_BASES)}); "
                            f"crediting cash on a dividend-adjusted price would double count"),
                        key=eligible_divs[0].action_key)
                for d in eligible_divs:
                    if any(sp.ex_date == d.ex_date for sp in splits):
                        return self._persist_block(
                            store, pid, Verdict(V_BLOCK, C_DIVIDEND_SPLIT_SAME_DAY,
                                                f"dividend {d.action_key} and a split share ex_date "
                                                f"{d.ex_date}: entitled share basis is ambiguous"),
                            key=d.action_key)

        # ---- apply (atomic, idempotent) ------------------------------------
        applied_now: list[str] = []
        with store.transaction():
            store.clear_blocked_action_rows(pid)
            for e in reflected:
                store.apply_position_action(position_id=pid, event=e, status=TRAIL_REFLECTED,
                                            detail=f"ex_date {e.ex_date} < entry basis {entry_basis}",
                                            entry_basis_as_of=entry_basis)
            for e in applicable:
                if store.apply_position_action(position_id=pid, event=e, status=TRAIL_APPLIED,
                                               detail="", entry_basis_as_of=entry_basis,
                                               exit_basis_as_of=exit_basis_as_of):
                    applied_now.append(e.action_key)
            for e in dividends:
                if e.ex_date <= entry_session:
                    continue
                store.apply_position_action(
                    position_id=pid, event=e, status=TRAIL_DIVIDEND_OBSERVED,
                    detail=("eligible: receivable created at settlement" if e in eligible_divs
                            else "observed during hold (entitlement decided at settlement)"),
                    entry_basis_as_of=entry_basis)
            eff = store.effective_shares_exact(pid)
        adjusted = any(a["status"] == TRAIL_APPLIED for a in store.position_action_trail(pid))
        return Verdict(V_ADJUSTED if adjusted else V_CLEAR, applied=tuple(applied_now),
                       effective_shares=eff, dividends=tuple(eligible_divs))

    @staticmethod
    def _conflict_in_window(conflict: str, entry_session: date, end: date) -> bool:
        parts = conflict.split("|")
        ex = _d(parts[2]) if len(parts) > 2 else None
        return ex is None or (entry_session < ex <= end)

    @staticmethod
    def _persist_block(store, pid: int, v: Verdict, *, key: str | None) -> Verdict:
        """Blocked verdicts are DERIVED diagnostics: persisted (replaceable) for
        operator visibility; they are never economics."""
        if key is not None:
            with store.transaction():
                store.clear_blocked_action_rows(pid)
                store.record_blocked_action(pid, key, TRAIL_BLOCKED_PREFIX + v.code, v.detail)
        return v


# --------------------------------------------------------------------------- #
# read-only consistency / projection helpers (raw sqlite connection)
# --------------------------------------------------------------------------- #
def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def effective_shares_map(con: sqlite3.Connection) -> dict[int, float]:
    """``{position_id: economic shares}`` for positions carrying APPLIED trail
    rows; positions absent from the map use their entry ``shares``.  Read-only."""
    if not _has_table(con, "position_corporate_actions"):
        return {}
    out: dict[int, Fraction] = {}
    for r in con.execute(
            "SELECT p.position_id, p.shares, a.ratio_num, a.ratio_den FROM position_corporate_actions a "
            "JOIN positions p ON p.position_id=a.position_id WHERE a.status=? ORDER BY a.id", (TRAIL_APPLIED,)):
        base = out.get(r[0], Fraction(str(r[1])))
        out[r[0]] = base * Fraction(int(r[2]), int(r[3]))
    return {k: float(v) for k, v in out.items()}


def shares_at_date(con: sqlite3.Connection, position_id: int, on_date: date) -> Fraction:
    """Economic shares held at the close BEFORE ``on_date``'s open (a dividend's ex-date), exact.

    ``positions.shares`` is expressed on the entry price basis ``B_e``: splits already
    reflected in that basis (REFLECTED rows) must be UNDONE for a date before their
    ex-date; splits applied afterwards (APPLIED rows) count only once their ex-date is
    strictly before ``on_date``.  Provider dividend ``rate`` is per share AS OF the ex-date
    (raw, not split-normalised), so ``rate x shares_at_date`` is the correct amount."""
    r = con.execute("SELECT shares FROM positions WHERE position_id=?", (position_id,)).fetchone()
    q = Fraction(str(r[0] if not isinstance(r, sqlite3.Row) else r["shares"])) if r else Fraction(0)
    for a in con.execute(
            "SELECT status, ex_date, ratio_num, ratio_den FROM position_corporate_actions "
            "WHERE position_id=? AND status IN ('APPLIED','REFLECTED_IN_ENTRY_BASIS') AND kind LIKE '%SPLIT' "
            "ORDER BY id", (position_id,)):
        status, ex, num, den = a[0], _d(a[1]), int(a[2]), int(a[3])
        ratio = Fraction(num, den)
        if status == TRAIL_APPLIED and ex < on_date:
            q *= ratio
        elif status == TRAIL_REFLECTED and ex > on_date:
            q /= ratio
    return q


def trail_rows(con: sqlite3.Connection, *, position_id: int | None = None) -> list[dict]:
    if not _has_table(con, "position_corporate_actions"):
        return []
    q = ("SELECT a.*, p.symbol AS symbol FROM position_corporate_actions a "
         "JOIN positions p ON p.position_id=a.position_id")
    args: tuple = ()
    if position_id is not None:
        q += " WHERE a.position_id=?"
        args = (position_id,)
    prev = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(q + " ORDER BY a.id", args)]
    finally:
        con.row_factory = prev


def consistency_problems(con: sqlite3.Connection) -> list[str]:
    """Genuinely inconsistent adjustment state (read-only).  A correctly adjusted
    split produces NO problem; the checks fail closed on real corruption."""
    if not _has_table(con, "position_corporate_actions"):
        return []
    # No corporate-action state in this ledger -> nothing to be inconsistent about
    # (also keeps minimal/legacy schemas from producing false alarms).
    if con.execute("SELECT COUNT(*) FROM position_corporate_actions").fetchone()[0] == 0:
        return []
    problems: list[str] = []
    prev = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        try:
            pos = {r["position_id"]: dict(r) for r in con.execute(
                "SELECT position_id, episode_id, status, shares, entry_session FROM positions")}
        except sqlite3.OperationalError as exc:
            return [f"cannot read positions to verify corporate-action trail: {exc}"]
        by_pos: dict[int, list[dict]] = {}
        for r in con.execute("SELECT * FROM position_corporate_actions ORDER BY id"):
            by_pos.setdefault(r["position_id"], []).append(dict(r))
        for pid, rows in by_pos.items():
            p = pos.get(pid)
            if p is None:
                problems.append(f"corporate-action trail for missing position_id={pid}")
                continue
            chain = Fraction(str(p["shares"]))
            for r in rows:
                if r["status"] != TRAIL_APPLIED:
                    continue
                if r["ex_date"] <= p["entry_session"]:
                    problems.append(f"position {p['episode_id']}: split {r['action_key']} applied with "
                                    f"ex_date {r['ex_date']} <= entry_session {p['entry_session']}")
                if Fraction(r["shares_before"]) != chain:
                    problems.append(f"position {p['episode_id']}: trail chain break at {r['action_key']} "
                                    f"(before={r['shares_before']} expected={chain})")
                after = Fraction(r["shares_before"]) * Fraction(int(r["ratio_num"]), int(r["ratio_den"]))
                if Fraction(r["shares_after"]) != after:
                    problems.append(f"position {p['episode_id']}: shares_after != before*ratio at {r['action_key']}")
                chain = Fraction(r["shares_after"])
            if p["status"] == "CLOSED":
                sells = con.execute("SELECT shares FROM trades WHERE action='SELL' AND episode_id=?",
                                    (p["episode_id"],)).fetchall()
                for s in sells:
                    if abs(Fraction(str(s["shares"])) - chain) > Fraction(1, 10**9) * max(1, abs(chain)):
                        problems.append(f"position {p['episode_id']}: SELL shares {s['shares']} != "
                                        f"economic shares {float(chain)} after corporate actions")
        # a CLOSED split-affected position whose SELL used entry shares is caught above; conversely
        # a CLOSED position with NO trail whose SELL shares != entry shares is also inconsistent:
        for pid, p in pos.items():
            if p["status"] == "CLOSED" and pid not in by_pos:
                for s in con.execute("SELECT shares FROM trades WHERE action='SELL' AND episode_id=?",
                                     (p["episode_id"],)):
                    if s["shares"] is not None and abs(float(s["shares"]) - float(p["shares"])) > 1e-9:
                        problems.append(f"position {p['episode_id']}: SELL shares {s['shares']} != entry "
                                        f"shares {p['shares']} with no corporate-action trail")
    finally:
        con.row_factory = prev
    return problems
