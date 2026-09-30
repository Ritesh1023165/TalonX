"""
FORWARD ALPHA VALIDATION -- CONTROL (unchanged live PAPER_SIGNAL policy) vs SHADOW (pre-registered SQF_V1), per
session and cumulative over sessions >= the hypothesis' validation start. READ-ONLY on production; inputs are the
signal_forensics datasets under results/profitability/.

Acceptance hierarchy (pre-registered, SQF_V1): gross > 0, then net > 0, then profit factor > 1, not concentrated, and
persistent across sessions -- only after >= 10 complete forward sessions. Early failure: with >= 60 SHADOW trades,
if mean gross + 2 standard errors < 0 the premise is reported as failing (no threshold changes during validation).
usage: python -m talonx_paperperf.forward day WINDOW [--live] | cumulative | append WINDOW
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import signal_forensics as F  # noqa: E402
from talonx_paperperf.hypotheses import SQF_V1  # noqa: E402

DOC = REPO / "docs" / "research" / "evidence" / "forward_alpha_validation.md"
H = SQF_V1.horizon


def rows_for(wid: str, live: bool = False) -> list[dict]:
    p = F.OUT / f"{wid}{'_live' if live else ''}.json"
    return json.loads(p.read_text(encoding="utf-8"))["rows"] if p.exists() else []


def windows_done() -> list[str]:
    return sorted(p.stem for p in F.OUT.glob("20??-??-??.json") if p.stem >= SQF_V1.validation_start)


def gross(r, h):
    return r.get(f"act_r{h}")


def side(rows: list[dict], name: str) -> dict:
    g = [gross(r, H) for r in rows if gross(r, H) is not None]
    n = [F.net(r, "act", H) for r in rows if F.net(r, "act", H) is not None]
    gs, ns = F.stats(g), F.stats(n)
    port = F.portfolio(rows, H) if rows else {}
    se = (statistics.stdev(g) / math.sqrt(len(g))) if len(g) > 1 else None
    out = {"name": name, "signals": len(rows), "resolved_30m": len(n),
           "resolved_15m": sum(1 for r in rows if r.get("act_r15") is not None),
           "resolved_60m": sum(1 for r in rows if r.get("act_r60") is not None),
           "gross_30m": gs, "net_30m": ns, "gross_mean_se_pct": round(100 * se, 3) if se else None,
           "mfe": F.stats([r.get("act_mfe") for r in rows]), "mae": F.stats([r.get("act_mae") for r in rows]),
           "portfolio_30m": port, "concentration_30m": F.concentration(rows, H) if n else {},
           "descriptive_net": {h: F.stats([F.net(r, "act", h) for r in rows]) for h in ("15", "60", "close")}}
    kept = [r for r in rows if not str(r.get("shadow_state")).startswith(("MISSED", "UNKNOWN"))]
    out["dtu"] = {"retained": len(kept), "event_recovered": sum(1 for r in kept if str(r.get("shadow_state"))
                                                                 .startswith("EVENT_PROMOTED")),
                  "missed": sum(1 for r in rows if str(r.get("shadow_state")).startswith("MISSED")),
                  "unknown": sum(1 for r in rows if str(r.get("shadow_state")).startswith("UNKNOWN")),
                  "FULL_NET_PNL": round(sum(x for x in n) * F.POSITION_USD, 2),
                  "DTU_NET_PNL": round(sum(F.net(r, "act", H) for r in kept if F.net(r, "act", H) is not None)
                                       * F.POSITION_USD, 2)}
    return out


def verdict(s: dict, sessions: int) -> str:
    g, n = s["gross_30m"], s["net_30m"]
    if not g.get("n"):
        return "NO_DATA"
    if g["n"] >= 60 and s["gross_mean_se_pct"] is not None and g["mean_pct"] + 2 * s["gross_mean_se_pct"] < 0:
        return "EARLY_FAILURE_CANDIDATE (gross clearly <= 0)"
    if sessions < SQF_V1.min_forward_sessions:
        return f"IN_PROGRESS ({sessions}/{SQF_V1.min_forward_sessions} sessions; gross {g['mean_pct']:+.3f}%, net {n['mean_pct']:+.3f}%)"
    pf = n.get("profit_factor") or 0
    conc = s["concentration_30m"]
    if g["mean_pct"] > 0 and n["mean_pct"] > 0 and pf > 1 and (conc.get("mean_without_best_3_pct") or -1) > 0:
        return "PRELIMINARY_FORWARD_EDGE"
    return "FAILED (gross/net/PF gate)"


def report(wids: list[str], live: bool = False) -> dict:
    rows = [r for w in wids for r in rows_for(w, live)]
    ctl = side(rows, "CONTROL")
    shw = side([r for r in rows if r.get("shadow_filter_pass")], "SHADOW_SQF_V1")
    drift = [r["entry_drift_pct"] for r in rows if r.get("entry_drift_pct") is not None]
    lat = [r["data_as_of_to_send_s"] for r in rows if r.get("data_as_of_to_send_s") is not None]
    fail = {}
    for r in rows:
        for x in filter(None, (r.get("shadow_filter_fail_reason") or "").split(";")):
            fail[x] = fail.get(x, 0) + 1
    return {"windows": wids, "live": live, "control": ctl, "shadow": shw, "shadow_fail_reasons": fail,
            "entry_drift_median_pct": round(statistics.median(drift), 3) if drift else None,
            "data_to_send_median_s": statistics.median(lat) if lat else None,
            "control_verdict": verdict(ctl, len(wids)), "shadow_verdict": verdict(shw, len(wids)),
            "hypothesis": {"id": SQF_V1.hypothesis_id, "fingerprint": SQF_V1.fingerprint(),
                           "validation_start": SQF_V1.validation_start}}


def fmt(v, k="mean_pct"):
    return "n/a" if not v or v.get(k) is None else f"{v[k]:+.3f}%"


def checkpoint(rep: dict, title: str) -> str:
    c, s = rep["control"], rep["shadow"]

    def pnl(x):
        return x["portfolio_30m"].get("NET_PNL", 0) if x["portfolio_30m"] else 0
    conc = c["concentration_30m"]
    return "\n".join([
        f"DATE: {title}", "",
        f"CONTROL_SIGNALS: {c['signals']}", f"CONTROL_RESOLVED_30M: {c['resolved_30m']}",
        f"CONTROL_GROSS_30M: {fmt(c['gross_30m'])}", f"CONTROL_NET_30M: {fmt(c['net_30m'])}",
        f"CONTROL_WIN_RATE: {c['net_30m'].get('win_rate')}", f"CONTROL_PROFIT_FACTOR: {c['net_30m'].get('profit_factor')}",
        f"CONTROL_PNL: ${pnl(c):,.2f} (max DD ${c['portfolio_30m'].get('MAX_DRAWDOWN', 0):,.2f})", "",
        f"SHADOW_ELIGIBLE: {s['signals']}", f"SHADOW_RESOLVED: {s['resolved_30m']}",
        f"SHADOW_GROSS_30M: {fmt(s['gross_30m'])}", f"SHADOW_NET_30M: {fmt(s['net_30m'])}",
        f"SHADOW_WIN_RATE: {s['net_30m'].get('win_rate')}", f"SHADOW_PROFIT_FACTOR: {s['net_30m'].get('profit_factor')}",
        f"SHADOW_PNL: ${pnl(s):,.2f} (max DD ${s['portfolio_30m'].get('MAX_DRAWDOWN', 0) if s['portfolio_30m'] else 0:,.2f})",
        "",
        f"CONTROL_VS_SHADOW: net30 {fmt(c['net_30m'])} vs {fmt(s['net_30m'])}; gross30 {fmt(c['gross_30m'])} vs "
        f"{fmt(s['gross_30m'])}; shadow fail reasons {rep['shadow_fail_reasons']}",
        f"ENTRY_DRIFT_MEDIAN: {rep['entry_drift_median_pct']}%  (data_as_of->send median {rep['data_to_send_median_s']} s)",
        f"DTU_CONTROL_CAPTURE: {c['dtu']['retained']}/{c['signals']} (event-recovered {c['dtu']['event_recovered']}, "
        f"missed {c['dtu']['missed']}, unknown {c['dtu']['unknown']}; P&L full ${c['dtu']['FULL_NET_PNL']:,.0f} vs "
        f"DTU ${c['dtu']['DTU_NET_PNL']:,.0f})",
        f"DTU_SHADOW_CAPTURE: {s['dtu']['retained']}/{s['signals']} (P&L full ${s['dtu']['FULL_NET_PNL']:,.0f} vs "
        f"DTU ${s['dtu']['DTU_NET_PNL']:,.0f})",
        f"TOP3_CONCENTRATION (control): top3 {conc.get('top_3_contribution_pct_points')} pp; mean without best 3 "
        f"{conc.get('mean_without_best_3_pct')}%",
        f"CURRENT_VERDICT: CONTROL = {rep['control_verdict']} | SHADOW = {rep['shadow_verdict']}"])


def append_session(wid: str) -> bool:
    """Append ONE session section to the cumulative doc (idempotent; never rewrites an existing section)."""
    marker = f"<!-- session:{wid} -->"
    text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if marker in text:
        return False
    day = report([wid])
    cum = report(windows_done())
    block = "\n".join(["", marker, f"## Session {wid} (appended {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ})", "",
                       "```", checkpoint(day, wid), "```", "",
                       f"Cumulative since {SQF_V1.validation_start} ({len(cum['windows'])} sessions):", "", "```",
                       checkpoint(cum, "CUMULATIVE " + ",".join(cum["windows"])), "```", ""])
    with open(DOC, "a", encoding="utf-8") as fh:
        fh.write(block)
    return True


def main(argv):
    if argv[0] == "day":
        live = "--live" in argv
        print(checkpoint(report([argv[1]], live), argv[1] + (" (LIVE)" if live else "")))
    elif argv[0] == "cumulative":
        print(checkpoint(report(windows_done()), "CUMULATIVE " + ",".join(windows_done())))
    elif argv[0] == "append":
        print("appended" if append_session(argv[1]) else "already present")


if __name__ == "__main__":
    main(sys.argv[1:])
