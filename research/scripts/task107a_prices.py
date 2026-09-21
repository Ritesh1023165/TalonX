"""
task107a_prices.py  --  TASK 107A Phase 7  (price-coverage audit, NO returns)
============================================================================
Fetch survivorship-inclusive daily bars (Alpaca SIP, adjustment=all,
entitled GET) for every issuer that appears in a candidate insider
buy-cluster episode, using the MULTI-SYMBOL bars endpoint (batched +
paginated) so ~4k tickers cost ~1-2k requests instead of ~4k.

No return, excess, or price change is computed -- only bar existence and
horizon reach.

Reuses results/task95g_broad_cross_sectional/_daily/*.csv where present.
New symbols -> results/task107a_form4_feasibility/_prices/*.csv
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task107a_form4_feasibility"
BUILD = OUT / "_build"
PRICES = OUT / "_prices"
PANEL = ROOT / "results" / "task95g_broad_cross_sectional" / "_daily"
PRICES.mkdir(parents=True, exist_ok=True)

_SYM_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def clean_sym(s: str) -> str | None:
    s = str(s).strip().strip('"').strip("'").strip("()").replace(" ", "").upper()
    return s if _SYM_RE.match(s) else None


KEY = SEC = None
for line in (ROOT / ".env").read_text().splitlines():
    if line.startswith("APCA_API_KEY_ID="):
        KEY = line.split("=", 1)[1].strip()
    elif line.startswith("APCA_API_SECRET_KEY="):
        SEC = line.split("=", 1)[1].strip()

_SESS = requests.Session()
_SESS.headers.update({"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC})
URL = "https://data.alpaca.markets/v2/stocks/bars"
START, END = "2019-01-01", "2026-08-31"
BATCH = 90


def fetch_batch(syms: list[str]) -> dict[str, list[tuple]]:
    acc: dict[str, list[tuple]] = {s: [] for s in syms}
    token = None
    for _ in range(400):
        params = {
            "symbols": ",".join(syms), "timeframe": "1Day", "adjustment": "all",
            "feed": "sip", "start": START, "end": END, "limit": 10000,
        }
        if token:
            params["page_token"] = token
        for attempt in range(6):
            try:
                r = _SESS.get(URL, params=params, timeout=90)
            except Exception:  # noqa: BLE001
                time.sleep(1.5 + attempt)
                continue
            if r.status_code == 429:
                time.sleep(3 + 3 * attempt)
                continue
            break
        else:
            break
        if r.status_code != 200:
            break
        j = r.json()
        for sym, bars in (j.get("bars") or {}).items():
            for b in bars:
                acc.setdefault(sym, []).append(
                    (b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]))
        token = j.get("next_page_token")
        if not token:
            break
    return acc


def main():
    panel_syms = {f.stem.upper() for f in PANEL.glob("*.csv")}
    want = set()
    for fn in ["episodes_w10_mo2.parquet", "episodes_w5_mo2.parquet", "episodes_w10_mo3.parquet"]:
        p = BUILD / fn
        if p.exists():
            want |= set(pd.read_parquet(p).issuer_sym.unique())
    want_clean = {c for s in want if (c := clean_sym(s))}
    todo = sorted(s for s in want_clean
                  if s not in panel_syms and not (PRICES / f"{s}.csv").exists())
    print(f"episode issuers {len(want)}  cleaned {len(want_clean)}  in panel {len(want_clean & panel_syms)}")
    print(f"to fetch: {len(todo)}  (batch={BATCH})", flush=True)

    ok = miss = 0
    t0 = time.time()
    for bi in range(0, len(todo), BATCH):
        batch = todo[bi:bi + BATCH]
        res = fetch_batch(batch)
        for sym in batch:
            rows = res.get(sym) or []
            if not rows:
                (PRICES / f"{sym}.csv").write_text("EMPTY\n")
                miss += 1
            else:
                pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"]) \
                    .drop_duplicates("date").to_csv(PRICES / f"{sym}.csv", index=False)
                ok += 1
        print(f"  {bi + len(batch)}/{len(todo)}  ok={ok} miss={miss}  {time.time()-t0:.0f}s", flush=True)

    # also ensure SPY
    if not (PRICES / "SPY.csv").exists() or (PRICES / "SPY.csv").stat().st_size < 100:
        r = fetch_batch(["SPY"]).get("SPY") or []
        if r:
            pd.DataFrame(r, columns=["date", "open", "high", "low", "close", "volume"]) \
                .drop_duplicates("date").to_csv(PRICES / "SPY.csv", index=False)
            print(f"SPY: {len(r)} bars")

    print(f"done: ok={ok} miss={miss}  ({time.time()-t0:.0f}s)", flush=True)

    # coverage recompute
    ep = pd.read_parquet(BUILD / "episodes_w10_mo2.parquet")
    ep["entry_session"] = pd.to_datetime(ep["entry_session"])

    def days_for(sym):
        for base in (PANEL, PRICES):
            f = base / f"{sym}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    d = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    return pd.DatetimeIndex([])
                if "date" not in d.columns or d.empty:
                    return pd.DatetimeIndex([])
                return pd.DatetimeIndex(pd.to_datetime(d["date"]).dt.normalize()).sort_values()
        return pd.DatetimeIndex([])

    cache = {}
    have_entry = h5 = h10 = h15 = 0
    for sym, g in ep.groupby("issuer_sym"):
        if sym not in cache:
            cache[sym] = days_for(sym)
        pdays = cache[sym]
        if len(pdays) == 0:
            continue
        for e in g.entry_session.dropna():
            k = pdays.searchsorted(e, side="left")
            if k < len(pdays) and pdays[k] == e:
                have_entry += 1
                h5 += int(k + 5 < len(pdays))
                h10 += int(k + 10 < len(pdays))
                h15 += int(k + 15 < len(pdays))
    n = len(ep)
    print("\n=== BROAD PRICE COVERAGE (task95g panel + Alpaca fetch) ===")
    print(f"episodes total: {n}")
    print(f"entry bar present:    {have_entry}/{n} ({have_entry/n*100:.1f}%)")
    print(f"+5D close available:  {h5}/{n} ({h5/n*100:.1f}%)")
    print(f"+10D close available: {h10}/{n} ({h10/n*100:.1f}%)")
    print(f"+15D close available: {h15}/{n} ({h15/n*100:.1f}%)")
    (OUT / "price_coverage.txt").write_text(
        f"episodes={n} entry={have_entry} h5={h5} h10={h10} h15={h15} ok={ok} miss={miss}\n")


if __name__ == "__main__":
    sys.exit(main())
