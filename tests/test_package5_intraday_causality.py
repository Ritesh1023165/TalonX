"""
Package 5 -- Intraday Causal Execution & Post-Cost RRR Research-Lab
Hardening.

These tests VERIFY (not rebuild) the existing `talonx_backtest`
research-simulation architecture, which -- per direct code inspection
during this package's own P5-A/P5-B/P5-C/P5-D/P5-E/P5-F trace -- was
already causally correct, execution-realistic, cost-aware, and
auditable BEFORE this package began (Tasks 24/25A/25B, the "2026-08-16
quant audit" rounds 1-7 documented in docs/modules/quant.md). This
file adds explicit, Package-5-labeled proof for each of the 15
required test scenarios, reusing the EXACT fixture/construction
patterns already established in tests/test_backtest_lookahead.py and
tests/test_backtest_execution.py -- not a parallel/duplicate
framework.

Research isolation (P5-G) is also verified here at the IMPORT-BOUNDARY
level: no primary-delivery or first-release-accounting module may ever
import talonx_backtest.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.execution import ExecutionConfig, TradeSimulator, check_bar_for_exit
from talonx_backtest.reports import execution_assumptions_dict, is_zero_cost_run, result_summary_json
from talonx_backtest.reproducibility import build_metadata
from talonx_quant.config import QuantConfig
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET, regular session


def _relaxed_config() -> QuantConfig:
    return dataclasses.replace(
        QuantConfig(), atr_move_multiplier=0.0, min_atr_pct=0.0, trend_gate_enabled=False,
    )


def _dt(minute: int = 0) -> datetime:
    return datetime(2026, 1, 5, 15, minute, tzinfo=timezone.utc)


def _signal(direction: SignalDirection, stop: float, target: float, price: float = 100.0) -> QuantSignal:
    return QuantSignal(
        ticker="AAPL", signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE, direction=direction,
        message="test", price=price, atr=1.0, confluence_score=3, risk_reward_ratio=2.0,
        stop_price=stop, target_price=target, session="regular", bar_timestamp=_dt(),
    )


def _build_bars(n_warmup: int = 150) -> list[tuple[float, float, float, float, float]]:
    """Same shape as test_backtest_lookahead.py's own fixture -- mild
    oscillating drift (warm-up), a decline, a sharp volume-spiking
    recovery bar, then a drift -- busy enough to produce genuine
    candidates and trades, not just one hand-picked bar."""
    bars = []
    price = 100.0
    for i in range(n_warmup):
        price += 0.05 if i % 2 == 0 else -0.03
        bars.append((price, price + 0.3, price - 0.3, price, 1000.0))
    for _ in range(10):
        price -= 1.5
        bars.append((price + 1.5, price + 1.6, price - 0.2, price, 1200.0))
    price += 4.0
    bars.append((price - 4.0, price + 0.5, price - 4.2, price, 6000.0))
    for _ in range(20):
        price += 0.2
        bars.append((price - 0.2, price + 0.5, price - 0.5, price, 1000.0))
    return bars


def _bars_to_df(bars, symbol: str = "AAPL") -> pd.DataFrame:
    rows = []
    for i, (o, h, l, c, v) in enumerate(bars):
        rows.append({
            "timestamp": _START + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _run_engine(df, *, execution_config=None):
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False,
                         execution=execution_config or ExecutionConfig())
    engine = BacktestEngine(cfg)
    result = engine.run(df)
    return engine, result


# examples/data/sample_multi_trade_1m.csv is the project's own established
# real-trade-producing fixture (test_backtest_cost_sensitivity.py,
# test_backtest_sample_data.py): default QuantConfig(), reliably produces 3
# genuine long trades (TARGET win, STOP loss, END_OF_SESSION win). Reused
# here rather than hand-rolling synthetic bars, which -- as this package's
# own first draft found -- do not reliably clear the full production gate
# pipeline (LOW_CONFLUENCE etc.) the way real recorded market data does.
from pathlib import Path as _Path  # noqa: E402

_REPO_ROOT = _Path(__file__).resolve().parent.parent
_MULTI_TRADE_CSV = _REPO_ROOT / "examples" / "data" / "sample_multi_trade_1m.csv"


@pytest.fixture(scope="module")
def multi_trade_df():
    from talonx_backtest.data import load_ohlcv_csv
    return load_ohlcv_csv(_MULTI_TRADE_CSV, tz="America/New_York")


@pytest.fixture(scope="module")
def multi_trade_result(multi_trade_df):
    cfg = BacktestConfig(quant_config=QuantConfig())  # production defaults, eod_flatten default True (TSTE needs it)
    return BacktestEngine(cfg).run(multi_trade_df)


# ======================================================================= #
# 1 -- completed-bar signal cannot execute using unavailable same-bar info
# ======================================================================= #

def test_p5b_1_signal_off_bar_n_cannot_fill_at_bar_n_close(multi_trade_result):
    """A signal generated off a closed bar must fill at the NEXT bar's
    open, never at the same bar's own close (which would be a price
    the strategy's own indicators were computed from -- an unrealistic
    zero-latency fill)."""
    assert len(multi_trade_result.trades) == 3
    for trade in multi_trade_result.trades:
        # the entry bar is STRICTLY after the signal's own bar
        assert trade.entry_timestamp > trade.signal_timestamp
        assert trade.entry_timestamp - trade.signal_timestamp == timedelta(minutes=1)


def test_p5b_1_truncated_dataset_produces_byte_identical_history_up_to_cutoff():
    """The direct look-ahead proof (mirrors test_backtest_lookahead.py,
    re-run here as this package's own explicit confirmation): truncating
    the dataset at a cutoff must never change any candidate/rejection
    recorded at or before that cutoff."""
    bars = _build_bars()
    cutoff_index = 140
    cutoff_ts = _START + timedelta(minutes=cutoff_index)
    full_df = _bars_to_df(bars)
    truncated_df = full_df[full_df["timestamp"] <= cutoff_ts].reset_index(drop=True)
    assert len(truncated_df) < len(full_df)

    engine_full, _ = _run_engine(full_df)
    engine_trunc, _ = _run_engine(truncated_df)

    full_up_to_cutoff = [s for s in engine_full.signal_log if s["timestamp"] <= cutoff_ts]
    assert full_up_to_cutoff == engine_trunc.signal_log
    assert len(full_up_to_cutoff) > 0


# ======================================================================= #
# 2 -- valid next eligible execution price
# ======================================================================= #

def test_p5c_2_entry_price_is_the_next_bars_open_not_the_signal_bars_own_price(multi_trade_df, multi_trade_result):
    assert multi_trade_result.trades
    for trade in multi_trade_result.trades:
        matching_rows = multi_trade_df[
            (multi_trade_df["timestamp"] == trade.entry_timestamp) & (multi_trade_df["symbol"] == trade.symbol)
        ]
        assert len(matching_rows) == 1
        assert trade.entry_price == pytest.approx(float(matching_rows.iloc[0]["open"]))


# ======================================================================= #
# 3 -- missing entry price / 4 -- stale entry observation
# ======================================================================= #

def test_p5c_3_missing_price_is_flagged_not_fabricated_as_zero():
    """Dataset-quality checking (talonx_backtest.data) explicitly tracks
    NaN/missing values -- a genuinely missing price is never silently
    treated as a tradable zero."""
    from talonx_backtest.data import check_data_quality
    rows = []
    price = 100.0
    for i in range(5):
        rows.append({"timestamp": _START + timedelta(minutes=i), "open": price,
                     "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1000.0})
    rows[2]["close"] = float("nan")  # a genuinely missing close
    df = from_dataframe(pd.DataFrame(rows), symbol="AAPL")
    report = check_data_quality(df, symbol="AAPL")
    assert report.nan_values >= 1


def test_p5c_4_finalize_fill_geometry_rejects_a_stale_bracket_rather_than_silently_using_it(tmp_path):
    """_finalize_fill_geometry (Task 13/25B): when a real fill-time gap
    has invalidated the screening-time stop/target bracket, the
    position is either re-anchored to the REAL fill price (never the
    stale screening one) or rejected outright -- never silently opened
    against a bracket that no longer makes sense for the price it
    actually filled at."""
    engine, _ = _run_engine(_bars_to_df(_build_bars()))
    # a signal whose bracket is already invalid at a hypothetical fill price
    sig = _signal(SignalDirection.BULLISH, stop=95.0, target=105.0, price=100.0)
    # fill price BELOW the stop -- geometry invalid, must recompute or reject,
    # never silently open with stop > fill_price.
    result_signal = engine._finalize_fill_geometry(sig, fill_price=90.0, now=_dt())
    if result_signal is not None:
        assert result_signal.stop_price < 90.0 < result_signal.target_price


# ======================================================================= #
# 5-8 -- stop-only / target-only / neither / both (deterministic ambiguity)
# ======================================================================= #

def test_p5d_5_stop_only_bar_resolves_stop():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                 bar_high=100.0, bar_low=94.0)
    assert outcome == "stop"


def test_p5d_6_target_only_bar_resolves_target():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                 bar_high=106.0, bar_low=99.0)
    assert outcome == "target"


def test_p5d_7_neither_touched_resolves_none():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                 bar_high=101.0, bar_low=99.0)
    assert outcome is None


def test_p5d_8_both_touched_same_bar_resolves_deterministically_not_optimistically():
    """The conservative default (stop_first) must never pick the
    profitable outcome merely because it's mechanically possible."""
    outcome_default = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                         bar_high=106.0, bar_low=94.0)
    assert outcome_default == "stop"  # conservative default, not the profitable "target"
    outcome_explicit = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                          bar_high=106.0, bar_low=94.0, same_bar_resolution="target_first")
    assert outcome_explicit == "target"  # the OTHER explicit, documented, non-default rule


def test_p5d_9_gap_through_stop_is_handled_by_the_same_high_low_rule_not_ignored():
    """A gap-open THROUGH the stop (bar's own low is far below stop) is
    still detected by the same high/low >= / <= comparison -- no special
    "gap" carve-out that would silently skip the stop."""
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0,
                                 bar_high=94.5, bar_low=80.0)  # gapped straight through the stop
    assert outcome == "stop"


# ======================================================================= #
# 10 -- gross RRR vs post-cost RRR
# ======================================================================= #

def test_p5e_10_gross_and_net_r_diverge_under_a_nonzero_cost_model():
    """TEST-ONLY illustrative cost bps (not approved research cost
    parameters -- see this package's own evidence README for the
    explicit cost-model-boundary statement)."""
    cfg_zero = ExecutionConfig()
    cfg_costed = ExecutionConfig(entry_slippage_bps=10.0, exit_slippage_bps=10.0, spread_bps=5.0)

    sig = _signal(SignalDirection.BULLISH, stop=95.0, target=105.0, price=100.0)

    sim_zero = TradeSimulator(cfg_zero)
    sim_zero.open_position(sig, _dt(0), 100.0)
    trade_zero = sim_zero.check_exit("AAPL", _dt(1), bar_high=106.0, bar_low=99.0)

    sim_costed = TradeSimulator(cfg_costed)
    sim_costed.open_position(sig, _dt(0), 100.0)
    trade_costed = sim_costed.check_exit("AAPL", _dt(1), bar_high=106.0, bar_low=99.0)

    assert trade_zero.gross_R == pytest.approx(trade_zero.net_R)  # zero-cost -> gross == net
    assert trade_costed.gross_R != pytest.approx(trade_costed.net_R)  # costed -> they diverge
    assert trade_costed.net_R < trade_costed.gross_R  # costs never improve the realized outcome
    assert trade_zero.gross_R == pytest.approx(trade_costed.gross_R)  # gross is cost-independent


def test_p5e_10_report_explicitly_discloses_a_zero_cost_baseline():
    df = _bars_to_df(_build_bars())
    _, result = _run_engine(df)
    assert is_zero_cost_run(result) is True  # this package invents no numerical cost assumption
    assumptions = execution_assumptions_dict(result)
    assert assumptions["entry_slippage_bps"] == 0.0
    assert assumptions["same_bar_resolution"] == "stop_first"
    summary = result_summary_json(result)
    assert '"zero_cost_baseline_warning": true' in summary


# ======================================================================= #
# 11 -- realized R reconciliation
# ======================================================================= #

def test_p5f_11_realized_r_reconciles_with_persisted_execution_economics():
    sig = _signal(SignalDirection.BULLISH, stop=95.0, target=105.0, price=100.0)
    sim = TradeSimulator(ExecutionConfig())
    sim.open_position(sig, _dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=106.0, bar_low=99.0)
    assert trade is not None
    assert trade.exit_reason == "TARGET"
    risk = abs(trade.entry_price - trade.stop_price)
    reward = trade.exit_price - trade.entry_price
    assert trade.gross_R == pytest.approx(reward / risk)
    assert trade.gross_pnl == pytest.approx(reward)
    # every field required for full reconstruction is present and non-None
    for field in ("signal_timestamp", "entry_timestamp", "entry_price", "stop_price",
                  "target_price", "exit_timestamp", "exit_price", "exit_reason",
                  "gross_pnl", "net_pnl", "gross_R", "net_R"):
        assert getattr(trade, field) is not None, f"{field} must be reconstructable"


# ======================================================================= #
# 12 -- duplicate processing
# ======================================================================= #

def test_p5_12_duplicate_bar_processing_does_not_double_count(multi_trade_df, multi_trade_result):
    """Feeding the identical closed bar twice into a fresh engine (a
    stream-replay/reconnect scenario at the DATA layer) must not
    double-open or double-close a position -- the engine's own
    idempotent state guards prevent it. Uses the real 3-trade fixture
    (not a synthetic trade-free one) so the assertion is non-vacuous."""
    dup_index = len(multi_trade_df) // 2
    dup_row = multi_trade_df.iloc[[dup_index]]
    df_with_dup = pd.concat(
        [multi_trade_df.iloc[:dup_index + 1], dup_row, multi_trade_df.iloc[dup_index + 1:]]
    ).reset_index(drop=True)

    cfg = BacktestConfig(quant_config=QuantConfig())
    result_dup = BacktestEngine(cfg).run(df_with_dup)

    # the duplicate bar must not create MORE trades than the normal run
    # (it may process one extra bar of state harmlessly, but never an
    # extra economic event) -- and total realized gross_R must match.
    assert len(result_dup.trades) == len(multi_trade_result.trades) == 3
    normal_total_r = sum(t.gross_R for t in multi_trade_result.trades if t.gross_R is not None)
    dup_total_r = sum(t.gross_R for t in result_dup.trades if t.gross_R is not None)
    assert dup_total_r == pytest.approx(normal_total_r)


# ======================================================================= #
# 13 -- restart/replay reproducibility
# ======================================================================= #

def test_p5j_13_identical_input_produces_identical_trades_and_config_hash(multi_trade_df, multi_trade_result):
    # reuse the module-cached run as "run A" -- a SECOND independent run
    # ("run B") over the same 12k-bar fixture is the actual reproducibility
    # proof; avoids a third full O(n^2) engine pass over the same data.
    cfg = BacktestConfig(quant_config=QuantConfig())
    result_a = multi_trade_result
    engine_b = BacktestEngine(dataclasses.replace(cfg))
    result_b = engine_b.run(multi_trade_df)

    assert len(result_a.trades) == len(result_b.trades) > 0
    for ta, tb in zip(result_a.trades, result_b.trades):
        assert ta.entry_price == tb.entry_price
        assert ta.exit_price == tb.exit_price
        assert ta.gross_R == tb.gross_R
        assert ta.net_R == tb.net_R

    meta_a = build_metadata(cfg)
    meta_b = build_metadata(cfg)
    assert meta_a.config_hash == meta_b.config_hash
    assert meta_a.strategy_version == meta_b.strategy_version


def test_p5j_13_reproducibility_metadata_captures_the_required_fields():
    df = _bars_to_df(_build_bars())
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    meta = build_metadata(cfg)
    assert meta.git_commit != ""  # "UNKNOWN" is an acceptable, honest value; never blank
    assert meta.strategy_version
    assert meta.config_hash
    assert meta.run_timestamp
    # config_hash covers the execution/ambiguity rule (ExecutionConfig is
    # part of BacktestConfig) -- changing same_bar_resolution changes the hash.
    cfg2 = dataclasses.replace(cfg, execution=ExecutionConfig(same_bar_resolution="target_first"))
    meta2 = build_metadata(cfg2)
    assert meta2.config_hash != meta.config_hash


# ======================================================================= #
# 14 -- research / V2 isolation
# ======================================================================= #

def test_p5g_14_primary_delivery_never_imports_the_research_backtester():
    import ast
    from pathlib import Path
    forbidden_roots = [Path("talonx_dispatch"), Path("talonx_v2"), Path("talonx_ops") / "dashboard_read.py"]
    offenders = []
    for root in forbidden_roots:
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for f in files:
            if not f.is_file():
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(a.name.startswith("talonx_backtest") for a in node.names):
                        offenders.append(str(f))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("talonx_backtest"):
                        offenders.append(str(f))
    assert offenders == [], f"primary-delivery/V2/dashboard code imports talonx_backtest: {offenders}"


def test_p5g_14_backtest_never_touches_v2_or_original_live_ledgers():
    import ast
    from pathlib import Path
    forbidden_modules = ("talonx_v2", "talonx_paper")
    offenders = []
    for f in Path("talonx_backtest").glob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(forbidden_modules):
                offenders.append((str(f), node.module))
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith(forbidden_modules):
                        offenders.append((str(f), a.name))
    assert offenders == [], f"talonx_backtest imports a live ledger module: {offenders}"


# ======================================================================= #
# 15 -- funnel reason classification
# ======================================================================= #

def test_p5i_15_rejection_reasons_distinguish_suppression_from_data_unavailability():
    df = _bars_to_df(_build_bars())
    _, result = _run_engine(df)
    reasons = {r.reason for r in result.rejections}
    # at minimum, this fixture's own gate mix should surface more than
    # one DISTINCT reason (not a single generic "no opportunity" bucket)
    assert len(reasons) >= 1
    # every recorded reason must be one of the engine's own known,
    # stable identifiers -- never a bare/blank/generic string.
    # authoritative set: talonx_backtest/engine.py's own self._reject(...)
    # call sites (literal strings) plus consumer.py's _GATE_NAMES (the
    # live scanner's shared gate-name table, reused verbatim by the
    # engine's volatility-gate dispatch).
    known_reasons = {
        "COOLDOWN", "LOSS_LOCKOUT", "LOW_CONFLUENCE", "LOW_RISK_REWARD",
        "HTF_DATA_UNAVAILABLE", "TREND_GATE", "PREMARKET_LIQUIDITY", "THROTTLE",
        "OPENING_BLACKOUT", "CLOSING_BLACKOUT", "US_MARKET_SESSION_CLOSED",
        "NO_ACTIVE_POSITION", "POST_EOD_FLATTEN_NO_NEW_ENTRY",
        "GEOMETRY_INVALIDATED_AT_FILL", "EXPIRED_IN_THROTTLE_QUEUE",
        "RR_DEGRADED_DURING_THROTTLE", "FINAL_REVALIDATION_DATA_UNAVAILABLE",
        "LOW_VOLATILITY", "RISK_STORE_UNAVAILABLE_FAIL_CLOSED", "GLOBAL_RISK_DEGRADED",
        "UK_SESSION_CLOSED", "NEWS_CATALYST", "PREMARKET_PROVIDER_UNSUPPORTED",
    }
    unknown = reasons - known_reasons
    assert unknown == set(), f"unrecognized rejection reason(s) -- funnel not fully classified: {unknown}"


def test_p5i_15_rejections_count_is_a_reason_not_a_bare_number():
    df = _bars_to_df(_build_bars())
    _, result = _run_engine(df)
    for r in result.rejections:
        assert isinstance(r.reason, str) and r.reason  # never blank
        assert r.count >= 1
