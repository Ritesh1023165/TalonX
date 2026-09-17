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

## OPS-003 — Entry-session deadline-consistency finding

**Status**: `OPEN` — Finding A recorded for future re-verification;
Finding B directly confirmed by code inspection and executed tests
this pass. **Neither finding is corrected by any documentation pass —
correction requires a separately authorized implementation task.**

### Finding A — Task 112R cross-methodology entry-session difference (original, unchanged)

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

**Explicitly not done in any pass so far**: no code was re-read
line-by-line to re-confirm Task 112R's original conclusion still
holds; no fix, adjustment, or reclassification was made. This remains
a disclosed, tracked re-verification item, not a live defect claim.

**Future corrective work — NOT IMPLEMENTED here**: re-run or replicate
Task 112R's own offline entry-session comparison against the current
codebase; confirm whether the 326-difference finding and its
"runtime is contract-correct" conclusion still hold; if the runtime
has since changed, re-assess whether that conclusion needs updating.

**Evidence references**: this project's Task 112R history (`docs/
research/TALONX_RESEARCH_LEDGER.md`); `talonx_v2/service.py`,
`talonx_v2/pipeline.py` (current code, not re-diffed against Task
112R's version).

### Finding B — intra-runtime dual-deadline discrepancy and fill-before-check ordering (new, 2026-09-16)

**Found**: 2026-09-16, during a documentation-correction pass that
re-examined `REQUIREMENTS_TRACKER.md` `S5-13`/`S5-14`'s original,
unsupported `Implemented` classification. **This finding is directly
confirmed by code inspection this pass, and corroborated by running
two pre-existing, isolated tests** (`tests/
test_task131_nonblocking_retry.py`, `tests/
test_task113_stale_entry_guard.py` — 8 passed, `tmp_path`-isolated, no
live system touched) — a stronger evidence standard than Finding A's
"recorded for re-verification."

**Agreed product behavior** (Session 5, `S5-13`/`S5-14`): for
`max_entry_staleness_sessions = 3`, the target entry session counts as
Session 1; recovery ends at the exchange-calendar official close of
Session 3 (inclusive of early-close days, exclusive of non-trading
days); expiry is checked **before** any fill is attempted; only
timely, durably admitted intents may reconcile.

**Observed implementation behavior**:
1. **Two different deadline computations exist for the same
   parameter, one session apart.** The general entry-attempt
   eligibility gate (`talonx_v2/service.py:377-381`) computes
   `stale_cut = ripe_through - max_entry_staleness_sessions` and keeps
   an episode attemptable through `eligible_entry_session + 3`
   sessions — a **4-session** window under the product's own
   1-indexed counting (Session 1, 2, 3, **4**). The missing-price
   retry-then-release path's own deadline
   (`talonx_v2/service.py:546-547`) computes `retry_deadline =
   add_sessions(eligible_entry_session, max_entry_staleness_sessions -
   1)` = `eligible_entry_session + 2` sessions — a **3-session**
   window (Session 1, 2, 3), matching the agreed policy exactly. The
   code's own inline comment (`service.py:527-543`) confirms this
   one-session gap between the two is a deliberate internal workaround
   (to keep the release path reachable before the coarser guard would
   otherwise sweep the episode up first) — the codebase's own authors
   were aware these two boundaries diverge; the discrepancy was never
   reconciled against the product's own stated policy, because that
   policy was not written down until Session 5.
2. **A fill is attempted before any deadline check, not after.**
   `_phase_open` (`talonx_v2/service.py:504-513`) calls
   `pipeline.process_episode(...)` (the actual fill attempt)
   **unconditionally**, for every episode not already excluded by the
   general 4-session staleness gate. The `retry_deadline` comparison
   (`service.py:546-548`) is evaluated **only reactively**, after that
   same attempt has already returned a `NO_ENTRY_BAR` miss — never
   before a fill attempt. A **successful** fill has no deadline check
   gating it at all beyond the (wider, 4-session) staleness gate.
3. **Everything is date-granular; no close-time boundary exists
   anywhere.** `talonx_v2/calendar.py` builds its entire session list
   from `exchange_calendars`' XNYS session **dates** only
   (`[ts.date() for ts in cal.sessions_in_range(...)]`, `calendar.py:
   22-29`) — non-trading days are correctly excluded and early-close
   days are correctly included as ordinary valid sessions (the
   calendar itself handles this, per the module's own docstring), but
   no function anywhere in this module or its callers carries or
   checks an actual close **timestamp**. There is no code path capable
   of distinguishing "before" vs. "after" the close of a given
   session — the mechanism only knows which calendar date something
   falls on.
4. **Restart/downtime does not extend the deadline** — both deadline
   computations above are pure functions of the episode's fixed
   `eligible_entry_session` and the calendar's static session list;
   neither consults process-uptime or last-run state. **This part of
   the agreed policy is correctly implemented**, and is not affected
   by findings 1-3 above.
5. **Reservation release is exactly-once** — a single, shared SQL
   guard (`WHERE intent_id=? AND status='PENDING'`, `talonx_v2/
   store.py:526-536`) backs every terminal release path
   (`EXPIRED_STALE`, `FAILED_NO_MARKET_DATA`, and the normal `FILLED`
   path alike). **This part of the agreed policy is correctly
   implemented**, confirmed by the executed test run above, and is not
   affected by findings 1-3 either.

**Concrete discrepancy**: a genuine entry fill remains structurally
possible as late as `eligible_entry_session + 3` sessions (the wider
gate) if a price happens to become available that late — one session
beyond the agreed "ends at Session 3" boundary — because nothing
gates a *successful* fill attempt against the narrower, policy-
matching `retry_deadline`. The narrower boundary is only ever enforced
reactively, and only for the specific missing-price-release path.

**Remaining evidence gap**: whether this one-session/ordering
discrepancy has ever actually produced a live fill outside the agreed
window is **not established either way** — V2's campaign has had 0
trades to date (2026-09-15 EOD closure), so this has not yet been
exercised against a real, late-arriving price. This is a structural
code-behavior finding, not a claim that a specific bad fill has
occurred.

**Future acceptance scenarios** (to define and test before any
correction is implemented — none of these is resolved by this
documentation pass):
- **Normal week** (no holiday, no early close): confirm the corrected
  boundary produces identical Session-1/2/3 dates under both the
  general gate and the release-path deadline.
- **Holiday within the 3-session window**: confirm `add_sessions()`
  correctly skips the non-trading day for *both* deadline computations
  once unified, and that Session 3 still resolves to a genuine trading
  day.
- **Early-close session as Session 3**: confirm whether "official
  close" for an early-close day is meant literally (the actual early
  close time) or treated as an ordinary session boundary (date-only,
  as today) — this is exactly `S5-19`'s open equality-at-deadline
  question, not resolved here.
- **Price arriving after the deadline** (a late/backfilled bar dated
  within the window but received after Session 3's close has passed):
  confirm the corrected code refuses the fill and releases the
  reservation as `EXPIRED_NO_MARKET_DATA`/`FAILED_NO_MARKET_DATA`,
  rather than accepting a technically-in-range price that arrived too
  late.
- **Restart after the deadline** (service down through the whole
  3-session window, resumed afterward): confirm the deadline is still
  correctly computed as expired on resume, exactly as today's
  restart-independence already demonstrates for the existing (albeit
  off-by-one) boundaries.

**Separate implementation authorization required**: no code change is
authorized by this or any prior documentation-only task. A future
implementation task would need to be separately authorized to: (a)
decide which of the two existing boundaries (2-session-offset or
3-session-offset) is the one to keep, or introduce a single, unified
boundary; (b) decide whether to gate successful fills against that
boundary proactively (check-before-attempt) rather than only the
missing-price path reactively; (c) resolve `S5-19`'s exact equality-
at-deadline and receive-vs-commit semantics as part of that same
design, since they directly determine the corrected boundary's exact
edge behavior; (d) test against the five acceptance scenarios above.

**Evidence references**: `talonx_v2/service.py:377-381,504-513,
527-548,555-571`; `talonx_v2/calendar.py:8-9,22-29`; `talonx_v2/
store.py:526-536`; `tests/test_task131_nonblocking_retry.py` and
`tests/test_task113_stale_entry_guard.py` (run this pass, 8 passed).

**Related**: `REQUIREMENTS_TRACKER.md` `S5-13`, `S5-14`, `S5-15`,
`S5-16`, `S5-17`, `S5-19`, `S5-20`.

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

**Session 6 extension (2026-09-16, ~18:47 UTC) — disclosed, not
confirmed**: Session 6 §B raised a related, but **not yet verified**,
question — whether V2's own frozen contract's *stated* eligibility
wording (the original Task 109 specification text) is broader than
the *actual*, inspected operational liquidity screen currently
enforced in code (20-session median-volume/price-floor gate). This
session did **not** perform a side-by-side comparison of the frozen
contract's exact text against the operational screen's exact code to
confirm whether a real gap exists — it is recorded here as an open
question to check, per the explicit instruction not to silently
rewrite the frozen contract's wording to match the code (or vice
versa) without that comparison first. **Status of this specific
sub-question**: not assessed, tracked under this same `OPS-006` entry
rather than a new ID, since it is the same underlying "stated
eligibility vs. implemented registry/screening reality" theme.
Related: `REQUIREMENTS_TRACKER.md` `S6-07`.

---

## OPS-007 — Intraday EOD-flatten durable-recovery gap

**Status**: `OPEN` — approved target design exists (Session 6 §H); no
implementation.

**Found**: Session 6 documentation pass (2026-09-16), via targeted code
inspection of `talonx_paper/config.py`, `talonx_paper/engine.py`, and
`talonx_paper/consumer.py`.

**Finding**: Original's intraday EOD-flatten sweep is real and running
(`_eod_flatten_loop`, `talonx_paper/consumer.py:188-218`), defaulting
to wall-clock 15:50 America/New_York (`config.py:141-143`) via a
DST-aware (`ZoneInfo`-based, `engine.py:189-200`) but **not**
exchange-calendar-aware scheduler — it does not check whether "today"
is an actual XNYS trading session. It flattens using the latest cached
positive price adjusted for simulated spread, **with no price-age
check**. A missing price is logged and skipped, and **no durable
recovery state is established** — nothing persists the miss for a
later, evidence-based retry beyond simply waiting for tomorrow's own
scheduled sweep to run again from scratch.

**Explicit implications**: if a required flatten price is genuinely
unavailable at 15:50 ET, the position is neither flattened nor
tracked as a distinguishable "recovery pending" obligation — it simply
waits for the next scheduled sweep, which may itself also miss, with
no escalation, no `EXIT_PENDING`/`EXIT_UNRESOLVED` state, and no
Operations notification. This is a **safe-but-silent** gap (nothing is
fabricated), not a wrong-price risk — but it also provides no
visibility or bounded-recovery guarantee.

**Future corrective work — NOT IMPLEMENTED here**: make the scheduler
exchange-calendar-aware; add a price-age check; build durable,
cross-restart recovery state through the official close of the next
session; add the per-account new-entry block while unresolved; add
deduplicated Operations notification; add the `EXIT_PENDING ·
AWAITING_PRICE` → `EXIT_UNRESOLVED` state progression described in
Session 6 §H.

**Evidence references**: `talonx_paper/config.py:141-143`; `talonx_paper/
engine.py:189-200`; `talonx_paper/consumer.py:188-218`.

**Related**: `REQUIREMENTS_TRACKER.md` `S6-21`, `S6-22`, `S6-23`.

---

## OPS-008 — Entry-geometry next-bar-execution and pre-fill RRR re-check gap

**Status**: `OPEN` — approved target design exists (Session 6 §F); no
implementation. The **inspected baseline itself is sound** (see
below) — this is a gap between baseline and target, not a defect in
the baseline.

**Found**: Session 6 documentation pass (2026-09-16), via targeted code
inspection of `talonx_quant/consumer.py` and `talonx_paper/engine.py`.

**Finding**: `QuantScanner._revalidate_candidate()`
(`talonx_quant/consumer.py:2017`) genuinely recalculates full trade
geometry against the latest buffered close before publication, and
`fill_geometry_is_valid()` (`talonx_paper/engine.py:156-186`) genuinely
checks the fill lands inside the stop/target bracket when both exist
— **this session explicitly confirms neither "no revalidation exists"
nor an unqualified economic-bias claim is supported**. The gap is
narrower and more specific: (1) the paper-buy path does not re-check
minimum RRR **after** the spread adjustment is applied to the fill
price — RRR is validated once, pre-spread; (2) today's alert-driven
entry fires on its own signal bar, not a deliberately-delayed
"next consecutive eligible one-minute bar's open" as the approved
target describes; (3) there is no explicit T-10 cutoff-and-cancel
mechanism, no bounded missing-bar recovery, and no frozen-stop/target-
never-moved enforcement distinct from what already exists structurally
by not having a rescue path at all.

**Future corrective work — NOT IMPLEMENTED here**: build the
next-eligible-bar-open entry scheduler; add a post-spread RRR
recheck (>= 1.5) at the execution-adjusted price; add explicit
geometry/data/admission skip-reason recording; add the T-10 cutoff;
define and implement the missing-bar bounded-recovery duration
(pending `OPS-005`'s provider qualification, tracked as `S6-26`); the
exact cost-model numbers remain deferred (`S6-25`).

**Evidence references**: `talonx_quant/consumer.py:2017-2050`;
`talonx_paper/engine.py:156-186`.

**Related**: `REQUIREMENTS_TRACKER.md` `S6-16`, `S6-17`, `S6-18`,
`S6-25`, `S6-26`.

---

## OPS-009 — Exit-precedence and ambiguity-handling gap

**Status**: `OPEN` — approved target design exists (Session 6 §G); no
implementation.

**Found**: Session 6 documentation pass (2026-09-16), via a
repository-wide search.

**Finding**: a search for `AMBIGUOUS_INTRABAR_ORDER`, `EXIT_UNRESOLVED`,
and `EXIT_PENDING` found **no matches anywhere in `talonx_paper/`** or
elsewhere in the codebase. None of Session 6 §G's agreed target
behaviors exist today: market-time exit-precedence resolution between
stop and target, the conservative stop-first assumption with an
explicit `AMBIGUOUS_INTRABAR_ORDER` tag, the declared stop-crossing/
gap-below-stop fill models, the extreme-low-fill prohibition, or the
stop-market-vs-stop-limit distinction. Exactly-once **position**
closure (distinct from V2's already-confirmed exactly-once
**reservation-release**, `S5-17`) was not separately traced this
session either.

**Future corrective work — NOT IMPLEMENTED here**: implement
market-time-sequenced exit resolution; implement the stop-first
conservative assumption and its `AMBIGUOUS_INTRABAR_ORDER` tag;
implement the declared fill models for ordinary and gap-below-stop
stop crossings; implement exactly-once position-closure guarantees
for duplicate/late exit instructions.

**Evidence references**: repository-wide search, this session (no
matches for the three cited status/tag strings).

**Related**: `REQUIREMENTS_TRACKER.md` `S6-19`, `S6-20`, `S6-23`.

**Session 7 correction (2026-09-16, ~20:55 UTC) — string-search
findings separated from control-flow evidence**: the original finding
above is accurate as a **string search** (no code matches those three
exact label strings) but was read too broadly — it does **not** mean
"no related exit protection exists at all." Direct reading of
`talonx_paper/engine.py`'s actual control flow this session found a
real, working `check_stop_take()` function (`engine.py:96-135`) that:
runs on every market tick for an open position; uses ATR-anchored
stop/target dollar levels persisted at signal time (falling back to
percentage bands only when those levels are missing); and **already
applies a stop-first conservative tiebreak** — its own docstring
states "on the (rare) tick where both thresholds are somehow crossed
at once, protecting capital wins the tiebreak over locking in a gain."
Exit fills also already go through `apply_spread(..., "SELL")`
(`talonx_paper/consumer.py`, multiple call sites; `simulated_spread_bps`
default 5bps, `talonx_paper/config.py:99`) — a real, working friction/
cost model on exits, not merely on entries.

**Corrected characterization**: the specific **explicit tagging**
(`AMBIGUOUS_INTRABAR_ORDER`), the **gap-below-stop vs. ordinary-
crossing** distinct fill models, the **stop-market-vs-stop-limit**
distinction, and true **sub-bar/intrabar** (rather than per-tick)
ordering resolution remain genuinely **not implemented** — that part
of the original finding stands. But the *conservative stop-first
tiebreak itself*, and *a real exit-side friction/slippage model*, are
**already implemented**, under different naming and at tick
granularity rather than the target's bar/intrabar granularity. This
finding's `Status` remains `OPEN` for the genuinely-missing pieces;
this correction narrows, rather than closes, the gap.

**Related requirement corrections**: see `REQUIREMENTS_TRACKER.md`
`S6-19`/`S6-20`'s own dated correction notes.

---

## OPS-010 — Development-centric grouping and CORRECTION-linkage gap

**Status**: `OPEN` — agreed target design exists (Session 7 §E); no
implementation.

**Found**: Session 7 documentation pass (2026-09-16), via direct
reading of `talonx_ingest/intelligence/delivery/update_policy.py` and
`outbox.py`.

**Finding**: `update_policy.py`'s `classify_update()` is real, working,
deterministic infrastructure — it decides `NEW` / `UPDATE` /
`SUPPRESS_DUPLICATE` / `SUPPRESS_NOOP` for a re-rendered card, keyed on
`content_hash` and significance band, with a defined set of
"material marker" line prefixes that count as a real content change.
This is genuine precedent for part of Session 7 §E's requirement.
**Two distinct gaps remain**: (1) `DeliveryOutbox` operates on one
`delivery_id` per `event_id` (`outbox.py:204,774`) — there is no
`development_id`/group/topic field to link multiple filings, press
releases, agreements, or amendments into one development record, so
today's dedup/update mechanism cannot group across sources the way
§E describes; (2) `classify_update()` has no `CORRECTION` decision
type — a materially-wrong repair of previously-delivered information
and a genuine new material change are not currently distinguished
from each other, so §E's and §G's `CORRECTION`-specific rules (link to
original, eligible despite mutes, never broadcast to new recipients,
etc.) have no existing decision type to attach to.

**Future corrective work — NOT IMPLEMENTED here**: design and
implement a development-record grouping key (verified entity +
transaction/topic + relevant dates, per `S7-12`); add a `CORRECTION`
decision type to `update_policy.py`, distinct from `UPDATE`; implement
the correction-specific delivery rules (§G) on top of that new type.

**Evidence references**: `talonx_ingest/intelligence/delivery/
update_policy.py` (full file read this session); `talonx_ingest/
intelligence/delivery/outbox.py:204,774`.

**Related**: `REQUIREMENTS_TRACKER.md` `S7-12`, `S7-13`, `S7-14`,
`S7-21`.

---

## OPS-011 — Per-stock company-event mute and materiality-catalogue gap

**Status**: `OPEN` — agreed target design exists (Session 7 §B/§C/§G);
no implementation.

**Found**: Session 7 documentation pass (2026-09-16), via targeted
search of `talonx_ingest/intelligence/dashboard/render.py` and
`talonx_ingest/intelligence/significance/`.

**Finding**: no per-stock company-event mute feature exists — a search
for "mute" in the Intelligence dashboard's render code found only a
CSS class name (`.muted`, a text-styling convention unrelated to
notification suppression). Separately, Intelligence's existing
significance engine (frozen ruleset `information-significance-v1`,
`talonx_ingest/intelligence/significance/`) computes a band score
(LOW/MEDIUM/HIGH/CRITICAL) — a real, working mechanism, but a
**different** one from Session 7 §C's agreed versioned, route-specific
materiality-rules catalogue (Route 1 verified-status-change vs. Route
2 measured-quantitative-development, each with its own evidence
rules). The existing content gate (`notification_policy.py`'s
`_substantive_evidence`) is likewise a single-axis check, not
Session 7 §B's six-question rubric evaluated individually.

**Explicit implication**: a `HIGH`/`CRITICAL` significance band today
does **not** by itself imply the six-question rubric or either
materiality route would be satisfied — the existing scorer and the
newly agreed qualification requirements are related but distinct, and
must not be conflated when this gap is eventually closed.

**Future corrective work — NOT IMPLEMENTED here**: build a per-stock
company-event mute (distinct from Original's own ticker-pause, which
is a structurally separate system per `S3-08`/`OPS-006`); build the
versioned materiality-rules catalogue with its two routes; build the
six-question rubric as an explicit, individually-evaluated gate ahead
of (not replacing) the existing significance engine. Numerical
thresholds for Route 2 and freshness windows are separately deferred
(`S7-25`, `S7-26`) and are explicitly **not** part of this finding's
corrective scope.

**Evidence references**: `talonx_ingest/intelligence/dashboard/
render.py` (targeted search, this session); `talonx_ingest/
intelligence/significance/` (established, this project's Task 96E
history); `talonx_ingest/intelligence/delivery/notification_policy.py`
(established, this project's Task 138-140c history).

**Related**: `REQUIREMENTS_TRACKER.md` `S7-05` through `S7-10`,
`S7-20`, `S7-23`.

---

## OPS-012 — V2 `EXIT_UNRESOLVED` account-block gap

**Status**: `OPEN` — agreed target design exists (Session 8 §E); no
implementation.

**Found**: Session 8 documentation pass (2026-09-16/17), via direct
reading of `talonx_v2/store.py`, `talonx_v2/service.py`, and
`talonx_v2/paper.py`.

**Finding**: `mark_exit_unresolved()` (`talonx_v2/store.py:410-419`)
correctly implements a real, distinct `EXIT_UNRESOLVED` status —
neither `OPEN` nor `CLOSED`, its own docstring says "loudly surfaced
for the operator" — set only after the full fall-forward window is
exhausted (`talonx_v2/pipeline.py:164-175`), durable (a DB row, so
correctly **not** cleared by a process restart), and correctly
surfaced in service status output via `store.unresolved_positions()`
(referenced at `service.py:1054,1159`). **However, `unresolved_
positions()` is used only for status reporting — it is never consulted
by `paper.py::open_position()`'s own admission gate**
(`talonx_v2/paper.py:93-139`, the same gate sequence already read in
this project's history: episode/intent checks, `SYMBOL_ALREADY_OPEN`,
cooldown, `MAX_CONCURRENT_*`, entry price, cash). **No code path
blocks a NEW entry (for any symbol) while an `EXIT_UNRESOLVED`
position exists anywhere in the account.**

**Explicit implication**: Session 8 §E's agreed containment policy
("block new entries in the affected V2 account until auditable
resolution") is a real product decision with **no corresponding
enforcement** in the code inspected this session — an `EXIT_UNRESOLVED`
position today reduces open capacity by one slot (via `n_open()`'s
ordinary count) but does not otherwise prevent new admissions
elsewhere in the same account, and does not require any operator
action before the system resumes normal admission behavior.

**Future corrective work — NOT IMPLEMENTED here**: add an explicit
account-wide gate in `open_position()` (or an equivalent point) that
consults `unresolved_positions()` and refuses new admissions while any
row is `EXIT_UNRESOLVED`; define the exact "auditable resolution"
release mechanism (manual investigation, never an invented price, per
Session 8 §E).

**Evidence references**: `talonx_v2/store.py:410-419`; `talonx_v2/
pipeline.py:164-175`; `talonx_v2/service.py:1054,1159`; `talonx_v2/
paper.py:93-139` (full admission-gate sequence, no `EXIT_UNRESOLVED`
check present).

**Related**: `REQUIREMENTS_TRACKER.md` `S8-13`, `S8-17`, `S8-18`.

**Session 11 update (2026-09-17, ~10:22 UTC) — clearance policy
defined, not implemented**: Session 11 §5 defines the exact clearance
policy this finding was waiting on — `EXIT_UNRESOLVED` is exactly the
"terminal unresolved exit" category requiring auditable resolution and
explicit operator clearance (`S11-15`), and restart must never
auto-clear it (`S11-15`). **This session still does not implement the
gate** — the release mechanism above remains the correct future fix.
Tracked jointly under `OPS-016` (the missing readiness-state model
this clearance policy would run inside) without merging the two
findings.

---

## OPS-013 — Telegram lifecycle-message-formatting and delivery-consolidation gap

**Status**: `OPEN` — agreed target design exists (Session 9 §B/§C/§D);
no dedicated implementation.

**Found**: Session 9 documentation pass (2026-09-17), via targeted
code review against this project's own established delivery
infrastructure.

**Finding**: the underlying mechanisms Session 9's message-formatting
requirements would draw from are real: per-strategy skip codes
(`S2-03`), `update_policy.py`'s `NEW`/`UPDATE`/`SUPPRESS_DUPLICATE`/
`SUPPRESS_NOOP` decisions (`S7-14`), and the `AMBIGUOUS`/`PENDING`/
`SENT` outbox states (established, Task 96F/117). **No dedicated
message-formatting layer exists on top of these** implementing: the
"Opportunity status"/"Paper status" separate-line format (`S9-05`);
the four-transition main-lifecycle-notification policy as its own
explicit rule, distinct from the underlying mechanisms that could
support it (`S9-08`); the exit-problem dual-destination routing rule
(`S9-10`, blocked in part on `S9-02`'s Operations bot not existing);
or the obsolete-pending-notification consolidation rule (`S9-11`).

**Future corrective work — NOT IMPLEMENTED here**: design and build
the message-formatting layer described in Session 9 §B; wire the
four-transition policy explicitly (rather than relying on ad hoc
per-strategy skip/update logic); build the consolidation rule for
obsolete pending notifications; build the Operations bot (`S9-02`) as
a prerequisite for the exit-problem dual-routing rule.

**Evidence references**: `talonx_ingest/intelligence/delivery/
update_policy.py`, `talonx_v2/paper.py` (established + this session).

**Related**: `REQUIREMENTS_TRACKER.md` `S9-05`, `S9-08`, `S9-10`,
`S9-11`.

---

## OPS-014 — Whole-share, fee-aware sizing not implemented

**Status**: `OPEN` — agreed target formula exists (Session 10 §C); no
implementation.

**Found**: Session 10 documentation pass (2026-09-17), via direct
reading of `talonx_paper/engine.py`.

**Finding**: `talonx_paper.engine.calculate_buy()` (reused by V2,
`talonx_v2/paper.py:25,115`) is defined as `calculate_buy(cash:
float, allocation_usd: float, price: float) -> tuple[float, float] |
None`, and its body returns `spend / price, spend` where `spend =
min(allocation_usd, cash)` — a **continuous, fractional** share count,
computed with **no fee parameter at all**. This directly confirms, with
concrete evidence, the caution already recorded in `S8-08` ("do not
imply all actual V2 quantities are already whole shares") — today's
actual sizing is not whole-share, and has no fee-awareness whatsoever
to reduce for a fee even if it wanted to.

**Explicit implication**: Session 10 §C's entire whole-share/fee-aware
sizing formula (`quantity × modeled_buy_price + fee(quantity, price)
<= reserved allocation`, choosing the largest non-negative whole
quantity) is a **target design**, not a description of any existing
behavior — there is no partial implementation to point to for this
specific requirement.

**Future corrective work — NOT IMPLEMENTED here**: replace
`calculate_buy()`'s continuous division with a whole-share search (or
closed-form `floor` when the fee is flat) against the agreed formula;
add a fee function parameter supporting percentage/per-share/minimum
fee structures; add an explicit sizing-skip outcome for zero eligible
shares; wire the pre-commit validation list (§C) around it.

**Evidence references**: `talonx_paper/engine.py:71-83`; `talonx_v2/
paper.py:25,115`.

**Related**: `REQUIREMENTS_TRACKER.md` `S10-07`, `S10-08`, `S10-09`.

---

## OPS-015 — EOD/restart reconciliation-mismatch does not block new admissions

**Status**: `OPEN` — agreed target design exists (Session 10 §H); no
implementation. Same structural pattern as `OPS-012`, a **different**
finding for a different trigger — kept as a separate ID, not merged.

**Found**: Session 10 documentation pass (2026-09-17), via direct
reading of `talonx_ops/eod_reconciliation.py`.

**Finding**: `talonx_ops/eod_reconciliation.py` genuinely **detects**
accounting mismatches — `STATUS_MISMATCH = "RECONCILED_WITH_MISMATCH"`
(line 43), with real, working mismatch-detection logic (lines
252-313) that produces this status whenever it finds a discrepancy.
**No code path was found that connects this detection to blocking new
admissions** in the affected account — reconciliation (a reporting/
detection concern) and admission-gating (an execution concern) are
structurally separate, unconnected mechanisms today, exactly the same
pattern already found for V2's `EXIT_UNRESOLVED` status (`OPS-012`),
but triggered by a ledger mismatch rather than an exhausted exit
fall-forward.

**Future corrective work — NOT IMPLEMENTED here**: wire
`STATUS_MISMATCH` (or an equivalent authoritative reconciliation
result) into each account's own admission gate, so a genuine mismatch
blocks new admissions in that account while existing obligations
continue to be managed; define and implement the block-clearance
mechanism (explicitly assigned to Session 11, not decided here).

**Evidence references**: `talonx_ops/eod_reconciliation.py:43,252-313`.

**Related**: `REQUIREMENTS_TRACKER.md` `S10-20`, `S10-21`; `OPS-012`
(the analogous V2-specific finding).

**Session 11 update (2026-09-17, ~10:22 UTC) — clearance policy
defined, not implemented**: Session 11 §5 names "ledger mismatches"
explicitly as one of the four serious-block categories requiring
auditable resolution and explicit operator clearance (`S11-15`) — the
same policy `OPS-012` received, now also covering this finding's own
trigger. Still not implemented; tracked alongside `OPS-016`.

---

## OPS-016 — No account-readiness state model or external outage watchdog

**Status**: `OPEN` — agreed target design exists (Session 11 §5/§6);
no implementation.

**Found**: Session 11 documentation pass (2026-09-17), via targeted
search of `talonx_ops/`.

**Finding**: no code in `talonx_ops/` implements the agreed five-state
account-readiness model (Checking and recovering / Ready / Managing
positions — new entries blocked / Paused by user / Stopped, `S11-12`),
a truthful "Partially Ready" global summary (`S11-13`), or an
independent external watchdog for total application/host outage
detection (`S11-17`) — a targeted search for `grace_period`,
incident-deduplication, and watchdog-related terms across `talonx_ops/`
found no matches. This is the **missing policy layer** that `OPS-012`'s
and `OPS-015`'s own clearance mechanisms (Session 11 §5, `S11-15`)
would need to run inside — those two findings' underlying detection is
real; this finding is about the **presentation/enforcement layer**
that would consume that detection and gate admissions on it.

**Future corrective work — NOT IMPLEMENTED here**: design and
implement the five-state model as an explicit, queryable account
status; implement the "Partially Ready" global summary; implement a
transient-block-clears-when-checks-pass mechanism; implement the
serious-block auditable-clearance workflow that `OPS-012`/`OPS-015`
would both plug into; stand up (or integrate with) an external
watchdog process, since nothing internal to the application can
observe its own total failure.

**Evidence references**: targeted repository-wide search, this
session (no matches in `talonx_ops/` for the cited concepts).

**Related**: `REQUIREMENTS_TRACKER.md` `S11-12` through `S11-15`,
`S11-17`, `S11-18`; `OPS-012`, `OPS-015`.

---

*See `REQUIREMENTS_TRACKER.md` for product-requirement tracking,
`DECISION_LOG.md` for the session-by-session product-owner record, and
`docs/research/TALONX_RESEARCH_LEDGER.md` for the research/validation
task history. This file tracks operational/runtime findings only.*
