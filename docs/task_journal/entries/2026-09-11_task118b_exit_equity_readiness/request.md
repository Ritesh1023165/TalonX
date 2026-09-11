Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118B — EXIT-TIMING VERIFICATION, EQUITY CORRECTION AND LIVE READINESS

OBJECTIVE
Close the specific evidence gaps from Task118A while today's session runs:
1. Verify the VRT paper exit's event/processing timestamps and fill validity.
2. Replace cash-based "portfolio drawdown" with correctly valued equity.
3. Verify regular-session warmup and evaluation readiness.
4. Correct the research protocol and repository task journal.

Complete the supported analysis; do not return another inventory-only report.
Do not broaden this into another general infrastructure audit.

BASELINE — VERIFY
Reported release:
- Branch: research/talonx-strategy-validation
- Deployed SHA: c88f4d4600735dcc65fb5108c73489e877d16ebe
- Docs-only commit afterward: d61b920
- Session: results/prospective_2026-09-11
- V2 fingerprint: 11107198c5b81237
- V2 scope: 39 resolved active watchlist names
- Lookback: 45 days
- Pricing: composite-yf
- Experimental external delivery: OFF
- V2 ledger: <REPO_ROOT>\v2_lane.db

Research:
- Branch: research/talonx-profitability-2026-09
- Prior baseline reconciliation: 4b1e50e
- Research corrections: 9ec25b0
- Read TASK118A_RESEARCH_CORRECTIONS.md and related Task118 reports.

Verify actual UTC time, exchange session, running process start times,
effective config and repository state. Do not assume HEAD equals the
revision loaded by running processes.

Locate the actual Task118A release evidence files. A prior GitHub fetch of
docs/audits/task118a_priority_hotfixes_2026-09-11/README.md returned 404.
Repair published navigation if necessary; do not infer the whole bundle
is missing from a missing README.

BOUNDARIES
- Default to read-only production inspection and isolated research.
- Use consistent SQLite snapshots and bounded reads.
- Do not change strategy thresholds, scope, sizing or holding rules.
- No ledger reset, historical backdating or synthetic production trades.
- No Redis flush, new sender/poller, paid data or Experimental external sends.
- Do not modify source files underneath running processes.
- Documentation and research corrections need no application restart.

A narrow functional hotfix and controlled restart remain authorized if
inspection proves an active execution/readiness defect. First reproduce it,
implement and test in isolation, then use the established safe deployment
procedure. Do not restart merely for documentation changes.

PART 1 — VRT EXIT CHRONOLOGY

Reported:
- Shutdown completed: 2026-09-11T11:53:31Z
- Restart: 2026-09-11T11:54:30Z
- VRT exit event time: 07:53:51-04:00 = 11:53:51Z
- Paper exit price: 251.0872125
- Net P&L: -213.72

The event timestamp falls inside the reported downtime.
Determine what actually happened without presuming either correctness or
a defect.

Publish one correlated trace containing:
- Position ID and entry state.
- Market event ID / Redis stream ID where available.
- Provider timestamp and whether it denotes bar start, bar end or quote time.
- Ingestion/publication timestamp.
- Consumer processing timestamp.
- Exit decision and database persistence timestamps.
- Process PID/start time and loaded revision.
- Price source, raw input price and fill/slippage/cost calculation.
- Stop/target trigger, session eligibility and freshness check.
- Delivery/display record updates and duplicate checks.

Distinguish unavailable timestamps from inferred ones.
A Redis stream ID alone is not proof of exchange event time.

Inspect:
- Stream replay/backlog behavior after restart.
- Whether this was a pre-restart event processed later.
- Whether premarket exits are allowed under the existing contract.
- Whether price adjustments match the entry/stop price basis.
- Whether the documented gap/fill policy supports the recorded price.

Verdict:
VALID_UNDER_EXISTING_PAPER_POLICY /
STALE_OR_INELIGIBLE_EVENT_DEFECT /
INSUFFICIENT_EVIDENCE

Call this a paper-model fill, not evidence of an executable market fill.

If invalid:
- Preserve the original record and evidence.
- Fix the forward-processing defect with focused tests.
- Do not silently erase/rewrite the historical exit.
- Document the required auditable correction separately; do not invent
  replacement prices or a new recovery rule.

Check the remaining BLSH/AMD/STX/SPCX positions against the same lifecycle,
without forcing an exit simply to demonstrate activity.

PART 2 — CORRECT EQUITY AND DRAWDOWN

The research correction currently derives "portfolio drawdown" from
portfolio_cash_after. Trace exactly what that field represents.

If it is uninvested cash:
- Withdraw the portfolio-drawdown label from -$23,042.30 / -7.68%.
- Label it as cash-path drawdown if useful.
- Explain that buying assets reduces cash without creating an equivalent
  immediate economic loss.

Reconstruct chronological equity:
equity(t) = cash(t) + market value of open positions(t)

Requirements:
- Use actual position quantities and consistent price adjustments.
- Use timestamped available marks; no future-price substitution.
- Apply the established cost convention exactly once.
- Respect event ordering for entry-open and exit-close transactions.
- Record missing/stale marks and their effect.
- Label daily-close drawdown as such; do not claim intraday drawdown from
  daily prices.
- Compute running peak and peak-to-trough dollar/percentage drawdown.
- Reconcile final equity/cash to the closed-trade net P&L.
- Report the $10m and $300k diagnostics separately.
- Confirm whether capital constraints and executed trades are identical.

Publish:
- Sanitized equity-series CSV with cash, open value, equity, peak,
  drawdown and valuation coverage.
- Peak/trough dates and position contributions.
- Reproducible script and data/runtime manifest.
- Corrected metric table.

If marks are insufficient, report portfolio drawdown as UNAVAILABLE or
explicitly PARTIAL. Do not substitute cash drawdown or summed trade returns.

PART 3 — REGULAR-SESSION READINESS

The preseed reportedly failed 0/43 due to a yfinance bulk failure, with
live-buffer fallback working. Establish the practical impact.

For each active ticker, capture:
- Required timeframe/bar count.
- Valid available bars and latest timestamp.
- Preseed outcome and fallback status.
- First READY time, if recorded.
- First actual regular-session strategy evaluation.
- Any readiness-related skip/error.

Separate:
1. Preseed provider failure.
2. Correct fallback operation.
3. Whether fallback became ready soon enough for intended evaluation.

Do not call the overall outcome "expected behavior" merely because a
fallback exists.

If the market has opened, inspect actual regular-session evidence.
If it has not, report what is proven now and the observation still needed;
do not fabricate a future readiness result or claim background monitoring.

Distinguish readiness-blocked evaluations from LOW_VOLATILITY rejections.
Do not claim a profitable opportunity was missed without causal candidate
and price evidence.

If an implementation defect is proven, fix only that defect. Do not lower
history requirements or thresholds to make the status green.

PART 4 — RESEARCH PROTOCOL CORRECTION

Revise the Task118A observation protocol:
- N=30 and 60 days are administrative review choices, not guarantees of
  adequate statistical power or independent observations.
- State the estimand: net return per trade versus portfolio return.
- Account for repeated issuers and overlapping holding periods.
- An entirely negative expectancy interval concerns this scope's expectancy.
  It does not, by itself, prove underperformance against a broader panel.
- A relative-performance claim needs a comparable difference analysis.
- Repeated monthly interval checks must not be presented as a fixed-test
  error guarantee without an appropriate sequential method.
- Preserve an INCONCLUSIVE outcome and do not force promotion or rejection.

Estimate a plausible time to accumulate useful evidence using the observed
trade frequency, clearly labelling extrapolation and uncertainty.

Do not make waiting for rare V2 trades the entire profitability programme.
Recommend one bounded next analysis supported by current data and previous
research, or identify the exact missing data needed. No broad optimisation,
post-hoc ticker removal or automatic strategy promotion.

PART 5 — CONDITIONAL HOTFIX / RESTART

Only if Parts 1 or 3 prove an active functional defect:
1. Reproduce and test in an isolated hotfix checkout.
2. Run focused execution, timestamp, restart and ledger-continuity tests.
3. Preserve current campaign, delivery and pending-position state.
4. Stop the necessary component or stack using supported ownership-safe
   controls; avoid marking EOD complete during a midday restart.
5. Back up databases consistently with writers stopped.
6. Deploy the reviewed commit and restart with existing approved config.
7. Verify one writer per ledger, truthful readiness, no duplicate exits/
   entries/messages, checkpoint survival and retained Redis.
8. Record before/after SHAs and the exact interruption window.

Do not restore a pre-deployment database over newer legitimate writes.
If no functional defect is established, leave runtime unchanged.

PART 6 — EOD

If still executing at/after the verified September 11 XNYS close:
python -m talonx_ops.prospective close

Expected close: 20:00 UTC.
Required completion: by 21:30 UTC.

Capture final counters, delivery states, positions, valuations and invariant
results; verify shutdown and preserve multi-day obligations.
Do not flatten V2 merely because the application closes.

If finished before EOD, return the explicit operator close action.
No unrequested scheduler or claimed background monitoring.

JOURNAL / PUBLICATION

Maintain docs/task_journal/:
- Exact prompt.
- Final response.
- Task118B record and index entry.
- Dated corrections linked from original Task118/118A claims.
- Verified versus reported versus unresolved evidence.
- Implementation, deployed and research SHAs where applicable.

Publish sanitized reports and reproducing scripts:
- TASK118B_EXIT_TIMING.md
- TASK118B_EQUITY_RECONCILIATION.md
- TASK118B_READINESS.md
- TASK118B_RESEARCH_PROTOCOL.md

Use appropriate release/research branches.
Push normally, no main merge or force-push.
No secrets, production databases or bulk private artifacts in Git.

FINAL RESPONSE
1. Overall verdict and starting/final SHAs.
2. VRT event-time/processing-time conclusion and fill validity.
3. Correct equity/drawdown results and withdrawn claims.
4. Regular-session readiness and actual evaluation coverage.
5. Any hotfix/restart performed, or runtime explicitly unchanged.
6. Current Experimental and V2 position continuity.
7. Corrected research protocol and one concrete next analysis.
8. Remaining gaps and EOD obligation.
9. Journal, evidence and commit links.

Do not equate operational repair, more alerts or a paper exit with
demonstrated profitability.
