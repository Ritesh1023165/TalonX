# Remaining gaps — what is NOT closed, and why

## Defects deferred (documented, not implemented)

### D4 — `prospective start` false "NO-GO" while the stack is up · P2
- **Evidence:** S2 `_day2_go_nogo.json` + S3 `activation/launch_output.txt` — both times
  `cmd_start`'s post-start `run_preflight(require_stack_up=True)` ran before `dashboard_web.py`
  bound `:8787` and printed a NO-GO banner though the stack was healthy.
- **Why deferred:** the fix reworks `cmd_start`'s post-start verdict path (poll the dashboard
  port with a bounded grace, or downgrade "port not bound yet" to WARN, and print the **spawn**
  result not the preflight verdict). That path is entangled with the ownership/shutdown plumbing
  (C-4: the Sep-9 close also did not reap base-stack grandchildren in one pass). Higher blast
  radius than the rest of this change set; wants its own change + a start/stop soak test.
- **Proposed acceptance:** after `prospective start` returns, exactly one supervisor / one V2
  companion / one checkpoint daemon; the printed verdict reflects `start_verify.json`; a second
  `prospective start` while one is running **refuses** (a pidfile / port check) rather than
  spawning a second `v2_lane.db` writer; `prospective close` reaps the whole owned tree in one
  bounded pass (residual → `PASS_WITH_FINDINGS`, exit 4).
- **Blocks next session?** No, but it is the **highest-value** deferred item — the double-stack
  risk is real.

### D6 — per-lane quant counters + persisted terminal dispositions · P3
- **Evidence:** `metrics:<date>:quant:*` Redis keys carry no lane suffix (Original + Experimental
  comingled — proven Sep 9); THROTTLE/COOLDOWN/revalidation dispositions are only on
  `talonx:quant:rejected` + `rejected_candidates` DB, so the integer surface under-counts
  `evaluated`. S3 lacks a preserved Redis metrics snapshot → its `94` residual is UNRESOLVED.
- **Why deferred:** needs (a) lane-suffixed Redis keys (`metrics:<date>:quant:<lane>:*`) or an
  `exp:` namespace — a change to the hot quant path shared by Original + Experimental, and (b) a
  new EOD writer that snapshots the counter family into the session evidence dir. Both want the
  live quant process to validate against.
- **Proposed acceptance:** for any session, `evaluated == Σ(terminal dispositions)` closes from
  the integer surface alone; the dashboard "Quant published / Candidates" tile is per-lane and
  Active-V2-attributable; `prospective close` writes `quant_metrics_eod.json` into the session dir.

## Analyses left INCOMPLETE (blocked by unavailable external evidence)

| cell | why incomplete |
|---|---|
| BLSH / SKHY current SEC filing status | forward-dated 2026 environment; `data.sec.gov/submissions/CIK{1872195,2120882}.json` not reachable. BLSH `LIKELY_MIS_EXCLUSION` and SKHY `CORRECT_EXCLUSION (pending)` cannot be confirmed against a live feed. |
| Oracle cited figures ($638 B backlog, +363 %, $67 B contracts) vs the actual 8-K | accession `0001193125-26-387905` is forward-dated; no filing body to check. They are LLM-narrative, not parsed XBRL (`ROIC=None`, "pending the 10-Q"). |
| tz-rebuild spot check (10 corrected rows vs the real EDGAR "Accepted" timestamp) | same — no live EDGAR for the 2026 accessions. The Eastern conclusion rests on the internal consistency evidence (constant ~4 h offset, ORCL after-close earnings) + stable SEC tz rules, not a live check. |
| Original Question C — was a **profitable** intraday trade missed? | preserved `quant.db.bar_buffer` covers only a subset of symbols/time; no per-setup mark-to-market was computed; post-hoc price rise is deliberately **not** treated as a missed trade. Classification: `INSUFFICIENT_EVIDENCE` — not "none missed". |
| LOW_VOLATILITY units / repeat-eval audit | needs the live quant config (`min_atr_pct`, the bar timeframe) + the in-memory candidate buffer to distinguish "correct selectivity" from "repeated evaluations of the same setup" or a units bug. The frozen threshold was **not** touched; a proper audit is a separate task. |
| Rendered SPA screenshots | no browser/screenshot tool in this session — `dashboard_acceptance.md` uses read-model API output instead. |

## Delivery closure — what is left after this task

- The drain **mechanics** (age cutoff, expire, HOLD-safe) are implemented + tested. The
  **wiring** into `runner.run_poll_loop` and the `deliver_intelligence_cards` flag are the
  non-executed activation steps in `intelligence_delivery_closure.md`.
- The 9,843-row backlog is **not** touched (inspected on the `.postclose` copy only). The policy
  that would expire it on first drain is tested against a synthetic old row.
- The **product decision** — is `intelligence_delivery` meant to deliver or stay a rendered
  audit trail — is not ours to make and is the gate for everything downstream.

## Test status (consolidated)

Targeted regressions run green:
- `intelligence` (edgar/pipeline/sessions/significance/delivery): **723 pass** (pre-change) → all
  green post-change with fixtures updated.
- affected modules (`test_intelligence_edgar_normalize`, `test_intelligence_pipeline`,
  `test_intelligence_sessions`, `test_task117_acceptance_timezone`, `test_task117_migration`,
  `test_task117_deployment_rehearsal`, `test_task117_execution_scope`): **85 pass**.
- prospective / phase0 / watchlist-coverage / spa-states: **85 pass**.
- dashboard / dispatch / funnel / supervisor / telegram_owner / preflight: **527 pass**;
  narrower re-run **115 pass**.
- V2 / research incl. Task 116 exact-runtime replay: **168 pass**.
- new: `test_task117_acceptance_timezone` (26), `test_task117_intel_delivery_age_cutoff` (5),
  `test_task117_telegram_owner_dedup` (4).
- **Pre-existing, NOT caused by this change** (fixed opportunistically): 6 tests in
  `test_task117_migration.py` / `test_task117_deployment_rehearsal.py` pinned the pre-activation
  ledger hash `c09c6a88…`; the authorized Task-117 activation migrated the live ledger to
  `29e57dbc…`. Both fixtures now accept either hash.

A single full-suite run did not complete inside the session's command timeout; the affected
surface is covered by the targeted runs above. A full `pytest tests/` should be run in CI before
merge.
