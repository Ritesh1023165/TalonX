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
| S3-12 | New-campaign defaults: $100,000 cash, $10,000 allocation, configurable, no inflation/forced entry | Agreed | Not authorized | Implemented (V2Config default $100,000 / $10,000; seeded once by RI-1; existing legacy campaign untouched) | Code inspection (this session); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
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
| S3-25 | Deferred: cross-strategy capital/exposure ENFORCEMENT policy (display resolved Agreed via S10-14; numerical limits split to S10-23/24/25) | Open — deferred (enforcement only) | N/A | N/A | N/A |
| S3-26 | Deferred: detailed experiment evaluation criteria/evidence sufficiency | Open — deferred | N/A | N/A | N/A |
| S3-27 | Deferred: exact 2-year historical data feasibility | Open — deferred | N/A | N/A | N/A |
| S3-28 | Deferred: remaining lifecycle semantics (mute controls, pending intents on pause) | Open — deferred | N/A | N/A | N/A |
| S4-01 | One "Start monitoring" action using saved settings | Agreed | Not authorized | Partially implemented (single-command start exists; no per-strategy readiness gate) | Code inspection (this session) |
| S4-02 | Resume enabled strategies only when prerequisites pass; per-strategy + shared-dependency readiness exposed | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S4-03 | Recover obligations/pending intents before new discovery; no chronological-accounting change; no later-funds-earlier | Agreed | Not authorized | Not assessed in this documentation pass (cross-system ordering not traced) | Not assessed in this documentation pass |
| S4-04 | Preserve campaign balances/positions/reservations/exit rules across start/stop | Agreed | Not authorized | Implemented (established, EOD closure evidence) | Natural live behavior (established) |
| S4-05 | Catch-up ingestion must not create late prospective entries or stale "act now" alerts | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S4-06 | Primary Telegram bot: opportunities, lifecycle updates, optional major-dev | Agreed | Not authorized (pre-existing, partial) | Implemented (opportunities/major-dev); lifecycle-update coverage not assessed | Code inspection (established + this session) |
| S4-07 | Separate Operations bot for incidents/recovery notifications | Agreed | Explicitly not authorized (no bot creation) | Implemented (Sentinel = OPERATIONS destination, durable ops outbox, RI-2; destination validated RI-4) | Code inspection (this session); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S4-08 | Optional Research bot isolated, OFF by default | Agreed (reaffirms S3-21) | Explicitly not authorized | Implemented as OFF (RESEARCH/Lab: double opt-in, no fallback; release gate `lab_off` check) | Code inspection (this session); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
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
| S5-08 | Each strategy/data-contract version defines one primary provider/feed/opening-reference/adjustment basis | Agreed | Not authorized | **Implemented (PQ-2B, V2 release mode)** — `V2_RELEASE_PRICE_CONTRACT@1`: Alpaca SIP daily bars, adjustment=split, OPEN = provider first-eligible-trade daily open (explicitly NOT the official auction print), CLOSE = official closing cross, fallback NONE; opt-in `--pricing-mode sip`, not activated | Code inspection (this session); PQ-2B evidence |
| S5-09 | Official auction price ≠ provider daily-bar open | Agreed | Not authorized | Implemented (PQ-2B: entry OPEN = SIP daily `o` = provider FIRST ELIGIBLE TRADE, NOT the official opening-auction print; disclosed in alerts and docs) | Not assessed in this documentation pass; final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S5-10 | Provider selection + free-tier feasibility remain OPEN | Open — deferred | N/A | Resolved for first release (Alpaca SIP daily, split-only; free-tier rate-limit stress NOT measured -> bounded follow-up under OPS-005) | N/A; final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S5-11 | No midday-price substitution/unvalidated fallback; qualified fallback is future work | Agreed | Not authorized | Implemented (CsvBarAdapter returns None, never substitutes — see OPS-002) | Code inspection (established, OPS-002) |
| S5-12 | Preserve source/first-receipt/processing/notification timestamps separately; batch timestamps ≠ observation evidence | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S5-13 | 3-session recovery: target entry = Session 1; recovery ends at exchange-calendar close of Session 3 | Agreed | Authorized and implemented (Package 3) | Implemented (Package 3, OPS-003 Finding B CLOSED — `calendar.session_close_utc()` real official close incl. early closes; `V2Service._recovery_deadline_session()`/`_recovery_deadline_passed()` unify the previously-divergent 4-session/3-session boundaries to the agreed Session-3 boundary) | Isolated test execution (`tests/test_package3_pricing_timing.py`, P3-D tests, 19 total incl. weekend/holiday/early-close/live-close-boundary) |
| S5-14 | Only timely, durably admitted intents reconcile; check expiry before fill | Agreed | Authorized and implemented (Package 3) | Implemented (Package 3) — the recovery deadline is now checked PROACTIVELY inside `_phase_open()`, before any fill attempt, not only reactively after a miss | Code inspection + isolated test execution (`tests/test_package3_pricing_timing.py::test_p3d_pending_intent_released_not_left_zombie_after_deadline`) |
| S5-15 | Downtime/identity/corp-action delays do not extend the deadline | Agreed | Not authorized | Partially implemented — **downtime does not extend the deadline, confirmed** (deadline is a pure function of calendar dates, independent of process uptime); corp-action-delay interaction not assessed, no corp-action code exists (`OPS-004`) | Code inspection (this session) |
| S5-16 | Missing-price expiry = EXPIRED_NO_MARKET_DATA at product level; distinct identity/corp-action reasons preserved | Agreed | Not authorized | Partially implemented (internal code uses `FAILED_NO_MARKET_DATA`/`EXPIRED_STALE` as two distinct dispositions, not one; product-level `EXPIRED_NO_MARKET_DATA` label not surfaced; no corp-action reason exists — `OPS-004`) | Code inspection (this session) |
| S5-17 | Release reservations exactly once, no invented cash credit | Agreed | Not authorized (pre-existing) | Implemented — confirmed by a shared, structural SQL guard (`WHERE intent_id=? AND status='PENDING'`) backing every release path | Code inspection (`talonx_v2/store.py:526-536`, this session) + isolated test execution (`test_price_still_missing_next_session_releases_intent_exactly_once`, passed) |
| S5-18 | Delayed reconciliation preserves original entry-reference session/exit schedule; recorded-at disclosed separately | Agreed | Not authorized | Partially implemented (entry-session preservation confirmed; separate recorded-at disclosure not assessed) | Code inspection (this session) |
| S5-19 | Exact equality-at-deadline / receive-vs-commit semantics — explicit open acceptance detail | Open — deferred | N/A | N/A | N/A — **left unresolved by the 2026-09-16 correction pass**, per its own instruction not to choose this semantics |
| S5-20 | Deadline-consistency finding recorded for re-verification, not corrected here | Open — tracked (`OPS-003`, extended 2026-09-16 with a directly-confirmed intra-runtime dual-deadline discrepancy, in addition to the original Task 112R cross-methodology finding) | N/A | N/A | N/A |
| S5-21 | Verified renames preserve identity/intent via effective-dated mappings | Agreed | Not authorized | Not implemented | Code inspection (this session — OPS-004) |
| S5-22 | Before-entry splits use post-split entry basis | Agreed | Not authorized | **Partially implemented (PQ-2A, V2 only)** — a split whose ex-date precedes the entry price's provider basis date is recorded `REFLECTED_IN_ENTRY_BASIS` (no share change); ex-date == basis date or unknown basis fails closed | Code inspection (this session — OPS-004); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S5-23 | After-target-entry splits require chronological reconstruction, transactional, exactly once | Agreed | Not authorized | **Partially implemented (PQ-2A, V2 only)** — split applied to economic shares transactionally, exactly once (content-keyed, append-only trail), chronologically by ex-date; unit-tested incl. restart/duplicate-event | Code inspection (this session — OPS-004); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S5-24 | Unverified changes block execution without discarding obligations | Agreed | Not authorized | **Partially implemented (PQ-2A, V2 only)** — unavailable/conflicting/unsupported/unknown-basis evidence holds inside the +5 window or moves to EXIT_UNRESOLVED (capacity + account block retained); obligations never discarded | Code inspection (this session — OPS-004); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S5-25 | Mergers/replacement securities require explicitly supported treatment | Agreed | Not authorized | **Fail-closed only (PQ-2A, V2)** — mergers/spin-offs/renames/unit splits/stock dividends are DETECTED (Alpaca action classes) and block settlement; no supported treatment exists | Code inspection (this session — OPS-004); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S5-26 | **REVISED (PQ-2A closure, gatekeeper decision): V2 paper accounting keeps EXACT fractional economic entitlement after a corporate action (5 sh x 1:10 reverse split = 0.5 sh); NO truncate, NO round-up, NO fabricated cash-in-lieu; NEW entries stay whole-share only (Package 4); proportional/unchanged aggregate cost basis. `CORP_ACTION_CASH` for cash-in-lieu is not modelled (no approved source of a settlement reference); ordinary cash dividends are handled by S10-17.** | Agreed (revised by gatekeeper; supersedes truncate + cash-in-lieu for V2 paper accounting) | Not authorized | **Implemented (PQ-2A + closure, V2 only)** — exact `Fraction` economic shares, append-only trail, unchanged aggregate cost, idempotent; cash-in-lieu deliberately absent | Code inspection (this session — OPS-004); PQ-2A `docs/research/evidence/provider_qualification_pq2a/`; PQ-2A closure `docs/research/evidence/provider_qualification_pq2a_closure/`; `tests/test_pq2a_closure_dividends.py::test_02_to_05_*` |
| S5-27 | Decimal arithmetic internally; cents/4-decimal display; no intermediate truncation; rounding mode open | Agreed | Not authorized | Partially implemented (corrected 2026-09-17 — `calculate_buy`/`calculate_sell_pnl` confirmed `float`, not `Decimal`; full surface not audited) | Code inspection (this session, `talonx_paper/engine.py:71-93`) |
| S5-28 | Durable checkpoints + overlap/dedup + recoverable enrichment state; no fixed 16-hour assumption | Agreed | Not authorized | Partially implemented (Intelligence's own checkpoint/backfill/poller exists, Task 96B; 16h-assumption search found none to remove) | Code inspection (established + this session) |
| S5-29 | Prioritize obligations/timely intents over bulk historical work | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S5-30 | Pre-market lockout window PROPOSED/UNDEFINED | Open — deferred | N/A | N/A | N/A |
| S5-31 | 2-year replay feasibility remains OPEN (5 sub-questions) | Open — deferred (extends S3-27) | N/A | N/A | N/A |
| S6-01 | Primary scope = Intraday Opportunities + V2; not implying running/validated/execution-ready | Agreed | Not authorized | Implemented (both exist and run; "primary scope" itself is a labelling decision) | Code inspection (established + this session) |
| S6-02 | Major-development notifications remain informational, not a third primary strategy | Agreed (reaffirms S1-02) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S6-03 | Fundamental Opportunities = isolated Research Lab candidate; resolves S3-24; no primary routing/activation; promotion criteria defined | Agreed | Not authorized | Not implemented (no such Research Lab candidate account exists) | Code inspection (this session) |
| S6-04 | Both intraday and multi-day remain primary scope; no demotion (reaffirms S3-01) | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S6-05 | Code P eligibility (open-market/private purchase); M=exercise/conversion; non-P doesn't qualify clusters | Agreed (inspected baseline) | Not authorized | Implemented (matches frozen V2 baseline) | Code inspection (established, Task 107B/109 history) |
| S6-06 | >=2 distinct owner CIKs; filing-date-driven window <=10 session-steps; detector at 2nd filing; greedy non-overlapping; no min amount | Agreed (inspected baseline) | Not authorized | Implemented (matches frozen V2 baseline) | Code inspection (established) |
| S6-07 | Operational liquidity screen (20-session median $5M vol, close>=$5); buyer-independence/symbol-grouping caveats; frozen wording preserved as-is | Agreed (inspected baseline) | Not authorized | Implemented (screen); gap disclosed re: frozen-wording-vs-operational-path (OPS-006 extension) | Code inspection (established) |
| S6-08 | Diagnose scarcity via full funnel; no guaranteed count/profitability claim | Agreed | Not authorized | Implemented (this documentation's own framing) | Code inspection (this session) |
| S6-09 | Intraday inspected code defaults (RSI/MACD/MA/ATR/confirmation/RRR/trend-gate/cooldown/lockout) | Agreed (inspected baseline) | Not authorized | Implemented (as code defaults; not a claim about live runtime overrides) | Code inspection (this session, talonx_quant/config.py) |
| S6-10 | RSI-recovery/confirmation interaction is documented intentional behavior, not a proven bug | Agreed (inspected baseline) | Not authorized | Implemented | Code inspection (established, Task 28 RSI-Curl/Confluence Contract) |
| S6-11 | Diagnostics distinguish 4 categories; cooldown/lockout/cash are not identical mechanisms | Agreed | Not authorized | Partially implemented (mechanisms exist distinctly in code; unified 4-category operator-facing diagnostic not confirmed) | Code inspection (this session) |
| S6-12 | Bearish observations never execute shorts/auto-close longs; legacy mappings verified separately | Agreed (reaffirms S2-01/S2-02) | Not authorized | Not assessed in this documentation pass (legacy-path exhaustive verification not performed) | Not assessed in this documentation pass |
| S6-13 | Timely opportunities stay Telegram-eligible despite capacity block; explicit skip explanation | Agreed (extends S2-03/S4-01) | Not authorized | Not implemented (no capacity-independent alert path confirmed for Original's intraday lane) | Code inspection (this session) |
| S6-14 | One expiry update; expired-but-new stays dashboard-visible; 3 distinct timestamps; no false-fresh/would-have-profited claims; flood prevention | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S6-15 | Delayed Market Simulation: separate labelled mode, chronological/causal, separate account, shares rules with replay | Agreed | Not authorized | Not implemented (no such mode exists) | Code inspection (this session) |
| S6-16 | Preserve corrected baseline: revalidation + bracket-check + no-post-spread-RRR-recheck + not-a-scheduler; reject "no revalidation" claim | Agreed (inspected baseline) | Not authorized | Implemented (accurately describes current code) | Code inspection (this session, talonx_quant/consumer.py:2017, talonx_paper/engine.py:156-186) |
| S6-17 | Approved target: approve-then-freeze, next-eligible-bar-open entry, RRR recheck at execution price, T-10 cutoff | Agreed | Not authorized | Not implemented (OPS-008) | Code inspection (this session) |
| S6-18 | Spread-adjusted entry ≠ full net-of-fees/exit-cost RRR; exact cost treatment TBD | Open — deferred (S6-25) | N/A | N/A | N/A |
| S6-19 | Market-time exit precedence; both-touched-unknown ⇒ stop-first + AMBIGUOUS_INTRABAR_ORDER (conservative, not proof) | Agreed | Not authorized | **Partially implemented** (corrected 2026-09-16 — `check_stop_take()` already applies a stop-first tiebreak at tick granularity; explicit tag/sub-bar resolution absent, OPS-009) | Code inspection (this session, `talonx_paper/engine.py:96-135`) |
| S6-20 | Stop/gap fill models; no extreme-low auto-fill; stop-market≠stop-limit; pre-entry ranges can't trigger post-entry exits; exactly-once closure | Agreed | Not authorized | **Partially implemented** (corrected 2026-09-16 — exit fills already spread-adjusted via `apply_spread`; gap/crossing distinction and exactly-once guarantee unconfirmed, OPS-009) | Code inspection (this session, `talonx_paper/consumer.py`, `config.py:99`) |
| S6-21 | Intraday EOD-flatten inspected baseline: 15:50 ET default, DST-aware not calendar-aware, no price-age check, no durable recovery state | Agreed (inspected baseline) | Not authorized | Implemented (accurately describes current code) | Code inspection (this session, talonx_paper/config.py, consumer.py) |
| S6-22 | Approved EOD-flatten target: close-10min cutoff, durable cross-restart recovery, account block, EXIT_UNRESOLVED, Operations notify-once | Agreed | Not authorized | Not implemented (OPS-007) | Code inspection (this session) |
| S6-23 | Shared recovery per-exit-type own evidence; explicit uncertainty; not applied to V2/fundamentals | Agreed | Not authorized | Not implemented (OPS-007/OPS-009) | Code inspection (this session) |
| S6-24 | Deadline equality/receipt-vs-processing semantics resolved at requirements level (resolves S5-19) | Agreed (requirements-level only) | Not authorized | Not implemented; implementation/validation tracked under OPS-003 | Code inspection (this session) |
| S6-25 | Deferred: numerical spread/slippage/fee assumptions for entry-geometry target | Open — deferred | N/A | N/A | N/A |
| S6-26 | Deferred: missing intraday entry-bar recovery duration (extends OPS-005) | Open — deferred | N/A | N/A | N/A |
| S7-01 | Primary Telegram = trading opportunities + opted-in major developments; informational, no auto-trade; routine filings dashboard-only | Agreed | Not authorized (pre-existing, partial) | Implemented | Code inspection (established) |
| S7-02 | Operations incidents + Research Lab notifications keep separate routing | Agreed (reaffirms S4-06/07/08) | Not authorized | Implemented (Sentinel OPERATIONS vs Lab RESEARCH routing separated; Lab OFF) | Code inspection (established); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S7-03 | Intraday + Insider Buying remain primary scope; no demotion revival | Agreed (reaffirms S3-01/S6-04) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S7-04 | No proposed bot/flag described as already deployed | Agreed | Not authorized | Implemented (this documentation's own framing) | Code inspection (this session, self-check) |
| S7-05 | Six-question qualification rubric; category/label alone insufficient; recognized-but-unsubstantive stays dashboard-pending | Agreed | Not authorized | Not implemented (existing gate is single-axis, not 6 distinct checks) | Code inspection (this session) |
| S7-06 | Versioned materiality-rules catalogue | Agreed | Not authorized | Not implemented (existing significance engine is a band scorer, not a routes catalogue) | Code inspection (this session) |
| S7-07 | Route 1: verified significant status change, no universal numerical threshold | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S7-08 | Route 2: measured quantitative development; comparable metrics; revision/financing context rules; debt ratios not universal thresholds | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S7-09 | Routine earnings dashboard-only unless qualifying; no forced structural catalyst; no unsupported "beat expectations"; no universal SEC-item claim | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S7-10 | Missing-reason handling; never infer misconduct/distress/price direction; "material" = policy-relevance not legal/market-impact guarantee | Agreed | Not authorized | Partially implemented (price-direction guarded via claim_safety; misconduct/distress not separately guarded) | Code inspection (this session, claim_safety.py:42) |
| S7-11 | Concise-alert content list; avoid jargon/generic labels/unsupported confidence/invented context | Agreed | Not authorized (pre-existing, partial) | Partially implemented (S1-05's jargon gap still open) | Code inspection (established, S1-05) |
| S7-12 | Development record links multiple filings/PRs/agreements; grouped by entity+transaction/topic+dates, not ticker/accession alone | Agreed | Not authorized | Not implemented (OPS-010) | Code inspection (this session, outbox.py delivery_id keying) |
| S7-13 | Duplicates/amendments enrich without new notification; distinct developments stay separate; uncertain relationships never fabricated | Agreed | Not authorized | Not implemented (OPS-010) | Code inspection (this session) |
| S7-14 | UPDATE vs CORRECTION distinction; update explains delta + links to prior; later development ≠ correction; history preserved | Agreed | Not authorized | Partially implemented (UPDATE decision type exists; CORRECTION does not) | Code inspection (this session, update_policy.py) |
| S7-15 | Four distinct timestamps kept separate; batch/DB-read/enrichment times never impersonate receipt/publication | Agreed | Not authorized | Partially implemented (mechanism exists; freshness_status UNKNOWN for 100% of persisted events per established Task140 finding) | Code inspection (established, this session) |
| S7-16 | UTC storage; explicit DST-aware display zones; no hardcoded BST; unknown times stay unknown | Agreed | Not authorized (pre-existing, partial) | Partially implemented (established UK-time discipline this session's own reporting; dashboard-wide audit not performed) | Code inspection (established) |
| S7-17 | Freshness follows source-publication time; no restart/reprocess refresh; stale-backlog-flood prevention; delayed summaries OFF by default | Agreed | Not authorized (pre-existing, partial) | Partially implemented | Code inspection (established, Task140c reclassify_pending_rows evidence) |
| S7-18 | Numerical freshness windows deferred; existing values recorded as current implementation only | Open — deferred (S7-25) | N/A | N/A | N/A |
| S7-19 | Major-dev Telegram opt-in explicit, persisted across restarts | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S7-20 | Per-stock company-event mute; doesn't suppress trades/exits/Operations; trading pause doesn't auto-pause monitoring; delayed summaries separate opt-in | Agreed | Not authorized | Not implemented (mute); Implemented (pause/monitoring separation, structural side-effect) | Code inspection (this session, render.py + S3-08/OPS-006 evidence) |
| S7-21 | Material corrections: eligible despite mutes, may repair past freshness window, must link+identify, never bypass shutdown/revocation/broadcast | Agreed | Not authorized | Not implemented (OPS-010, no CORRECTION type) | Code inspection (this session) |
| S7-22 | Distinguish qualification / delivery eligibility / delivery attempts / confirmed delivery | Agreed | Not authorized (pre-existing, partial) | Partially implemented (outbox states distinguish attempts/sent/ambiguous; full 4-way operator-facing distinction not confirmed) | Code inspection (established, this session) |
| S7-23 | 5 distinct coverage dimensions, may co-occur, none conceals another | Agreed | Not authorized | Not implemented (no unified 5-dimension surface found) | Code inspection (this session) |
| S7-24 | Empty feed ≠ nothing happened; disclose limitations; no exhaustive-coverage claim | Agreed | Not authorized | Implemented (this documentation's own framing; dashboard's own wording not audited) | Code inspection (this session, self-check) |
| S7-25 | Deferred: numerical freshness windows, requires bounded historical-filing review | Open — deferred | N/A | N/A | N/A |
| S7-26 | Deferred: event-specific quantitative materiality thresholds, requires bounded historical-filing review | Open — deferred | N/A | N/A | N/A |
| S8-01 | Startup catch-up intent valid only when admission durably committed strictly before target session's exchange-calendar open; delayed print/delivery doesn't extend deadline | Agreed | Not authorized | Implemented | Code inspection (this session, `_verify_temporal_boundary()`) |
| S8-02 | Overnight operation not required, timely completion not guaranteed; separate filing/receipt/admission timestamps; no retrospective entry | Agreed | Not authorized | Partially implemented (temporal-boundary check confirmed; distinct 3-timestamp preservation not traced end-to-end) | Code inspection (this session) |
| S8-03 | Late-discovered opportunities truthful expired/skipped status; qualification/admission/execution/delivery distinct; capacity-skipped still notify | Agreed (reaffirms S2-03/S2-04/S6-13) | Not authorized | Partially implemented (extends S6-13's own verdict) | Code inspection (established) |
| S8-04 | PENDING_ENTRY·AWAITING_PRICE reservation preserved; reconcile only target-session open, never midday/later substitute | Agreed | Not authorized | Partially implemented (mechanism real under FAILED_NO_MARKET_DATA naming, S5-16) | Code inspection (established, this session) |
| S8-05 | Applies Session-3-close entry-recovery incl. early closes; S5-19/S6-24 semantics; exact enforcement is OPS-003 work; intraday next-bar rules don't apply to V2 | Agreed | Authorized and implemented (Package 3) | Implemented (Package 3, OPS-003 Finding B CLOSED); S6-24's "at or before qualifies" equality semantics directly enforced (`_recovery_deadline_passed`'s `>` boundary, not `>=`) | Isolated test execution (`test_p3d_live_tick_immediately_before_session3_close_still_qualifies`) |
| S8-06 | Entry=Session 0, exit=close of 10th session after entry; holidays don't increment clock; delayed reconciliation doesn't shift exit session | Agreed (pre-existing) | Not authorized | Implemented | Code inspection (this session, `config.py:34,88`) |
| S8-07 | No stop-loss in frozen baseline; no position additions from new cluster; pause/exclude/scope-removal doesn't abandon obligations | Agreed (pre-existing) | Not authorized | Implemented (stop-loss/single-position halves); Not assessed (scope-removal-preserves-obligations half) | Code inspection (established + this session) |
| S8-08 | Missing valuations stale/unknown never fabricated zero; corp actions follow chronological policy without resetting exit clock (target only); no whole-share assumption | Agreed | Not authorized | Not implemented (corporate-action half, OPS-004); Implemented (missing-valuation half, reaffirms S2-12) | Code inspection (established) |
| S8-09 | 3-step frozen fall-forward contract (target → earliest-of-next-5 → EXIT_UNRESOLVED); never best-price; no future data | Agreed (pre-existing) | Not authorized | Implemented | Code inspection + isolated test execution (this session, `pipeline.py:132-202`, `test_e8c_exit_unresolved_when_target_and_all_fallforward_missing` passed) |
| S8-10 | "First available" ≠ race-arrival; record target/actual/source/price/reconciliation-time; V2 fall-forward distinct from intraday T-10 recovery | Agreed | Not authorized | Partially implemented (deterministic selection confirmed; full 5-field record-keeping not individually traced) | Code inspection (this session) |
| S8-11 | Committed exit never silently replaced by later backfill; proven errors need versioned auditable correcting entries | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S8-12 | EXIT_PENDING·AWAITING_PRICE: open, occupies capacity, no anticipated-proceeds credit, other entries continue only if checks reliable | Agreed | Not authorized | Partially implemented (capacity-occupation and no-phantom-proceeds confirmed structurally; explicit status label not found) | Code inspection (this session) |
| S8-13 | EXIT_UNRESOLVED: visible, blocks new entries account-wide until auditable resolution, not cleared by restart, containment not corruption-evidence, not auto-applied to other accounts | Agreed | Not authorized | Implemented (Package 2, OPS-012 CLOSED — `account_blocks.py` + `paper.py::enter_position()` first-statement gate inside the protected transaction; restart-durable; clearance refused while still EXIT_UNRESOLVED; per-account, never cross-account) | Code inspection + isolated test execution (`tests/test_package2_account_blocks.py`, 25 passed) |
| S8-14 | CLOSED: exactly-once settlement, duplicate/late instructions can't re-sell, notification failure doesn't roll back/duplicate; valuation freshness separate from exit status | Agreed (pre-existing) | Not authorized | Implemented | Code inspection (this session, `paper.py:155-191` atomic transaction) |
| S8-15 | Cooldown anchor = actual modeled exit session incl. fall-forward; delayed notification doesn't restart; frozen length 5 sessions/issuer | Agreed (pre-existing) | Not authorized | Implemented | Code inspection (this session, `paper.py:188`, `config.py:45,91`) |
| S8-16 | New entry still needs newly qualifying opportunity + timely admission; cooldown ending ≠ auto-BUY; boundary = first eligible re-entry session | Agreed (pre-existing) | Not authorized | Implemented (boundary directly resolved: exit_session+5 sessions, inclusive) | Code inspection (this session, `paper.py:104-106`) |
| S8-17 | Track acceptance evidence separately for 8 listed lifecycle guarantees | Agreed | Not authorized | Partially implemented (items 1/2/4 directly exercised this session; 3/5/6/7/8 not individually re-verified) | Code inspection + isolated test execution (this session) |
| S8-18 | Identify boundary coverage needs; existing tests may satisfy individually, cited not overclaimed | Agreed | Not authorized | Partially implemented (this documentation's own discipline; dedicated boundary tests for holidays/early-closes not located) | Code inspection (this session, self-check) |
| S8-25 | Deferred: provider finality/publication-qualification boundary for target-closing data | Open — deferred | N/A | Resolved at contract level (PQ-2B finality close+4h+16min; SIP provider); provider ACTIVATION remains the gated release-start step | N/A; final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S8-26 | Deferred: dedicated holiday/early-close-spanning fall-forward and admission-deadline boundary test coverage | Open — deferred | N/A | N/A | N/A |
| S9-01 | Primary Trade & Event bot scope | Agreed | Not authorized | Not implemented (no dedicated bot exists) | Code inspection (established) |
| S9-02 | Separate Operations bot: incidents, account blocks, recovery | Agreed (reaffirms S4-07) | Not authorized | Implemented (Sentinel: incidents, account blocks, recovery, RI-2) | Code inspection (established); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S9-03 | Optional Research bot isolated, OFF by default | Agreed (reaffirms S3-21/S4-08) | Explicitly not authorized | Implemented as OFF (Lab isolated, OFF by default) | Code inspection (established); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S9-04 | Target not deployment-claim; "qualified" ≠ profitable edge | Agreed | Not authorized | Implemented (this documentation's own framing) | Code inspection (this session, self-check) |
| S9-05 | Compact-message content requirements (status lines, identity, deadline/exit rule) | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S9-06 | Delayed Market Simulation message disclosure (market time, data age, unverified validity) | Agreed (extends S6-15) | Not authorized | Not implemented | Code inspection (this session) |
| S9-07 | Details/dashboard scope; critical limitations never hidden | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S9-08 | Main lifecycle notification set (not exhaustive whitelist) | Agreed | Not authorized | Not implemented (OPS-013) | Code inspection (this session) |
| S9-09 | Routine polling/repeated awaiting-price/minute P&L stay dashboard-only | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S9-10 | Exit-problem routing (Trade&Event factual vs. Operations incident); avoid redundancy | Agreed | Not authorized | Not implemented (OPS-013) | Code inspection (this session) |
| S9-11 | Obsolete-pending consolidation into truthful OPEN; preserve underlying events | Agreed | Not authorized | Not implemented (OPS-013) | Code inspection (this session) |
| S9-12 | No blind post-downtime flush; truthful catch-up reporting; never present historical fills as executable | Agreed | Not authorized | Partially implemented (S4-05's established no-flood evidence; consolidation-specific behavior not found) | Code inspection (established + this session) |
| S9-13 | Ambiguous delivery not assumed unsent/blindly retried; exactly-once execution ≠ exactly-once notification | Agreed (reaffirms established AMBIGUOUS contract) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S9-14 | Default overview excludes Research Lab; prospective vs. Delayed Simulation never blended | Agreed | Not authorized | Not assessed in this documentation pass (vacuously true, no Research Lab account exists yet) | Not assessed in this documentation pass |
| S9-15 | Top-to-bottom layout: Action Required, equal Equity/Open-P&L, opportunities/positions, Recent Activity, Details | Agreed (extends S2-10) | Not authorized | Not implemented | Code inspection (established, S2-10) |
| S9-16 | Distinct Research View; combined views identify accounts/modes, no double-counting | Agreed (reaffirms S3-13) | Not authorized | Not implemented | Code inspection (established) |
| S9-17 | Pause Updates ≠ Pause New Entries; execution/position-management unaffected | Agreed (reaffirms S4-12/S8-07) | Not authorized | Partially implemented (Pause Updates real, dashboard refresh controls; Pause New Entries not implemented, S4-12) | Code inspection (established) |
| S9-18 | Domain-specific mutes; manual refresh/controls from overview; auto-refresh preserves scroll/focus/panels | Agreed | Not authorized (pre-existing, partial) | Partially implemented (auto-refresh real and tested; domain-specific mutes not implemented, S7-20/OPS-011) | Code inspection (established, Task 140 evidence) |
| S9-19 | Full-reload restoration requires explicit saved-state behavior, not claimed; assess not assume refresh-fix compliance | Agreed | Not authorized | Implemented (this documentation's own honest framing) | Code inspection (this session, established Task 140 evidence re-read) |
| S9-20 | Dashboard P&L doesn't replace EOD Telegram; EOD retains account/mode separation + valuation limitations | Agreed (reaffirms S2-07/S4-13) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S10-01 | Account identity: ID·Strategy/Version·Execution Mode·Campaign·Currency | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S10-02 | New-campaign defaults $100k cash / $10k fee-inclusive max entry budget; existing accounts/frozen settings unchanged; USD-only initial scope | Agreed (extends S3-12/S3-14) | Not authorized | Implemented (defaults $100k / $10k fee-inclusive whole-share; Package 4 + RI-1) | Code inspection (established); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S10-03 | Reserved cash subset of ledger cash; available=ledger-reservations; atomic admission reserve; reservation doesn't alter equity | Agreed | Not authorized (pre-existing) | Implemented | Code inspection (established, this session, `talonx_v2/paper.py`) |
| S10-04 | Atomic execution debit; unused-release changes available not ledger cash; exactly-once release; consistency | Agreed (reaffirms S5-17) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S10-05 | Cost-free illustrative sequence; execution not necessarily equity-neutral with costs | Agreed | Not authorized | Implemented (illustrative, this documentation) | Code inspection (this session, self-check) |
| S10-06 | Separate spread/slippage-in-fill vs. explicit fees vs. reference basis; no double-counting | Agreed | Not authorized | Partially implemented (spread-in-fill real via apply_spread; explicit separate fee ledger not found for V2) | Code inspection (established + this session) |
| S10-07 | Whole-share, fee-aware sizing formula; require ≥1 share else explicit skip | Agreed | Authorized and implemented (Package 4, V2 only) | Implemented (Package 4, OPS-014 CLOSED for V2 — `talonx_v2/sizing.py::size_whole_shares_fee_inclusive`; Original's own sizing unchanged, out of scope) | Isolated test execution (`tests/test_package4_sizing_accounting.py`, P4-B tests) |
| S10-08 | Whole-share-within-budget distinct from cash-driven reduction; pre-commit validation list; no invented rounding | Agreed | Authorized and implemented (Package 4) | Implemented (Package 4) — insufficient available cash causes an explicit `INSUFFICIENT_AVAILABLE_CASH` skip, never a smaller reservation | Isolated test execution (`test_p4b_available_cash_smaller_than_allocation_rejects_not_resizes`) |
| S10-09 | Illustrative sizing example (not approved parameters) | Agreed | Not authorized | Implemented (illustrative, this documentation) | Code inspection (this session, self-check) |
| S10-10 | Net proceeds/P&L formulas; no double-deducted entry fees; reconcilable gross/net breakdown | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S10-11 | Costs ≠ auto unrealized-loss; missing valuation never zero; contribution denominators preserved; no invented return methodology | Agreed (reaffirms S2-10/S2-12) | Not authorized | Implemented (missing-valuation half, established); pending (return-methodology half, explicitly not invented) | Code inspection (established) |
| S10-12 | Position-limit slot-counting rules (pending/open/unresolved-continues/fall-forward-not-new-reservation/atomic-release) | Agreed | Not authorized | Partially implemented (limit itself real; count-once rules not individually traced) | Code inspection (this session) |
| S10-13 | Cash/position limits independent; V2's frozen 20-position limit preserved; no implied 10-position limit | Agreed (pre-existing) | Not authorized | Implemented | Code inspection (this session, `talonx_v2/config.py:44,90`) |
| S10-14 | Same-stock across independent accounts; exposure without merging performance; Research Lab excluded from default totals | Agreed | Not authorized | Not implemented (no exposure-display surface found) | Code inspection (this session) |
| S10-15 | No borrowing/leverage/negative-cash/shorts; explicit skip on insufficient capacity; truthful deficit recording, block+raise Operations | Agreed | Not authorized | Partially implemented (no-shorts/explicit-skip established; deficit-recording+Operations-raise not found) | Code inspection (established + this session) |
| S10-16 | Deposits/withdrawals explicit, auditable, separate from performance; no auto-top-ups; existing balances unchanged | Agreed | Not authorized | Not implemented (no deposit/withdrawal feature exists) | Code inspection (this session) |
| S10-17 | Dividends: **TOTAL RETURN retained (gatekeeper)** — ordinary cash dividends economically received while held are included in performance; recorded separately from price P&L; entitlement by explicit provider event and ex-date ownership (`entry_session < ex_date <= exit_fill_session`); receivable != cash (credited on/after payable date after fresh re-confirmation, also after the trade is closed); no double count (fills must be dividend-unadjusted, else fail closed); special/foreign/malformed dividends unsupported | Agreed (retained; implementation contract recorded) | Not authorized | **Implemented (PQ-2A closure, V2 only)** — `dividend_entitlements` ACCRUED->CREDITED lifecycle, quantity from the split trail, cash + total-return reconciliation, read-only operator view; live adapters moved to a split-only basis | Code inspection (established); PQ-2A `docs/research/evidence/provider_qualification_pq2a/`; PQ-2A closure evidence; `tests/test_pq2a_closure_dividends.py` |
| S10-18 | Preserve Session 5 split/cash-in-lieu requirements unchanged | Agreed (reaffirms S5-21..S5-27) | Not authorized | **Partially implemented (PQ-2A, V2 only)** — see S5-22..S5-26 | Code inspection (established); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S10-19 | Unsupported corporate actions preserve unresolved obligations; no guessed ratios/zero-write-offs; verified correction recordable | Agreed | Not authorized | **Partially implemented (PQ-2A, V2 only)** — unsupported actions preserve an unresolved position (no guessed ratio, no zero write-off); verified-correction recording not implemented | Code inspection (established); PQ-2A `docs/research/evidence/provider_qualification_pq2a/` |
| S10-20 | EOD/restart reconciles 7 listed items | Agreed (extends S4-13) | Not authorized (pre-existing, partial) | Partially implemented (detection real; full 7-item scope not individually traced) | Code inspection (established) |
| S10-21 | Genuine mismatch blocks new admissions; missing valuations alone ≠ mismatch proof; clearance authority → Session 11 | Agreed | Not authorized | Implemented (Package 2, OPS-015 CLOSED for both cited sources — V2's `_v2_reconcile()` via `close.py`, and this row's own literal `eod_reconciliation.py` via `_record_original_intraday_reconciliation_blocks()`; missing valuations kept structurally separate from a mismatch, per `blocked_reason()`'s reason-type-specific detail; clearance authority = the minimal CLI, see S11-15) | Code inspection + isolated test execution (`tests/test_package2_account_blocks.py`) |
| S10-22 | Deferred: numerical spread/slippage/fee assumptions | Open — deferred | N/A | N/A | N/A |
| S10-23 | Deferred: cross-account hard concentration limits | Open — deferred | N/A | N/A | N/A |
| S10-24 | Deferred: correlation-based admission gates | Open — deferred | N/A | N/A | N/A |
| S10-25 | Deferred: concentration-warning thresholds | Open — deferred | N/A | N/A | N/A |
| S11-01 | Pause Updates = dashboard refresh only | Agreed (sharpens S9-17) | Not authorized | Implemented (dashboard-refresh pause, Task 140) | Code inspection (established) |
| S11-02 | Pause New Entries blocks admissions + atomically cancels unfilled intents; existing positions still managed | Agreed (sharpens S4-12/S9-17) | Not authorized | Not implemented | Code inspection (established, S4-12) |
| S11-03 | Stop Application preserves state; deadlines continue offline; Resume = future admissions only, no resurrection | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S11-04 | Controlled shutdown: block admissions, finish/rollback transactions, persist state, report obligations, clean stop | Agreed | Not authorized | Partially implemented (stop_stack()/run_close() real for process/reconciliation; admission-blocking not wired) | Code inspection (established, EOD closure evidence) |
| S11-05 | Manual shutdown w/ intraday positions needs explicit offline-risk warning; unattended shutdown aborts if policy unmet | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S11-06 | Restart verifies ownership/identity, reconciles ledger, classifies obligations, assesses readiness, recovers notifications | Agreed | Not authorized | Partially implemented (ownership-verification and reconciliation real, established) | Code inspection (established) |
| S11-07 | Restart gates restrict new admissions only, not data/collection/safe management | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S11-08 | V2 intent eligible for price recovery after market open; admission vs. price-recovery deadlines distinct | Agreed (sharpens S8-05) | Authorized and implemented (Package 3) | Implemented (Package 3, OPS-003 Finding B CLOSED) | Isolated test execution (`tests/test_package3_pricing_timing.py`) |
| S11-09 | Evidence durably received by deadline may be processed later | Agreed (reaffirms S6-24/S8-05) | Authorized and implemented (Package 3) | Implemented (Package 3, OPS-021 CLOSED — TalonX's own durable `ingested_at_utc` receipt timestamp now checked, not merely the source's own timestamp; late receipt with an earlier source timestamp correctly refused; timely receipt with delayed processing correctly still admits) | Isolated test execution (`tests/test_package3_pricing_timing.py`, P3-E tests) |
| S11-10 | V2 checks original target close before fall-forward | Agreed (reaffirms S8-09) | Not authorized (pre-existing) | Implemented | Code inspection (established, this session) |
| S11-11 | Ambiguous deliveries preserved for investigation, never blindly resent/treated as confirmed-unsent | Agreed (sharpens S9-13) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S11-12 | Five account-readiness states (Checking/Ready/Managing/Paused/Stopped) | Agreed | Not authorized | Not implemented (OPS-016) | Code inspection (this session, targeted search) |
| S11-13 | Truthful global "Partially Ready" summary allowed | Agreed | Not authorized | Not implemented (OPS-016) | Code inspection (this session) |
| S11-14 | Transient blocks clear only when checks pass; readiness requires all prerequisites | Agreed | Not authorized | Not implemented (OPS-016) | Code inspection (this session) |
| S11-15 | Serious issues (mismatch/deficit/unresolved-exit/identity-mismatch) require auditable resolution + explicit clearance; restart never clears persisted pauses/serious blocks | Agreed | Not authorized | Partially implemented (Package 2, OPS-012/OPS-015 CLOSED for EXIT_UNRESOLVED/LEDGER_MISMATCH/CASH_DEFICIT — `talonx_ops/account_blocks.py`'s `attempt_clearance()` + `talonx_ops/prospective/clearance.py`'s reason-type-specific fresh re-verification, via `python -m talonx_ops.prospective clear-block`; restart-durable, confirmed by test. IDENTITY_MISMATCH has no detector and clearance always refuses it by design — no invented identity check, per this task's own instruction. OPS-016's five-state UI this clearance plugs into remains separately open) | Code inspection + isolated test execution (`tests/test_package2_account_blocks.py`) |
| S11-16 | Manual start/stop initially; optional Europe/London saved automation; 08:00-22:00 preferred not scheduled | Agreed (reaffirms S1-04) | Not authorized | Implemented (manual)/Not implemented (automation) | Code inspection (established) |
| S11-17 | Total outage detection requires independent external watchdog | Agreed | Not authorized | Not implemented | Code inspection (this session, targeted search) |
| S11-18 | Immediate notification = attempt + durable recording, not guaranteed delivery; grace periods/dedup; numerical thresholds pending | Agreed | Not authorized | Not implemented | Code inspection (this session) |
| S11-19 | Display/notification prefs apply immediately; strategy/account/execution changes need versioned activation; existing positions retain rules | Agreed | Not authorized | Not assessed in this documentation pass (config-effective-dates topic is new) | Not assessed in this documentation pass |
| S12-01 | Mandatory Prior Research Review before new experiments/framework work | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-02 | No repeat without documented reason; replication labelled; reuse existing capabilities; no exhaustive-audit claim | Agreed | Not authorized | Implemented (this documentation's own compliance) | Code inspection (this session, self-check) |
| S12-03 | Experiment registration before evaluation (hypothesis/baseline/candidate/data/account/assumptions/criteria) | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-04 | Systematic parameter testing retains all variations; tuning data ≠ independent validation | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-05 | Research isolation; EXPERIMENTAL — INTERNAL ONLY label; research bot OFF by default | Agreed (reaffirms S6-19/S3-21) | Explicitly not authorized (bot) | Not implemented (label confirmed absent again this session) | Code inspection (this session, re-run search, no match) |
| S12-06 | Shared collection permitted, must not starve primary; no primary mutation through experiments | Agreed (reaffirms S3-15-S3-20) | Not authorized | Implemented (isolation architecture, established) | Code inspection (established) |
| S12-07 | Separate dev/tuning vs. untouched evaluation data; disclose reuse + fresh evidence before promotion | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-08 | 2-year data feasibility open; no invented fixed trade-count/duration | Open — deferred (reaffirms S3-27/S5-31, tracked as S12-24) | N/A | N/A | N/A |
| S12-09 | Comparison dimensions: net performance/downside/frequency/concentration/evidence-quality/operational-reliability | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-10 | Strategy View vs. Account View; neither = real-world alpha | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-11 | Verdicts Reject/Inconclusive/Eligible-for-promotion-review; historical acceptance permits shadow only | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-12 | Define feed/reference/spread/slippage/fees/adverse scenarios; apply once before sizing/admission | Agreed (reaffirms S10-06) | Not authorized | Not implemented (numerical values deferred, S12-23) | Code inspection (established) |
| S12-13 | Intraday RRR gate uses modeled entry+frozen stop/target, not applied to V2; whole-share sizing fee-inclusive | Agreed (reaffirms S6-16/S10-07) | Not authorized | Implemented (baseline RRR mechanism, S6-16); Not implemented (fee-inclusive sizing, OPS-014) | Code inspection (established) |
| S12-14 | Rerun scenarios chronologically, not flat haircut; comparable baseline/candidate assumptions | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-15 | Example numbers illustrative only; numerical calibration deferred | Open — deferred (tracked as S12-23) | N/A | N/A | N/A |
| S12-16 | Freeze version/criteria before shadow observation; record actual evidence availability; no retrospective admission | Agreed (reaffirms S8-01/S8-02) | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-17 | Predeclared duration/evidence can't shorten for early profits; safety failures may stop early; insufficient evidence = Inconclusive | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-18 | Shadow validates observed behavior not real broker execution; historical+shadow are separate mandatory gates | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-19 | Explicit promotion approval records version/evidence/destination/activation/readiness/settings/rollback conditions | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-20 | Existing positions retain original rules; research profits not transferred to primary | Agreed (reaffirms S8-06/S6-18) | Not authorized (pre-existing) | Implemented | Code inspection (established) |
| S12-21 | Protective blocking automatic, strategy replacement not; rollback preserves history, never restores old cash/forces liquidation | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-22 | Previous-version restoration needs explicit approval+readiness; unsafe obligations need separately approved remediation | Agreed | Not authorized | Not assessed in this documentation pass | Not assessed in this documentation pass |
| S12-23 | Deferred: numerical execution-cost calibration | Open — deferred | N/A | N/A | N/A |
| S12-24 | Deferred: 2-year historical data feasibility (reaffirms S3-27/S5-31) | Open — deferred | N/A | N/A | N/A |
| S13-01 | First release: V2 = primary paper strategy, conditional on acceptance criteria | Agreed | Not authorized (release-scope decision, not a build) | Accepted for paper release (FINAL V2 RELEASE ACCEPTANCE: 34 PASS / 4 BOUNDED_FOLLOWUP / 0 blocking; profitability UNPROVEN; real money NOT enabled) | Code inspection (this session, Package 1 evidence); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S13-02 | Intraday Research-Lab-only for first release; excluded from primary totals/Telegram | Agreed | Not authorized | Not implemented (Research Lab account doesn't exist, S6-03) | Code inspection (established) |
| S13-03 | Company developments dashboard-visible; primary Telegram needs opt-in + Session 7 acceptance | Agreed (reaffirms S7-01/S9-01) | Not authorized | Not implemented (S7 rubric/routes not built, OPS-011) | Code inspection (established) |
| S13-04 | Prior-research reconciliation is PENDING, not completed | Agreed | N/A (a status statement) | Not implemented (S12-01's mandatory review not performed) | Code inspection (this session, self-check) |
| S13-05 | Packages 1-5 authorized in dependency order; release integration needs separate scoping | Agreed | Packages 1-2: Authorized (this task) | Packages 1-2: Implemented; Packages 3-5: Not implemented, not authorized | Isolated test execution (this session) |
| S13-06 | Staging order: Stage0 → P1 → P2 → P3 → P4 → P5 → release integration | Agreed | Not authorized beyond Package 2 | Package 1-2 stages complete; later stages not started | Isolated test execution (this session) |
| S13-07 | Provider qualification + prior-research review are parallel tracks, not strategy-parameter permission | Agreed | Explicitly not authorized (no parameter change) | Implemented (V2Config frozen values unchanged, fingerprint verified) | Code inspection (this session, direct fingerprint check) |
| S13-08 | Material-version cutover rules (7 sub-rules) | Agreed | Explicitly not authorized (no cutover performed) | Implemented (RI-1 cutover classification; no cutover performed) | Code inspection (this session, self-check — no cutover code path exercised); final acceptance `docs/research/evidence/v2_final_release_acceptance/` |
| S13-09 | Package 1 — Settlement Integrity & Unresolved Obligations | Agreed | Authorized and implemented (this task) | Implemented | Isolated test execution (this session, 14 new + 2 corrected existing tests, all passed) |
| S13-10 | Package 2 — Durable Account Blocks and Auditable Clearance | Agreed | Authorized and implemented (this task) | Implemented (OPS-012/OPS-015 closed for the four scoped account/reason combinations; IDENTITY_MISMATCH has no detector, disclosed; OPS-016's readiness-state UI remains separately open) | Isolated test execution (this session, `tests/test_package2_account_blocks.py`, 25 new tests + 2 corrected pre-existing Package 1 assertions, all passed) |
| S13-11 | Package 2 Acceptance Review — bounded correction of 5 findings (A1 reservation gap, A2 debit-cap + DCA block gap, A4 clearance race, A5 settlement caller-trust) found while verifying Package 2's own acceptance questions | Agreed | Authorized and implemented (this task) | Implemented (`PACKAGE2_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`; OPS-012/OPS-015 now genuinely CLOSED including these corrections; new `OPS-018`/`OPS-019` found-and-closed same session; A3/A6/A7 investigated, no code change required; 3 A6 presentation-only omissions recorded as P3 follow-ups, not fixed) | Isolated test execution (this session, `tests/test_package2_acceptance_review.py`, 17 new tests incl. 2 genuinely-independent-connection concurrency races; 42-file scoped regression 663 passed/9 pre-existing-unrelated failed/0 new; V2 fingerprint `11107198c5b81237` re-verified unchanged) |
| S13-12 | Package 3 — Authoritative Pricing, Refresh, Evidence Timestamps & Deadlines (P3-A through P3-G) | Agreed | Authorized and implemented (this task) | Implemented (`PACKAGE3_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`; OPS-003 Finding B CLOSED; new `OPS-020`/`OPS-021` found-and-closed same session; `pending_entry_intents` gained additive `source_event_ts_utc`/`receipt_ts_utc` audit columns; OPS-005 provider-finality gap remains open, unaffected) | Isolated test execution (this session, `tests/test_package3_pricing_timing.py`, 19 new tests incl. an independent-connection concurrency race; 21-file V2 regression 252 passed/3 pre-existing-unrelated failed/0 new; V2 fingerprint `11107198c5b81237` re-verified unchanged) |
| S13-13 | OPS-003 Finding A classified against the Package 3 runtime contract | Agreed | N/A (a classification, not new behavior) | `PARTIALLY_COMPATIBLE` — `cluster_engine.py`'s 2nd-distinct-owner activation directly re-confirmed unchanged; original `S2-15`-cited headline figures (research `build_episodes`, last-filing activation) remain INCOMPATIBLE with the runtime; Task 112R's own G2b re-evaluation and Task 116's replay already use runtime-matching semantics and may be treated as runtime-representative, though neither has been re-verified against Package 3's own pricing/deadline corrections (open, parallel prior-research track) | Code inspection (this session, direct re-read of `talonx_v2/cluster_engine.py`); no profitability recomputed |
| S13-14 | Package 4 — Whole-Share, Fee-Inclusive Sizing & Precise Accounting (P4-A through P4-H) | Agreed | Authorized and implemented (this task) | Implemented (`PACKAGE4_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`; OPS-014 CLOSED for V2; new `OPS-022` found-and-closed same session — dormant P&L defect, cost basis never re-derived from authoritative persisted total; zero-cost assumption explicitly disclosed, S10-22 remains unresolved; full multi-dimensional campaign-identity model — Session 10 §A — remains a disclosed, bounded release-integration follow-up, not built here) | Isolated test execution (this session, `tests/test_package4_sizing_accounting.py`, 28 new tests incl. an independent-connection cash-overcommit concurrency race; 21-file V2 regression 252 passed/3 pre-existing-unrelated failed/0 new; V2 fingerprint `11107198c5b81237` re-verified unchanged; `V2Config` itself never modified) |
| S13-15 | Package 5 — Intraday Causal Execution & Post-Cost RRR Research-Lab Hardening | Agreed | Authorized and implemented (this task) | Implemented (`PACKAGE5_ACCEPTED`; no defect found — `talonx_backtest`/`talonx_quant`'s causal-execution/RRR/reproducibility/isolation mechanisms already correct from Tasks 24/25A/25B; verification-and-evidence package, zero production-code changes) | Isolated test execution (this session, `tests/test_package5_intraday_causality.py`, 20 new tests covering all 15 required scenarios; 108+76 pre-existing `talonx_backtest` tests re-confirmed passing; V2 fingerprint `11107198c5b81237` re-verified unchanged) |
| S13-16 | V2 Release Integration Task RI-1 — Campaign Identity + End-to-End Execution Spine | Agreed | Authorized and implemented (this task) | Implemented (explicit persisted `campaign` identity record — RI1-B; RI1-C's `CAMPAIGN_STARTING_CASH`-vs-`V2Config.starting_cash_usd` ambiguity resolved via `campaign_cash.authoritative_starting_cash()`, new `OPS-024`; `talonx_v2/cutover.py` implements the agreed S13-08 cutover classification — RI1-D/E — reusing, not reinventing, Package 3's own recovery-deadline math (`talonx_v2/calendar.py::recovery_deadline_session`/`recovery_deadline_passed`, extracted for reuse); full entry/exit spine, account-block, reconciliation, restart, and legacy-compatibility proofs (RI1-F through RI1-L); V2 release fingerprint updated `11107198c5b81237`→`e2acf6454789217e` — a disclosed, non-strategy change (new `campaign_id`/`execution_mode` operational fields on `V2Config`) plus a separately-disclosed LF-normalization defect fix, new `OPS-023`; release integration itself remains NOT COMPLETED — RI-2 (Telegram/ops routing), dashboard/operator integration, provider qualification, and prospective paper validation are all explicitly NOT started) | Isolated test execution (this session, `tests/test_ri1_campaign_identity.py`, 35 new tests covering RI1-B through RI1-L; targeted regression across Packages 1-5 plus Task 110-117 V2 test files; V2 fingerprint recomputed directly, confirmed stable across a deliberate git-stash/pop roundtrip) |
| S13-17 | V2 Release Integration RI-2 — Multi-Channel Telegram + Durable Trade/Event/Operations Routing | Agreed (implements S6-01/S9-01-S9-03) | Authorized and implemented (this task) | Implemented (new `talonx_ops/notify/` package: TRADE_EVENT/OPERATIONS/RESEARCH logical destinations, RESEARCH double opt-in OFF by default with no fallback; V2's `v2_alert_outbox` gained an additive `destination` column + campaign identity in every message; new `ops_notification_outbox` durable store for OPERATIONS/RESEARCH, drained by the SAME already-proven `V2Service.tick()` runtime loop; the historical "9,843 PENDING / 0 SENT" Intelligence-outbox finding was RE-TRACED against current code and found ALREADY fixed by a prior task (Task 140's `proc.py` env propagation) — RI-2 confirms rather than re-fixes it; account-block/EXIT_UNRESOLVED/reconciliation-failure/startup/shutdown/delivery-failure OPERATIONS producers added via a poll-and-diff scanner, never an inline change to Package 1/2's own mutation methods; backlog/expiry safety, retry/restart, dedup, and secret-safety all directly tested; V2 fingerprint unaffected (`e2acf6454789217e`, unchanged); dashboard/operator integration, provider qualification, and prospective paper validation remain explicitly NOT started) | Isolated test execution (this session, `tests/test_ri2_notification_routing.py`, 31 new tests covering all 31 required scenarios; 310-test targeted regression, 308 passed / 2 pre-existing-unrelated `OPS-017` failures reproduced against clean HEAD; V2 fingerprint recomputed directly, confirmed unchanged) |
| S13-18 | RI-3 — Dashboard and Operator Integration (S9/S10/S11/S13 release visibility) | Agreed | Authorized and implemented (2026-09-18) | Implemented with bounded follow-ups: read-only campaign/account, reservations, unresolved obligations, intents, blocks/clearance, scoped reconciliation, realized P&L, notification/runtime state and attention; Intelligence/Operations routing and first-release Intraday isolation closed. Physical credentials/delivery validation, provider qualification and prospective validation remain separate gates. | `docs/research/evidence/v2_release_integration_ri3/README.md`; isolated fixture and targeted tests |
| S13-19 | PQ-1 — Provider Qualification & Price Finality | Agreed release gate | Authorized and completed as qualification; no provider activation authorized/performed | `PQ1_NOT_ACCEPTED`: current Alpaca credentials can read recent historical SIP daily bars, but prospective open/close finality and corporate-action-safe position accounting remain unqualified; OPS-005 stays open. Additive provider provenance persistence implemented for new runtime trades; legacy rows remain unknown. No strategy threshold/lifecycle changed. | `docs/research/evidence/provider_qualification_pq1/`; 117 focused tests passed (broader regression 325 passed / 3 pre-existing unrelated failures); bounded read-only entitlement probe |
| S13-20 | PQ-2A — Corporate Action Safety & Accounting Contract | Agreed release gate (corporate-action correctness only) | Authorized and completed; no provider activation, SIP runtime, finality, PQ-2B or release acceptance authorized/performed | `PQ2A_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`: V2 forward/reverse splits can no longer manufacture P&L (explicit-event, basis-proven, exactly-once, unchanged aggregate cost basis, exact fractional entitlement); unsupported/conflicting/unavailable/unknown-basis evidence fails closed; composite history refuses unprovable basis mixes; dividends observed-not-credited (`DIVIDEND_POLICY_DECISION_REQUIRED`). Strategy fingerprint `e2acf6454789217e` unchanged; OPS-005 stays open. | `docs/research/evidence/provider_qualification_pq2a/`; see README §Tests |
| S13-21 | PQ-2A CLOSURE — Fractional entitlement decision + dividend total-return accounting | Agreed release gate | Authorized and completed; no PQ-2B, SIP runtime, finality, release acceptance or prospective validation authorized/performed | See closure evidence README for the verdict. Exact fractional entitlement documented as the V2 paper rule (S5-26 revised); ordinary-cash-dividend total-return lifecycle implemented (S10-17); live adapters on a split-only basis; special/foreign/unsupported distributions fail closed. Fingerprint `e2acf6454789217e` unchanged. | `docs/research/evidence/provider_qualification_pq2a_closure/` |
| S13-22 | PQ-2B — SIP runtime adapter + OPEN/CLOSE finality + first-release provider contract | Agreed release gate | Authorized and completed; implemented, NOT activated; no production provider switch, release acceptance, freeze or prospective validation | See PQ-2B evidence README for the verdict. One executable provider contract (Alpaca SIP daily, split-only, fail closed, no fallback); measured OPEN/CLOSE semantics; calendar-aware finality (close+4h+16min); same-provider liquidity history with exact contiguous window; bounded late-dividend catch-up; readiness gate. OPS-005 resolved at contract level. Fingerprint `e2acf6454789217e` unchanged. | `docs/research/evidence/provider_qualification_pq2b/` |
| S13-23 | FINAL V2 RELEASE ACCEPTANCE — requirement-by-requirement release gate | Agreed release gate | Authorized and completed; no launch, no freeze, no production mutation, no real Telegram send | Explicit gated release profile `V2_RELEASE_CANDIDATE_PROFILE@1` (`talonx_v2/release_gate.py`; `--release` on `talonx_v2.run` and `talonx_ops.prospective start`): forces SIP + `V2_RELEASE_PRICE_CONTRACT@1` (`ac5e51aa3599d6c9`), never the stale csv default; refuses to start unless 17 read-only readiness checks pass. Matrix: 34 PASS / 4 BOUNDED_FOLLOWUP / 0 FAIL / 0 blocking. Fixed: dashboard health masking, alert wording (OPEN disclosure), stale whole-share test expectation. Strategy fingerprint `e2acf6454789217e` unchanged; profitability UNPROVEN. | `docs/research/evidence/v2_final_release_acceptance/` |
| S13-24 | Release freeze + preflight + controlled merge (v2-paper-rc1) | Agreed release gate | Authorized and completed; no launch, no session, no real send | Frozen SHA `a56ec8c` (tag `v2-paper-rc1`), pin `RELEASE_SHA_EXPECTED`; NEW clean campaign `V2-PAPER-RC1` ($100k/$10k, own ledger, PREPARED_FOR_CREATION_AT_LAUNCH); release gate hardened with campaign identity; main fast-forwarded. Fingerprints unchanged; profitability UNPROVEN. | `docs/research/evidence/release_freeze_preflight/` |
| S13-25 | Notification contract: Signal/Sentinel/Lab may share one private chat_id; isolation = destination + bot identity + event contract | Agreed (owner clarification 2026-09-24) | Authorized and implemented | Implemented (`resolve_destination_config(RESEARCH)` no longer rejects a shared chat_id; it rejects a Lab token equal to the Signal, Sentinel or legacy token; no fallback unchanged; Signal subscribers/broadcast NOT implemented, roadmap only in `docs/NOTIFICATION_CONTRACT.md`) | `tests/test_notify_same_chat_isolation.py`; one controlled Lab send (evidence `docs/research/evidence/lab_channel_enablement/`) |

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

**Session 7 update (2026-09-16, ~20:55 UTC) — refined**: Session 7 §A
refined this into the full agreed scope — the primary Telegram channel
carries both qualified trading opportunities AND explicitly opted-in
major developments, with company-development messages remaining
purely informational (never auto-creating a paper trade,
`S7-01`/`S7-19`). The plain-language presentation requirements are now
also fully specified (`S7-11`). Verdict unchanged: `Implemented` for
the optionality itself.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — linked, not resolved**:
Session 7 §D's full plain-language presentation requirement (`S7-11`)
directly incorporates "avoid unexplained SEC jargon" as one of its
explicit rules. **This gap is not fixed by Session 7** — the raw
"Item 2.03/2.04" citation was not re-checked or re-rendered this
session; `S7-11`'s own verdict is `Partially implemented`, citing this
same open gap. Whether prioritizing the fix is itself authorized
remains undecided.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — extended, not resolved**:
Session 6 §D agreed the concrete operator-facing requirement this
entry always lacked — one expiry update per unfilled alerted
opportunity, three distinct timestamps (deadline/discovery/
notification) shown, and an explicit "no paper position opened" skip
explanation (`S6-13`/`S6-14`). **Implementation status unchanged**:
still not found in the code inspected this session — `S6-14`'s own
verdict is `Not implemented`.

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

**Session 9 update (2026-09-17, ~07:12 UTC) — refined, capacity-
independent visibility reaffirmed**: Session 9 §B/§C directly answer
this entry's own "operator-facing surfacing" open question — the
agreed message format shows "Opportunity status" and "Paper status" on
separate lines, and the first-qualified notification is explicitly
required to fire "including capacity-skipped outcomes" (`S9-08`). The
exact wording remains undecided; the underlying skip mechanism this
entry describes is unaffected and unchanged (`Partially implemented`).

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

**Session 6 update (2026-09-16, ~18:47 UTC) — extended for Original's
intraday lane specifically**: Session 6 §D extended this distinction
to Original's intraday alerts explicitly — a timely, qualified
intraday opportunity stays Telegram-eligible even when paper capacity
blocks entry, with a clear skip explanation (`S6-13`). Prior evidence
for this entry was V2-only; `S6-13`'s own verdict is `Not implemented`
for Original's intraday lane specifically (no capacity-independent
alert path was found for it this session).

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — reaffirmed for V2's
own lifecycle specifically**: Session 8 §E confirms this entry's
"never auto-closes a multi-day position" claim extends correctly to
V2's own exit machinery — `settle_due_exits()` only ever closes a
position via its own frozen fall-forward contract (`S8-09`) or leaves
it `EXIT_UNRESOLVED` (`S8-13`); no EOD/reconciliation code path was
found that force-closes a pending or unresolved V2 exit. The
realized/unrealized/unknown valuation distinction is also reaffirmed:
`EXIT_UNRESOLVED` and `EXIT_PENDING`-style positions keep an
explicitly stale/unknown valuation, never a fabricated zero
(`S8-08`/`S8-12`). Verdict unchanged: `Implemented`.

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

**Session 9 update (2026-09-17, ~07:12 UTC) — resolved into a concrete
layout, still not implemented**: Session 9 §E directly answers this
entry's own candidate-session pointer — Account Equity and Aggregate
Open P&L are agreed to sit at position 2 of a five-part top-to-bottom
layout, immediately below a conditional Action Required banner
(`S9-15`). **This is the agreed target layout, not a claim it is
built** — the same gaps this entry already identified (no contribution
label, no explicit equal-prominence enforcement) remain unresolved.
Verdict unchanged: `Partially implemented`.

**Session 10 update (2026-09-17, ~07:12 UTC) — cost-free vs. cost-
bearing distinction added**: Session 10 §B's illustrative cash/
equity sequence is explicitly labelled **cost-free** — a pedagogical
example, not a claim about what execution actually looks like once
spread/slippage/fees apply (Session 10 §C explicitly states execution
is "not necessarily equity-neutral once costs are included"). This
sharpens, but does not change, this entry's own equity-tracking
verdict.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — reaffirmed, boundary
clarified**: Session 7 confirms notification/routing policy (§A) never
changes which securities are members of the master universe —
Intelligence's own content-gating and routing decisions (`S7-01`
through `S7-24`) are downstream of, and do not modify, `S3-08`'s
master-list/coverage membership. No demotion of Intraday occurred
(`S7-03`).

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — linked, obligation-
preservation confirmed**: Session 8 §C reaffirms that pause/exclude/
scope removal must not abandon an existing V2 position's obligations
(`S8-07`). No dedicated scope-removal code path was traced this
session for V2 specifically (`S8-07`'s own "Not assessed" half) — this
entry's own V2-side gap (no pause mechanism at all) remains
unresolved and is not contradicted. V2's issuer-level re-entry
cooldown (`S8-15`/`S8-16`, five sessions, anchored to actual exit) is
a **different** mechanism from Pause/Exclude — a cooldown is
automatic and time-bounded per issuer after a sale, not an operator-
initiated suspension of new opportunities.

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — unchanged,
confirmed**: Session 8's lifecycle discussion does not change this
entry's figures or apply them to V2's existing $300,000 campaign — no
account was reset or resized this session (verified: this task made
zero database writes). Verdict unchanged: `Not implemented` as a
stated default.

**Session 10 update (2026-09-17, ~07:12 UTC) — linked to the
inclusive-fee budget**: Session 10 §A sharpens the $10,000 figure into
a **fee-inclusive maximum entry budget** specifically (`S10-02`), and
§C's whole-share sizing formula (`S10-07`) is the concrete mechanism
that would consume that budget. Verdict unchanged: `Not implemented`
as a stated default — `OPS-014` additionally confirms today's actual
sizing (`calculate_buy()`) has no fee-awareness at all, so this
entry's figure could not yet be enforced as fee-inclusive even if
adopted.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — reaffirmed, not
downgraded**: Session 6 §A gave this entry's "experimental-candidate
account" its first concrete instance — Fundamental Opportunities, now
positioned as an isolated Research Lab candidate (`S6-03`) with the
optional research bot remaining OFF by default (reaffirms `S3-21`), no
existing process/account/obligation changed, and a labelled combined
portfolio view remaining permitted (not yet built) rather than
required. Verdict unchanged: `Not implemented`.

**Session 9/10 update (2026-09-17, ~07:12 UTC) — layout and identity
requirements added, still not built**: Session 9 §E requires a
"clearly distinct Research View" and combined views that identify
included accounts/execution modes without double-counting (`S9-16`);
Session 10 §A requires every account to identify Account ID/Strategy/
Execution Mode/Campaign/Currency (`S10-01`), and §E requires excluding
Research Lab replicas from default exposure totals (`S10-14`). All
three sharpen this entry's own combined-exposure-view requirement into
concrete UI/data rules — none of them is implemented. Verdict
unchanged: `Not implemented`.

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

**Session 12 update (2026-09-17, ~10:22 UTC) — full governance
layer specified, still not fully assessed**: Session 12 fills in the
governance this entry's four stages were always missing detail for —
mandatory prior-research review (`S12-01`/`S12-02`), experiment
registration (`S12-03`/`S12-04`), isolation specifics including the
"EXPERIMENTAL — INTERNAL ONLY" label (`S12-05`, re-confirmed absent
this session), cost treatment (`S12-12`-`S12-15`), shadow rules
(`S12-16`-`S12-18`), and promotion/rollback authority (`S12-19`-
`S12-22`). **This is a large batch of new, mostly `Not assessed`
requirements layered on this entry's own established "replay stage
real, live-shadow stage unconfirmed" finding** — none of them was
individually traced against `talonx_research/`'s actual code this
session; see each `S12-*` entry's own verdict.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — RESOLVED (product
positioning only)**: the product owner decided "Fundamental
Opportunities" is retained as an **isolated Research Lab candidate**,
not primary product scope, with promotion requiring explicit future
approval through a defined review (data/report provenance, valuation
method, causal replay, qualification, performance) —
`DECISION_LOG.md` Session 6 §A, tracked as `S6-03`. **Decision status
updated**: `Open — deferred` → `Resolved — see S6-03` for the
**product-positioning** question. This entry's original deferral text
is preserved unedited above. **A direct code/data inspection of
Original's long-term lane itself was still not performed this
session** — `S6-03`'s own implementation status is `Not implemented`
(no such Research Lab candidate account exists yet); the underlying
path's technical role remains as undecided as before, only its
**product category** is now settled.

## S3-25 — Deferred: cross-strategy capital/exposure enforcement policy

**Requirement**: `S3-13`'s combined-exposure **display** is agreed now;
any **enforcement** policy (e.g. a cross-strategy exposure cap) is
deferred. **Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: enforcement
needs its own risk discussion, not assumed alongside the display
feature. **Planned session**: Session 10 (Paper accounting, costs and
risk). **Dependency**: `S3-13`'s display feature existing first.

**Session 10 update (2026-09-17, ~07:12 UTC) — display resolved as
Agreed, enforcement remains deferred**: Session 10 §E explicitly
**approves exposure display** ("Exposure display is approved") — same-
stock exposure across independent accounts is shown, without merging
individual performance (`S10-14`). **Numerical cross-account hard
concentration limits, correlation-based admission gates, and
concentration-warning thresholds all remain explicitly deferred**
(`S10-23`, `S10-24`, `S10-25`), each requiring its own bounded
evaluation before activation — no numerical limit is invented by this
update. **Decision status**: the display half is now `Agreed` and
tracked separately (`S10-14`); this entry's own scope narrows to the
**enforcement** question specifically, which remains `Open —
deferred`, now split across `S10-23`/`S10-24`/`S10-25` rather than one
undifferentiated deferral.

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — clarified for V2
specifically, still not fully assessed**: Session 8 §A confirms V2's
own catch-up admission is timely-only — a startup catch-up may create
a valid intent, but never a retrospective one where no timely intent
existed (`S8-01`/`S8-02`). This directly supports (does not itself
prove) the "no chronological-accounting change" half of this entry
for V2's own lane; the cross-system (Original/Intelligence/V2)
ordering question this entry was originally about remains **not
assessed**.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — refined**: Session 7 §A
refines this entry's "Primary Telegram bot" framing into "Trade &
Event" routing specifically — trading opportunities and opted-in
major-company-developments share the primary channel, distinct from
Operations (`S4-07`) and Research (`S4-08`) routing. Independent
per-domain controls are now specified: event mute, trading pause, and
global delivery shutdown (`S7-20`/`S7-21`) — none of which were
tracked before this session. Verdict unchanged for the core routing
claim: `Implemented`.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — reaffirmed, not
downgraded**: Session 7 §G explicitly distinguishes event
qualification, delivery eligibility, delivery attempts, and confirmed
delivery as four separate concepts (`S7-22`) — none of which is
"notification success," reinforcing (not contradicting) this entry's
own claim that notification success never controls paper execution.
Verdict unchanged: `Implemented`.

**Session 9 update (2026-09-17, ~07:12 UTC) — reaffirmed at the
delivery-safeguard level**: Session 9 §D's "financial exactly-once
processing and notification-delivery guarantees are separate claims"
(`S9-13`) restates this entry's own architectural separation from the
delivery side specifically. Verdict unchanged: `Implemented`.

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — extended, exit-side
gap found**: Session 8 §E confirms the entry-side finding above
extends symmetrically to the exit side — `EXIT_BAR_PENDING_
FALLFORWARD` and `EXIT_UNRESOLVED` are two more genuinely distinct
internal dispositions (`talonx_v2/pipeline.py:179`, `store.py:410-419`,
this session), reinforcing the "separate missing-price/valuation
modifiers" pattern. **New gap disclosed**: unlike the entry-side
mechanism, `EXIT_UNRESOLVED` was found to lack an account-wide new-
entry block (`S8-13`/`OPS-012`) — a state-surfacing success paired
with an enforcement gap. Verdict unchanged: `Partially implemented`.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — reaffirmed, not
downgraded**: Session 6 (§D, §H) kept this entry's own distinction
intact and extended it — paused-entry cancellation remains explicitly
**distinct** from continuing position management (existing positions
keep their own exit rules regardless of a pause, `S6-13`'s framing),
and unresolved-exit recovery routing/Operations notification are now
linked via `OPS-007` (intraday EOD-flatten recovery) for the
**intraday** case specifically — V2's own analogous reservation-
release path (`S5-17`) remains separately correct and unaffected.
Verdict unchanged: `Not implemented` for this entry's own atomic-
cancel-on-pause claim.

**Session 9 update (2026-09-17, ~07:12 UTC) — named and distinguished
from a separate dashboard control**: Session 9 §F gives this entry's
own concept a name — **"Pause New Entries"** — and explicitly
distinguishes it from a **separate** dashboard control, **"Pause
Updates"** (which only pauses screen refresh, never execution,
`S9-17`). The two must never be confused: Pause Updates is the
established, real, tested dashboard-refresh-pause feature (Task 140
evidence); Pause New Entries is this entry's own still-unimplemented
V2 intent-cancellation feature. Verdict unchanged: `Not implemented`.

**Session 11 update (2026-09-17, ~10:22 UTC) — codified as an
operational control, still not implemented**: Session 11 §1 restates
Pause New Entries' exact agreed effect — blocks admissions and
atomically cancels unfilled intents, releasing reservations, while
existing positions remain managed (`S11-02`) — and §3's "Stop
Application" control is explicitly **broader**: it also preserves
checkpoints and delivery states and keeps deadlines running offline
(`S11-03`), which Pause New Entries alone does not claim to do. The
two remain distinct controls. Verdict unchanged: `Not implemented`.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — reaffirmed for
Intelligence specifically**: Session 7's development-centric grouping
requirement (`S7-12`) explicitly reaffirms this entry's own point —
grouping developments by "verified entities, transaction/topic, and
relevant dates" (not ticker or accession alone) directly depends on
the same security-identity distinction this entry describes as not
yet implemented. Verdict unchanged: `Not implemented`.

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

**Session 6 update (2026-09-16, ~18:47 UTC)**: Session 6 §F added a
second, related open dependency on this same provider-selection
question — the exact missing-intraday-entry-bar recovery duration
(`S6-26`) cannot be decided until a provider is qualified. **Decision
status unchanged**: still `Open — deferred`; no destination session
assigned.

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

**Session 7 update (2026-09-16, ~20:55 UTC) — sharpened, still not
assessed end-to-end**: Session 7 §F names the same four timestamps
explicitly (occurred/effective, source publication, first local
detection/receipt, notification-sent) and adds UTC-storage/DST-aware-
display conventions (`S7-15`/`S7-16`). This session's own targeted
check re-confirmed the established finding that `freshness_status` is
`UNKNOWN` for 100% of persisted Intelligence events (this project's
Task 140 evidence) — consistent with, not contradicting, this entry's
`Not assessed` verdict for full lineage tracing; the freshness-field
gap specifically is real and disclosed, not newly discovered.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — clarified, kept
distinct**: `S5-19` is now resolved **at the requirements level** by
Session 6 §I (`S6-24`) — see `S5-19`'s own dated update. **This entry's
V2-specific three-session **ENTRY** recovery window is explicitly kept
distinct from Session 6 §H's intraday **NEXT-session-close EXIT**
recovery** (`S6-22`/`S6-23`, tracked under `OPS-007`) — the two are
different mechanisms for different lanes (V2's prospective entry vs.
Original's intraday exit), and Session 6 explicitly states its
intraday recovery rules do not apply to V2. Neither this entry's
`Partially implemented` verdict nor its `OPS-003` gates changed.

**Session 8 update (2026-09-16/17, ~23:05 UTC) — further distinguished
from V2's OWN 5-session exit fall-forward**: this entry's three-session
**ENTRY** recovery window must also be kept distinct from V2's **own**
five-session **EXIT** fall-forward (`S8-09`/`S8-10`, Session 8 §D) —
two different windows, for two different lifecycle phases, within the
SAME strategy (V2), not to be confused with each other or with
intraday's separate recovery (already distinguished above). The entry
window is 3 sessions from the eligible entry session; the exit
fall-forward is up to 5 sessions from the target 10th-session exit —
neither number nor mechanism should be conflated with the other.
Provider-selection/finality remains unresolved for **both** windows
(`OPS-005`, `S8-25`) — this session does not resolve it for either.

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

**Session 6 update (2026-09-16, ~18:47 UTC) — RESOLVED AT REQUIREMENTS
LEVEL**: the product owner agreed the general semantics — evidence
durably received at or before the deadline qualifies, evidence
received afterward cannot qualify the original entry, expiry/
reconciliation are serialized to prevent double-release/double-fill,
and corrections are versioned/auditable, never silent
(`DECISION_LOG.md` Session 6 §I, tracked as `S6-24`). **Decision
status updated**: `Open — deferred` → `Resolved at requirements level
— see S6-24`. **Implementation and validation remain separately
tracked and pending under `OPS-003`** — this resolution answers *what*
the product wants, not *whether* `talonx_v2/service.py`'s actual code
(the `S5-13`/`S5-14`-corrected dual-deadline behavior) yet implements
it correctly; that remains open. `S5-13`'s own dependency on this
entry is now satisfied at the requirements level; `S5-13`'s
implementation status is unaffected and remains as corrected on
2026-09-16 (`Partially implemented`, `OPS-003`).

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

**Session 8 update (2026-09-16/17, ~23:05 UTC) — reaffirmed unchanged**:
Session 8 §C explicitly reaffirms corporate-action handling as target
behavior only, without resetting V2's holding-clock/exit-schedule
(`S8-08`) — no corporate-action code was found or implemented this
session either. Verdict unchanged: `Not implemented`.

**Session 10 update (2026-09-17, ~07:12 UTC) — dividend-consistency
dependency added**: Session 10 §G's dividend-double-counting-
prevention rule (never through both a cash credit **and** an adjusted
historical price, `S10-17`) must be designed **consistently** with
this entry's own price-adjustment-basis requirement — both are
instances of the same "don't adjust the same fact twice" principle.
Neither is implemented; this is a design-consistency dependency for
whenever `OPS-004` is eventually addressed, not a new requirement.
Verdict unchanged: `Not implemented`.

**PQ-2A closure update (2026-09-21) — gatekeeper decision, REVISES this entry for V2 paper
accounting**: the agreed truncate + cash-in-lieu treatment is **superseded**. After a corporate action
a V2 paper position keeps its **exact fractional economic entitlement** (5 shares under a 1-for-10
reverse split = exactly 0.5 share; settled at exit as 0.5 x price). It is never truncated, never
rounded up, and **no cash-in-lieu is fabricated** (no approved/free source provides a reliable
cash-in-lieu execution price). **New entries remain whole-share only** (Package 4 sizing is
unchanged): fractional quantity can only arise later, from a corporate action. Aggregate cost basis
is unchanged by a pure split. `CORP_ACTION_CASH` for cash-in-lieu is therefore not used; ordinary cash
dividends are handled under `S10-17`. Verdict for V2: `Implemented`.

## S5-27 — Decimal arithmetic; cents/4-decimal display; no intermediate truncation

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — auditing
V2's/Original's actual numeric types (whether `Decimal` or `float` is
used internally today) was not performed this session. **Validation**:
Not assessed in this documentation pass. **Dependency**: none
blocking to state the policy; blocking to verify compliance.

**Session 10 update (2026-09-17, ~07:12 UTC) — partial direct evidence
found**: Session 10's own targeted read of `talonx_paper.engine.
calculate_buy()`/`calculate_sell_pnl()` (`talonx_paper/engine.py:71-
93`) found both use plain `float` arithmetic (Python type hints
`float`, `spend / price` division) — **not** `Decimal`. This is
**partial, not complete, evidence**: only this one sizing/P&L function
was read; V2's/Original's full numeric surface (storage columns,
display formatting, other calculation paths) was **not** audited this
session. **Verdict refined**: `Partially implemented` → this specific
function uses `float`, contradicting the agreed high-precision
`Decimal` policy; the full-surface question remains `Not assessed`.

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

---

# Session 6 requirements (S6-01 through S6-26)

Compact format, per `DECISION_LOG.md` Session 6, grouped A–I as
discussed. `S6-25`/`S6-26` are explicit deferrals, not decisions.

## S6-01 — Primary scope = Intraday Opportunities + V2

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — both exist and run today; "primary
scope" is itself a labelling/positioning decision, not a runtime claim,
and is explicitly not a claim of validated profitability or execution
readiness. **Validation**: Code inspection (established + this
session). **Dependency**: `S3-01` (both horizons retained).

## S6-02 — Major-development notifications remain informational

**Decision**: Agreed (reaffirms `S1-02`). **Authorization**: Not
authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: none.

## S6-03 — Fundamental Opportunities = isolated Research Lab candidate (resolves S3-24)

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no such Research Lab candidate
account, promotion workflow instance, or research-bot report exists
yet; this session settles the product category only. **Validation**:
Code inspection (this session — no matching account/workflow found).
**Dependency**: `S3-15`-`S3-20` (the research-lab workflow this
candidate would eventually go through); `S3-24` (resolved by this
entry at the product-positioning level only).

**Session 7 update (2026-09-16, ~20:55 UTC) — scope of "resolved"
clarified**: Session 7 confirms this entry's own caveat explicitly —
"Fundamental Opportunities" was **partially inspected** (a product-
positioning decision only); **full technical qualification of
Original's underlying long-term/fundamentals path remains incomplete**
(`S3-24`'s original technical-review deferral is unaffected by this
entry). No new inspection of that path was performed this session
either.

## S6-04 — Both intraday and multi-day remain primary scope; no demotion

**Decision**: Agreed (reaffirms `S3-01`). **Authorization**: Not
authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: none.

## S6-05 — V2 code-P eligibility definition

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — matches the frozen
`INSIDER_BUY_CLUSTER_V2@1` baseline established in this project's Task
107B/109 history; not re-derived from scratch this session, but
consistent with prior evidence. **Validation**: Code inspection
(established). **Dependency**: none.

## S6-06 — V2 cluster window and detector-activation rules

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — matches the established
frozen baseline (`<=10` trading-session-step filing-date window,
second-distinct-owner activation, greedy non-overlapping episodes, no
minimum amount). **Validation**: Code inspection (established, this
project's Task 107B/109/112R history). **Dependency**: none.

## S6-07 — V2 operational liquidity screen and identity caveats

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented for the liquidity screen
itself (20-session median-volume/price-floor gate, established); the
"frozen contract's broader wording vs. inspected operational path"
distinction is **disclosed, not resolved** — see `OPERATIONAL_FINDINGS.md`
`OPS-006`'s extension. **Validation**: Code inspection (established).
**Dependency**: `OPS-006`.

## S6-08 — Diagnose scarcity via full funnel; no profitability claim

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — this documentation's own framing
(coverage→evidence→clusters→qualification→admission→completed trades)
follows this rule; no trade-count or profitability guarantee is made
anywhere in this documentation layer. **Validation**: Code inspection
(this session, self-check). **Dependency**: none.

## S6-09 — Intraday inspected code defaults

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — directly confirmed this
session: `rsi_oversold=30` (`talonx_quant/config.py:179`),
`macd_fast/slow/signal=12/26/9` (`config.py:158-160`),
`ma_fast/slow=10/50` (`config.py:161-162`),
`min_ma_spread_pct=0.0015` (`config.py:213`),
`min_atr_pct=0.25` (`config.py:355`),
`cooldown_seconds=1200` (20 min, `config.py:196`),
`loss_lockout_seconds=75*60` (`config.py:460`),
`trend_gate_enabled=True` (`config.py:387`). The specific
"confirmation score >= 2" and "minimum RRR 1.5" constants were **not**
individually located by name in this same targeted read — recorded as
given, consistent with the rest of the confirmed defaults, not
independently re-verified. **Validation**: Code inspection (this
session, `talonx_quant/config.py`, exact line numbers above).
**Dependency**: none.

## S6-10 — RSI-recovery/confirmation interaction is intentional

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — this project's own
established "RSI-Curl / Confluence Contract" (Task 28,
`RSI_CONFLUENCE_STATE_BASED_CONFIRMED`, 2026-08-21) directly documents
this as intentional design. **Validation**: Code inspection
(established, `talonx_quant/config.py`'s own inline documentation of
Task 28). **Dependency**: none.

## S6-11 — Diagnostics distinguish 4 categories; mechanisms are not identical

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the four underlying
mechanisms (signal rejection, data/readiness gating, cooldown/lockout
suppression, capacity/cash admission) exist as genuinely distinct code
paths; whether they are surfaced to an operator as one unified,
four-category diagnostic was **not confirmed** this session.
**Validation**: Code inspection (this session, mechanism existence
only). **Dependency**: none blocking.

## S6-12 — Bearish observations never execute/auto-close; legacy mappings verified separately

**Decision**: Agreed (reaffirms `S2-01`/`S2-02`). **Authorization**:
Not authorized. **Implementation**: Not assessed in this documentation
pass — this session explicitly does not claim every legacy code path
was checked; an exhaustive verification was not performed.
**Validation**: Not assessed in this documentation pass. **Dependency**:
none blocking; a candidate for a dedicated legacy-path audit.

## S6-13 — Telegram-eligible despite capacity block; explicit skip explanation

**Decision**: Agreed (extends `S2-03`/`S4-01`). **Authorization**: Not
authorized. **Implementation**: Not implemented — no capacity-
independent alert path was confirmed for Original's intraday lane
specifically this session (V2's own analogous behavior was discussed
under Session 4/5, not re-verified here for Original). **Validation**:
Code inspection (this session, targeted search, no match found).
**Dependency**: none blocking to design.

**Session 7 update (2026-09-16, ~20:55 UTC) — boundary clarified**:
Session 7 §F's company-development freshness rules (`S7-17`) are
**not** automatically applied to trade alerts — this entry's own
capacity-independent trade-alert requirement and Session 6 §D's
expired-opportunity handling remain governed by their own rules,
separate from Intelligence's company-event freshness policy. This
clarification prevents conflating the two domains; no implementation
status changed.

## S6-14 — Expiry-update discipline and duplicate-flood prevention

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no one-time expiry-update
mechanism, three-timestamp display, or flood-prevention logic specific
to this requirement was found. **Validation**: Code inspection (this
session). **Dependency**: `S6-13`.

## S6-15 — Delayed Market Simulation mode

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no separately labelled,
chronological-timestamp-driven simulation mode with its own isolated
account was found. **Validation**: Code inspection (this session).
**Dependency**: `S3-15`-`S3-20` (shares execution rules with the
research-lab replay workflow).

**Session 9 update (2026-09-17, ~07:12 UTC) — message-disclosure
requirement added, still not built**: Session 9 §B requires any
Delayed Market Simulation message to prominently disclose market
time, notification time/data age, and unverified current-entry
validity (`S9-06`) — and requires this mode to be kept separate from
prospective paper accounts on the dashboard (`S9-14`). Both extend,
without resolving, this entry's own "not implemented" verdict.

## S6-16 — Preserve corrected entry-geometry baseline finding

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — directly confirmed this
session by reading `QuantScanner._revalidate_candidate()`
(`talonx_quant/consumer.py:2017`, full-geometry recalculation against
latest buffered close, rejects missing-geometry/expired/insufficient-
RRR) and `fill_geometry_is_valid()` (`talonx_paper/engine.py:156-186`,
`stop_price < fill_price < target_price` when both bounds exist,
returns `True` when either is absent — a documented, pre-existing
convention, not an oversight). Confirms this baseline description is
accurate and rejects any "no revalidation exists" characterization.
**Validation**: Code inspection (this session, exact lines cited
above). **Dependency**: none.

## S6-17 — Approved entry-geometry/next-bar-execution target

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — none of the target's specific
mechanics (freeze-on-approval, next-eligible-bar-open entry,
execution-adjusted RRR recheck, T-10 cutoff-and-cancel) were found in
the inspected code; today's alert-driven entry fires on its own signal
bar, not a deliberately-delayed next bar. **Validation**: Code
inspection (this session — see `S6-16`'s confirmed baseline for what
exists instead). **Dependency**: `OPS-008`, `S6-25` (cost-model
detail), `S6-26` (missing-bar recovery duration).

**Session 10 update (2026-09-17, ~07:12 UTC) — linked to the declared
cost model**: Session 10 §C's "recheck the strategy's applicable
modeled-fill geometry" pre-commit step (`S10-08`) is the general-
accounting version of this entry's own execution-adjusted-RRR-recheck
requirement — the two must eventually share one declared cost model,
not be designed independently. Neither is implemented. `S6-25`'s own
numerical deferral is reaffirmed unchanged, now also tracked alongside
`S10-22` at the same destination (Session 12).

## S6-18 — Spread-adjusted entry ≠ full net-of-fees/exit-cost RRR

**Decision**: Open — deferred (`S6-25`). **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Dependency**: `S6-25`.

## S6-19 — Market-time exit precedence and stop-first ambiguity assumption

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: ~~Not implemented — a repository-wide search for
`AMBIGUOUS_INTRABAR_ORDER` found no matches anywhere in `talonx_paper/`
or elsewhere in the codebase; no code implements market-time exit-
precedence resolution or the stop-first conservative-ambiguity
assumption.~~ **Corrected, see note below.** **Validation**: Code
inspection (this session, repo-wide search, no match). **Dependency**:
`OPS-009`.

**Correction (2026-09-16, ~20:55 UTC) — string-search finding
separated from control-flow evidence**: the repository-wide search for
the exact `AMBIGUOUS_INTRABAR_ORDER` string genuinely found no match —
that part is accurate. But direct reading of `talonx_paper/engine.py`'s
`check_stop_take()` (`engine.py:96-135`) found a real, working
stop-first tiebreak: its own docstring states stop-loss is checked
first "on the (rare) tick where both thresholds are somehow crossed at
once, protecting capital wins the tiebreak over locking in a gain."
**Corrected classification: `Partially implemented`** — the
conservative stop-first *behavior* exists (at per-tick, not
sub-bar/intrabar, granularity, and without the explicit
`AMBIGUOUS_INTRABAR_ORDER` tag or market-time-sequenced multi-source
resolution the target describes). See `OPERATIONAL_FINDINGS.md`
`OPS-009`'s own correction note for the full evidence.

## S6-20 — Stop/gap fill models, exactly-once closure

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: ~~Not implemented — no code matching the declared
stop-crossing/gap-below-stop fill models, extreme-low-fill
prohibition, or stop-market-vs-stop-limit distinction was found; a
repository-wide search for `EXIT_UNRESOLVED`/`EXIT_PENDING` (target
status labels used elsewhere in this design) found no matches in
`talonx_paper/` either.~~ **Corrected, see note below.** Exactly-once
closure at the *position* level (distinct from V2's own exactly-once
*reservation-release*, `S5-17`) was not separately traced this
session. **Validation**: Code inspection (this session, repo-wide
search, no match). **Dependency**: `OPS-009`.

**Correction (2026-09-16, ~20:55 UTC) — string-search finding
separated from control-flow evidence**: the string searches for
`EXIT_UNRESOLVED`/`EXIT_PENDING` genuinely found no match — that part
is accurate, and the gap-below-stop-vs-ordinary-crossing distinct fill
models, the extreme-low-fill prohibition as an explicit rule, and the
stop-market-vs-stop-limit distinction remain genuinely not found.
**However**, exit fills already go through a real, working friction
model: `apply_spread(fill_price, simulated_spread_bps, "SELL")`
(`talonx_paper/consumer.py`, multiple call sites; default 5bps,
`talonx_paper/config.py:99`) — a declared adverse-cost adjustment on
every exit fill, not merely on entries. **Corrected classification:
`Partially implemented`** — a real exit-side cost model exists; the
target's more specific crossing-vs-gap fill-price distinction and
exactly-once position-closure guarantee remain unconfirmed/not found.

## S6-21 — Intraday EOD-flatten inspected baseline

**Decision**: Agreed (inspected baseline). **Authorization**: Not
authorized. **Implementation**: Implemented — directly confirmed this
session: `eod_flatten_hour_et=15`/`eod_flatten_minute_et=50`
(`talonx_paper/config.py:141-143`), `seconds_until_next_eod_flatten()`
(`talonx_paper/engine.py:189-200`) converts via `ZoneInfo` (DST-aware)
with no `exchange_calendars`/session-date check anywhere in
`talonx_paper/consumer.py`'s `_eod_flatten_loop`
(`consumer.py:188-218`) — confirming "DST-aware but not exchange-
calendar-aware" exactly as described. **Validation**: Code inspection
(this session, exact lines cited above). **Dependency**: none.

## S6-22 — Approved EOD-flatten recovery target

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — none of the target's specific
mechanics (close-minus-10-minutes cutoff, durable cross-restart
recovery state, per-account entry block while unresolved, `EXIT_
PENDING`/`EXIT_UNRESOLVED` status labels, deduplicated Operations
notification) were found; today's sweep logs-and-skips a missing price
with no persisted recovery state (`S6-21`'s confirmed baseline).
**Validation**: Code inspection (this session). **Dependency**:
`OPS-007`.

## S6-23 — Shared recovery with per-exit-type own evidence; scope limited to intraday

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no shared intraday-exit-recovery
architecture exists yet to exhibit this per-type-evidence property.
Explicitly **not** applicable to V2 (which keeps its own, separately-
corrected three-session recovery, `S5-13`-`S5-20`) or the Research-
Lab-only fundamentals account (`S6-03`). **Validation**: Code
inspection (this session). **Dependency**: `OPS-007`, `OPS-009`.

**Session 8 update (2026-09-16/17, ~23:05 UTC) — V2's own analogous
mechanism found, kept distinct**: V2 has its own real (not shared with
intraday) version of "per-exit-type own evidence" — the fall-forward
exit records a selected source/reference price/reconciliation time
per position (`S8-09`/`S8-10`), and `EXIT_UNRESOLVED` is V2's own
distinct terminal state, structurally unrelated to this entry's
intraday-only `EXIT_UNRESOLVED`/`EXIT_PENDING` target labels
(`OPS-007`/`OPS-009` remain Original-intraday-scoped; V2's status
names live in a separate codebase, `talonx_v2/store.py`, not
`talonx_paper/`). No entry-status naming is shared or reused between
the two lanes. Verdict unchanged for this (intraday) entry: `Not
implemented`.

## S6-24 — Deadline equality/receipt-vs-processing semantics (resolves S5-19 at requirements level)

**Decision**: Agreed (requirements-level resolution of `S5-19`).
**Authorization**: Not authorized. **Implementation**: Not implemented
— this is a cross-cutting semantics statement, not itself a feature;
whether V2's actual `S5-13`/`S5-14`-corrected code already satisfies it
is exactly `OPS-003`'s own open question, unresolved by this
requirements-level agreement. **Validation**: Code inspection (this
session — no new code re-read specifically against this exact
semantics beyond what `OPS-003` already covers). **Dependency**:
`OPS-003`, `S5-13`, `S5-14`.

## S6-25 — Deferred: numerical spread/slippage/fee assumptions for entry-geometry target

**Requirement**: exact cost-model numbers for `S6-17`'s approved
target. **Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: needs its
own cost-model evaluation, not assumed alongside the qualitative
target. **Planned session**: Session 12 (Technical validation,
usefulness and economic evidence). **Dependency**: `S6-17`.

## S6-26 — Deferred: missing intraday entry-bar recovery duration

**Requirement**: exact bounded-recovery duration for a missing
one-minute interval (`S6-17`). **Decision**: Open — deferred.
**Authorization**: N/A. **Implementation**: N/A. **Validation**: N/A.
**Reason**: depends on which data provider is ultimately qualified —
extends `OPS-005`'s open provider-qualification question, not a
knowledge-transfer-session topic. **Planned session**: none (a
data-provider qualification task). **Dependency**: `OPS-005`.

---

# Session 7 requirements (S7-01 through S7-26)

Compact format, per `DECISION_LOG.md` Session 7, grouped A–H as
discussed. `S7-18`, `S7-25`, `S7-26` are explicit deferrals, not
decisions.

## S7-01 — Primary Telegram = trading opportunities + opted-in major developments

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Implemented — reaffirms `S1-01`/`S1-02`.
**Validation**: Code inspection (established). **Dependency**: none.

## S7-02 — Operations/Research Lab notifications keep separate routing

**Decision**: Agreed (reaffirms `S4-06`/`S4-07`/`S4-08`).
**Authorization**: Not authorized. **Implementation**: Not implemented
— no Operations or Research bot exists. **Validation**: Code
inspection (established). **Dependency**: `S4-07`, `S4-08`.

## S7-03 — Intraday + Insider Buying remain primary scope; no demotion revival

**Decision**: Agreed (reaffirms `S3-01`/`S6-04`). **Authorization**:
Not authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: none.

## S7-04 — No proposed bot/flag described as already deployed

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — this documentation's own framing
complies (self-checked, same discipline as `S4-09`). **Validation**:
Code inspection (this session, self-check). **Dependency**: `S4-09`.

## S7-05 — Six-question qualification rubric

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — the existing content gate
(`notification_policy.py`'s `_substantive_evidence`/
`SUBSTANTIVE_REASON_CODES`) is a coarser, single-axis check (does
non-generic evidence text exist), not six individually-evaluated
rubric questions. **Validation**: Code inspection (this session).
**Dependency**: `S7-06`.

## S7-06 — Versioned materiality-rules catalogue

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — Intelligence's existing
significance engine (`talonx_ingest/intelligence/significance/`,
frozen ruleset `information-significance-v1`) is a band scorer
(LOW/MEDIUM/HIGH/CRITICAL), not a versioned, route-specific
materiality catalogue; the two are related but distinct. **Validation**:
Code inspection (this session, `talonx_ingest/intelligence/
significance/`). **Dependency**: `S7-07`, `S7-08`.

## S7-07 — Route 1: verified significant status change

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no distinct "Route 1" evidence
path was found separate from the general significance/content-gate
mechanism. **Validation**: Code inspection (this session).
**Dependency**: `S7-06`.

## S7-08 — Route 2: measured quantitative development

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no distinct "Route 2" comparable-
metrics/approved-threshold mechanism was found; existing XBRL-magnitude
evidence (`SUBSTANTIVE_REASON_CODES`'s `XBRL_MAGNITUDE`) is the closest
existing precedent but is not itself the versioned, event-specific
threshold catalogue this route describes. **Validation**: Code
inspection (this session). **Dependency**: `S7-06`, `S7-26`.

## S7-09 — Routine earnings dashboard-only unless qualifying

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing a real earnings-release event through the current pipeline to
confirm whether it is ever dashboard-only vs. always routed the same
way; not performed this session. **Validation**: Not assessed in this
documentation pass. **Dependency**: `S7-06`.

## S7-10 — Missing-reason handling; never infer misconduct/distress/price direction

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `claim_safety.py`'s
predictive-language block (`talonx_ingest/intelligence/delivery/
claim_safety.py:42`) rejects price-target/expected-return language,
matching the "never infer future price direction" half; it does
**not** separately guard against inferring misconduct or distress —
that half is not confirmed to exist. **Validation**: Code inspection
(this session, exact line cited). **Dependency**: none blocking.

## S7-11 — Plain-language presentation content list

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — most elements
have established precedent (one-sentence evidence lead, reply-for-
details, informational/no-trade framing); the "avoid unexplained SEC
jargon" element has a known, open gap (`S1-05`'s real-message
citation-syntax finding, unresolved). **Validation**: Code inspection
(established + this session). **Dependency**: `S1-05`.

## S7-12 — Development record links multiple filings/sources

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — `DeliveryOutbox`
(`talonx_ingest/intelligence/delivery/outbox.py`) operates on a single
`delivery_id` per `event_id`; no `development_id`/group/topic field
was found. **Validation**: Code inspection (this session,
`outbox.py:204,774`). **Dependency**: `S5-02` (security-identity
distinction), `OPS-010`.

## S7-13 — Grouping rules: duplicates enrich, distinct developments separate, no fabrication

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — depends on `S7-12`'s grouping
mechanism, which does not exist. **Validation**: Code inspection (this
session). **Dependency**: `S7-12`, `OPS-010`.

## S7-14 — UPDATE vs. CORRECTION distinction

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `update_policy.py`'s
`classify_update()` (`talonx_ingest/intelligence/delivery/
update_policy.py`) implements a real, deterministic `NEW`/`UPDATE`/
`SUPPRESS_DUPLICATE`/`SUPPRESS_NOOP` decision keyed on `content_hash`
and significance band — genuine precedent for the `UPDATE` half. **No
`CORRECTION` decision type exists** — a materially-wrong repair and a
genuine new material change are not currently distinguished.
**Validation**: Code inspection (this session, full file read).
**Dependency**: `OPS-010`.

**Session 9 update (2026-09-17, ~07:12 UTC) — boundaries preserved,
kept distinct from a different consolidation rule**: Session 9 §D's
material-correction boundaries (eligible despite mutes, must not
bypass global delivery shutdown or a revoked destination, never
broadcast to new recipients) are **reaffirmed unchanged** — Session 9
does not touch `CORRECTION`'s missing decision type. Session 9 §D's
own obsolete-pending-notification consolidation rule (`S9-11`,
combining stale pending messages into one truthful `OPEN` message) is
a **different** mechanism from `CORRECTION` — a pre-send consolidation
of not-yet-delivered messages, not a post-send repair of already-
delivered ones — and must not be conflated with it. Both remain
unimplemented; `OPS-010` and `OPS-013` are separate, related findings.

## S7-15 — Four distinct timestamps kept separate

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — see `S5-12`'s dated
update: the mechanism for tracking distinct timestamps exists in
concept, but `freshness_status` is `UNKNOWN` for 100% of persisted
events (established Task 140 finding, re-confirmed relevant, not
re-run this session). **Validation**: Code inspection (established).
**Dependency**: `S5-12`.

## S7-16 — UTC storage; DST-aware display; no hardcoded BST

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — this project's
own established UK-time discipline (Python `zoneinfo`, used
consistently in every documentation session including this one)
demonstrates the DST-aware display convention works correctly when
used; a dashboard/renderer-wide audit for any hardcoded BST was **not**
performed this session. **Validation**: Code inspection (established;
this session's own reporting practice). **Dependency**: none blocking.

## S7-17 — Freshness follows source-publication time; no restart-refresh; flood prevention

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — `reclassify_
pending_rows`'s established content-refresh behavior (Task 140c, this
project's history) demonstrates freshness-aware re-evaluation exists
in some form; a full audit against every sub-clause (restart-doesn't-
refresh-age, stale-backlog-flood-prevention specifically) was not
performed this session. **Validation**: Code inspection (established).
**Dependency**: `S7-18`.

**Session 8 update (2026-09-16/17, ~23:05 UTC) — boundary clarified**:
Session 8 confirms Intelligence's company-event freshness policy and
per-stock mute (`S7-20`) do **not** automatically govern V2's or
Original's own trade-lifecycle notifications, nor Operations
incidents (`S7-02`) — these remain three separate notification
domains with their own rules (Session 7 §A's routing separation,
reaffirmed). V2's own lifecycle-status disclosure (`S8-12`/`S8-13`)
follows V2's own agreed rules, not Intelligence's freshness policy.
Verdict unchanged: `Partially implemented`.

## S7-18 — Deferred: numerical freshness windows

**Decision**: Open — deferred (`S7-25`). **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Dependency**: `S7-25`.

## S7-19 — Major-dev opt-in explicit, persisted across restarts

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing the actual opt-in flag's persistence mechanism, not performed
this session. **Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S7-20 — Per-stock company-event mute; independent of trading pause

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented (mute) / Implemented (pause-
monitoring independence) — a search of `talonx_ingest/intelligence/
dashboard/render.py` for "mute" found only a CSS class name (`.muted`,
text styling), confirming no per-stock company-event mute feature
exists. Separately, Original's ticker-pause (`talonx_watchlist/
store.py`, `S3-11`) and Intelligence's own collection scope
(`talonx_ingest/intelligence/service/scope.py`) are structurally
separate systems (`S3-08`/`OPS-006`) — so "trading pause does not
auto-pause company monitoring" is true today, as a side effect of the
systems being unmerged rather than a deliberately designed control.
**Validation**: Code inspection (this session, exact files cited).
**Dependency**: `OPS-011`.

## S7-21 — Material corrections: eligible despite mutes, must link/identify, never bypass shutdown

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — depends on a `CORRECTION`
decision type (`S7-14`) that does not exist yet; a global-delivery-
shutdown/destination-revocation bypass guard specific to corrections
was not found (nor searched for independently of the missing
`CORRECTION` type itself). **Validation**: Code inspection (this
session). **Dependency**: `S7-14`, `OPS-010`.

## S7-22 — Distinguish qualification / eligibility / attempts / confirmed delivery

**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — `DeliveryOutbox`
already has distinct states for attempts and outcomes (`SENT`,
`PENDING`, `AMBIGUOUS`, established this project's history); whether
"event qualification" and "delivery eligibility" are equally
distinctly tracked as their own separate concepts (not just
attempt/outcome) was not separately confirmed this session.
**Validation**: Code inspection (established + this session).
**Dependency**: none blocking.

## S7-23 — Five distinct coverage dimensions, may co-occur

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no unified surface presenting
all five dimensions (no-qualifying-development / collection-delayed /
extraction-incomplete / identity-unresolved / qualified-but-muted) as
distinct, co-occurring states was found. **Validation**: Code
inspection (this session). **Dependency**: `S7-20` (mute is one of the
five dimensions).

## S7-24 — Empty feed ≠ nothing happened; no exhaustive-coverage claim

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — this documentation's own framing
complies (no exhaustive-coverage claim made anywhere in this product-
documentation layer); the dashboard's own actual wording for this
specific disclosure was not separately audited this session.
**Validation**: Code inspection (this session, self-check).
**Dependency**: none.

## S7-25 — Deferred: numerical freshness windows

**Requirement**: exact freshness-window numbers for §F. **Decision**:
Open — deferred. **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: requires a bounded review of
representative historical filings (selection method, examples, false
positives/misses, coverage limitations, proposed acceptance criteria)
before any number is chosen — not performed here; no number is
invented. **Planned session**: none assigned (a future bounded-review
task). **Dependency**: none blocking.

## S7-26 — Deferred: event-specific quantitative materiality thresholds

**Requirement**: exact Route 2 threshold numbers (§C). **Decision**:
Open — deferred. **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: same bounded-review requirement as
`S7-25`; this documentation task does not authorize a new extraction/
LLM project by implication. **Planned session**: none assigned.
**Dependency**: `S7-08`.

---

# Session 8 requirements (S8-01 through S8-18, S8-25, S8-26)

Compact format, per `DECISION_LOG.md` Session 8, grouped A–G as
discussed. `S8-25`/`S8-26` are explicit deferrals, not decisions.

## S8-01 — Pre-open admission deadline

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented — `V2Service._verify_temporal_
boundary()` (`talonx_v2/service.py:796-`) is a real, fail-closed check
that both the activating filing's dissemination and the admission
decision itself occurred strictly before the entry session's RTH open;
an unknown dissemination timestamp is a strict failure on any live
tick. **Validation**: Code inspection (this session, full docstring +
logic read). **Dependency**: none.

## S8-02 — No retrospective entry; distinct timestamps; no guaranteed overnight completion

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `S8-01`'s temporal-
boundary check structurally prevents retrospective entry; whether
filing-availability, first-receipt, and durable-admission are tracked
as three genuinely separate, disclosed timestamps (vs. just enforced
internally) was not traced end-to-end this session. **Validation**:
Code inspection (this session, partial). **Dependency**: `S8-01`.

## S8-03 — Truthful late-discovery status; capacity-skipped still notify

**Decision**: Agreed (reaffirms `S2-03`/`S2-04`/`S6-13`).
**Authorization**: Not authorized. **Implementation**: Partially
implemented — extends `S6-13`'s own verdict (not implemented for
Original's intraday lane specifically; V2's own capacity-skip
disposition codes, `NO_CASH` etc., are real per `S2-03`'s evidence).
**Validation**: Code inspection (established). **Dependency**: `S2-03`,
`S6-13`.

## S8-04 — Delayed entry-price reservation and reconciliation-source discipline

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the retry-then-release
mechanism is real (`FAILED_NO_MARKET_DATA`, `S5-16`'s established
finding); whether the code could ever reconcile against something
other than the exact target-session opening reference was not
separately re-tested this session, though no such substitution path
was found in the code read across this and prior sessions.
**Validation**: Code inspection (established). **Dependency**: `S5-13`,
`S5-16`.

## S8-05 — Session-3-close recovery applies; intraday next-bar rules excluded

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — matches `S5-13`'s
2026-09-16-corrected verdict exactly (session-based recovery exists;
exact Session-3-close enforcement and pre-fill expiry remain pending
`OPS-003`). Intraday next-bar simulation (`S6-16`/`S6-17`) is
confirmed structurally inapplicable to V2 — the two codebases
(`talonx_v2/`, `talonx_quant`/`talonx_paper/`) are separate.
**Validation**: Code inspection (established, `S5-13`'s correction).
**Dependency**: `S5-13`, `S5-19`, `OPS-003`.

## S8-06 — Holding clock: Session 0 entry, 10th-session close exit

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `hold_trading_days=10`
with a runtime assert (`talonx_v2/config.py:34,88`); `add_sessions()`
is calendar-based (non-trading days never increment). **Validation**:
Code inspection (this session, exact lines). **Dependency**: none.

**Session 12 update (2026-09-17, ~10:22 UTC) — reaffirmed for research
promotion specifically**: Session 12 §8 explicitly reaffirms that
existing positions retain their original rules through any future
strategy promotion, and research profits are never transferred into a
primary campaign (`S12-20`) — this is the same frozen-holding-clock
principle this entry already establishes, extended to the
promotion/versioning context. Verdict unchanged: `Implemented`.

## S8-07 — No stop-loss; no cluster-triggered additions; obligations survive pause/exclude/scope-removal

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented for no-stop-loss
(`stop_loss_enabled=False` with a runtime assert, `config.py:36,94`,
established) and no-cluster-triggered-additions
(`SYMBOL_ALREADY_OPEN` skip, `S2-03`'s evidence). **Not assessed**:
whether a scope-removal/exclusion event specifically preserves an
already-open V2 position's obligations — no scope-removal code path
was traced this session. **Validation**: Code inspection (established
+ this session). **Dependency**: `S3-11` (Pause/Exclude semantics).

## S8-08 — Missing valuations never fabricated zero; corporate actions target-only; no whole-share assumption

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented for the missing-valuation half
(reaffirms `S2-12`'s established `equity_value = None`-not-zero
evidence); **Not implemented** for the corporate-action half — no such
code exists (`OPS-004`, unchanged). **Validation**: Code inspection
(established). **Dependency**: `S2-12`, `OPS-004`.

## S8-09 — Three-step frozen fall-forward contract

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `settle_due_exits()`
(`talonx_v2/pipeline.py:132-202`) matches the target→earliest-of-
next-5→`EXIT_UNRESOLVED` contract exactly; the code's own comment
states "Never backwards. Never 'best price.'" **Validation**: Code
inspection + **isolated test execution** (`tests/
test_task117_phase0_entry_timing.py::
test_e8c_exit_unresolved_when_target_and_all_fallforward_missing`, run
this session, passed). **Dependency**: none.

## S8-10 — "First available" is deterministic, not race-arrival; full record-keeping

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the selection itself is
deterministic (a plain `for k in range(1, ff_max+1)` loop trying
sessions in strict forward order, `pipeline.py:155-162`, not a race
against provider response times); whether target session, actual
exit session, selected source, reference price, and reconciliation
time are ALL individually recorded as separate fields (vs. some being
implicit/derivable) was not exhaustively traced this session.
**Validation**: Code inspection (this session, loop structure).
**Dependency**: none blocking.

## S8-11 — Committed exit never silently replaced; correcting entries are versioned

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — requires
tracing what happens if a price provider later revises an
already-used closing print, not performed this session. **Validation**:
Not assessed in this documentation pass. **Dependency**: `OPS-005`.

## S8-12 — EXIT_PENDING·AWAITING_PRICE account behavior

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the underlying behavior is
structurally correct (an unresolved exit's position stays in
`open_positions()`, occupying capacity via `n_open()`, and no proceeds
are credited until `close_position()` actually runs); the literal
`EXIT_PENDING · AWAITING_PRICE` label was not found — the code's own
name is `EXIT_BAR_PENDING_FALLFORWARD` (`pipeline.py:179`), a naming
gap not a behavior gap. **Validation**: Code inspection (this
session). **Dependency**: none blocking.

**Session 10 update (2026-09-17, ~07:12 UTC) — phantom-proceeds
prevention reaffirmed at the general-accounting level**: Session 10
§B/§H's own no-fabricated-cash-on-release rule (`S10-03`, `S10-04`)
and no-phantom-proceeds requirement for pending/unresolved exits
(`S10-21` references this entry directly) restate this entry's own
"no anticipated sale proceeds are credited or reused" rule at the
account-ledger level. No implementation changed; verdict unchanged.

## S8-13 — EXIT_UNRESOLVED account-block behavior

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `mark_exit_unresolved()`
(`talonx_v2/store.py:410-419`) sets a real, distinct status,
correctly not cleared by a restart (it's a durable DB row, not
in-memory state) and correctly surfaced via
`store.unresolved_positions()` in service status output
(`service.py:1054,1159`). **Genuine gap**: no code path was found that
blocks NEW entries account-wide while an `EXIT_UNRESOLVED` position
exists — `unresolved_positions()` is read only for reporting, never
consulted by `open_position()`'s own admission gate. **Validation**:
Code inspection (this session, both files read in full relevant
sections). **Dependency**: `OPS-012`.

**Session 10 update (2026-09-17, ~07:12 UTC) — same pattern confirmed
at the general-ledger level, kept distinct**: Session 10 §H's own
account-block requirement on a genuine reconciliation mismatch
(`S10-21`, tracked as the new `OPS-015`) is the **same structural
gap** as this entry's `OPS-012` — detection/status exists, enforcement
does not — but for a **different trigger** (ledger mismatch vs.
exhausted fall-forward) and **must not be merged into one finding**;
`OPS-012` and `OPS-015` remain separate, both `OPEN`. Session 10 §H
also explicitly assigns "block-clearance authority and evidence" to
Session 11 — this entry's own clearance mechanism (never cleared by a
restart) remains correct and unaffected.

## S8-14 — CLOSED: exactly-once settlement

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `paper.close_position()`
(`talonx_v2/paper.py:155-191`) commits position-close, cash-credit,
trade-record, and cooldown-set together inside one
`store.transaction()`, matching Task 131's own "Remediation Directive
4" comment; a duplicate close is structurally impossible since
`close_position`'s own SQL is `WHERE ... AND status='OPEN'`.
**Validation**: Code inspection (this session, exact lines) +
established `test_task131_atomic_transactions.py` evidence (run this
session, passed). **Dependency**: none.

## S8-15 — Cooldown anchored to actual modeled exit session

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `close_position()`
computes `cooldown_until = add_sessions(exit_session, cfg.
reentry_cooldown_trading_days)` using the actual `exit_session`
**parameter** (the post-fall-forward value from `settle_due_exits()`,
not the original target session) — directly confirming the agreed
anchor. `reentry_cooldown_trading_days=5` is frozen with a runtime
assert (`config.py:45,91`). **Validation**: Code inspection (this
session, `paper.py:164,188`). **Dependency**: none.

## S8-16 — First eligible re-entry session (boundary, directly resolved)

**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `open_position()`'s own
gate (`talonx_v2/paper.py:104-106`) reads `if cd is not None and es <
cd: skip`, blocking entry only when the candidate entry session is
**strictly before** `cooldown_until`. **The boundary is directly
resolved by this code, not left ambiguous: the first eligible
re-entry session is exactly `exit_session + 5` trading sessions
(inclusive at +5), not +6.** This satisfies this task's own "boundary
verification still required" instruction — the counting convention was
not silently chosen; it was read directly from the comparison
operator. Cooldown ending alone never generates a BUY — a fresh
qualifying episode and timely admission are still required
structurally (the cooldown check is only one of several independent
gates in the same function). **Validation**: Code inspection (this
session, exact operator read). **Dependency**: none.

## S8-17 — Acceptance evidence tracked separately per lifecycle guarantee

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented (as a documentation
discipline) — items 1 (restart, no duplicate entry), 2 (interruption,
no duplicate economic effect), and 4 (earliest fall-forward, never
best) were directly, freshly exercised this session (23 tests run
across `test_task131_atomic_transactions.py` and
`test_task117_phase0_entry_timing.py`, all passed). Items 3, 5, 6, 7,
8 were **not** individually re-verified this session — 3 relies on
`S8-05`'s established (corrected) evidence, 6 relies on `S8-12`'s
structural finding, 7 is blocked entirely on `OPS-004` (no
corporate-action code exists to test), 8 relies on `S4-10`'s
established execution/delivery-separation evidence, and 5
(scope-removal) was not traced at all this session. **Validation**:
Code inspection + isolated test execution (this session, exact test
names and counts cited). **Dependency**: `OPS-004`, `OPS-012`.

## S8-18 — Boundary coverage identified; no overclaiming from unrelated evidence

**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented (as a documentation
discipline) — this entry itself follows the rule: `S8-16`'s cooldown
boundary was directly resolved (not asserted from an unrelated test),
`S8-09`'s fall-forward-exhaustion boundary was directly tested this
session, and `S8-01`'s admission-at-vs-before-open boundary was
confirmed by direct code reading. **Not located this session**: a
dedicated test spanning a holiday or early-close specifically for the
fall-forward loop or the admission deadline (`S8-26`). **This session
does not claim the entire V2 lifecycle is accepted** — no zero-
position live session or unrelated passing test is cited as blanket
evidence anywhere in this documentation. **Validation**: Code
inspection + isolated test execution (this session, self-check).
**Dependency**: `S8-26`.

## S8-25 — Deferred: provider finality/publication-qualification boundary

**Requirement**: the exact boundary between provisional/delayed and
genuinely unavailable target-closing data (§D). **Decision**: Open —
deferred. **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: depends on which data provider is
ultimately qualified — extends `OPS-005`. No waiting duration is
invented. **Planned session**: none (a data-provider qualification
task). **Dependency**: `OPS-005`.

## S8-26 — Deferred: holiday/early-close-spanning boundary test coverage

**Requirement**: dedicated test coverage for the fall-forward loop and
admission deadline across a holiday or early-close (§D/§G).
**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: not located
or authored this session; requires its own implementation-verification
task, not a knowledge-transfer session. **Planned session**: none.
**Dependency**: `S8-25`.

---

# Session 9 requirements (S9-01 through S9-20)

Compact format, per `DECISION_LOG.md` Session 9, grouped A–F.

## S9-01 — Primary Trade & Event bot scope
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no dedicated bot exists.
**Validation**: Code inspection (established). **Dependency**: none.

## S9-02 — Separate Operations bot
**Decision**: Agreed (reaffirms `S4-07`). **Authorization**: Not
authorized. **Implementation**: Not implemented. **Validation**: Code
inspection (established). **Dependency**: `S4-07`.

## S9-03 — Optional Research bot isolated, OFF by default
**Decision**: Agreed (reaffirms `S3-21`/`S4-08`). **Authorization**:
Explicitly not authorized. **Implementation**: Not implemented.
**Validation**: Code inspection (established). **Dependency**: `S4-08`.

## S9-04 — Target framing; qualified ≠ profitable
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (this documentation's own compliance).
**Validation**: Code inspection (self-check). **Dependency**: none.

## S9-05 — Compact-message content requirements
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no "Opportunity status"/"Paper
status" separate-line format was found. **Validation**: Code
inspection (this session). **Dependency**: `S9-08`.

## S9-06 — Delayed Simulation message disclosure
**Decision**: Agreed (extends `S6-15`). **Authorization**: Not
authorized. **Implementation**: Not implemented — `S6-15`'s mode
itself does not exist yet. **Validation**: Code inspection (this
session). **Dependency**: `S6-15`.

## S9-07 — Details/dashboard scope; limitations never hidden
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S9-08 — Main lifecycle notification set
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — the underlying mechanisms
(per-strategy skip codes, `UPDATE` decisions) exist; the four-
transition policy as its own explicit rule does not. **Validation**:
Code inspection (this session — `OPS-013`). **Dependency**: `OPS-013`.

## S9-09 — Dashboard-only routine updates
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S9-10 — Exit-problem routing; avoid redundancy
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no Operations bot exists to
route to. **Validation**: Code inspection (this session — `OPS-013`).
**Dependency**: `S9-02`, `OPS-013`.

## S9-11 — Obsolete-pending consolidation
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented. **Validation**: Code inspection
(this session — `OPS-013`). **Dependency**: `OPS-013`.

## S9-12 — No blind post-downtime flush; truthful catch-up
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `S4-05`'s established no-
alert-flood evidence supports the intent; the specific consolidation-
into-one-message behavior was not found. **Validation**: Code
inspection (established + this session). **Dependency**: `S4-05`.

## S9-13 — Ambiguous delivery not blindly retried; separate guarantees
**Decision**: Agreed (reaffirms established `AMBIGUOUS` contract).
**Authorization**: Not authorized (pre-existing). **Implementation**:
Implemented. **Validation**: Code inspection (established, Task 96F/
117 history). **Dependency**: none.

## S9-14 — Default overview excludes Research Lab; no blended totals
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass —
vacuously true today since no Research Lab account exists (`S6-03`).
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S6-03`.

## S9-15 — Top-to-bottom dashboard layout
**Decision**: Agreed (extends `S2-10`). **Authorization**: Not
authorized. **Implementation**: Not implemented — extends `S2-10`'s
own established gap (no Action-Required banner or this exact layout
order found). **Validation**: Code inspection (established, `S2-10`).
**Dependency**: `S2-10`.

## S9-16 — Distinct Research View; no double-counting
**Decision**: Agreed (reaffirms `S3-13`). **Authorization**: Not
authorized. **Implementation**: Not implemented. **Validation**: Code
inspection (established). **Dependency**: `S3-13`.

## S9-17 — Pause Updates ≠ Pause New Entries
**Decision**: Agreed (reaffirms `S4-12`/`S8-07`). **Authorization**:
Not authorized. **Implementation**: Partially implemented — Pause
Updates (dashboard refresh pause/resume) is real and tested (Task 140
evidence); Pause New Entries (V2 intent cancellation) is not
implemented (`S4-12`). **Validation**: Code inspection (established).
**Dependency**: `S4-12`.

## S9-18 — Domain-specific mutes; refresh controls; state preservation
**Decision**: Agreed. **Authorization**: Not authorized (pre-existing,
partial). **Implementation**: Partially implemented — auto-refresh
scroll/focus/panel preservation is real and tested (Task 140); domain-
specific mutes are not implemented (`S7-20`/`OPS-011`). **Validation**:
Code inspection (established, Task 140 evidence). **Dependency**:
`OPS-011`.

## S9-19 — Full-reload restoration not claimed; assess not assume
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (this documentation's own honest
scoping — the established fix is re-confirmed to cover auto-refresh
only, not a full page reload). **Validation**: Code inspection (this
session, re-reading Task 140 evidence). **Dependency**: none.

## S9-20 — Dashboard P&L doesn't replace EOD Telegram
**Decision**: Agreed (reaffirms `S2-07`/`S4-13`). **Authorization**:
Not authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: none.

---

# Session 10 requirements (S10-01 through S10-21, S10-22 through S10-25)

Compact format, per `DECISION_LOG.md` Session 10, grouped A–I.
`S10-22`-`S10-25` are explicit deferrals, not decisions.

## S10-01 — Account identity fields
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — whether
every account surface displays all five identity fields together was
not traced. **Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S10-02 — New-campaign defaults, fee-inclusive; USD-only initial scope
**Decision**: Agreed (extends `S3-12`/`S3-14`). **Authorization**: Not
authorized. **Implementation**: Not implemented (new default itself);
Implemented (existing-accounts-unchanged half, reaffirms `S3-14`).
**Validation**: Code inspection (established). **Dependency**: `S3-12`,
`S3-14`.

## S10-03 — Atomic reservation; available vs. ledger cash; no equity impact
**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — `talonx_v2/paper.py`'s reserve-then-
execute pattern (established, re-confirmed this session).
**Validation**: Code inspection (established + this session).
**Dependency**: none.

## S10-04 — Atomic execution debit; exactly-once release; consistency
**Decision**: Agreed (reaffirms `S5-17`). **Authorization**: Not
authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: `S5-17`.

## S10-05 — Cost-free illustrative sequence
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (illustrative content, this
documentation). **Validation**: Code inspection (self-check).
**Dependency**: none.

## S10-06 — Separate spread/fees/reference basis; no double-counting
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `apply_spread`-style
spread-in-fill is real (established, Original's `talonx_paper/
engine.py`); V2 itself has no separate explicit-fee ledger line found
this session. **Validation**: Code inspection (established + this
session). **Dependency**: none blocking.

## S10-07 — Whole-share, fee-aware sizing formula
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — `talonx_paper.engine.
calculate_buy()` (reused by V2, `talonx_v2/paper.py:25,115`) returns
`spend / price`, a continuous fractional share count with no fee
parameter at all. **Validation**: Code inspection (this session,
`engine.py:71-83` — `OPS-014`). **Dependency**: `OPS-014`.

## S10-08 — Whole-share-within-budget vs. cash-driven reduction; pre-commit checks
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — depends on `S10-07`'s sizing
mechanism, which does not exist as described. **Validation**: Code
inspection (this session — `OPS-014`). **Dependency**: `S10-07`,
`OPS-014`.

## S10-09 — Illustrative sizing example
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (illustrative content, this
documentation). **Validation**: Code inspection (self-check).
**Dependency**: none.

## S10-10 — Net proceeds/P&L formulas; reconcilable gross/net
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — the
exact realized-P&L formula (`talonx_paper/engine.py::
calculate_sell_pnl`) was read in a prior session but its fee-inclusion
correctness was not re-verified against this exact formula this
session. **Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S10-11 — Costs ≠ auto-loss; no invented return methodology
**Decision**: Agreed (reaffirms `S2-10`/`S2-12`). **Authorization**:
Not authorized. **Implementation**: Implemented (missing-valuation-
never-zero half, established); the return-methodology half is
explicitly left pending, not invented. **Validation**: Code inspection
(established). **Dependency**: `S2-10`, `S2-12`.

## S10-12 — Position-limit slot-counting rules
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — the limit itself is real
(`S10-13`); whether pending/open/unresolved/fall-forward each
correctly count as claimed was not individually traced this session.
**Validation**: Code inspection (this session, partial). **Dependency**:
`S10-13`.

## S10-13 — V2's frozen 20-position limit preserved
**Decision**: Agreed (pre-existing). **Authorization**: Not
authorized. **Implementation**: Implemented — `max_concurrent_
positions = 20` with a runtime assert (`talonx_v2/config.py:44,90`).
**Validation**: Code inspection (this session, exact lines).
**Dependency**: none.

## S10-14 — Same-stock cross-account exposure display
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no exposure-display surface
(security/sector, cross-account) was found. **Validation**: Code
inspection (this session). **Dependency**: none blocking.

## S10-15 — Cash-only boundaries; truthful deficit recording
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — no-shorts/explicit-skip-
on-insufficient-cash is established (`S2-03`'s `NO_CASH` evidence);
deficit-recording-with-Operations-raise was not found this session.
**Validation**: Code inspection (established + this session).
**Dependency**: `S9-02` (Operations bot doesn't exist to raise to).

## S10-16 — Deposits/withdrawals explicit and auditable
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no deposit/withdrawal feature
exists anywhere in the codebase inspected this session. **Validation**:
Code inspection (this session). **Dependency**: none blocking.

## S10-17 — Dividend accounting rules
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no dividend-handling code exists
(`OPS-004`). **Validation**: Code inspection (established).
**Dependency**: `OPS-004`.

**PQ-2A closure update (2026-09-21) — gatekeeper decision: total return RETAINED; contract
implemented for V2.** Performance = price P&L (`positions.realized_pnl_usd`, fee-inclusive) +
credited ordinary cash dividends (`dividend_entitlements`). Contract: (1) explicit provider event
(Alpaca `/v1/corporate-actions`; amount = raw per-share rate as of the ex-date), never inferred from
price; (2) entitled iff `entry_session < ex_date <= exit_fill_session` (a buyer on/after the ex-date is
not entitled; a seller on/after it keeps the dividend); (3) quantity = exact economic shares at the
ex-date from the split trail (10 sh -> 10:1 -> 100 sh, later $0.20 => $20); (4) `ACCRUED` receivable
recorded atomically with settlement, `CREDITED` to cash on/after `payable_date` after a fresh provider
re-confirmation, including after the trade is CLOSED (no trade is reopened), never without a
payable date; (5) no double count: fills must be RAW/SPLIT_ADJUSTED (live adapters now request the
split-only basis), otherwise a position with an eligible dividend fails closed; (6) special, foreign,
malformed, zero/negative/NaN dividends are unsupported => fail closed; (7) cash equation:
`cash + open cost + unresolved cost = starting + price P&L + credited dividends`; accrued
receivables count in equity, not cash; (8) idempotent by content key + once-only conditional UPDATE.

## S10-18 — Preserve Session 5 split/cash-in-lieu requirements
**Decision**: Agreed (reaffirms `S5-21`-`S5-27`). **Authorization**:
Not authorized. **Implementation**: Not implemented (`OPS-004`,
unchanged). **Validation**: Code inspection (established).
**Dependency**: `OPS-004`.

## S10-19 — Unsupported corporate actions stay unresolved
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented (`OPS-004`, unchanged).
**Validation**: Code inspection (established). **Dependency**:
`OPS-004`.

## S10-20 — EOD/restart 7-item reconciliation scope
**Decision**: Agreed (extends `S4-13`). **Authorization**: Not
authorized (pre-existing, partial). **Implementation**: Partially
implemented — `talonx_ops/eod_reconciliation.py` performs real
detection; whether all 7 listed items (ledger cash, reservations,
positions/quantities, fees, distributions/receivables, capital flows,
corporate actions/corrections) are each individually reconciled was
not traced item-by-item this session. **Validation**: Code inspection
(established + this session, partial). **Dependency**: none blocking.

## S10-21 — Genuine mismatch blocks new admissions
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — `STATUS_MISMATCH`
(`talonx_ops/eod_reconciliation.py:43`) is detected but not connected
to any admission-blocking code path. **Validation**: Code inspection
(this session, exact line — `OPS-015`). **Dependency**: `OPS-015`,
Session 11 (clearance authority).

## S10-22 — Deferred: numerical spread/slippage/fee assumptions
**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: needs a
cost-model evaluation. **Planned session**: Session 12 (reaffirms
`S6-25`/`S8-25`). **Dependency**: `S6-25`.

## S10-23 — Deferred: cross-account hard concentration limits
**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: requires
bounded evaluation before activation; no numerical limit invented.
**Planned session**: none assigned. **Dependency**: none blocking.

## S10-24 — Deferred: correlation-based admission gates
**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: same
bounded-evaluation requirement. **Planned session**: none assigned.
**Dependency**: none blocking.

## S10-25 — Deferred: concentration-warning thresholds
**Decision**: Open — deferred. **Authorization**: N/A.
**Implementation**: N/A. **Validation**: N/A. **Reason**: same
bounded-evaluation requirement; no numerical threshold invented.
**Planned session**: none assigned. **Dependency**: `S10-23`, `S10-24`.

---

# Session 11 requirements (S11-01 through S11-19)

Compact format, per `DECISION_LOG.md` Session 11, grouped 1–6.

## S11-01 — Pause Updates = dashboard refresh only
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (Task 140 dashboard pause/resume).
**Validation**: Code inspection (established). **Dependency**: none.

## S11-02 — Pause New Entries blocks admissions + cancels intents
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented (`S4-12`). **Validation**: Code
inspection (established). **Dependency**: `S4-12`.

## S11-03 — Stop Application state preservation; Resume semantics
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — the
`stop_stack()` mechanism preserves databases (established), but
whether "Resume never resurrects a cancelled intent" holds was not
traced (no cancel mechanism exists yet, `S11-02`). **Validation**: Not
assessed in this documentation pass. **Dependency**: `S11-02`.

## S11-04 — Controlled shutdown sequence
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — `stop_stack()`/
`run_close()` (`talonx_ops/prospective/proc.py`, `close.py`,
established EOD-closure evidence) genuinely persist state and stop
processes cleanly; explicit admission-blocking-before-shutdown was not
found as its own step. **Validation**: Code inspection (established).
**Dependency**: none blocking.

## S11-05 — Offline-risk warning; unattended-shutdown abort condition
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no such warning or abort
condition was found. **Validation**: Code inspection (this session).
**Dependency**: none blocking.

## S11-06 — Restart verification sequence
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — ownership verification
(startlock/PID registry, established EOD-closure evidence) and ledger
reconciliation (`run_close()`) are real; obligation-classification and
data-readiness assessment as explicit, separate restart steps were not
individually confirmed. **Validation**: Code inspection (established).
**Dependency**: none blocking.

## S11-07 — Restart gates restrict admissions only
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S11-06`.

## S11-08 — V2 price-recovery vs. admission-deadline distinction
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Partially implemented — matches `S8-05`'s
corrected verdict, `OPS-003`'s gates remain open. **Validation**: Code
inspection (established). **Dependency**: `OPS-003`.

## S11-09 — Durably-received-by-deadline evidence may process later
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented as a unified cross-cutting rule
(`S6-24`'s own verdict). **Validation**: Code inspection (established).
**Dependency**: `OPS-003`.

## S11-10 — V2 checks target close before fall-forward
**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — `settle_due_exits()` tries
`target_session` first, unconditionally, before any fall-forward loop
(`S8-09`'s established evidence, `pipeline.py:152-153`). **Validation**:
Code inspection (established). **Dependency**: none.

## S11-11 — Ambiguous deliveries preserved, never blindly resent
**Decision**: Agreed. **Authorization**: Not authorized (pre-existing).
**Implementation**: Implemented — established `AMBIGUOUS` outbox
contract (`S9-13`). **Validation**: Code inspection (established).
**Dependency**: none.

## S11-12 — Five account-readiness states
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — a targeted search of
`talonx_ops/` this session found no matching state model.
**Validation**: Code inspection (this session — `OPS-016`).
**Dependency**: `OPS-016`.

## S11-13 — Truthful "Partially Ready" global summary
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented (`OPS-016`). **Validation**: Code
inspection (this session). **Dependency**: `S11-12`, `OPS-016`.

## S11-14 — Transient-block clearance conditions
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented (`OPS-016`, no readiness model to
clear against). **Validation**: Code inspection (this session).
**Dependency**: `S11-12`, `OPS-016`.

## S11-15 — Serious-block auditable clearance; restart never auto-clears
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — this is the clearance mechanism
`OPS-012`/`OPS-015` both need; none exists yet. **Validation**: Code
inspection (this session). **Dependency**: `OPS-012`, `OPS-015`,
`OPS-016`.

## S11-16 — Manual start/stop; optional Europe/London automation
**Decision**: Agreed (reaffirms `S1-04`). **Authorization**: Not
authorized. **Implementation**: Implemented (manual, established) /
Not implemented (optional saved automation). **Validation**: Code
inspection (established). **Dependency**: `S1-04`.

## S11-17 — External watchdog required for total-outage detection
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no watchdog concept found this
session. **Validation**: Code inspection (this session, targeted
search). **Dependency**: none blocking.

## S11-18 — Notification-attempt vs. delivery-guarantee; grace/dedup
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no grace-period or incident-
dedup mechanism found this session. **Validation**: Code inspection
(this session, targeted search). **Dependency**: none blocking;
numerical thresholds explicitly pending.

## S11-19 — Configuration effective dates; immediate vs. versioned changes
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — a
genuinely new topic, not covered by any prior session's code
inspection. **Validation**: Not assessed in this documentation pass.
**Dependency**: `S12-19` (versioned promotion activation is the
research-side analogue of this same idea).

---

# Session 12 requirements (S12-01 through S12-22, plus deferrals S12-23/S12-24)

Compact format, per `DECISION_LOG.md` Session 12, grouped 1–8.

## S12-01 — Mandatory Prior Research Review
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — whether
past experiments (Task 107B/109/112R/115/116) documented this exact
review discipline at the time was not re-traced. **Validation**: Not
assessed in this documentation pass. **Dependency**: none blocking.

## S12-02 — No repeat without reason; labelled replication; reuse; no audit-completeness claim
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Implemented (this documentation's own compliance
— see Validation in `DECISION_LOG.md` Session 12 for exactly what was
and was not reviewed). **Validation**: Code inspection (self-check).
**Dependency**: none.

## S12-03 — Experiment registration before evaluation
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
none blocking.

## S12-04 — Systematic testing retains all variations; no tuning-as-validation
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S12-03`.

## S12-05 — Research isolation label and research-bot default
**Decision**: Agreed (reaffirms `S6-19`/`S3-21`). **Authorization**:
Explicitly not authorized (bot). **Implementation**: Not implemented —
re-ran the "EXPERIMENTAL" search in `dashboard_web_static/index.html`
this session, still no match. **Validation**: Code inspection (this
session, re-run of `S6-19`'s search). **Dependency**: `S6-19`.

## S12-06 — Shared collection without starving primary; no primary mutation
**Decision**: Agreed (reaffirms `S3-15`-`S3-20`). **Authorization**:
Not authorized. **Implementation**: Implemented — the established
physical-isolation architecture (`talonx_research/`'s refusal to touch
`v2_lane.db`) satisfies the no-mutation half; the collection-sharing-
without-starving half was not separately measured. **Validation**:
Code inspection (established). **Dependency**: none.

## S12-07 — Separate dev/tuning vs. untouched evaluation data
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S12-24`.

## S12-08 — 2-year feasibility open; no invented fixed count/duration
**Decision**: Open — deferred (reaffirms `S3-27`/`S5-31`, tracked as
`S12-24`). **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Dependency**: `S12-24`.

## S12-09 — Comparison dimensions
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
none blocking.

## S12-10 — Strategy View vs. Account View
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — whether
this distinction exists anywhere in `talonx_research/`'s reporting was
not traced. **Validation**: Not assessed in this documentation pass.
**Dependency**: none blocking.

## S12-11 — Verdict taxonomy; historical acceptance ≠ activation
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S12-18`.

## S12-12 — Cost definition and single-application rule
**Decision**: Agreed (reaffirms `S10-06`). **Authorization**: Not
authorized. **Implementation**: Not implemented — numerical values
explicitly deferred (`S12-23`). **Validation**: Code inspection
(established). **Dependency**: `S10-06`, `S12-23`.

## S12-13 — Intraday RRR gate scope; fee-inclusive whole-share sizing
**Decision**: Agreed (reaffirms `S6-16`/`S10-07`). **Authorization**:
Not authorized. **Implementation**: Implemented (RRR-gate baseline
mechanism exists and is correctly intraday-only, `S6-16`) / Not
implemented (fee-inclusive whole-share sizing, `OPS-014`).
**Validation**: Code inspection (established). **Dependency**: `S6-16`,
`OPS-014`.

## S12-14 — Chronological cost rerun, not a flat haircut
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S12-23`.

## S12-15 — Illustrative numbers only; calibration deferred
**Decision**: Open — deferred (tracked as `S12-23`). **Authorization**:
N/A. **Implementation**: N/A. **Validation**: N/A. **Dependency**:
`S12-23`.

## S12-16 — Freeze-before-observation; no retrospective admission
**Decision**: Agreed (reaffirms `S8-01`/`S8-02`). **Authorization**:
Not authorized. **Implementation**: Not assessed in this documentation
pass for the research-shadow context specifically (V2's own live
admission timing is `Implemented`, `S8-01`; the research-shadow
analogue was not traced). **Validation**: Not assessed in this
documentation pass. **Dependency**: `S8-01`.

## S12-17 — Predeclared criteria cannot shorten; Inconclusive on insufficient evidence
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
none blocking.

## S12-18 — Shadow scope; historical+shadow separate mandatory gates
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
none blocking.

## S12-19 — Explicit promotion-approval record
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass — whether
any promotion mechanism exists in `talonx_research/` beyond the
immutable-registry pattern was not traced this session. **Validation**:
Not assessed in this documentation pass. **Dependency**: `S3-18`.

## S12-20 — Existing positions retain original rules; no profit transfer
**Decision**: Agreed (reaffirms `S8-06`/`S6-18`). **Authorization**:
Not authorized (pre-existing). **Implementation**: Implemented.
**Validation**: Code inspection (established). **Dependency**: `S8-06`.

## S12-21 — Automatic protective blocking vs. non-automatic replacement; rollback preserves history
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S12-19`.

## S12-22 — Version-restoration approval; auditable remediation for unsafe obligations
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not assessed in this documentation pass.
**Validation**: Not assessed in this documentation pass. **Dependency**:
`S11-15` (same clearance mechanism).

## S12-23 — Deferred: numerical execution-cost calibration
**Requirement**: exact feed/reference/spread/slippage/fee/adverse-
scenario values (§6). **Decision**: Open — deferred. **Authorization**:
N/A. **Implementation**: N/A. **Validation**: N/A. **Reason**: the
discussion's own example numbers are explicitly illustrative, not
approved; needs bounded evaluation against evidence. **Planned
session**: none further assigned — this session was itself the
previously-named destination (`S6-25`/`S8-25`/`S10-22`) and still
leaves the numbers unresolved. **Dependency**: `S6-25`, `S8-25`,
`S10-22`.

## S12-24 — Deferred: two-year historical data feasibility
**Requirement**: data availability/granularity/point-in-time universe/
corporate actions/licensing (reaffirms `S3-27`/`S5-31`). **Decision**:
Open — deferred. **Authorization**: N/A. **Implementation**: N/A.
**Validation**: N/A. **Reason**: unresolved, not addressed by this
session's governance discussion. **Planned session**: none assigned.
**Dependency**: `S5-31`.

---

# Session 13 requirements (S13-01 through S13-09)

Compact format, per `DECISION_LOG.md` Session 13.

## S13-01 — First release: V2 as primary paper strategy, conditional
**Decision**: Agreed. **Authorization**: Not authorized (a release-
scope decision, not a build). **Implementation**: Not implemented —
conditional on pricing/timing/ledger/lifecycle/user-facing acceptance
criteria, none of which are all met yet (`OPS-002`/`OPS-003`/`OPS-005`
still open). **Validation**: Code inspection (this session, Package 1
evidence — one prerequisite closed, others remain). **Dependency**:
`Package 2` through `Package 4`.

## S13-02 — Intraday Research-Lab-only for first release
**Decision**: Agreed. **Authorization**: Not authorized.
**Implementation**: Not implemented — no Research Lab account exists
(`S6-03`). **Validation**: Code inspection (established). **Dependency**:
`S6-03`, `Package 5`.

## S13-03 — Company-development primary-Telegram gating
**Decision**: Agreed (reaffirms `S7-01`/`S9-01`). **Authorization**:
Not authorized. **Implementation**: Not implemented — the six-question
rubric and materiality routes this gate depends on do not exist
(`OPS-011`). **Validation**: Code inspection (established).
**Dependency**: `OPS-011`.

## S13-04 — Prior-research reconciliation is PENDING
**Decision**: Agreed (a status statement, not a build item).
**Authorization**: N/A. **Implementation**: Not implemented — `S12-01`'s
mandatory prior-research review has not been performed as its own
task; Package 1's own implementation reused established evidence by
citation only (see `S13-09`'s own Validation for exactly what was and
was not reviewed). **Validation**: Code inspection (this session,
self-check). **Dependency**: `S12-01`.

## S13-05 — Packages 1-5 authorized in dependency order; release integration unscoped
**Decision**: Agreed. **Authorization**: Package 1 only —
**"Package 1 implementation and isolated tests are authorized"** (this
task's own explicit grant). Packages 2-5 and release integration
remain **explicitly not authorized**. **Implementation**: Package 1
`Implemented` (`S13-09`); Packages 2-5 `Not implemented`, `Not
authorized`. **Validation**: Isolated test execution (this session,
Package 1 only). **Dependency**: `S13-06`.

## S13-06 — Staging order
**Decision**: Agreed: `Stage 0` → `Package 1` → `Package 2` →
`Package 3` → `Package 4` → `Package 5` → release integration.
**Authorization**: Not authorized beyond Package 1. **Implementation**:
Package 1 stage complete this session; no later stage started.
**Validation**: Isolated test execution (this session). **Dependency**:
none blocking to record the order itself.

## S13-07 — Provider qualification / prior-research review are parallel, not parameter-change permission
**Decision**: Agreed. **Authorization**: Explicitly not authorized (no
strategy-parameter change of any kind). **Implementation**:
Implemented — directly verified this session: `V2Config`'s frozen
values are unchanged and the V2 release fingerprint
(`research.scripts.task112_v2_release_fingerprint.
v2_release_fingerprint()`) still equals `11107198c5b81237`
(`talonx_ops/prospective/__init__.py`'s `V2_FINGERPRINT_EXPECTED`),
confirmed by direct execution, not inference. **Validation**: Isolated
test execution (this session, exact fingerprint values quoted).
**Dependency**: none.

## S13-08 — Material-version cutover rules (documentation only)
**Decision**: Agreed (7 sub-rules — new primary campaign with approved
capital; old campaign manages existing obligations only; future
unfilled intents cancelled atomically at cutover; timely admitted
intents within their recovery window stay under old rules; timely
persisted evidence reconciled even if processed later; existing
positions retain original rules; no historical accounting error erased
by a new campaign). **Authorization**: Explicitly not authorized — no
cutover performed or scheduled. **Implementation**: Not implemented —
documentation only; no cutover code path exists or was exercised.
**Validation**: Code inspection (this session, self-check — no cutover
mechanism found or invoked). **Dependency**: `Package 2` (account-block
clearance) is a natural prerequisite for any future cutover involving
an account with an outstanding block.

## S13-09 — Package 1: Settlement Integrity & Unresolved Obligations (implemented)

**Decision**: Agreed and **authorized** (this task's own explicit
grant — "Package 1 implementation and isolated tests are authorized").
**Authorization**: Authorized. **Implementation**: **Implemented.**

**What was built** (minimum-diff, read-only-verified-then-fixed):

1. `talonx_v2/store.py::close_position()` — now returns whether its
   own conditional `UPDATE ... WHERE status='OPEN'` actually matched a
   row (`cursor.rowcount > 0`), instead of unconditionally `None`. This
   IS the authoritative, atomic eligibility check for the state
   transition (SQL-level, inside the same transaction).
2. `talonx_v2/paper.py::close_position()` — now checks that return
   value before crediting cash, appending a trade, or setting cooldown;
   returns a new `ExitOutcome.settled: bool` field (`False` = no-op/
   already-resolved, no economic mutation) instead of always assuming
   settlement occurred.
3. `talonx_v2/pipeline.py::settle_due_exits()` — checks `out.settled`
   before appending to `res.exits`/building an exit alert, so a no-op
   outcome never generates a duplicate exit notification.
4. `talonx_v2/store.py::n_open()` and `::position_for_symbol()` —
   broadened to `status IN ('OPEN','EXIT_UNRESOLVED')`. `open_positions()`
   itself (and therefore `due_exits()`, the retryable/actionable set)
   is **unchanged** — EXIT_UNRESOLVED positions remain correctly
   excluded from automatic re-settlement.
5. `talonx_ops/prospective/close.py::_v2_reconcile()` — now sums
   `EXIT_UNRESOLVED` position cost separately and includes it in the
   `cash_plus_open_cost_reconciles` formula, closing the fabricated-
   mismatch gap.
6. `talonx_ops/paper_performance.py::_v2_snapshot()` — now queries
   unresolved-position rows (not just a count), includes their cost in
   `expected_cash`, and forces `equity_status = "PARTIAL"` whenever any
   unresolved position exists (previously vacuously `"COMPLETE"` when
   `opens` was empty). Added a new, additive
   `exit_unresolved_cost_basis_total` field; the existing
   `exit_unresolved` integer-count field's type is unchanged (a known
   consumer, `talonx_ops/dashboard_read.py:285`, treats it as a count).

**Explicitly NOT done** (Package 2's own scope): no account-wide
admission block was added for `EXIT_UNRESOLVED` (`OPS-012` remains
open) or for a reconciliation mismatch (`OPS-015` remains open) — slot/
capacity/symbol-ownership/valuation/reconciliation correctness is fixed;
the separate "block ALL new admissions in the account" workflow and its
explicit-clearance mechanism are not. No dashboard redesign, fee
implementation, or provider work was done.

**Validation**: **Isolated test execution** —
`tests/test_package1_settlement_integrity.py` (14 new tests, all
covering the specific properties this task required: sequential and
concurrent duplicate-close prevention, no duplicate cooldown, atomic
rollback on mid-settlement failure, no-op-outcome distinguishability,
unresolved-position slot/cost/symbol-block retention, no phantom
proceeds, honest non-COMPLETE equity, non-fabricated reconciliation,
restart persistence, and OPEN/CLOSED sanity) — captured failing
**before** the fix (9 of 14 failed against the unchanged baseline,
reproducing both described defects precisely) and passing **after**
(14/14). A scoped regression run of 32 existing test files touching
the same store/paper/pipeline/close/paper_performance surface (406
tests total across the full run) found **zero new failures** — the 9
pre-existing failures (5 in `test_task117_migration.py`, 1 each in
`test_task131_spa_discovery_backend.py`, `test_task117_deployment_
rehearsal.py`, plus the two `OPS-017` fingerprint-constant mismatches)
were independently reproduced against the unmodified baseline (`git
stash`) and confirmed unrelated. Two pre-existing tests
(`tests/test_task117_phase0_entry_timing.py::
test_e8c_exit_unresolved_when_target_and_all_fallforward_missing`,
`tests/test_task112_tuesday_release.py::
test_15_missing_through_plus5_is_explicit_unresolved`) asserted the
OLD (incorrect) `n_open() == 0` behavior for an `EXIT_UNRESOLVED`
position and were corrected to assert the fixed behavior (`n_open()
== 1`, `open_positions() == []`), preserving each test's original
intent. The V2 strategy fingerprint (`11107198c5b81237`) was directly
re-computed and confirmed unchanged.

**Not tested this session** (Package 2's own future scope): the
account-wide admission block itself, since it does not exist yet.

**Dependency**: `OPS-012` (its capacity/symbol/valuation prerequisites
are now fixed); `OPS-015` (a distinct, V2-specific fabricated-mismatch
defect in `_v2_reconcile()` is fixed — `OPS-015`'s own described gap,
`eod_reconciliation.py`'s missing admission-block wiring, is
untouched). Both findings' own account-block-clearance requirements
are unaffected and remain `Package 2`'s scope.
