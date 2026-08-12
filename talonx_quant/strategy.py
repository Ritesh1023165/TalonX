"""
talonx_quant.strategy
-------------------------
Evaluates an IndicatorSnapshot against configured thresholds and emits
zero or more QuantSignals. A single bar update can trigger multiple
independent signals (e.g. a MACD cross AND an RSI/volume setup on the
same bar) -- each is evaluated and emitted separately rather than
collapsed into one, since a downstream consumer may care about only one
signal type.

Crossover detection (MACD, MA) needs both a current and previous value --
a crossover is defined by the relationship flipping sign between the two
most recent bars, not just the current value's absolute position.

Analyst-review additions (see config.py's own docstrings for the full
rationale -- a live paper-trading review found a 0.33 profit factor and
3 consecutive SMCI losses driving 93% of session losses):
  - Every check below now ALSO requires this bar's own true range to
    clear atr_move_multiplier x ATR(14) -- a signal firing on a routine,
    average-sized bar (not a genuine directional move) was implicated in
    the reviewed whipsaw losses.
  - confluence_score (0-3) and risk_reward_ratio are bar-level
    properties (not signal-type-specific), computed once and attached to
    every signal that fires on that bar -- consumer.py filters on both
    before a signal is even allowed to start the per-ticker cooldown.
"""
from __future__ import annotations

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import IndicatorSnapshot
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


def evaluate_signals(
    ticker: str, snapshot: IndicatorSnapshot, config: QuantConfig
) -> list[QuantSignal]:
    signals: list[QuantSignal] = []
    confluence_score = _confluence_score(snapshot, config)
    risk_reward_ratio = _risk_reward_ratio(snapshot, config)

    _check_rsi_volume_setup(ticker, snapshot, config, signals, confluence_score, risk_reward_ratio)
    _check_macd_crossover(ticker, snapshot, config, signals, confluence_score, risk_reward_ratio)
    _check_ma_crossover(ticker, snapshot, config, signals, confluence_score, risk_reward_ratio)

    return signals


def _clears_atr_move(s: IndicatorSnapshot, config: QuantConfig) -> bool:
    """This bar's own true range (max(high-low, |high-prev_close|,
    |low-prev_close|) -- see indicators.py) must be at least
    atr_move_multiplier x ATR(14) to count as a real directional move,
    not routine noise on a high-beta name. Missing/not-yet-warmed-up ATR
    data fails OPEN (returns False) -- same "insufficient data -> no
    signal" posture every other check in this module already takes."""
    if s.atr is None or s.bar_true_range is None or s.atr <= 0:
        return False
    return s.bar_true_range >= config.atr_move_multiplier * s.atr


def _macd_crossed_this_bar(s: IndicatorSnapshot) -> bool:
    """True if EITHER direction of MACD/signal-line cross happened on
    this bar -- used both by _check_macd_crossover (to decide whether to
    emit its own signal) and by _confluence_score (to count a MACD cross
    as a conviction factor for ANY signal firing this bar, e.g. an RSI
    setup with a coincident MACD cross scores higher than one without)."""
    if None in (s.macd, s.macd_signal_line, s.macd_prev, s.macd_signal_line_prev):
        return False
    bullish = s.macd_prev <= s.macd_signal_line_prev and s.macd > s.macd_signal_line
    bearish = s.macd_prev >= s.macd_signal_line_prev and s.macd < s.macd_signal_line
    return bullish or bearish


def _confluence_score(s: IndicatorSnapshot, config: QuantConfig) -> int:
    """0-3: +1 each for a MACD cross firing THIS bar, RSI currently
    sitting in its extreme zone (< rsi_oversold or > rsi_overbought,
    regardless of whether it JUST crossed there), and volume surge above
    threshold. A bar-level conviction score, not signal-type-specific --
    every signal firing on this bar carries the SAME score."""
    score = 0
    if _macd_crossed_this_bar(s):
        score += 1
    if s.rsi is not None and (s.rsi < config.rsi_oversold or s.rsi > config.rsi_overbought):
        score += 1
    if s.volume_surge_ratio is not None and s.volume_surge_ratio > config.volume_surge_ratio_threshold:
        score += 1
    return score


def _risk_reward_ratio(s: IndicatorSnapshot, config: QuantConfig) -> float | None:
    """(atr_reward_multiplier x ATR) / (assumed_stop_loss_pct x price).
    The risk side is deliberately NOT another ATR multiple -- pairing two
    multiples of the SAME ATR value (e.g. 1.5x / 0.75x) always produces
    the same constant ratio regardless of any market data, which would
    make a "minimum risk/reward" filter a permanent no-op. Pairing the
    ATR-scaled reward against talonx_paper's actual stop-loss distance
    instead makes the ratio vary with each ticker's own ATR-to-price
    relationship -- see config.py's assumed_stop_loss_pct docstring for
    why that's a locally-mirrored constant, not a live cross-module read."""
    if s.atr is None or not s.price:
        return None
    risk = config.assumed_stop_loss_pct * s.price
    if risk <= 0:
        return None
    reward = config.atr_reward_multiplier * s.atr
    return reward / risk


def _check_rsi_volume_setup(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal],
    confluence_score: int, risk_reward_ratio: float | None,
) -> None:
    """
    Edge-triggered, like the MACD/MA crossover checks below: fires only on
    the bar RSI first crosses the threshold, not on every subsequent bar it
    remains oversold/overbought. Without this, a stock sitting under RSI 30
    for 5 consecutive bars would fire 5 signals instead of 1 -- a major
    source of the alert chatter this module was tuned to reduce.
    """
    if s.rsi is None or s.rsi_prev is None or s.volume_surge_ratio is None:
        return
    if not _clears_atr_move(s, config):
        return

    crossed_oversold = s.rsi_prev >= config.rsi_oversold and s.rsi < config.rsi_oversold
    if crossed_oversold and s.volume_surge_ratio > config.volume_surge_ratio_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalDirection.BULLISH,
            f"RSI {s.rsi:.1f} crossed into oversold (< {config.rsi_oversold:.0f}) with "
            f"{s.volume_surge_ratio:.1f}x volume surge (> {config.volume_surge_ratio_threshold:.1f}x)",
            confluence_score, risk_reward_ratio,
        ))
        return  # a bar crosses one direction at most; skip the overbought check

    crossed_overbought = s.rsi_prev <= config.rsi_overbought and s.rsi > config.rsi_overbought
    if crossed_overbought and s.volume_surge_ratio > config.volume_surge_ratio_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERBOUGHT_VOLUME_SURGE, SignalDirection.BEARISH,
            f"RSI {s.rsi:.1f} crossed into overbought (> {config.rsi_overbought:.0f}) with "
            f"{s.volume_surge_ratio:.1f}x volume surge (> {config.volume_surge_ratio_threshold:.1f}x)",
            confluence_score, risk_reward_ratio,
        ))


def _check_macd_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal],
    confluence_score: int, risk_reward_ratio: float | None,
) -> None:
    if None in (s.macd, s.macd_signal_line, s.macd_prev, s.macd_signal_line_prev):
        return
    if not _clears_atr_move(s, config):
        return

    was_below = s.macd_prev <= s.macd_signal_line_prev
    now_above = s.macd > s.macd_signal_line
    if was_below and now_above:
        signals.append(_build_signal(
            ticker, s, SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH,
            f"MACD ({s.macd:.3f}) crossed above signal line ({s.macd_signal_line:.3f})",
            confluence_score, risk_reward_ratio,
        ))
        return  # a bar crosses one direction at most; skip the bearish check

    was_above = s.macd_prev >= s.macd_signal_line_prev
    now_below = s.macd < s.macd_signal_line
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MACD_BEARISH_CROSS, SignalDirection.BEARISH,
            f"MACD ({s.macd:.3f}) crossed below signal line ({s.macd_signal_line:.3f})",
            confluence_score, risk_reward_ratio,
        ))


def _check_ma_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal],
    confluence_score: int, risk_reward_ratio: float | None,
) -> None:
    """
    Hysteresis-gated, on top of the was_below/now_above transition check:
    a technical crossover on paper (fast nudges from <= to > slow) isn't
    necessarily a real signal if the resulting gap is a few cents on a
    $500 stock. Requires the CURRENT spread to be at least
    config.min_ma_spread_pct of price before a crossover counts, so a
    $0.03 drift on MSFT (~0.006%) is filtered out but a genuine trend
    change (spread >= 0.15% of price, the default) still fires.
    """
    if None in (s.sma_fast, s.sma_slow, s.sma_fast_prev, s.sma_slow_prev, s.price) or not s.price:
        return
    if not _clears_atr_move(s, config):
        return

    spread = abs(s.sma_fast - s.sma_slow)
    if spread < config.min_ma_spread_pct * s.price:
        return  # crossover too small to matter -- likely noise, not a real trend change

    was_below = s.sma_fast_prev <= s.sma_slow_prev
    now_above = s.sma_fast > s.sma_slow
    if was_below and now_above:
        signals.append(_build_signal(
            ticker, s, SignalType.MA_GOLDEN_CROSS, SignalDirection.BULLISH,
            f"{config.ma_fast_period}-period MA ({s.sma_fast:.2f}) crossed above "
            f"{config.ma_slow_period}-period MA ({s.sma_slow:.2f})",
            confluence_score, risk_reward_ratio,
        ))
        return

    was_above = s.sma_fast_prev >= s.sma_slow_prev
    now_below = s.sma_fast < s.sma_slow
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MA_DEATH_CROSS, SignalDirection.BEARISH,
            f"{config.ma_fast_period}-period MA ({s.sma_fast:.2f}) crossed below "
            f"{config.ma_slow_period}-period MA ({s.sma_slow:.2f})",
            confluence_score, risk_reward_ratio,
        ))


def _build_signal(
    ticker: str,
    s: IndicatorSnapshot,
    signal_type: SignalType,
    direction: SignalDirection,
    message: str,
    confluence_score: int,
    risk_reward_ratio: float | None,
) -> QuantSignal:
    return QuantSignal(
        ticker=ticker.upper(),
        signal_type=signal_type,
        direction=direction,
        message=message,
        price=s.price,
        rsi=s.rsi,
        macd=s.macd,
        macd_signal_line=s.macd_signal_line,
        sma_fast=s.sma_fast,
        sma_slow=s.sma_slow,
        volume=s.volume,
        volume_surge_ratio=s.volume_surge_ratio,
        atr=s.atr,
        confluence_score=confluence_score,
        risk_reward_ratio=risk_reward_ratio,
        bar_timestamp=s.bar_timestamp,
    )
