"""Review-alert thinning (owner decision 2026-11-20): THIN OUT Signal-bot review alerts with a per-session cap.

The cap is a DELIVERY filter applied after an unchanged promotion decision: the first N released promotions of a trading
window are sent, the rest are recorded PROMOTED_SHADOW / THINNED_SESSION_CAP and never enqueued, sent or replayed.
OPPORTUNITY_PROMOTION_V1 (fingerprint 4926c12e5eace04e), its eligibility, ordering, rate limit and expiry are unchanged.
Fixtures and local renders only -- nothing is sent."""
from __future__ import annotations

import json
import sqlite3

from talonx_opportunity import promotion as P
from tests.test_review_alert_compact_template import Client, _setup, rich_seed

WIDE = P.PromotionPolicy(rate_max=1000)          # test-only: release everything in one tick (cadence is not under test)


def _control(root, thinning="default"):
    f = P.pause_path(root)
    d = json.loads(f.read_text(encoding="utf-8"))
    if thinning == "default":
        d["thinning"] = {"mode": "SESSION_CAP", "max_per_session": 10, "decision": "owner 2026-11-20 (test)"}
    elif thinning is None:
        d.pop("thinning", None)
    else:
        d["thinning"] = thinning
    f.write_text(json.dumps(d), encoding="utf-8")


def _run(tmp_path, monkeypatch, n=15, thinning="default", policy=WIDE):
    c = Client()
    _pr, tt = _setup(tmp_path, monkeypatch, c)
    _control(tmp_path, thinning)
    from tests.test_opportunity_promotion import Clock, _NoData
    for i in range(n):
        rich_seed(tmp_path, f"S{i:02d}", tt(15))
    pr = P.Promoter(root=tmp_path, clock=Clock(tt(15)), data=_NoData(), mode=P.PAPER_SIGNAL, policy=policy)
    pr.tick()
    return pr, c, tt


def _promotions(root):
    con = sqlite3.connect(root / "promotion.db")
    return con.execute("SELECT promotion_id, state, reason_code, score, queue_rank, signal_event_id "
                       "FROM promotions ORDER BY promotion_id").fetchall()


def _outbox(root):
    return sqlite3.connect(P.signal_outbox_path(root)).execute(
        "SELECT event_id, state FROM ops_notification_outbox ORDER BY event_id").fetchall()


def test_policy_fingerprint_unchanged():
    assert P.PROMOTION_V1.fingerprint() == "4926c12e5eace04e"


def test_session_cap_sends_first_ten_and_records_the_rest(tmp_path, monkeypatch):
    pr, c, _ = _run(tmp_path, monkeypatch, n=15)
    rows = _promotions(tmp_path)
    sent = [r for r in rows if r[1] == "PROMOTED_SIGNAL"]
    thinned = [r for r in rows if r[2] == P.THINNED_SESSION_CAP]
    assert len(sent) == 10 and len(thinned) == 5 and len(rows) == 15
    assert all(r[1] == "PROMOTED_SHADOW" and r[5] is None for r in thinned)    # record-only, no outbox id
    assert len(_outbox(tmp_path)) == 10 and len(c.sent) == 10                  # only the capped ten were sent
    assert pr.last["released"]["thinned"] == 5


def test_cap_keeps_release_order_highest_score_first(tmp_path, monkeypatch):
    c = Client()
    _pr, tt = _setup(tmp_path, monkeypatch, c)
    _control(tmp_path)
    from tests.test_opportunity_promotion import Clock, _NoData
    import sqlite3 as _sq
    for i in range(12):
        rich_seed(tmp_path, f"S{i:02d}", tt(15))
    s = _sq.connect(tmp_path / "opportunity.db")                           # distinct scores: S00 lowest ... S11 highest
    for i in range(12):
        s.execute("UPDATE candidate_events SET score=? WHERE symbol=?", (60.0 + i, f"S{i:02d}"))
    s.commit()
    s.close()
    P.Promoter(root=tmp_path, clock=Clock(tt(15)), data=_NoData(), mode=P.PAPER_SIGNAL, policy=WIDE).tick()
    sent = {r[0].split(":")[2] for r in _promotions(tmp_path) if r[1] == "PROMOTED_SIGNAL"}
    assert sent == {f"S{i:02d}" for i in range(2, 12)}                         # the 10 highest scores


def test_thinned_promotions_are_never_sent_later_or_after_restart(tmp_path, monkeypatch):
    pr, c, tt = _run(tmp_path, monkeypatch, n=15)
    from tests.test_opportunity_promotion import Clock, _NoData
    for m in (5, 10):                                                          # later ticks and a fresh process
        P.Promoter(root=tmp_path, clock=Clock(tt(15, m)), data=_NoData(), mode=P.PAPER_SIGNAL, policy=WIDE).tick()
    assert len(_outbox(tmp_path)) == 10 and len(c.sent) == 10


def test_cap_counts_survive_restart_for_new_promotions_in_the_same_window(tmp_path, monkeypatch):
    pr, c, tt = _run(tmp_path, monkeypatch, n=10)                              # cap already reached
    from tests.test_opportunity_promotion import Clock, _NoData
    rich_seed(tmp_path, "LATE", tt(15, 5))
    P.Promoter(root=tmp_path, clock=Clock(tt(15, 5)), data=_NoData(), mode=P.PAPER_SIGNAL, policy=WIDE).tick()
    late = [r for r in _promotions(tmp_path) if r[0].endswith(":LATE:GAP_UP")]
    assert late and late[0][1] == "PROMOTED_SHADOW" and late[0][2] == P.THINNED_SESSION_CAP
    assert len(c.sent) == 10


def test_cap_is_per_trading_window(tmp_path, monkeypatch):
    c = Client()
    _pr, tt = _setup(tmp_path, monkeypatch, c)
    _control(tmp_path)
    con = sqlite3.connect(tmp_path / "promotion.db")                          # 10 sent YESTERDAY must not count today
    cols = [d[0] for d in con.execute("SELECT * FROM promotions LIMIT 0").description]
    for i in range(10):
        row = {k: None for k in cols} | {"promotion_id": f"OPPORTUNITY_ENGINE:2026-09-23:Y{i}:GAP_UP",
                                          "candidate_id": f"2026-09-23:Y{i}:GAP_UP", "symbol": f"Y{i}",
                                          "state": "PROMOTED_SIGNAL", "window_id": "2026-09-23",
                                          "queued_utc": "2026-09-23T15:00:00+00:00",
                                          "decision_utc": "2026-09-23T15:00:00+00:00",
                                          "data_as_of_utc": "2026-09-23T14:44:00+00:00", "reference_price": 10.0}
        con.execute(f"INSERT INTO promotions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [row[k] for k in cols])
    con.commit()
    con.close()
    from tests.test_opportunity_promotion import Clock, _NoData
    for i in range(3):
        rich_seed(tmp_path, f"T{i}", tt(15))
    P.Promoter(root=tmp_path, clock=Clock(tt(15)), data=_NoData(), mode=P.PAPER_SIGNAL, policy=WIDE).tick()
    assert len(c.sent) == 3


def test_decisions_identical_with_and_without_thinning(tmp_path, monkeypatch):
    """Same seed: the promotion rows (ids, scores, queue ranks, set of released items) match; only the delivery state
    / reason of items past the cap differ."""
    out = {}
    for label, thin in (("off", None), ("on", "default")):
        root = tmp_path / label
        root.mkdir()
        _run(root, monkeypatch, n=15, thinning=thin)
        out[label] = _promotions(root)
        monkeypatch.undo()
    assert [(r[0], r[3], r[4]) for r in out["off"]] == [(r[0], r[3], r[4]) for r in out["on"]]
    assert {r[0] for r in out["off"] if r[1] == "PROMOTED_SIGNAL"} >= {r[0] for r in out["on"] if r[1] == "PROMOTED_SIGNAL"}
    assert sum(r[1] in ("PROMOTED_SIGNAL", "PROMOTED_SHADOW") for r in out["off"]) == \
        sum(r[1] in ("PROMOTED_SIGNAL", "PROMOTED_SHADOW") for r in out["on"]) == 15


def test_no_thinning_block_means_no_cap(tmp_path, monkeypatch):
    _pr, c, _ = _run(tmp_path, monkeypatch, n=12, thinning=None)
    assert len(c.sent) == 12


def test_malformed_thinning_block_fails_safe_to_the_default_cap(tmp_path, monkeypatch):
    for bad in ({"mode": "SESSION_CAP", "max_per_session": "ten"}, {"mode": "UNKNOWN"}, "not-an-object",
                {"mode": "SESSION_CAP", "max_per_session": -1}):
        root = tmp_path / f"bad{abs(hash(json.dumps(bad))) % 10_000}"
        root.mkdir()
        pr, c, _ = _run(root, monkeypatch, n=12, thinning=bad)
        assert len(c.sent) == P.DEFAULT_SESSION_CAP == 10
        assert pr.thinning["malformed"] is True
        monkeypatch.undo()


def test_status_and_config_fingerprint_report_the_cap(tmp_path, monkeypatch):
    pr, _c, _ = _run(tmp_path, monkeypatch, n=1)
    assert pr.last["signal_thinning"] == "SESSION_CAP:10"
    assert P.thinning_fp(pr.thinning) == "SESSION_CAP:10"


def test_cockpit_lane_reports_cap_and_thinned_count(tmp_path, monkeypatch):
    from talonx_ops import opportunity_read as R
    _pr, _c, tt = _run(tmp_path, monkeypatch, n=13)
    L = R.notification_lanes(tmp_path, now=tt(15, 30), repo=tmp_path, home=tmp_path)
    lane = next(x for x in L["lanes"] if x["lane"] == "PAPER_SIGNAL_PROMOTION")
    assert lane["promotions"]["thinned_session_cap"] == 3
    assert lane["thinning"]["configured"]["max_per_session"] == 10
    v2 = next(x for x in L["lanes"] if x["lane"] == "V2_ACTIONABLE")
    assert "PASSIVE" in v2["label"]
