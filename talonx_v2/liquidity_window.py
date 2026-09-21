"""
talonx_v2.liquidity_window -- PQ-2B: release-mode wrapper around the FROZEN liquidity gate
=========================================================================================
``talonx_v2.liquidity.evaluate_liquidity`` is part of the fingerprinted STRATEGY files and is left
byte-for-byte untouched.  This plumbing module adds ONE release-mode precondition in front of it:

    the window must be EXACTLY the ``liquidity_lookback_sessions`` XNYS sessions immediately preceding the
    entry session.

Without it a stale or partial provider response (recent sessions missing) would silently make the gate
use an OLDER 20-bar window.  Thresholds ($5 close, $5M median dollar volume) are NOT touched: after the
precondition passes, the unchanged ``evaluate_liquidity`` decides.  Dollar volume is ``close * volume`` of
the provider daily bar (consolidated volume, INVERSELY split-adjusted, so the product is invariant across
a split -- proven on NVDA 2024-06-10 in the PQ-2B tests).
"""
from __future__ import annotations

from datetime import date

from talonx_v2 import calendar as v2cal
from talonx_v2.config import V2Config
from talonx_v2.liquidity import LiquidityResult, evaluate_liquidity


def _d(b) -> date:
    v = b["date"]
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def evaluate_liquidity_checked(bars: list[dict], *, entry_session: date, config: V2Config | None = None,
                               require_contiguous: bool = False) -> LiquidityResult:
    cfg = config or V2Config()
    if require_contiguous:
        n = cfg.liquidity_lookback_sessions
        prior = sorted((b for b in bars if _d(b) < entry_session), key=_d)
        window = prior[-n:]
        if len(window) == n:                       # shorter windows keep the frozen INSUFFICIENT_HISTORY reason
            expected = [v2cal.add_sessions(entry_session, -k) for k in range(n, 0, -1)]
            if [_d(b) for b in window] != expected:
                missing = len(set(expected) - {_d(b) for b in window})
                return LiquidityResult(False, None, float(window[-1]["close"]), len(window),
                                       f"NON_CONTIGUOUS_WINDOW_{missing}_OF_{n}_SESSIONS_MISSING")
    return evaluate_liquidity(bars, entry_session=entry_session, config=cfg)
