# Dynamic Tradable Universe (DTU_V1) — implementation record, 2026-09-30

Branch `feature/continuous-opportunity-engine`. **Not deployed** at the time of writing. Live Signal policy, SQF_V1
and the forward-alpha experiment are unchanged. Paper only.

## 1. What it does

`talonx_opportunity/universe_tiers.py` selects which structurally eligible symbols receive **full** processing:
1-minute bars, features, scoring, SEC lookups and lifecycle.

| State | Rule | 09-30 count (dry run, 08:25Z, real data) |
|---|---|---|
| ACTIVE_CORE | V1-floor eligible, top 1,200 by D-1 ADV20 | 1,200 (1,162 + 38 counted as V2 scope) |
| EVENT_ELIGIBLE | V1-floor eligible outside the Core; promotable, **not excluded** | 2,620 |
| EVENT_PROMOTED | live promotion (durable: reason, start, expiry, source id, snapshot version, policy version) | 94 (gap 71 / 8-K 26 at first sweep) |
| AUTO_EXCLUDED | structurally eligible, below V1's own hard floors (price < $1 or ADV20 < $1M): V1 can never create a candidate from it | 1,735 |
| OPERATOR_ADDED | operator add (only in operator mutation ACTIVE) or V2 execution scope | 39 (V2 scope) |
| OPERATOR_EXCLUDED | operator exclusion (only in operator mutation ACTIVE; DRY_RUN today → none applied) | 0 |
| STRUCTURALLY_EXCLUDED | universe.py EXCLUDED:reason | 8,728 |
| **Effective active at start** | Core + promoted + operator/V2 + protected | **1,295** (full baseline 5,650) |

**Order of precedence** (highest first):
1. V2 open position or pending entry intent — this overrides even an operator exclusion.
2. OPERATOR_EXCLUDED.
3. OPERATOR_ADDED and V2 scope.
4. Structural and V1-floor exclusions.
5. CORE.
6. Live promotion.
7. Lifecycle protection.
8. EVENT_ELIGIBLE.

**Protection:**

| What | Kept active until |
|---|---|
| V2 position / pending intent | resolved |
| Open BULLISH/BEARISH setup identity | invalidated or expired |
| PAPER_SIGNAL promoted this window (its INTRADAY/SAME_DAY horizon) | the window closes |
| **WATCH identity created in this window** | the rest of this window only (WATCH never locks a symbol in across windows) |

**Triggers.** These are the only study-supported sources:
- **GAP:** |delayed_sip latestTrade / V1 reference close − 1| ≥ 3%, using V1's 45-minute stale gate and V1's own
  previous close from market.db daily. The snapshot's own daily fields are not used, per the field contract verified
  on 09-29. TTL: rest of the window.
- **SEC_8K:** from the EDGAR current-events feed, polled every 5 minutes. TTL: 3 sessions (**provisional**).
- **Not implemented:** a relative-volume trigger (no study evidence) and Form 4 (no universe-wide purchase codes).

**Ownership (reduces work upstream):**
- **DATA_INGESTION** is the single writer of `market.db`. Each cycle it builds the D-1 snapshot once per window from
  the daily bars it already fetches. It then runs the sweep: EVENT_ELIGIBLE symbols only, ~3 requests / ~2.7 s. It
  resolves the active set and passes **only that set** into the 1-minute fetch batches.
- **DISCOVERY** reads the resolved set (read-only) and filters members **before** features, scoring and SEC lookups.
- **yfinance:** not used by the Opportunity Engine (N/A).
- **D-1 snapshot:** `market.db` tables `dtu_snapshots` / `dtu_snapshot`, with version
  `<window>@<reference session>#<policy fp>`. It uses only daily bars dated ≤ the reference session, so it is causal.
  For 09-30 the Core and V1 pool are **identical** to the shadow collector's (1,200 / 3,915, 0 differences).

**Fail-safe:**
- **Triggers:** DTU ACTIVE plus any of the following falls back to the **full eligible universe**:
  - missing, empty or corrupt snapshot (fewer than 90% of members);
  - unreadable V2 positions;
  - V2 scope unavailable;
  - any resolution error.
- **Visibility:** the fallback is recorded in `dtu_active.fallback_reason`, the ingestion detail, discovery's funnel
  `DTU.fallback`, and Sentinel `/universe summary` ("⚠️ FALLBACK full universe"). It never produces a silent partial
  universe.
- **Stale snapshot:** a snapshot is keyed by window, so a new window always builds its own and a stale one is never
  reused.

**No replay:**
- A promoted symbol is backfilled from 04:00 ET only as indicator/aggregate warm-up. Discovery evaluates its *current*
  state, producing at most one NEW event per identity at the promotion scan (tested).
- On demotion or restore, lifecycle simply continues, with no events for the inactive interval (tested).
- Telegram and Signal eligibility rules are untouched.

## 2. Operator visibility

Sentinel commands (all read-only; `market.db` opened `mode=ro`):
- `/universe summary` — every state count plus effective active, and the fallback flag if set.
- `/universe status SYM` — operator state plus the DTU tier, reason, Core rank and latest promotion with its expiry.
- `/universe excluded` — the non-Core summary by reason (no symbol flood).
- `/universe excluded file` — a CSV with symbol, state, reason, price, ADV20, core_rank, promotion_eligible and
  snapshot_date.

`/status` and `/ping` now show separately:
- the OE universe (Core / promoted / effective / event-eligible, or "full, DTU OFF");
- the V2 / filing scope (39, a separate lane);
- PAPER_SIGNAL sent / queued / expired / rejected for a named window;
- Lab immediate vs digest counts today.

The rollover-invalidation roll-up is **deferred**: it would change Lab routing (notifier), which is out of scope.

## 3. Version and boundaries

| Component | Change | Class at its restart |
|---|---|---|
| ingestion | code (`ingestion.py`, `universe_tiers.py`) + config fp `DTU` (only when ACTIVE) | **DATA_FIX** (forced by the config fingerprint: data selection) |
| discovery | code + config fp `DTU` (only when ACTIVE) | **STRATEGY_MATERIAL** (forced: it changes which symbols can produce candidates, so detection and candidate counts are segmented) |
| sentinel | read-only commands and status | OPERATIONS_ONLY (default class for sentinel) |
| every other component | `runtime.py` only (hash coverage) | OPERATIONS_ONLY via `declare-shared-runtime --apply` at its next restart |

Hash coverage now also includes: `universe_tiers.py` and `operator_control/gates.py` for ingestion and discovery,
`ingestion.py` for discovery (it imports `read_state`), and `universe_view.py` for sentinel.

**V2 release preflight:** `talonx_shadow/` and `talonx_paperperf/` were added to the isolated research-lane prefixes
(never imported by the frozen release; guarded by a test), and `universe_view.py` to the operator-control list.
Without this the next V2 start would have been refused (`repo_head_matches_release`); this was found while testing.

**Forward-alpha boundary:** activating DTU changes which symbols can produce CONTROL Signals. The CONTROL *policy*
fingerprint components for promotion do not change, but the discovery config fingerprint does. The activation time
must be recorded as a boundary in `forward_alpha_validation.md`, and sessions before and after it are reported
separately.

## 4. Deployment (NOT executed; needs authorization; do it between sessions, not mid-session)

Run from a shell with the runbook §S3 environment plus `TALONX_DTU_MODE=ACTIVE`:
1. **Supervisor first.** Stop the current supervisor loop; components are detached and keep running. Start
   `python -m talonx_opportunity up --deliver --supervise` again with the same environment **plus**
   `TALONX_DTU_MODE=ACTIVE`, so any automatic respawn keeps DTU on. `up` reports ALREADY_RUNNING for every component.
2. `declare-change ingestion --class DATA_FIX --reason "DTU_V1 universe routing (ingestion-owned snapshot/sweep/active set)"`,
   then `restart ingestion`. Wait for the first `dtu_active` row with `fallback_reason IS NULL`.
3. `restart discovery`. This is forced STRATEGY_MATERIAL by the config fingerprint, with the declaration supplying the
   reason. Confirm the next scan's funnel shows `DTU.applied = true`.
4. `restart sentinel`: new commands.
5. Record the forward-alpha boundary; run `python -m talonx_shadow.dtu_canary_compare <window>` after the first
   session.

**Do not restart** V2, promotion, notifier, evaluators, outcomes or reporting; they aren't needed.

## 5. Rollback (immediate, no DB rollback, no replay)

Restart the supervisor, ingestion and discovery with `TALONX_DTU_MODE=OFF` (or unset):
- The config fingerprints return to their pre-DTU values, and the boundary is recorded.
- Ingestion fetches the full eligible universe from its next cycle.
- Symbols that were inactive resume from their last watermark, which backfills bars only; discovery evaluates current
  state only, so there is no event replay.
- The `dtu_*` tables stay as audit history.

## 6. Tests

`tests/test_dtu_universe.py` (14 tests), covering:
- snapshot causality and determinism;
- Core, event-eligible and auto-excluded states;
- gap and 8-K promotion with persistence and restart;
- TTL expiry;
- operator add and exclude precedence;
- position/intent protection beating exclusion;
- the WATCH window bound;
- fail-safe on a corrupt snapshot or unreadable positions;
- stale-gate gap calculation;
- OFF as an identity with unchanged fingerprints;
- ingestion fetching only the active set;
- discovery evaluating only the active set, with a visible fallback;
- **no replay on promotion or restore** (behavioural);
- read-only Sentinel views;
- the forward-alpha and Signal policy fingerprints unchanged.

Regression: 124 across engine, operator, Sentinel, release-check and DTU suites, plus 355 across SEC, notifier,
promotion, shadow, forward and forensic suites. The only failure is the known baseline `test_ri3_operator`
(Windows subprocess environment).
