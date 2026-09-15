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
| S2-01 | Alert-to-action mapping (BUY/SELL/EXIT act, BULLISH/BEARISH inform only) | Agreed | Not authorized by this documentation task | Implemented | Code inspection (this session) |
| S2-02 | No automatic shorting; SELL without a position gets an explicit, non-fabricating disposition | Agreed | Not authorized by this documentation task | Implemented | Code inspection (this session) |
| S2-03 | Capacity-skip records visible; cash never inflated/reset to force entry | Agreed | Not authorized by this documentation task | Partially implemented | Code inspection (this session) |
| S2-04 | Signal qualification distinct from paper-portfolio admission; skipped opportunities never counted as executed returns | Agreed | Not authorized by this documentation task | Partially implemented | Code inspection (this session) |
| S2-05 | Same execution/accounting rules for live and replay, separate campaign state/clocks | Agreed | Not authorized by this documentation task | Partially implemented | Code inspection (this session) |
| S2-06 | Replay respects information availability (no look-ahead); 2-year window desired, feasibility unverified | Agreed | Not authorized by this documentation task | Partially implemented (bounded window only) | Code inspection (this session) |
| S2-07 | EOD separates daily equity movement, realized, open/unrealized P&L; no auto-close of multi-day positions | Agreed | Not authorized by this documentation task | Implemented | Code inspection (this session) |
| S2-08 | Exit follows strategy's own rules; unresolved/delayed outcome disclosed when data unavailable | Agreed | Not authorized by this documentation task | Implemented | Code inspection (established this project's history + this session) |
| S2-09 | Directional accuracy and profitability reported as separate measurements | Agreed | Not authorized by this documentation task | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S2-10 | Equal-prominence Account Equity / Aggregate Open-Position P&L; per-position "contribution relative to entry equity" labelling; no cross-denominator summing | Agreed | Not authorized by this documentation task | Partially implemented (fields exist; prescribed labelling/layout does not) | Code inspection (this session) |
| S2-11 | Consistent gross/net and realized/unrealized disclosure; deposit/withdrawal methodology deferred | Agreed | Not authorized by this documentation task | Partially implemented | Code inspection (this session) |
| S2-12 | "Awaiting price"/"Valuation stale" with timestamp; unresolved P&L never shown as zero; incomplete equity flagged | Agreed | Not authorized by this documentation task | Partially implemented (status/None-vs-zero mechanism exists; prescribed wording does not) | Code inspection (this session) |
| S2-13 | Actual strategy exit rule + stop-loss status disclosed to the operator; V2-specific wording; allocation ≠ max/expected loss | Agreed | Not authorized by this documentation task | Partially implemented (rule exists and is frozen in code; operator-facing disclosure not found) | Code inspection (this session) |
| S2-14 | Strategy/stop-loss variants use separate versioned experiments and isolated accounts; baseline preserved | Agreed | Not authorized by this documentation task | Implemented | Code inspection (established, `talonx_research/`, this project's history) |
| S2-15 | No claim that a stop-loss necessarily helps/hurts; prior +2.0219% result is conditional evidence, not a live promise; no new experiment authorized here | Agreed | Explicitly not authorized (no new research experiment) | Not implemented (correctly — nothing to build) | Code inspection (this session) |

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

---

## S2-01 — Alert-to-action mapping

**Plain-language requirement**: BUY opens a long position (subject to
entry/portfolio rules); SELL/EXIT closes an existing position; BULLISH
and BEARISH are informational observations that execute nothing.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task` (this documents already-built behavior).

**Current implementation status**: `Implemented`. V2's episode pipeline
only ever opens a position via the `BUY` path in `talonx_v2/paper.py`
(`open_position`, triggered by an insider-buy-cluster episode reaching
`ENTERED`); exit is a separate, dedicated close path
(`talonx_v2/pipeline.py`'s 10th-trading-session close). No code path
was found this session that executes anything from a BULLISH/BEARISH-
labelled signal — those originate from Original/Intelligence's
descriptive layers, not V2's paper-execution layer.

**Validation status**: `Verified` — **Code inspection** (`talonx_v2/
paper.py`, `talonx_v2/pipeline.py`, this session).

**Evidence references**: `talonx_v2/paper.py:93-139`; `talonx_v2/
pipeline.py:148`.

**Open questions/dependencies**: none for V2; Original's own
intraday BUY/SELL signal-to-action mapping was not re-inspected this
session (established in this project's prior history, not re-verified
here).

---

## S2-02 — No automatic shorting; explicit disposition for a SELL without a position

**Plain-language requirement**: the system must never automatically
short a name, and a SELL/EXIT signal with no applicable existing
position must not fabricate a short or invented proceeds — it needs an
explicit, honest disposition.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Implemented`. V2's own service
status explicitly reports `"shorts": False` (`talonx_v2/service.py:1130`)
as a structural, always-true field, not a runtime toggle — no
short-selling code path exists to disable. An exit without a matching
open position cannot occur in V2's own flow because exits are only
evaluated against the strategy's own tracked open positions (there is
no independent "SELL signal" input to V2 at all — V2's only decision
input is the insider-buy-cluster episode pipeline).

**Validation status**: `Verified` — **Code inspection** (`talonx_v2/
service.py:1130`, this session).

**Evidence references**: `talonx_v2/service.py:1130`.

**Open questions/dependencies**: Original's intraday SELL-without-
position handling was not re-inspected this session — a candidate for
Session 6 (Original intraday strategy and filters).

---

## S2-03 — Capacity-skip records visible; cash never inflated to force an entry

**Plain-language requirement**: a qualified opportunity the virtual
account cannot currently take must remain visible, with an appropriate
skip record — and cash must never be inflated or reset to force an
entry.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. V2's entry
path (`talonx_v2/paper.py::open_position`) already returns distinct,
named, non-fabricating skip outcomes — `NO_CASH`, `SYMBOL_ALREADY_OPEN`,
`IN_COOLDOWN_UNTIL_*`, `MAX_CONCURRENT_*`, `BAD_ENTRY_PRICE` — and cash
is only ever debited by a real committed BUY inside one atomic
transaction (`store.transaction()`); no code path was found this
session that inflates or resets cash. **Gap**: none of these skip codes
reads as the specific operator-facing wording "Paper entry skipped:
insufficient cash/capacity" suggested in the discussion — the mechanism
exists under different, more granular naming; whether these codes are
currently surfaced anywhere the operator actually sees (Telegram/
dashboard) was **not traced end-to-end this session**.

**Validation status**: `Verified (mechanism)` / `Not assessed
(operator-facing surfacing)` — **Code inspection** (`talonx_v2/
paper.py:93-139`, this session).

**Evidence references**: `talonx_v2/paper.py:93-139`.

**Open questions/dependencies**: whether the near-miss funnel already
referenced in `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §3 ("V2 near-miss funnel: 4 historical
clusters, all stale") is the same mechanism the operator would see for
a live capacity skip — not confirmed this session; candidate for
Session 8 (V2 multi-day strategy and lifecycle) or Session 9 (Telegram
and dashboard experience).

---

## S2-04 — Signal qualification distinct from paper-portfolio admission

**Plain-language requirement**: "this is a qualified opportunity" and
"this was admitted into the paper portfolio" must be distinguishable,
and a skipped opportunity's hypothetical outcome must never be counted
as an executed portfolio return.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. The
underlying mechanism supports the distinction — a cluster episode can
reach eligibility (a qualifying insider-buy pattern) without ever
reaching `ENTERED` (blocked by `NO_CASH`/`MAX_CONCURRENT_*`/etc, S2-03)
— and V2's realized/unrealized P&L accounting
(`talonx_ops/paper_performance.py`) only ever sums real
`trade_history` rows, never a hypothetical skipped entry. Whether the
dashboard and any Telegram messaging **consistently label** the
qualification/admission distinction for the operator (as opposed to
the accounting layer correctly excluding skipped entries, which is
confirmed) was **not traced end-to-end this session**.

**Validation status**: `Verified (accounting exclusion)` / `Not
assessed (operator-facing labelling consistency)` — **Code inspection**
(`talonx_ops/paper_performance.py`, `talonx_v2/paper.py`, this
session).

**Evidence references**: `talonx_ops/paper_performance.py:436-454`;
`talonx_v2/paper.py:93-139`.

**Open questions/dependencies**: candidate for Session 8/Session 9,
same as S2-03.

---

## S2-05 — Same execution/accounting rules for live and replay

**Plain-language requirement**: live paper evaluation and historical
replay should reuse the same execution/accounting rules, with separate
campaign/account state and appropriate real/simulated clocks.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. Task
115/116 (this project's history, `docs/research/
TALONX_RESEARCH_LEDGER.md`) built `talonx_research/replay_engine.py`,
which drives the **real** `V2Service.tick()` chronologically against a
**physically separate** ledger file (the replay engine "physically
refuses `v2_lane.db`" — the live campaign database is structurally
unreachable from replay) — a genuine, verified shared-rules
architecture, not a reimplementation. This was built and exercised as
a **research validation tool**, not yet confirmed as the product's own
standing "live vs. replay" feature with its own operator-facing
identity — that framing is `NOT ASSESSED IN THIS DOCUMENTATION PASS`.

**Validation status**: `Verified (mechanism, as research infrastructure)`
— **Code inspection** (`talonx_research/replay_engine.py`'s existence
and its own prior task documentation, this session); not re-executed
this session (no application tests run, per this task's own
restriction).

**Evidence references**: `talonx_research/replay_engine.py`;
`docs/research/TALONX_RESEARCH_LEDGER.md` (Task 115/116 entries).

**Open questions/dependencies**: whether this research-grade replay
engine should become a product-facing feature (vs. remaining an
internal validation tool) — not decided; candidate for Session 12
(Technical validation, usefulness and economic evidence).

---

## S2-06 — Replay respects information availability; 2-year window desired, feasibility unverified

**Plain-language requirement**: replay must never access future data
relative to its simulated clock; a two-year replay window is desired,
but its data feasibility is explicitly not established by this
decision.

**Source/session**: Session 2.

**Decision status**: `Agreed` (need + no-look-ahead constraint) /
`Proposed` (the specific 2-year figure, feasibility unverified).

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. Task
115/116's replay engine drives the tick loop chronologically
(session-by-session, forward only) — consistent with no-look-ahead by
construction — over a window from 2024-09-01 to 2026-03-31, **bounded
by the available parquet data, not a full two years up to the present
session date**. Whether a genuine, current two-year-to-today window is
data-feasible was **not re-verified this session** — this documentation
pass explicitly does not claim it is.

**Validation status**: `Verified (existing window, no-look-ahead
mechanism)` / `Not assessed (2-year-to-today feasibility)` — **Code
inspection** + prior task evidence (`docs/research/
TALONX_RESEARCH_LEDGER.md`, Task 115/116).

**Evidence references**: `talonx_research/replay_engine.py`;
`docs/research/TALONX_RESEARCH_LEDGER.md` (Task 115/116).

**Open questions/dependencies**: a data-coverage audit for a genuine
rolling two-year window is future work, not performed here.

---

## S2-07 — EOD separates daily/realized/open P&L; no auto-close of multi-day positions

**Plain-language requirement**: EOD reporting shows daily equity
movement, realized results, and open/unrealized P&L as distinct
figures, and never automatically closes a multi-day position.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Implemented`. `talonx_ops/
paper_performance.py` computes `realized_pnl`, `unrealized_pnl`, and
`equity` as separate fields (each with its own status), surfaced
separately in the dashboard (`dashboard_web_static/index.html`'s
`renderV2`, lines ~446-458). Today's own EOD closure
(`docs/research/evidence/eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md`)
independently confirms V2's EOD reconciliation (`talonx_ops/
prospective/close.py`) never force-closes an open multi-day position —
it reconciles and reports, and the current campaign had 0 open
positions at that specific EOD to exercise the distinction against
directly.

**Validation status**: `Verified` — **Code inspection** (`talonx_ops/
paper_performance.py`, `dashboard_web_static/index.html`, this
session) + **Natural live behavior** (today's real EOD closure, no
force-close code path present or exercised).

**Evidence references**: `talonx_ops/paper_performance.py:436-458`;
`dashboard_web_static/index.html:446-458`; `docs/research/evidence/
eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md` §3.

**Open questions/dependencies**: none.

---

## S2-08 — Exit follows strategy's own rules; unresolved outcome disclosed when data unavailable

**Plain-language requirement**: final trade evaluation follows the
strategy's existing exit rules; if the planned exit can't complete
because data is unavailable, the system shows an unresolved/delayed
outcome rather than fabricating a close.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Implemented`. V2's frozen exit rule
(close of the 10th trading session after entry, `talonx_v2/
config.py:33`, `pipeline.py:148`) is the only exit path; when a
required exit price/date isn't available, the position surfaces as
`EXIT_UNRESOLVED` (this project's established terminal-state handling,
independently confirmed as `0` — meaning present and queryable, not
absent — in today's EOD obligations inspection).

**Validation status**: `Verified` — **Code inspection**
(`talonx_v2/config.py:33-36`, `pipeline.py:148`, this session) +
**Natural live behavior** (`EXIT_UNRESOLVED: 0` queried directly
against the live `v2_lane.db` during today's EOD closure).

**Evidence references**: `talonx_v2/config.py:33-36`; `talonx_v2/
pipeline.py:148`; `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §2.

**Open questions/dependencies**: none for the mechanism; whether
`EXIT_UNRESOLVED` is disclosed to the operator (not just internally
queryable) is folded into S1-06's open Telegram-surfacing question.

---

## S2-09 — Directional accuracy and profitability reported separately

**Plain-language requirement**: "was the direction called correctly"
and "was the trade profitable" are separate measurements and must not
be conflated in reporting.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Not assessed in this documentation
pass` — no existing dashboard/report field explicitly labelled
"directional accuracy" as distinct from P&L was located or ruled out
in the time available this session; this requires a dedicated
inspection of every performance-reporting surface, not performed here.

**Validation status**: `Not assessed in this documentation pass`.

**Evidence references**: none yet.

**Open questions/dependencies**: candidate for Session 10 (Paper
accounting, costs and risk) or Session 12 (Technical validation,
usefulness and economic evidence).

---

## S2-10 — Equal-prominence equity/open-P&L; per-position contribution labelling; no cross-denominator summing

**Plain-language requirement**: Account Equity and Aggregate
Open-Position P&L get equal visual prominence; each position shows its
monetary P&L, trade return, and a "Contribution relative to account
equity at entry" figure (denominator = equity immediately before that
position's entry); the overall account return is reported separately
and position percentages with different denominators are never summed
as if they were total account return.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. The
underlying data — per-position `unrealized_pnl_usd`, `realized_pnl_usd`,
`realized_pnl_pct`, and a separately-tracked account `equity` value —
already exists and is rendered (`dashboard_web_static/
index.html:446-478`). **Gaps found by direct inspection**: no
"Contribution relative to account equity at entry" label or
entry-equity-denominated contribution figure exists; no code enforces
or documents equal visual prominence between the equity figure and an
aggregate open-position-P&L figure (they are both present but not
verified as equally prominent by any explicit design rule); no
evidence either way of any place actually summing mismatched-
denominator percentages (not found, but not exhaustively ruled out
either).

**Validation status**: `Verified (data fields)` / `Verified (gap:
contribution labelling absent)` — **Code inspection**
(`dashboard_web_static/index.html:446-478`, this session).

**Evidence references**: `dashboard_web_static/index.html:446-478`;
`talonx_ops/paper_performance.py`.

**Open questions/dependencies**: candidate for Session 9 (Telegram and
dashboard experience) — this is a concrete, scoped presentation gap,
not a data-availability gap.

---

## S2-11 — Consistent gross/net, realized/unrealized disclosure; deposits/withdrawals deferred

**Plain-language requirement**: gross/net treatment and realized/
unrealized status are stated consistently; formal deposit/withdrawal
handling and a detailed portfolio-return methodology may come later and
must not be invented now.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. Realized
and unrealized figures are already structurally separate fields
(S2-07/S2-10 evidence); whether "gross" vs. "net" (of costs) is
consistently labelled everywhere was **not exhaustively checked** this
session — `talonx_ops/paper_performance.py` does carry a
`_TALONX_PAPER_COST_BREAKDOWN` structure attached to closed-trade
detail rows, suggesting cost/net figures exist for at least Original's
lane, but full-surface consistency was not verified. No deposit/
withdrawal feature exists anywhere in the codebase inspected this
session or across this project's history — correctly untouched, not a
gap, per this requirement's own explicit deferral.

**Validation status**: `Partially verified` — **Code inspection**
(`talonx_ops/paper_performance.py:433`, this session); gross/net
labelling consistency `NOT ASSESSED IN THIS DOCUMENTATION PASS` in
full.

**Evidence references**: `talonx_ops/paper_performance.py:420-433`.

**Open questions/dependencies**: deposit/withdrawal methodology and
full gross/net consistency audit — both explicitly deferred, candidates
for Session 10 (Paper accounting, costs and risk).

---

## S2-12 — Missing/stale valuation disclosure; unresolved P&L never shown as zero

**Plain-language requirement**: a missing current price shows
"Awaiting price" or "Valuation stale" with its timestamp; unknown/
unresolved P&L is never displayed as zero; a carried-forward mark is
labelled with its real freshness; incomplete equity is flagged as such.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. **Verified
by direct code inspection**: `talonx_ops/paper_performance.py`
computes `equity_status = "COMPLETE" if marked_value_complete else
("PARTIAL" if opens else "COMPLETE")` and, critically,
`equity_value = ... if marked_value_complete or not opens else None` —
equity is explicitly set to `None` (not zero, not silently estimated)
when a mark is incomplete, and flagged `PARTIAL` rather than presented
as fully current. This is a real, working match for this requirement's
**intent**. **Gap**: no literal "Awaiting price" / "Valuation stale"
string, and no explicit carried-forward-mark date label, was found in
`dashboard_web_static/index.html` — a grep for both exact phrases
returned no matches. The mechanism (never-zero, flagged-incomplete)
exists; the prescribed operator-facing wording does not.

**Validation status**: `Verified (mechanism)` / `Verified (gap:
prescribed wording absent)` — **Code inspection**
(`talonx_ops/paper_performance.py:451-452`, plus a direct grep of
`dashboard_web_static/index.html` for the requirement's literal
phrases, this session).

**Evidence references**: `talonx_ops/paper_performance.py:451-452`;
`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §4 (the related V2 pricing-freshness finding —
see also `OPERATIONAL_FINDINGS.md` `OPS-002`, which is about upstream
price-source freshness specifically, a related but distinct concern
from this dashboard-presentation requirement).

**Open questions/dependencies**: candidate for Session 9 (Telegram and
dashboard experience); directly related to, but not the same issue as,
`OPS-002`'s upstream pricing-resolver gap.

---

## S2-13 — Actual exit rule and stop-loss status disclosed; V2-specific wording; allocation ≠ loss

**Plain-language requirement**: the operator sees the real strategy
exit rule and stop-loss status; for the current V2 baseline
specifically, "Close of the 10th trading session after entry." / "No
price-based stop-loss."; this wording must not be applied to every
strategy; wording must avoid implying losses will recover before exit;
allocation is capital assigned, not a loss estimate.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Partially implemented`. **Verified
by direct code inspection**: the rule is real and frozen —
`talonx_v2/config.py:33` ("SELL at the CLOSE of the +10th trading
session after entry"), `stop_loss_enabled: bool = False` with an
explicit assertion (`config.py:94`, `assert self.stop_loss_enabled is
False`) guarding the frozen baseline, and `pipeline.py:148`'s own
comment confirms "FROZEN exit = close of the +10th trading session ...
the ONLY [exit rule]". **Gap**: no operator-facing surface (Telegram
message text, dashboard exit-rule display) presenting this rule in the
plain-language wording given in this requirement was found this
session — the rule is enforced in code, not explained to the operator
anywhere located.

**Validation status**: `Verified (rule exists, frozen)` / `Verified
(gap: operator-facing disclosure not found)` — **Code inspection**
(`talonx_v2/config.py:33-36,94`; `talonx_v2/pipeline.py:148`, this
session).

**Evidence references**: `talonx_v2/config.py:33-36,94`; `talonx_v2/
pipeline.py:148`.

**Open questions/dependencies**: candidate for Session 8 (V2 multi-day
strategy and lifecycle) or Session 9 (Telegram and dashboard
experience) — a concrete, scoped disclosure gap.

---

## S2-14 — Strategy/stop-loss variants use separate versioned, isolated experiments

**Plain-language requirement**: any strategy change, including a
stop-loss variant, runs as a separately versioned experiment with its
own isolated virtual account, comparable only under consistent
starting capital/data/cost assumptions — the baseline campaign is
preserved.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Not authorized by this documentation
task`.

**Current implementation status**: `Implemented`. This is the
established governance model built in Task 115/116
(`talonx_research/` — immutable `StrategyVersion`/`StrategyRegistry`,
the replay engine's own physical refusal to touch `v2_lane.db`, and
`docs/STRATEGY_LIFECYCLE.md`'s R1-R7 governance rules) — the exact
mechanism this requirement describes already exists as this project's
standing validation infrastructure, confirmed by this session's own
`git log` review and the prior task's evidence, not re-executed here.

**Validation status**: `Verified` — **Code inspection** (established,
this project's history — `talonx_research/`, `docs/
STRATEGY_LIFECYCLE.md`; re-confirmed present by directory/doc
inspection this session, not re-run).

**Evidence references**: `talonx_research/`; `docs/
STRATEGY_LIFECYCLE.md`; `docs/research/TALONX_RESEARCH_LEDGER.md`
(Task 115/116).

**Open questions/dependencies**: none.

---

## S2-15 — No stop-loss-necessarily-helps claim; prior result is conditional evidence; no new experiment authorized

**Plain-language requirement**: the product must not claim a stop-loss
necessarily improves or destroys returns; the prior +2.0219% net@20
result (Task 115/116) is conditional historical evidence, not a
validated promise for current live execution; this session authorizes
no new research experiment.

**Source/session**: Session 2.

**Decision status**: `Agreed`.

**Implementation authorization**: `Explicitly not authorized` — no new
research experiment is authorized by this or Session 2's own
discussion.

**Current implementation status**: `Not implemented` — correctly so;
nothing is meant to be built from this item. No stop-loss-variant
experiment, promotion, or fingerprint change was made this session
(confirmed: V2 fingerprint `11107198c5b81237` unchanged per today's own
EOD closure report).

**Validation status**: `Verified` — **Code inspection** / **Natural
live behavior** (V2 fingerprint unchanged, no new `talonx_research/`
experiment artifact created this session).

**Evidence references**: `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §4 (`v2_fingerprint_ok: true`, `11107198c5b81237`
unchanged); `docs/research/TALONX_RESEARCH_LEDGER.md` (Task 115/116,
the +2.0219%/+2.196% figures' own origin and stated conditionality).

**Open questions/dependencies**: whether/when a new stop-loss
experiment should be authorized is a future decision, not made here.
