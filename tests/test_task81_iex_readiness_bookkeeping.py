"""Task 81 §5 -- IEX readiness-churn bookkeeping invariants.

The Task 80 (2026-08-28) session recorded 532 DATA_NOT_READY / 515
STALE_DATA / 514 DATA_RECOVERED events. Analysis (see
results/task81_safety_baseline_closure/iex_findings.md) concluded the churn
is a faithful reflection of genuine Alpaca-IEX 1-minute bar sparsity for
mid-liquidity NASDAQ-100 names -- NOT a runtime bookkeeping or freshness
defect: the event counts reconcile exactly and match the independently
written freshness_report.json coverage ratios.

These tests LOCK the bookkeeping invariants that make that reconciliation
hold, so a future regression that would inflate / double-count / mis-route
readiness events is caught:

1. A re-delivered bar with a same-or-older source timestamp never resets
   the staleness wall-clock and never emits a second DATA_RECOVERED.
2. The opening-minutes DATA_NOT_READY (from readiness finalization, once
   per session) and the freshness DATA_NOT_READY (from _check_stale, once
   per stale episode) are distinct dimensions -- both firing for one symbol
   is correct, not a dedup failure -- and each is individually deduped.
3. An infra exclusion (STALE / DATA_NOT_READY) keeps a symbol out of the
   decision path entirely, so it can never also appear as a *strategy*
   rejection.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.freshness import DATA_GAP, STALE
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import ET, READY_AT, SessionRunner

UTC = ZoneInfo("UTC")
UNIVERSE = ("AAPL", "REGN")


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ScriptedBarsTransport:
    """Returns a scripted `bars/latest` batch per poll -- lets a test hand
    the runner the SAME bar twice (a sparse symbol whose latest print has
    not advanced) then a genuinely new one."""

    def __init__(self, batches):
        self.batches = list(batches)

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([])
        if "bars/latest" in url:
            return Response({"bars": self.batches.pop(0) if self.batches else {}})
        return Response({}, 404)

    def post(self, *a, **k):
        raise AssertionError("freshness path must never submit an order")

    def delete(self, *a, **k):
        raise AssertionError("freshness path must never cancel/close")


def bar_row(ts_iso, price=100.0):
    return {"t": ts_iso, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 1000}


def _runner(tmp_path, batches, *, decision_engine=None, stale_seconds=90):
    cfg = PivConfig(
        key_id="k", secret_key="s", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=UNIVERSE, stale_seconds=stale_seconds,
    )
    transport = ScriptedBarsTransport(batches)
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    return SessionRunner(cfg, bus, life, transport, decision_engine=decision_engine), bus


def _events(bus):
    import json
    return [json.loads(l) for l in bus.path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# 1. A re-delivered stale bar never resets staleness / re-emits recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redelivered_stale_bar_does_not_reset_staleness_or_reemit_recovery(tmp_path):
    session_local = datetime(2026, 8, 28, 11, 0, tzinfo=ET)   # mid-session, past READY_AT
    t0 = session_local.astimezone(UTC)
    t0_bar = t0.isoformat().replace("+00:00", "Z")
    t1_bar = (t0 + timedelta(seconds=400)).isoformat().replace("+00:00", "Z")

    run, bus = _runner(tmp_path, batches=[
        {"AAPL": bar_row(t0_bar)},   # tick 1: first bar
        {"AAPL": bar_row(t0_bar)},   # tick 2: SAME bar re-delivered (latest print hasn't advanced)
        {"AAPL": bar_row(t0_bar)},   # tick 3: SAME bar again
        {"AAPL": bar_row(t1_bar)},   # tick 4: a genuinely new bar
    ])
    run._session = t0.astimezone(ET).date()   # skip the session-boundary reset
    run._ready_symbols = {"AAPL", "REGN"}   # skip finalization; isolate the freshness path

    await run.process_tick(t0)
    await run.process_tick(t0 + timedelta(seconds=150))   # gap 150 > 90 -> STALE
    await run.process_tick(t0 + timedelta(seconds=210))   # still the same old bar -> still STALE, no new event
    await run.process_tick(t0 + timedelta(seconds=430))   # new bar -> RECOVERED (exactly once)

    ev = _events(bus)
    stale = [e for e in ev if e["event"] == "STALE_DATA" and e.get("symbol") == "AAPL"]
    recovered = [e for e in ev if e["event"] == "DATA_RECOVERED" and e.get("symbol") == "AAPL"]
    assert len(stale) == 1, "one STALE per episode -- a re-delivered old bar must not start a new one"
    assert len(recovered) == 1, "a re-delivered old bar must NOT emit DATA_RECOVERED; only the genuinely new bar does"


@pytest.mark.asyncio
async def test_distinct_stale_episodes_across_a_real_gap_are_counted_separately(tmp_path):
    session_local = datetime(2026, 8, 28, 11, 0, tzinfo=ET)
    t0 = session_local.astimezone(UTC)

    def iso(sec):
        return (t0 + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")

    run, bus = _runner(tmp_path, batches=[
        {"AAPL": bar_row(iso(0))},
        {},                              # gap -> STALE episode 1
        {"AAPL": bar_row(iso(200))},     # RECOVERED 1
        {},                              # gap -> STALE episode 2
        {"AAPL": bar_row(iso(500))},     # RECOVERED 2
    ])
    run._session = t0.astimezone(ET).date()
    run._ready_symbols = {"AAPL", "REGN"}
    for sec in (0, 150, 260, 420, 560):
        await run.process_tick(t0 + timedelta(seconds=sec))

    ev = _events(bus)
    assert len([e for e in ev if e["event"] == "STALE_DATA" and e.get("symbol") == "AAPL"]) == 2
    assert len([e for e in ev if e["event"] == "DATA_RECOVERED" and e.get("symbol") == "AAPL"]) == 2
    assert run._freshness._stale_episode_count["AAPL"] == 2


# ---------------------------------------------------------------------------
# 2. Opening-minutes DATA_NOT_READY vs freshness DATA_NOT_READY: distinct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalization_and_freshness_data_not_ready_are_distinct_dimensions(tmp_path):
    # REGN never prints an opening bar -> readiness finalization emits a
    # MISSING_REQUIRED_OPENING_MINUTES DATA_NOT_READY exactly once. It then
    # also goes stale during the session -> a SECOND, differently-reasoned
    # DATA_NOT_READY from _check_stale. Two dimensions, both legitimate.
    ready_at_local = datetime(2026, 8, 28, READY_AT.hour, READY_AT.minute, tzinfo=ET)
    t_ready = ready_at_local.astimezone(UTC)

    run, bus = _runner(tmp_path, batches=[
        {"AAPL": bar_row(t_ready.isoformat().replace("+00:00", "Z"))},
        {"AAPL": bar_row((t_ready + timedelta(seconds=300)).isoformat().replace("+00:00", "Z"))},
    ])
    # AAPL was seen pre-READY_AT; REGN never was.
    run._session = t_ready.astimezone(ET).date()
    run._last_seen_wall["REGN"] = t_ready - timedelta(seconds=10)

    await run.process_tick(t_ready)                              # triggers finalization
    run._check_stale(t_ready + timedelta(seconds=200))           # REGN now stale

    ev = _events(bus)
    regn_nr = [e for e in ev if e["event"] == "DATA_NOT_READY" and e.get("symbol") == "REGN"]
    reasons = {e.get("reason") or "" for e in regn_nr}
    assert any("MISSING_REQUIRED_OPENING" in r for r in reasons)
    assert any("INSUFFICIENT_RECENT_IEX_PRINTS" in r for r in reasons)
    # The finalization one fires exactly once.
    assert sum(1 for e in regn_nr if "MISSING_REQUIRED_OPENING" in (e.get("reason") or "")) == 1
    # A second _check_stale while still stale emits no further event.
    before = len(_events(bus))
    run._check_stale(t_ready + timedelta(seconds=260))
    assert len(_events(bus)) == before


# ---------------------------------------------------------------------------
# 3. Infra exclusion keeps a symbol out of the strategy path entirely
# ---------------------------------------------------------------------------

class _RecordingEngine:
    warmup_ready_symbols = {"AAPL", "REGN"}

    def __init__(self):
        self.on_bars_calls = []

    async def on_bars(self, bars):
        self.on_bars_calls.append(set(bars))


@pytest.mark.asyncio
async def test_stale_symbol_bar_is_never_forwarded_to_the_strategy(tmp_path):
    session_local = datetime(2026, 8, 28, 11, 0, tzinfo=ET)
    t0 = session_local.astimezone(UTC)

    def iso(sec):
        return (t0 + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")

    engine = _RecordingEngine()
    run, bus = _runner(tmp_path, batches=[
        {"AAPL": bar_row(iso(0)), "REGN": bar_row(iso(0))},   # tick 1: both fresh
        {"AAPL": bar_row(iso(60))},                            # tick 2: REGN silent -> goes stale
        {"AAPL": bar_row(iso(120))},                           # tick 3: REGN still silent / stale
    ], decision_engine=engine)
    run._session = t0.astimezone(ET).date()   # pre-set so the session-boundary reset doesn't wipe _ready_symbols
    run._ready_symbols = {"AAPL", "REGN"}

    await run.process_tick(t0)
    await run.process_tick(t0 + timedelta(seconds=150))    # REGN stale (gap 150 > 90)
    assert run._freshness.state_of("REGN") in (STALE, DATA_GAP)
    await run.process_tick(t0 + timedelta(seconds=210))

    # Tick 1: REGN was fresh, so it legitimately reached the strategy.
    # From the moment REGN is a stale infra exclusion, no further on_bars
    # call includes it -- an infra exclusion never becomes a strategy input
    # (and therefore never a strategy rejection).
    assert engine.on_bars_calls[0] == {"AAPL", "REGN"}
    assert all("REGN" not in call for call in engine.on_bars_calls[1:])
    # Belt-and-suspenders: STALE/DATA_GAP are in the explicit exclusion set.
    from talonx_piv.session_runner import STALE as RUNNER_STALE, DATA_GAP as RUNNER_GAP  # noqa: F401
    assert run._freshness.state_of("REGN") in (RUNNER_STALE, RUNNER_GAP)
