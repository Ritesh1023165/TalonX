# V2 live Form 4 coverage audit (2026-10-07)

**Verdict: `COVERAGE_MATCHES_APPROVED_SCOPE`.**

- The live V2 companion (`V2-PAPER-RC1`) runs on the **39-issuer** scope that the RC1 release specified.
- Every one of those 39 issuers is polled successfully.
- Zero paper trades follows from the strategy's own rules applied to that scope:
  - only one ≥2-insider cluster existed in the window, and it fired before the campaign started;
  - no new cluster formed during the campaign.
- The real gap is a **population decision, not a coverage defect.** The approved live scope (39) is about 6% of the
  626-name population on which V2 was validated, and that decision was never recorded as a campaign-population
  choice.

This was a read-only audit:
- no polling, scope, filter, schedule or account change;
- no restart, no SEC fetch, no replay, no Telegram;
- no ERM data touched.

## 1. Closure of the promotion-pause task

**Commits.** Branch `feature/continuous-opportunity-engine`:

| Commit | Content |
|---|---|
| `ab4b39d` | pause + dashboard |
| `bcfd10a` | version attribution |
| `3fde58c` | evidence |

HEAD = origin = `3fde58c` and the branch is in sync.

**User's file preserved.** `docs/research/evidence/forward_alpha_validation.md` is still modified and uncommitted
(+63 lines), with MD5 `6fa1639c…`, identical before and after every fast-forward.

**Pause holds.**
- The control file has `paused: true`. Promotion pid 17824 is RUNNING with config `signal_delivery=PAUSED`.
- There has been no deployment since 11:25:41Z.
- The Signal outbox is unchanged at 1,221 SENT; the last row was created 2026-10-06T19:55Z.
- Recording continues: 69 `PROMOTED_SHADOW / SIGNAL_DELIVERY_PAUSED` rows through 17:30Z, plus 1
  `REJECTED_WHILE_QUEUED / STALE`.

**Pending VR entry: cannot execute.** The row is NVCT, ACTIONABLE, window 2026-09-30, trade `13babda614db1b23`. This
was traced in code (`talonx_paperperf/vr_live.py`):

- `main()` calls `vr.tick(today.isoformat(), …)` only for **today's** UTC date window.
- `tick()` selects only trades `WHERE window_id=?` for that window.
- A 2026-09-30 row is therefore never selected again.
- `eod` only reads trades and writes a JSON report.
- No other caller ticks a past window: the repository was grepped and found only the tracker script, the EOD script
  and tests.
- The interruption JSON is **not** enforced by code. New entries stop because no `PROMOTED_SIGNAL` rows are produced,
  not because of that file.

**Separate latent VR defect (not fixed).** NVCT's Signal was sent at 20:03:43Z, after the 19:50Z flatten.

- `_try_open` (ACTIONABLE) skips only when there is *no* send time and T is past the flatten.
- With a send time after the flatten, the row has no terminal path. The tracker stops ticking the window at about
  20:21Z, so the row stays `PAPER_ENTRY_PENDING` forever.
- Effect: that window's EOD `states` shows 1 pending instead of 1 skipped. There is no execution risk.
- **Smallest fix (proposed only):** in `_try_open`, ACTIONABLE branch, when `wall` exists and
  `ceil_min(wall) >= flat`, call `self._skip(t, "SENT_AFTER_FLATTEN")`.
- The existing stranded row should be left as is, or resolved only under an explicit owner decision. It was not
  activated, backfilled or deleted.

## 2. Authoritative scope: what 626 / 39 / 141 measure

| Count | What it measures | Source / date / version | In live use? |
|---|---|---|---|
| **626** | *Discovery Universe v1*: the Task 116 620-name survivorship S&P panel ∪ the 39-name SEC-resolved watchlist. Static CIK manifest: 569 resolved, **57 unresolved** | `talonx_ingest/intelligence/service/data/discovery_universe_v1_626.json`, frozen 2026-09-13 (Task 131), from research commit `5282219` | **No.** Used only with `--enable-broad-discovery`. It was live on the pre-release lane on 2026-09-15 (`execution_scope_count: 626`, `eod_closure_2026-09-15`). RC1 does not use it |
| **39** | The **effective Intelligence poll list**, which is also the **live V2 execution allowlist**. The resolver takes 48 configured → 43 active → 39 SEC-resolvable. The 4 active non-filers are BABA, BLSH, SKHY and SPCX; 5 more are paused | `~/.talonx/intelligence/service.heartbeat.json` `scope`; `talonx_ops.watchlist_coverage`; live V2 status `execution_scope_count: 39` | **Yes**, for both polling and V2 admission |
| **141** | Distinct symbols with a **stored** Form 4 filed on or after 2026-08-24 in `ingestion_ledger.db` | 35 of them are among the 39. 101 are other 626 names and 5 are non-626, all last ingested between **2026-09-04 and 2026-09-15**, during the Task 131/140 broad collection. Separately, 209 symbols have completed backfill checkpoints ending 2026-09-14 | **Not a polling-coverage measure.** It is leftover broad-collection data. The 4 polled names with no filing since 08-24 are AGNC, INTC, NUE and SHOP |

**Live configuration** (process 10872/720, started 2026-10-04 22:12Z; repo HEAD `3fde58c`):

```
talonx_v2.run --mode live --form4-source insider --db v2_release_rc1.db --tick-seconds 150 --live-lookback-days 45
  --pricing-mode sip --execution-scope resolved-active-watchlist --release --deliver --transport telegram
```

There is **no** `--enable-broad-discovery`. The input store is `~/.talonx/ingestion_ledger.db` (`InsiderStore`).

**Governing decision.** The RC1 release launch specification prescribes exactly this argv and says:

> Do NOT add `--pricing-mode csv`, `--enable-broad-discovery` or Lab flags.

Sources: `release_freeze_preflight/13_full_day_launch_command.md`;
`v2_final_release_acceptance/release_candidate_configuration.json` `launch_argv`.

The narrow scope was therefore **deliberately adopted** for RC1. However, `talonx_ops/watchlist_coverage.py` itself
records the universe question as open:

> Applying the configured watchlist as the V2 execution universe is a GOVERNANCE decision
> (`UNIVERSE_CONTRACT_DECISION_REQUIRED`)

That item is still `OPS-006 OPEN` in `v2_final_release_acceptance/ops_classification.csv`. The historical validation
population was the S&P panel (Task 116 N=170; Task 130 N=153 on the 626 set). No decision record says the 39-name
scope is the campaign's study population.

## 3. Coverage table

Files:
- `coverage_by_symbol.csv`: 633 rows, the 626 ∪ 39 ∪ 48-watchlist names.
- `coverage_by_issuer.csv`: 629 issuers.
- `coverage_summary.json`.

| Class | Symbols | Issuers |
|---|---|---|
| CONFIGURED_AND_SUCCESSFULLY_POLLED_WITH_FILINGS (Form 4 filed since 2026-09-21) | 24 | 24 |
| CONFIGURED_AND_SUCCESSFULLY_POLLED_NO_FILINGS | 15 | 15 |
| CONFIGURED_BUT_FAILING | 0 | 0 |
| NOT_CONFIGURED (outside any approved scope) | 0 | 0 |
| IDENTITY_UNRESOLVED (626 manifest, no CIK; also outside RC1 scope) | 57 | 57 |
| OBSERVABILITY_INSUFFICIENT | 0 | 0 |
| INTENTIONALLY_OUT_OF_SCOPE (RC1 launch spec; 9 watchlist names by resolver reason or paused) | 537 | 533 |

- **Shared issuer mappings.** FOX/FOXA, GOOG/GOOGL, NWS/NWSA and UA/UAA, so 633 symbols map to 629 issuers. Only
  GOOGL is in the live 39.
- **Issuer matching.** All in-scope filings since 2026-08-23 match the resolved issuer CIK.
- **Poll evidence for the 39.**
  - `poll_history.jsonl` has 4,649 cycles from 2026-09-24 04:22Z to now.
  - **4,637 cycles report `symbols_polled=39, symbols_failed=0`.** `symbols_polled` counts per-symbol successful EDGAR
    submissions fetches (`poller.py`), so this is per-symbol evidence, not a heartbeat.
  - The last such cycle was 2026-10-07 17:36Z.
  - 12 partial-failure cycles occurred on 10-02 21:47Z and 10-04 23:48Z to 10-05 21:03Z, around the 10-04 reboot.
  - Downtime gaps: 09-24 20:00Z → 09-25 07:08Z, the weekend 09-26 → 09-28, and 10-04 17:49Z → 22:08Z.
  - Each poll reads the issuer's full submissions list, so a gap delays filings but does not lose them.
- **Freshness.** `SEC_EDGAR_SUBMISSIONS` and `SEC_FORM345_BULK` are FRESH (global definition). V2 status shows
  `data_state CURRENT`, 0 filings missing an authoritative filing date and 0 blocked symbols.

**Observability gaps.** These questions cannot be answered from existing telemetry:
1. No per-symbol poll timestamps or outcomes are persisted, only per-cycle counters. The partial-failure cycles cannot
   be attributed to symbols.
2. `poll_history.jsonl` begins 2026-09-24 04:22Z. The campaign started 2026-09-21 18:38Z, so 09-21 to 09-24 has no
   per-cycle evidence.
3. Identity drops (other-issuer ownership filings) are counted per cycle, not per symbol.
4. The V2 out-of-scope drop log lists at most 8 example symbols per tick.
5. The V2 checkpoint funnel snapshots stop at 2026-10-05 22:14Z. Today's funnel was recomputed read-only with
   `talonx_ops.prospective.funnel.build_funnel` (mode=ro).

## 4. Funnel: campaign start (2026-09-21 18:38Z) to now

| Stage | Count (scope = 39) | Evidence |
|---|---|---|
| Acquisition | 39/39 issuers polled per cycle; 24 issuers had ≥1 Form 4 filed since 09-21 | poll history; ledger |
| Issuer attribution | all matched; other-issuer drops = 1 recurring BAC-filed filing (correct) | `identity_drops`; 556c62c |
| Parse / ingest | 0 parse failures (session metrics); 0 missing filing dates | `service.metrics.json`; V2 status |
| Eligible transactions (code P) in the 45-day lookback (since 08-23) | **8 rows, 3 issuers**: ADC 6 rows / 3 owners, ABCL 1, ORCL 1. Filed *during* the campaign: only **ADC 09-23** (third owner) and **ORCL 10-01** | `insider_transactions`; funnel |
| Records V2 drops as out of scope | 13–16 per tick, all residue of the pre-RC1 broad collection (14 code-P rows, 8 issuers: ALLE, AMT, AON, BSX, CINF, CZR, DVN, ECL) | `v2_companion.log` |
| Clusters (≥2 distinct owners within 10 trading days) | 3 episodes ever in RC1; **0 fired after campaign start**; 0 fresh-eligible now | `processed_episodes`; funnel |
| Admission | ABCL `07242bc8…` eligible 08-17 → `SKIPPED_ENTRY_STALE`. ADC `19f814d1…` eligible 09-18 → `SKIPPED_NO_PRIOR_INTENT`. ABCL `7a91e5c1…` eligible 08-25 → `SKIPPED_ENTRY_STALE` | stored reason codes |
| Intents / orders / alerts | 0 / 0 / 0 (outbox empty) | ledger |

**Where activity stops: cluster construction.** In the 39-issuer scope, no new ≥2-insider cluster formed during the
campaign. The cause is **no qualifying clusters**. It is not incomplete acquisition, identity or parse rejection,
admission-policy rejection, configuration mismatch, or infrastructure failure.

**The three episodes.**
- **ABCL (eligible 08-17).** Two owners filed on 08-14, which predates the campaign by 5 weeks. It was stale on the
  first tick.
- **ADC (eligible 09-18).** Owners 1528153 and 1348490 filed on 09-17, so the cluster fired before the campaign was
  created on 09-21. The rule "no durable intent existed before this tick's OPEN phase" rejects a cold start. This is a
  launch-boundary effect, as recorded in RC1 Session 02.
- **ABCL (eligible 08-25).** This "new" episode was first seen on 09-29. When the 45-day lookback slid past the 08-14
  rows, the greedy grouping regrouped the remaining 08-18 and 08-24 filings, from two different owners, into a fresh
  cluster. That cluster is old and was correctly rejected as stale. **Observation only:** the sliding live window
  can re-cluster old filings into new episode IDs.

**Frequency context.** These are existing permitted reports; nothing was recomputed and no returns are used.
- `2026-09-30_v2_insider_cluster_validation.md` §6: of 4,173 V2-eligible episodes over the bulk history
  (2019Q1–2026Q2), **63 fell in the 39-name scope**, roughly 8 per year. Over a ~2.4-week campaign that is fewer than
  one expected episode.
- `watchlist_coverage.py` records about 1–2 entries per year on the 43-name subset (Task 116).

Zero trades so far is consistent with both. The same report's verdict for V2@1 as implemented is `UNSUPPORTED`; it
is cited here only as context for the decision below.

**Contrast.** On 2026-09-15 the pre-release lane ran broad discovery (scope 626, before RC1). Its checkpoint funnel
showed 4 clusters (ABCL, APTV, BSX, CE) and 19 near-miss issuers within a week.

## 5. V2 forward tracker (operational status only)

This is a different process from the live companion. Its success says nothing about the companion's coverage.

| Item | Value |
|---|---|
| Run identity | run `20261007T060000Z-bdd85a`, scheduled 06:00:00Z, started 06:00:00.24Z, ended 06:03:55Z, state `SUCCESS` |
| Stages | edgar_crawl, episodes, prices, evaluate, forward: all SUCCESS, **0 retries**, exit 0, empty stderr. Acquisition `COMPLETE_WITH_EVENTS` (crawl 2026-09-30..2026-10-06) |
| Cutoffs (fixed) | as_of 2026-10-07; filing-date max 2026-10-06; price end 2026-10-06 |
| Artifact | `results/v2_validation/forward/2026-10-07.json` exists (67,009 B); `validated: true`, no problems |
| Next run | the loop (`forward_daily_v2.sh`, pids 24096/13172) is sleeping to the next slot, **2026-10-08 06:00Z** |
| End date | stop date **2026-10-31**, unchanged (commit `51aa8b3`) |

**Exposure disclosure.** While reading the end of `results/v2_validation/forward.log` for the run-status line, the
last lines of an earlier summary block were also printed: a `…subset_net_+10` block with n, mean and profit factor.
These values were not used, recorded or interpreted anywhere in this audit. Future status reads should parse the JSON
status lines only.

## 6. DTU endpoint

- The collector loop (`tracker_dtu_collector.sh`) stops at **2026-10-08 00:15Z (01:15 BST)**, unchanged.
- A per-window final evaluation is documented in `results/dtu_shadow/daily.sh final W NEXT`: 00:20Z, running
  `dtu_eval` + `verify_contract` + `harm_check`.
- The last `*_final.txt` checkpoint is for **2026-09-30**. No final job is armed for 10-01..10-07.
- No committed study-level final-evaluation procedure was found.
- Nothing was executed.

## 7. Recommendation (one action)

**Record an explicit owner decision on the V2-PAPER-RC1 study population (`UNIVERSE_CONTRACT_DECISION_REQUIRED` /
OPS-006).** The choice is one of:

- **(a) Ratify the 39-issuer scope as RC1's population.** RC1 continues unchanged, and expectations are labelled:
  fewer than one episode per month historically.
- **(b) Authorise a separate campaign on a wider population**, for example the 626 set.

**Dependencies for (b).**
- Intelligence polling must expand to about 569 resolvable CIKs. SEC load was benchmarked in Task 131/132.
- The 57 unresolved identities need resolving.
- Broad discovery requires both `--enable-broad-discovery` and the Intelligence broad-scope opt-in.
- A new campaign ID and a release-gate run are required.

**Study impact.**
- Widening RC1 in place would change its population mid-study. That makes it a **campaign/population change
  requiring an explicit deployment decision, not an automatic repair**.
- The V2 forward tracker (crawl-based, broad) is unaffected either way.
- The decision should also weigh the latest validation verdict (`UNSUPPORTED`, 2026-09-30).
- No implementation mismatch was found: the approved RC1 scope *is* 39. Option (b) would be a new scope, not a
  correction.

Nothing was implemented in this task.
