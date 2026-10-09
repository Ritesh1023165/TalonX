# Finding: Form 144 earns generic "other filing" catalyst points (recorded only; NOT changed)

**Status.** OPEN and unchanged. This task made no change to scores, ranking, thresholds or admission.

## Exact current rule

1. **`talonx_premarket/catalysts.evaluate`.**
   - Each SEC filing for the symbol, filed between the prior session and the scan day (causally accepted), is split
     into two groups:
     - **strong:** forms in `STRONG_FORMS` (8-K/8-K/A, 6-K, S-1/S-3/F-1/F-3 and amendments, 424B1–B5, SC 13D(/A),
       425, DEFM14A, SC TO-T, SC 14D9);
     - **other:** every remaining form, including **144**, 3, 4, ARS, DEF 14A and so on.
   - `strength` is set as follows:

     | Strength | Condition |
     |---|---|
     | `STRONG` | any strong filing, or ≥ 2 distinct insider code-P buyers in 30 days |
     | `OTHER` | any *other* filing, or 1 insider buyer |
     | `NONE` | otherwise |

2. **`talonx_premarket/scoring.score`.** `q_cat = {"STRONG": catalyst_strong, "OTHER": catalyst_other}`, where
   `catalyst_strong = 1.0` and `catalyst_other = 0.6` (`talonx_premarket/config.py`). The catalyst weight is 15, so
   **OTHER = +9.0 points** and STRONG = +15.0.
3. **`classify`.** BULLISH_SETUP requires a total score ≥ 60, together with a move ≥ 3% and window-to-date dollar
   volume ≥ $500k. The 9 points therefore count towards crossing the setup threshold.

**Observed on 2026-10-09** (generation-time records only):
- `1 other SEC filing(s): 144`: PANW and XYZ, each `score_json.catalyst = 9.0`;
- `2 other SEC filing(s): 144, 4`: one further BULLISH_SETUP event.

## Why this matters

- A Form 144 is a **notice of a proposed sale** of restricted or control securities by an affiliate. It does not
  confirm a completed sale, and nothing about it supports an upward move.
- Counting it as positive catalyst evidence in a long-only "BULLISH" score treats neutral-to-negative supply
  information as confirmation.
- Forms 3, 4 and proxy materials receive the same generic credit regardless of their content.

## What this task did

- **Presentation.** The compact alert template (`RESEARCH_REVIEW_COMPACT_V1`) now describes such a record neutrally,
  as "Form 144 proposed-sale notice". It is never called a catalyst, a completed sale, or confirmation, and its link
  to the move is marked unverified.
- **No rule change.** The score contribution, the setup threshold, ranking and promotion admission are unchanged.

Any rule change (for example, treating Form 144 as non-scoring) would alter detection and promotion. It needs its own
pre-registered decision, a STRATEGY_MATERIAL declaration and a new research baseline.
