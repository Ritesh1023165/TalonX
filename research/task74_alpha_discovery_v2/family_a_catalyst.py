"""Task74B Family A -- CATALYST_EXTREME_ACTIVITY_CONTINUATION_OR_REVERSAL.
Isolated research code. See results/task74_alpha_discovery_v2/
research_design_lock_v2.json for the locked mechanism/parameters.
"""
from __future__ import annotations

import pandas as pd

from research.task67a_lib.research_stats import forward_return_horizons
from research.task71_lib.features import add_session_columns
from research.task74_alpha_discovery_v2.features_catalyst import catalyst_features

DECISION_HOUR, DECISION_MINUTE = 10, 0
THRESHOLD_BANDS = [
    {"label": "loose", "gap_pct_min": 2.0, "rvol_min": 2.0},
    {"label": "tight", "gap_pct_min": 3.0, "rvol_min": 3.0},
]
HYPOTHESES = ["CONTINUATION", "REVERSAL"]
HORIZONS_MINUTES = [120, None]
LEDGER_COLUMNS = [
    "symbol", "trading_day", "hypothesis", "threshold_band", "gap_pct", "rvol",
    "direction", "decision_timestamp", "entry_timestamp", "entry_price",
    "horizon_label", "exit_timestamp", "gross_return_pct",
    "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _direction_for(hypothesis: str, gap_pct: float) -> str | None:
    if gap_pct == 0:
        return None
    gap_up = gap_pct > 0
    if hypothesis == "CONTINUATION":
        return "LONG" if gap_up else "SHORT"
    return "SHORT" if gap_up else "LONG"


def evaluate(bars: pd.DataFrame) -> pd.DataFrame:
    df = add_session_columns(bars)
    reg = df[df["is_regular_session"]]
    feat = catalyst_features(bars, DECISION_HOUR, DECISION_MINUTE)
    if feat.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    bars_by_symbol_day = {k: v.sort_values("timestamp") for k, v in reg.groupby(["symbol", "trading_day"])}
    et_close_by_day = {}

    rows: list[dict] = []
    for _, f in feat.iterrows():
        symbol, day = f["symbol"], f["trading_day"]
        day_bars = bars_by_symbol_day.get((symbol, day))
        if day_bars is None:
            continue
        if day not in et_close_by_day:
            et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
            et_close_by_day[day] = (et_day_start + pd.Timedelta(hours=16)).tz_convert("UTC")
        session_close_utc = et_close_by_day[day]

        for band in THRESHOLD_BANDS:
            band_met = abs(f["gap_pct"]) >= band["gap_pct_min"] and f["rvol"] >= band["rvol_min"]
            for hypothesis in HYPOTHESES:
                if not band_met:
                    rows.append(_row(symbol=symbol, trading_day=day, hypothesis=hypothesis, threshold_band=band["label"],
                                      gap_pct=f["gap_pct"], rvol=f["rvol"], decision_timestamp=f["decision_timestamp"],
                                      data_ready=False, rejection_reason="THRESHOLD_NOT_MET"))
                    continue
                direction = _direction_for(hypothesis, f["gap_pct"])
                if direction is None:
                    rows.append(_row(symbol=symbol, trading_day=day, hypothesis=hypothesis, threshold_band=band["label"],
                                      gap_pct=f["gap_pct"], rvol=f["rvol"], decision_timestamp=f["decision_timestamp"],
                                      data_ready=False, rejection_reason="THRESHOLD_NOT_MET"))
                    continue

                after = day_bars[day_bars["timestamp"] > f["decision_timestamp"]]
                if after.empty:
                    rows.append(_row(symbol=symbol, trading_day=day, hypothesis=hypothesis, threshold_band=band["label"],
                                      gap_pct=f["gap_pct"], rvol=f["rvol"], direction=direction,
                                      decision_timestamp=f["decision_timestamp"],
                                      data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
                    continue
                entry_bar = after.iloc[0]
                entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])

                horizon_results = forward_return_horizons(
                    day_bars, entry_timestamp=entry_ts, entry_price=entry_price,
                    horizons_minutes=HORIZONS_MINUTES, session_close_timestamp=session_close_utc,
                )
                for h in horizon_results:
                    label = "EOD" if h["horizon_label"] == "TO_SESSION_CLOSE" else h["horizon_label"]
                    if h["bars_observed"] == 0:
                        rows.append(_row(symbol=symbol, trading_day=day, hypothesis=hypothesis, threshold_band=band["label"],
                                          gap_pct=f["gap_pct"], rvol=f["rvol"], direction=direction,
                                          decision_timestamp=f["decision_timestamp"], entry_timestamp=entry_ts,
                                          entry_price=entry_price, horizon_label=label,
                                          data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    raw = h["forward_close_return_pct"]
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(symbol=symbol, trading_day=day, hypothesis=hypothesis, threshold_band=band["label"],
                                      gap_pct=f["gap_pct"], rvol=f["rvol"], direction=direction,
                                      decision_timestamp=f["decision_timestamp"], entry_timestamp=entry_ts,
                                      entry_price=entry_price, horizon_label=label, exit_timestamp=h["bounded_end"],
                                      gross_return_pct=signed, data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
