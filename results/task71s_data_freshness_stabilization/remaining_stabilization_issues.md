# Task 71S -- Remaining Stabilisation Issues (NOT implemented in this task)

Per this task's explicit scope ("Do not implement dashboard redesign,
orchestration, Gemini, long-only product changes, new alpha, or
execution-independent alerts"), the following are retained for later,
separately-scoped tasks:

1. **Dashboard/EOD-report surfacing of the new fields** -- `provider_health`,
   per-symbol freshness state, and gap classifications are now produced
   (`piv_info["provider_health"]`, `freshness_report.json`,
   `gap_forensics.py`'s classification output) but no dashboard or EOD
   report template has been updated to DISPLAY them yet. `reporting.py`
   was deliberately not modified this task.
2. **Live, automated post-hoc gap classification wired into `eod`** --
   `gap_forensics.py` is a tested, reusable module, but it is not
   automatically invoked by the `eod` CLI command (that would add a new
   live network dependency -- a real Alpaca historical-data call -- to the
   EOD path, which this task judged out of scope for "the smallest safe
   correction"; today it is run manually/on-demand, exactly as this task's
   own artifacts were produced).
3. **A genuine PROVIDER_WIDE_INTERRUPTION worked example** -- 2026-08-26's
   real data contains zero cases meeting `gap_forensics.py`'s
   provider-wide-escalation bar (>=5 symbols disagreeing with history in
   the identical clock minute); this classification path is unit-tested
   with synthetic data (`test_provider_wide_interruption_requires_many_symbols_same_minute`)
   but has no real-world example to validate against yet.
4. **Cross-process/disk-persisted freshness state** -- `FreshnessTracker`
   is in-memory only (matching the PRE-EXISTING `_stale_flagged`/
   `_last_seen_wall`'s own in-memory-only posture); unlike
   `readiness.py`'s `session_readiness_state.json`, a process restart mid-
   session does not currently restore prior freshness/provider state. This
   was a deliberate choice (adding NEW persistence is a larger, separate
   change than "the smallest safe correction" for this task), not an
   oversight -- flagged here for a future task to evaluate.
5. **Threshold tuning for premarket/postmarket** -- see
   `threshold_analysis.md`: the evidence available does not support a
   different value for either window; revisit only if future evidence
   (per that document's own "what would justify revisiting this" section)
   emerges.
6. **Missing opening-minute semantics beyond classification** -- this task
   classifies WHY a minute was missing; it does not change
   `readiness.py`'s own pass/fail gate or its 30-minute opening-window
   definition (unmodified, per this task's fail-closed-by-default
   instruction).
7. **Unified Quant/Brain/Core/Dispatch/dashboard orchestration** --
   explicitly out of scope per this task's instruction.
8. **Execution-independent alerts and shadow ledger** -- explicitly out of
   scope per this task's instruction.
9. **Complete PAPER end-to-end re-verification** -- this task's evidence is
   entirely retrospective (historical reads) plus unit/integration tests;
   it does not re-run or re-verify a live PAPER session end-to-end (out of
   scope, and this task's own constraints prohibit starting one).
10. **`REQUIRED_1M_BARS`/`min_bars_required` decoupling** (carried over from
    Task 70S's own remaining-issues list, still unresolved, still out of
    scope since fixing it would require touching `talonx_quant/config.py`).
