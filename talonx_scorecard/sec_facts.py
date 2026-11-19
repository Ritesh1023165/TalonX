"""SEC XBRL company-facts -> point-in-time fundamental features F5-F9 and F12, plus the no-look-ahead audit.

Pure functions (no network). Point-in-time rule: a fact is usable only on sessions STRICTLY AFTER its ``filed`` date. The
companyfacts file carries only the filing date, not the acceptance time, so a filing is assumed to arrive after the 16:00
ET cutoff on its filing date (conservative: it never lets a value in early).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# concept -> XBRL tags in priority order (first tag that reports a period wins for that period)
FLOW_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "gross_profit": ["GrossProfit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "op_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}
INSTANT_TAGS = {"assets": ["Assets"], "equity": ["StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]}
NEEDED_US_GAAP = {t for d in (FLOW_TAGS, INSTANT_TAGS) for v in d.values() for t in v}
SHARES_TAG = "EntityCommonStockSharesOutstanding"
TOL = pd.Timedelta(days=10)


def extract_company(doc: dict) -> pd.DataFrame:
    """One companyfacts JSON -> long rows (concept, tag_rank, start, end, val, filed). Only the tags we use."""
    rows = []
    cik = int(doc.get("cik", 0))
    gaap = (doc.get("facts") or {}).get("us-gaap", {})
    for concept, tags in {**FLOW_TAGS, **INSTANT_TAGS}.items():
        for rank, tag in enumerate(tags):
            for it in (gaap.get(tag, {}).get("units", {}).get("USD") or []):
                if "end" in it and "val" in it and "filed" in it:
                    rows.append((cik, concept, rank, it.get("start"), it["end"], float(it["val"]), it["filed"]))
    for it in ((doc.get("facts") or {}).get("dei", {}).get(SHARES_TAG, {}).get("units", {}).get("shares") or []):
        if "end" in it and "val" in it and "filed" in it:
            rows.append((cik, "shares", 0, None, it["end"], float(it["val"]), it["filed"]))
    return pd.DataFrame(rows, columns=["cik", "concept", "rank", "start", "end", "val", "filed"])


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def first_reported(df: pd.DataFrame, flow: bool) -> pd.DataFrame:
    """Keep, for each (cik, concept, period), the highest-priority tag, then the earliest filing (no later restatements)."""
    df = _dates(df.copy())
    keys = ["cik", "concept", "start", "end"] if flow else ["cik", "concept", "end"]
    df = df.dropna(subset=["end", "filed"] + (["start"] if flow else []))
    df = df.sort_values(keys + ["rank", "filed"])
    best = df.groupby(keys, sort=False)["rank"].transform("min")
    df = df[df["rank"] == best]
    return df.sort_values(keys + ["filed"]).drop_duplicates(keys, keep="first")


def ttm_table(flow: pd.DataFrame) -> pd.DataFrame:
    """Trailing-twelve-month flows with the date each value became public. Columns: cik, concept, end, ttm, avail.

    Annual facts (~365 days) are TTM themselves. A year-to-date fact (start = fiscal-year start, ~1-3 quarters) uses
    FY_prev + YTD - YTD_prior_year. ``avail`` is the latest filing date among the components used.
    """
    f = first_reported(flow, flow=True)
    f["dur"] = (f["end"] - f["start"]).dt.days
    out = []
    for concept, g in f.groupby("concept"):
        g = g.copy()
        annual = g[(g["dur"] >= 350) & (g["dur"] <= 380)]
        out.append(annual.assign(ttm=annual["val"], avail=annual["filed"])[["cik", "concept", "end", "ttm", "avail"]])
        ytd = g[(g["dur"] >= 80) & (g["dur"] <= 290)].copy()
        if ytd.empty or annual.empty:
            continue
        ytd["bucket"] = (ytd["dur"] / 91.0).round().astype(int)
        ytd["k_fy"] = ytd["start"] - pd.Timedelta(days=1)
        ytd["k_py"] = ytd["end"] - pd.Timedelta(days=365)
        a = annual.rename(columns={"end": "a_end", "val": "fy_val", "filed": "fy_filed"})[["cik", "a_end", "fy_val", "fy_filed"]]
        m = pd.merge_asof(ytd.sort_values("k_fy"), a.sort_values("a_end"), left_on="k_fy", right_on="a_end", by="cik",
                          tolerance=TOL, direction="nearest")
        p = ytd.rename(columns={"end": "p_end", "val": "py_val", "filed": "py_filed"})[["cik", "bucket", "p_end", "py_val", "py_filed"]]
        m = pd.merge_asof(m.sort_values("k_py"), p.sort_values("p_end"), left_on="k_py", right_on="p_end", by=["cik", "bucket"],
                          tolerance=TOL, direction="nearest").dropna(subset=["fy_val", "py_val"])
        m["ttm"] = m["fy_val"] + m["val"] - m["py_val"]
        m["avail"] = m[["filed", "fy_filed", "py_filed"]].max(axis=1)
        out.append(m[["cik", "concept", "end", "ttm", "avail"]])
    if not out:
        return pd.DataFrame(columns=["cik", "concept", "end", "ttm", "avail"])
    t = pd.concat(out, ignore_index=True).sort_values(["cik", "concept", "end", "avail"])
    return t.drop_duplicates(["cik", "concept", "end"], keep="first").reset_index(drop=True)


def add_prior_year(t: pd.DataFrame) -> pd.DataFrame:
    """Attach the TTM value one year earlier (for revenue growth); available no later than the current value."""
    t = t.copy()
    t["k"] = t["end"] - pd.Timedelta(days=365)
    p = t.rename(columns={"end": "pend", "ttm": "ttm_prior", "avail": "pavail"})[["cik", "concept", "pend", "ttm_prior", "pavail"]]
    m = pd.merge_asof(t.sort_values("k"), p.sort_values("pend"), left_on="k", right_on="pend", by=["cik", "concept"],
                      tolerance=TOL, direction="nearest")
    m["avail"] = m[["avail", "pavail"]].max(axis=1)
    return m.drop(columns=["k", "pend", "pavail"])


def instant_table(df: pd.DataFrame) -> pd.DataFrame:
    """Balance-sheet and share-count facts. Share counts from several classes filed together are summed."""
    d = df[df["concept"].isin(["assets", "equity", "shares"])].copy()
    d = _dates(d)
    sh = d[d["concept"] == "shares"].groupby(["cik", "concept", "end", "filed"], as_index=False).agg(val=("val", "sum"), rank=("rank", "min"))
    sh["start"] = pd.NaT
    d = pd.concat([d[d["concept"] != "shares"], sh], ignore_index=True)
    d = first_reported(d, flow=False)
    return d.rename(columns={"filed": "avail"})[["cik", "concept", "end", "val", "avail"]].reset_index(drop=True)


def asof_wide(tbl: pd.DataFrame, value: str, sessions: pd.DatetimeIndex, ciks) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(value wide, source-filed-date wide) on sessions x cik. A row is usable on sessions strictly after ``avail``."""
    t = tbl.dropna(subset=[value, "avail"]).copy()
    t["idx"] = np.searchsorted(sessions.values, t["avail"].values, side="right")
    t = t[t["idx"] < len(sessions)].sort_values(["idx", "end"])
    last = t.groupby(["idx", "cik"], sort=False).tail(1)
    v = last.pivot(index="idx", columns="cik", values=value).reindex(index=range(len(sessions)))
    s = last.assign(filed_i=last["avail"].astype("int64")).pivot(index="idx", columns="cik", values="filed_i").reindex(index=range(len(sessions)))
    v.index = s.index = sessions
    v, s = v.reindex(columns=list(ciks)).ffill(), s.reindex(columns=list(ciks)).ffill()
    return v, s


def audit_no_lookahead(source_filed: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> tuple[bool, int, str]:
    """Gate 4 audit: every feature value's source filing date (int ns) must be strictly before its rank date."""
    checked = bad = 0
    ses_ns = sessions.values.astype("datetime64[ns]").astype("int64")[:, None]
    for name, s in source_filed.items():
        a = s.to_numpy(dtype=float)
        m = ~np.isnan(a)
        checked += int(m.sum())
        n_bad = int(((a >= ses_ns) & m).sum())
        bad += n_bad
    return bad == 0, checked, f"{checked} feature-days checked, {bad} with a source dated on or after the rank date"
