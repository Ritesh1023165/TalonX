# Owner decision: `TASK75_RETIRED_AFTER_CORPORATE_ACTION_CORRECTION`

- **Candidate:** `CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1`
- **Fingerprints:** full `08930fb2…eff3`, contract-only `677adccd…6f06`
- **Decision date:** 2026-10-01
- **Supersedes:** the registered preflight label `TASK75B_BLOCKED_DATA_INTEGRITY` (`7ac94c0`)

## Decision

**V1 is RETIRED.**
- It is not validated, not replicated and not re-parameterised.
- No V2 of this strategy is created by this decision.

## Basis

**1. The survival gate failed on corrected development data.**
- The gate is `DEVELOPMENT_CORPORATE_ACTION_SURVIVAL_V1`, pre-registered at `697f377` before any adjusted outcome.
- On Alpaca SIP 1-minute `adjustment=all` data (`41f53eae…`), gates A, C and D fail:

  | Measure | Result |
  |---|---|
  | Gross | 0.2296% |
  | Net @10 bps | **0.1296% < 0.15%** |
  | Symbol-cluster CI lower bound | −0.0087 (2,000 resamples) and −0.0043 (10,000) |
  | Entry-day-cluster CI lower bound | −0.2913 (2,000 resamples) and −0.2928 (10,000) |

**2. The bound argument: failure does not depend on the unexplained trades.**
- In the registered run, 391 changed trades were unexplained, totalling −1.56 pp of gross.
- Crediting **all** of them back in the candidate's favour still gives net @10 bps ≈ 0.131% < 0.15%.
- Both cluster lower bounds remain negative.
- No resolution of those trades could produce a pass.

**3. The residue is now fully explained (A2, data fix only; survival not re-run, thresholds unchanged).** Two data fixes
were applied:
- **Ex-date audit:** Alpaca's corporate-actions API filters on process or payable date. V2 queries by process date and
  selects locally by ex-date, giving 86 events including 81 dividends. That adds 29 missed ex-dates, for example GOOGL
  2025-03-10 and QCOM 2025-12-04.
- **Cent-rounding tolerance** for back-adjusted prices: |fe/fx − 1| ≤ 0.005/entry + 0.005/exit.

| Category | Trades | Gross change (pp) |
|---|---|---|
| DIRECT_CORPORATE_ACTION | 97 | −380.52 |
| RANK_BOUNDARY_PROPAGATION | 11 | +3.17 |
| OTHER_EXPLAINED (uniform factor) | 276 | +0.01 |
| OTHER_EXPLAINED_CENT_ROUNDING | 377 | −0.07 |
| UNCHANGED | 250 | 0 |
| **UNEXPLAINED** | **0** | **0.00** |

- **Total change:** −377.41 pp (607.04 → 229.62).
- **What happened to the original 391:** 377 are cent rounding, 11 are direct corporate actions and 3 are rank
  propagation.
- **Integrity:** the data-integrity block is resolved. The only remaining failure is survival, which is the retirement
  condition.

**4. The edge came from four split-spanning short trades on the unadjusted RAW data:**

| Trade | RAW | ALL |
|---|---|---|
| KLAC 2026-06-09 | +88.2% | −17.9% |
| KLAC 2026-06-10 | +88.4% | −16.0% |
| NFLX 2025-11-12 | +90.5% | +4.6% |
| NFLX 2025-11-13 | +90.0% | +0.2% |

Without them, the development edge does not clear the pre-registered bar.

## Holdout

- **Never consumed.** VALIDATION (2024-06-01..09-02) and REPLICATION (2024-10-21..12-20) were never downloaded, loaded
  or evaluated for Task75.
- The two-layer guard (`research/task75b_preflight/holdout.py`) stays in state **PREFLIGHT**, with **both windows
  locked**, preserved for a future, separately pre-registered hypothesis.
- The researcher-exposure record for LARGE_GAP_REVERSION_V1 remains in `holdout_state.json`.
