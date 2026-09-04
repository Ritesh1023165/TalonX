"""Task 99A S4 -- ExperimentalDispatcher.

Persist-before-send, idempotent on the deterministic public id (no double
send), retry with backoff, honour Telegram ``RetryAfter`` verbatim, fail fast
on a bad token / forbidden chat. External Telegram send is OFF unless
``enable_external_send=True`` is explicitly passed AND the sender reports
configured -- otherwise rows are recorded and left un-sent (dry run).

Trading orders are NEVER sent here. Only text notifications. The paper engine
is the sole execution target.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.renderers import (
    assert_no_predictive_language,
    render_directional_setup,
    render_event_update,
    render_experimental_trade,
    render_radar,
)

logger = logging.getLogger("talonx_signals.dispatcher")


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None
    retry_after: float | None = None
    permanent: bool = False


class SenderProtocol(Protocol):
    @property
    def configured(self) -> bool: ...
    async def send(self, text: str) -> SendResult: ...


class RecordingSender:
    """Test / dry-run sender. Records every text; never touches the network."""

    def __init__(self, fail_times: int = 0, retry_after: float | None = None, permanent: bool = False):
        self.sent: list[str] = []
        self._fail_times = fail_times
        self._retry_after = retry_after
        self._permanent = permanent

    @property
    def configured(self) -> bool:
        return True

    async def send(self, text: str) -> SendResult:
        if self._fail_times > 0:
            self._fail_times -= 1
            return SendResult(ok=False, error="transient", retry_after=self._retry_after,
                              permanent=self._permanent)
        self.sent.append(text)
        return SendResult(ok=True)


class NullSender:
    @property
    def configured(self) -> bool:
        return False

    async def send(self, text: str) -> SendResult:  # pragma: no cover - never called
        return SendResult(ok=False, error="null sender")


class TelegramSenderAdapter:
    """Wraps the existing, qualified ``talonx_dispatch.telegram_client
    .TelegramClient`` -- the ONLY transport touch point for external sends."""

    def __init__(self, client: Any = None):
        if client is None:
            from talonx_dispatch.telegram_client import TelegramClient

            client = TelegramClient()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(getattr(self._client, "is_configured", False))

    async def send(self, text: str) -> SendResult:
        try:
            from telegram.error import Forbidden, InvalidToken, RetryAfter
        except Exception:  # pragma: no cover
            Forbidden = InvalidToken = RetryAfter = ()  # type: ignore
        try:
            await self._client.send(text)
            return SendResult(ok=True)
        except RetryAfter as exc:  # type: ignore[misc]
            return SendResult(ok=False, error="retry_after", retry_after=float(getattr(exc, "retry_after", 1.0)))
        except (Forbidden, InvalidToken) as exc:  # type: ignore[misc]
            return SendResult(ok=False, error=f"permanent:{exc}", permanent=True)
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))


@dataclass
class DispatchMetrics:
    directional_recorded: int = 0
    directional_sent: int = 0
    trades_recorded: int = 0
    trades_sent: int = 0
    radar_sent: int = 0
    event_sent: int = 0
    duplicates_skipped: int = 0
    send_failures: int = 0
    dry_run_held: int = 0


@dataclass
class ExperimentalDispatcher:
    store: ExperimentalAlertStore
    sender: SenderProtocol = field(default_factory=NullSender)
    enable_external_send: bool = False
    max_attempts: int = 4
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 60.0
    company_lookup: Any = None  # optional callable symbol -> name
    metrics: DispatchMetrics = field(default_factory=DispatchMetrics)

    def _company(self, symbol: str) -> str | None:
        if self.company_lookup is None:
            return None
        try:
            return self.company_lookup(symbol)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    async def dispatch_directional(self, alert: Any) -> str:
        d = alert if isinstance(alert, dict) else alert.model_dump(mode="json")
        newly = self.store.record_directional(alert)
        if not newly:
            self.metrics.duplicates_skipped += 1
            return "DUPLICATE"
        self.metrics.directional_recorded += 1
        self.store.log(d["alert_id"], "directional", "RECORDED")
        text = render_directional_setup(d, company=self._company(d["symbol"]))
        return await self._deliver("directional_alerts", d["alert_id"], text, "directional")

    async def dispatch_trade(self, trade: dict) -> str:
        newly = self.store.record_trade(trade)
        if not newly:
            self.metrics.duplicates_skipped += 1
            return "DUPLICATE"
        self.metrics.trades_recorded += 1
        self.store.log(trade["trade_id"], "trade", "RECORDED")
        text = render_experimental_trade(trade, company=self._company(trade["symbol"]))
        return await self._deliver("experimental_trades", trade["trade_id"], text, "trade")

    async def dispatch_radar(self, row: dict) -> str:
        if not self.store.record_radar(row):
            self.metrics.duplicates_skipped += 1
            return "DUPLICATE"
        text = render_radar(row)
        return await self._deliver("radar_alerts", row["radar_id"], text, "radar")

    async def dispatch_event_update(self, row: dict) -> str:
        if not self.store.record_event_update(row):
            self.metrics.duplicates_skipped += 1
            return "DUPLICATE"
        text = render_event_update(row)
        return await self._deliver("event_updates", row["event_id"], text, "event")

    # ------------------------------------------------------------------
    async def _deliver(self, table: str, public_id: str, text: str, kind: str) -> str:
        assert_no_predictive_language(text)  # belt-and-braces before any send
        if not (self.enable_external_send and self.sender.configured):
            self.metrics.dry_run_held += 1
            self.store.log(public_id, kind, "DRY_RUN_HELD")
            return "HELD"
        ok = await self._send_with_retry(text)
        if ok:
            self.store.mark_sent(table, public_id)
            self._bump_sent(kind)
            return "SENT"
        self.metrics.send_failures += 1
        self.store.mark_send_error(table, public_id, "exhausted retries")
        return "FAILED"

    def _bump_sent(self, kind: str) -> None:
        if kind == "directional":
            self.metrics.directional_sent += 1
        elif kind == "trade":
            self.metrics.trades_sent += 1
        elif kind == "radar":
            self.metrics.radar_sent += 1
        elif kind == "event":
            self.metrics.event_sent += 1

    async def _send_with_retry(self, text: str) -> bool:
        for attempt in range(1, self.max_attempts + 1):
            res = await self.sender.send(text)
            if res.ok:
                return True
            if res.permanent:
                logger.warning("experimental dispatch permanent failure: %s", res.error)
                return False
            if attempt == self.max_attempts:
                return False
            delay = res.retry_after if res.retry_after is not None else min(
                self.backoff_cap_seconds, self.backoff_base_seconds * (2 ** (attempt - 1))
            )
            await asyncio.sleep(delay)
        return False

    # ------------------------------------------------------------------
    async def drain_pending(self) -> dict[str, int]:
        """Re-attempt every recorded-but-unsent row (restart recovery)."""
        out = {"directional": 0, "trade": 0}
        if not (self.enable_external_send and self.sender.configured):
            return out
        for row in self.store.pending("directional_alerts"):
            text = render_directional_setup(row, company=self._company(row["symbol"]))
            if await self._send_with_retry(text):
                self.store.mark_sent("directional_alerts", row["alert_id"])
                self._bump_sent("directional")
                out["directional"] += 1
        for row in self.store.pending("experimental_trades"):
            text = render_experimental_trade(row, company=self._company(row["symbol"]))
            if await self._send_with_retry(text):
                self.store.mark_sent("experimental_trades", row["trade_id"])
                self._bump_sent("trade")
                out["trade"] += 1
        return out
