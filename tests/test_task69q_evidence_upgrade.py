"""Task 69Q -- session-scoped telemetry, quant funnel accounting, natural vs
probe separation, position lifecycle close semantics, execution economics,
pre-market radar (observational-only), and /ping PIV-awareness."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.events import EventBus, PivEvent, notification_class_for, trading_date_for
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.premarket_radar import PremarketRadarEngine, classify, is_premarket
from talonx_piv.reporting import build_session_report
from talonx_piv.session_identity import build_session_identity, compute_config_hash
from talonx_piv.session_runner import Bar
from talonx_quant.schemas import QuantSignal, RejectedCandidateEvent, SignalDirection, SignalType


# ---------------------------------------------------------------------------
# Part 2: session-scoped telemetry
# ---------------------------------------------------------------------------

def test_trading_date_for_uses_america_new_york_not_utc():
    # 2026-08-25 00:30 UTC is still 2026-08-24 20:30 ET (before DST rolls back later in the year)
    assert trading_date_for("2026-08-25T00:30:00+00:00") == "2026-08-24"
    assert trading_date_for("2026-08-25T14:30:00+00:00") == "2026-08-25"


def test_event_bus_stamps_session_id_and_trading_date(tmp_path):
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="IEX_PAPER_PIV", session_id="piv_2026-08-25_abc123")
    bus.emit(PivEvent(event="STARTUP", timestamp="2026-08-25T14:00:00+00:00"))
    row = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip()
    assert '"session_id": "piv_2026-08-25_abc123"' in row
    assert '"trading_date_et": "2026-08-25"' in row


def test_build_session_report_scopes_to_one_trading_date_and_never_mixes_days(tmp_path):
    """Reproduces exactly the Task69P finding: a single append-only
    piv_events.jsonl spanning multiple trading dates must not have its
    counts silently mixed when a report is built for one date."""
    path = tmp_path / "events.jsonl"
    bus = EventBus(path, feed_mode="IEX_PAPER_PIV")
    bus.emit(PivEvent(event="SIGNAL", timestamp="2026-08-24T15:00:00+00:00", symbol="AAPL", source="STRATEGY"))
    bus.emit(PivEvent(event="SIGNAL", timestamp="2026-08-24T15:05:00+00:00", symbol="MSFT", source="STRATEGY"))
    bus.emit(PivEvent(event="SIGNAL", timestamp="2026-08-25T15:00:00+00:00", symbol="NVDA", source="STRATEGY"))

    report_24 = build_session_report(path, {}, trading_date_et="2026-08-24")
    report_25 = build_session_report(path, {}, trading_date_et="2026-08-25")
    report_all = build_session_report(path, {})  # legacy whole-file caller, unfiltered

    assert report_24["actual_strategy_signals"] == 2
    assert report_25["actual_strategy_signals"] == 1
    assert report_all["actual_strategy_signals"] == 3
    assert report_24["trading_date_et"] == "2026-08-24"


def test_session_identity_is_deterministic_for_same_config():
    cfg_a = PivConfig(state_dir=Path("x"), universe=("AAPL", "MSFT"), feed_mode="IEX_PAPER_PIV")
    cfg_b = PivConfig(state_dir=Path("y"), universe=("AAPL", "MSFT"), feed_mode="IEX_PAPER_PIV")
    assert compute_config_hash(cfg_a) == compute_config_hash(cfg_b)  # state_dir doesn't affect the hash
    identity = build_session_identity(cfg_a, now=datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc))
    assert identity.trading_date_et == "2026-08-25"
    assert identity.session_id.startswith("piv_2026-08-25_")


# ---------------------------------------------------------------------------
# Part 4/7: notification classification -- natural vs probe vs radar vs system
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("event,source,expected", [
    ("STARTUP", None, "SYSTEM"),
    ("STALE_DATA", None, "SYSTEM"),
    ("SIGNAL", "STRATEGY", "NATURAL_SIGNAL"),
    ("PAPER_ORDER_SUBMITTED", "STRATEGY", "PAPER_EXECUTION"),
    ("POSITION_OPENED", "PIV_LIFECYCLE_PROBE", "PIV_TEST"),
    ("PREMARKET_WATCH", "PREMARKET_RADAR", "PREMARKET_RADAR"),
    ("EOD_FLATTEN", None, "EOD"),
])
def test_notification_class_for(event, source, expected):
    assert notification_class_for(event, source) == expected


def test_format_telegram_prefixes_notification_class(tmp_path):
    bus = EventBus(tmp_path / "e.jsonl", feed_mode="IEX_PAPER_PIV")
    event = PivEvent.build("SIGNAL", symbol="AAPL", source="STRATEGY")
    event = type(event)(**{**event.__dict__, "notification_class": notification_class_for(event.event, event.source)})
    assert EventBus.format_telegram(event).startswith("[NATURAL_SIGNAL]")


def test_natural_vs_probe_traffic_never_conflated_in_report(tmp_path):
    path = tmp_path / "events.jsonl"
    bus = EventBus(path, feed_mode="IEX_PAPER_PIV")
    ts = "2026-08-25T15:00:00+00:00"
    bus.emit(PivEvent(event="PAPER_ORDER_SUBMITTED", timestamp=ts, symbol="AAPL", source="STRATEGY", alpha_evidence=False))
    bus.emit(PivEvent(event="PAPER_ORDER_SUBMITTED", timestamp=ts, symbol="AAPL", source="PIV_LIFECYCLE_PROBE", alpha_evidence=False))
    report = build_session_report(path, {}, trading_date_et="2026-08-25")
    assert report["natural_strategy"]["orders"] == 1
    assert report["piv_test_traffic"]["orders"] == 1
    assert report["piv_test_traffic"]["alpha_evidence"] is False


# ---------------------------------------------------------------------------
# Part 5: position lifecycle -- exit fill must CLOSE, not OPEN a new position
# ---------------------------------------------------------------------------

def _lifecycle(tmp_path):
    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)

    class Response:
        def __init__(self, body, status=200): self.body, self.status_code = body, status
        def json(self): return self.body
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

    class Transport:
        def __init__(self):
            self.n = 0
            self.orders: dict[str, dict] = {}

        def get(self, url, **kw):
            if url.endswith("/v2/account"): return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"})
            if "/v2/orders/" in url:
                order_id = url.rsplit("/", 1)[-1]
                return Response(self.orders[order_id])
            return Response([])

        def post(self, url, **kw):
            self.n += 1
            payload = kw.get("json", {})
            price = 100.0 if payload.get("side") == "buy" else 105.0
            order = {"id": f"order-{self.n}", "status": "filled", "filled_qty": "1", "filled_avg_price": str(price)}
            self.orders[order["id"]] = order
            return Response(order)

        def delete(self, url, **kw): return Response([])

    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    return life, bus


def test_exit_fill_emits_position_closed_not_a_second_position_opened(tmp_path):
    life, bus = _lifecycle(tmp_path)
    entry = life.order_intent("sig_entry", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False,
                               reference_price=99.5, stop_price=97.0)
    life.poll_order_until_terminal(entry["id"])
    exit_ = life.order_intent("sig_exit", "AAPL", "sell", 1, source="STRATEGY", alpha_evidence=False,
                               reference_price=105.0)
    life.poll_order_until_terminal(exit_["id"])

    rows = bus.path.read_text(encoding="utf-8").splitlines()
    events_seen = [__import__("json").loads(r)["event"] for r in rows]
    assert events_seen.count("POSITION_OPENED") == 1
    assert events_seen.count("POSITION_CLOSED") == 1
    positions = list(life.state.positions.values())
    assert len(positions) == 1  # same logical position, not a second record
    assert positions[0]["status"] == "CLOSED"
    assert life.state.open_position_by_symbol == {}


# ---------------------------------------------------------------------------
# Part 6: execution economics -- slippage, gross/net PnL, gross/net R, no
# fabricated R when no stop is defined
# ---------------------------------------------------------------------------

def test_execution_economics_captured_on_position_closed(tmp_path):
    life, bus = _lifecycle(tmp_path)
    entry = life.order_intent("sig_entry", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False,
                               reference_price=99.5, stop_price=97.0, strategy_id="MACD_BULLISH_CROSS", horizon="INTRADAY_SHORT")
    life.poll_order_until_terminal(entry["id"])
    exit_ = life.order_intent("sig_exit", "AAPL", "sell", 1, source="STRATEGY", alpha_evidence=False, reference_price=104.0)
    life.poll_order_until_terminal(exit_["id"])

    import json
    rows = [json.loads(r) for r in bus.path.read_text(encoding="utf-8").splitlines()]
    closed = next(r for r in rows if r["event"] == "POSITION_CLOSED")
    assert closed["gross_pnl"] == pytest.approx(5.0)  # (105 fill - 100 fill) * 1
    assert closed["net_pnl"] == pytest.approx(5.0)  # zero paper commissions
    assert closed["estimated_transaction_cost"] == 0.0
    assert closed["slippage_abs"] == pytest.approx(1.0)  # 105 fill vs 104 exit reference
    assert closed["gross_r"] == pytest.approx(5.0 / 3.0)  # entry(100)-stop(97)=3 risk, over 1 share
    assert closed["net_r"] == pytest.approx(5.0 / 3.0)
    assert closed["holding_seconds"] is not None and closed["holding_seconds"] >= 0

    opened = next(r for r in rows if r["event"] == "POSITION_OPENED")
    assert opened["reference_price"] == 99.5
    assert opened["slippage_abs"] == pytest.approx(0.5)  # 100 fill vs 99.5 reference
    assert opened["strategy_id"] == "MACD_BULLISH_CROSS"
    assert opened["horizon"] == "INTRADAY_SHORT"


def test_no_fabricated_r_when_strategy_defines_no_stop(tmp_path):
    life, bus = _lifecycle(tmp_path)
    entry = life.order_intent("sig_entry", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False, reference_price=99.5)
    life.poll_order_until_terminal(entry["id"])  # no stop_price passed
    exit_ = life.order_intent("sig_exit", "AAPL", "sell", 1, source="STRATEGY", alpha_evidence=False)
    life.poll_order_until_terminal(exit_["id"])

    import json
    rows = [json.loads(r) for r in bus.path.read_text(encoding="utf-8").splitlines()]
    closed = next(r for r in rows if r["event"] == "POSITION_CLOSED")
    assert closed["gross_r"] is None
    assert closed["net_r"] is None
    assert closed["gross_pnl"] == pytest.approx(5.0)  # PnL is still real; only R is withheld


# ---------------------------------------------------------------------------
# Part 3: quant candidate funnel accounting
# ---------------------------------------------------------------------------

class FakePubSub:
    def __init__(self, messages):
        self._messages = list(messages)
        self.subscribed = []

    async def subscribe(self, channel): self.subscribed.append(channel)
    async def unsubscribe(self, channel): pass
    async def close(self): pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2):
        if self._messages:
            return self._messages.pop(0)
        return None


class FakeRedisClient:
    def __init__(self, pubsub): self._pubsub = pubsub
    def pubsub(self): return self._pubsub


def _quant_config_channels():
    from talonx_quant.config import QuantConfig
    cfg = QuantConfig()
    return cfg.signals_channel, cfg.rejected_candidates_channel


def _engine(tmp_path, messages):
    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                     universe=("AAPL", "MSFT"))

    class Response:
        def __init__(self, body, status=200): self.body, self.status_code = body, status
        def json(self): return self.body
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

    class Transport:
        def get(self, url, **kw): return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"})
        def post(self, url, **kw): return Response({"id": "o1", "status": "filled", "filled_qty": "1", "filled_avg_price": "100.0"})
        def delete(self, url, **kw): return Response([])

    broker = AlpacaPaperClient(cfg, Transport())
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    engine = DecisionEngine(FakeRedisClient(FakePubSub(messages)), bus, life)
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    return engine


def bar(price=100.0):
    return Bar(datetime.now(timezone.utc), price, price + 1, price - 1, price, 1000)


@pytest.mark.asyncio
async def test_quant_funnel_reconciles_published_plus_rejected(tmp_path):
    signals_channel, rejected_channel = _quant_config_channels()
    published = QuantSignal(
        ticker="AAPL", signal_type=SignalType.MACD_BULLISH_CROSS, direction=SignalDirection.BEARISH,
        message="t", price=100.0, bar_timestamp=datetime.now(timezone.utc),
    )
    rejected = RejectedCandidateEvent(ticker="MSFT", gate="rr_gate", reason="LOW_RISK_REWARD", count=3)
    messages = [
        {"channel": rejected_channel, "data": rejected.model_dump_json().encode()},
        {"channel": signals_channel, "data": published.model_dump_json().encode()},
    ]
    engine = _engine(tmp_path, messages)
    await engine.on_bars({"AAPL": bar(), "MSFT": bar()})

    funnel = engine.funnel_summary()
    assert funnel["published"] == 1
    assert funnel["rejected"] == 3  # RejectedCandidateEvent.count aggregates duplicate rejections
    assert funnel["candidates"] == 4
    assert funnel["unaccounted_candidates"] == 0
    assert funnel["rejected_breakdown"] == {"LOW_RISK_REWARD": 3}
    assert funnel["evaluation_cycles"] == 1
    assert funnel["symbols_evaluated_total"] == 2


@pytest.mark.asyncio
async def test_quant_funnel_counts_unparseable_messages_as_errored(tmp_path):
    signals_channel, _ = _quant_config_channels()
    engine = _engine(tmp_path, [{"channel": signals_channel, "data": b"not-valid-json"}])
    await engine.on_bars({"AAPL": bar()})
    funnel = engine.funnel_summary()
    assert funnel["errored"] == 1
    assert funnel["candidates"] == 1
    assert funnel["unaccounted_candidates"] == 0


# ---------------------------------------------------------------------------
# Part 7A: pre-market radar -- observational only, structurally cannot order
# ---------------------------------------------------------------------------

def test_premarket_radar_module_never_imports_broker_or_lifecycle():
    """Structural guarantee, not just a runtime check: PREMARKET_RADAR
    events must be impossible to turn into an order, so the module that
    produces them must have no way to reach the broker/lifecycle at all."""
    source = Path("talonx_piv/premarket_radar.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
    assert not any("broker" in m or "lifecycle" in m for m in imported_modules)


def test_is_premarket_window_is_et_not_uk_local():
    # 2026-08-25 08:30 UTC is 04:30 ET (BST is UTC+1 in August) -- pre-market
    # per the ET-canonical rule, even though it is NOT yet 09:00 UK-local-
    # relative reasoning (i.e. this must not be gated by any UK clock).
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now_et = datetime(2026, 8, 25, 8, 30, tzinfo=timezone.utc).astimezone(et)
    assert is_premarket(now_et)
    too_early = datetime(2026, 8, 25, 7, 30, tzinfo=timezone.utc).astimezone(et)  # 03:30 ET
    assert not is_premarket(too_early)
    regular_session = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc).astimezone(et)  # 10:00 ET
    assert not is_premarket(regular_session)


def test_classify_gap_up_is_watch_bullish_never_a_trade_recommendation():
    obs = classify("NVDA", prev_close=100.0, latest_price=102.0)
    assert obs.data_status == "READY"
    assert obs.bias == "BULLISH"
    assert obs.gap_pct == pytest.approx(2.0)
    assert obs.reason_codes == ("PREMARKET_GAP_UP",)


def test_classify_missing_data_is_data_not_ready():
    obs = classify("NVDA", prev_close=None, latest_price=102.0)
    assert obs.data_status == "DATA_NOT_READY"
    assert obs.bias is None


def test_radar_engine_only_emits_on_bias_transition_not_every_tick():
    engine = PremarketRadarEngine()
    first = engine.evaluate([classify("NVDA", 100.0, 102.0)])
    assert len(first) == 1 and first[0]["event"] == "PREMARKET_WATCH"
    unchanged = engine.evaluate([classify("NVDA", 100.0, 102.1)])  # still BULLISH -- no repeat notification
    assert unchanged == []
    cleared = engine.evaluate([classify("NVDA", 100.0, 100.1)])  # gap closes back under threshold
    assert len(cleared) == 1 and cleared[0]["event"] == "PREMARKET_WATCH_CLEARED"
    assert engine.watch_count == 0


# ---------------------------------------------------------------------------
# Part 8: /ping -- PIV feed health must not be conflated with the general
# ingest subsystem's health
# ---------------------------------------------------------------------------

def test_pipeline_status_is_piv_aware_when_piv_info_present():
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    listener = TelegramReplyListener.__new__(TelegramReplyListener)  # bypass __init__ -- pure method test
    assert listener._pipeline_status(client=None, market_health="disconnected", piv_info={"feed_health": "HEALTHY (PIV live feed active)"}) == "HEALTHY (PIV live feed active)"


def test_pipeline_status_general_app_behavior_unchanged_when_no_piv_info():
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    listener = TelegramReplyListener.__new__(TelegramReplyListener)
    assert listener._pipeline_status(client=None, market_health="disconnected", piv_info=None) == "UNKNOWN (no Redis connection)"
    assert "DEGRADED" in listener._pipeline_status(client=object(), market_health="stale feed", piv_info=None)
