"""
talonx_ingest.shared_gateway.original_shadow_consumer
------------------------------------------------------------
Read-only shadow consumer for "Original-compatible" input equivalence
(Phase 5 offline replay + Phase 7 live coverage counting). Maps each
GatewayMarketEvent to the SAME dict shape talonx_ingest.events.schemas.
MarketTickEvent carries -- talonx_ingest.events.schemas is not imported/
constructed here to avoid any accidental coupling to the live publisher;
this only reproduces its field shape as a plain dict, which is all
talonx_quant.consumer.QuantScanner._handle_market_tick actually consumes.

SHADOW_INGESTION_ONLY: the default `sink` (inherited from
ShadowConsumerBase) is a no-op counter. Only Phase 5's offline replay
script explicitly injects a sink that calls a FRESHSTANDING QuantScanner
instance's _handle_market_tick -- never the real, live-running Original
process.
"""
from __future__ import annotations

from dataclasses import dataclass

from .event_schema import GatewayMarketEvent
from .redis_stream import ORIGINAL_SHADOW_GROUP
from .shadow_consumer_base import ShadowConsumerBase


@dataclass(kw_only=True)
class OriginalShadowConsumer(ShadowConsumerBase):
    group: str = ORIGINAL_SHADOW_GROUP

    def _map(self, event: GatewayMarketEvent) -> dict:
        # source is pinned to "polling" (not "gateway") because
        # talonx_quant.schemas.TickSource only accepts "websocket"/
        # "polling" -- the SAME MarketTickEvent contract QuantScanner
        # already validates against. The gateway's actual origin is
        # preserved separately via `gateway_event_id`.
        return {
            "event_type": event.event_type,
            "symbol": event.symbol,
            "source": "polling",
            "timestamp": event.provider_timestamp.isoformat(),
            "price": event.price,
            "volume": event.volume,
            "open": event.open,
            "high": event.high,
            "low": event.low,
            "close": event.close,
            "published_at": event.published_at.isoformat(),
            "gateway_event_id": event.event_id,
        }
