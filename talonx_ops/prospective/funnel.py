"""
V2 near-miss funnel (Task 114 A3) -- OBSERVATIONAL ONLY.

Reconstructs, from the same authoritative inputs the live V2 companion
uses (the InsiderStore + the frozen ``cluster_engine`` + ``v2_lane.db``),
the funnel:

  Form 4 records -> code-P open-market purchases -> distinct issuers
    -> single-insider near-miss episodes -> >=2-distinct-insider clusters
    -> stale historical clusters -> fresh eligible clusters
    -> V2 signals -> BUYs -> SELLs

No strategy logic is altered.  Every post-code-P episode is given an
explainable terminal state from ``processed_episodes`` where the live
lane recorded one; anything not yet recorded is classified from the same
frozen rules the lane applies (stale vs fresh-eligible vs pending).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _resolved_execution_scope() -> list[str] | None:
    """The enforced V2 execution allowlist (POLLED SEC-covered issuers), or
    ``None`` if it cannot be resolved offline. Same source the live companion
    uses via ``run.py --execution-scope resolved-active-watchlist`` (D1)."""
    try:
        from talonx_ops.watchlist_coverage import build_coverage_map
        allow = sorted(c["symbol"] for c in build_coverage_map()["tickers"]
                       if c.get("v2_collection_scope") == "POLLED")
        return allow or None
    except Exception:  # noqa: BLE001
        return None


def build_funnel(*, db_path: str | Path, as_of: date | None = None,
                 lookback_days: int = 45,
                 execution_allowlist: list[str] | None | str = "auto") -> dict[str, Any]:
    """``execution_allowlist``:
      * ``"auto"`` (default) -> resolve the enforced V2 scope and filter to it,
        matching what the live companion actually evaluates (D1 fix);
      * an explicit ``list[str]`` -> filter to exactly those symbols;
      * ``None`` -> unrestricted (the pre-D1 behaviour; historical replay only).
    """
    as_of = as_of or _today_utc()
    if execution_allowlist == "auto":
        execution_allowlist = _resolved_execution_scope()
    allow_set = ({s.upper() for s in execution_allowlist}
                 if execution_allowlist is not None else None)
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "scope": {
            "today_utc": as_of.isoformat(), "window_days": lookback_days,
            "execution_scope_enforced": allow_set is not None,
            "execution_scope_count": (len(allow_set) if allow_set is not None else None),
        },
        "available": False,
    }

    # ---- 1-3: Form 4 / code-P / issuers, from the live InsiderStore ----
    try:
        from datetime import timedelta
        from talonx_ingest.intelligence.insider.store import InsiderStore
        from talonx_ingest.intelligence.insider.domain import TransactionClass
        st = InsiderStore()
        since = as_of - timedelta(days=lookback_days)
        window = st.query_transactions(classification=TransactionClass.OPEN_MARKET_PURCHASE,
                                       since=since, newest_first=False)
        if allow_set is not None:
            window = [t for t in window if (t.symbol or "").upper() in allow_set]
        code_p_today = [t for t in window
                        if getattr(t, "accepted_at_utc", None)
                        and t.accepted_at_utc.date() == as_of]
        out["available"] = True
        out["form4"] = {
            "code_p_records_window": len(window),
            "code_p_records_today": len(code_p_today),
            "distinct_issuers_window": len({t.symbol for t in window if t.symbol}),
            "distinct_issuers_today": len({t.symbol for t in code_p_today if t.symbol}),
        }
        # cluster reconstruction from the frozen engine
        from talonx_v2 import form4_source, pipeline
        from talonx_v2.config import V2Config
        cfg = V2Config()
        recs = form4_source.from_insider_store(
            st, since=since,
            symbols=(sorted(allow_set) if allow_set is not None else None))
        episodes = pipeline.detect_episodes(recs, config=cfg)
        # single-insider near-misses: issuers with >=1 code-P record in the
        # window but no >=2-distinct-owner cluster
        cluster_issuers = {e.symbol for e in episodes}
        issuers_with_p = {t.symbol for t in window if t.symbol}
        single_insider = sorted(issuers_with_p - cluster_issuers)
        try:
            from talonx_v2.calendar import add_sessions, is_session, next_session_on_or_after
            ripe_through = as_of if is_session(as_of) else next_session_on_or_after(as_of)
            stale_cut = add_sessions(ripe_through, -cfg.max_entry_staleness_sessions)
        except Exception:  # noqa: BLE001
            stale_cut = None
        stale, fresh_eligible, pending = [], [], []
        for e in episodes:
            if stale_cut is not None and e.eligible_entry_session < stale_cut:
                stale.append(e.episode_id)
            elif e.eligible_entry_session <= (ripe_through if stale_cut is not None else as_of):
                fresh_eligible.append(e.episode_id)
            else:
                pending.append(e.episode_id)
        out["clusters"] = {
            "single_insider_near_miss_issuers": single_insider,
            "single_insider_near_miss_count": len(single_insider),
            "clusters_ge2_distinct_insiders": len(episodes),
            "cluster_symbols": sorted(cluster_issuers),
            "stale_historical_clusters": len(stale),
            "stale_episode_ids": stale,
            "fresh_eligible_clusters": len(fresh_eligible),
            "fresh_eligible_episode_ids": fresh_eligible,
            "not_yet_eligible_clusters": len(pending),
        }
    except Exception as exc:  # noqa: BLE001
        out["form4_error"] = f"{type(exc).__name__}: {exc}"

    # ---- terminal accounting from v2_lane.db ----
    p = Path(db_path)
    if p.exists():
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            dispositions: dict[str, int] = {}
            for row in con.execute("SELECT disposition, COUNT(*) c FROM processed_episodes GROUP BY disposition"):
                dispositions[row[0]] = row[1]
            buys = con.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'").fetchone()[0]
            sells = con.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'").fetchone()[0]
            n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
            out["terminal"] = {
                "processed_episode_dispositions": dispositions,
                "signals": int(buys),  # a BUY implies a BULLISH V2 signal was produced
                "buys": int(buys),
                "sells": int(sells),
                "open_positions": int(n_open),
            }
            # ---- decisions -> paper actions -> DELIVERY (Task 117 overnight) ----
            def _has(tbl: str) -> bool:
                return con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
                ).fetchone() is not None
            if _has("pending_entry_intents"):
                by_st: dict[str, int] = {}
                for r in con.execute("SELECT status, COUNT(*) c FROM pending_entry_intents GROUP BY status"):
                    by_st[r[0]] = r[1]
                pend = [dict(r) for r in con.execute(
                    "SELECT symbol, episode_id, target_entry_session, created_at_utc "
                    "FROM pending_entry_intents WHERE status='PENDING' ORDER BY target_entry_session")]
                out["intents"] = {"by_status": by_st, "pending": pend,
                                  "pending_count": len(pend)}
            if _has("v2_alert_outbox"):
                by_state: dict[str, int] = {}
                by_kind: dict[str, int] = {}
                for r in con.execute("SELECT state, COUNT(*) c FROM v2_alert_outbox GROUP BY state"):
                    by_state[r[0]] = r[1]
                for r in con.execute("SELECT kind, COUNT(*) c FROM v2_alert_outbox GROUP BY kind"):
                    by_kind[r[0]] = r[1]
                recent = [dict(r) for r in con.execute(
                    "SELECT kind, action, symbol, state, attempts, transport_ref, last_error, "
                    "created_at_utc, sent_at_utc FROM v2_alert_outbox ORDER BY created_at_utc DESC LIMIT 12")]
                out["delivery"] = {
                    "by_state": by_state, "by_kind": by_kind, "recent": recent,
                    "sent": by_state.get("SENT", 0), "held": by_state.get("HELD", 0),
                    "failed": by_state.get("FAILED", 0), "retry": by_state.get("RETRY", 0),
                    "pending": by_state.get("PENDING", 0), "ambiguous": by_state.get("AMBIGUOUS", 0),
                }
            con.close()
        except sqlite3.Error as exc:
            out["terminal_error"] = str(exc)
    else:
        out["terminal_error"] = "no v2_lane.db"

    # ---- interpretation: NO_OPPORTUNITY vs SELECTIVE vs SUPPRESSION ----
    f = out.get("form4", {})
    c = out.get("clusters", {})
    if not out["available"]:
        out["interpretation"] = "DATA_UNAVAILABLE"
    elif f.get("code_p_records_today", 0) == 0 and c.get("clusters_ge2_distinct_insiders", 0) == 0:
        out["interpretation"] = "NO_MARKET_OPPORTUNITY"          # nothing to act on
    elif c.get("fresh_eligible_clusters", 0) == 0 and c.get("clusters_ge2_distinct_insiders", 0) > 0:
        out["interpretation"] = "STRATEGY_SELECTIVE"             # clusters existed, none fresh-eligible
    elif c.get("fresh_eligible_clusters", 0) > 0 and out.get("terminal", {}).get("buys", 0) == 0:
        out["interpretation"] = "REVIEW_POSSIBLE_SUPPRESSION"    # fresh-eligible but no signal -> inspect
    else:
        out["interpretation"] = "ACTIVITY"
    return out
