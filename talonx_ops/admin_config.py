"""talonx_ops.admin_config -- Task 102 Phases 8-10.

A minimal, local-only replacement for the *routine* operational config editing
that only ``:8501`` (Streamlit) offered. NOT a broad control panel and NOT a
security model.

Hard constraints (Phase 8):
* every action goes through an **existing, already-validated** store method --
  this module adds no new write primitive of its own;
* strategy / execution / broker / short / Experimental-promotion keys are on an
  explicit **denylist** -- an attempt to touch one is rejected AND audited as a
  refusal (never silently);
* every accepted or rejected write is recorded in an audit log
  (``~/.talonx/admin/config_audit.db``) -- timestamp, key, previous value, new
  value, source, validation result, outcome;
* the caller (``dashboard_web.py``) only registers the routes when the server is
  bound to a loopback host, and every route requires an explicit
  ``confirm: true`` in the request body.

What is exposed (the operational subset, Phase 9):
    watchlist.add / watchlist.remove / watchlist.pause / watchlist.resume /
    watchlist.set_horizon / watchlist.set_paper_trading /
    watchlist.set_paper_trading_long_term / paper.set_trade_allocation /
    paper.set_dca_amount

What is NOT exposed here (stays on :8501 / a future task):
    portfolio resets (destructive), starting-balance edits, long-term research
    views, and -- permanently -- anything on the denylist below.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_HOME = Path.home() / ".talonx"
_AUDIT_DB = _HOME / "admin" / "config_audit.db"

_VALID_HORIZONS = ("INTRADAY", "LONG_TERM", "DUAL_HORIZON")

# ---- denylist: patterns that must NEVER be settable from an operational surface
_DENY_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"atr", r"confluence", r"risk[_ ]?reward", r"\brr\b", r"r:r", r"threshold",
    r"trend", r"min_bars", r"htf", r"sma", r"macd", r"rsi", r"pivot",
    r"trade[_ ]?gate", r"relaxed", r"override", r"promot", r"experimental_.*enable",
    r"enable_external_send", r"telegram.*token", r"broker", r"alpaca", r"real_capital",
    r"short", r"execution", r"order", r"quant_config", r"decision", r"brain",
    r"strategy_param", r"signal_type", r"episode",
))

_ALLOWED_ACTIONS = (
    "watchlist.add", "watchlist.remove", "watchlist.pause", "watchlist.resume",
    "watchlist.set_horizon", "watchlist.set_paper_trading",
    "watchlist.set_paper_trading_long_term",
    "paper.set_trade_allocation", "paper.set_dca_amount",
)

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS config_audit (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    at_utc         TEXT NOT NULL,
    action         TEXT NOT NULL,
    config_key     TEXT NOT NULL,
    previous_value TEXT,
    new_value      TEXT,
    source         TEXT NOT NULL DEFAULT 'admin surface',
    validation     TEXT NOT NULL,
    outcome        TEXT NOT NULL
);
"""


class ConfigDenied(Exception):
    """A denylisted (strategy/execution/…) key was requested."""


class ConfigValidationError(Exception):
    """The request failed operational validation before any write."""


@dataclass(frozen=True)
class ConfigResult:
    ok: bool
    action: str
    config_key: str
    previous_value: Any
    new_value: Any
    validation: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "action": self.action, "config_key": self.config_key,
            "previous_value": self.previous_value, "new_value": self.new_value,
            "validation": self.validation, "outcome": self.outcome,
        }


def is_denylisted(key: str) -> bool:
    k = key or ""
    return any(p.search(k) for p in _DENY_PATTERNS)


# --------------------------------------------------------------------------- #
class ConfigAuditLog:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or _AUDIT_DB)
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_AUDIT_DDL)
        self._conn.commit()

    def record(self, *, action: str, config_key: str, previous_value: Any, new_value: Any,
               validation: str, outcome: str, source: str = "admin surface",
               now: datetime | None = None) -> None:
        self._conn.execute(
            "INSERT INTO config_audit (at_utc, action, config_key, previous_value, new_value, "
            "source, validation, outcome) VALUES (?,?,?,?,?,?,?,?)",
            ((now or datetime.now(timezone.utc)).isoformat(), action, config_key,
             _jstr(previous_value), _jstr(new_value), source, validation, outcome),
        )
        self._conn.commit()

    def tail(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM config_audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


def _jstr(v: Any) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v, default=str)


# --------------------------------------------------------------------------- #
class AdminConfigService:
    """Stateless-ish coordinator. Opens the target stores per call (they migrate
    their own schema on ``__init__`` -- that is their existing behaviour, not a
    new side effect this module introduces) and records every attempt."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        audit_log: ConfigAuditLog | None = None,
        watchlist_factory: Callable[[], Any] | None = None,
        paper_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.home = home or _HOME
        self._audit = audit_log or ConfigAuditLog(self.home / "admin" / "config_audit.db")
        self._wl_factory = watchlist_factory
        self._paper_factory = paper_factory

    # -- store handles ------------------------------------------------------
    def _watchlist(self):
        if self._wl_factory is not None:
            return self._wl_factory()
        from talonx_watchlist.config import WatchlistConfig
        from talonx_watchlist.store import TickerWatchlistStore

        return TickerWatchlistStore(WatchlistConfig().db_path)

    def _paper(self):
        if self._paper_factory is not None:
            return self._paper_factory()
        from talonx_paper.config import PaperConfig
        from talonx_paper.store import PaperTradingStore

        return PaperTradingStore(PaperConfig().db_path)

    # -- the one entry point ---------------------------------------------
    def apply(self, action: str, params: dict[str, Any], *, confirm: bool = False,
              source: str = "admin surface", now: datetime | None = None) -> ConfigResult:
        now = now or datetime.now(timezone.utc)
        key = f"{action}:{params.get('symbol') or params.get('key') or ''}".rstrip(":")

        # 1. denylist / allowlist FIRST -- a strategy/execution/token request must
        # never have its raw param VALUES written to the audit log, whether or
        # not `confirm` was set. Only the param keys are recorded.
        deny_probe = " ".join([action, *[str(v) for v in params.values()], *params.keys()])
        if action not in _ALLOWED_ACTIONS or is_denylisted(deny_probe):
            redacted = {k: "<redacted>" for k in params}
            r = ConfigResult(False, action, key, None, redacted,
                             "denylist / not an allowed operational action", "REFUSED_DENYLIST")
            self._audit.record(action=action, config_key=key, previous_value=None,
                               new_value={"param_keys": sorted(params)},
                               validation=r.validation, outcome=r.outcome, source=source, now=now)
            raise ConfigDenied(r.validation)

        # 2. explicit confirmation (action is now known-safe; its params are
        # watchlist/paper operational values, no secrets)
        if not confirm:
            r = ConfigResult(False, action, key, None, params, "no confirm=true", "REJECTED_UNCONFIRMED")
            self._audit.record(action=action, config_key=key, previous_value=None, new_value=params,
                               validation=r.validation, outcome=r.outcome, source=source, now=now)
            return r

        # 3. dispatch to the existing validated store method
        try:
            prev, new = self._dispatch(action, params)
        except ConfigValidationError as exc:
            r = ConfigResult(False, action, key, None, params, f"validation failed: {exc}", "REJECTED_INVALID")
            self._audit.record(action=action, config_key=key, previous_value=None, new_value=params,
                               validation=r.validation, outcome=r.outcome, source=source, now=now)
            return r
        except Exception as exc:  # noqa: BLE001
            r = ConfigResult(False, action, key, None, params, f"store error: {exc!r}", "FAILED")
            self._audit.record(action=action, config_key=key, previous_value=None, new_value=params,
                               validation=r.validation, outcome=r.outcome, source=source, now=now)
            return r

        r = ConfigResult(True, action, key, prev, new, "ok", "APPLIED")
        self._audit.record(action=action, config_key=key, previous_value=prev, new_value=new,
                           validation="ok", outcome="APPLIED", source=source, now=now)
        return r

    # -- per-action handlers (all delegate to existing validated methods) --
    def _dispatch(self, action: str, p: dict[str, Any]) -> tuple[Any, Any]:
        sym = str(p.get("symbol", "")).strip().upper()
        if action.startswith("watchlist."):
            wl = self._watchlist()
            try:
                if action == "watchlist.add":
                    horizon = str(p.get("horizon", "INTRADAY")).upper()
                    if horizon not in _VALID_HORIZONS:
                        raise ConfigValidationError(f"horizon must be one of {_VALID_HORIZONS}")
                    if not sym:
                        raise ConfigValidationError("symbol is required")
                    before = wl.get_ticker(sym)
                    if before is not None:
                        raise ConfigValidationError(f"{sym} already on the watchlist")
                    wl.add_ticker(sym, str(p.get("name", "")), str(p.get("exchange", "")),
                                  status="paused", strategy_horizon=horizon)
                    return None, {"symbol": sym, "status": "paused", "horizon": horizon}
                before = dict(wl.get_ticker(sym) or {})   # snapshot -- never a live ref
                if not before:
                    raise ConfigValidationError(f"{sym} is not on the watchlist")
                if action == "watchlist.remove":
                    wl.remove_ticker(sym)
                    return before, None
                if action == "watchlist.pause":
                    wl.pause_ticker(sym)
                    return before.get("status"), "paused"
                if action == "watchlist.resume":
                    wl.resume_ticker(sym)
                    return before.get("status"), "active"
                if action == "watchlist.set_horizon":
                    h = str(p.get("horizon", "")).upper()
                    if h not in _VALID_HORIZONS:
                        raise ConfigValidationError(f"horizon must be one of {_VALID_HORIZONS}")
                    prev = before.get("strategy_horizon")
                    wl.set_strategy_horizon(sym, h)
                    return prev, h
                if action == "watchlist.set_paper_trading":
                    enabled = bool(p.get("enabled"))
                    prev = before.get("paper_trading_enabled")
                    wl.set_paper_trading(sym, enabled)
                    return prev, enabled
                if action == "watchlist.set_paper_trading_long_term":
                    enabled = bool(p.get("enabled"))
                    prev = before.get("paper_trading_enabled_long_term")
                    wl.set_paper_trading_long_term(sym, enabled)
                    return prev, enabled
                raise ConfigValidationError(f"unknown watchlist action {action}")
            finally:
                try:
                    wl.close()
                except Exception:  # noqa: BLE001
                    pass
        if action.startswith("paper."):
            ps = self._paper()
            try:
                amount = p.get("amount")
                try:
                    amount = float(amount)
                except (TypeError, ValueError):
                    raise ConfigValidationError("amount must be a number")
                if amount < 10.0:
                    raise ConfigValidationError("amount must be >= 10.0 (matches the :8501 min_value)")
                if action == "paper.set_trade_allocation":
                    prev = ps.get_portfolio_summary().get("trade_allocation_usd")
                    ps.update_trade_allocation(amount)
                    return prev, amount
                if action == "paper.set_dca_amount":
                    prev = ps.get_long_term_portfolio_summary().get("dca_contribution_usd")
                    ps.update_dca_contribution_amount(amount)
                    return prev, amount
                raise ConfigValidationError(f"unknown paper action {action}")
            finally:
                try:
                    ps.close()
                except Exception:  # noqa: BLE001
                    pass
        raise ConfigValidationError(f"unknown action {action}")

    def audit_tail(self, limit: int = 50) -> list[dict]:
        return self._audit.tail(limit)

    def close(self) -> None:
        self._audit.close()


ALLOWED_ACTIONS = _ALLOWED_ACTIONS
DENY_PATTERNS = _DENY_PATTERNS


def loopback_host(host: str | None) -> bool:
    return str(host or "").lower() in ("127.0.0.1", "localhost", "::1", "")
