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

### Documentation correction (2026-09-16, ~14:03 UTC / 15:03 BST) — three-session recovery implementation status

A follow-up documentation-only task re-examined `REQUIREMENTS_TRACKER.md`
`S5-13`/`S5-14`'s original **`Implemented`** classification and found it
**unsupported**. The original classification cited two real facts
(`max_entry_staleness_sessions = 3` and calendar-aware `add_sessions()`
both exist) but did not verify that they together produce the exact
agreed boundary (target entry session = Session 1, recovery ends at the
exchange-calendar official close of Session 3, expiry checked *before*
any fill attempt).

**Direct code inspection this pass** (`talonx_v2/service.py`,
`talonx_v2/calendar.py`, `talonx_v2/store.py`) found:

- **Two different deadline computations coexist for the same 3-session
  parameter**, one session apart: the general staleness gate that
  controls whether an episode is even attempted for entry at all
  remains open through `eligible_entry_session + 3` sessions (a
  **4-session** window under the product's own 1-indexed counting), while
  the missing-price retry-then-release path's own deadline is
  `eligible_entry_session + 2` sessions (a **3-session** window,
  matching the agreed "ends at Session 3" framing exactly). The
  code's own inline comment confirms this one-session gap is a
  deliberate internal workaround, not an oversight — but it means the
  **entry-attempt boundary** (the one that actually governs whether a
  position can still open) is one session more permissive than the
  agreed policy, even though the **missing-price-release boundary**
  matches it.
- **The fill attempt happens before any deadline check**, not after —
  `_phase_open` unconditionally calls `pipeline.process_episode(...)`
  (the actual fill) for every non-stale episode first; the
  `retry_deadline` comparison is evaluated only reactively, after a
  `NO_ENTRY_BAR` miss is already returned. A successful fill has no
  deadline check gating it beyond the coarser 4-session staleness
  gate above.
- **Everything is date-granular, never close-time-granular** —
  `talonx_v2/calendar.py` is built entirely on `exchange_calendars`
  session *dates* (`[ts.date() for ts in ...]`); it correctly excludes
  non-trading days and correctly includes early-close days as ordinary
  valid sessions, but carries no close-timestamp information at all,
  so there is no code path that can distinguish "before" from "after"
  the actual close time of a given session.
- **Restart/downtime does not extend the deadline** — both deadline
  computations are pure functions of the episode's fixed
  `eligible_entry_session` and the calendar, independent of process
  uptime. This part of the agreed policy **is** correctly implemented.
- **Reservation release is exactly-once** — a single, shared SQL guard
  (`WHERE intent_id=? AND status='PENDING'`, `talonx_v2/store.py:531-533`)
  backs every terminal release path (`EXPIRED_STALE`,
  `FAILED_NO_MARKET_DATA`, and the normal `FILLED` path alike). This
  part **is** correctly implemented, confirmed both by code inspection
  and by running the two directly-relevant, pre-existing, isolated
  tests this pass (`tests/test_task131_nonblocking_retry.py`,
  `tests/test_task113_stale_entry_guard.py` — 8 passed, `tmp_path`-
  isolated, no live system touched).

**Corrected classification**: see `REQUIREMENTS_TRACKER.md` `S5-13`
through `S5-20` for the full, itemized correction and
`OPERATIONAL_FINDINGS.md` `OPS-003` for the complete finding. The
overall three-session-recovery requirement is now classified
**"Partially implemented — session-based recovery exists; exact
Session-3-close enforcement and pre-fill expiry remain pending
OPS-003."** `S5-19`'s unresolved equality-at-deadline and
receive-vs-commit semantics remain **unresolved** — this correction
does not choose them.

This correction is **documentation only** — no code, test, or runtime
behavior was changed. The two test files above were run read-only, as
existing, already-committed tests, to obtain genuine executed-test
evidence rather than relying on source inspection alone.

---

## Session 6 — Signal Discovery and Strategy Mechanics

**Recorded**: 2026-09-16, approximately 18:47 UTC / 19:47 BST (Python
`zoneinfo`, this project's established recording-time discipline).
**Source**: the product-owner discussion supplied directly in this
session's prompt (same pattern as Sessions 1–5; the discussion's own
internal timestamp is unavailable and is not invented here).

### Context

This session grounds Sessions 1-5's distinctions (signal qualification
vs. portfolio admission vs. paper execution vs. Telegram delivery,
`S2-04`/`S3-06`) in Original's and V2's actual current rule sets, and
resolves `S3-24` (Original's long-term/fundamentals path). It covers
nine areas: strategy scope, V2's qualification baseline, Original's
intraday baseline, alerts independent of paper capacity, a new
"Delayed Market Simulation" evaluation mode, entry geometry/next-bar
execution, exit precedence/ambiguity, intraday EOD-flatten recovery,
and deadline-equality/audit-history semantics (resolving `S5-19` at
the requirements level). **Discussion closed; documented requirements,
with explicit deferrals and implementation gates** — this session does
not authorize implementation, and several areas below describe an
**approved target** distinct from the **inspected current baseline**.

### A. Strategy scope — agreed

- **Primary trading product scope**: Intraday Opportunities, and the
  Insider Buying Strategy (V2). "Primary scope" does **not** mean
  currently running, validated profitable, or execution-ready.
- Optional major-company-development notifications remain agreed
  (Session 1) as **informational**, not a third primary trading
  strategy.
- **Fundamental Opportunities is retained as an isolated Research Lab
  candidate** — resolving `S3-24`. No primary Telegram routing or new
  primary paper activation is authorized. The optional research bot
  remains OFF by default. Future promotion requires explicit approval
  following: data/report provenance and freshness review, valuation-
  method review, causal replay, periodic-addition/exit qualification,
  and performance evaluation. No existing process, account, or
  obligation is changed by this decision.
- **Both intraday and multi-day remain primary product scope** — this
  session does **not** repeat or revive the earlier, already-superseded
  proposal to demote Intraday (see `S1-09`'s Session 3 resolution,
  `S3-01`); that decision stands unchanged.

### B. V2 qualification — baseline description (inspected, not proposed)

Recorded as the accurately inspected baseline, not a new decision:

- Code **P only** qualifies a baseline cluster transaction: open-market
  **or** private purchase. P alone does not by itself establish
  personal funding or open-market execution specifically (both are
  possible under code P). Code **M** means exercise/conversion — not
  "acquired without holding" or any other informal reading. Code **J**
  and other non-P codes do **not** qualify a baseline cluster, though
  the underlying records may remain available for company monitoring
  more broadly (Intelligence's own insider-activity tracking is not
  restricted to only cluster-qualifying codes).
- A qualifying cluster requires **at least two distinct reporting-owner
  CIKs** — one owner's repeated purchases alone are insufficient.
  **Filing dates, not purchase (transaction) dates, drive the
  clustering window.** The exact inspected boundary is
  `later_filing_session - first_filing_session <= 10`, described as
  **up to ten trading-session steps apart**, not an inclusive
  ten-session count.
- The detector activates following the **second distinct owner's
  filing date**; actual local receipt and prospective admission remain
  **separate** checks from detection itself.
- Episode construction is **greedy and non-overlapping**.
- **No minimum individual or aggregate insider-purchase dollar amount**
  is enforced by the baseline cluster definition itself.
- The **inspected operational liquidity screen**: twenty prior
  sessions, median daily dollar trading volume >= $5 million, latest
  prior close >= $5.
- Distinct buyers participating in a cluster do **not** by themselves
  establish independent investment decisions or proven market
  consensus — multiple filers can still share non-independent
  motivations.
- **Symbol grouping alone does not prove issuer/security/share-class
  identity integrity** (directly connects to `S5-02`'s CIK-vs-security-
  identity distinction and `OPS-006`'s registry-fragmentation finding).
- **Purchase-size filtering is a future Research Lab hypothesis**, not
  part of today's baseline definition.
- **The frozen contract's own broader eligibility wording is preserved
  as written, and is not silently rewritten to match the inspected
  operational liquidity path** if the two differ — any such gap is
  recorded as a finding (`OPS-006` extension, see below), not resolved
  by editing the contract's own text here.

**Diagnosing signal scarcity** requires the full funnel: coverage,
collected evidence, clusters, qualification, admission, and completed
trades — **no guaranteed trade count or profitability claim** is made
or implied by this baseline description.

### C. Intraday baseline — distinct from target enhancements (inspected, not proposed)

Recorded as **inspected code defaults**, not asserted current runtime
values (defaults can be overridden by environment configuration; this
session records what the code defines, not necessarily what a specific
live process happens to be running right now):

- One-minute RSI recovery: below 30 to >= 30, with qualifying volume.
- MACD 12/26/9 crossover.
- MA 10/50 crossover with separation >= 0.15% of price.
- Trigger-bar true range >= 1x ATR.
- Minimum ATR/price 0.25%.
- Legacy confirmation score >= 2.
- Minimum reward-to-risk 1.5.
- Regular-session bullish trend gate: 200-period SMA of 15-minute bars.
- Twenty-minute cooldown; seventy-five-minute post-loss lockout.

The **RSI-recovery/confirmation interaction** (a signal component that
deliberately self-excludes unless a same-bar MACD cross also coincides
— this project's own prior "RSI-Curl / Confluence Contract" design) is
recorded here as **documented, intentional baseline behavior**, not a
newly proven bug and not an explanation of every historical signal
failure. The **separate legacy MACD direction-confirmation
qualification** is preserved as its own distinct mechanism, not merged
into the RSI-recovery discussion.

**Diagnostics distinguish four separate categories**: strategy
rejection (the signal itself didn't qualify); a data/readiness block
(insufficient bars, missing indicator inputs); strategy suppression/
re-entry restriction (cooldown, post-loss lockout); and portfolio
admission restriction (capacity/cash, independent of signal quality).
**Cooldown, post-loss lockout, and insufficient cash are explicitly
NOT identical mechanisms** — they have different triggers, different
durations, and different scopes, and must not be reported as
interchangeable "blocked" states.

**Bearish observations alone must not execute shorts or automatically
close long positions**, under the agreed product rules (reaffirms
`S2-01`/`S2-02`'s no-shorting rule). Legacy code mappings for this must
be **verified separately** — this session does **not** assert that
every existing path is already compliant; that is a distinct
verification task, not concluded here.

### D. Alerts independent of paper capacity — agreed

- Timely, qualified opportunities remain eligible for **primary
  Telegram notification** even when paper cash/capacity prevents entry
  (reaffirms and sharpens `S2-03`/`S2-04`/`S3-06`). The message states
  clearly that no paper position was opened, and explains the skip
  reason.
- A previously-alerted, still-unfilled opportunity receives **one**
  expiry update.
- A newly-discovered-but-already-expired opportunity stays
  dashboard-visible; a Telegram summary of it is optional/configurable
  (not forced).
- Show deadline, discovery time, and notification time — three
  distinct timestamps.
- **Never present an expired opportunity as a fresh, actionable
  instruction.** Never claim a missed trade "would have been
  profitable."
- Existing positions retain their own exit rules regardless of any of
  the above.
- Prevent duplicate/catch-up alert floods (a backlog of expired
  opportunities must not spam the channel on recovery).
- **Notification success is not a prerequisite for paper execution**
  (reaffirms `S4-10`).

### E. Delayed Market Simulation — agreed (a new, separately identified evaluation mode)

- A distinct intraday evaluation mode, separate from live prospective
  paper execution: processes data **chronologically, using actual
  market timestamps** (not wall-clock arrival order).
- Stores **actual receipt, processing, and notification times
  separately** — never assumes a constant five-minute (or any fixed)
  delay.
- Preserves causal information order; prevents lookahead.
- Every account, its returns, and its alerts are **labelled "Delayed
  Market Simulation"** wherever shown.
- Discloses data age and explicitly flags unverified current-entry
  validity.
- **Results measure the simulation's own contract** — not "returns a
  user could actually have achieved after receiving the Telegram
  message."
- Kept **separate** from prospective (live) paper-execution accounts —
  never the same account or balance.
- Replay (`S3-15`-`S3-20`'s research-lab workflow) and this delayed
  simulation mode **share the same underlying strategy/execution
  rules**, while each records its own, different data-availability
  assumptions distinctly.
- EOD **waits** for required data, or explicitly reports incompleteness
  — it does not fabricate a result from partial data.
- **V2's separately agreed prospective-intent rules (Session 5's
  three-session recovery, `S5-13`-`S5-20`) remain unchanged** by this
  mode — it is an intraday-specific addition, not a V2 change.
- **No existing campaign is silently switched into this mode.**

### F. Entry geometry and next-bar execution — baseline preserved, target approved

**Preserved corrected baseline finding** (inspected, confirmed this
session by direct code reading — see Validation below):
- `QuantScanner._revalidate_candidate()` (`talonx_quant/consumer.py`)
  already recalculates the **full** trade geometry (stop, target, risk,
  reward, ratio) against the **latest buffered close** immediately
  before publication — not just price and ratio in isolation. It
  rejects a candidate with missing geometry, an expired age, or
  insufficient RRR.
- Paper entry uses the alert's signal price, adjusted for simulated
  spread (not the original screening-time price unadjusted).
- The existing `fill_geometry_is_valid()` (`talonx_paper/engine.py`)
  checks the fill lands strictly inside the stop/target bracket **when
  both levels exist** — it deliberately **returns True (passes) when
  either bound is absent**, a pre-existing, documented "nothing to
  validate against" convention shared with the backtest engine's
  identical check, not an oversight.
- The **inspected paper-buy path does not recheck the minimum RRR
  after the spread adjustment** — RRR is validated once, at
  screening/revalidation time, not re-validated against the
  spread-adjusted execution price.
- The existing alert-driven entry mechanism is **not** a consecutive-
  next-bar scheduler — it fires on the alert's own signal bar, not a
  deliberately-delayed "next bar's open."
- **This session explicitly rejects** any claim that "no revalidation
  exists" or that there is a specific, quantified economic bias from
  this behavior — neither claim is supported by the inspected code.

**Approved target** (not implemented; a future design, not today's
behavior):
- Approve an entry using **only** information available at the
  simulated approval time.
- Freeze stop and target **upon approval** — not re-derived later.
- Enter at the **next consecutive eligible one-minute bar's open**,
  under the declared execution-cost model.
- If a later revalidation uses newer information, the eligible entry
  **advances accordingly** — it must never use an earlier bar's
  already-passed open.
- Require finite, valid entry/stop/target values; require
  `stop < modeled long fill < target`.
- Recalculate RRR at the **execution-adjusted** entry price and require
  it to remain >= 1.5 (closing the gap noted in the baseline above).
- **Never move the frozen stop/target levels to rescue an otherwise-
  invalid setup.**
- Record explicit, distinct skip reasons for geometry/data/admission
  failures.
- Missing one-minute intervals **block** new entries pending a bounded
  recovery — **never substitute an arbitrary later bar**.
- The exact missing-bar recovery **duration** remains deferred to
  provider qualification (see deferrals below) — not decided here.
- **No new entry at or after the T-10 cutoff**; cancel any unfilled
  instructions at that point.

**Cost-treatment caveat**: spread/slippage-adjusted entry is explicitly
**not** the same claim as fully net-of-fees-and-exit-cost RRR — the
exact cost treatment for the target design remains to be specified
(deferred to Session 12, see below).

### G. Exit precedence and ambiguity — agreed (target design; largely not implemented today, see validation)

- Market-time sequence determines the first eligible exit; reliable
  finer-granularity data takes precedence over an ambiguous OHLC-only
  assumption when both are available.
- For a position already open, if both stop and target are touched
  within a bar and the actual order is unknown, **assume stop-first**
  and tag the outcome `AMBIGUOUS_INTRABAR_ORDER` — an explicitly
  **conservative assumption**, not a claim of the actual sequence.
  **Never** describe such an unknown outcome as a "winner downgraded to
  a loser" — it is an honestly-flagged ambiguity, not a demotion.
- **Ordinary long stop crossing** fill model: the planned trigger price
  minus a declared adverse sell-side slippage.
- **Gap below stop**: the opening reference price minus a declared
  adverse sell-side slippage — **never fabricate a fill at the
  unavailable stop price itself.**
- **Never automatically fill at a bar's extreme low.**
- **Stop-market assumptions differ from stop-limit behavior** — the two
  order types are not interchangeable in this model.
- Intrabar price ranges **before** an actual entry occurred cannot
  trigger a **post-entry** exit — causal ordering applies within a bar
  too, not just across bars.
- **Exactly-once position closure**: a duplicate or later exit
  instruction for an already-closed position is recorded as resolved
  and must never generate a second sale.
- An explicit strategy **EXIT** signal remains distinct from a bearish
  **observation** (reaffirms §C's no-automatic-close rule).

### H. Intraday EOD flatten and recovery — baseline preserved, target approved

**Inspected baseline** (confirmed this session by direct code reading
— see Validation below):
- Defaults to actual wall-clock **15:50 America/New_York**
  (`talonx_paper/config.py`'s `eod_flatten_hour_et`/`minute_et`
  defaults, `15`/`50`).
- **DST-aware** (converts via `ZoneInfo`, not a fixed UTC offset — so
  the wall-clock target stays correctly pinned across the spring/fall
  transition) **but the scheduling helper is not exchange-calendar-
  aware** — it does not check whether "today" is an actual XNYS
  trading session before scheduling or firing.
- Uses the **latest cached positive price**, adjusted for simulated
  spread, to flatten.
- **No price-age check** exists in this sweep.
- A missing price is **logged and skipped** — **no dedicated, durable
  EOD-recovery state** is established by this path (it is not
  persisted for a later retry beyond the next day's own scheduled
  sweep).
- A scheduler started at or after the cutoff simply schedules its
  **next daily** occurrence (tomorrow's 15:50 ET), not an immediate
  catch-up.
- This sweep is **distinct** from other operator reconciliation
  commands (e.g. `talonx_ops.prospective close`, `talonx_ops.
  eod_reconciliation`) — it is Original's own intraday-specific
  mechanism, not the same code path.

**Approved target** (not implemented; a future design):
- Cutoff = the official exchange-session close **minus ten minutes**.
- Use the open of the one-minute bar **starting at that cutoff**,
  adjusted for declared sell-side execution costs.
- **Scheduled in advance, in market time** (not a wall-clock-only
  timer).
- No new entries at/after the cutoff; cancel any outstanding unfilled
  entries at that point.
- A missing exact reference produces `EXIT_PENDING · AWAITING_PRICE` —
  **no stale cached-price or later closing-auction substitution.**
- **Recover through the official close of the next trading session.**
- **Persist recovery state across restarts.**
- While exit/account state is unresolved, **block new entries in that
  specific strategy account**, while independent scanning/data
  collection continues unaffected.
- **Notify Operations once**, with deduplicated incident follow-ups
  (not a repeated alert storm).
- On final expiry of the recovery window, transition to
  `EXIT_UNRESOLVED` — **retain the position/obligation and the account
  block** until an auditable resolution occurs.
- **Manual intervention means investigation and authorized
  reconciliation — never inventing a price.**

**Shared recovery handling** may architecturally cover other intraday
exits (stop, target, strategy EXIT) alongside EOD flatten, but **each
must recover its OWN evidence and reference**, not a shared/generic
one:
- **EOD**: the original cutoff bar's own open.
- **Stop**: the crossing/gap evidence and the stop-fill model (§G).
- **Target**: the crossing evidence and the declared target-fill model.
- **Strategy EXIT**: its own designated subsequent execution reference.

If missing data makes **whether or when** an exit occurred genuinely
unknown, that uncertainty is represented **explicitly** — never
silently resolved either way. **These intraday rules do not apply to
V2 or to the (Research-Lab-only) fundamentals account** — V2 keeps its
own, separately agreed three-session recovery (`S5-13`-`S5-20`), kept
explicitly distinct from this intraday next-session-close EXIT
recovery.

### I. Deadline equality and audit history — agreed (resolves S5-19 at the requirements level)

- **Evidence durably received AT OR BEFORE the deadline qualifies** for
  subsequent processing; evidence first received **afterward** cannot
  qualify the original entry.
- **Serialize expiry/reconciliation** so that a reservation can never
  be both released AND filled for the same instruction.
- **Preserve original expired/unresolved history** — never overwritten.
- **Later corrections are versioned, auditable reconciliation** — never
  a silent edit of the original record.
- **No silent conversion of a late discovery into an on-time
  prospective trade.**
- Implementations must correctly handle evidence that was **timely
  received but is still awaiting validation** — and must never invent
  a receipt timestamp from a batch/refresh label (reaffirms `S5-12`'s
  "batch timestamps are not observation evidence").

This resolves `S5-19`'s exact equality-at-deadline and receive-versus-
commit semantics **at the requirements level** — the product's
intended answer is now recorded. **Implementation and validation
remain separately tracked under `OPS-003`** — this session does not
itself implement or verify this semantics against V2's or Original's
actual code; see `REQUIREMENTS_TRACKER.md` `S5-19`'s dated update and
`S6-24` below.

### Implementation authorization

**None.** Every decision above is an agreed product direction (or, for
§B/§C/§F's "inspected baseline"/§H's "inspected baseline" content, an
accurately recorded description of existing code); all new
implementation authorization is explicitly **"Not authorized by this
documentation task."** See `REQUIREMENTS_TRACKER.md` (`S6-01` through
`S6-24`).

### Validation performed this session

Targeted, read-only code inspection (not an exhaustive audit) directly
confirmed: `QuantScanner._revalidate_candidate()`
(`talonx_quant/consumer.py:2017`) and `fill_geometry_is_valid()`
(`talonx_paper/engine.py:156-186`, including its documented
either-bound-absent pass-through); `talonx_paper/config.py`'s
`eod_flatten_hour_et=15`/`eod_flatten_minute_et=50` defaults and
`seconds_until_next_eod_flatten()`'s `ZoneInfo`-based DST handling
with no `exchange_calendars`/session-awareness in
`talonx_paper/consumer.py`'s flatten loop; `talonx_quant/config.py`'s
RSI/MACD/MA/ATR/cooldown/lockout defaults (`rsi_oversold=30`,
`macd_fast/slow/signal=12/26/9`, `ma_fast/slow=10/50`,
`min_ma_spread_pct=0.0015`, `min_atr_pct=0.25`,
`cooldown_seconds=1200`, `loss_lockout_seconds=75*60`), all matching
§C's recorded defaults exactly. **Not individually re-verified this
session**: the exact `legacy confirmation score >= 2` and `minimum RRR
1.5` constants specifically (not located by name in the same targeted
read), and none of §G's exit-precedence/ambiguity claims — a repository
-wide search for `AMBIGUOUS_INTRABAR_ORDER`, `EXIT_UNRESOLVED`, and
`EXIT_PENDING` found **no matches anywhere in `talonx_paper/`**,
confirming §G and §H's "approved target" content (these specific
status labels) is **not implemented today** — a genuine gap, not
merely undocumented.

### Explicit deferrals

- **`S6-25`** — numerical spread/slippage/fee assumptions for the
  entry-geometry target design (§F). **Reason**: needs its own
  cost-model evaluation. **Planned session**: Session 12 (Technical
  validation, usefulness and economic evidence). **Dependency**: none
  blocking to state the target qualitatively (done, §F); blocking for
  exact numbers.
- **`S6-26`** — missing intraday entry-bar recovery duration (§F).
  **Reason**: depends on which data provider is ultimately qualified.
  **Planned session**: none (a data-provider qualification task, not a
  knowledge-transfer session) — extends `OPS-005`'s open provider-
  qualification question. **Dependency**: `OPS-005`.

Existing baseline cost settings (Original's current spread/slippage
model as coded today) are **unchanged** by this session. Several
subordinate technical details remain outstanding before any of §F/§G/H's
approved targets could be implemented (exact cost treatment, missing-
bar recovery duration, precise EOD-cutoff-bar sourcing) — this session
does not claim all execution mechanics are implemented; see
`OPERATIONAL_FINDINGS.md` `OPS-007` through `OPS-009` below.

### Findings tracked in `OPERATIONAL_FINDINGS.md`

- **`OPS-007`** — intraday EOD-flatten durable-recovery gap (§H's
  approved target vs. inspected baseline).
- **`OPS-008`** — entry-geometry next-bar-execution and pre-fill RRR
  re-check gap (§F's approved target vs. inspected baseline).
- **`OPS-009`** — exit-precedence/ambiguity handling gap (§G's target
  vs. no matching status codes found in `talonx_paper/`).

`OPS-002` and `OPS-003` **remain `OPEN`**, unaffected by this session
— re-confirmed by this session's own targeted code reads (no evidence
of closure found for either).

### Any separately authorized implementation work

**None.**

---

## Session 7 — Intelligence and Useful Company Developments

**Recorded**: 2026-09-16, approximately 20:55 UTC / 21:55 BST (Python
`zoneinfo`, this project's established recording-time discipline).
**Source**: the product-owner discussion supplied directly in this
session's prompt (same pattern as Sessions 1–6; the discussion's own
internal timestamp is unavailable and is not invented here). **Status:
discussion closed; agreed requirements documented, with numerical
policy choices deferred and implementation/validation separately
tracked.**

### Context

This session answers the pointers Session 6's documentation pass
queued here: `S1-05`'s unresolved SEC-jargon gap, `S1-13`'s non-
exhaustive wording-accuracy guardrail, Session 6 §B's identity-
grouping caveat, and `S5-01`-`S5-07`'s master-registry background. It
covers eight areas: purpose/routing, a six-question qualification
rubric, materiality routes, plain-language presentation, development-
centric grouping, timestamps/freshness, user controls/corrections, and
coverage/dashboard visibility.

### A. Purpose and routing — agreed

- Primary Telegram supports **both** qualified trading opportunities
  **and** explicitly opted-in major company developments.
- Company-development notifications are **informational** — they do
  **not** automatically create paper trades.
- Routine filings remain **dashboard-only**.
- Operations incidents and optional Research Lab notifications retain
  their **separate routing** (reaffirms `S4-06`/`S4-07`/`S4-08`).
- **Intraday and Insider Buying remain primary trading product scope**
  — this session does **not** revive the earlier, already-superseded
  proposal to demote Intraday (reaffirms `S3-01`/`S6-04`).
- **No proposed bot or flag is described as already deployed** — the
  Operations bot, Research bot, and any new opt-in flag discussed
  remain proposed/target, not existing features (reaffirms `S4-09`).

### B. Six-question qualification rubric — agreed

A major-development candidate must establish all six:
1. What specifically changed?
2. Which verified company/security is affected?
3. Why might it matter, using concrete context?
4. Is it new and timely?
5. Has this development already been reported?
6. What remains uncertain?

**A filing category, watchlist membership, or a `HIGH`/`CRITICAL`
label alone does not establish qualification.** If the system
recognizes a category but cannot extract substantive facts, the
candidate is **retained on the dashboard pending qualification** — a
generic "something important happened" message is never sent.

### C. Materiality routes — agreed

- Maintain a **versioned catalogue** of event-specific evidence and
  materiality rules.
- **Route 1 — verified significant status change** (e.g. a deal
  termination, an explicit dividend suspension): no universal numerical
  threshold is required, but identity, status, and necessary context
  must be established.
- **Route 2 — measured quantitative development**: uses comparable
  metrics and **approved, event-specific** thresholds. For revisions,
  matching periods, units, currency, and accounting basis must be
  verified. For financing, purpose, terms, and suitable company-scale
  context must be assessed — an old/new pair is not always the
  appropriate comparison. **Debt-to-cash or debt-to-market-cap are
  possible measures, not approved universal thresholds.**
- **Routine earnings releases remain dashboard-only** unless their
  content establishes a qualifying material development. A structural
  catalyst is **not required in every case** — a sufficiently material,
  verified financial change may qualify on its own. **Never** claim
  "beat expectations" without a reliable comparison dataset. **Never**
  assert all quarterly releases universally use the same SEC item.
- **Missing reasons**: a verified development may still qualify when
  its reason is undisclosed, **if** that reason is not necessary to
  establish materiality — state "reason not disclosed in the reviewed
  source" where supported. **Never infer misconduct, distress, or
  future price direction.** Missing context that *prevents*
  qualification results in dashboard-only status.
- **"Material" means relevant under this product's own policy** — not
  a legal materiality determination, and not a guarantee of market
  impact.

### D. Plain-language presentation — agreed

A concise alert contains: company and development type; one sentence
explaining the verified development; "why it matters," clearly
distinguishing interpretation from source facts; relevant status,
terms, and limitations; source publication time and detection delay;
an informational/no-paper-trade indication; and reply-for-details
access to sources and supporting evidence. **Avoid**: unexplained SEC
jargon, generic repeated category labels, unsupported confidence
claims, and invented financial context.

### E. Development-centric grouping — agreed

- One **development record** may link multiple filings, press
  releases, agreements, and amendments.
- Grouping uses **verified entities, transaction/topic, and relevant
  dates** — ticker alone or accession alone is insufficient.
- Duplicate sources and administrative amendments **enrich the record
  without another Telegram notification**.
- Distinct, unrelated developments within one filing remain **separate
  candidates**.
- Related financing may be **supporting context** for an acquisition
  rather than a redundant second alert.
- **Uncertain relationships remain explicit — grouping is never
  fabricated.**
- **Subsequent notifications require**: a qualifying material change →
  `UPDATE`; repair of materially wrong previously-delivered information
  → `CORRECTION`. An update explains what changed since the prior
  message and links to it. **A genuine later development is not a
  correction of formerly accurate reporting.** Source and notification
  history are preserved.

### F. Timestamps and freshness — agreed

Keep **four** timestamps distinct: occurred/effective time (if known —
occurrence and effective dates may differ; never forced into one
misleading value); source publication time; actual first local
detection/receipt time; successful notification-sent time. Previously
agreed processing timestamps are retained separately. **Batch labels,
DB-read times, and enrichment times must never impersonate first
receipt or source publication.**

- **Store authoritative timestamps in UTC.** Use explicit display
  zones: America/New_York follows its own DST rules; UK display uses
  Europe/London, correctly showing GMT or BST — **never hardcode BST
  year-round.** Unknown times remain unknown, never invented.
- **Freshness follows the relevant source publication time**: restart,
  reprocessing, or a duplicate document does **not** refresh event age.
  A material update to an old development has its **own** evidence/
  publication time. An unknown publication time results in dashboard-
  only status pending verification. A fresh, qualified catch-up event
  may still alert if all routing conditions pass. A genuinely stale
  startup backlog must **not** generate an immediate-alert flood.
  Delayed-development summaries are optional and **OFF by default**.
- **Numerical freshness windows remain deferred** (see below) —
  existing policy values are inspected and recorded as **current
  implementation only**, not silently replaced or newly approved.

### G. User controls and corrections — agreed

- Major-development Telegram notifications require **explicit opt-in**,
  persisted across restarts.
- **Per-stock company-event mute** suppresses those pushes only, **not
  collection**.
- Company-event mute does **not** suppress trade opportunities, exits,
  or Operations incidents.
- **Trading pause does not automatically pause company monitoring.**
- Delayed summaries have their own **separate** opt-in, **OFF by
  default**.
- **Material corrections** to previously delivered alerts: remain
  eligible despite ordinary stock/category event mutes; may repair an
  old alert even after its original freshness window has expired; must
  link to the original message and clearly identify itself as a
  correction; must **not** bypass a global delivery shutdown or a
  revoked destination; must **not** be broadcast to new recipients;
  preserve pending correction/audit state when delivery is unavailable;
  a minor formatting change does **not** warrant a corrective
  notification.
- **Distinguish four separate concepts**: event qualification, delivery
  eligibility, delivery attempts, and confirmed delivery.

### H. Coverage and dashboard visibility — agreed

Distinguish five states/dimensions: (1) no qualifying development
found; (2) collection delayed/unavailable; (3) document collected,
extraction incomplete; (4) identity unresolved; (5) development
qualified, notification disabled/muted. **These may be separate
dimensions rather than mutually exclusive states** — one label must
never conceal another, different problem. **An empty Telegram feed is
not evidence that nothing important occurred.** Source, identity,
extraction, and timing limitations are disclosed; **exhaustive
company-news coverage is never claimed.**

### Implementation authorization

**None.** Every decision above is an agreed product direction; all new
implementation authorization is explicitly **"Not authorized by this
documentation task."** See `REQUIREMENTS_TRACKER.md` (`S7-01` through
`S7-26`).

### Validation performed this session

Targeted, read-only code inspection (not an exhaustive audit) directly
found:
- `talonx_ingest/intelligence/delivery/update_policy.py`'s
  `classify_update()` — a real, deterministic `NEW` / `UPDATE` /
  `SUPPRESS_DUPLICATE` / `SUPPRESS_NOOP` decision keyed on rendered
  `content_hash` and significance band. This is genuine, working
  precedent for §E's `UPDATE` concept — **but there is no
  `CORRECTION` decision type**; a materially-wrong repair and a
  genuine new material change are not currently distinguished from
  each other in this code.
- `DeliveryOutbox` (`talonx_ingest/intelligence/delivery/outbox.py`)
  operates on a single `delivery_id` per `event_id` — **no
  `development_id`/group/topic field was found** — confirming §E's
  multi-filing "development record" grouping is **not implemented**;
  today's update/dedup mechanism works within one event's own delivery
  history, not across a merged group of filings.
- A search of `talonx_ingest/intelligence/dashboard/render.py` for
  "mute" found only a CSS class name (`.muted`, a text-styling
  convention) — **no per-stock company-event mute feature exists**.
- `claim_safety.py`'s predictive-language block
  (`talonx_ingest/intelligence/delivery/claim_safety.py:42`) rejects
  price-target/expected-return language — it does **not** separately
  guard against inferring misconduct or distress; §C's "never infer
  misconduct, distress, or future price direction" is **partially**
  matched (price-direction only) by existing code, not fully.
- Original's ticker-pause (`talonx_watchlist/store.py`, `S3-11`'s
  evidence) and Intelligence's own collection scope
  (`talonx_ingest/intelligence/service/scope.py`) are **structurally
  separate systems** (confirmed, `S3-08`/`OPS-006`) — meaning "trading
  pause does not automatically pause company monitoring" is **true
  today**, though as a side effect of the systems being unmerged, not
  by deliberate designed control.
- Intelligence's existing significance engine
  (`talonx_ingest/intelligence/significance/`, frozen ruleset
  `information-significance-v1`) is a **band scorer**
  (LOW/MEDIUM/HIGH/CRITICAL) — it is **not** the same thing as §C's
  versioned, route-specific materiality catalogue; the two are
  related but distinct, and this session does not claim the existing
  scorer already implements the new catalogue.
- The existing content gate (`notification_policy.py`'s
  `_substantive_evidence`/`SUBSTANTIVE_REASON_CODES`, this project's
  Task 140/140b/140c hardening) is a **coarser, single-axis** check
  (does non-generic evidence text exist at all) — it does **not**
  implement §B's six distinct rubric questions individually.

None of these findings were inferred from a function name, a generic
significance score, a passing unrelated test, or a prior narrative
claim alone — each is grounded in a specific, cited code read this
session. **Not assessed this session** (targeted inspection was
insufficient, marked honestly rather than guessed): the exact reply-
correlation-vs-update/correction-linkage relationship beyond what
`update_policy.py` shows; per-domain bot-routing enforcement details;
extraction-coverage completeness; and full timestamp-provenance tracing
end-to-end for a real event.

### Explicit deferrals

- **`S7-25`** — numerical freshness windows. **Reason**: requires a
  bounded review of representative historical filings (selection
  method, examples, false positives/misses, coverage limitations, and
  proposed acceptance criteria must all be recorded when that review
  occurs) before any specific number is chosen. **No numerical
  threshold is invented in this documentation task.**
- **`S7-26`** — event-specific quantitative materiality thresholds
  (§C Route 2). **Reason**: same bounded-review requirement as
  `S7-25`. **This documentation task does not authorize a new
  extraction/LLM project by implication** — reviewing representative
  filings is a future, separately authorized task.

`OPS-002` and `OPS-003` **remain `OPEN`**, unaffected by this session —
re-confirmed by this session's own targeted code reads (no evidence of
closure found for either).

### Findings tracked in `OPERATIONAL_FINDINGS.md`

- **`OPS-010`** — development-centric grouping not implemented (§E);
  today's update/dedup mechanism operates per single event, not across
  a merged multi-filing development record; no `CORRECTION` decision
  type distinct from `UPDATE` exists.
- **`OPS-011`** — per-stock company-event mute and materiality-
  catalogue gap (§B/§C/§G); no versioned materiality-routes catalogue
  and no per-stock mute feature exist; the existing significance
  engine and content gate are related but distinct, narrower
  mechanisms.

### Any separately authorized implementation work

**None.**

---

## Session 8 — V2 Multi-Day Strategy and Lifecycle

**Recorded**: 2026-09-16/17 (UTC/UK boundary), approximately 23:05 UTC
/ 00:05 BST 2026-09-17 (Python `zoneinfo`, this project's established
recording-time discipline). **Source**: the product-owner discussion
supplied directly in this session's prompt (same pattern as Sessions
1–7; the discussion's own internal timestamp is unavailable and is not
invented here). **Status: discussion closed; requirements documented,
with provider-finality and cooldown-boundary verification outstanding,
and implementation separately tracked.**

### Context

This session grounds Session 6 §B's V2 qualification-baseline
description in the full lifecycle it always implied — pre-open
catch-up/admission, delayed-price entry reconciliation, the holding
clock, scheduled exit and fall-forward, pending-vs-unresolved account
behavior, re-entry cooldown, and acceptance-evidence requirements. It
directly grounds `S5-13`-`S5-20`'s three-session recovery correction
(`OPS-003`) and `S1-06`'s V2-specific actionability-status question.

### A. Pre-open catch-up and admission — agreed

- Startup catch-up may create a valid V2 intent when all prerequisites
  pass **and** admission is durably committed **strictly before** the
  target session's exchange-calendar open.
- A delayed opening print or delayed provider delivery does **not**
  extend this admission deadline.
- Continuous overnight operation is **not required** by this policy,
  but timely startup/catch-up completion is **not guaranteed** either.
- Preserve actual filing availability, first receipt, and durable
  admission timestamps **separately**.
- **No retrospective entry where no timely intent existed.**
- Late-discovered opportunities remain visible with a **truthful**
  expired/skipped status, under the previously agreed notification
  policy (`S7-01`-`S7-24`).
- Qualification, admission, paper execution, and Telegram delivery
  remain distinct (reaffirms `S2-04`/`S3-06`/`S6-06`).
- Capacity-skipped qualified opportunities remain eligible for
  notification, with explicit disclosure that no paper position opened
  (reaffirms `S2-03`/`S6-13`).

### B. Valid intent with delayed entry price — agreed

- A timely-admitted intent may remain `PENDING_ENTRY · AWAITING_PRICE`.
- Its reservation is preserved during the approved recovery period.
- Reconcile **only** the designated target-session opening reference —
  **never** substitute a midday quote or a later session's opening
  price.
- Apply the previously agreed Session-3-close entry-recovery
  requirement, including exchange-calendar early closes
  (`S5-13`/`S6-24`).
- Preserve `S5-19`/`S6-24`'s agreed durable-receipt deadline semantics.
- **Exact enforcement remains implementation work under `OPS-003`**
  unless directly established by current evidence (see Validation
  below).
- **Intraday next-bar simulation rules (`S6-16`/`S6-17`) do not apply
  to V2.**

### C. Holding clock and position management — agreed

- Entry session is **Session 0**.
- Scheduled exit is the close of the **tenth trading session after
  entry**.
- Holidays/non-trading days do **not** increment the holding clock.
- Delayed entry reconciliation does **not** shift the scheduled exit
  session.
- Preserve intended market time and actual reconciliation time
  **separately**.
- **No price-based stop-loss** in the frozen V2 baseline.
- **No position additions** merely because another cluster appears for
  an already-open symbol.
- Pause, exclusion, or scope removal **must not abandon existing
  obligations** (reaffirms `S3-11`'s Pause/Exclude semantics, extended
  to V2).
- Missing valuations are explicitly **stale/unknown, never a
  fabricated zero P&L** (reaffirms `S2-12`/`S5-16`).
- Corporate actions follow the previously agreed chronological
  accounting policy without resetting the exit clock — this is
  **target behavior, not automatically implemented** (`OPS-004`
  remains open).
- This session does **not** imply all actual V2 quantities today are
  already whole shares — fractional-share handling remains entirely
  future policy (`S5-26`/`S5-27`, `OPS-004`).

### D. Scheduled exit and fall-forward — preserved (V2's frozen contract)

1. Use the target Session 10 closing reference when qualified and
   available.
2. If unavailable under the applicable policy, select the **earliest
   eligible close** in the following five trading sessions.
3. If no qualifying close is available through that extension, retain
   the obligation explicitly as `EXIT_UNRESOLVED`.

- **Never select the best-performing later price.**
- Later sessions must actually have occurred — **no future-data use.**
- "First available" must not be silently reinterpreted as whichever
  provider response happens to arrive first (a genuine ordering, not a
  race).
- Record target exit session, actual modeled exit session, selected
  source, reference price, and reconciliation time.
- **V2 fall-forward may change the exit session; it differs from
  intraday recovery of the original T-10 cutoff reference** (Session
  6 §H, `S6-22`/`S6-23`) — the two mechanisms are for different lanes
  and must not be conflated.
- Once committed, the exit is **never silently replaced** when older
  data is later backfilled or corrected.
- Proven errors may require **versioned, auditable correcting
  entries**, preserving the original record and complete provenance
  (reaffirms `S6-18`'s corporate-action-recovery discipline and
  `S7-14`'s correction-linkage intent).

**Explicit deferral**: the boundary between provisional/delayed and
genuinely unavailable target closing data requires chosen-provider
finality/publication qualification. **No waiting duration is invented
here, and this boundary is not claimed resolved.** Tracked as `S8-25`,
linked to `OPS-005`'s open provider-qualification question.

### E. Pending versus unresolved account behavior — agreed

**`EXIT_PENDING · AWAITING_PRICE`**:
- Position remains open and occupies capacity.
- No anticipated sale proceeds are credited or reused.
- Otherwise-valid entries for other securities may continue **only**
  when account cash, capacity, risk, and data checks remain reliable.
- This permission does **not** override another legitimate account
  block.

**`EXIT_UNRESOLVED`**:
- Position and obligation remain visible.
- **Block new entries in the affected V2 account until auditable
  resolution.**
- Continue managing other positions, collecting data, and reporting
  status.
- Requires operator investigation/recovery — **never invent a closing
  price.**
- The block is **not** cleared merely because the process restarts.
- This is a **containment policy**, not evidence that ledger
  corruption occurred.
- **Do not automatically apply the V2 block to independent strategy
  accounts** (Original, any future Research Lab account).

**`CLOSED`**:
- Commit settlement, proceeds, and capacity changes **exactly once**.
- Duplicate or late instructions cannot create another sale.
- Notification failure does not roll back or duplicate accounting
  (reaffirms `S4-10`).

**Valuation freshness is kept separate from exit lifecycle status**
(reaffirms `S2-12`).

### F. Re-entry cooldown — agreed

- **Agreed anchor: the actual modeled exit session, including a
  fall-forward exit** — not the original target session.
- Delayed notification or reconciliation time does **not** restart the
  cooldown.
- Frozen cooldown length remains **five trading sessions per issuer**.
- A new entry still needs a **newly qualifying opportunity** and
  **timely admission** — cooldown ending does **not** itself generate
  a BUY.

### G. Acceptance requirements — agreed (evidence tracked separately per item, see Validation)

Track evidence separately for: (1) restart after committed admission
without duplicate reservation/entry; (2) interruption during entry/
exit without duplicate economic effects; (3) delayed entry
reconciliation preserving the scheduled exit clock; (4) earliest
eligible fall-forward selection, never best-price selection; (5) scope
removal preserving existing exit obligations; (6) pending/unresolved
exits retaining capacity and preventing phantom proceeds; (7)
corporate-action recovery without double adjustment; (8) notification
failure leaving accounting intact.

Also identify necessary boundary coverage for: admission at vs. before
market open; holidays and early closes; account-block persistence/
release; actual-exit-anchored cooldown; provider provisional/final
data and late backfills.

**Existing tests may satisfy individual requirements — cite what they
exercise. The entire lifecycle is not accepted merely because a
zero-position live session preserved cash, or because unrelated tests
pass** (see Validation below for the specific tests actually run and
what each one covers).

### Implementation authorization

**None.** Every decision above is an agreed product direction (§D
preserves the existing frozen contract, it does not change it); all
new implementation authorization is explicitly **"Not authorized by
this documentation task."** See `REQUIREMENTS_TRACKER.md` (`S8-01`
through `S8-18`, plus deferrals `S8-25`/`S8-26`).

### Validation performed this session

Targeted, read-only code inspection **and** execution of two
pre-existing, isolated test files (not the full suite) directly
confirmed:

- **§A (pre-open admission)**: `V2Service._verify_temporal_boundary()`
  (`talonx_v2/service.py:796-`) is a real, rigorous, fail-closed check
  that BOTH the activating filing's real dissemination timestamp AND
  the admission-decision moment occurred strictly before the entry
  session's RTH open — an unknown dissemination timestamp is a
  **strict failure** on any live tick, never silently treated as safe.
  **Implemented.**
- **§D (fall-forward)**: `settle_due_exits()`
  (`talonx_v2/pipeline.py:132-202`) directly matches the three-step
  contract verbatim — tries the target session first, then the
  earliest available close in the next `exit_fallforward_max_sessions`
  (frozen at `5`, `talonx_v2/config.py:41,98`) sessions (first found,
  never best), then `store.mark_exit_unresolved()` if none is found.
  The code's own comment states "Never backwards. Never 'best
  price'." **Implemented**, and directly exercised by
  `tests/test_task117_phase0_entry_timing.py::
  test_e8c_exit_unresolved_when_target_and_all_fallforward_missing`
  (run this session, **passed**).
- **§F (cooldown anchor and boundary)**: `paper.close_position()`
  (`talonx_v2/paper.py:155-191`) computes
  `cooldown_until = add_sessions(exit_session, 5)` using the actual
  **modeled** `exit_session` parameter (post-fall-forward, not the
  original target session) — directly confirming the agreed anchor.
  **The boundary question is directly resolved by code inspection,
  not left uncertain**: `open_position()`'s own gate
  (`talonx_v2/paper.py:104-106`) reads `if cd is not None and es < cd:
  skip` — entry is blocked when the candidate entry session is
  strictly before `cooldown_until`, and allowed when it equals or
  follows it. **The first eligible re-entry session is exactly
  `exit_session + 5` trading sessions (inclusive at exactly +5), not
  +6.** `hold_trading_days=10`, `reentry_cooldown_trading_days=5`, and
  `exit_fallforward_max_sessions=5` are all frozen with explicit
  runtime asserts (`config.py:88,91,98`). **Implemented.**
- **§E (`EXIT_UNRESOLVED` account block) — genuine gap found**:
  `mark_exit_unresolved()` (`talonx_v2/store.py:410-419`) sets a real,
  distinct `EXIT_UNRESOLVED` status (its own docstring: "Not OPEN...
  not CLOSED... loudly surfaced for the operator") and is correctly
  surfaced in service status output (`store.unresolved_positions()`,
  referenced at `service.py:1054,1159`). **However, no code path was
  found that blocks NEW entries account-wide when an `EXIT_UNRESOLVED`
  position exists** — `unresolved_positions()` is used only for status
  reporting, never consulted by `open_position()`'s own admission gate.
  The agreed "block new entries in the affected account until
  auditable resolution" is therefore **not implemented** — see
  `OPERATIONAL_FINDINGS.md` `OPS-012`.
- **§G items 1/2 (restart, no duplicates)**: directly exercised by
  `tests/test_task117_phase0_entry_timing.py::
  test_e5b_duplicate_filing_or_restart_no_second_buy` and
  `tests/test_task131_atomic_transactions.py`'s full suite (atomic
  commit of position+cash+trade+cooldown together; nested-transaction
  rollback; `close_position` leaves nothing partial if `set_cooldown`
  fails) — **23 tests run this session across both files, all
  passed**, `tmp_path`-isolated, no live system touched.
- **§B/naming gap, consistent with `OPS-003`'s prior findings**: no
  code was found using the literal label `PENDING_ENTRY · AWAITING_
  PRICE` or `EXIT_PENDING · AWAITING_PRICE` — the internal code's
  actual names are `FAILED_NO_MARKET_DATA` (entry-side, `S5-16`'s
  prior finding) and `EXIT_BAR_PENDING_FALLFORWARD`/`EXIT_UNRESOLVED`
  (exit-side, confirmed this session) — functionally consistent, not
  identically named. This is a **naming gap**, not a behavior gap, per
  the same distinction already established for `S5-16`.

**Not assessed this session** (targeted inspection was insufficient,
marked honestly rather than guessed): §G items 3, 5, 6, 7, 8
individually (only items 1/2/4 were directly, freshly exercised this
session — 3/5/6/7/8 rely on established prior evidence or remain
unverified); the exact holiday/early-close boundary coverage for §D's
fall-forward loop (the loop uses `add_sessions`, which is
calendar-correct by construction per `S5-13`'s established evidence,
but a dedicated holiday-spanning fall-forward test was not located or
run this session).

### Corrections to Session 6's evidence (per this session's own instruction)

Session 6's `OPS-009` finding ("no matches for `AMBIGUOUS_INTRABAR_
ORDER`/`EXIT_UNRESOLVED`/`EXIT_PENDING` in `talonx_paper/`") was
correctly scoped to **Original's intraday** engine
(`talonx_paper/engine.py`) — it does **not** describe V2
(`talonx_v2/`), which is a separate codebase. This session confirms
`EXIT_UNRESOLVED` **does** exist as a real status in V2
(`talonx_v2/store.py`), consistent with, not contradicting,
`OPS-009`'s own scope (Original only). No correction to `OPS-009`
itself is needed — this note exists only to prevent a reader from
conflating the two systems' exit-status naming.

Separately, this session reaffirms Session 7's own correction of
`S6-19`/`S6-20`: `check_stop_take()` checking stop-before-target
against **one current price** (Original's intraday engine) is a real,
working tiebreak, but it is **not** the same claim as full OHLC
intrabar-sequence resolution — that distinction stands unchanged,
carried forward, not re-litigated here.

### Findings tracked in `OPERATIONAL_FINDINGS.md`

- **`OPS-012`** — V2's `EXIT_UNRESOLVED` account-block gap: the status
  exists and is surfaced, but no code blocks new entries account-wide
  while it is active.

`OPS-003`, `OPS-004`, `OPS-005` **remain `OPEN`** — this session adds
evidence (§A/§D/§F confirmed implemented) but resolves none of them;
provider-finality (§D's deferral) and the exact `OPS-003` equality-at-
deadline/pre-fill-check gates remain outstanding.

### Explicit deferrals

- **`S8-25`** — provider finality/publication-qualification boundary
  for target-closing-data availability (§D). **Reason**: depends on
  which data provider is ultimately qualified (`OPS-005`). **Planned
  session**: none (a data-provider qualification task). **Dependency**:
  `OPS-005`.
- **`S8-26`** — dedicated holiday/early-close-spanning fall-forward and
  admission-deadline boundary test coverage (§D/§G). **Reason**: not
  located or run this session; needs its own targeted test authored
  and executed. **Planned session**: none (an implementation-
  verification task, not a knowledge-transfer session). **Dependency**:
  `S8-25`.

### Any separately authorized implementation work

**None.**

---

## Session 9 — Telegram and Dashboard Experience

**Not yet conducted.** Scope preserved exactly as already established
in `KNOWLEDGE_TRANSFER_PLAN.md` — this is **not** "Account Ledgers &
Risk"; that topic belongs to the already-scheduled **Session 10
("Paper accounting, costs and risk")**, where this session's own
account-ledger/risk carry-forward items are recorded instead (see
below). Session 9 already carries forward, from prior sessions:
`S5-30` (pre-market lockout window), `S6-13`/`S6-14` (capacity-
independent alerts, expiry-update UI), `S6-11` (four-category
diagnostic surfacing), `S7-23`/`S7-24` (five-dimension coverage
surfacing), and `S7-20`'s per-stock mute UI.

**Carried forward to Session 10 ("Paper accounting, costs and risk")
from this session's discussion**:
- Separate strategy/execution-mode accounts (`S3-13`, V2's own account
  behavior detailed by `S8-12`-`S8-14`).
- Cash versus reservations versus invested capital (`S8-12`'s
  no-anticipated-proceeds-credit rule).
- New-campaign capital defaults and costs (`S3-12`, unchanged).
- Same-stock exposure across strategies (`S3-25`, still deferred).
- Corrections, deposits, and return attribution (`S2-11`, `S7-14`,
  `S8-11`'s versioned-correction discipline).
- Account blocks and auditable release (`S8-13`/`OPS-012`).
- Combined portfolio views without double-counting experimental
  capital (`S3-13`).

Session 9 is not conducted by this task; nothing above is resolved
here — this list only ensures both Session 9 and Session 10, when each
happens, has visible pointers to the relevant open threads rather than
starting cold.
