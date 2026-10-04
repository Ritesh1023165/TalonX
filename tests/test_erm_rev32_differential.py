"""LOCK REV 3.2 differential test: revision 3.1 code (53eb2da) vs the current code, the REAL phase_d.stage_run on the
same deterministic fixture store -> identical events, outcomes, d0_coverage.json, cells.csv, report.md, trial_ledger
.json (and screen.csv, which neither revision produces). 3.2 runs with 2 parallel evaluate workers, 3.1 sequentially.
Offline: the fixture SEC archive is complete and the driver refuses any socket connect."""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REV31 = "53eb2da"
PATHS = ["research", "talonx_v2", "talonx_premarket", "docs/research/preregistration"]
DRIVER = REPO / "research" / "event_response_map_v1" / "tools" / "rev_diff_driver.py"


def _rev31(dst: Path) -> None:
    r = subprocess.run(["git", "archive", "--format=tar", REV31, "--", *PATHS], cwd=REPO, capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"git archive {REV31} unavailable: {r.stderr[:200]!r}")
    tarfile.open(fileobj=io.BytesIO(r.stdout)).extractall(dst)


def _current(dst: Path) -> None:
    for p in PATHS:
        src = REPO / p
        shutil.copytree(src, dst / p, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _run(code_root: Path, dump: Path, workers: int) -> None:
    r = subprocess.run([sys.executable, str(DRIVER), str(code_root), str(dump), "--workers", str(workers)],
                       cwd=code_root, capture_output=True, text=True, env={**__import__("os").environ,
                                                                           "PYTHONPATH": str(code_root)},
                       timeout=3600)
    assert r.returncode == 0, f"driver failed for {code_root}:\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}"



def test_rev31_vs_rev32_identical_on_fixture(tmp_path):
    a, b = tmp_path / "rev31", tmp_path / "rev32"
    a.mkdir()
    b.mkdir()
    _rev31(a)
    _current(b)
    _run(a, tmp_path / "dump31", workers=1)
    _run(b, tmp_path / "dump32", workers=2)
    names = sorted(p.name for p in (tmp_path / "dump31").iterdir())
    assert names == sorted(p.name for p in (tmp_path / "dump32").iterdir())
    for must in ("events_1.csv", "outcomes_1.csv", "events_2.csv", "outcomes_2.csv", "cells.csv", "report.md",
                 "trial_ledger.json", "d0_coverage.json", "screen.csv"):
        assert must in names, must
    diff = [n for n in names if (tmp_path / "dump31" / n).read_bytes() != (tmp_path / "dump32" / n).read_bytes()]
    assert diff == [], f"revision 3.1 vs 3.2 outputs differ: {diff}"
    # the fixture really exercises the paths that changed
    out = (tmp_path / "dump32" / "outcomes_1.csv").read_text()
    assert "True" in out                                   # missing exits and/or suspect adjustments present
    led = (tmp_path / "dump32" / "trial_ledger.json").read_text()
    assert '"SCREEN_PASS": true' in led, "fixture should produce at least one SCREEN_PASS cell (diagnostic path)"
