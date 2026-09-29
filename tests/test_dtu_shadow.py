"""DTU shadow (2026-09-29): measurement-only isolation, the sweep's gap/stale rule, latency classification, and the
two protection modes. No network, no production store."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_shadow import dtu as D
from talonx_shadow import dtu_eval as E

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


def test_shadow_code_never_writes_production_or_sends_anything():
    for f in ("dtu.py", "dtu_eval.py"):
        src = (REPO / "talonx_shadow" / f).read_text(encoding="utf-8")
        tree = ast.parse(src)
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(("talonx_ops.notify", "talonx_dispatch", "telegram")) for m in mods)
        assert "sendMessage" not in src and "OPERATOR_UNIVERSE_MUTATION_MODE" not in src
    # every production store is opened read-only; the only read-write connect targets shadow.db
    src = (REPO / "talonx_shadow" / "dtu.py").read_text(encoding="utf-8")
    assert src.count("sqlite3.connect(") == 2 and "mode=ro" in src and "shadow_db()" in src
    assert "sqlite3.connect(" in (REPO / "talonx_shadow" / "dtu_eval.py").read_text(encoding="utf-8")
    assert "mode=ro" in (REPO / "talonx_shadow" / "dtu_eval.py").read_text(encoding="utf-8")
    for f in ("talonx_opportunity/runtime.py",):                    # not part of any production version hash
        assert "talonx_shadow" not in (REPO / f).read_text(encoding="utf-8")


def test_gap_uses_v1_reference_close_and_v1_stale_gate():
    pm = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    asof = datetime(2026, 9, 29, 14, 0, tzinfo=UTC)
    trade = lambda m, p: {"p": p, "t": (asof - timedelta(minutes=m)).isoformat()}  # noqa: E731
    assert round(D.gap_from_trade(trade(1, 10.3), 10.0, pm, asof), 6) == 3.0
    assert D.gap_from_trade(trade(46, 10.3), 10.0, pm, asof) is None                  # older than V1's 45-min gate
    assert D.gap_from_trade({"p": 11, "t": "2026-09-28T23:59:00Z"}, 10.0, pm, asof) is None   # previous window
    assert D.gap_from_trade(trade(1, 10.3), None, pm, asof) is None                   # no V1 reference close
    assert D.gap_from_trade({}, 10.0, pm, asof) is None


class _W:
    """Minimal stand-in for dtu_eval.Window."""
    def __init__(self):
        self.snap = {"CORE": {"is_operator_forced_active": 0, "is_v2_forced_active": 0, "core_rank": 5,
                              "v1_floor_eligible": 1},
                     "V2X": {"is_operator_forced_active": 0, "is_v2_forced_active": 1, "core_rank": 3000,
                             "v1_floor_eligible": 1},
                     "GAP": {"is_operator_forced_active": 0, "is_v2_forced_active": 0, "core_rank": 2500,
                             "v1_floor_eligible": 1},
                     "LOW": {"is_operator_forced_active": 0, "is_v2_forced_active": 0, "core_rank": None,
                             "v1_floor_eligible": 0},
                     "OLD": {"is_operator_forced_active": 0, "is_v2_forced_active": 0, "core_rank": 2600,
                             "v1_floor_eligible": 1}}
        self.prom = {"GAP": {"GAP_TRIGGER": "2026-09-29T14:07:00+00:00"},
                     "LOW": {"GAP_TRIGGER": "2026-09-29T14:00:00+00:00"},
                     "OLD": {"OPEN_CANDIDATE_PROTECTION": "2026-09-29T13:00:00+00:00"}}
        self.scan_times = [f"2026-09-29T14:{m:02d}:00+00:00" for m in range(0, 60, 5)]
        self.events = [{"event_type": "NEW", "symbol": "OLD", "at_utc": "2026-09-29T12:00:00+00:00", "seq": 1,
                        "candidate_id": "c-old"}]
        self.spans = {"c-old": ["OLD", "2026-09-29T12:00:00+00:00", None]}


def test_latency_classes_against_the_production_scan_grid():
    pol = E.Policy(_W(), 1200, "PROD")
    assert pol.status("CORE", "2026-09-29T14:05:00+00:00")[:2] == (E.SAME, "CORE")
    assert pol.status("V2X", "2026-09-29T14:05:00+00:00")[:2] == (E.SAME, "V2_FORCED")
    assert pol.status("GAP", "2026-09-29T14:10:00+00:00")[0] == E.SAME          # promoted 14:07 <= 14:10
    assert pol.status("GAP", "2026-09-29T14:05:00+00:00")[0] == E.ONE           # promoted before the 14:10 scan
    assert pol.status("GAP", "2026-09-29T14:00:00+00:00")[0] == E.TWO           # needs two scans
    assert pol.status("LOW", "2026-09-29T14:30:00+00:00")[0] == E.MISSED        # below V1 floors: never promotable


def test_protection_prod_vs_policy_is_not_circular():
    W = _W()
    prod = E.Policy(W, 1200, "PROD")
    assert prod.status("OLD", "2026-09-29T14:00:00+00:00")[:2] == (E.SAME, "OPEN_CANDIDATE_PROTECTION")
    # POLICY: OLD's identity was created at 12:00 while OLD was neither core, forced nor promoted -> not captured,
    # so it cannot protect later events of OLD
    pol = E.Policy(W, 1200, "POLICY")
    assert pol.status("OLD", "2026-09-29T14:00:00+00:00")[0] == E.MISSED
    # if OLD had been core when its identity was created, the identity protects it after it leaves the core
    W.snap["OLD"]["core_rank"] = 10
    pol2 = E.Policy(W, 1200, "POLICY")
    W.snap["OLD"]["core_rank"] = 2600
    assert pol2.status("OLD", "2026-09-29T14:00:00+00:00")[:2] == (E.SAME, "OPEN_CANDIDATE_PROTECTION")


def test_core_size_counterfactual_is_just_the_rank_cut():
    W = _W()
    assert E.Policy(W, 1200, "PROD").base("GAP") is None and E.Policy(W, 3000, "PROD").base("GAP") == "CORE"
