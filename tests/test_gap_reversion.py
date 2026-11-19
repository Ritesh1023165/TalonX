"""LARGE_GAP_REVERSION_V1: frozen spec, causal gap/entries, short-reference math, statistics and gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_paperperf import gap_reversion as G

UTC = timezone.utc
OPEN = datetime(2026, 9, 28, 13, 30, tzinfo=UTC)
CLOSE = datetime(2026, 9, 28, 20, 0, tzinfo=UTC)


def bar(i, o, h, l, c):
    return {"t": (OPEN + timedelta(minutes=i)).isoformat(), "o": o, "h": h, "l": l, "c": c, "v": 100}


def test_spec_frozen():
    assert G.VERSION == "LARGE_GAP_REVERSION_V1" and G.RESEARCH_SHORT_REFERENCE is True
    assert G.spec_fingerprint() == "18da4977123db5bf"


def test_gap_uses_open_bar_and_prior_regular_close():
    prev_close_utc = CLOSE - timedelta(days=1)
    prev = [{"t": (prev_close_utc - timedelta(minutes=k)).isoformat(), "c": 10.0 + k * 0.01} for k in (5, 1)]
    prev.append({"t": prev_close_utc.isoformat(), "c": 99.0})          # after-hours bar: never the prior close
    assert G.prior_close(prev, prev_close_utc) == pytest.approx(10.01)
    bars = [bar(-5, 11.5, 11.5, 11.5, 11.5), bar(0, 11.0, 11.2, 10.9, 11.1)]
    ob = G.open_bar(bars, OPEN)
    assert ob["o"] == 11.0 and G.gap(ob["o"], 10.0) == pytest.approx(0.10)


def test_sampling_and_buckets_deterministic():
    assert G.in_sample("X", "2025-01-02", 0.12)
    assert not G.in_sample("X", "2025-01-02", 0.02)
    assert G.in_sample("X", "2025-01-02", 0.04) == G.in_sample("X", "2025-01-02", 0.04)
    assert G.bucket(0.105) == "10-20%" and G.bucket(0.25) == "20-inf%" and G.bucket(0.04) == "3-5%"


def test_split_day_detection():
    assert G.split_day(10, 10, 5, 10)            # a 1:2 split between D-1 and D changes the raw/adjusted ratio
    assert not G.split_day(10, 10, 11, 11)


def test_entry_A_is_after_the_open_bar_closes():
    bars = [bar(0, 11, 11, 11, 11), bar(1, 10.9, 11, 10.8, 10.9)]
    e = G.entry_A(bars, OPEN)
    assert G._ts(e["t"]) == OPEN + timedelta(minutes=1) and e["o"] == 10.9


def test_entry_B_confirmation_is_causal():
    bars = [bar(0, 11, 11.2, 10.9, 11.1), bar(1, 11.1, 11.3, 11.0, 11.2), bar(2, 11.2, 11.2, 10.8, 10.9),
            bar(3, 10.85, 10.9, 10.7, 10.8)]
    e = G.entry_B(bars, OPEN)                    # bar 2 closes 10.9 < bar 1 low 11.0 -> enter bar 3's open
    assert G._ts(e["t"]) == OPEN + timedelta(minutes=3) and e["o"] == 10.85


def test_short_reference_returns_and_excursions():
    bars = [bar(1, 10, 10.5, 9.9, 10)] + [bar(1 + k, 10, 10, 9, 9) for k in range(1, 70)]
    o = G.short_outcomes(bars, bars[0], CLOSE)
    assert o["r30"] == pytest.approx(0.10)       # price fell 10 % -> short reference +10 %
    assert o["mfe_short"] == pytest.approx(0.10) and o["mae_short"] == pytest.approx(-0.05)
    assert o["t_retrace_1pct_min"] == 0.0             # the entry bar itself (after the open fill) dips 1 %


def test_describe_bootstrap_deterministic():
    xs = [0.01, -0.02, 0.03, 0.0, 0.015] * 10
    a, b = G.describe(xs, groups=list(range(50))), G.describe(xs, groups=list(range(50)))
    assert a == b and a["ci95_iid"][0] < a["mean"] < a["ci95_iid"][1]


def _rows(n, net, day="2024-06-01"):
    return [{"day": day, "gross30": net + 0.002, "net30": net} for _ in range(n)]


def test_gates():
    assert G.verdict(_rows(50, 0.01))["verdict"] == "INCONCLUSIVE_FORWARD_TEST_REQUIRED"
    assert G.verdict(_rows(300, -0.001))["verdict"] == "UNSUPPORTED"
    good = _rows(150, 0.004, "2024-06-01") + _rows(150, 0.003, "2025-09-01") + [
        {"day": "2026-02-01", "gross30": 0.1, "net30": 0.098}, {"day": "2026-02-02", "gross30": -0.2, "net30": -0.2}]
    assert G.verdict(good)["verdict"] == "PRICE_EDGE_PROMISING"
    one_half = _rows(150, 0.02, "2024-06-01") + _rows(150, -0.001, "2025-09-01")
    assert G.verdict(one_half)["verdict"] == "INCONCLUSIVE_FORWARD_TEST_REQUIRED"   # fails consistency
