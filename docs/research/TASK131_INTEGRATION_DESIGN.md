# Task 131 — Option A integration design

Branch `feature/task131-option-a-integration`, from release baseline
`f28986999eec5e313cfc89db24e4dbacfb378891`. This is a real production-
integration task, explicitly authorized as a full override of Task 129's
research pause and Task 130B's own "NOT authorized: production
integration" boundary — confirmed directly by the user before any code
was touched. Real-money trading remains out of scope; every change below
is paper-only, additive, and off-by-default unless stated otherwise.

## 1. Experimental ledger cleanup (Directive 1)

`scripts/migrations/task131_close_stranded_spcx.py` — a one-time,
idempotent, backed-up migration against the shadow Experimental paper
ledger (`~/.talonx/experimental/experimental_paper.db`). The SPCX
position (opened 2026-09-10T19:29:45Z, never marked or closed while the
application was stopped) is closed **administratively, at its own entry
price** — zero fabricated P&L, since no live price feed is queried and no
market outcome for the stranded period was ever actually observed.
`win_count`/`loss_count`/`total_realized_pnl_usd` are left unchanged
(this is not a real trading result). The database's WAL is checkpointed
and a timestamped `.bak` copy taken before any write; a full before/after
audit record is written to `results/task131_migrations/`. Executed once,
verified idempotent (a second run reports `NOOP_NO_OPEN_SPCX_POSITION`).

## 2. Durable lifecycle — WAL, four-phase state machine, reservation-before-entry

**WAL**: `talonx_v2.store.V2Store._conn()` already requested
`PRAGMA journal_mode=WAL` on every connection (pre-existing). Hardened
with a one-time, loud verification in `V2Store._init()`: after the first
`PRAGMA journal_mode` request, the actual mode is read back and the
constructor raises if it is not `wal` (except for an explicit `:memory:`
exemption, which cannot use WAL at all) — closing a real, if unlikely,
silent-fallback risk on some filesystems.

**Four explicit session phases**, replacing the single `V2Service.tick()`
body: `_phase_open` → `_phase_close` → `_phase_post_close` → `_phase_mark`,
called in that fixed order every tick.

- **OPEN** resolves entries **only** for episodes carrying an existing,
  durable `PENDING` intent row in `pending_entry_intents` — never a
  cold-start entry. An episode reaching OPEN with no valid prior intent
  is recorded `SKIPPED_NO_PRIOR_INTENT` (written only once the
  intent-creation window has definitively closed — see below) instead of
  the previous permissive "cold-start backfill" behaviour.
- **CLOSE** settles due exits, always **after** OPEN in the same tick —
  so a same-tick exit's proceeds can never fund a same-tick entry (the
  entries already ran against pre-exit cash).
- **POST-CLOSE** records staleness terminal dispositions/intent-expiry,
  then creates new `PENDING` intents for episodes eligible **through**
  the current session (`today <= eligible_entry_session <= next_session`)
  using this tick's own freshly-detected episodes. Because POST-CLOSE
  runs strictly after OPEN/CLOSE in the same tick, nothing it creates can
  ever be consumed before the **next** tick — the causal ordering is
  structural, not merely documented.
- **MARK** computes a lightweight daily mark-to-market for every open
  position: requested date, actual mark date, staleness, unrealized P&L
  — surfaced in the tick status (`open_position_marks`), never presenting
  an unavailable mark as a fresh valuation.

**Why the intent-creation window includes "today", not just strictly
future sessions**: the live composite-pricing adapter (Task 117 Phase 0)
distinguishes PROVISIONAL from FINAL data — a liquidity read taken
strictly before the entry session can still be provisional at that exact
moment. Restricting intent creation to strictly-future sessions only
would have made a not-yet-stabilised data read a **permanent** miss (no
tick would ever be positioned to retry the decision). Extending the
window through the entry session itself preserves the OPEN-before-
POST-CLOSE causal guarantee (an intent created in POST-CLOSE can only be
consumed by the NEXT tick's OPEN, never this one) while giving genuinely
improving intraday data a real, still-causal second chance. This was
discovered, not assumed: two existing Task 117 tests
(`test_provider_error_does_not_consume_the_episode`,
`test_open_position_exits_during_sec_failure_under_composite_yf`)
originally relied on exactly this multi-tick retry behaviour and failed
under a strictly-future-only window; they were repaired using genuinely
good liquidity history plus an isolated, transient price-fetch failure
(matching Directive 3, not the old, unbounded "no gate at all" model).

**Scope of the change**: entirely contained in `talonx_v2/service.py` (the
module's own docstring: "operational runtime only... carries NO strategy
semantics of its own"). `talonx_v2/pipeline.py` and `talonx_v2/paper.py`
— shared with offline replay and research — are **untouched**; the
`V2_FROZEN_CONTRACT` values in `config.py` are unchanged.

## 3. Missing-price resiliency (Directive 3)

`talonx_v2/price_resilience.py` — a small, fully dependency-injected
(`sleep_fn`/`time_fn`) bounded-retry helper: polls the same underlying
price lookup for up to `price_retry_max_wait_seconds` (default 300s / 5
minutes), `price_retry_poll_interval_seconds` between attempts (default
15s), returning the first available price or `None`. `V2Service.
_resilient_price_lookup(live: bool)` wraps `self._price` with this retry
loop **only for a true live tick** (`as_of is None`) — a pinned replay/
dry-run/test tick never waits a real wall-clock second (its clock is
simulated, its price coverage is a fixed, known fact).

If, after the bounded retry, `process_episode` still could not find an
entry bar (`NO_ENTRY_BAR`), `_phase_open` (in a live tick only) upgrades
the disposition to `FAILED_NO_MARKET_DATA` and releases the intent via
`store.mark_entry_intent(..., "FAILED_NO_MARKET_DATA", ...)` — an
explicit terminal state, never a silent, indefinite retry, and never a
substituted/invented/later price. A pinned test/replay tick leaves the
existing, unchanged `SKIPPED_NO_ENTRY_BAR` non-terminal behavior (the
intent stays `PENDING`, retried naturally on a later tick) — this was a
real bug found and fixed during implementation (the first version
escalated to `FAILED_NO_MARKET_DATA` unconditionally, breaking two
existing pricing-readiness tests that rely on the old unbounded retry
in **non-live** ticks).

## 4. SEC ingestion & identity expansion (Directive 4)

**Rate budget**: `talonx_ingest.edgar.client.EdgarClient` already
enforces an async token-bucket limiter at
`talonx_ingest.config.settings.edgar.max_requests_per_second`, default
**8.0** (env `TALONX_SEC_RPS`) — this pre-existing default already
matches the directive's 8 req/s requirement exactly; no new limiter was
built.

**Genuinely shared budget, not doubled**: `talonx_ingest/intelligence/
service/broad_discovery.py` extends the SAME `IngestionScope` (same
process, same `EdgarClient` instance, same in-memory token bucket) rather
than running a second, independent poller process — two separate
processes would each instantiate their own token bucket, silently
doubling the effective rate against SEC. `extend_scope_with_broad_
discovery()` is additive and opt-in (`TALONX_INTEL_ENABLE_BROAD_
DISCOVERY`, default off): with the flag unset, the returned scope is the
**same object**, byte-identical to pre-Task-131 behaviour. When enabled,
the frozen 626-name Discovery Universe v1 manifest
(`results/task131_discovery_universe/discovery_universe_v1_626.json`,
copied from the research branch's own Task 130B-validated population,
`C_full_panel_A_union_B`) is resolved through the **same** `CikDirectory`
every other symbol uses, unioned into the existing scope, and each
symbol's origin (`PRODUCT_WATCHLIST` / `BROAD_DISCOVERY`) is tracked
separately for the dashboard (Directive 5) — without a second scope,
process, or rate limiter.

**Continuous ingestion surviving EOD without duplicate pollers**: already
provided by the existing, mature `talonx_ingest.intelligence.service.
singleton.SingletonLock` (a PID-lock file, reclaimed automatically if the
prior holder's process is dead, refused if it's alive) plus `runner.py`'s
persistent poll loop with backoff/recovery cadence. SEC filings are not
tied to market hours, so this loop already runs continuously across EOD
sessions by construction; no new supervision code was needed.

**CIK/accession-level identity validation, live**: `talonx_ingest/
intelligence/service/identity_guard.py` (`check_filing_issuer_identity`)
applies, prospectively, the principle Task 130B established by research
(a shared ticker symbol can legitimately map to more than one issuer CIK
over time): for every Form 3/4/5 ownership filing about to be persisted,
its **own** declared `issuerCik` (parsed directly from its XML) is
compared against the caller's already-resolved, authoritative CIK for
that ticker (in production, `poller.py` passes the same `ResolvedSymbol
.cik` the filing was fetched with). A mismatch **drops** the filing —
never persisted, never force-mapped — with an explicit, loggable reason.
Wired into `talonx_ingest/intelligence/service/_insider.py::
ingest_form_ownership` via a new `enforce_issuer_identity: bool = True`
parameter (genuinely on by default; an explicit, non-default opt-out
exists for callers that need it). This is a live, forward-looking safety
check, narrower than Task 130B's own after-the-fact accession-chain
research — it does not resolve every historical rename, only "does this
filing's own declared issuer match what we currently, authoritatively
believe this ticker is."

## 5. Routing & UI preservation (Directive 5)

**Telegram `BROAD_DISCOVERY` toggle**: `talonx_ops/official_dispatch.py`
— `OfficialExternalRouter.decide(family, dedup_key, *, origin=
"PRODUCT_WATCHLIST")` gains an `origin` parameter (default preserves
existing behaviour exactly, since no existing caller ever passes it). A
`BROAD_DISCOVERY`-origin alert requires its **own**, independent env
toggle (`TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY`, default off) — a
defense-in-depth gate at the external-send boundary, separate from the
ingestion-side toggle (Directive 4) and separate from `V2Service`'s own
`execution_allowlist`. `talonx_v2/delivery.py::deliver_outbox` gains an
optional `broad_discovery_symbols: frozenset[str]` parameter (default
empty) to tag each outbox row's origin by symbol before calling
`router.decide`; `V2Service` carries this set (populated, opt-in, by
`talonx_v2/run.py --enable-broad-discovery`, which additively unions the
626-name manifest into the execution scope and tags the newly-added
symbols).

**Dashboard UI preservation**: `talonx_ops/dashboard_read.py::
v2_active_strategy()` — the existing 39-name/campaign-ledger panel — is
**completely unmodified**. A new, separate method,
`v2_broad_discovery()`, reads the **same** `v2_lane.db` read-only and
reports broad-discovery-specific metrics (open/closed counts, realized
P&L, both toggle states) for symbols in the 626-name universe that are
**not already** in the resolved 39-name watchlist — arithmetic that
never double-counts a symbol already shown in the primary panel. Wired
additively into `all_sections()` (new key `v2_broad_discovery`) and into
`dashboard_web.py`'s `_UNIFIED_SECTIONS`/`/api/sections`/
`/api/section/{name}` routes, so it is reachable exactly like every
other `:8787` cockpit section, without altering any existing route or
response shape beyond the one new top-level key (four existing
exact-key-set test assertions were updated to include it, matching the
established test-maintenance pattern used throughout this program when
a behavior change is intentional).

## 6. What is explicitly NOT started

Per the confirmed authorization boundary and this program's standing
practice of not silently starting unattended, externally-facing
processes: no continuous overnight SEC poller was actually **launched**
against the real network in this task, and no real Telegram message was
sent. Every toggle introduced here (`TALONX_INTEL_ENABLE_BROAD_
DISCOVERY`, `TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY`,
`--enable-broad-discovery`) defaults OFF; flipping any of them on and
actually starting the live processes is a distinct, separate operational
step for the user to take explicitly, not implied by this integration
work being complete and tested.
