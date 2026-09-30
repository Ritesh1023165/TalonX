"""Task75B PREFLIGHT: frozen fingerprints, two-layer holdout guard state machine, range intersection, live-path write
refusal, bootstrap determinism/grouping, and the no-synthetic-bar / manifest / attribution helpers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.task75_v1.fingerprint import compute_contract_only_fingerprint, compute_fingerprint
from research.task75b_preflight import holdout as H

FULL = "08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3"
CONTRACT = "677adccd7e653e30c96122f0149356523f3a2fb3cb82a3d4967c3a1a06aa6f06"


def test_full_fingerprint_exact():
    assert compute_fingerprint() == FULL


def test_contract_only_fingerprint_exact():
    assert compute_contract_only_fingerprint() == CONTRACT
    rec = json.loads((Path(__file__).resolve().parents[1] / "results" /
                      "task75_cross_sectional_extreme_winner_short_reversion" / "candidate_fingerprint.json").read_text())
    assert rec["contract_only_fingerprint_sha256"] == CONTRACT and rec["full_fingerprint_sha256"] == FULL


def test_contract_still_records_raw_provenance():
    from research.task75_v1 import contracts as C
    assert C.DATA_ADJUSTMENT.startswith("raw")          # the frozen discovery provenance is never edited


def g(tmp_path, state="PREFLIGHT"):
    return H.HoldoutGuard(state, tmp_path / "state.json")


@pytest.mark.parametrize("layer", ["DOWNLOAD", "LOAD"])
def test_preflight_blocks_both_windows_allows_development(tmp_path, layer):
    gd = g(tmp_path)
    gd.check_range("2025-02-03", "2025-03-14", layer=layer)
    gd.check_range("2026-05-15", "2026-08-14", layer=layer)
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-06-01", "2024-06-05", layer=layer)
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-12-01", "2024-12-31", layer=layer)


@pytest.mark.parametrize("s,e", [("2024-05-01", "2024-06-01"),      # touches start boundary
                                 ("2024-09-02", "2024-09-30"),      # touches end boundary
                                 ("2024-08-01", "2024-10-01"),      # partial overlap
                                 ("2024-01-01", "2024-12-31"),      # full overlap
                                 ("2024-07-01", "2024-07-02")])     # fully inside
def test_intersection_boundaries(s, e):
    assert H.intersects(s, e, H.VALIDATION)


def test_non_intersecting_edges():
    assert not H.intersects("2024-05-01", "2024-05-31", H.VALIDATION)
    assert not H.intersects("2024-09-03", "2024-10-20", H.VALIDATION)
    assert not H.intersects("2024-09-03", "2024-10-20", H.REPLICATION)


def test_ready_opens_validation_only(tmp_path):
    gd = g(tmp_path)
    gd.transition("TASK75B_READY", authorized_by="test", reason="t")
    gd.check_range("2024-06-01", "2024-09-02", layer="DOWNLOAD")
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-10-21", "2024-12-20", layer="DOWNLOAD")


@pytest.mark.parametrize("final", ["VALIDATION_FAIL", "VALIDATION_INCONCLUSIVE"])
def test_fail_or_inconclusive_locks_replication_permanently(tmp_path, final):
    gd = g(tmp_path)
    for s in ("TASK75B_READY", "VALIDATION_RUNNING", final):
        gd.transition(s, authorized_by="test", reason="t")
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-11-01", "2024-11-05", layer="LOAD")
    with pytest.raises(H.HoldoutViolation):
        gd.transition("REPLICATION_UNLOCKED", authorized_by="test", reason="t")


def test_pass_makes_replication_eligible_but_still_locked_until_explicit_unlock(tmp_path):
    gd = g(tmp_path)
    for s in ("TASK75B_READY", "VALIDATION_RUNNING", "VALIDATION_PASS"):
        gd.transition(s, authorized_by="test", reason="t")
    assert gd.replication_locked()
    gd.transition("REPLICATION_UNLOCKED", authorized_by="operator", reason="explicit")
    gd.check_range("2024-11-01", "2024-11-05", layer="LOAD")


def test_no_skipping_states(tmp_path):
    with pytest.raises(H.HoldoutViolation):
        g(tmp_path).transition("VALIDATION_PASS", authorized_by="x", reason="skip")


def test_loader_guard_rejects_frames_with_protected_timestamps(tmp_path):
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2025-02-03 14:30", "2024-06-03 14:30"], utc=True)})
    with pytest.raises(H.HoldoutViolation):
        g(tmp_path).check_frame(df)
    g(tmp_path).check_frame(df.iloc[:1])


def test_state_is_durable(tmp_path):
    gd = g(tmp_path)
    gd.transition("TASK75B_READY", authorized_by="t", reason="t")
    assert H.HoldoutGuard.load(tmp_path / "state.json").state == "TASK75B_READY"


def test_unknown_state_fails_closed(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"state": "READY", "audit": []}))
    with pytest.raises(H.HoldoutViolation):
        H.HoldoutGuard.load(p)


def test_live_runtime_paths_cannot_be_written():
    with pytest.raises(H.HoldoutViolation):
        H.assert_research_path(Path("C:/workspace/TalonX/results/opportunity/market.db"))
    H.assert_research_path(Path(__file__).resolve().parents[1] / "results" / "task75b_preflight" / "x.json")


def test_bootstrap_deterministic_seed_and_grouping():
    from research.task67a_lib.research_stats import DEFAULT_SEED, bootstrap_ci_clustered
    assert DEFAULT_SEED == 670067
    rng = np.random.default_rng(1)
    v = rng.normal(0.5, 3, 400)
    sym = np.repeat([f"S{i}" for i in range(20)], 20)
    a = bootstrap_ci_clustered(v, sym, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    b = bootstrap_ci_clustered(v, sym, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    assert (a.ci_low, a.ci_high) == (b.ci_low, b.ci_high)
    day = np.tile([f"D{i}" for i in range(40)], 10)
    c = bootstrap_ci_clustered(v, day, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    assert (c.ci_low, c.ci_high) != (a.ci_low, a.ci_high)      # grouping matters: symbol vs entry_day
