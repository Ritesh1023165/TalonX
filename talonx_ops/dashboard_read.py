"""talonx_ops.dashboard_read -- Task 100C.

ONE read-only aggregation layer that assembles the six primary sections of the
unified :8787 cockpit from the Task 100A/100B authoritative sources:

  OVERVIEW      -- runtime health, market health, alert health, source status
  PREMARKET     -- earnings radar, premarket watch, event context
  ORIGINAL_QUANT-- the Original funnel (bars -> suppressions -> published ->
                   Brain -> official alerts -> local paper), made legible
  VALIDATION    -- Experimental V1 shadow lane (internal only, never external)
  INTELLIGENCE  -- Task 96 filings / earnings / insider / significance summary
                   (+ deep-link to :8760)
  PAPER_EOD     -- Original / Experimental / PIV paper kept SEPARATE + the
                   Task 100B EOD reconciliation store

Design:
* Every store is opened ``file:...?mode=ro`` or via an already-read-only Task
  100A/B adapter -- this module physically cannot write and never instantiates
  a store class that migrates schema on ``__init__``.
* Every read is wrapped: a missing / locked / malformed source yields an
  explicit semantic status (``ACTIVE`` / ``ZERO_ACTIVITY`` /
  ``NO_ACTIVE_PRODUCER`` / ``SUPERSEDED`` / ``STALE`` / ``UNKNOWN``), never a
  bare misleading ``0``.
* NOT a producer. It never subscribes to Redis, never writes a DB, never
  computes a signal / significance / P&L that an authoritative producer owns.
* Original and Experimental numbers are returned in separate keys with explicit
  ``attribution`` / ``internal_only`` markers so the UI can never merge them.
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from talonx_ops.authoritative_read_model import AuthoritativeReadModel
from talonx_ops.market_health import MarketHealth

import os as _os

#: data root. ``TALONX_HOME`` overrides it -- for isolated-fixture renders /
#: acceptance runs the SPA can be pointed at a copy of the databases without
#: touching ``~/.talonx``.
_HOME = Path(_os.environ["TALONX_HOME"]) if _os.environ.get("TALONX_HOME") else (Path.home() / ".talonx")

# canonical Original rejection reasons, in funnel order (Phase 5). The UI shows
# whatever reasons actually appear; this list only fixes display order + ensures
# a known reason with 0 count is still shown as a real 0.
CANONICAL_REJECTION_REASONS = (
    "LOW_VOLATILITY", "ATR_MOVE", "IMPULSE", "LOW_CONFLUENCE", "LOW_RISK_REWARD",
    "TREND", "OPENING_BLACKOUT", "MARKET_SESSION_CLOSED", "COOLDOWN", "THROTTLE", "LOCKOUT",
)

_DEEP_LINK_8760 = "http://localhost:8760"


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _q1(con: sqlite3.Connection, sql: str, args: tuple = ()) -> Any:
    try:
        row = con.execute(sql, args).fetchone()
        return row[0] if row is not None else None
    except sqlite3.Error:
        return None


def _qall(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    try:
        return list(con.execute(sql, args).fetchall())
    except sqlite3.Error:
        return []


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _q1(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def _cols(con: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return None


class DashboardReadModel:
    """One instance per request batch. Cheap to construct."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        exp_home: Path | None = None,
        intel_ledger: Path | None = None,
        now: datetime | None = None,
        check_processes: bool = True,
    ) -> None:
        self.home = home or _HOME
        self.exp = exp_home or (self.home / "experimental")
        self.intel_ledger = intel_ledger or (self.home / "ingestion_ledger.db")
        self.now = now or datetime.now(timezone.utc)
        self.check_processes = check_processes
        self.arm = AuthoritativeReadModel(
            home=self.home, exp_home=self.exp, intel_state_dir=self.home / "intelligence",
            ledger_path=self.intel_ledger, now=self.now, check_processes=check_processes,
        )

    def _today(self) -> str:
        return self.now.astimezone(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ #
    # OVERVIEW
    # ------------------------------------------------------------------ #
    def overview(self) -> dict[str, Any]:
        orig = self.arm.original_producer()
        exp = self.arm.experimental_producer()
        intel = self.arm.intelligence_producer()
        sup = self.arm.supervision()
        mh = MarketHealth(home=self.home, now=self.now, check_processes=self.check_processes,
                          producer_probe=self.arm.original_producer).view()
        oa = self.arm.official_alerts()
        ea = self.arm.experimental_alerts()
        eod = self.arm.eod_reconciliation()

        # runtime component states (dashboard-derived from producer liveness --
        # the Supervisor object itself lives in another process)
        def cstate(live: bool, mandatory: bool) -> str:
            if live:
                return "READY"
            return "FAILED" if mandatory else "DEGRADED"

        runtime = {
            "overall": self._overall_health(orig["live"], exp["live"], intel["live"], mh.state),
            "original": cstate(orig["live"], True),
            "experimental": cstate(exp["live"], False),
            "intelligence": cstate(intel["live"], False),
            "telegram_send": self._telegram_send_state(oa),
            "telegram_receive": self._telegram_receive_state(orig["live"], sup),
            "forward_outcomes": "READY" if exp["live"] else "DEGRADED",
            "eod": eod.values.get("status", "NOT_DUE") if eod.values else "NOT_DUE",
            "notes": {
                "original": orig["reason"], "experimental": exp["reason"],
                "intelligence": intel["reason"],
            },
        }
        market = {
            "state": mh.state, "session_phase": mh.session_phase,
            "producer_live": mh.producer_live, "producer_reason": mh.producer_reason,
            "last_event": mh.newest_tick, "last_event_age_seconds": mh.newest_tick_age_seconds,
            "last_bar_age_seconds": mh.last_bar_age_seconds,
            "active_poller": mh.active_poller,
            "configured_symbols": mh.configured_symbols, "selected_symbols": mh.selected_symbols,
            "usable_coverage": mh.coverage_ratio, "symbols_priced": mh.symbols_priced,
            "provider_failures": mh.provider_failures, "provider_retries": mh.provider_retries,
            "redis_failures": mh.redis_failures, "redis_reconnects": mh.redis_reconnects,
            "redis_reachable": mh.redis_reachable,
            "source": mh.source,
        }
        alerts = {
            "official_generated": oa.values.get("generated_today"),
            "official_sent": oa.values.get("sent_today"),
            "official_failed": oa.values.get("failed_today"),
            "official_held_deduped": oa.values.get("held_today"),
            "official_status": oa.status.value,
            # The boundary status is the primary indicator -- it is structural,
            # not a count. `legacy_bookkeeping_rows` is the raw `sent=1` row
            # count in exp_alerts.db, which is dry-run bookkeeping (and, for
            # pre-Task-99I sessions, historical) -- NOT a live external send.
            "experimental_external_boundary": "BLOCKED -- structural (Task 100B Phase 6, 3-condition gate)",
            "experimental_external_eligible": bool(ea.values.get("external_eligible", False)),
            "experimental_live_external_sends": 0,
            "experimental_legacy_bookkeeping_rows": ea.values.get("external_sends", 0),
        }
        source_status = self._source_status_block()

        # ---- ACTIVE V2 -- first-class on the Overview (Task 114 A2/A5.1) ----
        try:
            v2 = self.v2_active_strategy()
            fn = v2.get("funnel", {}) or {}
            f4 = fn.get("form4", {}) or {}
            cl = fn.get("clusters", {}) or {}
            tm = fn.get("terminal", {}) or {}
            ldg = v2.get("ledger", {}) or {}
            svc = v2.get("service", {}) or {}
            active_v2 = {
                "strategy": "INSIDER_BUY_CLUSTER_V2@1",
                "role": "ACTIVE V2 -- current prospective candidate",
                "campaign_day": v2.get("campaign", {}).get("campaign_day"),
                "service_health": v2.get("health"),
                "data_state": v2.get("data_state"),
                "business_activity": v2.get("activity"),
                "source": svc.get("form4_source"),
                "last_tick_utc": svc.get("last_tick_utc"),
                "heartbeat_age_s": svc.get("heartbeat_age_s"),
                "form4_records_seen": svc.get("form4_records_seen"),
                "code_p_today": f4.get("code_p_records_today"),
                "code_p_issuers_today": f4.get("distinct_issuers_today"),
                "single_insider_near_miss": cl.get("single_insider_near_miss_count"),
                "clusters_ge2_distinct": cl.get("clusters_ge2_distinct_insiders"),
                "stale_clusters_ignored": cl.get("stale_historical_clusters"),
                "fresh_eligible_clusters": cl.get("fresh_eligible_clusters"),
                "signals": tm.get("signals"), "buys": tm.get("buys"), "sells": tm.get("sells"),
                "cash": ldg.get("cash"), "starting_campaign_cash": ldg.get("starting_campaign_cash"),
                "open_positions": ldg.get("n_open"), "capacity": ldg.get("capacity"),
                "allocated_capital": ldg.get("allocated_capital"),
                "available_capital": ldg.get("available_capital"),
                "realized_pnl_usd": ldg.get("realized_pnl_usd"),
                "exit_unresolved": ldg.get("exit_unresolved"),
                "eod_state": v2.get("eod", {}).get("state"),
                "eod_forced_flatten": "OFF",
                "hold_trading_sessions": 10,
                "signal_lineage": "Form4 -> code-P -> cluster -> V2 Quant -> Brain -> BUY/SELL "
                                  "-> Local Paper Engine -> Official Telegram -> :8787",
                "interpretation": fn.get("interpretation"),
                # Task 117: the 5 independent signals + delivery + candidate/dry-run,
                # surfaced on the Overview (not just the Active V2 tab).
                "coverage_state": v2.get("coverage_state"),
                "pricing_state": v2.get("pricing_state"),
                "pricing_mode": v2.get("readiness", {}).get("pricing_mode"),
                "candidate_pricing": (v2.get("readiness", {}).get("pricing_mode") not in (None, "csv")),
                "delivery": {"enabled": svc.get("delivery_enabled"),
                             **(fn.get("delivery", {}) or {})},
                "pending_entry_intents": len(svc.get("pending_entry_intents", []) or []),
                "v2_fingerprint": v2.get("readiness", {}).get("v2_fingerprint_frozen"),
                "delayed_fill_semantics": ("PLANNED BUY alerts fire before the open; the paper "
                                           "fill records on S+1 at S's open (whole-session "
                                           "provisional deferral) as a delayed notification"),
            }
        except Exception as exc:  # noqa: BLE001
            active_v2 = {"error": f"{type(exc).__name__}: {exc}"}

        if "error" not in active_v2:
            operator = v2.get("operator", {})
            active_v2["operator"] = operator
            active_v2["pending_entry_intents"] = operator.get("account", {}).get("reserved_slots")
        needs_attention = self._overview_needs_attention(runtime, market, active_v2, alerts)
        if active_v2.get("operator", {}).get("account", {}).get("blocked"):
            needs_attention = [x for x in needs_attention if "EXIT_UNRESOLVED" not in x]
        for item in active_v2.get("operator", {}).get("needs_attention", []):
            if item == "EXIT_UNRESOLVED" and any("EXIT_UNRESOLVED" in x for x in needs_attention):
                continue
            if item not in needs_attention:
                needs_attention.append(item)

        return {
            "generated_at": self.now.isoformat(),
            "active_v2": active_v2,          # <-- prioritized first-class block
            "runtime": runtime,
            "market": market,
            "alerts": alerts,
            "source_status": source_status,
            "needs_attention": needs_attention,
            "session": {
                "date": self._today(),
                "phase": mh.session_phase or "unknown",
            },
        }

    @staticmethod
    def _overview_needs_attention(runtime, market, active_v2, alerts) -> list[str]:
        """Only genuine current issues -- healthy zero activity is NOT an issue."""
        out: list[str] = []
        if runtime.get("original") == "FAILED":
            out.append("Core Runtime (Original V1) is DOWN")
        if market.get("state") in ("DISCONNECTED",):
            out.append("Market feed DISCONNECTED")
        if isinstance(active_v2, dict):
            if active_v2.get("service_health") == "DOWN":
                out.append("Active V2 companion is DOWN")
            elif active_v2.get("service_health") == "DEGRADED":
                out.append("Active V2 companion heartbeat DEGRADED")
            if active_v2.get("source") not in (None, "insider"):
                out.append(f"Active V2 source is '{active_v2.get('source')}' (expected insider)")
            if active_v2.get("exit_unresolved"):
                out.append(f"Active V2 has {active_v2.get('exit_unresolved')} EXIT_UNRESOLVED position(s)")
            if active_v2.get("interpretation") == "REVIEW_POSSIBLE_SUPPRESSION":
                out.append("Active V2: fresh eligible cluster with no signal -- review the funnel")
        if alerts.get("official_failed"):
            out.append(f"Official Telegram: {alerts.get('official_failed')} failed send(s) today")
        rt = runtime.get("telegram_receive")
        if rt == "DEGRADED":
            out.append("Telegram receive: >1 getUpdates owner reported (check logical/network owner)")
        return out

    def _overall_health(self, orig_live: bool, exp_live: bool, intel_live: bool, market_state: str) -> str:
        if not orig_live:
            return "FAILED"
        if market_state in ("DISCONNECTED",):
            return "FAILED"
        if (not exp_live) or (not intel_live) or market_state in ("STALE", "UNKNOWN"):
            return "DEGRADED"
        return "HEALTHY"

    def _telegram_send_state(self, oa) -> str:
        v = oa.values or {}
        if v.get("failed_today") and not v.get("sent_today"):
            return "DEGRADED"
        return "READY"

    def _telegram_receive_state(self, orig_live: bool, sup) -> str:
        if not orig_live:
            return "DOWN"
        owners = (sup.values or {}).get("telegram_get_updates_owners")
        if owners is not None and owners > 1:
            return "DEGRADED"
        return "READY"

    def _source_status_block(self) -> list[dict[str, Any]]:
        """Semantic status per domain -- the false-zero guard. Pulled straight
        from the Task 100A AuthoritativeReadModel."""
        out = []
        for m in (self.arm.market, self.arm.quant_funnel, self.arm.quant_signals,
                  self.arm.brain_reports, self.arm.official_alerts, self.arm.experimental_alerts,
                  self.arm.intelligence, self.arm.eod_reconciliation, self.arm.supervision):
            try:
                da = m()
                out.append({
                    "domain": da.domain, "status": da.status.value,
                    "authoritative_source": da.authoritative_source,
                    "last_update": da.last_update, "note": da.note,
                    "superseded_source": da.superseded_source,
                })
            except Exception as exc:  # noqa: BLE001
                out.append({"domain": getattr(m, "__name__", "?"), "status": "UNKNOWN",
                            "authoritative_source": "?", "note": repr(exc)})
        return out

    # ------------------------------------------------------------------ #
    # PREMARKET
    # ------------------------------------------------------------------ #
    def premarket(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "disclaimer": "Premarket observations are informational context, NOT BUY signals.",
        }
        # earnings radar (watchlist.db upcoming_earnings)
        con = _ro(self.home / "watchlist.db")
        radar: list[dict] = []
        radar_status = "UNKNOWN"
        if con is not None and _has_table(con, "upcoming_earnings"):
            cols = _cols(con, "upcoming_earnings")
            rows = _qall(con, "SELECT * FROM upcoming_earnings ORDER BY "
                              + ("earnings_date" if "earnings_date" in cols else "ticker") + " LIMIT 60")
            for r in rows:
                d = dict(r)
                edate = d.get("earnings_date") or d.get("report_date")
                radar.append({
                    "symbol": d.get("ticker") or d.get("symbol"),
                    "earnings_date": edate,
                    "session": d.get("session") or d.get("time_of_day"),
                    "window": self._earnings_window(edate),
                    "heads_up_sent": bool(d.get("heads_up_sent")),
                })
            radar_status = "ACTIVE" if radar else "ZERO_ACTIVITY"
        elif con is not None:
            radar_status = "ZERO_ACTIVITY"
        if con is not None:
            con.close()
        out["earnings_radar"] = {"status": radar_status, "source": "watchlist.db upcoming_earnings",
                                 "items": radar}

        # premarket watch candidates -- Task 102: now persisted by the
        # Experimental lane into ~/.talonx/premarket/premarket_state.db.
        out["premarket_watch"] = self._premarket_watch_block()
        # intelligence/event context that IS persisted (overnight SEC events)
        con = _ro(self.intel_ledger)
        ctx: list[dict] = []
        if con is not None and _has_table(con, "text_events"):
            cols = _cols(con, "text_events")
            tcol = next((c for c in ("accepted_at_utc", "accepted_at", "created_at", "filing_date") if c in cols), None)
            if tcol:
                rows = _qall(con, f"SELECT * FROM text_events ORDER BY {tcol} DESC LIMIT 15")
                for r in rows:
                    d = dict(r)
                    ctx.append({
                        "symbol": d.get("symbol") or d.get("ticker"),
                        "event_type": d.get("event_type") or d.get("form_type") or d.get("form"),
                        "accepted_at": d.get(tcol),
                    })
        if con is not None:
            con.close()
        out["event_context"] = {"status": "ACTIVE" if ctx else self.arm.intelligence().status.value,
                                "source": "ingestion_ledger.db text_events", "items": ctx}
        return out

    def _premarket_watch_block(self) -> dict[str, Any]:
        """Task 102 -- read the durable pre-market projection. Distinguishes
        ACTIVE / STALE / NO_SESSION_TODAY / NO_ACTIVE_PRODUCER / UNKNOWN; never
        fabricates a 0 (a missing volume feed reads NOT_AVAILABLE)."""
        db = self.exp / "premarket" / "premarket_state.db"
        source = "~/.talonx/experimental/premarket/premarket_state.db (PremarketStateStore)"
        if not db.exists():
            return {"status": "UNKNOWN", "source": source,
                    "note": "premarket_state.db not present (Experimental lane has not run since Task 102)"}
        try:
            from talonx_signals.premarket_store import PremarketStateStore

            store = PremarketStateStore(db, read_only=True)
            sess = store.current_session(now=self.now)
            events: dict[str, list[dict]] = {}
            counts: dict[str, int] = {}
            if sess.get("session_date"):
                counts = store.counts_for_session(sess["session_date"])
                raw = store.events_for_session(sess["session_date"], limit_per_kind=25)
                for kind, rows in raw.items():
                    events[kind] = [{
                        "watch_id": r["watch_id"], "symbol": r["symbol"], "kind": r["kind"],
                        "bias": r["bias"], "gap_pct": r["gap_pct"],
                        "relative_volume": r["relative_volume"] if r["relative_volume"] is not None else "NOT_AVAILABLE",
                        "reference_price": r["reference_price"], "prev_close": r["prev_close"],
                        "detail": r["detail"], "last_updated_at": r["last_updated_at"],
                        "external_eligible": bool(r["external_eligible"]),
                    } for r in rows]
            store.close()
        except Exception as exc:  # noqa: BLE001
            return {"status": "UNKNOWN", "source": source, "note": f"read error: {exc!r}"}

        exp_live = self.arm.experimental_producer().get("live")
        status = sess.get("status", "UNKNOWN")
        if status in ("NO_SESSION_TODAY",) and not exp_live:
            status = "NO_ACTIVE_PRODUCER"
        return {
            "status": status,
            "source": source,
            "session_date": sess.get("session_date"),
            "generated_at": sess.get("generated_at"),
            "last_updated_at": sess.get("last_updated_at"),
            "last_updated_age_seconds": sess.get("last_updated_age_seconds"),
            "coverage": {
                "configured": sess.get("watchlist_configured"),
                "active": sess.get("watchlist_active"),
                "covered": sess.get("watchlist_covered"),
            },
            "counts_by_family": counts,
            "events_by_family": events,
            "note": sess.get("note", ""),
            "external_eligible": False,
        }

    def _earnings_window(self, edate: str | None) -> str | None:
        if not edate:
            return None
        try:
            d = datetime.fromisoformat(str(edate)[:10]).date()
        except ValueError:
            return None
        delta = (d - self.now.date()).days
        if delta <= 0:
            return "T-0"
        if delta <= 2:
            return "T-2"
        if delta <= 7:
            return "T-7"
        return f"T-{delta}"

    # ------------------------------------------------------------------ #
    # ORIGINAL QUANT
    # ------------------------------------------------------------------ #
    def original_quant(self) -> dict[str, Any]:
        funnel = self.arm.quant_funnel()
        signals = self.arm.quant_signals()
        brain = self.arm.brain_reports()
        official = self.arm.official_alerts()
        orig_prod = self.arm.original_producer()

        # bar buffer / observed (quant.db bar_buffer -- "is it ticking")
        con = _ro(self.home / "quant.db")
        bars_observed = None
        rejection_rows: list[dict] = []
        if con is not None:
            if _has_table(con, "bar_buffer"):
                bars_observed = _q1(con, "SELECT COUNT(*) FROM bar_buffer") or 0
            if _has_table(con, "suppression_counts"):
                cols = _cols(con, "suppression_counts")
                dcol = "date" if "date" in cols else None
                today = self._today()
                if dcol:
                    rows = _qall(con, f"SELECT reason, SUM(count) AS n FROM suppression_counts "
                                      f"WHERE {dcol}=? GROUP BY reason", (today,))
                    seen = {r["reason"]: int(r["n"] or 0) for r in rows}
                else:
                    seen = {}
                total = sum(seen.values())
                ordered = list(CANONICAL_REJECTION_REASONS) + [r for r in seen if r not in CANONICAL_REJECTION_REASONS]
                for reason in ordered:
                    if reason in seen or reason in CANONICAL_REJECTION_REASONS:
                        n = seen.get(reason, 0)
                        rejection_rows.append({
                            "reason": reason, "count": n,
                            "pct": round(100.0 * n / total, 2) if total else 0.0,
                        })
            con.close()

        published = signals.values.get("published_proxy_alerts_today")
        suppressions_today = funnel.values.get("suppressions_today", 0)

        # the critical semantic rule
        if orig_prod["live"] and (published or 0) == 0 and (suppressions_today or 0) > 0:
            quant_state = "ACTIVE / NO SIGNALS PASSED"
        elif orig_prod["live"]:
            quant_state = "ACTIVE"
        else:
            quant_state = "NO_ACTIVE_PRODUCER"

        if orig_prod["live"] and (brain.values.get("reports_today") or 0) == 0 and (published or 0) == 0:
            brain_state = "ACTIVE / NO INPUT"
        elif orig_prod["live"]:
            brain_state = "ACTIVE"
        else:
            brain_state = brain.status.value

        return {
            "generated_at": self.now.isoformat(),
            "producer_live": orig_prod["live"],
            "thresholds": {"min_atr_pct": 0.25, "confluence_score_min": 2, "min_risk_reward_ratio": 1.5},
            "funnel": {
                "bars_observed_buffered": bars_observed,
                "suppressions_today": suppressions_today,
                "by_reason": rejection_rows,
                "published_quant_signals_today": published,
                "quant_to_brain_handoffs_today": brain.values.get("upstream_quant_signals_today"),
                "brain_reports_today": brain.values.get("reports_today"),
                "official_alerts_today": official.values.get("generated_today"),
                "official_alerts_all_time": official.values.get("generated_all_time"),
                "local_paper_trades_all_time": self._paper_trades_all_time(self.home / "paper_trading.db"),
            },
            "quant_state": quant_state,
            "quant_state_note": (
                "published=0 with suppressions>0 means the frozen gate ordering rejected every "
                "candidate -- Quant is running, nothing passed. NOT 'Quant inactive'."
            ),
            "brain_state": brain_state,
            "brain_state_note": "Brain reports 0 because 0 Quant signals were published today -- running and correctly idle, not broken.",
            "source_status": {
                "quant_funnel": funnel.status.value,
                "quant_signals": signals.status.value,
                "brain_reports": brain.status.value,
                "official_alerts": official.status.value,
            },
            "research_candidates_note": "Task 101 research candidates are NOT wired live and are NOT shown here as production signals.",
        }

    def _paper_trades_all_time(self, db: Path) -> int | None:
        con = _ro(db)
        if con is None:
            return None
        try:
            if _has_table(con, "trade_history"):
                return _q1(con, "SELECT COUNT(*) FROM trade_history")
            return None
        finally:
            con.close()

    # ------------------------------------------------------------------ #
    # VALIDATION  (Experimental V1 shadow -- INTERNAL ONLY)
    # ------------------------------------------------------------------ #
    def validation(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "label": "INTERNAL VALIDATION -- NOT OFFICIAL TRADING SIGNALS",
            "internal_only": True,
            "external_dispatchable": False,
            "no_send_action": "This dashboard exposes NO 'send Telegram' affordance for Experimental alerts.",
            "frozen_profile": {"min_atr_pct": 0.10, "confluence_score_min": 1, "min_risk_reward_ratio": 1.0},
        }
        exp = self.arm.experimental_alerts()
        exp_prod = self.arm.experimental_producer()
        out["experimental_state"] = "READY" if exp_prod["live"] else "DOWN"
        out["experimental_state_reason"] = exp_prod["reason"]
        out["by_family"] = exp.values.get("by_family", {})
        out["external_boundary"] = "BLOCKED -- structural (Task 100B Phase 6)"
        out["live_external_sends"] = 0
        out["legacy_bookkeeping_rows"] = exp.values.get("external_sends", 0)

        con = _ro(self.exp / "exp_alerts.db")
        directional: list[dict] = []
        gate = {"WOULD_PASS": 0, "WOULD_REJECT": 0, "OTHER": 0}
        direction = {"BULLISH": 0, "BEARISH": 0}
        reject_reasons: dict[str, int] = {}
        exp_trades: list[dict] = []
        if con is not None:
            if _has_table(con, "directional_alerts"):
                cols = _cols(con, "directional_alerts")
                tcol = next((c for c in ("bar_timestamp", "created_at", "generated_at") if c in cols), None)
                rows = _qall(con, f"SELECT * FROM directional_alerts ORDER BY {tcol} DESC LIMIT 200"
                             if tcol else "SELECT * FROM directional_alerts LIMIT 200")
                for r in rows:
                    d = dict(r)
                    gs = str(d.get("trade_gate_status") or "").upper()
                    if "WOULD_PASS" in gs:
                        gate["WOULD_PASS"] += 1
                    elif "WOULD_REJECT" in gs:
                        gate["WOULD_REJECT"] += 1
                        rr = d.get("trade_gate_reject_reason") or "UNSPECIFIED"
                        reject_reasons[rr] = reject_reasons.get(rr, 0) + 1
                    else:
                        gate["OTHER"] += 1
                    dr = str(d.get("direction") or "").upper().split(".")[-1]
                    if dr in direction:
                        direction[dr] += 1
                for r in rows[:25]:
                    d = dict(r)
                    directional.append({
                        "alert_id": d.get("alert_id"), "symbol": d.get("symbol"),
                        "direction": str(d.get("direction") or "").split(".")[-1],
                        "setup_type": d.get("setup_type"), "setup_score": d.get("setup_score"),
                        "session": d.get("session"), "price": d.get("price"),
                        "trade_gate_status": d.get("trade_gate_status"),
                        "trade_gate_reject_reason": d.get("trade_gate_reject_reason"),
                        "bar_timestamp": d.get("bar_timestamp"),
                    })
            if _has_table(con, "experimental_trades"):
                cols = _cols(con, "experimental_trades")
                tcol = next((c for c in ("opened_at", "created_at") if c in cols), None)
                rows = _qall(con, f"SELECT * FROM experimental_trades ORDER BY {tcol} DESC LIMIT 25"
                             if tcol else "SELECT * FROM experimental_trades LIMIT 25")
                for r in rows:
                    d = dict(r)
                    exp_trades.append({
                        "trade_id": d.get("trade_id"), "symbol": d.get("symbol"),
                        "side": d.get("side"), "entry": d.get("entry"), "exit": d.get("exit"),
                        "net_pnl": d.get("net_pnl"), "r_multiple": d.get("r_multiple"),
                        "opened_at": d.get("opened_at"), "closed_at": d.get("closed_at"),
                    })
            con.close()
        out["directional_recent"] = directional
        out["gate_breakdown"] = gate
        out["direction_breakdown"] = direction
        out["reject_reasons"] = [{"reason": k, "count": v} for k, v in
                                 sorted(reject_reasons.items(), key=lambda kv: -kv[1])]
        out["experimental_trades_recent"] = exp_trades

        # forward outcomes (Task 99G)
        out["forward_outcomes"] = self._forward_outcomes_block()

        # Original vs Experimental funnel comparison (informational)
        oq = self.original_quant()
        out["original_vs_experimental"] = {
            "note": "Informational funnel comparison. Validation-only. Not a profitability claim.",
            "original": {
                "thresholds": oq["thresholds"],
                "published_signals_today": oq["funnel"]["published_quant_signals_today"],
                "suppressions_today": oq["funnel"]["suppressions_today"],
            },
            "experimental": {
                "thresholds": out["frozen_profile"],
                "would_pass": gate["WOULD_PASS"],
                "would_reject": gate["WOULD_REJECT"],
                "directional_alerts_sampled": sum(gate.values()),
            },
        }
        return out

    def _forward_outcomes_block(self) -> dict[str, Any]:
        con = _ro(self.exp / "forward_outcomes.db")
        if con is None or not _has_table(con, "forward_observations"):
            if con:
                con.close()
            return {"status": self.arm.experimental_producer().get("live") and "ZERO_ACTIVITY" or "NO_ACTIVE_PRODUCER",
                    "source": "forward_outcomes.db", "summary": {}, "recent": []}
        cols = _cols(con, "forward_observations")
        rows = _qall(con, "SELECT * FROM forward_observations ORDER BY alert_ts DESC LIMIT 200")
        summ = {"total": len(rows), "pending": 0, "resolved_30m": 0, "resolved_60m": 0,
                "resolved_eod": 0, "resolved_1d": 0}
        recent = []
        for r in rows:
            d = dict(r)
            if str(d.get("status")) != "COMPLETE":
                summ["pending"] += 1
            for h, key in (("r_30m", "resolved_30m"), ("r_60m", "resolved_60m"),
                           ("r_eod", "resolved_eod"), ("r_1d", "resolved_1d")):
                if d.get(h) is not None:
                    summ[key] += 1
        for r in rows[:25]:
            d = dict(r)
            recent.append({
                "obs_id": d.get("obs_id"), "symbol": d.get("symbol"),
                "direction": d.get("direction"), "kind": d.get("kind"),
                "reference_price": d.get("reference_price"),
                "mfe": d.get("mfe"), "mae": d.get("mae"),
                "r_30m": d.get("r_30m"), "r_60m": d.get("r_60m"),
                "r_eod": d.get("r_eod"), "r_1d": d.get("r_1d"),
                "status": d.get("status"), "alert_ts": d.get("alert_ts"),
            })
        con.close()
        return {"status": "ACTIVE" if rows else "ZERO_ACTIVITY",
                "source": "forward_outcomes.db (Task 99G live wiring)",
                "summary": summ, "recent": recent}

    # ------------------------------------------------------------------ #
    # INTELLIGENCE  (summary + deep-link to :8760)
    # ------------------------------------------------------------------ #
    def intelligence(self) -> dict[str, Any]:
        da = self.arm.intelligence()
        out: dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "descriptive_only": True,
            "disclaimer": "Descriptive event/risk intelligence. No forward-return or directional claim.",
            "deep_link": _DEEP_LINK_8760,
            "status": da.status.value,
            "authoritative_source": da.authoritative_source,
            "note": da.note,
            "counts": {k: v for k, v in (da.values or {}).items() if k.endswith("_rows")},
            "newest_event": (da.values or {}).get("newest_event"),
            "producer": self.arm.intelligence_producer(),
        }
        con = _ro(self.intel_ledger)
        latest: list[dict] = []
        significance: list[dict] = []
        insider: list[dict] = []
        if con is not None:
            if _has_table(con, "text_events"):
                cols = _cols(con, "text_events")
                tcol = next((c for c in ("accepted_at_utc", "accepted_at", "created_at") if c in cols), None)
                order = f"ORDER BY {tcol} DESC" if tcol else ""
                for r in _qall(con, f"SELECT * FROM text_events {order} LIMIT 20"):
                    d = dict(r)
                    latest.append({
                        "event_id": d.get("event_id"), "symbol": d.get("symbol") or d.get("ticker"),
                        "event_type": d.get("event_type") or d.get("form_type") or d.get("form"),
                        "accepted_at": d.get(tcol) if tcol else None,
                    })
            if _has_table(con, "event_significance"):
                cols = _cols(con, "event_significance")
                scol = next((c for c in ("score", "significance_score") if c in cols), None)
                bcol = next((c for c in ("band", "significance_band") if c in cols), None)
                order = f"ORDER BY {scol} DESC" if scol else ""
                for r in _qall(con, f"SELECT * FROM event_significance {order} LIMIT 15"):
                    d = dict(r)
                    significance.append({
                        "event_id": d.get("event_id"),
                        "band": d.get(bcol) if bcol else None,
                        "score": d.get(scol) if scol else None,
                    })
            # Task 117 Section 4: intelligence-card DELIVERY health -- ingestion,
            # queued, sending/ambiguous, sent, failed, expired shown SEPARATELY.
            # A healthy poll loop does not imply anything was delivered.
            if _has_table(con, "intelligence_delivery"):
                by_state = {r["state"]: r["c"] for r in _qall(
                    con, "SELECT state, COUNT(*) c FROM intelligence_delivery GROUP BY state")}
                today = self._today()
                sent_today = _q1(
                    con, "SELECT COUNT(*) FROM intelligence_delivery "
                    "WHERE state='SENT' AND substr(sent_at_utc,1,10)=?", (today,)) or 0
                # Task 118A P3: sent_today counts CARD ROWS -- a DIGEST batch
                # marks every aggregated card row SENT under one shared
                # attempt_id (the digest_id, pipeline.py::process_digest),
                # so N cards in one digest is N rows but ONE actual Telegram
                # message. messages_sent_today counts the real message
                # count: every IMMEDIATE row is its own message; every
                # DIGEST attempt_id counts once regardless of how many
                # cards it aggregated.
                messages_sent_today = _q1(
                    con,
                    "SELECT COUNT(DISTINCT CASE WHEN route='IMMEDIATE' THEN delivery_id "
                    "ELSE COALESCE(attempt_id, delivery_id) END) FROM intelligence_delivery "
                    "WHERE state='SENT' AND substr(sent_at_utc,1,10)=?", (today,)) or 0
                last_sent = _q1(
                    con, "SELECT MAX(sent_at_utc) FROM intelligence_delivery WHERE state='SENT'")
                last_digest = None
                try:
                    r = con.execute(
                        "SELECT value FROM schema_meta WHERE key='last_digest_sent_utc'").fetchone()
                    last_digest = r[0] if r else None
                except Exception:  # noqa: BLE001
                    pass
                pending = int(by_state.get("PENDING", 0))
                out["card_delivery"] = {
                    "by_state": {
                        "PENDING": pending,
                        "IN_FLIGHT": int(by_state.get("IN_FLIGHT", 0)),
                        "SENT": int(by_state.get("SENT", 0)),
                        "AMBIGUOUS": int(by_state.get("AMBIGUOUS", 0)),
                        "FAILED": int(by_state.get("FAILED", 0)),
                        "EXPIRED": int(by_state.get("EXPIRED", 0)),
                        "SUPPRESSED": int(by_state.get("SUPPRESSED", 0)),
                    },
                    "sent_today": sent_today,
                    "messages_sent_today": messages_sent_today,
                    "last_card_sent_utc": last_sent,
                    "last_digest_sent_utc": last_digest,
                    "queued_not_sent": pending + int(by_state.get("IN_FLIGHT", 0)),
                    "note": ("cards QUEUED is not cards SENT. 0 SENT with a healthy poll "
                             "loop = delivery disabled or transport not configured -- see "
                             "the runner's per-cycle delivery summary. sent_today counts CARD "
                             "ROWS; a DIGEST aggregates several cards into ONE Telegram message "
                             "-- see messages_sent_today for the actual message count."),
                }
            con.close()
        out["latest_events"] = latest
        out["significance_ranked"] = significance
        out["insider_recent"] = insider
        out["deep_links"] = {
            "today": f"{_DEEP_LINK_8760}/",
            "watchlist": f"{_DEEP_LINK_8760}/watchlist",
            "filings": f"{_DEEP_LINK_8760}/filings",
            "evidence": f"{_DEEP_LINK_8760}/evidence",
        }
        return out

    # ------------------------------------------------------------------ #
    # PAPER / EOD
    # ------------------------------------------------------------------ #
    def _official_telegram_last_send(self) -> dict[str, Any]:
        """Last actual send + ack across EVERY official Telegram domain
        (intraday alerts, long-term alerts, earnings heads-up), unioned from
        the durable stores -- not just one table."""
        out: dict[str, Any] = {}
        con = _ro(self.home / "dispatch_audit.db")
        if con is not None:
            try:
                if _has_table(con, "alerts"):
                    out["intraday_alert"] = _q1(
                        con, "SELECT MAX(telegram_sent_at) FROM alerts WHERE telegram_sent=1")
                if _has_table(con, "long_term_alerts"):
                    r = con.execute(
                        "SELECT ticker, telegram_sent_at FROM long_term_alerts "
                        "WHERE telegram_sent=1 ORDER BY telegram_sent_at DESC LIMIT 1").fetchone()
                    out["long_term_alert"] = ({"ticker": r[0], "at": r[1]} if r else None)
                if _has_table(con, "last_telegram_push"):
                    for hz in ("intraday", "long_term", "earnings_heads_up"):
                        r = con.execute(
                            "SELECT MAX(pushed_at) FROM last_telegram_push WHERE horizon=?", (hz,)
                        ).fetchone()
                        out[f"last_push_{hz}"] = r[0] if r else None
            finally:
                con.close()
        out["note"] = ("API-confirmed send timestamps only; message ids are stored per row "
                       "where the transport returns them; human RECEIPT is never asserted here.")
        return out

    def paper_eod(self) -> dict[str, Any]:
        """Task 100B/100C base + Task 119A: the ONE paper-portfolios-and-
        reconciliation destination. Task 119 originally added a second,
        separate "Paper Performance" tab with richer per-lane P&L/equity/
        reconciliation data alongside this section's pre-existing thin
        open-positions/cash summary -- a duplicate navigation destination
        showing overlapping numbers. That tab is retired; its data (via
        talonx_ops.paper_performance.build_paper_performance -- unchanged,
        still the one accounting implementation) is folded in HERE, under
        each lane's existing block as a nested "performance" key, so there
        is exactly one place a user reads paper-portfolio state and it is
        never split into two cards that could show inconsistent totals.
        Every pre-existing top-level key on this method is BYTE-UNCHANGED
        (back-compat for any existing caller) -- only "performance" is new.
        """
        op = self.arm.original_paper()
        ep = self.arm.experimental_paper()
        piv = self.arm.piv()
        eod = self.arm.eod_reconciliation()
        perf = self.paper_performance()
        lanes = perf.get("lanes", {})
        return {
            "generated_at": self.now.isoformat(),
            "separation_note": "Original / Experimental / PIV paper are SEPARATE ledgers -- never one merged positions count.",
            "official_telegram_last_send": self._official_telegram_last_send(),
            "session_date": perf.get("session_date"),
            "regular_session_close_utc": perf.get("regular_session_close_utc"),
            "original_local_paper": {
                "attribution": "ORIGINAL / local-only (no broker)",
                "status": op.status.value,
                "open_positions": op.values.get("open_positions"),
                "trades_all_time": op.values.get("trades_all_time"),
                "current_cash": op.values.get("current_cash"),
                "note": op.note,
                "performance": lanes.get("original"),
            },
            "experimental_validation_paper": {
                "attribution": "EXPERIMENTAL / validation-only, simulated, no real capital",
                "internal_only": True,
                "status": ep.status.value,
                "open_positions": ep.values.get("open_positions"),
                "trades_all_time": ep.values.get("trades_all_time"),
                "current_cash": ep.values.get("current_cash"),
                "note": ep.note,
                "performance": lanes.get("experimental"),
            },
            "piv_alpaca_paper": {
                "attribution": "PIV / Alpaca PAPER (independent; structurally cannot route real capital)",
                "status": piv.status.value,
                "note": piv.note,
                "positions": "NOT_CHECKED",
                "orders": "NOT_CHECKED",
                "checked": False,
                # Task 119A A2: an inactive/unconfigured PIV is its own,
                # independent fact -- it must never read as (or be caused
                # by) a failure of Original/Experimental local paper
                # accounting, which are checked above and are unaffected
                # by PIV's state either way.
                "clarification": ("PIV is a separate, independent paper-trading subsystem "
                                  "(Alpaca sandbox). NOT_CHECKED here means no network read was "
                                  "performed by this read-only surface -- it does NOT mean, and "
                                  "must not be read as, a failure of Original or Experimental "
                                  "local paper accounting, which are unaffected by PIV's state."),
            },
            "eod_reconciliation": {
                "status": eod.status.value,
                "authoritative_source": eod.authoritative_source,
                "values": eod.values,
                "last_update": eod.last_update,
                "note": eod.note,
            },
            # V2's own richer accounting (equity/reconciliation/cost breakdown)
            # is folded into its ALREADY-existing single destination --
            # v2_active_strategy()'s "$300,000 campaign ledger" card -- not
            # duplicated here too (V2 never had a paper_eod entry before
            # Task 119, and this method must not create a second one).
            "intelligence_note": (lanes.get("intelligence") or {}).get("note"),
        }

    # ------------------------------------------------------------------ #
    # ACTIVE STRATEGY -- V2 (INSIDER_BUY_CLUSTER_V2)  [Task 112]
    # Read-only over v2_lane.db + the V2 service status file.  V2 is an
    # ACTIVE ORIGINAL-flow paper strategy, NOT Experimental -- it is
    # surfaced under its own section, never merged into validation.
    # ------------------------------------------------------------------ #
    def v2_active_strategy(self) -> dict[str, Any]:
        import json as _json
        import os as _os

        # V2 campaign ledger: env override, else the repo-root v2_lane.db
        # (the frozen operational location), else the ~/.talonx fallback.
        _repo_root = Path(__file__).resolve().parents[1]
        db = (_os.environ.get("TALONX_V2_DB_PATH")
              or (str(_repo_root / "v2_lane.db") if (_repo_root / "v2_lane.db").exists()
                  else str(self.home / "v2_lane.db")))
        status_path = (_os.environ.get("TALONX_V2_STATUS_PATH")
                       or (str(_repo_root / "v2_service_status.json")
                           if (_repo_root / "v2_service_status.json").exists()
                           else str(self.home / "v2_service_status.json")))
        out: dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "panel": "Active V2 -- INSIDER_BUY_CLUSTER_V2@1",
            "role": "ACTIVE V2 (current prospective candidate, Original-flow paper)",
            "not_experimental": True,
            "strategy_version": "INSIDER_BUY_CLUSTER_V2@1",
            "status_label": "PAPER_CANDIDATE",
            "v1_baseline_available": True,
            "v1_selectable": True,
            "v2_selectable": True,
            "real_capital": False,
            "shorts": False,
            "eod_forced_flatten": False,
            "eod_auto_close": "OFF",
            "hold_trading_sessions": 10,
        }
        # service heartbeat -- SERVICE HEALTH is distinct from data state and
        # business activity (Task 114 A4).
        try:
            s = _json.loads(open(status_path).read())
            age = _age_seconds(s.get("heartbeat_utc"), self.now)
            ttl = float(s.get("heartbeat_ttl_s", 180))
            if age is None:
                health = "DOWN"
            elif age < ttl:
                health = "HEALTHY"
            elif age < ttl * 3:
                health = "DEGRADED"
            else:
                health = "DOWN"
            out["health"] = health
            out["service"] = {
                # keep the legacy key for back-compat, but drive it from `health`
                "status": "ACTIVE" if health == "HEALTHY" else (
                    "DEGRADED" if health == "DEGRADED" else "NO_ACTIVE_PRODUCER"),
                "health": health,
                "active_profile": s.get("active_profile"),
                "strategy_version": s.get("strategy_version"),
                "form4_source": s.get("form4_source"),
                "form4_records_seen": s.get("form4_records_seen"),
                "heartbeat_age_s": round(age, 1) if age is not None else None,
                "heartbeat_ttl_s": ttl,
                "heartbeat_kind": s.get("heartbeat_kind"),
                "tick": s.get("tick"),
                "last_tick_utc": s.get("last_tick_utc"),
                "as_of": s.get("as_of"),
                "cash": s.get("cash"),
                "open_positions": s.get("open_positions"),
                "exit_unresolved": s.get("exit_unresolved", []),
                "eod_forced_flatten": s.get("eod_forced_flatten", False),
                # Task 117 overnight: pre-open intents + durable alert outbox
                "entry_intents_created_this_tick": s.get("entry_intents_created_this_tick"),
                "pending_entry_intents": s.get("pending_entry_intents", []),
                "alert_outbox": s.get("alert_outbox"),
                "last_delivery": s.get("last_delivery"),
                "delivery_enabled": s.get("delivery_enabled"),
            }
        except OSError:
            # Task 117 Phase 0 L1: a just-started companion has no status file
            # yet -- distinguish a bounded STARTING warmup from a crashed DOWN.
            health = "DOWN"
            note = "no v2 service status file"
            try:
                from talonx_ops.prospective.checkpoint import _session_started_utc, startup_grace
                g = startup_grace({}, self.now, _session_started_utc(self.now))
                if g["state"] == "STARTING":
                    health, note = "STARTING", f"bounded warmup; deadline {g.get('deadline_utc')}"
                elif g["state"] == "STARTUP_FAILED":
                    health, note = "STARTUP_FAILED", g["reason"]
            except Exception:  # noqa: BLE001
                pass
            out["health"] = health
            out["service"] = {"status": "NO_ACTIVE_PRODUCER" if health != "STARTING" else "STARTING",
                              "health": health, "note": note}
        except Exception as exc:  # noqa: BLE001
            out["health"] = "UNKNOWN"
            out["service"] = {"status": "UNKNOWN", "health": "UNKNOWN",
                              "note": f"{type(exc).__name__}: {exc}"}
        # ledger
        con = _ro(Path(db))
        if con is None:
            out["ledger"] = {"status": "NO_ACTIVE_PRODUCER", "note": "no v2_lane.db"}
        else:
            try:
                if not _has_table(con, "positions"):
                    out["ledger"] = {"status": "ZERO_ACTIVITY", "note": "no positions table"}
                else:
                    opens = _qall(con, "SELECT symbol, episode_id, entry_session, target_exit_session, "
                                       "entry_price, shares, position_cost, opened_at FROM positions "
                                       "WHERE status='OPEN' ORDER BY entry_session")
                    closed = _qall(con, "SELECT realized_pnl_usd FROM positions WHERE status='CLOSED'")
                    unresolved = _q1(con, "SELECT COUNT(*) FROM positions WHERE status='EXIT_UNRESOLVED'") or 0
                    realized = round(sum((r["realized_pnl_usd"] or 0.0) for r in closed), 2)
                    n_buys = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='BUY'") or 0
                    n_sells = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='SELL'") or 0
                    cash = _q1(con, "SELECT cash FROM portfolio WHERE id=1")
                    open_cost = sum((r["position_cost"] or 0.0) for r in opens)
                    out["ledger"] = {
                        "status": "ACTIVE" if (opens or closed) else "ZERO_ACTIVITY",
                        "open_positions": [self._v2_position_lifecycle(dict(r), now=self.now) for r in opens],
                        "n_open": len(opens),
                        "closed_positions": len(closed),
                        "exit_unresolved": int(unresolved),
                        "buys": int(n_buys),
                        "sells": int(n_sells),
                        "realized_pnl_usd": realized,
                        "starting_campaign_cash": 300_000.0,
                        "cash": cash,
                        "allocated_capital": round(open_cost, 2),
                        "available_capital": None if cash is None else round(cash, 2),
                        "capacity": f"{len(opens)}/20",
                    }
                    # PQ-2A: read-only corporate-action visibility (symbol, action
                    # type, effective session, ratio, adjustment status).  Never
                    # mutates the ledger; absent table -> NONE.
                    try:
                        from talonx_v2.corporate_actions import trail_rows
                        ca = [{"symbol": t["symbol"], "action_type": t["kind"], "ex_date": t["ex_date"],
                               "ratio": (f'{t["ratio_num"]}/{t["ratio_den"]}' if t["kind"] != "BLOCK" else None),
                               "adjustment_status": t["status"], "shares_before": t["shares_before"],
                               "shares_after": t["shares_after"], "detail": t["detail"]}
                              for t in trail_rows(con)]
                        blocked = [c for c in ca if str(c["adjustment_status"]).startswith("BLOCKED_")]
                        out["ledger"]["corporate_actions"] = {
                            "status": ("BLOCKED" if blocked else
                                       "ADJUSTED" if any(c["adjustment_status"] == "APPLIED" for c in ca)
                                       else "NONE" if not ca else "OBSERVED"),
                            "items": ca}
                    except Exception as exc:  # noqa: BLE001
                        out["ledger"]["corporate_actions"] = {"status": "UNKNOWN",
                                                              "note": f"{type(exc).__name__}: {exc}"}
                    # PQ-2A closure (TOTAL RETURN): read-only dividend receivable/credit view.
                    # `realized_pnl_usd` above stays PRICE P&L; total return adds credited dividends.
                    try:
                        from talonx_v2 import dividends as _dv
                        drows = _dv.rows(con)
                        d_cred = round(sum(d["amount_usd"] for d in drows if d["state"] == "CREDITED"), 2)
                        d_acc = round(sum(d["amount_usd"] for d in drows if d["state"] == "ACCRUED"), 2)
                        out["ledger"]["dividend_pnl_usd"] = d_cred
                        out["ledger"]["total_return_pnl_usd"] = round(realized + d_cred, 2)
                        out["ledger"]["dividends"] = {
                            "status": ("NONE" if not drows else "RECEIVABLE" if d_acc else "CREDITED"),
                            "credited_usd": d_cred, "accrued_receivable_usd": d_acc,
                            "items": [{"symbol": d["symbol"], "ex_date": d["ex_date"],
                                       "payable_date": d["payable_date"], "rate_per_share": d["rate"],
                                       "eligible_quantity": d["eligible_qty"], "total_usd": d["amount_usd"],
                                       "state": d["state"], "position_id": d["position_id"],
                                       "provenance": d["provenance_json"], "detail": d["detail"]}
                                      for d in drows]}
                    except Exception as exc:  # noqa: BLE001
                        out["ledger"]["dividends"] = {"status": "UNKNOWN",
                                                      "note": f"{type(exc).__name__}: {exc}"}
                    # Task 119A A1: fold V2's richer accounting (equity,
                    # arithmetic reconciliation, cost-treatment breakdown,
                    # marked open-position value) into this SAME ledger
                    # block -- V2's one existing destination -- instead of
                    # a second "Paper Performance" tab duplicating it.
                    try:
                        from talonx_ops.paper_performance import build_v2_paper_performance
                        out["ledger"]["performance"] = build_v2_paper_performance(
                            Path(db), home=self.home, now=self.now)
                    except Exception as exc:  # noqa: BLE001
                        out["ledger"]["performance"] = {"status": "UNKNOWN",
                                                        "note": f"{type(exc).__name__}: {exc}"}
            finally:
                con.close()

        # ---- funnel + EOD state + data/activity + campaign (Task 114 A3/A4/A5) ----
        try:
            from talonx_ops.prospective.funnel import build_funnel
            out["funnel"] = build_funnel(db_path=db, as_of=self.now.date())
        except Exception as exc:  # noqa: BLE001
            out["funnel"] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        try:
            from talonx_ops.prospective.checkpoint import campaign_day, eod_state
            out["eod"] = self._v2_eod_state(eod_state(self.now), now=self.now)
            out["campaign"] = {
                "start_date": "2026-09-08", "campaign_day": campaign_day(self.now),
                "day1_outcome": "NO_NATURAL_V2_SIGNAL",
                "natural_opportunities": out.get("funnel", {}).get("clusters", {}).get(
                    "fresh_eligible_clusters", 0),
                "trades_opened": out.get("ledger", {}).get("buys", 0),
                "trades_closed": out.get("ledger", {}).get("sells", 0),
                "prospective_sample_status": "SAMPLE_INSUFFICIENT",
                "note": "prospective validation -- no profitability inference from zero-trade days",
            }
        except Exception:  # noqa: BLE001
            out["eod"] = {"state": "UNKNOWN"}

        # ---- source & pricing readiness -- from the V2 service status file
        #      (Task 117 Phase 0 Phase 5): a fresh heartbeat is NOT proof of a
        #      current/complete filing read, and NO_OPPORTUNITIES must be
        #      distinct from DATA_UNAVAILABLE / INCOMPLETE_COVERAGE.
        svc_status: dict[str, Any] = {}
        try:
            svc_status = _json.loads(open(status_path).read())
        except Exception:  # noqa: BLE001
            pass
        src = svc_status.get("source", {}) or {}
        # Task 117 Phase 0 S1: the V2 service's `last_ok_utc` is a *DB-read*
        # timestamp -- proof the InsiderStore was readable, NOT proof the upstream
        # SEC poll is current.  Upstream-poll freshness lives in
        # ingestion_ledger.db `intel_processing_log`.  Surface BOTH, un-conflated.
        poll_last_ok, poll_age = None, None
        try:
            _c = _ro(Path(self.intel_ledger))
            if _c is not None:
                try:
                    poll_last_ok = _q1(_c, "SELECT MAX(at_utc) FROM intel_processing_log")
                    poll_age = _age_seconds(poll_last_ok, self.now)
                finally:
                    _c.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            from talonx_ops.prospective import V2_FINGERPRINT_EXPECTED as _V2FP
        except Exception:  # noqa: BLE001
            _V2FP = "e2acf6454789217e"  # RI-1: fallback kept in sync with the live constant
        readiness = {
            "form4_source_configured": svc_status.get("form4_source"),
            "form4_source_actual": src.get("actual"),
            "form4_source_ok": src.get("ok"),
            "form4_source_degraded": src.get("degraded"),
            "form4_last_ok_utc": src.get("last_ok_utc"),          # kept for back-compat
            "source_db_read_last_ok_utc": src.get("last_ok_utc"),  # explicit: DB read
            "source_db_read_age_s": _age_seconds(src.get("last_ok_utc"), self.now),
            "source_poll_last_ok_utc": poll_last_ok,               # explicit: upstream poll
            "source_poll_age_s": None if poll_age is None else round(poll_age, 1),
            "form4_records_seen": svc_status.get("form4_records_seen"),
            "pricing_mode": svc_status.get("pricing_mode"),
            "pricing_adapter": svc_status.get("pricing_adapter"),
            "pricing_unavailable_recent": svc_status.get("pricing_unavailable_recent", []),
            "svc_data_state": svc_status.get("data_state"),
            "v2_fingerprint_frozen": _V2FP,
            # Task 117 Phase 0 S4: an explicit coverage denominator + source.
            "coverage": {
                "source": "InsiderStore @ ~/.talonx/ingestion_ledger.db "
                          "(fed by talonx_ingest.intelligence.service poll)",
                "issuers_evaluated": svc_status.get("form4_records_seen"),
                "eligible_universe_denominator": "UNKNOWN -- frozen membership-OR-liquidity "
                "universe not fully materialised; scope decision pending "
                "(UNIVERSE_CONTRACT_DECISION_REQUIRED)",
                "completeness": "INCOMPLETE",
                "blind_spots": ["S&P MidCap 400 (no PIT membership file)",
                                "SEC ~1-day daily-index lag",
                                "non-index liquid names not polled"],
            },
        }
        out["readiness"] = readiness

        fn = out.get("funnel", {})
        # precedence: service DATA_UNAVAILABLE > funnel form4_error > CURRENT
        if readiness.get("svc_data_state") == "DATA_UNAVAILABLE" or src.get("ok") is False:
            out["data_state"] = "DATA_UNAVAILABLE"
        elif fn.get("available"):
            out["data_state"] = "CURRENT"
        elif fn.get("form4_error"):
            out["data_state"] = "DATA_UNAVAILABLE"
        else:
            out["data_state"] = "UNKNOWN"

        ldg = out.get("ledger", {})
        if out["data_state"] == "DATA_UNAVAILABLE":
            out["activity"] = "DATA_UNAVAILABLE"
        elif ldg.get("n_open", 0) > 0:
            out["activity"] = "POSITION_OPEN"
        elif ldg.get("buys", 0) > 0:
            out["activity"] = "ACTIVITY"
        elif readiness.get("pricing_unavailable_recent"):
            out["activity"] = "INCOMPLETE_COVERAGE"
        else:
            out["activity"] = "NO_OPPORTUNITIES"

        # Task 117 Phase 0 S1/S4/D2: coverage- and pricing-health are reported
        # INDEPENDENTLY of `activity` -- an open position must NOT mask a degraded
        # source or pricing feed behind a single precedence label.
        poll_stale = (readiness["source_poll_age_s"] is not None
                      and readiness["source_poll_age_s"] > 6 * 3600)
        if src.get("ok") is False or readiness.get("svc_data_state") == "DATA_UNAVAILABLE":
            out["coverage_state"] = "DATA_UNAVAILABLE"
        elif poll_stale:
            out["coverage_state"] = "DATA_STALE"
        else:
            out["coverage_state"] = "INCOMPLETE_COVERAGE"   # until the universe decision
        out["pricing_state"] = ("DEGRADED" if readiness.get("pricing_unavailable_recent")
                                else "READY")
        from talonx_ops.operator_read import operator_snapshot, redact_output
        operator = operator_snapshot(Path(db), now=self.now, status=svc_status,
                                     intel_path=self.home / "ingestion_ledger.db")
        out["operator"] = operator
        account = operator["account"]
        out["ledger"].update(
            cash=account["settled_cash"],
            realized_pnl_usd=account["realized_pnl"],
            starting_campaign_cash=account["starting_capital"],
            reserved_capital=account["reserved_capital"],
            available_capital=account["available_capital"],
            allocated_capital=account["allocated_capital"],
            capacity=f"{account['capacity_used']}/{account['capacity_limit']}",
            unresolved_positions=operator["positions"]["EXIT_UNRESOLVED"],
        )
        out["service"]["runtime_state"] = operator["runtime"]["state"]
        # Final-acceptance fix: an UNKNOWN process probe (no probe supplied) must not MASK the more
        # specific DOWN / STARTING / STARTUP_FAILED health derived from the status file + startup grace --
        # otherwise a companion that never started reads as merely "UNKNOWN".  STOPPED / DEGRADED (positive
        # evidence) still override as before.
        _specific = out.get("health") in ("DOWN", "STARTING", "STARTUP_FAILED")
        if operator["runtime"]["state"] in ("STOPPED", "UNKNOWN", "DEGRADED") and not (
                operator["runtime"]["state"] == "UNKNOWN" and _specific):
            out["health"] = operator["runtime"]["state"]
            out["service"]["health"] = out["health"]
            out["service"]["status"] = out["health"]
        return redact_output(out)

    # ------------------------------------------------------------------ #
    # BROAD DISCOVERY -- Task 131 Directive 4/5, extended for the SPA
    # Discovery Dashboard (Concurrent Admission Fix / SPA Acceptance
    # task). A SEPARATE, ADDITIVE metric panel for the 626-name Discovery
    # Universe v1 engine. Reads the SAME v2_lane.db as v2_active_
    # strategy() above, read-only, and classifies each symbol found there
    # by origin (PRODUCT_WATCHLIST vs BROAD_DISCOVERY) using the SAME
    # frozen manifest + resolved active watchlist every other symbol-
    # scope decision in this program uses -- it does NOT read any live
    # process's in-memory state. v2_active_strategy() above is UNCHANGED,
    # so the original 39-name watchlist view is preserved exactly as it
    # was.
    #
    # This extension adds, all read-only and additive:
    #   - universe_coverage: n_resolved/n_unresolved read LIVE from the
    #     manifest file's own cik_manifest key -- never a hardcoded
    #     literal in this code, and explicitly labelled as a STATIC,
    #     versioned research snapshot, never "historical identity
    #     verification" of a symbol's CURRENT CIK.
    #   - admission_policy: the REAL, current TALONX_V2_DURABLE_STORE_
    #     ENABLED state (GATED vs PERMISSIVE), not assumed.
    #   - source_health: reused directly from v2_active_strategy()'s own
    #     readiness computation -- the SAME source/process serves both
    #     views, so this is not a second, independently-observed feed.
    #   - dashboard_refresh_utc vs upstream_data_as_of_utc: kept
    #     explicitly distinct (this read's own timestamp vs the
    #     upstream source's last successful observation).
    #   - discovery_funnel: real episode dispositions + intent statuses
    #     for broad-discovery-only symbols, classified into DISCOVERED /
    #     PENDING / REJECTED / EXPIRED / FILLED (see
    #     _classify_discovery_candidate below) -- an honest UNCLASSIFIED
    #     bucket catches anything this mapping does not recognize, so a
    #     future new disposition string is never silently mis-bucketed.
    #   - action_queue: PENDING entry intents + recent alert-outbox rows
    #     for broad-discovery-only symbols, with outbox `state` shown
    #     as-is (PENDING/RETRY = queued, NOT delivered; only SENT
    #     confirms delivery).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _classify_discovery_candidate(ep: dict, intent: dict | None) -> dict[str, Any]:
        """Merge one episode's disposition with its (optional) entry
        intent into ONE discovery-candidate row, bucketed into exactly
        one of DISCOVERED / PENDING / REJECTED / EXPIRED / FILLED /
        UNCLASSIFIED. Every real disposition/intent-status string this
        program's V2 service actually writes (talonx_v2/service.py,
        talonx_v2/paper.py) is accounted for; anything unrecognized
        falls into UNCLASSIFIED rather than being silently misfiled into
        one of the five real buckets."""
        disposition = ep.get("disposition") or ""
        intent_status = (intent or {}).get("status")
        filled = {"ENTERED", "FILLED"}
        rejected = {"REJECTED_CAPACITY_EXCEEDED", "REJECTED_TEMPORAL_BOUNDARY_VIOLATION",
                   "SKIPPED_TEMPORAL_BOUNDARY_VIOLATION", "SKIPPED_ADMISSION_DEADLINE_PASSED",
                   "SKIPPED_NO_PRIOR_INTENT"}
        expired = {"EXPIRED_STALE", "FAILED_NO_MARKET_DATA", "SKIPPED_ENTRY_STALE"}
        if disposition in filled or intent_status in filled:
            bucket = "FILLED"
        elif intent_status == "PENDING":
            bucket = "PENDING"
        elif disposition in rejected or intent_status in rejected:
            bucket = "REJECTED"
        elif disposition in expired or intent_status in expired:
            bucket = "EXPIRED"
        elif disposition:
            bucket = "DISCOVERED"
        else:
            bucket = "UNCLASSIFIED"
        reason = ep.get("detail") or (intent or {}).get("detail") or disposition or "no detail recorded"
        return {
            "symbol": ep.get("symbol"), "episode_id": ep.get("episode_id"),
            "event_time": ep.get("updated_at"),
            "target_entry_session": ep.get("eligible_entry_session"),
            "disposition": disposition or None, "intent_status": intent_status,
            "status_bucket": bucket, "reason": reason,
        }

    def v2_broad_discovery(self) -> dict[str, Any]:
        import os as _os

        _repo_root = Path(__file__).resolve().parents[1]
        db = (_os.environ.get("TALONX_V2_DB_PATH")
              or (str(_repo_root / "v2_lane.db") if (_repo_root / "v2_lane.db").exists()
                  else str(self.home / "v2_lane.db")))
        manifest_path = (_repo_root / "talonx_ingest" / "intelligence" / "service" / "data"
                        / "discovery_universe_v1_626.json")

        out: dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "panel": "Broad Discovery -- Discovery Universe v1 (626 names)",
            "role": "ADDITIVE research-validated coverage panel, separate from the "
                   "primary 39-name watchlist view above",
            "not_a_replacement_for_the_39_name_view": True,
        }

        import json as _json

        universe: set[str] = set()
        manifest_data: dict[str, Any] = {}
        try:
            if manifest_path.is_file():
                manifest_data = _json.loads(manifest_path.read_text())
                universe = {s.strip().upper() for s in manifest_data.get("symbols", []) if s.strip()}
        except Exception as exc:  # noqa: BLE001
            out["manifest_error"] = f"{type(exc).__name__}: {exc}"
        out["universe_n"] = len(universe)
        out["manifest_path"] = str(manifest_path)

        # universe_coverage: read LIVE from the manifest file's own
        # cik_manifest key every call -- these are never literals baked
        # into this code. Explicitly labelled a STATIC, versioned
        # research-population snapshot (Task 131 Directive 6): a name
        # counted "unresolved" here can still have a perfectly valid,
        # CURRENT CIK -- this is NOT a live identity check and must never
        # be read as one.
        cm = manifest_data.get("cik_manifest") if manifest_data else None
        if cm:
            n_res, n_unres = cm.get("n_resolved"), cm.get("n_unresolved")
            total = (n_res or 0) + (n_unres or 0)
            out["universe_coverage"] = {
                "manifest_version": cm.get("manifest_version"),
                "n_resolved": n_res, "n_unresolved": n_unres,
                "resolved_pct": round(100.0 * n_res / total, 1) if total and n_res is not None else None,
                "unresolved_symbols_sample": (cm.get("unresolved") or [])[:25],
                "note": "a STATIC, versioned CIK resolution snapshot for this historical "
                       "research population, resolved once from a point-in-time SEC "
                       "company_tickers.json -- an 'unresolved' entry here is NOT a claim that "
                       "symbol's CIK is unknown or invalid TODAY, only that this snapshot did "
                       "not resolve it; this is never historical identity verification.",
            }
        else:
            out["universe_coverage"] = {
                "status": "UNKNOWN",
                "note": "manifest file missing, unreadable, or carries no cik_manifest key",
            }

        watchlist_39: set[str] = set()
        try:
            from talonx_ops.watchlist_coverage import build_coverage_map
            watchlist_39 = {c["symbol"].upper() for c in build_coverage_map()["tickers"]
                            if c.get("v2_collection_scope") == "POLLED"}
        except Exception as exc:  # noqa: BLE001
            out["watchlist_39_error"] = f"{type(exc).__name__}: {exc}"
        out["watchlist_39_n"] = len(watchlist_39)

        # broad-discovery-only = in the 626-universe but NOT already in the
        # 39-name product watchlist -- never double-counted.
        broad_only = universe - watchlist_39

        import os as _ingest_os
        toggles = {
            "sec_ingestion_expansion_enabled": _ingest_os.environ.get(
                "TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "").strip().lower() in ("1", "true", "yes", "on"),
            "dispatch_send_enabled": _ingest_os.environ.get(
                "TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "").strip().lower() in ("1", "true", "yes", "on"),
        }
        out["toggles"] = toggles

        # admission_policy: Task 140 -- prefer the REAL companion's own
        # same-process value (v2_service_status.json's
        # "durable_store_gate_enabled", written by the actual V2Service
        # instance at the moment IT read TALONX_V2_DURABLE_STORE_ENABLED)
        # over re-deriving the env var HERE, in the dashboard's own
        # separate process. This dashboard and the V2 companion are
        # spawned independently and can, in principle, see different
        # merged environments -- the exact class of gap already found
        # twice tonight for broad-discovery and delivery-enablement (see
        # docs/research/evidence/task140/). Falls back to the old env-
        # derived reading only for a status file predating this field.
        _admission_raw = _ingest_os.environ.get("TALONX_V2_DURABLE_STORE_ENABLED")
        _status_path = (_ingest_os.environ.get("TALONX_V2_STATUS_PATH")
                        or (str(_repo_root / "v2_service_status.json")
                            if (_repo_root / "v2_service_status.json").exists()
                            else str(self.home / "v2_service_status.json")))
        _source = "this process's own env (status file unavailable/predates this field -- unverified against the actual companion)"
        _admission_gated = (_admission_raw or "").strip().lower() in ("1", "true", "yes", "on")
        try:
            _status_raw = _json.loads(Path(_status_path).read_text())
            if "durable_store_gate_enabled" in _status_raw:
                _admission_gated = bool(_status_raw["durable_store_gate_enabled"])
                _source = "live companion (v2_service_status.json)"
        except Exception:  # noqa: BLE001 -- fall back to the env-derived reading above
            pass
        out["admission_policy"] = {
            "mode": "GATED" if _admission_gated else "PERMISSIVE",
            "env_var": "TALONX_V2_DURABLE_STORE_ENABLED",
            "raw_value": _admission_raw,
            "source": _source,
            "note": ("a durable PENDING intent is REQUIRED before any entry, and a hard "
                    "cash/slot reservation gate applies at intent-creation time"
                    if _admission_gated else
                    "the legacy, permissive cold-start policy applies -- an entry does not "
                    "require a pre-existing durable intent (this is the current production "
                    "default, TALONX_V2_DURABLE_STORE_ENABLED unset or false)"),
        }

        # source_health + freshness: reused directly from v2_active_
        # strategy()'s own readiness computation -- the SAME source/
        # process (the talonx_v2 service + InsiderStore) serves BOTH the
        # primary watchlist and broad discovery; this is deliberately NOT
        # a second, independently-observed feed. `_active`'s own ledger.
        # performance (build_v2_paper_performance) is ALSO reused below
        # for position-level detail -- computed once here, not twice.
        #
        # SPA Final Acceptance correction: FOUR genuinely different
        # timestamps, never substituted for one another --
        #   (0) dashboard_refresh_utc     -- when THIS read ran
        #   (1) db_read_last_ok_utc       -- the local SQLite read
        #                                    succeeded (proves the DB was
        #                                    reachable, NOT that upstream
        #                                    data is current)
        #   (2) upstream_poll_last_ok_utc -- the upstream SEC poll CYCLE
        #                                    itself last completed
        #                                    (proves polling is running,
        #                                    NOT that it found anything
        #                                    new)
        #   (3) latest_source_event_utc   -- the newest individual filing
        #                                    event actually observed in
        #                                    the source data (queried
        #                                    directly from
        #                                    insider_transactions;
        #                                    UNKNOWN when unavailable,
        #                                    never backfilled from (1) or
        #                                    (2))
        # The PRIOR version of this method set the top-level
        # ``upstream_data_as_of_utc`` from (1) -- a real defect (a
        # successful CACHE read is not evidence of upstream freshness).
        # It is now set from (3) only, or left explicitly None/UNKNOWN.
        out["dashboard_refresh_utc"] = out["generated_at"]
        _active: dict[str, Any] = {}
        try:
            _active = self.v2_active_strategy()
            _r = _active.get("readiness", {}) or {}
            latest_event_utc, latest_event_age_s, latest_event_note = None, None, None
            try:
                _ic = _ro(Path(self.intel_ledger))
                if _ic is not None:
                    try:
                        if _has_table(_ic, "insider_transactions"):
                            latest_event_utc = _q1(
                                _ic, "SELECT MAX(accepted_at_utc) FROM insider_transactions "
                                    "WHERE classification='OPEN_MARKET_PURCHASE'")
                            latest_event_age_s = _age_seconds(latest_event_utc, self.now)
                        else:
                            latest_event_note = "insider_transactions table not found"
                    finally:
                        _ic.close()
                else:
                    latest_event_note = "ingestion_ledger.db unavailable"
            except Exception as exc:  # noqa: BLE001
                latest_event_note = f"{type(exc).__name__}: {exc}"
            out["source_health"] = {
                "source_ok": _r.get("form4_source_ok"),
                "source_degraded": _r.get("form4_source_degraded"),
                "db_read_last_ok_utc": _r.get("source_db_read_last_ok_utc"),
                "db_read_age_s": _r.get("source_db_read_age_s"),
                "upstream_poll_last_ok_utc": _r.get("source_poll_last_ok_utc"),
                "upstream_poll_age_s": _r.get("source_poll_age_s"),
                "latest_source_event_utc": latest_event_utc,
                "latest_source_event_age_s": (round(latest_event_age_s, 1)
                                              if latest_event_age_s is not None else None),
                "latest_source_event_unavailable_reason": (
                    None if latest_event_utc is not None else (latest_event_note or "no rows yet")),
                "note": "the SAME source/process serves the primary 39-name watchlist AND "
                       "broad discovery -- not a separately-observed feed. FOUR distinct "
                       "timestamps are exposed here and must never be substituted for one "
                       "another: dashboard_refresh_utc (this read), db_read_last_ok_utc (the "
                       "local cache was reachable -- NOT proof of upstream freshness), "
                       "upstream_poll_last_ok_utc (the poll cycle ran -- NOT proof it found "
                       "anything new), latest_source_event_utc (the newest individual filing "
                       "event actually observed -- the real freshness signal, UNKNOWN when "
                       "unavailable rather than backfilled from either of the other two).",
            }
            out["upstream_data_as_of_utc"] = latest_event_utc
            out["upstream_data_as_of_basis"] = (
                "latest_source_event_utc" if latest_event_utc is not None else
                "UNKNOWN -- no event-level upstream timestamp available; this is deliberately "
                "left unset rather than substituted from a database-read or poll-cycle "
                "timestamp, neither of which proves upstream freshness")
        except Exception as exc:  # noqa: BLE001
            out["source_health"] = {"status": "UNKNOWN", "note": f"{type(exc).__name__}: {exc}"}
            out["upstream_data_as_of_utc"] = None
            out["upstream_data_as_of_basis"] = "UNKNOWN -- source_health computation itself failed"

        out["shared_campaign_ledger_note"] = (
            "Positions/cash below are a SYMBOL-FILTERED VIEW of the SAME shared $300,000 V2 "
            "campaign ledger shown on the Active V2 tab -- never a separate account or "
            "portfolio. Realized P&L is computed from ONLY broad-discovery-only symbols; "
            "campaign-level cash/equity/reconciliation are shown once, on the Active V2 tab, "
            "and are not meaningfully splittable by symbol subset.")

        con = _ro(Path(db))
        if con is None:
            out["ledger"] = {"status": "NO_ACTIVE_PRODUCER", "note": "no v2_lane.db"}
            out["discovery_funnel"] = {
                "status": "NO_ACTIVE_PRODUCER", "recent": [], "by_status": {},
                "empty_state_note": (
                    "The V2 campaign ledger database itself is unavailable -- this is NOT "
                    "the same as \"zero candidates were recorded\"; no query could even run. "
                    "See discovery_operating_evidence below."),
                "discovery_operating_evidence": {
                    "sec_ingestion_expansion_enabled": toggles["sec_ingestion_expansion_enabled"],
                    "dispatch_send_enabled": toggles["dispatch_send_enabled"],
                    "source_ok": out.get("source_health", {}).get("source_ok"),
                    "source_degraded": out.get("source_health", {}).get("source_degraded"),
                    "db_read_age_s": out.get("source_health", {}).get("db_read_age_s"),
                    "upstream_poll_age_s": out.get("source_health", {}).get("upstream_poll_age_s"),
                    "latest_source_event_utc": out.get("source_health", {}).get("latest_source_event_utc"),
                    "note": "these signals are INDEPENDENT of the ledger's own availability -- "
                           "the upstream source can be perfectly healthy even while THIS "
                           "specific campaign ledger file is missing/unreachable.",
                },
            }
            out["action_queue"] = {"status": "NO_ACTIVE_PRODUCER", "pending_intents": [], "recent_outbox": []}
        else:
            try:
                if not _has_table(con, "positions"):
                    out["ledger"] = {"status": "ZERO_ACTIVITY", "note": "no positions table"}
                else:
                    all_pos = _qall(con, "SELECT symbol, status, realized_pnl_usd, position_cost "
                                         "FROM positions")
                    bd_pos = [dict(r) for r in all_pos if (r["symbol"] or "").upper() in broad_only]
                    bd_open = [r for r in bd_pos if r["status"] == "OPEN"]
                    bd_closed = [r for r in bd_pos if r["status"] == "CLOSED"]
                    bd_realized = round(sum((r["realized_pnl_usd"] or 0.0) for r in bd_closed), 2)
                    out["ledger"] = {
                        "status": "ACTIVE" if bd_pos else "ZERO_ACTIVITY",
                        "n_open": len(bd_open),
                        "n_closed": len(bd_closed),
                        "realized_pnl_usd": bd_realized,
                        "open_symbols": sorted({r["symbol"] for r in bd_open}),
                        "administrative_adjustments_note": (
                            "the V2 positions table carries no administrative-adjustment "
                            "marker (unlike the Original/Experimental lanes) -- none have ever "
                            "been made to this ledger, so none are excluded here"),
                        "note": "counts ONLY symbols in the 626-universe that are NOT already "
                               "in the primary 39-name watchlist -- never double-counted "
                               "with v2_active_strategy's own ledger above",
                        "symbol_membership_note": (
                            "a symbol appears here because it is CURRENTLY in the 626-name "
                            "universe and NOT in the 39-name watchlist -- this does NOT prove "
                            "the position was originated via broad-discovery ingestion "
                            "specifically (TALONX_INTEL_ENABLE_BROAD_DISCOVERY may not have "
                            "been active when this episode was actually detected); it is a "
                            "present-tense symbol-membership filter, not a claim of historical "
                            "discovery origin"),
                    }

                    # SPA Final Acceptance section 3: position-level detail,
                    # reused DIRECTLY from build_v2_paper_performance (the
                    # SAME real paper engine + valuation evidence
                    # v2_active_strategy's own campaign-ledger card uses,
                    # already computed once above as `_active`) -- never a
                    # second/invented valuation. Filtered to broad-
                    # discovery-only symbols; the campaign-level totals
                    # (cash/equity/reconciliation) stay on the Active V2
                    # tab only, per shared_campaign_ledger_note above.
                    _perf = (_active.get("ledger") or {}).get("performance") or {}
                    if _perf.get("status") in (None, "UNAVAILABLE") and "open_positions" not in _perf:
                        out["ledger"]["position_detail_unavailable_reason"] = (
                            _perf.get("note") or "campaign performance snapshot unavailable")
                        out["ledger"]["open_positions_detail"] = []
                        out["ledger"]["closed_trades_detail"] = []
                    else:
                        _open_detail_all = ((_perf.get("open_positions") or {}).get("detail")) or []
                        _closed_detail_all = _perf.get("closed_trades") or []
                        out["ledger"]["open_positions_detail"] = [
                            r for r in _open_detail_all if (r.get("symbol") or "").upper() in broad_only]
                        out["ledger"]["closed_trades_detail"] = [
                            r for r in _closed_detail_all if (r.get("symbol") or "").upper() in broad_only]
                        out["ledger"]["position_detail_note"] = (
                            "mark/unrealized-P&L fields are exactly as computed by "
                            "build_v2_paper_performance (talonx_ops/paper_performance.py) -- "
                            "'mark'=None and 'unrealized_pnl_usd'=None mean NO usable mark was "
                            "available for that symbol (never a fabricated fresh valuation); "
                            "'mark' when present is a real quote, distinct from 'entry_price' "
                            "(the original fill), and is never presented as the fill price.")

                # discovery_funnel: real episode dispositions + intent
                # statuses for broad-discovery-only symbols, classified.
                # A genuinely PENDING intent has NO processed_episodes row
                # yet (V2Service only writes a disposition at ENTERED /
                # SKIPPED_* / REJECTED_* / EXPIRED_* / FAILED_* time, not
                # at intent-creation time) -- so the candidate set is the
                # UNION of both tables' episode_ids, never just the
                # episodes table alone, or every real PENDING intent
                # would be invisible here.
                ep_rows = _qall(con, "SELECT episode_id, symbol, disposition, detail, "
                                     "eligible_entry_session, updated_at FROM processed_episodes") \
                    if _has_table(con, "processed_episodes") else []
                bd_eps = {r["episode_id"]: dict(r) for r in ep_rows
                         if (r["symbol"] or "").upper() in broad_only}
                intent_rows = _qall(con, "SELECT intent_id, episode_id, symbol, status, "
                                         "target_entry_session, planned_exit_session, "
                                         "created_at_utc, fill_price, fill_entry_session, detail "
                                         "FROM pending_entry_intents") \
                    if _has_table(con, "pending_entry_intents") else []
                intent_by_episode = {r["episode_id"]: dict(r) for r in intent_rows
                                     if (r["symbol"] or "").upper() in broad_only}
                candidates = []
                for episode_id in set(bd_eps) | set(intent_by_episode):
                    ep = bd_eps.get(episode_id)
                    intent = intent_by_episode.get(episode_id)
                    if ep is None:
                        # intent-only -- no disposition written yet (the
                        # normal shape of a fresh PENDING reservation).
                        ep = {"episode_id": episode_id, "symbol": intent["symbol"], "disposition": "",
                             "detail": "", "eligible_entry_session": intent.get("target_entry_session"),
                             "updated_at": intent.get("created_at_utc")}
                    candidates.append(self._classify_discovery_candidate(ep, intent))
                candidates.sort(key=lambda c: c.get("event_time") or "", reverse=True)
                by_status: dict[str, int] = {}
                for c in candidates:
                    by_status[c["status_bucket"]] = by_status.get(c["status_bucket"], 0) + 1
                # SPA Final Acceptance correction: an empty candidate list
                # means ONLY "zero rows recorded in this ledger view" --
                # it does NOT, by itself, establish that no qualifying
                # filing activity occurred, that discovery is healthy, or
                # that the source is current. The prior text asserted a
                # REASON ("no code-P Form 4 activity has produced a
                # qualifying cluster") the ledger alone cannot prove.
                # Replaced with a purely factual statement, plus the
                # INDEPENDENT evidence (source health, toggles, admission
                # policy) a reader needs to form their OWN conclusion --
                # never inferred or asserted here.
                out["discovery_funnel"] = {
                    "status": "ACTIVE" if candidates else "ZERO_ACTIVITY",
                    "candidates_n": len(candidates),
                    "by_status": by_status,
                    "recent": candidates[:25],
                    "empty_state_note": (
                        None if candidates else
                        "No recorded broad-discovery candidates in this ledger. This states "
                        "ONLY that zero rows are recorded here -- see "
                        "discovery_operating_evidence (and source_health / toggles / "
                        "admission_policy above) to determine independently whether that is "
                        "because discovery is disabled, the source is stale/unavailable, or "
                        "the source is healthy and genuinely observed no qualifying activity."),
                    "discovery_operating_evidence": {
                        "sec_ingestion_expansion_enabled": toggles["sec_ingestion_expansion_enabled"],
                        "dispatch_send_enabled": toggles["dispatch_send_enabled"],
                        "source_ok": out.get("source_health", {}).get("source_ok"),
                        "source_degraded": out.get("source_health", {}).get("source_degraded"),
                        "db_read_age_s": out.get("source_health", {}).get("db_read_age_s"),
                        "upstream_poll_age_s": out.get("source_health", {}).get("upstream_poll_age_s"),
                        "latest_source_event_utc": out.get("source_health", {}).get("latest_source_event_utc"),
                        "note": "these signals are INDEPENDENT of the candidate count above -- "
                               "a healthy, actively-polling source can legitimately show zero "
                               "candidates (no qualifying cluster has formed YET), and a "
                               "disabled or unhealthy source can also show zero candidates for "
                               "an entirely different reason. Read them together; never infer "
                               "one from the other.",
                    },
                }

                # action_queue: pending intents + recent outbox rows for
                # broad-discovery-only symbols. Reserved cash/slots use
                # the SAME per-position allocation V2Service itself uses
                # (a config default, not a live write).
                bd_pending = [dict(r) for r in intent_rows
                             if (r["symbol"] or "").upper() in broad_only and r["status"] == "PENDING"]
                try:
                    from talonx_v2.config import V2Config
                    _alloc = V2Config().per_position_allocation_usd
                except Exception:  # noqa: BLE001
                    _alloc = None
                outbox_rows = _qall(con, "SELECT event_id, episode_id, kind, action, symbol, "
                                         "state, attempts, deliver_by_utc, created_at_utc, "
                                         "sent_at_utc, last_error FROM v2_alert_outbox") \
                    if _has_table(con, "v2_alert_outbox") else []
                bd_outbox = [dict(r) for r in outbox_rows if (r["symbol"] or "").upper() in broad_only]
                bd_outbox.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
                out["action_queue"] = {
                    "pending_intents": [
                        {**p, "reference_price": "PENDING -- resolved at the target session's "
                                                 "own open, never invented ahead of time"}
                        for p in bd_pending],
                    "pending_intents_n": len(bd_pending),
                    "reserved_cash_usd": (round(_alloc * len(bd_pending), 2)
                                          if _alloc is not None else None),
                    "reserved_slots": len(bd_pending),
                    "recent_outbox": bd_outbox[:25],
                    "note": "an outbox row's state PENDING or RETRY means QUEUED, NOT "
                           "delivered -- only SENT confirms delivery. EXPIRED, FAILED, and "
                           "AMBIGUOUS rows must never be read as a current actionable "
                           "instruction.",
                }
            except Exception as exc:  # noqa: BLE001
                out["ledger"] = out.get("ledger") or {"status": "UNKNOWN", "note": f"{type(exc).__name__}: {exc}"}
                out["discovery_funnel"] = {"status": "UNKNOWN", "note": f"{type(exc).__name__}: {exc}", "recent": [], "by_status": {}}
                out["action_queue"] = {"status": "UNKNOWN", "note": f"{type(exc).__name__}: {exc}", "pending_intents": [], "recent_outbox": []}
            finally:
                con.close()

        out["broad_discovery_only_symbols_n"] = len(broad_only)
        out["overlap_with_39_name_watchlist_n"] = len(universe & watchlist_39)
        return out

    @staticmethod
    def _v2_position_lifecycle(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        row = dict(row)
        _asof = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        try:
            from talonx_v2.calendar import trading_days_elapsed
            entry = row.get("entry_session")
            if entry:
                held = trading_days_elapsed(_date.fromisoformat(str(entry)[:10]), _asof)
                row["days_held"] = held
                row["sessions_remaining"] = max(0, 10 - held)
        except Exception:  # noqa: BLE001
            pass
        row["hold_trading_sessions"] = 10
        row["eod_auto_close"] = "OFF"
        return row

    @staticmethod
    def _v2_eod_state(es: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """Map the market-phase-aware EOD state to the dashboard vocabulary
        (Task 114 A5.4): STALE only after a real missed deadline.

        D3: a reconciliation row only supersedes when its ``session_date``
        matches the CURRENT session (``now``), never merely today's wall clock.
        A stale row from a prior session is ignored and surfaced separately so
        the tile never shows another day's PARTIAL/PASS as if it were current.
        """
        st = es.get("state", "UNKNOWN")
        ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
        stale_row_session = None
        try:
            from talonx_ops.eod_reconciliation import EodReconciliationStore
            row = EodReconciliationStore(read_only=True).latest()
            if row is not None:
                row_session = str(getattr(row, "session_date", ""))
                if row_session == ref:
                    st = {"RECONCILED": "RECONCILED_PASS", "PARTIAL": "PARTIAL",
                          "MISMATCH": "FAILED"}.get(getattr(row, "status", ""), st)
                elif row_session:
                    stale_row_session = row_session
        except Exception:  # noqa: BLE001
            pass
        out = {"state": st, "reason": es.get("reason"),
               "close_utc": es.get("close_utc"), "deadline_utc": es.get("deadline_utc"),
               "session_date": ref}
        if stale_row_session:
            out["prior_reconciliation_session"] = stale_row_session
            out["prior_reconciliation_note"] = (
                f"latest reconciliation row is for {stale_row_session}, "
                f"not the current session {ref} -- not applied to this tile")
        return out

    # ------------------------------------------------------------------ #
    # PAPER PERFORMANCE -- Task 119 (Task 118H Option 3), corrected Task
    # 119A A1: an attributable, per-lane realized/unrealized P&L,
    # open-position and reconciliation accessor. NOT a routed dashboard
    # section on its own (Task 119's separate "Paper Performance" tab was
    # a duplicate navigation destination and has been retired) -- its data
    # is folded into the ONE existing destination for each lane instead:
    # paper_eod() (Original/Experimental/PIV) and v2_active_strategy()
    # (V2), both of which call into this method/module. Kept as a public
    # method because it is directly useful and directly tested on its own
    # (tests/test_task119_paper_performance.py), not because it is a
    # second user-facing surface.
    # ------------------------------------------------------------------ #
    def paper_performance(self) -> dict[str, Any]:
        import os as _os

        from talonx_ops.paper_performance import build_paper_performance

        _repo_root = Path(__file__).resolve().parents[1]
        v2_db = (_os.environ.get("TALONX_V2_DB_PATH")
                 or (str(_repo_root / "v2_lane.db") if (_repo_root / "v2_lane.db").exists()
                     else str(self.home / "v2_lane.db")))
        return build_paper_performance(
            home=self.home, exp_home=self.exp, v2_db=Path(v2_db),
            now=self.now, check_processes=self.check_processes,
        )

    def all_sections(self) -> dict[str, Any]:
        return {
            "overview": self.overview(),
            "premarket": self.premarket(),
            "original_quant": self.original_quant(),
            "v2_active_strategy": self.v2_active_strategy(),   # Task 112 -- UNCHANGED, the
                                                                # original 39-name watchlist view
            "v2_broad_discovery": self.v2_broad_discovery(),   # Task 131 -- NEW, additive
            "validation": self.validation(),
            "intelligence": self.intelligence(),
            "paper_eod": self.paper_eod(),                     # includes folded-in Task 119 performance data
        }
