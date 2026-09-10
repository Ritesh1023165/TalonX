# TASK 117 — Output Defects & Three-Day Opportunity Reconciliation

**Branch:** `research/talonx-strategy-validation` · **Base:** `28af0774d75eee7d57bbb6227163d9fd32990a46`
**Scope of this task:** bounded source/test/dashboard/doc fixes + a bounded Sep 8–10 opportunity
comparison. **Not** in scope: production activation, restart, Telegram sends, production DB
migration/backlog mutation, watchlist/universe changes, threshold changes, `main` merge.

Application is **stopped** (verified). Production `v2_lane.db` md5 `29e57dbcd1a567fbc4bb0e73efdba95f`
unchanged. V2 fingerprint `11107198c5b81237` unchanged (none of the 5 hashed files touched).
Redis retained. No external messages.

---

## 1. What was fixed (code, with tests)

| id | fix | files | tests |
|---|---|---|---|
| **TZ** | **SEC `acceptanceDateTime` is US Eastern, not UTC.** `parse_acceptance_datetime` now treats a bare `Z` / `+00:00` / naive value as an Eastern wall-clock (DST-correct), converts to true UTC, and flags `acceptance_tz_assumed_eastern`. Explicit non-zero offsets (efts.sec.gov / RSS) are trusted verbatim. One switch: `EDGAR_ACCEPTANCE_ASSUMES_EASTERN`. | `talonx_ingest/intelligence/edgar_normalize.py`, `domain.py` (+flag) | `tests/test_task117_acceptance_timezone.py` (26), updated `test_intelligence_edgar_normalize.py`, `test_intelligence_pipeline.py` |
| **TZ-V2** | V2's `from_insider_store` fallback now keys the missing `filing_date` on the acceptance instant's **Eastern calendar date** (NYSE-session semantics), never the UTC date. | `talonx_v2/form4_source.py` (not in the fingerprint hash) | covered by the tz module + existing V2 suite |
| **D1** | `build_funnel` is scope-aware: default `"auto"` resolves the enforced V2 execution allowlist (same source as the live companion) and filters the near-miss / cluster funnel to it. `None` keeps the old unrestricted behaviour for replay. Output carries `execution_scope_enforced` / `_count`. | `talonx_ops/prospective/funnel.py` | funnel + prospective suite (527 pass) |
| **D2** | `count_telegram_get_updates_owners()` collapses the Windows venv shim + worker pair into **one logical** poller (a match whose ancestor is also a match is a shim child, not counted). | `talonx_ops/supervisor.py` | supervisor + telegram_owner suite |
| **D3** | Dashboard EOD tile only applies a reconciliation row when its `session_date` == the **current session** (`self.now`), never merely today's wall clock. A prior-session row is surfaced as `prior_reconciliation_note`, not shown as current. `_v2_position_lifecycle` days-held also uses `self.now`. | `talonx_ops/dashboard_read.py` | dashboard suite |
| **D7** | The earnings **heads-up** Telegram domain now also writes `last_telegram_push` (`horizon="earnings_heads_up"`) so a "last official send" surface is complete. (Correction: long-term alert sends were **already** recorded — see `corrected_three_day_reconciliation.md` §D7.) | `talonx_dispatch/consumer.py` | dispatch suite |
| tests | `test_task117_migration.py` / `test_task117_deployment_rehearsal.py` accept BOTH the pre- and post-activation ledger hash (the authorized activation migrated the live ledger; the fixtures still pinned the pre-migration hash). | those 2 test files | 6 previously-red tests now green |

**Not fixed here (documented, with the proposed fix + acceptance check):**
- **D4** — `prospective start` false NO-GO while the stack is up (double-stack risk). Requires
  reworking `cmd_start`'s post-start verdict to reflect the spawn result, not a preflight snapshot
  taken before `:8787` binds. Higher blast-radius; see `remaining_gaps.md`.
- **D5** — Intelligence `intelligence_delivery` outbox never drains (9,843 rows, 0 sent ever).
  Design + backlog policy in `intelligence_delivery_closure.md`; **implementation deferred** — it
  needs a product decision (intentional dry-run vs wire the drainer) and a backlog triage that
  must not flood Telegram on activation.
- **D6** — `metrics:<date>:quant:*` counters are comingled Original+Experimental with no lane
  suffix, and THROTTLE/COOLDOWN/revalidation dispositions are off-counter. Fix needs Redis key
  changes + an EOD counter snapshot; proposed in `remaining_gaps.md`.

## 2. Confirmed root causes of low user-visible output

| lane | why the user saw little/nothing | classification |
|---|---|---|
| **Intelligence event cards** | **The `intelligence_delivery` outbox has never drained** — 9,843 rows, 100 % `PENDING`, 0 ever `SENT`. This is a **missing integration**, not strictness. The only fundamental alerts the user received (ORCL LT6/LT7/LT8, earnings heads-up) went out via the *separate* Original long-term route (`talonx:alerts:longterm` → `talonx_dispatch`). | application behaviour (D5) |
| **V2 trading** | **Zero qualifying signals is the frozen contract applied correctly.** With the required pre-window lookback to 2026-07-15, the only in-scope ≥2-distinct-owner code-P cluster is **ABCL**, activated mid-August → eligible entry ~2026-08-17 → **stale** by the Sep 8 campaign start (`max_entry_staleness_sessions=3`). No fresh cluster activated Sep 8–10. Not a bug, not a coverage gap (the InsiderStore had continuous code-P history for all 39 names). | strictness + a genuinely quiet window |
| **Original intraday** | Every candidate was gate-suppressed; ~99.8 % at the `LOW_VOLATILITY` pre-filter (14,973/15,002 on Sep 10). This is the **frozen threshold's selectivity** on a large-cap watchlist in a low-range regime. | strictness (frozen threshold) |
| **Original long-term** | Delivered normally (ORCL). | working |
| **Timestamp mislabel** | Not a "no output" cause, but it **corrupts** the output that does ship: after-close filings (e.g. the ORCL earnings 8-K, real acceptance 16:16 ET) were persisted with `session_bucket = RTH` and the LT7/LT8 cards said "regular hours" when the release was after the close. Fixed. | correctness defect (TZ) |

## 3. Informational events missed vs qualifying trading signals missed

- **Qualifying V2 trading signals missed: NONE.** Every in-scope code-P issuer in the window
  (ABCL / ADC / INTC) is a `CORRECT_EXCLUSION` — ABCL stale, ADC & INTC single-insider near-misses.
  Out-of-scope code-P issuers (MUNEX, NMZ, PML, PMM — municipal closed-end funds) are correct
  scope exclusions.
- **Informational events not delivered: MANY, via D5.** The 9,843-row backlog (incl. 23 cards on
  Sep 10 alone: DELL/TSLA/WMT/AVGO/AFL/PG/V/ORCL/ADP/JPM insider + earnings + quarterly) were
  rendered and queued for Telegram and never sent. "Not delivered" ≠ "lost" — the rows are
  durable — but the user did not see them. Whether this outbox is *meant* to deliver is the open
  product question (D5).
- **Original intraday setups:** all recoverable Sep-10 rejections are `LOW_VOLATILITY` /
  `LOW_CONFLUENCE` / `OPENING_BLACKOUT` / `TREND_GATE`. No row is `SOURCE_COVERAGE_GAP` and none is
  a `CONFIRMED_QUALIFYING_SIGNAL_MISSED` — see `ticker_day_opportunity_matrix.csv` /
  `confirmed_misses.csv` (Original Question C is **INSUFFICIENT_EVIDENCE** for a full
  price-outcome pass — the preserved bar buffer covers only a subset and post-hoc price rise is
  not treated as a missed trade).

## 4. Profitability evidence and its limits

**No V2 trade-return evidence exists for Sep 8–10** — 0 V2 entries/exits across all three
sessions, `v2_lane.db` logically unchanged (cash $300,000, one terminal ABCL `SKIPPED_ENTRY_STALE`).
Operational PASS is not a profitability PASS. Experimental paper opened 5 positions (VRT, BLSH,
AMD, STX, SPCX) — internal-only, no exits, no realized P&L, mark-to-market not computed (internal
lane under the current guardrail). See `ticker_day_opportunity_matrix.csv` and
`corrected_three_day_reconciliation.md`.

## 5. Files in this bundle

| file | contents |
|---|---|
| `README.md` | this |
| `acceptance_matrix.md` | every acceptance criterion in the task → status + evidence |
| `corrected_three_day_reconciliation.md` | corrections to the published Sep-8/9/10 audit |
| `timestamp_trace.csv` + `timestamp_findings.md` | PG/V/ORCL/ADP/JPM end-to-end acceptance-time trace + root cause + impact + migration proposal |
| `issuer_identity_coverage.csv` + `issuer_identity_findings.md` | BABA/BLSH/SKHY/SPCX + `paper_trading_enabled=0` analysis |
| `intelligence_delivery_closure.md` | the enqueue path, the missing drainer, backlog policy, non-executed activation steps |
| `oracle_provenance.md` | LT6/LT7/LT8 trace, the $175→$165 revision, proposed event-version identity |
| `ticker_day_opportunity_matrix.csv` | per active ticker × day: coverage, informational event, V2 contract, Original setup |
| `confirmed_misses.csv` | rows classified `CONFIRMED_QUALIFYING_SIGNAL_MISSED` / `INFORMATIONAL_DELIVERY_MISSED` (with evidence) |
| `dashboard_acceptance.md` | isolated-data render checks for D1/D2/D3 (screenshots N/A — no browser tool; JSON/console evidence instead) |
| `deployment_candidate.md` + `rollback.md` | what to deploy from this change set, and how to revert |
| `remaining_gaps.md` | D4, D5-impl, D6, and every audit cell left incomplete |
| `evidence_manifest.csv` | file × source × sha256 |

All bulk data / DB snapshots stay under the git-ignored `results/` tree; this bundle is
self-contained without them.
