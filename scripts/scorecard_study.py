"""TICKER_SCORECARD_V1 study steps (pre-registration: Execution order). Each step runs ONCE and its result file is final.

  freeze   : hash the panel and features, write row counts. Computes no returns.
  fit      : fit RIDGE and isotonic calibration on TRAIN. Reads TRAIN outcomes only.
  validate : read VALIDATE once; choose EQ or RIDGE per horizon.
  holdout  : read HOLDOUT once for the chosen composite; apply gates G1-G5 and the decision table.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from talonx_scorecard import config as C, features, labels, metrics as M, model as MD, panel  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402

import os  # noqa: E402
STUDY = Path(os.environ.get("SCORECARD_STUDY_DIR", ROOT / "results" / "scorecard_v1"))
FEATURE_HASH_THROUGH = C.SEGMENTS["HOLDOUT"][1]      # SEC features can gain later rows (new filings); freeze what the study reads


def head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return "unknown"


def load(panel_path: str, sec_path: str):
    fr = pd.read_pickle(panel_path)
    sec = pd.read_pickle(sec_path)
    raw = {**features.raw_price_features(fr["adj_close"]), **sec}
    return fr, raw


def feature_hash(raw: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(raw):
        h.update(k.encode())
        h.update(pd.util.hash_pandas_object(raw[k].loc[:FEATURE_HASH_THROUGH].round(10), index=True).to_numpy().tobytes())
    return h.hexdigest()


def panel_hash(fr: dict) -> str:
    return panel.frame_sha256({"adj_close": fr["adj_close"], "raw_close": fr["raw_close"], "raw_volume": fr["raw_volume"], "spy": fr["spy"].to_frame("SPY")})


def refuse_if_done(path: Path):
    if path.exists():
        print(f"REFUSED: {path} already exists. A step that wrote its result file is final.", file=sys.stderr)
        raise SystemExit(4)


def require_freeze(fr, raw) -> dict:
    p = STUDY / "freeze" / "freeze.json"
    if not p.exists():
        print("REFUSED: run the freeze step first", file=sys.stderr); raise SystemExit(5)
    fz = json.loads(p.read_text())
    ph, fh = panel_hash(fr), feature_hash(raw)
    if fz["panel_sha256"] != ph or fz["feature_sha256"] != fh or fz["spec_fingerprint"] != C.spec_fingerprint():
        print(f"REFUSED: inputs differ from the frozen panel (panel {ph[:12]} vs {fz['panel_sha256'][:12]}, "
              f"features {fh[:12]} vs {fz['feature_sha256'][:12]})", file=sys.stderr)
        raise SystemExit(6)
    return fz


def iso_to_json(iso: IsotonicRegression) -> dict:
    return {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]}


def iso_from_json(d: dict) -> IsotonicRegression:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(np.array(d["x"]), np.array(d["y"]))
    return iso


def stamp(extra: dict) -> dict:
    return {"code_head": head(), "spec_fingerprint": C.spec_fingerprint(), "spec_commit": C.SPEC_COMMIT,
            "utc": pd.Timestamp.now("UTC").isoformat(), **extra}


def seg_inputs(fr, raw, horizon, segment, cache):
    sessions = fr["adj_close"].index
    dates = labels.segment_rank_dates(sessions, horizon, segment)
    need = [d for d in dates if d not in cache]
    cache.update(MD.build_cube(raw, fr["universe"], need))
    return dates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["freeze", "fit", "validate", "holdout"])
    ap.add_argument("--panel", default="results/scorecard_v1/panel/panel_frames.pkl.gz")
    ap.add_argument("--features", default="results/scorecard_v1/sec/raw_features.pkl.gz")
    a = ap.parse_args()
    fr, raw = load(a.panel, a.features)
    sessions, uni = fr["adj_close"].index, fr["universe"]
    out = STUDY / a.step
    out.mkdir(parents=True, exist_ok=True)

    if a.step == "freeze":
        res = out / "freeze.json"
        refuse_if_done(res)
        info = stamp({"panel_sha256": panel_hash(fr), "feature_sha256": feature_hash(raw), "sessions": len(sessions),
                      "symbols": int(fr["adj_close"].shape[1]), "universe_name_days": int(uni.to_numpy().sum()),
                      "features_present": sorted(raw), "features_missing": sorted(set(f.id for f in C.FEATURES) - set(raw))})
        res.write_text(json.dumps(info, indent=2)); print(json.dumps(info, indent=2)); return 0

    require_freeze(fr, raw)
    excess = {h: labels.excess_return(fr["adj_close"], fr["spy"], n) for h, n in C.HORIZONS.items()}
    cache: dict = {}

    if a.step == "fit":
        res = out / "fit.json"
        refuse_if_done(res)
        info = {"weights": {}, "calibration": {}, "train_ic": {}, "feature_ic_train": {}, "n_train_dates": {}}
        for h in C.HORIZONS:
            dates = seg_inputs(fr, raw, h, "TRAIN", cache)
            cube = {d: cache[d] for d in dates}
            w = MD.fit_ridge(cube, excess[h], dates)
            info["weights"][h] = w.to_dict()
            info["calibration"][h] = {"EQ": iso_to_json(MD.fit_calibration(cube, excess[h], dates, None)),
                                      "RIDGE": iso_to_json(MD.fit_calibration(cube, excess[h], dates, w))}
            tr = {}
            for name, ww in (("EQ", None), ("RIDGE", w)):
                per, _ = MD.evaluate(cube, excess[h], dates, ww, iso_from_json(info["calibration"][h][name]), h)
                tr[name] = float(per["ic"].mean())
            info["train_ic"][h] = tr
            fic = {}
            for fid in MD.FIDS:                              # sign check: IC of each already-signed feature, should be > 0
                ics = []
                for d in dates:
                    x = cube[d][fid]; y = excess[h].loc[d].reindex(x.index); ok = y.notna()
                    if ok.sum() >= 30 and x[ok].nunique() > 1:
                        ics.append(M.spearman(x[ok].to_numpy(), y[ok].to_numpy()))
                fic[fid] = float(np.nanmean(ics)) if ics else None
            info["feature_ic_train"][h] = fic
            info["n_train_dates"][h] = len(dates)
            print(h, "TRAIN IC", tr, flush=True)
        res.write_text(json.dumps(stamp(info), indent=2)); return 0

    fit = json.loads((STUDY / "fit" / "fit.json").read_text()) if (STUDY / "fit" / "fit.json").exists() else None
    if fit is None:
        print("REFUSED: run the fit step first", file=sys.stderr); return 5
    W = {h: pd.Series(fit["weights"][h]) for h in C.HORIZONS}
    ISO = {h: {k: iso_from_json(v) for k, v in fit["calibration"][h].items()} for h in C.HORIZONS}

    if a.step == "validate":
        res = out / "choice.json"
        refuse_if_done(res)
        info = {"choice": {}, "ic": {}}
        for h in C.HORIZONS:
            dates = seg_inputs(fr, raw, h, "VALIDATE", cache)
            cube = {d: cache[d] for d in dates}
            ic = {}
            for name, ww in (("EQ", None), ("RIDGE", W[h])):
                per, _ = MD.evaluate(cube, excess[h], dates, ww, ISO[h][name], h)
                ic[name] = float(per["ic"].mean())
            info["ic"][h] = ic
            info["choice"][h] = "RIDGE" if ic["RIDGE"] - ic["EQ"] >= C.RIDGE_MIN_IC_GAIN else "EQ"
            print(h, ic, "->", info["choice"][h], flush=True)
        res.write_text(json.dumps(stamp(info), indent=2)); return 0

    choice_p = STUDY / "validate" / "choice.json"
    if not choice_p.exists():
        print("REFUSED: run the validate step first", file=sys.stderr); return 5
    choice = json.loads(choice_p.read_text())["choice"]
    res = out / "verdict.json"
    refuse_if_done(res)
    info = {"horizons": {}}
    outcomes, hol_ic = {}, {}
    for h in C.HORIZONS:
        dates = seg_inputs(fr, raw, h, "HOLDOUT", cache)
        cube = {d: cache[d] for d in dates}
        name = choice[h]
        per, pooled = MD.evaluate(cube, excess[h], dates, None if name == "EQ" else W[h], ISO[h][name], h)
        g = M.gates(per, pooled, h)
        outcome, note = M.decide(g, h)
        fic = {}
        for fid in MD.FIDS:
            ics = []
            for d in dates:
                x = cube[d][fid]; y = excess[h].loc[d].reindex(x.index); ok = y.notna()
                if ok.sum() >= 30 and x[ok].nunique() > 1:
                    ics.append(M.spearman(x[ok].to_numpy(), y[ok].to_numpy()))
            fic[fid] = float(np.nanmean(ics)) if ics else None
        info["horizons"][h] = {"composite": name, "gates": {k: g[k] for k in ("G1", "G2", "G3", "G4", "G5")}, "metrics": {k: v for k, v in g.items() if not k.startswith("G")},
                               "outcome": outcome, "note": note, "feature_ic_holdout": fic,
                               "turnover_and_coverage": {"mean_names_per_date": float(np.mean([len(cube[d]) for d in dates]))}}
        outcomes[h] = outcome; hol_ic[h] = g["mean_ic"]
        print(h, name, outcome, {k: round(g[k], 4) if isinstance(g[k], float) else g[k] for k in ("mean_ic", "ic_lower95", "top_excess", "bottom_excess", "positive_month_share", "bull_hit", "bear_hit", "ece")}, flush=True)
    info["programme"] = M.programme_outcome(outcomes, hol_ic, {h: fit["train_ic"][h][choice[h]] for h in C.HORIZONS})
    res.write_text(json.dumps(stamp(info), indent=2)); print(info["programme"]); return 0


if __name__ == "__main__":
    raise SystemExit(main())
