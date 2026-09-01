"""
talonx_ingest.shared_gateway.piv_shadow_consumer
--------------------------------------------------------
Read-only shadow consumer for "PIV-compatible" input equivalence (Phase 5
offline replay + Phase 7 live coverage counting). Maps each
GatewayMarketEvent to the EXACT dict shape talonx_piv.decision_engine.
DecisionEngine.feed_bar already builds inline before calling
scanner._handle_market_tick -- see architecture_before.md §2/§15.
talonx_piv.decision_engine is NOT imported here.

SHADOW_INGESTION_ONLY: the default `sink` (inherited from
ShadowConsumerBase) is a no-op counter. Only Phase 5's offline replay
script explicitly injects a sink that calls a FRESHSTANDING DecisionEngine/
QuantScanner pair -- never the real, live-running PIV session (which owns
its own execution ownership lock and broker client this module never
references).
"""
from __future__ import annotations

from dataclasses import dataclass

from .event_schema import GatewayMarketEvent
from .redis_stream import PIV_SHADOW_GROUP
from .shadow_consumer_base import ShadowConsumerBase


@dataclass(kw_only=True)
class PivShadowConsumer(ShadowConsumerBase):
    group: str = PIV_SHADOW_GROUP

    def _map(self, event: GatewayMarketEvent) -> dict:
        return {
            "event_type": event.event_type,
            "symbol": event.symbol,
            "source": "polling",
            "timestamp": event.provider_timestamp.isoformat(),
            "open": event.open,
            "high": event.high,
            "low": event.low,
            "close": event.close,
            "volume": event.volume,
            "price": event.price,
            "gateway_event_id": event.event_id,
        }
