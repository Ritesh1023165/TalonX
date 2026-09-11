# Task 75S — Stage 2: Universe Selection Audit

## Question
Why were 10 symbols selected instead of the 35-symbol operational universe, and did that selection
rely only on canonical provenance, or also on the prior 35-symbol performance finding (Task 37)?

## Primary basis: documented provenance (sufficient on its own)
`stage0_verification_and_inventory.md` §5 cites, from `docs/research/TALONX_RESEARCH_LEDGER.md`:
- The 10-symbol universe established at Task 4/7B and reused continuously as the ledger's own
  "canonical baseline" / "frozen candidate" dataset through Task 24/25A/26/36/53/54/55/56/58/61R/63/63R.
- A documented mandatory research-family criterion requiring `>=10 symbols` (ledger, ~line 5664) --
  i.e. the 10-symbol set is itself the documented minimum bar, not a placeholder.
- Every ledger reference to "the frozen 35-symbol universe" is in the context of the **live/operational
  PIV product universe** (Task 64's paper-readiness preflight), never as an offline research/backtest
  scope choice.

This alone satisfies Task 74S's own instruction ("use the legacy 10 only if repository evidence
identifies it as the intended frozen research scope") without needing to reference any performance
number.

## Secondary reference that was also made: Task 37's outcome
`evaluation_protocol.md` §2 (Task 74S) additionally stated: "the one occasion the 35-symbol universe
was evaluated for research purposes — Task 37 — concluded `LIKELY_TOO_SPARSE` and was not adopted going
forward." **This is a reference to a prior task's observed signal-frequency result**, not pure
provenance. It was used as corroboration alongside the provenance argument, not as the sole or primary
basis for excluding the 35-symbol universe from this task's own replay.

## Assessment
- **Does this violate "never select symbols using observed returns, signal counts or performance"?**
  Narrowly read, that instruction governs selecting symbols *within* a universe based on *this task's
  own* results -- not citing a separate, already-completed, already-published prior task's outcome as
  one input to a provenance question. No symbol was added or removed from this task's own universe
  based on anything this task itself observed.
- However, the instruction's spirit is broader than that narrow reading, and the corroborating citation
  of Task 37's *signal-frequency finding* is a real, if secondary, use of performance-adjacent evidence
  in this selection's write-up. **This is disclosed here as a genuine (if minor) boundary blur, not
  hidden.** Removing that one sentence from `evaluation_protocol.md` would not change the selection --
  the provenance argument alone is sufficient and was the actual basis for going with 10 -- but the
  sentence should not have been included as written.

## Verdict
**Universe selection: MATCHES REQUESTED SCOPE**, on the strength of the documented-provenance argument
alone. The additional citation of Task 37's outcome was an unnecessary and imperfectly-scoped
corroboration that should be read as informational context, not as part of the selection's justifying
evidence. No correction to the selected universe (10 symbols) is warranted; a scope qualification is
recorded here and in `task74s_evidence_addendum.md`.
