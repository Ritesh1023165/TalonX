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
| S1-09 | Intraday vs. multi-day product-identity scope | **Resolved (Session 3) — see S3-01** | N/A | N/A | N/A |
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
| S3-01 | Both intraday and multi-day opportunities; one main feed, prominent horizon+strategy labels | Agreed (resolves S1-09) | Not authorized | Not implemented (no horizon-label UI found) | Code inspection (this session) |
| S3-02 | Original not retired/disconnected; intraday retention doesn't freeze Original's implementation | Agreed | Not authorized | Implemented (Original runs unchanged) | Natural live behavior (this project's history) |
| S3-03 | V2 is one multi-day strategy, not the whole multi-day category name | Agreed | Not authorized | Implemented (only one multi-day strategy exists today) | Code inspection (this session) |
| S3-04 | Intelligence facts/optional major-dev alerts; routine stays on dashboard (reaffirms S1-02/S1-03) | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S3-05 | Strategies independently identifiable/testable; own rules; shared contracts; no immediate consolidation | Agreed | Not authorized | Partially implemented (separation exists; shared contracts do not) | Code inspection (this session) |
| S3-06 | Qualified opportunity vs. paper admission distinct at target-architecture level | Agreed | Not authorized | Partially implemented (extends S2-03/S2-04) | Code inspection (this session) |
| S3-07 | Positions identified by account+strategy+opportunity, not ticker alone; horizon-crossed EXIT must not close the other's position | Agreed | Not authorized | Partially implemented (achieved via separate DBs, not a composite key) | Code inspection (this session) |
| S3-08 | Single master stock list (discovery+manual+exclusions); dedupe by security identity; global default + per-horizon overrides | Agreed | Not authorized | Not implemented (no unified master list found) | Code inspection (this session) |
| S3-09 | Manual-addition validation requirements; never bypasses eligibility rules | Agreed | Not authorized | Not implemented (no manual-addition validation flow found) | Code inspection (this session) |
| S3-10 | Distinct visible states (membership/identity/data-ready/eligible/qualified); no immediate broad-universe intraday expansion; counts not permanent | Agreed | Not authorized | Not implemented (states not distinctly surfaced) | Code inspection (this session) |
| S3-11 | Pause/Exclude/Mute definitions; per-horizon; never closes positions/deletes history; mute ≠ pause | Agreed | Not authorized | Partially implemented (Original's own active/paused ticker status exists; not per-horizon, no Exclude/Mute distinction) | Code inspection (this session) |
| S3-12 | New-campaign defaults: $100,000 cash, $10,000 allocation, configurable, no inflation/forced entry | Agreed | Not authorized | Not implemented (new default; no new campaign created) | Code inspection (this session) |
| S3-13 | Separate approved/baseline-shadow/experimental accounts; combined-exposure view; no pooling; no mixing into approved results | Agreed | Not authorized | Not implemented (no combined-exposure view found) | Code inspection (this session) |
| S3-14 | Existing campaigns not overwritten by new defaults; comparisons disclose changed capital assumptions | Agreed | Not authorized | Implemented (V2's $300k campaign untouched by this session) | Natural live behavior (this session; no write occurred) |
| S3-15 | Research workflow: replay → live shadow → review → explicit promotion; versioned config; isolated state | Agreed | Not authorized | Partially implemented (replay engine exists; shadow/promotion workflow not confirmed) | Code inspection (this session) |
| S3-16 | Equivalent assumptions for historical comparisons; live comparisons use an equivalently-initialized shadow account | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S3-17 | Evaluation criteria set before inspecting results; failed experiments preserved; unseen periods; EOD is interim not final | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S3-18 | Promotion carries config+evidence+effective time; existing positions retain prior rules; rollback preserved; logic vs. config changes distinguished | Agreed | Not authorized | Partially implemented (`talonx_research/`'s immutable StrategyVersion exists) | Code inspection (established, this project's history) |
| S3-19 | Research Lab dashboard visibility list; "EXPERIMENTAL — INTERNAL ONLY" label; no auto-promotion from a metric | Agreed | Not authorized | Not implemented (no such dashboard view found) | Code inspection (this session) |
| S3-20 | 2-year replay desired not verified; no experiment/profitability claim authorized here | Agreed | Explicitly not authorized | Not implemented (correctly — nothing to build) | Code inspection (this session) |
| S3-21 | Experiments off main feed; optional internal research bot, OFF/SUMMARY/DETAILED, no fallback to main bot | Agreed | Explicitly not authorized (no bot creation) | Not implemented | Code inspection (this session) |
| S3-22 | Approved display names; "Fundamental Opportunities" provisional; internal IDs/DBs/modules preserved | Agreed | Explicitly not authorized (no rename) | Not implemented (display layer; no renaming done) | Code inspection (this session) |
| S3-23 | Conditional database-reset permission for a future authorized implementation, with a 9-step required approach | Agreed | Not authorized now; conditionally pre-authorized for a future task that follows the 9-step approach | Not implemented (no reset performed) | N/A |
| S3-24 | Deferred: Original's long-term/fundamentals path role review | Open — deferred | N/A | N/A | N/A |
| S3-25 | Deferred: cross-strategy capital/exposure enforcement policy | Open — deferred | N/A | N/A | N/A |
| S3-26 | Deferred: detailed experiment evaluation criteria/evidence sufficiency | Open — deferred | N/A | N/A | N/A |
| S3-27 | Deferred: exact 2-year historical data feasibility | Open — deferred | N/A | N/A | N/A |
| S3-28 | Deferred: remaining lifecycle semantics (mute controls, pending intents on pause) | Open — deferred | N/A | N/A | N/A |
| S4-01 | One "Start monitoring" action using saved settings | Agreed | Not authorized | Partially implemented (single-command start exists; no per-strategy readiness gate) | Code inspection (this session) |
| S4-02 | Resume enabled strategies only when prerequisites pass; per-strategy + shared-dependency readiness exposed | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S4-03 | Recover obligations/pending intents before new discovery; no chronological-accounting change; no later-funds-earlier | Agreed | Not authorized | Not assessed in this documentation pass (cross-system ordering not traced) | Not assessed in this documentation pass |
| S4-04 | Preserve campaign balances/positions/reservations/exit rules across start/stop | Agreed | Not authorized | Implemented (established, EOD closure evidence) | Natural live behavior (established) |
| S4-05 | Catch-up ingestion must not create late prospective entries or stale "act now" alerts | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S4-06 | Primary Telegram bot: opportunities, lifecycle updates, optional major-dev | Agreed | Not authorized (pre-existing, partial) | Implemented (opportunities/major-dev); lifecycle-update coverage not assessed | Code inspection (established + this session) |
| S4-07 | Separate Operations bot for incidents/recovery notifications | Agreed | Explicitly not authorized (no bot creation) | Not implemented | Code inspection (this session) |
| S4-08 | Optional Research bot isolated, OFF by default | Agreed (reaffirms S3-21) | Explicitly not authorized | Not implemented | Code inspection (this session) |
| S4-09 | Bot creation/destinations/credentials require separate authorization; proposed flags not described as existing | Agreed | Explicitly not authorized | Implemented (this documentation itself follows the rule) | Code inspection (this session) |
| S4-10 | Paper execution automatic, independent of notification success | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (this session, delivery/execution code paths separate) |
| S4-11 | Explicit lifecycle states with separate missing-price/valuation modifiers | Agreed | Not authorized | Partially implemented (V2 has distinct FAILED_NO_MARKET_DATA vs. SKIPPED_ENTRY_STALE internally; not operator-facing) | Code inspection (this session) |
| S4-12 | Pausing new entries atomically cancels unfilled intents; preserves existing positions | Agreed | Not authorized | Not implemented (no atomic cancel-on-pause found) | Code inspection (this session) |
| S4-13 | EOD reports daily performance, open risk, unresolved obligations | Agreed (extends S2-07) | Not authorized (pre-existing) | Implemented | Code inspection (established, S2-07 evidence) |
| S4-14 | Independent outage detection + alert dedup are future work, not proven capabilities | Agreed | Not authorized | Partially implemented (single-owner Telegram-poller dedup exists; broader outage-detection/alert-dedup not confirmed) | Code inspection (this session) |
| S5-01 | One master security registry with per-strategy/horizon eligibility | Agreed | Not authorized | Not implemented (extends S3-08's finding) | Code inspection (this session) |
| S5-02 | CIK identifies issuer not security/class; track identity/symbol-history/price-series separately | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S5-03 | Daily bulk refresh + bounded event-triggered checks; retain last verified snapshot on failure, disclose freshness | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S5-04 | Preserve immutable historical versions/observed timestamps/verified effective dates | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S5-05 | Unknown/ambiguous identity blocks only affected admissions | Agreed | Not authorized | Not implemented (no registry to test against) | Code inspection (this session) |
| S5-06 | Registry refresh does not auto-expand approved universes | Agreed | Not authorized | N/A (no registry exists yet) | Code inspection (this session) |
| S5-07 | Coverage-count accuracy: 27/599 not adopted; actual 43/569/626 counts labelled with scope+date | Agreed | Not authorized | Implemented (in this documentation itself) | Code inspection (this session, dated citations) |
| S5-08 | Each strategy/data-contract version defines one primary provider/feed/opening-reference/adjustment basis | Agreed | Not authorized | Partially implemented (V2's csv mode is one such definition; not formalized as a versioned contract) | Code inspection (this session) |
| S5-09 | Official auction price ≠ provider daily-bar open | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S5-10 | Provider selection + free-tier feasibility remain OPEN | Open — deferred | N/A | N/A | N/A |
| S5-11 | No midday-price substitution/unvalidated fallback; qualified fallback is future work | Agreed | Not authorized | Implemented (CsvBarAdapter returns None, never substitutes — see OPS-002) | Code inspection (established, OPS-002) |
| S5-12 | Preserve source/first-receipt/processing/notification timestamps separately; batch timestamps ≠ observation evidence | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S5-13 | 3-session recovery: target entry = Session 1; recovery ends at exchange-calendar close of Session 3 | Agreed | Not authorized | **Partially implemented — session-based recovery exists; exact Session-3-close enforcement and pre-fill expiry remain pending OPS-003** (corrected 2026-09-16, was overstated as "Implemented") | Code inspection (this session, corrected); isolated test execution (`tests/test_task131_nonblocking_retry.py`, `tests/test_task113_stale_entry_guard.py`, 8 passed) |
| S5-14 | Only timely, durably admitted intents reconcile; check expiry before fill | Agreed | Not authorized | Partially implemented — admission/timeliness check exists; **pre-fill expiry check does not** (fill is attempted first, deadline checked only reactively after a miss) (corrected 2026-09-16, was overstated as "Implemented") | Code inspection (this session, corrected — `talonx_v2/service.py:504-548`) |
| S5-15 | Downtime/identity/corp-action delays do not extend the deadline | Agreed | Not authorized | Partially implemented — **downtime does not extend the deadline, confirmed** (deadline is a pure function of calendar dates, independent of process uptime); corp-action-delay interaction not assessed, no corp-action code exists (`OPS-004`) | Code inspection (this session) |
| S5-16 | Missing-price expiry = EXPIRED_NO_MARKET_DATA at product level; distinct identity/corp-action reasons preserved | Agreed | Not authorized | Partially implemented (internal code uses `FAILED_NO_MARKET_DATA`/`EXPIRED_STALE` as two distinct dispositions, not one; product-level `EXPIRED_NO_MARKET_DATA` label not surfaced; no corp-action reason exists — `OPS-004`) | Code inspection (this session) |
| S5-17 | Release reservations exactly once, no invented cash credit | Agreed | Not authorized (pre-existing) | Implemented — confirmed by a shared, structural SQL guard (`WHERE intent_id=? AND status='PENDING'`) backing every release path | Code inspection (`talonx_v2/store.py:526-536`, this session) + isolated test execution (`test_price_still_missing_next_session_releases_intent_exactly_once`, passed) |
| S5-18 | Delayed reconciliation preserves original entry-reference session/exit schedule; recorded-at disclosed separately | Agreed | Not authorized | Partially implemented (entry-session preservation confirmed; separate recorded-at disclosure not assessed) | Code inspection (this session) |
| S5-19 | Exact equality-at-deadline / receive-vs-commit semantics — explicit open acceptance detail | Open — deferred | N/A | N/A | N/A — **left unresolved by the 2026-09-16 correction pass**, per its own instruction not to choose this semantics |
| S5-20 | Deadline-consistency finding recorded for re-verification, not corrected here | Open — tracked (`OPS-003`, extended 2026-09-16 with a directly-confirmed intra-runtime dual-deadline discrepancy, in addition to the original Task 112R cross-methodology finding) | N/A | N/A | N/A |
| S5-21 | Verified renames preserve identity/intent via effective-dated mappings | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-22 | Before-entry splits use post-split entry basis | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-23 | After-target-entry splits require chronological reconstruction, transactional, exactly once | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-24 | Unverified changes block execution without discarding obligations | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-25 | Mergers/replacement securities require explicitly supported treatment | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-26 | Truncate+cash-in-lieu modeled policy; proportional cost basis; CORP_ACTION_CASH separate but counted in returns; unresolved entitlement not fabricated cash | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-27 | Decimal arithmetic internally; cents/4-decimal display; no intermediate truncation; rounding mode open | Agreed | Not authorized | Not assessed in this documentation pass (existing accounting precision not audited) | Not assessed in this documentation pass |
| S5-28 | Durable checkpoints + overlap/dedup + recoverable enrichment state; no fixed 16-hour assumption | Agreed | Not authorized | Partially implemented (Intelligence's own checkpoint/backfill/poller exists, Task 96B; 16h-assumption search found none to remove) | Code inspection (established + this session) |
| S5-29 | Prioritize obligations/timely intents over bulk historical work | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S5-30 | Pre-market lockout window PROPOSED/UNDEFINED | Open — deferred | N/A | N/A | N/A |
| S5-31 | 2-year replay feasibility remains OPEN (5 sub-questions) | Open — deferred (extends S3-27) | N/A | N/A | N/A |

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

**Session 3 update (2026-09-16) — clarified, not finalized**: `S1-09`
is now resolved (both horizons retained), which removes one blocker
noted above. Session 3 separately agreed a **new-campaign default** of
$10,000 per-position allocation **plus** $100,000 starting cash per
strategy account (`DECISION_LOG.md` Session 3, "Virtual account
defaults"; tracked as `S3-12`). This confirms the $10,000 figure as
the forward default for new campaigns, but **does not retroactively
change** Original's existing $2,500 default or V2's existing $300,000
campaign — cross-lane unification for *existing* accounts remains
undecided. **Decision status unchanged**: `Proposed` (the retroactive-
unification question) / `Agreed` (the $10,000 new-campaign figure,
newly settled by `S3-12`).

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

**Session 3 update (2026-09-16) — RESOLVED**: the product owner
decided TalonX offers **both** intraday and multi-day opportunities,
through one main Telegram feed using prominent INTRADAY/MULTI-DAY
labels and strategy identity (`DECISION_LOG.md` Session 3, "Agreed
product scope"; tracked as `S3-01`). **Decision status updated**:
`Open — not decided` → `Resolved — see S3-01`. This entry's original
text above is preserved unedited as the historical record of how the
question was first raised; this note documents the resolution, per
this tracker's own never-silently-edited discipline. `S3-01`'s own
implementation status is `Not implemented` (no horizon-label UI was
found this session) — the decision is settled, the UI work is not
authorized or built by this note.

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

**Session 3 update (2026-09-16) — clarified**: with both horizons
confirmed retained (`S3-01`) and a master stock list spanning both
(`S3-08`), this mapping now needs to resolve to a specific **account +
strategy + opportunity**, not just a ticker — see `S3-07` (positions
identified by account/strategy/opportunity, not ticker alone) and
`S3-08`/`S3-09` (master list, per-horizon overrides). This does not
change the BUY/SELL/EXIT/BULLISH/BEARISH mapping itself, only sharpens
which specific position/account it resolves to once multiple
strategies coexist under one shared stock list.

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

**Session 3 update (2026-09-16) — extended**: Session 3 recorded the
**full** research-lab workflow this requirement's isolation mechanism
supports — historical replay → internal live shadow → review →
explicit promotion, with dashboard visibility and an optional internal
research-bot delivery channel. See `S3-15` through `S3-21` for the
complete, newly-agreed workflow; this entry (`S2-14`) remains the
narrower "isolation exists" finding it always was, now a component of
that larger agreed picture rather than a standalone item.

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

---

# Session 3 requirements (S3-01 through S3-28)

Compact format (same five required fields per entry: decision status,
implementation authorization, current implementation status,
validation evidence, dependencies) — used here given the volume of
Session 3 items; see `DECISION_LOG.md` Session 3 for the full
plain-language discussion each entry summarizes.

## S3-01 — Both horizons; one main feed with prominent labels

**Requirement**: TalonX offers both intraday and multi-day
opportunities through one main Telegram feed with prominent INTRADAY/
MULTI-DAY labels and strategy identity. **Resolves `S1-09`.**
**Decision**: Agreed. **Authorization**: Not authorized by this
documentation task. **Implementation**: Not implemented — no
horizon-label UI (Telegram message formatting or dashboard) enforcing
this distinction was found this session. **Validation**: Code
inspection (this session; no positive match found for a horizon-label
convention in `talonx_v2/delivery.py` or `dashboard_web_static/
index.html`). **Dependencies**: `S3-08` (master stock list, per-
horizon eligibility) is a natural prerequisite for a horizon label to
be meaningful.

## S3-02 — Original not retired or disconnected

**Requirement**: keeping intraday does not retire/disconnect Original,
and does not freeze its own future implementation changes.
**Decision**: Agreed. **Authorization**: Not authorized (nothing to
build — a non-action). **Implementation**: Implemented — Original
continues running unchanged; no disconnection occurred.
**Validation**: Natural live behavior (established across this
project's history; Original's supervised process is unaffected by this
documentation task). **Dependencies**: none.

## S3-03 — V2 is one multi-day strategy, not the category name

**Requirement**: "V2" names `INSIDER_BUY_CLUSTER_V2@1` specifically;
future multi-day strategies are not implicitly "V2".
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — only one multi-day strategy exists
today, consistent with this naming discipline (nothing yet violates
it). **Validation**: Code inspection (`talonx_v2/config.py`'s single
frozen strategy identity, this session). **Dependencies**: relevant
again once a second multi-day strategy is proposed (`S3-15`-`S3-20`'s
research workflow governs how that would happen).

## S3-04 — Intelligence facts/optional alerts; routine on dashboard

**Requirement**: reaffirms `S1-02`/`S1-03` — Intelligence supplies
company facts/context with optional major-development notifications;
routine disclosures stay on the dashboard. **Decision**: Agreed (not
new). **Authorization**: Not authorized (pre-existing). \
**Implementation**: Implemented (see `S1-02`/`S1-03` for full
evidence). **Validation**: Code inspection (established).
**Dependencies**: none.

## S3-05 — Independently testable strategies with shared contracts

**Requirement**: each strategy owns its own qualification/timing/
entry/exit rules; strategies share data/opportunity/accounting/
presentation contracts where appropriate; this does not authorize
immediate process/database consolidation. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Partially
implemented — the independence half is real (Original and V2 are
fully separate processes/databases with their own rules today); the
"shared contracts" half does not exist (no common opportunity/
accounting/presentation interface spans both). **Validation**: Code
inspection (separate `v2_lane.db`/`paper_trading.db`, separate config
modules, this session and established history). **Dependencies**:
`S3-07` (position identification) is a natural first shared contract
if/when this is pursued — not authorized here.

## S3-06 — Qualified opportunity vs. paper admission (target architecture)

**Requirement**: extends `S2-03`/`S2-04` to the multi-strategy target
architecture — qualification and admission stay distinct concepts
regardless of how many strategies exist. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Partially
implemented — true within V2 today (`S2-03`/`S2-04`'s evidence); not
yet exercised across multiple concurrently-admitting strategies sharing
one stock list, since that list doesn't exist yet (`S3-08`).
**Validation**: Code inspection (this session, extending `S2-03`/
`S2-04`'s evidence). **Dependencies**: `S3-08`.

## S3-07 — Positions identified by account+strategy+opportunity

**Requirement**: positions are identified by account, strategy and
opportunity, not ticker alone; a horizon's EXIT must not close the
other horizon's position in the same stock. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Partially
implemented — the *outcome* is already achieved today (Original and V2
use entirely separate database files, so an intraday EXIT structurally
cannot reach a V2 position and vice versa), but **not** via a composite
account+strategy+opportunity key within a shared store — there is no
shared store yet. **Validation**: Code inspection
(`talonx_v2/paper.py`'s `episode_id`+`symbol` keying is scoped to V2's
own separate database; `talonx_watchlist/store.py` is Original's own
separate ticker store, this session). **Dependencies**: `S3-05`'s
shared-contracts question — a true composite key only becomes
necessary if/when stores are ever shared, which is not authorized.

## S3-08 — Single master stock list

**Requirement**: one master list combining discovery universes,
validated manual additions and explicit exclusions; dedupe by security
identity, not ticker alone; global default both horizons; per-stock/
per-horizon overrides. **Decision**: Agreed. **Authorization**: Not
authorized. **Implementation**: Not implemented — no unified list was
found. Today, Original has its own `talonx_watchlist/store.py`
(`active`/`paused` per ticker, no horizon dimension), V2 has its own
`execution_scope` (626 symbols, `talonx_v2/service.py`/`run.py`), and
Intelligence has its own collection-scope CIK list
(`talonx_ingest/intelligence/service/scope.py`,
`watchlist_source.py`) — three separate lists, not one master list.
**Validation**: Code inspection (this session — `talonx_watchlist/
store.py`, `talonx_v2/service.py`, `talonx_ingest/intelligence/
service/scope.py` each read directly). **Dependencies**: none
blocking to design; a real merge would need identity resolution across
all three today-separate lists.

## S3-09 — Manual-addition validation requirements

**Requirement**: manual additions require identity/provider/filing-
mapping/readiness validation and an explicit unsupported/awaiting-data
reason; adding a stock never bypasses eligibility rules.
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no manual-addition validation
flow (as a distinct, user-facing feature) was found this session; the
closest existing mechanism, Original's `TickerWatchlistStore.add_
ticker()`, validates only `status in ("active","paused")` and basic
symbol/name/exchange fields — it does not perform the richer identity/
provider/filing-mapping/strategy-readiness validation this requirement
describes. **Validation**: Code inspection (`talonx_watchlist/
store.py:188-206`, this session). **Dependencies**: `S3-08`.

## S3-10 — Distinct visible states; no automatic broad-universe expansion

**Requirement**: five distinct states (configured membership/identity
resolved/data ready/strategy eligibility/currently qualified); one
master list does not itself authorize expanding intraday polling to
the full broad universe; counts are timestamped, not permanent.
**Decision**: Agreed. **Authorization**: Not authorized (the
broad-universe-expansion prohibition is an explicit non-authorization).
**Implementation**: Not implemented — no UI/API surface distinguishing
these five states was found; existing surfaces report coarser states
(e.g. V2's `execution_scope_enforced`/`execution_scope_count` as a
single count, not five distinct per-symbol states). **Validation**:
Code inspection (this session). **Dependencies**: `S3-08`.

## S3-11 — Pause / Exclude / Mute definitions

**Requirement**: Pause (reversible, until resumed) vs. Exclude
(persistent, until explicitly removed) vs. Mute (notification
suppression only, distinct from both); per-horizon applicability;
neither Pause nor Exclude closes positions, deletes history, or
abandons exit management; existing-obligation prices/notifications
continue regardless. **Decision**: Agreed. **Authorization**: Not
authorized. **Implementation**: Partially implemented — Original's
`talonx_watchlist/store.py` already has a working `active`/`paused`
per-ticker status with a dedicated `pause_ticker()` method
(`store.py:222-225`) that survives without deleting the ticker's own
name/exchange/added_at history (`store.py:20-22`) — a real, working
partial match for the "Pause" half of this requirement. **Gaps**: no
per-horizon dimension (V2 has no equivalent pause mechanism at all);
no distinct "Exclude" (persistent, rediscovery-proof) state; no "Mute"
concept anywhere in the codebase. **Validation**: Code inspection
(`talonx_watchlist/store.py:20-22,188-225`, this session — direct grep
confirms `pause`/`paused` exist, `exclude`/`mute` as this requirement's
distinct concepts do not). **Dependencies**: `S3-28` (exact mute
controls and pending-intent handling, deferred).

## S3-12 — New-campaign virtual account defaults

**Requirement**: $100,000 starting cash per strategy account, $10,000
per-position allocation, both configurable; no borrowing/inflation/
forced-entry reset; strategy limits preserved, cash may tighten
further; fees/reservations can prevent funding 10 simultaneous
positions. **Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented as a stated default — this is a
new figure; no new campaign was created this session to apply it to.
**Note**: $10,000-per-position already matches V2's existing
`per_position_allocation_usd` default (`talonx_v2/config.py:58-60`,
see `S1-07`); the **new** element is the $100,000-starting-cash-per-
strategy-account figure, which does not match any existing running
campaign ($300,000 for V2, $10,000/$15,000 for Original's two lanes).
**Validation**: Code inspection (`talonx_v2/config.py:58-60` for the
allocation figure; no starting-cash-default match found for $100,000
specifically, this session). **Dependencies**: `S3-14` (existing
campaigns not overwritten).

## S3-13 — Separate accounts; combined-exposure view

**Requirement**: approved / baseline-shadow / experimental-candidate
accounts tracked separately; a combined-exposure view shows overlap
and labelled aggregate capital (two $100k accounts = $200k combined,
not a shared pool); experimental results never mixed into approved
performance. **Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no combined-exposure view (a
UI/API surface aggregating capital or exposure across more than one
account) was found this session. The underlying account-separation
precondition is met (V2 and Original already use physically separate
databases, and `talonx_research/`'s replay engine physically refuses
`v2_lane.db` — S2-14's evidence), but the aggregation/labelling view
itself does not exist. **Validation**: Code inspection (this session).
**Dependencies**: `S3-15`-`S3-19` (a baseline-shadow/experimental-
candidate account only exists once the research-lab workflow is
built).

## S3-14 — Existing campaigns not overwritten by new defaults

**Requirement**: V2's $300,000 campaign and Original's existing
$10,000/$15,000 lanes are not overwritten by the new $100,000/$10,000
defaults; future comparisons disclose changed capital assumptions.
**Decision**: Agreed. **Authorization**: Not authorized (a
non-action/constraint). **Implementation**: Implemented — trivially
true as of this documentation-only session: no database was written,
no campaign was reset or resized. **Validation**: Natural live
behavior (this session made zero database writes — read-only
inspection only, confirmed by this task's own restriction and this
session's actual tool use). **Dependencies**: `S3-23` (the conditional
reset policy governs how any *future* transition would be handled, not
this session).

## S3-15 — Research workflow: replay → shadow → review → promotion

**Requirement**: historical replay → internal live shadow → review →
explicit promotion; reuse strategy/execution/accounting code with
versioned config; isolate cash/positions/intents/reservations/
cooldowns/outcomes per experiment; share data without delaying
approved operation. **Decision**: Agreed. **Authorization**: Not
authorized. **Implementation**: Partially implemented — the
**historical replay** stage exists and was exercised (Task 115/116,
`talonx_research/replay_engine.py`, `S2-05`/`S2-06`'s evidence); an
**internal live shadow** stage (running a candidate against live data
in parallel, unpromoted) was **not confirmed** to exist this session —
`talonx_research/`'s own scope, beyond the replay engine, was not
re-audited in full this pass. **Validation**: Code inspection (replay
engine confirmed; live-shadow stage not assessed). **Dependencies**:
`S3-16`/`S3-17` depend on this stage existing to be meaningful.

## S3-16 — Equivalent comparison assumptions

**Requirement**: historical baseline/candidate comparisons use
equivalent data/capital/cost/pricing; live comparisons use an
equivalently-initialized baseline shadow account, not an established
account with unmatched positions. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Not assessed in
this documentation pass — verifying this requires tracing a specific
past or hypothetical comparison's exact inputs, not performed this
session. **Validation**: Not assessed in this documentation pass.
**Dependencies**: `S3-15`'s live-shadow stage (unconfirmed) is a
precondition for the live-comparison half of this requirement.

## S3-17 — Evaluation criteria set in advance; failed experiments preserved

**Requirement**: evaluation criteria defined before inspecting
results; failed experiments preserved and variant count retained;
unseen periods used where feasible; EOD is an interim report for
multi-day experiments, not final acceptance. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Not assessed in
this documentation pass — this is a process discipline that would need
to be traced through an actual past experiment's own artifacts (e.g.
Task 115/116's own prereg/evidence files) to confirm; not done this
session. **Validation**: Not assessed in this documentation pass (a
partial precedent: Task 107B/109's insider-cluster candidate was
"prereg frozen before outcomes" per this project's memory of that
task, suggesting the discipline has been followed before — not
re-verified here). **Dependencies**: `S3-26` (detailed criteria/
evidence-sufficiency discussion, deferred to Session 12).

## S3-18 — Promotion carries config+evidence+time; existing positions keep prior rules

**Requirement**: a promoted version carries its configuration,
evidence and effective time together; existing positions retain the
rules/version under which they were opened; rollback and historical
attribution preserved; parameter experiments vs. signal/entry/exit
semantic changes are distinguished. **Decision**: Agreed.
**Authorization**: Not authorized. **Implementation**: Partially
implemented — `talonx_research/`'s `StrategyVersion`/
`StrategyRegistry` are explicitly **immutable** (this project's
established Task 115/116 governance, `docs/STRATEGY_LIFECYCLE.md`'s
R1-R7 rules) — a strong structural match for "existing positions keep
their version's rules" and "rollback/attribution preserved." Whether a
**live promotion** (as opposed to a research-registry entry) has ever
been exercised, and whether it correctly distinguishes a parameter
tweak from a signal/entry/exit logic change in practice, is **not
assessed** this session. **Validation**: Code inspection
(`talonx_research/`, `docs/STRATEGY_LIFECYCLE.md`, established;
live-promotion exercise not assessed). **Dependencies**: `S3-15`'s
live-shadow stage.

## S3-19 — Research Lab dashboard visibility

**Requirement**: experiment identity/hypothesis/params, baseline/
candidate versions, replay-vs-live-shadow mode, opportunity/rejection/
non-execution records, positions/net results/drawdown/exposure, data
limitations, evaluation criteria/decision history; a prominent
"EXPERIMENTAL — INTERNAL ONLY" label; no auto-promotion from a
positive metric. **Decision**: Agreed. **Authorization**: Not
authorized. **Implementation**: Not implemented — a direct search of
`dashboard_web_static/index.html` for "EXPERIMENTAL" found no match;
no dedicated Research Lab dashboard section exists today.
**Validation**: Code inspection (targeted grep, this session — no
match). **Dependencies**: `S3-15` (the workflow this dashboard would
surface).

## S3-20 — 2-year replay desired, not verified; no experiment authorized here

**Requirement**: reaffirms `S2-06` — a 2-year replay window remains
desired, not a verified capability; no experiment or profitability
claim is authorized by this documentation. **Decision**: Agreed.
**Authorization**: Explicitly not authorized (no new experiment).
**Implementation**: Not implemented — correctly so; nothing was built
or claimed. **Validation**: Code inspection / natural live behavior
(no new experiment artifact created this session, same confirmation as
`S2-15`). **Dependencies**: `S3-27` (exact data-feasibility question,
deferred to Session 5).

## S3-21 — Optional internal research Telegram bot

**Requirement**: experiments never send to the main feed; MAY use a
separate internal research bot with OFF(default)/SUMMARY/DETAILED
modes, explicit enablement, clearly experimental wording, separate
credentials/destination, no fallback to the main bot, and correlation
scoped by bot+chat+message identity. **Decision**: Agreed.
**Authorization**: Explicitly not authorized — "No bot creation,
credential entry, destination selection, or message sending is
authorized by this task." **Implementation**: Not implemented — no
second bot configuration exists in the codebase inspected this
session; the existing Experimental-send boundary
(`talonx_ops/external_boundary.py`'s 3-condition gate, this project's
established history) currently means Experimental sends nowhere
external at all, which this requirement explicitly refines (adds an
opt-in internal channel) rather than contradicts. **Validation**: Code
inspection (targeted search for a second bot/research-bot
configuration, this session — no match; `external_boundary.py`'s
existing gate confirmed present by name only, not re-read line-by-line
this session). **Dependencies**: none blocking to design.

## S3-22 — User-facing display names

**Requirement**: the approved display-name table (Intraday
Opportunities, Insider Buying Strategy, Company Developments, Virtual
Portfolio, Stock Coverage, System Health, Research Lab); "Multi-Day" as
a horizon category; "Fundamental Opportunities" provisional; internal
IDs/database/module names preserved — display naming is not rename
authorization. **Decision**: Agreed. **Authorization**: Explicitly not
authorized (no technical rename). **Implementation**: Not implemented
— these are new display-layer names; no renaming of internal
identifiers occurred or is planned by this entry. **Validation**: Code
inspection (this session confirms no rename was made — `git diff`
touches only `docs/`). **Dependencies**: `S3-24` (Original's long-term
path review) gates "Fundamental Opportunities" specifically.

## S3-23 — Conditional database-reset permission

**Requirement**: a clean database/campaign reset MAY be used during a
**separately authorized implementation**, if necessary for
compatibility or trustworthy accounting, following a 9-step required
approach (identify/preserve-backups/prefer-migration/version-if-reset-
needed/limit-scope/preserve-dedup-or-set-cutoff/reconcile-obligations-
first/never-fabricate-or-abandon/explain-the-choice). **Decision**:
Agreed. **Authorization**: Not authorized *now*; conditionally
pre-authorized for a **future** task that (a) is itself separately
authorized to implement something requiring it, and (b) follows the
9-step approach and reports against it — this documentation task
performs no reset and authorizes none today. **Implementation**: Not
implemented (no reset performed; nothing to implement from a
permission-policy entry itself). **Validation**: N/A — a policy
record, not a technical claim to verify. **Dependencies**: this policy
updates, and should be read together with, the EOD closure task's
earlier absolute-preservation instruction
(`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md`'s originating prompt) and `S3-14` (existing
campaigns not overwritten *by this session*).

## S3-24 — Deferred: Original's long-term/fundamentals path review

**Requirement**: inspect Original's older fundamentals/long-term
path's role before deciding whether to retain, adapt, or retire it —
no activation/deactivation now. **Decision**: Open — deferred.
**Authorization**: N/A. **Implementation**: N/A. **Validation**: N/A.
**Reason**: "Fundamental Opportunities" naming is provisional on this
review; the path itself was not inspected this session. **Planned
session**: a future session covering Original's non-intraday path
(candidate: extending Session 6, or a new dedicated session — not
decided). **Dependency**: direct code/data inspection of Original's
long-term lane, not yet performed.

## S3-25 — Deferred: cross-strategy capital/exposure enforcement policy

**Requirement**: `S3-13`'s combined-exposure **display** is agreed now;
any **enforcement** policy (e.g. a cross-strategy exposure cap) is
deferred. **Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: enforcement
needs its own risk discussion, not assumed alongside the display
feature. **Planned session**: Session 10 (Paper accounting, costs and
risk). **Dependency**: `S3-13`'s display feature existing first.

## S3-26 — Deferred: experiment evaluation criteria and evidence sufficiency

**Requirement**: detailed experiment evaluation criteria and what
counts as sufficient evidence, deferred until a validation session,
before any experiment is authorized. **Decision**: Open — deferred.
**Authorization**: N/A. **Implementation**: N/A. **Validation**: N/A.
**Reason**: needs its own criteria-definition discussion. **Planned
session**: Session 12 (Technical validation, usefulness and economic
evidence). **Dependency**: none blocking; a prerequisite for any
future experiment authorization.

## S3-27 — Deferred: exact 2-year historical data feasibility

**Requirement**: whether a genuine, current 2-year-to-today replay
window is actually data-feasible (as opposed to the existing bounded
2024-09-01→2026-03-31 window). **Decision**: Open — deferred.
**Authorization**: N/A. **Implementation**: N/A. **Validation**: N/A.
**Reason**: needs a dedicated data-coverage audit. **Planned session**:
Session 5 (Data sources, discovery and coverage). **Dependency**:
none blocking.

**Session 5 update (2026-09-16)**: Session 5 detailed this deferral
into five explicit sub-questions (data availability, granularity,
point-in-time universe/identity, corporate actions, licensing — see
`S5-31`) rather than resolving it. **Decision status unchanged**: still
`Open — deferred`; no destination session has been assigned for the
actual audit itself yet (Session 5 was the discussion *about* the
question, not the audit).

## S3-28 — Deferred: remaining lifecycle semantics (mute, pending intents on pause)

**Requirement**: exact mute controls and the handling of already-
committed, unfilled intents when a stock is paused. **Decision**: Open
— deferred. **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: needs the full user-journey mapping
first — no cancellation semantics are invented in advance of that
discussion. **Planned session**: Session 4 (End-to-end user journey)
and/or Session 11 (Operation, stop/start and recovery). **Dependency**:
`S3-11`'s Pause/Exclude/Mute definitions (agreed this session) as the
starting point.

---

# Session 4 requirements (S4-01 through S4-14)

Compact format (same five fields per entry), per `DECISION_LOG.md`
Session 4.

## S4-01 — One "Start monitoring" action using saved settings

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `python -m
talonx_ops.prospective start` is already a single operator command
using persisted `.env` configuration, but it starts the stack as a
whole rather than gating on per-strategy readiness (`S4-02`).
**Validation**: Code inspection (`talonx_ops/prospective/`, this
session). **Dependency**: `S4-02`.

## S4-02 — Resume strategies only when prerequisites pass; readiness exposed

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no per-strategy readiness gate
or shared-dependency-failure surface was found; today's start either
brings the whole stack up or it doesn't. **Validation**: Code
inspection (this session). **Dependency**: `S3-05`'s independent-
strategy target architecture.

## S4-03 — Recover obligations before new discovery; no chronological-accounting change

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — this
requires tracing each of Original/Intelligence/V2's own startup
sequences end-to-end and comparing their obligation-recovery-vs-
discovery ordering, not performed this session. **Validation**: Not
assessed in this documentation pass. **Dependency**: none blocking to
design.

## S4-04 — Preserve campaign balances/positions/reservations/exit rules across restart

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — directly confirmed by this project's
own EOD closure evidence (`docs/research/evidence/
eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md`): V2's cash/positions
and Original's lane balances were unchanged across the graceful
shutdown, and no reset occurred. **Validation**: Natural live behavior
(2026-09-15 EOD closure). **Dependency**: none.

## S4-05 — Catch-up ingestion must not create late prospective entries or stale alerts

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing Intelligence's backfill/poller code against its own alert-
emission path specifically for this guarantee, not performed this
session. **Validation**: Not assessed in this documentation pass.
**Dependency**: `S5-28` (durable checkpoints, no fixed completeness
assumption) is the closest related, already-partially-implemented
mechanism.

## S4-06 — Primary Telegram bot scope

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Implemented for opportunities and
optional major-development alerts (established, `S1-01`/`S1-02`'s
evidence); explicit "lifecycle update" messages (entry/exit/expiry
notifications specifically, as their own message type) were **not**
separately confirmed this session. **Validation**: Code inspection
(established + this session). **Dependency**: `S4-11` (explicit
lifecycle states) as the underlying state model such updates would
draw from.

## S4-07 — Separate Operations bot

**Decision**: Agreed. **Authorization**: Explicitly not authorized (no
bot creation). **Implementation**: Not implemented — a targeted search
for a second, operations-specific Telegram bot configuration found
none. **Validation**: Code inspection (this session). **Dependency**:
none blocking to design.

## S4-08 — Optional Research bot isolated, OFF by default

**Decision**: Agreed (reaffirms `S3-21`). **Authorization**:
Explicitly not authorized. **Implementation**: Not implemented — same
finding as `S3-21`, now positioned as the third of three distinct bot
channels. **Validation**: Code inspection (this session).
**Dependency**: `S3-21`.

## S4-09 — Bot infrastructure requires separate authorization; no premature "existing" claims

**Decision**: Agreed. **Authorization**: Explicitly not authorized.
**Implementation**: Implemented, in the narrow sense that this
documentation itself complies — nowhere in `PRODUCT_DEFINITION.md`,
`DECISION_LOG.md`, or this tracker is the Operations/Research bot
described as an existing, working feature. **Validation**: Code
inspection (self-check of this session's own output). **Dependency**:
none.

## S4-10 — Paper execution automatic, independent of notification success

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — V2's entry/exit code path
(`talonx_v2/paper.py`) commits the position/cash/trade atomically
inside `store.transaction()` with no dependency on delivery; delivery
is a separate outbox mechanism (`DeliveryOutbox`, this project's
established Task 96F/138/140 work) that can independently succeed,
fail, or stay `PENDING`/`AMBIGUOUS` without touching the execution
record. **Validation**: Code inspection (`talonx_v2/paper.py`, this
session, confirming execution and delivery are architecturally
separate). **Dependency**: none.

## S4-11 — Explicit lifecycle states with separate missing-price/valuation modifiers

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — V2 already distinguishes
`FAILED_NO_MARKET_DATA` (missing price) from `SKIPPED_ENTRY_STALE`
(staleness) as separate internal dispositions
(`talonx_v2/service.py:555-571,612-618`), a real precedent for keeping
these two axes separate; none of this is yet surfaced to the operator
as an explicit lifecycle-state display. **Validation**: Code
inspection (this session). **Dependency**: `S5-16` (the product-level
`EXPIRED_NO_MARKET_DATA` naming this internal code would need to
adopt or map to).

## S4-12 — Pausing new entries atomically cancels unfilled intents

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — `pending_entry_intents` rows
transition status only via fill/expiry logic
(`talonx_v2/store.py:515-533`); no atomic "cancel all unfilled intents
for this symbol/strategy on pause" operation was found. **Validation**:
Code inspection (this session). **Dependency**: `S3-11` (Pause
definition) and `S3-28` (deferred pending-intent-on-pause semantics) —
this requirement sharpens that deferral into a specific atomicity
guarantee, still not implemented.

## S4-13 — EOD reports daily performance, open risk, unresolved obligations

**Decision**: Agreed (extends `S2-07`). **Authorization**: Not
authorized (pre-existing). **Implementation**: Implemented — see
`S2-07`'s evidence (`talonx_ops/paper_performance.py`,
`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md`); this entry additionally confirms EOD already
surfaces "open risk" (unrealized P&L, open positions) and unresolved
obligations (`EXIT_UNRESOLVED`, `AMBIGUOUS` outbox rows) as part of the
same reconciliation. **Validation**: Code inspection + natural live
behavior (established, 2026-09-15 EOD closure). **Dependency**: none.

## S4-14 — Outage detection and alert dedup are future work

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — a real, working
single-owner Telegram-poller dedup mechanism exists and was directly
observed this project's history (`telegram_get_updates_owners: 1`,
`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §4) and `talonx_ops/official_dispatch.py`/
`dashboard_read.py` contain dedup-related logic; a broader,
**independent outage-detection** capability (detecting a silent
failure, not just deduplicating a known message stream) was **not**
confirmed to exist as its own feature this session. **Validation**:
Code inspection (this session, targeted search). **Dependency**: none
blocking; this entry's own point is that the claim must stay honest,
not that a specific fix is owed.

---

# Session 5 requirements (S5-01 through S5-31)

Compact format, per `DECISION_LOG.md` Session 5, grouped A–E as
discussed.

## S5-01 — One master security registry with per-strategy/horizon eligibility

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — extends `S3-08`'s finding
(three separate, unmerged lists exist: Original's watchlist,
Intelligence's collection scope, V2's execution scope). **Validation**:
Code inspection (this session). **Dependency**: `S5-02`-`S5-06` define
the registry's data model.

## S5-02 — CIK identifies issuer, not security/class; distinct identity/symbol-history/price-series tracking

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no code found this session
tracking security identity, symbol history, and price-series identity
as three distinct, linked concepts; Intelligence's own scope/watchlist
code (`talonx_ingest/intelligence/service/scope.py`,
`watchlist_source.py`) operates on CIK/symbol pairs without this finer
distinction. **Validation**: Code inspection (this session).
**Dependency**: `S5-01`.

## S5-03 — Daily bulk refresh + bounded event-triggered checks; retain last-verified snapshot on failure

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented as described — Intelligence's
existing scope refresh (Task 96B's `scope`/`backfill`/`poller`
modules, this project's history) refreshes on its own cadence, but
whether it specifically retains a "last verified snapshot" with
explicit freshness disclosure on failure was **not confirmed** this
session. **Validation**: Not assessed in this documentation pass (full
implementation) / Code inspection (existence of a refresh mechanism at
all, established). **Dependency**: `S5-01`.

## S5-04 — Preserve immutable historical versions/observed timestamps/verified effective dates

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no registry exists yet to
version (`S5-01`). **Validation**: Code inspection (this session — N/A
finding). **Dependency**: `S5-01`, `S5-03`.

## S5-05 — Unknown/ambiguous identity blocks only affected admissions

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no registry to test this
isolation property against yet. **Validation**: Code inspection (this
session). **Dependency**: `S5-01`.

## S5-06 — Registry refresh does not auto-expand approved universes

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: N/A — no registry exists yet; this is a constraint
recorded in advance of building one. **Validation**: Code inspection
(this session). **Dependency**: `S5-01`.

## S5-07 — Coverage-count accuracy (27/599 not adopted; actual counts dated)

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented in this documentation itself — see
`DECISION_LOG.md` Session 5 §A for the three dated, cited counts
(Original 43/48 active, 39 SEC-covered; Intelligence 569; V2 626) and
the explicit statement that no evidence for 27/599 was found.
**Validation**: Code inspection (`docs/OPERATIONS.md:69`, `docs/
research/evidence/task140/gated_admission_activation.md:52`,
`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §4, all read this session). **Dependency**:
none.

## S5-08 — One primary provider/feed/opening-reference/adjustment basis per strategy version

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — V2's `"csv"` pricing mode
is a real, single, version-scoped provider definition
(`talonx_v2/config.py`/`service.py`), but it is not yet formalized as
an explicit, documented "data-contract version" object as this
requirement describes, and (per `OPS-002`) its own freshness telemetry
is incomplete. **Validation**: Code inspection (established, `OPS-002`
+ this session). **Dependency**: `OPS-005`.

## S5-09 — Official auction price ≠ provider daily-bar open

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
comparing V2's actual entry-price source against a genuine official-
auction reference, not performed this session. **Validation**: Not
assessed in this documentation pass. **Dependency**: `S5-08`.

## S5-10 — Provider selection + free-tier feasibility remain OPEN

**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: needs
dedicated data-provider research. **Planned session**: not assigned;
candidate is a dedicated technical task once Session 6 clarifies
strategy-specific needs. **Dependency**: `OPS-005`.

## S5-11 — No midday-price substitution/unvalidated fallback

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — `CsvBarAdapter.session()` returns
`None` (never substitutes a different time-of-day or provider's price)
for a missing date, confirmed during the 2026-09-15 EOD closure and
`OPS-002`. **Validation**: Code inspection (established, `OPS-002`).
**Dependency**: none.

## S5-12 — Preserve source/receipt/processing/notification timestamps separately

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing a specific event's full timestamp lineage through ingestion,
processing and delivery, not performed this session. **Validation**:
Not assessed in this documentation pass. **Dependency**: none
blocking.

## S5-13 — 3-session recovery: target entry = Session 1, ends at exchange-calendar close of Session 3

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: ~~Implemented — `max_entry_staleness_sessions = 3`
(`talonx_v2/config.py:72`) combined with the calendar-aware
`add_sessions()` (`talonx_v2/calendar.py:88`, driving the staleness
cutoff in `service.py:377-381`) matches this semantics exactly.~~
**Superseded, see correction below.** **Validation**: Code inspection
(this session, direct read of the cited lines). **Dependency**:
`S5-19` (exact equality-at-deadline detail still open).

**Correction (2026-09-16, ~14:03 UTC)**: the original "Implemented"
verdict above was **unsupported** — it verified that a session-based
mechanism exists, not that it produces the exact agreed boundary. Full
re-inspection found **two different deadline computations for the same
`max_entry_staleness_sessions=3` parameter**: the general
entry-attempt eligibility gate (`service.py:377-381`, `stale_cut =
ripe_through - 3`) stays open through `eligible_entry_session + 3`
sessions — a **4-session** window — while the missing-price
retry-then-release path's own deadline (`service.py:546-547`,
`retry_deadline = add_sessions(eligible_entry_session,
max_entry_staleness_sessions - 1)`) is `eligible_entry_session + 2`
sessions — a **3-session** window matching the agreed "ends at Session
3" framing. These two boundaries are one session apart, confirmed by
the code's own inline comment describing the gap as deliberate. A
genuine entry fill remains possible through the wider, 4-session
window if a price happens to become available that late — one session
beyond the agreed policy. **Corrected classification: "Partially
implemented — session-based recovery exists; exact Session-3-close
enforcement and pre-fill expiry remain pending `OPS-003`."** No code
was changed; `S5-19`'s own open equality-at-deadline question is left
unresolved by this correction. See `OPERATIONAL_FINDINGS.md` `OPS-003`
for the complete finding, and `DECISION_LOG.md`'s dated "Documentation
correction" note under Session 5 for the full narrative.

## S5-14 — Only timely, durably admitted intents reconcile; check expiry before fill

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: ~~Implemented — `service.py`'s retry-then-expire
ordering (`retry_deadline` checked before any fill attempt,
`service.py:546-571`) matches this.~~ **Superseded, see correction
below.** **Validation**: Code inspection (this session). **Dependency**:
none.

**Correction (2026-09-16, ~14:03 UTC)**: direct re-inspection of
`_phase_open` (`service.py:504-548`) found the **opposite ordering**
from what was originally reported: `pipeline.process_episode(...)`
(the actual fill attempt) runs **unconditionally first**, for every
episode not already excluded by the coarser staleness gate; the
`retry_deadline` comparison is evaluated **only reactively**, after a
`NO_ENTRY_BAR` miss has already been returned by that same attempt —
never before it. A successful fill is not gated by `retry_deadline` at
all. "Check expiry before attempting a fill" is therefore **not**
correctly implemented as stated — admission-timeliness itself
(whether the intent is durable and was created in time) is correctly
enforced elsewhere, but the specific attempt-vs-check ordering is
inverted from the agreed policy. **Corrected classification:
"Partially implemented — the admission/durability check is real; the
pre-fill expiry check is not."** Tracked under `OPS-003`. No code was
changed.

## S5-15 — Downtime/identity/corp-action delays do not extend the deadline

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the deadline itself is a
fixed calendar computation independent of process uptime (confirmed);
the corporate-action-delay interaction specifically is **not
assessed**, since no corporate-action code exists at all (`OPS-004`).
**Validation**: Code inspection (this session, deadline computation
only). **Dependency**: `OPS-004`.

**Correction note (2026-09-16, ~14:03 UTC) — reaffirmed, not
downgraded**: the 2026-09-16 correction pass re-confirmed the
"restart does not extend the deadline" half of this requirement is
genuinely correct — both of `S5-13`'s two (now-disclosed) deadline
computations are pure functions of the episode's fixed
`eligible_entry_session` and the calendar's static session list,
consulting no process-uptime or last-run state. This sub-claim is
**not** affected by `S5-13`/`S5-14`'s correction, per this task's own
instruction not to downgrade independently demonstrated behavior.

## S5-16 — Missing-price expiry = EXPIRED_NO_MARKET_DATA at product level

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the internal code's actual
disposition name is `FAILED_NO_MARKET_DATA` (`service.py:555-571`),
not `EXPIRED_NO_MARKET_DATA` — functionally equivalent, differently
named; no distinct identity/corporate-action expiry reason exists
since no corporate-action code exists (`OPS-004`). **Validation**:
Code inspection (this session). **Dependency**: `OPS-004`.

**Correction note (2026-09-16, ~14:03 UTC) — clarified**: the
2026-09-16 pass found `FAILED_NO_MARKET_DATA` and `EXPIRED_STALE` are
in fact **two distinct** internal dispositions (not one generic
"expired"), which is a stronger partial match for this requirement's
"preserve distinct reasons" intent than previously credited — see
`OPS-003`. The product-level `EXPIRED_NO_MARKET_DATA` naming itself is
still not surfaced anywhere operator-facing; verdict unchanged
(`Partially implemented`).

## S5-17 — Release reservations exactly once, no invented cash credit

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — established reservation-lifecycle
work from this project's Task 140 history (reservation-expiry-exactly-
once). **Validation**: Code inspection (established). **Dependency**:
none.

**Correction note (2026-09-16, ~14:03 UTC) — reaffirmed with stronger
evidence, not downgraded**: this pass found the exactly-once guarantee
is enforced by a single, shared, structural SQL guard in
`V2Store.mark_entry_intent` (`WHERE intent_id=? AND status='PENDING'`,
`talonx_v2/store.py:526-536`), used by **every** terminal release path
alike (`EXPIRED_STALE`, `FAILED_NO_MARKET_DATA`, and the normal
`FILLED` path) — a stronger, more structural guarantee than a
per-caller check would be. Directly confirmed by **running** (not just
reading) `tests/test_task131_nonblocking_retry.py::
test_price_still_missing_next_session_releases_intent_exactly_once`
this pass (passed). This requirement is **not** affected by `S5-13`/
`S5-14`'s correction — it remains `Implemented`.

## S5-18 — Delayed reconciliation preserves original entry-reference session; recorded-at disclosed separately

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `eligible_entry_session`
is preserved and used as the position's own timeline anchor
(`service.py`'s `target_exit = add_sessions(es, cfg.hold_trading_days)`
uses the entry session, not a later processing time); whether a
**separate, disclosed** "recorded-at" time is surfaced anywhere
operator-facing was not confirmed this session. **Validation**: Code
inspection (this session, entry-session preservation only).
**Dependency**: none blocking.

## S5-19 — Exact equality-at-deadline / receive-vs-commit semantics

**Decision**: Open — deferred (explicit implementation-acceptance
detail). **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: technical acceptance criteria, not a
product decision — needs definition before any implementation task
touching this window. **Planned session**: none (a future
implementation-acceptance task, not a knowledge-transfer session).
**Dependency**: `S5-13`.

## S5-20 — Deadline-consistency finding, recorded not corrected

**Decision**: Open — tracked as `OPS-003`. **Authorization**: N/A.
**Implementation**: N/A (no correction made). **Validation**: N/A.
**Dependency**: see `OPERATIONAL_FINDINGS.md` `OPS-003` for the full
finding (originally: Task 112R's G1 entry-session-semantics
comparison, re-verification against current code not performed at the
time).

**Extended (2026-09-16, ~14:03 UTC)**: a second, directly-confirmed
deadline-consistency finding was added to `OPS-003` this pass — the
`S5-13`/`S5-14` intra-runtime dual-deadline discrepancy (a 3-session
vs. 4-session boundary for the same parameter, plus fill-before-check
ordering), found by direct code inspection and corroborated by
executed tests, not merely recorded for future re-verification like
the original Task 112R item. **Decision status unchanged**: `Open —
tracked`; still no code correction made or authorized. See
`OPERATIONAL_FINDINGS.md` `OPS-003` for both findings side by side.

## S5-21 — Verified renames preserve identity/intent via effective-dated mappings

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no rename-handling code exists.
**Validation**: Code inspection (this session — see `OPS-004`).
**Dependency**: `S5-01` (a registry to attach effective-dated mappings
to).

## S5-22 — Before-entry splits use post-split entry basis

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no split-handling code exists.
**Validation**: Code inspection (this session — `OPS-004`).
**Dependency**: `OPS-004`.

## S5-23 — After-target-entry splits require chronological reconstruction, exactly once

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented. **Validation**: Code inspection
(this session — `OPS-004`). **Dependency**: `S5-18` (delayed-
reconciliation timeline preservation), `OPS-004`.

## S5-24 — Unverified changes block execution without discarding obligations

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no corporate-action verification
gate exists to block on. **Validation**: Code inspection (this session
— `OPS-004`). **Dependency**: `OPS-004`.

## S5-25 — Mergers/replacement securities require explicitly supported treatment

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented. **Validation**: Code inspection
(this session — `OPS-004`). **Dependency**: `OPS-004`.

## S5-26 — Truncate+cash-in-lieu policy; proportional cost basis; CORP_ACTION_CASH treatment

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — none of this accounting
treatment exists in code today. **Validation**: Code inspection (this
session — targeted search for split/merger/cash-in-lieu handling,
`OPS-004`). **Dependency**: `OPS-004`.

## S5-27 — Decimal arithmetic; cents/4-decimal display; no intermediate truncation

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — auditing
V2's/Original's actual numeric types (whether `Decimal` or `float` is
used internally today) was not performed this session. **Validation**:
Not assessed in this documentation pass. **Dependency**: none
blocking to state the policy; blocking to verify compliance.

## S5-28 — Durable checkpoints + overlap/dedup + recoverable enrichment state; no fixed 16-hour assumption

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — Intelligence's
established `scope`/`backfill`/`poller`/enrichment modules (Task 96B,
this project's history) already implement durable checkpointing and
recoverable state; a targeted search this session for a "16-hour"
completeness assumption anywhere in the codebase or docs found none —
there is nothing matching that figure to remove. **Validation**: Code
inspection (this session, targeted search + established Task 96B
evidence). **Dependency**: none.

## S5-29 — Prioritize obligations/timely intents over bulk historical work

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing actual scheduling/priority logic across ingestion and
execution, not performed this session. **Validation**: Not assessed in
this documentation pass. **Dependency**: none blocking.

## S5-30 — Pre-market lockout window PROPOSED/UNDEFINED

**Decision**: Open — deferred (explicitly not agreed).
**Authorization**: N/A. **Implementation**: N/A. **Validation**: N/A.
**Reason**: no specific window was agreed; recorded as undefined, not
defaulted. **Planned session**: Session 9 (Telegram and dashboard
experience) or Session 11 (Operation, stop/start and recovery) —
candidate, not decided. **Dependency**: none blocking.

## S5-31 — 2-year replay feasibility remains OPEN (5 sub-questions)

**Decision**: Open — deferred (extends `S3-27`). **Authorization**:
N/A. **Implementation**: N/A. **Validation**: N/A. **Reason**: data
availability, granularity, point-in-time universe/identity, corporate
actions, and licensing all need independent evidence — none resolved
this session. **Planned session**: not assigned (candidate: Session 12
or a dedicated data-engineering task). **Dependency**: `OPS-004`
(corporate-action question specifically overlaps).
