# V2 39-stock missed-opportunity audit (Session 02 / 2026-09-16 → 09-22)

This is a read-only forensic and economic review. There were no source, strategy, provider, accounting, campaign or notification changes. Release `v2-paper-rc1` (frozen `a56ec8c8`), strategy fp `e2acf6454789217e`, provider fp `ac5e51aa3599d6c9`, campaign `V2-PAPER-RC1` (PAPER), audited at main `1ae4d11`.

## Executive conclusion: `ZERO_ALERTS_EXPLAINED_WITH_INGESTION_MISSES`

Session 02's zero alerts are fully explained, and **no implementation suppression was found**.

- **No opportunity was actionable during Session 02.**
  - Across all 39 enforced symbols, SEC shows **no** code-P filing accepted from 2026-09-18 through the end of 09-22.
  - The only V2 cluster visible in Session 02 was ADC. Its entry session (09-18) had already passed, and its disposition was already terminal from Session 01.
  - For Session 02 itself, this is category A: no qualifying opportunity existed in its actionable window.
- **Inside the audit window there was one genuine opportunity: ADC `19f814d1f3ec3250`.** It was **missed because insider ingestion was offline from 2026-09-16 to 09-20** (category C).
  - The CEO's activating Form 4 was SEC-accepted 2026-09-17 11:00:24 ET, before the 09-18 open.
  - TalonX received it only at 2026-09-21 18:42:40Z.
  - The frozen rules then correctly refused a late, cold-start entry.
  - This was also before the campaign existed (created 2026-09-21 18:38Z).
- **No category D (implementation defect) and no category E (alert lost in delivery):** 0 intents, 0 V2 outbox rows, 0 positions ever.
- **Economic impact of the miss (HYPOTHETICAL):** 146 ADC shares at the $68.27 open = $9,967.42. Marked at the final 09-21 close of $67.62 that is **−$94.90 (−0.95%)**; the exit (10-02 close) is not reached yet. The only other cluster in the runtime's 45-day lookback, ABCL (pre-deployment, 08-17 entry), would have made **+$159.12 (+1.59%)**, also HYPOTHETICAL.

## 1. Answers to the summary questions

| # | Question | Answer |
|---|---|---|
| 1 | Symbols (of 39) with any code-P activity | **3** in the 45-day lookback (ABCL, ADC, INTC; 9 filings). **1** in 09-16..09-22 (ADC; 2 filings) |
| 2 | Valid 2-owner clusters | **2** (ABCL `07242bc857569f60`, ADC `19f814d1f3ec3250`). 1 in the core window (ADC) |
| 3 | Received by TalonX on time | **0** |
| 4 | Correctly rejected (system response correct) | **2** (ADC `SKIPPED_NO_PRIOR_INTENT`, ABCL `SKIPPED_ENTRY_STALE`), both after a late receipt |
| 5 | Missed due to ingestion downtime | **2** (ADC: downtime 09-16..09-20; ABCL: ingestion not yet deployed). **1** in the core window. Both pre-campaign |
| 6 | Should have been admitted (frozen executable rules) | **0**. Neither was received before its entry-session open. Both *would* have passed liquidity if received on time |
| 7 | Intents actually created | **0** |
| 8 | Fills | **0** |
| 9 | Implementation defects (V2) | **0** |
| 10 | Valid alerts generated but not delivered | **0** (0 generated) |
| 11 | What the missed opportunities would have earned (HYPOTHETICAL) | ADC −$94.90 (−0.95%) open, marked at 09-21. ABCL +$159.12 (+1.59%) closed. Net +$64.22 on $19,956.62 (+0.32%) |
| 12 | Does the evidence explain Session 02's zero alerts? | **Yes.** Nothing was actionable on 09-22, and the one in-window opportunity (ADC) had been lost to ingestion downtime days earlier |

Details: [UNIVERSE.md](UNIVERSE.md), [OPPORTUNITY_LEDGER.md](OPPORTUNITY_LEDGER.md), [ECONOMIC_OUTCOMES.md](ECONOMIC_OUTCOMES.md). Data extracts are in `extracts/`.

## 2. ADC cross-check (Task L)

The earlier conclusion stands:
- cluster `19f814d1f3ec3250`
- classification **LEGITIMATE_TIMING_REJECTION**
- operational category **MISSED_DUE_TO_INGESTION_DOWNTIME**
- system response **CORRECT**

The only correction is the timestamp label (erratum E1 below). It changes no conclusion.

## 3. Findings

| ID | Finding | Classification |
|---|---|---|
| F1 | **`insider_transactions.accepted_at_utc` holds SEC's New York wall-clock time labelled UTC.** SEC EDGAR submissions JSON `acceptanceDateTime` (e.g. AFL `0001104659-26-109651`: `2026-09-22T16:27:06.000Z`) is the same instant EDGAR's Atom feed reports as `2026-09-22T16:27:06-04:00`. TalonX copies the JSON value verbatim. Corroboration: across 542 filings since 09-01, the minimum SEC→TalonX receipt lag computed from the stored value is 241–245 min, a constant 4-hour (EDT) floor, with 0 negative lags. **V2 decision impact: none.** The activation date is SEC's ET filing date, which is the correct US convention. The dissemination-before-open check (`service.py:1232`) cannot flip, because the entry session is the next session and EDGAR closes at 22:00 ET. The binding receipt check uses `ingested_at_utc`, which is true UTC. **Evidence impact:** lags and "SEC time" in forensic documents are off by 4h (EDT) / 5h (EST). | BOUNDED_FOLLOWUP (data labelling, ingestion lane; no code change in this task) |
| F2 | Insider ingestion was not running from 2026-09-16 to 09-20 (3 trading days). 81 Form 4s for the 39 names (accepted 09-16..09-18) were received about 64–122 h after true SEC acceptance on the 09-21 catch-up, including ADC's trigger. | ENVIRONMENT / operating coverage |
| F3 | Insider ingestion first ran on 2026-09-04, so filings before that were only backfilled (ABCL). | ENVIRONMENT (pre-deployment history) |
| F4 | The funnel's `fresh_eligible` count ignores terminal dispositions (known). | BOUNDED_OBSERVABILITY_FOLLOWUP (unchanged) |
| F5 | The SHUTDOWN Sentinel notice stays PENDING at stop (known). | BOUNDED_FOLLOWUP (unchanged) |

**Erratum E1** (applies to `v2_full_day_session_02/cluster_19f814d1f3ec3250_forensic.md`, which is not edited here because it is outside this task's allowed diff): "SEC-accepted 2026-09-17T11:00:24Z (07:00 ET)" should read **11:00:24 ET = 15:00:24Z**. The SEC→TalonX receipt lag is **4 d 3 h 42 m**, not 4 d 7 h 42 m. The same applies to the other SEC acceptance times quoted there, which are all ET. Entry session, disposition, classification and verdict are unchanged. `prospective_validation/` has been updated to state that `accepted_at_utc` is ET.

## 4. Observability certainty (Task M)

| Level | Items |
|---|---|
| **PROVEN** | The 39-symbol universe (companion logs, both sessions). The code-P set and all Form 4 counts: the store matches SEC EDGAR for all 39 CIKs (95 filings at SEC since 09-16 = 89 in store + 6 accepted after the last poll/stop, with 0 errors), and the 6 post-stop filings are non-P. The 2 clusters (the frozen engine matches the ledger IDs). Ledger state: 0 intents, 0 V2 outbox rows, 0 positions or trades, $100,000 cash. TalonX receipt timestamps. Insider ingestion first ran 09-04. 0 filings ingested 09-16..09-20. SEC timestamps are ET-labelled (Atom `-04:00`). Liquidity, sizing and hypothetical P&L on FINAL SIP bars. ADC's only dividend ex-date is before entry. |
| **STRONGLY_INFERRED** | TalonX was **not running at all** 09-16..09-20. Basis: no prospective session dir, zero ingestion rows, and last 09-15 checkpoint 20:27Z / first 09-21 checkpoint 18:42Z; there is no between-session process log. Polling was continuous inside Session 02 (30-minute checkpoints plus the final poll heartbeat). The heartbeat is overwritten and there is no per-poll history. That the SEC JSON is complete (the cross-check uses the same SEC source as the ingester; the Atom feed was spot-checked for one issuer only). |
| **UNKNOWN** | The exact ingester stop/start instants between sessions. The 09-22 SIP bar is PROVISIONAL (fetched before the finality time 09-23 00:16Z), which affects context prices and the ADC provisional mark only. ADC's hypothetical final outcome (exit 2026-10-02). Filings for the 39 accepted after the cross-check (~21:05Z 09-22); these will be picked up by the next morning start. |

## 5. Method (reproducible, read-only)

1. Universe from the companion `execution scope ENFORCED` log line.
2. Filings: a scratch **copy** of `~/.talonx/ingestion_ledger.db` opened `mode=ro` (`InsiderStore()` writes its schema on open, so never open the live file). Joined `insider_transactions` ↔ `insider_filings` for `accepted_at_utc` / `ingested_at_utc`.
3. Clusters: frozen `talonx_v2.form4_source.from_insider_store` + `talonx_v2.pipeline.detect_episodes` with `V2Config()` defaults, `since = 2026-09-22 − 45 days` (the live `--live-lookback-days 45`), restricted to the 39 symbols.
4. Ledger: `v2_release_rc1.db` opened `mode=ro`.
5. Operating coverage: `results/prospective_*/checkpoints` plus `eod.json`, and ingestion-by-day counts.
6. SEC cross-check: read-only GETs to `data.sec.gov/submissions/CIK*.json`, the EDGAR Atom feed and filing XML, using the ingester's configured User-Agent at ≤7 req/s.
7. Prices: read-only GETs through the frozen `AlpacaSipBarAdapter` (SIP, 1Day, split); liquidity, sizing and exit via frozen `liquidity` / `sizing`; dividends via the frozen `AlpacaCorporateActionSource`.

Nothing was written to any TalonX database, and no TalonX service was started.

## 6. Next step

**ADD CONTINUOUS INGESTION COVERAGE AS AN OPERATIONAL REQUIREMENT FOR PROSPECTIVE VALIDATION.** The only in-window opportunity was lost to 3 unrun trading days. Then continue prospective validation on the same frozen release and campaign. No code change is required by this audit. F1 (the timestamp label) is a candidate bounded follow-up for the ingestion lane, to be decided at review.
