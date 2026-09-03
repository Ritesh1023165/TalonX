"""
tests/test_significance_identity.py
----------------------------------
Task 96E -- deterministic id + input fingerprint (excludes wall-clock now).
"""
from __future__ import annotations

from datetime import timedelta

from talonx_ingest.intelligence.significance.identity import (
    input_fingerprint,
    significance_id,
)
from _significance_helpers import NOW, mk_comparison, mk_event, mk_insider_activity


def test_significance_id_shape_and_ruleset():
    assert (
        significance_id("SEC:0000320193-26-000101:EARNINGS_RESULTS")
        == "SIG:SEC:0000320193-26-000101:EARNINGS_RESULTS:information-significance-v1"
    )
    assert significance_id("e", ruleset_version="v9") == "SIG:e:v9"


def test_fingerprint_is_deterministic_for_same_inputs():
    ev = mk_event()
    a = input_fingerprint(event=ev)
    b = input_fingerprint(event=ev)
    assert a == b and len(a) == 64


def test_fingerprint_excludes_now_but_includes_substantive_inputs():
    ev1 = mk_event(age_hours=1)
    ev2 = mk_event(age_hours=40)  # different age -> different recency, SAME accepted-at? no
    # same accepted_at_utc -> same fingerprint (recency is derived from now, not stored here)
    ev_same = mk_event(accepted_at=ev1.accepted_at_utc)
    assert input_fingerprint(event=ev1) == input_fingerprint(event=ev_same)
    # a genuinely different acceptance instant DOES change it
    assert input_fingerprint(event=ev1) != input_fingerprint(event=ev2)


def test_fingerprint_changes_on_watchlist_and_pin():
    ev = mk_event()
    base = input_fingerprint(event=ev)
    assert input_fingerprint(event=ev, on_watchlist=True) != base
    assert input_fingerprint(event=ev, pinned=True) != input_fingerprint(
        event=ev, on_watchlist=True
    )


def test_fingerprint_changes_when_comparison_or_insider_arrives():
    ev = mk_event(event_type=mk_event().event_type)
    base = input_fingerprint(event=ev)
    fc = mk_comparison(event=ev, rf_diff=0.5)
    assert input_fingerprint(event=ev, comparison=fc) != base
    act = mk_insider_activity(largest_value=2_000_000.0)
    assert input_fingerprint(event=ev, insider_activity=act) != base


def test_fingerprint_changes_on_context_and_ruleset():
    ev = mk_event()
    base = input_fingerprint(event=ev)
    assert input_fingerprint(event=ev, simultaneous_types=3) != base
    assert input_fingerprint(event=ev, rarity_code="RARE") != base
    assert input_fingerprint(event=ev, source_status="DOWN") != base
    assert input_fingerprint(event=ev, ruleset_version="other") != base
