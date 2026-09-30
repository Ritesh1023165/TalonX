"""Task75B PREFLIGHT -- corporate-action audit of the DEVELOPMENT windows only (35 frozen symbols + SPY), from Alpaca's
free corporate-actions API (metadata, no prices). Every queried range passes the holdout guard at the DOWNLOAD layer.
Bounded request rate; results/task75b_preflight/corporate_action_audit.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402

URL = "https://data.alpaca.markets/v1/corporate-actions"
MIN_INTERVAL_S = 2.0                                     # <= 30 requests/min: never competes with a live session


def _headers() -> dict:
    """Read-only use of the existing Alpaca research key from the live repo's .env (never modified, never printed)."""
    env = {}
    for line in Path("C:/workspace/TalonX/.env").read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    kid = os.environ.get("APCA_API_KEY_ID") or env.get("APCA_API_KEY_ID", "")
    sec = os.environ.get("APCA_API_SECRET_KEY") or env.get("APCA_API_SECRET_KEY", "")
    if not (kid and sec):
        raise SystemExit("Alpaca research key not available")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec}


_last = [0.0]


def get(params: dict, headers: dict) -> dict:
    wait = MIN_INTERVAL_S - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_actions(symbols: list[str], start: str, end: str, headers: dict, guard: HoldoutGuard) -> dict:
    guard.check_range(start, end, layer="DOWNLOAD")
    out, token = {}, None
    while True:
        p = {"symbols": ",".join(symbols), "start": start, "end": end, "limit": 1000}
        if token:
            p["page_token"] = token
        j = get(p, headers)
        for typ, rows in (j.get("corporate_actions") or {}).items():
            out.setdefault(typ, []).extend(rows)
        token = j.get("next_page_token")
        if not token:
            return out


def main() -> dict:
    guard = HoldoutGuard.load()
    man = json.loads((ROOT / "results" / "task74_alpha_discovery_v2" / "development_data_manifest.json").read_text())
    h = _headers()
    syms = C.UNIVERSE + [C.MARKET_SYMBOL]
    events = []
    for label, s in man["slices"].items():
        acts = fetch_actions(syms, s["start"], s["end"], h, guard)
        for typ, rows in acts.items():
            for r in rows:
                ex = r.get("ex_date") or r.get("process_date") or r.get("effective_date")
                events.append({"symbol": r.get("symbol") or r.get("target_symbol") or r.get("acquiree_symbol"),
                               "action_type": typ, "ex_or_effective_date": ex,
                               "split_ratio": (f"{r.get('new_rate')}:{r.get('old_rate')}" if "split" in typ else None),
                               "dividend": r.get("rate") if "dividend" in typ else None,
                               "record_date": r.get("record_date"), "payable_date": r.get("payable_date"),
                               "development_window": label, "window": [s["start"], s["end"]],
                               "source": "Alpaca /v1/corporate-actions (free metadata; no prices)"})
    events.sort(key=lambda e: (e["development_window"], e["symbol"] or "", e["ex_or_effective_date"] or ""))
    by_type = {}
    for e in events:
        by_type[e["action_type"]] = by_type.get(e["action_type"], 0) + 1
    res = {"queried_utc": datetime.now(timezone.utc).isoformat(), "symbols": syms, "windows": man["slices"],
           "events": events, "count": len(events), "by_type": by_type,
           "symbols_with_events": sorted({e["symbol"] for e in events if e["symbol"]}),
           "spy_events": [e for e in events if e["symbol"] == "SPY"],
           "splits": [e for e in events if "split" in e["action_type"]],
           "note": "DEVELOPMENT windows only; reserved 2024 windows never queried (guard at DOWNLOAD layer)."}
    out = ROOT / "results" / "task75b_preflight" / "corporate_action_audit.json"
    assert_research_path(out)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("count", "by_type", "symbols_with_events", "splits")}, indent=1))
    print("SPY events:", [(e["action_type"], e["ex_or_effective_date"], e["dividend"]) for e in r["spy_events"]])
