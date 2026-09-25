"""Skipped discovery slot impact (READ-ONLY on TalonX stores; read-only Alpaca SIP historical bars for the few
affected symbols). usage: python skip_impact.py <skipped_slot_iso> <next_scan_iso>

For every candidate first seen -- and every setup first surfaced -- on the scan after the skipped slot, rebuild the
symbol's window-to-date aggregate from SIP 1-min bars up to the data horizon the skipped slot WOULD have used (the
freshest ingestion as_of at that slot), then re-run the frozen features -> hard gate -> score -> classify.
Catalyst strength is taken from the actual event's catalyst label (the SEC set can only grow in 5 min; noted).

A NOT_OBSERVABLE_YET (no data-ready features) | B OBSERVABLE_BUT_BELOW_THRESHOLD | C OBSERVABLE_AND_WOULD_HAVE_QUALIFIED
| D UNKNOWN
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity.aggregates import SymbolAggregate, features_from_aggregate  # noqa: E402
from talonx_opportunity.config import CONTINUOUS_RESEARCH_V1 as CFG  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402
from talonx_premarket import __main__ as M  # noqa: E402
from talonx_premarket import scoring as S  # noqa: E402

R = REPO / "results" / "opportunity"
SETUP_EV = ("BULLISH", "BEARISH")


def ro(n):
    c = sqlite3.connect(f"file:{R / n}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def strength(label: str | None) -> str:
    t = (label or "").lower()
    if not t or "none found" in t:
        return "NONE"
    if "incomplete" in t:
        return "UNKNOWN"
    if any(k in t for k in ("8-k", "6-k", "424b", "s-1", "s-3", "f-1", "f-3", "offering", "distinct insiders")):
        return "STRONG"
    return "OTHER"


slot, nxt = datetime.fromisoformat(sys.argv[1]), datetime.fromisoformat(sys.argv[2])
o, mk, n, oc = ro("opportunity.db"), ro("market.db"), ro("notification.db"), ro("outcomes.db")
wid = slot.date().isoformat()
w = trading_window(slot.date())
cyc = mk.execute("select at_utc, as_of_utc from cycles where window_id=? and at_utc<=? and as_of_utc is not null "
                 "order by id desc limit 1", (wid, slot.isoformat())).fetchone()
skip_asof = datetime.fromisoformat(cyc["as_of_utc"])
nscan = o.execute("select decision_utc, data_as_of_utc, duration_s from scans where window_id=? and decision_utc>=? "
                  "order by decision_utc limit 1", (wid, nxt.isoformat())).fetchone()
prev = o.execute("select decision_utc, duration_s from scans where window_id=? and decision_utc<? order by decision_utc desc "
                 "limit 1", (wid, slot.isoformat())).fetchone()
evs = [dict(r) for r in o.execute("select * from candidate_events where window_id=? and at_utc=? and "
                                  "(event_type='NEW' or (event_type='UPGRADE' and classification in ('BULLISH','BEARISH')))",
                                  (wid, nscan["decision_utc"]))]
daily = {r["symbol"]: json.loads(r["bars_json"]) for r in mk.execute("select symbol, bars_json from daily where window_id=?", (wid,))}
M._env()
data = M._data()
syms = sorted({e["symbol"] for e in evs})
bars = {}
for i in range(0, len(syms), 100):
    res = data.bars_ex(syms[i:i + 100], timeframe="1Min", start=w.premarket_start_utc, end=skip_asof - timedelta(seconds=1))
    bars.update(res.bars)
rows, klass = [], {"A": 0, "B": 0, "C": 0, "D": 0}
for e in evs:
    sym = e["symbol"]
    try:
        agg = SymbolAggregate(sym, wid)
        agg.add(sorted(bars.get(sym, []), key=lambda b: b["t"]))
        feats, why = features_from_aggregate(sym, daily.get(sym, []), agg if agg.bars else None,
                                             prev_session=w.reference_session, data_as_of=skip_asof, cfg=CFG.base)
        if feats is None:
            k, est = "A", f"NOT_DATA_READY:{why}"
        elif S.hard_gate(feats, CFG.base):
            k, est = "B", f"REJECTED:{S.hard_gate(feats, CFG.base)}"
        else:
            sc = S.score(feats, strength(e["catalyst"]), CFG.base)
            cls = S.classify(feats, sc, CFG.base)
            est = f"{cls}@{round(sc.total, 1)} gap {round(feats.gap_pct, 2)}"
            k = "C" if cls in ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP") else "B"
    except Exception as exc:  # noqa: BLE001
        k, est = "D", f"{type(exc).__name__}: {exc}"[:80]
    klass[k] += 1
    d = n.execute("select decision, outbox_event_id from decisions where event_id=?", (e["event_id"],)).fetchone()
    r = oc.execute("select status, ret_30m_pct, ret_1h_pct, mfe_pct from outcomes where candidate_id=?", (e["candidate_id"],)).fetchone()
    rows.append({"symbol": sym, "type": e["event_type"], "actual": f"{e['classification']}@{round(e['score'] or 0, 1)}",
                 "move_now": round(e["gap_pct"] or 0, 2), "class": k, "estimated_at_skipped_slot": est,
                 "delay_s": round((datetime.fromisoformat(nscan["decision_utc"]) - slot).total_seconds()),
                 "lab": d["decision"] if d else None, "outcome": dict(r) if r else None})
out = {"SKIPPED_SLOT_TIME": slot.isoformat()[11:19], "PREVIOUS_SCAN_START": prev["decision_utc"][11:19],
       "PREVIOUS_SCAN_END": (datetime.fromisoformat(prev["decision_utc"]) + timedelta(seconds=prev["duration_s"])).isoformat()[11:19],
       "NEXT_ACTUAL_SCAN_START": nscan["decision_utc"][11:19], "NEXT_SCAN_DATA_AS_OF": nscan["data_as_of_utc"][11:16],
       "SKIPPED_SLOT_WOULD_HAVE_USED_AS_OF": skip_asof.isoformat()[11:16],
       "EXTRA_DISCOVERY_LATENCY_S": round((datetime.fromisoformat(nscan["decision_utc"]) - slot).total_seconds()),
       "CANDIDATES_FIRST_SEEN_ON_NEXT_SCAN": sum(1 for e in evs if e["event_type"] == "NEW"),
       "SETUPS_FIRST_SEEN_ON_NEXT_SCAN": sum(1 for e in evs if e["classification"] in SETUP_EV),
       "classes": klass, "MATERIALLY_DELAYED(C setups)": [r for r in rows if r["class"] == "C" and r["actual"].split("@")[0] in SETUP_EV],
       "detail": rows}
print(json.dumps(out, indent=1, default=str))
