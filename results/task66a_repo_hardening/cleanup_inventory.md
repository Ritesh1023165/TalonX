# Task 66A Repository Cleanup Inventory

Conservative, evidence-based. See `cleanup_inventory.json` for the full machine-readable version.

## Result: zero deletions, three fixed gaps

Given the repository's scale and the explicit instruction to preserve all research evidence
(`results/`, `docs/research/TALONX_RESEARCH_LEDGER.md`, and every dataset/config-hash/fingerprint
artifact), this pass targeted **genuine, evidenced gaps** rather than manufacturing deletions to fill
a quota. Three real issues were found and fixed; nothing was found that met the bar for
`DELETE_CANDIDATE` with the kind of proof this task requires (no imports, superseded by a named
canonical doc, generated output, duplicate, abandoned/unreachable code, dead flag with no reader).

### Fixed

1. **`.gitignore` gap** — `logs/` (6 old `task14_*` report logs, predating this session) was untracked
   but not ignored, showing as noise in every `git status` all day. Confirmed unreferenced by any
   source file. Added `/logs/` to `.gitignore`, matching the existing `reports/`/`/results/`/`/data/`/
   `.run/` pattern for generated, machine-local content. **No files deleted.**
2. **Superseded handoff doc** — `results/task64_paper_piv_readiness/tomorrow_0800_handoff.md` predates
   Tasks 65/65B/66A and can't describe them. Added a non-destructive marker at the top pointing to the
   current canonical handoff and runbook. **Original content below the marker is unchanged.**
3. **README doc gap** — README never mentioned `talonx_piv` (a substantial harness since Task 64) or
   the research ledger (the actual current-status source of truth). Added two short pointer sections.
   **No existing README content was rewritten.**

### Categories

| Category | Count | Notes |
|---|---|---|
| ACTIVE | Every `talonx_*` package, `tests/`, `docs/`, `results/`, `research/scripts/`, root-level operational scripts | See `cleanup_inventory.json` for per-item evidence |
| ARCHIVE | 0 | Nothing met the archive bar (superseded-but-audit-relevant) beyond the handoff doc, which was marked in place rather than moved, to keep its existing path/links intact |
| DELETE_CANDIDATE | 0 | No file had the required evidence (zero imports/references, confirmed unreachable, confirmed generated-not-source) within this pass's scope |
| UNKNOWN_KEEP | 2 sample CSVs | `examples/data/sample_AAPL_trade_1m.csv` / `sample_multi_trade_1m.csv` — confirmed built on a pre-fix bug (commit `1e28647`), already tracked as a follow-up regeneration there, still actively used by `xfail(strict=True)` tests. Out of scope for a repo-hardening task to silently regenerate or remove. |

### What this pass deliberately did not attempt

An exhaustive per-file audit of `results/` (65+ tasks' worth of research evidence) or
`research/scripts/` (28+ reproduction scripts). Both are treated as a single protected category per
this task's own rules. This is a scope decision, not an oversight — see `cleanup_inventory.json`'s
`explicitly_not_done` for the full reasoning.
