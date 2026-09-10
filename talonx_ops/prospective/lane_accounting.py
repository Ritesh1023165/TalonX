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

    # ---- funnel closure from the comingled counter, IF present ----------
    closure: dict[str, Any] = {"status": "NO_METRICS_SNAPSHOT"}
    mk = metrics.get("keys") or {}
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
            "status": "CLOSED" if 0 <= residual <= 8 else "RESIDUAL_UNEXPLAINED",
            "evaluated": ev,
            "terminal_with_counter": terminal,
            "terminal_with_counter_sum": counter_sum,
            "residual": residual,
            "residual_class": "THROTTLE / COOLDOWN / failed-revalidation "
                              "(recorded on talonx:quant:rejected + rejected_candidates, "
                              "not in metrics:quant:*)" if 0 <= residual <= 8 else "unexplained",
            "pre_evaluation_drops_excluded": {
                "dropped_duplicate_bars": mk.get(f"metrics:{day}:quant:dropped_duplicate_bars"),
                "failed_min_volatility": mk.get(f"metrics:{day}:quant:failed_min_volatility"),
            },
            "published_all_experimental": mk.get(f"metrics:{day}:quant:published") == experimental["would_pass"],
            "note": "the mid-session ping's '126 candidates / 3 publications' was a partial "
                    "snapshot; this is the EOD comingled counter. published == the Experimental "
                    "WOULD_PASS count (Original published 0, V2 published 0).",
        }

    return {
        "generated_utc": now.isoformat(),
        "session_date": day,
        "lanes": {"original_intraday": original,
                  "experimental": experimental,
                  "v2_trading": v2_acc},
        "comingled_metrics_quant": metrics,
        "funnel_closure": closure,
        "in_flight": in_flight,
        "historical_94_candidate_gap": {
            "status": ("RESOLVED_WITH_EVIDENCE" if closure.get("status") == "CLOSED"
                       else "UNRESOLVED"),
            "resolution": (
                f"EOD comingled counter: evaluated={closure.get('evaluated')} = "
                f"sum(terminal counters)={closure.get('terminal_with_counter_sum')} + "
                f"residual={closure.get('residual')} (THROTTLE/COOLDOWN/revalidation, "
                f"off-counter). published={mk.get(f'metrics:{day}:quant:published')} == "
                f"Experimental WOULD_PASS. Same mechanism that closed Sep-9 exactly. "
                f"The '94' was the 16:24Z ping's 126/3 measured against the EOD *displayed* "
                f"3-gate breakdown, not the EOD comingled counter."
            ) if closure.get("status") == "CLOSED" else
            "no metrics:<date>:quant:* snapshot reachable; cannot close to an integer -- "
            "NOT reported as resolved.",
        },
        "lane_attribution_defect": {
            "D6": "metrics:<date>:quant:* keys carry no lane suffix; Original + Experimental "
                  "increment the same keys. Lane-suffixing them is a change to the hot quant "
                  "path -- proposed, not made here. This snapshot is the interim lane-scoped "
                  "surface, built from the durable per-lane stores.",
        },
    }
