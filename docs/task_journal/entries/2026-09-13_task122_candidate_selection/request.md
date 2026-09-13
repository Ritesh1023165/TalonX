Saved verbatim (condensed), as received. Single-turn request.

---

TASK122 — CLOSE EXPERIMENTAL EVALUATION AND SELECT ONE NEW CANDIDATE

OBJECTIVE
Stop the repeated evaluation of EXPERIMENTAL_RELAXED_V1. Select at most
ONE materially different, evidence-backed candidate that could serve the
configured-ticker product, and complete its bounded feasibility check.
Must end with a concrete candidate evaluation plan or an explicit
NO_FEASIBLE_CANDIDATE decision. Do not invent a strategy to satisfy the
task. Do not launch another long replay or broad parameter search.

BASELINE — VERIFY: release `research/talonx-strategy-validation` @
`f28986999eec5e313cfc89db24e4dbacfb378891`; research
`research/talonx-profitability-2026-09` @ `3e6cd9e`. Read
TASK121B_EXTENDED_PROTOCOL.md, TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md,
PRODUCT_STATUS.md and configured-ticker manifest, research rejection
inventory/underlying evidence, task journal/roadmap. Verify actual state,
preserve unrelated work.

BOUNDARIES: research-only, no production app launch/release deployment,
no production ledger/config write or Redis mutation, preserve
SPCX/obligations, no external messages/broker/shorts/paid data,
Experimental external delivery stays OFF, no live scope/threshold/
sizing/holding-rule changes, no dashboard/general-platform rewrite,
normal research commit/push only.

PART 1 — CLOSE TASK121B WITHOUT ANOTHER REPLAY: record separate
verdicts (statistical: INSUFFICIENT_EVIDENCE under the original
predeclared rule; product: DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT).
Explain negative gross/net results, adequate activity but no edge, the
+$1.06 upper CI bound below the +$1.25 threshold conditional on the
estimator, and that failing the formal negative-rejection rule doesn't
justify promotion or repeat investigation. Preserve the original
protocol's decision rule unchanged. Correct two reporting limits: (1)
call the delayed-entry result a repricing sensitivity unless source
evidence proves full chronological propagation; (2) state daily marked
drawdown was not supplied -- ending equity is not drawdown. No 11-hour
rerun required. Archive the unchanged Experimental contract as an
internal research baseline; don't touch production components.

PART 2 — DEFINE WHAT A REPLACEMENT MUST ACHIEVE: product requirement =
configured tickers by horizon -> alerts -> attributable paper
portfolios -> measurable economics after costs. V2 stays sparse
supplementary; Intelligence stays informational; neither is evidence the
trading objective is achieved. Write a short candidate contract:
horizon/user action, long-only entry + explicit exit, information
available before the decision, expected opportunity frequency on the
configured universe, data/execution requirements, costs/materiality,
falsification. Don't invent a trades-per-day quota; report estimated
frequency and whether it materially improves on current sparse output.
A changed threshold/removed loser/extra indicator/favorable subperiod is
not automatically materially different.

PART 3 — SHORTLIST AT MOST THREE HYPOTHESES: use existing
datasets/research/primary literature. For each: mechanism, why it could
apply to configured tickers, signal availability/timing, holding/exit
logic, existing data coverage/missing inputs, closest prior TalonX
experiment, exact substantive difference, main failure reason, estimated
effort. Cite actual papers/authoritative docs with universe/period/
assumptions -- published success doesn't establish TalonX performance.
Do not: treat an opposite historical sign as automatic inverted-strategy
evidence, reopen a rejected family under a new name, declare all
free-data hypotheses exhausted without evidence, expand the production
universe to improve historical results, add AI/ML without a specific
justified information advantage. Fewer than 3 is fine; don't pad.

PART 4 — EXISTING-DATA FEASIBILITY CHECK: before inspecting candidate
returns, rank by mechanism plausibility/data availability/runtime
complexity/frequency/overlap with rejected work. For the top-ranked
candidate: static universe mapping, historical field availability/
timestamps, point-in-time usability/revision/lookahead risk, price/
volume coverage at required resolution, event/setup counts by month and
ticker WITHOUT choosing dates by profitable outcomes, corporate-action/
listing-boundary handling, realistic decision-to-entry timing. Existing
data first; small bounded retrievals via existing free access permitted,
no bulk acquisition/new provider integration. No return-based ranking of
many candidates then describing the winner as preselected. If the first
candidate fails feasibility, consider the next ranked one; stop after the
shortlist is exhausted.

PART 5 — SELECT ONE CANDIDATE OR STOP: return
ONE_CANDIDATE_READY_FOR_FIXED_EVALUATION or
NO_FEASIBLE_CANDIDATE_UNDER_CURRENT_CONSTRAINTS (with exact limiting
constraint + smallest enabling change, no unauthorized data purchase/
scope change). "Needs more research" alone is not acceptable. For a
selected candidate, produce a fixed evaluation protocol: universe/
window, already-inspected vs. genuinely unused data, exact signal/entry/
exit, cost/execution assumptions, benchmark/control, portfolio/
concurrency constraints, primary metric + dependence-aware uncertainty,
limited predefined sensitivities, practical acceptance/rejection
criteria, missing-data/terminal-position treatment, fixed stopping rule.
If no untouched data exists, label exploratory + specify a separate
confirmation requirement. No parameter grid, no automatic larger-window
sequence, no promotion from a favorable development result.

PART 6 — MAKE THE NEXT TASK EXECUTABLE: identify reusable production/
research functions + exact revisions, minimal adapter work, a small
causal event trace needed before a historical run, estimated bar/event
count and runtime from measured infrastructure, whether profiling is
necessary, output artifacts and the exact economic decision the run will
make. Don't build another general replay engine; don't start the full
evaluation this task. One credible executable experiment, not a vague
roadmap or fabricated "new edge."

PART 7 — JOURNAL/PUBLICATION/STOPPING RULE: Task122 journal entry (exact
prompt/final response, starting/final SHAs, Task121B closure + reporting
corrections, shortlist/selection rationale, source/data feasibility
evidence, selected protocol or no-feasible-candidate decision, ONE next
action + acceptance criteria, production-preservation checks). Update
PRODUCT_STATUS.md and the research ledger concisely, keeping previous
conclusions with dated corrections. Commit sanitized
TASK122_CANDIDATE_DECISION.md, feasibility table/manifest, fixed
evaluation protocol (if qualifying), small reproducing feasibility
script, Task121B reporting corrections. No secrets/production DBs/bulk
datasets in git. Push normally. Stop once the candidate decision and
executable next step are published -- don't auto-start Task123, a full
replay, deployment, or live session.

FINAL RESPONSE (required, 10-point): 1. Task121B statistical verdict +
product DO_NOT_ADVANCE decision. 2. Starting/final SHAs and push result.
3. Shortlist, including why prior rejected work is not being repeated.
4. Selected candidate or NO_FEASIBLE_CANDIDATE. 5. Existing-data
feasibility and estimated opportunity frequency. 6. Execution/cost and
historical-data limitations. 7. Fixed next evaluation and estimated
runtime. 8. ONE next action. 9. Production preservation. 10. Journal,
protocol, primary sources and commit links. "A credible decision to stop
is preferable to another unsupported candidate. The objective remains
profitable alerts, not simply more alerts."
