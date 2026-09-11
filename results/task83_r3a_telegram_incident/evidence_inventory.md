# Task 83-R3A evidence inventory

This inventory points to retained evidence. It does not reproduce credentials, environment
variables, account identifiers, or large logs. All repository paths are relative to the TalonX
root unless explicitly described as local installed-library evidence.

## Repository and committed evidence

| Evidence | Location or identity | Use |
|---|---|---|
| R3A starting checkpoint | commit `ee69cdb9604beb38e9f7b35646ab09bfa88f4dc6` and local tracking ref `refs/remotes/origin/research/talonx-strategy-validation` | Establishes synchronized retained Git metadata. |
| Defect/fix commit | `478723ad0a000c61804f19ab08d6f0a0b09d1c43` | Shows constructor-time `Bot` capture changed to poll-time module-symbol resolution. |
| Pre-fix listener | `478723ad^:talonx_dispatch/telegram_listener.py` | Shows `self._bot_factory = bot_factory or Bot`, production retry loop, and context entry. |
| Exact affected test | `tests/test_telegram_listener.py` | Shows fixture construction before `patch(...)`, fake async context, fake `get_updates`, post-return assertions, and exact node. |
| R2 explicit-factory tests | `tests/test_task83_r2_notification_session_integrity.py` | Explains why new tests remained isolated while the legacy patch seam escaped. |
| Interrupted adjacent output | `results/task83_r2_crash_recovery/raw_test_output/adjacent-codex-20260829-234726.txt` | Stops at 80%; no summary and no `.exitcode` companion. This file was preserved and not modified by R3A. |
| Successful post-fix adjacent output | `results/task83_r2_crash_recovery/raw_test_output/adjacent-codex-20260829-235510.txt` plus `.exitcode` | Records 358 passes and exit 0 after the repair. |
| Successful post-fix focused outputs | `results/task83_r2_crash_recovery/raw_test_output/focused-final-20260829-235603-run1.*` and `focused-final-20260829-235648-run2.*` | Records two post-fix focused passes. |
| Final suite | `results/task83_r2_crash_recovery/raw_test_output/full-suite-final-20260830-000151.*` | Records 2890 passes and exit 0 after the repair. |
| R2 claims | `results/task83_r2_crash_recovery/telemetry_polling_checkpoint.md` and `final_manifest_checkpoint.md` | Identifies the historical zero-external-activity statement and qualification claims. |

## Retained R2 task-log coordinates

The local Codex task titled `Fix notification session leakage`, task id
`01a04f80-72d5-7661-ba09-30138d15c5b9`, retains the orchestration evidence that quiet pytest output
could not contain. Relevant event ordinals are:

- 956: exact adjacent-suite command and its full explicit test-pattern list;
- 981, 998, 1011: process IDs/start times and unchanged 80% output observations;
- 1040 and 1042: decision to interrupt and failed/incomplete command completion;
- 1067/1080/1082: narrowed Telegram command, exact node identification after 51 passes, and
  interruption;
- 1102/1103: root-cause statement and bounded late-binding repair.

This task log may contain unrelated operational history and must not be copied wholesale into the
repository. The sanitized timeline in `incident_report.md` includes only incident facts.

## Exact adjacent command (sanitized structure)

The R2 task built a unique sorted file list from these patterns and invoked the venv Python with
`-X faulthandler -m pytest`, `-q`, `--disable-warnings`, and a system-temp `--basetemp`:

```text
tests/test_task82_runtime_isolation.py
tests/test_task80_p1_process_guard.py
tests/test_task81_reconciliation_admission.py
tests/test_task81_r1_*.py
tests/test_task81_r2_*.py
tests/test_task72o_eod_lifecycle.py
tests/test_task76s_protective_exit_eod.py
tests/test_task78i_*.py
tests/test_task77i_alert_shadow_independence.py
tests/test_task77i_notification_outbox.py
tests/test_task77i_observability.py
tests/test_task81_source_health_and_reporting.py
tests/test_task69p_telegram_piv_parity.py
tests/test_telegram_listener.py
tests/test_telegram_ping_safety.py
```

Output was redirected to the interrupted adjacent file, with a success/exit file written only after
Python returned. Because it was interrupted, the exit file was never created.

The narrowed command used the same venv Python and pytest options with only
`tests/test_telegram_listener.py` and `tests/test_telegram_ping_safety.py`, in verbose/long-traceback
mode. It named the exact active node before interruption.

## Installed-library evidence

These already-installed local files were read as text only:

- `.venv/Lib/site-packages/python_telegram_bot-22.8.dist-info/METADATA` — package name/version;
- `.venv/Lib/site-packages/telegram/_bot.py` — `Bot.__aenter__`, `initialize`, `get_me`, `_post`,
  `_do_post`, default base URL, and request URL construction;
- `.venv/Lib/site-packages/telegram/_version.py` — version tuple `22.8.0`.

No Telegram module was imported or instantiated during R3A.

## Integrity and limitations

The final SHA-256 hashes of all three new sanitized report files are reported by the R3A final
response after the committed bytes exist. Embedding a file's own ordinary SHA-256 inside that file
is self-referential and cannot be made stable; no fourth sidecar file is permitted by the task.

No retained packet capture, firewall/EDR network event, DNS trace, HTTP transport log, or Telegram
server receipt was found in the scoped evidence. Consequently, the investigation cannot prove that
a request left the machine or reached Telegram. That uncertainty cannot be retroactively removed.
