"""RS_ALPHA_V1 pre-registration: frozen spec / mapping hashes, causality, RS math, gates and Phase B selection."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import rs_study as R

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
OPEN = datetime(2026, 9, 28, 13, 30, tzinfo=UTC)


def bars(start: datetime, closes: list[float], vol: float = 100.0) -> list[dict]:
    return [{"t": (start + timedelta(minutes=i)).isoformat(), "c": c, "o": c, "v": vol} for i, c in enumerate(closes)]


# ---------------------------------------------------------------------------------------------------- frozen identity
def test_spec_and_mapping_hashes_are_frozen():
    assert R.HYPOTHESIS_VERSION == "RS_ALPHA_V1"
    assert R.SECTOR_MAPPING_VERSION == "SIC_ETF_MAP_V1"
    assert R.mapping_hash() == "5c861b56a91c8858"
    assert R.spec_fingerprint() == "711e5b0c5ee04277"
    assert R.cost_model_hash() == "3e57efbe3f2a203d"


def test_mapping_artifact_on_disk_matches_code():
    p = REPO / "docs" / "research" / "preregistration" / "rs_sector_mapping_v1.json"
    art = json.loads(p.read_text(encoding="utf-8"))
    assert art["mapping"] == R.mapping_artifact()
    assert art["mapping_hash"] == R.mapping_hash()


def test_hypothesis_text_frozen_and_no_mechanism_claim():
    assert R.HYPOTHESIS.startswith("Stocks exhibiting causal idiosyncratic outperformance")
    assert "institutional" not in R.HYPOTHESIS.lower()


# ---------------------------------------------------------------------------------------------------- SIC mapping
@pytest.mark.parametrize("sic,etf", [(1311, "XLE"), (2911, "XLE"), (2834, "XBI"), (2836, "XBI"), (2837, "SPY"),
                                     (3841, "XLV"), (3851, "XLV"), (3572, "XLK"), (7372, "XLK"), (6022, "XLF"),
                                     (6798, "XLF"), (3674, "XLI"), (3711, "XLI"), (5812, "SPY"), (4911, "SPY")])
def test_sic_mapping_deterministic(sic, etf):
    assert R.sector_benchmark(sic) == etf
    assert R.sector_benchmark(str(sic)) == etf              # same answer every time, any representation


@pytest.mark.parametrize("sic", [None, "", "abc", 0, 9999])
def test_unmapped_goes_to_spy(sic):
    assert R.sector_benchmark(sic) == "SPY"


def test_ranges_do_not_overlap():
    rs = sorted(R.SECTOR_MAP)
    for (a0, a1, _), (b0, b1, _) in zip(rs, rs[1:]):
        assert a1 < b0


# ---------------------------------------------------------------------------------------------------- observations
def test_one_primary_observation_per_symbol_session():
    ev = [{"symbol": "AAA", "session": "2026-09-28", "t0": "2026-09-28T15:00:00+00:00", "seq": 9},
          {"symbol": "AAA", "session": "2026-09-28", "t0": "2026-09-28T14:10:00+00:00", "seq": 5},
          {"symbol": "AAA", "session": "2026-09-28", "t0": "2026-09-28T14:10:00+00:00", "seq": 4},
          {"symbol": "AAA", "session": "2026-09-29", "t0": "2026-09-29T14:30:00+00:00", "seq": 1},
          {"symbol": "BBB", "session": "2026-09-28", "t0": "2026-09-28T16:00:00+00:00", "seq": 2}]
    p = R.primary_observations(ev)
    assert len(p) == 3
    a = [x for x in p if x["symbol"] == "AAA" and x["session"] == "2026-09-28"]
    assert len(a) == 1 and a[0]["seq"] == 4


def test_d1_core_membership_and_dtu_state():
    rows = [{"symbol": f"S{i}", "adv20_usd": 1e9 - i, "v1_floor_eligible": 1} for i in range(5)]
    rows.append({"symbol": "BIG_BUT_INELIGIBLE", "adv20_usd": 1e12, "v1_floor_eligible": 0})
    core = R.core_membership(rows, n=3)
    assert core == {"S0", "S1", "S2"}
    prom = {"S4": [("2026-09-28T14:05:00+00:00", None, "GAP_TRIGGER")]}
    assert R.dtu_state_at("S0", "2026-09-28T14:00:00+00:00", core, prom) == "ACTIVE_CORE"
    assert R.dtu_state_at("S4", "2026-09-28T14:00:00+00:00", core, prom) == "OUT_OF_DTU"      # promoted later
    assert R.dtu_state_at("S4", "2026-09-28T14:05:00+00:00", core, prom) == "EVENT_PROMOTED:GAP_TRIGGER"
    prom2 = {"S3": [("2026-09-28T10:00:00+00:00", "2026-09-28T12:00:00+00:00", "SEC_8K")]}
    assert R.dtu_state_at("S3", "2026-09-28T14:00:00+00:00", core, prom2) == "OUT_OF_DTU"     # expired


def test_core_index_uses_only_given_d1_members_and_no_forward_fill():
    start = OPEN
    core = {"A": bars(start, [10.0] * 31), "B": bars(start, [20.0] * 15 + [22.0] * 16)}
    r, cov = R.core_index_return(core, start + timedelta(minutes=15), start + timedelta(minutes=30))
    assert cov == 1.0 and r == pytest.approx((0.0 + 0.1) / 2)
    # a constituent with a gap longer than the stale limit at the endpoint is dropped, not filled
    core["C"] = bars(start, [5.0] * 10)                    # no bars after 13:40
    r2, cov2 = R.core_index_return(core, start + timedelta(minutes=15), start + timedelta(minutes=30))
    assert cov2 == pytest.approx(2 / 3) and r2 == pytest.approx(r)


# ---------------------------------------------------------------------------------------------------- causality
def test_price_closed_by_never_uses_an_unclosed_or_future_bar():
    b = bars(OPEN, [1, 2, 3, 4])                          # bars start 13:30..13:33
    p, end = R.price_closed_by(b, OPEN + timedelta(minutes=2))
    assert p == 2 and end == OPEN + timedelta(minutes=2)  # the 13:32 bar is not closed at 13:32
    p, end = R.price_closed_by(b, OPEN + timedelta(minutes=2, seconds=59))
    assert p == 2
    assert R.price_closed_by(b, OPEN) == (None, None)


def test_stale_price_is_missing_not_filled():
    b = bars(OPEN, [1, 2])
    assert R.price_closed_by(b, OPEN + timedelta(minutes=2 + R.STALE_MAX_MIN))[0] == 2
    assert R.price_closed_by(b, OPEN + timedelta(minutes=3 + R.STALE_MAX_MIN)) == (None, None)


def test_aligned_timestamps_and_no_future_benchmark_bar():
    # stock's last bar closes at 14:00 - 3 min (illiquid); benchmark trades every minute incl. a jump at 13:59
    stock = bars(OPEN, [10.0] * 16) + bars(OPEN + timedelta(minutes=16), [11.0] * 11)   # last bar starts 13:56
    spy = bars(OPEN, [100.0] * 29) + [{"t": (OPEN + timedelta(minutes=29)).isoformat(), "c": 200.0, "v": 1}]
    al = R.aligned_return(stock, {"SPY": spy}, T0, 15, OPEN)
    assert al["e_star"] == OPEN + timedelta(minutes=27)                                 # stock endpoint 13:57
    assert al["bench"]["SPY"] == pytest.approx(0.0)       # the 13:59 benchmark jump is newer than the stock bar
    assert al["stock"] == pytest.approx(0.1)


def test_no_future_stock_bar():
    stock = bars(OPEN, [10.0] * 30) + bars(OPEN + timedelta(minutes=30), [50.0] * 5)    # future bars after 14:00
    al = R.aligned_return(stock, {}, T0, 15, OPEN)
    assert al["stock"] == pytest.approx(0.0)


def test_lookback_may_not_leave_the_regular_session():
    stock = bars(OPEN - timedelta(minutes=30), [10.0] * 60)
    assert R.aligned_return(stock, {}, OPEN + timedelta(minutes=10), 15, OPEN) is None
    assert R.aligned_return(stock, {}, OPEN + timedelta(minutes=15), 15, OPEN) is not None


# ---------------------------------------------------------------------------------------------------- RS math
def test_rs_math():
    al = {"stock": 0.03, "bench": {"XLK": 0.01, "SPY": -0.005, "QQQ": 0.002, "DTU_CORE_EW": 0.004}}
    f = R.rs_features(al, "XLK")
    assert f["sector_excess"] == pytest.approx(0.02)
    assert f["market_excess"] == pytest.approx(0.035)
    assert f["qqq_excess"] == pytest.approx(0.028)
    assert f["core_excess"] == pytest.approx(0.026)
    assert f["rs_ratio"] == pytest.approx(1.03 / 1.01)
    assert R.rs_features({"stock": 0.01, "bench": {}}, "XLK")["sector_excess"] is None


def test_rvol_15m_uses_only_closed_bars_in_window():
    b = bars(OPEN, [1.0] * 40, vol=1000.0)
    r = R.rvol_15m(b, OPEN + timedelta(minutes=30), adv20_sh=390_000)     # 15 bars x 1000 / (390000 * 15/390)
    assert r == pytest.approx(15_000 / 15_000)
    assert R.rvol_15m(b, OPEN + timedelta(minutes=30), None) is None


# ---------------------------------------------------------------------------------------------------- quintiles
def test_quintile_assignment_equal_count_and_ordered():
    obs = [{"symbol": f"S{i:03d}", "session": "d", "sector_excess": i / 1000} for i in range(100)]
    q = R.assign_quintiles(obs)
    assert [len(q[k]) for k in range(1, 6)] == [20] * 5
    assert max(o["sector_excess"] for o in q[1]) < min(o["sector_excess"] for o in q[5])
    assert sum(len(v) for v in R.assign_quintiles(obs + [{"symbol": "X", "session": "d", "sector_excess": None}]).values()) == 100


def test_gradient_gate_does_not_require_literal_monotonicity():
    qs = {1: {"n": 50, "gross_mean": -0.002, "net_mean": -0.004}, 2: {"n": 50, "gross_mean": 0.001, "net_mean": -.001},
          3: {"n": 50, "gross_mean": 0.000, "net_mean": -0.002}, 4: {"n": 50, "gross_mean": 0.004, "net_mean": .002},
          5: {"n": 50, "gross_mean": 0.006, "net_mean": 0.003}}
    g = R.gradient_gate(qs)
    assert g["pass"] and g["spearman"] > 0 and g["q5_minus_q1_gross"] == pytest.approx(0.008)
    qs[5]["net_mean"] = -0.0001
    assert not R.gradient_gate(qs)["pass"]                # Q5 must be net-positive


# ---------------------------------------------------------------------------------------------------- metrics / gates
def test_cost_model_consistency_with_the_forensic_contract():
    from talonx_paperperf import signal_forensics as F
    from talonx_v2.config import V2Config
    assert R.COST_MODEL["friction_bps"] == F.V2_FRICTION_BPS == V2Config().friction_bps == 20.0
    assert tuple(R.COST_MODEL["quote_windows_s"]) == F.QUOTE_WINDOWS_S
    assert R.cost_frac(None) == pytest.approx(0.002)
    assert R.cost_frac(12.0) == pytest.approx(0.002)
    assert R.cost_frac(55.0) == pytest.approx(0.0055)


def test_top3_removal_and_concentration():
    tr = [(0.10, 0.098), (0.02, 0.018), (0.01, 0.008)] + [(0.001, -0.001)] * 7
    m = R.metrics(tr)
    assert m["n"] == 10
    assert m["top1_share_of_gross"] == pytest.approx(0.10 / 0.137)
    assert m["top3_removed_net_mean"] == pytest.approx(-0.001)
    g = R.minimum_gate(m, True)
    assert not g["conditions"]["top1_le_20pct"] and not g["conditions"]["positive_after_top3_removed"]


def _m(n=60, gross=0.005, net=0.003, pf=1.4, top1=0.05, top3=0.12, rest=0.002):
    return {"n": n, "gross_mean": gross, "net_mean": net, "profit_factor": pf, "top1_share_of_gross": top1,
            "top3_share_of_gross": top3, "top3_removed_net_mean": rest}


def test_variant_definitions_frozen():
    ids = [v["id"] for v in R.VARIANTS]
    assert ids == ["RS-1", "RS-2", "RS-3", "RS-4", "RS-5", "RS-6"]
    rules = {v["id"]: v["rule"] for v in R.VARIANTS}
    assert rules["RS-1"] == [("market_excess", ">=", 0.015)]
    assert rules["RS-2"] == [("sector_excess", ">=", 0.015)]
    assert rules["RS-3"] == [("stock_ret", ">=", 0.020), ("spy_ret", "<=", 0.0)]
    assert rules["RS-4"] == [("sector_excess", ">=", 0.015), ("rvol_15m", ">=", 2.0)]
    assert rules["RS-5"] == [("sector_excess", ">=", 0.015), ("spread_to_price", "<=", 0.010)]
    assert rules["RS-6"] == [("sector_excess", "<=", -0.020)]
    assert R.variant_pass(R.VARIANTS[3], {"sector_excess": 0.02, "rvol_15m": None}) is False   # missing never passes
    assert R.variant_pass(R.VARIANTS[2], {"stock_ret": 0.02, "spy_ret": 0.0}) is True


def test_rs6_cannot_promote():
    rs6 = R.VARIANTS[5]
    assert R.classify_variant(rs6, _m(gross=0.02, net=0.015), True) == "DIAGNOSTIC_ONLY"
    res = [{"variant": rs6, "metrics": _m(gross=0.02, net=0.015), "status": "PASSES_STRONG_GATE"}]
    assert R.select_phase_b(res)[0] is None


def test_no_phase_b_candidate_if_gradient_gate_fails():
    v = R.VARIANTS[1]
    st = R.classify_variant(v, _m(gross=0.01, net=0.008), gradient_pass=False)
    assert st == "FAILS_MINIMUM"
    assert R.select_phase_b([{"variant": v, "metrics": _m(), "status": st}])[0] is None


def test_035_requirement():
    v = R.VARIANTS[1]
    assert R.classify_variant(v, _m(gross=0.0034, net=0.001), True) == "INTERESTING_BUT_INSUFFICIENT"
    assert R.classify_variant(v, _m(gross=0.0035, net=0.001), True) == "PASSES_STRONG_GATE"
    assert R.verdict(500, 0.99, True, {"RS-2": "INTERESTING_BUT_INSUFFICIENT"}, None) == "INCONCLUSIVE"
    assert R.verdict(500, 0.99, False, {"RS-2": "FAILS_MINIMUM"}, None) == "UNSUPPORTED"
    assert R.verdict(100, 0.99, True, {}, None) == "INCONCLUSIVE"


def test_deterministic_selection_of_at_most_one():
    V = {v["id"]: v for v in R.VARIANTS}
    res = [{"variant": V["RS-1"], "metrics": _m(net=0.004, n=50), "status": "PASSES_STRONG_GATE"},
           {"variant": V["RS-2"], "metrics": _m(net=0.004, n=80), "status": "PASSES_STRONG_GATE"},
           {"variant": V["RS-4"], "metrics": _m(net=0.003, n=200), "status": "PASSES_STRONG_GATE"}]
    assert R.select_phase_b(res)[0] == "RS-2"                           # tie on net -> larger N
    res[0]["metrics"] = _m(net=0.004, n=80, top3=0.05)
    assert R.select_phase_b(res)[0] == "RS-1"                           # tie on N -> lower top-3 concentration
    res[0]["metrics"] = _m(net=0.004, n=80, top3=0.12)
    res[1]["variant"] = V["RS-5"]                                       # tie on all -> simpler (complexity 1 < 2)
    assert R.select_phase_b(res)[0] == "RS-1"
    assert R.select_phase_b(list(reversed(res)))[0] == "RS-1"           # order-independent


def test_incremental_to_score_flags_redundant():
    import random
    rnd = random.Random(7)
    obs = []
    for i in range(400):
        sc = rnd.uniform(40, 90)
        rs = rnd.gauss(0, 0.01)
        obs.append({"score": sc, "sector_excess": rs, "gross30": 0.0001 * (sc - 60) + rnd.gauss(0, 0.004)})
    out = R.incremental_to_score(obs)
    assert out["answer"] in ("NO", "INCONCLUSIVE") and out["usable_bands"] >= 2
    for o in obs:
        o["gross30"] += 0.5 * o["sector_excess"]
    assert R.incremental_to_score(obs)["answer"] == "YES"
