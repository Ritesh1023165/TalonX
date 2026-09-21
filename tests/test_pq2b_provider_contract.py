"""PQ-2B: SIP runtime adapter + OPEN/CLOSE finality + first-release provider contract.

Deterministic; no network, broker or production DB.  The SIP endpoint is an in-memory fake; the fake
records the request parameters so the CONTRACT (feed=sip, adjustment=split, end lag) is asserted.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import test_pq2a_corporate_actions as base
from test_pq2a_corporate_actions import CFG, ENTRY, TARGET, episode, guard_with
from talonx_v2 import calendar as v2cal, dividends as dv, pipeline, provider_contract as pc
from talonx_v2.corporate_actions import make_dividend_event, make_split_event
from talonx_v2.liquidity_window import evaluate_liquidity_checked
from talonx_v2.pricing import (
    CompositeBarAdapter, IncompatibleAdjustmentBasis, PricingResolver, YFinanceBarAdapter, make_resolver)
from talonx_v2.sip_adapter import (
    AlpacaSipBarAdapter, ProviderEntitlementError, ProviderError, ProviderMalformed, ProviderRateLimited,
    ProviderTimeout, session_of)
from talonx_v2.store import V2Store

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
NOW_LATE = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)          # long after every session used below
SYM = "PQX"


def t_of(session: date) -> str:
    """Alpaca daily-bar timestamp: New-York midnight expressed in UTC."""
    return datetime(session.year, session.month, session.day, tzinfo=ET).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def bar(session: date, o=20.0, c=20.5, v=1_000_000, h=None, l=None, **extra):
    d = {"t": t_of(session), "o": o, "h": h if h is not None else max(o, c) + 0.1,
         "l": l if l is not None else min(o, c) - 0.1, "c": c, "v": v, "n": 1000, "vw": (o + c) / 2}
    d.update(extra)
    return d


class FakeSip:
    """In-memory /v2/stocks/bars.  ``bars`` = list of bar dicts; ``exc`` raised on every call."""
    def __init__(self, bars=None, exc=None):
        self.bars, self.exc, self.calls = list(bars or []), exc, []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if self.exc:
            raise self.exc
        return {"bars": {params["symbols"]: list(self.bars)}, "next_page_token": None}


def prior_sessions(entry=ENTRY, n=20):
    return [s for s in v2cal._sessions() if s < entry][-n:]


def world_bars(entry_open=25.0, exit_close=27.0, *, exit_session=TARGET, skip=(), history_close=20.0):
    out = [bar(s, o=history_close, c=history_close) for s in prior_sessions() if s not in skip]
    out.append(bar(ENTRY, o=entry_open, c=entry_open + 0.5))
    if exit_session is not None:
        out.append(bar(exit_session, o=exit_close, c=exit_close))
    return out


def resolver_for(fake, *, now=NOW_LATE, **kw):
    return make_resolver(mode="sip", bar_dirs=[], today=lambda: now.date(), now=lambda: now,
                         sip_http_get=fake, **kw)


def new_store(tmp_path, name="s"):
    return V2Store(str(tmp_path / f"{name}.db"), starting_cash=300_000.0)


def run_entry(store, resolver, *, strict=True):
    return pipeline.process_episode(episode(), store=store, bars_lookup=resolver.bars_lookup,
                                    price_lookup=resolver.price_lookup, config=CFG,
                                    strict_liquidity_window=strict)


# =========================================================================== #
# 1-2  adapter contract
# =========================================================================== #
def test_01_sip_adapter_normal_daily_bar_and_provenance_fields():
    fake = FakeSip([bar(ENTRY, o=25.0, c=25.5, v=2_000_000)])
    a = AlpacaSipBarAdapter(key_id="k", secret="s", http_get=fake, now=lambda: NOW_LATE)
    r = a.session(SYM, ENTRY)
    assert (r["date"], r["open"], r["close"], r["volume"]) == (ENTRY.isoformat(), 25.0, 25.5, 2_000_000.0)
    assert (r["high"], r["low"]) == (25.6, 24.9)
    assert r["_source_timestamp"] == t_of(ENTRY) == "2026-09-08T04:00:00Z"
    assert (r["_feed"], r["_adjustment_state"], r["_basis_as_of"]) == ("sip", "SPLIT_ADJUSTED", NOW_LATE.date().isoformat())
    assert r["_receipt_timestamp"].startswith("2026-10-05T15:00:00")
    assert a.name == "alpaca:sip:1Day:adjustment=split"


def test_02_split_only_sip_daily_is_what_is_requested_never_dividend_adjusted():
    fake = FakeSip([bar(ENTRY)])
    AlpacaSipBarAdapter(key_id="k", secret="s", http_get=fake, now=lambda: NOW_LATE).history(SYM)
    url, p = fake.calls[0]
    assert url == "https://data.alpaca.markets/v2/stocks/bars"
    assert (p["feed"], p["adjustment"], p["timeframe"], p["symbols"], p["sort"]) == ("sip", "split", "1Day", SYM, "asc")
    assert p["adjustment"] not in ("all", "dividend", "raw")
    end = datetime.strptime(p["end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert NOW_LATE - end >= timedelta(minutes=15)                      # free-tier SIP: end >= 15 min old
    c = pc.RELEASE_CONTRACT
    assert (c.provider, c.feed, c.adjustment, c.fallback_mode, c.open_field, c.close_field) == (
        "alpaca", "sip", "split", "NONE", "o", "c")
    assert AlpacaSipBarAdapter.adjustment_state in pipeline_safe_bases()


def pipeline_safe_bases():
    from talonx_v2.corporate_actions import DIVIDEND_SAFE_BASES
    return DIVIDEND_SAFE_BASES


def test_adapter_cache_respects_ttl_and_refetches_when_stale():
    fake = FakeSip([bar(ENTRY)])
    clock = {"now": NOW_LATE}
    a = AlpacaSipBarAdapter(key_id="k", secret="s", http_get=fake, now=lambda: clock["now"])
    a.history(SYM); a.history(SYM)
    assert len(fake.calls) == 1                                          # within TTL -> no extra call
    clock["now"] = NOW_LATE + timedelta(seconds=pc.RELEASE_CONTRACT.cache_ttl_s + 1)
    a.history(SYM)
    assert len(fake.calls) == 2                                          # stale cache -> refetch (never stuck)


# =========================================================================== #
# 3-9  ENTRY OPEN
# =========================================================================== #
def test_03_normal_target_open_and_09_open_provenance_on_the_price():
    fake = FakeSip(world_bars(entry_open=25.0))
    px = resolver_for(fake).price_lookup(SYM, ENTRY)
    assert px["open"] == 25.0
    p = px["_provenance"]
    assert (p["provider"], p["feed"], p["adjustment_state"], p["session"]) == (
        "alpaca:sip:1Day:adjustment=split", "sip", "SPLIT_ADJUSTED", ENTRY.isoformat())
    assert p["source_timestamp"] == "2026-09-08T04:00:00Z" and p["receipt_timestamp"] and p["basis_as_of"]
    assert p["contract"] == "V2_RELEASE_PRICE_CONTRACT@1" and p["contract_fingerprint"] == pc.RELEASE_CONTRACT.fingerprint()
    assert p["session_tz"] == "America/New_York"
    assert p["usable_after_utc"] == pc.FinalityPolicy().usable_at(ENTRY).isoformat()


def test_04_open_missing_is_unavailable_never_a_fill(tmp_path):
    fake = FakeSip(world_bars(entry_open=25.0)[:-1][:20])            # entry bar absent
    r = resolver_for(fake)
    assert r.price_lookup(SYM, ENTRY) is None and r.last[f"{SYM}|{ENTRY.isoformat()}"].reason == "NO_BAR"
    store = new_store(tmp_path)
    res = run_entry(store, r)
    assert not res.entries and store.all_positions() == [] and store.cash() == 300_000.0


@pytest.mark.parametrize("bad", [float("nan"), 0.0, -3.0, None, "abc", float("inf")])
def test_05_06_07_open_nan_zero_negative_never_a_fill_or_a_zero(tmp_path, bad):
    bars = world_bars()
    for b in bars:
        if b["t"] == t_of(ENTRY):
            b["o"] = bad
    fake = FakeSip(bars)
    a = AlpacaSipBarAdapter(key_id="k", secret="s", http_get=fake, now=lambda: NOW_LATE)
    assert a.session(SYM, ENTRY) is None and any(x.get("t") == t_of(ENTRY) for x in a.rejected)
    store = new_store(tmp_path, f"bad{abs(hash(str(bad)))}")
    res = run_entry(store, resolver_for(fake))
    assert not res.entries and store.all_positions() == []


def test_08_open_delayed_availability_provisional_until_the_tape_is_complete():
    fake = FakeSip(world_bars())
    usable = pc.FinalityPolicy().usable_at(ENTRY)
    assert usable == datetime(2026, 9, 9, 0, 16, tzinfo=UTC)             # 20:00 ET post-market end + 16 min
    just_before = resolver_for(fake, now=usable - timedelta(seconds=1))
    assert just_before.price_lookup(SYM, ENTRY) is None
    assert just_before.last[f"{SYM}|{ENTRY.isoformat()}"].reason == "PROVISIONAL_ONLY"
    at = resolver_for(fake, now=usable)
    assert at.price_lookup(SYM, ENTRY)["open"] == 25.0
    # even after the regular close (16:00 ET) and after-hours started, the bar is NOT yet usable
    assert resolver_for(fake, now=v2cal.session_close_utc(ENTRY) + timedelta(hours=1)).price_lookup(SYM, ENTRY) is None


# =========================================================================== #
# 10-14  EXIT CLOSE + early close
# =========================================================================== #
def test_10_13_target_close_normal_with_provenance():
    fake = FakeSip(world_bars(exit_close=27.0))
    px = resolver_for(fake).price_lookup(SYM, TARGET)
    assert px["close"] == 27.0 and px["_provenance"]["source_timestamp"] == t_of(TARGET)
    assert px["_provenance"]["feed"] == "sip" and px["_provenance"]["adjustment_state"] == "SPLIT_ADJUSTED"


def test_11_close_missing_and_12_close_delayed():
    r = resolver_for(FakeSip(world_bars(exit_session=None)))
    assert r.price_lookup(SYM, TARGET) is None and r.last[f"{SYM}|{TARGET.isoformat()}"].reason == "NO_BAR"
    usable = pc.FinalityPolicy().usable_at(TARGET)
    late = resolver_for(FakeSip(world_bars()), now=usable - timedelta(minutes=1))
    assert late.price_lookup(SYM, TARGET) is None and late.last[f"{SYM}|{TARGET.isoformat()}"].reason == "PROVISIONAL_ONLY"
    assert resolver_for(FakeSip(world_bars()), now=usable).price_lookup(SYM, TARGET)["close"] == 27.0


def test_14_early_close_uses_the_actual_exchange_close_not_16_00():
    early, normal = date(2025, 11, 28), date(2025, 11, 26)
    assert v2cal.session_close_utc(early) == datetime(2025, 11, 28, 18, 0, tzinfo=UTC)      # 13:00 ET (EST)
    assert v2cal.session_close_utc(normal) == datetime(2025, 11, 26, 21, 0, tzinfo=UTC)     # 16:00 ET
    assert v2cal.session_extended_end_utc(early) == datetime(2025, 11, 28, 22, 0, tzinfo=UTC)   # 17:00 ET
    pol = pc.FinalityPolicy()
    assert pol.usable_at(early) == datetime(2025, 11, 28, 22, 16, tzinfo=UTC)
    assert pol.usable_at(normal) == datetime(2025, 11, 27, 1, 16, tzinfo=UTC)
    # a hardcoded 16:00 ET / 21:00Z assumption would have declared the early-close bar final 1h16m too early
    assert not pol.is_usable(early, datetime(2025, 11, 28, 21, 0, tzinfo=UTC))
    assert pol.is_usable(early, datetime(2025, 11, 28, 22, 16, tzinfo=UTC))
    assert v2cal.session_open_utc(date(2026, 9, 8)) == datetime(2026, 9, 8, 13, 30, tzinfo=UTC)   # EDT
    assert v2cal.session_open_utc(date(2025, 11, 26)) == datetime(2025, 11, 26, 14, 30, tzinfo=UTC)  # EST


# =========================================================================== #
# 15-20  failures
# =========================================================================== #
@pytest.mark.parametrize("exc,reason", [
    (ProviderTimeout("t"), "PROVIDER_TIMEOUT"), (ProviderRateLimited("429"), "PROVIDER_RATE_LIMITED"),
    (ProviderError("HTTP 500"), "PROVIDER_ERROR"), (ProviderEntitlementError("403"), "PROVIDER_ENTITLEMENT"),
    (ProviderMalformed("bad"), "PROVIDER_MALFORMED_RESPONSE")])
def test_15_16_17_timeout_rate_limit_provider_error_fail_closed_without_fabrication(tmp_path, exc, reason):
    r = resolver_for(FakeSip(exc=exc))
    assert r.price_lookup(SYM, ENTRY) is None and r.last[f"{SYM}|{ENTRY.isoformat()}"].reason == reason
    assert r.bars_lookup(SYM) == [] and r.last[f"{SYM}|history"].reason == reason
    store = new_store(tmp_path, reason)
    res = run_entry(store, r)
    assert not res.entries and store.all_positions() == [] and store.cash() == 300_000.0     # no trade, no zero default


def test_malformed_response_shapes_are_typed_errors():
    for body in ({"bars": "nope"}, {"bars": [1]}, []):
        a = AlpacaSipBarAdapter(key_id="k", secret="s", http_get=lambda u, p, b=body: b, now=lambda: NOW_LATE)
        with pytest.raises(ProviderMalformed):
            a.history(SYM)


def test_18_stale_response_missing_recent_sessions_fails_the_liquidity_window_closed(tmp_path):
    # a realistic stale response: 30 sessions of older history but the 2 MOST RECENT sessions missing
    older = [bar(s, o=20.0, c=20.0) for s in prior_sessions(n=32)[:-2]]
    stale = older + [bar(ENTRY, o=25.0, c=25.5)]
    store = new_store(tmp_path)
    res = run_entry(store, resolver_for(FakeSip(stale)))
    assert not res.entries
    assert store.episode_disposition("pq2a-episode").startswith("SKIPPED_NON_CONTIGUOUS_WINDOW_2_OF_20")
    # non-terminal: the same episode is retried once the provider catches up
    res2 = run_entry(store, resolver_for(FakeSip(world_bars())))
    assert len(res2.entries) == 1


def test_19_wrong_session_date_is_never_used_for_the_requested_session():
    other = prior_sessions()[-1]
    fake = FakeSip([bar(other, o=99.0, c=99.0)])
    r = resolver_for(fake)
    assert r.price_lookup(SYM, ENTRY) is None                            # no "nearest bar" substitution
    a = AlpacaSipBarAdapter(key_id="k", secret="s", http_get=fake, now=lambda: NOW_LATE)
    assert a.session(SYM, ENTRY) is None and a.session(SYM, other)["open"] == 99.0


def test_20_timezone_session_mapping_edt_est_and_rejected_non_midnight_stamps():
    assert session_of("2026-09-08T04:00:00Z") == date(2026, 9, 8)         # EDT midnight
    assert session_of("2025-11-28T05:00:00Z") == date(2025, 11, 28)       # EST midnight
    assert session_of("2026-09-08T00:00:00Z") is None                     # 20:00 ET previous day: NOT a daily stamp
    assert session_of("2026-09-08T13:30:00Z") is None                     # intraday
    assert session_of("2026-09-08T04:00:00") is None and session_of("garbage") is None and session_of(None) is None
    a = AlpacaSipBarAdapter(key_id="k", secret="s", now=lambda: NOW_LATE,
                            http_get=FakeSip([{**bar(ENTRY), "t": "2026-09-08T13:30:00Z"}]))
    assert a.history(SYM) == [] and a.rejected[0]["why"] == "malformed daily bar"


def test_conflicting_duplicate_rows_for_one_session_are_dropped_not_guessed():
    a = AlpacaSipBarAdapter(key_id="k", secret="s", now=lambda: NOW_LATE,
                            http_get=FakeSip([bar(ENTRY, o=25.0), bar(ENTRY, o=26.0)]))
    assert a.session(SYM, ENTRY) is None
    same = AlpacaSipBarAdapter(key_id="k", secret="s", now=lambda: NOW_LATE, http_get=FakeSip([bar(ENTRY), bar(ENTRY)]))
    assert same.session(SYM, ENTRY) is not None


# =========================================================================== #
# 21-26  recovery windows unchanged
# =========================================================================== #
def test_21_target_entry_missing_then_later_recovery_uses_the_target_sessions_open(tmp_path):
    store = new_store(tmp_path)
    fake = FakeSip(world_bars(entry_open=25.0)[:-1][:20])                 # session-1 bar missing at first
    r = resolver_for(fake)
    res = run_entry(store, r)
    assert not res.entries and res.skipped[-1]["reason"] == "NO_ENTRY_BAR"
    fake.bars = world_bars(entry_open=25.0) + [bar(v2cal.add_sessions(ENTRY, 1), o=99.0, c=99.0)]   # later: S1 bar appears
    r._raw_for = None
    res2 = run_entry(store, resolver_for(fake))
    assert len(res2.entries) == 1 and res2.entries[0]["entry_price"] == 25.0        # NOT Session 2's 99.0
    prov = json.loads(store.all_positions()[0]["entry_price_provenance"])
    assert prov["session"] == ENTRY.isoformat() and prov["field"] == "open"


def test_22_session_3_boundary_is_unchanged():
    dl = v2cal.recovery_deadline_session(ENTRY, CFG.max_entry_staleness_sessions)
    assert dl == v2cal.add_sessions(ENTRY, 2)                              # Session 3 with Session 1 = target
    assert not v2cal.recovery_deadline_passed(ENTRY, max_entry_staleness_sessions=3, ripe_through=dl, live=False)
    assert v2cal.recovery_deadline_passed(ENTRY, max_entry_staleness_sessions=3,
                                          ripe_through=v2cal.add_sessions(dl, 1), live=False)
    assert CFG.max_entry_staleness_sessions == 3 and CFG.exit_fallforward_max_sessions == 5


def _position(tmp_path, name="x"):
    store = new_store(tmp_path, name)
    res = run_entry(store, resolver_for(FakeSip(world_bars(exit_session=None)), now=pc.FinalityPolicy().usable_at(ENTRY)))
    assert len(res.entries) == 1
    return store


def _settle(store, fake, *, as_of, now=NOW_LATE):
    r = resolver_for(fake, now=now)
    pipeline.settle_due_exits(store=store, as_of_session=as_of, price_lookup=r.price_lookup, config=CFG,
                              corporate_actions=guard_with())
    return store.all_positions()[0]


def test_23_target_exit_missing_then_first_eligible_close_in_plus_5(tmp_path):
    store = _position(tmp_path)
    ff1 = v2cal.add_sessions(TARGET, 1)
    fake = FakeSip(world_bars(exit_session=None) + [bar(ff1, o=28.0, c=28.0)])
    pos = _settle(store, fake, as_of=ff1)
    assert pos["status"] == "CLOSED" and pos["exit_session"] == ff1.isoformat() and pos["exit_price"] == 28.0
    assert json.loads(pos["exit_price_provenance"])["session"] == ff1.isoformat()


def test_24_25_26_plus_5_boundary_beyond_plus_5_never_used_and_exit_unresolved_when_exhausted(tmp_path):
    ff5, ff6 = v2cal.add_sessions(TARGET, 5), v2cal.add_sessions(TARGET, 6)
    s5 = _position(tmp_path, "p5")
    assert _settle(s5, FakeSip(world_bars(exit_session=None) + [bar(ff5, o=28.0, c=28.0)]), as_of=ff5)["status"] == "CLOSED"
    s6 = _position(tmp_path, "p6")
    pos = _settle(s6, FakeSip(world_bars(exit_session=None) + [bar(ff6, o=28.0, c=28.0)]), as_of=ff6)
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["exit_price"] is None and pos["realized_pnl_usd"] is None
    assert [t["action"] for t in s6.trades()] == ["BUY"]                    # no invented SELL, no zero price


def test_exit_bar_not_yet_final_is_not_used_early_within_the_window(tmp_path):
    store = _position(tmp_path)
    usable = pc.FinalityPolicy().usable_at(TARGET)
    pos = _settle(store, FakeSip(world_bars()), as_of=TARGET, now=usable - timedelta(minutes=5))
    assert pos["status"] == "OPEN"                                            # provisional close never settles
    assert _settle(store, FakeSip(world_bars()), as_of=TARGET, now=usable)["status"] == "CLOSED"


# =========================================================================== #
# 27-32  liquidity contract
# =========================================================================== #
def _liq(close, volume, *, n=20):
    return [{"date": s.isoformat(), "close": close, "volume": volume} for s in prior_sessions(n=n)]


def test_27_28_thresholds_unchanged_5_dollar_close_and_5m_median_dollar_volume():
    ok = evaluate_liquidity_checked(_liq(5.00, 1_000_000), entry_session=ENTRY, require_contiguous=True)
    assert ok.ok and ok.median_dollar_volume == 5_000_000.0
    assert not evaluate_liquidity_checked(_liq(4.99, 2_000_000), entry_session=ENTRY, require_contiguous=True).ok
    assert not evaluate_liquidity_checked(_liq(5.00, 999_999), entry_session=ENTRY, require_contiguous=True).ok
    assert evaluate_liquidity_checked(_liq(10.0, 500_000), entry_session=ENTRY, require_contiguous=True).ok
    assert (CFG.liquidity_min_close, CFG.liquidity_min_median_dollar_volume, CFG.liquidity_lookback_sessions) == (5.0, 5_000_000.0, 20)


# real NVDA rows (2024-06-05..06-13, SIP) recorded in the PQ-2A probe: raw vs adjustment=split
NVDA_RAW = [("2024-06-05", 1224.4, 52840178), ("2024-06-06", 1209.98, 66469619), ("2024-06-07", 1208.88, 41238580),
            ("2024-06-10", 121.79, 314162666), ("2024-06-11", 120.91, 222551158)]
NVDA_SPLIT = [("2024-06-05", 122.44, 528401780), ("2024-06-06", 121.0, 664696190), ("2024-06-07", 120.89, 412385800),
              ("2024-06-10", 121.79, 314162666), ("2024-06-11", 120.91, 222551158)]


def test_29_30_split_inside_the_liquidity_window_dollar_volume_is_basis_invariant():
    for (d1, c1, v1), (d2, c2, v2) in zip(NVDA_RAW, NVDA_SPLIT):
        assert d1 == d2 and math.isclose(c1 * v1, c2 * v2, rel_tol=2e-3)       # price x volume identical across the split
    # gate decision identical on raw-vs-split series (price falls 10x, volume rises 10x)
    sess = prior_sessions(n=20)
    def series(rows_pre, rows_post):
        pre, post = rows_pre[0], rows_post[0]
        return ([{"date": s.isoformat(), "close": pre[0], "volume": pre[1]} for s in sess[:10]] +
                [{"date": s.isoformat(), "close": post[0], "volume": post[1]} for s in sess[10:]])
    raw = series([(1208.88, 41_238_580)], [(121.79, 314_162_666)])
    spl = series([(120.89, 412_385_800)], [(121.79, 314_162_666)])
    a = evaluate_liquidity_checked(raw, entry_session=ENTRY, require_contiguous=True)
    b = evaluate_liquidity_checked(spl, entry_session=ENTRY, require_contiguous=True)
    assert a.ok == b.ok and math.isclose(a.median_dollar_volume, b.median_dollar_volume, rel_tol=2e-3)
    # mixing basis (split-adjusted price with RAW pre-split volume) would understate dollar volume ~10x
    mixed = [{"date": s.isoformat(), "close": 120.89, "volume": 41_238_580} for s in sess]
    assert evaluate_liquidity_checked(mixed, entry_session=ENTRY, require_contiguous=True).median_dollar_volume < \
        b.median_dollar_volume / 5


def test_31_32_composite_all_adjusted_snapshot_cannot_contaminate_split_only_release_history(tmp_path):
    import csv
    bd = tmp_path / "bars"
    bd.mkdir()
    with open(bd / f"{SYM}.csv", "w", newline="") as fh:                      # a POISONED snapshot: must never be read
        w = csv.writer(fh)
        w.writerow(["date", "open", "close", "volume"])
        for s in prior_sessions():
            w.writerow([s.isoformat(), 999.0, 999.0, 1])
    r = make_resolver(mode="sip", bar_dirs=[str(bd)], today=lambda: NOW_LATE.date(), now=lambda: NOW_LATE,
                      sip_http_get=FakeSip(world_bars()))
    bars = r.bars_lookup(SYM)
    assert len(bars) == 22 and {b["close"] for b in bars} == {20.0, 25.5, 27.0}
    assert all(b["open"] != 999.0 and b["_provenance"]["feed"] == "sip" for b in bars)
    assert r.adapter.name == "alpaca:sip:1Day:adjustment=split" and not hasattr(r.adapter, "hist")
    # the composite path itself refuses an all-adjusted snapshot + split-only tail (state mismatch)
    comp = make_resolver(mode="composite-yf", bar_dirs=[str(bd)], today=lambda: NOW_LATE.date(),
                         yf_ticker_factory=lambda s: _YfStub(), ca_source=guard_with())
    assert comp.bars_lookup(SYM) == []
    assert comp.last[f"{SYM}|history"].reason == "REJECTED_INCOMPATIBLE_ADJUSTMENT_BASIS"


class _YfStub:
    def history(self, **kw):
        import pandas as pd
        idx = pd.to_datetime([v2cal.add_sessions(ENTRY, 1).isoformat()])
        return pd.DataFrame({"Open": [26.0], "Close": [26.0], "Volume": [1_000_000]}, index=pd.Index(idx, name="Date"))


def test_31_incompatible_basis_fails_closed_directly():
    hist = base.MemAdapter("snap", [{**base.row(s), "_adjustment_state": "SPLIT_DIVIDEND_ADJUSTED"} for s in prior_sessions(n=5)])
    live = base.MemAdapter("live", [{**base.row(ENTRY), "_adjustment_state": "SPLIT_ADJUSTED"}])
    with pytest.raises(IncompatibleAdjustmentBasis, match="adjustment state mismatch"):
        CompositeBarAdapter(hist, live, ca_source=guard_with(), today=lambda: NOW_LATE.date()).history(SYM)


# =========================================================================== #
# 33-35  disagreement + fallback
# =========================================================================== #
def test_33_provider_disagreement_is_logged_primary_stays_authoritative_never_averaged():
    witness = base.MemAdapter("witness-yf", [{**base.row(ENTRY, open_=25.6, close=26.05), "_adjustment_state": "SPLIT_ADJUSTED"}])
    r = resolver_for(FakeSip(world_bars(entry_open=25.0)), witness=witness)
    px = r.price_lookup(SYM, ENTRY)
    assert px["open"] == 25.0                                               # primary, not 25.3 (average) and not 25.6
    dis = {d["field"]: d for d in r.disagreements}
    assert set(dis) == {"open", "close"} and dis["open"]["action"] == "LOGGED_ONLY_PRIMARY_AUTHORITATIVE"
    assert dis["open"]["primary"]["value"] == 25.0 and dis["open"]["witness"]["value"] == 25.6
    # agreeing witness -> nothing logged; failing witness -> ignored, price unaffected
    ok = base.MemAdapter("w", [{**base.row(ENTRY, open_=25.01, close=25.5)}])
    r2 = resolver_for(FakeSip(world_bars(entry_open=25.0)), witness=ok)
    assert r2.price_lookup(SYM, ENTRY)["open"] == 25.0 and r2.disagreements == []
    class Boom:
        name = "boom"
        def session(self, *a): raise RuntimeError("x")
    r3 = resolver_for(FakeSip(world_bars(entry_open=25.0)), witness=Boom())
    assert r3.price_lookup(SYM, ENTRY)["open"] == 25.0


def test_34_35_fallback_only_when_semantically_compatible_and_release_mode_has_none():
    S = pc.SEMANTICS
    primary = S["sip_release"]
    same = pc.AdapterSemantics(**{**primary.__dict__, "name": "hypothetical-identical-sip"})
    assert pc.fallback_mismatches(primary, same) == []
    assert pc.fallback_allowed(primary, same, mode="COMPATIBLE_ONLY") == (True, [])
    ok, why = pc.fallback_allowed(primary, same)                            # RELEASE setting = NONE
    assert not ok and "fail closed" in why[0]
    for key, needle in (("iex_split", "feed_scope"), ("yfinance_split", "not qualified"),
                        ("task107a_sip_snapshot", "adjustment")):
        ok, why = pc.fallback_allowed(primary, S[key], mode="COMPATIBLE_ONLY")
        assert not ok and any(needle in w for w in why), (key, why)
    allbasis = pc.AdapterSemantics(**{**primary.__dict__, "adjustment": "all"})
    assert "adjustment: split != all" in pc.fallback_mismatches(primary, allbasis)
    assert pc.RELEASE_CONTRACT.fallback_mode == "NONE"
    r = resolver_for(FakeSip(exc=ProviderTimeout("down")))
    assert r.price_lookup(SYM, ENTRY) is None                               # provider down -> NO silent fallback


# =========================================================================== #
# 36-38  corporate-action / dividend compatibility + provenance
# =========================================================================== #
def _full_position_via_sip(tmp_path, *, exit_close, events, name="ca"):
    store = new_store(tmp_path, name)
    entry_res = resolver_for(FakeSip(world_bars(exit_session=None)), now=pc.FinalityPolicy().usable_at(ENTRY))
    assert len(run_entry(store, entry_res).entries) == 1
    r = resolver_for(FakeSip(world_bars(exit_close=exit_close)))
    guard = guard_with(*events)
    pipeline.settle_due_exits(store=store, as_of_session=TARGET, price_lookup=r.price_lookup, config=CFG,
                              corporate_actions=guard)
    return store, guard


def test_36_split_during_hold_is_compatible_with_split_only_sip_prices(tmp_path):
    store, _ = _full_position_via_sip(tmp_path, exit_close=2.7,
                                      events=[make_split_event(SYM, v2cal.add_sessions(ENTRY, 4), 10, 1)], name="split")
    pos = store.all_positions()[0]
    assert pos["status"] == "CLOSED" and pos["realized_pnl_pct"] == pytest.approx(8.0)       # 400 -> 4000 sh, +$800
    assert [t for t in store.trades() if t["action"] == "SELL"][0]["shares"] == 4000.0
    # split INSIDE the liquidity window: same gate decision on the split-only series
    sess = prior_sessions()
    bars = [bar(s, o=100.0 if i < 10 else 10.0, c=100.0 if i < 10 else 10.0, v=200_000 if i < 10 else 2_000_000)
            for i, s in enumerate(sess)] + [bar(ENTRY, o=10.5, c=10.5)]
    bs = new_store(tmp_path, "winsplit")
    assert len(run_entry(bs, resolver_for(FakeSip(bars))).entries) == 1               # $20M/day both sides of the split


def test_37_dividend_during_hold_credits_cash_without_double_counting_on_sip_prices(tmp_path):
    ex = v2cal.add_sessions(ENTRY, 3)
    ev = make_dividend_event(SYM, ex, "0.50", payable_date=ex + timedelta(days=7))
    store, guard = _full_position_via_sip(tmp_path, exit_close=27.0, events=[ev], name="div")
    pos = store.all_positions()[0]
    assert pos["realized_pnl_usd"] == pytest.approx(400 * 27.0 - 10_000.0)             # price P&L untouched by the dividend
    assert [e["amount_usd"] for e in store.dividend_entitlements()] == [200.0]          # SIP basis is dividend-UNadjusted -> allowed
    dv.settle_receivables(store, guard, as_of=ev.payable_date)
    assert store.cash() == pytest.approx(300_000.0 + 800.0 + 200.0)


def test_38_entry_exit_and_liquidity_provenance_persist_through_restart(tmp_path):
    store, _ = _full_position_via_sip(tmp_path, exit_close=27.0, events=[], name="prov")
    restarted = V2Store(str(tmp_path / "prov.db"))
    pos = restarted.all_positions()[0]
    for fld, col, session in (("open", "entry_price_provenance", ENTRY), ("close", "exit_price_provenance", TARGET)):
        p = json.loads(pos[col])
        assert (p["provider"], p["feed"], p["field"], p["session"], p["adjustment_state"]) == (
            "alpaca:sip:1Day:adjustment=split", "sip", fld, session.isoformat(), "SPLIT_ADJUSTED")
        assert p["source_timestamp"] == t_of(session) and p["receipt_timestamp"] and p["basis_as_of"]
        assert p["contract"] == "V2_RELEASE_PRICE_CONTRACT@1" and p["usable_after_utc"]
    assert [json.loads(t["price_provenance"])["field"] for t in restarted.trades()] == ["open", "close"]
    lw = json.loads(pos["source_meta"])["liquidity_window"]
    assert lw["n_sessions"] == 20 and lw["providers"] == ["alpaca:sip:1Day:adjustment=split"] and lw["feeds"] == ["sip"]
    assert lw["adjustment_states"] == ["SPLIT_ADJUSTED"] and lw["strict_contiguous_window"] is True
    assert (lw["first_session"], lw["last_session"]) == (prior_sessions()[0].isoformat(), prior_sessions()[-1].isoformat())
    assert lw["contract"] == "V2_RELEASE_PRICE_CONTRACT@1"


# =========================================================================== #
# 39  replay compatibility
# =========================================================================== #
def test_39_replay_compatibility_classification_is_explicit():
    S = pc.SEMANTICS
    verdict, why = pc.classify_replay(S["task107a_sip_snapshot"])
    assert verdict == "PARTIALLY_COMPATIBLE"
    assert any(w.startswith("adjustment: replay all") for w in why) and any("snapshot" in w for w in why) \
        and any("corporate-action" in w for w in why)
    assert pc.classify_replay(S["sip_release"])[0] == "COMPATIBLE"
    for k in ("iex_split", "yfinance_split"):
        v, w = pc.classify_replay(S[k])
        assert v == "INCOMPATIBLE" and any("feed_scope" in x or "semantics" in x for x in w)


# =========================================================================== #
# 40-42  configuration / entitlement / readiness
# =========================================================================== #
class ReadyFake:
    """A provider that honours split-only (NVDA raw open 1197.70 vs split 119.77)."""
    def __init__(self, honour=True, exc=None):
        self.honour, self.exc, self.calls = honour, exc, []

    def __call__(self, url, params):
        self.calls.append(params)
        if self.exc:
            raise self.exc
        if params["symbols"] == "AAPL":
            return {"bars": {"AAPL": [bar(date(2026, 10, 2), o=300.0, c=301.0, v=50_000_000)]}}
        split = params["adjustment"] == "split" and self.honour
        o, c, v = (119.77, 120.89, 412_385_800) if split else (1197.7, 1208.88, 41_238_580)
        return {"bars": {"NVDA": [bar(date(2024, 6, 7), o=o, c=c, v=v)]}}


ENV = {"APCA_API_KEY_ID": "k", "APCA_API_SECRET_KEY": "s"}


def test_40_configuration_missing_is_reported_and_no_call_is_made():
    fake = ReadyFake()
    rep = pc.check_readiness(env={"APCA_API_KEY_ID": "k"}, http_get=fake, now=lambda: NOW_LATE)
    assert rep.level == "NOT_CONFIGURED" and not rep.qualified and fake.calls == []
    assert rep.checks["configured"]["missing"] == ["APCA_API_SECRET_KEY"]
    assert pc.check_readiness(env={}, http_get=fake).level == "NOT_CONFIGURED"
    assert pc.check_readiness(env={"APCA_API_KEY_ID": " ", "APCA_API_SECRET_KEY": "s"}, http_get=fake).level == "NOT_CONFIGURED"


def test_41_entitlement_failure_is_reachable_but_not_entitled_or_qualified():
    rep = pc.check_readiness(env=ENV, http_get=ReadyFake(exc=ProviderEntitlementError("HTTP 403")), now=lambda: NOW_LATE)
    assert rep.level == "REACHABLE" and not rep.qualified and rep.checks["entitled"]["ok"] is False
    rep2 = pc.check_readiness(env=ENV, http_get=ReadyFake(exc=ProviderTimeout("t")), now=lambda: NOW_LATE)
    assert rep2.level == "CONFIGURED" and not rep2.qualified


def test_42_readiness_qualified_only_when_split_only_is_provably_honoured():
    good = pc.check_readiness(env=ENV, http_get=ReadyFake(), now=lambda: NOW_LATE)
    assert good.level == "QUALIFIED" and good.qualified
    assert 9.9 < good.checks["split_only_enforced"]["open_ratio"] < 10.1
    assert len(ReadyFake().calls) == 0
    bad = pc.check_readiness(env=ENV, http_get=ReadyFake(honour=False), now=lambda: NOW_LATE)
    assert bad.level == "ENTITLED" and not bad.qualified and "adjustment=split" in bad.problems[0]
    d = good.to_dict()
    assert d["contract_id"] == "V2_RELEASE_PRICE_CONTRACT@1" and d["contract_fingerprint"] == pc.RELEASE_CONTRACT.fingerprint()


def test_live_start_in_sip_mode_refuses_unless_the_provider_is_qualified(tmp_path, monkeypatch):
    from talonx_v2 import run
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    monkeypatch.setattr(pc, "check_readiness", lambda **kw: pc.ReadinessReport(level="ENTITLED", problems=["split-only not honoured"]))
    with pytest.raises(SystemExit) as ei:
        run.main(["--mode", "live", "--db", str(tmp_path / "x.db"), "--once", "--as-of", "2026-09-08",
                  "--pricing-mode", "sip"])
    assert "not QUALIFIED" in str(ei.value) and "ENTITLED" in str(ei.value)


def test_service_status_reports_the_active_release_contract_and_strict_window(tmp_path):
    from talonx_v2.service import V2Service
    svc = V2Service(config=base.V2Config(db_path=str(tmp_path / "svc.db"), starting_cash_usd=300_000.0),
                    bar_dirs=[tmp_path], status_path=str(tmp_path / "s.json"), pricing_mode="sip",
                    corporate_actions=guard_with())
    st = svc._provider_contract_status()
    assert st["release_contract_active"] and st["provider"] == "alpaca" and st["feed"] == "sip"
    assert st["adjustment"] == "split" and st["fallback_mode"] == "NONE" and "extended_end" in st["finality_rule"]
    assert svc.strict_liquidity_window is True
    csv_svc = V2Service(config=base.V2Config(db_path=str(tmp_path / "svc2.db")), bar_dirs=[tmp_path],
                        status_path=str(tmp_path / "s2.json"))
    assert csv_svc.strict_liquidity_window is False and csv_svc._provider_contract_status()["release_contract_active"] is False
    # clock: a pinned tick is the START of the pinned date, a live tick is the wall clock
    svc._as_of_holder.update(d=date(2026, 9, 10), live=False)
    assert svc._pricing_now() == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    svc._as_of_holder.update(live=True)
    assert abs((svc._pricing_now() - datetime.now(UTC)).total_seconds()) < 5


# =========================================================================== #
# 43-46  strategy integrity
# =========================================================================== #
def test_43_44_strategy_thresholds_and_fingerprint_unchanged_and_liquidity_module_byte_identical():
    cfg = base.V2Config()
    assert (cfg.min_distinct_owners, cfg.hold_trading_days, cfg.entry_offset_sessions, cfg.liquidity_lookback_sessions,
            cfg.liquidity_min_median_dollar_volume, cfg.liquidity_min_close, cfg.exit_fallforward_max_sessions,
            cfg.max_entry_staleness_sessions) == (2, 10, 1, 20, 5_000_000.0, 5.0, 5, 3)
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "research" / "scripts" / "task112_v2_release_fingerprint.py"
    spec = importlib.util.spec_from_file_location("pq2b_fp", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.v2_release_fingerprint()["fingerprint"] == "e2acf6454789217e"


# =========================================================================== #
# 47-50  late-published dividend catch-up (bounded)
# =========================================================================== #
def _closed_position(tmp_path, name, *, exit_close=27.0):
    store, _ = _full_position_via_sip(tmp_path, exit_close=exit_close, events=[], name=name)       # settled with NO dividend known
    assert store.all_positions()[0]["status"] == "CLOSED" and store.dividend_entitlements() == []
    return store


def _late_div():
    ex = v2cal.add_sessions(ENTRY, 4)
    return make_dividend_event(SYM, ex, "0.40", payable_date=ex + timedelta(days=8))


def test_47_late_published_eligible_dividend_on_a_recently_closed_trade_is_accrued_then_credited(tmp_path):
    store = _closed_position(tmp_path, "late")
    ev = _late_div()
    g = guard_with(ev)
    out = dv.catch_up_recent_closed(store, g, as_of=v2cal.add_sessions(TARGET, 1))
    assert [o["status"] for o in out] == ["LATE_DIVIDEND_ACCRUED"]
    e = store.dividend_entitlements()[0]
    assert (e["state"], e["amount_usd"], e["eligible_qty"]) == ("ACCRUED", 160.0, "400")
    pos_before = dict(store.all_positions()[0])
    cash0 = store.cash()
    assert dv.settle_receivables(store, g, as_of=ev.payable_date)[0]["status"] == "CREDITED"
    assert store.cash() == pytest.approx(cash0 + 160.0)
    assert dict(store.all_positions()[0]) == pos_before                     # the closed trade was never reopened/mutated


def test_48_duplicate_late_publication_and_repeated_catch_up_remain_idempotent(tmp_path):
    store = _closed_position(tmp_path, "late2")
    ev = _late_div()
    dup = make_dividend_event(SYM, ev.ex_date, "0.400", provider_id="DIFFERENT-ID", payable_date=ev.payable_date)
    g = guard_with(ev, dup)
    asof = v2cal.add_sessions(TARGET, 1)
    assert len(dv.catch_up_recent_closed(store, g, as_of=asof)) == 1
    for _ in range(3):
        assert dv.catch_up_recent_closed(store, g, as_of=asof) == []          # nothing new
    dv.settle_receivables(store, g, as_of=ev.payable_date)
    dv.settle_receivables(store, g, as_of=ev.payable_date)
    assert len(store.dividend_entitlements()) == 1 and store.dividends_credited_total() == 160.0


def test_49_lookback_bound_is_enforced_no_indefinite_rescan(tmp_path):
    store = _closed_position(tmp_path, "late3")
    g = guard_with(_late_div())
    assert dv.catch_up_recent_closed(store, g, as_of=v2cal.add_sessions(TARGET, dv.LATE_DIVIDEND_LOOKBACK_SESSIONS + 1)) == []
    assert store.dividend_entitlements() == []
    assert [o["status"] for o in dv.catch_up_recent_closed(
        store, g, as_of=v2cal.add_sessions(TARGET, dv.LATE_DIVIDEND_LOOKBACK_SESSIONS))] == ["LATE_DIVIDEND_ACCRUED"]
    assert dv.LATE_DIVIDEND_LOOKBACK_SESSIONS == CFG.exit_fallforward_max_sessions == 5


def test_50_legacy_and_unrelated_trades_are_not_backfilled(tmp_path):
    store = new_store(tmp_path, "legacy")
    pid = store.insert_open_position(episode_id="legacy", symbol=SYM, issuer_cik="", entry_session=ENTRY,
                                     target_exit_session=TARGET, entry_price=25.0, shares=400, position_cost=10_000.0)
    store.set_cash(290_000.0)
    with sqlite3.connect(store.path) as con:                                # a settled LEGACY trade (no provenance)
        con.execute("UPDATE positions SET status='CLOSED', exit_session=?, exit_price=27.0, realized_pnl_usd=800.0 "
                    "WHERE position_id=?", (TARGET.isoformat(), pid))
    out = dv.catch_up_recent_closed(store, guard_with(_late_div()), as_of=v2cal.add_sessions(TARGET, 1))
    assert [o["status"] for o in out] == ["SKIPPED_PRICE_BASIS_NOT_UNADJUSTED_OR_LEGACY"] and store.dividend_entitlements() == []
    assert store.all_positions()[0]["entry_price_provenance"] is None       # nothing fabricated
    # an OPEN position and a different symbol are not touched by the catch-up
    s2 = _position(tmp_path, "openpos")
    assert dv.catch_up_recent_closed(s2, guard_with(_late_div()), as_of=v2cal.add_sessions(TARGET, 1)) == []
    s3 = _closed_position(tmp_path, "othersym")
    other = make_dividend_event("ZZZ", v2cal.add_sessions(ENTRY, 4), "0.40", payable_date=TARGET + timedelta(days=9))
    assert dv.catch_up_recent_closed(s3, guard_with(other), as_of=v2cal.add_sessions(TARGET, 1)) == []


def test_catch_up_skips_unsupported_or_conflicting_evidence_and_evidence_outage(tmp_path):
    from talonx_v2.corporate_actions import make_unsupported_event
    store = _closed_position(tmp_path, "skip")
    asof = v2cal.add_sessions(TARGET, 1)
    u = make_unsupported_event(SYM, v2cal.add_sessions(ENTRY, 3), "spin_offs")
    assert dv.catch_up_recent_closed(store, guard_with(_late_div(), u), as_of=asof)[0]["status"] == \
        "SKIPPED_UNSUPPORTED_OR_CONFLICTING_EVIDENCE"
    assert dv.catch_up_recent_closed(store, guard_with(status="UNAVAILABLE"), as_of=asof)[0]["status"] == "EVIDENCE_UNAVAILABLE"
    assert store.dividend_entitlements() == []
