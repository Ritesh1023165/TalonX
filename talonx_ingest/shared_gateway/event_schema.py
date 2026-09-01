"""
talonx_ingest.shared_gateway.event_schema
----------------------------------------------
The Shared Alpaca Gateway's wire contract -- an ADAPTER envelope, not a
replacement for talonx_ingest.events.schemas.MarketTickEvent or PIV's
inline feed_bar dict. Neither existing shape is changed by this module;
consumer-side adapters (original_shadow_consumer.py / piv_shadow_consumer.py)
translate GatewayMarketEvent into each side's own established shape.

See results/task88_shared_gateway/design.md §2.2 for the full rationale,
including why `event_id` is derived from (provider, symbol,
provider_timestamp, event_type) rather than invented: Alpaca's batched
`/v2/stocks/bars/latest` endpoint returns at most one bar per symbol per
minute, so that tuple is already the provider's own natural key -- the
same key talonx_quant.consumer.QuantScanner._is_new_bar_tick uses for its
own (process-local) bar dedup, made portable across independent consumer
groups.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


def compute_event_id(
    provider: str, symbol: str, provider_timestamp: datetime, event_type: str,
    provider_sequence: str | None = None,
) -> str:
    """Deterministic, content-derived event identity for duplicate
    detection. Folds in `provider_sequence` only when the provider actually
    supplies one (never fabricated) -- see module docstring."""
    parts = [provider, symbol.upper(), provider_timestamp.isoformat(), event_type]
    if provider_sequence:
        parts.append(provider_sequence)
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


class GatewayMarketEvent(BaseModel):
    """One normalized market-data event on `talonx:gateway:alpaca:market:v1`."""

    schema_version: int = SCHEMA_VERSION
    event_id: str
    symbol: str
    event_type: Literal["bar"] = "bar"
    provider: Literal["ALPACA"] = "ALPACA"
    provider_feed: str  # "iex" | "sip"
    provider_timestamp: datetime  # the bar's own close-time, as reported by Alpaca
    gateway_receive_timestamp: datetime  # wall-clock when the gateway's HTTP call returned

    open: float
    high: float
    low: float
    close: float
    volume: float
    price: float  # mirrors `close` -- consumer-shape parity with MarketTickEvent/feed_bar

    # Alpaca's batched-bars endpoint has no native per-bar sequence id --
    # always None for this producer. Kept so a future streaming producer
    # (which does receive a per-message sequence) needs no schema change.
    provider_sequence: str | None = None

    gateway_session_id: str  # UUID4, one per gateway process lifetime
    poll_cycle_id: str  # UUID4, one per poll cycle -- groups bars from the same HTTP round-trip

    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_redis_payload(cls, raw: str | bytes) -> "GatewayMarketEvent":
        return cls.model_validate_json(raw)


def build_event(
    *, symbol: str, provider_feed: str, provider_timestamp: datetime,
    gateway_receive_timestamp: datetime, open_: float, high: float, low: float,
    close: float, volume: float, gateway_session_id: str, poll_cycle_id: str,
    provider_sequence: str | None = None,
) -> GatewayMarketEvent:
    """Single construction path so `event_id` is always derived consistently
    -- callers never set it directly."""
    event_id = compute_event_id("ALPACA", symbol, provider_timestamp, "bar", provider_sequence)
    return GatewayMarketEvent(
        event_id=event_id, symbol=symbol.upper(), provider_feed=provider_feed,
        provider_timestamp=provider_timestamp, gateway_receive_timestamp=gateway_receive_timestamp,
        open=open_, high=high, low=low, close=close, volume=volume, price=close,
        provider_sequence=provider_sequence, gateway_session_id=gateway_session_id,
        poll_cycle_id=poll_cycle_id,
    )
