"""
Task 112 -- FINAL SAFETY, RELEASE FREEZE & TUESDAY FULL-DAY QUALIFICATION.

Covers the Phase-24 matrix: explicit V2 profile selection, frozen
fingerprints, the $300k operational paper balance (cash-only, no sizing
change), 20-position capacity + 21st blocked + cash release, the bounded
exit fall-forward (forward-only, first-available, explicit unresolved
state after +5), restart / persistence, no EOD flatten, Experimental
shadow isolation, official Telegram, dashboard placement, supervisor
ownership, and the safety invariants (no broker / shorts / real capital /
paid data / strategy drift).

Pure / in-memory + a live-Redis-optional item.  No live trading session.
"""
from __future__ import annotations

import json
import os
from datetime import date

import pytest

from talonx_v2 import calendar as v2cal
from talonx_v2 import dispatch_bridge, form4_source, pipeline
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config, V2_VERSION
from talonx_v2.paper import close_position, due_exits, enter_position
from talonx_v2.profile import DEFAULT_PROFILE, StrategyProfile, active_profile
from talonx_v2.schemas import V2Action
from talonx_v2.store import V2Store


TUESDAY_PAPER_BALANCE = 300_000.0


def _cfg(**kw):
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", TUESDAY_PAPER_BALANCE)
    return V2Config(**kw)


def _liquid_bars(a="2026-01-01", b="2026-12-01", close=100.0, vol=200_000):
    sess = [s for s in v2cal._sessions()
            if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _two(sym, d1="2026-03-02", d2="2026-03-04"):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
             accession=sym + "a1", transaction_value=60_000, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
             accession=sym + "a2", transaction_value=90_000, is_director=True, transaction_code="P"),
    ]


def _mk_lookups(bars_by_sym, entry_open=100.0, exit_close=105.0):
    def bl(sym):
        return bars_by_sym.get(sym, [])

    def pl(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        for x in bars_by_sym.get(sym, []):
            if x["date"] == ds:
                return {"open": entry_open, "close": exit_close}
        return None

    return bl, pl


# ===================== 1-4 : profile + fingerprints =====================
def test_01_v2_selected_explicitly():
    assert active_profile({"TALONX_ACTIVE_STRATEGY_PROFILE": "INSIDER_BUY_CLUSTER_V2"}) \
        is StrategyProfile.INSIDER_BUY_CLUSTER_V2


def test_02_original_v1_still_selectable_and_default():
    assert DEFAULT_PROFILE is StrategyProfile.ORIGINAL_V1
    assert active_profile({}) is StrategyProfile.ORIGINAL_V1


def test_03_v1_fingerprint_intact():
    from talonx_backtest.reproducibility import get_strategy_version
    assert get_strategy_version() == "2ae6216bca70"
    from talonx_quant.config import QuantConfig
    c = QuantConfig()
    assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)


def test_04_v2_release_fingerprint_stable():
    from research.scripts.task112_v2_release_fingerprint import v2_release_fingerprint
    a = v2_release_fingerprint()
    b = v2_release_fingerprint()
    assert a["fingerprint"] == b["fingerprint"] and len(a["fingerprint"]) == 16
    assert a["strategy_version"] == V2_VERSION
    assert a["config"]["cluster_window_trading_days"] == 10
    assert a["config"]["min_distinct_owners"] == 2
    assert a["config"]["transaction_code"] == "P"
    assert a["config"]["hold_trading_days"] == 10
    assert a["config"]["exit_fallforward_max_sessions"] == 5


# ===================== 5-10 : $300k balance + capacity =====================
def test_05_300k_local_paper_config():
    os.environ["TALONX_V2_STARTING_CASH_USD"] = "300000"
    try:
        assert V2Config().starting_cash_usd == 300_000.0
    finally:
        os.environ.pop("TALONX_V2_STARTING_CASH_USD", None)


def test_06_per_position_sizing_unchanged_by_balance():
    small = V2Config(starting_cash_usd=100_000.0)
    big = V2Config(starting_cash_usd=300_000.0)
    assert small.per_position_allocation_usd == big.per_position_allocation_usd == 10_000.0


def test_07_max_concurrent_unchanged():
    assert V2Config(starting_cash_usd=300_000.0).max_concurrent_positions == 20


def test_08_and_09_twenty_fit_and_21st_blocked(tmp_path):
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=TUESDAY_PAPER_BALANCE)
    cfg = _cfg()
    rows, bars = [], {}
    for i in range(21):
        sym = f"C{i:02d}"
        rows += _two(sym)
        bars[sym] = _liquid_bars()
    bl, pl = _mk_lookups(bars)
    eps = detect_episodes(form4_source.from_rows(rows), config=cfg)
    entered = 0
    blocked_reason = None
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.liquidity import evaluate_liquidity
    for ep in eps:
        liq = evaluate_liquidity(bl(ep.symbol), entry_session=ep.eligible_entry_session, config=cfg)
        dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq, config=cfg))
        out = enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                             config=cfg, source_meta={"issuer_cik": ep.issuer_cik})
        if out.entered:
            entered += 1
        else:
            blocked_reason = out.reason
    assert entered == 20                                  # all 20 fit at $300k -- no false NO_CASH
    assert blocked_reason and "MAX_CONCURRENT_20" in blocked_reason
    # $300k - 20*$10k = $100k left  (no borrowing / margin)
    assert st.cash() == pytest.approx(100_000.0)


def test_10_cash_released_after_exit_allows_new_position(tmp_path):
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=200_000.0)   # 20 positions exactly
    cfg = _cfg(starting_cash_usd=200_000.0)
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.liquidity import evaluate_liquidity
    rows, bars = [], {}
    for i in range(20):
        sym = f"D{i:02d}"
        rows += _two(sym)
        bars[sym] = _liquid_bars()
    bl, pl = _mk_lookups(bars)
    eps = detect_episodes(form4_source.from_rows(rows), config=cfg)
    for ep in eps:
        liq = evaluate_liquidity(bl(ep.symbol), entry_session=ep.eligible_entry_session, config=cfg)
        dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq, config=cfg))
        enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                       config=cfg, source_meta={})
    assert st.n_open() == 20 and st.cash() == pytest.approx(0.0)
    pos = st.open_positions()[0]
    close_position(st, pos, exit_price=110.0, exit_session=date(2026, 4, 1), config=cfg)
    assert st.cash() > 0                                  # cash released
    assert st.n_open() == 19


# ===================== 11-17 : exit fall-forward safety =====================
def _one_open(tmp_path, cfg, target_bar_dates):
    """open a position with entry 2026-03-04, target exit +10 td, and a
    price_lookup that only has closes on the given dates."""
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=TUESDAY_PAPER_BALANCE)
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.liquidity import evaluate_liquidity
    ep = detect_episodes(form4_source.from_rows(_two("EE")), config=cfg)[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session, config=cfg)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq, config=cfg))
    enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                   config=cfg, source_meta={})
    pos = st.open_positions()[0]
    target = date.fromisoformat(pos["target_exit_session"])
    avail = {v2cal.add_sessions(target, k).isoformat() for k in target_bar_dates}

    def pl(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        return {"open": 100.0, "close": 108.0} if ds in avail else None

    return st, pos, target, pl


@pytest.mark.parametrize("offset", [0, 1, 3, 5])
def test_11_to_14_fallforward_uses_first_available(tmp_path, offset):
    cfg = _cfg()
    st, pos, target, pl = _one_open(tmp_path, cfg, [offset])
    far = v2cal.add_sessions(target, 10)
    pipeline.settle_due_exits(store=st, as_of_session=far, price_lookup=pl, config=cfg)
    assert st.n_open() == 0
    closed = [p for p in st.all_positions() if p["status"] == "CLOSED"][0]
    assert closed["exit_session"] == v2cal.add_sessions(target, offset).isoformat()


def test_15_missing_through_plus5_is_explicit_unresolved(tmp_path):
    cfg = _cfg()
    st, pos, target, pl = _one_open(tmp_path, cfg, [])          # no bars at all near target
    far = v2cal.add_sessions(target, 10)
    res = pipeline.settle_due_exits(store=st, as_of_session=far, price_lookup=pl, config=cfg)
    # Package 1 Settlement Integrity: EXIT_UNRESOLVED is no longer OPEN
    # (not retryable), but it still occupies its capacity slot until an
    # operator auditably resolves it -- n_open() now correctly counts
    # OPEN + EXIT_UNRESOLVED.
    assert st.open_positions() == []
    assert st.n_open() == 1
    unresolved = st.unresolved_positions()
    assert len(unresolved) == 1 and unresolved[0]["status"] == "EXIT_UNRESOLVED"
    assert any(s["reason"] == "EXIT_UNRESOLVED" for s in res.skipped)
    # and it is NOT retried / not silently held
    res2 = pipeline.settle_due_exits(store=st, as_of_session=far, price_lookup=pl, config=cfg)
    assert res2.skipped == [] and res2.exits == []


def test_16_no_best_price_selection(tmp_path):
    cfg = _cfg()
    # bars at target+1 (close 108) AND target+3 (close 999) -> must take +1, not the better +3
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=TUESDAY_PAPER_BALANCE)
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.liquidity import evaluate_liquidity
    ep = detect_episodes(form4_source.from_rows(_two("FF")), config=cfg)[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session, config=cfg)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq, config=cfg))
    enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                   config=cfg, source_meta={})
    pos = st.open_positions()[0]
    target = date.fromisoformat(pos["target_exit_session"])
    plus1, plus3 = v2cal.add_sessions(target, 1), v2cal.add_sessions(target, 3)

    def pl(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        if ds == plus1.isoformat():
            return {"open": 100.0, "close": 108.0}
        if ds == plus3.isoformat():
            return {"open": 100.0, "close": 999.0}
        return None

    pipeline.settle_due_exits(store=st, as_of_session=v2cal.add_sessions(target, 8),
                              price_lookup=pl, config=cfg)
    closed = [p for p in st.all_positions() if p["status"] == "CLOSED"][0]
    assert closed["exit_price"] == 108.0                       # first available, NOT 999
    assert closed["exit_session"] == plus1.isoformat()


def test_17_never_searches_backwards(tmp_path):
    cfg = _cfg()
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=TUESDAY_PAPER_BALANCE)
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.liquidity import evaluate_liquidity
    ep = detect_episodes(form4_source.from_rows(_two("GG")), config=cfg)[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session, config=cfg)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq, config=cfg))
    enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                   config=cfg, source_meta={})
    pos = st.open_positions()[0]
    target = date.fromisoformat(pos["target_exit_session"])
    before = v2cal.add_sessions(target, -2)

    def pl(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        return {"open": 100.0, "close": 77.0} if ds == before.isoformat() else None

    res = pipeline.settle_due_exits(store=st, as_of_session=v2cal.add_sessions(target, 10),
                                    price_lookup=pl, config=cfg)
    # the only bar is BEFORE target -> must NOT be used; position goes unresolved
    assert st.unresolved_positions() and not [p for p in st.all_positions() if p["status"] == "CLOSED"]


# ===================== 18-20 : restart / persistence / no flatten =====================
def test_18_and_19_restart_open_and_overdue(tmp_path):
    db = str(tmp_path / "v2.db")
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_two("HH"))
    bl, pl = _mk_lookups({"HH": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    st = V2Store(db, starting_cash=TUESDAY_PAPER_BALANCE)
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)

    st2 = V2Store(db)                                    # restart mid-hold
    from talonx_v2.paper import recover
    rec = recover(st2, as_of_session=v2cal.add_sessions(ep.eligible_entry_session, 3))
    assert rec["open_positions"] == 1
    p = st2.open_positions()[0]
    assert p["episode_id"] == ep.episode_id
    assert p["target_exit_session"] == v2cal.add_sessions(ep.eligible_entry_session, 10).isoformat()

    # app down across the target day -> restart AFTER it -> overdue exit settles safely
    st3 = V2Store(db)
    over = v2cal.add_sessions(ep.eligible_entry_session, 14)
    r = pipeline.settle_due_exits(store=st3, as_of_session=over, price_lookup=pl, config=cfg)
    assert st3.n_open() == 0 and len(r.exits) == 1
    assert r.exits[0]["trading_days_held"] == 10          # held-day count is NOT reset


def test_20_no_eod_flatten(tmp_path):
    from talonx_ops.dashboard_read import DashboardReadModel  # noqa: F401
    db = str(tmp_path / "v2.db")
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_two("II"))
    bl, pl = _mk_lookups({"II": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    st = V2Store(db, starting_cash=TUESDAY_PAPER_BALANCE)
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    from talonx_v2.dashboard_read import eod_view
    v = eod_view(st, as_of_session=v2cal.add_sessions(ep.eligible_entry_session, 4))
    assert v["v2_positions_flattened_at_eod"] is False and v["n_open"] == 1


# ===================== 21-26 : shadow / telegram / dashboard =====================
def test_21_experimental_shadow_families_unchanged():
    from talonx_signals.external_boundary import EXPERIMENTAL_FAMILIES, is_external_eligible
    for f in EXPERIMENTAL_FAMILIES:
        assert is_external_eligible(f) is False


def test_22_experimental_external_boundary_still_three_condition():
    from talonx_signals.external_boundary import (
        assert_experimental_send_allowed, ExperimentalExternalBoundaryError,
    )
    with pytest.raises(ExperimentalExternalBoundaryError):
        assert_experimental_send_allowed("tuesday")


def test_23_official_telegram_v2_family_eligible_and_wording_safe():
    from talonx_signals.external_boundary import is_external_eligible
    assert is_external_eligible("insider_buy_cluster_v2") is True
    from talonx_v2.schemas import V2Alert, V2Direction
    a = V2Alert(episode_id="e", symbol="AAA", action=V2Action.BUY, direction=V2Direction.BULLISH,
                headline="INSIDER BUY CLUSTER — BULLISH / BUY — AAA",
                body="2 distinct insiders bought AAA on the open market. Paper only.")
    card = dispatch_bridge.render_telegram(a)
    low = card.lower()
    for banned in ("guaranteed", "guarantee profit", "will rise", "validated real-money"):
        assert banned not in low
    assert "paper only" in low


def test_24_dispatch_dedup_distinct_buy_sell():
    class R:
        def __init__(self): self.d = set()
        def decide(self, fam, key=""):
            from types import SimpleNamespace
            fam = fam.lower()
            elig = fam == "insider_buy_cluster_v2"
            already = (fam, key) in self.d
            return SimpleNamespace(family=fam, eligible=elig, already_delivered=already,
                                   should_send=elig and not already,
                                   to_dict=lambda: {"should_send": elig and not already,
                                                    "already_delivered": already})
    r = R()
    from talonx_v2.schemas import V2Alert, V2Direction
    buy = V2Alert(episode_id="ep", symbol="A", action=V2Action.BUY, direction=V2Direction.BULLISH,
                  headline="h", body="b")
    sell = V2Alert(episode_id="ep", symbol="A", action=V2Action.SELL, direction=V2Direction.BULLISH,
                   headline="h", body="b")
    assert dispatch_bridge.route(r, buy).should_send is True
    r.d.add(("insider_buy_cluster_v2", "ep:BUY"))
    assert dispatch_bridge.route(r, buy).already_delivered is True
    assert dispatch_bridge.route(r, sell).already_delivered is False


def test_25_dashboard_v2_section_present_and_not_experimental():
    from talonx_ops.dashboard_read import DashboardReadModel
    m = DashboardReadModel(check_processes=False)
    keys = list(m.all_sections().keys())
    assert "v2_active_strategy" in keys
    i_v2, i_val = keys.index("v2_active_strategy"), keys.index("validation")
    assert i_v2 < i_val                                   # rendered in the Active-Strategy area
    sec = m.v2_active_strategy()
    assert sec["not_experimental"] is True
    assert sec["strategy_version"] == V2_VERSION
    assert sec["real_capital"] is False and sec["shorts"] is False
    assert sec["eod_forced_flatten"] is False


def test_26_dashboard_experimental_separation_intact():
    from talonx_ops.dashboard_read import DashboardReadModel
    m = DashboardReadModel(check_processes=False)
    val = m.validation()
    # the validation section is still the Experimental one (relaxed 0.10/1/1.0)
    assert val["frozen_profile"] == {"min_atr_pct": 0.10, "confluence_score_min": 1,
                                     "min_risk_reward_ratio": 1.0}


# ===================== 27-28 : supervisor / co-process =====================
def test_27_supervisor_can_own_v2_optionally_without_touching_original():
    from talonx_ops.supervisor import default_talonx_components
    base = default_talonx_components(include_dashboard=False)
    withv2 = default_talonx_components(include_dashboard=False, include_v2=True)
    assert {c.name for c in base} == {"original", "experimental", "intelligence"}
    assert {c.name for c in withv2} == {"original", "experimental", "intelligence", "v2"}
    orig_base = next(c for c in base if c.name == "original")
    orig_v2 = next(c for c in withv2 if c.name == "original")
    assert orig_base.argv == orig_v2.argv                 # Original spec byte-identical
    assert orig_base.classification == orig_v2.classification
    v2 = next(c for c in withv2 if c.name == "v2")
    from talonx_ops.supervisor import Classification
    assert v2.classification == Classification.OPTIONAL   # failure never affects Original


def test_28_v2_live_once_tick_offline(tmp_path):
    from talonx_v2.service import V2Service
    from pathlib import Path
    cfg = _cfg(db_path=str(tmp_path / "v2.db"))
    svc = V2Service(config=cfg,
                    bar_dirs=[Path("results/task95g_broad_cross_sectional/_daily"),
                              Path("results/task107a_form4_feasibility/_prices")],
                    form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"))
    st = svc.tick(as_of=date(2026, 3, 13))
    assert st["strategy_version"] == V2_VERSION
    assert st["eod_forced_flatten"] is False
    assert st["real_capital"] is False and st["shorts"] is False
    assert st["max_concurrent"] == 20
    assert (tmp_path / "status.json").exists()
    assert svc.ready() is True                            # fresh heartbeat


# ===================== 29-37 : invariants =====================
def test_29_process_shutdown_persists_state(tmp_path):
    db = str(tmp_path / "v2.db")
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_two("JJ"))
    bl, pl = _mk_lookups({"JJ": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    st = V2Store(db, starting_cash=TUESDAY_PAPER_BALANCE)
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    del st
    st2 = V2Store(db)
    assert st2.n_open() == 1
    p = st2.open_positions()[0]
    assert p["entry_price"] and p["shares"] and p["target_exit_session"]


def test_30_no_broker_in_v2_package():
    import pkgutil
    import talonx_v2
    for m in pkgutil.iter_modules(talonx_v2.__path__):
        src = open(next(iter(talonx_v2.__path__)) + f"/{m.name}.py", encoding="utf-8").read().lower()
        # no broker CLIENT / order-execution path anywhere in the V2 lane
        for banned in ("alpaca_trade_api", "alpaca.trading", "tradeapi", "submit_order",
                       "place_order", "create_order", "broker_client"):
            assert banned not in src, f"{m.name}.py contains {banned!r}"


def test_31_no_shorts():
    assert set(a.value for a in V2Action) == {"BUY", "SELL", "HOLD"}
    assert V2Config().allow_shorts is False


def test_32_no_real_capital():
    assert V2Config().allow_real_capital is False
    V2Config().validate_frozen()


def test_33_no_paid_data_marker_present():
    txt = open("results/task109_v2_freeze/v2_strategy_contract.md", encoding="utf-8").read()
    assert "PAID_DATA_SPEND = £0" in txt


def test_34_no_strategy_semantic_drift():
    c = V2Config()
    assert (c.cluster_window_trading_days, c.min_distinct_owners, c.transaction_code,
            c.hold_trading_days, c.entry_offset_sessions, c.max_concurrent_positions,
            c.reentry_cooldown_trading_days, c.stop_loss_enabled) == (10, 2, "P", 10, 1, 20, 5, False)
    assert c.liquidity_min_median_dollar_volume == 5_000_000.0
    assert c.liquidity_min_close == 5.0


def test_35_no_v1_semantic_drift():
    from talonx_quant.config import QuantConfig
    c = QuantConfig()
    assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)


def test_36_no_task107b_outcome_retuning_hook():
    import talonx_v2.config as m
    src = open(m.__file__).read().lower()
    assert "analysis.json" not in src and "sharpe" not in src and "optimize" not in src


def test_37_staleness_guard_is_operational_not_semantic(tmp_path):
    # the guard skips STALE entries in the live service only -- it does NOT
    # change the frozen entry rule (open of first session strictly after)
    c = V2Config()
    assert c.max_entry_staleness_sessions >= 0
    assert c.entry_offset_sessions == 1                   # frozen rule untouched


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
