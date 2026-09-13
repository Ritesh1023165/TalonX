1. **Overall and separate gate verdicts**: **`PASS_FOR_INTEGRATION_REVIEW`**
   (reaffirmed on a corrected implementation). Historical economic
   result: PASS. Prospective-policy implementation acceptance:
   **ACCEPTED** (genuinely in-line-gated, tested). Timestamp-evidence
   limitations: disclosed, session-granular only. Portfolio/risk
   acceptance: real daily mark-to-market drawdown −2.7478%, not
   recovered within window (boundary effect), no invented risk
   tolerance. Identity/coverage acceptance: **PARTIAL** — 21/35
   ambiguous symbols resolved, 14/35 remain genuinely unresolved at the
   symbol level (0 actual trades compromised, proven directly).

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged. Research: start `7afcb0d5ccd630434c44655bb2b6a5133ab58cfc`
   (confirmed exact) → protocol-freeze checkpoint `9d1d795` → final
   **`<this commit>`**, pushed to `research/talonx-profitability-2026-09`
   only.

3. **Prospective-policy enforcement and timestamp limitations**: the
   entry gate is now in-line (before any cash/capacity mutation), not
   post-hoc — a durable `PENDING` intent, created on a strictly earlier
   simulated session and never cancelled/expired/consumed, is required
   for every admitted entry; verified by 9 fixture tests including
   missing-intent rejection, capacity exhaustion, and same-session
   ordering. All timing is session-granular (real XNYS calendar); no
   intraday timestamp is manufactured or called "observed."

4. **Capacity, reservations, phantom-exit fix**: intents reserve
   $10,000 cash + 1 slot immediately; deterministic
   `(eligible_entry_session, issuer_cik, symbol)` ordering under
   competition; hard `SKIPPED_INSUFFICIENT_CAPITAL` with no partial
   fills; entries resolved before same-session exit proceeds are
   credited. The `open_notional.pop(episode_id, allocation)` fallback
   is removed entirely — positions are tracked as real dict entries, so
   an exit can only settle an episode that structurally has an open
   position.

5. **Corrected economics versus Task 130**: **identical** — N=153
   closed trades, net mean **+2.0219%**/round trip, issuer-block CI
   [+0.7222%,+3.3989%], date-block CI [+0.5723%,+3.4573%], both
   exclude zero and agree. Per-episode comparison: 153/153 unchanged, 0
   newly excluded/admitted/changed — explained by this window's
   capacity never having been binding in either implementation (Task
   130's own already-disclosed finding), not assumed equivalence.

6. **Daily marked equity and drawdown**: real daily mark-to-market
   series (every session, causal last-close marks, stale marks
   flagged not zeroed). Max drawdown **−2.7478%** (peak 2026-03-04,
   trough 2026-03-20, not recovered within the window — a disclosed
   boundary effect, not a claimed recovery or failure). Ending
   cash=equity $330,935.40, 0 open/unresolved positions at window end
   (natural completion). Capital utilization: 85.99% of sessions had
   an open position (a frequency measure, explicitly distinguished
   from an unbuilt invested-capital/equity exposure-ratio metric).

7. **Winner-concentration and stability**: original trade-count-ranked
   sensitivity (unchanged) stays positive through top-5 removal
   (+1.95%). NEW supplemental P&L-ranked sensitivity (labelled as such,
   not preregistered) also stays positive but declines more (+1.79% →
   +1.14% through top-5) — a real, disclosed concentration pattern
   (69 of 106 issuers are net-positive contributors; the top 5 account
   for a meaningful share). Calendar half-year stability unchanged:
   3 of 4 half-years positive, 2026H1 negative (−0.50%, n=33), period
   boundaries not moved or excluded.

8. **Issuer identity and coverage**: 35 ambiguous symbols (matches Task
   130's own manifest exactly, re-scoped correctly to the 626-name
   universe). 19 likely legitimate identity changes, 2 multiple-
   securities-same-name, 14 unresolved. For all 8 ambiguous symbols
   with an actual entered trade, the trade's entry date matches exactly
   ONE issuer_cik's filing range — **proving no cluster merged two
   issuers under a shared ticker**, checked directly, not assumed.
   Corrected Task 130's own misstatement: Task 112R's +1.01% belongs to
   the full-panel (N=756) result, not the 39-name live scope (whose own
   corrected figure is Task 120A-C's −0.85%, N=57).

9. **One next action**: none proposed as a new research task — the
   remaining named gaps (14 unresolved identities; restart/idempotency
   testing; an invested-capital exposure-ratio metric) belong to the
   SAME later, separately-authorized integration-review task Task
   130's own handoff already specified. Production preservation:
   unchanged — no process started, no port opened, Redis untouched, no
   SQLite ledger of any kind created (in-memory driver by design).
   Task 129's broader alpha-research pause remains in effect elsewhere.

10. **Journal/reports**: `entries/2026-09-13_task130a_prospective_repair/`
    + `docs/research/{TASK130A_REPAIR_PROTOCOL,TASK130A_PROSPECTIVE_REPLAY_ACCEPTANCE,TASK130A_CORRECTED_ECONOMIC_DECISION}.md`
    + `docs/research/evidence/task130a/*.json` +
    `research/scripts/task130a_{prospective_replay,identity_and_stats}.py`
    + `tests/test_task130a_prospective_replay.py` — protocol freeze at
    `9d1d795`, remainder at this commit, both pushed.

Qualification gaps addressed: prospective policy now genuinely
in-line-gated and tested; phantom-exit defect removed by construction;
daily mark-to-market equity/drawdown computed; issuer identity
reconciled with a direct, checked proof against actual trades; a
supplemental (not substituted) concentration lens added. No new
hypothesis, parameter search, or unrelated operational work introduced.
