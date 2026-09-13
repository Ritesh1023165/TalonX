# Request

Verbatim user request (2026-09-13), immediately following Task 123's
completed overnight-attention diagnostic:

> TASK124 — BOUNDED INTRADAY DATA FEASIBILITY AND NEXT ECONOMIC DECISION
>
> OBJECTIVE
> Determine whether existing free data access can supply the missing
> coverage needed for a meaningful, causally timed evaluation of the
> overnight-attention candidate.
>
> Complete this as one bounded task. Do not run another profitability
> backtest, change the hypothesis, or build a new data platform.
>
> BASELINE
> - Repository: Ritesh1023165/TalonX
> - Research branch: research/talonx-profitability-2026-09
> - Expected research HEAD: eee821f — resolve and record full SHA.
> - Release: research/talonx-strategy-validation
> - Expected release SHA: f28986999eec5e313cfc89db24e4dbacfb378891.
> - Verify actual state; preserve unrelated changes.
>
> Production remains stopped. Preserve all ledgers, Redis, configuration,
> and outstanding SPCX obligations. No application launch, Telegram
> messages, broker activity, paid subscription, release change, or
> strategy promotion.
>
> 1. CARRY FORWARD THE CORRECT TASK123 DECISION — preserve Track A
>    qualified non-actionable association, Track B statistically
>    inconclusive with a negative point estimate, product decision
>    DO_NOT_ADVANCE the tested actionable contract. Correct any remaining
>    "genuinely executable" wording: Track B used causally timed reference
>    fills; actual execution quality was not established. Do not
>    reinterpret an inconclusive result as proof the hypothesis is false,
>    or the daily association as evidence of an actionable edge.
>
> 2. INVENTORY EXISTING DATA BEFORE REQUESTING MORE — locate all existing
>    relevant daily and minute datasets including Task93/121 data and
>    both historical price directories; build a manifest covering all 48
>    configured tickers (active/paused+snapshot date, minute-data date
>    ranges, provider/feed identity, regular-session coverage, missing
>    sessions/timestamps, volume availability/meaning, adjustment mode,
>    corporate-action info, prior tasks, whether outcomes already
>    inspected). Separate locally-available / verified-retrievable /
>    merely-claimed / unavailable data. Current watchlist membership is
>    not historical point-in-time membership.
>
> 3. VERIFY EXISTING FREE ACCESS WITH SMALL PROBES — inspect existing
>    adapters/provider config/account capabilities, never print
>    credentials. Use official docs + bounded requests for retention,
>    feed, pagination limits, historical-vs-recent restrictions,
>    adjustment options, coverage around decision/entry/next-open. Probe:
>    an already-covered period, an older period, a currently-missing
>    active ticker, a known corporate-action interval. Data verification
>    only, never inspecting strategy returns. Distinguish no-entitlement /
>    no-trading-history / empty-response / request-error. No provider
>    bypass, no new provider integration.
>
> 4. ESTABLISH WHETHER THE DATA FITS THE CONTRACT — Track B's decision
>    rule unchanged (fixed pre-close cutoff, same-time-of-day cumulative
>    volume, 2-minute delay, next-session-open exit, frozen threshold/
>    cost). Verify complete historical reference windows, correct bar
>    timestamp semantics, entry-after-delay availability, actual next
>    exchange session, early-close handling, missing-bar handling without
>    manufactured fills, consistent split/dividend treatment. IEX volume
>    and consolidated volume are not automatically interchangeable — do
>    not concatenate feeds into a supposedly uniform volume history or
>    substitute a feed silently. A material contract/feed change is a
>    separate research decision.
>
> 5. MEASURE FEASIBILITY, NOT PROFITABILITY — active tickers supportable,
>    complete sessions/eligible observations, covered calendar span,
>    expected download size/request count, estimated acquisition runtime
>    from measured probe performance, remaining quality limitations,
>    whether a genuinely unexamined evaluation period exists. No returns,
>    no threshold tuning, no cutoff search, no outcome-based date choice.
>    Explain issuer/date dependence; no "properly powered" claim from an
>    arbitrary trade count. Bounded to ~90 minutes of active work; finish
>    with the exact restriction if blocked, not repeated retries.
>
> 6. RETURN ONE DATA VERDICT — DATA_EXTENSION_FEASIBLE (one concrete
>    acquisition-and-validation task spec) / DATA_AVAILABLE_BUT_CONTRACT_
>    INCOMPATIBLE (name the incompatibility + smallest required decision)
>    / DATA_EXTENSION_BLOCKED (exact limitation, archive as unsupported).
>    None of these authorizes deployment.
>
> 7. JOURNAL AND PUBLISH — update the task journal with the exact
>    request, starting/final SHAs, actual actions/probe timestamps,
>    data-source evidence, findings/corrections, outcome/one next action.
>    Commit TASK124_INTRADAY_DATA_FEASIBILITY.md, machine-readable
>    coverage/probe manifests, a concise product-status update, small
>    reusable verification code only if necessary. Keep credentials/
>    databases/bulk market data/generated caches out of Git. Commit/push
>    to the research branch only, no merge to release/main, avoid
>    unrelated documentation cleanup.
>
> FINAL RESPONSE: 1. Data verdict. 2. Starting/final SHAs and push
> result. 3. Existing vs. newly verified accessible coverage. 4.
> Provider/feed/adjustment findings. 5. Causal-timing compatibility. 6.
> Unexamined-data availability and limitations. 7. Acquisition estimate
> or exact blocker. 8. One concrete next task. 9. Production
> preservation. 10. Repository evidence links.
>
> The deliverable is a decision about whether the missing evidence is
> obtainable—not another strategy result, dashboard change, or
> operational acceptance cycle.
