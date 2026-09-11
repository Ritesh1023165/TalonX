# Corrections to the published Sep 8–10 audit (`docs/audits/2026-09-10/`)

Original evidence is preserved; this file records the deltas. Each correction is backed by a
preserved snapshot under `results/` (see `evidence_manifest.csv`).

---

## C-1 · September 8 — "4 events/cards" vs "6 queued rows"

**Published:** `signal_delivery_trace.csv` row `S1-INTEL-CARDS-4` said *"4 cards enqueued"*;
`lane_outcomes.csv` also said 4. The Task-113 EOD summary said `product_cards_enqueued_today: 4`.

**Corrected:** the preserved `intelligence_delivery` table shows **6 rows** enqueued on 2026-09-08,
from **4 filings (accessions)**:

| accession | event(s) | delivery row(s) |
|---|---|---|
| `0000070858-26-000464` | INSIDER_TRANSACTION | 1 (DIGEST) |
| `0001104659-26-105721` | INSIDER_TRANSACTION | 1 (IMMEDIATE) |
| `0001193125-26-385183` | INSIDER_TRANSACTION | 1 (IMMEDIATE) |
| `0001193125-26-384402` | **OTHER_MATERIAL_EVENT + REGULATION_FD** (one multi-item 8-K) | **2** (DIGEST + IMMEDIATE) |
| `0000731766-26-000205` | REGULATION_FD | 1 (IMMEDIATE) |

So **4 filings → 5 classified events → 6 `intelligence_delivery` rows** (the multi-item 8-K
`…384402` produced two events, each its own row). The Task-113 summary's "4" counts filings; it is
not equal to the 6 queued rows. **0 sent.**

## C-2 · September 9 — "9 publications" is an intermediate observation, not the final total

**Published:** `candidate_reconciliation.md` S2 used **evaluated = 121 / published = 9**, taken
from the 17:20Z pre-EOD forensic snapshot.

**Corrected:** those are **17:20Z** values, and the previous Day-2 report referenced **16**
final-day publications. Reconciliation:
- The `metrics:<date>:quant:*` counter is **cumulative** and **comingled Original + Experimental**
  (no lane suffix — proven Sep 9). Between 17:20Z and the 20:12Z close the Experimental lane kept
  evaluating; its `WOULD_PASS` / published count grew from **9** to **16** by EOD.
- `exp_alerts.db` (preserved) shows the Sep-9 Experimental lane ended the day with more
  `directional_alerts` and additional paper entries after 17:20Z, consistent with the counter
  reaching 16.
- **Neither 9 nor 16 is an Original or a V2 publication.** Original intraday published **0** all
  day (every candidate suppressed); V2 published **0**. The 9→16 growth is entirely Experimental,
  on the isolated `talonx:exp:*` channel, never routed to Brain/Core/Dispatch/Telegram.

So the S2 exact-closure (`evaluated = Σ terminal dispositions`, residual 0) holds **at the 17:20Z
cutoff**; the **final-day** comingled counter is ~16 published (all Experimental) against a larger
`evaluated`, and was not re-snapshotted at EOD. The S2 funnel is exactly closed **as of 17:20Z**
and **structurally consistent** at EOD; a byte-exact EOD closure was not preserved.

## C-3 · September 10 — SHOP/BLSH/SKHY "3 publications" ownership: reconstruction, not direct correlation

**Published:** `findings.md` C1 said the S3 "3 quant publications" **are** the 3 Experimental
`WOULD_PASS` directional alerts (SHOP 14:28Z, BLSH 15:22Z, SKHY 16:10Z), confidence "HIGH".

**Corrected (label softened):** this is an **evidence-supported reconstruction**, not a
preserved-Redis correlation. What IS preserved: (a) exactly 3 Experimental `WOULD_PASS`
directional alerts before the 16:24:25Z ping cutoff, in `exp_alerts.db`; (b) the Sep-9 proof that
`metrics:quant:*` is comingled Original+Experimental with no lane suffix; (c) Original intraday
`published_quant_signals_today = 0` and `dispatch_audit.alerts` all-time = 0. What is **not**
preserved: an S3 `metrics:<date>:quant:*` snapshot tying the ping's literal "3" to those 3 rows.
Verdict: **RECONSTRUCTED (high plausibility) — direct correlation UNRESOLVED.** It is still not
labelled "dedup-suppressed" (no evidence for that).

## C-4 · September 10 — 94-candidate residual stays UNRESOLVED

No new records. `126 − 18 − 10 − 1 − 3 = 94` remains **UNRESOLVED**: structurally the same
comingled-counter + off-counter-disposition (THROTTLE/COOLDOWN/revalidation) cause proven for
Sep 9, but the S3 Redis metrics snapshot was not preserved so it cannot be closed to an exact
integer. Not attributed to "repeat/in-flight evaluations" — there are no per-candidate records.

## C-5 · September 9 cleanup narrative

**Published (`findings.md` C4):** described the Sep-9 canonical close as leaving
`residual_talonx_processes` that a follow-up `post_eod_cleanup_20260909T202954Z` "reaped".

**Corrected:** the preserved `post_eod_cleanup_20260909T202954Z/` evidence shows the residual
base-stack processes (`dashboard_web.py`, `talonx_signals.run`, `run_talonx.py`) **exited on
their own** between the canonical close and the cleanup check — the cleanup task performed a
**read-only verification** and **no termination** (`pre_residual_pid_check.txt` → already gone;
`post_processes.txt` → none). So the correct statement is: *"the Sep-9 canonical close's
ownership-aware reap did not cover the base-stack grandchildren in one pass; they self-exited
shortly after; the follow-up task confirmed this read-only and killed nothing."* The Sep-10 close
reaped everything in one pass (`residual_talonx_processes: []`). Still a real one-pass-reap
gap in the Sep-9 code path (D4-adjacent) — but no processes were force-terminated by an operator
task.

## C-6 · `watchlist_scope.csv` — snapshot time vs row update time vs session start

**Published:** `source_snapshot_utc` = `2026-09-10T07:44:36Z` with a parenthetical noting per-row
`last_updated` at `07:45–07:46Z`.

**Corrected:** the header value conflated three distinct instants. They are:
- **Session start** (companion spawn): `2026-09-10T07:44:32Z`.
- **DB file acquisition** (the `.backup()` of `watchlist.db`): `~2026-09-10T20:29Z` (pre-close
  evidence sweep) — this is the true *snapshot acquisition* time.
- **Per-row `last_updated`**: `2026-09-10T07:45:18Z – 07:46:11Z` — when the intelligence service
  refreshed each `upcoming_earnings` row at startup. (The `tickers` table rows carry `added_at`
  from 2026-08-09 – 2026-08-30, untouched during the session.)

The export's implied "snapshot earlier than some row updates" was an artifact of labelling the
acquisition with the session-start time. The corrected `issuer_identity_coverage.csv` in this
bundle uses three explicit columns. No data value changes — 48 rows, 43 active, 5 paused, 39
SEC-covered stand.

## C-7 · D7 (long-term sends missing from `last_telegram_push`) — partially wrong

**Published:** D7 said long-term ORCL sends (LT7/LT8) were absent from `last_telegram_push`.

**Corrected:** the `.postclose` snapshot of `dispatch_audit.db` shows
`last_telegram_push('ORCL','long_term','2026-09-10T20:30:49.719Z', 152.94)` — LT8's timestamp.
`save_last_telegram_push` is an UPSERT on `(ticker, horizon)`, so LT7 then LT8 updated that row.
**Long-term sends ARE recorded.** The prior finding read a `.preclose` snapshot (taken ~20:29Z,
before the 20:30 sends). The **real** D7 residue: (a) the **earnings heads-up** domain never
wrote `last_telegram_push` (fixed this task — now writes `horizon="earnings_heads_up"`); (b)
`last_telegram_push` is a per-(ticker,horizon) **cooldown cache**, not a complete send log — a
"last official send" dashboard tile should union `alerts` + `long_term_alerts` + heads-up, not
read this table.
