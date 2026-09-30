# Raw-adjustment contamination audit (Phase B), 2026-10-01

**Scope:** read-only across **all 12 remote branches**. Metadata only: no outcome was recomputed and no study was re-run.
- Branch: `research/raw-adjustment-audit`, based on `origin/main` @ `696370e`.
- Tooling: `research/raw_adjustment_audit/`. The split metadata is in `results/raw_adjustment_audit/split_events.json`.

**Reserved windows:**
- 2024-06-01..09-02 and 2024-10-21..12-20 were **not queried**. The Task75B guard is vendored byte-identical and a test
  proves it refuses both.
- Inside those windows only the public facts already recorded by Task75A are cited: NVDA 10:1 around 2024-06-10 and
  AVGO 10:1 around 2024-07-15.

## B1. Code that requests Alpaca bars, and its adjustment

When `adjustment` is omitted, Alpaca defaults to **raw**. The blob columns identify identical copies across branches.

| File:line | Mode | Timeframe | Branches (blob) | Use |
|---|---|---|---|---|
| `scripts/download_historical_1m.py:208` | **raw (hard-coded)** | 1Min | all 12 (`164f2fce71`) | research downloader behind `data/historical_1m/*`: Tasks 7B–75 and `task93_canonical_v1` / 95A |
| `research/scripts/task63r_probe_alpaca_feeds.py:66` | raw | 1Min | all 12 (`24958675c0`) | feed probe (no verdict) |
| `research/scripts/task124_alpaca_feed_probe.py:28,68` | raw | 1Min/1Day | profitability (`c2961ed9dc`) | feed probe (no verdict) |
| `research/scripts/task125_acquire_intraday.py:98,141,158` | **raw** | 1Min | profitability (`738e2ccd0d`) | Task 125 Track B acquisition |
| `research/scripts/task125_feed_provenance_probe.py:14,49` | raw | 1Min/1Day | profitability | probe |
| `research/scripts/task107a_prices.py:59` | **all** | 1Day | 10 branches (`f84c2d38e9`) | Task107 / V2 / 116 daily prices |
| `research/scripts/task107b_form4_cluster.py:19` | all (documented) | — | 10 branches | consumes 107a / 95g |
| `talonx_premarket/config.py:36` (+ `alpaca_data.py:137`) | **split** (default) | 1Min/1Day | main, feature | Opportunity Engine ingestion and the `talonx_paperperf` forensics (inherit split) |
| `talonx_paperperf/gap_reversion_run.py:43` | raw (override) | 1Day/1Min | feature (`9461bcb084`) | LARGE_GAP_REVERSION_V1, with an explicit SPLIT_DAY exclusion |
| `talonx_paperperf/v2_validation.py:155` | all | 1Day | feature | V2@1 validation |
| `research/task75b_preflight/download_all.py:73` | all | 1Min | task75b | TASK75_DATASET_ALL_V1 |
| `talonx_v2/pricing.py:207` / `provider_contract.py:61` / `sip_adapter.py` | split (release contract) or all (older blob `e74ab41d0a`) | 1Day | 5 branches / 3 branches | live V2 pricing (dividends paid as explicit cash) |
| `talonx_piv/alpaca_historical_warmup.py:92`, `talonx_ingest/shared_gateway/alpaca_gateway.py:154` | raw (omitted) | 1Min / latest | 10 branches | **live** intraday runtime, not research |
| `docs/.../2026-09-29_dynamic_tradable_universe/tools/fetch_d1_features.py:48` | raw (omitted) | 1Min | feature | DTU study D-1 coverage/range features (no alpha verdict) |
| `docs/.../2026-09-25_continuous_live_validation/tools/skip_impact.py:67` | raw (omitted) | 1Min | feature | skip-impact evidence (no alpha verdict) |

**Unknown code:** the acquisition code for `task93_canonical_v1`, `task95a` and `task95b_daily_v1` is **not on any branch**.
Their untracked local manifests record the adjustment:

| Dataset | Adjustment |
|---|---|
| `task93_canonical_v1` | "UNADJUSTED (Alpaca 1-min bars as delivered)" |
| `task95a` | "raw (unadjusted) — identical to task93_canonical_v1" |
| `task95b_daily_v1` | "SPLIT-ADJUSTED adj_* columns (raw retained; volume not adjusted)" |
| `task95g_sp500_daily_v1` | Alpaca SIP `adjustment=all` |

## Split / spin-off events in research data windows

Source: Alpaca `/v1/corporate-actions`, queried by process date with ex-date selection (the Task75 A1 fix). Universe:
the 35 frozen names plus SPY, BABA, SHOP and SPCX.

| Year | Events (ex-date) |
|---|---|
| 2020 | AAPL 4:1 (08-31), TSLA 5:1 (08-31) |
| 2021 | NVDA 4:1 (07-20), ISRG 3:1 (10-05) |
| 2022 | AMZN 20:1 (06-06), SHOP 10:1 (06-29), GOOGL 20:1 (07-18), TSLA 3:1 (08-25), PANW 3:1 (09-14) |
| 2024 (outside reserved windows) | **LRCX 10:1 (10-03)** |
| 2024 reserved windows (not queried; Task75A public facts) | NVDA 10:1 (~06-10), AVGO 10:1 (~07-15) |
| 2025 | HON spin-off (10-30), **NFLX 10:1 (11-17)** |
| 2026 | CMCSA spin-off (01-05), **BKNG 25:1 (04-06)**, **KLAC 10:1 (06-12)**, HON 1:2 / spin-off (06-29) |

(The MXIM, XLNX and VMW stock mergers are acquiree delistings, with no price adjustment to the 35.)

**Contradiction found:** `task93_canonical_v1`'s own data-quality report states "none of the 35 split in
2025-01 → 2026-08". The ex-date audit shows NFLX (2025-11-17), BKNG (2026-04-06) and KLAC (2026-06-12) inside that span.
Its > 25% one-minute close scan evidently did not see the overnight step. That report's corporate-action section is
**unreliable**.

## B2. Research verdicts on raw-sourced data

Every row cites where the verdict lives: branch @ commit.

**Classes:**
- `INTRADAY_SAME_SESSION_ONLY`: a split cannot fall inside a session.
- `MULTI_DAY_FEATURE`: lookbacks, ATR spanning the boundary, prior-session pivots, N-day returns or regime state.
- `MULTI_DAY_HOLDING`: positions are held across sessions.
- `EXPLICIT_SPLIT_EXCLUSION`: splits are handled by a rule.

| # | Study | Where (branch @ commit) | Dataset (adjustment) | Window | Class | Verdict (direction) | Split in window? |
|---|---|---|---|---|---|---|---|
| 1 | **Task 74/74B**: multi-day discovery, nominating the Task75 short-reversion candidate | alpha-phenomenon @ `7a64a98` (results), ledger `16d2b2a` | `data/historical_1m` 4 dev slices (**raw**) | 2025-02..2026-08 | MULTI_DAY_FEATURE + MULTI_DAY_HOLDING | **positive** (nomination) | **YES**: NFLX 10:1, KLAC 10:1, HON ×2. **Already rechecked in Phase A → Task75 RETIRED** |
| 2 | **Task 71**: structural discovery, nominating `IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1` | alpha-phenomenon @ `727daaa` | same 4 dev slices (**raw**) | 2025-02..2026-08 | MULTI_DAY_FEATURE (+ overnight holding) | **positive** (nomination); later failed validation (#3) | **YES**: NFLX, KLAC, HON |
| 3 | Task 72/73: residual-momentum LONG V1 validation | alpha-phenomenon @ `345af45` | `task72_validation` (**raw**) | 2024-04-01..05-31 | MULTI_DAY_FEATURE + overnight holding | negative (`VALIDATION_FAIL`) | **NO** split in window (dividends unadjusted, minor) |
| 4 | Task 67A/68: F6_FADE phenomenon / freeze | alpha-phenomenon @ ledger `16d2b2a` | `task67a_development` (**raw**) | 2026-05-15..08-14 | INTRADAY_SAME_SESSION_ONLY (13:30–14:00 UTC window, 60-minute hold, session close) | positive (phenomenon) | yes (KLAC, HON), **not reachable** intraday |
| 5 | Task 70: F6 validation (PASS) / replication (FAIL) | alpha-phenomenon @ `6743527` | `task70_validation` / `task70_replication` (**raw**) | 2024-02-01..03-15 / 2024-09-03..10-18 | INTRADAY_SAME_SESSION_ONLY | negative (`F6_ALPHA_REJECTED` after replication fail) | replication contains **LRCX 10:1 (2024-10-03)**, not reachable intraday |
| 6 | **Task 121/121A/121B**: `EXPERIMENTAL_RELAXED_V1` full-history replay (**no EOD flatten**) | profitability @ ledger `5282219` | `task93_canonical_v1` (**raw**) | 2019-06..2025-08 | **MULTI_DAY_HOLDING** + MULTI_DAY_FEATURE | negative / inconclusive (`DO_NOT_ADVANCE`) | **YES**: 2020 AAPL/TSLA, 2021 NVDA/ISRG, 2022 AMZN/GOOGL/TSLA/PANW, 2024 LRCX (+ reserved-window NVDA/AVGO) |
| 7 | Task 93: frozen-strategy full-history baseline | main `RESEARCH_STATUS.md` @ `9bec279` (results local, untracked) | `task93_canonical_v1` (**raw**) | 2025-01..2026-08 | MULTI_DAY_FEATURE (prior-session pivots, 15-minute SMA200, ATR across the open) | negative (`EDGE_WEAK_OR_UNPROVEN`) | **YES**: NFLX, BKNG, KLAC, HON, CMCSA. **Its own CA check wrongly said none** |
| 8 | Task 94: 49 intraday event studies | main @ `9bec279` (local results) | `task93_canonical_v1` (**raw**) | 2025-01..2026-08 | mixed: mostly INTRADAY; any lookback / regime features are MULTI_DAY_FEATURE | negative (0/49) | YES (as #7) |
| 9 | Task 95A: regime expansion (opening drift) | main @ `9bec279` (local results) | `task95a` (**raw**) | 2020..2026 | INTRADAY entry, but regime labels are MULTI_DAY_FEATURE | negative | **YES**: every event above |
| 10 | Task 101A/101B: event-first and trend-gate dip-reclaim | main @ `9bec279` | `task95a` lineage (**raw**) | 2020..2026 | MULTI_DAY_FEATURE (15-minute trend gate / HTF) | negative (`TREND_GATE_LEAD_REJECTED`) | YES |
| 11 | Task 125 Track B: overnight actionable (next-open exit) | profitability @ `7c8bcab` | `task125` acquisition (**raw**) + `task93_canonical_v1` | 2022-12..2025-08 | MULTI_DAY_HOLDING (overnight) + **partial** EXPLICIT_SPLIT_EXCLUSION (±50% guard) | inconclusive / `DO_NOT_ADVANCE` | LRCX 10:1 in window if in cohort; guard excludes split-sized moves (Task 126 already flagged it as incomplete) |
| 12 | Task 56: family holdout | alpha-phenomenon @ ledger `16d2b2a` | `data/historical_1m` (**raw**) | 2025-12-11..2026-07-09 | MULTI_DAY_FEATURE (V1 pivots / HTF) | negative (`FAMILY_EFFECT_WEAKENED`) | **YES**: CMCSA, BKNG, KLAC, HON |
| 13 | Task 61R: FPRC_V1 validation | alpha-phenomenon @ ledger `16d2b2a` | `data/historical_1m` (**raw**) | 2025-05-06..08-14 | MULTI_DAY_FEATURE | negative (`FPRC_V1_REJECTED`) | NO |
| 14 | Task 63P/63R: ORPB_V1 | alpha-phenomenon @ ledger `16d2b2a` | `data/historical_1m` (**raw**) | 2025 | INTRADAY opening-range, plus V1 features | negative (`ORPB_V1_REJECTED` / data not ready) | window-dependent, low |
| 15 | Tasks 7B–22, 26, 36, 46, 52–59: V1 Original backtests | all branches, ledger `636fa9c` / `16d2b2a` | `data/historical_1m` (**raw**; 10 and 35 symbols) | ~2025–2026 | MULTI_DAY_FEATURE (+ some overnight holds pre-Task 24) | negative / retired | window-dependent (NFLX, BKNG, KLAC, HON, CMCSA) |
| 16 | LARGE_GAP_REVERSION_V1 | feature @ `86f7375` | Alpaca raw 1-minute, gap from the prior close | 2024-01..2026-09 | MULTI_DAY_FEATURE (prior close) + **EXPLICIT_SPLIT_EXCLUSION** (SPLIT_DAY rule) | negative (UNSUPPORTED) | handled by rule (54 SPLIT_DAY exclusions) |
| 17 | DTU study | feature @ `2b3bae3` | raw 1-minute D-1 coverage / range | 2026-09 | D-1 feature, not an alpha verdict | n/a (capture study) | NO |

**Not raw-sourced (split-safe; listed for completeness):**

| Study | Adjustment |
|---|---|
| 95B, 95C-D, 95I, 95K, 97 | `task95b_daily_v1` split-adjusted; SPY `all` (stock dividends unadjusted, a small excess-return bias) |
| 95E, 95G, 107A/B, 109–116, 123 Track A | `all` |
| V2@1 validation (2026-09-30) | `all` |
| Profitability forensic, alpha hypotheses, RS Phase A, VR_PAPER_V1 | split 1-minute (prior-session pivots split-adjusted) |
| Task75B corrected | `all` |

## B3. Downloader change (this branch)

**`scripts/download_historical_1m.py` has no default adjustment:**
- `--adjustment {raw,split,all}` is **required**.
- `raw` is **refused** (exit 2) unless `--allow-raw-intraday-only` is passed.
- The mode is passed to the provider and recorded in `download_summary.json`.

**Per provider:**

| Provider | Support |
|---|---|
| Alpaca | raw, split, all |
| Polygon | raw or split; all refused |
| yfinance | all only (`auto_adjust=True`) |

Unsupported combinations are refused before any request.

**Tests:** 48 in `tests/test_download_historical_1m.py`: 40 existing, updated to pass an explicit adjustment, plus 8 new.

**Callers that now fail closed until they choose an adjustment** (not edited):
- `research/scripts/task61r_download_alpaca.py`
- `research/scripts/task62_probe_alpaca_availability.py`
- `research/scripts/task63_download_alpaca.py`

**Other branches carrying their own, old copy** (blob `164f2fce71`, raw hard-coded; **not edited**, propagation is your
decision):
- `feature/continuous-opportunity-engine`
- `research/talonx-alpha-phenomenon-discovery`
- `research/task75b-corporate-action-preflight`
- `research/talonx-profitability-2026-09`
- `research/talonx-strategy-validation-framework`
- `hotfix/task118a-experimental-exit-lifecycle`
- `hotfix/task118f-resilient-warmup`
- `hotfix/task119-paper-performance-dashboard`
- `evidence/v2-full-day-session-01`
- `audit/v2-39-stock-missed-opportunities`
- `fix/v2-sec-filing-date-admission`

(`main` is the base of this branch.)

## B4. Ranked recheck list

Positive multi-day verdicts come first. **Nothing here was re-run**; you choose.

| Rank | Study | Why | Priority |
|---|---|---|---|
| — | Task 74/74B → Task75 | done in Phase A: edge = split artefacts, **retired** | DONE |
| 1 | **Task 71 → residual-momentum LONG nomination** | positive nomination on raw multi-day development data containing NFLX/KLAC 10:1 and HON events; the later validation failed on a split-free window, so the nomination itself may have been split-inflated like Task75 | **HIGH** (verifies the discovery lineage; the verdict is already negative downstream) |
| 2 | **Task 121/121A/121B** | raw **multi-day holding** (no EOD flatten) over 2019–2025 with eight splits in window; a false negative or false positive is possible; inconclusive CI | **MEDIUM** |
| 3 | **Task 93 / 94** | raw data plus multi-day V1 features, and the dataset's own corporate-action check is demonstrably wrong (NFLX/BKNG/KLAC); negative verdicts, but the canonical dataset feeds later work | **MEDIUM** (fix the dataset claim first) |
| 4 | Task 95A / 101A-B | raw 2020–2026, many splits, multi-day regime / trend features; negative | LOW–MEDIUM |
| 5 | Task 125 Track B | raw overnight holding with a partial ±50% guard; inconclusive | LOW |
| 6 | Task 56, Tasks 7B–59 (V1 lineage) | raw with V1 multi-day features; negative and retired | LOW |
| — | Task 72/73, 61R | no split in their windows | NONE |
| — | Task 67A/68/70 (F6) | same-session only | NONE |
| — | LARGE_GAP_REVERSION_V1 | explicit SPLIT_DAY exclusion | NONE |
