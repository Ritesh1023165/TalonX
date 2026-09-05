"""Fail-closed Original/PIV runtime binding isolation (Task 82).

This module configures the reused QuantScanner without changing protected
strategy files. It also validates every shared-resource boundary before a
PIV process is allowed to coexist with the Original application.
"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from urllib.parse import urlparse

from talonx_quant.config import QuantConfig

from .config import PivConfig


def _redis_identity(url: str) -> tuple[str, str, int, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("Redis URL must use redis:// or rediss:// and include a host")
    try:
        database = int(parsed.path.lstrip("/") or "0")
    except ValueError as exc:
        raise ValueError("Redis URL database must be a non-negative integer") from exc
    if database < 0:
        raise ValueError("Redis URL database must be a non-negative integer")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or 6379, database


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def piv_quant_db_path(config: PivConfig) -> Path:
    return _resolved(config.quant_db_path or (config.state_dir / "piv_quant.db"))


def build_piv_quant_config(config: PivConfig) -> QuantConfig:
    """Return QuantScanner configuration bound only to PIV resources."""
    return replace(
        QuantConfig(),
        redis_url=config.redis_url,
        market_stream_channel=config.market_stream_channel,
        signals_channel=config.signals_channel,
        rejected_candidates_channel=config.rejected_candidates_channel,
        news_events_channel=config.news_events_channel,
        paper_trades_channel=config.paper_trades_channel,
        db_path=str(piv_quant_db_path(config)),
    )


def isolation_binding_payload(config: PivConfig) -> dict[str, object]:
    """Credential-free identity fields included in the session hash."""
    try:
        scheme, host, port, database = _redis_identity(config.redis_url)
        redis: dict[str, object] = {
            "scheme": scheme, "host": host, "port": port, "database": database,
        }
    except ValueError:
        # Still produce a stable, credential-free identity hash; validation
        # independently blocks this malformed binding before startup.
        redis = {"invalid": True}
    return {
        "redis": redis,
        "redis_namespace": config.redis_namespace,
        "channels": sorted({
            config.market_stream_channel, config.signals_channel,
            config.rejected_candidates_channel, config.news_events_channel,
            config.paper_trades_channel,
        }),
        "quant_db_path": str(piv_quant_db_path(config)),
        "state_dir": str(_resolved(config.state_dir)),
        "telegram_enabled": config.telegram_enabled,
    }


def validate_piv_isolation(config: PivConfig) -> tuple[bool, str]:
    """Prove PIV cannot share mutable runtime bindings with Original.

    Details intentionally contain no URLs, credentials, or tokens.
    """
    failures: list[str] = []
    try:
        piv_redis = _redis_identity(config.redis_url)
        original_redis = _redis_identity(os.getenv("TALONX_REDIS_URL", "redis://localhost:6379/0"))
        if piv_redis == original_redis:
            failures.append("PIV and Original resolve to the same Redis endpoint/database")
    except ValueError as exc:
        failures.append(str(exc))

    original_channels = {
        os.getenv("TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"),
        os.getenv("TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"),
        os.getenv("TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL", "talonx:quant:rejected"),
        os.getenv("TALONX_REDIS_NEWS_EVENTS_CHANNEL", "talonx:news:events"),
        os.getenv("TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"),
    }
    piv_channels = {
        config.market_stream_channel,
        config.signals_channel,
        config.rejected_candidates_channel,
        config.news_events_channel,
        config.paper_trades_channel,
    }
    prefix = f"{config.redis_namespace}:" if config.redis_namespace else ""
    if not prefix or any(not channel.startswith(prefix) for channel in piv_channels):
        failures.append("every PIV Redis channel must use the configured non-empty PIV namespace")
    if len(piv_channels) != 5:
        failures.append("PIV Redis channels must be mutually distinct")
    if piv_channels & original_channels:
        failures.append("one or more PIV Pub/Sub channels overlap Original channels")

    original_quant_db = _resolved(os.getenv(
        "TALONX_QUANT_DB_PATH", str(Path.home() / ".talonx" / "quant.db")
    ))
    if piv_quant_db_path(config) == original_quant_db:
        failures.append("PIV and Original Quant persistence paths overlap")

    if config.telegram_enabled:
        failures.append("PIV Telegram must remain disabled while Original owns notifications and bot polling")

    if failures:
        return False, "; ".join(failures)
    return True, (
        "isolated Redis database, namespaced Pub/Sub channels, PIV Quant DB, and PIV state; "
        "PIV Telegram disabled"
    )
