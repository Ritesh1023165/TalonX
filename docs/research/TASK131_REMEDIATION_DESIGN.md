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
