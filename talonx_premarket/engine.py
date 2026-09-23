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
from talonx_premarket.alpaca_data import AlpacaData, complete_bars_as_of, data_as_of, parse_ts
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
    """Prefetches the whole pre-market window once; each scan sees only bars complete as-of."""

    def __init__(self, data: AlpacaData, symbols: list[str], sd: SessionDay, cfg: PremarketConfig):
        self.data, self.symbols, self.sd, self.cfg = data, symbols, sd, cfg
        self._daily: dict[str, list[dict]] | None = None
        self._pm: dict[str, list[dict]] | None = None

    def daily(self) -> dict[str, list[dict]]:
        if self._daily is None:
            start = datetime.combine(self.sd.prev_session - timedelta(days=45), datetime.min.time(), timezone.utc)
            end = datetime.combine(self.sd.day, datetime.min.time(), timezone.utc)
            self._daily = self.data.bars(self.symbols, timeframe="1Day", start=start, end=end)
        return self._daily

    def premarket(self, as_of: datetime) -> dict[str, list[dict]]:
        if self._pm is None:
            self._pm = self.data.bars(self.symbols, timeframe="1Min", start=self.sd.premarket_start_utc,
                                      end=self.sd.open_utc)
        return {s: complete_bars_as_of(rows, as_of) for s, rows in self._pm.items()}

    def rth(self, symbols: list[str]) -> dict[str, list[dict]]:
        return self.data.bars(symbols, timeframe="1Min", start=self.sd.open_utc, end=self.sd.close_utc)


class LiveSource(ReplaySource):
    """Incremental: each scan fetches only [last_end, as_of) and appends (15-min SIP delay honoured)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pm = {}
        self._fetched_to: datetime | None = None

    def premarket(self, as_of: datetime) -> dict[str, list[dict]]:
        start = self._fetched_to or self.sd.premarket_start_utc
        end = min(as_of, self.sd.open_utc)
        if end > start:
            new = self.data.bars(self.symbols, timeframe="1Min", start=start, end=end)
            for s, rows in new.items():
                self._pm.setdefault(s, []).extend(rows)
            self._fetched_to = end
        return {s: complete_bars_as_of(rows, as_of) for s, rows in self._pm.items()}

    def rth(self, symbols: list[str]) -> dict[str, list[dict]]:
        end = min(data_as_of(datetime.now(timezone.utc), self.cfg), self.sd.close_utc)
        if end <= self.sd.open_utc:
            return {}
        return self.data.bars(symbols, timeframe="1Min", start=self.sd.open_utc, end=end)


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
        self._cat_cache: dict[str, CatalystEvidence] = {}

    # -- catalysts (bounded: gap candidates only) -------------------------------------------
    def _catalyst(self, sym: str, decision: datetime) -> CatalystEvidence:
        m = self.members[sym]
        filings = []
        if self.sec is not None and m.cik:
            subs, observed = self.sec.get(m.cik)
            if subs is not None:
                filings = parse_submissions(subs, observed_at=observed)
        owners = insider_open_market_owners(self.ledger_path, sym, scan_day=self.sd.day, decision_utc=decision) \
            if self.ledger_path else 0
        return evaluate(filings, prev_session=self.sd.prev_session, scan_day=self.sd.day, decision_utc=decision,
                        live=(self.mode == "live"), insider_owners=owners)

    # -- one scan ------------------------------------------------------------------------------
    def scan(self, decision: datetime) -> ScanResult:
        t0 = time.monotonic()
        as_of = data_as_of(decision, self.cfg)
        phase = phase_at(decision, self.cfg)
        daily = self.source.daily()
        pm = self.source.premarket(as_of)
        funnel = Counter(UNIVERSE=self.universe_total, ELIGIBLE=len(self.members))
        rejected = Counter()
        observations: dict[str, tuple[A.Observation, dict | None, dict | None, str]] = {}
        for sym in sorted(self.members):
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
            sc = S.score(feats, cat.strength, self.cfg)
            cls = S.classify(feats, sc, self.cfg)
            funnel["SCORED"] += 1
            if cls != S.SCORED_ONLY:
                funnel[cls] += 1
            observations[sym] = (A.Observation(sym, cls, feats.gap_pct, sc.total, feats.last_price, feats.prev_close),
                                 feats.as_dict(), sc.as_dict(), cat.summary())
        funnel["ALERT_WORTHY"] = funnel[S.WATCH] + funnel[S.BULLISH_SETUP] + funnel[S.BEARISH_SETUP]
        emitted = self._apply_alerts(decision, as_of, phase, observations)
        res = ScanResult(decision.isoformat(), as_of.isoformat(), phase,
                         {**dict(funnel), "hard_reject_reasons": dict(rejected)}, emitted,
                         round(time.monotonic() - t0, 2))
        self.store.add_scan({"scan_id": f"{self.mode}:{decision.isoformat()}", "session_date": self.session,
                             "decision_utc": decision.isoformat(), "data_as_of_utc": as_of.isoformat(), "phase": phase,
                             "mode": self.mode, "config_fingerprint": self.cfg.fingerprint(), "funnel_json": res.funnel,
                             "duration_s": res.duration_s, "requests": getattr(self.source.data, "requests", 0),
                             "errors_json": list(getattr(self.source.data, "errors", []))[-20:]})
        return res

    def _active_candidate(self, sym: str) -> dict | None:
        rows = [c for c in self.store.candidates_for(self.session) if c["symbol"] == sym]
        active = [c for c in rows if c["state"] != A.INVALIDATED]
        return active[-1] if active else None

    def _apply_alerts(self, decision, as_of, phase, observations) -> list[dict]:
        emitted: list[dict] = []
        for sym, (obs, feats, sc, cat) in observations.items():
            prev = self._active_candidate(sym)
            if prev is not None and prev["state"].startswith("SUPPRESSED_"):
                continue                          # capped this session: recorded once, never re-alerted
            if prev is None and obs.gap_pct is not None and obs.classification in A.ACTIVE_STATES:
                closed = self.store.get_candidate(A.candidate_id(self.session, sym, A.family_of(obs.gap_pct)))
                if closed is not None:
                    continue                      # identity invalidated earlier this session: stays closed
            d = A.decide(prev, obs, session_date=self.session, now=decision,
                         new_alerts_so_far=self.store.count_new_alerts(self.session), cfg=self.cfg)
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
            if d.suppressed:
                alert["routed"] = f"SUPPRESSED:{d.suppressed}"
            else:
                alert["routed"] = self.route(alert)
            self.store.add_alert(alert)
            first = prev["first_alert_utc"] if prev else (None if d.suppressed else decision.isoformat())
            self.store.upsert_candidate({
                "candidate_id": d.candidate_id, "session_date": self.session, "symbol": sym, "family": fam,
                "state": d.new_state if not d.suppressed else f"SUPPRESSED_{d.new_state}",
                "first_alert_utc": first, "last_alert_utc": decision.isoformat(),
                "last_alert_score": obs.score, "last_alert_gap": obs.gap_pct,
                "ref_price": prev["ref_price"] if prev else obs.last_price,
                "prev_close": prev["prev_close"] if prev else obs.prev_close,
                "delivered": int(bool(prev and prev["delivered"]) or alert["routed"].startswith("ENQUEUED")),
                "updated_utc": decision.isoformat()})
            emitted.append(alert)
        return emitted

    # -- post-open tracking (evaluation only) -------------------------------------------------
    def track_outcomes(self, now: datetime) -> list[dict]:
        cands = [c for c in self.store.candidates_for(self.session) if c["first_alert_utc"]]
        if not cands:
            return []
        bars = self.source.rth(sorted({c["symbol"] for c in cands}))
        out = []
        for c in cands:
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


def write_status(path: Path, payload: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def in_premarket(t: datetime, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> bool:
    return phase_at(t, cfg) in PREMARKET_PHASES
