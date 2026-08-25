"""Task 69Q Part 9 -- prototype ALTERNATIVE historical-warmup data source.

NOT wired into the live warmup path (talonx_piv/warmup.py's preseed_and_verify
still uses yfinance via talonx_quant.consumer.QuantScanner.preseed_symbols,
UNCHANGED). This module is a verified-feasible, tested building block for a
future task to complete the integration -- see
results/task69q_evidence_upgrade/warmup_provider_assessment.json for the
live entitlement check that justified building this (Alpaca's own historical
bars endpoint, same IEX-tier credentials already used for the live feed,
returned hundreds of 1-minute bars for symbols that yfinance's warmup marked
INSUFFICIENT_1M_HISTORY).

Deliberately NOT integrated with talonx_quant.consumer.QuantScanner's
RollingBarBuffer in this task -- that requires bar-format/HTF-aggregation
correctness review this task's time budget does not cover (see
production_readiness_gaps.json PRG-07). This module only proves the fetch
side works against the real account/entitlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

ALPACA_HISTORICAL_PROVIDER = "ALPACA_HISTORICAL"


@dataclass(frozen=True)
class HistoricalBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_1m_bars(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str,
    symbol: str, start_iso: str, end_iso: str, feed: str = "iex", limit: int = 1000,
) -> list[HistoricalBar]:
    """Fetches Alpaca's own historical 1-minute bars for `symbol` -- the SAME
    transport/header pattern already used everywhere else in talonx_piv
    (session_runner.fetch_bars_latest, broker.py). feed='iex' is the SAME
    entitlement level already verified for the live feed (preflight.py's IEX
    feed check) -- this function does NOT require or assume SIP access."""
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
    response = transport.get(
        f"{data_endpoint}/v2/stocks/{symbol}/bars",
        headers=headers,
        params={"timeframe": "1Min", "limit": limit, "feed": feed, "start": start_iso, "end": end_iso},
        timeout=15,
    )
    if response.status_code != 200:
        return []
    rows = (response.json() or {}).get("bars") or []
    bars: list[HistoricalBar] = []
    for row in rows:
        raw_ts = row.get("t")
        if not raw_ts:
            continue
        bars.append(HistoricalBar(
            timestamp=datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")),
            open=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
            close=float(row["c"]), volume=float(row["v"]),
        ))
    return bars
