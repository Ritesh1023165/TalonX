"""Task75A -- fingerprint determinism and single-frozen-parameter-set tests."""
from __future__ import annotations

from research.task75_v1 import contracts as C
from research.task75_v1.fingerprint import compute_contract_only_fingerprint, compute_fingerprint


def test_full_fingerprint_deterministic():
    fp1 = compute_fingerprint()
    fp2 = compute_fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 64


def test_contract_only_fingerprint_matches_recorded_value():
    assert compute_contract_only_fingerprint() == "677adccd7e653e30c96122f0149356523f3a2fb3cb82a3d4967c3a1a06aa6f06"


def test_full_fingerprint_matches_recorded_value():
    assert compute_fingerprint() == "08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3"


def test_single_frozen_parameter_set_no_alternatives():
    # V1 must freeze exactly ONE threshold, ONE lookback, ONE horizon --
    # no grid/list of alternatives may exist in the contract.
    assert isinstance(C.UPPER_PERCENTILE, float)
    assert isinstance(C.LOOKBACK_TRADING_DAYS, int)
    assert isinstance(C.EXIT_HORIZON_TRADING_DAYS, int)
    assert C.DIRECTION == "SHORT_ONLY"


def test_universe_is_fixed_35_symbols():
    assert len(C.UNIVERSE) == 35
    assert C.MARKET_SYMBOL == "SPY"
    assert C.MARKET_SYMBOL not in C.UNIVERSE
