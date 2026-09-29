# 2026-09-29 — Telegram package deployment + SEC observability-only

Branch `feature/continuous-opportunity-engine`, start `b72297e`. Paper only. Discovery, evaluators, ingestion, V2 and
Original were not restarted. `OPERATOR_UNIVERSE_MUTATION_MODE` stays DRY_RUN.

## 1. Telegram package deployment (06:42–06:43Z, before PREMARKET)

**Scope:** notifier and promotion only, via the documented `declare-change` + `restart <component>`. The environment
was identical to the live supervisor's: deliver = 1, the `REGULAR_EXT` notify policy, `PAPER_SIGNAL`, Sentinel
enabled, `DRY_RUN`.

| Component | Old → new version | Boundary | Rule |
|---|---|---|---|
| notifier | 07045afceef8 → **4f669052a777** | **ROUTING_FIX** | `RULE:CONFIG_FINGERPRINT_CHANGED` (new `LAB_DELIVERY_POLICY` fp 46a2c622a7856f88); declaration #17 supplied the reason |
| promotion | 3dc2ce224318 → **f0c3b237b589** | **UI_ONLY** | `RULE:CONFIG_KEY_MAPPED+DECLARED` (`promotion_src` → UI_ONLY with declaration #18); `PROMOTION_POLICY` 4926c12e5eace04e unchanged |

**Proof after the restart.** Files: `2026-09-29_telegram_deploy/pre_deploy.json`, `post_deploy.json`, and
`telegram_verify_*.json`.
- **Health:** engine HEALTHY; exactly one worker (plus its Windows venv shim) each for notifier and promotion.
- **Notifier:** cursor 11452 = the store's max seq, so lag is 0. 0 events processed and 0 sent on restart.
- **Promotion:** PAPER_SIGNAL; cursor 11452; 0 evaluated, 0 queued, 0 sent.
- **No replay:** Lab outbox 613/613 SENT (no new rows) and Signal outbox 190/190 SENT (no new rows). Duplicate dedup
  keys: 0 in each.
- **Digest:** the `digests` table was created (additive) with 0 rows. Nothing historical was digested, because routing
  applies only to events decided after the restart.
- **Signal eligibility unchanged:** the promotion policy fingerprint is the same. Only `render`, `_ref` and
  `SIGNAL_FOOTER` changed (AST-verified in the 09-28 evidence).
- **New UX/routing on live traffic:** checked by `telegram_verify.py` after the first PREMARKET Lab events. The result
  is in §3.

## 2. SEC observability only (code; not deployed)

The capacity remediation committed on 09-28 (93ab219: global limiter, refresher I/O outside the lock, refreshing
during scans, reuse window) is **not** used by default. `TALONX_SEC_REFRESH_CAPACITY` selects the mode:

| Mode | Behaviour |
|---|---|
| `OBSERVABILITY_ONLY` (**default**) | Refresher identical to the live cf0cffb one: idle-only, one request at a time through `SecSubmissions.get` under the cache lock, no limiter, no reuse window. Only metrics are added. |
| `REMEDIATION_V1` | The 09-28 capacity changes. Opt-in; not deployed; not to be scaled until the universe study settles. |

**Metrics per scan** (`scans.funnel_json.sec_cache`). The rounded `max_served_age_s` is kept for compatibility:
- `max_served_age_raw` (6 decimals), `served_age_p95_raw`, `served_age_p99_raw`;
- `cache_fresh_count`, `sync_refresh_count`, `stale_fallback_count`, `no_data_count`;
- `stale_fallback_reasons` (`STALE_FALLBACK:{FETCH_ERROR|RATE_LIMIT|RATE_LIMIT_BACKOFF|TIMEOUT|OTHER}`),
  `stale_fallback_max_age_raw`;
- `count_age_ge_590`, `count_age_ge_595`, `count_age_ge_600`.

The discovery config fingerprint is unchanged in the default mode (`SEC_CATALYST_CACHE = BACKGROUND_REFRESH_V1`). The
opt-in mode records a distinct value.

**Tests:** `tests/test_sec_observability_only.py` (new) plus the existing SEC suites, 64 passing ×3.
- **Failure paths, in both modes:** a fresh hit; an expired entry with a successful synchronous refresh; an expired
  entry with a fetch error, timeout, 429 or an exception with an empty message, each surfacing as a stale fallback
  with its reason at exactly 600.0 s and counted in ≥590/595/600; the back-off period (stale, no request); 599.95 vs
  600.0 raw precision.
- **Mode-specific:**
  - OBSERVABILITY_ONLY matches the archived cf0cffb refresher **step for step**: served payloads, requests,
    errors, cache contents and stats over a 60-step mixed sequence with failures and refresher passes.
  - It holds the lock during refresher I/O like the live one, so no capacity change slipped into the default.
  - It never refreshes while discovery is active.

**Same-data parity** (`2026-09-29_sec_observability/sec_parity_observability_only.json`). Real SEC, throttled to
2 req/s. Scanned Monday's final after-hours snapshot (as-of 23:44Z, decision clock 23:59Z) three ways:
- R1: plain synchronous SEC;
- R2: OBSERVABILITY_ONLY refresher, cold;
- R3: the same refresher after refreshing.

| | R1 vs R2 | R1 vs R3 |
|---|---|---|
| Candidate identity / presence | 0 / 0 | 0 / 0 |
| Classification | 0 | 0 |
| Score | 0 | 0 |
| Catalyst | 0 | 0 |
| Lifecycle event type | 0 | 0 |
| Symbols / events / candidates checked | 5,652 / 455 / 455 | 5,652 / 455 / 455 |

Observability on R3: 467 cache-fresh, 0 sync refreshes, 0 stale fallbacks, raw max age 240.406 s, 0 lookups aged
≥590 / 595 / 600. There were 0 SEC errors and 0 back-offs over 4,203 requests. **This is not live acceptance:** SEC
stays INCONCLUSIVE until a live session is measured with these metrics.

**Deploying the SEC observability** requires a discovery restart and is not done here. The boundary would be a
code-only change with the config fingerprint unchanged, so it must be declared. Proposed class: REPORTING_ONLY-like
(no detection impact), recorded as **DATA_FIX** for consistency with the SEC cache history.

## 3. Live confirmation at 08:30Z (TELEGRAM_DEPLOYMENT = PASS)

Evidence: `2026-09-29_telegram_deploy/telegram_verify_0830.json` (read-only).

| Check | Result |
|---|---|
| Lab rows since deploy | 50, all in the new 🧪 format, all SENT |
| Duplicate dedup keys (Lab / Signal) | 0 / 0 |
| Every decision since deploy routed by the new policy (no legacy SELECTED rows) | yes (0 unrouted) |
| Event both immediate and digested | 0 |
| Notifier cursor lag | 0 |
| Signal rows since deploy | 0 (no REGULAR session yet; all rows will use the new format) |
| Digests | 0 so far (no digest-class event yet) |

**Observation (follow-up, not changed).** All 50 messages are `SENT_SETUP_INVALIDATED`, a burst at the first scans of
the new trading window. Setups carried from 09-28 are re-measured against the new reference close and fade below 1%.
They are HIGH-information by policy, but the burst itself is a noise candidate: for example, one roll-over summary
instead of individual messages for carried identities. Decide in a separate routing task.
