# Task 130 — frozen signal, execution, portfolio, and economic-gate protocol

Written and committed BEFORE `research/scripts/task130_discovery_evaluation.py`
is run against any real return outcome. Only code-reading, existing
artifact inspection, and the universe-manifest build (no return/P&L)
preceded this freeze.

## Part 3 — signal and prospective execution contract

### Preserved unchanged (verified from `talonx_v2/config.py`, `liquidity.py`, `pipeline.py`, direct source read)

- `INSIDER_BUY_CLUSTER_V2@1`, fingerprint `11107198c5b81237` (re-verified
  before the run; the run aborts if it has moved).
- ≥2 distinct reporting-owner Code-P (open-market purchase) filings for
  the same issuer within 10 trading sessions (`cluster_window_trading_days=10`,
  `min_distinct_owners=2`, `transaction_code="P"`).
- Causal activation: an episode's `eligible_entry_session` is the first
  XNYS session strictly after the qualifying 2nd owner's filing becomes
  causally available (`entry_offset_sessions=1`).
- Exit target: `add_sessions(entry_session, 10)` (`hold_trading_days=10`).
- Bounded exit fall-forward: `exit_fallforward_max_sessions=5` — if the
  exact +10td session has no bar, the first available close within 5
  sessions is used; all 5 missing → explicit `EXIT_UNRESOLVED`, never a
  silent hold or invented price.
- 5-session re-entry cooldown per issuer (`reentry_cooldown_trading_days=5`).
- No pyramiding (`allow_adds=False`), no shorts (`allow_shorts=False`),
  no real capital (`allow_real_capital=False`).
- Deduplication: `detect_episodes_for_issuer` filters to code-P rows
  with a non-null owner CIK/filing date, deduplicates via `_dedupe`
  (verified in `cluster_engine.py`), and sorts deterministically by
  `(filing_date, owner_cik)` before greedy non-overlapping clustering —
  no additional owners are manufactured from duplicate/amended records;
  this task's `records_provider` reuses the SAME dedup path unchanged.

### Eligibility rule — resolved from actual code, not the documented label

`talonx_v2/liquidity.py`'s own docstring documents the FROZEN contract
as membership-OR-liquidity ("the S&P 500/400 membership branch... is an
OR — when a PIT membership list is available it also passes"). **Direct
grep across every `talonx_v2/*.py` module found NO implementation of
the membership branch anywhere** — only two comments describing it as
theoretical. **The actually-executed rule, verified, is LIQUIDITY-ONLY**:
trailing-20-trading-session MEDIAN dollar volume (`close × volume`,
causal — only sessions strictly before the entry session) ≥
$5,000,000, AND last close ≥ $5.00. **This is named here as a real
difference between the documented contract and the executed research/
runtime code** — this task evaluates the ACTUALLY-EXECUTED liquidity-
only rule, the same rule every prior V2 replay (Task 111/112R/115/116/
118D/120A-C) has actually run under; it does not inherit Task 112R's
acceptance automatically, but is the best-evidenced, most-used
interpretation, chosen over inventing an unimplemented membership
branch.

### Prospective-only campaign rule — a genuine, documented policy CHANGE

**Current runtime behavior (verified, `talonx_v2/service.py`
`_on_entry_recorded`, `delayed = pre_intent is not None`)**: an episode
whose `eligible_entry_session` arrives without a durable
`pending_entry_intents` row already present (e.g. backlog/cold-start at
replay or live-service start) is STILL ENTERED — the resulting alert is
merely labelled `"NOTE: no earlier intent existed (cold-start
backfill)... not prospectively actionable."` **This is a real,
documented policy the current runtime permits — this task's stricter
policy is a genuine change from it, not "unchanged runtime behavior."**

**This task's frozen policy (`v2_prospective_policy_v2`, isolated to
this evaluation, no production code modified)**:

- Historical filings and dispositions may still be stored/observed.
- The existing 45-day rolling causal filing window is preserved
  unchanged.
- **A new campaign position requires a durable `pending_entry_intents`
  row that already existed (created on a strictly earlier simulated
  session) before the target-entry deadline.**
- **A cold-start episode without such a prior intent does NOT create a
  position and does NOT change campaign cash** in this task's Track B
  reporting (see below) — it is recorded as
  `NO_PRIOR_INTENT_EXCLUDED_FROM_PROSPECTIVE_TRACK`, a new, explicit
  disposition label distinct from every existing `SKIPPED_*` reason.
- Delayed reconciliation of a TIMELY intent (one that existed before
  the deadline but whose fill is only reconciled later) is permitted,
  with all timestamps retained — this is the existing `delayed=True`
  path, unchanged.

**Implementation approach (documented before running)**: rather than
modifying `talonx_v2/service.py` (out of scope — research-only,
isolated code per this task's authorization), this task runs the
UNMODIFIED production-adjacent replay ONCE (producing a complete,
faithful `pending_entry_intents` ledger via the real
`V2Service.tick()`'s own existing pre-open-intent pass — verified this
task to already run causally, one session at a time, inside
`talonx_research.replay_engine.run_chronological_replay`), and then
derives TWO SEPARATE, ISOLATED analysis tracks from that one ledger in
this task's own research code:

- **Track A — historical ideal-timing evidence**: every closed trade
  the unmodified replay produced (includes cold-start entries) — this
  is what every prior V2 replay (Task 111 onward) has always reported.
- **Track B — timestamp-proven prospective-policy evidence**: only
  closed trades where `store.entry_intent(episode_id) is not None`
  (the code's own exact definition of "not cold-start") — this task's
  **new, isolated, post-hoc reconstruction**, with its own SEPARATELY
  RECOMPUTED chronological cash/position/equity series (only Track B's
  own entries/exits move cash in this reconstruction — a cold-start
  trade genuinely does not touch Track B's campaign cash, satisfying
  the frozen rule above without modifying the underlying replay).
- **Track C — operational latency evidence**: NOT available from any
  offline replay by definition (it requires observing REAL ingestion/
  delivery latency from a live-running service) — reported as
  `UNAVAILABLE_REQUIRES_LIVE_OBSERVATION`, not approximated or
  fabricated from historical dates alone.

**Timestamp limitation, stated explicitly**: the historical Form 4
research parquet has FILING DATES, not intraday dissemination times.
No intraday timestamp is manufactured or presented as "observed" —
every causal-timing claim in this task operates at trading-SESSION
granularity (consistent with every prior V2 task), never finer.

## Part 4 — portfolio and capacity rules (frozen before outcomes)

- **Starting capital**: **$300,000**, an isolated research-only pool —
  this figure is chosen to match Tier 4's specification and happens to
  equal the PRODUCTION V2 campaign's own paper balance, but is a
  **completely separate ledger/database** (never `v2_lane.db`,
  `talonx_research.replay_engine`'s own hard safety check enforced) —
  no connection to, and no effect on, the real campaign.
- **Per-position allocation**: $10,000 (`per_position_allocation_usd`,
  existing default, unchanged).
- **Maximum concurrent positions**: 20 (`max_concurrent_positions`,
  existing default, unchanged, enforced in `talonx_v2/paper.py`:
  `store.n_open() >= cfg.max_concurrent_positions` → skip).
- **Maximum simultaneous entry notional**: $200,000 — verified
  mathematically EQUIVALENT to (not a separate enforcement beyond) the
  existing 20-position × $10,000 cap, since every position is sized at
  exactly $10,000 (`calculate_buy` spends `min(allocation_usd, cash)` —
  never more than the fixed allocation). Reported explicitly as market
  EXPOSURE (simultaneous entry notional), not a market-value or
  loss-risk cap — a position's later mark-to-market value can exceed or
  fall below its $10,000 entry notional; that is not this cap.
- **No borrowing / no negative cash**: verified existing behavior
  (`talonx_paper.engine.calculate_buy`: `spend = min(allocation_usd,
  cash)`, returns `None`/no-entry if `cash <= 0`) — never spends more
  than available cash. Reused unchanged, tested this task (Part 6).
- **Cash evolution**: `store.cash()`/`set_cash()` persists across the
  full replay — no daily reset, no periodic top-up.
- **Reservation of cash/slots for pending intents**: a `PENDING`
  `pending_entry_intents` row does **not** reserve cash or a position
  slot in the existing runtime (verified: `upsert_entry_intent` performs
  no cash/slot mutation) — capacity is checked only at the moment of
  actual entry (`process_episode` → `paper.enter_position`). This is
  the existing, reused behavior; not changed by this task's Track B
  filter (which only gates WHETHER an entry may proceed at all, not
  how capacity is checked once it does).
- **Deterministic ordering under competing capacity**: verified this
  task — `detect_episodes` groups by symbol (insertion order of a
  deterministically-sorted `records_provider` output) and
  `detect_episodes_for_issuer` sorts by `(filing_date, owner_cik)`
  before clustering; this task's own `records_provider` sorts its
  output by `filing_date` before every call (same pattern as Task
  118D's `run_populations_bc.py`) — tested this task (Part 6) for
  run-to-run determinism.
- **Simultaneous entries/exits**: the existing tick loop processes
  exits before entries within one session (verified,
  `talonx_v2/service.py::tick`, `settle_due_exits` called after the
  entry loop but a symbol's own same-day sequencing follows the
  existing, unmodified pipeline order) — reused unchanged.
- **Late reference price**: handled by the existing bounded
  exit-fall-forward (5 sessions) and `SKIPPED_NO_ENTRY_BAR`/
  `EXIT_UNRESOLVED` dispositions — never a fabricated fill.
- **Missing prices / unresolved exits**: reported explicitly by
  disposition/status, never silently dropped or defaulted to zero.
- **Selection under capacity uses no future information**: verified —
  `paper.enter_position` is evaluated strictly at the entry session's
  own OPEN, using only that session's own price and the current,
  already-realized `store.cash()`/`store.n_open()` state; no future
  price or outcome influences which episode is admitted.

Qualified signal decisions (episode detected, liquidity-passed,
BUY-decided), capacity-blocked paper outcomes (`MAX_CONCURRENT_20`),
and notification outcomes (alert enqueue/delivery) are kept as
SEPARATE, distinctly-labelled counts throughout (Part 7).

## Part 5 — economic gates (frozen before any new return is computed)

- **Primary economic criterion**: mean net return per closed round trip
  **> +0.50%** after 20bps round-trip friction (applied exactly once:
  `net = (exit_price − entry_price)/entry_price − 0.0020`).
- **Statistical criterion**: 95% issuer-block bootstrap (resampling
  distinct ISSUERS, not individual trades — preserving issuer-repeat
  dependence, the same method Task 118D already used, seed **130130**,
  5,000 reps) lower bound **> 0**.
- **Time-dependence sensitivity**: a date-block bootstrap (resampling
  distinct FILING/ACTIVATION dates in non-overlapping monthly blocks,
  seed 130130, same rep count) reported ALONGSIDE the issuer-block
  result — acknowledges shared market periods (a cluster of episodes
  activating in the same week/month are not independent of each
  other's market regime).
- **Disagreement-between-methods rule, frozen now**: if the issuer-block
  and date-block CIs disagree on whether zero is excluded, the verdict
  defaults to the MORE CONSERVATIVE (wider-including-zero) of the two —
  i.e., a clean PASS requires BOTH methods' lower bound > 0, not either
  one alone.
- **Top-issuer-removal sensitivity**: recompute mean net return removing
  the top 1, top 3, and top 5 issuers, where **"top" = ranked by
  absolute count of closed trades contributed** (the same convention
  Task 118D/122/123 already used) — reported alongside the primary
  result, never substituted for it.
- **Calendar-period stability**: mean net return by calendar half-year
  across the frozen window — reported, not used to cherry-pick a
  sub-window.
- **Concentration measure**: top-1-issuer share of total closed trades
  and of total net P&L.
- **Cost applied exactly once**: verified in code (Part 6 tests) — the
  20bps figure appears in exactly one subtraction per trade, both in
  the underlying replay's own `friction_bps` reporting field and in
  this task's own net-return recomputation.
- **Benchmark / market-exposure comparison**: SPY buy-and-hold over the
  identical window, same starting capital convention, reusing
  `results/task107a_form4_feasibility/_prices/SPY.csv` (the same
  source/convention already used in Tasks 125/127/128) — reported for
  context, never used to claim alpha from a positive absolute return
  alone.
- **Portfolio-risk reporting**: maximum marked-equity drawdown and
  capital utilization are reported with precise definitions (Part 7).
  **No user-approved drawdown tolerance exists and none is invented
  here** — risk is reported explicitly; economic qualification (this
  section's gates) is kept SEPARATE from any future deployment-risk
  acceptance decision, which this task does not make.

### Decision verdicts (fixed now, not rewritten after results)

- **`PASS_FOR_INTEGRATION_REVIEW`** — Track B's primary criterion is met
  AND both uncertainty methods' lower bounds exceed zero AND the
  top-1/3/5-issuer-removal sensitivity does not reverse the sign of the
  primary result AND no single calendar half-year is the sole source of
  a positive result.
- **`DO_NOT_ADVANCE`** — Track B's primary criterion is not met, or
  either uncertainty method's CI is entirely negative.
- **`INCONCLUSIVE`** — Track B's CI(s) include zero under the
  disagreement rule above, without a clear negative reading.
- **`BLOCKED_BY_SPECIFIC_EVIDENCE_GAP`** — Track B's closed-trade count
  is too small for either uncertainty method to run at all (e.g. fewer
  than the minimum issuer-block count needed for a meaningful
  resample), named exactly, not substituted with Track A's larger
  (cold-start-inclusive) sample to manufacture a bigger N.

**The prior +1.01%/10-trading-day headline (Task 112R, the 39-name live
scope under the original runtime) is explicitly NOT an automatic pass
for this task's different population (626-name Discovery Universe v1),
different capacity rules ($300k/$10k/20-max, vs. Task 112R's own
convention), and different prospective policy (Track B's intent gate,
which did not exist as a filter in Task 112R's own reported number).**
Each of these differences is named, not glossed over, and this task's
own Track B result is evaluated fresh against the criteria above.

## Stopping rule

Run once, this exact frozen contract, over the predeclared window
(2024-09-01 → 2026-03-31, Task 118D's own matched-runtime window,
reused — not re-searched). No threshold, horizon, issuer-subset, or
universe search after outcomes.
