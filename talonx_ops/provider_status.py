"""Task 66B-PREP Parts 5/6: explicit market-data-provider and
paper-execution-path identification for the normal run_talonx.py
application. Pure read of existing config -- constructs nothing, opens no
connection, never falls back/retries anything itself. The actual runtime
decision (e.g. Polygon auth failure -> yfinance mid-run) still lives
entirely in talonx_ingest.market_data.manager.MarketDataManager, unchanged;
this module only states what's CONFIGURED, matching the same condition
(`config.polygon_api_key` truthiness) that manager already branches on.
"""

from __future__ import annotations

from talonx_ingest.config import settings

POLYGON_WEBSOCKET = "POLYGON_WEBSOCKET"
YFINANCE_POLLING = "YFINANCE_POLLING"

LOCAL_SIMULATED_PAPER_LEDGER = "LOCAL_SIMULATED_LEDGER (talonx_paper, SQLite -- not a broker)"


def configured_market_data_provider() -> str:
    """POLYGON_WEBSOCKET if POLYGON_API_KEY is configured (may still fall
    back to yfinance mid-run on auth failure/exhausted reconnects -- see
    MarketDataManager.stream()), else YFINANCE_POLLING."""
    return POLYGON_WEBSOCKET if settings.market_data.polygon_api_key else YFINANCE_POLLING


def paper_execution_path_label() -> str:
    """The normal application's paper trading (talonx_paper) is always a
    local simulated ledger -- never Alpaca. Unlike this, talonx_piv submits
    real (paper-mode) orders to Alpaca's broker endpoint. Stated explicitly
    so logs/reports/EOD metadata never conflate the two."""
    return LOCAL_SIMULATED_PAPER_LEDGER
