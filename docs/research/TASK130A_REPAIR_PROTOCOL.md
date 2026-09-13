# Task 130A — repair protocol (review hold + freeze, before any corrected return)

Written and committed BEFORE `research/scripts/task130a_prospective_replay.py`
computes any corrected return. Original Task 130 artifacts are
preserved unchanged (not deleted, not overwritten in place).

## Review hold — dated correction to Task 130's own conclusions

- **Historical subset statistics remain reported** — Task 130's Track
  A (N=157) and Track B (N=153) figures stand as computed; not deleted.
- **`PASS_FOR_INTEGRATION_REVIEW` is UNDER REVIEW**, not withdrawn and
  not reaffirmed, pending this task's repair.
- **Track B was an intent-ASSOCIATED subset, not a proven prospective-
  policy replay.** Task 130 ran the PERMISSIVE policy (production's
  own current behavior, cold-start entries allowed) to completion, THEN
  filtered completed trades post-hoc by intent presence. The excluded
  cold-start entries still consumed real capacity/cooldown/occupancy
  state DURING the underlying replay — meaning other, intent-backed
  episodes that a genuinely stricter, gated simulation would have
  admitted differently were never re-evaluated under the corrected
  capacity timeline. This is a real methodological gap, not merely a
  reporting label issue.
- **The −2.25% figure was a "realized-equity" drawdown (cash + open
  positions marked at unchanging ENTRY COST), not a daily
  MARK-TO-MARKET equity drawdown.** It could not show an unrealized
  loss on any still-open position, by construction. This is corrected
  in Part 6 of this repair with genuine daily marks.

## What is NOT changed

Same hypothesis (`INSIDER_BUY_CLUSTER_V2@1`), same evaluation window
(2024-09-01 → 2026-03-31), same Discovery Universe v1 population (626
names), same signal thresholds (≥2 distinct Code-P owners/10 sessions,
liquidity gate unchanged), same holding period (+10 trading sessions),
same economic thresholds (mean net > +0.50%/round trip after 20bps;
95% issuer-block bootstrap lower bound > 0). **This is qualification
repair — fixing HOW the contract was tested, not what the contract
is.** The window is not treated as an untouched holdout merely because
it was re-examined here; it is the SAME data Task 130 already used,
now evaluated with a corrected implementation.

## Repair addendum (frozen before any corrected return)

### Exact runtime changes

A NEW, isolated session-by-session driver
(`research/scripts/task130a_prospective_replay.py`) replaces Task
130's reuse of `talonx_research.replay_engine.run_chronological_replay`
(which drives the unmodified, PERMISSIVE `V2Service.tick()`). The new
driver calls the SAME underlying production-adjacent primitives
directly and in the same order (`talonx_v2.cluster_engine.detect_episodes`,
`talonx_v2.liquidity.evaluate_liquidity`, `talonx_v2.quant_bridge.build_signal`,
`talonx_v2.brain_bridge.contextualize`, `talonx_v2.store.V2Store`,
`talonx_v2.pipeline.settle_due_exits` — unmodified imports, no
production file edited) but inserts the entry-eligibility GATE
in-line, before any entry is attempted, so excluded episodes never
touch capacity/cooldown/cash state at all.

### Simulated-clock and information-availability assumptions

- **Filing public-availability evidence**: the research Form 4 parquet
  carries FILING DATES only (no intraday dissemination timestamp) —
  unchanged from Task 130.
- **Assumed historical availability**: a filing is assumed causally
  knowable from its own `filing_date`'s session onward — the SAME
  convention every V2 task in this program has used; stated here
  explicitly as an assumption, not an observed fact.
- **Simulated ingestion/decision time**: session-granular — a record is
  "seen" on the tick whose `as_of` session is ≥ its filing date, exactly
  as `_records`/`records_provider` already works.
- **Intent persistence time**: the SIMULATED SESSION (not wall clock)
  on which `upsert_entry_intent` is called during this driver's own
  tick loop — tracked explicitly per intent as `created_session`.
- **Target open / close**: the existing `eligible_entry_session`'s own
  OPEN bar; exit at `add_sessions(entry, 10)`'s own CLOSE bar (or the
  bounded 5-session fall-forward) — unchanged.
- **Reference-price observation**: the same daily bar directories Task
  130 used — unchanged, no new data.
- **Ledger reconciliation**: this driver's own isolated SQLite ledger,
  written incrementally per session, never the live `v2_lane.db`.

**Date-only filings cannot establish observed intraday availability —
stated explicitly, not implied. All economics in this repair are
conditional on the session-level assumption above, not a claim of
minute-level observed dissemination.**

### Capacity/reservation and event-ordering rules

- $300,000 isolated starting capital, $10,000 FIXED entry allocation
  (no partial fill — insufficient available cash is a hard
  `SKIPPED_INSUFFICIENT_CAPITAL`, never a smaller spend), max 20 open
  positions, no borrowing, no cash reset.
- **A PENDING intent reserves $10,000 cash and 1 slot immediately upon
  creation** — a genuine behavior change from the current runtime
  (which reserves nothing for a PENDING intent) — this is what makes
  capacity genuinely respected across the intent→entry gap, not just
  at the moment of entry.
- **Deterministic ordering for competing intents/entries on the same
  session**: sorted by `(eligible_entry_session, issuer_cik, symbol)` —
  stable, reproducible, tested for run-to-run determinism.
- **Reservations release** on: `EXPIRED_STALE` (the existing
  staleness rule fires before entry), or consumption (converted into
  an actual position at entry) — never on any other event.
- **Entry precedes same-session exit crediting**: within one session's
  processing, ENTRIES (open-priced, using only cash available BEFORE
  that session's own exits are credited) are resolved before EXIT
  proceeds (close-priced) are added to cash — a same-day exit's
  proceeds can never fund that same morning's entries.
- **A missing entry price** fails that specific entry
  (`SKIPPED_NO_ENTRY_BAR`, reservation released) — it does not, by
  itself, let a same-session competitor take the slot out of the
  already-fixed deterministic order.

### Identity treatment

Issuer-CIK ambiguities are resolved from accession-level evidence
(`issuer_name` alongside `issuer_cik` in the same parquet rows), NEVER
by trade profitability — see Part 7 of the acceptance document. The
626-name population definition itself is NOT shrunk to dodge an
ambiguity; unresolved cases are reported as incomplete coverage.

### Daily valuation and cost treatment

Every open position is marked at EVERY trading session using the same
daily bar directories already used for entry/exit pricing (Task 130's
own convention, `adjustment=all` where available) — see Part 6. Costs
(20bps round-trip) are applied exactly once, verified by test.

### Original versus supplemental concentration tests

The ORIGINAL, already-frozen trade-COUNT-ranked issuer-removal test
(Task 130's own convention) is preserved unchanged. A SUPPLEMENTAL,
clearly-labelled P&L-CONTRIBUTION-ranked removal test is added
alongside it (Part 8) — never substituted for the original, never
selected after seeing which definition "passes."

### Acceptance requirements (unchanged from Task 130, restated)

Primary: mean net return per closed round trip > +0.50% after 20bps.
Statistical: 95% issuer-block bootstrap lower bound > 0. Time-
dependence: date-block bootstrap must AGREE (both exclude zero) under
the same conservative disagreement rule. Top-issuer-removal
sensitivity (both original count-ranked and supplemental P&L-ranked)
must not reverse sign. No single calendar half-year may be the sole
source of a positive result — 2026H1's negative reading stays visible,
period boundaries are not moved or excluded.

**An economic pass alone does not close missing implementation,
identity, or valuation evidence** — the final verdict (Part 10 of the
acceptance document) is gated on ALL of: economic result, prospective-
policy implementation acceptance, timestamp-evidence limitations,
portfolio/risk acceptance, and identity/coverage acceptance —
separately reported, not collapsed into one number.
