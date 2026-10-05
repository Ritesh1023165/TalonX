"""Synthetic END-TO-END tests of the ERM nominee validation workflow (research/erm_nominee_validation/workflow.py).

Fixture adapters live ONLY in this test module (no production bypass flag). The fixture acquirer writes inputs in the
REAL archive formats (frozen Phase D bar pages + manifest, SEC insider zip, submissions gz, filing headers,
master.idx, S&P CSV, ETF cash-dividend JSON), so the PRODUCTION loader, the frozen data.load, the V2.1 builder, the
frozen events.outcomes, gates, diagnostics, report and marker all run for real on synthetic data. Only the guard
transition and acquisition are fixtures. No SEC / Alpaca call, no protected data, temporary paths only.
"""
import gzip
import hashlib
import io
import json
import os
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from research.erm_nominee_validation import adapters as A, workflow as W
from research.erm_nominee_validation.config import (HYPOTHESIS, OwnerDecisionPending, OwnerDecisions,
                                                     ValidationConfig)
from research.erm_nominee_validation.guard import (GuardReleaseNotAuthorised, ValidationGuard,
                                                    check_authorisation_scope)

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "docs/research/preregistration/rs_sector_mapping_v1.json"
DECIDED = OwnerDecisions(window="B", task75_reserve_acknowledged=True, min_sample_floor_adopted=True, etf_cost_bps=4,
                         procedural_amendments_approved=True, decision_record="fixture")
CFG = ValidationConfig("B", DECIDED)
N_SYM = 70


def auth_for(cfg, **over):
    a = {"hypothesis": HYPOTHESIS, "window_id": cfg.window_id, "config_hash": cfg.config_hash(), "owner_go": True}
    a.update(over)
    return a


# ------------------------------------------------------------------------------------------------ fixture guard
class FixtureGuard:
    """Fixture transition: refuses EVERY acquisition/load until a correctly scoped authorisation is accepted, and any
    request outside [window start - 120 d, window end] even afterwards."""

    def __init__(self, cfg):
        self.cfg, self.released, self.calls = cfg, False, []

    def authorise(self, auth):
        check_authorisation_scope(auth, self.cfg)          # the SAME scope check production uses
        self.released = True

    def _ok(self, a, b):
        return self.released and a >= self.cfg.start - timedelta(days=120) and b <= self.cfg.end

    def check_acquisition(self, a, b, what):
        self.calls.append(("acq", what))
        if not self._ok(a, b):
            raise GuardReleaseNotAuthorised(f"fixture guard refused acquisition {what} {a}..{b}")

    def frame_guard(self):
        return self

    def check_frame(self, df, layer="LOAD", ts_col="timestamp"):
        import pandas as pd
        self.calls.append(("load", layer))
        t = pd.to_datetime(df[ts_col], utc=True)
        if len(t) and not self._ok(t.min().date(), t.max().date()):
            raise GuardReleaseNotAuthorised("fixture guard refused load")


# ------------------------------------------------------------------------------------------------ synthetic world
def sessions():
    out, d = [], date(2023, 11, 1)
    while len(out) < 180:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def world():
    """N_SYM named operating stocks; each has two +12 % gaps followed by an 11-session 3 % decline (a short profit);
    distinct price levels and volumes per symbol so no two series are duplicates. SPY and XLK flat."""
    ss = sessions()
    bars = {}
    for k in range(N_SYM):
        sym = "S" + chr(65 + k // 26) + chr(65 + k % 26)
        p, vol, rows = 10.0 + 0.12 * k, 3_000_000 + 7919 * k, []      # stays inside L1 ($20M-$100M ADV)
        gaps = {45 + (k % 50), 105 + (k % 50)}          # both inside window B (starts at session ~41)
        decline = {}
        for i, d in enumerate(ss):
            o = p
            if i in gaps:
                o = p * 1.12
                for j in range(1, 12):
                    decline[i + j] = 0.97 ** (1 / 11)
            c = o * decline.get(i, 1.0)
            rows.append((d, o, max(o, c) * 1.001, min(o, c) * 0.999, c, vol))
            p = c
        bars[sym] = rows
    for etf in ("SPY", "XLK"):
        bars[etf] = [(d, 100.0, 100.1, 99.9, 100.0, 50_000_000) for d in ss]
    return ss, bars


def ts(d):
    return datetime(d.year, d.month, d.day, 5, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FixtureAcquirer:
    def __init__(self, guard, omit=(), corrupt=None, break_subs=False, no_identity=False):
        self.guard, self.omit, self.corrupt, self.break_subs, self.no_identity = guard, set(omit), corrupt, break_subs, no_identity
        self.called = 0

    def acquire(self, cfg, arc: Path) -> dict:
        self.called += 1
        ss, bars = world()
        written = {}

        def put(name, rel, data: bytes):
            self.guard.check_acquisition(ss[0], ss[-1], name)
            p = arc / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            written.setdefault(name, []).append(rel)

        man = {"files": []}
        for purpose in ("RETURNS", "ELIGIBILITY_ONLY"):
            body = json.dumps({"bars": {s: [{"t": ts(d), "o": o, "h": h, "l": l, "c": c, "v": v}
                                            for d, o, h, l, c, v in rows]
                                        for s, rows in bars.items() if not (purpose == "ELIGIBILITY_ONLY" and s in ("SPY", "XLK"))}}).encode()
            name = f"{purpose.lower()}_0.json.gz"
            put("bars", f"bars/{name}", gzip.compress(body, mtime=0))
            man["files"].append({"file": name, "purpose": purpose, "sha256": hashlib.sha256(body).hexdigest()})
        put("bars", "bars/manifest.json", json.dumps(man).encode())
        stocks = [s for s in bars if s not in ("SPY", "XLK")]
        cik = {s: str(1000 + i).zfill(10) for i, s in enumerate(stocks)}
        put("candidates", "candidates.json", json.dumps({"names": {s: f"{s} Inc" for s in stocks},
                                                         "symbols": {s: ["A"] for s in stocks},
                                                         "identity_cik": cik}).encode())
        tsv = "ACCESSION_NUMBER\tFILING_DATE\tISSUERCIK\tISSUERTRADINGSYMBOL\n" + "".join(
            f"x{i}\t01-OCT-2023\t{int(cik[s])}\t{s}\n" for i, s in enumerate(stocks) if not self.no_identity)
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.writestr("SUBMISSION.TSV", tsv)
        put("form345", "sec/2023q4_form345.zip.gz", gzip.compress(zb.getvalue(), mtime=0))
        put("renames", "renames.json", b"[]")
        for s in stocks:
            doc = {"filings": {"recent": {"filingDate": ["2023-08-01"], "form": ["10-Q"], "accessionNumber": [f"acc-{s}"],
                                          "items": [""], "reportDate": ["2023-06-30"]}, "files": []}}
            if self.break_subs:
                doc = {"broken": True}
            put("submissions", f"sec/sub_CIK{cik[s]}.json.gz", gzip.compress(json.dumps(doc).encode(), mtime=0))
            put("filing_headers", f"sec/hdr_acc-{s}.html.gz",
                gzip.compress(b"STANDARD INDUSTRIAL CLASSIFICATION: COMPUTER [3571]\n", mtime=0))
        put("master_idx", "sec/master_2023_QTR3.idx.gz", gzip.compress(
            "".join(f"{int(cik[s])}|{s} Inc|10-Q|2023-08-01|x\n" for s in stocks).encode(), mtime=0))
        put("sp500_pit", "sp500.csv", b"date,tickers\n2023-01-03,SPY\n")
        put("etf_cash_dividends", "etf_div.json", json.dumps([{"symbol": "XLK", "ex_date": "2023-12-15"}]).encode())
        for k in self.omit:
            for rel in written.pop(k, []):
                (arc / rel).unlink()
        out = A.write_archive_manifest(arc, written)
        if self.corrupt:
            p = arc / self.corrupt
            p.write_bytes(p.read_bytes() + b" ")
        return out


def comps(**kw):
    g = FixtureGuard(CFG)
    return W.Components(guard=g, acquirer=FixtureAcquirer(g, **kw), loader=A.ProductionLoader(g, MAPPING))


# ------------------------------------------------------------------------------------------------ tests
def test_successful_full_workflow_marker_written_last(tmp_path):
    rec = W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    assert rec["status"] == "COMPLETE" and rec["verdict"] == "PASS_STATISTICAL_PROXY_PRE_BORROW"
    g = json.loads((tmp_path / "gates.json").read_text())
    assert g["scheme"] == "PASS" and g["gates"]["n_valid"] >= 100 and g["gates"]["distinct_dates"] >= 40
    assert g["gates"]["mean"] > 0 and all(g["gates"][k] for k in ("G1", "G2", "G3", "G4"))
    marker = tmp_path / "RUN_COMPLETE.json"
    others = [tmp_path / n for n in ("manifest.csv", "obs.csv", "gates.json", "diagnostics.json", "report.md")]
    assert all(p.exists() for p in others)
    assert marker.stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in others)
    m = json.loads(marker.read_text())
    assert m["run_record_sha256"] == hashlib.sha256((tmp_path / "run_record.json").read_bytes()).hexdigest()
    rr = json.loads((tmp_path / "run_record.json").read_text())
    assert rr["config_hash"] == CFG.config_hash() and "research/erm_nominee_audit/v2_rules.py" in rr["code_sha256"]
    assert rr["archive_manifest_sha256"] and json.loads((tmp_path / "archive/ARCHIVE_MANIFEST.json").read_text())["complete"]
    d = json.loads((tmp_path / "diagnostics.json").read_text())
    assert d["label"].startswith("DESCRIPTIVE") and d["unit_book"]["concurrency"]["max"] >= 1
    assert abs(d["unit_book"]["cumulative_pnl_units"] - g["gates"]["mean"] * g["gates"]["n_valid"]) < 1e-9
    assert "Verdict: PASS_STATISTICAL_PROXY_PRE_BORROW" in (tmp_path / "report.md").read_text()


def test_pending_owner_choices_rejected_before_any_acquisition(tmp_path):
    c = comps()
    with pytest.raises(OwnerDecisionPending):
        W.run_validation(ValidationConfig("B", OwnerDecisions()), auth_for(CFG), c, tmp_path)
    assert c.acquirer.called == 0 and c.guard.calls == [] and not any(tmp_path.iterdir())


@pytest.mark.parametrize("auth", [None, {"window_id": "A"}, {"hypothesis": "OTHER|CELL"}, {"config_hash": "x"},
                                  {"owner_go": False}])
def test_missing_or_misscoped_authorisation_rejected(tmp_path, auth):
    c = comps()
    a = None if auth is None else auth_for(CFG, **auth)
    with pytest.raises(GuardReleaseNotAuthorised):
        W.run_validation(CFG, a, c, tmp_path)
    assert c.acquirer.called == 0 and not c.guard.released and not any(tmp_path.iterdir())


def test_incomplete_acquisition_classified_and_retry_allowed(tmp_path):
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(omit=("form345",)), tmp_path)
    rr = json.loads((tmp_path / "run_record.json").read_text())
    assert rr["status"] == "INCOMPLETE_ACQUIRE" and rr["outcome_exposure"] is False and rr["retry_allowed"] is True
    assert not (tmp_path / "report.md").exists() and not (tmp_path / "RUN_COMPLETE.json").exists()


def test_input_hash_mismatch_fails_at_load(tmp_path):
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth_for(CFG), comps(corrupt="renames.json"), tmp_path)
    assert isinstance(e.value.cause, A.InputHashMismatch)
    assert json.loads((tmp_path / "run_record.json").read_text())["status"] == "INCOMPLETE_LOAD"


def test_identity_metadata_failure_fails_build_without_outcomes(tmp_path):
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(break_subs=True), tmp_path)
    rr = json.loads((tmp_path / "run_record.json").read_text())
    assert rr["status"] == "INCOMPLETE_BUILD" and rr["outcome_exposure"] is False and not (tmp_path / "obs.csv").exists()


def test_absent_identity_evidence_gives_inconclusive_not_a_crash(tmp_path):
    rec = W.run_validation(CFG, auth_for(CFG), comps(no_identity=True), tmp_path)
    g = json.loads((tmp_path / "gates.json").read_text())
    assert rec["status"] == "COMPLETE" and g["gates"]["n_valid"] == 0 and g["verdict"] == "INCONCLUSIVE"


def test_scoring_failure_after_outcomes_blocks_retry(tmp_path, monkeypatch):
    from research.erm_nominee_validation import diagnostics as DG

    def boom(*a, **k):
        raise RuntimeError("diagnostics failure")
    monkeypatch.setattr(DG, "unit_book", boom)
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    rr = json.loads((tmp_path / "run_record.json").read_text())
    assert rr["status"] == "INCOMPLETE_DIAGNOSTICS" and rr["outcome_exposure"] is True and rr["retry_allowed"] is False
    assert "obs.csv" in rr["outputs_present"] and "PARTIAL OUTPUTS" in rr["partial_outputs_note"]
    assert not (tmp_path / "report.md").exists() and not (tmp_path / "RUN_COMPLETE.json").exists()
    monkeypatch.undo()
    with pytest.raises(W.RunRefused, match="after outcomes"):
        W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)


def test_report_write_failure_leaves_no_marker(tmp_path, monkeypatch):
    real = W.B.atomic

    def flaky(path, text):
        if Path(path).name == "report.md":
            raise OSError("disk full")
        return real(path, text)
    monkeypatch.setattr(W.B, "atomic", flaky)
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    rr = json.loads((tmp_path / "run_record.json").read_text())
    assert rr["status"] == "INCOMPLETE_REPORT" and not (tmp_path / "RUN_COMPLETE.json").exists()


def test_completed_run_is_never_overwritten(tmp_path):
    W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    before = (tmp_path / "RUN_COMPLETE.json").read_bytes()
    with pytest.raises(W.RunRefused, match="never overwritten"):
        W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    assert (tmp_path / "RUN_COMPLETE.json").read_bytes() == before


def test_one_reexecution_preserves_partial_outputs_then_abort(tmp_path):
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(corrupt="renames.json"), tmp_path)
    with pytest.raises(W.StageFailure):                                        # attempt 2 also fails -> ABORT
        W.run_validation(CFG, auth_for(CFG), comps(corrupt="renames.json"), tmp_path)
    prev = json.loads((tmp_path / "attempt_1/run_record.json").read_text())
    assert prev["status"] == "INCOMPLETE_LOAD" and (tmp_path / "attempt_1/archive/ARCHIVE_MANIFEST.json").exists()
    assert json.loads((tmp_path / "run_record.json").read_text())["status"] == "ABORTED_OWNER_DECIDES"
    with pytest.raises(W.RunRefused, match="exhausted"):
        W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)


def test_reexecution_after_preoutcome_failure_can_complete(tmp_path):
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth_for(CFG), comps(omit=("renames",)), tmp_path)
    rec = W.run_validation(CFG, auth_for(CFG), comps(), tmp_path)
    assert rec["status"] == "COMPLETE" and rec["attempt"] == 2
    assert json.loads((tmp_path / "attempt_1/run_record.json").read_text())["status"] == "INCOMPLETE_ACQUIRE"


# ------------------------------------------------------------------------------------------------ production stays closed
def test_production_components_refuse_even_with_scoped_authorisation(tmp_path):
    g = ValidationGuard(CFG)
    c = W.Components(guard=g, acquirer=A.ProductionAcquirer(g), loader=A.ProductionLoader(g, MAPPING))
    with pytest.raises(GuardReleaseNotAuthorised, match="no reviewed guard transition"):
        W.run_validation(CFG, auth_for(CFG), c, tmp_path)
    assert not any(tmp_path.iterdir())
    with pytest.raises(GuardReleaseNotAuthorised):
        A.ProductionAcquirer(g).acquire(CFG, tmp_path)                       # guard refuses before the stub


def test_production_loader_refuses_protected_rows_via_frozen_guard(tmp_path):
    g = FixtureGuard(CFG)
    g.authorise(auth_for(CFG))
    FixtureAcquirer(g).acquire(CFG, tmp_path)                                 # synthetic rows dated 2023-11..2024-07
    with pytest.raises(Exception) as e:
        A.ProductionLoader(ValidationGuard(CFG), MAPPING).load(tmp_path, CFG)
    assert "LOCKED" in str(e.value) or "refused" in str(e.value)


def test_cli_execute_propagates_refusal():
    from research.erm_nominee_validation import run
    with pytest.raises(OwnerDecisionPending):
        run.main(["--window", "B", "--execute"])
