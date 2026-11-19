"""LOCAL renderer for the PROPOSED research-alert template (review evidence only -- NOT wired into production, never
sends anything). Input: sample.json from review_sample.py. Uses only values recorded at generation time; the message
"written" instant is the outbox creation time (when production renders the text). Telegram acknowledgement time is
known only after sending, so it appears only in the separate AUDIT annotation, never in the message.

usage: python render_proposed.py sample.json > rendered_examples.md
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
REVIEW_START = "2026-10-07"           # research-review alerts restored 2026-10-07 22:42:55Z
VERDICT_REF = "docs/research/evidence/2026-10-07_review_alert_restoration.md"
EXAMPLES = ("APO", "CF", "PBR", "PANW")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def et(s, sec=False):
    return ts(s).astimezone(ET).strftime("%H:%M:%S" if sec else "%H:%M")


def px(v):
    return f"${v:,.2f}" if v >= 1 else f"${v:.4f}"


def catalyst_line(c: str | None) -> str:
    if not c:
        return "UNKNOWN (not recorded)"
    if c == "none found":
        return "none in SEC filings (since prior session) or insider purchases (30d); news not checked"
    if c.startswith("catalyst lookup incomplete") or "lookup incomplete" in c:
        return f"UNKNOWN: {c}; news not checked"
    return f"{c} (SEC record; link to this move not assessed); news not checked"


def structure_line(t: dict) -> str:
    pos = t.get("range_position")
    if pos == "ABOVE_PREV_HIGH":
        return f"above prior-day high {px(t['prev_high'])} by {t['range_distance_pct']:.2f}%"
    if pos == "INSIDE_PREV_RANGE":
        return f"still inside prior-day range (high {px(t['prev_high'])})"
    return (pos or "UNKNOWN").replace("_", " ").lower()


def repeat_line(i: dict) -> str:
    r = i["repeat"]
    if r["earlier_in_same_window"]:
        return f"{r['earlier_in_same_window']} earlier alert(s) for {i['symbol']} today"
    if r["earlier_review_alerts_for_symbol"]:
        return (f"also alerted {r['latest_earlier_window']} (earlier session). Today is a new move vs today's prior "
                f"close, not an update of that alert")
    return f"first research alert for {i['symbol']} since review alerts began ({REVIEW_START})"


def render(i: dict) -> str:
    t, p, tm = i["trigger"], i["price"], i["timing_utc"]
    written = tm["outbox_created"]
    age = int((ts(written) - ts(p["data_as_of_utc"])).total_seconds() // 60)
    bar_end = (ts(p["last_bar_start_utc"]) + timedelta(minutes=1)).isoformat() if p.get("last_bar_start_utc") else None
    gapx = abs(t["gap_pct_vs_prev_close"]) / t["atr20_pct"] if t.get("atr20_pct") else None
    lines = [
        "🔎 RESEARCH OPPORTUNITY — UNVALIDATED",
        "For review only · no order placed · not a buy instruction",
        "",
        f"{i['symbol']} — up {abs(t['gap_pct_vs_prev_close']):.2f}% vs prior close {px(t['prev_close'])}",
        f"Setup: upward move, rule label BULLISH (describes the move, not a forecast); {t['reason']}",
        "",
        f"Why flagged (data as of {et(p['data_as_of_utc'])} ET):",
        f"• Move {t['gap_pct_vs_prev_close']:+.2f}% vs prior close"
        + (f" = {gapx:.1f}× its 20-day average range" if gapx is not None else ""),
        f"• Volume since 04:00 ET {t['window_to_date_volume_sh']:,.0f} sh = "
        f"{t['volume_fraction_of_adv20'] * 100:.1f}% of 20-day average",
        f"• Price {structure_line(t)}",
        f"• Catalyst: {catalyst_line(i['catalyst_as_generated'])}",
        "",
        f"Price {px(p['reference_price'])} = last 1-min bar close at {et(bar_end) if bar_end else 'UNKNOWN'} ET, "
        f"{p.get('provider_delay_min') or 'UNKNOWN'}-min delayed feed. Not a live quote.",
        f"Data age when written: {age} min (detected {et(tm['candidate_event'])} ET, written {et(written)} ET)",
        "Horizon: today's session only, to the 16:00 ET close (INTRADAY and SAME_DAY both end then). "
        "No exit or holding period is defined.",
        f"Rule score {i['score']['total']:.1f}/100 (alert threshold 60): points for move, volume, liquidity, filings, "
        "price position and data coverage. Not a probability.",
        f"Repeat: {repeat_line(i)}",
        "",
        "⚠️ Research to date: this alert policy's paper results were NEGATIVE after costs (replay −0.61%, forward "
        "−0.46%). Unverified: cause of the move, news, live price.",
        f"Policy {i['policy_version']} · universe DTU_V3_TOP600 · ref {i['ref']}",
    ]
    return "\n".join(lines)


def audit(i: dict) -> str:
    tm, d = i["timing_utc"], i["delays_s"]
    tr = (tm.get("trace") or [{}])[0]
    return (f"AUDIT (post-send, not part of the message): Telegram API ack {et(tm['api_acknowledged_sent_at'], True)} ET "
            f"(trace response {et(tr['response_utc'], True) + ' ET' if tr.get('response_utc') else 'n/a'}, "
            f"retries {tr.get('network_retries', 'n/a')}); queued→ack {d['queued_to_ack']} s; "
            f"data→ack {d['data_to_ack']} s ({d['data_to_ack'] / 60:.1f} min)")


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    items = d["items"]
    ack_min = [i["delays_s"]["data_to_ack"] / 60 for i in items]
    q = [i["delays_s"]["queued_to_ack"] for i in items]
    out = [f"<!-- generated by render_proposed.py from sample cutoff {d['cutoff_utc']} -->",
           f"Data age at Telegram acknowledgement across the sample: min {min(ack_min):.1f}, median "
           f"{statistics.median(ack_min):.1f}, max {max(ack_min):.1f} min; queue→ack wait: median "
           f"{statistics.median(q):.1f} s, max {max(q):.1f} s ({sum(x > 60 for x in q)} of {len(q)} waited > 60 s).", ""]
    for sym in EXAMPLES:
        i = next(x for x in items if x["symbol"] == sym)
        out += [f"### {sym}", "", "| Existing (as delivered) | Proposed (local render) |", "|---|---|",
                "| <pre>" + i["rendered_message"].replace("\n", "<br>").replace("|", "\\|") + "</pre> | <pre>"
                + render(i).replace("\n", "<br>").replace("|", "\\|") + "</pre> |", "", audit(i), ""]
    print("\n".join(out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
