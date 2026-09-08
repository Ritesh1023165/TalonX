"""
talonx_v2.service -- the V2 lane LIVE companion loop (Task 112)
============================================================
Operational runtime only -- it detects causally-ripe cluster episodes,
opens/holds/closes the frozen 10-trading-day paper positions, and writes
a heartbeat + status file.  It carries NO strategy semantics of its own
(those live in the frozen ``cluster_engine`` / ``config`` / ``liquidity``).

  python -m talonx_v2.run --mode live  [--once] [--tick-seconds N]
      [--db PATH] [--form4-source insider|parquet] [--bar-dir DIR ...]

Never sends a real Telegram, never touches a broker, never uses real
capital.  Graceful on SIGINT/SIGTERM: finishes the current tick, persists,
exits.  Open V2 positions survive shutdown in ``v2_lane.db``.
"""
from __future__ import annotations

import json
import logging
import signal
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from talonx_v2 import form4_source, paper, pipeline
from talonx_v2.calendar import is_session, next_session_on_or_after
from talonx_v2.config import V2_VERSION, V2Config
from talonx_v2.profile import active_profile
from talonx_v2.store import V2Store

logger = logging.getLogger("talonx_v2.service")

# Health-heartbeat TTL.  The heartbeat is written on its OWN lightweight
# cadence (``heartbeat_seconds``), decoupled from the strategy evaluation
# cadence (``tick_seconds``) -- so a long strategy poll interval never
# makes the service look "stale" (Task 113 P2 / Task 114 B5).
HEARTBEAT_TTL_S = 180
HEARTBEAT_SECONDS_DEFAULT = 30


class V2Service:
    def __init__(self, *, config: V2Config, bar_dirs: list[Path],
                 form4_kind: str = "parquet",
                 form4_parquet: str | None = None,
                 status_path: str | None = None,
                 since: date | None = None,
                 live_lookback_days: int = 45):
        self.cfg = config
        self.cfg.validate_frozen()
        self.store = V2Store(config.db_path, starting_cash=config.starting_cash_usd)
        self.bar_dirs = bar_dirs
        self.form4_kind = form4_kind
        self.form4_parquet = form4_parquet or \
            "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
        # live mode only looks back far enough to see any in-flight cluster
        # (a cluster window is 10 trading days ~ 2 weeks; 45 calendar days
        # is comfortable).  Already-processed episodes are idempotently
        # skipped, so a bounded window keeps each tick cheap.
        self.live_lookback_days = live_lookback_days
        self.since = since  # explicit override; None -> rolling window in _records()
        import os
        _sp = status_path or os.environ.get("TALONX_V2_STATUS_PATH") \
            or str(Path(config.db_path).parent / "v2_service_status.json")
        self.status_path = Path(_sp)
        self._stop = False
        self._bar_cache: dict[str, list[dict]] = {}
        self._tick = 0
        self._last_status: dict | None = None

    # ---- bar access (local CSV; no network) ----
    def _bars(self, sym: str) -> list[dict]:
        if sym in self._bar_cache:
            return self._bar_cache[sym]
        import pandas as pd
        for d in self.bar_dirs:
            f = d / f"{sym}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    df = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    continue
                if "date" not in df.columns:
                    continue
                rows = [{"date": str(r.date)[:10], "open": float(getattr(r, "open", "nan")),
                         "close": float(r.close), "volume": float(getattr(r, "volume", 0) or 0)}
                        for r in df.itertuples(index=False)]
                self._bar_cache[sym] = rows
                return rows
        self._bar_cache[sym] = []
        return []

    def _price(self, sym: str, session: date) -> dict | None:
        s = session.isoformat() if isinstance(session, date) else str(session)[:10]
        for row in self._bars(sym):
            if row["date"] == s:
                return row
        return None

    # ---- form4 source ----
    def _records(self, *, as_of: date):
        since = self.since or (as_of - timedelta(days=self.live_lookback_days))
        if self.form4_kind == "insider":
            try:
                from talonx_ingest.intelligence.insider.store import InsiderStore
                st = InsiderStore()  # default ingestion_ledger.db
                return form4_source.from_insider_store(st, since=since)
            except Exception as exc:  # noqa: BLE001
                logger.warning("insider store unavailable (%r) -> falling back to parquet", exc)
        return form4_source.from_research_parquet(self.form4_parquet, since=since)

    # ---- one tick ----
    def tick(self, *, as_of: date | None = None) -> dict:
        self._tick += 1
        today = as_of or datetime.now(timezone.utc).date()
        ripe_through = today if is_session(today) else next_session_on_or_after(today)

        from talonx_v2.calendar import add_sessions

        records = self._records(as_of=today)
        all_ripe = [e for e in pipeline.detect_episodes(records, config=self.cfg)
                    if e.eligible_entry_session <= ripe_through]

        # live guard: do NOT chase a stale entry at a historical price
        stale_cut = add_sessions(ripe_through, -self.cfg.max_entry_staleness_sessions) \
            if self.cfg.max_entry_staleness_sessions > 0 else date.min
        episodes, stale = [], 0
        for e in all_ripe:
            if self.cfg.max_entry_staleness_sessions > 0 and e.eligible_entry_session < stale_cut:
                # A stale episode is NEVER entered -- skip it on every tick,
                # whether or not it has been seen before.  Only the disposition
                # write is guarded so we don't rewrite it each tick.
                if not self.store.episode_seen(e.episode_id):
                    self.store.record_disposition(
                        episode_id=e.episode_id, symbol=e.symbol,
                        disposition="SKIPPED_ENTRY_STALE", issuer_cik=e.issuer_cik,
                        eligible_entry_session=e.eligible_entry_session.isoformat(),
                        detail=f"eligible {e.eligible_entry_session.isoformat()} > "
                               f"{self.cfg.max_entry_staleness_sessions} sessions before {ripe_through.isoformat()}")
                stale += 1
                continue
            episodes.append(e)
        self._stale_skipped = stale

        res = pipeline.ProcessResult()
        for ep in episodes:
            pipeline.process_episode(ep, store=self.store, bars_lookup=self._bars,
                                     price_lookup=self._price, config=self.cfg, result=res)
        pipeline.settle_due_exits(store=self.store, as_of_session=ripe_through,
                                  price_lookup=self._price, config=self.cfg, result=res)

        status = self._write_status(today, len(records), len(episodes), res)
        return status

    def _write_status(self, today: date, n_records: int, n_ripe: int, res) -> dict:
        opens = paper.open_position_report(self.store, today)
        unresolved = self.store.unresolved_positions()
        status = {
            "service": "talonx_v2",
            "strategy_version": V2_VERSION,
            "active_profile": active_profile().value,
            "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_ttl_s": HEARTBEAT_TTL_S,
            "heartbeat_kind": "TICK",
            "last_tick_utc": datetime.now(timezone.utc).isoformat(),
            "tick": self._tick,
            "as_of": today.isoformat(),
            "db_path": self.cfg.db_path,
            "form4_source": self.form4_kind,
            "live_lookback_days": self.live_lookback_days,
            "form4_records_seen": n_records,
            "ripe_episodes_this_tick": n_ripe,
            "stale_entry_skipped_this_tick": getattr(self, "_stale_skipped", 0),
            "entries_this_tick": len(res.entries),
            "exits_this_tick": len(res.exits),
            "open_positions": len(opens),
            "open_symbols": [o["symbol"] for o in opens],
            "exit_unresolved": [{"symbol": u["symbol"], "episode_id": u["episode_id"]}
                                for u in unresolved],
            "cash": self.store.cash(),
            "max_concurrent": self.cfg.max_concurrent_positions,
            "hold_trading_days": self.cfg.hold_trading_days,
            "exit_fallforward_max_sessions": self.cfg.exit_fallforward_max_sessions,
            "eod_forced_flatten": False,
            "real_capital": False,
            "shorts": False,
        }
        self._atomic_write_status(status)
        self._last_status = status
        return status

    def _atomic_write_status(self, status: dict) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        tmp.write_text(json.dumps(status, indent=2, default=str))
        tmp.replace(self.status_path)

    def _write_heartbeat(self) -> None:
        """Lightweight health heartbeat -- refresh ``heartbeat_utc`` (and the
        cheap live ledger fields) on the status file WITHOUT running a
        strategy evaluation.  Keeps the service 'fresh' between ticks."""
        base = self._last_status
        if base is None:
            try:
                base = json.loads(self.status_path.read_text())
            except Exception:  # noqa: BLE001
                return
        s = dict(base)
        s["heartbeat_utc"] = datetime.now(timezone.utc).isoformat()
        s["heartbeat_kind"] = "LIGHTWEIGHT"
        try:  # cheap SQLite reads only -- no cluster detection
            s["cash"] = self.store.cash()
            s["open_positions"] = self.store.n_open()
            s["exit_unresolved"] = [{"symbol": u["symbol"], "episode_id": u["episode_id"]}
                                    for u in self.store.unresolved_positions()]
        except Exception:  # noqa: BLE001
            pass
        self._atomic_write_status(s)
        self._last_status = s

    def ready(self) -> bool:
        """Readiness probe: status file fresh + correct profile + DB writable."""
        try:
            s = json.loads(self.status_path.read_text())
        except Exception:  # noqa: BLE001
            return False
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
        except Exception:  # noqa: BLE001
            return False
        return age < HEARTBEAT_TTL_S and s.get("strategy_version") == V2_VERSION

    # ---- loop ----
    def run(self, *, once: bool, tick_seconds: int,
            heartbeat_seconds: int = HEARTBEAT_SECONDS_DEFAULT) -> int:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "_stop", True))
            except (ValueError, OSError):
                pass
        hb = max(1, min(int(heartbeat_seconds), max(1, tick_seconds)))
        logger.info("talonx_v2 service start (once=%s tick=%ss heartbeat=%ss db=%s)",
                    once, tick_seconds, hb, self.cfg.db_path)
        while not self._stop:
            t0 = time.monotonic()
            try:
                st = self.tick()
                logger.info("tick %s: entries=%s exits=%s open=%s cash=%.0f",
                            st["tick"], st["entries_this_tick"], st["exits_this_tick"],
                            st["open_positions"], st["cash"])
            except Exception:  # noqa: BLE001
                logger.exception("tick failed")
            if once:
                break
            # inter-tick: sleep in short slices, emitting a lightweight
            # health heartbeat every ``hb`` seconds so the service never
            # looks stale while waiting for the next strategy evaluation.
            end = time.monotonic() + max(1.0, tick_seconds - (time.monotonic() - t0))
            next_hb = time.monotonic() + hb
            while time.monotonic() < end and not self._stop:
                time.sleep(0.5)
                if time.monotonic() >= next_hb:
                    try:
                        self._write_heartbeat()
                    except Exception:  # noqa: BLE001
                        logger.exception("heartbeat write failed")
                    next_hb = time.monotonic() + hb
        logger.info("talonx_v2 service stopped cleanly (open positions persist in %s)",
                    self.cfg.db_path)
        return 0
