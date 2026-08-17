"""
generate_eod_report.py
-----------------------
Standalone script: reads each module's own SQLite store for a given
calendar day (local to --tz, default America/New_York) and writes a
consolidated End-of-Day report -- Markdown + raw CSVs -- so "what
happened today, and why" is answerable after market close without
manually cross-referencing dashboard tables or asking for an ad-hoc
analysis (see today's GOOGL/IBM/MSTR/MSFT paper-trading question, which
is exactly the case the per-ticker section below is built to answer).

Follows the same convention run_talonx.py / talonx_dispatch/app.py use:
import each module's own Config + Store pair directly rather than
touching sqlite3/paths by hand, so this script never has to guess where
a database file lives.

talonx_paper's executed/ignored trade ledger -- alerts, executed trades,
ignored trades (with reason), and portfolio summary.

Phase 2: talonx_core/talonx_quant/talonx_brain's own local stats stores
(suppression_counts / report_counts) extend this with a signal funnel
(quant signals generated -> suppressed by quant -> reached core ->
suppressed by core -> became an alert) and LLM/cache economics
(cache_hit/stale_fallback/degraded/cold_start/llm_call counts). These
three stores bucket by UTC calendar date, not the local trading day
Phase 1 uses -- in practice this never matters, since quant/core/brain
only ever produce events during market hours, which never straddles a
UTC midnight boundary for any timezone this script would realistically
be run with; documented here rather than reconciled with a second
date-range query.

Every Phase 2 store is optional -- a fresh install that predates this
feature (or one running with persistence disabled) simply shows no data
for that section rather than erroring, so this script never fails just
because one module's stats store isn't there yet.

Run: python generate_eod_report.py [--date YYYY-MM-DD] [--tz America/New_York] [--out-dir reports]
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from talonx_brain.config import BrainConfig
from talonx_brain.store import BrainStatsStore
from talonx_core.config import CoreConfig
from talonx_core.store import TickerStateStore
from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_paper.config import PaperConfig
from talonx_paper.store import PaperTradingStore
from talonx_quant.config import QuantConfig
from talonx_quant.store import QuantStateStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logger = logging.getLogger("generate_eod_report")

DEFAULT_TZ = "America/New_York"


@dataclass
class ValuationSnapshot:
    """Phase 2's per-ticker "where does this stand right now" snapshot for
    the Valuation & Margin of Safety Radar section -- built from
    AuditStore's long_term_alerts table (already the exact denormalized
    shape needed: quality/moat/price/fair-value all on one row) rather
    than re-deriving it from talonx_core's ticker_state_long_term, whose
    report_json/signal_json blobs would need deserializing just to get
    back to the same numbers. Same "latest row per ticker" idea as the
    dashboard's render_valuation_radar (talonx_dispatch/app.py) -- this
    is that same radar, as a point-in-time snapshot for the day's report."""
    ticker: str
    action: str
    current_price: float
    fair_value: float
    margin_of_safety_pct: float
    quality_score: int
    moat_rating: str
    last_updated: str


@dataclass
class TickerSection:
    ticker: str
    paper_trading_enabled: bool
    alert_counts: dict[str, int] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    ignored_counts: dict[str, int] = field(default_factory=dict)
    verdict: str = ""
    quant_suppressed: dict[str, int] = field(default_factory=dict)
    core_suppressed: dict[str, int] = field(default_factory=dict)
    brain_categories: dict[str, int] = field(default_factory=dict)


@dataclass
class EODReport:
    date: str
    tz: str
    generated_at: datetime
    tickers_monitored: list[str]
    tickers_paper_enabled: list[str]
    total_alerts: int
    total_trades_executed: int
    total_trades_ignored: int
    telegram_sent: int
    telegram_failed: int
    portfolio_summary: dict
    ticker_sections: list[TickerSection]
    alerts: list[dict]
    phase2_available: bool = False
    valuation_snapshots: list[ValuationSnapshot] = field(default_factory=list)
    long_term_portfolio_summary: dict = field(default_factory=dict)


def _day_bounds(date_str: str, tz_name: str) -> tuple[datetime, datetime]:
    """[start, end) for the given calendar day, expressed as UTC-aware
    datetimes -- the stores compare against UTC ISO strings, so the local
    trading-day boundary has to be converted before it's usable in a
    WHERE clause."""
    tz = ZoneInfo(tz_name)
    start_local = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))


def _build_verdict(
    enabled: bool, alerts: list[dict], trades: list[dict], ignored: list[dict],
) -> str:
    if not enabled:
        return "Paper trading not enabled for this ticker."
    if not alerts:
        return "No alerts today."
    if trades:
        buys = sum(1 for t in trades if t["order_type"] == "BUY")
        sells = sum(1 for t in trades if t["order_type"] == "SELL")
        pnl = sum(t.get("realized_pnl_usd") or 0.0 for t in trades)
        return f"{buys} BUY / {sells} SELL executed today; realized PnL ${pnl:+.2f}."
    if ignored:
        reason_str = ", ".join(f"{r} x{c}" for r, c in Counter(i["reason"] for i in ignored).most_common())
        action_str = ", ".join(f"{a} x{c}" for a, c in Counter(a["action"] for a in alerts).most_common())
        return f"No trade today -- {len(alerts)} alert(s) ({action_str}), all ignored: {reason_str}."
    return f"{len(alerts)} alert(s) today, no trade and nothing recorded as ignored (check logs)."


def _group_counts(rows: list[dict], reason_key: str) -> dict[str, dict[str, int]]:
    """rows shaped like suppression_counts_for_date()/report_counts_for_date()
    output -> {ticker: {reason_or_category: count}}."""
    grouped: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        grouped[row["ticker"]][row[reason_key]] = row["count"]
    return grouped


def _build_valuation_snapshots(audit_store: AuditStore) -> list[ValuationSnapshot]:
    """Latest long-term alert per ticker, regardless of report day --
    unlike the intraday alert log, fundamentals-driven evaluations happen
    on the order of quarters, so restricting this to just today's alerts
    would show nothing on most days. A "where things stand now" snapshot
    is what the Radar name promises, not "what changed today"."""
    rows = audit_store.recent_long_term(limit=1000)
    latest_per_ticker: dict[str, dict] = {}
    for row in rows:  # DESC by correlated_at/id -- first occurrence per ticker is the latest
        latest_per_ticker.setdefault(row["ticker"], row)

    return [
        ValuationSnapshot(
            ticker=row["ticker"],
            action=row["action"],
            current_price=row["market_price"],
            fair_value=row["intrinsic_fair_value"],
            margin_of_safety_pct=row["margin_of_safety_pct"],
            quality_score=row["quality_score"],
            moat_rating=row["moat_rating"],
            last_updated=row["correlated_at"],
        )
        for row in sorted(latest_per_ticker.values(), key=lambda r: r["ticker"])
    ]


def _build_long_term_portfolio_summary(paper_store: PaperTradingStore) -> dict:
    """Cash/realized-PnL summary plus unrealized PnL/total-contributed
    computed from the open long-term positions -- same shape the
    dashboard's render_long_term_portfolio derives, added here rather
    than inside PaperTradingStore since it's purely a display rollup, not
    ledger state."""
    summary = dict(paper_store.get_long_term_portfolio_summary())
    open_positions = paper_store.get_open_long_term_positions()
    latest_prices = paper_store.get_latest_prices()

    total_contributed = 0.0
    unrealized_pnl = 0.0
    for pos in open_positions:
        total_contributed += pos["total_contributed_usd"]
        live_price = latest_prices.get(pos["ticker"], pos["avg_cost_basis"])
        unrealized_pnl += pos["total_shares"] * (live_price - pos["avg_cost_basis"])

    summary["total_contributed_usd"] = total_contributed
    summary["unrealized_pnl_usd"] = unrealized_pnl
    return summary


def build_report(
    date_str: str,
    audit_store: AuditStore,
    paper_store: PaperTradingStore,
    watchlist_store: TickerWatchlistStore,
    tz_name: str = DEFAULT_TZ,
    core_store: TickerStateStore | None = None,
    quant_store: QuantStateStore | None = None,
    brain_store: BrainStatsStore | None = None,
) -> EODReport:
    start, end = _day_bounds(date_str, tz_name)

    alerts = audit_store.alerts_between(start, end)
    trades = paper_store.get_trade_history_between(start, end)
    ignored = paper_store.get_ignored_decisions_between(start, end)
    portfolio_summary = paper_store.get_portfolio_summary()

    tickers = watchlist_store.list_tickers()
    paper_enabled = set(watchlist_store.list_paper_trading_symbols())

    alerts_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in alerts:
        alerts_by_ticker[row["ticker"]].append(row)
    trades_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in trades:
        trades_by_ticker[row["ticker"]].append(row)
    ignored_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in ignored:
        ignored_by_ticker[row["ticker"]].append(row)

    # Phase 2: bucketed by UTC calendar date -- see the module docstring
    # for why date_str is used as-is rather than reconciled against the
    # local trading-day window Phase 1 uses.
    quant_suppressed_by_ticker = _group_counts(
        quant_store.suppression_counts_for_date(date_str) if quant_store else [], "reason"
    )
    core_suppressed_by_ticker = _group_counts(
        core_store.suppression_counts_for_date(date_str) if core_store else [], "reason"
    )
    brain_categories_by_ticker = _group_counts(
        brain_store.report_counts_for_date(date_str) if brain_store else [], "category"
    )
    phase2_available = any((quant_store, core_store, brain_store))

    all_symbols = sorted(
        {t["symbol"] for t in tickers}
        | set(alerts_by_ticker) | set(trades_by_ticker) | set(ignored_by_ticker)
        | set(quant_suppressed_by_ticker) | set(core_suppressed_by_ticker) | set(brain_categories_by_ticker)
    )

    sections = []
    for symbol in all_symbols:
        t_alerts = alerts_by_ticker.get(symbol, [])
        t_trades = trades_by_ticker.get(symbol, [])
        t_ignored = ignored_by_ticker.get(symbol, [])
        enabled = symbol in paper_enabled
        sections.append(
            TickerSection(
                ticker=symbol,
                paper_trading_enabled=enabled,
                alert_counts=dict(Counter(a["action"] for a in t_alerts)),
                trades=t_trades,
                ignored_counts=dict(Counter(i["reason"] for i in t_ignored)),
                verdict=_build_verdict(enabled, t_alerts, t_trades, t_ignored),
                quant_suppressed=quant_suppressed_by_ticker.get(symbol, {}),
                core_suppressed=core_suppressed_by_ticker.get(symbol, {}),
                brain_categories=brain_categories_by_ticker.get(symbol, {}),
            )
        )

    return EODReport(
        date=date_str,
        tz=tz_name,
        generated_at=datetime.now(ZoneInfo("UTC")),
        tickers_monitored=[t["symbol"] for t in tickers],
        tickers_paper_enabled=sorted(paper_enabled),
        total_alerts=len(alerts),
        total_trades_executed=len(trades),
        total_trades_ignored=len(ignored),
        telegram_sent=sum(1 for a in alerts if a.get("telegram_sent")),
        telegram_failed=sum(1 for a in alerts if a.get("telegram_error")),
        portfolio_summary=portfolio_summary,
        ticker_sections=sections,
        alerts=alerts,
        phase2_available=phase2_available,
        valuation_snapshots=_build_valuation_snapshots(audit_store),
        long_term_portfolio_summary=_build_long_term_portfolio_summary(paper_store),
    )


def render_markdown(report: EODReport) -> str:
    lines = [
        f"# TalonX End-of-Day Report -- {report.date} ({report.tz})",
        f"_Generated {report.generated_at.isoformat()}_",
        "",
        "## Executive summary",
        "",
        f"- Tickers monitored: {len(report.tickers_monitored)} ({', '.join(report.tickers_monitored) or 'none'})",
        f"- Paper trading enabled: {len(report.tickers_paper_enabled)} ({', '.join(report.tickers_paper_enabled) or 'none'})",
        f"- Alerts today: {report.total_alerts}",
        f"- Trades executed: {report.total_trades_executed}",
        f"- Trades ignored: {report.total_trades_ignored}",
        f"- Telegram: {report.telegram_sent} sent, {report.telegram_failed} failed",
        "",
        "## Portfolio summary",
        "",
        f"- Cash: ${report.portfolio_summary.get('current_cash', 0):,.2f}",
        f"- Open positions: {report.portfolio_summary.get('open_positions_count', 0)}",
        f"- Total realized PnL: ${report.portfolio_summary.get('total_realized_pnl_usd', 0):,.2f} "
        f"({report.portfolio_summary.get('total_realized_pnl_pct', 0):+.2f}%)",
        f"- Win rate: {report.portfolio_summary.get('win_rate_pct', 0):.1f}% "
        f"({report.portfolio_summary.get('win_count', 0)}W / {report.portfolio_summary.get('loss_count', 0)}L)",
        "",
        "## Long-Term Portfolio summary",
        "",
        f"- Cash: ${report.long_term_portfolio_summary.get('current_cash', 0):,.2f}",
        f"- Open positions: {report.long_term_portfolio_summary.get('open_positions_count', 0)}",
        f"- Total DCA contributed: ${report.long_term_portfolio_summary.get('total_contributed_usd', 0):,.2f}",
        f"- Unrealized PnL (open positions): ${report.long_term_portfolio_summary.get('unrealized_pnl_usd', 0):,.2f}",
        f"- Total realized PnL: ${report.long_term_portfolio_summary.get('total_realized_pnl_usd', 0):,.2f} "
        f"({report.long_term_portfolio_summary.get('total_realized_pnl_pct', 0):+.2f}%)",
        f"- Win rate: {report.long_term_portfolio_summary.get('win_rate_pct', 0):.1f}% "
        f"({report.long_term_portfolio_summary.get('win_count', 0)}W / "
        f"{report.long_term_portfolio_summary.get('loss_count', 0)}L)",
        "",
        "## Valuation & Margin of Safety Radar",
        "",
    ]

    if report.valuation_snapshots:
        lines.append(
            "| Ticker | Action | Price | Fair Value | Margin of Safety | Quality | Moat | Last evaluated |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for snap in report.valuation_snapshots:
            lines.append(
                f"| {snap.ticker} | {snap.action.replace('_', ' ').title()} | "
                f"${snap.current_price:,.2f} | ${snap.fair_value:,.2f} | "
                f"{snap.margin_of_safety_pct:+.1%} | {snap.quality_score}/10 | "
                f"{snap.moat_rating.title()} | {snap.last_updated} |"
            )
    else:
        lines.append(
            "_No long-term alerts yet -- tag a ticker LONG_TERM in the watchlist and "
            "wait for a fundamental signal to clear the threshold and produce a report._"
        )
    lines.append("")

    lines.extend([
        "## Per-ticker breakdown",
        "",
    ])

    for section in report.ticker_sections:
        lines.append(f"### {section.ticker}")
        lines.append("")
        lines.append(f"**{section.verdict}**")
        lines.append("")
        if section.quant_suppressed:
            counts = ", ".join(f"{r} x{c}" for r, c in section.quant_suppressed.items())
            lines.append(f"- talonx_quant suppressed: {counts}")
        if section.core_suppressed:
            counts = ", ".join(f"{r} x{c}" for r, c in section.core_suppressed.items())
            lines.append(f"- talonx_core suppressed: {counts}")
        if section.alert_counts:
            counts = ", ".join(f"{a} x{c}" for a, c in section.alert_counts.items())
            lines.append(f"- Alerts by action: {counts}")
        if section.brain_categories:
            counts = ", ".join(f"{c} x{n}" for c, n in section.brain_categories.items())
            lines.append(f"- talonx_brain reports: {counts}")
        if section.trades:
            for t in section.trades:
                pnl = t.get("realized_pnl_usd")
                pnl_str = f", PnL ${pnl:+.2f}" if pnl is not None else ""
                lines.append(f"- {t['order_type']} @ ${t['execution_price']:.2f}{pnl_str} ({t['timestamp']})")
        if section.ignored_counts:
            counts = ", ".join(f"{r} x{c}" for r, c in section.ignored_counts.items())
            lines.append(f"- Ignored by reason: {counts}")
        lines.append("")

    if report.phase2_available:
        lines.append("## LLM / cache economics")
        lines.append("")
        totals: Counter = Counter()
        for section in report.ticker_sections:
            totals.update(section.brain_categories)
        if totals:
            for category, count in totals.most_common():
                lines.append(f"- {category}: {count}")
        else:
            lines.append("_No talonx_brain report data for this day._")
        lines.append("")
    else:
        lines.append("## LLM / cache economics")
        lines.append("")
        lines.append(
            "_Not available -- no talonx_core/talonx_quant/talonx_brain stats store was "
            "found. This section (and the per-ticker suppression funnel above) requires "
            "those modules to have run with persistence enabled (the default) at least "
            "once since this feature was added._"
        )
        lines.append("")

    lines.append("## Alert log appendix")
    lines.append("")
    if report.alerts:
        lines.append("| Time | Ticker | Action | Severity | Confidence | Price | Telegram |")
        lines.append("|---|---|---|---|---|---|---|")
        for a in report.alerts:
            lines.append(
                f"| {a['correlated_at']} | {a['ticker']} | {a['action']} | {a['severity']} | "
                f"{a['research_confidence']:.0%} | {a['price']:.2f} | "
                f"{'sent' if a.get('telegram_sent') else ('failed' if a.get('telegram_error') else '-')} |"
            )
    else:
        lines.append("_No alerts today._")

    return "\n".join(lines) + "\n"


def _write_csvs(report: EODReport, out_dir: Path) -> None:
    import pandas as pd

    if report.alerts:
        pd.DataFrame(report.alerts).to_csv(out_dir / f"eod_{report.date}_alerts.csv", index=False)
    all_trades = [t for s in report.ticker_sections for t in s.trades]
    if all_trades:
        pd.DataFrame(all_trades).to_csv(out_dir / f"eod_{report.date}_trades.csv", index=False)
    if report.valuation_snapshots:
        pd.DataFrame([vars(s) for s in report.valuation_snapshots]).to_csv(
            out_dir / f"eod_{report.date}_valuation_radar.csv", index=False
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a TalonX End-of-Day report.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today in --tz")
    parser.add_argument("--tz", default=DEFAULT_TZ, help=f"IANA timezone, default {DEFAULT_TZ}")
    parser.add_argument("--out-dir", default="reports", help="Output directory, default ./reports")
    args = parser.parse_args()

    date_str = args.date or datetime.now(ZoneInfo(args.tz)).strftime("%Y-%m-%d")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dispatch_config = DispatchConfig()
    paper_config = PaperConfig()
    watchlist_config = WatchlistConfig()

    # Phase 2 stores are optional -- an older install (or one running with
    # persistence disabled) simply has no signal-funnel/LLM-economics data,
    # not a crash. Each is opened independently so one missing/broken
    # store doesn't take the others down with it.
    core_store: TickerStateStore | None = None
    quant_store: QuantStateStore | None = None
    brain_store: BrainStatsStore | None = None
    try:
        core_store = TickerStateStore(CoreConfig().state_db_path)
    except Exception as exc:  # noqa: BLE001 -- this section is best-effort
        logger.warning("talonx_core stats unavailable for this report: %s", exc)
    try:
        quant_store = QuantStateStore(QuantConfig().db_path)
    except Exception as exc:  # noqa: BLE001 -- this section is best-effort
        logger.warning("talonx_quant stats unavailable for this report: %s", exc)
    try:
        brain_store = BrainStatsStore(BrainConfig().db_path)
    except Exception as exc:  # noqa: BLE001 -- this section is best-effort
        logger.warning("talonx_brain stats unavailable for this report: %s", exc)

    try:
        with AuditStore(dispatch_config.audit_db_path) as audit_store, \
             PaperTradingStore(paper_config.db_path) as paper_store, \
             TickerWatchlistStore(watchlist_config.db_path) as watchlist_store:
            report = build_report(
                date_str, audit_store, paper_store, watchlist_store, args.tz,
                core_store=core_store, quant_store=quant_store, brain_store=brain_store,
            )
    finally:
        for store in (core_store, quant_store, brain_store):
            if store is not None:
                store.close()

    md_path = out_dir / f"eod_{date_str}.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    _write_csvs(report, out_dir)

    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
