"""Bulk downloads from SEC. No per-company API calls. Needs a contact User-Agent (SEC_USER_AGENT)."""
from __future__ import annotations

import datetime as dt
import os
import time
import zoneinfo
from pathlib import Path

import requests

COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC moved the newest quarters (2026 Q2 onward) from /structureddata/ to /datastandardsinnovation/; try both.
FORM345_URLS = [
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip",
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{y}q{q}_form345.zip",
]


def user_agent() -> str:
    ua = (os.environ.get("SEC_USER_AGENT") or os.environ.get("TALONX_SEC_USER_AGENT") or "").strip().strip("\"'")
    if "@" not in ua:
        raise RuntimeError("SEC_USER_AGENT must be a contact string with an email, e.g. 'Your Name you@example.com'")
    return ua


def in_us_market_hours(now: dt.datetime | None = None) -> bool:
    et = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zoneinfo.ZoneInfo("America/New_York"))
    return et.weekday() < 5 and dt.time(9, 0) <= et.time() <= dt.time(16, 30)


def download(url: str, dest: Path, ua: str, tries: int = 4) -> bool:
    """Stream ``url`` to ``dest`` (skipped when present). Returns False on HTTP 404, raises on other failures."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for k in range(tries):
        try:
            with requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, stream=True, timeout=(30, 300)) as r:
                if r.status_code == 404:
                    return False
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            tmp.replace(dest)
            return True
        except (requests.RequestException, OSError) as e:
            print(f"  download retry {k + 1}/{tries} for {url}: {e}", flush=True)
            time.sleep(10 * (k + 1))
    raise RuntimeError(f"could not download {url}")


def quarters(start: str, end: str):
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    y, q = s.year, (s.month - 1) // 3 + 1
    while (y, q) <= (e.year, (e.month - 1) // 3 + 1):
        yield y, q
        q += 1
        if q == 5:
            y, q = y + 1, 1
