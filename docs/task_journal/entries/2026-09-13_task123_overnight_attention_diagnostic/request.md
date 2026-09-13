Saved verbatim (condensed), as received. Single-turn request.

---

TASK123 — OVERNIGHT ATTENTION DIAGNOSTIC WITH CAUSAL TIMING

OBJECTIVE
Correct Task122's timing assumption and run the bounded overnight-return
diagnostic. Separately determine whether existing intraday data supports
an actionable version of the hypothesis. Produce results and a decision
in this task. Do not build a new framework, run a broad search or change
production.

BASELINE — VERIFY: release `research/talonx-strategy-validation` @
`f28986999eec5e313cfc89db24e4dbacfb378891`; research
`research/talonx-profitability-2026-09` @ `36b28ca`. Read
TASK122_CANDIDATE_DECISION.md, its feasibility script/artifacts, existing
data manifests, configured-watchlist snapshot, task journal. Preserve
production ledgers, SPCX's obligation, Redis and config. No application
launch, external messages, broker calls or paid data. No release merge,
strategy promotion or live scope change.

PART 1 — CORRECT THE TIMING CLAIM: Task122 assumed final same-day volume
was known early enough to buy at that same day's closing price. Withdraw
that causal-execution claim -- final daily volume includes activity
through the close; shift(1) prevents baseline contamination but does not
make the trigger observable before entry. Define two distinct tracks: A.
DAILY-DATA ASSOCIATION DIAGNOSTIC (final volume on session S selects
observations whose reference return is S.close -> next XNYS session
open -- a conditional historical-return study, not an executable
strategy or achievable paper fill). B. ACTIONABLE PRE-CLOSE CANDIDATE
(decision uses only info available at a fixed pre-close cutoff; entry
after a stated decision/delivery delay using a subsequent observable
price; requires suitable intraday data and a separately frozen
contract). Do not silently substitute yesterday's volume or post-close
entry -- different hypotheses. Append a correction to Task122 and the
journal.

PART 2 — FREEZE THE PROTOCOL BEFORE RETURNS: static universe/active-
paused status from the recorded snapshot; primary dates/actual coverage;
trigger = final daily volume >=2x trailing 20-session average excluding
S; entry/exit references and calendar alignment; return definition and
corporate-action treatment; cost convention and practical materiality
threshold; control population and weighting; uncertainty method; exact
sensitivities and stopping rule. Do not select thresholds after
observing outcomes. Replace vague "e.g. 3x" with an exact choice or
remove it. At most two predefined sensitivities. A materiality threshold
in bps must be justified independently of the result -- notional sizing
converts to dollars, it doesn't establish execution realism.

PART 3 — COVERAGE AND DATA VALIDITY: distinguish all configured/active/
paused/historically-covered/missing-or-pre-listing. Do not call 35/48
full coverage. Do not include paused names in a primary active-scope
claim without labelling. Reuse existing data first including the second
price directory; resolve duplicate/source precedence explicitly; no
unnecessary downloads/universe expansion. Verify ordered unique dates,
valid prices/volumes, complete prior-20-session windows, correct next
exchange session (holidays/early closes), missing next-session prices/
terminal observations, adjustment provenance. Do not use the next
available row as next session when intervening sessions are missing.
For splits/dividends: determine price-return vs. adjusted-total-return,
check corporate-action boundaries against existing metadata, don't
double-add dividends, don't call adjusted historical prices executable
quotes; if unresolved, report the limitation. DATA_UNAVAILABLE != no
trigger.

PART 4 — RUN THE FAST DAILY DIAGNOSTIC: small vectorized script reusing
existing loaders. Before the full calculation, test: (1) trailing
average excludes the trigger session; (2) return pairs correct
symbol/next exchange session; (3) missing sessions not silently skipped;
(4) cost conversion applied once; (5) corporate-action treatment matches
the stated return definition; (6) zero-trigger vs. unavailable-data
stay distinct. Compute trigger counts by ticker/month, gross/net
close-to-next-open reference return, mean/median/win-rate/tail-losses,
issuer/date concentration, coverage/exclusion counts. Compare with
unconditional overnight returns, consistent weighting/common usable
dates. Report absolute conditional return AND incremental difference vs.
control. For uncertainty: preserve trigger/control overlap in joint
resampling, address common market shocks via date/time blocks, include
issuer sensitivity without treating correlated stocks as independent,
fix block construction before outcomes, report limitations rather than
the most favorable interval. No portfolio-equity claim from event-average
returns unless a full portfolio simulation (allocation/concurrency/cash/
costs) is explicitly defined.

PART 5 — ACTIONABLE DATA FEASIBILITY: inspect existing intraday data
only for coverage of the same symbols/dates, completed bars available
before close, volume accumulation/timestamp semantics, a subsequent
entry-price observation, next-session opening observation. Before
calculating actionable returns, freeze: decision cutoff relative to
actual XNYS close, prior-data-only reference volume measure, trigger
threshold, alert/processing delay, entry-price observation after that
delay, fixed next-open exit policy, costs/missing-data/corporate-action
rules. Prior-full-day average vs. same-time-of-day cumulative average
are different normalizations -- select and justify ONE, don't test both
and pick the profitable one. On early-close days use the actual schedule
or predeclare exclusion; don't use full-day volume/closing-auction info
at a pre-close decision time. If data supports it, execute the bounded
test in this task with the frozen contract, report separately from the
daily diagnostic, use a reference-fill label where execution can't be
established. If not: complete the daily diagnostic, name exact missing
symbols/dates/fields/timing evidence, return
ACTIONABLE_FEASIBILITY_BLOCKED, no fabricated prices/paid data/new
provider. Do not search multiple cutoffs/delays/holding periods.

PART 6 — DECISION: separate verdicts -- diagnostic
(ASSOCIATION_SUPPORTED / ASSOCIATION_NOT_SUPPORTED /
ASSOCIATION_INCONCLUSIVE) and actionable candidate
(READY_FOR_FURTHER_VALIDATION / NOT_SUPPORTED_UNDER_TESTED_CONTRACT /
ACTIONABLE_FEASIBILITY_BLOCKED). A profitable-looking daily association
cannot advance an executable strategy if it depends on unavailable
same-close information. A positive CI is insufficient without credible
timing/cost/coverage assumptions. Already-inspected history stays
exploratory. No automatic Telegram enablement/production promotion. No
repeated window extension until significance appears. Select ONE next
action addressing the actual result; if unsupported, close it rather
than automatically searching variants; if blocked, specify the smallest
missing input and its value.

PART 7 — JOURNAL/PUBLICATION: Task123 journal entry (exact prompt/final
response, starting/final SHAs, Task122 timing correction, frozen
protocol/exposure chronology, data/runtime manifest, tests/results/
limitations/decision, production-preservation checks). Commit sanitized
reproducing script + focused tests, protocol, coverage and trigger/
control result tables, TASK123_OVERNIGHT_ATTENTION_RESULTS.md, actionable
feasibility/test report, journal and corrected Task122 references. No
secrets/production DBs/bulk data in git. Push normally. No main merge,
release deployment, production session or recurring job.

FINAL RESPONSE (required, 10-point): 1. Diagnostic and actionable
verdicts separately. 2. Starting/final SHAs and push result. 3.
Corrected timing contract. 4. Active/configured/historical coverage. 5.
Conditional and control returns, costs and uncertainty. 6. Corporate-
action and execution limitations. 7. Actionable test result or exact
missing data. 8. ONE next action. 9. Production preservation. 10.
Journal, reports and immutable commit links. "Priority: causal contract
-> bounded computation -> economic decision."
