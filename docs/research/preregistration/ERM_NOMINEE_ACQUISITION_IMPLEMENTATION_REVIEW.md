# ERM nominee: production acquisition implementation review package

**Status: IMPLEMENTATION REVIEW PACKAGE. NOT LOCKED, NO GO, NOT APPROVED.** This package records an engineering
completion. It does not lock a protocol or the implementation, does not record any owner decision, does not release
any guard and does not authorise validation. Draft r9 (`ERM_NOMINEE_PREREG_DRAFT_r9.md`, sha256 `fa59a9ca…a3a32b`) is
unchanged and remains the governing draft; no new draft was needed, because no procedural wording changed.

Hypothesis: `GAP_UP_10|SHORT|H10|L1` under correction spec V2.1 (freeze `aab578e`; corrected development result `b91dc0a`).
Owner decisions D1, D2 and D4–D6 are still pending, and window B is recommended but not approved. The fixtures exercise
a proposed configuration (window B, `etf_cost_bps=4`), but they approve nothing.

The implementation is at commit `a6006b8`; the evidence and this package are in the commit that adds this file. Both are on branch
`research/erm-nominee-validation-plumbing` (worktree `C:\workspace\TalonX-erm-val`).

## 1 Execution path

```
run.py --window A|B --execute
  -> ValidationConfig(decisions from the committed decision record; none exists -> every field pending)
  -> release.production_guard(cfg)        ValidationGuard (refuses everything) unless a valid ACTIVE release journal
  -> adapters.ProductionAcquirer(guard)   acquisition/acquirer.ProductionAcquirer over transport.HttpTransport
  -> adapters.ProductionLoader(guard)
  -> workflow.run_validation
       precheck: cfg.require_decided() ; guard.authorise(auth)            (before any request or run state)
       ACQUIRE -> LOAD -> BUILD -> OUTCOMES -> GATES -> DIAGNOSTICS -> REPORT -> MARKER
```

Every provider request passes through these steps in order:

1. `acquirer.get` checks the request with `guard.check_acquisition(content_from, content_to, category)` before the
   request is built.
2. `transport.fetch` sends it under the live policy: the R5 off-hours rule (weekdays 09:00–16:30 ET are refused);
   provider spacing of 1.6 s for Alpaca bars, 2.0 s for Alpaca metadata, 0.34 s for SEC and 1.0 s for GitHub; and
   bounded retries on 429, 5xx, timeouts and connection errors (4 attempts, backoff 2/4/8 s, `Retry-After` honoured up
   to 60 s).
3. The result is classified into one evidence state.
4. An append-only ledger record (fsync'd) is written.

Bars use the frozen `data.Downloader` unchanged. Its opener is routed through the same transport, and its
`check_range`/`record` calls are routed to the acquisition guard and the acquisition ledger. The frozen guard state is
never written.

The credentials are the existing `.env` keys, read by `universe_source.headers()`, plus the frozen SEC user agent.
Headers are never recorded.

## 2 Staging (acquirer S1–S8)

| Stage | Content | Network? | Outcome data? |
|---|---|---|---|
| S1 BASE | Asset list; in-window name changes and mergers (calendar-year requests clipped to the window); identity-only renames; SEC `company_tickers` and `cik-lookup`; Form 3/4/5 2018Q1 to window end; `master.idx` for window quarters; S&P list with an explicit as-of date | yes | no |
| S2 SCOPE | Candidates A–D, then R3 identity (two passes), R1a, R6 intervals, R7 dated SIC and R1b (`scope.build_scope`, a port of `r3_metadata.main`) → R1-kept and R1a-removed sets; submissions and R7 headers fetched on demand | yes (SEC) | no |
| S3 BARS | Frozen Downloader in two groups, exactly as Phase D: KEPT (RETURNS = kept + 7 benchmark ETFs; ELIGIBILITY_ONLY = kept) and R1A_REMOVED, from `bars_from` (warm-up) to the window end | yes | prices only |
| S4 EVENTS | Gap days, L1 eligibility and V2.1 identity at D (`candidate_events.json`: dates, symbol, issuer and identity only). No exit session, forward price or return is computed | no | **no** |
| S5 EVIDENCE | Issuer submissions (rule SUB-2), then the point-in-time header of each issuer's latest company filing on or before D, read through the builder's own `subs_reader` | yes (SEC) | no |
| S6 ETF | Cash dividends for the benchmark ETFs (**optional**) | yes | no |
| S7 COMPLETE | Every required request must be USABLE or LEGITIMATELY_ABSENT; otherwise `AcquisitionFailure` stops the run before build | no | no |
| S8 MATERIALISE | Loader-format files, `acquisition_status.json`, per-category evidence indexes, then `ARCHIVE_MANIFEST.json`, written last | no | no |

After S8, the workflow continues with LOAD, which verifies every sha256 before parsing. Then BUILD constructs the
network-free V2.1 manifest. Only after that does OUTCOMES run.

Candidate discovery (S4) and outcome computation (OUTCOMES) are separate code paths. The archive and manifest are
complete and hashed before any outcome is computed.

### Coverage per input category

Coverage is defined explicitly in `acquisition/period.py`. No global date constant is mutated for acquisition.
`builder.window_bounds` is the only place that substitutes the frozen `events.DEV_START/DEV_END`, and it now holds a
process-wide lock.

| Category | DEV | A | B | Required |
|---|---|---|---|---|
| bars (raw + ALL, incl. warm-up) | 2018-11-01..2023-12-29 | 2023-11-01..2024-12-31 | 2023-11-01..2026-09-30 | yes |
| corporate actions (B/C, renames) | 2019-01-01..2023-12-31 | 2024 | 2024-01-01..2026-09-30 | yes |
| identity-only renames | frozen Task75-skipping post-2023 ranges | 2025-01-01..download date | 2026-10-01..download date | yes |
| Form 3/4/5 | 2018Q1..2023Q4 | 2018Q1..2024Q4 | 2018Q1..2026Q3 | yes (404 = INSUFFICIENT) |
| master.idx | 2019Q1..2023Q4 | 2024Q1..Q4 | 2024Q1..2026Q3 | yes |
| submissions | broad (history to retrieval) | broad | broad | yes per CIK (404 = ABSENT) |
| filing headers | ≤ window end | ≤ window end | ≤ window end | yes per accession (404 = ABSENT) |
| S&P PIT list | rows 2019..2023 | rows 2024 | rows 2024-01-01..2026-09-30, as-of ≥ 2026-09-30 | yes |
| ETF cash dividends | 2019..2023 | 2024 | 2024-01-01..2026-09-30 | **optional** |

### Broad endpoints

Some endpoints necessarily return more than the date scope. These are:

- the current asset list;
- the SEC reference files;
- the submissions main JSON;
- the S&P CSV.

Each one is guarded under its own category with `content_to` set to the retrieval date. As a result, any protected
period needs an explicit release-scope entry that names that category. After retrieval, rows dated past the scope end
are dropped before any other field is read, and the S&P CSV is materialised only up to `sp500_to`. The raw bytes are
kept for provenance.

In this task those endpoints ran only against fixtures and archived development bytes. The network smoke test
requested none of them.

## 3 Evidence states and completeness

The five states are defined in `acquisition/states.py`:

| State | Meaning | Effect |
|---|---|---|
| `RETRIEVED_USABLE` | Retrieved, parsed and valid | Usable |
| `RETRIEVED_LEGITIMATELY_ABSENT` | SEC 404 for a specific submissions file or header | Frozen unresolved policy, with recorded status and rationale |
| `INSUFFICIENT_HISTORICAL_COVERAGE` | Form 3/4/5 or `master.idx` 404 (not yet published), or S&P as-of date before the scope end | Required → stop |
| `TRANSPORT_OR_PROVIDER_FAILURE` | Network error, timeout, exhausted 429/5xx, R5 refusal, replay miss | Required → stop; optional → recorded |
| `MALFORMED_OR_INCOMPLETE_RESPONSE` | Unparsable, missing keys, or truncated pagination | Required → stop; the body is quarantined in `acquisition/malformed/` |

Three guarantees follow from this:

- A failed request is never converted into an exclusion, an empty universe, a SPY fallback or a successful archive.
- A required failure stops the run before build.
- The only optional input is ETF dividends. If that input fails, the descriptive dividend leg becomes `UNKNOWN`,
  recorded in `acquisition_status.json`.

**Absent SIC header.** A legitimately absent SIC header follows the frozen V2.1 instrument rules:

- rule 5: a verified S&P member becomes OPERATING_SECTOR_UNKNOWN, with SPY as the explicit frozen benchmark;
- rule 6: anything else becomes UNRESOLVED_INSTRUMENT and is excluded.

This applies only to a recorded ABSENT state, never to a failure.

**Resume and provenance.** The ledger records:

- source;
- request scope;
- retrieval time;
- HTTP status;
- attempts;
- path;
- sha256;
- byte count.

On resume, a request already USABLE or ABSENT is never requested again. Bytes are written once: a later revision is
stored as `<path>.rev-<sha8>` alongside the earlier bytes. A partial bar group is moved to `bars_incomplete/<group>_<n>`
and redone from scratch. Bar pages carry their provenance (scope, symbols, sha256, retrieval time) in the frozen
Downloader manifest and `events.jsonl`. The store only ever writes inside the run's own archive, never to the frozen
development evidence.

## 4 Scoped release: built but inactive

The release is implemented in `release.py`. It has no guard-disable option.

**What a ReleasedGuard requires.** It exists only when `load_release` validates a complete journal and the following
hold:

- **Owner decisions:** `require_decided()` passes.
- **Hypothesis:** exactly `GAP_UP_10|SHORT|H10|L1`.
- **Window:** A or B, equal to the configured window.
- **Config hash:** equal.
- **Hashes:** `protocol_lock_sha256` (`ERM_NOMINEE_PROTOCOL_LOCK.json`), the implementation sha256 (aggregate over
  `research/erm_nominee_validation/**/*.py` plus 11 frozen modules), the owner-decision record and a **separate** GO
  record all equal their current files.
- **GO record:** names exactly this hypothesis, window, hashes and scope.
- **Scope:** exactly equal to `scope_envelopes(window, download_date)`. A wider scope, a narrower scope or an
  additional category is refused.

**Transition.** The journal moves through PREPARED → ERM_AUDIT_WRITTEN → TASK75_LEDGER_WRITTEN → ACTIVE. Each step is
fsync'd and written once. The ERM audit record and the ERM-owned Task75 reserve-consumption ledger must both name the
same release id. The ledger must also equal the overlap of the scope with the reserved windows, and both records must
still match the hashes in the journal. Every hash is re-checked when the release is loaded.

Failure handling:

- An interrupted transition, at any prefix of the journal, is incomplete and refuses every request.
- A store that already holds a journal refuses a second activation.
- The original Task75 study is never modified or released.

**Why it is inactive now:**

- `production_guard` finds no store at `results/erm_nominee_validation/guard_release` and returns ValidationGuard.
- `activate` is a library function with no CLI.
- `activate` would refuse anyway: owner decisions are pending (OwnerDecisionPending), and the protocol-lock, decision
  and GO records do not exist.
- `run.py --window B --execute` raises OwnerDecisionPending before any request.
- All release tests use temporary fixture stores, and an autouse fixture asserts that the real guard-state sha256
  (`b512322d…`) is unchanged after every test.

## 5 S&P coverage adapter

`acquirer.sp500` lists the fja05680 repository, parses the as-of date from each dataset filename and selects the
latest. If that date is earlier than the scope end, the result is INSUFFICIENT; membership is never assumed unchanged.
The CSV header is validated and the file is materialised only up to `sp500_to`.

The fixtures show:

- an as-of date of 2026-09-30 is accepted for window B;
- 2026-06-30 is rejected as INSUFFICIENT;
- rows after 2026-09-30 are never materialised.

**Source-availability uncertainty.** The local point-in-time file ends on 2026-06-30. Whether fja05680 has published,
or will publish, a dataset with an as-of date of 2026-09-30 or later was **not checked**, because doing so would mean
inspecting validation-period source metadata. If no such dataset exists, window B stops at S1 with
INSUFFICIENT_HISTORICAL_COVERAGE. Window A needs an as-of date of at least 2024-12-31, which the existing source covers.

## 6 Verification

### (A) Recorded development replay: `REPLAY_PARITY_PASS`

The replay ran the production acquirer S1–S8, the production loader and `workflow.build_rows` against archived
development bytes only (`acquisition/replay.py`, with no network). Two inputs had to be reconstructed because their
raw responses were never archived: the asset list (rebuilt from `candidates.json`) and the corporate-action pages
(rebuilt from the archived parsed rows by process date).

Results from `results/erm_nominee_validation/dev_replay/replay_record.json`, run at the implementation commit
2026-10-05 17:46–18:04Z:

| Check | Production path | Frozen development evidence | Result |
|---|---|---|---|
| Candidates A–D | 10,772 (sources and names identical) | 10,772 (`candidates.json`) | equal |
| R1-kept / R1a-removed / R1b-removed | 7,613 / 2,769 / 390 | `candidates_r3.json` | equal; identity CIK diffs 0 |
| Bar pages KEPT / R1A_REMOVED | 1,339 / 128 | Phase D `alpaca` / `alpaca_diag` | every page sha256 and the aggregate equal |
| Requests by category | submissions 7,365; headers 8,080; Form 3/4/5 24; `master.idx` 20; corporate actions 10; identity renames 5; ETF 5; reference 2; assets 2; S&P 2 | — | all RETRIEVED_USABLE |
| Archive manifest | 16,966 files, complete, sha256 `68db99b7…a969a` | — | complete |
| Candidate events (S4) | 2,752 (symbol, entry) | 2,752 manifest rows | same keys |
| V2.1 manifest (LOAD → BUILD) | 2,752 rows; `manifest.csv` `3824fa6a…dfcb`; `duplicate_groups.csv` `ba05509a…a222` | frozen V2.1 manifest; recorded dev-parity hashes | 0 field diffs; duplicate and unresolved sets equal; **byte-identical** to dev parity |

An earlier replay run, made before three store fixes (gz naming, per-category evidence indexes, empty bar groups), is
kept in `dev_replay_prefix_attempt/`. It also passed with identical parity.

The run made 15,519 guarded checks before requests. There were **zero replay misses**: every submissions file, header,
Form 3/4/5 set, index and bar page the production rules requested exists in the frozen development evidence.

### (B) Development-only network smoke test

**Result: `SMOKE_PASS`.** The run used live `HttpTransport` at the implementation commit, started 2026-10-05 at
20:33:01Z (after the R5 window closed) and finished at 20:33:16Z. The record is
`results/erm_nominee_validation/dev_smoke/smoke_record.json`.

The request set was predeclared in `acquisition/dev_smoke.py` before the run. The guard was a DevelopmentAcquisitionGuard
with **no** broad endpoint authorised. The run made 9 guarded checks (bars ×2, corporate actions ×2, ETF dividends,
Form 3/4/5, `master.idx`, one history page and one header). All 7 ledger records are RETRIEVED_USABLE, with no
failures.

Not requested: the asset list, `company_tickers`, `cik-lookup`, the submissions main JSON, the S&P CSV and post-period
renames.

| Item | Fresh vs archived development bytes | Result |
|---|---|---|
| Bars, frozen Downloader through the transport: RETURNS AAPL/MSFT/SPY and ELIGIBILITY_ONLY AAPL/MSFT, 2019-01-02..01-31 | 21 sessions each; identical dates; schema `t,o,h,l,c,v,n,vw` identical; 0 OHLCV value differences | equal |
| Corporate actions 2019-01 | renames 0 = 0; mergers 14 = 14, identical ids and fields | equal |
| ETF cash dividends 2019 (7 ETFs) | 28 = 28, identical (symbol, ex_date, rate) | equal |
| Form 3/4/5 2019q1 | **byte-identical**; 21,311 ticker observations equal | equal |
| `master.idx` 2019 QTR1 | **byte-identical**; 297,116 lines; 5,920 periodic CIKs equal | equal |
| Submissions page `CIK0000004904-submissions-001.json` | same schema (16 keys); **revised**: SEC has re-paginated it (fresh 2,000 rows 2000-03-24..2019-12-05; archived 2,002 rows 1999-12-06..2019-09-18; 17/19 rows differ at the page edges) | schema equal; content revised |
| Header `0000319815-19-000056` | SIC 3690 = 3690; the only byte difference is an SEC-injected `<script src=…>` path after `</SEC-DOCUMENT>` | semantically equal |

What the revisions mean:

1. **Submissions page boundaries are not stable over time; the same file name can hold a different date range.**
   Production is unaffected for two reasons. It always selects pages from the main JSON fetched in the same
   acquisition. And the builder reads the union of the main and its pages filtered by filing date, so a filing is
   never lost by repagination as long as the main and its pages are fetched together.

   A consequence for provenance: page hashes from different retrieval dates are not comparable, and the frozen
   development pages cannot be re-verified byte-for-byte against SEC today. The archived bytes remain the development
   evidence.
2. **SEC HTML wrappers carry a per-request script path, so header byte-hashes differ on every retrieval.**
   Provenance hashes are therefore per retrieval. The parsed SIC is the semantic content.
3. **The smoke test guarded the history page by the range the archived main declared (to 2019-09-29).** The fresh page
   ran to 2019-12-05. That is still development-dated, so no protected content was received.

   This is exactly why production guards submissions as a broad category with `content_to` = the retrieval date
   (§2): a declared page range is not a reliable content bound.

### (C) End-to-end fixtures: 44 passed

These run in `tests/test_erm_nominee_acquisition_e2e.py`. The production orchestration is exercised with only the
transport substituted (FixtureProvider inside the production RetryingTransport) and a ReleasedGuard from a temporary
store. They cover:

- **Success:** the run reaches report and marker, with staging order and outcome-free candidate events.
- **Pagination:** bars and corporate actions paginate; truncated pagination is classified MALFORMED.
- **Retries:** 429 and connection resets are retried to success; exhausted retries give TRANSPORT with no empty
  universe.
- **Failures that stop the run:** bars failure stops before S4; malformed submissions stop at S2; incomplete S&P
  coverage and an unpublished Form 3/4/5 quarter both give INSUFFICIENT.
- **Required versus optional:** optional ETF failure is recorded and the run completes; a header 404 is ABSENT and
  follows the frozen policy; a required header transport failure stops the run.
- **Resume:** no duplicate requests and no replaced bytes; a partial bar group is preserved and redone; revisions are
  stored alongside earlier bytes.
- **Hashes and staleness:** an archive hash mismatch fails at LOAD; stale config is rejected; changed protocol,
  implementation, GO or decision hashes are rejected.
- **Release scope:** wider, narrower, extra-category, other-hypothesis, other-window and other-config releases are
  rejected; so are a GO record with a different scope and an authorisation naming another release; the guard refuses
  out-of-scope requests and unknown categories.
- **Transitions:** interrupted transitions (3 prefixes) fail closed, including through `production_guard`; the Task75
  ledger is consistent; a tampered audit record invalidates the release.
- **After outcomes:** a failure after outcomes allows no automatic retry.
- **Before authorisation:** no protected request is made.
- **Inactive production path:** the production guard is inactive and the runner refuses.
- **Development guard:** it refuses protected and unauthorised broad requests, including the Task75 windows.
- **Live transport policy:** off-hours refusal happens before any request, `Retry-After` is honoured, retries
  exhaust, and a 404 is returned for classification.

### Regression

All ERM suites pass: 176 tests (validation workflow and plumbing, acquisition E2E, V2 rules, accounting fixtures and
the frozen map). Builder rules are unchanged; the only builder change is the `window_bounds` lock.

The replay manifest parity (2,752 rows, zero field differences against the frozen V2.1 manifest) is the development
parity for the production path. No new research scoring was run: no outcome, gate or metric was computed in this
task.

## 7 Items for final review

These are possible substantive amendments. **None is adopted.**

1. **Submissions-page asymmetry, frozen as found.**
   - SUB-1 (R3): CIKs in the candidate scope get their main file plus pages overlapping the filing window.
   - SUB-2 (V2.1 audit): verified event issuers without an S2 main get every page with filingFrom on or before the
     window end.

   Effect: an issuer resolved in S2 never gets pages wholly before the window, which could matter for
   `r1a_available` or the latest company filing in the earliest weeks. A uniform SUB-2 rule would be an amendment.
2. **Broad endpoints in A/B.** These include content after the window end (for A, 2025+ filings, the asset list and
   renames). This is unavoidable at the endpoint and dropped before use, but it requires the owner's explicit release
   scope.
3. **Window A identity renames.** These span 2025-01-01 to the download date, past the window, mirroring the frozen
   post-2023 design. They need explicit scope.
4. **Benchmark symbols.** If a benchmark symbol ever enters the kept scope (for example as an S&P member), the frozen
   `request_params` refuses raw benchmark bars and acquisition stops (fail closed).

## 8 Final lock checklist (open items)

- [ ] Owner decisions D1, D2 and D4–D6 recorded in `ERM_NOMINEE_OWNER_DECISIONS_<W>.json` (window A or B chosen;
      Task75 reserve acknowledged).
- [ ] Decide on the §7 items (no amendment proposed by default).
- [ ] Confirm the S&P source publishes an as-of date on or after the window end (window B), or choose A.
- [ ] Final review of this implementation at `a6006b8`; record the implementation sha256 (currently
      `5f893f47…60df`; it changes with any code edit).
- [ ] Protocol lock record `ERM_NOMINEE_PROTOCOL_LOCK.json` (r9, or a successor if amended), with its sha256.
- [ ] A separate GO record naming hypothesis, window, config hash, protocol and implementation hashes, and exact scope.
- [ ] A reviewed activation step (no CLI exists) that writes the production release store, followed by `load_release`
      verification.
- [ ] Only then: off-hours production acquisition with `run.py --window <W> --execute`.

## 9 Confirmations

- No validation-window input or outcome was acquired, inspected or counted. The smoke test requested only predeclared
  development-dated items; the replay used archived development bytes only.
- No reserve was consumed and no real guard state changed (`b512322d…` before and after; every release test used a
  temporary store).
- No final lock, GO or validation run took place. No protocol-lock or GO record exists.
- r1–r9, V1/V2/V2.1, Gate D, the development results and the frozen archives are untouched. The replay wrote only
  under `results/erm_nominee_validation/dev_replay*`.
- The live runtime and checkout (`C:\workspace\TalonX` at `0b2967d`) are untouched.
