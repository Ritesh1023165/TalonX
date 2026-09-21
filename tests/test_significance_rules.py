"""
tests/test_significance_rules.py
-------------------------------
Task 96E -- each scoring component family in isolation. Every rule is a
pure function; direction never matters; caps always hold.
"""
from __future__ import annotations

from datetime import timedelta

from talonx_ingest.intelligence.comparison.domain import SectionStatus
from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance import rules
from talonx_ingest.intelligence.significance.config import (
    FILING_CHANGE_CAP,
    INSIDER_CAP,
)
from talonx_ingest.intelligence.significance.rarity import RarityResult
from _significance_helpers import NOW, mk_comparison, mk_event, mk_insider_activity


def _wc(**kw):
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    return build_what_changed(mk_comparison(event=ev, **kw))


# --- event type base ------------------------------------------------------
def test_event_type_base_weights():
    c, r = rules.event_type_base(mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",)))
    assert c.points == 3
    c, _ = rules.event_type_base(mk_event(event_type=EventType.EARNINGS_RESULTS, items=("2.02",)))
    assert c.points == 2
    c, _ = rules.event_type_base(
        mk_event(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",))
    )
    assert c.points == 0


def test_item_1_05_lifts_base_to_three():
    ev = mk_event(event_type=EventType.OTHER_MATERIAL_EVENT, items=("8.01", "1.05"))
    c, r = rules.event_type_base(ev)
    assert c.points == 3
    assert any("cybersecurity" in x.description for x in r)


def test_insider_parent_event_scores_only_with_open_market_activity():
    ev = mk_event(event_type=EventType.INSIDER_TRANSACTION, form_type="4", items=())
    c0, _ = rules.event_type_base(ev, has_open_market_insider=False)
    c1, _ = rules.event_type_base(ev, has_open_market_insider=True)
    assert c0.points == 0
    assert c1.points == 1


def test_amendment_of_periodic_adds_a_point():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K/A", items=(), is_amendment=True)
    c, r = rules.event_type_base(ev)
    assert c.points == 3  # 2 base + 1 amends
    assert any(x.code == "AMENDS_PRIOR_FILING" for x in r)


# --- material items -----------------------------------------------------
def test_multi_item_needs_three_distinct_material_items():
    assert rules.material_items(mk_event(items=("2.02", "9.01")))[0].points == 0
    assert rules.material_items(mk_event(items=("5.02", "1.01", "9.01")))[0].points == 0
    c, _ = rules.material_items(mk_event(items=("5.02", "1.01", "2.03", "9.01")))
    assert c.points == 1


# --- filing change ----------------------------------------------------
def test_filing_change_decile_vs_tercile():
    c, r = rules.filing_change(_wc(rf_diff=0.70))  # > RF decile 0.6466
    assert any(x.code == "SECTION_CHANGE_DECILE" for x in r)
    assert c.points == 2
    c, r = rules.filing_change(_wc(rf_diff=0.15))  # > tercile 0.1093, < decile
    assert any(x.code == "SECTION_CHANGE_TERCILE" for x in r)
    assert c.points == 1
    c, _ = rules.filing_change(_wc(rf_diff=0.05))  # below tercile
    assert c.points == 0


def test_filing_change_ignores_not_found_section():
    c, _ = rules.filing_change(_wc(rf_diff=0.9, rf_status=SectionStatus.NOT_FOUND))
    assert c.points == 0


def test_filing_change_cap():
    wc = _wc(rf_diff=0.9, mdna_diff=0.9, liq_diff=0.9, whole_diff=0.9)
    c, r = rules.filing_change(wc)
    assert c.points == FILING_CHANGE_CAP
    assert c.raw_points > FILING_CHANGE_CAP
    assert sum(x.points for x in r) == c.points  # cap reason keeps the invariant


def test_new_material_passages_contributes():
    from talonx_ingest.intelligence.comparison.domain import (
        PassageChange,
        PassageChangeType,
    )

    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    fc = mk_comparison(event=ev, rf_diff=0.05)
    passages = tuple(
        PassageChange(
            change_type=PassageChangeType.NEW_IN_CURRENT,
            section="risk_factors",
            index=i,
            word_count=50,
            char_count=300,
            text="w " * 50,
        )
        for i in range(3)
    )
    fc = fc.model_copy(update={"new_passages": passages})
    c, r = rules.filing_change(build_what_changed(fc))
    assert any(x.code == "NEW_MATERIAL_PASSAGES" for x in r)


# --- risk language ---------------------------------------------------
def test_risk_language_threshold_and_direction_neutrality():
    assert rules.risk_language(_wc(neg_kw_delta=5))[0].points == 0     # below 15
    c, _ = rules.risk_language(_wc(neg_kw_delta=20))
    assert c.points == 1
    # a DECREASE of the same magnitude scores 0 (it is an increase rule),
    # and never a negative -- no direction is manufactured
    assert rules.risk_language(_wc(neg_kw_delta=-20))[0].points == 0


# --- xbrl magnitude -------------------------------------------------
def test_xbrl_magnitude_uses_absolute_value():
    up = rules.xbrl_magnitude(_wc(revenue_rel_delta=0.55))[0]
    down = rules.xbrl_magnitude(_wc(revenue_rel_delta=-0.55))[0]
    assert up.points == down.points == 2            # +55% and -55% score identically
    mid = rules.xbrl_magnitude(_wc(revenue_rel_delta=0.25))[0]
    assert mid.points == 1
    small = rules.xbrl_magnitude(_wc(revenue_rel_delta=0.05))[0]
    assert small.points == 0


def test_xbrl_takes_the_largest_field_not_the_sum():
    c, _ = rules.xbrl_magnitude(_wc(revenue_rel_delta=0.6, eps_rel_delta=0.9))
    assert c.points == 2  # not 4


# --- insider ------------------------------------------------------
def test_insider_large_transaction_and_cluster():
    c, _ = rules.insider_activity(mk_insider_activity(largest_value=2_000_000.0))
    assert c.points == 1
    c, r = rules.insider_activity(mk_insider_activity(largest_value=2_000_000.0, cluster=True))
    assert c.points == 3  # 1 + 2
    assert any(x.code == "INSIDER_CLUSTER" for x in r)


def test_insider_buy_and_sell_score_the_same():
    from talonx_ingest.intelligence.insider.domain import InsiderCluster

    sell = mk_insider_activity(largest_value=2_000_000.0, cluster=True)
    buy = sell.model_copy(
        update={
            "clusters": (
                InsiderCluster(
                    kind="MULTIPLE_OPEN_MARKET_BUYERS",
                    window_calendar_days=30,
                    as_of_date=sell.as_of_date,
                    distinct_owners=2,
                ),
            )
        }
    )
    assert rules.insider_activity(sell)[0].points == rules.insider_activity(buy)[0].points


def test_insider_cap():
    act = mk_insider_activity(largest_value=9_000_000.0, cluster=True)
    c, _ = rules.insider_activity(act)
    assert c.points <= INSIDER_CAP


# --- rarity -----------------------------------------------------
def test_rarity_component_maps_points():
    rare = RarityResult("RARE", 2, "d", 0, 0, NOW)
    assert rules.rarity_component(rare)[0].points == 2
    common = RarityResult("COMMON", 0, "d", 3, 5, NOW)
    assert rules.rarity_component(common)[0].points == 0
    assert rules.rarity_component(None)[0].points == 0


# --- recency ----------------------------------------------------
def test_recency_only_scores_under_two_hours():
    assert rules.recency(mk_event(age_hours=1), now=NOW)[0].points == 1
    assert rules.recency(mk_event(age_hours=10), now=NOW)[0].points == 0
    assert rules.recency(mk_event(age_hours=100), now=NOW)[0].points == 0
    assert rules.recency(mk_event(age_hours=1), now=NOW)[0].substantive is False


def test_recency_missing_timestamp():
    ev = mk_event().model_copy(update={"accepted_at_utc": None})
    assert rules.recency(ev, now=NOW)[0].points == 0


# --- watchlist ------------------------------------------------
def test_watchlist_points_and_non_substantive():
    on = rules.watchlist_priority(on_watchlist=True, pinned=False)[0]
    pin = rules.watchlist_priority(on_watchlist=True, pinned=True)[0]
    assert on.points == 1 and pin.points == 2
    assert on.substantive is False and pin.substantive is False
    assert rules.watchlist_priority(on_watchlist=False, pinned=False)[0].points == 0


# --- simultaneous --------------------------------------------
def test_simultaneous_events_threshold():
    assert rules.simultaneous_events(distinct_type_count=1, window_days=7)[0].points == 0
    assert rules.simultaneous_events(distinct_type_count=2, window_days=7)[0].points == 1


# --- quality penalty ----------------------------------------
def test_quality_penalty_accumulates_and_floors():
    ev = mk_event(quality_flags=("missing_acceptance_timestamp", "primary_document_unavailable"))
    fc = mk_comparison(event=ev, rf_diff=0.2, quality_flags=("missing_prior_filing",))
    act = mk_insider_activity(largest_value=2e6, quality_flags=("unknown_transaction_code",))
    c, r = rules.quality_penalty(
        event=ev, comparison=fc, activity=act, source_status="DOWN"
    )
    assert c.points == -2  # floor
    assert c.raw_points <= -4
    assert sum(x.points for x in r) == c.points


def test_quality_penalty_none_when_clean():
    c, r = rules.quality_penalty(event=mk_event(), comparison=None, activity=None)
    assert c.points == 0 and r == []
