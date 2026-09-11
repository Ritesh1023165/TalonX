Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118 — BASELINE RECONCILIATION, PROFITABILITY DIAGNOSTICS AND TASK JOURNAL

OBJECTIVE
Move from infrastructure validation to measurable product economics.
Complete the research below while preserving today's running paper session.
Implement the repository task journal as part of this task.

Do not stop after an inventory or a plan. Produce the analyses supported by
available data, clearly identify remaining evidence gaps, and publish results.

CONTEXT — VERIFY BEFORE WORK
Running release:
- Branch: research/talonx-strategy-validation
- Reported SHA: fb4b071eafb74f13bf2ab290d1e2c80e400d6163
- Session: results/prospective_2026-09-11
- V2 fingerprint: 11107198c5b81237
- Approved execution scope: 39 resolved active watchlist names
- Lookback: 45 calendar days
- Pricing: composite-yf; delayed daily-bar reference-model fills
- Intelligence and V2 official Telegram delivery enabled
- Experimental external delivery blocked

Research:
- Worktree: C:\workspace\TalonX-task118-profitability
- Branch: research/talonx-profitability-2026-09
- Reported SHA: c85a72ffb3dd6153c88a4e74bc9eeee5586aca54
- Read docs/research/TASK118_BASELINE_A_RESULTS.md,
  TASK118_INVENTORY.md and the profitability research contract.

Reported baseline:
10 closed trades, 30% wins, −2.93% mean net return, PF 0.315.
This is a small retrospective subset diagnostic, not an established estimate
of future profitability. Verify its construction before using it for tuning.

WORKING BOUNDARIES
- Keep the running release, strategy, scope, thresholds and config unchanged.
- No live checkout, merge, restart, new poller or experimental external send.
- Research uses isolated databases, outputs and bounded compute resources.
- Obtain consistent SQLite snapshots using the supported backup mechanism;
  do not copy an actively written database without WAL consistency.
- No production database mutation, Redis mutation or ledger reset.
- No paid data, new AI integration or broad parameter search.
- Do not remove losing tickers to make results positive.
- Do not merge research into the release branch.
- Record actual state if it differs from this handoff; never overwrite
  unrelated work to force the expected baseline.

PART 1 — PERMANENT REPOSITORY TASK JOURNAL

Create:
docs/task_journal/README.md
docs/task_journal/TEMPLATE.md
docs/task_journal/TASK_INDEX.md
docs/task_journal/RETROSPECTIVE.md
docs/task_journal/entries/<date>_task118_profitability_diagnostics/
  request.md
  outcome.md
  record.md

Save this exact prompt in request.md, with any subsequent steering.
Save the final execution response in outcome.md.

record.md must contain:
- Task objective, acceptance criteria, UTC start/end.
- Branch, starting SHA, implementation/result SHA.
- Requested versus completed scope.
- Source/runtime/data manifests and reproducible commands.
- Tests, experiments, results and limitations.
- User-visible outcome.
- Operational and profitability verdicts separately.
- Production effects, external sends and protected-state checks.
- Fixed/open/deferred findings and next actions.
- Evidence links and later corrections.

Index existing Task117 audit bundles and Task118 reports without duplicating
them. Missing historical prompts must be labelled NOT_AVAILABLE.
Do not reconstruct all earlier iterations.

Add a concise repository instruction in the appropriate existing contributor
instruction file so future tasks maintain this journal. Respect existing
instructions; do not replace them wholesale.

Preserve original conclusions and append corrections. Keep secrets,
destination identifiers, databases and bulk datasets out of Git.

PART 2 — RECONCILE THE V2 BASELINE

A. Reproducible runtime and data
Record the actual relevant runtime modules and versions, including service,
Form-4 adapter, store, calendar, pricing and scope enforcement.
Five frozen-file fingerprint equality alone is insufficient.

Ensure any narrowly synchronized research dependencies are reproducible from
committed source. Avoid a broad branch merge.

Record:
- Exact 39-symbol/CIK manifest and resolution date.
- Historical membership limitations and retrospective selection bias.
- Filing and price datasets, coverage windows and hashes.
- Chronological replay settings, liquidity rules, sizing and costs.
- Missing data and its effect on eligible episodes.

Specifically establish whether missing SHOP prices blocked an otherwise
eligible episode. "No SHOP trades" alone does not establish no impact.

B. Trade-level reconciliation
Publish sanitized:
- All 17 episode dispositions.
- All 10 closed trades, with correlated episode IDs.
- Filing availability, eligibility, entry and exit dates.
- Entry/exit prices, gross/net returns, costs and dollar P&L.
- Rejection/skip reasons and pricing-source provenance.

Explain the difference between:
1. Earlier reported three trades in the watchlist-restricted replay.
2. Current ten executed trades.
3. Task116 episode counts versus its 150 executed BUY/SELL pairs.

Use matched periods, runtime, definitions and costs for comparisons.
Task112R's longer historical window must not be presented as the same window.

If a comparison cannot be reproduced, state precisely what is unavailable.
Do not invent a reconciliation.

C. Correct economic measurement
Verify:
- Costs are applied once under a clearly stated convention.
- Win rate, profit factor and net expectancy.
- Realized dollar P&L and ending cash.
- Chronological portfolio equity and drawdown, where price coverage permits.
- Exposure, concurrency and issuer concentration.

Distinguish the reported −42.7% cumulative trade-return drawdown from actual
portfolio drawdown. Do not label one as the other.

Explain the $10m research starting cash / position sizing versus the $300k
live campaign. If a $300k replay is needed to measure campaign constraints,
run it as a separately labelled diagnostic.

Keep the full ten-trade result primary. Leave-one-issuer-out results are
concentration diagnostics, never a justification to delete MSTR.

PART 3 — ORIGINAL INTRADAY SELECTIVITY AND OUTCOMES

Determine why configured tickers rarely produce actionable Original alerts.

Separate:
- Unavailable/stale data and warmup.
- Pre-evaluation volatility rejection.
- Confluence, risk/reward, trend and session gates.
- Qualified publication.
- Delivery and paper execution.

Use distinct evaluations and consistent cutoffs. Do not equate repeated bar
processing with independent opportunities.

Inspect the reported 4/43 intraday warmup readiness:
- Was this expected before open?
- What data and cadence are required?
- Was readiness achieved during the regular session?
- Did a readiness defect prevent valid evaluation?

Read-only inspection only; no intraday production fixes.

Trace volatility units and timeframe against their documented thresholds.
Distinguish a unit/implementation error from an intentionally selective rule.

Where historical data supports it, measure outcomes for the complete
predefined candidate population, with causal entry timing, direction,
costs and a stated exit horizon. Do not select only stocks that later rose.

Do not lower thresholds in production. If counterfactual analysis is
appropriate, specify one bounded hypothesis before running it and retain
the frozen baseline. Label already inspected data as exploratory.

If price coverage is insufficient, complete the supported analysis and
report the precise missing symbols/dates/bars.

PART 4 — EXPERIMENTAL PAPER OUTCOMES

Reconcile the five previously reported open positions:
VRT, BLSH, AMD, STX and SPCX.

For each, report:
- Actual recorded entry, quantity, price and strategy.
- Current recorded status and any exit obligation.
- Realized P&L.
- Unrealized P&L using a timestamped reliable price.
- Costs, price age and data availability.

Unknown MTM must remain UNKNOWN, not zero.
Keep this lane separate from V2 and Original.

Reconcile dashboard forward-outcome sample counts versus full-population
counts, including pending versus resolved observations and date windows.
Check bullish/bearish return direction and stated cost assumptions.

No synthetic historical entries, forced exits, live ledger writes or
Experimental Telegram enablement.

PART 5 — RECOMMEND ONE NEXT RESEARCH ACTION

Produce a concise decision table:
lane | available evidence | economic result | limiting factor |
next experiment | promotion requirement

Answer:
- Is the main limitation lack of opportunity, data/readiness, delivery,
  strategy selectivity or negative observed economics?
- What evidence supports that conclusion for each lane?
- Which single next experiment has the strongest rationale?
- What prior rejected experiment does it resemble, and what new evidence
  justifies revisiting it, if applicable?
- What result would cause us to reject it?

Do not promise a 50–60% win rate or profitability.
Do not promote a strategy from these small or previously inspected samples.
Informational Telegram delivery is a product result, not a trading return.

PART 6 — LIVE SESSION AND EOD

Research must not interfere with the active session.

If this execution is still active at or after the verified September 11
XNYS close, perform the already-authorized canonical EOD closure:
python -m talonx_ops.prospective close

Expected close: 20:00 UTC; closure deadline: 21:30 UTC.
Verify actual time/session state before acting. Do not close early.

Preserve open multi-day positions and pending obligations; do not flatten
them just because the application is shutting down.

Capture:
- Final per-lane counters and their cutoffs.
- Delivery states and acknowledged message IDs, sanitized.
- Paper positions, trades, realized/unrealized P&L and unresolved prices.
- Ledger reconciliation and invariants.
- Processes/ports after close, retained Redis, remaining obligations.

If research finishes before EOD, return the research result and state the
remaining operator close action. Do not claim background monitoring.

DELIVERABLES
Commit on the research branch:
- Task journal and index.
- Baseline reconciliation report and sanitized episode/trade CSVs.
- Reproducible analysis scripts and runtime/data manifest.
- Original selectivity/outcome report.
- Experimental outcome report.
- One next-experiment proposal.
- Evidence limitations and corrections.

Link existing reports rather than rewriting them.
Keep large/private artifacts outside Git, with hashes and locations.
Push normally; no release-branch merge or force-push.

FINAL RESPONSE
1. Starting/final research SHA and push result.
2. Live session preserved, or canonical EOD result if performed.
3. Reconciled V2 numbers and corrections to earlier claims.
4. Original intraday findings.
5. Experimental realized/unrealized outcomes.
6. What we learned about profitability.
7. One recommended next experiment and its rejection criteria.
8. Remaining evidence gaps.
9. Task-journal and report links.

Do not substitute another broad infrastructure audit for these deliverables.
