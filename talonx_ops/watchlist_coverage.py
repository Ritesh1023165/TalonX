"""
talonx_ops.watchlist_coverage -- read-only "what serves each configured ticker?" map
================================================================================
Task 117 overnight P5.  Honest, read-only reconciliation of the owner's
configured watchlist against what the product can actually do for each ticker
and horizon.  NOTHING here changes the trade universe, ingestion scope, or any
strategy.  It only *reports*.

Five scopes are kept explicitly separate (do not conflate):

  1. COLLECTION scope        -- which issuers TalonX ingests SEC Form 4 for
  2. USER ALERT scope        -- which tickers the owner asked for alerts on
  3. FROZEN STRATEGY         -- which tickers a frozen strategy is *eligible* on
     ELIGIBILITY                (V2: membership-OR-liquidity, at cluster time)
  4. PAPER EXECUTION          -- which tickers can take a paper position, in which
     ELIGIBILITY                ledger
  5. HISTORICAL VALIDATION    -- the population a strategy's edge was measured on
     POPULATION

Run:  python -m talonx_ops.watchlist_coverage   [--json]
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HOME = Path.home() / ".talonx"

# --- honest per-lane serving statements (from the closed alpha program) --------
_INTRADAY_METHOD = (
    "Original quant scanner -- descriptive BULLISH / BEARISH / BUY / SELL assessments. "
    "NO validated intraday edge (Task 94 ALPHA_DISCOVERY_NO_CANDIDATE_PASSED / "
    "Task 95A INTRADAY_ALPHA_NOT_SUPPORTED). Assessments are informational."
)
_MULTIDAY_METHOD = (
    "INSIDER_BUY_CLUSTER_V2@1 (fp 11107198c5b81237) -- the one PAPER_CANDIDATE. "
    "Event-driven: only fires when >=2 distinct insiders file SEC code-P open-market "
    "purchases in the issuer within 10 trading days. 10-trading-day hold. Descriptive, "
    "not a profit claim."
)
_LONGTERM_METHOD = (
    "No validated long-only strategy (Task 95B/95C/95E/95I all closed with no free "
    "long-only alpha). Intelligence (Task 96) provides descriptive risk / event "
    "information ONLY -- it is not a trading policy."
)


@dataclass
class TickerCoverage:
    symbol: str
    name: str
    exchange: str
    status: str                       # active | paused
    configured_horizon: str           # DUAL_HORIZON | INTRADAY | ...
    paper_trading_enabled: bool
    paper_trading_enabled_long_term: bool
    # per-lane serving
    intraday_serving: str
    multiday_serving: str
    longterm_serving: str
    # V2 specifics
    v2_collection_scope: str          # POLLED | NOT_POLLED
    v2_strategy_eligibility: str
    v2_evidence_status: str
    v2_alert_capability: str
    v2_paper_portfolio: str
    unsupported_reason: str


def _rows(db: Path) -> list[dict]:
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT symbol, name, exchange, status, strategy_horizon, "
            "paper_trading_enabled, paper_trading_enabled_long_term FROM tickers "
            "ORDER BY symbol")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _us_listed(exchange: str) -> bool:
    ex = (exchange or "").upper()
    return any(k in ex for k in ("NYSE", "NASDAQ")) and "KRX" not in ex


def build_coverage_map(*, home: Path | None = None) -> dict[str, Any]:
    home = home or _HOME
    rows = _rows(home / "watchlist.db")
    out: list[TickerCoverage] = []
    for r in rows:
        sym = r["symbol"]
        active = r["status"] == "active"
        horizon = r["strategy_horizon"] or "UNKNOWN"
        wants_multiday = horizon in ("DUAL_HORIZON", "SWING", "MULTI_DAY")
        us = _us_listed(r["exchange"])

        # V2 collection scope: intelligence.service polls the resolvable ACTIVE
        # watchlist.  A US-listed active name is polled; a paused / non-US /
        # private name is not.
        polled = active and us
        v2_scope = "POLLED" if polled else "NOT_POLLED"

        if not wants_multiday:
            v2_elig = "N/A -- owner configured INTRADAY only for this ticker"
            v2_evi = "N/A"
            v2_alert = "N/A (V2 lane)"
            v2_paper = "N/A (V2 lane)"
            reason = "owner did not request a multi-day horizon here"
        elif not us:
            v2_elig = "INELIGIBLE -- non-US listing (SEC Form 4 not filed; V2 is a US insider signal)"
            v2_evi = "n/a"
            v2_alert = "none (V2)"
            v2_paper = "none (V2)"
            reason = f"{r['exchange']} -- outside the SEC Form 4 domain"
        elif not polled:
            v2_elig = "UNKNOWN -- issuer not currently in the V2 SEC collection scope"
            v2_evi = "no cluster history (not ingested)"
            v2_alert = "would use family insider_buy_cluster_v2 IF ingested and a cluster forms"
            v2_paper = "v2_lane.db ($300,000 campaign) -- only on an actual eligible cluster"
            reason = "paused watchlist entry -- not polled for Form 4"
        else:
            v2_elig = ("EVALUATED PER-TICK at cluster time: membership-OR-liquidity. "
                       "Liquidity branch (median $-vol >= $5M and close >= $5) is computed "
                       "from bars; membership branch is UNKNOWN (no free PIT S&P feed "
                       "materialised -- UNIVERSE_CONTRACT_DECISION_REQUIRED). MEMBERSHIP_UNKNOWN "
                       "!= NON_MEMBER; the liquidity branch backstops.")
            v2_evi = ("in the V2 collection scope; a cluster only exists if >=2 distinct "
                      "insiders buy (code P) within 10 td -- most names never produce one "
                      "(Task 116 base rate ~1-2 entries/yr on the 43-name subset)")
            v2_alert = ("family insider_buy_cluster_v2 -> ONE official Telegram path via "
                        "OfficialExternalRouter + the durable v2_alert_outbox "
                        "(SENT/HELD/RETRY/FAILED/AMBIGUOUS)")
            v2_paper = "v2_lane.db ($300,000 campaign ledger), separate from Original paper"
            reason = ""

        out.append(TickerCoverage(
            symbol=sym, name=r["name"], exchange=r["exchange"], status=r["status"],
            configured_horizon=horizon,
            paper_trading_enabled=bool(r["paper_trading_enabled"]),
            paper_trading_enabled_long_term=bool(r["paper_trading_enabled_long_term"]),
            intraday_serving=_INTRADAY_METHOD,
            multiday_serving=(_MULTIDAY_METHOD if wants_multiday else
                             "not requested (INTRADAY-only configuration)"),
            longterm_serving=(_LONGTERM_METHOD if r["paper_trading_enabled_long_term"] else
                              "long-term paper lane not enabled for this ticker"),
            v2_collection_scope=v2_scope,
            v2_strategy_eligibility=v2_elig, v2_evidence_status=v2_evi,
            v2_alert_capability=v2_alert, v2_paper_portfolio=v2_paper,
            unsupported_reason=reason,
        ))

    n_active = sum(1 for r in rows if r["status"] == "active")
    n_dual = sum(1 for r in rows if (r["strategy_horizon"] or "") == "DUAL_HORIZON")
    n_polled = sum(1 for c in out if c.v2_collection_scope == "POLLED")
    return {
        "scopes": {
            "1_collection": (f"SEC Form 4 ingested for the resolvable ACTIVE US-listed "
                             f"watchlist -- {n_polled} of {len(rows)} configured tickers. "
                             "NOT broadened by this task."),
            "2_user_alert": (f"owner configured {len(rows)} tickers "
                             f"({n_active} active); {n_dual} with a DUAL_HORIZON "
                             "(intraday + multi-day) preference."),
            "3_frozen_strategy_eligibility": (
                "V2 membership-OR-liquidity, evaluated per-ticker at cluster time. "
                "Frozen; not changed. The configured watchlist is NOT silently substituted "
                "as the V2 execution universe -- see UNIVERSE_CONTRACT_DECISION_REQUIRED."),
            "4_paper_execution_eligibility": (
                "V2 -> v2_lane.db ($300k campaign); Original intraday -> "
                "~/.talonx/paper_trading.db; long-term -> the long-term paper lane. "
                "Separate ledgers, always attributable apart."),
            "5_historical_validation_population": (
                "V2 edge measured on the survivorship S&P panel 2024-09..2026-03 "
                "(Task 116, N=170, net@20 ~+2.2% in-window / +1.01% full-panel per Task 112R). "
                "A paper candidate is NOT a profit guarantee. Intraday & long-term: NO "
                "validated edge population exists."),
        },
        "summary": {
            "configured_tickers": len(rows), "active": n_active,
            "dual_horizon": n_dual, "v2_polled": n_polled,
            "v2_paper_candidates_possible": n_polled,
            "intraday_validated_edge": False, "longterm_validated_edge": False,
        },
        "tickers": [asdict(c) for c in out],
    }


def to_markdown(m: dict[str, Any]) -> str:
    L = ["# CONFIGURED WATCHLIST -> STRATEGY COVERAGE (read-only, honest)", "",
         "**No production universe / ingestion / strategy change.** This is a report.", "",
         "## The five scopes (kept separate)"]
    for k, v in m["scopes"].items():
        L.append(f"- **{k}** -- {v}")
    s = m["summary"]
    L += ["", "## Summary",
          f"- {s['configured_tickers']} configured tickers · {s['active']} active · "
          f"{s['dual_horizon']} DUAL_HORIZON · {s['v2_polled']} in the V2 collection scope",
          f"- intraday validated edge: **{s['intraday_validated_edge']}** · "
          f"long-term validated edge: **{s['longterm_validated_edge']}**",
          f"- V2 is the only PAPER_CANDIDATE; a cluster is rare (~1-2/yr on the polled subset)",
          "", "## Per-ticker map",
          "", "| ticker | horizon | status | V2 scope | V2 eligibility (short) | V2 alert | V2 paper ledger | reason if unsupported |",
          "|---|---|---|---|---|---|---|---|"]
    for c in m["tickers"]:
        elig = c["v2_strategy_eligibility"].split(" -- ")[0].split(":")[0][:48]
        L.append(f"| {c['symbol']} | {c['configured_horizon']} | {c['status']} | "
                 f"{c['v2_collection_scope']} | {elig} | "
                 f"{'yes' if c['v2_collection_scope']=='POLLED' else 'no'} | "
                 f"{'v2_lane.db' if c['v2_collection_scope']=='POLLED' else '--'} | "
                 f"{c['unsupported_reason'] or '--'} |")
    L += ["", "## What the owner can actually rely on today",
          "- **Multi-day**: V2 insider-buy-cluster paper alerts + paper entries on the "
          f"{s['v2_polled']} polled US names, WHEN a >=2-distinct-insider code-P cluster forms "
          "and the issuer clears the frozen liquidity gate. Descriptive; paper only.",
          "- **Intraday**: Original quant BULLISH/BEARISH/BUY/SELL assessments -- informational, "
          "NO validated edge. Not a V2 substitute.",
          "- **Long-term / fundamental**: descriptive Intelligence (risk & event) only -- no "
          "validated trading policy.",
          "", "Applying the configured watchlist as the V2 execution universe is a "
          "GOVERNANCE decision (UNIVERSE_CONTRACT_DECISION_REQUIRED), not a conformance repair; "
          "it is not done here."]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser("talonx_ops.watchlist_coverage")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    m = build_coverage_map()
    print(json.dumps(m, indent=2) if a.json else to_markdown(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
