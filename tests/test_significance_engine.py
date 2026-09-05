"""
tests/test_significance_engine.py
--------------------------------
Task 96E -- the deterministic composer: score, bands, structural floors,
quality caps, determinism, and the reason-sum invariant.
"""
from __future__ import annotations

import importlib
import pkgutil
from datetime import timedelta

import pytest

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.language_safety import scan_significance
from talonx_ingest.intelligence.significance.rarity import RarityResult
from _significance_helpers import NOW, mk_comparison, mk_event, mk_insider_activity


# ----------------------------------------------------------------------
# invariant: reasons sum to the score, always
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        dict(),
        dict(on_watchlist=True),
        dict(pinned=True, simultaneous_type_count=3),
        dict(source_status="DOWN"),
    ],
)
def test_reason_points_sum_to_score(kwargs):
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    sig = evaluate_significance(ev, now=NOW, **kwargs)
    assert sig.points_check()
    assert sum(c.points for c in sig.components) == sig.raw_score


# ----------------------------------------------------------------------
# banding
# ----------------------------------------------------------------------
def test_routine_event_is_low():
    ev = mk_event(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=100)
    sig = evaluate_significance(ev, now=NOW)
    assert sig.band is SignificanceBand.LOW
    assert sig.score <= 1


def test_earnings_plus_moderate_facts_is_medium_or_high():
    ev = mk_event(event_type=EventType.EARNINGS_RESULTS, items=("2.02", "9.01"), age_hours=1)
    sig = evaluate_significance(ev, now=NOW, on_watchlist=True)
    assert sig.band in (SignificanceBand.MEDIUM, SignificanceBand.HIGH)


def test_large_10q_risk_factor_change_is_high():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(), age_hours=30)
    fc = mk_comparison(event=ev, rf_diff=0.70, mdna_diff=0.20)
    sig = evaluate_significance(ev, comparison=fc, now=NOW)
    assert sig.band is SignificanceBand.HIGH


def test_bundled_material_8k_with_debt_reaches_high_or_critical():
    ev = mk_event(
        event_type=EventType.MATERIAL_AGREEMENT,
        items=("1.01", "2.03", "2.05", "9.01"),
        age_hours=1,
    )
    sig = evaluate_significance(
        ev,
        now=NOW,
        rarity_result=RarityResult("RARE", 2, "rare for filer", 0, 0, NOW),
        simultaneous_type_count=2,
    )
    assert sig.band in (SignificanceBand.HIGH, SignificanceBand.CRITICAL)


# ----------------------------------------------------------------------
# CRITICAL / HIGH structural floors  (CRITICAL_BAND_POLICY.md)
# ----------------------------------------------------------------------
def test_critical_needs_substantive_structure_not_just_boosts():
    # score can reach 7 from base(3) + recency(1) + pinned(2) + simultaneous(1)
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",), age_hours=1)
    sig = evaluate_significance(ev, now=NOW, pinned=True, simultaneous_type_count=2)
    assert sig.raw_score >= 7
    assert sig.band is SignificanceBand.HIGH  # held down: only 4 substantive pts / 2 families
    assert any("CRITICAL held to HIGH" in c for c in sig.band_caps_applied)


def test_genuine_critical_passes_the_floor():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(), age_hours=1)
    fc = mk_comparison(
        event=ev, rf_diff=0.70, mdna_diff=0.30, whole_diff=0.30, revenue_rel_delta=-0.6
    )
    sig = evaluate_significance(
        ev,
        comparison=fc,
        now=NOW,
        rarity_result=RarityResult("UNCOMMON", 1, "d", 0, 1, NOW),
        simultaneous_type_count=2,
    )
    assert sig.score >= 7
    assert sig.substantive_points >= 5 and sig.substantive_families >= 2
    assert sig.band is SignificanceBand.CRITICAL


def test_watchlist_only_cannot_exceed_low():
    ev = mk_event(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=1)
    sig = evaluate_significance(ev, now=NOW, pinned=True)  # 0 + 1 recency + 2 pinned = 3
    assert sig.substantive_points == 0
    assert sig.band is SignificanceBand.LOW
    assert any("no substantive evidence" in c for c in sig.band_caps_applied)


# ----------------------------------------------------------------------
# data-quality
# ----------------------------------------------------------------------
def test_missing_acceptance_timestamp_caps_band_at_medium():
    ev = mk_event(
        event_type=EventType.ANNUAL_FILING,
        form_type="10-K",
        items=(),
        quality_flags=("missing_acceptance_timestamp",),
    )
    fc = mk_comparison(event=ev, rf_diff=0.70, mdna_diff=0.30, whole_diff=0.4)
    sig = evaluate_significance(ev, comparison=fc, now=NOW)
    assert sig.band in (SignificanceBand.LOW, SignificanceBand.MEDIUM)
    assert any("MEDIUM" in c for c in sig.band_caps_applied)


def test_incomplete_comparison_docks_a_point():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    clean = evaluate_significance(ev, comparison=mk_comparison(event=ev, rf_diff=0.7), now=NOW)
    dq = evaluate_significance(
        ev,
        comparison=mk_comparison(event=ev, rf_diff=0.7, quality_flags=("ambiguous_section",)),
        now=NOW,
    )
    assert dq.score == clean.score - 1
    assert "ambiguous_section" in dq.data_quality_flags


def test_stale_source_penalty():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    base = evaluate_significance(ev, now=NOW)
    stale = evaluate_significance(ev, now=NOW, source_status="STALE")
    assert stale.score == base.score - 1
    assert "source_stale" in stale.data_quality_flags


# ----------------------------------------------------------------------
# determinism
# ----------------------------------------------------------------------
def test_same_inputs_same_output():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    fc = mk_comparison(event=ev, rf_diff=0.5)
    a = evaluate_significance(ev, comparison=fc, on_watchlist=True, now=NOW)
    b = evaluate_significance(ev, comparison=fc, on_watchlist=True, now=NOW)
    assert a.model_dump() == b.model_dump()


def test_direction_neutral_xbrl_and_exec_change():
    ev_up = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    up = evaluate_significance(
        ev_up, comparison=mk_comparison(event=ev_up, revenue_rel_delta=0.6), now=NOW
    )
    down = evaluate_significance(
        ev_up, comparison=mk_comparison(event=ev_up, revenue_rel_delta=-0.6), now=NOW
    )
    assert up.score == down.score


def test_output_is_language_safe():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    fc = mk_comparison(
        event=ev, rf_diff=0.7, mdna_diff=0.3, whole_diff=0.4, revenue_rel_delta=-0.6,
        neg_kw_delta=20,
    )
    sig = evaluate_significance(ev, comparison=fc, pinned=True, now=NOW)
    assert scan_significance(sig) == []


# ----------------------------------------------------------------------
# Phase 24 -- no forward-return / P&L module reachable from the package
# ----------------------------------------------------------------------
_FORBIDDEN_IMPORT_ROOTS = (
    "talonx_quant",
    "talonx_core.decision",
    "talonx_paper",
    "talonx_piv",
    "talonx_ingest.backtest",
)


def _imported_modules(path: str) -> set[str]:
    import ast

    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_significance_package_imports_nothing_return_related():
    import talonx_ingest.intelligence.significance as pkg

    seen: set[str] = set()
    for m in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        mod = importlib.import_module(m.name)
        for imported in _imported_modules(mod.__file__):
            for bad in _FORBIDDEN_IMPORT_ROOTS:
                assert not imported.startswith(bad), f"{m.name} imports {imported!r}"
        seen.add(m.name)
    assert seen  # walked something
