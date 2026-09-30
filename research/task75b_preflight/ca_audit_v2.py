"""Task75 closure A1 -- corporate-action audit V2 (DATA FIX; survival gates untouched).

Empirical finding (2026-09-30, GOOGL ex 2025-03-10 / payable 2025-03-17): Alpaca /v1/corporate-actions filters its
start/end on PROCESS_DATE (= payable date for cash dividends), not on the ex-date. V1 therefore missed dividends whose
ex-date fell inside a development window but whose payable date fell after it.

V2: query each window by process date over [start - 10 d, end + 120 d] (payable dates trail ex-dates by weeks), then
select LOCALLY by ex-date in [start - 10 d, end] (the 10 d covers the 3-session feature lookback before the first
decision day). Every query range passes the Task75B holdout guard at the DOWNLOAD layer and none touches 2024.
Metadata only; no prices. Output: results/task75b_preflight/corporate_action_audit_v2.json (V1 file left unchanged).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75b_preflight.ca_audit import _headers, fetch_actions  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402

LOOKBACK_PAD_DAYS = 10
PROCESS_TRAIL_DAYS = 120


def ex_date_of(row: dict) -> str | None:
    return row.get("ex_date") or row.get("effective_date") or row.get("process_date")


def select_by_ex_date(rows_by_type: dict, lo: str, hi: str) -> list[dict]:
    """Local ex-date selection (the fix): keep rows whose ex/effective date is inside [lo, hi]."""
    out = []
    for typ, rows in rows_by_type.items():
        for r in rows:
            ex = ex_date_of(r)
            if ex and lo <= ex <= hi:
                out.append({"symbol": r.get("symbol") or r.get("target_symbol") or r.get("acquiree_symbol")
                            or r.get("source_symbol"), "action_type": typ, "ex_or_effective_date": ex,
                            "split_ratio": (f"{r.get('new_rate')}:{r.get('old_rate')}" if "split" in typ else None),
                            "dividend": r.get("rate") if "dividend" in typ else None,
                            "record_date": r.get("record_date"), "payable_date": r.get("payable_date"),
                            "process_date": r.get("process_date"), "id": r.get("id")})
    return out


def main() -> dict:
    guard = HoldoutGuard.load()
    man = json.loads((ROOT / "results" / "task74_alpha_discovery_v2" / "development_data_manifest.json").read_text())
    h = _headers()
    syms = C.UNIVERSE + [C.MARKET_SYMBOL]
    events, seen = [], set()
    for label, s in man["slices"].items():
        lo = (date.fromisoformat(s["start"]) - timedelta(days=LOOKBACK_PAD_DAYS)).isoformat()
        q_hi = (date.fromisoformat(s["end"]) + timedelta(days=PROCESS_TRAIL_DAYS)).isoformat()
        acts = fetch_actions(syms, lo, q_hi, h, guard)          # guard.check_range(lo, q_hi, DOWNLOAD) inside
        for e in select_by_ex_date(acts, lo, s["end"]):
            k = (e["symbol"], e["action_type"], e["ex_or_effective_date"], e.get("id"))
            if k in seen:
                continue
            seen.add(k)
            events.append({**e, "development_window": label, "window": [s["start"], s["end"]],
                           "query_process_date_range": [lo, q_hi], "selected_ex_date_range": [lo, s["end"]],
                           "source": "Alpaca /v1/corporate-actions (process-date query, local ex-date selection)"})
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["action_type"]] = by_type.get(e["action_type"], 0) + 1
    v1 = json.loads((ROOT / "results" / "task75b_preflight" / "corporate_action_audit.json").read_text())["events"]
    k1 = {(e["symbol"], e["action_type"], e["ex_or_effective_date"]) for e in v1}
    k2 = {(e["symbol"], e["action_type"], e["ex_or_effective_date"]) for e in events}
    res = {"version": "CA_AUDIT_V2_EX_DATE", "queried_utc": datetime.now(timezone.utc).isoformat(),
           "finding": "Alpaca filters start/end on process_date (payable date for dividends); V2 selects by ex-date locally",
           "events": sorted(events, key=lambda e: (e["development_window"], e["symbol"] or "", e["ex_or_effective_date"])),
           "count": len(events), "by_type": by_type, "new_vs_v1": sorted(map(list, k2 - k1), key=str),
           "in_v1_not_v2": sorted(map(list, k1 - k2), key=str)}
    out = ROOT / "results" / "task75b_preflight" / "corporate_action_audit_v2.json"
    assert_research_path(out)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({"count": r["count"], "by_type": r["by_type"], "new_vs_v1_n": len(r["new_vs_v1"]),
                      "in_v1_not_v2": r["in_v1_not_v2"]}, indent=1))
    print("non-dividend:", [(e["symbol"], e["action_type"], e["ex_or_effective_date"], e["split_ratio"])
                            for e in r["events"] if e["action_type"] != "cash_dividends"])
