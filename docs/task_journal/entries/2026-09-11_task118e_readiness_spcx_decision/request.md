Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118E — READINESS RECOVERY, SPCX PRICE FRESHNESS AND ONE RESEARCH DECISION

OBJECTIVE
Resolve the operational limitations that still affect today's useful output:
1. Only 24/43 tickers were strategy-ready at the last observation.
2. SPCX's reported valuation used a roughly 25-minute-old price.
3. Task118D needs a clear episode/trade reconciliation and bounded
   composition analysis leading to one decision.

Complete evidenced repairs and validation today where feasible.
Do not substitute another descriptive report for an actionable outcome.

STANDING AUTHORIZATION
Controlled hotfixes, configuration corrections and stop/start cycles are
authorized when an evidenced defect prevents intended operation.
Do not wait for EOD solely to preserve an unproductive session.

First validate changes in isolation, preserve state, then deploy/restart
through the supported mechanism. No repeated permission request is needed
for these already-authorized operational actions.

This does not authorize arbitrary strategy tuning, scope expansion, paid
data, broker activity or Experimental external delivery.

BASELINE — VERIFY
Release branch: research/talonx-strategy-validation
Reported running code: c88f4d4600735dcc65fb5108c73489e877d16ebe
Latest reported release docs: 0209ada
Research branch: research/talonx-profitability-2026-09
Latest reported research SHA: 355eb16
Session: results/prospective_2026-09-11

Protected:
- V2 fingerprint 11107198c5b81237.
- V2 ledger <REPO_ROOT>\v2_lane.db.
- 39-name resolved-active-watchlist execution scope.
- 45-day lookback; composite-yf.
- Existing official V2/Intelligence delivery configuration.
- Experimental external delivery OFF.
- No real-capital or short activity.

Read Task118D reports, Task118C incident evidence, current runbook and journal.
Verify actual UTC time, market session, runtime and ledger state.

PART 1 — READINESS: ESTABLISH THE ACTUAL SERVICE GAP

Capture all 43 active tickers at one UTC cutoff:
symbol | required timeframe/history | valid bars | missing bars |
latest bar time | readiness | last evaluation | blocking reason

For not-ready symbols:
- Trace preseed failure, fallback progress and provider responses.
- Verify historical bars are ordered, unique, correctly timestamped and
  compatible with indicator/session requirements.
- Estimate readiness time from observed valid-bar arrival cadence.
- Label estimates uncertain; do not assume every minute creates a bar.
- Record which portion of the regular session was actually unevaluable.

Distinguish:
- Fresh prices.
- Sufficient indicator history.
- Actual strategy evaluation.

Do not claim LOW_VOLATILITY explains a ticker that never reached evaluation.
Do not claim a profitable trade was missed without candidate evidence.

PART 2 — BOUNDED WARMUP RECOVERY

Determine whether existing historical data or existing provider access can
safely supply the missing valid history now.

Prefer:
- Validated local historical data.
- Existing supported warmup/backfill mechanisms.
- Bounded per-symbol recovery for failed bulk requests.
- Rate-limited retries with timeouts, backoff and visible results.

Requirements:
- Preserve indicator formulas, minimum history and timeframe semantics.
- No synthetic bars, future data or current daily bars substituted for
  intraday history.
- Match symbol identity and price-adjustment conventions.
- Merge/deduplicate safely without corrupting live buffers.
- Historical warmup must not emit retrospective actionable signals or
  paper trades, or replay historical exit events into open positions.
- Resume decisions using current eligible observations after warmup.
- Avoid competing writers, overlapping pollers and provider request storms.

If a supported recovery action is sufficient, use it.
If a code/config defect requires a fix, implement and test in isolation.

If data cannot support recovery, report exact symbols, missing ranges and
provider limitations. Do not lower readiness requirements to report PASS.

Acceptance:
- Before/after readiness table.
- Evidence recovered symbols actually evaluate on subsequent live data.
- Any remaining unsupported symbols labelled explicitly.
- No duplicate bars, alerts, entries or exits.

Do not promise 43/43 readiness when valid data is unavailable.

PART 3 — SPCX: VALUATION VERSUS EXIT MONITORING

Verify the actual instrument mapping, open position and latest market data.
Do not infer issuer identity or filing status from a cached application label.

Trace:
provider observation -> ingestion -> publication -> Experimental consumer ->
exit evaluation -> displayed valuation

Record:
- Event time and processing time.
- Price source, price age and adjustment basis.
- Last exit-evaluation timestamp and disposition.
- Whether the 25-minute-old mark was only a report snapshot or represented
  an ongoing monitoring gap.

If SPCX has already exited, reconcile the actual exit instead.
Do not assume the last reported position state still holds.

Fix a proven routing/consumer/valuation defect using focused tests.
If the provider has no fresh observation, expose DATA_UNAVAILABLE or the
equivalent pending state. Do not fill using an invented current price.

Preserve existing stop/target/gap/session policy.
No forced or backdated exit merely to complete this task.

Reconcile Experimental:
- Four previously reported closes total -$324.4662.
- Verify current realized P&L and any additional trades.
- Report unrealized P&L only with a timestamped price and freshness label.
- Keep repair-affected trades separate from clean prospective evidence.

PART 4 — TASK118D ACCOUNTING CORRECTIONS

Reconcile populations under the matched runtime:
A: configured 39 names.
B: remaining 587 names.
C: combined 626 names.

Explicitly distinguish:
- Records and clusters.
- Evaluated episodes.
- Eligible episodes.
- Entered positions.
- Closed round trips.
- BUY/SELL rows.
- Open/unresolved positions.

Explain whether the reported 10 / 147 / 157 are trades, entered episodes or
all evaluated episodes. Do not relabel counts without tracing artifacts.

Verify C = A + B at the appropriate level and explain any portfolio
interaction or selection differences.

Preserve the Task116 comparison correction:
the prior 620-name population and runtime are not interchangeable with C.

Keep issuer-bootstrap confidence intervals labelled conditional on their
dependence assumptions. Assess whether overlapping trade windows/shared
market shocks materially limit interpretation. If practical with existing
data, add one predeclared time-dependence sensitivity; do not shop methods
until significance appears.

PART 5 — BOUNDED COMPOSITION ANALYSIS

Question:
Do observable pre-entry characteristics provide a plausible explanation
for A's historical difference from B?

Before calculating results, record:
- One small predefined feature set.
- Units, historical source and availability dates.
- Issuer-versus-trade weighting.
- Comparison statistic and randomization/resampling method.
- Missing-data treatment and limitations.

Use sector/size only where historical evidence is available.
Do not substitute current market capitalization or classifications and call
them point-in-time. Omit unsupported features or label them separately.

Use volatility/liquidity features derived strictly before entry.
Treat repeated issuer trades explicitly; do not count them as independent
issuers.

If comparing A's six traded issuers with random six-issuer subsets of B:
- Explain the sampling assumptions.
- Preserve relevant temporal exposure where feasible.
- Report uncertainty and the small effective sample.
- A non-significant difference means insufficient evidence, not proof of
  identical composition.
- Avoid causal claims from descriptive associations.

Do not remove MSTR or select features after seeing which make A look better.
No scope expansion or live strategy change follows automatically.

REQUIRED RESEARCH DECISION
End with either:

A. ONE_TESTABLE_HYPOTHESIS
Specify causal rationale, available data, fixed protocol, cost model,
evaluation population, relation to earlier rejected work and rejection
criteria. Identify genuinely unused evaluation data; if none exists, label
the proposed work exploratory and retain a future confirmation requirement.

OR

B. NO_SUPPORTED_STRATEGY_CHANGE
State what evidence is missing and the smallest concrete action that would
resolve it. Do not recommend an endless chain of composition reports or
waiting years for rare trades as the sole programme.

PART 6 — CONDITIONAL DEPLOYMENT / RESTART

If operational changes are required:
1. Test in an isolated hotfix checkout based on the actual release.
2. Run focused readiness, historical/live separation, exit, restart and
   ledger-continuity tests.
3. Record current effective configuration and pending obligations.
4. Gracefully stop affected writers; use full-stack restart only if needed.
5. Verify ownership, no competing writer and consistent backups.
6. Deploy the reviewed committed change.
7. Restart with the same approved scope, strategy and ledger paths.
8. Verify checkpoint survival, truthful readiness, fresh exit evaluation,
   no duplicate delivery/trade and retained Redis.

Do not edit loaded source files in place.
Do not mark EOD reconciled during a midday restart.
Do not restore a backup over newer legitimate ledger writes.
Record actual interruption and before/after SHAs.

If no safe change is supported, leave runtime unchanged and explain why.

PART 7 — EOD AND JOURNAL

If still executing at/after verified September 11 XNYS close, perform:
python -m talonx_ops.prospective close

Expected close: 2026-09-11T20:00:00Z.
Complete by 21:30:00Z.
If overdue, close promptly and document lateness.
If already closed, verify existing evidence rather than duplicate closure.

Capture final:
- Per-symbol readiness/evaluation coverage.
- Per-lane activity and delivery counts.
- Experimental realized/unrealized outcomes and remaining obligations.
- V2 reconciliation and invariant state.
- Shutdown process/port checks and retained Redis.

Do not arbitrarily flatten multi-day positions.
If finished before close, return the explicit operator action.
No unrequested scheduler or claimed background monitoring.

Maintain a TASK118E repository journal entry:
- Exact prompt and final response.
- Evidence, decisions, tests and limitations.
- Starting/final/deployed SHAs.
- Deployment changes and recovery checks.
- Corrections linked from previous claims.

Publish sanitized reports/scripts on appropriate branches and push normally.
No main merge, force-push, secrets, databases or bulk private data.

FINAL RESPONSE
1. Verdict and SHAs.
2. Readiness before/after, exact cutoff and remaining blocked symbols.
3. Recovery performed, or precise data limitation.
4. SPCX freshness, exit-monitoring and current position result.
5. Experimental P&L reconciliation.
6. Episode/trade-count corrections.
7. Composition result and its limitations.
8. ONE_TESTABLE_HYPOTHESIS or NO_SUPPORTED_STRATEGY_CHANGE.
9. Deployment/restart results or runtime unchanged.
10. EOD status and journal/report links.

Operational success and profitability evidence must remain separate.
