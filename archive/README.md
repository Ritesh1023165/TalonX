# archive/ — index of retained historical material

Task 105 created this index. **Nothing was physically moved into `archive/`** — the repository's
historical material is load-bearing (referenced by runtime path defaults, research reproduction
scripts with SHA manifests, and tests), so it stays where it is. This file points at it.

## Historical research & owner decisions (in `docs/research/`)

| file | what it is | why retained |
|---|---|---|
| `docs/research/TALONX_RESEARCH_LEDGER.md` | append-only chronological history of every research/validation task | the canonical "what was tried and rejected" record; linked from README |
| `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md` | frozen product & strategy specification | defines the frozen Original semantics |
| `docs/research/TALONX_OWNER_DECISIONS.md` | owner-level decisions log | the "why" behind product direction |
| `docs/research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md` | PIV permanent product target | PIV scope + real-capital prohibition |
| `docs/research/task21_frozen_early_failure_spec.json` | early-failure spec | **SHA-referenced by `research/scripts/task22_freeze_spec.py`** — do not move |

## Pre-consolidation architecture docs (in `docs/`)

`architecture-overview.md`, `modules/{ingest,quant,brain,core,dispatch,paper,orchestrator}.md`,
`setup.md`, `running.md`, `troubleshooting.md`, `configuration.md`, `performance.md`,
`roadmap.md`, `phase2-multi-horizon.md`, `earnings-radar.md`, `premarket-radar.md`,
`bar_buffer_persistence.md`, `backtesting.md` (old).

**Status:** superseded by the current docs (`docs/CURRENT_ARCHITECTURE.md` et al., indexed in
`docs/README.md`). Kept because they still carry accurate low-level detail (indicator math,
env-var reference, bar-buffer restart handling, radar internals). When they conflict with a
current doc, the current doc wins.

## Task artifacts (in `results/`)

- `results/task55…task88/**` — git-tracked Task 55-88 diagnostic / PIV / qualification evidence
  (committed before `.gitignore` gained `/results/`). Referenced by `talonx_piv` /
  `talonx_compare` runtime path defaults and by `research/scripts/*` (SHA-verified inputs).
  **Do not move.**
- `results/task9*/`, `results/task10*/` — local-only (gitignored) per the established convention.
  Includes the large research datasets (Alpaca SIP, point-in-time universe, event datasets) and
  every Task 93-105 `final_report.md` / `preregistration.md`. See
  `results/task105_repository_cleanup/backtest_preservation_manifest.md`.

## Compressed verdicts (auto-memory, outside the repo)

`~/.claude/projects/…/memory/talonx_task*.md` — one file per task with the compressed verdict.
Not a repo artifact; noted here for completeness.
