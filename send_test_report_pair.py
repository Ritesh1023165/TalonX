"""
send_test_report_pair.py
-----------------------------
Publishes a synthetic QuantSignal directly to talonx:signals:quant AND a
matching ResearchReport directly to talonx:reports:brain -- bypassing
talonx_quant's indicator math and talonx_brain's retrieval+LLM call
entirely. Unlike send_test_signal.py (which only gets you a QuantSignal
and depends on whatever talonx_brain's configured LLM provider decides
to say -- Gemini/Ollama verdicts aren't scripted, so they don't reliably
land on a high-confidence agreeing verdict), this script controls BOTH
halves of the pair directly, so it's the fast, deterministic way to
verify talonx_core's decision matrix and talonx_dispatch end-to-end
without depending on LLM judgment at all.

By default direction and verdict agree (both bullish) with confidence
0.85, well past every one of decision.py's evaluate() gates (see its
docstring): well past TALONX_CORE_MIN_CONFIDENCE, both timestamps are
"now" so well within TALONX_CORE_CORRELATION_WINDOW, and --ticker
defaults to TESTQ specifically because it's nobody's real symbol -- no
live market_data/quant process tracks it, and it can't collide with a
real ticker's TALONX_CORE_TICKER_COOLDOWN from earlier testing.

model_used is hardcoded to "synthetic-test-fixture" (not a real Gemini/
Ollama model string) so this injected data is unmistakable in the audit
trail/Streamlit dashboard, never mistaken for a genuine LLM-generated
report.

Requires talonx_core.run (and, if you want to see it reach the
dashboard, talonx_dispatch.run) already running and subscribed --
this only PUBLISHES, it doesn't consume or compute anything itself.

Usage:
    python send_test_report_pair.py
    python send_test_report_pair.py --ticker TESTQ --direction bearish
    python send_test_report_pair.py --direction bullish --verdict bearish   # forces CONTRADICTED
    python send_test_report_pair.py --confidence 0.3                       # forces UNCONFIRMED (no alert)
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Same resolution approach as send_test_signal.py -- load the shared .env
# by path, not by searching the current directory.
_shared_env = Path(__file__).resolve().parent / ".env"
if _shared_env.is_file():
    load_dotenv(_shared_env, override=False)

import os

REDIS_URL = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
SIGNALS_CHANNEL = os.environ.get("TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant")
REPORTS_CHANNEL = os.environ.get("TALONX_REDIS_REPORTS_CHANNEL", "talonx:reports:brain")

# bullish -> RSI oversold (the "buy the dip" read); bearish -> RSI
# overbought -- same signal_type choices send_test_signal.py's synthetic
# bar recipe is engineered to produce, kept consistent for anyone
# cross-referencing the two scripts.
_SIGNAL_TYPE_FOR_DIRECTION = {
    "bullish": "rsi_oversold_volume_surge",
    "bearish": "rsi_overbought_volume_surge",
}


def build_signal(ticker: str, direction: str) -> dict:
    now = datetime.now(timezone.utc)
    # Plausible-looking indicator snapshot -- decision.py's evaluate()
    # never inspects these fields (only .direction), they just need to be
    # valid numbers for QuantSignal to parse.
    rsi = 24.3 if direction == "bullish" else 78.1
    return {
        "ticker": ticker.upper(),
        "signal_type": _SIGNAL_TYPE_FOR_DIRECTION[direction],
        "direction": direction,
        "message": f"Synthetic {direction} test signal (send_test_report_pair.py)",
        "price": 131.5,
        "rsi": rsi,
        "macd": None,
        "macd_signal_line": None,
        "sma_fast": None,
        "sma_slow": None,
        "volume": 5_000_000.0,
        "volume_surge_ratio": 3.6,
        "bar_timestamp": now.isoformat(),
        "published_at": now.isoformat(),
    }


def build_report(signal: dict, verdict: str, confidence: float) -> dict:
    now = datetime.now(timezone.utc)
    ticker = signal["ticker"]
    return {
        "ticker": ticker,
        "triggering_signal": signal,
        "verdict": verdict,
        "confidence": confidence,
        "summary": (
            f"Synthetic {verdict} test verdict (send_test_report_pair.py) -- "
            "not a real LLM call, generated to verify talonx_core's decision "
            "matrix and talonx_dispatch end-to-end without depending on LLM judgment."
        ),
        "key_findings": ["Synthetic finding for end-to-end pipeline testing"],
        "risk_factors": ["This is injected test data, not a real research call"],
        "citations": [],  # talonx_core's trimmed ResearchReport mirror ignores this anyway
        "model_used": "synthetic-test-fixture",
        "generated_at": now.isoformat(),
        "published_at": now.isoformat(),
    }


async def main(ticker: str, direction: str, verdict: str, confidence: float, delay: float) -> None:
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        print("The 'redis' package is required: pip install redis")
        return

    client = redis_asyncio.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}")
        print("Check that Redis is running and TALONX_REDIS_URL is correct.")
        return

    signal = build_signal(ticker, direction)
    report = build_report(signal, verdict, confidence)

    agrees = direction == verdict
    if not agrees and verdict in ("bullish", "bearish"):
        expected = "CONTRADICTED"
    elif confidence < 0.5:
        expected = "no alert (confidence below TALONX_CORE_MIN_CONFIDENCE default 0.5)"
    else:
        expected = f"CONFIRMED_{direction.upper()}"

    print(f"Publishing synthetic QuantSignal (direction={direction}) for {ticker.upper()} to {SIGNALS_CHANNEL}")
    await client.publish(SIGNALS_CHANNEL, json.dumps(signal))
    print(f"  Published. Waiting {delay}s before publishing the report "
          "(mimics realistic signal-then-report ordering; talonx_core "
          "correlates on whichever half arrives last, so this isn't strictly required).")
    await asyncio.sleep(delay)

    print(f"Publishing synthetic ResearchReport (verdict={verdict}, confidence={confidence}) "
          f"for {ticker.upper()} to {REPORTS_CHANNEL}")
    await client.publish(REPORTS_CHANNEL, json.dumps(report))

    print(f"\nDone. Expected outcome: {expected}")
    print(f"Check the talonx_core.run terminal for an alert log line, or query "
          f"~/.talonx/core_state.db's ticker_state row for {ticker.upper()}.")
    print("If talonx_dispatch.run is also running, check its terminal/audit trail/Streamlit "
          f"dashboard for a {ticker.upper()} entry with model_used=\"synthetic-test-fixture\".")
    await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Publish a synthetic QuantSignal + matching ResearchReport pair "
        "to verify talonx_core + talonx_dispatch end-to-end, without depending on "
        "talonx_quant's indicator math or talonx_brain's LLM call."
    )
    parser.add_argument("--ticker", default="TESTQ", help="Ticker symbol to use (default: TESTQ -- not a real symbol, avoids cooldown/collision with live data)")
    parser.add_argument("--direction", choices=["bullish", "bearish"], default="bullish", help="QuantSignal direction (default: bullish)")
    parser.add_argument("--verdict", choices=["bullish", "bearish", "neutral", "insufficient_context"], default=None, help="ResearchReport verdict (default: matches --direction, for a guaranteed CONFIRMED alert)")
    parser.add_argument("--confidence", type=float, default=0.85, help="ResearchReport confidence, 0-1 (default: 0.85)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between publishing the signal and the report (default: 0.5)")
    args = parser.parse_args()
    verdict = args.verdict or args.direction
    asyncio.run(main(args.ticker, args.direction, verdict, args.confidence, args.delay))
