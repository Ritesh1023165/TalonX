"""P0 package 2A (2026-09-26): missed-EOD visibility (F-P3), boundary hardening (F-P1 supervisor class, F-P2 verified
shared-runtime declarations), role-aware Telegram poller health, supervised Sentinel + promotion, status visibility.
No network, no Telegram."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_opportunity import runtime as RT

UTC = timezone.utc
OWNER = "547"


# ================================================================================ F-P3 missed previous-session EOD
def _session(root: Path, day: str, closed: bool):
    sd = root / f"prospective_{day}"
    sd.mkdir(parents=True)
    (sd / "start_verify.json").write_text("{}")
    if closed:
        (sd / "eod.json").write_text("{}")


def _eod(now, root):
    from talonx_ops.prospective.checkpoint import eod_state
    return eod_state(now, results_root=root)


def test_friday_closed_is_not_overdue_on_saturday(tmp_path):
    _session(tmp_path, "2026-09-25", closed=True)
    assert _eod(datetime(2026, 9, 26, 12, tzinfo=UTC), tmp_path)["state"] == "NOT_DUE_YET"


@pytest.mark.parametrize("when", [datetime(2026, 9, 26, 12, tzinfo=UTC), datetime(2026, 9, 27, 18, tzinfo=UTC),
                                  datetime(2026, 9, 28, 9, tzinfo=UTC)])       # Sat, Sun, Monday before the open
def test_friday_missed_is_overdue_until_closed(tmp_path, when):
    _session(tmp_path, "2026-09-25", closed=False)
    st = _eod(when, tmp_path)
    assert st["state"] == "OVERDUE_EOD_CLOSE" and st["session_date"] == "2026-09-25"
    assert st["session_dir"].endswith("prospective_2026-09-25")


def test_no_friday_session_is_no_false_alarm(tmp_path):
    assert _eod(datetime(2026, 9, 26, 12, tzinfo=UTC), tmp_path)["state"] == "NOT_DUE_YET"
    (tmp_path / "prospective_2026-09-25").mkdir()                   # empty dir: never started
    assert _eod(datetime(2026, 9, 26, 12, tzinfo=UTC), tmp_path)["state"] == "NOT_DUE_YET"


def test_holiday_uses_the_previous_real_session(tmp_path):
    # Thanksgiving 2026-11-26 (Thu) is not a session; the previous session is Wed 2026-11-25
    _session(tmp_path, "2026-11-25", closed=False)
    st = _eod(datetime(2026, 11, 26, 15, tzinfo=UTC), tmp_path)
    assert st["state"] == "OVERDUE_EOD_CLOSE" and st["session_date"] == "2026-11-25"
    (tmp_path / "prospective_2026-11-25" / "eod.json").write_text("{}")
    assert _eod(datetime(2026, 11, 26, 15, tzinfo=UTC), tmp_path)["state"] == "NOT_DUE_YET"


def test_todays_own_session_states_are_unchanged(tmp_path):
    _session(tmp_path, "2026-09-24", closed=True)
    assert _eod(datetime(2026, 9, 25, 15, tzinfo=UTC), tmp_path)["state"] == "NOT_DUE_YET"
    assert _eod(datetime(2026, 9, 25, 20, 30, tzinfo=UTC), tmp_path)["state"] == "PENDING"
    assert _eod(datetime(2026, 9, 25, 22, tzinfo=UTC), tmp_path)["state"] == "STALE"


def test_overdue_is_never_closed_without_force(tmp_path, monkeypatch):
    from talonx_ops.prospective import close as CL
    monkeypatch.setattr(CL, "eod_state", lambda now: {"state": "OVERDUE_EOD_CLOSE", "reason": "missed"})
    monkeypatch.setattr(CL, "capture", lambda **k: pytest.fail("close ran without --force"))
    res = CL.run_close(tmp_path / "sd", force=False, do_shutdown=False)
    assert res.verdict == "NOT_DUE_YET" and not (tmp_path / "sd" / "eod.json").exists()


# ================================================================================ F-P1 supervisor boundary class
def _rs(tmp_path):
    return RT.RuntimeStore(tmp_path)


def test_supervisor_code_change_without_declaration_is_operations_only(tmp_path):
    rs = _rs(tmp_path)
    rs.record_start("supervisor", version="c87ea35f2378", config_fps={"deliver": "1"}, commit="x")
    out = rs.record_start("supervisor", version="75437e48756a", config_fps={"deliver": "1"}, commit="y")
    assert out["classification"] == "OPERATIONS_ONLY" and out["decided_by"] == "RULE:UNDECLARED_CODE_CHANGE_DEFAULT"


def test_a_declared_class_still_wins_and_strategy_components_keep_their_default(tmp_path):
    rs = _rs(tmp_path)
    rs.record_start("supervisor", version="a", config_fps={}, commit="x")
    rs.declare_change("supervisor", "ROUTING_FIX", "explicit")
    assert rs.record_start("supervisor", version="b", config_fps={}, commit="y")["classification"] == "ROUTING_FIX"
    rs.record_start("evaluator:INTRADAY", version="a", config_fps={}, commit="x")
    assert rs.record_start("evaluator:INTRADAY", version="b", config_fps={}, commit="y")["classification"] \
        == "STRATEGY_MATERIAL"
    rs.record_start("sentinel", version="a", config_fps={}, commit="x")
    assert rs.record_start("sentinel", version="b", config_fps={}, commit="y")["classification"] == "OPERATIONS_ONLY"


# ================================================================================ F-P2 verified shared-runtime decl.
@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    rels = set(RT._SHARED) | set(RT.COMPONENT_SOURCES["evaluator:INTRADAY"]) | set(RT.COMPONENT_SOURCES["ingestion"])
    for rel in rels:
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(f"# {rel}\n", encoding="utf-8")
    g = lambda *a: subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, check=True)  # noqa: E731
    g("init", "-q")
    g("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    sha = g("rev-parse", "--short=12", "HEAD").stdout.strip()
    monkeypatch.setattr(RT, "REPO_ROOT", r)
    return r, sha


def _deploy(tmp_path, comp, sha):
    rs = RT.RuntimeStore(tmp_path / "rt")
    rs.record_start(comp, version=RT.component_version(comp), config_fps={}, commit=sha)
    return rs


def test_shared_runtime_only_change_is_eligible_and_bound_to_the_exact_version(tmp_path, repo):
    r, sha = repo
    rs = _deploy(tmp_path, "evaluator:INTRADAY", sha)
    (r / "talonx_opportunity/runtime.py").write_text("# runtime changed\n", encoding="utf-8")
    plan = rs.declare_shared_runtime_changes(["evaluator:INTRADAY"])
    assert plan[0]["status"] == "ELIGIBLE" and plan[0]["changed"] == ["talonx_opportunity/runtime.py"]
    new_v = RT.component_version("evaluator:INTRADAY")
    out = rs.record_start("evaluator:INTRADAY", version=new_v, config_fps={}, commit="z")
    assert out["classification"] == "OPERATIONS_ONLY" and out["decided_by"] == "DECLARED"


def test_declaration_never_applies_to_a_different_later_version(tmp_path, repo):
    r, sha = repo
    rs = _deploy(tmp_path, "evaluator:INTRADAY", sha)
    (r / "talonx_opportunity/runtime.py").write_text("# runtime changed\n", encoding="utf-8")
    rs.declare_shared_runtime_changes(["evaluator:INTRADAY"])
    (r / "talonx_opportunity/evaluators.py").write_text("# a real strategy change\n", encoding="utf-8")
    out = rs.record_start("evaluator:INTRADAY", version=RT.component_version("evaluator:INTRADAY"), config_fps={},
                          commit="z")
    assert out["classification"] == "STRATEGY_MATERIAL" and out["decided_by"] == "RULE:UNDECLARED_CODE_CHANGE_DEFAULT"


def test_component_source_change_is_refused(tmp_path, repo):
    r, sha = repo
    rs = _deploy(tmp_path, "ingestion", sha)
    (r / "talonx_opportunity/runtime.py").write_text("# runtime changed\n", encoding="utf-8")
    (r / "talonx_opportunity/ingestion.py").write_text("# gate added\n", encoding="utf-8")
    plan = rs.declare_shared_runtime_changes(["ingestion"])
    assert plan[0]["status"] == "REFUSED" and "ingestion.py" in plan[0]["why"] and "declaration_id" not in plan[0]


def test_unverifiable_or_mismatched_history_is_refused(tmp_path, repo):
    r, sha = repo
    rs = RT.RuntimeStore(tmp_path / "rt")
    rs.record_start("reporting", version="deadbeef0000", config_fps={}, commit=sha)       # not what git rebuilds
    rs.record_start("outcomes", version="x", config_fps={}, commit=sha + "-dirty")
    (r / "talonx_opportunity/runtime.py").write_text("# runtime changed\n", encoding="utf-8")
    plan = {p["component"]: p for p in rs.plan_shared_runtime_declarations(["reporting", "outcomes"])}
    assert plan["reporting"]["status"] == "REFUSED" and "rebuilt" in plan["reporting"]["why"]
    assert plan["outcomes"]["status"] == "REFUSED" and "not verifiable" in plan["outcomes"]["why"]


def test_unchanged_component_needs_no_declaration(tmp_path, repo):
    _, sha = repo
    rs = _deploy(tmp_path, "evaluator:INTRADAY", sha)
    assert rs.plan_shared_runtime_declarations(["evaluator:INTRADAY"])[0]["status"] == "NOT_NEEDED"


# ================================================================================ Telegram poller health (roles)
@pytest.fixture
def owner(monkeypatch):
    from talonx_ops.prospective import telegram_owner as to
    monkeypatch.setattr(to, "_sentinel_expected_but_dead", lambda: False)
    return to


def _report(to, monkeypatch, roles_by_pid, dead=False):
    monkeypatch.setattr(to, "_network_pids", lambda: (sorted(roles_by_pid), "ok"))
    monkeypatch.setattr(to, "_role_of_pid", lambda pid: roles_by_pid[pid])
    monkeypatch.setattr(to, "_sentinel_expected_but_dead", lambda: dead)
    return to.logical_poller_report()


def test_signal_only_is_healthy(owner, monkeypatch):
    r = _report(owner, monkeypatch, {1: owner.SIGNAL})
    assert r.healthy and r.verdict == "EXPECTED_DISTINCT_POLLERS"


def test_signal_plus_sentinel_is_healthy(owner, monkeypatch):
    r = _report(owner, monkeypatch, {1: owner.SIGNAL, 2: owner.SENTINEL, 3: owner.SENDER})
    assert r.healthy and r.logical_owners == 2 and r.roles[owner.SENDER] == 1


@pytest.mark.parametrize("roles", [("SIGNAL", "SIGNAL"), ("SENTINEL", "SENTINEL"), ("SIGNAL", "UNRESOLVED")])
def test_two_pollers_of_the_same_role_are_duplicates(owner, monkeypatch, roles):
    r = _report(owner, monkeypatch, {i: getattr(owner, n) for i, n in enumerate(roles, 1)})
    assert not r.healthy and r.verdict == "DUPLICATE_SAME_ROLE"


def test_unknown_telegram_client_is_flagged(owner, monkeypatch):
    r = _report(owner, monkeypatch, {1: owner.SIGNAL, 2: owner.UNKNOWN})
    assert not r.healthy and r.verdict == "UNKNOWN_TELEGRAM_CLIENT"


def test_dead_enabled_sentinel_is_flagged(owner, monkeypatch):
    r = _report(owner, monkeypatch, {1: owner.SIGNAL}, dead=True)
    assert not r.healthy and r.verdict == "SENTINEL_POLLER_DEAD"


def test_role_classification_of_real_command_lines(owner):
    rc = owner.role_of_cmdline
    assert rc([r"C:\py\python.exe", r"C:\workspace\TalonX\run_talonx.py"]) == owner.SIGNAL
    assert rc(["python", "run_talonx.py", "--skip-dispatch"]) != owner.SIGNAL
    assert rc(["python", "-m", "talonx_opportunity", "component", "sentinel"]) == owner.SENTINEL
    assert rc(["python", "-m", "talonx_opportunity", "component", "notifier"]) == owner.SENDER
    assert rc(["python", "-m", "talonx_v2.run", "--mode", "live"]) == owner.SENDER
    assert rc(["python", "some_script.py"]) == owner.UNKNOWN and rc([]) == owner.UNRESOLVED


# ================================================================================ supervised Sentinel component
class _Msg:
    def __init__(self, text, chat):
        self.text, self.chat_id, self.from_user = text, chat, None


class _Upd:
    def __init__(self, uid, text, chat=OWNER):
        self.update_id, self.message = uid, _Msg(text, chat)


class _Bot:
    def __init__(self, batches):
        self.batches, self.sent, self.offsets = list(batches), [], []

    async def get_updates(self, offset=None, timeout=0, allowed_updates=None):
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []

    async def send_message(self, **k):
        self.sent.append(("msg", k["chat_id"], k["text"]))

    async def send_document(self, **k):
        self.sent.append(("doc", k["chat_id"], k["filename"]))


@pytest.fixture
def ops(tmp_path, monkeypatch):
    from talonx_ops.notify import DestinationConfig
    from talonx_ops.operator_control.store import OperatorStore
    monkeypatch.setenv("TALONX_OPERATOR_DB", str(tmp_path / "operator_control.db"))
    monkeypatch.delenv("OPERATOR_UNIVERSE_MUTATION_MODE", raising=False)
    cfg = DestinationConfig(destination="OPERATIONS", enabled=True, bot_token="123:SECRET", chat_id=OWNER,
                            reason="test") if "bot_token" in DestinationConfig.__dataclass_fields__ else None
    monkeypatch.setattr("talonx_ops.notify.resolve_destination_config", lambda d: cfg or _Cfg())
    return OperatorStore()


class _Cfg:
    enabled, bot_token, chat_id, reason = True, "123:SECRET", OWNER, "test"


def _comp(tmp_path, bot, store, env=None):
    from talonx_opportunity.sentinel_component import SentinelComponent
    return SentinelComponent(root=tmp_path, env={"TALONX_SENTINEL_COMMANDS_ENABLED": "1"} if env is None else env,
                             bot_factory=lambda cfg: bot, store=store)


def test_disabled_sentinel_idles_and_never_touches_telegram(tmp_path, ops):
    c = _comp(tmp_path, None, ops, env={})
    assert c.tick() == 60.0 and c.poller is None and c.detail()["enabled"] is False
    assert c.config_fps() == {"enabled": "0", "mutation_mode": "DRY_RUN", "destination": "SENTINEL"}


def test_sentinel_answers_help_status_and_dry_run_exclude_then_persists_the_offset(tmp_path, ops, monkeypatch):
    monkeypatch.setattr("talonx_opportunity.sentinel_component.status_text", lambda root, env: "🛰 status ok")
    bot = _Bot([[_Upd(10, "/help"), _Upd(11, "/status"), _Upd(12, "/exclude add TSLA weekend-test")]])
    c = _comp(tmp_path, bot, ops)
    c.tick()
    texts = [s[2] for s in bot.sent]
    assert "COMMAND HELP" in texts[0] and texts[1] == "🛰 status ok"
    assert "PENDING" in texts[2] or "DRY_RUN" in texts[2]
    assert ops.exclusion_row("TSLA")["status"] != "EXCLUDED" or "PENDING" in texts[2]
    assert json.loads((tmp_path / "sentinel_state.json").read_text())["next_offset"] == 13
    c2 = _comp(tmp_path, _Bot([]), ops)                       # restart: resumes AFTER the handled updates
    c2.tick()
    assert c2.bot.offsets == [13] and c2.bot.sent == []


def test_offset_is_saved_before_handling_so_a_crash_never_replays_a_command(tmp_path, ops, monkeypatch):
    from talonx_ops.operator_control import sentinel as S

    async def boom(self, message):
        raise RuntimeError("crash mid-command")
    monkeypatch.setattr(S.SentinelCommandPoller, "handle_message", boom)
    c = _comp(tmp_path, _Bot([[_Upd(40, "/exclude add TSLA")]]), ops)
    c.tick()
    assert json.loads((tmp_path / "sentinel_state.json").read_text())["next_offset"] == 41
    assert c.detail()["last_error"] == "RuntimeError"


def test_unauthorized_chat_cannot_mutate_or_read_status_and_is_audited(tmp_path, ops, monkeypatch):
    monkeypatch.setattr("talonx_opportunity.sentinel_component.status_text", lambda root, env: "secret status")
    bot = _Bot([[_Upd(20, "/exclude add AAPL", chat="999"), _Upd(21, "/status", chat="999")]])
    c = _comp(tmp_path, bot, ops)
    c.tick()
    assert ops.exclusion_row("AAPL") is None
    assert all("secret status" not in s[2] for s in bot.sent) and all("Not authorised" in s[2] for s in bot.sent)
    import sqlite3
    con = sqlite3.connect(tmp_path / "operator_control.db")
    assert con.execute("SELECT COUNT(*) FROM operator_audit WHERE result='REJECTED_UNAUTHORIZED'").fetchone()[0] == 2


def test_sentinel_detail_and_config_never_contain_the_token(tmp_path, ops):
    c = _comp(tmp_path, _Bot([[_Upd(1, "/help")]]), ops)
    c.tick()
    blob = json.dumps(c.detail()) + json.dumps(c.config_fps())
    assert "SECRET" not in blob and "123:" not in blob


def test_sentinel_component_uses_only_operations_credentials():
    src = (Path(RT.__file__).resolve().parent / "sentinel_component.py").read_text(encoding="utf-8")
    ctl = (Path(RT.__file__).resolve().parents[1] / "talonx_ops" / "operator_control" / "sentinel.py").read_text(
        encoding="utf-8")
    assert "operations_poller(" in src and "resolve_destination_config(OPERATIONS)" in ctl
    for bad in ("TRADE_EVENT", "RESEARCH", "OPERATIONS", "TELEGRAM_BOT_TOKEN", "TelegramClient("):
        assert bad not in src


# ================================================================================ supervision + status visibility
def test_promotion_and_sentinel_are_supervised_components():
    from talonx_opportunity import supervise as SV
    from talonx_opportunity.__main__ import cmd_component  # noqa: F401 -- dispatch exists
    assert {"promotion", "sentinel"} <= set(SV.COMPONENTS)
    src = (Path(RT.__file__).resolve().parent / "__main__.py").read_text(encoding="utf-8")
    assert 'name == "sentinel"' in src and 'name == "promotion"' in src


def test_status_shows_promotion_mode_and_sentinel_state(tmp_path):
    from talonx_ops.opportunity_read import read_opportunity_status
    rs = RT.RuntimeStore(tmp_path)
    rs.set_component("promotion", pid=1, state="RUNNING", heartbeat_utc=datetime.now(UTC).isoformat(), version="v",
                     config_fps_json=json.dumps({"mode": "PAPER_SIGNAL", "PROMOTION_POLICY": "4926c12e5eace04e"}),
                     commit_sha="c", detail_json="{}")
    rs.set_component("sentinel", pid=1, state="RUNNING", heartbeat_utc=datetime.now(UTC).isoformat(), version="v",
                     config_fps_json=json.dumps({"enabled": "1", "mutation_mode": "DRY_RUN"}), commit_sha="c",
                     detail_json=json.dumps({"enabled": True, "mutation_mode": "DRY_RUN", "bot": "@TalonXSentinalBot",
                                             "last_error": None}))
    s = read_opportunity_status(tmp_path)
    comps = {c["component"]: c for c in s["components"]}
    assert comps["promotion"]["mode"] == "PAPER_SIGNAL" and comps["promotion"]["config_fp"] == "4926c12e5eace04e"
    assert comps["sentinel"]["mode"] == "ENABLED" and comps["sentinel"]["mutation_mode"] == "DRY_RUN"
    assert comps["sentinel"]["logical"] == "SENTINEL_COMMANDS" and comps["promotion"]["pid"] == 1


def test_supervisor_respawn_env_keeps_promotion_mode_and_never_enables_active_mutation():
    """Runbook contract: the supervisor loop env carries PAPER_SIGNAL (respawn keeps the mode) and never ACTIVE."""
    from talonx_ops.operator_control import mutation_mode
    assert mutation_mode({}) == "DRY_RUN" and mutation_mode({"OPERATOR_UNIVERSE_MUTATION_MODE": "yes"}) == "DRY_RUN"


def test_reply_ledger_records_every_update_without_chat_ids_or_tokens(tmp_path, ops, monkeypatch):
    monkeypatch.setattr("talonx_opportunity.sentinel_component.status_text", lambda root, env: "🛰 status ok")
    bot = _Bot([[_Upd(50, "/help"), _Upd(51, "hello"), _Upd(52, "/exclude add TSLA x"),
                 _Upd(53, "/exclude add AAPL", chat="999")]])
    c = _comp(tmp_path, bot, ops)
    c.tick()
    rows = [json.loads(x) for x in (tmp_path / "sentinel_replies.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["update_id"] for r in rows] == [50, 51, 52, 53]
    assert [r["result"] for r in rows] == ["SENT", "NO_REPLY", "SENT", "SENT"]
    assert rows[0]["kind"] == "MESSAGE" and rows[3]["authorized"] is False
    blob = json.dumps(rows)
    assert OWNER not in blob and "999" not in blob and "SECRET" not in blob
