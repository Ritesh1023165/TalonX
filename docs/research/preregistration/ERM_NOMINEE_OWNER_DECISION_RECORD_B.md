# ERM nominee: owner decision record (window B), 2026-10-06

**Recorded owner decisions.** Authority: the owner's instruction of 2026-10-06 ("OWNER DECISIONS AUTHORISED BY THIS
PROMPT"). They authorise **locking** the final protocol and implementation only.

**This is NOT a GO.** It authorises no release activation, no guard lift, no data acquisition, no Task75 reserve
consumption entry and no validation run. Those require a separate, explicit GO.

## Decisions (verbatim scope) and their config fields

The config fields are in `ERM_NOMINEE_OWNER_DECISIONS_B.json`, read by `config.OwnerDecisions`.

| # | Decision recorded | Config field |
|---|---|---|
| D1 | Window **B**: gap days 2024-01-02..2026-09-30 | `window = "B"` |
| D2 | Acknowledge that the **later, separately authorised** acquisition will consume the overlapping Task75 reserved windows (2024-06-01..09-02, 2024-10-21..12-20) and the reserved 2025–September 2026 data. **No consumption is authorised now.** | `task75_reserve_acknowledged = true` |
| D4 | Adopt the minimum sample: 100 valid events and 40 distinct **entry** dates (below either → INCONCLUSIVE) | `min_sample_floor_adopted = true` (`MIN_SAMPLE_FLOOR`; `gates.gates` counts distinct entry dates) |
| D5 | ETF cost **4 bps round trip**, an unmeasured primary assumption; 0/12/20 bps sensitivities descriptive only; stock cost stays **30 bps** round trip | `etf_cost_bps = 4` (subtracted once per trade in `gates.pair_net`, i.e. round trip); `STOCK_COST_BPS = 30` and `ETF_COST_SENSITIVITIES_BPS = (0, 12, 20)` are fixed |
| D6 | Approve the documented procedural and diagnostic conventions (step 0 / RUN_INVALID, step 2′ n = 0, the §5/§6 diagnostic conventions, the T5/T8–T12 acquisition procedure), subject to D6a below | `procedural_amendments_approved = true` |
| D6a | The acquisition-retry rule below, exactly | (implemented in `attempts.py` + `workflow.py`) |
| D7 | Accept the bounded broad-metadata scope for a **future, separately authorised** acquisition (detailed below) | `broad_metadata_scope_approved = true` |
| S&P | Insufficient S&P coverage → **ACQUISITION_BLOCKED**: no scoring, no statistical FAIL, no automatic alternative source, no window switch | (acquirer S0; final protocol T11) |

**D7 scope:**

- `assets_current`, `sec_reference_current`, `submissions` and `sp500_pit`, through the reference date R + 1 day.
- `identity_renames`, from the day after the window end (2026-10-01) through R.
- Eligibility may use only evidence permitted by V2.1. Broader acquisition is **not** permission for future-assisted
  admission (final protocol T8).

## D6a: exact policy

1. An acquisition blockage before any outcome has been computed, persisted, displayed or otherwise exposed does not consume the single statistical scoring run.
2. At most one acquisition retry is permitted, under the same locked rules and approved scope (at most two executions in total; each execution acquires afresh into its own archive).
3. The retry requires an explicit recorded reason. The requests, retrieved data and exposure of every attempt are recorded and preserved (`attempt_<n>/`), never deleted.
4. The attempt budget is held in one attempt ledger per hypothesis and window, outside every run directory (`results/erm_nominee_validation/ATTEMPT_LEDGER.jsonl`). A new run ID, a renamed directory or a restarted process does not reset it.
5. No retry of any kind once outcomes may exist (the scoring stage has started). The owner decides.
6. A second failure before outcomes stops for owner review (ABORTED_OWNER_DECIDES).
7. Separate counters are kept: `acquisition_attempts` (executions started) and `scoring_attempts` (the outcome stage entered; at most one, ever).
8. A request-level transport retry is not an acquisition attempt. It is the existing bounded policy: 4 attempts, 2/4/8 s backoff, `Retry-After` ≤ 60 s, recorded per request. It happens inside one execution.
9. Reference date. An execution whose acquisition would fall outside the authorised envelope (retrieval after R + 1 day) is refused before it starts and consumes nothing. R is never re-pinned and access is never widened; a separate scope decision (a new release and GO) is required.

## Not approved by this record

Nothing beyond the table above is approved. In particular:

- no change to the nominee, the V2.1 rules, eligibility, the statistical method, the gates or the costs;
- no window other than B;
- no execution-time reference date R (R is instantiated and bound only in the later GO and release request);
- no release activation, guard change, data acquisition or validation run.
