"""Task 65B warmup fix -- causal, fail-closed hydration before any live
decision. Covers Part E's warmup checklist: cold scanner not decision-ready,
preseed-before-live ordering, 120/200 bar thresholds, HTF SMA200
availability, per-symbol fail-closed isolation, no synthetic history,
mixed-provider identity, and warmup producing zero alpha-relevant events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.events import EventBus
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.warmup import LIVE_PROVIDER, WARMUP_PROVIDER, preseed_and_verify
from talonx_quant.buffer import RollingBarBuffer

HTF_PERIOD = 200


class FakeScanner:
    """Real RollingBarBuffer instances (reuse, not reimplement) driven by a
    controllable fake preseed_symbols -- isolates warmup.py's own
    verification logic from network/yfinance."""

    def __init__(self, populate: dict[str, tuple[int, int]] | None = None, raise_on_preseed: bool = False):
        self.buffer = RollingBarBuffer(max_bars_per_symbol=250)
        self.buffer_htf = RollingBarBuffer(max_bars_per_symbol=250)
        self._populate = populate or {}  # symbol -> (n_1m_bars, n_15m_bars)
        self._raise_on_preseed = raise_on_preseed
        self.preseed_calls: list[list[str]] = []

    async def preseed_symbols(self, symbols: list[str]) -> None:
        self.preseed_calls.append(list(symbols))
        if self._raise_on_preseed:
            raise RuntimeError("simulated preseed failure")
        base = datetime(2026, 8, 21, 9, 30, tzinfo=timezone.utc)  # strictly BEFORE any live 2026-08-24 bar
        for symbol in symbols:
            n_1m, n_15m = self._populate.get(symbol.upper(), (0, 0))
            for i in range(n_1m):
                ts = base + timedelta(minutes=i)
                self.buffer.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0 + (i % 5), 1000, session="regular")
            for i in range(n_15m):
                ts = base + timedelta(minutes=15 * i)
                self.buffer_htf.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0 + (i % 7), 1000, session="regular")


@pytest.mark.asyncio
async def test_cold_scanner_is_not_decision_ready():
    scanner = FakeScanner()  # no preseed data populated at all
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert len(checks) == 1 and not checks[0].ready
    assert checks[0].reason == "INSUFFICIENT_1M_AND_HTF_HISTORY"


@pytest.mark.asyncio
async def test_120_1m_bar_requirement_hydrated():
    scanner = FakeScanner(populate={"AAPL": (120, 0)})
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert checks[0].bar_count_1m == 120 and checks[0].bar_count_1m >= checks[0].required_1m_bars


@pytest.mark.asyncio
async def test_119_1m_bars_still_insufficient():
    scanner = FakeScanner(populate={"AAPL": (119, 200)})
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert not checks[0].ready and checks[0].reason == "INSUFFICIENT_1M_HISTORY"


@pytest.mark.asyncio
async def test_200_regular_session_15m_bars_hydrated_and_htf_sma200_available():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert checks[0].bar_count_15m_regular == 200
    assert checks[0].htf_sma_200_available is True
    assert checks[0].ready is True
    assert checks[0].reason == "SUFFICIENT_1M_AND_HTF_HISTORY"


@pytest.mark.asyncio
async def test_199_15m_bars_leaves_htf_unavailable():
    scanner = FakeScanner(populate={"AAPL": (120, 199)})
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert checks[0].htf_sma_200_available is False
    assert not checks[0].ready and checks[0].reason == "INSUFFICIENT_HTF_HISTORY"


@pytest.mark.asyncio
async def test_per_symbol_preseed_failure_isolated_fail_closed():
    # AAPL fully hydrated; MSFT never populated (simulates an individual
    # per-symbol fetch failure) -- one bad symbol must not affect the other.
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    checks = await preseed_and_verify(scanner, ["AAPL", "MSFT"], HTF_PERIOD)
    by_symbol = {c.symbol: c for c in checks}
    assert by_symbol["AAPL"].ready is True
    assert by_symbol["MSFT"].ready is False


@pytest.mark.asyncio
async def test_no_synthetic_history_on_preseed_exception():
    scanner = FakeScanner(raise_on_preseed=True)
    checks = await preseed_and_verify(scanner, ["AAPL", "MSFT"], HTF_PERIOD)
    assert all(not c.ready for c in checks)
    assert all(c.bar_count_1m == 0 and c.bar_count_15m_regular == 0 for c in checks)  # nothing fabricated
    assert all("PRESEED_RAISED" in c.preseed_status for c in checks)


@pytest.mark.asyncio
async def test_mixed_provider_identity_recorded():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert checks[0].warmup_provider == WARMUP_PROVIDER == "YFINANCE"
    assert checks[0].live_provider == LIVE_PROVIDER == "ALPACA_IEX"


@pytest.mark.asyncio
async def test_preseed_called_before_verification_returns_ready_state():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    assert scanner.buffer.bar_count("AAPL") == 0  # nothing hydrated yet -- proves pre-call cold state
    checks = await preseed_and_verify(scanner, ["AAPL"], HTF_PERIOD)
    assert scanner.preseed_calls == [["AAPL"]]  # preseed ran exactly once, for this call
    assert checks[0].ready is True  # verification reflects POST-preseed state


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=("AAPL", "MSFT"))
    values.update(overrides)
    return PivConfig(**values)


class FakePubSub:
    async def subscribe(self, channel): pass
    async def unsubscribe(self, channel): pass
    async def close(self): pass
    async def get_message(self, **kwargs): return None


class FakeRedisClient:
    def pubsub(self): return FakePubSub()


@pytest.mark.asyncio
async def test_decision_engine_start_gates_warmup_ready_symbols(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    transport_events = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    broker = AlpacaPaperClient(cfg)
    life = PaperLifecycle(tmp_path / "state.json", broker, transport_events)
    engine = DecisionEngine(FakeRedisClient(), transport_events, life)

    fake_scanner = FakeScanner(populate={"AAPL": (120, 200)})  # MSFT deliberately not populated
    monkeypatch.setattr(engine, "scanner", fake_scanner)
    checks = await engine.start(["AAPL", "MSFT"])
    assert engine.warmup_ready_symbols == {"AAPL"}
    assert len(checks) == 2


@pytest.mark.asyncio
async def test_warmup_alone_emits_no_alpha_relevant_events(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    broker = AlpacaPaperClient(cfg)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    engine = DecisionEngine(FakeRedisClient(), bus, life)
    monkeypatch.setattr(engine, "scanner", FakeScanner(populate={"AAPL": (120, 200)}))

    await engine.start(["AAPL"])
    assert not bus.path.exists() or '"event": "SIGNAL"' not in bus.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_catastrophic_warmup_failure_fails_closed_before_live_loop(tmp_path):
    """If the architecture cannot safely isolate ANY warmed symbol (zero
    ready out of the whole universe), the session must fail closed before
    ever entering the live tick loop -- not silently proceed with a
    decision engine that can never produce a signal."""
    from talonx_piv.broker import AlpacaPaperClient
    from talonx_piv.session_runner import SessionRunner

    cfg = config(tmp_path)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    broker = AlpacaPaperClient(cfg)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.state.session_enabled = True

    fake_engine = AsyncMock()
    fake_engine.warmup_ready_symbols = set()  # nothing survived warmup
    fake_engine.start.return_value = []

    class DummyTransport:
        def get(self, *a, **k): raise AssertionError("must not reach live polling")

    runner = SessionRunner(cfg, bus, life, DummyTransport(), decision_engine=fake_engine)
    tick_calls = []
    runner.process_tick = lambda now: tick_calls.append(now)  # type: ignore[method-assign]

    await runner.run(clock=lambda: datetime(2026, 8, 24, 9, 15, tzinfo=timezone.utc))

    fake_engine.start.assert_awaited_once_with(list(cfg.universe))
    fake_engine.stop.assert_awaited_once()
    assert tick_calls == []  # live loop never entered
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"event": "BROKER_ERROR"' in events_text
    assert "WARMUP_CATASTROPHIC_FAILURE" in events_text
