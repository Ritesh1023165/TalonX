# Monitored-symbol count reconciliation (2026-10-09)

**Source.** One ingestion generation, read in one read-only transaction: generation **54**, data as-of
2026-10-09T08:41Z, matched to its own cycle row and the published snapshot `2026-10-09@2026-10-08#2849da5594f272db`
(DTU_V3_TOP600). Script: `reconcile_cycle.py`; output: `reconcile_latest.json`.

**Fetch-list rule.** `dtu_active.symbols_json` is written only when the fetch list changes. The list in force is the
latest non-null row at or before the cycle (here the row written at 08:03:26Z), which is the same rule discovery uses
(`universe_tiers.latest_active`).

| Layer | Set / measure | Count |
|---|---|---|
| Membership | C = published Core (`ACTIVE_CORE`) | **600** |
| | V = V2 execution scope (companion log) | **39** |
| | C ∩ V | **36** |
| | C − V | **564** |
| | V − C | **3**: ABCL (CAP_RANK_EXCLUDED rank 1229), ACHR (LIVE_BELOW_CLOSE_5), ADC (CAP_RANK_EXCLUDED rank 924) |
| | P = protected/shared additions | **0** |
| | C ∪ V ∪ P | **603** |
| Fetch scheduling | symbols requested this cycle | **603** (= C ∪ V ∪ P exactly) |
| Successful response | cycle row: fetched 603, batches 4, failed batches 0, failed symbols 0; all 603 watermarks advanced to the as-of | 603 |
| Data freshness (premarket, 08:41Z) | ≥ 1 premarket bar so far / none yet / a bar in the last 15 min | 357 / 246 / 189 |
| Discovery admission | admissible = C | **600** |

**Conclusion.** This was a **wording error, not a coverage defect**.
- "564 core + 39" are the resolver's per-symbol **labels**. `resolve()` gives V2 scope (`OPERATOR_ADDED`) precedence
  over `ACTIVE_CORE`, so the 36 V2 names inside the Core carry the V2 label.
- The membership is 600 Core plus 3 V2-only names, giving 603.

**Notes.**
- A symbol with no premarket bar yet is still subscribed and requested; it simply has not traded since 04:00 ET. It
  is not a missing subscription.
- ACHR is in V2's scope but below the $5 floor. It is fetched for V2 management, which is by design, and is not
  admissible for new opportunities.
