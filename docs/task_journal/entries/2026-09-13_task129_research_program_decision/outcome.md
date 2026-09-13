1. **Programme verdict**: **`PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS`**.
   No remaining candidate (turn-of-month, longer-horizon 52-week-high,
   further V2 live accumulation, a new free price/volume hypothesis)
   clears the six-point next-experiment gate.

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task, no code executed). Research
   `8f9dfc0b` (confirmed exact) → **`<this commit>`**, pushed to
   `research/talonx-profitability-2026-09` only.

3. **What the product currently delivers**: configured-ticker
   intraday and long-term product SURFACES (both horizons now
   explicitly authorized), understandable BUY/SELL alert contracts
   with defined decision/entry/exit policies, local paper portfolios
   and dashboard, long-only execution, descriptive Intelligence
   (non-predictive), and V2's live paper campaign — all operationally
   real and delivered.

4. **What profitability evidence does and does not support**: no
   mechanism in this repository currently carries a supported,
   positive, materiality-clearing profitability verdict on any
   live-configured population. V2 (configured scope) is genuinely
   `INCONCLUSIVE`, not rejected — the one mechanism still open. Every
   other tested mechanism (Original, Experimental, overnight-attention
   both tracks, 52-week-high, the grouped free price/volume families)
   is either `INSUFFICIENT_EVIDENCE`, `DO_NOT_ADVANCE`, or closed.

5. **Main causes of unnecessary iteration** (5, each with a lightweight
   prevention rule reusing an existing mechanism): stale-worktree/
   runtime-parity errors (Task121A); accounting/labeling corrections
   found a task later (Tasks120-128); unsupported product-restriction
   inferences (Task126); data-extension checks delayed by one task
   (Tasks123-125); provenance assumed instead of verified
   (Tasks124-125). Full detail with citations in the decision document
   §3.

6. **One next experiment, explicit pause, or specific user decision**:
   explicit pause (Option B). No experiment named under Option A — none
   passed the gate. No Option C escalation — no genuinely unresolved
   user choice was found that would itself unblock a viable programme
   without also requiring new data or a bounded experiment already
   covered by the pause's own resuming conditions.

7. **Budget and stop condition**: at most ONE new evaluation, ≤2
   working days of active effort (unless a disclosed computation
   extension), no tuning after results, no automatic follow-on after
   an inconclusive result — a proposed future budget only, not spent
   in this task. Roadmap start date retained at 2026-09-11 (Task
   118H). Stop condition: paused until one of §5's three resuming
   conditions occurs, or a subsequently authorized single evaluation's
   2-day budget is exhausted without a clearing result.

8. **Three-step roadmap**: Now (this decision, published) → Next
   authorised action (ONE user product decision or data/feature-class
   authorization, not yet made) → Decision afterward (the resulting
   single bounded experiment or continued passive V2 observation, with
   a frozen acceptance outcome). Intraday and long-term status kept
   separate throughout.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after; no code executed, no backtest run, no new
   download — this was a documentation/synthesis-only task, exactly as
   scoped.

10. **Journal/reports**: `entries/2026-09-13_task129_research_program_decision/`
    + `docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` +
    `TASK129_EVIDENCE_MATRIX.csv` + a dated correction note appended to
    `TASK128_BASELINE_PRODUCT_DECISION.md` + minimal pointer updates to
    `PRODUCT_STATUS.md`, `TALONX_RESEARCH_LEDGER.md`, and
    `TASK_INDEX.md` — all at this commit, pushed.

Priority followed as instructed: establish portfolio/programme truth →
assess user value → make one decision. The success criterion applied
here was a credible finite decision, not another task to perform — and
that is what this task delivers: a pause, with a named, bounded set of
conditions under which the programme would resume.
