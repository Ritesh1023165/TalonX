"""
Causal shadow replay of one past session through the SAME engine the live canary runs.

At each scheduled scan instant T (identical schedule to live) the engine sees only:
* daily bars for sessions before the scan day;
* 1Min SIP bars COMPLETE by data_as_of(T) = T - 15 min (the live subscription's SIP delay);
* SEC filings whose resolved acceptance <= T (conservative exclusion when unresolvable);
* insider-ledger purchases TalonX had RECEIVED by T.
Regular-session bars are fetched only afterwards, for alerted candidates, as EVALUATION data.
Nothing is routed: replay alerts are recorded with routed=NOT_ROUTED_REPLAY.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from talonx_premarket.alpaca_data import AlpacaData
from talonx_premarket.catalysts import SecSubmissions
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.engine import Engine, ReplaySource
from talonx_premarket.session import scan_schedule, session_day
from talonx_premarket.store import ResearchStore
from talonx_premarket.universe import UniverseMember


def run_replay(*, day: date, universe: list[UniverseMember], data: AlpacaData, sec: SecSubmissions | None,
               ledger_path: str | None, v2_scope: set[str], out_dir: Path,
               cfg: PremarketConfig = PREMARKET_RESEARCH_V1, progress=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if sec is not None:
        sec.ttl_s = float("inf")     # one fetch per CIK; causality is enforced by acceptance <= decision time
    sd = session_day(day, cfg)
    store = ResearchStore(out_dir / "premarket_research_replay.db")
    symbols = sorted(m.symbol for m in universe if m.status == "ELIGIBLE")
    src = ReplaySource(data, symbols, sd, cfg)
    eng = Engine(universe=universe, source=src, store=store, sd=sd, mode="replay", v2_scope=v2_scope, sec=sec,
                 ledger_path=ledger_path, cfg=cfg, route=lambda a: "NOT_ROUTED_REPLAY")
    scans = []
    for t in scan_schedule(day, cfg):
        r = eng.scan(t)
        scans.append(r)
        progress(f"scan {t:%H:%M}Z phase={r.phase} as_of={r.data_as_of_utc[11:16]}Z "
                 f"ready={r.funnel.get('DATA_READY', 0)} scored={r.funnel.get('SCORED', 0)} "
                 f"worthy={r.funnel.get('ALERT_WORTHY', 0)} alerts={len(r.alerts)} ({r.duration_s}s)")
    outcomes = eng.track_outcomes(datetime.now(timezone.utc))
    return {"session": day.isoformat(), "config_version": cfg.version, "config_fingerprint": cfg.fingerprint(),
            "scans": len(scans), "alerts": store.alerts_for(day.isoformat()),
            "candidates": store.candidates_for(day.isoformat()), "outcomes": outcomes,
            "scan_funnels": [{"decision_utc": s.decision_utc, "phase": s.phase, **s.funnel} for s in scans],
            "requests": data.requests, "data_errors": data.errors, "sec_requests": sec.requests if sec else 0,
            "sec_errors": sec.errors if sec else []}
