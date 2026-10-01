"""EVENT_RESPONSE_MAP_V1 -- the ONE daily-bar downloader + loader (equities, SPY and sector ETFs share this path).

DOWNLOAD layer: every request range is checked by the program's LockedRangeGuard BEFORE the request is built.
LOAD layer:     every loaded frame is checked (range + interior rows) BEFORE it is used.
Adjustment:     'all' for returns/benchmarks. 'raw' only with purpose=ELIGIBILITY_ONLY and never for a benchmark.
Rate:           <= 37.5 requests/min (1.6 s spacing) and OFF-HOURS ONLY: refuses to start or continue on a weekday
                between 13:00 and 20:30 UTC (the live engine shares the IP during 13:30-20:00Z).
Archive:        each response body is written verbatim (gzip) and listed in manifest.json with sha256; the archive,
                not a re-download, is authoritative.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, HoldoutViolation, LockedRangeGuard, assert_research_path

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
BENCHMARKS = ("SPY", "XLE", "XBI", "XLV", "XLK", "XLI", "XLF")
DATA_START, DATA_END = "2018-11-01", "2023-12-29"
BATCH = 100                     # symbols per request
PAGE_LIMIT = 10_000             # bars per page
MIN_SPACING_S = 1.6             # 37.5 req/min
PURPOSES = {"RETURNS": "all", "ELIGIBILITY_ONLY": "raw"}


class MarketHoursRefusal(RuntimeError):
    pass


def market_hours_blocked(now: datetime) -> bool:
    """Weekday 13:00-20:30 UTC is blocked (covers 13:30-20:00Z with a 30-min buffer, either DST regime)."""
    m = now.hour * 60 + now.minute
    return now.weekday() < 5 and 13 * 60 <= m < 20 * 60 + 30


def request_params(symbols: list[str], start: str, end: str, *, purpose: str, page_token: str | None = None) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    adj = PURPOSES[purpose]
    if adj == "raw" and set(symbols) & set(BENCHMARKS):
        raise ValueError("benchmarks are never downloaded raw")
    p = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start, "end": end, "adjustment": adj,
         "feed": "sip", "limit": PAGE_LIMIT, "sort": "asc"}
    if page_token:
        p["page_token"] = page_token
    return p


def estimate_requests(n_symbols: int, sessions: int = 1295, coverage: float = 0.6) -> int:
    """Pages needed for one pass: per batch ceil(BATCH * sessions * coverage / PAGE_LIMIT)."""
    import math
    batches = math.ceil(n_symbols / BATCH)
    return batches * max(1, math.ceil(BATCH * sessions * coverage / PAGE_LIMIT))


class Downloader:
    def __init__(self, archive_dir: Path, headers: dict, *, guard: LockedRangeGuard | None = None, clock=None,
                 opener=None, sleep=time.sleep):
        self.dir = Path(archive_dir)
        assert_research_path(self.dir)
        self.guard = guard or LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
        self.h, self.clock = headers, clock or (lambda: datetime.now(timezone.utc))
        self.opener = opener or (lambda req: urllib.request.urlopen(req, timeout=120).read())
        self.sleep, self.last = sleep, 0.0
        self.manifest = {"program": "EVENT_RESPONSE_MAP_V1", "files": []}

    def _get(self, params: dict) -> bytes:
        if market_hours_blocked(self.clock()):
            raise MarketHoursRefusal("off-hours only: weekday 13:00-20:30Z is blocked")
        wait = MIN_SPACING_S - (time.monotonic() - self.last)
        if wait > 0:
            self.sleep(wait)
        self.last = time.monotonic()
        req = urllib.request.Request(BARS_URL + "?" + urllib.parse.urlencode(params), headers=self.h)
        return self.opener(req)

    def pass_(self, symbols: list[str], *, purpose: str, start: str = DATA_START, end: str = DATA_END) -> None:
        self.guard.check_range(start, end, layer="DOWNLOAD")          # before ANY request is built
        self.dir.mkdir(parents=True, exist_ok=True)
        syms = sorted(set(symbols))
        for i in range(0, len(syms), BATCH):
            chunk, token, page = syms[i:i + BATCH], None, 0
            while True:
                body = self._get(request_params(chunk, start, end, purpose=purpose, page_token=token))
                name = f"{purpose.lower()}_{i // BATCH:04d}_{page:03d}.json.gz"
                (self.dir / name).write_bytes(gzip.compress(body, mtime=0))
                self.manifest["files"].append({"file": name, "purpose": purpose, "adjustment": PURPOSES[purpose],
                                               "symbols": chunk, "start": start, "end": end,
                                               "sha256": hashlib.sha256(body).hexdigest(),
                                               "downloaded_utc": self.clock().isoformat()})
                token, page = json.loads(body).get("next_page_token"), page + 1
                if not token:
                    break
        self.write_manifest()

    def write_manifest(self) -> None:
        agg = hashlib.sha256("".join(f["sha256"] for f in self.manifest["files"]).encode()).hexdigest()
        self.manifest["aggregate_sha256"] = agg
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=1))
        self.guard.record({"event": "download_manifest", "files": len(self.manifest["files"]), "aggregate": agg})


def load(archive_dir: Path, *, purpose: str, guard: LockedRangeGuard | None = None):
    """Archive -> DataFrame[symbol, date, open, high, low, close, volume]; verifies sha256 and the LOAD guard.
    Duplicate symbol-sessions are removed entirely (integrity tolerance) and returned as a count."""
    import pandas as pd
    guard = guard or LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    man = json.loads((Path(archive_dir) / "manifest.json").read_text())
    rows = []
    for f in man["files"]:
        if f["purpose"] != purpose:
            continue
        body = gzip.decompress((Path(archive_dir) / f["file"]).read_bytes())
        if hashlib.sha256(body).hexdigest() != f["sha256"]:
            raise HoldoutViolation(f"archive corrupted: {f['file']}")
        for sym, bars in (json.loads(body).get("bars") or {}).items():
            rows += [{"symbol": sym, "timestamp": b["t"], "open": b["o"], "high": b["h"], "low": b["l"],
                      "close": b["c"], "volume": b["v"]} for b in bars]
    df = pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])
    guard.check_frame(df, layer="LOAD")
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
    dup = df.duplicated(["symbol", "date"], keep=False)
    n_dup = int(df.loc[dup, ["symbol", "date"]].drop_duplicates().shape[0])
    df = df.loc[~dup].drop(columns="timestamp").sort_values(["symbol", "date"]).reset_index(drop=True)
    return df, {"duplicate_symbol_sessions_removed": n_dup}
