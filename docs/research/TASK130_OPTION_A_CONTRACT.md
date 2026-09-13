# Task 130 — Option A: four-tier product contract

Explicit, bounded resumption of Task 129's paused programme, per the
user's own Option A selection — broader V2 discovery while preserving
the configured watchlist. Research-only; no production integration or
activation in this task.

## Tier 1 — configured watchlist (unchanged, verified live)

Resolved from `talonx_ops.watchlist_coverage.build_coverage_map()`
directly, 2026-09-13:

| population | count |
|---|---:|
| Configured | **48** |
| Active | **43** |
| SEC-resolved (`v2_collection_scope == "POLLED"`) | **39** |

These are three **distinct populations**, not interchangeable
invariants: "configured" is every ticker in the product's watchlist
config; "active" is the subset not paused; "SEC-resolved" is the
subset `talonx_v2/run.py --execution-scope resolved-active-watchlist`
actually resolves to an allowed-issuer list for V2 execution (the 39
names verified identical to Task 118D's own `THE_39` list). The
48/43/39 snapshot matches every prior task's count this session —
unchanged, re-verified, not assumed.

## Tier 2 — discovery universe (versioned, evidence-anchored)

**Discovery Universe v1** = the union of the Task 118D matched-runtime
"Population C" (626 issuer-symbols) — itself `(Task 116's 620-name
panel) ∪ (Tier 1's 39 SEC-resolved names)`, re-run under the
post-Task-117 runtime (execution-allowlist enforcement + F3
dissemination-slack fix) that Task 116's own original run predates.
**Reused directly from
`results/task118_profitability/reconciliation/population_manifest.json`
— not reconstructed from scratch, and not substituted with "all US
equities," Russell 3000, or S&P 1500**, none of which has been shown
equivalent to this program's actual researched population. Exact
counts, re-verified this task: A (Tier 1's 39) ⊂ C (626) ⊇ B (587, C
minus A). See §Universe manifest below for the full versioned
artifact.

**No market-cap threshold is invented anywhere in this contract** —
eligibility is the liquidity gate (Tier 2/3 below), not a market-cap
screen.

## Tier 3 — alert subscription

Two independent subscription states, orthogonal to Tier 4's paper
execution:

- `WATCHLIST_ONLY` — alerts scoped to Tier 1's 39 SEC-resolved names
  (today's production default).
- `BROAD_DISCOVERY` — alerts scoped to Tier 2's 626-name Discovery
  Universe v1.

**Subscription changes must not, by themselves, create paper
positions, alter economic eligibility, or disable an existing
position's exit management** — subscription is a notification-routing
concern only. This task does not implement either subscription mode
(no dashboard/Telegram change, per this task's own authorization
limits); it is specified here as the Tier 3 contract for a later
integration task to implement, contingent on Part 8's decision below.

## Tier 4 — paper execution (this task's actual subject)

The **explicitly approved discovery population** for PAPER execution
(not merely alerting) — this task evaluates whether Discovery Universe
v1, under a real capacity-constrained, prospective-only paper campaign,
is economically justified. Tier 4 carries its own:

- **Universe version**: `discovery_universe_v1` (Tier 2, 626 names,
  frozen this task).
- **Prospective execution-policy version**: `v2_prospective_policy_v2`
  (this task's stricter intent-gated policy — see §3 below; distinct
  from and a documented supersession of the production runtime's
  current cold-start-permitting behavior, `v2_prospective_policy_v1`).
- **Architecture**: the existing isolated V2 campaign architecture
  (`talonx_v2.service.V2Service` driven by
  `talonx_research.replay_engine.run_chronological_replay`, an isolated
  research SQLite ledger — never the live `v2_lane.db`).

**Scope-change / existing-position rule**: if an issuer leaves the
entry-eligible universe (e.g., a Discovery Universe v1 name is dropped
from a later universe version, or fails the liquidity gate on a later
tick), **any already-open position in that issuer is still managed to
its existing exit rule** — universe membership governs NEW entries
only, never forces or blocks the exit of an already-open position. This
is enforced by construction in the existing runtime (`settle_due_exits`
operates on open positions independent of the execution allowlist —
verified by direct code read this task, `talonx_v2/service.py`: the
execution allowlist is applied only at the `records`/`episodes` stages,
never inside `settle_due_exits`).
