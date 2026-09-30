"""Task75B PREFLIGHT -- the ONE-SHOT corrected DEVELOPMENT evaluation (DEVELOPMENT_CORPORATE_ACTION_SURVIVAL_V1).
Runs the FROZEN evaluate() on TASK75_DATASET_ALL_V1 (archived bytes, hash-verified against the manifest), applies the
pre-registered gates, diffs every trade against the archived RAW ledger with attribution, checks dataset completeness
and classifies. Refuses to run twice (result file exists). Loads are guard-checked at the LOAD layer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75_v1.calendar import build_daily_table, canonical_calendar  # noqa: E402
from research.task75_v1.fingerprint import compute_contract_only_fingerprint, compute_fingerprint  # noqa: E402
from research.task75_v1.strategy import evaluate  # noqa: E402
from research.task75b_preflight import raw_parity as RP  # noqa: E402
from research.task75b_preflight import survival as S  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402
from talonx_backtest.data import load_ohlcv_directory  # noqa: E402

RES = ROOT / "results" / "task75b_preflight"
ALL_DIR = ROOT / "data" / "historical_1m" / "task75b_all_v1"
OUTF = RES / "corrected_development_result.json"


def regular_days(bars: pd.DataFrame) -> dict[str, set[str]]:
    d = build_daily_table(bars)
    return {s: set(map(str, g["trading_day"])) for s, g in d.groupby("symbol")}


def main() -> dict:
    if OUTF.exists():
        raise SystemExit("corrected development already evaluated once -- refusing to re-run (run_once)")
    fp_ok = (compute_fingerprint() == "08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3" and
             compute_contract_only_fingerprint() == "677adccd7e653e30c96122f0149356523f3a2fb3cb82a3d4967c3a1a06aa6f06")
    guard = HoldoutGuard.load()
    man = json.loads((RES / "dataset_manifest_all_v1.json").read_text())
    raw_man = json.loads(RP.MANIFEST.read_text())["slices"]
    parity = json.loads((RES / "raw_parity.json").read_text())

    # ---- dataset integrity: bytes == manifest, every symbol present, no dup / rejects
    integrity = {"hash_mismatch": [], "missing_files": [], "empty": [], "duplicates": [], "rejected": []}
    for label, sl in man["slices"].items():
        for sym in C.UNIVERSE + [C.MARKET_SYMBOL]:
            f = ALL_DIR / label / f"{sym}.csv"
            meta = sl["files"].get(sym)
            if meta is None or not f.exists():
                integrity["missing_files"].append(f"{label}/{sym}")
                continue
            if S.file_sha256(f) != meta["sha256"]:
                integrity["hash_mismatch"].append(f"{label}/{sym}")
            if meta["rows"] == 0:
                integrity["empty"].append(f"{label}/{sym}")
            if meta["duplicate_timestamps"]:
                integrity["duplicates"].append(f"{label}/{sym}")
            if meta["rejected_malformed"]:
                integrity["rejected"].append(f"{label}/{sym}")

    all_led, raw_led, cov, calendars = [], [], {}, {}
    for label, sl in man["slices"].items():
        guard.check_range(*sl["window"], layer="LOAD")
        bars = load_ohlcv_directory(ALL_DIR / label, symbols=C.UNIVERSE + [C.MARKET_SYMBOL])
        guard.check_frame(bars, layer="LOAD")
        raw_bars = RP.load_slice(RP.ARCHIVE_DEFAULT, label, raw_man[label]["data_dir"].replace("\\", "/"))
        guard.check_frame(raw_bars, layer="LOAD")
        ra, rr = regular_days(bars), regular_days(raw_bars)
        spy = sorted(ra.get("SPY", set()))
        calendars[label] = spy
        cov[label] = {"spy_sessions_all": len(spy), "spy_sessions_raw": len(rr.get("SPY", set())),
                      "missing_vs_spy_all": {s: sorted(set(spy) - ra.get(s, set())) for s in C.UNIVERSE
                                             if set(spy) - ra.get(s, set())},
                      "sessions_in_raw_not_in_all": {s: sorted(rr.get(s, set()) - ra.get(s, set())) for s in rr
                                                     if rr.get(s, set()) - ra.get(s, set())}}
        la, lr = evaluate(bars), evaluate(raw_bars)
        la["slice"], lr["slice"] = label, label
        all_led.append(la)
        raw_led.append(lr)
    A = pd.concat(all_led, ignore_index=True)
    Rw = pd.concat(raw_led, ignore_index=True)
    trades = A[A["data_ready"] == True].copy()  # noqa: E712
    st = S.survival_stats(trades)
    ca = json.loads((RES / "corporate_action_audit.json").read_text())["events"]
    diff = S.attribute_diff(Rw, A, ca, calendars)
    cats = diff["category"].value_counts().to_dict() if len(diff) else {}
    changes = diff["change"].value_counts().to_dict() if len(diff) else {}
    unexplained = int(cats.get("UNEXPLAINED", 0))
    gates = S.survival_gates(st, unexplained)
    dataset_ok = (not any(integrity.values()) and
                  all(c["spy_sessions_all"] == c["spy_sessions_raw"] and not c["sessions_in_raw_not_in_all"]
                      for c in cov.values()))
    semantics_ok = json.loads((RES / "provider_semantics.json").read_text())["all_proven"]
    untouched = guard.state == "PREFLIGHT" and guard.validation_locked() and guard.replication_locked()
    cls = S.classify(gates, fingerprints_ok=fp_ok, raw_parity_ok=parity["RAW_PARITY"] == "PASS",
                     semantics_ok=semantics_ok, dataset_ok=dataset_ok, unexplained=unexplained,
                     holdout_untouched=untouched)
    res = {"survival_id": S.SURVIVAL_ID, "dataset": man["id"], "dataset_aggregate_sha256": man.get("dataset_aggregate_sha256"),
           "fingerprints_ok": fp_ok, "raw_parity": parity["RAW_PARITY"], "semantics_proven": semantics_ok,
           "dataset_integrity": integrity, "coverage": cov, "dataset_ok": dataset_ok,
           "corrected_development": st, "gates": gates, "diff_changes": changes, "diff_categories": cats,
           "unexplained": unexplained, "holdout_state": guard.state, "validation_data_present": False,
           "replication_data_present": False, "classification": cls}
    assert_research_path(OUTF)
    trades.to_csv(RES / "all_development_trades.csv", index=False)
    diff.to_csv(RES / "raw_vs_all_trade_diff.csv", index=False)
    OUTF.write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("classification", "corrected_development", "gates", "diff_changes",
                                        "diff_categories", "dataset_ok", "dataset_integrity")}, indent=1, default=str))
