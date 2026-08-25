# Claude Handoff — after Task70

## Immediate next priority

**New DEVELOPMENT-phase phenomenon discovery.** F6_FADE_V1 is rejected —
`REPLICATION_FAIL` on a broader, cleaner sample than validation, with the
gross edge's sign reversed and a bootstrap CI entirely negative. Do not
revisit F6 looking for a way to rescue it; the task's own rule is explicit
about this. Read `task70_summary.md` first for the full reasoning, then
`profitability_evidence_summary.md` for the cross-period comparison that
drove the rejection.

## If you're asked "was this a fair test, could F6 have just gotten
unlucky on replication?"

Check `replication_summary.md` first — the answer the evidence supports is
no: PF<1 at every cost level including zero, bootstrap CI entirely
negative (not just failing to exclude zero — actively excluding it on the
negative side), not concentrated in a few symbols/days, removing the best
winners makes it worse, zero data-integrity issues, and a LARGER sample
than the validation period that passed. There isn't a plausible "unlucky
draw" story here that survives contact with the diagnostics already run.

## If you're asked to develop a new candidate

Follow the exact discipline this task and Task67A/67B/68A used:
1. Pick a family/phenomenon on DEVELOPMENT data only (nothing here is
   held out for iteration — see `results/task67a_phenomenon_discovery/
   data_split_contract.json`).
2. Freeze it (spec + fingerprint), pre-register the pass/fail criteria
   BEFORE touching any holdout (see `results/task68_f6_freeze/
   validation_protocol.json` as the template — reuse its exact 8-criterion
   structure unless there's a specific reason to change it, and if you do
   change it, that change must also be pre-registered before any holdout
   outcome exists).
3. Use `historical_exposure_audit.json`'s conclusion: 2024 is now
   PARTIALLY consumed (VALIDATION=2024-02-01..03-15 and
   REPLICATION=2024-09-03..10-18 are now OUTCOME_CONTAMINATED for THIS
   task's own record — don't reuse them as "clean" for a new candidate).
   Remaining clean 2024 territory: roughly 2024-01-01..2024-01-31,
   2024-03-16..2024-09-02, and 2024-10-19..2024-12-31 — re-audit before
   trusting this, don't just take my word for it.
4. Materialize data, run once, classify honestly per whatever you
   pre-registered — same as this task.

## If you're asked about F6's product gap (no stop)

It's moot now (F6 is rejected), but if a *different* fade-style candidate
is developed later, remember: F6_FADE_V1 had `stop_rule: NONE` by design
(Task 67B never established a causal risk unit). Any successor intended
for production needs its own defensible stop, derived from DEVELOPMENT
data only, frozen before validation — never backed into from a validation/
replication result.

## If you're asked about the runtime warmup provider (Task69Q's finding)

Not this task's concern (runtime worktree was not touched, per instruction)
— but worth remembering: `TalonX/talonx_piv/alpaca_historical_warmup.py`
(runtime worktree) has a verified, tested prototype for replacing
yfinance-based warmup with Alpaca's own historical bars (feed=iex). Still
needs its own integration task — don't casually mix it into alpha work.

## Files worth reading first

- `task70_summary.md` (this task's full narrative)
- `profitability_evidence_summary.md` (why replication, not validation, is
  the decisive signal)
- `historical_exposure_audit.md` (what's clean, what isn't, for the NEXT
  candidate's holdout selection)
