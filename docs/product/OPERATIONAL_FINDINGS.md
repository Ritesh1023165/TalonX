# TalonX Operational Findings Tracker

**Created**: 2026-09-15, during the Session 2 documentation pass
(`DECISION_LOG.md` Session 2). This is the first entry in this file —
no prior operational-issue tracker existed in this repository at the
product-experience layer. It is a **separate domain** from the other
trackers in this repository:

- `REQUIREMENTS_TRACKER.md` — product-experience **requirements**
  (what the product should do, agreed with the owner).
- `docs/research/TALONX_OWNER_DECISIONS.md` — Original's
  strategy-tuning parameters specifically.
- `docs/research/TALONX_RESEARCH_LEDGER.md` — the append-only
  chronological history of every research/validation task.
- **This file** — operational/runtime **findings**: things discovered
  during live inspection, EOD closures, or reviews that describe a gap
  or risk in the running system's own operational behavior (not a
  product-direction decision, and not a research-alpha finding).

Same discipline as the other trackers: append-only, stable IDs
(`OPS-<sequence>`), never silently edited — a later update adds a
dated note under the original entry.

---

## OPS-001 — EOD Closure 2026-09-15: review/correction note

**Status**: `CLOSED` (documentation review only — no code/runtime
issue; this is a scope-qualification note, not a defect).

**Raw report**: `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` (preserved as originally written — this entry
does not edit it, it appends a linked review note to the report itself
and indexes that note here).

**Review note** (recorded 2026-09-15, Session 2 documentation pass):
the original EOD closure report is accurate as a timestamped,
evidenced record of what was inspected, reconciled, and shut down on
2026-09-15 — it is **not** re-litigated here. What this note adds is a
scope qualification that the original report did not itself state
explicitly:

> **EOD accounting and controlled shutdown were supported by the
> report. This does not establish readiness for current-session V2
> paper execution.** A clean EOD reconciliation (zero mismatches among
> checked components, a graceful shutdown with zero residual
> processes) demonstrates that the accounting and process lifecycle
> are sound as of that closure. It does not, by itself, demonstrate
> that V2 is currently able to correctly price and execute a fresh
> opportunity — see `OPS-002` below, found during this same
> documentation pass, for the specific gap this qualification refers
> to.

This qualification has also been appended directly to
`EOD_CLOSURE_REPORT.md` (a new §8, dated and linked back to this
entry) so a reader of that report alone sees the same caveat.

**Evidence references**: `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §8 (Review note, Session 2 pass).

---

## OPS-002 — V2 current-price availability and freshness reporting incomplete

**Status**: `OPEN` — implementation requires a separately authorized
corrective task. Not implemented, not fixed, not worked around by this
documentation pass.

**Found**: 2026-09-15, first during the EOD closure task (same-day),
re-reviewed and formally tracked during the Session 2 documentation
pass.

**Reported evidence** (from `EOD_CLOSURE_REPORT.md` §4, re-verified by
targeted code re-reading this pass, not re-run):

- Runtime pricing mode was `csv` (`talonx_v2/service.py`,
  `V2Service.__init__`).
- In `pricing_mode == "csv"`, `self._resolver` is **never constructed**
  (`if pricing_mode != "csv": self._resolver = _pricing.make_resolver
  (...)`) — the price-validation/freshness-tracking resolver object
  simply does not exist in this mode.
- The `pricing_adapter` status field's `"csv:frozen_bar_dirs"` value is
  a **hardcoded fallback string**, not a real registered adapter's own
  name — it is emitted whenever `self._resolver` is `None`.
- `pricing_unavailable_recent` reads from `self._resolver.last`, which
  doesn't exist in this mode — the field is **structurally always
  empty**, not "checked and found healthy."
- The actual default bar directory in use (no `--bar-dir` override in
  the live launch argv, confirmed via `session.pids.json`) —
  `results/task95g_broad_cross_sectional/_daily/` — has its latest
  usable row (`AAPL.csv`) dated **2026-08-14**, roughly 22 trading days
  stale relative to the 2026-09-15 EOD closure date.
- `CsvBarAdapter.session(symbol, date)` returns `None` (not a stale or
  incorrect substitute price) for a date it doesn't have — confirmed by
  direct code reading, not assumed.

**Distinction clarified in this pass** (per this task's own
instruction not to overstate what was established): **this does not
mean V2 performs no price lookup.** `CsvBarAdapter.session()` is the
actual fill/valuation lookup the entry/exit code paths use — it is a
real, functioning lookup against the configured bar directory, and it
fails safely (returns `None`, never a stale/wrong number) when a date
is missing. What is missing is the **separate diagnostic resolver/
freshness-tracker** object (`self._resolver`) that the `"csv"` mode
never constructs — so the *operational visibility* into staleness
(the `pricing_unavailable_recent` telemetry field) is absent, even
though the underlying lookup mechanism itself exists and behaves
safely. **Configured vs. fallback path**: the `"csv:frozen_bar_dirs"`
label is a fallback string used only for status display, not a sign
that the wrong data source is being read — the actual data source
(`results/task95g_broad_cross_sectional/_daily/`) is the one genuinely
in use, confirmed via the live launch argv, and it genuinely is stale.

**Explicit implications** (as instructed, none silently assumed away):

- Missing-price handling may correctly prevent an invented fill, but
  it may equally prevent a valid, currently-qualifying opportunity
  from entering or being valued — a safe failure mode, but not a free
  one.
- Execution scope count (`execution_scope_count: 626`,
  `EOD_CLOSURE_REPORT.md` §4) is not the same claim as price coverage
  for those 626 symbols on the current session date.
- GATED admission (`durable_store_gate_enabled: true`) is an admission
  gate, not a pricing-readiness gate — the two are independent.
- Zero trades in the current campaign does not prove zero qualifying
  opportunities existed — it is also consistent with a stale-price
  rejection having silently occurred (fails safe, but not
  distinguishable from "no qualifying opportunity" in the telemetry
  currently available).
- Zero trades does not prove price lookup was never attempted — the
  lookup mechanism runs regardless; only its *diagnostic visibility* is
  what's missing.
- Empty freshness telemetry (`pricing_unavailable_recent: []`) must
  not be read as "prices are fresh and healthy" — it is structurally
  empty in this mode regardless of actual price condition.

**Future corrective work — NOT IMPLEMENTED here, requires a separately
authorized task**:

1. Trace the authoritative V2 entry/exit/valuation price paths
   end-to-end (beyond `CsvBarAdapter.session()` alone).
2. Verify configured paths, symbol coverage, and usable date ranges
   against the live watchlist.
3. Restore a supported current-price path using authorized existing
   sources (no new paid data, no unapproved provider).
4. Preserve and disclose reference-price/provisional-bar semantics —
   do not silently mask a stale mark as current.
5. Test current-session, missing, provisional, and stale-price
   behavior explicitly (isolated tests, not live trading).
6. Expose price readiness independently from process/ingestion health
   in the dashboard/status surfaces (distinct from S2-12's dashboard-
   presentation requirement, though related — S2-12 is about how a
   missing valuation is *shown*; this item is about the upstream
   *data* the display would draw from).
7. Reconcile "strategy rejected the opportunity" vs. "price was
   unavailable" as distinguishable rejection reasons, not conflated.

**Acceptance criteria** (for the future corrective task, not met by
this documentation pass):

- Relevant price coverage and dates are visible (not structurally
  empty).
- A current target-session request behaves under an explicit, declared
  policy (not an undocumented `None`-on-miss with no visibility).
- Missing/provisional data yields an explicit disposition, not silence.
- Stale or absent telemetry cannot produce a misleading "healthy"
  verdict.
- No silent provider/strategy change, and no fabricated fill, at any
  point in the fix.

**Explicitly out of scope for this entry**: no provider was changed,
no data was downloaded or refreshed, no path was repaired, and no code
was modified to produce this finding — it is a disclosed, tracked gap
only, per this documentation task's own restrictions.

**Evidence references**: `talonx_v2/service.py` (`V2Service.__init__`,
the `pricing_mode != "csv"` conditional); `talonx_v2/pricing.py`
(`CsvBarAdapter.session`); `results/task95g_broad_cross_sectional/
_daily/AAPL.csv` (last row date); `docs/research/evidence/
eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md` §4 (original finding).

**Related but distinct**: `REQUIREMENTS_TRACKER.md` `S2-12`
(dashboard presentation of missing/stale valuations — a display-layer
requirement) and `S2-06`/`S2-05` (live-vs-replay parity) both touch
adjacent ground but do not resolve this upstream data-freshness gap.

**Session 3 note (2026-09-16)**: the Session 3 documentation pass
(`DECISION_LOG.md` Session 3 — application structure, master stock
coverage, capital defaults, research-lab workflow) recorded a large
set of product decisions but made **no code, runtime, configuration,
or data changes**. `OPS-002` **remains `OPEN`**, exactly as described
above — none of Session 3's decisions fix, mask, or otherwise touch
V2's pricing-resolver gap. `S3-06`/`S3-07`/`S3-10` (master-list
eligibility states) are conceptually adjacent — a future "data ready"
state in `S3-10`'s five-state model would need to account for exactly
this kind of upstream freshness gap — but none of them resolve it
today.

---

## OPS-003 — Entry-session deadline-consistency finding (recorded for re-verification)

**Status**: `OPEN` — recorded for future re-verification against
current code; **not corrected by this documentation pass**.

**Found**: originally, Task 112R (this project's history, before this
documentation track existed); re-surfaced and formally tracked during
the Session 5 documentation pass (2026-09-16).

**Finding**: Task 112R's own "G1" review found that the research
`build_episodes` methodology (used to compute the historical
`+2.0219%`/`+2.196%` evidence figures cited in `S2-15`) determines
entry eligibility after the **last** insider filing in a cluster
window, while the actual Task 109 contract and V2's live runtime
(`talonx_v2/service.py`/`pipeline.py`) fire entry eligibility at the
**second distinct insider** filing — a difference that produced 326
entry-session differences in an offline, like-for-like comparison.
Task 112R's own conclusion at the time was that the **runtime is
contract-correct** (matches the frozen Task 109 specification) and the
research methodology is the one that differs — no code change was
made, because the runtime was judged correct against its own frozen
spec.

**Why this is tracked again now**: Session 5's discussion of exact
three-session-recovery deadline semantics (`S5-13`, `S5-19`,
`S5-20`) raised this as a specific, named example of a
previously-inspected deadline-related inconsistency that should be
**re-verified against current code** before it is relied on further —
the original Task 112R review predates this documentation track, used
an offline comparison, and has not been re-run against the code as it
exists today (multiple V2/Task 131+ changes have landed since).

**Explicitly not done in this pass**: no code was re-read line-by-line
to re-confirm Task 112R's original conclusion still holds; no fix,
adjustment, or reclassification was made. This is a disclosed,
tracked re-verification item, not a live defect claim.

**Future corrective work — NOT IMPLEMENTED here**: re-run or replicate
Task 112R's own offline entry-session comparison against the current
codebase; confirm whether the 326-difference finding and its
"runtime is contract-correct" conclusion still hold; if the runtime
has since changed, re-assess whether that conclusion needs updating.

**Evidence references**: this project's Task 112R history (`docs/
research/TALONX_RESEARCH_LEDGER.md`); `talonx_v2/service.py`,
`talonx_v2/pipeline.py` (current code, not re-diffed against Task
112R's version this session).

**Related**: `REQUIREMENTS_TRACKER.md` `S5-13`, `S5-19`, `S5-20`.

---

## OPS-004 — Corporate-action and fractional-share handling gap

**Status**: `OPEN` — no such code exists today; Session 5 §D is
entirely future policy, not implemented behavior.

**Found**: Session 5 documentation pass (2026-09-16), via targeted
code search.

**Finding**: a search across the codebase for stock-split, reverse-
split, merger, cash-in-lieu, and fractional-share handling found **no
production code implementing any of this** — the only matches were in
an unrelated research script (`research/scripts/task101a_event_first.py`,
a different "event-first" methodology study, not corporate-action
handling). V2's frozen strategy and Original's own accounting operate
on the assumption that a symbol's identity and share count remain
stable between entry and exit; nothing currently detects, blocks on,
or reconciles a corporate action occurring during that window.

**Explicit implications**: any of Session 5 §D's agreed policies
(verified-rename mapping, before/after-entry split handling,
merger/replacement-security treatment, proportional cost-basis
allocation, `CORP_ACTION_CASH` accounting) describe a **target**, not
a gap being closed — there is no partial implementation to point to.
A corporate action occurring today during a live V2 holding period
would not be specially handled by any code found this session (though
this was not exercised live — V2's campaign has had 0 trades to date
per the 2026-09-15 EOD closure, so this gap has not yet been tested
against a real event).

**Future corrective work — NOT IMPLEMENTED here**: build the
verification/blocking gate for unresolved corporate actions; build
split/merger-adjusted entry-basis and chronological-reconstruction
logic; build proportional cost-basis allocation and `CORP_ACTION_CASH`
accounting; decide and implement the exact rounding mode and residual-
reconciliation policy (`S5-27`).

**Evidence references**: targeted repository-wide search, this
session (no matches in `talonx_v2/`, `talonx_paper/`, `talonx_ops/`).

**Related**: `REQUIREMENTS_TRACKER.md` `S5-15`, `S5-16`, `S5-21`
through `S5-27`.

---

## OPS-005 — Price-provider qualification gap

**Status**: `OPEN` — extends `OPS-002`'s pricing-freshness finding
with the broader, unresolved provider-selection question.

**Found**: Session 5 documentation pass (2026-09-16).

**Finding**: Session 5 §B agreed that each strategy/data-contract
version should define **one primary provider, feed, opening-reference
definition, and adjustment basis**, explicitly distinguishing an
official auction price from a provider's own daily-bar open. Today,
V2's `"csv"` pricing mode is a real, working, version-scoped price
source (`talonx_v2/config.py`/`service.py`) — but it is not formalized
as an explicit, documented data-contract object, its relationship to
an "official auction price" was not verified this session, and (per
`OPS-002`) its own freshness-tracking resolver is not constructed in
this mode at all. **Actual provider selection and free-tier
feasibility for a more complete/current pricing source remain
genuinely undecided** (`S5-10`) — this is not a defect in the current
`"csv"` mode's own behavior (it fails safely, `OPS-002`), but a gap in
having any **qualified, validated alternative or fallback** ready.

**Future corrective work — NOT IMPLEMENTED here**: research and select
an authorized, free-tier-feasible primary provider per strategy;
define its opening-reference/adjustment basis explicitly; build a
**qualified** fallback path (not an unvalidated substitution) with
equivalent live/replay rules (`S5-11`); resolve `OPS-002`'s freshness-
telemetry gap for whichever provider is ultimately used.

**Evidence references**: `talonx_v2/config.py`, `talonx_v2/service.py`
(this session); `OPERATIONAL_FINDINGS.md` `OPS-002` (the related,
narrower freshness-telemetry finding).

**Related**: `REQUIREMENTS_TRACKER.md` `S5-08` through `S5-12`.

---

## OPS-006 — Registry/coverage-scope fragmentation

**Status**: `OPEN` — three separate, non-unified symbol scopes
confirmed with dated evidence; extends `S3-08`'s finding.

**Found**: Session 3 (`S3-08`, initial finding); confirmed with dated
evidence during the Session 5 documentation pass (2026-09-16).

**Finding**: no single master security registry exists. Three
separate, independently-maintained scopes were confirmed this session,
each with its own dated evidence:

- **Original**: 48 configured tickers, 43 active/selected, 39
  SEC-covered (`docs/OPERATIONS.md:69`; `docs/audits/2026-09-10/
  README.md:86`; corroborated by `selected_symbols: 43` in multiple
  Task 138-140 checkpoint files, dated 2026-09-14/15).
- **Intelligence**: 569-symbol effective collection scope
  (`docs/research/evidence/task140/gated_admission_activation.md:52`,
  `effective_symbols: 569`; corroborated by `docs/research/evidence/
  task137/TASK137_OVERNIGHT_CONTINUITY_REPORT.md:160`, dated
  2026-09-14).
- **V2**: 626-symbol execution scope (`execution_scope_count: 626`,
  `docs/research/evidence/eod_closure_2026-09-15/
  EOD_CLOSURE_REPORT.md` §4, dated 2026-09-15).

None of these is a superset or subset of the others by construction —
they were built independently for each system's own purpose. **No
evidence was found this session for a "27-unresolved / 599-resolved"
count pair** referenced in the Session 5 discussion prompt; that
figure is explicitly not adopted anywhere in this documentation.

**Future corrective work — NOT IMPLEMENTED here**: build the master
security registry (`S5-01`-`S5-06`); reconcile/cross-map the three
existing scopes into it; decide and disclose how per-strategy/per-
horizon eligibility derives from the unified registry going forward.

**Evidence references**: see the dated citations above (also
duplicated in `DECISION_LOG.md` Session 5 §A and
`REQUIREMENTS_TRACKER.md` `S5-07`).

**Related**: `REQUIREMENTS_TRACKER.md` `S3-08`, `S5-01` through
`S5-07`.

---

*See `REQUIREMENTS_TRACKER.md` for product-requirement tracking,
`DECISION_LOG.md` for the session-by-session product-owner record, and
`docs/research/TALONX_RESEARCH_LEDGER.md` for the research/validation
task history. This file tracks operational/runtime findings only.*
