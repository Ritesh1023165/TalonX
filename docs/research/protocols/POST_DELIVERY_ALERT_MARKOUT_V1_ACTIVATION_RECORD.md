# POST_DELIVERY_ALERT_MARKOUT_V1: activation record (configuration locked 2026-10-09)

**Output.** *Post-delivery price markout under stated cost assumptions*. Not an executable fill, realised P&L or
portfolio return.

## Owner approval (activation-preparation instruction, 2026-10-09)

**Approved.**
- Protocol revision 2. The fingerprint **`c812a3e65e4018a5`** was verified against the code; the parameters are
  unchanged.
- 5-minute reaction delay.
- 30-minute interval with exact target bars.
- 60 s maximum quote age.
- Half spread at entry + half spread at exit + **5 bps total additional assumed cost** (an *unsupported modelling
  assumption*, not measured slippage).
- First delivery per symbol per session, selected before any price is inspected. An uncertain first delivery excludes
  that symbol/session, with no substitution.
- Delivery tracing **REQUIRED**.
- 20 sessions.
- Final reporting only after every completion check passes.
- Tracing deployment and one daily off-hours collector.

**Not authorised.** Pricing earlier alerts, changing research rules, or claiming profitability.

**Locked config:** `POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json`. It contains the approval, the protocol
fingerprint and parameters, and the SHA-256 of each implementation file:
- `post_delivery_markout.py`
- `post_delivery_acquisition.py`
- `post_delivery_collector.py`
- `talonx_opportunity/delivery_trace.py`

**Every run revalidates it** (`load_activation(require_integrity=True)`). Any changed file makes the run
`NOT_APPROVED: INTEGRITY_FAILED`, so an earlier hash can never cover changed code.

## Calendar (XNYS via `talonx_opportunity.phases.trading_window`; verified by test)

| Item | UTC | Europe/London |
|---|---|---|
| Activation boundary (window opens; earlier alerts are never admitted) | 2026-10-19 00:00Z | 01:00 BST |
| First session (regular 13:30–20:00Z) | 2026-10-19 | 14:30–21:00 BST |
| UK DST change | 2026-10-25 | BST → GMT |
| US DST change (close becomes 21:00Z from 2026-11-02) | 2026-11-01 | — |
| Last (20th) session | 2026-11-13 (14:30–21:00Z) | 14:30–21:00 GMT |
| Final observation deadline (close of 2026-11-17 + 60 min) | **2026-11-17 22:00Z** | **22:00 GMT** |
| Final-report eligibility | ≥ 2026-11-17 22:00Z **and** every completion check passes | — |

**Sessions:** 2026-10-19 … 10-23, 10-26 … 10-30, 11-02 … 11-06, 11-09 … 11-13. There are no holidays and no half days
in the period.

**Session deadline** = close of the second subsequent session + 60 min.

## R5 finding

The authoritative definition is in `research/event_response_map_v1/data.py` ("LOCK REV 2 (R5)") and the ERM
`transport.py`: Alpaca and SEC calls are refused on **weekdays 09:00–16:30 America/New_York, DST-aware**.
- The "13:00–20:30 UTC" wording seen earlier is that rule's **EDT** rendering. In EST the rule is 14:00–21:30 UTC.
- There is no genuine conflict, and no restriction was changed.
- The schedule avoids **both** the ET rule and the fixed 13:00–20:30 UTC form, enforced by test.
- `post_delivery_acquisition.r5_permitted` also refuses any request inside R5.

## Schedule (Windows Task Scheduler, `\TalonX\PDM_V1_Collector`)

**Trigger:** daily **00:15 Europe/London** (the machine's local zone).
- = **23:15Z** while BST (to 2026-10-24); = **00:15Z** while GMT (from 2026-10-26).
- 2026-10-25 00:15 occurs before the 02:00 change, so it is BST (23:15Z on 10-24).
- Each run therefore falls after the previous session's close + 60 min: 21:00Z in EDT and 22:00Z in EST.
- Each session gets at least 2 runs before its deadline (test).
- `StartBoundary` 2026-10-19 00:15 local; `EndBoundary` 2026-11-18 12:00 local. The last run, 2026-11-18 00:15Z, is a
  reconcile-only recovery run, because it is after the final deadline.

**Command** (working directory `C:\workspace\TalonX`):
```
C:\workspace\TalonX\.venv\Scripts\python.exe -m talonx_paperperf.post_delivery_collector
    --config C:\workspace\TalonX\docs\research\protocols\POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json
    --enable --budget-s 900
```

**Guards.**
- Scheduler: `MultipleInstancesPolicy=IgnoreNew` and a 30-minute execution limit.
- Collector: its own lock (an overlapping run is refused) and a 900 s request budget.
- Provider limits: 40 requests/min, 2 retries, ≤ 5 quote pages.
- Processing budget: ≤ 200 due observations per run (`collector.max_observations_per_run`, authoritative). This is a batch size,
  not a sample cap; see *Operational correction* below.
- **Scope:**
  - No request before the activation boundary.
  - No new admission outside the 20 sessions. After the last session, only outstanding in-scope observations are
    fetched, until their own deadlines.
  - At or after the endpoint, the run reconciles and writes status only. Nothing late is fetched and nothing is
    reopened.
- Each run logs scheduled vs actual time and missed days to `results/post_delivery_markout_ops/runs.jsonl`, with
  operational status only; no return value is ever written there.
- There is no Telegram summary and no rolling outcome publication.

**Machine requirements** (unchanged, not modified):
- The user is logged in: interactive token, the same as the existing TalonX tasks.
- The machine is on AC power (existing convention: no start on battery).
- The network is available.

`StartWhenAvailable` runs a missed instance late. Lateness and missed days are recorded, and deadlines are never
extended.

## Final reporting

`final_report()` returns numbers only if **all** of these hold:
- the 20-session period has ended;
- the final deadline has passed;
- every in-scope source delivery has been registered, with none still in flight;
- every selected observation is terminal;
- the implementation integrity check passes;
- the protocol fingerprint matches.

Otherwise it returns `INCOMPLETE` (or `NOT_AVAILABLE_BEFORE_ENDPOINT`) with the failing checks. There is no
profitability verdict in either case.

## Rollback

1. **First**, disable the collector: `schtasks /change /tn "\TalonX\PDM_V1_Collector" /disable`.
2. Optionally remove it later with `/delete`.
3. Keep `results/post_delivery_markout*` as evidence.

Tracing can stay; it never affects delivery. To remove it, revert `Promoter._drain_signal` to the plain `drain(...)`
call and make a declared promotion restart.

None of this pauses review alerts, replays messages, resumes VR, alters other studies or deletes collected evidence.

## Delivery tracing: deployment and natural verification (2026-10-09)

**Deployments.** Both were component-specific declared restarts of promotion only.
- 13:36:12Z (14:36 BST): commit `4a4826d`, declaration #48, v`466ddff305d7`.
- 13:46:00Z (14:46 BST): commit `507f8c0`, declaration #49, v`02df848a2940`. This added `delivery_trace.py` to the
  promotion version hash; the running code was unchanged.

Routing, content, parse mode, retry limits, dedup, the 600 cap, the rate limit and the VR interruption are all unchanged.
Old rows were not replayed and no historical trace was fabricated.

**Natural verification.** 6 natural review alerts, 13:50–13:56Z, were checked read-only by `verify_natural_traces.py`.
Evidence: `NATURAL_TRACE_VERIFICATION_2026-10-09.json` (sanitised: no message IDs, chat identifiers or payloads).
- **Correlation:** each outbox `SENT` row has exactly one trace (payload SHA-256), and the study lookup returns
  `TRACE_OK`.
- **Ordering:**
  - send start ≤ response, by 733–1098 ms;
  - outbox `sent_at` is 8–25 ms after the response;
  - row created ≤ send start.
- **Server timestamp:** 1 s precision. Server − response ranges from −1.034 s to −0.264 s, consistent with truncation
  and inside the package's existing 2.0 s tolerance.
- Message ID present; destination stored only as a 12-character hash.
- **Retries:** 0 network, 0 rate-limit and 0 definite; outbox attempts = 1. The wrapper's retry observation of the
  real client is proven by test.
- No duplicated dedup key and no untraced `SENT` row.
- VR entry control: `BLOCKED`.
- **Clock:** w32tm reports source time.windows.com, stratum 5, root dispersion 0.27 s, against the package tolerance of
  2.0 s.

No alert was paired with bars or quotes, and no synthetic message was sent.

## Operational correction: `--max-observations` (2026-10-09, before any collection)

**Defect.** The collector recorded `--max-observations` but never passed it on, so `acquire()` used a built-in 200.

**Was it batching or truncation?** Batching. No delivery was ever dropped:
- source scan, registration and first-per-symbol selection are unbounded and re-run on every run (idempotent by
  `event_id`, with no cursor);
- the limit applied only to per-run acquisition, and unprocessed observations stayed `SELECTED_WAITING`.

**Defects inside that batch:**
- not-yet-matured observations and work after time-budget exhaustion still took slots;
- budget-exhausted iterations counted as attempts;
- within a session the order fell back to `obs_id`, which embeds the ticker, so any shortfall would land
  alphabetically.

**Correction.** Study rules are unchanged: population, selection, dates, timing, costs, method and endpoint.
- **One authoritative value.** It is `collector.max_observations_per_run` = **200** in the locked config.
  - The optional CLI flag must equal it.
  - A missing, invalid, or conflicting value refuses the run (`CONFIG_REJECTED`) before any request.
  - The engine also rejects values below 1 and non-integers.
- **Due work only.** A run processes matured observations before their original deadline.
- **Processing order** is earliest deadline, then fewest attempts, then `sha256(obs_id)`. The hash is deterministic,
  independent of prices and outcomes, and never used for selection.
- **Budget exhaustion.** The run stops. Nothing more is requested, and no error or attempt is recorded for untouched
  observations. The remainder is reported as `deferred` and stays pending.
- Deadlines keep their meaning, and final reporting still requires reconciled sources and all-terminal observations.

**Lock update.** The procedure:
1. Confirm no collector is running and no study store exists.
2. Fix the code and tests.
3. Recompute `implementation_hashes()`.
4. Append a `lock_history` entry with old and new hashes.
5. Recompute the config SHA.
6. Verify integrity and the fingerprint.

Approval, protocol fingerprint, parameters, first session and trace policy are byte-identical. The task definition is
unchanged, and so is its config path.

Config SHA-256 (excluding its own field): `d1b14b4281b59b5d4ca832a1a90fe21417108a2928df6a5563edc0fdeb1c57a4` → `f96b1c15237518259cc8229bfc4bd877b0e9756e83f79dd283b3067e24782fc8`.

| File | Previous SHA-256 | New SHA-256 |
|---|---|---|
| `talonx_paperperf/post_delivery_collector.py` | `e21e7312758c30f1c4a1d2f625a2f4a76bc9421ab3af00e646a70ed335c969e0` | `922675f2a53f338e8e2e0efc4a0c7d9a91f9cbc96725a44c695cdd2592ef30fd` |
| `talonx_paperperf/post_delivery_markout.py` | `b969c8ac49fdfce0a6925b48b7525d29c3397fa9616f3a5ac6def7781bedcd51` | `31a2c95877ce0b5dbe346e60faf9e3a65013248f9462d0ad4dd1f19a3d8d174e` |

`post_delivery_acquisition.py` and `talonx_opportunity/delivery_trace.py` are unchanged. The corrected path adds no new
module dependency.

The study still uses two dependencies outside the integrity lock, as before:
- `talonx_opportunity/phases.py` (XNYS calendar), which the calendar tests check;
- `talonx_premarket/__main__._env` (credential loading).

## Processing capacity: ESTIMATE and deadline risk

Source: `pdm_v1_scheduler/capacity_estimate.py` → `CAPACITY_ESTIMATE_2026-10-09.json`. It drives the real `acquire()`
and `AlpacaAcquirer` pacing, retry and budget code against a simulated clock and a mock transport. It is synthetic,
not a provider measurement.

**Per run** (900 s, 40/min, so at most about 600 requests and at least 4 requests per observation):

| Transport scenario | Observations per run |
|---|---|
| Clean, 1 quote page | ~151 |
| 5% transient 5xx errors | ~137 |
| 2 quote pages | ~101 |
| 2 quote pages and 5% 5xx | ~92 |

**The binding limit is the 900 s budget at 40/min, not the 200.** The 200 is never reached.

**Demand.** The last 7 sessions had 133–203 first deliveries per symbol per session (counts only), before
eligibility and ambiguity exclusions.

**Calendar replay** (20 sessions, daily runs, earliest deadline first, no study rule changed):
- At 151 per run there are no expiries up to 170 per session.
- At ~205 per session, 44 of 4,100 expire.
- At 2 quote pages (101 per run), 535 of 3,400 expire at 170 per session.

**Genuine deadline risk:** on busy sessions, or if quotes need more than one page, some selected observations would
expire unattempted. Expiry is recorded as `EXPIRED` and never dropped. The ticker-neutral order makes the loss
quasi-random rather than alphabetical.

**Proposal (not implemented; owner decision).** Add a second off-hours daily trigger to the same task, for example
06:30 London (05:30Z BST / 06:30Z GMT, outside R5).
- Every per-run bound stays the same: 900 s, 40/min, retries, pages, 200.
- This roughly doubles daily capacity (estimate ~184–300 observations per day).

Alternatives:
- raise `budget_s` to 1,500 s together with a 40-minute execution limit;
- an off-hours rate above 40/min, which needs a shared-quota review first.

## Operational amendment: second daily trigger and calendar integrity (2026-10-09, before any collection)

**Owner approval.** One existing task, `\TalonX\PDM_V1_Collector`, now has two daily triggers: 00:15 and 06:30
Europe/London. Both run the same collector, configuration, store and singleton lock.

**Unchanged:**
- 200 observations per invocation, the 900 s budget, 40 requests/min and the retry policy;
- deadlines;
- population, sampling, timing, costs and reporting;
- the 20 sessions from 2026-10-19 to 2026-11-13, and the endpoint, 2026-11-17 22:00Z.

This is a capacity change only. It neither extends the study nor permits early collection.

### Schedule

| Trigger | Local boundaries (Europe/London) | UTC under BST (to 2026-10-24) | UTC under GMT (from 2026-10-26) |
|---|---|---|---|
| 00:15 | 2026-10-20 00:15 to 2026-11-18 12:00 | 23:15Z the previous day | 00:15Z |
| 06:30 | 2026-10-20 06:30 to 2026-11-17 12:00 | 05:30Z | 06:30Z |

- **First invocations:** 2026-10-19 23:15Z, after session 1 closes + 60 min (21:00Z), and 2026-10-20 05:30Z. Nothing
  runs before 2026-10-19.
  - The previous first instant, 2026-10-18 23:15Z, was a pre-boundary no-op and has been removed.
- **Last 06:30 invocation:** 2026-11-17 06:30Z, before the endpoint.
- **Last permitted invocation:** 2026-11-18 00:15Z, reconcile only. No 06:30 run follows it.
- **Task expiry:** 2026-11-18 12:00 London (12:00Z), the latest possible late start. It is R5-permitted (07:00 ET).
- **R5:** every instant is outside the America/New_York R5 rule and its fixed-UTC form across the 2026-10-25 UK and
  2026-11-01 US changes (tested).
- **Chances per session:** at least 4 triggers fall between each session's maturity and its original deadline (tested).
- **Overlap:** a missed trigger that overlaps the next cannot start a concurrent fetcher. The scheduler setting
  `IgnoreNew` and the collector lock both prevent it.
- **Late invocations:**
  - every invocation re-checks integrity, calendar, activation and endpoint before any request;
  - a late start inside R5 makes no request;
  - a run that reaches R5 mid-way stops and defers the rest, with no errors or attempts recorded;
  - missed trigger slots are logged (`missed_slots`);
  - the study period never expands.

### Calendar integrity binding

**Bound local code.** These files determine session dates, open/close and deadline arithmetic:
- `talonx_opportunity/phases.py` (`trading_window`, `window_at`, `phase_at`);
- `talonx_premarket/session.py` (`_xnys`, `is_session`).

`talonx_premarket/config.py` is imported by `session.py`, but the functions on this path don't use its values, so it is
not bound.

**Enforced result check.** `calendar_sha256` = `65d1d40d8298c492fd400439dce40d4d42384ee01b41c902b208075dc8ce6c96`. It covers session, open, close, maturity and
deadline for the 20 sessions, which `calendar_table` stores in the config.
- The deployed environment reproduces the approved table.
- A changed bound file, a different calendar result, or a missing calendar package refuses the run
  (`INTEGRITY_FAILED`) before any request.

**Recorded provenance (not enforced):**
- exchange_calendars 4.13.2;
- tzdata 2026.3 (`zoneinfo.TZPATH` is empty, so the tzdata package is the source);
- pandas 3.0.5;
- Python 3.12.10.

**Operational consequence.** `phases.py` is also an engine runtime file. Any edit to it, or to `session.py`, before
2026-11-18 makes the collector refuse until it is re-locked with this procedure.

**Bound vs not bound.**
- *Bound:* source code and the calendar result.
- *Not bound:*
  - **secret configuration** (Alpaca credentials loaded from `.env` by `talonx_premarket.__main__._env`), which is never
    hashed, printed or persisted;
  - Python packages other than through the calendar result.

### Lock update

Previous records are preserved in `lock_history[0]`.

Config SHA-256: `f96b1c15237518259cc8229bfc4bd877b0e9756e83f79dd283b3067e24782fc8` → `6c4512675f685bacdbb6a8ddf2e9e88bb0595da01866cc544b2855c4d487ed14`. Protocol fingerprint
`c812a3e65e4018a5` is unchanged.

| File | Previous SHA-256 | New SHA-256 |
|---|---|---|
| `talonx_paperperf/post_delivery_markout.py` | `31a2c95877ce0b5dbe346e60faf9e3a65013248f9462d0ad4dd1f19a3d8d174e` | `7ddcb760e72f0d8dca8aa95b2f055b94b53ffbe4cab4fd7f8e77473bc5a993b1` |
| `talonx_paperperf/post_delivery_acquisition.py` | `5a7f41759aa2ccd3225398afadd701f2bb4a8b5dc945cf92aca64fc9a4d15a52` | `5a7f41759aa2ccd3225398afadd701f2bb4a8b5dc945cf92aca64fc9a4d15a52` |
| `talonx_paperperf/post_delivery_collector.py` | `922675f2a53f338e8e2e0efc4a0c7d9a91f9cbc96725a44c695cdd2592ef30fd` | `d81a501b642d5777f58425f7d3c83104d9c2f843e7222fa88ad47eed0c40e263` |
| `talonx_opportunity/delivery_trace.py` | `41712a78015d78c678c2553a23eda192a22ae617f1afbd32f5a04a1ef5590519` | `41712a78015d78c678c2553a23eda192a22ae617f1afbd32f5a04a1ef5590519` |
| `talonx_opportunity/phases.py` | `— (newly bound)` | `1a0c330d106cce1e1ef730174f9d612d5de0f8567d42cbe7422e50ab5029f42a` |
| `talonx_premarket/session.py` | `— (newly bound)` | `4bda535a1d6f273649262c5a6b0296665df3f8dd581384382292955348f2486a` |

### Capacity: ESTIMATE, one trigger vs two

Source: `pdm_v1_scheduler/capacity_two_triggers.py` → `CAPACITY_TWO_TRIGGERS_2026-10-09.json`.

**What it drives.** The real `run()`: deadline reconciliation, registration, selection, the `processing_key` order and
`acquire()`. Each trigger fires at its actual UTC instant, and the store persists across invocations, as a restart
would.

**Per invocation:** a fresh `AlpacaAcquirer` with a 900 s budget, 40/min, 2 retries, ≤ 5 quote pages and a cap of 200.

**Demand:** 133, 170, 203 or 205 eligible selected deliveries per session, spread across each session.

**Miss scenarios:**
- *missed run:* the 2026-10-27 00:15Z trigger is skipped;
- *missed day:* both 2026-11-04 triggers are skipped.

**Not modelled:**
- latency variance (fixed 0.3 s per request) and provider 429s;
- machine sleep or late starts;
- trace exclusions;
- production disk speed.

The study store ran with `synchronous=OFF` in the simulation. Local work before the first request does not consume the
900 s budget, because the acquirer is created lazily; the maximum local wall time measured was about 42 s per
invocation.

**Not a provider measurement.**

| Transport | Demand/session | Schedule | Missed | Measured | Expired | Max due at a trigger | Max backlog after a run | Max maturity→measured (h) |
|---|---|---|---|---|---|---|---|---|
| clean_1_quote_page | 133 | one trigger | none | 2660 / 2660 | **0** | 133 | 0 | 3.2 |
| clean_1_quote_page | 133 | two triggers | none | 2660 / 2660 | **0** | 133 | 0 | 3.2 |
| clean_1_quote_page | 133 | two triggers | missed run | 2660 / 2660 | **0** | 133 | 0 | 9.5 |
| clean_1_quote_page | 133 | two triggers | missed day | 2660 / 2660 | **0** | 266 | 116 | 26.2 |
| clean_1_quote_page | 170 | one trigger | none | 3400 / 3400 | **0** | 249 | 99 | 27.2 |
| clean_1_quote_page | 170 | two triggers | none | 3400 / 3400 | **0** | 170 | 20 | 9.5 |
| clean_1_quote_page | 170 | two triggers | missed run | 3400 / 3400 | **0** | 190 | 40 | 27.2 |
| clean_1_quote_page | 170 | two triggers | missed day | 3400 / 3400 | **0** | 340 | 190 | 32.5 |
| clean_1_quote_page | 203 | one trigger | none | 4028 / 4060 | **32** | 406 | 256 | 51.2 |
| clean_1_quote_page | 203 | two triggers | none | 4060 / 4060 | **0** | 203 | 53 | 9.5 |
| clean_1_quote_page | 203 | two triggers | missed run | 4060 / 4060 | **0** | 256 | 106 | 27.2 |
| clean_1_quote_page | 203 | two triggers | missed day | 4060 / 4060 | **0** | 406 | 256 | 32.5 |
| clean_1_quote_page | 205 | one trigger | none | 4044 / 4100 | **56** | 410 | 260 | 51.2 |
| clean_1_quote_page | 205 | two triggers | none | 4100 / 4100 | **0** | 205 | 55 | 9.5 |
| clean_1_quote_page | 205 | two triggers | missed run | 4100 / 4100 | **0** | 260 | 110 | 27.2 |
| clean_1_quote_page | 205 | two triggers | missed day | 4100 / 4100 | **0** | 410 | 260 | 32.5 |
| 2_quote_pages | 133 | one trigger | none | 2660 / 2660 | **0** | 265 | 165 | 51.2 |
| 2_quote_pages | 133 | two triggers | none | 2660 / 2660 | **0** | 133 | 33 | 9.5 |
| 2_quote_pages | 133 | two triggers | missed run | 2660 / 2660 | **0** | 166 | 66 | 27.2 |
| 2_quote_pages | 133 | two triggers | missed day | 2660 / 2660 | **0** | 266 | 166 | 32.5 |
| 2_quote_pages | 170 | one trigger | none | 2844 / 3400 | **556** | 340 | 240 | 75.2 |
| 2_quote_pages | 170 | two triggers | none | 3400 / 3400 | **0** | 170 | 70 | 9.5 |
| 2_quote_pages | 170 | two triggers | missed run | 3400 / 3400 | **0** | 240 | 140 | 27.2 |
| 2_quote_pages | 170 | two triggers | missed day | 3400 / 3400 | **0** | 340 | 240 | 32.5 |
| 2_quote_pages | 203 | one trigger | none | 2904 / 4060 | **1156** | 406 | 306 | 99.2 |
| 2_quote_pages | 203 | two triggers | none | 4060 / 4060 | **0** | 214 | 114 | 27.2 |
| 2_quote_pages | 203 | two triggers | missed run | 4060 / 4060 | **0** | 314 | 214 | 33.5 |
| 2_quote_pages | 203 | two triggers | missed day | 4051 / 4060 | **9** | 406 | 306 | 50.2 |
| 2_quote_pages | 205 | one trigger | none | 2904 / 4100 | **1196** | 410 | 310 | 99.2 |
| 2_quote_pages | 205 | two triggers | none | 4100 / 4100 | **0** | 224 | 124 | 27.2 |
| 2_quote_pages | 205 | two triggers | missed run | 4100 / 4100 | **0** | 324 | 224 | 33.5 |
| 2_quote_pages | 205 | two triggers | missed day | 4085 / 4100 | **15** | 410 | 310 | 50.2 |
| 5pct_transient_5xx | 133 | one trigger | none | 2660 / 2660 | **0** | 134 | 1 | 26.2 |
| 5pct_transient_5xx | 133 | two triggers | none | 2660 / 2660 | **0** | 133 | 1 | 8.5 |
| 5pct_transient_5xx | 133 | two triggers | missed run | 2660 / 2660 | **0** | 133 | 1 | 9.5 |
| 5pct_transient_5xx | 133 | two triggers | missed day | 2660 / 2660 | **0** | 266 | 127 | 26.2 |
| 5pct_transient_5xx | 170 | one trigger | none | 3400 / 3400 | **0** | 300 | 163 | 75.2 |
| 5pct_transient_5xx | 170 | two triggers | none | 3400 / 3400 | **0** | 171 | 35 | 26.2 |
| 5pct_transient_5xx | 170 | two triggers | missed run | 3400 / 3400 | **0** | 203 | 65 | 27.2 |
| 5pct_transient_5xx | 170 | two triggers | missed day | 3400 / 3400 | **0** | 340 | 204 | 32.5 |
| 5pct_transient_5xx | 203 | one trigger | none | 3845 / 4060 | **215** | 406 | 270 | 51.2 |
| 5pct_transient_5xx | 203 | two triggers | none | 4060 / 4060 | **0** | 203 | 68 | 9.5 |
| 5pct_transient_5xx | 203 | two triggers | missed run | 4060 / 4060 | **0** | 268 | 135 | 27.2 |
| 5pct_transient_5xx | 203 | two triggers | missed day | 4060 / 4060 | **0** | 406 | 268 | 32.5 |
| 5pct_transient_5xx | 205 | one trigger | none | 3854 / 4100 | **246** | 410 | 276 | 74.2 |
| 5pct_transient_5xx | 205 | two triggers | none | 4100 / 4100 | **0** | 205 | 73 | 26.2 |
| 5pct_transient_5xx | 205 | two triggers | missed run | 4100 / 4100 | **0** | 276 | 138 | 27.2 |
| 5pct_transient_5xx | 205 | two triggers | missed day | 4100 / 4100 | **0** | 410 | 271 | 32.5 |
| 2_quote_pages_and_5pct_5xx | 133 | one trigger | none | 2551 / 2660 | **109** | 266 | 177 | 51.2 |
| 2_quote_pages_and_5pct_5xx | 133 | two triggers | none | 2660 / 2660 | **0** | 134 | 45 | 27.2 |
| 2_quote_pages_and_5pct_5xx | 133 | two triggers | missed run | 2660 / 2660 | **0** | 175 | 80 | 27.2 |
| 2_quote_pages_and_5pct_5xx | 133 | two triggers | missed day | 2660 / 2660 | **0** | 266 | 178 | 32.5 |
| 2_quote_pages_and_5pct_5xx | 170 | one trigger | none | 2642 / 3400 | **758** | 340 | 251 | 75.2 |
| 2_quote_pages_and_5pct_5xx | 170 | two triggers | none | 3400 / 3400 | **0** | 171 | 81 | 26.2 |
| 2_quote_pages_and_5pct_5xx | 170 | two triggers | missed run | 3400 / 3400 | **0** | 248 | 156 | 27.2 |
| 2_quote_pages_and_5pct_5xx | 170 | two triggers | missed day | 3400 / 3400 | **0** | 340 | 247 | 32.5 |
| 2_quote_pages_and_5pct_5xx | 203 | one trigger | none | 2681 / 4060 | **1379** | 406 | 317 | 99.2 |
| 2_quote_pages_and_5pct_5xx | 203 | two triggers | none | 4060 / 4060 | **0** | 276 | 184 | 32.5 |
| 2_quote_pages_and_5pct_5xx | 203 | two triggers | missed run | 4060 / 4060 | **0** | 360 | 269 | 33.5 |
| 2_quote_pages_and_5pct_5xx | 203 | two triggers | missed day | 4003 / 4060 | **57** | 406 | 316 | 50.2 |
| 2_quote_pages_and_5pct_5xx | 205 | one trigger | none | 2691 / 4100 | **1409** | 410 | 320 | 99.2 |
| 2_quote_pages_and_5pct_5xx | 205 | two triggers | none | 4100 / 4100 | **0** | 291 | 199 | 33.5 |
| 2_quote_pages_and_5pct_5xx | 205 | two triggers | missed run | 4100 / 4100 | **0** | 378 | 285 | 51.2 |
| 2_quote_pages_and_5pct_5xx | 205 | two triggers | missed day | 4045 / 4100 | **55** | 410 | 319 | 50.2 |

**Findings:**
- **One trigger:** observations expire whenever demand reaches about 170 per session with 2-page quotes, or about 203
  with a clean transport.
- **Two triggers, no missed runs:** no expiries in any scenario.
- **Two triggers, one missed run:** no expiries.
- **Two triggers, one missed full day:** 9–57 expiries in the 2-quote-page scenarios at 203–205 per session.
- The 200 cap never binds; the 900 s budget does.

**This does not guarantee complete coverage.** Real latency, 429s, multi-day outages or higher demand can still expire
observations.
- Expired observations stay in coverage reporting with their acquisition histories and reasons.
- The hash order removes alphabetical preference. It does not establish that missingness is random.
- No budget, trigger, deadline or selection rule was changed to close the residual risk.

### Rollback

Restore the one-trigger task and the previous config binding together:
1. Disable the task.
2. Re-import the task definition from commit `0804485`
   (`docs/research/protocols/pdm_v1_scheduler/PDM_V1_Collector.task.xml`).
3. Restore the config, collector and markout files from `0804485`, then verify integrity.
4. Re-enable the task.

The study store, ops logs and all evidence are kept. Observation deadlines are unchanged.
