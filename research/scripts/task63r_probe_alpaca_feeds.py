"""Diagnose Task 63's implicit Alpaca feed and SIP entitlement without ORPB replay."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "results/task63r_orpb_v1_feed_remediation"
DATA = ROOT / "data/historical_1m/task63_orpb_v1_validation"
CASES = {
    "BKNG": ["2025-02-10", "2025-02-11", "2025-03-26", "2025-04-25", "2025-04-30"],
    "KLAC": ["2025-02-07"],
}
ET = "America/New_York"


def normalize(rows: list[dict], session: str) -> list[dict]:
    normalized = []
    for row in rows:
        timestamp = pd.Timestamp(row["t"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        local = timestamp.tz_convert(ET)
        minute = local.hour * 60 + local.minute
        if local.date().isoformat() == session and 570 <= minute < 960:
            normalized.append({
                "t": timestamp.isoformat(), "o": float(row["o"]), "h": float(row["h"]),
                "l": float(row["l"]), "c": float(row["c"]), "v": float(row["v"]),
            })
    return sorted(normalized, key=lambda item: item["t"])


def digest(rows: list[dict]) -> str:
    payload = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def buckets(rows: list[dict]) -> list[str]:
    values = set()
    for row in rows:
        local = pd.Timestamp(row["t"]).tz_convert(ET)
        if local.hour == 9 and 30 <= local.minute < 60:
            values.add(f"09:{(local.minute // 5) * 5:02d}")
    return sorted(values)


def fetch(symbol: str, session: str, feed: str | None) -> dict:
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    params = {
        "timeframe": "1Min", "start": f"{session}T00:00:00Z",
        "end": f"{session}T23:59:59Z", "limit": 10000, "adjustment": "raw",
    }
    if feed is not None:
        params["feed"] = feed
    response = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
        headers=headers, params=params, timeout=30,
    )
    result = {"http_status": response.status_code, "feed_parameter": feed or "omitted"}
    if response.status_code != 200:
        try:
            result["error"] = response.json().get("message", response.text)
        except ValueError:
            result["error"] = response.text
        return result
    rows = normalize(response.json().get("bars") or [], session)
    result.update({
        "regular_session_bars": len(rows), "regular_session_sha256": digest(rows),
        "opening_buckets": buckets(rows),
    })
    return result


def persisted(symbol: str, session: str) -> dict:
    frame = pd.read_csv(DATA / f"{symbol}.csv")
    timestamp = pd.to_datetime(frame["timestamp"], utc=True)
    local = timestamp.dt.tz_convert(ET)
    minute = local.dt.hour * 60 + local.dt.minute
    frame = frame[(local.dt.strftime("%Y-%m-%d") == session) & (minute >= 570) & (minute < 960)]
    rows = [
        {"t": pd.Timestamp(row.timestamp).isoformat(), "o": float(row.open), "h": float(row.high),
         "l": float(row.low), "c": float(row.close), "v": float(row.volume)}
        for row in frame.itertuples(index=False)
    ]
    return {
        "regular_session_bars": len(rows), "regular_session_sha256": digest(rows),
        "opening_buckets": buckets(rows),
    }


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for symbol, sessions in CASES.items():
        for session in sessions:
            cases.append({
                "symbol": symbol, "session": session,
                "persisted": persisted(symbol, session),
                "omitted": fetch(symbol, session, None),
                "iex": fetch(symbol, session, "iex"),
                "sip": fetch(symbol, session, "sip"),
            })
    sip_available = all(item["sip"]["http_status"] == 200 for item in cases)
    matches = {}
    for feed in ("omitted", "iex", "sip"):
        matches[feed] = all(
            item[feed].get("regular_session_sha256")
            == item["persisted"]["regular_session_sha256"]
            for item in cases
        )
    resolved = "SIP" if matches["sip"] else ("IEX" if matches["iex"] else "other")
    payload = {
        "task": "63R", "diagnostic_only": True, "orpb_outcomes_inspected": False,
        "persisted_task63_feed": resolved, "implicit_omitted_matches_persisted": matches["omitted"],
        "feed_matches": matches, "sip_available": sip_available, "cases": cases,
    }
    (OUT / "feed_diagnostic.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: payload[key] for key in (
        "persisted_task63_feed", "implicit_omitted_matches_persisted", "feed_matches", "sip_available"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
