"""Task 71S -- read-only, evidence-based classification of a missing-minute
or STALE_DATA gap, using Alpaca's own historical IEX 1-minute archive as
ground truth.

This module performs HISTORICAL market-data reads only (GET
/v2/stocks/{symbol}/bars) -- no order/broker endpoint is ever reachable
from here, and it is never called from the live decision path (see
session_runner.py, which uses talonx_piv/freshness.py for its real-time
state machine instead). Its purpose is strictly retrospective: given a
day's already-recorded gap (a missing opening minute, or a STALE_DATA
event), determine -- using the same feed (feed=iex) the live system itself
used -- whether the gap is CONFIRMED_NO_IEX_TRADE (the historical archive
independently agrees no trade printed) or a genuine
HISTORICAL_DATA_DISAGREEMENT (the archive shows a bar the live system
evidently missed). Classification is only ever as strong as the evidence
available -- an unreachable historical endpoint, or a gap outside any
window this module can evaluate, is honestly reported UNKNOWN, never
guessed into a definitive bucket.

See results/task71s_data_freshness_stabilization/ for the full 2026-08-26
forensic run produced by this exact methodology (developed first as a
one-off analysis script, then hardened into this tested, reusable module).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .alpaca_historical_warmup import _parse_bars_page, _request_page

ET = ZoneInfo("America/New_York")

CONFIRMED_NO_IEX_TRADE = "CONFIRMED_NO_IEX_TRADE"
LIVE_STREAM_BAR_MISSED = "LIVE_STREAM_BAR_MISSED"
SUBSCRIPTION_OR_PIPELINE_GAP = "SUBSCRIPTION_OR_PIPELINE_GAP"
PROVIDER_WIDE_INTERRUPTION = "PROVIDER_WIDE_INTERRUPTION"
LOCAL_PROCESSING_DELAY = "LOCAL_PROCESSING_DELAY"
HISTORICAL_DATA_DISAGREEMENT = "HISTORICAL_DATA_DISAGREEMENT"
UNKNOWN = "UNKNOWN"

GAP_CLASSIFICATIONS = (
    CONFIRMED_NO_IEX_TRADE, LIVE_STREAM_BAR_MISSED, SUBSCRIPTION_OR_PIPELINE_GAP,
    PROVIDER_WIDE_INTERRUPTION, LOCAL_PROCESSING_DELAY, HISTORICAL_DATA_DISAGREEMENT, UNKNOWN,
)


@dataclass(frozen=True)
class GapClassification:
    symbol: str
    classification: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_historical_minute_set(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str, symbol: str,
    start_iso: str, end_iso: str, feed: str = "iex", limit: int = 1000,
) -> set[str] | None:
    """Returns the set of ET "HH:MM" minute-labels with at least one
    historical 1-minute bar in [start_iso, end_iso), or None if the fetch
    itself failed (non-200, or a transport exception) -- None is the
    signal to callers that no historical evidence is available (must
    classify UNKNOWN, never fabricate an inference from a failed
    read-only check)."""
    try:
        response = _request_page(transport, data_endpoint, key_id, secret_key, symbol, start_iso, end_iso, feed, limit)
    except Exception:  # noqa: BLE001 -- read-only forensic check; a failure here must degrade to UNKNOWN, not raise
        return None
    if response.status_code != 200:
        return None
    parsed = _parse_bars_page(response.json() or {})
    if parsed is None:
        return None
    return {b.timestamp.astimezone(ET).strftime("%H:%M") for b in parsed}


def classify_missing_minute(minute_et_label: str, historical_minutes: set[str] | None) -> str:
    """`minute_et_label`: an "HH:MM" ET label for the specific minute that
    was missing live (e.g. from readiness.py's ReadinessTelemetry.missing_minutes,
    reformatted). historical_minutes: the symbol's own historical minute-label
    set for the same day (from fetch_historical_minute_set), or None if
    unavailable."""
    if historical_minutes is None:
        return UNKNOWN
    return HISTORICAL_DATA_DISAGREEMENT if minute_et_label in historical_minutes else CONFIRMED_NO_IEX_TRADE


def classify_stale_event(
    event_timestamp_utc: str, historical_minutes: set[str] | None,
) -> tuple[str, str]:
    """Classifies one STALE_DATA event (its own recorded wall-clock
    `timestamp` field) against the symbol's historical minute set for that
    day. Checks the two whole ET minutes immediately preceding the flag
    instant -- these are the minutes whose absence directly justifies a
    >120s-no-new-bar flag (a bar landing in either would have refreshed
    last_seen_wall and prevented/cleared it). Returns (classification,
    evidence_string).

    CONFIRMED_NO_IEX_TRADE: neither of those two minutes has a historical
    bar either -- the flag was an accurate reflection of genuine market
    sparsity, exactly as this module's own docstring's 2026-08-26 forensic
    run found for all 72 stale events that day.

    HISTORICAL_DATA_DISAGREEMENT: the historical archive DOES show a bar
    in one of those two minutes -- a bar existed that should have kept the
    symbol fresh; this is the evidence-based trigger for
    LIVE_STREAM_BAR_MISSED / SUBSCRIPTION_OR_PIPELINE_GAP -- distinguishing
    between those two requires knowing whether OTHER symbols were ALSO
    affected in the same poll cycle (see PROVIDER_WIDE_INTERRUPTION vs a
    single symbol's own gap), which this function -- scoped to one symbol
    -- deliberately leaves to the caller (see classify_stale_events_batch).

    UNKNOWN: no historical evidence available (fetch failed) -- never
    guessed into either bucket."""
    if historical_minutes is None:
        return UNKNOWN, "historical fetch unavailable"
    ts_et = datetime.fromisoformat(event_timestamp_utc).astimezone(ET)
    m1 = (ts_et - timedelta(minutes=1)).strftime("%H:%M")
    m2 = (ts_et - timedelta(minutes=2)).strftime("%H:%M")
    m1_present, m2_present = m1 in historical_minutes, m2 in historical_minutes
    if not m1_present and not m2_present:
        return CONFIRMED_NO_IEX_TRADE, f"neither {m2} nor {m1} ET has a historical bar"
    present = [m for m, ok in ((m2, m2_present), (m1, m1_present)) if ok]
    return HISTORICAL_DATA_DISAGREEMENT, f"historical archive has a bar at {','.join(present)} ET that the live system missed"


def classify_stale_events_batch(
    events: list[dict[str, Any]], historical_minutes_by_symbol: dict[str, set[str] | None],
    provider_wide_threshold: int = 5,
) -> list[GapClassification]:
    """Batch classification across potentially many symbols/events in the
    same session. A HISTORICAL_DATA_DISAGREEMENT is only ever escalated to
    PROVIDER_WIDE_INTERRUPTION when at least `provider_wide_threshold`
    DIFFERENT symbols show a disagreement in the SAME clock minute --
    otherwise it is reported as a single-symbol SUBSCRIPTION_OR_PIPELINE_GAP
    (this repo's live path is a per-symbol-batched REST poll, not a
    per-symbol WebSocket subscription, so "subscription" here means "this
    symbol's row in the batched poll response", not a literal socket)."""
    per_event = []
    for e in events:
        symbol = e["symbol"]
        hist = historical_minutes_by_symbol.get(symbol)
        classification, evidence = classify_stale_event(e["timestamp"], hist)
        per_event.append({"symbol": symbol, "timestamp": e["timestamp"], "classification": classification, "evidence": evidence})

    # Find disagreement clusters sharing the same ET minute across symbols.
    from collections import defaultdict
    disagreement_minutes: dict[str, set[str]] = defaultdict(set)
    for row in per_event:
        if row["classification"] == HISTORICAL_DATA_DISAGREEMENT:
            ts_et = datetime.fromisoformat(row["timestamp"]).astimezone(ET)
            minute_label = ts_et.strftime("%H:%M")
            disagreement_minutes[minute_label].add(row["symbol"])

    results = []
    for row in per_event:
        classification = row["classification"]
        evidence = row["evidence"]
        if classification == HISTORICAL_DATA_DISAGREEMENT:
            ts_et = datetime.fromisoformat(row["timestamp"]).astimezone(ET)
            minute_label = ts_et.strftime("%H:%M")
            symbols_sharing = disagreement_minutes.get(minute_label, set())
            if len(symbols_sharing) >= provider_wide_threshold:
                classification = PROVIDER_WIDE_INTERRUPTION
                evidence += f"; shared with {len(symbols_sharing) - 1} other symbol(s) at {minute_label} ET"
            else:
                classification = SUBSCRIPTION_OR_PIPELINE_GAP
        results.append(GapClassification(symbol=row["symbol"], classification=classification, evidence=evidence))
    return results
