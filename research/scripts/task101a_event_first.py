"""Task 101A — Event-first structural candidate attribution & gate-expectancy research.

OFFLINE RESEARCH ONLY. Zero live wiring. Does not import or touch run_talonx.py,
Telegram, paper engines, PIV, or any live runtime. Reuses talonx_quant.config
thresholds and the same pandas_ta indicator calls talonx_quant.indicators uses,
so ATR/RSI/MACD are byte-comparable with production — but computes them here in an
isolated research pass over historical 1-minute data, never in the live path.

Pre-registration: results/task101a_event_first/preregistration.md (locked before
any outcome analysis). Trigger definitions here match that document verbatim.

Usage:
    python research/scripts/task101a_event_first.py candidates   # build directional_candidates.parquet
    python research/scripts/task101a_event_first.py analyze      # all analysis artifacts from the parquet
    python research/scripts/task101a_event_first.py all
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
DATA_DIR = REPO / "results" / "task95a_regime_expansion" / "_expanded_data"
OUT = REPO / "results" / "task101a_event_first"
OUT.mkdir(parents=True, exist_ok=True)

ET = "America/New_York"
RTH_START = dt.time(9, 30)
RTH_END = dt.time(16, 0)
OR_BARS = 15                      # first 15 completed RTH 1m bars => OR (09:30..09:44)
OPEN_BLACKOUT_END = dt.time(9, 45)
CLOSE_BLACKOUT_START = dt.time(15, 30)
WARMUP_BARS = 60
F3_MAX_RECLAIM_BARS = 3
F3_CORP_ACTION_GAP = 0.25         # |overnight gap| > 25% => skip F3 for that session
COST_BPS = [0.0, 5.0, 10.0, 20.0]

# ---- frozen thresholds from talonx_quant.config (read, not hardcoded) -------------
try:
    from talonx_quant.config import QuantConfig
    _c = QuantConfig()
    ATR_PERIOD = _c.atr_period
    RSI_PERIOD = _c.rsi_period
    RSI_OS = _c.rsi_oversold
    RSI_OB = _c.rsi_overbought
    MACD_FAST, MACD_SLOW, MACD_SIGNAL = _c.macd_fast, _c.macd_slow, _c.macd_signal
    VOL_AVG = _c.volume_avg_period
    VOL_SURGE = _c.volume_surge_ratio_threshold
    ATR_MOVE_MULT = _c.atr_move_multiplier
    ATR_STOP_MULT = _c.atr_stop_multiplier
    ATR_REWARD_MULT = _c.atr_reward_multiplier
    HTF_SMA = _c.htf_sma_period
    ORIG = dict(min_atr_pct=_c.min_atr_pct, confluence_min=_c.confluence_score_min,
                min_rr=_c.min_risk_reward_ratio)
except Exception as e:  # pragma: no cover - config must be importable
    print(f"FATAL: could not read QuantConfig: {e}", file=sys.stderr)
    raise
EXP = dict(min_atr_pct=0.10, confluence_min=1, min_rr=1.0)

HORIZONS = {"15m": 15, "30m": 30, "60m": 60}


def _live_universe() -> set[str]:
    try:
        con = sqlite3.connect(os.path.expanduser("~/.talonx/watchlist.db"))
        live = set()
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            sc = "symbol" if "symbol" in cols else ("ticker" if "ticker" in cols else None)
            if sc:
                for (s,) in con.execute(f"SELECT DISTINCT {sc} FROM {t}"):
                    if s:
                        live.add(str(s).upper())
        con.close()
        return live
    except Exception:
        return set()


LIVE = _live_universe()


def _pandas_ta_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """RSI/MACD/ATR via the exact same df.ta.* calls talonx_quant.indicators uses."""
    import pandas_ta as ta  # noqa: F401  (df.ta accessor side effect)
    out = df.copy()
    out["rsi"] = df.ta.rsi(length=RSI_PERIOD)
    macd = df.ta.macd(fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    # pandas_ta cols: MACD_12_26_9 (line), MACDs_12_26_9 (signal), MACDh_12_26_9 (hist)
    mcol = [c for c in macd.columns if c.startswith("MACD_")][0]
    scol = [c for c in macd.columns if c.startswith("MACDs_")][0]
    out["macd"] = macd[mcol]
    out["macd_sig"] = macd[scol]
    out["atr"] = df.ta.atr(length=ATR_PERIOD)
    # this bar's own true range (same formula ATR averages)
    pc = df["close"].shift(1)
    out["btr"] = np.maximum.reduce([
        (df["high"] - df["low"]).values,
        (df["high"] - pc).abs().values,
        (df["low"] - pc).abs().values,
    ])
    out["vol_avg20"] = df["volume"].rolling(VOL_AVG).mean()
    out["vol_surge"] = df["volume"] / out["vol_avg20"]
    return out


def _load_symbol(path: str) -> pd.DataFrame | None:
    sym = os.path.basename(path)[:-4]
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["et"] = df["timestamp"].dt.tz_convert(ET)
    df["date"] = df["et"].dt.date
    df["tod"] = df["et"].dt.time
    df["dow"] = df["et"].dt.weekday
    rth = df[(df["tod"] >= RTH_START) & (df["tod"] < RTH_END)].copy()
    rth = rth.sort_values("et").reset_index(drop=True)
    if len(rth) < WARMUP_BARS + 400:
        return None
    rth["symbol"] = sym
    # continuous-series indicators (spans session boundaries, as production ATR does)
    rth = _pandas_ta_indicators(rth)
    return rth


def _session_avwap(g: pd.DataFrame) -> np.ndarray:
    tp = (g["high"] + g["low"] + g["close"]).values / 3.0
    v = g["volume"].values.astype(float)
    cpv = np.cumsum(tp * v)
    cv = np.cumsum(v)
    with np.errstate(divide="ignore", invalid="ignore"):
        aw = np.where(cv > 0, cpv / cv, np.nan)
    return aw


def _detect_candidates(rth: pd.DataFrame) -> list[dict]:
    sym = rth["symbol"].iloc[0]
    cands: list[dict] = []
    # prior-session H/L/C for pivots + prior-day-low, per date
    day_stats = rth.groupby("date").agg(
        d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last"),
        d_open=("open", "first"), n=("close", "size"),
    )
    dates = list(day_stats.index)
    prev_of = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

    # 15m HTF SMA200 (RTH-only buckets), causal: value known at the close of each 15m bucket
    r = rth.set_index("et")
    htf = r["close"].resample("15min", label="right", closed="right", origin="start_day").last().dropna()
    htf_sma = htf.rolling(HTF_SMA).mean()
    # map each 1m bar to the SMA of the most-recently-COMPLETED 15m bucket strictly before it
    sma_idx = htf_sma.index
    sma_val = htf_sma.values
    bar_et = rth["et"].values
    pos = np.searchsorted(sma_idx.values, bar_et, side="right") - 1
    htf_sma_for_bar = np.where(pos >= 0, sma_val[np.clip(pos, 0, len(sma_val) - 1)], np.nan)
    rth = rth.copy()
    rth["htf_sma200"] = htf_sma_for_bar

    # Warm-up: drop whole leading trading dates (not a mid-session bar slice), so every
    # per-date `g` below is a COMPLETE session -> the opening-range window and per-bar
    # loops always start at the true 09:30 session open. WARMUP_BARS/390 dates rounded up,
    # minimum 1, so indicators (ATR14/RSI14/MACD, ~26-bar warm-up) are settled.
    all_dates = sorted(set(rth["date"]))
    n_warm_dates = min(len(all_dates) - 1, max(1, (WARMUP_BARS + 389) // 390))
    warm = rth if n_warm_dates <= 0 else rth[rth["date"] >= all_dates[n_warm_dates]]
    for date, g in warm.groupby("date"):
        g = g.reset_index(drop=True)
        if len(g) < 30:
            continue
        n = len(g)
        close = g["close"].values
        low = g["low"].values
        high = g["high"].values
        openp = g["open"].values
        tod = g["tod"].values
        aw = _session_avwap(g)
        rsi = g["rsi"].values
        atr = g["atr"].values
        btr = g["btr"].values
        vs = g["vol_surge"].values
        macd = g["macd"].values
        macd_sig = g["macd_sig"].values
        sma200 = g["htf_sma200"].values
        et_arr = g["et"].values

        pdate = prev_of.get(date)
        prior = day_stats.loc[pdate] if pdate is not None else None
        pdl = float(prior["d_low"]) if prior is not None else np.nan
        if prior is not None:
            ph, pl, pc = float(prior["d_high"]), float(prior["d_low"]), float(prior["d_close"])
            pp = (ph + pl + pc) / 3.0
            piv_s1 = 2 * pp - ph
            piv_r1 = 2 * pp - pl
            gap = abs(float(g["open"].iloc[0]) / pc - 1.0) if pc else np.nan
        else:
            piv_s1 = piv_r1 = np.nan
            gap = np.nan
        corp_action_suspect = (not np.isfinite(gap)) or (gap > F3_CORP_ACTION_GAP)

        def emit(i_trigger, direction, trigger_type, extra=None):
            """i_trigger indexes bar t within g; reference = open of t+1."""
            ts = pd.Timestamp(et_arr[i_trigger])
            has_next = i_trigger + 1 < n
            ref = float(openp[i_trigger + 1]) if has_next else np.nan
            rec = dict(
                candidate_id=f"{sym}:{trigger_type}:{ts.isoformat()}",
                symbol=sym, trigger_type=trigger_type, direction=direction,
                candidate_timestamp=ts.isoformat(), source_bar_timestamp=ts.isoformat(),
                session_date=str(date),
                trigger_bar_idx=int(i_trigger), n_session_bars=int(n),
                reference_price=ref, has_next_bar=bool(has_next),
                trigger_close=float(close[i_trigger]),
                avwap_at_t=float(aw[i_trigger]) if np.isfinite(aw[i_trigger]) else np.nan,
                prior_day_low=pdl, prior_day_high=(float(prior["d_high"]) if prior is not None else np.nan),
                piv_s1=piv_s1, piv_r1=piv_r1, overnight_gap=gap,
                corp_action_suspect=bool(corp_action_suspect),
                # market state
                atr=float(atr[i_trigger]) if np.isfinite(atr[i_trigger]) else np.nan,
                atr_pct=(float(atr[i_trigger]) / float(close[i_trigger]) * 100.0)
                if np.isfinite(atr[i_trigger]) and close[i_trigger] else np.nan,
                btr=float(btr[i_trigger]) if np.isfinite(btr[i_trigger]) else np.nan,
                vol_surge=float(vs[i_trigger]) if np.isfinite(vs[i_trigger]) else np.nan,
                rsi_t=float(rsi[i_trigger]) if np.isfinite(rsi[i_trigger]) else np.nan,
                rsi_t1=float(rsi[i_trigger - 1]) if i_trigger - 1 >= 0 and np.isfinite(rsi[i_trigger - 1]) else np.nan,
                rsi_t2=float(rsi[i_trigger - 2]) if i_trigger - 2 >= 0 and np.isfinite(rsi[i_trigger - 2]) else np.nan,
                rsi_t3=float(rsi[i_trigger - 3]) if i_trigger - 3 >= 0 and np.isfinite(rsi[i_trigger - 3]) else np.nan,
                macd_cross_up=bool(i_trigger - 1 >= 0 and np.isfinite(macd[i_trigger]) and np.isfinite(macd_sig[i_trigger])
                                   and np.isfinite(macd[i_trigger - 1]) and np.isfinite(macd_sig[i_trigger - 1])
                                   and macd[i_trigger - 1] <= macd_sig[i_trigger - 1] and macd[i_trigger] > macd_sig[i_trigger]),
                macd_cross_dn=bool(i_trigger - 1 >= 0 and np.isfinite(macd[i_trigger]) and np.isfinite(macd_sig[i_trigger])
                                   and np.isfinite(macd[i_trigger - 1]) and np.isfinite(macd_sig[i_trigger - 1])
                                   and macd[i_trigger - 1] >= macd_sig[i_trigger - 1] and macd[i_trigger] < macd_sig[i_trigger]),
                htf_sma200=float(sma200[i_trigger]) if np.isfinite(sma200[i_trigger]) else np.nan,
                tod=str(tod[i_trigger]),
                in_open_blackout=bool(tod[i_trigger] < OPEN_BLACKOUT_END),
                in_close_blackout=bool(tod[i_trigger] >= CLOSE_BLACKOUT_START),
                in_live_universe=bool(sym in LIVE),
                year=ts.year,
            )
            if extra:
                rec.update(extra)
            cands.append(rec)

        # ---- F1: session AVWAP reclaim (BULLISH), dedup per reclaim episode ----
        eligible = True
        for i in range(1, n):
            if not (np.isfinite(aw[i]) and np.isfinite(aw[i - 1])):
                continue
            if eligible and close[i - 1] <= aw[i - 1] and close[i] > aw[i]:
                emit(i, "BULLISH", "F1_AVWAP_RECLAIM")
                eligible = False
            elif not eligible and close[i] < aw[i] and low[i] < aw[i]:
                eligible = True  # decisively re-lost AVWAP -> next reclaim eligible

        # ---- F2: 15m opening-range breakout ----
        if n > OR_BARS + 2 and str(tod[OR_BARS - 1]) <= "09:45:00":
            or_hi = float(np.max(high[:OR_BARS]))
            or_lo = float(np.min(low[:OR_BARS]))
            fired_up = fired_dn = False
            for i in range(OR_BARS, n):
                if not fired_up and close[i] > or_hi and close[i - 1] <= or_hi:
                    emit(i, "BULLISH", "F2_OR_BREAKOUT", dict(or_high=or_hi, or_low=or_lo))
                    fired_up = True
                if not fired_dn and close[i] < or_lo and close[i - 1] >= or_lo:
                    emit(i, "BEARISH", "F2_OR_BREAKDOWN", dict(or_high=or_hi, or_low=or_lo, informational=True))
                    fired_dn = True
                if fired_up and fired_dn:
                    break

        # ---- F3: prior-day-low sweep / reclaim (BULLISH) ----
        if prior is not None and np.isfinite(pdl) and not corp_action_suspect:
            i = 0
            while i < n:
                if low[i] < pdl:  # sweep at bar i
                    reclaim_idx = None
                    ambiguous = False
                    for j in range(i, min(i + F3_MAX_RECLAIM_BARS + 1, n)):
                        if close[j] > pdl:
                            reclaim_idx = j
                            if j == i:
                                ambiguous = True  # same-bar sweep+reclaim, order unknown
                            break
                    if reclaim_idx is not None:
                        emit(reclaim_idx, "BULLISH", "F3_PDL_RECLAIM",
                             dict(sweep_bar_idx=int(i), reclaim_lag=int(reclaim_idx - i),
                                  same_bar_ambiguous=bool(ambiguous)))
                        # advance past this episode: to first bar back above pdl and then next sweep
                        k = reclaim_idx + 1
                        while k < n and low[k] < pdl:
                            k += 1
                        i = k
                        continue
                i += 1
    return cands


def _confluence(direction, macd_cross_up, macd_cross_dn, rsi_val, vol_surge):
    """talonx_quant.strategy._confluence_score semantics; structural trigger is
    never a MACD trigger so own_trigger_is_macd=False (the MACD leg always counts
    when a cross occurred)."""
    score = 0
    if (macd_cross_up or macd_cross_dn):
        score += 1
    if np.isfinite(rsi_val):
        if direction == "BULLISH" and rsi_val < RSI_OS:
            score += 1
        elif direction == "BEARISH" and rsi_val > RSI_OB:
            score += 1
    if np.isfinite(vol_surge) and vol_surge > VOL_SURGE:
        score += 1
    return score


def _rr_structural(direction, ref, atr, s1, r1):
    """talonx_quant.strategy.calculate_trade_geometry: rr defined ONLY when both
    the structural stop (S1<ref) and structural target (R1>ref) are valid."""
    if direction != "BULLISH" or not (np.isfinite(ref) and np.isfinite(atr) and atr > 0 and ref > 0):
        return np.nan, np.nan, np.nan
    if np.isfinite(s1) and 0 < s1 < ref:
        stop = s1
    else:
        stop = ref - ATR_STOP_MULT * atr
    risk = ref - stop
    if risk <= 0:
        return np.nan, stop, np.nan
    if np.isfinite(r1) and r1 > ref:
        target = r1
        reward = target - ref
        rr = reward / risk
    else:
        target = ref + ATR_REWARD_MULT * atr
        rr = np.nan  # reward=None in production => rr undefined
    return rr, stop, target


def build_candidates() -> pd.DataFrame:
    files = sorted(glob.glob(str(DATA_DIR / "*.csv")))
    all_rows: list[dict] = []
    per_symbol_bars = {}
    for k, f in enumerate(files, 1):
        sym = os.path.basename(f)[:-4]
        rth = _load_symbol(f)
        if rth is None:
            print(f"[{k}/{len(files)}] {sym}: SKIP (insufficient)")
            continue
        per_symbol_bars[sym] = int(len(rth))
        cands = _detect_candidates(rth)
        # forward attribution per symbol (needs the full rth series)
        _attribute_forward(rth, cands)
        all_rows.extend(cands)
        print(f"[{k}/{len(files)}] {sym}: {len(rth):>7} bars -> {len(cands):>6} candidates")
    df = pd.DataFrame(all_rows)
    # gates (vectorized over the frame)
    _apply_gates(df)
    df.to_parquet(OUT / "directional_candidates.parquet", index=False)
    (OUT / "_per_symbol_bars.json").write_text(json.dumps(per_symbol_bars, indent=2))
    print(f"\nWROTE {len(df)} candidates -> directional_candidates.parquet")
    return df


def _attribute_forward(rth: pd.DataFrame, cands: list[dict]) -> None:
    """Causal forward returns / MFE / MAE / path metrics from reference_price
    (open of t+1), using only bars at/after t+1."""
    by_date = {d: g.reset_index(drop=True) for d, g in rth.groupby("date")}
    dates = list(by_date.keys())
    next_date = {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}
    for c in cands:
        d = dt.date.fromisoformat(c["session_date"])
        g = by_date[d]
        it = c["trigger_bar_idx"]
        n = len(g)
        if not c["has_next_bar"]:
            continue
        ref = c["reference_price"]
        start = it + 1
        fwd_close = g["close"].values[start:]
        fwd_high = g["high"].values[start:]
        fwd_low = g["low"].values[start:]
        sign = 1.0 if c["direction"] == "BULLISH" else -1.0

        def ret_at(mins):
            j = min(mins - 1, len(fwd_close) - 1)  # close 'mins' minutes after ref-bar open
            if j < 0:
                return np.nan, False
            trunc = (mins - 1) > (len(fwd_close) - 1)
            return sign * (fwd_close[j] / ref - 1.0), trunc

        for name, mm in HORIZONS.items():
            r, trunc = ret_at(mm)
            c[f"ret_{name}"] = r
            c[f"ret_{name}_trunc"] = bool(trunc)
        # EOD
        c["ret_eod"] = sign * (g["close"].values[-1] / ref - 1.0) if n > start else np.nan
        # +1D
        nd = next_date.get(d)
        c["ret_1d"] = (sign * (by_date[nd]["close"].values[-1] / ref - 1.0)) if nd is not None else np.nan
        # MFE / MAE over t+1 .. EOD (favourable = direction-aligned)
        if len(fwd_close) > 0:
            up = fwd_high / ref - 1.0
            dn = fwd_low / ref - 1.0
            if c["direction"] == "BULLISH":
                c["mfe"] = float(np.max(up)); c["mae"] = float(np.min(dn))
            else:
                c["mfe"] = float(-np.min(dn)); c["mae"] = float(-np.max(up))  # favourable decline / adverse rise
        else:
            c["mfe"] = c["mae"] = np.nan
        # structural path metrics (BULLISH only, finite structural risk)
        rr, stop, target = _rr_structural(c["direction"], ref, c["atr"], c["piv_s1"], c["piv_r1"])
        c["rr_structural"] = rr
        c["struct_stop"] = stop
        c["struct_target"] = target
        c["risk_per_share"] = (ref - stop) if (np.isfinite(stop) and c["direction"] == "BULLISH") else np.nan
        if c["direction"] == "BULLISH" and np.isfinite(stop) and (ref - stop) > 0 and len(fwd_close) > 0:
            R = ref - stop
            tgt_1r = ref + R
            tgt_15 = ref + 1.5 * R
            tgt_2r = ref + 2.0 * R
            hit_stop = fwd_low <= stop
            first_stop = np.argmax(hit_stop) if hit_stop.any() else 10**9
            for lbl, tg in (("1r", tgt_1r), ("15r", tgt_15), ("2r", tgt_2r)):
                hit_t = fwd_high >= tg
                first_t = np.argmax(hit_t) if hit_t.any() else 10**9
                # conservative same-bar rule: adverse first
                if first_t == first_stop and first_t < 10**9:
                    c[f"pos_{lbl}_before_stop"] = False
                else:
                    c[f"pos_{lbl}_before_stop"] = bool(first_t < first_stop)
            c["stop_before_1r"] = bool(first_stop < (np.argmax(fwd_high >= tgt_1r) if (fwd_high >= tgt_1r).any() else 10**9)
                                       or (first_stop < 10**9 and not (fwd_high >= tgt_1r).any()))
            # realised R at first exit (target 1R vs stop), conservative same-bar
            hit1 = fwd_high >= tgt_1r
            f1 = np.argmax(hit1) if hit1.any() else 10**9
            if f1 == first_stop and f1 < 10**9:
                c["path_R_1rt"] = -1.0
            elif f1 < first_stop:
                c["path_R_1rt"] = 1.0
            elif first_stop < 10**9:
                c["path_R_1rt"] = -1.0
            else:
                c["path_R_1rt"] = float(sign * (g["close"].values[-1] - ref) / R)  # neither touched -> EOD in R
        # forward R at fixed horizons (BULLISH, finite risk)
        if c["direction"] == "BULLISH" and np.isfinite(c.get("risk_per_share", np.nan)) and c["risk_per_share"] > 0:
            for name in HORIZONS:
                c[f"R_{name}"] = c[f"ret_{name}"] * ref / c["risk_per_share"] if np.isfinite(c[f"ret_{name}"]) else np.nan
            c["R_eod"] = c["ret_eod"] * ref / c["risk_per_share"] if np.isfinite(c["ret_eod"]) else np.nan


def _apply_gates(df: pd.DataFrame) -> None:
    d = df
    d["conf_score"] = [
        _confluence(dir_, cu, cd, r, v)
        for dir_, cu, cd, r, v in zip(d["direction"], d["macd_cross_up"], d["macd_cross_dn"],
                                      d["rsi_t"], d["vol_surge"])
    ]
    # RSI-memory confluence variants (BULLISH: recompute the RSI leg only)
    for k in (1, 2, 3):
        cols = ["rsi_t"] + [f"rsi_t{j}" for j in range(1, k + 1)]
        rmin = d[cols].min(axis=1, skipna=True)
        base_no_rsi = [
            _confluence(dir_, cu, cd, np.nan, v)  # confluence WITHOUT rsi leg
            for dir_, cu, cd, v in zip(d["direction"], d["macd_cross_up"], d["macd_cross_dn"], d["vol_surge"])
        ]
        rsi_leg = ((d["direction"] == "BULLISH") & (rmin < RSI_OS)) | ((d["direction"] == "BEARISH") & (rmin > RSI_OB))
        d[f"conf_score_mem{k}"] = np.array(base_no_rsi) + rsi_leg.astype(int).values
    d["conf_score_mem0"] = d["conf_score"]

    for label, cfg in (("orig", ORIG), ("exp", EXP)):
        d[f"{label}_atr_pass"] = d["atr_pct"] >= cfg["min_atr_pct"]
        d[f"{label}_conf_pass"] = d["conf_score"] >= cfg["confluence_min"]
        d[f"{label}_rr_pass"] = d["rr_structural"].notna() & (d["rr_structural"] >= cfg["min_rr"])
        # trend: BULLISH regular only; None(n/a) counts as pass
        trend_applicable = d["direction"] == "BULLISH"
        trend_ok = (~trend_applicable) | (d["reference_price"] > d["htf_sma200"])
        # if htf_sma200 is NaN -> not knowable -> production returns None -> treat as pass (n/a)
        trend_ok = trend_ok | d["htf_sma200"].isna()
        d[f"{label}_trend_pass"] = trend_ok
        d[f"{label}_openblk_pass"] = ~d["in_open_blackout"]
        d[f"{label}_closeblk_pass"] = ~((d["direction"] == "BULLISH") & d["in_close_blackout"])
        d[f"{label}_impulse_pass"] = d["btr"] >= (ATR_MOVE_MULT * d["atr"])
        d[f"{label}_would_pass"] = (
            d[f"{label}_atr_pass"] & d[f"{label}_conf_pass"] & d[f"{label}_rr_pass"]
            & d[f"{label}_trend_pass"] & d[f"{label}_openblk_pass"] & d[f"{label}_closeblk_pass"]
        )
    # first rejection reason + rejection vector (Original)
    order = [("ATR", "orig_atr_pass"), ("CONFLUENCE", "orig_conf_pass"), ("RR", "orig_rr_pass"),
             ("TREND", "orig_trend_pass"), ("OPEN_BLACKOUT", "orig_openblk_pass"),
             ("CLOSE_BLACKOUT", "orig_closeblk_pass")]

    def first_rej(row):
        for name, col in order:
            if not row[col]:
                return name
        return "NONE"

    d["first_rejection"] = d.apply(first_rej, axis=1)
    d["n_orig_fail"] = sum((~d[c]).astype(int) for _, c in order)
    d["rejection_vector"] = [
        ";".join(name for name, col in order if not row[col]) or "NONE"
        for _, row in d.iterrows()
    ]


# ================================ ANALYSIS ====================================

# --- DEFECT FIX (documented deviation from preregistration §8): raw R = ret*ref/(ref-stop)
# explodes when the structural stop (prior-session S1 pivot) sits pathologically close to the
# reference price (risk_frac -> 0, ~1.4% of BULLISH candidates). The preregistered *definition*
# of R is preserved; for AGGREGATION only, the effective per-share risk is floored at 0.10% of
# the reference price (a realistic minimum meaningful stop) and the resulting R is winsorized to
# +/-10. All headline acceptance criteria (preregistration §12) are stated in bps net of cost and
# are unaffected by this fix. ---
_R_RISK_FLOOR_FRAC = 0.001
_R_WINSOR = 10.0


def _robust_R(s: pd.DataFrame, ret_col: str) -> pd.Series:
    rf = ((s["reference_price"] - s["struct_stop"]) / s["reference_price"]).clip(lower=_R_RISK_FLOOR_FRAC)
    R = (s[ret_col] / rf).clip(-_R_WINSOR, _R_WINSOR)
    return R[(s["direction"] == "BULLISH") & s["struct_stop"].notna()]


def _fmt_row(sub: pd.DataFrame, horizon="ret_30m") -> dict:
    s = sub[sub["has_next_bar"]]
    r = s[horizon].dropna()
    if len(r) == 0:
        return dict(N=len(sub), mean_bps=np.nan)
    rr = _robust_R(s, "ret_eod").dropna()
    net10 = r - 10 / 1e4
    net20 = r - 20 / 1e4
    wins = (r > 0).mean()
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    p1r = s.get("pos_1r_before_stop")
    return dict(
        N=len(s),
        mean_R=float(rr.mean()) if len(rr) else np.nan,
        median_R=float(rr.median()) if len(rr) else np.nan,
        gross_bps=float(r.mean() * 1e4),
        net10_bps=float(net10.mean() * 1e4),
        net20_bps=float(net20.mean() * 1e4),
        win_pct=float(wins * 100),
        pf=float(pf),
        median_mfe_bps=float(s["mfe"].median() * 1e4),
        median_mae_bps=float(s["mae"].median() * 1e4),
        p1r_before_stop=float(p1r.mean() * 100) if p1r is not None and p1r.notna().any() else np.nan,
    )


def analyze() -> None:
    df = pd.read_parquet(OUT / "directional_candidates.parquet")
    fams = {
        "F1_AVWAP": df["trigger_type"] == "F1_AVWAP_RECLAIM",
        "F2_OR_bull": df["trigger_type"] == "F2_OR_BREAKOUT",
        "F2_OR_bear_info": df["trigger_type"] == "F2_OR_BREAKDOWN",
        "F3_PDL": (df["trigger_type"] == "F3_PDL_RECLAIM") & (~df["same_bar_ambiguous"].fillna(False)),
        "F3_PDL_ambiguous": (df["trigger_type"] == "F3_PDL_RECLAIM") & (df["same_bar_ambiguous"].fillna(False)),
        "ALL_bull": df["direction"] == "BULLISH",
    }
    # ---- Phase 9: gate expectancy matrix ----
    rows = []
    for fam, mask in fams.items():
        base = df[mask]
        subsets = {
            "1_ALL": base,
            "2_orig_PASS": base[base["orig_would_pass"]],
            "3_exp_WOULD_PASS": base[base["exp_would_pass"]],
            "4_ATR_only_reject": base[(~base["orig_atr_pass"]) & base["orig_conf_pass"] & base["orig_rr_pass"] & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "5_CONF_only_reject": base[base["orig_atr_pass"] & (~base["orig_conf_pass"]) & base["orig_rr_pass"] & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "6_RR_only_reject": base[base["orig_atr_pass"] & base["orig_conf_pass"] & (~base["orig_rr_pass"]) & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "7_TREND_only_reject": base[base["orig_atr_pass"] & base["orig_conf_pass"] & base["orig_rr_pass"] & (~base["orig_trend_pass"]) & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "8_OPENBLK_only_reject": base[base["orig_atr_pass"] & base["orig_conf_pass"] & base["orig_rr_pass"] & base["orig_trend_pass"] & (~base["orig_openblk_pass"]) & base["orig_closeblk_pass"]],
            "9_multi_gate_reject": base[base["n_orig_fail"] >= 2],
            "10_ATRfail_rest_pass": base[(~base["orig_atr_pass"]) & base["orig_conf_pass"] & base["orig_rr_pass"] & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "11_CONFfail_rest_pass": base[base["orig_atr_pass"] & (~base["orig_conf_pass"]) & base["orig_rr_pass"] & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
            "12_RRfail_rest_pass": base[base["orig_atr_pass"] & base["orig_conf_pass"] & (~base["orig_rr_pass"]) & base["orig_trend_pass"] & base["orig_openblk_pass"] & base["orig_closeblk_pass"]],
        }
        for sname, sub in subsets.items():
            r = _fmt_row(sub)
            r.update(family=fam, subset=sname)
            rows.append(r)
    gem = pd.DataFrame(rows)[["family", "subset", "N", "mean_R", "median_R", "gross_bps",
                              "net10_bps", "net20_bps", "win_pct", "pf", "median_mfe_bps",
                              "median_mae_bps", "p1r_before_stop"]]
    gem.to_csv(OUT / "gate_expectancy_matrix.csv", index=False)

    # ---- Phase 10: continuous gate distributions ----
    cd_rows = []
    atr_bins = [(-1, .10), (.10, .15), (.15, .20), (.20, .25), (.25, .30), (.30, 99)]
    rr_bins = [(-99, .5), (.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 999)]
    bull = df[(df["direction"] == "BULLISH") & df["has_next_bar"]]
    for lo, hi in atr_bins:
        sub = bull[(bull["atr_pct"] >= lo) & (bull["atr_pct"] < hi)]
        r = _fmt_row(sub); r.update(dim="atr_pct", bin=f"{lo}-{hi}"); cd_rows.append(r)
    for cs in [0, 1, 2, 3]:
        sub = bull[bull["conf_score"] == cs]
        r = _fmt_row(sub); r.update(dim="confluence", bin=str(cs)); cd_rows.append(r)
    for lo, hi in rr_bins:
        sub = bull[bull["rr_structural"].between(lo, hi, inclusive="left")]
        r = _fmt_row(sub); r.update(dim="rr", bin=f"{lo}-{hi}"); cd_rows.append(r)
    sub = bull[bull["rr_structural"].isna()]
    r = _fmt_row(sub); r.update(dim="rr", bin="undefined"); cd_rows.append(r)
    pd.DataFrame(cd_rows)[["dim", "bin", "N", "gross_bps", "net10_bps", "net20_bps",
                           "mean_R", "median_R", "median_mfe_bps", "median_mae_bps",
                           "win_pct", "p1r_before_stop"]].to_csv(
        OUT / "continuous_gate_distributions.csv", index=False)

    # ---- Phase 11: brain visibility ----
    bv = df[df["direction"] == "BULLISH"].copy()
    bv["d"] = bv["session_date"]
    per_day = bv.groupby("d").agg(
        structural=("candidate_id", "size"),
        orig_pass=("orig_would_pass", "sum"),
        exp_pass=("exp_would_pass", "sum"),
    )
    # peak 15-min burst
    ts = pd.to_datetime(bv["candidate_timestamp"], utc=True)
    burst = bv.assign(bucket=ts.dt.floor("15min")).groupby("bucket").size()
    bvsum = dict(
        trading_days=int(per_day.shape[0]),
        structural_per_day_mean=float(per_day["structural"].mean()),
        structural_per_day_median=float(per_day["structural"].median()),
        structural_per_symbol_day=float(bv.groupby(["symbol", "d"]).size().mean()),
        orig_pass_per_day_mean=float(per_day["orig_pass"].mean()),
        exp_pass_per_day_mean=float(per_day["exp_pass"].mean()),
        peak_15min_burst=int(burst.max()),
        p95_15min_burst=int(burst.quantile(0.95)),
        total_structural_bull=int(len(bv)),
    )
    (OUT / "brain_visibility_summary.md").write_text(
        "# Brain visibility (event-first, analysis only -- no live Brain)\n\n"
        + "\n".join(f"- **{k}**: {v}" for k, v in bvsum.items()) + "\n", encoding="utf-8")

    # ---- Phase 12: robustness (per family) ----
    rob = {}
    for fam, mask in {"F1_AVWAP": fams["F1_AVWAP"], "F2_OR_bull": fams["F2_OR_bull"], "F3_PDL": fams["F3_PDL"]}.items():
        s = df[mask & df["has_next_bar"]].copy()
        s = s[s["ret_30m"].notna()]
        if len(s) < 50:
            rob[fam] = {"N": len(s), "note": "insufficient"}
            continue
        r = s["ret_30m"].values
        net10 = r.mean() * 1e4 - 10
        # bootstrap by trading-day block
        s["d"] = s["session_date"]
        day_groups = [g["ret_30m"].values for _, g in s.groupby("d")]
        rng = np.random.default_rng(101)
        boot = []
        for _ in range(1000):
            pick = rng.integers(0, len(day_groups), len(day_groups))
            vals = np.concatenate([day_groups[i] for i in pick])
            boot.append(vals.mean() * 1e4 - 10)
        lo, hi = np.percentile(boot, [5, 95])
        by_year = s.groupby("year")["ret_30m"].mean() * 1e4 - 10
        by_sym = s.groupby("symbol")["ret_30m"].agg(["size", "mean"])
        by_sym["contrib"] = by_sym["size"] * by_sym["mean"]
        top_sym = by_sym["contrib"].abs().idxmax()
        s_wo_top = s[s["symbol"] != top_sym]
        # top-5 winners removal
        s_sorted = s.sort_values("ret_30m", ascending=False)
        s_wo_top5 = s_sorted.iloc[5:]
        # regime split
        def reg(y):
            return "2020-21" if y <= 2021 else ("2022" if y == 2022 else "2023-26")
        by_regime = s.assign(rg=s["year"].map(reg)).groupby("rg")["ret_30m"].mean() * 1e4 - 10
        # chrono holdout
        train = s[s["session_date"] < "2024-01-01"]["ret_30m"].mean() * 1e4 - 10
        hold = s[s["session_date"] >= "2024-01-01"]["ret_30m"].mean() * 1e4 - 10
        rob[fam] = dict(
            N=int(len(s)),
            net10_bps=float(net10),
            net20_bps=float(r.mean() * 1e4 - 20),
            boot_ci90=[float(lo), float(hi)],
            by_year_net10={int(k): float(v) for k, v in by_year.items()},
            by_regime_net10={k: float(v) for k, v in by_regime.items()},
            top_symbol_by_contrib=top_sym,
            net10_wo_top_symbol=float(s_wo_top["ret_30m"].mean() * 1e4 - 10),
            net10_wo_top5_winners=float(s_wo_top5["ret_30m"].mean() * 1e4 - 10),
            symbol_herfindahl=float(((by_sym["size"] / by_sym["size"].sum()) ** 2).sum()),
            train_net10=float(train), holdout_net10=float(hold),
            median_bps=float(np.median(r) * 1e4),
        )
    (OUT / "robustness_report.md").write_text(
        "# Task 101A robustness / anti-curve-fit (primary horizon +30m, net of 10bps unless noted)\n\n"
        "```json\n" + json.dumps(rob, indent=2) + "\n```\n")

    # ---- trigger_summary.csv ----
    tsum = []
    for fam, mask in fams.items():
        s = df[mask]
        sh = s[s["has_next_bar"]]
        tsum.append(dict(
            family=fam, N=len(s), N_with_fwd=len(sh),
            orig_pass=int(s["orig_would_pass"].sum()),
            exp_pass=int(s["exp_would_pass"].sum()),
            gross_30m_bps=float(sh["ret_30m"].mean() * 1e4),
            net10_30m_bps=float(sh["ret_30m"].mean() * 1e4 - 10),
            net10_eod_bps=float(sh["ret_eod"].mean() * 1e4 - 10),
            win30_pct=float((sh["ret_30m"] > 0).mean() * 100),
            median_mfe_bps=float(sh["mfe"].median() * 1e4),
            median_mae_bps=float(sh["mae"].median() * 1e4),
        ))
    pd.DataFrame(tsum).to_csv(OUT / "trigger_summary.csv", index=False)

    # ---- RSI memory analysis ----
    b = df[(df["direction"] == "BULLISH") & df["has_next_bar"] & df["ret_30m"].notna()]
    rsi_rows = []
    for k in range(4):
        col = f"conf_score_mem{k}"
        passers = b[b[col] >= ORIG["confluence_min"]]
        newly = b[(b[col] >= ORIG["confluence_min"]) & (b["conf_score_mem0"] < ORIG["confluence_min"])]
        rsi_rows.append(dict(
            variant=f"mem{k}",
            n_conf_ge2=int((b[col] >= 2).sum()),
            n_conf_ge1=int((b[col] >= 1).sum()),
            n_newly_passing_vs_mem0=int(len(newly)),
            newly_passing_net10_30m_bps=float(newly["ret_30m"].mean() * 1e4 - 10) if len(newly) else np.nan,
            all_passers_net10_30m_bps=float(passers["ret_30m"].mean() * 1e4 - 10) if len(passers) else np.nan,
        ))
    pd.DataFrame(rsi_rows).to_csv(OUT / "rsi_memory_analysis.csv", index=False)

    # ---- R:R decay ----
    bb = df[(df["direction"] == "BULLISH")].copy()
    dec = bb[bb["rr_structural"].notna()]
    rr_decay = dict(
        n_with_structural_rr=int(len(dec)),
        median_rr_structural=float(dec["rr_structural"].median()),
        pct_rr_ge_1_5=float((dec["rr_structural"] >= 1.5).mean() * 100),
        median_rr_by_family={
            f: float(dec[dec["trigger_type"].str.startswith(f)]["rr_structural"].median())
            for f in ["F1", "F2_OR_BREAKOUT", "F3"]
        },
        note="rr_original_decision (delayed-confirmation reference) not separately recomputed in "
             "this pass — see final_report.md R:R decay section for the methodological limitation.",
    )
    (OUT / "rr_decay_analysis.md").write_text(
        "# R:R structural distribution (BULLISH candidates)\n\n```json\n"
        + json.dumps(rr_decay, indent=2) + "\n```\n")

    # markdown mirror of the expectancy matrix
    (OUT / "gate_expectancy_matrix.md").write_text(
        "# Gate expectancy matrix (primary horizon +30m)\n\n" + _df_to_md(gem.round(3)) + "\n")
    print("Analysis artifacts written to", OUT)


def _df_to_md(d: pd.DataFrame) -> str:
    cols = list(d.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in d.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("candidates", "all"):
        build_candidates()
    if mode in ("analyze", "all"):
        analyze()
