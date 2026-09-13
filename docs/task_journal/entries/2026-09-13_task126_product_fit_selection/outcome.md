1. **Selection, statistical, and product verdicts**: Selection =
   **`NO_CANDIDATE_PASSES_PRODUCT_AND_DATA_GATES`**. Statistical =
   **not applicable** (no evaluation was run — neither candidate
   passed the pre-return selection gate). Product verdicts: 52-week-
   high proximity = **`BLOCKED_BY_SPECIFIC_PRODUCT_OR_DATA_REQUIREMENT`**;
   turn-of-month = **`DO_NOT_ADVANCE`**.

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task). Research `1248a0d` (confirmed
   exact) → **`<this commit>`**, pushed to
   `research/talonx-profitability-2026-09` only. No merge to
   release/main.

3. **Why neither candidate fits**: 52-week-high proximity (George &
   Hwang 2004) is published as a cross-sectional, long-short,
   decile-ranked portfolio held 6-12 months — no existing TalonX
   strategy holds anything near that long, and this task's own
   instruction explicitly disallows inventing a convenient shorter
   holding period to make it fit; that is an unresolved PRODUCT
   decision, not a research one. Turn-of-month (McConnell & Xu 2008)
   is published as an aggregate, market-wide calendar effect; applied
   per-ticker it produces an IDENTICAL signal across all 48 configured
   tickers every month — using no ticker-specific information at all,
   which structurally conflicts with a "configured-ticker alert"
   product's own premise.

4. **Exact causal contract and holding period**: none — no contract
   was frozen for either candidate since neither passed the selection
   gate (Part 4 of the task is explicitly conditional on a candidate
   passing).

5. **Coverage, costs, and corporate-action treatment**: both
   candidates have full existing daily-bar data coverage (same
   `task95g_broad_cross_sectional/_daily`, `adjustment=all` panel used
   throughout this program) and trivial corporate-action requirements
   — neither was blocked on data availability. This was documented as
   part of the product-fit gate but no cost model or corporate-action
   handling was implemented since no evaluation ran.

6. **Absolute and benchmark-relative economics**: not computed for
   either candidate — no return, trigger, or P&L was ever inspected,
   consistent with selecting before looking at outcomes.

7. **Uncertainty, concentration, and limitations**: not applicable to
   either candidate (no data was evaluated). The genuine "uncertainty"
   in this task is a PRODUCT uncertainty, named precisely: (a) whether
   TalonX will authorize a multi-month, capital-locked alert horizon;
   (b) whether a non-differentiating, calendar-wide exposure toggle is
   an acceptable "alert" type for this product.

8. **One next action / explicit stop decision**: explicit stop for
   this task. The smallest unblocking requirement for each candidate
   is named in `TASK126_CANDIDATE_SELECTION.md` Part 3 — both are
   product decisions outside this research-only task's authorization,
   not additional research or data work. No third hypothesis invented,
   no broad literature search started, no indefinite live-waiting
   recommendation made. No strategy in this research program currently
   carries an `ADVANCE_TO_FURTHER_VALIDATION` product verdict pending
   action.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after; no code was executed against any live or
   production path (this task involved only document authoring and
   reasoning, no scripts run).

10. **Journal/reports**: `entries/2026-09-13_task126_product_fit_selection/`
    + `docs/research/{TASK126_CANDIDATE_SELECTION,TASK126_ECONOMIC_DECISION}.md`
    + `docs/research/evidence/task126/selection_summary.json` +
    corrections appended to `TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md`
    and the Task 125 journal outcome + `PRODUCT_STATUS.md` and
    `TALONX_RESEARCH_LEDGER.md` updates — all at this commit, pushed.

Priority followed as instructed: product fit → (no frozen contract
reached) → (no computation reached) → economic decision. A credible
decision to stop, reached on mechanism/product-fit/data grounds before
any return was inspected for either candidate, is reported here rather
than another unsupported candidate evaluation.
