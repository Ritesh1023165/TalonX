# TalonX task journal

A permanent, per-task record of what was actually requested, what was
actually done, and what the user-visible and internal outcome was — kept
separately from the (already extensive) task-numbered audit/research
documents under `docs/audits/` and `docs/research/`, which remain the
authoritative evidence for their own tasks. This journal indexes and links
those, it does not replace or duplicate them.

## Why this exists

Introduced by Task 118 (2026-09-11) because task-by-task history had
accumulated only as prose inside individual audit/research documents, with
no single place recording, per task: the exact request, whether it was
completed as scoped or partially, the operational vs. profitability
verdicts kept separately, and what was fixed/open/deferred. This directory
is that place, going forward. It does not reconstruct history that was not
already captured this way.

## Structure

```
docs/task_journal/
  README.md            -- this file
  TEMPLATE.md           -- the record.md template
  TASK_INDEX.md          -- one row per task, linking to entries/ and to
                            existing docs/audits, docs/research bundles
  RETROSPECTIVE.md       -- what this journal does and does not cover;
                            corrections to earlier entries
  entries/
    <date>_task<N>_<short-slug>/
      request.md          -- the exact prompt (verbatim), + any subsequent
                             steering messages, verbatim
      outcome.md           -- the final response actually delivered to the user
      record.md            -- structured record per TEMPLATE.md
```

## How to use it (for future tasks — see also the repository instruction
in `README.md` §16)

1. At the start of a task that materially changes running behavior, touches
   production state, or is itself a research/audit deliverable, create
   `entries/<date>_task<N>_<short-slug>/`.
2. Save the user's exact request text to `request.md` as soon as it is
   known (append later steering messages verbatim, in order, rather than
   paraphrasing them).
3. At the end, save the exact final response delivered to the user to
   `outcome.md`, and fill in `record.md` per `TEMPLATE.md`.
4. Add one row to `TASK_INDEX.md` linking the entry and any
   `docs/audits/`/`docs/research/` bundles the task produced — do not copy
   their content into the journal.
5. If a later task corrects an earlier entry's conclusion, **append** the
   correction to that entry's `record.md` (a new "Corrections" section with
   a date) and to `RETROSPECTIVE.md` — never edit out or silently overwrite
   the original text.

## What this journal does not do

- It does not reconstruct prompts for tasks that predate its creation.
  Where a historical prompt was not separately captured as a file, the
  index row says `NOT_AVAILABLE` rather than inventing or approximating
  one from memory or from the audit doc's own prose.
- It does not duplicate the content of `docs/audits/*` or `docs/research/*`
  bundles — it links to them.
- It is maintained on whichever branch the task itself was done on; it is
  not automatically synchronized across branches (this instance lives on
  `research/talonx-profitability-2026-09`).
