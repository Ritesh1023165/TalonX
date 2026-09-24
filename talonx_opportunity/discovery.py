"""
DISCOVERY component -- continuous, phase-aware, UNCAPPED (REQ S14-01, S14-02). Single writer of opportunity.db.

Each evaluation (cadence per phase; PREMARKET uses V1's EARLY/CORE/NEAR_OPEN cadence exactly):

  phase + window  -> effective provider capability (fail closed: DATA_UNAVAILABLE, nothing else stops)
  market.db       -> window-to-date aggregates as-of the ingestion watermark (15-min delayed SIP)
  V1 pipeline     -> features (aggregate-equivalent) -> hard gates -> catalyst -> score -> classify   (FROZEN V1)
  lifecycle       -> talonx_premarket.alerts.decide(..., new_alerts_so_far=0)   i.e. V1 transitions, NEVER capped
  persist         -> every valid candidate + every transition, with provenance, regardless of Telegram

Phase crossings never mint a new identity: the active identity for (symbol, family) is continued across
04:00 / 09:30 / 16:00 ET and carried across the 20:00 ET window roll (REFERENCE_ROLLED, lineage kept).
Data state UNKNOWN (incomplete provider batch, lagging ingestion) HOLDS every affected identity: no candidate is
created, updated or invalidated from unknown data.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from talonx_opportunity import capabilities as C
from talonx_opportunity.aggregates import features_from_aggregate
from talonx_opportunity.config import CONTINUOUS_RESEARCH_V1, ContinuousResearchConfig
from talonx_opportunity.db import iso, j, unj, utcnow
from talonx_opportunity.ingestion import read_state
from talonx_opportunity.phases import AFTER_HOURS, CLOSED, OVERNIGHT, PREMARKET, REGULAR, phase_at, trading_window
from talonx_opportunity.store import ACTIVE, CLOSED_STATES, VOCAB, OpportunityStore
from talonx_premarket import alerts as A
from talonx_premarket import scoring as S
from talonx_premarket.alpaca_data import data_as_of
from talonx_premarket.catalysts import CatalystEvidence, evaluate, insider_open_market_owners, parse_submissions

PROVIDER_LAG_LIMIT = timedelta(minutes=15)   # ingestion as-of older than this vs the SIP as-of -> PROVIDER_STALE


def _horizons(phase: str) -> list[str]:
    if phase in (PREMARKET, REGULAR):
        return ["INTRADAY", "SAME_DAY"]
    if phase in (AFTER_HOURS, OVERNIGHT):
        return ["SAME_DAY", "SHORT_TERM"]
    return ["SAME_DAY"]


def cadence_s(phase: str, now: datetime, cfg: ContinuousResearchConfig = CONTINUOUS_RESEARCH_V1) -> int:
    if phase == PREMARKET:
        from talonx_premarket.session import phase_at as v1_phase, scan_interval_s
        return scan_interval_s(v1_phase(now, cfg.base), cfg.base)
    return {REGULAR: cfg.regular_scan_interval_s, AFTER_HOURS: cfg.after_hours_scan_interval_s}.get(
        phase, cfg.unavailable_poll_s)


def seconds_to_next_boundary(now: datetime, interval: int) -> float:
    e = now.timestamp()
    return max(1.0, interval - (e % interval))


class Discovery:
    def __init__(self, *, root=None, cfg: ContinuousResearchConfig = CONTINUOUS_RESEARCH_V1, sec=None,
                 ledger_path: str | None = None, v2_scope: set[str] | None = None, clock=None, state_reader=None):
        self.root, self.cfg = root, cfg
        self.store = OpportunityStore(root)
        self.sec = sec
        self.ledger_path = ledger_path
        self.v2_scope = v2_scope or set()
        self.clock = clock or utcnow
        self.state_reader = state_reader or (lambda wid: read_state(root, wid))
        self.last_summary: dict = {}

    # -- catalyst (identical to V1 Engine._catalyst, parameterised by the window) --------------------------------
    def _catalyst(self, member: dict, sym: str, decision: datetime, w) -> CatalystEvidence:
        filings, unknown = [], []
        if self.sec is not None and member.get("cik"):
            subs, observed = self.sec.get(member["cik"])
            if subs is not None:
                filings = parse_submissions(subs, observed_at=observed)
            else:
                unknown.append("SEC lookup failed")
        owners = insider_open_market_owners(self.ledger_path, sym, scan_day=w.session, decision_utc=decision) \
            if self.ledger_path else 0
        if owners is None:
            unknown.append("insider ledger unavailable")
            owners = 0
        ev = evaluate(filings, prev_session=w.reference_session, scan_day=w.session, decision_utc=decision,
                      live=True, insider_owners=owners)
        if unknown:
            ev.labels.append("catalyst lookup incomplete: " + ", ".join(unknown))
            if ev.strength == "NONE":
                ev.strength = "UNKNOWN"
        return ev

    # -- one evaluation --------------------------------------------------------------------------------------------
    def tick(self) -> float:
        now = self.clock()
        phase, w = phase_at(now)
        if w is None or phase == CLOSED:
            self._expire_and_roll(now, None)
            self._scan_row(now, None, CLOSED, "CLOSED", C.STATIC_CAPABILITIES[CLOSED].as_dict(), {}, None, 0.0)
            self.store.commit()
            return float(self.cfg.unavailable_poll_s)
        t0 = time.monotonic()
        st = self.state_reader(w.window_id)
        cap = C.effective_capability(phase, st["probes"].get(phase))
        if not cap.usable_for_discovery:
            self._expire_and_roll(now, w)
            self._scan_row(now, w, phase, "DATA_UNAVAILABLE", cap.as_dict(), {}, None, time.monotonic() - t0)
            self.store.commit()
            return float(self.cfg.unavailable_poll_s)
        ing = st["state"]
        sip_as_of = data_as_of(now, self.cfg.base)
        if ing is None or datetime.fromisoformat(ing["as_of_utc"]) < sip_as_of - PROVIDER_LAG_LIMIT:
            # ingestion lagging / not yet run: data state UNKNOWN -> hold everything (no create/update/invalidate)
            self._scan_row(now, w, phase, "PROVIDER_STALE", cap.as_dict(),
                           {"ingestion_as_of": ing["as_of_utc"] if ing else None}, None, time.monotonic() - t0)
            self.store.commit()
            return 60.0
        as_of = datetime.fromisoformat(ing["as_of_utc"])
        incomplete = set(unj(ing["incomplete_json"], []))
        self._expire_and_roll(now, w)
        members = {m["symbol"]: m for m in st["members"] if m.get("status") == "ELIGIBLE"}
        funnel = {"UNIVERSE": len(st["members"]), "ELIGIBLE": len(members), "DATA_READY": 0, "HARD_REJECTED": 0,
                  "NOT_DATA_READY": 0, "PROVIDER_INCOMPLETE": 0, "SCORED": 0, "WATCH": 0, "BULLISH_SETUP": 0,
                  "BEARISH_SETUP": 0, "CATALYST_UNKNOWN": 0, "HELD_STALE_NON_INVALIDATING_PHASE": 0}
        rejected: dict[str, int] = {}
        obs: dict[str, tuple] = {}
        for sym in sorted(members):
            if sym in incomplete:
                funnel["PROVIDER_INCOMPLETE"] += 1
                obs[sym] = (A.Observation(sym, "UNKNOWN:PROVIDER_INCOMPLETE", None, None, None, None), None, None, "")
                continue
            feats, why = features_from_aggregate(sym, st["daily"].get(sym, []), st["aggs"].get(sym),
                                                 prev_session=w.reference_session, data_as_of=as_of, cfg=self.cfg.base)
            if feats is None:
                funnel["NOT_DATA_READY"] += 1
                rejected[why] = rejected.get(why, 0) + 1
                obs[sym] = (A.Observation(sym, f"REJECTED:{why}", None, None, None, None), None, None, "")
                continue
            funnel["DATA_READY"] += 1
            gate = S.hard_gate(feats, self.cfg.base)
            if gate:
                funnel["HARD_REJECTED"] += 1
                rejected[gate] = rejected.get(gate, 0) + 1
                obs[sym] = (A.Observation(sym, f"REJECTED:{gate}", feats.gap_pct, None, feats.last_price,
                                          feats.prev_close), feats.as_dict(), None, "")
                continue
            cat = self._catalyst(members[sym], sym, now, w) if S.needs_catalyst_lookup(feats, self.cfg.base) \
                else CatalystEvidence()
            funnel["CATALYST_UNKNOWN"] += int(cat.strength == "UNKNOWN")
            sc = S.score(feats, cat.strength, self.cfg.base)
            cls = S.classify(feats, sc, self.cfg.base)
            funnel["SCORED"] += 1
            if cls != S.SCORED_ONLY:
                funnel[cls] += 1
            obs[sym] = (A.Observation(sym, cls, feats.gap_pct, sc.total, feats.last_price, feats.prev_close),
                        feats.as_dict(), sc.as_dict(), cat.summary())
        funnel["ALERT_WORTHY"] = funnel["WATCH"] + funnel["BULLISH_SETUP"] + funnel["BEARISH_SETUP"]
        funnel["hard_reject_reasons"] = rejected
        prov = {"provider": cap.provider, "feed": cap.feed, "delay_minutes": cap.delay_minutes,
                "adjustment": cap.adjustment, "data_as_of_utc": as_of.isoformat(), "phase": phase,
                "ingestion_cycle_utc": ing["cycle_utc"], "provider_complete": not incomplete,
                "incomplete_symbols": len(incomplete)}
        n_ev = self._apply_lifecycle(now, as_of, phase, w, obs, members, funnel, prov)
        funnel["EVENTS"] = n_ev
        funnel["ACTIVE_CANDIDATES"] = len(self.store.active_candidates())
        self._scan_row(now, w, phase, "SCANNED", cap.as_dict(), funnel, as_of, time.monotonic() - t0)
        self._latest(now, w, phase, obs)
        self.store.commit()
        self.last_summary = {"phase": phase, "window_id": w.window_id, "as_of": as_of.isoformat(),
                             "worthy": funnel["ALERT_WORTHY"], "events": n_ev,
                             "active": funnel["ACTIVE_CANDIDATES"]}
        return seconds_to_next_boundary(self.clock(), cadence_s(phase, now, self.cfg))

    # -- lifecycle -------------------------------------------------------------------------------------------------
    def _apply_lifecycle(self, now, as_of, phase, w, obs, members, funnel, prov) -> int:
        n = 0
        active = {}
        for c in self.store.active_candidates():
            active[c["symbol"]] = c                      # latest active identity per symbol
        order = sorted(obs.items(), key=lambda kv: (-(kv[1][0].score if kv[1][0].score is not None
                                                      else float("-inf")), kv[0]))
        for sym, (o, feats, sc, cat) in order:
            prev = active.get(sym)
            if prev is not None:
                if o.classification.startswith(("REJECTED:STALE", "REJECTED:NO_PREMARKET")) \
                        and phase not in self.cfg.stale_invalidates_phases:
                    funnel["HELD_STALE_NON_INVALIDATING_PHASE"] += 1
                    continue
                if prev["reference_session"] != w.reference_session.isoformat() and o.gap_pct is not None:
                    self._event(now, as_of, phase, w, prev, "REFERENCE_ROLLED", prev["state"], prev["state"], o, feats,
                                sc, cat, prov, f"window roll: reference {prev['reference_session']} -> "
                                f"{w.reference_session}")
                    prev = {**prev, "reference_session": w.reference_session.isoformat(), "prev_close": o.prev_close}
                    self.store.upsert_candidate({"candidate_id": prev["candidate_id"],
                                                 "reference_session": prev["reference_session"],
                                                 "prev_close": o.prev_close})
                    n += 1
            else:
                if o.gap_pct is None or o.classification not in ACTIVE:
                    continue
                cid = A.candidate_id(w.window_id, sym, A.family_of(o.gap_pct))
                if self.store.candidate(cid) is not None:
                    continue                             # identity closed earlier in this window stays closed
            dprev = None if prev is None else {
                "candidate_id": prev["candidate_id"], "state": prev["state"], "family": prev["family"],
                "last_alert_utc": prev["last_event_utc"], "last_alert_score": prev["last_event_score"],
                "last_alert_gap": prev["last_event_gap"]}
            d = A.decide(dprev, o, session_date=w.window_id, now=now, new_alerts_so_far=0, cfg=self.cfg.base)
            if prev is not None and o.classification in ACTIVE and o.gap_pct is not None:
                self.store.upsert_candidate({"candidate_id": prev["candidate_id"], "last_observed_utc": iso(now),
                                             "last_phase": phase, "last_score": o.score, "last_gap_pct": o.gap_pct,
                                             "last_active_window_id": w.window_id,
                                             "max_score": max(prev["max_score"] or 0, o.score or 0)})
            if d is None:
                continue
            assert not d.suppressed, "detection must never be capped"
            if prev is None:
                etype = "NEW"
                row = {"candidate_id": d.candidate_id, "window_id": w.window_id, "symbol": sym,
                       "family": A.family_of(o.gap_pct), "direction": "BULLISH" if o.gap_pct > 0 else "BEARISH",
                       "state": d.new_state, "classification": VOCAB[d.new_state], "first_seen_utc": iso(now),
                       "first_seen_phase": phase, "first_data_as_of_utc": as_of.isoformat(),
                       "last_updated_utc": iso(now), "last_phase": phase, "last_observed_utc": iso(now),
                       "last_active_window_id": w.window_id, "last_event_utc": iso(now),
                       "last_event_score": o.score, "last_event_gap": o.gap_pct, "first_score": o.score,
                       "last_score": o.score, "max_score": o.score, "first_gap_pct": o.gap_pct,
                       "last_gap_pct": o.gap_pct, "ref_price": o.last_price, "prev_close": o.prev_close,
                       "reference_session": w.reference_session.isoformat(), "horizons_json": j(_horizons(phase)),
                       "catalyst": cat or "none found",
                       "liquidity_json": j({k: (feats or {}).get(k) for k in ("pm_dollars", "pm_volume",
                                                                                "adv20_dollars", "activity_adv_fraction")}),
                       "provenance_json": j(prov), "config_version": self.cfg.version,
                       "config_fp": self.cfg.fingerprint(), "in_v2_scope": int(sym in self.v2_scope),
                       "closed_reason": None}
                self.store.upsert_candidate(row)
                prev = row
            else:
                etype = {"MATERIAL_UPDATE": "MATERIAL_UPDATE", "INVALIDATED": "INVALIDATED"}.get(d.alert_type, "UPGRADE")
                upd = {"candidate_id": prev["candidate_id"], "state": d.new_state,
                       "classification": VOCAB.get(d.new_state, d.new_state), "last_updated_utc": iso(now),
                       "last_phase": phase, "last_event_utc": iso(now)}
                if o.score is not None:
                    upd.update(last_event_score=o.score, last_score=o.score)
                if o.gap_pct is not None:
                    upd.update(last_event_gap=o.gap_pct, last_gap_pct=o.gap_pct)
                if d.new_state == "INVALIDATED":
                    upd["closed_reason"] = d.reason
                self.store.upsert_candidate(upd)
            self._event(now, as_of, phase, w, prev, etype, prev["state"] if etype != "NEW" else None, d.new_state,
                        o, feats, sc, cat, prov, d.reason)
            n += 1
        return n

    def _event(self, now, as_of, phase, w, cand, etype, frm, to, o, feats, sc, cat, prov, reason) -> None:
        self.store.add_event({
            "event_id": f"{cand['candidate_id']}:{etype}:{iso(now)}", "candidate_id": cand["candidate_id"],
            "window_id": w.window_id, "symbol": cand["symbol"], "at_utc": iso(now),
            "data_as_of_utc": as_of.isoformat() if as_of else None, "phase": phase, "event_type": etype,
            "from_state": frm, "to_state": to, "classification": VOCAB.get(to, to),
            "score": o.score if o else None, "gap_pct": o.gap_pct if o else None,
            "last_price": o.last_price if o else None, "reason": reason, "features_json": j(feats or {}),
            "score_json": j(sc or {}), "catalyst": cat or None, "provenance_json": j(prov or {}),
            "config_fp": self.cfg.fingerprint()})

    def _expire_and_roll(self, now, w) -> None:
        """EXPIRED: an identity not observed as alert-worthy during the current or the previous trading window."""
        if w is None:
            return
        keep = {w.window_id, w.reference_session.isoformat()}
        for c in self.store.active_candidates():
            if c["last_active_window_id"] not in keep:
                self.store.upsert_candidate({"candidate_id": c["candidate_id"], "state": "EXPIRED",
                                             "classification": "EXPIRED", "last_updated_utc": iso(now),
                                             "closed_reason": f"not alert-worthy for {self.cfg.expire_after_idle_windows}"
                                                              f" full trading window(s)"})
                self._event(now, None, w.phase_at(now), w, c, "EXPIRED", c["state"], "EXPIRED", None, None, None,
                            None, None, "idle expiry (lifecycle bookkeeping; never notified)")

    def _scan_row(self, now, w, phase, state, cap, funnel, as_of, dur) -> None:
        self.store.add_scan({"scan_id": f"{iso(now)}", "window_id": w.window_id if w else None,
                             "decision_utc": iso(now), "data_as_of_utc": as_of.isoformat() if as_of else None,
                             "phase": phase, "state": state, "capability": cap, "funnel": funnel,
                             "duration_s": round(dur, 2), "config_fp": self.cfg.fingerprint()})

    def _latest(self, now, w, phase, obs) -> None:
        rows, near = [], []
        for sym, (o, *_rest) in obs.items():
            rows.append((w.window_id, sym, iso(now), phase, o.classification, o.gap_pct, o.score))
            if o.gap_pct is not None and abs(o.gap_pct) >= self.cfg.base.watch_min_abs_gap_pct \
                    and o.classification not in ACTIVE:
                near.append((w.window_id, iso(now), sym, phase, o.classification, o.gap_pct, o.score))
        self.store.con.executemany("INSERT OR REPLACE INTO symbol_latest VALUES (?,?,?,?,?,?,?)", rows)
        self.store.con.executemany("INSERT OR IGNORE INTO near_misses VALUES (?,?,?,?,?,?,?)", near)

    def detail(self) -> dict:
        return dict(self.last_summary)


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    from talonx_premarket import __main__ as M
    M._env()
    root = os.environ.get("TALONX_OPP_ROOT")
    sec = M._sec()
    scope = M._v2_scope(None)
    disc = Discovery(root=root, sec=sec, ledger_path=str(M.DEFAULT_LEDGER), v2_scope=scope)
    run_component("discovery", tick=disc.tick, root=root, detail=disc.detail,
                  config_fps={"CONTINUOUS_RESEARCH": CONTINUOUS_RESEARCH_V1.fingerprint(),
                              "PREMARKET_RESEARCH_V1": CONTINUOUS_RESEARCH_V1.base.fingerprint()})
    return 0
