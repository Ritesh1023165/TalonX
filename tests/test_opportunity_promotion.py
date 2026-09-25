"""OPPORTUNITY_PROMOTION_V1 -- Opportunity Engine setup -> PAPER opportunity (SHADOW default). No network, no send."""
from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import promotion as P
from talonx_opportunity.store import OpportunityStore

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


def T(h, m=0, s=0):
    return datetime(2026, 9, 24, h, m, s, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def seed(root, specs):
    """specs: dict(sym, cls, typ, phase, at, asof, score, price, state, reason)."""
    s = OpportunityStore(root)
    for i, x in enumerate(specs):
        fam = "GAP_DOWN" if x.get("cls") == "BEARISH" else "GAP_UP"
        cid = f"2026-09-24:{x['sym']}:{fam}"
        s.upsert_candidate({"candidate_id": cid, "window_id": "2026-09-24", "symbol": x["sym"], "family": fam,
                            "state": x.get("state", "BULLISH_SETUP"), "classification": x.get("cls", "BULLISH"),
                            "first_seen_utc": x["at"].isoformat(), "first_seen_phase": x.get("phase", "REGULAR"),
                            "in_v2_scope": 0, "horizons_json": '["INTRADAY", "SAME_DAY"]',
                            "closed_reason": x.get("reason")})
        s.add_event({"event_id": f"{cid}:{x.get('typ', 'NEW')}:{x['at'].isoformat()}:{i}", "candidate_id": cid,
                     "window_id": "2026-09-24", "symbol": x["sym"], "at_utc": x["at"].isoformat(),
                     "data_as_of_utc": x.get("asof", x["at"] - timedelta(minutes=16)).isoformat(),
                     "phase": x.get("phase", "REGULAR"), "event_type": x.get("typ", "NEW"),
                     "classification": x.get("cls", "BULLISH"), "score": x.get("score", 70.0),
                     "last_price": x.get("price", 10.0), "gap_pct": 5.0, "features_json": "{}", "score_json": "{}",
                     "provenance_json": "{}"})
    s.commit()
    s.close()


def setstate(root, sym, state, reason=None, fam="GAP_UP"):
    s = OpportunityStore(root)
    s.upsert_candidate({"candidate_id": f"2026-09-24:{sym}:{fam}", "state": state, "closed_reason": reason})
    s.commit()
    s.close()


def promoter(root, now, **kw):
    seed(root, [])                                         # store exists -> boundary = current max seq
    return P.Promoter(root=root, clock=Clock(now), data=_NoData(), **kw)


class _NoData:
    def bars_ex(self, syms, **kw):
        from talonx_premarket.alpaca_data import FetchResult
        return FetchResult(batches=1)


def rows(pr, sql):
    return [tuple(r) for r in pr.con.execute(sql).fetchall()]


def reasons(pr):
    return {r[0]: r[1] for r in rows(pr, "SELECT symbol, reason_code FROM evaluations")}


# ---------------------------------------------------------------------------------------------------- eligibility
def test_01_valid_regular_bullish_setup_is_eligible_and_promoted_in_shadow(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert reasons(pr) == {"AAA": "OK"}
    assert rows(pr, "SELECT state, promotion_mode, source_strategy FROM promotions") == [("PROMOTED_SHADOW", "SHADOW", "OPPORTUNITY_ENGINE")]


@pytest.mark.parametrize("spec,why", [
    (dict(sym="W", cls="WATCH", state="WATCH"), "WATCH"),                                   # 2
    (dict(sym="B", cls="BEARISH", state="BEARISH_SETUP"), "BEARISH"),                       # 3
    (dict(sym="PM", phase="PREMARKET", at=T(13), asof=T(12, 44)), "PHASE"),                 # 4
    (dict(sym="AH", phase="AFTER_HOURS", at=T(20, 30), asof=T(20, 14)), "PHASE"),           # 5
    (dict(sym="DP", asof=T(13, 20)), "DATA_PHASE"),                                          # 6 processing REGULAR, data PREMARKET
])
def test_02_to_06_rejections(tmp_path, spec, why):
    now = spec.get("at", T(15))
    pr = promoter(tmp_path, now if spec.get("phase") != "PREMARKET" else T(13))
    spec.setdefault("at", T(13, 36) if spec["sym"] == "DP" else now)
    seed(tmp_path, [spec])
    pr.clock.t = spec["at"]
    pr.tick()
    assert reasons(pr)[spec["sym"]] == why
    assert rows(pr, "SELECT COUNT(*) FROM promotions") == [(0,)]


def test_07_stale_data_rejected(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="S", at=T(15), asof=T(14, 20))])      # 25 min behind the SIP as-of (14:45)
    pr.tick()
    assert reasons(pr)["S"] == "STALE"


def test_08_invalidated_candidate_rejected(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="I", at=T(15), state="INVALIDATED", reason="gap flipped direction")])
    pr.tick()
    assert reasons(pr)["I"] == "INVALIDATED"


def test_09_faded_and_stale_closed_candidates_rejected(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="F", at=T(15), state="INVALIDATED", reason="gap faded below 1.0%"),
                    dict(sym="C", at=T(15), state="INVALIDATED", reason="price went stale")])
    pr.tick()
    assert reasons(pr)["F"] == "FADED" and reasons(pr)["C"] == "STALE"


# ---------------------------------------------------------------------------------------------------- dedup / restart
def test_10_duplicate_candidate_never_promoted_twice(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15)), dict(sym="AAA", typ="UPGRADE", at=T(15, 5), asof=T(14, 49))])
    pr.clock.t = T(15, 5)
    pr.tick()
    assert rows(pr, "SELECT COUNT(*) FROM promotions") == [(1,)]
    assert sorted(r[0] for r in rows(pr, "SELECT reason_code FROM evaluations")) == ["DUPLICATE", "OK"]


def test_11_restart_preserves_dedup_and_does_not_replay(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    pr2 = P.Promoter(root=tmp_path, clock=Clock(T(15, 1)), data=_NoData())      # "restart"
    pr2.tick()
    assert rows(pr2, "SELECT COUNT(*) FROM promotions") == [(1,)]
    assert rows(pr2, "SELECT COUNT(*) FROM evaluations") == [(1,)]


# ---------------------------------------------------------------------------------------------------- delivery
def test_12_shadow_sends_nothing(tmp_path, monkeypatch):
    sent = []
    import talonx_ops.notify.worker as W
    monkeypatch.setattr(W, "drain", lambda *a, **k: sent.append(1))
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert sent == [] and not P.signal_outbox_path(tmp_path).exists()


def test_13_paper_signal_enqueues_to_trade_event_destination_with_signal_credentials(tmp_path, monkeypatch):
    for k, v in {"TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN": "signal-token", "TALONX_NOTIFY_TRADE_EVENT_CHAT_ID": "chat",
                 "TELEGRAM_BOT_TOKEN": "legacy-revoked", "TALONX_NOTIFY_RESEARCH_ENABLED": "1",
                 "TALONX_NOTIFY_RESEARCH_BOT_TOKEN": "lab-token", "TALONX_NOTIFY_RESEARCH_CHAT_ID": "chat"}.items():
        monkeypatch.setenv(k, v)
    used = []

    def fake_drain(store):
        from talonx_ops.notify import TRADE_EVENT, telegram_client_for
        used.append(telegram_client_for(TRADE_EVENT).config.telegram_bot_token)
        return {"sent": 1}
    pr = promoter(tmp_path, T(15), mode=P.PAPER_SIGNAL, drain=fake_drain)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    c = sqlite3.connect(P.signal_outbox_path(tmp_path))
    dest, etype, dedup, text = c.execute("SELECT destination, event_type, dedup_key, payload_text FROM ops_notification_outbox").fetchone()
    assert (dest, etype, dedup) == ("TRADE_EVENT", "PAPER_OPPORTUNITY", "OPPORTUNITY_ENGINE:2026-09-24:AAA:GAP_UP")
    assert "PAPER OPPORTUNITY" in text and "BUY" not in text.upper().replace("NOT BUY/SELL", "")
    assert used == ["signal-token"]                                             # 14: never lab / legacy


def test_14_lab_credentials_and_default_client_never_referenced():
    src = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")
    assert "RESEARCH" not in src.replace("RESEARCH_", "") and "TelegramClient(" not in src
    assert "TELEGRAM_BOT_TOKEN" not in src


# ---------------------------------------------------------------------------------------------------- isolation
def test_15_no_v2_tables_or_ledgers_touched(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    names = {p.name for p in tmp_path.iterdir()}
    assert not any("v2" in n.lower() for n in names)
    tree = ast.parse((REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and m.startswith("talonx_v2") for m in mods)


def test_16_no_broker_or_order_api():
    src = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8").lower()
    for bad in ("submit_order", "place_order", "/v2/orders", "tradingclient", "paper_trading", "alpaca.trading"):
        assert bad not in src


def test_17_causality_violation_rejected(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="FUT", at=T(15), asof=T(15, 2))])        # data newer than the decision -> impossible
    pr.tick()
    assert reasons(pr)["FUT"] == "CAUSALITY"


# ---------------------------------------------------------------------------------------------------- queue / rate
def test_18_19_rate_limit_3_per_5m_and_score_order(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym=f"S{i}", at=T(15), score=60 + i) for i in range(6)])
    pr.tick()
    promoted = rows(pr, "SELECT symbol FROM promotions WHERE state='PROMOTED_SHADOW' ORDER BY score DESC")
    assert [r[0] for r in promoted] == ["S5", "S4", "S3"]
    assert rows(pr, "SELECT COUNT(*) FROM promotions WHERE state='QUEUED'") == [(3,)]
    pr.clock.t = T(15, 5, 1)
    pr.tick()
    assert rows(pr, "SELECT COUNT(*) FROM promotions WHERE state='PROMOTED_SHADOW'") == [(6,)]


def test_20_queue_expires_after_30_minutes(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym=f"S{i}", at=T(15), score=60 + i) for i in range(4)])
    pr.tick()
    pr.clock.t = T(15, 31)
    pr.tick()
    assert rows(pr, "SELECT symbol, state, reason_code FROM promotions WHERE symbol='S0'") == [("S0", "EXPIRED", "QUEUE_EXPIRY_30M")]


def test_queued_candidate_invalidated_before_release_is_not_promoted(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym=f"S{i}", at=T(15), score=60 + i) for i in range(4)])
    pr.tick()
    setstate(tmp_path, "S0", "INVALIDATED", "gap faded below 1.0%")
    pr.clock.t = T(15, 6)
    pr.tick()
    assert rows(pr, "SELECT state, reason_code FROM promotions WHERE symbol='S0'") == [("REJECTED_WHILE_QUEUED", "FADED")]


# ---------------------------------------------------------------------------------------------------- boundary
def test_21_pre_boundary_candidates_are_never_replayed(tmp_path):
    seed(tmp_path, [dict(sym="OLD", at=T(14, 50))])                    # exists before the component first starts
    pr = P.Promoter(root=tmp_path, clock=Clock(T(15)), data=_NoData())
    pr.tick()
    assert rows(pr, "SELECT COUNT(*) FROM evaluations") == [(0,)] and pr.meta("PROMOTION_START_UTC")


def test_22_shadow_to_paper_signal_switch_does_not_replay_shadow_history(tmp_path):
    pr = promoter(tmp_path, T(15))
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    pr2 = P.Promoter(root=tmp_path, clock=Clock(T(15, 2)), mode=P.PAPER_SIGNAL, drain=lambda s: {"sent": 0},
                     data=_NoData())
    pr2.tick()
    c = sqlite3.connect(P.signal_outbox_path(tmp_path))
    assert c.execute("SELECT COUNT(*) FROM ops_notification_outbox").fetchone() == (0,)
    seed(tmp_path, [dict(sym="NEW1", at=T(15, 3), asof=T(14, 47))])
    pr2.clock.t = T(15, 3)
    pr2.tick()
    assert c.execute("SELECT dedup_key FROM ops_notification_outbox").fetchall() == [("OPPORTUNITY_ENGINE:2026-09-24:NEW1:GAP_UP",)]


# ---------------------------------------------------------------------------------------------------- outcomes
def _bars(start, prices):
    return [{"t": (start + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": p, "h": p + 0.05, "l": p - 0.05,
             "c": p, "v": 100} for i, p in enumerate(prices)]


def test_23_outcome_linked_to_promotion(tmp_path):
    class D:
        def bars_ex(self, syms, **kw):
            from talonx_premarket.alpaca_data import FetchResult
            r = FetchResult(batches=1)
            r.bars = {"AAA": _bars(T(14, 44), [10 + 0.01 * i for i in range(90)])}
            return r
    pr = promoter(tmp_path, T(15))
    pr._data = D()
    seed(tmp_path, [dict(sym="AAA", at=T(15), asof=T(14, 44))])
    pr.tick()
    pr.clock.t = T(16, 30)
    pr.tick()
    row = rows(pr, "SELECT promotion_id, candidate_id, ret_15m_pct, ret_30m_pct, ret_1h_pct FROM paper_outcomes")[0]
    assert row[0] == "OPPORTUNITY_ENGINE:2026-09-24:AAA:GAP_UP" and row[1] == "2026-09-24:AAA:GAP_UP"
    assert row[2] > 0 and row[3] > 0 and row[4] > 0


def test_24_long_only_outcome_direction():
    ref = T(15)
    down = P.measure_long(ref, 10.0, _bars(ref, [10 - 0.02 * i for i in range(70)]), T(20))
    up = P.measure_long(ref, 10.0, _bars(ref, [10 + 0.02 * i for i in range(70)]), T(20))
    assert down["ret_30m_pct"] < 0 and up["ret_30m_pct"] > 0 and down["status"] == "FAILED_CONFIRMATION"


def test_policy_fingerprint_and_mode_contract():
    assert P.PROMOTION_V1.version == "OPPORTUNITY_PROMOTION_V1" and len(P.PROMOTION_V1.fingerprint()) == 16
    assert P.mode_from_env({}) == P.SHADOW
    with pytest.raises(SystemExit):
        P.mode_from_env({P.MODE_ENV: "LIVE"})
