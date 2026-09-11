# record.md template

Copy this into `entries/<date>_task<N>_<short-slug>/record.md` and fill in
every section. Leave a section explicitly stated as `NOT_APPLICABLE` or
`NOT_AVAILABLE` rather than deleting it — a missing section should never be
silently indistinguishable from one that was filled in and found empty.

```markdown
# Task <N> — <short title>

## Objective and acceptance criteria
<What was asked; what "done" meant for this task.>

## Timing
- UTC start: <timestamp>
- UTC end: <timestamp>

## Branch / SHA
- Branch(es): <e.g. release + research>
- Starting SHA(s): <per branch>
- Implementation / result SHA(s): <per branch, pushed>

## Requested vs. completed scope
<Enumerate the requested parts/sections; mark each DONE / PARTIAL (with
what's missing) / NOT_DONE (with why) / BLOCKED (with the exact blocker).>

## Source / runtime / data manifest
<Modules and versions actually exercised (not just "fingerprint matches"),
data sources and coverage windows, reproducible commands.>

## Tests / experiments / results / limitations
<What was run, what it showed, what it does not show.>

## User-visible outcome
<What the user was told, in the same terms as outcome.md.>

## Verdicts (kept separate)
- Operational verdict: <e.g. LIVE_PAPER_SESSION_STARTED / NO_GO / ...>
- Profitability / research verdict: <e.g. BASELINE_COMPLETE / INCONCLUSIVE
  / BLOCKED — never inferred from the operational verdict>

## Production effects, external sends, protected-state checks
<Any live database/ledger changes (with before/after hash if applicable),
any external message sent (transport, outcome, message id, sanitized
destination), confirmation that protected state (secrets, live ledgers)
was not read/written outside what was authorized.>

## Findings
- Fixed: <...>
- Open: <...>
- Deferred: <... and why>

## Evidence links
<Links to docs/audits/*, docs/research/*, CSVs, commits.>

## Later corrections
<Filled in by a LATER task if this entry's conclusions needed revision —
never edited into the original sections above.>
```
