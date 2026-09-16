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
  `Implemented`, directly matching existing frozen code
  (`talonx_v2/config.py:72`, `talonx_v2/calendar.py:88`). Exact
  equality-at-deadline/receive-vs-commit semantics remain an explicit
  open implementation-acceptance detail (`S5-19`). A previously-
  inspected deadline-consistency finding (Task 112R's G1 entry-session
  comparison) is recorded for future re-verification, not corrected —
  `OPERATIONAL_FINDINGS.md` `OPS-003`.
- **Corporate actions/fractional shares**: entirely future policy — no
  such code exists today (confirmed by targeted search) —
  `OPERATIONAL_FINDINGS.md` `OPS-004`.
- **Catch-up/priorities/historical data**: durable checkpoints already
  exist for Intelligence (Task 96B); no fixed 16-hour completeness
  assumption was found to remove; a pre-market lockout window remains
  explicitly undefined (`S5-30`); 2-year replay feasibility remains
  open across five distinct sub-questions (`S5-31`, extends `S3-27`).

`OPS-002` **remains open**, unaffected by Session 4 or 5.

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
