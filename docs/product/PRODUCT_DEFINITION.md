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

## 7. Open / proposed — see `REQUIREMENTS_TRACKER.md` for tracked status

- **Intraday-vs-multi-day scope** ("swing intelligence assistant"): does
  TalonX retain Original's intraday lane, focus on V2's multi-day
  opportunities, or support both as a stated product identity (as
  opposed to today's de facto "both exist, historically accumulated"
  state)? **Not decided.** (S1-09)
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
