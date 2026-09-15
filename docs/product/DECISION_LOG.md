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

## Session 3 — Application Overview: Original, Intelligence and V2

**Not yet conducted.** Per `KNOWLEDGE_TRANSFER_PLAN.md`, this session
already covers "Original, Intelligence and V2" as its topic. The
following discussion items are added to its agenda from this
documentation pass (raised by gaps and open questions surfaced during
Session 2's recording, not answered here):

- The respective responsibilities of Original, Intelligence and V2 —
  a single clear statement of what each of the three flows is for.
- Whether Original's reported intraday and long-term accounts
  represent distinct active strategies, dormant paths, or accounting
  containers only — not inferred from the account labels alone.
- How signal qualification differs from paper-portfolio admission
  today, concretely (Session 2 requirement B's distinction, not yet
  verified against the actual current code paths).
- Which price source each flow actually uses today, and each source's
  current coverage/freshness (directly motivated by the V2
  pricing-freshness finding — see `OPERATIONAL_FINDINGS.md` `OPS-002`).
- Where the existing implementation differs from the Session 1–2
  decisions recorded so far — a consolidated gap list, not a new
  round of decisions.

Product scope must not be inferred from account labels alone — this is
an explicit instruction carried into Session 3, not a decision made in
this pass.
