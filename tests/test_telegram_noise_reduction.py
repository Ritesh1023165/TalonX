"""Telegram noise reduction (2026-09-28): LAB_DELIVERY_POLICY_V1 routing (IMMEDIATE / DIGEST) after the UNCHANGED
LAB_NOTIFY_POLICY_V1 decision, the periodic Lab digest, compact Lab/Signal formats, and component hash coverage.
No network: the outbox drain is a fake; nothing is ever sent."""
from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import lab_delivery as LD
from talonx_opportunity import promotion as P
from talonx_opportunity import runtime as RT
from talonx_opportunity.notifier import NOTIFY_POLICY_OVERRIDES, Notifier, lab_delivery_from_env, outbox_path
from talonx_opportunity.store import OpportunityStore

UTC = timezone.utc
WID = "2026-09-24"                       # Thursday session: open 13:30Z, close 20:00Z
EXT = NOTIFY_POLICY_OVERRIDES["LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"]
REPO = Path(__file__).resolve().parents[1]


def T(h, m=0):
    return datetime(2026, 9, 24, h, m, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def seed(root, specs):
    """specs: (symbol, event_type, classification, at, gap, family). One candidate per (symbol, family)."""
    s = OpportunityStore(root)
    for i, sp in enumerate(specs):
        sym, typ, cls, at, gap = sp[:5]
        fam = sp[5] if len(sp) > 5 else ("GAP_UP" if gap >= 0 else "GAP_DOWN")
        cid = f"{WID}:{sym}:{fam}"
        state = {"BULLISH": "BULLISH_SETUP", "BEARISH": "BEARISH_SETUP"}.get(cls, cls)
        if s.candidate(cid) is None:
            s.upsert_candidate({"candidate_id": cid, "window_id": WID, "symbol": sym, "family": fam, "state": state,
                                "classification": cls, "first_seen_utc": at.isoformat(), "first_seen_phase": "REGULAR",
                                "in_v2_scope": 0})
        else:
            s.upsert_candidate({"candidate_id": cid, "state": state, "classification": cls})
        s.add_event({"event_id": f"{cid}:{typ}:{at.isoformat()}:{i}", "candidate_id": cid, "window_id": WID,
                     "symbol": sym, "at_utc": at.isoformat(), "data_as_of_utc": (at - timedelta(minutes=16)).isoformat(),
                     "phase": "AFTER_HOURS" if at >= T(20) else "REGULAR" if at >= T(13, 30) else "PREMARKET",
                     "event_type": typ, "from_state": "WATCH" if typ == "UPGRADE" else None, "to_state": state,
                     "classification": cls, "score": 70.0 + i % 5, "gap_pct": gap, "last_price": 10.0,
                     "reason": "gap faded below 1.0%" if typ == "INVALIDATED" else "x",
                     "features_json": json.dumps({"gap_pct": gap, "pm_dollars": 28e6, "prev_close": 10.0, "last_price": 10.0,
                                                  "pm_volume": 1e6, "activity_adv_fraction": 0.1}),
                     "score_json": json.dumps({"total": 70.0 + i % 5}), "catalyst": "8-K catalyst",
                     "provenance_json": "{}"})
    s.commit()
    s.close()


def promote(root, sym, at, window=WID, fam="GAP_UP"):
    """A PROMOTED_SIGNAL row in promotion.db (what the promotion component would have written)."""
    c = sqlite3.connect(P.promotion_db(root))
    c.executescript(P.SCHEMA)
    c.execute("INSERT INTO promotions (promotion_id, candidate_id, symbol, state, decision_utc, window_id) "
              "VALUES (?,?,?,?,?,?)", (f"OPPORTUNITY_ENGINE:{WID}:{sym}:{fam}", f"{WID}:{sym}:{fam}", sym,
                                       "PROMOTED_SIGNAL", at.isoformat(), window))
    c.commit()
    c.close()


def notifier(root, now, lab=LD.LAB_DELIVERY_POLICY_V1):
    return Notifier(root=root, policy=EXT, deliver=True, drain=lambda store: {"sent": 0}, lab_delivery=lab,
                    clock=Clock(now))


def dec(n):
    return {(r["symbol"], r["event_type"]): dict(r) for r in n.con.execute("SELECT * FROM decisions ORDER BY seq")}


def outbox(root):
    c = sqlite3.connect(outbox_path(root))
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute("SELECT * FROM ops_notification_outbox ORDER BY created_at_utc, event_id")]


def by_type(root, event_type):
    """The single outbox row of one type (created_at ties are common on Windows' 15.6 ms clock; never rely on order)."""
    rows = [o for o in outbox(root) if o["event_type"] == event_type]
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------------------------------------------- routing
def test_new_bullish_and_new_bearish_setups_are_immediate(tmp_path):
    seed(tmp_path, [("AAA", "NEW", "BULLISH", T(15), 6.0), ("BBB", "NEW", "BEARISH", T(15), -7.0)])
    n = notifier(tmp_path, T(15, 1))
    n.tick()
    d = dec(n)
    for k, why in ((("AAA", "NEW"), LD.R_NEW_SETUP), (("BBB", "NEW"), LD.R_NEW_SETUP)):
        assert (d[k]["decision"], d[k]["lab_route"], d[k]["info_class"], d[k]["route_reason"]) == \
               ("SELECTED", "IMMEDIATE", "HIGH", why)
    assert [o["event_type"] for o in outbox(tmp_path)] == ["OPPORTUNITY_RESEARCH_NEW"] * 2


def test_watch_to_setup_upgrade_is_immediate_and_new_watch_goes_to_the_digest(tmp_path):
    seed(tmp_path, [("WWW", "NEW", "WATCH", T(15), 4.0), ("WWW", "UPGRADE", "BULLISH", T(15, 10), 6.0)])
    n = notifier(tmp_path, T(15, 11))
    n.tick()
    d = dec(n)
    assert (d[("WWW", "NEW")]["lab_route"], d[("WWW", "NEW")]["route_reason"]) == ("DIGEST", LD.R_NEW_WATCH)
    assert d[("WWW", "NEW")]["decision"] == "SELECTED"                      # V1 decision unchanged (budget counted)
    assert (d[("WWW", "UPGRADE")]["lab_route"], d[("WWW", "UPGRADE")]["route_reason"]) == ("IMMEDIATE", LD.R_UPGRADE)
    ob = outbox(tmp_path)
    assert len(ob) == 1 and "⬆️ WATCH → BULLISH" in ob[0]["payload_text"]


def test_watch_material_update_is_suppressed_to_the_digest(tmp_path):
    seed(tmp_path, [("WWW", "NEW", "WATCH", T(15), 4.0), ("WWW", "MATERIAL_UPDATE", "WATCH", T(15, 40), 8.0)])
    n = notifier(tmp_path, T(15, 41))
    n.tick()
    d = dec(n)[("WWW", "MATERIAL_UPDATE")]
    assert (d["decision"], d["lab_route"], d["info_class"], d["route_reason"]) == \
           ("SELECTED", "DIGEST", "LOW", LD.R_WATCH_UPDATE)
    assert outbox(tmp_path) == []


def test_invalidation_of_a_never_sent_candidate_is_suppressed(tmp_path):
    seed(tmp_path, [("WWW", "NEW", "WATCH", T(15), 4.0), ("WWW", "INVALIDATED", "INVALIDATED", T(15, 20), 0.5)])
    n = notifier(tmp_path, T(15, 21))
    n.tick()
    d = dec(n)[("WWW", "INVALIDATED")]
    assert (d["decision"], d["lab_route"], d["route_reason"]) == ("SELECTED", "DIGEST", LD.R_INVALIDATED_UNSENT)
    assert outbox(tmp_path) == []


def test_invalidation_of_a_previously_sent_setup_is_immediate(tmp_path):
    seed(tmp_path, [("AAA", "NEW", "BULLISH", T(15), 6.0), ("AAA", "INVALIDATED", "INVALIDATED", T(16), 0.4)])
    n = notifier(tmp_path, T(16, 1))
    n.tick()
    d = dec(n)[("AAA", "INVALIDATED")]
    assert (d["lab_route"], d["info_class"], d["route_reason"]) == ("IMMEDIATE", "HIGH", LD.R_SETUP_INVALIDATED)
    txt = by_type(tmp_path, "OPPORTUNITY_RESEARCH_INVALIDATED")["payload_text"]
    assert "SETUP INVALIDATED" in txt and "AAA · BULLISH → INVALIDATED" in txt and "gap faded" in txt


def test_invalidation_of_an_open_signal_candidate_is_immediate_even_if_never_surfaced_in_lab(tmp_path):
    # never surfaced in Lab (V1: NOT_SURFACED_PARENT), but promoted to Signal at 15:05 -> horizon open until 20:00Z
    seed(tmp_path, [("SIG", "MATERIAL_UPDATE", "BULLISH", T(15), 5.0),
                    ("SIG", "INVALIDATED", "INVALIDATED", T(17), 0.3)])
    promote(tmp_path, "SIG", T(15, 5))
    n = notifier(tmp_path, T(17, 1))
    n.tick()
    d = dec(n)[("SIG", "INVALIDATED")]
    assert d["decision"] == "NOT_SURFACED_PARENT"                         # V1 decision unchanged
    assert (d["lab_route"], d["route_reason"]) == ("IMMEDIATE", LD.R_SIGNAL_INVALIDATED)
    ob = outbox(tmp_path)
    assert len(ob) == 1 and "Was a Signal paper opportunity (15:05Z)" in ob[0]["payload_text"]
    assert {o["destination"] for o in ob} == {"RESEARCH"}


def test_signal_candidate_invalidated_after_its_horizon_closed_is_not_immediate(tmp_path):
    seed(tmp_path, [("OLD", "INVALIDATED", "INVALIDATED", T(20, 30), 0.3)])     # after the 20:00Z close
    promote(tmp_path, "OLD", T(15))
    n = notifier(tmp_path, T(20, 31))
    n.tick()
    d = dec(n)[("OLD", "INVALIDATED")]
    assert d["decision"] == "NOT_SURFACED_PARENT" and d["lab_route"] is None and outbox(tmp_path) == []


def test_setup_update_immediate_only_when_the_move_extends_beyond_the_last_shown_gap(tmp_path):
    seed(tmp_path, [("AAA", "NEW", "BULLISH", T(15), 10.0),
                    ("AAA", "MATERIAL_UPDATE", "BULLISH", T(15, 30), 6.0),      # fade -> digest
                    ("AAA", "MATERIAL_UPDATE", "BULLISH", T(16), 9.5),          # re-test below 10 -> digest
                    ("AAA", "MATERIAL_UPDATE", "BULLISH", T(16, 30), 14.0),     # new extreme -> immediate
                    ("AAA", "MATERIAL_UPDATE", "BULLISH", T(17), 12.0)])        # below 14 -> digest
    n = notifier(tmp_path, T(17, 1))
    n.tick()
    rows = [r for r in n.con.execute("SELECT lab_route, route_reason FROM decisions WHERE event_type='MATERIAL_UPDATE' "
                                     "ORDER BY seq")]
    assert [tuple(r) for r in rows] == [("DIGEST", LD.R_SETUP_FADE), ("DIGEST", LD.R_SETUP_FADE),
                                        ("IMMEDIATE", LD.R_SETUP_EXTENDED), ("DIGEST", LD.R_SETUP_FADE)]
    txt = by_type(tmp_path, "OPPORTUNITY_RESEARCH_MATERIAL_UPDATE")["payload_text"]
    assert "SETUP UPDATE" in txt and "+14.00% (was +10.00%)" in txt


def test_v1_decisions_budget_and_surfaced_state_are_identical_with_and_without_the_delivery_policy(tmp_path):
    specs = ([(f"W{i:02d}", "NEW", "WATCH", T(14), 3.0) for i in range(18)]
             + [(f"S{i:02d}", "NEW", "BULLISH", T(15), 6.0) for i in range(5)]
             + [("S00", "MATERIAL_UPDATE", "BULLISH", T(15, 40), 2.0), ("W00", "INVALIDATED", "INVALIDATED", T(16), 0.2),
                ("W17", "MATERIAL_UPDATE", "WATCH", T(16), 9.0)])
    out = []
    for lab in (None, LD.LAB_DELIVERY_POLICY_V1):
        root = tmp_path / ("legacy" if lab is None else "v1")
        seed(root, specs)
        n = notifier(root, T(16, 1), lab=lab)
        n.tick()
        out.append(([tuple(r) for r in n.con.execute(
            "SELECT event_id, decision, reason, counted_new, budget_json FROM decisions ORDER BY seq")],
            sorted(r[0] for r in n.con.execute("SELECT candidate_id FROM surfaced"))))
    assert out[0] == out[1]


# ---------------------------------------------------------------------------------------------------- digest
SMALL = LD.LabDeliveryPolicy(digest_min_events=1)          # digest mechanics tests: no minimum batch


def _digest_fixture(root):
    seed(root, [("WWW", "NEW", "WATCH", T(15, 2), 4.0), ("VVV", "NEW", "WATCH", T(15, 3), 4.0),
                ("VVV", "INVALIDATED", "INVALIDATED", T(15, 20), 0.2), ("AAA", "NEW", "BULLISH", T(15, 5), 7.0)])


def test_digest_aggregates_suppressed_events_once_per_bucket(tmp_path):
    _digest_fixture(tmp_path)
    n = notifier(tmp_path, T(15, 25), lab=SMALL)
    n.tick()                                                                # bucket 15:00-15:30 still open
    assert n.con.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0
    n.clock.t = T(15, 31)
    n.tick()
    dg = [dict(r) for r in n.con.execute("SELECT * FROM digests")]
    assert len(dg) == 1 and dg[0]["n_events"] == 3 and json.loads(dg[0]["counts_json"]) == {
        LD.R_NEW_WATCH: 2, LD.R_INVALIDATED_UNSENT: 1}
    txt = dg[0]["payload_text"]
    assert txt.startswith("🧪 TALONX LAB — REGULAR DIGEST") and "3 low-information updates held back" in txt
    assert "• 2 new WATCH" in txt and "• 1 invalidations of never-sent candidates" in txt
    assert "Sent individually: 1 new bullish" in txt and "No open Signal opportunity affected" in txt
    assert "WWW" not in txt and "VVV" not in txt                            # no symbol flood
    assert n.con.execute("SELECT COUNT(*) FROM decisions WHERE digest_id=?", (dg[0]["digest_id"],)).fetchone()[0] == 3
    ob = [o for o in outbox(tmp_path) if o["event_type"] == "OPPORTUNITY_RESEARCH_DIGEST"]
    assert len(ob) == 1 and ob[0]["event_id"] == dg[0]["digest_id"] and ob[0]["destination"] == "RESEARCH"


def test_digest_is_never_resent_after_restart_and_events_are_never_replayed(tmp_path):
    _digest_fixture(tmp_path)
    n = notifier(tmp_path, T(15, 25), lab=SMALL)
    n.tick()                                                               # decided in the 15:00 bucket
    n.clock.t = T(15, 31)
    n.tick()                                                               # digest built + enqueued
    before = outbox(tmp_path)
    assert sum(o["event_type"] == "OPPORTUNITY_RESEARCH_DIGEST" for o in before) == 1
    for t in (T(15, 32), T(16, 5), T(16, 40)):                               # restarts, later buckets
        n2 = notifier(tmp_path, t, lab=SMALL)
        n2.tick()
        n2.digest()
    assert outbox(tmp_path) == before                                      # no new outbox rows, no replay
    assert n2.con.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 1


def test_crash_between_digest_record_and_enqueue_enqueues_exactly_once(tmp_path):
    _digest_fixture(tmp_path)
    n = notifier(tmp_path, T(15, 25), lab=SMALL)
    n.tick()
    n.deliver = False                                                      # simulate: recorded, crashed before enqueue
    n.clock.t = T(15, 31)
    n.digest()
    with n.con:
        n.con.execute("UPDATE digests SET routed='ENQUEUED_RESEARCH'")
    assert not [o for o in outbox(tmp_path) if o["event_type"] == "OPPORTUNITY_RESEARCH_DIGEST"]
    n2 = notifier(tmp_path, T(15, 45), lab=SMALL)
    n2.tick()
    n2.tick()
    ob = [o for o in outbox(tmp_path) if o["event_type"] == "OPPORTUNITY_RESEARCH_DIGEST"]
    assert len(ob) == 1
    # an event is linked to exactly one digest
    assert n2.con.execute("SELECT COUNT(DISTINCT digest_id) FROM decisions WHERE digest_id IS NOT NULL").fetchone()[0] == 1


def test_immediate_and_digest_never_both_carry_the_same_event(tmp_path):
    _digest_fixture(tmp_path)
    seed(tmp_path, [("AAA", "INVALIDATED", "INVALIDATED", T(15, 10), 0.3)])
    n = notifier(tmp_path, T(15, 25), lab=SMALL)
    n.tick()
    n.clock.t = T(15, 31)
    n.tick()
    assert n.con.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 1
    both = n.con.execute("SELECT COUNT(*) FROM decisions WHERE lab_route='IMMEDIATE' AND digest_id IS NOT NULL"
                         ).fetchone()[0]
    ids = [o["event_id"] for o in outbox(tmp_path)]
    assert both == 0 and len(ids) == len(set(ids))


def test_small_batches_are_held_until_the_minimum_or_the_maximum_hold(tmp_path):
    _digest_fixture(tmp_path)                                               # 3 held events (< 5)
    n = notifier(tmp_path, T(15, 25))
    n.tick()
    for t in (T(15, 31), T(16, 1), T(16, 31)):
        n.clock.t = t
        n.tick()
    assert n.con.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0          # held, still auditable
    assert n.con.execute("SELECT COUNT(*) FROM decisions WHERE lab_route='DIGEST' AND digest_id IS NULL"
                         ).fetchone()[0] == 3
    n.clock.t = T(17, 31)                                                   # oldest held >= 2 h -> flushed
    n.tick()
    assert [r[0] for r in n.con.execute("SELECT n_events FROM digests")] == [3]
    seed(tmp_path, [(f"X{i}", "NEW", "WATCH", T(17, 40), 4.0) for i in range(5)])
    n.clock.t = T(17, 45)
    n.tick()
    n.clock.t = T(18, 1)                                                    # 5 pending -> built at the next boundary
    n.tick()
    assert [r[0] for r in n.con.execute("SELECT n_events FROM digests ORDER BY period_end_utc")] == [3, 5]


def test_restart_does_not_replay_immediate_messages(tmp_path):
    seed(tmp_path, [("AAA", "NEW", "BULLISH", T(15), 6.0)])
    notifier(tmp_path, T(15, 1)).tick()
    notifier(tmp_path, T(15, 2)).tick()
    assert len(outbox(tmp_path)) == 1


def test_legacy_mode_is_the_exact_previous_path():
    assert lab_delivery_from_env({"TALONX_LAB_DELIVERY": "LEGACY"}) is None
    assert lab_delivery_from_env({}) is LD.LAB_DELIVERY_POLICY_V1
    with pytest.raises(SystemExit):
        lab_delivery_from_env({"TALONX_LAB_DELIVERY": "OFF"})


# ---------------------------------------------------------------------------------------------------- Signal
def test_signal_eligibility_policy_is_unchanged():
    assert P.PROMOTION_V1.fingerprint() == "4926c12e5eace04e"              # the fingerprint running on 2026-09-28
    p = P.PROMOTION_V1
    assert (p.rate_max, p.rate_window_s, p.queue_expiry_s, p.classes, p.processing_phases) == \
           (3, 300, 1800, ("BULLISH",), ("REGULAR",))


def test_signal_format_contract():
    txt = P.render({"symbol": "NVDA", "score": 78.66, "reference_price": 232.1234, "processing_phase": "REGULAR",
                    "data_as_of_utc": "2026-09-28T13:34:00+00:00", "horizons_json": '["INTRADAY", "SAME_DAY"]'})
    lines = txt.splitlines()
    assert lines[0] == "🚨 TALONX SIGNAL — PAPER" and "🟢 NVDA · BULLISH" in lines
    assert "⭐ Score 78.7" in lines and "💵 Ref $232.12" in lines and "🕒 REGULAR · data 13:34Z" in lines
    assert "⏱ INTRADAY / SAME_DAY" in lines and lines[-1].startswith("Paper opportunity only · no order placed")
    assert "BUY" not in txt.upper() and "SELL" not in txt.upper() and len(lines) <= 9
    assert "profitable" not in txt.replace("not proven profitable", "")


def test_lab_format_contract_and_no_cross_channel_source():
    ev = {"event_type": "UPGRADE", "classification": "BEARISH", "from_state": "WATCH", "symbol": "CRCL",
          "gap_pct": -4.07, "phase": "PREMARKET", "data_as_of_utc": "2026-09-28T09:29:00+00:00",
          "features_json": json.dumps({"gap_pct": -4.07, "pm_dollars": 28.0e6}), "score_json": '{"total": 60.6}',
          "catalyst": "8-K catalyst"}
    txt = LD.render_lab(ev, None, LD.R_UPGRADE)
    assert txt.splitlines()[:8] == ["🧪 TALONX LAB — SETUP UPGRADE", "", "🔴 CRCL · BEARISH", "⭐ 60.6", "📉 -4.07%",
                                    "💵 $28.0M session volume", "📰 8-K catalyst", "⬆️ WATCH → BEARISH"]
    assert "PREMARKET · data 09:29Z" in txt and txt.count("Research only") == 1
    assert "BUY" not in txt.upper() and "SELL" not in txt.upper()
    for f in ("notifier.py", "lab_delivery.py"):                           # Lab code never names the Signal destination
        assert "TRADE_EVENT" not in (REPO / "talonx_opportunity" / f).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- hash coverage
@pytest.mark.parametrize("component,module", [("notifier", "notifier.py"), ("promotion", "promotion.py")])
def test_every_engine_module_imported_by_the_component_is_in_its_version_hash(component, module):
    tree = ast.parse((REPO / "talonx_opportunity" / module).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "talonx_opportunity":
                mods |= {f"talonx_opportunity/{a.name}.py" for a in node.names}
            elif node.module.startswith(("talonx_opportunity.", "talonx_ops.notify", "talonx_ops.operator_control.gates")):
                mods.add(node.module.replace(".", "/") + ".py")
    mods = {m if (REPO / m).exists() else m.replace(".py", "/__init__.py") for m in mods}
    assert mods and mods <= set(RT.component_sources(component)), sorted(mods - set(RT.component_sources(component)))


def test_promotion_presentation_change_can_be_declared_ui_only_but_never_silently(tmp_path):
    st = RT.RuntimeStore(tmp_path)
    old = {"PROMOTION_POLICY": "4926c12e5eace04e", "mode": "PAPER_SIGNAL", "promotion_src": "aaa"}
    new = {**old, "promotion_src": "bbb"}
    st.record_start("promotion", version="v1", config_fps=old, commit="c1")
    assert st.record_start("promotion", version="v2", config_fps=new, commit="c2")["classification"] == \
        "STRATEGY_MATERIAL"                                                 # undeclared: conservative
    st.declare_change("promotion", "UI_ONLY", "Signal message format only", expected_version="v3")
    r = st.record_start("promotion", version="v3", config_fps={**new, "promotion_src": "ccc"}, commit="c3")
    assert (r["classification"], r["decided_by"]) == ("UI_ONLY", "RULE:CONFIG_KEY_MAPPED+DECLARED")
    st.declare_change("promotion", "UI_ONLY", "x", expected_version="v4")
    r = st.record_start("promotion", version="v4", config_fps={**new, "PROMOTION_POLICY": "zzz"}, commit="c4")
    assert r["classification"] == "STRATEGY_MATERIAL"                       # a policy change can never be downgraded
