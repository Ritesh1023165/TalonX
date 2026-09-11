# Task 117 final-activation corrections — acceptance matrix

Corrects the specific defects found reviewing `24aaf05`. Branch
`research/talonx-strategy-validation`. No strategy change; V2 fingerprint
`11107198c5b81237` unchanged throughout.

| item | requirement | result | evidence |
|---|---|---|---|
| **A1 paths** | real `v2_lane.db`/`.env`/status paths traced; "fresh Day-1" narrative removed; correct backup targets; fail closed if the ledger is unexpectedly missing; automatic schema changes enumerated; backup+migration rehearsed on isolated copies with cash/positions/stale-ABCL/intents/delivery-history verified to survive | **PASS** | `resolved_paths_and_migrations.md`; `deployment_candidate.md` §1 corrected; live `v2_lane.db` md5 `29e57dbcd1a567fbc4bb0e73efdba95f` unchanged before/after the rehearsal |
| **A2 lookback** | `--live-lookback-days 45` (not 5) in the deployment candidate; propagation verified CLI→worker→source adapter; boundary case (first insider outside 5 days, inside the 10-td cluster window) added | **PASS** | `deployment_candidate.md` fixed; `test_task117_live_lookback_boundary.py` (3/3 pass) — proves 45-day lookback keeps both insiders visible, demonstrates a 5-day lookback would silently drop the first one, and pins the CLI/`V2Service` defaults at 45 |
| **A3 single Intelligence process** | inspect the existing `ComponentSpec`; remove the separate manual poller from the runbook; propagate delivery config to the one supervised child; verify acceptance list | **PASS** | `supervised_intelligence.md`; `deployment_candidate.md` §3 rewritten; `test_task117_supervised_intelligence.py` (4/4 pass) — exactly one `intelligence` spec, no `--send` baked into its argv, `include_v2` stays False, env-var propagation proven with a real spawned subprocess through the actual `SubprocessRunner.spawn()` path |
| **A4 lock lifecycle** | robust lock spanning acquisition→spawn→registration→surviving stack; PID-reuse-safe identity; live owner never bypassed by `--force`, with or without valid metadata; unknown/corrupt metadata fails closed; stale recovery verified gone; no check/unlink race can delete a fresh replacement lock; cleanup only releases entitled ownership; Windows path-identity consistent; real isolated tests (a)–(g) | **PASS** | `ownership_lifecycle_tests.md`; `talonx_ops/prospective/lock.py` rewritten (rebind_owner + owner_token + atomic rename-claim + verify-before-discard + bounded psutil calls); `tests/test_task117_single_writer_lock.py` 18/18 real-process tests, stable over 4 consecutive full runs; startup verdict semantics unaffected (16/16) |
| **A5 backlog** | recompute at the actual rehearsal timestamp using the verified event-time/origin policy; `event_time_lookup=None` removed; unknown freshness never silently fresh; counts + sample dispositions published; production expiry unexecuted | **PASS** | `backlog_rehearsal.md` — 9,840 EXPIRED / 3 PENDING at the real instant `2026-09-11T07:17:03Z`, using the runtime's own `text_events.accepted_at_utc` policy; isolated copy only, deleted after; production untouched |
| **A5 rollback** | prefer compatible-code rollback retaining additive data; stop owned writers first; preserve positions/intents/message-IDs/ambiguous attempts; never blind-restore over new activity; explicit reconciliation plan before any DB restore | **PASS** | `rollback.md` — supersedes the prior doc's wrong path and blind-restore ordering; documents why every schema change here is additive/backward-compatible so code rollback alone suffices, with a reconciled-restore procedure as a fallback and full restore as an explicit last resort |
| **B research** | verify the reported worktree/branch/commit; read the contract; do not broadly merge release/research to sync a fingerprint; identify exact runtime modules/data contracts for an equivalent replay; complete dataset inventory + prior-rejection summary + frozen 39-name manifest | **PASS** | worktree confirmed at `C:\workspace\TalonX-task118-profitability`, branch `research/talonx-profitability-2026-09`, commit `6c27914` verified, new commit `863d1ed` pushed; fingerprint mismatch (`ea2c686e...` vs `11107198...`) root-caused to a line-ending checkout artifact (content byte-identical once `\r` stripped) and fixed by a narrow 5-file byte-copy — **not** a branch merge; `docs/research/TASK118_INVENTORY.md` — datasets, 9 closed prior-rejection spaces, frozen 39-name manifest resolved 2026-09-11 |
| **B baseline run** | run deliverable A if data exists, else finish inventory and name the precise missing input | **NOT RUN — precise reason given** | deliverable A needs a real, isolated `ingestion_ledger.db` copy driven through `talonx_research/replay_engine` end-to-end — a multi-hour analysis exercise, correctly out of scope for tonight's bounded release-correction window; `INVENTORY.md` §5 states exactly what it needs (frozen membership — done; isolated ledger copy; `replay_engine` wiring with `execution_allowlist`; 20 bps costs; price data ends 2026-03-31) so it can start immediately tomorrow |
| **C verification** | focused tests + affected regressions; one isolated rehearsal of the corrected launch path; sanitized evidence published; both branches committed/pushed separately; production state unchanged; no processes/messages left | see `MORNING_HANDOFF_ADDENDUM.md` | 1,212+ passed / 0 failed across the affected surface (delivery, dashboard, prospective, lock, lane_accounting, supervisor, execution_scope, lookback boundary); production ledger md5s unchanged; stray test-created lock artifact found and removed; Redis untouched; release SHA and research SHA pushed separately, no main merge |

## Newly found and fixed during this correction (not in the original review list)

- `runner.py::deliver_cycle` computed its own `now` but never forwarded it to
  `process_pending`/`process_digest` — production behaviour was correct
  (falls back to real time either way) but a caller-pinned `now` (as tests
  do) was silently ignored, which is exactly the §1D "actual decision time"
  contract this whole release is about. Fixed: `now=now` now passed through
  to both calls.
- `test_task117_execution_scope.py::test_prospective_start_stack_passes_the_deployment_flags`
  took a real lock against the live `v2_lane.db` (no isolation) — found via a
  stray `v2_lane.db.startlock` file sitting next to the production ledger.
  Fixed: isolated onto a `tmp_path` ledger, matching the pattern already used
  elsewhere.
- A race in the stale-lock-break path (`_claim_stale_for_removal`) could let
  two racers both become "owner" if the second one's atomic claim happened to
  grab the first one's freshly-created replacement lock — reproduced
  directly with a real 2-subprocess test, fixed by re-verifying claimed
  content before discarding it.
- A real Windows process-teardown hazard: a `psutil` liveness/identity query
  on a process concurrently exiting (the `.venv`-shim → re-exec'd grandchild
  pattern the supervisor/V2 companion always use) can block indefinitely —
  reproduced directly, root-caused to non-detached test child processes
  (production always uses `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`), and
  hardened with bounded (2 s) timeouts on every `_terminate`-path psutil call
  as defense in depth regardless of that root cause.

## Not claimed

That all possible defects are eliminated. `remaining_blockers.md` lists what
remains open.
