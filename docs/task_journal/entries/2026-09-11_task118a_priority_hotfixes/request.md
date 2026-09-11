Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118A — PRIORITY HOTFIXES, VALIDATION AND CONTROLLED RESTART TODAY

AUTHORIZATION AND OBJECTIVE
Fix the evidenced priority defects, validate them, deploy the passing hotfix,
and restart the affected component or application today.

A controlled restart is authorized. Do not stop merely to request the same
permission again after passing the gates below.

Preserve existing ledgers, positions, pending notifications and session
continuity. This is a functional repair, not strategy tuning.

Do not claim all possible defects are eliminated. Close the concrete issues
below and report any newly discovered blockers honestly.

BASELINE — VERIFY ACTUAL STATE
Reported running release:
- Branch: research/talonx-strategy-validation
- SHA: fb4b071eafb74f13bf2ab290d1e2c80e400d6163
- Session: results/prospective_2026-09-11
- V2 fingerprint: 11107198c5b81237
- V2 ledger: <REPO_ROOT>\v2_lane.db
- Scope: 39 resolved active watchlist names
- Live lookback: 45 days
- Pricing: composite-yf
- Official V2 and Intelligence Telegram delivery enabled
- Experimental external delivery blocked

Research:
- Branch: research/talonx-profitability-2026-09
- Latest reported SHA: 4b1e50e4f1b587b907e204dbc900d59dd2973eb6
- Read TASK118_BASELINE_RECONCILIATION.md,
  TASK118_ORIGINAL_SELECTIVITY.md, TASK118_EXPERIMENTAL_OUTCOMES.md,
  TASK118_NEXT_EXPERIMENT.md and docs/task_journal/.

Verify actual UTC time and XNYS session state. Do not assume it is still
premarket. Record any differences from these reported baselines.

PRIORITY 1 — EXPERIMENTAL PAPER EXIT LIFECYCLE

Reported defect:
check_exits/flatten_all exist in talonx_signals/experimental_paper.py but
are not invoked by the live loop. Five positions remain open:
VRT, BLSH, AMD, STX, SPCX.

1. Trace the real producer, market-data path, paper store and exit rules.
   Confirm the defect from source and recorded state before changing code.

2. Wire the existing intended exit lifecycle into the appropriate runtime.
   Preserve documented stop/target/holding/session rules.
   Do not introduce a new mandatory flatten rule just because flatten_all
   exists. Determine which policy applies to this lane.

3. Ensure exits are evaluated independently of:
   - Whether a fresh entry signal is generated.
   - Entry volatility/confluence filters.
   - New-entry lockouts or unavailable entry-only inputs.

4. Validate instrument identity, price timestamps, session eligibility and
   price availability before executing a paper exit.
   Missing/stale/invalid prices must produce an explicit pending/degraded
   disposition, not an invented fill.

5. Use atomic, durable position transitions.
   Repeated ticks, concurrent callbacks and restarts must not duplicate an
   exit or corrupt cash, quantities, trade history or realized P&L.

6. Experimental must remain local paper only:
   no broker calls and no external Telegram messages.

EXISTING POSITIONS — RECOVERY POLICY
- Take a consistent isolated snapshot and inspect all five positions.
- A historical reference price below a stop is evidence to investigate,
  not proof of an executable fill at the stop.
- Never backdate an exit, rewrite an entry or claim a missed stop executed.
- Apply the established gap/fill policy to the next valid eligible
  observation, recording actual observation time and recovery reason.
- If no applicable recovery policy exists, leave the affected position
  explicitly pending and report the exact semantic decision needed.
- Do not silently invent a new trading rule to complete the hotfix.

Meaningful tests must cover:
- Stop and target exits under the existing policy.
- Exit without a new entry candidate.
- Entry rejection does not block an existing-position exit.
- Missing/stale prices.
- Restart and repeated-event idempotency.
- Existing overdue positions under the supported recovery policy.
- Ledger/cash reconciliation.
- Experimental external-send prohibition.

PRIORITY 2 — ORIGINAL WARMUP / DATA READINESS

Reported observation: only 4/43 tickers had sufficient intraday bars before
open, despite broad HTF readiness.

1. Trace required bar count, timeframe, timestamp/session policy, preseed,
   backfill, provider limits and live-buffer population.
2. Separate expected premarket behavior from failed initialization.
3. Determine whether readiness prevents valid regular-session evaluation.
4. If an evidenced implementation defect exists, fix it with focused tests.
5. If behavior is expected, document it and correct misleading readiness
   presentation where needed.

Do not lower the volatility threshold, reduce required history, change
indicator semantics or manufacture bars to make readiness green.
Do not run expensive historical downloads on the active feed path.
Use existing data entitlements and bounded requests only.

If regular-session observation is still required, say so. Do not claim it
passed from premarket fixtures alone.

PRIORITY 3 — OPERATOR-VISIBLE CORRECTNESS

Address the following where still present:
- Intelligence digest displaying literal <b> markup.
- User-facing "held events" wording for a successfully delivered digest.
- Cards delivered versus actual Telegram message count.
- Experimental exit readiness/pending reasons.
- Missing prices or unavailable outcomes displayed as zero.
- Current-session EOD state presented as already reconciled before close.

Keep changes bounded. Reuse authoritative states and existing routing.
Do not add another sender/poller or redesign the dashboard.

For digest content, use available event facts:
ticker, concise event description, event time and source link.
Do not invent significance explanations, recommendations or missing facts.
Keep Intelligence explicitly informational.

Verify affected views in the real SPA using isolated data and, after
deployment, the live read model. Distinguish fixture screenshots from live
screenshots. If rendering is unavailable, state that limitation.

PRIORITY 4 — RESEARCH REPORT CORRECTIONS

On the research branch, correct:
1. The reversed rejection criterion:
   positive-side confidence-interval exclusion is not a rejection rule.
   Define a bounded observation protocol with sample requirements,
   review horizon, uncertainty and adverse-result criteria before tuning.
   Do not invent arbitrary thresholds solely to obtain a verdict.

2. The drawdown claim:
   reconcile -$2,926.15 net closed-trade P&L with reported -$23,042.30
   maximum drawdown using the dated equity curve and valuation inputs.
   Distinguish cumulative trade returns, marked portfolio equity and
   realized-cash drawdown.
   Identical dollar results on $300k and $10m imply different percentages.

3. The overbroad claim that every free-data research space is closed:
   cite specific rejected hypotheses and their limits instead.

Preserve original claims and append dated corrections in the task journal.
Do not delay a validated operational repair for extended research work.

IMPLEMENTATION AND RELEASE PROCESS

A. Preflight and isolation
- Record current SHA, tree state, effective configuration, process ownership,
  ports, lock owner, heartbeat, ledger states and pending delivery states.
- Never print credentials or commit .env.
- Work on an isolated hotfix checkout based on the actual release.
- Do not edit files underneath running Python processes.
- Do not reset or overwrite unrelated work.

B. Validation
- Run focused tests for changed behavior and relevant lifecycle,
  delivery, paper-ledger and startup regressions.
- Verify V2 frozen fingerprint and strategy/scope settings unchanged.
- Rehearse migration/restart on consistent database copies if applicable.
- Confirm existing positions and pending notifications survive.
- Use intercepted transports for synthetic tests; do not send fake trading
  alerts to the real Telegram destination.
- Stop optional testing once concrete risks and required gates are covered.

C. Choose restart scope
Inspect the actual supervisor ownership and restart mechanisms:
- Prefer a component restart only if it loads the reviewed hotfix safely
  and does not leave dependent components running an incompatible revision.
- Otherwise perform a controlled full-stack restart.
- Do not use an EOD-close command merely as a midday stop mechanism if it
  marks the trading session reconciled or ended.
- Use supported stop/resume semantics, retaining today's session history.
- If safe same-session restart is unsupported, implement and test that
  bounded lifecycle fix before deployment.

D. Controlled deployment — authorized when gates pass
1. Record the pre-deployment cutoff and current state.
2. Gracefully stop the selected writers using ownership-safe controls.
3. Verify processes exited and no competing writer remains.
4. Back up affected databases consistently, including required WAL state;
   protect config backups and record recovery locations.
5. Deploy the reviewed committed hotfix without broad research merges.
6. Apply only required tested migrations.
7. Restart with the same approved effective configuration:
   39-name scope, 45-day lookback, composite-yf, existing delivery gates,
   single supervised Intelligence producer, Experimental external OFF.
8. Preserve existing ledger paths; never create a replacement campaign.
9. Record new SHA, restart time, interruption duration and deployment reason.

No additional Telegram smoke message is required simply for this restart.
Existing authorized natural delivery may resume through the official path.

E. Post-restart acceptance
Verify:
- Startup reaches truthful READY within its bounded grace period.
- One writer per ledger and one intended Telegram polling owner.
- Fresh component/data heartbeats and accurate readiness.
- V2 scope, fingerprint, cash, positions and stale ABCL disposition preserved.
- Pending notifications retained; no replay of expired historical alerts.
- No duplicate entries, exits or logical deliveries.
- Experimental exits now receive valid market observations.
- Existing-position recovery outcomes are attributable and reconciled.
- Dashboard values agree with authoritative state.
- Redis retained; no flush/restart.
- No unrelated process affected.
- No real-capital, short or broker activity.

Observe a bounded period covering multiple real processing cycles.
Do not require a natural trade to claim startup readiness.
Do not claim production exit execution unless a real eligible exit occurred.

FAILURE AND ROLLBACK
If deployment fails:
- Stop affected writers safely.
- Prefer compatible-code rollback.
- Never restore a pre-deployment database over newer legitimate writes.
- Preserve pending obligations, delivery attempts and evidence.
- Report the concrete failed gate and recovery state.
- If a new strategy-policy decision is genuinely required, complete all
  independent repairs first and ask only for that specific decision.

TODAY'S EOD
Maintain the existing obligation:
python -m talonx_ops.prospective close
at/after verified 2026-09-11 XNYS close, expected 20:00 UTC,
with closure completed by 21:30 UTC.

If this task is still executing after close, perform the authorized canonical
closure. Otherwise hand back the explicit operator action.
Do not create an unrequested scheduler or claim background monitoring.

Preserve V2 multi-day positions; do not confuse Experimental's documented
exit policy with V2's +10-session holding contract.

REPOSITORY JOURNAL AND EVIDENCE
Create/update a TASK118A entry containing:
- Exact prompt and final response.
- Baseline, implementation and deployed SHAs.
- Findings confirmed versus not reproduced.
- Tests and rendered acceptance.
- Before/after ledger reconciliation.
- Restart sequence, interruption and recovery.
- Pre-hotfix versus post-hotfix session evidence.
- Remaining issues, decisions and next task.

Commit sanitized source/tests/docs and push normally.
Keep release fixes and research corrections on their appropriate branches.
No main merge, force-push, secrets, databases or bulk results in Git.

FINAL RESPONSE
1. Verdict: HOTFIX_DEPLOYED_AND_RESTART_VERIFIED / PARTIAL / BLOCKED.
2. Starting, fixed and actually running SHAs.
3. Each priority issue: fixed / expected behavior / unresolved, with evidence.
4. Tests and validation results.
5. Restart scope, timings and current health.
6. All five Experimental positions: before/after state and recovery outcome.
7. V2/Intelligence continuity and duplicate-prevention results.
8. Research corrections completed.
9. Remaining issues and EOD obligation.
10. Journal, reports and commit links.

Finish with the next profitability task.
Do not equate successful repair or increased alert volume with profitability.
