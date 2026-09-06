"""
task107a_episodes.py  --  TASK 107A Phases 3,4,6,7,8  (NO returns)
=================================================================
Construct candidate insider open-market BUY cluster episodes and report
sample-size / causal-timing / price-coverage / frequency diagnostics
ONLY.  No forward return, price change, or outcome is read.

Episode definition (candidate, for the audit):
  * one issuer
  * >= MIN_OWNERS distinct reporting-owner CIKs, all with code P
  * all filing_date values within a rolling WINDOW trading-day span
  * "causally knowable" at MAX(filing_date) of the qualifying filings
  * earliest entry = next trading session STRICTLY after the knowable date
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

_SYM_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def clean_sym(s) -> str | None:
    s = str(s).strip().strip('"').strip("'").strip("()").replace(" ", "").upper()
    return s if _SYM_RE.match(s) else None

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task107a_form4_feasibility"
BUILD = OUT / "_build"
PANEL = ROOT / "results" / "task95g_broad_cross_sectional" / "_daily"
TXN = BUILD / "form4_open_market_txn.parquet"


def trading_days() -> pd.DatetimeIndex:
    d = pd.read_csv(PANEL / "AAPL.csv")
    return pd.DatetimeIndex(pd.to_datetime(d["date"]).dt.normalize().unique()).sort_values()


def build_episodes(P: pd.DataFrame, window_td: int, min_owners: int,
                   tdays_i8: np.ndarray) -> pd.DataFrame:
    fd_i8 = P["filing_date"].values.astype("datetime64[ns]").astype("int64")
    ford = np.searchsorted(tdays_i8, fd_i8, side="left")
    ford = np.clip(ford, 0, len(tdays_i8) - 1)
    P = P.assign(_ford=ford)
    P = P.sort_values(["issuer_sym", "_ford", "filing_date"]).reset_index(drop=True)

    sym = P["issuer_sym"].values
    ocik = P["owner_cik"].values
    val = np.nan_to_num(P["value"].values.astype("float64"))
    isoff = P["is_officer"].values.astype(bool)
    isdir = P["is_director"].values.astype(bool)
    isten = P["is_ten_pct"].values.astype(bool)
    ford = P["_ford"].values
    fdate = P["filing_date"].values

    # issuer group boundaries
    bounds = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1]])
    bounds = np.r_[bounds, len(sym)]

    rows = []
    for gi in range(len(bounds) - 1):
        a, b = bounds[gi], bounds[gi + 1]
        i = a
        while i < b:
            start_ord = ford[i]
            owners = {ocik[i]}
            v = val[i]
            of_ = bool(isoff[i]); di_ = bool(isdir[i]); te_ = bool(isten[i])
            j = i + 1
            while j < b and (ford[j] - start_ord) <= window_td:
                owners.add(ocik[j]); v += val[j]
                of_ |= bool(isoff[j]); di_ |= bool(isdir[j]); te_ |= bool(isten[j])
                j += 1
            if len(owners) >= min_owners:
                rows.append((sym[i], len(owners), j - i,
                             fdate[i], fdate[j - 1], start_ord, ford[j - 1],
                             float(v), of_, di_, te_))
                i = j
            else:
                i += 1

    ep = pd.DataFrame(rows, columns=[
        "issuer_sym", "n_distinct_owners", "n_filings",
        "first_filing", "last_filing", "first_ord", "last_ord",
        "agg_value", "any_officer", "any_director", "any_ten_pct"])
    if ep.empty:
        return ep
    # entry = first session strictly after last_ord
    entry_ord = ep["last_ord"].values + 1
    ok = entry_ord < len(tdays_i8)
    ep["entry_ord"] = np.where(ok, entry_ord, -1)
    ep["knowable_date"] = pd.to_datetime(ep["last_filing"]).dt.normalize()
    ei = np.where(ok, np.clip(entry_ord, 0, len(tdays_i8) - 1), 0)
    ep["entry_session"] = pd.to_datetime(tdays_i8[ei])
    ep.loc[~ok, "entry_session"] = pd.NaT
    return ep


def main():
    df = pd.read_parquet(TXN)
    P = df[(df.code == "P") & (df.owner_cik.astype(str).str.len() > 0)].copy()
    P["issuer_sym"] = P["issuer_sym"].map(clean_sym)
    n_bad = P["issuer_sym"].isna().sum()
    P = P[P["issuer_sym"].notna()].copy()
    print(f"dropped {n_bad} P rows with unparseable ticker")
    tdays = trading_days()
    tdays_i8 = tdays.values.astype("datetime64[ns]").astype("int64")
    print(f"calendar {tdays.min().date()}..{tdays.max().date()} ({len(tdays)} sessions)")
    print(f"P txns {len(P):,}  issuers {P.issuer_sym.nunique()}  owners {P.owner_cik.nunique()}")

    panel_syms = {f.stem.upper() for f in PANEL.glob("*.csv")}
    print(f"task95g panel symbols: {len(panel_syms)}")

    summary = []
    saved = {}
    for w in (3, 5, 7, 10):
        for mo in (2, 3):
            ep = build_episodes(P, w, mo, tdays_i8)
            if ep.empty:
                continue
            ep["in_panel"] = ep.issuer_sym.isin(panel_syms)
            yrs = ep.entry_session.dt.year.dropna()
            span_years = int(yrs.max() - yrs.min() + 1)
            summary.append(dict(
                window_td=w, min_owners=mo, episodes=len(ep),
                issuers=ep.issuer_sym.nunique(),
                in_panel=int(ep.in_panel.sum()),
                in_panel_issuers=ep.loc[ep.in_panel, "issuer_sym"].nunique(),
                median_owners=float(ep.n_distinct_owners.median()),
                ge_50k=int((ep.agg_value >= 50_000).sum()),
                ge_100k=int((ep.agg_value >= 100_000).sum()),
                ge_250k=int((ep.agg_value >= 250_000).sum()),
                ge_500k=int((ep.agg_value >= 500_000).sum()),
                ge_1m=int((ep.agg_value >= 1_000_000).sum()),
                per_year=round(len(ep) / span_years, 1),
                in_panel_per_year=round(int(ep.in_panel.sum()) / span_years, 1),
            ))
            saved[(w, mo)] = ep

    s = pd.DataFrame(summary)
    s.to_csv(OUT / "episode_counts.csv", index=False)
    print("\n=== EPISODE COUNTS (no returns) ===")
    print(s.to_string(index=False))

    for key, fn in [((10, 2), "episodes_w10_mo2.parquet"),
                    ((5, 2), "episodes_w5_mo2.parquet"),
                    ((10, 3), "episodes_w10_mo3.parquet")]:
        if key in saved:
            saved[key].to_parquet(BUILD / fn, index=False)

    ep = saved[(10, 2)]
    span = (pd.to_datetime(ep.last_filing) - pd.to_datetime(ep.first_filing)).dt.days
    gap = (ep.entry_session - ep.knowable_date).dt.days
    print("\n=== CAUSAL TIMING (primary w=10td, >=2 owners) ===")
    print(f"episodes {len(ep)}; usable entry_session {ep.entry_session.notna().mean()*100:.1f}%")
    print(f"entry strictly after knowable date: {(ep.entry_session > ep.knowable_date).mean()*100:.2f}%")
    print(f"knowable->entry gap days: median {gap.median()} p95 {gap.quantile(.95):.0f} max {gap.max()}")
    print(f"first->last filing span (cal days): median {span.median()} p90 {span.quantile(.9):.0f}")
    print("episodes by entry year:")
    print(ep.entry_session.dt.year.value_counts().sort_index().to_string())

    covered = ep[ep.issuer_sym.isin(panel_syms)].copy()
    print(f"\n=== PRICE COVERAGE (task95g panel) ===")
    print(f"episodes with issuer in panel: {len(covered)}/{len(ep)} ({len(covered)/len(ep)*100:.1f}%)")
    ok_entry = ok5 = ok10 = ok15 = 0
    cache = {}
    for sym, g in covered.groupby("issuer_sym"):
        if sym not in cache:
            try:
                d = pd.read_csv(PANEL / f"{sym}.csv")
                cache[sym] = pd.DatetimeIndex(pd.to_datetime(d["date"]).dt.normalize()).sort_values()
            except Exception:
                cache[sym] = pd.DatetimeIndex([])
        if len(cache[sym]) == 0:
            continue
        pdays = cache[sym]
        for e in g.entry_session.dropna():
            k = pdays.searchsorted(e, side="left")
            if k < len(pdays) and pdays[k] == e:
                ok_entry += 1
                ok5 += int(k + 5 < len(pdays))
                ok10 += int(k + 10 < len(pdays))
                ok15 += int(k + 15 < len(pdays))
    print(f"entry bar present: {ok_entry}/{len(covered)}")
    print(f"+5D close available:  {ok5}/{len(covered)}")
    print(f"+10D close available: {ok10}/{len(covered)}")
    print(f"+15D close available: {ok15}/{len(covered)}")

    # median spacing between episodes (whole set + in-panel set)
    for label, e2 in [("all", ep), ("in-panel", covered)]:
        dd = e2.entry_session.dropna().sort_values().diff().dt.days.dropna()
        print(f"median days between consecutive episodes ({label}): {dd.median():.1f}")


if __name__ == "__main__":
    main()
