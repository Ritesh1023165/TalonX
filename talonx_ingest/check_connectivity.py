"""
check_connectivity.py
------------------------
Standalone diagnostic script -- run this BEFORE the full pipeline if a run
hangs with no log output. It tests each external endpoint the pipeline
needs, one at a time, with a short hard timeout, so you can see exactly
which one is blocked instead of waiting indefinitely on the full run.

Usage:
    python check_connectivity.py

If a corporate proxy is required, set HTTP_PROXY / HTTPS_PROXY first, e.g.
in PowerShell:
    $env:HTTPS_PROXY = "http://proxy.yourcompany.com:8080"
    python check_connectivity.py
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
import urllib.error

CHECKS = [
    (
        "SEC ticker map",
        "https://www.sec.gov/files/company_tickers.json",
    ),
    (
        "SEC submissions API",
        "https://data.sec.gov/submissions/CIK0000320193.json",
    ),
    (
        "SEC filing archives",
        "https://www.sec.gov/Archives/edgar/data/320193/",
    ),
    (
        "Hugging Face (embedding model host)",
        "https://huggingface.co",
    ),
]

TIMEOUT_SECONDS = 8


def check_one(name: str, url: str) -> bool:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TalonX Connectivity Check test@example.com"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            elapsed = time.monotonic() - start
            print(f"  OK   {name:<38} {resp.status} in {elapsed:.2f}s")
            return True
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - start
        # A fast HTTP error (e.g. 403) still proves the network path works --
        # it's a config problem (User-Agent), not a connectivity problem.
        print(f"  HTTP {name:<38} {exc.code} in {elapsed:.2f}s (path reachable)")
        return True
    except (urllib.error.URLError, TimeoutError) as exc:
        elapsed = time.monotonic() - start
        print(f"  FAIL {name:<38} {exc} after {elapsed:.2f}s")
        return False


def main() -> int:
    print("TalonX connectivity check")
    print(f"HTTP_PROXY  = {os.environ.get('HTTP_PROXY', '(not set)')}")
    print(f"HTTPS_PROXY = {os.environ.get('HTTPS_PROXY', '(not set)')}")
    print(f"Each check times out after {TIMEOUT_SECONDS}s.\n")

    all_ok = True
    for name, url in CHECKS:
        ok = check_one(name, url)
        all_ok = all_ok and ok

    print()
    if all_ok:
        print("All endpoints reachable. If the pipeline still hangs, the "
              "issue is likely the embedding model download progressing "
              "slowly rather than a network block -- give it more time, "
              "or check Task Manager for python.exe network activity.")
    else:
        print("One or more endpoints are NOT reachable directly.")
        print("If you're on a corporate network, set HTTP_PROXY/HTTPS_PROXY "
              "in your .env or shell and re-run this script. If it's still "
              "blocked even with a proxy set, your network/firewall admin "
              "may need to allowlist the failing domain(s) above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
