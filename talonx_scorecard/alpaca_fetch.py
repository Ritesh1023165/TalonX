"""Alpaca market-data fetch (network). Run on the machine that holds the keys; never used by the tests.

Keys come from the environment (APCA_API_KEY_ID / APCA_API_SECRET_KEY) or the repo-root ``.env``. They are never logged.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ACTIONS_URL = "https://data.alpaca.markets/v1/corporate-actions"


def load_keys(root: Path) -> tuple[str, str]:
    key, sec = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    env = root / ".env"
    if (not key or not sec) and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("APCA_API_KEY_ID="):
                key = line.split("=", 1)[1].strip()
            elif line.startswith("APCA_API_SECRET_KEY="):
                sec = line.split("=", 1)[1].strip()
    if not key or not sec:
        raise RuntimeError("Alpaca keys not found (APCA_API_KEY_ID / APCA_API_SECRET_KEY)")
    return key, sec


def session(root: Path) -> requests.Session:
    key, sec = load_keys(root)
    s = requests.Session()
    s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    return s


def _get(s: requests.Session, url: str, params: dict, tries: int = 6) -> dict:
    for i in range(tries):
        r = s.get(url, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, 2 ** i)); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"giving up on {url} after {tries} tries (last status {r.status_code})")


def fetch_bars(s: requests.Session, symbols: list[str], adjustment: str, start: str, end: str) -> dict[str, list[dict]]:
    """Daily SIP bars for a batch of symbols, paginated. adjustment: 'all' (split+dividend) or 'raw' (as traded)."""
    acc: dict[str, list[dict]] = {x: [] for x in symbols}
    token = None
    for _ in range(500):
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "adjustment": adjustment, "feed": "sip",
                  "start": start, "end": end, "limit": 10000}
        if token:
            params["page_token"] = token
        d = _get(s, BARS_URL, params)
        for sym, rows in (d.get("bars") or {}).items():
            acc.setdefault(sym, []).extend(rows)
        token = d.get("next_page_token")
        if not token:
            return acc
    raise RuntimeError("pagination did not terminate")


def fetch_splits(s: requests.Session, symbols: list[str], start: str, end: str) -> dict:
    """Merged corporate-actions payload (forward + reverse splits) for a batch of symbols."""
    merged: dict = {"corporate_actions": {"forward_splits": [], "reverse_splits": []}}
    token = None
    for _ in range(500):
        params = {"symbols": ",".join(symbols), "types": "forward_split,reverse_split", "start": start, "end": end, "limit": 1000}
        if token:
            params["page_token"] = token
        d = _get(s, ACTIONS_URL, params)
        for kind in ("forward_splits", "reverse_splits"):
            merged["corporate_actions"][kind].extend((d.get("corporate_actions") or {}).get(kind, []) or [])
        token = d.get("next_page_token")
        if not token:
            return merged
    raise RuntimeError("pagination did not terminate")
