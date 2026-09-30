"""TASK75_DATASET_ALL_V1 downloader -- DEVELOPMENT windows ONLY (declaration 697f377). Alpaca SIP 1Min adjustment=all,
35 frozen symbols + SPY with IDENTICAL parameters. Holdout guard at the DOWNLOAD layer for every request range.
Bounded rate (<= 40 req/min), resumable per (slice, symbol) file, conservative retries; never synthesises a bar.
Writes data/historical_1m/task75b_all_v1/<slice>/<SYM>.csv (the archive format: timestamp,symbol,open,high,low,close,
volume) and results/task75b_preflight/dataset_manifest_all_v1.json (per-file sha256, per-slice aggregate hash, coverage).
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75b_preflight.ca_audit import _headers  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402
from research.task75b_preflight.survival import aggregate_hash, file_sha256  # noqa: E402

DECL = json.loads((ROOT / "results" / "task75b_preflight" / "dataset_basis_declaration.json").read_text())
BASIS = DECL["dataset_basis"]
OUT = ROOT / "data" / "historical_1m" / "task75b_all_v1"
MAN = ROOT / "results" / "task75b_preflight" / "dataset_manifest_all_v1.json"
ET = ZoneInfo("America/New_York")
MIN_INTERVAL_S = 1.5                                       # <= 40 requests / minute


def bounds(start: str, end: str) -> tuple[str, str]:
    s = datetime.fromisoformat(start).replace(tzinfo=ET).astimezone(timezone.utc)
    e = datetime.fromisoformat(end).replace(hour=23, minute=59, second=59, tzinfo=ET).astimezone(timezone.utc)
    return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")


_last = [0.0]


def call(url: str, params: dict, headers: dict, tries: int = 6) -> dict:
    for a in range(tries):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < tries - 1:
                time.sleep(min(60, 5 * 2 ** a))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if a < tries - 1:
                time.sleep(min(60, 5 * 2 ** a))
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_symbol(sym: str, start: str, end: str, headers: dict) -> tuple[list[dict], int]:
    url = f"https://data.alpaca.markets/v2/stocks/{sym}/bars"
    qs, qe = bounds(start, end)
    rows, bad, token = [], 0, None
    while True:
        p = {"timeframe": BASIS["timeframe"], "start": qs, "end": qe, "limit": 10000, "feed": BASIS["feed"],
             "adjustment": BASIS["adjustment"]}
        if token:
            p["page_token"] = token
        j = call(url, p, headers)
        for b in j.get("bars") or []:
            if not all(k in b and b[k] is not None for k in ("t", "o", "h", "l", "c", "v")):
                bad += 1
                continue
            rows.append(b)
        token = j.get("next_page_token")
        if not token:
            return rows, bad


def main() -> dict:
    assert (BASIS["provider"], BASIS["feed"], BASIS["timeframe"], BASIS["adjustment"]) == ("alpaca", "sip", "1Min", "all")
    guard = HoldoutGuard.load()
    h = _headers()
    man = json.loads(MAN.read_text()) if MAN.exists() else {"id": BASIS["id"], "declaration_sha": "697f377",
                                                             "basis": {k: BASIS[k] for k in ("provider", "feed",
                                                                                             "timeframe", "adjustment")},
                                                             "slices": {}}
    for label, (start, end) in BASIS["windows"].items():
        guard.check_range(start, end, layer="DOWNLOAD")
        d = OUT / label
        assert_research_path(d)
        d.mkdir(parents=True, exist_ok=True)
        sl = man["slices"].setdefault(label, {"window": [start, end], "query": dict(zip(("start", "end"), bounds(start, end))),
                                              "files": {}})
        for sym in C.UNIVERSE + [C.MARKET_SYMBOL]:
            f = d / f"{sym}.csv"
            if sym in sl["files"] and f.exists():
                continue
            rows, bad = fetch_symbol(sym, start, end, h)
            ts = [b["t"] for b in rows]
            dup = len(ts) - len(set(ts))
            with open(f, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
                for b in sorted(rows, key=lambda b: b["t"]):
                    w.writerow([datetime.fromisoformat(b["t"].replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S+00:00"),
                                sym, b["o"], b["h"], b["l"], b["c"], b["v"]])
            sl["files"][sym] = {"sha256": file_sha256(f), "rows": len(rows), "duplicate_timestamps": dup,
                                "rejected_malformed": bad, "downloaded_utc": datetime.now(timezone.utc).isoformat()}
            MAN.write_text(json.dumps(man, indent=1))
            print(json.dumps({"slice": label, "symbol": sym, "rows": len(rows)}), flush=True)
        sl["aggregate_sha256"] = aggregate_hash({s: v["sha256"] for s, v in sl["files"].items()})
        MAN.write_text(json.dumps(man, indent=1))
    man["dataset_aggregate_sha256"] = aggregate_hash({f"{k}/{s}": v["sha256"] for k, sl in man["slices"].items()
                                                      for s, v in sl["files"].items()})
    MAN.write_text(json.dumps(man, indent=1))
    return man


if __name__ == "__main__":
    m = main()
    print(json.dumps({"dataset_aggregate_sha256": m["dataset_aggregate_sha256"],
                      "slices": {k: v["aggregate_sha256"] for k, v in m["slices"].items()}}, indent=1))
