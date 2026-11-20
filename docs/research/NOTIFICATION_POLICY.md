# TalonX Informational Notification Delivery Policy (Task 138, revised Task 140; owner decisions 2026-11-20)

## 0. Owner decisions 2026-11-20 (supersede anything below that conflicts)

**Context.** On 2026-11-19 the programme decision was approved: stop the edge search under the current constraints.
- V2 forward: `V2_NO_EDGE_CONFIRMED`.
- PDM: `PDM_NOT_COST_SURVIVING`.
- TalonX continues as a descriptive Risk & Event Intelligence product (`docs/research/closeout/2026-11-20_alpha_programme_closeout.md`).

Every message TalonX sends is **awareness only**. None is worded or presented as a trade prompt, buy/sell
language, entry timing or target.

### 0.1 Signal-bot review alerts: thinned to a per-session cap

| Item | Rule |
|---|---|
| Producer | `talonx_opportunity/promotion.py`, `RESEARCH_OPPORTUNITY` to the TRADE_EVENT (Signal) bot |
| Cap | Only the **first 10 released alerts per trading window** are sent |
| Past the cap | Recorded `PROMOTED_SHADOW` / reason `THINNED_SESSION_CAP`: never enqueued, sent or replayed |
| Configuration | `results/opportunity/control/promotion_signal_delivery.json`, block `"thinning": {"mode": "SESSION_CAP", "max_per_session": 10}`. Read at component start; a change needs `python -m talonx_opportunity restart promotion` |
| Fail-safe | A malformed block falls back to the default cap of 10. A typo can never produce more alerts |
| Rollback | Remove the block (no cap) and restart promotion |
| Unchanged | Delivery filter only. `OPPORTUNITY_PROMOTION_V1` (fingerprint `4926c12e5eace04e`), its eligibility, score ordering, rate limit (3 per 5 min), 30-min queue expiry and one-promotion-per-candidate rule; paper outcomes are still recorded for every released promotion |
| Expected volume | About 60 → 10 per session (replay over the 24 sessions 2026-10-19 … 11-19, 1,448 alerts → 240) |
| What the cap drops | Alerts released after the first 10 of the session, typically after the first 25–85 minutes of the regular session. A later, higher-scored alert can be dropped: the cap keeps release order, not the best scores of the day |
| Cockpit | `:8787`, Notification lanes → `PAPER_SIGNAL_PROMOTION` shows the configured vs loaded cap and the `thinned_session_cap` count |

### 0.2 Review-alert wording: template `RESEARCH_REVIEW_AWARENESS_V4`

Same layout as V3 (five visible lines, details in an expandable quote) and the same values.

| | Before | After |
|---|---|---|
| First line | `… · UNVALIDATED` | `… · AWARENESS ONLY` |
| Score line | `Score N/100 · not a probability` | `Rule score N/100 · not a probability or recommendation` |
| Warning line | `Paper results negative after costs · review only · no order` | `Awareness only · not a trade prompt · tested: no edge after costs` |
| Scope line | `Scope: Today’s session, closing 16:00 ET. No entry, exit or holding rule.` | `Observed in today’s session (closes 16:00 ET).` |
| Footer | `For review only · not a buy instruction · no order placed` | `Awareness only · not a trade prompt · no order placed` |
| Fallback header | `RESEARCH OPPORTUNITY — UNVALIDATED` | `MARKET MOVE — AWARENESS ONLY` |

- **Enforcement:** `tests/test_review_alert_awareness_wording.py` fails on buy/sell, entry/exit, target, stop,
  opportunity, setup, actionable or signal wording in any review-alert render.
- **Exemption:** the two provenance lines that carry fingerprinted identifiers (`OPPORTUNITY_PROMOTION_V1`,
  `OPPORTUNITY_ENGINE:…`), which cannot be renamed.

### 0.3 V2 companion (`INSIDER_BUY_CLUSTER_V2@1`): passive record, sends nothing

- **What it sends:** no BUY/SELL alert to the Signal bot and **no V2-produced OPERATIONS notification**
  (`DEGRADED_HEALTH` from component `v2`, `EXIT_UNRESOLVED`, `ACCOUNT_BLOCK`). This holds **whatever flags it is
  started with**: the release start still passes `--deliver --transport telegram`.
- **Where it's enforced:** `talonx_v2/passive.py` (`V2_PASSIVE = True`), applied in `talonx_v2/service.py`.
- **Unsent rows:** every unsent V2 alert row is retired `EXPIRED` with `SUPPRESSED_V2_PASSIVE: …` (terminal; it can
  never be replayed). SENT rows are untouched.
- **What keeps running:** the companion as a descriptive record (Form 4 polling, cluster episodes, paper ledger,
  dashboard), and the **shared OPERATIONS drain** (owner choice "silence V2 only"), so other components' operations
  messages (Intelligence health, start-up notices) still arrive.
- **Fingerprint:** the frozen V2 strategy fingerprint `e2acf6454789217e` is unchanged (passive lives outside
  `V2Config`).
- **Messages already sent before this change**, recorded for the owner:
  - 2026-11-14 01:17Z "PLANNED BUY ABCL";
  - 2026-11-17 01:16Z "BUY FILLED ABCL".

  These were paper notices from a strategy with no demonstrated edge. The ABCL paper position is still managed
  silently to its planned 2026-12-01 exit, and no SELL message will be sent.
- **Forward tracker:** the V2 forward-study daily loop ended on 2026-10-31 as registered. There is no daily forward
  record to keep, and the closed study is not rerun.
- **Enforcement:** `tests/test_v2_passive.py`, including a negative control showing the same setup would send when
  passive is off.

### 0.4 Out of scope of these decisions (unchanged, listed for completeness)

- **Opportunity Lab bot** (`talonx_opportunity/notifier.py`, about 200 messages per day): uses
  "NEW SETUP / BULLISH / BEARISH" wording. Not covered by the 2026-11-20 decisions; open for a separate owner decision.
- **Intelligence cards** (this document §1–§9): unchanged. A ≥2-insider open-market buy cluster still routes
  `IMMEDIATE` (§3.3) as a descriptive filing card, not as a V2 signal.

---

Status: active configurable delivery policy, not an economically-validated
trading threshold. Governs which already-enriched, already-scored
informational cards interrupt the operator via Telegram, and which are
held for the periodic digest or dashboard-only. It changes **nothing**
about ingestion, enrichment, significance scoring, the freeze fingerprint,
or V2's own paper entry/exit delivery (a completely separate route/
meaning, untouched — see §5).

**Task 140 update**: the periodic filing-activity DIGEST route itself is
now OFF by default (§2.1) — a routine, non-substantive event no longer
produces ANY Telegram message by default (previously it still reached the
operator, just bundled into one larger periodic message rather than sent
individually). This closes the gap the original Task 138 policy left:
replacing a large filing-inventory digest with a smaller one is still
noise if the digest itself was never explicitly requested.

## 1. Objective

Keep collecting and scoring broadly (every event still reaches
enrichment, significance, comparison, insider-activity, and the
dashboard). Reduce how often the operator's Telegram is interrupted, by
requiring a **specific, already-established, substantive reason** before
a card reaches the operator immediately — not merely a band label, a
form/item number, or watchlist membership.

## 2. Three dispositions

| disposition | meaning | mechanism |
|---|---|---|
| `IMMEDIATE` | one Telegram message, as soon as the freshness gate allows | existing `ROUTE_IMMEDIATE` outbox route, unchanged |
| `DIGEST` | bundled into the periodic digest message | existing `ROUTE_DIGEST` outbox route, unchanged |
| `DASHBOARD_ONLY` | never enters the Telegram delivery outbox at all | new: `_enqueue_delivery` skips `enqueue_card` entirely; the event, its enrichment, and its significance score remain fully persisted and dashboard-queryable exactly as before |

No new delivery engine, no new outbox table, no new route. `DASHBOARD_
ONLY` is the only genuinely new behaviour, and it is a *subtraction*
(skip the existing enqueue call), not an addition.

## 2.1 DIGEST delivery itself: OFF by default (Task 140)

Distinct from which individual cards route to `DIGEST` (§3) is whether the
periodic DIGEST message is sent to Telegram **at all**. New config field
`ServiceConfig.deliver_digest_enabled` (env `TALONX_INTEL_DELIVER_DIGEST_
ENABLED`), **default `False`** — independent of, and does not require
touching, the existing `deliver_intelligence_cards`/`TALONX_INTEL_DELIVER_
CARDS` master switch that still governs `IMMEDIATE`.

- **Off (default)**: `IntelligenceService.deliver_cycle` drains
  `process_digest` in the SAME `mode="disabled"` the whole delivery path
  already uses for a fully-disabled deployment — DIGEST-route rows stay
  `PENDING`, logged `HELD` / `"digest due but delivery disabled"`, never
  sent, never dropped, never mutated otherwise. They remain visible via
  the dashboard/detail surfaces and age out through the SAME existing
  freshness/expiry mechanism as any other backlog row (no special-cased
  deletion). This check runs **every** `deliver_cycle`, not a one-time
  migration — a backlog row enqueued before this config existed is held
  on every cycle it is evaluated, not just the first.
- **On (`TALONX_INTEL_DELIVER_DIGEST_ENABLED=1`)**: exact pre-Task-140
  behaviour — the periodic aggregated digest is sent as before.
- `IMMEDIATE` delivery is completely unaffected by this flag either way.

**Effective default for this deployment**: OFF (not currently set in
`.env` or the environment). Verified reaching the running process via
`ServiceConfig.from_env().deliver_digest_enabled is False` and a live
`deliver_cycle` observation (`DIGEST.held >= 1`, `DIGEST.delivered == 0`)
— see `docs/research/evidence/task140/`.

## 3. Deterministic rule (implemented in
`talonx_ingest/intelligence/delivery/notification_policy.py::classify_disposition`)

Inputs: the event's significance `band`, the full `reasons` tuple the
significance engine already computed (`SignificanceReason.code`, one per
scoring rule that actually hit), and the `insider_activity` object when
present (for the buy/sell cluster distinction, §3.3).

1. **`CRITICAL` band → `IMMEDIATE`.** The engine's own CRITICAL structural
   floor (`CRITICAL_BAND_POLICY.md`: ≥2 substantive scoring families, ≥5
   substantive points) already REQUIRES multiple, real, established
   signals before a card can reach CRITICAL at all — this policy does not
   re-derive substantiveness for a band the engine has already gated that
   strictly.
2. **`LOW` band → `DASHBOARD_ONLY`.** Essentially no scoring signal;
   never worth a digest slot, let alone an interruption.
3. **`MEDIUM`/`HIGH` band → `IMMEDIATE` only if at least one SUBSTANTIVE
   trigger is present** (§3.1–§3.3); otherwise `DIGEST`.

### 3.1 Substantive reason codes (filing-comparison / fundamentals)

Any of these reason **codes** present in `sig.reasons` — each already
required to cross a frozen, pre-existing threshold to be emitted at all
(`significance/config.py`'s decile/tercile/keyword/XBRL constants,
unchanged by this task):

`SECTION_CHANGE_DECILE`, `SECTION_CHANGE_TERCILE`, `WHOLE_DOCUMENT_
CHANGE`, `NEW_MATERIAL_PASSAGES`, `RISK_TERM_COUNT_ROSE`, `XBRL_
MAGNITUDE`.

### 3.2 Substantive reason code (insider dollar magnitude)

`LARGE_OPEN_MARKET_TRANSACTION` — a single open-market P/S transaction at
or above the existing frozen `INSIDER_LARGE_TRANSACTION_USD` ($1,000,000)
threshold.

### 3.3 Substantive signal (insider buy cluster, checked directly, not via
reason code)

`insider_activity.clusters` contains at least one cluster with `kind ==
"MULTIPLE_OPEN_MARKET_BUYERS"` — ≥2 distinct insiders buying in the open
market within the existing cluster window. Checked directly against the
cluster list (not the generic `INSIDER_CLUSTER` reason code, which fires
identically for **either** buyers or sellers) specifically so a routine
**sell**-side cluster does **not** qualify on its own — matching the
AXON example in §6.

### 3.4 Deliberately NOT substantive triggers, on their own

- `ON_WATCHLIST` / `WATCHLIST_PINNED` (watchlist membership)
- `EVENT_TYPE_BASE` (a filing of this TYPE was filed — e.g. "a Form 4 was
  filed", "an 8-K Item 7.01 was filed" — the form/item number alone)
- `MULTI_ITEM_8K` (multiple disclosure types bundled in one filing)
- `INSIDER_CLUSTER` on its own without confirming buy-side via §3.3 (a
  routine sell-side cluster)
- band label alone (`HIGH`/`CRITICAL` without any of §3.1–§3.3 present
  is not possible for `CRITICAL` by construction, per rule 1; for `HIGH`
  it routes to `DIGEST`, not suppressed — see §4)

## 4. What happens to a non-substantive HIGH/MEDIUM card

Nothing is lost. It routes to `DIGEST` (unchanged existing route) with an
explicit `disposition_reason` recorded in the processing log
(`intel_processing_log`, kind `NOTIFICATION_POLICY`) — e.g. `"HIGH band
but no substantive trigger present (routed to DIGEST)"`. If enrichment
genuinely could not explain a substantive change (e.g. `what_changed` is
unavailable for a periodic filing), the event still retains that
limitation in the digest text rather than being silently dropped or
force-elevated.

## 5. V2 paper entry/exit — separate route (SUPERSEDED 2026-11-20: V2 is passive and sends nothing, see §0.3)

V2's own actionable entry/exit Telegram notifications are generated and
delivered entirely through `talonx_v2`'s own `alert_outbox` /
`OfficialExternalRouter` path — a structurally separate system from the
Intelligence informational pipeline this policy governs. This task does
not modify `talonx_v2/` at all. Action, reference price, timing, and
paper-status detail in those messages are preserved exactly as before —
they were never generic informational cards and this policy does not
touch their format.

## 6. Representative examples (illustrative, from real, already-observed
card content this session)

**DXCM/PSA-style generic Regulation FD notice** — `EventType.REGULATION_
FD`, no `what_changed` comparison exists (8-Ks are not comparison
targets), `HIGH` band driven by `EVENT_TYPE_BASE` + `ON_WATCHLIST` only →
**`DIGEST`**. If a FUTURE Reg FD disclosure happens to attach a genuine
comparison with a decile/tercile-crossing change, it would qualify
under §3.1 and go `IMMEDIATE` — the policy does not hardcode by event
type, it checks the actual substantive signal.

**AXON routine insider-sale summary** — `EventType.INSIDER_TRANSACTION`,
a single or few-insider open-market SALE, no cluster or a sell-only
cluster, transaction size under $1,000,000 → **`DIGEST`** (fails §3.2
and §3.3; a sell cluster alone does not satisfy §3.3 by design).

**A genuine >=2-distinct-insider open-market BUY cluster** (the same
signal class V2's own frozen strategy already treats as significant) →
**`IMMEDIATE`** (§3.3).

**A 10-Q with a Risk Factors section change in the top decile of this
filer's own history** → **`IMMEDIATE`** (§3.1, `SECTION_CHANGE_DECILE`).

**A CRITICAL-band card** (by construction: ≥2 substantive families, ≥5
substantive points already required by the engine) → **`IMMEDIATE`**.

## 7. Compact message shape

Target: **3–5 short lines**.

```
[INFO] SYMBOL — specific event
One sentence describing the verified change.
Source: timestamp / age
Reply "details" for facts and filing link.
```

Repeated explanatory boilerplate (full aggregation-window breakdowns,
extended factual lists) moves to the reply-for-details response (Task
138 Workstream 3) rather than the initial push. The initial line must
name the SPECIFIC verified change (e.g. "Risk Factors rewrite, top
decile"), never a generic "significant filing" placeholder.

"Fresh" is never claimed from a bare DB-read timestamp — the compact
line separates **source age** (event's own `accepted_at_utc`) from
**delivery/freshness-check timing**, which is a distinct concept (see
Task 136B); when only one dimension is actually known, only that one is
labelled.

## 8. Consolidation of related events

Multiple informational events sharing one accession are consolidated
into ONE notification when they would otherwise fire back-to-back for
the same filing (e.g. `EXECUTIVE_CHANGE` + `CHARTER_BYLAW_AMENDMENT` from
one 8-K) — every constituent event ID and distinct fact is preserved and
individually addressable via reply-for-details (Workstream 3); separate
transactions or filings are never collapsed into an invented combined
total. An event whose content has not changed since it last qualified is
not re-pushed (the existing `content_hash`/update-policy mechanism
already prevents this; unchanged).

## 9. Applying this policy to the existing PENDING backlog

New cards are classified by this policy at enqueue time going forward.
Already-PENDING rows enqueued under the OLD band-only logic are brought
under the new policy too, via a bounded, idempotent reclassification pass
(`talonx_ingest/intelligence/delivery/notification_policy.py::
reclassify_pending_rows`) run once as part of cutover: for each PENDING
`IMMEDIATE`-route row (bounded batch size, oldest-enqueued first), it
re-fetches the row's own already-persisted significance record (reasons)
and insider activity, re-runs `classify_disposition`, and — only when the
new verdict is `DIGEST` — updates that row's `route` column in place
(logged, with the reason). A row already on `DIGEST` is left as-is (no
information is lost by leaving it there). No `DASHBOARD_ONLY` downgrade
is applied retroactively to an already-enqueued row (there is no clean
way to "un-enqueue" one) — that disposition only ever applies at the
initial enqueue decision. No row is deleted, and no `SENT`/`AMBIGUOUS`
row is ever touched or replayed.
