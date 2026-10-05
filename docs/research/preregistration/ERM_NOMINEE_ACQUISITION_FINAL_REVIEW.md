# ERM nominee: final acquisition and release-scope review

**Verdict: `READY_WITH_DECLARED_ACQUISITION_PREREQUISITE`.** The package is ready for the owner's lock decision, with one
declared prerequisite: window-B S&P coverage through 2026-09-30 **cannot be confirmed from publication metadata**. It
becomes the first request after a GO, and insufficient coverage stops acquisition as ACQUISITION_BLOCKED.

**NOT LOCKED, NO GO, NOT APPROVED.** Owner decisions D1, D2 and D4–D7 are pending, and recommendations are not
approvals. No lock, decision, GO, release or activation record exists.

Draft **r10** (`ERM_NOMINEE_PREREG_DRAFT_r10.md`) is the procedural successor of r9:

- r9 is preserved byte-exact (`fa59a9ca…a3a32b`).
- r10 changes procedure only (r10 §12). No strategy section, rule, gate, cost or statistical method changed.

This package supersedes the open items of `ERM_NOMINEE_ACQUISITION_IMPLEMENTATION_REVIEW.md` (`dc0c406`, preserved).

## 1 Baseline (verified 2026-10-06)

| Item | Value |
|---|---|
| Branch / start HEAD | `research/erm-nominee-validation-plumbing` @ `dc0c406` (equal to origin); implementation `a6006b8` |
| Start implementation aggregate | `5f893f47…60df` (matched) |
| r9 | `fa59a9cac2065006d0e9d5a9b5e53f95564f58c5309610369b7f565202a3a32b` (matched, unchanged) |
| Real ERM guard state | `b512322d…d6d30b5` before and after (every release test used temporary stores) |
| Release state | `production_guard` = ValidationGuard; no release store, protocol lock, decision record or GO record |
| Live runtime | `C:\workspace\TalonX` @ `0b2967d`, untouched |
| Duplicate smoke launcher | none pending: no `dev_smoke` process or scheduler sleep exists; the single smoke run completed (`SMOKE_EXIT 0`, 2026-10-05 20:33Z). It was not rerun. |

## 2 Submissions-page asymmetry: resolved

### The exact asymmetry, as implemented and as in the frozen development evidence

| Caller | Rule | What it reads |
|---|---|---|
| S2: R3 scope (`scope.build_scope` → `dev_filings`; port of `r3_metadata`) | The main JSON plus pages **overlapping** [filings_from, filings_to] | Only rows dated inside the window: R7 sic_end, the 5.06 split and R1b |
| S5: V2.1 evidence (`acquirer.issuer_evidence`; port of `subs_v2_fetch`) | Main plus **all** pages with filingFrom ≤ window end, but only for issuers **without** an S2 main | Not applicable |
| BUILD (V2.1 `builder.subs_reader`) | Every page present for the issuer | R1a "periodic filing ≤ D, any year", latest company filing ≤ D (PIT SIC header) and the 5.06 transitions |

**Can it omit filings or affect identity, R1 or SIC?**

- **Identity:** no. R3 identity uses only the main JSON, and V2.1 identity uses dated Form 3/4/5.
- **R1b and R7:** no. They read only in-window rows, so they cannot be affected.
- **BUILD:** yes, in principle. For an issuer resolved in S2, history pages lying wholly before the window were never
  fetched. If the issuer's only filing on or before D sat in such a page, V2.1 R1a availability or the PIT SIC would
  see "no filing", and the row would be excluded on missing evidence.

**Measured on the development evidence:**

- 482 of the 1,076 event issuers have such unfetched pages, all wholly before 2019-01-02.
- These issuers account for 966 manifest rows. **Zero of those rows are decision-sensitive:** every one already has a
  company filing on or before D in the fetched evidence (`sic_source` ARCHIVED or HEADER_WITHOUT_SIC), with R1a and
  S&P status settled.
- Unfetched older pages can only add filings older than the fetched SIC source. Under V2.1 instrument rule 1, a 5.06
  older than the SIC source does not count. So no development eligibility decision depended on them.
- Only the descriptive `s506_*` counts could differ, and they cannot be verified without fetching the old pages, which
  was not done.

### Fix (acquisition correctness; the V2.1 rule text is unchanged)

Each window now declares its page rule (`period.submissions_page_rule`):

- **A and B: `ALL_PAGES_TO_WINDOW_END`.** Every event issuer gets its main JSON plus every page that main advertises
  with filingFrom ≤ window end. That gives complete history to D, as V2.1 requires ("any year"; "latest company filing
  ≤ D").
- **DEV: `FROZEN_DEV_EVIDENCE`.** This is the development evidence exactly as acquired, and it is used only for the
  recorded replay.

Each page is enumerated from the authoritative main JSON fetched **in the same acquisition** and verified against that
main's advertisement. The checks are calibrated on all 431 archived development pages, every one of which satisfies
them exactly:

- row count = `filingCount`;
- first filing = `filingFrom`;
- last filing ≤ `filingTo` + 1 day, because SEC's `filingTo` lags by at most one day.

Failure handling:

| Case | Outcome |
|---|---|
| A page that keeps its name but changes coverage (the repagination seen live in the smoke test) | `MALFORMED_OR_INCOMPLETE_RESPONSE` ("REPAGINATION_OR_INCOMPLETE_PAGE"), a required failure → ACQUISITION_BLOCKED |
| An advertised page that returns 404 | Incomplete pagination, a required failure; never `LEGITIMATELY_ABSENT` |
| A malformed page | Required failure |
| Main JSON 404 | The only legitimate absence (the CIK has no submissions); the frozen unresolved policy then applies |
| Identical duplicate rows for one accession number (stable filing identity) | Collapsed in `builder.subs_reader` (the development evidence has zero duplicates) |
| Conflicting duplicate rows | `ValueError`; the build stops |

A complete, verified history that holds no qualifying filing is **evidence**, recorded in
`acquisition/issuer_history.json`. The frozen V2.1 policy then applies to it. An omitted page can never become an
exclusion, because it stops the run before build.

This changes acquisition, not eligibility semantics, so no protocol amendment is needed. The procedure is written down as
r10 T9, under D6.

## 3 Broad-endpoint and response scope: declared and enforced

**Two checks per request.**

1. **Before the request exists:** `guard.check_acquisition(content_from, content_to, category)`, where the content range
   is the response the endpoint can return, not the nominal query.
2. **After the response arrives:** a response-scope check against the declared envelope. A violation quarantines the
   bytes in `acquisition/scope_exceeded/` and records an exposure event and the state
   `RESPONSE_EXCEEDS_AUTHORISED_SCOPE`. The run becomes **RUN_INVALID** (`ScopeExceeded`), even for an optional input.

Filtering after download is never treated as making a response unexposed.

**Endpoint scope table.** R is the acquisition reference date named in the release; broad endpoints are bounded by R + 1 day. Windows: A = 2024-01-02..2024-12-31; B = 2024-01-02..2026-09-30.

| # | Endpoint | Category | Requested range | Can it restrict dates? | Broader content it can return; response check | Archived | May influence identity | May influence eligibility | Release authorisation needed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Alpaca `/v2/stocks/bars` (ALL and raw) | `bars` | 2023-11-01 (warm-up) .. window end; R1-kept ∪ R1a-removed, plus the 7 ETFs (ALL only) | yes | None; every bar must lie in [start, end] | all pages + frozen manifest | Volume continuity only (V2.1 trading-break rule) | Gap, L1 eligibility, prices, outcomes | **Price/outcome access** (bars envelope) |
| 2 | Alpaca `/v2/assets` (active, inactive) | `assets_current` | none (current) | no | Current asset list at retrieval: names, exchanges, post-window listing status | raw | No | Source A of the download scope; the `named` flag (frozen design) | **D7** broad: [history, R+1] |
| 3 | Alpaca corporate actions: `name_change` and mergers, calendar years | `corporate_actions` | window | yes | At least one primary date (process/ex) inside [start, end]; process, ex, effective, payable and record dates ≤ end + 60 d; any other date ≤ end | raw | In-window rename edges | Sources B/C; ticker on D | Window scope |
| 4 | Alpaca corporate actions: `name_change` after the window | `identity_renames` | A: 2025-01-01..R; B: 2026-10-01..R | yes (end = R exactly) | As row 3, with end R | raw; identity fields in `renames.json` | **Only to relabel the requested series' ticker on D** (T8) | No admission fact (T8) | **D7** post-window identity |
| 5 | Alpaca corporate actions: `cash_dividend`, 7 ETFs | `etf_cash_dividends` | window | yes | As row 3 | raw | No | Descriptive ETF leg only (optional input) | Window scope |
| 6 | SEC `company_tickers.json` | `sec_reference_current` | none | no | Current ticker→CIK map | raw | R3 CIK resolution (download scope) | R1a/R1b download scope only; V2.1 identity at D uses dated Form 3/4/5 | **D7** |
| 7 | SEC `cik-lookup-data.txt` | `sec_reference_current` | none | no | All entity names to retrieval | raw | R3 name matching | Download scope only | **D7** |
| 8 | SEC Form 3/4/5 data sets (quarterly) | `form345` | 2018Q1 .. window-end quarter | yes (per quarter) | Every FILING_DATE inside its quarter | zips | Dated ticker→issuer evidence ≤ D | Identity at D; S&P link | Window scope (2024+ quarters) |
| 9 | SEC `master.idx` (quarterly) | `master_idx` | window quarters | yes | Every row inside its quarter | raw | No | R1a availability (periodic ≤ D); R3 R1a | Window scope |
| 10 | SEC submissions main JSON | `submissions` | history | no | All filings to retrieval; nothing may be dated after R + 1 d | raw | R3 tickers / former names | V2.1 R1a / SIC / 5.06 from rows ≤ D only | **D7** |
| 11 | SEC submissions history pages | `submissions` | as advertised (filingFrom ≤ window end) | by page | Page coverage can move (repagination) → verified (§2); rows ≤ R + 1 d | raw | No | As row 10 | **D7** (same category) |
| 12 | SEC filing headers (`-index-headers.html`) | `filing_headers` | one accession filed ≤ window end | yes (one filing) | That filing's header; `FILED AS OF` ≤ scope end | raw | No | PIT SIC → instrument status, sector benchmark | Window scope |
| 13 | GitHub contents listing (fja05680) | `sp500_pit` | none | no | File names, git blob sha and size; no membership rows | raw | No | No (provenance, file choice) | **D7** |
| 14 | fja05680 historical S&P CSV | `sp500_pit` | none | no | Membership rows to the author's last update; ≤ R + 1 d enforced; git blob sha must equal the listing's | raw; materialised ≤ window end | No | Source D; S&P exemption (rows ≤ D) | **D7** |

**Proposed D7 wording (NOT YET GIVEN).** "Authorise acquisition of the broad metadata categories `assets_current`,
`sec_reference_current`, `submissions` and `sp500_pit` with content to R + 1 day, and of `identity_renames` from the day
after the window end to R. They are used only as tabulated: renames only to relabel the ticker on D, and every
eligibility predicate only from rows dated ≤ D. This is separate from, and not including, price and outcome access."

The release binds these envelopes exactly. `release.scope_envelopes` covers every category in the table, and a release
naming a wider, narrower or different scope is refused.

## 4 Post-window renames

- **Use:** only to reconstruct which ticker the requested (provider-relabelled) series traded under on D, through
  V2.1 `ticker_at`, whose predecessor edges must precede the edge they feed. No ticker reuse is chained through.
- **Not admission evidence:** a later rename cannot establish a filing, operating status, index membership or
  issuer: every V2.1 predicate reads evidence dated ≤ D. This is tested with:
  - future Form 3/4/5 evidence (identity stays UNRESOLVED);
  - an S&P row after D (NO_MEMBERSHIP_BY_D);
  - a periodic filing after D (R1a not available);
  - a 5.06 effective after D (UNRESOLVED_INSTRUMENT);
  - a reused ticker (not chained).
- **Fixed cut-off:** one acquisition reference date R is pinned in `acquisition/reference.json` at the first request,
  and identity renames are requested with end = R exactly, never "today". On resume:
  - asking for another R → `REFERENCE_DATE_MISMATCH`;
  - a release naming another R → blocked;
  - any broad request after R + 1 day → `RESUME_AFTER_REFERENCE_WINDOW`;

  each refused before any request is sent. Requests that are already USABLE are served from the archive and never
  re-requested, so provider as-of semantics cannot drift within one acquisition.

## 5 Window-B S&P coverage: `COVERAGE_UNCONFIRMED_UNTIL_AUTHORISED_ACQUISITION`

**Metadata-only evidence**, gathered 2026-10-05 23:11Z with no membership row downloaded:

- **GitHub contents listing** (`api.github.com/repos/fja05680/sp500/contents`, 200, sha256 `3e33b93c…280d`): files
  `S&P 500 Historical Components & Changes (Updated).csv` (5,530,907 B, blob `656b033b…`) and
  `S&P 500 Historical Components & Changes.csv`. **Neither file name carries an as-of date.** The previous dated
  naming, which the adapter assumed, is gone.
- **README** (sha256 `1b328209…df04`): "historical S&P 500 index membership from 1996 til MM-DD-YYYY", a
  **placeholder**, with an update cadence of "every couple of months".
- **Releases and tags:** none (0 / 0).
- **Not used:** commit timestamps (not coverage evidence) and the file's rows.

**Consequence: no metadata establishes coverage through 2026-09-30, or through 2024-12-31 for window A.** The adapter
was corrected to the real publication format:

- It selects the fixed file name and verifies the downloaded bytes' git blob sha against the listing.
- Coverage holds only if a membership row is dated ≥ the window end.
- S&P is the **first** request (S0). If coverage is insufficient, the file is absent from the listing or the blob does
  not match, acquisition stops as **ACQUISITION_BLOCKED** before any Alpaca, SEC or bar request.
- On a block, the exposure and ledger records are kept. The run is not scored, not labelled FAIL, not switched to
  window A and not given a substitute source.

The evidence files are under `results/erm_nominee_validation/sp500_metadata_check/`.

## 6 Release and failure semantics

**What the release binds:**

- the hypothesis and window;
- the config hash;
- the protocol-lock, implementation, owner-decision and separate GO-record hashes;
- the exact scope envelopes: warm-up bars, every metadata category, the broad endpoints (R + 1 d) and post-window
  identity (to R);
- R itself, which the acquirer must match;
- the ERM audit record and the ERM-owned Task75 consumption ledger.

**Fail-closed guarantees:**

- An interrupted activation (any journal prefix) refuses everything.
- A second activation is refused.
- A wider or narrower scope, another hypothesis, another window, a stale config or any changed hash is refused.
- A resume cannot widen scope: R is pinned and the retrieval window is enforced.

**Failure classes.** Every failed run records a `failure_class`. None of them is a statistical verdict; PASS, FAIL and
INCONCLUSIVE exist only in a COMPLETE run.

| Class | Meaning |
|---|---|
| IMPLEMENTATION_FAILURE | Code or invariant error before outcomes |
| ACQUISITION_BLOCKED | A required input could not be acquired with verified, sufficient coverage inside the authorised scope; this includes a guard refusal *before* sending (nothing exposed) |
| RUN_INVALID | r9 step 0: archive, hash or config verification failure, or a **response** exceeding the authorised scope (exposure) |
| INCOMPLETE_AFTER_OUTCOME_EXPOSURE | Any failure once outcomes may exist; no retry |

**Re-execution.** The behaviour is unchanged from r9 (pending D6): one re-execution after any pre-outcome failure, then
ABORTED_OWNER_DECIDES. Every attempt's archive, ledger and exposure records are preserved.

r9 does not say whether an ACQUISITION_BLOCKED attempt (no outcome produced) consumes that single re-execution. r10
proposes exact wording as **D6a** and does **not** change behaviour before the owner decides:

> "An attempt that ends ACQUISITION_BLOCKED before any outcome exists does not count as an execution attempt; its
> archive and exposure records are preserved; it is never retried automatically; a new attempt needs an explicit owner
> instruction and, if the reference date has passed, a new release."

## 7 Verification

### Focused tests: `tests/test_erm_nominee_acquisition_review.py`, 32 passed

All 32 run through the production orchestration with fixture transports and temporary release stores. After every test
the real guard state is asserted unchanged.

| Area | Tests |
|---|---|
| Submissions pages | Per-window rule; complete history for an S2-resolved issuer (pre-window 10-K now in the builder's evidence); repaginated page with an unchanged name ×3 (count, start, end), each blocked as ACQUISITION_BLOCKED with no build; the +1-day `filingTo` lag accepted; missing advertised page is incomplete pagination, not an absence; malformed page; identical duplicate accession collapsed; conflicting duplicate rejected |
| Response scope (all RUN_INVALID, quarantined, exposure recorded) | Corporate actions ×2 (out-of-range primary date; unknown late date field); ETF payable date beyond the lag (an optional input still invalidates); submissions row after R + 1 d; Form 3/4/5 row outside its quarter; header filed after the scope end; S&P row after R + 1 d; bars beyond the window end. An attribute date inside the lag is accepted. |
| Post-window renames | Ticker on D reconstructed; future Form 3/4/5, S&P, periodic-filing and 5.06 evidence never admits; ticker reuse not chained; identity-rename end = R even on R + 1 |
| Reference date | Resume after R + 1 d blocks before any request, while resume inside the window completes without repeating S0; resume with another R blocks; R must equal the release; a release with a wider broad-endpoint bound is rejected |
| S&P prerequisite | Last row before the window end and a git-blob mismatch both block with only GitHub requests made (no Alpaca, SEC or bars) and no gates or outcomes; file absent from the listing blocks |
| Failure classes | IMPLEMENTATION_FAILURE, RUN_INVALID (hash), INCOMPLETE_AFTER_OUTCOME_EXPOSURE; ACQUISITION_BLOCKED keeps the r9 re-execution rule and preserves `attempt_1/` records |

Interrupted release (3 prefixes), wrong config / protocol / implementation / GO / decision hashes, wrong-scope releases
and tampered audit records remain covered in `tests/test_erm_nominee_acquisition_e2e.py`. All 44 of those tests pass,
with their S&P fixtures updated to the real publication format.

### Regression

**208 passed** across:

- validation workflow (19) and plumbing (20);
- acquisition E2E (44) and review (32);
- V2 rules;
- accounting fixtures;
- the frozen event-response map.

### Development parity (rerun because the acquirer and builder changed): **`REPLAY_PARITY_PASS`**

The record is `results/erm_nominee_validation/dev_replay_review/replay_record.json`. It ran against the reviewed code on
2026-10-05 between 23:22Z and 23:40Z, using archived development bytes only. Earlier replays are preserved.

- **Candidates and scope:** 10,772 candidates, with sources and names identical. Kept / R1a / R1b counts are 7,613 /
  2,769 / 390, all equal; identity CIK diffs 0.
- **Bars:** 1,339 + 128 pages, every sha256 and aggregate equal.
- **Manifest:** 2,752 rows with 0 field diffs; duplicate and unresolved sets are equal. `manifest.csv` `3824fa6a…dfcb`
  and `duplicate_groups.csv` `ba05509a…a222` are **byte-identical to development parity**.
- **New checks on real development responses:** they passed on 7,365 submissions files (page verification), 8,080
  headers (`FILED AS OF` bound), 10 + 5 + 5 corporate-action responses (envelopes), 24 Form 3/4/5 sets and 20
  `master.idx` quarters (quarter bounds), and the S&P S0 check (coverage last row ≥ 2023-12-31).
- **Archive manifest:** 16,966 files, complete, sha256 `00c93a4c…3823`.

No outcome, gate or metric was computed.

## 8 Hashes

| Item | Value |
|---|---|
| Implementation aggregate (`release.implementation_hash`) | `24a9e262b4b34971ab0bf104bf2c20c5fafe84328011442f99c7ff0212f6f81b` (was `5f893f47…60df`) |
| Draft r10 | `e6385dd04b3553bca958efc324aead0734bad96c731dbd58c3d382219e899929` |
| Draft r9 (preserved) | `fa59a9cac2065006d0e9d5a9b5e53f95564f58c5309610369b7f565202a3a32b` |
| Changed modules | `acquisition/acquirer.py` `f0f67d19…`; `acquisition/period.py` `6f20c4ec…`; `acquisition/states.py` `b8538c5e…`; `acquisition/replay.py` `f5ba852c…`; `builder.py` `d30fce04…`; `workflow.py` `8dd2519d…`. `release.py` is unchanged (`e5319311…`). |
| Frozen modules | unchanged: `v2_rules.py` `a4e3b82d…`, `data.py`, `events.py`, `identity.py`, `universe*.py`, `r3_metadata.py`, `metrics.py`, `locked_range_guard.py`, `research_stats.py` |

Per-file hashes are in `ERM_NOMINEE_ACQUISITION_FINAL_REVIEW.json`. The aggregate changes with any code edit; the lock
records the value at lock time.

## 9 Remaining owner decisions (exact)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Window A or B | B (r10 §8), with the reserve trade-off and the S0 S&P prerequisite |
| D2 | Acknowledge consumption of the Task75 reserved windows (and the 2025–2026-09 reserved data) | Acknowledge |
| D4 | Minimum-sample floor (n < 100 or dates < 40 → INCONCLUSIVE) | Adopt |
| D5 | ETF cost: primary 4 bps (unmeasured), with 0/12/20 bps descriptive | Accept as labelled |
| D6 | Procedural conventions, including the r10 T5/T9–T11 acquisition procedure and the step-0 wording | Approve |
| D6a | Whether ACQUISITION_BLOCKED (no outcome) consumes the single re-execution | Adopt the proposed wording |
| D7 | Broad-metadata and post-window identity scope exactly as tabulated (§3), separate from price/outcome access | Authorise as tabulated |

## 10 Proposed owner approval statement: **NOT YET GIVEN**

> "Choose window B, acknowledge consumption of the overlapping Task75 reserved windows and the reserved
> 2025–September 2026 data, adopt the 100-event/40-date floor, accept the declared ETF-cost assumptions and
> descriptive sensitivities, and approve the final procedural conventions of draft r10, including the T5/T9–T11
> acquisition procedure and the D6a wording. Authorise the broad-metadata and post-window identity scope exactly as
> tabulated in the final acquisition review (categories `assets_current`, `sec_reference_current`, `submissions` and
> `sp500_pit` to the reference date plus one day; `identity_renames` from the day after the window end to the
> reference date), separately from price and outcome access. Accept that window-B S&P coverage through 2026-09-30 is
> unconfirmed until the first authorised acquisition request, and that insufficient coverage stops the run as
> ACQUISITION_BLOCKED without scoring, a FAIL label, a substitute source or a window switch. Authorise locking draft
> r10 and the reviewed implementation only. Do not release guards or run validation until a separate GO."

## 11 Confirmations

- No protected validation membership, prices, filing contents or outcomes were acquired. The only network calls were
  three metadata-only GitHub requests (listing, README, releases/tags); no membership file was downloaded.
- No guard was lifted, no reserve consumed, no GO, activation, lock or decision record created, and no validation
  executed.
- The nominee, eligibility rules, statistical method and costs are unchanged; no window switch was made.
- No development scoring run was made. The replay rebuilds the manifest only, with no outcome, gate or metric.
- Live services, trackers and schedules are untouched, and the smoke test was not rerun.
