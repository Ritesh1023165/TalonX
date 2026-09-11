# Task 82 — Original/PIV Runtime Isolation

## Scope

This task isolates the existing Original application from the PIV validation
runtime. It does not launch either application, change strategy behavior,
enable experimental authorization, access holdout data, or change broker
permissions.

## Ownership contract

| Resource | Original | PIV |
|---|---|---|
| Redis keys | `TALONX_REDIS_URL` (default DB 0) | `TALONX_PIV_REDIS_URL` (default DB 1) |
| Redis Pub/Sub | Existing `talonx:*` channels | Required `talonx:piv:*` namespace |
| Quant persistence binding | Existing `TALONX_QUANT_DB_PATH` | `<PIV state_dir>/piv_quant.db` by default |
| Runtime evidence | Existing Original stores/logs | `TALONX_PIV_STATE_DIR` |
| Telegram outbound | Original only | Disabled and rejected by isolation validation |
| Telegram inbound polling | Original only | Disabled and rejected by isolation validation |
| Process role | One Original | One `--isolated-parallel` PIV |

Redis database selection alone is insufficient because Redis Pub/Sub ignores
the selected database. PIV therefore requires both a different database and
different channel names. The reused `QuantScanner` receives these bindings
through an explicit `QuantConfig`; protected Quant strategy files are not
modified.

The current in-process PIV `QuantScanner` still operates without a
`QuantStateStore`; therefore it does not presently write that SQLite file.
The isolated path is nevertheless explicit in its `QuantConfig`, preventing a
future persistence enablement from silently selecting Original's database.

## Fail-closed process policy

- A second Original process is rejected.
- A second PIV process is rejected.
- PIV may coexist with Original only after PIV isolation validation passes.
- Original permits a PIV peer only when its command line carries the
  `--isolated-parallel` marker required by the PIV CLI.
- Process-enumeration errors, malformed rows, unknown roles and unclassified
  legacy output all block role-aware startup.
- Existing broker execution-ownership locking remains independent and
  authoritative for PAPER broker mutations.

## Session identity

The credential-free configuration hash now includes the resolved PIV state
directory, PIV Quant path, Redis endpoint identity (scheme/host/port/database),
all isolated channel names, namespace and Telegram-disabled status. A restart
with changed bindings therefore cannot silently reuse the prior session
identity.

## Explicitly deferred

- Original/PIV dashboard comparison and source-health presentation.
- Offline parallel rehearsal and fault injection.
- Any PAPER pilot or live-session launch.
- Enabling a durable PIV `QuantStateStore` (the isolated path is reserved;
  current PIV Quant counters/buffers remain in memory plus existing PIV ledgers).
- Strategy tuning, alpha research conclusions or profitability claims.
