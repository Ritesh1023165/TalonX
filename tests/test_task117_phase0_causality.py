"""
Task 117 Phase 0 Phase 4 -- causal-timestamp fixtures for the Form-4 adapter.

The frozen contract: an episode fires when the 2nd distinct insider's Form 4
is *publicly disseminated* (FILING_DATE / EDGAR acceptance).  A live tick sees
only what is public at the tick's `as_of`; an as-of replay must not admit
later-in-day / after-cutoff information.

`from_insider_store(since=, causal_cutoff=)`:
  - `since`  bounds the DISSEMINATION window from below (widened SQL +
    re-filter on acceptance date -> late-filed old transactions kept)
  - `causal_cutoff` bounds acceptance from above (no future knowledge)

Two transactions by ONE owner never make a cluster; the 2nd DISTINCT owner
activates; a stale eligible-entry episode is never entered.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from talonx_v2 import form4_source
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config


class _Txn:
    def __init__(self, symbol, owner_cik, transaction_date, accepted_at_utc, accession):
        self.symbol = symbol
        self.owner_cik = owner_cik
        self.issuer_cik = symbol + "_cik"
        self.accession = accession
        self.transaction_date = date.fromisoformat(transaction_date)
        self.accepted_at_utc = datetime.fromisoformat(accepted_at_utc)
        self.filing_date = None
        self.transaction_value = 250_000.0
        self.transaction_code = "P"
        self.is_officer = True
        self.is_director = self.is_ten_percent_owner = False


class _Store:
    def __init__(self, txns):
        self._t = txns

    def query_transactions(self, *, since=None, causal_cutoff=None, **_):
        out = []
        for t in self._t:
            if since is not None and t.transaction_date < since:
                continue
            if causal_cutoff is not None and t.accepted_at_utc > causal_cutoff:
                continue
            out.append(t)
        return out


def _cut(d):
    return datetime.combine(date.fromisoformat(d), datetime.max.time().replace(microsecond=0),
                            tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
def test_later_same_day_filing_visible_only_after_its_acceptance():
    # owner o2 accepted 2026-09-08 18:00Z; a tick as-of 2026-09-08 (cutoff = end of day)
    # sees it; a tick "as of the 2026-09-08 open" (cutoff 14:00Z) does not.
    txns = [_Txn("AAA", "o1", "2026-09-02", "2026-09-03T14:00:00+00:00", "a1"),
            _Txn("AAA", "o2", "2026-09-05", "2026-09-08T18:00:00+00:00", "a2")]
    since = date(2026, 7, 26)
    late = form4_source.from_insider_store(_Store(txns), since=since, causal_cutoff=_cut("2026-09-08"))
    early = form4_source.from_insider_store(
        _Store(txns), since=since,
        causal_cutoff=datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc))
    assert len(late) == 2 and len(early) == 1
    assert detect_episodes(late, config=V2Config()) != []      # cluster once both are public
    assert detect_episodes(early, config=V2Config()) == []     # not yet


def test_after_close_acceptance_belongs_to_that_calendar_day_cutoff():
    txns = [_Txn("BBB", "o1", "2026-09-01", "2026-09-02T13:00:00+00:00", "b1"),
            _Txn("BBB", "o2", "2026-09-03", "2026-09-04T23:30:00+00:00", "b2")]  # after close
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-04"))
    assert {r.owner_cik for r in got} == {"o1", "o2"}
    assert form4_source.from_insider_store(
        _Store(txns), since=date(2026, 7, 26), causal_cutoff=_cut("2026-09-03")) == \
        [r for r in got if r.owner_cik == "o1"]


def test_late_filed_old_transaction_stays_in_window():
    # transaction 90 days before `since`, accepted inside it
    txns = [_Txn("CCC", "o1", "2026-04-20", "2026-08-05T14:00:00+00:00", "c1"),
            _Txn("CCC", "o2", "2026-04-22", "2026-08-06T14:00:00+00:00", "c2")]
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-09"))
    assert len(got) == 2
    assert detect_episodes(got, config=V2Config()) != []


def test_transaction_date_differs_from_acceptance_uses_acceptance_for_window():
    txns = [_Txn("DDD", "o1", "2026-06-01", "2026-07-10T14:00:00+00:00", "d1"),  # accepted BEFORE since
            _Txn("DDD", "o2", "2026-08-01", "2026-08-03T14:00:00+00:00", "d2")]
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-09"))
    assert [r.owner_cik for r in got] == ["o2"]                # o1 disseminated before the window


def test_future_records_already_in_store_are_excluded_by_cutoff():
    txns = [_Txn("EEE", "o1", "2026-09-04", "2026-09-08T14:00:00+00:00", "e1"),
            _Txn("EEE", "o2", "2026-09-05", "2026-09-20T14:00:00+00:00", "e2")]  # future
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-09"))
    assert [r.owner_cik for r in got] == ["o1"]


def test_two_transactions_one_owner_not_a_cluster():
    txns = [_Txn("FFF", "same", "2026-08-10", "2026-08-11T14:00:00+00:00", "f1"),
            _Txn("FFF", "same", "2026-08-12", "2026-08-13T14:00:00+00:00", "f2")]
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-09"))
    assert len(got) == 2
    assert detect_episodes(got, config=V2Config()) == []


def test_second_distinct_owner_activates():
    txns = [_Txn("GGG", "o1", "2026-08-10", "2026-08-11T14:00:00+00:00", "g1"),
            _Txn("GGG", "o1", "2026-08-12", "2026-08-13T14:00:00+00:00", "g1b"),  # same owner again
            _Txn("GGG", "o2", "2026-08-14", "2026-08-17T14:00:00+00:00", "g2")]   # 2nd DISTINCT
    got = form4_source.from_insider_store(_Store(txns), since=date(2026, 7, 26),
                                          causal_cutoff=_cut("2026-09-09"))
    eps = detect_episodes(got, config=V2Config())
    assert len(eps) == 1
    # activation keyed on the 2nd distinct owner's dissemination (2026-08-17)
    assert eps[0].activation_filing_date == date(2026, 8, 17)
    assert eps[0].n_distinct_owners == 2


def test_abcl_style_stale_episode_excluded_by_service_guard(tmp_path):
    from talonx_v2.service import V2Service
    from talonx_v2.store import V2Store
    txns = [_Txn("ABCL", "o1", "2026-07-27", "2026-07-28T14:00:00+00:00", "h1"),
            _Txn("ABCL", "o2", "2026-07-29", "2026-07-31T14:00:00+00:00", "h2")]  # disseminated inside the
    #   45-day window (since=2026-07-26); eligible entry ~2026-08-03 -> >3 sessions stale by 2026-09-09
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "v.db"), starting_cash_usd=300_000.0),
                    bar_dirs=[tmp_path], form4_kind="insider", status_path=str(tmp_path / "s.json"))
    import talonx_ingest.intelligence.insider.store as _st
    _st_orig = _st.InsiderStore
    _st.InsiderStore = lambda *a, **k: _Store(txns)
    try:
        st = svc.tick(as_of=date(2026, 9, 9))            # ~40 sessions later -> STALE
    finally:
        _st.InsiderStore = _st_orig
    assert st["stale_entry_skipped_this_tick"] == 1
    assert st["entries_this_tick"] == 0
    assert V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0).cash() == 300_000.0
