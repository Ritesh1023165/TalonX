# Stage 3 raw output manifest (what is committed vs. kept local-only)

`stage3_replay/` contains the full raw output of the single frozen replay. Most files (summary.json/
txt, trades.csv/json, equity_curve.csv, data_quality.json, results.html, research_candidate_telemetry.csv,
run_stdout.log, run_stderr.log — all <1MB except the candidate telemetry at 832KB) are committed as-is.

**Two files are excluded from git** (left on local disk only, not committed, not deleted):
| File | Size | Rows | SHA-256 |
|---|---:|---:|---|
| `task74s_10symbol_full_research_volatility_telemetry.csv` | 163MB | 1,901,855 | `a60c75d7e7bd51aefbcf4c0ff96ae7de1caa974ee7ba9610ce397a6f764e1f8f` |
| `task74s_10symbol_full_rejected_signals.csv` | 84MB | 1,786,849 | `0887b1712e65346fb8318d2ac8405e8d069904509da9bf81df61ccecf5f1da53` |

**Reason**: committing ~247MB of raw per-bar/per-rejection telemetry to git would substantially bloat
repository size for marginal benefit — every number needed for this task's conclusions has already been
extracted into small, committed, derived artifacts (`stage3_funnel.csv`,
`stage3_per_symbol_rejection_pivot.csv`, `stage3_non_volatility_rejections.csv` (the 5,000-row
non-`LOW_VOLATILITY` subset of `rejected_signals.csv`, itself committed and sufficient to reproduce
every candidate-level rejection number in this report), `stage3_per_symbol_summary.csv`,
`stage3_per_bucket_summary.csv`). The two excluded files are exactly reproducible byte-for-byte by
re-running the command in `stage3_replay_launch_manifest.json` against the unchanged dataset/config
(hashes above let a future reader confirm a regenerated copy matches this run without needing the
original file). This is a repository-hygiene decision, not evidence suppression — nothing in the
excluded files contradicts or adds to the conclusions already extracted and committed.
