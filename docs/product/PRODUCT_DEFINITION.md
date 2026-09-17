# TalonX Product Definition

**Status**: v0.1 — created 2026-09-15 from Knowledge-Transfer Session 1.
This is the **product-experience layer** (what the user sees and why it
exists). It does not replace, duplicate, or override:

- `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md` — the STRATEGY-TUNING
  specification for Original's intraday signal logic (confluence, ATR
  semantics, signal-family independence), confirmed by the owner in
  Task 33 (2026-08-21). That document governs *how Original decides to
  enter/exit a trade*; this document governs *what the product is, who
  it's for, and how it communicates*.
- `docs/RESEARCH_STATUS.md` / `docs/research/TALONX_RESEARCH_LEDGER.md`
  — the alpha-research history and conclusions (why V2's
  `INSIDER_BUY_CLUSTER_V2@1` strategy exists, why free-tier intraday
  price/volume alpha research is closed).

Where those documents describe *why the strategies work the way they
do*, this one describes *why the product exists, who it's for, and what
"good" looks like from a user's chair* — the layer the product owner
knowledge-transfer sessions (`KNOWLEDGE_TRANSFER_PLAN.md`) are building.

**Every claim below is marked** `IMPLEMENTED` (working today, cite
evidence), `PROPOSED` (discussed, not yet agreed as a requirement), or
`AGREED — IMPLEMENTATION STATUS SEPARATE` (the product owner has agreed
this is the intended direction; whether the current system already
delivers it is a **separate**, explicitly-stated question — see
`REQUIREMENTS_TRACKER.md` for the authoritative per-requirement status).
**Repository HEAD and running-component versions are separate
concepts** — a claim about `IMPLEMENTED` code being present in this
repository is not a claim about what is currently running live, and vice
versa; where this document says "running", it means confirmed against a
live production process at documentation time, not merely present in
the repository.

---

## 1. Primary goal — `AGREED` (Session 1, S1-01/S1-02)

> Help the user discover and understand selected stock-trading
> opportunities without continuously monitoring markets, using concise,
> evidence-backed alerts and paper tracking to evaluate the results.

This is the product owner's own framing, recorded verbatim from Session
1 (`DECISION_LOG.md`, S1-01). It supersedes no prior confirmed
requirement — it is the first time the FULL product (not just Original's
strategy) has been framed as a single goal statement in this
documentation layer.

## 2. Core experience — three surfaces, three jobs

| Surface | Job | Status |
|---|---|---|
| **Telegram — trading opportunities** | The user's primary channel for things that might warrant a decision: V2 multi-day paper BUY/SELL notifications, and Intelligence's optional major-development alerts. | `AGREED` direction (S1-01); V2 paper-trade Telegram delivery `IMPLEMENTED` (Task 110-117); Intelligence `IMMEDIATE` alerts `IMPLEMENTED` (Task 96F, hardened through Task 140c) — see `REQUIREMENTS_TRACKER.md` S1-01/S1-02 for evidence. |
| **Dashboard (`:8787`) — everything else** | General corporate monitoring, raw filings, the full audit trail, operational health. Not the primary discovery surface — the reference surface. | `AGREED` direction (S1-03); dashboard's Intelligence tab + routine-digest-OFF-by-default `IMPLEMENTED` (Task 140, commit `55dd31c`). |
| **Paper tracking** | Evaluate results without risking real capital — both Original's intraday paper ledger and V2's $300,000 multi-day paper campaign. | `IMPLEMENTED` (established across the project's history; V2 campaign ledger, reservation lifecycle, EOD reconciliation all exist and were exercised this session — Task 140's reservation-expiry-exactly-once work). |

## 3. Notification philosophy — `AGREED` (Session 1, S1-02/S1-05)

- Major-development notifications are **optional** informational
  alerts, distinct from trade-actionable alerts (V2 BUY/SELL).
- A major-development message must explain **what happened and why it
  matters in plain language, without unexplained SEC jargon**.
  **Partial implementation** — the concise-alert content-gate work this
  session (Task 138 Workstream 2 through Task 140c) already enforces
  "a specific supported development, not a bare category label" and
  removed several category-only-bypass defects; it does **not** yet
  remove raw SEC citation syntax from the message itself (e.g. a real
  header line still reads *"Direct financial obligation (8-K Item
  2.03/2.04)"* — the item-number jargon is present). See
  `REQUIREMENTS_TRACKER.md` S1-05 for the precise gap.
- "High conviction" is a **desired quality**, not a claim of
  profitability and not authorization to invent a numeric confidence
  score. No confidence-score feature exists in the product today
  (nothing to violate this guardrail with); the system's existing
  claim-safety enforcement (`assert_clean`/`PredictiveLanguageError`,
  rejects predictive/price-target language before any send) is
  consistent with this constraint.

## 4. Operating preference — `AGREED` (Session 1, S1-04), implementation `NOT ASSESSED AS BUILT`

- Typical operating window: **08:00–22:00 UK local time.**
- This is stated explicitly as **a preference**, not a claim that an
  automatic start/stop scheduler tied to this window exists.
- **Verified by code inspection**: no automatic UK-hours-based
  start/stop scheduler was found. The closest existing mechanism,
  `talonx_ops.prospective` (`python -m talonx_ops.prospective
  {start|close|status|checkpoint}`), is a **manually operator-invoked**
  morning-start/evening-close command pair; it displays Europe/London
  local time alongside UTC in its own logs (`talonx_ops/prospective/
  paths.py`) but does not itself gate *when* it may run. The system
  otherwise runs continuously once started (supervisor-managed,
  always-on).
- Opportunities and major events **may be detected** during this
  window — detection time does **not** automatically establish
  actionability (a detected-but-stale opportunity must still be
  labelled honestly, see §5).

## 5. Presentation — `AGREED` (Session 1, S1-05/S1-06/S1-07/S1-08)

- Trade alerts begin with a one-sentence plain-English explanation of
  the supporting evidence.
- Examples and generated copy must not call people "executives" or
  describe a purchase as using "personal funds" unless the underlying
  source data actually supports those specific descriptions (insider
  role/ownership-nature fields, not inferred). **Code-inspection
  evidence (not exhaustive)**: the real insider-transaction renderer
  paths inspected this session cite the source's own role field
  verbatim (e.g. "CEO reported open-market N sale(s)") and no instance
  of "executive" or "personal funds" wording was found — consistent
  with this guardrail, not yet exhaustively verified across every
  render path.
- **Clear opportunity status is required** to prevent chasing expired
  entries. V2's internal state machine already distinguishes terminal
  states including `SKIPPED_ENTRY_STALE` (Task 113's P1 fix, this
  project's history); whether that internal state is communicated to
  the operator via the Telegram alert itself, as opposed to only the
  dashboard/internal log, is `NOT ASSESSED IN THIS DOCUMENTATION PASS`
  — see `REQUIREMENTS_TRACKER.md` S1-06.
- **Standardized paper sizing is desired; $10,000 per allocation is
  proposed; cross-lane scope is not finalized.** **Verified by code
  inspection**: V2's own default (`talonx_v2/config.py`,
  `per_position_allocation_usd`, env `TALONX_V2_ALLOCATION_USD`) is
  **already `$10,000`**. Original's own default (`talonx_paper/
  config.py`, `default_trade_allocation_usd`, env
  `TALONX_PAPER_TRADE_ALLOCATION`) is **`$2,500`** — a different value.
  The two lanes are NOT currently unified; a $10,000 standard across
  both lanes would be a change for Original, not merely a
  documentation of existing behavior.
- Allocation size must not be described as maximum possible loss (a
  wording/claim-safety constraint for future copy, not yet a concrete
  feature to verify against).
- Existing reply-for-details remains useful — `IMPLEMENTED`,
  extensively hardened this session (Task 138 Workstream 3 through
  Task 140's reply-details ordering/pagination/source-link corrections).
- New interactive Telegram buttons are **deferred, low priority** — not
  authorized for implementation. No interactive-button feature exists
  today (consistent with this being a deferred, not a regressed,
  capability).

## 6. Boundaries — `IMPLEMENTED`, established project-wide

- Development and paper tracking only.
- Existing free-tier infrastructure; **no new paid data authorized**.
- **No real-capital execution authorized** — V2 and Original both remain
  structurally paper-only (`real_capital: BLOCKED` surfaced directly on
  the dashboard's Active V2 tab; no broker-order code path exists for
  V2 at all).

## 6a. Paper execution, accounting, risk and evaluation — `AGREED` (Session 2), implementation `PARTIALLY ASSESSED`

Recorded in full in `DECISION_LOG.md` Session 2 and tracked as `S2-01`
through `S2-15` in `REQUIREMENTS_TRACKER.md`. Summary only — see those
two documents for the authoritative detail:

- Alert-to-action mapping (BUY/SELL act, BULLISH/BEARISH inform only,
  no automatic shorting) — `Implemented` (V2), confirmed by code
  inspection this session.
- Capacity boundaries (visible skip records, no cash inflation,
  qualification vs. admission distinction) — `Partially implemented`;
  the skip mechanism exists under different naming than the suggested
  operator-facing wording.
- Live/replay parity and a desired-but-unverified 2-year replay window
  — `Partially implemented`, existing bounded research-grade replay
  infrastructure only (`talonx_research/`).
- EOD daily/realized/open-P&L separation, exit-follows-strategy-rules,
  unresolved-exit disclosure — `Implemented`.
- Dashboard presentation (equal-prominence equity/open-P&L,
  entry-equity-denominated contribution labelling, missing/stale
  valuation wording) — `Partially implemented`; the underlying data
  fields and a never-zero/flagged-incomplete equity mechanism exist,
  but the requirement's specific labels and layout do not yet.
- Exit-rule and stop-loss disclosure to the operator (the V2-specific
  "10th trading session, no stop-loss" wording) — the rule is real and
  frozen in code; **no operator-facing disclosure surface was found**
  this session.
- Experimental isolation (separate versioned experiments, isolated
  accounts, no stop-loss-necessarily-helps claim) — `Implemented`,
  matches this project's existing `talonx_research/` governance.

**This session's discussion of both intraday and multi-day accounting
does not resolve §7's open intraday-vs-multi-day scope question below,
and its accounting examples do not finalize the $10,000 cross-lane
allocation figure** — both remain exactly as open as before this
session; see `DECISION_LOG.md` Session 2's own "Open questions" for the
explicit statement.

A specific operational (not product-requirement) finding from this same
period — V2's current-price freshness telemetry being structurally
incomplete in its running `"csv"` pricing mode — is tracked separately
in `OPERATIONAL_FINDINGS.md` (`OPS-002`), since it is a runtime data
gap, not a product decision.

## 6b. Application structure, coverage, capital and research workflow — `AGREED` (Session 3), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 3 and tracked as `S3-01`
through `S3-28` in `REQUIREMENTS_TRACKER.md` (`S3-24`-`S3-28` are
explicit deferrals, not decisions). Summary only:

- **Scope resolved**: TalonX offers both intraday and multi-day
  opportunities through one main feed with prominent horizon/strategy
  labels — this **resolves §7's former `S1-09` open item** below (kept
  visible here with its resolution noted, not deleted). Original is
  explicitly not retired; V2 is one multi-day strategy, not the
  category name.
- **Target architecture**: independently testable strategies sharing
  contracts (not immediate consolidation); positions identified by
  account+strategy+opportunity, not ticker alone — `Partially
  implemented` (today's separation is achieved by using entirely
  separate databases per lane, not a shared composite-key store).
- **Master stock coverage model** (one list: discovery + manual +
  exclusions, per-horizon overrides, Pause/Exclude/Mute as distinct
  concepts) — `Not implemented`; three separate, unmerged lists exist
  today (Original's watchlist, V2's execution scope, Intelligence's
  collection scope). Original's own ticker store already has a working
  Pause mechanism (`talonx_watchlist/store.py`), a real partial match.
- **New-campaign capital defaults**: $100,000 starting cash per
  strategy account, $10,000 per-position allocation — `Not
  implemented` as a stated default; existing campaigns (V2's $300,000,
  Original's $10,000/$15,000) are explicitly **not** overwritten by
  this decision.
- **Research lab workflow** (replay → live shadow → review → explicit
  promotion, with dashboard visibility and an optional internal
  research Telegram bot) — `Partially implemented`; the historical-
  replay stage and immutable strategy-versioning already exist
  (`talonx_research/`, Task 115/116); the live-shadow stage, the
  dedicated "EXPERIMENTAL — INTERNAL ONLY" dashboard, and the research
  bot do not.
- **Conditional database-reset permission**: a future, separately
  authorized implementation task may perform a reset if necessary for
  compatibility/trustworthy accounting, following a defined 9-step
  approach — this updates, but does not exercise, the project's
  earlier absolute-preservation instruction from the EOD closure task.

`OPS-002` (V2 pricing-freshness gap, `OPERATIONAL_FINDINGS.md`)
**remains open** — none of Session 3's product decisions touch it.

## 6c. End-to-end user journey — `AGREED` (Session 4), implementation `MOSTLY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 4, tracked as `S4-01`
through `S4-14` in `REQUIREMENTS_TRACKER.md`. Summary:

- One "Start monitoring" action, per-strategy readiness gating, and
  ordered obligation-recovery-before-discovery — `Partially
  implemented`/`Not assessed`; a single start command already exists,
  but per-strategy readiness gating and cross-system recovery
  ordering were not found or traced this session.
- Campaign preservation across restart — `Implemented`, directly
  evidenced by the 2026-09-15 EOD closure.
- A three-bot model (Primary opportunities/lifecycle, separate
  Operations incidents, optional isolated Research) — `Not
  implemented` beyond the single existing bot; **no Operations or
  Research bot exists**, and none is authorized by this documentation.
- Paper execution independent of notification success — `Implemented`,
  confirmed by code inspection (execution and delivery are
  architecturally separate paths).
- Explicit lifecycle states with a separate missing-price/valuation
  axis — `Partially implemented`; V2 already has distinct internal
  dispositions for this, not yet operator-facing.
- Atomic intent-cancellation on pause — `Not implemented`.
- EOD daily performance/open risk/unresolved obligations —
  `Implemented` (extends `S2-07`).
- Outage detection and alert deduplication — `Partially implemented`;
  a real single-owner Telegram-poller dedup exists, a broader outage-
  detection capability was not confirmed.

## 6d. Data sources, discovery and coverage — `AGREED` (Session 5), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 5, tracked as `S5-01`
through `S5-31` in `REQUIREMENTS_TRACKER.md` (`S5-10`, `S5-19`,
`S5-20`, `S5-30`, `S5-31` are open/deferred, not decisions). **This
session is closed at the requirements level only — it does not
establish execution readiness or universal validation of any of the
five areas below.** Summary:

- **Master registry/identity**: one master security registry with
  per-strategy/horizon eligibility, CIK-vs-security-identity
  distinction — `Not implemented`; today's three separate scopes
  (Original 43/48 active, Intelligence 569, V2 626 — each with dated
  evidence, see `OPERATIONAL_FINDINGS.md` `OPS-006`) remain unmerged.
  **A "27-unresolved/599-resolved" count pair referenced in this
  session's own prompt was checked for and not found anywhere in this
  repository — not adopted.**
- **Price reference/timestamps**: one primary provider per strategy
  version, official-auction-vs-daily-bar-open distinction, no
  unvalidated fallback — `Partially implemented`; provider selection
  itself remains explicitly `OPEN` (`S5-10`) — see
  `OPERATIONAL_FINDINGS.md` `OPS-005`.
- **Three-session recovery**: target-entry-session and exchange-
  calendar-close semantics for `max_entry_staleness_sessions=3` —
  **`Partially implemented — session-based recovery exists; exact
  Session-3-close enforcement and pre-fill expiry remain pending
  `OPS-003``** (corrected 2026-09-16; a session-based mechanism
  genuinely exists, but direct code inspection found two different
  deadline computations for the same parameter one session apart, and
  a fill is attempted before any deadline check rather than after —
  see `OPERATIONAL_FINDINGS.md` `OPS-003` Finding B). Restart-
  independence and exactly-once reservation release **are** correctly
  implemented and unaffected by this correction. Exact equality-at-
  deadline/receive-vs-commit semantics remain an explicit open
  implementation-acceptance detail (`S5-19`), not resolved by this
  correction. A previously-inspected cross-methodology
  deadline-consistency finding (Task 112R's G1 entry-session
  comparison) remains recorded for future re-verification, not
  corrected — `OPERATIONAL_FINDINGS.md` `OPS-003` Finding A.
- **Corporate actions/fractional shares**: entirely future policy — no
  such code exists today (confirmed by targeted search) —
  `OPERATIONAL_FINDINGS.md` `OPS-004`.
- **Catch-up/priorities/historical data**: durable checkpoints already
  exist for Intelligence (Task 96B); no fixed 16-hour completeness
  assumption was found to remove; a pre-market lockout window remains
  explicitly undefined (`S5-30`); 2-year replay feasibility remains
  open across five distinct sub-questions (`S5-31`, extends `S3-27`).

`OPS-002` **remains open**, unaffected by Session 4 or 5.

## 6e. Signal discovery and strategy mechanics — `AGREED` (Session 6), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 6, tracked as `S6-01`
through `S6-26` in `REQUIREMENTS_TRACKER.md` (`S6-18`, `S6-25`,
`S6-26` are open/deferred, not decisions). **Discussion closed;
documented requirements, with explicit deferrals and implementation
gates** — several areas record an inspected, accurate baseline
separately from an approved-but-unbuilt target; this session does not
claim execution readiness for any of them. Summary:

- **Strategy scope**: primary scope = Intraday Opportunities + V2,
  without implying execution-readiness; **Fundamental Opportunities is
  retained as an isolated Research Lab candidate**, resolving `S3-24`
  at the product-positioning level (its underlying technical role
  remains uninspected); both horizons remain primary — no demotion.
- **V2 qualification baseline** (code P, >=2 distinct owner CIKs,
  filing-date-driven <=10-session-step window, operational liquidity
  screen) — `Implemented`, matches this project's established frozen
  `INSIDER_BUY_CLUSTER_V2@1` contract. Whether the frozen contract's
  own broader wording matches the operational screen exactly was
  **not verified this session** — disclosed, not resolved
  (`OPERATIONAL_FINDINGS.md` `OPS-006`).
- **Intraday baseline** (RSI/MACD/MA/ATR/cooldown/lockout defaults) —
  `Implemented`, directly confirmed by reading `talonx_quant/config.py`
  this session; the RSI-recovery/confirmation self-exclusion is
  confirmed **intentional**, established design (Task 28), not a bug.
- **Alerts independent of paper capacity** and **Delayed Market
  Simulation** (a new, separately labelled evaluation mode) — both
  `Not implemented`.
- **Entry geometry/next-bar execution**: the **inspected baseline is
  genuinely sound** — `QuantScanner._revalidate_candidate()` and
  `fill_geometry_is_valid()` both confirmed by direct code reading this
  session, explicitly refuting any "no revalidation exists" claim. The
  **approved target** (freeze-on-approval, next-eligible-bar-open
  entry, post-spread RRR recheck, T-10 cutoff) is `Not implemented` —
  `OPERATIONAL_FINDINGS.md` `OPS-008`.
- **Exit precedence/ambiguity**: `Not implemented` — a repository-wide
  search found no matching status codes (`AMBIGUOUS_INTRABAR_ORDER`,
  `EXIT_UNRESOLVED`, `EXIT_PENDING`) anywhere in `talonx_paper/` —
  `OPERATIONAL_FINDINGS.md` `OPS-009`.
- **Intraday EOD-flatten**: the **inspected baseline** (15:50 ET
  default, DST-aware but not exchange-calendar-aware, no price-age
  check, no durable recovery state) is confirmed accurate by direct
  code reading. The **approved target** (close-minus-10-minutes
  cutoff, durable cross-restart recovery, per-account entry block,
  `EXIT_UNRESOLVED` terminal state) is `Not implemented` —
  `OPERATIONAL_FINDINGS.md` `OPS-007`. **These intraday recovery rules
  do not apply to V2 or the Research-Lab-only fundamentals account.**
- **Deadline equality/audit history**: resolves `S5-19` **at the
  requirements level only** — implementation/validation against V2's
  actual code remain tracked under `OPS-003`, unresolved.

`OPS-002` and `OPS-003` **remain open**, re-confirmed unaffected by
this session's own targeted code reads.

## 6f. Intelligence and useful company developments — `AGREED` (Session 7), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 7, tracked as `S7-01`
through `S7-26` in `REQUIREMENTS_TRACKER.md` (`S7-18`, `S7-25`,
`S7-26` are open/deferred, not decisions). **Discussion closed; agreed
requirements documented, with numerical policy choices deferred and
implementation/validation separately tracked.** Summary:

- **Purpose/routing**: primary Telegram = trading opportunities +
  opted-in major developments, informational only — `Implemented`
  (reaffirms `S1-01`/`S1-02`). Operations/Research routing remains
  separate but unbuilt (`S7-02`).
- **Six-question qualification rubric** and the **versioned
  materiality-rules catalogue** (Routes 1/2) — both `Not implemented`.
  The existing significance engine (`information-significance-v1`) and
  content gate are **related but distinct**, narrower mechanisms — a
  `HIGH`/`CRITICAL` band does not by itself satisfy either the rubric
  or a materiality route (`OPERATIONAL_FINDINGS.md` `OPS-011`).
- **Development-centric grouping and `UPDATE`/`CORRECTION`
  linkage**: a real, working `UPDATE`/`SUPPRESS_DUPLICATE`/
  `SUPPRESS_NOOP` decision mechanism exists (`update_policy.py`), but
  operates per single event — no multi-filing "development record"
  grouping and no `CORRECTION` type distinct from `UPDATE` exist
  (`OPERATIONAL_FINDINGS.md` `OPS-010`).
- **Timestamps/freshness**: the established `freshness_status: UNKNOWN`
  gap (100% of persisted events, Task 140 evidence) remains
  unaddressed; numerical freshness windows are explicitly deferred
  (`S7-18`/`S7-25`), not invented.
- **User controls/corrections**: no per-stock company-event mute
  exists (a CSS class name was the only "mute" match found); trading
  pause not auto-pausing company monitoring is **true today**, as a
  structural side effect of Original's and Intelligence's separate
  systems, not a deliberately designed control.
- **Coverage/dashboard visibility**: the five-dimension distinction is
  agreed but not yet surfaced as a unified view.

This session performed a self-correction of a prior session's finding:
Session 6's OPS-009 (exit-precedence gap) is **narrowed**, not
reversed — direct control-flow reading found `talonx_paper/engine.py`'s
`check_stop_take()` already applies a stop-first tiebreak, and exit
fills already go through a spread-adjusted friction model
(`apply_spread`) — the earlier "no matches for these status strings"
finding was accurate as a string search but had been read too broadly;
`S6-19`/`S6-20` are corrected to `Partially implemented`.

`OPS-002` and `OPS-003` **remain open**, unaffected by this session.

## 6g. V2 multi-day strategy and lifecycle — `AGREED` (Session 8), implementation `MOSTLY BUILT AND VERIFIED`

Recorded in full in `DECISION_LOG.md` Session 8, tracked as `S8-01`
through `S8-18` in `REQUIREMENTS_TRACKER.md`, plus deferrals `S8-25`/
`S8-26`. **Discussion closed; requirements documented, with provider-
finality and cooldown-boundary verification outstanding, and
implementation separately tracked.** Unlike several earlier sessions,
much of this session's own subject matter is **already correctly
implemented** — directly confirmed by code inspection and by running
two pre-existing, isolated test files (23 tests, all passed) this
session:

- **Pre-open admission deadline** (`S8-01`) — `Implemented`, a real,
  fail-closed temporal-boundary check.
- **Holding clock** (Session 0 entry, 10th-session close exit, no
  stop-loss) — `Implemented`, frozen with runtime asserts.
- **Fall-forward exit contract** (target → earliest-of-next-5 →
  `EXIT_UNRESOLVED`, never best-price) — `Implemented`, directly
  tested this session.
- **Re-entry cooldown** — `Implemented`; the anchor (actual modeled
  exit session, including fall-forward) and the exact boundary (first
  eligible re-entry = `exit_session + 5` sessions, inclusive) were
  **both directly resolved by code inspection**, not left uncertain.
- **`CLOSED` exactly-once settlement** — `Implemented`, atomic
  transaction confirmed and tested.
- **Genuine gap found**: `EXIT_UNRESOLVED`'s agreed account-wide
  new-entry block is **not implemented** — the status exists and is
  correctly surfaced, but nothing in `open_position()`'s admission
  gate consults it (`OPERATIONAL_FINDINGS.md` `OPS-012`).
- **Still deferred**: the provider-finality boundary for target-
  closing-data availability (`S8-25`) and dedicated holiday/early-
  close boundary test coverage (`S8-26`) — neither invented nor
  resolved this session.

This session also confirmed, by direct code reading, that Session 6's
`OPS-009` finding was correctly scoped to Original's intraday engine
all along and does not describe V2 — `EXIT_UNRESOLVED` genuinely
exists in V2's own codebase (`talonx_v2/store.py`), a separate system
from `talonx_paper/`; no correction to `OPS-009` was needed, only this
clarifying note to prevent conflating the two.

`OPS-003`, `OPS-004`, `OPS-005` **remain open** — this session adds
confirming/disconfirming evidence but resolves none of them.

## 6h. Telegram and dashboard experience — `AGREED` (Session 9), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 9, tracked as `S9-01`
through `S9-20` in `REQUIREMENTS_TRACKER.md`. **Discussion closed;
requirements documented, with explicit deferrals and implementation/
validation separately tracked.** Summary:

- **Destinations**: Primary Trade & Event, Operations, and Research
  bots — all three `Not implemented` beyond the underlying mechanisms
  each would draw from (`OPS-013`).
- **Message content and lifecycle transitions**: a full compact-
  message and four-transition-notification design agreed — `Not
  implemented` as its own formatting/policy layer (`OPS-013`).
- **Delivery safeguards**: obsolete-pending consolidation, no-blind-
  flush catch-up, and ambiguous-delivery handling — the last is
  `Implemented` (established `AMBIGUOUS` contract); the first two are
  `Not implemented`/`Partially implemented`.
- **Dashboard layout**: a concrete five-part top-to-bottom layout
  (Action Required → equal Equity/Open-P&L → opportunities/positions →
  Recent Activity → Details) resolves `S2-10`'s own long-open
  candidate-session pointer — `Not implemented`.
- **Controls**: "Pause Updates" (real, tested, dashboard-refresh-
  scoped) is explicitly distinguished from "Pause New Entries" (not
  implemented, `S4-12`) — a naming clarification that prevents
  conflating a real, shipped feature with an unbuilt one. Full
  browser-reload state restoration is explicitly **not** claimed —
  only the established auto-refresh fix is (Task 140 evidence,
  re-confirmed this session).

## 6i. Paper accounting, costs and risk — `AGREED` (Session 10), implementation `MIXED — SOME BUILT, TWO GENUINE GAPS FOUND`

Recorded in full in `DECISION_LOG.md` Session 10, tracked as `S10-01`
through `S10-21` in `REQUIREMENTS_TRACKER.md`, plus deferrals
`S10-22`-`S10-25`. **Discussion closed; requirements documented, with
explicit deferrals and implementation/validation separately tracked.**
Summary:

- **Reservation mechanics** (atomic reserve, exactly-once release, no
  equity impact) — `Implemented`, directly confirmed against V2's
  established reserve-then-execute pattern.
- **Whole-share, fee-aware sizing — genuine gap found**: today's actual
  sizing (`talonx_paper.engine.calculate_buy()`, reused by V2) is a
  **continuous, fractional** share count with **no fee parameter at
  all** — the agreed whole-share/fee-aware formula is entirely target
  design (`OPERATIONAL_FINDINGS.md` `OPS-014`).
- **Position limits**: V2's frozen twenty-position limit is confirmed
  unchanged and correctly independent of the new $100,000/$10,000
  capital defaults — `Implemented`.
- **Cash-only boundaries**: no-shorts/explicit-skip-on-insufficient-
  cash is established; truthful-deficit-recording-with-Operations-
  escalation was not found — `Partially implemented`.
- **Dividends/corporate actions**: entirely `Not implemented`
  (`OPS-004`, reaffirmed unchanged, with a new design-consistency
  dependency between dividend double-counting prevention and
  `S5-26`'s corporate-action price-adjustment basis).
- **Reconciliation — genuine gap found**: `talonx_ops/
  eod_reconciliation.py` genuinely detects ledger mismatches
  (`STATUS_MISMATCH`), but nothing connects that detection to blocking
  new admissions — the same structural pattern as `OPS-012`, tracked
  separately as `OPS-015` since the trigger differs.
- **Partial evidence on numeric precision**: `calculate_buy()`/
  `calculate_sell_pnl()` were directly confirmed to use plain `float`
  arithmetic, not `Decimal` — contradicting `S5-27`'s agreed high-
  precision policy for at least this one function; the full numeric
  surface was not audited.
- **Exposure display is explicitly approved** (same-stock across
  independent accounts, without merging performance); numerical
  cross-account concentration limits, correlation-based admission
  gates, and concentration-warning thresholds all remain **explicitly
  deferred** (`S10-23`-`S10-25`) — `S3-25`'s own long-open deferral is
  split accordingly, with its display half now `Agreed`.

`OPS-002`, `OPS-003`, `OPS-004`, `OPS-005`, `OPS-012` **remain open**,
unaffected by these two sessions.

## 6j. Operation, stop/start and recovery — `AGREED` (Session 11), implementation `LARGELY NOT BUILT`

Recorded in full in `DECISION_LOG.md` Session 11, tracked as `S11-01`
through `S11-19` in `REQUIREMENTS_TRACKER.md`. **Discussion closed;
requirements documented, with explicit deferrals and implementation/
validation separately tracked.** This session defines the account-
block **clearance policy** that `OPS-012` and `OPS-015` were both
waiting on (ledger mismatches, unexplained deficits, terminal
unresolved exits, and database identity mismatches all require
auditable resolution and explicit operator clearance; restart never
auto-clears a serious block) — **the policy is now agreed; the
enforcement mechanism, and the five-state account-readiness model it
would run inside, are not implemented** (`OPERATIONAL_FINDINGS.md`
`OPS-016`, new this session). Real, established mechanisms this
session builds on: `stop_stack()`/`run_close()` (bounded, ownership-
verified shutdown and reconciliation), the `AMBIGUOUS`-delivery
contract, and V2's own target-close-before-fall-forward ordering — all
`Implemented`. Genuinely new and unbuilt: the five account states, a
"Partially Ready" summary, an external outage watchdog, and
configuration-effective-dates (immediate vs. versioned activation).

## 6k. Research, tuning and promotion — `AGREED` (Session 12), implementation `MOSTLY NOT ASSESSED THIS SESSION`

Recorded in full in `DECISION_LOG.md` Session 12, tracked as `S12-01`
through `S12-22` in `REQUIREMENTS_TRACKER.md`, plus deferrals
`S12-23`/`S12-24`. **Discussion closed; requirements documented, with
explicit deferrals and implementation/validation separately tracked.**
This session lays a full governance layer — mandatory prior-research
review, experiment registration, isolation, evidence discipline
(untouched evaluation data), comparison methodology (Strategy View vs.
Account View, three-verdict taxonomy), cost treatment (apply-once,
rerun-chronologically, intraday-RRR-not-for-V2), shadow-testing rules,
and promotion/rollback authority — on top of `S3-15`-`S3-20`'s already-
agreed qualitative research-lab workflow. **Most of Session 12's own
requirements were explicitly marked `Not assessed in this
documentation pass`, rather than guessed** — this documentation task
reused the established `talonx_research/` record (Task 115/116) but
did not re-audit its full current code against these newly detailed
rules. Confirmed unchanged this session: the "EXPERIMENTAL — INTERNAL
ONLY" dashboard label remains absent (re-run search, `S6-19`'s finding
still holds); existing positions retain their original rules through
any future promotion (`Implemented`, reaffirms `S8-06`). Numerical
cost calibration (`S12-23`) and two-year data feasibility (`S12-24`)
remain explicitly deferred — the discussion's own example numbers are
labelled illustrations, not adopted.

`OPS-002`-`OPS-005`, `OPS-012`, `OPS-015`, `OPS-016` **remain open**,
unaffected by either session.

## 6l. Reconciliation and release planning — `AGREED` (Session 13), Package 1 `IMPLEMENTED`

Recorded in full in `DECISION_LOG.md` Session 13, tracked as `S13-01`
through `S13-09` in `REQUIREMENTS_TRACKER.md`. This is the **first
session in this documentation series with an authorized, implemented
code change** — Package 1 (Settlement Integrity & Unresolved
Obligations), `S13-09`.

- **Release scope agreed**: V2 (Insider Buying) is the first-release
  primary paper strategy, conditional on acceptance criteria not yet
  fully met; Intraday is Research-Lab-only for the first release
  (does not reopen `S3-01`'s long-term both-horizons decision); company
  developments stay dashboard-visible with primary-Telegram gating
  requiring both opt-in and Session 7's (still unbuilt) acceptance
  criteria.
- **Staging agreed**: `Stage 0` → `Package 1` → `Package 2` →
  `Package 3` → `Package 4` → `Package 5` → release integration.
  **Only Package 1 is authorized and built** — Packages 2-5 and
  release integration remain explicitly unauthorized.
- **Package 1, built and verified**: fixed a genuine duplicate-
  settlement defect (`talonx_v2/paper.py::close_position()` now checks
  whether its own conditional state transition actually occurred
  before crediting cash/appending a trade/setting cooldown) and a
  genuine unresolved-obligation-visibility defect (`EXIT_UNRESOLVED`
  positions now correctly retain their capacity slot and symbol
  ownership, and their cost basis is no longer silently omitted from
  V2's reconciliation/equity reporting). Both were reproduced failing
  against the unmodified baseline first (9/14 new tests failed), then
  fixed (14/14 pass). A scoped 32-file/406-test regression run found
  zero new failures; the V2 strategy fingerprint (`11107198c5b81237`)
  is directly confirmed unchanged.
- **Explicitly not done**: the account-wide admission block for
  `EXIT_UNRESOLVED`/reconciliation-mismatch (`OPS-012`/`OPS-015`'s own
  described gap) remains open — that is `Package 2`'s scope, not
  satisfied by Package 1's slot-retention fix.
- **New finding**: `OPS-017` — a stale hardcoded fingerprint constant
  in two unrelated pre-existing test files, confirmed pre-existing via
  baseline reproduction, not fixed here.
- **Material-version cutover rules recorded** (documentation only) —
  no cutover performed or scheduled.

## 7. Open / proposed — see `REQUIREMENTS_TRACKER.md` for tracked status

- **Intraday-vs-multi-day scope** ("swing intelligence assistant"):
  **Resolved in Session 3 (`S3-01`) — both horizons retained**, through
  one main feed with prominent labels. This item is kept here,
  historically, rather than deleted — see `REQUIREMENTS_TRACKER.md`
  `S1-09` for the dated resolution note. (S1-09)
- **Market-session labels vs. opportunity-status labels**: a proposal to
  stop implying "regular trading hours" automatically means "an
  opportunity is currently active" — these are two different concepts
  today conflated in places. **Proposed, not agreed.** (S1-11)
- Exact acceptance criteria for "qualified opportunity", "major
  development", and "high conviction" — deferred to a later session.
- Quiet-period, downtime/catch-up, and missed-opportunity behavior —
  not yet specified.
- No profitability promise and no target launch date were agreed in
  Session 1.

---

*See `DECISION_LOG.md` for the full verbatim record of how each
statement above was reached, `REQUIREMENTS_TRACKER.md` for the
authoritative per-requirement tracking table, and
`KNOWLEDGE_TRANSFER_PLAN.md` for the session schedule and workflow.*
