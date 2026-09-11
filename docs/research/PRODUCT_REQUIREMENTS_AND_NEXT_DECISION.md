# Product requirements vs. current capability, and the next decision (2026-09-11)

## Requirement-to-capability table

| requirement | current serving lane | demonstrated behavior | economic evidence | gap | next deliverable |
|---|---|---|---|---|---|
| Intraday alerts, short horizon | Original | Selective by design — `LOW_VOLATILITY` ≥99.8% of gate rejections (Task 118/118B, unit-trace confirmed correct); readiness now repaired (43/43, Task 118F) | 9 free-data alpha spaces closed (Task 93–97/106A) — no edge found at any tested horizon/regime | selectivity is confirmed intentional, not a bug; 0 published signals today is consistent with the closed research, not new evidence of anything | **none proposed** — re-testing an already-closed space needs a new hypothesis, which does not exist here |
| Medium/long-horizon insider-cluster signals | V2 | Working, frozen contract, rare on the live 39-name scope (10 trades/19mo) | A (39-scope): −2.93%, inconclusive (CI includes zero). B (587-name, matched runtime): +2.15%, CI excludes zero (credible positive) | why the 39-scope differs from the broader panel is only descriptively, not causally, explained (Task 118E/F: pre-entry volatility, MSTR-dependent) | live volatility tracking already in progress (Task 118E/F protocol) — continues, but is explicitly **not** the sole programme per this task's own instruction |
| Informational Telegram delivery | Intelligence | Working correctly post-fix (6 cards → 1 digest message today; literal-markup/wording bugs fixed Task 118A) | N/A by design — descriptive only, never a trading recommendation | none against its own stated scope | none needed |
| Attributable local paper portfolios | Original / V2 / Experimental (3 separate ledgers) | All three independently reconciled at every EOD this session, `mismatches: []` at canonical close | Experimental: −$324.47 realized, **4/4 first-ever exits today** (Task 118A fix); V2: $0 (0 trades); Original: $0 (0 trades) | Experimental's exit mechanism was proven live for the first time only today — its economics are **not yet established** at N=4, all recovery-affected; results exist per-lane in raw ledger data but are **not surfaced together, clearly labelled, in one place** | see selected task below |
| Positive aggregate economics | — | — | **Not established for any live-scope lane yet** — this is the honest, current state, not softened | the core, unresolved product gap | requires more live cycles across every lane; no single deliverable closes this today |

## Three candidate next-work options considered

### Option 1 — extend volatility-conditioned tracking to Experimental
- **Requirement advanced**: medium-horizon economic evidence (indirectly;
  Experimental is a different, faster-cadence lane than V2).
- **Already implemented**: the tracking protocol itself (Task 118F).
- **Remaining uncertainty**: whether it holds for Experimental's own,
  much higher-frequency signal generation (5 entries in 2 days vs. V2's
  10 in 19 months).
- **Data/runtime**: exists (same `experimental_paper.db` ledger).
- **Deliverable**: a parallel live-tracking table.
- **Not a repeat of rejected research**: distinct signal source (Original/
  Experimental's relaxed intraday gates, not V2's insider-cluster rule).
- **Effort (estimate)**: small — reuses existing patterns directly.
- **Weakness**: still fundamentally "wait for more data," and — like V2's
  own tracking — cannot by itself demonstrate positive aggregate
  economics for a long time; does not produce a usable capability today.

### Option 2 — a bounded, one-hypothesis re-examination of Original's LOW_VOLATILITY threshold's economic cost
- **Requirement advanced**: intraday alerts.
- **Already implemented**: the gate itself, fully traced and confirmed
  correct (Task 118/118B).
- **Remaining uncertainty**: none identified that a new analysis would
  resolve — Task 95A already measured intraday drift (~5bps) against cost
  (~5bps) at 25.8M-bar scale, the definitive version of this exact
  question.
- **Not a repeat of rejected research**: it **is** essentially a repeat —
  rejected on evidentiary grounds.
- **Effort**: n/a — **not selected**, matches this task's own explicit
  instruction not to repeat closed research or claim a hidden opportunity
  without candidate/price evidence.

### Option 3 — an attributable, per-lane paper-performance reconciliation surface (chosen)
- **Requirement advanced**: directly serves **two** explicit stated
  requirements — "attributable local paper portfolios" and "Dashboard
  and paper results must remain attributable by lane."
- **Already implemented**: every underlying number already exists,
  independently reconciled, in the canonical EOD report and each lane's
  own ledger (`eod.json.base_reconciliation`, `experimental_paper.db`,
  `v2_lane.db`, `dispatch_audit.db`) — confirmed today's `mismatches: []`.
- **Remaining uncertainty**: none about the data's correctness — the gap
  is **presentation**, not evidence: the three lanes' realized/unrealized
  P&L, trade counts, and recovery-affected flags are not currently shown
  together, consistently labelled, in one place an operator (or this
  task series) could read without re-deriving them by hand each time
  (as every Task 118 report has had to do).
- **Data/runtime**: 100% already available; no new data acquisition, no
  new provider call, no strategy change.
- **Deliverable**: one read-only dashboard section (or a documented,
  scripted reconciliation report, whichever is smaller) showing, per
  lane: realized P&L (campaign-to-date and today), open positions with
  timestamped unrealized P&L, trade counts (today vs. all-time), and an
  explicit "recovery-affected" flag on any trade whose lifecycle was
  fixed this session — reusing existing read-only accessors
  (`dashboard_read.py`'s existing per-section pattern), **no new
  provider, no threshold change, no promotion logic**.
- **Acceptance criteria**: (a) all three lanes' figures agree exactly
  with the canonical EOD's own numbers for the same date; (b) recovery-
  affected trades are visibly flagged, not silently pooled; (c) SPCX-style
  open positions show a timestamped mark and an explicit staleness label,
  never a fabricated "0" when unknown; (d) no strategy/threshold/scope
  value is read from or written to by this surface.
- **Not a repeat of rejected research**: this is a **product/reporting**
  deliverable, not a new alpha search — it does not compete with, and is
  not subject to, the closed-research history at all.
- **Effort (estimate)**: small-to-medium — a bounded, testable, read-only
  addition to an already-existing dashboard/reporting layer.

## Selected: Option 3

**Chosen because it is the only one of the three that produces a usable
capability rather than another open-ended report or a repeat of an
already-tested/already-rejected question**, uses zero new data, and
directly advances two requirements stated verbatim in this task's own
objective. **This document specifies it; it is not implemented in this
task** (per this task's own scope: EOD closure and roadmap decision, not
new engineering under time pressure) — it is the acceptance-criteria-
bearing task recommended for the next focused session/follow-up, not
launched automatically here.

## Explicitly not done

No watchlist expansion. No threshold relaxation. No removal of MSTR or
any other name. No Experimental promotion. No new paid data, AI
integration, or broker dependency. No win-rate target asserted. If no
evidence-backed strategy change existed, that is stated plainly above —
it does not, and none is proposed.
