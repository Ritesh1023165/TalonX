"""
tests/test_dispatch_formatter.py
-------------------------------------
Tests talonx_dispatch.formatter's two Telegram Markdown formatters:

  - format_telegram_summary(alert, alert_id): the actual push -- built
    from a live ActionableAlert, must stay SHORT (no research writeup)
    and must include the alert ID + reply hint.
  - format_telegram_details(row): the full writeup sent back on a reply,
    built from an audit ROW DICT (not a Pydantic object) -- same content
    the old single format() used to always send.

No I/O, no bot token needed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_dispatch.formatter import escape_markdown, format_telegram_details, format_telegram_summary
from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    ResearchVerdict,
    SignalDirection,
    TriggeringSignalRef,
)

NOW = datetime(2026, 8, 7, 14, 23, 0, tzinfo=timezone.utc)


def _alert(
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    severity: AlertSeverity = AlertSeverity.WARNING,
    message: str = "RSI 24.3 oversold with 2.8x volume surge",
) -> ActionableAlert:
    return ActionableAlert(
        ticker="AAPL",
        action=action,
        severity=severity,
        rationale="rationale text",
        quant_direction=SignalDirection.BULLISH,
        research_verdict=ResearchVerdict.BULLISH,
        research_confidence=0.85,
        triggering_signal=TriggeringSignalRef(
            ticker="AAPL",
            signal_type="rsi_oversold_volume_surge",
            direction=SignalDirection.BULLISH,
            message=message,
            price=312.41,
            bar_timestamp=NOW,
        ),
        research_summary="Fundamentals support the move.",
        model_used="gemini-flash-latest",
        signal_received_at=NOW,
        report_received_at=NOW,
        correlated_at=NOW,
        published_at=NOW,
    )


def _row(
    alert_id: int = 47,
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    severity: AlertSeverity = AlertSeverity.WARNING,
    rationale: str = "Quant signal (bullish): RSI oversold. Research verdict agrees: bullish at 85% confidence -- Fundamentals support the move.",
    key_findings: list[str] | None = None,
    risk_factors: list[str] | None = None,
) -> dict:
    """Matches AuditStore.get_by_id()'s return shape (talonx_dispatch/store.py's
    _row_to_dict) -- a plain dict with string action/severity/verdict, not enums."""
    return {
        "id": alert_id,
        "ticker": "AAPL",
        "action": action.value,
        "severity": severity.value,
        "rationale": rationale,
        "quant_direction": "bullish",
        "research_verdict": "bullish",
        "research_confidence": 0.85,
        "signal_type": "rsi_oversold_volume_surge",
        "price": 312.41,
        "research_summary": "Fundamentals support the move.",
        "key_findings": key_findings or [],
        "risk_factors": risk_factors or [],
        "model_used": "gemini-flash-latest",
        "correlated_at": NOW.isoformat(),
        "received_at": NOW.isoformat(),
        "telegram_sent": False,
        "telegram_sent_at": None,
        "telegram_error": None,
    }


def test_escape_markdown_escapes_the_four_special_characters():
    assert escape_markdown("under_score *star* `tick` [bracket]") == (
        "under\\_score \\*star\\* \\`tick\\` \\[bracket]"
    )


def test_escape_markdown_leaves_plain_text_untouched():
    assert escape_markdown("plain text 123") == "plain text 123"


# --- format_telegram_summary (the actual push) ----------------------------

def test_summary_includes_ticker_price_confidence_and_id():
    text = format_telegram_summary(_alert(), alert_id=47)
    assert "AAPL" in text
    assert "312.41" in text
    assert "85%" in text
    assert "#47" in text
    assert "Reply with 47" in text


def test_summary_includes_the_one_line_quant_trigger():
    text = format_telegram_summary(_alert(message="MACD crossed above signal line"), alert_id=47)
    assert "MACD crossed above signal line" in text


def test_summary_stays_short_and_omits_the_research_writeup():
    text = format_telegram_summary(_alert(), alert_id=47)
    # The full research summary/findings/risks never appear in the short push.
    assert "Fundamentals support the move." not in text
    assert "Key findings" not in text
    assert "Risks" not in text
    assert len(text) < 400


def test_summary_confirmed_bullish_uses_green_circle():
    text = format_telegram_summary(_alert(action=AlertAction.CONFIRMED_BULLISH), alert_id=1)
    assert "\U0001F7E2" in text
    assert "CONFIRMED BULLISH" in text


def test_summary_degraded_quant_alert_does_not_raise():
    text = format_telegram_summary(_alert(action=AlertAction.DEGRADED_QUANT_ALERT), alert_id=1)
    assert "DEGRADED" in text


def test_summary_critical_severity_adds_fire_prefix():
    text = format_telegram_summary(_alert(severity=AlertSeverity.CRITICAL), alert_id=1)
    assert text.startswith("\U0001F525")


# --- format_telegram_details (sent back on a reply) ------------------------

def test_details_includes_ticker_price_verdict_and_id():
    text = format_telegram_details(_row(alert_id=47))
    assert "AAPL" in text
    assert "312.41" in text
    assert "bullish" in text
    assert "85%" in text
    assert "#47" in text


def test_details_confirmed_bearish_uses_red_circle():
    text = format_telegram_details(_row(action=AlertAction.CONFIRMED_BEARISH))
    assert "\U0001F534" in text
    assert "CONFIRMED BEARISH" in text


def test_details_contradicted_uses_warning_label():
    text = format_telegram_details(_row(action=AlertAction.CONTRADICTED))
    assert "CONTRADICTED" in text


def test_details_degraded_quant_alert_does_not_raise():
    # Regression coverage: _ACTION_EMOJI/_ACTION_LABEL are plain dict
    # lookups with no default -- adding a new AlertAction without adding
    # it to both would raise KeyError here and silently break Telegram
    # delivery for every degraded alert.
    text = format_telegram_details(_row(action=AlertAction.DEGRADED_QUANT_ALERT))
    assert "DEGRADED" in text


def test_details_critical_severity_adds_fire_prefix():
    text = format_telegram_details(_row(severity=AlertSeverity.CRITICAL))
    assert text.startswith("\U0001F525")


def test_details_non_critical_severity_has_no_fire_prefix():
    text = format_telegram_details(_row(severity=AlertSeverity.WARNING))
    assert not text.startswith("\U0001F525")


def test_details_includes_key_findings_and_risk_factors_as_bullets():
    text = format_telegram_details(_row(key_findings=["Finding one"], risk_factors=["Risk one"]))
    assert "Key findings:" in text
    assert "• Finding one" in text
    assert "Risks:" in text
    assert "• Risk one" in text


def test_details_omits_sections_when_lists_empty():
    text = format_telegram_details(_row(key_findings=[], risk_factors=[]))
    assert "Key findings:" not in text
    assert "Risks:" not in text


def test_details_escapes_special_characters_in_dynamic_text():
    text = format_telegram_details(_row(rationale="Growth in *services* and R_D spend"))
    assert "\\*services\\*" in text
    assert "R\\_D" in text


def test_details_truncates_very_long_rationale():
    text = format_telegram_details(_row(rationale="x" * 2000))
    assert "…" in text
    assert len(text) < 2000 + 500  # generous bound; just proving truncation happened


def test_details_formats_the_correlated_at_timestamp():
    text = format_telegram_details(_row())
    assert "2026-08-07 14:23 UTC" in text
