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
  - confluence_score (0-3) and risk_reward_ratio are computed per
    SIGNAL (direction-aware -- see the 2026-08-16 gap fixes below) and
    attached to every signal that fires -- consumer.py filters on both
    before a signal is even allowed to start the per-ticker cooldown.

Phase 2 requirement doc additions:
  - Explicit $ stop_price/target_price (1x ATR stop / pivot-or-2x-ATR
    target) attached to every signal, not just the derived
    risk_reward_ratio -- see _stop_target_prices.
  - Session-aware volume-surge threshold: pre-market bars (04:00-09:30 ET)
    require a stricter surge ratio than regular-session bars -- see
    session.get_session and _pick_volume_threshold.
  - trend_aligned/htf_sma_200 attached to every signal (None when the
    15m-200-SMA trend gate doesn't apply -- bearish, pre-market, or HTF
    buffer still warming up). The actual DROP decision for a
    trend-misaligned bullish candidate happens in consumer.py, same
    "strategy.py computes/attaches, consumer.py gates" split the
    confluence/risk-reward filters already use.

Requirement-doc gap fixes (2026-08-16):
  - Direction-Aware Confluence: confluence_score is now computed PER
    SIGNAL DIRECTION, not once per bar. An RSI reading in the extreme
    zone only counts toward a BULLISH candidate's score if it's OVERSOLD
    (< rsi_oversold) and toward a BEARISH candidate's score if it's
    OVERBOUGHT (> rsi_overbought) -- an overbought bar (RSI > 70) earns a
    bullish candidate ZERO points for that leg, since overbought is
    bearish evidence, not confluence for going long. See _confluence_score.
  - Structural R:R Calculation: risk_reward_ratio is now measured against
    the nearest classic floor-trader pivot level (prior completed
    regular session's R1/S1, see indicators.compute_daily_pivots) rather
    than a second ATR multiple -- see _structural_risk_reward.
  - RSI Reversal Curl: neither RSI+volume leg fires on the initial
    threshold breach anymore; both wait for RSI to curl back to the
    neutral side first -- bullish recovers back ABOVE rsi_oversold,
    bearish recovers back BELOW rsi_overbought (made symmetric
    2026-08-16 per a quant audit -- see _check_rsi_volume_setup).
  - Harmonized risk distance: risk_reward_ratio's denominator and the
    published stop_price now use the SAME atr_stop_multiplier x ATR
    distance (2026-08-16 quant-audit fix) -- previously a separate,
    wider multiplier fed only the gate while a narrower one fed only the
    executed stop, so a candidate could pass the R:R gate on a different
    number than its actual executed R:R -- see _structural_risk_reward
    and _stop_target_prices.
"""
from __future__ import annotations

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType
from talonx_quant.session import Session, get_session


def evaluate_signals(
    ticker: str,
    snapshot: IndicatorSnapshot,
    config: QuantConfig,
    htf_sma_200: float | None = None,
    daily_pivots: DailyPivots | None = None,
) -> list[QuantSignal]:
    signals: list[QuantSignal] = []
    session = get_session(snapshot.bar_timestamp)
    volume_threshold = _pick_volume_threshold(session, config)

    ctx = _SignalContext(
        session=session, htf_sma_200=htf_sma_200, volume_threshold=volume_threshold, pivots=daily_pivots,
    )

    _check_rsi_volume_setup(ticker, snapshot, config, signals, ctx)
    _check_macd_crossover(ticker, snapshot, config, signals, ctx)
    _check_ma_crossover(ticker, snapshot, config, signals, ctx)

    return signals


class _SignalContext:
    """Bundles the per-bar, non-IndicatorSnapshot inputs every check needs
    -- avoids growing each _check_* function's positional-arg list every
    time a new session-aware input is added."""

    __slots__ = ("session", "htf_sma_200", "volume_threshold", "pivots")

    def __init__(
        self, session: Session, htf_sma_200: float | None, volume_threshold: float,
        pivots: DailyPivots | None = None,
    ):
        self.session = session
        self.htf_sma_200 = htf_sma_200
        self.volume_threshold = volume_threshold
        self.pivots = pivots


def _pick_volume_threshold(session: Session, config: QuantConfig) -> float:
    """Pre-market bars require a stricter volume-surge ratio (default
    3.0x) than regular-session bars (default 2.0x) -- pre-market liquidity
    is thin enough that the regular bar isn't a meaningful filter."""
    if session == "pre_market":
        return config.premarket_volume_surge_ratio_threshold
    return config.volume_surge_ratio_threshold


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


def _confluence_score(
    s: IndicatorSnapshot, config: QuantConfig, volume_threshold: float, direction: SignalDirection,
) -> int:
    """0-3: +1 each for a MACD cross firing THIS bar, RSI sitting in the
    extreme zone that actually SUPPORTS this candidate's direction, and
    volume surge above the session-appropriate threshold.

    Direction-Aware Confluence: unlike the old bar-level (direction-
    agnostic) score, a RSI reading only contributes a point when it
    agrees with the direction being scored -- oversold (< rsi_oversold)
    for a BULLISH candidate, overbought (> rsi_overbought) for a BEARISH
    one. An overbought bar (RSI > 70) earns a BULLISH candidate ZERO
    points for this leg: being overbought is bearish evidence, not
    conviction for going long, so it must not silently pad a long
    setup's score toward the confluence_score_min gate. Computed fresh
    per signal (not once per bar) since two signals of opposite
    direction can legitimately fire on the same bar (e.g. a MACD
    bullish cross and, on a later bar, an MA death cross) and each needs
    its own direction-appropriate score."""
    score = 0
    if _macd_crossed_this_bar(s):
        score += 1
    if s.rsi is not None:
        if direction == SignalDirection.BULLISH and s.rsi < config.rsi_oversold:
            score += 1
        elif direction == SignalDirection.BEARISH and s.rsi > config.rsi_overbought:
            score += 1
    if s.volume_surge_ratio is not None and s.volume_surge_ratio > volume_threshold:
        score += 1
    return score


def _structural_risk_reward(
    s: IndicatorSnapshot, direction: SignalDirection, pivots: DailyPivots | None, config: QuantConfig,
) -> float | None:
    """Structural R:R Calculation: reward is the distance from entry to
    the nearest classic floor-trader pivot level from the prior completed
    regular session (R1 for a BULLISH candidate, S1 for a BEARISH one --
    see indicators.compute_daily_pivots), a genuine market-derived target
    rather than a second ATR multiple; risk is
    atr_stop_multiplier x ATR (default 1.5x) -- the SAME multiplier
    _stop_target_prices uses for the EXECUTED dollar stop below. These
    two must use one shared multiplier: a 2026-08-16 quant audit caught
    an earlier version of this code gating on a WIDER risk distance
    (1.5x ATR) than the stop it then actually placed (1.0x ATR) --
    passing the gate at a nominal 2.0 R:R while the executed trade's real
    R:R (reward / the tighter 1.0x-ATR stop that was actually live) was
    3.0, a discrepancy between "what was evaluated" and "what was
    traded." Returns None -- same fail-closed, "insufficient data -> no
    signal" posture every other warm-up-dependent check in this module
    takes -- when ATR/price/pivots aren't available yet, or when the
    relevant pivot level sits on the WRONG side of entry (e.g. price has
    already traded through R1, leaving no bullish room left to target)."""
    if s.atr is None or s.atr <= 0 or not s.price or pivots is None:
        return None
    risk = config.atr_stop_multiplier * s.atr
    if risk <= 0:
        return None
    if direction == SignalDirection.BULLISH:
        reward = pivots.resistance - s.price
    else:
        reward = s.price - pivots.support
    if reward <= 0:
        return None
    return reward / risk


def _stop_target_prices(
    price: float, atr: float | None, direction: SignalDirection, config: QuantConfig,
    pivots: DailyPivots | None,
) -> tuple[float | None, float | None]:
    """Explicit dollar stop/target levels: stop = atr_stop_multiplier x
    ATR against the trade (default 1.5x -- the SAME multiplier
    _structural_risk_reward's risk side uses, so the executed stop always
    matches what the R:R gate actually evaluated; see that function's own
    docstring for the harmonization fix this is half of); target = the
    nearest pivot level (R1/S1) when available -- the SAME structural
    level _structural_risk_reward's reward side uses, so a published
    signal's displayed/executed target actually matches what cleared the
    R:R gate -- else the old atr_reward_multiplier x ATR approximation
    (default 2x) while prior-session pivot data is still warming up.
    None/None when ATR isn't available yet (insufficient history), same
    warm-up posture as every other ATR-derived value here."""
    if atr is None or atr <= 0:
        return None, None
    stop_distance = config.atr_stop_multiplier * atr
    fallback_target_distance = config.atr_reward_multiplier * atr

    if direction == SignalDirection.BULLISH:
        stop = price - stop_distance
        if pivots is not None and pivots.resistance > price:
            return stop, pivots.resistance
        return stop, price + fallback_target_distance

    stop = price + stop_distance
    if pivots is not None and pivots.support < price:
        return stop, pivots.support
    return stop, price - fallback_target_distance


def _trend_aligned(
    price: float, direction: SignalDirection, session: Session, htf_sma_200: float | None, config: QuantConfig,
) -> bool | None:
    """Trend Alignment Gate: BULLISH setups only, regular session only,
    per the requirement doc ("Evaluates BULLISH setups only if current
    price is above the 15-minute 200 SMA"). Returns None (not applicable/
    not yet knowable) for bearish signals, pre-market bars, a disabled
    gate, or an HTF buffer that hasn't warmed up to 200 bars yet -- the
    actual candidate-drop decision for a `False` result lives in
    consumer.py, not here."""
    if not config.trend_gate_enabled or direction != SignalDirection.BULLISH or session != "regular":
        return None
    if htf_sma_200 is None:
        return None
    return price > htf_sma_200


def _check_rsi_volume_setup(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal], ctx: _SignalContext,
) -> None:
    """
    Edge-triggered, like the MACD/MA crossover checks below: fires only on
    the bar RSI first crosses a threshold, not on every subsequent bar it
    remains oversold/overbought. Without this, a stock sitting under RSI 30
    for 5 consecutive bars would fire 5 signals instead of 1 -- a major
    source of the alert chatter this module was tuned to reduce.

    RSI Reversal Curl: NEITHER leg fires on the initial breach of its
    threshold -- both wait for RSI to curl back to the neutral side
    first, then fire on that recovery bar. Bullish fires when RSI curls
    back UP above rsi_oversold (rsi_prev still below it, rsi now
    at/above it) -- avoids a falling-knife entry with no confirmation the
    selloff has actually stopped. Bearish fires when RSI curls back DOWN
    below rsi_overbought (rsi_prev still above it, rsi now at/below it)
    -- symmetric with the bullish leg as of a 2026-08-16 quant audit,
    which flagged the ORIGINAL asymmetric version (bearish fired
    immediately on the initial cross INTO overbought) as a momentum
    trap: in a trending bull market RSI can sit elevated for hours, and
    shorting the first touch fights the trend rather than confirming a
    genuine reversal, the same false-signal risk the bullish leg was
    already fixed for.
    """
    if s.rsi is None or s.rsi_prev is None or s.volume_surge_ratio is None:
        return
    if not _clears_atr_move(s, config):
        return

    recovered_from_oversold = s.rsi_prev < config.rsi_oversold and s.rsi >= config.rsi_oversold
    if recovered_from_oversold and s.volume_surge_ratio > ctx.volume_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalDirection.BULLISH,
            f"RSI {s.rsi:.1f} curled back above oversold (>= {config.rsi_oversold:.0f}, "
            f"was {s.rsi_prev:.1f}) with {s.volume_surge_ratio:.1f}x volume surge "
            f"(> {ctx.volume_threshold:.1f}x)",
            config, ctx,
        ))
        return  # a bar crosses one direction at most; skip the overbought check

    recovered_from_overbought = s.rsi_prev > config.rsi_overbought and s.rsi <= config.rsi_overbought
    if recovered_from_overbought and s.volume_surge_ratio > ctx.volume_threshold:
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERBOUGHT_VOLUME_SURGE, SignalDirection.BEARISH,
            f"RSI {s.rsi:.1f} curled back below overbought (<= {config.rsi_overbought:.0f}, "
            f"was {s.rsi_prev:.1f}) with {s.volume_surge_ratio:.1f}x volume surge "
            f"(> {ctx.volume_threshold:.1f}x)",
            config, ctx,
        ))


def _check_macd_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal], ctx: _SignalContext,
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
            config, ctx,
        ))
        return  # a bar crosses one direction at most; skip the bearish check

    was_above = s.macd_prev >= s.macd_signal_line_prev
    now_below = s.macd < s.macd_signal_line
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MACD_BEARISH_CROSS, SignalDirection.BEARISH,
            f"MACD ({s.macd:.3f}) crossed below signal line ({s.macd_signal_line:.3f})",
            config, ctx,
        ))


def _check_ma_crossover(
    ticker: str, s: IndicatorSnapshot, config: QuantConfig, signals: list[QuantSignal], ctx: _SignalContext,
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
            config, ctx,
        ))
        return

    was_above = s.sma_fast_prev >= s.sma_slow_prev
    now_below = s.sma_fast < s.sma_slow
    if was_above and now_below:
        signals.append(_build_signal(
            ticker, s, SignalType.MA_DEATH_CROSS, SignalDirection.BEARISH,
            f"{config.ma_fast_period}-period MA ({s.sma_fast:.2f}) crossed below "
            f"{config.ma_slow_period}-period MA ({s.sma_slow:.2f})",
            config, ctx,
        ))


def _build_signal(
    ticker: str,
    s: IndicatorSnapshot,
    signal_type: SignalType,
    direction: SignalDirection,
    message: str,
    config: QuantConfig,
    ctx: _SignalContext,
) -> QuantSignal:
    confluence_score = _confluence_score(s, config, ctx.volume_threshold, direction)
    risk_reward_ratio = _structural_risk_reward(s, direction, ctx.pivots, config)
    stop_price, target_price = _stop_target_prices(s.price, s.atr, direction, config, ctx.pivots)
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
        stop_price=stop_price,
        target_price=target_price,
        trend_aligned=_trend_aligned(s.price, direction, ctx.session, ctx.htf_sma_200, config),
        htf_sma_200=ctx.htf_sma_200,
        pivot_resistance=None if ctx.pivots is None else ctx.pivots.resistance,
        pivot_support=None if ctx.pivots is None else ctx.pivots.support,
        session=ctx.session,
        bar_timestamp=s.bar_timestamp,
    )
