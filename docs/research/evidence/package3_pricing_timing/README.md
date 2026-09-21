# Package 3 — Authoritative Pricing, Refresh, Evidence Timestamps & Deadlines

**Type**: implementation task, following Package 2's acceptance
(`docs/research/evidence/package2_account_blocks/ACCEPTANCE_REVIEW.md`,
verdict `PACKAGE2_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`). Branch
`feature/task131-option-a-integration`. Starting HEAD `dc553c1`
(verified: current branch, current HEAD, clean tree — no drift to
reconcile).

## 1. P3-A — Price authority map

```
signal/evidence (SEC Form 4, code P)
  -> InsiderStore.query_transactions()          [accepted_at_utc = SOURCE event time]
  -> InsiderStore.get_filing()                  [ingested_at_utc = TalonX DURABLE receipt time]  (NEW, wired this package)
  -> cluster_engine.detect_episodes()            [activation = 2nd distinct owner filing -- UNCHANGED]
  -> liquidity gate (20-session median $-vol >= $5M, close >= $5)
  -> _verify_temporal_boundary()                 [causal + receipt check, live-tick-only]
  -> ADMISSION: upsert_entry_intent()             durable PENDING intent, pre-open window
       (persists source_event_ts_utc/receipt_ts_utc -- NEW, this package)
  -> price_lookup(symbol, eligible_entry_session) [entry-session OPEN]
       - "csv" mode (default/live): V2Service._bars() -- direct CSV read, NOW validated (this package)
       - "composite-yf"/"composite-iex": pricing.PricingResolver -- already validated (validate_bar)
  -> price refresh/retry: _pending_retry_episodes, re-attempted every tick, bounded by
       the recovery deadline (NOW unified + proactively checked -- this package)
  -> paper.enter_position(): calculate_buy(cash, allocation, entry_price) -> (shares, cost)
  -> V2Store.insert_open_position(entry_price=..., shares=..., position_cost=...)  [write-once]
  -> persisted position (cost basis) -> later close_position() re-reads this SAME row
       (Package 2 acceptance A5's own fix) for P&L
```

**Every price source used**:

| Source | Provider | Timestamp | Session-scoped | Persisted | Mutable | Caller-supplied | Stale detection | Missing->0 risk | Fallback |
|---|---|---|---|---|---|---|---|---|---|
| `V2Service._bars()` ("csv" mode, **default live wiring**) | frozen Task 107A Alpaca SIP snapshot (static CSV) | none (date-only) | yes (exact date match) | no (re-read from CSV each call, cached in-process) | no (static file) | no (service reads its own files) | no | **YES -- found and fixed this package** (NaN via `float(getattr(r,"open","nan"))`; NaN is truthy, bypassed the missing-price check) | none needed (source is fixed; row simply excluded if malformed) |
| `pricing.PricingResolver` ("composite-yf"/"composite-iex" modes, **not the live default**) | CSV history + yfinance/Alpaca-IEX tail | none (date-only) | yes | no | live tail is not static | no | yes (`validate_bar` rejects non-finite/non-positive; same-day bar is PROVISIONAL, excluded) | no (already guarded) | composite: historical CSV authoritative for what it covers, live tail only for the uncovered recent bar |

**The single authoritative entry price**: `entry_price` is computed
**once**, in `pipeline.process_episode()`, from `price_lookup(symbol,
eligible_entry_session)["open"]`, and passed as a single Python float
through `paper.enter_position()` into
`calculate_buy(cash, allocation, entry_price)` (sizing),
`V2Store.insert_open_position(entry_price=...)` (reservation write and
cost basis), and `res.entries[...]["entry_price"]` (the alert/audit
record) — **one variable, one flow, no second read, no possibility of
silent disagreement between sizing/reservation/fill/cost-basis**.
Verified structurally by code trace and directly by
`test_p3a_same_entry_price_flows_into_sizing_reservation_fill_and_cost_basis`.
P&L at exit uses the SAME persisted `entry_price`, re-read fresh from
the authoritative row (Package 2 acceptance's own A5 correction,
unchanged and re-verified this package: Package 1's 14-test suite
still passes unmodified against Package 3's changes).

## 2. P3-B — Missing/stale price semantics

**Previous behaviour (defect found this package)**:
`V2Service._bars()` (the default "csv"-mode bar loader) built each
row's `open` via `float(getattr(r, "open", "nan"))` — a genuinely
missing/blank cell silently became an actual `NaN` float. **`NaN` is
truthy in Python** (`not float("nan")` is `False`), so
`pipeline.process_episode`'s own `if not px or not px.get("open"):`
missing-price check would have **silently passed a NaN price straight
through** into `calculate_buy()`/sizing/cost-basis — `calculate_buy`'s
own `if price <= 0: return None` guard does NOT catch NaN either
(`NaN <= 0` is `False` in Python), so this was a genuine, reachable
"missing price masquerades as a legitimate fill" defect in the
**default, live-wired pricing path**.

**Correction** (`talonx_v2/service.py::_bars()`): each row's
`open`/`close` is now parsed and validated (`math.isfinite(x) and x >
0`) before being included; a malformed/missing/non-positive value
causes **that single row** to be excluded (never fabricated, never
crashes the whole symbol's bar load). `volume` is defensively
normalized to `0.0` on any parse failure (unrelated to price
fabrication — a bad volume correctly fails the liquidity gate rather
than corrupting a price).

**Tests**: `test_p3b_missing_open_value_never_becomes_a_usable_price`
(direct proof of the NaN-truthiness defect and its fix),
`test_p3b_valid_price_is_used_normally`,
`test_p3b_one_malformed_row_does_not_drop_the_whole_symbol` (zero,
negative, and non-numeric rows all correctly excluded; good rows
survive), `test_p3b_missing_price_does_not_fabricate_a_zero_cost_reservation`
(end-to-end: `NO_ENTRY_BAR`, no mutation).

## 3. P3-C — Authoritative price refresh

**Lifecycle** (already substantially correct; verified, not rebuilt):
a missing entry-session price does not block the tick — `_phase_open`
records `PENDING_RETRY` (in `self._pending_retry_episodes`, an
in-memory, per-tick observability list) and the SAME durable
`pending_entry_intents` row (status still `PENDING`) is simply
re-attempted on the service's own next natural tick — no in-call
sleep loop, no uncontrolled polling (Task 131 Remediation Directive
2, pre-existing and unchanged).

- **Causal**: bounded by the SAME recovery deadline as every other
  admission decision (Package 3 P3-D's now-unified boundary).
- **Bounded**: `retry_deadline`/`_recovery_deadline_session` — never
  retried past the deadline.
- **Restart-safe**: the intent's own `PENDING` status is the ONLY
  durable state a retry depends on — a pure function of
  `eligible_entry_session` and the calendar's static session list, no
  process-uptime/last-run state consulted (confirmed by
  `test_p3e_restart_preserves_the_pending_intent_before_processing`,
  a genuinely fresh `V2Service`/`V2Store` instance against the same
  file).
- **Idempotent**: `pipeline.process_episode`'s own idempotency guard
  (`episode_disposition in ("ENTERED","SKIPPED_ENTRY_STALE") or
  position_for_episode(...) is not None`) refuses a repeat fill for
  the same episode (`test_p3e_duplicate_processing_does_not_create_duplicate_signal_or_position`).
- **Auditable**: every retry-exhausted release writes an explicit
  terminal disposition/intent status (`FAILED_NO_MARKET_DATA` or, now,
  `EXPIRED_STALE`/`EXPIRED_RECOVERY_DEADLINE` depending on which gate
  catches it first — see P3-D).
- **No duplicate fill under real concurrency**: proven with two
  genuinely INDEPENDENT `V2Store` connections racing for the SAME
  episode
  (`test_concurrency_independent_writers_cannot_double_fill_the_same_intent`)
  — writer B's own `BEGIN IMMEDIATE` correctly blocks on writer A's
  held SQLite write lock (a bounded `Thread.join` liveness check, not
  a hopeful sleep), and only ONE position/BUY trade exists afterward.

**No new polling architecture was introduced.**

## 4. P3-D — Session-3 recovery deadline (OPS-003 Finding B)

**Defect (OPS-003 Finding B, directly re-confirmed by code inspection
this package before any change)**:

1. Two DIVERGENT deadline computations existed for the same
   parameter: the general admission-eligibility gate (`tick()`'s own
   `stale_cut`) allowed a **4-session** window
   (`eligible_entry_session + 3` sessions), one session wider than the
   agreed 3-session policy; the missing-price retry-release path's OWN
   `retry_deadline` correctly computed the **3-session** boundary
   (`eligible_entry_session + 2`) but only checked it **reactively**,
   after a fill attempt had already missed.
2. A fill was attempted **unconditionally**, with no deadline check
   at all gating a *successful* attempt.
3. Everything was date-granular — no function anywhere carried or
   checked an actual close **timestamp**, so "immediately before" vs.
   "immediately after" the official close of the SAME calendar day
   could not be distinguished.

**Correction**:
- `talonx_v2/calendar.py::session_close_utc()` (new) — the REAL
  official XNYS close timestamp (UTC), via
  `exchange_calendars`' own `session_close()` — correctly returns
  `18:00 UTC` (13:00 ET) for the day after Thanksgiving (an early
  close) vs. the ordinary `21:00 UTC` (16:00 ET), never approximated
  as a fixed hour offset, midnight UTC, or midnight local.
- `V2Service._recovery_deadline_session()` (new) — the SINGLE, unified
  Session-3 boundary (`add_sessions(eligible_entry_session,
  max_entry_staleness_sessions - 1)`), now used by BOTH the coarse
  `stale_cut` gate (widened boundary removed — `tick()`'s own
  computation corrected from `-max_entry_staleness_sessions` to
  `-(max_entry_staleness_sessions - 1)`) and the new proactive check
  below.
- `V2Service._recovery_deadline_passed()` (new) — LIVE: compares the
  real wall clock against Session 3's own ACTUAL close timestamp
  (strictly-after semantics — "at or before qualifies," per Session 6
  §I / `S6-24`'s agreed equality resolution). Non-live (replay/
  backtest/restart-independent by design, matching OPS-003 Finding B's
  own item 4, which was already correct and is unaffected): date-only,
  `ripe_through > deadline_session`.
- `_phase_open()` now calls this PROACTIVELY, immediately after the
  existing look-ahead-bias check and BEFORE any fill attempt — the
  reactive missing-price-path's own release logic is left in place
  unchanged (now effectively a redundant, harmless second line of
  defense for the specific "missing price" sub-case, since the
  proactive check already catches every "deadline has passed" case
  first).

**Deliberately NOT touched**: `max_entry_staleness_sessions`'s frozen
default value (3) is unchanged; the reactive missing-price release
path's own code is unchanged (still correct, now redundant-but-
harmless for the deadline-passed sub-case).

**Tests** (all required scenarios from the task):
`test_p3d_session3_is_computed_via_the_real_calendar_ordinary_week`
(Mon->Wed), `test_p3d_weekend_is_skipped_by_the_real_calendar`
(Thu->following Mon, weekend skipped),
`test_p3d_market_holiday_is_skipped_by_the_real_calendar` (Labor Day
never counted as a session),
`test_p3d_early_close_session_uses_the_actual_early_close_timestamp`
(the real 18:00 UTC vs. 21:00 UTC, directly against `exchange_calendars`),
`test_p3d_live_tick_immediately_before_session3_close_still_qualifies`
/ `test_p3d_live_tick_immediately_after_session3_close_is_refused`
(exactly at the close and one minute before still qualify; one minute
after is refused — a frozen, controlled clock, not real time.sleep),
`test_p3d_replay_tick_date_only_boundary_matches_live_session_boundary`,
`test_p3d_pending_intent_released_not_left_zombie_after_deadline` (no
new fill, terminal intent status, cash unchanged).

One pre-existing test's assertions were corrected as a disclosed,
intended consequence of closing the 4-session/3-session gap (see
`tests/test_task131_nonblocking_retry.py`,
`test_price_still_missing_next_session_releases_intent_exactly_once`):
the episode is now excluded by the tightened OUTER gate one tick
earlier than before, so its terminal state is now `EXPIRED_STALE`
(via `_phase_post_close`'s pre-existing staleness sweep) rather than
`FAILED_NO_MARKET_DATA` (via `_phase_open`'s reactive path) — still
terminal, still exactly-once, still no economic mutation; only the
specific terminal label changed.

## 5. P3-E — Durable evidence receipt vs. processing time

**Timestamps traced**:

| timestamp | meaning | source | durable? | decision use |
|---|---|---|---|---|
| `InsiderTransaction.accepted_at_utc` | SEC EDGAR's own filing-acceptance instant | SEC EDGAR (provider) | yes (in `InsiderStore`, the source system's own durable store) | look-ahead-bias check (must be strictly before entry-session RTH open) — pre-existing |
| `InsiderFiling.ingested_at_utc` | TalonX's OWN durable receipt of the filing | TalonX's ingestion service (`talonx_ingest.intelligence.service`) | yes | **NEW this package**: ALSO checked against the same RTH-open boundary in `_verify_temporal_boundary`, and durably persisted onto the admission record |
| `pending_entry_intents.created_at_utc` | TalonX's own admission-time durable record | this store | yes | intent-creation-time causality check (pre-existing) |
| `positions.entry_price`/`entry_session` | the fill itself | this store | yes | economic mutation (Package 1/2's own protections) |
| `trades.executed_at` | fill timing | this store | yes | audit trail |

**Defect found and closed**: `_verify_temporal_boundary` only ever
checked `accepted_at_utc` (the SOURCE's own timestamp) against the RTH
-open causal boundary. TalonX's own durable receipt timestamp
(`InsiderFiling.ingested_at_utc`) was **never consulted at all** — so
a filing SEC accepted before RTH open but that TalonX itself did not
durably ingest until AFTER RTH open would have incorrectly passed,
based purely on the source's own timestamp. This is exactly the "late
receipt masquerading as timely because the source timestamp was
earlier" failure mode this package must prevent.

**Correction**: `_refresh_dissemination_lookup` now ALSO populates
`self._receipt_lookup` (one `InsiderStore.get_filing()` lookup per
distinct accession, cached within the same refresh call — no N+1
blowup) with the LATEST `ingested_at_utc` per `(symbol, filing_date)`.
`_verify_temporal_boundary` now additionally refuses if a KNOWN
receipt timestamp is not strictly before the RTH open — checked only
when the receipt timestamp is actually available (soft no-op
otherwise: `InsiderFiling.ingested_at_utc` is a required, non-nullable
column in real `InsiderStore` data, so this is populated in every
genuine production read; a caller/test that never wired
`_receipt_lookup` at all is exercising an unrelated concern and must
not be spuriously broken by this addition — confirmed: the full 252-
test V2 regression run passed unchanged with this addition in place).
Both timestamps are now ALSO durably persisted onto the admission
record itself (`pending_entry_intents.source_event_ts_utc`/
`receipt_ts_utc` — see P3-F).

**Required invariant, both directions, proven**:
- `test_p3e_late_receipt_is_refused_even_with_an_earlier_source_timestamp`
  — source timestamp 1 hour before RTH open (timely), receipt
  timestamp 2 hours AFTER RTH open (late) -> refused, citing the
  receipt timestamp explicitly.
- `test_p3e_timely_receipt_and_timely_processing_admits_normally`,
  `test_p3e_timely_receipt_but_delayed_processing_still_admits` (fill
  attempted a full session later than admission -- still succeeds,
  never penalized for the processing delay).
- `test_p3e_restart_preserves_the_pending_intent_before_processing`,
  `test_p3e_duplicate_processing_does_not_create_duplicate_signal_or_position`.

## 6. P3-F — Price/evidence auditability

**Schema change** (additive only, `ALTER TABLE ... ADD COLUMN`,
following this store's own pre-existing migration convention — no
destructive migration, no new table): `pending_entry_intents` gained
`source_event_ts_utc TEXT` and `receipt_ts_utc TEXT` (both nullable),
populated at admission time (`upsert_entry_intent`) from
`_dissemination_lookup`/`_receipt_lookup` when known.

**What can now be reconstructed for a filled V2 trade** (querying
`pending_entry_intents` joined to `positions`/`trades` by
`episode_id`): qualifying evidence identity (`episode_id`,
`activation_filing_date`, `issuer_cik`), the source timestamp where
available (`source_event_ts_utc`), TalonX's own durable receipt
timestamp where available (`receipt_ts_utc`), admission timing
(`created_at_utc`), target entry session (`target_entry_session`),
recovery/fill session (`fill_entry_session`), the selected
authoritative entry price (`positions.entry_price`, identical to
`pending_entry_intents.fill_price`), fill timing (`trades.executed_at`),
and expiry reason if never filled (`status` + `detail`).

**What remains unavailable (disclosed, not fixed)**: the specific
price bar's own `status`/`source` (FINAL vs. PROVISIONAL, which
adapter) is computed by `pricing.PricingResolver` but discarded at the
`price_lookup(symbol, session) -> {open, close, volume}` callable
boundary before it ever reaches `pipeline.process_episode` — so "why
was THIS specific price eligible" cannot currently be reconstructed
beyond "it was the entry session's own `open`, and it passed whatever
validation the active pricing mode performs." Threading this through
would touch multiple call-site signatures (`price_lookup`'s own
contract, `pipeline.process_episode`, `_price()`) — judged broader
than this package's bounded scope; recorded as a P2 follow-up, not
fixed here.

## 7. P3-G — OPS-003 Finding A / historical compatibility

**Classification: `PARTIALLY_COMPATIBLE`**

Directly re-confirmed by code inspection this package (Task 112R's own
finding had been "recorded for future re-verification," not
re-checked since): `talonx_v2/cluster_engine.py` still fires
`activation_filing_date` at the filing_date of the **2nd distinct
owner** (`if len(seen) == cfg.min_distinct_owners: activation_fd =
r.filing_date`, `min_distinct_owners` = 2, the frozen contract) — this
runtime semantics is **unchanged** by Package 3 (this package touches
pricing/timing/admission-deadline/evidence-receipt logic only, never
`cluster_engine.py`'s own episode-detection/activation rule).

Task 112R's own prior, still-unrefuted finding established that the
ORIGINAL research methodology (`build_episodes`, used to compute the
`+2.0219%`/`+2.196%`/`+1.69%` headline profitability figures cited in
`S2-15`) determines entry eligibility at the **LAST** filing in a
cluster window, not the 2nd — a concretely different rule that
produced 326 entry-session differences in Task 112R's own offline,
like-for-like comparison. **This makes those ORIGINAL headline figures
INCOMPATIBLE with the runtime's actual entry-session semantics** — not
a rounding difference, a materially different selection rule.

However, not every prior V2 result shares this incompatibility: Task
112R's OWN "G2b" re-evaluation explicitly re-ran its comparison using
the runtime's real 2nd-distinct-owner semantics (net@20 +1.01%,
corrected from +1.69%), and Task 115/116's validation-framework replay
(a SEPARATE, later, isolated-worktree task) drives the REAL
`V2Service.tick()` chronologically and reproduced G2b bit-for-bit
within its own comparison window — meaning **G2b and the Task 116
replay figures ALREADY use compatible, runtime-matching entry-session
semantics**, distinct from the original P1/P2 headline figures.

**Consequence, precisely**: the ORIGINAL `S2-15`-cited headline
figures (`+2.0219%`/`+2.196%`/`+1.69%`) must NOT be attributed to the
release runtime implementation as-is — they were computed under a
different entry-selection rule. Only the G2b-corrected figure
(net@20 +1.01%, `TASK112R`) and the Task 116 replay figures may be
treated as runtime-representative, and even those predate Package 3's
own pricing-authority/deadline corrections (the NaN-price defect,
the unified Session-3 boundary, the receipt-timestamp check) — so a
full reconciliation of "does the runtime-matching historical
figure still hold under Package 3's corrected admission/pricing
logic" remains open for the parallel prior-research reconciliation
track. **No profitability was recomputed, no historical result was
rewritten, and no strategy parameter was tuned by this package** to
produce this classification — it is derived entirely from
already-existing Task 112R/115/116 evidence plus this session's own
direct, unmodified code inspection of `cluster_engine.py`.

## 8. Provider limitations (disclosed, not resolved)

The DEFAULT, live-wired provider remains `CsvBarAdapter` — a frozen,
static replay of the Task 107A Alpaca SIP `adjustment=all` snapshot
(`pricing.py`'s own docstring: "the frozen conformant default").
`YFinanceBarAdapter` (data-only, `CONFORMANT = True` **only within its
own tested parity-study domain**) and `AlpacaIexBarAdapter`
(explicitly `NON_CONFORMANT`) exist as probes/candidates, never
auto-enabled for ACTIVE. **What the current provider establishes**: a
deterministic, already-validated historical daily-bar series with an
explicit FINAL/PROVISIONAL distinction and non-fabricating rejection
of malformed rows (this package closed the ONE gap where that
validation was bypassed, in the "csv" mode's own direct bar loader).
**What it does NOT establish**: genuine "official auction price"
finality — there is no confirmation this is NYSE's own official
opening/closing auction print versus an ordinary consolidated daily
bar; this is `OPS-005`'s own already-disclosed, pre-existing gap, not
newly introduced or newly resolved here. This package did not switch,
activate, or purchase any provider, and does not claim finality beyond
what `validate_bar`'s FINAL/PROVISIONAL status already, honestly,
represents. Provider qualification remains a separate, parallel track.

## 9. Restart / idempotency / concurrency

- **Restart**: `test_p3e_restart_preserves_the_pending_intent_before_processing`
  uses a genuinely fresh `V2Service`/`V2Store` instance against the
  same on-disk file — the durable `PENDING` intent and the correct
  (still-not-passed) deadline computation both survive unchanged.
- **Duplicate processing**: `test_p3e_duplicate_processing_does_not_create_duplicate_signal_or_position`
  — `pipeline.process_episode`'s pre-existing idempotency guard
  (unchanged by this package) refuses a repeat fill attempt for an
  already-`ENTERED` episode.
- **Refresh race / duplicate fill**: `test_concurrency_independent_writers_cannot_double_fill_the_same_intent`
  — TWO independent `V2Store` connections (not two calls on one
  instance), a bounded `Thread.join(timeout=0.5)` liveness check
  proving the second writer is genuinely blocked on SQLite's own real
  write lock (not merely unlucky in timing) before release, exactly
  one position/BUY trade afterward.
- **Expiry racing fill**: structurally prevented by the SAME
  `V2Store.transaction()` (`BEGIN IMMEDIATE`) serialization Package
  1/2 already established — the deadline check and the fill attempt
  are both evaluated inside `_phase_open`'s single pass per episode
  per tick; a concurrent block/expiry write from another connection
  would need to acquire the same write lock, exactly the mechanism
  already re-verified in Package 2's own acceptance review (A4).

## 10. Tests and results

```
.venv/Scripts/python.exe -m pytest tests/test_package3_pricing_timing.py -p no:cacheprovider -q
19 passed (run 3x to confirm no flakiness in the concurrency test)

.venv/Scripts/python.exe -m pytest tests/test_task113_stale_entry_guard.py tests/test_task131_nonblocking_retry.py -p no:cacheprovider -q
8 passed (2 pre-existing assertions corrected, disclosed above)

.venv/Scripts/python.exe -m pytest <25-file V2 regression -- see below> -p no:cacheprovider -q
252 passed, 3 failed
```

The 3 failures are byte-identical BY NAME to 3 of the 9 pre-existing
failures already documented in Package 1/2's own evidence
(`test_task111_v2_e2e.py::test_item3_original_strategy_fingerprint_unchanged`,
`test_task112_tuesday_release.py::test_03_v1_fingerprint_intact` — both
report the SAME `ed8272fe568d` value, the already-tracked `OPS-017`
finding in `talonx_quant/*`, a subsystem this package never touches;
`test_task131_spa_discovery_backend.py::test_admission_policy_reflects_permissive_default`,
also already documented and unrelated). Zero new failures.

25-file regression scope: `test_task110_v2_integration.py`,
`test_task111_v2_e2e.py`, `test_task112_tuesday_release.py`,
`test_task113_stale_entry_guard.py`, `test_task114_prospective.py`,
`test_task117_phase0_{causality,entry_timing,lifecycle,
source_readiness,source_repairs,universe_enforcement}.py`,
`test_task117_pricing_readiness.py`, `test_task131_{atomic_
transactions,concurrent_admission,nonblocking_retry,remediation_
directive6,spa_discovery_backend,targeted_remediation,temporal_
boundary}.py`, `test_task140_{exit_eligibility_after_scope_change,
reservation_expiry_exactly_once}.py`.

V2's own strategy fingerprint (`11107198c5b81237`) independently
re-verified unchanged via
`tests/test_task114_prospective.py::test_b1_preflight_fingerprints_are_expected`
and `::test_task114_does_not_change_fingerprints` (both pass) — this
package's changes are plumbing/pricing-authority/timing corrections,
never a `V2Config` frozen-parameter or strategy-logic change.

## 11. Production safety

No live TalonX process found (`tasklist`, checked at session start and
again before evidence capture — consistent throughout). `v2_lane.db`
(repo root) and `paper_trading.db`/`dispatch_audit.db`
(`~/.talonx/`) content modification timestamps unchanged throughout
this session (`2026-09-15 05:45`/`21:45` respectively — never touched;
every test uses an isolated `tmp_path` SQLite file). No application
start/stop/restart, no Telegram send, no provider activation/switch,
no real capital, no broker call.

## 12. Package 3 verdict

**`PACKAGE3_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`.**

All 11 acceptance-standard items are satisfied:
1. Missing prices cannot masquerade as valid zero/NaN prices (P3-B,
   fixed and tested).
2. Authoritative entry-price semantics are explicit and single-flow
   (P3-A, traced and tested).
3. Recovery respects the official Session-3 close, via the real
   calendar, not an approximation (P3-D, fixed and tested).
4. Late processing cannot invalidate timely durable receipt (P3-E/
   P3-C, tested).
5. Late receipt cannot masquerade as timely evidence merely because
   the source timestamp was earlier (P3-E, fixed and tested).
6. Restart preserves legitimate recovery obligations (P3-C/P3-E,
   tested).
7. Duplicate processing cannot create duplicate exposure (P3-C,
   tested, pre-existing guard re-verified).
8. Expired recovery cannot create new exposure (P3-D, fixed and
   tested).
9. Persisted trade economics use the accepted authoritative price
   consistently (P3-A/P3-F, tested).
10. Provider-finality limitations are explicitly recorded, not
    fabricated (§8 above — a bounded, disclosed follow-up, exactly as
    the acceptance standard permits).
11. OPS-003 historical/runtime compatibility is explicitly classified
    (`PARTIALLY_COMPATIBLE`, §7 above, evidence-backed).

**Bounded follow-ups** (none block acceptance, per the standard's own
explicit allowance for a disclosed provider-finality limitation and
non-blocking secondary gaps):
- Price bar `status`/`source` (FINAL/PROVISIONAL, adapter identity)
  is not threaded through to the persisted admission record (P3-F §6).
- `OPS-005`'s pre-existing provider-finality gap remains open (§8) —
  unchanged by this package, not newly introduced.
- The full reconciliation of "does the runtime-matching G2b/Task 116
  historical figure still hold under Package 3's own corrected
  pricing/deadline logic" remains open for the parallel prior-research
  track (§7) — explicitly NOT performed here, per the task's own
  instruction not to recompute profitability.
