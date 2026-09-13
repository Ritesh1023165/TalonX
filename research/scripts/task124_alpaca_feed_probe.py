"""
TASK 124 Part 3 -- small, bounded probes of EXISTING free Alpaca access,
reusing the exact request/credential pattern already established by
research/scripts/task63r_probe_alpaca_feeds.py (release worktree) --
no new provider integration, no bulk download, no strategy-return
inspection. Every probe reports HTTP status, row counts, and timestamp
coverage only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RELEASE_ROOT))

OUT = RESEARCH_ROOT / "results" / "task124_intraday_feasibility"
OUT.mkdir(parents=True, exist_ok=True)


def _fetch(symbol: str, start: str, end: str, *, feed: str | None, adjustment: str = "raw",
          timeframe: str = "1Min") -> dict:
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    params = {"timeframe": timeframe, "start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z",
             "limit": 10000, "adjustment": adjustment}
    if feed is not None:
        params["feed"] = feed
    resp = requests.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                        headers=headers, params=params, timeout=30)
    result = {"symbol": symbol, "start": start, "end": end, "feed_parameter": feed or "omitted",
             "adjustment": adjustment, "timeframe": timeframe, "http_status": resp.status_code}
    if resp.status_code != 200:
        try:
            result["error"] = resp.json().get("message", resp.text)
        except ValueError:
            result["error"] = resp.text
        result["classification"] = "REQUEST_ERROR"
        return result
    body = resp.json()
    bars = body.get("bars") or []
    result["n_bars"] = len(bars)
    result["next_page_token"] = body.get("next_page_token")
    if not bars:
        result["classification"] = "EMPTY_RESPONSE"
        return result
    ts = pd.to_datetime([b["t"] for b in bars], utc=True)
    result["first_ts"] = ts.min().isoformat()
    result["last_ts"] = ts.max().isoformat()
    result["distinct_dates"] = sorted({t.date().isoformat() for t in ts})
    result["classification"] = "DATA_PRESENT"
    return result


def probe_1_already_covered(sym: str = "AAPL", date_: str = "2025-02-05") -> dict:
    """Confirm the ALREADY-DOWNLOADED task93_canonical_v1 data matches a
    fresh fetch on a known-covered date (feed identity + timestamp
    semantics sanity check) -- via SIP (the manifest's own claimed feed)."""
    live = _fetch(sym, date_, date_, feed="sip", adjustment="raw")
    persisted_path = RELEASE_ROOT / f"results/task93_alpha_foundation/_canonical_data/{sym}.csv"
    persisted_n = 0
    if persisted_path.exists():
        df = pd.read_csv(persisted_path, usecols=["timestamp"], parse_dates=["timestamp"])
        persisted_n = int((df["timestamp"].dt.date == pd.Timestamp(date_).date()).sum())
    return {"probe": "1_already_covered", "live": live, "persisted_row_count_same_date": persisted_n}


def probe_2_older_period(sym: str = "AAPL", date_: str = "2024-03-01") -> dict:
    """Historical minute-data retention: a date BEFORE task93's own window
    start (2025-01-24) -- does free SIP/IEX minute history extend back
    this far at all?

    NOTE: an earlier run of this probe used date_="2024-01-15", which is
    Martin Luther King Jr. Day (a U.S. market holiday, no trading) -- it
    returned EMPTY_RESPONSE on both feeds, which was a test-date-selection
    artifact, not a genuine retention/entitlement finding. Corrected here
    to an ordinary trading day; see docs/research/TASK124_INTRADAY_DATA_FEASIBILITY.md
    Part 3 for the full retention sweep (2020-03-02 .. 2024-03-01) run
    ad hoc to establish retention depth beyond this one persisted date."""
    sip = _fetch(sym, date_, date_, feed="sip", adjustment="raw")
    iex = _fetch(sym, date_, date_, feed="iex", adjustment="raw")
    return {"probe": "2_older_period", "sip": sip, "iex": iex}


def probe_3_missing_active_ticker(sym: str = "SPCX", date_: str = "2025-06-02") -> dict:
    """A currently-active configured ticker with NO located existing
    daily/minute coverage in any local dataset -- does Alpaca have any
    bars for it at all (entitlement vs. genuinely no trading history)?"""
    sip = _fetch(sym, date_, date_, feed="sip", adjustment="raw")
    iex = _fetch(sym, date_, date_, feed="iex", adjustment="raw")
    return {"probe": "3_missing_active_ticker", "symbol": sym, "sip": sip, "iex": iex}


def probe_2b_retention_depth(sym: str = "AAPL",
                             dates: tuple[str, ...] = ("2023-03-01", "2022-03-01", "2020-03-02")) -> dict:
    """Follow-up to probe 2: how far back does SIP minute retention
    actually extend? Persists the ad-hoc retention sweep performed
    during this task's investigation so the finding is reproducible
    from the committed script, not only from shell history."""
    return {"probe": "2b_retention_depth", "symbol": sym,
           "by_date": {d: _fetch(sym, d, d, feed="sip", adjustment="raw") for d in dates}}


def probe_3b_other_missing_tickers(date_: str = "2023-03-01",
                                   syms: tuple[str, ...] = ("STX", "SHOP", "BABA")) -> dict:
    """Follow-up to probe 3: is SPCX's thinness representative of ALL
    currently-uncovered active tickers, or specific to SPCX? Checks two
    OTHER active-but-locally-uncovered names (SHOP, BABA) plus one
    already-covered name (STX) as a control, all on the same date."""
    return {"probe": "3b_other_missing_tickers", "date": date_,
           "by_symbol": {s: _fetch(s, date_, date_, feed="sip", adjustment="raw") for s in syms}}


def probe_4_corporate_action(sym: str = "JPM", ex_date: str = "2025-04-04") -> dict:
    """A known corporate-action-adjacent interval (a regular quarterly
    ex-dividend date for an existing, well-covered dividend payer) --
    confirms adjustment=raw vs adjustment=all actually differ as
    expected, using DAILY bars only (a tiny, single-symbol request)."""
    lo = (pd.Timestamp(ex_date) - pd.Timedelta(days=5)).date().isoformat()
    hi = (pd.Timestamp(ex_date) + pd.Timedelta(days=5)).date().isoformat()
    raw = _fetch(sym, lo, hi, feed="sip", adjustment="raw", timeframe="1Day")
    allj = _fetch(sym, lo, hi, feed="sip", adjustment="all", timeframe="1Day")
    return {"probe": "4_corporate_action_adjustment_check", "symbol": sym, "ex_date_window": [lo, hi],
           "adjustment_raw": raw, "adjustment_all": allj}


def main() -> int:
    load_dotenv(RELEASE_ROOT / ".env", override=False)
    if "APCA_API_KEY_ID" not in os.environ or "APCA_API_SECRET_KEY" not in os.environ:
        print(json.dumps({"error": "APCA credentials not present in environment -- aborting, no probe run"}))
        return 1

    results = {
        "task": "124", "diagnostic_only": True, "strategy_returns_inspected": False,
        "probe_1_already_covered": probe_1_already_covered(),
        "probe_2_older_period": probe_2_older_period(),
        "probe_2b_retention_depth": probe_2b_retention_depth(),
        "probe_3_missing_active_ticker": probe_3_missing_active_ticker(),
        "probe_3b_other_missing_tickers": probe_3b_other_missing_tickers(),
        "probe_4_corporate_action": probe_4_corporate_action(),
    }
    out_path = OUT / "alpaca_feed_probe.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    # print a credential-free summary only
    summary = {}
    for k, v in results.items():
        if not isinstance(v, dict):
            continue
        summary[k] = {kk: (vv.get("classification") if isinstance(vv, dict) else vv)
                     for kk, vv in v.items() if kk in ("sip", "iex", "live", "adjustment_raw", "adjustment_all")}
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
