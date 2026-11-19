"""
Horizon evaluators (REQ S14-06): INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM.

Each evaluator is its own process (``component evaluator:<HORIZON>``), consumes the SAME durable candidate_events
stream through its OWN cursor and is the single writer of its own ``evaluator_<horizon>.db`` -- so one evaluator's
bug/restart never touches another evaluator, discovery or notification.

Vocabulary: WATCH / BULLISH / BEARISH / MATERIAL_UPDATE / INVALIDATED are research states and are recorded as such.
BUY / SELL are ACTIONABLE strategy states: an evaluator may only emit them when an AUTHORIZED strategy for its
horizon says so. No research-lane strategy is authorized (``AUTHORIZED_STRATEGIES`` is empty), so these evaluators
never emit BUY/SELL -- they record ``action_state=NONE`` with the reason. They never create paper orders.

SHORT_TERM additionally reports the existing specialised multi-session strategy (frozen V2, INSIDER_BUY_CLUSTER_V2@1)
READ-ONLY from its status file; V2 is not rewritten into, fed by, or evaluated through this engine.
LONG_TERM is registered but NOT_IMPLEMENTED: it keeps its cursor current and reports that state honestly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from talonx_opportunity.db import REPO_ROOT, connect, iso, root_dir
from talonx_opportunity.store import OpportunityStore, opportunity_db

HORIZONS = ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM")
BUY, SELL = "BUY", "SELL"
AUTHORIZED_STRATEGIES: dict[str, tuple[str, ...]] = {h: () for h in HORIZONS}
PHASE_SCOPE = {"INTRADAY": ("PREMARKET", "REGULAR"), "SAME_DAY": ("OVERNIGHT", "PREMARKET", "REGULAR", "AFTER_HOURS"),
               "SHORT_TERM": ("AFTER_HOURS", "OVERNIGHT"), "LONG_TERM": ()}
IMPLEMENTED = {"INTRADAY": True, "SAME_DAY": True, "SHORT_TERM": True, "LONG_TERM": False}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, last_seq INTEGER, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS records (
    event_id TEXT PRIMARY KEY, seq INTEGER, horizon TEXT, candidate_id TEXT, window_id TEXT, symbol TEXT,
    at_utc TEXT, phase TEXT, research_state TEXT, event_type TEXT, action_state TEXT, execution_eligibility TEXT,
    strategy TEXT, reason TEXT, recorded_utc TEXT);
"""


def evaluator_db(root, horizon: str) -> Path:
    return root_dir(root) / f"evaluator_{horizon.lower()}.db"


def v2_status(path: str | None = None) -> dict:
    """Frozen V2 companion identity, read-only from its status file (no talonx_v2 import)."""
    p = Path(path or os.environ.get("TALONX_V2_STATUS_PATH") or (REPO_ROOT / "v2_release_rc1_status.json"))
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "path": str(p)}
    return {"available": True, "strategy_version": s.get("strategy_version"), "campaign_id": s.get("campaign_id"),
            "execution_mode": s.get("execution_mode"), "heartbeat_utc": s.get("heartbeat_utc"),
            "price_provider_contract": s.get("price_provider_contract"), "data_state": s.get("data_state")}


class HorizonEvaluator:
    def __init__(self, horizon: str, *, root=None, batch: int = 2000):
        if horizon not in HORIZONS:
            raise ValueError(horizon)
        self.h, self.root, self.batch = horizon, root, batch
        self.con = connect(evaluator_db(root, horizon), schema=SCHEMA)
        self.last: dict = {}

    def cursor(self) -> int:
        r = self.con.execute("SELECT last_seq FROM cursor WHERE name='events'").fetchone()
        return int(r["last_seq"]) if r else 0

    def evaluate(self, ev: dict) -> dict | None:
        if not IMPLEMENTED[self.h] or ev["phase"] not in PHASE_SCOPE[self.h]:
            return None
        strategies = AUTHORIZED_STRATEGIES[self.h]
        action, strategy = "NONE", None
        reason = ("NO_AUTHORIZED_STRATEGY: research states never become BUY/SELL without an authorizing strategy"
                  if not strategies else "authorized strategy did not act")
        return {"event_id": ev["event_id"], "seq": ev["seq"], "horizon": self.h, "candidate_id": ev["candidate_id"],
                "window_id": ev["window_id"], "symbol": ev["symbol"], "at_utc": ev["at_utc"], "phase": ev["phase"],
                "research_state": ev.get("classification"), "event_type": ev["event_type"], "action_state": action,
                "execution_eligibility": "NOT_EXECUTABLE_RESEARCH_LANE", "strategy": strategy, "reason": reason,
                "recorded_utc": iso()}

    def tick(self) -> float:
        n = 0
        if opportunity_db(self.root).exists():
            opp = OpportunityStore(self.root, readonly=True)
            try:
                evs = opp.events_after(self.cursor(), limit=self.batch)
            finally:
                opp.close()
            with self.con:
                for ev in evs:
                    rec = self.evaluate(ev)
                    if rec is not None:
                        assert rec["action_state"] not in (BUY, SELL) or rec["strategy"], "BUY/SELL needs a strategy"
                        self.con.execute(f"INSERT OR IGNORE INTO records ({','.join(rec)}) VALUES "
                                         f"({','.join('?' * len(rec))})", list(rec.values()))
                        n += 1
                if evs:
                    self.con.execute("INSERT OR REPLACE INTO cursor VALUES ('events', ?, ?)", (evs[-1]["seq"], iso()))
        self.last = {"horizon": self.h, "implemented": IMPLEMENTED[self.h], "cursor": self.cursor(), "recorded": n,
                     "state": "RUNNING" if IMPLEMENTED[self.h] else "IDLE_NOT_IMPLEMENTED",
                     "authorized_strategies": list(AUTHORIZED_STRATEGIES[self.h])}
        if self.h == "SHORT_TERM":
            self.last["external_strategy_v2"] = v2_status()
        return 30.0

    def detail(self) -> dict:
        return dict(self.last)


def main(horizon: str) -> int:
    from talonx_opportunity.runtime import run_component
    root = os.environ.get("TALONX_OPP_ROOT")
    ev = HorizonEvaluator(horizon, root=root)
    run_component(f"evaluator:{horizon}", tick=ev.tick, root=root, detail=ev.detail,
                  config_fps={"authorized_strategies": ",".join(AUTHORIZED_STRATEGIES[horizon]) or "none",
                              "phase_scope": ",".join(PHASE_SCOPE[horizon])})
    return 0
