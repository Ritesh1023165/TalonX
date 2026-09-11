# Oracle long-term alerts LT6 / LT7 / LT8 — provenance

Source: preserved `dispatch_audit.db.postclose` (`long_term_alerts`, `processed_alert_outbox_ids`),
`talonx_original.log`, `ingestion_ledger.db.postclose` (`text_events`, `intelligence_delivery`).

| | LT6 | LT7 | LT8 |
|---|---|---|---|
| session | Sep 9 | Sep 10 | Sep 10 |
| `correlated_at` | 2026-09-09T06:58:34.959Z | 2026-09-10T20:30:41.733Z | 2026-09-10T20:30:49.705Z |
| `telegram_sent_at` | 06:58:34.984Z | 20:30:46.594Z | 20:30:49.719Z |
| outbox id | `6a111f52…` | `9db24f03…` | `e004cc42…` |
| triggering accession | ORCL 8-K earnings re-read (per log "8-K earnings re-read 06:58:26Z") | **`0001193125-26-387905`** (8-K Item 2.02 + 8.01) | **same `0001193125-26-387905`** |
| model | `gemini-flash-lite-latest` | `gemini-flash-lite-latest` | `gemini-flash-lite-latest` |
| model inputs (per rationale) | "reusing FY2026 factors (ROIC=None, F-Score=7) pending the 10-Q" | same | same |
| `market_price` | 162.52 | 152.94 | **152.94** (identical to LT7) |
| `quality_score` / `moat` | 8 / wide | 8 / wide | 8 / wide |
| `revenue_eps_surprise` | null | null | null |
| `guidance_revision_notes` | null | null | null |
| **`intrinsic_fair_value`** | **175.00** | **175.00** | **165.00** |
| `previous_fair_value` | null | **null** (did NOT carry LT6's 175 forward) | 175.00 |
| `margin_of_safety_pct` | 7.1 % | 12.6 % | 7.3 % |

## LT7 → LT8: **repeat model execution produced an inconsistent estimate**

LT7 and LT8 are **8 seconds apart**, from the **same accession**, with **identical inputs**:
same `market_price` ($152.94), same `quality_score`, same `moat_rating`, same
`revenue_eps_surprise` (null), same `guidance_revision_notes` (null), same "reusing FY2026
factors (ROIC=None, F-Score=7) pending the 10-Q" note. **The only field that changed is the
LLM-produced `intrinsic_fair_value`: 175.00 → 165.00** (and the derived MoS 12.6 % → 7.3 %).

There is **no evidence of a new input** justifying the revision — no new filing, no XBRL update,
no guidance note, no price move. `previous_fair_value` on LT8 is populated (175.00), so the
system *recorded* it as an update, but the revision is a **second, non-deterministic run of
`gemini-flash-lite-latest` on the same prompt** returning a different number. This matches the
task's suspected failure mode: *"repeat model execution produced inconsistent estimates."*

## LT6 → LT7 lineage gap

LT6 (Sep 9) and LT7 (Sep 10) both report `intrinsic_fair_value = 175.00` with
`previous_fair_value = null`. LT7 did **not** carry LT6's assessment forward as a baseline — each
session's first ORCL alert presents as a first-ever assessment. Only LT8 (the intra-session
re-run) set `previous_fair_value`.

## Cited financial figures

The "$638 billion RPO backlog (+363 %)" / "$67 billion AI infrastructure contracts in a single
quarter" / "F-Score 7/9" phrases live in the **LLM-generated `rationale` / `summary` text**, not
in a parsed XBRL fact (`ROIC=None`, factors explicitly "pending the 10-Q"). They cannot be
checked against the actual filing period in this environment (accession `0001193125-26-387905` is
forward-dated; no live EDGAR). **Verification INCOMPLETE** — flagged in `remaining_gaps.md`.

## Outbox / send acknowledgement

All three: `telegram_sent = 1`, `telegram_error = NULL`, `suppress_reason = "NONE"`; a matching
`processed_alert_outbox_ids` row on channel `talonx:alerts:longterm`. **API-confirmed send only**
— no stored Telegram `message_id` for LT6/LT7/LT8 (the dispatch consumer does not persist the
returned message id for long-term alerts), and **human receipt is not claimed**. The activation
smoke test (message id `710`) remains the only send with a stored id.

## Bounded corrections proposed (design — not implemented here)

1. **Stable event/version identity.** Key an assessment on
   `(accession, model_version, input_fingerprint)` where `input_fingerprint` hashes the actual
   numeric inputs (factors, market_price bucket). A re-run with an unchanged fingerprint is a
   **no-op**, not a new "update" alert.
2. **Preserve prior assessments across sessions.** Load the last persisted `intrinsic_fair_value`
   for the ticker at session start so LT(n)'s `previous_fair_value` is always populated.
3. **Explicit supersedes/update relationship.** An update alert carries
   `supersedes_alert_id` and states *what changed* ("fair value 175 → 165; inputs unchanged —
   model re-estimate"). If inputs are unchanged, either suppress the second alert or label it
   `MODEL_RE_ESTIMATE (non-deterministic)` so a reader is not told there is new information.
4. **No unsupported numerical valuation as established fact.** Where factors are "pending the
   10-Q", the card should say "preliminary, pending 10-Q" rather than present a point fair value.
5. **Message-id capture.** Persist the Telegram `message_id` for every successful long-term /
   heads-up send (as the smoke test already does) so future sends are reconcilable. Do not
   backfill missing ids.

None of these are implemented in this task (they touch the Brain/Core long-term path and need
their own validation). They are the acceptance targets.
