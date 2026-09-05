"""
talonx_ingest.intelligence.delivery.claim_safety
================================================
Context-aware claim-safety scan over the FINAL rendered Telegram text
(``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md``).

The renderer's own wording is fully controlled; the uncontrolled surface
is company names, 96A titles, 96E reason strings (already scanned in 96E),
and 96C frozen-lexicon term values. A **factual** SEC transaction word —
"open-market sale", "purchase of 40,000 shares", a "Buy-Sell Agreement" —
must NOT be rejected. A **predictive / advice** construct — "buy signal",
"bullish", "expected return", "high conviction" — must be.

Strategy:
  1. unambiguous predictive PHRASES  -> always a violation;
  2. bare predictive TOKENS (bullish / bearish / conviction / alpha / …)
     -> violation via the shared scanner;
  3. bare "buy" / "sell" -> violation ONLY when not inside an allow-listed
     factual construct (an SEC agreement type, a share count, an
     open-market qualifier).
"""
from __future__ import annotations

import re

from talonx_ingest.intelligence.significance.language_safety import (
    PredictiveLanguageError,
    scan_text as _sig_scan,
)

__all__ = [
    "PredictiveLanguageError",
    "scan_rendered",
    "assert_clean",
]

# ---- 1. unambiguous predictive / advice phrases ---------------------------
_PROHIBITED_PHRASES: tuple[str, ...] = (
    "buy signal", "sell signal", "buy recommendation", "sell recommendation",
    "strong buy", "strong sell", "should buy", "should sell",
    "buy the dip", "buy now", "sell now",
    "expected return", "price target", "target price", "profit target",
    "take profit", "stop loss", "likely to rise", "likely to fall",
    "likely to decline", "likely to drop", "likely to gain",
    "will rise", "will fall", "will drop", "will rally", "will move",
    "high conviction", "high-conviction", "conviction buy", "conviction sell",
    "smart money", "insider alpha", "alpha signal", "trade signal",
    "risk-on", "risk-off", "bullish", "bearish", "outperform", "underperform",
    "overweight", "underweight", "undervalued", "overvalued",
    "positive catalyst", "negative catalyst", "good news", "bad news",
)
_PHRASE_RE = [
    re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", re.IGNORECASE)
    for p in _PROHIBITED_PHRASES
]

# ---- 3. factual allow-list for bare buy / sell -------------------------
_BUY_SELL_RE = re.compile(r"(?<![a-z])(buy|sell)(?![a-z])", re.IGNORECASE)
_ALLOWED_CONTEXT_RE = re.compile(
    r"""
    buy[-\s]?sell\s+agreement          # "Buy-Sell Agreement" (SEC 8-K 1.01 type)
    | (?:open[-\s]market\s+)?(?:buy|sell)(?:er|ing|s)?\s+
        (?:of\s+)?\d                    # "open-market sell of 12,000" / "sellers 3"
    | \d[\d,]*\s+shares?\s+(?:were\s+)?(?:bought|sold)   # "40,000 shares sold"
    | (?:bought|sold)\s+\d[\d,]*\s+shares?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _bare_buy_sell_violations(text: str) -> list[str]:
    out: list[str] = []
    for m in _BUY_SELL_RE.finditer(text):
        s, e = m.start(), m.end()
        window = text[max(0, s - 40): min(len(text), e + 40)]
        if _ALLOWED_CONTEXT_RE.search(window):
            continue
        out.append(m.group(0).lower())
    return sorted(set(out))


def scan_rendered(text: str | None) -> list[str]:
    """Return every ``(kind:term)`` claim-safety violation in the rendered
    message. Empty list == clean."""
    if not text:
        return []
    violations: list[str] = []
    for term in _sig_scan(text):
        # the shared scanner already excludes bare buy/sell nuance we
        # handle below; keep everything else it flags.
        if term in ("buy", "sell"):
            continue
        violations.append(f"phrase:{term}")
    for pat, phrase in zip(_PHRASE_RE, _PROHIBITED_PHRASES):
        if pat.search(text):
            violations.append(f"phrase:{phrase}")
    for t in _bare_buy_sell_violations(text):
        violations.append(f"token:{t}")
    return sorted(set(violations))


def assert_clean(text: str | None) -> None:
    v = scan_rendered(text)
    if v:
        raise PredictiveLanguageError(
            f"rendered Telegram text contains prohibited claim language: {v}"
        )
