# Live-universe floor DTU_V2: close ≥ $5 and ADV20 ≥ $20M (2026-10-04)

**Owner decision (2026-10-04).** The live Opportunity Engine universe requires:
- a previous completed regular-session close of at least USD 5;
- average daily dollar volume over the previous 20 completed sessions of at least USD 20M.

Membership is refreshed daily, using only data available before the session's decisions.

This is a **tradability and workload change. It is not evidence of profitability.** No spread, volatility, fundamental, reverse-split or going-concern filter was added.

| | |
|---|---|
| Implementation commit | `daa1d29` (branch `feature/oe-live-liquidity-floor`, fast-forwarded into `feature/continuous-opportunity-engine`) |
| Policy | `DTU_V2_LIVE_FLOOR`, fingerprint `65f3285f8181c552` (DTU_V1 is still `da27de22a3bb839a`) |
| Activation | Engine restarted 2026-10-04 20:50:35Z. First window under DTU_V2: **2026-10-05**, effective from its start (2026-10-05 00:00Z) |
| Rollback | `TALONX_DTU_POLICY=DTU_V1` (see below) |

## 1. Exact eligibility definition

**Authority.** There is one membership authority: `talonx_opportunity/universe_tiers.py`, through `classify_members`, `DTU.ensure_snapshot` and `resolve`. The window snapshot (`market.db`, tables `dtu_snapshot` / `dtu_snapshots`) is the only membership record. All consumers read it:
- ingestion's fetch set;
- discovery's admission set (`read_admission`);
- Sentinel's `/universe` views (`universe_view.py`, read-only).

### Inputs

| Item | Definition |
|---|---|
| Price/volume source | Alpaca SIP `1Day` bars with **`adjustment=raw`** (as traded). These go to a separate table, `dtu_live_daily`. They are **never mixed** with the split-adjusted `daily` table, which still feeds V1 features and the gap-trigger reference close. |
| Close | The bar's `c`: the official consolidated regular-session close (closing auction). Verified on AAPL 2026-10-01: daily `c` 330.32, while the last RTH minute closed at 330.48. |
| Session volume | The bar's `v`: Alpaca's consolidated daily volume, including extended-hours prints. Verified on AAPL 2026-10-01: 36.47M daily, against 26.34M summed over RTH minutes. |
| Session dollar volume | `c × v` for each session, both as traded. |
| ADV20 | The mean of the session dollar volume over the **20 completed XNYS sessions ending at D-1**, from `exchange_calendars` `XNYS.sessions_window(D-1, -20)`. Weekends and holidays are never sessions. Early-close sessions are completed sessions and count. |
| Reference close | The as-traded close of D-1, the previous completed session (`TradingWindow.reference_session`). |
| Cutoff | Request `end` = `min(D 00:00Z, SIP as-of) − 1 s`. A bar of D (the current or partial session) cannot be fetched. A bar dated outside the 20 sessions is ignored anyway. There is no lookahead and no invented value. |
| Refresh | Once per trading window, at window start (OVERNIGHT/PREMARKET, before any decision). The snapshot is immutable for the window. If the policy changes inside a window, the snapshot is rebuilt and the rebuild is recorded (`SNAPSHOT_REBUILT_POLICY_CHANGE`). |

### Thresholds

Both thresholds are **inclusive**: `close ≥ 5.00` and `ADV20 ≥ 20,000,000.00`.

### Validity

All 20 sessions need a valid bar: numeric, `c > 0`, `v ≥ 0`. A zero-volume bar counts, at USD 0 dollar volume.

### Reason codes

The codes are mutually exclusive. Data quality is decided first; only then the thresholds.

| Code | Report category |
|---|---|
| `LIVE_DATA_FETCH_FAILED` | DATA_QUALITY. The raw fetch batch failed; it is retried before the snapshot. |
| `LIVE_DATA_NO_HISTORY` | DATA_QUALITY. No bar in the 20 sessions. |
| `LIVE_DATA_STALE_NO_D1_BAR` | DATA_QUALITY. No bar for D-1. |
| `LIVE_DATA_INSUFFICIENT_<n>_OF_20` | DATA_QUALITY. |
| `LIVE_DATA_INVALID_BAR:<date>` | DATA_QUALITY. |
| `LIVE_BELOW_CLOSE_5` | PRICE_ONLY |
| `LIVE_BELOW_ADV20_20M` | LIQUIDITY_ONLY |
| `LIVE_BELOW_CLOSE_5_AND_ADV20_20M` | PRICE_AND_LIQUIDITY |
| `BELOW_V1_*` / `NO_D1_DAILY_HISTORY` | RETAINED_V1_RULE. The existing V1 floors, still applied after the live floor. |
| `STRUCTURAL:*` | STRUCTURAL. The existing instrument eligibility: funds, ETFs, warrants and so on. |

### Retained rules

All existing rules still apply:
- the structural instrument eligibility;
- the V1 floors;
- Core = top 1200 by ADV20, now ranked on the as-traded ADV20;
- the gap trigger (≥ 3 %, rest of window) and the SEC 8-K trigger (3 sessions);
- operator precedence and position/intent safety.

The live floor only adds an exclusion. A promotion from an earlier window, such as an 8-K TTL, **cannot** re-admit a symbol that fails the floor.

### Admission vs management

Discovery creates a **new** candidate identity only for a symbol in the window's qualifying set (Core plus event tier). It **fails closed** while no snapshot of the running policy exists. Funnel counter: `ADMISSION_BLOCKED_LIVE_FLOOR`.

A symbol that fails the floor still stays **fetched** for management when it has any of:
- a V2 open position or pending intent;
- V2 execution scope;
- an operator add;
- an open WATCH/SETUP identity;
- a PAPER_SIGNAL this window.

Existing identities keep their lifecycle (updates, invalidation, expiry). The outcome tracker fetches its own bars for every live candidate and is universe-independent.

### Fail-safe

If the window snapshot cannot be built, ingestion fetches the full eligible base, so existing work keeps its data. Discovery admits nothing new. Both facts are recorded: the `dtu_active.fallback_reason` and funnel `DTU.admission=FAIL_CLOSED_NO_SNAPSHOT`.

### Benchmarks and other subscriptions

None depend on the OE universe, so none needed preserving:
- **SPY** is fetched directly by the ingestion capability probe.
- **Sector and benchmark ETFs** are STRUCTURALLY_EXCLUDED and were never OE candidates.
- **The OE outcome tracker, the V2 companion, the V2 forward tracker, the VR tracker and the DTU shadow collector** each fetch their own data.

## 2. Operational data acquisition

This is the only new provider use. It is **one** extra raw-daily fetch per window, for the eligible universe and the 20-session window only:
- about 29 requests (5,6xx symbols at 200 per request, one page each);
- through ingestion's existing `RateLimiter(120)` and `AlpacaData.bars_ex` (batch retry, explicit failure set);
- at window start (00:00Z), when no session fetching runs.

Research download/load guards were not touched. No historical validation outcome file was read.

## 3. Universe summary, latest completed session

Window **2026-10-05**, data as of the **2026-10-02** close, sessions 2026-09-04 .. 2026-10-02. The counts below are from the pre-activation preview, which uses the same code path. See §6 for the engine-built match.

| | count |
|---|---:|
| Universe members (all) | 14,388 |
| Structurally excluded (unchanged rule) | 8,748 |
| Previous admissible pool, DTU_V1 on the same data (Core 1200 + event-eligible) | **3,898** |
| Qualifying under DTU_V2 (Core 1200 + event-eligible 890) | **2,090** |
| Retained | 2,090 |
| Added | 0 |
| Removed | **1,808** |

**Removed by category** (mutually exclusive):

| Category | count |
|---|---:|
| Price only | 69 |
| Liquidity only | 1,269 |
| Both | 459 |
| Data quality | 11 |

**All excluded, ELIGIBLE base, by category:**

| Category | count |
|---|---:|
| Price only | 75 |
| Liquidity only | 1,920 |
| Both | 1,532 |
| Data quality | 23 |
| Retained V1 rule | 0 |

**Data-quality detail (23):**
- 21 `INSUFFICIENT_n_OF_20`, including **TEVA at 15/20**: the provider has 15 bars since 2026-09-14 in both the raw and the split tables. It is excluded explicitly; V1 averaged whatever bars existed.
- 1 `NO_HISTORY` (SVA).
- 1 `STALE_NO_D1_BAR` (UCFI).
- 0 fetch failures.

**Protected subscriptions** (fetched for management at report time, not admissible): 393 symbols failing the floor.
- 392 are open setups carried from window 2026-10-02.
- 1 is V2 scope.
- Discovery's idle expiry shrinks the open-setup protections as the window proceeds.

V2 execution scope: 39 symbols, of which 38 qualify. Open V2 positions: 0.

**Reconciliation:**
- the categories sum to the members;
- qualifying = Core + event;
- qualifying = retained + added;
- previous = retained + removed;
- removed-by-category sums to removed.

All five checks **PASS**.

**Full lists** (local operational reports, not in git):
- `results/opportunity/universe_reports/<window>/universe_<window>_members.csv`: every symbol with state, reason, category, change, as-traded close, ADV20, previous state and protection;
- `universe_<window>.json`;
- `universe_<window>_summary.txt`.

The engine writes them at each window start. `python -m talonx_opportunity universe-report [--window D]` rebuilds them read-only.

## 4. Workload

**Measured** on the last live window (2026-10-02, DTU_V1):

| | value |
|---|---|
| Effective active per cycle | min 1,367 · mean 2,061 · max 2,565 |
| 1-min ingestion fetched symbols per cycle | mean 2,032 |
| 1-min bar batches over the window | 7,949 |
| Gap/8-K sweep pool (EVENT_ELIGIBLE) | 2,706 symbols, about 3 snapshot requests per sweep |
| Day-end composition | Core 1,162 · event-promoted 1,364 · V2 scope 39 |

**Estimated** for DTU_V2 (not measured yet):
- The admission pool falls from 3,898 to 2,090 (−46 %).
- The sweep pool falls from 2,706 to 890 symbols, about 1 request per sweep.
- The effective active set is bounded by 2,090 + management-only protections (≤ 393 at the start, shrinking), so ≤ about 2,480 at worst, against a measured V1 max of 2,565.
- The typical active set should fall more, because only 890 (not 2,706) symbols can be gap-promoted.

The first measured DTU_V2 numbers come from the 2026-10-05 session (`cycles`, `dtu_active`).

## 5. Deployment boundary (repository rules: `talonx_opportunity/runtime.py`)

The change alters the DTU config fingerprint. A config-fingerprint change forces the component's material class and **cannot be declared down**.

| Component | Class | Decided by |
|---|---|---|
| ingestion | **DATA_FIX** | `RULE:CONFIG_FINGERPRINT_CHANGED` |
| discovery | **STRATEGY_MATERIAL** | `RULE:CONFIG_FINGERPRINT_CHANGED` |

Both carry the owner-decision reason (declarations #31 and #32).

The change affects detection, candidate and alert counts, notification and profitability analysis. It is **not** OPERATIONS_ONLY.

**Pre-existing drift, unrelated to this change:** evaluators ×4, notifier, outcomes, reporting and promotion had run code older than `86f7375`. Their only changed source was the shared `talonx_opportunity/runtime.py`. They were recorded **OPERATIONS_ONLY** through the repository's verified F-P2 procedure (`declare-shared-runtime --apply`, declarations #23 to #30, version-bound). The shutdown manifest's expectation of "unchanged-restart rows only" was therefore incorrect for these eight. Sentinel was an unchanged restart.

## 6. Activation evidence

Filled in after the engine built window 2026-10-05; see `activation.md` in this folder.

## 7. Trackers

| Tracker | Universe dependence | Handling |
|---|---|---|
| **VR paper tracker** (`vr_live`, until 2026-10-16) | **Inherits**: it reads OE PAPER_SIGNALs | Restarted with the same end date. Every window is labelled with its OE universe segment (`vr_live.db` meta `universe_segment:<window>`; `eod_<window>.json` `oe_universe_segment`). SEG1 = DTU_V1 (2026-09-30 .. 10-02, interrupted by the shutdown, no session missed). SEG2 = DTU_V2 (2026-10-05 .. 10-16). The segments are never pooled. Registry: `results/vr_paper/UNIVERSE_SEGMENTS.json`. |
| **DTU shadow collector** (until 2026-10-08 00:15Z) | **Partial**: its own V1-definition population is unchanged, but its production-open-candidate protection input and any shadow-vs-production comparison change from 10-05 | Restarted with the same end date. Segments: SEG1 production DTU_V1 (09-30 .. 10-02), SEG2 production DTU_V2 (10-05 .. 10-07). Registry: `results/dtu_shadow/UNIVERSE_SEGMENTS.json`. |
| **V2 shadow forward tracker** (daily at 06:00Z until 2026-10-31) | **None**: Form 4 / its own prices | Restarted to sleep until **2026-10-05 06:00Z**, its normal slot. There is no catch-up cycle tonight. |
| **CONTROL/SHADOW forward tracker** | Would inherit | **Stalled since 2026-09-30 and not restarted.** If it is ever resumed, sessions ≥ 2026-10-05 are a separate successor segment. Registry: `results/profitability/UNIVERSE_SEGMENTS.json`. |
| **Original / V2 companion / Intelligence** | None | These are separate strategies and lanes; their code is untouched. |

No tracker end date was extended. ERM (rules, fingerprints, files, pre-registration) was not touched.

## 8. Rollback

The previous configuration is saved in `C:\Users\rites\TalonX_universe_change_backups\20261004T204247Z\`:
- `pre_change_state.json`: SHAs, component versions and config fingerprints, the last deployments, the DTU snapshots and the previous `up` environment;
- the pre-change source files.

**Behavioural rollback** (no code change; restores DTU_V1, fingerprint `da27de22a3bb839a`):

1. Declare both components:
   ```
   python -m talonx_opportunity declare-change ingestion --class DATA_FIX --reason "rollback DTU_V2 -> DTU_V1"
   python -m talonx_opportunity declare-change discovery --class STRATEGY_MATERIAL --reason "rollback DTU_V2 -> DTU_V1"
   ```
2. Stop the engine supervisor loop. It has no stop command: verify its PID, command line and creation time, then terminate it.
3. Run `python -m talonx_opportunity down`.
4. Restart with the **same** environment as the activation, but `TALONX_DTU_POLICY=DTU_V1`:
   ```
   env -u TALONX_OPP_ROOT TALONX_DTU_MODE=ACTIVE TALONX_DTU_POLICY=DTU_V1 TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1 \
     TALONX_SEC_REFRESH_CAPACITY=OBSERVABILITY_ONLY TALONX_NOTIFY_RESEARCH_ENABLED=1 \
     TALONX_OPP_NOTIFY_POLICY=LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925 TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL \
     TALONX_SENTINEL_COMMANDS_ENABLED=1 OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN \
     .venv/Scripts/python.exe -u -m talonx_opportunity up --deliver --supervise
   ```

What happens after the restart:
- Ingestion rebuilds the current window's snapshot under DTU_V1 automatically (`SNAPSHOT_REBUILT_POLICY_CHANGE`).
- Discovery's admission gate is off under DTU_V1.
- The extra raw-daily fetch stops.
- `dtu_live_daily*` and the reports are additive tables and files; they can stay.

**Residual difference under DTU_V1:** `resolve` now lets an open-identity protection keep an AUTO_EXCLUDED symbol fetched. Under V1's own floors ($1 / $1M) such identities cannot be created, so this is inert.

**Code rollback**, if the code itself must go: `git revert daa1d29` on the live branch (never a force-push), then the same declare-and-restart.

## 9. Tests

`tests/test_live_universe_floor.py` (14 tests) covers:
- the inclusive $5 / $20M boundaries and combined exclusions;
- the owner values and the unchanged V1 fingerprint;
- the prior-session cutoff, weekend, holiday (Thanksgiving 2025), early close and partial-session exclusion;
- the fetch window ending before D, with failed-batch retry;
- the 20-session mean, and missing / stale / insufficient / invalid / fetch-failed data;
- one membership shared by ingestion, discovery and Sentinel;
- the snapshot rebuild on a policy change;
- position, setup and V2-scope retention without admission;
- the discovery admission block while existing identities are still managed;
- fail-closed admission;
- outcome-tracker independence;
- the window-start snapshot and report built before PREMARKET;
- report counts reconciling to the CSV lists;
- VR segment labelling with the end date unchanged.

The DTU_V1 tests in `tests/test_dtu_universe.py` are pinned to `TALONX_DTU_POLICY=DTU_V1`.

**Affected-lane regression:** 17 modules (every test importing `talonx_opportunity`, `vr_live`, `universe_view` or `talonx_shadow`), **307 passed**.
