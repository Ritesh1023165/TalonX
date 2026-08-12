"""
talonx_dispatch.app
------------------------
Streamlit dashboard: a live view over the audit trail consumer.py
(DispatchAgent) writes to, PLUS a control surface over the ticker
watchlist (talonx_watchlist.store) that run_talonx.py's market data
streaming and periodic ingestion read from. The alert-trail half is
read-only; the "Tracked tickers" section actually writes (add/remove).

ALWAYS a separate, standalone process from the consumer -- Streamlit
reruns this entire script top-to-bottom on every interaction/autorefresh
tick, which is fundamentally incompatible with holding a persistent
asyncio Redis Pub/Sub subscription open (a fresh subscribe-and-consume
loop on every rerun would be both wasteful and lossy between reruns).
Instead this reads the same durable SQLite store the consumer writes to
(store.py) -- see that module's docstring for why a shared SQLite file
across two separate processes is safe here (standard multi-process
access via file locking, WAL mode enabled for smoother concurrent
read-while-write). The watchlist store (talonx_watchlist/store.py)
follows the same pattern -- this process writes to it, run_talonx.py
polls it for changes.

Usage:
    streamlit run talonx_dispatch/app.py

Run this ALONGSIDE `python run_talonx.py` (or at least
`python -m talonx_dispatch.run`, the consumer) -- without it, there's
nothing writing to the audit trail and the alert feed stays empty, and
ticker add/remove here won't be picked up by anything.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# `streamlit run` invokes its own console-script entry point rather than
# `python -m`, so unlike every other entrypoint in this project it does
# NOT put the repo root on sys.path automatically -- only this script's
# own folder. Same "resolve relative to this file's location, not the
# current working directory" fix every config.py already applies to
# .env loading, applied here to sys.path instead.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_paper.config import PaperConfig
from talonx_paper.store import PaperTradingStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

ACTION_EMOJI = {
    "confirmed_bullish": "\U0001F7E2",
    "confirmed_bearish": "\U0001F534",
    "contradicted": "⚠️",
    "degraded_quant_alert": "\U0001F6A7",
}
SEVERITY_EMOJI = {"critical": "\U0001F525", "warning": "⚠️", "info": "ℹ️"}

# Phase 2 LONG_TERM path -- disjoint action set from ACTION_EMOJI above,
# never mixed (long-term alerts live in their own table/tab).
LT_ACTION_EMOJI = {
    "high_conviction_buy": "\U0001F7E2",
    "hold_quality": "\U0001F535",
    "take_profit_rebalance": "\U0001F4B0",
    "under_perform_rebalance": "\U0001F534",
}
MOAT_EMOJI = {"wide": "\U0001F6E1️", "narrow": "\U0001F6A7", "none": "⚠️"}


@st.cache_resource
def get_store(db_path: str) -> AuditStore:
    # check_same_thread=False: Streamlit's execution model can run a
    # session's script on a different thread than the one that created
    # this cached object -- see store.py's docstring for why this is the
    # one deliberate exception to the project's usual
    # check_same_thread=True default.
    return AuditStore(db_path, check_same_thread=False)


@st.cache_resource
def get_watchlist_store(db_path: str) -> TickerWatchlistStore:
    # Same check_same_thread=False reasoning as get_store() above --
    # TickerWatchlistStore already defaults to it for exactly this reason
    # (see its own docstring), but pinned explicitly here too.
    return TickerWatchlistStore(db_path)


@st.cache_resource
def get_paper_store(
    db_path: str, default_initial_balance: float, default_trade_allocation_usd: float,
    default_long_term_initial_balance: float, default_dca_contribution_usd: float,
) -> PaperTradingStore:
    # default_* only matter the very first time this file/db is created --
    # PaperTradingStore's _ensure_*_row methods are a no-op on every later
    # call. The long-term pair are this store's Phase 2 additions -- see
    # its own docstring for why they share this ONE connection/file with
    # the intraday portfolio instead of a second store.
    return PaperTradingStore(
        db_path, default_initial_balance, default_trade_allocation_usd,
        default_long_term_initial_balance, default_dca_contribution_usd,
    )


def render_metrics(df: pd.DataFrame) -> None:
    cols = st.columns(5)
    cols[0].metric("Total alerts", len(df))
    cols[1].metric("Distinct tickers", df["ticker"].nunique() if not df.empty else 0)
    cols[2].metric(
        "Confirmed bullish", int((df["action"] == "confirmed_bullish").sum()) if not df.empty else 0
    )
    cols[3].metric(
        "Confirmed bearish", int((df["action"] == "confirmed_bearish").sum()) if not df.empty else 0
    )
    cols[4].metric(
        "Contradicted", int((df["action"] == "contradicted").sum()) if not df.empty else 0
    )


def render_alert_history(store: AuditStore) -> None:
    st.subheader("Tickers with alert history")
    st.caption(
        "Derived from the audit trail -- which tickers have actually produced "
        "alerts, not what's currently being tracked (see \"Tracked tickers\" above for that)."
    )
    watchlist = store.watchlist_summary()
    if not watchlist:
        st.info("No alerts yet. Once talonx_core dispatches one, it'll show up here.")
        return

    wdf = pd.DataFrame(watchlist)
    wdf["last_action"] = wdf["last_action"].map(lambda a: f"{ACTION_EMOJI.get(a, '')} {a}")
    wdf["last_severity"] = wdf["last_severity"].map(lambda s: f"{SEVERITY_EMOJI.get(s, '')} {s}")
    wdf = wdf.rename(columns={
        "ticker": "Ticker", "alert_count": "Alerts", "last_seen": "Last seen",
        "last_action": "Last action", "last_severity": "Last severity",
    })
    st.dataframe(wdf, hide_index=True)


EXCHANGE_OPTIONS = ["NASDAQ", "NYSE", "NYSE American (AMEX)", "NASDAQ (US ADR) / Euronext Amsterdam", "NSE", "BSE", "LSE (London Stock Exchange)", "Korea Exchange (KRX)", "NYSE (US ADR) / HKEX", "OTC Markets", "TSX", "LSE", "Other"]
HORIZON_OPTIONS = ["INTRADAY", "LONG_TERM", "DUAL_HORIZON"]
HORIZON_LABEL = {"INTRADAY": "\U0001F4C8 Intraday", "LONG_TERM": "\U0001F48E Long-Term", "DUAL_HORIZON": "\U0001F501 Dual"}
WATCHLIST_PAGE_SIZE = 10
_SORT_KEYS = {
    "Symbol": "symbol", "Name": "name", "Exchange": "exchange", "Status": "status",
    "Horizon": "strategy_horizon", "Added": "added_at",
}

# Color-codes the Pause/Resume/Remove buttons so the three actions read as
# distinct at a glance. Targets Streamlit's `st-key-<key>` class, which it
# puts on a widget's wrapping container whenever an explicit `key=` is
# passed (documented for exactly this "style a specific widget" use case,
# stable since Streamlit added it) -- so this only affects buttons whose
# key starts with pause_/resume_/remove_, nothing else on the page.
_WATCHLIST_BUTTON_CSS = """
<style>
div[class*="st-key-pause_"] button  { background-color: #F59E0B; border-color: #F59E0B; color: white; }
div[class*="st-key-resume_"] button { background-color: #16A34A; border-color: #16A34A; color: white; }
div[class*="st-key-remove_"] button { background-color: #DC2626; border-color: #DC2626; color: white; }
div[class*="st-key-pause_"] button:hover,
div[class*="st-key-resume_"] button:hover,
div[class*="st-key-remove_"] button:hover { filter: brightness(1.1); color: white; }
</style>
"""


def render_ticker_watchlist(store: TickerWatchlistStore, poll_interval_seconds: float) -> None:
    st.subheader("\U0001F3AF Tracked tickers")
    st.caption(
        f"What run_talonx.py actually streams market data (and periodically ingests "
        f"filings/news) for. Remove or pause/resume a ticker here and the running "
        f"pipeline picks it up within {poll_interval_seconds:.0f}s -- no restart needed. "
        f"Pausing stops streaming/ingestion for that ticker but keeps its row -- unlike "
        f"removing, you don't lose the name/exchange when you resume it later. A newly "
        f"added ticker starts PAUSED -- resume it once you're ready to start tracking it."
    )
    st.markdown(_WATCHLIST_BUTTON_CSS, unsafe_allow_html=True)

    tickers = store.list_tickers()
    if not tickers:
        st.info("Watchlist is empty -- market data streaming is paused until you add a ticker.")
    else:
        exchanges_present = sorted({t["exchange"] for t in tickers if t["exchange"]})
        f_col, sort_col, dir_col = st.columns([2, 2, 1])
        filter_exchanges = f_col.multiselect("Filter by exchange", exchanges_present)
        sort_label = sort_col.selectbox("Sort by", list(_SORT_KEYS), key="watchlist_sort_by")
        sort_desc = dir_col.checkbox("Desc", key="watchlist_sort_desc")

        filtered = [t for t in tickers if not filter_exchanges or t["exchange"] in filter_exchanges]
        sort_key = _SORT_KEYS[sort_label]
        filtered.sort(key=lambda t: (t[sort_key] or "").lower(), reverse=sort_desc)

        total = len(filtered)
        total_pages = max(1, -(-total // WATCHLIST_PAGE_SIZE))  # ceil division
        page = st.session_state.get("watchlist_page", 0)
        page = max(0, min(page, total_pages - 1))

        prev_col, label_col, next_col = st.columns([1, 3, 1])
        if prev_col.button("◀ Prev", disabled=page == 0, key="watchlist_prev"):
            page -= 1
        label_col.markdown(f"Page {page + 1} of {total_pages} ({total} ticker(s))")
        if next_col.button("Next ▶", disabled=page >= total_pages - 1, key="watchlist_next"):
            page += 1
        st.session_state["watchlist_page"] = page

        page_rows = filtered[page * WATCHLIST_PAGE_SIZE : (page + 1) * WATCHLIST_PAGE_SIZE]

        if not page_rows:
            st.info("No tickers match the current filter.")
        else:
            h = st.columns([1, 1.8, 1.2, 1.4, 1, 1.3, 1, 1])
            for col, label in zip(h, ["Symbol", "Name", "Exchange", "Added", "Status", "Horizon", "", ""]):
                col.markdown(f"**{label}**")

            for row in page_rows:
                c = st.columns([1, 1.8, 1.2, 1.4, 1, 1.3, 1, 1])
                c[0].write(row["symbol"])
                c[1].write(row["name"])
                c[2].write(row["exchange"] or "—")
                c[3].write(row["added_at"][:19].replace("T", " "))
                is_active = row["status"] == "active"
                c[4].write("▶️ Active" if is_active else "⏳ Paused")
                horizon = row["strategy_horizon"]
                new_horizon = c[5].selectbox(
                    "Horizon", HORIZON_OPTIONS, index=HORIZON_OPTIONS.index(horizon),
                    format_func=lambda h: HORIZON_LABEL[h], key=f"horizon_{row['symbol']}",
                    label_visibility="collapsed",
                )
                if new_horizon != horizon:
                    store.set_strategy_horizon(row["symbol"], new_horizon)
                    st.rerun()
                if is_active:
                    if c[6].button("⏳ Pause", key=f"pause_{row['symbol']}"):
                        store.pause_ticker(row["symbol"])
                        st.rerun()
                else:
                    if c[6].button("▶️ Resume", key=f"resume_{row['symbol']}"):
                        store.resume_ticker(row["symbol"])
                        st.rerun()
                if c[7].button("\U0001F5D1️ Remove", key=f"remove_{row['symbol']}"):
                    store.remove_ticker(row["symbol"])
                    st.rerun()

    with st.form("add_ticker_form", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([1, 1.8, 1.2, 1.3, 1])
        symbol = c1.text_input("Symbol", placeholder="e.g. NVDA")
        name = c2.text_input("Company name", placeholder="e.g. NVIDIA Corporation")
        exchange = c3.selectbox("Exchange", EXCHANGE_OPTIONS)
        horizon = c4.selectbox("Horizon", HORIZON_OPTIONS, format_func=lambda h: HORIZON_LABEL[h])
        submitted = c5.form_submit_button("Add ticker (paused)")
        if submitted:
            if not symbol.strip():
                st.error("Symbol is required.")
            else:
                store.add_ticker(symbol, name, exchange, status="paused", strategy_horizon=horizon)
                st.rerun()


_TRADE_HISTORY_COLUMNS = {
    "id": "Trade #", "ticker": "Ticker", "order_type": "Type", "execution_price": "Price",
    "shares": "Shares", "entry_price": "Entry", "realized_pnl_usd": "PnL ($)",
    "realized_pnl_pct": "PnL (%)", "portfolio_cash_after": "Cash after", "timestamp": "Time",
}


def render_paper_trading(paper_store: PaperTradingStore) -> None:
    st.subheader("\U0001F4B0 Paper Trading")
    st.caption(
        "Virtual broker: simulates a BUY on a CONFIRMED_BULLISH alert and a SELL on "
        "CONFIRMED_BEARISH/CONTRADICTED, for tickers enabled below. Only ONE open "
        "position per ticker at a time -- a repeat signal while already in that state "
        "is ignored, not stacked. Settings (allocation, ticker enablement, reset) are "
        "in the Watchlist & Settings tab."
    )

    summary = paper_store.get_portfolio_summary()
    open_positions = paper_store.get_open_positions()
    latest_prices = paper_store.get_latest_prices()

    open_value = 0.0
    for pos in open_positions:
        open_value += pos["shares"] * latest_prices.get(pos["ticker"], pos["entry_price"])
    total_value = summary["current_cash"] + open_value
    total_pnl = total_value - summary["initial_balance"]
    total_pnl_pct = (total_pnl / summary["initial_balance"] * 100) if summary["initial_balance"] else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Portfolio value", f"${total_value:,.2f}", f"{total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)")
    m2.metric("Cash", f"${summary['current_cash']:,.2f}")
    closed_trades = summary["win_count"] + summary["loss_count"]
    m3.metric(
        "Win rate",
        f"{summary['win_rate_pct']:.0f}%" if closed_trades else "—",
        f"{summary['win_count']}W / {summary['loss_count']}L",
        delta_color="off",
    )
    m4.metric("Open positions", summary["open_positions_count"])

    if open_positions:
        st.markdown("**Open positions**")
        rows = []
        for pos in open_positions:
            live = latest_prices.get(pos["ticker"], pos["entry_price"])
            u_pnl = pos["shares"] * (live - pos["entry_price"])
            u_pnl_pct = ((live - pos["entry_price"]) / pos["entry_price"] * 100) if pos["entry_price"] else 0.0
            rows.append({
                "Ticker": pos["ticker"], "Shares": round(pos["shares"], 4),
                "Entry": pos["entry_price"], "Live price": live,
                "Unrealized PnL ($)": round(u_pnl, 2), "Unrealized PnL (%)": round(u_pnl_pct, 2),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("No open positions.")

    history = paper_store.get_trade_history()
    if not history:
        st.info("No trades executed yet.")
        return

    hdf = pd.DataFrame(history)

    st.markdown("**Equity curve**")
    equity_df = hdf.sort_values("id")[["timestamp", "portfolio_cash_after"]].copy()
    equity_df["timestamp"] = pd.to_datetime(equity_df["timestamp"])
    st.area_chart(equity_df.set_index("timestamp").rename(columns={"portfolio_cash_after": "Cash after trade"}))

    closed = hdf[hdf["order_type"] == "SELL"].copy()
    if not closed.empty:
        st.markdown("**Per-trade PnL**")
        closed["result"] = closed["realized_pnl_usd"].apply(lambda x: "Win" if x >= 0 else "Loss")
        chart = (
            alt.Chart(closed)
            .mark_bar()
            .encode(
                x=alt.X("id:O", title="Trade #", sort=None),
                y=alt.Y("realized_pnl_usd:Q", title="PnL ($)"),
                color=alt.Color(
                    "result:N", title="Result",
                    scale=alt.Scale(domain=["Win", "Loss"], range=["#16A34A", "#DC2626"]),
                ),
                tooltip=["ticker", "realized_pnl_usd", "realized_pnl_pct"],
            )
            .properties(height=250)
        )
        st.altair_chart(chart, use_container_width=True)

    st.markdown("**Trade history**")
    display_df = hdf.rename(columns=_TRADE_HISTORY_COLUMNS)
    st.dataframe(display_df, hide_index=True, use_container_width=True)
    st.download_button(
        "\U0001F4E5 Download trade history (CSV)",
        data=hdf.to_csv(index=False).encode("utf-8"),
        file_name="talonx_paper_trades.csv",
        mime="text/csv",
    )


def render_paper_trading_settings(paper_store: PaperTradingStore, watchlist_store: TickerWatchlistStore) -> None:
    """Intraday Module 6 settings -- extracted out of render_paper_trading
    so Tab 1 (the live monitor) stays read-mostly and every settings
    control lives together in Tab 3, matching that tab's "Watchlist &
    Settings" purpose."""
    summary = paper_store.get_portfolio_summary()
    with st.expander("\U0001F4B0 Intraday Paper Trading Settings", expanded=False):
        s1, s2, s3 = st.columns([1, 1, 1])
        new_balance = s1.number_input(
            "Starting balance ($)", min_value=100.0, value=float(summary["initial_balance"]), step=500.0,
            help="Only takes effect via Reset Portfolio below -- changing this alone doesn't touch the live balance.",
        )
        new_allocation = s2.number_input(
            "Trade allocation ($/position)", min_value=10.0, value=float(summary["trade_allocation_usd"]), step=100.0,
            help="Fixed $ spent per BUY, capped at whatever cash is actually available.",
        )
        if s3.button("Save allocation", key="save_intraday_allocation"):
            paper_store.update_trade_allocation(new_allocation)
            st.rerun()

        tracked = [t["symbol"] for t in watchlist_store.list_tickers()]
        currently_enabled = watchlist_store.list_paper_trading_symbols()
        enabled = st.multiselect(
            "Enable intraday paper trading for", options=tracked, default=currently_enabled,
            help="Only tracked tickers selected here are ever traded by the INTRADAY paper engine. "
                 "Independent of the Long-Term Paper Trading Settings toggle below -- a DUAL_HORIZON "
                 "ticker can have one enabled without the other.",
        )
        if set(enabled) != set(currently_enabled):
            for symbol in tracked:
                watchlist_store.set_paper_trading(symbol, symbol in enabled)
            st.rerun()

        st.divider()
        confirm_reset = st.checkbox(
            "I understand this clears all open positions and trade history",
            key="confirm_reset_intraday",
        )
        if st.button(
            "\U0001F504 Reset Intraday Portfolio", disabled=not confirm_reset, type="primary",
            key="reset_intraday_portfolio",
        ):
            paper_store.reset_portfolio(new_balance, new_allocation)
            st.rerun()


def render_long_term_paper_settings(paper_store: PaperTradingStore, watchlist_store: TickerWatchlistStore) -> None:
    """Phase 2's sibling to render_paper_trading_settings above -- its own
    starting balance/DCA amount/rebalance trim %, its own ticker-enablement
    toggle (a SEPARATE flag from the intraday one -- see
    talonx_watchlist/store.py's set_paper_trading_long_term), and its own
    independent Reset button (deliberately NOT the same reset as the
    intraday portfolio -- the two cash pools are fully separate, see
    store.py)."""
    lt_summary = paper_store.get_long_term_portfolio_summary()
    with st.expander("\U0001F48E Long-Term Paper Trading Settings", expanded=False):
        s1, s2 = st.columns([1, 1])
        new_lt_balance = s1.number_input(
            "Starting balance ($)", min_value=100.0, value=float(lt_summary["initial_balance"]), step=1000.0,
            help="Only takes effect via Reset Long-Term Portfolio below.",
            key="lt_new_balance",
        )
        new_dca = s2.number_input(
            "DCA contribution ($/cycle)", min_value=10.0, value=float(lt_summary["dca_contribution_usd"]), step=50.0,
            help="Added to every currently-open long-term position on each recurring DCA cycle "
                 "(TALONX_PAPER_DCA_INTERVAL_DAYS, default 30 days).",
        )
        if st.button("Save DCA amount"):
            paper_store.update_dca_contribution_amount(new_dca)
            st.rerun()

        tracked = [t["symbol"] for t in watchlist_store.list_tickers()]
        currently_enabled_lt = watchlist_store.list_paper_trading_long_term_symbols()
        enabled_lt = st.multiselect(
            "Enable long-term paper trading for", options=tracked, default=currently_enabled_lt,
            help="Only tracked tickers selected here are ever traded by the LONG-TERM paper engine "
                 "(and only if they're also tagged LONG_TERM or DUAL_HORIZON -- untagged tickers "
                 "never receive a long-term alert to act on regardless of this toggle). Independent "
                 "of the intraday toggle above.",
        )
        if set(enabled_lt) != set(currently_enabled_lt):
            for symbol in tracked:
                watchlist_store.set_paper_trading_long_term(symbol, symbol in enabled_lt)
            st.rerun()

        st.divider()
        confirm_reset = st.checkbox(
            "I understand this clears all open long-term positions and trade history",
            key="confirm_reset_long_term",
        )
        if st.button(
            "\U0001F504 Reset Long-Term Portfolio", disabled=not confirm_reset, type="primary",
            key="reset_long_term_portfolio",
        ):
            paper_store.reset_long_term_portfolio(new_lt_balance, new_dca)
            st.rerun()


_LT_TRADE_HISTORY_COLUMNS = {
    "id": "Trade #", "ticker": "Ticker", "order_type": "Type", "execution_price": "Price",
    "shares": "Shares", "contribution_cost": "Cost/Proceeds ($)", "avg_cost_basis_after": "Avg cost after",
    "total_shares_after": "Shares after", "realized_pnl_usd": "PnL ($)", "realized_pnl_pct": "PnL (%)",
    "holding_period_days": "Held (days)", "portfolio_cash_after": "Cash after", "timestamp": "Time",
}


def render_valuation_radar(store: AuditStore) -> None:
    st.subheader("\U0001F48E Valuation & Margin of Safety Radar")
    st.caption(
        "Latest long-term alert per ticker -- current price vs. talonx_brain's DCF fair "
        "value, quality score (0-10), and moat rating. Only tickers that have cleared the "
        "fundamental factor threshold and produced at least one long-term alert show up here."
    )
    rows = store.recent_long_term(limit=500)
    if not rows:
        st.info("No long-term alerts yet. Tag a ticker LONG_TERM in the watchlist tab and wait for a signal.")
        return

    latest_per_ticker: dict[str, dict] = {}
    for row in rows:  # DESC by correlated_at/id -- first occurrence per ticker is the latest
        latest_per_ticker.setdefault(row["ticker"], row)

    radar_rows = [
        {
            "Ticker": row["ticker"],
            "Action": f"{LT_ACTION_EMOJI.get(row['action'], '')} {row['action'].replace('_', ' ').title()}",
            "Price": row["market_price"],
            "Fair value": row["intrinsic_fair_value"],
            "Margin of safety %": row["margin_of_safety_pct"] * 100,
            "Quality": row["quality_score"],
            "Moat": f"{MOAT_EMOJI.get(row['moat_rating'], '')} {row['moat_rating'].title()}",
            "Last evaluated": row["correlated_at"][:19].replace("T", " "),
        }
        for row in latest_per_ticker.values()
    ]
    radar_df = pd.DataFrame(radar_rows).sort_values("Margin of safety %", ascending=False)
    st.dataframe(
        radar_df, hide_index=True, use_container_width=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Fair value": st.column_config.NumberColumn(format="$%.2f"),
            "Margin of safety %": st.column_config.NumberColumn(format="%.1f%%"),
            "Quality": st.column_config.ProgressColumn(min_value=0, max_value=10, format="%d/10"),
        },
    )


def render_long_term_research_viewer(store: AuditStore) -> None:
    st.subheader("\U0001F4DA Long-Term Research")
    st.caption("The latest moat/capital-allocation/DCF writeup behind each ticker's radar row above.")
    rows = store.recent_long_term(limit=500)
    if not rows:
        st.info("Nothing yet.")
        return

    latest_per_ticker: dict[str, dict] = {}
    for row in rows:
        latest_per_ticker.setdefault(row["ticker"], row)

    for ticker in sorted(latest_per_ticker):
        row = latest_per_ticker[ticker]
        emoji = LT_ACTION_EMOJI.get(row["action"], "")
        moat = MOAT_EMOJI.get(row["moat_rating"], "")
        title = (
            f"{emoji} {ticker} — {row['action'].replace('_', ' ').title()} "
            f"({moat} {row['moat_rating'].title()} moat, quality {row['quality_score']}/10)"
        )
        with st.expander(title, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Price:** ${row['market_price']:,.2f}")
            c2.write(f"**Fair value:** ${row['intrinsic_fair_value']:,.2f}")
            c3.write(f"**Margin of safety:** {row['margin_of_safety_pct']:+.1%}")

            st.write(row["rationale"])
            st.markdown(f"**Capital allocation:** {row['capital_allocation_assessment']}")

            if row["key_findings"]:
                st.markdown("**Key findings:**")
                for f in row["key_findings"]:
                    st.markdown(f"- {f}")
            if row["risk_factors"]:
                st.markdown("**Risks:**")
                for r in row["risk_factors"]:
                    st.markdown(f"- {r}")

            st.caption(f"{row['model_used']} · {row['correlated_at']}")


def render_long_term_portfolio(paper_store: PaperTradingStore) -> None:
    st.subheader("\U0001F4B0 Long-Term Portfolio")
    st.caption(
        "A SEPARATE cash pool and position ledger from the intraday paper portfolio "
        "(Tab 1) -- HIGH_CONVICTION_BUY opens a position, ongoing conviction is expressed "
        "via recurring DCA contributions rather than repeated buys, TAKE_PROFIT_REBALANCE "
        "trims a fraction, UNDER_PERFORM_REBALANCE exits fully."
    )

    summary = paper_store.get_long_term_portfolio_summary()
    open_positions = paper_store.get_open_long_term_positions()
    latest_prices = paper_store.get_latest_prices()

    open_value = 0.0
    total_contributed = 0.0
    for pos in open_positions:
        open_value += pos["total_shares"] * latest_prices.get(pos["ticker"], pos["avg_cost_basis"])
        total_contributed += pos["total_contributed_usd"]
    total_value = summary["current_cash"] + open_value
    total_pnl = total_value - summary["initial_balance"]
    total_pnl_pct = (total_pnl / summary["initial_balance"] * 100) if summary["initial_balance"] else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Portfolio value", f"${total_value:,.2f}", f"{total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)")
    m2.metric("Cash", f"${summary['current_cash']:,.2f}")
    m3.metric("Total DCA contributed", f"${total_contributed:,.2f}")
    m4.metric("Open positions", summary["open_positions_count"])

    if open_positions:
        st.markdown("**Open positions**")
        rows = []
        for pos in open_positions:
            live = latest_prices.get(pos["ticker"], pos["avg_cost_basis"])
            u_pnl = pos["total_shares"] * (live - pos["avg_cost_basis"])
            u_pnl_pct = ((live - pos["avg_cost_basis"]) / pos["avg_cost_basis"] * 100) if pos["avg_cost_basis"] else 0.0
            rows.append({
                "Ticker": pos["ticker"], "Shares": round(pos["total_shares"], 4),
                "Avg cost basis": pos["avg_cost_basis"], "Live price": live,
                "Total contributed ($)": round(pos["total_contributed_usd"], 2),
                "First entry": pos["first_entry_at"][:19].replace("T", " "),
                "Unrealized PnL ($)": round(u_pnl, 2), "Unrealized PnL (%)": round(u_pnl_pct, 2),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("No open long-term positions.")

    history = paper_store.get_long_term_trade_history()
    if not history:
        st.info("No long-term trades executed yet.")
        return

    hdf = pd.DataFrame(history)

    st.markdown("**Equity curve**")
    equity_df = hdf.sort_values("id")[["timestamp", "portfolio_cash_after"]].copy()
    equity_df["timestamp"] = pd.to_datetime(equity_df["timestamp"])
    st.area_chart(equity_df.set_index("timestamp").rename(columns={"portfolio_cash_after": "Cash after trade"}))

    st.markdown("**Trade history** (BUY / DCA_CONTRIBUTION / SELL)")
    display_df = hdf.rename(columns=_LT_TRADE_HISTORY_COLUMNS)
    st.dataframe(display_df, hide_index=True, use_container_width=True)
    st.download_button(
        "\U0001F4E5 Download long-term trade history (CSV)",
        data=hdf.to_csv(index=False).encode("utf-8"),
        file_name="talonx_paper_long_term_trades.csv",
        mime="text/csv",
    )


def render_feed(rows: list[dict], limit: int = 20) -> None:
    st.subheader("Live alert feed")
    if not rows:
        st.info("Nothing yet.")
        return

    for row in rows[:limit]:
        emoji = ACTION_EMOJI.get(row["action"], "")
        sev = SEVERITY_EMOJI.get(row["severity"], "")
        title = f"{emoji} {row['ticker']} — {row['action'].replace('_', ' ').title()} {sev}"
        with st.expander(title, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Price:** ${row['price']:,.2f}")
            c2.write(f"**Research confidence:** {row['research_confidence']:.0%}")
            telegram_status = (
                "✅ sent" if row["telegram_sent"]
                else (f"❌ failed: {row['telegram_error']}" if row["telegram_error"] else "—")
            )
            c3.write(f"**Telegram:** {telegram_status}")

            st.write(row["rationale"])

            if row["key_findings"]:
                st.markdown("**Key findings:**")
                for f in row["key_findings"]:
                    st.markdown(f"- {f}")
            if row["risk_factors"]:
                st.markdown("**Risks:**")
                for r in row["risk_factors"]:
                    st.markdown(f"- {r}")

            st.caption(f"{row['model_used']} · {row['correlated_at']}")


def _apply_date_range_filter(df: pd.DataFrame, date_col: str, date_range: tuple) -> pd.DataFrame:
    """st.date_input(value=()) returns an empty tuple until the user picks
    a date, a 1-tuple after just the start date, and a 2-tuple once both
    are picked -- handles all three (no filter / single-day / inclusive
    range). Compared as UTC calendar dates, matching how every timestamp
    in this project is stored (datetime.now(timezone.utc).isoformat())."""
    if not date_range:
        return df
    dates = pd.to_datetime(df[date_col], utc=True).dt.date
    start = date_range[0]
    end = date_range[1] if len(date_range) > 1 else date_range[0]
    return df[(dates >= start) & (dates <= end)]


def render_audit_trail(df: pd.DataFrame, long_term_rows: list[dict]) -> None:
    """Unified audit trail with a horizon filter -- a radio toggle rather
    than one merged table, since the intraday/long-term field sets differ
    too much to share display columns cleanly (same reasoning that kept
    alerts/long_term_alerts as separate tables in store.py)."""
    st.subheader("Audit trail")
    horizon = st.radio("Horizon", ["Intraday", "Long-Term"], horizontal=True, key="audit_trail_horizon")

    if horizon == "Intraday":
        if df.empty:
            st.info("Nothing recorded yet.")
            return
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1.4])
        tickers = col1.multiselect("Ticker", sorted(df["ticker"].unique()), key="audit_intraday_ticker")
        actions = col2.multiselect("Action", sorted(df["action"].unique()), key="audit_intraday_action")
        severities = col3.multiselect("Severity", sorted(df["severity"].unique()), key="audit_intraday_severity")
        date_range = col4.date_input(
            "Date range", value=(), key="audit_intraday_date_range",
            help="Filters on correlated_at. Leave empty for no date filter.",
        )

        filtered = df
        if tickers:
            filtered = filtered[filtered["ticker"].isin(tickers)]
        if actions:
            filtered = filtered[filtered["action"].isin(actions)]
        if severities:
            filtered = filtered[filtered["severity"].isin(severities)]
        filtered = _apply_date_range_filter(filtered, "correlated_at", date_range)

        display_cols = [
            "id", "correlated_at", "ticker", "action", "severity",
            "research_confidence", "price", "telegram_sent", "suppress_reason",
        ]
        st.dataframe(filtered[display_cols], hide_index=True)
        st.caption(f"{len(filtered)} of {len(df)} alert(s) shown")
    else:
        if not long_term_rows:
            st.info("Nothing recorded yet.")
            return
        lt_df = pd.DataFrame(long_term_rows)
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1.4])
        tickers = col1.multiselect("Ticker", sorted(lt_df["ticker"].unique()), key="audit_lt_ticker")
        actions = col2.multiselect("Action", sorted(lt_df["action"].unique()), key="audit_lt_action")
        severities = col3.multiselect("Severity", sorted(lt_df["severity"].unique()), key="audit_lt_severity")
        date_range = col4.date_input(
            "Date range", value=(), key="audit_lt_date_range",
            help="Filters on correlated_at. Leave empty for no date filter.",
        )

        filtered = lt_df
        if tickers:
            filtered = filtered[filtered["ticker"].isin(tickers)]
        if actions:
            filtered = filtered[filtered["action"].isin(actions)]
        if severities:
            filtered = filtered[filtered["severity"].isin(severities)]
        filtered = _apply_date_range_filter(filtered, "correlated_at", date_range)

        display_cols = [
            "id", "correlated_at", "ticker", "action", "severity", "quality_score",
            "moat_rating", "market_price", "intrinsic_fair_value", "margin_of_safety_pct",
            "telegram_sent", "suppress_reason",
        ]
        st.dataframe(filtered[display_cols], hide_index=True)
        st.caption(f"{len(filtered)} of {len(lt_df)} alert(s) shown")


def main() -> None:
    st.set_page_config(page_title="TalonX", page_icon="\U0001F4E1", layout="wide")

    config = DispatchConfig()
    watchlist_config = WatchlistConfig()
    paper_config = PaperConfig()
    st_autorefresh(interval=config.autorefresh_ms, key="dispatch_autorefresh")

    store = get_store(config.audit_db_path)
    watchlist_store = get_watchlist_store(watchlist_config.db_path)
    paper_store = get_paper_store(
        paper_config.db_path, paper_config.default_initial_balance, paper_config.default_trade_allocation_usd,
        paper_config.default_long_term_initial_balance, paper_config.dca_contribution_usd,
    )

    st.title("\U0001F4E1 TalonX — Live Dashboard")
    st.caption(
        f"Reading {config.audit_db_path} · "
        f"refreshing every {config.autorefresh_ms / 1000:.0f}s · "
        f"last render {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    rows = store.recent(limit=config.feed_limit)
    df = pd.DataFrame(rows)
    long_term_rows = store.recent_long_term(limit=config.feed_limit)

    tab_intraday, tab_long_term, tab_settings = st.tabs(
        ["\U0001F4C8 Intraday Monitor", "\U0001F48E Long-Term Radar", "⚙️ Watchlist & Settings"]
    )

    with tab_intraday:
        render_metrics(df)
        st.divider()

        left, right = st.columns([1, 2])
        with left:
            render_alert_history(store)
        with right:
            render_feed(rows)

        st.divider()
        render_paper_trading(paper_store)

    with tab_long_term:
        render_valuation_radar(store)
        st.divider()
        render_long_term_portfolio(paper_store)
        st.divider()
        render_long_term_research_viewer(store)

    with tab_settings:
        render_ticker_watchlist(watchlist_store, watchlist_config.poll_interval_seconds)
        st.divider()
        render_paper_trading_settings(paper_store, watchlist_store)
        render_long_term_paper_settings(paper_store, watchlist_store)
        st.divider()
        render_audit_trail(df, long_term_rows)


if __name__ == "__main__":
    main()
