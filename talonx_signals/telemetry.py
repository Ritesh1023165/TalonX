"""Task 99A S5 -- forward-outcome telemetry.

For every directional alert AND every experimental paper trade, record a
forward-observation row and fill +30m / +60m / EOD / +1D returns, MFE and MAE
as prices arrive. +1D legitimately stays PENDING past today's close -- a
next-session backfill pass completes it.

Directional-accuracy semantics:
  BULLISH -> positive forward return is favourable
  BEARISH -> negative forward return is favourable   (directional_hit)
BEARISH NEVER produces a simulated short P&L. Directional accuracy and trade
profitability are separate metrics.

Own SQLite file (``forward_outcomes.db``), additive, idempotent on ``obs_id``.
Never touches CONTROL / PIV / dispatch / paper databases.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HORIZONS = ("30m", "60m", "eod", "1d")
_STATUS_ORDER = ("PENDING_30M", "PENDING_60M", "PENDING_EOD", "PENDING_1D", "COMPLETE")

_DDL = """
CREATE TABLE IF NOT EXISTS forward_observations (
    obs_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,              -- 'directional' | 'trade'
    source_id TEXT NOT NULL,         -- alert_id or trade_id
    symbol TEXT NOT NULL,
    direction TEXT,
    profile TEXT NOT NULL,
    setup TEXT,
    setup_score INTEGER,
    horizon TEXT,                    -- headline horizon label for display
    catalyst TEXT,
    trade_gate_status TEXT,
    trade_gate_reject_reason TEXT,
    admitted_by TEXT,
    alert_ts TEXT NOT NULL,
    reference_price REAL NOT NULL,
    r_30m REAL, r_60m REAL, r_eod REAL, r_1d REAL,
    hit_30m INTEGER, hit_60m INTEGER, hit_eod INTEGER, hit_1d INTEGER,
    mfe REAL, mae REAL,
    -- trade-only economics
    entry REAL, stop REAL, target REAL, quantity REAL,
    exit REAL, exit_reason TEXT,
    gross_pnl REAL, est_costs REAL, net_pnl REAL, r_multiple REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fo_symbol ON forward_observations(symbol);
CREATE INDEX IF NOT EXISTS idx_fo_status ON forward_observations(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(ts: Any) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if getattr(ts, "tzinfo", None) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# admission attribution (S5.5)
# ---------------------------------------------------------------------------

FROZEN_MIN_ATR_PCT = 0.25
FROZEN_CONFLUENCE_MIN = 2
FROZEN_MIN_RR = 1.5


def classify_admission(
    *, atr_pct: float | None, confluence_score: int | None, risk_reward_ratio: float | None,
) -> str:
    """Which relaxed threshold(s) let EXPERIMENTAL_RELAXED_V1 admit a candidate
    that the frozen control would have rejected."""
    reasons: list[str] = []
    if atr_pct is not None and atr_pct < FROZEN_MIN_ATR_PCT:
        reasons.append("relaxed_volatility")
    if confluence_score is not None and confluence_score < FROZEN_CONFLUENCE_MIN:
        reasons.append("relaxed_confluence")
    if risk_reward_ratio is not None and risk_reward_ratio < FROZEN_MIN_RR:
        reasons.append("relaxed_rr")
    if not reasons:
        return "would_also_pass_control"
    if len(reasons) > 1:
        return "multiple:" + "+".join(r.split("_", 1)[1] for r in reasons)
    return reasons[0]


@dataclass(frozen=True)
class HorizonWindow:
    m30: timedelta = timedelta(minutes=30)
    m60: timedelta = timedelta(minutes=60)


class ForwardOutcomeStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_DDL)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _get(self, obs_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM forward_observations WHERE obs_id=?", (obs_id,)
            ).fetchone()
        return dict(r) if r else None

    def upsert_new(self, row: dict) -> bool:
        cols = ", ".join(row)
        ph = ", ".join("?" * len(row))
        with self._lock:
            cur = self._conn.execute(
                f"INSERT OR IGNORE INTO forward_observations ({cols}) VALUES ({ph})",
                tuple(row.values()),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def _update(self, obs_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE forward_observations SET {sets} WHERE obs_id=?",
                (*fields.values(), obs_id),
            )
            self._conn.commit()

    def all_rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM forward_observations ORDER BY alert_ts"
            ).fetchall()]

    def pending_backfill(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM forward_observations WHERE status != 'COMPLETE'"
            ).fetchall()]


class ForwardOutcomeRecorder:
    """Idempotent. ``open_*`` creates the row; ``on_price`` advances MFE/MAE and
    resolves a horizon the moment its window has elapsed; ``resolve_eod`` /
    ``resolve_next_day`` fill the session-boundary horizons explicitly."""

    def __init__(self, store: ForwardOutcomeStore, *, windows: HorizonWindow | None = None):
        self.store = store
        self.windows = windows or HorizonWindow()

    # ---- open ----
    def open_from_directional(self, alert: Any) -> str:
        d = alert if isinstance(alert, dict) else alert.model_dump(mode="json")
        obs_id = "FO-" + str(d["alert_id"])
        ev = d.get("evidence") or {}
        row = {
            "obs_id": obs_id, "kind": "directional", "source_id": d["alert_id"],
            "symbol": d["symbol"], "direction": str(d["direction"]).split(".")[-1],
            "profile": d["profile"], "setup": d.get("setup_type"), "setup_score": d.get("setup_score"),
            "horizon": "multi", "catalyst": (ev.get("nearby_catalyst") if isinstance(ev, dict) else None),
            "trade_gate_status": str(d.get("trade_gate_status")),
            "trade_gate_reject_reason": d.get("trade_gate_reject_reason"),
            "admitted_by": None,
            "alert_ts": str(d["bar_timestamp"]), "reference_price": float(d["price"]),
            "mfe": 0.0, "mae": 0.0,
            "status": "PENDING_30M", "created_at": _now(), "updated_at": _now(),
        }
        self.store.upsert_new(row)
        return obs_id

    def open_from_trade(self, trade: dict, *, atr_pct: float | None = None) -> str:
        obs_id = "FO-" + str(trade["trade_id"])
        admitted = trade.get("admitted_by") or classify_admission(
            atr_pct=atr_pct,
            confluence_score=trade.get("setup_score"),
            risk_reward_ratio=trade.get("risk_reward_ratio"),
        )
        row = {
            "obs_id": obs_id, "kind": "trade", "source_id": trade["trade_id"],
            "symbol": trade["symbol"], "direction": "BULLISH",
            "profile": trade.get("profile", "EXPERIMENTAL_RELAXED_V1"),
            "setup": trade.get("setup"), "setup_score": trade.get("setup_score"),
            "horizon": "trade", "catalyst": trade.get("catalyst"),
            "trade_gate_status": "WOULD_PASS", "trade_gate_reject_reason": None,
            "admitted_by": admitted,
            "alert_ts": str(trade["opened_at"]), "reference_price": float(trade["entry"]),
            "entry": float(trade["entry"]), "stop": trade.get("stop"), "target": trade.get("target"),
            "quantity": trade.get("quantity"),
            "mfe": 0.0, "mae": 0.0,
            "status": "PENDING_30M", "created_at": _now(), "updated_at": _now(),
        }
        self.store.upsert_new(row)
        return obs_id

    # ---- fill ----
    def on_price(self, obs_id: str, ts: datetime, price: float) -> None:
        row = self.store._get(obs_id)
        if row is None or row["status"] == "COMPLETE":
            return
        t0 = _as_utc(row["alert_ts"])
        ref = row["reference_price"]
        if ts <= t0 or not ref:
            return
        ret = (price - ref) / ref * 100.0
        updates: dict[str, Any] = {}
        # running extremes (in % terms)
        mfe = max(row.get("mfe") or 0.0, ret)
        mae = min(row.get("mae") or 0.0, ret)
        updates["mfe"], updates["mae"] = mfe, mae
        elapsed = ts - t0
        if elapsed >= self.windows.m30 and row["r_30m"] is None:
            updates.update(self._resolve_field(row, "30m", ret))
        if elapsed >= self.windows.m60 and row["r_60m"] is None:
            updates.update(self._resolve_field(row, "60m", ret))
        updates["status"] = self._advance_status(row, updates)
        self.store._update(obs_id, **updates)

    def resolve_eod(self, obs_id: str, eod_price: float) -> None:
        self._resolve_boundary(obs_id, "eod", eod_price)

    def resolve_next_day(self, obs_id: str, next_day_price: float) -> None:
        self._resolve_boundary(obs_id, "1d", next_day_price)

    def _resolve_boundary(self, obs_id: str, horizon: str, price: float) -> None:
        row = self.store._get(obs_id)
        if row is None:
            return
        field = f"r_{horizon}"
        if row.get(field) is not None:
            return  # idempotent
        ref = row["reference_price"]
        ret = (price - ref) / ref * 100.0 if ref else 0.0
        updates = self._resolve_field(row, horizon, ret)
        updates["mfe"] = max(row.get("mfe") or 0.0, ret)
        updates["mae"] = min(row.get("mae") or 0.0, ret)
        updates["status"] = self._advance_status(row, updates)
        self.store._update(obs_id, **updates)

    def _resolve_field(self, row: dict, horizon: str, ret: float) -> dict:
        favourable = ret > 0 if row["direction"] == "BULLISH" else ret < 0
        return {f"r_{horizon}": ret, f"hit_{horizon}": int(favourable)}

    def _advance_status(self, row: dict, updates: dict) -> str:
        """EOD and +1D are the two horizons that decide whether a row is
        settled. +30m/+60m are best-effort intraday snapshots -- a live
        session fills them from price ticks, but a missed tick must never
        strand a row as permanently pending."""
        def val(f):
            return updates.get(f, row.get(f))
        if val("r_eod") is not None and val("r_1d") is not None:
            return "COMPLETE"
        if val("r_eod") is not None:
            return "PENDING_1D"
        if val("r_60m") is not None:
            return "PENDING_EOD"
        if val("r_30m") is not None:
            return "PENDING_60M"
        return "PENDING_30M"

    # ---- trade close economics ----
    def close_trade(
        self, obs_id: str, *, exit_price: float, exit_reason: str,
        gross_pnl: float, est_costs: float, net_pnl: float, r_multiple: float | None,
        mfe: float | None = None, mae: float | None = None,
    ) -> None:
        row = self.store._get(obs_id)
        if row is None:
            return
        fields: dict[str, Any] = {
            "exit": exit_price, "exit_reason": exit_reason,
            "gross_pnl": gross_pnl, "est_costs": est_costs, "net_pnl": net_pnl,
            "r_multiple": r_multiple,
        }
        if mfe is not None:
            fields["mfe"] = mfe
        if mae is not None:
            fields["mae"] = mae
        self.store._update(obs_id, **fields)
