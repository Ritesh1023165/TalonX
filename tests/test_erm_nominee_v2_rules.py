"""Fixtures for the ERM nominee correction rules V2 (research/erm_nominee_audit/v2_rules.py). SYNTHETIC data only; no
archive, no returns, no outcomes. Separate from any profitability scoring."""
from datetime import date, timedelta

from research.erm_nominee_audit import v2_rules as R

D0 = date(2021, 6, 15)


def days(start, n):
    return [start + timedelta(days=k) for k in range(n)]


def traded(start, n, v=1000):
    return {d: v for d in days(start, n)}


# 1 reused ticker vs genuine rename continuity ---------------------------------------------------------------------------
def test_genuine_rename_relabelled_history_resolves_to_predecessor_ticker():
    edges = [("OLDCO", "NEWCO", date(2022, 3, 1))]                      # rename AFTER the event
    f345 = {"OLDCO": [(date(2021, 5, 1), "0000000001")]}
    r = R.identity_at("NEWCO", D0, edges, f345, traded(date(2021, 1, 1), 200))
    assert r["ticker_at_D"] == "OLDCO" and r["issuer"] == "0000000001"
    assert r["identity"] == "VERIFIED_HISTORICAL_IDENTITY" and r["reason"] == "DATED_F345+RENAME_RECORDS"


def test_relabel_walk_does_not_chain_through_a_later_ticker_reuse():
    # ACIC -> ACHR (2021-09-17, Atlas Crest); later UIHC -> ACIC (2023-08-15) is ANOTHER company reusing ACIC
    edges = [("ACIC", "ACHR", date(2021, 9, 17)), ("UIHC", "ACIC", date(2023, 8, 15))]
    t, chain, prob = R.ticker_at("ACHR", date(2021, 2, 10), edges)
    assert t == "ACIC" and prob is None and len(chain) == 1


def test_reused_ticker_after_rename_away_is_not_continuity():
    edges = [("XYZ", "ABC", date(2020, 1, 10))]                          # original XYZ renamed away BEFORE the event
    f345 = {"XYZ": [(date(2019, 6, 1), "0000000001"), (date(2021, 6, 1), "0000000002")]}  # new issuer reuses XYZ
    r = R.identity_at("XYZ", D0, edges, f345, traded(date(2021, 1, 1), 200))
    assert r["issuer"] == "0000000002"                                   # the issuer reporting XYZ at D, not the old one
    assert R.mapping_class(r, "0000000001") == "VERIFIED_DIFFERENT_SECURITY"


def test_reuse_detected_by_trading_break_is_unresolved_not_bad():
    vol = {**traded(date(2021, 1, 1), 60), **{d: 0 for d in days(date(2021, 3, 2), 30)}, **traded(date(2021, 4, 1), 90)}
    f345 = {"T": [(date(2021, 1, 15), "0000000001")]}
    r = R.identity_at("T", D0, [], f345, vol)
    assert r["identity"] == "UNRESOLVED_IDENTITY" and r["reason"] == "CONTRADICTORY:TRADING_BREAK_AFTER_EVIDENCE"


def test_absent_evidence_is_unresolved_absent():
    r = R.identity_at("T", D0, [], {}, traded(date(2021, 1, 1), 200))
    assert r["identity"] == "UNRESOLVED_IDENTITY" and r["reason"].startswith("ABSENT")


# 2/3 share classes; identical volumes but different prices --------------------------------------------------------------
def _series(prices, vols):
    ds = days(date(2021, 5, 1), len(prices))
    return {"vol": dict(zip(ds, vols)), "open": dict(zip(ds, prices)), "close": dict(zip(ds, prices)),
            "window": ds, "key": ds[-3:]}


def test_identical_volumes_but_different_prices_are_not_duplicates():
    a, b = _series([10.0] * 25, [500] * 25), _series([12.0] * 25, [500] * 25)
    assert R.same_series(a, b) == "DIFFERENT_PRICES"
    assert R.duplicate_link("DIFFERENT_PRICES", {}, {}) == "NOT_DUPLICATE"


def test_share_classes_of_one_issuer_are_never_merged_by_issuer():
    a, b = _series([10.0] * 25, [500] * 25), _series([10.4] * 25, [300] * 25)
    assert R.same_series(a, b) == "NOT_CANDIDATE"
    ia = {"identity": "VERIFIED_HISTORICAL_IDENTITY", "ticker_at_D": "BRK.A", "issuer": "1"}
    ib = {"identity": "VERIFIED_HISTORICAL_IDENTITY", "ticker_at_D": "BRK.B", "issuer": "1"}
    assert R.duplicate_link("SAME_DATA", ia, ib) == "UNRESOLVED_DUPLICATE"     # same data needs same ticker on D


def test_same_data_same_ticker_same_issuer_is_verified_duplicate():
    a = _series([10.0] * 25, [500] * 25)
    assert R.same_series(a, dict(a)) == "SAME_DATA"
    i = {"identity": "VERIFIED_HISTORICAL_IDENTITY", "ticker_at_D": "OLDCO", "issuer": "1"}
    assert R.duplicate_link("SAME_DATA", i, dict(i)) == "VERIFIED_DUPLICATE"


# 4 ambiguous groups ----------------------------------------------------------------------------------------------------
def test_group_with_partial_links_is_unresolved_not_chained():
    links = {(0, 1): "VERIFIED_DUPLICATE", (1, 2): "VERIFIED_DUPLICATE", (0, 2): "UNRESOLVED_DUPLICATE"}
    groups, unres = R.duplicate_groups([0, 1, 2, 3], links)
    assert groups == [] and unres == {0, 1, 2}


def test_clique_of_verified_links_is_one_group():
    links = {(0, 1): "VERIFIED_DUPLICATE", (1, 2): "VERIFIED_DUPLICATE", (0, 2): "VERIFIED_DUPLICATE"}
    groups, unres = R.duplicate_groups([0, 1, 2, 3], links)
    assert groups == [[0, 1, 2]] and unres == set()


# 5 representative independent of outcomes -------------------------------------------------------------------------------
def test_representative_uses_ticker_on_d_then_quality_then_lexical():
    info = {0: {"symbol": "NEWCO", "ticker_at_D": "OLDCO", "traded_in_window": 20},
            1: {"symbol": "OLDCO", "ticker_at_D": "OLDCO", "traded_in_window": 20}}
    assert R.representative([0, 1], info) == (1, "OWN_TICKER_ON_D")
    info2 = {0: {"symbol": "B", "ticker_at_D": "X", "traded_in_window": 20},
             1: {"symbol": "A", "ticker_at_D": "X", "traded_in_window": 20}}
    assert R.representative([0, 1], info2) == (1, "LEXICAL_TIE_BREAK")
    # the function has no access to returns / outcomes by construction
    import inspect
    assert "return" not in inspect.signature(R.representative).parameters


# 6/7 unresolved identity & instrument excluded; operating with unknown sector -> SPY -------------------------------------
D_EV = date(2020, 11, 9)


def test_unresolved_instrument_and_spac():
    assert R.instrument_status(None, None, [], "NO_MEMBERSHIP_BY_D", D_EV) == ("UNRESOLVED_INSTRUMENT", "")
    assert R.instrument_status("6770", "2020-11-01", [], "VERIFIED", D_EV)[0] == "SPAC"


# 5.06 fixtures (V2.1) ----------------------------------------------------------------------------------------------------
def test_later_506_with_explicit_shell_interval_covering_d_is_spac():
    # dated SIC 6770 header on 2020-10-30 (interval start <= D); cessation effective 2021-02-26, filed 2021-03-01 (> D)
    assert R.instrument_status("6770", "2020-10-30", [("2021-02-26", "2021-03-01")], "NO_MEMBERSHIP_BY_D", D_EV)[0] == "SPAC"


def test_later_506_whose_shell_interval_does_not_cover_d():
    # an operating SIC is dated <= D; the only shell evidence is a cessation AFTER D -> shell start unknown -> unresolved
    assert R.instrument_status("3790", "2020-10-30", [("2021-02-26", "2021-03-01")], "NO_MEMBERSHIP_BY_D", D_EV) ==         ("UNRESOLVED_INSTRUMENT", "")
    # a cessation filed long BEFORE D ended the earlier shell interval -> operating on D
    assert R.instrument_status("3790", "2020-10-30", [("2014-01-15", "2014-01-23")], "NO_MEMBERSHIP_BY_D", D_EV)[0] ==         "OPERATING_SECTOR_KNOWN"


def test_506_without_adequate_interval_evidence_is_unresolved():
    # no dated SIC at all, only a later cessation, no S&P evidence
    assert R.instrument_status(None, None, [("2021-02-26", "2021-03-01")], "NO_MEMBERSHIP_BY_D", D_EV) ==         ("UNRESOLVED_INSTRUMENT", "")


def test_effective_date_versus_publication_date():
    # effective and published by D -> cessation established -> operating (stale 6770 header -> sector unknown -> SPY)
    assert R.instrument_status("6770", "2020-10-01", [("2020-11-02", "2020-11-05")], "NO_MEMBERSHIP_BY_D", D_EV) ==         ("OPERATING_SECTOR_UNKNOWN", "")
    # effective possibly before D but PUBLISHED after D: the cessation date is only bounded to [report, filing] ->
    # status on D not determinable -> unresolved (no operating override without dated evidence)
    assert R.instrument_status("6770", "2020-10-01", [("2020-11-06", "2020-11-12")], "NO_MEMBERSHIP_BY_D", D_EV) ==         ("UNRESOLVED_INSTRUMENT", "")
    # effective after D, header 6770 dated <= D -> shell interval covers D
    assert R.instrument_status("6770", "2020-10-01", [("2020-11-10", "2020-11-12")], "NO_MEMBERSHIP_BY_D", D_EV)[0] == "SPAC"


def test_verified_operating_unknown_sector_uses_spy_and_known_sector_uses_map():
    st, sic = R.instrument_status(None, None, [], "VERIFIED", D_EV)
    assert st == "OPERATING_SECTOR_UNKNOWN" and R.benchmark(st, sic, lambda s: "XLK") == "SPY"
    st, sic = R.instrument_status("3571", "2020-10-10", [], "NO_MEMBERSHIP_BY_D", D_EV)
    assert R.benchmark(st, sic, lambda s: "XLK" if s == "3571" else "SPY") == "XLK"
    assert R.benchmark("UNRESOLVED_INSTRUMENT", "", lambda s: "XLK") == ""


def test_unresolved_reasons_rank_before_r1a_and_instrument():
    assert R.first_reason({"ID_UNRESOLVED", "R1A_NOT_AVAILABLE", "INSTRUMENT_UNRESOLVED"}) == "ID_UNRESOLVED"
    assert R.first_reason({"INSTRUMENT_UNRESOLVED"}) == "INSTRUMENT_UNRESOLVED"


# 8 S&P evidence tied to the security, not the ticker string -------------------------------------------------------------
def test_sp_membership_of_a_reused_ticker_is_not_evidence():
    sp_rows = [("2019-03-01", {"ABC"})]
    f345 = {"ABC": [(date(2019, 2, 1), "OLD"), (date(2021, 6, 1), "NEW")]}
    edges = [("ABC", "ZZZ", date(2020, 1, 1))]
    assert R.sp_exempt("ABC", "NEW", D0, sp_rows, f345, edges) == "UNVERIFIED_LINK"
    assert R.sp_exempt("ABC", "OLD", date(2019, 6, 1), sp_rows, f345, []) == "VERIFIED"
    assert R.sp_exempt("ABC", "OLD", date(2019, 1, 15), sp_rows, f345, []) == "NO_MEMBERSHIP_BY_D"


def test_r1a_availability_has_no_recency_limit():
    assert R.r1a_available(["2012-03-01"], D0) is True
    assert R.r1a_available(["2021-06-16"], D0) is False
    assert R.r1a_available(["2021-06-15"], D0) is True


# 9 adjustment inside either leg -----------------------------------------------------------------------------------------
def test_leg_adjustment_detected_inside_interval_even_if_reversed():
    flat = [(9.9, 10.0, 9.9, 10.0)] * 11
    assert R.leg_no_adjustment(flat) == "NO_ADJUSTMENT"
    step = flat[:5] + [(9.0, 10.0, 9.0, 10.0)] + flat[6:]               # intermediate change that reverses
    assert R.leg_no_adjustment(step) == "ADJUSTED"
    assert R.leg_no_adjustment(flat[:5] + [None] + flat[6:]) == "UNKNOWN"
    assert R.sensitivity_member("NO_ADJUSTMENT", "ADJUSTED") == "OUT_OF_SUBSET"
    assert R.sensitivity_member("NO_ADJUSTMENT", "UNKNOWN") == "UNKNOWN"
    assert R.sensitivity_member("NO_ADJUSTMENT", "NO_ADJUSTMENT") == "IN_SUBSET"


def test_cent_rounding_is_not_an_adjustment():
    bars = [(10.004 * 0.98, 10.00, 12.346 * 0.98, 12.35)] * 11            # raw rounded to cents, factor 0.98
    assert R.leg_no_adjustment(bars) == "NO_ADJUSTMENT"


# 10 determinism and count reconciliation --------------------------------------------------------------------------------
def test_deterministic_grouping_and_reasons():
    links = {(2, 3): "VERIFIED_DUPLICATE", (0, 1): "UNRESOLVED_DUPLICATE"}
    a = R.duplicate_groups([3, 2, 1, 0], links)
    b = R.duplicate_groups([0, 1, 2, 3], dict(reversed(list(links.items()))))
    assert a == b == ([[2, 3]], {0, 1})
    flags = [{"C1_NO_GAP_PLACEHOLDER", "ID_UNRESOLVED"}, {"DUP_NOT_REPRESENTATIVE"}, set(), {"INSTRUMENT_SPAC"}]
    reasons = [R.first_reason(f) for f in flags]
    assert reasons == ["C1_NO_GAP_PLACEHOLDER", "DUP_NOT_REPRESENTATIVE", "", "INSTRUMENT_SPAC"]
    assert sum(1 for x in reasons if x) + sum(1 for x in reasons if not x) == len(flags)


# duplicate graph semantics (V2.1) ---------------------------------------------------------------------------------------
def test_identical_volume_different_price_candidates_stay_separate_and_valid():
    a, b = _series([10.0] * 25, [500] * 25), _series([12.0] * 25, [500] * 25)
    link = R.duplicate_link(R.same_series(a, b), {}, {})
    assert link == R.NOT_DUPLICATE
    groups, unres = R.duplicate_groups([0, 1], {(0, 1): link})
    assert groups == [] and unres == set()                 # no edge: both rows remain eligible on their own


def test_mixed_group_with_verified_rejected_and_unresolved_links():
    links = {(0, 1): R.VERIFIED_DUPLICATE, (1, 2): R.UNRESOLVED_DUPLICATE, (2, 3): R.NOT_DUPLICATE,
             (4, 5): R.VERIFIED_DUPLICATE}
    groups, unres = R.duplicate_groups([0, 1, 2, 3, 4, 5], links)
    assert groups == [[4, 5]]                             # clean verified pair accepted
    assert unres == {0, 1, 2}                             # component joined by an unresolved edge -> all unresolved
    assert 3 not in unres                                 # the rejected (NOT_DUPLICATE) link creates no edge


def test_rejected_pair_inside_a_verified_component_is_a_contradiction():
    links = {(0, 1): R.VERIFIED_DUPLICATE, (1, 2): R.VERIFIED_DUPLICATE, (0, 2): R.NOT_DUPLICATE}
    groups, unres = R.duplicate_groups([0, 1, 2], links)
    assert groups == [] and unres == {0, 1, 2}


def test_sensitivity_label_and_unknown_handling():
    assert R.SENSITIVITY_LABEL == "NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND"
    assert R.sensitivity_member("NO_ADJUSTMENT", "UNKNOWN") == "UNKNOWN"
