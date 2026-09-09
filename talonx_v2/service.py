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
from talonx_v2.calendar import (is_session, next_session_on_or_after,
                                next_session_strictly_after)
from talonx_v2.config import V2_VERSION, V2Config
from talonx_v2.profile import active_profile
from talonx_v2.schemas import V2Action
from talonx_v2.store import V2Store

logger = logging.getLogger("talonx_v2.service")

# Health-heartbeat TTL.  The heartbeat is written on its OWN lightweight
# cadence (``heartbeat_seconds``), decoupled from the strategy evaluation
# cadence (``tick_seconds``) -- so a long strategy poll interval never
# makes the service look "stale" (Task 113 P2 / Task 114 B5).
HEARTBEAT_TTL_S = 180
HEARTBEAT_SECONDS_DEFAULT = 30


class V2SourceError(RuntimeError):
    """The configured live Form-4 source (InsiderStore) could not be read.

    Raised instead of silently substituting the historical research parquet:
    a live tick that cannot see the authoritative feed must fail loudly
    (stale heartbeat, DEGRADED source-health) rather than trade on
    six-month-old fixture data (Task 117 Phase 0 F5).
    """


class V2Service:
    def __init__(self, *, config: V2Config, bar_dirs: list[Path],
                 form4_kind: str = "parquet",
                 form4_parquet: str | None = None,
                 status_path: str | None = None,
                 since: date | None = None,
                 live_lookback_days: int = 45,
                 pricing_mode: str = "csv",
                 router=None, transport=None, deliver: bool = False):
        self.cfg = config
        self.cfg.validate_frozen()
        self.store = V2Store(config.db_path, starting_cash=config.starting_cash_usd)
        self.bar_dirs = bar_dirs
        # official-alert delivery (Task 117 overnight).  ``router`` =
        # talonx_ops.official_dispatch.OfficialExternalRouter; ``transport`` = an
        # injected boundary sink (default: dry-run HOLD).  ``deliver`` gates the
        # per-tick outbox drain -- OFF unless an operator wires a real transport.
        self._router = router
        self._transport = transport
        self._deliver = bool(deliver)
        self._last_delivery: dict = {}
        # Pricing: "csv" (default) = the frozen CSV snapshot, byte-identical to
        # the pre-Task-117 behaviour.  Any other mode routes bar/price lookups
        # through talonx_v2.pricing.make_resolver (strict validation,
        # PROVISIONAL/FINAL, explicit unavailability).  Never auto-enabled for
        # ACTIVE -- an operator opts in with --pricing-mode.
        self.pricing_mode = pricing_mode
        self._as_of_holder = {"d": None}
        self._resolver = None
        if pricing_mode != "csv":
            from talonx_v2 import pricing as _pricing
            self._resolver = _pricing.make_resolver(
                mode=pricing_mode, bar_dirs=[str(p) for p in bar_dirs],
                today=lambda: self._as_of_holder["d"] or datetime.now(timezone.utc).date())
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
        # source-readiness telemetry (Task 117 Phase 0 F4/F5) -- distinct from
        # the process heartbeat; a fresh heartbeat is NOT proof of a good source read.
        self._source_state: dict = {
            "configured": self.form4_kind, "actual": None, "ok": None,
            "records": 0, "since": None, "causal_cutoff": None,
            "last_ok_utc": None, "error": None,
        }

    # ---- bar access ----
    def _bars(self, sym: str) -> list[dict]:
        if self._resolver is not None:
            return self._resolver.bars_lookup(sym)
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
        if self._resolver is not None:
            return self._resolver.price_lookup(sym, session)
        s = session.isoformat() if isinstance(session, date) else str(session)[:10]
        for row in self._bars(sym):
            if row["date"] == s:
                return row
        return None

    # ---- form4 source ----
    def _records(self, *, as_of: date):
        # ``since`` bounds the DISSEMINATION window (contract: "FILING_DATE /
        # EDGAR acceptance"); the adapter re-filters on the acceptance date so a
        # late-filed Form 4 for an older transaction is not dropped (F3).
        since = self.since or (as_of - timedelta(days=self.live_lookback_days))
        # explicit as-of causal cutoff -- for a pinned dry-run/replay this excludes
        # filings accepted after the modelled session; for real live it is
        # end-of-today and excludes nothing (D-adapters requirement).
        cutoff = datetime.combine(as_of, datetime.max.time().replace(microsecond=0),
                                  tzinfo=timezone.utc)
        self._source_state.update(since=since.isoformat(), causal_cutoff=cutoff.isoformat(),
                                  configured=self.form4_kind)

        if self.form4_kind == "insider":
            try:
                from talonx_ingest.intelligence.insider.store import InsiderStore
                st = InsiderStore()  # default ingestion_ledger.db (read side)
                recs = form4_source.from_insider_store(st, since=since, causal_cutoff=cutoff)
            except Exception as exc:  # noqa: BLE001
                self._source_state.update(actual="insider", ok=False, records=0, error=repr(exc))
                logger.error("live Form-4 source (InsiderStore) unavailable: %r -- NOT "
                             "falling back to the historical parquet in live mode", exc)
                raise V2SourceError(f"InsiderStore read failed: {exc!r}") from exc
            self._source_state.update(actual="insider", ok=True, records=len(recs), error=None,
                                      last_ok_utc=datetime.now(timezone.utc).isoformat())
            return recs

        # form4_kind == "parquet": EXPLICIT offline / replay selection only.
        recs = form4_source.from_research_parquet(self.form4_parquet, since=since)
        self._source_state.update(
            actual="parquet", ok=True, records=len(recs), error=None,
            last_ok_utc=datetime.now(timezone.utc).isoformat(),
            note="OFFLINE research parquet -- explicit --form4-source parquet (NOT live)")
        return recs

    # ---- one tick ----
    def tick(self, *, as_of: date | None = None) -> dict:
        self._tick += 1
        today = as_of or datetime.now(timezone.utc).date()
        self._as_of_holder["d"] = today          # pricing resolver's causal "today"
        ripe_through = today if is_session(today) else next_session_on_or_after(today)

        from talonx_v2.calendar import add_sessions

        # Task 117 overnight P3: an unavailable Form-4 SOURCE blocks NEW
        # event-based entries/intents -- but it must NOT block due-exit
        # management of positions that are ALREADY open (those settle on
        # reliable bar prices, independent of the SEC feed).
        source_degraded: str | None = None
        try:
            records = self._records(as_of=today)
        except V2SourceError as exc:
            records = None
            source_degraded = str(exc)
            logger.error("tick %s: SOURCE DEGRADED -- %s (existing positions still "
                         "get due-exit evaluation)", self._tick, exc)

        res = pipeline.ProcessResult()
        self._intents_created = 0
        self._stale_skipped = 0
        episodes: list = []

        all_eps = pipeline.detect_episodes(records, config=self.cfg) if records is not None else []
        all_ripe = [e for e in all_eps if e.eligible_entry_session <= ripe_through]

        # --- PRE-OPEN ENTRY INTENT PASS (Task 117 overnight) ---------------
        # An episode whose eligible entry session has NOT started gets a
        # durable PENDING intent + an ACTIONABLE alert now (before that
        # session's open).  It carries no economic weight -- the fill still
        # runs the unchanged frozen pipeline at the eligible-entry-session
        # OPEN and is then LINKED to this intent (delayed fill notification).
        next_sess = next_session_strictly_after(ripe_through)
        intents_created = 0
        for e in all_eps:
            if not (today < e.eligible_entry_session <= next_sess):
                continue                                   # started/past, or too far ahead
            if self.store.episode_disposition(e.episode_id) in ("ENTERED", "SKIPPED_ENTRY_STALE"):
                continue
            if self.store.entry_intent(e.episode_id) is not None:
                continue
            liq, dec = self._eval_causal_decision(e)
            if dec.action is V2Action.BUY:
                try:
                    planned_exit = add_sessions(e.eligible_entry_session,
                                                self.cfg.hold_trading_days).isoformat()
                except Exception:  # noqa: BLE001
                    planned_exit = ""
                intent = self.store.upsert_entry_intent(
                    e, dec, liq, horizon=self.cfg.hold_trading_days,
                    planned_exit_session=planned_exit)
                intents_created += 1
                self._enqueue_alert(kind="ENTRY_INTENT", episode=e, decision=dec,
                                    intent=intent, extra={
                                        "target_entry_session": e.eligible_entry_session.isoformat(),
                                        "planned_exit_session": planned_exit,
                                        "actionable": True})
        self._intents_created = intents_created

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
                    intent = self.store.entry_intent(e.episode_id)
                    if intent is not None and intent["status"] == "PENDING":
                        self.store.mark_entry_intent(
                            intent["intent_id"], "EXPIRED_STALE",
                            detail=f"entry session {e.eligible_entry_session.isoformat()} went "
                                   f"stale (> {self.cfg.max_entry_staleness_sessions} sessions) "
                                   "before a FINAL entry bar was observed")
                        self._enqueue_alert(kind="ENTRY_STALE", episode=e, decision=None,
                                            intent=intent, extra={"expired": True})
                stale += 1
                continue
            episodes.append(e)
        self._stale_skipped = stale

        for ep in episodes:
            # one noisy symbol must not starve the rest of the tick (Task 117
            # Phase 0 §2).  Nothing is persisted on a raised error, so the
            # episode is simply retried next tick -- no duplicate BUY risk.
            pre_intent = self.store.entry_intent(ep.episode_id)
            n_before = len(res.entries)
            try:
                pipeline.process_episode(ep, store=self.store, bars_lookup=self._bars,
                                         price_lookup=self._price, config=self.cfg, result=res)
            except Exception:  # noqa: BLE001
                logger.exception("episode_processing_failed episode_id=%s symbol=%s",
                                 ep.episode_id, ep.symbol)
                continue
            if len(res.entries) > n_before:
                self._on_entry_recorded(ep, res.entries[-1], pre_intent, ripe_through)
        try:
            n_exits_before = len(res.exits)
            pipeline.settle_due_exits(store=self.store, as_of_session=ripe_through,
                                      price_lookup=self._price, config=self.cfg, result=res)
            for x in res.exits[n_exits_before:]:
                self._on_exit_recorded(x)
        except Exception:  # noqa: BLE001
            logger.exception("settle_due_exits_failed as_of=%s", ripe_through)

        # drain the durable alert outbox (only when an operator wired a transport)
        if self._deliver and self._router is not None:
            try:
                from talonx_v2.delivery import deliver_outbox
                self._last_delivery = deliver_outbox(
                    self.store, router=self._router, transport=self._transport)
            except Exception:  # noqa: BLE001
                logger.exception("deliver_outbox failed")

        status = self._write_status(today, len(records or []), len(episodes), res,
                                    source_degraded=source_degraded)
        return status

    # ---- causal decision + alert helpers (Task 117 overnight) ----
    def _eval_causal_decision(self, ep):
        """Frozen liquidity gate + Brain for ``ep`` using ONLY bars strictly
        before its eligible entry session (identical to what process_episode
        derives -- no economic divergence, just evaluated earlier)."""
        from talonx_v2 import brain_bridge, quant_bridge
        from talonx_v2.liquidity import evaluate_liquidity
        bars = self._bars(ep.symbol) or []
        liq = evaluate_liquidity(bars, entry_session=ep.eligible_entry_session, config=self.cfg)
        sig = quant_bridge.build_signal(ep, liq, config=self.cfg)
        return liq, brain_bridge.contextualize(sig)

    def _enqueue_alert(self, *, kind: str, episode, decision, intent, extra: dict | None = None):
        import hashlib
        extra = extra or {}
        sym = episode.symbol.upper()
        action = {"ENTRY_INTENT": "BUY", "ENTRY_FILL": "BUY",
                  "EXIT_FILL": "SELL", "ENTRY_STALE": "INFO"}[kind]
        ref = (extra.get("position_id") or extra.get("target_entry_session")
               or extra.get("exit_session") or episode.eligible_entry_session.isoformat())
        event_id = hashlib.sha256(f"{episode.episode_id}|{kind}|{ref}".encode()).hexdigest()[:24]
        dedup_key = f"{episode.episode_id}:{action}:{kind}"
        provenance = {
            "episode_id": episode.episode_id, "kind": kind,
            "issuer_cik": episode.issuer_cik,
            "distinct_owner_ciks": list(episode.distinct_owner_ciks),
            "activation_filing_date": episode.activation_filing_date.isoformat(),
            "causal_event_ts": episode.causal_event_ts.isoformat(),
            "eligible_entry_session": episode.eligible_entry_session.isoformat(),
            "intent_id": (intent or {}).get("intent_id"),
            "intent_created_at_utc": (intent or {}).get("created_at_utc"),
            "decision_at_utc": (decision.decided_at.isoformat() if decision is not None else None),
            "enqueued_at_utc": __import__("datetime").datetime.now(timezone.utc).isoformat(),
            **{k: v for k, v in extra.items() if k != "position_id"},
        }
        if kind == "ENTRY_INTENT":
            headline = (f"INSIDER BUY CLUSTER — PLANNED BUY — {sym}  "
                        f"(open of {extra.get('target_entry_session')})")
            body = (f"{decision.rationale}\n"
                    f"ACTIONABLE: a market-on-open paper entry is planned for the OPEN of "
                    f"{extra.get('target_entry_session')} (first XNYS session strictly after the "
                    f"cluster fired). Planned exit {extra.get('planned_exit_session')} "
                    f"(+{self.cfg.hold_trading_days} trading days). Multi-day horizon. Paper only.")
        elif kind == "ENTRY_FILL":
            delayed = extra.get("delayed")
            headline = f"INSIDER BUY CLUSTER — BUY FILLED — {sym}"
            body = (("(delayed notification of a previously-recorded paper intent) "
                     if delayed else "")
                    + f"Paper long opened at the {extra.get('entry_session')} OPEN "
                    f"{extra.get('entry_price')}. Planned exit {extra.get('target_exit_session')}. "
                    f"Paper only. Strategy INSIDER_BUY_CLUSTER_V2@1.")
            if extra.get("backfill"):
                body += (" NOTE: no earlier intent existed (cold-start backfill); the "
                         f"{extra.get('entry_session')} open is a historical price and was "
                         "not prospectively actionable.")
        elif kind == "EXIT_FILL":
            headline = f"INSIDER BUY CLUSTER — SELL / EXIT — {sym}"
            body = (f"Closed the {sym} paper long at the {extra.get('exit_session')} CLOSE "
                    f"{extra.get('exit_price')} ({extra.get('realized_pnl_pct', 0.0):+.2f}%, held "
                    f"{extra.get('trading_days_held')} sessions). Paper only.")
        else:  # ENTRY_STALE
            headline = f"INSIDER BUY CLUSTER — entry expired — {sym}"
            body = (f"The planned {sym} paper entry for {episode.eligible_entry_session.isoformat()} "
                    f"expired without a FINAL entry bar within "
                    f"{self.cfg.max_entry_staleness_sessions} sessions. No position opened. "
                    "Informational only.")
        payload = "\n".join([f"⚡ *{action}* — *{sym}*  INSIDER BUY CLUSTER",
                             "—" * 12, headline, "", body,
                             "", "[INSIDER_BUY_CLUSTER_V2@1 · PAPER_CANDIDATE · PAPER ONLY]"])
        self.store.enqueue_alert(
            event_id=event_id, episode_id=episode.episode_id, kind=kind, action=action,
            symbol=sym, strategy_version="INSIDER_BUY_CLUSTER_V2@1", dedup_key=dedup_key,
            payload_text=payload, provenance=provenance,
            horizon_trading_days=self.cfg.hold_trading_days,
            intent_id=(intent or {}).get("intent_id"), position_id=extra.get("position_id"))

    def _on_entry_recorded(self, ep, entry: dict, pre_intent: dict | None, ripe_through) -> None:
        pos = self.store.position_for_episode(ep.episode_id)
        pid = pos["position_id"] if pos else None
        delayed = pre_intent is not None
        if pre_intent is not None and pre_intent["status"] == "PENDING":
            self.store.mark_entry_intent(
                pre_intent["intent_id"], "FILLED", position_id=pid,
                fill_price=entry["entry_price"], fill_session=entry["entry_session"],
                detail=f"reconciled at the {entry['entry_session']} open")
        self._enqueue_alert(kind="ENTRY_FILL", episode=ep, decision=None,
                            intent=pre_intent, extra={
                                "position_id": pid, "entry_session": entry["entry_session"],
                                "entry_price": entry["entry_price"],
                                "target_exit_session": entry["target_exit_session"],
                                "delayed": delayed, "backfill": pre_intent is None})

    def _on_exit_recorded(self, x: dict) -> None:
        class _E:
            episode_id = x["episode_id"]
            symbol = x["symbol"]
            issuer_cik = ""
            distinct_owner_ciks: tuple = ()
            from datetime import date as _d, datetime as _dt, timezone as _tz
            activation_filing_date = _d.fromisoformat(x["exit_session"])
            causal_event_ts = _dt.now(_tz.utc)
            eligible_entry_session = _d.fromisoformat(x["exit_session"])
        self._enqueue_alert(kind="EXIT_FILL", episode=_E(), decision=None, intent=None,
                            extra={"exit_session": x["exit_session"],
                                   "exit_price": x["exit_price"],
                                   "realized_pnl_pct": x.get("realized_pnl_pct", 0.0),
                                   "trading_days_held": x.get("trading_days_held")})

    def _outbox_summary(self) -> dict:
        rows = self.store.all_outbox()
        by_state: dict[str, int] = {}
        for r in rows:
            by_state[r["state"]] = by_state.get(r["state"], 0) + 1
        return {"total": len(rows), "by_state": by_state,
                "recent": [{"kind": r["kind"], "action": r["action"], "symbol": r["symbol"],
                            "state": r["state"], "attempts": r["attempts"],
                            "transport_ref": r["transport_ref"], "last_error": r["last_error"]}
                           for r in rows[-8:]]}

    def _write_status(self, today: date, n_records: int, n_ripe: int, res,
                      *, source_degraded: str | None = None) -> dict:
        opens = paper.open_position_report(self.store, today)
        unresolved = self.store.unresolved_positions()
        status = {
            "service": "talonx_v2",
            "strategy_version": V2_VERSION,
            "active_profile": active_profile().value,
            "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_ttl_s": HEARTBEAT_TTL_S,
            "heartbeat_kind": "DEGRADED_SOURCE" if source_degraded else "TICK",
            "last_tick_utc": datetime.now(timezone.utc).isoformat(),
            "tick": self._tick,
            "as_of": today.isoformat(),
            "db_path": self.cfg.db_path,
            "form4_source": self.form4_kind,
            "pricing_mode": self.pricing_mode,
            "pricing_adapter": (self._resolver.adapter.name if self._resolver is not None
                                else "csv:frozen_bar_dirs"),
            "pricing_unavailable_recent": (
                sorted({f"{k.split('|')[0]}:{getattr(v, 'reason', '')}"
                        for k, v in list(self._resolver.last.items())[-40:]
                        if not hasattr(v, "open")})[:20]
                if self._resolver is not None else []),
            # source readiness -- separate from the heartbeat (F4): a fresh
            # heartbeat is NOT proof of a complete/current filing read.
            "source": dict(self._source_state, degraded=source_degraded),
            "data_state": "DATA_UNAVAILABLE" if source_degraded else "CURRENT",
            "live_lookback_days": self.live_lookback_days,
            "form4_records_seen": n_records,
            "ripe_episodes_this_tick": n_ripe,
            "stale_entry_skipped_this_tick": getattr(self, "_stale_skipped", 0),
            "entries_this_tick": len(res.entries),
            "exits_this_tick": len(res.exits),
            # pre-open intent + durable alert outbox (Task 117 overnight)
            "entry_intents_created_this_tick": getattr(self, "_intents_created", 0),
            "pending_entry_intents": [
                {"symbol": i["symbol"], "episode_id": i["episode_id"],
                 "target_entry_session": i["target_entry_session"],
                 "created_at_utc": i["created_at_utc"]}
                for i in self.store.pending_entry_intents()],
            "alert_outbox": self._outbox_summary(),
            "last_delivery": self._last_delivery or None,
            "delivery_enabled": self._deliver,
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
