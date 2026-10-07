# INSIDER_BUY_CLUSTER_V2@1: reconciling "+1.01% paper candidate" with "UNSUPPORTED" (2026-10-07)

This note is a read-only reconciliation of reports that already exist and are already unblinded. Nothing was
recomputed. The blinded V2 forward tracker outputs (`results/v2_validation/forward/*.json`) were **not** opened. The
2026-10-07 accidental exposure, recorded in `2026-10-07_v2_form4_coverage_audit/REPORT.md` §5, is noted here and those
values are not reused.

## Conclusion

**Today the evidence supports `UNSUPPORTED`: no demonstrated positive edge for V2@1 *as implemented*.** This is not
proof of a negative true effect.

- The implemented population's development-period mean is **close to zero** (net −0.15%, PF 0.97, n = 4,009).
- The one positive out-of-sample quarter is outlier-driven.
- The **S&P 500 in-panel subset** is positive in the development data, but the holdout does not confirm it beyond
  market beta.

The two headline numbers answer **different questions on different populations**, so neither report contradicts the
other's arithmetic.

## The two verdicts side by side

| | Earlier: paper-candidate (`+1.01%`) | Later: `UNSUPPORTED` (2026-09-30) |
|---|---|---|
| Strategy / fingerprint | `INSIDER_BUY_CLUSTER_V2`; Task 109 freeze `3103d89` (fingerprint `11107198c5b81237`; RI-1 re-fingerprinted `e2acf6454789217e` with strategy fields byte-identical) | Same `V2@1`, `e2acf6454789217e` |
| Reports | Task 107B `results/task107b_form4_cluster/final_report.md` (verdict `TASK107B_FORM4_PAPER_CANDIDATE`); Task 112R `results/task112r_release_rehearsal/backtest_reproducibility.md` §G2b | `docs/research/evidence/2026-09-30_v2_insider_cluster_validation.md` (checkpoints 1 and 2) |
| Hypothesis | ≥2 distinct insiders, code P, within 10 trading days → positive long return at +10 sessions | Same rule, evaluated **as frozen and implemented in the runtime** |
| Population | **P2 IN-PANEL**: episodes in the Task 95g survivorship-correct **S&P 500 panel**. Frozen code n = 810; runtime detector **n = 756** | **The runtime's eligibility**: S&P 500 ∪ 400 membership **or** liquidity (median $vol ≥ $5M, close ≥ $5). The runtime wires only the liquidity branch, so the population is mostly liquid non-S&P names. 4,009 evaluated discovery episodes |
| Dates | Entries 2019-06 .. 2026-03 (chronological discovery/holdout split inside, at 2023-07-01) | Discovery 2019-01 .. 2026-04. Holdout 2026Q2 (unseen by the freeze). Checkpoint 2 adds 2026-07..09 and the first prospective (post-freeze) events |
| Return / cost / benchmark | Open of the next session → close at +10; 20 bps round trip; raw net (SPY-excess reported in 107B: P2 +0.92%, P1 ≈ 0) | Same entry/exit/20 bps; also reports vs SPY and an unconditional same-symbol baseline |
| Acceptance criteria | 9 (112R) / 10 (107B) frozen gates: net > 0 overall, discovery and holdout; PF > 1; concentration drops; N ≥ 300; issuer-block CI lower bound > 0 | Validation protocol: positive net in unseen data that survives concentration and benchmark checks |
| Headline | **+1.01% net / 10 td**, PF 1.34, CIs > 0 (runtime detector on P2). 107B's *pre-registered primary* P1 BROAD: +0.60% net, SPY-excess ≈ 0 | Discovery **−0.148% net**, PF 0.967, −0.38% vs SPY. 2026Q2 holdout +2.75% net (n = 145), with MNTS = 37% of net points and the S&P subset −0.48% vs SPY. Checkpoint 2: Q3 2026 net −2.47% (n = 99); all unseen +0.63% net but **−0.08% vs SPY**, and −0.23% without the best 3 |
| Status | **Development-period** evidence (a paper candidate, explicitly not a profit claim). P2 was the robustness anchor, not the pre-registered primary population | **Validation** of the implemented population, with an unseen holdout plus checkpoint 2 |

## Why the summaries differed

1. **Different population.** The +1.01% is the S&P 500 in-panel subset. The 2026-09-30 report reproduces that subset
   in its own pipeline: discovery S&P 500 names gave n = 788, net +0.88%, +0.74% vs SPY. Liquid non-S&P names, which
   the runtime also admits, gave n = 3,221 and **−0.40%**. "The liquidity gate is not the validated domain."
2. **Benchmark.** The +1.01% is raw. Against SPY, the unseen periods are flat (−0.08%) and the 2026Q2 S&P subset is
   −0.48%.
3. **Out of sample.** 112R's "holdout" (≥ 2023-07) is a split inside data the rule was developed on. The 2026-09-30
   report adds truly unseen 2026Q2–Q3 data.

## Does the later report supersede?

- **For the live V2@1 strategy as implemented: yes.** `UNSUPPORTED` is the current verdict, and the operator
  expectancy "+1.0%/10 td" from Task 112R should not be presented as the expected return of the running strategy.
- **The S&P-500-panel historical finding is not refuted.** It remains a development-period, post-hoc-population result
  whose out-of-sample beta-adjusted confirmation is missing.

## Scopes kept separate

- **Live RC1** runs the deliberately configured **39-issuer** scope (`2026-10-07_v2_form4_coverage_audit`).
  - The 2026-09-30 report's in-scope subset is n = 63, which is too small to evaluate.
  - Population governance is open as OPS-006 / `UNIVERSE_CONTRACT_DECISION_REQUIRED`.
  - Nothing here changes the campaign.
- **The 626-name research universe** (57 unresolved identities) is a research population and is not live.
- **The blinded forward tracker** (until 2026-10-31) is separate. This note does not use or anticipate its outcomes.
