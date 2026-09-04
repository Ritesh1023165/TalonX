"""Task 99A -- EOD attribution report generator.

Reads the three ISOLATED talonx_signals stores (exp_alerts.db /
forward_outcomes.db / experimental_paper.db) plus caller-supplied
market/dispatch/premarket context, and renders ``TASK99A_EOD_REPORT.md``.

Mandatory framing line, emitted verbatim:
    ONE_DAY_PROFITABILITY_RESULT = OBSERVATIONAL_ONLY
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.telemetry import ForwardOutcomeStore

_PROFILE_CONTROL = "FROZEN_CONTROL"
_PROFILE_EXPERIMENTAL = "EXPERIMENTAL_RELAXED_V1"
OBSERVATIONAL_LINE = "ONE_DAY_PROFITABILITY_RESULT = OBSERVATIONAL_ONLY"


def _fmt(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _tbl(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_none_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "|" + "|".join("---" for _ in headers) + "|\n"
    for r in rows:
        out += "| " + " | ".join("" if c is None else str(c) for c in r) + " |\n"
    return out


def generate_eod_report(
    alert_store: ExperimentalAlertStore,
    outcome_store: ForwardOutcomeStore,
    *,
    session_meta: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
    premarket: Any = None,
    telegram: dict[str, Any] | None = None,
    paper_positions: list[dict] | None = None,
    dashboard: dict[str, Any] | None = None,
) -> str:
    meta = session_meta or {}
    market = market or {}
    telegram = telegram or {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with alert_store._lock:  # noqa: SLF001 - read-only, same module family
        directional = [dict(r) for r in alert_store._conn.execute(
            "SELECT * FROM directional_alerts ORDER BY bar_timestamp"
        ).fetchall()]
        trades = [dict(r) for r in alert_store._conn.execute(
            "SELECT * FROM experimental_trades ORDER BY created_at"
        ).fetchall()]
        radar = [dict(r) for r in alert_store._conn.execute("SELECT * FROM radar_alerts").fetchall()]
        events = [dict(r) for r in alert_store._conn.execute("SELECT * FROM event_updates").fetchall()]
    outcomes = outcome_store.all_rows()
    obs_by_source = {o["source_id"]: o for o in outcomes}

    def _dir(profile, direction):
        return [d for d in directional
                if d["profile"] == profile and str(d["direction"]).upper().endswith(direction)]

    lines: list[str] = []
    lines.append(f"# TASK99A_EOD_REPORT\n")
    lines.append(f"_generated {now} -- {OBSERVATIONAL_LINE}_\n")
    lines.append(f"- session start / stop: {meta.get('session_start', '?')} -> {meta.get('session_stop', '?')}")
    lines.append(f"- frozen control config: unchanged (`PRODUCTION_STRATEGY_UNCHANGED`)")
    lines.append(f"- experimental profile: `{_PROFILE_EXPERIMENTAL}` "
                 f"(min_atr_pct 0.10, confluence_score_min 1, min_risk_reward_ratio 1.0) -- paper-only\n")

    # ---- Market / feed ----
    lines.append("## Market / feed\n")
    lines.append(_tbl(["metric", "value"], [
        ["events / bars received", market.get("events", "?")],
        ["last event timestamp", market.get("last_event_at", "?")],
        ["coverage", market.get("coverage", "?")],
        ["provider failures", market.get("provider_failures", 0)],
        ["retries", market.get("retries", 0)],
        ["feed status", market.get("status", "?")],
    ]))

    # ---- Pre-market ----
    lines.append("## Pre-market\n")
    if premarket is not None:
        pm = premarket if isinstance(premarket, dict) else premarket.model_dump(mode="json")
        lines.append(_tbl(["surface", "count", "symbols"], [
            [k, len(pm.get(k, [])), ", ".join(w["symbol"] for w in pm.get(k, []))]
            for k in ("radar", "gap_up", "gap_down", "abnormal_volume",
                      "bullish_watch", "bearish_watch", "event_context")
        ]))
    else:
        lines.append("_no pre-market scan recorded_\n")

    # ---- Intelligence family ----
    lines.append("## Intelligence alerts\n")
    lines.append(f"- earnings RADAR: {len(radar)}  (sent {sum(r['sent'] for r in radar)})")
    lines.append(f"- SEC / post-earnings / fundamental updates: {len(events)}  "
                 f"(sent {sum(e['sent'] for e in events)})\n")

    # ---- Directional informational alerts ----
    lines.append("## Informational directional alerts\n")
    for profile in (_PROFILE_CONTROL, _PROFILE_EXPERIMENTAL):
        b, r = _dir(profile, "BULLISH"), _dir(profile, "BEARISH")
        lines.append(f"### {profile}: {len(b)} bullish / {len(r)} bearish\n")
        rows = []
        for d in b + r:
            o = obs_by_source.get(d["alert_id"], {})
            rows.append([
                d.get("bar_timestamp"), d["symbol"], str(d["direction"]).split(".")[-1],
                d.get("setup_type"), d.get("setup_score"),
                _fmt(o.get("r_30m")), _fmt(o.get("r_60m")), _fmt(o.get("r_eod")),
                o.get("status", "no-obs"),
            ])
        lines.append(_tbl(["time", "sym", "dir", "setup", "score",
                           "+30m%", "+60m%", "EOD%", "status"], rows))

    # ---- Control funnel ----
    lines.append("## Control (FROZEN_CONTROL)\n")
    c_dir = [d for d in directional if d["profile"] == _PROFILE_CONTROL]
    c_rej: dict[str, int] = {}
    for d in c_dir:
        rr = d.get("trade_gate_reject_reason")
        if rr:
            c_rej[rr] = c_rej.get(rr, 0) + 1
    lines.append(_tbl(["metric", "value"], [
        ["directional candidates", len(c_dir)],
        ["would-pass trade gate", sum(1 for d in c_dir if d.get("trade_gate_status") == "WOULD_PASS")],
        ["control trades", meta.get("control_trades", 0)],
    ]))
    lines.append("Rejection funnel:\n")
    lines.append(_tbl(["reason", "count"], sorted(c_rej.items())))

    # ---- Experimental funnel ----
    lines.append("## Experimental (EXPERIMENTAL_RELAXED_V1)\n")
    e_dir = [d for d in directional if d["profile"] == _PROFILE_EXPERIMENTAL]
    buys = [t for t in trades if str(t["side"]).upper() == "BUY"]
    exits = [t for t in trades if str(t["side"]).upper() == "SELL"]
    net = sum(float(t["net_pnl"] or 0) for t in exits)
    gross = sum(float(t["gross_pnl"] or 0) for t in exits)
    lines.append(_tbl(["metric", "value"], [
        ["directional candidates", len(e_dir)],
        ["experimental BUYs", len(buys)],
        ["exits", len(exits)],
        ["gross P&L", _fmt(gross)],
        ["est. costs", _fmt(gross - net)],
        ["net P&L", _fmt(net)],
        ["open positions at report time", len(paper_positions or [])],
    ]))
    lines.append("Per experimental trade:\n")
    trade_rows = []
    for t in buys:
        matching_exit = next((x for x in exits if x["symbol"] == t["symbol"]), None)
        o = obs_by_source.get(t["trade_id"], {})
        trade_rows.append([
            t["symbol"], t.get("admitted_by"), _fmt(t.get("entry")),
            _fmt((matching_exit or {}).get("exit")),
            _fmt((matching_exit or {}).get("net_pnl")),
            _fmt((matching_exit or {}).get("r_multiple")),
            _fmt(o.get("mfe")), _fmt(o.get("mae")),
        ])
    lines.append(_tbl(["sym", "admitted_by", "entry", "exit", "net P&L", "R", "MFE%", "MAE%"], trade_rows))
    admit_counts: dict[str, int] = {}
    for t in buys:
        admit_counts[t.get("admitted_by") or "?"] = admit_counts.get(t.get("admitted_by") or "?", 0) + 1
    lines.append("Relaxation attribution (which relaxed rule admitted each BUY):\n")
    lines.append(_tbl(["admitted_by", "count"], sorted(admit_counts.items())))

    # ---- Comparison ----
    lines.append("## CONTROL vs EXPERIMENTAL_RELAXED_V1\n")
    lines.append(_tbl(["metric", "FROZEN_CONTROL", "EXPERIMENTAL_RELAXED_V1"], [
        ["directional alerts", len(c_dir), len(e_dir)],
        ["  bullish", len(_dir(_PROFILE_CONTROL, "BULLISH")), len(_dir(_PROFILE_EXPERIMENTAL, "BULLISH"))],
        ["  bearish", len(_dir(_PROFILE_CONTROL, "BEARISH")), len(_dir(_PROFILE_EXPERIMENTAL, "BEARISH"))],
        ["trades", meta.get("control_trades", 0), len(buys)],
        ["net P&L", "-", _fmt(net)],
    ]))

    # ---- Telegram ----
    lines.append("## Telegram\n")
    lines.append(_tbl(["metric", "value"], [
        ["external send enabled", telegram.get("external_send_enabled", False)],
        ["sent", telegram.get("sent", 0)],
        ["failed", telegram.get("failed", 0)],
        ["duplicates skipped", telegram.get("duplicates", 0)],
        ["retries", telegram.get("retries", 0)],
        ["held (dry-run)", telegram.get("held", 0)],
    ]))

    # ---- Dashboard ----
    lines.append("## Dashboard\n")
    lines.append(_tbl(["metric", "value"], [
        ["served", (dashboard or {}).get("served", "?")],
        ["data completeness", (dashboard or {}).get("completeness", "?")],
    ]))

    # ---- Paper ----
    lines.append("## Paper (experimental_paper.db)\n")
    lines.append(_tbl(["metric", "value"], [
        ["orders (BUY/SELL)", f"{len(buys)}/{len(exits)}"],
        ["open positions at close", len(paper_positions or [])],
        ["final reconciliation", "flat" if not (paper_positions or []) else "OPEN POSITIONS REMAIN"],
    ]))

    lines.append(f"\n---\n**{OBSERVATIONAL_LINE}** -- one day of paper observation is not validation of an edge.\n")
    return "\n".join(lines)
