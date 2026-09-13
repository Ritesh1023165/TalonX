# Request

Verbatim user request (2026-09-13), immediately following Task 128's
baseline product decision:

> TASK129 — RESEARCH PROGRAM DECISION AND BOUNDED PATH TO THE PRODUCT
> GOAL
>
> OBJECTIVE
> Decide whether TalonX has a justified next profitability experiment
> or whether the current research programme should pause.
>
> Use existing evidence to make that decision. Do not run another
> backtest, invent another shortlist merely to keep work moving, or
> begin application improvements.
>
> Deliver one concise decision document, an evidence matrix, and the
> required journal entry. Avoid another large documentation project.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: 8f9dfc0b88d87730dc1f9c2649910d335ef8aa12
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual state and preserve unrelated changes.
>
> Research-only task. No production launches, external messages,
> broker calls, paid data, new downloads, configuration changes, or
> release merges. Preserve ledgers, Redis, and SPCX obligations.
>
> 1. RESTATE THE ACTUAL PRODUCT REQUIREMENTS — configured tickers;
>    intraday and short/long-term opportunities; understandable
>    bullish/bearish/BUY/SELL alerts; local paper portfolios and
>    dashboard; long-only execution, SELL closes an existing long;
>    positive aggregate economics is the goal, no guaranteed return/win
>    rate; existing free data/infrastructure; alerts and paper
>    execution outcomes remain separate. Do not introduce unsupported
>    requirements (every ticker alerts; every session trades; every
>    signal differs per ticker; long-term holdings prohibited; complex
>    beats simple by default). Separate delivered-operationally from
>    economically-still-unsupported.
>
> 2. CONSOLIDATE THE EXISTING EVIDENCE — read the research ledger,
>    prior-rejection history, current product status, authoritative
>    final reports; follow corrections to their latest supported
>    conclusions. Start with the index; inspect underlying code/
>    artifacts only where material ambiguity could change this task's
>    decision — do not read every repository file indiscriminately.
>    One row per distinct mechanism, grouping repeated tasks. Include
>    mechanism/contract, product horizon, universe/period, runtime/
>    data fidelity, costs/execution, result/uncertainty, bias/missing
>    evidence, product verdict, authoritative report/commit, what new
>    information could change the decision. Cover the earlier rejected
>    families plus Original intraday, Experimental relaxed contract,
>    V2 configured scope vs. broader populations, overnight-attention,
>    52-week-high selection, no-selection long-term benchmark. Do not
>    equate "not evaluated," "inconclusive," "negative estimate," and
>    "economically rejected." Do not transfer broader-universe V2
>    results to the configured live scope.
>
> 3. IDENTIFY WHY THE PROGRAMME HAS TAKEN SO LONG — use concrete
>    repository evidence to distinguish real integration defects,
>    stale-worktree/runtime-parity errors, accounting/reporting
>    corrections, repeated use of already-examined data, data
>    limitations assumed before checking existing access, product
>    restrictions inferred without user support, research that
>    answered a decision vs. work that merely generated another task.
>    At most five major causes, each with one lightweight prevention
>    rule reusing existing mechanisms. No new governance platform, test
>    suite rewrite, or broad documentation cleanup.
>
> 4. ASSESS WHETHER A NEXT EXPERIMENT IS JUSTIFIED — qualifies only if
>    it addresses an economically distinct unresolved question; is not
>    a parameter variation of a rejected contract; existing evidence
>    gives a credible mechanism or concrete unresolved finding;
>    available data can answer it with defensible timing/accounting;
>    its result would change a specific product decision; cost/
>    completion criteria are bounded. Look first for genuinely
>    unresolved questions in existing evidence — no broad literature
>    search, no new candidate merely because the shortlist is empty. If
>    a proposed experiment depends on a source claim, verify it from
>    the primary source, narrowly targeted. Do not claim "all
>    strategies fail" or "all free-data research is exhausted" — state
>    only what this repository's evidence supports.
>
> 5. MAKE ONE PROGRAMME DECISION — A. ONE_FINAL_BOUNDED_EXPERIMENT_JUSTIFIED
>    (name exactly one, with question/why-not-already-answered/new-
>    information/product-decisions-changed/data-and-computation/effort-
>    and-runtime/frozen-acceptance/stop-conditions — not executed this
>    task); B. PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS (what
>    remains usable, what profitability claims remain unsupported,
>    which specific constraint/evidence change could justify resuming,
>    what work stops immediately — no indefinite live observation or
>    generic shortlist as a substitute); C. SPECIFIC_USER_DECISION_REQUIRED
>    (only for a genuinely unresolved user choice that materially
>    changes the viable programme — one concrete choice, consequences,
>    a grounded recommendation, not reconfirming stated requirements).
>
> 6. SET A FINITE REMAINING BUDGET — at most one new evaluation; at
>    most two working days of active research effort unless measured
>    computation requires a disclosed extension; no tuning after
>    results; no automatic follow-on after an inconclusive result. A
>    proposed future budget, not authorization to spend it now. Retain
>    the original decision-roadmap start date if documented — do not
>    reset the clock after each correction or claim a profitability
>    deadline. Define the stop condition in advance.
>
> 7. PRODUCE A PRACTICAL PRODUCT ROADMAP — three rows (Now / Next
>    authorised action / Decision afterward), each with deliverable,
>    completion gate, what the user actually gains. Keep intraday and
>    long-term economic status separate. Do not promise another session
>    will generate trades or another study will find an edge. No
>    deployment recommendation may rely only on a passing test suite,
>    increased alert count, or positive historical returns without
>    their limitations.
>
> 8. CLOSE REPORTING LOOSE ENDS WITHOUT RERUNS — using existing Task128
>    evidence: preserve USEFUL_AS_TRACKING_BENCHMARK_ONLY; clarify that
>    lower return with lower exposure/drawdown does not alone establish
>    dominance by SPY; describe the survivor-universe limitation
>    accurately (do not say delisting risk is impossible); preserve the
>    cohort-return-average vs. chronological-portfolio distinction.
>    Concise dated notes only — do not reopen Task128 calculations.
>
> 9. JOURNAL AND PUBLISH — TASK129_RESEARCH_PROGRAM_DECISION.md
>    (concise, preferably ≤1,500 words); TASK129_EVIDENCE_MATRIX.csv;
>    the existing-format task-journal entry with this exact prompt,
>    actions, outcome, SHAs. Update PRODUCT_STATUS.md and the research
>    ledger only enough to point to the authoritative decision. Commit
>    and push normally to the research branch. Keep secrets, databases,
>    bulk data, and caches out of Git. No release/main merge.
>
> FINAL RESPONSE: 1. Programme verdict. 2. Starting/final SHAs and push
> result. 3. What the product currently delivers. 4. What
> profitability evidence does and does not support. 5. The main causes
> of unnecessary iteration. 6. One next experiment, explicit pause, or
> specific user decision. 7. Budget and stop condition. 8. Three-step
> roadmap. 9. Production preservation. 10. Decision document, evidence
> matrix, and journal links.
>
> The success criterion is a credible finite decision—not finding
> another task to perform.
