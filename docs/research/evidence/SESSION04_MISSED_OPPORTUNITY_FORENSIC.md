# Session 04 (2026-09-24): missed-opportunity forensic review (Stage A)

- **Baseline:** `main` at `696370e`, which includes PR #19 and PR #20.
- **Status:** Stage A, analysis only. No product code was changed to produce this report.
- **Machine-readable evidence (gitignored):** `results/session04_forensic/`
  - `forensic_analysis.json`: every classified row.
  - `replay/observations.db`: per-scan, per-symbol causal observations.
  - `market/day_summary.json`, `market/movers_1m.json`, `market/extended_hours.json`: hindsight market data.
  - Scripts: `forensic_replay.py`, `market_day.py`, `analyze.py`.
- **Access:** every runtime database was opened read-only (`mode=ro`), and nothing was hand-edited.

**Verdict: `FORENSIC_ANALYSIS: PASS_WITH_FINDINGS`**

---

## 1. Session 04 verified baseline

Every figure was re-read from the raw evidence, not from earlier summaries.

| Item | Verified value | Source |
|---|---|---|
| Premarket config | `PREMARKET_RESEARCH_V1` `62ba413daf85e674`; 1 run, end state `DONE` | `runs` table |
| Eligible universe | 5,653 of 14,384 | scan funnel |
| Scans | 41, first 08:15:00Z, last 13:25:00Z, **0 at or after 13:30Z** | `scans` table |
| Provider | `PROVIDER_COMPLETE` on all 41; 0 gaps; 0 failed batches; 0 retries; 0 errors | `funnel_json.provider`, `errors_json` |
| Candidate identities | 174: 25 NEW alerts (6 later lifecycle-INVALIDATED), 149 `SUPPRESSED_*` | `candidates` |
| Alert events | 76 SENT, 149 SUPPRESSED | `alerts.delivery_state` |
| Lab outbox (09-24) | 76 rows, all `SENT` on attempt 1 | `premarket_research_notifications.db` |
| Outcomes of the 25 | 7 CONFIRMED, 10 FAILED_CONFIRMATION, 8 INVALIDATED | `outcomes` |
| V2 | 0 trades, 0 positions, 0 intents, 0 account blocks; 2 processed (historical, `SKIPPED_*`) episodes | `v2_release_rc1.db` (ro) |

One identity count needs explaining: 174 identities map to 173 symbols, because **BB** had both a GAP_UP and a GAP_DOWN identity.

## 2. Methodology

### 2.1 Causal view: what V1 could know at each scan

`results/session04_forensic/forensic_replay.py` re-ran 2026-09-24 through the **unchanged** V1 engine:
- same config and fingerprint
- same code path
- replay mode, nothing routed

It also persisted what the live engine keeps only in memory: every symbol's per-scan observation, including hard-gate and data-readiness rejection reasons.

**Replay vs live parity**

| Check | Result |
|---|---|
| Identities | 173 of 174 live identities reproduced |
| Final state | 169 of 173 identical |
| Replay-only identities | 4 (FUL, HLN, INFQ, WRD) |
| Live-only identities | 1 (ACB) |
| Delivered set | 2 swaps at the cap boundary (live CRDL and EXC; replay JAGX and WRD) |

The differences come from SIP bars that were revised after the fact: late-reported prints changed scores near the 40-point line. Because of this:
- The **live DB is authoritative** for candidates.
- The replay is used **only** to explain why a non-candidate was not detected.

### 2.2 Hindsight view: what the market actually did

`market_day.py` uses the same economic contract as the canary: Alpaca SIP, split-adjusted, 1-minute and 1-day bars.
- **Coverage:** all 5,653 eligible symbols, 04:00–16:00 ET (0 fetch errors, 171 requests).
- **After-hours and overnight:** fetched for the movers.

**Validation:** re-running the frozen `outcomes.measure()` on this data reproduces the live outcome table for the **25 delivered candidates exactly (25 of 25 identical)**.

### 2.3 Pre-registered definitions

These were fixed before the results were inspected.

**Meaningful mover:** an eligible symbol whose largest move versus the previous close, at any point from 04:00 to 16:00 ET, was **≥ 5%**. There were 1,357 identity rows, covering 1,356 symbols.

**Realistically actionable:**
- passes the frozen hard gates: previous close ≥ $1 and 20-session ADV ≥ $1M;
- and regular-session dollar volume ≥ $1M.

**Categories.** Each row gets exactly one, in this precedence order:

| Order | Category | Applies to | Rule |
|---|---|---|---|
| 1 | **C** DETECTED_THEN_INVALIDATED | Candidates | Live lifecycle `INVALIDATED` before the open: the \|gap\| fell below 1% pre-open. All 6 were delivered first. |
| 2 | **A** DETECTED_AND_SENT | Candidates | The NEW alert was SENT. |
| 3 | **B** DETECTED_BUT_SUPPRESSED_BY_CAP | Candidates | `SESSION_NEW_ALERT_CAP` |
| 4 | **H** NOT_REALISTICALLY_ACTIONABLE | Non-candidates | Fails the frozen price or liquidity gate, recomputed on the day's own data. |
| 5 | **F** DATA_OR_PROVIDER_LIMITATION | Non-candidates | Fetch failure, `UNKNOWN` hold, `INSUFFICIENT_DAILY_HISTORY` or `MISSING_PREVIOUS_SESSION_BAR`. |
| 6 | **E** EMERGED_AFTER_09_30_ET_AND_V1_COULD_NOT_DISCOVER | Non-candidates | No pre-open scan ever saw \|gap\| ≥ 2% (the frozen WATCH gap), **and** the ≥ 5% move first printed after the last scan's data horizon (13:10Z / 09:10 ET). Sub-reason `AFTER_09_30_ET` (321 rows) or `09_10_TO_09_30_ET_AFTER_LAST_SCAN_DATA_ASOF` (1 row). |
| 7 | **G** FILTER_OR_SCORING_REJECTION | Non-candidates | Observed pre-open, but a frozen hard gate or the WATCH rule rejected it (WATCH needs \|gap\| ≥ 2% **and** score ≥ 40 in the same scan). |
| 8 | **D** AVAILABLE_DURING_SCANNING_BUT_NOT_DETECTED | Non-candidates | Residual. |

`NO_PREMARKET_PRINTS` at the 08:15Z scan is not a rejection. Nothing is complete yet at that point, for any symbol.

**Terminology:**
- **Hindsight mover:** a symbol that moved ≥ 5%.
- **Causally detectable:** V1 produced, or would have produced, a worthy observation from data available at scan time.
- **Realistically actionable:** as defined above.

A move later in the day is not called a "missed opportunity" by itself.

## 3. Complete opportunity classification

All counts are identity rows.

| Category | All rows (1,439) | Hindsight movers (1,357) | **Actionable movers (558)** |
|---|---:|---:|---:|
| A DETECTED_AND_SENT | 19 | 14 | **13** |
| B DETECTED_BUT_SUPPRESSED_BY_CAP | 149 | 73 | **69** |
| C DETECTED_THEN_INVALIDATED | 6 | 5 | **5** |
| D AVAILABLE_DURING_SCANNING_BUT_NOT_DETECTED | 2 | 2 | **2** |
| E EMERGED_AFTER_09_30_ET_AND_V1_COULD_NOT_DISCOVER | 356 | 356 | **322** |
| F DATA_OR_PROVIDER_LIMITATION | 1 | 1 | **1** |
| G FILTER_OR_SCORING_REJECTION | 209 | 209 | **146** |
| H NOT_REALISTICALLY_ACTIONABLE | 697 | 697 | 0 |

### Observations

- **H (697).** 269 rows have a previous close under $1 and 428 have ADV under $1M. Half of all ≥ 5% movers are penny or illiquid names, which the frozen gates correctly exclude.
- **When actionable movers first reached ≥ 5%:**
  - REGULAR session: 424
  - PREMARKET: 106
  - never on a bar close (intrabar extreme only): 28
- **E (322 actionable) is the largest gap.** It is structural:
  - Of these, 192 had some pre-market prints, but never a gap of 2% or more.
  - The other 130 had no pre-market prints at all.
  - V1 stops scanning at the open (`talonx_premarket/__main__.py:204-205`), so none of them could be discovered.
  - Magnitudes: 265 moved 5–10%, 40 moved 10–20%, and 1 moved more than 20%.
- **G (146 actionable).** 146 is the unique-symbol count. Some symbols recorded rejections under more than one gate, so the figures below add up to more than 146.
  - **`STALE_PREMARKET_PRICE`** (last pre-market print more than 45 minutes older than the data as-of): 108 symbols. In 80 of them the stale-rejected observation already showed a WATCH-sized gap (≥ 2%). This frozen data-quality gate is the main pre-open filter loss, concentrated in thinly traded pre-market names. Examples: SVRN +59.8%, QMCO +23.5%, TJGC +22.6%, SCTX −19.5%.
  - **Never met WATCH (≥ 2% gap and score ≥ 40 in the same scan):** 36 symbols. Examples: YDES (gap 4.95%, score 10.5 on $3k of pre-market volume, then +67% in the regular session); DBGI (best score 41.2, but that came at a 1.05% gap).
  - **`INSUFFICIENT_LIQUIDITY`, as computed by the engine's own window:** 2 symbols (AVX, MNTK).
- **D (2):** FUL and INFQ. Both were worthy in the replay but have no live identity. This is live/replay drift; they are not demonstrated live misses.
- **F (1):** ETRA, `INSUFFICIENT_DAILY_HISTORY`.
- **Signals before 04:00 ET** (overnight and previous after-hours, section 5):
  - **100 actionable-mover symbols** had a ≥ 2% move versus the previous close before 04:00 ET.
  - 73 of them were visible in 09-23 after-hours (SIP).
  - 61 were visible in overnight BOATS.
  - Of these 100: 12 ended up A, 28 B, 4 C, 18 E and 38 G.

### Representative rows

The full per-row fields are in `forensic_analysis.json`: symbol, first meaningful timestamp and phase, price and previous close, % moves, pre-market, regular and ADV dollar volume, catalyst, `candidate_id`, score and class, sent or suppressed, outcome, and exact reason.

| Cat | Symbol | Prev close | Max up / down | Close | First ≥ 5% (UTC) | Pre-open max \|gap\| | Reason |
|---|---|---:|---|---:|---|---:|---|
| E | DNA | 8.58 | +21.7 / −4.1 | +19.7% | 13:44 REGULAR | 1.69 | never ≥ 2% pre-open |
| E | TWST | 158.50 | +16.9 / −1.4 | +16.1% | 13:49 REGULAR | 1.44 | never ≥ 2% pre-open |
| E | GDDY | 96.38 | +14.5 / −1.7 | +4.6% | 14:24 REGULAR | 0.44 | never ≥ 2% pre-open |
| E | AGL | 84.56 | −1.6 / −14.7 | −10.3% | 14:03 REGULAR | — (no pre-market prints) | undiscoverable pre-open |
| G | SVRN | 32.55 | +59.8 / −6.1 | +27.6% | 11:42 PREMARKET | 6.14 | `STALE_PREMARKET_PRICE` |
| G | QMCO | 25.97 | +23.5 / −3.4 | +13.4% | 13:36 REGULAR | 2.39 | `STALE_PREMARKET_PRICE` ×4 |
| B | SRZN | 16.16 | +121.9 / +2.1 | +108.2% | 10:55 PREMARKET | 86.0 | cap (first seen 11:35Z, BULLISH, score 72) |
| B | GLND | 2.91 | +93.8 / −4.1 | +83.2% | 11:36 PREMARKET | 7.90 | cap |
| B | PFSA | 2.05 | +122.0 / −5.4 | +47.3% | 11:30 PREMARKET | 106.8 | cap (BULLISH, score 85; FAILED_CONFIRMATION, 30m −13.2%) |
| A | GCTK | 2.03 | +148.8 / +3.9 | +27.1% | 08:00 PREMARKET | 132.0 | sent (BULLISH, 98.8; FAILED_CONFIRMATION, 30m −40.6%) |

## 4. Delivered vs cap-suppressed (A2)

The frozen scores, classes and `measure()` outcome rule were used throughout; no new score was introduced. Returns are direction-adjusted to the alert reference price.

| | Delivered 25 | Cap-suppressed 149 | Suppressed, setups only (10) |
|---|---|---|---|
| First score, median (p25–p75) | 49.3 (43.7–61.1) | 42.4 (41.0–46.5) | — |
| First type | WATCH 20, BULLISH 4, BEARISH 1 | WATCH 139, BULLISH 8, BEARISH 2 | — |
| First seen (UTC hour) | **all 25 at 08:30** | 08: 19, 09: 31, 10: 21, 11: 25, 12: 40, 13: 13 | — |
| Catalyst present | 11 | 57 | 5 |
| Median pre-market $ at first sighting | $2.08M | $1.10M | — |
| In V2 scope | 0 | **7** (AMD, DELL, INTC, MSTR, ORCL, SHOP, VRT) | 1 (ORCL) |
| ≥ 5% hindsight movers | 19 | 73 | 10 |
| Outcome C / FC / INV | 7 / 10 / 8 | 36 / 41 / **72** | 3 / 4 / 3 |
| +30m mean / median | −1.95 / −0.89 | −1.48 / −1.54 | +0.97 / −3.88 |
| Close mean / median | −4.06 / −2.26 | −2.02 / −2.37 | +1.74 / −1.37 |
| MFE / MAE median | +1.06 / −4.31 | +0.56 / −4.37 | +8.44 / −10.44 |

### How the cap allocated attention

- The cap filled completely at 08:30Z, the first scan with any data. Delivery then followed score order within that one scan. 144 of the 149 suppressed identities were first seen **later**.
- **121** suppressed identities had a first score above the lowest delivered score (40.61).
- **11** scored 60 or more, which is setup grade: PFSA 85.0, AIXI 79.2, NCPL 74.5, SKYQ 74.3, SRZN 72.0, GRAL 69.9, YMAT 69.4, BIDU 67.0, ORCL 65.3, DRI 65.0, BB 61.1.
- **8 BULLISH and 2 BEARISH setups** were never delivered, while 20 generic WATCH alerts from 08:30 were.

### Answer

> **Did the 25-cap mostly create a delivery/attention problem, or did the underlying scanner itself also miss important candidates?**

**Both, and the scanner's gap is larger.**

- **The cap is a delivery and attention problem.** First-scan allocation used all 25 slots on the thinnest pre-market data (04:30 ET). It then discarded every later identity, including 10 setups, 11 identities scoring ≥ 60, and all 7 V2-scope names. As a group, though, the suppressed candidates were **not** better: 24% CONFIRMED against 28% for the delivered 25, and 48% gap-filled within 30 minutes against 32%. The cap cost *attention*, not demonstrated edge.
- **The scanner itself misses far more actionable movers than the cap hid.**
  - **Cap:** 69 actionable movers suppressed (B).
  - **Architecture:** 322 actionable movers emerged after V1's last data horizon (E). This is structural: scanning stops at the open.
  - **Filters:** 146 were rejected by frozen filters (G), 108 of them by `STALE_PREMARKET_PRICE`.
  - **Detected:** V1 caught only 87 of 558 actionable movers (A + B + C), or 16%.

Nothing here is a profitability claim. The outcome columns describe a single session.

## 5. Post-open and extended-hours analysis

- **Regular session.** 424 of the 558 actionable movers first reached ≥ 5% during regular hours. For 322 of them there was no pre-open evidence, so V1 was blind by construction.
- **Previous after-hours** (09-23, 16:00–20:00 ET, SIP). 555 of 557 actionable-mover symbols printed, and **73** were already ≥ 2% from their close.
- **Overnight** (20:00–04:00 ET). SIP returns **no bars** (verified). The only overnight source on this subscription is **BOATS** (Blue Ocean ATS):
  - It is **single-venue**, so it is not the consolidated SIP contract.
  - Only 201 of 557 actionable-mover symbols had any BOATS bars, with a median of **4 bars** per night (p90 85).
  - 61 showed ≥ 2% versus the previous close.
- **09-24 after-hours.** This session was still running when the data was pulled (window to 21:24Z). Ten actionable movers had moved ≥ 5% further by then: AIXI, AKAM, BENF, BMM, GLND, JELD, NCPL, SVRN, VOGX, YMAT. A complete after-hours pass is pending (`market_day.py ah` after 00:16Z).

### Provider capability, demonstrated on this subscription (probes 2026-09-24)

| Phase | Feed | Result |
|---|---|---|
| PREMARKET 04:00–09:30 ET | SIP | Complete, 15-minute delay (the whole session) |
| REGULAR | SIP | Complete, 15-minute delay |
| AFTER_HOURS 16:00–20:00 ET | SIP | Bars present, 15-minute delay; data newer than now − 15 min returns `403` |
| OVERNIGHT 20:00–04:00 ET | SIP | **No bars** |
| OVERNIGHT | BOATS | Historical and 15-minute-delayed bars present (no `403` at now − 16 min); **recent returns `403`**; single-venue and sparse |
| any | `overnight` | `HTTP 400 invalid feed` |
| any | IEX | Real-time, but effectively no extended hours (1 bar in the last 60 minutes of after-hours) |

## 6. M1 root cause (Experimental lane silent)

**Classification: multiple separate issues.**

**1. Consumer absent. This is the M1 defect.**
- `talonx_signals/run.py:565-570` starts four tasks on one event loop: the Experimental scanner, the directional consumer (`consume()` at `:267-276`), the dashboard and the intelligence bridge.
- `consume()` calls `pubsub.subscribe()` **once, with no retry**.
- The tasks have **no done-callback or supervision**. They are gathered only at shutdown, with `return_exceptions=True` (`:580`). A consumer that raises or hangs before subscribing is therefore invisible.
- Evidence from the lane's own log (`results/task100b_runtime_integration/_supervisor_logs/experimental.log`), correlated with `exp_alerts.db`:

| Lane start date | Starts | `subscribed:` logged | Directional alerts that day |
|---|---|---|---|
| 09-08 / 09 / 10 / 11 / 14 | 8 | yes | 57, 108, 116, 81, 74 |
| 09-15 | 5 | **no** | 0 |
| 09-21 | 1 | **no** | 0 |
| 09-22 | 1 | **no** | 0 |
| 09-23 | 1 | yes | 101 |
| **09-24** | 1 | **no** | **0** |

- On 09-24 the Experimental scanner still produced quality-gate candidates (`exp_quant.db` `suppression_counts`: LOW_CONFLUENCE 107, LOW_RISK_REWARD 8, TREND_GATE 6), and it logged **17 `Signal PUBLISHED with ZERO subscribers on talonx:exp:signals:quant`**.
- **The trigger is undetermined.** The swallowed exception or hang left no trace. No Redis error was logged by any component at 05:22. No commit between 09-14 and 09-15 changes the lane's startup: Task 135 `66a49f9` only added the subscriber-count warning, which made the problem visible.

**2. The CONTROL strategy generated no event. This is expected, not a defect.**
- CONTROL Brain and Core subscribed to `talonx:signals:quant`, and Dispatch to `talonx:quant:rejected`.
- CONTROL Quant published **0 signals** on 09-24: LOW_VOLATILITY rejected candidates 24,559 times and LOW_CONFLUENCE 12 times.
- So Brain, Core and Dispatch receiving zero is correct. This matches Task 93, where the volatility gate rejected 92.8%.

**3. Metrics ambiguity.**
- Both `QuantScanner` instances (CONTROL and Experimental) increment the **same** Redis counters, `metrics:{date}:quant:*`, via `talonx_quant/consumer.py:417` (`_incr_metric(..., "quant", ...)`).
- `/ping`'s QUANT section (`talonx_dispatch/telegram_listener.py:793-830`) shows Experimental `published_no_subscriber` with the text "likely never reached Brain", even though Brain never subscribes to `talonx:exp:*`.
- Another section (`:906`) already labels the counter "all lanes incl. Experimental".

### Redis inventory

Built from the actual 09-24 subscription lines and the code.

| Channel | Producer | Intended subscriber(s) | Actual 09-24 subscribers | Owner / purpose | Status |
|---|---|---|---|---|---|
| `talonx:market:stream` | yfinance poller (Original) | Quant (CONTROL and Experimental), Paper, fundamental consumer, Experimental price cache | CONTROL Quant, Paper ×2, fundamental, Experimental Quant | legacy 43-name live feed | active, legacy |
| `talonx:signals:quant` | CONTROL Quant | Brain, Core, Experimental consumer | Brain, Core (Experimental absent) | Original strategy | active (0 signals on 09-24) |
| `talonx:quant:rejected` | CONTROL Quant | Dispatch, Experimental consumer | Dispatch | Original diagnostics | active |
| `talonx:exp:signals:quant` | Experimental Quant | Experimental consumer | **none** | Experimental lane | **broken (M1)** |
| `talonx:exp:quant:rejected` | Experimental Quant | Experimental consumer | **none** | Experimental lane | **broken (M1)** |
| `talonx:exp:paper:trades` | Experimental paper | Experimental Quant | Experimental Quant | Experimental lane | active |
| `talonx:reports:brain` | Brain | Core | Core | Original | active |
| `talonx:alerts:dispatch` | Core | Dispatch, Paper | Dispatch, Paper | Original | active |
| `talonx:paper:trades`, `talonx:alerts:longterm`, `talonx:paper:trades:longterm`, `talonx:reports:longterm`, `talonx:signals:fundamental` | Original paper and long-term modules | Dispatch, Quant, Core | as intended | Original | active, legacy |
| `talonx:filings:events`, `talonx:fundamentals:events`, `talonx:news:events` | Original ingest | Brain, fundamental consumer, Quant | as intended | Original | active, legacy |
| `talonx:v2:*` | Task 110 V2 bus | none in the release path; the V2 release companion uses SQLite plus the notify outbox | — | historical Task 110/111 | historical only |
| `talonx:piv:*` | PIV lane | PIV consumers (opt-in only) | not running | PIV | historical and opt-in |
| `talonx:gateway:alpaca:*` | Alpaca gateway (Task 92) | PIV | not running | PIV | historical and opt-in |

## 7. General market-data (yfinance) failure root cause

- **Caller.** `talonx_ingest/market_data/yfinance_poll.py` runs inside `run_talonx.py` (the Original stack, provider `YFINANCE_POLLING`).
- **Load.** It calls `yf.Ticker(sym).fast_info` for **43 symbols every 12 seconds** (`TALONX_YF_POLL_INTERVAL`), about **4,800 cycles** on 09-24. yfinance version is 1.6.0.
- **Failures.** **55 cycles (about 1.1%) came back fully degraded**, with 0 of 43 symbols returning data (one had 8 of 43). They were spread through the day, from 11Z to 20Z. Each produced about 42 per-symbol `PROVIDER_SCHEMA_ERROR: 'currentTradingPeriod'` errors (**2,309 in total**; Yahoo returned a throttled or incomplete payload) plus **52** `Too Many Requests` errors.
- **Retry.** Each degraded cycle was isolated ("1 consecutive"), backed off 1–3 seconds, and the next cycle succeeded. The retry behaviour is sensible.
- **Why the count looked huge.** `provider_requests_failed` is incremented **once per symbol** (`:299-300`), so one upstream throttle event counts as about 43 "failures". Expected throttling is also categorised as a *schema error*.
- **Coverage impact.** The feed supplies **only** the legacy CONTROL and Experimental Quant lanes (43-name watchlist). The Pre-market Research engine (Alpaca SIP), V2 (Alpaca SIP daily, contract `ac5e51aa3599d6c9`) and Intelligence (SEC EDGAR) do not use it.
  - Missing about 1% of 12-second polls has a negligible effect on 1-minute bars.
  - **No Research or V2 candidate coverage was affected.**
- **Correction to an earlier draft.** An earlier draft claimed a 13–16Z blackout in CONTROL Quant. That was **withdrawn**: `quant.db` `bar_buffer` is a rolling retained buffer (about 120 bars per symbol), not an ingestion log.
- **The V2 Alpaca contract is not to be changed** because of this.

## 8. Intelligence delivery root cause

| Symptom | Classification | Evidence |
|---|---|---|
| **No Intelligence card SENT on 09-24** | **Operational coverage gap plus notification scheduling weakness** (not a code correctness defect) | 10 cards on 09-24 came from filings dated 09-23 or later (verified; `intelligence_delivery` joined to `text_events`). **7 were `IMMEDIATE`/HIGH**: 6 ORCL Form 4s and 1 NVDA Form 4, all filed 09-23 after the close. They were enqueued on the **04:22Z morning catch-up** and immediately `EXPIRED` by `stale_card` at **9.0–11.5 h old by event time, over the 6 h IMMEDIATE cutoff** (`delivery/config.py:78`). The stack was stopped from the 09-23 EOD close until 04:22Z, so they aged out before TalonX was running. There is no fallback: an item too old for IMMEDIATE is not re-routed to DIGEST, and DIGEST is disabled anyway (next row). The remaining 3 were `DIGEST` (below). |
| **Fresh DIGEST rows stayed PENDING** (ACHR Form 4; ACHR 8-K Reg FD, band HIGH; VRT 8-K Reg FD) | **Notification scheduling weakness (by configuration)** | Digest sending is **disabled by default**: `talonx_ingest/intelligence/service/config.py:143` `deliver_digest_enabled=False`, and `TALONX_INTEL_DELIVER_DIGEST_ENABLED` is unset in `.env`. `last_digest_sent_utc` is `2026-09-15T00:07:54Z`. DIGEST rows can only age out, via the 24-hour cutoff (`delivery/config.py:79`). A HIGH-band card therefore never reaches the operator unless it is IMMEDIATE-eligible. |
| **About 3,956 historical cards enqueued, then EXPIRED, on 09-24** (3,352 on 09-22, 3,228 on 09-23) | **Expected backlog behaviour, with a wasteful path** | The recovery reconciliation (`service/runner.py:419`) makes orphaned historical events discoverable. Enrichment then calls `enqueue_card` (`service/enrichment.py:417`) **without an event-age check**, and `expire_stale` (`delivery/outbox.py:883`) expires each row in the same cycle. Every row is a distinct event with attempts = 0, so **nothing was sent**. Backlog remaining: **10,277** events at stage `STORED` (23,798 already processed through recovery), which is roughly 2–3 more running days of churn. |
| Correctness defect? | **No.** Nothing stale was sent and no fresh card was dropped by a bug. | — |

This is separate from V2 trade delivery. V2 `TRADE_EVENT` had no activity (0 rows), and routing stayed isolated.

## 9. Issues ranked

"Strategy?" means the fix changes strategy semantics. "Reports?" means the issue affects reports or calculations.

| # | Sev. | Issue | Evidence | Root cause | Component | Strategy? | Reports? | Recommended action |
|---|---|---|---|---|---|---|---|---|
| 1 | **HIGH** | Discovery stops at the regular open | 322 of 558 actionable movers were in E; 0 scans after 13:30Z | `run_session` breaks at open (`__main__.py:204`); `scan_schedule` covers pre-market only | `talonx_premarket` | No, for the discovery loop. REGULAR / AFTER_HOURS classification needs a **new versioned config** | Yes: coverage and missed-opportunity counts | B1 continuous phase-aware discovery |
| 2 | **HIGH** | The notification cap constrained surfaced visibility and later lifecycle delivery. It did **not** limit raw detection: 174 identities were detected and recorded (25 NEW delivered, 149 cap-suppressed). | The 149 were persisted as `SUPPRESSED_*`, then **frozen**: never re-evaluated, updated or invalidated (`engine.py`: suppressed identities are skipped), and never outcome-tracked. 10 setups and all 7 V2-scope names were never surfaced. | The notification cap is evaluated inside the lifecycle decision (`alerts.py:72`), coupling attention capacity to candidate lifecycle | `talonx_premarket` | No, if scoring is preserved | Yes: lifecycle, alert counts, and outcomes of suppressed identities | B3 contract: detection and durable persistence must never depend on Telegram capacity. B4 moves the budget to a separate notification layer |
| 3 | **HIGH** | Experimental directional consumer silently absent (M1) | 8 of 9 starts since 09-15 never subscribed; 0 alerts on those days; 17 ZERO-subscriber publishes on 09-24 | Unsupervised task, single subscribe attempt, `return_exceptions` at shutdown only | `talonx_signals/run.py` | No | Yes: Experimental evidence loss; `DETECTED_BY_EXPERIMENTAL` uninformative | Supervise tasks, retry subscribe, expose health, or retire the lane (B9 decides) |
| 4 | MEDIUM | Quant metrics mix CONTROL and Experimental | Shared `metrics:{date}:quant:*`; `/ping` says "never reached Brain" | Hard-coded stage `"quant"` for both scanners | `talonx_quant/consumer.py:417`, `telegram_listener.py:826` | No | Yes: operator metrics | Lane-prefixed stage, or remove the Experimental metrics when the lane is retired |
| 5 | MEDIUM | `STALE_PREMARKET_PRICE` hard gate rejects thin pre-market names | 108 actionable G movers, 80 of them with a gap ≥ 2% when stale-rejected | Frozen 45-minute staleness gate | V1 config | **Yes** if changed | Yes: G counts | **No change in this refactor.** Record as evidence; any change is a new config version, pre-registered |
| 6 | MEDIUM | No live overnight capability | SIP has no overnight bars; BOATS is single-venue and sparse | Provider entitlement | data | No | Yes: coverage claims | B2: OVERNIGHT = `NOT_SUPPORTED` (SIP) or `DEGRADED_SINGLE_VENUE` (BOATS), never fabricated |
| 7a | MEDIUM | IMMEDIATE Intelligence cards for after-close filings expire before the morning start | 7 HIGH IMMEDIATE cards (ORCL ×6, NVDA) EXPIRED at 04:22Z, 9.0–11.5 h old against the 6 h cutoff | Stack not running overnight, plus no downgrade path for an aged IMMEDIATE card | Intelligence service schedule; `delivery/config.py:78` | No | Yes: notification metrics | Continuous runtime (B6) keeps ingestion and notification up overnight. Surface expired-by-age counts. Any cutoff or re-route change is a versioned notification-policy decision |
| 7 | MEDIUM | DIGEST delivery disabled, so HIGH-band DIGEST cards are never surfaced | 3 fresh cards PENDING at shutdown; last digest 09-15 | `deliver_digest_enabled=False` default | Intelligence delivery | No | Yes: notification metrics | Surface on dashboard/status; the enable decision is an operator notification-policy choice (not changed silently) |
| 8 | LOW | Stale historical cards enqueued, then expired | About 3.9k per day | No age check at enqueue on the recovery path | `enrichment.py:417` | No | Store noise only | Skip enqueue when already past the age cutoff (record `DONE` + reason) |
| 9 | LOW | yfinance failure counts inflated | 2,309 schema errors from 55 degraded cycles | Per-symbol counting; throttle categorised as schema error | `yfinance_poll.py` | No | `/ping` only | Count degraded cycles and classify as throttle; the component is legacy (B9) |
| 10 | LOW | Live/replay SIP revision drift near the score boundary | 2 delivered swaps; 4 replay-only identities | Late-reported SIP prints | data | No | Replay reproducibility | Document; replay is explanatory only |
| 11 | LOW | Canary heartbeat is not written during a scan or the post-scan sleep | 83.6 s and 514 s observations | Status is written only between scans | `talonx_premarket/__main__.py` | No | No | B6 per-component heartbeat |
| 12 | LOW | Supervisor Original metadata stale (`started_at` 09-23) | checkpoint | Metadata file not refreshed | `talonx_ops` | No | No | B10 |
| 13 | LOW | `base_reconciliation: PARTIAL` | known | No PIV reader | `talonx_ops` | No | No | Unchanged (accepted) |

**CRITICAL:** none. No V2 strategy, account, ledger or routing breach was found.

## 10. Defect classes

- **Architecture defects:** #1 discovery stops at open; #2 notification cap coupled to the candidate lifecycle (detection itself was not capped); #3 unsupervised consumer tasks; #11 heartbeat.
- **Operational defects:** #3 (its operational face: the lane runs blind with no alarm); #7a (stack stopped overnight, so after-close IMMEDIATE cards expire before the morning start); #12.
- **Notification policy:** #2 (first-scan allocation); #7a (no downgrade path for aged IMMEDIATE cards); #7 digest disabled; #8 stale enqueue.
- **Data limitations:** #6 overnight; #10 SIP revisions; the E share is partly data (no pre-market prints for 130 E rows).
- **Strategy and filter quality:** #5 staleness gate; the 36 below-WATCH rejections; outcome quality (the 25 delivered: 28% confirmed). **None is changed in Stage B.**
- **Metrics:** #4, #9.

## 11. Stage B implementation plan

**Principles:**
- V2 is untouched: strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9`, campaign `V2-PAPER-RC1`, no reinitialisation.
- `PREMARKET_RESEARCH_V1` stays frozen and reproducible: its engine, replay and fingerprint are unchanged.
- The new behaviour is versioned side by side.
- Paper only, no new paid provider, and no threshold or weight chosen from 09-24 outcomes.

**Branch:** `feature/continuous-opportunity-engine`, from `696370e`.

### B1. Continuous discovery: new package `talonx_opportunity/`

It reuses `talonx_premarket` features, scoring and alerts **by import**; V1 is not edited.

- **Phase model.** `phase_at(t)` returns OVERNIGHT, PREMARKET, REGULAR, AFTER_HOURS or CLOSED, from the XNYS calendar (early closes included).
- **Discovery loop.** It runs whenever the process runs, with a per-phase cadence. It never breaks at the open.
- **Phase-aware features.** Session-to-date window versus the previous close. This is the same feature definitions and frozen weights and thresholds, applied to the current phase's bars.
- **Versioning.**
  - PREMARKET-phase classification is **identical** to V1. A test asserts equal outputs on the same bars.
  - REGULAR and AFTER_HOURS use the same frozen weights and thresholds under a new pre-registered config, `CONTINUOUS_RESEARCH_V1`, with its own fingerprint. It is defined a priori with no outcome tuning, and documented as new semantics.
- **Identity.** One identity per session date, symbol and direction family, persisted across phases, with a lifecycle event log. A phase change never creates a new identity.

### B2. Provider capability registry

`capabilities.py` records, per phase: provider, feed, delay, adjustment, completeness and execution eligibility. Each record is persisted and shown on the dashboard.
- **OVERNIGHT:** SIP is `NOT_SUPPORTED`. BOATS is `DEGRADED_SINGLE_VENUE`; it is off by default and never mixed into the SIP contract. The module continues without it.

### B3. Uncapped durable candidate store

- **Schema.** New tables: `candidates`, `candidate_events` (append-only lifecycle), `observations_summary` and `notification_decisions`.
- **Isolation.** A separate DB under `results/opportunity/<date>/`, never a protected V2 DB.
- **No cap state.** Detection never writes `SUPPRESSED`.

### B4. Notification policy `LAB_NOTIFY_POLICY_V1`

It is versioned, configurable, phase-aware and fingerprinted, and it reads the candidate store.
- **Priority:** BULLISH / BEARISH above WATCH.
- **Budgets:** separate per-phase budgets for setups and for WATCH, so WATCH cannot exhaust setup capacity.
- **Budget values:** kept at today's total of 25 per session as the default, and split evenly across phases *by rule, not by outcome*. The values are configuration, not evidence-derived.
- **MATERIAL_UPDATE:** only for candidates already surfaced, using V1's frozen delta thresholds.
- **INVALIDATED:** notified only if the candidate was surfaced.
- **Decisions:** every decision is persisted (`SELECTED` / `BUDGET_EXHAUSTED` / `NOT_SURFACED_PARENT` …) and never alters the candidate.

### B5. Horizon metadata

`horizon` ∈ {INTRADAY, SAME_DAY, SHORT_TERM, LONG_TERM} on candidates and evaluator records. There is an evaluator interface: each evaluator consumes `candidate_events` through its own durable cursor. `SAME_DAY` (the research outcome tracker) is implemented first; the others are registered as `NOT_IMPLEMENTED` with an explicit status. V2 stays a separate specialised multi-session strategy.

### B6. Independently restartable components

`python -m talonx_opportunity component {discovery|notifier|outcomes|evaluator:<h>|reporting}`. Each component has:
- its own PID, lock and heartbeat row;
- a durable cursor, so a restart resumes and never duplicates, through idempotent keys;
- its own cadence.

A notifier restart never touches candidates. A discovery restart never touches the outbox. A light supervisor command, `up`, starts and restarts components individually.

### B7. Deployment and change boundaries

Each component start records a `deployment_events` row if its commit SHA, component version or config fingerprint changed. The row carries:
- `deployment_id`, UTC time, component, old and new version, SHA, fingerprints, reason;
- the classification (OPERATIONS_ONLY … STRATEGY_MATERIAL);
- the `affects_*` flags, derived from the component and fingerprint diff.

There is also `record-deployment` for manual entries.

### B8. Reporting impact contract

The session report splits metrics at every boundary whose flags affect detection, classification or P&L. It prints comparability warnings. It explicitly states "comparability intact" for OPERATIONS_ONLY / ROUTING_FIX / UI_ONLY restarts.

### B9. Legacy manifest and cleanup

First `docs/LEGACY_MANIFEST.md`, then targeted removals only where references are proven absent. Planned items:
- Experimental lane M1: supervise and retry, or DEPRECATE (to be decided in the manifest from its evidence value).
- Quant metrics: lane-prefix them.
- yfinance counting: fix the metric.
- Stale-card enqueue: add the guard.
- The `talonx:v2:*` bus and the PIV / gateway channels: mark as historical.
- The live canary's `run` path stays for V1 reproducibility (KEEP_HISTORICAL).

### B10. Dashboard and status

Add `talonx_ops/dashboard_read.py` and status sections for SYSTEM / DATA (capability per phase) / DISCOVERY / HORIZONS / NOTIFICATION (Signal, Lab, Sentinel plus the Intelligence digest-disabled flag) / PAPER / REPORTING (boundaries plus warnings). Removed dead paths are demoted from `/ping`.

### B11. Documentation

Update PRODUCT_DEFINITION, DECISION_LOG (with SUPERSEDED markers), REQUIREMENTS_TRACKER, KNOWLEDGE_TRANSFER_PLAN, OPERATIONAL_FINDINGS, NOTIFICATION_CONTRACT, runbooks and the env example, using the new core requirement wording.

### B12. Tests

The 18 required scenarios, plus a V1-equivalence test for PREMARKET classification. Run the largest practical regression suite and name any baseline test that hangs. `test_session03` noted that the full suite hangs at a backtest test; that will be identified precisely.

### Explicitly out of scope for Stage B

- Changing V1 or V2 thresholds, weights, gates or the 45-minute staleness rule.
- Enabling Intelligence digest delivery by default.
- Enabling Research in the V2 window.
- Any paid feed.
- Claiming overnight coverage beyond `DEGRADED_SINGLE_VENUE`.
