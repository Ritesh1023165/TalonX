# Task 75S — Stage 1: Test Collection and Dependency Closure

## Reproduction (before any change)
- Interpreter: `C:\workspace\TalonX\.venv\Scripts\python.exe`, Python 3.12.10.
- Active virtual environment: `.venv` (this repo's own established venv; `include-system-site-packages
  = false`; created 2026-08-07 per `pyvenv.cfg`).
- Command: `python -m pytest --collect-only -q` (also reproduced with plain `python -m pytest -q`,
  same result). No `--ignore`/`--deselect`/`--continue-on-collection-errors` flag used for this
  reproduction.
- Result: `ERROR collecting tests/test_task61_validation_protocol.py`,
  `ERROR collecting tests/test_task61r_temporal_freeze.py`, both
  `ModuleNotFoundError: No module named 'exchange_calendars'`. Final line:
  **`2179 tests collected, 2 errors in 11.65s`**; pytest reports
  `Interrupted: 2 errors during collection` and (per this repo's default configuration, no
  continue-on-collection-errors) **the run aborts before any test executes** -- zero tests pass, zero
  fail, when this error is present and no override flag is used. See `collection_before.txt`.
- Dependency state before repair: `pip show exchange-calendars` → "WARNING: Package(s) not found."

## Cause determination
- `exchange-calendars==4.13.2` **is declared**, but only in `research/requirements-task61.txt` (a
  task-specific, narrow-scope requirements file added in commit `24afb11`, never modified since) --
  **not** in `requirements-dev.txt`, `talonx_quant/requirements.txt`, or `pyproject.toml`'s own
  dependency list.
- The two affected test files (`tests/test_task61_validation_protocol.py`,
  `tests/test_task61r_temporal_freeze.py`) have **no `pytest.importorskip`/`skipif` guard**: both
  unconditionally `SPEC.loader.exec_module(...)` a `research/scripts/task61*.py` module at file-import
  (collection) time, and that module does `import exchange_calendars` at ITS OWN top level. There is no
  `conftest.py` collection-ignore rule scoping these files to an optional extra.
- **Classification: missing test-extra declaration / an intentional optional-integration boundary
  implemented without a guard.** This is a pre-existing test-authoring fragility (these two files
  should have skipped cleanly when the optional research dependency is absent, but do not), not a
  "wrong interpreter" issue (this IS the project's one and only established venv) and not a broad
  missing-dependency problem (every other test in the 2179-item suite collects and runs fine without it).

## What can and cannot be established about prior presence
- `.venv/Lib/site-packages`'s own directory mtime is **2026-08-14**, and no entry inside it (checked via
  `-newermt "2026-08-13"`) is newer than that date except `psutil-7.2.2` and `yfinance-1.6.0` --
  **no `exchange_calendars*` dist-info exists now, and nothing in this venv shows evidence of an
  install/uninstall of this specific package at any point the directory's own history reflects.**
- However, `pip install -r research/requirements-task61.txt` resolved from **pip's local wheel cache**
  (`Using cached exchange_calendars-4.13.2-py3-none-any.whl` and its sub-dependencies) rather than
  downloading from the network -- meaning this exact wheel *was* fetched into this machine's pip cache
  at some prior point (consistent with the file's own history, `24afb11`, being used for the original
  Task 61 work), even though it is not evidence of it having been installed into *this* `.venv`
  specifically.
- **This task's own `stage4_final_full_suite_results.txt` (Task 73S, commit `848de0d`, same calendar
  day as this audit -- see `scope_timeline.md`) is truncated**: it begins mid-progress-dot-stream, with
  no pytest banner, no `collected N items` line, and no recorded invocation command. It is therefore
  **not possible to confirm from that file alone** whether the Task 73S run actually collected these 2
  modules successfully, or excluded them via a flag that simply wasn't captured in the saved log.
- **Correction to Task 74S's claim**: Task 74S's `execution_journal.md`/`task74s_summary.md` stated this
  dependency was "present as of Task 73S's clean run two days ago, absent now." Both halves of that
  claim are now known to be unsupported: (a) the two runs are the **same calendar day** (`848de0d` at
  2026-08-27 07:53 +0100; this audit's reproduction later the same day -- see `scope_timeline.md`), not
  two days apart, and (b) there is no positive evidence the package was present in `.venv` during the
  Task 73S run either -- the site-packages mtime evidence, if anything, suggests it was **not** present
  then either, given no install/uninstall touched that directory since Aug 14. **Per this task's
  instruction, this claim is not asserted as "the package disappeared" -- the correct, evidence-backed
  statement is: this task cannot establish that `exchange-calendars` was ever present in this `.venv`,
  and Task 74S's "present two days ago" claim was an unverified assumption that is hereby withdrawn.**
  See `task74s_evidence_addendum.md`.

## Repair performed
**Permitted repair applied**: `python -m pip install -r research/requirements-task61.txt` -- restores
an already-declared, already-pinned dependency (`exchange-calendars==4.13.2`) into this project's own
established `.venv`, via the repository's own requirements file and normal `pip install` method. No
global install, no version change, no broad upgrade (3 small transitive dependencies --
`pyluach`, `toolz`, `korean_lunar_calendar` -- were pulled in as `exchange-calendars`' own declared
requirements, not separately chosen).

## After repair
- `python -m pytest --collect-only -q`: **2185 tests collected, 0 errors** (2179 + 6 from the two
  previously-uncollectable modules; see `collection_after.txt`).
- `tests/test_task61_validation_protocol.py tests/test_task61r_temporal_freeze.py`: **6 passed** (see
  `affected_module_results.txt`).
- Full suite: see `full_suite_results.txt` and `task75s_summary.json` for exact collected/passed/
  failed/skipped/xfailed counts and the explanation of the count difference from Task 74S's reported
  `2168 passed, 1 skipped, 10 xfailed`.

## Note on the fragility itself (observation, not an action taken)
Independent of the environment question above, the lack of an `importorskip`/`skipif` guard in these
two test files means **any** environment missing this optional research dependency will silently abort
the *entire* suite (zero tests run) rather than skipping just these two files -- a materially worse
failure mode than a clean skip. This is flagged as an observation for a future, separately-scoped task;
per this task's "smallest justified correction" instruction, no test-file change is made here (the
repair is dependency installation only, and this task's own scope is not to modify test-file skip
behavior beyond auditing why collection failed).
