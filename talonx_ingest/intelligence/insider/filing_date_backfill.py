"""Backfill SEC's authoritative ``filingDate`` into insider rows whose ``filing_date`` is NULL.

Only ``filing_date`` is written, and only where it is NULL (idempotent, never overwrites). No row is
re-ingested, so ``accepted_at_utc`` and the durable receipt ``ingested_at_utc`` are untouched. The date is
taken from SEC metadata -- persisted ``text_events.filing_date`` first, then SEC's submissions feed
(``filings.recent`` plus older shards) -- and NEVER from ``accepted_at_utc.date()``, whose SEC semantics are
unstable. Accessions SEC does not list stay unresolved; V2 release mode fails closed on them.

    python -m talonx_ingest.intelligence.insider.filing_date_backfill            # dry run
    python -m talonx_ingest.intelligence.insider.filing_date_backfill --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
FetchJson = Callable[[str], dict]


def _default_fetch(user_agent: str, *, min_interval_s: float = 0.15, retries: int = 4) -> FetchJson:
    last = [0.0]

    def fetch(url: str) -> dict:
        for attempt in range(retries):
            wait = min_interval_s - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": user_agent})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {}
                if e.code == 429 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        return {}
    return fetch


def _pairs(block: dict) -> dict[str, str]:
    return {a: d for a, d in zip(block.get("accessionNumber", []), block.get("filingDate", [])) if a and d}


def sec_filing_dates_for_cik(cik: str, wanted: set[str], fetch: FetchJson) -> dict[str, str]:
    """accession -> SEC filingDate (ISO) for ``wanted`` accessions of one issuer CIK."""
    root = fetch(f"{SUBMISSIONS_BASE}/CIK{str(int(cik)).zfill(10)}.json")
    filings = root.get("filings", {}) if root else {}
    found = {a: d for a, d in _pairs(filings.get("recent", {})).items() if a in wanted}
    for shard in filings.get("files", []):
        if wanted <= found.keys():
            break
        name = shard.get("name")
        if name:
            found.update({a: d for a, d in _pairs(fetch(f"{SUBMISSIONS_BASE}/{name}")).items() if a in wanted})
    return found


def _counts(con: sqlite3.Connection, table: str) -> tuple[int, int]:
    total, populated = con.execute(
        f"SELECT COUNT(*), SUM(filing_date IS NOT NULL) FROM {table}").fetchone()
    return int(total), int(populated or 0)


def backfill(db_path: str | Path, *, fetch: FetchJson, apply: bool = False) -> dict:
    con = sqlite3.connect(str(db_path))
    try:
        before = {t: _counts(con, t) for t in ("insider_filings", "insider_transactions")}
        missing = con.execute(
            "SELECT accession, MAX(issuer_cik) FROM ("
            " SELECT accession, issuer_cik FROM insider_filings WHERE filing_date IS NULL"
            " UNION ALL SELECT accession, issuer_cik FROM insider_transactions WHERE filing_date IS NULL)"
            " WHERE accession IS NOT NULL GROUP BY accession").fetchall()
        resolved: dict[str, tuple[str, str]] = {}
        has_events = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='text_events'").fetchone() is not None
        for acc, fd in [] if not has_events else con.execute(
                "SELECT accession, MAX(filing_date) FROM text_events WHERE filing_date IS NOT NULL "
                "AND accession IN (SELECT accession FROM insider_filings WHERE filing_date IS NULL "
                "UNION SELECT accession FROM insider_transactions WHERE filing_date IS NULL) GROUP BY accession"):
            resolved[acc] = (str(fd)[:10], "persisted_text_events")
        by_cik: dict[str, set[str]] = {}
        for acc, cik in missing:
            if acc not in resolved and cik:
                by_cik.setdefault(cik, set()).add(acc)
        errors: dict[str, str] = {}
        for cik, accs in sorted(by_cik.items()):
            try:
                for acc, fd in sec_filing_dates_for_cik(cik, accs, fetch).items():
                    resolved[acc] = (fd, "sec_submissions_filingDate")
            except Exception as exc:  # noqa: BLE001 -- that issuer stays unresolved (fail closed downstream)
                errors[cik] = f"{type(exc).__name__}: {exc}"[:160]
        for acc, (fd, _src) in resolved.items():
            date.fromisoformat(fd)  # refuse anything that is not an ISO calendar date
        updated = {"insider_filings": 0, "insider_transactions": 0}
        if apply and resolved:
            with con:
                for acc, (fd, _src) in resolved.items():
                    for table in updated:
                        updated[table] += con.execute(
                            f"UPDATE {table} SET filing_date = ? WHERE accession = ? AND filing_date IS NULL",
                            (fd, acc)).rowcount
        unresolved = sorted({acc for acc, _ in missing} - resolved.keys())
        null_code_p = {a for (a,) in con.execute(
            "SELECT DISTINCT accession FROM insider_transactions WHERE filing_date IS NULL AND transaction_code='P'")}
        unresolved_code_p = sorted(null_code_p if apply else null_code_p - resolved.keys())
        rows = {}
        for t in before:
            null_accs = [a for (a,) in con.execute(f"SELECT accession FROM {t} WHERE filing_date IS NULL")]
            rows[t] = {"total": before[t][0], "already_populated": before[t][1],
                       "backfilled": updated[t] if apply else sum(1 for a in null_accs if a in resolved),
                       "unresolved": sum(1 for a in null_accs if a not in resolved) if not apply else len(null_accs)}
        return {
            "db_path": str(db_path), "applied": apply,
            "run_at_utc": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
            "accessions_missing": len(missing), "accessions_resolved": len(resolved),
            "resolved_by_source": {s: sum(1 for v in resolved.values() if v[1] == s)
                                   for s in ("persisted_text_events", "sec_submissions_filingDate")},
            "accessions_unresolved": len(unresolved), "unresolved_sample": unresolved[:50],
            "unresolved_code_p_accessions": unresolved_code_p,
            "cik_errors": errors,
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None, help="ingestion ledger (default: settings.ledger.path)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--report", default=None, help="write the JSON report here")
    a = ap.parse_args(argv)
    from talonx_ingest.config import settings
    db = a.db or settings.ledger.path
    rep = backfill(db, fetch=_default_fetch(settings.edgar.user_agent), apply=a.apply)
    text = json.dumps(rep, indent=2)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    return 0 if not rep["unresolved_code_p_accessions"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
