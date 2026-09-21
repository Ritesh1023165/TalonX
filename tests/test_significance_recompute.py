"""
tests/test_significance_recompute.py
-----------------------------------
Task 96E -- the deterministic invalidation policy.
"""
from __future__ import annotations

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.recompute import needs_recompute
from _significance_helpers import NOW, mk_comparison, mk_event


def test_recompute_when_nothing_stored():
    d = needs_recompute(None, new_fingerprint="x")
    assert d.needed and "no stored" in d.reason


def test_no_recompute_when_unchanged():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    sig = evaluate_significance(ev, now=NOW)
    d = needs_recompute(sig, new_fingerprint=sig.input_fingerprint)
    assert not d.needed


def test_recompute_on_ruleset_change():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    sig = evaluate_significance(ev, now=NOW, ruleset_version="information-significance-v1")
    d = needs_recompute(
        sig, new_fingerprint=sig.input_fingerprint, ruleset_version="information-significance-v2"
    )
    assert d.needed and "ruleset changed" in d.reason


def test_recompute_when_comparison_arrives():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    before = evaluate_significance(ev, now=NOW)
    after = evaluate_significance(ev, comparison=mk_comparison(event=ev, rf_diff=0.7), now=NOW)
    d = needs_recompute(before, new_fingerprint=after.input_fingerprint)
    assert d.needed and "fingerprint mismatch" in d.reason


def test_recompute_when_watchlist_state_changes():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    before = evaluate_significance(ev, now=NOW)
    after = evaluate_significance(ev, now=NOW, pinned=True)
    assert needs_recompute(before, new_fingerprint=after.input_fingerprint).needed


def test_time_passing_alone_does_not_force_recompute():
    from datetime import timedelta

    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",), age_hours=1)
    early = evaluate_significance(ev, now=NOW)
    later = evaluate_significance(ev, now=NOW + timedelta(hours=10))
    # recency contribution differs...
    assert early.score != later.score
    # ...but the fingerprint (substantive inputs) does not
    assert not needs_recompute(early, new_fingerprint=later.input_fingerprint).needed
