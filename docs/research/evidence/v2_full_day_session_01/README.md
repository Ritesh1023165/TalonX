# FIRST FULL-DAY END-TO-END PAPER SESSION - frozen release v2-paper-rc1 (2026-09-21)

## SESSION VERDICT: FULL_DAY_PASS_WITH_FINDINGS  -  **with a mandatory coverage qualification**

> **This was a PARTIAL-day session, not a full-day one.** The task was picked up at 18:37 UTC on 2026-09-21, i.e. 5.1 h after the 13:30 UTC XNYS open
> (1.4 h before the 20:00 UTC close). The operator was asked and explicitly chose to launch immediately rather than hold for the next pre-open.
> The verdict label is the closest of the five permitted classes: it describes the **infrastructure** result for the ~78-minute window that was run
> (start 18:42:19Z, session runtime 18:42:30Z-20:06:22Z incl. 20:00Z close). **The full-day validation itself (pre-open -> open -> close, with pre-open intent
> creation) has NOT been performed and remains outstanding.**

| | |
|---|---|
| RELEASE TAG / FROZEN SHA | `v2-paper-rc1` / `a56ec8c8d10adb36a113ebd373204f297c230081` |
| MAIN | `0130a13` (descends from the frozen SHA; only docs/tests/pin differ) |
| V2 STRATEGY FINGERPRINT | `e2acf6454789217e` (verified by gate, preflight, checkpoint) |
| PROVIDER CONTRACT | `V2_RELEASE_PRICE_CONTRACT@1` / `ac5e51aa3599d6c9` (Alpaca SIP, 1Day, split-only, fallback NONE) - CSV FALLBACK USED: NO |
| CAMPAIGN | `V2-PAPER-RC1`, PAPER, $100,000 / $10,000, ledger `v2_release_rc1.db`; LEGACY $300K CAMPAIGN TOUCHED: NO (md5 `cff00b0f...` unchanged) |
| MARKET SESSION | 2026-09-21, normal close (13:30-20:00 UTC, 6.50 h, from the exchange calendar) |
| RELEASE GATE | READY, 18/18 PASS, 0 WARN (pre-open) and again inside the companion at start |
| TRADES | 0 (see funnel) |
| ACCOUNT AT END | cash $100,000.00; reserved $0; available $100,000.00; 0 open; 0 EXIT_UNRESOLVED; 0 pending intents; 0 blocks; realized P&L $0; 0 dividend receivables |
| EOD_RECONCILIATION | PASS_WITH_FINDINGS (all V2 asserts PASS; base reconciliation PARTIAL = no PIV reader, mismatches=[]) |
| PROFITABILITY VALIDATION | NOT_COMPLETE |
| SOURCE CODE CHANGED DURING SESSION | NO (HEAD 0130a13 throughout; no tracked file modified) |
| STRATEGY RULES / PROVIDER CONTRACT CHANGED | NO / NO |

## Zero-trade interpretation (funnel evidence, Task J)
Not a failure and not "no opportunity". Of the 10 code-P Form 4 records in the 45-day window (3 issuers):
- **ADC - a genuine >=2-distinct-insider cluster** (2nd distinct owner filed 2026-09-17 -> eligible entry session 2026-09-18). Episode `19f814d1f3ec3250` = `SKIPPED_NO_PRIOR_INTENT`:
  no durable pre-open intent existed because V2 was not running on 09-18 / this morning; the frozen rule "a cold-start entry is never admitted" (Task 131 Directive 2) correctly refused a chase.
  Category **B/operational (timing)**: a valid opportunity was missed only because the service was not live pre-open. Nothing was weakened.
- ABCL: stale historical cluster (eligible 2026-08-17, > 3 sessions) - `SKIPPED_ENTRY_STALE`. INTC: single insider (near-miss).
- No account/campaign safety block, no provider outage, no implementation defect (categories C, D, E: none).
The funnel's `REVIEW_POSSIBLE_SUPPRESSION` is explained by ADC above.

## Findings (none is a release blocker)
| # | finding | class |
|---|---|---|
| 1 | Session start drained **9 stale `RECONCILIATION_FAILURE` rows to the real TalonX Sentinel channel**: fixture data (episode `ep1`, campaign `V2`), created 2026-09-18 by earlier test runs writing to the shared production `notifications.db`, sat unsent and were sent at 18:42:48Z. **Operator: ignore those 9 Sentinel messages.** Root cause = test isolation of the ops outbox | BOUNDED_FOLLOWUP (test hygiene; a purge/isolation step should precede the next start) |
| 2 | Sentinel STARTUP text labels the campaign `V2` (start path reads campaign id from an env dict that lacks it); SHUTDOWN correctly says `V2-PAPER-RC1` | BOUNDED_FOLLOWUP (cosmetic) |
| 3 | Operator checkpoint `campaign` block shows legacy constants (start_date 2026-09-08, campaign_day 10, day1_outcome NO_NATURAL_V2_SIGNAL) | BOUNDED_FOLLOWUP (presentation; ledger/gate/dashboard all show V2-PAPER-RC1) |
| 4 | `close` stopped the stack before the SHUTDOWN Sentinel event was delivered: row left `PENDING` (drains at next start) | BOUNDED_FOLLOWUP |
| 5 | `close` writes the release ledger copy to the fixed name `v2_lane.db.eod-copy` (and `v2_service_status.eod.json`); content is the release ledger, name is legacy | BOUNDED_FOLLOWUP (naming) |
| 6 | Sentinel `DEGRADED_HEALTH intelligence: PROCESSING_OR_INPUT_DEGRADED` at 18:45Z; Intelligence log was ~5.9 days old at start, fresh (25 s) by 20:05Z; earlier `market feed STALE` pre-start event recovered to HEALTHY | EXPECTED_BEHAVIOUR / ENVIRONMENT (Sentinel surfaced it correctly) |
| 7 | Checkpoint-1 event listed ADC as a single-insider near-miss although the filing history has 2 distinct owners (cluster reported at checkpoint 2) | BOUNDED_FOLLOWUP (checkpoint event timing; terminal funnel/close were correct) |
| 8 | `/ping` was rendered from the live status file (V2 section correct) but I cannot send a Telegram command as the operator; a `/ping` typed in TalonX Signal should be confirmed by the operator. `/ping` wording says "broad-discovery-inclusive" while broad discovery is not enabled (funnel: broad_discovery_included=false) | BOUNDED_FOLLOWUP / operator confirmation |
| 9 | **The Telegram bot token appears in clear in the companion's httpx INFO request log** (`results/prospective_2026-09-21/logs/v2_companion.log`, 22 lines; `results/` is gitignored, and the token is redacted in the evidence copy). Consider rotating that bot token and lowering httpx log level before the next start | BOUNDED_FOLLOWUP (security hygiene) |
| 10 | CPU/RAM not captured (process liveness and heartbeat only) | limitation |

## Signal / Sentinel
- Signal (TalonX Signal): 0 V2 alerts (no trade, none manufactured); V2 alert outbox 0 rows; no Intelligence card delivery (OFF).
- Sentinel: STARTUP (SENT), 9 stale test rows (SENT, finding 1), DEGRADED_HEALTH intelligence (SENT), SHUTDOWN (PENDING). No account block / provider / reconciliation incident this session.

## Provider
34 ticks at 150 s on SIP; 0 provider errors / 429 / timeouts / stale / fallback in the companion log; `pricing_unavailable_recent` empty; market-data health OK throughout; corporate-action guard ACTIVE, 0 splits/dividends/unsupported observed.

## Checkpoints
18:42Z startup - 18:44Z post-start - 19:05Z - 19:35Z - 19:58Z pre-close - 20:05Z after close - 20:06Z EOD close - final. Every checkpoint: 3/3 processes alive, heartbeat fresh, ledger unchanged
(cash 100,000, 0 positions), dashboard v2_active_strategy HEALTHY / NO_OPPORTUNITIES on campaign V2-PAPER-RC1 (never the legacy $300k), legacy ledger md5 unchanged.

## Next step
CONTINUE PROSPECTIVE PAPER VALIDATION ON THE SAME FROZEN RELEASE AND CAMPAIGN - with the **genuine full-day session** started before the next pre-open (e.g. 2026-09-22 before 13:30 UTC).
Do NOT re-run `--init-campaign` (the campaign exists; verify with `--verify-campaign`). Before that start, address finding 1 (stale Sentinel rows) operationally.

## Files
`00_calendar_and_time.txt`, `01_campaign_initialization.json`, `02_release_gate_preopen.json`, `03_prospective_preflight_preopen.txt`, `04_baseline_before_launch.txt`, `05_start_command_output.txt`,
`06_ping_v2_section_startup.txt`, `07_close_command_output.txt`, `checkpoint_*.json` (read-only snapshots), `operator_session_artifacts/` (operator EOD report, eod.json, events, logs).
No secrets are recorded.
