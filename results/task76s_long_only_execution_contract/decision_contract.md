# Task 76S — Stage 1: Decision Contract

Module: `talonx_piv/decision_contract.py`. Pure, standalone, no protected-file/EventBus/broker
dependency. See `remaining_integration_work.md` for what is deliberately NOT wired into the live
`decision_engine.py` signal loop in this task.

## Kept distinct (never conflated)
| Concept | Type | Notes |
|---|---|---|
| Market view | `MarketView` (BULLISH/BEARISH/NEUTRAL) | What was observed, independent of position. |
| Recommendation | `Recommendation` (BUY/HOLD/SELL_TO_CLOSE/NO_TRADE) | What the product wants next. |
| Strategy approval | `StrategyApprovalStatus` (UNVALIDATED/APPROVED) | Independent of today's market view. |
| Execution eligibility | `ExecutionStatus` | Whether the recommendation may reach the broker now. |
| Execution result | *(not part of this contract)* | Recorded separately by `lifecycle.py`. |

## Required behaviour table — implementation mapping
| Condition | `decide()` branch | Recommendation | reason_codes (example) |
|---|---|---|---|
| Approved, eligible bullish setup; no holding | `not has_open_long`, BULLISH, READY, APPROVED | `BUY` | `ELIGIBLE_APPROVED_BULLISH_SETUP_NO_HOLDING` |
| Existing long; no approved exit condition | `has_open_long`, `not approved_exit_condition` | `HOLD` | `EXISTING_LONG_NO_APPROVED_EXIT_CONDITION` |
| Existing long; approved deterministic exit condition | `has_open_long`, `approved_exit_condition` | `SELL_TO_CLOSE` | `EXISTING_LONG_APPROVED_EXIT_CONDITION` |
| Bearish view; no holding | `not has_open_long`, view != BULLISH | `NO_TRADE` | `BEARISH_OR_NEUTRAL_VIEW_NO_HOLDING` |
| Unvalidated strategy | `not has_open_long`, BULLISH, READY, status != APPROVED | `NO_TRADE` | `STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION` |
| Data insufficient for entry | `not has_open_long`, BULLISH, readiness != READY | `NO_TRADE` | `DATA_INSUFFICIENT_FOR_ENTRY:<status>` |
| Valid BUY but PAPER entry disabled | recommendation resolves to `BUY`, `paper_entry_enabled=False` | **`BUY` (unchanged)** | `+PAPER_ENTRY_DISABLED_FOR_TICKER`, `execution_status=ENTRY_BLOCKED_PAPER_DISABLED` |

## The one hard invariant
`SELL_TO_CLOSE` is reachable **only** through `has_open_long and approved_exit_condition` — never from
`market_view` alone. A bearish observation while holding, with no authorised exit condition, resolves
to `HOLD`, not a new/untested exit rule (verified by
`tests/test_task76s_decision_contract.py::test_bearish_view_while_holding_without_exit_condition_is_hold_not_a_new_exit_rule`).

## Strategy approval default
No production strategy-approval mechanism exists anywhere in this repository (Stage 0 finding). Every
real caller must therefore construct `strategy_approval_status=StrategyApprovalStatus.UNVALIDATED` —
there is no code path in `decision_contract.py`, `cli.py`, or `decision_engine.py` that ever sets
`APPROVED`. `APPROVED` is exercised only by `PaperEntrySettings.for_test`-style isolated test fixtures,
labelled `TEST_FIXTURE_ONLY — NOT ALPHA EVIDENCE`.

## Levels are never invented
`entry_price`/`stop_price`/`target_price`/`horizon` are plain optional passthrough fields — `decide()`
never computes or infers them; a caller either supplies them (from an existing `QuantSignal` or a
probe's fixed levels) or leaves them `None`.
