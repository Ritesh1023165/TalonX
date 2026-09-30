"""Phase B2 -- split / reverse-split / spin-off METADATA for the universes used by raw-sourced research datasets.
Alpaca /v1/corporate-actions (free), queried by PROCESS date (its filter) and selected locally by EX-date (the
Task75 A1 fix). Every query range is guard-checked; the two reserved Task75 windows are cut OUT of the ranges and never
queried. For those windows only the public facts already recorded in Task75A are cited (not queried).
No prices are read. Output: results/raw_adjustment_audit/split_events.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.raw_adjustment_audit.holdout_guard import HoldoutGuard  # noqa: E402

URL = "https://data.alpaca.markets/v1/corporate-actions"
TYPES = "forward_split,reverse_split,spin_off,stock_merger,unit_split,stock_dividend"
UNIVERSE_35 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX", "ADBE", "ADI", "AMAT",
               "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON", "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ",
               "MU", "NFLX", "PANW", "PEP", "QCOM", "REGN", "SBUX", "TXN", "VRTX"]
EXTRA = ["SPY", "BABA", "SHOP", "SPCX"]
SEGMENTS = [("2019-01-01", "2024-05-31"), ("2024-09-03", "2024-10-20"), ("2024-12-21", "2026-09-30")]
RESERVED_PUBLIC_FACTS = [
    {"symbol": "NVDA", "action_type": "forward_splits", "ex_or_effective_date": "~2024-06-10", "split_ratio": "10:1",
     "source": "Task75A corporate_action_policy.json (public knowledge; reserved window NOT queried)"},
    {"symbol": "AVGO", "action_type": "forward_splits", "ex_or_effective_date": "~2024-07-15", "split_ratio": "10:1",
     "source": "Task75A corporate_action_policy.json (public knowledge; reserved window NOT queried)"}]


def headers() -> dict:
    env = {}
    for line in Path("C:/workspace/TalonX/.env").read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return {"APCA-API-KEY-ID": os.environ.get("APCA_API_KEY_ID") or env["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": os.environ.get("APCA_API_SECRET_KEY") or env["APCA_API_SECRET_KEY"]}


def main() -> dict:
    g = HoldoutGuard.load(ROOT / "results" / "raw_adjustment_audit" / "guard_state_not_used.json")
    assert g.state == "PREFLIGHT" and g.validation_locked() and g.replication_locked()
    h = headers()
    events, seen = [], set()
    for s, e in SEGMENTS:
        g.check_range(s, e, layer="DOWNLOAD")
        token = None
        while True:
            p = {"symbols": ",".join(UNIVERSE_35 + EXTRA), "start": s, "end": e, "types": TYPES, "limit": 1000}
            if token:
                p["page_token"] = token
            time.sleep(2.0)                                          # <= 30 req/min
            with urllib.request.urlopen(urllib.request.Request(URL + "?" + urllib.parse.urlencode(p), headers=h),
                                        timeout=60) as r:
                j = json.loads(r.read())
            for typ, rows in (j.get("corporate_actions") or {}).items():
                for x in rows:
                    ex = x.get("ex_date") or x.get("effective_date") or x.get("process_date")
                    sym = x.get("symbol") or x.get("source_symbol") or x.get("target_symbol") or x.get("acquiree_symbol")
                    if not ex or not (s <= ex <= e):
                        continue                                     # local ex-date selection inside the segment
                    k = (sym, typ, ex)
                    if k in seen:
                        continue
                    seen.add(k)
                    events.append({"symbol": sym, "action_type": typ, "ex_or_effective_date": ex,
                                   "split_ratio": (f"{x.get('new_rate')}:{x.get('old_rate')}" if "split" in typ else None),
                                   "source": "Alpaca /v1/corporate-actions (process-date query, ex-date selection)"})
            token = j.get("next_page_token")
            if not token:
                break
    events.sort(key=lambda e: (e["ex_or_effective_date"], e["symbol"] or ""))
    res = {"segments_queried": SEGMENTS, "reserved_windows_not_queried": ["2024-06-01..2024-09-02", "2024-10-21..2024-12-20"],
           "events": events, "reserved_window_public_facts": RESERVED_PUBLIC_FACTS,
           "count": len(events)}
    out = ROOT / "results" / "raw_adjustment_audit" / "split_events.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    for e in r["events"]:
        print(e["ex_or_effective_date"], e["symbol"], e["action_type"], e["split_ratio"])
    print("count", r["count"])
