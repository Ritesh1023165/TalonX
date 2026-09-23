"""
Hard gates (genuine invalidity only) vs an explainable fixed-weight score.

Funnel stages exposed per scan:
UNIVERSE -> DATA_READY -> HARD_REJECTED | SCORED -> WATCH | BULLISH_SETUP | BEARISH_SETUP

A symbol with no pre-market prints is simply not DATA_READY (there is no gap to measure) -- that
is absence of data, not a filter. Everything that IS data-ready and valid gets a score; softer
quality differences never reject, they only lower the score.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.features import Features

WATCH = "WATCH"
BULLISH_SETUP = "BULLISH_SETUP"
BEARISH_SETUP = "BEARISH_SETUP"
SCORED_ONLY = "SCORED"


def hard_gate(f: Features, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> str:
    """'' when valid, else the HARD_REJECTED reason."""
    if not (math.isfinite(f.prev_close) and math.isfinite(f.last_price) and math.isfinite(f.atr20_pct)):
        return "INVALID_NUMERIC"
    if f.prev_close < cfg.min_prev_close:
        return "PRICE_BELOW_MIN"
    if f.adv20_dollars < cfg.min_adv_dollar_20d:
        return "INSUFFICIENT_LIQUIDITY"
    if f.staleness_min > cfg.max_premarket_staleness_min:
        return "STALE_PREMARKET_PRICE"
    if f.staleness_min < -1.0:
        return "INVALID_TIMESTAMP"
    if abs(f.gap_pct) > cfg.max_abs_gap_pct:
        return "IMPLAUSIBLE_GAP"
    return ""


@dataclass(frozen=True)
class Score:
    total: float
    gap: float
    activity: float
    liquidity: float
    catalyst: float
    structure: float
    data_confidence: float
    why: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _clip01(x: float) -> float:
    return 0.0 if not math.isfinite(x) else max(0.0, min(1.0, x))


def score(f: Features, catalyst_strength: str, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> Score:
    w = cfg.weights
    atr = f.atr20_pct if f.atr20_pct > 0 else float("nan")
    gap_mult = abs(f.gap_pct) / atr if math.isfinite(atr) else 0.0
    q_gap = _clip01(gap_mult / cfg.gap_atr_multiple_full)
    q_act = _clip01(f.activity_adv_fraction / cfg.activity_adv_fraction_full)
    lo, hi = math.log10(cfg.liquidity_dollars_zero), math.log10(cfg.liquidity_dollars_full)
    q_liq = _clip01((math.log10(max(f.pm_dollars, 1.0)) - lo) / (hi - lo))
    q_cat = {"STRONG": cfg.catalyst_strong, "OTHER": cfg.catalyst_other}.get(catalyst_strength, 0.0)
    up = f.gap_pct > 0
    beyond = (up and f.range_position == "ABOVE_PREV_HIGH") or (not up and f.range_position == "BELOW_PREV_LOW")
    trend_aligned = f.trend5_pct is not None and ((f.trend5_pct > 0) == up)
    q_struct = 1.0 if beyond else (0.5 if trend_aligned else 0.0)
    q_data = _clip01(f.pm_bars / cfg.data_bars_full)
    parts = dict(gap=q_gap * w.gap, activity=q_act * w.activity, liquidity=q_liq * w.liquidity,
                 catalyst=q_cat * w.catalyst, structure=q_struct * w.structure, data_confidence=q_data * w.data_confidence)
    why = (f"gap {f.gap_pct:+.2f}% = {gap_mult:.1f}x its 20d ATR ({f.atr20_pct:.2f}%)",
           f"pre-market volume {f.pm_volume:,.0f} sh = {f.activity_adv_fraction * 100:.1f}% of 20d ADV",
           f"pre-market dollar volume ${f.pm_dollars:,.0f}",
           f"price {f.range_position.replace('_', ' ').lower()}"
           + (f" by {f.range_distance_pct:.2f}%" if beyond else "")
           + (f"; 5d trend {f.trend5_pct:+.1f}%" if f.trend5_pct is not None else ""),
           f"catalyst {catalyst_strength.lower()}",
           f"{f.pm_bars} pre-market 1-min bars")
    return Score(round(sum(parts.values()), 2), *(round(parts[k], 2) for k in
                 ("gap", "activity", "liquidity", "catalyst", "structure", "data_confidence")), why)


def classify(f: Features, s: Score, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> str:
    g = abs(f.gap_pct)
    if g >= cfg.setup_min_abs_gap_pct and s.total >= cfg.setup_min_score and f.pm_dollars >= cfg.setup_min_premarket_dollars:
        return BULLISH_SETUP if f.gap_pct > 0 else BEARISH_SETUP
    if g >= cfg.watch_min_abs_gap_pct and s.total >= cfg.watch_min_score:
        return WATCH
    return SCORED_ONLY


def needs_catalyst_lookup(f: Features, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> bool:
    """Catalysts are fetched only for symbols whose gap could qualify (bounds SEC requests)."""
    return abs(f.gap_pct) >= cfg.watch_min_abs_gap_pct
