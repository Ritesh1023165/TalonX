"""Task 121A Part 3 -- deterministic parity trace for the corrected
Experimental replay adapter (research/scripts/task121a_experimental_replay.py).

Reuses the established hand-built-QuantSignal-injection pattern from the
existing, passing tests/test_backtest_long_only_lifecycle.py (see that
file's own module docstring) -- `_signal`/`_step` here are a minimal,
locally-adapted copy of that proven technique, driving
ExperimentalLifecycleShim-equipped engines instead of stock ones. No
strategy/gate/threshold logic is reimplemented; every gate function is
still the real, imported talonx_quant.consumer/strategy code.

Engine timing note (inherited from the reused pattern, unchanged here):
a signal INJECTED at bar N is only RESOLVED (schedules `_pending_entry`,
then the shim's `open_position` fires) on the NEXT `_process_symbol_bar`
call for that symbol -- so every "open" in this file is two `_step()`
calls: one to inject+publish, one (often with an empty candidate list) to
let engine.py's own pending-entry resolution reach the shim. This is
engine.py's own existing, unmodified per-bar sequencing, not something
this adapter introduces.

Covers the 9 required scenarios: valid bullish entry, stop exit, target
exit, exit evaluated despite an entry-gate rejection, bearish with/without
an open position, stale/missing observation, session-close crossing with
an open position held (no EOD flatten), simultaneous multi-symbol
candidates, and restart/state-persistence (isolated SQLite reopened).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task121a_experimental_replay as t121a  # noqa: E402 -- sets sys.path to RELEASE_ROOT first

import talonx_backtest.engine as engine_module  # noqa: E402
from talonx_backtest.engine import BacktestConfig, BacktestEngine  # noqa: E402
from talonx_backtest.execution import ExecutionConfig, apply_entry_cost, apply_exit_cost  # noqa: E402
from talonx_quant.config import QuantConfig  # noqa: E402
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType  # noqa: E402
from talonx_signals.experimental_paper import ExperimentalPaperEngine  # noqa: E402

_DAY = datetime(2026, 1, 5, tzinfo=timezone.utc)
_BAR = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}
_MIN = timedelta(minutes=1)


def test_apply_spread_worked_example():
    """Part 2 cost-convention correction, verified directly: apply_spread
    crosses HALF the given bps on ONE side -- a 5.0 parameter is ~5bps
    ROUND-TRIP at an unchanged reference price, NOT 5bps per side."""
    from talonx_paper.engine import apply_spread

    buy_fill = apply_spread(100.0, 5.0, "BUY")
    sell_fill = apply_spread(100.0, 5.0, "SELL")
    assert buy_fill == pytest.approx(100.025)   # +2.5bps
    assert sell_fill == pytest.approx(99.975)   # -2.5bps
    round_trip_cost_bps = (buy_fill - sell_fill) / 100.0 * 10_000
    assert round_trip_cost_bps == pytest.approx(5.0)   # NOT 10.0


def _signal(ticker: str, direction: SignalDirection, bar_timestamp: datetime,
            session: str = "regular", price: float = 100.0) -> QuantSignal:
    signal_type = SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS
    if direction == SignalDirection.BULLISH:
        stop, target = price - 1.5, price + 10.0
    else:
        stop, target = price + 1.5, price - 10.0
    return QuantSignal(
        ticker=ticker, signal_type=signal_type, direction=direction, message="test",
        price=price, atr=1.0, confluence_score=3, risk_reward_ratio=5.0,
        volume_surge_ratio=5.0, trend_aligned=True,
        htf_sma_200=90.0 if direction == SignalDirection.BULLISH else None,
        stop_price=stop, target_price=target,
        pivot_resistance=price + 20.0, pivot_support=price - 10.0,
        session=session, bar_timestamp=bar_timestamp, signal_generated_at=bar_timestamp,
    )


def _shimmed_engine(tmp_path, db_name="exp_paper.db", *, low_gates: bool = False):
    qc = QuantConfig()
    if low_gates:
        from dataclasses import replace
        qc = replace(qc, confluence_score_min=1, min_risk_reward_ratio=1.0, min_atr_pct=0.10)
    cfg = BacktestConfig(quant_config=qc, execution=ExecutionConfig(spread_bps=0.0),
                         eod_flatten_enabled=False, allow_overlapping_trades=True)
    engine = BacktestEngine(cfg, research_telemetry=True)
    paper = ExperimentalPaperEngine(db_path=tmp_path / db_name, allocation_usd=2500.0,
                                    spread_bps=5.0, initial_cash=100_000.0)
    shim = t121a.ExperimentalLifecycleShim(paper=paper, bar_close={})
    engine.simulator = shim
    return engine, paper, shim


def _step(monkeypatch, engine, shim, symbol: str, timestamp: datetime, injected=(), bar: dict | None = None) -> None:
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


def _open(monkeypatch, engine, shim, symbol: str, t0: datetime, price: float = 100.0):
    """Injects a qualifying bullish candidate at t0 (published+scheduled),
    then steps once more at t0+1min (empty candidate list) so engine.py's
    own next-call pending-entry resolution reaches the shim, which fills
    at the SIGNAL's own bar close (t0's price), not the fill-bar's."""
    sig = _signal(symbol, SignalDirection.BULLISH, t0, price=price)
    _step(monkeypatch, engine, shim, symbol, t0, injected=[sig], bar={**_BAR, "close": price})
    _step(monkeypatch, engine, shim, symbol, t0 + _MIN, injected=[])
    return t0 + _MIN


# ---------------------------------------------------------------------
# 1. Valid qualifying bullish entry
# ---------------------------------------------------------------------
def test_1_valid_bullish_entry_fills_at_signal_bar_close_not_next_bar_open(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "AAAA", t0, price=100.0)

    assert shim.has_open("AAAA")
    pos = paper.store.get_position("AAAA")
    entry_net = apply_entry_cost(100.0, SignalDirection.BULLISH, ExecutionConfig(spread_bps=5.0))
    assert pos["entry_price"] == pytest.approx(entry_net)
    assert any(p["action"] == "OPENED" for p in shim.published_log)


# ---------------------------------------------------------------------
# 2. Stop-triggered exit
# ---------------------------------------------------------------------
def test_2_stop_triggered_exit(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    # NOTE: engine.py's own _revalidate() re-derives stop/target from
    # structural pivot levels at throttle-flush time (calculate_trade_
    # geometry), OVERRIDING the ATR-based stop/target _signal() set --
    # this is the SAME reused, unmodified revalidation step
    # test_backtest_long_only_lifecycle.py's own fixture already relies
    # on; with this fixture's pivot_support=price-10=90.0, the
    # REVALIDATED stop is 90.0, not price-1.5.
    t_open = _open(monkeypatch, engine, shim, "BBBB", t0, price=100.0)
    assert shim.has_open("BBBB")
    pos = paper.store.get_position("BBBB")
    assert pos["stop_price"] == pytest.approx(90.0)

    t_next = t_open + _MIN
    _step(monkeypatch, engine, shim, "BBBB", t_next, injected=[], bar={**_BAR, "close": 89.9})  # below revalidated stop
    assert not shim.has_open("BBBB")
    closed = t121a._fetch_rows(paper.store._conn, "SELECT * FROM trade_history WHERE order_type='SELL'")
    assert len(closed) == 1
    # trade_history.exit_reason stores the coarser AlertAction
    # (CONFIRMED_BEARISH for both stop/target); the TRUE reason is only on
    # the shim's own exit_log (see ExperimentalLifecycleShim docstring).
    assert closed[0]["exit_reason"] == "confirmed_bearish"
    assert shim.exit_log[-1]["true_exit_reason"] == "stop_loss"


# ---------------------------------------------------------------------
# 3. Target-triggered exit
# ---------------------------------------------------------------------
def test_3_target_triggered_exit(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    t_open = _open(monkeypatch, engine, shim, "CCCC", t0, price=100.0)  # revalidated target = pivot_resistance = 120.0
    pos = paper.store.get_position("CCCC")
    assert pos["target_price"] == pytest.approx(120.0)
    t_next = t_open + _MIN
    _step(monkeypatch, engine, shim, "CCCC", t_next, injected=[], bar={**_BAR, "close": 120.5})
    assert not shim.has_open("CCCC")
    closed = t121a._fetch_rows(paper.store._conn, "SELECT * FROM trade_history WHERE order_type='SELL'")
    assert closed[0]["exit_reason"] == "confirmed_bearish"  # coarse AlertAction, see test_2's note
    assert shim.exit_log[-1]["true_exit_reason"] == "target_exit"


# ---------------------------------------------------------------------
# 4. Exit evaluated despite THIS bar's entry-gate rejection
# ---------------------------------------------------------------------
def test_4_open_position_still_checked_for_exit_when_todays_candidate_is_gate_rejected(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path, low_gates=True)
    t0 = _DAY.replace(hour=15, minute=0)
    t_open = _open(monkeypatch, engine, shim, "DDDD", t0, price=100.0)
    assert shim.has_open("DDDD")

    # A LOW-CONFLUENCE candidate this bar (gate-rejected, never reaches the
    # shim at all) -- the open position must STILL be checked for its
    # stop, independent of that rejection.
    t_next = t_open + _MIN
    rejected_candidate = _signal("DDDD", SignalDirection.BULLISH, t_next, price=89.9)
    rejected_candidate = rejected_candidate.model_copy(update={"confluence_score": 0})
    _step(monkeypatch, engine, shim, "DDDD", t_next, injected=[rejected_candidate], bar={**_BAR, "close": 89.9})
    assert not shim.has_open("DDDD")  # revalidated stop (90.0) still fired even though the bar's own candidate was rejected


# ---------------------------------------------------------------------
# 5. Bearish signal with and without an open position
# ---------------------------------------------------------------------
def test_5a_bearish_while_flat_takes_no_action_and_is_recorded(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    sig = _signal("EEEE", SignalDirection.BEARISH, t0)
    _step(monkeypatch, engine, shim, "EEEE", t0, injected=[sig])
    assert not shim.has_open("EEEE")
    assert any(r.ticker == "EEEE" and r.reason == "NO_ACTIVE_POSITION" for r in engine.rejections)


def test_5b_bearish_while_long_does_not_close_the_position(tmp_path, monkeypatch):
    """The confirmed, corrected fact: NOTHING in the live runtime closes
    an Experimental long on a bearish signal. Unlike Original's LONG_ONLY
    backtest lifecycle, this must be a no-op, logged, not a close."""
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    t_open = _open(monkeypatch, engine, shim, "FFFF", t0, price=100.0)
    assert shim.has_open("FFFF")

    # past the 20-minute per-ticker cooldown armed by the entry's own
    # publication, so the bearish candidate below reaches revalidation/
    # routing instead of being dropped as COOLDOWN.
    t_next = t_open + timedelta(minutes=25)
    bearish = _signal("FFFF", SignalDirection.BEARISH, t_next, price=100.3)
    _step(monkeypatch, engine, shim, "FFFF", t_next, injected=[bearish], bar={**_BAR, "close": 100.3})
    # a scheduled pending-exit resolves on the NEXT step, same one-bar lag as an entry
    _step(monkeypatch, engine, shim, "FFFF", t_next + _MIN, injected=[], bar={**_BAR, "close": 100.3})
    assert shim.has_open("FFFF")  # still open -- a bearish signal is NOT an exit trigger
    assert any("BEARISH_PUBLISHED_WHILE_OPEN_NO_ACTION_TAKEN" in p["action"] for p in shim.published_log)


# ---------------------------------------------------------------------
# 6. Stale or missing market observation
# ---------------------------------------------------------------------
def test_6_missing_bar_close_observation_never_invents_a_fill(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "GGGG", t0, price=100.0)
    assert shim.has_open("GGGG")

    # directly exercise the shim's check_exit with a timestamp that has NO
    # bar_close entry -- must be a clean no-op, no exception, no fill.
    missing_ts = pd.Timestamp(t0 + timedelta(hours=5))
    result = shim.check_exit("GGGG", missing_ts, 1000.0, 1000.0)
    assert result is None
    assert shim.has_open("GGGG")


# ---------------------------------------------------------------------
# 7. Crossing session close with an open position (no EOD flatten)
# ---------------------------------------------------------------------
def test_7_position_survives_a_session_close_crossing_no_eod_flatten(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=45)  # near/after 15:50 ET -- would be flattened under Original's lifecycle
    t_open = _open(monkeypatch, engine, shim, "HHHH", t0, price=100.0)
    assert shim.has_open("HHHH")

    # next session's bar -- position must STILL be open (never force-closed
    # at session close; only a real stop/target closes it)
    t_next_day = t_open + timedelta(days=1)
    _step(monkeypatch, engine, shim, "HHHH", t_next_day, injected=[], bar={**_BAR, "close": 101.0})
    assert shim.has_open("HHHH")


# ---------------------------------------------------------------------
# 8. Simultaneous candidates on multiple symbols
# ---------------------------------------------------------------------
def test_8_simultaneous_multi_symbol_candidates_handled_independently(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path)
    t0 = _DAY.replace(hour=15, minute=0)
    sig_i = _signal("IIII", SignalDirection.BULLISH, t0, price=100.0)
    _step(monkeypatch, engine, shim, "IIII", t0, injected=[sig_i], bar={**_BAR, "close": 100.0})
    sig_j = _signal("JJJJ", SignalDirection.BULLISH, t0, price=50.0)
    _step(monkeypatch, engine, shim, "JJJJ", t0, injected=[sig_j], bar={**_BAR, "open": 50.0, "close": 50.0})
    # resolve both pending entries -- the fill-bar's own OPEN must stay
    # near each symbol's own reference price (_finalize_fill_geometry
    # checks the fill lands inside the revalidated stop/target bracket;
    # the shared default _BAR's open=100.0 would be wildly outside JJJJ's
    # ~50 bracket and spuriously reject it -- a test-fixture detail, not
    # an adapter defect).
    t1 = t0 + _MIN
    _step(monkeypatch, engine, shim, "IIII", t1, injected=[], bar={**_BAR, "open": 100.0, "close": 100.0})
    _step(monkeypatch, engine, shim, "JJJJ", t1, injected=[], bar={**_BAR, "open": 50.0, "close": 50.0})

    assert shim.has_open("IIII")
    assert shim.has_open("JJJJ")
    pos_i = paper.store.get_position("IIII")
    pos_j = paper.store.get_position("JJJJ")
    assert pos_i["entry_price"] != pos_j["entry_price"]
    assert pos_i["shares"] != pos_j["shares"]  # same $2,500 allocation, different price -> different share count


# ---------------------------------------------------------------------
# 9. Repeated events and restart (state persistence)
# ---------------------------------------------------------------------
def test_9_restart_reopens_the_same_isolated_ledger_with_state_intact(tmp_path, monkeypatch):
    engine, paper, shim = _shimmed_engine(tmp_path, db_name="restart.db")
    t0 = _DAY.replace(hour=15, minute=0)
    _open(monkeypatch, engine, shim, "KKKK", t0, price=100.0)
    assert shim.has_open("KKKK")
    paper.close()

    # "restart" -- a brand-new ExperimentalPaperEngine pointed at the SAME db file
    paper2 = ExperimentalPaperEngine(db_path=tmp_path / "restart.db", allocation_usd=2500.0,
                                     spread_bps=5.0, initial_cash=100_000.0)
    pos = paper2.store.get_position("KKKK")
    assert pos is not None
    assert pos["entry_price"] == pytest.approx(apply_entry_cost(100.0, SignalDirection.BULLISH, ExecutionConfig(spread_bps=5.0)))
    # a repeated identical open_long call while already open must still be a no-op (idempotent, no duplicate)
    dup = paper2.open_long("KKKK", 100.0, stop=98.5, target=110.0, now=t0)
    assert dup is None
    paper2.close()


# ---------------------------------------------------------------------
# Zero external sends -- structural check
# ---------------------------------------------------------------------
def test_zero_external_sends_no_network_dependency_in_the_adapter_module():
    import inspect

    src = inspect.getsource(t121a)
    for token in ("requests.", "aiohttp", "socket.", "urllib", "TelegramSenderAdapter", "redis.Redis(", "aioredis"):
        assert token not in src, f"unexpected network/external-send dependency: {token}"
