# TalonX Product Knowledge-Transfer Plan

## Why this exists

The product owner has become out of sync with the evolving application.
TalonX has grown across many independently-executed tasks (see
`docs/research/TALONX_RESEARCH_LEDGER.md`); this plan is a structured,
session-by-session return to first principles — assuming little
investment knowledge — **before** authorizing further product
development. This is a discussion/documentation track, not an
implementation track: nothing in these sessions changes runtime
behavior by itself (see §6, Tracking future changes).

## Discussion format (every session)

1. **Plain-language explanation and a concrete example.** No unexplained
   jargon; a real, worked example wherever possible (a real historical
   message, a real trade, a real dashboard screen).
2. **Current implementation, supported by code/evidence.** What the
   system actually does today, cited to a file/line or a real
   production trace — never asserted from memory alone.
3. **Interactive questions and refinement.** The owner asks, Claude
   answers or investigates; positions get refined in the conversation
   itself.
4. **Decisions, open questions, and proposed enhancements** — recorded
   distinctly (see `DECISION_LOG.md`'s own format) at the end of the
   session.

Kept distinct throughout every session: **implemented** behavior (in the
repository, running or not), **validated** behavior (confirmed against
real evidence — code inspection, isolated test, integrated/browser test,
natural live behavior, or product-owner acceptance — see
`REQUIREMENTS_TRACKER.md`), and **proposed** behavior (discussed, not
yet agreed). **Repository HEAD and running-component versions are
separate concepts** — a change committed to the repository is not
necessarily the version currently running live; every claim in this
documentation track that matters to "what does the user experience
today" specifies which one it means.

## Session schedule

| # | Title | Status |
|---|---|---|
| 1 | Purpose and user value | **Done — recorded in `DECISION_LOG.md`** |
| 2 | Paper execution, accounting, risk and evaluation | **Decisions recorded; implementation assessment/authorization separate.** Recorded in `DECISION_LOG.md` (title updated from the originally-planned "Investment basics through a paper-trade example"; the plan is owner-adjustable — see below) |
| 3 | Application structure and configuration: Original, Intelligence and V2 | **Agreed decisions recorded (S3-01..S3-23); named deferrals remain (S3-24..S3-28).** Recorded in `DECISION_LOG.md` (title extended from "Application overview" to reflect its actual scope — master stock coverage, capital defaults, research-lab workflow, naming, and a conditional reset policy, in addition to the three flows' responsibilities). |
| 4 | End-to-end user journey | **Agreed decisions recorded (S4-01..S4-14).** Recorded in `DECISION_LOG.md`. |
| 5 | Data sources, discovery and coverage | **Closed at the requirements level (S5-01..S5-31); explicit technical decisions and implementation gates remain outstanding — not execution readiness or universal validation.** Recorded in `DECISION_LOG.md`. |
| 6 | Signal discovery and strategy mechanics | **Discussion closed; documented requirements (S6-01..S6-26), with explicit deferrals and implementation gates.** Recorded in `DECISION_LOG.md`. Resolved `S3-24` (Fundamental Opportunities = isolated Research Lab candidate) and `S5-19` (deadline-equality semantics, requirements level only) — see `REQUIREMENTS_TRACKER.md` for both dated updates. |
| 7 | Intelligence and useful company developments | **Discussion closed; agreed requirements documented (S7-01..S7-26), with numerical policy choices deferred and implementation/validation separately tracked.** Recorded in `DECISION_LOG.md`. |
| 8 | V2 multi-day strategy and lifecycle | **Discussion closed; requirements documented (S8-01..S8-18), with provider-finality and cooldown-boundary verification outstanding (S8-25/S8-26), and implementation separately tracked.** Recorded in `DECISION_LOG.md`. Much of the discussed lifecycle was found `Implemented` and directly test-confirmed this session (admission deadline, holding clock, fall-forward contract, cooldown anchor/boundary, exactly-once close); one genuine gap found (`OPS-012`, `EXIT_UNRESOLVED` account-block not enforced). |
| 9 | Telegram and dashboard experience | **Discussion closed; requirements documented (S9-01..S9-20), with implementation/validation separately tracked (OPS-013).** Recorded in `DECISION_LOG.md`. |
| 10 | Paper accounting, costs and risk | **Discussion closed; requirements documented (S10-01..S10-21), with explicit deferrals (S10-22..S10-25) and implementation/validation separately tracked (OPS-014, OPS-015).** Recorded in `DECISION_LOG.md`. Resolved `S3-25`'s display half as `Agreed` (`S10-14`); its enforcement half remains deferred, now split across `S10-23`-`S10-25`. |
| 11 | Operation, stop/start and recovery | Not yet conducted. Carries forward `S3-28` (mute controls, pending-intent handling), `S5-30` (pre-market lockout window, undefined), `OPS-007` (intraday EOD-flatten durable recovery) and `S6-22`/`S6-23`'s cross-restart persistence requirements, `OPS-012` (V2 `EXIT_UNRESOLVED` account-block enforcement) and `S8-26` (holiday/early-close boundary test coverage), and now `OPS-015` (EOD/restart reconciliation-mismatch admission block) and `S10-21`'s explicitly-assigned block-clearance authority/evidence question — see `DECISION_LOG.md` Session 11's carried-forward-ID pointer list for the full mapping (stop behavior, operating windows, per-strategy restart, pause/exclude/mute scope, incident thresholds, account-block clearance, configuration effective dates, single ownership/outage detection). |
| 12 | Technical validation, usefulness and economic evidence | Not yet conducted. Receives `S3-26` (experiment evaluation criteria/evidence sufficiency, deferred from Session 3), is a candidate destination for `S5-31`'s 2-year-replay-feasibility audit, `S6-25`/`S8-25` (numerical spread/slippage/fee assumptions), `S7-25`/`S7-26` (numerical freshness windows and event-specific materiality thresholds, each requiring a bounded historical-filing review), and now `S10-22` (numerical spread/slippage/fee assumptions, same destination) — all prerequisites for authorizing any future experiment or implementation of Sessions 6-10's approved targets. |
| 13 | Architecture, effective configuration and prioritized roadmap | Not yet conducted |

**Closure discipline** (applies from Session 3 onward): before closing
each session, every question raised in it is recorded as **agreed**,
**rejected**, or **explicitly deferred with a reason and a named
destination session** — never silently dropped. Session 3's own
deferrals (`S3-24` through `S3-28`) were the first application of this
discipline; Session 5's own deferrals (`S5-10`, `S5-19`→now resolved
at requirements level by Session 6, `S5-20`, `S5-30`, `S5-31`),
Session 6's own deferrals (`S6-18`, `S6-25`, `S6-26`), Session 7's own
deferrals (`S7-18`, `S7-25`, `S7-26`), Session 8's own deferrals
(`S8-25`, `S8-26`), and Session 10's own deferrals (`S10-22` through
`S10-25`) follow the same pattern — see `DECISION_LOG.md`
Session 3/5/6/7/8/10's "Explicit deferrals" sections. (Session 9 had
no new deferrals of its own — all of §A-F were agreed decisions.)

**This plan is adjustable by the owner** — the order, content, or
existence of any future session may change; nothing here is fixed in
advance, and no decision for a session that hasn't happened yet is
invented in this document. Session 1's own open questions (S1-09,
S1-11, and others in `REQUIREMENTS_TRACKER.md`) are natural candidates
for early follow-up but are not pre-assigned to a specific numbered
session unless the owner says so.

## §6 — How future changes are tracked

1. **Each session appends a decision record** to `DECISION_LOG.md`,
   under its own `## Session N — <title>` heading. Prior sessions'
   entries are never edited — a later session that changes an earlier
   decision adds a new, dated note under the *original* entry, with the
   newer session linking back to it.
2. **Accepted decisions update `PRODUCT_DEFINITION.md`** — the current
   product definition reflects the latest *accepted* state, always with
   a pointer to the `DECISION_LOG.md` entry that established it.
3. **Superseded decisions remain visible**, with a link to whatever
   replaced them — never silently removed.
4. **Requirements retain stable IDs** (`REQUIREMENTS_TRACKER.md`,
   `S<session>-<sequence>`) for the life of the project. An ID is never
   reused for a different requirement, even if the original requirement
   is later dropped.
5. **Development prompts cite the IDs they implement.** A future task
   that builds toward a requirement should name the `S<n>-<seq>` ID(s)
   it addresses, so the tracker and the actual commit history stay
   traceable to each other.
6. **Completion reports link IDs to code and validation evidence** — the
   same discipline this project's own task-completion evidence bundles
   already use (`docs/research/evidence/task*/`), extended to product
   requirement IDs specifically.
7. **A proposal does not authorize implementation.** `Agreed` (a
   product direction) and `Implementation authorized` (permission to
   build it) are tracked as separate steps in
   `REQUIREMENTS_TRACKER.md`'s decision-status progression
   (`Proposed → Agreed → Implementation authorized → Implemented →
   Verified`) — reaching `Agreed` does not imply the next two steps
   have also occurred.
8. **Discussion does not automatically change runtime configuration.**
   Nothing recorded in a knowledge-transfer session, by itself, restarts
   a service, flips a flag, or sends a message. A configuration change
   requires its own explicit authorization and its own task, exactly
   like any other runtime change in this project.

## End-of-session summary template

Every session's `DECISION_LOG.md` entry ends with:

- **Agreed decisions** — settled product direction.
- **Open questions** — explicitly unresolved, not defaulted.
- **Differences from current behavior** — where the agreed direction
  and the actual, evidenced current implementation diverge.
- **Proposed enhancements** — discussed, not agreed as requirements.
- **Any separately authorized implementation work** — named
  explicitly, or "None" if no implementation was authorized (the
  expected outcome for a pure discussion session).

---

*See `PRODUCT_DEFINITION.md` for the current accepted product
definition, `DECISION_LOG.md` for the full session-by-session record,
and `REQUIREMENTS_TRACKER.md` for the authoritative per-requirement
status table.*
