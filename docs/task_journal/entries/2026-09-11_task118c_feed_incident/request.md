Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK118C — REGULAR-SESSION FEED INCIDENT, RECOVERY AND READINESS

OBJECTIVE
Investigate the latest stale-feed ping immediately, establish whether the
failure is data production, consumption or telemetry, and restore correct
operation today if a defect is confirmed.

This takes priority over the historical profitability comparison.
A tested hotfix and controlled restart are already authorized.
Do not restart blindly or change strategy filters.

INCIDENT EVIDENCE
Ping cutoff: 2026-09-11T14:29:18Z / 15:29:18 BST.
Reported:
- Process RUNNING; pipeline DEGRADED, market feed stale.
- Source Disconnected; last market event unknown / no heartbeat.
- 43 active tickers; 7,379 market events today.
- 31 provider failures; 0 retries; 0 Redis publish failures/reconnects.
- 623 LOW_VOLATILITY; 45 candidates.
- Displayed candidate reasons: 8 LOW_CONFLUENCE, 13 OPENING_BLACKOUT.
- 0 published; 0 Telegram pushes.
- Regular session.

Earlier "healthy" reports do not override this later observation.
Cumulative event counts do not prove current freshness.
The displayed candidate reasons do not constitute a complete reconciliation.

VERIFY BASELINE
Reported runtime SHA:
c88f4d4600735dcc65fb5108c73489e877d16ebe
Release branch: research/talonx-strategy-validation
Later docs-only SHA: 813bfc0
Session: results/prospective_2026-09-11

Protected configuration:
- V2 fingerprint 11107198c5b81237.
- V2 ledger <REPO_ROOT>\v2_lane.db.
- Scope: 39 resolved active watchlist names.
- Lookback: 45 days.
- Pricing: composite-yf.
- Official V2/Intelligence delivery enabled.
- Experimental external delivery OFF.
- Last reported V2 cash $300,000 / 0 positions.
- Experimental VRT closed; BLSH/AMD/STX/SPCX last reported open.

Verify actual process state, positions, effective config and UTC/session time.
Distinguish repository HEAD from code loaded by running processes.

PART 1 — CAPTURE EVIDENCE BEFORE MUTATION

Create a timestamped incident evidence directory.
Preserve:
- Process ownership, PIDs, start times and supervisor state.
- Latest producer heartbeat, market event and consumer activity.
- Authoritative market-health view and the ping's underlying read model.
- Relevant logs surrounding the incident and restart earlier today.
- Redis metrics, relevant key existence/TTL and counter scope.
- Provider failure taxonomy, timestamps and affected tickers.
- Current readiness, positions, pending exits and delivery states.

Use bounded reads and consistent SQLite snapshots.
Do not print credentials, destination IDs or sensitive process environments.
Do not flush Redis, reset counters or erase evidence.

If the feed has already recovered, still diagnose the incident from retained
evidence; do not reproduce an outage on the live application.

PART 2 — TRACE THE MARKET PATH

At a common UTC cutoff, establish:
provider request -> returned data -> normalized event -> publication ->
consumer receipt -> bar buffer -> strategy/exit evaluation -> health reporting

For each boundary, record:
- Latest successful timestamp and age.
- Whether the timestamp represents event time or processing time.
- Instrument coverage and failures.
- Process liveness separately from forward progress.

Inspect:
- Poll loop termination, blocking calls and request timeouts.
- Bulk versus per-symbol failures and fallback behavior.
- Retry/backoff implementation versus what the counter measures.
- Redis subscription/stream behavior actually used by each consumer.
- Heartbeat key producer, namespace, expiry and restart behavior.
- Whether one stale symbol incorrectly marks the whole feed disconnected,
  or a healthy aggregate masks unavailable symbols.
- Whether today's hotfix/restart changed any relevant behavior.

Do not infer "no retry logic" merely from a zero retry counter.
Do not infer provider rate limiting without evidence.
Do not change freshness thresholds merely to make health green.

Classify the root cause:
ACTUAL_PRODUCER_STALL /
CONSUMER_STALL /
PARTIAL_SYMBOL_COVERAGE /
TELEMETRY_DEFECT /
RECOVERED_TRANSIENT /
INSUFFICIENT_EVIDENCE

Multiple causes may coexist.

PART 3 — REGULAR-SESSION READINESS AND POSITION SAFETY

Publish one row per active ticker:
symbol | preseed result | required/valid bars | latest bar time |
READY state | first regular-session evaluation | latest evaluation |
blocking reason

Separate:
- Data/readiness-blocked tickers.
- Ready but rejected by strategy gates.
- Evaluated candidates and publications.

Zero suppression rows alone do not prove readiness blocking.
Corroborate with buffer state and actual evaluation paths.

For each currently open Experimental position:
- Verify fresh market observations reach exit evaluation.
- Record last evaluation time, price age and pending reason.
- Do not force exits, invent prices or backdate fills.

Independently verify V2:
- SEC poll freshness versus successful local database reads.
- Daily-price readiness and pending obligations.
- Continued ledger integrity.

An intraday market heartbeat failure does not automatically establish
V2 SEC/daily-price failure, or vice versa.

PART 4 — TELEGRAM AND COUNTER RECONCILIATION

Explain why the ping reports zero pushes despite the earlier acknowledged
Intelligence digest and connectivity message.

Check:
- UTC-day versus since-restart counters.
- Trading versus Intelligence versus administrative domains.
- Cards delivered versus Telegram messages.
- Durable transport acknowledgements versus volatile counters.
- Namespace/config changes after restart.

Do not resend old alerts to test this.
Do not claim a message was lost solely because a counter is zero.

For the 45 candidates:
- Identify actual counter definitions, lanes and cutoff.
- Reconcile only using preserved matching evidence.
- Label an unavailable historical breakdown UNRESOLVED.
- Do not assign the arithmetic residual to an assumed rejection class.

Fix misleading labels or aggregation if a concrete telemetry defect is
confirmed. Keep changes focused on accurate operational reporting.

PART 5 — FIX AND RECOVER IF NECESSARY

If an active implementation defect is proven:
1. Implement a narrow fix in an isolated hotfix checkout.
2. Add meaningful regression tests reproducing the failure.
3. Test recovery, restart, missing/stale data and truthful health reporting.
4. Verify exits remain independent of entry filters.
5. Keep V2 economics, scope, sizing and thresholds unchanged.
6. Preserve Experimental external-send prohibition.

For provider transients:
- Use existing supported bounded recovery/backoff.
- Do not create retry storms, overlapping polling loops or new paid sources.
- Record what recovery action actually changed.

Choose the smallest safe restart scope.
If a full restart is required, it is authorized after validation.

Deployment:
- Record current state and pre-deployment cutoff.
- Stop affected writers gracefully using ownership-safe controls.
- Verify no competing writer remains.
- Take consistent backups.
- Deploy the reviewed committed fix.
- Restart using existing approved ledger paths and configuration.
- Preserve the current session; do not invoke EOD close as a midday stop
  if it marks the day reconciled.
- Verify checkpoint daemon survival and stale stop-flag handling.

Do not edit source underneath running processes.
Do not restore a backup over legitimate post-backup writes.
Do not send synthetic trading alerts.

PART 6 — RECOVERY ACCEPTANCE

Verify over multiple actual polling/evaluation cycles:
- Market timestamps advance.
- Producer and consumer progress agree.
- Per-symbol coverage/readiness is reported honestly.
- Ping/dashboard health agrees with authoritative state.
- Open-position exit checks receive valid prices.
- V2 ledger/config/fingerprint continuity holds.
- No duplicate entries, exits or deliveries.
- One intended producer/poller and writer per ledger.
- Redis and unrelated processes remain intact.

A single heartbeat or successful HTTP response is insufficient.
A natural trading signal is not required for recovery acceptance.

If only telemetry was defective, explicitly state that underlying market
processing continued and supply the supporting timestamps.

If unresolved, report the exact affected components, positions, last-good
times and next necessary action. Do not declare generic HEALTHY.

PART 7 — JOURNAL, PUBLICATION AND EOD

Create a TASK118C task-journal entry:
- Exact prompt and final response.
- Incident timeline and root cause.
- Evidence before/after.
- Tests, implementation/deployed SHAs and restart window.
- Product impact and uncertain opportunity impact.
- Remaining issues and next research task.

Commit and push sanitized source/tests/reports on the appropriate branch.
No main merge, force-push, secrets, databases or bulk private artifacts.
Repair documentation links if needed.

If still executing at/after verified XNYS close:
python -m talonx_ops.prospective close

Expected close: 2026-09-11T20:00:00Z.
Complete by 21:30:00Z.
Preserve multi-day V2 obligations; capture final per-lane evidence.
If already beyond the deadline, close promptly and report the lateness.
If finished earlier, return the explicit operator EOD action.

FINAL RESPONSE
1. Verdict: FEED_RECOVERED / TELEMETRY_DEFECT_CONFIRMED /
   RECOVERED_TRANSIENT / BLOCKED_WITH_EVIDENCE.
2. Root cause and incident timeline, including unknowns.
3. Starting/final/deployed SHAs; runtime changed or unchanged.
4. Provider, publisher and consumer last-good/current timestamps.
5. Readiness/evaluation coverage out of 43.
6. Experimental exit and V2 continuity results.
7. Explanation for zero Telegram pushes and candidate-accounting limits.
8. Fixes/tests/restart and observed recovery evidence.
9. Remaining issues and EOD action.
10. Journal and evidence links.

Once recovery is verified, return to the bounded Task118 scope comparison.
Do not substitute increased alert volume for profitability evidence.
