"""Task 81-R1 §4 -- missing / unusable session identity recovery.

Reproduces: lifecycle_state.json contains an OPEN position but
session_identity.json is ABSENT. Pre-fix, assess_session_recovery returns
FRESH_SESSION_CLEAN and resolve_session_identity mints a brand-new,
authorization-bound identity around the unresolved exposure.

Required: a missing / corrupt / incomplete identity WITH unresolved
exposure / orders / intents is RECOVERY_REQUIRED; existing evidence is
preserved (no identity minted or written); assessment mode / reasons /
unresolved_exposure agree; CLI start/supervise refuse and explain; and
the existing runtime/config/feed/date binding requirements are unchanged.

Frozen `now`; per-test tmp_path; no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.session_identity import (
    FRESH_SESSION_CLEAN, RECOVERY_REQUIRED, RESUME_SAME_SESSION, SessionRecoveryRequired,
    assess_session_recovery, build_session_identity, compute_config_hash, resolve_session_identity,
)

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
TODAY_ET = "2026-08-28"


def _cfg(tmp_path, **o):
    v = dict(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
             broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
             universe=("AAPL", "MSFT"), feed_mode="IEX_PAPER_PIV")
    v.update(o)
    return PivConfig(**v)


def _write_lifecycle(tmp_path, **over):
    state = {
        "session_enabled": True, "kill_switch": False,
        "positions": {}, "orders": {}, "intents": {},
    }
    state.update(over)
    (tmp_path / "lifecycle_state.json").write_text(json.dumps(state), encoding="utf-8")


_OPEN_POS = {"pos_AAPL": {"symbol": "AAPL", "status": "OPEN", "quantity": 2, "remaining_quantity": 2,
                          "stop_price": 95.0, "target_price": 110.0}}
_PENDING_INTENT = {"i1": {"status": "ORDER_INTENT", "payload": {"symbol": "AAPL", "side": "buy", "qty": "1"}}}
_UNCERTAIN_INTENT = {"i2": {"status": "SUBMIT_FAILED_UNCERTAIN", "payload": {"symbol": "AAPL", "side": "buy", "qty": "1"}}}


# ---------------------------------------------------------------------------
# Pre-fix reproduction / corrected behaviour
# ---------------------------------------------------------------------------

def test_missing_identity_with_open_position_requires_recovery(tmp_path):
    cfg = _cfg(tmp_path)
    _write_lifecycle(tmp_path, positions=_OPEN_POS)
    assert not (tmp_path / "session_identity.json").exists()

    assessment = assess_session_recovery(cfg, now=NOW)

    assert assessment.mode == RECOVERY_REQUIRED, "absent identity + OPEN position must not be FRESH_SESSION_CLEAN"
    assert assessment.unresolved_exposure is True
    assert any("SESSION_IDENTITY_MISSING" in r for r in assessment.reasons)
    assert any(r.startswith("OPEN_POSITION:AAPL") for r in assessment.reasons)
    assert assessment.identity is None
    assert "eod" in assessment.required_action

    with pytest.raises(SessionRecoveryRequired) as ei:
        resolve_session_identity(cfg, now=NOW)
    assert "SESSION_IDENTITY_MISSING" in " ".join(ei.value.reasons)
    # Existing evidence preserved -- no identity file minted.
    assert not (tmp_path / "session_identity.json").exists()


@pytest.mark.parametrize("intents_key,intents", [("pending", _PENDING_INTENT), ("uncertain", _UNCERTAIN_INTENT)])
def test_corrupt_identity_with_pending_or_uncertain_order_requires_recovery(tmp_path, intents_key, intents):
    cfg = _cfg(tmp_path)
    _write_lifecycle(tmp_path, intents=intents)
    (tmp_path / "session_identity.json").write_text("{ not valid json", encoding="utf-8")

    assessment = assess_session_recovery(cfg, now=NOW)
    assert assessment.mode == RECOVERY_REQUIRED
    assert any("SESSION_IDENTITY_CORRUPT" in r for r in assessment.reasons)

    with pytest.raises(SessionRecoveryRequired):
        resolve_session_identity(cfg, now=NOW)
    # The corrupt file is NOT overwritten.
    assert (tmp_path / "session_identity.json").read_text() == "{ not valid json"


def test_recovery_required_does_not_write_identity(tmp_path):
    cfg = _cfg(tmp_path)
    _write_lifecycle(tmp_path, positions=_OPEN_POS)
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(SessionRecoveryRequired):
        resolve_session_identity(cfg, now=NOW)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert "session_identity.json" not in after
    assert before == after


def test_assessment_fields_are_consistent(tmp_path):
    cfg = _cfg(tmp_path)
    # missing identity, incomplete EOD, no exposure
    _write_lifecycle(tmp_path, session_enabled=False)
    (tmp_path / "eod_state.json").write_text(
        json.dumps({"trading_date_et": TODAY_ET, "status": "INCONCLUSIVE"}), encoding="utf-8",
    )
    a = assess_session_recovery(cfg, now=NOW)
    assert a.mode == RECOVERY_REQUIRED
    assert a.unresolved_exposure is False           # no position/order/intent -- only EOD
    assert any("EOD_NOT_COMPLETE" in r for r in a.reasons)
    assert any("SESSION_IDENTITY_MISSING" in r for r in a.reasons)
    # A FRESH_SESSION_CLEAN result never carries unresolved_exposure=True.
    _write_lifecycle(tmp_path, session_enabled=False)
    (tmp_path / "eod_state.json").write_text(json.dumps({"trading_date_et": TODAY_ET, "status": "PASSED"}), encoding="utf-8")
    b = assess_session_recovery(cfg, now=NOW)
    assert b.mode == FRESH_SESSION_CLEAN and b.unresolved_exposure is False


# ---------------------------------------------------------------------------
# Coverage matrix
# ---------------------------------------------------------------------------

def _mint_identity(tmp_path, cfg, *, runtime_sha="sha-old", now=NOW, **over):
    with patch("talonx_piv.session_identity.runtime_sha", return_value=runtime_sha):
        ident = build_session_identity(cfg, now=now)
    d = ident.to_dict()
    d.update(over)
    (tmp_path / "session_identity.json").write_text(json.dumps(d), encoding="utf-8")
    return ident


def test_recovery_matrix(tmp_path):
    cfg = _cfg(tmp_path)

    # 1. genuinely clean startup -- nothing on disk
    assert assess_session_recovery(cfg, now=NOW).mode == FRESH_SESSION_CLEAN

    # 2. missing identity + open position -> RECOVERY_REQUIRED
    _write_lifecycle(tmp_path, positions=_OPEN_POS)
    assert assess_session_recovery(cfg, now=NOW).mode == RECOVERY_REQUIRED

    # 3. missing identity + orphan ORDER_INTENT -> RECOVERY_REQUIRED
    _write_lifecycle(tmp_path, intents=_PENDING_INTENT)
    assert assess_session_recovery(cfg, now=NOW).mode == RECOVERY_REQUIRED

    # 4. corrupt identity + uncertain submission -> RECOVERY_REQUIRED
    _write_lifecycle(tmp_path, intents=_UNCERTAIN_INTENT)
    (tmp_path / "session_identity.json").write_text("nope", encoding="utf-8")
    assert assess_session_recovery(cfg, now=NOW).mode == RECOVERY_REQUIRED
    (tmp_path / "session_identity.json").unlink()

    # 5. incomplete EOD, no exposure -> RECOVERY_REQUIRED
    _write_lifecycle(tmp_path, session_enabled=False)
    (tmp_path / "eod_state.json").write_text(json.dumps({"trading_date_et": TODAY_ET, "status": "PENDING"}), encoding="utf-8")
    assert assess_session_recovery(cfg, now=NOW).mode == RECOVERY_REQUIRED
    (tmp_path / "eod_state.json").unlink()

    # 6. unchanged-binding restart into a still-live session -> RESUME
    _write_lifecycle(tmp_path, session_enabled=True, positions=_OPEN_POS)
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-r"):
        _mint_identity(tmp_path, cfg, runtime_sha="sha-r")
        assert assess_session_recovery(cfg, now=NOW).mode == RESUME_SAME_SESSION

    # 7. genuinely clean fresh start after a flat, EOD-complete prior session
    _write_lifecycle(tmp_path, session_enabled=False)
    (tmp_path / "eod_state.json").write_text(json.dumps({"trading_date_et": TODAY_ET, "status": "PASSED"}), encoding="utf-8")
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-r"):
        assert assess_session_recovery(cfg, now=NOW).mode == FRESH_SESSION_CLEAN


def test_binding_requirements_unchanged(tmp_path):
    """A wellformed identity whose runtime_sha no longer matches, WITH open
    exposure, still requires recovery (Task 81 §3 behaviour, unchanged)."""
    cfg = _cfg(tmp_path)
    _write_lifecycle(tmp_path, session_enabled=True, positions=_OPEN_POS)
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        _mint_identity(tmp_path, cfg, runtime_sha="sha-old")
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-NEW"):
        a = assess_session_recovery(cfg, now=NOW)
    assert a.mode == RECOVERY_REQUIRED
    assert any("runtime_sha" in r for r in a.reasons)


# ---------------------------------------------------------------------------
# CLI refusal
# ---------------------------------------------------------------------------

def test_cli_start_refuses_on_missing_identity_with_exposure(tmp_path, capsys, monkeypatch):
    from talonx_piv import cli
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    _write_lifecycle(tmp_path, positions=_OPEN_POS)

    rc = cli.main(["start", "--approved-sha", "abc", "--no-live-loop"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "PIV_BLOCKED_RECOVERY_REQUIRED" in err
    assert "SESSION_IDENTITY_MISSING" in err
    assert not (tmp_path / "session_identity.json").exists()
