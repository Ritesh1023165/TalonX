"""Read-only V2 Form 4 coverage table (2026-10-07 audit). No network, no writes outside the output directory."""
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
HOME = Path(os.path.expanduser("~/.talonx"))
OUT = Path(sys.argv[1])
CAMPAIGN_START = "2026-09-21"         # campaign.created_at_utc 2026-09-21T18:38Z
LOOKBACK_SINCE = "2026-08-23"         # status.source.since (45-day live lookback)
BROAD_SINCE = "2026-08-24"

hb = json.loads((HOME / "intelligence" / "service.heartbeat.json").read_text(encoding="utf-8"))
w39 = list(hb["effective_symbols"])
man = json.loads((REPO / "talonx_ingest/intelligence/service/data/discovery_universe_v1_626.json").read_text())
u626 = list(man["symbols"])
cm = man["cik_manifest"]
resolved = cm["resolved"]
unres = {(u["symbol"] if isinstance(u, dict) else u): (u.get("reason") if isinstance(u, dict) else None)
         for u in cm["unresolved"]}
ct = json.loads((HOME / "intelligence" / "company_tickers.json").read_text(encoding="utf-8"))
live_cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in ct.values()}
covmap = json.loads(Path(sys.argv[2]).read_text())
wl48 = {t["symbol"]: t for t in covmap["tickers"]}


def cik_of(sym):
    r = resolved.get(sym)
    if isinstance(r, dict):
        r = r.get("cik") or r.get("cik_str")
    if r:
        return str(r).zfill(10), "STATIC_626_MANIFEST"
    if sym in live_cik:
        return live_cik[sym], "LOCAL_COMPANY_TICKERS_CACHE"
    return None, None


L = sqlite3.connect(f"file:{HOME / 'ingestion_ledger.db'}?mode=ro", uri=True)
fil = defaultdict(dict)
for sym, n_c, n_l, n_b, last_f, last_ing, mism in L.execute(
        "SELECT symbol, SUM(filing_date>=?), SUM(filing_date>=?), SUM(filing_date>=?), MAX(filing_date), "
        "MAX(ingested_at_utc), 0 FROM insider_filings GROUP BY symbol", (CAMPAIGN_START, LOOKBACK_SINCE, BROAD_SINCE)):
    fil[sym] = dict(f_campaign=n_c or 0, f_lookback=n_l or 0, f_since0824=n_b or 0, last_filed=last_f,
                    last_ingested=last_ing)
issuer_cik_seen = defaultdict(set)
for sym, ik in L.execute("SELECT DISTINCT symbol, issuer_cik FROM insider_filings WHERE filing_date>=?", (LOOKBACK_SINCE,)):
    issuer_cik_seen[sym].add(ik)
codep = defaultdict(lambda: [0, set()])
for sym, owner in L.execute("SELECT symbol, owner_cik FROM insider_transactions WHERE transaction_code='P' "
                            "AND filing_date>=?", (LOOKBACK_SINCE,)):
    codep[sym][0] += 1
    codep[sym][1].add(owner)
bf = {s: (lp, c, ls) for s, lp, c, ls in L.execute(
    "SELECT symbol, latest_processed_date, completed, last_success_utc FROM intel_backfill_checkpoint WHERE form='4'")}

ph = [json.loads(x) for x in (HOME / "intelligence" / "poll_history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
full = [x for x in ph if x.get("symbols_polled") == len(w39) and not x.get("symbols_failed")]
partial = [x for x in ph if x.get("symbols_failed")]
last_full = full[-1]["at_utc"] if full else None
last_cycle = ph[-1]["at_utc"]

V = sqlite3.connect(f"file:{REPO / 'v2_release_rc1.db'}?mode=ro", uri=True)
eps = defaultdict(list)
for sym, d, det in V.execute("SELECT symbol, disposition, eligible_entry_session FROM processed_episodes"):
    eps[sym].append(f"{d}@{det}")

syms = sorted(set(u626) | set(w39) | set(wl48))
by_cik = defaultdict(list)
for s in syms:
    c, _ = cik_of(s)
    if c:
        by_cik[c].append(s)

rows = []
for s in syms:
    c, csrc = cik_of(s)
    in39, in626, inwl = s in w39, s in u626, s in wl48
    f = fil.get(s, {})
    cp = codep.get(s, [0, set()])
    b = bf.get(s)
    if in39:
        if not c:
            cls = "IDENTITY_UNRESOLVED"
        elif f.get("f_campaign"):
            cls = "CONFIGURED_AND_SUCCESSFULLY_POLLED_WITH_FILINGS"
        else:
            cls = "CONFIGURED_AND_SUCCESSFULLY_POLLED_NO_FILINGS"
        ev = (f"in every one of {len(full)} all-success poll cycles (symbols_polled=39, symbols_failed=0) since "
              f"{ph[0]['at_utc'][:16]}Z; {len(partial)} partial-failure cycles are not symbol-attributed")
        gov = "V2 execution allowlist = intelligence resolve_watchlist POLLED (run.py --execution-scope resolved-active-watchlist)"
    elif inwl:
        w = wl48[s]
        if (w.get("unsupported_reason") or "").startswith("known_non_filer"):
            cls, gov = "INTENTIONALLY_OUT_OF_SCOPE", "watchlist resolver: " + w["unsupported_reason"]
        else:
            cls, gov = "INTENTIONALLY_OUT_OF_SCOPE", f"watchlist status={w['status']}: {w.get('unsupported_reason')}"
        ev = "not in effective_symbols; not polled"
    else:
        cls = "INTENTIONALLY_OUT_OF_SCOPE" if c else "IDENTITY_UNRESOLVED"
        gov = ("RC1 release launch spec excludes --enable-broad-discovery "
               "(release_freeze_preflight/13_full_day_launch_command.md; v2_final_release_acceptance/"
               "release_candidate_configuration.json launch_argv)")
        if not c:
            gov = "626 static CIK manifest: unresolved; and out of RC1 scope (" + gov + ")"
        ev = ("not polled since broad collection stopped; last Form 4 ingested " + str(f.get("last_ingested"))[:19]
              if f else "no stored Form 4")
    rows.append({
        "symbol": s, "issuer_cik": c or "", "cik_source": csrc or "UNRESOLVED",
        "shared_issuer_tickers": ";".join(t for t in by_cik.get(c, []) if t != s) if c else "",
        "in_discovery_universe_v1_626": in626, "in_live_v2_scope_39": in39, "in_owner_watchlist_48": inwl,
        "configured_live_polling": in39,
        "last_attempted_poll_utc": last_cycle if in39 else "",
        "last_successful_poll_utc": (last_full or "") if in39 else "",
        "poll_evidence": ev,
        "backfill_form4_latest_processed": b[0] if b else "", "backfill_completed": bool(b[1]) if b else "",
        "latest_failure_category": ("none attributable (cycle counters only)" if in39 else ""),
        "input_freshness": ("FRESH (source_freshness SEC_EDGAR_SUBMISSIONS; global)" if in39 else "N/A not polled"),
        "form4_filings_since_campaign_0921": f.get("f_campaign", 0),
        "form4_filings_in_v2_lookback_since_0823": f.get("f_lookback", 0),
        "form4_filings_since_0824": f.get("f_since0824", 0),
        "issuer_cik_matched": (("YES" if issuer_cik_seen.get(s) <= {c} else "MIXED:" + ";".join(sorted(issuer_cik_seen[s])))
                               if issuer_cik_seen.get(s) and c else ""),
        "codeP_rows_since_0823": cp[0], "codeP_distinct_owners_since_0823": len(cp[1]),
        "last_form4_filed": f.get("last_filed") or "", "last_form4_ingested_utc": (f.get("last_ingested") or "")[:19],
        "v2_episodes": ";".join(eps.get(s, [])),
        "coverage_class": cls, "governing_decision": gov,
    })

OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "coverage_by_symbol.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

iss = {}
for r in rows:
    k = r["issuer_cik"] or ("UNRESOLVED:" + r["symbol"])
    e = iss.setdefault(k, {"issuer_cik": k, "tickers": [], "classes": set(), "in39": False, "in626": False,
                           "f_campaign": 0, "codeP": 0})
    e["tickers"].append(r["symbol"]); e["classes"].add(r["coverage_class"])
    e["in39"] |= r["in_live_v2_scope_39"]; e["in626"] |= r["in_discovery_universe_v1_626"]
    e["f_campaign"] = max(e["f_campaign"], r["form4_filings_since_campaign_0921"])
    e["codeP"] = max(e["codeP"], r["codeP_rows_since_0823"])
order = ["CONFIGURED_AND_SUCCESSFULLY_POLLED_WITH_FILINGS", "CONFIGURED_AND_SUCCESSFULLY_POLLED_NO_FILINGS",
         "CONFIGURED_BUT_FAILING", "IDENTITY_UNRESOLVED", "OBSERVABILITY_INSUFFICIENT", "INTENTIONALLY_OUT_OF_SCOPE",
         "NOT_CONFIGURED"]
with (OUT / "coverage_by_issuer.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["issuer_cik", "tickers", "coverage_class", "in_live_v2_scope_39", "in_discovery_universe_v1_626",
                "max_form4_since_campaign", "max_codeP_rows_since_0823"])
    for e in iss.values():
        cls = next(c for c in order if c in e["classes"])
        e["cls"] = cls
        w.writerow([e["issuer_cik"], ";".join(e["tickers"]), cls, e["in39"], e["in626"], e["f_campaign"], e["codeP"]])

summary = {
    "symbols_total": len(rows), "issuers_total": len(iss),
    "by_symbol": Counter(r["coverage_class"] for r in rows),
    "by_issuer": Counter(e["cls"] for e in iss.values()),
    "symbols_in_626": len(u626), "symbols_in_39": len(w39), "symbols_in_48": len(wl48),
    "39_subset_of_626": set(w39) <= set(u626),
    "626_unresolved_cik": len(unres), "626_resolved_cik": len(resolved),
    "shared_cik_groups": {k: v for k, v in by_cik.items() if len(v) > 1},
    "poll_history": {"first": ph[0]["at_utc"], "last": last_cycle, "cycles": len(ph), "all_success_cycles": len(full),
                     "partial_failure_cycles": len(partial), "last_all_success": last_full},
    "in39_with_filings_since_campaign": sum(1 for r in rows if r["in_live_v2_scope_39"] and r["form4_filings_since_campaign_0921"]),
    "in39_codeP_rows_since_0823": {r["symbol"]: [r["codeP_rows_since_0823"], r["codeP_distinct_owners_since_0823"]]
                                   for r in rows if r["in_live_v2_scope_39"] and r["codeP_rows_since_0823"]},
    "out_of_scope_codeP_rows_since_0823": sum(r["codeP_rows_since_0823"] for r in rows if not r["in_live_v2_scope_39"]),
    "out_of_scope_symbols_with_codeP_since_0823": sorted(r["symbol"] for r in rows if not r["in_live_v2_scope_39"] and r["codeP_rows_since_0823"]),
    "out_of_scope_last_form4_ingested": max((r["last_form4_ingested_utc"] for r in rows if not r["in_live_v2_scope_39"] and r["last_form4_ingested_utc"]), default=None),
}
(OUT / "coverage_summary.json").write_text(json.dumps(summary, indent=1, default=lambda o: dict(o) if isinstance(o, Counter) else str(o)), encoding="utf-8")
print(json.dumps(summary, indent=1, default=lambda o: dict(o) if isinstance(o, Counter) else str(o)))
