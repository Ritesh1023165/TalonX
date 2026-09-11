"""
task107a_form4_build.py  --  TASK 107A  (feasibility audit, NO returns)
======================================================================
Download the SEC quarterly Form 3/4/5 bulk data sets and build a broad,
per-insider, causally-datable open-market transaction table.

Source (free, no auth):
  https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/<YYYY>q<Q>_form345.zip

Output (all under results/task107a_form4_feasibility/, gitignored):
  _bulk/<YYYY>q<Q>_form345.zip          raw downloads (cached)
  _build/form4_open_market_txn.parquet  one row per NONDERIV code P/S transaction

This script inspects NO forward returns, prices, or outcomes.  It only
parses filings and counts.  Return analysis is Task 107B and happens
only after the preregistration is frozen.
"""
from __future__ import annotations

import csv
import io
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task107a_form4_feasibility"
BULK = OUT / "_bulk"
BUILD = OUT / "_build"
BULK.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "TalonX research ritesh.bgm48@gmail.com"}
BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"

# 2019Q1 .. 2026Q3  (task95g daily price panel spans 2019-06-03 .. 2026-08-14)
QUARTERS = [f"{y}q{q}" for y in range(2019, 2027) for q in (1, 2, 3, 4)]
QUARTERS = [q for q in QUARTERS if q <= "2026q3"]


def download(qtag: str) -> Path | None:
    dst = BULK / f"{qtag}_form345.zip"
    if dst.exists() and dst.stat().st_size > 100_000:
        return dst
    url = f"{BASE}/{qtag}_form345.zip"
    try:
        req = urllib.request.Request(url, headers=UA)
        t = time.time()
        data = urllib.request.urlopen(req, timeout=180).read()
        dst.write_bytes(data)
        print(f"  {qtag}: {len(data):,} bytes  ({time.time()-t:.1f}s)")
        time.sleep(0.4)  # be polite to SEC
        return dst
    except Exception as e:  # noqa: BLE001
        print(f"  {qtag}: SKIP ({e!r})")
        return None


def _f(v, cap=None):
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    if cap is not None and not (0 < x < cap):
        return None
    return x


def _date(s: str):
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def parse_zip(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        names = {n.split("/")[-1].upper(): n for n in z.namelist()}

        def rd(fn):
            real = names.get(fn.upper())
            if real is None:
                return []
            with z.open(real) as fh:
                return list(
                    csv.DictReader(
                        io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                        delimiter="\t",
                    )
                )

        subs = {r["ACCESSION_NUMBER"]: r for r in rd("SUBMISSION.tsv")}
        owners: dict[str, list[dict]] = {}
        for r in rd("REPORTINGOWNER.tsv"):
            owners.setdefault(r["ACCESSION_NUMBER"], []).append(r)
        trans = rd("NONDERIV_TRANS.tsv")

    rows = []
    for r in trans:
        code = (r.get("TRANS_CODE") or "").strip().upper()
        if code not in ("P", "S"):
            continue
        acc = r["ACCESSION_NUMBER"]
        s = subs.get(acc, {})
        sym = (s.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
        if not sym or sym in ("NONE", "N/A"):
            continue
        fdate = _date(s.get("FILING_DATE"))
        tdate = _date(r.get("TRANS_DATE"))
        if fdate is None:
            continue
        os_ = owners.get(acc, [{}])
        o = os_[0]
        rel = (o.get("RPTOWNER_RELATIONSHIP") or o.get("RPTOWNER_TXT") or "").lower()
        doc = (s.get("DOCUMENT_TYPE") or "4").strip().upper()
        sh = _f(r.get("TRANS_SHARES"))
        px = _f(r.get("TRANS_PRICEPERSHARE"), cap=1_000_000)
        val = sh * px if (sh and px) else None
        rows.append(
            dict(
                accession=acc,
                issuer_cik=str(s.get("ISSUERCIK") or "").strip(),
                issuer_sym=sym,
                issuer_name=(s.get("ISSUERNAME") or "").strip(),
                filing_date=fdate,
                trans_date=tdate,
                owner_cik=str(o.get("RPTOWNERCIK") or "").strip(),
                owner_name=(o.get("RPTOWNERNAME") or "").strip(),
                n_owners_on_filing=len(os_),
                title=(o.get("RPTOWNER_TITLE") or "").strip(),
                is_officer=("officer" in rel),
                is_director=("director" in rel),
                is_ten_pct=("tenpercent" in rel or "10%" in rel),
                code=code,
                shares=sh,
                price=px,
                value=val,
                direct_indirect=(r.get("DIRECT_INDIRECT_OWNERSHIP") or "").strip(),
                form_type=doc,
                is_amendment=doc.endswith("/A") or doc.endswith("-A"),
            )
        )
    return rows


def main():
    print("downloading SEC form345 bulk data sets ...")
    paths = []
    for q in QUARTERS:
        p = download(q)
        if p:
            paths.append((q, p))

    print(f"\nparsing {len(paths)} quarterly zips ...")
    all_rows: list[dict] = []
    for q, p in paths:
        rr = parse_zip(p)
        all_rows.extend(rr)
        print(f"  {q}: {len(rr):,} P/S non-deriv rows")

    df = pd.DataFrame(all_rows)
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["trans_date"] = pd.to_datetime(df["trans_date"])
    df = df.sort_values(["issuer_sym", "filing_date", "owner_cik"]).reset_index(drop=True)
    dst = BUILD / "form4_open_market_txn.parquet"
    df.to_parquet(dst, index=False)
    print(f"\nwrote {dst}  shape={df.shape}")
    print("code counts:", df["code"].value_counts().to_dict())
    print("P: issuers", df[df.code == "P"].issuer_sym.nunique(),
          " owners", df[df.code == "P"].owner_cik.nunique())
    print("date span:", df.filing_date.min(), "->", df.filing_date.max())


if __name__ == "__main__":
    sys.exit(main())
