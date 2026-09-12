Saved verbatim (condensed), as received. Single-turn request.

---

TASK121A — REPAIR RUNTIME PARITY AND COMPLETE THE EXPERIMENTAL REPLAY

OBJECTIVE
Correct Task121's source/protocol errors, prove the replay represents the
repaired Experimental runtime, then run one fixed longer historical
window. Deliver a usable economic result or a precisely evidenced
blocker. Do not extend the previous adapter unchanged. Do not return
another standalone audit or inventory.

BASELINE — VERIFY: release `research/talonx-strategy-validation` @
`f28986999eec5e313cfc89db24e4dbacfb378891`; research
`research/talonx-profitability-2026-09` @ `2f28922`. Production session
closed; preserve production ledgers, SPCX's obligation, config, Redis.
Read Task121 protocol/results/script, Task118A exit-fix evidence, and the
actual release source. Verify current branch states; preserve unrelated
work.

AUTHORIZATION/BOUNDARIES: implement research adapter fixes, run isolated
tests/replays, commit/push; no production app start/DB/config write/Redis
mutation; no external messages/broker/paid data/strategy tuning; no
dashboard expansion or general research-platform rewrite; no main merge/
force-push; do not repair production's already-fixed exit wiring again.

PART 1 — SOURCE PROVENANCE FIRST: the verified release contains
ExperimentalLane.consume() -> _maybe_check_exit() -> self.paper.check_exits().
Task121's claim that no automatic exit caller exists is incorrect for
this release; its "Friday's exits were manual" claim is unsupported.
Determine why the research task saw different behavior (stale worktree?
search scope? import precedence? cached imports/different checkout?
another evidenced cause?). Record for every material imported module:
__file__/resolved path, repository/commit, content hash, any intentional
research adaptation -- scanner, strategy/config, Experimental
runtime/paper, shared paper math, calendar, backtest engine, execution
adapter. Fail before replay if imports resolve to an unintended checkout;
a five-file fingerprint alone is insufficient. Use narrow reproducible
synchronization or explicit module loading -- no broad branch merge, no
uncommitted manual byte-copy. Append corrections to Task121: automatic
exits are wired in the pinned release; Friday's exits must not be
reclassified as manual without evidence; one-week vs one-month
discrepancies; historical 35-symbol universe vs current configured
scope; runtime estimate; previously inferred signal directions.

PART 2 — FREEZE THE ACTUAL CONTRACT: read the actual event path, not
only function names/config labels. Record candidate triggers/relaxed
gates, bar completion/indicator availability, warmup/HTF requirements,
session/blackout rules, global candidate ordering/throttle,
cooldown/loss-lockout behavior, actual Experimental entry
admission/position sizing, stop/target triggers and gap/freshness rules,
whether bearish signals close positions, overnight/weekend holding
behavior, whether EOD flatten is actually scheduled. Do not enable 15:50
EOD flatten merely because flatten_all() exists. Do not infer
Experimental's behavior from Original's lifecycle. Cost convention:
apply_spread crosses half the specified spread per side -- a 5bps
parameter is ~5bps round-trip at unchanged reference prices, not 5bps
per side; verify with a small worked test; distinguish embedded
spread/other costs/unmodeled fees; correct earlier conflicting labels.
Docs-only correction if needed; do not reopen dashboard implementation.

PART 3 — PROVE PARITY BEFORE THE LONG RUN: small deterministic event
trace through (A) pinned repaired runtime components with isolated
stores/transports and (B) the replay adapter. Include: qualifying
bullish entry; stop-triggered exit; target-triggered exit; existing-
position exit while entry gates reject; bearish signal with/without an
open position; stale/missing observation; crossing session close with an
open position; simultaneous candidates on multiple symbols; repeated
events/restart where state persistence is modeled. Compare decisions/
rejection reasons, entry/exit ordering/timestamps, prices/spread/
quantities, cash/position state, cooldown/throttle behavior, zero
external sends. Do not cite unrelated passing tests as proof of adapter
equivalence -- publish correlated traces and focused tests. If historical
data can't reproduce live tick timing: define a common observation
schedule, label the limitation explicitly, don't call intrabar H/L
identical to sampled-price exits, keep any conservative sensitivity
separate from the primary simulation. No long replay until material
lifecycle differences are resolved; if unresolvable, report the exact
blocker, no invented parity.

PART 4 — FIX TELEMETRY AND UNIVERSE ACCOUNTING: capture every published
signal (ID, symbol, event/decision time, direction/trigger, gate
disposition, entry/exit eligibility, actual paper action or reason for
no action). Verify the earlier "75 bearish signals" claim from actual
records if they exist; otherwise keep UNVERIFIED, superseded by the new
run's trace. Do not infer direction from equality of aggregate counters.
Publish a static mapping: historical dataset symbols <-> current
configured Experimental symbols -- separate historical validation
universe, configured-symbol intersection, missing configured names,
before-listing periods, missing eligible sessions. Do not call 35
historical symbols the complete configured product scope without proving
that mapping.

PART 5 — FIXED LONGER REPLAY: before inspecting new outcomes, freeze one
contiguous calendar-month window with explicit inclusive/exclusive
bounds, sufficient pre-roll, explicit terminal-position policy; do not
repeatedly extend until trades appear; record that this history has
already been inspected. Use measured throughput to budget honestly --
previous evidence estimated ~2.5hr/month; do not substitute the one-week
runtime as the monthly estimate. Run in the isolated research worktree,
bounded progress reporting, durable outputs, one authoritative
portfolio/event ordering; do not parallelize per symbol if shared
throttle/ordering/capital constraints make results dependent; safe data
prep may be optimized separately; no abandoned duplicate processes. If
optimizing the hot path, prove decision/trade equivalence on the fixed
trace first. Run the frozen contract once -- no threshold grid/new
signal family/post-hoc loser removal.

PART 6 — ECONOMICS AND COMPLETENESS: actual processed date
range/symbols/bars; raw candidates and fully qualified publications;
bullish/bearish counts from records; entries/exits/open-unresolved
positions; every no-entry disposition; trade frequency/holding duration;
gross P&L/modeled costs/net P&L; win rate/expectancy/PF where defined;
marked equity/drawdown where supported; issuer/time
concentration/uncertainty. Do not force positions closed at the dataset
boundary -- use subsequent observations under the frozen policy, or
retain with explicit marked valuations/obligations. Zero trades is a
valid result only after verified direction/action accounting -- it does
not prove a defect is absent simply because candidates were generated.
Do not describe sample size alone as "properly powered." A CI excluding
zero is one input to a decision, not automatic evidence for live
promotion.

PART 7 — ONE DECISION: ADVANCE_TO_FURTHER_VALIDATION /
REJECT_CURRENT_CONTRACT_FOR_PRODUCT_USE /
INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER, considering opportunity
frequency/net economics/execution fidelity/coverage/concentration/
uncertainty together. If still zero-entry or too sparse, state the
product implication; don't automatically recommend another longer run
without explaining why it would resolve a specific uncertainty. No
Experimental Telegram enablement/strategy promotion; no return to V2
composition analysis or dashboard work.

PART 8 — JOURNAL/PUSH/CLEANUP: Task121A journal entry (exact
prompt/final response, starting/final SHAs, source-provenance root
cause/corrections, frozen contract/protocol, parity traces/tests, replay
duration/outcomes/limitations, product decision/one next action). Commit
sanitized adapter/tests, module manifest, signal/trade tables,
reconciliation summary, report. Keep secrets/production DBs/bulk data
outside git. Push normally. Verify all task-owned subprocesses stopped;
do not signal unrelated processes or alter Redis.

FINAL RESPONSE (required, 10-point): 1. Verdict and SHAs. 2. Why Task121
inspected/reported the wrong exit behavior. 3. Correct contract,
including EOD and spread treatment. 4. Runtime-versus-adapter parity
evidence. 5. Actual replay window, scope, runtime and completion. 6.
Signal directions and entry/exit reconciliation. 7. Economic results and
limitations. 8. Advance/reject/inconclusive decision. 9. ONE next action
and acceptance criteria. 10. Production preservation, journal and
evidence links. "Priority: correct source -> proven parity -> completed
replay -> decision."
