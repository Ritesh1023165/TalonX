"""
talonx_v2.dividends -- PQ-2A closure: ordinary-cash-dividend TOTAL-RETURN lifecycle
================================================================================
Gatekeeper decision (S10-17 retained): V2 performance is TOTAL RETURN.

    total realized result = price P&L (positions.realized_pnl_usd: exit proceeds
                            - entry economic cost, fee-inclusive)
                          + dividend P&L (sum of CREDITED dividend_entitlements)

Lifecycle (smallest auditable, additive, never rewrites a position/trade row):

    provider event (explicit, id/ex/record/payable)      -- Alpaca /v1/corporate-actions
      -> ELIGIBLE  iff entry_session < ex_date <= exit_fill_session
                  (T+1-era ownership rule: a buyer on/after the ex-date is NOT entitled;
                   a seller on/after the ex-date KEEPS the dividend)
      -> ACCRUED   recorded ATOMICALLY with settlement (paper.close_position); quantity =
                  exact economic shares AT the ex-date (split trail), amount = provider
                  per-share rate x quantity (rate is raw per-share as of the ex-date, NOT
                  split-normalised), cents ROUND_HALF_UP.  No cash yet.
      -> CREDITED  on/after payable_date, after a FRESH provider re-confirmation of the same
                  event; ``portfolio.cash`` += amount in the SAME transaction as the state
                  change (conditional UPDATE ... WHERE state='ACCRUED' = once-only gate).

An entitlement survives the position being CLOSED (no trade is reopened).  Missing payable_date
or an event the provider no longer confirms is NEVER credited (stays ACCRUED, operator-visible).
Price fills must be dividend-unadjusted (guard in ``corporate_actions``), so cash is never
credited on top of a dividend-adjusted price.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

logger = logging.getLogger(__name__)

OVERDUE_DAYS = 10          # ACCRUED this long past payable_date => reconciliation problem
# PQ-2B: bounded catch-up for a dividend the provider published only AFTER a trade already settled.
# Same length as the exit-recovery window; never scanned indefinitely, never reopens a trade.
LATE_DIVIDEND_LOOKBACK_SESSIONS = 5


def catch_up_recent_closed(store, guard, *, as_of: date,
                           lookback_sessions: int = LATE_DIVIDEND_LOOKBACK_SESSIONS) -> list[dict]:
    """Create the SAME idempotent ACCRUED receivable for an eligible ordinary cash dividend that was
    published only after the position settled.  Strictly bounded: only positions CLOSED within the last
    ``lookback_sessions`` sessions; only positions whose entry AND exit fills carry a dividend-unadjusted
    basis (a legacy / provenance-less trade is NEVER back-filled); unsupported/conflicting evidence in the
    hold window skips the position (operator-visible status).  Never reopens or mutates the trade."""
    from talonx_v2 import calendar as v2cal
    from talonx_v2 import corporate_actions as ca
    out: list[dict] = []
    if guard is None:
        return out
    for p in store.all_positions():
        if p["status"] != "CLOSED" or not p.get("exit_session"):
            continue
        exit_s = date.fromisoformat(str(p["exit_session"])[:10])
        entry_s = date.fromisoformat(str(p["entry_session"])[:10])
        if v2cal.sessions_between(exit_s, as_of) > lookback_sessions:
            continue                                            # lookback bound
        row = {"position_id": p["position_id"], "symbol": p["symbol"], "exit_session": exit_s.isoformat()}
        try:
            res = guard.fetch(p["symbol"], entry_s, exit_s, fresh=True)
            if not res.ok:
                out.append({**row, "status": "EVIDENCE_UNAVAILABLE"})
                continue
            window = [e for e in res.events if e.ex_date is None or entry_s < e.ex_date <= exit_s]
            divs = [e for e in window if e.kind == ca.KIND_CASH_DIVIDEND]
            if not divs and not [e for e in window if e.kind == ca.KIND_UNSUPPORTED]:
                continue
            if any(ca.CorporateActionGuard._conflict_in_window(c, entry_s, exit_s) for c in res.conflicts) \
                    or any(e.kind == ca.KIND_UNSUPPORTED for e in window):
                out.append({**row, "status": "SKIPPED_UNSUPPORTED_OR_CONFLICTING_EVIDENCE"})
                continue
            states = (ca._parse_adjustment_state(p.get("entry_price_provenance")),
                      ca._parse_adjustment_state(p.get("exit_price_provenance")))
            if any(s not in ca.DIVIDEND_SAFE_BASES for s in states):
                out.append({**row, "status": "SKIPPED_PRICE_BASIS_NOT_UNADJUSTED_OR_LEGACY", "states": list(states)})
                continue
            splits = [e for e in window if e.kind in ca.SPLIT_KINDS]
            for d in divs:
                if any(sp.ex_date == d.ex_date for sp in splits):
                    out.append({**row, "status": "SKIPPED_DIVIDEND_SPLIT_SAME_EX_DATE", "ex_date": d.ex_date.isoformat()})
                    continue
                created = store.record_dividend_entitlement(position_id=p["position_id"], event=d, exit_session=exit_s)
                if created:
                    out.append({**row, "status": "LATE_DIVIDEND_ACCRUED", "ex_date": d.ex_date.isoformat(),
                                "action_key": d.action_key})
        except Exception as exc:  # noqa: BLE001 -- one position never blocks another
            logger.exception("late_dividend_catch_up_failed position=%s", p.get("position_id"))
            out.append({**row, "status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:160]})
    return out


def settle_receivables(store, guard, *, as_of: date) -> list[dict]:
    """Credit every ACCRUED entitlement whose payable_date <= ``as_of`` -- for CLOSED positions
    as well as open ones.  Deterministic, idempotent, restart-safe.  Never credits on missing /
    unavailable / changed evidence."""
    out: list[dict] = []
    if guard is None:
        return out
    for e in store.dividend_entitlements(state="ACCRUED"):
        pay = e["payable_date"]
        row = {"entitlement_id": e["entitlement_id"], "symbol": e["symbol"], "ex_date": e["ex_date"],
               "payable_date": pay, "amount_usd": e["amount_usd"]}
        try:
            if not pay:
                out.append({**row, "status": "NO_PAYABLE_DATE"})
                continue
            if date.fromisoformat(pay) > as_of:
                out.append({**row, "status": "NOT_YET_PAYABLE"})
                continue
            ex = date.fromisoformat(e["ex_date"])
            res = guard.fetch(e["symbol"], ex - timedelta(days=1), date.fromisoformat(pay), fresh=True)
            if not res.ok:
                store.note_dividend_check(e["entitlement_id"], f"provider unavailable at {as_of}: {res.detail}")
                out.append({**row, "status": "EVIDENCE_UNAVAILABLE"})
                continue
            if any(c.split("|")[2:3] == [e["ex_date"]] for c in res.conflicts):
                store.note_dividend_check(e["entitlement_id"], f"conflicting evidence at {as_of}")
                out.append({**row, "status": "EVIDENCE_CONFLICT"})
                continue
            confirmed = next((x for x in res.events if x.action_key == e["action_key"]), None)
            if confirmed is None:
                store.note_dividend_check(e["entitlement_id"], f"provider no longer confirms event at {as_of}")
                out.append({**row, "status": "NOT_CONFIRMED"})
                continue
            if confirmed.payable_date is None or confirmed.payable_date.isoformat() != pay:
                store.note_dividend_check(e["entitlement_id"], f"payable_date changed at {as_of}")
                out.append({**row, "status": "PAYABLE_DATE_CHANGED"})
                continue
            ok = store.credit_dividend(e["entitlement_id"], as_of=as_of,
                                       detail=f"re-confirmed by {confirmed.source} at {as_of}")
            out.append({**row, "status": "CREDITED" if ok else "ALREADY_CREDITED"})
        except Exception as exc:  # noqa: BLE001 -- one bad row never blocks the others / the tick
            logger.exception("dividend_credit_failed entitlement=%s", e.get("entitlement_id"))
            out.append({**row, "status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:200]})
    return out


# --------------------------------------------------------------------------- #
# read-only helpers (raw sqlite connection)
# --------------------------------------------------------------------------- #
def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def credited_total(con: sqlite3.Connection) -> float:
    if not _has_table(con, "dividend_entitlements"):
        return 0.0
    return float(con.execute("SELECT COALESCE(SUM(amount_usd),0) FROM dividend_entitlements "
                             "WHERE state='CREDITED'").fetchone()[0] or 0.0)


def accrued_total(con: sqlite3.Connection) -> float:
    if not _has_table(con, "dividend_entitlements"):
        return 0.0
    return float(con.execute("SELECT COALESCE(SUM(amount_usd),0) FROM dividend_entitlements "
                             "WHERE state='ACCRUED'").fetchone()[0] or 0.0)


def per_position_totals(con: sqlite3.Connection) -> dict[int, dict]:
    """``{position_id: {credited, accrued}}`` for total-return presentation (price P&L + dividends)."""
    if not _has_table(con, "dividend_entitlements"):
        return {}
    out: dict[int, dict] = {}
    for r in con.execute("SELECT position_id, state, amount_usd FROM dividend_entitlements"):
        d = out.setdefault(r[0], {"credited": 0.0, "accrued": 0.0})
        d["credited" if r[1] == "CREDITED" else "accrued"] += float(r[2])
    return out


def rows(con: sqlite3.Connection) -> list[dict]:
    if not _has_table(con, "dividend_entitlements"):
        return []
    prev = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM dividend_entitlements ORDER BY entitlement_id")]
    finally:
        con.row_factory = prev


def problems(con: sqlite3.Connection, *, as_of: date | None = None) -> list[str]:
    """Genuinely inconsistent dividend accounting (read-only; a correct ledger yields NONE):
    duplicate credit, impossible lineage, wrong quantity/amount, credit before payable date,
    overdue receivable.  The CASH consequence (missing/extra credit) is caught by the ledger
    cash equation, which includes ``credited_total``."""
    if not _has_table(con, "dividend_entitlements"):
        return []
    from talonx_v2.corporate_actions import fraction_to_decimal, shares_at_date
    out: list[str] = []
    prev = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        try:
            ents = [dict(r) for r in con.execute("SELECT * FROM dividend_entitlements ORDER BY entitlement_id")]
            pos = {r["position_id"]: dict(r) for r in con.execute(
                "SELECT position_id, episode_id, status, entry_session, exit_session FROM positions")}
        except sqlite3.OperationalError as exc:
            return [f"cannot read positions to verify dividend accounting: {exc}"]
        seen: dict[tuple, int] = {}
        for e in ents:
            tag = f"dividend {e['symbol']} ex {e['ex_date']} (entitlement {e['entitlement_id']})"
            key = (e["position_id"], e["symbol"], e["ex_date"])
            seen[key] = seen.get(key, 0) + 1
            p = pos.get(e["position_id"])
            if p is None:
                out.append(f"{tag}: lineage broken -- position {e['position_id']} missing")
                continue
            if e["episode_id"] != p["episode_id"]:
                out.append(f"{tag}: lineage mismatch -- episode {e['episode_id']} != position episode {p['episode_id']}")
            if e["ex_date"] <= p["entry_session"]:
                out.append(f"{tag}: ineligible -- ex_date not after entry_session {p['entry_session']}")
            if p["status"] == "CLOSED" and p["exit_session"] and e["ex_date"] > p["exit_session"]:
                out.append(f"{tag}: ineligible -- ex_date after exit_session {p['exit_session']}")
            try:
                qty = shares_at_date(con, e["position_id"], date.fromisoformat(e["ex_date"]))
                if Fraction(e["eligible_qty"]) != qty:
                    out.append(f"{tag}: eligible_qty {e['eligible_qty']} != economic shares at ex-date {qty}")
                exact = Decimal(e["rate"]) * fraction_to_decimal(Fraction(e["eligible_qty"]))
                usd = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if abs(float(usd) - float(e["amount_usd"])) > 0.005:
                    out.append(f"{tag}: amount {e['amount_usd']} != rate x quantity {usd}")
            except (ValueError, ArithmeticError) as exc:
                out.append(f"{tag}: unreadable amount/quantity ({exc})")
            if e["state"] == "CREDITED":
                if e["cash_after"] is None or not e["credited_as_of"]:
                    out.append(f"{tag}: CREDITED without cash_after/credited_as_of")
                elif not e["payable_date"] or e["credited_as_of"] < e["payable_date"]:
                    out.append(f"{tag}: credited before payable date")
            elif e["state"] == "ACCRUED" and as_of is not None and e["payable_date"] and \
                    as_of - date.fromisoformat(e["payable_date"]) > timedelta(days=OVERDUE_DAYS):
                out.append(f"{tag}: receivable overdue -- payable {e['payable_date']}, still ACCRUED at {as_of}")
        for key, n in seen.items():
            if n > 1:
                out.append(f"duplicate dividend entitlement for position {key[0]} {key[1]} ex {key[2]} (x{n})")
    finally:
        con.row_factory = prev
    return out
