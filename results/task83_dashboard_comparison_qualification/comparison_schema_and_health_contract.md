# Task 83 — Comparison Schema & Health-State Contract

## Comparison identity (`talonx_compare.identity.ComparisonRecord`)

Every comparable unit of work from either pipeline is projected onto ONE
record with exactly these fields (§2):

| field | meaning | notes |
|---|---|---|
| `pipeline` | `ORIGINAL` \| `PIV` | never merged |
| `session_id` | the emitting pipeline's own session id | Original wire records carry none → `None`; never shared |
| `trading_date` | America/New_York calendar date `YYYY-MM-DD` | derived tz-aware from `event_time`; the only alignment bucket |
| `stage` | `warmup·quant·brain·core·dispatch·telegram·readiness·freshness·decision·shadow·lifecycle·reconciliation·eod` | frozen vocabulary |
| `symbol` | uppercased ticker, or `""` for stage-level aggregates | |
| `event_time` | ISO-8601 UTC — when the pipeline recorded it | |
| `source_bar_time` | ISO-8601 — the market bar the work derived from | `None` where the source does not carry it — see the unresolved IEX receipt-vs-source-time question; schema keeps the field so both timestamps can be shown later |
| `decision_id` | PIV decision id / Original alert id | or `None` |
| `decision_outcome` | decision/outcome label (`BUY`, `HOLD`, `REJECTED`, `READY`, …) | |
| `reason_codes` | tuple of reason-code strings | **order-normalised** (sorted) so re-reads hash identically |
| `execution_class` | `NONE·SIMULATED_PAPER·PIV_SHADOW·PIV_PAPER·EXPERIMENTAL` | disjoint; never summed |
| `payload_fingerprint` | sha256[:16] of the identity-bearing payload | **excludes** `pipeline`, `session_id`, and transport-noise timestamps, so an Original record and a PIV record for the same work hash identically and compare as *agreement* |

`_id` (persisted): `pipeline|session|date|stage|symbol|decision_id|fingerprint` —
the restart-safe dedup key. A late re-delivery of the same logical record maps to
the same `_id` and is recorded once (explicit `DUPLICATE` diagnostic).

## Alignment (`talonx_compare.alignment`)

- Keys strictly on `(trading_date, stage, symbol)`.
- `restrict_trading_date` hard-drops any record for another date **before** pairing —
  a cross-date comparison is structurally impossible.
- When multiple records share a key, the pick is deterministic: latest `event_time`,
  then highest fingerprint — a late arrival *replaces* an earlier projection, never dropped.
- Output order = sorted alignment key ⇒ re-running over the same inputs yields
  byte-identical `comparison.json` (`test_alignment_is_deterministic_and_tz_aware`).

## Divergence classes (`talonx_compare.divergence`, §2)

Precedence, first match wins:

| # | class | trigger |
|---|---|---|
| 1 | `SOURCE_UNAVAILABLE` | a required source's health is not OK on one side |
| 2 | `LATE_OR_MISSING_STAGE` | exactly one side has a record for the key |
| 3 | `FEED_INPUT_DIFFERENCE` | `source_bar_time` differs |
| 4 | `EXECUTION_MODE_DIFFERENCE` | `execution_class` differs (e.g. `SIMULATED_PAPER` vs `PIV_PAPER`) |
| 5 | stage-mapped | `decision_outcome` or `reason_codes` differ → `READINESS_DIFFERENCE` (warmup/readiness), `FRESHNESS_EXCLUSION` (freshness), `QUANT_GATE_DIFFERENCE` (quant), `DECISION_DIFFERENCE` (brain/core/decision), `ALERT_DELIVERY_DIFFERENCE` (dispatch/telegram) |
| — | agreement | identical fingerprint + execution_class → no divergence |

Every `Divergence.to_dict()` carries `AGREEMENT_IS_NOT_ALPHA` — operational agreement
is **not** profitability or alpha evidence (strategy UNVALIDATED, profitability UNDETERMINED).

## Health-state contract (`talonx_compare.health`, §3)

Exactly nine states — a missing/unreadable/stale/not-run/wrong-session source is
**never** rendered as a plausible zero:

| state | meaning | `trustworthy_zero` |
|---|---|---|
| `RUNNING` | process/loop live now | yes |
| `HEALTHY` | present, fresh, consistent (incl. a *verified* zero) | yes |
| `DEGRADED` | present with recorded problems / partial data | no |
| `STALE` | newest record older than the freshness bound (default 120 s) | no |
| `MISSING` | a required source is absent | no |
| `DISCONNECTED` | a live transport (Redis) could not be reached | no |
| `NOT_RUN` | nothing has run for this scope yet — **distinct from "zero activity"** | no |
| `UNREADABLE` | present but corrupt / unparseable | no |
| `WRONG_SESSION` | present, belongs to another session/date | no |

Each `SourceHealth` carries `detail`, `last_update` (ISO-8601, if the source has one),
`age_seconds`, and `scope` (the session/date the judgement is bound to). Dashboards
render the badge + timestamp + age next to every count.

`classify_json_file`, `classify_jsonl_stream`, `classify_redis`, and
`classify_pipeline_run` are the shared classifiers used by the collector and both
dashboards. `"Original: NOT_RUN"` is produced by `classify_pipeline_run(corroborated=False, live=False)`
and is asserted distinct from a healthy zero run.

## Execution-class / P&L separation (§3.9)

`SIMULATED_PAPER` (Original local paper), `PIV_SHADOW` (PIV shadow ledger),
`PIV_PAPER` (PIV Alpaca-paper lifecycle) and `EXPERIMENTAL` are always reported
under separate keys and are never summed into one P&L or agreement number. The
divergence classifier flags a cross-class pair as `EXECUTION_MODE_DIFFERENCE`,
never agreement.
