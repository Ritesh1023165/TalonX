"""Task 99A -- supervised experimental + directional lane.

Runs ALONGSIDE ``python run_talonx.py`` (CONTROL, unchanged) as its own
process -- the same "separate process" pattern PIV, the Streamlit dashboard,
and dashboard_web.py already use. It never imports or mutates the CONTROL
pipeline.

What it does:
  * starts a SECOND QuantScanner bound to EXPERIMENTAL_RELAXED_V1 (relaxed
    thresholds via dataclasses.replace, isolated talonx:exp:* channels +
    exp_quant.db) -- reuses the real scanner, so buffer/indicator/warmup
    logic is identical to CONTROL, only the three gate thresholds differ;
  * subscribes to CONTROL (talonx:signals:quant / talonx:quant:rejected) AND
    experimental (talonx:exp:signals:quant / talonx:exp:quant:rejected)
    channels, turning every candidate -- passed OR gate-rejected -- into an
    informational DirectionalAlert (decoupled from the trade gate);
  * for an experimental candidate that PASSED the relaxed gates, opens an
    experimental paper BUY (isolated experimental_paper.db, local sim, no
    real capital, long-only);
  * records forward-outcome telemetry for every alert and trade;
  * dispatches Telegram cards (dry-run unless --enable-external-send);
  * serves the experimental dashboard.

Modes:
  --offline   open stores + build the dashboard app + print readiness, then
              exit 0. No Redis, no market subscription. This is the S8 smoke.
  (default)   full live lane. Ctrl+C for graceful shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone

from talonx_signals.config import ExperimentalConfig, validate_experimental_isolation
from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.dashboard import ExperimentalDashboard
from talonx_signals.directional import DirectionalAlertEngine
from talonx_signals.dispatcher import ExperimentalDispatcher, NullSender, TelegramSenderAdapter
from talonx_signals.experimental_paper import ExperimentalPaperEngine
from talonx_signals.intelligence_bridge import (
    BridgeMetrics,
    EarningsRadarBridge,
    PostEarningsBridge,
    bridge_health,
    overnight_event_labels,
)
from talonx_signals.premarket import PremarketSymbolInput, PremarketWatchEngine
from talonx_signals.relaxed_profile import assert_control_profile_unchanged, build_experimental_quant_config
from talonx_signals.schemas import PROFILE_CONTROL, PROFILE_EXPERIMENTAL, TradeGateStatus
from talonx_signals.telemetry import ForwardOutcomeRecorder, ForwardOutcomeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("talonx_signals.run")

_CONTROL_SIGNALS = "talonx:signals:quant"
_CONTROL_REJECTED = "talonx:quant:rejected"


def _parse_event_ts(raw: str | None) -> datetime | None:
    """Task 99G -- the bar's OWN market timestamp (never wall-clock "now"),
    for causal forward-outcome advancement. Returns None (never fabricates a
    time) if the payload carries no usable timestamp -- that bar is simply
    not used to advance telemetry, same fail-closed posture as everywhere
    else in this module."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ExperimentalLane:
    def __init__(self, cfg: ExperimentalConfig, *, enable_external_send: bool = False):
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.alert_store = ExperimentalAlertStore(cfg.quant_db_path.parent / "exp_alerts.db")
        self.outcome_store = ForwardOutcomeStore(cfg.telemetry_db_path)
        self.paper = ExperimentalPaperEngine(db_path=cfg.paper_db_path)
        self.recorder = ForwardOutcomeRecorder(self.outcome_store)
        sender = TelegramSenderAdapter() if enable_external_send else NullSender()
        self.dispatcher = ExperimentalDispatcher(
            store=self.alert_store, sender=sender, enable_external_send=enable_external_send,
        )
        self.dir_control = DirectionalAlertEngine()
        self.dir_experimental = DirectionalAlertEngine(config=build_experimental_quant_config(cfg))
        # Task 99B -- live intelligence bridge
        self.radar_bridge = EarningsRadarBridge()
        self.post_earnings_bridge = PostEarningsBridge()
        self.bridge_metrics = BridgeMetrics()
        self.premarket_engine = PremarketWatchEngine()
        self._intel_api = None            # lazily opened IntelligenceReadAPI
        self._watchlist = None
        self._last_price: dict[str, float] = {}
        self._premarket_bundle = None
        self._effective_symbols: list[str] = []
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    async def handle_message(self, channel: str, payload: dict) -> None:
        if channel in (_CONTROL_SIGNALS, self.cfg.signals_channel):
            profile = PROFILE_CONTROL if channel == _CONTROL_SIGNALS else PROFILE_EXPERIMENTAL
            eng = self.dir_control if profile == PROFILE_CONTROL else self.dir_experimental
            alert = eng.from_wire(payload, profile=profile,
                                  trade_gate_status=TradeGateStatus.WOULD_PASS)
            if alert:
                await self.dispatcher.dispatch_directional(alert)
                self.recorder.open_from_directional(alert)
            if profile == PROFILE_EXPERIMENTAL and str(payload.get("direction", "")).lower().startswith("bull"):
                await self._maybe_open_experimental(payload)
        elif channel in (_CONTROL_REJECTED, self.cfg.rejected_candidates_channel):
            profile = PROFILE_CONTROL if channel == _CONTROL_REJECTED else PROFILE_EXPERIMENTAL
            eng = self.dir_control if profile == PROFILE_CONTROL else self.dir_experimental
            reason = str(payload.get("reason") or payload.get("gate") or "")
            # only "quality"-gate rejections become informational setups; a
            # blackout / cooldown / session-closed rejection is operational noise.
            if reason.upper() in ("LOW_VOLATILITY", "LOW_CONFLUENCE", "LOW_RISK_REWARD",
                                  "HTF_DATA_UNAVAILABLE", "TREND_GATE"):
                alert = eng.from_wire(payload, profile=profile,
                                      trade_gate_status=TradeGateStatus.WOULD_REJECT,
                                      trade_gate_reject_reason=reason)
                if alert:
                    await self.dispatcher.dispatch_directional(alert)
                    self.recorder.open_from_directional(alert)

    async def _maybe_open_experimental(self, sig: dict) -> None:
        symbol = str(sig.get("ticker") or sig.get("symbol") or "").upper()
        price = sig.get("price")
        if not symbol or price is None:
            return
        atr = sig.get("atr")
        atr_pct = (atr / price * 100.0) if atr and price else None
        trade = self.paper.open_long(
            symbol, float(price), stop=sig.get("stop_price"), target=sig.get("target_price"),
            setup=sig.get("signal_type"), setup_score=sig.get("confluence_score"),
            risk_reward_ratio=sig.get("risk_reward_ratio"), atr_pct=atr_pct,
        )
        if trade:
            await self.dispatcher.dispatch_trade(trade)
            self.recorder.open_from_trade(trade, atr_pct=atr_pct)
            logger.info("experimental paper BUY %s @ %.2f (admitted_by=%s)",
                        symbol, trade["entry"], trade["admitted_by"])

    # ------------------------------------------------------------------
    async def consume(self) -> None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self.cfg.redis_url, decode_responses=True)
        pubsub = client.pubsub()
        channels = [_CONTROL_SIGNALS, _CONTROL_REJECTED,
                    self.cfg.signals_channel, self.cfg.rejected_candidates_channel]
        channels = channels + ["talonx:market:stream"]   # price cache only (read-only)
        await pubsub.subscribe(*channels)
        logger.info("subscribed: %s", channels)
        try:
            while not self._stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    continue
                try:
                    payload = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                if msg["channel"] == "talonx:market:stream":
                    px = payload.get("price") or payload.get("close")
                    sym = str(payload.get("symbol") or payload.get("ticker") or "").upper()
                    if sym and px is not None:
                        self._last_price[sym] = float(px)
                        # Task 99G -- advance forward-outcome telemetry from this
                        # SAME live tick (no separate polling loop). A malformed
                        # timestamp or a lookup failure is fully isolated inside
                        # on_market_bar and must never break this message loop.
                        raw_ts = payload.get("timestamp") or payload.get("published_at")
                        bar_ts = _parse_event_ts(raw_ts)
                        if bar_ts is not None:
                            try:
                                self.recorder.on_market_bar(sym, bar_ts, float(px))
                            except Exception:  # noqa: BLE001
                                logger.exception("forward-outcome bar update failed for %s", sym)
                    continue
                try:
                    await self.handle_message(msg["channel"], payload)
                except Exception:  # noqa: BLE001 - one bad message never stops the lane
                    logger.exception("failed handling message on %s", msg["channel"])
        finally:
            await pubsub.unsubscribe()
            await client.aclose()

    # ------------------------------------------------------------------
    # Task 99B -- live intelligence bridge
    # ------------------------------------------------------------------
    def _open_intel(self):
        if self._intel_api is None:
            from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI

            self._intel_api = IntelligenceReadAPI()
        if self._watchlist is None:
            from talonx_watchlist.config import WatchlistConfig
            from talonx_watchlist.store import TickerWatchlistStore

            self._watchlist = TickerWatchlistStore(WatchlistConfig().db_path)
        return self._intel_api, self._watchlist

    def _price(self, symbol: str) -> float | None:
        return self._last_price.get(symbol.upper())

    async def bridge_cycle(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        api, wl = self._open_intel()
        result = {"radar": 0, "events": 0, "errors": 0}
        try:
            upcoming = wl.list_upcoming_earnings()
            self._effective_symbols = sorted({str(r["ticker"]).upper() for r in upcoming}) or None
            radar_rows = self.radar_bridge.build_rows(upcoming, now=now, price_lookup=self._price)
            self.bridge_metrics.radar_rows_built += len(radar_rows)
            for row in radar_rows:
                r = await self.dispatcher.dispatch_radar(row)
                if r not in ("DUPLICATE",):
                    self.bridge_metrics.radar_dispatched += 1
                    result["radar"] += 1
            self.bridge_metrics.last_radar_refresh_utc = now.isoformat()
        except Exception:  # noqa: BLE001
            logger.exception("earnings radar bridge cycle failed")
            self.bridge_metrics.bridge_failures += 1
            result["errors"] += 1
        try:
            since = now - timedelta(days=3)
            ev_rows = self.post_earnings_bridge.scan(api, since=since, price_lookup=self._price)
            self.bridge_metrics.event_rows_built += len(ev_rows)
            for row in ev_rows:
                r = await self.dispatcher.dispatch_event_update(row)
                if r not in ("DUPLICATE",):
                    self.bridge_metrics.event_dispatched += 1
                    result["events"] += 1
            self.bridge_metrics.last_event_bridge_utc = now.isoformat()
        except Exception:  # noqa: BLE001
            logger.exception("post-earnings bridge cycle failed")
            self.bridge_metrics.bridge_failures += 1
            result["errors"] += 1
        return result

    async def refresh_premarket(self, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        try:
            api, wl = self._open_intel()
            upcoming = {str(r["ticker"]).upper(): r for r in wl.list_upcoming_earnings()}
            overnight = overnight_event_labels(
                api, self._effective_symbols, since=now - timedelta(hours=18),
            )
            syms = sorted(set(self._last_price) | set(upcoming) | set(overnight))
            inputs = []
            for s in syms:
                ue = upcoming.get(s)
                inputs.append(PremarketSymbolInput(
                    symbol=s,
                    latest_price=self._last_price.get(s),
                    earnings_when=(str(ue["earnings_date"]) if ue else None),
                    overnight_events=tuple(overnight.get(s, ())),
                ))
            self._premarket_bundle = self.premarket_engine.assess(
                inputs, now=now, watchlist_configured=len(syms), watchlist_active=len(syms),
            )
        except Exception:  # noqa: BLE001
            logger.exception("premarket refresh failed")
        return self._premarket_bundle

    async def _bridge_loop(self, interval_seconds: float) -> None:
        # first pass immediately, then every `interval_seconds`
        while not self._stop.is_set():
            await self.bridge_cycle()
            await self.refresh_premarket()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass

    def premarket_provider(self):
        return self._premarket_bundle

    def health(self) -> dict:
        base = {
            "market_feed": {"status": "up" if not self._stop.is_set() else "down",
                            "detail": f"{len(self._last_price)} symbols priced"},
            "control_strategy": {"status": "healthy", "detail": "run_talonx.py (separate process)"},
            "experimental_strategy": {"status": "healthy", "detail": PROFILE_EXPERIMENTAL},
            "dispatcher": {"status": "healthy",
                           "detail": "external send ON" if self.dispatcher.enable_external_send else "dry-run"},
            "paper_engine": {"status": "healthy", "detail": str(self.cfg.paper_db_path)},
            "telegram": {"status": "healthy" if self.dispatcher.enable_external_send else "degraded"},
        }
        try:
            fo = self.outcome_store.summary()
            base["forward_outcomes"] = {
                "status": "healthy",
                "detail": (f"{fo['pending']} pending / {fo['total']} total -- "
                          f"resolved 30m={fo['resolved_30m']} 60m={fo['resolved_60m']} "
                          f"eod={fo['resolved_eod']} 1d={fo['resolved_1d']}"),
                "pending": fo["pending"], "total": fo["total"],
                "resolved_30m": fo["resolved_30m"], "resolved_60m": fo["resolved_60m"],
                "resolved_eod": fo["resolved_eod"], "resolved_1d": fo["resolved_1d"],
                "last_update": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:  # noqa: BLE001
            base["forward_outcomes"] = {"status": "degraded", "detail": "summary unavailable"}
        try:
            api, wl = self._open_intel()
            bh = bridge_health(api, wl.list_upcoming_earnings(), self.bridge_metrics)
            base["intelligence_service"] = bh["intelligence_source"]
            base["earnings_source"] = bh["earnings_source"]
            base["intelligence_bridge"] = bh["dispatch_bridge"]
        except Exception:  # noqa: BLE001
            base["intelligence_service"] = {"status": "idle", "detail": "not opened"}
        return base

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self.alert_store.close()
        self.outcome_store.close()
        self.paper.close()
        for h in (self._intel_api, self._watchlist):
            try:
                h and h.close()
            except Exception:  # noqa: BLE001
                pass


async def _serve_dashboard(lane: ExperimentalLane, host: str, port: int) -> None:
    from aiohttp import web

    board = ExperimentalDashboard(lane.alert_store, lane.outcome_store,
                                  health_provider=lane.health,
                                  premarket_provider=lane.premarket_provider)

    async def _index(_req):
        return web.Response(text=board.render(), content_type="text/html")

    async def _health(_req):
        return web.json_response({"ok": True, "counts": lane.alert_store.counts()})

    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/__health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("experimental dashboard: http://%s:%d", host, port)
    try:
        await lane._stop.wait()
    finally:
        await runner.cleanup()


async def _amain(args: argparse.Namespace) -> int:
    cfg = ExperimentalConfig()
    ok, detail = validate_experimental_isolation(cfg)
    if not ok:
        logger.error("EXPERIMENTAL ISOLATION FAILED (fail-closed): %s", detail)
        return 3
    logger.info("isolation OK: %s", detail)
    assert_control_profile_unchanged()

    lane = ExperimentalLane(cfg, enable_external_send=args.enable_external_send)
    logger.info("relaxed profile: min_atr_pct=%.2f confluence_score_min=%d min_risk_reward_ratio=%.1f",
                *(getattr(build_experimental_quant_config(cfg), k)
                  for k in ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")))

    if args.offline:
        board = ExperimentalDashboard(lane.alert_store, lane.outcome_store, health_provider=lane.health)
        html = board.render()
        print(json.dumps({
            "mode": "offline-smoke", "isolation": detail,
            "stores": {
                "exp_alerts": str(lane.alert_store.db_path),
                "forward_outcomes": str(lane.outcome_store.db_path),
                "experimental_paper": str(lane.paper.store.path),
            },
            "dashboard_render_bytes": len(html),
            "external_send": args.enable_external_send,
            "control_profile_unchanged": True,
        }, indent=2))
        lane.close()
        return 0

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, lane.stop)
    except NotImplementedError:
        pass

    # second QuantScanner (experimental) -- reuse the real one, isolated bindings
    from talonx_quant.consumer import QuantScanner
    from talonx_quant.store import QuantStateStore

    qstore = QuantStateStore(str(cfg.quant_db_path))
    scanner = QuantScanner(config=build_experimental_quant_config(cfg), store=qstore)

    tasks = [
        asyncio.create_task(scanner.run(), name="exp-quant-scanner"),
        asyncio.create_task(lane.consume(), name="exp-directional-consumer"),
        asyncio.create_task(_serve_dashboard(lane, args.host, args.port), name="exp-dashboard"),
        asyncio.create_task(lane._bridge_loop(args.bridge_interval), name="exp-intel-bridge"),
    ]
    try:
        await lane._stop.wait()
    except KeyboardInterrupt:
        lane.stop()
    finally:
        logger.info("shutting down experimental lane...")
        scanner.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        qstore.close()
        lane.close()
        assert_control_profile_unchanged()
        logger.info("experimental lane stopped cleanly; CONTROL profile unchanged")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Task 99A experimental + directional lane")
    ap.add_argument("--offline", action="store_true", help="smoke mode: open stores + dashboard, no Redis")
    ap.add_argument("--enable-external-send", action="store_true",
                    help="explicitly enable external Telegram delivery (default: dry-run)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--bridge-interval", type=float, default=300.0,
                    help="seconds between live-intelligence bridge cycles")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(_amain(args)))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
