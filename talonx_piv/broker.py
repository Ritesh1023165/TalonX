"""Alpaca adapter that is structurally incapable of live-capital routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests

from .config import PAPER_ENDPOINT, PivConfig
from .execution_ownership import ExecutionOwnership, ExecutionOwnershipError


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
        # Task 78I Stage 1D: None (the default -- every pre-Task78I caller)
        # means NO ownership enforcement at all, preserving all existing
        # single-process test/behavior exactly. A real live session
        # (cli.py::runtime()) always sets this after verify_paper_identity()
        # succeeds, before any mutation is attempted -- see
        # execution_ownership.py's own module docstring for the full design.
        self.execution_ownership: ExecutionOwnership | None = None

    def _require_execution_ownership(self) -> None:
        if self.execution_ownership is None:
            return
        try:
            self.execution_ownership.require()
        except ExecutionOwnershipError as exc:
            raise PaperGuardError(f"EXECUTION_OWNERSHIP_NOT_HELD: {exc}") from exc

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

    def get_order(self, order_id: str) -> dict[str, Any]:
        self._require_verified()
        response = self.transport.get(f"{PAPER_ENDPOINT}/v2/orders/{order_id}", headers=self.headers, timeout=15)
        response.raise_for_status()
        return dict(response.json())

    def find_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        """Task 79E-R1/R2: the ONLY way to resolve a SUBMIT_FAILED_UNCERTAIN
        intent -- one whose submit_order call raised BEFORE any broker order
        id was ever received, so lifecycle.py has no id to poll with
        get_order. Alpaca's own order-status-vocabulary is keyed by broker
        id, but every order this codebase submits also carries a stable,
        locally-derived client_order_id (see lifecycle.stable_id) -- looking
        the order up by THAT identity answers "did this actually reach the
        broker?" without ever blindly resubmitting.

        Task 79E-R2: uses Alpaca's ACTUAL documented endpoint --
        `GET /v2/orders:by_client_order_id?client_order_id=...` (see
        https://docs.alpaca.markets/us/reference/getorderbyclientorderid),
        NOT `/v2/orders?status=all&client_order_id=...` (an R1 mistake --
        that query param is not part of the documented list-orders filter
        set at all; it happened to "work" only because the offline fakes
        modeled the WRONG contract). Returns the single Order object on a
        clean 200, or None on a clean 404 (an explicit "no such order"
        response, per Alpaca's get-by-id semantics). Any OTHER response
        (malformed body, non-404 error status) raises -- lifecycle.py's own
        caller already treats a raised exception as "still unresolved,
        retry later," never as evidence of anything; only a genuine 404 (or
        a genuine match) is evidence. A single 404 is deliberately NOT
        treated as fully conclusive by the caller either -- see
        lifecycle.py's own _resolve_uncertain_submissions, which requires
        this to be observed on more than one separate reconcile() pass
        before treating "not found" as durable evidence the order never
        reached the broker."""
        self._require_verified()
        response = self.transport.get(
            f"{PAPER_ENDPOINT}/v2/orders:by_client_order_id", headers=self.headers,
            params={"client_order_id": client_order_id}, timeout=15,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not body.get("id"):
            # Task 79E-R2: a 200 with a malformed/empty body is NOT the same
            # as a documented 404 -- it is ambiguous, not evidence of
            # anything. Raising (rather than returning None) keeps the
            # caller's fail-closed "still unresolved" path, never silently
            # treated as "confirmed not submitted."
            raise PaperGuardError(f"malformed order-by-client-id response for {client_order_id!r}")
        return body

    def positions(self) -> list[dict[str, Any]]:
        self._require_verified()
        response = self.transport.get(f"{PAPER_ENDPOINT}/v2/positions", headers=self.headers, timeout=15)
        response.raise_for_status()
        return list(response.json())

    def submit_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_verified()
        self._require_execution_ownership()
        response = self.transport.post(f"{PAPER_ENDPOINT}/v2/orders", headers=self.headers, json=payload, timeout=15)
        response.raise_for_status()
        return dict(response.json())

    def cancel_all_orders(self) -> list[dict[str, Any]]:
        self._require_verified()
        self._require_execution_ownership()
        response = self.transport.delete(f"{PAPER_ENDPOINT}/v2/orders", headers=self.headers, timeout=15)
        response.raise_for_status()
        return list(response.json() or [])

    def close_all_positions(self) -> list[dict[str, Any]]:
        self._require_verified()
        self._require_execution_ownership()
        response = self.transport.delete(f"{PAPER_ENDPOINT}/v2/positions", headers=self.headers, params={"cancel_orders": "true"}, timeout=15)
        response.raise_for_status()
        return list(response.json() or [])
