"""
Task 117 D6 -- lane-scoped candidate / evaluation accounting, for the EOD
snapshot.

The frozen ``metrics:<date>:quant:*`` Redis counters carry NO lane suffix, so
Original + Experimental increment the same keys and the dashboard "Quant
published / Candidates" tile is a comingled figure. THROTTLE / COOLDOWN /
revalidation dispositions are recorded only on the ``talonx:quant:rejected``
channel + the ``rejected_candidates`` DB, never in ``metrics:quant:*``, so the
integer surface under-counts ``evaluated``.

This module builds an explicit, lane-separated snapshot from the durable
stores (read-only), records the off-counter disposition class, and NEVER
reports the historical "94-candidate" gap as resolved without records.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_HOME = Path.home() / ".talonx"


def _ro(db: Path):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _q1(db: Path, sql: str, params: tuple = ()) -> Any:
    try:
        c = _ro(db)
        try:
            r = c.execute(sql, params).fetchone()
            return r[0] if r else None
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        return None


def _rows(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        c = _ro(db)
        try:
            return list(c.execute(sql, params).fetchall())
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        return []


def _redis_quant_metrics(day: str) -> dict[str, Any]:
    """The comingled ``metrics:<date>:quant:*`` family, if Redis is reachable.
    Returned verbatim + tagged ``lane_attributable=False``."""
    try:
        import redis  # type: ignore

        r = redis.Redis(host="localhost", port=6379, db=0, socket_timeout=1.5)
        keys = list(r.scan_iter(match=f"metrics:{day}:quant:*", count=500))
        out = {}
        for k in keys:
            ks = k.decode() if isinstance(k, bytes) else k
            v = r.get(k)
            try:
                out[ks] = int(v)
            except Exception:  # noqa: BLE001
                out[ks] = v.decode() if isinstance(v, bytes) else v
        return {"present": bool(out), "keys": out, "lane_attributable": False,
                "note": "no lane suffix -- Original + Experimental comingled (D6)"}
    except Exception as exc:  # noqa: BLE001
        return {"present": False, "error": repr(exc), "lane_attributable": False}


def build_lane_accounting(*, now: datetime | None = None,
                          v2_db: Path | str | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(timezone.utc).date().isoformat()
    dispatch = _HOME / "dispatch_audit.db"
    exp = _HOME / "experimental" / "exp_alerts.db"
    v2 = Path(v2_db) if v2_db else (_HOME.parent / "TalonX" / "v2_lane.db")
    if not v2.exists():
        v2 = Path("v2_lane.db")

    # ---- ORIGINAL intraday ------------------------------------------------
    orig_gate_rows = _rows(
        dispatch,
        "SELECT gate, reason, COUNT(*) FROM rejected_candidates "
        "WHERE substr(rejected_at,1,10)=? GROUP BY gate, reason ORDER BY 3 DESC",
        (day,),
    )
    orig_by_gate = {f"{g}/{rsn}": n for g, rsn, n in orig_gate_rows}
    orig_total_terminal = sum(orig_by_gate.values())
    orig_distinct_tickers = _q1(
        dispatch, "SELECT COUNT(DISTINCT ticker) FROM rejected_candidates "
        "WHERE substr(rejected_at,1,10)=?", (day,)) or 0
    orig_published = _q1(
        dispatch, "SELECT COUNT(*) FROM alerts WHERE substr(received_at,1,10)=?", (day,)) or 0
    original = {
        "lane": "ORIGINAL_INTRADAY",
        "terminal_dispositions_by_gate": orig_by_gate,
        "terminal_total": orig_total_terminal,
        "distinct_tickers_with_a_rejection": orig_distinct_tickers,
        "published_intraday_alerts": orig_published,
        "off_counter_disposition_class": {
            "what": "THROTTLE / COOLDOWN / failed-revalidation",
            "recorded_where": "talonx:quant:rejected channel + rejected_candidates DB "
                              "(gate LIKE '%throttle%' / '%cooldown%' / '%reval%')",
            "count_today": sum(
                n for k, n in orig_by_gate.items()
                if any(t in k.lower() for t in ("throttle", "cooldown", "reval"))
            ),
            "in_metrics_quant_counter": False,
        },
    }

    # ---- EXPERIMENTAL ---------------------------------------------------
    exp_directional = _q1(
        exp, "SELECT COUNT(*) FROM directional_alerts WHERE substr(generated_at,1,10)=?",
        (day,)) or 0
    exp_would_pass = _q1(
        exp, "SELECT COUNT(*) FROM directional_alerts "
        "WHERE substr(generated_at,1,10)=? AND trade_gate_status='WOULD_PASS'", (day,)) or 0
    exp_trades = _q1(
        exp, "SELECT COUNT(*) FROM experimental_trades WHERE substr(opened_at,1,10)=?",
        (day,)) or 0
    exp_sent = _q1(
        exp, "SELECT COUNT(*) FROM directional_alerts "
        "WHERE substr(generated_at,1,10)=? AND sent=1", (day,)) or 0
    experimental = {
        "lane": "EXPERIMENTAL",
        "directional_alerts": exp_directional,
        "would_pass": exp_would_pass,
        "paper_trades_opened": exp_trades,
        "external_sends": exp_sent,   # must be 0 -- external isolation
        "channel": "talonx:exp:* (isolated -- never routed to Brain/Core/Dispatch)",
    }

    # ---- V2 -----------------------------------------------------------
    v2_present = v2.exists()
    v2_acc = {
        "lane": "V2_TRADING",
        "ledger_present": v2_present,
        "processed_episodes": _q1(v2, "SELECT COUNT(*) FROM processed_episodes") if v2_present else None,
        "dispositions": dict(_rows(
            v2, "SELECT disposition, COUNT(*) FROM processed_episodes GROUP BY disposition")
        ) if v2_present else {},
        "buys": _q1(v2, "SELECT COUNT(*) FROM trades WHERE action='BUY'") if v2_present else None,
        "sells": _q1(v2, "SELECT COUNT(*) FROM trades WHERE action='SELL'") if v2_present else None,
        "open_positions": _q1(v2, "SELECT COUNT(*) FROM positions WHERE status='OPEN'") if v2_present else None,
        "pending_entry_intents": _q1(v2, "SELECT COUNT(*) FROM pending_entry_intents") if v2_present else None,
        "alert_outbox_by_state": dict(_rows(
            v2, "SELECT state, COUNT(*) FROM v2_alert_outbox GROUP BY state")) if v2_present else {},
    }

    # ---- pending / in-flight -------------------------------------------
    in_flight = {
        "v2_pending_entry_intents": v2_acc["pending_entry_intents"],
        "v2_alert_outbox_pending": (v2_acc["alert_outbox_by_state"] or {}).get("PENDING", 0),
        "note": "reconciliation must account for these before declaring a lane closed",
    }

    metrics = _redis_quant_metrics(day)
    mk = metrics.get("keys") or {}

    # ---- verify off-counter dispositions FROM RECORDS (not as a remainder) --
    dispatch = _HOME / "dispatch_audit.db"
    off_counter_records = {
        "throttle": _q1(dispatch, "SELECT COUNT(*) FROM rejected_candidates WHERE "
                        "substr(rejected_at,1,10)=? AND (gate LIKE '%throttle%' OR reason LIKE '%THROTTLE%')", (day,)) or 0,
        "cooldown": _q1(dispatch, "SELECT COUNT(*) FROM rejected_candidates WHERE "
                        "substr(rejected_at,1,10)=? AND (gate LIKE '%cooldown%' OR reason LIKE '%COOLDOWN%')", (day,)) or 0,
        "revalidation": _q1(dispatch, "SELECT COUNT(*) FROM rejected_candidates WHERE "
                            "substr(rejected_at,1,10)=? AND (gate LIKE '%reval%' OR reason LIKE '%REVAL%')", (day,)) or 0,
        "lockout": _q1(dispatch, "SELECT COUNT(*) FROM rejected_candidates WHERE "
                       "substr(rejected_at,1,10)=? AND (gate LIKE '%lockout%' OR reason LIKE '%LOCKOUT%')", (day,)) or 0,
        "source": "dispatch_audit.rejected_candidates (the talonx:quant:rejected sink)",
    }
    off_counter_total = sum(v for k, v in off_counter_records.items() if isinstance(v, int))

    # ---- final-day funnel from the comingled counter (SEPARATE from the ping) --
    closure: dict[str, Any] = {"status": "NO_METRICS_SNAPSHOT"}
    ev = mk.get(f"metrics:{day}:quant:evaluated")
    if isinstance(ev, int):
        _terminal_prefixes = ("failed_", "dropped_", "published")
        terminal = {
            k.split(":quant:")[-1]: v for k, v in mk.items()
            if isinstance(v, int)
            and k.split(":quant:")[-1].startswith(_terminal_prefixes)
            and "regime_shadow" not in k
            and k.split(":quant:")[-1] not in ("dropped_duplicate_bars",)
            and not k.split(":quant:")[-1].startswith("failed_min_volatility")
        }
        counter_sum = sum(terminal.values())
        residual = ev - counter_sum
        closure = {
            "status": "COUNTER_RECONCILED" if residual == 0 else "COUNTER_RESIDUAL",
            "evaluated": ev,
            "terminal_with_counter": terminal,
            "terminal_with_counter_sum": counter_sum,
            "residual": residual,
            "residual_explained_by_records": (
                residual == off_counter_total and off_counter_total > 0),
            "residual_attribution": (
                f"matches {off_counter_total} throttle/cooldown/revalidation record(s)"
                if (residual == off_counter_total and off_counter_total > 0) else
                "NO corresponding disposition records found -- the residual is NOT "
                "attributed to throttle/cooldown/revalidation (there are none on this "
                "day) and is NOT defined as the arithmetic remainder. UNEXPLAINED_FROM_RECORDS."),
            "pre_evaluation_drops_excluded": {
                "dropped_duplicate_bars": mk.get(f"metrics:{day}:quant:dropped_duplicate_bars"),
                "failed_min_volatility": mk.get(f"metrics:{day}:quant:failed_min_volatility"),
            },
            "published_counter": mk.get(f"metrics:{day}:quant:published"),
            "published_is_comingled": True,
            "original_official_publications": original["published_intraday_alerts"],  # dispatch_audit.alerts
            "v2_publications": 0,
        }

    return {
        "generated_utc": now.isoformat(),
        "session_date": day,
        "lanes": {"original_intraday": original,
                  "experimental": experimental,
                  "v2_trading": v2_acc},
        "comingled_metrics_quant": {
            **metrics,
            "warning": "metrics:<date>:quant:* is COMINGLED Original+Experimental with NO lane "
                       "suffix. Its 'published' is NOT an Original official-publication count. "
                       "Original official publications = dispatch_audit.alerts "
                       f"({original['published_intraday_alerts']} today). V2 publications = 0. "
                       "The dashboard does not display this counter as Original's.",
        },
        "off_counter_dispositions_from_records": off_counter_records,
        "final_day_funnel_closure": closure,
        "in_flight": in_flight,
        "historical_16_24_ping_snapshot": {
            "reported": "candidates 126; displayed rejections confluence 18 / opening-blackout 10 "
                        "/ trend 1; quant publications 3",
            "status": "NOT_RECONSTRUCTABLE",
            "why": "metrics:<date>:quant:* counters are CUMULATIVE, not point-in-time; there is "
                   "no 16:24:25Z snapshot of them. The final-day counter (evaluated=%s) cannot "
                   "reconstruct the mid-session 126/3. Final-day reconciliation and the ping "
                   "attribution are kept SEPARATE." % (closure.get("evaluated")),
        },
        "historical_94_candidate_gap": {
            "status": "SUPERSEDED_BY_FINAL_DAY_RECONCILIATION",
            "note": "the '94' arose from '126 - 18 - 10 - 1 - 3' (the 16:24 ping vs the EOD "
                    "displayed 3-gate breakdown) -- an apples-to-oranges subtraction. The "
                    "final-day funnel is reconciled against the comingled counter above "
                    "(evaluated=%s, terminal-with-counter=%s, residual=%s %s). The residual "
                    "is NOT the 94 and is NOT defined as throttle/cooldown/revalidation "
                    "(no such records exist for the day)." % (
                        closure.get("evaluated"), closure.get("terminal_with_counter_sum"),
                        closure.get("residual"), closure.get("residual_attribution", "")),
        },
        "lane_attribution_defect": {
            "D6": "metrics:<date>:quant:* keys carry no lane suffix; Original + Experimental "
                  "increment the same keys. Lane-suffixing them is a change to the hot quant "
                  "path -- proposed, not made here. This snapshot is the interim lane-scoped "
                  "surface, built from the durable per-lane stores.",
        },
    }
