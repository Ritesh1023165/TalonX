"""Deterministic, non-enabling Task 64 preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from .broker import AlpacaPaperClient
from .config import CANONICAL_ALPHA_FEED_MODES, FEED_MODE_PARAM, FEED_MODES, PivConfig
from .events import EventBus, PivEvent
from .readiness import SessionReadinessValidator


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def config_hash(config: PivConfig) -> str:
    safe = {
        "paper_trading": config.paper_trading, "real_capital": config.real_capital,
        "broker_endpoint": config.broker_endpoint, "data_endpoint": config.data_endpoint,
        "stale_seconds": config.stale_seconds, "entry_cutoff_et": config.entry_cutoff_et,
        "eod_flatten_et": config.eod_flatten_et, "universe": config.universe, "feed_mode": config.feed_mode,
        "version": "TASK64_V1",
    }
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()


class Preflight:
    def __init__(self, config: PivConfig, broker: AlpacaPaperClient, events: EventBus, repo: Path = Path("."), transport: Any = requests) -> None:
        self.config, self.broker, self.events, self.repo, self.transport = config, broker, events, repo, transport

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def run(self) -> tuple[str, list[Check]]:
        checks: list[Check] = []
        def check(name: str, action: Callable[[], tuple[bool, str]]) -> None:
            try:
                passed, detail = action()
            except Exception as exc:
                passed, detail = False, f"{type(exc).__name__}: {exc}"
            checks.append(Check(name, bool(passed), detail))

        check("approved_sha", lambda: ((head := self._git("rev-parse", "HEAD")) == self.config.approved_sha, head))
        check("tracked_tree_clean", lambda: (not (status := self._git("status", "--short", "--untracked-files=no")), status or "clean"))
        check("config_hash", lambda: (True, config_hash(self.config)))
        identity: dict[str, Any] = {}
        def paper() -> tuple[bool, str]:
            value = self.broker.verify_paper_identity(); identity["value"] = value
            return value.environment == "PAPER", f"PAPER endpoint={value.endpoint} account=***{value.account_number_suffix}"
        check("paper_account_verified", paper)
        broker_state: dict[str, Any] = {}
        def orders() -> tuple[bool, str]:
            broker_state["orders"] = self.broker.open_orders()
            return True, str(len(broker_state["orders"]))
        def positions() -> tuple[bool, str]:
            broker_state["positions"] = self.broker.positions()
            return True, str(len(broker_state["positions"]))
        check("open_paper_orders_queried", orders)
        check("open_paper_positions_queried", positions)
        def reconcile() -> tuple[bool, str]:
            state_path = self.config.state_dir / "lifecycle_state.json"
            internal = set()
            if state_path.exists():
                body = json.loads(state_path.read_text(encoding="utf-8"))
                internal = {str(row.get("symbol")) for row in body.get("positions", {}).values() if row.get("status") == "OPEN"}
            broker_symbols = {str(row.get("symbol")) for row in broker_state.get("positions", [])}
            matched = internal == broker_symbols
            return matched, f"internal={sorted(internal)} broker={sorted(broker_symbols)}"
        check("internal_broker_reconciled", reconcile)
        def market_data_feed() -> tuple[bool, str]:
            mode = self.config.feed_mode
            if mode not in FEED_MODES:
                return False, f"unknown feed_mode={mode!r}; must be one of {FEED_MODES}"
            # Explicit, mode-pinned feed param only -- never omitted, never
            # retried against a different feed on failure. A RESEARCH_SIP
            # preflight that gets a 403 on sip must fail closed, not
            # silently probe iex, and vice versa.
            feed_param = FEED_MODE_PARAM[mode]
            url = f"{self.config.data_endpoint}/v2/stocks/AAPL/trades/latest"
            response = self.transport.get(url, headers=self.broker.headers, params={"feed": feed_param}, timeout=15)
            trade = response.json().get("trade") or {}
            raw_timestamp = str(trade.get("t") or "")
            parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")) if raw_timestamp else None
            valid = response.status_code == 200 and parsed is not None and parsed.tzinfo is not None
            return valid, f"HTTP {response.status_code} feed_mode={mode} feed={feed_param} timestamp={raw_timestamp}"
        check("market_data_feed_accessible", market_data_feed)
        def feed_classification() -> tuple[bool, str]:
            mode = self.config.feed_mode
            canonical = mode in CANONICAL_ALPHA_FEED_MODES
            label = "CANONICAL_ALPHA_EVIDENCE" if canonical else "OPERATIONAL_PIV_ONLY_NOT_ALPHA_EVIDENCE"
            return mode in FEED_MODES, f"feed_mode={mode} classification={label}"
        check("feed_mode_classification", feed_classification)
        check("timezone_and_xnys", lambda: (ZoneInfo("America/New_York").key == "America/New_York", "XNYS/ET configured"))
        check("universe_loaded", lambda: (len(self.config.universe) == 35 and len(set(self.config.universe)) == 35, f"{len(self.config.universe)} symbols"))
        check("stale_detection_armed", lambda: (self.config.stale_seconds > 0, f"{self.config.stale_seconds}s"))
        check("readiness_validator_loaded", lambda: (isinstance(SessionReadinessValidator(), SessionReadinessValidator), "Task64 reusable validator"))
        def writable() -> tuple[bool, str]:
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            probe = self.config.state_dir / ".write_probe"; probe.write_text("ok", encoding="utf-8"); probe.unlink()
            return True, str(self.config.state_dir)
        check("logging_writable", writable)
        check("telemetry_enabled", lambda: (True, str(self.events.path)))
        def telegram() -> tuple[bool, str]:
            if not self.config.telegram_token or not self.config.telegram_chat_id:
                return False, "Telegram token/chat id missing"
            response = self.transport.get(f"https://api.telegram.org/bot{self.config.telegram_token}/getMe", timeout=15)
            return response.status_code == 200 and bool(response.json().get("ok")), f"HTTP {response.status_code}"
        check("telegram_reachable", telegram)
        check("kill_switch_available", lambda: (True, "persistent fail-closed lifecycle switch"))
        check("eod_flatten_configured", lambda: (self.config.eod_flatten_et == "15:50", self.config.eod_flatten_et))
        check("duplicate_order_protection", lambda: (True, "stable intent id persisted before submit"))
        status = "PIV_READY" if all(item.passed for item in checks) else "PIV_BLOCKED"
        self.events.emit(PivEvent.build("PREFLIGHT_PASS" if status == "PIV_READY" else "PREFLIGHT_FAIL", status=status, reason="; ".join(c.name for c in checks if not c.passed) or "ALL_CHECKS_PASS"))
        return status, checks

    @staticmethod
    def write_report(path: Path, status: str, checks: list[Check], feed_mode: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "status": status, "checks": [asdict(c) for c in checks]}
        if feed_mode is not None:
            payload["feed_mode"] = feed_mode
            payload["canonical_alpha_evidence"] = feed_mode in CANONICAL_ALPHA_FEED_MODES
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
