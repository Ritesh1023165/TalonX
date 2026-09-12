Saved verbatim (condensed), as received. Single-turn request.

---

TASK121 — EXPERIMENTAL EXACT-CONTRACT ECONOMIC EVALUATION

OBJECTIVE
Evaluate the existing EXPERIMENTAL_RELAXED_V1 contract once, without
tuning, using available historical data and existing replay
infrastructure. Answer whether this faster-frequency lane merits further
validation for the configured-ticker product. Correct the remaining
Task120 accounting labels within this task; do not launch another V2
research cycle. Complete the replay and economic decision where inputs
permit. Do not stop at a framework proposal or inventory.

BASELINE — VERIFY: release `research/talonx-strategy-validation` @
`f28986999eec5e313cfc89db24e4dbacfb378891`; research
`research/talonx-profitability-2026-09` @ `47530ce`. September 11
production session closed; preserve production databases, SPCX's
outstanding position, Redis and config. Read
TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md, task120b_chronological_baseline.py,
Task93 dataset/harness, current Experimental runtime/paper engine/config,
existing rejection inventory and task journal. Verify actual HEADs; do not
reset unrelated work.

BOUNDARIES: research-only, isolated worktree; no application launch,
production DB/config write, or Redis mutation; no external
messages/broker/paid data/new AI integration; no live strategy changes,
scope expansion, or Experimental promotion; no parameter grid/new signal
family/post-hoc loser removal; dashboard work closed; commit/push research
normally, no main merge/force-push.

PART 1 — close the small Task120 corrections: remove unsupported
"properly powered" wording; reconcile gross vs. cost-adjusted ending
equity (publish starting capital + gross realized P&L − explicit research
cost adjustment = cost-adjusted ending equity, verify the exact
57 × $10,000 × 0.002 = $1,140 notional, do not describe $296,307.36 as
cost-adjusted, do not charge costs twice); append corrections to prior
reports/journal; keep bounded, do not rerun the full V2 baseline unless
necessary.

PART 2 — short harness check and frozen protocol: determine whether
Task93's existing harness can execute the actual Experimental contract
with a narrow adapter (do not assume replacing three thresholds makes it
equivalent); record the actual contract from source (triggers/gates,
warmup/HTF, session/blackout/timezone, ordering/throttle/cooldown/dedup,
entry price/timing/spread, stop/target precedence/gap handling,
holding/session-exit behavior, sizing/capital/re-entry, exit evaluation
independent of entry filters, data freshness/missing-data handling);
specifically verify whether Experimental is genuinely intraday or permits
overnight positions (do not add EOD flattening merely to fit the intended
label); pin source revisions/static universe manifest; use the configured
Experimental scope, report which configured symbols have historical
coverage; reference the current REPAIRED Experimental runtime, not the
earlier version whose exits were never invoked; save a short protocol
BEFORE looking at new outcomes (window/universe, data sources/adjustment,
execution/cost assumptions, primary metrics/uncertainty method, limited
predeclared sensitivity checks, advance/reject/inconclusive
interpretation, data already-inspected vs. genuinely unused); no
retrospective claim of preregistration or untouched holdout.

PART 3 — build only the necessary replay adapter: prefer the actual
scanner and Experimental paper lifecycle through an isolated deterministic
harness; if Task93 used reconstructed research logic, demonstrate
equivalence on representative event traces, reuse production functions
where practical, list unresolved differences, do not label the full
result EXACT_CONTRACT if material behavior differs; freeze clocks/event
order, replace live networking with recorded inputs/intercepted
transport, isolated stores, no production paths; demonstrate: valid
entry, stop/target exit, exit evaluation despite entry-gate rejection,
gap/stale/missing-data behavior, duplicate-event/restart protection,
position/cash reconciliation, zero external sends; do not build a new
general research platform; if essential behavior can't be represented,
complete supported work and name the exact blocker, no invented parity.

PART 4 — data/execution validity: existing historical data first; verify
per-symbol coverage/listing boundaries, timestamp tz/bar meaning,
ordered/unique bars, price-adjustment compatibility, sufficient
pre-roll/terminal coverage, historical universe limitations; no fabricated
bars; missing configured symbols stay explicit; a completed bar's
indicators must not fill at a pre-decision price; for stop/target, follow
the actual runtime observation model, do not use intrabar highs/lows as
executable evidence if production samples differently, report the
limitation and use a predeclared conservative sensitivity where valid;
separate (A) production-policy simulation from (B) execution-realism
sensitivity; no silent strategy modification while claiming baseline
parity.

PART 5 — run one frozen baseline: complete population, not selected
winners; capture evaluated opportunities/gate dispositions,
published/eligible candidates, entries/exits, position/capital
rejections, open/unresolved at end, missing-data exclusions; no invented
prices for unresolved positions; publish an attributable trade table
(symbol, decision/processing times, entry/exit event+prices, quantity,
stop/target, exit reason, holding duration, gross P&L, embedded spread,
other cost adjustments, net P&L); no double-deducted spread; no invented
gross-vs-spread decomposition if unadjusted prices weren't retained.

PART 6 — economic results: closed trades/distinct issuers/independent
time groups, trades per session/month and zero-trade periods, win
rate/avg win-loss/net expectancy, profit factor, net dollar P&L, daily
marked equity/drawdown where data permits, exposure/concurrency/overnight
holdings, issuer/time concentration, costs/unresolved execution
assumptions; equity = cash + marked open-position value, never
cash-path/cumulative-return-sum; dependence-aware uncertainty for
available groups; report issuer/time sensitivity where predeclared; a CI
excluding zero alone is not sufficient for promotion; do not
threshold-search after losses, remove losers, cherry-pick cost
assumptions, present small-N as adequately powered from count alone, or
pool the four recovery-affected live exits into this historical test.

PART 7 — one economic decision: ADVANCE_TO_FURTHER_VALIDATION (only if
net result/coverage/execution/concentration/uncertainty collectively
justify the next step — no live promotion/Telegram authorization implied)
/ REJECT_CURRENT_CONTRACT_FOR_PRODUCT_USE (negative evidence or frequency
can't serve the use case — distinguish negative economics from
insufficient frequency and from missing evidence) /
INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER (exact missing information +
smallest resolving action, not a generic deferral); explain how the
result advances the configured-ticker product; if the contract fails,
keep it as a research baseline rather than re-tuning without new
rationale; ONE next action with acceptance criteria; no dashboard work,
no return to descriptive V2 composition analysis.

PART 8 — journal/publication/stopping rule: TASK121 journal entry (exact
prompt/final response, starting/final SHAs, frozen protocol and
runtime/data manifest, harness-equivalence evidence, corrections/results/
limitations, product decision/next action, production-preservation
checks); commit sanitized adapter/reproducing script + focused tests,
protocol, coverage/trade tables, equity/metric summaries,
TASK121_EXPERIMENTAL_CONTRACT_RESULTS.md, Task120 accounting corrections;
secrets/production DBs/bulk datasets stay outside git; push normally on
research branch; stop after the baseline and decision are published, do
not automatically run another strategy variation or start production.

FINAL RESPONSE (required, 10-point): 1. Verdict and starting/final SHAs.
2. Task120 gross/net accounting corrections. 3. Experimental contract and
harness-equivalence result. 4. Universe/window coverage and excluded
data. 5. Trade frequency, net economics, drawdown and uncertainty. 6.
Execution/cost/concentration limitations. 7. Advance/reject/inconclusive
decision and why. 8. ONE next action with acceptance criteria. 9.
Production/Redis preservation. 10. Journal, report and commit links. "A
well-supported negative result closes a question. A passing test suite
does not establish a trading edge."
