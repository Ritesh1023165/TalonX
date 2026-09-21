"""
Task 89 -- integrated dual-consumer harness.
Mode: MARKET_DATA_PLUS_STRATEGY_EVAL, EXECUTION_WITHHELD.

Each Task 88 shadow consumer is wired to a real, ISOLATED QuantScanner:
  * Original-role -> Redis db 3, channels `talonx:t89orig:*`
  * PIV-role      -> Redis db 4, channels `talonx:t89piv:*`
The gateway Stream stays on db 2. Redis db 0 (Original) and db 1 (PIV) are
NEVER touched.

Why a bare QuantScanner and not a DecisionEngine: the market-data boundary
BOTH runtimes use is `QuantScanner._handle_market_tick(dict)`.
`talonx_piv.decision_engine.DecisionEngine.feed_bar` is a one-line wrapper
that builds exactly the dict `PivShadowConsumer._map` already produces and
calls `_handle_market_tick`. Everything downstream of signal *publication*
(decision recording, broker `order_intent`) is deliberately NOT wired here
-- that is the structural execution-withheld boundary for Task 89's
offline rehearsal (see results/task89_dual_consumer_rehearsal/
execution_safety.md). No broker / lifecycle / DecisionEngine object is
constructed or imported by this module.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from talonx_ingest.shared_gateway import redis_stream as rs
from talonx_ingest.shared_gateway.original_shadow_consumer import OriginalShadowConsumer
from talonx_ingest.shared_gateway.piv_shadow_consumer import PivShadowConsumer
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover
    redis_asyncio = None

ORIG_REDIS_URL = "redis://localhost:6379/3"
PIV_REDIS_URL = "redis://localhost:6379/4"
GATEWAY_STREAM_KEY = "talonx:gateway:alpaca:market:v1"
GATEWAY_REDIS_URL = "redis://localhost:6379/2"

# Every Redis key either role's isolated scanner can create -- asserted
# before any flushdb in the test fixture, so a misconfiguration that
# pointed a scanner at db 0/1 is caught instead of silently wiping data.
ALLOWED_ISOLATED_KEY_PREFIXES = ("talonx:t89", "processed_bar:", "metrics:", "quant:")


class SinkFailure(RuntimeError):
    """Raised by a role's sink to simulate a downstream processing failure
    for the failure-isolation test -- leaves the Stream entry un-acked so
    the redelivery / dead-letter machinery is exercised."""


def isolated_quant_config(role: str, redis_url: str) -> QuantConfig:
    ns = f"talonx:t89{role}"
    return dataclasses.replace(
        QuantConfig(),
        redis_url=redis_url,
        market_stream_channel=f"{ns}:market:stream",
        signals_channel=f"{ns}:signals:quant",
        rejected_candidates_channel=f"{ns}:quant:rejected",
        news_events_channel=f"{ns}:news:events",
        paper_trades_channel=f"{ns}:paper:trades",
        historical_preseed_enabled=False,  # no network warm-up during the rehearsal
        enable_persistence=False,          # no sqlite; store stays None regardless
    )


@dataclass
class RoleRuntime:
    """One side of the integrated rehearsal: a shadow consumer + its
    isolated QuantScanner + the counters Phase 4 asserts on."""

    role: str
    redis_url: str
    scanner: QuantScanner
    consumer: Any  # OriginalShadowConsumer | PivShadowConsumer
    scanner_client: Any = None
    fail_on_event_id: str | None = None
    downstream_ticks: int = 0
    sink_errors: int = 0
    last_event_id: str | None = None
    received: list[dict] = field(default_factory=list)

    async def sink(self, mapped: dict) -> None:
        eid = mapped.get("gateway_event_id")
        if self.fail_on_event_id is not None and eid == self.fail_on_event_id:
            self.sink_errors += 1
            raise SinkFailure(f"{self.role} simulated downstream failure on {eid}")
        self.received.append(mapped)
        self.downstream_ticks += 1
        self.last_event_id = eid
        await self.scanner._handle_market_tick(mapped)

    def stats(self) -> dict:
        c = self.consumer.counters
        return {
            "role": self.role,
            "events_consumed": c.events_consumed,
            "deserialize_failed": c.events_deserialize_failed,
            "dead_lettered": c.events_dead_lettered,
            "reconnect_attempts": c.reconnect_attempts,
            "downstream_ticks": self.downstream_ticks,
            "sink_errors": self.sink_errors,
            "scanner_bars_processed": self.scanner._bars_processed,
            "last_event_id": self.last_event_id,
        }

    async def aclose(self) -> None:
        """Simulate the role's process going away: drop both the isolated
        scanner's Redis client and the shadow consumer's own Stream client."""
        for client in (self.scanner_client, getattr(self.consumer, "_client", None)):
            try:
                if client is not None:
                    await client.aclose()
            except Exception:
                pass
        if self.consumer is not None:
            self.consumer._client = None


async def _make_scanner(role: str, redis_url: str, *, attach_redis: bool) -> tuple[QuantScanner, Any]:
    scanner = QuantScanner(isolated_quant_config(role, redis_url))
    client = None
    if attach_redis and redis_asyncio is not None:
        client = redis_asyncio.from_url(redis_url)
        await client.ping()
        scanner._client = client
    return scanner, client


async def make_original_role(
    *, stream_key: str, stream_redis_url: str = GATEWAY_REDIS_URL,
    group: str = "original_shadow", consumer_name: str = "t89-original-1",
    group_start_id: str = "$", claim_min_idle_ms: int = 30_000,
    attach_redis: bool = True, fail_on_event_id: str | None = None,
) -> RoleRuntime:
    scanner, client = await _make_scanner("orig", ORIG_REDIS_URL, attach_redis=attach_redis)
    rt = RoleRuntime(role="original", redis_url=ORIG_REDIS_URL, scanner=scanner,
                     consumer=None, scanner_client=client, fail_on_event_id=fail_on_event_id)
    rt.consumer = OriginalShadowConsumer(
        group=group, consumer_name=consumer_name, redis_url=stream_redis_url,
        key=stream_key, sink=rt.sink, group_start_id=group_start_id,
        claim_min_idle_ms=claim_min_idle_ms,
    )
    await rt.consumer._connect()  # eager: the consumer group exists once the "process" is up
    return rt


async def make_piv_role(
    *, stream_key: str, stream_redis_url: str = GATEWAY_REDIS_URL,
    group: str = "piv_shadow", consumer_name: str = "t89-piv-1",
    group_start_id: str = "$", claim_min_idle_ms: int = 30_000,
    attach_redis: bool = True, fail_on_event_id: str | None = None,
) -> RoleRuntime:
    scanner, client = await _make_scanner("piv", PIV_REDIS_URL, attach_redis=attach_redis)
    rt = RoleRuntime(role="piv", redis_url=PIV_REDIS_URL, scanner=scanner,
                     consumer=None, scanner_client=client, fail_on_event_id=fail_on_event_id)
    rt.consumer = PivShadowConsumer(
        group=group, consumer_name=consumer_name, redis_url=stream_redis_url,
        key=stream_key, sink=rt.sink, group_start_id=group_start_id,
        claim_min_idle_ms=claim_min_idle_ms,
    )
    await rt.consumer._connect()  # eager: the consumer group exists once the "process" is up
    return rt


async def drain_until_idle(role: RoleRuntime, *, max_rounds: int = 200) -> int:
    """Pump the consumer one iteration at a time until it stops making
    progress (consumed + dead-lettered stops advancing). Returns rounds used."""
    prev = -1
    for rounds in range(1, max_rounds + 1):
        c = role.consumer.counters
        marker = (c.events_consumed + c.events_dead_lettered
                  + c.events_deserialize_failed + role.sink_errors)
        if marker == prev:
            return rounds
        prev = marker
        await role.consumer.run(max_iterations=1)
    return max_rounds


async def drain_both_until_idle(a: RoleRuntime, b: RoleRuntime, *, max_rounds: int = 400) -> None:
    prev = None
    for _ in range(max_rounds):
        for r in (a, b):
            await r.consumer.run(max_iterations=1)
        ca, cb = a.consumer.counters, b.consumer.counters
        marker = (
            ca.events_consumed + ca.events_dead_lettered + ca.events_deserialize_failed + a.sink_errors,
            cb.events_consumed + cb.events_dead_lettered + cb.events_deserialize_failed + b.sink_errors,
        )
        if marker == prev:
            return
        prev = marker


# --------------------------------------------------------------------------
# Standalone SINGLE-ROLE runner (Phase 7 live use only -- NOT exercised by
# the offline tests). One process per role => true failure isolation and an
# independently kill/restartable consumer for the controlled restart test.
# Writes a stats line (incl. a freshness monitor) every ~30s and keeps a
# live dump of its received event_ids for the common-input comparison.
# --------------------------------------------------------------------------
_LIVENESS_KEY = "talonx:gateway:alpaca:liveness"


async def _gateway_liveness(stream_redis_url: str) -> dict:  # pragma: no cover
    """Read the gateway's own liveness beacon (TTL 90s on db2). Never raises."""
    if redis_asyncio is None:
        return {"present": False, "error": "redis missing"}
    c = redis_asyncio.from_url(stream_redis_url)
    try:
        raw = await c.get(_LIVENESS_KEY)
        if raw is None:
            return {"present": False}
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw.decode() if isinstance(raw, bytes) else str(raw)}
        return {"present": True, "payload": payload}
    except Exception as exc:  # noqa: BLE001
        return {"present": False, "error": repr(exc)}
    finally:
        await c.aclose()


def _freshness(role: RoleRuntime) -> dict:  # pragma: no cover
    """Stale gateway data must be VISIBLE, never silently replayed as fresh
    (Phase 5 requirement). Reports the newest provider_timestamp this role
    has seen and how stale it is vs wall clock."""
    from datetime import datetime, timezone

    ts_list = [m.get("timestamp") for m in role.received if m.get("timestamp")]
    if not ts_list:
        return {"max_provider_timestamp_seen": None, "provider_staleness_seconds": None}
    newest = max(ts_list)
    try:
        dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
        stale = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        stale = None
    return {"max_provider_timestamp_seen": newest, "provider_staleness_seconds": stale}


async def _run_single_role(role_name: str, duration_seconds: float, out_dir: Path,
                           report_seconds: float = 30.0) -> None:  # pragma: no cover
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = out_dir / f"t89_{role_name}_stats.jsonl"
    ids_path = out_dir / f"t89_{role_name}_event_ids.json"

    consumer_name = f"t89-live-{role_name}-1"
    if role_name == "original":
        role = await make_original_role(stream_key=GATEWAY_STREAM_KEY, group="original_shadow",
                                        consumer_name=consumer_name)
    elif role_name == "piv":
        role = await make_piv_role(stream_key=GATEWAY_STREAM_KEY, group="piv_shadow",
                                   consumer_name=consumer_name)
    else:
        raise SystemExit(f"--role must be 'original' or 'piv', got {role_name!r}")

    import signal as _signal

    stop_at = time.monotonic() + duration_seconds
    stopping = {"v": False}

    def _stop(*_a):
        stopping["v"] = True
        role.consumer.stop()

    for sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            _signal.signal(sig, _stop)
        except Exception:
            pass

    print(f"[{role_name}] started pid={__import__('os').getpid()} consumer={consumer_name} "
          f"duration={duration_seconds}s", flush=True)

    last_report = 0.0
    while not stopping["v"] and time.monotonic() < stop_at:
        try:
            await role.consumer.run(max_iterations=1)
        except Exception as exc:  # noqa: BLE001
            print(f"[{role_name}] loop error: {exc!r}", flush=True)
            role.consumer._client = None
        now = time.monotonic()
        if now - last_report >= report_seconds:
            last_report = now
            liveness = await _gateway_liveness(role.consumer.redis_url)
            seen_ids = [m["gateway_event_id"] for m in role.received]
            line = {
                "ts": time.time(),
                "role": role_name,
                "stats": role.stats(),
                "received_id_count": len(seen_ids),
                "unique_id_count": len(set(seen_ids)),
                "freshness": _freshness(role),
                "gateway_liveness_present": liveness.get("present"),
                "gateway_liveness": liveness.get("payload"),
            }
            with stats_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
            ids_path.write_text(json.dumps({"role": role_name, "ts": time.time(),
                                            "event_ids": seen_ids}, indent=0), encoding="utf-8")
            print(json.dumps(line), flush=True)
        await asyncio.sleep(1.0)

    # final flush
    seen_ids = [m["gateway_event_id"] for m in role.received]
    ids_path.write_text(json.dumps({"role": role_name, "ts": time.time(), "final": True,
                                    "event_ids": seen_ids}, indent=0), encoding="utf-8")
    with stats_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.time(), "role": role_name, "final": True,
                             "stats": role.stats(), "received_id_count": len(seen_ids),
                             "unique_id_count": len(set(seen_ids))}) + "\n")
    await role.aclose()
    print(f"[{role_name}] stopped cleanly. consumed={role.consumer.counters.events_consumed} "
          f"unique_ids={len(set(seen_ids))}", flush=True)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["original", "piv"])
    ap.add_argument("--duration-seconds", type=float, default=600.0)
    ap.add_argument("--out-dir", default="results/task89_dual_consumer_rehearsal/live")
    a = ap.parse_args()
    asyncio.run(_run_single_role(a.role, a.duration_seconds, Path(a.out_dir)))
