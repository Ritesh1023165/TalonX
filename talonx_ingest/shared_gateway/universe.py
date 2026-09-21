"""
talonx_ingest.shared_gateway.universe
-------------------------------------------
Resolves the Shared Gateway's symbol universe once at startup, as the
union of Original's dynamic watchlist (read-only) and PIV's hard-coded
DEFAULT_UNIVERSE. See results/task88_shared_gateway/design.md §2.6 for why
this is resolved once (not re-polled intraday) and why that's an accepted
MVP limitation (finding P2-3, BACKLOG), and
results/task88_shared_gateway/architecture_before.md §9 for why the two
sides' universes are not the same list today.

Read-only: this module only ever reads talonx_watchlist's SQLite file. It
never writes to it, and it never imports talonx_piv beyond the plain
DEFAULT_UNIVERSE constant (no lifecycle/broker coupling).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("talonx_ingest.shared_gateway.universe")


@dataclass(frozen=True)
class ResolvedUniverse:
    configured: tuple[str, ...]
    origins: dict[str, list[str]] = field(default_factory=dict)  # symbol -> ["original","piv"]
    original_count: int = 0
    piv_count: int = 0
    original_source: str = "UNAVAILABLE"


def _read_original_watchlist(db_path: str) -> tuple[list[str], str]:
    """Best-effort, read-only SQLite read. Returns (symbols, source_status)
    -- an unreachable/missing/malformed watchlist DB never crashes gateway
    startup; it just means the gateway's universe is PIV-only that run,
    explicitly recorded in `original_source`, never silently assumed."""
    if not Path(db_path).is_file():
        return [], "WATCHLIST_DB_NOT_FOUND"
    try:
        # Read-only URI connection -- this process must never accidentally
        # acquire a write lock against a file two other live processes
        # (run_talonx.py, the Streamlit dashboard) may be using.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            rows = conn.execute(
                "SELECT symbol FROM tickers WHERE status = 'active'"
            ).fetchall()
        finally:
            conn.close()
        return [r[0].upper() for r in rows], "OK"
    except sqlite3.Error as exc:
        logger.warning("Could not read Original watchlist at %s: %s", db_path, exc)
        return [], f"WATCHLIST_DB_READ_ERROR:{type(exc).__name__}"


def resolve_universe(original_watchlist_db_path: str) -> ResolvedUniverse:
    from talonx_piv.config import DEFAULT_UNIVERSE  # local import: no hard PIV coupling at module load

    original_symbols, original_source = _read_original_watchlist(original_watchlist_db_path)
    piv_symbols = list(DEFAULT_UNIVERSE)

    origins: dict[str, list[str]] = {}
    for sym in original_symbols:
        origins.setdefault(sym, []).append("original")
    for sym in piv_symbols:
        origins.setdefault(sym, []).append("piv")

    configured = tuple(sorted(origins.keys()))
    logger.info(
        "Gateway universe resolved: %d symbols (original=%d [%s], piv=%d)",
        len(configured), len(original_symbols), original_source, len(piv_symbols),
    )
    return ResolvedUniverse(
        configured=configured, origins=origins,
        original_count=len(original_symbols), piv_count=len(piv_symbols),
        original_source=original_source,
    )
