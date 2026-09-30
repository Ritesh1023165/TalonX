"""
Form 4 open-market transactions from SEC EDGAR per-filing documents (free), for periods the quarterly bulk data set
does not cover yet. READ-ONLY research tool: writes only results/v2_validation/edgar/.

Mirrors research/scripts/task107a_form4_build.py::parse_zip field-for-field (same rules, so the frozen detector sees
identical inputs): NON-DERIVATIVE transactions with code P or S, issuer trading symbol required, FIRST reporting owner
of the filing (XML order; the bulk table order can differ on rare multi-owner filings -- documented), relationship flags from that owner, value = shares x price (price capped at 1e6), amendments kept and
flagged. filing_date = the EDGAR daily-index date (= the bulk FILING_DATE).

Source: https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx  (Form 4 and 4/A rows; a filing is
listed once per filer entity -> de-duplicated by accession), then the filing's full submission .txt.
Throttled (default 3 requests/s, well under SEC's 10/s fair-access limit, leaving room for production SEC traffic).
usage: python -m talonx_paperperf.form4_edgar START END [--rate 3]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "results" / "v2_validation" / "edgar"
ROW = re.compile(r"^(?P<form>4(?:/A)?)\s{2,}(?P<name>.+?)\s{2,}(?P<cik>\d{1,10})\s{2,}(?P<date>\d{8})\s{2,}"
                 r"(?P<file>edgar/\S+)\s*$")
XML = re.compile(r"<XML>(.*?)</XML>", re.S | re.I)


class Client:
    def __init__(self, rate: float = 3.0):
        from talonx_premarket import __main__ as M
        M._env()
        self.ua = os.environ.get("TALONX_SEC_USER_AGENT", "").strip()
        if not self.ua:
            raise SystemExit("TALONX_SEC_USER_AGENT not configured")
        self.gap, self.last, self.requests = 1.0 / rate, 0.0, 0

    def get(self, url: str, attempts: int = 4) -> str | None:
        for a in range(attempts):
            wait = self.gap - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                time.sleep(2 ** a * (5 if e.code in (403, 429) else 1))
            except Exception:  # noqa: BLE001
                time.sleep(2 ** a)
        return None


def index_rows(c: Client, day: date) -> list[dict] | None:
    q = (day.month - 1) // 3 + 1
    t = c.get(f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx")
    if t is None:
        return None
    out = {}
    for line in t.splitlines():
        m = ROW.match(line)
        if m:
            acc = m["file"].rsplit("/", 1)[-1].removesuffix(".txt")
            out.setdefault(acc, {"accession": acc, "form": m["form"], "file": m["file"], "date": m["date"]})
    return list(out.values())


def _t(node, path):
    x = node.find(path)
    return x.text.strip() if x is not None and x.text else None


def _f(v, cap=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x < 0 or (cap is not None and x > cap):
        return None
    return x


def _flag(node, path) -> bool:
    return (_t(node, path) or "").lower() in ("1", "true")


def parse_filing(text: str, accession: str, filing_date: str) -> list[dict]:
    m = XML.search(text or "")
    if not m:
        return []
    try:
        root = ET.fromstring(m.group(1).strip())
    except ET.ParseError:
        return []
    sym = (_t(root, "issuer/issuerTradingSymbol") or "").strip().upper()
    if not sym or sym in ("NONE", "N/A"):
        return []
    owners = root.findall("reportingOwner")
    o = owners[0] if owners else None
    doc = (_t(root, "documentType") or "4").strip().upper()
    rows = []
    for tr in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = (_t(tr, "transactionCoding/transactionCode") or "").strip().upper()
        if code not in ("P", "S"):
            continue
        sh = _f(_t(tr, "transactionAmounts/transactionShares/value"))
        px = _f(_t(tr, "transactionAmounts/transactionPricePerShare/value"), cap=1_000_000)
        px = round(px, 2) if px is not None else None           # the bulk data set carries 2 decimals
        td = (_t(tr, "transactionDate/value") or "")[:10] or None
        rows.append({
            "accession": accession, "issuer_cik": str(int(_t(root, "issuer/issuerCik") or 0)).zfill(10),
            "issuer_sym": sym, "issuer_name": _t(root, "issuer/issuerName") or "",
            "filing_date": f"{filing_date[:4]}-{filing_date[4:6]}-{filing_date[6:]}", "trans_date": td,
            "owner_cik": str(int(_t(o, "reportingOwnerId/rptOwnerCik") or 0)).zfill(10) if o is not None else "",
            "owner_name": (_t(o, "reportingOwnerId/rptOwnerName") or "") if o is not None else "",
            "n_owners_on_filing": len(owners),
            "title": (_t(o, "reportingOwnerRelationship/officerTitle") or "") if o is not None else "",
            "is_officer": _flag(o, "reportingOwnerRelationship/isOfficer") if o is not None else False,
            "is_director": _flag(o, "reportingOwnerRelationship/isDirector") if o is not None else False,
            "is_ten_pct": _flag(o, "reportingOwnerRelationship/isTenPercentOwner") if o is not None else False,
            "code": code, "shares": sh, "price": px, "value": sh * px if (sh and px) else None,
            "direct_indirect": (_t(tr, "ownershipNature/directOrIndirectOwnership/value") or "").strip(),
            "form_type": doc, "is_amendment": doc.endswith("/A") or doc.endswith("-A")})
    return rows


def crawl(start: date, end: date, rate: float = 3.0) -> None:
    """One JSONL per day (idempotent: a finished day is skipped). Filing-level progress is checkpointed."""
    OUT.mkdir(parents=True, exist_ok=True)
    c = Client(rate)
    d = start
    while d <= end:
        f = OUT / f"{d:%Y%m%d}.jsonl"
        done = OUT / f"{d:%Y%m%d}.done"
        if d.weekday() < 5 and not done.exists():
            rows = index_rows(c, d)
            if rows is None:
                print(json.dumps({"day": d.isoformat(), "index": "MISSING"}), flush=True)
            else:
                seen = set()
                if f.exists():
                    seen = {json.loads(x)["_acc"] for x in f.read_text(encoding="utf-8").splitlines() if x}
                n_tx = 0
                with open(f, "a", encoding="utf-8") as fh:
                    for r in rows:
                        if r["accession"] in seen:
                            continue
                        txt = c.get(f"https://www.sec.gov/Archives/{r['file']}")
                        tx = parse_filing(txt, r["accession"], r["date"]) if txt else []
                        n_tx += len(tx)
                        fh.write(json.dumps({"_acc": r["accession"], "_ok": txt is not None, "tx": tx}) + "\n")
                done.write_text(json.dumps({"filings": len(rows), "requests": c.requests}), encoding="utf-8")
                print(json.dumps({"day": d.isoformat(), "filings": len(rows), "tx_P_S": n_tx,
                                  "requests_total": c.requests}), flush=True)
        d += timedelta(days=1)


def load(start: str | None = None, end: str | None = None) -> tuple[list[dict], dict]:
    """All crawled transaction rows (+ coverage: days done, filings fetched / failed)."""
    rows, cov = [], {"days": [], "filings": 0, "failed": 0}
    for f in sorted(OUT.glob("*.jsonl")):
        day = f.stem
        if (start and day < start.replace("-", "")) or (end and day > end.replace("-", "")):
            continue
        if not (OUT / f"{day}.done").exists():
            continue
        cov["days"].append(day)
        for x in f.read_text(encoding="utf-8").splitlines():
            if not x:
                continue
            j = json.loads(x)
            cov["filings"] += 1
            cov["failed"] += 0 if j["_ok"] else 1
            rows.extend(j["tx"])
    return rows, cov


if __name__ == "__main__":
    a = sys.argv[1:]
    rate = float(a[a.index("--rate") + 1]) if "--rate" in a else 3.0
    crawl(date.fromisoformat(a[0]), date.fromisoformat(a[1]), rate)
