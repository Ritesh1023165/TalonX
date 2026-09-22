# TalonX V2-PAPER-RC1 — Full-Day Session 02 (first genuine full trading day)

Date: 2026-09-22 (Tuesday, XNYS regular session)
Prior session: `docs/research/evidence/v2_full_day_session_01/` (2026-09-21, partial-day, zero trades).

| | |
|---|---|
| SESSION VERDICT | **FULL_DAY_PASS_WITH_FINDINGS** |
| ADC (`19f814d1f3ec3250`) | **LEGITIMATE_TIMING_REJECTION**. Second filing SEC-accepted 2026-09-17, received by TalonX 2026-09-21 18:42:40Z, entry session 2026-09-18 already passed, so `SKIPPED_NO_PRIOR_INTENT`. Not a defect. See [cluster_19f814d1f3ec3250_forensic.md](cluster_19f814d1f3ec3250_forensic.md). |
| PROFITABILITY VALIDATION | **NOT_COMPLETE** (0 trades) |

## 1. Release identity
- Release tag: `v2-paper-rc1`
- Frozen strategy SHA: `a56ec8c8d10adb36a113ebd373204f297c230081`
- Main SHA at session start / throughout / at close: `032def9877e45eb063856df9558553709d8bf590` (descendant of frozen SHA; only docs/tests/ops-hardening changed — PR #13 + PR #14 merged)
- V2 strategy fingerprint: `e2acf6454789217e` — matched expected all day (preflight, mid-session, final checkpoint)
- Provider contract fingerprint: `ac5e51aa3599d6c9` (`V2_RELEASE_PRICE_CONTRACT@1`, alpaca/sip/1Day/adjustment=split/fallback=NONE) — matched expected

## 2. Campaign
- Campaign: `V2-PAPER-RC1`, starting cash $100,000, allocation $10,000, execution PAPER
- Legacy $300k `v2_lane.db`: NOT touched (untouched throughout; only `v2_release_rc1.db` was written)
- Shared `notifications.db`: NOT used by this release session (isolated `v2_release_rc1_notifications.db` used throughout)

## 3. Morning preflight
- Repository: PASS (fast-forwarded d84ed23 -> 032def9; one pre-existing uncommitted tracked-file diff was identical to the version merged in PR #14, stashed and resolved cleanly by the pull, tree clean afterward)
- Campaign verify (`--verify-campaign`): PASS — clean, $100,000 settled cash, 0 positions, 0 blocks
- Release gate (`release_gate`): READY — 20/20 checks PASS
- Signal / Sentinel: READY (per prior evidence `post_rotation_go_preflight`, credentials rotated, controlled validation SENT for both destinations)
- Lab: OFF

## 4. Startup
- Start time: 2026-09-22T07:51:52+01:00 (Europe/London), via `talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram`
- Startup verdict: READY (base stack alive, V2 companion alive, checkpoint daemon alive, dashboard :8787 alive)
- Post-start preflight: `READY_WITH_FINDINGS` — sole finding was untracked operational artifacts (WAL/lock/status files created by the running process itself), not source drift (see `preflight_poststart.json`)

## 5. Ping
Not confirmed back to me in-conversation during the session; the release gate had already independently verified Signal/Sentinel delivery-validation binding as PASS before start, so this did not block the go-live decision. Treat as an open confirmation gap for process discipline next time, not a technical blocker.

## 6. Input freshness before open
- INTELLIGENCE: DEGRADED at first checkpoint (07:51:39 UTC, processing log 38,786s / ~10.8h old — consistent with the known overnight-gap pattern) -> CURRENT by later checkpoints well before/around the open.
- INSIDER STORE (Form 4 source): CURRENT throughout (`source.ok=true`, 10 code-P records seen in window).
- DISCOVERY: CURRENT (execution scope resolved to 39 watchlist symbols, `qualification: FRESH_VALID`).

## 7. Pre-open gate
PRE_OPEN_GO: YES (implicit — release gate READY pre-start, startup READY, all subsequent checkpoints HEALTHY/CURRENT with `any_critical: false` through the session).

## 8. Market session
- Official XNYS close (from runtime's own calendar-derived value): 2026-09-22T20:00:00 UTC (21:00 Europe/London)
- Full regular session observed: YES — the stack ran continuously from 07:51 UK (pre-open) through the close and into the post-close EOD grace window with zero restarts (same 14 OS processes throughout, `session.pids.json`).

## 9. Provider
- SIP: HEALTHY throughout (coverage ratio 1.0, 51 symbols priced at final checkpoint, newest tick age single-digit seconds at every checkpoint sampled)
- CSV fallback used: NO
- No provider errors/429s/stale-response events observed in any checkpoint or in `events.jsonl`

## 10. V2 funnel (session totals)
- Execution scope: 39 (watchlist-only, enforced)
- Form 4 code-P records in window: 10 (3 distinct issuers); 0 new today
- Clusters (>=2 distinct insiders): 2 (`ABCL`, `ADC`) — 1 stale (historical, correctly skipped `SKIPPED_ENTRY_STALE`), 1 labelled "fresh-eligible" by the funnel (`19f814d1f3ec3250`, ADC), which was actually already terminal (`SKIPPED_NO_PRIOR_INTENT`) since Session 01
- Single-insider near-miss: 1 (`INTC`)
- Admitted entry intents: 0; Fills: 0; Open positions: 0; Exits: 0; EXIT_UNRESOLVED: 0
- Funnel interpretation: `REVIEW_POSSIBLE_SUPPRESSION` (held steady all day). Resolved by forensic review ([cluster_19f814d1f3ec3250_forensic.md](cluster_19f814d1f3ec3250_forensic.md)): the "fresh-eligible" cluster is ADC. Its target entry session was 2026-09-18, but its activating filing only reached TalonX on 2026-09-21 18:42Z because the ingester was offline from 09-16 to 09-20. It was therefore already terminal `SKIPPED_NO_PRIOR_INTENT` from Session 01, which is **LEGITIMATE_TIMING_REJECTION**. The funnel's fresh-eligible count ignores terminal dispositions, which is an observability-only finding.

## 11. Trades
None. Zero BUY/SELL events for the entire session.

## 12. Account
- Starting cash: $100,000.00 -> Ending settled cash: $100,000.00 (unchanged)
- Reserved: $0 / Available: $100,000.00 / Occupied: 0/20 position slots
- Active blocks: 0

## 13. Corporate actions / dividends
None observed. `dividends_credited_usd`: 0.0, `dividends_accrued_usd`: 0.0. Corporate-action guard remained ACTIVE with an empty sweep log.

## 14. TalonX Signal
0 sent / 0 pending / 0 failed / 0 ambiguous (no trades occurred, so no TRADE_EVENT payloads were generated — expected, not a defect).

## 15. TalonX Sentinel
Real operational events sent via the isolated release outbox (`v2_release_rc1_notifications.db`, table `ops_notification_outbox`):
1. `STARTUP` — SENT at 2026-09-22T06:51:44 UTC (created 06:51:39 UTC)
2. `DEGRADED_HEALTH` (intelligence: `PROCESSING_OR_INPUT_DEGRADED`) — SENT at 2026-09-22T13:02:28 UTC (created 13:02:19 UTC); bracketing checkpoints (12:51 UTC and 13:21 UTC) both show Intelligence `CURRENT` with normal processing-log age, so this was a brief, self-recovered transient inside the 30-minute checkpoint gap, correctly detected and alerted, with no effect on V2 (V2's Form-4 source pipeline is independent of the Intelligence deep-processing lane and stayed `CURRENT`/`ok=true` throughout).
3. `SHUTDOWN` — PENDING (0 attempts) at close, 2026-09-22T20:05:47 UTC — see Phase 23 finding below.

STALE TEST FIXTURE ALERTS: 0

## 16. Intelligence
One brief degrade/recover cycle (see Sentinel section above), fully bounded within a single 30-minute checkpoint window, no missed approved intelligence identified, no effect on V2 trading path.

## 17. Dashboard/operator
PASS — dashboard reachable at http://localhost:8787 (HTTP 200) for the duration; `dashboard_v2_section_present` check PASS with all 8 expected sections including `v2_active_strategy`; supervisor read-model consistently reported `V2-PAPER-RC1` / PAPER / correct cash figures, never legacy $300k state.

## 18. EOD
`python -m talonx_ops.prospective close` run at 2026-09-22T21:05:47+01:00 (20:05:47 UTC), i.e. within the documented post-close grace window (close 20:00 UTC, deadline 21:30 UTC).
- Verdict: **PASS_WITH_FINDINGS**
- 19/20 named asserts PASS; `base_reconciliation`: PARTIAL — expected/documented (`no PIV reader injected (offline / not opted in)`), zero mismatches reported
- Shutdown: clean — checkpoint daemon, V2 companion, and supervisor all signalled and stopped; 0 residual TalonX processes; all 4 dashboard ports (8787/8760/8770/8501) confirmed released; `v2_lane_db_intact: true` (legacy ledger untouched); `startlock_released: true`; open V2 positions (none) preserved.

## 19. Shutdown
SHUTDOWN event: **PENDING** — created in the outbox at close time (20:05:47 UTC) but not yet delivered (0 attempts) at the moment the stack stopped, since delivery of the SHUTDOWN notice happens via a process that itself needed to be running. This reproduces the previously-documented known bounded issue verbatim: "SHUTDOWN notices may not be delivered before the stack stops." Per the frozen 2-hour STARTUP/SHUTDOWN expiry hardening, this is expected/accepted behavior, not redesigned during this session.

## 20. Findings
| Finding | Classification |
|---|---|
| Pre-existing uncommitted tracked-file diff at repo preflight (identical to PR #14 content) | ENVIRONMENT — resolved via stash+pull, no code change |
| Post-start "repo_tree_clean" finding = only WAL/lock/status operational artifacts | EXPECTED_BEHAVIOUR |
| Intelligence briefly `PROCESSING_OR_INPUT_DEGRADED` ~13:02 UTC, self-recovered within the checkpoint window | BOUNDED_FOLLOWUP (transient, correctly detected/alerted, no V2 impact) |
| One "fresh-eligible" insider cluster (ADC, `19f814d1f3ec3250`) never admitted | EXPECTED_BEHAVIOUR: LEGITIMATE_TIMING_REJECTION (entry session 09-18 passed before the filing was received on 09-21); funnel label = observability-only BOUNDED_FOLLOWUP. See the forensic file. |
| `base_reconciliation: PARTIAL` (no PIV reader) at EOD | EXPECTED_BEHAVIOUR (documented) |
| Legacy Quant signals published with zero Redis subscribers (gatekeeper-reported) | Separate from V2. The forensic review confirms `talonx_v2` uses only its own `talonx:v2:*` channels and InsiderStore input. |
| SHUTDOWN notification PENDING, not delivered before stack stop | BOUNDED_FOLLOWUP (previously known, reproduces as documented) |
| Operator did not explicitly relay a `/ping` confirmation transcript during the session | ENVIRONMENT (process-discipline gap; release gate had independently already verified delivery-validation binding pre-start) |

No RELEASE_BLOCKER findings.

## 21. Session verdict
**FULL_DAY_PASS_WITH_FINDINGS**

The frozen V2-PAPER-RC1 release ran the complete genuine XNYS regular-session lifecycle (pre-open through close and EOD) with zero restarts, zero invariant breaches, zero source/strategy/provider/accounting changes, and a clean controlled shutdown. Zero trades occurred; funnel evidence shows this was a legitimate no-opportunity/not-yet-admitted day, not a failure mode.

## 22. Profitability
PROFITABILITY VALIDATION: **NOT_COMPLETE**
Observed P&L: $0.00 realized, $0.00 unrealized, $0.00 dividends, total return $0.00 (0 trades). Campaign day 11 since 2026-09-08; prospective sample remains `SAMPLE_INSUFFICIENT` until real prospective trades accumulate. No strategy tuning performed or recommended from this single day.

## 23. Release integrity
- SOURCE CODE CHANGED: NO
- STRATEGY RULES CHANGED: NO
- PROVIDER CONTRACT CHANGED: NO
- ACCOUNTING CHANGED: NO
- Tracked source tree: clean at both preflight and close (only expected untracked operational artifacts present)

## 24. Evidence location
`docs/research/evidence/v2_full_day_session_02/` (this directory): `preflight_poststart.json`, `release_gate.json`, `checkpoint_0001_startup.json`, `checkpoint_0027_pre_close.json`, `eod_final_checkpoint.json`, `eod.json`, `lane_accounting_eod.json`, `events.jsonl`, `final_report.md`.
Raw session artifacts (not committed): `results/prospective_2026-09-22/` on the local machine, including all 27 checkpoints and `v2_lane.db.eod-copy`.

## 25. Next step
NEXT STEP: CONTINUE PROSPECTIVE PAPER VALIDATION ON THE SAME FROZEN STRATEGY RELEASE AND V2-PAPER-RC1 CAMPAIGN.
