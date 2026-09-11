# Issuer identity & source coverage — BABA / BLSH / SKHY / SPCX + `paper_trading_enabled=0`

Source of truth for the resolver's disposition: `talonx_ops.watchlist_coverage.build_coverage_map()`
against the cached `~/.talonx/intelligence/company_tickers.json`. All four excluded names **do have
a CIK** in that file — so "not covered by this adapter" is **not** the same as "no public
filings", exactly as the task warns.

| symbol | CIK (cached) | resolver rationale | assessment |
|---|---|---|---|
| BABA | 1577552 | `foreign private issuer - files 20-F/6-K` | **CORRECT.** An FPI files 20-F/6-K and its officers/directors/10 % owners are **exempt from Section 16** → no Form 3/4/5. BABA is not a Form-4 issuer. `CORRECT_EXCLUSION`. |
| BLSH | 1872195 | `no domestic 8-K/10-Q/10-K filing history` | **LIKELY STALE.** "Bullish" is a crypto-exchange holding company with a real US common-stock listing. A US domestic registrant with listed common stock files 8-K/10-Q and its insiders file Form 4. The rationale holds only *before* the listing. → `LIKELY_MIS_EXCLUSION`. |
| SKHY | 2120882 | `Korean issuer - no SEC domestic filings` | **PLAUSIBLY CORRECT.** SK hynix trades on KRX; a US presence would be an unsponsored/Level-1 ADR with no SEC reporting and no Section 16. `CORRECT_EXCLUSION` pending a primary check of CIK 2120882. |
| SPCX | 1181412 | `SpaceX - private company, no SEC reporting` | **MISCONFIGURATION SUSPECTED.** SpaceX is private with no listed common stock; a "NASDAQ" exchange + tradable ticker in the watchlist is internally inconsistent. SpaceX's CIK exists from Form D only. Either a ticker-reuse error or a placeholder row. `CORRECT_EXCLUSION` for Form 4 (SpaceX does not file 4), but the **watchlist row itself should be flagged**. |

## Verification limit

This environment is forward-dated to 2026 with synthetic accessions; the live EDGAR
`submissions/CIK##########.json` feed for these four CIKs as of Sep 2026 is **not reachable**, so
the "actual current filing status" cell is **INCOMPLETE** for BLSH and SKHY. The BABA (FPI +
Section 16 exemption) and SPCX (private, Form D only) conclusions rest on stable SEC rules, not on
a live check.

## Does any of this change the Sep 8–10 result?

**No.** The preserved `insider_transactions` for the window (2026-07-15 … 2026-09-11, incl. the
pre-window lookback) contain **zero** Form 4 rows for BABA, BLSH, SKHY or SPCX. Even if BLSH
should be in V2 scope, there was **no V2 opportunity to miss** in the window.

## Tested candidate configuration (NOT production)

`docs/audits/task117_output_closure/candidate_config/` (a doc, not a live config change) proposes:
- Re-classify **BLSH** as a domestic Form-4 filer *iff* a primary EDGAR check confirms listed
  common stock and a Form 4 history — this is a **semantic scope change** that requires its own
  validation pass (a new name entering V2 execution scope changes the eligible universe). Do
  **not** silently enlarge production collection/execution scope.
- Leave **BABA / SKHY / SPCX** excluded; upgrade their `unsupported_reason` strings from the blunt
  `known_non_filer` label to the specific, defensible reason (FPI+§16 exemption / KRX-only /
  private+Form-D-only) so the metadata is not misleading. This is a **string / metadata**
  correction, no scope change.
- Add a `resolver_confidence` field: `RULE_BASED` (BABA, SPCX) vs `NEEDS_PRIMARY_CHECK`
  (BLSH, SKHY).

The `known_non_filer` label is an **application classification**, never asserted here as an
independently verified issuer fact.

## `paper_trading_enabled = 0` — which lane does it govern?

The 8 names inside the 39-name V2 scope with `paper_trading_enabled = 0`
(BAC, JNJ, JPM, KO, MA, MCD, PG, WMT — all added 2026-08-30) are **still V2-eligible**:

- `v2_collection_scope == "POLLED"` is the **only** gate for V2 execution scope. It is derived
  from SEC coverage, independent of `paper_trading_enabled`.
- `paper_trading_enabled` / `paper_trading_enabled_long_term` govern the **Original** intraday and
  long-term paper lanes (`intraday_serving` / `longterm_serving` in the resolver output).
- So `paper_trading_enabled = 0` means "the Original quant scanner does not paper-trade this name"
  — it does **not** disable V2, and it is **not intended to**. No new semantics are needed;
  user preferences are preserved.
- **Observability note (feeds `remaining_gaps.md`):** an operator reading `paper_trading_enabled=0`
  could reasonably assume the name is fully dormant. The dashboard watchlist view should show
  per-lane enablement (Original-intraday / Original-long-term / V2) rather than a single flag.
