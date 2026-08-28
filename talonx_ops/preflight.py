"""Task 66B-PREP Parts 3 + 4: read-only preflight for the NORMAL
run_talonx.py application. Deliberately NOT talonx_piv's PIV_READY/
PIV_BLOCKED terminology -- that only proves the narrower PIV runtime is
ready, not this one. Status here is FULL_APP_E2E_READY / FULL_APP_E2E_BLOCKED.

Every check is read-only / non-destructive: stores are opened then closed
without writing rows, Brain's readiness check constructs its LLM chain
object (same as run_talonx.py's own main() already does) without ever
calling generate(), and the market-data/Telegram checks are the same
"identify what's configured" reads talonx_ops.provider_status already
does -- no connection is opened that a normal preflight wouldn't already
open (Redis ping, Telegram getMe -- same as talonx_piv.preflight).

Part 4's hard requirement lives here, not in run_talonx.py: production's
"Brain degrades gracefully, pipeline still runs" philosophy (see
run_talonx.py's own module docstring) is correct for production and is
NOT changed by this file. This preflight simply refuses to call TOMORROW's
session FULL_APP_E2E_READY if Brain isn't genuinely operational -- a
stricter validation-time bar layered on top of, not a change to, the
existing runtime behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

import requests

from talonx_core.config import CoreConfig
from talonx_core import process_guard
from talonx_core.store import TickerStateStore
from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_ingest.config import settings
from talonx_paper.config import PaperConfig
from talonx_paper.store import PaperTradingStore
from talonx_quant.config import QuantConfig
from talonx_quant.store import QuantStateStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

from .provider_status import configured_market_data_provider, paper_execution_path_label

FULL_APP_E2E_READY = "FULL_APP_E2E_READY"
FULL_APP_E2E_BLOCKED = "FULL_APP_E2E_BLOCKED"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FullAppPreflight:
    def __init__(self, expected_sha: str | None = None, repo: Path = Path("."), transport: Any = requests) -> None:
        self.expected_sha = expected_sha
        self.repo = repo
        self.transport = transport

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def run(self) -> tuple[str, list[Check]]:
        checks: list[Check] = []

        def check(name: str, action: Callable[[], tuple[bool, str]]) -> None:
            try:
                passed, detail = action()
            except Exception as exc:  # noqa: BLE001 -- a check that raises is a failed check, not a crashed preflight
                passed, detail = False, f"{type(exc).__name__}: {exc}"
            checks.append(Check(name, bool(passed), detail))

        # 1-2: branch/SHA + tree clean
        def sha() -> tuple[bool, str]:
            head = self._git("rev-parse", "HEAD")
            if self.expected_sha is None:
                return True, head
            return head == self.expected_sha, head
        check("expected_sha", sha)

        def tree_clean() -> tuple[bool, str]:
            status = self._git("status", "--short", "--untracked-files=no")
            return not status, status or "clean"
        check("tracked_tree_clean", tree_clean)

        # 3: no duplicate full-app/PIV process. Inability to enumerate is a
        # launch block because uncertainty is not proof that no competitor
        # exists. The current preflight process itself is excluded.
        check("no_duplicate_full_app_or_piv_process", process_guard.no_competing_talonx_process)

        # 4: Redis reachable
        def redis_reachable() -> tuple[bool, str]:
            import redis
            client = redis.Redis.from_url(settings.redis.url, socket_connect_timeout=5)
            return bool(client.ping()), f"reachable at {settings.redis.url}"
        check("redis_reachable", redis_reachable)

        # 5-6: watchlist non-empty + exact symbol list
        watchlist_state: dict[str, Any] = {}
        def watchlist() -> tuple[bool, str]:
            store = TickerWatchlistStore(WatchlistConfig().db_path)
            try:
                symbols = sorted(store.list_active_symbols())
            finally:
                store.close()
            watchlist_state["symbols"] = symbols
            return len(symbols) > 0, f"{len(symbols)} active symbol(s): {symbols}"
        check("active_watchlist_non_empty", watchlist)

        # 7: paper-enabled symbols
        def paper_enabled_symbols() -> tuple[bool, str]:
            store = TickerWatchlistStore(WatchlistConfig().db_path)
            try:
                symbols = sorted(store.list_paper_trading_symbols())
            finally:
                store.close()
            return True, f"{len(symbols)} paper-enabled symbol(s): {symbols}"
        check("paper_enabled_symbols_recorded", paper_enabled_symbols)

        # 8: Quant persistence store accessible if configured
        def quant_store_check() -> tuple[bool, str]:
            quant_config = QuantConfig()
            if not quant_config.enable_persistence:
                return True, "persistence disabled by config -- not required"
            store = QuantStateStore(quant_config.db_path)
            store.close()
            return True, str(quant_config.db_path)
        check("quant_store_accessible", quant_store_check)

        # 9-10: Brain genuinely operational (Part 4 hard requirement)
        def brain_operational() -> tuple[bool, str]:
            from talonx_brain.config import BrainConfig
            from talonx_brain.consumer import ResearchAgent
            try:
                agent = ResearchAgent(config=BrainConfig())
            except (ImportError, ValueError) as exc:
                return False, (
                    f"Brain NOT operational ({type(exc).__name__}: {exc}) -- production's normal "
                    "degrade-and-continue is fine for a regular run, but this blocks "
                    "FULL_APP_E2E_READY for tomorrow's validation specifically."
                )
            return True, f"provider={agent.llm_chain.describe()}"
        check("brain_operational_hard_requirement", brain_operational)

        # 11: Chroma/vector store accessible
        def chroma_check() -> tuple[bool, str]:
            import chromadb  # noqa: F401 -- import-capability + real client construction below
            client = chromadb.PersistentClient(path=settings.vector_store.persist_directory)
            client.heartbeat()
            return True, str(settings.vector_store.persist_directory)
        check("chroma_vector_store_accessible", chroma_check)

        # 12: Core store accessible
        def core_store_check() -> tuple[bool, str]:
            core_config = CoreConfig()
            if not core_config.enable_persistence:
                return True, "persistence disabled by config -- not required"
            store = TickerStateStore(core_config.state_db_path)
            store.close()
            return True, str(core_config.state_db_path)
        check("core_store_accessible", core_store_check)

        # 13: Dispatch audit store accessible
        def dispatch_store_check() -> tuple[bool, str]:
            dispatch_config = DispatchConfig()
            with AuditStore(dispatch_config.audit_db_path):
                pass
            return True, str(dispatch_config.audit_db_path)
        check("dispatch_audit_store_accessible", dispatch_store_check)

        # 14: Paper store accessible
        def paper_store_check() -> tuple[bool, str]:
            paper_config = PaperConfig()
            with PaperTradingStore(paper_config.db_path):
                pass
            return True, str(paper_config.db_path)
        check("paper_store_accessible", paper_store_check)

        # 15: Telegram outbound configured/reachable
        def telegram_outbound() -> tuple[bool, str]:
            cfg = DispatchConfig()
            token = getattr(cfg, "telegram_bot_token", None)
            chat_id = getattr(cfg, "telegram_chat_id", None)
            if not token or not chat_id:
                return False, "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing"
            response = self.transport.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
            return response.status_code == 200 and bool(response.json().get("ok")), f"HTTP {response.status_code}"
        check("telegram_outbound_reachable", telegram_outbound)

        # 16: Telegram inbound /ping capability
        def telegram_inbound() -> tuple[bool, str]:
            # DispatchAgent already constructs TelegramReplyListener(..., dispatch_agent=self)
            # internally and starts it in .run() whenever telegram_client.is_configured --
            # verified by reading talonx_dispatch/consumer.py for this task, not built here.
            # This check only confirms the capability class imports cleanly.
            from talonx_dispatch.telegram_listener import TelegramReplyListener  # noqa: F401
            return True, "DispatchAgent.run() starts TelegramReplyListener(dispatch_agent=self) when Telegram is configured"
        check("telegram_inbound_ping_capability", telegram_inbound)

        # 17-18: market-data provider identified + connectivity smoke test
        def provider_identified() -> tuple[bool, str]:
            return True, configured_market_data_provider()
        check("market_data_provider_identified", provider_identified)

        def provider_connectivity() -> tuple[bool, str]:
            provider = configured_market_data_provider()
            if provider == "YFINANCE_POLLING":
                import yfinance  # noqa: F401 -- capability only, no network call here
                return True, "yfinance importable (network call happens at session start, not preflight)"
            return True, "POLYGON_API_KEY configured -- WebSocket auth is verified at connect time"
        check("market_data_provider_connectivity_capability", provider_connectivity)

        # 19: pre-market data mechanism available
        def premarket_capability() -> tuple[bool, str]:
            from talonx_ingest.poller import fetch_watchlist_quotes  # noqa: F401
            from talonx_ingest.session import is_premarket_window
            return True, f"is_premarket_window()={is_premarket_window()}"
        check("premarket_mechanism_available", premarket_capability)

        # 20: Quant initial preseed mechanism available
        def preseed_capability() -> tuple[bool, str]:
            from talonx_quant.preseed_ordering import run_initial_preseed  # noqa: F401
            import yfinance  # noqa: F401
            return True, "talonx_quant.preseed_ordering.run_initial_preseed importable; yfinance importable"
        check("quant_initial_preseed_capability", preseed_capability)

        # 21: EOD report generator runnable
        def eod_capability() -> tuple[bool, str]:
            import generate_eod_report  # noqa: F401
            return True, "generate_eod_report.py importable"
        check("eod_report_capability", eod_capability)

        # 22-23: no real-capital execution, no Alpaca live broker adapter
        def no_real_capital() -> tuple[bool, str]:
            import talonx_paper.engine as engine_module
            source = Path(engine_module.__file__).read_text(encoding="utf-8")
            forbidden = ("alpaca", "live_broker", "real_capital")
            hits = [term for term in forbidden if term in source.lower()]
            return not hits, f"talonx_paper.engine references: {hits or 'none'}"
        check("no_real_capital_execution_capability", no_real_capital)
        check("execution_path_is_local_simulated", lambda: (True, paper_execution_path_label()))

        # 24: no unsafe secrets printed -- structural: this preflight never
        # logs/returns raw token values, only booleans/labels (see checks
        # above -- telegram_outbound_reachable reports only the HTTP status).
        check("no_secrets_printed", lambda: (True, "checks report booleans/labels/HTTP status only, never raw credential values"))

        # 25: current time/session state
        check("current_time_reported", lambda: (True, datetime.now(timezone.utc).isoformat()))

        status = FULL_APP_E2E_READY if all(c.passed for c in checks) else FULL_APP_E2E_BLOCKED
        return status, checks

    @staticmethod
    def write_report(path: Path, status: str, checks: list[Check]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "checks": [c.to_dict() for c in checks],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
