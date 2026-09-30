# Task75B corporate-action preflight: result

## Classification

**Registered classification: `TASK75B_BLOCKED_DATA_INTEGRITY`.**
- The pre-registered `classify()` order checks integrity before survival.
- 391 changed trades are UNEXPLAINED under the registered tolerances.

**Substantive finding: the survival gate fails** (A, C and D). The failure is decisive and does not depend on the
unexplained residue.

**Candidate status:**
- The candidate should be treated as `TASK75_RETIRED_AFTER_CORPORATE_ACTION_CORRECTION` in substance.
- **The validation holdout is not consumed.** The guard state stays PREFLIGHT, with validation and replication locked.

## Commits

| Step | Commit |
|---|---|
| Base | `16d2b2a` (frozen Task75A) |
| Guards and parity | `a166d83` |
| **Declaration and registration** | `697f377`, 2026-09-30T22:32:02Z, before any ALL outcome |
| Dataset and evaluator | `0cb57b7` |
| Result | this commit |

## Gates in order

**1. Fingerprints:** MATCH.
- Full: `08930fb2…eff3`
- Contract-only: `677adccd…6f06`

**2. RAW parity: PASS (bit-exact).**
- All 4 archived dataset hashes match.
- 1,000 trades; gross 0.6070373392207478%.
- Anchor CIs reproduced exactly with the ORIGINAL call (`cell_summary`, **2,000** resamples, seed 670067):

  | Cluster | CI |
  |---|---|
  | Symbol | [0.068478, 1.270970] |
  | Decision day | [0.034016, 1.201483] |

- The task specified 10,000 resamples, but the anchor used 2,000. The registration required both calls to pass.

**3. Development corporate-action audit** (Alpaca `/v1/corporate-actions`, 36 symbols, **4** authoritative slices):
- 66 events: 61 cash dividends (2 on SPY), 2 forward splits (NFLX 10:1 on 2025-11-17, KLAC 10:1 on 2026-06-12), 1
  reverse-split record and 2 spin-offs (HON on 2026-06-29, plus one in 2025-10).
- **Audit limitation, found after the run:** the API range appears to filter on record or payable dates. Some in-window
  ex-dates were missed (for example GOOGL ex-dividend 2025-03-10 and QCOM ex-dividend 2025-12-04), and 9 returned events
  carry ex-dates outside their window.

**4. Provider semantics: PROVEN** on out-of-window events (KLAC and ORLY splits, SPY dividend).

| Adjustment | Behaviour |
|---|---|
| RAW | keeps split jumps: post/pre 0.106 (KLAC) and 0.068 (ORLY) |
| SPLIT | removes split jumps; leaves dividends |
| ALL | split-adjusted plus a dividend factor step equal to $1.9035 (SPY); download-date dependent |

**5. Dataset `TASK75_DATASET_ALL_V1`:** Alpaca SIP, 1Min, adjustment=all, 35 symbols + SPY with identical parameters.
- 4 development slices: 3,110,463 rows.
- 0 duplicates, 0 rejected, 0 empty files, no synthetic bars.
- Aggregate sha256 `41f53eae82bc003a68bdd698e58d1cff3f83bcbcf917f8fff76173b8c7248d18`. The archived bytes are
  authoritative.
- Session coverage equals RAW. Validation and replication were **never requested**.

## Corrected development (frozen `evaluate()`, one run)

| Metric | RAW (anchor) | **ALL (corrected)** |
|---|---|---|
| Trades | 1,000 | 1,000 |
| Gross mean | 0.6070% | **0.2296%** |
| Net @10 bps | 0.5070% | **0.1296%** |
| Net @25 bps | 0.3570% | **−0.0204%** |
| Symbol-cluster CI (2,000 resamples) | [0.068, 1.271] | **[−0.0087, 0.4706]** |
| Symbol-cluster CI (10,000 resamples) | [0.092, 1.282] | **[−0.0043, 0.4743]** |
| Day-cluster CI (2,000 resamples) | [0.034, 1.201] | **[−0.2913, 0.7266]** |
| Entry-day-cluster CI (10,000 resamples) | [0.030, 1.205] | **[−0.2928, 0.7459]** |

**Survival gates:**

| Gate | Result |
|---|---|
| A: net @10 bps ≥ 0.15 | FAIL (0.1296) |
| B: gross > 0 | PASS |
| C: symbol-cluster lower bound > 0 | FAIL |
| D: entry-day-cluster lower bound > 0 | FAIL |
| E, F: same implementation and parameters | PASS |
| G: unexplained = 0 | FAIL (391) |

## RAW vs ALL trade diff

**Status counts:** 250 unchanged, 739 price or P&L changed, 11 newly selected, 11 no longer selected.

| Category | Trades | Gross change (pp) |
|---|---|---|
| DIRECT_CORPORATE_ACTION | 75 | **−382.65** |
| RANK_BOUNDARY_PROPAGATION | 10 | +6.78 |
| OTHER_EXPLAINED (uniform back-adjustment) | 285 | +0.01 |
| BENCHMARK_MEDIATED | 0 | — |
| **UNEXPLAINED** | **391** | **−1.56** |
| Total | 1,011 | −377.41 (607.04 → 229.62) |

**The edge came from four split artefacts in RAW.** Each short spanned an unadjusted 10:1 split:

| Trade | RAW gross | ALL gross |
|---|---|---|
| KLAC 2026-06-09 | +88.2% | −17.9% |
| KLAC 2026-06-10 | +88.4% | −16.0% |
| NFLX 2025-11-12 | +90.5% | +4.6% |
| NFLX 2025-11-13 | +90.0% | +0.2% |

**The unexplained residue is small and mechanical, not an integrity failure of the price data:**
- The median |Δ| is 0.0025 pp, and 99% are below 0.12 pp.
- It comes from dividend ex-dates the audit missed (the query-date semantics above) and from cent rounding of heavily
  back-adjusted ALL prices (for example BKNG's later 25:1 split, factor 0.0396, and CMCSA's later spin-off).
- Its total is −1.56 pp. **Under any resolution it cannot rescue survival:** crediting all of it back gives net
  @10 bps ≈ 0.131% < 0.15%, and both cluster lower bounds stay negative.

## Holdout status

| Item | Status |
|---|---|
| VALIDATION_DATA_PRESENT | NO |
| REPLICATION_DATA_PRESENT | NO |
| VALIDATION_OUTCOMES_READ | NO |
| REPLICATION_OUTCOMES_READ | NO |
| Guard state | PREFLIGHT (no transition made) |

The researcher-exposure record (LARGE_GAP_REVERSION_V1) is in `holdout_state.json`.

**Live application:** untouched. No process, database, Telegram, DTU, CONTROL, SQF, VR paper, V2 or Sentinel change.
