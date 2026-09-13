Saved verbatim (condensed), as received. Single-turn request.

---

TASK121B — FIXED EXTENDED EXPERIMENTAL REPLAY AND ECONOMIC DECISION

OBJECTIVE
Run the remaining predefined Segment A under the repaired Experimental
contract and reach a decision about further validation. First close the
current portfolio-accounting and replay-reliability gaps. Do not change
strategy thresholds or extend the dataset until significance appears.
This is one fixed evaluation, not an optimisation campaign.

BASELINE — VERIFY: release `research/talonx-strategy-validation` @
`f28986999eec5e313cfc89db24e4dbacfb378891`; research
`research/talonx-profitability-2026-09` @ `2239b21`. Read
TASK121A_PROVENANCE_AND_CONTRACT.md, TASK121A_CORRECTED_REPLAY_RESULTS.md,
current adapter/shim, source manifest/tests/salvaged ledger, Segment A
manifest, task journal. Last result: 2025-01-24->2025-02-23, 375,628
bars, 35 symbols, N=33, 18 issuers, net +$61.92, PF 1.13, win rate 21.2%,
issuer-block CI [-$12.36,+$16.88]/trade. Open-position/equity
completeness must be verified. Funnel telemetry was lost after the
summary process hung. Do not confuse the historical validation universe
with the complete current configured watchlist.

BOUNDARIES: research-only, production stopped; no production DB/config
write, Redis mutation, external sends; preserve SPCX/live ledger
obligations; no paid data/broker/new signal family/parameter search; no
dashboard/release/promotion; commit/push normally, no main merge/
force-push; do not overwrite unrelated work.

PART 1 — RECONCILE THE FIRST MONTH'S COMPLETE PORTFOLIO: read the
salvaged ledger consistently. Report starting capital, entries/closed
round trips, remaining open positions/quantities, realized P&L/embedded
spread, cash, marked open-position value/unrealized P&L, ending equity,
unresolved valuations. Equity = cash + marked open value. Do not equate
+$61.92 with total portfolio profit unless verified. Use marks available
at cutoff with timestamps/adjustment basis, no forced terminal
liquidation/invented prices, flag outstanding positions. Verify
holding-period distribution, overnight/weekend exposure, avg win/loss,
largest winners/losers, concentration. Preserve the earlier result,
append corrections if needed.

PART 2 — MAKE THE EXISTING REPLAY RELIABLE: confirm the actual cause of
the hang and VERIFY the fix -- do not assume killing the process fixed
it. Persist signal directions/dispositions/entries/exits/exit
reasons/position transitions incrementally; record
progress/cursor/config/source hashes; bounded summary generation over
durable artifacts; verify cancellation/failure leaves readable
attributable results; ensure any supported resume preserves scanner/
throttle/cooldown/portfolio state, not only the paper ledger. Small
deterministic tests: normal replay->durable summary->clean exit;
interrupted execution + recovery; ledger/telemetry reconciliation; no
duplicate events/trades on supported resume; zero production
paths/network sends. No new general research framework. Do not claim
resumability if indicator/decision state can't be restored correctly --
use a deterministic rerun instead.

PART 3 — FREEZE THE EXTENDED PROTOCOL BEFORE OUTCOMES: verify Segment
A's exact begin/end from manifest, freeze the full remaining interval
with explicit inclusive/exclusive bounds, no results-driven date
selection. Distinguish previously-inspected first month, remaining
Segment A not yet run under this contract, earlier research exposure to
the same data -- not automatically an untouched holdout. Primary
estimand: net economics under the documented production-policy
simulation. Predeclare costs/execution assumptions, primary
metrics/uncertainty methods, one execution-realism sensitivity,
concentration/time sensitivity, a practical economic materiality
threshold justified before outcomes, fixed stopping date/decision rules.
Do not define success solely as "CI excludes zero"; do not interpret a
broad zero-spanning interval as proof of near-zero edge.

PART 4 — PRESERVE CHRONOLOGICAL CONTINUITY: continue from month 1 only
if a complete verified checkpoint exists (indicator buffers, pending
candidates, cooldowns, throttle, open positions); otherwise rerun from
the same start through the fixed Segment A end using corrected
telemetry -- do not stitch independent monthly portfolios into a
"continuous campaign." Preserve global event ordering/cross-symbol
throttle, capital/position constraints, actual entry-admission behavior,
stop/target sampled-price exits, overnight/multi-day holding policy, no
invented EOD flatten, identical parameters/static universe manifest. Do
not parallelize by symbol unless independence demonstrated; data prep
may be optimized independently; any speed improvement must preserve
decisions on a fixed parity trace.

PART 5 — EXECUTION CAUSALITY AND COST SENSITIVITY: verify signal-bar-
close pricing against actual available information at decision time.
Record bar event timestamp/completion, signal decision timestamp, price
observation used for the fill, any difference vs. a subsequently
obtainable simulated price. Primary: preserve/label the production-
policy reference simulation. Sensitivity: one predefined next-available-
price/slippage model supported by the data -- no same-bar future
info/optimistic intrabar ordering/cherry-picked cost. If the alternative
fill changes portfolio state, propagate chronologically, don't just
subtract a constant. If data can't support it, report the limitation, no
invented quotes. Spread: verify half-spread-per-side formula, avoid
double deduction, separate modeled spread from commissions/fees/other
assumptions.

PART 6 — COMPLETE THE FIXED RUN: estimate runtime from measured
throughput and actual remaining bars; realistic compute budget, don't
shrink the window again for a quick result. Run once to the
predetermined end, persist progress, report milestones; don't abandon a
healthy long run for taking hours. At dataset end: preserve open
positions, mark at valid available prices, report incomplete exit
obligations, don't exclude open losers from total performance; if using
a predeclared settle tail, prohibit new entries during it and report the
tail separately.

PART 7 — RESULTS AND DECISION: publish actual symbols/dates/bars/gaps;
per-direction candidates/publications; entries/closed/open-unresolved
positions; no-entry/exit reasons; trades per month/zero-entry periods;
holding-period distribution/overnight exposure; gross/cost/net P&L;
cash/open valuation/total equity; daily marked drawdown where supported;
avg win/loss/win rate/PF/net expectancy; issuer/time concentration;
dependence-aware uncertainty/predeclared sensitivities; first-month vs.
extension vs. continuous-campaign total. Do not pool the four recovery-
affected live exits into this study; do not assert stable monthly
frequency from one active month. Choose ONE:
ADVANCE_TO_FURTHER_VALIDATION / REJECT_CURRENT_CONTRACT_FOR_PRODUCT_USE /
INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER. Positive results must
survive credible costs/execution limitations/concentration review;
negative economics and inadequate frequency are different rejection
reasons; a zero-spanning interval is inconclusive, whether it rules out
a useful edge depends on its bounds; no automatic repeat with a larger
window until significance appears. If inconclusive, identify the exact
uncertainty and whether resolving it is worth further effort within the
existing roadmap deadline -- don't automatically propose another replay.
No live promotion/Experimental Telegram enablement.

PART 8 — JOURNAL/PUBLICATION/CLEANUP: Task121B journal entry (exact
prompt/final response, starting/final SHAs, first-month accounting
correction, reliability fix/verification, frozen protocol/runtime/data
manifest, run duration/scope/results, economic decision/ONE next
action). Commit sanitized adapter/reliability fixes + focused tests,
protocol, signal/trade/disposition summaries, equity/metric artifacts,
TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md. Keep production DBs/secrets/
bulk data outside git. Push normally. Stop task-owned subprocesses
cleanly, verify no leftovers. Leave Redis/production untouched.

FINAL RESPONSE (required, 10-point): 1. Verdict and SHAs. 2. First-month
complete portfolio reconciliation. 3. Summary-hang fix and durable
telemetry acceptance. 4. Actual extended window, continuity and runtime.
5. Signal/entry/exit accounting. 6. Net economic results, equity and
drawdown. 7. Execution sensitivity and uncertainty. 8. Product decision
and ONE next action. 9. Remaining limitations and production
preservation. 10. Journal, reports and commit links. "Priority: reliable
fixed run -> complete portfolio economics -> decision."
