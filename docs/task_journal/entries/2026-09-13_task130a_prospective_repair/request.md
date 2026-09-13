# Request

Verbatim user request (2026-09-13), the qualification-repair follow-up
to Task 130:

> TASK130A — COMPLETE OPTION A QUALIFICATION: PROSPECTIVE REPLAY,
> ACCOUNTING, AND IDENTITY
>
> OBJECTIVE
> Resolve the concrete Task130 review findings and reach a defensible
> integration-review verdict. Keep the same hypothesis, evaluation
> window, population definition, signal thresholds, holding period, and
> economic thresholds. This is qualification repair, not strategy
> tuning. Complete the fixes, tests, corrected evaluation, and decision
> in this task. Do not stop after documenting the defects.
>
> BASELINE
> Research: research/talonx-profitability-2026-09 @
> 7afcb0d5ccd630434c44655bb2b6a5133ab58cfc. Release:
> research/talonx-strategy-validation @
> f28986999eec5e313cfc89db24e4dbacfb378891. Verify actual state,
> preserve unrelated changes, do not reset either branch.
>
> AUTHORIZATION
> Authorized: isolated research implementation/focused tests;
> existing-data evaluation; narrow issuer-identity verification using
> primary sources where needed; research documentation, normal
> commits/push. Not authorized: production integration/ingestion
> expansion/application launch; Telegram/broker/paid data/production
> config changes; release/main merge or production ledger mutation.
> Preserve Redis, the V2 campaign, SPCX obligations.
>
> 1. RECORD THE REVIEW HOLD AND FREEZE THE REPAIR — append a dated
>    correction: historical subset statistics remain reported;
>    PASS_FOR_INTEGRATION_REVIEW is under review; Track B was an
>    intent-associated subset, not a proven prospective-policy replay;
>    the -2.25% measure was realized-equity drawdown, not daily marked-
>    equity drawdown. Preserve original artifacts unchanged. Before
>    calculating corrected returns, commit a repair addendum: exact
>    runtime changes; simulated-clock and information-availability
>    assumptions; capacity/reservation and event-ordering rules;
>    identity treatment; daily valuation and cost treatment; original
>    versus supplemental concentration tests; acceptance requirements.
>    Do not rewrite the original economic thresholds or claim this
>    previously examined dataset is an untouched holdout.
>
> 2. ENFORCE PROSPECTIVE ELIGIBILITY BEFORE ENTRY — implement the
>    stricter policy in an isolated replay path using production-
>    adjacent V2 logic. Do not run the permissive policy and filter
>    completed trades afterward. For every potential entry: a durable
>    intent must exist; its simulated creation timestamp must precede
>    the target entry deadline; it must match the episode/issuer/
>    target session; it must not be cancelled/expired/already
>    consumed; historical ingestion without a timely intent must not
>    mutate portfolio cash or create a position. An intent created
>    after the deadline must fail even if it exists in the final
>    database. Preserve historical catch-up, second-owner activation +
>    duplicate handling, existing staleness rules, re-entry cooldown,
>    existing-position exits, delayed reconciliation of timely
>    intents. Re-evaluate all candidates chronologically so excluded
>    entries cannot leave behind artificial occupancy/cooldown/capacity
>    effects.
>
> 3. USE AN EXPLICIT SIMULATED CLOCK — separate filing public-
>    availability evidence, assumed historical availability, simulated
>    ingestion/decision time, intent persistence time, target open/
>    close, reference-price observation, ledger reconciliation.
>    Date-only filings cannot establish observed intraday availability
>    -- define a conservative, explicit session-level convention and
>    label the resulting economics conditional on it. Use actual
>    exchange calendars. Provide timestamp-complete fixtures: timely
>    intent; late intent; missing intent; after-hours filing leading to
>    the next eligible session; restart with a previously persisted
>    intent; delayed price reconciliation without a duplicate entry. Do
>    not call synthetic timestamps "timestamp-proven historical
>    evidence."
>
> 4. IMPLEMENT CAPACITY AND EVENT ORDER CORRECTLY — $300,000 isolated
>    starting capital, $10,000 fixed entry allocation, max 20
>    positions, no borrowing/cash reset. Reserve cash/slots for
>    admitted pending intents; deterministic causal ordering for
>    competing intents; record capacity exclusions; release
>    reservations on cancellation/expiry/consumption. Do not partially
>    allocate merely because available cash is below the fixed
>    allocation -- record an insufficient-capital disposition. Entry at
>    a session's open precedes exits priced at that session's close --
>    no future close proceeds funding morning entries. A timely intent
>    retains its capacity commitment while reference-fill reconciliation
>    is pending; a missing price must not silently free capacity for an
>    overlapping position. Reuse frozen missing-price/fall-forward
>    policies without inventing fills.
>
> 5. FIX THE PHANTOM-EXIT ACCOUNTING DEFECT — remove the
>    `open_notional.pop(episode_id, allocation)` fallback; an exit for a
>    never-opened position must not create proceeds; surface an
>    explicit accounting error or invalid-event disposition. Required
>    assertions: every valid exit matches one actual open position; one
>    entry receives at most one exit settlement; skipped entries
>    produce zero exit proceeds; restart does not duplicate principal/
>    P&L; cash+marked positions reconciles to equity; costs applied
>    exactly once. Use actual position quantity/notional for dollar
>    P&L -- do not assume every trade spent $10,000 without checking.
>
> 6. COMPUTE DAILY MARKED EQUITY — value all open positions on every
>    relevant session using existing suitable prices. Record mark
>    date/source/adjustment basis, stale/missing mark treatment, cash,
>    open-position cost basis, marked value, realized/unrealized P&L,
>    costs, equity, drawdown. Ensure price-adjustment consistency with
>    reference fills/corporate actions. Do not substitute entry cost for
>    market value and call it mark-to-market; do not silently exclude
>    unavailable marks or default to zero; do not force-close positions
>    to finish flat. Include starting equity in the drawdown series.
>    Report capital utilization with its formula, distinguishing
>    invested-capital/equity exposure from % of days with any open
>    position.
>
> 7. RECONCILE ISSUER IDENTITIES — inspect the 35 ambiguous symbol-to-
>    CIK mappings. Distinguish legitimate historical identity changes,
>    symbol reuse by different issuers, multiple securities for one
>    issuer, mapping defects, unresolved cases. Use accession-level
>    issuer evidence/effective dates, never trade profitability. Trace
>    ambiguity to input records/cluster construction/evaluated
>    episodes/entered trades. Prove different issuers were not combined
>    into a cluster because they shared a ticker. Keep the 626-name
>    population fixed -- report incomplete coverage rather than
>    silently shrinking it and inheriting the full-scope verdict.
>    Correct the Task130 statement that Task112R's +1.01% belonged to
>    the 39-name scope -- it did not.
>
> 8. COMPLETE CONCENTRATION AND STABILITY EVIDENCE -- preserve the
>    originally frozen trade-count-ranked issuer-removal test. Add
>    separately: rank issuers by aggregate positive net dollar P&L
>    contribution, remove top 1/3/5, report remaining N/expectancy/P&L,
>    deterministic tie-breaking, label as a supplemental completion
>    test, not original preregistration. Do not select whichever
>    concentration definition passes. Retain issuer- and time-block
>    uncertainty methods and the conservative disagreement rule;
>    explain remaining dependence limitations. Keep 2026H1's negative
>    result visible -- do not change period boundaries or exclude it.
>
> 9. RUN MEANINGFUL TESTS, THEN ONE CORRECTED EVALUATION -- test at
>    minimum: missing/late intent rejection before portfolio mutation;
>    timely intent + delayed reconciliation; removed cold-start entry
>    doesn't arm cooldown/suppress a later valid episode; competing
>    intents can't overbook cash/slots; 21st position rejected;
>    insufficient cash creates neither partial allocation nor later
>    proceeds; close proceeds can't fund the same morning's open;
>    duplicate entry/exit + restart behavior; existing positions exit
>    after removal from entry scope; unrealized decline appears in
>    daily drawdown; ambiguous symbols don't merge distinct issuers;
>    costs reconcile exactly. Tests must assert economic/state
>    outcomes, not merely non-negative ending cash. Run a small
>    deterministic parity check, then the corrected full evaluation
>    over 2024-09-01 -> 2026-03-31. Preserve Task130 outputs, write
>    corrected artifacts to a separate directory. Per-episode
>    comparison: unchanged/newly excluded/newly admitted/changed
>    timing/changed quantity-P&L/identity-related difference. Explain
>    every material difference -- do not force the corrected result to
>    reproduce +2.02%.
>
> 10. APPLY THE FINAL GATE -- report separately: historical economic
>     result; prospective-policy implementation acceptance; timestamp
>     evidence limitations; portfolio/risk acceptance; identity/
>     coverage acceptance; integration-review verdict. Retain the
>     original economic requirements (mean net >+0.50% after 20bps;
>     issuer confidence lower bound >0; time-dependence method agrees;
>     required concentration/stability checks). An economic pass alone
>     cannot close missing implementation/identity/valuation evidence.
>     Choose PASS_FOR_INTEGRATION_REVIEW / DO_NOT_ADVANCE /
>     INCONCLUSIVE / BLOCKED_BY_SPECIFIC_EVIDENCE_GAP. A pass
>     authorizes no deployment. If critical evidence remains
>     unavailable, name it precisely and stop without redesigning the
>     strategy.
>
> 11. JOURNAL AND PUBLISH -- record this exact prompt, repair
>     checkpoint, runtime manifest, tests, corrected results,
>     differences, verdict. Publish TASK130A_REPAIR_PROTOCOL.md,
>     TASK130A_PROSPECTIVE_REPLAY_ACCEPTANCE.md,
>     TASK130A_CORRECTED_ECONOMIC_DECISION.md, compact episode-
>     difference/identity/concentration/equity evidence, relevant
>     isolated code and tests, minimal PRODUCT_STATUS.md and research-
>     ledger updates. Commit/push normally to the research branch. No
>     bulk data/credentials/production databases/caches in Git. No
>     release/main merge.
>
> FINAL RESPONSE: 1. Overall and separate gate verdicts. 2. Starting/
> final SHAs and push result. 3. Actual prospective-policy enforcement
> and timestamp limitations. 4. Capacity, reservations, and phantom-
> exit fix. 5. Corrected economics versus Task130. 6. Daily marked
> equity and drawdown. 7. Winner-concentration and stability. 8.
> Issuer identity and coverage. 9. One next action, production
> preservation, and process cleanup. 10. Journal, protocol, code,
> tests, and evidence links.
>
> Complete the identified qualification gaps. Do not introduce a new
> hypothesis, parameter search, or unrelated operational work.
