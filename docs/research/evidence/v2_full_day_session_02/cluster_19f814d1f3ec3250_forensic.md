# Cluster 19f814d1f3ec3250 (ADC): forensic review

This review is read-only. No source, strategy, provider, campaign or ledger state was changed and no TalonX service was started. The ledger was read from a scratch copy of `results/prospective_2026-09-22/v2_lane.db.eod-copy`, and the insider store from a scratch copy of `~/.talonx/ingestion_ledger.db`, opened in read-only mode (`mode=ro`). Episodes were rebuilt with the frozen `talonx_v2.pipeline.detect_episodes` and the default `V2Config()`.

## 0. Repository / evidence state
- Branch `main`, HEAD `032def9877e45eb063856df9558553709d8bf590`. The tracked tree is clean. The only untracked files are Session 02 evidence and operational WAL, SHM and status files.
- `v2-paper-rc1` resolves to `a56ec8c8d10adb36a113ebd373204f297c230081`, which is an ancestor of HEAD.
- V2 fingerprint `e2acf6454789217e`, provider fingerprint `ac5e51aa3599d6c9`. Source: Session 02 `release_gate.json` and `eod_final_checkpoint.json`.
- No TalonX python process was running during the review.

## 1. Cluster facts
| Field | Value | Source |
|---|---|---|
| Symbol / issuer | ADC, Agree Realty Corp, CIK 0000917251 | ledger `processed_episodes`, insider store |
| Owner #1 | 0001528153, RAKOLTA JOHN JR (Director) | `insider_transactions` |
| Owner #2 | 0001348490, Agree Joey (President & CEO, Director) | `insider_transactions` |
| Filings in cluster (3) | 0001528153-26-000013, SEC-accepted 2026-09-02 20:05:28Z; 0001348490-26-000006, accepted 2026-09-17 11:00:24Z; 0001528153-26-000015, accepted 2026-09-17 11:00:41Z | insider store; rebuilt episode `n_filings=3` |
| Purchase code | P (OPEN_MARKET_PURCHASE), aggregate $2,600,721.60 | rebuilt episode |
| Distinct owners | 2 (minimum required: 2) | rebuilt episode |
| Activation filing date / causal ts | 2026-09-17 / 2026-09-17T23:59:59Z | rebuilt episode |
| Source timestamp (activating filing) | 2026-09-17T11:00:24Z (07:00 ET) | `accepted_at_utc` |
| Durable receipt timestamp | 2026-09-21T18:42:40.12Z (`insider_filings.ingested_at_utc`); Intelligence discovery at 18:43:14Z | ingestion ledger |
| Entry session / target entry session | 2026-09-18 (Fri), from `entry_offset_sessions=1` | rebuilt episode; ledger `eligible_entry_session` |
| Intent-creation window | Only on ticks where `today <= 2026-09-18` (`service.py:960`). Admission deadline: RTH open of 2026-09-18 (`_verify_temporal_boundary`) | code |
| Staleness cut | 2026-09-18 + 3 sessions = 2026-09-23 | frozen `max_entry_staleness_sessions=3` |
| Fresh at activation-receipt | Not stale (inside the 3-session staleness window), **but past its entry session** | as above |
| In execution scope | YES. ADC appears in the scope-filtered funnel (39 watchlist symbols, enforced) | checkpoints 1-27 |
| Liquidity history complete / prior close / 20-session MDV | NOT EVALUATED. `_eval_causal_decision` runs only inside the intent-creation window, which never opened | code; 0 intents |
| Price ≥ $5 / MDV ≥ $5M | NOT_REACHED. Filing prices were about $68-73, but the system never evaluated these gates | — |
| Corporate-action block | NO. `corporate_actions` has 0 rows | ledger |
| Account block | NO. `account_blocks` has 0 rows | ledger |
| Capacity available | YES. 0 of 20 positions used, cash $100,000 | ledger |
| Campaign existence | `V2-PAPER-RC1` was created 2026-09-21T18:38:19Z | ledger `campaign` |

## 2. Chronological timeline
| UTC | Event | Evidence |
|---|---|---|
| 2026-09-02 20:05:28 | Owner #1 Form 4 (code P) accepted by SEC | insider store |
| 2026-09-04 10:38:13 | That filing is durably received | `insider_filings.ingested_at_utc` |
| 2026-09-15 20:46 → 2026-09-21 18:42 | **No insider filing ingested on any day from 09-16 to 09-20.** The SEC ingester was not running. | ingested-per-day counts: 09-15 = 17,125; 09-16 to 09-20 = 0; 09-21 = 98 |
| 2026-09-17 11:00:24 | Owner #2 Form 4 accepted by SEC. The cluster activates on the source timeline. | insider store |
| 2026-09-18 13:30 → 20:00 | Target entry session (RTH). No TalonX process was running, no RC1 campaign existed, and the store did not yet contain the filing. | as above |
| 2026-09-21 18:38:19 | RC1 campaign created (cold start) | ledger `campaign.created_at_utc` |
| 2026-09-21 18:42:40 | Activating filings durably received (catch-up) | `insider_filings.ingested_at_utc` |
| 2026-09-21 18:45:03 | V2 tick: the episode is visible and its entry session (09-18) is before today. There is no durable PENDING intent, so it is recorded as terminal **`SKIPPED_NO_PRIOR_INTENT`**. | ledger `processed_episodes.first_seen_at` / `updated_at` |
| 2026-09-21 (Session 01 close) | Accepted as a non-economic terminal skip by the continuation verifier | `pre_full_day_cleanup/11_campaign_verification.md`, `post_rotation_go_preflight/09_campaign_verification.md` |
| 2026-09-22 06:51:39 → 20:05:41 (Session 02) | Checkpoints 1-27 list the episode as `fresh_eligible`. Each tick's `_phase_open` counts it as `no_prior_intent_skipped_this_tick=1`, and the disposition row is **not rewritten** (`updated_at` is still 2026-09-21). No intent, outbox row, position or trade exists. | checkpoints; status JSON; ledger |

## 3. Frozen decision path
| # | Step | Result | Evidence / reason |
|---|---|---|---|
| 1 | Discovery event received | **PASS, but late**: received 2026-09-21 18:42Z, 4 days after SEC acceptance and after the entry session | `insider_filings.ingested_at_utc` |
| 2 | Code-P qualification | PASS | `transaction_code='P'`, OPEN_MARKET_PURCHASE |
| 3 | Distinct-owner clustering | PASS | 2 distinct CIKs within the 10-trading-day window |
| 4 | Cluster activation | PASS | activation 2026-09-17; episode persisted in `processed_episodes` |
| 5 | Scope check | PASS | ADC is in the enforced 39-symbol scope |
| 6 | Timing / deadline (durable-intent gate) | **FAIL** | `_phase_open` (`service.py:642-661`): no PENDING intent exists and `eligible_entry_session (2026-09-18) < today`, so the result is terminal `SKIPPED_NO_PRIOR_INTENT`. The intent could never have been created because `_phase_post_close` only creates intents when `today <= eligible_entry_session` (`service.py:960`), and no RC1 tick ran on or before 2026-09-18. |
| 7 | Freshness (staleness guard) | PASS | not stale until after 2026-09-23 |
| 8 | Liquidity | NOT_REACHED | evaluated only during intent creation |
| 9 | Account / capacity | NOT_REACHED (state would have passed: 0 blocks, 0/20 used) | ledger |
| 10 | Price / provider readiness | NOT_REACHED | no SIP call for ADC entry |
| 11 | Intent admission | NOT_REACHED | `pending_entry_intents` has 0 rows (all time) |
| 12 | Reservation | NOT_REACHED | reserved $0 |
| 13 | Paper entry | NOT_REACHED | 0 positions, 0 trades |

## 4. First decisive drop point
- **Component:** `talonx_v2.service.V2Service._phase_open`, the durable-intent gate (Task 131 Directive 2, `TALONX_V2_DURABLE_STORE_ENABLED=true`). Its precondition is the intent-creation window in `_phase_post_close` (`today <= eligible_entry_session`).
- **Expected input:** a durable PENDING intent, created on a tick on or before 2026-09-18, before the 2026-09-18 RTH open.
- **Actual input:** no intent. The first tick that could see the episode ran on 2026-09-21. The filing was received at 18:42Z and the campaign was created at 18:38Z that day.
- **Expected result (frozen contract):** a late-discovered episode whose entry session has passed is never entered and is recorded terminal.
- **Actual result:** `SKIPPED_NO_PRIOR_INTENT`, terminal, written once on 2026-09-21 18:45:03Z. This matches the expected result.
- **Reason recorded by system:** "no durable PENDING intent existed before this tick's OPEN phase, and the intent-creation window has closed -- a cold-start entry is never admitted (Task 131 Directive 2; TALONX_V2_DURABLE_STORE_ENABLED=true)"

Two independent conditions each prevented entry. Either one alone was sufficient:
1. The **activating filing reached TalonX only on 2026-09-21**, after the 2026-09-18 entry session. This is a timing/receipt constraint.
2. The **RC1 campaign did not exist until 2026-09-21**. This is a cold start.

The receipt lag is the earlier one in the decision path (step 1 → step 6), so it is the decisive cause. Its root cause is environmental: the SEC ingester was offline from 2026-09-16 to 2026-09-20.

## 5. Intent-path analysis
**INTENT_PATH: NOT_REACHED.** It was stopped at the timing gate, meaning the intent-creation window (`service.py:960`) had already closed before the episode was first observable. `pending_entry_intents` has 0 rows ever, and `v2_alert_outbox` has 0 rows. Nothing was attempted, created, cancelled or lost.

## 6. Historical failure-pattern checks
| Pattern | Result | Evidence |
|---|---|---|
| scope mismatch | NO | ADC is in the enforced scope; it appears in the scope-filtered funnel |
| stale-entry misclassification | NO | disposition is NO_PRIOR_INTENT, not STALE; stale cut is 2026-09-23 |
| no_prior_intent | YES (correct) | this is the recorded and contract-correct reason |
| UTC/ET timing error | NO | accepted 11:00Z (07:00 ET) on 09-17, so the next session is 09-18 |
| source vs durable receipt error | NO (a receipt gap existed but was handled correctly) | source 09-17 11:00Z, receipt 09-21 18:42Z; the system refused a late entry and did not treat source time as admission time |
| cold-start suppression | YES (expected, contract-intended) | campaign created 09-21 18:38Z |
| liquidity history incompleteness | NOT_RELEVANT | not reached |
| provider finality unavailable | NOT_RELEVANT | not reached |
| price missing/NaN | NOT_RELEVANT | not reached |
| account/capacity block | NO | 0 blocks; 0 of 20 positions used |
| durable account block | NO | `account_blocks` has 0 rows |
| intent reservation/cash race | NO | 0 intents, cash unchanged |
| outbox/delivery-only issue | NO | no alert was due; outbox has 0 rows |
| cluster activation never persisted | NO | `processed_episodes` row exists |
| restart loss | NO | the terminal row survived from Session 01 to Session 02 unchanged |
| duplicate-owner false clustering | NO | two distinct CIKs, names and roles; owner #1's three filings count once |

## 7. Intelligence impact
**INTELLIGENCE_DEGRADATION_AFFECTED_CLUSTER: NO.** V2 reads Form 4 records from `InsiderStore` (`talonx_v2.form4_source.from_insider_store`), which is populated by the SEC ingestion service. That is the one real upstream dependency, and it is the lane whose absence from 09-16 to 09-20 caused the late receipt. The Session 02 `PROCESSING_OR_INPUT_DEGRADED` notice at 2026-09-22 13:02Z came about 18 hours after the episode was already terminal (2026-09-21 18:45Z), so it could not have affected this cluster. Intelligence card delivery is OFF in the release and does not feed V2 admission.

## 8. Legacy Quant/Brain impact
**LEGACY_QUANT_BRAIN_DISCONNECT_AFFECTED_CLUSTER: NO.** `talonx_v2` subscribes only to its own `talonx:v2:*` channels (`bus.py`; `V2Config.redis_channel_*`). Its episode input is the InsiderStore only, and nothing in `talonx_v2` references Quant or Brain channels.

## 9. Classification
**LEGITIMATE_TIMING_REJECTION**

The frozen contract correctly refused an episode whose activating filing became known to TalonX only after its target entry session (2026-09-18) and admission deadline had passed. The system's recorded reason is the cold-start form of the same rule. The campaign's cold start was also sufficient on its own, but it is not the earliest cause.

Secondary observability finding (bounded, not a correctness defect): `talonx_ops/prospective/funnel.py:158-165` classifies clusters as `fresh_eligible` using calendar staleness only. It never consults `processed_episodes`, so an episode that is already terminal (`SKIPPED_NO_PRIOR_INTENT`) is still counted as fresh-eligible. That count then drives `REVIEW_POSSIBLE_SUPPRESSION` at `funnel.py:244`. The label will persist through 2026-09-23 and clear once the episode passes the staleness cut. Session 01 evidence (`v2_full_day_session_01/README.md`) had already explained ADC this way. The Session 02 README had misstated it and has been corrected.

## 10. Release impact
**SESSION_VERDICT_UNCHANGED** (`FULL_DAY_PASS_WITH_FINDINGS`). No release-blocking defect and no bounded correctness defect. There is one observability defect (the funnel label). The environmental root cause (ingester offline from 09-16 to 09-20) is an operating-coverage fact: an insider filing that arrives while TalonX is not running can miss its entry session.

## 11. Next action
NO CODE CHANGE. Continue prospective paper validation on the same frozen release and V2-PAPER-RC1 campaign.

Optional, gatekeeper's call, not required: a later observability-only task to make the funnel exclude terminally dispositioned episodes from `fresh_eligible`. It would not change strategy, admission or accounting.
