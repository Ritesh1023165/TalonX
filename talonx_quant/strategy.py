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
"""
from __future__ import annotations

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import IndicatorSnapshot
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


def evaluate_signals(
    ticker: str, snapshot: IndicatorSnapshot, config: QuantConfig
) -> list[QuantSignal]:
    signals: list[QuantSignal] = []

    _check_rsi_volume_setup(ticker, snapshot, config, signals)
    _check_macd_crossover(ticker, snapshot, config, signals)
    _check_ma_crossover(ticker, snapshot, config, signals)

    return signals


def _check_rsi_volume_setup(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal]
) -> None:
    if s.rsi is None or s.volume_surge_ratio is None:
        return

    if s.rsi < config.rsi_oversold and s.volume_surge_ratio > config.volume_surge_ratio_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalDirection.BULLISH,
            f"RSI {s.rsi:.1f} oversold (< {config.rsi_oversold:.0f}) with "
            f"{s.volume_surge_ratio:.1f}x volume surge (> {config.volume_surge_ratio_threshold:.1f}x)",
        ))
    elif s.rsi > config.rsi_overbought and s.volume_surge_ratio > config.volume_surge_ratio_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERBOUGHT_VOLUME_SURGE, SignalDirection.BEARISH,
            f"RSI {s.rsi:.1f} overbought (> {config.rsi_overbought:.0f}) with "
            f"{s.volume_surge_ratio:.1f}x volume surge (> {config.volume_surge_ratio_threshold:.1f}x)",
        ))


def _check_macd_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal]
) -> None:
    if None in (s.macd, s.macd_signal_line, s.macd_prev, s.macd_signal_line_prev):
        return

    was_below = s.macd_prev <= s.macd_signal_line_prev
    now_above = s.macd > s.macd_signal_line
    if was_below and now_above:
        signals.append(_build_signal(
            ticker, s, SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH,
            f"MACD ({s.macd:.3f}) crossed above signal line ({s.macd_signal_line:.3f})",
        ))
        return  # a bar crosses one direction at most; skip the bearish check

    was_above = s.macd_prev >= s.macd_signal_line_prev
    now_below = s.macd < s.macd_signal_line
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MACD_BEARISH_CROSS, SignalDirection.BEARISH,
            f"MACD ({s.macd:.3f}) crossed below signal line ({s.macd_signal_line:.3f})",
        ))


def _check_ma_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal]
) -> None:
    if None in (s.sma_fast, s.sma_slow, s.sma_fast_prev, s.sma_slow_prev):
        return

    was_below = s.sma_fast_prev <= s.sma_slow_prev
    now_above = s.sma_fast > s.sma_slow
    if was_below and now_above:
        signals.append(_build_signal(
            ticker, s, SignalType.MA_GOLDEN_CROSS, SignalDirection.BULLISH,
            f"{config.ma_fast_period}-period MA ({s.sma_fast:.2f}) crossed above "
            f"{config.ma_slow_period}-period MA ({s.sma_slow:.2f})",
        ))
        return

    was_above = s.sma_fast_prev >= s.sma_slow_prev
    now_below = s.sma_fast < s.sma_slow
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MA_DEATH_CROSS, SignalDirection.BEARISH,
            f"{config.ma_fast_period}-period MA ({s.sma_fast:.2f}) crossed below "
            f"{config.ma_slow_period}-period MA ({s.sma_slow:.2f})",
        ))


def _build_signal(
    ticker: str,
    s: IndicatorSnapshot,
    signal_type: SignalType,
    direction: SignalDirection,
    message: str,
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
        bar_timestamp=s.bar_timestamp,
    )
