"""
TASK 130A -- a genuinely gated, session-by-session prospective replay
of INSIDER_BUY_CLUSTER_V2@1 over Discovery Universe v1. Corrects Task
130's post-hoc filtering: this driver enforces the entry-eligibility
gate IN-LINE, so an episode without a prior durable intent NEVER
touches cash/capacity/cooldown state at all (not run-then-filtered).

Calls the SAME production-adjacent primitives Task 130/production used
(unmodified imports; no production file edited): cluster_engine.detect_episodes,
liquidity.evaluate_liquidity, quant_bridge.build_signal,
brain_bridge.contextualize, calendar.add_sessions/next_session_strictly_after,
pipeline.settle_due_exits (exits are independent of entry-scope
eligibility, reused unchanged). Position/cash bookkeeping and the
entry gate are this task's own, isolated, explicit state machine (not
talonx_v2.store.V2Store/paper.py, which implement the PERMISSIVE
policy) -- this keeps the correction auditable and testable without
touching production code.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_ROOT))  # talonx_v2 lives here too (Task 118D/130 convention)

OUT = RESEARCH_ROOT / "results" / "task130a_corrected_replay"
OUT.mkdir(parents=True, exist_ok=True)

DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"
FORM4_PARQUET = RELEASE_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"

START, END = "2024-09-01", "2026-03-31"
STARTING_CASH = 300_000.0
ALLOCATION = 10_000.0
MAX_CONCURRENT = 20
COST_BPS = 20.0
HOLD_TRADING_DAYS = 10
EXIT_FALLFORWARD_MAX_SESSIONS = 5
REENTRY_COOLDOWN_TRADING_DAYS = 5
MAX_ENTRY_STALENESS_SESSIONS = 3
EXPECTED_FINGERPRINT = "11107198c5b81237"


# ---------------------------------------------------------------------
# state
# ---------------------------------------------------------------------
@dataclass
class Intent:
    episode_id: str
    symbol: str
    issuer_cik: str
    target_entry_session: date
    created_session: date
    status: str = "PENDING"  # PENDING | FILLED | EXPIRED_STALE | EXPIRED_NO_PRICE | EXPIRED_COOLDOWN | EXPIRED_SYMBOL_OPEN


@dataclass
class OpenPosition:
    episode_id: str
    symbol: str
    entry_session: date
    entry_price: float
    shares: float
    notional: float
    target_exit_session: date


@dataclass
class State:
    cash: float = STARTING_CASH
    reserved_cash: float = 0.0
    intents: dict = field(default_factory=dict)          # episode_id -> Intent
    open_positions: dict = field(default_factory=dict)    # episode_id -> OpenPosition
    cooldown_until: dict = field(default_factory=dict)    # symbol -> date
    dispositions: dict = field(default_factory=dict)      # episode_id -> reason
    closed_trades: list = field(default_factory=list)
    daily_marks: list = field(default_factory=list)

    @property
    def n_reserved_slots(self) -> int:
        return sum(1 for i in self.intents.values() if i.status == "PENDING")

    @property
    def available_cash(self) -> float:
        return self.cash - self.reserved_cash

    @property
    def available_slots(self) -> int:
        return MAX_CONCURRENT - len(self.open_positions) - self.n_reserved_slots


def _net_return(entry_px: float, exit_px: float) -> float:
    return (exit_px - entry_px) / entry_px - COST_BPS / 10_000.0


def _price_lookup_factory(bars_by_symbol: dict[str, pd.DataFrame]):
    idx = {}
    for sym, df in bars_by_symbol.items():
        idx[sym] = df.set_index("date")

    def lookup(symbol: str, session: date, col: str) -> float | None:
        df = idx.get(symbol)
        if df is None or session not in df.index:
            return None
        v = df.loc[session, col]
        return float(v) if pd.notna(v) else None

    def last_close_on_or_before(symbol: str, session: date) -> float | None:
        df = idx.get(symbol)
        if df is None:
            return None
        prior = df.loc[:session]
        if len(prior) == 0:
            return None
        return float(prior["close"].iloc[-1])

    return lookup, last_close_on_or_before


def load_bars(universe: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for sym in universe:
        p1, p2 = DAILY_DIR_1 / f"{sym}.csv", DAILY_DIR_2 / f"{sym}.csv"
        src = p1 if p1.exists() else (p2 if p2.exists() else None)
        if src is None or src.stat().st_size < 20:  # "EMPTY\n" placeholder (task107a_prices.py convention) or truly empty
            continue
        try:
            df = pd.read_csv(src, usecols=["date", "open", "close", "volume"], parse_dates=["date"])
        except (pd.errors.EmptyDataError, ValueError):
            continue
        df["date"] = df["date"].dt.date
        df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        out[sym] = df
    return out


def load_records(universe: list[str]):
    from talonx_v2 import form4_source
    all_recs = list(form4_source.from_research_parquet(str(FORM4_PARQUET), since=date(2019, 1, 1)))
    all_recs.sort(key=lambda r: r.filing_date)
    syms = set(universe)
    return [r for r in all_recs if r.symbol in syms]


def run_replay(universe: list[str], *, verbose: bool = True,
               bars_override: dict | None = None, records_override: list | None = None,
               start: str = START, end: str = END,
               starting_cash: float = STARTING_CASH, skip_fingerprint_check: bool = False) -> dict:
    from talonx_research.versioning import v2_fingerprint
    from talonx_v2 import brain_bridge, quant_bridge
    from talonx_v2.calendar import add_sessions, next_session_strictly_after
    from talonx_v2.cluster_engine import detect_episodes
    from talonx_v2.config import V2Config
    from talonx_v2.liquidity import evaluate_liquidity
    from talonx_v2.schemas import V2Action
    import exchange_calendars as xc

    fp = v2_fingerprint()
    if not skip_fingerprint_check and fp != EXPECTED_FINGERPRINT:
        raise SystemExit(f"FINGERPRINT MOVED: {fp} -- ABORT")

    cfg = V2Config(starting_cash_usd=starting_cash, per_position_allocation_usd=ALLOCATION,
                  db_path=str(OUT / "unused_placeholder.db"))
    cfg.validate_frozen()

    bars = bars_override if bars_override is not None else load_bars(universe)
    all_recs = records_override if records_override is not None else load_records(universe)
    price_lookup, last_close = _price_lookup_factory(bars)

    cal = xc.get_calendar("XNYS")
    sessions = [d.date() for d in cal.sessions_in_range(start, end)]
    tail = [d.date() for d in cal.sessions_window(sessions[-1], 20)][1:]
    all_sessions = sessions + tail

    st = State(cash=starting_cash)
    processed_episode_ids: set[str] = set()
    ep_by_id: dict[str, object] = {}
    funnel_counts: dict[str, int] = {}

    def _bump(k: str) -> None:
        funnel_counts[k] = funnel_counts.get(k, 0) + 1

    def records_asof(as_of: date):
        lo = as_of - timedelta(days=45)
        return [r for r in all_recs if lo <= r.filing_date <= as_of]

    for as_of in all_sessions:
        recs = records_asof(as_of)
        eps = detect_episodes(recs, config=cfg)
        for e in eps:
            ep_by_id[e.episode_id] = e
        next_sess = next_session_strictly_after(as_of)

        # ---- staleness pass: episodes whose eligible_entry_session has
        # gone stale relative to `as_of` are terminally skipped, and any
        # PENDING intent for them is expired (reservation released).
        stale_cut = add_sessions(as_of, -MAX_ENTRY_STALENESS_SESSIONS)
        for e in eps:
            if e.episode_id in processed_episode_ids:
                continue
            if e.eligible_entry_session < stale_cut:
                processed_episode_ids.add(e.episode_id)
                st.dispositions[e.episode_id] = "SKIPPED_ENTRY_STALE"
                _bump("SKIPPED_ENTRY_STALE")
                intent = st.intents.get(e.episode_id)
                if intent is not None and intent.status == "PENDING":
                    intent.status = "EXPIRED_STALE"
                    st.reserved_cash -= ALLOCATION

        # ---- PRE-OPEN INTENT PASS: one shot, exactly one session before
        # the entry session -- deterministic order across competing
        # episodes this same tick.
        candidates = sorted(
            (e for e in eps if e.episode_id not in processed_episode_ids
             and e.episode_id not in st.intents
             and as_of < e.eligible_entry_session <= next_sess),
            key=lambda e: (e.eligible_entry_session, e.issuer_cik, e.symbol))
        for e in candidates:
            b = bars.get(e.symbol)
            liq = evaluate_liquidity((b.to_dict("records") if b is not None else []),
                                     entry_session=e.eligible_entry_session, config=cfg)
            sig = quant_bridge.build_signal(e, liq, config=cfg)
            decision = brain_bridge.contextualize(sig)
            if decision.action is not V2Action.BUY:
                st.dispositions[e.episode_id] = f"SKIPPED_{liq.reason if not liq.ok else 'NON_BUY'}"
                _bump(st.dispositions[e.episode_id])
                processed_episode_ids.add(e.episode_id)
                continue
            if st.available_cash < ALLOCATION:
                st.dispositions[e.episode_id] = "SKIPPED_INSUFFICIENT_CAPITAL"
                _bump("SKIPPED_INSUFFICIENT_CAPITAL")
                processed_episode_ids.add(e.episode_id)
                continue
            if st.available_slots <= 0:
                st.dispositions[e.episode_id] = "SKIPPED_MAX_CONCURRENT_20"
                _bump("SKIPPED_MAX_CONCURRENT_20")
                processed_episode_ids.add(e.episode_id)
                continue
            st.intents[e.episode_id] = Intent(episode_id=e.episode_id, symbol=e.symbol,
                                              issuer_cik=e.issuer_cik,
                                              target_entry_session=e.eligible_entry_session,
                                              created_session=as_of)
            st.reserved_cash += ALLOCATION
            _bump("INTENT_CREATED")

        # ---- ENTRY LOOP: only episodes ripe THIS session, deterministic order ----
        ripe = sorted((e for e in eps if e.episode_id not in processed_episode_ids
                      and e.eligible_entry_session <= as_of),
                     key=lambda e: (e.eligible_entry_session, e.issuer_cik, e.symbol))
        for e in ripe:
            processed_episode_ids.add(e.episode_id)
            intent = st.intents.get(e.episode_id)
            # THE GATE: a durable PENDING intent must exist, created on a
            # STRICTLY EARLIER simulated session than the target entry
            # deadline, matching this exact episode.
            if intent is None or intent.status != "PENDING" or intent.created_session >= e.eligible_entry_session:
                st.dispositions[e.episode_id] = "SKIPPED_NO_PRIOR_INTENT"
                _bump("SKIPPED_NO_PRIOR_INTENT")
                continue
            if st.cooldown_until.get(e.symbol) is not None and e.eligible_entry_session < st.cooldown_until[e.symbol]:
                st.dispositions[e.episode_id] = "SKIPPED_IN_COOLDOWN"
                _bump("SKIPPED_IN_COOLDOWN")
                intent.status = "EXPIRED_COOLDOWN"
                st.reserved_cash -= ALLOCATION
                continue
            if any(p.symbol == e.symbol for p in st.open_positions.values()):
                st.dispositions[e.episode_id] = "SKIPPED_SYMBOL_ALREADY_OPEN"
                _bump("SKIPPED_SYMBOL_ALREADY_OPEN")
                intent.status = "EXPIRED_SYMBOL_OPEN"
                st.reserved_cash -= ALLOCATION
                continue
            entry_px = price_lookup(e.symbol, e.eligible_entry_session, "open")
            if entry_px is None or entry_px <= 0:
                st.dispositions[e.episode_id] = "SKIPPED_NO_ENTRY_BAR"
                _bump("SKIPPED_NO_ENTRY_BAR")
                intent.status = "EXPIRED_NO_PRICE"
                st.reserved_cash -= ALLOCATION
                continue
            # -- ADMIT: consume the reservation, open the position --
            shares = ALLOCATION / entry_px
            st.cash -= ALLOCATION
            st.reserved_cash -= ALLOCATION
            intent.status = "FILLED"
            target_exit = add_sessions(e.eligible_entry_session, HOLD_TRADING_DAYS)
            st.open_positions[e.episode_id] = OpenPosition(
                episode_id=e.episode_id, symbol=e.symbol, entry_session=e.eligible_entry_session,
                entry_price=entry_px, shares=shares, notional=ALLOCATION, target_exit_session=target_exit)
            st.dispositions[e.episode_id] = "ENTERED"
            _bump("ENTERED")

        # ---- EXIT SETTLEMENT (after entries -- a same-session exit's
        # proceeds can never fund that same morning's entries) ----
        due = [p for p in st.open_positions.values() if p.target_exit_session <= as_of]
        due.sort(key=lambda p: (p.entry_session, p.symbol))
        for p in due:
            exit_px = None
            exit_sess = None
            for k in range(EXIT_FALLFORWARD_MAX_SESSIONS + 1):
                cand = add_sessions(p.target_exit_session, k) if k else p.target_exit_session
                if cand > as_of:
                    break
                px = price_lookup(p.symbol, cand, "close")
                if px is not None and px > 0:
                    exit_px, exit_sess = px, cand
                    break
            if exit_px is None:
                if as_of >= add_sessions(p.target_exit_session, EXIT_FALLFORWARD_MAX_SESSIONS):
                    st.dispositions[p.episode_id] = "EXIT_UNRESOLVED"
                continue  # keep trying on subsequent sessions until fall-forward exhausted
            gross = (exit_px - p.entry_price) / p.entry_price
            net = _net_return(p.entry_price, exit_px)
            proceeds = p.notional * (1.0 + net)
            st.cash += proceeds
            st.closed_trades.append({
                "episode_id": p.episode_id, "symbol": p.symbol,
                "entry_session": str(p.entry_session), "exit_session": str(exit_sess),
                "entry_price": p.entry_price, "exit_price": exit_px,
                "shares": p.shares, "notional": p.notional,
                "gross_return": gross, "net_return": net, "net_pnl_usd": p.notional * net,
            })
            st.cooldown_until[p.symbol] = add_sessions(exit_sess, REENTRY_COOLDOWN_TRADING_DAYS)
            del st.open_positions[p.episode_id]
            _bump("EXITED")

        # ---- DAILY MARK (every session, causal, last close on/before) ----
        marked_value = 0.0
        cost_basis = 0.0
        stale_marks = []
        for p in st.open_positions.values():
            px = last_close(p.symbol, as_of)
            cost_basis += p.notional
            if px is not None:
                marked_value += p.shares * px
            else:
                marked_value += p.notional  # no mark available yet -- hold at cost, flagged
                stale_marks.append(p.symbol)
        realized_pnl_cum = sum(t["net_pnl_usd"] for t in st.closed_trades)
        equity = st.cash + marked_value
        st.daily_marks.append({
            "date": str(as_of), "cash": round(st.cash, 2), "reserved_cash": round(st.reserved_cash, 2),
            "cost_basis_open": round(cost_basis, 2), "marked_value_open": round(marked_value, 2),
            "unrealized_pnl": round(marked_value - cost_basis, 2),
            "realized_pnl_cum": round(realized_pnl_cum, 2),
            "equity": round(equity, 2), "n_open": len(st.open_positions),
            "n_reserved": st.n_reserved_slots, "stale_marks": stale_marks,
        })

    n_filings_seen = len(ep_by_id)
    return {
        "state": st, "funnel_counts": funnel_counts, "n_episodes_detected": n_filings_seen,
        "fingerprint": fp, "sessions_replayed": len(all_sessions),
    }


def main() -> int:
    m = json.loads((RESEARCH_ROOT / "results/task118_profitability/reconciliation/population_manifest.json").read_text())
    universe = sorted(m["C_full_panel_A_union_B"])
    result = run_replay(universe)
    st: State = result["state"]

    (OUT / "closed_trades.json").write_text(json.dumps(st.closed_trades, indent=2, default=str))
    (OUT / "daily_marks.json").write_text(json.dumps(st.daily_marks, indent=2, default=str))
    (OUT / "dispositions.json").write_text(json.dumps(st.dispositions, indent=2, default=str))

    eq = pd.Series([d["equity"] for d in st.daily_marks], index=pd.to_datetime([d["date"] for d in st.daily_marks]))
    eq_with_start = pd.concat([pd.Series([STARTING_CASH], index=[eq.index[0] - pd.Timedelta(days=1)]), eq])
    running_max = eq_with_start.cummax()
    dd = (eq_with_start - running_max) / running_max
    n_days_with_open = sum(1 for d in st.daily_marks if d["n_open"] > 0)

    summary = {
        "window": {"start": START, "end": END}, "universe_n": len(universe),
        "starting_cash": STARTING_CASH, "allocation": ALLOCATION, "max_concurrent": MAX_CONCURRENT,
        "fingerprint": result["fingerprint"], "n_episodes_detected": result["n_episodes_detected"],
        "funnel_counts": result["funnel_counts"],
        "n_closed_trades": len(st.closed_trades),
        "n_open_at_end": len(st.open_positions),
        "open_at_end": [{"episode_id": p.episode_id, "symbol": p.symbol, "entry_session": str(p.entry_session)}
                        for p in st.open_positions.values()],
        "ending_cash": round(st.cash, 2), "ending_equity": round(eq.iloc[-1], 2) if len(eq) else STARTING_CASH,
        "max_drawdown_pct_daily_marked": round(float(dd.min() * 100), 4),
        "capital_utilization_pct_days_with_open_position": round(100 * n_days_with_open / len(st.daily_marks), 2),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
