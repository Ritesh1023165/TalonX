"""Dynamic Tradable Universe study -- D-1 tradability features that do not exist locally (READ-ONLY research).

For every symbol ELIGIBLE in any stored window (market.db ``universe``), from the EXISTING Alpaca SIP subscription
(no new provider, nothing written to production stores):
  * RTH 1-minute bars per session  -> rth_bars, rth_coverage (= bars / 390), rth_dollars, rth_trades,
                                      median 1-min range proxy (h-l)/vwap in bps
  * sampled NBBO quotes per session (SIP ``/v2/stocks/quotes``) at fixed instants, widening the window for symbols
    without a quote -> median quoted spread in bps ((ask-bid)/mid), n quotes, sample window used
Rate: <= RATE_PER_MIN requests/min (default 60; live ingestion + outcomes stay < 200/min shared).
The cost of the run (requests, seconds, rows) is recorded -- it is the measured cost of a daily D-1 batch.
usage: python fetch_d1_features.py OUT_DIR [RATE_PER_MIN]"""
from __future__ import annotations

import gzip
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from talonx_premarket import __main__ as M  # noqa: E402
from talonx_premarket.alpaca_data import AlpacaData, RateLimiter, iso  # noqa: E402

UTC = timezone.utc
QUOTES_URL = "https://data.alpaca.markets/v2/stocks/quotes"
# (session, RTH open UTC, RTH close UTC) -- EDT sessions (13:30-20:00Z)
BAR_SESSIONS = ("2026-09-24", "2026-09-25", "2026-09-28")
QUOTE_SESSIONS = ("2026-09-25", "2026-09-28")
QUOTE_INSTANTS = ("15:00:00", "18:00:00")        # UTC instants (11:00 / 14:00 ET), away from open/close auctions
QUOTE_WINDOWS_S = (2, 60, 900)                   # widen for symbols with no valid quote


def symbols() -> list[str]:
    import sqlite3
    c = sqlite3.connect(f"file:{REPO / 'results' / 'opportunity' / 'market.db'}?mode=ro", uri=True)
    out = set()
    for (mj,) in c.execute("SELECT members_json FROM universe"):
        out |= {m["symbol"] for m in json.loads(mj) if m.get("status") == "ELIGIBLE"}
    return sorted(out)


def rth_bars(data: AlpacaData, syms: list[str], day: str) -> dict:
    d = datetime.fromisoformat(day).replace(tzinfo=UTC)
    start, end = d + timedelta(hours=13, minutes=30), d + timedelta(hours=19, minutes=59)
    res = data.bars_ex(syms, timeframe="1Min", start=start, end=end)
    out = {}
    for s in syms:
        if s in res.failed:
            out[s] = {"failed": True}
            continue
        rows = [b for b in res.bars.get(s, []) if b.get("v", 0) > 0 and b.get("c", 0) > 0]
        rng = sorted((b["h"] - b["l"]) / (b.get("vw") or b["c"]) * 1e4 for b in rows if (b.get("vw") or b["c"]) > 0)
        out[s] = {"rth_bars": len(rows), "rth_coverage": round(len(rows) / 390, 4),
                  "rth_dollars": round(sum(b["v"] * (b.get("vw") or b["c"]) for b in rows), 0),
                  "rth_trades": sum(int(b.get("n") or 0) for b in rows),
                  "range_bps_med": round(statistics.median(rng), 2) if rng else None,
                  "last_close": rows[-1]["c"] if rows else None}
    return out


def quotes(data: AlpacaData, syms: list[str], start: datetime, end: datetime) -> tuple[dict, int]:
    got: dict[str, list[float]] = {}
    pages = 0
    for i in range(0, len(syms), 200):
        batch, token = syms[i:i + 200], None
        while True:
            p = {"symbols": ",".join(batch), "start": iso(start), "end": iso(end), "feed": "sip", "limit": "10000"}
            if token:
                p["page_token"] = token
            try:
                j = data._call(QUOTES_URL, p)
            except Exception as exc:  # noqa: BLE001 -- recorded; the symbols stay unmeasured (never invented)
                data.errors.append(f"quotes batch@{i}: {exc}")
                break
            pages += 1
            for s, rows in (j.get("quotes") or {}).items():
                for q in rows:
                    bp, ap = float(q.get("bp") or 0), float(q.get("ap") or 0)
                    if bp > 0 and ap > bp:
                        got.setdefault(s, []).append((ap - bp) / ((ap + bp) / 2) * 1e4)
            token = j.get("next_page_token")
            if not token:
                break
    return got, pages


def main(out_dir: str, rate: int = 60) -> None:
    M._env()
    base = M._data()
    data = AlpacaData(key_id=base._headers["APCA-API-KEY-ID"], secret=base._headers["APCA-API-SECRET-KEY"],
                      limiter=RateLimiter(rate))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    syms = symbols()
    cost = {"symbols": len(syms), "rate_per_min": rate, "started_utc": datetime.now(UTC).isoformat()}
    for day in BAR_SESSIONS:
        t0, r0 = time.monotonic(), data.requests
        feats = rth_bars(data, syms, day)
        cost[f"bars_{day}"] = {"requests": data.requests - r0, "seconds": round(time.monotonic() - t0, 1),
                               "failed": sum(1 for v in feats.values() if v.get("failed"))}
        with gzip.open(out / f"rth_bars_{day}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(feats, f)
        print(day, cost[f"bars_{day}"], flush=True)
    for day in QUOTE_SESSIONS:
        t0, r0 = time.monotonic(), data.requests
        spreads: dict[str, dict] = {}
        pages_total = 0
        for inst in QUOTE_INSTANTS:
            at = datetime.fromisoformat(f"{day}T{inst}+00:00")
            todo = list(syms)
            for w in QUOTE_WINDOWS_S:
                if not todo:
                    break
                got, pages = quotes(data, todo, at, at + timedelta(seconds=w))
                pages_total += pages
                for s, xs in got.items():
                    spreads.setdefault(s, {"samples": []})["samples"].append(
                        {"instant": inst, "window_s": w, "n": len(xs), "med_bps": round(statistics.median(xs), 2)})
                todo = [s for s in todo if s not in got]
        for s, v in spreads.items():
            v["spread_bps_med"] = round(statistics.median(x["med_bps"] for x in v["samples"]), 2)
        cost[f"quotes_{day}"] = {"requests": data.requests - r0, "pages": pages_total,
                                 "seconds": round(time.monotonic() - t0, 1), "measured_symbols": len(spreads)}
        with gzip.open(out / f"spreads_{day}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(spreads, f)
        print(day, cost[f"quotes_{day}"], flush=True)
    cost["errors"] = data.errors[-20:]
    cost["finished_utc"] = datetime.now(UTC).isoformat()
    (out / "fetch_cost.json").write_text(json.dumps(cost, indent=1), encoding="utf-8")
    print(json.dumps(cost))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], int(a[1]) if len(a) > 1 else 60)
