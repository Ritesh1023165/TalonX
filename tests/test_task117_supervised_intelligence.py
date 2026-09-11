"""
Task 117 final-activation correction (A3): Intelligence-card delivery runs
under the ONE existing supervised ``intelligence`` ComponentSpec
(``talonx_ops.supervisor.default_talonx_components``), never a second manual
poller started outside the supervisor. The reviewed delivery configuration
(``TALONX_INTEL_DELIVER_CARDS`` / ``TALONX_INTEL_DRY_RUN_DELIVERY`` / ...)
reaches that child through ordinary env-var inheritance -- verified for real
via ``ProcessRunner.spawn()``'s ``env = dict(os.environ)``, not asserted.
"""
from __future__ import annotations

import dataclasses

from talonx_ops.supervisor import (
    Classification, SubprocessRunner, default_talonx_components,
)


def test_exactly_one_intelligence_component_no_duplicate():
    specs = default_talonx_components(include_dashboard=True, with_backfill=True)
    intel = [s for s in specs if s.name == "intelligence"]
    assert len(intel) == 1
    assert intel[0].classification == Classification.OPTIONAL
    assert "talonx_ingest.intelligence.service" in intel[0].argv
    assert "poll" in intel[0].argv


def test_intelligence_argv_never_includes_a_second_send_flag():
    """The supervised component itself must never carry --send -- delivery
    enablement is config-driven (env vars), not a CLI flag baked into the
    always-running supervised process argv (which would make --send-without-
    --i-understand-external-send an unreviewable, silent default)."""
    specs = default_talonx_components()
    intel = next(s for s in specs if s.name == "intelligence")
    assert "--send" not in intel.argv
    assert "--i-understand-external-send" not in intel.argv


def test_v2_is_never_included_via_supervisor_by_default():
    """Task 112T T1: the V2 companion is spawned separately by
    talonx_ops.prospective, never via supervisor include_v2 (that path reads
    stale parquet). default_talonx_components()'s own default must stay
    include_v2=False."""
    specs = default_talonx_components()
    assert not any(s.name == "v2" for s in specs)


def test_delivery_config_env_vars_reach_the_spawned_intelligence_child(tmp_path, monkeypatch):
    """Real env-var propagation: RealSubprocessRunner.spawn() builds its
    child env from THIS process's os.environ, exactly as
    talonx_ops.supervisor run (itself a child of `prospective start`) does.
    If the operator's shell / .env carries the delivery vars before running
    `prospective start`, they are inherited all the way to the supervised
    intelligence poll loop -- no second, unconfigured process needed."""
    monkeypatch.setenv("TALONX_INTEL_DELIVER_CARDS", "1")
    monkeypatch.setenv("TALONX_INTEL_DRY_RUN_DELIVERY", "0")

    specs = default_talonx_components(include_dashboard=False, with_backfill=False)
    intel = next(s for s in specs if s.name == "intelligence")

    runner = SubprocessRunner(log_dir=tmp_path)
    # spawn a real, tiny stand-in process that just prints the two env vars
    # it can see, proving the SAME env-inheritance path the real
    # intelligence child goes through actually carries them.
    import subprocess
    import sys
    probe_spec = dataclasses.replace(
        intel,
        argv=[sys.executable, "-c",
              "import os,sys; sys.stdout.write(os.environ.get('TALONX_INTEL_DELIVER_CARDS','')+','+"
              "os.environ.get('TALONX_INTEL_DRY_RUN_DELIVERY',''))"])
    handle = runner.spawn(probe_spec)   # a real subprocess.Popen, logged to tmp_path
    try:
        handle.wait(timeout=20)
    finally:
        if handle.poll() is None:
            handle.kill()
    text = (tmp_path / "intelligence.log").read_bytes().decode()
    assert text.strip() == "1,0"
