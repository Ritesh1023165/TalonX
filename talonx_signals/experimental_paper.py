"""Task 99A S4/S5 -- experimental paper execution.

Reuses talonx_paper's PURE engine functions + PaperTradingStore, pointed at an
ISOLATED database (``experimental_paper.db``). LONG-ONLY, paper-only:

  - ``open_long``  -- BUY, only when flat. Never opens a short.
  - ``close_long`` -- SELL, only when an experimental LONG exists. "SELL"
    means EXIT; a flat symbol returns None (no short is ever created).
  - ``check_exits`` / ``flatten_all`` -- stop/target and EOD.

Every trade dict carries ``profile="EXPERIMENTAL_RELAXED_V1"``, a deterministic
``X…`` ``trade_id``, and ``admitted_by`` (which relaxed threshold let it in vs
frozen control). Emits nothing to CONTROL/PIV channels or the CONTROL paper DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from talonx_paper.engine import apply_spread, calculate_buy, calculate_sell_pnl, check_stop_take
from talonx_paper.schemas import AlertAction
from talonx_paper.store import PaperTradingStore

from talonx_signals.schemas import PROFILE_EXPERIMENTAL, make_trade_id
from talonx_signals.telemetry import classify_admission

_EXIT_ACTION = {
    "signal_exit": AlertAction.CONFIRMED_BEARISH,
    "stop_loss": AlertAction.CONFIRMED_BEARISH,
    "target_exit": AlertAction.CONFIRMED_BEARISH,
    "eod_flatten": AlertAction.EOD_FLAT_LIQUIDATION,
}


@dataclass
class ExperimentalPaperEngine:
    db_path: str | Path
    allocation_usd: float = 2500.0
    spread_bps: float = 5.0
    initial_cash: float = 100_000.0
    stop_loss_pct: float = 0.005
    take_profit_pct: float = 0.01
    _store: PaperTradingStore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        Path(str(self.db_path)).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._store = PaperTradingStore(
            self.db_path,
            default_initial_balance=self.initial_cash,
            default_trade_allocation_usd=self.allocation_usd,
        )

    def close(self) -> None:
        try:
            self._store._conn.close()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    @property
    def store(self) -> PaperTradingStore:
        return self._store

    def open_positions(self) -> list[dict]:
        return self._store.get_open_positions()

    def _cash(self) -> float:
        row = self._store._conn.execute(  # noqa: SLF001
            "SELECT current_cash FROM portfolio_state WHERE id = 1"
        ).fetchone()
        return float(row[0]) if row else 0.0

    # ------------------------------------------------------------------
    def open_long(
        self,
        symbol: str,
        price: float,
        *,
        stop: float | None = None,
        target: float | None = None,
        now: datetime | None = None,
        setup: str | None = None,
        setup_score: int | None = None,
        risk_reward_ratio: float | None = None,
        atr_pct: float | None = None,
        source_alert_id: str = "",
    ) -> dict | None:
        now = now or datetime.now(timezone.utc)
        symbol = symbol.upper()
        if self._store.get_position(symbol) is not None:
            return None  # already long -> no pyramiding, and NEVER a short
        fill = apply_spread(price, self.spread_bps, "BUY")
        buy = calculate_buy(self._cash(), self.allocation_usd, fill)
        if buy is None:
            return None
        shares, cost = buy
        if shares <= 0:
            return None
        self._store.execute_buy(symbol, shares, fill, cost, now, stop_price=stop, target_price=target)
        admitted = classify_admission(
            atr_pct=atr_pct, confluence_score=setup_score, risk_reward_ratio=risk_reward_ratio,
        )
        return {
            "trade_id": make_trade_id(symbol=symbol, profile=PROFILE_EXPERIMENTAL, side="BUY",
                                      opened_at=now, source_alert_id=source_alert_id),
            "symbol": symbol, "profile": PROFILE_EXPERIMENTAL, "side": "BUY",
            "entry": fill, "stop": stop, "target": target, "quantity": shares,
            "admitted_by": admitted, "setup": setup, "setup_score": setup_score,
            "risk_reward_ratio": risk_reward_ratio, "atr_pct": atr_pct,
            "opened_at": now.isoformat(), "est_entry_cost": abs(fill - price) * shares,
        }

    def close_long(
        self, symbol: str, price: float, *, exit_reason: str = "signal_exit",
        now: datetime | None = None,
    ) -> dict | None:
        now = now or datetime.now(timezone.utc)
        symbol = symbol.upper()
        pos = self._store.get_position(symbol)
        if pos is None or pos["shares"] <= 0:
            return None  # nothing to exit -> a SELL never opens a short
        shares = pos["shares"]
        entry = pos["entry_price"]
        fill = apply_spread(price, self.spread_bps, "SELL")
        gross_pnl, _pct = calculate_sell_pnl(shares, entry, price)
        net_pnl, _npct = calculate_sell_pnl(shares, entry, fill)
        est_costs = abs(gross_pnl - net_pnl)
        action = _EXIT_ACTION.get(exit_reason, AlertAction.CONFIRMED_BEARISH)
        self._store.execute_sell(symbol, fill, now, action)
        r_mult = None
        if pos.get("stop_price") not in (None, entry):
            risk = entry - pos["stop_price"]
            if risk > 0:
                r_mult = (fill - entry) / risk
        return {
            "trade_id": make_trade_id(symbol=symbol, profile=PROFILE_EXPERIMENTAL, side="SELL",
                                      opened_at=now, source_alert_id=exit_reason),
            "symbol": symbol, "profile": PROFILE_EXPERIMENTAL, "side": "SELL",
            "entry": entry, "exit": fill, "quantity": shares, "exit_reason": exit_reason,
            "gross_pnl": gross_pnl, "est_costs": est_costs, "net_pnl": net_pnl,
            "r_multiple": r_mult, "closed_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    def check_exits(self, symbol: str, price: float, *, now: datetime | None = None) -> dict | None:
        pos = self._store.get_position(symbol.upper())
        if pos is None:
            return None
        hit = check_stop_take(
            pos["entry_price"], price, self.stop_loss_pct, self.take_profit_pct,
            stop_price=pos.get("stop_price"), target_price=pos.get("target_price"),
        )
        if hit == "STOP_LOSS":
            return self.close_long(symbol, price, exit_reason="stop_loss", now=now)
        if hit == "TAKE_PROFIT":
            return self.close_long(symbol, price, exit_reason="target_exit", now=now)
        return None

    def flatten_all(self, prices: dict[str, float], *, now: datetime | None = None) -> list[dict]:
        out = []
        for pos in list(self._store.get_open_positions()):
            sym = pos["ticker"]
            px = prices.get(sym, pos["entry_price"])
            t = self.close_long(sym, px, exit_reason="eod_flatten", now=now)
            if t:
                out.append(t)
        return out
