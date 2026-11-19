"""Dynamic Tradable Universe study code (research, read-only): classification floors, ranking, threshold grid, event
promotion + TTL, Core/Event union without double counting, operator precedence, miss reporting, determinism."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
P = REPO / "docs" / "research" / "evidence" / "2026-09-29_dynamic_tradable_universe" / "tools" / "dtu_study.py"
spec = importlib.util.spec_from_file_location("dtu_study", P)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def F(sym, price=10.0, adv=5e6, cov=0.99, spread=10.0, structural="ELIGIBLE"):
    return {"symbol": sym, "structural": structural, "price": price, "adv20_usd": adv, "rth_coverage_d1": cov,
            "spread_bps": spread}


FEATS = {"A": F("A", adv=9e7), "B": F("B", adv=5e7), "C": F("C", adv=2e7, price=2.5), "D": F("D", adv=8e5),
         "E": F("E", adv=3e6, cov=0.85, spread=250.0), "X": F("X", adv=9e9, structural="WARRANT"),
         "Z": F("Z", price=0.5, adv=4e6)}


def test_floors_and_structural_exclusion():
    assert D.passes(FEATS["A"]) and not D.passes(FEATS["X"])            # structurally excluded never passes
    assert not D.passes(FEATS["Z"]) and not D.passes(FEATS["D"])        # V1 floors: price >= 1, ADV >= 1M
    assert D.passes(FEATS["C"]) and not D.passes(FEATS["C"], price=3)
    assert not D.passes(FEATS["E"], cov=0.9) and D.passes(FEATS["E"], cov=0.8)
    assert not D.passes(FEATS["E"], spread=200) and D.passes(FEATS["E"])
    assert not D.passes({**FEATS["A"], "spread_bps": None}, spread=100)  # unmeasured spread never passes a spread cap


def test_core_ranking_is_adv_descending_deterministic_and_capped():
    assert D.core(FEATS, 2) == {"A", "B"}
    assert D.core(FEATS, None) == {"A", "B", "C", "E"}
    assert D.core(FEATS, 3, price=3) == {"A", "B", "E"}
    tie = {"Q": F("Q", adv=1e7), "P": F("P", adv=1e7)}
    assert D.core(tie, 1) == {"P"}                                     # ties broken by symbol


class _W:
    def __init__(self, session):
        from talonx_opportunity.phases import trading_window
        self.w = trading_window(date.fromisoformat(session))

    def __getitem__(self, k):
        return self.w if k == "w" else None


def test_filing_promotion_ttl_and_d1_vs_realtime():
    W = {"w": _W("2026-09-28").w}
    fev = {"F4": [("2026-09-16", "FORM4", "a1"), ("2026-09-22", "FORM4", "a2")],       # cluster within 10 sessions
           "F4OLD": [("2026-09-10", "FORM4", "b1"), ("2026-09-11", "FORM4", "b2")],     # > 10 sessions before 09-28
           "ONE4": [("2026-09-24", "FORM4", "c1")],                                     # single filing: no cluster
           "K8": [("2026-09-24", "FILING_8K", "d1")],                                   # 09-24 = 2 sessions before
           "K8TODAY": [("2026-09-28", "FILING_8K", "e1")]}                              # same session
    d1 = D.promoted_by_filings(W, fev, ttl_8k=3)
    assert d1 == {"F4": "FORM4_CLUSTER", "K8": "FILING_8K"}
    assert "K8" not in D.promoted_by_filings(W, fev, ttl_8k=2)                          # TTL 2: 09-24 expired
    rt = D.promoted_by_filings(W, fev, ttl_8k=3, realtime=True)
    assert rt["K8TODAY"] == "FILING_8K" and "K8TODAY" not in d1                        # realtime needs a live feed


def test_operator_precedence_and_event_timing():
    kw = dict(core_set={"A"}, added={"V2"}, excluded={"A", "BAD"}, prom_filing={"F": "FILING_8K"},
              gap_times={"G": [("2026-09-28T14:00:00+00:00", 6.0)]}, gap_g=5.0)
    assert D.status_at("A", "2026-09-28T15:00:00+00:00", **kw)[0] == "OPERATOR_EXCLUDED"   # exclusion beats core
    assert D.status_at("V2", "2026-09-28T15:00:00+00:00", **kw)[0] == "OPERATOR_ADDED"
    assert D.status_at("F", "2026-09-28T15:00:00+00:00", **kw) == ("EVENT_RECOVERED", "FILING_8K")
    assert D.status_at("G", "2026-09-28T13:55:00+00:00", **kw)[0] == "MISSED"              # before the trigger
    assert D.status_at("G", "2026-09-28T14:00:00+00:00", **kw)[0] == "EVENT_RECOVERED_1_SCAN_LATE"
    assert D.status_at("G", "2026-09-28T14:05:00+00:00", **kw)[0] == "EVENT_RECOVERED"
    assert D.status_at("N", "2026-09-28T14:05:00+00:00", **kw) == ("MISSED", None)
    prot = {"P": [("2026-09-28T10:00:00+00:00", "2026-09-28T15:00:00+00:00")]}          # identity open 10:00-15:00Z
    kw2 = {**kw, "protected": prot}
    assert D.status_at("P", "2026-09-28T15:00:00+00:00", **kw2)[0] == "PROTECTED_ACTIVE_IDENTITY"   # its invalidation
    assert D.status_at("P", "2026-09-28T16:00:00+00:00", **kw2)[0] == "MISSED"                      # closed after
    assert D.status_at("P", "2026-09-28T10:00:00+00:00", **kw2)[0] == "MISSED"          # creation itself not protected


def test_gap_trigger_uses_the_first_qualifying_observation():
    g = [("t1", 2.5), ("t2", 4.0), ("t3", 7.0)]
    assert (D.gap_trigger_time(g, 3), D.gap_trigger_time(g, 5), D.gap_trigger_time(g, 10)) == ("t2", "t3", None)


def test_threshold_grid_is_monotone():
    base = list(FEATS.values())
    n = lambda **k: sum(1 for f in base if D.passes(f, **k))  # noqa: E731
    assert n(price=1) >= n(price=2) >= n(price=3) >= n(price=5)
    assert n(adv=5e5) >= n(adv=1e6) >= n(adv=2e6) >= n(adv=5e6) >= n(adv=1e7)
    assert n(cov=0.8) >= n(cov=0.9) >= n(cov=0.95) >= n(cov=0.98)


def test_study_tool_never_opens_production_stores_writable():
    src = P.read_text(encoding="utf-8")
    assert "mode=ro" in src and ".commit(" not in src and "INSERT" not in src and "UPDATE " not in src
    assert "OPERATOR_UNIVERSE_MUTATION_MODE" not in src                        # never touches the control plane
