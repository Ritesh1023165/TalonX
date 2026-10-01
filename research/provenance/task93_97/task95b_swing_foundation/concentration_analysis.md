# TASK 95B — Phase 13 — Breadth / Concentration / Outlier Robustness

For every bin the ledger records: event count, symbols, years, months, best-symbol share of
positive excess-R, best-year share, best-month share, top-3-event share, and the net-excess-@5-bps
after removing (independently) the best event, best 3, best 5, best symbol, best month, best year.
`SWING_RESEARCH_PROTOCOL.md` S6 (all removals keep excess > 0) and S7 (best symbol ≤ 35 %, best
month ≤ 25 %, best year ≤ 45 % of positive excess-R).

## Families A / B / C

Not applicable in the "does the edge survive?" sense — these bins have **no positive excess to
concentrate** (momentum and breakout are negative-excess; pullback is +4 to +14 bps, below the bar).
Where marginally positive (`A-mom_60d_q1` +20.8), S7 already fails (concentration flag in the
ledger).

## Family D / E — the effects that had positive excess

| Bin | best-sym share | best-year share | best-month share | top-3 events | remove best-3 (net@5) | remove best year (net@5) | remove best sym | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `D-deepdd_fresh3ddrop` (k=3, vs global) | 0.11 | **0.52 (2020)** | 0.17 | 0.019 | +20.5 | +98.5* | +28.9 | **S7 fail** — 2020 crash-recovery = half the positive excess-R |
| `D-dd20_rsi35` (k=5, vs global) | 0.06 | **0.64** | 0.12 | 0.017 | +27.8 | +57.2* | +45.2 | **S7 fail** + S4 |
| `E-gapdn_p10 × vol_high` (k=3, vs global) | 0.14 | 0.45 | 0.15 | 0.027 | +56.3 | **+22.4** | +74.0 | passes S6/S7 vs **global** … |
| `E-gapdn_p10 × vol_high` (k=3, **vs vol_high baseline**) | 0.14 | 0.45 | 0.15 | 0.027 | +27.6 | **−6.3** | +45.3 | **S6 fail** — remove best year → **negative** |
| `E-gapdn_p10 × vol_high` (k=5, vs vol_high baseline) | 0.14 | 0.47 | 0.17 | 0.030 | +36.4 | **−28.9** | +65.2 | **S6 fail** |

\* the "remove best year" figure is *higher* than the base for the D bins because the removed year
(2020) is also a very-high-count year whose events drag the mean down on net; the S7 flag (52–64 % of
*positive* excess-R from one year) is the binding concentration failure regardless.

## Event-level concentration is fine; period-level is not

- **No single event or symbol dominates.** top-3-event share ≤ 3 % everywhere; best-symbol share
  ≤ 14 % on the D/E bins. The effects are not one lucky trade or one lucky ticker.
- **A single year dominates.** For every bin with positive excess, **45–64 % of the positive
  excess-R comes from one calendar year — 2020 (COVID bottom) or, for the vol_high cell, split
  2020 + 2023 with 2022 negative.** Removing that year (S6 / Phase-13 explicit test) either
  collapses the effect to ≈ 0 (D bins vs matched comparator) or turns it **negative**
  (`E-gapdn_p10 × vol_high` vs the correct regime-matched comparator).

## Conclusion

The one candidate that survived the automated S1–S10 gates does **not** survive Phase 13 against the
correct comparator: **remove the best year and the excess goes negative.** Per the protocol
("If edge collapses: FAIL") and the task's Phase 13 instruction, this is a hard failure. Every other
positive-excess bin fails S7 (one year = > 45 % of positive excess-R). No candidate is outlier-robust.
