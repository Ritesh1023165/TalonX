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

**Package 3 update (2026-09-17) — Finding B CLOSED; Finding A
re-confirmed (still open, unaffected)**:

Finding B (the intra-runtime dual-deadline discrepancy) is now
corrected: `talonx_v2/calendar.py::session_close_utc()` (new) gives the
REAL official XNYS close timestamp (honoring early closes, e.g.
13:00 ET the day after Thanksgiving, never approximated as a fixed
hour offset). `V2Service._recovery_deadline_session()`/
`_recovery_deadline_passed()` (new) provide ONE unified Session-3
boundary, used by BOTH the coarse admission gate (`tick()`'s
`stale_cut`, corrected from a 4-session to the agreed 3-session
window) and a new PROACTIVE check inside `_phase_open()` that refuses
a fill attempt once the deadline has genuinely passed — live ticks
compare the real wall clock against the actual close; non-live
(replay/restart) ticks use the pre-existing, already-correct
date-only boundary. All 5 of Finding B's own listed acceptance
scenarios are now tested (ordinary week, weekend, holiday, live
immediately-before/after the actual close). See
`docs/research/evidence/package3_pricing_timing/README.md` §4.

Finding A was DIRECTLY RE-CONFIRMED this session (previously only
"recorded for re-verification," not re-checked since Task 112R):
`talonx_v2/cluster_engine.py` still fires episode activation at the
2nd distinct owner filing, unchanged. Task 112R's own original
cross-methodology difference against the research `build_episodes`
methodology (last-filing activation) therefore still stands, fully
unresolved by Package 3 (which never touches `cluster_engine.py`).
See `REQUIREMENTS_TRACKER.md`'s new `S13-12` and the evidence README
§7 for the full `PARTIALLY_COMPATIBLE` classification and its exact
consequences for which prior V2 result figures may/may not be
attributed to the release runtime.

---

## OPS-004 — Corporate-action and fractional-share handling gap

**Status**: `PARTIALLY_RESOLVED (V2 forward/reverse-split accounting, PQ-2A
2026-09-21)` — see the *PQ-2A update* below. Still open: cash-dividend
accounting (`DIVIDEND_POLICY_DECISION_REQUIRED`), mergers/spin-offs/renames
(fail closed, not supported), truncate+cash-in-lieu (`S5-26`), Original's
own accounting. Original text of this finding follows unchanged.

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

**PQ-2A update (2026-09-21)** — V2 only. Root cause of the PQ-1 "-89% on a
10:1 split" was a price-BASIS mismatch: entry price/shares/cost persisted on
the basis the provider served at entry time, exit close served on the
post-split basis, shares never re-expressed. Implemented (additive, no
migration): explicit-event corporate-action layer `talonx_v2/corporate_actions.py`
(Alpaca `/v1/corporate-actions` + optional yfinance witness), append-only
`position_corporate_actions` trail, exact-`Fraction` share adjustment with
unchanged aggregate cost basis, idempotent by content key, per-fill
`basis_as_of` proof, settlement on economic quantity, fail closed
(hold-in-window / `EXIT_UNRESOLVED`) for unavailable/conflicting/unsupported/
unknown-basis evidence, reconciliation + read-only operator projection, and
`CompositeBarAdapter.history()` now refuses to splice bases it cannot prove
compatible. Reverse-split fractional entitlement is retained EXACTLY (not the
agreed `S5-26` truncate+cash-in-lieu, whose settlement reference no source
provides) — recorded as a gatekeeper decision. Cash dividends are observed and
never credited (interim price-return-only mechanics; agreed `S10-17`
total-return treatment needs a receivable lifecycle). Legacy/unknown-basis
positions are never back-filled. Evidence:
`docs/research/evidence/provider_qualification_pq2a/`.

**PQ-2A closure update (2026-09-21)** — the two PQ-2A follow-ups are resolved by
gatekeeper decision for V2: exact fractional entitlement (S5-26 revised; no
cash-in-lieu, new entries whole-share only) and TOTAL-RETURN dividend
accounting (S10-17 retained and implemented: explicit-event ACCRUED->CREDITED
lifecycle, ex-date ownership rule, split-trail quantity, post-close credit,
dividend-unadjusted fill basis). Still fail-closed / open: mergers, spin-offs,
renames, unit splits, stock/special/foreign distributions; ex-date == entry
basis-date ambiguity; provider corporate-action SLA. Status remains
`PARTIALLY_RESOLVED (V2)` for complex actions and Original's own accounting.
Evidence: `docs/research/evidence/provider_qualification_pq2a_closure/`.

**Evidence references**: targeted repository-wide search, this
session (no matches in `talonx_v2/`, `talonx_paper/`, `talonx_ops/`).

**Related**: `REQUIREMENTS_TRACKER.md` `S5-15`, `S5-16`, `S5-21`
through `S5-27`.

---

## OPS-005 — Price-provider qualification gap

**Status**: `RESOLVED (PQ-2B, 2026-09-21, contract level; V2 release mode implemented, NOT activated)`
— see the *PQ-2B update* below. Original finding text follows unchanged; it
extends `OPS-002`'s pricing-freshness finding with the provider-selection
question.

**PQ-2B update (2026-09-21)** — ONE executable first-release provider contract
now exists (`talonx_v2/provider_contract.py`, `talonx_v2/sip_adapter.py`):
Alpaca Market Data v2 `/v2/stocks/bars`, `feed=sip`, `1Day`, `adjustment=split`,
fallback `NONE` (fail closed), opt-in via `--pricing-mode sip` behind a QUALIFIED
readiness check. Measured semantics: daily **close == official closing-auction
cross** (30/30 samples incl. 4 early closes); daily **open is the provider's
first eligible trade, NOT the official opening auction print** (exact in 7/29,
max deviation 1.2%); daily **volume is consolidated full-tape-day** (regular +
post-market). OPEN and CLOSE of session S are usable only once the daily bar is
COMPLETE: `now >= close(S)+4h (post-market end; 17:00 ET on an early close) + 15 min
(conservative margin = the documented free-tier SIP delay window; the `end` parameter rule
is verified: end=now-10min -> 403, now-16min -> 200; a live probe showed the in-progress
current-day bar is served ~81 s after the open but is provisional) + 1 min`. Liquidity history comes from the SAME provider/basis (no snapshot splice;
exact 20 contiguous sessions). Revision study: 3,150 bars over 150 symbols,
snapshot (2026-09-06) vs re-fetch (2026-09-21): 2,751 identical, 399 uniform
dividend basis shifts, **0 genuine revisions**. Residual (bounded): the provider
exposes no correction/version metadata, so a correction after first usability is
not detectable — the persisted execution value is immutable and a later provider
value is never applied silently. Production activation NOT performed.
Evidence: `docs/research/evidence/provider_qualification_pq2b/`.

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

**PQ-1 update (2026-09-19)**: **remains OPEN**. Current configured
credentials now successfully return recent Alpaca SIP historical
`1Day adjustment=all` bars (bounded read-only probe: AAPL, five
completed sessions, HTTP 200; no broker/order call), superseding the
old Task 117 entitlement observation for current availability only.
This does not close qualification: no V2 runtime SIP adapter exists;
no provider-guaranteed immutable/sufficient-finality boundary was
established for the consumed daily open/close; and the current
all-adjusted execution model is not paired with split share/basis or
dividend-entitlement accounting (`OPS-004`). `PQ1_NOT_ACCEPTED` is
therefore the evidence-based gate verdict. Automatic fallback remains
unqualified; default/provider activation remains unchanged. New
resolver-backed trades now persist additive entry/exit provider
provenance (composite modes name the actual supplying sub-adapter), while
legacy provenance remains NULL rather than invented. Also found: composite
history can mix adjustment bases across a split between snapshot and live
tail, and a characterization test demonstrates a spurious ~-89% realized
loss for a 10:1 split during a hold (same open corporate-action gap).
Evidence: `docs/research/evidence/provider_qualification_pq1/`.

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

**Package 1 update (2026-09-17, ~12:49 UTC) — capacity/symbol/
valuation half CLOSED; account-wide block still OPEN**: Session 13's
Package 1 (`S13-09`) fixed the three consequences of this finding that
were within its own scope — `n_open()` now counts `EXIT_UNRESOLVED`
toward capacity (no longer silently frees a slot),
`position_for_symbol()` now also matches `EXIT_UNRESOLVED` (a second
position in the same symbol is correctly refused), and the reporting/
reconciliation paths (`talonx_ops/paper_performance.py`,
`talonx_ops/prospective/close.py`) now include an unresolved
position's cost basis instead of silently omitting it. **The
account-wide "block ALL new admissions while any `EXIT_UNRESOLVED`
position exists" gate itself — Session 8 §E's actual containment
policy — remains genuinely `OPEN`, not implemented**; this was
explicitly out of Package 1's scope ("Package 2's account-wide
admission block and explicit clearance workflow remain out of scope.
Do not claim those requirements are satisfied by slot retention.").
Verified by 5 new isolated tests
(`tests/test_package1_settlement_integrity.py`), captured failing
against the unmodified baseline first, then passing after the fix.

**Package 2 update (2026-09-17, ~15:27 UTC) — CLOSED**: the
account-wide gate this finding described as missing is now
implemented. `talonx_v2/store.py::mark_exit_unresolved()` durably
records an `EXIT_UNRESOLVED` row in a new, generic, additive
`account_blocks` table (`talonx_ops/account_blocks.py`) in the SAME
commit as the status transition; `talonx_v2/paper.py::enter_position()`
checks `account_blocks.blocked_reason()` as the FIRST statement inside
its own protected `store.transaction()` block — the same transaction
as the entry's economic mutation, not an earlier read or a dashboard
flag — and refuses admission for ANY symbol, not only the affected
one, until an operator clears it. Restart-durable (ordinary DB rows);
idempotent (repeated detection never duplicates an active block);
clearance requires an identified operator, a stated reason, and a
reference to supporting evidence, is refused while the position is
still `EXIT_UNRESOLVED` (Package 2 does not invent an exit price or
force settlement), and is invoked via
`python -m talonx_ops.prospective clear-block` (a minimal CLI, not a
new dashboard). The identical mechanism was also extended to
`talonx_paper.store` (`execute_buy`/`execute_long_term_buy`) for the
local Intraday/Long-term accounts, with separate account identities
sharing one file. Verified by 25 new isolated tests
(`tests/test_package2_account_blocks.py`), including a real two-
connection SQLite-write-lock race proving a competing writer cannot
commit an entry after a prior block activation. See `OPS-015` and
`OPS-016` below for the parts of this finding's own neighbouring
findings this same change also affects.

**Package 2 Acceptance Review update (2026-09-17) — a gap in the fill
path's own upstream reservation step found and closed**: the
acceptance review traced the FULL V2 lifecycle (candidate → reservation
→ durable PENDING intent → a later tick's fill), not just the
admission-gate check in isolation, per the review's own explicit
instruction. The fill path itself was confirmed already safe (the
account-block check is the only gate on the ONLY code path that ever
marks an intent FILLED). A real gap was found one step upstream:
`V2Service._capacity_rejection_reason()` — the sole gate on creating a
NEW PENDING intent (reservation) — checked cash/slot capacity only,
never the account block, so a brand-new episode discovered while the
account was blocked could still receive a fresh reservation and an
ACTIONABLE alert promising a fill that could never occur. Fixed: an
unconditional account-block check (never gated behind
`TALONX_V2_DURABLE_STORE_ENABLED`, unlike the capacity check) now runs
first, inside the same transaction as the reservation write. Legitimate
expiry/cancellation of an existing PENDING intent, and existing
open-position exits, were confirmed to remain unaffected (both are
already unconditional and were not touched). 5 new isolated tests
(`tests/test_package2_acceptance_review.py`), including a genuinely
independent-connection race. See `docs/research/evidence/
package2_account_blocks/ACCEPTANCE_REVIEW.md` §A1 for full detail.

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

**Status**: `CLOSED` (for V2) — Package 4, 2026-09-17. Original's own
sizing is unaffected/unchanged (separate, out-of-scope). See the
Package 4 update below for the full record.

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

**Package 4 update (2026-09-17) — CLOSED for V2**: a new, V2-only
module `talonx_v2/sizing.py` implements Session 10 §C's exact agreed
formula — the largest whole `Q` such that `Q*price + fee_fn(Q,price)
<= allocation`, via a bounded backward search (correct for ANY fee
shape, not just a flat/quantity-independent one), never rounding up,
with an explicit sizing-skip reason when zero shares are eligible.
Wired into `talonx_v2/paper.py::enter_position()`/`close_position()`,
replacing `talonx_paper.engine.calculate_buy`/`calculate_sell_pnl` for
V2 specifically — Original's own shared copies remain completely
unmodified (Original's fractional-share sizing is a separate,
out-of-scope concern; the frozen "no fractional shares" requirement
is scoped to "the first-release V2 paper strategy" only). The default
`fee_fn` (`sizing.zero_fee`) returns `0.0` — the current, frozen,
approved cost assumption; `S10-22`'s own numerical cost-assumption
question remains unresolved and undecided by this closure. A dormant
P&L defect was also found and fixed in the same pass:
`calculate_sell_pnl` re-derived cost basis as `shares*entry_price`
rather than reading the authoritative persisted `position_cost`
(entry_total) — invisible under the zero-fee assumption (they were
numerically identical), but would have silently omitted the entry fee
from P&L the moment any non-zero fee was ever configured; V2's new
`sizing.compute_exit_economics` uses the authoritative persisted total
throughout. Verified by 28 new isolated tests
(`tests/test_package4_sizing_accounting.py`), including a genuinely
independent-connection concurrency proof that two admissions cannot
together overcommit account cash. See `docs/research/evidence/
package4_sizing_accounting/README.md` for full detail.

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

**Package 1 update (2026-09-17, ~12:49 UTC) — a related but DISTINCT
V2-specific defect fixed; this finding's own admission-block gap
remains fully OPEN**: this finding is specifically about
`talonx_ops/eod_reconciliation.py` (Original/Experimental's base
reconciliation). Package 1 (`S13-09`) did **not** touch that file —
it fixed a separate, V2-specific bug in
`talonx_ops/prospective/close.py::_v2_reconcile()`, where an
`EXIT_UNRESOLVED` position's cost basis was omitted from the
`cash_plus_open_cost_reconciles` formula, causing that check to
**fabricate** a mismatch purely because the cost was missing from the
arithmetic — not a real accounting problem. That specific fabrication
is now fixed (verified by an isolated test, captured failing against
the unmodified baseline first). **This does not close this finding**:
the actual "genuine mismatches don't block new admissions" gap this
entry describes — for either `eod_reconciliation.py` or
`_v2_reconcile()` — is unchanged and remains fully `OPEN`, tracked
alongside `OPS-016` exactly as before.

**Package 2 update (2026-09-17, ~15:27 UTC) — CLOSED for both cited
reconciliation sources**: both halves of this finding are now wired to
persisted, enforced blocks via the same generic `account_blocks`
mechanism described under `OPS-012`. (1) V2:
`talonx_ops/prospective/close.py::_record_v2_reconciliation_blocks()`
connects `_v2_reconcile()`'s own already-verified
`cash_plus_open_cost_reconciles`/`no_negative_cash` FAIL results to a
`LEDGER_MISMATCH`/`CASH_DEFICIT` block on the `V2` account, called from
`run_close()` immediately after `_v2_reconcile()`. (2)
Original/Intraday — this finding's own literal finding location:
`talonx_ops/eod_reconciliation.py::_record_original_intraday_
reconciliation_blocks()` connects `build_reconciliation()`'s own
conservative `original_paper: N open position(s) but 0 trades recorded
ever` mismatch to a `LEDGER_MISMATCH` block on `ORIGINAL_INTRADAY`
specifically — `original_paper` is read from ONLY the
`positions`/`trade_history` tables (never `long_term_positions`/
`long_term_trade_history`), so this attribution is exact, not an
invented identity check. `experimental_paper` mismatches are
deliberately **not** wired (Package 2's scope is "local Intraday and
V2"; Experimental is a separate, untouched architecture — still an
open gap, not claimed closed). Both connections open their own minimal
write connection rather than the owning store's constructor, so
neither ever triggers unrelated schema-migration/portfolio-seed side
effects on a production ledger. Clearance for either reason type
re-runs the SAME bounded reconciliation fresh at clearance time (never
the evidence attached at detection time) and refuses if it still
fails. Verified by isolated tests in
`tests/test_package2_account_blocks.py` (see `OPS-012`'s own update
for the full count).

**Package 2 Acceptance Review update (2026-09-17) — Original
CASH_DEFICIT: implemented, plus a real debit-capping gap found and
closed first**: the acceptance review inspected Original's persisted
cash model (`portfolio_state.current_cash` / `long_term_portfolio_
state.current_cash`, no reservation concept) and found that ALL THREE
debit paths (`execute_buy`, `execute_long_term_buy`, `execute_dca_
contribution`) trusted a caller-supplied cost value with NO internal
cap against available cash — callers do pre-size/pre-check today, but
the store itself never verified it, so the "current_cash < 0" signal
this review wanted to build a detector on would not actually have been
reliable. Fixed first (`talonx_paper/store.py`): all three methods now
refuse (no mutation) rather than debit past available cash, the same
"rejected, nothing mutated" contract the account-block check already
uses. Also found `execute_dca_contribution` had NO account-block check
at all (a real Package 2 coverage gap — a DCA contribution is new
economic exposure into an existing position, the same category the
block covers for a fresh BUY) — fixed, mirroring `execute_long_term_
buy` exactly. With every debit path capped, a negative `current_cash`
now has no benign explanation; `talonx_ops/eod_reconciliation.py`'s new
`_record_original_cash_deficit_blocks()` (wired into `run_and_
persist()`) records a `CASH_DEFICIT` block on the correct account when
this occurs. `OPS-015` is now CLOSED for Original as well as V2. 7 new
isolated tests (`tests/test_package2_acceptance_review.py`). See
`docs/research/evidence/package2_account_blocks/ACCEPTANCE_REVIEW.md`
§A2 for full detail.

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

**Package 2 update (2026-09-17, ~15:27 UTC) — still OPEN, by design**:
Package 2 implemented `OPS-012`/`OPS-015`'s underlying serious-block
enforcement and clearance mechanism directly (`talonx_ops/
account_blocks.py` + a minimal `python -m talonx_ops.prospective
{list-blocks,clear-block}` CLI), deliberately **independently** of the
five-state readiness model / "Partially Ready" summary / external
watchdog this finding describes — the task's own scope explicitly
excluded "the full readiness dashboard" and "unrelated pause UI." A
serious integrity block and the pre-existing user-pause control remain
two separate mechanisms; clearing one never touches the other. This
finding's own remaining gaps (the five-state model, the global
summary, the watchdog) are unaffected and remain fully `OPEN` — a
future readiness-state layer can consume `account_blocks.
blocked_reason()`/`active_blocks()` as its data source rather than
needing to invent its own detection.

---

## OPS-017 — Stale hardcoded fingerprint constant in two pre-existing tests

**Status**: `OPEN` — pre-existing, confirmed unrelated to Package 1,
not fixed here (out of Package 1's scope).

**Found**: Session 13 documentation pass (2026-09-17), while running
Package 1's regression suite against a scoped set of 32 existing test
files.

**Finding**: `tests/test_task112_tuesday_release.py::
test_03_v1_fingerprint_intact` and `tests/test_task111_v2_e2e.py::
test_item3_original_strategy_fingerprint_unchanged` both assert
`get_strategy_version() == "2ae6216bca70"` and fail — the actual
computed value is `"ed8272fe568d"`. Direct inspection found
`talonx_ops/prospective/__init__.py:49` already defines
`V1_FINGERPRINT_EXPECTED = "ed8272fe568d"` — the **canonical** current
value used elsewhere in the codebase (e.g. `talonx_ops/prospective/
preflight.py`) — while these two specific test files still hardcode
the **older** literal `"2ae6216bca70"` directly instead of importing
the shared constant. **Confirmed pre-existing and unrelated to Package
1**: reproduced identically with Package 1's changes fully reverted
(`git stash`), against unmodified HEAD `58249ef`. Package 1 never
touches any of Original's frozen strategy files
(`talonx_quant/{strategy,indicators,config,session,consumer}.py`), so
this divergence predates and is independent of this task's work.

**Explicit implication**: these two tests have been silently failing
(or were already known-failing/skipped) independent of any change in
this session; their own historical record of when
`V1_FINGERPRINT_EXPECTED` was last updated versus when these two test
files were last touched was not traced this session.

**Future corrective work — NOT IMPLEMENTED here**: update both test
files to import `V1_FINGERPRINT_EXPECTED` from `talonx_ops.prospective`
instead of hardcoding a literal value, so the two can never silently
drift apart again; separately confirm which value is actually correct
against Original's real, current frozen strategy files before treating
either as authoritative.

**Evidence references**: `talonx_ops/prospective/__init__.py:49`;
`tests/test_task112_tuesday_release.py:84`;
`tests/test_task111_v2_e2e.py:85`; baseline reproduction via `git
stash` (this session).

**Related**: `REQUIREMENTS_TRACKER.md` `S13-07`, `S13-09`.

**Package 2 update (2026-09-17, ~15:27 UTC) — reproduced again,
confirmed still unrelated, not fixed here**: the same two tests fail
identically (`ed8272fe568d` vs the hardcoded `2ae6216bca70`) against
Package 2's own scoped 34-file regression run. Package 2 never touches
`talonx_quant/*` either; both V1's `get_strategy_version()` output and
`V2_FINGERPRINT_EXPECTED = "11107198c5b81237"` were independently
re-verified unchanged before/after this session's own changes via
`tests/test_task114_prospective.py::test_b1_preflight_fingerprints_are_
expected` and `::test_task114_does_not_change_fingerprints` (both
pass). Still out of scope to fix here — same stale-literal defect as
before, unchanged by two full task packages now.

---

## OPS-018 — Clearance verification/write race (found and closed same session)

**Status**: `CLOSED` — found and fixed within the Package 2 Acceptance
Review (2026-09-17); no window where this was OPEN in a released state.

**Found**: Package 2 Acceptance Review, direct inspection of
`talonx_ops/prospective/clearance.py::clear_block()` against the
review's own A4 question ("a successful clearance must not be based on
verification invalidated by a concurrent mutation before clearance
commits").

**Finding**: `clear_block()` called `verify_clearance_eligible()` on
short-lived, separate read connections that opened and closed BEFORE
the actual clearance write (`store.attempt_block_clearance()`) even
began its own transaction — a textbook TOCTOU: a concurrent writer
re-detecting the same underlying issue between "verified healthy" and
"clearance committed" would not be seen, and the clearance would still
proceed to mark the block CLEARED based on now-stale evidence.

**Fix**: `clear_block()` now acquires the account's own write lock
FIRST and holds it continuously through BOTH the fresh verification
read and the clearance write, committing together — for V2 via
`V2Store.transaction()`'s existing real `BEGIN IMMEDIATE`; for Original
via a new `PaperTradingStore.lock()` context manager that issues a
REAL `BEGIN IMMEDIATE` of its own (the store's existing `threading.
Lock` alone was insufficient, since `clear_block()` constructs its own
fresh store instance rather than reusing any existing one — a
Python-level lock on a freshly-constructed object provides no
protection against a genuinely separate instance). `PaperTradingStore`
also gained `PRAGMA busy_timeout=30000` (previously absent — default
0), so a contending writer correctly waits rather than raising
`OperationalError: database is locked` immediately.

**Verification**: two independent-writer race tests (real threads,
real separate `V2Store`/`PaperTradingStore` connections, a bounded
`Thread.join` liveness check proving the competing writer is genuinely
blocked, not merely unlucky in timing) —
`test_a4_concurrent_writer_cannot_land_between_verification_and_clearance_write`,
`test_a4_original_clearance_also_serializes_verification_and_write`
(`tests/test_package2_acceptance_review.py`).

**Disclosed limitation**: this closes the race for the clearance path
specifically. It does not retrofit `BEGIN IMMEDIATE` onto Original's
OTHER writers (`execute_buy` etc., still implicit DEFERRED
transactions) — a broader change than this review's bounded scope.

**Evidence references**: `docs/research/evidence/
package2_account_blocks/ACCEPTANCE_REVIEW.md` §A4.

**Related**: `OPS-012`, `OPS-015` (the clearance mechanism this race
was in).

---

## OPS-019 — Settlement trusted caller-supplied economics (found and closed same session)

**Status**: `CLOSED` — found and fixed within the Package 2 Acceptance
Review (2026-09-17); no window where this was OPEN in a released state.

**Found**: Package 2 Acceptance Review, re-examining Package 1/2's own
prior reasoning ("`close_position`'s caller-supplied shares/entry_
price/position_cost are safe because the corresponding DB columns are
write-once") against A5's explicit instruction that this reasoning was
insufficient evidence.

**Finding**: that reasoning was correct about today's SCHEMA but was
proof the caller's copy currently happens to agree with the
authoritative row, not proof settlement USES the authoritative row —
a materially weaker guarantee, fragile to any future code that
legitimately needs to touch those columns, a caller bug, or a stale
snapshot held by an overlapping reader.
`talonx_v2/paper.py::close_position()` computed realized P&L and
holding period from the caller-supplied `position` dict BEFORE ever
reading the database, and used the caller's `shares`/`position_cost`
for the cash credit and trade record.

**Fix**: `close_position()` now treats `position_id` as the ONLY
trusted input. Inside the same protected transaction as the close
itself, it re-reads `episode_id`/`symbol`/`entry_price`/`shares`/
`position_cost`/`entry_session` fresh from the live row and uses ONLY
those values for every subsequent computation and mutation. A
`position_id` that no longer exists returns a non-fabricating
`settled=False` outcome.

**Verification**: `tests/test_package2_acceptance_review.py` proves a
caller passing 100× the real share count and a wildly wrong entry
price still produces the economically CORRECT cash credit and P&L (the
authoritative row wins, not the caller's claim); a wrong symbol/
episode_id in the caller dict still produces the correct trade record;
a nonexistent `position_id` fabricates nothing. Package 1's own
existing 14-test suite (`test_package1_settlement_integrity.py`)
re-run unmodified against this rewrite: 14/14 still pass.

**Evidence references**: `docs/research/evidence/
package2_account_blocks/ACCEPTANCE_REVIEW.md` §A5.

**Related**: `S13-09` (Package 1's own settlement-integrity work, which
this closes a remaining gap in).

---

## OPS-020 — Default-mode price loader could parse a missing value as NaN (found and closed same session)

**Status**: `CLOSED` — found and fixed within Package 3 (2026-09-17);
no window where this was OPEN in a released state.

**Found**: Package 3 P3-B, direct inspection of `V2Service._bars()`
(the "csv"-mode bar loader — the DEFAULT, live-wired pricing path).

**Finding**: `float(getattr(r, "open", "nan"))` turned a genuinely
missing/blank CSV cell into an actual `NaN` float. `NaN` is TRUTHY in
Python (`not float("nan")` is `False`), so `pipeline.process_episode`'s
own `if not px or not px.get("open"):` missing-price check would have
silently passed a NaN price straight through — and `calculate_buy()`'s
own `if price <= 0: return None` guard does not catch NaN either
(`NaN <= 0` is `False`) — a genuine "missing price masquerades as a
legitimate fill" defect reachable in the default live pricing mode.

**Fix**: `_bars()` now validates each row's `open`/`close`
(`math.isfinite(x) and x > 0`) before including it; a malformed row is
excluded (never fabricated, never crashes the whole symbol's load).
`pricing.PricingResolver`'s own `validate_bar()` (the "composite-yf"/
"composite-iex" modes) already had this protection — only the default
"csv" mode's own separate, less-defensive loader was affected.

**Verification**: `tests/test_package3_pricing_timing.py`
(`test_p3b_missing_open_value_never_becomes_a_usable_price` and
siblings).

**Evidence references**: `docs/research/evidence/
package3_pricing_timing/README.md` §2.

---

## OPS-021 — Admission causality checked source timestamp only, never TalonX's own durable receipt (found and closed same session)

**Status**: `CLOSED` — found and fixed within Package 3 (2026-09-17);
no window where this was OPEN in a released state.

**Found**: Package 3 P3-E, direct inspection of
`V2Service._verify_temporal_boundary()` /
`_refresh_dissemination_lookup()`.

**Finding**: the admission-time look-ahead-bias check compared only
`InsiderTransaction.accepted_at_utc` (SEC EDGAR's own source/provider
acceptance timestamp) against the entry session's RTH open.
`InsiderFiling.ingested_at_utc` — TalonX's OWN durable receipt
timestamp, already captured by the separate, already-running
ingestion service — was never consulted at all. A filing SEC accepted
before RTH open but that TalonX itself did not durably ingest until
AFTER RTH open would have incorrectly passed, based purely on the
source's own timestamp — the "late receipt masquerading as timely
because the source timestamp was earlier" failure mode.

**Fix**: `_refresh_dissemination_lookup` now also populates
`self._receipt_lookup` (one `InsiderStore.get_filing()` lookup per
distinct accession, cached per refresh); `_verify_temporal_boundary`
additionally refuses when a KNOWN receipt timestamp is not strictly
before RTH open (soft no-op when no receipt timestamp is available at
all, so an unrelated caller/test is not spuriously broken). Both
timestamps are now also durably persisted onto the admission record
(`pending_entry_intents.source_event_ts_utc`/`receipt_ts_utc`, an
additive, non-destructive schema change) for later audit (P3-F).

**Verification**: `tests/test_package3_pricing_timing.py`
(`test_p3e_late_receipt_is_refused_even_with_an_earlier_source_timestamp`
and siblings); full 252-test V2 regression confirms the soft-no-op
design does not regress any existing caller.

**Evidence references**: `docs/research/evidence/
package3_pricing_timing/README.md` §5.

**Related**: `OPS-003` (the deadline/timing finding this session
otherwise closed Finding B of).

---

## OPS-022 — Exit P&L re-derived cost basis, never read the authoritative persisted entry total (found and closed same session)

**Status**: `CLOSED` — found and fixed within Package 4 (2026-09-17);
dormant (invisible under the zero-fee assumption then in force), never
observed live (V2's campaign has had 0 trades to date).

**Found**: Package 4 P4-A/P4-E, direct inspection of
`talonx_paper.engine.calculate_sell_pnl()` and its call site in
`talonx_v2/paper.py::close_position()`, while tracing the full
capital-flow map before any code change.

**Finding**: `calculate_sell_pnl(shares, entry_price, exit_price)`
computed `cost_basis = shares * entry_price` internally, rather than
using the persisted, authoritative `positions.position_cost`
(entry_total) that Package 2 acceptance's own A5 principle already
established as the correct source for every OTHER settlement value.
Numerically invisible under the zero-fee assumption in force since
this codebase's inception (`position_cost == shares*entry_price` when
no fee is ever applied) — but wrong in general: the instant any
non-zero entry fee is configured, this formula would have silently
omitted it from realized P&L, overstating gains by exactly the entry
fee amount.

**Fix**: `talonx_v2/sizing.py::compute_exit_economics()` computes
`realized_pnl = (shares*exit_price - exit_fee) - entry_total`, where
`entry_total` is the caller-supplied, authoritative persisted
`position_cost` — wired into `close_position()` in the same pass that
introduced fee-inclusive sizing (`OPS-014`). `talonx_paper.engine.
calculate_sell_pnl` itself is unmodified; Original's own P&L
accounting is unaffected (out of scope).

**Verification**: `tests/test_package4_sizing_accounting.py`
(`test_p4e_exit_pnl_uses_authoritative_entry_total_not_notional_alone`,
`test_p4e_round_trip_cash_reconciles_with_fees`).

**Evidence references**: `docs/research/evidence/
package4_sizing_accounting/README.md` §2, §6.

**Related**: `OPS-014` (found in the same pass, same underlying
capital-flow trace).

---

## OPS-023 — V2 release fingerprint was not line-ending-normalized (found and closed same session, RI-1)

**Status**: FOUND AND FIXED (V2 Release Integration Task RI-1).

**Finding**: `research/scripts/task112_v2_release_fingerprint.py`'s
`v2_release_fingerprint()` hashed each of its 5 `_STRATEGY_FILES`' raw
bytes directly (`digest.update(p.read_bytes())`), with no line-ending
normalization — the EXACT class of defect Task 137 already found and
fixed for `V1_FINGERPRINT_EXPECTED`/`get_strategy_version()`
(`talonx_backtest/reproducibility.py`), but the fix was never mirrored
onto V2's own fingerprint function. Confirmed directly during RI-1 (not
hypothesized): a plain `git stash` / `git stash pop` roundtrip on this
working tree — zero real content change — shifted the computed V2
fingerprint THREE different ways across three re-computations, purely
from CRLF/LF representation churn. The historically recorded
`V2_FINGERPRINT_EXPECTED = "11107198c5b81237"` was itself unreproducible
from a clean checkout of `c752af0` in this environment before this fix.

**Fix**: `v2_release_fingerprint()` now hashes
`p.read_bytes().replace(b"\r\n", b"\n")` for every strategy file — the
identical technique already used by `get_strategy_version()` and by
`tests/test_task65b_protected_fingerprints.py`'s other two frozen-
candidate fingerprints. A genuine content change is still fully
detected; only the line-ending REPRESENTATION stops being significant.

**Separately, and NOT to be confused with this fix**: `V2_FINGERPRINT_
EXPECTED` was ALSO updated (`"11107198c5b81237"` → `"e2acf6454789217e"`)
for an unrelated, deliberate, disclosed reason — RI-1 added `campaign_id`/
`execution_mode` fields to `talonx_v2/config.py` (one of the 5
fingerprinted files), changing its bytes. Every individually-hashed
STRATEGY value (`cluster_window_trading_days`, `min_distinct_owners`,
`transaction_code`, `direction`, `entry_offset_sessions`,
`hold_trading_days`, `stop_loss_enabled`, `max_concurrent_positions`,
`reentry_cooldown_trading_days`, `liquidity_lookback_sessions`,
`liquidity_min_median_dollar_volume`, `liquidity_min_close`,
`exit_fallforward_max_sessions`, `max_entry_staleness_sessions`) was
directly re-verified byte-for-byte unchanged before and after.

**Verification**: `research/scripts/task112_v2_release_fingerprint.py`
re-run after a deliberate stash/pop roundtrip, confirmed stable at
`e2acf6454789217e` both times. `tests/test_task114_prospective.py`
(`test_b1_preflight_fingerprints_are_expected`,
`test_task114_does_not_change_fingerprints`), `tests/
test_task117_deployment_rehearsal.py`, `tests/test_task117_overnight_e2e.py`,
`tests/test_task117_phase0_source_readiness.py`, `tests/
test_task117_spa_states.py` — all updated to assert against the live
`V2_FINGERPRINT_EXPECTED` constant rather than a duplicated hardcoded
literal (several already had this exact stale-duplicate defect,
independent of RI-1's own change).

**Evidence references**: `docs/research/evidence/
v2_release_integration_ri1/README.md`.

**Related**: mirrors Task 137's `V1_FINGERPRINT_EXPECTED` fix exactly;
not itself a strategy-semantics change.

---

## OPS-024 — Campaign starting-cash had two disconnected sources of truth (found and closed same session, RI-1)

**Status**: FOUND AND FIXED (V2 Release Integration Task RI-1).

**Finding**: `talonx_v2.config.V2Config.starting_cash_usd` (env
`TALONX_V2_STARTING_CASH_USD`, default $100,000 — the actual mechanism
that seeds `V2Store`'s `portfolio.cash` row exactly once at first
creation) and `talonx_ops.prospective.CAMPAIGN_STARTING_CASH` (a
separate hardcoded module constant, $300,000 — used by `close.py`'s
`_v2_reconcile()` and `ledger_guard.py`'s `check_ledger_continuity()` to
compute "expected cash if flat") were two INDEPENDENT numbers for what
should be the same concept. They happened to agree for the one existing
production campaign only because an operator manually set both the env
var and the constant to $300,000 at Task 112/113's own deployment. A
second campaign created with the new $100,000 default would have
produced a false `LEDGER_MISMATCH` (or masked a real one) in every
reconciliation, since the constant would still say $300,000.

**Fix**: `talonx_v2/store.py` gained a new `campaign` table (RI1-B) —
an immutable-after-creation identity + capitalization record, seeded
exactly once (`SEEDED_AT_CREATION` for a genuinely fresh ledger,
`LEGACY_MIGRATED` with `starting_cash_usd=NULL` — never fabricated —
for a ledger file that predates RI-1). New shared resolver
`talonx_ops/prospective/campaign_cash.py::authoritative_starting_cash()`
prefers this persisted, campaign-specific value; falls back to the
pre-RI-1 `CAMPAIGN_STARTING_CASH` constant ONLY when the campaign row is
absent or its `starting_cash_usd` is still NULL — preserving the
EXISTING production campaign's reconciliation behavior byte-for-byte
without requiring any migration.

**Verification**: `tests/test_ri1_campaign_identity.py` (RI1-C, RI1-K
sections). `tests/test_package1_settlement_integrity.py`, `tests/
test_package2_account_blocks.py`, `tests/test_package4_sizing_accounting.py`
re-run clean after their own `CAMPAIGN_STARTING_CASH` monkeypatches were
retargeted to the new resolver module (one test —
`test_clear_block_ledger_mismatch_refuses_while_reconcile_still_fails`
— redesigned to inject a genuine ledger-data mismatch directly, since a
wrong `CAMPAIGN_STARTING_CASH` patch is no longer sufficient to fool a
reconciliation that now correctly reads the real persisted amount
first).

**Evidence references**: `docs/research/evidence/
v2_release_integration_ri1/README.md`.

**Related**: `S13-08` (material-version cutover rules), Package 4
(`OPS-014`, sizing/allocation mechanics this campaign record also
carries for audit).

---

## OPS-025 — Historical Intelligence-outbox drain gap re-traced: already fixed, not re-open (RI-2)

**Status**: CONFIRMED FIXED (by a prior task, re-verified by RI-2 — no new code change).

**Historical finding** (`docs/audits/task117_output_closure/README.md`
D5, 2026-09 era): the `intelligence_delivery` outbox accumulated 9,843
rows, 100% `PENDING`, 0 ever `SENT` — a missing runtime-wiring
integration, not a strictness/threshold issue. At the time, "implementation
deferred" pending a product decision.

**RI-2's re-trace** (V2 Release Integration Task RI-2, direct code
read, not doc trust): `talonx_ops/prospective/proc.py:241-264`
(Task 140, building on Task 132's own investigation) already closes
this — whenever `prospective start --deliver --transport telegram` is
invoked, the SAME flags now also propagate `TALONX_INTEL_DELIVER_
CARDS=1`/`TALONX_INTEL_DRY_RUN_DELIVERY=0` into the supervisor
subprocess's environment, which inherits to the Intelligence child
process (`talonx_ops/supervisor.py`'s `default_talonx_components()`
unconditionally spawns `python -m talonx_ingest.intelligence.service
poll --with-backfill` as a supervised component). Previously only V2's
own companion argv received the delivery-enablement flags; Intelligence
silently stayed in permanent dry-run regardless of operator intent —
this is the exact defect D5 described, already fixed.

**Not re-tested end-to-end by RI-2**: Intelligence's own delivery
pipeline internals (backlog/expiry safety, restart behavior) were
traced for WIRING only — its own prior test coverage (referenced in
`docs/audits/task117_delivery_timestamp_completion/`) is relied upon,
consistent with RI-2's own scope boundary against broadly refactoring
or re-verifying unrelated messaging subsystems.

**Evidence references**: `docs/research/evidence/
v2_release_integration_ri2/README.md` §3.

**Related**: this is a DIFFERENT outbox/pipeline than V2's own
`v2_alert_outbox` (`OPS-023`/`OPS-024`, RI-1) — the two were
historically conflated in casual discussion but are architecturally
separate, confirmed via direct code trace.

---

*See `REQUIREMENTS_TRACKER.md` for product-requirement tracking,
`DECISION_LOG.md` for the session-by-session product-owner record, and
`docs/research/TALONX_RESEARCH_LEDGER.md` for the research/validation
task history. This file tracks operational/runtime findings only.*


## OPS-026 — V2 dashboard presentation understated capital and obligations (found and closed in RI-3)

**Status:** CLOSED for the RI-3 operator surfaces (2026-09-18).

`talonx_ops/dashboard_read.py` displayed a hardcoded $300,000 seed for every
campaign, equated settled cash with available cash despite PENDING reservations,
and excluded EXIT_UNRESOLVED cost/slots from allocated capital and capacity.
`talonx_ops/paper_performance.py` independently repeated the fixed seed.
These were presentation errors, not trading-ledger or settlement defects.
The RI-3 read-only projection now uses the RI-1 campaign row, Package-4
persisted economics and accepted reservation/obligation semantics. Unknown
legacy seed remains unknown. Tests and full operator fixture:
`docs/research/evidence/v2_release_integration_ri3/README.md`.
