# Acceptance matrix — Task 117 output closure

`DONE` = implemented + tested in this change set · `PARTIAL` = implemented in part, remainder
documented · `DOC` = designed / analysed, not implemented (with reason) · `INCOMPLETE` = blocked
by unavailable external evidence.

## §1 Reconcile evidence before causal claims

| item | status | where |
|---|---|---|
| Sep 8 — 4 events/cards vs 6 queued rows: establish the actual relationship | DONE | `corrected_three_day_reconciliation.md` C-1 (4 filings → 5 events → 6 rows) |
| Sep 9 — 9 publications intermediate vs 16 final-day | DONE | C-2 (17:20Z snapshot = 9; EOD Experimental `WOULD_PASS` = **16**, verified in `exp_alerts.db`) |
| Sep 10 — label SHOP/BLSH/SKHY as reconstruction, no direct Redis correlation | DONE | C-3 (RECONSTRUCTED, direct correlation UNRESOLVED) |
| 94-candidate residual stays UNRESOLVED | DONE | C-4 |
| Correct the Sep 9 cleanup narrative (no termination performed) | DONE | C-5 |
| Distinguish snapshot acquisition / row update / session start times | DONE | C-6 + `issuer_identity_coverage.csv` (3 explicit columns) |
| Preserve original evidence, document corrections | DONE | `docs/audits/2026-09-10/` untouched; deltas in this bundle |

## §2 Four-hour timestamp pattern

| item | status | where |
|---|---|---|
| Inspect raw SEC timestamps + tz semantics + parser + persisted + exported | DONE | `timestamp_findings.md`, `timestamp_trace.csv` |
| Trace representative PG / V / ORCL / ADP-JPM end-to-end | DONE | `timestamp_trace.csv` (5 records + AVGO) |
| Determine cause (delay / ET-as-UTC / export-only / combo) | DONE | **Eastern wall-clock labelled UTC** (constant ~4 h offset; ORCL after-close earnings → RTH) |
| Use tz-aware America/New_York, test std + daylight; respect explicit offsets | DONE | `parse_acceptance_datetime_ex`; `test_task117_acceptance_timezone.py` (EDT, EST, both DST transitions, explicit offsets trusted) |
| Fix runtime defect + focused tests (UTC persistence / session class / pre-open / after-close / 2nd-owner activation / eligible entry / replay cutoff) | DONE | `edgar_normalize.py` + `talonx_v2/form4_source.py`; 26 tz tests + updated pipeline/normalize fixtures |
| Assess effects on historical V2 + existing records | DONE | `timestamp_findings.md` "Impact assessment" (Task 116 replay provably independent; `causal_cutoff` was the real exposure; Sep 8–10 outcomes unchanged) |
| Do not rewrite production history; migration/rebuild proposal on copies | DOC | `timestamp_findings.md` "Migration / rebuild proposal" (6 steps, not run) |
| An unchanged fingerprint is not proof of economic parity | DONE | stated; fingerprint `11107198c5b81237` unchanged AND the economic path shown independent |

## §3 Issuer identity & source coverage

| item | status | where |
|---|---|---|
| Use exact 48-row export (43 active / 5 paused / 39 V2 scope) | DONE | `issuer_identity_coverage.csv` |
| Primary-check BABA / BLSH / SKHY / SPCX (instrument, exchange, CIK, domestic vs foreign, forms, Form-4 relevance, historical status) | PARTIAL / INCOMPLETE | `issuer_identity_findings.md` — BABA (FPI+§16 exemption → CORRECT), SPCX (private/Form-D → CORRECT for F4, row likely misconfigured), BLSH (LIKELY_MIS_EXCLUSION — stale rationale), SKHY (plausibly correct). **Live EDGAR verification of BLSH/SKHY CIK filing status is not possible in this forward-dated env → INCOMPLETE.** |
| Don't equate "not covered by this adapter" with "no public filings" | DONE | all 4 have a CIK in `company_tickers.json`; noted explicitly |
| Correct misleading metadata / resolver logic in a TESTED CANDIDATE config; no silent scope enlargement | DOC | `issuer_identity_findings.md` "Tested candidate configuration" — BLSH re-classification flagged as a semantic scope change needing its own validation; BABA/SKHY/SPCX = string-only rationale upgrades |
| Establish whether `paper_trading_enabled=0` governs V2 or another lane | DONE | governs **Original** intraday/long-term paper; V2 gate is `v2_collection_scope==POLLED`, independent. No new semantics. |

## §4 Intelligence delivery through the official route

| item | status | where |
|---|---|---|
| Trace the enqueue path + missing delivery integration | DONE | `intelligence_delivery_closure.md` (drain `process_pending` never called by `runner`) |
| Keep Original long-term route + `intelligence_delivery` distinguishable | DONE | documented; different channels/consumers |
| Implement eligible-card delivery via existing transport, explicit enablement, safe HOLD default | PARTIAL | drain + `TelegramSender` + intercept tested end-to-end; **runner wiring is the non-executed activation step** (gated `deliver_intelligence_cards=False`) |
| Acceptance: newly eligible card → intercepted Telegram boundary | PARTIAL | tested in `test_delivery_pipeline.py`; live-loop wiring deferred |
| IMMEDIATE / DIGEST respected; restart preserves pending; honest retry/permanent/ambiguous; no uncontrolled repetition; no BUY framing; no duplicate poller / bypass | DONE (mechanics) | existing `test_delivery_*` + `delivery/claim_safety.py` + D2 fix |
| Backlog: inspect on isolated copy; separate backfill / fresh / update / expired; preserve audit trail; explicit age/cutoff policy; activation cannot flood; review CRITICAL individually; prepare (not run) migration steps | DONE | `intelligence_delivery_closure.md` + `expire_stale()` + `CARD_MAX_AGE_SECONDS` + `test_task117_intel_delivery_age_cutoff.py` (5 tests incl. "NOT flooded"); 23 CRITICAL rows reviewed → all stale → EXPIRED |
| Don't hardcode a policy to pass a fixture; document user-facing behaviour | DONE | 6 h IMMEDIATE / 24 h DIGEST, meaning documented; tests assert behaviour not a magic constant |

## §5 Oracle content & delivery

| item | status | where |
|---|---|---|
| Trace LT6 / LT7 / LT8 (accession, period, facts, model inputs, valuation, prior linkage, outbox, ack) | DONE | `oracle_provenance.md` (full table) |
| LT7 $175 → LT8 $165 in ~3 s from same accession: new inputs / correction / inconsistent re-run? | DONE | **repeat model execution, inconsistent estimate** — identical inputs (same accession, market_price, factors), 8 s apart, only `intrinsic_fair_value` changed |
| Different output alone ≠ meaningful evidence-based update | DONE | stated; `previous_fair_value` populated but no new input |
| Check cited backlog / figures vs actual filing period | INCOMPLETE | LLM-narrative figures, not parsed XBRL; no live EDGAR for accession `0001193125-26-387905` |
| Bounded corrections (stable event/version identity, preserve prior assessments, explicit supersedes, no repeated "new" for unchanged event, no unsupported valuation as fact) | DOC | `oracle_provenance.md` §"Bounded corrections proposed" — 5 targets, not implemented (Brain/Core path, own validation) |
| Reconcile claimed sends vs acks + aliases; store message IDs for FUTURE sends; don't claim receipt / reconstruct missing IDs | DONE (analysis) + DOC (impl) | LT6/7/8 = API-confirmed send only, no stored id; smoke test 710 is the only id; message-id capture is proposed, not backfilled |

## §6 Dashboard / accounting defects

| defect | status | evidence |
|---|---|---|
| D1 — scope the V2 funnel to the enforced allowlist | DONE | `funnel.py` `execution_allowlist="auto"`; `dashboard_acceptance.md` (scoped → `[ADC, INTC]`, unscoped → `[ADC, INTC, MUNEX, NMZ, PML]`) |
| D2 — count logical Telegram poller ownership on Windows | DONE | `supervisor.py` ancestor-dedup + token match; `test_task117_telegram_owner_dedup.py` (shim+worker = 1; two launchers = 2; mention ≠ launch) |
| D3 — current-session EOD state + truthful valuation timestamps | DONE | `dashboard_read.py` `_v2_eod_state(now=…)` + `_v2_position_lifecycle(now=…)`; prior-session row surfaced as a note, not applied |
| D4 — startup verdict matches actual state; repeat start ≠ second stack/writer | DOC | `remaining_gaps.md` — higher blast-radius; proposed fix + acceptance check |
| D6 — separate Original / Experimental / V2 counters; persist terminal dispositions + EOD counter snapshots; distinguish event identity from repeat attempts | DOC | `remaining_gaps.md` — needs Redis key change + EOD snapshot writer |
| D7 — all official delivery domains in last-send telemetry | DONE (heads-up) + corrected | `consumer.py` heads-up now writes `last_telegram_push`; long-term was already recorded (C-7) |
| Show ingestion / processing / queued / sent delivery separately; healthy poll ≠ messages sent | PARTIAL | `intelligence_delivery` `counts_by_state()` distinguishes PENDING/SENT/EXPIRED/FAILED; a dashboard tile that renders it is proposed in `remaining_gaps.md` |
| Verify on the actual SPA with isolated data + screenshots | PARTIAL / INCOMPLETE | `dashboard_acceptance.md` — no browser/screenshot tool in this session; JSON/console acceptance evidence instead |

## §7 Bounded Sep 8–10 opportunity comparison

| item | status | where |
|---|---|---|
| Per active ticker × day coverage | DONE | `ticker_day_opportunity_matrix.csv` (43 × 3 = 129 rows) |
| Separate A (informational) / B (V2 contract) / C (Original technical) | DONE | columns `A_*` / `B_*` / `C_*` |
| V2 pre-window filing lookback for clusters activated Sep 8–10 | DONE | `insider_transactions` queried 2026-07-15 → 09-11; classified by transaction_code + distinct owners |
| Don't equate every Form 4 with an open-market purchase | DONE | code distribution (P = 26 of 1,600+; S = 830; M = 316; …); only code-P counts for V2 |
| Original: distinguish missing data / failed gate / unsupported method / missing evidence; no "missed profit" from later price rise; prespecified set not selected winners; RTH vs ETH; feasible timestamps; unresolved holds + unavailable costs explicit | PARTIAL | matrix classifies every ticker-day as `FAILED_GATE` (with gate breakdown); no `SOURCE_COVERAGE_GAP`; Question-C price-outcome pass = `INSUFFICIENT_EVIDENCE` (partial bar buffer, no per-setup MTM) — stated, not fabricated |
| LOW_VOLATILITY suppressions: units/timeframe/implementation correct? repeated evals? frozen threshold selectivity? (no prod threshold change / sweep) | PARTIAL | `remaining_gaps.md` — the gate fires on ~99.8 % of bar-evaluations; a units/repeat-eval audit needs the live quant buffer + config, deferred; **no threshold touched** |
| Experimental compared separately incl. MTM + costs; internal-only is correct | DONE | `ticker_day_opportunity_matrix` notes + `corrected_three_day_reconciliation.md`; 5 open positions, no exits, MTM not computed (internal lane) |
| Final classifications used | DONE | `confirmed_misses.csv` — 22 `INFORMATIONAL_DELIVERY_MISSED`, 0 `CONFIRMED_QUALIFYING_SIGNAL_MISSED`, `INSUFFICIENT_EVIDENCE` for Original price outcomes |
| No "no opportunities missed" for unverified rows | DONE | Original Question C is `INSUFFICIENT_EVIDENCE`, not "none missed" |

## §8 Validation & publication

| item | status |
|---|---|
| Focused behaviour tests + affected regressions | DONE — see `README.md` §1 test column; consolidated run in `remaining_gaps.md` |
| Rerun exact-runtime replay if timestamp/eligibility affects economics | DONE — Task 116 replay path shown independent of the fix (parquet, no `edgar_normalize`); 168 V2/research tests green incl. Task 116 |
| Production ledger + protected state unchanged; Redis retained; no external messages; no processes left running | DONE — `v2_lane.db` md5 `29e57dbc…`; Redis PONG, not flushed; 0 sends; 0 app processes |
| Publish sanitized deliverables under `docs/audits/task117_output_closure/` | DONE |
