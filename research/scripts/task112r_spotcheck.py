"""
task112r_spotcheck.py -- Task 112R G1.4 : deterministic side-by-side spot checks
                         + investigation of the 26 missing / 23 unexpected
                         in-panel episodes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "task112r_release_rehearsal"


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


t107a = _load("t107a", "research/scripts/task107a_episodes.py")
t112rp = _load("t112rp", "research/scripts/task112r_parity.py")
from talonx_v2.cluster_engine import PurchaseRecord, detect_episodes_for_issuer
from talonx_v2.config import V2Config
from talonx_v2 import calendar as v2cal


def synthetic_cases():
    """Deterministic fixtures -- research vs runtime side by side."""
    cfg = V2Config()
    cases = {
        "exactly_2_insiders": [
            ("A", "O1", "2026-03-02"), ("A", "O2", "2026-03-04")],
        "3plus_insiders": [
            ("B", "O1", "2026-03-02"), ("B", "O2", "2026-03-03"), ("B", "O3", "2026-03-05")],
        "dup_txn_same_insider": [
            ("C", "O1", "2026-03-02"), ("C", "O1", "2026-03-03"), ("C", "O2", "2026-03-06")],
        "multiple_codeP_same_filing": [
            ("D", "O1", "2026-03-02"), ("D", "O1", "2026-03-02"), ("D", "O2", "2026-03-04")],
        "weekend_filing": [
            ("E", "O1", "2026-03-06"), ("E", "O2", "2026-03-07")],   # Fri, Sat
        "window_boundary_10td_ok": None,     # built below
        "window_boundary_11td_no": None,
        "issuer_repeated_episodes": [
            ("G", "O1", "2026-03-02"), ("G", "O2", "2026-03-03"),
            ("G", "O5", "2026-04-01"), ("G", "O6", "2026-04-02")],
    }
    d1 = date(2026, 3, 2)
    cases["window_boundary_10td_ok"] = [("F", "O1", d1.isoformat()),
                                        ("F", "O2", v2cal.add_sessions(d1, 10).isoformat())]
    cases["window_boundary_11td_no"] = [("F2", "O1", d1.isoformat()),
                                        ("F2", "O2", v2cal.add_sessions(d1, 11).isoformat())]

    out = []
    tdays = t107a.trading_days()
    ti8 = tdays.values.astype("datetime64[ns]").astype("int64")
    for name, rows in cases.items():
        df = pd.DataFrame([{"issuer_sym": s, "owner_cik": o, "filing_date": pd.Timestamp(d),
                            "value": 50000.0, "is_officer": False, "is_director": False,
                            "is_ten_pct": False, "code": "P", "accession": f"{s}{o}{d}"}
                           for s, o, d in rows])
        R = t107a.build_episodes(df.assign(issuer_sym=df.issuer_sym), 10, 2, ti8)
        recs = [PurchaseRecord(symbol=r.issuer_sym, issuer_cik="x", owner_cik=r.owner_cik,
                               filing_date=r.filing_date.date(), accession=r.accession,
                               transaction_value=r.value, transaction_code="P")
                for r in df.itertuples(index=False)]
        U = detect_episodes_for_issuer(recs, config=cfg)
        out.append({
            "case": name,
            "research_episodes": int(len(R)),
            "research_entry": [str(x) for x in (R.entry_session.dt.date.tolist() if len(R) else [])],
            "research_n_owners": (R.n_distinct_owners.tolist() if len(R) else []),
            "runtime_episodes": len(U),
            "runtime_entry": [e.eligible_entry_session.isoformat() for e in U],
            "runtime_activation": [e.activation_filing_date.isoformat() for e in U],
            "runtime_n_owners": [e.n_distinct_owners for e in U],
        })
    return out


def investigate_diffs():
    """The 26 missing / 23 unexpected in-panel keys -- are they real
    detection bugs, or first_filing-key artifacts of greedy consumption?"""
    P = t112rp.load_P()
    panel = {f.stem.upper() for f in (ROOT / "results/task95g_broad_cross_sectional/_daily").glob("*.csv")}
    R = t112rp.research_episodes(P); R = R[R.issuer_sym.isin(panel)].copy()
    U = t112rp.runtime_episodes(P); U = U[U.issuer_sym.isin(panel)].copy()
    for dfx in (R, U):
        for c in ("first_filing", "last_filing"):
            dfx[c] = pd.to_datetime(dfx[c]).dt.date
    R["key"] = R.issuer_sym + "|" + R.first_filing.astype(str)
    U["key"] = U.issuer_sym + "|" + U.first_filing.astype(str)
    missing = sorted(set(R.key) - set(U.key))
    unexpected = sorted(set(U.key) - set(R.key))

    # a "missing" key is BENIGN if the runtime has *some* episode for the
    # same issuer whose window overlaps the research episode's window
    def overlap(sym, r_first, r_last, other):
        for _, o in other[other.issuer_sym == sym].iterrows():
            if not (o["last_filing"] < r_first or o["first_filing"] > r_last):
                return True
        return False

    benign_missing = real_missing = 0
    real_missing_rows = []
    for k in missing:
        row = R[R.key == k].iloc[0]
        if overlap(row.issuer_sym, row.first_filing, row.last_filing, U):
            benign_missing += 1
        else:
            real_missing += 1
            real_missing_rows.append(k)
    benign_unexp = real_unexp = 0
    real_unexp_rows = []
    for k in unexpected:
        row = U[U.key == k].iloc[0]
        if overlap(row.issuer_sym, row.first_filing, row.last_filing, R):
            benign_unexp += 1
        else:
            real_unexp += 1
            real_unexp_rows.append(k)

    return {
        "missing_keys": len(missing), "benign_missing_overlapping_episode": benign_missing,
        "REAL_missing_no_overlap": real_missing, "real_missing_examples": real_missing_rows[:10],
        "unexpected_keys": len(unexpected), "benign_unexpected_overlapping_episode": benign_unexp,
        "REAL_unexpected_no_overlap": real_unexp, "real_unexpected_examples": real_unexp_rows[:10],
    }


def main() -> int:
    sc = synthetic_cases()
    inv = investigate_diffs()
    print("=== G1.4 SYNTHETIC SPOT CHECKS ===")
    for c in sc:
        print(json.dumps(c, default=str))
    print("\n=== 26 missing / 23 unexpected INVESTIGATION ===")
    print(json.dumps(inv, indent=2, default=str))
    (OUT / "_g1_spotcheck.json").write_text(json.dumps(
        {"synthetic": sc, "diff_investigation": inv}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
