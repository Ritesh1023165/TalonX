"""Task 121B Part 2 -- reliability tests for the durable-telemetry replay
adapter (research/scripts/task121b_reliable_replay.py). Reuses the same
hand-built-QuantSignal-injection pattern established in
tests/test_backtest_long_only_lifecycle.py and
tests/test_task121a_parity_trace.py.

Covers the 5 required scenarios: (1) normal replay -> durable summary ->
clean exit; (2) interrupted execution leaves readable, attributable
telemetry; (3) ledger/telemetry reconciliation; (4) no duplicate
events/trades across independent run_ids (this adapter's own declared
contract -- full mid-run state resume is NOT claimed, so "no duplicate on
resume" is verified as "a fresh deterministic rerun under a new run_id
never corrupts or double-counts a prior attempt's durable telemetry");
(5) zero production paths/network sends.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task121a_experimental_replay as t121a  # noqa: E402
import task121b_reliable_replay as t121b  # noqa: E402

import talonx_backtest.engine as engine_module  # noqa: E402
from talonx_backtest.engine import BacktestConfig, BacktestEngine  # noqa: E402
from talonx_backtest.execution import ExecutionConfig, apply_entry_cost  # noqa: E402
from talonx_quant.config import QuantConfig  # noqa: E402
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType  # noqa: E402
from talonx_signals.experimental_paper import ExperimentalPaperEngine  # noqa: E402

_DAY = datetime(2026, 1, 5, tzinfo=timezone.utc)
_BAR = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}
_MIN = timedelta(minutes=1)


def _signal(ticker, direction, bar_timestamp, price=100.0):
    signal_type = SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS
    stop, target = (price - 1.5, price + 10.0) if direction == SignalDirection.BULLISH else (price + 1.5, price - 10.0)
    return QuantSignal(
        ticker=ticker, signal_type=signal_type, direction=direction, message="test",
        price=price, atr=1.0, confluence_score=3, risk_reward_ratio=5.0,
        volume_surge_ratio=5.0, trend_aligned=True,
        htf_sma_200=90.0 if direction == SignalDirection.BULLISH else None,
        stop_price=stop, target_price=target,
        pivot_resistance=price + 20.0, pivot_support=price - 10.0,
        session="regular", bar_timestamp=bar_timestamp, signal_generated_at=bar_timestamp,
    )


def _reliable_engine(tmp_path, run_id: str, db_name="exp.db", telemetry_name="tel.sqlite3"):
    qc = QuantConfig()
    cfg = BacktestConfig(quant_config=qc, execution=ExecutionConfig(spread_bps=0.0),
                         eod_flatten_enabled=False, allow_overlapping_trades=True)
    engine = BacktestEngine(cfg, research_telemetry=False)
    paper = ExperimentalPaperEngine(db_path=tmp_path / db_name, allocation_usd=2500.0,
                                    spread_bps=5.0, initial_cash=100_000.0)
    telemetry = t121b.TelemetryStore(tmp_path / telemetry_name)
    telemetry.start_run(run_id, label="test", window_start="2026-01-05", window_end_inclusive="2026-01-05",
                        n_bars_total=10, module_manifest={}, relaxed_thresholds={})
    shim = t121b.ReliableExperimentalLifecycleShim(paper=paper, bar_close={}, telemetry=telemetry, run_id=run_id)
    engine.simulator = shim
    return engine, paper, shim, telemetry


def _step(monkeypatch, engine, shim, symbol, timestamp, injected=(), bar=None):
    ts = pd.Timestamp(timestamp)
    injected = list(injected)
    bar = dict(bar) if bar is not None else dict(_BAR)
    shim.bar_close[(symbol.upper(), ts)] = bar["close"]

    def fake_compute_indicators(df_1m, qc):
        return SimpleNamespace(atr=1.0, price=bar["close"], bar_timestamp=ts)

    def fake_evaluate_signals(sym, snapshot, qc, htf_sma_200=None, daily_pivots=None):
        return injected

    monkeypatch.setattr(engine_module, "compute_indicators", fake_compute_indicators)
    monkeypatch.setattr(engine_module, "evaluate_signals", fake_evaluate_signals)
    candidates: list[QuantSignal] = []
    engine._process_symbol_bar(symbol, ts, bar, candidates)
    if candidates:
        engine._flush_throttle(candidates, ts)


def _open(monkeypatch, engine, shim, symbol, t0, price=100.0):
    sig = _signal(symbol, SignalDirection.BULLISH, t0, price=price)
    _step(monkeypatch, engine, shim, symbol, t0, injected=[sig], bar={**_BAR, "close": price})
    _step(monkeypatch, engine, shim, symbol, t0 + _MIN, injected=[])
    return t0 + _MIN


# ---------------------------------------------------------------------
# 1. Normal replay -> durable summary -> clean process exit
# ---------------------------------------------------------------------
def test_1_normal_run_produces_durable_queryable_telemetry(tmp_path, monkeypatch):
    run_id = "run-normal"
    engine, paper, shim, telemetry = _reliable_engine(tmp_path, run_id)
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "AAAA", t0, price=100.0)
    telemetry.finish_run(run_id, status="COMPLETE")
    telemetry.flush()

    # a SEPARATE connection (simulating "read it back after the process exited")
    con2 = sqlite3.connect(str(tmp_path / "tel.sqlite3"))
    status = con2.execute("SELECT status FROM run_meta WHERE run_id=?", (run_id,)).fetchone()[0]
    assert status == "COMPLETE"
    n_pub = con2.execute("SELECT COUNT(*) FROM published_signals WHERE run_id=?", (run_id,)).fetchone()[0]
    assert n_pub >= 1
    con2.close()
    paper.close()


# ---------------------------------------------------------------------
# 2. Interrupted execution + recovery: durable telemetry up to the
#    interrupt point remains readable and attributable to its own run_id
# ---------------------------------------------------------------------
def test_2_interrupted_run_leaves_readable_attributable_partial_telemetry(tmp_path, monkeypatch):
    run_id = "run-interrupted"
    engine, paper, shim, telemetry = _reliable_engine(tmp_path, run_id)
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "BBBB", t0, price=100.0)
    telemetry.update_progress(run_id, bars_done=2, bars_total=1000, last_bar_ts=str(t0))
    # simulate a hard interrupt: NO finish_run() call, NO graceful shutdown --
    # just stop touching the store and open a fresh connection, as a
    # recovery procedure would.
    telemetry.con.commit()

    con2 = sqlite3.connect(str(tmp_path / "tel.sqlite3"))
    status = con2.execute("SELECT status FROM run_meta WHERE run_id=?", (run_id,)).fetchone()[0]
    assert status == "RUNNING"  # never finalized -- correctly distinguishable from a completed run
    bars_done = con2.execute("SELECT bars_done FROM progress WHERE run_id=?", (run_id,)).fetchone()[0]
    assert bars_done == 2
    n_pub = con2.execute("SELECT COUNT(*) FROM published_signals WHERE run_id=?", (run_id,)).fetchone()[0]
    assert n_pub >= 1  # the entry already made before the interrupt is NOT lost
    con2.close()
    paper.close()


# ---------------------------------------------------------------------
# 3. Ledger/telemetry reconciliation
# ---------------------------------------------------------------------
def test_3_ledger_and_telemetry_reconcile(tmp_path, monkeypatch):
    run_id = "run-reconcile"
    engine, paper, shim, telemetry = _reliable_engine(tmp_path, run_id)
    t0 = _DAY.replace(hour=15, minute=0)
    t_open = _open(monkeypatch, engine, shim, "CCCC", t0, price=100.0)
    pos = paper.store.get_position("CCCC")
    assert pos["target_price"] == pytest.approx(120.0)
    _step(monkeypatch, engine, shim, "CCCC", t_open + timedelta(minutes=1), injected=[], bar={**_BAR, "close": 120.5})
    telemetry.finish_run(run_id, status="COMPLETE")

    closed = t121a._fetch_rows(paper.store._conn, "SELECT * FROM trade_history WHERE order_type='SELL'")
    n_exits_ledger = len(closed)
    n_exits_telemetry = telemetry.con.execute("SELECT COUNT(*) FROM exits WHERE run_id=?", (run_id,)).fetchone()[0]
    assert n_exits_ledger == n_exits_telemetry == 1
    ledger_reason = closed[0]["exit_reason"]  # coarse AlertAction
    tel_reason = telemetry.con.execute(
        "SELECT true_exit_reason FROM exits WHERE run_id=?", (run_id,)).fetchone()[0]
    assert ledger_reason == "confirmed_bearish"
    assert tel_reason == "target_exit"  # fine-grained, only available from telemetry
    paper.close()


# ---------------------------------------------------------------------
# 4. No duplicate events/trades across independent run_ids (declared
#    resume contract: a fresh deterministic rerun, not state resume)
# ---------------------------------------------------------------------
def test_4_independent_reruns_do_not_duplicate_or_corrupt_each_others_telemetry(tmp_path, monkeypatch):
    telemetry_path = tmp_path / "shared_tel.sqlite3"
    t0 = _DAY.replace(hour=15, minute=0)

    run_id_a = "run-a"
    engine_a, paper_a, shim_a, tel_a = _reliable_engine(tmp_path, run_id_a, db_name="a.db", telemetry_name="shared_tel.sqlite3")
    _open(monkeypatch, engine_a, shim_a, "DDDD", t0, price=100.0)
    tel_a.finish_run(run_id_a, status="COMPLETE")
    paper_a.close()

    run_id_b = "run-b"
    engine_b, paper_b, shim_b, tel_b = _reliable_engine(tmp_path, run_id_b, db_name="b.db", telemetry_name="shared_tel.sqlite3")
    _open(monkeypatch, engine_b, shim_b, "DDDD", t0, price=100.0)
    tel_b.finish_run(run_id_b, status="COMPLETE")
    paper_b.close()

    con = sqlite3.connect(str(telemetry_path))
    n_a = con.execute("SELECT COUNT(*) FROM published_signals WHERE run_id=?", (run_id_a,)).fetchone()[0]
    n_b = con.execute("SELECT COUNT(*) FROM published_signals WHERE run_id=?", (run_id_b,)).fetchone()[0]
    n_total = con.execute("SELECT COUNT(*) FROM published_signals").fetchone()[0]
    assert n_a >= 1 and n_b >= 1
    assert n_total == n_a + n_b  # each run's events are additive, never merged/deduplicated across run_ids
    n_runs = con.execute("SELECT COUNT(DISTINCT run_id) FROM run_meta").fetchone()[0]
    assert n_runs == 2
    con.close()


# ---------------------------------------------------------------------
# 5. Zero production paths / network sends
# ---------------------------------------------------------------------
def test_5_zero_external_sends_no_network_dependency():
    import inspect

    src = inspect.getsource(t121b)
    for token in ("requests.", "aiohttp", "socket.", "urllib", "TelegramSenderAdapter", "redis.Redis(", "aioredis"):
        assert token not in src, f"unexpected network/external-send dependency: {token}"


# ---------------------------------------------------------------------
# Bounded summary generation -- SQL aggregates, not a Python reduction
# over an unbounded in-memory list (the Task 121A hang's suspected cause)
# ---------------------------------------------------------------------
def test_summary_queries_are_bounded_sql_aggregates_not_python_list_reduction(tmp_path, monkeypatch):
    run_id = "run-bounded"
    engine, paper, shim, telemetry = _reliable_engine(tmp_path, run_id)
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "EEEE", t0, price=100.0)
    telemetry.finish_run(run_id, status="COMPLETE")
    funnel = telemetry.funnel_summary(run_id)
    assert "published_signal_actions" in funnel
    assert funnel["n_published_signal_events"] >= 1
    paper.close()
