"""
talonx_v2.liquidity -- causal trailing-20-session liquidity gate (Phase 3/6)
=========================================================================
FROZEN eligibility rule (Task 109 v2_strategy_contract.md, Eligibility 1):

  issuer passes if, using ONLY sessions STRICTLY BEFORE the eligible entry
  session, the trailing-20-session MEDIAN dollar volume >= $5,000,000
  AND the last close >= $5.

"Dollar volume" for a session = close * volume.  No look-ahead: the entry
session's own bar is never used.  (The S&P 500 / 400 membership branch of
the contract is an OR -- when a PIT membership list is available it also
passes; the liquidity screen is the always-available operational
substitute and is what this module computes.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from talonx_v2.config import V2Config


@dataclass(frozen=True)
class LiquidityResult:
    ok: bool
    median_dollar_volume: float | None
    last_close: float | None
    n_sessions_used: int
    reason: str


def evaluate_liquidity(
    bars: list[dict],
    *,
    entry_session: date,
    config: V2Config | None = None,
) -> LiquidityResult:
    """``bars`` = list of {'date','close','volume'} (any order).  Only
    sessions with date < entry_session are considered; the most recent
    ``liquidity_lookback_sessions`` of those are used."""
    cfg = config or V2Config()

    def _d(b) -> date:
        v = b["date"]
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])

    prior = sorted((b for b in bars if _d(b) < entry_session), key=_d)
    if not prior:
        return LiquidityResult(False, None, None, 0, "NO_PRIOR_BARS")

    window = prior[-cfg.liquidity_lookback_sessions:]
    if len(window) < cfg.liquidity_lookback_sessions:
        return LiquidityResult(
            False, None, float(window[-1]["close"]), len(window),
            f"INSUFFICIENT_HISTORY_{len(window)}_OF_{cfg.liquidity_lookback_sessions}",
        )

    dvs = sorted(float(b["close"]) * float(b["volume"]) for b in window)
    m = len(dvs)
    median_dv = dvs[m // 2] if m % 2 else (dvs[m // 2 - 1] + dvs[m // 2]) / 2.0
    last_close = float(window[-1]["close"])

    if last_close < cfg.liquidity_min_close:
        return LiquidityResult(False, median_dv, last_close, len(window),
                               f"CLOSE_{last_close:.2f}_LT_{cfg.liquidity_min_close}")
    if median_dv < cfg.liquidity_min_median_dollar_volume:
        return LiquidityResult(False, median_dv, last_close, len(window),
                               f"MEDIAN_DV_{median_dv:.0f}_LT_{cfg.liquidity_min_median_dollar_volume:.0f}")
    return LiquidityResult(True, median_dv, last_close, len(window), "PASS")
