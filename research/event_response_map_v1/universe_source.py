"""EVENT_RESPONSE_MAP_V1 C1 -- point-in-time universe SOURCE audit (METADATA ONLY, no prices).

Candidate-symbol source (best free, NOT fully survivorship-free):
  A. Alpaca /v2/assets us_equity, status active AND inactive, listed exchanges only (NYSE/NASDAQ/AMEX/ARCA/BATS),
     instrument-type name rules + symbol regex reused from talonx_premarket/universe.py (status/tradable/CIK NOT required)
  B. Alpaca /v1/corporate-actions name_change (old_symbol -> new_symbol, process date) 2019-01-01..2023-12-31
  C. Alpaca /v1/corporate-actions cash / stock / stock-and-cash mergers (acquiree symbols) 2019..2023
Coverage reference: Task95F point-in-time S&P 500 membership (fja05680, Wikipedia; read-only from the live worktree's
untracked results) -- every name that was a member on ANY day of year Y, checked against A|B|C.
All query ranges are guard-checked (no 2024, no 2025+). Output: results/event_response_map_v1/universe_source_audit.json
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402

LISTED = ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
PIT = Path("C:/workspace/TalonX/results/task95g_broad_cross_sectional/_fja05680_pit.csv")
YEARS = (2019, 2020, 2021, 2022, 2023)


def name_excluded(name: str) -> str | None:
    from talonx_premarket.universe import _NAME_RULES
    for code, rx in _NAME_RULES:
        if rx.search(name or ""):
            return code
    return None


def headers() -> dict:
    env = {}
    for line in Path("C:/workspace/TalonX/.env").read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}


def get(url, params, h):
    time.sleep(2.0)                                       # <= 30 req/min
    with urllib.request.urlopen(urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=h),
                                timeout=120) as r:
        return json.loads(r.read())


def corporate_actions(types: str, h, guard) -> list[dict]:
    out = []
    for y in YEARS:
        s, e = f"{y}-01-01", f"{y}-12-31"
        guard.check_range(s, e, layer="DOWNLOAD")
        token = None
        while True:
            p = {"start": s, "end": e, "types": types, "limit": 1000}
            if token:
                p["page_token"] = token
            j = get("https://data.alpaca.markets/v1/corporate-actions", p, h)
            for typ, rows in (j.get("corporate_actions") or {}).items():
                out += [{**r, "_type": typ} for r in rows]
            token = j.get("next_page_token")
            if not token:
                break
    return out


def main() -> dict:
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    h = headers()
    assets = []
    for st in ("active", "inactive"):
        assets += get("https://paper-api.alpaca.markets/v2/assets", {"status": st, "asset_class": "us_equity"}, h)
    a_common = {}
    excl = {}
    for a in assets:
        sym, ex = str(a.get("symbol", "")).upper(), a.get("exchange")
        if ex not in LISTED or not SYMBOL_RE.match(sym):
            continue
        why = name_excluded(a.get("name", ""))
        if why:
            excl[why] = excl.get(why, 0) + 1
            continue
        a_common[sym] = {"status": a.get("status"), "exchange": ex, "name": a.get("name")}
    renames = corporate_actions("name_change", h, guard)
    mergers = corporate_actions("cash_merger,stock_merger,stock_and_cash_merger", h, guard)
    old_syms = {str(r.get("old_symbol", "")).upper() for r in renames if r.get("old_symbol")}
    acq_syms = {str(r.get("acquiree_symbol", "")).upper() for r in mergers if r.get("acquiree_symbol")}
    cand = set(a_common) | old_syms | acq_syms
    # coverage vs PIT S&P 500 (any-day membership per year)
    members = {y: set() for y in YEARS}
    with open(PIT, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            y = int(row["date"][:4])
            if y in members:
                members[y] |= {t.strip().upper() for t in row["tickers"].split(",") if t.strip()}
    cov = {}
    for y in YEARS:
        m = members[y]
        direct = {t for t in m if t in a_common}
        via = {t for t in m if t not in a_common and t in (old_syms | acq_syms)}
        miss = sorted(m - direct - via)
        cov[str(y)] = {"sp500_members_any_day": len(m), "covered_direct_asset": len(direct),
                       "covered_via_rename_or_merger": len(via), "missing": len(miss),
                       "coverage_pct": round(100 * (len(direct) + len(via)) / len(m), 2), "missing_examples": miss[:25]}
    res = {"assets_total": len(assets),
           "assets_listed_common": len(a_common),
           "assets_listed_common_active": sum(1 for v in a_common.values() if v["status"] == "active"),
           "assets_listed_common_inactive": sum(1 for v in a_common.values() if v["status"] == "inactive"),
           "name_rule_exclusions": excl,
           "name_changes_2019_2023": len(renames), "mergers_2019_2023": len(mergers),
           "candidate_symbols_total": len(cand),
           "coverage_vs_pit_sp500": cov,
           "renames_sample": [(r.get("old_symbol"), r.get("new_symbol"), r.get("process_date")) for r in renames[:10]]}
    out = ROOT / "results" / "event_response_map_v1" / "universe_source_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    (out.parent / "_renames_2019_2023.json").write_text(json.dumps(renames))
    (out.parent / "_mergers_2019_2023.json").write_text(json.dumps(mergers))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: v for k, v in r.items() if k != "renames_sample"}, indent=1)[:4000])


def build_candidates() -> dict:
    """Freeze the Phase D candidate list (METADATA ONLY): A (assets active+inactive, listed common) | B (pre-rename
    tickers) | C (merger acquirees) | D (any-day PIT S&P 500 members 2019-2023). Writes candidates.json."""
    h = headers()
    assets = []
    for st in ("active", "inactive"):
        assets += get("https://paper-api.alpaca.markets/v2/assets", {"status": st, "asset_class": "us_equity"}, h)
    a_common, names = set(), {}
    for a in assets:
        sym, ex = str(a.get("symbol", "")).upper(), a.get("exchange")
        if ex in LISTED and SYMBOL_RE.match(sym) and not name_excluded(a.get("name", "")):
            a_common.add(sym)
            names[sym] = a.get("name")
    out_dir = ROOT / "results" / "event_response_map_v1"
    renames = json.loads((out_dir / "_renames_2019_2023.json").read_text())
    mergers = json.loads((out_dir / "_mergers_2019_2023.json").read_text())
    b = {str(r["old_symbol"]).upper() for r in renames if r.get("old_symbol")}
    c = {str(r["acquiree_symbol"]).upper() for r in mergers if r.get("acquiree_symbol")}
    d = set()
    with open(PIT, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if 2019 <= int(row["date"][:4]) <= 2023:
                d |= {t.strip().upper() for t in row["tickers"].split(",") if t.strip()}
    from research.event_response_map_v1.universe import candidates
    cand = candidates(a_common, b, c, d)
    for r in renames:                                       # pre-rename tickers inherit the company name
        o, n = str(r.get("old_symbol", "")).upper(), str(r.get("new_symbol", "")).upper()
        if o and o not in names and n in names:
            names[o] = names[n]
    doc = {"symbols": cand, "names": {s: names[s] for s in cand if s in names},
           "source_counts": {k: sum(1 for v in cand.values() if k in v) for k in "ABCD"},
           "only_from": {k: sum(1 for v in cand.values() if v == [k]) for k in "ABCD"}}
    (out_dir / "candidates.json").write_text(json.dumps(doc, sort_keys=True, indent=0))
    return doc
