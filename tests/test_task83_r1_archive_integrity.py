"""Task 83-R1 §6 -- fail-closed archive integrity.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.evidence import REQUIRED_FILES, EvidenceWriter
from talonx_compare.testing import write_piv_state

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"
T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION)
    return CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)


def _healthy_archive(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    return EvidenceWriter(cfg.evidence_root, DATE)


# --- 6.1 required file set defined --------------------------

def test_required_file_set_defined():
    assert "manifest.json" in REQUIRED_FILES
    assert "runtime_status.json" in REQUIRED_FILES
    assert "file_hashes.json" not in REQUIRED_FILES  # it hashes the others
    assert set(REQUIRED_FILES) == {
        "manifest.json", "runtime_status.json", "original_events.jsonl",
        "piv_records.jsonl", "comparison.json", "divergences.json",
        "telegram.json", "diagnostics.json",
    }


def test_fresh_archive_is_healthy(cfg):
    w = _healthy_archive(cfg)
    integ = w.verify_archive()
    assert integ.ok and integ.state == "HEALTHY", integ.problems


# --- 6.2 the verifier detects every corruption class --------

def test_verifier_detects_required_missing(cfg):
    w = _healthy_archive(cfg)
    (w.dir / "comparison.json").unlink()
    integ = w.verify_archive()
    assert not integ.ok
    assert any("required file missing: comparison.json" in p for p in integ.problems)


def test_verifier_detects_unexpected_file(cfg):
    w = _healthy_archive(cfg)
    (w.dir / "surprise.json").write_text("{}", encoding="utf-8")
    integ = w.verify_archive()
    assert any("unexpected file" in p for p in integ.problems)


def test_verifier_detects_malformed_json(cfg):
    w = _healthy_archive(cfg)
    (w.dir / "comparison.json").write_text("{ not json", encoding="utf-8")
    integ = w.verify_archive()
    assert integ.state == "UNREADABLE"
    assert any("malformed JSON" in p for p in integ.problems)


def test_verifier_detects_malformed_jsonl(cfg):
    w = _healthy_archive(cfg)
    with (w.dir / "piv_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    integ = w.verify_archive()
    assert any("malformed JSONL record" in p for p in integ.problems)


def test_verifier_detects_missing_and_duplicate_id(cfg):
    w = _healthy_archive(cfg)
    lines = (w.dir / "piv_records.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    no_id = dict(first); no_id.pop("_id")
    with (w.dir / "piv_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(first) + "\n")        # duplicate _id
        fh.write(json.dumps(no_id) + "\n")        # missing _id
    integ = w.verify_archive()
    assert any("duplicate _id" in p for p in integ.problems)
    assert any("missing _id" in p for p in integ.problems)


def test_verifier_detects_hash_mismatch(cfg):
    w = _healthy_archive(cfg)
    p = w.dir / "diagnostics.json"
    p.write_text(p.read_text(encoding="utf-8").replace("}", " } ", 1), encoding="utf-8")
    integ = w.verify_archive()
    assert any("hash mismatch" in x for x in integ.problems)


def test_verifier_detects_truncated_stream(cfg):
    w = _healthy_archive(cfg)
    p = w.dir / "piv_records.jsonl"
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw.rstrip("\n") + '{"partial":', encoding="utf-8")   # no trailing newline
    integ = w.verify_archive()
    assert any("truncated append-only stream" in x for x in integ.problems)


def test_verifier_detects_wrong_date(cfg):
    w = _healthy_archive(cfg)
    lines = (w.dir / "piv_records.jsonl").read_text().splitlines()
    bad = json.loads(lines[0]); bad["trading_date"] = "2025-01-01"; bad["_id"] = bad["_id"] + "X"
    with (w.dir / "piv_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(bad) + "\n")
    integ = w.verify_archive()
    assert any("wrong-date record" in x for x in integ.problems)


def test_verifier_detects_incomplete_hash_inventory(cfg):
    w = _healthy_archive(cfg)
    inv = json.loads((w.dir / "file_hashes.json").read_text())
    inv["hashes"].pop("comparison.json")
    (w.dir / "file_hashes.json").write_text(json.dumps(inv), encoding="utf-8")
    integ = w.verify_archive()
    assert any("incomplete hash inventory" in x for x in integ.problems)


# --- 6.3 malformed records never silently discarded ---------

def test_malformed_jsonl_not_silently_skipped(cfg):
    w = _healthy_archive(cfg)
    with (w.dir / "piv_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("GARBAGE\n")
    recs, problems = w.read_records_with_problems("piv_records.jsonl")
    assert problems and any("piv_records.jsonl" in p for p in problems)


# --- 6.4 write refused on pre-existing corruption -----------

def test_write_refused_on_pre_existing_corruption(cfg, piv_dir=None):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    # corrupt the archive between passes
    (cfg.evidence_root / DATE / "comparison.json").write_text("{ broken", encoding="utf-8")
    hashes_before = (cfg.evidence_root / DATE / "file_hashes.json").read_text()

    r = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(minutes=5)).collect_once()
    assert r.write_aborted is True
    assert r.original_appended == 0 and r.piv_appended == 0
    # hashes were NOT regenerated over corruption
    assert (cfg.evidence_root / DATE / "file_hashes.json").read_text() == hashes_before
    assert any(d["kind"] == "UNREADABLE" and "ABORTED" in d["detail"] for d in r.diagnostics)


# --- 6.5 atomic mutable writes -----------------------------

def test_mutable_writes_are_atomic(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    d = cfg.evidence_root / DATE
    # no leftover temp files from any atomic write
    assert not list(d.glob("*.tmp")) and not list(d.glob(".*tmp"))
    for name in ("runtime_status.json", "comparison.json", "file_hashes.json"):
        assert (d / name).read_text().endswith("\n")


# --- 6.6 collect-once takes the collector lock -------------

def test_collect_once_takes_collector_lock(cfg, monkeypatch):
    import talonx_compare.collector as mod

    seen = {"acquired": False}
    real = mod.CollectorLock

    class Spy(real):
        def acquire(self, *a, **k):
            seen["acquired"] = True
            return super().acquire(*a, **k)

    monkeypatch.setattr(mod, "CollectorLock", Spy)
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    assert seen["acquired"] is True


# --- 6.7 integrity metadata updated only after successful writes ---

def test_integrity_metadata_updated_after_write(cfg):
    r1 = ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    h1 = json.loads((cfg.evidence_root / DATE / "file_hashes.json").read_text())["hashes"]
    # a legitimate late append
    dl = json.loads((cfg.piv_state_dir / "decision_ledger.json").read_text())
    dl["dLATE"] = {"session_id": SESSION, "trading_date_et": DATE, "symbol": "MSFT",
                   "timestamp": f"{DATE}T15:30:00+00:00", "recommendation": "HOLD",
                   "reason_codes": [], "market_view": "NEUTRAL",
                   "decision_execution_status": "NO_ACTION", "data_readiness": "COMPLETE"}
    (cfg.piv_state_dir / "decision_ledger.json").write_text(json.dumps(dl), encoding="utf-8")
    r2 = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(minutes=5)).collect_once()
    assert r2.piv_appended == 1
    h2 = json.loads((cfg.evidence_root / DATE / "file_hashes.json").read_text())["hashes"]
    assert h2["piv_records.jsonl"] != h1["piv_records.jsonl"]   # updated
    assert r2.archive_integrity["ok"] is True


# --- 6.8 dashboards surface corruption ---------------------

def test_dashboard_flags_corruption(cfg):
    from talonx_compare.dashboard_views import compare_view

    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    (cfg.evidence_root / DATE / "divergences.json").write_text("nope", encoding="utf-8")
    view = compare_view(config=cfg, trading_date=DATE)
    assert view["trustworthy"] is False
    assert view["archive_integrity"]["ok"] is False
    assert view["per_stage_totals"] == {}                 # not shown as trustworthy
    assert view["untrusted_comparison"] is not None        # still available, clearly labelled
