# Rollback — Task 117 overnight release

**Superseded.** The authoritative rollback procedure is
`docs/audits/task117_final_activation_corrections/rollback.md`. This file
previously described restoring pre-activation database copies as a routine
step — that instruction was stale and has been removed here, not merely
annotated: every schema change this release made is additive, so a
compatible-code rollback (`git checkout <PREV_SHA>`, no database touched)
is sufficient in the ordinary case, and any database restore should only
ever be a reconciled, last-resort action that never blindly discards
legitimate post-activation writes (new positions, entry intents, delivered
or ambiguous-attempt records with their message IDs). See the corrected
document for the actual procedure, including the reconciled-restore fallback
and the full-restore last resort with their required preconditions.
