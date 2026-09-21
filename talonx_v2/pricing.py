"""
talonx_v2.pricing -- daily-bar adapters for the V2 companion (Task 117 Phase 0 F2)
================================================================================
The frozen pipeline consumes two callables:

    bars_lookup(symbol)              -> list[{date, open, close, volume}]
    price_lookup(symbol, session)   -> {open, close, volume} | None

Entry uses the ``open`` of the eligible entry session; exit uses the
``close`` of the +10th session; the liquidity gate uses ``close*volume``
over the 20 sessions STRICTLY BEFORE entry (Task 109 contract).  This
module supplies those callables from a swappable *daily-bar adapter* so
the companion is not hard-wired to a static CSV directory.

FROZEN pricing contract (Task 109 / Task 107A): Alpaca SIP ``/v2/stocks/bars``
``1Day`` ``adjustment=all``.  ``CsvBarAdapter`` replays exactly that
(the Task 107A ``_prices`` snapshot).  ``AlpacaIexBarAdapter`` is a
**data-only, NON-CONFORMANT** live source (single-venue IEX volume is a
small fraction of consolidated -> it breaks the liquidity $-volume gate)
and is provided for probes / parity study only -- it is NOT wired into
the live companion, which stays on ``CsvBarAdapter`` until the
provider-parity decision is taken (see contract_matrix.md).

Nothing here sends orders or touches a broker.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

_LOOKBACK_LOAD_SESSIONS = 60          # enough for the 20-session liquidity window + slack


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    close: float
    volume: float
    status: str = "FINAL"            # FINAL | PROVISIONAL
    source: str = ""
    source_timestamp: str | None = None
    receipt_timestamp: str | None = None
    adjustment_state: str = "UNKNOWN"
    # PQ-2A: the date on which the provider computed the adjustment basis this row
    # is expressed on (splits/dividends with ex_date <= basis_as_of are reflected).
    # None = UNKNOWN (e.g. a static snapshot) -- never guessed.
    basis_as_of: str | None = None

    def as_dict(self) -> dict:
        return {"date": self.date, "open": self.open, "close": self.close,
                "volume": self.volume, "status": self.status, "source": self.source,
                "source_timestamp": self.source_timestamp,
                "receipt_timestamp": self.receipt_timestamp,
                "adjustment_state": self.adjustment_state,
                "basis_as_of": self.basis_as_of}


@dataclass(frozen=True)
class PriceUnavailable:
    symbol: str
    session: str
    reason: str                      # NO_BAR | PROVISIONAL_ONLY | REJECTED_<why> | PROVIDER_ERROR | FUTURE_SESSION


def _finite_pos(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0.0


def validate_bar(raw: dict, *, symbol: str, want_session: str,
                 today: date, source: str) -> Bar | PriceUnavailable:
    """Reject stale / malformed / nonfinite / zero-or-negative / future /
    wrong-session rows.  A row dated after ``today`` -- or dated ``today``
    itself before the session has closed -- is PROVISIONAL, never usable
    as a completed daily close/volume."""
    d = str(raw.get("date") or raw.get("t") or "")[:10]
    if not d:
        return PriceUnavailable(symbol, want_session, "REJECTED_NO_DATE")
    if d != want_session:
        return PriceUnavailable(symbol, want_session, f"REJECTED_WRONG_SESSION_{d}")
    o = raw.get("open", raw.get("o"))
    c = raw.get("close", raw.get("c"))
    v = raw.get("volume", raw.get("v"))
    if not _finite_pos(o) or not _finite_pos(c):
        return PriceUnavailable(symbol, want_session, "REJECTED_NONFINITE_OR_NONPOSITIVE_PRICE")
    if v is None or (not math.isfinite(float(v))) or float(v) < 0:
        return PriceUnavailable(symbol, want_session, "REJECTED_BAD_VOLUME")
    try:
        sd = date.fromisoformat(d)
    except ValueError:
        return PriceUnavailable(symbol, want_session, "REJECTED_BAD_DATE")
    if sd > today:
        return PriceUnavailable(symbol, want_session, "FUTURE_SESSION")
    status = "PROVISIONAL" if sd == today else "FINAL"
    # A composite adapter tags each row with the sub-adapter that actually
    # supplied it (PQ-1) so persisted provenance names the real source.
    return Bar(date=d, open=float(o), close=float(c), volume=float(v),
              status=status, source=str(raw.get("_source_adapter") or source),
              source_timestamp=raw.get("_source_timestamp") or raw.get("t"),
              receipt_timestamp=datetime.now(timezone.utc).isoformat(),
              adjustment_state=str(raw.get("_adjustment_state") or "UNKNOWN"),
              basis_as_of=(str(raw["_basis_as_of"])[:10] if raw.get("_basis_as_of") else None))


# --------------------------------------------------------------------------- #
# adapter protocol
# --------------------------------------------------------------------------- #
class DailyBarAdapter(Protocol):
    name: str

    def history(self, symbol: str) -> list[dict]:
        """All locally-known FINAL sessions for ``symbol`` (ascending)."""

    def session(self, symbol: str, session: date) -> dict | None:
        """One session's raw row, or None."""


# --------------------------------------------------------------------------- #
# CSV adapter -- the frozen-conformant default (Task 107A Alpaca SIP snapshot)
# --------------------------------------------------------------------------- #
class CsvBarAdapter:
    name = "csv:task107a_sip_adjustment_all"
    adjustment_state = "SPLIT_DIVIDEND_ADJUSTED"

    def __init__(self, bar_dirs: list[str | Path]):
        self.bar_dirs = [Path(p) for p in bar_dirs]
        self._cache: dict[str, list[dict]] = {}

    def _load(self, symbol: str) -> list[dict]:
        if symbol in self._cache:
            return self._cache[symbol]
        import pandas as pd
        rows: list[dict] = []
        for d in self.bar_dirs:
            f = d / f"{symbol}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    df = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    continue
                if "date" not in df.columns:
                    continue
                rows = [{"date": str(r.date)[:10], "open": float(getattr(r, "open", "nan")),
                         "close": float(r.close), "volume": float(getattr(r, "volume", 0) or 0)}
                        for r in df.itertuples(index=False)]
                for row in rows:
                    row["_adjustment_state"] = self.adjustment_state
                break
        rows.sort(key=lambda r: r["date"])
        self._cache[symbol] = rows
        return rows

    def history(self, symbol: str) -> list[dict]:
        return list(self._load(symbol))

    def session(self, symbol: str, session: date) -> dict | None:
        s = session.isoformat()
        for r in self._load(symbol):
            if r["date"] == s:
                return r
        return None


# --------------------------------------------------------------------------- #
# Alpaca IEX adapter -- DATA-ONLY, NON-CONFORMANT (parity not established)
# --------------------------------------------------------------------------- #
class AlpacaIexBarAdapter:
    name = "alpaca:iex:1Day:adjustment=all(NON_CONFORMANT_vs_SIP)"
    CONFORMANT = False
    adjustment_state = "SPLIT_DIVIDEND_ADJUSTED"

    def __init__(self, *, key_id: str | None = None, secret: str | None = None,
                 http_get: Callable[[str, dict], dict] | None = None):
        self._kid = key_id or os.environ.get("APCA_API_KEY_ID", "")
        self._sec = secret or os.environ.get("APCA_API_SECRET_KEY", "")
        self._get = http_get or self._default_get
        self._cache: dict[str, list[dict]] = {}

    def _default_get(self, url: str, params: dict) -> dict:  # pragma: no cover - network
        import json
        import urllib.parse
        import urllib.request
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{url}?{q}",
            headers={"APCA-API-KEY-ID": self._kid, "APCA-API-SECRET-KEY": self._sec})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)

    def _fetch(self, symbol: str) -> list[dict]:
        if symbol in self._cache:
            return self._cache[symbol]
        d = self._get("https://data.alpaca.markets/v2/stocks/bars",
                      {"symbols": symbol, "timeframe": "1Day", "adjustment": "all",
                       "feed": "iex", "limit": str(_LOOKBACK_LOAD_SESSIONS + 5)})
        bars = d.get("bars", {}).get(symbol, []) or []
        basis = datetime.now(timezone.utc).date().isoformat()     # PQ-2A: fetch-date basis
        rows = [{"date": str(b["t"])[:10], "open": float(b["o"]), "close": float(b["c"]),
                 "volume": float(b["v"]), "_source_timestamp": str(b["t"]),
                 "_adjustment_state": self.adjustment_state, "_basis_as_of": basis} for b in bars]
        rows.sort(key=lambda r: r["date"])
        self._cache[symbol] = rows
        return rows

    def history(self, symbol: str) -> list[dict]:
        return list(self._fetch(symbol))

    def session(self, symbol: str, session: date) -> dict | None:
        s = session.isoformat()
        for r in self._fetch(symbol):
            if r["date"] == s:
                return r
        return None


# --------------------------------------------------------------------------- #
# yfinance adapter -- FROZEN-CONFORMANT CANDIDATE (Task 117 Phase 0 parity study)
# --------------------------------------------------------------------------- #
class YFinanceBarAdapter:
    """Free consolidated daily bars, ``auto_adjust=True`` (split+dividend
    adjusted OHLC, split-adjusted volume) -- the policy match to Alpaca
    ``adjustment=all``.

    Parity study (results/task117_phase0_free_data_and_lifecycle_*/provider_study):
    22 symbols across the $5-close and $5M-median-$-volume boundaries,
    1210 field comparisons, 660 candidate entry-session liquidity
    classifications (580 PASS + 80 FAIL) -> **0 classification flips**,
    close p99 relative diff 0.06%, volume p90 0.4%; no future/holiday/latest
    substitution.  `CONFORMANT = True` **only within that tested domain**;
    still not enabled for ACTIVE by default.
    """
    name = "yfinance:1d:auto_adjust=all"
    CONFORMANT = True                       # within the Phase 0 parity-study domain
    adjustment_state = "SPLIT_DIVIDEND_ADJUSTED"

    def __init__(self, *, ticker_factory: Callable[[str], object] | None = None,
                 lookback_sessions: int = _LOOKBACK_LOAD_SESSIONS):
        self._tf = ticker_factory
        self._lb = lookback_sessions
        self._cache: dict[str, list[dict]] = {}

    def _fetch(self, symbol: str) -> list[dict]:
        if symbol in self._cache:
            return self._cache[symbol]
        if self._tf is not None:
            tk = self._tf(symbol)
        else:  # pragma: no cover - network
            import yfinance as yf
            tk = yf.Ticker(symbol)
        import datetime as _dt
        start = (_dt.date.today() - _dt.timedelta(days=int(self._lb * 1.6) + 10)).isoformat()
        h = tk.history(start=start, interval="1d", auto_adjust=True, actions=False)
        rows: list[dict] = []
        basis = datetime.now(timezone.utc).date().isoformat()     # PQ-2A: fetch-date basis
        if h is not None and not h.empty:
            h = h.reset_index()
            for r in h.itertuples(index=False):
                d = getattr(r, "Date", None) or getattr(r, "index", None)
                rows.append({"date": str(d)[:10], "open": float(r.Open),
                             "close": float(r.Close), "volume": float(r.Volume),
                             "_source_timestamp": str(d),
                             "_adjustment_state": self.adjustment_state,
                             "_basis_as_of": basis})
        rows.sort(key=lambda x: x["date"])
        self._cache[symbol] = rows
        return rows

    def history(self, symbol: str) -> list[dict]:
        return list(self._fetch(symbol))

    def session(self, symbol: str, session: date) -> dict | None:
        s = session.isoformat()
        return next((r for r in self._fetch(symbol) if r["date"] == s), None)


# --------------------------------------------------------------------------- #
# composite: FINAL history from `hist`, recent tail from `live`
# --------------------------------------------------------------------------- #
class IncompatibleAdjustmentBasis(RuntimeError):
    """Raised when a merged history would combine rows on adjustment bases that
    cannot be PROVEN compatible across a corporate action (PQ-2A)."""


class CompositeBarAdapter:
    """Liquidity window (older, FINAL) from ``hist``; the entry/exit session
    (recent) from ``live`` when ``hist`` has no bar for it.  Keeps the
    deterministic historical snapshot authoritative for everything it
    covers and only reaches ``live`` for the uncovered recent tail.

    PQ-2A: ``history()`` may only splice the two sources when their adjustment
    bases are PROVEN compatible.  Rows carry ``_basis_as_of`` (fetch date; None
    for a static snapshot).  If both are known and equal -> compatible.  Else the
    ``ca_source`` (a corporate-action source) must show NO split/unsupported
    action with an effective date in ``(hist basis, live basis]`` -- otherwise (or
    if evidence is unavailable / no source is configured) the merge is REFUSED
    (``IncompatibleAdjustmentBasis``) rather than silently mixing a pre-split
    snapshot with a post-split tail.  ``session()`` returns ONE source's row and
    never mixes."""
    name = "composite"

    def __init__(self, hist: DailyBarAdapter, live: DailyBarAdapter, *, ca_source=None,
                 today: Callable[[], date] | None = None):
        self.hist, self.live = hist, live
        self.name = f"composite({hist.name}+{live.name})"
        self.ca_source = ca_source
        self._today = today or (lambda: datetime.now(timezone.utc).date())

    @staticmethod
    def _tag(row: dict | None, adapter) -> dict | None:
        return None if row is None else {**row, "_source_adapter": adapter.name}

    @staticmethod
    def _basis(rows: list[dict]) -> date | None:
        """Earliest known basis among rows; None if ANY row lacks one (unknown)."""
        bases = []
        for r in rows:
            b = r.get("_basis_as_of")
            if not b:
                return None
            bases.append(date.fromisoformat(str(b)[:10]))
        return min(bases) if bases else None

    def _require_compatible(self, symbol: str, h: list[dict], live_rows: list[dict]) -> None:
        hb, lb = self._basis(h), self._basis(live_rows)
        if hb is not None and lb is not None and hb == lb:
            return                                            # same basis date -> compatible
        if self.ca_source is None:
            raise IncompatibleAdjustmentBasis(
                f"{symbol}: hist basis {hb} != live basis {lb} and no corporate-action evidence "
                f"source configured -- refusing to splice")
        hist_last = max(date.fromisoformat(r["date"]) for r in h)
        lower = hb if hb is not None else hist_last
        upper = lb if lb is not None else self._today()
        if upper <= lower:
            return
        res = self.ca_source.fetch(symbol, lower + timedelta(days=1), upper)
        if not res.ok:
            raise IncompatibleAdjustmentBasis(
                f"{symbol}: corporate-action evidence unavailable ({res.detail}) -- cannot prove "
                f"hist basis {hb} and live basis {lb} are compatible")
        if res.conflicts:
            raise IncompatibleAdjustmentBasis(f"{symbol}: conflicting corporate-action evidence "
                                              f"{list(res.conflicts)}")
        for e in res.events:
            # dividends only rescale by a tiny factor inside the frozen `adjustment=all`
            # contract; splits and unsupported actions are NOT safe to splice across.
            if e.kind != "CASH_DIVIDEND" and (e.ex_date is None or lower < e.ex_date <= upper):
                raise IncompatibleAdjustmentBasis(
                    f"{symbol}: {e.kind} ({e.action_key}) effective {e.ex_date} lies between the "
                    f"snapshot basis ({hb}) and live basis ({lb}) -- mixed adjustment bases")

    def history(self, symbol: str) -> list[dict]:
        h = [self._tag(r, self.hist) for r in self.hist.history(symbol)]
        seen = {r["date"] for r in h}
        live_rows = [self._tag(r, self.live) for r in self.live.history(symbol)
                     if r["date"] not in seen]
        if h and live_rows:
            self._require_compatible(symbol, h, live_rows)
        merged = h + live_rows
        merged.sort(key=lambda r: r["date"])
        return merged

    def session(self, symbol: str, session: date) -> dict | None:
        return (self._tag(self.hist.session(symbol, session), self.hist)
                or self._tag(self.live.session(symbol, session), self.live))


# --------------------------------------------------------------------------- #
# factory: adapter -> (bars_lookup, price_lookup, resolve)
# --------------------------------------------------------------------------- #
@dataclass
class PricingResolver:
    adapter: DailyBarAdapter
    today: Callable[[], date] = field(default=lambda: datetime.now(timezone.utc).date())
    last: dict = field(default_factory=dict)   # symbol|session -> Bar|PriceUnavailable (introspection)

    def bars_lookup(self, symbol: str) -> list[dict]:
        # FINAL sessions only -- never feed a PROVISIONAL "today" bar into the
        # 20-session liquidity median (no future close/full-day volume leak).
        t = self.today()
        out = []
        try:
            hist = self.adapter.history(symbol)
        except IncompatibleAdjustmentBasis:
            # PQ-2A: fail closed -- an unprovable/mixed adjustment basis is never used.
            self.last[f"{symbol}|history"] = PriceUnavailable(
                symbol, "history", "REJECTED_INCOMPATIBLE_ADJUSTMENT_BASIS")
            return out
        except Exception:  # noqa: BLE001 -- transient provider fault -> empty history
            # (the liquidity gate then reports NO_PRIOR_BARS / INSUFFICIENT_HISTORY,
            # a non-terminal skip that retries next tick, rather than crashing the tick).
            self.last[f"{symbol}|history"] = PriceUnavailable(symbol, "history", "PROVIDER_ERROR")
            return out
        for r in hist:
            b = validate_bar(r, symbol=symbol, want_session=str(r["date"])[:10],
                             today=t, source=self.adapter.name)
            if isinstance(b, Bar) and b.status == "FINAL":
                out.append({"date": b.date, "open": b.open, "close": b.close, "volume": b.volume,
                            "_provenance": {"provider": b.source, "session": b.date,
                                             "source_timestamp": b.source_timestamp,
                                             "receipt_timestamp": b.receipt_timestamp,
                                             "adjustment_state": b.adjustment_state,
                                             "basis_as_of": b.basis_as_of,
                                             "finality": b.status}})
        return out

    def resolve(self, symbol: str, session: date) -> Bar | PriceUnavailable:
        t = self.today()
        s = session.isoformat()
        if session > t:
            r = PriceUnavailable(symbol, s, "FUTURE_SESSION")
            self.last[f"{symbol}|{s}"] = r
            return r
        try:
            raw = self.adapter.session(symbol, session)
        except Exception:  # noqa: BLE001 -- a transient provider fault is an explicit
            # *temporary* unavailability, never a tick-aborting crash (Task 117 Phase 0 §2).
            r = PriceUnavailable(symbol, s, "PROVIDER_ERROR")
            self.last[f"{symbol}|{s}"] = r
            return r
        if raw is None:
            r = PriceUnavailable(symbol, s, "NO_BAR")
        else:
            r = validate_bar(raw, symbol=symbol, want_session=s, today=t, source=self.adapter.name)
            if isinstance(r, Bar) and r.status == "PROVISIONAL":
                r = PriceUnavailable(symbol, s, "PROVISIONAL_ONLY")
        self.last[f"{symbol}|{s}"] = r
        return r

    def price_lookup(self, symbol: str, session) -> dict | None:
        sd = session if isinstance(session, date) else date.fromisoformat(str(session)[:10])
        r = self.resolve(symbol, sd)
        if isinstance(r, Bar):
            return {"open": r.open, "close": r.close, "volume": r.volume,
                    "_provenance": {"provider": r.source, "session": r.date,
                                     "source_timestamp": r.source_timestamp,
                                     "receipt_timestamp": r.receipt_timestamp,
                                     "adjustment_state": r.adjustment_state,
                                     "basis_as_of": r.basis_as_of,
                                     "finality": r.status}}
        return None            # pipeline treats None as SKIPPED_NO_ENTRY_BAR / fall-forward


def make_resolver(*, mode: str, bar_dirs: list[str | Path],
                  today: Callable[[], date] | None = None,
                  yf_ticker_factory: Callable[[str], object] | None = None,
                  ca_source=None) -> PricingResolver:
    """``mode``:
      "csv"          -- frozen CSV snapshot only (default live wiring; the
                        companion stays here until the provider decision is
                        signed off).
      "composite-yf" -- FINAL history from the CSV snapshot + the recent tail
                        from yfinance (``auto_adjust=True``).  FROZEN-CONFORMANT
                        CANDIDATE per the Phase 0 parity study; supply it via
                        --pricing-mode composite-yf for a candidate run.  Never
                        auto-enabled for ACTIVE.
      "composite-iex" -- CSV history + Alpaca IEX tail.  NON-CONFORMANT
                        (single-venue volume breaks the liquidity gate) --
                        probes / study only.
    """
    csv = CsvBarAdapter(bar_dirs)
    if mode == "csv":
        adapter: DailyBarAdapter = csv
    elif mode == "composite-yf":
        adapter = CompositeBarAdapter(csv, YFinanceBarAdapter(ticker_factory=yf_ticker_factory),
                                      ca_source=ca_source, today=today)
    elif mode == "composite-iex":
        adapter = CompositeBarAdapter(csv, AlpacaIexBarAdapter(), ca_source=ca_source, today=today)
    else:
        raise ValueError(f"unknown pricing mode {mode!r}")
    r = PricingResolver(adapter=adapter)
    if today is not None:
        r.today = today
    return r
