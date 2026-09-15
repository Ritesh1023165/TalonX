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

## Session 2 — Investment Basics Through a Paper-Trade Example

**Not yet conducted.** Placeholder per `KNOWLEDGE_TRANSFER_PLAN.md`.
