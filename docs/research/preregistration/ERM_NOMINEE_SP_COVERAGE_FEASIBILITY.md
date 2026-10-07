# ERM nominee: S&P coverage blocker feasibility review (2026-10-07)

**Verdict: `COVERAGE_NOT_ESTABLISHED_KEEP_PARKED`.**

**Recommended route.** Keep `GAP_UP_10|SHORT|H10|L1_V1` parked under `PARKED_DATA_COVERAGE_BLOCK`, with a defined
**zero-amendment reactivation trigger** (Route A). A bounded source amendment (Route B) and a paid source (Route C) are
documented below as owner options. Neither is recommended now.

This is design only:
- nothing is implemented or executed;
- locks, release, guards and attempt ledger are unchanged;
- the remaining D6a retry is unused.

Baseline (verified): branch `research/erm-nominee-validation-plumbing` @ `4cda47a`, equal to origin; lock verify PASS.
This report lives on the isolated branch `research/erm-nominee-sp-coverage-feasibility`.

## 1 Why the workflow needs S&P coverage through 2026-09-30

The callers below were traced in the locked code.

| # | Caller | Rows read | Effect | Coverage it actually needs |
|---|---|---|---|---|
| 1 | Candidate source D: `scope.build_candidates` → `sp_members(csv, sp500_from, sp500_to)` | every snapshot dated 2024-01-01..**2026-09-30** (any-day membership) | adds S&P members to the candidate universe and download scope ([MAP→W] source D) | through **2026-09-30**: a member added after the last row would be missing from the universe |
| 2 | R3 R1a exemption: `scope.build_scope` → `r1a_reason(…, pit, exempt=True)` | the same window set | spares S&P members from R3 R1a removal. This only moves symbols between the KEPT and R1A_REMOVED download groups; both are downloaded | through 2026-09-30 (download scope only) |
| 3 | V2.1 per event: `builder.build` → `R.sp_exempt(ticker_at_D, issuer, D, sp_rows, …)` | snapshots dated 2018-01-01..**D** | `sp_evidence = VERIFIED` (a) exempts unnamed issuers from V2.1 R1a and (b) gives instrument rule 5 (no dated SIC → OPERATING_SECTOR_UNKNOWN → SPY benchmark) | through the **last decision-relevant gap day**: entry is the session after D and exit is entry + 10 sessions ≤ 2026-09-30, so D ≤ **2026-09-15** |
| — | `identity.build_identity(…, pit)` | — | the parameter is accepted but **unused** | none |
| — | Acquirer S0 (`acquirer.sp500`) | whole file | the global check: a full snapshot dated ≥ `sp500_to` (2026-09-30) | the check enforces caller 1's requirement |

**Conclusions.**

- **The global criterion follows from caller 1.** The locked universe definition is "any-day S&P membership through
  the window end". Per-event logic (caller 3) needs less, only through 2026-09-15, but the last row (2026-08-18)
  fails that too. Relaxing the criterion would not unblock the run, so it is not a fix.
- **The criterion is not wrong for change-date snapshots.** Coverage through T means "no unrecorded change in
  (last row, T]". A snapshot dated ≥ T shows the source's record extends past T. Without one, the record's horizon is
  unknown.
- **Classification:** under the locked evidence alone, the source has no verifiable coverage horizon beyond
  2026-08-18. The inadvertent exposure below adds that **membership changes did occur after 2026-08-18 and before
  2026-09-30** (a quarterly-rebalance change set effective 2026-09-21), and that the source had not recorded them by
  the 2026-10-06 retrieval. So the blocker is **genuine missing membership evidence** for the window's tail, not
  merely an unverifiable horizon.

## 2 Recovery routes (public documentation and metadata only)

### Route A: existing source, no amendment (recommended reactivation path)

| Aspect | Finding |
|---|---|
| Source | fja05680/sp500, `S&P 500 Historical Components & Changes (Updated).csv` (https://github.com/fja05680/sp500) |
| Proven | full membership snapshots dated at index changes; last row 2026-08-18; file blob `656b033b…`, sha256 `36326709…` (closeout) |
| Unverified | update date or cadence (README: "every couple of months", informal); no published as-of date, releases or tags |
| What would establish coverage | a later version containing a full snapshot dated **≥ 2026-09-30**. A row for the 2026-09-21 change set alone would still fail the locked rule; the next recorded change on or after 2026-09-30 is needed |
| Detection without exposure | the GitHub contents listing (file names, git blob sha, size; no membership rows) shows a **new blob sha** for the file. That indicates a new version, not coverage; coverage is decided only by S0 under a new authorisation |
| Identity, effective dates | unchanged from the locked rules |
| Cost / access | free, public |
| Amendment | **none**: the protocol, rules, implementation and criterion stay locked |

**Owner decisions needed to reactivate:**
1. A new release and GO with a **new reference date R′**. The current one lapses 2026-10-08T00:00Z.
2. Acceptance that R′ widens the broad-endpoint retrieval bound to R′+1. This is more post-window content: current
   asset list, SEC submissions and renames to R′.
3. **D6a status.** The ledger records 1 acquisition attempt. A new execution would be execution 2 of 2, the last
   permitted. D6a says the retry is "under the same locked rules and approved scope", and a new R′ is a new scope. The
   owner must decide explicitly whether a new release's execution counts as that retry; the safe reading is that it
   does. The ledger is **not** reset.

**Uncertainty:** the timing is unknown. The source may take weeks or months to record a change dated ≥ 2026-09-30.

### Route B: preserved baseline + authoritative change announcements (bounded source amendment; not recommended now)

| Aspect | Finding |
|---|---|
| Sources | baseline: the preserved 2026-08-18 snapshot (local archive, sha256 `36326709…`). Changes: S&P Dow Jones Indices public index announcements and press releases (https://www.spglobal.com/spdji/en/index-announcements/ ; PDFs under `spglobal.com/spdji/en/documents/indexnews/announcements/`; https://press.spglobal.com/) |
| Proven | the index provider publishes constituent changes publicly, with effective dates ("effective prior to the open of trading on …"), as dated PDFs and press releases |
| Unverified | **completeness**. There is no proof that every change in a period is in the retrieved set, and an absent announcement is not proof of no change. The methodology PDF (https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf) returned HTTP 403, so the announcement policy is unconfirmed. Enumerating announcements reproducibly (a search page) is unverified |
| Identity | announcements name issuers and tickers; mapping to provider series needs explicit rules (ticker on the effective date; class shares; same-day ticker changes) |
| Amendment class | **acquisition source + completeness criterion amendment**. The candidate rules are unchanged if reconstruction is exact |

**Minimal amendment, if the owner chooses it:**

- **Completeness criterion.** Coverage through T holds iff:
  1. the baseline snapshot S₀ (dated t₀) is preserved and hash-verified;
  2. every S&P DJI announcement with an effective date in (t₀, T] is retrieved, archived and hashed;
  3. S₀ plus the ordered changes reproduces **exactly** an independent full snapshot dated ≥ T (for example a later
     fja05680 snapshot), set-equal after mapping.

  Without condition 3 the coverage is unresolved, which means ACQUISITION_BLOCKED.
- **Conflicts.** Any mismatch, any unmapped ticker or any announcement without an effective date → ACQUISITION_BLOCKED.
  It never becomes "unchanged".
- **Exposure.** A new data category, `sp500_change_announcements` (t₀..T), needs explicit release scope.
- **Checks before any validation access:**
  - fixture tests (gaps, conflicts, same-day multi-changes, ticker changes);
  - a development replay that reconstructs a known 2019–2023 period from a 2019 snapshot plus that period's
    announcements, compared with the preserved development snapshots.
- **Process:** new protocol revision, new locks, new release and new GO. The original locks, blocked-attempt evidence
  and attempt ledger are preserved; the ledger is not reset.

**Why not now.** Condition 3 needs an independent dated end snapshot, which today is exactly what Route A waits for.
Without it, completeness rests on the unverified premise that the announcements are complete. That makes this a
larger amendment, with a new source, mapping and a development replay, for no evidential gain over Route A.

### Route C: paid point-in-time constituent data (owner decision; not recommended now)

| Aspect | Finding |
|---|---|
| Source | Norgate Data, US Stocks **Platinum** (historical index constituents, delisted securities, history to 1990). https://norgatedata.com/prices.php , https://norgatedata.com/stockmarketpackages.php , https://norgatedata.com/data-content-tables.php |
| Published cost | Platinum USD 346.50 / 6 months or USD 630.00 / 12 months; Diamond USD 433.13 / 787.50 (search-result snippet of the pricing page; not independently re-verified) |
| Access | subscription plus the Norgate Data Updater; Python integration available (claimed on the vendor pages) |
| Unverified | the exact coverage horizon or as-of semantics of the historical-constituent series; export and archiving terms (licence); symbology for delisted names |
| Amendment class | **source substitution** for callers 1–3: a new source, a mapping amendment and possibly different membership semantics. It needs explicit owner approval, a purchase decision, a new protocol revision, locks, a development replay against the preserved 2019–2023 snapshots, and a new release and GO |

Institutional alternatives (CRSP/Compustat via WRDS, S&P DJI licensed constituent files) were not evaluated. Their
access and cost are unknown.

## 3 Recommendation and remaining work

**`COVERAGE_NOT_ESTABLISHED_KEEP_PARKED`.**

Coverage through 2026-09-30 is not established by any permitted evidence. The inadvertent exposure indicates the tail
has unrecorded changes. Route A needs no amendment and is the least disruptive defensible path, but its timing is
unknown.

**Minimum remaining work to reactivate (Route A):**

1. **Metadata-only check:** the GitHub contents listing shows a blob sha different from `656b033b…`. This is one
   request, metadata only, and needs a separate small authorisation (it is not membership data).
2. **Owner decisions:** a new R′, a new release and GO, acceptance of the R′ broad-endpoint window, and the D6a
   execution-2 reading.
3. **Execution:** the locked runner in R5 off-hours, with S0 first. If coverage is still insufficient, the result is
   ACQUISITION_BLOCKED again, the last execution under D6a, and the run stops for owner review.

**Effort:** under one hour of operational work once a new version exists. No code changes.

**Concrete uncertainty:**
- when, or whether, the source records a change dated ≥ 2026-09-30;
- whether a second block exhausts the D6a budget.

## 4 Inadvertent exposure during this review

A web search intended to find S&P DJI methodology documentation (2026-10-07, about 00:40Z) returned press-release
**headlines and a summary naming 2026 S&P 500 membership changes**:

- the change effective 2026-08-18 (one replacement);
- the change set effective 2026-09-21 (three additions, three deletions);
- earlier 2026 changes.

No announcement document was opened, and no constituent list or change file was downloaded. The information is
validation-period **membership metadata only**: no prices, events or outcomes. It was not used to change any rule,
threshold or scope. It is recorded here because the task prohibited acquiring detailed membership-change records. A
later GO should state whether it changes anything; the protocol's prior-exposure section (§1e) is the place to note
it.

## 5 Confirmations

- No new validation price, event or outcome data was acquired, and no constituent list or change file was downloaded.
  The search-snippet exposure is disclosed in section 4.
- No retry and no execution occurred. The release, guards, locks, protocol, implementation and attempt ledger are
  unchanged.
- No purchase, subscription or contact was made.
- The live system was untouched.
