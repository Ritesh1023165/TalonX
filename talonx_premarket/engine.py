"""
Scan orchestration shared by LIVE and REPLAY (identical decision path; only the data source and
routing differ).

    universe -> data (SIP 1Min, 15-min delayed) -> features -> hard gates -> score -> classify
             -> alert state machine (dedup) -> RESEARCH route (live) / not routed (replay)
             -> post-open outcome tracking (evaluation only)
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from talonx_premarket import alerts as A
from talonx_premarket import features as F
from talonx_premarket import scoring as S
from talonx_premarket.alpaca_data import AlpacaData, complete_bars_as_of, data_as_of, merge_bars, sorted_bars
from talonx_premarket.catalysts import CatalystEvidence, SecSubmissions, evaluate, insider_open_market_owners, \
    parse_submissions
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.outcomes import measure
from talonx_premarket.session import PREMARKET_PHASES, SessionDay, phase_at, session_day
from talonx_premarket.store import ResearchStore
from talonx_premarket.universe import UniverseMember

logger = logging.getLogger("talonx_premarket.engine")
_SCOPE_RE = re.compile(r"V2 execution scope ENFORCED -- \d+ allowed issuers: (.*)$")


def v2_scope_from_log(path: str | Path) -> set[str]:
    """The V2 39-name execution scope exactly as the companion logged it (read-only)."""
    scope: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SCOPE_RE.search(line)
        if m:
            scope = {s.strip().upper() for s in m.group(1).split(",") if s.strip()}
    return scope


# ---------------------------------------------------------------------------------------------
# data sources
# ---------------------------------------------------------------------------------------------
class ReplaySource:
    """Prefetches the whole pre-market window once; each scan sees only bars complete as-of.

    Completeness contract (both sources): ``daily()`` and ``premarket()`` return ``(bars, incomplete)`` where
    ``incomplete`` is the set of symbols whose provider fetch did NOT complete. Their data is unknown -- never
    treated as "no prints" / "no history". Failed symbols are re-requested on every later call until they
    succeed; nothing partial is ever cached as authoritative."""

    def __init__(self, data: AlpacaData, symbols: list[str], sd: SessionDay, cfg: PremarketConfig):
        self.data, self.symbols, self.sd, self.cfg = data, symbols, sd, cfg
        self._daily: dict[str, dict[str, dict]] = {}
        self._daily_pending: set[str] = set(symbols)
        self._pm: dict[str, dict[str, dict]] = {}
        self._pm_pending: set[str] = set(symbols)
        self.last_fetch: dict = {}

    def _note(self, kind: str, res) -> None:
        self.last_fetch[kind] = {"batches": res.batches, "failed_batches": res.failed_batches,
                                 "retried_batches": res.retried_batches, "failed_symbols": len(res.failed)}

    def daily(self) -> tuple[dict[str, list[dict]], set[str]]:
        if self._daily_pending:
            start = datetime.combine(self.sd.prev_session - timedelta(days=45), datetime.min.time(), timezone.utc)
            end = datetime.combine(self.sd.day, datetime.min.time(), timezone.utc) - timedelta(seconds=1)
            res = self.data.bars_ex(sorted(self._daily_pending), timeframe="1Day", start=start, end=end)
            self._note("daily", res)
            merge_bars(self._daily, res.bars)
            self._daily_pending = set(res.failed)
        return sorted_bars(self._daily), set(self._daily_pending)

    def premarket(self, as_of: datetime) -> tuple[dict[str, list[dict]], set[str]]:
        if self._pm_pending:
            res = self.data.bars_ex(sorted(self._pm_pending), timeframe="1Min", start=self.sd.premarket_start_utc,
                                    end=self.sd.open_utc - timedelta(seconds=1))
            self._note("premarket", res)
            merge_bars(self._pm, res.bars)
            self._pm_pending = set(res.failed)
        return ({s: complete_bars_as_of(rows, as_of) for s, rows in sorted_bars(self._pm).items()},
                set(self._pm_pending))

    def rth(self, symbols: list[str]):
        return self.data.bars_ex(symbols, timeframe="1Min", start=self.sd.open_utc,
                                 end=self.sd.close_utc - timedelta(seconds=1))


class LiveSource(ReplaySource):
    """Incremental with a PER-SYMBOL watermark: each symbol's watermark advances only when its batch succeeded, so
    a failed batch leaves a visible gap that the next scan re-requests (no silent permanent hole). Requests use an
    exclusive end (``end - 1s``; Alpaca's ``end`` is inclusive) so the boundary bar is never fetched twice, and bars
    are keyed by (symbol, t) so any re-fetch replaces rather than duplicates."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._wm: dict[str, datetime] = {s: self.sd.premarket_start_utc for s in self.symbols}

    def premarket(self, as_of: datetime) -> tuple[dict[str, list[dict]], set[str]]:
        end = min(as_of, self.sd.open_utc)
        groups: dict[datetime, list[str]] = {}
        for s in self.symbols:
            if self._wm[s] < end:
                groups.setdefault(self._wm[s], []).append(s)
        agg = {"batches": 0, "failed_batches": 0, "retried_batches": 0, "failed_symbols": 0}
        for start, syms in sorted(groups.items()):
            res = self.data.bars_ex(syms, timeframe="1Min", start=start, end=end - timedelta(seconds=1))
            merge_bars(self._pm, res.bars)
            for s in syms:
                if s not in res.failed:
                    self._wm[s] = end
            for k in agg:
                agg[k] += len(res.failed) if k == "failed_symbols" else getattr(res, k)
        self.last_fetch["premarket"] = agg
        incomplete = {s for s in self.symbols if self._wm[s] < end}
        return ({s: complete_bars_as_of(rows, as_of) for s, rows in sorted_bars(self._pm).items()}, incomplete)

    def rth(self, symbols: list[str]):
        from talonx_premarket.alpaca_data import FetchResult
        end = min(data_as_of(datetime.now(timezone.utc), self.cfg), self.sd.close_utc)
        if end <= self.sd.open_utc:
            return FetchResult()
        return self.data.bars_ex(symbols, timeframe="1Min", start=self.sd.open_utc, end=end - timedelta(seconds=1))


# ---------------------------------------------------------------------------------------------
@dataclass
class ScanResult:
    decision_utc: str
    data_as_of_utc: str
    phase: str
    funnel: dict
    alerts: list[dict] = field(default_factory=list)
    duration_s: float = 0.0


class Engine:
    def __init__(self, *, universe: list[UniverseMember], source: ReplaySource, store: ResearchStore,
                 sd: SessionDay, mode: str, v2_scope: set[str], sec: SecSubmissions | None,
                 ledger_path: str | None, cfg: PremarketConfig = PREMARKET_RESEARCH_V1,
                 route: Callable[[dict], str] | None = None):
        assert mode in ("live", "replay")
        self.cfg, self.sd, self.mode = cfg, sd, mode
        self.members = {m.symbol: m for m in universe if m.status == "ELIGIBLE"}
        self.universe_total = len(universe)
        self.source, self.store, self.sec, self.ledger_path = source, store, sec, ledger_path
        self.v2_scope = v2_scope
        self.route = route or (lambda alert: "NOT_ROUTED")
        self.session = sd.day.isoformat()
        # in-memory mirror of this session's candidate rows (the store stays the durable source of truth)
        self._cands: dict[str, list[dict]] = {}
        for row in store.candidates_for(self.session):
            self._cands.setdefault(row["symbol"], []).append(row)

    # -- catalysts (bounded: gap candidates only) -------------------------------------------
    def _catalyst(self, sym: str, decision: datetime) -> CatalystEvidence:
        """A lookup that could not complete is CATALYST UNKNOWN, never "no catalyst". Unknown contributes 0 score
        points exactly as before (frozen scoring unchanged) but is labelled and counted."""
        m = self.members[sym]
        filings = []
        unknown: list[str] = []
        if self.sec is not None and m.cik:
            subs, observed = self.sec.get(m.cik)
            if subs is not None:
                filings = parse_submissions(subs, observed_at=observed)
            else:
                unknown.append("SEC lookup failed")
        owners = insider_open_market_owners(self.ledger_path, sym, scan_day=self.sd.day, decision_utc=decision) \
            if self.ledger_path else 0
        if owners is None:
            unknown.append("insider ledger unavailable")
            owners = 0
        ev = evaluate(filings, prev_session=self.sd.prev_session, scan_day=self.sd.day, decision_utc=decision,
                      live=(self.mode == "live"), insider_owners=owners)
        if unknown:
            ev.labels.append("catalyst lookup incomplete: " + ", ".join(unknown))
            if ev.strength == "NONE":
                ev.strength = "UNKNOWN"
        return ev

    # -- one scan ------------------------------------------------------------------------------
    def scan(self, decision: datetime) -> ScanResult:
        t0 = time.monotonic()
        as_of = data_as_of(decision, self.cfg)
        phase = phase_at(decision, self.cfg)
        daily, daily_incomplete = self.source.daily()
        pm, pm_incomplete = self.source.premarket(as_of)
        incomplete = (daily_incomplete | pm_incomplete) & set(self.members)
        stale = provider_stale(pm, as_of, self.sd)
        funnel = Counter(UNIVERSE=self.universe_total, ELIGIBLE=len(self.members))
        rejected = Counter()
        observations: dict[str, tuple[A.Observation, dict | None, dict | None, str]] = {}
        cat_unknown = 0
        for sym in sorted(self.members):
            if stale or sym in incomplete:
                # data state unknown: HOLD -- no new candidate, no update, no invalidation for this symbol
                funnel["PROVIDER_INCOMPLETE"] += 1
                why = "PROVIDER_STALE" if stale else "PROVIDER_INCOMPLETE"
                observations[sym] = (A.Observation(sym, f"UNKNOWN:{why}", None, None, None, None), None, None, "")
                continue
            feats, why = F.compute(sym, daily.get(sym, []), pm.get(sym, []), prev_session=self.sd.prev_session,
                                   data_as_of=as_of, cfg=self.cfg)
            if feats is None:
                funnel["NOT_DATA_READY"] += 1
                rejected[why] += 1
                observations[sym] = (A.Observation(sym, f"REJECTED:{why}", None, None, None, None), None, None, "")
                continue
            funnel["DATA_READY"] += 1
            gate = S.hard_gate(feats, self.cfg)
            if gate:
                funnel["HARD_REJECTED"] += 1
                rejected[gate] += 1
                observations[sym] = (A.Observation(sym, f"REJECTED:{gate}", feats.gap_pct, None, feats.last_price,
                                                   feats.prev_close), feats.as_dict(), None, "")
                continue
            cat = self._catalyst(sym, decision) if S.needs_catalyst_lookup(feats, self.cfg) else CatalystEvidence()
            cat_unknown += int(cat.strength == "UNKNOWN")
            sc = S.score(feats, cat.strength, self.cfg)
            cls = S.classify(feats, sc, self.cfg)
            funnel["SCORED"] += 1
            if cls != S.SCORED_ONLY:
                funnel[cls] += 1
            observations[sym] = (A.Observation(sym, cls, feats.gap_pct, sc.total, feats.last_price, feats.prev_close),
                                 feats.as_dict(), sc.as_dict(), cat.summary())
        funnel["ALERT_WORTHY"] = funnel[S.WATCH] + funnel[S.BULLISH_SETUP] + funnel[S.BEARISH_SETUP]
        emitted = self._apply_alerts(decision, as_of, phase, observations)
        data = self.source.data
        provider = {"PROVIDER_COMPLETE": not incomplete and not stale, "PROVIDER_STALE": stale,
                    "DATA_GAPS": len(incomplete), "DATA_GAP_SYMBOLS": sorted(incomplete)[:50],
                    "FETCH": dict(self.source.last_fetch),
                    "FAILED_BATCHES_TOTAL": getattr(data, "failed_batches_total", 0),
                    "RETRIED_BATCHES_TOTAL": getattr(data, "retried_batches_total", 0),
                    "LAST_SUCCESSFUL_PROVIDER_FETCH": (data.last_success_utc.isoformat()
                                                       if getattr(data, "last_success_utc", None) else None),
                    "CATALYST_UNKNOWN": cat_unknown}
        res = ScanResult(decision.isoformat(), as_of.isoformat(), phase,
                         {**dict(funnel), "hard_reject_reasons": dict(rejected), "provider": provider}, emitted,
                         round(time.monotonic() - t0, 2))
        self.store.add_scan({"scan_id": f"{self.mode}:{decision.isoformat()}", "session_date": self.session,
                             "decision_utc": decision.isoformat(), "data_as_of_utc": as_of.isoformat(), "phase": phase,
                             "mode": self.mode, "config_fingerprint": self.cfg.fingerprint(), "funnel_json": res.funnel,
                             "duration_s": res.duration_s, "requests": getattr(self.source.data, "requests", 0),
                             "errors_json": list(getattr(self.source.data, "errors", []))[-20:]})
        return res

    def _active_candidate(self, sym: str) -> dict | None:
        active = [c for c in self._cands.get(sym, []) if c["state"] != A.INVALIDATED]
        return active[-1] if active else None

    def _new_alerts_so_far(self) -> int:
        return sum(1 for rows in self._cands.values() for c in rows if c["first_alert_utc"])

    def _mirror_candidate(self, row: dict) -> None:
        rows = self._cands.setdefault(row["symbol"], [])
        for i, c in enumerate(rows):
            if c["candidate_id"] == row["candidate_id"]:
                rows[i] = {**c, **row}
                return
        rows.append(dict(row))

    def _apply_alerts(self, decision, as_of, phase, observations) -> list[dict]:
        emitted: list[dict] = []
        # Highest score first, so the per-session new-alert cap keeps the strongest candidates (ties: symbol).
        ordered = sorted(observations.items(),
                         key=lambda kv: (-(kv[1][0].score if kv[1][0].score is not None else float("-inf")), kv[0]))
        for sym, (obs, feats, sc, cat) in ordered:
            prev = self._active_candidate(sym)
            if prev is not None and prev["state"].startswith("SUPPRESSED_"):
                continue                          # capped this session: recorded once, never re-alerted
            if prev is None and obs.gap_pct is not None and obs.classification in A.ACTIVE_STATES:
                cid = A.candidate_id(self.session, sym, A.family_of(obs.gap_pct))
                if any(c["candidate_id"] == cid for c in self._cands.get(sym, [])):
                    continue                      # identity invalidated earlier this session: stays closed
            d = A.decide(prev, obs, session_date=self.session, now=decision,
                         new_alerts_so_far=self._new_alerts_so_far(), cfg=self.cfg)
            if d is None:
                continue
            name = self.members[sym].name
            text = A.render(d.alert_type, symbol=sym, name=name, feats=feats, score=sc, catalyst=cat or "none found",
                            phase=phase, data_as_of_utc=as_of.isoformat(),
                            reason=d.reason + ("; " + "; ".join(sc["why"][:3]) if sc else ""),
                            inside_v2_scope=sym in self.v2_scope)
            fam = prev["family"] if prev else A.family_of(obs.gap_pct)
            alert = {"alert_id": f"{d.candidate_id}:{d.alert_type}:{decision.isoformat()}",
                     "candidate_id": d.candidate_id, "session_date": self.session, "symbol": sym,
                     "alert_type": d.alert_type, "decision_utc": decision.isoformat(),
                     "data_as_of_utc": as_of.isoformat(), "score": obs.score, "gap_pct": obs.gap_pct,
                     "ref_price": obs.last_price, "text": text, "features_json": feats or {}, "score_json": sc or {},
                     "catalyst": cat, "mode": self.mode}
            alert["routed"] = f"SUPPRESSED:{d.suppressed}" if d.suppressed else PENDING_ROUTE
            first = prev["first_alert_utc"] if prev else (None if d.suppressed else decision.isoformat())
            cand = {
                "candidate_id": d.candidate_id, "session_date": self.session, "symbol": sym, "family": fam,
                "state": d.new_state if not d.suppressed else f"SUPPRESSED_{d.new_state}",
                "first_alert_utc": first, "last_alert_utc": decision.isoformat(),
                "last_alert_score": obs.score, "last_alert_gap": obs.gap_pct,
                "ref_price": prev["ref_price"] if prev else obs.last_price,
                "prev_close": prev["prev_close"] if prev else obs.prev_close,
                "delivered": int(bool(prev and prev.get("delivered"))),   # 1 only once an alert was actually SENT
                "updated_utc": decision.isoformat()}
            # durable FIRST (alert + candidate in one transaction), THEN route: a crash between the two can only
            # leave a PENDING_ROUTE alert that is re-routed idempotently on restart -- never a second NEW alert.
            self.store.persist_decision(alert, cand)
            self._mirror_candidate(cand)
            if not d.suppressed:
                alert["routed"] = self.route(alert)
                self.store.set_routed(alert["alert_id"], alert["routed"])
            emitted.append(alert)
        return emitted

    def resume_pending_routes(self) -> int:
        """Re-route alerts persisted but not yet routed (crash window). Routing is idempotent (event_id)."""
        n = 0
        for a in self.store.alerts_for(self.session):
            if a["routed"] == PENDING_ROUTE:
                self.store.set_routed(a["alert_id"], self.route(a))
                n += 1
        return n

    # -- post-open tracking (evaluation only) -------------------------------------------------
    def track_outcomes(self, now: datetime) -> list[dict]:
        cands = [c for c in self.store.candidates_for(self.session) if c["first_alert_utc"]]
        if not cands:
            return []
        fetched = self.source.rth(sorted({c["symbol"] for c in cands}))
        bars = fetched.bars
        out = []
        for c in cands:
            if c["symbol"] in fetched.failed:
                continue                      # provider failure: keep the last persisted outcome, retry next cycle
            m = measure(family=c["family"], ref_price=c["ref_price"], prev_close=c["prev_close"],
                        rth_bars=bars.get(c["symbol"], []), open_utc=self.sd.open_utc, close_utc=self.sd.close_utc,
                        confirm_min=self.cfg.confirm_horizon_min)
            row = {"candidate_id": c["candidate_id"], "session_date": self.session, "symbol": c["symbol"],
                   "family": c["family"], "ref_price": c["ref_price"], "status": m["status"],
                   **{k: m.get(k) for k in ("open_px", "px_30m", "px_1h", "close_px", "mfe_pct", "mae_pct",
                                            "open_ret_pct", "ret_30m_pct", "ret_1h_pct", "close_ret_pct")},
                   "updated_utc": now.isoformat(), "detail_json": {"session_complete": m.get("session_complete")}}
            self.store.upsert_outcome(row)
            out.append(row)
        return out


PENDING_ROUTE = "PENDING_ROUTE"
# Universe-wide data-state guard (not a scoring rule): once the pre-market has been open for this long, at least one
# of ~5.6k symbols prints every few minutes. If the newest complete bar anywhere is older than this, the provider is
# lagging and every symbol is HELD as unknown (no candidate created, updated or invalidated from stale data).
PROVIDER_STALE_AFTER = timedelta(minutes=15)


def provider_stale(pm: dict[str, list[dict]], as_of: datetime, sd: SessionDay) -> bool:
    if as_of - sd.premarket_start_utc < PROVIDER_STALE_AFTER:
        return False
    newest = max((rows[-1]["t"] for rows in pm.values() if rows), default=None)
    if newest is None:
        return True
    from talonx_premarket.alpaca_data import parse_ts
    return as_of - (parse_ts(newest) + timedelta(minutes=1)) > PROVIDER_STALE_AFTER


def write_status(path: Path, payload: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def in_premarket(t: datetime, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> bool:
    return phase_at(t, cfg) in PREMARKET_PHASES
