"""
talonx_dispatch.app
------------------------
Streamlit dashboard: a live, read-only view over the audit trail
consumer.py (DispatchAgent) writes to.

ALWAYS a separate, standalone process from the consumer -- Streamlit
reruns this entire script top-to-bottom on every interaction/autorefresh
tick, which is fundamentally incompatible with holding a persistent
asyncio Redis Pub/Sub subscription open (a fresh subscribe-and-consume
loop on every rerun would be both wasteful and lossy between reruns).
Instead this reads the same durable SQLite store the consumer writes to
(store.py) -- see that module's docstring for why a shared SQLite file
across two separate processes is safe here (standard multi-process
access via file locking, WAL mode enabled for smoother concurrent
read-while-write).

Usage:
    streamlit run talonx_dispatch/app.py

Run this ALONGSIDE `python -m talonx_dispatch.run` (the consumer) --
without it, there's nothing writing to the audit trail and the dashboard
just stays empty.
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

ACTION_EMOJI = {
    "confirmed_bullish": "\U0001F7E2",
    "confirmed_bearish": "\U0001F534",
    "contradicted": "⚠️",
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


def render_watchlist(store: AuditStore) -> None:
    st.subheader("Active watchlist")
    st.caption(
        "Derived from the audit trail, not a configured list -- talonx_quant has no "
        "dynamic watchlist of its own yet (see README §8). This just shows which "
        "tickers have actually produced alerts."
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
    st.set_page_config(page_title="TalonX Dispatch", page_icon="\U0001F4E1", layout="wide")

    config = DispatchConfig()
    st_autorefresh(interval=config.autorefresh_ms, key="dispatch_autorefresh")

    store = get_store(config.audit_db_path)

    st.title("\U0001F4E1 TalonX — Live Alert Dashboard")
    st.caption(
        f"Reading {config.audit_db_path} · "
        f"refreshing every {config.autorefresh_ms / 1000:.0f}s · "
        f"last render {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    rows = store.recent(limit=config.feed_limit)
    df = pd.DataFrame(rows)

    render_metrics(df)
    st.divider()

    left, right = st.columns([1, 2])
    with left:
        render_watchlist(store)
    with right:
        render_feed(rows)

    st.divider()
    render_audit_trail(df)


if __name__ == "__main__":
    main()
