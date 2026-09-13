"""
TASK 130B -- durable, session-phased, V2Store-backed prospective replay.

Reuses talonx_v2.store.V2Store's ACTUAL schema/methods (unmodified
import) on an explicitly isolated SQLite path -- every intent/position/
cash/cooldown transition is a real, committed SQLite write, not
in-memory state (Task 130A's own disclosed limitation). No new store
architecture is built: reservations are computed BY QUERYING the
existing `pending_entry_intents` table (a PENDING row IS the
reservation -- no separate ledger needed), matching "extend only what
is necessary."

Explicit session phases (Part 7) -- each `as_of` tick runs, IN ORDER:
  1. OPEN   -- resolve entries for episodes whose intent was created on
              a STRICTLY EARLIER tick (today's own filings are not yet
              loaded at this point in the tick -- structurally cannot
              influence today's own morning entries).
  2. CLOSE  -- settle due exits at today's close; retry any pending
              missing-price entry reconciliation within its bounded
              window.
  3. POST-CLOSE -- NOW ingest today's own records/filings, detect new
              episodes, create PENDING intents (reservations) for
              episodes eligible at a FUTURE session.
  4. MARK   -- daily mark-to-market of every still-open position.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_ROOT))

OUT = RESEARCH_ROOT / "results" / "task130b_durable_replay"
OUT.mkdir(parents=True, exist_ok=True)

DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"
FORM4_PARQUET = RELEASE_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"

STUDY_START, STUDY_END = "2024-09-01", "2026-03-31"  # no new ELIGIBLE ENTRY sessions after this
SETTLEMENT_TAIL_SESSIONS = 20                          # tail manages only already-admitted obligations
STARTING_CASH = 300_000.0
ALLOCATION = 10_000.0
MAX_CONCURRENT = 20
COST_BPS = 20.0
HOLD_TRADING_DAYS = 10
EXIT_FALLFORWARD_MAX_SESSIONS = 5
ENTRY_PRICE_RECONCILIATION_MAX_SESSIONS = 5  # symmetric bounded retry window for a missing ENTRY reference price
REENTRY_COOLDOWN_TRADING_DAYS = 5
MAX_ENTRY_STALENESS_SESSIONS = 3
EXPECTED_FINGERPRINT = "11107198c5b81237"


def _price_lookup_factory(bars_by_symbol: dict[str, pd.DataFrame]):
    idx = {sym: df.set_index("date") for sym, df in bars_by_symbol.items()}

    def lookup(symbol, session, col):
        df = idx.get(symbol)
        if df is None or session not in df.index:
            return None, None
        v = df.loc[session, col]
        return (float(v), session) if pd.notna(v) else (None, None)

    def last_close_on_or_before(symbol, session):
        df = idx.get(symbol)
        if df is None:
            return None, None, False
        prior = df.loc[:session]
        if len(prior) == 0:
            return None, None, False
        mark_date = prior.index[-1]
        return float(prior["close"].iloc[-1]), mark_date, (mark_date != session)  # (price, mark_date, is_stale)

    return lookup, last_close_on_or_before


def load_bars(universe: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for sym in universe:
        p1, p2 = DAILY_DIR_1 / f"{sym}.csv", DAILY_DIR_2 / f"{sym}.csv"
        src = p1 if p1.exists() else (p2 if p2.exists() else None)
        if src is None or src.stat().st_size < 20:
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


class ReplayDriver:
    """Holds cross-tick state that is NOT in the SQLite store: the
    accumulated set of known episodes (populated at each tick's
    POST-CLOSE phase, consumed at the NEXT tick's OPEN phase) and
    pending-entry-price-reconciliation retry counters (a missing entry
    price is NOT immediately terminal -- see Part 5)."""

    def __init__(self, store, bars, price_lookup, last_close, cfg):
        self.store = store
        self.bars = bars
        self.price_lookup = price_lookup
        self.last_close = last_close
        self.cfg = cfg
        self.known_episodes: dict[str, object] = {}
        self.pending_entry_reconciliation: dict[str, int] = {}  # episode_id -> n_retry_sessions_so_far
        self.daily_marks: list[dict] = []
        self.audit_log: list[dict] = []
        self.funnel: dict[str, int] = {}

    def _bump(self, k):
        self.funnel[k] = self.funnel.get(k, 0) + 1

    def _audit(self, event, **kw):
        self.audit_log.append({"event": event, **kw})

    def _reserved_cash(self) -> float:
        return ALLOCATION * len(self.store.pending_entry_intents())

    def _reserved_slots(self) -> int:
        return len(self.store.pending_entry_intents())

    def available_cash(self) -> float:
        return self.store.cash() - self._reserved_cash()

    def available_slots(self) -> int:
        return MAX_CONCURRENT - self.store.n_open() - self._reserved_slots()

    # ---- OPEN phase: resolve entries for episodes with a PRIOR-tick intent ----
    def phase_open(self, as_of: date):
        from talonx_v2.calendar import add_sessions
        ripe = sorted((e for e in self.known_episodes.values()
                      if self.store.episode_disposition(e.episode_id) is None
                      and e.eligible_entry_session <= as_of),
                     key=lambda e: (e.eligible_entry_session, e.issuer_cik, e.symbol))
        for e in ripe:
            intent = self.store.entry_intent(e.episode_id)
            if intent is None or intent["status"] != "PENDING":
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_NO_PRIOR_INTENT", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self._bump("SKIPPED_NO_PRIOR_INTENT")
                continue
            # created strictly before the deadline (durable, DB-verified: the intent
            # was upserted on the earlier tick's POST-CLOSE phase, never same-tick)
            cd = self.store.cooldown_until(e.symbol)
            if cd is not None and e.eligible_entry_session < cd:
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_IN_COOLDOWN", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self.store.mark_entry_intent(intent["intent_id"], "EXPIRED_COOLDOWN")
                self._bump("SKIPPED_IN_COOLDOWN")
                self._audit("RESERVATION_RELEASED_COOLDOWN", episode_id=e.episode_id, session=str(as_of))
                continue
            if self.store.position_for_symbol(e.symbol) is not None:
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_SYMBOL_ALREADY_OPEN", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self.store.mark_entry_intent(intent["intent_id"], "EXPIRED_SYMBOL_OPEN")
                self._bump("SKIPPED_SYMBOL_ALREADY_OPEN")
                self._audit("RESERVATION_RELEASED_SYMBOL_OPEN", episode_id=e.episode_id, session=str(as_of))
                continue
            entry_px, entry_mark_date = self.price_lookup(e.symbol, e.eligible_entry_session, "open")
            if entry_px is None:
                # NOT immediately terminal -- bounded retry (Part 5)
                n = self.pending_entry_reconciliation.get(e.episode_id, 0)
                if n < ENTRY_PRICE_RECONCILIATION_MAX_SESSIONS:
                    self.pending_entry_reconciliation[e.episode_id] = n + 1
                    self._audit("ENTRY_PRICE_PENDING_RETRY", episode_id=e.episode_id, session=str(as_of), attempt=n + 1)
                    continue  # intent stays PENDING, reservation intact, retried next tick
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_NO_ENTRY_BAR", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self.store.mark_entry_intent(intent["intent_id"], "EXPIRED_NO_PRICE")
                self._bump("SKIPPED_NO_ENTRY_BAR")
                self._audit("RESERVATION_RELEASED_NO_PRICE_BOUNDARY", episode_id=e.episode_id, session=str(as_of))
                continue
            # -- ADMIT: consume reservation, open position (transactional: cash debit + position insert) --
            shares = ALLOCATION / entry_px
            target_exit = add_sessions(e.eligible_entry_session, HOLD_TRADING_DAYS)
            self.store.set_cash(self.store.cash() - ALLOCATION)
            self.store.insert_open_position(episode_id=e.episode_id, symbol=e.symbol, issuer_cik=e.issuer_cik,
                                            entry_session=e.eligible_entry_session, entry_price=entry_px,
                                            shares=shares, position_cost=ALLOCATION,
                                            target_exit_session=target_exit)
            self.store.mark_entry_intent(intent["intent_id"], "FILLED")
            self.store.append_trade(episode_id=e.episode_id, symbol=e.symbol, action="BUY",
                                    execution_price=entry_px, shares=shares, position_cost=ALLOCATION,
                                    portfolio_cash_after=self.store.cash())
            self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol, disposition="ENTERED",
                                         issuer_cik=e.issuer_cik, eligible_entry_session=e.eligible_entry_session.isoformat())
            self._bump("ENTERED")
            self._audit("ENTRY_COMMITTED", episode_id=e.episode_id, session=str(as_of), price=entry_px)

    # ---- CLOSE phase: settle due exits ----
    def phase_close(self, as_of: date):
        from talonx_v2.calendar import add_sessions
        due = sorted((p for p in self.store.open_positions()
                     if date.fromisoformat(p["target_exit_session"]) <= as_of),
                    key=lambda p: (p["entry_session"], p["symbol"]))
        for p in due:
            target = date.fromisoformat(p["target_exit_session"])
            exit_px, exit_sess = None, None
            for k in range(EXIT_FALLFORWARD_MAX_SESSIONS + 1):
                cand = add_sessions(target, k) if k else target
                if cand > as_of:
                    break
                px, _ = self.price_lookup(p["symbol"], cand, "close")
                if px is not None and px > 0:
                    exit_px, exit_sess = px, cand
                    break
            if exit_px is None:
                if as_of >= add_sessions(target, EXIT_FALLFORWARD_MAX_SESSIONS):
                    self.store.mark_exit_unresolved(p["position_id"], detail="fall-forward exhausted")
                continue
            entry_price = p["entry_price"]
            gross = (exit_px - entry_price) / entry_price
            net = gross - COST_BPS / 10_000.0
            realized = p["position_cost"] * net
            proceeds = p["position_cost"] * (1.0 + net)
            self.store.close_position(position_id=p["position_id"], exit_session=exit_sess, exit_price=exit_px,
                                      realized_pnl_usd=realized, realized_pnl_pct=100 * net,
                                      trading_days_held=(exit_sess - p["entry_session"] if isinstance(p["entry_session"], date) else None))
            self.store.set_cash(self.store.cash() + proceeds)
            self.store.append_trade(episode_id=p["episode_id"], symbol=p["symbol"], action="SELL",
                                    execution_price=exit_px, shares=p["shares"], position_cost=p["position_cost"],
                                    entry_price=entry_price, realized_pnl_usd=realized, realized_pnl_pct=100 * net,
                                    portfolio_cash_after=self.store.cash())
            self.store.set_cooldown(p["symbol"], add_sessions(exit_sess, REENTRY_COOLDOWN_TRADING_DAYS))
            self._bump("EXITED")
            self._audit("EXIT_SETTLED", episode_id=p["episode_id"], session=str(as_of), price=exit_px, proceeds=proceeds)

    # ---- POST-CLOSE phase: ingest today's OWN records, detect episodes, create intents ----
    def phase_post_close(self, as_of: date, records_provider):
        from talonx_v2 import brain_bridge, quant_bridge
        from talonx_v2.calendar import next_session_strictly_after
        from talonx_v2.cluster_engine import detect_episodes
        from talonx_v2.liquidity import evaluate_liquidity
        from talonx_v2.schemas import V2Action

        recs = records_provider(as_of)
        eps = detect_episodes(recs, config=self.cfg)
        for e in eps:
            self.known_episodes.setdefault(e.episode_id, e)

        stale_cut = as_of  # computed via add_sessions below
        from talonx_v2.calendar import add_sessions
        stale_cut = add_sessions(as_of, -MAX_ENTRY_STALENESS_SESSIONS)
        next_sess = next_session_strictly_after(as_of)

        for e in sorted(self.known_episodes.values(), key=lambda e: (e.eligible_entry_session, e.issuer_cik, e.symbol)):
            if self.store.episode_disposition(e.episode_id) is not None:
                continue
            if self.store.entry_intent(e.episode_id) is not None:
                continue
            if e.eligible_entry_session < stale_cut:
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_ENTRY_STALE", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self._bump("SKIPPED_ENTRY_STALE")
                continue
            if not (as_of < e.eligible_entry_session <= next_sess):
                continue  # not yet in the one-shot intent-creation window
            b = self.bars.get(e.symbol)
            liq = evaluate_liquidity((b.to_dict("records") if b is not None else []),
                                     entry_session=e.eligible_entry_session, config=self.cfg)
            sig = quant_bridge.build_signal(e, liq, config=self.cfg)
            decision = brain_bridge.contextualize(sig)
            if decision.action is not V2Action.BUY:
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition=f"SKIPPED_{liq.reason if not liq.ok else 'NON_BUY'}",
                                             issuer_cik=e.issuer_cik, eligible_entry_session=e.eligible_entry_session.isoformat())
                self._bump("SKIPPED_LIQUIDITY_OR_NONBUY")
                continue
            if self.available_cash() < ALLOCATION or self.available_slots() <= 0:
                self.store.record_disposition(episode_id=e.episode_id, symbol=e.symbol,
                                             disposition="SKIPPED_INSUFFICIENT_CAPACITY", issuer_cik=e.issuer_cik,
                                             eligible_entry_session=e.eligible_entry_session.isoformat())
                self._bump("SKIPPED_INSUFFICIENT_CAPACITY")
                continue
            self.store.upsert_entry_intent(e, decision, liq, horizon=HOLD_TRADING_DAYS,
                                          planned_exit_session="")
            self._bump("INTENT_CREATED")
            self._audit("INTENT_RESERVED", episode_id=e.episode_id, session=str(as_of),
                       target_entry_session=str(e.eligible_entry_session))

    # ---- MARK phase: daily mark-to-market ----
    def phase_mark(self, as_of: date):
        marked_value, cost_basis, stale = 0.0, 0.0, []
        for p in self.store.open_positions():
            px, mark_date, is_stale = self.last_close(p["symbol"], as_of)
            cost_basis += p["position_cost"]
            if px is not None:
                marked_value += p["shares"] * px
                if is_stale:
                    stale.append({"symbol": p["symbol"], "mark_date": str(mark_date), "requested_date": str(as_of)})
            else:
                marked_value += p["position_cost"]
                stale.append({"symbol": p["symbol"], "mark_date": None, "requested_date": str(as_of), "unavailable": True})
        cash = self.store.cash()
        equity = cash + marked_value
        self.daily_marks.append({
            "date": str(as_of), "cash": round(cash, 2), "reserved_cash": round(self._reserved_cash(), 2),
            "cost_basis_open": round(cost_basis, 2), "marked_value_open": round(marked_value, 2),
            "unrealized_pnl": round(marked_value - cost_basis, 2),
            "equity": round(equity, 2), "n_open": self.store.n_open(),
            "n_reserved": self._reserved_slots(), "stale_or_missing_marks": stale,
            "mark_source": "adjustment=all daily bars, same convention as entry/exit pricing",
        })


def run_replay(universe: list[str], db_path: Path, *, skip_fingerprint_check: bool = False,
               bars_override=None, records_override=None) -> ReplayDriver:
    from talonx_research.versioning import v2_fingerprint
    from talonx_v2.config import V2Config
    from talonx_v2.store import V2Store
    import exchange_calendars as xc

    fp = v2_fingerprint()
    if not skip_fingerprint_check and fp != EXPECTED_FINGERPRINT:
        raise SystemExit(f"FINGERPRINT MOVED: {fp} -- ABORT")

    cfg = V2Config(starting_cash_usd=STARTING_CASH, per_position_allocation_usd=ALLOCATION, db_path=str(db_path))
    cfg.validate_frozen()

    bars = bars_override if bars_override is not None else load_bars(universe)
    all_recs = records_override if records_override is not None else load_records(universe)
    price_lookup, last_close = _price_lookup_factory(bars)

    store = V2Store(str(db_path), starting_cash=STARTING_CASH)
    driver = ReplayDriver(store, bars, price_lookup, last_close, cfg)

    def records_provider(as_of):
        lo = as_of - timedelta(days=45)
        return [r for r in all_recs if lo <= r.filing_date <= as_of]

    cal = xc.get_calendar("XNYS")
    study_sessions = [d.date() for d in cal.sessions_in_range(STUDY_START, STUDY_END)]
    tail = [d.date() for d in cal.sessions_window(study_sessions[-1], SETTLEMENT_TAIL_SESSIONS)][1:]
    all_sessions = study_sessions + tail
    driver.study_cutoff = study_sessions[-1]

    for as_of in all_sessions:
        driver.phase_open(as_of)
        driver.phase_close(as_of)
        if as_of <= study_sessions[-1]:
            # NO new eligible-entry sessions after the study cutoff -- the
            # tail manages only already-admitted obligations (Part 8)
            driver.phase_post_close(as_of, records_provider)
        driver.phase_mark(as_of)
        if as_of == study_sessions[-1]:
            driver._audit("STUDY_CUTOFF_REACHED", session=str(as_of), equity=driver.daily_marks[-1]["equity"],
                         n_open=driver.store.n_open())

    return driver
