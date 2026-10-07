"""2026-10-07 owner decision: pause PAPER_SIGNAL promotion -> Signal-bot delivery (record-only), keep discovery, promotion
records, paper outcomes and VR position management; make the dashboard show every notification lane. No network."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import promotion as P
from talonx_ops import opportunity_read as R
from tests.test_opportunity_promotion import Clock, T, _NoData, promoter, rows, seed

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
PAUSE = {"paused": True, "effective_utc": "2026-10-07T11:30:00Z", "effective_local": "2026-10-07 12:30 BST",
         "decision": "owner 2026-10-07", "policy_id": "PROMOTION_SIGNAL_DELIVERY_PAUSE_V1"}


def pause(root, body=PAUSE):
    f = P.pause_path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


class Drains:
    def __init__(self):
        self.calls = 0

    def __call__(self, store):
        self.calls += 1
        return {"sent": 0}


def outbox(root):
    c = sqlite3.connect(P.signal_outbox_path(root))
    return {r[0]: (r[1], r[2]) for r in c.execute("SELECT dedup_key, state, last_error FROM ops_notification_outbox")}


def signal_promoter(root, now, drain, *, paused=False):
    if paused:
        pause(root)
    seed(root, [])
    return P.Promoter(root=root, clock=Clock(now), data=_NoData(), mode=P.PAPER_SIGNAL, drain=drain)


# ------------------------------------------------------------------------------------------------------- the pause
def test_paused_promotions_are_recorded_but_never_enqueued_or_drained(tmp_path):
    d = Drains()
    pr = signal_promoter(tmp_path, T(15), d, paused=True)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert rows(pr, "SELECT state, promotion_mode, reason_code, signal_event_id FROM promotions") == \
        [("PROMOTED_SHADOW", "SHADOW", "SIGNAL_DELIVERY_PAUSED", None)]
    assert d.calls == 0 and not P.signal_outbox_path(tmp_path).exists()
    assert pr.last["requested_mode"] == "PAPER_SIGNAL" and pr.last["signal_delivery"] == "PAUSED"
    assert pr.last["pause"]["policy_id"] == "PROMOTION_SIGNAL_DELIVERY_PAUSE_V1"


def test_paused_promotions_still_get_paper_outcomes(tmp_path):
    pr = signal_promoter(tmp_path, T(15), Drains(), paused=True)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    pid = rows(pr, "SELECT promotion_id FROM promotions")[0][0]
    # the outcome tracker selects PROMOTED_SHADOW and PROMOTED_SIGNAL alike (unchanged code path)
    src = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")
    assert "p.state IN ('PROMOTED_SHADOW','PROMOTED_SIGNAL')" in src[src.index("def _outcomes"):]
    assert pid


def test_malformed_pause_file_fails_safe_to_paused(tmp_path):
    pause(tmp_path, "{not json")
    d = Drains()
    pr = signal_promoter(tmp_path, T(15), d)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert pr.mode == P.SHADOW and pr.pause["decision"] == "UNREADABLE_CONTROL_FILE_FAIL_SAFE" and d.calls == 0


def test_paused_false_without_a_boundary_stays_paused_fail_safe(tmp_path):
    # 2026-10-07 (review restoration): a resumption must name its delivery boundary, otherwise it stays paused
    pause(tmp_path, {**PAUSE, "paused": False})
    d = Drains()
    pr = signal_promoter(tmp_path, T(15), d)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert pr.mode == P.SHADOW and pr.pause["decision"] == "RESUME_WITHOUT_VALID_BOUNDARY_FAIL_SAFE" and d.calls == 0


def test_absent_control_file_keeps_legacy_paper_signal_behaviour(tmp_path):
    d = Drains()
    pr = signal_promoter(tmp_path, T(15), d)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert pr.mode == P.PAPER_SIGNAL and pr.delivery_boundary is None and d.calls == 1
    assert list(outbox(tmp_path).values())[0][0] == "PENDING"


def test_shadow_env_is_not_changed_by_a_pause_file(tmp_path):
    pause(tmp_path)
    pr = promoter(tmp_path, T(15))
    assert pr.mode == P.SHADOW and pr.pause is None and pr.suppressed_at_start == 0


# ------------------------------------------------------------------------------------------- pending / in-flight
def _make_outbox_rows(root):
    """Three never-sent PAPER_OPPORTUNITY rows (PENDING), then mark one SENT and one AMBIGUOUS as a transport would."""
    pr = signal_promoter(root, T(15), lambda s: {"sent": 0})
    seed(root, [dict(sym=s, at=T(15), score=70 + i) for i, s in enumerate(("AAA", "BBB", "CCC"))])
    pr.tick()
    from talonx_ops.notify.outbox import NotifyStore
    ob = NotifyStore(str(P.signal_outbox_path(root)))
    ids = {r["dedup_key"].split(":")[2]: r["event_id"] for r in ob.all_outbox()}
    ob.update_outbox(ids["AAA"], state="SENT", attempts=1, transport_ref="m1", sent=True)
    ob.update_outbox(ids["BBB"], state="AMBIGUOUS", attempts=1, last_error="timeout after write")
    return ids


def test_pending_rows_are_suppressed_once_and_sent_or_ambiguous_rows_are_untouched(tmp_path):
    _make_outbox_rows(tmp_path)
    before = outbox(tmp_path)
    pr = signal_promoter(tmp_path, T(15, 1), Drains(), paused=True)
    after = outbox(tmp_path)
    key = lambda s: f"OPPORTUNITY_ENGINE:2026-09-24:{s}:GAP_UP"
    assert after[key("AAA")] == before[key("AAA")] == ("SENT", None)
    assert after[key("BBB")] == before[key("BBB")]                         # outcome unknown stays AMBIGUOUS
    st, why = after[key("CCC")]
    assert st == "EXPIRED" and why.startswith("SUPPRESSED_POLICY_PAUSE") and "was PENDING after 0" in why
    assert "transport" not in why.split(";")[0]                            # policy, not a transport failure
    assert pr.suppressed_at_start == 1
    # restart while paused: no duplicate suppression, no rewrite of the first record
    pr2 = signal_promoter(tmp_path, T(15, 2), Drains(), paused=True)
    assert pr2.suppressed_at_start == 0 and outbox(tmp_path) == after


def test_no_replay_on_restart_or_resumption(tmp_path):
    _make_outbox_rows(tmp_path)
    signal_promoter(tmp_path, T(15, 1), Drains(), paused=True)
    pr = signal_promoter(tmp_path, T(15, 6), Drains(), paused=True)        # restart, still paused
    seed(tmp_path, [dict(sym=f"Q{i}", at=T(15, 6), asof=T(14, 50), score=60 + i) for i in range(5)])
    pr.tick()                                                              # 3 released (record-only) + 2 queued
    assert rows(pr, "SELECT COUNT(*) FROM promotions WHERE state='QUEUED'") == [(2,)]
    # explicit resumption: paused=false + boundary + restart. Nothing suppressed or queued while paused is sent.
    pause(tmp_path, {**PAUSE, "paused": False, "delivery_mode": "RESEARCH_REVIEW",
                     "delivery_boundary_utc": T(15, 12).isoformat()})
    sent = []
    from talonx_ops.notify.outbox import NotifyStore

    def drain(store):
        sent.extend(r["dedup_key"] for r in store.outbox_due(now_iso="9999", destination="TRADE_EVENT"))
        return {}
    pr3 = P.Promoter(root=tmp_path, clock=Clock(T(15, 12)), data=_NoData(), mode=P.PAPER_SIGNAL, drain=drain)
    pr3.tick()
    assert sent == []
    assert rows(pr3, "SELECT COUNT(*) FROM promotions WHERE reason_code='MODE_SWITCH_NO_CARRYOVER'") == [(2,)]
    seed(tmp_path, [dict(sym="NEW1", at=T(15, 13), asof=T(14, 57))])
    pr3.clock.t = T(15, 13)
    pr3.tick()
    assert sent == ["OPPORTUNITY_ENGINE:2026-09-24:NEW1:GAP_UP"]            # only post-resumption promotions
    assert NotifyStore(str(P.signal_outbox_path(tmp_path))).counts_by_state().get("SENT") == 1


def test_config_fingerprint_records_the_pause_and_main_passes_it():
    body = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")
    body = body[body.index("def main("):]
    assert '"signal_delivery": "PAUSED" if pr.pause else (' in body and '"RESEARCH_REVIEW@"' in body


# ---------------------------------------------------------------------------------------------- scope (other lanes)
def test_pause_control_is_read_only_by_promotion_and_the_dashboard():
    hits = []
    for p in REPO.rglob("*.py"):
        if any(x in p.parts for x in (".venv", "results", ".git", "tests")):
            continue
        try:
            if "promotion_signal_delivery" in p.read_text(encoding="utf-8", errors="ignore"):
                hits.append(p.relative_to(REPO).as_posix())
        except OSError:
            pass
    assert sorted(hits) == ["talonx_opportunity/promotion.py", "talonx_ops/opportunity_read.py"]


def test_other_destinations_still_dispatch_while_paused(tmp_path, monkeypatch):
    pause(tmp_path)
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "lab-token")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "chat")
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_ops.notify.worker import drain

    class Client:
        def send(self, text, **kw):
            return {"ok": True, "ref": "1"}
    lab = NotifyStore(str(tmp_path / "opportunity_research_notifications.db"))
    lab.enqueue(event_id="L1", destination="RESEARCH", event_type="OPPORTUNITY_RESEARCH_NEW", producer="OE",
                dedup_key="L1", payload_text="x", provenance={})
    out = drain(lab, destination="RESEARCH", client=Client())
    assert out["sent"] == 1 and lab.counts_by_state().get("SENT") == 1


# --------------------------------------------------------------------------------------------------------- VR impact
def test_vr_takes_no_new_entries_from_paused_promotions_and_keeps_managing_open_trades(tmp_path):
    from tests.test_vr_live import FLAT, WID, Env, rows as vr_rows
    env = Env(tmp_path, [FLAT] * 25 + [(10, 12, 10, 11.9)])
    env.run(10)
    assert vr_rows(env)["VIRTUAL_REALTIME"]["state"] == "OPEN"
    p = sqlite3.connect(env.live / "promotion.db")                      # promotion recorded while paused
    p.execute("INSERT INTO promotions VALUES ('P2','C2','BBB','BULLISH',80,'2026-09-28T14:20:00+00:00',"
              "'2026-09-28T14:36:00+00:00','2026-09-28T14:36:05+00:00',10.0,NULL,?, 'PROMOTED_SHADOW')", (WID,))
    p.commit()
    p.close()
    env.run(20)
    r = vr_rows(env)
    assert r["VIRTUAL_REALTIME"]["state"] == "EXITED"                    # management / exit continues
    assert not any(k.endswith("P2") for k in r)                          # no entry from a paused promotion


def test_vr_actionable_never_gets_a_synthetic_send_time(tmp_path):
    from tests.test_vr_live import FLAT, Env, rows as vr_rows
    env = Env(tmp_path, [FLAT] * 400)
    o = sqlite3.connect(env.live / "promotion_signal_notifications.db")    # suppressed at the boundary, never sent
    o.execute("UPDATE ops_notification_outbox SET state='EXPIRED', sent_at_utc=NULL WHERE event_id='S1'")
    o.commit()
    o.close()
    env.run(2)
    a = vr_rows(env)["ACTIONABLE"]
    assert a["state"] == "PAPER_ENTRY_PENDING" and a["entry_market_time"] is None
    env.now = datetime(2026, 9, 28, 20, 10, tzinfo=UTC)                  # past the flatten
    env.run(1)
    a = vr_rows(env)["ACTIONABLE"]
    assert (a["state"], a["skip_reason"], a["entry_market_time"]) == ("SKIPPED", "NEVER_SENT_BEFORE_FLATTEN", None)


# ---------------------------------------------------------------------------------------------------------- dashboard
def _live_like(tmp_path, *, paused):
    root = tmp_path / "opp"
    root.mkdir()
    _make_outbox_rows(root)                                             # history before the boundary
    pr = signal_promoter(root, T(15, 6), Drains(), paused=paused)
    seed(root, [dict(sym="ZZZ", at=T(15, 6), asof=T(14, 50))])
    pr.tick()
    from talonx_opportunity.runtime import RuntimeStore
    rs = RuntimeStore(root)
    rs.con.execute("INSERT OR REPLACE INTO components (name, pid, state, heartbeat_utc, version, config_fps_json, "
                   "commit_sha, detail_json) VALUES ('promotion', 1, 'RUNNING', ?, 'v', ?, ?, ?)",
                   (datetime.now(UTC).isoformat(), json.dumps({"mode": "SHADOW" if paused else "PAPER_SIGNAL",
                                                              "signal_delivery": "PAUSED" if paused else "ACTIVE"}),
                    "0123456789ab", json.dumps(pr.last)))
    rs.con.commit()
    rs.con.close()
    pr.con.close()
    return root


def test_dashboard_lane_reconciles_with_the_stores(tmp_path):
    root = _live_like(tmp_path, paused=True)
    now = T(15, 30)
    L = R.notification_lanes(root, now=now, repo=tmp_path, home=tmp_path)
    lane = next(x for x in L["lanes"] if x["lane"] == "PAPER_SIGNAL_PROMOTION")
    from talonx_ops.notify.outbox import NotifyStore
    counts = NotifyStore(str(P.signal_outbox_path(root))).counts_by_state()
    n = lane["notifications"]
    assert {k: v for k, v in n["history"].items() if v} == counts            # rows, by state, exactly
    assert n["history"]["SENT"] == 1 and n["history"]["AMBIGUOUS"] == 1      # confirmed vs ambiguous kept apart
    assert n["suppressed_by_policy"] == 1 and n["send_attempts_total"] == 2  # attempts are not notifications
    c = sqlite3.connect(root / "promotion.db")
    assert lane["promotions"]["history"] == dict(c.execute("SELECT state, COUNT(*) FROM promotions GROUP BY 1"))
    assert lane["promotions"]["recorded_while_paused"] == 1
    assert lane["mode"].startswith("PAUSED") and lane["configured_pause"]["policy_id"] == PAUSE["policy_id"]
    assert lane["research_status"]["status"] == "NEGATIVE" and "Not a validated profitable" in \
        lane["research_status"]["statement"]
    assert L["period"]["start_utc"] == "2026-09-24T00:00:00+00:00" and "BST" in L["period"]["timezone"]
    assert {x["lane"] for x in L["lanes"]} == {"PAPER_SIGNAL_PROMOTION", "INTELLIGENCE_CARDS", "V2_ACTIONABLE",
                                               "OPERATIONS", "LAB_RESEARCH", "VR_PAPER"}


def test_dashboard_historical_sends_stay_visible_after_the_pause_and_period_is_separate(tmp_path):
    root = _live_like(tmp_path, paused=True)
    # outbox rows carry the wall-clock creation time: the next UTC day is a period with no sends
    L = R.notification_lanes(root, now=datetime.now(UTC) + timedelta(days=1), repo=tmp_path, home=tmp_path)
    n = next(x for x in L["lanes"] if x["lane"] == "PAPER_SIGNAL_PROMOTION")["notifications"]
    assert n["history"]["SENT"] == 1 and n["period"]["SENT"] == 0 and n["last_confirmed_send_utc"]


def test_dashboard_mode_follows_configuration(tmp_path):
    root = _live_like(tmp_path, paused=False)
    lane = lambda: next(x for x in R.notification_lanes(root, now=T(15, 30), repo=tmp_path, home=tmp_path)["lanes"]
                        if x["lane"] == "PAPER_SIGNAL_PROMOTION")
    assert lane()["mode"].startswith("ACTIVE")
    pause(root)                                                         # configured, not yet loaded by a restart
    assert lane()["mode"].startswith("PAUSE_CONFIGURED_NOT_YET_LOADED")
    (root / "runtime.db").unlink()
    assert lane()["mode"].startswith("UNKNOWN")


def test_opportunity_status_drops_the_false_untouched_statement(tmp_path):
    root = _live_like(tmp_path, paused=True)
    s = R.read_opportunity_status(root)
    assert "signal_sentinel" not in s["notification"] and "untouched" not in json.dumps(s["notification"])
    assert "PAPER_SIGNAL promotion" in s["notification"]["signal_bot_note"]
    assert s["notification"]["lanes"]["lanes"][0]["lane"] == "PAPER_SIGNAL_PROMOTION"


# ------------------------------------------------------------------------------------------------- version display
def _git(cwd, *a):
    import subprocess
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


RUNTIME_STUB = """
_P = "talonx_opportunity/"
_SHARED = [_P + "runtime.py"]
COMPONENT_SOURCES: dict[str, list[str]] = {
    "promotion": [_P + "promotion.py"],
    **{f"evaluator:{h}": [_P + "evaluators.py"] for h in ("INTRADAY", "SAME_DAY")},
}
"""


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "talonx_opportunity").mkdir(parents=True)
    (r / "talonx_ingest").mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "talonx_opportunity" / "runtime.py").write_text(RUNTIME_STUB)
    (r / "talonx_opportunity" / "promotion.py").write_text("x=1\n")
    (r / "talonx_opportunity" / "evaluators.py").write_text("e=1\n")
    (r / "talonx_ingest" / "i.py").write_text("y=1\n")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "c1")
    return r


def _loaded(repo, name):
    srcs = R._component_sources(repo)
    return {"commit_sha": _git(repo, "rev-parse", "HEAD")[:12] + "-dirty",
            "version": R._checkout_version(repo, srcs[0], srcs[1], name)}


def test_static_source_map_matches_runtime_and_hashes_agree():
    from talonx_opportunity import runtime as RT
    shared, sources = R._component_sources(REPO)
    assert shared == RT._SHARED and sources == RT.COMPONENT_SOURCES
    for n in ("promotion", "ingestion", "evaluator:INTRADAY", "sentinel"):
        assert R._checkout_version(REPO, shared, sources, n) == RT.component_version(n)


def test_loaded_version_differing_from_head_by_other_code_is_not_stale(repo):
    loaded = {"promotion": _loaded(repo, "promotion"), "evaluator:INTRADAY": _loaded(repo, "evaluator:INTRADAY"),
              "notifier": None}
    (repo / "talonx_ingest" / "i.py").write_text("y=2\n")                 # an Intelligence-only commit
    (repo / "talonx_opportunity" / "evaluators.py").write_text("e=2\n")   # ...and another component's code
    _git(repo, "commit", "-qam", "later commits")
    v = R.version_attribution(loaded, repo)
    p = v["components"]["promotion"]
    assert v["repo_head"] != p["loaded_commit"][:12]
    assert p["status"].startswith("CURRENT") and p["commit_vs_head"] == "OLDER_OR_OTHER_COMMIT"
    assert p["dirty_at_load"].startswith("YES")
    assert v["components"]["evaluator:INTRADAY"]["status"].startswith("SOURCES_CHANGED_SINCE_LOAD")
    assert v["components"]["notifier"]["status"].startswith("UNKNOWN")
    (repo / "talonx_opportunity" / "promotion.py").write_text("x=2\n")    # uncommitted edit to its own source
    v = R.version_attribution(loaded, repo)
    assert v["dirty_tracked_files_now"] == ["talonx_opportunity/promotion.py"]
    assert v["components"]["promotion"]["status"].startswith("SOURCES_CHANGED_SINCE_LOAD")


def test_unreadable_source_map_is_unknown_not_stale(repo):
    loaded = {"promotion": _loaded(repo, "promotion")}
    (repo / "talonx_opportunity" / "runtime.py").write_text("COMPONENT_SOURCES = build()\n")
    assert R.version_attribution(loaded, repo)["components"]["promotion"]["status"].startswith("UNKNOWN")
