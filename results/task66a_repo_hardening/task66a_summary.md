# Task 66A — Repository Cleanup + Infrastructure Hardening

Branch `research/talonx-strategy-validation`, starting SHA `e2d696722731f772088b7d95727303eed03723a4`.

## A) Restart-safe session readiness

Fixed the exact defect found live in Task 65B: `SessionReadinessValidator` state was in-memory only, so a
process restart after 10:00 ET made every symbol read `DATA_NOT_READY` regardless of true data quality.

`talonx_piv/readiness.py` gained `to_state()`/`restore_state()` plus atomic `save_readiness_state()`/
`load_readiness_state()`, persisting per-symbol-session readiness (finalized READY/DATA_NOT_READY decisions,
plus raw pre-finalization observations for a symbol still PENDING at crash time) to
`session_readiness_state.json`. Fail-closed throughout: a corrupt or previous-day state is rejected; a
corrupt individual symbol entry cannot become eligible while other symbols in the same file restore
correctly; nothing is ever synthesized. Wired into `talonx_piv/session_runner.py` at every session-date
rollover (covers both a genuine new trading day and a mid-session restart). Four new telemetry events
(`SESSION_READINESS_STATE_RESTORED`/`MISSING`/`INVALID`/`STALE`). 18 focused tests (17 unit + 1 end-to-end
integration reproducing today's actual incident timeline).

## B) Full application runtime parity

Traced `run_talonx.py` (the full 6-module application) against the Task 65B PIV runtime and found one real
gap: the inbound Telegram `/ping` command listener (`talonx_dispatch.telegram_listener.TelegramReplyListener`)
was never started by `cli.py start`. That class already supports a standalone, `dispatch_agent=None` degrade
path by design (documented in its own module docstring) -- no duplicate listener was built; the existing one
is reused with a PIV-scoped audit DB (`piv_telegram_audit.db`, never sharing state with a separately-running
full application's own audit trail) and started as a concurrent asyncio task alongside `SessionRunner.run()`,
stopped cleanly in every exit path. A `--no-telegram-inbound` flag exists for the one real operational
constraint documented in `telegram_inbound.py`: Telegram allows only one `get_updates()` poller per bot token,
so this must be disabled if a separate `run_talonx.py` process is polling the same token concurrently.

A machine-readable `talonx_piv/runtime_manifest.py` documents all 13 expected PIV runtime components and
which preflight check covers each; a new `runtime_parity` preflight check reports `RUNTIME_PARITY_PASS`/
`RUNTIME_PARITY_FAIL` explicitly. `talonx_brain`/`talonx_core`/`talonx_paper` remain intentionally out of PIV
scope (research-report and multi-signal-correlation machinery, not operational health) -- not silently
disabled, never part of the PIV harness's purpose in the first place.

## C) Repository cleanup

Conservative and evidence-based, per instruction: **zero files deleted.** Three genuine, evidenced gaps were
found and fixed (see `cleanup_inventory.md`/`.json` for full reasoning): `.gitignore` was missing a rule for
the untracked `logs/` directory (added); a Task-64-era handoff doc factually predates three subsequent tasks
it can't describe (marked superseded in place, original content untouched); README never mentioned
`talonx_piv` or the research ledger (two short pointer sections added, nothing rewritten). No file met the
evidence bar this task requires for `DELETE_CANDIDATE` (zero imports/references, confirmed superseded by a
named doc, confirmed generated output, confirmed duplicate, confirmed unreachable). `results/` and
`research/scripts/` were deliberately treated as a single protected category (canonical research evidence)
rather than individually audited, per this task's own explicit preservation rules.

## D) Proof nothing strategy-relevant changed

Protected files (`strategy.py`, `indicators.py`, `consumer.py`, `config.py`) have zero diff, checked before
and after all work. ORPB_V1 and FPRC_V1 implementation fingerprints reconfirmed unchanged. No alpha tuning,
replay, or reinterpretation occurred anywhere in this task.

## Tests

101 focused PIV tests passed. Full regression: **1984 passed, 1 known pre-existing failure (unrelated,
unchanged from prior tasks), 1 skipped, 15 xfailed** -- exactly 26 more passing tests than the previous
1958-test baseline, matching the 26 new focused tests added today with no other drift.

## Safety at task end

Zero PAPER open orders, zero PAPER open positions, zero active PIV runners/schedulers. Real-capital execution
remains unsupported everywhere in the codebase. PR #10 remains draft/open/unmerged.

## Conclusion

`INFRASTRUCTURE_HARDENING_COMPLETE` / `FULL_E2E_PIV_READY`. Alpha remains **UNPROVEN** -- this was
infrastructure work only; no profitability conclusion is made or implied. Next action:
**one clean, full end-to-end PAPER PIV session** (see `next_e2e_piv_handoff.md`) -- not started by this task.
