Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118D — MATCHED-SCOPE PROFITABILITY COMPARISON AND SESSION EVIDENCE

OBJECTIVE
Complete the bounded historical scope comparison now that the feed incident
has recovered. Preserve today's running session and capture the remaining
readiness, delivery and paper-performance evidence.

Do not repeat a broad infrastructure audit or stop at another research plan.

BASELINE — VERIFY
Release branch: research/talonx-strategy-validation
Reported running code: c88f4d4600735dcc65fb5108c73489e877d16ebe
Latest reported release documentation: 0209ada
Research branch: research/talonx-profitability-2026-09
Latest reported research commit: ec79240

Session: results/prospective_2026-09-11
V2 fingerprint: 11107198c5b81237
V2 scope: 39 resolved active watchlist names
Lookback: 45 days
Pricing: composite-yf
Experimental external delivery: OFF

Task118C verdict:
RECOVERED_TRANSIENT; exact heartbeat-lapse cause unresolved.
No code change or restart performed.

Read the Task118 baseline, reconciliation, Task118B corrections/protocol,
Task118C incident report and repository task journal.

Verify actual state rather than forcing these reported values.

BOUNDARIES
- Research runs in the isolated research worktree using consistent snapshots.
- No running-release edits, restart, strategy tuning or scope expansion.
- No production database writes, Redis mutation or new external sends.
- No paid data, broad optimisation or post-hoc removal of losing tickers.
- Preserve open positions and notification obligations.
- Use bounded compute so research does not impair the live session.

PART 1 — DEFINE COMPARABLE POPULATIONS

Create three explicitly defined populations:
A. Configured 39-name scope.
B. Remaining historical panel, excluding those 39 names.
C. Full historical panel, containing A and B.

Match:
- Historical window.
- Filing availability and causal entry rules.
- Runtime and adapter versions.
- Price adjustments and availability.
- Eligibility rules, holding period and cost convention.
- Episode versus executed-trade definitions.

Reconcile Task116's episode counts versus executed BUY/SELL pairs.
Do not compare 170 episodes directly with 10 executed trades.

Publish membership, trade counts, issuer counts, missing-data exclusions
and the exact source/runtime manifests.

The 39-name population was selected retrospectively.
This comparison is exploratory, not an untouched holdout validation.

PART 2 — VERIFY WHETHER EXISTING TRADES ARE COMPARABLE

Use existing artifacts where they satisfy the matched contract.

Check whether separate replays change:
- Capital constraints.
- Concurrent positions.
- Cooldown or position limits.
- Trade eligibility or execution selection.

Do not assume filtering a full-panel trade ledger reproduces an independently
executed subset portfolio.

If a narrow replay is necessary to obtain a valid matched comparison, run
only that replay under the frozen contract and explain why.
Do not launch new strategy searches.

Publish sanitized trade tables and a bridge explaining any population
differences. If inputs are unavailable, complete supported descriptive
comparisons and identify the exact missing input.

PART 3 — ECONOMIC COMPARISON AND UNCERTAINTY

Primary comparison: A versus B.
Secondary: A versus C, explicitly acknowledging the overlap.

Report:
- Executed trades and distinct issuers.
- Mean/median net return per trade.
- Win rate and profit factor.
- Issuer concentration and temporal concentration.
- Exposure/concurrency where relevant.
- Portfolio metrics only when equity is correctly marked.

Keep the known A baseline visible:
10 closed trades, approximately -2.926% mean net return,
PF 0.315, 30% wins, net closed-trade P&L -$2,926.15.

Use corrected daily marked-equity drawdown, not portfolio_cash_after.
Verify rather than blindly copying previously reported numbers.

For uncertainty:
- Define the estimand and resampling unit before calculating intervals.
- Do not manufacture one-to-one trade pairs between A and B.
- Preserve issuer dependence and address overlapping holding periods.
- For A versus C, preserve their shared observations in joint resampling.
- Report method, assumptions, seed, repetitions and effective group counts.
- If too few independent groups support credible inference, say so.
- Do not treat bootstrap output as automatically reliable at N=10.
- Do not claim relative underperformance solely because A's own interval
  is negative; evaluate the actual difference.

Any concentration sensitivity must retain the complete population as primary.
Do not recommend removing MSTR just because doing so improves the result.

PART 4 — ANSWER THE PRODUCT QUESTION

Explain what the comparison supports about:
- Rare opportunities in the configured ticker scope.
- Observed negative results versus uncertainty.
- Whether scope composition plausibly explains the broader-panel difference.
- Which conclusions remain unsupported.

A broader panel's performance does not authorize expanding the watchlist.
More alerts do not establish a profitable strategy.

Recommend one concrete next analysis or experiment:
- Causal rationale.
- Existing data available.
- Relationship to previously rejected research.
- Fixed scope and evaluation procedure.
- What would reject the hypothesis.
- Expected deliverable.

Do not make waiting years for V2 trades the entire programme.
Do not promise that an untested alternative will work.
If no justified experiment is available, identify the specific evidence gap
instead of repeating "all free-data research is exhausted."

PART 5 — REMAINING LIVE EVIDENCE, READ-ONLY

At a clearly recorded regular-session cutoff:

A. Readiness
Report per ticker:
required/valid bars, latest data time, readiness, last actual evaluation,
and blocking reason.

Explain usable_coverage separately from strategy readiness.
Do not infer 43/43 ready from usable_coverage = 1.0.
Do not infer a missed profitable trade merely from delayed readiness.

B. Experimental outcome
Reconcile the reported closed positions:
- VRT -$213.72
- STX -$25.38
- AMD -$8.22
- BLSH -$77.14
Reported sum: -$324.46

Verify exact ledger totals, cost treatment, quantities and exit timestamps.
Check SPCX's actual current state; do not assume it remains open.

For any open position, report timestamped unrealized P&L and price freshness.
Missing valuation is UNKNOWN, not zero.
Separate realized/unrealized and pre-hotfix/post-hotfix events.
Flag recovery-affected trades; do not treat them as clean prospective
strategy validation.

C. Delivery
Reconcile by domain:
Trading / Intelligence / system-admin / Experimental.

Separate:
- Event cards.
- Logical notifications.
- API-acknowledged Telegram messages.
- Unconfirmed/ambiguous delivery.

Document that the current generic ping label may describe only the Original
domain. Do not change the running application just to fix this label.

D. Incident carryover
Keep the heartbeat-lapse locus and historical 45-candidate total unresolved
unless new preserved evidence actually resolves them.
Do not assign arithmetic residuals to assumed categories.

PART 6 — CANONICAL EOD IF DUE

Verify actual UTC time and XNYS session state.

If this task remains active at/after September 11 close, execute the
already-authorized:
python -m talonx_ops.prospective close

Expected close: 2026-09-11T20:00:00Z.
Complete by 21:30:00Z.
If already overdue, act promptly and document lateness.
Do not run close before the session ends.

Before shutdown preserve:
- Final per-lane counters and cutoff timestamps.
- Readiness/evaluation coverage.
- Paper trades, open positions, prices and valuations.
- Notification states and sanitized acknowledgement identifiers.
- Source/feed health and remaining obligations.

After close verify:
- Ledger reconciliation and invariants.
- Application processes stopped with no unintended respawn.
- Redis retained.
- Multi-day V2 obligations and any remaining Experimental positions preserved
  according to their existing policies, not arbitrarily flattened.

If already closed, inspect existing closure evidence; do not duplicate it.
If the task finishes before close, return the explicit operator action.
Do not claim background monitoring or create a scheduler.

JOURNAL AND PUBLICATION

Create a TASK118D journal entry with:
- Exact prompt and final response.
- Starting/final SHAs.
- Population definitions and decisions.
- Reproducible commands and evidence links.
- Results, limitations and remaining blockers.
- Runtime unchanged, or canonical EOD action if performed.

Publish on the research branch:
- TASK118D_SCOPE_COMPARISON.md
- Sanitized matched trade/population tables.
- Reproducible analysis script.
- Runtime/data manifest.
- One next-experiment recommendation.
- Links to live-session/EOD evidence.

Preserve prior reports; append corrections with links.
Commit and push normally. No main merge or force-push.
No secrets, production databases or bulk private data in Git.

FINAL RESPONSE
1. Verdict and research starting/final SHAs.
2. A/B/C populations and comparability limitations.
3. Economic comparison and uncertainty.
4. What this means for the configured-ticker product.
5. Regular-session readiness result.
6. Experimental realized/unrealized reconciliation.
7. Delivery counts by domain and outstanding incident gaps.
8. EOD result or exact pending operator action.
9. One next research action.
10. Task-journal, report and commit links.

Report operational acceptance and profitability evidence separately.
