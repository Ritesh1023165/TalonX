"""
Task 117 Phase 0 -- Acceptance closure Phase 5: frozen-universe enforcement
conformance.

The frozen rule is membership-OR-liquidity.  These tests pin the enforcement
invariants that a broader ingestion must not break:
  * issuer-CIK is authoritative; owner-CIK spillover cannot bypass eligibility
  * a valid >=2-distinct-owner cluster that FAILS the liquidity screen never enters
  * MEMBERSHIP_UNKNOWN is not NON_MEMBER -- the liquidity branch backstops

No production store. Isolated V2Store + synthetic bars only.
"""
from __future__ import annotations

from datetime import date

from talonx_v2 import pipeline, pricing
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.form4_source import from_rows
from talonx_v2.store import V2Store

ENTRY = date(2026, 8, 17)
ACT = date(2026, 8, 14)


class _Adapter:
    name = "fake"

    def __init__(self, bars):
        self._b = bars

    def history(self, sym):
        return list(self._b.get(sym, []))

    def session(self, sym, s):
        return next((r for r in self._b.get(sym, []) if r["date"] == s.isoformat()), None)


def _hist(close, vol, sym="X"):
    from talonx_v2 import calendar as v2cal
    ss = [s for s in v2cal._sessions() if date(2026, 6, 1) <= s < ENTRY]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in ss]


def _cluster(sym, issuer_cik, owner_ciks):
    rows = [{"symbol": sym, "issuer_cik": issuer_cik, "owner_cik": oc,
             "filing_date": ACT.isoformat(), "accession": f"a{i}",
             "transaction_value": 250000, "transaction_code": "P"}
            for i, oc in enumerate(owner_ciks)]
    eps = detect_episodes(from_rows(rows), config=V2Config())
    return eps


def _run(tmp_path, ep, bars):
    r = pricing.PricingResolver(adapter=_Adapter(bars))
    r.today = lambda: date(2026, 8, 18)
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    res = pipeline.ProcessResult()
    pipeline.process_episode(ep, store=store, bars_lookup=r.bars_lookup,
                             price_lookup=r.price_lookup, config=V2Config(), result=res)
    return store, res


def test_issuer_cik_authoritative_two_distinct_owners_is_a_cluster(tmp_path):
    eps = _cluster("AAA", "0001111111", ["own_A", "own_B"])
    assert len(eps) == 1
    assert eps[0].issuer_cik == "0001111111"          # from the issuer, not an owner
    assert eps[0].n_distinct_owners == 2


def test_same_owner_twice_is_not_a_cluster(tmp_path):
    eps = _cluster("BBB", "0002222222", ["solo", "solo"])
    assert eps == []                                   # 1 distinct owner


def test_owner_cik_spillover_does_not_merge_two_issuers(tmp_path):
    # one owner CIK files code-P for TWO different issuers -- must stay two
    # separate issuers, neither a cluster (1 distinct owner each)
    rows = [
        {"symbol": "FUND1", "issuer_cik": "0000000001", "owner_cik": "BIGHOLDER",
         "filing_date": ACT.isoformat(), "accession": "s1", "transaction_code": "P",
         "transaction_value": 100000},
        {"symbol": "FUND2", "issuer_cik": "0000000002", "owner_cik": "BIGHOLDER",
         "filing_date": ACT.isoformat(), "accession": "s2", "transaction_code": "P",
         "transaction_value": 100000},
    ]
    assert detect_episodes(from_rows(rows), config=V2Config()) == []


def test_spillover_issuer_failing_liquidity_never_enters(tmp_path):
    # a genuine >=2-distinct-owner cluster, but the issuer's $-volume is far
    # below $5M -> SKIPPED, no BUY (eligibility is enforced at the issuer level)
    eps = _cluster("THIN", "0003333333", ["own_A", "own_B"])
    assert len(eps) == 1
    illiquid = {"THIN": _hist(close=8.0, vol=1_000, sym="THIN") + [   # 8*1000 = $8k/session
        {"date": ENTRY.isoformat(), "open": 8.0, "close": 8.0, "volume": 1_000}]}
    store, res = _run(tmp_path, eps[0], illiquid)
    assert res.entries == []
    disp = store.episode_disposition(eps[0].episode_id)
    assert disp.startswith("SKIPPED_") and "MEDIAN_DV" in disp
    assert store.n_open() == 0 and store.cash() == 300_000.0


def test_close_below_five_dollars_never_enters(tmp_path):
    eps = _cluster("PENNY", "0004444444", ["own_A", "own_B"])
    cheap = {"PENNY": _hist(close=3.5, vol=10_000_000, sym="PENNY") + [
        {"date": ENTRY.isoformat(), "open": 3.5, "close": 3.5, "volume": 10_000_000}]}
    store, res = _run(tmp_path, eps[0], cheap)
    assert res.entries == []
    assert "CLOSE_3.50_LT_5.0" in store.episode_disposition(eps[0].episode_id)


def test_membership_unknown_is_not_non_member_liquidity_backstops(tmp_path):
    # no PIT membership list is wired into talonx_v2 -> membership is UNKNOWN for
    # every issuer.  An issuer that PASSES the liquidity branch still enters --
    # UNKNOWN membership does not block (frozen OR-rule, limitation 5).
    eps = _cluster("LIQ", "0005555555", ["own_A", "own_B"])
    liquid = {"LIQ": _hist(close=50.0, vol=1_000_000, sym="LIQ") + [   # 50*1e6 = $50M/session
        {"date": ENTRY.isoformat(), "open": 51.0, "close": 52.0, "volume": 900_000}]}
    store, res = _run(tmp_path, eps[0], liquid)
    assert len(res.entries) == 1
    assert store.episode_disposition(eps[0].episode_id) == "ENTERED"


def test_liquidity_uses_only_sessions_strictly_before_entry(tmp_path):
    # even a huge entry-session bar cannot rescue a name that fails on the
    # trailing-20 window (no look-ahead)
    eps = _cluster("LOOK", "0006666666", ["own_A", "own_B"])
    bars = {"LOOK": _hist(close=8.0, vol=1_000, sym="LOOK") + [
        {"date": ENTRY.isoformat(), "open": 8.0, "close": 8.0, "volume": 999_999_999}]}
    store, res = _run(tmp_path, eps[0], bars)
    assert res.entries == []                           # entry-session volume ignored
