# Overnight hardening + broad-universe pre-market research engine (2026-09-23)

| | |
|---|---|
| **Branch** | `feature/premarket-broad-opportunity-engine`, started from `main` `6bb89e1` (PR #18 merged 20:51Z) |
| **Strategy fingerprint** | `e2acf6454789217e` before and after |
| **Provider fingerprint** | `ac5e51aa3599d6c9` before and after |
| **V2 boundary** | 39-name execution scope unchanged. Campaign `V2-PAPER-RC1` untouched: no ledger, outbox or state writes. |
| **Release gate on branch HEAD** | READY 21/21 (`intelligence_card_delivery` is WARN and disclosed). `repo_head_matches_release` accepts the branch through closed allowlists. |
| **Real-money capability** | None added. The research lane has no order, intent or paper-trading path (tested). |

## Commits

| Commit | What |
|---|---|
| `6888475` | Session 03 findings A1–A6 (see SESSION03_FINDINGS_FIXES.md) |
| `fb673f5` | `talonx_premarket` engine plus `PREMARKET_RESEARCH_V1` config pinned **before** the replay (fingerprint `62ba413daf85e674`) |
| `f4bf44e` | Per-session alert cap applied in score order (found in replay candidates before outcomes; config unchanged); performance |
| (this commit) | `--env-file`, evidence, runbook |

## Documents

| File | Content |
|---|---|
| [SESSION03_FINDINGS_FIXES.md](SESSION03_FINDINGS_FIXES.md) | A1 effective delivery state (FIXED), A2 card UTC time (FIXED), A3 degraded root cause (established; cause codes), A4 legacy Quant (EXPECTED_UNUSED_LEGACY_PATH), A5 queue (no defect; clarified), A6 SHUTDOWN (FIXED, bounded) |
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | Alpaca SIP extended hours verified; 15-min subscription delay; IEX has no extended hours; limits, pagination, stale semantics |
| [UNIVERSE.md](UNIVERSE.md) | 14,373 total → 5,655 eligible, with reason-coded exclusions |
| [SCORING.md](SCORING.md) | Features, hard gates, fixed weights, classification |
| [ALERT_CONTRACT.md](ALERT_CONTRACT.md) | Research-only semantics, dedup and state machine, isolated RESEARCH routing, post-open outcomes |
| [SHADOW_REPLAY_2026-09-23.md](SHADOW_REPLAY_2026-09-23.md) | Causal replay, comparison with Session 03, ADC, legacy Quant, outcome table |
| [TEST_EVIDENCE.md](TEST_EVIDENCE.md) | Tests and regression comparison |
| [PR19_HARDENING_REVIEW.md](PR19_HARDENING_REVIEW.md) | Final review: 2 CRITICAL + 4 HIGH + 6 MEDIUM findings fixed (provider watermark, inclusive `end` duplication, false invalidation, restart duplicates, enqueued≠sent, …) |
| [TOMORROW_CANARY_RUNBOOK.md](TOMORROW_CANARY_RUNBOOK.md) | Exact commands for 2026-09-24 |

## Readiness: `READY_WITH_BOUNDED_FINDINGS`

**Ready:**
- the universe loads;
- pre-market SIP data is verified;
- scans finish well inside cadence;
- rate limits are respected;
- the replay funnel is non-zero;
- routing is isolated;
- dedup and post-open tracking work;
- V2 is unchanged.

**Bounded findings:**
- **R1:** the V1 cap is used up by the first scan. It was not tuned; a pre-registered V1.1 is proposed.
- **Live data is delayed 15 min** by the free SIP entitlement. Alerts are labelled as delayed.
- **RESEARCH Telegram cannot be enabled** until a distinct research chat is configured. The default canary is record-only.
- **Experimental lane:** its consumer silently failed to subscribe on 09-22 (root cause undetermined; separate follow-up).
- **Intelligence recovery pass:** backlog comparison fetches hit SEC 429s (diagnostics added; back-off follow-up).
- **Full suite not run end-to-end tonight.** It hangs on the same backtest subprocess test on clean `main` as on this branch. The targeted regression is in TEST_EVIDENCE.md.

**Not done, by design:** no canary started, no real money, no change to frozen V2, and no tuning from replay outcomes.
