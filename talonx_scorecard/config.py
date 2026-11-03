"""Locked study constants. Transcribed from the approved pre-registration; do not edit after approval."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

SPEC_COMMIT = "4a3bec3125e181baea695dab3f2bebb1f9037395"
SPEC_PATH = "docs/research/preregistration/2026-11-03_ticker_scorecard_v1.md"

# Horizon -> label window length in sessions (close t -> close t+h).
HORIZONS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}
# 1D ranks every session; the others rank every Friday close (or the last session of the week).
RANK_DAILY = {"1D"}

SAMPLE_START = "2019-01-02"
SAMPLE_END = "2026-10-30"
SEGMENTS = {  # inclusive rank-date ranges
    "TRAIN": ("2019-01-02", "2023-12-29"),
    "VALIDATE": ("2024-01-02", "2024-12-31"),
    "HOLDOUT": ("2025-01-02", "2026-06-30"),
}
SEGMENT_ORDER = ("TRAIN", "VALIDATE", "HOLDOUT")

# Universe floor (DTU_V2): as-traded close >= $5 and 20-day average dollar volume >= $20M.
MIN_PRICE = 5.0
MIN_ADV20_USD = 20_000_000.0

COST_BULL_BPS = 20.0   # round trip
COST_BEAR_BPS = 10.0   # one sell

WINSOR = (0.01, 0.99)
MISSING_FILL = 0.5
MAX_MISSING_FEATURES = 6          # a name missing MORE than this many of 12 is dropped for that date
RIDGE_ALPHA = 1.0
RIDGE_MIN_IC_GAIN = 0.005         # RIDGE chosen only if VALIDATE IC beats EQ by at least this
DECILE = 0.10

# Data gates (checked before any outcome is computed).
GATE_LABEL_COVERAGE = 0.90
GATE_FUNDAMENTAL_COVERAGE = 0.80
CUTOFF_ET = "16:00"

# Outcome gates, evaluated on HOLDOUT.
G1_MIN_IC = 0.0
G4_MIN_POSITIVE_MONTH_SHARE = 0.60
G5_MIN_BULL_HIT = 0.52
G5_MAX_BEAR_HIT = 0.48
G5_MAX_CAL_ERROR = 0.05
G3_MAX_BEAR_EXCESS_BPS = -10.0


@dataclass(frozen=True)
class Feature:
    id: str
    family: str
    name: str
    sign: int          # +1: higher raw value is bullish; -1: higher raw value is bearish (flipped before blending)


FEATURES = (
    Feature("F1", "Reversal", "ret_5d", -1),
    Feature("F2", "Reversal", "ret_21d_skip5", -1),
    Feature("F3", "Trend", "ret_12m_skip1m", +1),
    Feature("F4", "Risk", "vol_60d", -1),
    Feature("F5", "Quality", "gross_profitability", +1),
    Feature("F6", "Quality", "accruals", -1),
    Feature("F7", "Value", "earnings_yield", +1),
    Feature("F8", "Value", "book_to_market", +1),
    Feature("F9", "Growth", "revenue_growth", +1),
    Feature("F10", "Insider", "net_insider_buyers_90d", +1),
    Feature("F11", "FilingRisk", "risk_factor_change", -1),
    Feature("F12", "Dilution", "share_count_change", -1),
)
assert len(FEATURES) == 12


def spec_fingerprint() -> str:
    """SHA-256 of every locked constant. Recorded with every run; a mismatch means the spec was edited."""
    payload = {
        "commit": SPEC_COMMIT, "horizons": HORIZONS, "rank_daily": sorted(RANK_DAILY),
        "sample": [SAMPLE_START, SAMPLE_END], "segments": SEGMENTS,
        "floor": [MIN_PRICE, MIN_ADV20_USD], "costs": [COST_BULL_BPS, COST_BEAR_BPS],
        "winsor": WINSOR, "fill": MISSING_FILL, "max_missing": MAX_MISSING_FEATURES,
        "ridge": [RIDGE_ALPHA, RIDGE_MIN_IC_GAIN], "decile": DECILE,
        "data_gates": [GATE_LABEL_COVERAGE, GATE_FUNDAMENTAL_COVERAGE, CUTOFF_ET],
        "gates": [G1_MIN_IC, G4_MIN_POSITIVE_MONTH_SHARE, G5_MIN_BULL_HIT, G5_MAX_BEAR_HIT,
                  G5_MAX_CAL_ERROR, G3_MAX_BEAR_EXCESS_BPS],
        "features": [(f.id, f.family, f.name, f.sign) for f in FEATURES],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
