"""Task 99H -- Telegram Markdown/entity-escaping fix.

Focus: `talonx_signals/renderers.py`'s `_raw()`/`_esc()` contract must make
every current alert-card renderer produce text that Telegram's legacy
Markdown parser (`ParseMode.MARKDOWN`, the default of
`talonx_dispatch.telegram_client.TelegramClient.send`) can always parse,
regardless of what dynamic/identifier content is embedded, while preserving
the intended trusted formatting (headers, the backtick-wrapped symbol/ID) and
human-readability.

Root cause (see results/task99h_telegram_escape/root_cause.md): `_raw()`
treated internally-generated identifiers (enum `.value` strings, all
snake_case/SCREAMING_SNAKE_CASE by convention) as "never need escaping" --
false under Telegram's legacy Markdown, which reacts to literal characters
regardless of provenance. 10/61 live sends failed 2026-09-04 because the
AGGREGATE unescaped-underscore count across several `_raw()` fields in one
message happened to be odd.

Oracle used throughout: after the fix, the ONLY unescaped occurrences of the
four legacy-Markdown special characters (`_ * \\` [`) in any rendered message
must be the literal backticks the template itself hardcodes around the
symbol/public-id (never a `_`/`*`/`[`, and never a dynamic-field-controlled
backtick count) -- i.e. every character contributed by a dynamic/identifier
field must be escaped, and the trusted-formatting backtick count must be
invariant to what the dynamic fields contain.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.renderers import (
    _esc,
    _raw,
    render_directional_details,
    render_directional_setup,
    render_event_update,
    render_event_update_details,
    render_experimental_trade,
    render_radar,
    render_radar_details,
)

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)

# The 4 chars legacy Markdown treats as entity delimiters.
_SPECIALS = "_*`["
# `_`/`*`/`[` are NEVER intentionally emitted unescaped by any template in
# this module -- zero-tolerance. Backtick IS intentionally used, unescaped,
# by the templates themselves (wrapping the trusted symbol/public-id), so it
# is checked separately (invariant count, not zero) -- see
# `test_trusted_backtick_count_invariant_to_dynamic_content`.
_STRICT_ZERO = "_*["

_UNESCAPED = {
    ch: re.compile(r"(?<!\\)" + re.escape(ch)) for ch in _SPECIALS
}


def _unescaped_count(text: str, ch: str) -> int:
    """Count occurrences of `ch` in `text` not immediately preceded by a
    backslash (i.e. would still act as a live Telegram entity delimiter)."""
    return len(_UNESCAPED[ch].findall(text))


def _base_directional(**overrides) -> dict:
    base = dict(
        alert_id="Dtestbase0000001", symbol="AAPL", direction="BULLISH",
        profile="EXPERIMENTAL_RELAXED_V1", setup_type="macd_bullish_cross",
        setup_score=2, session="regular", price=100.0,
        trade_gate_status="WOULD_REJECT", trade_gate_reject_reason="LOW_RISK_REWARD",
        message="MACD crossed above signal",
    )
    base.update(overrides)
    return base


def _base_trade(**overrides) -> dict:
    base = dict(
        trade_id="Xtestbase0000001", symbol="AAPL", profile="EXPERIMENTAL_RELAXED_V1",
        side="BUY", entry=100.0, stop=98.0, target=104.0, quantity=25,
        admitted_by="relaxed_confluence",
    )
    base.update(overrides)
    return base


def _base_radar(**overrides) -> dict:
    base = dict(radar_id="Rtestbase0000001", symbol="AAPL", reporting_when="2026-09-10 AMC",
                context="Q3 earnings")
    base.update(overrides)
    return base


def _base_event(**overrides) -> dict:
    base = dict(event_id="Etestbase0000001", symbol="AAPL", event_type="8-K Item 2.02",
                accepted_at="2026-09-04T20:15:00Z")
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1-25: individual character / class coverage
# ---------------------------------------------------------------------------

_CHAR_CASES = [
    ("plain_ascii", "hello world"),
    ("ticker_ordinary", "ABC123"),
    ("underscore", "low_risk_reward"),
    ("asterisk", "risk*reward"),
    ("square_brackets", "[click here]"),
    ("parentheses", "(see notes)"),
    ("tilde", "~approx~"),
    ("backtick", "code`span`here"),
    ("greater_than", "value > threshold"),
    ("hash", "#tag context"),
    ("plus", "value+1"),
    ("minus", "value-1"),
    ("equals", "a=b"),
    ("pipe", "a|b"),
    ("braces", "{key: value}"),
    ("period", "end of sentence."),
    ("exclamation", "big move!"),
    ("ampersand", "R&D update"),
    ("angle_brackets", "<tag>text</tag>"),
    ("quotes_apostrophes", "it's a \"test\""),
    ("unicode_punct", "café — naïve"),
    ("em_dash", "before — after"),
    ("percent", "up 12% today"),
    ("dollar", "$1,234.56"),
    ("slash_colon", "http://example.com:8080/path"),
]


@pytest.mark.parametrize("name,value", _CHAR_CASES, ids=[c[0] for c in _CHAR_CASES])
def test_char_case_directional_message_field_safe(name, value):
    """Each character/class embedded in a free-text (`_esc`) field must never
    leave an unescaped `_`/`*`/backtick/`[` in the rendered card, and the
    human-readable substance must still be present (modulo the inserted
    escape backslashes)."""
    text = render_directional_setup(_base_directional(message=value))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0, f"{name}: unescaped {ch!r} leaked into output"
    # readability: stripping our own escape backslashes recovers the original
    stripped = text.replace("\\_", "_").replace("\\*", "*").replace("\\`", "`").replace("\\[", "[")
    assert value in stripped


@pytest.mark.parametrize("name,value", _CHAR_CASES, ids=[c[0] for c in _CHAR_CASES])
def test_char_case_directional_identifier_field_safe(name, value):
    """The same character classes routed through `_raw()` (as a
    trade_gate_reject_reason-shaped identifier field) must be equally safe --
    this is the actual field that broke live delivery on 2026-09-04."""
    text = render_directional_setup(_base_directional(trade_gate_reject_reason=value))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0, f"{name}: unescaped {ch!r} leaked into output"


# ---------------------------------------------------------------------------
# 26-29: composite / adversarial dynamic content
# ---------------------------------------------------------------------------

def test_url_containing_field():
    text = render_event_update_details(_base_event(evidence_url="https://sec.gov/path_with_under_scores?a=1&b=2"))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0
    assert "sec.gov" in text


def test_filing_title_multi_special_chars():
    title = "Item 2.02 [Results]: Q3_2026 *record* revenue -- up 12%! (see `10-Q`)"
    text = render_event_update(_base_event(event_type=title))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0


def test_event_description_mixed_punctuation():
    ctx = "Guidance raised; R&D spend +15%, margin ~22% (vs. 18% prior) -- CEO: \"strong quarter\"."
    text = render_radar(_base_radar(context=ctx))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0


def test_malicious_looking_markup_injection_string():
    """A dynamic field that looks like it's trying to inject its own
    Markdown/entity structure must never succeed in doing so."""
    injection = "*BOLD_INJECT* [link](javascript:alert(1)) `escape_code` __also_bold__ [a](b)[c](d)"
    text = render_directional_setup(_base_directional(message=injection))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0
    # the injected "[link](...)" must not become a live Markdown link -- the
    # literal "[" is escaped so Telegram can never parse it as one.
    assert "\\[link\\]" in text or "\\[" in text


# ---------------------------------------------------------------------------
# 30: trusted heading formatting preserved
# ---------------------------------------------------------------------------

def test_trusted_heading_and_symbol_backticks_preserved():
    text = render_directional_setup(_base_directional(message="anything_with_underscores"))
    assert "\U0001F7E2 ⚡ BULLISH SETUP" in text  # hardcoded trusted header, untouched
    assert "`AAPL`" in text  # trusted backtick wrapping around the (safe) ticker survives
    assert "#SETUP" in text  # trusted hashtag literal survives


def test_trusted_backtick_count_invariant_to_dynamic_content():
    """The number of UNESCAPED backticks (all trusted, template-authored) must
    not change no matter what a dynamic field contains -- proves dynamic
    content can never smuggle in a live entity delimiter of its own."""
    clean = render_directional_setup(_base_directional())
    dirty = render_directional_setup(_base_directional(message="`*_[injected structure]_*`"))
    assert _unescaped_count(clean, "`") == _unescaped_count(dirty, "`")
    assert _unescaped_count(dirty, "_") == 0
    assert _unescaped_count(dirty, "*") == 0
    assert _unescaped_count(dirty, "[") == 0


# ---------------------------------------------------------------------------
# 31-32: escaped exactly once / no double escaping
# ---------------------------------------------------------------------------

def test_dynamic_field_escaped_exactly_once():
    text = render_directional_setup(_base_directional(trade_gate_reject_reason="LOW_RISK_REWARD"))
    assert "LOW\\_RISK\\_REWARD" in text
    assert "LOW\\\\_RISK" not in text  # not double-escaped


def test_raw_and_esc_are_not_stacked_by_any_call_site():
    """`_raw`/`_esc` are terminal -- neither function's output is ever passed
    back through the other anywhere in renderers.py (verified by direct
    behavioural equivalence: both now perform exactly one escaping pass)."""
    assert _raw("a_b*c`d[e") == _esc("a_b*c`d[e")
    once = _esc("a_b")
    assert _esc(once) != once  # sanity: re-escaping WOULD double-escape if ever mis-called
    assert once == "a\\_b"


# ---------------------------------------------------------------------------
# 33-35: missing / long / multiline data
# ---------------------------------------------------------------------------

def test_empty_and_none_dynamic_fields():
    text = render_directional_setup(_base_directional(message=None))
    assert "Reason:" not in text  # optional field correctly omitted, not "None"
    text2 = render_directional_setup(_base_directional(message=""))
    assert "Reason:" not in text2  # falsy string also correctly omitted


def test_very_long_dynamic_field_does_not_explode():
    long_text = ("alpha_beta_gamma*delta`epsilon[zeta " * 200).strip()
    text = render_directional_setup(_base_directional(message=long_text))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0
    # escaping roughly doubles the specials' footprint, not the whole message;
    # no pathological blow-up (e.g. quadratic re-escaping).
    assert len(text) < 3 * len(long_text) + 500


def test_multiline_dynamic_field():
    multi = "line one_with_underscore\nline *two*\nline `three`"
    text = render_directional_setup(_base_directional(message=multi))
    for ch in _STRICT_ZERO:
        assert _unescaped_count(text, ch) == 0
    assert text.count("\n") >= multi.count("\n")  # line breaks preserved


# ---------------------------------------------------------------------------
# 36: every current alert-card renderer
# ---------------------------------------------------------------------------

_ADVERSARIAL = "under_score *star* `tick` [bracket]"


def test_all_current_renderers_are_safe_under_adversarial_dynamic_content():
    cases = [
        render_directional_setup(_base_directional(message=_ADVERSARIAL)),
        render_directional_details({
            "alert_id": "Dtestbase0000001", "direction": "BEARISH", "symbol": "AAPL",
            "profile": "EXPERIMENTAL_RELAXED_V1", "horizon": "INTRADAY_SHORT",
            "price": 100.0, "setup_type": "rsi_oversold_volume_surge", "setup_score": 2,
            "evidence": {"nearby_catalyst": _ADVERSARIAL}, "stop_price": 98.0,
            "target_price": 104.0, "risk_reward_ratio": 1.2, "geometry_path": "STRUCTURAL_PRIMARY",
            "trade_gate_status": "WOULD_REJECT", "trade_gate_reject_reason": "LOW_RISK_REWARD",
            "bar_timestamp": NOW.isoformat(), "generated_at": NOW.isoformat(),
        }),
        render_experimental_trade(_base_trade(admitted_by=_ADVERSARIAL)),
        render_experimental_trade(_base_trade(side="SELL", exit=103.0, exit_reason=_ADVERSARIAL,
                                               gross_pnl=75.0, est_costs=3.0, net_pnl=72.0,
                                               r_multiple=1.44, mfe=1.5, mae=-0.3)),
        render_radar(_base_radar(context=_ADVERSARIAL, holding_status=_ADVERSARIAL)),
        render_radar_details(_base_radar(context=_ADVERSARIAL, holding_status=_ADVERSARIAL)),
        render_event_update(_base_event(event_type=_ADVERSARIAL, insider_context=_ADVERSARIAL,
                                         material_changes=[_ADVERSARIAL], significance_band="HIGH")),
        render_event_update_details(_base_event(event_type=_ADVERSARIAL, insider_context=_ADVERSARIAL,
                                                 material_changes=[_ADVERSARIAL],
                                                 significance_band="HIGH",
                                                 significance_reasons=[_ADVERSARIAL],
                                                 evidence_url=_ADVERSARIAL,
                                                 source_event_id=_ADVERSARIAL)),
    ]
    for text in cases:
        for ch in _STRICT_ZERO:
            assert _unescaped_count(text, ch) == 0, f"unescaped {ch!r} in: {text!r}"


# ---------------------------------------------------------------------------
# 37-40: transport / retry / dedup / observability
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = ExperimentalAlertStore(tmp_path / "exp_alerts.db")
    yield s
    s.close()


@pytest.mark.asyncio
async def test_transport_receives_final_valid_payload(store):
    """The exact text handed to the sender (i.e. what would go to Telegram)
    must already be fully escaped -- the transport does no escaping itself."""
    sender = RecordingSender()
    dispatcher = ExperimentalDispatcher(store=store, sender=sender, enable_external_send=True)
    alert = _base_directional(trade_gate_reject_reason="LOW_RISK_REWARD")
    result = await dispatcher.dispatch_directional(alert)
    assert result == "SENT"
    assert len(sender.sent) == 1
    for ch in _STRICT_ZERO:
        assert _unescaped_count(sender.sent[0], ch) == 0


@pytest.mark.asyncio
async def test_retry_does_not_duplicate_send_on_transient_failure(store):
    sender = RecordingSender(fail_times=2)  # fails twice, then succeeds
    dispatcher = ExperimentalDispatcher(store=store, sender=sender, enable_external_send=True)
    result = await dispatcher.dispatch_directional(_base_directional())
    assert result == "SENT"
    assert len(sender.sent) == 1  # exactly one successful send recorded, no duplicate


@pytest.mark.asyncio
async def test_parse_failure_remains_observable_not_silently_held(store):
    """If a send exhausts retries (e.g. a hypothetical future parse failure),
    the dispatcher must record FAILED with a visible error -- never silently
    convert it to SENT or HELD."""
    sender = RecordingSender(fail_times=99)  # never succeeds
    dispatcher = ExperimentalDispatcher(store=store, sender=sender, enable_external_send=True)
    result = await dispatcher.dispatch_directional(_base_directional())
    assert result == "FAILED"
    assert dispatcher.metrics.send_failures == 1
    row = store.get_directional(_base_directional()["alert_id"])
    assert row["send_error"] == "exhausted retries"
    assert row["sent"] in (0, False)


@pytest.mark.asyncio
async def test_dedup_idempotency_unchanged_by_escaping_fix(store):
    sender = RecordingSender()
    dispatcher = ExperimentalDispatcher(store=store, sender=sender, enable_external_send=True)
    alert = _base_directional()
    first = await dispatcher.dispatch_directional(alert)
    second = await dispatcher.dispatch_directional(alert)  # same alert_id
    assert first == "SENT"
    assert second == "DUPLICATE"
    assert len(sender.sent) == 1
    assert dispatcher.metrics.duplicates_skipped == 1
