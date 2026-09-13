"""
TASK 125 Part 2 -- resolve task93_canonical_v1's missing feed identity
from CONTEMPORANEOUS ACQUISITION CODE first (not from comparing prices/
row counts alone), then run one small confirmatory live probe.

Code-based finding (see docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md
Part 2 for the full citation trail): all three of task93's declared
sources (task63_orpb_v1_validation, task61r_fprc_v1_validation,
task7b_alpaca_long_history) route through the SAME shared
`scripts/download_historical_1m.py::fetch_alpaca`, whose Alpaca request
params never include a `feed` key at all:

    params = {"timeframe": "1Min", "start": ..., "end": ...,
              "limit": 10000, "adjustment": "raw"}

Alpaca's own API serves the account's DEFAULT feed when `feed` is
omitted -- for an account without a live SIP subscription that default
is IEX. This script's confirmatory probe issues the EXACT same
omitted-feed request the original code made, alongside explicit
feed=sip and feed=iex requests for the same symbol/date, and compares
bar-for-bar (count, timestamps, OHLCV) to see which explicit feed the
omitted-feed response matches -- confirmation of the code-based finding,
not a substitute for it.

Also checks basic Alpaca availability for the 5 candidate "new" symbols
identified in Task124 (BABA, BLSH, SHOP, SKHY, SPCX) before any bulk
acquisition is attempted -- SKHY is a Korea Exchange (KRX) listing, not
a US security, and is expected to be unavailable through this provider.
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

OUT = RESEARCH_ROOT / "results" / "task125_intraday_extension"
OUT.mkdir(parents=True, exist_ok=True)


def _fetch(symbol: str, start: str, end: str, *, feed, adjustment: str = "raw",
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
    result = {"symbol": symbol, "start": start, "end": end, "feed_parameter": feed or "OMITTED",
             "adjustment": adjustment, "http_status": resp.status_code}
    if resp.status_code != 200:
        try:
            result["error"] = resp.json().get("message", resp.text)
        except ValueError:
            result["error"] = resp.text
        result["classification"] = "REQUEST_ERROR"
        return result
    body = resp.json()
    bars = body.get("bars")
    if bars is None:
        result["classification"] = "NO_ENTITLEMENT_OR_UNKNOWN_SYMBOL"
        result["n_bars"] = 0
        return result
    result["n_bars"] = len(bars)
    if not bars:
        result["classification"] = "EMPTY_RESPONSE"
        return result
    ts = pd.to_datetime([b["t"] for b in bars], utc=True)
    result["classification"] = "DATA_PRESENT"
    result["first_ts"] = ts.min().isoformat()
    result["last_ts"] = ts.max().isoformat()
    # fingerprint for bar-for-bar comparison: (t, o, h, l, c, v) tuples
    result["bar_fingerprint_sha256"] = __import__("hashlib").sha256(
        json.dumps([[b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars],
                  sort_keys=False).encode()).hexdigest()
    return result


def probe_feed_identity(sym: str = "AAPL", date_: str = "2025-02-05") -> dict:
    """The exact date/symbol already used in Task124 probe 1 (an
    already-covered date within task93's window) -- issues the SAME
    omitted-feed request the legacy code made, plus explicit sip/iex,
    and compares."""
    omitted = _fetch(sym, date_, date_, feed=None)
    sip = _fetch(sym, date_, date_, feed="sip")
    iex = _fetch(sym, date_, date_, feed="iex")
    matches_sip = (omitted.get("bar_fingerprint_sha256") == sip.get("bar_fingerprint_sha256")
                  and omitted.get("classification") == "DATA_PRESENT")
    matches_iex = (omitted.get("bar_fingerprint_sha256") == iex.get("bar_fingerprint_sha256")
                  and omitted.get("classification") == "DATA_PRESENT")
    return {"probe": "feed_identity_confirmation", "symbol": sym, "date": date_,
           "omitted_feed_param": omitted, "explicit_sip": sip, "explicit_iex": iex,
           "omitted_matches_sip_bar_for_bar": matches_sip,
           "omitted_matches_iex_bar_for_bar": matches_iex,
           "conclusion": ("OMITTED_FEED_IS_IEX" if matches_iex and not matches_sip else
                         "OMITTED_FEED_IS_SIP" if matches_sip and not matches_iex else
                         "AMBIGUOUS_OR_IDENTICAL_ACROSS_FEEDS")}


def probe_new_symbol_availability(date_: str = "2023-06-01") -> dict:
    """Basic per-symbol availability check for the 5 Task124-identified
    candidate additions, on one representative date, feed=sip
    (the feed this task will use for acquisition)."""
    out = {}
    for sym in ("BABA", "BLSH", "SHOP", "SKHY", "SPCX"):
        out[sym] = _fetch(sym, date_, date_, feed="sip")
    return {"probe": "new_symbol_availability", "date": date_, "by_symbol": out}


def probe_blsh_listing_window() -> dict:
    """BLSH (Bullish, NYSE) is a recent listing -- check for the earliest
    available daily bar to establish its listing date rather than
    assuming 2023-01-01 coverage exists."""
    r = _fetch("BLSH", "2023-01-01", "2026-09-01", feed="sip", timeframe="1Day")
    return {"probe": "blsh_listing_window", "result": r}


def main() -> int:
    load_dotenv(RELEASE_ROOT / ".env", override=False)
    if "APCA_API_KEY_ID" not in os.environ or "APCA_API_SECRET_KEY" not in os.environ:
        print(json.dumps({"error": "APCA credentials not present in environment -- aborting"}))
        return 1

    results = {
        "task": "125", "diagnostic_only": True, "strategy_returns_inspected": False,
        "code_based_finding": "task63_download_alpaca.py, task61r_download_alpaca.py, and "
                              "task7b's own download_summary.json format all route through "
                              "scripts/download_historical_1m.py::fetch_alpaca, whose Alpaca "
                              "request params never include a 'feed' key -- confirmed by direct "
                              "source read, not inferred from output.",
        "feed_identity_confirmation": probe_feed_identity(),
        "new_symbol_availability": probe_new_symbol_availability(),
        "blsh_listing_window": probe_blsh_listing_window(),
    }
    out_path = OUT / "feed_provenance_probe.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))

    summary = {
        "feed_identity_conclusion": results["feed_identity_confirmation"]["conclusion"],
        "new_symbol_classifications": {k: v.get("classification")
                                       for k, v in results["new_symbol_availability"]["by_symbol"].items()},
        "blsh_earliest_bar": results["blsh_listing_window"]["result"].get("first_ts"),
    }
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
