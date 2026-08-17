"""
talonx_backtest.reports
----------------------------
Machine-readable (JSON/CSV) and human-readable output for a completed
BacktestResult. Never fabricates numbers -- every value here is read
directly off engine.BacktestResult/metrics.PerformanceMetrics; a report
generated from zero trades says so explicitly rather than omitting
sections or inventing placeholder figures.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from io import StringIO
from pathlib import Path

from talonx_backtest import analysis, reproducibility
from talonx_backtest.data import DataQualityReport
from talonx_backtest.engine import BacktestResult, RejectionRecord
from talonx_backtest.metrics import PerformanceMetrics, metric_set
from talonx_backtest.portfolio import Trade

_SESSION_TIMEZONE = "America/New_York"  # talonx_quant.session's hardcoded market-session timezone

PORTFOLIO_DISCLAIMER = (
    "This backtest evaluates TRADE-LEVEL strategy performance (R-multiples per signal). "
    "It does NOT model starting capital, position sizing, maximum portfolio exposure, "
    "concurrent-position limits, or buying power. Aggregate R/expectancy figures here "
    "describe the strategy's per-trade edge, not a realistic portfolio-level return."
)

SURVIVORSHIP_BIAS_NOTE = (
    "This is an INDIVIDUAL-SECURITY backtest, not a historical-universe backtest. If the "
    "symbol(s) tested were selected because they are prominent/liquid TODAY (e.g. current "
    "S&P 500 constituents), results may overstate historical edge relative to a "
    "point-in-time universe that would have also included names that were later delisted, "
    "acquired, or otherwise dropped out -- classic survivorship bias. Point-in-time "
    "universe construction is not implemented by this engine; interpret results "
    "accordingly, especially over long lookback periods."
)


def execution_assumptions_dict(result: BacktestResult) -> dict:
    """The exact execution-mechanics settings this run used -- read
    straight off result.config, never re-derived or guessed. Spec
    section 8: these must be prominent in every report, not buried in
    raw JSON."""
    execution = result.config.execution
    return {
        "entry_slippage_bps": execution.entry_slippage_bps,
        "exit_slippage_bps": execution.exit_slippage_bps,
        "spread_bps": execution.spread_bps,
        "same_bar_resolution": execution.same_bar_resolution,
        "eod_flatten_enabled": result.config.eod_flatten_enabled,
        "allow_overlapping_trades": result.config.allow_overlapping_trades,
    }


def is_zero_cost_run(result: BacktestResult) -> bool:
    execution = result.config.execution
    return execution.entry_slippage_bps == 0 and execution.exit_slippage_bps == 0 and execution.spread_bps == 0


# 30 matches metrics.py's own documented threshold ("never treat a CI
# from under ~30 trades as tight") -- Sharpe/Sortino/confidence
# intervals all lean on a normal-approximation/CLT assumption that
# isn't trustworthy below roughly this many observations.
SMALL_SAMPLE_TRADE_THRESHOLD = 30


def is_small_sample(trade_count: int) -> bool:
    """True when there's at least one trade but fewer than
    SMALL_SAMPLE_TRADE_THRESHOLD -- zero trades already gets its own
    "no trades were executed" messaging elsewhere, so this is
    specifically the "statistics exist but shouldn't be over-trusted"
    case (spec: keep the numbers, just make the caveat impossible to
    miss)."""
    return 0 < trade_count < SMALL_SAMPLE_TRADE_THRESHOLD


def timezone_info_dict(input_timezone: str | None) -> dict:
    """Spec section 12: the report must show input/internal/session
    timezone explicitly, never leave a reader to infer them. `internal`
    is always UTC (every talonx_backtest.data loader normalizes to it);
    `session` is talonx_quant.session's hardcoded America/New_York
    market-session timezone (not configurable -- it IS the US equities
    market's own timezone). `input_timezone` is None when the caller
    didn't say what --tz was used (e.g. building a report without going
    through the CLI) -- reported as "unspecified", never guessed."""
    return {
        "input_timezone": input_timezone or "unspecified",
        "internal_timezone": "UTC",
        "session_timezone": _SESSION_TIMEZONE,
    }


def trades_to_csv(trades: list[Trade]) -> str:
    """Always writes a header row, even with zero trades -- a
    zero-byte trades.csv is genuinely ambiguous (empty file? crashed
    run? really zero trades?), whereas a headers-only CSV unambiguously
    says "this ran, and executed zero trades." Every column comes from
    portfolio.Trade's own field list, so the header never drifts out of
    sync with what a populated row actually contains."""
    buf = StringIO()
    fieldnames = [f.name for f in fields(Trade)]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for t in trades:
        writer.writerow(t.to_dict())
    return buf.getvalue()


def trades_to_json(trades: list[Trade]) -> str:
    return json.dumps([t.to_dict() for t in trades], indent=2, default=str)


def metrics_to_dict(m: PerformanceMetrics) -> dict:
    d = asdict(m)
    for key in ("win_rate_ci", "expectancy_ci", "average_r_ci"):
        if d.get(key) is not None:
            d[key] = {k: v for k, v in d[key].items()}
    return d


def result_summary_text(
    result: BacktestResult,
    input_timezone: str | None = None,
    dataset_path: str | Path | None = None,
    dataset_symbols: list[str] | None = None,
) -> str:
    assumptions = execution_assumptions_dict(result)
    tz = timezone_info_dict(input_timezone)
    meta = reproducibility.build_metadata(result.config, dataset_path=dataset_path, dataset_symbols=dataset_symbols)

    lines = [
        "Backtest Summary",
        "----------------",
        "",
        f"Period:               {result.start} -> {result.end}",
        f"Symbols:              {', '.join(result.symbols)}",
        f"Bars processed:       {result.bars_processed:,}",
        f"Signals generated:    {result.signals_generated}",
        f"Signals published:    {result.signals_published}",
        f"Trades executed:      {len(result.trades)}",
        f"Throttle fidelity:    {result.config.throttle_fidelity}",
        "",
        "Execution assumptions",
        "----------------------",
        f"Entry slippage:       {assumptions['entry_slippage_bps']} bps",
        f"Exit slippage:        {assumptions['exit_slippage_bps']} bps",
        f"Spread:               {assumptions['spread_bps']} bps",
        f"Same-bar resolution:  {assumptions['same_bar_resolution'].upper()}",
        f"EOD flatten:          {'ENABLED' if assumptions['eod_flatten_enabled'] else 'DISABLED'}",
        "",
    ]

    if is_zero_cost_run(result):
        lines += [
            "*** COST-FREE BASELINE ***",
            "Slippage: 0 bps   Spread: 0 bps",
            "These results do NOT represent realistic execution costs -- do not call this",
            "\"realistic performance\" or \"live expected return\". Use --cost-sensitivity for",
            "a range of non-zero cost assumptions.",
            "",
        ]

    lines += [
        "Timezone",
        "--------",
        f"Input timezone:       {tz['input_timezone']}",
        f"Internal timezone:    {tz['internal_timezone']}",
        f"Session timezone:     {tz['session_timezone']}",
        "",
        "Reproducibility",
        "----------------",
        f"git_commit:           {meta.git_commit}",
        f"backtester_version:   {meta.backtester_version}",
        f"strategy_version:     {meta.strategy_version}",
        f"config_hash:          {meta.config_hash}",
        f"dataset_hash:         {meta.dataset_hash}",
        f"run_timestamp:        {meta.run_timestamp}",
        "",
        "Portfolio disclaimer",
        "---------------------",
        PORTFOLIO_DISCLAIMER,
        "",
    ]

    if not result.trades:
        lines.append("No trades were executed -- see `rejections` for the gate funnel (no fabricated metrics below).")
        return "\n".join(lines)

    if is_small_sample(len(result.trades)):
        lines += [
            f"*** SMALL SAMPLE ({len(result.trades)} trade{'s' if len(result.trades) != 1 else ''}) ***",
            "Sharpe, Sortino, and confidence intervals below are NOT statistically reliable at this",
            "trade count (normal-approximation/CLT assumptions need roughly 30+ observations) -- treat",
            "them as illustrative only. Win rate/profit factor/expectancy are exact arithmetic over what",
            "occurred, but may not represent the strategy's true long-run behavior at this sample size.",
            "",
        ]

    sets = metric_set(result.trades)
    for label in ("gross", "net"):
        lines.append(f"--- {label.upper()} (before costs)" if label == "gross" else f"--- {label.upper()} (after slippage/spread)")
        lines.extend(sets[label].summary_lines())
        lines.append("")

    return "\n".join(lines)


def result_summary_json(
    result: BacktestResult,
    input_timezone: str | None = None,
    cost_sensitivity: list[dict] | None = None,
    dataset_path: str | Path | None = None,
    dataset_symbols: list[str] | None = None,
) -> str:
    sets = metric_set(result.trades) if result.trades else {}
    meta = reproducibility.build_metadata(result.config, dataset_path=dataset_path, dataset_symbols=dataset_symbols)
    payload = {
        "period": {"start": str(result.start), "end": str(result.end)},
        "symbols": result.symbols,
        "bars_processed": result.bars_processed,
        "signals_generated": result.signals_generated,
        "signals_published": result.signals_published,
        "trades_executed": len(result.trades),
        "throttle_fidelity": result.config.throttle_fidelity,
        "execution_assumptions": execution_assumptions_dict(result),
        "zero_cost_baseline_warning": is_zero_cost_run(result),
        "small_sample_warning": is_small_sample(len(result.trades)),
        "timezone": timezone_info_dict(input_timezone),
        "reproducibility": meta.to_dict(),
        "portfolio_disclaimer": PORTFOLIO_DISCLAIMER,
        "survivorship_bias_note": SURVIVORSHIP_BIAS_NOTE,
        "metrics": {label: metrics_to_dict(m) for label, m in sets.items()},
        "rejections_by_reason": _rejection_counts(result),
        "cost_sensitivity": cost_sensitivity or [],
    }
    return json.dumps(payload, indent=2, default=str)


def _rejection_counts(result: BacktestResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in result.rejections:
        counts[r.reason] = counts.get(r.reason, 0) + r.count
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


EQUITY_CURVE_FIELDS = ("sequence", "trade_id", "symbol", "exit_timestamp", "gross_R", "net_R", "cumulative_gross_R", "cumulative_net_R")


def equity_curve_rows(trades: list[Trade]) -> list[dict]:
    """One row per closed trade, ordered by exit_timestamp (the order
    P&L was actually realized in) -- cumulative_gross_R/cumulative_net_R
    are the running equity curve metrics.max_drawdown_r is computed
    from, exposed here so a caller (or the HTML report) can plot it
    without recomputing the ordering logic."""
    ordered = sorted((t for t in trades if t.exit_timestamp is not None), key=lambda t: t.exit_timestamp)
    rows = []
    cum_gross = 0.0
    cum_net = 0.0
    for i, t in enumerate(ordered, start=1):
        cum_gross += t.gross_R or 0.0
        cum_net += t.net_R or 0.0
        rows.append({
            "sequence": i, "trade_id": t.trade_id, "symbol": t.symbol,
            "exit_timestamp": str(t.exit_timestamp), "gross_R": t.gross_R, "net_R": t.net_R,
            "cumulative_gross_R": cum_gross, "cumulative_net_R": cum_net,
        })
    return rows


def equity_curve_to_csv(trades: list[Trade]) -> str:
    """Always writes a header row, even with zero closed trades -- same
    "never an ambiguous zero-byte file" reasoning as trades_to_csv. An
    equity curve is inherently anchored to trade EXITS (each row is "the
    running R total as of this realized trade"), so with no trades there
    is no real observation to report -- a header-only, zero-row file is
    the honest representation, not a fabricated `0.0 at the period
    start` reading that never actually happened."""
    rows = equity_curve_rows(trades)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(EQUITY_CURVE_FIELDS))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def rejected_signals_to_csv(rejections: list[RejectionRecord]) -> str:
    if not rejections:
        return ""
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=["ticker", "reason", "count", "timestamp"])
    writer.writeheader()
    for r in rejections:
        writer.writerow({"ticker": r.ticker, "reason": r.reason, "count": r.count, "timestamp": str(r.timestamp)})
    return buf.getvalue()


def data_quality_to_json(reports: dict[str, DataQualityReport] | None) -> str:
    if not reports:
        return json.dumps({}, indent=2)
    payload = {}
    for symbol, r in reports.items():
        d = asdict(r)
        d.pop("missing_bar_gaps", None)  # tuple-of-Timestamp pairs -- not cleanly JSON-serializable, summary() covers it
        d["is_clean"] = r.is_clean
        payload[symbol] = d
    return json.dumps(payload, indent=2, default=str)


def cost_sensitivity_to_csv(rows: list[dict] | None) -> str:
    if not rows:
        return ""
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


_BREAKDOWN_FUNCS = {
    "by_symbol": analysis.by_symbol,
    "by_confluence": analysis.by_confluence,
    "by_risk_reward": analysis.by_risk_reward,
    "by_volume_surge": analysis.by_volume_surge,
    "by_session": analysis.by_session,
    "by_time_of_day": analysis.by_time_of_day,
    "by_direction": analysis.by_direction,
    "by_trend_alignment": analysis.by_trend_alignment,
}


def _breakdown_payload(trades: list[Trade], r_field: str) -> dict[str, dict[str, dict]]:
    payload = {}
    for label, fn in _BREAKDOWN_FUNCS.items():
        buckets = fn(trades, r_field=r_field)
        payload[label] = {
            bucket: {
                "trades": m.total_trades, "win_rate": m.win_rate, "expectancy_r": m.expectancy_r,
                "total_r": m.total_r, "profit_factor": None if m.profit_factor in (None, float("inf")) else m.profit_factor,
            }
            for bucket, m in buckets.items()
        }
    return payload


def build_html_report(
    result: BacktestResult,
    data_quality: dict[str, DataQualityReport] | None = None,
    input_timezone: str | None = None,
    cost_sensitivity: list[dict] | None = None,
    dataset_path: str | Path | None = None,
    dataset_symbols: list[str] | None = None,
) -> str:
    """A single, self-contained HTML file (no external requests, no CDN,
    inline CSS/JS only -- opens directly from disk in any browser) with
    an equity curve, drawdown, trade-return distribution, metrics cards
    (gross vs net), breakdown charts, the exit-reason/rejection funnel,
    execution assumptions (with a zero-cost warning when applicable),
    timezone/reproducibility metadata, the portfolio/survivorship
    disclaimers, and the full trade table. Every number in it comes
    straight from `result`/`data_quality`/`cost_sensitivity` -- if there
    are no trades, the report says so instead of rendering empty charts
    as if they meant something."""
    sets = metric_set(result.trades) if result.trades else {}
    meta = reproducibility.build_metadata(result.config, dataset_path=dataset_path, dataset_symbols=dataset_symbols)
    payload = {
        "meta": {
            "period_start": str(result.start), "period_end": str(result.end),
            "symbols": result.symbols, "bars_processed": result.bars_processed,
            "signals_generated": result.signals_generated,
            "signals_published": result.signals_published, "trades_executed": len(result.trades),
            "throttle_fidelity": result.config.throttle_fidelity,
        },
        "execution_assumptions": execution_assumptions_dict(result),
        "zero_cost_baseline_warning": is_zero_cost_run(result),
        "small_sample_warning": is_small_sample(len(result.trades)),
        "timezone": timezone_info_dict(input_timezone),
        "reproducibility": meta.to_dict(),
        "portfolio_disclaimer": PORTFOLIO_DISCLAIMER,
        "survivorship_bias_note": SURVIVORSHIP_BIAS_NOTE,
        "metrics": {label: metrics_to_dict(m) for label, m in sets.items()},
        "equity_curve": equity_curve_rows(result.trades),
        "breakdowns": _breakdown_payload(result.trades, "net_R") if result.trades else {},
        "exit_reasons": analysis.exit_reason_counts(result.trades) if result.trades else {},
        "rejections_by_reason": _rejection_counts(result),
        "trades": [t.to_dict() for t in result.trades],
        "data_quality": json.loads(data_quality_to_json(data_quality)),
        "time_of_day_order": list(analysis.TIME_OF_DAY_ORDER),
        "cost_sensitivity": cost_sensitivity or [],
    }
    # Escape "</" so an embedded string (e.g. a rejection reason) can
    # never prematurely close the <script> tag it's embedded in.
    payload_json = json.dumps(payload, default=str).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__PAYLOAD_JSON__", payload_json)


def write_report(
    result: BacktestResult,
    out_dir: str | Path,
    prefix: str = "backtest",
    data_quality: dict[str, DataQualityReport] | None = None,
    input_timezone: str | None = None,
    cost_sensitivity: list[dict] | None = None,
    dataset_path: str | Path | None = None,
    dataset_symbols: list[str] | None = None,
) -> dict[str, Path]:
    """Writes the full results/ set into `out_dir` (created if missing):
    trades.csv/json, summary.json/txt, equity_curve.csv,
    rejected_signals.csv, data_quality.json, and results.html. Returns
    the paths written. `data_quality` (from
    talonx_backtest.data.check_dataset_quality) is optional -- omit it
    and the data-quality section of the report is simply empty, not
    fabricated."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "trades_csv": out_dir / f"{prefix}_trades.csv",
        "trades_json": out_dir / f"{prefix}_trades.json",
        "summary_json": out_dir / f"{prefix}_summary.json",
        "summary_txt": out_dir / f"{prefix}_summary.txt",
        "equity_curve_csv": out_dir / f"{prefix}_equity_curve.csv",
        "rejected_signals_csv": out_dir / f"{prefix}_rejected_signals.csv",
        "data_quality_json": out_dir / f"{prefix}_data_quality.json",
        "results_html": out_dir / f"{prefix}_results.html",
    }
    if cost_sensitivity:
        paths["cost_sensitivity_csv"] = out_dir / f"{prefix}_cost_sensitivity.csv"

    # newline="" on every CSV write: csv.writer already emits its own
    # "\r\n" row terminators: without newline="", Path.write_text's
    # platform-default newline translation (on Windows) translates the
    # "\n" INSIDE that "\r\n" a second time, producing "\r\r\n" -- which
    # readers/splitlines() see as an extra blank line after every row.
    # JSON/HTML/plain-text writes are unaffected (no embedded "\r\n") and
    # keep the platform-default translation.
    paths["trades_csv"].write_text(trades_to_csv(result.trades), encoding="utf-8", newline="")
    paths["trades_json"].write_text(trades_to_json(result.trades), encoding="utf-8")
    paths["summary_json"].write_text(
        result_summary_json(
            result, input_timezone=input_timezone, cost_sensitivity=cost_sensitivity,
            dataset_path=dataset_path, dataset_symbols=dataset_symbols,
        ),
        encoding="utf-8",
    )
    paths["summary_txt"].write_text(
        result_summary_text(
            result, input_timezone=input_timezone, dataset_path=dataset_path, dataset_symbols=dataset_symbols,
        ),
        encoding="utf-8",
    )
    paths["equity_curve_csv"].write_text(equity_curve_to_csv(result.trades), encoding="utf-8", newline="")
    paths["rejected_signals_csv"].write_text(rejected_signals_to_csv(result.rejections), encoding="utf-8", newline="")
    paths["data_quality_json"].write_text(data_quality_to_json(data_quality), encoding="utf-8")
    paths["results_html"].write_text(
        build_html_report(
            result, data_quality, input_timezone=input_timezone, cost_sensitivity=cost_sensitivity,
            dataset_path=dataset_path, dataset_symbols=dataset_symbols,
        ),
        encoding="utf-8",
    )
    if cost_sensitivity:
        paths["cost_sensitivity_csv"].write_text(cost_sensitivity_to_csv(cost_sensitivity), encoding="utf-8", newline="")
    return paths


# ------------------------------------------------------------------
# Self-contained HTML report template. No CDN/external requests -- all
# CSS/JS inline, opens directly from disk. __PAYLOAD_JSON__ is replaced
# with one JSON blob (build_html_report, above); everything below is a
# pure renderer over that data, no separate data-fetching of its own.
# ------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TalonX Backtest Report</title>
<style>
  :root {
    --bg: #f7f7f8; --panel: #ffffff; --border: #e2e2e6; --text: #1b1c1f; --muted: #6b6f76;
    --accent: #2f6fed; --pos: #1a8f5c; --neg: #d1453b; --neutral: #9497a0;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #131417; --panel: #1c1d21; --border: #2c2d33; --text: #e8e9ec; --muted: #9497a0;
      --accent: #6d9bff; --pos: #35c281; --neg: #ff6a63; --neutral: #6b6f76; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font: 14px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 0 0 12px; color: var(--text); }
  .muted { color: var(--muted); }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
  .card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 20px; font-weight: 600; margin-top: 4px; }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .neutral { color: var(--neutral); }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th { cursor: pointer; color: var(--muted); font-weight: 600; user-select: none; }
  th:hover { color: var(--text); }
  .trade-table-wrap { max-height: 520px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
  .bar-row { display: grid; grid-template-columns: 110px 1fr 90px 60px; gap: 8px; align-items: center; padding: 4px 0; font-size: 12.5px; }
  .bar-track { background: var(--border); border-radius: 4px; height: 14px; position: relative; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; }
  .toggle-group { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin-bottom: 12px; }
  .toggle-group button { border: none; background: var(--panel); color: var(--text); padding: 6px 14px; cursor: pointer; font-size: 12.5px; }
  .toggle-group button.active { background: var(--accent); color: white; }
  .empty-note { color: var(--muted); font-style: italic; }
  svg text { fill: var(--muted); font-size: 10px; }
  .flex-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 800px) { .flex-cols { grid-template-columns: 1fr; } }
  .warning-banner { background: color-mix(in srgb, var(--neg) 15%, var(--panel)); border: 1px solid var(--neg);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; }
  .warning-banner .title { font-weight: 700; color: var(--neg); margin-bottom: 4px; }
  .warning-banner.info { background: color-mix(in srgb, var(--accent) 15%, var(--panel)); border-color: var(--accent); }
  .warning-banner.info .title { color: var(--accent); }
  .kv-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px 20px; font-size: 12.5px; }
  .kv-grid div span.k { color: var(--muted); display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
  .kv-grid div span.v { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .disclaimer { font-size: 12.5px; color: var(--muted); line-height: 1.6; }
</style>
</head>
<body>
<div class="panel">
  <h1>TalonX Backtest Report</h1>
  <div class="muted" id="meta-line"></div>
</div>

<div id="zero-cost-warning"></div>

<div class="panel" id="metrics-panel">
  <h2>Performance</h2>
  <div id="small-sample-warning"></div>
  <div class="toggle-group" id="metric-toggle"></div>
  <div class="grid" id="metric-cards"></div>
</div>

<div class="flex-cols">
  <div class="panel" id="equity-panel">
    <h2>Equity Curve (cumulative net R)</h2>
    <div id="equity-chart"></div>
  </div>
  <div class="panel" id="drawdown-panel">
    <h2>Drawdown (from running peak, net R)</h2>
    <div id="drawdown-chart"></div>
  </div>
</div>

<div class="panel" id="distribution-panel">
  <h2>Trade return distribution (net R)</h2>
  <div id="distribution-chart"></div>
</div>

<div class="flex-cols">
  <div class="panel"><h2>Exit reasons</h2><div id="exit-reasons"></div></div>
  <div class="panel"><h2>Rejection funnel (by gate)</h2><div id="rejections"></div></div>
</div>

<div class="panel" id="breakdowns-panel">
  <h2>Breakdowns (net R)</h2>
  <div id="breakdowns"></div>
</div>

<div class="panel" id="cost-sensitivity-panel">
  <h2>Cost sensitivity</h2>
  <div id="cost-sensitivity"></div>
</div>

<div class="panel">
  <h2>Execution assumptions</h2>
  <div class="kv-grid" id="execution-assumptions"></div>
</div>

<div class="panel">
  <h2>Timezone</h2>
  <div class="kv-grid" id="timezone-info"></div>
</div>

<div class="panel">
  <h2>Reproducibility</h2>
  <div class="kv-grid" id="reproducibility-info"></div>
</div>

<div class="panel">
  <h2>Data quality</h2>
  <div id="data-quality"></div>
</div>

<div class="panel">
  <h2>Research limitations</h2>
  <p class="disclaimer" id="portfolio-disclaimer"></p>
  <p class="disclaimer" id="survivorship-note"></p>
</div>

<div class="panel">
  <h2>Trades (<span id="trade-count"></span>)</h2>
  <p class="disclaimer">
    <strong>screening_rr</strong> = reward:risk at strategy screening/revalidation time (what the
    confluence/R:R gate actually approved). <strong>execution_rr</strong> = reward:risk using the
    real filled entry price against the same stop/target. These can legitimately differ -- the
    actual fill price is not always identical to the screening-time reference price.
  </p>
  <div class="trade-table-wrap"><table id="trade-table"><thead></thead><tbody></tbody></table></div>
</div>

<script type="application/json" id="payload">__PAYLOAD_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);

function fmt(x, digits) {
  if (x === null || x === undefined) return "n/a";
  if (typeof x !== "number" || !isFinite(x)) return String(x);
  return x.toFixed(digits === undefined ? 3 : digits);
}
function pct(x) { return x === null || x === undefined ? "n/a" : (x * 100).toFixed(1) + "%"; }
function signClass(x) { return x === null || x === undefined ? "neutral" : (x > 0 ? "pos" : (x < 0 ? "neg" : "neutral")); }

// ---- meta ----
document.getElementById("meta-line").textContent =
  `${DATA.meta.period_start} -> ${DATA.meta.period_end}  |  Symbols: ${DATA.meta.symbols.join(", ") || "none"}  |  ` +
  `Bars processed: ${DATA.meta.bars_processed}  |  Signals generated: ${DATA.meta.signals_generated}  |  ` +
  `Published: ${DATA.meta.signals_published}  |  Trades: ${DATA.meta.trades_executed}  |  ` +
  `Throttle fidelity: ${DATA.meta.throttle_fidelity}`;

// ---- zero-cost warning banner ----
if (DATA.zero_cost_baseline_warning) {
  const ea = DATA.execution_assumptions;
  document.getElementById("zero-cost-warning").innerHTML = `<div class="warning-banner">
    <div class="title">⚠ COST-FREE BASELINE</div>
    Slippage: ${ea.entry_slippage_bps}/${ea.exit_slippage_bps} bps (entry/exit) &nbsp; Spread: ${ea.spread_bps} bps<br>
    These results do NOT represent realistic execution costs. Do not call this "realistic performance" or
    "live expected return" -- run with <code>--cost-sensitivity</code> for a range of non-zero cost assumptions.
  </div>`;
}

// ---- small-sample statistical warning ----
// DATA.small_sample_warning is precomputed in Python (reports.is_small_sample,
// same "compute the boolean server-side, JS just renders it" pattern as
// zero_cost_baseline_warning above) -- Sharpe/Sortino/confidence
// intervals all lean on a normal-approximation/CLT assumption that
// simply isn't trustworthy yet at a handful of trades. This does NOT
// hide the numbers (spec: "keep the statistics") -- it just makes sure
// nobody reads them as settled evidence.
if (DATA.small_sample_warning) {
  const n = DATA.meta.trades_executed;
  document.getElementById("small-sample-warning").innerHTML = `<div class="warning-banner info">
    <div class="title">⚠ SMALL SAMPLE (${n} trade${n === 1 ? "" : "s"})</div>
    Sharpe, Sortino, and confidence intervals below rely on a normal-approximation assumption that is NOT
    reliable at this trade count -- treat them as illustrative only, not statistically meaningful evidence.
    Win rate, profit factor, and expectancy are still exact arithmetic over the trades that occurred, but a
    small sample means they may not be representative of the strategy's true long-run behavior either.
    Numbers are shown as computed, not hidden or adjusted -- read them with that caveat in mind.
  </div>`;
}

// ---- execution assumptions / timezone / reproducibility (plain key-value panels) ----
function renderKvGrid(elId, obj, formatters) {
  const el = document.getElementById(elId);
  el.innerHTML = Object.entries(obj).map(([k, v]) => {
    const display = (formatters && formatters[k]) ? formatters[k](v) : String(v);
    return `<div><span class="k">${k.replace(/_/g, " ")}</span><span class="v">${display}</span></div>`;
  }).join("");
}
renderKvGrid("execution-assumptions", DATA.execution_assumptions, {
  entry_slippage_bps: v => `${v} bps`, exit_slippage_bps: v => `${v} bps`, spread_bps: v => `${v} bps`,
  same_bar_resolution: v => String(v).toUpperCase(),
  eod_flatten_enabled: v => v ? "ENABLED" : "DISABLED",
  allow_overlapping_trades: v => v ? "yes" : "no",
});
renderKvGrid("timezone-info", DATA.timezone);
renderKvGrid("reproducibility-info", DATA.reproducibility);

document.getElementById("portfolio-disclaimer").textContent = DATA.portfolio_disclaimer;
document.getElementById("survivorship-note").textContent = DATA.survivorship_bias_note;

// ---- metric cards (gross/net toggle) ----
const metricFields = [
  ["total_trades", "Trades", 0], ["win_rate", "Win rate", "pct"], ["profit_factor", "Profit factor", 2],
  ["expectancy_r", "Expectancy (R)", 3], ["total_r", "Total R", 2], ["max_drawdown_r", "Max drawdown (R)", 2],
  ["average_r", "Average R", 3], ["median_r", "Median R", 3], ["best_trade_r", "Best trade (R)", 2],
  ["worst_trade_r", "Worst trade (R)", 2], ["average_mfe_r", "Avg MFE (R)", 2], ["average_mae_r", "Avg MAE (R)", 2],
  ["winners_average_mfe_r", "Winners avg MFE (R)", 2], ["losers_average_mae_r", "Losers avg MAE (R)", 2],
  ["sharpe_per_trade", "Sharpe (per-trade)", 2], ["sortino_per_trade", "Sortino (per-trade)", 2],
];
const toggle = document.getElementById("metric-toggle");
const cardsEl = document.getElementById("metric-cards");
const labels = Object.keys(DATA.metrics);
function renderMetrics(label) {
  const m = DATA.metrics[label];
  cardsEl.innerHTML = "";
  if (!m) { cardsEl.innerHTML = '<div class="empty-note">No trades were executed.</div>'; return; }
  for (const [key, title, digits] of metricFields) {
    const val = m[key];
    const display = digits === "pct" ? pct(val) : fmt(val, digits);
    const cls = key.includes("_r") || key === "profit_factor" || key.includes("R") ? signClass(val) : "";
    cardsEl.insertAdjacentHTML("beforeend",
      `<div class="card"><div class="label">${title}</div><div class="value ${cls}">${display}</div></div>`);
  }
}
if (labels.length) {
  for (const label of labels) {
    const btn = document.createElement("button");
    btn.textContent = label.toUpperCase() + (label === "gross" ? " (before costs)" : " (after costs)");
    btn.onclick = () => { renderMetrics(label); [...toggle.children].forEach(b => b.classList.remove("active")); btn.classList.add("active"); };
    toggle.appendChild(btn);
  }
  toggle.children[labels.indexOf("net") >= 0 ? labels.indexOf("net") : 0].classList.add("active");
  renderMetrics(labels.indexOf("net") >= 0 ? "net" : labels[0]);
} else {
  document.getElementById("metrics-panel").insertAdjacentHTML("beforeend",
    '<div class="empty-note">No trades were executed -- see the rejection funnel below for why.</div>');
}

// ---- equity curve (plain SVG polyline, no library) ----
(function renderEquityCurve() {
  const el = document.getElementById("equity-chart");
  const points = DATA.equity_curve;
  if (!points.length) { el.innerHTML = '<div class="empty-note">No closed trades to chart.</div>'; return; }
  const w = 900, h = 220, padL = 40, padB = 20, padT = 10, padR = 10;
  const ys = points.map(p => p.cumulative_net_R);
  const minY = Math.min(0, ...ys), maxY = Math.max(0, ...ys);
  const range = (maxY - minY) || 1;
  const x = i => padL + (i / Math.max(points.length - 1, 1)) * (w - padL - padR);
  const y = v => padT + (1 - (v - minY) / range) * (h - padT - padB);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.cumulative_net_R).toFixed(1)}`).join(" ");
  const zeroY = y(0).toFixed(1);
  const last = points[points.length - 1];
  const lineColor = last.cumulative_net_R >= 0 ? "var(--pos)" : "var(--neg)";
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
    <line x1="${padL}" y1="${zeroY}" x2="${w - padR}" y2="${zeroY}" stroke="var(--border)" stroke-dasharray="3,3"/>
    <text x="${padL - 6}" y="${padT + 4}" text-anchor="end">${maxY.toFixed(1)}R</text>
    <text x="${padL - 6}" y="${h - padB}" text-anchor="end">${minY.toFixed(1)}R</text>
    <path d="${path}" fill="none" stroke="${lineColor}" stroke-width="2"/>
  </svg>
  <div class="muted">${points.length} trade(s) -- final cumulative net R: <b class="${signClass(last.cumulative_net_R)}">${fmt(last.cumulative_net_R, 2)}</b></div>`;
})();

// ---- drawdown (running peak minus cumulative net R -- derived from the
// SAME equity_curve data the chart above uses, not a separate series) ----
(function renderDrawdown() {
  const el = document.getElementById("drawdown-chart");
  const points = DATA.equity_curve;
  if (!points.length) { el.innerHTML = '<div class="empty-note">No closed trades to chart.</div>'; return; }
  let peak = 0;
  const dd = points.map(p => { peak = Math.max(peak, p.cumulative_net_R); return peak - p.cumulative_net_R; });
  const maxDd = Math.max(...dd, 0.001);
  const w = 900, h = 220, padL = 40, padB = 20, padT = 10, padR = 10;
  const x = i => padL + (i / Math.max(points.length - 1, 1)) * (w - padL - padR);
  const y = v => padT + (v / maxDd) * (h - padT - padB);
  const path = "M" + dd.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" L");
  const areaPath = path + ` L${x(dd.length - 1).toFixed(1)},${padT} L${x(0).toFixed(1)},${padT} Z`;
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
    <text x="${padL - 6}" y="${padT + 4}" text-anchor="end">-${maxDd.toFixed(1)}R</text>
    <text x="${padL - 6}" y="${h - padB}" text-anchor="end">0R</text>
    <path d="${areaPath}" fill="var(--neg)" fill-opacity="0.15" stroke="none"/>
    <path d="${path}" fill="none" stroke="var(--neg)" stroke-width="2"/>
  </svg>
  <div class="muted">Max drawdown: <b class="neg">-${maxDd.toFixed(2)}R</b></div>`;
})();

// ---- trade return distribution (histogram of net R) ----
(function renderDistribution() {
  const el = document.getElementById("distribution-chart");
  const values = DATA.trades.map(t => t.net_R).filter(v => v !== null && v !== undefined);
  if (!values.length) { el.innerHTML = '<div class="empty-note">No closed trades to chart.</div>'; return; }
  const min = Math.min(...values), max = Math.max(...values);
  const bucketCount = Math.min(12, Math.max(4, Math.ceil(Math.sqrt(values.length))));
  const span = (max - min) || 1;
  const bucketWidth = span / bucketCount;
  const buckets = new Array(bucketCount).fill(0);
  for (const v of values) {
    let idx = Math.floor((v - min) / bucketWidth);
    if (idx >= bucketCount) idx = bucketCount - 1;
    if (idx < 0) idx = 0;
    buckets[idx]++;
  }
  const maxCount = Math.max(...buckets, 1);
  let html = '<div style="display:flex;align-items:flex-end;gap:3px;height:140px">';
  for (let i = 0; i < bucketCount; i++) {
    const bucketStart = min + i * bucketWidth;
    const heightPct = (buckets[i] / maxCount) * 100;
    const color = (bucketStart + bucketWidth / 2) >= 0 ? "var(--pos)" : "var(--neg)";
    html += `<div title="${bucketStart.toFixed(2)}R to ${(bucketStart + bucketWidth).toFixed(2)}R: ${buckets[i]} trade(s)"
      style="flex:1;height:${Math.max(heightPct, 2)}%;background:${color};border-radius:2px 2px 0 0"></div>`;
  }
  html += "</div>";
  html += `<div class="muted" style="display:flex;justify-content:space-between;margin-top:4px">
    <span>${min.toFixed(2)}R</span><span>${max.toFixed(2)}R</span></div>`;
  el.innerHTML = html;
})();

// ---- cost sensitivity (spec section 10 -- sensitivity only, no "best" highlighted) ----
(function renderCostSensitivity() {
  const el = document.getElementById("cost-sensitivity");
  const rows = DATA.cost_sensitivity;
  if (!rows || !rows.length) {
    el.innerHTML = '<div class="empty-note">Not run for this backtest -- pass --cost-sensitivity to generate this table.</div>';
    return;
  }
  const body = rows.map(r => `<tr>
    <td>${r.cost_bps}</td><td>${r.trades}</td><td>${pct(r.win_rate)}</td>
    <td>${fmt(r.profit_factor, 2)}</td><td class="${signClass(r.expectancy_r)}">${fmt(r.expectancy_r, 3)}</td>
    <td class="${signClass(r.max_drawdown_r)}">${fmt(r.max_drawdown_r, 2)}</td></tr>`).join("");
  el.innerHTML = `<table><thead><tr><th>Cost (bps)</th><th>Trades</th><th>Win rate</th>
    <th>Profit factor</th><th>Expectancy (R)</th><th>Max DD (R)</th></tr></thead><tbody>${body}</tbody></table>
    <div class="muted" style="margin-top:6px">Sensitivity analysis only -- no scenario above is selected or recommended.</div>`;
})();

// ---- exit reasons / rejections ----
function renderCountTable(el, obj, colLabel) {
  const entries = Object.entries(obj || {});
  if (!entries.length) { el.innerHTML = '<div class="empty-note">None.</div>'; return; }
  const total = entries.reduce((a, [, v]) => a + v, 0);
  let rows = entries.sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<tr><td>${k}</td><td>${v}</td><td class="muted">${(100 * v / total).toFixed(1)}%</td></tr>`).join("");
  el.innerHTML = `<table><thead><tr><th>${colLabel}</th><th>Count</th><th>%</th></tr></thead><tbody>${rows}</tbody></table>`;
}
renderCountTable(document.getElementById("exit-reasons"), DATA.exit_reasons, "Reason");
renderCountTable(document.getElementById("rejections"), DATA.rejections_by_reason, "Gate");

// ---- breakdowns ----
(function renderBreakdowns() {
  const el = document.getElementById("breakdowns");
  const groups = Object.entries(DATA.breakdowns || {});
  if (!groups.length) { el.innerHTML = '<div class="empty-note">No trades to break down.</div>'; return; }
  let html = "";
  for (const [groupName, buckets] of groups) {
    let bucketEntries = Object.entries(buckets);
    if (groupName === "by_time_of_day") {
      const order = DATA.time_of_day_order;
      bucketEntries.sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
    }
    if (!bucketEntries.length) continue;
    const maxAbsExp = Math.max(...bucketEntries.map(([, m]) => Math.abs(m.expectancy_r || 0)), 0.001);
    html += `<h2 style="margin-top:16px">${groupName.replace(/^by_/, "").replace(/_/g, " ")}</h2>`;
    for (const [bucket, m] of bucketEntries) {
      const widthPct = Math.min(100, Math.abs(m.expectancy_r || 0) / maxAbsExp * 100);
      const cls = signClass(m.expectancy_r);
      const color = cls === "pos" ? "var(--pos)" : (cls === "neg" ? "var(--neg)" : "var(--neutral)");
      html += `<div class="bar-row">
        <div>${bucket}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${widthPct}%;background:${color}"></div></div>
        <div class="${cls}">${fmt(m.expectancy_r, 3)}R</div>
        <div class="muted">n=${m.trades}</div>
      </div>`;
    }
  }
  el.innerHTML = html || '<div class="empty-note">No trades to break down.</div>';
})();

// ---- data quality ----
(function renderDataQuality() {
  const el = document.getElementById("data-quality");
  const entries = Object.entries(DATA.data_quality || {});
  if (!entries.length) { el.innerHTML = '<div class="empty-note">No data-quality report was supplied for this run.</div>'; return; }
  let rows = entries.map(([symbol, r]) => `<tr>
    <td>${symbol}</td><td>${r.rows}</td><td>${r.duplicate_timestamps}</td><td>${r.out_of_order_timestamps}</td>
    <td>${r.missing_bars}</td><td>${r.invalid_prices}</td><td>${r.invalid_ohlc_relationship}</td>
    <td>${r.negative_volume}</td><td>${r.nan_values}</td><td>${r.infinite_values}</td>
    <td>${r.is_clean ? "yes" : "no"}</td></tr>`).join("");
  el.innerHTML = `<table><thead><tr><th>Symbol</th><th>Rows</th><th>Dup ts</th><th>Out-of-order</th>
    <th>Missing bars</th><th>Invalid px</th><th>Bad OHLC</th><th>Neg vol</th><th>NaN</th><th>Inf</th><th>Clean</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
})();

// ---- trade table (sortable) ----
(function renderTradeTable() {
  const trades = DATA.trades;
  document.getElementById("trade-count").textContent = trades.length;
  if (!trades.length) {
    document.querySelector(".trade-table-wrap").innerHTML = '<div class="empty-note" style="padding:12px">No trades were executed.</div>';
    return;
  }
  const cols = ["symbol", "direction", "signal_type", "session", "entry_timestamp", "entry_price", "stop_price",
    "target_price", "exit_timestamp", "exit_price", "exit_reason", "gross_R", "net_R", "holding_seconds",
    "confluence_score", "screening_rr", "execution_rr", "volume_surge_ratio", "trend_alignment", "mfe_r", "mae_r"];
  const thead = document.querySelector("#trade-table thead");
  const tbody = document.querySelector("#trade-table tbody");
  thead.innerHTML = "<tr>" + cols.map(c => `<th data-col="${c}">${c}</th>`).join("") + "</tr>";

  let sortCol = "exit_timestamp", sortAsc = false;
  function render() {
    const rows = [...trades].sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol];
      if (av === null || av === undefined) av = -Infinity;
      if (bv === null || bv === undefined) bv = -Infinity;
      if (typeof av === "string") return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
      return sortAsc ? av - bv : bv - av;
    });
    tbody.innerHTML = rows.map(t => "<tr>" + cols.map(c => {
      const v = t[c];
      const cls = (c === "gross_R" || c === "net_R" || c === "mfe_r" || c === "mae_r") ? signClass(v) : "";
      return `<td class="${cls}">${v === null || v === undefined ? "" : (typeof v === "number" ? fmt(v, 3) : v)}</td>`;
    }).join("") + "</tr>").join("");
  }
  thead.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
    const col = th.dataset.col;
    if (col === sortCol) sortAsc = !sortAsc; else { sortCol = col; sortAsc = false; }
    render();
  }));
  render();
})();
</script>
</body>
</html>
"""
