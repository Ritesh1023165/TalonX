"""EVENT_RESPONSE_MAP_V1 C1 -- candidate assembly (sources A|B|C|D) and D-1 point-in-time eligibility + buckets."""
from __future__ import annotations

import re

import pandas as pd

SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
CLOSE_MIN = 5.0
ADV20_MIN = 20_000_000.0
ADV_WINDOW = 20
BUCKETS = (("L1", 20_000_000.0, 100_000_000.0), ("L2", 100_000_000.0, 1_000_000_000.0), ("L3", 1_000_000_000.0, float("inf")))


def candidates(asset_common: set[str], rename_old: set[str], merger_acquirees: set[str], pit_sp500: set[str]) -> dict:
    """Union of the four sources, each symbol tagged with every source it came from (sorted, deterministic)."""
    out: dict[str, list[str]] = {}
    for tag, src in (("A", asset_common), ("B", rename_old), ("C", merger_acquirees), ("D", pit_sp500)):
        for s in src:
            s = str(s).strip().upper()
            if SYMBOL_RE.match(s):
                out.setdefault(s, []).append(tag)
    return dict(sorted(out.items()))


def bucket(adv20: float) -> str | None:
    for name, lo, hi in BUCKETS:
        if lo <= adv20 < hi:
            return name
    return None


def eligibility(raw: pd.DataFrame, sessions: list) -> pd.DataFrame:
    """raw: AS-TRADED daily bars [symbol, date, close, volume]. sessions: the market session calendar (sorted dates).
    For each symbol and session D: eligible iff the symbol has bars on each of the 20 sessions ending D-1 (D-1 = the
    previous MARKET session), close_{D-1} >= $5 and mean(close*volume) over those 20 sessions >= $20M.
    Uses nothing from D or later. Returns [symbol, date, close_prev, adv20, bucket, eligible]."""
    idx = {d: i for i, d in enumerate(sessions)}
    out = []
    for sym, g in raw.sort_values("date").groupby("symbol", sort=True):
        g = g[g["date"].isin(idx)]
        pos = g["date"].map(idx).to_numpy()
        dv = (g["close"] * g["volume"]).to_numpy()
        close = g["close"].to_numpy()
        for k in range(ADV_WINDOW - 1, len(g)):
            # the 20 rows ending at k must be 20 consecutive market sessions
            if pos[k] - pos[k - ADV_WINDOW + 1] != ADV_WINDOW - 1 or pos[k] + 1 >= len(sessions):
                continue
            adv = float(dv[k - ADV_WINDOW + 1:k + 1].mean())
            ok = close[k] >= CLOSE_MIN and adv >= ADV20_MIN
            out.append({"symbol": sym, "date": sessions[pos[k] + 1], "close_prev": float(close[k]), "adv20": adv,
                        "bucket": bucket(adv) if ok else None, "eligible": bool(ok)})
    return pd.DataFrame(out, columns=["symbol", "date", "close_prev", "adv20", "bucket", "eligible"])


_SUFFIX = re.compile(r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS?|GROUP|THE)\b")


def norm_name(name: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper())
    return " ".join(_SUFFIX.sub(" ", s).split())


def map_ciks(symbols: dict, sec_tickers: dict, renames: list[dict], asset_names: dict, cik_lookup: list[tuple[str, str]]) -> dict:
    """symbol -> (cik10 | None, method). Order: SEC company_tickers (current) -> rename chain (old inherits the new
    symbol's CIK) -> UNIQUE exact normalized-name match in cik-lookup-data. No CIK -> no 8-K events, benchmark SPY.
    A pre-rename ticker always uses the rename chain (tickers get recycled). Phase D additionally keeps a mapping only
    if that CIK's submissions show at least one filing dated in the development period (else UNMAPPED_INACTIVE_CIK)."""
    by_name: dict[str, set[str]] = {}
    for nm, cik in cik_lookup:
        by_name.setdefault(norm_name(nm), set()).add(str(cik).zfill(10))
    new_of = {str(r["old_symbol"]).upper(): str(r["new_symbol"]).upper() for r in renames
              if r.get("old_symbol") and r.get("new_symbol")}
    out = {}
    for s in symbols:
        if s in sec_tickers and s not in new_of:   # a renamed ticker may have been recycled: rename chain wins
            out[s] = (str(sec_tickers[s]).zfill(10), "SEC_TICKERS")
            continue
        seen, t = set(), s
        while t in new_of and t not in seen:       # follow the rename chain forward
            seen.add(t)
            t = new_of[t]
            if t in sec_tickers:
                break
        if t != s and t in sec_tickers:
            out[s] = (str(sec_tickers[t]).zfill(10), "RENAME_CHAIN")
            continue
        hits = by_name.get(norm_name(asset_names.get(s, ""))) if asset_names.get(s) else None
        out[s] = (next(iter(hits)), "UNIQUE_NAME_MATCH") if hits and len(hits) == 1 else (None, "UNMAPPED")
    return out
