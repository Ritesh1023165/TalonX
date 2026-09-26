"""Next-version P0 package 1, change B (2026-09-26): AFTER_HOURS (and every later-phase) reserve is consumed by the
event's causal DATA_PHASE = ``phase_at(data_as_of - 1 min)``, never the wall-clock processing phase.

Fixtures reproduce the 2026-09-25 failure shape: VEON/CERT/DRVN (REGULAR data as of 19:44Z, processed 20:01Z) and
HP (true AFTER_HOURS data as of 20:03Z).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from talonx_opportunity.notifier import (NOTIFY_POLICY_OVERRIDES, Notifier, data_phase, reserve_for,
                                         selected_policy)
from talonx_opportunity.store import OpportunityStore

UTC = timezone.utc
WID = "2026-09-24"                       # Thursday XNYS session: open 13:30Z, close 20:00Z (EDT)
EXT = NOTIFY_POLICY_OVERRIDES["LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"]      # 75 total / WATCH 15 / AH keeps 3


def T(h, m=0):
    return datetime(2026, 9, 24, h, m, tzinfo=UTC).isoformat()


# ======================================================================================== AH reserve (data phase)
def _seed(root, specs):
    """specs: (symbol, classification, event_type, processed_at, data_as_of or None). Candidates are GAP_UP."""
    s = OpportunityStore(root)
    for i, (sym, cls, typ, at, asof) in enumerate(specs):
        cid = f"{WID}:{sym}:GAP_UP"
        if s.candidate(cid) is None:
            s.upsert_candidate({"candidate_id": cid, "window_id": WID, "symbol": sym, "family": "GAP_UP",
                                "state": cls, "classification": cls, "first_seen_utc": at,
                                "first_seen_phase": "REGULAR", "in_v2_scope": 0})
        ph = "AFTER_HOURS" if at >= T(20) else "REGULAR" if at >= T(13, 30) else "PREMARKET"
        s.add_event({"event_id": f"{cid}:{typ}:{at}:{i}", "candidate_id": cid, "window_id": WID, "symbol": sym,
                     "at_utc": at, "data_as_of_utc": asof, "phase": ph, "event_type": typ, "classification": cls,
                     "score": 70.0, "features_json": "{}", "score_json": "{}", "provenance_json": "{}"})
    s.commit()
    s.close()


def _fill_to(root, n_setups):
    """15 WATCH + n_setups REGULAR-data BULLISH surfacings processed in REGULAR."""
    _seed(root, [(f"W{i:02d}", "WATCH", "NEW", T(14), T(13, 44)) for i in range(15)]
          + [(f"R{i:02d}", "BULLISH", "NEW", T(15), T(14, 44)) for i in range(n_setups)])


def _dec(n):
    return {r["symbol"]: dict(r) for r in n.con.execute("SELECT * FROM decisions")}


def test_data_phase_uses_causal_data_time_in_the_events_window():
    ev = {"window_id": WID, "phase": "AFTER_HOURS"}
    assert data_phase({**ev, "data_as_of_utc": T(19, 44)}) == "REGULAR"
    assert data_phase({**ev, "data_as_of_utc": T(20, 0)}) == "REGULAR"          # last bar used = 19:59 RTH minute
    assert data_phase({**ev, "data_as_of_utc": T(20, 3)}) == "AFTER_HOURS"
    assert data_phase({**ev, "data_as_of_utc": T(13, 20), "phase": "REGULAR"}) == "PREMARKET"
    assert data_phase({**ev, "data_as_of_utc": None}) is None
    assert data_phase({**ev, "data_as_of_utc": "garbage"}) is None
    assert data_phase({**ev, "window_id": "2026-09-26", "data_as_of_utc": T(20, 3)}) is None   # not a session


def test_regular_data_before_the_close_is_handled_as_before(tmp_path):
    _fill_to(tmp_path, 57)                                        # 72/75 used
    _seed(tmp_path, [("PRE", "BULLISH", "NEW", T(19, 50), T(19, 34))])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)["PRE"]
    assert d["decision"] == "BUDGET_RESERVED_LATER_PHASE" and d["data_phase"] == "REGULAR"
    assert d["reason"] == "72/75 used; 3 kept for phases after REGULAR"      # identical text when phases agree


def test_the_2026_09_25_failure_shape_regular_data_after_close_cannot_take_the_ah_reserve(tmp_path):
    _fill_to(tmp_path, 57)                                        # 72/75 used, 3 left = the AFTER_HOURS reserve
    _seed(tmp_path, [(s, "BULLISH", "UPGRADE", T(20, 1), T(19, 44)) for s in ("VEON", "CERT", "DRVN")]
          + [("HP", "BEARISH", "UPGRADE", T(20, 20), T(20, 3))])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)
    for s in ("VEON", "CERT", "DRVN"):
        assert d[s]["decision"] == "BUDGET_RESERVED_LATER_PHASE" and d[s]["counted_new"] == 0
        assert d[s]["phase"] == "AFTER_HOURS" and d[s]["data_phase"] == "REGULAR"
        assert "REGULAR data (processed in AFTER_HOURS)" in d[s]["reason"]
    assert d["HP"]["decision"] == "SELECTED" and d["HP"]["counted_new"] == 1 and d["HP"]["data_phase"] == "AFTER_HOURS"
    st = n.reserve_status()
    assert (st["AH_RESERVED_TOTAL"], st["AH_RESERVED_USED_BY_TRUE_AH"], st["AH_RESERVED_REMAINING"]) == (3, 1, 2)
    assert st["REGULAR_DATA_AFTER_CLOSE"] == {"BUDGET_RESERVED_LATER_PHASE": 3}
    assert st["REGULAR_DATA_AFTER_CLOSE_COUNTED_NEW"] == 0 and st["TRUE_AH_SENT"] == 1


def test_three_true_ah_setups_use_exactly_the_three_slots_and_the_fourth_is_held(tmp_path):
    _fill_to(tmp_path, 57)
    _seed(tmp_path, [(f"A{i}", "BEARISH", "NEW", T(20, 20 + i), T(20, 3 + i)) for i in range(4)])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)
    assert [d[f"A{i}"]["decision"] for i in range(4)] == ["SELECTED"] * 3 + ["BUDGET_EXHAUSTED_TOTAL"]
    st = n.reserve_status()
    assert (st["AH_RESERVED_USED_BY_TRUE_AH"], st["AH_RESERVED_REMAINING"], st["TRUE_AH_SENT"], st["TRUE_AH_HELD"]) \
        == (3, 0, 3, 1)


def test_first_true_ah_setup_gets_reserved_capacity_even_after_delayed_regular_events(tmp_path):
    _fill_to(tmp_path, 57)
    n = Notifier(root=tmp_path, policy=EXT)
    _seed(tmp_path, [(s, "BULLISH", "UPGRADE", T(20, 1), T(19, 44)) for s in ("VEON", "CERT", "DRVN")]
          + [(s, "BEARISH", "NEW", T(20, 16), T(19, 58)) for s in ("WOR", "FLGT")])      # still REGULAR data at 20:16
    n.tick()
    _seed(tmp_path, [("HP", "BEARISH", "UPGRADE", T(20, 20), T(20, 3))])
    n.tick()
    d = _dec(n)
    assert all(d[s]["decision"] == "BUDGET_RESERVED_LATER_PHASE" for s in ("VEON", "CERT", "DRVN", "WOR", "FLGT"))
    assert d["HP"]["decision"] == "SELECTED" and n._used(WID) == (73, 15)


def test_update_to_a_never_sent_candidate_does_not_consume_the_reserve(tmp_path):
    _fill_to(tmp_path, 57)
    _seed(tmp_path, [("CXW", "BEARISH", "MATERIAL_UPDATE", T(20, 20), T(20, 3)),
                     ("GPOR", "BEARISH", "INVALIDATED", T(20, 20), T(20, 3))])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)
    assert d["CXW"]["decision"] == d["GPOR"]["decision"] == "NOT_SURFACED_PARENT"
    assert n._used(WID) == (72, 15) and n.reserve_status()["AH_RESERVED_REMAINING"] == 3


def test_missing_data_phase_fails_closed(tmp_path):
    _fill_to(tmp_path, 57)
    _seed(tmp_path, [("NOD", "BULLISH", "NEW", T(20, 20), None)])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)["NOD"]
    assert d["decision"] == "BUDGET_RESERVED_LATER_PHASE" and d["counted_new"] == 0 and d["data_phase"] is None
    assert "UNKNOWN data phase, fail-closed" in d["reason"]
    assert reserve_for(EXT, {"phase": "AFTER_HOURS", "window_id": WID, "data_as_of_utc": None}) == (10, "UNKNOWN")
    assert reserve_for(EXT, {"phase": "REGULAR", "window_id": WID, "data_as_of_utc": T(14, 44)}) == (3, "REGULAR")


def test_premarket_data_processed_after_the_open_cannot_take_regular_capacity(tmp_path):
    """Same keying at the PREMARKET->REGULAR transition (acceptance criterion 7)."""
    pr = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925"})
    _seed(tmp_path, [(f"W{i:02d}", "WATCH", "NEW", T(9), T(8, 44)) for i in range(15)]
          + [(f"B{i:02d}", "BULLISH", "NEW", T(9, 10), T(8, 54)) for i in range(15)]         # PREMARKET extra 5 used
          + [("LATEPM", "BULLISH", "NEW", T(13, 40), T(13, 24)),                          # PREMARKET data @13:40
             ("REG", "BULLISH", "NEW", T(13, 50), T(13, 34))])
    n = Notifier(root=tmp_path, policy=pr)
    n.tick()
    d = _dec(n)
    assert d["LATEPM"]["decision"] == "BUDGET_RESERVED_LATER_PHASE" and d["LATEPM"]["data_phase"] == "PREMARKET"
    assert d["REG"]["decision"] == "SELECTED"


def test_no_replay_after_the_policy_boundary_and_old_rows_are_not_reinterpreted(tmp_path):
    """Pre-boundary decisions (old schema, no data_phase column, processing-phase semantics) are never re-decided."""
    _fill_to(tmp_path, 57)
    _seed(tmp_path, [(s, "BULLISH", "UPGRADE", T(20, 1), T(19, 44)) for s in ("VEON", "CERT", "DRVN")])
    old = Notifier(root=tmp_path, policy=EXT)
    old.tick()
    with old.con:                                                  # emulate the pre-fix outcome + old schema
        old.con.execute("UPDATE decisions SET decision='SELECTED', counted_new=1, reason='new surfacing within budget' "
                        "WHERE symbol IN ('VEON','CERT','DRVN')")
    old.con.close()
    con = sqlite3.connect(tmp_path / "notification.db")
    rows = con.execute("SELECT * FROM decisions ORDER BY event_id").fetchall()
    cols = [r[1] for r in con.execute("PRAGMA table_info(decisions)") if r[1] != "data_phase"]
    con.execute("CREATE TABLE d2 AS SELECT " + ",".join(cols) + " FROM decisions")
    con.execute("DROP TABLE decisions")
    con.execute("ALTER TABLE d2 RENAME TO decisions")
    con.commit()
    con.close()
    n = Notifier(root=tmp_path, policy=EXT)                        # migration adds data_phase; nothing re-decided
    n.tick()
    after = n.con.execute("SELECT " + ",".join(cols) + " FROM decisions ORDER BY event_id").fetchall()
    assert [tuple(r) for r in after] == [tuple(r[:len(cols)]) for r in rows]
    assert n._used(WID) == (75, 15)                                # budget honours the historical sends
    _seed(tmp_path, [("HP", "BEARISH", "UPGRADE", T(20, 20), T(20, 3))])
    n.tick()
    assert _dec(n)["HP"]["decision"] == "BUDGET_EXHAUSTED_TOTAL"   # the lost slots are not given back (no replay)


def test_restart_preserves_reserve_accounting(tmp_path):
    _fill_to(tmp_path, 57)
    _seed(tmp_path, [("VEON", "BULLISH", "UPGRADE", T(20, 1), T(19, 44)), ("A0", "BEARISH", "NEW", T(20, 20), T(20, 3))])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    first = n.reserve_status()
    n.con.close()
    n2 = Notifier(root=tmp_path, policy=EXT)
    n2.tick()
    assert n2.reserve_status() == first
    _seed(tmp_path, [(f"A{i}", "BEARISH", "NEW", T(20, 25), T(20, 8)) for i in (1, 2, 3)])
    n2.tick()
    d = _dec(n2)
    assert [d[f"A{i}"]["decision"] for i in (1, 2, 3)] == ["SELECTED", "SELECTED", "BUDGET_EXHAUSTED_TOTAL"]


def test_regular_behaviour_unchanged_when_data_and_processing_phase_agree(tmp_path):
    """Pure REGULAR day (all data REGULAR, processed in REGULAR): identical decisions to the processing-phase rule."""
    _seed(tmp_path, [(f"W{i:02d}", "WATCH", "NEW", T(14), T(13, 44)) for i in range(20)]
          + [(f"R{i:02d}", "BULLISH", "NEW", T(15), T(14, 44)) for i in range(62)])
    n = Notifier(root=tmp_path, policy=EXT)
    n.tick()
    d = _dec(n)
    assert sum(r["decision"] == "BUDGET_EXHAUSTED_WATCH" for r in d.values()) == 5
    rg = [d[f"R{i:02d}"]["decision"] for i in range(62)]
    assert rg.count("SELECTED") == 57 and rg.count("BUDGET_RESERVED_LATER_PHASE") == 5   # 75-15-3 = 57
    assert all(r["data_phase"] == r["phase"] == "REGULAR" for r in d.values())


def test_notifier_config_fingerprint_records_the_reserve_basis():
    import inspect

    from talonx_opportunity import notifier
    assert notifier.RESERVE_PHASE_BASIS == "CAUSAL_DATA_PHASE_V1"
    assert '"reserve_phase_basis": RESERVE_PHASE_BASIS' in inspect.getsource(notifier.main)
    assert EXT.fingerprint() == selected_policy(
        {"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"}).fingerprint()   # caps unchanged
    assert (EXT.total_new_per_window, EXT.setup_reserved) == (75, 60)
