"""Sentinel DTU visibility + operator override layer (DRY_RUN): populations, files, status, move semantics,
safety holds, idempotency, persistence, and proof that read-only / DRY_RUN commands never mutate DTU state."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from talonx_ops.operator_control import universe_view as UV
from talonx_ops.operator_control.commands import handle
from talonx_ops.operator_control.store import OperatorStore

WID = "2026-09-28"
NOW = "2026-09-28T15:00:00+00:00"
OWNER = "42"


def _market(root):
    root.mkdir()
    m = sqlite3.connect(root / "market.db")
    m.executescript("""
    CREATE TABLE dtu_snapshots (window_id TEXT, snapshot_version TEXT, reference_session TEXT, created_utc TEXT,
        core_size INTEGER, counts_json TEXT, policy_fp TEXT);
    CREATE TABLE dtu_snapshot (window_id TEXT, symbol TEXT, state TEXT, reason TEXT, core_rank INTEGER, price REAL,
        prev_close REAL, adv20 REAL, cik TEXT, snapshot_version TEXT);
    CREATE TABLE dtu_promotions (window_id TEXT, symbol TEXT, reason TEXT, started_utc TEXT, expires_utc TEXT,
        source_event_id TEXT, snapshot_version TEXT, state_version TEXT, detail_json TEXT);
    CREATE TABLE dtu_active (window_id TEXT, cycle_utc TEXT, n_active INTEGER, counts_json TEXT, symbols_json TEXT,
        fallback_reason TEXT, policy_fp TEXT);""")
    snap = [("CRA", "ACTIVE_CORE", "ADV20_RANK_1", 1), ("CRB", "ACTIVE_CORE", "ADV20_RANK_2", 2),
            ("VTWO", "ACTIVE_CORE", "ADV20_RANK_3", 3), ("PROM", "EVENT_ELIGIBLE", "ADV20_RANK_9_OUTSIDE_CORE", 9),
            ("ELIG", "EVENT_ELIGIBLE", "ADV20_RANK_10_OUTSIDE_CORE", 10),
            ("POS", "EVENT_ELIGIBLE", "ADV20_RANK_11_OUTSIDE_CORE", 11),
            ("AUTO", "AUTO_EXCLUDED", "BELOW_V1_PRICE_FLOOR", None),
            ("ETFX", "STRUCTURALLY_EXCLUDED", "STRUCTURAL:FUND_ETF_ETN", None)]
    snap += [("E" + chr(65 + i // 26) + chr(65 + i % 26), "EVENT_ELIGIBLE", "ADV20_RANK_X", 100 + i) for i in range(80)]
    for s, st, why, rk in snap:
        m.execute("INSERT INTO dtu_snapshot VALUES (?,?,?,?,?,10.0,10.0,1e7,NULL,'SNAPV')", (WID, s, st, why, rk))
    m.execute("INSERT INTO dtu_snapshots VALUES (?, 'SNAPV', '2026-09-25', ?, 3, ?, 'fp')",
              (WID, NOW, json.dumps({"ACTIVE_CORE": 3})))
    m.execute("INSERT INTO dtu_promotions VALUES (?, 'PROM', 'GAP_TRIGGER', '2026-09-28T14:00:00+00:00', NULL, NULL,"
              " 'SNAPV', 'v', '{}')", (WID,))
    active = ["CRA", "CRB", "VTWO", "PROM", "POS"]
    m.execute("INSERT INTO dtu_active VALUES (?, ?, 5, ?, ?, NULL, 'fp')",
              (WID, NOW, json.dumps({"ACTIVE_CORE": 2, "EVENT_PROMOTED": 2, "OPERATOR_ADDED": 1,
                                     "effective_active": 5}), json.dumps(active)))
    m.commit()
    m.close()
    return root


READERS = {"open_candidates": lambda w: [], "signals_today": lambda w: [], "positions": lambda w: ["POS"],
           "intents": lambda w: []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("OPERATOR_UNIVERSE_MUTATION_MODE", raising=False)
    from talonx_opportunity.sentinel_component import universe_factory
    root = _market(tmp_path / "opp")
    store = OperatorStore(tmp_path / "operator_control.db")
    fac = universe_factory(root, READERS, window_id=WID, v2_scope={"VTWO"}, now=NOW)
    monkeypatch.setattr(UV, "UniverseView", lambda *a, **k: UV.__dict__["_UVB"](root, WID))
    env.fac = fac
    return root, store, lambda: fac(store)


UV._UVB = UV.UniverseView


def cmd(text, store, mode="DRY_RUN", chat=OWNER):
    return handle(text, chat_id=chat, user="op", owner_chat_id=OWNER, store=store, mode=mode, universe=env.fac)


def digest(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_populations_and_semantics(env):
    root, store, view = env
    v = view()
    pop = {k: [x["SYMBOL"] for x in v.population(k)] for k in UV.POP_TITLE}
    assert pop["active"] == ["CRA", "CRB", "POS", "PROM", "VTWO"]            # the exact live dtu_active set
    assert "ELIG" in pop["eligible"] and not set(pop["eligible"]) & set(pop["active"])  # eligible = not active now
    assert pop["excluded"] == ["AUTO"] and pop["structural"] == ["ETFX"]          # auto vs structural kept separate
    assert pop["core"] == ["CRA", "CRB", "VTWO"] and "PROM" in pop["promoted"]
    assert pop["overrides"] == []


def test_status_reasoning_and_protections(env):
    root, store, view = env
    r = view().rows()
    assert r["PROM"]["SYSTEM_STATE"] == "EVENT_ELIGIBLE" and r["PROM"]["RESOLVED_STATE"] == "EVENT_PROMOTED"
    assert r["PROM"]["REASON"] == "GAP_TRIGGER" and r["PROM"]["FETCH_ELIGIBLE"] and r["PROM"]["DISCOVERY_ELIGIBLE"]
    assert r["POS"]["POSITION_PROTECTED"] and r["VTWO"]["V2_PROTECTED"]
    assert r["AUTO"]["EFFECTIVE_STATE"] == "EXCLUDED" and not r["AUTO"]["FETCH_ELIGIBLE"]
    t = cmd("/universe status PROM", store).text
    assert "System state: EVENT_ELIGIBLE" in t and "Effective state: ACTIVE (EVENT_PROMOTED)" in t
    assert "Reason: GAP_TRIGGER" in t and "Operator override: NONE" in t
    assert "Not in the TalonX base universe" in cmd("/universe status ZZZZ", store).text


def test_large_list_preview_does_not_flood_and_file_has_fields(env):
    root, store, view = env
    t = cmd("/universe eligible", store).text
    assert "… +" in t and "/universe eligible file" in t and len(t) < 1500
    r = cmd("/universe eligible file", store)
    lines = r.document.decode().splitlines()
    assert r.filename.endswith(".csv") and len(lines) == 1 + len(view().population("eligible"))
    for f in ("SYMBOL", "SYSTEM_STATE", "EFFECTIVE_STATE", "OPERATOR_OVERRIDE", "REASON", "CORE", "EVENT_PROMOTED",
              "EVENT_ELIGIBLE", "AUTO_EXCLUDED", "STRUCTURAL_EXCLUSION", "V2_PROTECTED", "POSITION_PROTECTED",
              "INTENT_PROTECTED", "FETCH_ELIGIBLE", "DISCOVERY_ELIGIBLE", "STATE_AS_OF", "SNAPSHOT_ID"):
        assert f in lines[0].split(",")


@pytest.mark.parametrize("target,override", [("active", "FORCE_ACTIVE"), ("eligible", "FORCE_ELIGIBLE"),
                                             ("excluded", "FORCE_EXCLUDED")])
def test_move_records_pending_only_in_dry_run(env, target, override):
    root, store, view = env
    sym = {"active": "AUTO", "eligible": "CRA", "excluded": "CRB"}[target]
    before = view().rows()[sym]
    m0 = digest(root / "market.db")
    r = cmd(f"/universe move {sym} {target}", store)
    assert "Status: PENDING" in r.text and "No provider/discovery change has been applied." in r.text
    assert r.mutated
    row = store.override_row(sym)
    assert row["override"] == override and row["status"] == "PENDING" and row["applied_at"] is None
    after = view().rows()[sym]
    assert after["SYSTEM_STATE"] == before["SYSTEM_STATE"]                     # system state preserved
    assert after["EFFECTIVE_STATE"] == before["EFFECTIVE_STATE"]               # DRY_RUN: effective unchanged
    assert after["OPERATOR_OVERRIDE"] == override                              # override shown separately
    assert digest(root / "market.db") == m0                                    # no DTU mutation


def test_auto_clears_and_idempotency(env):
    root, store, view = env
    assert "ALREADY_AUTO" in cmd("/universe move AUTO auto", store).text
    cmd("/universe move AUTO active", store)
    assert "ALREADY_REQUESTED" in cmd("/universe move AUTO active", store).text
    assert len([x for x in store.overrides() if x["symbol"] == "AUTO"]) == 1   # no duplicate override
    assert "Status: PENDING" in cmd("/universe move AUTO auto", store).text
    assert store.current_override("AUTO") == "NONE"
    assert "ALREADY_EFFECTIVE" in cmd("/universe move CRA active", store).text   # already active, no override
    assert "ALREADY_EFFECTIVE" in cmd("/universe move AUTO excluded", store).text  # already auto-excluded


def test_safety_protections_hold(env, monkeypatch):
    root, store, view = env
    r = cmd("/universe move POS excluded", store)
    assert "HELD_PROTECTED" in r.text and "OPEN_POSITION_PROTECTED" in r.text and not r.mutated
    assert store.current_override("POS") == "NONE"
    assert "V2_SCOPE_PROTECTED" in cmd("/universe move VTWO excluded", store).text
    assert "V2_SCOPE_PROTECTED" in cmd("/universe move VTWO eligible", store).text
    READERS["intents"] = lambda w: ["ELIG"]
    try:
        assert "PENDING_INTENT_PROTECTED" in cmd("/universe move ELIG excluded", store).text
    finally:
        READERS["intents"] = lambda w: []
    held = [x for x in store.override_requests() if x["status"] == "HELD_PROTECTED"]
    assert len(held) == 4 and all(x["previous_system_state"] for x in held)


def test_request_audit_fields(env):
    root, store, view = env
    cmd("/universe move AUTO active because-test", store)
    q = store.override_requests("AUTO")[-1]
    for k in ("request_id", "symbol", "previous_system_state", "previous_effective_state", "requested_override",
              "operator", "requested_at", "mode", "status", "reason", "snapshot_id", "state_as_of"):
        assert k in q
    assert q["previous_system_state"] == "AUTO_EXCLUDED" and q["snapshot_id"] == "SNAPV" and q["mode"] == "DRY_RUN"


def test_overrides_persist_across_restart(env, tmp_path):
    root, store, view = env
    cmd("/universe move AUTO active", store)
    store.con.close()
    again = OperatorStore(tmp_path / "operator_control.db")                  # Sentinel restart = new store object
    assert again.current_override("AUTO") == "FORCE_ACTIVE"
    assert "ALREADY_REQUESTED" in cmd("/universe move AUTO active", again).text


def test_read_only_commands_never_mutate(env, tmp_path):
    root, store, view = env
    store.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    m0, o0 = digest(root / "market.db"), digest(tmp_path / "operator_control.db")
    for c in ("/universe summary", "/universe active", "/universe eligible", "/universe excluded",
              "/universe structural", "/universe core", "/universe promoted", "/universe overrides",
              "/universe status CRA", "/universe active file", "/universe excluded file", "/universe list"):
        r = cmd(c, store)
        assert not r.mutated
    store.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert digest(root / "market.db") == m0 and digest(tmp_path / "operator_control.db") == o0


def test_list_redirects_instead_of_zero_active(env):
    root, store, view = env
    t = cmd("/universe list", store).text
    assert "This is NOT the full DTU universe." in t and "OPERATOR UNIVERSE (0 active)" not in t


def test_dry_run_gates_stay_identity(env):
    root, store, view = env
    cmd("/universe move CRB excluded", store)
    cmd("/universe move AUTO active", store)
    from talonx_ops.operator_control import gates
    base = ["CRA", "CRB", "PROM"]
    assert gates.effective_symbols(base, store=store) == base                  # DRY_RUN: exact identity
    assert gates.effective_members({"CRB": {}}, store=store) == {"CRB": {}}
    # the ACTIVE-mode contract already consumes FORCE_ACTIVE / FORCE_EXCLUDED via the legacy intent tables
    assert store.added() == {"AUTO"} and store.excluded() == {"CRB"}


def test_unauthorised_move_is_rejected(env):
    root, store, view = env
    r = cmd("/universe move AUTO active", store, chat="999")
    assert "Not authorised" in r.text and store.current_override("AUTO") == "NONE"


def test_help_distinguishes_read_only_and_mutating(env):
    root, store, view = env
    t = cmd("/help", store).text
    assert "DTU Visibility (read-only, LIVE)" in t and "Operator Overrides" in t and "Mutation mode: DRY_RUN" in t
