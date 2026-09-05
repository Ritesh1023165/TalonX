# Task 78I — Rehearsal Logs

This rehearsal is entirely test-driven (`tests/test_task78i_stage5_rehearsal.py`) — there is no
separate live-process log to capture; the full pytest run itself IS the rehearsal execution, and
each scenario's trigger/expected/observed/evidence/verdict is recorded per-row in
`../rehearsal_scenarios.csv`.

The full raw suite output is kept out of git (per repository convention for large logs) — its
content is reproduced verbatim in `../test_results.txt` (committed; final summary line only would
be too little, so the full run is preserved there) with the following hash for provenance:

```
sha256(test_results.txt) = 83887d02c3c87262aafb002260e4e249a834660d0924eed35721b8e56398c631
```

## Reproduction commands

```
# Full 20-scenario Stage 5 rehearsal only:
.venv/Scripts/python.exe -m pytest tests/test_task78i_stage5_rehearsal.py -q

# Full repository suite (what test_results.txt captures):
.venv/Scripts/python.exe -m pytest -q

# Full collection check (0 errors expected):
.venv/Scripts/python.exe -m pytest --collect-only -q
```

Run from the repository root (`c:\workspace\TalonX`) using the project's own `.venv` interpreter
(the shell's default `python` on this machine resolves to an unrelated global install — see
`execution_journal.md`'s own environment note, carried forward from Task 77I).
