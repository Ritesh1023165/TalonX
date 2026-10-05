"""Verification B -- LIMITED development-only network smoke test of the production acquisition adapters.

  python -m research.erm_nominee_validation.acquisition.dev_smoke --out <dir>

PREDECLARED request set (fixed here, before any run; every item is development-dated metadata or bars, every request
is guarded by DevelopmentAcquisitionGuard WITHOUT any broad-endpoint authorisation, so an accidental request for a
current list, a full submissions history, the S&P file or any 2024+ content is refused before it is built):
  S1 bars          RETURNS (all) AAPL, MSFT, SPY and ELIGIBILITY_ONLY (raw) AAPL, MSFT, 2019-01-02..2019-01-31, through
                   the frozen data.Downloader exactly as the acquirer drives it
  S2 corp actions  name_change and cash/stock/stock_and_cash mergers, 2019-01-01..2019-01-31
  S3 ETF dividends cash_dividend for the 7 benchmark ETFs, 2019-01-01..2019-12-31
  S4 Form 3/4/5    2019q1 insider data set
  S5 master.idx    2019 QTR1
  S6 submissions   ONE historical page CIK0000004904-submissions-001.json (declared range 1999-12-06..2019-09-29)
  S7 header        0000319815-19-000056 (filed 2019-05-16)
NOT requested (broad): Alpaca asset list, company_tickers.json, cik-lookup-data.txt, submissions main JSON, S&P CSV,
identity-only post-period renames. Live policy: R5 off-hours (weekday 09:00-16:30 ET refused), provider spacing,
bounded retry -- all from transport.HttpTransport. Fresh bytes are compared with the archived development bytes for
schema, semantics, coverage and provenance; byte equality is reported, not required.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import gzip
import hashlib
import io
import json
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))
from research.erm_nominee_validation import builder as B  # noqa: E402
from research.erm_nominee_validation.acquisition import acquirer as AQ, states as S  # noqa: E402
from research.erm_nominee_validation.acquisition.guards import DevelopmentAcquisitionGuard  # noqa: E402
from research.erm_nominee_validation.acquisition.period import PERIODS  # noqa: E402
from research.erm_nominee_validation.acquisition.replay import AUDIT, ERM  # noqa: E402
from research.erm_nominee_validation.acquisition.scope import form345_obs, master_periodic  # noqa: E402
from research.erm_nominee_validation.acquisition.store import ArchiveStore  # noqa: E402
from research.erm_nominee_validation.acquisition.transport import HttpTransport, req  # noqa: E402
from research.event_response_map_v1 import data as D, identity as I  # noqa: E402

PLAN = {
    "bars": {"returns": ["AAPL", "MSFT", "SPY"], "eligibility": ["AAPL", "MSFT"], "from": "2019-01-02", "to": "2019-01-31"},
    "corporate_actions": {"from": "2019-01-01", "to": "2019-01-31"},
    "etf_cash_dividends": {"from": "2019-01-01", "to": "2019-12-31"},
    "form345": "2019q1",
    "master_idx": "2019/QTR1",
    "submissions_page": {"cik": "0000004904", "name": "CIK0000004904-submissions-001.json",
                         "from": "1999-12-06", "to": "2019-09-29"},
    "header": {"cik": "0000319815", "acc": "0000319815-19-000056", "filed": "2019-05-16"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def arch_sec(name: str) -> bytes | None:
    for d in (ERM / "_archive/sec", AUDIT / "_sec_pit", AUDIT / "_sec_v2"):
        if (d / (name + ".gz")).exists():
            return gzip.decompress((d / (name + ".gz")).read_bytes())
    return None


def cmp_bars(arc: Path) -> dict:
    fresh = {}
    man = json.loads((arc / "bars/SMOKE/manifest.json").read_text())
    for f in man["files"]:
        for s, bs in (json.loads(gzip.decompress((arc / "bars/SMOKE" / f["file"]).read_bytes())).get("bars") or {}).items():
            fresh.setdefault((f["purpose"], s), []).extend(bs)
    old = {}
    fm = json.loads((ERM / "_archive/alpaca/manifest.json").read_text())
    want = {(p, s) for p, ss in (("RETURNS", PLAN["bars"]["returns"]), ("ELIGIBILITY_ONLY", PLAN["bars"]["eligibility"]))
            for s in ss}
    for f in fm["files"]:
        if not any(s in f["symbols"] for _, s in want if _ == f["purpose"]):
            continue
        for s, bs in (json.loads(gzip.decompress((ERM / "_archive/alpaca" / f["file"]).read_bytes())).get("bars") or {}).items():
            if (f["purpose"], s) in want:
                old.setdefault((f["purpose"], s), []).extend(
                    b for b in bs if PLAN["bars"]["from"] <= b["t"][:10] <= PLAN["bars"]["to"])
    out = {}
    for k in sorted(want):
        a, b = fresh.get(k, []), old.get(k, [])
        ka = {x["t"]: x for x in a}
        kb = {x["t"]: x for x in b}
        diffs = [t for t in sorted(set(ka) & set(kb)) if any(ka[t][f] != kb[t][f] for f in ("o", "h", "l", "c", "v"))]
        out["/".join(k)] = {"fresh_sessions": len(a), "archived_sessions": len(b), "same_dates": set(ka) == set(kb),
                            "schema_fresh": sorted(a[0]) if a else [], "schema_archived": sorted(b[0]) if b else [],
                            "ohlcv_value_diffs": len(diffs), "first_diffs": diffs[:3]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (out / "smoke_record.json").exists():
        raise SystemExit("smoke test already recorded here; refusing to overwrite")
    out.mkdir(parents=True, exist_ok=True)
    guard = DevelopmentAcquisitionGuard()                               # NO broad endpoint authorised
    tr = HttpTransport()
    rec = {"run": "ERM_ACQUISITION_DEV_NETWORK_SMOKE", "started_utc": now(), "plan": PLAN,
           "r5_blocked_at_start": D.market_hours_blocked(datetime.now(timezone.utc)), "results": {}}
    if rec["r5_blocked_at_start"]:
        rec.update(status="NOT_RUN_R5_OFF_HOURS", ended_utc=now())
        B.atomic(out / "smoke_record.json", json.dumps(rec, indent=1))
        print(rec["status"])
        return 2
    acq = AQ.ProductionAcquirer(guard, tr, download_date=date.today())
    arc = out / "archive"
    acq.cfg, acq.archive, acq.per = None, arc, PERIODS["DEV"]
    acq.store = ArchiveStore(arc)
    acq._subs, acq._hdr = {}, {}
    R = rec["results"]
    # S1 bars -- the production bars path (frozen Downloader through the transport and guard adapter)
    smoke_per = dataclasses.replace(PERIODS["DEV"], bars_from=date.fromisoformat(PLAN["bars"]["from"]),
                                    events_to=date.fromisoformat(PLAN["bars"]["to"]))
    acq.bars_group("SMOKE", PLAN["bars"]["returns"], PLAN["bars"]["eligibility"], smoke_per)
    R["bars"] = cmp_bars(arc) if (arc / "bars/SMOKE/manifest.json").exists() else {"failed": acq.failures[-1:]}
    # S2 corporate actions (one month) vs archived rows with process_date in the month
    c = PLAN["corporate_actions"]
    rn = acq.corporate_actions("corporate_actions", "name_change", c["from"], c["to"])
    mg = acq.corporate_actions("corporate_actions", AQ.MERGER_TYPES, c["from"], c["to"])
    old_rn = [r for r in json.loads((ERM / "_renames_2019_2023.json").read_text()) if c["from"] <= r["process_date"] <= c["to"]]
    old_mg = [r for r in json.loads((ERM / "_mergers_2019_2023.json").read_text()) if c["from"] <= r["process_date"] <= c["to"]]
    for k, fresh, old in (("renames", rn, old_rn), ("mergers", mg, old_mg)):
        if fresh is AQ.MISSING:
            R[k] = {"failed": True}
            continue
        fi, oi = {x["id"] for x in fresh}, {x["id"] for x in old}
        R[k] = {"fresh": len(fresh), "archived": len(oi), "same_ids": fi == oi, "only_fresh": sorted(fi - oi)[:5],
                "only_archived": sorted(oi - fi)[:5],
                "field_diffs": sum(1 for x in fresh for y in old if x["id"] == y["id"]
                                   and {k2: v for k2, v in x.items()} != {k2: v for k2, v in y.items()})}
    # S3 ETF cash dividends 2019
    e = PLAN["etf_cash_dividends"]
    etf = acq.corporate_actions("etf_cash_dividends", "cash_dividend", e["from"], e["to"], symbols=",".join(D.BENCHMARKS),
                                required=False)
    old_etf = (json.loads((AUDIT / "_alpaca_v2/etf_cash_dividends_2019_0.json").read_text())
               .get("corporate_actions") or {}).get("cash_dividends", [])
    if etf is AQ.MISSING:
        R["etf_cash_dividends"] = {"failed": True}
    else:
        fk = {(x["symbol"], x["ex_date"], x.get("rate")) for x in etf}
        ok = {(x["symbol"], x["ex_date"], x.get("rate")) for x in old_etf}
        R["etf_cash_dividends"] = {"fresh": len(fk), "archived": len(ok), "same_symbol_exdate_rate": fk == ok,
                                   "only_fresh": sorted(fk - ok)[:5], "only_archived": sorted(ok - fk)[:5]}
    # S4 Form 3/4/5 2019q1
    q = PLAN["form345"]
    zb = acq.sec_file("form345", AQ.form345_url(q), f"{q}_form345.zip", (date(2019, 1, 1), date(2019, 3, 31)),
                      required=True, insufficient_on_404=True, validate=acq._zip_form345)
    zo = arch_sec(f"{q}_form345.zip")
    if zb is AQ.MISSING:
        R["form345"] = {"failed": True}
    else:
        lo, hi = date(2018, 1, 1), date(2023, 12, 29)
        a_, b_ = set(form345_obs(zb, lo, hi)), set(form345_obs(zo, lo, hi))
        R["form345"] = {"bytes_equal": h(zb) == h(zo), "fresh_obs": len(a_), "archived_obs": len(b_),
                        "same_ticker_observations": a_ == b_, "only_fresh": len(a_ - b_), "only_archived": len(b_ - a_)}
    # S5 master.idx 2019 QTR1
    mq = PLAN["master_idx"]
    mb = acq.sec_file("master_idx", AQ.SEC_MASTER.format(mq), "master_" + mq.replace("/", "_") + ".idx",
                      (date(2019, 1, 1), date(2019, 3, 31)), required=True, insufficient_on_404=True,
                      validate=acq._master)
    mo = arch_sec("master_" + mq.replace("/", "_") + ".idx")
    if mb is AQ.MISSING:
        R["master_idx"] = {"failed": True}
    else:
        pa = master_periodic(mb.decode("latin-1"), "2019-01-01", "2023-12-31")
        pb = master_periodic(mo.decode("latin-1"), "2019-01-01", "2023-12-31")
        R["master_idx"] = {"bytes_equal": h(mb) == h(mo), "lines_fresh": mb.count(b"\n"), "lines_archived": mo.count(b"\n"),
                           "same_periodic_cik_set": pa == pb, "periodic_ciks": len(pa)}
    # S6 one historical submissions page (dated category: the guard checks its declared range)
    sp = PLAN["submissions_page"]
    pb_ = acq.get("submissions_history_page", req("sec", AQ.SEC_SUB.format(sp["name"])),
                  (date.fromisoformat(sp["from"]), date.fromisoformat(sp["to"])), "sec/sub_" + sp["name"] + ".gz",
                  required=True, absent_on_404=True, validate=acq._json_obj("filingDate"))
    po = arch_sec("sub_" + sp["name"])
    if pb_ is AQ.MISSING or pb_ is None:
        R["submissions_page"] = {"failed": True, "absent": pb_ is None}
    else:
        jf, jo = json.loads(pb_), json.loads(po)
        rows = lambda j: {(j["filingDate"][i], j["form"][i], j["accessionNumber"][i]) for i in range(len(j["form"]))}  # noqa: E731
        R["submissions_page"] = {"bytes_equal": h(pb_) == h(po), "keys_fresh": sorted(jf), "keys_archived": sorted(jo),
                                 "rows_fresh": len(jf["form"]), "rows_archived": len(jo["form"]),
                                 "same_filing_rows": rows(jf) == rows(jo),
                                 "max_filing_date": max(jf["filingDate"]) if jf["filingDate"] else None}
    # S7 one 2019 filing header
    hd = PLAN["header"]
    t = acq.header_text(hd["cik"], hd["acc"], hd["filed"])
    to = arch_sec(f"hdr_{hd['acc']}.html")
    R["header"] = ({"failed": True} if t is None else
                   {"bytes_equal": t.encode("latin-1") == to, "sic_fresh": I.header_sic(t),
                    "sic_archived": I.header_sic(to.decode("latin-1"))})
    rec["ledger"] = [json.loads(x) for x in (arc / "acquisition/ledger.jsonl").read_text().splitlines()]
    rec["guard_checks"] = guard.log
    rec["failures"] = acq.failures
    states = {x["state"] for x in rec["ledger"]}
    rec["status"] = ("SMOKE_PASS" if states <= {S.USABLE} and not acq.failures else "SMOKE_FAILURES")
    rec["ended_utc"] = now()
    B.atomic(out / "smoke_record.json", json.dumps(rec, indent=1, default=str))
    print(json.dumps({"status": rec["status"], "results": R}, indent=1, default=str))
    return 0 if rec["status"] == "SMOKE_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
