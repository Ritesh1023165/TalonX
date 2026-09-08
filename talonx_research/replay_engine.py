"""
Exact chronological runtime replay (Task 115.E / R5).

Drives the REAL frozen production path -- ``talonx_v2.service.V2Service``
(detect_episodes -> staleness guard -> process_episode -> liquidity gate
-> quant_bridge -> brain_bridge -> paper engine -> settle_due_exits) --
one XNYS session at a time, "as if living through time".

Strategy decisions are NOT reimplemented: the engine only supplies
adapters for the clock (as_of), the data transport (historical Form 4 +
local bar CSVs), and a DRY-RUN alert-payload sink.  External transport is
DRY-RUN ONLY -- it can never send a Telegram message.

HARD SAFETY: the engine refuses to open the live prospective ledger
(``v2_lane.db`` in the primary worktree, or any path named ``v2_lane.db``
outside a results/ work area).  Test: talonx_research tests case 12.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

_FORBIDDEN_LEDGER_NAMES = ("v2_lane.db",)
_LIVE_LEDGER_ABS = (Path("C:/workspace/TalonX/v2_lane.db"),
                    Path.home() / ".talonx" / "v2_lane.db")


class LiveLedgerProtectionError(RuntimeError):
    """Raised if a historical replay is pointed at the live prospective ledger."""


def assert_research_ledger_path(db_path: str | Path) -> Path:
    p = Path(db_path).resolve()
    for live in _LIVE_LEDGER_ABS:
        try:
            if p == live.resolve():
                raise LiveLedgerProtectionError(
                    f"historical replay must NEVER open the live ledger {live}")
        except OSError:
            if str(p).lower() == str(live).lower():
                raise LiveLedgerProtectionError(
                    f"historical replay must NEVER open the live ledger {live}")
    if p.name in _FORBIDDEN_LEDGER_NAMES and "results" not in {q.lower() for q in p.parts}:
        raise LiveLedgerProtectionError(
            f"replay ledger '{p}' looks like a live ledger -- put the replay ledger "
            "under a results/ work area with a distinct name (e.g. replay_v2_lane.db)")
    return p


@dataclass
class ReplayResult:
    window: dict[str, str]
    sessions_replayed: int
    fingerprint: str
    activity: dict[str, Any] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    alert_payloads: list[dict] = field(default_factory=list)
    exit_unresolved: list[dict] = field(default_factory=list)
    open_at_end: list[dict] = field(default_factory=list)
    ledger_path: str = ""
    external_sends: int = 0                          # MUST be 0
    portfolio: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def run_chronological_replay(
    *, start: str, end: str, ledger_path: str | Path, bar_dirs: list[str | Path],
    form4_parquet: str | Path | None = None,
    records_provider: Callable[[date], list] | None = None,
    starting_cash: float = 10_000_000.0,
    settle_tail_sessions: int = 20,
    on_session: Callable[[date, Any], None] | None = None,
) -> ReplayResult:
    """`records_provider(as_of)` -> list[PurchaseRecord] visible at `as_of`
    (causal).  If None, the frozen ``form4_source.from_research_parquet``
    is used with a rolling window (production 'parquet' behaviour)."""
    ledger = assert_research_ledger_path(ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if ledger.exists():
        ledger.unlink()                              # a replay always starts fresh

    import exchange_calendars as xc
    from talonx_v2 import form4_source, dispatch_bridge
    from talonx_v2.config import V2Config
    from talonx_v2.service import V2Service
    from talonx_v2.store import V2Store

    cfg = V2Config(db_path=str(ledger), starting_cash_usd=starting_cash)
    cfg.validate_frozen()
    fp = _v2_fingerprint()

    svc = V2Service(config=cfg, bar_dirs=[Path(p) for p in bar_dirs],
                    form4_kind="parquet",
                    form4_parquet=str(form4_parquet) if form4_parquet else None,
                    status_path=str(ledger.parent / "replay_status.json"),
                    live_lookback_days=45)

    if records_provider is not None:
        svc._records = lambda *, as_of: records_provider(as_of)   # noqa: SLF001

    cal = xc.get_calendar("XNYS")
    sessions = [d.date() for d in cal.sessions_in_range(start, end)]
    # a small tail so +10td exits after the last activation can settle
    if sessions:
        tail = [d.date() for d in cal.sessions_window(sessions[-1], settle_tail_sessions)][1:]
        sessions = sessions + tail

    store = V2Store(str(ledger))
    n = 0
    for sess in sessions:
        st = svc.tick(as_of=sess)
        n += 1
        if on_session is not None:
            on_session(sess, st)

    # ---- collect results from the research ledger ----
    trades = store.trades()
    opens = store.open_positions()
    unresolved = store.unresolved_positions()
    all_pos = store.all_positions()

    # DRY-RUN alert payloads: rebuilt from the trade log (no transport ever touched)
    payloads: list[dict] = []
    for t in trades:
        payloads.append({
            "dry_run": True, "transport": "NONE",
            "strategy_version": "INSIDER_BUY_CLUSTER_V2@1", "fingerprint": fp,
            "action": t["action"], "symbol": t["symbol"], "episode_id": t["episode_id"],
            "price": t.get("execution_price"), "shares": t.get("shares"),
            "position_cost": t.get("position_cost"),
            "realized_pnl_usd": t.get("realized_pnl_usd"),
            "executed_at": t.get("executed_at"),
            "portfolio_cash_after": t.get("portfolio_cash_after"),
        })

    disp: dict[str, int] = {}
    for p in all_pos:
        disp[p["status"]] = disp.get(p["status"], 0) + 1
    import sqlite3
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    ep_disp = {r[0]: r[1] for r in con.execute(
        "SELECT disposition, COUNT(*) FROM processed_episodes GROUP BY disposition")}
    con.close()

    res = ReplayResult(
        window={"start": start, "end": end, "settle_tail_sessions": settle_tail_sessions},
        sessions_replayed=n, fingerprint=fp, ledger_path=str(ledger),
        external_sends=0,
        trades=trades,
        alert_payloads=payloads,
        exit_unresolved=[{"symbol": u["symbol"], "episode_id": u["episode_id"]} for u in unresolved],
        open_at_end=[dict(o) for o in opens],
        activity={"processed_episode_dispositions": ep_disp, "position_status_counts": disp,
                  "n_buys": sum(1 for t in trades if t["action"] == "BUY"),
                  "n_sells": sum(1 for t in trades if t["action"] == "SELL")},
        portfolio={"starting_cash": starting_cash, "ending_cash": store.cash(),
                   "n_open_end": len(opens), "n_closed": disp.get("CLOSED", 0),
                   "n_exit_unresolved": disp.get("EXIT_UNRESOLVED", 0)},
    )
    return res


def _v2_fingerprint() -> str:
    from talonx_research.versioning import v2_fingerprint
    return v2_fingerprint()
