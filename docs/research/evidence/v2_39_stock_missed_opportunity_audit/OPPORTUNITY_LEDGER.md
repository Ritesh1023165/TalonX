# Opportunity ledger: every code-P filing and every cluster for the 39 symbols

> **CORRECTION (2026-09-22, SEC filing-date release-fidelity fix; see `../v2_sec_filing_date_release_fix/TIMESTAMP_SEMANTICS.md`).**
> The first version of this file labelled the stored `accepted_at_utc` values as New York (ET) time. That was
> wrong for every code-P filing below: all 9 were ingested after SEC had re-rendered `acceptanceDateTime` to
> true UTC, so the stored values are UTC. The tables now show the true ET time with the UTC value in brackets.
> The corrections are: ABCL activation **12:04:25 ET** (not "16:04:25 ET"), ADC activation **07:00:24 ET = 11:00:24Z**
> (not "11:00:24 ET = 15:00:24Z"). No filing date, entry session, disposition or classification changes.

The method is anti-hindsight, taken in this order: universe → contemporaneous filings → frozen rules → admission outcome → economics (in [ECONOMIC_OUTCOMES.md](ECONOMIC_OUTCOMES.md)). No symbol was selected because of its price move.

Rules applied are the frozen executable behaviour (`V2Config()` defaults, `talonx_v2.pipeline.detect_episodes`, `talonx_v2.liquidity.evaluate_liquidity`, `talonx_v2/service.py` admission gates):
- code `P` (`OPEN_MARKET_PURCHASE`)
- at least 2 distinct owner CIKs within 10 trading days
- activation = the filing date bringing in the 2nd distinct owner; entry = the next session (`entry_offset_sessions=1`)
- a buy intent only on a tick with `today <= entry session`, strictly before the entry-session RTH open, **and** TalonX receipt (`ingested_at_utc`) before that open (`service.py:960`, `:1149-1261`)
- no cold-start entry (`service.py:642-661`)
- staleness 3 sessions
- liquidity: last close ≥ $5 and 20-session median dollar volume ≥ $5M, using sessions strictly before entry
- whole-share fee-inclusive sizing on a $10,000 allocation with the zero-fee frozen assumption; entry at the entry-session open, exit at the close 10 sessions later

**Doc vs code:** no discrepancy found for the rules exercised here. One timestamp-labelling finding (F1) affects evidence arithmetic only; see README.

All times below are shown as **SEC acceptance in New York time (ET)**, with the true UTC in brackets (corrected; see banner). TalonX receipt is true UTC.

## 1. All code-P filings for the 39 symbols (45-day lookback, 2026-08-08 → 2026-09-22)

From `extracts/filings_clusters_ledger.json` → `codeP_filings`. Cross-checked against SEC EDGAR: no code-P filing for these 39 names is missing from the store (`extracts/sec_edgar_crosscheck.json`).

| # | Symbol | Owner CIK | Owner | Accession | SEC accepted, ET (true UTC) | TalonX receipt (UTC) | Amendment |
|---|---|---|---|---|---|---|---|
| 1 | ABCL | 0001352908 | Hayden Michael R | 0001628280-26-057007 | 2026-08-14 11:50:16 (15:50:16Z) | 2026-09-04 10:18:49 | no |
| 2 | ABCL | 0001834411 | Booth Andrew | 0001834411-26-000008 | 2026-08-14 12:04:25 (16:04:25Z) | 2026-09-04 10:18:49 | no |
| 3 | INTC | 0001008463 | TAN LIP BU | 0000050863-26-000177 | 2026-08-14 16:27:15 (20:27:15Z) | 2026-09-04 12:50:49 | no |
| 4 | ABCL | 0001834423 | Montalbano John S. | 0001834423-26-000008 | 2026-08-18 14:45:24 (18:45:24Z) | 2026-09-04 10:18:49 | no |
| 5 | ABCL | 0001352908 | Hayden Michael R | 0001628280-26-058684 | 2026-08-24 17:21:48 (21:21:48Z) | 2026-09-04 10:18:49 | no |
| 6 | ADC | 0001528153 | RAKOLTA JOHN JR | 0001528153-26-000011 | 2026-08-31 07:00:11 (11:00:11Z) | 2026-09-04 10:38:14 | no |
| 7 | ADC | 0001528153 | RAKOLTA JOHN JR | 0001528153-26-000013 | 2026-09-02 16:05:28 (20:05:28Z) | 2026-09-04 10:38:13 | no |
| 8 | ADC | 0001348490 | Agree Joey | 0001348490-26-000006 | 2026-09-17 07:00:24 (11:00:24Z) | 2026-09-21 18:42:40 | no |
| 9 | ADC | 0001528153 | RAKOLTA JOHN JR | 0001528153-26-000015 | 2026-09-17 07:00:41 (11:00:41Z) | 2026-09-21 18:42:40 | no |

Code-P filings inside the core window 2026-09-16..09-22: **2** (rows 8 and 9, both ADC, both 09-17).

Other Form 4 activity in the core window: 87 non-P filings (sales, awards, tax withholding, exercises, gifts and similar), which are not V2 inputs. The 6 Form 4s accepted on 09-22 after the stack stopped (AFL, DELL ×3, NVDA, STX) were read directly from SEC: their codes are S, J and M, none is code P, and none can seed a 09-23 opportunity.

## 2. Clusters (frozen `detect_episodes`, 45-day lookback, 39-symbol scope)

The frozen engine returns exactly **2** episodes. These are the same two IDs the runtime recorded in `processed_episodes`.

| Field | ABCL `07242bc857569f60` | ADC `19f814d1f3ec3250` |
|---|---|---|
| Owner 1 / owner 2 | 0001352908 (Hayden) / 0001834411 (Booth) | 0001528153 (Rakolta) / 0001348490 (Agree, CEO) |
| First filing (ET) | 2026-08-14 11:50:16 | 2026-09-02 16:05:28 |
| Activating (2nd-owner) filing (ET) | 2026-08-14 12:04:25 (16:04:25Z) | 2026-09-17 07:00:24 (11:00:24Z) |
| Activation date / causal ts | 2026-08-14 | 2026-09-17 |
| TalonX receipt of activating filing | 2026-09-04 10:18:49Z (poll; first day insider ingestion ever ran) | 2026-09-21 18:42:40Z (poll catch-up) |
| Intended entry session / RTH open | 2026-08-17 / 13:30Z | 2026-09-18 / 13:30Z |
| Receipt before entry-session open? | NO (+18 days) | NO (+3 sessions) |
| TalonX operating in actionable window | NO. Insider ingestion first ran 2026-09-04; no prospective session existed. | NO. No session between 09-15 20:27Z and 09-21 18:42Z; 0 filings ingested 09-16..09-20. |
| Campaign existed at entry session | NO (campaign created 2026-09-21 18:38:19Z) | NO |
| Liquidity (if it had been evaluated) | PASS: close $11.38, MDV $32.4M | PASS: close $68.16, MDV $93.6M |
| Ledger disposition (PROVEN) | `SKIPPED_ENTRY_STALE` | `SKIPPED_NO_PRIOR_INTENT` |
| Intent / outbox / position | none / none / none | none / none / none |

Single-owner near-miss (no cluster): **INTC**. One code-P owner (0001008463, 2026-08-14) and no second distinct owner within 10 trading days, so it fails at step 2 (distinct owners).

## 3. Sequential frozen-rule evaluation (first decisive rule only)

| Step | ABCL | ADC | INTC |
|---|---|---|---|
| 1 Code-P | PASS | PASS | PASS |
| 2 Distinct owners ≥2 | PASS | PASS | **FAIL** (1 owner) |
| 3 Scope | PASS | PASS | not reached |
| 4 Timing: intent window `today <= entry`, before RTH open | **FAIL** (first TalonX tick able to see it: 2026-09-21) | **FAIL** (first tick able to see it: 2026-09-21) | not reached |
| 5 Durable receipt before RTH open | FAIL (downstream, not counted) | FAIL (downstream, not counted) | not reached |
| 6 Freshness | FAIL (stale; downstream) | PASS | not reached |
| 7 Liquidity | not reached (would PASS) | not reached (would PASS) | not reached |
| 8 Provider readiness | not reached | not reached | not reached |
| 9 Account/capacity | not reached (0 blocks, 0/20 used) | not reached | not reached |
| 10 Intent admission | not reached | not reached | not reached |

The other 36 symbols had **no code-P filing** and stop before step 1.

## 4. Classification (taxonomy from `prospective_validation/README.md` §2)

| Unit | Count | Top-level | Subreason |
|---|---|---|---|
| 36 symbols with no code-P filing | 36 | `NO_QUALIFYING_CLUSTER` | NO_CODE_P_ACTIVITY |
| INTC | 1 | `NO_QUALIFYING_CLUSTER` | SINGLE_OWNER_NEAR_MISS |
| ADC `19f814d1f3ec3250` | 1 | `MISSED_DUE_TO_INGESTION_DOWNTIME` | PRE_CAMPAIGN; ingester offline 09-16..09-20. System response after late receipt: CORRECT (`LEGITIMATE_TIMING_REJECTION`, unchanged from the Session 02 forensic) |
| ABCL `07242bc857569f60` | 1 | `MISSED_DUE_TO_INGESTION_DOWNTIME` | PRE_CAMPAIGN; INGESTION_NOT_YET_DEPLOYED (insider ingestion first ran 2026-09-04). Outside the 09-16..09-22 core window; included because it is inside the 45-day lookback the runtime evaluated in Session 02. System response: CORRECT (`SKIPPED_ENTRY_STALE`) |
| `RECEIVED_ON_TIME_REJECTED_BY_RULE` | 0 | | |
| `RECEIVED_ON_TIME_ADMITTED` | 0 | | |
| `RECEIVED_ON_TIME_FILLED` | 0 | | |
| `LATE_SOURCE_OR_LATE_RECEIPT_CORRECTLY_REJECTED` | 0 | | |
| `IMPLEMENTATION_DEFECT` | 0 | | |

## 5. Suppression and delivery checks (Tasks G/H)

- **Should have been admitted under the frozen executable rules:** 0. Neither cluster was received before its entry-session open, so admission was contractually impossible. Neither is an implementation suppression.
- **Intent path:** NOT_REACHED for both. `pending_entry_intents` has 0 rows ever.
- **Alerts:** 0 V2 actionable alerts were generated (`v2_alert_outbox` has 0 rows), so 0 were generated and not delivered. The release Sentinel outbox holds only STARTUP, DEGRADED_HEALTH (Intelligence) and SHUTDOWN (PENDING), none trade-related. There is no delivery-loss path to examine.
