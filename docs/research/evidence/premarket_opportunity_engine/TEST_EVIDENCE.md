# Test evidence

## New tests

**`tests/test_premarket_research_engine.py`, 31 tests: 31 pass.**

| Area | Tests |
|---|---|
| Universe | deterministic, order-independent; eligible > 39; reason-coded exclusions (ETF, warrant, OTC, malformed, non-registrant, preferred); class shares and ADRs kept; V2 names eligible |
| Session | XNYS phases; EDT and EST opens; weekend and holiday; schedule starts one SIP-delay after 04:00 ET and ends before the open |
| Pre-market data | 15-min delay (`data_as_of`); only complete bars; batching, pagination and error reporting; rate limiter waits instead of exceeding |
| Features | causal gap, volume, activity and range position; staleness; missing, NaN and previous-session-absent data → not data-ready |
| Hard gates vs score | stale / sub-$1 / illiquid rejected; weak-but-valid symbols scored, never rejected |
| Scoring | frozen config; fingerprint pinned to `frozen_config.json`; deterministic, explainable; BULLISH / BEARISH / WATCH classification |
| Catalysts | acceptance ≤ decision time using the resolved SEC time; unresolved same-day acceptance excluded in replay, kept live |
| Alerts | new → upgrade → material update (time-gated) → invalidated; no duplicate on an unchanged re-scan; invalidated identity closed; direction flip; cap suppresses; cap keeps the highest scores |
| Isolation | router writes RESEARCH rows only, never TRADE_EVENT; disabled destination sends nothing; protected DBs refused; RESEARCH refuses to alias the primary chat; no trading/V2 identifiers in the package; no frozen-release module imports it |
| Post-open | OPEN / +30M / +1H / CLOSE, MFE/MAE, CONFIRMED / FAILED / INVALIDATED / PENDING, direction adjustment; outcomes never change alerts |
| No lookahead | a future price spike is invisible to an earlier scan and visible to a later one |
| Regression | strategy fp `e2acf6454789217e`, provider fp `ac5e51aa3599d6c9`, campaign `V2-PAPER-RC1`; preflight accepts the research lane but still rejects other runtime changes |

**`tests/test_session03_findings_hardening.py`, 30 tests: 30 pass.**

| Area | Tests |
|---|---|
| A2 time | ADC → `2026-09-23 11:00:20 UTC`; late-ingest true UTC; EST; spring-forward and fall-back transitions; evening filing crossing UTC midnight; ambiguous → filing date only; concise and expanded card rendering; card carries `filing_date` plus receipt separately; V2 does not import the resolver |
| A1 delivery | configured / runtime / effective matrix (6 cases); launcher and gate share one implementation; no secret read |
| A3 health | cause codes; recovery-only → `RECOVERY_PASS_DEGRADED`; incident still raised with causes; runner wiring |
| A4 / A5 `/ping` | shared-counter labels; queue breakdown separates live pending / failed / held / expired / drain |
| A6 | bounded drain times out without hanging; Operations-only; enqueue precedes drain |
| Allowlist | the Session-03 list is closed and strategy-free; branch shape accepted, other runtime rejected |

**NEW: 61 pass / 0 fail.**

## Updated existing tests (behaviour intentionally changed)

- `test_v2_final_release_acceptance.py::test_gate_discloses_intelligence_card_delivery_as_a_warning_not_a_blocker`. The old "off" case encoded the Session 03 bug: an implicit `--deliver --transport telegram` run is effectively ON. The test now covers the implicit, explicit-OFF and dry-run cases.
- `test_telegram_listener.py`: the Brain label now names its scope.
- `test_task132_ping_discovery_section.py`: the fixture table gains the real schema's `route` / `enqueued_at_utc` / `updated_at_utc`, and the assertion uses the new live-queue wording.
- `test_task69p_telegram_piv_parity.py`: collects every part of a split `/ping` reply. The pin itself is unchanged.

## Focused and regression runs

**FOCUSED:** 84 pass / 0 fail. These are the files touching the changed renderer, `/ping`, policy and critical-content gate, plus the Session 03 tests.

**REGRESSION:** every test file importing a changed module (Intelligence, release gate, prospective, notify, Telegram listener), 138 files plus the 2 new ones:
- **branch:** **1,765 pass / 9 fail / 6 skipped**;
- **clean `origin/main` `6bb89e1` worktree:** 1,695 pass / 9 fail / 15 skipped.

| Branch failure | Why it is not a regression |
|---|---|
| `test_ri3_operator::test_renderer_shows_end_to_end_fixture` | fails identically on base |
| `test_task117_release_rehearsal::test_bounded_release_rehearsal` | fails identically on base |
| `test_task118a_dashboard_message_count::test_immediate_and_digest_sends_count_messages_correctly` | fails identically on base |
| `test_task117_migration` (5) and `test_task117_deployment_rehearsal` (1) | environmental. They copy the untracked legacy `v2_lane.db` from the main checkout (md5 `cff00b0f…`, the known baseline value) and assert an older hash; on the base worktree the file is absent, so they skip. The md5 is unchanged by this work, which also shows the legacy ledger was not touched. |

**Base-only failures** (flaky or order-dependent on base, passing on the branch): 6.

**Full suite (5,423 tests):** not completed tonight. Both the branch run and the clean-base run stalled at the same point, around test #330 (`test_backtest_sample_data`, which spawns the documented backtest command as a subprocess), with no output for more than an hour. The stall is identical on base, so it isn't caused by this branch. It's a bounded follow-up.

## Live-path verification (read-only, real APIs)

| Check | Result |
|---|---|
| Alpaca SIP extended hours | verified (DATA_CONTRACT.md) |
| Universe build | 14,373 → 5,655 eligible |
| Live incremental source (replaying 09-23 as-of 12:00/12:05/12:10Z) | cold scan 135.6 s (daily + full pre-market window + about 150 SEC lookups); incremental scans **26.5 s and 23.6 s**, 29 Alpaca requests each, 0 limiter waits, 0 errors. The cadence is ≥ 300 s. |
| Causal replay | 41 scans, 9–14 s each once the SEC cache is warm; 59 Alpaca + 595 SEC requests; 0 errors |
| Release gate on branch HEAD (release env) | READY, 21 checks; strategy / provider fingerprints PASS; `lab_off` PASS; `authoritative_filing_date_readiness` PASS; `intelligence_card_delivery` WARN `configured=OFF runtime_requested_by_start=ON effective=ON` |
| Preflight `frozen_release_ok(HEAD, a56ec8c)` | `True`: "only docs/tests/pin/declared ops-hardening, release-fidelity-fix, Session-03-hardening and isolated research-lane files changed" |

## PR19 hardening pass (2026-09-23 night)

**NEW:** `tests/test_premarket_canary_hardening.py`, **44 pass / 0 fail**. It covers provider completeness and watermarks, the daily partial cache, duplicate bars, the single SIP delay, restart/resume, invalidation safety, SEC unknown and 429 handling, the cap, enqueued vs sent, stop flags, session edges, status/report and poll history.

**All pre-market + Session 03 tests:** 105 pass / 0 fail. **V2 test files** (`tests/test_v2_*.py`): 60 pass / 0 fail.

**Targeted regression** (every test file importing a changed module, plus the new files): **1,808 pass / 10 fail / 6 skipped**.

| Failing test | Classification | Reproduction |
|---|---|---|
| `test_ri3_operator::test_renderer_shows_end_to_end_fixture` | PRE_EXISTING | fails identically on the clean `origin/main` worktree |
| `test_task117_release_rehearsal::test_bounded_release_rehearsal` | PRE_EXISTING | fails identically on clean main |
| `test_task118a_dashboard_message_count::test_immediate_and_digest_sends_count_messages_correctly` | PRE_EXISTING | fails identically on clean main |
| `test_task117_migration` (5) and `test_task117_deployment_rehearsal` (1) | ENVIRONMENTAL | They require the untracked legacy `v2_lane.db` to have an older md5. The main checkout's copy is `cff00b0f…` (unchanged by this work); on the base worktree the file is absent and they skip. |
| `test_task118a_checkpoint_daemon_restart::test_a_real_session_loop_exits_immediately_with_a_stale_stop_flag` | ENVIRONMENTAL (timing under load) | Failed once while the network-heavy replay ran concurrently; passes 3/3 in isolation on the branch **and** 3/3 on clean main |

**Replay equivalence.** The 2026-09-23 replay was re-run on the hardened code (`results/premarket_research/replay_2026-09-23_hardened`):
- The scan funnels are identical scan for scan.
- Candidates (141, with the same states, first-alert times and reference prices) and outcomes are **identical**.
- 223 alert events. Exactly one differs: a transient SEC fetch failure for NWG during the re-run was correctly labelled `catalyst lookup incomplete: SEC lookup failed`. Its score was 46.5 instead of 61.5 (catalyst points unknown → 0, exactly as the frozen scoring treats NONE). Same WATCH classification, same candidate.

**Full suite:** not completed, for the same reason as before. It stalls on clean main too, in `test_backtest_sample_data`.
