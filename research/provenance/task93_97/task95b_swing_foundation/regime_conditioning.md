# TASK 95B — Phase 10 — Regime Conditioning

The single best-`excess_net_5bps` bin from each family (A `near_hi20`, B `uptrend_5dpull_q1`,
C `new_hi20`, D `5d_drawdown_q1`, E `gapdn_p10`) was re-run under seven deterministic, causally
observable regimes (labels from the Task 95A framework, computed on split-adjusted daily series and
shifted): `trend_bull` / `trend_bear` (vs 50-day SMA), `vol_high` / `vol_low` (`rv60` top/bottom
quintile), `mkt_bull` / `mkt_bear` (basket vs its 50-day SMA), `dd20` (> 20 % drawdown from high).
35 cells. Metric = net excess bps over the **global** discovery comparator (a regime-matched
comparator is applied in the deep-dive, `_deepdive.json`).

## What conditioning revealed

| Pattern | Evidence | Verdict |
|---|---|---|
| **Positive excess only in stress regimes** | Every cell with `excess_net_5bps > +10` is `vol_high`, `mkt_bear`, or `dd20` applied to the oversold/gap-down families: `D-5d_drawdown_q1 × vol_high` +45.6 · `D-5d_drawdown_q1 × mkt_bear` +22.6 · `E-gapdn_p10 × vol_high` +63.7 · `E-gapdn_p10 × mkt_bull` +26.6 · `E-gapdn_p10 × dd20` +15.3 · `A-near_hi20 × vol_high` +37.4 · `C-new_hi20 × mkt_bear` +45.6 | none survives — see below |
| **All of them fail S4 or S7** | non-overlap CI spans zero (`D×vol_high` [−10, +103], `D×mkt_bear` [−0.9, +71], `E×mkt_bull` [−5.6, ...], `C×mkt_bear` [−38, ...]) **or** best-year share > 0.45 (`A×vol_high` 0.54, `C×mkt_bear` 0.66, `D×dd20` 0.58) **or** both | `DISCOVERY_FAIL` |
| **The one that passed the automated check** (`E-gapdn_p10 × vol_high`) is a V-bottom artifact | 2022 (largest sub-sample, n=588) is **negative**; remove-best-year → negative; ~77 % of the raw return is the same-dates market move; negative on COMMON10; adjudicated FAIL (`gap_followthrough_analysis.md`) | `DISCOVERY_FAIL` (adjudicated) |
| **Momentum / breakout stay negative in every regime** | `A-near_hi20` and `C-new_hi20` are negative-excess in `trend_bull`, `trend_bear`, `vol_low`, `mkt_bull`; only marginally positive (and S4/S7-failing) in the thin `mkt_bear` / `vol_high` slices | `DISCOVERY_FAIL` |
| **`vol_low` regime is uniformly bad for swing longs here** | every family's `vol_low` cell is the most negative of its seven (`A×vol_low` −41 · `C×vol_low` −44 · `D×vol_low` −14 · `E×vol_low` −22) — the opposite of Task 95A's intraday finding | consistent, informative negative |

## Conclusion

Regime conditioning **did not** produce a candidate. Its clear message is that the only swing-horizon
long-only excess in this data lives in **market-stress episodes that were followed by sharp
recoveries** (2020 COVID bottom, 2023 bear bottom) — and that excess (a) is not statistically
separable from zero once overlapping 3–5-day returns are corrected, (b) is dominated by the
coincident broad-market rally, and (c) reverses in the one sustained bear (2022). A causally
observable regime label ("high realized vol", "market in drawdown") is not enough: the *forward
recovery* it needs is not itself predictable, so the regime-conditional edge does not carry to a
regime the discovery sample didn't happen to be followed by a rally in.
