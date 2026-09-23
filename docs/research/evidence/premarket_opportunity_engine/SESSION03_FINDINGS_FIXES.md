# Session 03 findings: root causes and fixes

**Scope:** the six findings from Session 03 (2026-09-23). None of the fixes touches a V2 strategy, provider, accounting, ledger or admission file. The strategy fingerprint stays `e2acf6454789217e` and the provider contract stays `ac5e51aa3599d6c9`.

**Commit:** `6888475`. **Tests:** `tests/test_session03_findings_hardening.py` (30 tests).

Every changed runtime file is listed in a new closed preflight list, `FREEZE_SESSION03_HARDENING_FILES`, so tomorrow's `repo_head_matches_release` stays READY. Any other runtime change is still NO_GO.

| # | Finding | Result |
|---|---|---|
| A1 | The gate said Intelligence delivery was OFF while cards were being sent | **FIXED** |
| A2 | The ADC card showed "07:00 UTC" for an 11:00:20 UTC acceptance | **FIXED** |
| A3 | Recurring `PROCESSING_OR_INPUT_DEGRADED` around 13:00Z | **Root cause established.** Cause attribution added; the alert is kept. |
| A4 | Quant published 3–4, Brain/Core received 0 | **EXPECTED_UNUSED_LEGACY_PATH**, plus a separate Experimental-lane finding |
| A5 | Discovery queue pending rose into double digits | **No defect.** Observability clarified. |
| A6 | Sentinel SHUTDOWN stayed PENDING | **FIXED** with a bounded drain |

---

## A1: the gate and the runtime disagreed on Intelligence delivery

**Root cause.** Since Task 140, `prospective start --deliver --transport telegram` injects `TALONX_INTEL_DELIVER_CARDS=1` and `TALONX_INTEL_DRY_RUN_DELIVERY=0` into the supervised Intelligence child (`talonx_ops/prospective/proc.py`). The release-gate check `intelligence_card_delivery` read only the pre-start environment, so it said OFF. Two `[INFO]` cards were then sent: ADC at 11:03Z and AFL at 13:03Z.

**Fix.**
- **One helper.** `talonx_v2/release_gate.py` now has one shared implementation, `intelligence_delivery_env_overrides()` / `intelligence_delivery_state()`. The launcher (`proc.py`) and the gate both call it, so they can no longer drift apart. The delivery behaviour itself is unchanged: the intended INFO delivery still happens.
- **Gate text.** The check now reports three values: `INTELLIGENCE DELIVERY configured=OFF runtime_requested_by_start=ON effective=ON`. It is WARN, disclosed and non-blocking, whenever the effective state is ON.
- **Start output.** `prospective start` prints the same line before launching.

**Operator semantics for tomorrow's standard start** (no explicit key in the environment):

```
INTELLIGENCE DELIVERY: configured=OFF runtime_requested_by_start=ON effective=ON
```

To keep Intelligence cards off, set `TALONX_INTEL_DELIVER_CARDS=0` before start. That gives `effective=OFF`, because an explicit key always wins.

**Isolation is preserved.** Signal (TRADE_EVENT), Sentinel (OPERATIONS) and Research remain separate. No secret is read by the state function; a test checks this.

## A2: wrong source time on Intelligence cards

**Root cause.** This is the same SEC feed behaviour PR #17 handled for V2. For roughly 5.5 hours after acceptance, the submissions JSON serves `acceptanceDateTime` as the New York wall clock labelled `Z`. The card printed the stored value as UTC: ADC showed "07:00 UTC", while the truth is 07:00:20 ET, which is 11:00:20 UTC.

**Fix.**
- **Resolver.** New `talonx_ingest/intelligence/sec_time.py`. `resolve_acceptance(raw, observed_at, filing_date)` decides which rendering the stored value was. It uses:
  - TalonX's own receipt time (`ingested_at_utc`, true UTC);
  - SEC `filingDate`, which is the ET calendar day;
  - the SEC re-render window measured in the 425-filing audit (a UTC rendering was never seen under 324.7 min; an ET rendering was never seen over 342.8 min; margins widen that band).
- **No guessing.** When only one rendering is physically and empirically possible, it is used. Otherwise the result is `AMBIGUOUS`, and the card shows `SEC filing date YYYY-MM-DD (acceptance time unverified)`.
- **Card fields.** `AlertCard` gains two additive optional fields, `filing_date` and `source_observed_at_utc`. `timestamp_utc` keeps the raw value as provenance. The concise `Source:` line and the expanded `Accepted` line render the resolved time, for example `SEC accepted 2026-09-23 07:00:20 ET (2026-09-23 11:00:20 UTC)`. Source age is computed from the resolved instant; the receipt time stays separate.
- **No effect on V2 admission.** V2 does not import the resolver (tested). V2 still uses `filing_date` from PR #17.
- **Legacy cards.** A card with no filing date whose time cannot be resolved (legacy or serialized) shows `SEC feed time … (UTC/ET rendering unverified)` with its age, never "UTC".
- **No re-sends.** Already-SENT cards will not be re-sent. The `Source`/`Accepted` lines are not material lines in `update_policy`, so a re-render classifies as a cosmetic NOOP.

**Verified on the live ledger (read-only):**

| Event | Stored value | Resolves to |
|---|---|---|
| ADC Form 4 `0001747962-26-000007` | 07:00:20Z | **11:00:20 UTC** (07:00:20 ET) |
| AFL Form 4 `0001104659-26-109827` | 09:00:07Z | 13:00:07 UTC |
| AFL 09-22 `0001104659-26-109651` | — | 16:27:06 ET (matches the independently verified SGML header) |

**Regression coverage:** EDT, EST, the spring-forward and fall-back transitions, ET-labelled-Z input, true-UTC input (late ingest), an evening filing crossing UTC midnight, and the ambiguous case.

## A3: recurring `PROCESSING_OR_INPUT_DEGRADED` at 12:55–13:02Z

**Root cause (established from `intelligence.log` and the processing table).**
- **What triggered it.** Both incidents (09-22 13:02:19Z and 09-23 12:55:43Z) were raised by the recovery pass (`reconcile_and_enrich`) reporting `timed_out=1`. That pass enriches the backlog of about 14,300 `STORED` events left by broad backfill.
- **Why it timed out.** Their comparison step fetches prior-period 10-Q documents from `www.sec.gov/Archives`. SEC returned 429s, and 5 exponential back-off retries pushed one event past its time budget.
- **The documents involved.** Every 429 on both days fell between 12:00 and 13:59Z and hit the same historical documents: ECL 2024 10-Qs (CIK 31462) and HCA (CIK 860730).
- **The live path was healthy.** In the same cycles the live path showed `polled=39 failed=0 fresh=FRESH`, delivery was `ok=True`, and V2's Form 4 path was unaffected.
- **Why the alert was misleading.** The single aggregate predicate treated a backlog-enrichment timeout the same as a live-ingestion fault.

**Not established:** why SEC throttles these fetches in that window. It could be US-morning load on `sec.gov/Archives`, or these backlog items reaching the same retry position each day. I did not invent a fix for SEC's behaviour, and no threshold was raised.

**Fix (diagnostics, not suppression).**
- **Cause codes.** The runner computes cause codes with the same predicate as before: `POLL_SYMBOL_FAILURES`, `POLL_ERRORS`, `RECOVERY_PASS_TIMED_OUT`, `RECOVERY_PASS_FAILED`, `DELIVERY_NOT_OK`, `SOURCE_<state>`. It logs them and includes them in the Operations incident.
- **Separate condition name.** When the only causes are recovery-pass causes, the incident condition is `RECOVERY_PASS_DEGRADED` (live path healthy). Otherwise it stays `PROCESSING_OR_INPUT_DEGRADED`. The incident is still raised in both cases.

**Bounded follow-up:** back off per SEC host on repeated 429s for backlog comparison fetches only, so a throttled backlog item is deferred rather than retried five times inside a cycle.

## A4: Quant published but Brain/Core received 0

**Classification:** `EXPECTED_UNUSED_LEGACY_PATH` for the counter mismatch.

**Evidence (Redis `metrics:<day>:*`, `original.log`, `experimental.log`, `exp_alerts.db` scratch copy):**
- **What was counted.** Every "Quant published" on 09-22 (13) and 09-23 (4) came from the Experimental lane's own Quant instance (`talonx_signals`, `EXPERIMENTAL_RELAXED_V1`). It publishes on the isolated channel `talonx:exp:signals:quant`, but increments the same Redis key `metrics:<day>:quant:published` that Original uses. `/ping` then printed that shared counter next to "Brain received", which Brain counts only for Original's `talonx:signals:quant`.
- **Original.** Original's Quant published 0 on both days: no `Signal:` line in `original.log`. Brain and Core were subscribed from 06:48Z, so Brain received 0, as designed.
- **09-23 Experimental signals.** The 4 signals had 1 subscriber, the Experimental lane's own consumer:

  | Time (UTC) | Symbol | Signal |
  |---|---|---|
  | 14:21 | MSTR | rsi_oversold_volume_surge |
  | 14:21 | AMD | rsi_oversold_volume_surge |
  | 15:18 | AMAT | rsi_overbought_volume_surge |
  | 16:09 | BLSH | macd_bullish_cross |

  They became Experimental paper records (MSTR, AMD and BLSH opened) and were `DRY_RUN_HELD`, not sent externally, as the Experimental external-send boundary requires. The user did not receive them. This was a **detection with deliberately no delivery**, not a delivery failure.

**Separate Experimental-lane finding:** on 09-22 all 13 signals had **zero** subscribers. The Experimental process started at 06:51Z but never logged `subscribed:` that day, while on 09-23 it did at 06:47Z. Its consumer task runs under `asyncio.gather(..., return_exceptions=True)`, so a failure before subscribing is silent and the process stays READY. The exact failure is `INSUFFICIENT_EVIDENCE`: there is no traceback in the log. This is a bounded follow-up for the Experimental lane: log task exceptions and restart the consumer. It does not affect V2 or the new engine.

**Fix:** observability only. `/ping` now reads:
- `Quant published (all lanes incl. Experimental talonx:exp:*)`
- `Quant published with zero subscribers`
- `Brain received (Original talonx:signals:quant only)`

**The new engine does not use this path:** no Redis Pub/Sub, no Quant, no Brain (tested by import scan).

## A5: Discovery informational queue

**Finding: no defect.**
- **Pending rows.** All 4 PENDING rows at EOD were `DIGEST`-route cards waiting for their digest window.
- **Expired rows.** The 3,222 rows expired on 09-23 (46,812 all-time) are months-old cards produced by the A3 backlog recovery pass. They are expired by the 24-hour DIGEST staleness cutoff (`stale_card: ~10,000h old`), which is correct.
- **Failures.** 0 failed.
- **The confusion.** `/ping` printed all-time totals, which mixed the live queue with historical expiry.

**Fix:** a read-only `talonx_ops/intel_queue.delivery_queue_breakdown()`, used by `/ping`. At 09-23 EOD it shows:

```
Discovery informational queue -- LIVE_PENDING: 4 (digest 4, oldest 859.5 min), LIVE_FAILED (24h): 0, HELD: 0
Drain -- sent 1h: 0, sent 24h: 2; EXPIRED 24h: 3222 (all-time 46,812; stale backlog cards expire by design)
Last successful discovery delivery: 2026-09-23T13:03:08.527067+00:00
```

## A6: SHUTDOWN notice left PENDING

**Root cause.** `prospective close` enqueued SHUTDOWN only after `run_close` had stopped the stack. The only drainer of the Operations outbox is the V2 companion's tick, so the notice sat PENDING until its 2-hour deadline expired it.

**Fix.**
- **Bounded drain.** Right after enqueueing, `cmd_close` runs `drain_operations_bounded()`. That is one `worker.drain(destination=OPERATIONS)` in a daemon thread with a hard 20-second join.
- **Failure modes.** A slow or unreachable Telegram cannot hang `close`: the result is `TIMEOUT` and the row keeps its normal expiry. A disabled destination leaves the row PENDING (unchanged semantics). Errors are recorded as `ERROR:<type>`.
- **Evidence.** The drain result is written into `eod.json` as `shutdown.shutdown_notice`.
- **Tests:** the timeout bound, Operations-only sending, and ordering (enqueue before drain).
