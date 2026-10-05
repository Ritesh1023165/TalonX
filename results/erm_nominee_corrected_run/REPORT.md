# ERM nominee GAP_UP_10|SHORT|H10|L1: corrected development run (spec V2.1)

## Verdict: CORRECTED_DEVELOPMENT_SCREEN_PASS

This result **supports further research only**. It is not validated profitability, and it does not validate the map.

Still pending:
- window selection;
- Task75 reserve consumption;
- the final validation protocol.

**Scope:** one development-only run, 2019–2023. No other cell was scored and nothing was re-nominated. Neighbour support was **not** rechecked.

**Metric:** mean directional, sector-relative **adjusted-return research proxy** (ALL-adjusted ratio). It is **not executable short P&L**. Borrow, locate, financing and the ETF-leg cost are not modelled by the frozen screen.

**Run:** 2026-10-05 14:10:16Z → 14:18:38Z, at frozen commit `aab578e`, scoring worktree `C:\workspace\TalonX-erm-score`.
- Freeze record sha256: `8581e3d3…31f5`.
- Rules sha256: `a4e3b82d…48ef`.
- Builder sha256: `bed3c5bd…bf9a`.
- Scorer sha256: `c27bf682…bdc`.
- Offline guard active; maximum bar date read: 2023-12-29.
- Guard state `b512322d…30b5`, unchanged.

## Prerequisite checks

| Check | Result |
|---|---|
| Original-rule parity | All 25 Gate D metric keys reproduced **exactly** (json-identical, including per-year, top-k, CI and missing-exit bounds); screen identical (`parity_original_cell.json`) |
| Corrected manifest | Rebuilt from archives in no-fetch mode: sha256 `9ed45652…579d` = frozen; 2,752 rows; 1,999 valid + 2 missing exits; 0 bar-presence failures |

## Original vs corrected

- **Original** = uncorrected discovery evidence (Gate D).
- **Corrected** = the narrower V2.1 evidence-covered population.

| Metric | Original | Corrected |
|---|---|---|
| n (valid) / distinct dates / symbols | 2,695 / 898 / 1,370 | 1,999 / 806 / 1,047 |
| Missing exits (rate) | 8 (0.30 %) | 2 (0.10 %) |
| Mean sector-relative gross | +2.852 % | **+1.963 %** |
| Median sector-relative | +2.085 % | +1.496 % |
| Net of 30 bps (frozen L1 cost) | +2.552 % | +1.663 % |
| Date-clustered 95 % CI | [+1.421 %, +4.230 %] | **[+0.576 %, +3.324 %]** |
| Hit rate | 58.4 % | 56.4 % |
| SD | 22.1 % | 20.6 % |
| Mean without top 1 / 3 / 5 | +2.818 / +2.756 / +2.697 % | +1.918 / +1.838 / +1.767 % |
| Mean raw / vs SPY (directional) | +1.539 % / +2.903 % | +0.803 % / +2.114 % |
| Suspect-adjustment events (excluded sensitivity) | 24 (+2.849 %) | 15 (+1.825 %) |
| Per year (entry year): mean / n | 2019 +0.41 % / 276; 2020 +2.08 % / 973; 2021 +4.47 % / 684; 2022 +1.83 % / 402; 2023 +4.89 % / 360 | 2019 +0.10 % / 240; 2020 +2.10 % / 720; 2021 +3.18 % / 455; 2022 +0.82 % / 300; 2023 +2.47 % / 284 |

## Frozen screen (`metrics.screen`, source-verified): corrected

| Criterion | Value | Result |
|---|---|---|
| n ≥ 300 | 1,999 | PASS |
| distinct dates ≥ 150 | 806 | PASS |
| mean in the cell's direction ≥ 2 × 30 bps | +1.963 % ≥ 0.60 % | PASS |
| date-cluster 95 % CI excludes 0 on the side of the mean | [+0.576 %, +3.324 %] | PASS |
| yearly sign = overall sign in ≥ 4 of 5 years (n ≥ 20 each) | 5 of 5; 2019 only +0.10 % | PASS |
| removing the top 5 keeps the sign | +1.767 % | PASS |
| missing-exit rate ≤ 2 % | 0.10 % | PASS |

## Survivorship diagnostic under corrected eligibility

- **EXCLUSION_DEPENDENT = False.**
- No V2.1 row was excluded **solely** by R1A_NOT_AVAILABLE: the 3 R1a-flagged rows all carry other exclusion flags. So 0 rows were added and **the diagnostic is vacuous** for this population.
- Unresolved rows were never added or scored.

## Descriptive subset NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND (never gating)

- n = 1,459 (681 dates).
- Mean sector-relative +1.486 %; net +1.186 %.
- CI [+0.048 %, +2.848 %]; hit rate 55.7 %.
- Caveat: ETF evidence covers cash dividends only, and other ETF actions are unverified.

## Limitations

- Evidence-covered population: 625 unresolved rows are excluded, mostly Section-16-exempt foreign private issuers.
- Neighbour support was not rechecked.
- The metric is an adjusted-return proxy.
- The 30 bps cost is a frozen research assumption.
- Borrow and locate are not modelled.
- The validation-draft ETF-leg cost (4 bps) and minimum-sample rules were **not** applied; they belong to the pending pre-registration.
