# TalonX Product Requirements Tracker

Stable-ID tracking for product-level requirements, session by session.
IDs never change once assigned; a requirement that is later superseded
gets a note and a pointer, never a silent edit (same discipline as
`DECISION_LOG.md`/`docs/research/TALONX_RESEARCH_LEDGER.md`).

**ID convention**: no existing repository convention covers
product-experience requirements (the existing `FREQ-001`/`CONF-001`/
`SIG-00N`/`ATR-*`/`COST-001` IDs in `docs/research/
TALONX_OWNER_DECISIONS.md` are a topic-prefixed convention scoped to
Original's strategy-tuning parameters — a different, narrower domain).
This tracker uses **session-prefixed IDs**: `S<session>-<sequence>`,
e.g. `S1-01` for the first requirement recorded in Session 1.

**Decision-status progression**: `Proposed` → `Agreed` →
`Implementation authorized` → `Implemented` → `Verified`. Decision
status and implementation status are tracked **separately** — a
requirement can be `Agreed` while its current implementation status is
`Implemented` (built before it was ever written down here) or
`Not implemented` (net-new) or `Not assessed in this documentation pass`
(status genuinely unexamined).

**Verified must name its evidence type**: `Code inspection` / `Isolated
test` / `Integrated or browser test` / `Natural live behavior` /
`Product-owner acceptance`. A requirement is never marked `Verified`
without naming which of these applies.

---

## Summary

| ID | Requirement (short) | Decision status | Impl. authorization | Current implementation | Validation |
|---|---|---|---|---|---|
| S1-01 | Trading opportunities first in Telegram | Agreed | Not authorized (pre-existing) | Implemented | Code inspection + natural live behavior (this session) |
| S1-02 | Optional major-development notifications | Agreed | Not authorized (pre-existing) | Implemented | Code inspection + natural live behavior (this session) |
| S1-03 | Routine filings/raw corporate data on dashboard only | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (this session) |
| S1-04 | Preferred UK 08:00–22:00 operating window | Agreed | Not authorized | Not implemented (no scheduler) | Code inspection |
| S1-05 | Plain-language, evidence-led, jargon-free trade/dev alerts | Agreed | Not authorized | Partially implemented | Code inspection (gap found: raw item-number jargon remains) |
| S1-06 | Clear actionability/expiry status, no chasing expired entries | Agreed | Not authorized | Partially implemented | Code inspection; Telegram-facing surfacing not assessed |
| S1-07 | Standardized paper sizing; $10,000 proposed | Proposed (amount) / Agreed (need for standard) | Not authorized | Partially implemented (V2 only) | Code inspection |
| S1-08 | Interactive Telegram buttons deferred | Agreed (to defer) | Explicitly not authorized | Not implemented | Code inspection |
| S1-09 | Intraday vs. multi-day product-identity scope | **Open — not decided** | N/A | N/A | N/A |
| S1-10 | Free-tier data / paper-only, no real capital | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (established project-wide) |
| S1-11 | Separate market-session label from opportunity-status label | Proposed | Not authorized | Not implemented | Not assessed in this documentation pass |
| S1-12 | "High conviction" = desired quality, not profitability/confidence-score claim | Agreed | Not authorized | Implemented (no conflicting feature exists) | Code inspection |
| S1-13 | Example/alert wording accuracy guardrail (roles, fund source) | Agreed | Not authorized | Implemented (partial evidence) | Code inspection (not exhaustive) |

---

## S1-01 — Trading opportunities appear in Telegram first

**Plain-language requirement**: the user's primary surface for
"something that might warrant a decision" is Telegram, not the
dashboard.

**Source/session**: Session 1, product-owner discussion.

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized — this documents
already-built, previously-authorized behavior for the first time at the
product-experience layer.

**Current implementation status**: `Implemented`. V2's paper BUY/SELL
notifications are delivered via Telegram (`talonx_v2` delivery lane,
integrated through Task 110–117 of this project's history); Intelligence's
`IMMEDIATE`-route informational alerts are delivered via Telegram
(`talonx_ingest/intelligence/delivery/`, Task 96F onward, hardened
through Task 140c this session).

**Validation status**: `Verified` — **Code inspection** (delivery
pipeline code read directly this session) + **Natural live behavior**
(real AXON/DD/ADM/ALK messages traced against the live production
ledger this session, `docs/research/evidence/task140/`).

**Evidence references**: `docs/research/evidence/task140/README.md` and
its subfolders; `talonx_v2/service.py`; `talonx_ingest/intelligence/
delivery/pipeline.py`.

**Open questions/dependencies**: none for the core claim; depends on
S1-09 (intraday-vs-multi-day scope) for exactly WHICH strategies'
opportunities this applies to going forward.

---

## S1-02 — Optional major-development notifications

**Plain-language requirement**: general corporate-development alerts
(distinct from trade-actionable V2 alerts) must be optional, not forced.

**Source/session**: Session 1.

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized (pre-existing,
newly documented).

**Current implementation status**: `Implemented`. Intelligence's
notification policy (`notification_policy.py::classify_disposition`)
already distinguishes `IMMEDIATE` (interrupts) from `DIGEST` (routine,
currently OFF by default) from `DASHBOARD_ONLY` (never leaves the
dashboard) — the user is never forced to receive routine filing traffic.

**Validation status**: `Verified` — **Code inspection** +
**Natural live behavior** (this session's Task 140/140b/140c work
traced real production sends and non-sends against this exact policy).

**Evidence references**: `talonx_ingest/intelligence/delivery/
notification_policy.py`; `docs/research/evidence/task140/README.md`
("digest off by default").

**Open questions/dependencies**: none.

---

## S1-03 — Routine filings and general corporate monitoring stay on the dashboard

**Plain-language requirement**: raw filing inventory and general
corporate monitoring should not compete with Telegram for the user's
attention — they belong on the dashboard.

**Source/session**: Session 1.

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized (pre-existing).

**Current implementation status**: `Implemented`. Routine digest send
is OFF by default (`TALONX_INTEL_DELIVER_DIGEST_ENABLED` default
`False`, commit `55dd31c`); the dashboard's Intelligence tab remains the
full, always-available record regardless of delivery state.

**Validation status**: `Verified` — **Code inspection** (this session,
`docs/research/evidence/task140/README.md`).

**Evidence references**: `docs/research/evidence/task140/README.md`;
`dashboard_web_static/index.html`'s `renderIntelligence`.

**Open questions/dependencies**: none.

---

## S1-04 — Preferred UK 08:00–22:00 operating window

**Plain-language requirement**: the user typically expects the system
to be relevant/operating between 08:00 and 22:00 UK local time. This is
explicitly a **preference statement**, not an assertion that a
scheduler already exists.

**Source/session**: Session 1.

**Decision status**: `Agreed` (as a stated preference to evaluate
against — not yet a concrete acceptance criterion).

**Implementation authorization**: `Not authorized`. No scheduler
implementation is authorized by this record.

**Current implementation status**: `Not implemented` as an automatic
scheduler. The only existing UK-time-related code
(`talonx_ops/prospective/paths.py`, `close.py`, `__main__.py`) converts
timestamps to Europe/London for **display purposes** in a manually
operator-invoked start/close command pair (`python -m talonx_ops.
prospective {start|close}`) — it does not itself gate operating hours.
The system otherwise runs continuously once started.

**Validation status**: `Verified` — **Code inspection** (grep +
direct read of the three matching files this session; no scheduler
logic found).

**Evidence references**: `talonx_ops/prospective/paths.py:69`,
`close.py:235`, `__main__.py:57`.

**Open questions/dependencies**: whether "preferred operating window"
should become (a) an actual start/stop scheduler, (b) a quieter-hours
notification-suppression window only, or (c) remain purely descriptive
of when the operator personally checks in — not decided; a candidate
topic for a later session (see `KNOWLEDGE_TRANSFER_PLAN.md` §11,
Operation/stop-start/recovery).

---

## S1-05 — Plain-language, evidence-led, jargon-free alerts

**Plain-language requirement**: trade alerts begin with a one-sentence
plain-English explanation of the supporting evidence; major-development
messages explain what happened and why it matters without unexplained
SEC jargon.

**Source/session**: Session 1.

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized (documents +
partially contradicts existing behavior — see gap below).

**Current implementation status**: `Partially implemented`. The
concise-alert content gate (Task 138 Workstream 2 through Task 140c,
this session) already enforces "a specific supported development, not
a bare category label alone" — multiple real defects of exactly that
kind were found and fixed this session. **Gap, found by direct
inspection of a real sent message**: the header line format
(`EVENT_TYPE_LABEL`) still surfaces raw SEC citation syntax, e.g. a
real production message read *"Direct financial obligation (8-K Item
2.03/2.04)"* — "Item 2.03/2.04" is unexplained jargon to a reader with
little investment knowledge, exactly the audience this product is being
reviewed for.

**Validation status**: `Verified (gap identified)` — **Code inspection**
+ **Natural live behavior** (the exact real message is quoted in
`docs/research/evidence/task140/axon_live_defect/before_after_message_
examples.md`).

**Evidence references**: `talonx_ingest/intelligence/delivery/
renderer.py` (`EVENT_TYPE_LABEL`, `render_concise`);
`docs/research/evidence/task140/axon_live_defect/`.

**Open questions/dependencies**: whether removing/rewording the raw
item-number citation is itself a requirement the owner wants
prioritized, or an acceptable technical-audience detail — not decided;
a candidate topic for Session 7 (Intelligence and useful company
developments).

---

## S1-06 — Clear actionability/expiry status

**Plain-language requirement**: the user must be able to tell, at a
glance, whether an opportunity is still actionable or has expired — to
avoid chasing a stale entry.

**Source/session**: Session 1.

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized.

**Current implementation status**: `Partially implemented`. V2's
internal state machine already has terminal, non-actionable states
including `SKIPPED_ENTRY_STALE` (fixed this project's Task 113, a real
P1 defect where a stale historical cluster was nearly replayed into a
fresh campaign) and reservation-expiry handling (this session's Task
140 reservation-expiry-exactly-once work). Whether that internal state
is **surfaced to the operator in the Telegram alert itself** (as
opposed to only the dashboard/internal log) was **not examined in this
documentation pass**.

**Validation status**: `Partially verified` — **Code inspection**
(internal state machine, this project's history + this session's
reservation-lifecycle tests) confirms the internal mechanism exists;
the Telegram-facing surfacing question is `NOT ASSESSED IN THIS
DOCUMENTATION PASS`.

**Evidence references**: `talonx_v2/service.py` (`SKIPPED_ENTRY_STALE`);
`docs/research/evidence/task140/` (reservation-expiry evidence, earlier
in this session's Task 140 work).

**Open questions/dependencies**: a candidate topic for Session 8 (V2
multi-day strategy and lifecycle) and Session 9 (Telegram and dashboard
experience) — needs a concrete acceptance check of what the OPERATOR
actually sees for a stale/expired opportunity, not just the internal
state.

---

## S1-07 — Standardized paper sizing; $10,000 proposed

**Plain-language requirement**: paper-trade position sizing should be
standardized (a consistent, predictable allocation), with $10,000 per
allocation proposed as the figure. Cross-lane (Original vs. V2) scope is
explicitly not finalized.

**Source/session**: Session 1.

**Decision status**: `Proposed` (the $10,000 figure and cross-lane
scope) / `Agreed` (the general need for standardization).

**Implementation authorization**: `Not authorized`. No sizing change is
authorized by this record.

**Current implementation status**: `Partially implemented`. **Verified
by direct code inspection**: V2's own default
(`talonx_v2/config.py::per_position_allocation_usd`, env
`TALONX_V2_ALLOCATION_USD`) is **already `$10,000`**. Original's own
default (`talonx_paper/config.py::default_trade_allocation_usd`, env
`TALONX_PAPER_TRADE_ALLOCATION`) is **`$2,500`** — a different figure.
The two lanes are not currently unified.

**Validation status**: `Verified` — **Code inspection** (both config
files read directly this session; exact line numbers below).

**Evidence references**: `talonx_v2/config.py:58-60`; `talonx_paper/
config.py:84`.

**Open questions/dependencies**: whether unification means raising
Original to $10,000, lowering V2, or keeping lane-specific sizes
by design (intraday risk profile vs. multi-day) — not decided; depends
on S1-09's scope decision (does Original's intraday lane remain part of
the product at all).

---

## S1-08 — Interactive Telegram buttons deferred

**Plain-language requirement**: new interactive buttons (as opposed to
the existing reply-with-text "details" correlation) are a low priority
and should not be built now.

**Source/session**: Session 1.

**Decision status**: `Agreed` (to defer).

**Implementation authorization**: `Explicitly not authorized` — the
owner's own instruction is not to build this now.

**Current implementation status**: `Not implemented`. No interactive
(inline-keyboard-style) Telegram buttons exist anywhere in the delivery
code inspected this session or across this project's prior sessions;
the existing "details" mechanism is a plain-text reply correlation
(`talonx_ingest/intelligence/delivery/reply_correlation.py`), not a
button. This is consistent with the deferral, not a gap.

**Validation status**: `Verified` — **Code inspection** (this session's
extensive reply_correlation.py work, Task 138/140).

**Evidence references**: `talonx_ingest/intelligence/delivery/
reply_correlation.py`.

**Open questions/dependencies**: none — explicitly deferred, revisit
only if the owner raises it again in a future session.

---

## S1-09 — Intraday vs. multi-day product-identity scope

**Plain-language requirement**: should TalonX's product identity (a)
retain Original's intraday lane, (b) focus on V2's multi-day
opportunities only, or (c) explicitly support both?

**Source/session**: Session 1 — raised as an unresolved question by the
assistant during the discussion of the owner's "swing intelligence
assistant" framing, not answered by the owner in Session 1.

**Decision status**: `Open — not decided`. Recorded explicitly as open;
not defaulted to any option.

**Implementation authorization**: `N/A` — nothing to authorize until a
decision exists.

**Current implementation status**: `N/A` for a decision that doesn't
exist yet. Factually, as of today's codebase, **both** Original
(intraday) and V2 (multi-day, `INSIDER_BUY_CLUSTER_V2@1`) exist and run
concurrently — this is a description of current fact, not a decision
that "both" is the agreed product scope.

**Validation status**: `N/A`.

**Evidence references**: `docs/RESEARCH_STATUS.md` (Original's
research-closed status); `docs/research/TALONX_RESEARCH_LEDGER.md`
Task 107B/109 onward (V2's origin).

**Open questions/dependencies**: this decision affects S1-01 (which
lane's opportunities are "first"), S1-07 (cross-lane sizing), and
potentially the entire Session 8 (V2 lifecycle) / Session 6 (Original
strategy) discussion structure. Should be prioritized early in a future
session.

---

## S1-10 — Free-tier data and paper-only boundary

**Plain-language requirement**: the product uses existing free-tier
infrastructure only (no new paid data sources) and never executes with
real capital.

**Source/session**: Session 1 (restating a long-established project
boundary in the product-experience layer for the first time).

**Decision status**: `Agreed`.

**Implementation authorization**: Not newly authorized — this is
already the project's enforced practice, established well before
Session 1.

**Current implementation status**: `Implemented`. No paid data source
exists anywhere in the codebase inspected across this project's
history; V2's dashboard card explicitly surfaces `real capital: BLOCKED`
and no broker-order code path exists for V2.

**Validation status**: `Verified` — **Code inspection** (established
and re-confirmed repeatedly across this project's history, including
this session's own boundary checks before every cutover).

**Evidence references**: `dashboard_web_static/index.html`
(`renderV2`'s `real_capital` line); `docs/RESEARCH_STATUS.md`.

**Open questions/dependencies**: none.

---

## S1-11 — Separate market-session labels from opportunity-status labels

**Plain-language requirement**: a proposal (not the owner's original
stated intent, which is S1-06's actionability requirement) to stop a
"regular trading hours" session label from implying an opportunity is
currently active — these should be two visually/semantically distinct
labels.

**Source/session**: Session 1 — proposed refinement, raised during
discussion of S1-06's actionability intent.

**Decision status**: `Proposed`. Recorded **separately** from S1-06's
agreed intent, per the owner's own instruction not to conflate the two.

**Implementation authorization**: `Not authorized`.

**Current implementation status**: `Not implemented` as a distinct
labelling scheme — `NOT ASSESSED IN THIS DOCUMENTATION PASS` in full
depth (a precise inventory of every place a session label and an
opportunity-status label might currently be conflated was not performed
in this documentation-only pass).

**Validation status**: `Not assessed in this documentation pass`.

**Evidence references**: none yet — a candidate for direct inspection
in Session 9 (Telegram and dashboard experience).

**Open questions/dependencies**: depends on S1-06's fuller resolution.

---

## S1-12 — "High conviction" is a desired quality, not a profitability/confidence-score claim

**Plain-language requirement**: "high conviction" describes what the
user wants to feel about a surfaced opportunity — it is not a claim
that the system has proven profitability, and it does not authorize
inventing a numeric confidence score.

**Source/session**: Session 1.

**Decision status**: `Agreed` (as a guardrail/definition constraint).

**Implementation authorization**: `Not authorized` (a constraint on
future work, not a feature to build).

**Current implementation status**: `Implemented` in the sense that
nothing currently violates it — no confidence-score feature exists
anywhere in the product to check against this constraint, and the
system's existing claim-safety enforcement
(`talonx_ingest/intelligence/delivery/claim_safety.py`'s
`assert_clean`/`PredictiveLanguageError`, which rejects predictive or
price-target language before any message can be sent) is directionally
consistent with this guardrail.

**Validation status**: `Verified` — **Code inspection** (claim-safety
module read this session as part of the AXON/DD content-gate work).

**Evidence references**: `talonx_ingest/intelligence/delivery/
claim_safety.py`.

**Open questions/dependencies**: exact acceptance criteria for what
"high conviction" should concretely look like (a qualitative label?
which evidence combinations qualify?) deferred to a later session, per
the owner's own instruction.

---

## S1-13 — Example/alert wording accuracy guardrail

**Plain-language requirement**: generated copy must not call people
"executives" or describe a transaction as using "personal funds" unless
the underlying source data specifically supports those descriptions.

**Source/session**: Session 1.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized` (a constraint on
future/existing copy, not new feature work).

**Current implementation status**: `Implemented` (partial evidence).
The real insider-transaction renderer paths inspected this session
(Task 140c's DD/ABCL/ABT examples) cite a real, pre-aggregated role
subset verbatim (e.g. "CEO reported open-market N sale(s)", drawn from
`activity.role_subsets` / `RoleSubsetAggregate.subset`, restricted to
the real `CEO`/`CFO` values only — never an invented "executive" label)
and never manufacture an "executive" label; no instance of "personal
funds" wording was found anywhere in the renderer code read this
session.

**Validation status**: `Verified (not exhaustive)` — **Code inspection**
of the specific render paths exercised this session
(`talonx_ingest/intelligence/delivery/renderer.py`'s `_insider_facts`);
not a claim that every render path in the codebase was checked.

**Evidence references**: `talonx_ingest/intelligence/delivery/
renderer.py`; `docs/research/evidence/task140/alert_usefulness_review/
rendered_samples_post_fix.txt` (real "CEO reported..." examples).

**Open questions/dependencies**: a full audit of every message-
generating path (not just the ones exercised this session) is a
candidate for Session 7 (Intelligence and useful company developments).
