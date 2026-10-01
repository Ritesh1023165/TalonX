# TASK 95G — BROAD-UNIVERSE CROSS-SECTIONAL REPLICATION — FINAL REPORT

Offline research. Frozen SHA `4b0e5dfa2415afe1dbf423c63c9cc479264106fa`. `PRODUCTION_STRATEGY_UNCHANGED`
· `NO_LIVE_SESSION_REQUIRED_FOR_TASK95G` · `NO_LOCAL_AI_REQUIRED` · **`PAID_DATA_SPEND = £0`** ·
validation/holdout untouched. Replication of Task 95E's standalone families A–D on a historically-
correct ~500-name S&P 500 — **not** a new factor hunt.

---

## 1. Verdict

# `BROAD_CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED`

13 experiments (exact replication of Task 95E Families A–D — 6 relative-momentum lookbacks, 2
pullback, 2 volatility-adjusted, 3 relative-volume) on the point-in-time S&P 500 discovery partition
(819 ranking dates, ~498 eligible members/date, 2020-10 → 2023-06). **0 `DISCOVERY_PASS`, 13
`DISCOVERY_FAIL`.** The early-stop gate fired; no composites were run.

## 2. Universe integrity

- **Identity verification** (`identity_verification_report.md`): the ~10 rows Task 95F flagged were
  resolved — 3 RESOLVED (ALXN/KSU/VAR: foreign-parent acquisitions, ticker terminates, no in-universe
  remap), 3 EXCLUDED_WITH_REASON (AXE legacy/incorrect, MXPS placeholder, CTRA_OLD_COG malformed).
  No unresolved row blocked the task. Deterministic, no fuzzy/AI matching.
- **Membership cross-check** (`membership_crosscheck_report.md`): the Task 95F Wikipedia
  reconstruction vs the independent free `fja05680/sp500` — raw ticker Jaccard 0.955 (dominated by
  rename vintage), **company-level Jaccard 0.988** after rename normalization; residual < 1.5%
  (backward-walk missing-ADD artifacts + ±1–3-day effective-date offsets). **NOT
  `TASK95G_BLOCKED_UNIVERSE_INTEGRITY`.** `fja05680` adopted as the primary membership (removes the
  larger error source).

## 3. Dataset

`task95g_sp500_daily_v1` (`broad_daily_dataset_manifest.json`, fp `08aa253ad4df1121`): **620 unique
historical symbols, 619 with data, 1,059,207 daily rows**, 2019-06 → 2026-08, Alpaca SIP
`adjustment=all`. Quality (`broad_daily_data_quality.md`): 0 dup / 0 impossible-OHLC / 0 nonpos-close;
49 split-artifact cells masked; removed names terminate on the corporate-action date (no zombie bars).

## 4. Survivorship status

`SURVIVORSHIP_CONTROL` strong and **confirmed by decomposition** (`survivorship_control.md`): for
every momentum feature the reversal is **~2× stronger among later-removed constituents**
(rel_3d: current −20.7 bps, removed −49.1). The bias direction in Task 95E's survivor-only 35-name
set was to *hide* a negative effect — removing survivorship bias made the signal **more** negative.

## 5. Cross-sectional dispersion

Mean daily cross-sectional SD of `fwd_kd`: **188 / 402 / 628 / 1011 bps** at 1/3/5/10d. Any effect
found (≤ ±26 bps) is < 0.06 SD.

## 6. Relative-momentum replication (`momentum_replication.md`)

**Relative strength is a significantly NEGATIVE (reversal) predictor on the honest universe.**
`rel_3d` top-decile excess **−26.3 bps** at k3 (net@5 −42.1), symbol-block CI **[−32.6, −20.5]**,
0/4 years positive, and a **monotone reversal decile gradient** (D1 −26.3 → D10 +26.7,
`top_minus_bottom` −53). Every lookback 1d–60d is negative. **All 6 FAIL.**

## 7. Pullback replication (`pullback_replication.md`)

The only non-negative-signed family: top-decile excess +2 to +4 bps, `top_minus_bottom` +17. But
net@5 negative after turnover (0.40/day), symbol-block CI **[−0.2, +8.1]** ≈ 0, net@10/20 firmly
negative, 2/4 years, **non-monotone** (the bump is in D2, not D1). **Both FAIL.**

## 8. Volatility-adjusted replication (`vol_adjusted_replication.md`)

Same momentum signal rescaled — significantly negative, monotone reversal, 0/4 years. **Both FAIL.**

## 9. Relative-volume replication (`relative_volume_replication.md`)

Flat decile gradient (no rank information), turnover 0.69–0.96/day. **All 3 FAIL.**

## 10. Composite result

**None run.** Protocol §7 early-stop fired: no family shows a monotone long-direction gradient,
`top_minus_bottom` is negative or ≈ 0 or below the +20 bar, and no family has a positive
turnover-adjusted `top_decile_excess`. Per the protocol, no ML fallback and no new factors.

## 11. Decile monotonicity (`decile_monotonicity.md`)

Momentum & vol-adjusted: **monotone in the reversal direction** (D1 worst) — a credible ranking
relationship, wrong sign for a long strategy. Pullback: non-monotone (D2 bump). Relative volume:
flat. **No family shows the long-direction monotone gradient gate G7 requires.** Task 95E's `rel_10d`
"monotonicity" (a D1-only spike with random interior deciles) fails this test outright.

## 12. Top-decile excess

Best pooled `top_decile_excess` in the entire task is **+3.8 bps** (`B-pull_20_5`, k3), which is
< 0.01 SD, straddles zero, and is negative after cost. Every momentum/vol-adjusted cell is between
−16 and −26 bps.

## 13. Top-minus-bottom spread

Negative for Families A and C (−29 to −53 — the top decile *underperforms* the bottom). ≈ 0 for
Family D. +17 for Family B (< the +20 gate). No spread is both ≥ +20 and long-viable.

## 14. Turnover / costs (`turnover_cost_analysis.md`)

Not the binding issue — **10 of 13 experiments are negative-gross before any cost**. `net@20` is
negative for **every** experiment. Non-overlapping 5-day rebalance: still negative for every family.

## 15. Date-block confidence

`statistical_confidence.md`: **no experiment has a positive lower bound** on either the date-block or
the symbol-block bootstrap. Momentum/vol-adjusted are **significantly negative**; pullback and
relative-volume are indistinguishable from zero.

## 16. Symbol robustness

Best single symbol ≤ 1.5% of the (negative) top-decile excess-R; top-3 ≤ 4.3% (vs Task 95E's TSLA at
12–25%). The broad-universe negative is **diffuse** — removing any few names does not change it.

## 17. Year robustness (`year_robustness.md`)

Momentum/vol-adjusted negative in **all four** discovery years (2020 worst). Pullback and
relative-volume alternate sign year to year. No family clears gate G5 (≥ 4 positive years).

## 18. Sector robustness (`sector_robustness.md`)

No sector-concentration rescue and no sector-concentration artifact. The top decile in the broad
universe is sector-diversified and rotating — it is not a persistent tech bet like Task 95E's
7-name bucket. The negative is diffuse across sectors.

## 19. Removed-constituent robustness (`survivorship_control.md`)

The reversal is **stronger** among later-removed constituents (~2×). No family shows a signal that
exists only in survivors.

## 20. Direct Task 95E comparison — did breadth change the conclusion?

**No — it strengthened the negative.**

| | Task 95E (35 survivor names) | Task 95G (500 point-in-time names) |
|---|---|---|
| best standalone cell | `rel_10d` +27.9 bps top-excess k5, 4/4 years, "DISCOVERY_PASS" pre-adjudication | `rel_10d` **−18.4 bps** k5, 1/4 years, symbol-CI **[−25.3, −12.7]** |
| momentum sign | positive (concentrated), later adjudicated a TSLA/NVDA/AMD 2020/2023 artifact | **significantly negative** (reversal), monotone decile gradient, diffuse |
| symbol-block bootstrap | not run (the missing test) | run — kills every cell; the significant CIs are all negative |
| verdict | `CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED` | `BROAD_CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED` |

Task 95E's single near-miss **does not replicate — it inverts.** The broad, survivorship-controlled
universe reveals that short-horizon cross-sectional relative strength is a *negative* long-only
predictor, and that Task 95E's positive was a small-universe concentration + survivorship artifact,
exactly as Task 95E's own adjudication suspected.

## 21. Cost status

**`PAID_DATA_SPEND = £0`.** Membership from `fja05680/sp500` (free GitHub) + Task 95F artifacts;
prices from the existing Alpaca SIP entitlement (GET only). No purchase, no trial, no premium endpoint.

## 22. Production status

`PRODUCTION_STRATEGY_UNCHANGED`. No change to strategy, indicators, decision engine, risk, execution,
or dispatch. All work in `results/task95g_broad_cross_sectional/` + scratchpad. Tree clean at `4b0e5df`.

## 23. Live status

`NO_LIVE_SESSION_REQUIRED_FOR_TASK95G`. No Gateway / Original / PIV / PAPER / shadow.

## 24. AI status

`NO_LOCAL_AI_REQUIRED`. No XGBoost, random forest, neural net, AutoML, LLM, embeddings, or model
training. Deterministic ranks only. Per the ML rule: simple ranks across 500 stocks contain **no
positive** cross-sectional information, so complexity would add overfitting risk, not information —
none was built.

---

## Conclusion for the roadmap gatekeeper

**Generic cross-sectional price/volume ranking is `CLOSED FOR NOW`.** Three progressively stronger
tests — Task 95E (35 names), the Task 95F feasibility work, and Task 95G (500 historically-correct
names with survivorship control and the symbol-block bootstrap) — all conclude that simple
price/volume features carry no cost-survivable long-only cross-sectional edge at 3–10 days; on the
honest universe the momentum family is *significantly negative*. Do **not** launch another
factor-mining task. The remaining roadmap decision is between **fundamentally different information
sources** (paid point-in-time consensus, news/sentiment, options) or a **product-direction change**
(decision-support rather than autonomous alpha) — not another variation of this hypothesis space.

## Final action

**STOP.** Not auto-starting independent validation, more factor discovery, ML, local AI, paid data,
news/sentiment, options, strategy changes, live shadow, or PIV alpha. Findings returned to the
roadmap gatekeeper.

### Artifacts (`results/task95g_broad_cross_sectional/`)
`TASK95G_CHECKPOINT.md` · `identity_verification_report.md` · `membership_crosscheck_report.md` ·
`broad_daily_dataset_manifest.json` · `broad_daily_data_quality.md` (+ `.json`) ·
`cross_sectional_panel_manifest.json` · `cross_sectional_partitions.json` · `partition_rationale.md` ·
`BROAD_CROSS_SECTIONAL_RESEARCH_PROTOCOL.md` · `EXPERIMENT_LEDGER.csv` · `momentum_replication.md` ·
`pullback_replication.md` · `vol_adjusted_replication.md` · `relative_volume_replication.md` ·
`turnover_cost_analysis.md` · `statistical_confidence.md` · `year_robustness.md` ·
`sector_robustness.md` · `survivorship_control.md` · `decile_monotonicity.md` · `candidate_ranking.csv` ·
`rejected_hypotheses.md` · `FINAL_REPORT.md` · supporting `_*.json` / `_*.csv` + `_daily/` (619 CSVs)
