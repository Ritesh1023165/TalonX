# TalonX Product Decision Log

Append-only, session-by-session record of product-level (as opposed to
strategy-tuning — see `docs/research/TALONX_OWNER_DECISIONS.md` for
that layer) discussions with the product owner. Prior entries are never
edited or removed; a later session that revises an earlier decision adds
a new, dated note under the *original* entry and a pointer from the
newer entry back to it — the same discipline
`docs/research/TALONX_RESEARCH_LEDGER.md` already uses.

Each entry records: the plain-language discussion, the concrete example
used (if any), the current implementation as of that session (with
evidence), what was **agreed** (a product direction) vs. what remains
**open/proposed** (not yet a settled requirement), and — separately —
whether any implementation work was **authorized**. A proposal or an
agreed direction does **not** by itself authorize implementation; see
`KNOWLEDGE_TRANSFER_PLAN.md` §6 for the exact workflow.

---

## Session 1 — Product Purpose, User Value and Boundaries

**Recorded**: 2026-09-15. **Source**: the product-owner discussion
supplied directly in this session's prompt (a knowledge-transfer
conversation between the product owner and Claude, conducted because the
product owner had become out of sync with the evolving application; this
log records the OUTCOME of that discussion as given, not a live
transcript).

### Context

The product owner requested a first-principles review of TalonX,
assuming little investment knowledge, before authorizing further product
development. This session covered product purpose, user value, and
boundaries — not yet the technical/architecture layers (see
`KNOWLEDGE_TRANSFER_PLAN.md` for Sessions 2 onward).

### Agreed product direction

**Primary goal** — `AGREED`:
> Help the user discover and understand selected stock-trading
> opportunities without continuously monitoring markets, using concise,
> evidence-backed alerts and paper tracking to evaluate the results.

**Core experience** — `AGREED`:
- Trading opportunities appear in Telegram first.
- General corporate monitoring and raw filings remain on the dashboard.
- Major-company-development notifications are optional.
- Major-development messages must explain what happened and why it
  matters in plain language, without unexplained SEC jargon.
- "High conviction" is a desired quality — not proof of profitability,
  and not authorization to invent a confidence score.

**Operating preference** — `AGREED`:
- Typically 08:00–22:00 UK local time is the preferred operating
  window. Explicitly **not** an assertion that a scheduler or a
  reliable arbitrary start/stop lifecycle is already implemented — this
  is a stated preference for later engineering to evaluate against.
- Opportunities/major events may be detected during this window;
  detection time does not automatically establish actionability.

**Presentation** — `AGREED`:
- Trade alerts begin with a one-sentence plain-English explanation of
  the supporting evidence.
- Examples must not call people "executives" or describe a purchase as
  "personal funds" unless the source data actually supports those
  descriptions.
- Clear opportunity status is required to prevent chasing expired
  entries.
- Standardized paper sizing is desired; $10,000 per allocation is
  **proposed**; cross-lane scope is **not finalized**.
- Allocation size must not be described as maximum possible loss.
- Existing reply-for-details remains useful.
- New interactive Telegram buttons are deferred, low priority (not
  authorized).

**Boundaries** — `AGREED`, and already the project's established
practice:
- Development and paper tracking only.
- Existing free-tier infrastructure; no new paid data authorized.
- No real-capital execution authorized.

### Open / proposed — NOT settled, not promoted to requirements

- The owner described TalonX, in places, as a **"swing intelligence
  assistant."** During the discussion, an unresolved scope question was
  identified: should TalonX (a) retain Original's intraday lane, (b)
  focus product identity on V2's multi-day opportunities, or (c)
  explicitly support both? **This is recorded as an open decision still
  to be finalized** — not resolved in Session 1, and not to be treated
  as decided by omission. Tracked as `S1-09`.
- Separating **market-session labels** (is the market open right now)
  from **opportunity-status labels** (is this specific opportunity
  still actionable) was **proposed**, to avoid implying that regular
  trading hours automatically means an opportunity is active. The
  owner's original intent (clear actionability/expiry status, §
  Presentation above) and this specific proposed mechanism are recorded
  **separately** — the intent is agreed, the mechanism is a proposal.
  Tracked as `S1-11`.
- Exact acceptance criteria for **"qualified opportunity"**, **"major
  development"**, and **"high conviction"** need definitions with
  concrete pass/fail criteria in a later session — not defined in
  Session 1.
- **Quiet-period, downtime/catch-up, and missed-opportunity behavior**
  remain unspecified — not discussed in enough depth in Session 1 to
  record a decision either way.
- **No profitability promise** and **no target launch date** were
  agreed or even proposed in Session 1 — explicitly absent, not an
  oversight in this recording.

### Implementation authorization

**None.** This session was a knowledge-transfer/product-alignment
discussion. No implementation work of any product change discussed in
Session 1 is authorized by this record. See `REQUIREMENTS_TRACKER.md`
for the per-requirement `Implementation authorization` column — every
Session 1 entry there reads `NOT AUTHORIZED` except where an item
describes already-existing, previously-authorized-and-built behavior
being *documented* here for the first time (which is not new
authorization, only newly-recorded observation).

### Differences from current behavior (see `REQUIREMENTS_TRACKER.md` for full detail)

- The 08:00–22:00 UK operating-window preference has no corresponding
  automatic scheduler today (manual `talonx_ops.prospective`
  start/close only).
- "No unexplained SEC jargon" is not yet fully met — a real example
  message's header line still shows a raw item-number citation.
- Standardized $10,000 paper sizing already matches V2's own default,
  but not Original's ($2,500) — cross-lane unification does not exist
  today.
- No interactive Telegram buttons exist (consistent with "deferred",
  not a regression).

### Proposed enhancements (not agreed as requirements)

- Removing raw SEC item-number citations from the primary message line
  (implied by the "no unexplained jargon" goal, not separately proposed
  as its own item in Session 1 — recorded here as a natural next
  discussion point for a future session, not a decision).
- A dedicated, Telegram-visible "this opportunity has expired" status
  line distinct from the dashboard-only internal state.

---

## Session 2 — Paper Execution, Accounting, Risk and Evaluation

**Recorded**: 2026-09-15, approximately 21:35 UTC / 22:35 BST (this
documentation pass's own recording time, captured via Python `zoneinfo`
per this project's established UK-time discipline — see
`docs/research/evidence/eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md`).
**Source**: the product-owner discussion supplied directly in this
session's prompt (the same pattern as Session 1 — this log records the
OUTCOME of that discussion as given, not a live transcript; the
discussion's own internal timestamp is unavailable and is not invented
here). This session's actual content — paper-execution mechanics,
capacity handling, live-vs-replay parity, performance/accounting
presentation, valuation-freshness disclosure, exit-rule disclosure, and
experimental isolation — covers different ground than
`KNOWLEDGE_TRANSFER_PLAN.md`'s originally-scheduled Session 2 title
("Investment basics through a paper-trade example"); the plan is
explicitly owner-adjustable (`KNOWLEDGE_TRANSFER_PLAN.md`, "This plan is
adjustable by the owner"), so the schedule table has been updated to
reflect what was actually conducted rather than treated as a mismatch.

### Context

Paper trading is virtual investment without real money: it automatically
evaluates explicit trading instructions and records their outcomes under
declared pricing, timing, sizing and cost assumptions. This session
covered how the product owner expects paper execution, accounting, risk
disclosure and evaluation to behave — building on Session 1's purpose/
boundaries discussion, not yet the full technical architecture (still
Session 3 onward).

### Agreed product direction

**A. Alert-to-action mapping** — `AGREED`:
- BUY opens a long position subject to entry and portfolio rules.
- SELL/EXIT closes an existing position.
- BULLISH and BEARISH are informational observations and execute
  nothing.
- No automatic short selling.
- A SELL without an applicable existing position must not create a
  short or fabricate proceeds; its disposition must be explicit.

**B. Capacity boundaries** — `AGREED`:
- A qualified opportunity remains visible even when the virtual account
  cannot take it.
- An appropriate skip record (e.g. "Paper entry skipped: insufficient
  cash/capacity") should exist.
- Cash must never be inflated or reset to force an entry.
- Signal qualification and paper-portfolio admission must be
  distinguishable.
- Hypothetical outcomes of skipped opportunities must not be counted as
  executed portfolio returns.

**C. Live evaluation and historical replay** — `AGREED`:
- The same execution/accounting rules should serve live paper
  evaluation and historical replay.
- Separate campaign/account state and appropriate real/simulated clocks
  per context.
- Replay must respect information availability — no future-data access.
- A two-year replay window is **desired**; data feasibility is
  **explicitly not verified** by this decision.
- This architecture, and any two-year replay capability, must not be
  claimed as already existing without direct evidence.

**D. Performance judgment** — `AGREED`:
- EOD shows daily equity movement, realized results and open/unrealized
  P&L separately.
- EOD does not automatically close multi-day positions.
- Final trade evaluation follows the strategy's own exit rules.
- If a planned exit cannot complete because required data is
  unavailable, an unresolved/delayed outcome is shown under the
  strategy's existing policy — not a fabricated close.
- Directional accuracy and profitability are separate measurements.

**E. Dashboard presentation** — `AGREED`:
- Account Equity and Aggregate Open-Position P&L receive equal
  prominence.
- Individual position details show monetary P&L and trade return.
- Position contribution is shown labelled "Contribution relative to
  account equity at entry", denominator = account equity immediately
  before that position's entry.
- Overall account return is reported separately from any individual
  position's contribution percentage.
- Position percentages with different denominators must never be
  summed as though they were total account return.
- Gross/net treatment and realized/unrealized status are stated
  consistently.
- Formal deposit/withdrawal handling and a detailed portfolio-return
  methodology may be specified later — not invented here.

**F. Missing/stale valuations** — `AGREED`:
- Show "Awaiting price" or "Valuation stale" with the applicable
  timestamp.
- Unknown/unresolved P&L must not be displayed as zero.
- A carried-forward mark is labelled with its actual date/freshness.
- Account equity affected by missing marks is identified as incomplete
  or estimated, not presented as fully current.

**G. Exit-rule disclosure** — `AGREED`:
- Display the actual strategy exit rule and stop-loss status.
- For the **current V2 baseline** specifically: "Close of the 10th
  trading session after entry." / "No price-based stop-loss."
- This exit rule must not be applied to every strategy by default —
  it is `INSIDER_BUY_CLUSTER_V2@1`-specific.
- Avoid reassuring wording that implies losses will recover before
  exit.
- Allocation is capital assigned, not maximum loss or expected loss.

**H. Experimental isolation** — `AGREED`:
- Preserve baseline campaign results.
- Strategy changes, including stop-loss variants, use separate
  versioned experiments and isolated virtual accounts.
- Compare using consistent starting capital, data and cost assumptions.
- A stop-loss must not be claimed to necessarily improve or destroy
  returns.
- The prior +2.0219% result (Task 115/116, `docs/research/
  TALONX_RESEARCH_LEDGER.md`) is conditional historical evidence, not a
  validated promise for current live execution.
- No new research experiment is authorized by this session.

### Implementation authorization

**None.** Every decision above is recorded as an **agreed product
direction**; implementation authorization is explicitly **"Not
authorized by this documentation task."** See
`REQUIREMENTS_TRACKER.md` (`S2-01` through `S2-15`) for the
per-requirement decision-status / authorization / implementation /
validation breakdown — several items describe already-existing,
previously-built behavior being documented here for the first time
(not new authorization), and several describe genuine gaps not yet
built.

### Differences from current behavior (see `REQUIREMENTS_TRACKER.md` for full detail)

- V2's entry path already has distinct, non-fabricating skip
  dispositions (`NO_CASH`, `SYMBOL_ALREADY_OPEN`, `IN_COOLDOWN_*`,
  `MAX_CONCURRENT_*`, `BAD_ENTRY_PRICE` — `talonx_v2/paper.py`), but
  none reads literally "Paper entry skipped: insufficient cash/
  capacity" — the mechanism exists, the exact operator-facing wording
  in requirement B does not yet.
- Realized P&L, unrealized P&L and equity are already reported as
  separate fields with independent status (`talonx_ops/
  paper_performance.py`'s `equity_status`/`up.status`, surfaced in
  `dashboard_web_static/index.html`'s `renderV2`), including equity
  correctly reported as `None` (not zero) and flagged `PARTIAL` when a
  mark is incomplete — a real partial match for requirement F's intent,
  under different field names and without the literal "Awaiting price"/
  "Valuation stale" wording.
- No "Contribution relative to account equity at entry" label,
  dedicated equal-prominence Account-Equity/Aggregate-Open-P&L layout,
  or carried-forward-mark freshness date exists in the dashboard code
  inspected this session (requirement E, part of F) — genuine gaps.
- V2's exit rule (10th-trading-session close, no stop-loss) is real and
  frozen in code (`talonx_v2/config.py:33-36`, `pipeline.py:148`) but is
  **not surfaced to the operator as explanatory text** anywhere found
  this session — the rule exists, its disclosure does not.
- No automatic short-selling code path exists for V2 (`talonx_v2/
  service.py`'s `"shorts": False` status field) — consistent with
  requirement A, not a gap.
- Two-year replay: Task 115/116 already built and exercised a
  chronological replay engine that drives the real `V2Service.tick()`
  (`talonx_research/replay_engine.py`) with a 2024-09-01→2026-03-31
  window (bounded by available parquet, not a full 2 years to today) —
  **partially responsive to requirement C**, not the same as a
  standing, product-facing 2-year replay capability; not claimed as
  such here.

### Open questions

- **Session 1's `S1-09` intraday-vs-multi-day product-identity scope
  question remains open.** This session discussed accounting/execution
  concepts that apply to both horizons (Original's intraday lane and
  V2's multi-day lane) without deciding which horizon(s) the product's
  identity should center on — that discussion does not silently
  resolve `S1-09`; it stays `Open — not decided`
  (`REQUIREMENTS_TRACKER.md`).
- **The proposed $10,000 cross-lane allocation standard (`S1-07`) is
  not finalized by this session's accounting examples.** Session 2
  used $10,000-scale figures for illustration (matching V2's own
  existing default) without deciding whether Original's $2,500 default
  should change — `S1-07` remains `Proposed` (the figure) /
  `Agreed` (the need for a standard), unchanged by this session.
- Exact operator-facing wording/placement for capacity-skip records,
  valuation-staleness, and exit-rule disclosure — not specified beyond
  the phrasing given in this session; a later session or a dedicated
  UI-design task would finalize copy.
- Deposit/withdrawal handling and the detailed portfolio-return
  methodology — explicitly deferred, not decided.
- Whether/when a genuine 2-year, to-date replay capability (as opposed
  to the existing bounded historical window) should be built — data
  feasibility for the full window is **not verified** by this session.

### Proposed enhancements (not agreed as requirements)

- None recorded beyond the agreed items above — this session's content
  was decision-level, not feature-brainstorming.

### Any separately authorized implementation work

**None.**

---

## Session 3 — Application Structure and Configuration: Original, Intelligence and V2

**Recorded**: 2026-09-16, approximately 01:42 UTC / 02:42 BST (this
documentation pass's own recording time, Python `zoneinfo`, per this
project's established discipline). **Source**: the product-owner
discussion supplied directly in this session's prompt (same pattern as
Sessions 1–2 — the discussion's own internal timestamp is unavailable
and not invented here).

### Context

This session answers the agenda items Session 2's documentation pass
added to Session 3's queue: Original/Intelligence/V2's respective
responsibilities, the master stock coverage model, virtual-account
capital defaults, the research-lab workflow, an optional research
Telegram bot, user-facing naming, and a conditional database-reset
permission. **Product scope was not inferred from account labels
alone** — the "both horizons" decision below was made explicitly by
the owner in this session's discussion, not derived from Original
having two account labels.

### Agreed product scope

- **TalonX offers BOTH intraday and multi-day trading opportunities.**
  This resolves Session 1's open `S1-09` question — see `S3-01`.
- One main Telegram opportunity feed uses prominent INTRADAY/MULTI-DAY
  labels and strategy identity, rather than separate feeds per
  horizon.
- Original is **not retired or disconnected** by this discussion.
- Keeping intraday does **not** freeze Original's existing
  implementation — it remains open to its own future changes,
  independent of this decision.
- **V2 is one multi-day strategy** (`INSIDER_BUY_CLUSTER_V2@1`), not
  the name of the entire multi-day category — future multi-day
  strategies are not implicitly "V2".
- Intelligence supplies company facts/context, with optional
  major-development notifications; routine disclosures remain on the
  dashboard (reaffirms Session 1's `S1-02`/`S1-03`, not a new
  decision).

### Target architecture

- Strategies remain independently identifiable and testable.
- Each strategy owns its own qualification, timing, entry and exit
  rules.
- Strategies share supporting data, opportunity, accounting and
  presentation **contracts** where appropriate — a shared interface,
  not shared internal state by default.
- **This does not authorize immediate process or database
  consolidation.** Original and V2 remain separate processes/databases
  unless and until a separately authorized task changes that.
- Qualified opportunities and paper-account admission remain distinct
  concepts (reaffirms Session 2's `S2-04`, extended to the multi-
  strategy target architecture as `S3-06`).
- A qualified opportunity remains visible when its virtual account
  lacks cash or capacity (reaffirms `S2-03`, same extension).
- Positions are identified by **account, strategy and opportunity** —
  not ticker alone.
- An intraday EXIT must not close a multi-day position in the same
  stock (and, symmetrically, a multi-day exit must not touch an
  intraday position in the same stock).

### Master stock coverage model

One **master stock list** combines: supported automatic-discovery
universes, validated manual additions, and explicit exclusions.
Duplicate security entries are removed while retaining source/
provenance; ticker alone is insufficient to identify a security where
issuer/security identity is ambiguous (e.g. a symbol reused across
exchanges or after a corporate action).

- **Global default**: both horizons permitted where supported.
- **Per-stock/per-horizon overrides**: Intraday / Multi-day / Both /
  Pause or exclusion from new opportunities.
- **Manual additions require**: company/security/exchange identity
  validation; provider and filing mapping where applicable;
  strategy-specific data/readiness assessment; an explicit unsupported/
  awaiting-data reason when applicable.
- **Adding a stock never bypasses** strategy, liquidity, timing,
  freshness, capacity, or other eligibility rules.
- **Distinct visible states**: configured membership; identity
  resolved; data ready; strategy eligibility; a currently qualified
  opportunity — five separate states, not collapsed into one
  "supported/not supported" flag.
- **One master list does NOT authorize** expanding intraday polling
  from the existing watchlist to every broad-universe symbol
  immediately — that remains a separate, unauthorized decision.
- Current symbol/scope counts (e.g. V2's `execution_scope_count: 626`,
  Intelligence's ~569-symbol collection scope referenced in Session 2)
  are **timestamped observations, not permanent product constants**.

**Pause / Exclude / Mute** — agreed intended meanings:
- **Pause**: reversible suspension of new opportunities, normally
  until resumed.
- **Exclude**: persistent exclusion from new opportunities, including
  automatic rediscovery, until explicitly removed.
- Either can apply **per horizon** (e.g. paused for intraday, still
  eligible for multi-day).
- **Neither** automatically closes a position, deletes history, or
  abandons required exit management.
- Prices and notifications required to manage **existing** obligations
  continue regardless of pause/exclude state.
- **Mute is a distinct concept**: notification suppression is not
  equivalent to pausing strategy opportunities — a muted stock can
  still qualify and be admitted; it just doesn't notify.
- Exact mute controls, and the handling of already-committed, unfilled
  intents when a stock is paused, are **explicitly deferred** — see
  `S3-28` below; no cancellation semantics are invented in this
  session.

### Virtual account defaults

**Agreed for NEW evaluation campaigns**:
- Starting virtual cash: **$100,000 per strategy account**.
- Allocation: **$10,000 per position**.
- Both figures remain configurable.
- No automatic borrowing, cash inflation, or reset to force entries.
- Strategy position limits are preserved; available cash may impose a
  tighter effective limit than the strategy's own stated maximum.
- Fees and reservations can prevent funding ten simultaneous $10,000
  positions out of $100,000 even before any strategy-level cap binds.

**Separate strategy accounts and results**: approved strategy
accounts, baseline shadow accounts, and experimental candidate
accounts are tracked as three distinct categories.

**Combined exposure view**: display overlapping exposure to the same
security across accounts; clearly label aggregate capital. Two
$100,000 accounts represent **$200,000 combined virtual capital**, not
a shared $100,000 pool. Experimental results are never mixed into
approved-account performance reporting.

**Existing campaigns are not overwritten** to match these new
defaults — V2's existing $300,000 campaign (Task 112's `$300k` F1
fix, still running per `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md`) is unaffected by this session; these are
defaults for campaigns created going forward. The separately agreed
**conditional reset policy** is recorded below, and does not itself
apply these new defaults retroactively.

A $100,000/$10,000 campaign can produce different capacity outcomes
(more simultaneous positions, different percentage returns for the
same dollar P&L) than the existing $300,000 V2 campaign — any future
comparison between them must disclose the changed capital assumption,
not transfer prior economic results as if the campaigns were
equivalent.

### Research lab workflow

**Agreed process**: historical replay → internal live shadow
comparison → review → explicitly approved promotion.

- Reuse strategy/execution/accounting code with **versioned
  configurations** (not forked code paths).
- Isolate cash, positions, intents, reservations, cooldowns and
  outcomes per experiment.
- Share collected data where practical, without delaying approved
  operation.
- Historical baseline/candidate comparisons use **equivalent** data,
  capital, cost and pricing assumptions.
- Live candidate comparisons use an **equivalently-initialized
  baseline shadow account**, not a comparison against an established
  account carrying unmatched existing positions.
- **Evaluation criteria are defined before inspecting candidate
  results** — not chosen after seeing which criteria make the
  candidate look best.
- Failed experiments are preserved, and the count of attempted
  variants is retained (no silent survivorship).
- Suitable **unseen periods** are used where feasible.
- **EOD is an interim report** for multi-day experiments, not final
  acceptance — a multi-day candidate's EOD snapshot is not itself a
  promotion decision.
- A promoted version carries its **configuration, evidence, and
  effective time** together.
- **Existing positions retain the rules/version under which they were
  opened** — a promotion does not retroactively change an open
  position's own exit contract.
- Rollback and historical attribution are preserved.
- **Parameter experiments and changes to signal/entry/exit semantics
  are distinguished** — a logic change must never be presented as a
  mere configuration adjustment.
- The two-year replay window remains **desired, not a verified
  capability** (reaffirms `S2-06`). **No experiment or profitability
  claim is authorized by this documentation.**

**Research Lab dashboard** — agreed visibility:
- Experiment identity, hypothesis, and changed parameters.
- Baseline/candidate versions.
- Historical-replay vs. live-shadow mode, clearly distinguished.
- Opportunity, rejection, and non-execution records.
- Positions, net results, drawdown, and exposure.
- Data limitations and incomplete outcomes.
- Evaluation criteria and decision history.
- A prominent **"EXPERIMENTAL — INTERNAL ONLY"** label.
- **No automatic promotion** merely because a dashboard metric turns
  positive.

### Optional research Telegram bot

This **explicitly refines** the project's earlier general
"experimental alerts stay off the main channel" understanding
(`talonx_ops/external_boundary.py`'s existing 3-condition Experimental-
send gate, this project's history) — it is not a reversal, it adds a
specific, opt-in internal channel:

- Experiments must **not** send to the main Telegram feed.
- Experiments **MAY** use a separately configured **internal research
  bot**.
- Modes: **OFF** (default, dashboard only) / **SUMMARY**
  (experiment/EOD comparisons) / **DETAILED** (selected experiments'
  opportunities and outcomes).
- Requires: explicit enablement; clearly experimental/paper-only
  message wording; separate bot credentials and destination
  configuration; **no fallback** from a missing research configuration
  to the main bot; reply/details correlation scoped by bot, chat and
  message identity; experimental-account isolation independent of
  delivery destination (an experiment stays isolated in its own
  account even if its delivery mode changes).
- **No bot creation, credential entry, destination selection, or
  message sending is authorized by this task.**

### User-facing names

Approved display names/direction:

| Display name | Meaning |
|---|---|
| Intraday Opportunities | intraday product category |
| Insider Buying Strategy | current V2 strategy |
| Company Developments | Intelligence's user-facing information surface |
| Virtual Portfolio | simulated accounts, positions and outcomes |
| Stock Coverage | stock membership, permissions and readiness |
| System Health | operational/data status |
| Research Lab | isolated experiments |

- "**Multi-Day**" remains a horizon category (not a strategy name).
- Specific intraday strategy display names are deferred until after a
  rule review.
- "**Fundamental Opportunities**" is **provisional**, pending review of
  Original's older long-term path — see `S3-24` (deferred).
- **Internal strategy IDs, historical experiment identifiers, database
  names and module names are preserved.** Display naming is **not**
  authorization for a technical rename or migration.

### Conditional database reset permission

The owner agreed that a clean database/campaign reset **MAY** be used
during a **separately authorized implementation**, if necessary for
compatibility or trustworthy accounting. This **updates** the earlier
absolute-preservation wording used in the EOD closure task
(`docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md`'s originating task prompt: "Do not ... reset
databases") and this documentation task's own restrictions — **it does
not authorize resetting anything now**, in this or any past
documentation-only session.

**Required approach for any future authorized reset**:
1. Identify affected stores/tables and the compatibility issue.
2. Preserve consistent backups and useful historical evidence.
3. Prefer a straightforward migration when suitable.
4. If a clean store is necessary, version it and record the new
   campaign boundary.
5. Limit the reset to the affected state only.
6. Preserve notification deduplication, or establish an explicit
   delivery cutoff preventing historical alert replay.
7. Reconcile open positions and uncertain delivery obligations before
   retiring their operational state.
8. Never fabricate settlements or silently abandon obligations.
9. Explain the chosen migration/reset in the implementation plan and
   report.

A database reset is **permitted when necessary, not the default
response** to an implementation problem. A future implementation task
that already covers a specific reset action under this policy does not
need a redundant separate permission request.

### Implementation authorization

**None.** Every decision above is an **agreed product direction**;
all new implementation authorization is explicitly **"Not authorized
by this documentation task."** See `REQUIREMENTS_TRACKER.md` (`S3-01`
through `S3-28`) for the per-requirement breakdown, including which
items describe already-existing behavior (documented, not newly
authorized) and which describe genuine gaps.

### Clarifications to Sessions 1–2 (dated notes, originals not rewritten)

- **`S1-09`** (intraday-vs-multi-day scope) — **resolved** by this
  session's "both horizons" decision. See `REQUIREMENTS_TRACKER.md`
  `S1-09` for the dated resolution note and pointer to `S3-01`.
- **`S1-07`** (standardized paper sizing, $10,000 proposed) —
  **clarified and extended**, not finalized across existing lanes:
  this session confirms $10,000 per-position allocation as a
  **new-campaign default** (alongside a newly-agreed $100,000 starting
  cash per strategy account), but does **not** retroactively change
  Original's existing $2,500 default or V2's existing $300,000
  campaign. See `REQUIREMENTS_TRACKER.md` `S1-07` for the dated note.
- **`S2-01`** (alert-to-action mapping) — **clarified**: the
  account/strategy/opportunity-specific identity requirement (`S3-07`)
  sharpens how BUY/SELL/EXIT map to a position once multiple
  strategies coexist under one master stock list. See
  `REQUIREMENTS_TRACKER.md` `S2-01`.
- **`S2-14`/`S2-15`** (experimental isolation) — **extended** by the
  full replay → shadow → review → promotion workflow (`S3-15` through
  `S3-20`) and the research-bot refinement (`S3-21`). See
  `REQUIREMENTS_TRACKER.md` `S2-14`.
- Session 1's preferred **08:00–22:00 UK operating window** (`S1-04`)
  is **retained unchanged** — this session does not make continuous
  overnight operation mandatory, and does not touch `S1-04`'s existing
  "no scheduler exists" implementation finding.
- Session 1's **optional major-development notifications** (`S1-02`)
  are **preserved unchanged**.

### Explicit deferrals

Each deferred item below is recorded with its reason, its planned
discussion session, and its dependency — per this project's closure
discipline (every session-closing question is agreed, rejected, or
explicitly deferred with a named destination, never silently dropped).

- **`S3-24`** — Original's older fundamentals/long-term path: role
  needs inspection before deciding whether to retain, adapt, or
  retire it. **Reason**: "Fundamental Opportunities" naming is
  provisional on this review. **Planned session**: a future session
  covering Original's non-intraday path specifically (candidate:
  extending Session 6's scope, or a dedicated session — not decided).
  **Dependency**: direct code/data inspection of Original's long-term
  lane, not yet performed.
- **`S3-25`** — shared cross-strategy capital/exposure **enforcement**
  policy: display of combined exposure is agreed now (`S3-13`);
  enforcement (e.g. a cross-strategy exposure cap) is deferred.
  **Reason**: enforcement policy needs its own risk discussion.
  **Planned session**: Session 10 (Paper accounting, costs and risk).
  **Dependency**: `S3-13`'s display feature existing first.
- **`S3-26`** — detailed experiment evaluation criteria and evidence
  sufficiency: deferred until a validation session, before any
  experiment is authorized. **Reason**: needs its own
  criteria-definition discussion, not assumed here. **Planned
  session**: Session 12 (Technical validation, usefulness and economic
  evidence). **Dependency**: none blocking; a prerequisite for any
  future experiment authorization.
- **`S3-27`** — exact historical data feasibility for a genuine 2-year
  replay window: deferred. **Reason**: needs a dedicated data-coverage
  audit. **Planned session**: Session 5 (Data sources, discovery and
  coverage). **Dependency**: none blocking.
- **`S3-28`** — remaining lifecycle semantics, including already-
  committed pending intents when a stock is paused, and exact mute
  controls: deferred. **Reason**: needs the full user-journey mapping
  first. **Planned session**: Session 4 (End-to-end user journey) and/
  or Session 11 (Operation, stop/start and recovery). **Dependency**:
  `S3-11`'s pause/exclude/mute definitions (agreed this session) as
  the starting point.

`OPS-002` (V2 pricing-freshness gap) **remains `OPEN`** —
`OPERATIONAL_FINDINGS.md` has a dated note confirming these product
decisions do not fix it.

### Proposed enhancements (not agreed as requirements)

- None recorded beyond the agreed items above.

### Any separately authorized implementation work

**None.**

---

## Session 4 — End-to-End User Journey

**Recorded**: 2026-09-16, approximately 13:46 UTC / 14:46 BST (Python
`zoneinfo`, this project's established recording-time discipline).
**Source**: the product-owner discussion supplied directly in this
session's prompt (same pattern as Sessions 1–3; the discussion's own
internal timestamp is unavailable and is not invented here).

### Context

This session answers the 9 scenarios Session 3's documentation pass
queued for Session 4 (start/inspect, discovery+manual addition,
intraday full cycle, multi-day full cycle, dual-strategy same-stock,
pause/exclude with obligations, stale-data/downtime, research-candidate
routing, promotion vs. existing-position rules). It refines existing
requirement IDs (`S3-06`/`S3-07`, `S3-11`, `S3-15`-`S3-20`, `S3-28`)
rather than introducing a disconnected specification.

### Agreed product direction

- **One "Start monitoring" action** using previously saved settings —
  a single operator action, not a multi-step manual reconfiguration
  each time.
- **Resume previously-enabled paper strategies only when their
  prerequisites pass**; per-strategy readiness and any **shared**
  dependency failure (e.g. a data feed both Original and V2 rely on)
  are both exposed to the operator, not collapsed into one undiffer-
  entiated "not ready" state.
- **Recover existing obligations and pending intents before new
  discovery** starts — chronological accounting must not change, and
  a later exit's proceeds must never fund an earlier entry (recovery
  order matters for accounting correctness, not just convenience).
- **Preserve campaign balances, positions, reservations and exit
  rules** across a start/stop cycle — a restart is not a reset.
- **Catch-up ingestion must not create late prospective entries or
  stale "act now" alerts** — backfilled data must be evaluated as
  historical context, never presented as a fresh, actionable-right-now
  opportunity.
- **Primary Telegram bot**: qualified intraday and multi-day
  opportunities, lifecycle updates (entry/exit/expiry), and optional
  substantive major corporate developments.
- **Separate Operations bot**: meaningful incidents and recovery
  notifications (distinct audience/purpose from trading opportunities).
- **Optional Research bot remains isolated and OFF by default**
  (reaffirms `S3-21`, now positioned alongside the Primary/Operations
  distinction as a third, clearly separate channel).
- **Bot creation, destinations and credentials require separate
  implementation authorization** — proposed flags/channels must not be
  described as existing features anywhere in product copy or
  documentation.
- **Paper execution is automatic and independent of notification
  success** — a failed/delayed Telegram send must never block or skip
  an actual paper entry/exit.
- **Explicit lifecycle states**, with **separate** missing-price and
  valuation-staleness modifiers (an opportunity's lifecycle state and
  its current pricing confidence are two independent axes, not
  conflated into one status).
- **Pausing new entries cancels unfilled intents atomically**, while
  preserving existing position management (a pause stops new
  commitments; it does not touch positions already entered).
- **EOD reports daily performance, open risk, and unresolved
  obligations** (extends `S2-07` to the multi-strategy/multi-account
  picture Session 3 introduced).
- **Independent outage detection and operational alert deduplication
  remain implementation work, not proven capabilities** — neither is
  claimed as already solved by this session.

### Implementation authorization

**None.** Every decision above is an agreed product direction; all new
implementation authorization is explicitly **"Not authorized by this
documentation task."** See `REQUIREMENTS_TRACKER.md` (`S4-01` through
`S4-14`).

### Differences from current behavior (see `REQUIREMENTS_TRACKER.md` for full detail)

- `talonx_ops.prospective start` is already a single operator command
  (`S4-01`'s intent partially met), but does not itself gate on
  **per-strategy readiness** in the way described — it starts the
  supervised stack as a whole.
- V2's own retry/staleness machinery already has a **distinct**
  "missing market data" disposition (`FAILED_NO_MARKET_DATA`,
  `talonx_v2/service.py:555-571`) separate from the staleness-terminal
  `SKIPPED_ENTRY_STALE` — a real, working precedent for `S4-11`'s
  "separate missing-price/valuation modifier" intent, under different
  naming than what a future Telegram/dashboard surface would show.
- No unified "recover obligations before new discovery" ordering
  guarantee was traced end-to-end across Original/Intelligence/V2 this
  session (each currently runs its own independent startup sequence) —
  `S4-03` is `Not assessed in this documentation pass` at that
  cross-system level.
- No second ("Operations") Telegram bot or research-bot mode-switch
  exists in the codebase inspected this session — targeted search
  found no second bot configuration anywhere (`S4-07`/`S4-08`).
- `pending_entry_intents` rows only have a `PENDING`→(other) status
  transition path driven by fill/expiry logic
  (`talonx_v2/store.py:515-533`) — no explicit, atomic
  "cancel-on-pause" operation was found (`S4-12`).

### Open questions

- Exact UI/copy for per-strategy readiness and shared-dependency-
  failure surfacing — not specified, a future design detail.
- Exact Operations-bot incident taxonomy (what counts as "meaningful")
  — not defined this session.

### Proposed enhancements (not agreed as requirements)

- None beyond the agreed items above.

### Any separately authorized implementation work

**None.**

---

## Session 5 — Data Sources, Discovery and Coverage

**Recorded**: 2026-09-16, approximately 13:46 UTC / 14:46 BST (same
recording pass as Session 4 above; both sessions were supplied
together in this task's prompt). **Source**: the product-owner
discussion supplied directly in this session's prompt.

### Context

This session closes the requirements-level discussion for data
sources, discovery and coverage, carrying forward `S3-27`'s deferred
2-year-replay-feasibility question and `S3-08`/`S3-09`/`S3-10`'s
master-stock-coverage gaps into concrete technical detail across five
areas: master registry/identity, price reference/timestamps,
three-session recovery semantics, corporate actions/fractional shares,
and catch-up/priorities/historical data. **This session is closed at
the requirements level, with explicitly listed technical decisions and
implementation gates still outstanding — it does not establish
execution readiness or universal validation of any of these areas.**

### A. Master registry and identity — agreed

- **One master security registry** with per-strategy/horizon
  eligibility (the concrete data model behind `S3-08`'s master stock
  list).
- **SEC CIK identifies the issuer, not necessarily the specific share
  class/security** — a single CIK can cover multiple share classes or
  security types; the registry tracks **security identity**, **symbol
  history**, and **price-series identity** as related but distinct
  concepts.
- **Refresh bulk mappings daily**, with **bounded event-triggered
  checks** for out-of-cycle changes (not purely a fixed daily batch).
- **Retain the last verified snapshot on refresh failure**, and
  **disclose freshness** — a failed refresh must not silently serve
  stale data as if current, nor crash/block on a transient failure.
- **Preserve immutable historical versions**, **observed timestamps**,
  and **verified effective dates** — without inventing historical
  validity for a mapping that was never actually verified at that
  point in time.
- **Unknown/ambiguous identity blocks only the affected admission(s)**
  — not unrelated securities, and not existing obligations (an
  ambiguous NEW symbol must never retroactively freeze an existing
  position in a different, unambiguous symbol).
- **Registry refresh does not automatically expand approved
  universes** — discovering more identity mappings is not the same as
  authorizing more symbols for trading.
- **Coverage-count accuracy**: this session's discussion referenced
  **27-unresolved / 599-resolved** counts; **no evidence for these
  specific figures was found** in this repository's code, tests, or
  evidence documents during this documentation pass, and they are
  **not adopted**. The actual, evidence-dated counts found this
  session are three **different, non-unified** scopes (consistent with
  `S3-08`'s "three separate lists" finding, not one master registry):
  - **Original**: 48 configured tickers, **43 active/selected**, of
    which **39 are SEC-covered** (`docs/OPERATIONS.md:69`; `docs/
    audits/2026-09-10/README.md:86`; corroborated by multiple Task
    138–140 checkpoint JSON files reading `selected_symbols: 43`, most
    recently `docs/research/evidence/task140/
    cutover_after_full_verification.json`, dated within this project's
    Task 140 work, 2026-09-14/15).
  - **Intelligence**: **569**-symbol effective collection scope
    (`docs/research/evidence/task140/gated_admission_activation.md:52`,
    `effective_symbols: 569`; corroborated by `docs/research/evidence/
    task137/TASK137_OVERNIGHT_CONTINUITY_REPORT.md:160`, "569 symbols
    (39 [SEC-covered from Original's own set]"), dated 2026-09-14).
  - **V2**: **626**-symbol execution scope
    (`execution_scope_count: 626`, `docs/research/evidence/
    eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md` §4, dated
    2026-09-15). None of these three counts is "the" master registry
    count — `S3-08`'s finding that no unified master list exists yet
    stands.

### B. Price reference and timestamps — agreed

- Each strategy/data-contract **version** defines **one primary
  provider, feed, opening-reference definition, and adjustment
  basis** — not an implicit, undocumented default.
- **Official auction price and a provider's daily-bar open are not
  interchangeable** — they can differ, and a system must not treat
  them as the same number without saying so.
- **Actual provider selection and free-tier feasibility remain OPEN**
  — not decided by this session; see the deferrals below.
- **No midday-price substitution or unvalidated provider fallback** —
  if the primary price is unavailable, the system does not silently
  substitute a different provider or a different time-of-day price
  without that being an explicit, validated fallback path.
- **Qualified fallback is future work**, requiring explicit validation
  and **equivalent live/replay rules** (a fallback used live must
  behave the same way a replay of that fallback would).
- **Preserve source time, actual first receipt, processing, and
  notification timestamps separately** — four distinct timestamps, not
  collapsed into one. **Batch timestamps are not observation
  evidence** — a bulk-refresh's own run time must not be presented as
  when a specific fact was actually first true or first observed.

### C. Three-session recovery — agreed

- For `max_entry_staleness_sessions = 3` (V2's existing frozen
  parameter, `talonx_v2/config.py:72`), the **target entry session is
  Session 1** (the session the opportunity first became eligible).
- **Recovery ends at the exchange-calendar official close of Session
  3**, including early-close days and excluding non-trading days —
  calendar-aware, not a naive 3-calendar-day window.
- **Only timely, durably admitted intents may reconcile** — an intent
  that was never durably recorded, or recorded too late, does not get
  a delayed fill.
- **Check expiry before attempting a fill** — the order matters; a
  fill attempt must not proceed on an already-expired intent.
- **Downtime and identity/corporate-action delays do not extend the
  deadline** — the 3-session window is fixed relative to the target
  entry session, not relative to when the system happened to be
  running.
- **Missing-price expiry is `EXPIRED_NO_MARKET_DATA` at the product
  level** — distinct from unresolved-identity or corporate-action
  delay reasons, which must be preserved as their own distinct
  reasons, not collapsed into one generic "expired."
- **Release reservations exactly once**, without inventing a cash
  credit — a reservation release is a bookkeeping unlock, never a
  fabricated gain.
- **Delayed reconciliation preserves the original entry-reference
  session and exit schedule** (the position's own timeline is anchored
  to when it was *supposed* to enter, not when the system happened to
  catch up) — the actual **recorded-at** time is disclosed separately.
- **Exact equality-at-deadline semantics** (is Session 3's own close
  itself still eligible, or only sessions strictly before it?) and
  **receive-versus-commit boundary semantics** (does "received before
  deadline" mean data received, or transaction committed?) are
  recorded as **explicit implementation-acceptance details still
  requiring definition** — not resolved by this session.
- **Finding recorded, not corrected**: a previously-inspected
  deadline-related inconsistency in this area — most directly, Task
  112R's own G1 finding (this project's history: the research
  `build_episodes` methodology enters after the *last* window filing,
  while the Task 109 contract/runtime fires at the *second* distinct
  insider filing, producing 326 entry-session differences in an
  offline comparison; that review concluded the runtime is
  contract-correct, not the research methodology, and made no code
  change) — is logged here as a finding to **re-verify against
  current code** in a future implementation task. **This documentation
  pass does not re-verify or silently correct it** — see
  `OPERATIONAL_FINDINGS.md` `OPS-003`.

### D. Corporate actions and fractional shares — agreed (all future policy; none implemented today)

- **Verified renames** preserve identity and intent via **effective-
  dated mappings**.
- **Before-entry splits** use the corresponding **post-split entry
  basis**.
- **After-target-entry splits during delayed reconciliation** require
  **chronological reconstruction**, applied **transactionally and
  exactly once**.
- **Unverified changes block execution without discarding
  obligations** — an unresolved corporate action pauses that specific
  position's progress, it does not cancel it.
- **Mergers/replacement securities require explicitly supported
  treatment** — no implicit "just use the new ticker" substitution.
- **Whole-share truncate-and-cash-in-lieu is a modeled policy, not a
  guarantee of broker settlement terms** — the model's own rounding
  choice must not be presented as what a real broker would actually
  do.
- **Cost basis is allocated proportionally** to retained and
  liquidated quantities in a partial corporate action.
- **`CORP_ACTION_CASH` is recorded separately**, but its associated
  gain/loss is **included in position and account returns** — it must
  **never be counted as a new deposit**.
- **A missing settlement reference preserves an unresolved
  entitlement**, not fabricated spendable cash.
- **High-precision `Decimal` arithmetic internally.**
- **Posted USD amounts use cents; fractional-share display uses four
  decimal places.**
- **Intermediate entitlements are never truncated to display
  precision** before the final calculation is complete.
- **Exact rounding mode and residual reconciliation** remain
  **explicit technical details to settle before implementation** — not
  decided by this session.
- **Avoid double-adjustment** of prices and quantities (a split-
  adjusted price must not also be applied to an already-split-adjusted
  quantity, or vice versa).

### E. Catch-up, priorities and historical data — agreed

- **Durable source checkpoints**, plus **overlap/deduplication** and
  **recoverable enrichment state** — **no fixed 16-hour completeness
  assumption** (no code or documentation matching a "16-hour" figure
  was found this session; this requirement explicitly rules such an
  assumption out going forward, it does not describe removing an
  existing one).
- **Prioritize obligations and timely intents over bulk historical
  work** — a backlog of historical backfill must never delay servicing
  an active, time-sensitive obligation.
- **A specific pre-market lockout window is PROPOSED/UNDEFINED, not
  agreed** — recorded explicitly as not decided, not defaulted to any
  specific window.
- **Two-year replay feasibility remains OPEN** (extends `S3-27`):
  data availability, granularity, point-in-time universe/identity,
  corporate actions, and licensing **all need evidence** — none of
  these five sub-questions is resolved by this session.

### Implementation authorization

**None.** All new implementation authorization is explicitly **"Not
authorized by this documentation task."** See `REQUIREMENTS_TRACKER.md`
(`S5-01` through `S5-31`).

### Findings tracked in `OPERATIONAL_FINDINGS.md`

Per this session's own instruction to add distinct findings without
duplicating `OPS-002`:
- **`OPS-003`** — the deadline-consistency finding (§C above).
- **`OPS-004`** — corporate-action/fractional-share handling gap (no
  such code exists today; §D above is entirely future policy).
- **`OPS-005`** — price-provider qualification gap (no authoritative
  primary-provider/opening-reference definition confirmed per
  strategy; extends `OPS-002`'s pricing-freshness finding with the
  broader provider-selection question).
- **`OPS-006`** — registry/coverage-scope fragmentation (three
  separate, non-unified symbol scopes — Original 43/48, Intelligence
  569, V2 626 — confirmed this session, extending `S3-08`'s finding
  with dated evidence).

### Explicit deferrals (carried and new)

- **`S3-27`** (2-year replay data feasibility) — **not resolved**,
  restated and detailed as `S5-31`'s five sub-questions; still
  destined for Session 5's own slot... this **is** Session 5, so this
  specific deferral now moves to whichever session performs the actual
  data-coverage audit (not decided; a candidate for Session 12's
  technical-validation work, or a dedicated data-engineering task, not
  a knowledge-transfer session).
- Provider selection and free-tier feasibility (§B) — deferred; no
  destination session assigned yet, candidate for Session 6 or a
  dedicated technical session once V2's own strategy-mechanics
  discussion (Session 6) clarifies which strategies would need which
  providers.
- Pre-market lockout window (§E) — deferred; candidate for Session 9
  (Telegram and dashboard experience) or Session 11 (Operation,
  stop/start and recovery).
- Exact equality-at-deadline / receive-vs-commit semantics (§C) —
  deferred to a future implementation-acceptance task specifically,
  not a knowledge-transfer session (these are technical acceptance
  criteria, not product decisions).
- Exact rounding mode / residual reconciliation for fractional shares
  (§D) — deferred, same destination as above.

`OPS-002` **remains `OPEN`**, unaffected by this session, per this
task's own instruction.

### Any separately authorized implementation work

**None.**

---

## Session 6 — Signal Discovery and Strategy Mechanics

**Not yet conducted.** Carries forward from Sessions 1–5:

- Both intraday and multi-day remain product scope (`S3-01`) — a V2
  deep-dive in Session 6 does not retire the intraday strategy.
- Distinguish signal qualification, portfolio admission, paper
  execution, and Telegram delivery as four separate concepts
  (`S2-04`/`S3-06`) — Session 6 should ground this distinction in
  Original's and V2's actual current rule sets.
- Explain current **frozen** rules (V2's `INSIDER_BUY_CLUSTER_V2@1`,
  Original's existing intraday confluence rules) **separately** from
  any **proposed** change — no tuning or implementation is authorized
  by the discussion itself.
- Preserve `S3-24`'s unresolved deferral: Original's long-term/
  fundamentals path still needs its own role review before Session 6
  or a later session decides to retain, adapt, or retire it.
