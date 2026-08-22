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
  - Explicit $ stop_price/target_price (atr_stop_multiplier x ATR stop --
    1.5x default, see the harmonization fix below -- / pivot-or-2x-ATR
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

2026-08-16 quant audit (round 3) -- canonical trade geometry:
  - calculate_trade_geometry is now the SINGLE function that derives
    stop_price/target_price/risk/reward/risk_reward_ratio from an entry
    price -- _structural_risk_reward and _stop_target_prices are thin
    wrappers around it, and consumer.py's _revalidate_candidate calls it
    directly. A prior version of _revalidate_candidate recalculated only
    risk_reward_ratio against a fresher price at throttle-flush time
    without also recalculating stop_price/target_price, so a published
    signal's displayed stop/target could reference the ORIGINAL, stale
    entry price while its ratio referenced the new one -- an internally
    inconsistent trade geometry. Routing both signal-generation and
    revalidation through this one function makes that drift structurally
    impossible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from talonx_quant.config import ConfluenceContract, QuantConfig
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType
from talonx_quant.session import Session, get_session

# Task 35 (owner-confirmed ATR-RISK-001: MARKET_STRUCTURE_PRIMARY) -- stable
# geometry-path / fallback-reason markers, mirroring the plain-string
# convention this module already uses for exit_reason/SignalType.value
# elsewhere rather than introducing a new enum type for a simple label.
GEOMETRY_PATH_STRUCTURAL_PRIMARY = "STRUCTURAL_PRIMARY"
GEOMETRY_PATH_ATR_FALLBACK = "ATR_FALLBACK"

FALLBACK_REASON_NO_STRUCTURAL_SUPPORT = "NO_STRUCTURAL_SUPPORT"
FALLBACK_REASON_STRUCTURE_NOT_BELOW_ENTRY = "STRUCTURE_NOT_BELOW_ENTRY"
FALLBACK_REASON_STRUCTURE_INVALID_OR_NONFINITE = "STRUCTURE_INVALID_OR_NONFINITE"


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


def _macd_bullish_crossed_this_bar(s: IndicatorSnapshot) -> bool:
    """True if MACD crossed ABOVE its signal line on this bar -- the exact
    condition _check_macd_crossover uses to fire MACD_BULLISH_CROSS."""
    if None in (s.macd, s.macd_signal_line, s.macd_prev, s.macd_signal_line_prev):
        return False
    return s.macd_prev <= s.macd_signal_line_prev and s.macd > s.macd_signal_line


def _macd_bearish_crossed_this_bar(s: IndicatorSnapshot) -> bool:
    """True if MACD crossed BELOW its signal line on this bar -- the exact
    condition _check_macd_crossover uses to fire MACD_BEARISH_CROSS."""
    if None in (s.macd, s.macd_signal_line, s.macd_prev, s.macd_signal_line_prev):
        return False
    return s.macd_prev >= s.macd_signal_line_prev and s.macd < s.macd_signal_line


def _macd_crossed_this_bar(s: IndicatorSnapshot) -> bool:
    """True if EITHER direction of MACD/signal-line cross happened on
    this bar -- used both by _check_macd_crossover (to decide whether to
    emit its own signal) and by _confluence_score/LEGACY contract (to
    count a MACD cross as a conviction factor for ANY signal firing this
    bar, e.g. an RSI setup with a coincident MACD cross scores higher
    than one without). Direction-AGNOSTIC on purpose -- this is the
    pre-Task-51 LEGACY formula, frozen for zero-drift; the Task 51
    EXPERIMENTAL contract uses the direction-aware halves above instead
    (see evaluate_independent_confirmations)."""
    return _macd_bullish_crossed_this_bar(s) or _macd_bearish_crossed_this_bar(s)


def _confluence_score(
    s: IndicatorSnapshot, config: QuantConfig, volume_threshold: float, direction: SignalDirection,
    signal_type: SignalType,
) -> int:
    """0-3: +1 each for an INDEPENDENT MACD cross firing THIS bar, RSI
    sitting in the extreme zone that actually SUPPORTS this candidate's
    direction, and volume surge above the session-appropriate threshold.

    No-Self-Credit (2026-08-22 requirement-alignment fix, Task 47/49):
    the owner's confluence contract is TRIGGER + ONE INDEPENDENT
    CONFIRMATION. For a candidate whose own trigger IS the MACD cross
    (signal_type MACD_BULLISH_CROSS/MACD_BEARISH_CROSS), that same cross
    can no longer also count as this candidate's confirmation leg --
    Task 47 measured a 100% self-credit rate before this fix, since
    _macd_crossed_this_bar's condition is identical to the trigger
    condition that created the candidate in the first place. A
    non-MACD-triggered candidate (RSI/MA) that happens to coincide with
    an independent MACD cross on the same bar is unaffected -- that IS a
    genuinely independent confirmation, exactly the case this leg exists
    to reward.

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
    own_trigger_is_macd = signal_type in (SignalType.MACD_BULLISH_CROSS, SignalType.MACD_BEARISH_CROSS)
    if _macd_crossed_this_bar(s) and not own_trigger_is_macd:
        score += 1
    if s.rsi is not None:
        if direction == SignalDirection.BULLISH and s.rsi < config.rsi_oversold:
            score += 1
        elif direction == SignalDirection.BEARISH and s.rsi > config.rsi_overbought:
            score += 1
    if s.volume_surge_ratio is not None and s.volume_surge_ratio > volume_threshold:
        score += 1
    return score


@dataclass(frozen=True)
class ConfirmationState:
    """Task 51: structured result of evaluate_independent_confirmations --
    which independent confirmation legs a candidate has, under the
    INDEPENDENT_CONFIRMATION_EXPERIMENTAL contract. confirmation_count is
    what confluence_score is set to under that contract (see _build_signal);
    confirmation_components is a stable, human-readable audit trail (e.g.
    for RejectedCandidateEvent/shadow telemetry) of exactly which legs
    fired, independent of the numeric count alone."""
    macd_confirmed: bool
    rsi_confirmed: bool
    volume_confirmed: bool
    confirmation_count: int
    confirmation_components: tuple[str, ...]


def evaluate_independent_confirmations(
    s: IndicatorSnapshot, signal_type: SignalType, direction: SignalDirection,
    volume_threshold: float, config: QuantConfig,
) -> ConfirmationState:
    """Task 51 authoritative family-aware confirmation model for the
    INDEPENDENT_CONFIRMATION_EXPERIMENTAL contract: TRIGGER + AT LEAST ONE
    independent, directionally-supportive confirmation, for every family
    (RSI/MACD/MA) -- the owner's contract read literally, not as a numeric
    threshold. This is the ONE authoritative implementation of that
    contract; talonx_backtest's engine reuses this function unchanged
    (same "reuse the same strategy.py, do not duplicate formulas"
    architecture every other gate in this module already follows).

    Family self-credit exclusion (generalizes Task 47/49's MACD-specific
    fix to every family): a candidate's own trigger family can never count
    as its own confirmation leg, regardless of which family that is --
    - MACD-triggered: the MACD leg is excluded (that IS the trigger).
    - RSI-triggered: the RSI leg is excluded. Structurally this was
      already true before Task 51 (Task 28/33: the curl-recovery trigger
      condition and the confluence RSI-extreme-state condition are
      disjoint), kept explicit here so the exclusion doesn't rely on that
      coincidence remaining true forever.
    - MA-triggered: _confluence_score never had an MA-state leg to begin
      with -- nothing to exclude, MA can draw on all three legs below.

    Direction-aware MACD (Task 51 fix to the LEGACY formula's direction-
    agnostic weakness): a BULLISH candidate can only be confirmed by a
    BULLISH MACD cross, a BEARISH candidate only by a BEARISH one -- see
    _macd_bullish_crossed_this_bar/_macd_bearish_crossed_this_bar. Under
    the OLD (LEGACY) _macd_crossed_this_bar, a bearish MACD cross could
    confirm a bullish RSI/MA candidate on the same bar, which is not
    "directionally supportive" by any reading of the owner's contract.

    Volume is shared, family-agnostic confirmation evidence for every
    family (it never fires a trigger of its own, so it is never excluded
    for self-credit) -- same direction-aware volume_threshold every other
    volume check in this module uses (session-appropriate surge ratio)."""
    own_trigger_is_macd = signal_type in (SignalType.MACD_BULLISH_CROSS, SignalType.MACD_BEARISH_CROSS)
    own_trigger_is_rsi = signal_type in (SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalType.RSI_OVERBOUGHT_VOLUME_SURGE)

    if direction == SignalDirection.BULLISH:
        macd_directional = _macd_bullish_crossed_this_bar(s)
    else:
        macd_directional = _macd_bearish_crossed_this_bar(s)
    macd_confirmed = macd_directional and not own_trigger_is_macd

    rsi_directional = s.rsi is not None and (
        (direction == SignalDirection.BULLISH and s.rsi < config.rsi_oversold)
        or (direction == SignalDirection.BEARISH and s.rsi > config.rsi_overbought)
    )
    rsi_confirmed = rsi_directional and not own_trigger_is_rsi

    volume_confirmed = s.volume_surge_ratio is not None and s.volume_surge_ratio > volume_threshold

    components = tuple(
        name for name, ok in (("macd", macd_confirmed), ("rsi", rsi_confirmed), ("volume", volume_confirmed)) if ok
    )
    return ConfirmationState(
        macd_confirmed=macd_confirmed, rsi_confirmed=rsi_confirmed, volume_confirmed=volume_confirmed,
        confirmation_count=len(components), confirmation_components=components,
    )


@dataclass(frozen=True)
class TradeGeometry:
    """Everything derived from one entry price via one shared risk
    distance -- stop, target, risk, reward, and the resulting ratio.
    Returned as a single unit so a caller can never update the ratio
    without also updating the stop/target it was measured against (see
    calculate_trade_geometry's own docstring for the bug this fixes).

    Task 35 additions (owner-confirmed ATR-RISK-001: MARKET_STRUCTURE_
    PRIMARY): geometry_path/fallback_reason/structural_level/
    structural_level_type record WHICH stop path this geometry actually
    used and why -- observability fields, not inputs to any downstream
    decision beyond the stop/risk values themselves."""

    stop_price: float
    target_price: float
    risk: float
    reward: float | None
    risk_reward_ratio: float | None
    geometry_path: str
    fallback_reason: str | None
    structural_level: float | None
    structural_level_type: str | None


def calculate_trade_geometry(
    price: float, atr: float | None, direction: SignalDirection,
    pivot_resistance: float | None, pivot_support: float | None, config: QuantConfig,
) -> TradeGeometry | None:
    """Canonical stop/target/risk/reward/R:R calculation -- the SINGLE
    source of truth used both when a candidate is first built
    (_build_signal, below) and when consumer.py's _revalidate_candidate
    re-derives these numbers against a fresher price at throttle-flush
    time. A 2026-08-16 quant audit caught _revalidate_candidate
    recalculating risk_reward_ratio against the new price WITHOUT also
    recalculating stop_price/target_price, so a revalidated signal could
    publish with a ratio that no longer matched its own displayed/
    executed stop and target -- the same class of evaluated-vs-executed
    drift an earlier audit had already fixed for signal generation (see
    this module's "Harmonized risk distance" note above). Routing both
    call sites through the exact same function makes that drift
    structurally impossible.

    target = the nearest classic floor-trader pivot level (R1 for
    BULLISH, S1 for BEARISH) when it sits on the correct side of price,
    else the atr_reward_multiplier x ATR approximation while pivot data
    is still warming up. reward/risk_reward_ratio are only populated when
    the target is the STRUCTURAL pivot level -- the ATR-fallback target
    doesn't count as a validated reward for gating purposes, matching the
    prior _structural_risk_reward's fail-closed "insufficient pivot data
    -> no ratio" posture (a candidate with risk_reward_ratio=None never
    clears consumer.py's R:R gate).

    Task 35 stop geometry (owner-confirmed ATR-RISK-001: MARKET_STRUCTURE_
    PRIMARY, Task 34's CURRENT_ATR_STOPS_SYSTEMATICALLY_MISALIGNED_WITH_
    STRUCTURE finding) -- BULLISH ONLY, mirroring the existing bullish
    target logic's own structural-first/ATR-fallback shape:
      1. STRUCTURAL_PRIMARY: if pivot_support is finite, > 0, and strictly
         below `price`, the stop IS pivot_support -- no buffer is
         subtracted around it (Task 34 found no existing repository
         requirement defines one; inventing one here would be parameter
         tuning, not spec alignment -- see docs/modules/quant.md's
         STRUCTURAL_BUFFER_REQUIREMENT_NOT_DEFINED note).
      2. ATR_FALLBACK: otherwise, stop = price - atr_stop_multiplier x ATR
         (the unmodified, pre-existing formula -- fallback_reason records
         exactly why structure wasn't used: NO_STRUCTURAL_SUPPORT (pivot_
         support is None or non-finite), STRUCTURE_INVALID_OR_NONFINITE
         (a finite value that isn't a usable positive price), or
         STRUCTURE_NOT_BELOW_ENTRY (a valid, finite, positive pivot that
         simply isn't on the correct side of -- or is exactly equal to --
         the current price; equality is deliberately treated as invalid,
         since a stop at entry would be a zero-risk trade).
    `risk` is always price - stop (recomputed from whichever stop was
    actually selected), so risk_reward_ratio always reflects the REAL
    selected geometry, never a stale ATR-only figure -- see the R:R
    Contract note in docs/modules/quant.md.

    BEARISH is unchanged (still atr_stop_multiplier x ATR, unconditional)
    -- the owner's MARKET_STRUCTURE_PRIMARY contract is scoped to LONG
    trades only (Task 25A's LONG_ONLY lifecycle means a BEARISH signal
    never opens a new position; its stop/target are computed but not
    economically load-bearing the way a BULLISH candidate's are).

    Returns None when ATR/price aren't available yet or risk resolves to
    <= 0 -- same warm-up posture as every other ATR-derived value here."""
    if atr is None or atr <= 0 or not price:
        return None
    atr_risk = config.atr_stop_multiplier * atr
    if atr_risk <= 0:
        return None

    if direction == SignalDirection.BULLISH:
        structural_valid = (
            pivot_support is not None
            and math.isfinite(pivot_support)
            and pivot_support > 0
            and pivot_support < price
        )
        if structural_valid:
            stop = pivot_support
            geometry_path = GEOMETRY_PATH_STRUCTURAL_PRIMARY
            fallback_reason = None
            structural_level = pivot_support
            structural_level_type = "prior_session_S1_pivot"
        else:
            stop = price - atr_risk
            geometry_path = GEOMETRY_PATH_ATR_FALLBACK
            structural_level = None
            structural_level_type = None
            if pivot_support is None:
                fallback_reason = FALLBACK_REASON_NO_STRUCTURAL_SUPPORT
            elif not math.isfinite(pivot_support) or pivot_support <= 0:
                fallback_reason = FALLBACK_REASON_STRUCTURE_INVALID_OR_NONFINITE
            else:
                fallback_reason = FALLBACK_REASON_STRUCTURE_NOT_BELOW_ENTRY

        risk = price - stop
        if risk <= 0:
            return None  # defensive -- unreachable given the checks above, never propagate invalid geometry

        if pivot_resistance is not None and pivot_resistance > price:
            target = pivot_resistance
            reward = target - price
        else:
            target = price + config.atr_reward_multiplier * atr
            reward = None
    else:
        stop = price + atr_risk
        risk = atr_risk
        geometry_path = GEOMETRY_PATH_ATR_FALLBACK
        fallback_reason = None
        structural_level = None
        structural_level_type = None
        if pivot_support is not None and pivot_support < price:
            target = pivot_support
            reward = price - target
        else:
            target = price - config.atr_reward_multiplier * atr
            reward = None

    risk_reward_ratio = (reward / risk) if reward is not None and reward > 0 else None
    return TradeGeometry(
        stop_price=stop, target_price=target, risk=risk,
        reward=reward, risk_reward_ratio=risk_reward_ratio,
        geometry_path=geometry_path, fallback_reason=fallback_reason,
        structural_level=structural_level, structural_level_type=structural_level_type,
    )


def _structural_risk_reward(
    s: IndicatorSnapshot, direction: SignalDirection, pivots: DailyPivots | None, config: QuantConfig,
) -> float | None:
    """Thin wrapper around calculate_trade_geometry -- kept as its own
    function since it's unit-tested directly (see test_quant_strategy.py)
    and reads more naturally at its _build_signal call site than
    unpacking a TradeGeometry there. See calculate_trade_geometry's
    docstring for the actual calculation and the harmonization/drift
    history behind it."""
    geometry = calculate_trade_geometry(
        s.price, s.atr, direction,
        None if pivots is None else pivots.resistance,
        None if pivots is None else pivots.support,
        config,
    )
    return None if geometry is None else geometry.risk_reward_ratio


def _stop_target_prices(
    price: float, atr: float | None, direction: SignalDirection, config: QuantConfig,
    pivots: DailyPivots | None,
) -> tuple[float | None, float | None]:
    """Thin wrapper around calculate_trade_geometry -- see that function's
    docstring and _structural_risk_reward's for why this stays a separate
    function rather than being inlined at the _build_signal call site."""
    geometry = calculate_trade_geometry(
        price, atr, direction,
        None if pivots is None else pivots.resistance,
        None if pivots is None else pivots.support,
        config,
    )
    if geometry is None:
        return None, None
    return geometry.stop_price, geometry.target_price


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

    Trigger/confirmation separation (Task 51): under LEGACY, volume surge
    remains a hard PREREQUISITE for the trigger to fire at all -- byte-
    for-byte the pre-Task-51 behavior, frozen for zero-drift. Under
    INDEPENDENT_CONFIRMATION_EXPERIMENTAL, the curl ALONE creates the
    candidate (the SignalType enum values keep their legacy
    *_VOLUME_SURGE names for wire compatibility -- see schemas.SignalType
    -- but no longer imply volume was present at trigger time under this
    contract); volume becomes purely a confirmation leg, evaluated by
    evaluate_independent_confirmations downstream in _build_signal, never
    double-required here.
    """
    if s.rsi is None or s.rsi_prev is None:
        return
    if not _clears_atr_move(s, config):
        return
    experimental = config.confluence_contract == ConfluenceContract.INDEPENDENT_CONFIRMATION_EXPERIMENTAL
    if not experimental and s.volume_surge_ratio is None:
        return  # LEGACY: volume required for the trigger itself, exactly as before Task 51

    volume_confirmed = s.volume_surge_ratio is not None and s.volume_surge_ratio > ctx.volume_threshold
    if s.volume_surge_ratio is not None:
        vol_desc = f"with {s.volume_surge_ratio:.1f}x volume surge (> {ctx.volume_threshold:.1f}x)"
    else:
        vol_desc = "(no volume surge -- EXPERIMENTAL curl-only trigger)"

    recovered_from_oversold = s.rsi_prev < config.rsi_oversold and s.rsi >= config.rsi_oversold
    if recovered_from_oversold and (experimental or volume_confirmed):
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalDirection.BULLISH,
            f"RSI {s.rsi:.1f} curled back above oversold (>= {config.rsi_oversold:.0f}, "
            f"was {s.rsi_prev:.1f}) {vol_desc}",
            config, ctx,
        ))
        return  # a bar crosses one direction at most; skip the overbought check

    recovered_from_overbought = s.rsi_prev > config.rsi_overbought and s.rsi <= config.rsi_overbought
    if recovered_from_overbought and (experimental or volume_confirmed):
        signals.append(_build_signal(
            ticker, s, SignalType.RSI_OVERBOUGHT_VOLUME_SURGE, SignalDirection.BEARISH,
            f"RSI {s.rsi:.1f} curled back below overbought (<= {config.rsi_overbought:.0f}, "
            f"was {s.rsi_prev:.1f}) {vol_desc}",
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
    # Task 51: contract dispatch. LEGACY keeps _confluence_score exactly as
    # Task 49 left it (byte-for-byte, zero-drift) -- confirmation_* fields
    # stay None, never populated under LEGACY. EXPERIMENTAL uses the new
    # family-aware model instead; confluence_score is REDEFINED to be
    # confirmation_count under this contract (see evaluate_independent_
    # confirmations's own docstring) -- same field, different, explicitly
    # documented meaning, disambiguated for any reader by the also-attached
    # confirmation_contract field.
    confirmation_state: ConfirmationState | None = None
    if config.confluence_contract == ConfluenceContract.INDEPENDENT_CONFIRMATION_EXPERIMENTAL:
        confirmation_state = evaluate_independent_confirmations(s, signal_type, direction, ctx.volume_threshold, config)
        confluence_score = confirmation_state.confirmation_count
    else:
        confluence_score = _confluence_score(s, config, ctx.volume_threshold, direction, signal_type)
    pivot_resistance = None if ctx.pivots is None else ctx.pivots.resistance
    pivot_support = None if ctx.pivots is None else ctx.pivots.support
    # Task 35: a single calculate_trade_geometry call (was two separate
    # wrapper calls computing the identical geometry twice) -- also the
    # only place geometry_path/fallback_reason/structural_level need to be
    # read out, so one call now serves both the existing stop/target/R:R
    # fields and the new observability fields without duplicating the
    # underlying calculation. _structural_risk_reward/_stop_target_prices
    # remain unchanged for their own direct unit tests.
    geometry = calculate_trade_geometry(s.price, s.atr, direction, pivot_resistance, pivot_support, config)
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
        confirmation_count=None if confirmation_state is None else confirmation_state.confirmation_count,
        confirmation_macd=None if confirmation_state is None else confirmation_state.macd_confirmed,
        confirmation_rsi=None if confirmation_state is None else confirmation_state.rsi_confirmed,
        confirmation_volume=None if confirmation_state is None else confirmation_state.volume_confirmed,
        confirmation_contract=config.confluence_contract.value if confirmation_state is not None else None,
        risk_reward_ratio=None if geometry is None else geometry.risk_reward_ratio,
        stop_price=None if geometry is None else geometry.stop_price,
        target_price=None if geometry is None else geometry.target_price,
        geometry_path=None if geometry is None else geometry.geometry_path,
        fallback_reason=None if geometry is None else geometry.fallback_reason,
        structural_level=None if geometry is None else geometry.structural_level,
        structural_level_type=None if geometry is None else geometry.structural_level_type,
        trend_aligned=_trend_aligned(s.price, direction, ctx.session, ctx.htf_sma_200, config),
        htf_sma_200=ctx.htf_sma_200,
        pivot_resistance=pivot_resistance,
        pivot_support=pivot_support,
        session=ctx.session,
        bar_timestamp=s.bar_timestamp,
    )
