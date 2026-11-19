"""Universe-wide filing events from SEC EDGAR daily form indexes (free; the SEC source TalonX already uses).
One request per business day: https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx
Keeps 8-K / 8-K/A / 6-K and 4 / 4/A rows (CIK, form, date, accession path). Throttled to 1 request/s.
LIMITATION (documented): the index has no Form 4 transaction codes and no 8-K item numbers -- a "Form 4 cluster" here
means >=2 distinct Form 4 filings for the issuer, NOT the >=2 open-market purchasers V2 uses.
usage: python fetch_edgar_daily_index.py OUT_JSON START END"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from talonx_premarket import __main__ as M  # noqa: E402

KEEP = {"8-K", "8-K/A", "6-K", "4", "4/A"}
ROW = re.compile(r"^(?P<form>\S+(?: \S+)?)\s{2,}(?P<name>.+?)\s{2,}(?P<cik>\d{1,10})\s{2,}(?P<date>\d{8})\s{2,}"
                 r"(?P<file>edgar/\S+)\s*$")


def fetch(day: date, ua: str) -> list[dict] | None:
    q = (day.month - 1) // 3 + 1
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=60) as r:
            text = r.read().decode("latin-1")
    except urllib.error.HTTPError as e:
        return None if e.code in (403, 404) else []
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m and m["form"] in KEEP:
            rows.append({"form": m["form"], "cik": m["cik"].zfill(10), "date": day.isoformat(),
                         "accession": m["file"].rsplit("/", 1)[-1].removesuffix(".txt")})
    return rows


def main(out: str, start: str, end: str) -> None:
    M._env()
    ua = M._sec()._ua
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    res = {"days": {}, "rows": []}
    while d <= e:
        if d.weekday() < 5:
            rows = fetch(d, ua)
            res["days"][d.isoformat()] = None if rows is None else len(rows)
            res["rows"] += rows or []
            time.sleep(1.0)
        d += timedelta(days=1)
    Path(out).write_text(json.dumps(res), encoding="utf-8")
    print(json.dumps(res["days"]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
