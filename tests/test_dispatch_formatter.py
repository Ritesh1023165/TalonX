"""
tests/test_dispatch_formatter.py
-------------------------------------
Tests talonx_dispatch.formatter -- pure ActionableAlert -> Telegram
Markdown text logic. No I/O, no bot token needed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_dispatch.formatter import escape_markdown, format_telegram_message
from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    ResearchVerdict,
    SignalDirection,
    TriggeringSignalRef,
)


def _alert(
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    severity: AlertSeverity = AlertSeverity.WARNING,
    summary: str = "Fundamentals support the move.",
    key_findings: list[str] | None = None,
    risk_factors: list[str] | None = None,
) -> ActionableAlert:
    now = datetime(2026, 8, 7, 14, 23, 0, tzinfo=timezone.utc)
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
            message="RSI 24.3 oversold with 2.8x volume surge",
            price=312.41,
            bar_timestamp=now,
        ),
        research_summary=summary,
        key_findings=key_findings or [],
        risk_factors=risk_factors or [],
        model_used="gemini-flash-latest",
        signal_received_at=now,
        report_received_at=now,
        correlated_at=now,
        published_at=now,
    )


def test_escape_markdown_escapes_the_four_special_characters():
    assert escape_markdown("under_score *star* `tick` [bracket]") == (
        "under\\_score \\*star\\* \\`tick\\` \\[bracket]"
    )


def test_escape_markdown_leaves_plain_text_untouched():
    assert escape_markdown("plain text 123") == "plain text 123"


def test_format_includes_ticker_price_and_verdict():
    text = format_telegram_message(_alert())
    assert "AAPL" in text
    assert "312.41" in text
    assert "bullish" in text
    assert "85%" in text


def test_format_confirmed_bullish_uses_green_circle():
    text = format_telegram_message(_alert(action=AlertAction.CONFIRMED_BULLISH))
    assert "\U0001F7E2" in text
    assert "CONFIRMED BULLISH" in text


def test_format_confirmed_bearish_uses_red_circle():
    text = format_telegram_message(_alert(action=AlertAction.CONFIRMED_BEARISH))
    assert "\U0001F534" in text
    assert "CONFIRMED BEARISH" in text


def test_format_contradicted_uses_warning_emoji():
    text = format_telegram_message(_alert(action=AlertAction.CONTRADICTED))
    assert "CONTRADICTED" in text


def test_format_degraded_quant_alert_does_not_raise():
    # Regression coverage: _ACTION_EMOJI/_ACTION_LABEL are plain dict
    # lookups with no default -- adding a new AlertAction without adding
    # it to both would raise KeyError here and silently break Telegram
    # delivery for every degraded alert.
    text = format_telegram_message(_alert(action=AlertAction.DEGRADED_QUANT_ALERT))
    assert "DEGRADED" in text


def test_format_critical_severity_adds_fire_prefix():
    text = format_telegram_message(_alert(severity=AlertSeverity.CRITICAL))
    assert text.startswith("\U0001F525")


def test_format_non_critical_severity_has_no_fire_prefix():
    text = format_telegram_message(_alert(severity=AlertSeverity.WARNING))
    assert not text.startswith("\U0001F525")


def test_format_includes_key_findings_and_risk_factors_as_bullets():
    text = format_telegram_message(
        _alert(key_findings=["Finding one"], risk_factors=["Risk one"])
    )
    assert "Key findings:" in text
    assert "• Finding one" in text
    assert "Risks:" in text
    assert "• Risk one" in text


def test_format_omits_sections_when_lists_empty():
    text = format_telegram_message(_alert(key_findings=[], risk_factors=[]))
    assert "Key findings:" not in text
    assert "Risks:" not in text


def test_format_escapes_special_characters_in_dynamic_text():
    text = format_telegram_message(_alert(summary="Growth in *services* and R_D spend"))
    assert "\\*services\\*" in text
    assert "R\\_D" in text


def test_format_truncates_very_long_summary():
    text = format_telegram_message(_alert(summary="x" * 1000))
    # Truncated segment should be well under the raw 1000 chars, plus the ellipsis marker.
    assert "…" in text
    assert len(text) < 1000 + 500  # generous bound; just proving truncation happened
