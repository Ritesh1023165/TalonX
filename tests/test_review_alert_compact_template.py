"""Compact research-review alert template RESEARCH_REVIEW_COMPACT_V1 (owner-approved 2026-10-09, presentation only).
Fixtures and local renders only -- nothing is sent. Every value must come from records available at render time."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from talonx_opportunity import promotion as P
from talonx_opportunity.phases import trading_window
from talonx_opportunity.store import OpportunityStore

UTC = timezone.utc
FEATS = {"gap_pct": 3.015193820937734, "prev_close": 275.77, "prev_high": 280.53, "prev_low": 273.46,
         "range_position": "ABOVE_PREV_HIGH", "range_distance_pct": 1.267244145011226, "atr20_pct": 5.5385937556659535,
         "pm_volume": 640567.0, "activity_adv_fraction": 0.1397100448463776, "last_bar_utc": "2026-10-09T15:47:00Z"}
PROV = {"delay_minutes": 15, "feed": "sip"}


def q(**over):
    d = {"promotion_id": "OPPORTUNITY_ENGINE:2026-10-09:TWLO:GAP_UP", "symbol": "TWLO", "score": 65.89,
         "reference_price": 284.085, "data_as_of_utc": "2026-10-09T15:48:00+00:00",
         "event_utc": "2026-10-09T16:05:00.041831+00:00", "window_id": "2026-10-09"}
    d.update(over)
    return d


def ctx(cat="none found", feats=FEATS, prov=PROV, close=None, prior=None, universe="DTU_V3_TOP600"):
    return {"event": {"features_json": json.dumps(feats), "score_json": "{}", "catalyst": cat,
                      "provenance_json": json.dumps(prov)},
            "close_utc": close or trading_window(date(2026, 10, 9)).close_utc, "prior_delivery_date": prior,
            "universe": universe}


NOW = datetime(2026, 10, 9, 16, 5, 36, 733277, tzinfo=UTC)


# ============================================================================================ content
def test_typical_alert_renders_the_approved_structure_exactly():
    txt = P.render_review_compact(q(), NOW, "OPPORTUNITY_PROMOTION_V1", ctx())
    assert txt.split("\n") == [
        "🔎 RESEARCH OPPORTUNITY — UNVALIDATED",
        "TWLO · price up 3.02% from prior close $275.77",
        "",
        "Why flagged: move = 0.5× its 20-day average true range (5.54% of price) · volume since 04:00 ET 640,567 sh "
        "= 14.0% of 20-day avg daily volume · 1.27% above prior-day high $280.53",
        "",
        "Historical price: $284.08 at 11:48 ET",
        "15-min delayed feed · data 17 min old when written · not a live quote",
        "Detected 12:05 ET · written 12:05 ET",
        "",
        "SEC context: No matching SEC/insider record found in the checked sources. News not checked.",
        "",
        "Scope: Today’s session, closing 16:00 ET. No entry, exit or holding rule.",
        "Rule score: 65.9/100; not a probability.",
        "",
        "⚠️ This policy’s evaluated paper results were negative after costs.",
        "For review only · not a buy instruction · no order placed",
        "Policy OPPORTUNITY_PROMOTION_V1 · universe DTU_V3_TOP600 · reference OPPORTUNITY_ENGINE:2026-10-09:TWLO:GAP_UP",
    ]


def test_no_forecast_catalyst_or_trading_language_and_no_acknowledgement_time():
    txt = P.render_review_compact(q(), NOW, "OPPORTUNITY_PROMOTION_V1", ctx())
    low = txt.lower()
    for banned in ("bullish", "premarket", "pre-market", "target", "stop", "expected", "urgent", "buy now",
                   "probability of", "confidence", "manipulat", "ack", "delivered at", "received"):
        assert banned not in low, banned
    assert "not a buy instruction" in txt and "not a probability" in txt and "not a live quote" in txt


def test_missing_evidence_renders_unknown_and_never_raises():
    bare = {"promotion_id": "OPPORTUNITY_ENGINE:x", "symbol": "AAA", "score": None, "reference_price": None,
            "data_as_of_utc": None, "event_utc": None, "window_id": "not-a-date"}
    for c in (None, {"event": None}, {"event": {"features_json": "not json", "provenance_json": None, "catalyst": None}}):
        txt = P.render_review_compact(bare, NOW, "OPPORTUNITY_PROMOTION_V1", c)
        assert "price move vs prior close UNKNOWN" in txt
        assert "Why flagged: UNKNOWN" in txt and "Historical price: UNKNOWN at UNKNOWN" in txt
        assert "Delayed feed · data UNKNOWN age old when written" in txt and "Detected UNKNOWN · written 12:05 ET" in txt
        assert "SEC context: UNKNOWN (no catalyst record). News not checked." in txt
        assert "closing UNKNOWN" in txt and "Rule score: UNKNOWN." in txt and "universe UNKNOWN" in txt
        assert "Repeat:" not in txt
        assert "⚠️ This policy’s evaluated paper results were negative after costs." in txt


def test_partial_reason_fields_are_marked_unknown_individually():
    f = {k: v for k, v in FEATS.items() if k not in ("atr20_pct", "activity_adv_fraction", "range_position")}
    txt = P.render_review_compact(q(), NOW, "P", ctx(feats=f))
    assert ("Why flagged: move vs 20-day range UNKNOWN · volume since 04:00 ET 640,567 sh · position vs prior-day "
            "high UNKNOWN") in txt


# ============================================================================================ SEC wording
@pytest.mark.parametrize("cat,expect", [
    ("none found", "SEC context: No matching SEC/insider record found in the checked sources. News not checked."),
    ("catalyst lookup incomplete: SEC lookup failed",
     "SEC context: UNKNOWN (catalyst lookup incomplete: SEC lookup failed). News not checked."),
    (None, "SEC context: UNKNOWN (no catalyst record). News not checked."),
    ("1 other SEC filing(s): 144",
     "SEC context: other filing(s): Form 144 proposed-sale notice. Connection to the move unverified; news not checked."),
    ("2 other SEC filing(s): 144, 4", "SEC context: other filing(s): Form 144 proposed-sale notice, Form 4 insider "
                                      "transaction report. Connection to the move unverified; news not checked."),
    ("6-K filed 2026-10-08", "SEC context: 6-K filed 2026-10-08. Connection to the move unverified; news not checked."),
    ("8-K items 7.01 filed 2026-10-09; 3 other SEC filing(s): ARS, DEF 14A, DEFA14A",
     "SEC context: 8-K items 7.01 filed 2026-10-09; other filing(s): Form ARS, Form DEF 14A, Form DEFA14A. "
     "Connection to the move unverified; news not checked."),
    ("8-K earnings (item 2.02) filed 2026-10-09; catalyst lookup incomplete: insider ledger unavailable",
     "SEC context: 8-K earnings (item 2.02) filed 2026-10-09; other sources UNKNOWN (catalyst lookup incomplete: "
     "insider ledger unavailable). Connection to the move unverified; news not checked."),
])
def test_sec_context_distinguishes_no_match_from_unknown_and_stays_neutral(cat, expect):
    assert P._sec_context(cat) == expect
    assert "bullish" not in expect.lower() and "catalyst confirmed" not in expect.lower()


def test_form_144_is_a_proposed_sale_notice_not_a_completed_sale_or_bullish_catalyst():
    txt = P.render_review_compact(q(), NOW, "P", ctx(cat="1 other SEC filing(s): 144"))
    assert "Form 144 proposed-sale notice" in txt
    assert "sold" not in txt.lower() and "sale completed" not in txt.lower() and "bullish" not in txt.lower()


# ============================================================================================ time
def test_old_data_and_queue_delay_are_separated_from_detection():
    qq = q(data_as_of_utc="2026-10-09T14:03:00+00:00", event_utc="2026-10-09T14:20:00.059498+00:00")
    txt = P.render_review_compact(qq, datetime(2026, 10, 9, 14, 32, 47, tzinfo=UTC), "P", ctx())
    assert "Historical price: $284.08 at 10:03 ET" in txt
    assert "15-min delayed feed · data 29 min old when written · not a live quote" in txt
    assert "Detected 10:20 ET · written 10:32 ET" in txt


@pytest.mark.parametrize("window,asof,now,close_et,asof_et", [
    ("2026-10-30", "2026-10-30T14:00:00+00:00", datetime(2026, 10, 30, 14, 16, tzinfo=UTC), "16:00", "10:00"),  # EDT
    ("2026-11-02", "2026-11-02T15:00:00+00:00", datetime(2026, 11, 2, 15, 16, tzinfo=UTC), "16:00", "10:00"),  # EST
    ("2026-11-27", "2026-11-27T15:00:00+00:00", datetime(2026, 11, 27, 15, 16, tzinfo=UTC), "13:00", "10:00"),  # half day
])
def test_session_close_comes_from_the_exchange_calendar_across_dst_and_half_days(window, asof, now, close_et, asof_et):
    close = trading_window(date.fromisoformat(window)).close_utc
    txt = P.render_review_compact(q(window_id=window, data_as_of_utc=asof, event_utc=asof), now, "P",
                                  ctx(close=close))
    assert f"Scope: Today’s session, closing {close_et} ET. No entry, exit or holding rule." in txt
    assert f"at {asof_et} ET" in txt and "data 16 min old when written" in txt


# ============================================================================================ repeat / escaping / size
def test_repeat_line_only_with_a_supported_earlier_confirmed_delivery():
    assert "Repeat: earlier alert for TWLO delivered 2026-10-01" in \
        P.render_review_compact(q(), NOW, "P", ctx(prior="2026-10-01"))
    assert "Repeat" not in P.render_review_compact(q(), NOW, "P", ctx(prior=None))
    assert "first" not in P.render_review_compact(q(), NOW, "P", ctx(prior=None)).lower()


def test_plain_text_is_verbatim_for_parse_mode_none_and_well_under_telegram_limit():
    worst = ctx(cat="; ".join([f"8-K items 1.01, 2.03, 7.01, 8.01, 9.01 filed 2026-10-0{i}" for i in range(1, 9)]
                              + ["9 other SEC filing(s): 144, 3, 4, 5, 8-A12B, ARS, DEF 14A, DEFA14A, SC 13G"]))
    txt = P.render_review_compact(q(symbol="BRK.B<b>&_*[x]"), NOW, "P", worst)
    assert "BRK.B<b>&_*[x] · price up" in txt                     # no HTML/Markdown escaping: sent as plain text
    assert len(txt) < 4096 and len(P.render_review_compact(q(), NOW, "P", ctx())) < 1200


# ============================================================================================ end-to-end send path
def rich_seed(root, sym, at, cat="none found"):
    s = OpportunityStore(root)
    cid = f"2026-09-24:{sym}:GAP_UP"
    s.upsert_candidate({"candidate_id": cid, "window_id": "2026-09-24", "symbol": sym, "family": "GAP_UP",
                        "state": "BULLISH_SETUP", "classification": "BULLISH", "first_seen_utc": at.isoformat(),
                        "first_seen_phase": "REGULAR", "in_v2_scope": 0, "horizons_json": '["INTRADAY", "SAME_DAY"]'})
    s.add_event({"event_id": f"{cid}:NEW:{at.isoformat()}", "candidate_id": cid, "window_id": "2026-09-24",
                 "symbol": sym, "at_utc": at.isoformat(), "data_as_of_utc": (at - timedelta(minutes=16)).isoformat(),
                 "phase": "REGULAR", "event_type": "NEW", "classification": "BULLISH", "score": 70.0,
                 "last_price": 10.0, "gap_pct": 5.0, "features_json": json.dumps({**FEATS, "gap_pct": 5.0,
                                                                                  "prev_close": 9.52}),
                 "score_json": "{}", "catalyst": cat, "provenance_json": json.dumps(PROV)})
    s.commit()
    s.close()


def _setup(tmp_path, monkeypatch, client):
    from tests.test_delivery_trace_deployment import FakeBot  # noqa: F401 (fixture module import side effects)
    from tests.test_opportunity_promotion import Clock, T as tt, _NoData, seed
    from tests.test_promotion_signal_pause import PAUSE, pause
    pause(tmp_path, {**PAUSE, "paused": False, "delivery_mode": "RESEARCH_REVIEW",
                     "delivery_boundary_utc": tt(14).isoformat()})
    import talonx_ops.notify as N
    import talonx_ops.notify.worker as W
    monkeypatch.setattr(N, "telegram_client_for", lambda dest: client)
    monkeypatch.setattr(N, "resolve_destination_config", lambda dest: SimpleNamespace(enabled=True, reason="t"))
    monkeypatch.setattr(W, "resolve_destination_config", lambda dest: SimpleNamespace(enabled=True, reason="t"))
    monkeypatch.setattr(W, "telegram_client_for", lambda dest: client)

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return tt(15).astimezone(tz) if tz else tt(15)
    monkeypatch.setattr(W, "datetime", FixedNow)
    (tmp_path / "control").mkdir(exist_ok=True)
    (tmp_path / "control" / "dtu_policy_schedule.json").write_text(json.dumps(
        {"schedule": [{"policy": "DTU_V3_TOP600", "effective_from_window": "2026-09-01"}]}), encoding="utf-8")
    seed(tmp_path, [])
    pr = P.Promoter(root=tmp_path, clock=Clock(tt(15)), data=_NoData(), mode=P.PAPER_SIGNAL)
    return pr, tt


class Client:
    is_configured = True

    def __init__(self):
        self.sent = []

    async def send(self, text, parse_mode=None, **kw):
        self.sent.append((text, parse_mode))
        return SimpleNamespace(message_id=11, date=datetime.now(UTC).replace(microsecond=0), chat=SimpleNamespace(id=-7))


def test_live_path_renders_compact_template_records_version_and_tracing_still_correlates(tmp_path, monkeypatch):
    from talonx_opportunity import delivery_trace as Tr
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)
    rich_seed(tmp_path, "AAA", tt(15), cat="1 other SEC filing(s): 144")
    pr.tick()
    ob = sqlite3.connect(P.signal_outbox_path(tmp_path))
    ev, payload, state, prov = ob.execute("SELECT event_id, payload_text, state, provenance_json FROM "
                                          "ops_notification_outbox").fetchone()
    assert state == "SENT" and c.sent == [(payload, None)]                    # one plain-text send, same text
    assert payload.startswith("🔎 RESEARCH OPPORTUNITY — UNVALIDATED\nAAA · price up 5.00% from prior close $9.52")
    assert "Form 144 proposed-sale notice" in payload and "closing 16:00 ET" in payload
    assert "universe DTU_V3_TOP600 · reference OPPORTUNITY_ENGINE:2026-09-24:AAA:GAP_UP" in payload
    assert json.loads(prov)["template_version"] == P.REVIEW_TEMPLATE_VERSION
    look = Tr.make_trace_lookup(P.signal_outbox_path(tmp_path), P.trace_path(tmp_path))(ev)
    assert look["trace_state"] == "TRACE_OK"


def test_score_state_and_eligibility_are_unchanged_by_the_template(tmp_path, monkeypatch):
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)
    rich_seed(tmp_path, "AAA", tt(15))
    pr.tick()
    row = sqlite3.connect(P.promotion_db(tmp_path)).execute(
        "SELECT state, reason_code, score, reference_price, policy_fp FROM promotions").fetchone()
    assert row == ("PROMOTED_SIGNAL", P.REVIEW_REASON, 70.0, 10.0, P.PROMOTION_V1.fingerprint())
    assert P.PROMOTION_V1.fingerprint() == "4926c12e5eace04e"                # policy fingerprint unchanged


def test_repeat_uses_only_earlier_confirmed_sent_deliveries(tmp_path, monkeypatch):
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)
    with pr.con:                                                             # an earlier promotion of the symbol
        for pid, w in (("OLD1", "2026-09-23"), ("OLD2", "2026-09-22")):
            pr.con.execute("INSERT INTO promotions (promotion_id, candidate_id, symbol, state, signal_event_id, "
                           "window_id, data_as_of_utc, decision_utc, queued_utc, event_utc, reference_price, score) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, "c-" + pid, "AAA", "PROMOTED_SIGNAL", pid, w, f"{w}T14:00:00+00:00",
                            f"{w}T14:16:00+00:00", f"{w}T14:16:00+00:00", f"{w}T14:16:00+00:00", 10.0, 70.0))
    pr.outbox.enqueue(event_id="OLD1", destination="TRADE_EVENT", event_type="RESEARCH_OPPORTUNITY", producer="t",
                      dedup_key="OLD1", payload_text="old wording kept", provenance={},
                      deliver_by_utc=(tt(15) + timedelta(hours=1)).isoformat())
    ob = sqlite3.connect(P.signal_outbox_path(tmp_path))
    ob.execute("UPDATE ops_notification_outbox SET state='FAILED' WHERE event_id='OLD1'")   # never confirmed
    ob.commit()
    rich_seed(tmp_path, "AAA", tt(15))
    pr.tick()
    new = ob.execute("SELECT payload_text FROM ops_notification_outbox WHERE event_id LIKE 'OPPORTUNITY_ENGINE:%'"
                     ).fetchone()[0]
    assert "Repeat:" not in new                                              # FAILED is not a confirmed delivery
    assert ob.execute("SELECT payload_text FROM ops_notification_outbox WHERE event_id='OLD1'").fetchone()[0] == \
        "old wording kept"                                                   # pre-existing rows never rewritten
    ob.execute("UPDATE ops_notification_outbox SET state='SENT', sent_at_utc='2026-09-23T14:00:00+00:00' "
               "WHERE event_id='OLD1'")
    ob.commit()
    ctx_ = pr._review_context(OpportunityStore(tmp_path, readonly=True),
                              {"event_id": "x", "window_id": "2026-09-24", "symbol": "AAA",
                               "promotion_id": "OPPORTUNITY_ENGINE:2026-09-24:AAA:GAP_UP"})
    assert ctx_["prior_delivery_date"] == "2026-09-23" and ctx_["universe"] == "DTU_V3_TOP600"
    assert ctx_["close_utc"] == trading_window(date(2026, 9, 24)).close_utc


def test_a_presentation_fault_never_blocks_release(tmp_path, monkeypatch):
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)
    monkeypatch.setattr(P.Promoter, "_review_context", lambda self, s, q: (_ for _ in ()).throw(RuntimeError("x")))
    rich_seed(tmp_path, "AAA", tt(15))
    pr.tick()
    assert len(c.sent) == 1 and "SEC context: UNKNOWN" in c.sent[0][0]
