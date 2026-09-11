# Single supervised Intelligence process (Task 117 final-activation A3)

## What was wrong

`docs/audits/task117_overnight_release_closure/deployment_candidate.md`'s
step 3 described a *separate, manually-run* `python -m
talonx_ingest.intelligence.service poll --duration 3600 --send
--i-understand-external-send` process, run outside `prospective start`. That
would be a **second, independently-configured Intelligence
poller/drainer** racing the one the supervisor already starts — exactly the
risk the review flags (duplicate producers, an uncoordinated second Telegram
poller, configuration that "survives" only by luck of which process wins a
race).

## The single supervised component already exists

`talonx_ops/supervisor.py::default_talonx_components()` has, unconditionally
(no flag gates it off), an `"intelligence"` `ComponentSpec`:

```python
intel_argv = [py, "-m", "talonx_ingest.intelligence.service", "poll"]
if with_backfill:
    intel_argv.append("--with-backfill")
ComponentSpec(name="intelligence", argv=intel_argv,
             classification=Classification.OPTIONAL, start_order=30, ...,
             readiness_probe=_intelligence_ready_probe,
             restart_policy=RestartPolicy(max_restarts=None, backoff_base_s=15.0, backoff_cap_s=900.0),
             graceful_stop_s=30.0)
```

`talonx_ops.supervisor run` (spawned by `prospective start` → `_start_stack_locked`
as `sup_argv = [py, "-m", "talonx_ops.supervisor", "run"]`) calls
`default_talonx_components(include_dashboard=..., with_backfill=...)` with
`include_v2` never set (stays `False` — Task 112T T1: V2 is spawned
separately, never via `supervisor include_v2`). There is exactly **one**
Intelligence producer under `prospective start`, today, with no code change
needed to create it.

## Configuration propagation — verified, not assumed

`talonx_ops.supervisor.SubprocessRunner.spawn()`:
```python
env = dict(os.environ)
if spec.env: env.update(spec.env)
...
subprocess.Popen(spec.argv, cwd=..., env=env, ...)
```
Every child (including `intelligence`) inherits the **supervisor process's
own environment**, which is itself inherited from whatever launched it
(`prospective start`, which inherits from the operator's shell via
`talonx_ops/prospective/proc.py::_spawn`'s `full_env = {**os.environ,
**(env or {})}`). So the reviewed delivery configuration
(`TALONX_INTEL_DELIVER_CARDS`, `TALONX_INTEL_DRY_RUN_DELIVERY`, per-cycle
limit, timeout, digest interval, age-cutoff) reaches the supervised child by
ordinary env-var inheritance — exported **once**, before `prospective
start`, in the same shell.

Verified with a real spawned subprocess through the exact same
`SubprocessRunner.spawn()` path (`test_task117_supervised_intelligence.py`):

```
monkeypatch.setenv("TALONX_INTEL_DELIVER_CARDS", "1")
monkeypatch.setenv("TALONX_INTEL_DRY_RUN_DELIVERY", "0")
... runner.spawn(probe_spec) ...   # a real subprocess
# child's own os.environ actually contains "1" and "0"
```

## Acceptance

| requirement | evidence |
|---|---|
| Exactly one Intelligence producer/drainer | `default_talonx_components()` has exactly one `"intelligence"` spec (`test_exactly_one_intelligence_component_no_duplicate`) |
| No additional Telegram poller | runbook step 3 rewritten to remove the standalone manual `poll --send` process; the supervised component's argv never carries `--send`/`--i-understand-external-send` (`test_intelligence_argv_never_includes_a_second_send_flag`) — enablement is config-driven (env vars), not a baked-in CLI flag on an always-running process |
| Configuration survives supervised restart | the supervisor process's own env does not change across a `RestartPolicy` restart of its `intelligence` child — `SubprocessRunner.spawn()` re-reads `os.environ` fresh each time from the SAME long-lived supervisor process, so a restarted child gets the identical env |
| Delivery readiness appears in status/dashboard | `_intelligence_ready_probe()` (heartbeat freshness, `AuthoritativeReadModel().intelligence_producer()`) for process liveness; the dashboard's Intelligence → **Card delivery** block (added this release, see `docs/audits/task117_overnight_release_closure/dashboard_acceptance.md`) for actual delivery state (by-state counts, sent-today, last-sent) |
| Canonical close owns and stops this component | `prospective close` → `stop_stack` reaps the supervisor's whole owned tree (`_owned_tree`, descendants found via `psutil.Process(pid).children(recursive=True)`, ownership-verified by create-time + cmdline) — the `intelligence` child is a descendant of the supervisor pid and is torn down with everything else; nothing separate to remember |
| Missing required delivery configuration is visible, not silently ON | with either `TALONX_INTEL_DELIVER_CARDS` or `dry_run_delivery`-equivalent unset, the runner's `deliver_cycle` summary reports `mode="disabled"` every cycle (logged) and the dashboard's Card-delivery note explains "0 SENT with a healthy poll loop = delivery disabled or transport not configured" — never presented as an ambiguous or default-ON state |
| Intercepted transport, isolated state, nothing sent externally in this verification | `test_task117_supervised_intelligence.py`'s probe process never imports or touches `talonx_dispatch`; it only proves env-var propagation |

Tests: `tests/test_task117_supervised_intelligence.py` (4/4 pass).

## Runbook change

`docs/audits/task117_overnight_release_closure/deployment_candidate.md` §3
rewritten: the backlog drain (3a) is unchanged; the enablement step (3b) now
sets the env vars **before** `prospective start` (step 2) instead of running
a separate `poll --send` process after it.
