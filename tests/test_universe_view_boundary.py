"""Boundary fix: talonx_ops/operator_control/universe_view.py no longer imports the research lane. Its V2 scope is a
read-only parse of the same V2 companion log with the same rule. Proof that Sentinel's /universe output is IDENTICAL
before (module source at 86f7375, which imported talonx_premarket) and after, on one fixture store."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from talonx_ops.operator_control import universe_view as UV
from tests.test_sentinel_universe_overrides import NOW, READERS, WID, _market

REPO = Path(__file__).resolve().parents[1]
BASE = "86f7375"
HEAD_TXT = "🌐 TalonX Sentinel"


def _old_module():
    r = subprocess.run(["git", "show", f"{BASE}:talonx_ops/operator_control/universe_view.py"], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        pytest.skip(f"base source {BASE} not available: {r.stderr[:100]}")
    mod = types.ModuleType("uv_before")
    mod.__file__ = str(REPO / "talonx_ops" / "operator_control" / "universe_view.py")   # same REPO_ROOT derivation
    exec(compile(r.stdout, "uv_before", "exec"), mod.__dict__)
    return mod


def _logs(root: Path, specs: dict[str, list[str]]) -> None:
    for name, lines in specs.items():
        d = root / "results" / name / "logs"
        d.mkdir(parents=True)
        (d / "v2_companion.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


SCOPE = "V2 execution scope ENFORCED -- {n} allowed issuers: {s}"
LOG_CASES = {
    "none": {},
    "single": {"prospective_20260928": ["boot", SCOPE.format(n=2, s="vtwo, POS"), "tick"]},
    "last_line_wins_newest_log_wins": {
        "prospective_20260927": [SCOPE.format(n=1, s="OLD")],
        "prospective_20260929": [SCOPE.format(n=1, s="FIRST"), SCOPE.format(n=3, s="VTWO,CRA , prom")]},
    "newest_log_empty_falls_back": {
        "prospective_20260928": [SCOPE.format(n=1, s="VTWO")],
        "prospective_20260930": ["started", "no scope line yet"]},
}


@pytest.mark.parametrize("case", sorted(LOG_CASES))
def test_v2_scope_parity_with_the_research_lane_rule(tmp_path, monkeypatch, case):
    _logs(tmp_path, LOG_CASES[case])
    from talonx_premarket import __main__ as M
    monkeypatch.setattr(M, "REPO_ROOT", tmp_path)
    assert UV.v2_scope(tmp_path) == set(M._v2_scope(None))


def _outputs(mod, root: Path, store) -> dict:
    from talonx_opportunity.sentinel_component import LiveDTUDeps
    deps = LiveDTUDeps(root, READERS)
    mk = lambda: mod.LiveUniverse(root, WID, store=store, deps=deps, now=NOW)     # noqa: E731  v2_scope=None: default path
    out = {"summary": mod.summary_text(mod.UniverseView(root, WID), HEAD_TXT)}
    for pop in mod.POP_TITLE:
        v = mk()
        out[f"pop:{pop}"] = mod.population_text(v, pop, HEAD_TXT)
        out[f"csv:{pop}"] = v.csv(v.population(pop)).decode()
    for sym in ("VTWO", "POS", "PROM", "ELIG", "AUTO", "ETFX", "ZZZZ"):
        out[f"status:{sym}"] = mod.live_status_text(mk(), sym, HEAD_TXT, "DRY_RUN")
    return out


@pytest.mark.parametrize("case", ["single", "last_line_wins_newest_log_wins", "none"])
def test_sentinel_universe_output_identical_before_and_after(tmp_path, monkeypatch, case):
    monkeypatch.delenv("OPERATOR_UNIVERSE_MUTATION_MODE", raising=False)
    fake_repo = tmp_path / "repo"
    _logs(fake_repo, LOG_CASES[case])
    root = _market(tmp_path / "opp")
    from talonx_ops.operator_control.store import OperatorStore
    store = OperatorStore(tmp_path / "operator_control.db")
    old = _old_module()
    from talonx_premarket import __main__ as M
    monkeypatch.setattr(M, "REPO_ROOT", fake_repo)        # BEFORE: research-lane scope reader
    monkeypatch.setattr(UV, "REPO_ROOT", fake_repo)       # AFTER: the boundary-safe reader
    before, after = _outputs(old, root, store), _outputs(UV, root, store)
    assert before.keys() == after.keys()
    diff = [k for k in before if before[k] != after[k]]
    assert diff == [], f"Sentinel /universe output changed for {diff}"
    if case == "single":                                   # the scope really flows into the output
        assert "YES" in [ln.split(",")[UV.CSV_FIELDS.index("V2_PROTECTED")] for ln in
                         after["csv:active"].splitlines()[1:] if ln.startswith("VTWO,")]


def test_universe_view_imports_no_research_lane_module():
    tree = ast.parse((REPO / "talonx_ops" / "operator_control" / "universe_view.py").read_text(encoding="utf-8"))
    mods = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods.append(n.module or "")
    assert not [m for m in mods if m.startswith(("talonx_premarket", "talonx_opportunity", "talonx_paperperf",
                                                 "talonx_shadow", "talonx_research"))], mods
