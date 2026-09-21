"""
talonx_v2.provider_contract -- PQ-2B: the ONE executable first-release price-provider contract
============================================================================================
Evidence: docs/research/evidence/provider_qualification_pq2b/ (bounded read-only Alpaca probes).

AUTHORITATIVE RELEASE PROVIDER   Alpaca Market Data v2, ``GET /v2/stocks/bars``
FEED / TIMEFRAME                 ``feed=sip`` (consolidated tape), ``timeframe=1Day``
ADJUSTMENT BASIS                 ``adjustment=split`` (split-adjusted price, inverse-split-adjusted
                                 volume, NO dividend adjustment -- PQ-2A: dividends are explicit cash)
FALLBACK                         NONE (one authoritative provider, fail closed)

Measured semantics (PQ-2B):
* daily ``c``  == the official closing-auction cross print (SIP condition ``6``) -- 30/30 samples,
  incl. four 13:00-ET early closes.  It is NOT the last extended-hours trade.
* daily ``o``  == the provider's first eligible trade of the day by participant timestamp.  It is NOT
  the official opening-auction print (exact in 7/29; max deviation 1.2%).  Same definition as the
  frozen Task107A/95G research snapshots.
* daily ``v``  == consolidated volume over the WHOLE tape day 04:00 ET .. post-market end (daily /
  (regular + extended minute volume) = 1.000..1.098), inversely split-adjusted.
* the tape's post-market session ends 20:00 ET (17:00 ET after an early close) = official close + 4h.
* free-tier SIP: the request ``end`` must be >= 15 minutes old.

Usability / finality rule (both OPEN and CLOSE of session S, no exception):
    usable  <=>  now >= session_extended_end(S) + 15 min + 1 min (provider settle)
i.e. the daily bar is COMPLETE (post-market over: its volume/high/low stop growing) plus a CONSERVATIVE margin
equal to the provider's documented free-tier SIP delay window (15 min) and its late-trade recalculation
margin (~30 s).  Live probe (PQ-2B, 2026-09-21): the free tier serves the IN-PROGRESS current-day bar in
near real time (first visible 81 s after the 09:30 open, not bounded by the request ``end``), so the
15 minutes is NOT required for visibility -- it is retained because the minimal safe margin after
post-market end could not be measured (no same-day close observation) and paper settlement is not
latency-sensitive.  An in-progress bar is PROVISIONAL (partial close/high/low/volume) and is never used.
This replaces the previous UTC-date heuristic, which was 1h early in winter and ignored the early-close
calendar.  Historical corrections after usability are not detectable (no version metadata) --
the persisted execution value is immutable and later provider revisions are never applied silently.

No network is performed at import.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Sequence

from talonx_v2 import calendar as v2cal

REQUIRED_ENV = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
SIP_QUERY_LAG_MINUTES = 15          # free-tier SIP: `end` must be >= 15 min old (documented + probed)
SETTLE_MARGIN_MINUTES = 1           # provider recalculation window for late trades (~30 s documented)


@dataclass(frozen=True)
class ReleaseProviderContract:
    contract_id: str = "V2_RELEASE_PRICE_CONTRACT@1"
    provider: str = "alpaca"
    endpoint: str = "https://data.alpaca.markets/v2/stocks/bars"
    timeframe: str = "1Day"
    feed: str = "sip"
    adjustment: str = "split"
    open_field: str = "o"
    close_field: str = "c"
    volume_field: str = "v"
    open_semantics: str = "PROVIDER_DAILY_FIRST_ELIGIBLE_TRADE_OPEN_NOT_OFFICIAL_AUCTION_PRINT"
    close_semantics: str = "OFFICIAL_CLOSING_CROSS_PRINT"
    volume_semantics: str = "CONSOLIDATED_FULL_TAPE_DAY_INVERSE_SPLIT_ADJUSTED"
    session_tz: str = "America/New_York"
    fallback_mode: str = "NONE"
    timeout_s: float = 20.0
    max_pages: int = 5
    cache_ttl_s: float = 300.0
    required_env: tuple = REQUIRED_ENV

    def fingerprint(self) -> str:
        blob = json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()},
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


RELEASE_CONTRACT = ReleaseProviderContract()


# --------------------------------------------------------------------------- #
# finality
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FinalityPolicy:
    contract: ReleaseProviderContract = RELEASE_CONTRACT

    def usable_at(self, session: date) -> datetime:
        return (v2cal.session_extended_end_utc(session)
                + timedelta(minutes=SIP_QUERY_LAG_MINUTES + SETTLE_MARGIN_MINUTES))

    def is_usable(self, session: date, now: datetime) -> bool:
        return now >= self.usable_at(session)

    def rule_text(self) -> str:
        return (f"usable iff now >= session_extended_end(S)=close(S)+{v2cal.EXTENDED_SESSION_AFTER_CLOSE_HOURS}h "
                f"+ {SIP_QUERY_LAG_MINUTES}min SIP lag + {SETTLE_MARGIN_MINUTES}min settle")


# --------------------------------------------------------------------------- #
# adapter semantics registry (fallback compatibility + replay classification)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AdapterSemantics:
    name: str
    feed_scope: str              # CONSOLIDATED_SIP | SINGLE_VENUE_IEX | UNVERIFIED
    adjustment: str              # split | all | raw | unknown
    open_semantics: str
    close_semantics: str
    volume_semantics: str
    session_tz: str
    source_kind: str             # live | snapshot
    qualified: bool
    corporate_action_accounting: bool = True


_C = RELEASE_CONTRACT
SEMANTICS = {
    "sip_release": AdapterSemantics("alpaca:sip:1Day:split", "CONSOLIDATED_SIP", "split", _C.open_semantics,
                                    _C.close_semantics, _C.volume_semantics, _C.session_tz, "live", True),
    "iex_split": AdapterSemantics("alpaca:iex:1Day:split", "SINGLE_VENUE_IEX", "split",
                                  "IEX_SINGLE_VENUE_FIRST_TRADE", "IEX_SINGLE_VENUE_LAST_TRADE",
                                  "IEX_SINGLE_VENUE_VOLUME", _C.session_tz, "live", False),
    "yfinance_split": AdapterSemantics("yfinance:1d:auto_adjust=False", "UNVERIFIED", "split",
                                       "UNVERIFIED_YAHOO_DAILY_OPEN", "UNVERIFIED_YAHOO_DAILY_CLOSE",
                                       "UNVERIFIED_YAHOO_VOLUME", _C.session_tz, "live", False),
    "task107a_sip_snapshot": AdapterSemantics("csv:task107a_sip_adjustment_all", "CONSOLIDATED_SIP", "all",
                                              _C.open_semantics, _C.close_semantics, _C.volume_semantics,
                                              _C.session_tz, "snapshot", True, corporate_action_accounting=False),
}

_HARD_DIMS = ("feed_scope", "open_semantics", "close_semantics", "volume_semantics", "session_tz")


def fallback_mismatches(primary: AdapterSemantics, candidate: AdapterSemantics) -> list[str]:
    """Every dimension on which ``candidate`` is NOT interchangeable with ``primary`` (empty list =>
    semantically compatible).  A fallback is only valid with NO mismatch, an identical adjustment basis
    and a qualified candidate.  With ``fallback_mode == NONE`` (the release setting) nothing is used
    regardless."""
    out = [f"{d}: {getattr(primary, d)} != {getattr(candidate, d)}" for d in _HARD_DIMS
           if getattr(primary, d) != getattr(candidate, d)]
    if primary.adjustment != candidate.adjustment:
        out.append(f"adjustment: {primary.adjustment} != {candidate.adjustment}")
    if candidate.source_kind != "live":
        out.append("source_kind: candidate is not a live source")
    if not candidate.qualified:
        out.append("candidate is not qualified")
    return out


def fallback_allowed(primary: AdapterSemantics, candidate: AdapterSemantics, *,
                     mode: str = RELEASE_CONTRACT.fallback_mode) -> tuple[bool, list[str]]:
    if mode == "NONE":
        return False, ["fallback_mode NONE: one authoritative provider, fail closed"]
    mism = fallback_mismatches(primary, candidate)
    return (not mism), mism


def classify_replay(replay: AdapterSemantics, release: AdapterSemantics = SEMANTICS["sip_release"]) -> tuple[str, list[str]]:
    """COMPATIBLE / PARTIALLY_COMPATIBLE / INCOMPATIBLE of a historical/replay evidence source against
    the release contract.  Any hard semantic difference (feed scope, OPEN/CLOSE/volume definition,
    session identity) => INCOMPATIBLE; only soft differences (dividend adjustment basis, snapshot vs live
    timing, absent corporate-action accounting) => PARTIALLY_COMPATIBLE."""
    hard = [f"{d}: {getattr(replay, d)} != {getattr(release, d)}" for d in _HARD_DIMS
            if getattr(replay, d) != getattr(release, d)]
    soft = []
    if replay.adjustment != release.adjustment:
        soft.append(f"adjustment: replay {replay.adjustment} vs release {release.adjustment}")
    if replay.source_kind != release.source_kind:
        soft.append(f"source_kind: replay {replay.source_kind} snapshot vs live release feed (finality/timing not reproduced)")
    if not replay.corporate_action_accounting:
        soft.append("corporate-action position accounting absent in replay")
    if hard:
        return "INCOMPATIBLE", hard + soft
    return ("PARTIALLY_COMPATIBLE" if soft else "COMPATIBLE"), soft


# --------------------------------------------------------------------------- #
# readiness (bounded, read-only)
# --------------------------------------------------------------------------- #
LEVELS = ("NOT_CONFIGURED", "CONFIGURED", "REACHABLE", "ENTITLED", "QUALIFIED")


@dataclass
class ReadinessReport:
    level: str = "NOT_CONFIGURED"
    checks: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    @property
    def qualified(self) -> bool:
        return self.level == "QUALIFIED"

    def to_dict(self) -> dict:
        return {"level": self.level, "checks": self.checks, "problems": self.problems,
                "contract_id": RELEASE_CONTRACT.contract_id, "contract_fingerprint": RELEASE_CONTRACT.fingerprint()}


def _rel(a: float, b: float) -> float:
    return abs(a / b - 1.0) if b else float("inf")


def check_readiness(*, env: dict | None = None, http_get: Callable[[str, dict], dict] | None = None,
                    now: Callable[[], datetime] | None = None,
                    contract: ReleaseProviderContract = RELEASE_CONTRACT) -> ReadinessReport:
    """CONFIGURED (credentials present) -> REACHABLE (an HTTP answer) -> ENTITLED (SIP daily bars
    return 200) -> QUALIFIED (the provider honours ``adjustment=split`` on a known 10:1 split:
    NVDA 2024-06-07 raw/split open ratio ~10, close x volume invariant).  Never starts trading; <= 3
    read-only market-data calls, no broker endpoint."""
    from talonx_v2.sip_adapter import ProviderEntitlementError, ProviderError, default_http_get
    env = os.environ if env is None else env
    rep = ReadinessReport()
    missing = [k for k in contract.required_env if not str(env.get(k, "")).strip()]
    rep.checks["configured"] = {"ok": not missing, "missing": missing}
    if missing:
        rep.problems.append(f"missing credentials: {missing}")
        return rep
    rep.level = "CONFIGURED"
    get = http_get or default_http_get(env["APCA_API_KEY_ID"], env["APCA_API_SECRET_KEY"], contract.timeout_s)
    nowf = now or (lambda: datetime.now(timezone.utc))
    end = (nowf() - timedelta(minutes=SIP_QUERY_LAG_MINUTES + SETTLE_MARGIN_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        recent = get(contract.endpoint, {"symbols": "AAPL", "timeframe": contract.timeframe, "feed": contract.feed,
                                          "adjustment": contract.adjustment,
                                          "start": (nowf().date() - timedelta(days=10)).isoformat(),
                                          "end": end, "limit": "10"})
        rep.level = "REACHABLE"
        bars = (recent.get("bars") or {}).get("AAPL") or []
        ok_bar = bool(bars) and all(float(bars[-1][k]) > 0 for k in ("o", "c")) and float(bars[-1]["v"]) >= 0
        rep.checks["entitled"] = {"ok": ok_bar, "n_bars": len(bars)}
        if not ok_bar:
            rep.problems.append("SIP daily bars returned no usable recent AAPL bar")
            return rep
        rep.level = "ENTITLED"
    except ProviderEntitlementError as exc:
        rep.level = "REACHABLE"
        rep.checks["entitled"] = {"ok": False, "error": str(exc)[:160]}
        rep.problems.append(f"not entitled / credentials rejected: {exc}")
        return rep
    except ProviderError as exc:
        rep.checks["reachable"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
        rep.problems.append(f"provider unreachable/erroring: {exc}")
        return rep
    try:
        def nv(adj):
            b = get(contract.endpoint, {"symbols": "NVDA", "timeframe": "1Day", "feed": contract.feed,
                                        "adjustment": adj, "start": "2024-06-07", "end": "2024-06-08T12:00:00Z",
                                        "limit": "5"})["bars"]["NVDA"][0]
            return float(b["o"]), float(b["c"]), float(b["v"])
        (ro, rc, rv), (so, sc, sv) = nv("raw"), nv(contract.adjustment)
        ok = (9.5 < ro / so < 10.5 and 9.5 < sv / rv < 10.5 and _rel(sc * sv, rc * rv) < 0.01)
        rep.checks["split_only_enforced"] = {"ok": ok, "open_ratio": round(ro / so, 3), "volume_ratio": round(sv / rv, 3)}
        if not ok:
            rep.problems.append("provider did not honour adjustment=split / inverse volume adjustment")
            return rep
        rep.level = "QUALIFIED"
    except (ProviderError, KeyError, IndexError, ValueError, ZeroDivisionError) as exc:
        rep.checks["split_only_enforced"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
        rep.problems.append(f"qualification self-check failed: {exc}")
    return rep


def main(argv: Sequence[str] | None = None) -> int:      # pragma: no cover - CLI, read-only
    from dotenv import load_dotenv
    load_dotenv(".env", override=False)
    rep = check_readiness()
    print(json.dumps(rep.to_dict(), indent=2))
    return 0 if rep.qualified else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
