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

_HOME = Path.home() / ".talonx"

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
            }
        except Exception as exc:  # noqa: BLE001
            active_v2 = {"error": f"{type(exc).__name__}: {exc}"}

        needs_attention = self._overview_needs_attention(runtime, market, active_v2, alerts)

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
    def paper_eod(self) -> dict[str, Any]:
        op = self.arm.original_paper()
        ep = self.arm.experimental_paper()
        piv = self.arm.piv()
        eod = self.arm.eod_reconciliation()
        return {
            "generated_at": self.now.isoformat(),
            "separation_note": "Original / Experimental / PIV paper are SEPARATE ledgers -- never one merged positions count.",
            "original_local_paper": {
                "attribution": "ORIGINAL / local-only (no broker)",
                "status": op.status.value,
                "open_positions": op.values.get("open_positions"),
                "trades_all_time": op.values.get("trades_all_time"),
                "current_cash": op.values.get("current_cash"),
                "note": op.note,
            },
            "experimental_validation_paper": {
                "attribution": "EXPERIMENTAL / validation-only, simulated, no real capital",
                "internal_only": True,
                "status": ep.status.value,
                "open_positions": ep.values.get("open_positions"),
                "trades_all_time": ep.values.get("trades_all_time"),
                "current_cash": ep.values.get("current_cash"),
                "note": ep.note,
            },
            "piv_alpaca_paper": {
                "attribution": "PIV / Alpaca PAPER (independent; structurally cannot route real capital)",
                "status": piv.status.value,
                "note": piv.note,
                "positions": "NOT_CHECKED",
                "orders": "NOT_CHECKED",
                "checked": False,
            },
            "eod_reconciliation": {
                "status": eod.status.value,
                "authoritative_source": eod.authoritative_source,
                "values": eod.values,
                "last_update": eod.last_update,
                "note": eod.note,
            },
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
                        "open_positions": [self._v2_position_lifecycle(dict(r)) for r in opens],
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
            out["eod"] = self._v2_eod_state(eod_state(self.now))
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
            _V2FP = "11107198c5b81237"
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
        return out

    @staticmethod
    def _v2_position_lifecycle(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        try:
            from talonx_v2.calendar import trading_days_elapsed
            entry = row.get("entry_session")
            if entry:
                held = trading_days_elapsed(_date.fromisoformat(str(entry)[:10]),
                                            datetime.now(timezone.utc).date())
                row["days_held"] = held
                row["sessions_remaining"] = max(0, 10 - held)
        except Exception:  # noqa: BLE001
            pass
        row["hold_trading_sessions"] = 10
        row["eod_auto_close"] = "OFF"
        return row

    @staticmethod
    def _v2_eod_state(es: dict[str, Any]) -> dict[str, Any]:
        """Map the market-phase-aware EOD state to the dashboard vocabulary
        (Task 114 A5.4): STALE only after a real missed deadline."""
        st = es.get("state", "UNKNOWN")
        # if a reconciliation row exists for today, PASS/PARTIAL supersedes
        try:
            from talonx_ops.eod_reconciliation import EodReconciliationStore
            row = EodReconciliationStore(read_only=True).latest()
            today = datetime.now(timezone.utc).date().isoformat()
            if row is not None and str(getattr(row, "session_date", "")) == today:
                st = {"RECONCILED": "RECONCILED_PASS", "PARTIAL": "PARTIAL",
                      "MISMATCH": "FAILED"}.get(getattr(row, "status", ""), st)
        except Exception:  # noqa: BLE001
            pass
        return {"state": st, "reason": es.get("reason"),
                "close_utc": es.get("close_utc"), "deadline_utc": es.get("deadline_utc")}

    # ------------------------------------------------------------------ #
    def all_sections(self) -> dict[str, Any]:
        return {
            "overview": self.overview(),
            "premarket": self.premarket(),
            "original_quant": self.original_quant(),
            "v2_active_strategy": self.v2_active_strategy(),   # Task 112
            "validation": self.validation(),
            "intelligence": self.intelligence(),
            "paper_eod": self.paper_eod(),
        }
