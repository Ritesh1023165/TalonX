# Tomorrow's full-application E2E session — how to run it

This is the exact contract for the **next** task (Task 66B or equivalent) to launch ONE clean,
full-application PAPER validation session using `run_talonx.py` — the normal 6-module application,
**not** `talonx_piv`. Not started, scheduled, or launched by this task (Task 66B-PREP) — this is
the handoff only, per explicit instruction ("Do NOT start or schedule any live session in this
task").

## Target start

Approximately **07:00 ET / 12:00 UK**, ~2.5 hours before the 09:30 ET regular open — enough time
for market-data ingestion, ChromaDB/Brain, the causal initial Quant preseed (Task 66B-PREP Part 2;
real smoke test on 2 symbols took well under a minute per symbol, but budget generously for the
full watchlist, same as the PIV warmup budget in `next_e2e_piv_handoff.md`), Redis subscriptions,
Telegram, every store, and the pre-market feed to all settle before the regular session starts —
avoiding the exact "started after market close" problem Task 66B hit on 2026-08-24.

No date is hardcoded anywhere in the startup logic this task touched — this handoff may mention
2026-08-25 as the next trading day, but nothing in `run_talonx.py`/`talonx_ops` depends on that
literal date.

## Sequence

```
06:30 ET / 11:30 UK   Fresh preflight:
                       py -3.12 -m talonx_ops.cli preflight --expected-sha (git rev-parse HEAD) \
                           --out results/task66b_e2e/full_app_preflight.json
                       Require FULL_APP_E2E_READY. If BLOCKED, STOP -- do not weaken any check
                       to force a pass. brain_operational_hard_requirement failing is a real
                       blocker for E2E validation specifically (see talonx_ops/preflight.py's
                       own docstring) -- production's normal Brain-degrades-gracefully behavior
                       is untouched, but this preflight refuses to call the session
                       FULL_APP_E2E_READY if Brain isn't genuinely operational.

~07:00 ET / 12:00 UK  Start exactly ONE full run_talonx.py application:
                       py -3.12 run_talonx.py
                       (no --skip-* flags -- this is a full-topology validation run; add
                       --skip-earnings-fast-track / --skip-earnings-sync only if genuinely
                       needed to reduce noise, never --skip-quant/--skip-brain/--skip-core/
                       --skip-dispatch/--skip-paper-trading)

07:00-09:30 ET         Verify, before the regular session begins:
                       - Initial Quant preseed log line ("Initial Quant preseed complete: N/M
                         symbol(s) ready") appeared BEFORE any live tick was processed
                       - Market data provider log line matches talonx_ops.provider_status
                         .configured_market_data_provider()
                       - Brain/Core/Dispatch/Paper all show "enabled" in the startup summary log
                       - /ping answers (send it to the configured bot/chat) and reports live
                         uptime/CPU/RAM/pipeline metrics -- NOT the "unknown" placeholders PIV's
                         /ping shows for brain/core/dispatch (those pipeline stages genuinely
                         don't exist in PIV; they DO exist here, so /ping should report them for
                         real)
                       - No duplicate Telegram poller (only ONE of {this run_talonx.py process,
                         a separate talonx_piv session} may poll the same bot token at once)

09:30 ET                Regular session begins.

10:00 ET                Formal E2E checkpoint -- effective decision-eligible universe, per
                        talonx_ops.comparator's stage taxonomy where evidence allows.

15:50 ET                EOD/flatten window is talonx_piv's convention, not the normal
                        application's -- run_talonx.py's PaperTradingEngine has no scheduled
                        flatten of its own (see talonx_paper/engine.py); confirm this explicitly
                        rather than assuming PIV's EOD behavior carries over.

16:00 ET+                Stop the process (Ctrl+C -- SIGINT is handled cleanly, stops every
                        component and closes every store, see run_talonx.py's _handle_sigint).
                        Then generate the EOD report:
                        python generate_eod_report.py --date YYYY-MM-DD
                        Confirm the new "## Run metadata" section (Task 66B-PREP Part 10) shows
                        run_mode=FULL_APP, the real commit SHA, and the real configured market
                        data provider / paper execution path -- NOT "unknown", which would mean
                        runtime_metadata.json wasn't written (check the startup log for the
                        "Failed to write runtime metadata" warning if so).
```

## Cross-path comparator

Once this session has run, `talonx_ops.comparator.build_comparator_report()` can finally compare
real full-app evidence against the same day's PIV evidence (if a PIV session also ran) --
`talonx_ops/cli.py comparator-smoke` reads `results/task66b_prep/comparator_smoke_report.json`'s
sibling for the honest "what actually agrees, what's missing" answer. See
`cross_path_comparator_contract.md` for the taxonomy and its known limitation (presence-based only
until real full-app evidence exists to calibrate a field-level diff against).

## Expected success criteria

- Preflight: `FULL_APP_E2E_READY`.
- Startup log shows the initial Quant preseed complete line BEFORE the first live-tick log line.
- Brain, Core, Dispatch, Paper Trading all show "enabled" — none silently degraded.
- Market data provider explicitly identified in logs/`runtime_metadata.json`/EOD report.
- Paper execution path explicitly `LOCAL_SIMULATED_LEDGER` in the same places — never conflated
  with PIV's Alpaca paper broker.
- `/ping` answered at least once with real (not "unknown") pipeline metrics.
- No duplicate Telegram poller.
- Session runs uninterrupted (or, if restarted, that's reported honestly, not glossed over — this
  runtime has no restart-safe readiness persistence of its own the way `talonx_piv` does; a
  restart here is a real gap to report, not something to paper over).
- ORPB_V1/FPRC_V1 fingerprints unchanged; zero diff on protected `talonx_quant/*` files.
- No real-capital capability introduced or exercised anywhere.
- Alpha status remains explicitly **UNPROVEN** in whatever summary is produced.

## Do not

- Do not weaken any preflight/safety check to force `FULL_APP_E2E_READY`.
- Do not tune, replay, or reinterpret ORPB_V1/FPRC_V1 — both remain rejected and retired.
- Do not force a natural signal by adjusting strategy config/thresholds.
- Do not begin alpha discovery inside this session — see `results/task65_piv/next_alpha_discovery_plan.md`.
- Do not assume PIV's readiness/staleness/reconciliation architecture applies here — it doesn't
  (see `full_app_runtime_graph.md`'s comparison table); build a full-app-specific equivalent only
  if a real defect is found running this session, not preemptively.
