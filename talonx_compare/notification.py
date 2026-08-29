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

from talonx_piv.notification_telemetry import TELEMETRY_NAME, select_telemetry

VERIFIED_ZERO = "VERIFIED_ZERO"
UNVERIFIED = "UNVERIFIED"
MISSING = "MISSING"
WRONG_SESSION = "WRONG_SESSION"
ATTEMPTS_RECORDED = "ATTEMPTS_RECORDED"


def assess_piv_notification(
    state_dir: Path, expected_session_id: str | None,
    expected_trading_date_et: str | None,
) -> dict[str, Any]:
    if not expected_session_id or not expected_trading_date_et:
        return {
            "verdict": UNVERIFIED,
            "evidence_status": "MISSING_IDENTITY",
            "detail": "exact session_id and trading_date_et are required; notification behaviour is UNVERIFIED",
            "piv_zero_attempt_assertion": False,
            "telemetry": None,
        }
    evidence_status, tel = select_telemetry(
        Path(state_dir), session_id=expected_session_id,
        trading_date_et=expected_trading_date_et,
    )
    if evidence_status != "OK" or tel is None:
        return {
            "verdict": UNVERIFIED,
            "evidence_status": evidence_status,
            "detail": (
                f"{TELEMETRY_NAME} exact selection failed ({evidence_status}); "
                "PIV notification behaviour is UNVERIFIED, never zero"
            ),
            "piv_zero_attempt_assertion": False,
            "telemetry": None,
        }

    own = tel.get("ownership", {})
    outbound = tel.get("outbound", {})
    inbound = tel.get("inbound", {})
    required_ownership = {
        "outbound_enabled", "sender_constructed", "inbound_poller_constructed",
        "inbound_poller_started",
    }
    required_outbound = {"attempts", "successes", "failures"}
    required_inbound = {
        "poll_starts", "poll_attempts", "poll_successes", "poll_failures",
    }
    if not (
        required_ownership <= set(own)
        and required_outbound <= set(outbound)
        and required_inbound <= set(inbound)
    ):
        return {
            "verdict": UNVERIFIED, "evidence_status": "INCOMPLETE",
            "detail": "telemetry record lacks required ownership or counter fields",
            "piv_zero_attempt_assertion": False, "telemetry": tel,
        }
    try:
        outbound_attempts = int(outbound["attempts"])
        inbound_starts = int(inbound["poll_starts"])
        inbound_attempts = int(inbound["poll_attempts"])
        all_counts = [
            outbound_attempts, int(outbound["successes"]), int(outbound["failures"]),
            inbound_starts, inbound_attempts, int(inbound["poll_successes"]),
            int(inbound["poll_failures"]),
        ]
    except (TypeError, ValueError):
        return {
            "verdict": UNVERIFIED, "evidence_status": "CORRUPT_COUNTERS",
            "detail": "telemetry counters are not valid integers",
            "piv_zero_attempt_assertion": False, "telemetry": tel,
        }
    if any(value < 0 for value in all_counts):
        return {
            "verdict": UNVERIFIED, "evidence_status": "CORRUPT_COUNTERS",
            "detail": "telemetry counters cannot be negative",
            "piv_zero_attempt_assertion": False, "telemetry": tel,
        }

    if outbound_attempts > 0 or inbound_starts > 0 or inbound_attempts > 0:
        return {
            "verdict": ATTEMPTS_RECORDED,
            "evidence_status": "OK",
            "detail": (f"outbound attempts={outbound_attempts} "
                       f"(failures={outbound.get('failures', 0)}, successes={outbound.get('successes', 0)}), "
                       f"inbound poll_starts={inbound_starts}, poll_attempts={inbound_attempts}"),
            "piv_zero_attempt_assertion": False,
            "telemetry": tel,
        }

    disabled = (
        own.get("outbound_enabled") is False
        and own.get("sender_constructed") is False
        and own.get("inbound_poller_constructed") is False
        and own.get("inbound_poller_started") is False
    )
    counters_zero = all(value == 0 for value in all_counts)
    session_match = (
        tel.get("session_id") == expected_session_id
        and tel.get("trading_date_et") == expected_trading_date_et
    )

    if disabled and counters_zero and session_match:
        return {
            "verdict": VERIFIED_ZERO,
            "evidence_status": "OK",
            "detail": "telemetry present for this session; outbound + inbound disabled; all counters zero",
            "piv_zero_attempt_assertion": True,
            "telemetry": tel,
        }
    return {
        "verdict": UNVERIFIED,
        "evidence_status": "OK",
        "detail": (f"cannot assert zero -- disabled={disabled}, counters_zero={counters_zero}, "
                   f"session_match={session_match}"),
        "piv_zero_attempt_assertion": False,
        "telemetry": tel,
    }
