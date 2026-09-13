# Task 131 Remediation — design

Branch `feature/task131-option-a-integration`, remediating a HOLD verdict
against commit `58044a6` (6 launch-blocking defects). This document
covers the architecture of the non-blocking retry model, atomic SQLite
transactions, and the temporal dissemination boundary — the three
directives with real design substance; the other three (routing fix,
admin-adjustment isolation, feature flags) are narrower and covered in
the retrospective's traceability matrix.

## A hard constraint discovered mid-remediation: the frozen strategy fingerprint

Before any design content: `talonx_v2/{config,cluster_engine,liquidity,
quant_bridge,brain_bridge}.py` are hash-fingerprinted as a group
(`research/scripts/task112_v2_release_fingerprint.py`, asserted by
`test_task114_prospective.py`, `test_task117_deployment_rehearsal.py`,
`test_task117_overnight_e2e.py`). Directive 3 (temporal dissemination
boundary) originally attempted to add an optional `accepted_at_utc`
field to `cluster_engine.PurchaseRecord`/`ClusterEpisode` — purely
additive, no behavior change — and this still moved the fingerprint,
because the fingerprint hashes raw file BYTES, not semantics. Reverted
in full; the real capability (storing and enforcing the real wall-clock
dissemination timestamp) is instead implemented entirely in
`talonx_v2/service.py` (the operational layer, never fingerprinted) —
see Directive 3 below.

**A second, self-inflicted issue surfaced during that revert**: `git
checkout -- talonx_v2/cluster_engine.py` re-materialized the file with
this machine's `core.autocrlf=true` Git setting, silently converting its
LF line endings to CRLF — which ALSO changes the fingerprint (byte-level
hash), even though `git diff` reports no differences (Git's own diff
normalizes line endings for display; the fingerprint script does not).
Fixed by writing the exact `git show HEAD:<path>` blob bytes back to
disk directly (bypassing `git checkout`'s autocrlf conversion). Recorded
here because it is a real, reproducible trap on any Windows checkout of
this repo with `autocrlf=true`: **never use `git checkout -- <path>` to
revert one of the five fingerprinted files** — restore via `git show
HEAD:<path> > <path>` instead, which writes the blob's exact bytes with
no line-ending translation.

## Directive 2 — non-blocking retry, PENDING_RETRY

The original Task 131 integration's `_resilient_price_lookup` blocked
inside a single `tick()` call for up to 5 minutes (`time.sleep`-based
bounded retry) whenever an entry price was momentarily missing on a live
tick — stalling the ENTIRE service (heartbeat, other symbols' exit
processing, everything) for that whole window.

**Removed entirely.** `_resilient_price_lookup` now makes exactly one,
immediate attempt per tick (`return self._price`) — no loop, no sleep,
regardless of live/replay. `talonx_v2/price_resilience.py` (the
blocking-retry helper) is deleted.

**Replaced with a cross-tick, non-blocking model.** A missing entry bar
no longer escalates immediately. `_phase_open` leaves the intent's store
row untouched (still `'PENDING'`) and records the episode in
`self._pending_retry_episodes` for this tick's own observability
(`pending_retry_episodes_this_tick` / `pending_retry_count_this_tick` in
the tick status). Because the intent stays `PENDING`, the SAME episode
is naturally re-attempted on the service's own next tick — a real retry,
but one that costs nothing beyond that tick's own single price lookup;
"yielding control back to the event loop" (the literal remediation
wording) is expressed, for this synchronous, non-asyncio codebase
(`V2Service`/`run()` has never used asyncio, and introducing it here
would be a disproportionate, unscoped rewrite unrelated to the actual
defect), as **never blocking a single `tick()` call at all** — the
service's own existing inter-tick wait (`run()`'s `time.sleep(0.5)`
heartbeat loop, unchanged) is what already yields control between ticks.

**Retained through the full RTH session window.** The intent is only
escalated to a terminal `FAILED_NO_MARKET_DATA` (reservation released
exactly once, alert enqueued) once a LATER tick observes that its own
`eligible_entry_session`'s calendar day has fully passed
(`ripe_through > ep.eligible_entry_session`) with no price ever found —
never mid-session. This uses the existing session-date granularity
`talonx_v2` already models timing at (no synthetic intraday RTH-open/
close clock was introduced, matching the existing architecture).

Proven under real failure conditions in `tests/test_task131_nonblocking_
retry.py`: a missing-price tick completes in well under 2 seconds (wall-
clock timed, would fail loudly if a blocking sleep reappeared); the
intent survives 5 repeated same-session ticks unmarked; a late-arriving
bar reconciles with exactly one fill; a price still missing the next
session releases the intent exactly once and a further tick does not
re-touch it.

## Directive 3 — temporal filing dissemination boundary

**Design constraint**: cannot touch `cluster_engine.py` (see above).
Implemented instead as a self-contained, operational-layer feature:

- `V2Service._refresh_dissemination_lookup` — called once per tick
  (immediately after `form4_source.from_insider_store`, only for
  `form4_kind="insider"`), queries `InsiderStore.query_transactions`
  directly (the SAME store `_records()` already opened that tick — no
  new network call, no new store) for every open-market (code P)
  transaction in the current causal window, and builds
  `self._dissemination_lookup: dict[(symbol, filing_date_iso),
  latest_accepted_at_utc]`. Using the LATEST timestamp per (symbol, day)
  is a deliberately conservative choice — it never UNDER-estimates how
  late information became available.
- `V2Service._verify_temporal_boundary(ep)` — looks up
  `(ep.symbol, ep.activation_filing_date)` in that table, resolves the
  entry session's own real RTH open via `exchange_calendars` (the same
  library already used elsewhere in this file for `deliver_by`
  computation), and asserts the dissemination timestamp is strictly
  before it. A violation (or an inability to resolve the session open at
  all) refuses the entry: `SKIPPED_TEMPORAL_BOUNDARY_VIOLATION`
  disposition, `REJECTED_TEMPORAL_BOUNDARY_VIOLATION` intent status,
  logged at ERROR level.
- Called from `_phase_open`, before `process_episode` is ever invoked.
- A date-only source (`form4_kind="parquet"`) has no real wall-clock
  timestamp available — the lookup is explicitly emptied for that path,
  and the check is a documented no-op (never fabricates a timestamp to
  make the check "pass").

**Why this should structurally never fire under the frozen contract**:
`entry_offset_sessions=1` (frozen, unchanged) means an entry always
happens at the OPEN of the session strictly after the activating
filing's own day — that session's own RTH open is, by construction,
always later than "activation day's own 23:59:59 UTC," which is itself
always later than or equal to any same-day dissemination timestamp. The
check is a genuine, enforced invariant (not merely asserted in a
docstring) that would catch an actual anomaly — a backfilled or
mis-timestamped filing, a future bug in session-offset logic — rather
than assuming the invariant always holds. Tested directly in
`tests/test_task131_temporal_boundary.py`, including the defensive
"anomalously late timestamp" case and a direct unit-level sweep of the
comparison across the exact boundary.

## Directive 4 — atomic transactions and hard reservation gate

**Atomicity.** `talonx_v2.paper.enter_position`/`close_position` each
called 4 separate `V2Store` methods (`insert_open_position`,
`set_cash`, `append_trade`, `record_disposition` / `close_position`,
`set_cash`, `append_trade`, `set_cooldown`) — each opening and
committing its OWN SQLite transaction. A crash between any two left a
position without its cash debit, a debit without a trade record, or a
closed position without its cash credit.

`V2Store` gained a reentrant transaction primitive: `self._active_conn`
(default `None`) is checked by the existing `_conn()` helper — when
set, every nested `_conn()` call reuses the SAME connection instead of
opening a new one, so a sequence of otherwise-independent method calls
commits together as one unit. `V2Store.transaction()` is the public
context manager that sets it, WAL mode active throughout (already the
default per-connection setting, now shared across the whole block); an
exception inside the block closes the connection WITHOUT calling
`commit()`, so nothing partial survives. `paper.enter_position`/
`close_position` now wrap their own multi-write sequences in `with
store.transaction():`. Every pre-existing caller that never uses
`transaction()` is completely unaffected — `_conn()`'s default behavior
(open/commit/close per call) is unchanged.

Proven under real failure conditions in `tests/test_task131_atomic_
transactions.py`, using a real temporary SQLite file and a monkeypatched
mid-sequence exception (`store.append_trade`/`store.set_cooldown`
raising): a fresh `V2Store` reopened against the same file shows NOTHING
partial — no position, cash untouched, no trade row, no disposition (or,
for the exit case: the position stays OPEN, cash unchanged, no SELL
row, no cooldown).

**Hard reservation gate.** `upsert_entry_intent` previously had no
cash/capacity check at all — an unbounded number of `PENDING` intents
could accumulate, each implicitly claiming $10,000 + 1 slot that might
not actually be available once consumption was attempted.
`V2Service._capacity_rejection_reason()` computes TRUE unreserved
cash/capacity (current cash/open-position-count MINUS every currently-
`PENDING` intent's own reservation) and is checked BEFORE
`upsert_entry_intent` is ever called, in `_phase_post_close`. A
rejection writes `REJECTED_CAPACITY_EXCEEDED` and creates no intent row
at all. Proven directly (`test_intent_creation_rejected_when_cash_
would_be_over_reserved`, `test_intent_creation_rejected_at_the_21st_
competing_slot`) and gated behind Directive 6's feature flag (below) —
the check is a genuine behavior change (the pre-Task-131 policy never
gated at creation time), so it participates in the same explicit
opt-in as the rest of the durable-lifecycle admission policy.

## Directive 6 — feature flag and static CIK manifest

`TALONX_V2_DURABLE_STORE_ENABLED` (default `False`) gates ONLY the
Task 131 admission-POLICY changes: the requirement that an entry have a
pre-existing durable `PENDING` intent (Directive 2's `SKIPPED_NO_PRIOR_
INTENT` gate) and the hard capacity-reservation check at intent
creation (Directive 4's `REJECTED_CAPACITY_EXCEEDED` gate). It does
**not** gate WAL/SQLite durability itself — `V2Store` has used WAL since
Task 110, predating this entire integration; disabling that by default
would be a real regression (reverting a live paper-trading system to
non-durable state), not a cautious rollback. OFF reproduces the exact
pre-Task-131 permissive entry policy (cold-start entries allowed,
capacity checked only at consumption); ON enables the corrected,
gated policy this integration was built to deliver. The test suite's
own default (`tests/conftest.py`) is ON — the corrected policy is what
nearly every V2Service test in this repo exercises and asserts — while
`V2Service`'s own runtime default (no env override) stays OFF, matching
the literal remediation requirement for a real deployment.

The 626-name Discovery Universe v1 population's CIK resolution is now a
**static, versioned manifest** (`CIK_MANIFEST_V1`, embedded in
`discovery_universe_v1_626.json`'s own `cik_manifest` key) rather than a
live `CikDirectory` lookup — resolved ONCE from a snapshot of SEC
`company_tickers.json` (569 of 626 resolved; 57 unresolved — legitimately
delisted/acquired/renamed names from this historical, point-in-time
research population that a LIVE lookup against CURRENT SEC data would
silently drop entirely, which would be the actually-wrong choice for
this specific frozen population, not merely the cautious one). This is
scoped narrowly: the primary product watchlist (~39-48 names) and the
Directive 4 identity guard's own filing-vs-caller-CIK check both
continue to use the existing, dynamic `CikDirectory` unchanged — turning
THAT general-purpose, live-refreshed mechanism static would be a real
correctness regression for ordinary operation (new tickers, renames)
and was not attempted.

## Final Remediation pass (on top of `53c3e4a`)

A third pass, closing four remaining production boundaries identified
after the remediation above. All four stayed inside `talonx_v2/service.py`,
`talonx_v2/store.py`, and test configuration — no SPA/frontend or
Supervisor lifecycle change was in scope, and none was made. The frozen
strategy fingerprint (`11107198c5b81237`) was re-verified unchanged after
every edit in this pass, same discipline as the two prior passes.

### Directive 1 — strict intent-creation-time deadline

The prior pass's `_verify_temporal_boundary` checked only the filing's
own dissemination timestamp against the entry session's RTH open. It did
not also check WHEN the durable `PENDING` intent itself was created —
so a real, look-ahead-safe dissemination timestamp paired with a bug
that somehow created the intent AFTER that session's RTH open (e.g. a
late-arriving backfill tick) would have passed silently.

Two changes:

- **Unknown dissemination timestamp is now a strict failure**, not a
  pass, but only when this tick's own `_refresh_dissemination_lookup`
  actually completed a real `InsiderStore` query (tracked via the new
  `self._dissemination_lookup_refreshed_this_tick` flag, reset every
  tick). Using `form4_kind == "insider"` alone (the prior pass's
  condition) was the wrong signal — several existing tests set
  `form4_kind="insider"` but inject data directly via `svc._records`,
  bypassing the real InsiderStore fetch the flag is meant to gate on;
  gating on "a real query ran and still came back with nothing" is the
  condition the directive actually describes, and is the one that does
  not spuriously break tests that never touch InsiderStore at all.
- **The durable intent's own `created_at_utc` is now compared against
  the entry session's RTH open**, refusing the entry
  (`REJECTED_TEMPORAL_BOUNDARY_VIOLATION`) if the intent was created at
  or after it. This check is gated on `live` (`as_of is None` in
  `tick()`, threaded through `_phase_open`/`_verify_temporal_boundary`)
  — a pinned historical replay's simulated `as_of` clock has no fixed
  relationship to `created_at_utc`'s real wall-clock value, so the
  comparison is only meaningful, and only ever applied, on a genuine
  live tick.

### Directive 2 — true atomic lifecycle across `process_episode` + intent update

The prior pass's atomic-transaction primitive (`V2Store.transaction()`)
covered `paper.enter_position`/`close_position` internally, but the
OUTER call sequence in `_phase_open` — `pipeline.process_episode`
(which calls `enter_position`) followed by a separate
`mark_entry_intent(..., "FILLED")` call — still committed as two
independent transactions. A crash between them left a real, cash-debited
open position whose intent row was permanently stuck `PENDING`.

`V2Store.transaction()` was made **reentrant**: a nested
`with store.transaction():` now joins the same outer connection/depth
counter instead of raising, and only the outermost block commits or
rolls back. `_phase_open`'s entry-attempt block now wraps
`pipeline.process_episode(...)` and the subsequent
`mark_entry_intent(FILLED)` call in one outer `with self.store.
transaction():` — so a capacity check, reservation, ledger entry, and
the `PENDING`→`FILLED` transition commit, or roll back, as a single
unit. Proven in `tests/test_task131_atomic_transactions.py`'s two new
reentrancy tests (nested blocks join the outer one; a nested exception
rolls back everything written by the outer block too).

### Directive 3 — retry deadline and the legacy-mode crash

**Legacy-mode crash**: with `TALONX_V2_DURABLE_STORE_ENABLED` at its
default (`False`), `pre_intent` can legitimately be `None` (a genuine
cold start, no intent ever created) — two sites in `_phase_open`
(the temporal-boundary-violation path and the `FAILED_NO_MARKET_DATA`
path) unconditionally indexed `pre_intent["intent_id"]`, raising
`TypeError` whenever this legacy path was actually exercised. Both are
now guarded with `if pre_intent is not None:` before the
`mark_entry_intent` call.

**Retry deadline**: the prior pass's non-blocking retry model escalated
to `FAILED_NO_MARKET_DATA` on the very first tick of the NEXT session
after the eligible entry session — effectively a one-session grace
window, not the approved multi-session recovery window
(`max_entry_staleness_sessions`, frozen at 3). Restored the deadline to
`add_sessions(ep.eligible_entry_session, max_entry_staleness_sessions - 1)`
— i.e. the approved window, offset by exactly one session short of the
raw staleness threshold. The `-1` offset is deliberate, not a
simplification: the pre-existing staleness guard in `_phase_post_close`
excludes a stale episode from `ripe_attemptable` at the SAME threshold
(`max_entry_staleness_sessions`), one phase earlier in the very same
tick. Using the identical threshold for both would make the
`FAILED_NO_MARKET_DATA` escalation mathematically unreachable — staleness
would always exclude the episode from `_phase_open` one step before this
logic could ever run at the boundary tick. Diagnosed via direct SQL
tracing of `processed_episodes`/entry-intent status across a tick-by-tick
replay before the off-by-one was found.

A genuine pre-existing bug surfaced during that same debugging, not
named in the directive but squarely inside "backend ledger integrity":
the staleness guard's `EXPIRED_STALE` intent-status transition was
nested inside the SAME `if not self.store.episode_seen(...)` guard as
the `SKIPPED_ENTRY_STALE` disposition write. If `pipeline.
process_episode`'s own frozen logic had already written a different
disposition for that episode earlier (`SKIPPED_NO_ENTRY_BAR`),
`episode_seen()` was already `True`, and the ENTIRE staleness block —
including intent expiry — was silently skipped forever, leaving the
intent `PENDING` indefinitely with no disposition ever attached to it.
Fixed by decoupling: the disposition write stays guarded by
`episode_seen()` (a disposition should still only be written once), but
the intent-liveness check and `EXPIRED_STALE` transition now run
unconditionally on every tick the episode is stale, regardless of any
earlier, unrelated disposition.

### Directive 4 — no global durable-store-flag override in tests

`tests/conftest.py`'s `os.environ.setdefault("TALONX_V2_DURABLE_STORE_
ENABLED", "true")` (added by the prior remediation pass to make the
corrected policy the suite's default) is removed. `V2Service`'s own
runtime default (`False`, no env override) is now also the test suite's
default, with no global override anywhere. Exactly 2 of the ~198 tests
in the V2-focused battery actually depended on the gate being ON
(`test_task117_overnight_journey.py::test_p1_same_session_first_tick_
defers_never_enters_cold` and `::test_p1_late_first_tick_is_a_permanent_
miss_not_a_stale_backfill`, both specifically testing the gated
cold-start policy) — each now sets
`monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")` locally,
so the mode a given test exercises is visible in that test file itself,
not hidden in a repo-wide default.
`tests/test_task131_remediation_directive6.py` already carried dedicated,
explicit-`monkeypatch` coverage of both the OFF (default) and ON states
from the prior pass and needed no change here.

## Targeted Remediation pass (on top of `9a81e5c`)

A fourth pass, closing 3 further production boundaries -- again entirely
within `talonx_v2/service.py` (no SPA frontend or Supervisor lifecycle
change). All 3 directives converge on the same function,
`_verify_temporal_boundary`, now called from TWO places with two
different meanings of "the moment this admission decision is being
evaluated."

### Directive 1 — strict intent deadline validation

Two real gaps in the prior pass's version of `_verify_temporal_boundary`:

- **Unknown dissemination timestamp on a live tick.** The strict-failure
  condition was `self._dissemination_lookup_refreshed_this_tick` --
  True only when a real InsiderStore query ran THIS tick and still found
  nothing. That was the right condition for a NON-live (replay/test)
  tick (see the Final Remediation section above for why: most of this
  test suite bypasses `_records` entirely, so the flag correctly stays
  False and the check correctly no-ops). But on a genuine LIVE tick, an
  unknown timestamp was ALSO silently passing whenever the flag happened
  to be False for any other reason -- e.g. `_refresh_dissemination_
  lookup`'s own query raising an exception, or a live run misconfigured
  with `form4_kind="parquet"`. Fixed: the strict-failure condition is now
  `live or self._dissemination_lookup_refreshed_this_tick` -- a live
  decision never silently proceeds on an unobserved timestamp, for any
  reason, while the non-live/replay skip is preserved exactly as before.
- **Missing/malformed intent `created_at_utc` on a live tick.** The prior
  pass's intent-creation-time check (`if live and intent is not None:`)
  only ever produced a FAILURE when `created_at_utc` was present AND
  parsed AND `>= rth_open`. If it was missing (`created_raw` falsy) or
  malformed (`ValueError`), the code silently fell through to `return
  True, ""` at the end of the function -- the exact opposite of "strict
  failure for unknown timing" the durable-intent contract requires.
  Fixed: `created_ts is None` (missing OR malformed) is now itself an
  explicit `return False, ...` — never silently treated as "assume it
  was early enough."

### Directive 2 — pre-admission deadline check

`_verify_temporal_boundary` previously only ran at CONSUMPTION time
(`_phase_open`, called with the episode's own pre-existing intent). It
never ran at ADMISSION time (`_phase_post_close`, BEFORE the intent is
created) — so on a live tick running late in the day, an episode whose
`eligible_entry_session` is TODAY but whose RTH open has already passed
could still receive a brand-new `PENDING` intent and an "ACTIONABLE"
alert, even though that intent is structurally guaranteed to fail
Directive 1's own consumption-time check on the very next tick (its
`created_at_utc` would necessarily be `>= rth_open`). A real user-facing
defect: an operator would be alerted to "act now" on an instruction that
was already, provably, too late to honour causally.

Rather than duplicate the temporal-boundary logic, `_verify_temporal_
boundary` is now called from `_phase_post_close` too, with `intent=None`
— the function's existing `intent is not None` branch (consumption-time:
compare the intent's own `created_at_utc`) and a new `else` branch
(admission-time: compare `datetime.now(timezone.utc)`, i.e. "the instant
a fresh intent would be created right now") share one coherent
definition: *the moment this admission decision is evaluated must be
strictly before the entry session's own RTH open*, whether that moment
is a past intent's recorded creation time or the present instant. A
violation writes `SKIPPED_ADMISSION_DEADLINE_PASSED` and creates no
intent, no alert, at all. Like every other wall-clock comparison in this
function, gated strictly on `live` — a replay/backtest tick must still be
able to admit any historical `eligible_entry_session` (the entire point
of replay), so the deadline check never applies when `live=False`.

`_phase_post_close` gained a `live: bool = False` parameter, threaded
from `tick()`'s own `live = as_of is None`, matching the existing pattern
already used for `_phase_open`.

### Directive 3 — atomic admission lifecycle under contention

`_phase_post_close`'s admission sequence — `_capacity_rejection_reason()`
(read), `upsert_entry_intent()` (write), `_enqueue_alert()` → `store.
enqueue_alert()` (write) — previously ran as three independent,
separately-committed operations. A crash between the second and third
(a real possibility: `enqueue_alert` builds a fairly involved provenance
payload and resolves `deliver_by` via `exchange_calendars`, either of
which can raise) would leave a real, cash/slot-reserving `PENDING` intent
with NO alert ever recorded — a reservation nobody was ever told about.

The whole decision — capacity check through to notification, both the
success path (intent + alert) and the rejection path (a single
`REJECTED_CAPACITY_EXCEEDED` disposition write) — is now wrapped in one
`with self.store.transaction():` block, reusing the reentrant primitive
built for the Final Remediation pass. `continue` inside the `with` block
exits it normally (no exception), so the single-write rejection path
still commits correctly; an exception anywhere in the success path rolls
back the ENTIRE sequence, leaving nothing partial.

Proven in `tests/test_task131_targeted_remediation.py` with a real
temporary SQLite file and two failure-injection tests: one that crashes
inside `store.enqueue_alert` (after the intent write would have
succeeded) — which, before raising, ALSO opens a genuinely separate
`V2Store` connection to prove real SQLite-level isolation: the reserving
intent is invisible to that contending reader while the outer transaction
is still open, not just "eventually rolled back" — and one that crashes
inside `store.upsert_entry_intent` itself. Both leave a fresh connection
against the same file showing nothing: no intent row, no alert, no
disposition.

## Concurrent Admission Fix + SPA Dashboard Acceptance (on top of `26118e4`)

A fifth pass, on the same branch: (1) closes a real database-boundary
concurrency gap the Targeted Remediation pass's atomicity work never
actually exercised (single-connection, single-process testing only), and
(2) implements a new, additive SPA dashboard tab surfacing the 626-name
Discovery Universe v1 engine — explicitly authorized for this pass,
superseding the earlier SPA exclusion. Supervisor/overnight-ingestion
lifecycle stays out of scope.

### 1 — the concurrent-admission fix

**Root cause, verified against the actual code before any change**:
`V2Store.transaction()` opened a connection and set PRAGMAs but never
issued an explicit `BEGIN`. Python's `sqlite3` module (default
`isolation_level`) only ever issues an IMPLICIT `BEGIN` right before the
first INSERT/UPDATE/DELETE — a bare `SELECT` (e.g.
`_capacity_rejection_reason()`'s cash/slot reads) acquires no lock at
all. Two genuinely concurrent connections could therefore both run their
own admission reads, both observe the SAME pre-reservation capacity, and
both proceed to write — a classic time-of-check-to-time-of-use race the
prior pass's tests never actually exercised (they used one connection,
a simulated crash, and a plain reader — see the SCOPE NOTE added to that
test in this pass).

**Fix**: the OUTERMOST `transaction()` call now opens its connection with
`isolation_level=None` (autocommit) and issues an explicit
`BEGIN IMMEDIATE` the instant it opens, before its own first read. A
second connection's own `BEGIN IMMEDIATE` now genuinely BLOCKS (bounded
by `busy_timeout`, still 30s in production) until the first connection's
transaction commits or rolls back — so by the time the second
connection's own admission reads run, the first writer's reservation is
already fully committed and visible. Nested `transaction()` calls
(already inside an active outer connection) are unaffected — they join
the existing lock, never re-acquiring it. On a lock-timeout failure, the
connection is closed and the exception propagates BEFORE
`self._active_conn` is ever set, so no partial reservation/alert/mutation
survives even that failure mode.

`V2Store.__init__` gained an optional `busy_timeout_ms: int = 30_000`
parameter (threaded into both `_conn()` and `transaction()`'s PRAGMA
calls) so a test can exercise the bounded-wait-then-fail path in well
under 30 real seconds; every production caller keeps the 30s default
unchanged.

**Other transaction callers inspected for compatibility**: `paper.
enter_position`'s own capacity/cooldown/cash reads (`position_for_
symbol`, `cooldown_until`, `n_open`, `cash`) previously ran via separate,
unprotected `_conn()` calls BEFORE its own `with store.transaction():`
block. When called from `V2Service._phase_open` (the real production/
replay path), this was already accidentally protected — `_phase_open`
wraps `pipeline.process_episode` in its OWN outer `transaction()`, so
`_conn()`'s reentrant check meant these reads already reused the active
connection. But `enter_position` called standalone (a test, or any
future caller) had no such protection. Fixed by moving ALL of
`enter_position`'s admission reads inside its own `with store.
transaction():` block, so it is now self-sufficiently safe regardless of
calling context — nesting is transparent either way. `paper.
close_position` was inspected and found to have no analogous read-then-
decide sequence worth protecting (its only pre-transaction reads come
from the already-fetched `position` dict, not a fresh store read).

**Proof**: `tests/test_task131_concurrent_admission.py` — every test uses
TWO independent `V2Service`/`V2Store` instances (two real `sqlite3`
connections) against ONE shared on-disk database file, coordinated with
`threading.Event` (never an arbitrary sleep as the correctness
mechanism; a short, bounded `Thread.join()` liveness check confirms a
writer is genuinely blocked before the test proceeds). Since
`max_concurrent_positions` is part of the FROZEN strategy contract
(`validate_frozen()` asserts it `== 20`), "one remaining slot" is
achieved by pre-seeding 19 real PENDING intents via the store directly,
never by relaxing the frozen parameter. Covers: one-slot exactly-one-
admitted, cash-limited admission with plenty of slots, a competing
writer succeeding after the first writer's simulated crash rolls back
(the freed slot is genuinely re-evaluated, not assumed free), and a
bounded lock-timeout that leaves nothing partial. The prior pass's own
reader-isolation/rollback test (`test_task131_targeted_remediation.py`)
is retained, with its docstring corrected to state plainly what it does
and does not prove (visibility + rollback on ONE simulated writer, not
competing-writer capacity enforcement) — the genuine competing-writer
proof lives in the new file.

### 2 — the SPA Discovery Dashboard

**Investigated first**: `dashboard_web.py` already registered
`v2_broad_discovery` as a section (Task 131 Directive 5) and
`talonx_ops.dashboard_read.DashboardReadModel.v2_broad_discovery()`
already existed — but `dashboard_web_static/index.html` had NO nav
button or renderer for it; the panel was reachable only via the raw
`/api/section/v2_broad_discovery` JSON endpoint, never actually visible
in the rendered SPA. The existing 39-name "Active V2" tab/renderer
(`renderV2`) was left completely untouched.

**Backend extension** (`v2_broad_discovery()`, additive, read-only,
backward-compatible — every existing key unchanged): `universe_coverage`
reads `n_resolved`/`n_unresolved`/`manifest_version` LIVE from the
manifest file's own `cik_manifest` key every call (never a hardcoded
626/569/57 literal), labelled explicitly as a static, versioned research
snapshot — NOT live identity verification. `admission_policy` reads the
real, current `TALONX_V2_DURABLE_STORE_ENABLED` state. `source_health` /
`dashboard_refresh_utc` / `upstream_data_as_of_utc` are reused directly
from `v2_active_strategy()`'s own readiness computation (the SAME
source/process serves both views — deliberately not a second,
independently-observed feed) with the dashboard's own read time kept
explicitly distinct from the upstream source's last successful
observation. `discovery_funnel` classifies real episode dispositions +
intent statuses for broad-discovery-only symbols into DISCOVERED /
PENDING / REJECTED / EXPIRED / FILLED (`_classify_discovery_candidate`,
with an honest UNCLASSIFIED fallback for any future disposition string
this mapping doesn't yet recognize) — built from the UNION of
`processed_episodes` and `pending_entry_intents` rows, not episodes
alone, since a genuinely PENDING intent has no disposition row yet in
the real system (a bug caught while writing the very first version of
this query, against real V2Store data, before it shipped). `action_queue`
surfaces PENDING intents (reference price explicitly `"PENDING --
resolved at the target session's own open, never invented ahead of
time"`, never a fabricated number) and recent outbox rows with `state`
shown as-is (PENDING/RETRY = queued, NOT delivered; only SENT confirms
delivery). `shared_campaign_ledger_note` states explicitly that the
positions/cash shown are a symbol-filtered VIEW of the SAME shared
$300,000 V2 campaign ledger the Active V2 tab shows — never implied as a
separate account or portfolio. V2's own `positions` table carries no
administrative-adjustment marker at all (unlike Original/Experimental,
where the Task 131 SPCX closure lives) — this is stated directly rather
than building unused UI around a column that doesn't exist for this
lane.

**Frontend**: new `Broad Discovery` nav button + `renderV2Discovery()` in
`dashboard_web_static/index.html`, registered in `SECTION_RENDER` (the
existing hash-based deep-link routing, `sectionFromHash()`, picks it up
automatically — no new routing code needed). 6 new `.pill` CSS states.
A real bug caught during local verification: the first draft returned
`pill(...)`'s own HTML markup from inside a `boundedTable()` cell's
`get()` function — `boundedTable()` pipes every cell through
`esc(num(...))`, which would have HTML-escaped the pill markup into
literal broken text. Fixed to return the plain status string in table
cells (matching every other existing renderer's own convention — none of
them do this either); now covered by a dedicated regression test.

**Verification, honestly scoped to this environment's actual tools**:
this environment has no browser-automation tool and no Node.js. The real
`dashboard_web.py` + `index.html` were served against two isolated
fixture scenarios (populated/gated/mixed-candidates, and
empty/disabled/permissive) via real headless Chrome (`--headless=new
--screenshot`), using the SPA's own pre-existing hash-based deep-linking
to land directly on the new tab. Every displayed value was reconciled
against the SAME run's raw `/api/section/v2_broad_discovery` JSON. The
existing Active V2 and Overview tabs were also screenshotted against the
same populated fixture to confirm zero regression. A narrow-screen
(390px) rendering characteristic (long `.kv` row values extending past
the viewport rather than wrapping) was found and confirmed, via a
side-by-side screenshot, to be an existing characteristic of the shared
`.kv` component already present on the UNMODIFIED Active V2 tab — not
something this task introduced, and not in scope to fix here. Full
evidence, reconciliation tables, and the tooling-limitation disclosure
live in `results/task131_concurrent_admission_spa_acceptance/
SPA_ACCEPTANCE.md` (gitignored, evidence-only, like every other
`results/` acceptance record in this repo).

Automated (non-browser) coverage: `tests/test_task131_spa_discovery_
backend.py` (backend fields, real V2Store fixtures, the classifier's
UNCLASSIFIED fallback) and `tests/test_task131_spa_frontend.py`
(static-content assertions on `index.html`, matching this repo's own
established pattern for testing the SPA file — e.g. `test_task100c_
unified_dashboard.py::test_45_narrow_layout_integrity` — plus an
aiohttp `TestClient` wiring check; no JS test runner is available in
this environment, so these are the meaningful automated checks that ARE
runnable here).
