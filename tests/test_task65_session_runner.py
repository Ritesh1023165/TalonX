"""Task 65 -- SessionRunner: readiness gating, no synthesized data, no feed
fallback, stale-data detection, and a deterministic (not probabilistic)
guarantee of zero orders -- no decision path is wired in today, see
session_runner.py's module docstring for why."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import SessionRunner

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)
UNIVERSE = ("AAPL", "MSFT")


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class BarsTransport:
    """Serves one canned response per fetch_bars_latest() call, in order."""

    def __init__(self, batches: list[dict[str, dict]]):
        self.batches = list(batches)
        self.feed_params_used: list[str] = []
        self.orders: list = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response(self.orders)
        if "bars/latest" in url:
            self.feed_params_used.append(kwargs["params"]["feed"])
            body = self.batches.pop(0) if self.batches else {}
            return Response({"bars": body})
        return Response({}, 404)

    def post(self, url, **kwargs):
        order = {"id": f"order-{len(self.orders) + 1}", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def bar_row(ts: str, price: float = 100.0) -> dict:
    return {"t": ts, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 1000}


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=UNIVERSE, stale_seconds=90)
    values.update(overrides)
    return PivConfig(**values)


def runner(tmp_path, batches, **overrides):
    cfg = config(tmp_path, **overrides)
    transport = BarsTransport(batches)
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    return SessionRunner(cfg, bus, life, transport), transport, bus


def to_utc_iso(local: datetime) -> str:
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def test_missing_opening_minute_marks_symbol_data_not_ready(tmp_path):
    # AAPL gets all 30 opening minutes; MSFT is missing minute 09:35.
    batches = []
    skip_time = datetime(2026, 8, 24, 9, 35, tzinfo=ET).time()
    for i in range(30):
        minute = datetime(2026, 8, 24, 9, 30, tzinfo=ET) + timedelta(minutes=i)
        ts = to_utc_iso(minute)
        row = {"AAPL": bar_row(ts)}
        if minute.time() != skip_time:
            row["MSFT"] = bar_row(ts)
        batches.append(row)
    ready_tick = datetime(2026, 8, 24, 10, 0, tzinfo=ET)
    batches.append({"AAPL": bar_row(to_utc_iso(ready_tick)), "MSFT": bar_row(to_utc_iso(ready_tick))})

    run, transport, bus = runner(tmp_path, batches)
    ticks = [datetime(2026, 8, 24, 9, 30, tzinfo=ET) + timedelta(minutes=i) for i in range(30)]
    ticks.append(ready_tick)
    for tick in ticks:
        run.process_tick(tick.astimezone(ZoneInfo("UTC")))

    assert run._ready_symbols == {"AAPL"}
    events = bus.path.read_text(encoding="utf-8")
    assert '"event": "MARKET_DATA_READY"' in events and '"symbol": "AAPL"' in events
    assert '"event": "DATA_NOT_READY"' in events and '"symbol": "MSFT"' in events


def test_no_decision_path_zero_orders_regardless_of_ticks(tmp_path):
    # A full, otherwise-clean session (all 30 opening minutes + 15 more
    # live-window ticks for both symbols) must still submit exactly zero
    # orders -- deterministic by construction, not "no signal happened to
    # fire this run."
    batches = []
    for i in range(45):
        minute = datetime(2026, 8, 24, 9, 30, tzinfo=ET) + timedelta(minutes=i)
        ts = to_utc_iso(minute)
        batches.append({"AAPL": bar_row(ts, 100 + i), "MSFT": bar_row(ts, 200 + i)})

    run, transport, bus = runner(tmp_path, batches)
    for i in range(45):
        tick = datetime(2026, 8, 24, 9, 30, tzinfo=ET) + timedelta(minutes=i)
        run.process_tick(tick.astimezone(ZoneInfo("UTC")))

    assert run._ready_symbols == {"AAPL", "MSFT"}
    assert transport.orders == []
    events = bus.path.read_text(encoding="utf-8")
    assert '"event": "SIGNAL"' not in events
    assert '"event": "ORDER_INTENT"' not in events


def test_stale_data_flagged_once_when_no_new_bar_arrives(tmp_path):
    base = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run, transport, bus = runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    run._last_seen_wall["AAPL"] = base
    run._check_stale(base + timedelta(seconds=200))
    run._check_stale(base + timedelta(seconds=210))  # still stale -- must not re-emit
    events = bus.path.read_text(encoding="utf-8").splitlines()
    stale_events = [row for row in events if '"event": "STALE_DATA"' in row]
    assert len(stale_events) == 1


def test_feed_param_pinned_no_fallback(tmp_path):
    ts = to_utc_iso(datetime(2026, 8, 24, 9, 30, tzinfo=ET))
    run, transport, bus = runner(tmp_path, [{"AAPL": bar_row(ts)}], feed_mode="IEX_PAPER_PIV")
    run.process_tick(datetime(2026, 8, 24, 9, 30, tzinfo=ET).astimezone(ZoneInfo("UTC")))
    assert run._last_bar_ts and transport.feed_params_used == ["iex"]


def test_missing_symbol_in_response_is_not_synthesized(tmp_path):
    ts = to_utc_iso(datetime(2026, 8, 24, 9, 30, tzinfo=ET))
    run, transport, bus = runner(tmp_path, [{"AAPL": bar_row(ts)}])  # MSFT absent
    run.process_tick(datetime(2026, 8, 24, 9, 30, tzinfo=ET).astimezone(ZoneInfo("UTC")))
    assert "MSFT" not in run._last_bar_ts
    assert "AAPL" in run._last_bar_ts


def test_duplicate_bar_not_reprocessed(tmp_path):
    ts = to_utc_iso(datetime(2026, 8, 24, 9, 30, tzinfo=ET))
    run, transport, bus = runner(tmp_path, [{"AAPL": bar_row(ts)}, {"AAPL": bar_row(ts)}])
    tick = datetime(2026, 8, 24, 9, 30, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run.process_tick(tick)
    first_seen = run._last_seen_wall["AAPL"]
    run.process_tick(tick + timedelta(seconds=30))
    assert run._last_seen_wall["AAPL"] == first_seen  # duplicate timestamp never advanced last-seen


def test_kill_switch_stops_loop_without_processing_further_ticks(tmp_path):
    run, transport, bus = runner(tmp_path, [])
    run.lifecycle.activate_kill_switch()
    calls = []
    run.process_tick = lambda now: calls.append(now)  # type: ignore[method-assign]
    ticks = iter([datetime(2026, 8, 24, 9, 31, tzinfo=ET).astimezone(ZoneInfo("UTC"))])
    run.run(clock=lambda: next(ticks), sleep=lambda s: None)
    assert calls == []
    events = bus.path.read_text(encoding="utf-8")
    assert '"event": "KILL_SWITCH"' in events
