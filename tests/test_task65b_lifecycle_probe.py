"""Task 65B Part E -- PIV_LIFECYCLE_PROBE: disabled by default, requires
explicit confirmation, PAPER-only, blocked on unreconciled state, excluded
from strategy statistics, controlled exit."""
from __future__ import annotations

from datetime import time

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.lifecycle_probe import (
    PROBE_CUTOFF_ET, PROBE_SYMBOL, close_piv_lifecycle_probe, natural_strategy_lifecycle_observed,
    run_piv_lifecycle_probe,
)


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self, positions=None, orders=None):
        self.positions = positions or []
        self.orders = orders or []
        self.submitted: list[dict] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response(self.orders)
        if "/v2/orders/" in url:
            order_id = url.rsplit("/", 1)[-1]
            match = next((o for o in self.submitted if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        order = {
            "id": f"order-{len(self.submitted) + 1}", "status": "filled", "filled_qty": "1",
            "filled_avg_price": "100.0", **kwargs.get("json", {}),
        }
        self.submitted.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    values.update(overrides)
    return PivConfig(**values)


def lifecycle(tmp_path, transport=None):
    transport = transport or Transport()
    cfg = config(tmp_path)
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    return cfg, bus, life, transport


AFTER_CUTOFF = time(15, 5)
BEFORE_CUTOFF = time(11, 0)


def test_probe_disabled_by_default_without_confirmation(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=False, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "PROBE_REQUIRES_EXPLICIT_OPERATOR_CONFIRMATION"
    assert transport.submitted == []


def test_probe_requires_cutoff_reached(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=BEFORE_CUTOFF)
    assert not result.ran and result.reason == "PROBE_CUTOFF_NOT_YET_REACHED"
    assert transport.submitted == []


def test_probe_blocked_on_non_paper_endpoint(tmp_path):
    cfg = config(tmp_path, broker_endpoint="https://api.alpaca.markets")
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "PROBE_BLOCKED_NON_PAPER_ENDPOINT"


def test_probe_blocked_on_real_capital(tmp_path):
    cfg = config(tmp_path, real_capital=True)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "PROBE_BLOCKED_REAL_CAPITAL_OR_NON_PAPER_STATE"


def test_probe_skipped_if_natural_strategy_lifecycle_already_observed(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    life.order_intent("natural-sig", "MSFT", "buy", 1, source="STRATEGY", alpha_evidence=False)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "NATURAL_STRATEGY_LIFECYCLE_ALREADY_OBSERVED_PROBE_NOT_NEEDED"
    assert len(transport.submitted) == 1  # only the natural order, no probe order added


def test_probe_blocked_on_unreconciled_state(tmp_path):
    # Broker reports a position the internal state doesn't know about -> matched=False.
    transport = Transport(positions=[{"symbol": "NFLX"}])
    cfg, bus, life, _ = lifecycle(tmp_path, transport)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "PROBE_BLOCKED_UNRECONCILED_STATE"
    assert transport.submitted == []


def test_probe_blocked_if_existing_position_in_probe_symbol(tmp_path):
    # Setup order deliberately untagged (not source="STRATEGY") so this
    # isolates the existing-position guard, not the earlier
    # natural-lifecycle-observed check (covered by its own test above).
    # Transport is pre-seeded with the matching broker-side position so
    # reconciliation passes and the existing-position guard is what fires.
    transport = Transport(positions=[{"symbol": PROBE_SYMBOL}])
    cfg, bus, life, transport = lifecycle(tmp_path, transport)
    entry = life.order_intent("prior-sig", PROBE_SYMBOL, "buy", 1)
    life.apply_broker_update(entry["id"], "filled", 1, 100.0)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert not result.ran and result.reason == "PROBE_BLOCKED_EXISTING_POSITION_IN_PROBE_SYMBOL"


def test_probe_runs_full_lifecycle_and_is_tagged_not_alpha_evidence(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    result = run_piv_lifecycle_probe(cfg, bus, life, explicit_confirmation=True, now_et_time=AFTER_CUTOFF)
    assert result.ran and result.entry_order is not None
    assert transport.submitted[0]["symbol"] == PROBE_SYMBOL and transport.submitted[0]["side"] == "buy"
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"source": "PIV_LIFECYCLE_PROBE"' in events_text
    assert '"alpha_evidence": false' in events_text

    closed = close_piv_lifecycle_probe(bus, life)
    assert closed is not None and transport.submitted[1]["side"] == "sell"
    assert '"event": "EXIT_REQUESTED"' in bus.path.read_text(encoding="utf-8")


def test_natural_strategy_lifecycle_observed_helper(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    assert natural_strategy_lifecycle_observed(bus.path) is False
    life.order_intent("s", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False)
    assert natural_strategy_lifecycle_observed(bus.path) is True


def test_natural_strategy_lifecycle_ignores_probe_source(tmp_path):
    cfg, bus, life, transport = lifecycle(tmp_path)
    life.order_intent("p", PROBE_SYMBOL, "buy", 1, source="PIV_LIFECYCLE_PROBE", alpha_evidence=False)
    assert natural_strategy_lifecycle_observed(bus.path) is False
