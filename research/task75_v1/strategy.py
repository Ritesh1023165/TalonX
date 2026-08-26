"""Task75A -- frozen CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1
signal + entry + exit, canonical-calendar-safe. SHORT_ONLY: this module
implements ONLY the top-20%-rank SHORT leg (the rejected LONG mirror and
the rejected MOMENTUM hypothesis are NOT implemented here at all -- see
research/task74_alpha_discovery_v2/ for the historical discovery code,
preserved unmodified as evidence).

Causality/session invariants (see tests/test_task75_v1_*.py):
  - Day0/Day1/exit are positions in SPY's own canonical calendar, never a
    symbol's own positionally-available row sequence
  - a symbol missing any required canonical session is REJECTED, never
    shifted to a later available row and never filled/synthesized
  - the 3-day return and the rank are computed using only information
    complete as of Day0 close
  - entry is the canonical NEXT session's open; exit is the close of the
    3rd canonical session counting the entry day as day 1
  - no stop is applied inside this module -- see risk_policy.json
"""
from __future__ import annotations

import pandas as pd

from research.task75_v1 import contracts as C
from research.task75_v1.calendar import build_daily_table, canonical_calendar

LEDGER_COLUMNS = [
    "symbol", "decision_day", "market_adjusted_return_pct", "cross_sectional_rank_pct",
    "direction", "entry_day", "entry_timestamp", "entry_price",
    "exit_day", "exit_timestamp", "exit_price", "gross_return_pct",
    "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _has_all_sessions(day_map: dict, days: list) -> bool:
    return all(d in day_map for d in days)


def evaluate(bars_with_market: pd.DataFrame) -> pd.DataFrame:
    daily = build_daily_table(bars_with_market)
    calendar = canonical_calendar(daily)
    n_cal = len(calendar)
    if n_cal == 0:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    spy_by_day = {row["trading_day"]: row for _, row in daily[daily["symbol"] == C.MARKET_SYMBOL].iterrows()}
    stock_daily = daily[daily["symbol"] != C.MARKET_SYMBOL]
    by_symbol_day = {sym: {r["trading_day"]: r for _, r in g.iterrows()} for sym, g in stock_daily.groupby("symbol")}

    rows: list[dict] = []
    for idx0 in range(C.LOOKBACK_TRADING_DAYS, n_cal):
        day0 = calendar[idx0]
        day_lb = calendar[idx0 - C.LOOKBACK_TRADING_DAYS]
        lookback_span = calendar[idx0 - C.LOOKBACK_TRADING_DAYS: idx0 + 1]

        spy0, spy_lb = spy_by_day.get(day0), spy_by_day.get(day_lb)
        if spy0 is None or spy_lb is None or spy_lb["close"] == 0:
            spy_ret = None
        else:
            spy_ret = (spy0["close"] - spy_lb["close"]) / spy_lb["close"] * 100.0

        entry_idx = idx0 + 1
        exit_idx = idx0 + C.EXIT_HORIZON_TRADING_DAYS
        has_entry = entry_idx < n_cal
        has_exit = exit_idx < n_cal
        entry_day = calendar[entry_idx] if has_entry else None
        exit_day = calendar[exit_idx] if has_exit else None

        # --- pass 1: compute feature + rank for every symbol with valid data this Day0 ---
        candidates: dict[str, float] = {}
        for symbol in C.UNIVERSE:
            day_map = by_symbol_day.get(symbol, {})
            if spy_ret is None or not _has_all_sessions(day_map, lookback_span):
                continue
            row0, row_lb = day_map[day0], day_map[day_lb]
            if row_lb["close"] == 0:
                continue
            stock_ret = (row0["close"] - row_lb["close"]) / row_lb["close"] * 100.0
            candidates[symbol] = stock_ret - spy_ret

        if len(candidates) < C.MIN_CROSS_SECTIONAL_BREADTH:
            for symbol in C.UNIVERSE:
                reason = "DATA_NOT_READY" if symbol not in candidates else "INSUFFICIENT_CROSS_SECTIONAL_BREADTH"
                rows.append(_row(symbol=symbol, decision_day=day0,
                                  market_adjusted_return_pct=candidates.get(symbol),
                                  data_ready=False, rejection_reason=reason))
            continue

        ranks = pd.Series(candidates).rank(pct=True, method=C.RANK_METHOD)

        for symbol in C.UNIVERSE:
            if symbol not in candidates:
                rows.append(_row(symbol=symbol, decision_day=day0, data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue
            rank = float(ranks[symbol])
            base = dict(symbol=symbol, decision_day=day0, market_adjusted_return_pct=candidates[symbol], cross_sectional_rank_pct=rank)

            if rank < C.UPPER_PERCENTILE:
                rows.append(_row(**base, data_ready=False, rejection_reason="THRESHOLD_NOT_MET"))
                continue
            if not has_entry:
                rows.append(_row(**base, direction="SHORT", data_ready=False, rejection_reason="SYMBOL_MISSING_REQUIRED_SESSION" if n_cal else "SPY_CALENDAR_NOT_ESTABLISHED"))
                continue
            if not has_exit:
                rows.append(_row(**base, direction="SHORT", entry_day=entry_day, data_ready=False, rejection_reason="SPY_CALENDAR_NOT_ESTABLISHED"))
                continue

            required_days = calendar[entry_idx:exit_idx + 1]
            day_map = by_symbol_day.get(symbol, {})
            if not _has_all_sessions(day_map, required_days):
                rows.append(_row(**base, direction="SHORT", entry_day=entry_day, exit_day=exit_day,
                                  data_ready=False, rejection_reason="SYMBOL_MISSING_REQUIRED_SESSION"))
                continue

            entry_row, exit_row = day_map[entry_day], day_map[exit_day]
            entry_price, exit_price = float(entry_row["open"]), float(exit_row["close"])
            gross = -(exit_price - entry_price) / entry_price * 100.0  # SHORT: profit when price falls
            rows.append(_row(**base, direction="SHORT", entry_day=entry_day, entry_timestamp=entry_row["open_timestamp"],
                              entry_price=entry_price, exit_day=exit_day, exit_timestamp=exit_row["close_timestamp"],
                              exit_price=exit_price, gross_return_pct=gross, data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
