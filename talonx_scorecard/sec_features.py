"""Assemble raw fundamental feature panels (sessions x symbol) for F5-F9 and F12 from SEC facts, point in time."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import sec_facts as SF

SHARE_LAG_SESSIONS = 252


def _to_symbols(w: pd.DataFrame, sym2cik: dict[str, int], symbols) -> pd.DataFrame:
    cols = {s: w[sym2cik[s]] if sym2cik.get(s) in w.columns else pd.Series(np.nan, index=w.index) for s in symbols}
    return pd.DataFrame(cols, index=w.index)


def _latest_src(*srcs: pd.DataFrame) -> pd.DataFrame:
    """Latest source date among the inputs of a ratio (what the ratio actually depends on)."""
    out = srcs[0]
    for s in srcs[1:]:
        out = np.fmax(out, s)
    return out


def build_fundamental_features(facts: pd.DataFrame, sessions: pd.DatetimeIndex, raw_close: pd.DataFrame,
                               sym2cik: dict[str, int]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Returns (features, sources). ``features`` are raw F5..F9, F12 as sessions x symbol. ``sources`` are cik-level wides of
    the filing date (ns) each value came from, used by the no-look-ahead audit."""
    symbols = list(raw_close.columns)
    ciks = sorted({c for s, c in sym2cik.items() if s in raw_close.columns and c is not None})
    flow = facts[facts["concept"].isin(SF.FLOW_TAGS)]
    ttm = SF.add_prior_year(SF.ttm_table(flow))
    inst = SF.instant_table(facts)

    def ttm_wide(concept, col="ttm"):
        t = ttm[ttm["concept"] == concept]
        return SF.asof_wide(t, col, sessions, ciks)

    def inst_wide(concept):
        t = inst[inst["concept"] == concept]
        return SF.asof_wide(t, "val", sessions, ciks)

    gp, gp_s = ttm_wide("gross_profit")
    ni, ni_s = ttm_wide("net_income")
    ocf, ocf_s = ttm_wide("op_cash_flow")
    rev = ttm[ttm["concept"] == "revenue"].copy()
    rev["growth"] = np.where(rev["ttm_prior"] > 0, rev["ttm"] / rev["ttm_prior"] - 1.0, np.nan)
    gr, gr_s = SF.asof_wide(rev, "growth", sessions, ciks)
    assets, as_s = inst_wide("assets")
    equity, eq_s = inst_wide("equity")
    shares, sh_s = inst_wide("shares")
    assets = assets.where(assets > 0)
    shares = shares.where(shares > 0)
    shares_prev = shares.shift(SHARE_LAG_SESSIONS)

    close_c = pd.DataFrame({c: raw_close[s] for s, c in sym2cik.items() if s in raw_close.columns and c in ciks}).T.groupby(level=0).first().T
    close_c = close_c.reindex(index=sessions, columns=ciks)
    mcap = shares * close_c

    feats_c = {
        "F5": gp / assets,
        "F6": (ni - ocf) / assets,
        "F7": ni / mcap,
        "F8": equity / mcap,
        "F9": gr,
        "F12": shares / shares_prev - 1.0,
    }
    sources = {
        "F5": _latest_src(gp_s, as_s), "F6": _latest_src(ni_s, ocf_s, as_s), "F7": _latest_src(ni_s, sh_s),
        "F8": _latest_src(eq_s, sh_s), "F9": gr_s, "F12": sh_s,
    }
    feats = {k: _to_symbols(v.replace([np.inf, -np.inf], np.nan), sym2cik, symbols) for k, v in feats_c.items()}
    return feats, sources


def has_fundamental(feats: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """True where at least one of F5-F9, F12 has a usable value (gate 3)."""
    acc = None
    for df in feats.values():
        m = df.notna()
        acc = m if acc is None else (acc | m)
    return acc
