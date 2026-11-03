"""Point-in-time daily panel: pure transforms (no network). Fetching lives in ``alpaca_fetch.py``."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from . import config as C
from .splits import Split


def bars_to_wide(bars: dict[str, list[dict]], field: str) -> pd.DataFrame:
    """Alpaca bar dicts ({'t','o','h','l','c','v'}) -> sessions x symbols for one field. Index = session date."""
    cols = {}
    for sym, rows in bars.items():
        if not rows:
            continue
        idx = pd.to_datetime([r["t"] for r in rows], utc=True).tz_convert("America/New_York").normalize().tz_localize(None)
        cols[sym] = pd.Series([r[field] for r in rows], index=idx, dtype="float64")
    out = pd.DataFrame(cols).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.reindex(sorted(out.columns), axis=1)


def universe_mask(raw_close: pd.DataFrame, raw_volume: pd.DataFrame) -> pd.DataFrame:
    """DTU_V2 floor on AS-TRADED data known at the close of each session: close >= $5 and 20-session average
    dollar volume >= $20M. A name needs all 20 sessions, so a fresh listing enters after 20 sessions."""
    dollar = raw_close * raw_volume
    adv20 = dollar.rolling(20, min_periods=20).mean()
    return ((raw_close >= C.MIN_PRICE) & (adv20 >= C.MIN_ADV20_USD)).fillna(False)


def parse_splits(payload: dict) -> list[Split]:
    """Alpaca corporate-actions payload -> Split list.

    ASSUMED shape (verify on first live run): {"corporate_actions": {"forward_splits": [...], "reverse_splits": [...]}}
    with per-item ``symbol``, ``ex_date``, ``new_rate``, ``old_rate``. ratio = new_rate / old_rate, so a 2-for-1 is 2.0
    and a 1-for-10 reverse split is 0.1.
    """
    acts = payload.get("corporate_actions", {}) or {}
    out: list[Split] = []
    for kind in ("forward_splits", "reverse_splits"):
        for it in acts.get(kind, []) or []:
            try:
                ratio = float(it["new_rate"]) / float(it["old_rate"])
                out.append(Split(str(it["symbol"]), pd.Timestamp(it["ex_date"]), ratio))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                out.append(Split(str(it.get("symbol", "?")), pd.Timestamp("1900-01-01"), 0.0))   # surfaces as INVALID_RATIO
    return out


def frame_sha256(frames: dict[str, pd.DataFrame]) -> str:
    """Deterministic hash of named frames (names, column order, index and values at float64)."""
    h = hashlib.sha256()
    for name in sorted(frames):
        f = frames[name].sort_index().reindex(sorted(frames[name].columns), axis=1)
        h.update(name.encode())
        h.update(str(list(f.columns)).encode())
        h.update(f.index.strftime("%Y-%m-%d").to_numpy().astype("U10").tobytes())
        h.update(np.ascontiguousarray(f.to_numpy(dtype="float64"), dtype="float64").tobytes())
    return h.hexdigest()
