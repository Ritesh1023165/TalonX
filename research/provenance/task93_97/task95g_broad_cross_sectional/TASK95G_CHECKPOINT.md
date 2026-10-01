# TASK 95G — BROAD-UNIVERSE CROSS-SECTIONAL REPLICATION — CHECKPOINT

> Authoritative Task 95G memory. **After any context/session refresh: READ THIS FIRST.** OFFLINE
> research. Narrow purpose: *does replacing the 35-name survivor universe with a historically-correct
> point-in-time S&P 500 change Task 95E's `CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED`?* This is a
> **replication**, not a factor hunt. `PAID_DATA_SPEND = £0`. No production change, no threshold
> tuning, no live, no PIV alpha, **no ML / no local AI**, no real capital.

## Fixed inputs

| | |
|---|---|
| Starting SHA | `4b0e5dfa2415afe1dbf423c63c9cc479264106fa` (tree clean) |
| Production strategy | UNCHANGED — research code isolated in scratchpad + `results/task95g_broad_cross_sectional/` |
| Free/entitled only | `fja05680/sp500` point-in-time membership (free GitHub) · Task 95F artifacts · Alpaca SIP daily (entitled, GET) · local task95* datasets |
| Task 95E result being tested | `CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED` — its one automated pass (`rel_10d`) was a TSLA/NVDA/AMD 2020/2023 dispersion artifact that failed remove-best-3 + non-monotone deciles |

## Preconditions — DONE

- **A · identity verification** (`identity_verification_report.md`): 3 flagged rows RESOLVED
  (ALXN/KSU/VAR — foreign-parent acquisitions, ticker terminates, no in-universe remap), 3 EXCLUDED
  with reason (AXE legacy/incorrect, MXPS placeholder, CTRA_OLD_COG malformed). No unresolved row
  blocks the task. `ticker_identity_map_verified.csv` written.
- **B · membership cross-check** (`membership_crosscheck_report.md`): Wikipedia reconstruction vs
  `fja05680/sp500` — raw ticker Jaccard 0.955 (dominated by rename-vintage), **company-level Jaccard
  0.988** after rename normalization, residual < 1.5% (backward-walk missing-ADD artifact +
  ±1-3-day offsets). **NOT `TASK95G_BLOCKED_UNIVERSE_INTEGRITY`.** Adopted `fja05680` as primary
  membership (removes the backward-walk artifact).

## Phases

| Phase | State | Artifact |
|---|---|---|
| 1 acquire daily prices | DONE | `broad_daily_dataset_manifest.json` — `task95g_sp500_daily_v1`, **620 symbols / 619 with data / 1,059,207 daily rows**, 2019-06→2026-08, Alpaca SIP `adjustment=all`, fp `08aa253ad4df1121` |
| 2 daily data quality | DONE | `broad_daily_data_quality.md` / `.json` |
| 3 point-in-time panel | DONE | `cross_sectional_panel_manifest.json` — `task95g_sp500_panel_v1` |
| 4 partitions | DONE | `cross_sectional_partitions.json`, `partition_rationale.md` (Task 95B chronology verbatim; discovery only) |
| 5 protocol | DONE | `BROAD_CROSS_SECTIONAL_RESEARCH_PROTOCOL.md` (frozen; G1-G8; symbol-block bootstrap mandatory; top 10%) |
| 6 replicate A-D | DONE | `momentum_replication.md`, `pullback_replication.md`, `vol_adjusted_replication.md`, `relative_volume_replication.md` |
| 7 early-stop gate | see FINAL_REPORT | |
| 8 composite | see FINAL_REPORT | |
| robustness / CI / turnover / sector / survivorship / monotonicity | DONE | respective .md files |
| final report | DONE | `FINAL_REPORT.md` |

## VERDICT

See `FINAL_REPORT.md`. Verdict: **`BROAD_CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED`** —
broader breadth + survivorship control did **not** change Task 95E's conclusion.
`PAID_DATA_SPEND = £0` · `PRODUCTION_STRATEGY_UNCHANGED` · `NO_LIVE_SESSION_REQUIRED_FOR_TASK95G` ·
`NO_LOCAL_AI_REQUIRED`.

## EXACT NEXT ACTION

Task 95G COMPLETE. All artifacts written; tree clean at `4b0e5df`; £0 spent; no ML; no production/
live change. **Return to the roadmap gatekeeper.** Generic cross-sectional price/volume ranking is
`CLOSED FOR NOW` — do NOT launch another factor-mining task. Do NOT auto-start validation, more
factor discovery, ML, paid data, news/sentiment, options, strategy changes, live shadow, or PIV alpha.
