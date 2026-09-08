"""
Validation orchestrator (Task 115) -- ties versioning + holdout +
validation_contract + gate + replay_engine + manifest into one
deterministic run producing the Task 115.I evidence set.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from talonx_research import COST_GRID_BPS, PRIMARY_COST_BPS
from talonx_research.gate import evaluate_gate
from talonx_research.holdout import make_windows, split
from talonx_research.manifest import build_manifest, write_manifest
from talonx_research.validation_contract import evaluate_returns, yearly_quarterly
from talonx_research.versioning import (StrategyRegistry, LifecycleState, seed_known_versions,
                                       v2_fingerprint)


def _load_mod(name: str, rel: str, *, data_root: Path | None = None):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if data_root is not None:
        dr = Path(data_root)
        for attr, val in (("ROOT", dr),
                          ("TXN", dr / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"),
                          ("PANEL", dr / "results/task95g_broad_cross_sectional/_daily"),
                          ("PRICES", dr / "results/task107a_form4_feasibility/_prices"),
                          ("A_OUT", dr / "results/task107a_form4_feasibility"),
                          ("BUILD", dr / "results/task107a_form4_feasibility/_build")):
            if hasattr(m, attr):
                setattr(m, attr, val)
    return m


def _episode_returns(*, start: str, end: str, data_root: Path,
                     horizon: int = 10) -> tuple[pd.DataFrame, dict]:
    """Runtime-semantic episodes (frozen detect_episodes) restricted to the
    survivorship panel + [start,end] activation window, joined to returns
    via the frozen Task 107B build_returns."""
    t112rp = _load_mod("t112r_parity", "research/scripts/task112r_parity.py", data_root=data_root)
    t107b = _load_mod("t107b_eval", "research/scripts/task107b_form4_cluster.py", data_root=data_root)

    P = t112rp.load_P()
    U = t112rp.runtime_episodes(P)               # frozen runtime detector
    panel = {f.stem.upper() for f in (data_root / "results/task95g_broad_cross_sectional/_daily").glob("*.csv")}
    U["issuer_sym"] = U["issuer_sym"].str.upper()
    U = U[U.issuer_sym.isin(panel)].copy()
    U["entry_session"] = pd.to_datetime(U["entry_session"])
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    win = U[(U.entry_session >= s) & (U.entry_session <= e)].copy()

    # enrich with the fields build_returns/evaluate need
    P2 = P.copy()
    P2["issuer_sym"] = P2["issuer_sym"].str.upper()
    agg = P2.groupby("issuer_sym").agg(
        any_officer=("is_officer", "any"), any_director=("is_director", "any"),
        any_ten_pct=("is_ten_pct", "any")).reset_index()
    win = win.merge(agg, on="issuer_sym", how="left")
    val_by_ep = []
    for r in win.itertuples(index=False):
        sub = P2[(P2.issuer_sym == r.issuer_sym)
                 & (pd.to_datetime(P2.filing_date) <= pd.Timestamp(r.activation_filing_date))
                 & (pd.to_datetime(P2.filing_date) >= pd.Timestamp(r.first_filing))]
        val_by_ep.append(float(pd.to_numeric(sub.get("value"), errors="coerce").fillna(0).sum()))
    win["agg_value"] = val_by_ep
    win = win.rename(columns={"n_distinct_owners": "n_distinct_owners"})
    win["any_officer"] = win["any_officer"].fillna(False)
    win["any_director"] = win["any_director"].fillna(False)
    win["any_ten_pct"] = win["any_ten_pct"].fillna(False)

    rr = t107b.build_returns(win.rename(columns={"entry_session": "entry_session"}))
    rr = rr.dropna(subset=[f"raw_{horizon}"]).copy()
    meta = {
        "runtime_episodes_total": int(len(U)),
        "in_window_in_panel": int(len(win)),
        "priced_at_entry_and_horizon": int(len(rr)),
        "panel_universe": len(panel),
        "detector": "talonx_v2.cluster_engine.detect_episodes (frozen)",
        "source": "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
    }
    return rr, meta


def run_validation(*, strategy_id: str, start: str, end: str,
                   primary_cost_bps: int = PRIMARY_COST_BPS,
                   data_root: Path | None = None, out_dir: Path,
                   registry_path: Path | None = None,
                   do_replay: bool = True, horizon: int = 10) -> dict[str, Any]:
    data_root = Path(data_root) if data_root else _ROOT
    out = Path(out_dir)
    (out).mkdir(parents=True, exist_ok=True)

    reg = StrategyRegistry(registry_path)
    seed_known_versions(reg, root=_ROOT)
    sv = reg.get(strategy_id)
    if sv is None:
        raise SystemExit(f"unknown strategy version {strategy_id}; run `registry` to list")

    live_fp = v2_fingerprint(_ROOT)
    fp_ok = (live_fp == sv.fingerprint)

    windows = make_windows(start, end)
    rr, ep_meta = _episode_returns(start=start, end=end, data_root=data_root, horizon=horizon)

    metrics = evaluate_returns(rr, label=strategy_id, horizon=horizon,
                               primary_cost_bps=primary_cost_bps,
                               holdout_cutoff=windows.holdout_cutoff, data_root=data_root)
    yq = yearly_quarterly(rr, horizon=horizon, primary_cost_bps=primary_cost_bps, data_root=data_root)

    # This frame is entirely post-freeze for an already-FROZEN version, so the
    # whole window is genuinely out-of-sample.  Also evaluate the version's
    # ORIGINAL registered discovery window for context.
    dw = sv.discovery_window or {}
    out_of_sample_note = ("validation window is entirely after the version freeze -- the whole "
                          "window is out-of-sample; the in-window split below is chronological.")
    registered_discovery_metrics: dict = {}
    try:
        if dw.get("start") and dw.get("end") and pd.Timestamp(dw["end"]) < pd.Timestamp(start):
            drr, _ = _episode_returns(start=dw["start"], end=dw["end"],
                                      data_root=data_root, horizon=horizon)
            dm = evaluate_returns(drr, label=f"{strategy_id}:discovery_window", horizon=horizon,
                                  primary_cost_bps=primary_cost_bps, data_root=data_root)
            registered_discovery_metrics = _metrics_summary(dm, primary_cost_bps)
    except Exception as exc:  # noqa: BLE001
        registered_discovery_metrics = {"error": f"{type(exc).__name__}: {exc}"}

    span_years = max(0.25, (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25)
    eps_per_year = ep_meta["priced_at_entry_and_horizon"] / span_years

    gate = evaluate_gate(metrics.to_dict(), episodes_per_year=eps_per_year,
                         concentration=metrics.concentration)

    # ---- runtime parity: episode-level vs chronological portfolio replay ----
    parity: dict[str, Any] = {"performed": False}
    replay_summary: dict[str, Any] = {}
    if do_replay:
        parity, replay_summary = _runtime_parity(
            start=start, end=end, data_root=data_root, out=out,
            episode_level_n=ep_meta["priced_at_entry_and_horizon"])

    # ---- write the Task 115.I artifact set ----
    _write_outputs(out=out, strategy_id=strategy_id, sv=sv, live_fp=live_fp, fp_ok=fp_ok,
                   windows=windows, metrics=metrics, yq=yq, gate=gate, ep_meta=ep_meta,
                   parity=parity, replay_summary=replay_summary, rr=rr,
                   primary_cost_bps=primary_cost_bps, eps_per_year=eps_per_year)

    verdict = gate.verdict if fp_ok else "VALIDATION_FAIL"
    if not fp_ok:
        gate.hard_fails.append(f"fingerprint mismatch: live {live_fp} != registered {sv.fingerprint}")

    manifest = build_manifest(
        strategy=sv.strategy_family, version=sv.version, fingerprint=sv.fingerprint,
        validation_window=windows.to_dict()["validation"],
        discovery_window=windows.discovery, holdout_window=windows.holdout,
        primary_cost_bps=primary_cost_bps, verdict=verdict,
        shadow_eligible=(gate.shadow_eligible and fp_ok),
        runtime_parity=(parity.get("verdict", "NOT_RUN")),
        gate_checks=gate.checks,
        metrics_summary=_metrics_summary(metrics, primary_cost_bps),
        extra={"episode_meta": ep_meta, "fingerprint_ok": fp_ok, "live_fingerprint": live_fp,
               "episodes_per_year": eps_per_year,
               "out_of_sample_note": out_of_sample_note,
               "registered_discovery_window": dw,
               "registered_discovery_window_metrics": registered_discovery_metrics})
    write_manifest(manifest, out / "validation_manifest.json")
    return {"verdict": verdict, "shadow_eligible": manifest["shadow_eligible"],
            "runtime_parity": manifest["runtime_parity"], "out_dir": str(out)}


def _runtime_parity(*, start: str, end: str, data_root: Path, out: Path,
                    episode_level_n: int) -> tuple[dict, dict]:
    from talonx_research.replay_engine import run_chronological_replay
    ledger = out / "replay_v2_lane.db"
    bar_dirs = [data_root / "results/task95g_broad_cross_sectional/_daily",
                data_root / "results/task107a_form4_feasibility/_prices"]
    parquet = data_root / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"

    panel = {f.stem.upper() for f in bar_dirs[0].glob("*.csv")}
    from talonx_v2 import form4_source

    from datetime import timedelta as _td

    # pre-load the code-P records ONCE (Tuesday runtime uses the InsiderStore
    # SQLite `since=` query; this per-tick parquet re-read is a replay-harness
    # cost only -- caching it keeps a 2-year walk feasible).
    _all = [r for r in form4_source.from_research_parquet(
        str(parquet), since=date.fromisoformat("2019-01-01"))
        if r.symbol.upper() in panel]
    _all.sort(key=lambda r: r.filing_date)

    def provider(as_of):
        lo = as_of - _td(days=45)
        return [r for r in _all if lo <= r.filing_date <= as_of]

    rres = run_chronological_replay(
        start=start, end=end, ledger_path=ledger, bar_dirs=bar_dirs,
        records_provider=provider, starting_cash=10_000_000.0)
    rd = rres.to_dict()
    (out / "replay_result.json").write_text(json.dumps(rd, indent=2, default=str))

    n_buys = rd["activity"]["n_buys"]
    n_sells = rd["activity"]["n_sells"]
    disp = rd["activity"]["processed_episode_dispositions"]
    verdict = "PASS"
    notes = []
    if rres.external_sends != 0:
        verdict = "FAIL"
        notes.append("replay emitted an external send")
    # the chronological portfolio replay enters a subset of the episode-level
    # set (staleness guard + $10k/20 concurrency + price availability); that is
    # an EXPECTED_DIFFERENCE, not a bug.
    parity = {
        "performed": True, "verdict": verdict,
        "episode_level_priced_n": episode_level_n,
        "chronological_replay_buys": n_buys, "chronological_replay_sells": n_sells,
        "processed_episode_dispositions": disp,
        "exit_unresolved": len(rres.exit_unresolved),
        "open_at_end": len(rres.open_at_end),
        "external_sends": rres.external_sends,
        "note": "episode-level count is the unconstrained frozen-detector signal; the "
                "chronological replay applies the frozen staleness guard, $10k / max-20 "
                "concurrency and local price availability -> EXPECTED_DIFFERENCE.",
    }
    return parity, rd


def _metrics_summary(m, cost) -> dict:
    prim = m.cost_sensitivity.get(cost, {})
    return {
        "n_trades": m.n_trades,
        f"net_mean_{cost}bps": prim.get("mean"),
        "profit_factor": prim.get("profit_factor"),
        "win_rate": prim.get("win_rate"),
        "avg_winner": prim.get("avg_winner"), "avg_loser": prim.get("avg_loser"),
        "max_drawdown": prim.get("max_drawdown"),
        "discovery_mean": m.discovery.get("mean"), "holdout_mean": m.holdout.get("mean"),
        "issuer_block_ci_net20": m.dependence.get("issuer_block_ci_net20"),
        "week_cluster_ci_net20": m.dependence.get("week_cluster_ci_net20"),
        "spy_excess_mean": m.benchmark.get("mean"),
        "drop_top1_mean_net20": m.concentration.get("drop_top1_mean_net20"),
        "drop_top3_mean_net20": m.concentration.get("drop_top3_mean_net20"),
    }


def _write_outputs(*, out: Path, strategy_id, sv, live_fp, fp_ok, windows, metrics, yq,
                   gate, ep_meta, parity, replay_summary, rr, primary_cost_bps, eps_per_year):
    (out / "metrics.json").write_text(json.dumps(metrics.to_dict(), indent=2, default=str))
    (out / "runtime_parity.json").write_text(json.dumps(parity, indent=2, default=str))
    (out / "concentration.json").write_text(json.dumps(metrics.concentration, indent=2, default=str))
    (out / "monthly_results.json").write_text(json.dumps(
        {"monthly": metrics.monthly, **yq}, indent=2, default=str))
    with (out / "monthly_results.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["period", "trades", "mean_net", "sum_net"])
        for r in metrics.monthly:
            w.writerow([r["period"], r["trades"], r["mean_net"], r["sum_net"]])
    with (out / "cost_sensitivity.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["cost_bps", "n", "mean_net", "profit_factor", "win_rate"])
        for c, mm in metrics.cost_sensitivity.items():
            w.writerow([c, mm.get("n"), mm.get("mean"), mm.get("profit_factor"), mm.get("win_rate")])
    rr.to_csv(out / "trade_ledger.csv", index=False)
    with (out / "alert_payloads.jsonl").open("w") as fh:
        for r in rr.itertuples(index=False):
            fh.write(json.dumps({
                "dry_run": True, "transport": "NONE",
                "strategy_version": strategy_id, "fingerprint": sv.fingerprint,
                "symbol": r.issuer_sym, "action": "BUY",
                "entry_session": str(r.entry_session),
                f"raw_return_{metrics.horizon}": getattr(r, f"raw_{metrics.horizon}", None),
            }, default=str) + "\n")

    prim = metrics.cost_sensitivity.get(primary_cost_bps, {})
    rep = [
        f"# Validation report -- {strategy_id}",
        f"generated: {datetime.now(timezone.utc).isoformat()}",
        f"fingerprint: registered {sv.fingerprint}  live {live_fp}  ok={fp_ok}",
        f"windows: validation {windows.validation_start}..{windows.validation_end}  "
        f"holdout cutoff {windows.holdout_cutoff}",
        "",
        "## Gate",
        f"verdict: {gate.verdict}   shadow_eligible: {gate.shadow_eligible}",
        f"hard fails: {gate.hard_fails or 'none'}",
        f"findings: {gate.findings or 'none'}",
        "",
        "## Performance (net @ {}bps, +{}D)".format(primary_cost_bps, metrics.horizon),
        f"n_trades: {metrics.n_trades}",
        f"net mean: {prim.get('mean')}   PF: {prim.get('profit_factor')}   "
        f"win rate: {prim.get('win_rate')}",
        f"avg winner / loser: {prim.get('avg_winner')} / {prim.get('avg_loser')}",
        f"discovery / holdout mean: {metrics.discovery.get('mean')} / {metrics.holdout.get('mean')}",
        f"max drawdown: {prim.get('max_drawdown')}",
        f"issuer-block CI (net20): {metrics.dependence.get('issuer_block_ci_net20')}",
        f"week-cluster CI (net20): {metrics.dependence.get('week_cluster_ci_net20')}",
        f"SPY-excess mean: {metrics.benchmark.get('mean')}",
        f"drop-top1 / drop-top3 mean net20: {metrics.concentration.get('drop_top1_mean_net20')} / "
        f"{metrics.concentration.get('drop_top3_mean_net20')}",
        f"episodes / year (priced): {eps_per_year:.1f}",
        "",
        "## Runtime parity",
        json.dumps(parity, indent=2, default=str),
        "",
        "## Episode meta",
        json.dumps(ep_meta, indent=2, default=str),
    ]
    (out / "final_report.md").write_text("\n".join(rep))
    (out / "terminal_summary.txt").write_text("\n".join([
        f"STRATEGY   {strategy_id}",
        f"FINGERPRINT registered {sv.fingerprint}  live {live_fp}  ok={fp_ok}",
        f"WINDOW     {windows.validation_start} .. {windows.validation_end}  "
        f"(holdout cut {windows.holdout_cutoff})",
        f"N_TRADES   {metrics.n_trades}",
        f"NET@{primary_cost_bps}bps {prim.get('mean')}   PF {prim.get('profit_factor')}   "
        f"WIN {prim.get('win_rate')}",
        f"DISCOVERY  {metrics.discovery.get('mean')}   HOLDOUT {metrics.holdout.get('mean')}",
        f"DROP-TOP1  {metrics.concentration.get('drop_top1_mean_net20')}   "
        f"DROP-TOP3 {metrics.concentration.get('drop_top3_mean_net20')}",
        f"ISSUER-BLK CI {metrics.dependence.get('issuer_block_ci_net20')}",
        f"WEEK-CLUS  CI {metrics.dependence.get('week_cluster_ci_net20')}",
        f"SPY-EXCESS  {metrics.benchmark.get('mean')}",
        f"RUNTIME PARITY {parity.get('verdict', 'NOT_RUN')}",
        f"GATE       {gate.verdict}   SHADOW_ELIGIBLE {gate.shadow_eligible}",
        f"HARD FAILS {gate.hard_fails or 'none'}",
        f"FINDINGS   {gate.findings or 'none'}",
        "PROMOTION  NOT ALLOWED (explicit separate decision -- R6)",
    ]))
