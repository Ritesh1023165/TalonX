"""Task 83-R1 §2 -- immutable bindings vs mutable runtime status.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Drives the real
``ComparisonCollector`` with changing clocks (not one fixed clock).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.evidence import IMMUTABLE_MANIFEST_FIELDS
from talonx_compare.testing import make_pair, write_piv_state

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"
T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def piv_dir(tmp_path):
    d = tmp_path / "piv"
    write_piv_state(d)
    return d


@pytest.fixture
def cfg(tmp_path, piv_dir):
    return CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv_dir)


def _clock(t):
    return lambda: t


# --- 2.1 / 2.5 the reproduced defect: +5s must NOT conflict ---------------

def test_repeated_pass_different_clock_no_conflict(cfg):
    r1 = ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    assert r1.manifest_written is True and r1.manifest_conflict is False
    r2 = ComparisonCollector(cfg, clock=_clock(T0 + timedelta(seconds=5))).collect_once()
    assert r2.manifest_conflict is False, r2.manifest_changed_fields
    assert r2.manifest_written is False  # already written, identical bindings


def test_manifest_stable_over_many_passes(cfg):
    first = None
    for i in range(6):
        t = T0 + timedelta(minutes=i * 7, seconds=i)
        r = ComparisonCollector(cfg, clock=_clock(t)).collect_once()
        assert r.manifest_conflict is False
        raw = (cfg.evidence_root / DATE / "manifest.json").read_text()
        first = first or raw
        assert raw == first  # byte-identical immutable manifest every pass


# --- 2.2 / 2.3 field whitelist -----------------------------------------

def test_immutable_manifest_field_whitelist(cfg):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    manifest = json.loads((cfg.evidence_root / DATE / "manifest.json").read_text())
    assert set(manifest) <= IMMUTABLE_MANIFEST_FIELDS
    assert set(manifest) >= {"trading_date", "original", "piv", "collector"}


def test_manifest_excludes_mutable_fields(cfg):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    manifest = json.loads((cfg.evidence_root / DATE / "manifest.json").read_text())
    blob = json.dumps(manifest)
    for banned in ("generated_at", "reachable", "session_enabled", "kill_switch",
                   "health", "reconnect", "collection", "pass_count", "last_message"):
        assert banned not in blob, banned
    # and none of these appear under piv/original either
    assert "reachable_at_manifest_time" not in json.dumps(manifest["original"])
    assert "session_enabled" not in json.dumps(manifest["piv"])


# --- 2.4 deferred until bindings available ----------------------------

def test_manifest_deferred_until_bindings_available(cfg, piv_dir):
    # no identity, no events, no caller date -> nothing to anchor a manifest
    for f in ("session_identity.json", "piv_events.jsonl", "decision_ledger.json",
              "lifecycle_state.json"):
        (piv_dir / f).unlink(missing_ok=True)
    r = ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    assert r.trading_date is None
    assert "manifest NOT written" in (r.skipped_reason or "")
    assert not (cfg.evidence_root / DATE / "manifest.json").exists()


# --- 2.6 genuine binding change fails visibly, original preserved ------

_BINDING_CHANGES = {
    "session_id": dict(session_id="piv_2026-08-28_090000_zzzz0000"),
    "runtime_sha": dict(runtime_sha="cafebabe"),
    "config_hash": dict(config_hash="deadc0de"),
    "feed_mode": dict(feed_mode="IEX_PAPER_PIV"),
}


@pytest.mark.parametrize("field,override", list(_BINDING_CHANGES.items()))
def test_binding_change_fails_visibly(cfg, piv_dir, field, override):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    original_bytes = (cfg.evidence_root / DATE / "manifest.json").read_text()

    write_piv_state(piv_dir, **override)
    r = ComparisonCollector(cfg, clock=_clock(T0 + timedelta(seconds=5))).collect_once()

    assert r.manifest_conflict is True
    assert any(field in c or field.replace("_", "") in c for c in r.manifest_changed_fields), \
        r.manifest_changed_fields
    assert any(d["kind"] == "WRONG_SESSION" and d["source"] == "manifest.json"
               for d in r.diagnostics)
    # the ORIGINAL immutable manifest is untouched
    assert (cfg.evidence_root / DATE / "manifest.json").read_text() == original_bytes


def test_binding_change_redis_or_channel(cfg, piv_dir, monkeypatch):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    original_bytes = (cfg.evidence_root / DATE / "manifest.json").read_text()
    cfg2 = CompareConfig(state_dir=cfg.state_dir, evidence_root=cfg.evidence_root,
                         piv_state_dir=piv_dir, piv_redis_url="redis://localhost:6379/7")
    r = ComparisonCollector(cfg2, clock=_clock(T0 + timedelta(seconds=5))).collect_once()
    assert r.manifest_conflict is True
    assert (cfg.evidence_root / DATE / "manifest.json").read_text() == original_bytes


# --- 2.7 runtime status: separate, mutable, atomic -------------------

def test_runtime_status_file_written_atomically(cfg):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    rs_path = cfg.evidence_root / DATE / "runtime_status.json"
    assert rs_path.exists()
    # no stray temp files
    assert not list((cfg.evidence_root / DATE).glob("*.tmp"))
    rs = json.loads(rs_path.read_text())
    assert rs["trading_date"] == DATE


def test_runtime_status_has_mutable_fields(cfg):
    r1 = ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    rs1 = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    r2 = ComparisonCollector(cfg, clock=_clock(T0 + timedelta(minutes=3))).collect_once()
    rs2 = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    for key in ("generated_at", "collection", "transport_health", "source_health",
                "piv_lifecycle_status", "original_run_scope"):
        assert key in rs2, key
    assert rs1["generated_at"] != rs2["generated_at"]          # updated each pass
    assert rs2["collection"]["pass_count"] == 1                 # fresh collector object -> counts its own passes
    assert rs2["generated_at"] == (T0 + timedelta(minutes=3)).isoformat()


# --- 2.8 EOD updates the correct session; immutable identity intact ---

def test_eod_update_keeps_immutable_manifest(cfg, piv_dir):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    manifest_before = (cfg.evidence_root / DATE / "manifest.json").read_text()

    (piv_dir / "eod_state.json").write_text(json.dumps({
        "status": "PASSED", "trading_date_et": DATE, "completed_at": f"{DATE}T20:10:00+00:00",
    }), encoding="utf-8")
    r = ComparisonCollector(cfg, clock=_clock(T0 + timedelta(hours=5))).collect_once()

    assert r.manifest_conflict is False
    assert (cfg.evidence_root / DATE / "manifest.json").read_text() == manifest_before
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    assert rs["eod_status"] == "PASSED"
    assert rs["piv_session_id"] == SESSION
    piv_recs = [json.loads(x) for x in
                (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    eod = [x for x in piv_recs if x["stage"] == "eod"]
    assert eod and eod[0]["run_scope"] == SESSION and eod[0]["decision_outcome"] == "PASSED"


# --- 2.9 health transition covered ---------------------------------

def test_health_transition_does_not_touch_manifest(cfg):
    ComparisonCollector(cfg, clock=_clock(T0)).collect_once()
    mb = (cfg.evidence_root / DATE / "manifest.json").read_text()
    # pass with an explicit transport-health snapshot (as CollectorService would)
    ComparisonCollector(cfg, clock=_clock(T0 + timedelta(seconds=30))).collect_once(
        transport_health={"ORIGINAL": {"state": "DISCONNECTED", "last_error": "boom"},
                          "PIV": {"state": "RUNNING"}})
    assert (cfg.evidence_root / DATE / "manifest.json").read_text() == mb
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    assert rs["transport_health"]["ORIGINAL"]["state"] == "DISCONNECTED"
