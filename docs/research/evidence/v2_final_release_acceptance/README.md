# FINAL V2 RELEASE ACCEPTANCE — requirement-by-requirement release gate

**Verdict: `V2_RELEASE_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`** (paper only) — **`READY_TO_FREEZE`** at the acceptance commit.
Starting HEAD `cb010de`. Nothing was launched, frozen or sent. Production `v2_lane.db` md5 unchanged (`cff00b0f…`).

| Item | Result |
|---|---|
| Requirement matrix (38) | 34 PASS / 4 BOUNDED_FOLLOWUP / 0 FAIL / 0 blocking — `requirement_matrix.md` / `.csv` |
| Open OPS findings | 0 RELEASE_BLOCKING — `ops_classification.csv` |
| Release gate (real environment) | READY, 17 checks (16 PASS, 1 WARN: legacy ledger without campaign record) — `release_gate_real_environment.json` |
| Acceptance tests | 31 new (`tests/test_v2_final_release_acceptance.py`), all pass under the network guard |
| Carried failures | 16, every one reproduced on `cb010de` — `test_results.txt` |
| Strategy fingerprint | `e2acf6454789217e` unchanged; contract `ac5e51aa3599d6c9` unchanged |

## Key finding (OPS-027) and the fix
The qualified SIP provider from PQ-2B was **unreachable from the operator launch path**: `prospective start` and `talonx_v2.run` defaulted to stale `csv` pricing.
An explicit gated profile fixes this without touching research/replay defaults: `--release` (`talonx_v2/release_gate.py`) forces SIP + `V2_RELEASE_PRICE_CONTRACT@1`,
requires `--deliver --transport telegram`, refuses to start unless the read-only gate is READY, and `--force` never bypasses it. `V2Service(release_mode=True)` also refuses any non-SIP mode.

## Other fixes (all tiny, no strategy change)
* Dashboard health override could mask `DOWN`/`STARTING`/`STARTUP_FAILED` with `UNKNOWN` (fixes a baseline failing test).
* Alert wording claimed "market-on-open"; now: daily-bar OPEN = provider first eligible trade, **NOT** the official opening-auction price.
* `/ping` V2 section now shows release mode, provider contract (or "NOT the release contract"), market-data health, campaign, account blocks, EXIT_UNRESOLVED.
* Stale whole-share expectation in `test_task117_overnight_journey` corrected (290,001.0).

## Explicit statements
* AUTHORITATIVE RELEASE PROVIDER: Alpaca Market Data v2 · FEED: `sip` · ADJUSTMENT: `split` · RELEASE PROVIDER CONTRACT: `V2_RELEASE_PRICE_CONTRACT@1` · FINGERPRINT `ac5e51aa3599d6c9`
* RELEASE PRICING MODE: `sip` · CSV DEFAULT USED FOR RELEASE: NO
* Entry OPEN = SIP daily `o` (first eligible trade) — NOT the official opening-auction print; exit CLOSE = official closing cross.
* TalonX Signal / Sentinel READY (validated for the active config); TalonX Lab OFF. `/ping` owner: `talonx_dispatch/telegram_listener.py`.
* V2 STRATEGY FINGERPRINT `e2acf6454789217e`; STRATEGY RULES CHANGED: NO.
* V2 PROFITABILITY: UNPROVEN. PROFITABILITY RESEARCH PERFORMED: NO.
* FULL-DAY PAPER SESSION: NOT_STARTED · PROSPECTIVE VALIDATION: NOT_STARTED · REAL-MONEY TRADING: NOT_ENABLED.

## Bounded follow-ups (none block release)
Requirement rows 16 (IDENTITY_MISMATCH has no detector), 17 (S10-20 reconciliation scope not individually traced), 29 (dashboard presentation), 30 (OPS-016 five-state readiness + external watchdog).
OPS: 002, 004, 005 (rate-limit stress unmeasured), 006, 010, 011, 013, 016. OPS-017 left untouched.

## Freeze-step items (operator)
1. Update `RELEASE_SHA_EXPECTED` (`0d52e7c`) or pass `--expected-sha <RC SHA>`.
2. Decide: continue the legacy $300k campaign vs a new campaign (not decided here).

## Files
`requirement_matrix.md|csv`, `ops_classification.csv`, `release_candidate_configuration.json` (prepared, NOT frozen), `release_gate_real_environment.json`, `test_results.txt`, `repository_state.txt`.
