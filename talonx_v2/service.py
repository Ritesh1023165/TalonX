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


def _env_flag(name: str, *, default: bool) -> bool:
    import os
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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
                 router=None, transport=None, deliver: bool = False,
                 execution_allowlist: list[str] | None = None,
                 broad_discovery_symbols: list[str] | None = None):
        self.cfg = config
        self.cfg.validate_frozen()
        self.store = V2Store(config.db_path, starting_cash=config.starting_cash_usd)
        self.bar_dirs = bar_dirs
        # EXECUTION SCOPE ENFORCEMENT (Task 117 final activation).  When set, ONLY
        # issuers whose symbol is in this allowlist are considered for a cluster /
        # entry -- enforced in code, not merely described.  The InsiderStore can
        # carry a broad historical backfill; this pins the live execution universe
        # to the approved, resolved, SEC-covered set.
        #   None  -> unrestricted (offline replay / tests only)
        #   []    -> FAIL CLOSED: an empty allowlist enters NOTHING -- it must
        #            NEVER silently become unrestricted.
        self.execution_allowlist = (None if execution_allowlist is None
                                    else frozenset(s.upper() for s in execution_allowlist))
        if self.execution_allowlist is not None and not self.execution_allowlist:
            logger.warning("V2 execution allowlist is EMPTY -- fail closed: no issuer will "
                           "ever be entered until a non-empty scope is supplied")
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
        # Task 131 Remediation Directive 2: missing-price handling is a
        # non-blocking, cross-tick PENDING_RETRY state -- never a
        # time.sleep loop inside tick(). See _phase_open.
        self._pending_retry_episodes: list[dict] = []
        # Task 131 Remediation Directive 3: (symbol, filing_date_iso) ->
        # latest real wall-clock dissemination timestamp observed this
        # tick. Empty for a date-only source (parquet) or before the
        # first successful "insider" tick -- _verify_temporal_boundary
        # treats a missing entry as "unknown, skip the check", never a
        # fabricated pass or fail.
        self._dissemination_lookup: dict[tuple[str, str], datetime] = {}
        # Final Remediation Directive 1: True only for a tick where
        # _refresh_dissemination_lookup ACTUALLY ran against the real
        # InsiderStore this tick -- distinct from ``form4_kind ==
        # "insider"`` alone, since many tests (and some operational
        # tooling) override ``_records`` directly, bypassing the real
        # fetch entirely. The strict "unknown timestamp -> fail" rule
        # below applies only when a genuine live-data fetch happened and
        # STILL came up empty for a specific episode -- never to a
        # bypassed/mocked/replayed records path.
        self._dissemination_lookup_refreshed_this_tick = False
        self._capacity_rejected = 0
        # Targeted Remediation Directive 2: episodes refused a NEW
        # PENDING intent at admission time because the target session's
        # own RTH open had already passed the moment admission was
        # evaluated (live ticks only) -- distinct from _capacity_rejected
        # (which refuses for lack of cash/slots, not timing).
        self._admission_deadline_rejected = 0
        # Task 131 Remediation Directive 6: the Task 131 durable-lifecycle
        # RUNTIME BEHAVIOR changes (requiring a durable PENDING intent
        # before any entry -- no cold-start backfill -- and the hard
        # capacity-reservation gate at intent-creation time) are gated
        # behind this explicit, OFF-by-default flag. This does NOT gate
        # WAL/SQLite durability itself (V2Store has used WAL since Task
        # 110, predating this integration entirely, and reverting that
        # would be a real regression, not a safety rollback) -- only the
        # NEW admission-policy behavior this integration introduces. OFF
        # (default) reproduces the exact pre-Task-131 permissive entry
        # policy; ON enables the corrected, gated policy.
        self.durable_store_gate_enabled = _env_flag("TALONX_V2_DURABLE_STORE_ENABLED", default=False)
        self._no_prior_intent_skipped = 0
        # Package 2 acceptance A1: episodes refused a NEW PENDING intent
        # (reservation) at admission time because the account carries an
        # active, serious integrity block -- UNCONDITIONAL (unlike
        # _capacity_rejected, never gated behind durable_store_gate_
        # enabled): a serious account block is a safety mechanism, not
        # an opt-in admission-policy refinement, and must apply
        # regardless of which lifecycle-policy variant is active.
        self._account_blocked_intent_rejected = 0
        # Task 131 Directive 5: symbols whose alerts should be tagged
        # BROAD_DISCOVERY origin for the dispatcher's own, independent
        # toggle -- empty by default (byte-identical routing for every
        # symbol unless explicitly populated by the caller, e.g. run.py's
        # --enable-broad-discovery wiring).
        self.broad_discovery_symbols = frozenset(
            s.upper() for s in (broad_discovery_symbols or ()))

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

    def _resilient_price_lookup(self, *, live: bool):
        """Price-lookup callable for this tick's entry/exit resolution.

        Task 131 Remediation Directive 2: this makes EXACTLY ONE, non-
        blocking attempt per tick -- never a ``time.sleep`` loop inside
        ``tick()``. A missing price on a live tick is NOT immediately
        terminal (see ``_phase_open``'s ``PENDING_RETRY`` handling below):
        the SAME intent is simply re-attempted, at zero extra cost, on
        the service's own next natural tick (already a non-blocking
        cadence -- ``run()``'s own inter-tick wait, unchanged). This
        replaces the earlier bounded in-tick retry loop (which could
        block the entire service, including due-exit processing for
        OTHER positions, for up to 5 minutes on one missing price)."""
        return self._price

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
                self._refresh_dissemination_lookup(st, since=since, causal_cutoff=cutoff)
            except Exception as exc:  # noqa: BLE001
                self._source_state.update(actual="insider", ok=False, records=0, error=repr(exc))
                logger.error("live Form-4 source (InsiderStore) unavailable: %r -- NOT "
                             "falling back to the historical parquet in live mode", exc)
                raise V2SourceError(f"InsiderStore read failed: {exc!r}") from exc
            recs = self._apply_execution_allowlist(recs, stage="records")
            self._source_state.update(actual="insider", ok=True, records=len(recs), error=None,
                                      last_ok_utc=datetime.now(timezone.utc).isoformat())
            return recs

        # form4_kind == "parquet": EXPLICIT offline / replay selection only.
        # A date-only source has no real wall-clock dissemination timestamp
        # -- the lookup is explicitly empty (never fabricated).
        self._dissemination_lookup = {}
        recs = form4_source.from_research_parquet(self.form4_parquet, since=since)
        recs = self._apply_execution_allowlist(recs, stage="records")
        self._source_state.update(
            actual="parquet", ok=True, records=len(recs), error=None,
            last_ok_utc=datetime.now(timezone.utc).isoformat(),
            note="OFFLINE research parquet -- explicit --form4-source parquet (NOT live)")
        return recs

    def _refresh_dissemination_lookup(self, insider_store, *, since: date,
                                      causal_cutoff: datetime) -> None:
        """Task 131 Remediation Directive 3: the REAL SEC EDGAR wall-clock
        dissemination timestamp for every open-market (code P) transaction
        currently in this tick's own causal window, keyed by
        ``(symbol, filing_date_iso)`` -> the LATEST ``accepted_at_utc``
        observed for that issuer/day (a conservative choice -- using the
        latest, not earliest, never UNDER-estimates how late information
        became available). Queried directly against the SAME InsiderStore
        ``_records()`` already reads from -- a separate, lightweight local
        SQLite read, not a new network call. Entirely contained in this
        operational module; the frozen cluster_engine.PurchaseRecord/
        ClusterEpisode shapes are never touched."""
        from talonx_ingest.intelligence.insider.domain import TransactionClass
        lookup: dict[tuple[str, str], datetime] = {}
        try:
            txns = insider_store.query_transactions(
                classification=TransactionClass.OPEN_MARKET_PURCHASE,
                since=since, causal_cutoff=causal_cutoff, newest_first=False)
        except Exception:  # noqa: BLE001 -- best-effort; the boundary check simply no-ops without it
            logger.exception("dissemination_lookup_refresh_failed")
            self._dissemination_lookup = {}
            return
        for t in txns:
            if not t.symbol or not t.accepted_at_utc:
                continue
            fd = t.filing_date or t.accepted_at_utc.date()
            key = (t.symbol.upper(), fd.isoformat())
            prev = lookup.get(key)
            if prev is None or t.accepted_at_utc > prev:
                lookup[key] = t.accepted_at_utc
        self._dissemination_lookup = lookup
        # a genuine, successful query against the real InsiderStore ran --
        # from here on, "no matching record" for a specific episode means
        # it genuinely was not found, not merely "we never looked."
        self._dissemination_lookup_refreshed_this_tick = True

    def _apply_execution_allowlist(self, items, *, stage: str):
        """Drop anything whose issuer symbol is not in the approved execution
        allowlist.  ``items`` is a list of PurchaseRecord (stage='records') or
        ClusterEpisode (stage='episodes').  No-op when no allowlist is set."""
        if self.execution_allowlist is None:
            return items
        kept, dropped = [], []
        for it in items:
            sym = getattr(it, "symbol", "").upper()
            (kept if sym in self.execution_allowlist else dropped).append(it)
        if dropped:
            self._allowlist_dropped = getattr(self, "_allowlist_dropped", 0) + len(dropped)
            logger.info("execution allowlist: dropped %d out-of-scope %s (e.g. %s); kept %d",
                        len(dropped), stage,
                        sorted({getattr(d, "symbol", "?") for d in dropped})[:8], len(kept))
        return kept

    # ---- one tick -- four explicit phases (Task 131 Directive 2/7) ----
    # OPEN        -- resolve entries ONLY for episodes with a durable PENDING
    #                intent that already existed before this tick began.
    # CLOSE       -- settle due exits at this tick's prices (after OPEN, so a
    #                same-tick exit's proceeds can never fund a same-tick entry).
    # POST-CLOSE  -- NOW record staleness terminal dispositions and create NEW
    #                PENDING intents (reservations) for future sessions, using
    #                this tick's own freshly-detected episodes.
    # MARK        -- mark every still-open position for observability.
    def tick(self, *, as_of: date | None = None) -> dict:
        self._tick += 1
        today = as_of or datetime.now(timezone.utc).date()
        self._as_of_holder["d"] = today          # pricing resolver's causal "today"
        ripe_through = today if is_session(today) else next_session_on_or_after(today)
        live = as_of is None                     # true live wall-clock tick vs. pinned replay/dry-run

        from talonx_v2.calendar import add_sessions

        # reset per-tick counters BEFORE _records() so the records-stage
        # execution-allowlist drop count is included in this tick's status.
        self._intents_created = 0
        self._stale_skipped = 0
        self._allowlist_dropped = 0
        self._no_prior_intent_skipped = 0
        self._pending_retry_episodes = []
        self._capacity_rejected = 0
        self._admission_deadline_rejected = 0
        self._account_blocked_intent_rejected = 0
        self._dissemination_lookup_refreshed_this_tick = False

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

        all_eps = pipeline.detect_episodes(records, config=self.cfg) if records is not None else []
        # defense-in-depth: even if a record slipped through, no episode outside
        # the approved execution scope is ever considered for a cluster/entry.
        all_eps = self._apply_execution_allowlist(all_eps, stage="episodes")
        all_ripe = [e for e in all_eps if e.eligible_entry_session <= ripe_through]

        stale_cut = add_sessions(ripe_through, -self.cfg.max_entry_staleness_sessions) \
            if self.cfg.max_entry_staleness_sessions > 0 else date.min

        def _is_stale(e) -> bool:
            return self.cfg.max_entry_staleness_sessions > 0 and e.eligible_entry_session < stale_cut

        ripe_attemptable = [e for e in all_ripe if not _is_stale(e)]
        price_lookup = self._resilient_price_lookup(live=live)

        # --- PHASE OPEN ------------------------------------------------
        self._phase_open(ripe_attemptable, ripe_through, res, price_lookup=price_lookup,
                         today=today, live=live)

        # --- PHASE CLOSE -------------------------------------------------
        self._phase_close(ripe_through, res, price_lookup=price_lookup)

        # --- PHASE POST-CLOSE --------------------------------------------
        self._phase_post_close(all_eps, all_ripe, today, ripe_through, _is_stale, live=live)

        # --- PHASE MARK ----------------------------------------------------
        marks = self._phase_mark(today)

        # drain the durable alert outbox (only when an operator wired a transport).
        # For a PINNED as-of tick (replay / dry-run) the delivery clock is that
        # session ~close, so notification deadlines are evaluated on the modelled
        # timeline; a live tick (as_of is None) uses the real wall clock.
        if self._deliver and self._router is not None:
            try:
                from datetime import time as _time

                from talonx_v2.delivery import deliver_outbox
                deliver_now = (None if as_of is None else
                               datetime.combine(today, _time(20, 0), tzinfo=timezone.utc))
                self._last_delivery = deliver_outbox(
                    self.store, router=self._router, transport=self._transport,
                    now=deliver_now, broad_discovery_symbols=self.broad_discovery_symbols)
            except Exception:  # noqa: BLE001
                logger.exception("deliver_outbox failed")

        status = self._write_status(today, len(records or []), len(ripe_attemptable), res,
                                    source_degraded=source_degraded, marks=marks)
        return status

    def _phase_open(self, episodes: list, ripe_through: date, res, *, price_lookup,
                    today: date, live: bool = False) -> None:
        """Resolve entries ONLY for episodes carrying an existing durable
        PENDING intent (necessarily created by an EARLIER tick's own
        POST-CLOSE pass -- intent creation only ever targets a FUTURE
        session, so a PENDING intent visible here was structurally
        impossible to have been created this same tick). An episode with
        no valid prior intent is never entered cold -- it is recorded
        SKIPPED_NO_PRIOR_INTENT (Task 131 Directive 2, matching the
        corrected Task 130A/130B research contract) instead of the
        previous permissive cold-start-backfill behaviour."""
        from talonx_v2.calendar import add_sessions
        no_prior = 0
        gate_enabled = self.durable_store_gate_enabled
        for ep in episodes:
            intent = self.store.entry_intent(ep.episode_id)
            if gate_enabled and (intent is None or intent["status"] != "PENDING"):
                # the intent-creation window (PHASE POST-CLOSE, below) stays
                # open THROUGH the eligible entry session itself (today <=
                # eligible), so an episode whose entry session is TODAY may
                # still legitimately receive its first PENDING intent this
                # very tick's own post-close -- fillable on a LATER tick.
                # Only once that window has definitively closed (today has
                # moved PAST the eligible session with no intent ever
                # created) is the miss permanent and worth a terminal write.
                if ep.eligible_entry_session < today and not self.store.episode_seen(ep.episode_id):
                    self.store.record_disposition(
                        episode_id=ep.episode_id, symbol=ep.symbol,
                        disposition="SKIPPED_NO_PRIOR_INTENT", issuer_cik=ep.issuer_cik,
                        eligible_entry_session=ep.eligible_entry_session.isoformat(),
                        detail="no durable PENDING intent existed before this tick's OPEN "
                               "phase, and the intent-creation window has closed -- a "
                               "cold-start entry is never admitted (Task 131 Directive 2; "
                               "TALONX_V2_DURABLE_STORE_ENABLED=true)")
                no_prior += 1
                continue
            # gate_enabled=False (the current default): pre_intent may be
            # None (a genuine cold-start backfill) -- reproducing the
            # EXACT pre-Task-131 permissive policy, unchanged, until an
            # operator explicitly opts into the corrected one.
            pre_intent = intent
            # Task 131 Remediation Directive 3 / Final Remediation
            # Directive 1: an explicit, enforced check (never merely
            # assumed) that this episode's own activating filing -- AND
            # its own durable intent's creation -- occurred BEFORE its
            # entry session's own RTH open. Given the frozen entry_offset_
            # sessions=1 contract this should always hold structurally --
            # but it is verified here, not just implied, and a violation
            # refuses the entry outright rather than silently proceeding
            # on stale timing assumptions.
            boundary_ok, boundary_detail = self._verify_temporal_boundary(ep, pre_intent, live=live)
            if not boundary_ok:
                self.store.record_disposition(
                    episode_id=ep.episode_id, symbol=ep.symbol,
                    disposition="SKIPPED_TEMPORAL_BOUNDARY_VIOLATION", issuer_cik=ep.issuer_cik,
                    eligible_entry_session=ep.eligible_entry_session.isoformat(),
                    detail=boundary_detail)
                # Final Remediation Directive 3: pre_intent is None in a
                # genuine legacy-mode (gate disabled) cold start -- guard
                # before subscripting it, never crash the tick.
                if pre_intent is not None:
                    self.store.mark_entry_intent(
                        pre_intent["intent_id"], "REJECTED_TEMPORAL_BOUNDARY_VIOLATION",
                        detail=boundary_detail)
                logger.error("temporal_boundary_violation episode_id=%s symbol=%s detail=%s",
                            ep.episode_id, ep.symbol, boundary_detail)
                continue
            n_before = len(res.entries)
            n_skipped_before = len(res.skipped)
            # Final Remediation Directive 2: the entry attempt (capacity
            # re-check inside enter_position + position insert + cash
            # debit + trade record + disposition, all already atomic via
            # paper.enter_position's own store.transaction()) AND the
            # subsequent PENDING -> FILLED intent-status update now
            # commit as ONE outer atomic unit -- V2Store.transaction() is
            # reentrant, so enter_position's own inner transaction() call
            # joins this outer one rather than opening a second one. A
            # crash between "position committed" and "intent marked
            # FILLED" can no longer happen -- both commit together, or
            # neither does.
            #
            # one noisy symbol must not starve the rest of the tick (Task
            # 117 Phase 0 §2).  Nothing is persisted on a raised error, so
            # the episode is simply retried next tick -- no duplicate BUY risk.
            try:
                with self.store.transaction():
                    pipeline.process_episode(ep, store=self.store, bars_lookup=self._bars,
                                             price_lookup=price_lookup, config=self.cfg, result=res)
                    if len(res.entries) > n_before:
                        self._on_entry_recorded(ep, res.entries[-1], pre_intent, ripe_through)
            except Exception:  # noqa: BLE001
                logger.exception("episode_processing_failed episode_id=%s symbol=%s",
                                 ep.episode_id, ep.symbol)
                continue
            if len(res.entries) > n_before:
                continue
            new_skips = res.skipped[n_skipped_before:]
            if not any(s.get("reason") == "NO_ENTRY_BAR" for s in new_skips):
                continue
            # Task 131 Remediation Directive 2: a missing entry bar is NOT
            # immediately escalated -- the durable PENDING intent is left
            # exactly as is (never touched, never blocked-on with a sleep)
            # and this episode is surfaced as PENDING_RETRY for this tick's
            # observability. Because the intent stays 'PENDING' in the
            # store, phase_open will naturally re-attempt it on the very
            # next tick -- a non-blocking, zero-extra-cost retry driven by
            # the service's own existing tick cadence, not an in-call
            # sleep loop. Final Remediation Directive 3: retained through
            # the APPROVED session-based recovery window -- one session
            # SHORT of max_entry_staleness_sessions (the SAME, already-
            # frozen operational parameter the pre-existing staleness
            # guard uses, 3 sessions by default), not just the one
            # immediate next session. This offset is deliberate, not
            # arbitrary: the staleness guard EXCLUDES a stale episode from
            # ripe_attemptable entirely (it never reaches this method
            # again) the moment ripe_through > eligible + max_entry_
            # staleness_sessions -- using that SAME threshold here would
            # make this escalation UNREACHABLE (staleness would always
            # win the race, one phase earlier in the very same tick).
            # Ending the retry window one session earlier guarantees this
            # escalation gets a genuine, reachable chance to release the
            # intent as FAILED_NO_MARKET_DATA before the coarser,
            # unrelated staleness guard would ALSO have swept it up as
            # EXPIRED_STALE. Only once this window has fully elapsed with
            # no price ever found is the miss escalated (released exactly
            # once).
            retry_deadline = add_sessions(ep.eligible_entry_session,
                                          max(0, self.cfg.max_entry_staleness_sessions - 1))
            if ripe_through <= retry_deadline:
                self._pending_retry_episodes.append({
                    "episode_id": ep.episode_id, "symbol": ep.symbol,
                    "eligible_entry_session": ep.eligible_entry_session.isoformat(),
                    "retry_deadline": retry_deadline.isoformat(),
                })
                continue
            self.store.record_disposition(
                episode_id=ep.episode_id, symbol=ep.symbol,
                disposition="FAILED_NO_MARKET_DATA", issuer_cik=ep.issuer_cik,
                eligible_entry_session=ep.eligible_entry_session.isoformat(),
                detail=f"no entry bar observed through the approved "
                       f"{self.cfg.max_entry_staleness_sessions}-session recovery window "
                       f"(deadline {retry_deadline.isoformat()}) -- intent released, not "
                       f"silently retried forever")
            # Final Remediation Directive 3: pre_intent is None in a
            # genuine legacy-mode (gate disabled) cold start -- guard
            # before subscripting it, never crash the tick.
            if pre_intent is not None:
                self.store.mark_entry_intent(
                    pre_intent["intent_id"], "FAILED_NO_MARKET_DATA",
                    detail="market data unavailable through the approved recovery window")
            self._enqueue_alert(kind="ENTRY_FAILED_NO_DATA", episode=ep, decision=None,
                                intent=pre_intent, extra={"released": True})
        self._no_prior_intent_skipped = no_prior

    def _phase_close(self, ripe_through: date, res, *, price_lookup) -> None:
        try:
            n_exits_before = len(res.exits)
            pipeline.settle_due_exits(store=self.store, as_of_session=ripe_through,
                                      price_lookup=price_lookup, config=self.cfg, result=res)
            for x in res.exits[n_exits_before:]:
                self._on_exit_recorded(x)
        except Exception:  # noqa: BLE001
            logger.exception("settle_due_exits_failed as_of=%s", ripe_through)

    def _phase_post_close(self, all_eps: list, all_ripe: list, today: date,
                          ripe_through: date, is_stale, *, live: bool = False) -> None:
        """Record staleness terminal dispositions/intent-expiry, THEN
        create NEW durable PENDING intents (reservations) for episodes
        eligible at a FUTURE session -- using THIS tick's own
        freshly-detected episodes. Runs strictly after PHASE OPEN/CLOSE
        above, so nothing created here could possibly have funded this
        same tick's own entries (Task 131 Directive 2/7)."""
        from talonx_v2.calendar import add_sessions

        stale = 0
        for e in all_ripe:
            if not is_stale(e):
                continue
            # A stale episode is NEVER entered -- skip it on every tick,
            # whether or not it has been seen before.  The disposition
            # WRITE is guarded so we don't keep rewriting SKIPPED_ENTRY_
            # STALE every tick -- but the intent-expiry check below is
            # NOT similarly guarded: a genuine bug was found here where an
            # episode already dispositioned for an UNRELATED reason
            # earlier (e.g. process_episode's own SKIPPED_NO_ENTRY_BAR,
            # written while its PENDING_RETRY was still active) made
            # episode_seen() True before it ever went stale -- silently
            # skipping the EXPIRED_STALE transition entirely and leaving
            # the intent PENDING forever. The intent-liveness check
            # (``entry_intent(...)["status"] == "PENDING"``) is itself
            # already idempotent and cheap, so it runs on every tick this
            # episode is stale, independent of the disposition-write guard.
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
        self._stale_skipped = stale

        # --- PRE-OPEN ENTRY INTENT PASS (Task 117 overnight) ---------------
        # An episode whose eligible entry session has NOT started, OR IS
        # TODAY, gets a durable PENDING intent + an ACTIONABLE alert now.
        # It carries no economic weight -- the fill still runs the
        # unchanged frozen pipeline at the eligible-entry-session OPEN
        # (PHASE OPEN, on a LATER tick -- THIS tick's own PHASE OPEN
        # already ran before this method, so an intent created here can
        # never be consumed before the NEXT tick) and is then LINKED to
        # this intent (delayed fill notification). Including "today" in
        # the window (not just strictly future sessions) lets a
        # composite/live pricing source whose liquidity read was only
        # PROVISIONAL at the moment of an earlier tick get a further,
        # still-causal chance once data stabilises -- without ever
        # letting a same-tick decision fund a same-tick entry.
        next_sess = next_session_strictly_after(ripe_through)
        intents_created = 0
        for e in all_eps:
            if not (today <= e.eligible_entry_session <= next_sess):
                continue                                   # started/past, or too far ahead
            if self.store.episode_disposition(e.episode_id) in ("ENTERED", "SKIPPED_ENTRY_STALE"):
                continue
            if self.store.entry_intent(e.episode_id) is not None:
                continue
            liq, dec = self._eval_causal_decision(e)
            if dec.action is V2Action.BUY:
                # Targeted Remediation Directive 2: the SAME temporal
                # deadline check used at consumption time (_phase_open)
                # is now also applied here, BEFORE a reservation or its
                # actionable alert is ever created -- called with
                # intent=None, so on a live tick it compares "right now"
                # (the instant a fresh intent would be created) against
                # the target session's own RTH open. A session whose
                # causal admission window has already closed never gets
                # a new BUY intent, no matter how the episode itself was
                # detected.
                boundary_ok, boundary_detail = self._verify_temporal_boundary(e, None, live=live)
                if not boundary_ok:
                    self.store.record_disposition(
                        episode_id=e.episode_id, symbol=e.symbol,
                        disposition="SKIPPED_ADMISSION_DEADLINE_PASSED", issuer_cik=e.issuer_cik,
                        eligible_entry_session=e.eligible_entry_session.isoformat(),
                        detail=boundary_detail)
                    self._admission_deadline_rejected += 1
                    logger.error("admission_deadline_passed episode_id=%s symbol=%s detail=%s",
                                e.episode_id, e.symbol, boundary_detail)
                    continue
                try:
                    planned_exit = add_sessions(e.eligible_entry_session,
                                                self.cfg.hold_trading_days).isoformat()
                except Exception:  # noqa: BLE001
                    planned_exit = ""
                # Targeted Remediation Directive 3: the capacity check,
                # the intent-creation reservation, and its notification
                # now commit -- or roll back -- as ONE atomic unit. A
                # crash/exception at ANY point in this sequence (a
                # capacity re-check racing a concurrent writer, a
                # notification write that fails) must never leave a
                # reservation with no alert, nor an alert for an
                # admission that was never actually reserved. A rejection
                # (capacity exceeded) is itself still a single, complete,
                # committed outcome -- `continue` inside `with` exits the
                # block normally (no exception), so that single
                # disposition write still commits on its own.
                with self.store.transaction() as c:
                    # Package 2 acceptance A1: a serious account block
                    # must stop NEW account exposure from being
                    # COMMITTED to, not merely stop the eventual fill --
                    # a PENDING intent is itself a reservation (an
                    # ACTIONABLE alert promising a future BUY, capacity/
                    # cash set aside for it) even though no cash is
                    # actually debited until the fill (Product Rule 4).
                    # Checked on the SAME connection/transaction as the
                    # write it gates (never an earlier, separate read),
                    # UNCONDITIONALLY -- unlike the capacity check below,
                    # this never depends on durable_store_gate_enabled.
                    # This does NOT touch: the fill-time recheck inside
                    # enter_position() (already correct and unconditional
                    # -- see paper.py), legitimate expiry/cancellation of
                    # an EXISTING PENDING intent (_phase_post_close's
                    # stale sweep above, untouched), or open-position
                    # exits (_phase_close/settle_due_exits, untouched).
                    from talonx_ops import account_blocks
                    from talonx_v2.store import V2_ACCOUNT_ID
                    block_reason = account_blocks.blocked_reason(c, V2_ACCOUNT_ID)
                    if block_reason is not None:
                        self.store.record_disposition(
                            episode_id=e.episode_id, symbol=e.symbol,
                            disposition="SKIPPED_ACCOUNT_BLOCKED", issuer_cik=e.issuer_cik,
                            eligible_entry_session=e.eligible_entry_session.isoformat(),
                            detail=f"no new reservation created -- account blocked: {block_reason}")
                        self._account_blocked_intent_rejected += 1
                        continue
                    # Task 131 Remediation Directive 4: a HARD admission
                    # gate at intent-creation time, not merely at
                    # consumption -- cash/capacity are reserved by a
                    # PENDING intent the instant it is written, so a
                    # reservation must never be created if there is not
                    # truly enough unreserved cash/slots to eventually
                    # honour it. Checked BEFORE the intent row is
                    # written -- never rejected after the fact -- and now
                    # read on the SAME connection/transaction as the
                    # write that follows it, so nothing can invalidate
                    # this read between the check and the write it gates.
                    reject_reason = (self._capacity_rejection_reason()
                                     if self.durable_store_gate_enabled else None)
                    if reject_reason is not None:
                        self.store.record_disposition(
                            episode_id=e.episode_id, symbol=e.symbol,
                            disposition="REJECTED_CAPACITY_EXCEEDED", issuer_cik=e.issuer_cik,
                            eligible_entry_session=e.eligible_entry_session.isoformat(),
                            detail=reject_reason)
                        self._capacity_rejected += 1
                        continue
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

    def _phase_mark(self, today: date) -> list[dict]:
        """Lightweight daily mark-to-market of every still-open position
        (Task 131 Directive 2/8): requested date, actual mark date/price,
        freshness, and unrealized P&L -- never presents an unavailable
        mark as a fresh valuation."""
        marks = []
        for p in self.store.open_positions():
            px = self._price(p["symbol"], today)
            mark_date, mark_price, stale = None, None, True
            if px and px.get("close"):
                mark_date, mark_price, stale = today.isoformat(), float(px["close"]), False
            else:
                # fall back to the frozen bar directory's own last available
                # close on/before today -- flagged STALE, never presented as fresh.
                for row in sorted(self._bars(p["symbol"]), key=lambda r: r["date"], reverse=True):
                    if row["date"] <= today.isoformat() and row.get("close"):
                        mark_date, mark_price, stale = row["date"], float(row["close"]), True
                        break
            entry_price = p["entry_price"]
            unrealized_pct = (100.0 * (mark_price - entry_price) / entry_price
                              if mark_price is not None else None)
            marks.append({
                "symbol": p["symbol"], "position_id": p["position_id"],
                "requested_date": today.isoformat(), "mark_date": mark_date,
                "mark_price": mark_price, "mark_available": mark_price is not None,
                "mark_stale": stale if mark_price is not None else None,
                "entry_price": entry_price, "shares": p["shares"], "cost_basis": p["position_cost"],
                "unrealized_pnl_pct": (round(unrealized_pct, 4) if unrealized_pct is not None else None),
                "unrealized_pnl_usd": (round(p["shares"] * (mark_price - entry_price), 2)
                                      if mark_price is not None else None),
            })
        return marks

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

    def _capacity_rejection_reason(self) -> str | None:
        """Task 131 Remediation Directive 4: the hard admission gate at
        intent-CREATION time. A PENDING intent reserves $10,000 (the
        configured per-position allocation) and one slot the instant it
        exists -- so this checks TRUE unreserved cash/capacity (current
        cash/open-position-count MINUS every currently-PENDING intent's
        own reservation), never just the raw store.cash()/n_open() a
        moment before consumption. Returns None when there IS room,
        otherwise an explicit, loggable reason."""
        pending = self.store.pending_entry_intents()
        reserved_cash = self.cfg.per_position_allocation_usd * len(pending)
        reserved_slots = len(pending)
        available_cash = self.store.cash() - reserved_cash
        available_slots = self.cfg.max_concurrent_positions - self.store.n_open() - reserved_slots
        if available_cash < self.cfg.per_position_allocation_usd:
            return (f"unreserved cash ${available_cash:,.2f} < required "
                   f"${self.cfg.per_position_allocation_usd:,.2f} "
                   f"(cash=${self.store.cash():,.2f}, {len(pending)} intent(s) already "
                   f"reserving ${reserved_cash:,.2f})")
        if available_slots <= 0:
            return (f"no unreserved capacity slots -- open={self.store.n_open()} + "
                   f"pending_intents={reserved_slots} >= max={self.cfg.max_concurrent_positions}")
        return None

    def _verify_temporal_boundary(self, ep, intent: dict | None = None, *,
                                  live: bool = False) -> tuple[bool, str]:
        """Task 131 Remediation Directive 3 / Final Remediation Directive 1
        / Targeted Remediation Directives 1-2: explicit, enforced check
        that BOTH (a) ``ep``'s own activating filing was disseminated,
        AND (b) the moment this admission decision is evaluated (an
        existing durable PENDING intent's own creation time, or "right
        now" if none exists yet) occurred strictly BEFORE the entry
        session's own RTH open -- never merely assumed from the frozen
        entry_offset_sessions=1 contract. The real wall-clock
        dissemination timestamp is looked up from
        ``self._dissemination_lookup`` (refreshed each tick directly from
        InsiderStore -- see ``_refresh_dissemination_lookup``); this
        method and its lookup table live entirely in this operational
        module and never touch the frozen cluster_engine.PurchaseRecord/
        ClusterEpisode shapes.

        An UNKNOWN dissemination timestamp is a STRICT FAILURE whenever
        EITHER this is a true LIVE tick (``live=True``, regardless of
        whether this tick's own InsiderStore query happened to find
        anything at all -- a live decision must never silently proceed
        on an unobserved timestamp) OR
        ``self._dissemination_lookup_refreshed_this_tick`` is True (a
        genuine query against the real InsiderStore ran THIS tick, even
        on a pinned replay, and still found nothing for this specific
        episode -- a real data-quality gap in a feed that IS expected to
        carry this timestamp must never be silently treated as "safely
        early"). It remains an explicit, documented, non-fabricating SKIP
        only on a NON-live tick whose fetch never happened at all (a
        date-only source -- research parquet / from_rows -- or a caller
        that overrides ``_records`` directly, bypassing the real
        InsiderStore query entirely, e.g. most of this test suite, which
        always pins ``as_of`` and is therefore never ``live``) -- using
        ``form4_kind == "insider"`` alone would incorrectly treat every
        such bypassed/mocked/replayed records path as a violation. The
        DATE-level causal_event_ts / eligible_entry_session ordering is
        itself still enforced structurally by cluster_engine regardless
        of whether this finer check can run.

        The intent-creation-time / admission-time check (b) is
        LIVE-TICK-ONLY: a pinned replay/dry-run/test tick's own ``as_of``
        bears no relationship to either the intent row's REAL wall-clock
        ``created_at_utc`` or to ``datetime.now()`` (always the actual,
        real present) -- comparing either against a SIMULATED historical
        RTH open would be comparing two unrelated clocks and would
        spuriously fail every replayed/backtested entry.

        Targeted Remediation Directive 1/2: on a true LIVE tick, an
        UNKNOWN dissemination timestamp is now ALWAYS a strict failure
        (never a silent pass), and check (b) is now called from TWO
        places with two different meanings of "the moment being
        evaluated":

          - called with a real ``intent`` (from ``_phase_open``, at
            CONSUMPTION time): the intent's own ``created_at_utc`` MUST
            be present, parsable, and strictly before the RTH open --
            missing or malformed timing data is now itself a strict
            failure, never silently treated as "assume it was early
            enough."
          - called with ``intent=None`` (from ``_phase_post_close``, at
            ADMISSION time, BEFORE any intent row exists): the real
            wall-clock ``datetime.now(timezone.utc)`` -- i.e. "if a
            PENDING intent were created right now" -- MUST itself be
            strictly before the RTH open, so a reservation (and its
            actionable alert) is never created for a session whose
            causal admission window has already closed."""
        ts = self._dissemination_lookup.get((ep.symbol.upper(), ep.activation_filing_date.isoformat()))
        if ts is None:
            if live or self._dissemination_lookup_refreshed_this_tick:
                return False, (
                    f"no real dissemination timestamp available for the activating filing "
                    f"(symbol={ep.symbol}, activation_filing_date="
                    f"{ep.activation_filing_date.isoformat()}) -- failing STRICT rather than "
                    f"assuming an unobserved timestamp was safely early"
                    + ("" if self._dissemination_lookup_refreshed_this_tick else
                       " (live tick, no successful InsiderStore query this tick either)"))
            return True, ""
        try:
            import exchange_calendars as _xc
            rth_open = _xc.get_calendar("XNYS").session_open(
                ep.eligible_entry_session.isoformat()).to_pydatetime().astimezone(timezone.utc)
        except Exception as exc:  # noqa: BLE001 -- cannot resolve the session open; fail SAFE (refuse)
            return False, f"could not resolve RTH open for {ep.eligible_entry_session.isoformat()}: {exc!r}"
        if ts >= rth_open:
            return False, (f"activation filing disseminated at {ts.isoformat()}, which is NOT "
                           f"strictly before the entry session's own RTH open "
                           f"({rth_open.isoformat()}) -- refusing to prevent look-ahead bias")
        # Targeted Remediation Directive 1/2: on a true LIVE tick, the
        # moment THIS admission decision is being evaluated -- the
        # existing intent's own creation time if one already exists,
        # otherwise "right now" (the instant a fresh intent would be
        # created) -- must ALSO be strictly before the entry session's
        # RTH open. Live-only: see the docstring above for why comparing
        # a replay's own simulated clock against either real wall-clock
        # value would be meaningless.
        if live:
            if intent is not None:
                created_ts = None
                created_raw = intent.get("created_at_utc")
                if created_raw:
                    try:
                        created_ts = datetime.fromisoformat(str(created_raw))
                        if created_ts.tzinfo is None:
                            created_ts = created_ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        created_ts = None
                if created_ts is None:
                    return False, (
                        f"the durable PENDING intent carries no valid, parsable "
                        f"created_at_utc timestamp (raw={created_raw!r}) -- refusing to "
                        f"assume it was created strictly before the entry session's own "
                        f"RTH open ({rth_open.isoformat()})")
                if created_ts >= rth_open:
                    return False, (
                        f"the durable PENDING intent itself was created at "
                        f"{created_ts.isoformat()}, which is NOT strictly before the entry "
                        f"session's own RTH open ({rth_open.isoformat()}) -- refusing to "
                        f"prevent look-ahead bias")
            else:
                now = datetime.now(timezone.utc)
                if now >= rth_open:
                    return False, (
                        f"admission is being evaluated at {now.isoformat()}, which is NOT "
                        f"strictly before the entry session's own RTH open "
                        f"({rth_open.isoformat()}) -- refusing to create a BUY intent for a "
                        f"session whose causal admission window has already closed")
        return True, ""

    def _enqueue_alert(self, *, kind: str, episode, decision, intent, extra: dict | None = None):
        import hashlib
        extra = extra or {}
        sym = episode.symbol.upper()
        action = {"ENTRY_INTENT": "BUY", "ENTRY_FILL": "BUY",
                  "EXIT_FILL": "SELL", "ENTRY_STALE": "INFO",
                  "ENTRY_FAILED_NO_DATA": "INFO"}[kind]
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
        elif kind == "ENTRY_FAILED_NO_DATA":
            headline = f"INSIDER BUY CLUSTER — market data unavailable — {sym}"
            body = (f"The planned {sym} paper entry for {episode.eligible_entry_session.isoformat()} "
                    f"could not be filled: no entry bar was ever observed through the end of "
                    f"that session's own RTH window, despite non-blocking retries on every "
                    f"intervening tick. The reservation was released; no position opened. "
                    "Informational only (Task 131 Remediation Directive 2).")
        else:  # ENTRY_STALE
            headline = f"INSIDER BUY CLUSTER — entry expired — {sym}"
            body = (f"The planned {sym} paper entry for {episode.eligible_entry_session.isoformat()} "
                    f"expired without a FINAL entry bar within "
                    f"{self.cfg.max_entry_staleness_sessions} sessions. No position opened. "
                    "Informational only.")
        payload = "\n".join([f"⚡ *{action}* — *{sym}*  INSIDER BUY CLUSTER",
                             "—" * 12, headline, "", body,
                             "", "[INSIDER_BUY_CLUSTER_V2@1 · PAPER_CANDIDATE · PAPER ONLY · dry-run/candidate]"])
        # actionable-instruction deadline: a PLANNED BUY is only deliverable
        # BEFORE its target session's XNYS open (Task 117 deployment-readiness).
        deliver_by = None
        if kind == "ENTRY_INTENT":
            try:
                import exchange_calendars as _xc
                _open = _xc.get_calendar("XNYS").session_open(
                    episode.eligible_entry_session.isoformat()).to_pydatetime()
                deliver_by = _open.astimezone(timezone.utc).isoformat()
            except Exception:  # noqa: BLE001 -- fall back to start-of-session-day UTC
                deliver_by = datetime.combine(episode.eligible_entry_session,
                                              datetime.min.time(), tzinfo=timezone.utc).isoformat()
        self.store.enqueue_alert(
            event_id=event_id, episode_id=episode.episode_id, kind=kind, action=action,
            symbol=sym, strategy_version="INSIDER_BUY_CLUSTER_V2@1", dedup_key=dedup_key,
            payload_text=payload, provenance=provenance,
            horizon_trading_days=self.cfg.hold_trading_days, deliver_by_utc=deliver_by,
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
                      *, source_degraded: str | None = None, marks: list[dict] | None = None) -> dict:
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
            "no_prior_intent_skipped_this_tick": getattr(self, "_no_prior_intent_skipped", 0),
            "capacity_rejected_this_tick": getattr(self, "_capacity_rejected", 0),
            "admission_deadline_rejected_this_tick": getattr(self, "_admission_deadline_rejected", 0),
            "account_blocked_intent_rejected_this_tick": getattr(self, "_account_blocked_intent_rejected", 0),
            "entries_this_tick": len(res.entries),
            "exits_this_tick": len(res.exits),
            # Task 131 Remediation Directive 2: non-blocking, cross-tick
            # missing-price retry observability -- never a blocking sleep.
            "pending_retry_episodes_this_tick": getattr(self, "_pending_retry_episodes", []),
            "pending_retry_count_this_tick": len(getattr(self, "_pending_retry_episodes", [])),
            # Task 131 Directive 2/8: lightweight per-position daily mark
            "open_position_marks": marks or [],
            # Task 140: expose the REAL, same-process admission-gate value
            # this running companion actually reads at __init__ (line
            # ~173) -- so /ping and the dashboard can read the authoritative
            # source instead of each independently re-deriving
            # TALONX_V2_DURABLE_STORE_ENABLED from THEIR OWN process's
            # environment (a genuine divergence risk: Original and the V2
            # companion are separately-spawned processes, and this exact
            # class of cross-process env-propagation gap has already
            # surfaced twice tonight for broad-discovery and delivery-
            # enablement -- see docs/research/evidence/task140/).
            "durable_store_gate_enabled": self.durable_store_gate_enabled,
            # execution scope enforcement (Task 117 final activation)
            "execution_scope_enforced": self.execution_allowlist is not None,
            "execution_scope_count": (len(self.execution_allowlist)
                                      if self.execution_allowlist is not None else None),
            "execution_scope_out_of_scope_dropped_this_tick": getattr(self, "_allowlist_dropped", 0),
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
