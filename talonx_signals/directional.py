"""Task 99A S3 -- DirectionalAlertEngine.

Turns the RAW output of talonx_quant.strategy.evaluate_signals() (trigger
detection + geometry, BEFORE any consumer.py quality suppression) into
informational BULLISH / BEARISH DirectionalAlerts.

    market bar -> IndicatorSnapshot -> evaluate_signals() -> [QuantSignal]
                                                                  |
                                              DirectionalAlertEngine.evaluate()
                                                                  |
                                              [DirectionalAlert]  (dedup'd)

Contract (S3.3 / S3.4):
  - MACD / RSI / MA logic is NEVER reimplemented here -- evaluate_signals()
    is the single source.
  - An alert is emitted even if the trade-execution gate would later reject
    the same setup (LOW_VOLATILITY / LOW_CONFLUENCE / LOW_RISK_REWARD /
    blackout / cooldown / ...). `trade_gate_status` records that separately.
  - Edge-triggered upstream (evaluate_signals only fires on the transition
    bar), so the only dedup needed here is a short informational cooldown to
    swallow rapid re-crosses in chop; a genuinely new trigger after the
    window emits again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType
from talonx_quant.strategy import evaluate_signals
from talonx_quant.session import get_session

from talonx_signals.schemas import (
    PROFILE_CONTROL,
    AlertDirection,
    DirectionalAlert,
    MarketSession,
    SetupEvidence,
    TradeGateStatus,
    make_alert_id,
)

# QuantSignal is edge-triggered, so this only suppresses re-crosses of the
# SAME setup within the window -- not the first trigger, and not a genuinely
# new one after it expires. Deliberately short.
DEFAULT_INFORMATIONAL_COOLDOWN_SECONDS = 900.0   # 15 min
DEFAULT_RETRIGGER_PRICE_DELTA_PCT = 1.0          # bypass the cooldown on a real move

_DIR_MAP = {
    SignalDirection.BULLISH: AlertDirection.BULLISH,
    SignalDirection.BEARISH: AlertDirection.BEARISH,
}
_MACD_CROSS = {
    SignalType.MACD_BULLISH_CROSS: "bullish",
    SignalType.MACD_BEARISH_CROSS: "bearish",
}

GateProbe = Callable[[QuantSignal, IndicatorSnapshot], tuple[TradeGateStatus, str | None]]
CatalystLookup = Callable[[str, datetime], str | None]


def build_evidence(sig: QuantSignal, snapshot: IndicatorSnapshot, *, catalyst: str | None = None) -> SetupEvidence:
    atr_pct = None
    if sig.atr is not None and sig.price:
        atr_pct = sig.atr / sig.price * 100.0
    price_vs_htf = None
    if sig.htf_sma_200:
        price_vs_htf = (sig.price - sig.htf_sma_200) / sig.htf_sma_200 * 100.0
    return SetupEvidence(
        rsi=sig.rsi,
        macd=sig.macd,
        macd_signal_line=sig.macd_signal_line,
        macd_cross=_MACD_CROSS.get(sig.signal_type),
        sma_fast=sig.sma_fast,
        sma_slow=sig.sma_slow,
        volume_surge_ratio=sig.volume_surge_ratio,
        atr=sig.atr,
        atr_pct=atr_pct,
        trend_aligned=sig.trend_aligned,
        htf_sma_200=sig.htf_sma_200,
        price_vs_htf_sma_200_pct=price_vs_htf,
        pivot_resistance=sig.pivot_resistance,
        pivot_support=sig.pivot_support,
        nearby_catalyst=catalyst,
    )


@dataclass
class DirectionalAlertEngine:
    """Stateful only for dedup. `config` is the FROZEN control QuantConfig --
    evaluate_signals() attaches confluence/geometry but applies no gate, so
    the same frozen config drives the informational read for both profiles
    (the profile label is set by the caller)."""

    config: QuantConfig = field(default_factory=QuantConfig)
    informational_cooldown_seconds: float = DEFAULT_INFORMATIONAL_COOLDOWN_SECONDS
    retrigger_price_delta_pct: float = DEFAULT_RETRIGGER_PRICE_DELTA_PCT
    catalyst_lookup: CatalystLookup | None = None
    _last_emit: dict[tuple[str, str, str, str], tuple[datetime, float]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    def evaluate(
        self,
        ticker: str,
        snapshot: IndicatorSnapshot,
        *,
        htf_sma_200: float | None = None,
        daily_pivots: DailyPivots | None = None,
        now: datetime | None = None,
        profile: str = PROFILE_CONTROL,
        gate_probe: GateProbe | None = None,
    ) -> list[DirectionalAlert]:
        now = now or datetime.now(timezone.utc)
        raw: list[QuantSignal] = evaluate_signals(
            ticker, snapshot, self.config, htf_sma_200=htf_sma_200, daily_pivots=daily_pivots,
        )
        session = get_session(snapshot.bar_timestamp)
        out: list[DirectionalAlert] = []
        for sig in raw:
            direction = _DIR_MAP[sig.direction]
            key = (ticker.upper(), direction.value, sig.signal_type.value, session)
            if self._suppressed(key, now, sig.price):
                continue
            self._last_emit[key] = (now, sig.price)

            gate_status, gate_reason = TradeGateStatus.NOT_EVALUATED, None
            if gate_probe is not None:
                gate_status, gate_reason = gate_probe(sig, snapshot)

            catalyst = None
            if self.catalyst_lookup is not None:
                try:
                    catalyst = self.catalyst_lookup(ticker.upper(), snapshot.bar_timestamp)
                except Exception:  # noqa: BLE001 -- context is best-effort, never blocks an alert
                    catalyst = None

            episode_ts = _as_utc(snapshot.bar_timestamp)
            out.append(DirectionalAlert(
                alert_id=make_alert_id(
                    symbol=ticker, direction=direction.value, setup_type=sig.signal_type.value,
                    session=session, episode_ts=episode_ts,
                ),
                symbol=ticker.upper(),
                direction=direction,
                profile=profile,
                setup_type=sig.signal_type.value,
                setup_score=sig.confluence_score,
                session=MarketSession(session),
                price=sig.price,
                trade_gate_status=gate_status,
                trade_gate_reject_reason=gate_reason,
                risk_reward_ratio=sig.risk_reward_ratio,
                stop_price=sig.stop_price,
                target_price=sig.target_price,
                geometry_path=sig.geometry_path,
                message=sig.message,
                evidence=build_evidence(sig, snapshot, catalyst=catalyst),
                bar_timestamp=episode_ts,
                generated_at=now,
                episode_key="|".join(key),
            ))
        return out

    # ------------------------------------------------------------------
    def _suppressed(self, key: tuple[str, str, str, str], now: datetime, price: float) -> bool:
        prev = self._last_emit.get(key)
        if prev is None:
            return False
        last_ts, last_price = prev
        if now - last_ts >= timedelta(seconds=self.informational_cooldown_seconds):
            return False
        if last_price and abs(price - last_price) / last_price * 100.0 >= self.retrigger_price_delta_pct:
            return False  # genuine move -> allow a re-alert inside the window
        return True

    def reset(self) -> None:
        self._last_emit.clear()

    # ------------------------------------------------------------------
    # Wire-payload path -- build a DirectionalAlert straight from a published
    # QuantSignal / RejectedCandidateEvent dict (used by talonx_signals.run,
    # which reuses the real QuantScanner rather than re-warming a buffer here).
    # ------------------------------------------------------------------
    def from_wire(
        self,
        payload: dict,
        *,
        profile: str = PROFILE_CONTROL,
        trade_gate_status: TradeGateStatus = TradeGateStatus.NOT_EVALUATED,
        trade_gate_reject_reason: str | None = None,
        now: datetime | None = None,
    ) -> DirectionalAlert | None:
        now = now or datetime.now(timezone.utc)
        raw_dir = str(payload.get("direction", "")).lower()
        if "bull" in raw_dir:
            direction = AlertDirection.BULLISH
        elif "bear" in raw_dir:
            direction = AlertDirection.BEARISH
        else:
            return None
        symbol = str(payload.get("ticker") or payload.get("symbol") or "").upper()
        if not symbol:
            return None
        setup_type = str(payload.get("signal_type") or payload.get("reason") or "setup")
        session = str(payload.get("session") or "regular")
        price = payload.get("price")
        bar_ts = payload.get("bar_timestamp") or payload.get("rejected_at") or now.isoformat()
        episode_ts = _as_utc(_parse_ts(bar_ts))
        key = (symbol, direction.value, setup_type, session)
        if price is not None and self._suppressed(key, now, float(price)):
            return None
        if price is not None:
            self._last_emit[key] = (now, float(price))
        ev = SetupEvidence(
            rsi=payload.get("rsi"), macd=payload.get("macd"),
            macd_signal_line=payload.get("macd_signal_line"),
            macd_cross=_MACD_CROSS.get(_safe_signal_type(setup_type)),
            volume_surge_ratio=payload.get("volume_surge_ratio"),
            atr=payload.get("atr"),
            atr_pct=(payload["atr"] / payload["price"] * 100.0)
            if payload.get("atr") and payload.get("price") else None,
            trend_aligned=payload.get("trend_aligned"), htf_sma_200=payload.get("htf_sma_200"),
            pivot_resistance=payload.get("pivot_resistance"), pivot_support=payload.get("pivot_support"),
        )
        return DirectionalAlert(
            alert_id=make_alert_id(symbol=symbol, direction=direction.value, setup_type=setup_type,
                                   session=session, episode_ts=episode_ts),
            symbol=symbol, direction=direction, profile=profile, setup_type=setup_type,
            setup_score=payload.get("confluence_score"),
            session=MarketSession(session) if session in ("pre_market", "regular", "closed") else MarketSession.REGULAR,
            price=float(price) if price is not None else 0.0,
            trade_gate_status=trade_gate_status, trade_gate_reject_reason=trade_gate_reject_reason,
            risk_reward_ratio=payload.get("risk_reward_ratio"), stop_price=payload.get("stop_price"),
            target_price=payload.get("target_price"), geometry_path=payload.get("geometry_path"),
            message=str(payload.get("message") or payload.get("reason") or ""),
            evidence=ev, bar_timestamp=episode_ts, generated_at=now, episode_key="|".join(key),
        )


def _safe_signal_type(value: str):
    try:
        return SignalType(value)
    except ValueError:
        return None


def _parse_ts(v):
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return v


def _as_utc(ts) -> datetime:
    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
