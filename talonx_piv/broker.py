"""Alpaca adapter that is structurally incapable of live-capital routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests

from .config import PAPER_ENDPOINT, PivConfig


class PaperGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperIdentity:
    account_id: str
    account_number_suffix: str
    status: str
    endpoint: str = PAPER_ENDPOINT
    environment: str = "PAPER"


class AlpacaPaperClient:
    def __init__(self, config: PivConfig, transport: Any = requests) -> None:
        self.config = config
        self.transport = transport
        self.identity: PaperIdentity | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self.config.key_id, "APCA-API-SECRET-KEY": self.config.secret_key}

    def verify_paper_identity(self) -> PaperIdentity:
        if not self.config.paper_trading or self.config.real_capital:
            raise PaperGuardError("required state is PAPER_TRADING=true and REAL_CAPITAL=false")
        if self.config.broker_endpoint.rstrip("/") != PAPER_ENDPOINT:
            raise PaperGuardError("broker endpoint is not the immutable Alpaca paper endpoint")
        if not self.config.key_id or not self.config.secret_key:
            raise PaperGuardError("Alpaca credentials are missing")
        response = self.transport.get(f"{PAPER_ENDPOINT}/v2/account", headers=self.headers, timeout=15)
        if response.status_code != 200:
            raise PaperGuardError(f"paper account verification failed HTTP {response.status_code}")
        body = response.json()
        account_id = str(body.get("id") or "")
        account_number = str(body.get("account_number") or "")
        status = str(body.get("status") or "")
        if not account_id or not account_number or not status:
            raise PaperGuardError("paper identity response was incomplete")
        self.identity = PaperIdentity(account_id, account_number[-4:], status)
        return self.identity

    def _require_verified(self) -> None:
        if self.identity is None:
            raise PaperGuardError("paper account identity has not been positively verified")

    def open_orders(self) -> list[dict[str, Any]]:
        self._require_verified()
        response = self.transport.get(f"{PAPER_ENDPOINT}/v2/orders", headers=self.headers, params={"status": "open"}, timeout=15)
        response.raise_for_status()
        return list(response.json())

    def positions(self) -> list[dict[str, Any]]:
        self._require_verified()
        response = self.transport.get(f"{PAPER_ENDPOINT}/v2/positions", headers=self.headers, timeout=15)
        response.raise_for_status()
        return list(response.json())

    def submit_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_verified()
        response = self.transport.post(f"{PAPER_ENDPOINT}/v2/orders", headers=self.headers, json=payload, timeout=15)
        response.raise_for_status()
        return dict(response.json())

    def cancel_all_orders(self) -> list[dict[str, Any]]:
        self._require_verified()
        response = self.transport.delete(f"{PAPER_ENDPOINT}/v2/orders", headers=self.headers, timeout=15)
        response.raise_for_status()
        return list(response.json() or [])

    def close_all_positions(self) -> list[dict[str, Any]]:
        self._require_verified()
        response = self.transport.delete(f"{PAPER_ENDPOINT}/v2/positions", headers=self.headers, params={"cancel_orders": "true"}, timeout=15)
        response.raise_for_status()
        return list(response.json() or [])
