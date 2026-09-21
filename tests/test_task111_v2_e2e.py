"""
Task 111 -- FULL OFFLINE END-TO-END REPLAY QUALIFICATION for
INSIDER_BUY_CLUSTER_V2.

Validates the ACTUAL integrated path:

  Form 4 -> V2 cluster -> V2 Quant publication -> V2 Brain -> BUY
  -> local paper -> multi-day persistence -> SELL -> official dispatch
  -> :8787 / EOD

Items from results/task110_v2_integration/task111_handoff.md:
  (2) Redis-transport E2E -- publish V2* on talonx:v2:* and drive a subscriber
  (3) interleaved-with-Original: Original strategy fingerprint byte-identical
  (4) restart under load across a multi-issuer book
  (5) official dispatch dedup (BUY vs SELL distinct, no double-send)
  (6) dashboard render: V2 slots under "Active Strategy", not Experimental

Requires a local Redis for the transport test (skipped cleanly if absent).
No real capital, no broker, no shorts, no Experimental Telegram.
"""
from __future__ import annotations

from datetime import date

import pytest

from talonx_v2 import (
    brain_bridge,
    calendar as v2cal,
    dispatch_bridge,
    form4_source,
    pipeline,
    quant_bridge,
)
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.liquidity import evaluate_liquidity
from talonx_v2.schemas import V2Action, V2Alert, V2Decision, V2Direction, V2QuantSignal
from talonx_v2.store import V2Store


# --------------------------------------------------------------------------
def _cfg(**kw):
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", 1_000_000.0)
    return V2Config(**kw)


def _liquid_bars(a="2026-01-01", b="2026-12-01", close=100.0, vol=200_000):
    sess = [s for s in v2cal._sessions()
            if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _two(sym, d1, d2):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
             accession=sym + "a1", transaction_value=60_000, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
             accession=sym + "a2", transaction_value=90_000, is_director=True, transaction_code="P"),
    ]


def _mk_lookups(bars_by_sym, entry_open=100.0, exit_close=112.0):
    def bl(sym):
        return bars_by_sym.get(sym, [])

    def pl(sym, d):
        ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
        for x in bars_by_sym.get(sym, []):
            if x["date"] == ds:
                return {"open": entry_open, "close": exit_close}
        return None

    return bl, pl


# ======================= (3) Original fingerprint byte-identical =======================
def test_item3_original_strategy_fingerprint_unchanged():
    import talonx_v2  # noqa: F401  -- importing the V2 lane must not perturb Original
    from talonx_backtest.reproducibility import get_strategy_version

    # frozen Original strategy fingerprint (talonx_quant/{strategy,indicators,
    # config,session,consumer}.py) -- byte-identical since well before V2 work
    assert get_strategy_version() == "2ae6216bca70"


def test_item3_v2_files_not_in_the_frozen_fingerprint_set():
    from talonx_backtest.reproducibility import _STRATEGY_FILES

    assert not any("talonx_v2" in str(p) for p in _STRATEGY_FILES)


def test_item3_setting_v2_profile_does_not_touch_v1_config():
    import os
    from talonx_quant.config import QuantConfig

    os.environ["TALONX_ACTIVE_STRATEGY_PROFILE"] = "INSIDER_BUY_CLUSTER_V2"
    try:
        c = QuantConfig()
        assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)
    finally:
        os.environ.pop("TALONX_ACTIVE_STRATEGY_PROFILE", None)


# ======================= full integrated single-episode path =======================
def test_full_path_form4_to_sell(tmp_path):
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=1_000_000.0)
    cfg = _cfg()
    recs = form4_source.from_rows(_two("AAA", "2026-03-02", "2026-03-04"))
    bars = {"AAA": _liquid_bars()}
    bl, pl = _mk_lookups(bars)

    # stage 1: Form4 -> cluster
    eps = detect_episodes(recs, config=cfg)
    assert len(eps) == 1
    ep = eps[0]

    # stage 2: cluster -> liquidity -> V2 Quant publication
    liq = evaluate_liquidity(bl("AAA"), entry_session=ep.eligible_entry_session, config=cfg)
    sig = quant_bridge.build_signal(ep, liq, config=cfg)
    assert isinstance(sig, V2QuantSignal) and sig.direction is V2Direction.BULLISH

    # stage 3: V2 Brain
    dec = brain_bridge.contextualize(sig)
    assert isinstance(dec, V2Decision) and dec.action is V2Action.BUY

    # stage 4-6: BUY -> local paper -> multi-day persistence
    res = pipeline.run_replay(recs, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    assert len(res.entries) == 1 and len(res.exits) == 1
    # stage 7: SELL at +10 td
    assert res.exits[0]["trading_days_held"] == 10
    trades = st.trades()
    assert [t["action"] for t in trades] == ["BUY", "SELL"]
    # stage 8: official dispatch card rendered for both
    actions = [a["action"] for a in res.alerts]
    assert actions == ["BUY", "SELL"]


# ======================= (5) official dispatch dedup =======================
class _FakeRouter:
    """Mimics talonx_ops.official_dispatch.OfficialExternalRouter.decide
    with an in-memory delivered set."""

    OFFICIAL_PATH = "official"
    NO_PATH = "none"

    def __init__(self):
        self.delivered: set[tuple[str, str]] = set()

    def decide(self, family, dedup_key=""):
        from types import SimpleNamespace
        fam = (family or "").strip().lower()
        eligible = fam == "insider_buy_cluster_v2"
        already = (fam, dedup_key) in self.delivered
        d = SimpleNamespace(
            family=fam, eligible=eligible, already_delivered=already,
            path=self.OFFICIAL_PATH if (eligible and not already) else self.NO_PATH,
            reason="", should_send=eligible and not already,
            to_dict=lambda: {"family": fam, "eligible": eligible,
                             "already_delivered": already,
                             "should_send": eligible and not already},
        )
        return d

    def mark(self, family, dedup_key):
        self.delivered.add(((family or "").strip().lower(), dedup_key))


def test_item5_dispatch_dedup_buy_and_sell_distinct(tmp_path):
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=1_000_000.0)
    cfg = _cfg()
    router = _FakeRouter()
    recs = form4_source.from_rows(_two("BBB", "2026-03-02", "2026-03-04"))
    bl, pl = _mk_lookups({"BBB": _liquid_bars()})
    res = pipeline.run_replay(recs, store=st, bars_lookup=bl, price_lookup=pl,
                              config=cfg, router=router)
    routes = [a["routing"] for a in res.alerts]
    assert [a["action"] for a in res.alerts] == ["BUY", "SELL"]
    # both the BUY and the SELL card are eligible + not-yet-delivered -> both send
    assert routes[0]["should_send"] is True and routes[1]["should_send"] is True
    # and they carry DISTINCT dedup keys ("<episode_id>:BUY" vs ":SELL") so
    # delivering the BUY never suppresses the later SELL
    ep_id = detect_episodes(recs, config=cfg)[0].episode_id
    router.mark("insider_buy_cluster_v2", f"{ep_id}:BUY")
    buy_alert = V2Alert(episode_id=ep_id, symbol="BBB", action=V2Action.BUY,
                        direction=V2Direction.BULLISH, headline="h", body="b")
    sell_alert = V2Alert(episode_id=ep_id, symbol="BBB", action=V2Action.SELL,
                         direction=V2Direction.BULLISH, headline="h", body="b")
    assert dispatch_bridge.route(router, buy_alert).already_delivered is True
    assert dispatch_bridge.route(router, sell_alert).already_delivered is False


def _dedup_of(alert_rec):
    # the alert card text encodes the action; the router dedup key is
    # "<episode_id>:<action>" -- see dispatch_bridge.route
    return alert_rec["action"]


def test_item5_same_alert_twice_is_deduped(tmp_path):
    router = _FakeRouter()
    alert = V2Alert(episode_id="ep1", symbol="CCC", action=V2Action.BUY,
                    direction=V2Direction.BULLISH, headline="h", body="b")
    d1 = dispatch_bridge.route(router, alert)
    assert d1.should_send is True
    router.mark("insider_buy_cluster_v2", "ep1:BUY")
    d2 = dispatch_bridge.route(router, alert)
    assert d2.should_send is False and d2.already_delivered is True


# ======================= (4) restart under load =======================
def test_item4_restart_under_load_multi_issuer(tmp_path):
    db = str(tmp_path / "v2.db")
    cfg = _cfg(db_path=db)
    rows, bars = [], {}
    for i in range(8):
        sym = f"L{i}"
        rows += _two(sym, "2026-03-02", "2026-03-04")
        bars[sym] = _liquid_bars()
    recs = form4_source.from_rows(rows)
    bl, pl = _mk_lookups(bars)
    eps = detect_episodes(recs, config=cfg)
    assert len(eps) == 8

    # enter all 8 (fresh store), then restart-check at day 0/+3/+9, exit at +10
    st = V2Store(db, starting_cash=1_000_000.0)
    for ep in eps:
        pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    entry_session = eps[0].eligible_entry_session
    for day in (0, 3, 9):
        st_d = V2Store(db)                         # simulate a process restart
        as_of = v2cal.add_sessions(entry_session, day)
        pipeline.settle_due_exits(store=st_d, as_of_session=as_of, price_lookup=pl, config=cfg)
        assert st_d.n_open() == 8, f"lost positions at day {day}"
        # re-processing the same episodes must NOT double-buy
        r = ProcessAll(st_d, eps, bl, pl, cfg)
        assert r == 0
    st10 = V2Store(db)
    as_of10 = v2cal.add_sessions(entry_session, 10)
    res = pipeline.settle_due_exits(store=st10, as_of_session=as_of10, price_lookup=pl, config=cfg)
    assert st10.n_open() == 0 and len(res.exits) == 8
    assert all(e["trading_days_held"] == 10 for e in res.exits)


def ProcessAll(store, eps, bl, pl, cfg) -> int:
    new_entries = 0
    for ep in eps:
        r = pipeline.process_episode(ep, store=store, bars_lookup=bl, price_lookup=pl, config=cfg)
        new_entries += len(r.entries)
    return new_entries


# ======================= (6) dashboard render placement =======================
def test_item6_dashboard_section_under_active_strategy(tmp_path):
    from talonx_v2 import dashboard_read
    st = V2Store(str(tmp_path / "v2.db"), starting_cash=1_000_000.0)
    cfg = _cfg()
    recs = form4_source.from_rows(_two("DDD", "2026-03-02", "2026-03-04"))
    bl, pl = _mk_lookups({"DDD": _liquid_bars()})
    pipeline.run_replay(recs, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)

    sec = dashboard_read.build_section(st, config=cfg)
    assert sec["panel"] == "ACTIVE STRATEGY (Original flow)"
    assert sec["not_experimental"] is True
    assert sec["v2_is_active_profile"] is False        # default profile unchanged
    assert sec["active_profile"] == "ORIGINAL_V1"
    assert sec["v1_selectable"] and sec["v2_selectable"]
    assert sec["closed_positions"] == 1
    assert sec["realized_pnl_usd"] == pytest.approx(1200.0)   # 100->112, 100 sh
    assert sec["paper_only"] is True and sec["real_capital"] is False

    eod = dashboard_read.eod_view(st, as_of_session=date(2026, 3, 20))
    assert eod["v2_positions_flattened_at_eod"] is False


# ======================= (2) Redis transport round-trip =======================
def _has_redis() -> bool:
    try:
        import redis
        redis.Redis.from_url("redis://localhost:6379/0").ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_redis(), reason="no local Redis")
def test_item2_redis_wire_contracts_roundtrip():
    from talonx_v2.bus import V2Bus

    bus = V2Bus()
    ps = bus.subscribe(bus.cfg.redis_channel_signal, bus.cfg.redis_channel_decision,
                       bus.cfg.redis_channel_alert, bus.cfg.redis_channel_trade)

    recs = form4_source.from_rows(_two("EEE", "2026-03-02", "2026-03-04"))
    cfg = _cfg()
    ep = detect_episodes(recs, config=cfg)[0]
    liq = evaluate_liquidity(_liquid_bars(), entry_session=ep.eligible_entry_session, config=cfg)
    sig = quant_bridge.build_signal(ep, liq, config=cfg)
    dec = brain_bridge.contextualize(sig)
    alert = dispatch_bridge.build_alert(dec, entry_session=ep.eligible_entry_session,
                                        target_exit_session=v2cal.add_sessions(ep.eligible_entry_session, 10))
    from talonx_v2.schemas import V2PaperTrade
    tr = V2PaperTrade(trade_id=1, episode_id=ep.episode_id, symbol="EEE", action=V2Action.BUY,
                      execution_price=100.0, shares=100.0, position_cost=10_000.0,
                      entry_session=ep.eligible_entry_session,
                      target_exit_session=v2cal.add_sessions(ep.eligible_entry_session, 10),
                      portfolio_cash_after=990_000.0)

    bus.publish_signal(sig)
    bus.publish_decision(dec)
    bus.publish_alert(alert)
    bus.publish_trade(tr)

    got = list(bus.listen(ps, count=4, timeout=5.0))
    kinds = {type(x).__name__ for x in got}
    assert kinds == {"V2QuantSignal", "V2Decision", "V2Alert", "V2PaperTrade"}
    # round-tripped values survive JSON
    rsig = next(x for x in got if type(x).__name__ == "V2QuantSignal")
    assert rsig.episode_id == ep.episode_id and rsig.symbol == "EEE"
    assert rsig.direction is V2Direction.BULLISH
    rdec = next(x for x in got if type(x).__name__ == "V2Decision")
    assert rdec.action is V2Action.BUY
    ps.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
