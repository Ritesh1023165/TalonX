# Task 83-R3A Telegram test-escape incident report

## Verdict and scope

`INCIDENT_CHARACTERIZED`

This is a bounded, evidence-only reconstruction. No test, listener, runtime, service, broker, or
library code was executed for R3A. The historical uncertainty about packet transmission and remote
receipt cannot be retroactively removed.

## Starting checkpoint

- Branch: `research/talonx-strategy-validation`
- Required and observed local HEAD: `ee69cdb9604beb38e9f7b35646ab09bfa88f4dc6`
- Locally retained `origin/research/talonx-strategy-validation` ref:
  `ee69cdb9604beb38e9f7b35646ab09bfa88f4dc6`
- Tracked working tree: clean.
- Protected Quant files: no staged or unstaged diff.
- Processes: no process named `python`, `pythonw`, `pytest`, or `TalonX` at the R3A checkpoint.
- Stashes preserved: Task 83-R2 stash at `stash@{0}` and both Task 56 stashes at `stash@{1}` and
  `stash@{2}`.

The remote-tracking equality above is based on already-retained local Git metadata. R3A did not
fetch because an investigative network call was forbidden.

## Exact retained timeline

All wall-clock times below are Europe/London (BST, UTC+01:00) on 2026-08-29. UTC event times are
also supplied where the retained Codex task log provides them.

1. At 23:47:23.876 BST (22:47:23.876Z), the R2 task issued the adjacent-suite command shown in the
   evidence inventory. It used `.venv\Scripts\python.exe`, `-X faulthandler`, and `-m pytest`, with
   a system-temp `--basetemp`, quiet output, and warnings disabled.
2. The launcher and worker processes both started at 23:47:26 BST. Retained process inspection
   identified the venv launcher as PID 7224 and the Python 3.12 worker as PID 18164. The retained
   pytest logs identify the environment as Python 3.12.10, pytest 9.1.1, and
   `C:\workspace\TalonX\.venv\Scripts\python.exe`.
3. The durable output reached 80% and was last modified at 23:48:14 BST. It never printed a test
   summary or normal exit status.
4. At 23:49:07, 23:49:46, and 23:50:24 BST the same two Python processes still existed while the
   output stayed unchanged. At 23:51:07 the run was treated as a possible long timeout. At
   23:52:11.519 it was declared hung/incomplete and deliberately interrupted. The command ended at
   23:52:11.728 with failed tool status. No `.exitcode` companion exists, so no normal pytest exit
   is evidenced.
5. Static ordering narrowed the late-suite area. A two-file non-Telegram subset completed with 26
   passes. At 23:52:43.581 BST (22:52:43.581Z), R2 started a verbose narrowed command for
   `tests/test_telegram_listener.py` and `tests/test_telegram_ping_safety.py`.
6. That command passed its preceding 51 tests, then stopped at the exact node
   `tests/test_telegram_listener.py::test_poll_forever_drains_backlog_then_handles_new_updates`.
   The R2 task recorded the identification at 23:53:20.781 BST and interrupted the narrowed run;
   its command ended with failed status at 23:53:21.125. It did not exit normally.
7. Source inspection found the fake-bypass defect. R2 changed the listener to late-resolve the
   module symbol and subsequently reran qualification successfully. That fix is commit
   `478723ad0a000c61804f19ab08d6f0a0b09d1c43` and is already part of the R3A starting HEAD.

The quiet adjacent log does not itself print the active node. The exact node is established by the
retained verbose isolation immediately afterward, the 51 preceding passes, and the same pre-fix
source path. Both the adjacent run and the narrowed isolation entered the defective test path and
were interrupted; neither has a normal success exit record.

## Exact fake bypass and first production call

The shared `listener` pytest fixture constructed `TelegramReplyListener` before the test's
`with patch("talonx_dispatch.telegram_listener.Bot", ...)` block ran. At the pre-fix revision,
the constructor executed:

```text
self._bot_factory = bot_factory or Bot
```

No explicit factory was supplied by that fixture, so the constructor stored the then-current real
`telegram.Bot` class. Patching the module symbol later could not change the already-stored class.
When the test awaited `listener.run()`, production `_poll_forever()` called the stored class and the
first escaped production boundary was:

```text
telegram.Bot(token=<test placeholder>).__aenter__()
```

The expected fake was the `unittest.mock.patch` replacement of
`talonx_dispatch.telegram_listener.Bot`, configured to return an async context whose entered value
was an `AsyncMock`. Its fake `get_updates` side effect would drain one update, handle one live
update, then call `listener.stop()` on the third call. Because the real class had already been
captured, none of those fake calls or the stop action was reached.

The test had no assertion or fail-closed guard between fixture construction and `await
listener.run()`. Assertions occurred only after `run()` returned. Production `run()` catches every
exception from `_poll_forever()`, sleeps with reconnect backoff, and retries until stopped. A failed
real Bot initialization therefore appeared as a hang instead of failing the test immediately.

## Installed Telegram library path

Read-only metadata identifies the installed package as `python-telegram-bot 22.8`. The local source
path is `.venv/Lib/site-packages/telegram/_bot.py`; it was read as text and was not imported.

The installed code path is deterministic:

```text
Bot.__aenter__
  -> Bot.initialize
     -> initialize both request objects
     -> Bot.get_me
        -> Bot._post("getMe")
           -> Bot._do_post
              -> request.post(base_url + "/getMe")
```

The default base URL is `https://api.telegram.org/bot` with the supplied token appended, so the
likely Bot API method was `getMe` and the sanitized endpoint form was
`https://api.telegram.org/bot<test-placeholder>/getMe`.

`__aenter__()` must finish initialization before yielding the bot to the listener body. The retained
run never reached the fake's first `get_updates`, the listener backlog drain, the live polling loop,
message handling, or notification dispatch. The escaped path is therefore an initialization/auth
probe, not a `sendMessage` attempt and not an inbound polling request.

## External-activity classification

These classifications concern the identified R2 escape executions only.

| # | Statement | Classification | Evidence-bounded reason |
|---:|---|---|---|
| 1 | A network request was attempted by local Python code. | `CONFIRMED` | The real `Bot` async context was entered; installed `__aenter__()` unconditionally initializes and invokes `get_me()`, whose implementation calls the HTTP request boundary. This confirms a local code-level attempt, not transmission. |
| 2 | A request left the machine. | `POSSIBLE_NOT_PROVABLE` | No packet capture, firewall record, HTTP transport log, or equivalent retained evidence exists. |
| 3 | Telegram received the request. | `POSSIBLE_NOT_PROVABLE` | Remote receipt cannot be derived from the local code path or a hung process. |
| 4 | Telegram authenticated the placeholder token. | `DISPROVED` | The incident used the committed test placeholder, not a valid credential; the fake stop path was never reached and no successful initialization is retained. |
| 5 | `getMe` succeeded. | `DISPROVED` | A successful `getMe` would complete the context entry and reach listener backlog drain; the retained node instead remained in the pre-body retry path until interrupted. |
| 6 | `sendMessage` was called. | `DISPROVED` | The escaped listener path contains no send call before initialization, and context entry never completed. |
| 7 | A Telegram notification was delivered. | `DISPROVED` | No send method or notification-dispatch path was reached. |
| 8 | The inbound polling loop started. | `DISPROVED` | `get_updates`, backlog drain, and the loop occur only after successful context entry, which was not reached. |
| 9 | A valid Telegram credential was accessed. | `DISPROVED` | The exact fixture supplied a committed test placeholder directly; this path did not read a Telegram credential from environment or configuration secrets. |
| 10 | Any Alpaca, Gemini, Redis, broker, or TalonX runtime activity occurred. | `DISPROVED` | The retained command was a bounded pytest file list, the exact active node was a Telegram listener unit test with mocks, and the retained process set was the pytest Python pair; no such runtime boundary is present in the escaped path. |

`CONFIRMED` in item 1 does not establish items 2 or 3. It describes local execution reaching the
library request operation. The historical network boundary remains unknowable from retained
evidence.

## Root cause and qualification impact

Immediate cause: eager constructor-time capture of a patchable production class. The existing fake
patched the correct module symbol but too late to affect the stored reference. The test did not fail
closed because it relied on post-return mock assertions and had no non-loopback network guard.
Production `run()` converted initialization errors into reconnect/retry behavior, so the test
appeared to hang.

Earlier R2 focused tests did not expose the weakness because the new polling-boundary tests supplied
an explicit `bot_factory`; tests that exercised handler logic did not call the production context;
and the no-op test returned before constructing a bot. The affected legacy polling test was reached
only in the later adjacent set. After the late-binding repair, the exact test, adjacent suite,
focused suites, and final repository suite completed successfully according to their retained logs.

Preserved R2 claims:

- session/date notification telemetry partitioning, same-session restart preservation, historical
  evidence handling, atomic counter updates, and fail-closed telemetry writes;
- optional real `get_updates` boundary instrumentation when an explicit fake is injected;
- disabled-by-default PIV ownership and zero counters;
- the 13/13 rehearsal matrix, committed-blob verification, final manifest verification, protected
  Quant-file status, and post-fix passing qualification counts;
- the final committed implementation's late-binding fake seam and successful post-fix suites.

The single invalidated R2 claim is the historical claim of **zero external activity/no external
Telegram call during Task 83-R2 execution**. It must be replaced with: local Python definitely
reached the Telegram library's `getMe` request operation with a test placeholder; whether bytes left
the machine or Telegram received them is not provable. No notification send is implicated.
