"""
talonx_v2.bus -- thin Redis pub/sub for the V2 wire contracts (Task 111)
====================================================================
V2's stage objects (``V2QuantSignal`` / ``V2Decision`` / ``V2Alert`` /
``V2PaperTrade``) are normally passed between stage functions in-process.
This module publishes/consumes them on the dedicated ``talonx:v2:*``
channels so an E2E harness can prove the JSON wire contracts round-trip,
exactly the "listens to a Redis channel" convention the other services
use.

It is OPTIONAL infrastructure -- the pipeline works without it.  Nothing
here touches ``talonx:market:stream`` or any Original channel.
"""
from __future__ import annotations

import json
from typing import Iterator

from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Alert, V2Decision, V2PaperTrade, V2QuantSignal

_MODEL_FOR_CHANNEL = {}


def _redis(url: str | None = None):
    import redis

    return redis.Redis.from_url(url or "redis://localhost:6379/0", decode_responses=True)


class V2Bus:
    def __init__(self, url: str | None = None, config: V2Config | None = None):
        self.cfg = config or V2Config()
        self.r = _redis(url)
        self._map = {
            self.cfg.redis_channel_signal: V2QuantSignal,
            self.cfg.redis_channel_decision: V2Decision,
            self.cfg.redis_channel_alert: V2Alert,
            self.cfg.redis_channel_trade: V2PaperTrade,
        }

    # ---- publish ----
    def publish_signal(self, sig: V2QuantSignal) -> int:
        return self.r.publish(self.cfg.redis_channel_signal, sig.to_redis_payload())

    def publish_decision(self, dec: V2Decision) -> int:
        return self.r.publish(self.cfg.redis_channel_decision, dec.to_redis_payload())

    def publish_alert(self, alert: V2Alert) -> int:
        return self.r.publish(self.cfg.redis_channel_alert, alert.to_redis_payload())

    def publish_trade(self, tr: V2PaperTrade) -> int:
        return self.r.publish(self.cfg.redis_channel_trade, tr.to_redis_payload())

    # ---- subscribe ----
    def subscribe(self, *channels: str):
        ps = self.r.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(*(channels or tuple(self._map)))
        # prime the connection: redis-py establishes the pubsub socket
        # lazily -- one get_message() call pumps the SUBSCRIBE handshake so
        # a publish issued immediately afterwards actually has a receiver.
        ps.get_message(timeout=1.0)
        return ps

    def listen(self, ps, *, count: int | None = None, timeout: float = 5.0) -> Iterator:
        """Yield parsed model objects from a pubsub handle until ``count``
        messages seen or ``timeout`` s of wall-clock silence.

        redis-py's ``get_message(timeout=...)`` can return ``None`` on the
        first few polls even when a message is already buffered, so we
        drive a wall-clock deadline rather than bailing on the first
        ``None``.
        """
        import time as _t

        seen = 0
        deadline = _t.monotonic() + timeout
        while _t.monotonic() < deadline:
            msg = ps.get_message(timeout=0.2)
            if msg is None:
                continue
            if msg.get("type") != "message":
                continue
            model = self._map.get(msg["channel"])
            if model is None:
                continue
            yield model.model_validate(json.loads(msg["data"]))
            seen += 1
            deadline = _t.monotonic() + timeout   # reset idle window after a hit
            if count is not None and seen >= count:
                return
