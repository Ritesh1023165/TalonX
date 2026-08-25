# F6_FADE_V1 — Profitability Evidence Synthesis (Development vs Validation vs Replication)

| Role | Period | Trades | Symbols | Days | Gross exp. | Net exp. @10bps | PF @10bps | Bootstrap CI (95%, by symbol) | Max DD | Top-3-winners-removed | Long exp. | Short exp. | Classification |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEVELOPMENT | 2026-05-15..08-14 | 735 | 35 | 63 | +0.060% | **−0.040%** | 0.93 | n/a (not re-tested) | −1.397 | −0.064% | −0.199% | +0.112% | N/A (discovery period) |
| VALIDATION | 2024-02-01..03-15 | 43 | 20 | 10 | +0.438% | **+0.338%** | 2.05 | [−0.071%, +0.694%] | −0.035 | +0.193% | +0.460% | −0.063% | VALIDATION_PASS |
| REPLICATION | 2024-09-03..10-18 | 182 | 33 | 34 | **−0.124%** | **−0.224%** | 0.56 | [−0.319%, −0.123%] | −0.515 | −0.273% | −0.347% | +0.0001% | **REPLICATION_FAIL** |

*(Development figures reproduced by re-running the same frozen, unmodified
evaluator against the DEVELOPMENT dataset in the identical metric
convention as validation/replication — for comparability only; development
is not a holdout and this is not a new test of anything, see
`development_reproduced_metrics.json`.)*

## Does validation improve or worsen relative to development?

**Improves, on paper** (net expectancy flips from −0.040% to +0.338%) — but
on a dramatically smaller, boundary-hugging sample (43 trades vs 735;
`session_coverage` sits exactly at the 10-day minimum). This alone would be
a fragile basis for confidence.

## Does replication agree directionally with validation?

**No.** Replication's gross expectancy is negative (−0.124%), reversing the
sign both validation (+0.438%) and development (+0.060%) showed. This is
the single most important finding in this task: on the broadest of the
three samples (182 trades, 33 symbols, 34 days — more statistical power
than validation itself), the hypothesized fade edge is not merely absent,
it is inverted, with a bootstrap CI that confidently excludes zero on the
negative side.

## Is the edge economically large enough relative to 10bps?

Only in validation, and only marginally (net +0.338% vs a 10bps round-trip
cost already netted in). In development and replication, the edge is
smaller than — or opposite in sign to — the cost drag itself.

## Is performance concentrated?

No, in any of the three periods — top1/top3 symbol and day shares are all
well under the 40% flag threshold everywhere. This rules out "a few lucky/
unlucky trades explain everything" as an excuse for either the validation
pass or the replication failure.

## Is symmetry (long vs. short) supported?

No — and this is itself informative. The profitable side of the trade
**flips** across all three periods: development favors short, validation
favors long, replication favors neither. A real, structural mean-reversion
effect should show a more stable directional signature across independent
periods than this. The instability is consistent with the effect being
closer to noise than to a robust phenomenon.

## Bottom line

Two of three independent periods (development, replication) show a
net-negative, cost-adjusted result; the third (validation) shows a
positive result but on the thinnest, most boundary-hugging sample of the
three, and none of the three periods agree with each other on which side
of the trade is profitable. This is not the profile of a credible, robust
edge — see `task70_summary.md` for the final classification.
