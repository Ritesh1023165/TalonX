"""
INSIDER_BUY_CLUSTER_V2@1 profitability-first validation (READ-ONLY research; outputs under results/v2_validation/).

Evaluates the FROZEN rule exactly as the live runtime implements it -- nothing here defines a threshold:
  * episodes   talonx_v2.cluster_engine.detect_episodes (code P, >= 2 distinct owner CIKs, 10-trading-day window,
               greedy non-overlapping, fires on the 2nd distinct owner's FILING_DATE; causal = end of that day)
  * eligible   talonx_v2.liquidity.evaluate_liquidity (trailing-20-session median $ volume >= $5M and last close >= $5,
               sessions strictly before entry) -- the runtime's wired branch (no free PIT S&P 400 feed)
  * entry      BUY at the OPEN of eligible_entry_session (first NYSE session strictly after the fire); a bar must exist
  * exit       SELL at the CLOSE of entry + 10 sessions; missing bar -> first available close within 5 more sessions,
               else EXIT_UNRESOLVED (V2Config.exit_fallforward_max_sessions)
  * cost       V2Config.friction_bps = 20 bps round trip (the documented V2 research friction; no daily spread exists)
  * portfolio  V2-PAPER-RC1 assumptions: $100k, $10k per position, max 20 concurrent (cash-bound), no adds,
               5-session per-issuer re-entry cooldown after a SELL, one open position per issuer
Descriptive only: +1/+3/+5 session closes, entry at the entry session's CLOSE (delay sensitivity), SPY and a causal
same-symbol unconditional baseline. Prices: Alpaca SIP daily bars, adjustment=all.

Periods (by activation filing date): DISCOVERY <= 2026-03-31 (the data the rule was frozen from -- NOT validation),
HOLDOUT_2026Q2 2026-04-01..06-30 (SEC Q2 data set, not available to the freeze), POST_Q2 >= 2026-07-01 (EDGAR
per-filing crawl), of which PROSPECTIVE = activation >= 2026-09-07 (after the Task 109 freeze of 2026-09-06).
usage: python -m talonx_paperperf.v2_validation episodes | prices | evaluate
"""
from __future__ import annotations

import collections as C
import importlib.util
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_v2 import calendar as cal  # noqa: E402
from talonx_v2.cluster_engine import detect_episodes  # noqa: E402
from talonx_v2.config import V2_VERSION, V2Config  # noqa: E402
from talonx_v2.form4_source import from_rows  # noqa: E402
from talonx_v2.liquidity import evaluate_liquidity  # noqa: E402

OUT = REPO / "results" / "v2_validation"
STAGE_DEADLINE_ENV = "TALONX_FWD_STAGE_DEADLINE_EPOCH"     # set by forward_runner: no retry may cross it


def atomic_write_text(path: Path, text: str) -> None:
    """Write-then-rename: a crash or a failed stage never leaves a truncated artifact behind (2026-10-05)."""
    import os
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _stage_deadline_monotonic() -> float | None:
    import os
    import time
    v = os.environ.get(STAGE_DEADLINE_ENV)
    return None if not v else time.monotonic() + (float(v) - time.time())
BULK = REPO / "results" / "task107a_form4_feasibility" / "_bulk"
HIST = REPO / "results" / "task107a_form4_feasibility" / "_build" / "form4_open_market_txn.parquet"
CFG = V2Config()
FREEZE_DATE = date(2026, 9, 6)            # Task 109 freeze (3103d89); forward = activation filed after it
HORIZONS = (1, 3, 5, 10)
START_CAPITAL, POSITION_USD = 100_000.0, 10_000.0
PERIODS = (("DISCOVERY", date(2000, 1, 1), date(2026, 3, 31)), ("HOLDOUT_2026Q2", date(2026, 4, 1), date(2026, 6, 30)),
           ("POST_Q2", date(2026, 7, 1), date(2099, 1, 1)))


def period_of(d: date) -> str:
    for name, a, b in PERIODS:
        if a <= d <= b:
            return name
    return "UNKNOWN"


# ============================================================================================================ inputs
def q2_rows() -> list[dict]:
    p = OUT / "txn_2026q2.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    sp = importlib.util.spec_from_file_location("t107a_build", REPO / "research/scripts/task107a_form4_build.py")
    b = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(b)
    rows = b.parse_zip(BULK / "2026q2_form345.zip")
    for r in rows:
        for k in ("filing_date", "trans_date"):
            r[k] = r[k].isoformat() if r[k] else None
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(rows))
    return rows


def all_txn_rows() -> tuple[list[dict], dict]:
    import pandas as pd
    df = pd.read_parquet(HIST)
    hist = df.to_dict("records")
    for r in hist:
        for k in ("filing_date", "trans_date"):
            v = r.get(k)
            r[k] = None if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)[:10]
    q2 = q2_rows()
    from talonx_paperperf import form4_edgar as E
    crawl, cov = E.load(start="2026-07-01")
    # a filing is sourced from exactly one period source (bulk through 06-30, crawl after)
    crawl = [r for r in crawl if r["filing_date"] >= "2026-07-01"]
    src = {"historical_bulk_2019q1_2026q1": len(hist), "bulk_2026q2": len(q2), "edgar_crawl_from_2026_07_01": len(crawl),
           "edgar_crawl_days": len(cov["days"]), "edgar_crawl_filings": cov["filings"],
           "edgar_crawl_failed_filings": cov["failed"],
           "edgar_crawl_last_day": cov["days"][-1] if cov["days"] else None}
    return hist + q2 + crawl, src


def to_records(rows: list[dict]):
    """The runtime's own row -> PurchaseRecord mapping (form4_source.from_rows); code P only."""
    return from_rows([{"symbol": r["issuer_sym"], "issuer_cik": r.get("issuer_cik", ""), "owner_cik": r["owner_cik"],
                       "filing_date": r["filing_date"], "accession": r.get("accession", ""),
                       "transaction_date": r.get("trans_date"), "transaction_value": r.get("value"),
                       "is_officer": bool(r.get("is_officer")), "is_director": bool(r.get("is_director")),
                       "is_ten_percent": bool(r.get("is_ten_pct")), "transaction_code": "P"}
                      for r in rows if str(r.get("code", "")).upper() == "P"])


def build_episodes() -> dict:
    rows, src = all_txn_rows()
    recs = to_records(rows)
    eps = detect_episodes(recs, config=CFG)
    by_ep = C.defaultdict(list)                  # qualifying records per episode for cluster-strength descriptives
    idx = C.defaultdict(list)
    for r in recs:
        idx[r.symbol.upper()].append(r)
    out = []
    for e in eps:
        q = [r for r in idx[e.symbol] if r.owner_cik in e.distinct_owner_ciks
             and e.first_filing_date <= r.filing_date <= e.activation_filing_date]
        tds = [r.transaction_date for r in q if r.transaction_date]
        d = e.to_dict()
        d.update({"period": period_of(e.activation_filing_date),
                  "prospective": e.activation_filing_date > FREEZE_DATE,
                  "filing_lag_days": (e.activation_filing_date - max(tds)).days if tds else None,
                  "density_sessions": cal.session_ordinal(e.activation_filing_date) -
                  cal.session_ordinal(e.first_filing_date),
                  "repeat_purchases": len(q) > len({r.owner_cik for r in q}),
                  "ten_pct_only": all(r.is_ten_percent and not (r.is_officer or r.is_director) for r in q)})
        out.append(d)
    res = {"version": V2_VERSION, "sources": src, "records_code_P": len(recs), "episodes": out}
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUT / "episodes.json", json.dumps(res, default=str))
    return res


# ============================================================================================================ prices
def fetch_prices(symbols: list[str], start: date, end: date, refresh: set[str] = frozenset()) -> None:
    """Alpaca SIP daily bars, adjustment=all, multi-symbol + paginated; cache per symbol in one JSON (resumable)."""
    from talonx_paperperf.rs_phase_a import _alpaca
    from talonx_paperperf.transient_http import resilient_alpaca_get
    data = _alpaca(150)
    # classified transient retries (TLS handshake timeout, resets, 429 + Retry-After, 5xx) REPLACE AlpacaData's 429-only
    # loop; the limiter is re-acquired per retry; no retry crosses the runner's stage deadline (2026-10-05)
    data._get = resilient_alpaca_get(limiter=data.limiter, deadline=_stage_deadline_monotonic())
    p = OUT / "daily_bars.json"
    have = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    import re as _re
    ok = _re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")
    malformed = sorted(s for s in set(symbols) if not ok.match(s))        # e.g. '"OMEX"': never priceable
    need = [s for s in sorted(set(symbols)) if (s not in have or s in refresh) and ok.match(s)]
    print(json.dumps({"malformed_symbols_unpriceable": len(malformed), "examples": malformed[:10]}), flush=True)
    import re
    rejected = []
    for i in range(0, len(need), 100):
        batch = need[i:i + 100]
        got: dict[str, list] = {s: [] for s in batch}
        token = None
        while True:
            params = {"symbols": ",".join(batch), "timeframe": "1Day", "start": start.isoformat(),
                      "end": end.isoformat(), "feed": "sip", "adjustment": "all", "limit": "10000"}
            if token:
                params["page_token"] = token
            try:
                j = data._call("https://data.alpaca.markets/v2/stocks/bars", params)
            except RuntimeError as ex:                       # one unknown symbol fails the batch: drop it, retry
                m = re.search(r'invalid symbol: \W*([A-Za-z0-9.\-]+)', str(ex))
                if not m or m.group(1) not in batch:
                    raise
                batch.remove(m.group(1))
                rejected.append(m.group(1))
                got = {s: [] for s in list(got)}             # restart the batch from page 1 (no partial merge)
                token = None
                continue
            for s, bars in (j.get("bars") or {}).items():
                got.setdefault(s, []).extend([b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars)
            token = j.get("next_page_token")
            if not token:
                break
        have.update(got)
        if (i // 100) % 10 == 9 or i + 100 >= len(need):
            atomic_write_text(p, json.dumps(have))
            print(json.dumps({"fetched": min(i + 100, len(need)), "of": len(need)}), flush=True)


# ============================================================================================================ evaluation
def bars_map(raw: list) -> dict[date, tuple]:
    return {date.fromisoformat(b[0]): tuple(b[1:]) for b in raw}


def close_at_or_after(bm: dict, d: date, last: date):
    """Close of session d, else the first available close within the fall-forward limit (never backwards)."""
    for k in range(CFG.exit_fallforward_max_sessions + 1):
        s = cal.add_sessions(d, k)
        if s > last:
            return None, None, "PENDING"
        if s in bm:
            return bm[s][3], s, "OK" if k == 0 else f"FALL_FORWARD_{k}"
    return None, None, "EXIT_UNRESOLVED"


def evaluate_episode(e: dict, bm: dict, spy: dict, last: date) -> dict:
    E = date.fromisoformat(e["eligible_entry_session"])
    r = {k: e[k] for k in ("episode_id", "symbol", "issuer_cik", "period", "prospective", "activation_filing_date",
                           "n_distinct_owners", "n_filings", "aggregate_purchase_value", "any_officer", "any_director",
                           "any_ten_percent", "ten_pct_only", "filing_lag_days", "density_sessions",
                           "repeat_purchases")}
    r["entry_session"] = E.isoformat()
    if E > last:
        r["status"] = "PENDING_ENTRY"
        return r
    lq = evaluate_liquidity([{"date": d, "close": b[3], "volume": b[4]} for d, b in bm.items()], entry_session=E,
                            config=CFG)
    r["liq_reason"], r["median_dv"], r["last_close"] = lq.reason, lq.median_dollar_volume, lq.last_close
    if not lq.ok:
        r["status"] = "INELIGIBLE_LIQUIDITY"
        return r
    if E not in bm:
        r["status"] = "NOT_PRICEABLE_ON_ENTRY"
        return r
    op = bm[E][0]
    r["entry_open"] = op
    r["status"] = "EVALUATED"
    for h in HORIZONS:
        c, s, st = close_at_or_after(bm, cal.add_sessions(E, h), last)
        r[f"g{h}"] = None if c is None else c / op - 1.0
        r[f"s{h}"] = st
        if h == CFG.hold_trading_days:
            r["exit_session"] = s.isoformat() if s else None
            if s and E in spy and s in spy:
                r["spy10"] = spy[s][3] / spy[E][0] - 1.0
            if s:
                path = [bm[d] for d in bm if E <= d <= s]
                r["mfe10"] = max(b[1] for b in path) / op - 1.0
                r["mae10"] = min(b[2] for b in path) / op - 1.0
                r["g10_entry_close"] = c / bm[E][3] - 1.0          # delay sensitivity: enter at E's close
    if r.get("g10") is not None:
        r["net10"] = r["g10"] - CFG.friction_bps / 1e4
        # causal same-symbol unconditional baseline: every 10-session open->close window that ENDED before E
        ds = sorted(d for d in bm if d < E)[-260:]
        base = []
        for i, d in enumerate(ds):
            if i + CFG.hold_trading_days < len(ds):
                base.append(bm[ds[i + CFG.hold_trading_days]][3] / bm[d][0] - 1.0)
        r["same_symbol_uncond10"] = statistics.mean(base) if len(base) >= 100 else None
        spyd = sorted(d for d in spy if d < E)
        r["spy_above_200d"] = (spy[spyd[-1]][3] > statistics.mean(spy[d][3] for d in spyd[-200:])) \
            if len(spyd) >= 200 else None
    return r


def stats(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    w = [x for x in xs if x > 0]
    los = [x for x in xs if x <= 0]
    return {"n": len(xs), "mean_pct": round(100 * statistics.mean(xs), 3),
            "median_pct": round(100 * statistics.median(xs), 3), "win_rate": round(len(w) / len(xs), 3),
            "profit_factor": round(sum(w) / -sum(los), 3) if los and sum(los) < 0 else None}


def concentration(rows: list[dict], key="net10") -> dict:
    xs = sorted(((r[key], r["symbol"], r["entry_session"]) for r in rows if r.get(key) is not None), reverse=True)
    if not xs:
        return {}
    tot = sum(x[0] for x in xs)
    out = {"total_pct_points": round(100 * tot, 2)}
    for k in (1, 3, 5):
        out[f"top{k}_contribution_pp"] = round(100 * sum(x[0] for x in xs[:k]), 2)
        out[f"top{k}_share_of_total"] = round(sum(x[0] for x in xs[:k]) / tot, 3) if tot > 0 else None
        out[f"mean_without_best_{k}_pct"] = round(100 * (tot - sum(x[0] for x in xs[:k])) / (len(xs) - k), 3) \
            if len(xs) > k else None
    out["best"] = [(s, d, round(100 * v, 2)) for v, s, d in xs[:5]]
    out["worst"] = [(s, d, round(100 * v, 2)) for v, s, d in xs[-5:]]
    return out


def group(rows, fn, min_n=20) -> dict:
    g = C.defaultdict(list)
    for r in rows:
        g[fn(r)].append(r)
    return {str(k): {**stats([x["g10"] for x in v]), "net_mean_pct": stats([x["net10"] for x in v]).get("mean_pct"),
                     "small_bucket": len(v) < min_n}
            for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def portfolio(rows: list[dict], bars: dict, *, start_cash=START_CAPITAL, pos_usd=POSITION_USD) -> dict:
    """Chronological V2 paper book on the priced, resolved +10 trades. Entries at the open (cash freed by a close
    the same day is not reusable until the next day), exits at the close. Daily mark-to-market equity."""
    trades = sorted((r for r in rows if r.get("g10") is not None and r.get("exit_session")),
                    key=lambda r: (r["entry_session"], r["symbol"]))
    if not trades:
        return {}
    days = sorted({d for r in trades for d in (r["entry_session"], r["exit_session"])})
    first, lastd = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    sessions, d = [], first
    while d <= lastd:
        sessions.append(d)
        d = cal.add_sessions(d, 1)
    by_entry = C.defaultdict(list)
    for r in trades:
        by_entry[r["entry_session"]].append(r)
    cash, open_, cooldown, taken, skipped = start_cash, {}, {}, [], C.Counter()
    eq_curve, util = [], []
    fr = CFG.friction_bps / 1e4
    for d in sessions:
        ds = d.isoformat()
        for r in by_entry.get(ds, []):
            sym = r["symbol"]
            if sym in open_:
                skipped["OPEN_POSITION_IN_ISSUER"] += 1
                continue
            if sym in cooldown and d <= cooldown[sym]:
                skipped["REENTRY_COOLDOWN"] += 1
                continue
            if len(open_) >= CFG.max_concurrent_positions:
                skipped["MAX_CONCURRENT_20"] += 1
                continue
            if cash < pos_usd:
                skipped["INSUFFICIENT_CASH"] += 1
                continue
            cash -= pos_usd
            open_[sym] = (r, pos_usd / r["entry_open"])
        for sym in [s for s, (r, _) in open_.items() if r["exit_session"] == ds]:
            r, sh = open_.pop(sym)
            proceeds = pos_usd * (1 + r["g10"])
            cash += proceeds - pos_usd * fr
            taken.append({"symbol": sym, "entry": r["entry_session"], "exit": ds, "gross_usd": pos_usd * r["g10"],
                          "net_usd": pos_usd * (r["g10"] - fr)})
            cooldown[sym] = cal.add_sessions(d, CFG.reentry_cooldown_trading_days)
        mtm = 0.0
        for sym, (r, sh) in open_.items():
            bm = bars.get(sym, {})
            px = bm[d][3] if d in bm else None
            mtm += sh * px if px else pos_usd
        eq_curve.append(cash + mtm)
        util.append(len(open_) * pos_usd / (cash + mtm) if cash + mtm > 0 else 0)
    peak, mdd = -1e18, 0.0
    for v in eq_curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    g = sum(t["gross_usd"] for t in taken)
    n = sum(t["net_usd"] for t in taken)
    wins = [t["net_usd"] for t in taken if t["net_usd"] > 0]
    loss = [t["net_usd"] for t in taken if t["net_usd"] <= 0]
    return {"STARTING_CAPITAL": start_cash, "POSITION_SIZE": pos_usd,
            "MAX_CONCURRENT_POSITIONS": f"{CFG.max_concurrent_positions} (contract; cash-bound at "
                                        f"{int(start_cash // pos_usd)})",
            "HOLDING_PERIOD": f"{CFG.hold_trading_days} sessions", "trades_taken": len(taken),
            "skipped": dict(skipped), "CAPITAL_UTILIZATION_mean": round(statistics.mean(util), 3),
            "GROSS_PNL": round(g, 2), "NET_PNL": round(n, 2), "ENDING_CAPITAL": round(eq_curve[-1], 2),
            "MAX_DRAWDOWN_pct_mark_to_market": round(100 * mdd, 2),
            "PROFIT_FACTOR": round(sum(wins) / -sum(loss), 3) if loss and sum(loss) < 0 else None,
            "EXPECTANCY_PER_TRADE_USD": round(n / len(taken), 2) if taken else None,
            "first_entry": days[0], "last_exit": days[-1]}


def summarize(rows: list[dict], bars: dict, label: str) -> dict:
    ev = [r for r in rows if r.get("g10") is not None]
    res = {"label": label, "episodes_evaluated_+10": len(ev),
           "unique_symbols": len({r["symbol"] for r in ev}),
           "unique_entry_sessions": len({r["entry_session"] for r in ev})}
    if not ev:
        return res
    res["sample_start"] = min(r["entry_session"] for r in ev)
    res["sample_end"] = max(r["entry_session"] for r in ev)
    res["horizons_gross"] = {f"+{h}": stats([r.get(f"g{h}") for r in ev]) for h in HORIZONS}
    res["horizons_net"] = {f"+{h}": stats([None if r.get(f"g{h}") is None else r[f"g{h}"] - CFG.friction_bps / 1e4
                                           for r in ev]) for h in HORIZONS}
    res["PRIMARY_+10"] = {"gross": stats([r["g10"] for r in ev]), "net": stats([r["net10"] for r in ev]),
                          "mfe_mean_pct": round(100 * statistics.mean(r["mfe10"] for r in ev), 3),
                          "mae_mean_pct": round(100 * statistics.mean(r["mae10"] for r in ev), 3),
                          "mfe_median_pct": round(100 * statistics.median(r["mfe10"] for r in ev), 3),
                          "mae_median_pct": round(100 * statistics.median(r["mae10"] for r in ev), 3)}
    res["ENTRY_DELAY_SENSITIVITY (entry at entry-session CLOSE, same exit)"] = stats(
        [r.get("g10_entry_close") for r in ev])
    spy = [r for r in ev if r.get("spy10") is not None]
    res["BASELINES"] = {"zero": 0.0,
                        "SPY_same_window_mean_pct": round(100 * statistics.mean(r["spy10"] for r in spy), 3),
                        "excess_vs_SPY_mean_pct": round(100 * statistics.mean(r["g10"] - r["spy10"] for r in spy), 3),
                        "excess_vs_SPY_win": round(sum(1 for r in spy if r["g10"] > r["spy10"]) / len(spy), 3)}
    ss = [r for r in ev if r.get("same_symbol_uncond10") is not None]
    if ss:
        res["BASELINES"].update({
            "same_symbol_uncond10_mean_pct (prior-year, causal)": round(100 * statistics.mean(
                r["same_symbol_uncond10"] for r in ss), 3),
            "excess_vs_same_symbol_mean_pct": round(100 * statistics.mean(
                r["g10"] - r["same_symbol_uncond10"] for r in ss), 3), "n": len(ss)})
    res["CONCENTRATION"] = concentration(ev)
    res["BY_SYMBOL_top_contributors_pp"] = sorted(
        ((s, round(100 * sum(r["net10"] for r in ev if r["symbol"] == s), 2), sum(1 for r in ev if r["symbol"] == s))
         for s in {r["symbol"] for r in ev}), key=lambda x: -x[1])[:8]
    res["BY_YEAR"] = group(ev, lambda r: r["entry_session"][:4], 10)
    res["BY_QUARTER_2025_2026"] = group([r for r in ev if r["entry_session"] >= "2025"],
                                        lambda r: f"{r['entry_session'][:4]}Q{(int(r['entry_session'][5:7]) - 1) // 3 + 1}", 10)
    res["CLUSTER_STRENGTH"] = {
        "n_distinct_owners": group(ev, lambda r: min(r["n_distinct_owners"], 4)),
        "aggregate_value": group(ev, lambda r: "a <100k" if r["aggregate_purchase_value"] < 1e5 else
                                 "b 100k-250k" if r["aggregate_purchase_value"] < 2.5e5 else
                                 "c 250k-1M" if r["aggregate_purchase_value"] < 1e6 else "d >=1M"),
        "density_sessions_first_to_activation": group(ev, lambda r: "0-2" if r["density_sessions"] <= 2 else
                                                      "3-5" if r["density_sessions"] <= 5 else "6-10"),
        "filing_lag_days": group(ev, lambda r: "unknown" if r["filing_lag_days"] is None else
                                 "0-2" if r["filing_lag_days"] <= 2 else "3-5" if r["filing_lag_days"] <= 5 else ">5"),
        "role": group(ev, lambda r: "officer" if r["any_officer"] else "director_only" if r["any_director"] else
                      "ten_pct_only" if r["ten_pct_only"] else "other"),
        "repeat_purchases": group(ev, lambda r: r["repeat_purchases"])}
    res["LIQUIDITY"] = {
        "price_band": group(ev, lambda r: "a 5-10" if r["entry_open"] < 10 else "b 10-20" if r["entry_open"] < 20
                            else "c 20-50" if r["entry_open"] < 50 else "d >=50"),
        "median_dollar_volume": group(ev, lambda r: "a 5-20M" if r["median_dv"] < 2e7 else "b 20-100M"
                                      if r["median_dv"] < 1e8 else "c >=100M")}
    res["REGIME_SPY_above_200d"] = group(ev, lambda r: r.get("spy_above_200d"))
    res["PORTFOLIO_RC1"] = portfolio(ev, bars)
    return res


def event_quality() -> dict:
    """Contamination check of the inputs: the detector keeps code P only; how clean are the code-P rows?"""
    rows, _ = all_txn_rows()
    p = [r for r in rows if str(r.get("code", "")).upper() == "P"]
    n = len(p)
    return {"code_P_rows": n, "code_S_rows_excluded": sum(1 for r in rows if str(r.get("code", "")).upper() == "S"),
            "other_codes": "not ingested (grants/exercises/tax/gifts/derivatives never enter)",
            "P_missing_or_zero_price_pct": round(100 * sum(1 for r in p if not r.get("price")) / n, 2),
            "P_missing_value_pct": round(100 * sum(1 for r in p if not r.get("value")) / n, 2),
            "P_amendment_pct": round(100 * sum(1 for r in p if r.get("is_amendment")) / n, 2),
            "P_indirect_pct": round(100 * sum(1 for r in p if r.get("direct_indirect") == "I") / n, 2),
            "P_ten_pct_owner_pct": round(100 * sum(1 for r in p if r.get("is_ten_pct")) / n, 2),
            "P_missing_owner_cik": sum(1 for r in p if not r.get("owner_cik"))}


def intersections(rows: list[dict]) -> dict:
    """DTU + V2-scope intersection of the V2-eligible (liquidity-passing, priced) episodes.
    DTU_V1 has NO Form 4 trigger (GAP >= 3 % and 8-K only), so outside the Core a V2 name is active only by
    coincidence (or as OPERATOR_ADDED when in V2 scope). Historical episodes predate DTU: they are classified against
    the production 2026-09-30 D-1 snapshot as a STATIC PROXY (labelled), not a causal replay."""
    import sqlite3
    from talonx_premarket import __main__ as M
    M._env()
    scope = set(M._v2_scope(None))
    m = sqlite3.connect(f"file:{REPO / 'results' / 'opportunity' / 'market.db'}?mode=ro", uri=True)
    snap = {s: st for s, st in m.execute("SELECT symbol, state FROM dtu_snapshot WHERE window_id='2026-09-30'")}
    prom = {s for (s,) in m.execute("SELECT DISTINCT symbol FROM dtu_promotions WHERE window_id='2026-09-30'")}
    elig = [r for r in rows if r.get("status") == "EVALUATED" or r.get("status") == "PENDING_ENTRY"
            and r.get("liq_reason") == "PASS"]
    out = {}
    for label, sub in (("ALL_V2_ELIGIBLE", [r for r in rows if r.get("liq_reason") == "PASS"]),
                       ("UNSEEN_V2_ELIGIBLE", [r for r in rows if r.get("liq_reason") == "PASS"
                                               and r["period"] != "DISCOVERY"])):
        st = C.Counter()
        for r in sub:
            s = r["symbol"]
            if s in scope:
                st["OPERATOR_ADDED (V2 scope)"] += 1
            elif snap.get(s) == "ACTIVE_CORE":
                st["ACTIVE_CORE"] += 1
            elif snap.get(s) == "EVENT_ELIGIBLE":
                st["EVENT_ELIGIBLE (active only if a gap/8-K trigger coincides; no Form 4 trigger)"] += 1
            elif snap.get(s) == "AUTO_EXCLUDED":
                st["AUTO_EXCLUDED"] += 1
            else:
                st[f"{snap.get(s) or 'NOT_IN_UNIVERSE'}"] += 1
        n = len(sub)
        kept = st["OPERATOR_ADDED (V2 scope)"] + st["ACTIVE_CORE"]
        out[label] = {"INSIDER_EVENTS_TOTAL": n, "by_state_STATIC_PROXY_2026-09-30": dict(st.most_common()),
                      "DTU_RETAINED (Core or V2 scope)": kept,
                      "DTU_EVENT_PROMOTED_POSSIBLE (event-eligible, trigger-dependent)":
                          st["EVENT_ELIGIBLE (active only if a gap/8-K trigger coincides; no Form 4 trigger)"],
                      "DTU_MISSED (not Core, not scope)": n - kept,
                      "V2_SCOPE_COUNT": len(scope), "QUALIFYING_CLUSTER_EVENTS_IN_V2_SCOPE":
                          sum(1 for r in sub if r["symbol"] in scope),
                      "QUALIFYING_CLUSTER_EVENTS_OUTSIDE_V2_SCOPE": sum(1 for r in sub if r["symbol"] not in scope)}
    live = [r for r in rows if r.get("liq_reason") == "PASS" and "2026-09-28" <= r["entry_session"] <= "2026-09-30"]
    out["LIVE_DTU_WINDOW_EVENTS (entry 09-28..09-30)"] = [
        {"symbol": r["symbol"], "entry": r["entry_session"], "v2_scope": r["symbol"] in scope,
         "dtu_09_30": snap.get(r["symbol"]), "promoted_09_30": r["symbol"] in prom} for r in live]
    in_scope_eval = [r for r in rows if r.get("g10") is not None and r["symbol"] in scope]
    out["V2_SCOPE_SUBSET_+10_all_periods"] = {**stats([r["net10"] for r in in_scope_eval]),
                                              "symbols": sorted({r["symbol"] for r in in_scope_eval})}
    return out


def evaluate() -> dict:
    E = json.loads((OUT / "episodes.json").read_text(encoding="utf-8"))
    raw = json.loads((OUT / "daily_bars.json").read_text(encoding="utf-8"))
    bars = {s: bars_map(v) for s, v in raw.items()}
    spy = bars["SPY"]
    last = max(spy)
    rows = [evaluate_episode(e, bars.get(e["symbol"], {}), spy, last) for e in E["episodes"]]
    st = C.Counter((r["period"], r["status"]) for r in rows)
    res = {"version": V2_VERSION, "sources": E["sources"], "bars_last_session": last.isoformat(),
           "status_by_period": {f"{a}|{b}": n for (a, b), n in sorted(st.items())},
           "liquidity_fail_reasons": dict(C.Counter(r["liq_reason"].split("_")[0] + "_" + r["liq_reason"].split("_")[1]
                                                    if r.get("liq_reason", "PASS") != "PASS" else "PASS"
                                                    for r in rows if r.get("liq_reason")).most_common(6)),
           "unresolved_or_fallforward": dict(C.Counter(r.get("s10") for r in rows if r.get("s10") not in (None, "OK")))}
    for name in ("DISCOVERY", "HOLDOUT_2026Q2", "POST_Q2"):
        res[name] = summarize([r for r in rows if r["period"] == name], bars, name)
    res["PROSPECTIVE_after_freeze"] = summarize([r for r in rows if r["prospective"]], bars, "PROSPECTIVE")
    res["ALL_UNSEEN (HOLDOUT_2026Q2 + POST_Q2)"] = summarize(
        [r for r in rows if r["period"] in ("HOLDOUT_2026Q2", "POST_Q2")], bars, "ALL_UNSEEN")
    res["DTU_AND_V2_SCOPE"] = intersections(rows)
    res["EVENT_QUALITY"] = event_quality()
    atomic_write_text(OUT / "rows.json", json.dumps(rows, default=str))
    atomic_write_text(OUT / "evaluation.json", json.dumps(res, indent=1, default=str))
    return res


def forward() -> dict:
    """SHADOW-only forward tracker: every episode whose activation filing is after the 2026-09-06 freeze, with its
    entry, +1/+3/+5/+10 outcomes and cost-adjusted primary result (resolved as bars arrive). Writes
    results/v2_validation/forward/<today>.json. Sends nothing; changes no V2 state."""
    import glob
    import os
    rows = json.loads((OUT / "rows.json").read_text(encoding="utf-8"))
    panel = {os.path.basename(p)[:-4] for p in glob.glob(str(REPO / "results/task95g_broad_cross_sectional/_daily/*.csv"))}
    fw = [r for r in rows if r.get("prospective")]
    keep = ("episode_id", "symbol", "activation_filing_date", "entry_session", "status", "liq_reason", "entry_open",
            "g1", "g3", "g5", "g10", "net10", "s10", "exit_session", "spy10", "n_distinct_owners",
            "aggregate_purchase_value")
    ev = [r for r in fw if r.get("g10") is not None]
    out = {"as_of": date.today().isoformat(), "version": V2_VERSION, "freeze": FREEZE_DATE.isoformat(),
           "episodes_after_freeze": len(fw), "v2_eligible": sum(1 for r in fw if r.get("liq_reason") == "PASS"),
           "resolved_+10": len(ev), "primary_net_+10": stats([r["net10"] for r in ev]),
           "primary_gross_+10": stats([r["g10"] for r in ev]),
           "sp500_panel_subset_net_+10": stats([r["net10"] for r in ev if r["symbol"] in panel]),
           "open_or_pending": sum(1 for r in fw if r.get("liq_reason") == "PASS" and r.get("g10") is None),
           "rows": [{k: r.get(k) for k in keep} | {"sp500_panel": r["symbol"] in panel} for r in fw]}
    d = OUT / "forward"
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_text(d / f"{out['as_of']}.json", json.dumps(out, indent=1, default=str))
    return out


def main(argv):
    if argv[0] == "episodes":
        r = build_episodes()
        print(json.dumps({"sources": r["sources"], "records_code_P": r["records_code_P"],
                          "episodes": len(r["episodes"]),
                          "by_period": dict(C.Counter(e["period"] for e in r["episodes"])),
                          "prospective": sum(1 for e in r["episodes"] if e["prospective"])}, indent=1))
    elif argv[0] == "prices":
        E = json.loads((OUT / "episodes.json").read_text(encoding="utf-8"))
        syms = sorted({e["symbol"] for e in E["episodes"]} | {"SPY"})
        recent = {e["symbol"] for e in E["episodes"] if e["eligible_entry_session"] >= "2026-08-01"} | {"SPY"}
        fetch_prices(syms, date(2018, 11, 1), date.today() - timedelta(days=1), refresh=recent)
    elif argv[0] == "forward":
        r = forward()
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1, default=str))
    elif argv[0] == "evaluate":
        r = evaluate()
        print(json.dumps({k: v for k, v in r.items()}, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main(sys.argv[1:])
