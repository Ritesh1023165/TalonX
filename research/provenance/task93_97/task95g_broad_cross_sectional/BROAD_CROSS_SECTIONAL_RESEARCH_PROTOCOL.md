# TASK 95G — BROAD CROSS-SECTIONAL RESEARCH PROTOCOL (FROZEN BEFORE OUTCOMES)

Frozen 2026-09-03, before any conditioned outcome table was inspected. Starts from
`results/task95e_cross_sectional_alpha/CROSS_SECTIONAL_RESEARCH_PROTOCOL.md` and **does not weaken
it**; it tightens the gates where the broader universe removes an excuse. This is a **replication**
of Task 95E's standalone families on a historically-correct ~500-name universe — **not** a new
factor hunt. `PAID_DATA_SPEND = £0` · long-only · no ML.

---

## 1. Universe & eligibility

- **Membership:** `fja05680/sp500` point-in-time daily list (independent, free; cross-checked 98.8%
  vs the Task 95F Wikipedia reconstruction). Tickers normalized to current tradable symbol.
- **Eligible on date `t`:** member on `t` **AND** ≥ 200 prior trading days **AND** `close(t) > 0`.
- Forward-return availability does not gate eligibility; a truncated `fwd_kd` is dropped from that
  horizon's mean (correctly terminating acquired/delisted names).

## 2. Ranking, buckets, horizons

- Rank eligible members each discovery date by the feature. **Top 10% / middle 80% / bottom 10%**
  (≈ 50 names/tail with ~500 eligible). All 10 deciles reported for monotonicity.
- Entry = `adj_close(t)`; exit = `adj_close(t+k)`, k ∈ {1, 3, 5, 10}. **Primary: 3, 5, 10.** k = 1
  diagnostic only.
- Rebalance: daily (primary) + k-day non-overlapping (control).
- Long-only: the bottom decile is a comparator only (gate G-sign / X11).

## 3. Metrics (per horizon k, in bps)

- `top_decile_excess` = mean over ranking dates of [ mean(top-decile `fwd_kd`) − equal-weight
  eligible-member `fwd_kd` ] — **PRIMARY** (market drift removed by construction).
- `top_minus_bottom` = D1 − D10 decile excess.
- `top_vs_median`, `top_vs_spy` — secondary.
- `net_c` = `top_decile_excess − turnover × 2c × (k/step)` for c ∈ {0, 2, **5**, 10, 20}. Net@5 is
  the decision number; net@20 is the mandatory stress.

## 4. Overlap / confidence

Both, mandatory (Task 95E's 35-name result lacked ideal symbol breadth):
1. **date-block bootstrap** — resample ranking dates in 10-day blocks, 2000 iters (seed `95_070_003`).
2. **symbol-block bootstrap** — resample the eligible symbols with replacement, 2000 iters —
   **the test Task 95E lacked**; it is what would have killed 95E's `rel_10d`.
3. **non-overlapping k-day rebalance** — independent forward windows.
A gate passes only if the symbol-block **and** date-block CI lower bounds are > 0 **and** the
non-overlap result is > 0 **and** `top_vs_spy` > 0.

## 5. Discovery pass gates (ALL; frozen; ≥ Task 95E strictness)

Primary horizon `k*` = best of {3, 5, 10} by turnover-adjusted `net@5`; the other two ≥ −8 bps.

| # | Gate |
|---|---|
| G1 | ≥ 300 ranking dates · avg eligible ≥ 100 · top bucket ≥ 20 names |
| G2 | `top_decile_excess` net@5 ≥ **+12 bps** at k* **AND** `top_minus_bottom` net@5 ≥ **+20 bps** |
| G3 | `top_decile_excess` net@10 > 0 at k* |
| G4 | symbol-block CI low > 0 **AND** date-block CI low > 0 **AND** non-overlap > 0 **AND** `top_vs_spy` > 0 |
| G5 | `top_decile_excess` > 0 in **≥ 4** discovery years |
| G6 | drop-2020 > 0 · drop-2022 > 0 · drop-2023 > 0 · remove-best-10-symbols > 0 |
| G7 | decile gradient reasonably monotone (D1 > … > D10, D1 = max); no single symbol > 25% and no top-3 > 45% of positive top-decile excess-R |
| G8 | deterministic re-run reproduces every headline |
| G-sign | realised `top_decile_excess` sign matches the hypothesised sign (long the top) |

Do **not** lower the bar because the universe is larger.

## 6. Families — exact replication of Task 95E (no new features)

- **A — relative momentum:** `rel_n` = own trailing n-day return − equal-weight member-universe
  trailing n-day return, n ∈ {1, 3, 5, 10, 20, 60}.
- **B — pullback within relative strength:** `pctrank(rel_20) − pctrank(rel_3)`, and the 20/5 version.
- **C — volatility-adjusted relative strength:** `ret_20 / rv_20`, `ret_60 / rv_60`
  (rv = trailing 20/60-day stdev of daily returns).
- **D — relative volume / attention:** `vol / vol_20d_avg`, `(vol_ratio_20)/(prior)`,
  `pctrank(rel_5) + pctrank(vol_ratio_20)`.

## 7. Early-stop

After A–D: if no family shows a reasonably monotone decile gradient **and** `top_minus_bottom` ≈ 0
(|·| < 15 bps) **and** no positive turnover-adjusted `top_decile_excess`, **STOP before composites**
and return `BROAD_CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED`. **No ML fallback.**

## 8. Composite (Phase 8) — only if ≥ 2 standalone families independently clear G2

Simple equal-weight rank sum, ≤ 2 pre-registered combinations, fixed weights, no optimiser, no ML.

## 9. Diagnostics also reported (not pass/fail)

By-year table; sector contribution (GICS from the current constituent table, best-effort);
**current-member vs removed-member** excess contribution (survivorship control); COMMON10/35 lens
("does the effect survive back on mega-caps?").

## 10. Verdicts

`DISCOVERY_PASS` / `DISCOVERY_FAIL` / `DISCOVERY_INCONCLUSIVE` (INCONCLUSIVE = fails only G1). A pass
freezes into `candidate_<ID>_spec.md`; no further optimisation; no validation/holdout inspection.
