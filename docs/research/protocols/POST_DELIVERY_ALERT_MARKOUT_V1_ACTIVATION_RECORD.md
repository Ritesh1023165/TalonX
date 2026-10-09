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
