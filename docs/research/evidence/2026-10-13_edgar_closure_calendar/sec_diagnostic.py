"""Bounded SEC diagnostic + official-page archive for the 2026-10-13 EDGAR closure correction.

Same identification and transport as talonx_paperperf.form4_edgar.Client (urllib, the configured
TALONX_SEC_USER_AGENT, Accept-Encoding: identity, 30 s timeout). ONE attempt per URL, no retries, >= 2 s apart,
5 requests total. Refuses to run inside R5 (weekdays 09:00-16:30 America/New_York). Index bodies are NOT parsed and
NOT stored (length + sha256 only); official pages are archived raw. The User-Agent value is never written out.

usage: python sec_diagnostic.py OUT_DIR
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

PAGES = [("calendar", "https://www.sec.gov/submit-filings/filer-support-resources/edgar-calendar"),
         ("announcements", "https://www.sec.gov/submit-filings/edgar-news-announcements"),
         ("accessing_edgar_data", "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data")]
INDEXES = [("index_2026-10-12_closure", "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261012.idx"),
           ("index_2026-10-09_known_good", "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261009.idx")]
KEEP_HEADERS = ("server", "content-type", "content-length", "date", "last-modified", "etag", "cache-control",
                "x-amz-request-id", "x-cache", "via", "x-frame-options", "content-encoding")


def classify(status: int, body: bytes) -> str:
    t = body[:20000].decode("utf-8", errors="replace").lower()
    if status == 200:
        return "OK"
    if "request rate threshold exceeded" in t:
        return "RATE_THRESHOLD_PAGE"
    if "undeclared automated tool" in t or "user-agent" in t and "declare" in t:
        return "UNDECLARED_TOOL_PAGE"
    if "<code>accessdenied</code>" in t or "accessdenied" in t:
        return "ACCESS_DENIED_XML"
    if "nosuchkey" in t:
        return "NO_SUCH_KEY_XML"
    if "not found" in t:
        return "NOT_FOUND_PAGE"
    return "UNCLASSIFIED" if t.strip() else "EMPTY_BODY"


def fetch(url: str, ua: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    t0 = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, headers, body = r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        status, headers, body = e.code, dict(e.headers.items()) if e.headers else {}, e.read() or b""
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "requested_utc": t0.isoformat(), "status": None, "error": type(exc).__name__}
    return {"url": url, "requested_utc": t0.isoformat(), "status": status,
            "headers": {k: v for k, v in headers.items() if k.lower() in KEEP_HEADERS},
            "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_class": classify(status, body), "_body": body}


def main(out: Path) -> int:
    from talonx_paperperf.post_delivery_acquisition import r5_permitted
    now = datetime.now(timezone.utc)
    if not r5_permitted(now):
        print(json.dumps({"refused": "R5 (weekday 09:00-16:30 America/New_York)", "at_utc": now.isoformat()}))
        return 3
    from talonx_premarket import __main__ as M
    M._env()
    ua = os.environ.get("TALONX_SEC_USER_AGENT", "").strip()
    if not ua:
        print(json.dumps({"refused": "TALONX_SEC_USER_AGENT not configured"}))
        return 3
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, (name, url) in enumerate(PAGES + INDEXES):
        if i:
            time.sleep(2.0)
        r = fetch(url, ua)
        body = r.pop("_body", None)
        if name in dict(PAGES) and body is not None and r.get("status") == 200:
            p = out / f"{name}_{r['requested_utc'][:19].replace(':', '')}Z.html"
            p.write_bytes(body)
            r["archived_as"] = p.name
        r["name"] = name
        results.append(r)
    (out / "SEC_DIAGNOSTIC.json").write_text(json.dumps({"user_agent": "configured (value not recorded)",
                                                         "attempts_per_url": 1, "requests": len(results),
                                                         "results": results}, indent=1), encoding="utf-8")
    print(json.dumps([{k: r.get(k) for k in ("name", "status", "body_class", "body_bytes")} for r in results]))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent))
