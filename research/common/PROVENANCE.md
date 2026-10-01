# research/common: provenance

| File | Source | Identity |
|---|---|---|
| `research_stats.py` | `research/task67a_lib/research_stats.py` on `origin/research/task75b-corporate-action-preflight` @ `14e770e883f542002efbc6851bb7750ab2308cd4` (git blob `9351a281910fa2d123a942a38dfead161c2b6ccd`) | **byte-identical**; sha256 `79ae73bf8082c8fa70f97f8b2e3277b00e64f3a4a98fe5b165ed1ee2b78c243d`. Pinned by `tests/test_research_common.py`. |
| `locked_range_guard.py` | ported from `research/task75b_preflight/holdout.py` @ `14e770e` | **generalized**, not a copy: per-program `ProgramSpec`, its own state file under `results/<program>/`, and download + load enforcement. It refuses another program's state file and refuses to change a registered program's locked ranges. The Task75 guard state (`results/task75b_preflight/holdout_state.json` on the task75b branch) is a different file on a different branch and is never opened. |

**`research_stats.py` must not be edited.** A change breaks the hash test. Upstream fixes require a new, recorded copy.
