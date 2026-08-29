"""Task 83-R1 §5 -- authoritative PIV Telegram zero-attempt evidence.

The collector reads the durable, session-scoped
``piv_notification_telemetry.json`` written by the PIV runtime at the
actual send / poller boundaries. It may assert "PIV attempted zero
outbound Telegram sends" ONLY when all three hold:

  1. telemetry EXISTS and is for the PIV session being archived;
  2. outbound is disabled AND inbound poller is disabled (ownership);
  3. every counter is verified zero.

Anything else is ``UNVERIFIED`` -- never silently zero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from talonx_piv.notification_telemetry import TELEMETRY_NAME, load_telemetry

VERIFIED_ZERO = "VERIFIED_ZERO"
UNVERIFIED = "UNVERIFIED"
MISSING = "MISSING"
WRONG_SESSION = "WRONG_SESSION"
ATTEMPTS_RECORDED = "ATTEMPTS_RECORDED"


def assess_piv_notification(state_dir: Path, expected_session_id: str | None) -> dict[str, Any]:
    tel = load_telemetry(Path(state_dir))
    if tel is None:
        return {
            "verdict": MISSING,
            "detail": f"{TELEMETRY_NAME} absent -- PIV notification behaviour is UNVERIFIED, not zero",
            "piv_zero_attempt_assertion": False,
            "telemetry": None,
        }

    tel_session = tel.get("session_id")
    if expected_session_id is not None and tel_session not in (None, expected_session_id):
        return {
            "verdict": WRONG_SESSION,
            "detail": f"telemetry is for session {tel_session!r}, archiving {expected_session_id!r}",
            "piv_zero_attempt_assertion": False,
            "telemetry": tel,
        }

    own = tel.get("ownership", {})
    outbound = tel.get("outbound", {})
    inbound = tel.get("inbound", {})
    outbound_attempts = int(outbound.get("attempts", 0) or 0)
    inbound_starts = int(inbound.get("poll_starts", 0) or 0)

    if outbound_attempts > 0 or inbound_starts > 0:
        return {
            "verdict": ATTEMPTS_RECORDED,
            "detail": (f"outbound attempts={outbound_attempts} "
                       f"(failures={outbound.get('failures', 0)}, successes={outbound.get('successes', 0)}), "
                       f"inbound poll_starts={inbound_starts}"),
            "piv_zero_attempt_assertion": False,
            "telemetry": tel,
        }

    disabled = (
        own.get("outbound_enabled") is False
        and own.get("sender_constructed") is False
        and own.get("inbound_poller_constructed") is False
        and own.get("inbound_poller_started") is False
    )
    counters_zero = (
        outbound_attempts == 0
        and int(outbound.get("failures", 0) or 0) == 0
        and int(outbound.get("successes", 0) or 0) == 0
        and inbound_starts == 0
        and int(inbound.get("poll_attempts", 0) or 0) == 0
    )
    session_match = (expected_session_id is None) or (tel_session == expected_session_id)

    if disabled and counters_zero and session_match:
        return {
            "verdict": VERIFIED_ZERO,
            "detail": "telemetry present for this session; outbound + inbound disabled; all counters zero",
            "piv_zero_attempt_assertion": True,
            "telemetry": tel,
        }
    return {
        "verdict": UNVERIFIED,
        "detail": (f"cannot assert zero -- disabled={disabled}, counters_zero={counters_zero}, "
                   f"session_match={session_match}"),
        "piv_zero_attempt_assertion": False,
        "telemetry": tel,
    }
