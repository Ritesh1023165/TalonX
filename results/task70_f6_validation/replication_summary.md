# F6_FADE_V1 — REPLICATION Summary

**Classification: REPLICATION_FAIL**

Ran exactly once (VALIDATION_PASS was a precondition, satisfied — see
`validation_summary.md`), against the separately locked REPLICATION window,
completely unmodified strategy, per `holdout_selection_lock.json`.

Period: **2024-09-03 → 2024-10-18**. Universe: canonical 35 symbols, no
substitutions. Dataset hash `c79eea280e19`. Strategy fingerprint
reconfirmed `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084`
immediately before this run.

## Headline numbers

| Metric | Value |
|---|---|
| Candidates evaluated | 1,190 |
| Trades | 182 |
| Long / Short | 119 / 63 |
| Symbols with a trade | 33 |
| Trading days with a trade | 34 |
| Gross expectancy | **−0.124%** |
| Net expectancy @10bps | **−0.224%** |
| Profit factor @10bps | **0.56** |
| Win rate | 41.8% |
| Median trade (net) | −0.223% |
| Max drawdown (cum. net_return) | −51.5 pts |

This sample is far broader than VALIDATION's (182 vs 43 trades, 33 vs 20
symbols, 34 vs 10 days) — a genuinely more statistically powerful test, not
a thin one.

## Cost sensitivity

| Cost | Expectancy | Total return | Profit factor |
|---|---|---|---|
| 0bps | −0.124% | −22.51% | 0.73 |
| 5bps | −0.174% | −31.61% | 0.64 |
| 10bps | −0.224% | −40.71% | 0.56 |

Negative at **every** cost level, including zero cost. This is not a
"costs erased a thin edge" story — there is no gross edge here to erase.

## Bootstrap (95% CI, clustered by symbol, n_groups=33)

point_estimate=−0.224%, **ci_low=−0.319%, ci_high=−0.123%** — the entire
95% CI is negative; it does not merely fail to exclude zero, it excludes
zero on the negative side. This is a statistically confident negative
result, not sampling noise.

## Concentration / outlier sensitivity

top1_symbol=16.2%, top1_day=20.4% (both well under the 40% flag — this is
NOT a concentrated result; the negative edge is broad-based). Removing the
best 3 trades makes expectancy **more** negative (−0.273%) — the losses are
not confined to a few bad days either; there is no rescue available by
excluding outliers in either direction.

## Long vs. short

Long expectancy −0.347% (119 trades); short expectancy ≈ 0.000% (63
trades, essentially flat). Neither side shows the fade edge validation and
development pointed to — if anything the long side (fading an up-open) is
where the loss concentrates.

## Integrity diagnostics

- Causal violations: **0**.
- Decision→entry delay: 60s median (occasionally up to 180s on sparser
  data-gap days — still strictly causal, no lookahead).
- Holding duration: 3,540–3,600s, 100% `FIXED_60M_EXIT` (no session-close
  caps triggered in this window).
- Rejection breakdown: `DATA_NOT_READY`=39, `OPENING_MOVE_BELOW_THRESHOLD`=969
  — clean funnel, no unexplained rejection category.
- Data quality: 35/35 FULL, zero duplicate/out-of-order/NaN/Inf/invalid-OHLC/
  negative-volume/future-timestamp rows (see `replication_data_quality.json`).

**No integrity or data problem explains this result.** It is a genuine,
broad-based, statistically confident negative outcome on a locked,
previously-untouched historical window.

## Assessment

Per the task's own framing (no demand for identical performance, but
looking for positive net edge, same qualitative fade behavior, breadth,
robustness, no integrity problems): **none of these hold**. The edge is
negative both gross and net, in the OPPOSITE direction from what discovery
and validation suggested, on a sample with better breadth than validation
itself, with a bootstrap CI that confidently excludes zero on the negative
side, and with no concentration or integrity issue to explain it away.

This is not treated as noise, and no attempt is made to rescue it by
reweighting criteria, cherry-picking a sub-window, or blaming data quality
— none of which are supported by the evidence above. **REPLICATION_FAIL.**
