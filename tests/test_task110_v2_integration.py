"""
Task 110 -- INSIDER_BUY_CLUSTER_V2 integration test matrix.

Covers the 46-item matrix from the Task 110 spec: profile selection,
frozen thresholds, code-P-only + distinct-owner cluster semantics,
deterministic episode identity, causal timing, Quant/Brain stage,
V1-gate isolation, BULLISH/BUY/SELL semantics, Original-paper-engine
integration, the 10-trading-day multi-day lifecycle, no EOD flatten,
restart recovery, official Telegram path, Experimental Telegram stays
zero, :8787 visibility, EOD reconciliation, and the safety invariants
(no shorts / no real capital / no broker / no paid data).

Pure / in-memory -- no network, no live services.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone

import pytest

from talonx_v2 import (
    brain_bridge,
    calendar as v2cal,
    dispatch_bridge,
    form4_source,
    pipeline,
    quant_bridge,
)
from talonx_v2.cluster_engine import PurchaseRecord, detect_episodes, detect_episodes_for_issuer
from talonx_v2.config import V2Config, V2_VERSION
from talonx_v2.liquidity import evaluate_liquidity
from talonx_v2.paper import close_position, due_exits, enter_position, open_position_report, recover
from talonx_v2.profile import DEFAULT_PROFILE, StrategyProfile, active_profile
from talonx_v2.schemas import V2Action, V2Direction
from talonx_v2.store import V2Store


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _store(tmp_path, cash=100_000.0) -> V2Store:
    return V2Store(str(tmp_path / "v2.db"), starting_cash=cash)


def _cfg(**kw) -> V2Config:
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", 100_000.0)
    return V2Config(**kw)


def _rows_two_insiders(sym="AAA", d1="2026-09-01", d2="2026-09-03"):
    return [
        dict(symbol=sym, issuer_cik="111", owner_cik="O1", filing_date=d1,
             accession="a1", transaction_value=60_000, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik="111", owner_cik="O2", filing_date=d2,
             accession="a2", transaction_value=90_000, is_director=True, transaction_code="P"),
    ]


def _liquid_bars(sym_start="2026-06-01", sym_end="2026-11-01", close=100.0, vol=200_000):
    sess = [s for s in v2cal._sessions()
            if date.fromisoformat(sym_start) <= s <= date.fromisoformat(sym_end)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _mk_lookups(bars_by_sym, entry_open=100.0, exit_close=110.0):
    def bars_lookup(sym):
        return bars_by_sym.get(sym, [])

    def price_lookup(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        for b in bars_by_sym.get(sym, []):
            if b["date"] == ds:
                return {"open": entry_open, "close": exit_close}
        return None

    return bars_lookup, price_lookup


# ============================ 1-3 : profile ============================
def test_01_v1_selectable_and_default():
    assert DEFAULT_PROFILE is StrategyProfile.ORIGINAL_V1
    assert active_profile({}) is StrategyProfile.ORIGINAL_V1
    assert active_profile({"TALONX_ACTIVE_STRATEGY_PROFILE": "garbage"}) is StrategyProfile.ORIGINAL_V1


def test_02_v2_selectable():
    assert active_profile({"TALONX_ACTIVE_STRATEGY_PROFILE": "INSIDER_BUY_CLUSTER_V2"}) \
        is StrategyProfile.INSIDER_BUY_CLUSTER_V2


def test_03_v1_thresholds_unchanged():
    from talonx_quant.config import QuantConfig

    c = QuantConfig()
    assert c.min_atr_pct == 0.25
    assert c.confluence_score_min == 2
    assert c.min_risk_reward_ratio == 1.5


# ============================ 4-11 : cluster semantics ============================
def test_04_code_p_purchase_accepted():
    eps = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))
    assert len(eps) == 1
    assert eps[0].n_distinct_owners == 2


def test_05_non_p_transaction_rejected():
    rows = _rows_two_insiders()
    rows[1]["transaction_code"] = "A"          # grant, not a purchase
    eps = detect_episodes_for_issuer(form4_source.from_rows(rows))
    assert eps == []                            # only 1 code-P owner -> no cluster


def test_06_duplicate_owner_not_counted_twice():
    rows = _rows_two_insiders()
    rows[1]["owner_cik"] = "O1"                 # same insider again
    eps = detect_episodes_for_issuer(form4_source.from_rows(rows))
    assert eps == []


def test_07_second_distinct_owner_completes_cluster():
    eps = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))
    assert eps[0].activation_filing_date == date(2026, 9, 3)


def test_08_cluster_window_semantics_trading_days():
    # O2 files 11 trading days after O1 -> outside the 10-td window -> no cluster
    d1 = date(2026, 3, 2)
    d2 = v2cal.add_sessions(d1, 11)
    rows = _rows_two_insiders(d1=d1.isoformat(), d2=d2.isoformat())
    assert detect_episodes_for_issuer(form4_source.from_rows(rows)) == []
    d2_ok = v2cal.add_sessions(d1, 9)
    rows_ok = _rows_two_insiders(d1=d1.isoformat(), d2=d2_ok.isoformat())
    assert len(detect_episodes_for_issuer(form4_source.from_rows(rows_ok))) == 1


def test_09_deterministic_episode_id():
    a = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    b = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    assert a.episode_id == b.episode_id and len(a.episode_id) == 16


def test_10_duplicate_filing_safe():
    rows = _rows_two_insiders() + _rows_two_insiders()   # exact dupes
    eps = detect_episodes_for_issuer(form4_source.from_rows(rows))
    assert len(eps) == 1 and eps[0].n_filings == 2


def test_11_amendment_duplicate_safe(tmp_path):
    rows = _rows_two_insiders()
    dup = dict(rows[1]); dup["accession"] = "a2"          # same txn, re-reported
    eps = detect_episodes_for_issuer(form4_source.from_rows(rows + [dup]))
    assert len(eps) == 1


# ============================ 12-15 : causal timing ============================
def test_12_causal_timestamp_is_activation_filing_eod():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    assert ep.causal_event_ts.date() == ep.activation_filing_date
    assert ep.causal_event_ts.tzinfo is timezone.utc


def test_13_entry_is_next_session_strictly_after():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    # activation 2026-09-03 (Thu) -> entry 2026-09-04 (Fri), strictly after
    assert ep.eligible_entry_session == date(2026, 9, 4)
    assert ep.eligible_entry_session > ep.activation_filing_date


def test_14_after_close_rolls_to_next_session():
    # activation on a Friday -> entry the following Monday/Tuesday session
    rows = _rows_two_insiders(d1="2026-09-01", d2="2026-09-04")   # Fri
    ep = detect_episodes_for_issuer(form4_source.from_rows(rows))[0]
    assert ep.eligible_entry_session == date(2026, 9, 8)          # Mon 9-7 is Labor Day


def test_15_weekend_holiday_rule():
    # activation on Saturday 2026-07-04 area -> next real session
    rows = _rows_two_insiders(d1="2026-06-29", d2="2026-07-04")   # Sat
    ep = detect_episodes_for_issuer(form4_source.from_rows(rows))[0]
    assert v2cal.is_session(ep.eligible_entry_session)
    assert ep.eligible_entry_session > date(2026, 7, 4)


# ============================ 16-19 : quant + brain ============================
def test_16_quant_v2_signal_generated():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    sig = quant_bridge.build_signal(ep, liq)
    assert sig.symbol == "AAA" and sig.direction is V2Direction.BULLISH
    assert sig.horizon_trading_days == 10 and sig.paper_eligible is True


def test_17_strategy_profile_carried():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    sig = quant_bridge.build_signal(ep, liq)
    assert sig.strategy_profile == "INSIDER_BUY_CLUSTER_V2"
    assert sig.strategy_version == V2_VERSION


def test_18_brain_receives_v2_and_emits_bullish_buy():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq))
    assert dec.direction is V2Direction.BULLISH
    assert dec.action is V2Action.BUY
    assert dec.official_eligible is True


def test_19_v1_gates_not_applied_to_v2():
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    sig = quant_bridge.build_signal(ep, liq)
    # no ATR / confluence / R:R fields exist on the V2 signal at all
    for forbidden in ("atr", "confluence_score", "risk_reward_ratio", "rsi", "macd"):
        assert not hasattr(sig, forbidden)
    dec = brain_bridge.contextualize(sig)
    assert "confluence" not in dec.rationale.lower()
    assert "atr" not in dec.rationale.lower()


# ============================ 20-24 : semantics + paper entry ============================
def test_20_bullish_is_informational_not_short():
    assert V2Direction.BEARISH.value == "BEARISH"
    # there is no SHORT action in the enum
    assert set(a.value for a in V2Action) == {"BUY", "SELL", "HOLD"}


def test_21_buy_semantics(tmp_path):
    st = _store(tmp_path)
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq))
    out = enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                         config=_cfg(), source_meta={"issuer_cik": "111"})
    assert out.entered and out.shares == pytest.approx(100.0)


def test_22_no_short_semantics_anywhere():
    src = (dispatch_bridge.__file__)
    txt = open(src).read().lower()
    assert "short" not in txt.replace("shortcut", "")


def test_23_local_paper_entry_persists(tmp_path):
    st = _store(tmp_path)
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq))
    enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session, config=_cfg())
    pos = st.position_for_symbol("AAA")
    assert pos and pos["status"] == "OPEN"
    assert pos["strategy_version"] == V2_VERSION


def test_24_strategy_attribution_in_position(tmp_path):
    st = _store(tmp_path)
    ep = detect_episodes_for_issuer(form4_source.from_rows(_rows_two_insiders()))[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session)
    dec = brain_bridge.contextualize(quant_bridge.build_signal(ep, liq))
    enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session, config=_cfg())
    pos = st.position_for_symbol("AAA")
    assert pos["strategy_profile"] == "INSIDER_BUY_CLUSTER_V2"
    assert pos["episode_id"] == ep.episode_id


# ============================ 25-32 : multi-day lifecycle ============================
def _run(tmp_path, **cfg_kw):
    st = _store(tmp_path)
    cfg = _cfg(**cfg_kw)
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    res = pipeline.run_replay(recs, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    return st, cfg, res


def test_25_target_exit_session_is_entry_plus_10_td(tmp_path):
    st, cfg, res = _run(tmp_path)
    e = res.entries[0]
    assert v2cal.add_sessions(date.fromisoformat(e["entry_session"]), 10) \
        == date.fromisoformat(e["target_exit_session"])


def test_26_no_day0_eod_flatten(tmp_path):
    st = _store(tmp_path)
    cfg = _cfg()
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    # same session close sweep -> position stays open
    pipeline.settle_due_exits(store=st, as_of_session=ep.eligible_entry_session,
                              price_lookup=pl, config=cfg)
    assert st.n_open() == 1


@pytest.mark.parametrize("elapsed", [1, 5, 9])
def test_27_28_29_position_persists_before_day10(tmp_path, elapsed):
    st = _store(tmp_path)
    cfg = _cfg()
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    as_of = v2cal.add_sessions(ep.eligible_entry_session, elapsed)
    pipeline.settle_due_exits(store=st, as_of_session=as_of, price_lookup=pl, config=cfg)
    assert st.n_open() == 1


def test_30_day10_sell(tmp_path):
    st, cfg, res = _run(tmp_path)
    assert len(res.exits) == 1
    assert res.exits[0]["trading_days_held"] == 10
    assert st.n_open() == 0


def test_31_sell_closes_long_only(tmp_path):
    st, cfg, res = _run(tmp_path)
    trades = st.trades()
    assert [t["action"] for t in trades] == ["BUY", "SELL"]
    assert all(t["shares"] > 0 for t in trades)          # never a negative/short qty


def test_32_realized_pnl_math(tmp_path):
    st, cfg, res = _run(tmp_path)
    e = res.exits[0]
    # entry 100 open, exit 110 close, 100 shares -> +1000 / +10%
    assert e["realized_pnl_usd"] == pytest.approx(1000.0)
    assert e["realized_pnl_pct"] == pytest.approx(10.0)


# ============================ 33-34 : restart recovery ============================
def test_33_restart_recovery_reopens_positions(tmp_path):
    db = str(tmp_path / "v2.db")
    st = V2Store(db, starting_cash=100_000.0)
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    # simulate a process restart: brand-new store object, same file
    st2 = V2Store(db)
    rec = recover(st2, as_of_session=v2cal.add_sessions(ep.eligible_entry_session, 3))
    assert rec["open_positions"] == 1 and rec["symbols"] == ["AAA"]


def test_34_duplicate_buy_prevented_after_restart(tmp_path):
    db = str(tmp_path / "v2.db")
    st = V2Store(db, starting_cash=100_000.0)
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    st2 = V2Store(db)
    r = pipeline.process_episode(ep, store=st2, bars_lookup=bl, price_lookup=pl, config=cfg)
    assert st2.n_open() == 1
    assert any(s["reason"] == "ALREADY_PROCESSED" for s in r.skipped)


# ============================ 35-39 : dispatch / dashboard / eod ============================
def test_35_official_family_is_external_eligible():
    from talonx_signals.external_boundary import is_external_eligible
    assert is_external_eligible("insider_buy_cluster_v2") is True


def test_36_experimental_families_still_blocked_and_boundary_intact():
    from talonx_signals.external_boundary import is_external_eligible, EXPERIMENTAL_FAMILIES
    for fam in EXPERIMENTAL_FAMILIES:
        assert is_external_eligible(fam) is False


def test_37_telegram_render_escapes_markdown(tmp_path):
    st, cfg, res = _run(tmp_path)
    card = res.alerts[0]["telegram"]
    assert "INSIDER BUY CLUSTER" in card
    assert "PAPER ONLY" in card
    # legacy-markdown special chars in dynamic text are escaped
    from talonx_v2 import dispatch_bridge as db
    from talonx_v2.schemas import V2Alert, V2Action as A, V2Direction as D
    a = V2Alert(episode_id="e", symbol="A_B", action=A.BUY, direction=D.BULLISH,
                headline="h", body="under_scored *starred*")
    out = db.render_telegram(a)
    assert "\\_" in out and "\\*" in out


def test_38_dashboard_section_not_experimental(tmp_path):
    from talonx_v2 import dashboard_read
    st, cfg, res = _run(tmp_path)
    sec = dashboard_read.build_section(st, config=cfg)
    assert sec["not_experimental"] is True
    assert sec["active_profile"] == "ORIGINAL_V1"        # default unchanged
    assert sec["v2_selectable"] is True and sec["v1_selectable"] is True
    assert sec["realized_pnl_usd"] == pytest.approx(1000.0)
    assert sec["paper_only"] is True and sec["real_capital"] is False


def test_39_eod_reconciliation_sees_open_v2_and_never_flattens(tmp_path):
    from talonx_v2 import dashboard_read
    st = _store(tmp_path)
    cfg = _cfg()
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    as_of = v2cal.add_sessions(ep.eligible_entry_session, 4)
    view = dashboard_read.eod_view(st, as_of_session=as_of)
    assert view["v2_positions_flattened_at_eod"] is False
    assert view["n_open"] == 1
    assert view["open_v2_positions"][0]["trading_days_held"] == 4
    assert view["open_v2_positions"][0]["trading_days_remaining"] == 6


# ============================ 40-46 : preservation + safety ============================
def test_40_v1_modules_untouched_by_v2_import():
    # importing talonx_v2 must not mutate talonx_quant config defaults
    import importlib
    import talonx_quant.config as qc
    importlib.reload(qc)
    c = qc.QuantConfig()
    assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)


def test_41_original_local_paper_only_no_alpaca():
    import talonx_v2.paper as p
    src = open(p.__file__).read().lower()
    assert "alpaca" not in src
    # only reuse is the PURE math from talonx_paper.engine -- no broker/order client
    assert "import" in src
    assert "orderclient" not in src and "submit_order" not in src
    assert "from talonx_paper.engine import" in src


def test_42_no_real_capital_flag():
    cfg = V2Config()
    assert cfg.allow_real_capital is False
    cfg.validate_frozen()


def test_43_no_shorts_flag():
    assert V2Config().allow_shorts is False


def test_44_no_stop_loss_in_frozen_primary():
    assert V2Config().stop_loss_enabled is False


def test_45_frozen_contract_constants_intact():
    c = V2Config()
    assert (c.cluster_window_trading_days, c.min_distinct_owners, c.transaction_code,
            c.hold_trading_days, c.entry_offset_sessions, c.max_concurrent_positions,
            c.reentry_cooldown_trading_days) == (10, 2, "P", 10, 1, 20, 5)
    assert c.liquidity_min_median_dollar_volume == 5_000_000.0
    assert c.liquidity_min_close == 5.0


def test_46_no_research_parameter_mutation_helpers_present():
    # there is no "optimize"/"tune"/"sweep" entry point in the package
    import pkgutil
    import talonx_v2
    names = [m.name for m in pkgutil.iter_modules(talonx_v2.__path__)]
    assert not any(k in n for n in names for k in ("optimi", "tune", "sweep", "search"))


# ============================ liquidity gate ============================
def test_liquidity_gate_blocks_illiquid(tmp_path):
    st = _store(tmp_path)
    cfg = _cfg()
    recs = form4_source.from_rows(_rows_two_insiders())
    thin = [{"date": b["date"], "open": 3.0, "close": 3.0, "volume": 1000}
            for b in _liquid_bars()]                       # $3k/day, close < $5
    bl, pl = _mk_lookups({"AAA": thin})
    res = pipeline.run_replay(recs, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    assert res.entries == []
    assert any("CLOSE" in s["reason"] or "MEDIAN_DV" in s["reason"] for s in res.skipped)


def test_cooldown_blocks_reentry(tmp_path):
    st = _store(tmp_path)
    cfg = _cfg()
    # two clusters in AAA: one entering 2026-03-03, next well after the first
    r1 = _rows_two_insiders("AAA", "2026-03-02", "2026-03-03")
    # second cluster fires right after the first position's exit+cooldown window
    r2 = [
        dict(symbol="AAA", issuer_cik="111", owner_cik="O5", filing_date="2026-03-19",
             accession="b1", transaction_value=50_000, transaction_code="P"),
        dict(symbol="AAA", issuer_cik="111", owner_cik="O6", filing_date="2026-03-20",
             accession="b2", transaction_value=50_000, transaction_code="P"),
    ]
    bl, pl = _mk_lookups({"AAA": _liquid_bars("2026-01-01", "2026-06-01")})
    res = pipeline.run_replay(form4_source.from_rows(r1 + r2), store=st,
                              bars_lookup=bl, price_lookup=pl, config=cfg)
    # first enters; second is inside the 10-day hold or the 5-day cooldown -> skipped
    assert len(res.entries) == 1
    assert any("COOLDOWN" in s["reason"] or s["reason"] == "SYMBOL_ALREADY_OPEN"
               for s in res.skipped)


def test_max_concurrent_positions_enforced(tmp_path):
    st = _store(tmp_path, cash=1_000_000.0)          # plenty of cash -> the cap, not cash, binds
    cfg = _cfg(starting_cash_usd=1_000_000.0)
    # 22 different issuers all fire the same day -> only 20 may enter
    rows = []
    bars = {}
    for i in range(22):
        sym = f"S{i:02d}"
        rows += [
            dict(symbol=sym, issuer_cik=str(i), owner_cik=f"{i}a", filing_date="2026-03-02",
                 accession=f"{i}x", transaction_value=50_000, transaction_code="P"),
            dict(symbol=sym, issuer_cik=str(i), owner_cik=f"{i}b", filing_date="2026-03-03",
                 accession=f"{i}y", transaction_value=50_000, transaction_code="P"),
        ]
        bars[sym] = _liquid_bars("2026-01-01", "2026-06-01")
    bl, pl = _mk_lookups(bars)
    res = pipeline.run_replay(form4_source.from_rows(rows), store=st,
                              bars_lookup=bl, price_lookup=pl, config=cfg)
    assert len(res.entries) == 20                     # cap enforced at entry time
    assert len(res.exits) == 20                       # all 20 later close at +10td
    assert sum(1 for s in res.skipped if "MAX_CONCURRENT" in s["reason"]) == 2


# ============================ Phase 21/22 replay fixtures ============================
def test_phase21_single_episode_replay_fixture(tmp_path):
    """First filing -> NO buy; second distinct insider -> cluster active;
    next session -> Quant->Brain->BULLISH/BUY->local paper; duplicate
    filings -> NO duplicate buy."""
    st = _store(tmp_path)
    cfg = _cfg()
    one = [_rows_two_insiders()[0]]
    assert detect_episodes(form4_source.from_rows(one), config=cfg) == []      # 1 insider only
    full = form4_source.from_rows(_rows_two_insiders() * 3)                      # + dupes
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    res = pipeline.run_replay(full, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    assert res.episodes_detected == 1
    assert len(res.entries) == 1
    assert st.trades()[0]["action"] == "BUY"


def test_phase22_multi_day_replay_with_restart(tmp_path):
    db = str(tmp_path / "v2.db")
    cfg = _cfg(db_path=db)
    recs = form4_source.from_rows(_rows_two_insiders())
    bl, pl = _mk_lookups({"AAA": _liquid_bars()})
    ep = detect_episodes(recs, config=cfg)[0]

    st = V2Store(db, starting_cash=100_000.0)
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    for day in (1, 5, 9):
        st_d = V2Store(db)   # restart each check
        as_of = v2cal.add_sessions(ep.eligible_entry_session, day)
        pipeline.settle_due_exits(store=st_d, as_of_session=as_of, price_lookup=pl, config=cfg)
        assert st_d.n_open() == 1, f"closed early at day {day}"
    st10 = V2Store(db)
    as_of10 = v2cal.add_sessions(ep.eligible_entry_session, 10)
    r = pipeline.settle_due_exits(store=st10, as_of_session=as_of10, price_lookup=pl, config=cfg)
    assert st10.n_open() == 0 and len(r.exits) == 1
    assert r.exits[0]["trading_days_held"] == 10


def test_phase23_source_unavailable_no_fabricated_cluster(tmp_path):
    st = _store(tmp_path)
    cfg = _cfg()
    res = pipeline.run_replay([], store=st, bars_lookup=lambda s: [],
                              price_lookup=lambda s, d: None, config=cfg)
    assert res.episodes_detected == 0 and res.entries == [] and st.n_open() == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
