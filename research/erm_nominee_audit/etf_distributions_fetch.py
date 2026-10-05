"""Targeted provider METADATA (V2 descriptive sensitivity only): cash-dividend corporate actions 2019-2023 for the 7
benchmark ETFs (SPY, XLE, XBI, XLV, XLK, XLI, XLF). The archive has no raw ETF bars (frozen: benchmarks never raw), so
these records are the only evidence for ETF-leg adjustments. Frozen universe_source.get (<= 30 req/min), ERM guard range
check (development years only), R5 off-hours refusal. Bytes archived with sha256 in results/erm_nominee_audit/_alpaca_v2/."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D  # noqa: E402
from research.event_response_map_v1.universe_source import YEARS, get, headers  # noqa: E402

OUT = HERE / "results" / "erm_nominee_audit" / "_alpaca_v2"
OUT.mkdir(parents=True, exist_ok=True)
if D.market_hours_blocked(datetime.now(timezone.utc)):
    raise SystemExit("R5: off-hours only")
guard, h, rows, man = LockedRangeGuard(EVENT_RESPONSE_MAP_V1), headers(), [], []
for y in YEARS:
    s, e = f"{y}-01-01", f"{y}-12-31"
    guard.check_range(s, e, layer="DOWNLOAD")
    token = None
    while True:
        p = {"symbols": ",".join(D.BENCHMARKS), "start": s, "end": e, "types": "cash_dividend", "limit": 1000}
        if token:
            p["page_token"] = token
        j = get("https://data.alpaca.markets/v1/corporate-actions", p, h)
        body = json.dumps(j, sort_keys=True).encode()
        name = f"etf_cash_dividends_{y}_{len(man)}.json"
        (OUT / name).write_bytes(body)
        man.append({"file": name, "params": {k: v for k, v in p.items() if k != "page_token"},
                    "sha256": hashlib.sha256(body).hexdigest(), "utc": datetime.now(timezone.utc).isoformat()})
        for typ, rs in (j.get("corporate_actions") or {}).items():
            rows += [{**r, "_type": typ} for r in rs]
        token = j.get("next_page_token")
        if not token:
            break
(OUT / "manifest.json").write_text(json.dumps(man, indent=1))
(OUT / "etf_cash_dividends.json").write_text(json.dumps(rows, indent=1))
print({"records": len(rows), "by_symbol": {s: sum(1 for r in rows if r.get("symbol") == s) for s in D.BENCHMARKS},
       "fields": sorted(rows[0]) if rows else []})
