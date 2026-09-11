"""
talonx_ingest.shared_gateway.metrics
------------------------------------------
Gateway-stage telemetry writer -- deliberately mirrors
talonx_ingest.events.publisher.RedisEventPublisher's own metric/liveness/
coverage conventions (same `metrics:{YYYY-MM-DD}:{stage}:{counter}` key
shape, same "never raise, log and continue" posture, same 32-day TTL) so
Task 88's gateway is observable the same way every other TalonX component
already is, per this project's "no internal library between modules"
convention (this file is not shared/imported by talonx_ingest.events.
publisher; it is a new, independent copy for stage="gateway").
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("talonx_ingest.shared_gateway.metrics")

STAGE = "gateway"
LIVENESS_KEY = "talonx:gateway:alpaca:liveness"
LIVENESS_TTL_SECONDS = 90
SYMBOL_COVERAGE_KEY = "talonx:gateway:alpaca:symbol_coverage"
SYMBOL_COVERAGE_TTL_SECONDS = 360
CONSUMER_LAG_KEY_TEMPLATE = "talonx:gateway:alpaca:consumer_lag:{group}"
CONSUMER_LAG_TTL_SECONDS = 90

_METRIC_TTL_SECONDS = 2764800  # 32 days, matches every other `metrics:*` key in the project


async def incr_metric(client, counter: str, amount: int = 1) -> None:
    """Same shape/semantics as every other module's local incr_metric copy
    (talonx_ingest.events.publisher, talonx_quant.consumer, ...). Never
    raises -- a metrics-write failure must not affect ingestion."""
    if client is None or amount <= 0:
        return
    key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{STAGE}:{counter}"
    try:
        new_value = await client.incrby(key, amount)
        if new_value == amount:
            await client.expire(key, _METRIC_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- telemetry must never break ingestion
        logger.warning("Gateway metric increment failed for %s: %s", key, exc)


async def write_liveness(client, payload: dict) -> bool:
    if client is None:
        return False
    try:
        await client.set(LIVENESS_KEY, json.dumps(payload), ex=LIVENESS_TTL_SECONDS)
        return True
    except Exception as exc:  # noqa: BLE001 -- a liveness write must never crash the gateway
        logger.warning("Failed to write gateway liveness beat: %s", exc)
        return False


async def write_symbol_coverage(client, coverage: dict) -> bool:
    if client is None:
        return False
    try:
        await client.set(SYMBOL_COVERAGE_KEY, json.dumps(coverage), ex=SYMBOL_COVERAGE_TTL_SECONDS)
        return True
    except Exception as exc:  # noqa: BLE001 -- coverage telemetry must never break ingestion
        logger.debug("Failed to write gateway symbol coverage: %s", exc)
        return False


async def write_consumer_lag(client, group: str, lag: int | None) -> bool:
    if client is None or lag is None:
        return False
    key = CONSUMER_LAG_KEY_TEMPLATE.format(group=group)
    try:
        await client.set(key, str(lag), ex=CONSUMER_LAG_TTL_SECONDS)
        return True
    except Exception as exc:  # noqa: BLE001 -- lag telemetry must never break a consumer
        logger.debug("Failed to write consumer lag for %s: %s", group, exc)
        return False
