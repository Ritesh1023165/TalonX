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

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

ACTION_EMOJI = {
    "confirmed_bullish": "\U0001F7E2",
    "confirmed_bearish": "\U0001F534",
    "contradicted": "⚠️",
    "degraded_quant_alert": "\U0001F6A7",
}
SEVERITY_EMOJI = {"critical": "\U0001F525", "warning": "⚠️", "info": "ℹ️"}


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
WATCHLIST_PAGE_SIZE = 10
_SORT_KEYS = {"Symbol": "symbol", "Name": "name", "Exchange": "exchange", "Status": "status", "Added": "added_at"}

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
            h = st.columns([1, 2, 1.4, 1.6, 1.1, 1, 1])
            for col, label in zip(h, ["Symbol", "Name", "Exchange", "Added", "Status", "", ""]):
                col.markdown(f"**{label}**")

            for row in page_rows:
                c = st.columns([1, 2, 1.4, 1.6, 1.1, 1, 1])
                c[0].write(row["symbol"])
                c[1].write(row["name"])
                c[2].write(row["exchange"] or "—")
                c[3].write(row["added_at"][:19].replace("T", " "))
                is_active = row["status"] == "active"
                c[4].write("▶️ Active" if is_active else "⏳ Paused")
                if is_active:
                    if c[5].button("⏳ Pause", key=f"pause_{row['symbol']}"):
                        store.pause_ticker(row["symbol"])
                        st.rerun()
                else:
                    if c[5].button("▶️ Resume", key=f"resume_{row['symbol']}"):
                        store.resume_ticker(row["symbol"])
                        st.rerun()
                if c[6].button("\U0001F5D1️ Remove", key=f"remove_{row['symbol']}"):
                    store.remove_ticker(row["symbol"])
                    st.rerun()

    with st.form("add_ticker_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 2, 1.3, 1])
        symbol = c1.text_input("Symbol", placeholder="e.g. NVDA")
        name = c2.text_input("Company name", placeholder="e.g. NVIDIA Corporation")
        exchange = c3.selectbox("Exchange", EXCHANGE_OPTIONS)
        submitted = c4.form_submit_button("Add ticker (paused)")
        if submitted:
            if not symbol.strip():
                st.error("Symbol is required.")
            else:
                store.add_ticker(symbol, name, exchange, status="paused")
                st.rerun()


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


def render_audit_trail(df: pd.DataFrame) -> None:
    st.subheader("Audit trail")
    if df.empty:
        st.info("Nothing recorded yet.")
        return

    col1, col2, col3 = st.columns(3)
    tickers = col1.multiselect("Ticker", sorted(df["ticker"].unique()))
    actions = col2.multiselect("Action", sorted(df["action"].unique()))
    severities = col3.multiselect("Severity", sorted(df["severity"].unique()))

    filtered = df
    if tickers:
        filtered = filtered[filtered["ticker"].isin(tickers)]
    if actions:
        filtered = filtered[filtered["action"].isin(actions)]
    if severities:
        filtered = filtered[filtered["severity"].isin(severities)]

    display_cols = [
        "id", "correlated_at", "ticker", "action", "severity",
        "research_confidence", "price", "telegram_sent",
    ]
    st.dataframe(filtered[display_cols], hide_index=True)
    st.caption(f"{len(filtered)} of {len(df)} alert(s) shown")


def main() -> None:
    st.set_page_config(page_title="TalonX", page_icon="\U0001F4E1", layout="wide")

    config = DispatchConfig()
    watchlist_config = WatchlistConfig()
    st_autorefresh(interval=config.autorefresh_ms, key="dispatch_autorefresh")

    store = get_store(config.audit_db_path)
    watchlist_store = get_watchlist_store(watchlist_config.db_path)

    st.title("\U0001F4E1 TalonX — Live Dashboard")
    st.caption(
        f"Reading {config.audit_db_path} · "
        f"refreshing every {config.autorefresh_ms / 1000:.0f}s · "
        f"last render {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    render_ticker_watchlist(watchlist_store, watchlist_config.poll_interval_seconds)
    st.divider()

    rows = store.recent(limit=config.feed_limit)
    df = pd.DataFrame(rows)

    render_metrics(df)
    st.divider()

    left, right = st.columns([1, 2])
    with left:
        render_alert_history(store)
    with right:
        render_feed(rows)

    st.divider()
    render_audit_trail(df)


if __name__ == "__main__":
    main()
