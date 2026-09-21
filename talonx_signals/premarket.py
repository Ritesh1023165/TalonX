"""Task 99A S3.5 -- pre-market informational assembly.

Pure assembly over ALREADY-AVAILABLE data (previous close, latest
extended-hours quote, pre-market volume, upcoming-earnings calendar, 96A
overnight SEC events). NO regular-session MACD/RSI evaluation is forced onto
extended-hours bars -- pre-market produces WATCH / GAP / RADAR / event-context
items only. Regular-session technical directional evaluation is
DirectionalAlertEngine's job, RTH only.

Gap bias reuses talonx_piv.premarket_radar.classify() unchanged (the existing,
structurally order-free radar classifier -- it has no import of broker/
lifecycle, so nothing here can ever place an order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_piv.premarket_radar import classify as _radar_classify

from talonx_signals.schemas import (
    MarketSession,
    PremarketBundle,
    PremarketWatch,
    WatchKind,
    make_watch_id,
)

DEFAULT_GAP_WATCH_PCT = 1.0        # BULLISH/BEARISH WATCH bias boundary (label only)
DEFAULT_GAP_MOVER_PCT = 2.0       # |gap| at/above this -> a GAP_UP / GAP_DOWN mover
DEFAULT_ABNORMAL_VOLUME_X = 3.0   # pre-market volume vs its own trailing average


@dataclass(frozen=True)
class PremarketSymbolInput:
    symbol: str
    prev_close: float | None = None
    latest_price: float | None = None
    latest_volume: float | None = None
    avg_premarket_volume: float | None = None
    earnings_when: str | None = None            # e.g. "2026-09-05 BMO"
    overnight_events: tuple[str, ...] = ()       # short labels from 96A intelligence


@dataclass
class PremarketWatchEngine:
    gap_watch_pct: float = DEFAULT_GAP_WATCH_PCT
    gap_mover_pct: float = DEFAULT_GAP_MOVER_PCT
    abnormal_volume_x: float = DEFAULT_ABNORMAL_VOLUME_X

    def assess(
        self,
        inputs: list[PremarketSymbolInput],
        *,
        now: datetime | None = None,
        watchlist_configured: int = 0,
        watchlist_active: int = 0,
    ) -> PremarketBundle:
        now = now or datetime.now(timezone.utc)
        day = now
        bundle = PremarketBundle(
            as_of=now,
            watchlist_configured=watchlist_configured or len(inputs),
            watchlist_active=watchlist_active or len(inputs),
        )
        covered = 0
        for item in inputs:
            sym = item.symbol.upper()

            if item.earnings_when:
                bundle.radar.append(PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind="RADAR", day=day),
                    symbol=sym, kind=WatchKind.RADAR, reference_price=item.latest_price,
                    prev_close=item.prev_close, detail=f"Reports {item.earnings_when}",
                    reason_codes=("SCHEDULED_EARNINGS",),
                ))

            for label in item.overnight_events:
                bundle.event_context.append(PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind="EVENT_CONTEXT", day=day, bias=label),
                    symbol=sym, kind=WatchKind.EVENT_CONTEXT, reference_price=item.latest_price,
                    prev_close=item.prev_close, detail=label, reason_codes=("OVERNIGHT_SEC_EVENT",),
                ))

            obs = _radar_classify(
                sym, item.prev_close, item.latest_price, item.latest_volume,
                gap_watch_threshold_pct=self.gap_watch_pct,
            )
            if obs.data_status != "READY":
                continue
            covered += 1
            gap_pct = obs.gap_pct

            if gap_pct is not None and abs(gap_pct) >= self.gap_mover_pct:
                kind = WatchKind.GAP_UP if gap_pct > 0 else WatchKind.GAP_DOWN
                w = PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind=kind.value, day=day),
                    symbol=sym, kind=kind, reference_price=item.latest_price,
                    prev_close=item.prev_close, gap_pct=gap_pct,
                    detail=f"{gap_pct:+.2f}% vs prior close",
                    reason_codes=obs.reason_codes,
                )
                (bundle.gap_up if gap_pct > 0 else bundle.gap_down).append(w)

            if obs.bias == "BULLISH":
                bundle.bullish_watch.append(PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind="BULLISH_WATCH", day=day, bias="BULLISH"),
                    symbol=sym, kind=WatchKind.BULLISH_WATCH, reference_price=item.latest_price,
                    prev_close=item.prev_close, gap_pct=gap_pct, detail=f"Pre-market gap up {gap_pct:+.2f}%",
                    reason_codes=obs.reason_codes,
                ))
            elif obs.bias == "BEARISH":
                bundle.bearish_watch.append(PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind="BEARISH_WATCH", day=day, bias="BEARISH"),
                    symbol=sym, kind=WatchKind.BEARISH_WATCH, reference_price=item.latest_price,
                    prev_close=item.prev_close, gap_pct=gap_pct, detail=f"Pre-market gap down {gap_pct:+.2f}%",
                    reason_codes=obs.reason_codes,
                ))

            if (
                item.avg_premarket_volume
                and item.avg_premarket_volume > 0
                and item.latest_volume is not None
                and item.latest_volume / item.avg_premarket_volume >= self.abnormal_volume_x
            ):
                ratio = item.latest_volume / item.avg_premarket_volume
                bundle.abnormal_volume.append(PremarketWatch(
                    watch_id=make_watch_id(symbol=sym, kind="ABNORMAL_VOLUME", day=day),
                    symbol=sym, kind=WatchKind.ABNORMAL_VOLUME, reference_price=item.latest_price,
                    prev_close=item.prev_close, detail=f"{ratio:.1f}x avg pre-market volume",
                    reason_codes=("PREMARKET_VOLUME_SURGE",),
                ))

        bundle.watchlist_covered = covered
        if covered < bundle.watchlist_active:
            bundle.notes.append(
                f"{bundle.watchlist_active - covered} of {bundle.watchlist_active} active "
                "symbols had no usable pre-market quote"
            )
        return bundle
