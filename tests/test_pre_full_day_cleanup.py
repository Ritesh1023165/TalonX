"""Pre-full-day operational cleanup (after the partial-day RC1 canary).

  1. stale TEST-fixture RECONCILIATION_FAILURE rows must never again reach the real Sentinel channel:
       tests cannot write the shared/release ops outbox; the release owns its own isolated outbox; the release gate refuses a
       start while that outbox holds foreign rows;
  2. Telegram bot tokens / API secrets must never be written to logs (request log, failure log, exception text);
  3. compromised credentials block a release start until rotated (fingerprint-only, one-way);
  4. Sentinel STARTUP carries the real campaign id; STARTUP/SHUTDOWN notices are time-bound.

Everything uses temp DBs and RecordingTransport -- NO real Telegram send, no network."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import test_v2_final_release_acceptance as acc
import talonx_ops.log_redaction as lr
from talonx_ops.notify import OPERATIONS, RESEARCH, TRADE_EVENT, resolve_destination_config
from talonx_ops.notify.outbox import NotifyStore
from talonx_ops.notify.producers import enqueue_lifecycle_event, enqueue_reconciliation_failure
from talonx_ops.notify.worker import drain
from talonx_v2 import release_gate as rg
from talonx_v2.delivery import RecordingTransport
from talonx_v2.store import V2Store

REPO = Path(__file__).resolve().parents[1]
FAKE_TOKEN = "1234567890:AAH-fake_TOKEN_value_0123456789abcdefgh"          # obviously fake, well-formed
FAKE_SECRET = "psk_live_FAKE_alpaca_secret_9f8e7d6c5b4a"
RC1 = rg.RELEASE_PROFILE.campaign_id


def _clean_notify_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("TALONX_NOTIFY_") or k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            monkeypatch.delenv(k, raising=False)


# =========================================================================== #
# 1. tests cannot write the shared / release ops outbox
# =========================================================================== #
def test_01_test_execution_cannot_populate_the_shared_or_release_notification_store(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod
    shared = REPO / "notifications.db"
    before = (shared.stat().st_size, shared.stat().st_mtime_ns) if shared.exists() else None
    # the EXACT flow that polluted the production outbox in the canary (fixture ledger + a failing reconciliation assert)
    db = tmp_path / "v2_lane.db"
    V2Store(str(db), starting_cash=300_000.0)
    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    close_mod._record_v2_reconciliation_blocks({"cash_plus_open_cost_reconciles": "FAIL"}, ["cash_plus_open_cost_reconciles: FAIL some detail"])
    after = (shared.stat().st_size, shared.stat().st_mtime_ns) if shared.exists() else None
    assert after == before                                                                    # the shared outbox was not touched
    assert Path(os.environ["TALONX_NOTIFY_DB_PATH"]).parent != REPO                           # default store is a per-test temp file
    tmp_store = close_mod._default_ops_notify_store()
    assert [r["event_type"] for r in tmp_store.all_outbox(destination=OPERATIONS)] == ["RECONCILIATION_FAILURE"]   # the row went to the temp store
    # even if a test scrubs the env var (as some notification tests do) the shared/release outbox is unreachable
    monkeypatch.delenv("TALONX_NOTIFY_DB_PATH", raising=False)
    for forbidden in (shared, REPO / rg.RELEASE_PROFILE.notify_db_filename, "notifications.db"):
        with pytest.raises(RuntimeError, match="must not open"):
            NotifyStore(str(forbidden))


# =========================================================================== #
# 2-4, 10. release outbox isolation, RC1 drain, stale rows, restart
# =========================================================================== #
def _gate_with_outbox(tmp_path, outbox_path, **env_over):
    env, vp = acc.good_env(tmp_path)
    env["TALONX_NOTIFY_DB_PATH"] = str(outbox_path)
    env.update(env_over)
    return acc.gate(tmp_path, env=env, vpath=vp)


def _mk_release_outbox(tmp_path, monkeypatch):
    """Create the release outbox at its release filename WITHOUT tripping the test guard (the guard protects the REPO paths only)."""
    return tmp_path / rg.RELEASE_PROFILE.notify_db_filename


def test_02_release_gate_requires_the_isolated_release_outbox_and_refuses_the_shared_default(tmp_path):
    ok = _gate_with_outbox(tmp_path, tmp_path / rg.RELEASE_PROFILE.notify_db_filename)
    assert "release_notification_store" not in {c.name for c in ok.failed}
    shared = _gate_with_outbox(tmp_path, tmp_path / "notifications.db")
    assert "release_notification_store" in {c.name for c in shared.failed}
    other = _gate_with_outbox(tmp_path, tmp_path / "something_else.db")
    assert "release_notification_store" in {c.name for c in other.failed}
    env, vp = acc.good_env(tmp_path)
    env.pop("TALONX_NOTIFY_DB_PATH")                                                        # unset -> shared default -> refused
    assert "release_notification_store" in {c.name for c in acc.gate(tmp_path, env=env, vpath=vp).failed}


def test_03_release_drain_ignores_foreign_rows_and_the_gate_refuses_a_contaminated_outbox(tmp_path):
    path = tmp_path / rg.RELEASE_PROFILE.notify_db_filename
    store = NotifyStore(str(path))
    # a stale TEST-FIXTURE row exactly as the canary saw it (campaign "V2", episode ep1, 12.5 shares)
    enqueue_reconciliation_failure(store, campaign_id="V2", findings=["whole_share_positions: [('ep1', 12.5)]"], reference="c96ec5ab")
    rep = _gate_with_outbox(tmp_path, path)
    assert "release_notification_store" in {c.name for c in rep.failed}                     # the start is refused, nothing drains
    detail = {c.name: c.detail for c in rep.checks}["release_notification_store"]
    assert "RECONCILIATION_FAILURE" in detail and "campaign=V2" in detail


def test_04_real_rc1_notifications_still_drain_normally(tmp_path, monkeypatch):
    _clean_notify_env(monkeypatch)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    store = NotifyStore(str(tmp_path / rg.RELEASE_PROFILE.notify_db_filename))
    assert enqueue_lifecycle_event(store, event_type="STARTUP", campaign_id=RC1, detail="prospective start")
    enqueue_reconciliation_failure(store, campaign_id=RC1, findings=["cash_plus_open_cost_reconciles: real RC1 finding"], reference="r1")
    client = RecordingTransport()
    res = drain(store, destination=OPERATIONS, client=client)
    assert res["sent"] == 2 and res["failed"] == 0 and len(client.sent) == 2
    assert all(RC1 in str(m) for m in client.sent)
    # RC1 rows are accepted by the gate too
    rep = _gate_with_outbox(tmp_path, tmp_path / rg.RELEASE_PROFILE.notify_db_filename)
    assert "release_notification_store" not in {c.name for c in rep.failed}


def test_05_stale_pre_rc1_rows_in_the_shared_store_cannot_emit_at_release_startup(tmp_path, monkeypatch):
    _clean_notify_env(monkeypatch)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    legacy = NotifyStore(str(tmp_path / "legacy_shared_notifications.db"))                   # stands in for the polluted shared file
    for d in ("2026-09-18", "2026-09-19", "2026-09-21"):
        enqueue_reconciliation_failure(legacy, campaign_id="V2", findings=["cash_plus_open_cost_reconciles: FAIL some detail"], reference=d)
    assert len(legacy.outbox_due(now_iso=datetime.now(timezone.utc).isoformat(), destination=OPERATIONS)) == 3
    release = NotifyStore(str(tmp_path / rg.RELEASE_PROFILE.notify_db_filename))              # the release drains ONLY its own outbox
    client = RecordingTransport()
    res = drain(release, destination=OPERATIONS, client=client)
    assert res["considered"] == 0 and client.sent == []
    assert len(legacy.outbox_due(now_iso=datetime.now(timezone.utc).isoformat(), destination=OPERATIONS)) == 3   # untouched


def test_06_isolation_survives_restart(tmp_path):
    path = tmp_path / rg.RELEASE_PROFILE.notify_db_filename
    NotifyStore(str(path)).enqueue(event_id="e1", destination=OPERATIONS, event_type="X", producer="t", dedup_key="k",
                                   payload_text="p", provenance={"campaign_id": "V2-OTHER"})
    reopened = NotifyStore(str(path))                                                        # "restart": a fresh object on the same file
    assert [r["event_id"] for r in reopened.all_outbox()] == ["e1"]
    rep = _gate_with_outbox(tmp_path, path)
    assert "release_notification_store" in {c.name for c in rep.failed}                     # contamination is still detected after restart
    with pytest.raises(RuntimeError, match="must not open"):
        NotifyStore(str(REPO / "notifications.db"))


# =========================================================================== #
# 5-7. secrets never reach logs
# =========================================================================== #
@pytest.fixture()
def log_capture(monkeypatch):
    monkeypatch.setenv("APCA_API_SECRET_KEY", FAKE_SECRET)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", FAKE_TOKEN)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    lg = logging.getLogger("talonx_test_redaction")
    lg.setLevel(logging.DEBUG); lg.addHandler(h); lg.propagate = False
    yield lg, buf
    lg.removeHandler(h)


def test_07_telegram_token_is_absent_from_request_and_failure_logs(log_capture):
    lg, buf = log_capture
    lg.info('HTTP Request: POST https://api.telegram.org/bot%s/sendMessage "HTTP/1.1 200 OK"', FAKE_TOKEN)
    lg.warning("telegram send failed url=https://api.telegram.org/bot" + FAKE_TOKEN + "/getUpdates?chat_id=-1001234567890&timeout=30")
    out = buf.getvalue()
    assert FAKE_TOKEN not in out and FAKE_TOKEN.split(":")[1] not in out
    assert "api.telegram.org/bot[REDACTED]/sendMessage" in out
    assert "-1001234567890" not in out                                                       # chat id treated as sensitive


def test_08_telegram_token_is_absent_from_exception_text(log_capture):
    lg, buf = log_capture
    try:
        raise RuntimeError(f"NetworkError: POST https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage failed")
    except RuntimeError:
        lg.exception("delivery failed")
    out = buf.getvalue()
    assert "Traceback" in out and FAKE_TOKEN not in out and FAKE_TOKEN.split(":")[1] not in out
    lg.error("stack", stack_info=True)
    assert FAKE_TOKEN not in buf.getvalue()


def test_09_provider_and_generic_secrets_are_absent_from_the_same_logging_path(log_capture):
    lg, buf = log_capture
    lg.info("alpaca request headers=%s", {"APCA-API-KEY-ID": "PKABCDEFGHIJ1234", "APCA-API-SECRET-KEY": FAKE_SECRET})
    lg.info("Authorization: Bearer abcdef0123456789abcdef and api_key=k_live_0123456789 and password=hunter2hunter2")
    lg.info("free text with the raw secret %s embedded", FAKE_SECRET)                        # exact env value, unusual position
    out = buf.getvalue()
    for leaked in (FAKE_SECRET, "PKABCDEFGHIJ1234", "abcdef0123456789abcdef", "k_live_0123456789", "hunter2hunter2"):
        assert leaked not in out, leaked
    assert lr.REDACTED in out


def test_10_redaction_is_process_wide_and_httpx_is_quiet():
    assert logging.getLogRecordFactory().__name__ == "factory"                                # installed for EVERY logger/handler
    assert logging.getLogger("httpx").level >= logging.WARNING and logging.getLogger("httpcore").level >= logging.WARNING
    assert lr.redact("no secrets here") == "no secrets here"
    assert lr.secret_fingerprint(FAKE_TOKEN) == hashlib.sha256(FAKE_TOKEN.encode()).hexdigest()[:12]


def test_11_every_release_entry_point_installs_redaction_before_logging():
    for rel in ("talonx_v2/run.py", "talonx_ops/supervisor.py", "talonx_dispatch/run.py", "talonx_dispatch/telegram_client.py",
                "talonx_ops/notify/__init__.py", "talonx_ops/logging_setup.py"):
        assert "import talonx_ops.log_redaction" in (REPO / rel).read_text(encoding="utf-8"), rel


# =========================================================================== #
# credential rotation: the gate refuses known-compromised tokens (fingerprint only)
# =========================================================================== #
def test_12_gate_refuses_a_still_compromised_token_and_accepts_a_rotated_one(tmp_path):
    env, vp = acc.good_env(tmp_path)
    old_token = "1111111111:AA-old_compromised_token_value_ABCDEFGH"
    prof = rg.ReleaseProfile(compromised_secret_fingerprints=(lr.secret_fingerprint(old_token),))
    def run(e):
        return rg.evaluate_release_readiness(db_path=tmp_path / "none.db", pricing_mode="sip", deliver=True, transport="telegram", env=e,
                                             http_get=acc._Ready(), now=lambda: acc.clk(acc.date(2026, 10, 5)), validation_path=vp, profile=prof)
    stale = run(dict(env, TELEGRAM_BOT_TOKEN=old_token))
    assert "compromised_credentials_rotated" in {c.name for c in stale.failed}
    detail = {c.name: c.detail for c in stale.checks}["compromised_credentials_rotated"]
    assert "ROTATION_REQUIRED" in detail and old_token not in json.dumps(stale.to_dict())     # fingerprint-only, never the value
    rotated = run(dict(env, TELEGRAM_BOT_TOKEN="2222222222:AA-brand_new_rotated_token_value_ZYXWVUTS"))
    assert "compromised_credentials_rotated" not in {c.name for c in rotated.failed}


def test_13_the_declared_compromised_fingerprints_are_wellformed_one_way_identifiers():
    fps = rg.RELEASE_PROFILE.compromised_secret_fingerprints
    assert len(fps) == 2 and all(len(f) == 12 and set(f) <= set("0123456789abcdef") for f in fps)


# =========================================================================== #
# startup label + time-bound lifecycle notices
# =========================================================================== #
def test_14_startup_message_uses_the_real_campaign_id(tmp_path, monkeypatch):
    from talonx_ops.prospective.__main__ import _campaign_label
    monkeypatch.setenv("TALONX_V2_CAMPAIGN_ID", RC1)
    assert _campaign_label({"TALONX_V2_STARTING_CASH_USD": "100000"}) == RC1                # resolve_env() dict lacks it -> real env wins
    monkeypatch.delenv("TALONX_V2_CAMPAIGN_ID")
    assert _campaign_label({}) == "V2"                                                       # legacy default unchanged
    store = NotifyStore(str(tmp_path / "n.db"))
    monkeypatch.setenv("TALONX_V2_CAMPAIGN_ID", RC1)
    enqueue_lifecycle_event(store, event_type="STARTUP", campaign_id=_campaign_label({}), detail="prospective start")
    text = store.all_outbox(destination=OPERATIONS)[0]["payload_text"]
    assert f"campaign `{RC1}`" in text and "campaign `V2`" not in text


def test_15_a_stale_shutdown_or_startup_notice_expires_instead_of_being_sent_out_of_order(tmp_path, monkeypatch):
    _clean_notify_env(monkeypatch)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    store = NotifyStore(str(tmp_path / "n.db"))
    enqueue_lifecycle_event(store, event_type="SHUTDOWN", campaign_id=RC1, detail="prospective close")
    row = store.all_outbox()[0]
    assert row["deliver_by_utc"]                                                             # time-bound
    client = RecordingTransport()
    next_day = datetime.now(timezone.utc) + timedelta(hours=20)                             # the next start, a day later
    res = drain(store, destination=OPERATIONS, client=client, now=next_day)
    assert res["expired"] == 1 and client.sent == []                                        # never delivered as "fresh"
    assert store.all_outbox()[0]["state"] == "EXPIRED"


# =========================================================================== #
# campaign verify, routing, Lab, fingerprints, freeze integrity
# =========================================================================== #
def test_16_release_campaign_verification_passes_on_the_clean_campaign(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)                       # never load the real .env into the test process
    db = tmp_path / rg.RELEASE_PROFILE.campaign_db_filename
    rg.init_release_campaign(db)
    assert rg.main(["--verify-campaign", "--db", str(db)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["clean"] is True and out["state"]["settled_cash"] == 100_000.0 and out["state"]["campaign"]["campaign_id"] == RC1


def test_17_signal_sentinel_routing_is_unchanged_and_lab_stays_off(monkeypatch):
    _clean_notify_env(monkeypatch)
    assert (TRADE_EVENT, OPERATIONS, RESEARCH) == ("TRADE_EVENT", "OPERATIONS", "RESEARCH")
    assert resolve_destination_config(RESEARCH).enabled is False                            # Lab OFF, no fallback
    assert rg.RELEASE_PROFILE.lab_enabled is False and rg.RELEASE_PROFILE.signal_destination == "TRADE_EVENT"
    assert rg.RELEASE_PROFILE.sentinel_destination == "OPERATIONS" and rg.RELEASE_PROFILE.lab_destination == "RESEARCH"


def test_18_strategy_and_provider_fingerprints_are_unchanged():
    from talonx_v2 import provider_contract as pc
    assert rg._strategy_fingerprint() == "e2acf6454789217e"
    assert pc.RELEASE_CONTRACT.fingerprint() == "ac5e51aa3599d6c9"
    assert rg.RELEASE_PROFILE.strategy_fingerprint == "e2acf6454789217e" and rg.RELEASE_PROFILE.contract_fingerprint == "ac5e51aa3599d6c9"


def test_19_ops_hardening_allowlist_contains_no_strategy_provider_pricing_or_accounting_file():
    from talonx_ops.prospective.preflight import FREEZE_OPS_HARDENING_FILES as files
    v2 = {Path(f).name for f in files if f.startswith("talonx_v2/")}
    assert v2 == {"release_gate.py", "run.py"}                                              # only the release gate + entry point in the V2 package
    forbidden = ("config.py", "cluster_engine.py", "liquidity", "quant_bridge", "brain_bridge", "pricing", "provider_contract",
                 "sip_adapter", "paper", "store", "pipeline", "corporate_actions", "dividends", "sizing", "calendar")
    assert not [f for f in files if any(x in Path(f).name for x in forbidden)]


def test_20_head_is_the_frozen_release_plus_only_declared_changes():
    from talonx_ops.prospective.preflight import frozen_release_ok
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["git", "cat-file", "-e", "a56ec8c"], cwd=REPO, check=True, capture_output=True)
    except Exception:
        pytest.skip("git history unavailable")
    ok, why = frozen_release_ok(head, "a56ec8c", repo=REPO)
    if not ok and "runtime files changed" in why:
        pytest.fail(why)                                                                     # uncommitted work is not part of this check; committed drift is


# =========================================================================== #
# continuation campaign verify + post-rotation controlled validation command
# =========================================================================== #
def test_21_continuation_verify_allows_only_non_economic_skipped_episode_records(tmp_path):
    db = tmp_path / rg.RELEASE_PROFILE.campaign_db_filename
    rg.init_release_campaign(db)
    con = sqlite3.connect(db)                                                                # the two records the canary left (no trade, no intent)
    con.execute("INSERT INTO processed_episodes(episode_id,symbol,issuer_cik,activation_filing_date,eligible_entry_session,disposition,detail,first_seen_at,updated_at) "
                "VALUES('e1','ABCL','1','', '2026-08-17','SKIPPED_ENTRY_STALE','x','t','t'),('e2','ADC','2','', '2026-09-18','SKIPPED_NO_PRIOR_INTENT','x','t','t')")
    con.commit(); con.close()
    st = rg.campaign_state(db)
    assert st["processed_episodes"] == 2 and st["skipped_episode_records"] == 2
    assert rg.clean_campaign_problems(st)                                                    # fresh-creation rule still strict
    assert rg.clean_campaign_problems(st, allow_skipped_episodes=True) == []                # continuation verify accepts them
    con = sqlite3.connect(db); con.execute("UPDATE processed_episodes SET disposition='ENTERED' WHERE episode_id='e2'"); con.commit(); con.close()
    assert rg.clean_campaign_problems(rg.campaign_state(db), allow_skipped_episodes=True)   # a non-skipped episode is NOT clean


def _validation_env(monkeypatch, tmp_path):
    env, vp = acc.good_env(tmp_path)
    for k in list(os.environ):
        if k.startswith("TALONX_NOTIFY_") or k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        if k.startswith("TALONX_NOTIFY_"):
            monkeypatch.setenv(k, v)
    return env


def test_22_controlled_validation_is_dry_run_by_default_and_never_touches_lab(tmp_path, monkeypatch):
    from talonx_ops.notify.validate import validate
    _validation_env(monkeypatch, tmp_path)
    rec = tmp_path / "rec.json"
    made = []
    res = validate([OPERATIONS, TRADE_EVENT, RESEARCH], record_path=rec, send=False, client_factory=lambda d: made.append(d) or RecordingTransport())
    assert made == [] and not rec.exists()                                                   # dry-run: no client built, nothing sent, nothing written
    assert res["destinations"][OPERATIONS]["result"] == "DRY_RUN" and res["destinations"][TRADE_EVENT]["result"] == "DRY_RUN"
    assert res["destinations"][RESEARCH]["result"] == "REFUSED"


def test_23_controlled_validation_records_a_fingerprint_bound_record_the_gate_accepts_and_leaks_no_secret(tmp_path, monkeypatch):
    from talonx_ops.notify.validate import validate
    env = _validation_env(monkeypatch, tmp_path)
    rec = tmp_path / "rec.json"
    clients = {}
    res = validate([OPERATIONS, TRADE_EVENT], record_path=rec, send=True,
                   client_factory=lambda d: clients.setdefault(d, RecordingTransport()))
    assert res["destinations"][OPERATIONS]["result"] == "SENT" and res["destinations"][TRADE_EVENT]["result"] == "SENT"
    assert len(clients[OPERATIONS].sent) == 1 and len(clients[TRADE_EVENT].sent) == 1        # exactly one harmless notice each, to its own destination
    blob = rec.read_text(encoding="utf-8") + json.dumps(res)
    for secret in ("sig-token-SECRET", "sen-token-SECRET", "sig-chat-SECRET", "sen-chat-SECRET"):
        assert secret not in blob
    record = json.loads(rec.read_text(encoding="utf-8"))
    assert record["kind"] == "ri4_controlled_telegram_validation" and set(record["destinations"]) == {OPERATIONS, TRADE_EVENT}
    def gate_with(e):
        return rg.evaluate_release_readiness(db_path=tmp_path / "none.db", pricing_mode="sip", deliver=True, transport="telegram", env=e,
                                             http_get=acc._Ready(), now=lambda: acc.clk(acc.date(2026, 10, 5)), validation_path=rec)
    assert not {"signal_delivery_validation_bound", "sentinel_delivery_validation_bound"} & {c.name for c in gate_with(env).failed}
    # a rotated Sentinel credential invalidates it again (NEEDS_REVALIDATION); Signal stays valid
    failed = {c.name for c in gate_with(dict(env, TALONX_NOTIFY_OPERATIONS_BOT_TOKEN="rotated-sentinel-token-0123456789")).failed}
    assert "sentinel_delivery_validation_bound" in failed and "signal_delivery_validation_bound" not in failed


def test_24_controlled_validation_refuses_a_still_compromised_token(tmp_path, monkeypatch):
    from talonx_ops.notify.validate import validate
    _validation_env(monkeypatch, tmp_path)
    fps = rg.ReleaseProfile(compromised_secret_fingerprints=(lr.secret_fingerprint("sen-token-SECRET"),))
    monkeypatch.setattr(rg, "RELEASE_PROFILE", fps)
    res = validate([OPERATIONS], record_path=tmp_path / "rec.json", send=True, client_factory=lambda d: RecordingTransport())
    assert res["destinations"][OPERATIONS]["result"] == "REFUSED" and "ROTATION_REQUIRED" in res["destinations"][OPERATIONS]["reason"]
    assert not (tmp_path / "rec.json").exists()
