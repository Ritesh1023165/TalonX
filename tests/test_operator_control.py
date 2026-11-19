"""Sentinel operator control plane (2026-09-25): commands, DRY_RUN identity, ACTIVE fetch gates, promotion gate,
no replay, authorization, /scanned. No network, no Telegram."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3

import pytest

from talonx_ops import operator_control as OC
from talonx_ops.operator_control import commands as C
from talonx_ops.operator_control import gates as G
from talonx_ops.operator_control.store import OperatorStore, normalize_symbol

OWNER = "547"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_OPERATOR_DB", str(tmp_path / "operator_control.db"))
    monkeypatch.delenv(OC.MODE_ENV, raising=False)
    return OperatorStore()


def run(store, text, chat=OWNER, mode=OC.DRY_RUN, scanned=None):
    return C.handle(text, chat_id=chat, user="u1", owner_chat_id=OWNER, store=store, mode=mode, scanned=scanned)


# ---------------------------------------------------------------------------------------------------- help / UX
@pytest.mark.parametrize("cmd,needle", [("/help", "COMMAND HELP"), ("/help universe", "/universe add PLTR"),
                                        ("/help exclude", "never fetched"), ("/help scanned", "/scanned file"),
                                        ("/help status", "/status")])
def test_help(store, cmd, needle):
    r = run(store, cmd)
    assert needle in r.text and not r.mutated


def test_help_mentions_dry_run_before_activation(store):
    assert "DRY_RUN" in run(store, "/help exclude").text and "DRY_RUN" not in run(store, "/help exclude", mode=OC.ACTIVE).text


def test_unknown_command_suggests(store):
    assert "Did you mean /exclude" in run(store, "/exclde add TSLA").text


@pytest.mark.parametrize("text,needle", [("/exclude add", "missing symbol"), ("/exclude add $$$", "invalid symbol"),
                                         ("/exclude frob TSLA", "Usage: /exclude"), ("/universe", "Usage: /universe"),
                                         ("/scanned bogus", "Usage: /scanned")])
def test_bad_syntax(store, text, needle):
    assert needle in run(store, text, scanned=object()).text


def test_non_command_and_ping_fall_through(store):
    assert run(store, "47") is None and run(store, "/ping") is None and run(store, "/status") is None


def test_symbol_normalisation():
    assert normalize_symbol(" tsla ") == ("TSLA", None)
    assert normalize_symbol("brk.b") == ("BRK.B", None) and normalize_symbol("bf-b") == ("BF-B", None)
    assert normalize_symbol("TOOLONGX")[1] and normalize_symbol("A1")[1] and normalize_symbol("")[1]


# ---------------------------------------------------------------------------------------------------- mutation (DRY_RUN)
def test_dry_run_persists_pending_intent_and_is_audited(store):
    r = run(store, "/exclude add tsla earnings noise")
    assert r.mutated and "PENDING" in r.text and "unchanged until activation" in r.text
    row = store.exclusion_row("TSLA")
    assert row["status"] == "EXCLUDED" and row["activation"] == "PENDING_ACTIVATION" and row["reason"] == "earnings noise"
    a = dict(store.con.execute("SELECT * FROM operator_audit").fetchone())
    assert a["authorized"] == 1 and a["symbol"] == "TSLA" and a["result"] == "PENDING_ACTIVATION"
    assert "already excluded" in run(store, "/exclude add TSLA").text
    assert "PENDING" in run(store, "/exclude remove TSLA").text and store.exclusion_row("TSLA")["status"] == "RESTORED"
    assert "not excluded" in run(store, "/exclude remove TSLA").text


def test_universe_add_remove_list_status(store):
    assert "PENDING" in run(store, "/universe add pltr").text
    assert "already in the operator universe" in run(store, "/universe add PLTR").text
    assert "PLTR" in run(store, "/universe list").text and "PENDING_ACTIVATION" in run(store, "/universe status PLTR").text
    assert "removal accepted" in run(store, "/universe remove PLTR").text
    assert "not an operator-added" in run(store, "/universe remove PLTR").text


def test_dry_run_gates_are_exact_identities(store):
    run(store, "/exclude add AAA")
    run(store, "/universe add ZZZ")
    base = ["AAA", "BBB"]
    assert G.effective_symbols(base) == base                       # DRY_RUN: untouched
    m = {"AAA": {}, "BBB": {}}
    assert G.effective_members(m) is m and G.is_excluded("AAA") is False


# ---------------------------------------------------------------------------------------------------- authorization
def test_unauthorized_never_mutates_and_is_audited_without_secrets(store, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "sentinel-SECRET-token")
    r = run(store, "/exclude add TSLA", chat="999")
    assert "Not authorised" in r.text and not r.mutated and store.exclusion_row("TSLA") is None
    a = [dict(x) for x in store.con.execute("SELECT * FROM operator_audit")]
    assert a[0]["authorized"] == 0 and a[0]["result"] == "REJECTED_UNAUTHORIZED"
    assert "SECRET" not in json.dumps(a) and "SECRET" not in r.text


# ---------------------------------------------------------------------------------------------------- ACTIVE gates
def test_active_effective_universe_precedence_and_restore(store, monkeypatch):
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add BBB", mode=OC.ACTIVE)
    run(store, "/universe add ZZZ", mode=OC.ACTIVE)
    assert G.effective_symbols(["AAA", "BBB"]) == ["AAA", "ZZZ"]
    assert G.effective_symbols(["AAA", "BBB"], include_added=False) == ["AAA"]
    run(store, "/exclude add ZZZ", mode=OC.ACTIVE)                   # exclusion wins over an operator add
    assert G.effective_symbols(["AAA"]) == ["AAA"]
    run(store, "/exclude remove BBB", mode=OC.ACTIVE)
    assert G.effective_symbols(["AAA", "BBB"]) == ["AAA", "BBB"]
    run(store, "/universe remove ZZZ", mode=OC.ACTIVE)
    run(store, "/exclude remove ZZZ", mode=OC.ACTIVE)
    assert G.effective_symbols(["AAA"]) == ["AAA"]                   # restored exclusion but removed -> not fetched


def test_active_alpaca_batch_never_requests_an_excluded_symbol(store, monkeypatch, tmp_path):
    from tests.test_continuous_opportunity_engine import U, Clock, FakeData, _world
    from talonx_opportunity.ingestion import Ingestion
    minute, daily, members = _world()
    seen = []

    class Rec(FakeData):
        def bars_ex(self, symbols, **kw):
            if kw.get("timeframe") == "1Min":
                seen.append(sorted(symbols))
            return super().bars_ex(symbols, **kw)
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add BBB", mode=OC.ACTIVE)
    ing = Ingestion(data=Rec(minute, daily), root=tmp_path / "opp", clock=Clock(U(9)), universe_loader=lambda: (members, "t"))
    ing.tick()
    assert seen and all("BBB" not in s for s in seen if s != ["SPY"])
    monkeypatch.setenv(OC.MODE_ENV, "DRY_RUN")                       # DRY_RUN: BBB fetched as today
    seen.clear()
    ing2 = Ingestion(data=Rec(minute, daily), root=tmp_path / "opp2", clock=Clock(U(9)), universe_loader=lambda: (members, "t"))
    ing2.tick()
    assert any("BBB" in s for s in seen)


def test_active_yfinance_batch_never_requests_an_excluded_symbol(store, monkeypatch):
    from talonx_ingest.market_data.yfinance_poll import YFinancePoller
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add TSLA", mode=OC.ACTIVE)
    p = YFinancePoller()
    got = []

    def fake_fetch(symbols):
        got.append(list(symbols))
        p.stop()
        return []
    monkeypatch.setattr(p, "_fetch_snapshots", fake_fetch)

    async def go():
        await asyncio.wait_for(p.stream(["AAPL", "TSLA"], lambda e: None), timeout=10)
    try:
        asyncio.run(go())
    except Exception:  # noqa: BLE001 -- the loop may end on stop; the batch is what matters
        pass
    assert got and got[0] == ["AAPL"]


def test_active_discovery_members_skip_excluded_and_add_operator_symbols(store, monkeypatch):
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add BBB", mode=OC.ACTIVE)
    run(store, "/universe add NEWCO", mode=OC.ACTIVE)
    out = G.effective_members({"AAA": {"symbol": "AAA"}, "BBB": {"symbol": "BBB"}})
    assert "BBB" not in out and out["NEWCO"]["status"] == "ELIGIBLE" and out["NEWCO"]["cik"] is None


# ---------------------------------------------------------------------------------------------------- promotion gate + no replay
def test_active_promotion_rejects_excluded_expires_queued_and_keeps_sent_outcomes(store, monkeypatch, tmp_path):
    from tests.test_opportunity_promotion import T, promoter, rows, seed
    root = tmp_path / "opp"
    pr = promoter(root, T(15))
    seed(root, [dict(sym=f"S{c}", at=T(15), score=60 + i) for i, c in enumerate("ABCD")])
    pr.tick()                                                       # SD,SC,SB promoted (shadow); SA queued
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add SA", mode=OC.ACTIVE)
    run(store, "/exclude add SD", mode=OC.ACTIVE)                    # already promoted: history kept
    seed(root, [dict(sym="SD", typ="UPGRADE", at=T(15, 6), asof=T(14, 50)), dict(sym="NEW", at=T(15, 6), asof=T(14, 50))])
    pr.clock.t = T(15, 6)
    pr.tick()
    assert rows(pr, "SELECT state, reason_code FROM promotions WHERE symbol='SA'") == [("EXPIRED", "OPERATOR_EXCLUDED")]
    assert rows(pr, "SELECT state FROM promotions WHERE symbol='SD'") == [("PROMOTED_SHADOW",)]
    assert rows(pr, "SELECT state FROM promotions WHERE symbol='NEW'") == [("PROMOTED_SHADOW",)]


def test_restore_never_replays_the_excluded_period(store, monkeypatch, tmp_path):
    from tests.test_opportunity_promotion import T, promoter, reasons, rows, seed
    root = tmp_path / "opp"
    pr = promoter(root, T(15))
    monkeypatch.setenv(OC.MODE_ENV, "ACTIVE")
    run(store, "/exclude add XX", mode=OC.ACTIVE)                    # T1
    seed(root, [dict(sym="XX", at=T(15), asof=T(14, 44))])           # event inside the excluded period
    pr.tick()
    assert reasons(pr)["XX"] == "OPERATOR_EXCLUDED"
    run(store, "/exclude remove XX", mode=OC.ACTIVE)                 # T2
    pr.clock.t = T(15, 1)
    pr.tick()                                                       # the excluded-period event is NOT re-evaluated
    assert rows(pr, "SELECT COUNT(*) FROM promotions WHERE symbol='XX'") == [(0,)]


# ---------------------------------------------------------------------------------------------------- /scanned
@pytest.fixture
def scanned(tmp_path):
    from tests.test_continuous_opportunity_engine import U, Clock, FakeData, _world
    from talonx_opportunity.discovery import Discovery
    from talonx_opportunity.ingestion import Ingestion
    from talonx_ops.operator_control.scanned import ScannedReader
    minute, daily, members = _world()
    clock = Clock(U(9))
    root = tmp_path / "opp"
    ing = Ingestion(data=FakeData(minute, daily), root=root, clock=clock, universe_loader=lambda: (members, "t"))
    disc = Discovery(root=root, clock=clock)
    for t in (U(9), U(14, 30)):
        clock.t = t
        ing.tick()
        disc.tick()
    return ScannedReader(root, excluded={"CCC"})


def test_scanned_summary_uses_authoritative_counts(store, scanned):
    r = run(store, "/scanned", scanned=scanned)
    s = scanned.summary()
    assert f"Candidates: {s['candidates']}" in r.text and s["candidates"] >= 1 and s["unique_symbols_seen"] >= 1


def test_scanned_lists_and_file(store, scanned):
    assert "CANDIDATES (" in run(store, "/scanned candidates", scanned=scanned).text
    assert "SETUPS (" in run(store, "/scanned setups", scanned=scanned).text
    assert "PAPER PROMOTIONS (0)" in run(store, "/scanned signals", scanned=scanned).text
    f = run(store, "/scanned file", scanned=scanned)
    rows = list(csv.DictReader(io.StringIO(f.document.decode())))
    assert f.filename.endswith(".csv") and {"symbol", "max_score", "candidate", "excluded", "universe_source"} <= set(rows[0])
    assert any(r["symbol"] == "CCC" and r["excluded"] == "Y" for r in rows)


# ---------------------------------------------------------------------------------------------------- Sentinel poller
def test_sentinel_poller_replies_on_its_own_bot_and_sends_files(store, scanned):
    from talonx_ops.operator_control.sentinel import SentinelCommandPoller
    sent = []

    class Bot:
        async def send_message(self, **k):
            sent.append(("msg", k["chat_id"], k["text"][:30]))

        async def send_document(self, **k):
            sent.append(("doc", k["chat_id"], k["filename"]))

    class M:
        def __init__(self, text, chat):
            self.text, self.chat_id, self.from_user = text, chat, None
    p = SentinelCommandPoller(bot=Bot(), owner_chat_id=OWNER, store=store, scanned_factory=lambda: scanned)
    for t in ("/help", "/scanned file", "/exclude add TSLA"):
        asyncio.run(p.handle_message(M(t, OWNER)))
    asyncio.run(p.handle_message(M("/exclude add AAPL", "999")))
    assert [s[0] for s in sent] == ["msg", "doc", "msg", "msg"] and store.exclusion_row("AAPL") is None


def test_sentinel_poller_uses_only_operations_credentials():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "talonx_ops" / "operator_control" / "sentinel.py").read_text(encoding="utf-8")
    assert "resolve_destination_config(OPERATIONS)" in src
    for bad in ("TRADE_EVENT", "RESEARCH", "TELEGRAM_BOT_TOKEN", "TelegramClient("):
        assert bad not in src
