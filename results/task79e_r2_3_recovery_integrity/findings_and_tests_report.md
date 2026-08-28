# Task 79E-R2-3 — Recovery-State Integrity and Deterministic Poller Closure

## Build checkpoint

- Starting branch: `research/talonx-strategy-validation`
- Starting SHA: `96fa40ab5e1601b06f639cf757191caa8c4329f6`
- Task feature commit: `fbc78f4`.

## Confirmed defects and fixes

1. Periodic reconciliation discarded `matched=False`, while an exception
   retained potentially permissive prior flags. Reconciliation now persists an
   entry-only admission block on mismatch or error and clears it only after a
   successful matched pass. Unexpected shorts retain their more specific,
   higher-priority rejection. SELL-to-close remains available.
2. Pending-plan restart recovery selected intents by symbol and could restore
   an older terminal intent. Recovery now derives exact outstanding BUY
   `intent_id` values from non-terminal orders and orphan uncertain/bare
   intents; ambiguous same-symbol state is visibly blocked rather than guessed.
3. A later cumulative BUY fill replaced the position record. BUY updates now
   merge only the incremental fill into current holdings while preserving prior
   exits, P&L fields, first-fill timing, and the durable exit-reason latch.
4. Same-day identity recovery did not verify current bindings. Reuse now also
   requires matching config hash, feed mode, and runtime SHA; otherwise a fresh
   session identity is minted.
5. Two yfinance tests depended on the real premarket clock. Tests now freeze
   the regular-session branch they assert, with a separate test proving that
   premarket still fetches data but intentionally suppresses callbacks.

## Acceptance results

- **Reconciliation admission:** mismatch and exceptions persist a BUY-only
  broker-boundary block; a later matched pass clears it.
- **Protective exits:** reconciliation failure does not disable SELL-to-close;
  verified holdings minus pending sells remain the sizing authority.
- **Exact pending plan:** restart recovery follows the non-terminal order's
  exact `intent_id`; an older terminal same-symbol plan is not restored.
- **Cumulative BUY merge:** prior exit quantity/price/P&L, current remaining
  holdings, first-fill timestamp, and triggered-exit latch survive later fills.
- **Session binding and durable exposure:** changed config/runtime bindings mint
  a fresh identity without resetting durable experimental budgets or unresolved
  entry exposure; the pending-entry retry guard remains active.
- **Combined production wiring:** real `SessionRunner.process_tick` coverage now
  combines restart, delayed fill, partial protective exit, second restart,
  reconciliation exception, recovered price, correctly-sized completion, and
  blocked new BUY admission.
- **Poller determinism:** regular-session callback expectations and intentional
  premarket suppression are independently frozen and covered.

## Verification

- Focused Task 79E-R2-3 + yfinance after the project-wide handover audit:
  `60 passed` in `5.71s`, exit code 0.
- Adjacent lifecycle/runner/broker-boundary/authorization/protective-exit
  suites: `132 passed` in `8.02s`, exit code 0.
- First full suite: `2529 passed, 1 failed, 1 skipped, 10 xfailed`; the sole
  failure showed the generic reconciliation rejection preceding the established
  unexpected-short rejection.
- After restoring short-specific precedence: focused confirmation `61 passed`.
- Pre-handover final full repository suite: **`2530 passed, 1 skipped, 10
  xfailed, 48 warnings`** in `1080.79s`; zero failures.
- Authoritative post-audit full repository suite, after all edits stopped:
  **`2530 passed, 1 skipped, 10 xfailed, 48 warnings`** in `942.54s`, exit
  code 0; zero failures.

Commands used for the post-audit verification:

```text
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_task79e_r2_activation_safety.py tests/test_yfinance_poller.py -q
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_task65_session_runner.py tests/test_task65b_lifecycle_probe.py tests/test_task76s_broker_boundary.py tests/test_task76s_protective_exit_eod.py tests/test_task77i_runtime_safety.py tests/test_task77i_end_to_end.py tests/test_task79e_r1_activation_safety.py tests/test_task79e_decision_engine_experimental.py tests/test_task79e_lifecycle_experimental.py -q
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/ -q
```

The prior two `test_yfinance_poller.py` failures are therefore closed as a
clock-isolation defect, not attributed to dependency drift.

## Product and safety boundaries

- Long-only PAPER execution boundaries are unchanged; no real capital, shorts,
  options, or leverage were added.
- Reconciliation and PAPER-entry blocks affect BUY admission only. Alerts,
  independent shadow tracking, monitoring, protective exits, and forced EOD
  exits remain outside that gate.
- Gemini remains additive informational enrichment and has no order authority.
- Strategy approval remains `UNVALIDATED`; experimental authorization remains a
  separate permission and is not profitability evidence.
- No `experimental_authorization.json` or `paper_entry_settings.json` exists.
- No live session, broker mutation, notification, holdout access, strategy
  tuning, or Task 80 activation occurred.
- Protected `talonx_quant/strategy.py`, `indicators.py`, `consumer.py`, and
  `config.py` were not changed.

## Verdict

**PASS for the bounded implementation task.** This is software-safety evidence,
not strategy validation, profitability evidence, or Task 80 launch authority.

## Build identity

- Feature commit: `fbc78f4`.
- Final docs follow-up: the commit containing the filled feature SHA; see
  `git log --oneline`.
