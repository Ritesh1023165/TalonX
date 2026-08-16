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
from dataclasses import asdict
from io import StringIO
from pathlib import Path

from talonx_backtest import analysis
from talonx_backtest.data import DataQualityReport
from talonx_backtest.engine import BacktestResult, RejectionRecord
from talonx_backtest.metrics import PerformanceMetrics, metric_set
from talonx_backtest.portfolio import Trade


def trades_to_csv(trades: list[Trade]) -> str:
    if not trades:
        return ""
    buf = StringIO()
    fieldnames = list(trades[0].to_dict().keys())
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


def result_summary_text(result: BacktestResult) -> str:
    lines = [
        "Backtest Summary",
        "----------------",
        "",
        f"Period:               {result.start} -> {result.end}",
        f"Symbols:              {', '.join(result.symbols)}",
        f"Signals generated:    {result.signals_generated}",
        f"Signals published:    {result.signals_published}",
        f"Trades executed:      {len(result.trades)}",
        f"Throttle fidelity:    {result.config.throttle_fidelity}",
        "",
    ]

    if not result.trades:
        lines.append("No trades were executed -- see `rejections` for the gate funnel (no fabricated metrics below).")
        return "\n".join(lines)

    sets = metric_set(result.trades)
    for label in ("gross", "net"):
        lines.append(f"--- {label.upper()} (before costs)" if label == "gross" else f"--- {label.upper()} (after slippage/spread)")
        lines.extend(sets[label].summary_lines())
        lines.append("")

    return "\n".join(lines)


def result_summary_json(result: BacktestResult) -> str:
    sets = metric_set(result.trades) if result.trades else {}
    payload = {
        "period": {"start": str(result.start), "end": str(result.end)},
        "symbols": result.symbols,
        "signals_generated": result.signals_generated,
        "signals_published": result.signals_published,
        "trades_executed": len(result.trades),
        "throttle_fidelity": result.config.throttle_fidelity,
        "metrics": {label: metrics_to_dict(m) for label, m in sets.items()},
        "rejections_by_reason": _rejection_counts(result),
    }
    return json.dumps(payload, indent=2, default=str)


def _rejection_counts(result: BacktestResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in result.rejections:
        counts[r.reason] = counts.get(r.reason, 0) + r.count
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


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
    rows = equity_curve_rows(trades)
    if not rows:
        return ""
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
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
) -> str:
    """A single, self-contained HTML file (no external requests, no CDN,
    inline CSS/JS only -- opens directly from disk in any browser) with
    an equity curve, metrics cards (gross vs net), breakdown charts, the
    exit-reason/rejection funnel, and the full trade table. Every number
    in it comes straight from `result`/`data_quality` -- if there are no
    trades, the report says so instead of rendering empty charts as if
    they meant something."""
    sets = metric_set(result.trades) if result.trades else {}
    payload = {
        "meta": {
            "period_start": str(result.start), "period_end": str(result.end),
            "symbols": result.symbols, "signals_generated": result.signals_generated,
            "signals_published": result.signals_published, "trades_executed": len(result.trades),
            "throttle_fidelity": result.config.throttle_fidelity,
        },
        "metrics": {label: metrics_to_dict(m) for label, m in sets.items()},
        "equity_curve": equity_curve_rows(result.trades),
        "breakdowns": _breakdown_payload(result.trades, "net_R") if result.trades else {},
        "exit_reasons": analysis.exit_reason_counts(result.trades) if result.trades else {},
        "rejections_by_reason": _rejection_counts(result),
        "trades": [t.to_dict() for t in result.trades],
        "data_quality": json.loads(data_quality_to_json(data_quality)),
        "time_of_day_order": list(analysis.TIME_OF_DAY_ORDER),
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
    paths["trades_csv"].write_text(trades_to_csv(result.trades), encoding="utf-8")
    paths["trades_json"].write_text(trades_to_json(result.trades), encoding="utf-8")
    paths["summary_json"].write_text(result_summary_json(result), encoding="utf-8")
    paths["summary_txt"].write_text(result_summary_text(result), encoding="utf-8")
    paths["equity_curve_csv"].write_text(equity_curve_to_csv(result.trades), encoding="utf-8")
    paths["rejected_signals_csv"].write_text(rejected_signals_to_csv(result.rejections), encoding="utf-8")
    paths["data_quality_json"].write_text(data_quality_to_json(data_quality), encoding="utf-8")
    paths["results_html"].write_text(build_html_report(result, data_quality), encoding="utf-8")
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
</style>
</head>
<body>
<div class="panel">
  <h1>TalonX Backtest Report</h1>
  <div class="muted" id="meta-line"></div>
</div>

<div class="panel" id="metrics-panel">
  <h2>Performance</h2>
  <div class="toggle-group" id="metric-toggle"></div>
  <div class="grid" id="metric-cards"></div>
</div>

<div class="panel" id="equity-panel">
  <h2>Equity Curve (cumulative net R)</h2>
  <div id="equity-chart"></div>
</div>

<div class="flex-cols">
  <div class="panel"><h2>Exit reasons</h2><div id="exit-reasons"></div></div>
  <div class="panel"><h2>Rejection funnel (by gate)</h2><div id="rejections"></div></div>
</div>

<div class="panel" id="breakdowns-panel">
  <h2>Breakdowns (net R)</h2>
  <div id="breakdowns"></div>
</div>

<div class="panel">
  <h2>Data quality</h2>
  <div id="data-quality"></div>
</div>

<div class="panel">
  <h2>Trades (<span id="trade-count"></span>)</h2>
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
  `Signals generated: ${DATA.meta.signals_generated}  |  Published: ${DATA.meta.signals_published}  |  ` +
  `Trades: ${DATA.meta.trades_executed}  |  Throttle fidelity: ${DATA.meta.throttle_fidelity}`;

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
    "confluence_score", "risk_reward_ratio", "volume_surge_ratio", "trend_alignment", "mfe_r", "mae_r"];
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
