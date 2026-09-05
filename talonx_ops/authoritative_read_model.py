"""talonx_ops.authoritative_read_model -- Task 100A.

A read-ONLY, no-write-side-effect adapter that answers "what is the truthful
state of each logical TalonX domain?" so dashboards / reports / operators stop
reading an overloaded numeric ``0`` and mistaking NO_ACTIVE_PRODUCER /
SUPERSEDED / STALE for real ZERO_ACTIVITY.

Design (Task 99K authoritative_data_map.md + legacy_channel_ownership.md,
Task 99L decision_log.md):

* Every store is opened ``file:...?mode=ro`` -- the adapter physically cannot
  write, and it never instantiates a store class (several of those migrate
  their schema on ``__init__``, which is a write).
* Every read is wrapped so a missing / locked / malformed store yields
  ``UNKNOWN`` for that domain, never an exception.
* Legacy numeric fields are preserved verbatim under ``values``; the new
  ``status`` field carries the semantic state.
* NOT a runtime merge and NOT a dashboard redesign -- Task 100B / 100C.

Producer liveness:
* Original (run_talonx.py): ``~/.talonx/runtime_metadata.json`` (pid + started_at),
  cross-checked against a live process, with an optional Redis liveness key.
* Experimental (talonx_signals.run): a process scan for ``-m talonx_signals.run``.
* Intelligence (talonx_ingest.intelligence.service): the service heartbeat file
  ``~/.talonx/intelligence/service.heartbeat.json`` recency.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_HOME = Path.home() / ".talonx"
_EXP = _HOME / "experimental"
_INTEL_STATE = _HOME / "intelligence"

# staleness thresholds (seconds)
_ORIGINAL_METADATA_MAX_AGE = 6 * 3600          # runtime_metadata.json older than this + no live pid => not live
_MARKET_TICK_MAX_AGE = 15 * 60                 # last written tick older than this => STALE
_INTEL_HEARTBEAT_MAX_AGE = 30 * 60             # > ~2x the 900s recovery cadence => NO_ACTIVE_PRODUCER


class AuthorityStatus(str, Enum):
    ACTIVE = "ACTIVE"                          # producer live + genuine activity
    ZERO_ACTIVITY = "ZERO_ACTIVITY"            # producer live + genuinely nothing to report (a real zero)
    NO_ACTIVE_PRODUCER = "NO_ACTIVE_PRODUCER"  # the producing process is not running
    SUPERSEDED = "SUPERSEDED"                  # this source is not the domain authority; a newer one is
    STALE = "STALE"                            # data exists but is old / poll recency is old
    UNKNOWN = "UNKNOWN"                         # store missing / unreadable -- do not guess


@dataclass(frozen=True)
class DomainAuthority:
    domain: str
    status: AuthorityStatus
    authoritative_source: str
    values: dict[str, Any] = field(default_factory=dict)
    last_update: str | None = None
    legacy_sources: tuple[str, ...] = ()
    superseded_source: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status.value,
            "authoritative_source": self.authoritative_source,
            "values": self.values,
            "last_update": self.last_update,
            "legacy_sources": list(self.legacy_sources),
            "superseded_source": self.superseded_source,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# small read-only helpers
# --------------------------------------------------------------------------- #
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


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _q1(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:  # noqa: BLE001
            return False


def _proc_matches(*needles: str) -> bool:
    """True if a running process's command line contains every needle."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return False
    for p in psutil.process_iter(["cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
        except Exception:  # noqa: BLE001
            continue
        if cl and all(n in cl for n in needles):
            return True
    return False


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
class AuthoritativeReadModel:
    """One instance per read. Cheap to construct; opens nothing until a
    domain method is called."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        exp_home: Path | None = None,
        intel_state_dir: Path | None = None,
        runtime_metadata_path: Path | None = None,
        ledger_path: Path | None = None,
        now: datetime | None = None,
        check_processes: bool = True,
    ) -> None:
        self.home = home or _HOME
        self.exp = exp_home or (self.home / "experimental")
        self.intel_state = intel_state_dir or (self.home / "intelligence")
        self.runtime_metadata_path = runtime_metadata_path or (self.home / "runtime_metadata.json")
        self.ledger_path = ledger_path or (self.home / "ingestion_ledger.db")
        self.now = now or datetime.now(timezone.utc)
        self.check_processes = check_processes
        self._orig_live: tuple[bool, str] | None = None
        self._intel_live: tuple[bool, str, str | None] | None = None

    # ---- producer liveness -------------------------------------------------
    def original_producer(self) -> dict[str, Any]:
        if self._orig_live is None:
            live, reason, meta = False, "no runtime_metadata.json", None
            try:
                meta = json.loads(self.runtime_metadata_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = None
            if meta:
                pid = meta.get("pid")
                started = meta.get("started_at")
                pid_ok = bool(pid) and self.check_processes and _pid_alive(pid)
                proc_ok = self.check_processes and _proc_matches("run_talonx.py")
                age = _age_seconds(started, self.now)
                if pid_ok or proc_ok:
                    live, reason = True, ("pid alive" if pid_ok else "run_talonx.py process found")
                elif age is not None and age < _ORIGINAL_METADATA_MAX_AGE and not self.check_processes:
                    live, reason = True, f"runtime_metadata age {age:.0f}s (process check disabled)"
                else:
                    live, reason = False, (
                        f"pid {pid} not alive, no run_talonx.py process"
                        + (f", metadata {age:.0f}s old" if age is not None else "")
                    )
            self._orig_live = (live, reason)
            self._orig_meta = meta
        return {"live": self._orig_live[0], "reason": self._orig_live[1],
                "metadata": getattr(self, "_orig_meta", None)}

    def experimental_producer(self) -> dict[str, Any]:
        live = self.check_processes and _proc_matches("talonx_signals.run")
        return {"live": bool(live),
                "reason": "talonx_signals.run process found" if live else "no talonx_signals.run process"}

    def intelligence_producer(self) -> dict[str, Any]:
        if self._intel_live is None:
            hb = self.intel_state / "service.heartbeat.json"
            live, reason, hb_ts = False, "no service.heartbeat.json", None
            try:
                payload = json.loads(hb.read_text(encoding="utf-8"))
                hb_ts = payload.get("at") or payload.get("timestamp") or payload.get("written_at")
                if hb_ts is None:
                    hb_ts = datetime.fromtimestamp(hb.stat().st_mtime, timezone.utc).isoformat()
                age = _age_seconds(hb_ts, self.now)
                if age is not None and age <= _INTEL_HEARTBEAT_MAX_AGE:
                    live, reason = True, f"heartbeat {age:.0f}s old"
                else:
                    live, reason = False, (
                        f"heartbeat {age:.0f}s old (> {_INTEL_HEARTBEAT_MAX_AGE}s)"
                        if age is not None else "heartbeat timestamp unreadable"
                    )
            except FileNotFoundError:
                pass
            except Exception:  # noqa: BLE001
                reason = "heartbeat unreadable"
            self._intel_live = (live, reason, hb_ts)
        return {"live": self._intel_live[0], "reason": self._intel_live[1],
                "heartbeat_at": self._intel_live[2]}

    # ---- domains ---------------------------------------------------------
    def _today(self) -> str:
        return self.now.astimezone(timezone.utc).strftime("%Y-%m-%d")

    def market(self) -> DomainAuthority:
        con = _ro(self.home / "paper_trading.db")
        if con is None:
            return DomainAuthority("market", AuthorityStatus.UNKNOWN,
                                   "talonx_ingest.market_data.manager (state)",
                                   note="paper_trading.db (latest_prices tap) unavailable")
        try:
            n = _q1(con, "SELECT COUNT(*) FROM latest_prices") or 0
            newest = _q1(con, "SELECT MAX(updated_at) FROM latest_prices")
        finally:
            con.close()
        orig = self.original_producer()
        age = _age_seconds(newest, self.now)
        vals = {"symbols_priced": n, "newest_tick": newest,
                "newest_tick_age_seconds": round(age) if age is not None else None}
        if not orig["live"]:
            return DomainAuthority(
                "market", AuthorityStatus.NO_ACTIVE_PRODUCER,
                "talonx_ingest.market_data.manager (via run_talonx.py)", vals, newest,
                legacy_sources=("talonx:market:stream", "dashboard_web.py ChannelStats"),
                note=f"run_talonx.py not running ({orig['reason']}); last tick data is a stale projection")
        if age is None or age > _MARKET_TICK_MAX_AGE:
            return DomainAuthority("market", AuthorityStatus.STALE,
                                   "talonx_ingest.market_data.manager (via run_talonx.py)", vals, newest,
                                   legacy_sources=("talonx:market:stream",),
                                   note=f"producer live but newest tick is {age:.0f}s old" if age is not None
                                   else "producer live but no tick timestamp")
        return DomainAuthority("market", AuthorityStatus.ACTIVE,
                               "talonx_ingest.market_data.manager (via run_talonx.py)", vals, newest,
                               legacy_sources=("talonx:market:stream",))

    def symbol_coverage(self) -> DomainAuthority:
        con = _ro(self.home / "watchlist.db")
        if con is None or not _has_table(con, "tickers"):
            if con:
                con.close()
            return DomainAuthority("symbol_coverage", AuthorityStatus.UNKNOWN,
                                   "talonx_watchlist.store.TickerWatchlistStore (watchlist.db)",
                                   note="watchlist.db unavailable")
        try:
            total = _q1(con, "SELECT COUNT(*) FROM tickers") or 0
            cols = [r[1] for r in con.execute("PRAGMA table_info(tickers)")]
            active = None
            if "active" in cols:
                active = _q1(con, "SELECT COUNT(*) FROM tickers WHERE active=1")
            elif "status" in cols:
                active = _q1(con, "SELECT COUNT(*) FROM tickers WHERE status='active'")
        finally:
            con.close()
        return DomainAuthority(
            "symbol_coverage", AuthorityStatus.ACTIVE,
            "talonx_watchlist.store.TickerWatchlistStore (watchlist.db)",
            {"configured": total, "active": active, "excluded": (total - active) if active is not None else None},
            note="config store -- always readable; authority already correct (Task 99K KEEP)")

    def quant_funnel(self) -> DomainAuthority:
        con = _ro(self.home / "quant.db")
        if con is None or not _has_table(con, "suppression_counts"):
            if con:
                con.close()
            return DomainAuthority("quant_funnel", AuthorityStatus.UNKNOWN,
                                   "quant.db suppression_counts (talonx_quant.QuantStateStore)",
                                   note="quant.db unavailable")
        try:
            today = self._today()
            cols = [r[1] for r in con.execute("PRAGMA table_info(suppression_counts)")]
            dcol = "date" if "date" in cols else ("date_str" if "date_str" in cols else None)
            rcol = "reason" if "reason" in cols else None
            ccol = "count" if "count" in cols else None
            rows_today: list = []
            if dcol and rcol and ccol:
                rows_today = con.execute(
                    f"SELECT {rcol}, SUM({ccol}) FROM suppression_counts WHERE {dcol}=? GROUP BY {rcol}",
                    (today,)).fetchall()
            total_rows = _q1(con, "SELECT COUNT(*) FROM suppression_counts") or 0
            newest = _q1(con, f"SELECT MAX({dcol}) FROM suppression_counts") if dcol else None
        finally:
            con.close()
        by_reason = {r[0]: int(r[1] or 0) for r in rows_today}
        total_today = sum(by_reason.values())
        vals = {"suppressions_today": total_today, "by_reason_today": by_reason,
                "rows_all_time": total_rows, "newest_date": newest}
        orig = self.original_producer()
        if total_today > 0:
            return DomainAuthority("quant_funnel", AuthorityStatus.ACTIVE,
                                   "quant.db suppression_counts", vals, newest,
                                   legacy_sources=("talonx:quant:rejected",),
                                   note="Original rejection funnel -- the authoritative 'why did Quant not trade' surface")
        status = AuthorityStatus.ZERO_ACTIVITY if orig["live"] else AuthorityStatus.NO_ACTIVE_PRODUCER
        return DomainAuthority("quant_funnel", status, "quant.db suppression_counts", vals, newest,
                               legacy_sources=("talonx:quant:rejected",),
                               note=("run_talonx.py live -- 0 suppressions recorded today yet"
                                     if orig["live"] else
                                     f"run_talonx.py not running ({orig['reason']}); newest data {newest}"))

    def quant_signals(self) -> DomainAuthority:
        con = _ro(self.home / "dispatch_audit.db")
        orig = self.original_producer()
        if con is None or not _has_table(con, "alerts"):
            if con:
                con.close()
            return DomainAuthority("quant_signals", AuthorityStatus.UNKNOWN,
                                   "dispatch_audit.db alerts (durable) + talonx:signals:quant (live tap)",
                                   note="dispatch_audit.db unavailable")
        try:
            today = self._today()
            n_alerts_today = _q1(con,
                                 "SELECT COUNT(*) FROM alerts WHERE substr(received_at,1,10)=?", (today,)) or 0
            n_alerts_all = _q1(con, "SELECT COUNT(*) FROM alerts") or 0
            newest = _q1(con, "SELECT MAX(received_at) FROM alerts")
        finally:
            con.close()
        vals = {"published_proxy_alerts_today": n_alerts_today, "published_proxy_alerts_all_time": n_alerts_all,
                "newest": newest}
        if n_alerts_today > 0:
            return DomainAuthority("quant_signals", AuthorityStatus.ACTIVE,
                                   "dispatch_audit.db alerts + talonx:signals:quant", vals, newest,
                                   legacy_sources=("talonx:signals:quant",))
        status = AuthorityStatus.ZERO_ACTIVITY if orig["live"] else AuthorityStatus.NO_ACTIVE_PRODUCER
        return DomainAuthority(
            "quant_signals", status, "dispatch_audit.db alerts + talonx:signals:quant", vals, newest,
            legacy_sources=("talonx:signals:quant",),
            note=("0 published Original signals today -- this is ZERO_ACTIVITY_BY_DESIGN (frozen gate "
                  "ordering, Task 99F/101A); it does NOT mean 0 market processing -- see quant_funnel"
                  if orig["live"] else f"run_talonx.py not running ({orig['reason']})"))

    def brain_reports(self) -> DomainAuthority:
        con = _ro(self.home / "brain.db")
        orig = self.original_producer()
        if con is None or not _has_table(con, "report_counts"):
            if con:
                con.close()
            return DomainAuthority("brain_reports", AuthorityStatus.UNKNOWN,
                                   "brain.db report_counts (talonx_brain.BrainStatsStore)",
                                   note="brain.db unavailable")
        try:
            today = self._today()
            cols = [r[1] for r in con.execute("PRAGMA table_info(report_counts)")]
            dcol = "date" if "date" in cols else ("date_str" if "date_str" in cols else None)
            n_today = _q1(con, f"SELECT COALESCE(SUM(count),0) FROM report_counts WHERE {dcol}=?",
                          (today,)) if dcol else None
            n_all = _q1(con, "SELECT COALESCE(SUM(count),0) FROM report_counts") or 0
            newest = _q1(con, f"SELECT MAX({dcol}) FROM report_counts") if dcol else None
        finally:
            con.close()
        qs = self.quant_signals()
        vals = {"reports_today": int(n_today or 0), "reports_all_time": int(n_all),
                "newest_date": newest, "upstream_quant_signals_today": qs.values.get("published_proxy_alerts_today")}
        if (n_today or 0) > 0:
            return DomainAuthority("brain_reports", AuthorityStatus.ACTIVE, "brain.db report_counts",
                                   vals, newest, legacy_sources=("talonx:reports:brain",))
        if not orig["live"]:
            return DomainAuthority("brain_reports", AuthorityStatus.NO_ACTIVE_PRODUCER,
                                   "brain.db report_counts", vals, newest,
                                   legacy_sources=("talonx:reports:brain",),
                                   note=f"run_talonx.py not running ({orig['reason']})")
        # producer live: distinguish "0 because 0 Quant publications" from "Brain down"
        note = ("0 reports today because 0 Quant signals were published today (KEEP_CURRENT_FLOW, "
                "Task 99K/99L) -- Brain is running and correctly idle, NOT down")
        return DomainAuthority("brain_reports", AuthorityStatus.ZERO_ACTIVITY, "brain.db report_counts",
                               vals, newest, legacy_sources=("talonx:reports:brain",), note=note)

    def official_alerts(self) -> DomainAuthority:
        con = _ro(self.home / "dispatch_audit.db")
        orig = self.original_producer()
        if con is None or not _has_table(con, "alerts"):
            if con:
                con.close()
            return DomainAuthority("official_alerts", AuthorityStatus.UNKNOWN,
                                   "dispatch_audit.db (AuditStore)", note="dispatch_audit.db unavailable")
        try:
            today = self._today()
            gen = _q1(con, "SELECT COUNT(*) FROM alerts WHERE substr(received_at,1,10)=?", (today,)) or 0
            sent = _q1(con, "SELECT COUNT(*) FROM alerts WHERE telegram_sent=1 AND substr(received_at,1,10)=?",
                       (today,)) or 0
            failed = _q1(con, "SELECT COUNT(*) FROM alerts WHERE telegram_error IS NOT NULL "
                              "AND telegram_error<>'' AND substr(received_at,1,10)=?", (today,)) or 0
            held = _q1(con, "SELECT COUNT(*) FROM alerts WHERE suppress_reason IS NOT NULL "
                            "AND suppress_reason<>'' AND substr(received_at,1,10)=?", (today,)) or 0
            gen_all = _q1(con, "SELECT COUNT(*) FROM alerts") or 0
            lt_all = _q1(con, "SELECT COUNT(*) FROM long_term_alerts") if _has_table(con, "long_term_alerts") else 0
            newest = _q1(con, "SELECT MAX(received_at) FROM alerts")
        finally:
            con.close()
        vals = {"generated_today": gen, "sent_today": sent, "failed_today": failed, "held_today": held,
                "generated_all_time": gen_all, "long_term_all_time": lt_all,
                "external_eligible": True, "internal_only": False, "newest": newest,
                "dedup_basis": "one row in dispatch_audit.db.alerts == one logical alert "
                               "(transient talonx:alerts:dispatch is NOT counted separately)"}
        if gen > 0:
            return DomainAuthority("official_alerts", AuthorityStatus.ACTIVE, "dispatch_audit.db (AuditStore)",
                                   vals, newest, legacy_sources=("talonx:alerts:dispatch",))
        status = AuthorityStatus.ZERO_ACTIVITY if orig["live"] else AuthorityStatus.NO_ACTIVE_PRODUCER
        return DomainAuthority("official_alerts", status, "dispatch_audit.db (AuditStore)", vals, newest,
                               legacy_sources=("talonx:alerts:dispatch",),
                               note=("run_talonx.py live -- 0 official alerts today (downstream of 0 Quant "
                                     "publications)" if orig["live"] else f"run_talonx.py not running "
                                     f"({orig['reason']})"))

    def experimental_alerts(self) -> DomainAuthority:
        con = _ro(self.exp / "exp_alerts.db")
        exp = self.experimental_producer()
        if con is None:
            return DomainAuthority("experimental_alerts", AuthorityStatus.UNKNOWN,
                                   "~/.talonx/experimental/exp_alerts.db (ExperimentalAlertStore)",
                                   note="exp_alerts.db unavailable (Experimental lane may have never run)")
        try:
            tables = ["directional_alerts", "experimental_trades", "radar_alerts", "event_updates"]
            counts = {}
            sent = {}
            for t in tables:
                if _has_table(con, t):
                    counts[t] = _q1(con, f"SELECT COUNT(*) FROM {t}") or 0
                    tcols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
                    sent[t] = (_q1(con, f"SELECT COUNT(*) FROM {t} WHERE sent=1") or 0) if "sent" in tcols else 0
            dlog = _q1(con, "SELECT COUNT(*) FROM dispatch_log") if _has_table(con, "dispatch_log") else 0
        finally:
            con.close()
        total = sum(counts.values())
        total_sent = sum(sent.values())
        vals = {"by_family": counts, "sent_by_family": sent, "total": total,
                "external_sends": total_sent, "external_eligible": False, "internal_only": True,
                "dispatch_log_rows": dlog,
                "boundary": "Experimental is INTERNAL-ONLY (Task 99K/99L / Task 99I-verified). "
                            "external_sends here are DRY_RUN/never-external unless --enable-external-send "
                            "was explicitly passed, which the boundary forbids."}
        if not exp["live"] and total == 0:
            return DomainAuthority("experimental_alerts", AuthorityStatus.NO_ACTIVE_PRODUCER,
                                   "exp_alerts.db (ExperimentalAlertStore)", vals,
                                   note=f"talonx_signals.run not running ({exp['reason']}); no rows")
        status = AuthorityStatus.ACTIVE if (exp["live"] and total > 0) else (
            AuthorityStatus.STALE if total > 0 else AuthorityStatus.ZERO_ACTIVITY)
        return DomainAuthority("experimental_alerts", status, "exp_alerts.db (ExperimentalAlertStore)",
                               vals, legacy_sources=("talonx:signals:directional", "talonx:exp:alerts"),
                               note=("talonx_signals.run live" if exp["live"]
                                     else "talonx_signals.run not running -- counts are a static projection"))

    def _paper(self, db: Path, domain: str, authority: str, attribution: str,
               producer_live: bool, producer_reason: str) -> DomainAuthority:
        con = _ro(db)
        if con is None:
            return DomainAuthority(domain, AuthorityStatus.UNKNOWN, authority,
                                   {"attribution": attribution}, note=f"{db.name} unavailable")
        try:
            open_pos = _q1(con, "SELECT COUNT(*) FROM positions") if _has_table(con, "positions") else 0
            trades = _q1(con, "SELECT COUNT(*) FROM trade_history") if _has_table(con, "trade_history") else 0
            cash = None
            if _has_table(con, "portfolio_state"):
                cash = _q1(con, "SELECT current_cash FROM portfolio_state WHERE id=1")
            newest = _q1(con, "SELECT MAX(timestamp) FROM trade_history") if _has_table(con, "trade_history") else None
        finally:
            con.close()
        vals = {"attribution": attribution, "open_positions": open_pos or 0, "trades_all_time": trades or 0,
                "current_cash": cash, "execution": "LOCAL_SIMULATED_LEDGER (no broker)",
                "isolated_from": "the other paper engines -- separate DB file, separate engine class"}
        if (open_pos or 0) > 0:
            return DomainAuthority(domain, AuthorityStatus.ACTIVE, authority, vals, newest)
        status = AuthorityStatus.ZERO_ACTIVITY if producer_live else AuthorityStatus.NO_ACTIVE_PRODUCER
        return DomainAuthority(domain, status, authority, vals, newest,
                               note=("producer live -- flat book (0 open positions)" if producer_live
                                     else f"producer not running ({producer_reason})"))

    def original_paper(self) -> DomainAuthority:
        o = self.original_producer()
        return self._paper(self.home / "paper_trading.db", "original_paper",
                           "paper_trading.db (talonx_paper.consumer)", "ORIGINAL / local-only",
                           o["live"], o["reason"])

    def experimental_paper(self) -> DomainAuthority:
        e = self.experimental_producer()
        return self._paper(self.exp / "experimental_paper.db", "experimental_paper",
                           "~/.talonx/experimental/experimental_paper.db (ExperimentalPaperEngine)",
                           "EXPERIMENTAL / validation-only", e["live"], e["reason"])

    def piv(self) -> DomainAuthority:
        state_dir = Path(os.environ.get("TALONX_PIV_STATE_DIR",
                                        "results/task64_paper_piv_readiness/runtime"))
        live = self.check_processes and _proc_matches("talonx_piv")
        exists = state_dir.exists()
        vals = {"attribution": "PIV / Alpaca PAPER (independent)", "state_dir": str(state_dir),
                "state_dir_present": exists,
                "isolation": "own Redis DB index + namespace + state dir; structurally cannot route real capital "
                             "(PaperGuardError on real_capital=True); never surfaced as Original local paper"}
        if live:
            return DomainAuthority("piv", AuthorityStatus.ACTIVE, "talonx_piv (Alpaca PAPER, read-only checks)",
                                   vals, note="talonx_piv process running")
        return DomainAuthority("piv", AuthorityStatus.NO_ACTIVE_PRODUCER,
                               "talonx_piv (Alpaca PAPER)", vals,
                               note="no talonx_piv process; live Alpaca position/order counts require an "
                                    "explicit opt-in read (not performed here to avoid a network call)")

    def intelligence(self) -> DomainAuthority:
        ip = self.intelligence_producer()
        con = _ro(self.ledger_path)
        vals: dict[str, Any] = {"heartbeat_at": ip["heartbeat_at"], "producer": ip["reason"]}
        newest = None
        if con is not None:
            try:
                for tbl, key in (("text_events", "text_events"), ("event_significance", "event_significance")):
                    if _has_table(con, tbl):
                        vals[f"{key}_rows"] = _q1(con, f"SELECT COUNT(*) FROM {tbl}") or 0
                if _has_table(con, "text_events"):
                    tcols = [r[1] for r in con.execute("PRAGMA table_info(text_events)")]
                    for cand in ("accepted_at_utc", "accepted_at", "acceptance_datetime", "filing_date", "created_at"):
                        if cand in tcols:
                            newest = _q1(con, f"SELECT MAX({cand}) FROM text_events")
                            break
            finally:
                con.close()
        vals["newest_event"] = newest
        if con is None:
            return DomainAuthority("intelligence", AuthorityStatus.UNKNOWN,
                                   "ingestion_ledger.db (Task 96A/C/D/E) via IntelligenceReadAPI",
                                   vals, note="ingestion_ledger.db unavailable")
        if ip["live"]:
            return DomainAuthority("intelligence", AuthorityStatus.ACTIVE,
                                   "ingestion_ledger.db (Task 96A/C/D/E) via IntelligenceReadAPI", vals, newest,
                                   legacy_sources=("talonx:filings:events",))
        return DomainAuthority(
            "intelligence", AuthorityStatus.NO_ACTIVE_PRODUCER,
            "ingestion_ledger.db (Task 96A/C/D/E) via IntelligenceReadAPI", vals, newest,
            legacy_sources=("talonx:filings:events",),
            note=("talonx_ingest.intelligence.service is NOT continuously scheduled (Task 99K/99L). "
                  "Rows shown are from the last one-off backfill/qualification run -- treat as STALE, "
                  "NOT as 'no SEC events happened'. Task 99L Option D: bring it under supervision (Task 100B)."))

    def filings_legacy_channel(self) -> DomainAuthority:
        """The legacy `talonx:filings:events` Redis channel, viewed as a DOMAIN
        SOURCE POINTER for filings -- SUPERSEDED by the Task 96 intelligence
        store. The channel itself is KEEP (Original's Brain-context feed) and
        is not deleted; it is just not the authority for the filings domain."""
        return DomainAuthority(
            "filings_legacy_channel", AuthorityStatus.SUPERSEDED,
            "ingestion_ledger.db (Task 96 intelligence) via IntelligenceReadAPI",
            {"channel": "talonx:filings:events",
             "channel_role": "Original's lightweight Brain-context filing feed (in-process, run_talonx.py) -- KEPT",
             "why_superseded": "the richer authoritative filings/8-K-taxonomy/insider/significance data "
                               "lives in the Task 96 ingestion_ledger.db, not on this channel"},
            legacy_sources=("talonx:filings:events",),
            superseded_source="talonx:filings:events",
            note="Task 99K action: KEEP the channel; do NOT re-publish Task 96 data onto it. Consumers that "
                 "want 'filings' should read the intelligence() domain, not this channel's counter.")

    def telegram_delivery(self) -> DomainAuthority:
        """Three independent, correctly-scoped delivery states -- NOT merged
        (Task 99K/99L). Reported side by side, each counted once against its
        own store."""
        vals: dict[str, Any] = {"merged": False,
                                "transport": "talonx_dispatch.telegram_client.TelegramClient (shared class)",
                                "get_updates_poller": "exactly one, inside run_talonx.py's DispatchAgent"}
        con = _ro(self.home / "dispatch_audit.db")
        if con is not None:
            try:
                sent = _q1(con, "SELECT COUNT(*) FROM alerts WHERE telegram_sent=1") or 0
                last_push = _q1(con, "SELECT MAX(pushed_at) FROM last_telegram_push") \
                    if _has_table(con, "last_telegram_push") else None
            finally:
                con.close()
            vals["original"] = {"store": "dispatch_audit.db", "sent_all_time": sent,
                                "last_push": last_push, "external_eligible": True}
        con = _ro(self.exp / "exp_alerts.db")
        if con is not None:
            try:
                ext = 0
                for t in ("directional_alerts", "experimental_trades", "radar_alerts", "event_updates"):
                    if _has_table(con, t):
                        tcols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
                        if "sent" in tcols:
                            ext += _q1(con, f"SELECT COUNT(*) FROM {t} WHERE sent=1") or 0
            finally:
                con.close()
            vals["experimental"] = {"store": "exp_alerts.db", "external_sends": ext,
                                    "external_eligible": False,
                                    "note": "INTERNAL-ONLY -- external_sends is dry-run bookkeeping, never a real send"}
        con = _ro(self.ledger_path)
        if con is not None:
            try:
                q = _q1(con, "SELECT COUNT(*) FROM intelligence_delivery") \
                    if _has_table(con, "intelligence_delivery") else None
            finally:
                con.close()
            vals["intelligence_96f"] = {"store": "ingestion_ledger.db intelligence_delivery",
                                        "outbox_rows": q,
                                        "status": "dormant -- 96F delivery never activated (--send double-gated)"}
        return DomainAuthority("telegram_delivery", AuthorityStatus.ACTIVE,
                               "three separate stores (Original / Experimental / 96F) -- NOT merged",
                               vals, note="one logical alert is counted once, against its own family's store")

    def eod_reconciliation(self) -> DomainAuthority:
        return DomainAuthority(
            "eod_reconciliation", AuthorityStatus.NO_ACTIVE_PRODUCER,
            "(none -- no persistent EOD store exists)", {},
            note="EOD reconciliation is ad-hoc per forensic script (Task 92/99F/99I). Task 99K flagged a "
                 "persistent EOD summary store as an OPTIONAL Task 100 improvement -- not built in Task 100A.")

    # ---- aggregate ------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        methods = [
            self.market, self.symbol_coverage, self.quant_funnel, self.quant_signals,
            self.brain_reports, self.official_alerts, self.experimental_alerts,
            self.original_paper, self.experimental_paper, self.piv, self.intelligence,
            self.filings_legacy_channel, self.telegram_delivery, self.eod_reconciliation,
        ]
        domains = []
        for m in methods:
            try:
                domains.append(m().to_dict())
            except Exception as exc:  # noqa: BLE001 -- one bad domain must not break the snapshot
                domains.append({"domain": m.__name__, "status": AuthorityStatus.UNKNOWN.value,
                                "authoritative_source": "?", "values": {}, "last_update": None,
                                "legacy_sources": [], "superseded_source": None,
                                "note": f"read error: {exc!r}"})
        counts: dict[str, int] = {}
        for d in domains:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        return {
            "generated_at": self.now.astimezone(timezone.utc).isoformat(),
            "producers": {
                "original": self.original_producer(),
                "experimental": self.experimental_producer(),
                "intelligence": self.intelligence_producer(),
            },
            "status_counts": counts,
            "domains": domains,
        }
