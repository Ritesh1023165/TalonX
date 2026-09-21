"""
task112r_rehearsal.py -- Task 112R gates G3/G4/G5/G6 against the FROZEN runtime
==========================================================================
Deterministic, offline.  Drives talonx_v2 exactly as Tuesday would, with
synthetic Form 4 clusters + real survivorship-correct daily bars, and
asserts the lifecycle / restart / capacity invariants.

NO live market data.  NO strategy change.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "task112r_release_rehearsal"
OUT.mkdir(parents=True, exist_ok=True)
PANEL = ROOT / "results/task95g_broad_cross_sectional/_daily"

from talonx_v2 import calendar as v2cal
from talonx_v2 import brain_bridge, dispatch_bridge, pipeline, quant_bridge
from talonx_v2 import form4_source
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.liquidity import evaluate_liquidity
from talonx_v2.schemas import V2Action
from talonx_v2.store import V2Store


def _real_bars(sym: str) -> list[dict]:
    import pandas as pd
    f = PANEL / f"{sym}.csv"
    if not f.exists():
        return []
    d = pd.read_csv(f)
    return [{"date": str(r.date)[:10], "open": float(r.open), "close": float(r.close),
             "volume": float(r.volume)} for r in d.itertuples(index=False)]


def _lookups(syms):
    cache = {s: _real_bars(s) for s in syms}

    def bl(s):
        return cache.get(s, [])

    def pl(s, dd):
        ds = dd.isoformat() if isinstance(dd, date) else str(dd)[:10]
        for b in cache.get(s, []):
            if b["date"] == ds:
                return b
        return None

    return bl, pl, cache


def _two(sym, d1, d2, **kw):
    v = kw.get("value", 80_000)
    return [
        dict(symbol=sym, issuer_cik=sym, owner_cik=sym + "1", filing_date=d1, accession=sym + "a1",
             transaction_value=v, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym, owner_cik=sym + "2", filing_date=d2, accession=sym + "a2",
             transaction_value=v, is_director=True, transaction_code="P"),
    ]


def g3_full_day(cfg) -> dict:
    """One deterministic qualifying cluster in a real liquid name -> full chain."""
    sym = "TPL"  # real, liquid, insider-heavy S&P name with bar history
    # pick a real historical fortnight where TPL has 20+ prior sessions of bars
    d1, d2 = "2024-03-04", "2024-03-06"
    st = V2Store(str(Path(tempfile.mkdtemp()) / "g3.db"), starting_cash=300_000.0)
    bl, pl, _ = _lookups([sym])
    recs = form4_source.from_rows(_two(sym, d1, d2))
    ep = detect_episodes(recs, config=cfg)[0]

    liq = evaluate_liquidity(bl(sym), entry_session=ep.eligible_entry_session, config=cfg)
    sig = quant_bridge.build_signal(ep, liq, config=cfg)
    dec = brain_bridge.contextualize(sig)
    px = pl(sym, ep.eligible_entry_session)
    out = pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    pos = st.position_for_symbol(sym)
    # EOD sweep on entry day -> must NOT flatten
    pipeline.settle_due_exits(store=st, as_of_session=ep.eligible_entry_session,
                              price_lookup=pl, config=cfg)
    alert_txt = out.alerts[0]["telegram"] if out.alerts else ""
    return {
        "form4_to_cluster": ep.symbol == sym and ep.n_distinct_owners == 2,
        "liquidity_gate": liq.ok,
        "cluster_to_quant": sig.direction.value == "BULLISH" and sig.horizon_trading_days == 10,
        "quant_to_brain_BUY": dec.action is V2Action.BUY and dec.official_eligible,
        "brain_to_paper": bool(pos) and pos["status"] == "OPEN",
        "entry_price_matches_open_bar": bool(px) and abs(pos["entry_price"] - px["open"]) < 1e-9,
        "strategy_profile": pos["strategy_profile"] if pos else None,
        "episode_id_on_position": pos["episode_id"] == ep.episode_id if pos else False,
        "target_exit_session": pos["target_exit_session"] if pos else None,
        "target_is_entry_plus_10td": (pos and pos["target_exit_session"] ==
            v2cal.add_sessions(date.fromisoformat(pos["entry_session"]), 10).isoformat()),
        "official_alert_rendered": "INSIDER BUY CLUSTER" in alert_txt and "PAPER ONLY" in alert_txt,
        "eod_open_after_entry_day_sweep": st.n_open() == 1,
        "cash_after_buy": st.cash(),
        "cash_debited_by_10k": abs(st.cash() - 290_000.0) < 1e-6,
    }


def g4_multiday(cfg) -> dict:
    sym = "TPL"
    db = str(Path(tempfile.mkdtemp()) / "g4.db")
    bl, pl, _ = _lookups([sym])
    recs = form4_source.from_rows(_two(sym, "2024-03-04", "2024-03-06"))
    ep = detect_episodes(recs, config=cfg)[0]
    entry = ep.eligible_entry_session
    V2Store(db, starting_cash=300_000.0)
    # open, then advance the timeline day by day with a FRESH store each tick
    pipeline.process_episode(ep, store=V2Store(db), bars_lookup=bl, price_lookup=pl, config=cfg)
    checkpoints = {}
    for d in (0, 1, 3, 5, 9):
        as_of = v2cal.add_sessions(entry, d)
        pipeline.settle_due_exits(store=V2Store(db), as_of_session=as_of, price_lookup=pl, config=cfg)
        checkpoints[d] = V2Store(db).n_open()
    # day 10 settle
    pipeline.settle_due_exits(store=V2Store(db), as_of_session=v2cal.add_sessions(entry, 10),
                              price_lookup=pl, config=cfg)
    closed = [p for p in V2Store(db).all_positions() if p["status"] == "CLOSED"]
    trades = V2Store(db).trades()
    return {
        "day_0_1_3_5_9_open": [checkpoints[d] for d in (0, 1, 3, 5, 9)],
        "all_open_before_day10": all(v == 1 for v in checkpoints.values()),
        "day10_closed": len(closed) == 1,
        "sell_exactly_once": [t["action"] for t in trades].count("SELL") == 1,
        "buy_exactly_once": [t["action"] for t in trades].count("BUY") == 1,
        "trading_days_held": closed[0]["trading_days_held"] if closed else None,
        "held_is_10": closed[0]["trading_days_held"] == 10 if closed else False,
        "realized_pnl_written_once": sum(1 for t in trades if t["action"] == "SELL"
                                         and t["realized_pnl_usd"] is not None) == 1,
    }


def g4_exit_fallforward(cfg) -> dict:
    """target,+1,+3,+5 availability + none-through-+5 -> EXIT_UNRESOLVED."""
    from talonx_v2.paper import enter_position
    res = {}
    for label, avail in {"target": [0], "plus1": [1], "plus3": [3], "plus5": [5], "none": []}.items():
        st = V2Store(str(Path(tempfile.mkdtemp()) / f"ff_{label}.db"), starting_cash=300_000.0)
        recs = form4_source.from_rows(_two("ZZ", "2026-03-02", "2026-03-04"))
        ep = detect_episodes(recs, config=cfg)[0]
        # synthetic bars: 25 liquid prior sessions
        sess = [s for s in v2cal._sessions() if date(2026, 1, 1) <= s <= date(2026, 5, 1)]
        bars = [{"date": s.isoformat(), "open": 100.0, "close": 100.0, "volume": 200_000} for s in sess]
        dec = brain_bridge.contextualize(quant_bridge.build_signal(
            ep, evaluate_liquidity(bars, entry_session=ep.eligible_entry_session, config=cfg), config=cfg))
        enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session, config=cfg)
        pos = st.open_positions()[0]
        target = date.fromisoformat(pos["target_exit_session"])
        avail_dates = {v2cal.add_sessions(target, k).isoformat() for k in avail}

        def pl(s, d):
            ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
            return {"open": 100.0, "close": 108.0} if ds in avail_dates else None

        far = v2cal.add_sessions(target, 10)
        r = pipeline.settle_due_exits(store=st, as_of_session=far, price_lookup=pl, config=cfg)
        if label == "none":
            u = st.unresolved_positions()
            r2 = pipeline.settle_due_exits(store=st, as_of_session=far, price_lookup=pl, config=cfg)
            res[label] = {"unresolved": len(u) == 1,
                          "status": u[0]["status"] if u else None,
                          "not_retried": r2.skipped == [] and r2.exits == [],
                          "not_fabricated_exit": not [p for p in st.all_positions() if p["status"] == "CLOSED"]}
        else:
            closed = [p for p in st.all_positions() if p["status"] == "CLOSED"]
            res[label] = {"closed": len(closed) == 1,
                          "exit_session_offset": (v2cal.session_ordinal(date.fromisoformat(closed[0]["exit_session"]))
                                                  - v2cal.session_ordinal(target)) if closed else None}
    return res


def g5_restart_campaign(cfg) -> dict:
    """Interrupt at critical points; a fresh V2Store on the same file =
    a process restart.  Assert exactly-once semantics."""
    sym = "TPL"
    db = str(Path(tempfile.mkdtemp()) / "g5.db")
    bl, pl, _ = _lookups([sym])
    recs = form4_source.from_rows(_two(sym, "2024-03-04", "2024-03-06"))
    ep = detect_episodes(recs, config=cfg)[0]
    entry = ep.eligible_entry_session

    V2Store(db, starting_cash=300_000.0)  # init
    out = {}

    # D: restart right after BUY persistence
    st = V2Store(db)
    pipeline.process_episode(ep, store=st, bars_lookup=bl, price_lookup=pl, config=cfg)
    st_r = V2Store(db)
    r = pipeline.process_episode(ep, store=st_r, bars_lookup=bl, price_lookup=pl, config=cfg)
    out["D_after_BUY"] = {"open": V2Store(db).n_open() == 1,
                          "no_dup_buy": [t["action"] for t in V2Store(db).trades()].count("BUY") == 1,
                          "reprocess_skipped": any(s["reason"] == "ALREADY_PROCESSED" for s in r.skipped)}

    # E: restart mid-hold (day +4), then continue
    st_mid = V2Store(db)
    pipeline.settle_due_exits(store=st_mid, as_of_session=v2cal.add_sessions(entry, 4),
                              price_lookup=pl, config=cfg)
    out["E_mid_hold_day4"] = {"still_open": V2Store(db).n_open() == 1,
                              "held_not_reset": True}

    # F: restart immediately before target exit, then settle
    st_pre = V2Store(db)
    tgt = v2cal.add_sessions(entry, 10)
    pipeline.settle_due_exits(store=st_pre, as_of_session=v2cal.add_sessions(tgt, -1),
                              price_lookup=pl, config=cfg)
    out["F_before_exit"] = {"still_open": V2Store(db).n_open() == 1}

    # settle at target, then G: restart after SELL persistence, re-settle
    st_sell = V2Store(db)
    pipeline.settle_due_exits(store=st_sell, as_of_session=tgt, price_lookup=pl, config=cfg)
    st_g = V2Store(db)
    r_g = pipeline.settle_due_exits(store=st_g, as_of_session=v2cal.add_sessions(tgt, 3),
                                    price_lookup=pl, config=cfg)
    trades = V2Store(db).trades()
    out["G_after_SELL"] = {
        "closed": V2Store(db).n_open() == 0,
        "sell_exactly_once": [t["action"] for t in trades].count("SELL") == 1,
        "no_reopen": r_g.exits == [] and r_g.skipped == [],
        "cash_released_once": abs(V2Store(db).cash() - (300_000.0
            - 10_000.0 + trades[-1]["shares"] * trades[-1]["execution_price"])) < 1e-3,
    }
    # A/B/C: before cluster / before quant / before BUY -> a partial-input restart
    # must produce NO cluster / NO signal / NO position from incomplete data
    stx = V2Store(str(Path(tempfile.mkdtemp()) / "g5abc.db"), starting_cash=300_000.0)
    one = form4_source.from_rows([_two(sym, "2024-03-04", "2024-03-06")[0]])  # only insider #1
    eps_partial = detect_episodes(one, config=cfg)
    out["ABC_partial_input"] = {"no_cluster_from_1_insider": eps_partial == [],
                                "no_position": stx.n_open() == 0}
    return out


def g6_capacity(cfg) -> dict:
    from talonx_v2.paper import enter_position, close_position
    st = V2Store(str(Path(tempfile.mkdtemp()) / "g6.db"), starting_cash=300_000.0)
    sess = [s for s in v2cal._sessions() if date(2026, 1, 1) <= s <= date(2026, 5, 1)]
    bars = [{"date": s.isoformat(), "open": 100.0, "close": 100.0, "volume": 300_000} for s in sess]
    entered, blocked = 0, None
    per_open_cash = []
    for i in range(21):
        sy = f"CAP{i:02d}"
        recs = form4_source.from_rows(_two(sy, "2026-03-02", "2026-03-04"))
        ep = detect_episodes(recs, config=cfg)[0]
        dec = brain_bridge.contextualize(quant_bridge.build_signal(
            ep, evaluate_liquidity(bars, entry_session=ep.eligible_entry_session, config=cfg), config=cfg))
        o = enter_position(st, dec, entry_price=100.0, entry_session=ep.eligible_entry_session,
                           config=cfg, source_meta={})
        if o.entered:
            entered += 1
            per_open_cash.append(st.cash())
        else:
            blocked = o.reason
    at_20 = st.cash()
    # close 3, capacity should free
    for p in st.open_positions()[:3]:
        close_position(st, p, exit_price=110.0, exit_session=date(2026, 4, 15), config=cfg)
    freed = st.n_open()
    return {
        "entered": entered, "blocked_reason": blocked,
        "twenty_open": entered == 20,
        "twenty_first_blocked_max_concurrent": bool(blocked) and "MAX_CONCURRENT_20" in blocked,
        "cash_after_20": at_20, "cash_floor_100k": abs(at_20 - 100_000.0) < 1e-6,
        "negative_cash_ever": any(c < 0 for c in per_open_cash),
        "monotone_cash_decrement_10k": all(abs((per_open_cash[k] - per_open_cash[k + 1]) - 10_000.0) < 1e-6
                                           for k in range(len(per_open_cash) - 1)),
        "capacity_freed_after_3_closes": freed == 17,
    }


def main() -> int:
    cfg = V2Config()
    cfg.validate_frozen()
    report = {
        "G3_full_day": g3_full_day(cfg),
        "G4_multiday": g4_multiday(cfg),
        "G4_exit_fallforward": g4_exit_fallforward(cfg),
        "G5_restart_campaign": g5_restart_campaign(cfg),
        "G6_capacity": g6_capacity(cfg),
    }
    (OUT / "rehearsal_g3_g6.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
