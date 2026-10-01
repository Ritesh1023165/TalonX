"""
Task 97 — dataset builder (Phase 1).

Inputs (all existing, £0):
  results/task95a_regime_expansion/_expanded_data/<SYM>.csv   1-min OHLCV, SIP raw, UTC
  results/task95b_swing_foundation/_daily_all.parquet         split-adj daily + atr_pct
  results/task95i_filing_alpha/_events/core_events.parquet    catalyst events

Outputs (results/task97_catalyst_displacement/):
  task97_panel.parquet         one row per (symbol, trading day) with a valid 09:35 entry
  task97_events.parquet        catalyst rows joined to gap/RVOL/forward returns/MFE-MAE/group
  task97_dataset_manifest.json fingerprints + counts

Frozen defs: MARKET_ENERGY_SPEC.md, RVOL_CAUSALITY_SPEC.md, CATALYST_EVENT_SPEC.md.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("results/task97_catalyst_displacement")
MIN_DIR = Path("results/task95a_regime_expansion/_expanded_data")
DAILY = Path("results/task95b_swing_foundation/_daily_all.parquet")
EVENTS = Path("results/task95i_filing_alpha/_events/core_events.parquet")
ET = "America/New_York"

# forward horizons in minutes from the 09:35 entry (intraday)
H_30 = 30
H_60 = 60

PRIMARY_FAMILIES = {
    "EARN": {"2.02"},
    "REGFD": {"7.01"},
    "AGREEMENT": {"1.01"},
    "MNA": {"2.01"},
    "RESTRUCT": {"2.05"},
}
DIAG_FAMILIES = {
    "EXEC": {"5.02"}, "OTHER8K": {"8.01"}, "DEBT": {"2.03"}, "VOTE": {"5.07"},
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


ENTRY_MIN = 574        # bar covering 09:34:00-09:34:59 -> close is the 09:35 price
M_30 = ENTRY_MIN + H_30   # 604 -> 10:05 price
M_60 = ENTRY_MIN + H_60   # 634 -> 10:35 price
M_0945 = 584


def build_symbol(sym: str, daily_sym: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(MIN_DIR / f"{sym}.csv", usecols=["timestamp", "open", "high", "low", "close", "volume"])
    ts = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(ET)
    df["date"] = ts.dt.normalize().dt.tz_localize(None)
    df["et_min"] = ts.dt.hour * 60 + ts.dt.minute
    reg = df[(df["et_min"] >= 570) & (df["et_min"] <= 959)].copy()
    del df

    daily_sym = daily_sym.copy()
    daily_sym["d"] = pd.to_datetime(daily_sym["date"]).dt.tz_localize(None)
    split_days = set(daily_sym.loc[daily_sym["is_split_day"] == True, "d"])  # noqa: E712
    dd = daily_sym.set_index("d")[["atr_pct", "rv20", "rv60"]]

    n_bars = reg.groupby("date").size()
    good_days = n_bars[n_bars >= 60].index

    # per-minute close pivot for the specific minutes we need
    want = reg[reg["et_min"].isin([570, ENTRY_MIN, M_30, M_60, M_0945])]
    piv_c = want.pivot_table(index="date", columns="et_min", values="close", aggfunc="first")
    piv_o = reg[reg["et_min"] == 570].set_index("date")["open"]

    first5 = reg[reg["et_min"].between(570, 574)].groupby("date")["volume"].sum()
    eod_close = reg.groupby("date")["close"].last()

    post = reg[reg["et_min"] >= 575]
    hi = post.groupby("date")["high"].max()
    lo = post.groupby("date")["low"].min()
    hi_idx = post.loc[post.groupby("date")["high"].idxmax()][["date", "et_min"]].set_index("date")["et_min"]
    lo_idx = post.loc[post.groupby("date")["low"].idxmin()][["date", "et_min"]].set_index("date")["et_min"]

    out = pd.DataFrame(index=pd.Index(sorted(good_days), name="date")).reset_index()
    out["symbol"] = sym
    out["open_0930"] = out["date"].map(piv_o).fillna(out["date"].map(lambda d: np.nan))
    for col, m in [("entry_px", ENTRY_MIN), ("px_0945", M_0945), ("_p30", M_30), ("_p60", M_60)]:
        out[col] = out["date"].map(piv_c[m]) if m in piv_c.columns else np.nan
    out["eod_px"] = out["date"].map(eod_close)
    out["vol_first5"] = out["date"].map(first5)
    out["atr_pct"] = out["date"].map(dd["atr_pct"])
    out["rv20"] = out["date"].map(dd["rv20"])
    out["rv60"] = out["date"].map(dd["rv60"])
    out["is_split_day"] = out["date"].isin(split_days)

    out = out.sort_values("date").reset_index(drop=True)
    out["prev_close"] = out["eod_px"].shift(1)
    out["prev_date"] = out["date"].shift(1)
    out["gap"] = out["open_0930"] / out["prev_close"] - 1.0
    out["r_30m"] = out["_p30"] / out["entry_px"] - 1
    out["r_60m"] = out["_p60"] / out["entry_px"] - 1
    out["r_eod"] = out["eod_px"] / out["entry_px"] - 1
    out["mfe"] = out["date"].map(hi) / out["entry_px"] - 1
    out["mae"] = out["date"].map(lo) / out["entry_px"] - 1
    out["t_mfe"] = out["date"].map(hi_idx) - 575
    out["t_mae"] = out["date"].map(lo_idx) - 575
    out = out.drop(columns=["_p30", "_p60"])

    # causal RVOL: trailing-20 median of vol_first5, shifted 1 (strictly before entry day)
    tr = out["vol_first5"].shift(1).rolling(20, min_periods=10).median()
    out["rvol_open"] = out["vol_first5"] / tr

    # +1D / +3D from the 09:35 entry price to the Nth-later trading-day EOD close
    eod = out["eod_px"].values
    entry = out["entry_px"].values
    r1 = np.full(len(out), np.nan)
    r3 = np.full(len(out), np.nan)
    for i in range(len(out)):
        if entry[i] != entry[i]:
            continue
        if i + 1 < len(out) and eod[i + 1] == eod[i + 1]:
            r1[i] = eod[i + 1] / entry[i] - 1
        if i + 3 < len(out) and eod[i + 3] == eod[i + 3]:
            r3[i] = eod[i + 3] / entry[i] - 1
    out["r_1d"] = r1
    out["r_3d"] = r3
    # overnight vs intraday split for +1D
    out["r_1d_overnight"] = np.where(
        (out["eod_px"].notna()) & (out["open_0930"].shift(-1).notna()),
        out["open_0930"].shift(-1) / out["eod_px"] - 1, np.nan,
    )
    return out


def main() -> None:
    daily = pd.read_parquet(DAILY)
    daily["date"] = pd.to_datetime(daily["date"]).dt.tz_localize(None)
    syms = sorted(p.stem for p in MIN_DIR.glob("*.csv"))
    print(f"building {len(syms)} symbols ...")

    panels = []
    for i, sym in enumerate(syms, 1):
        dsym = daily[daily["symbol"] == sym].copy()
        p = build_symbol(sym, dsym)
        panels.append(p)
        print(f"  [{i}/{len(syms)}] {sym}: {len(p)} trading days, "
              f"entries={p['entry_px'].notna().sum()}, "
              f"rvol!na={p['rvol_open'].notna().sum()}")
    panel = pd.concat(panels, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])

    # -- leave-one-out equal-weight basket per date/horizon -------------
    for h in ["r_30m", "r_60m", "r_eod", "r_1d", "r_3d"]:
        grp = panel.groupby("date")[h]
        s = grp.transform("sum")
        c = grp.transform("count")
        panel[f"bmk_{h}"] = (s - panel[h].fillna(0)) / (c - panel[h].notna().astype(int)).replace(0, np.nan)
        panel[f"exc_{h}"] = panel[h] - panel[f"bmk_{h}"]

    panel["year"] = panel["date"].dt.year
    panel["month"] = panel["date"].dt.strftime("%Y-%m")
    ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(ROOT / "task97_panel.parquet", index=False)
    print(f"panel: {panel.shape} -> task97_panel.parquet")

    # -- catalyst events ------------------------------------------------
    ev = pd.read_parquet(EVENTS)
    ev["entry_day"] = pd.to_datetime(ev["entry_day"])
    ev["acc_ts"] = pd.to_datetime(ev["acc_ts_utc"], utc=True).dt.tz_convert(ET)

    # INTRADAY events: defer to the next trading day's 09:35
    trading_days_by_sym = {s: sorted(panel.loc[panel.symbol == s, "date"].dt.normalize().unique())
                           for s in panel.symbol.unique()}

    def next_td(sym, day):
        tds = trading_days_by_sym.get(sym, [])
        for t in tds:
            if t > day:
                return t
        return pd.NaT

    ev["eff_entry_day"] = ev["entry_day"]
    intraday_mask = ev["session"] == "INTRADAY"
    ev.loc[intraday_mask, "eff_entry_day"] = [
        next_td(s, d) for s, d in zip(ev.loc[intraday_mask, "symbol"],
                                     ev.loc[intraday_mask, "entry_day"])
    ]
    ev["entry_deferred_intraday"] = intraday_mask

    def fams(items: str) -> list[str]:
        codes = {c.strip() for c in str(items).split(",") if c.strip()}
        out = [f for f, its in PRIMARY_FAMILIES.items() if codes & its]
        out += [f for f, its in DIAG_FAMILIES.items() if codes & its]
        if "10-Q" in str(items) or "10-K" in str(items):
            out.append("PERIODIC")
        return out

    ev["families"] = ev["items"].fillna("").map(fams)
    ev.loc[ev["base_form"].isin(["10-Q", "10-K"]), "families"] = ev.loc[
        ev["base_form"].isin(["10-Q", "10-K"]), "families"
    ].map(lambda x: sorted(set(x) | {"PERIODIC"}))
    ev["is_primary_catalyst"] = ev["families"].map(
        lambda fs: any(f in PRIMARY_FAMILIES for f in fs)
    )

    # merge event -> panel row on (symbol, eff_entry_day)
    key = panel.rename(columns={"date": "eff_entry_day"})
    key["eff_entry_day"] = key["eff_entry_day"].dt.normalize()
    ev["eff_entry_day"] = pd.to_datetime(ev["eff_entry_day"]).dt.normalize()
    merged = ev.merge(
        key[["symbol", "eff_entry_day", "prev_close", "open_0930", "entry_px", "gap",
             "rvol_open", "vol_first5", "atr_pct", "rv20", "rv60",
             "r_30m", "r_60m", "r_eod", "r_1d", "r_3d", "r_1d_overnight",
             "mfe", "mae", "t_mfe", "t_mae", "is_split_day",
             "bmk_r_30m", "bmk_r_60m", "bmk_r_eod", "bmk_r_1d", "bmk_r_3d",
             "exc_r_30m", "exc_r_60m", "exc_r_eod", "exc_r_1d", "exc_r_3d"]],
        on=["symbol", "eff_entry_day"], how="left", suffixes=("_evt", ""),
    )

    # energy tier
    ag = merged["gap"].abs()
    rv = merged["rvol_open"]
    merged["tier"] = "NO_ENERGY"
    merged.loc[(ag >= 0.02) & (rv >= 2.0), "tier"] = "MODERATE"
    merged.loc[(ag >= 0.03) & (rv >= 3.0), "tier"] = "STRONG"
    merged.loc[(ag >= 0.05) & (rv >= 4.0), "tier"] = "EXTREME"
    merged["high_energy"] = merged["tier"] != "NO_ENERGY"
    merged["pos_gap"] = merged["gap"] > 0
    merged["long_energy"] = merged["high_energy"] & merged["pos_gap"]

    # group A/B for catalyst rows (C/D built in the analysis script from the panel)
    merged["group"] = np.where(
        merged["is_primary_catalyst"] & merged["long_energy"], "A",
        np.where(merged["is_primary_catalyst"], "B", "non_primary"),
    )
    merged["has_entry"] = merged["entry_px"].notna()
    merged.to_parquet(ROOT / "task97_events.parquet", index=False)
    print(f"events: {merged.shape} -> task97_events.parquet")
    print("group counts (primary-catalyst rows with an entry):")
    print(merged[merged.has_entry & merged.is_primary_catalyst]["group"].value_counts())
    print("tier counts (primary-catalyst rows with an entry, pos gap):")
    print(merged[merged.has_entry & merged.is_primary_catalyst & merged.pos_gap]["tier"].value_counts())

    manifest = {
        "built_utc": pd.Timestamp.utcnow().isoformat(),
        "sources": {
            "minute_dir": str(MIN_DIR), "daily": str(DAILY), "events": str(EVENTS),
            "daily_sha256": _sha(DAILY), "events_sha256": _sha(EVENTS),
        },
        "panel_rows": int(len(panel)), "panel_symbols": int(panel.symbol.nunique()),
        "panel_years": sorted(int(y) for y in panel.year.unique()),
        "panel_sha256": _sha(ROOT / "task97_panel.parquet"),
        "events_rows": int(len(merged)),
        "events_with_entry": int(merged.has_entry.sum()),
        "events_sha256": _sha(ROOT / "task97_events.parquet"),
        "primary_catalyst_with_entry": int((merged.has_entry & merged.is_primary_catalyst).sum()),
        "group_A": int((merged.has_entry & (merged.group == "A")).sum()),
        "group_B": int((merged.has_entry & (merged.group == "B")).sum()),
    }
    (ROOT / "task97_dataset_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("manifest ->", ROOT / "task97_dataset_manifest.json")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    sys.exit(main())
