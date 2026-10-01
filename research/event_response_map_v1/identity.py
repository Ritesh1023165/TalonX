"""EVENT_RESPONSE_MAP_V1 LOCK REV 3 -- identity resolution (R1-FIX b), dated ticker<->CIK rule (R6), dated SIC (R7).

METADATA ONLY. Network calls go through the R5 off-hours guard (data.market_hours_blocked).

Identity sources (declared):
  * Alpaca name_change corporate actions, BOTH directions (old->new and new->old), 2019-2023 (already archived) plus
    renames processed AFTER 2023, owner-authorized FOR IDENTITY ONLY. Post-2023 query ranges SKIP the Task75 reserved
    windows 2024-06-01..2024-09-02 and 2024-10-21..2024-12-20 (global rule 1); only old_symbol / new_symbol /
    process_date are kept from those records. Renames processed inside the reserved windows are therefore not
    covered (counted as a residual limitation).
  * EDGAR tickers: SEC company_tickers.json, the 'tickers' field of each submissions JSON, and the issuer trading
    symbol reported on every Form 3/4/5 in the SEC insider data sets 2019Q1-2023Q4 (SUBMISSION.tsv:
    ISSUERCIK, ISSUERTRADINGSYMBOL, FILING_DATE) -- a DATED, point-in-time ticker observation.
  * EDGAR names: cik-lookup-data.txt plus 'name' and 'formerNames' of every archived submissions JSON.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from research.event_response_map_v1 import data as D
from research.event_response_map_v1.universe import SYMBOL_RE, norm_name

DEV_START, DEV_END = date(2019, 1, 2), date(2023, 12, 29)
TASK75_RESERVED = ((date(2024, 6, 1), date(2024, 9, 2)), (date(2024, 10, 21), date(2024, 12, 20)))
POST2023_RENAME_RANGES = (("2024-01-01", "2024-05-31"), ("2024-09-03", "2024-10-20"), ("2024-12-21", "2024-12-31"),
                          ("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-09-30"))
FAR_PAST, FAR_FUTURE = date(1900, 1, 1), date(9999, 12, 31)
COMPANY_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "40-F", "6-K", "S-1", "S-4", "DEF 14A")
SIC_RE = re.compile(r"STANDARD INDUSTRIAL CLASSIFICATION:[^\[\n]*\[(\d{4})\]")


def assert_outside_reserved(start: str, end: str) -> None:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    for a, b in TASK75_RESERVED:
        if s <= b and e >= a:
            raise RuntimeError(f"identity metadata range {start}..{end} intersects a Task75 reserved window")


def norm_ticker(t) -> str | None:
    s = str(t or "").strip().upper()
    if ":" in s:
        s = s.rsplit(":", 1)[1].strip()
    s = s.replace("-", ".").replace("/", ".").replace(" ", "")
    if s in ("NONE", "NA", "N.A", "NULL", "TBD"):
        return None
    return s if SYMBOL_RE.match(s) else None


# ------------------------------------------------------------------------------------------------ fetch (metadata)
def fetch_post2023_renames(headers: dict, out: Path, guard, opener=None, clock=None) -> list[dict]:
    """Alpaca name_change processed after 2023, reserved windows skipped, IDENTITY fields only. Cached in `out`."""
    if out.exists():
        return json.loads(out.read_text())
    import time
    clock = clock or (lambda: datetime.now(timezone.utc))
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=120).read())
    rows = []
    for s, e in POST2023_RENAME_RANGES:
        assert_outside_reserved(s, e)
        token = None
        while True:
            if D.market_hours_blocked(clock()):
                raise D.MarketHoursRefusal("Alpaca identity metadata: off-hours only")
            p = {"start": s, "end": e, "types": "name_change", "limit": 1000}
            if token:
                p["page_token"] = token
            time.sleep(2.0)
            j = json.loads(opener(urllib.request.Request(
                "https://data.alpaca.markets/v1/corporate-actions?" + urllib.parse.urlencode(p), headers=headers)))
            for r in (j.get("corporate_actions") or {}).get("name_changes", []):
                rows.append({"old_symbol": r.get("old_symbol"), "new_symbol": r.get("new_symbol"),
                             "process_date": r.get("process_date")})
            token = j.get("next_page_token")
            if not token:
                break
    out.write_text(json.dumps(rows), encoding="utf-8", newline="\n")
    guard.record({"event": "IDENTITY_METADATA_POST_2023", "source": "alpaca name_change", "records": len(rows),
                  "ranges": POST2023_RENAME_RANGES, "use": "ticker identity only; Task75 reserved windows skipped"})
    return rows


def form345_ticker_obs(zip_bytes: bytes) -> list[tuple[str, str, date]]:
    """(symbol, issuer_cik10, filing_date) for every Form 3/4/5 submission in one quarterly insider data set."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.split("/")[-1].upper() == "SUBMISSION.TSV")
        with z.open(name) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"):
                sym, cik = norm_ticker(r.get("ISSUERTRADINGSYMBOL")), str(r.get("ISSUERCIK") or "").strip()
                try:
                    fd = datetime.strptime(str(r.get("FILING_DATE", "")).strip()[:11], "%d-%b-%Y").date()
                except ValueError:
                    try:
                        fd = date.fromisoformat(str(r.get("FILING_DATE", "")).strip()[:10])
                    except ValueError:
                        continue
                if sym and cik.isdigit() and DEV_START <= fd <= DEV_END:
                    out.append((sym, cik.zfill(10), fd))
    return out


# ------------------------------------------------------------------------------------------------ identity
def rename_edges(renames: list[dict]) -> list[tuple[str, str, date]]:
    out = set()
    for r in renames:
        o, n = norm_ticker(r.get("old_symbol")), norm_ticker(r.get("new_symbol"))
        pdte = str(r.get("process_date") or "")[:10]
        if o and n and o != n and pdte:
            out.add((o, n, date.fromisoformat(pdte)))
    return sorted(out, key=lambda x: (x[2], x[0], x[1]))


def build_identity(cand: dict, sec_tickers: dict, edges: list, f345: list, name_index: dict, pit: set) -> dict:
    """symbol -> {"cik": cik10|None, "method": str}. Order (first hit wins):
       1 RENAME_CHAIN_FWD   follow dated renames forward (any year) to a ticker in SEC company_tickers
       2 SEC_TICKERS        symbol itself is a current SEC ticker AND it was never renamed away (recycling guard)
       3 RENAME_CHAIN_BWD   a later rename INTO this symbol came from a ticker that resolves (new->old direction)
       4 FORM345_TICKER     symbol reported as issuer trading symbol in 2019-2023 for exactly ONE issuer CIK
       5 UNIQUE_NAME_MATCH  normalized name (Alpaca/inherited) matches exactly one CIK across cik-lookup + formerNames
       else UNMAPPED.  A symbol reported for >1 issuer CIK in Form 3/4/5 is FORM345_AMBIGUOUS unless 1-3 resolved it."""
    fwd = defaultdict(list)
    renamed_away = set()
    for o, n, d in edges:
        fwd[o].append((d, n))
        renamed_away.add(o)
    by_sym345 = defaultdict(set)
    for s, c, _ in f345:
        by_sym345[s].add(c)
    names = cand.get("names", {})

    def forward(s):
        seen, t = {s}, s
        while fwd.get(t):
            t = sorted(fwd[t])[-1][1]
            if t in seen:
                break
            seen.add(t)
            if t in sec_tickers:
                return t
        return None

    out = {}
    for s in sorted(cand["symbols"]):
        hit = None
        t = forward(s) if s in renamed_away else None
        if t:
            hit = (str(sec_tickers[t]).zfill(10), "RENAME_CHAIN_FWD")
        elif s in sec_tickers and s not in renamed_away:
            hit = (str(sec_tickers[s]).zfill(10), "SEC_TICKERS")
        if not hit and len(by_sym345.get(s, ())) == 1:
            hit = (next(iter(by_sym345[s])), "FORM345_TICKER")
        if not hit and s in names:
            ciks = name_index.get(norm_name(names[s]))
            if ciks and len(ciks) == 1:
                hit = (next(iter(ciks)), "UNIQUE_NAME_MATCH")
        if not hit:
            hit = (None, "FORM345_AMBIGUOUS" if len(by_sym345.get(s, ())) > 1 else "UNMAPPED")
        out[s] = {"cik": hit[0], "method": hit[1]}
    # propagate along dated rename edges in BOTH directions until stable:
    #   s renamed INTO a resolved ticker n  (s -> n)  -> same company before the rename  (RENAME_CHAIN_FWD)
    #   s created FROM a resolved ticker o  (o -> s)  -> same company after the rename   (RENAME_CHAIN_BWD)
    changed = True
    while changed:
        changed = False
        for o, n, d in edges:
            if o in out and not out[o]["cik"] and out.get(n, {}).get("cik"):
                out[o] = {"cik": out[n]["cik"], "method": "RENAME_CHAIN_FWD"}
                changed = True
            if n in out and not out[n]["cik"] and out.get(o, {}).get("cik"):
                out[n] = {"cik": out[o]["cik"], "method": "RENAME_CHAIN_BWD"}
                changed = True
    return out


def dated_intervals(identity: dict, edges: list) -> dict:
    """cik -> [(symbol, valid_from, valid_to_exclusive)]: a symbol is valid for its CIK from the date a rename INTO it
    was processed until the date a rename OUT of it was processed (dated Alpaca rename chain, any year)."""
    into, out_of = defaultdict(list), defaultdict(list)
    for o, n, d in edges:
        out_of[o].append(d)
        into[n].append(d)
    res = defaultdict(list)
    for s, v in identity.items():
        if not v["cik"]:
            continue
        lo = max(into[s]) if into.get(s) else FAR_PAST
        hi = min([d for d in out_of.get(s, []) if d > lo] or [FAR_FUTURE])
        res[v["cik"]].append((s, lo, hi))
    return {c: sorted(v, key=lambda x: (x[1], x[0])) for c, v in res.items()}


def assign(cik: str, d: date, intervals: dict) -> tuple[str | None, str]:
    """The ONE ticker valid for `cik` on date d. -> (symbol, ASSIGNED) | (None, AMBIGUOUS | NO_VALID_TICKER)."""
    valid = [s for s, lo, hi in intervals.get(str(cik).zfill(10), []) if lo <= d < hi]
    if len(valid) == 1:
        return valid[0], "ASSIGNED"
    return None, ("AMBIGUOUS" if valid else "NO_VALID_TICKER")


def symbol_cik_on(symbol: str, d: date, intervals_by_symbol: dict) -> str | None:
    """Dated reverse lookup: the CIK a symbol belonged to on date d (None outside its validity)."""
    for cik, lo, hi in intervals_by_symbol.get(symbol, []):
        if lo <= d < hi:
            return cik
    return None


def by_symbol(intervals: dict) -> dict:
    out = defaultdict(list)
    for cik, rows in intervals.items():
        for s, lo, hi in rows:
            out[s].append((cik, lo, hi))
    return dict(out)


# ------------------------------------------------------------------------------------------------ R7 dated SIC
def last_company_filing(filings: list[dict], before: date, forms=COMPANY_FORMS) -> dict | None:
    """filings: [{form, filingDate, accessionNumber}] (dev period). Latest company filing strictly before `before`."""
    best = None
    for f in filings:
        fd = date.fromisoformat(f["filingDate"])
        if f["form"] in forms and fd < before and (best is None or fd > date.fromisoformat(best["filingDate"])):
            best = f
    return best


def header_sic(text: str) -> str | None:
    m = SIC_RE.search(text)
    return m.group(1) if m else None


def sic_timeline(sic_end: str | None, despac_date: date | None, sic_before_despac: str | None) -> list:
    """[(from_date, sic)] covering the development period. Without an 8-K item 5.06 (change in shell company status)
    the SIC of the last company filing in the period applies throughout; with one, the pre-5.06 header SIC applies
    before it and the end-of-period SIC from it on."""
    if despac_date and sic_before_despac:
        return [(FAR_PAST, sic_before_despac), (despac_date, sic_end)]
    return [(FAR_PAST, sic_end)]


def sic_on(timeline: list, d: date) -> str | None:
    cur = None
    for lo, sic in timeline:
        if d >= lo:
            cur = sic
    return cur
