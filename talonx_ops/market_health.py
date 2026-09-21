"""talonx_ops.market_health -- Task 100B Phase 12.

ONE authoritative, read-only market-health accessor.

Task 100A left market health with three physical derivations (``:8787``
``ChannelStats``, ``:8770`` ``/__health``, ``run_talonx.py`` internal). This
module does not add a fourth producer -- it is a pure *aggregate view* over the
state those three already read:

* ``paper_trading.db`` ``latest_prices`` -- the cross-process price tap (no Redis
  needed): how many symbols are priced and how old the newest tick is.
* ``watchlist.db`` -- configured vs selected/active symbols and coverage.
* ``runtime_metadata.json`` + a live-process check -- is ``run_talonx.py`` (the
  one market-feed owner) actually running.
* an *optional* injected Redis reader (``redis_reader``) for the
  ``talonx:ingest:liveness`` / ``talonx:ingest:ws_heartbeat`` beat -- session
  phase, last-BAR age, active poller, transport (provider / Redis)
  failure+reconnect counters, per-symbol coverage. Omitted in offline tests, in
  which case those fields are ``None`` and never fabricated.

The feed ``state`` vocabulary matches ``talonx_ingest.liveness`` deliberately:
``HEALTHY`` / ``IDLE`` / ``STALE`` / ``DISCONNECTED`` / ``UNKNOWN``.

Nothing here writes. Every read is wrapped so a missing/locked store yields
``UNKNOWN``, never an exception. ``AuthoritativeReadModel.market()`` consumes
this rather than re-deriving producer truth.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_HOME = Path.home() / ".talonx"

# thresholds (seconds)
MARKET_TICK_STALE_AGE = 15 * 60          # newest latest_prices row older than this => STALE
MARKET_BAR_STALE_AGE = 90                # ws_heartbeat BAR age past this, in-session => STALE


@dataclass(frozen=True)
class MarketHealthView:
    state: str                                  # HEALTHY / IDLE / STALE / DISCONNECTED / UNKNOWN
    producer_live: bool
    producer_reason: str
    symbols_priced: int | None = None
    newest_tick: str | None = None
    newest_tick_age_seconds: float | None = None
    last_bar_age_seconds: float | None = None
    session_phase: str | None = None
    active_poller: str | None = None
    configured_symbols: int | None = None
    selected_symbols: int | None = None
    coverage_ratio: float | None = None
    provider_failures: int | None = None
    provider_retries: int | None = None
    redis_failures: int | None = None
    redis_reconnects: int | None = None
    redis_reachable: bool | None = None
    source: str = "talonx_ingest.market_data.manager (via run_talonx.py); taps: paper_trading.db.latest_prices, watchlist.db, talonx:ingest:liveness"
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _q1(con: sqlite3.Connection, sql: str, args: tuple = ()) -> Any:
    try:
        row = con.execute(sql, args).fetchone()
        return row[0] if row is not None else None
    except sqlite3.Error:
        return None


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _q1(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return None


# US regular-session phases in which we DO expect ticks (so quiet => STALE, not IDLE)
_IN_SESSION_PHASES = {"regular", "open", "rth", "regular_hours"}


class MarketHealth:
    """Cheap to construct; opens nothing until :meth:`view` is called.

    ``redis_reader`` -- optional zero-arg callable returning the parsed
    ``talonx:ingest:liveness`` payload dict (or ``None``). Kept injectable so
    offline callers/tests never touch Redis; ``run_talonx.py`` / a dashboard can
    pass a real reader.
    """

    def __init__(
        self,
        *,
        home: Path | None = None,
        runtime_metadata_path: Path | None = None,
        now: datetime | None = None,
        check_processes: bool = True,
        redis_reader: Callable[[], dict | None] | None = None,
        producer_probe: Callable[[], dict] | None = None,
    ) -> None:
        self.home = home or _HOME
        self.runtime_metadata_path = runtime_metadata_path or (self.home / "runtime_metadata.json")
        self.now = now or datetime.now(timezone.utc)
        self.check_processes = check_processes
        self._redis_reader = redis_reader
        self._producer_probe = producer_probe

    # -- producer liveness (delegates to the read model unless a probe is injected)
    def _producer(self) -> dict:
        if self._producer_probe is not None:
            return self._producer_probe()
        try:
            from talonx_ops.authoritative_read_model import AuthoritativeReadModel

            arm = AuthoritativeReadModel(
                home=self.home,
                runtime_metadata_path=self.runtime_metadata_path,
                now=self.now,
                check_processes=self.check_processes,
            )
            return arm.original_producer()
        except Exception as exc:  # noqa: BLE001
            return {"live": False, "reason": f"producer probe error: {exc!r}"}

    def view(self) -> MarketHealthView:
        prod = self._producer()
        notes: list[str] = []

        # --- price tap (offline-safe) ---
        symbols_priced = newest_tick = None
        con = _ro(self.home / "paper_trading.db")
        if con is not None:
            try:
                if _has_table(con, "latest_prices"):
                    symbols_priced = _q1(con, "SELECT COUNT(*) FROM latest_prices") or 0
                    newest_tick = _q1(con, "SELECT MAX(updated_at) FROM latest_prices")
            finally:
                con.close()
        tick_age = _age_seconds(newest_tick, self.now)

        # --- watchlist coverage (offline-safe) ---
        configured = selected = None
        con = _ro(self.home / "watchlist.db")
        if con is not None and _has_table(con, "tickers"):
            try:
                configured = _q1(con, "SELECT COUNT(*) FROM tickers") or 0
                cols = [r[1] for r in con.execute("PRAGMA table_info(tickers)")]
                if "active" in cols:
                    selected = _q1(con, "SELECT COUNT(*) FROM tickers WHERE active=1")
                elif "status" in cols:
                    selected = _q1(con, "SELECT COUNT(*) FROM tickers WHERE status='active'")
            finally:
                con.close()
        elif con is not None:
            con.close()
        coverage_ratio = None
        if configured:
            base = selected if selected is not None else configured
            priced = symbols_priced or 0
            coverage_ratio = round(min(priced, base) / base, 4) if base else None

        # --- optional Redis liveness beat ---
        bar_age = session_phase = active_poller = None
        prov_fail = prov_retry = redis_fail = redis_reconn = None
        redis_reachable = None
        if self._redis_reader is not None:
            try:
                beat = self._redis_reader()
            except Exception as exc:  # noqa: BLE001
                beat = None
                notes.append(f"redis liveness read failed: {exc!r}")
            if isinstance(beat, dict):
                bar_age = beat.get("last_market_event_age_seconds")
                session_phase = beat.get("session_phase")
                active_poller = beat.get("active_poller")
                redis_reachable = beat.get("redis_reachable")
                tc = beat.get("transport_counters") or {}
                if isinstance(tc, dict):
                    prov_fail = tc.get("provider_failures") or tc.get("failures")
                    prov_retry = tc.get("provider_retries") or tc.get("retries")
                    redis_fail = tc.get("redis_failures") or tc.get("publish_failures")
                    redis_reconn = tc.get("redis_reconnects") or tc.get("reconnects")

        # --- derive feed state ---
        state = self._derive_state(prod, tick_age, bar_age, session_phase, notes)

        return MarketHealthView(
            state=state,
            producer_live=bool(prod.get("live")),
            producer_reason=str(prod.get("reason", "")),
            symbols_priced=symbols_priced,
            newest_tick=newest_tick,
            newest_tick_age_seconds=round(tick_age) if tick_age is not None else None,
            last_bar_age_seconds=bar_age,
            session_phase=session_phase,
            active_poller=active_poller,
            configured_symbols=configured,
            selected_symbols=selected,
            coverage_ratio=coverage_ratio,
            provider_failures=prov_fail,
            provider_retries=prov_retry,
            redis_failures=redis_fail,
            redis_reconnects=redis_reconn,
            redis_reachable=redis_reachable,
            notes=tuple(notes),
        )

    def _derive_state(
        self,
        prod: dict,
        tick_age: float | None,
        bar_age: float | None,
        session_phase: str | None,
        notes: list[str],
    ) -> str:
        if not prod.get("live"):
            notes.append(f"run_talonx.py not running ({prod.get('reason', '')}) -- market data below is a stale projection")
            return "DISCONNECTED"
        in_session = (session_phase or "").lower() in _IN_SESSION_PHASES
        # prefer the BAR-age signal (Redis) when present; else fall back to the price-tap age
        age = bar_age if bar_age is not None else tick_age
        if age is None:
            return "UNKNOWN" if tick_age is None else "IDLE"
        if session_phase is None:
            # no session context: only the coarse price-tap threshold is meaningful
            return "STALE" if (tick_age is not None and tick_age > MARKET_TICK_STALE_AGE) else "HEALTHY"
        if in_session:
            threshold = MARKET_BAR_STALE_AGE if bar_age is not None else MARKET_TICK_STALE_AGE
            return "STALE" if age > threshold else "HEALTHY"
        # legitimately quiet (pre/after-hours, closed, weekend)
        return "IDLE"


def market_health_view(**kwargs: Any) -> MarketHealthView:
    """Convenience wrapper: ``MarketHealth(**kwargs).view()``."""
    return MarketHealth(**kwargs).view()
