"""PQ-1 focused deterministic provider/provenance qualification tests.

No network, broker, production DB, or provider activation is used here.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from talonx_v2 import calendar as v2cal, pipeline
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.liquidity import evaluate_liquidity
from talonx_v2.pricing import CompositeBarAdapter, PriceUnavailable, PricingResolver
from talonx_v2.store import V2Store
from talonx_v2.service import V2Service


class MemAdapter:
    def __init__(self, name, rows=None, exc=None):
        self.name, self.rows, self.exc = name, rows or [], exc

    def history(self, symbol):
        if self.exc:
            raise self.exc
        return list(self.rows)

    def session(self, symbol, session):
        if self.exc:
            raise self.exc
        return next((r for r in self.rows if r["date"] == session.isoformat()), None)


def row(session, open_=20.0, close=20.5, volume=1_000_000, **extra):
    return {"date": session.isoformat(), "open": open_, "close": close,
            "volume": volume, **extra}


def episode(entry):
    act = date(2026, 8, 14)
    return ClusterEpisode(
        episode_id="pq1-episode", symbol="PQX", issuer_cik="1",
        distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
        first_filing_date=act, activation_filing_date=act, last_filing_date=act,
        aggregate_purchase_value=1.0, any_officer=False, any_director=False,
        any_ten_percent=False,
        causal_event_ts=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        eligible_entry_session=entry)


def test_timeout_and_rate_limit_fail_closed_as_provider_error():
    for exc in (TimeoutError("timeout"), RuntimeError("HTTP 429")):
        resolver = PricingResolver(MemAdapter("failed", exc=exc), today=lambda: date(2026, 9, 9))
        assert resolver.bars_lookup("PQX") == []
        got = resolver.resolve("PQX", date(2026, 9, 8))
        assert isinstance(got, PriceUnavailable) and got.reason == "PROVIDER_ERROR"


def test_split_adjusted_price_and_volume_preserve_dollar_volume_economics():
    entry = date(2026, 9, 8)
    sessions = list(v2cal._sessions())
    prior = [s for s in sessions if s < entry][-20:]
    raw = [row(s, close=100.0, volume=100_000) for s in prior]
    split_adjusted = [row(s, close=10.0, volume=1_000_000) for s in prior]
    a = evaluate_liquidity(raw, entry_session=entry)
    b = evaluate_liquidity(split_adjusted, entry_session=entry)
    assert a.ok == b.ok
    assert a.median_dollar_volume == b.median_dollar_volume == 10_000_000


def test_composite_disagreement_never_arbitrarily_overwrites_authority():
    session = date(2026, 9, 8)
    primary = MemAdapter("primary", [row(session, open_=20.0)])
    fallback = MemAdapter("fallback", [row(session, open_=99.0)])
    composite = CompositeBarAdapter(primary, fallback)
    assert composite.session("PQX", session)["open"] == 20.0


def test_entry_exit_provenance_persists_across_restart(tmp_path):
    entry = date(2026, 9, 8)
    exit_session = v2cal.add_sessions(entry, 10)
    sessions = [s for s in v2cal._sessions() if s < entry][-20:]
    rows = [row(s, close=20.0, volume=1_000_000,
                _adjustment_state="SPLIT_DIVIDEND_ADJUSTED") for s in sessions]
    rows += [row(entry, open_=25.0, close=25.5, volume=2_000_000,
                 _source_timestamp=f"{entry.isoformat()}T04:00:00Z",
                 _adjustment_state="SPLIT_DIVIDEND_ADJUSTED"),
             row(exit_session, open_=27.0, close=28.0, volume=2_100_000,
                 _source_timestamp=f"{exit_session.isoformat()}T04:00:00Z",
                 _adjustment_state="SPLIT_DIVIDEND_ADJUSTED")]
    resolver = PricingResolver(MemAdapter("qualified-fixture", rows),
                               today=lambda: v2cal.add_sessions(exit_session, 1))
    db = tmp_path / "pq1.db"
    store = V2Store(str(db), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0)
    result = pipeline.process_episode(
        episode(entry), store=store, bars_lookup=resolver.bars_lookup,
        price_lookup=resolver.price_lookup, config=cfg)
    assert len(result.entries) == 1
    pipeline.settle_due_exits(store=store, as_of_session=exit_session,
                              price_lookup=resolver.price_lookup, config=cfg)

    restarted = V2Store(str(db))
    position = restarted.all_positions()[0]
    entry_p = json.loads(position["entry_price_provenance"])
    exit_p = json.loads(position["exit_price_provenance"])
    trades = restarted.trades()
    assert (entry_p["provider"], entry_p["field"], entry_p["session"]) == (
        "qualified-fixture", "open", entry.isoformat())
    assert (exit_p["provider"], exit_p["field"], exit_p["session"]) == (
        "qualified-fixture", "close", exit_session.isoformat())
    assert [json.loads(t["price_provenance"])["field"] for t in trades] == ["open", "close"]
    assert json.loads(position["source_meta"])["liquidity_price_provenance"]


def test_legacy_rows_are_not_given_fabricated_provenance(tmp_path):
    store = V2Store(str(tmp_path / "legacy.db"), starting_cash=300_000.0)
    pid = store.insert_open_position(
        episode_id="legacy", symbol="OLD", issuer_cik="", entry_session=date(2026, 9, 8),
        target_exit_session=date(2026, 9, 22), entry_price=10.0, shares=100,
        position_cost=1_000.0)
    position = store.all_positions()[0]
    assert position["position_id"] == pid
    assert position["entry_price_provenance"] is None


def test_default_csv_runtime_labels_date_only_provenance_without_fabricating_finality(tmp_path):
    import csv
    bars = tmp_path / "bars"
    bars.mkdir()
    with open(bars / "PQX.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "close", "volume"])
        writer.writerow(["2026-09-08", 20.0, 21.0, 1_000_000])
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "runtime.db")),
                    bar_dirs=[bars], form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"))
    px = svc._price("PQX", date(2026, 9, 8))
    assert px["_provenance"]["provider"] == "csv:frozen_bar_dirs"
    assert px["_provenance"]["finality"] == "LEGACY_DATE_ONLY"
    assert px["_provenance"]["adjustment_state"] == "UNKNOWN_LEGACY_CSV"
    assert px["_provenance"]["source_timestamp"] is None


def test_exit_unresolved_marker_preserves_existing_price_evidence(tmp_path):
    store = V2Store(str(tmp_path / "unresolved.db"), starting_cash=300_000.0)
    pid = store.insert_open_position(
        episode_id="unresolved", symbol="OLD", issuer_cik="", entry_session=date(2026, 9, 8),
        target_exit_session=date(2026, 9, 22), entry_price=10.0, shares=100,
        position_cost=1_000.0,
        source_meta={"liquidity_price_provenance": [{"provider": "source-a"}]})
    store.mark_exit_unresolved(pid, detail="bounded fixture")
    meta = json.loads(store.all_positions()[0]["source_meta"])
    assert meta["liquidity_price_provenance"][0]["provider"] == "source-a"
    assert meta["exit_unresolved"] is True


# --------------------------------------------------------------------------- #
# PQ-1 (continuation): composite provenance, fallback policy, lifecycle
# recovery with provenance, invariance of strategy fingerprint/thresholds, and
# a characterization of the open corporate-action gap (OPS-004/OPS-005).
# --------------------------------------------------------------------------- #
def _prior(entry, n=20):
    return [s for s in v2cal._sessions() if s < entry][-n:]


def _liquid_history(entry, **extra):
    return [row(s, close=20.0, volume=1_000_000, **extra) for s in _prior(entry)]


def test_composite_provenance_names_the_sub_adapter_that_supplied_the_bar():
    entry = date(2026, 9, 8)
    # PQ-2A: splicing two sources requires a PROVABLY compatible adjustment basis
    # (same basis date); an unknown/unequal basis is refused (see the PQ-2A tests).
    basis = "2026-09-10"
    hist = MemAdapter("hist-snapshot", [row(s, close=20.0, _basis_as_of=basis) for s in _prior(entry)])
    live = MemAdapter("live-tail", [row(entry, open_=25.0, close=25.5, _basis_as_of=basis)])
    resolver = PricingResolver(CompositeBarAdapter(hist, live), today=lambda: date(2026, 9, 10))
    assert resolver.price_lookup("PQX", entry)["_provenance"]["provider"] == "live-tail"
    covered = _prior(entry)[-1]
    assert resolver.price_lookup("PQX", covered)["_provenance"]["provider"] == "hist-snapshot"
    providers = {b["_provenance"]["provider"] for b in resolver.bars_lookup("PQX")}
    assert providers == {"hist-snapshot", "live-tail"}


def test_composite_fallback_only_for_sessions_the_authority_does_not_cover():
    session = date(2026, 9, 8)
    hist = MemAdapter("primary", [])
    live = MemAdapter("secondary", [row(session, open_=31.0)])
    composite = CompositeBarAdapter(hist, live)
    assert composite.session("PQX", session)["open"] == 31.0          # gap -> tail
    hist.rows = [row(session, open_=30.0)]
    assert composite.session("PQX", session)["open"] == 30.0          # authority wins
    assert composite.session("PQX", session)["_source_adapter"] == "primary"


def test_missing_or_invalid_open_never_becomes_a_fill_or_a_zero(tmp_path):
    entry = date(2026, 9, 8)
    for bad in (float("nan"), 0.0, -1.0, None):
        rows = _liquid_history(entry) + [row(entry, open_=bad, close=21.0)]
        resolver = PricingResolver(MemAdapter("bad-open", rows),
                                   today=lambda: date(2026, 9, 9))
        assert resolver.price_lookup("PQX", entry) is None
        store = V2Store(str(tmp_path / f"m{abs(hash(str(bad)))}.db"), starting_cash=300_000.0)
        res = pipeline.process_episode(
            episode(entry), store=store, bars_lookup=resolver.bars_lookup,
            price_lookup=resolver.price_lookup, config=V2Config(starting_cash_usd=300_000.0))
        assert not res.entries and store.all_positions() == []
        assert store.cash() == 300_000.0


def _open_position(tmp_path, entry, exit_rows):
    exit_session = v2cal.add_sessions(entry, 10)
    rows = _liquid_history(entry) + [row(entry, open_=25.0, close=25.5)] + exit_rows(exit_session)
    resolver = PricingResolver(MemAdapter("fixture", rows), today=lambda: date(2026, 12, 31))
    store = V2Store(str(tmp_path / "lc.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0)
    res = pipeline.process_episode(
        episode(entry), store=store, bars_lookup=resolver.bars_lookup,
        price_lookup=resolver.price_lookup, config=cfg)
    assert len(res.entries) == 1
    return store, resolver, cfg, exit_session


def test_exit_fallforward_uses_first_later_close_and_records_that_session(tmp_path):
    entry = date(2026, 9, 8)
    target = v2cal.add_sessions(entry, 10)
    ff2 = v2cal.add_sessions(target, 2)     # +1 missing too: earliest AVAILABLE is +2
    store, resolver, cfg, target = _open_position(
        tmp_path, entry, lambda t: [row(ff2, open_=27.0, close=28.0)])
    pipeline.settle_due_exits(store=store, as_of_session=ff2,
                              price_lookup=resolver.price_lookup, config=cfg)
    pos = store.all_positions()[0]
    assert pos["status"] == "CLOSED" and pos["exit_session"] == ff2.isoformat()
    assert json.loads(pos["exit_price_provenance"])["session"] == ff2.isoformat()


def test_exit_bar_beyond_five_sessions_is_never_used_and_exhaustion_is_unresolved(tmp_path):
    entry = date(2026, 9, 8)
    target = v2cal.add_sessions(entry, 10)
    too_late = v2cal.add_sessions(target, 6)
    store, resolver, cfg, target = _open_position(
        tmp_path, entry, lambda t: [row(too_late, open_=27.0, close=28.0)])
    pipeline.settle_due_exits(store=store, as_of_session=too_late,
                              price_lookup=resolver.price_lookup, config=cfg)
    pos = store.all_positions()[0]
    assert pos["status"] == "EXIT_UNRESOLVED"
    assert pos["exit_price"] is None and pos["exit_price_provenance"] is None
    assert json.loads(pos["source_meta"])["liquidity_price_provenance"] is not None
    assert [t["action"] for t in store.trades()] == ["BUY"]          # no made-up SELL


def test_strategy_thresholds_and_release_fingerprint_unchanged_by_pq1():
    cfg = V2Config()
    assert (cfg.min_distinct_owners, cfg.hold_trading_days, cfg.entry_offset_sessions,
            cfg.liquidity_lookback_sessions, cfg.liquidity_min_median_dollar_volume,
            cfg.liquidity_min_close, cfg.exit_fallforward_max_sessions,
            cfg.max_entry_staleness_sessions) == (2, 10, 1, 20, 5_000_000.0, 5.0, 5, 3)
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "research" / "scripts" / "task112_v2_release_fingerprint.py"
    spec = importlib.util.spec_from_file_location("pq1_fp", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.v2_release_fingerprint()["fingerprint"] == "e2acf6454789217e"


def test_split_during_hold_is_normalized_by_the_ledger_pq2a_supersedes_known_gap(tmp_path):
    """PQ-1 KNOWN_GAP, now a CORRECTNESS test (superseded by PQ-2A; the original
    characterization -- ~-89% spurious loss on a 10:1 split during a hold -- is
    reproduced in tests/test_pq2a_corporate_actions.py::test_root_cause_*).

    Same fixture: 10:1 forward split during the hold, exit ~2.7.  With the
    corporate-action guard the position is re-expressed as 10x shares at
    unchanged aggregate cost, so realized P&L is the true ~+8%, not -89%."""
    from talonx_v2.corporate_actions import (
        CorporateActionGuard, StaticCorporateActionSource, make_split_event)
    entry = date(2026, 9, 8)
    basis = "2026-09-08"
    exit_session = v2cal.add_sessions(entry, 10)
    rows = ([row(s, close=20.0, volume=1_000_000, _basis_as_of=basis) for s in _prior(entry)]
            + [row(entry, open_=25.0, close=25.5, _basis_as_of=basis),
               row(exit_session, open_=2.6, close=2.7, _basis_as_of="2026-09-23")])   # ~25.5 / 10
    resolver = PricingResolver(MemAdapter("fixture", rows), today=lambda: date(2026, 12, 31))
    store = V2Store(str(tmp_path / "lc.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0)
    pipeline.process_episode(episode(entry), store=store, bars_lookup=resolver.bars_lookup,
                             price_lookup=resolver.price_lookup, config=cfg)
    guard = CorporateActionGuard(StaticCorporateActionSource(
        [make_split_event("PQX", v2cal.add_sessions(entry, 4), 10, 1)]))
    pipeline.settle_due_exits(store=store, as_of_session=exit_session,
                              price_lookup=resolver.price_lookup, config=cfg, corporate_actions=guard)
    pos = store.all_positions()[0]
    assert pos["status"] == "CLOSED"
    assert pos["realized_pnl_pct"] == 8.0 or abs(pos["realized_pnl_pct"] - 8.0) < 1e-6
    assert pos["realized_pnl_pct"] > -50.0                       # the spurious ~-89% is gone
