"""
task112r_parity.py -- Task 112R Gate G1 + G2 : research <-> runtime parity
========================================================================
G1: does the FROZEN runtime detector (talonx_v2.cluster_engine.detect_episodes)
    reproduce the SAME episode set the Task 107B research code
    (research/scripts/task107a_episodes.py::build_episodes) produced?
G2: does re-running the frozen Task 107B +10D/20bps primary spec on each
    episode set reproduce the frozen headline (~+1.69% in-panel)?

NO parameter research.  NO strategy change.  Frozen inputs only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "task112r_release_rehearsal"
OUT.mkdir(parents=True, exist_ok=True)
TXN = ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
PANEL = ROOT / "results/task95g_broad_cross_sectional/_daily"
PRICES = ROOT / "results/task107a_form4_feasibility/_prices"

# frozen research module
import importlib.util
_spec = importlib.util.spec_from_file_location("t107a_ep", ROOT / "research/scripts/task107a_episodes.py")
t107a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t107a)

from talonx_v2.cluster_engine import PurchaseRecord, detect_episodes
from talonx_v2.config import V2Config


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_P() -> pd.DataFrame:
    df = pd.read_parquet(TXN)
    P = df[(df.code == "P") & (df.owner_cik.astype(str).str.len() > 0)].copy()
    P["issuer_sym"] = P["issuer_sym"].map(t107a.clean_sym)
    P = P[P["issuer_sym"].notna()].copy()
    P["filing_date"] = pd.to_datetime(P["filing_date"])
    return P


def research_episodes(P: pd.DataFrame) -> pd.DataFrame:
    tdays = t107a.trading_days()
    tdays_i8 = tdays.values.astype("datetime64[ns]").astype("int64")
    ep = t107a.build_episodes(P, 10, 2, tdays_i8)
    ep = ep[ep.entry_session.notna()].copy()
    ep["entry_session"] = pd.to_datetime(ep["entry_session"]).dt.date
    ep["knowable_date"] = pd.to_datetime(ep["knowable_date"]).dt.date
    ep["first_filing"] = pd.to_datetime(ep["first_filing"]).dt.date
    return ep


def runtime_episodes(P: pd.DataFrame) -> pd.DataFrame:
    recs = [
        PurchaseRecord(
            symbol=r.issuer_sym, issuer_cik=str(getattr(r, "issuer_cik", "")),
            owner_cik=str(r.owner_cik), filing_date=r.filing_date.date(),
            accession=str(getattr(r, "accession", "")),
            transaction_date=(r.trans_date.date() if pd.notna(getattr(r, "trans_date", pd.NaT)) else None),
            transaction_value=(float(r.value) if pd.notna(getattr(r, "value", np.nan)) else None),
            is_officer=bool(getattr(r, "is_officer", False)),
            is_director=bool(getattr(r, "is_director", False)),
            is_ten_percent=bool(getattr(r, "is_ten_pct", False)),
            transaction_code="P",
        )
        for r in P.itertuples(index=False)
    ]
    eps = detect_episodes(recs, config=V2Config())
    return pd.DataFrame([{
        "issuer_sym": e.symbol, "n_distinct_owners": e.n_distinct_owners,
        "n_filings": e.n_filings, "first_filing": e.first_filing_date,
        "activation_filing_date": e.activation_filing_date,
        "last_filing": e.last_filing_date, "entry_session": e.eligible_entry_session,
        "episode_id": e.episode_id,
    } for e in eps])


def main() -> int:
    panel = {f.stem.upper() for f in PANEL.glob("*.csv")}
    P = load_P()
    print(f"frozen P rows: {len(P)}  issuers {P.issuer_sym.nunique()}  "
          f"input_sha {_sha(sorted(P[['issuer_sym','owner_cik','accession']].astype(str).agg('|'.join, axis=1).tolist()))}")

    R = research_episodes(P)
    U = runtime_episodes(P)
    Rp = R[R.issuer_sym.isin(panel)].copy()
    Up = U[U.issuer_sym.isin(panel)].copy()
    print(f"research episodes total {len(R)}  in-panel {len(Rp)}")
    print(f"runtime  episodes total {len(U)}  in-panel {len(Up)}")

    # canonical logical key = (symbol, first_filing_date)  -- both encodings
    # anchor an episode at its first qualifying code-P filing for that issuer.
    Rp["key"] = Rp.issuer_sym + "|" + Rp.first_filing.astype(str)
    Up["key"] = Up.issuer_sym + "|" + Up.first_filing.astype(str)
    rk, uk = set(Rp.key), set(Up.key)
    matched = rk & uk
    missing_runtime = rk - uk           # research had it, runtime didn't
    unexpected_runtime = uk - rk        # runtime invented it

    # for matched keys, compare entry session + owner count + activation
    m = Rp.merge(Up, on="key", suffixes=("_r", "_u"))
    entry_mismatch = m[m.entry_session_r != m.entry_session_u]
    owners_mismatch = m[m.n_distinct_owners_r != m.n_distinct_owners_u]

    summary = {
        "research_episodes_in_panel": int(len(Rp)),
        "runtime_episodes_in_panel": int(len(Up)),
        "exact_matched_keys": int(len(matched)),
        "missing_from_runtime": int(len(missing_runtime)),
        "unexpected_runtime": int(len(unexpected_runtime)),
        "entry_session_mismatches": int(len(entry_mismatch)),
        "distinct_owner_count_mismatches": int(len(owners_mismatch)),
        "entry_mismatch_gap_sessions": {
            "note": "runtime enters at the 2nd-distinct-insider filing; research entered "
                    "after the LAST filing in the 10-td window (contract vs research code)",
        },
        "research_key_sha": _sha(sorted(rk)),
        "runtime_key_sha": _sha(sorted(uk)),
    }
    print("\n=== G1 PARITY (in-panel / P2) ===")
    print(json.dumps(summary, indent=2, default=str))

    # gap distribution on entry mismatches
    if len(entry_mismatch):
        g = (pd.to_datetime(entry_mismatch.entry_session_u) -
             pd.to_datetime(entry_mismatch.entry_session_r)).dt.days
        print("entry gap (runtime - research) calendar days: "
              f"min {g.min()} median {g.median()} max {g.max()}  "
              f"(<=0 means runtime enters same-or-earlier)")
        entry_mismatch.assign(gap_days=g.values).to_csv(OUT / "g1_entry_mismatches.csv", index=False)

    Rp.to_csv(OUT / "research_runtime_parity_research.csv", index=False)
    Up.to_csv(OUT / "research_runtime_parity_runtime.csv", index=False)
    parity = pd.DataFrame([{"key": k,
                            "in_research": k in rk, "in_runtime": k in uk}
                           for k in sorted(rk | uk)])
    parity.to_csv(OUT / "research_runtime_parity.csv", index=False)
    (OUT / "_g1_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
