"""ERM nominee validation -- end-to-end workflow / run state machine (r9 §10).

config -> owner decisions -> scoped authorisation -> ACQUIRE (archive + manifest) -> LOAD (sha256-verified, guarded)
-> BUILD (V2.1 manifest) -> OUTCOMES -> GATES -> DIAGNOSTICS -> REPORT -> RUN_COMPLETE.json (written LAST).

Components are injected (guard, acquirer, loader). Production components: ValidationGuard (release disabled) +
ProductionAcquirer (not implemented) + ProductionLoader. Tests inject fixture components; there is no bypass flag.

Run-state rules (r9 §7 step 0, §10):
  * RUN_COMPLETE.json present                         -> refuse (never overwrite a completed run)
  * previous attempt failed AFTER outcomes existed    -> refuse (no retry once outcomes exist; owner decides)
  * previous attempt failed BEFORE outcomes, 1 attempt -> one re-execution; its partial outputs are moved to
                                                         attempt_<n>/ and preserved
  * second failure                                    -> ABORT (status ABORTED_OWNER_DECIDES), no further attempts
  * report and marker are written only after every stage succeeded; a failure leaves status INCOMPLETE_<stage>,
    lists the outputs present and states whether outcomes were exposed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from research.erm_nominee_validation import builder as B, diagnostics as DG, gates as G
from research.erm_nominee_validation.config import MIN_SAMPLE_FLOOR, ValidationConfig

HERE = Path(__file__).resolve().parents[2]
OUTPUTS = ("archive", "manifest.csv", "duplicate_groups.csv", "obs.csv", "gates.json", "diagnostics.json", "report.md")


class RunRefused(RuntimeError):
    pass


class StageFailure(RuntimeError):
    def __init__(self, stage: str, cause: BaseException):
        super().__init__(f"{stage}: {type(cause).__name__}: {cause}")
        self.stage, self.cause = stage, cause


@dataclass
class Components:
    guard: object
    acquirer: object
    loader: object


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identities(cfg: ValidationConfig, auth: dict | None) -> dict:
    pk = HERE / "research/erm_nominee_validation"
    code = {p.relative_to(HERE).as_posix(): sha(p) for p in sorted(pk.glob("*.py"))}
    for p in ("research/erm_nominee_audit/v2_rules.py", "research/event_response_map_v1/events.py",
              "research/event_response_map_v1/metrics.py", "research/event_response_map_v1/universe.py",
              "research/event_response_map_v1/data.py", "research/common/research_stats.py"):
        code[p] = sha(HERE / p)
    spec = {p: sha(HERE / p) for p in ("docs/research/preregistration/ERM_NOMINEE_CORRECTION_SPEC_V2_1.md",
                                       "docs/research/preregistration/ERM_NOMINEE_PREREG_DRAFT_r9.md")
            if (HERE / p).exists()}
    return {"config": cfg.canonical(), "config_hash": cfg.config_hash(), "code_sha256": code, "spec_sha256": spec,
            "authorisation_sha256": hashlib.sha256(json.dumps(auth or {}, sort_keys=True).encode()).hexdigest()}


def _record(run: Path, rec: dict) -> None:
    B.atomic(run / "run_record.json", json.dumps(rec, indent=1, default=str))


def _prior_state(run: Path) -> dict | None:
    p = run / "run_record.json"
    return json.loads(p.read_text()) if p.exists() else None


def run_validation(cfg: ValidationConfig, auth: dict | None, comp: Components, run: Path) -> dict:
    # 1 owner decisions + scoped authorisation BEFORE any protected request, read or run-state change (a refused
    #   precheck writes nothing and never consumes the re-execution allowance)
    cfg.require_decided()
    comp.guard.authorise(auth)
    run.mkdir(parents=True, exist_ok=True)
    # ---------------------------------------------------------------------------------------------- run-state policy
    if (run / "RUN_COMPLETE.json").exists():
        raise RunRefused("RUN_COMPLETE.json exists: a completed run is never overwritten")
    prior = _prior_state(run)
    attempt = 1
    if prior:
        if prior.get("outcome_exposure"):
            raise RunRefused("a previous attempt failed after outcomes existed: no retry (owner decides)")
        if prior.get("status") == "ABORTED_OWNER_DECIDES" or prior.get("attempt", 1) >= 2:
            raise RunRefused("re-execution allowance exhausted: ABORTED, owner decides")
        attempt = prior.get("attempt", 1) + 1
        keep = run / f"attempt_{prior.get('attempt', 1)}"
        keep.mkdir()
        for name in OUTPUTS + ("run_record.json",):
            if (run / name).exists():
                shutil.move(str(run / name), str(keep / name))
    rec = {"run": "ERM_NOMINEE_HISTORICAL_VALIDATION", "attempt": attempt, "started_utc": now(), "status": "STARTED",
           "precheck": "owner decisions decided; scoped authorisation accepted by the guard",
           "outcome_exposure": False, "stages_done": [], **identities(cfg, auth)}
    _record(run, rec)

    def stage(name, fn):
        rec["status"] = f"RUNNING_{name}"
        _record(run, rec)
        try:
            out = fn()
        except BaseException as e:  # noqa: BLE001 -- classified, recorded, re-raised
            present = sorted(n for n in OUTPUTS if (run / n).exists())
            final = "ABORTED_OWNER_DECIDES" if attempt >= 2 else f"INCOMPLETE_{name}"
            rec.update(status=final, failed_stage=name, error=f"{type(e).__name__}: {e}", ended_utc=now(),
                       outputs_present=present, traceback=traceback.format_exc(limit=5),
                       retry_allowed=(attempt == 1 and not rec["outcome_exposure"]),
                       partial_outputs_note="PARTIAL OUTPUTS -- NOT A RESULT; no report, no completion marker")
            _record(run, rec)
            raise StageFailure(name, e) from e
        if name != "MARKER":                               # the marker stage finalises the record itself;
            rec["stages_done"].append(name)                # nothing is written after RUN_COMPLETE.json
            _record(run, rec)
        return out

    archive = run / "archive"
    archive.mkdir(exist_ok=True)

    def acquire():
        from research.erm_nominee_validation.adapters import AcquisitionIncomplete
        m = comp.acquirer.acquire(cfg, archive)
        if not m.get("complete"):
            raise AcquisitionIncomplete(f"acquisition incomplete: missing {m.get('missing')}")
        return m
    man = stage("ACQUIRE", acquire)
    rec["archive_manifest_sha256"] = sha(archive / "ARCHIVE_MANIFEST.json")
    loaded = stage("LOAD", lambda: comp.loader.load(archive, cfg))

    def build():
        pop = []
        for tag, eq, raw in loaded.archives:
            pop += B.population(eq, raw, loaded.sessions, cfg.start, cfg.end, tag)
        import pandas as pd
        eqs = pd.concat([a for _, a, _ in loaded.archives])
        raws = pd.concat([r for _, _, r in loaded.archives])
        syms = {s for _, s, _, _ in pop}
        ser = B.series(eqs[eqs["symbol"].isin(syms)], raws[raws["symbol"].isin(syms)])
        rows, groups = B.build(pop, ser, loaded.sessions, loaded.meta, cfg.end)
        keys = [(r["symbol"], r["entry"]) for r in rows]
        if len(keys) != len(set(keys)):
            raise RuntimeError("manifest invariant violated: duplicate (symbol, entry) rows")
        bad = [k for k, r in zip(keys, rows) if r["v2_status"] == "VALID" and not r["benchmark_v2"]]
        if bad:
            raise RuntimeError(f"manifest invariant violated: VALID rows without benchmark: {bad[:5]}")
        if rows:
            rec["manifest_sha256"] = B.write_manifest(rows, groups, run)
        return rows
    rows = stage("BUILD", build)

    def outcomes():
        import pandas as pd
        from research.event_response_map_v1 import events as E
        valid = [r for r in rows if r["v2_status"] == "VALID"]
        me = [r for r in rows if r["v2_status"] == "DATA_MISSING_EXIT"]
        from datetime import date as _d
        bmap = {(r["symbol"], _d.fromisoformat(r["entry"])): r["benchmark_v2"] for r in valid}
        ev = pd.DataFrame({"event_type": "GAP_UP_10", "symbol": [r["symbol"] for r in valid],
                           "event_date": [_d.fromisoformat(r["gap_day"]) for r in valid],
                           "entry_date": [_d.fromisoformat(r["entry"]) for r in valid], "bucket": "L1"})
        ev = ev.sort_values(["entry_date", "symbol"]).reset_index(drop=True)
        rec["outcome_exposure"] = True                     # from here on, outcomes may exist: no automatic retry
        _record(run, rec)
        cols = ["event_type", "symbol", "entry_date", "bucket", "horizon", "ret_raw", "ret_spy_rel", "ret_sector_rel",
                "benchmark", "suspect_adjustment", "missing_exit"]
        if valid:
            with B.window_bounds(cfg.start, cfg.end):
                o, cnt = E.outcomes(ev, loaded.bars_all, loaded.bench, lambda s, d: bmap[(s, d)], loaded.sessions)
            o = o[o["horizon"] == "H10"].reset_index(drop=True)
        else:                                              # n = 0: empty frame with the frozen outcome schema
            o, cnt = pd.DataFrame(columns=cols), {}
        if len(o) != len(valid) or o["missing_exit"].any():
            raise RuntimeError(f"outcomes inconsistent with manifest: {len(o)} vs {len(valid)} ({cnt})")
        mex = pd.DataFrame({"event_type": "GAP_UP_10", "symbol": [r["symbol"] for r in me],
                            "entry_date": [_d.fromisoformat(r["entry"]) for r in me], "bucket": "L1", "horizon": "H10",
                            "ret_raw": float("nan"), "ret_spy_rel": float("nan"), "ret_sector_rel": float("nan"),
                            "benchmark": None, "suspect_adjustment": False, "missing_exit": True})
        obs = (pd.concat([o, mex], ignore_index=True) if len(o) else mex) if len(mex) else o
        B.atomic(run / "obs.csv", obs.to_csv(index=False, lineterminator="\n"))
        return obs
    obs = stage("OUTCOMES", outcomes)

    d = cfg.decisions
    stock_c, etf_c = 30 / 1e4, d.etf_cost_bps / 1e4

    def gates():
        x, grp, nm = G.pair_net(obs, stock_c, etf_c)
        g = G.gates(x, grp, nm)
        label, step = G.verdict(g, d.min_sample_floor_adopted, MIN_SAMPLE_FLOOR)
        out = {"gates": g, "verdict": label, "scheme": G.scheme(label), "rule": step,
               "costs": {"stock_bps": 30, "etf_bps": d.etf_cost_bps},
               "etf_cost_sensitivities_descriptive": G.sensitivities(x, grp, etf_c)}
        B.atomic(run / "gates.json", json.dumps(out, indent=1, default=float))
        return out, x
    gres, x = stage("GATES", gates)

    def diagnostics():
        import numpy as np
        from datetime import date as _d
        valid = [r for r in rows if r["v2_status"] == "VALID"]
        bars = loaded.bars_all
        bmap = {(r["symbol"], r["entry"]): r for r in valid}
        evs, pn, held = [], {}, []
        vo = obs[~obs["missing_exit"].astype(bool)]
        for r in vo.itertuples():
            row = bmap[(r.symbol, str(r.entry_date))]
            ent, ex = _d.fromisoformat(row["entry"]), _d.fromisoformat(row["exit"])
            sb = bars[(bars["symbol"] == r.symbol) & (bars["date"] >= ent) & (bars["date"] <= ex)]
            eb = loaded.bench[row["benchmark_v2"]]
            eb = eb[(eb["date"] >= ent) & (eb["date"] <= ex)]
            evs.append({"entry": ent, "exit": ex,
                        "stock": {t.date: (t.open, t.high, t.close) for t in sb.itertuples()},
                        "etf": {t.date: (t.open, t.close) for t in eb.itertuples()}})
            pn[(r.symbol, row["entry"])] = float(-r.ret_sector_rel - stock_c - etf_c)
            held.append((ent, ex))
        out = {"label": "DESCRIPTIVE ONLY -- never gating",
               "frozen_cell_diagnostics": DG.frozen_cell_diagnostics(obs),
               "unit_book": DG.unit_book(evs, loaded.sessions, stock_c, etf_c),
               "worst_and_mae": DG.worst_and_mae(evs, pn),
               "break_even_borrow": DG.break_even_borrow(list(pn.values()), held),
               "descriptive_subset_rows": int(sum(1 for r in valid if r["sens_no_detected_stock_adj_or_etf_cash_div"] == "IN_SUBSET"))}
        out["unit_book"].pop("daily_pnl_units")
        B.atomic(run / "diagnostics.json", json.dumps(out, indent=1, default=float))
        return out
    diag = stage("DIAGNOSTICS", diagnostics)

    def report():
        g = gres["gates"]
        lines = [f"# ERM historical validation -- {cfg.window_id} ({cfg.start}..{cfg.end})", "",
                 f"**Verdict: {gres['verdict']}** (scheme: {gres['scheme']}; rule {gres['rule']})", "",
                 "Statistical acceptance of the pre-borrow hedged adjusted-return proxy on the V2.1 evidence-covered "
                 "population; not executable profitability. Conditional on entry-date clustering (overlap not "
                 "captured), prior exposure, evidence coverage and the proxy.", "",
                 "| Gate | Value | Result |", "|---|---|---|",
                 f"| G1 mean(pair_net) > 0 | {g['mean']} | {g['G1']} |",
                 f"| G2 CI low > 0 | [{g['ci_low']}, {g['ci_high']}] | {g['G2']} |",
                 f"| G3 mean without top 5 > 0 | {g['mean_without_top5']} | {g['G3']} |",
                 f"| G4 missing exits <= 2 % | {g['missing_exit_rate']} | {g['G4']} |", "",
                 f"n_valid {g['n_valid']}, dates {g['distinct_dates']}, missing exits {g['n_missing_exit']}.", "",
                 "## Descriptive (non-gating)", "", "```json", json.dumps(diag, indent=1, default=float), "```", ""]
        B.atomic(run / "report.md", "\n".join(lines))
    stage("REPORT", report)

    def marker():
        outs = {n: sha(run / n) for n in OUTPUTS if n != "archive" and (run / n).exists()}
        missing = [n for n in ("gates.json", "diagnostics.json", "report.md", "obs.csv") if n not in outs]
        if missing:
            raise RuntimeError(f"cannot mark complete; missing outputs {missing}")
        rec["stages_done"].append("MARKER")
        rec.update(status="COMPLETE", verdict=gres["verdict"], ended_utc=now(), outputs_sha256=outs)
        _record(run, rec)
        B.atomic(run / "RUN_COMPLETE.json", json.dumps({"utc": now(), "verdict": gres["verdict"],
                                                        "run_record_sha256": sha(run / "run_record.json")}))
    stage("MARKER", marker)
    return rec
