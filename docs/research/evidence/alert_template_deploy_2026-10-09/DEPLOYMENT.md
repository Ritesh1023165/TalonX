# Research-review alert template `RESEARCH_REVIEW_COMPACT_V1`: deployment record (2026-10-09)

**Change type: presentation only, owner-approved.**
- *Unchanged:* opportunity rules, scores, thresholds, rate limits (3 per 5 min), delivery timing, routing (TRADE_EVENT,
  plain text `parse_mode=None`), deduplication, paper accounting, the 600-stock universe, V2, DTU, ERM, VR (still
  BLOCKED) and the POST_DELIVERY_ALERT_MARKOUT_V1 lock.
- *Recorded only:* the Form 144 scoring issue, in [`FORM144_SCORING_FINDING.md`](FORM144_SCORING_FINDING.md).

## Version and boundary

| Item | Value |
|---|---|
| Template | `RESEARCH_REVIEW_COMPACT_V1`, `talonx_opportunity.promotion.render_review_compact`. The previous `render_review` is kept, unused, for rollback. |
| Code commit | `2de2a86` on `feature/continuous-opportunity-engine`, pushed; the live checkout was fast-forwarded. The runtime records `2de2a86e0b6d-dirty` only because of the unrelated, preserved `docs/research/evidence/forward_alpha_validation.md` working-tree modification. |
| Declaration | #50, `UI_ONLY`. The runtime decided `RULE:CONFIG_KEY_MAPPED+DECLARED`; the only changed config key was `promotion_src`. |
| Deployed (promotion restart) | **2026-10-09 16:53:33Z = 17:53:33 Europe/London (BST)** |
| Loaded promotion version | `02df848a2940` → **`0f06331c662f`**. Component RUNNING, `PAPER_SIGNAL`, `signal_delivery=RESEARCH_REVIEW`, boundary 2026-10-07 22:42:55Z (unchanged), `suppressed_pending_at_start=0`. |
| Owner | One logical promotion process: venv shim 20924 → worker 17100. Only promotion was restarted. |
| Unchanged fingerprints | PROMOTION_V1 policy `4926c12e5eace04e`. DTU schedule (DTU_V3_TOP600 from 2026-10-09): file sha256 `9f0c07a5…`. PDM protocol `c812a3e65e4018a5`, config file sha256 `f7f012fd…`, `verify_integrity` = [] **before and after**. |
| Template provenance | `template_version` was added to the outbox row's existing `provenance_json`. It is additive and not read by any study: the PDM registration reads named outbox columns only. |

**Pre-existing messages.**
- At deployment the Signal outbox held **1,431 rows, all `SENT`, none pending**.
- No row was re-rendered, edited, replayed or suppressed. Old payloads keep their original wording and provenance.
- Only messages rendered after 16:53:33Z use the new template.

## Deployed template (structure)

```
🔎 RESEARCH OPPORTUNITY — UNVALIDATED
{SYMBOL} · price up|down {x.xx}% from prior close {prev_close}

Why flagged: move = {n.n}× its 20-day average true range ({atr}% of price) · volume since 04:00 ET {vol} sh = {pct}% of 20-day avg daily volume · {d}% above prior-day high {ph} | inside prior-day range (high {ph}) | {d}% below prior-day low {pl}

Historical price: {price} at {data time} ET
{delay}-min delayed feed · data {age} min old when written · not a live quote
Detected {event time} ET · written {render time} ET

SEC context: No matching SEC/insider record found in the checked sources. News not checked.
           | {records, Form 144 = "Form 144 proposed-sale notice"}. Connection to the move unverified; news not checked.
           | UNKNOWN ({lookup incomplete …}). News not checked.

Scope: Today’s session, closing {exchange-calendar close} ET. No entry, exit or holding rule.
Rule score: {s}/100; not a probability.
Repeat: earlier alert for {SYMBOL} delivered {YYYY-MM-DD}     ← only when an earlier outbox row is SENT

⚠️ This policy’s evaluated paper results were negative after costs.
For review only · not a buy instruction · no order placed
Policy {policy} · universe {DTU policy} · reference {promotion_id}
```

**Rules.**
- **Missing evidence** shows as `UNKNOWN`. A presentation fault falls back to the evidence-free form and never blocks a
  release.
- **Repeat line:** omitted when there is no confirmed earlier delivery, or when the lookup fails. "First" is never
  claimed.
- **Acknowledgement time** is never in the message.
- **Times** are America/New_York; the close comes from `phases.trading_window`, so half days and DST are correct.

**SEC "no match".** "No matching SEC/insider record found in the checked sources" is shown only for the engine's
`none found` result. A failed lookup is recorded as `catalyst lookup incomplete: …` and renders as `UNKNOWN`.

**Limitation.** `none found` would also be produced for a member without a CIK, where no search happens. On 2026-10-09
all 600 ACTIVE members of the window had a CIK and live discovery runs with an SEC client, so for this universe
`none found` means a search with no match.

## Detailed evidence that stays outside the message

- The per-alert score arithmetic (`score_json` parts and `why`), the setup threshold (60) and the research-verdict
  figures are not on the dashboard today. The :8787 opportunity lane shows delivery counts and the verdict line, not
  per-alert score parts.
- These details remain in:
  - `opportunity.db` `candidate_events.score_json` (per alert);
  - [`../alert_usability_2026-10-09/REVIEW.md`](../alert_usability_2026-10-09/REVIEW.md) (score definition and
    weights);
  - [`../2026-10-07_review_alert_restoration.md`](../2026-10-07_review_alert_restoration.md) (negative verdict:
    replay −0.61%, forward −0.46% net).
- No dashboard subsystem was added.

## Verification

- **Fixtures:** `tests/test_review_alert_compact_template.py`, 23 tests covering:
  - typical render (exact text) and forbidden wording;
  - missing and partial evidence;
  - SEC: no match vs unknown vs records; Form 144; 6-K, 8-K and Form 4;
  - old data and queue delay;
  - EDT, EST and the half-day close (2026-11-27 13:00 ET);
  - repeat present or absent (FAILED is not confirmed);
  - plain text with no escaping, and length < 4096;
  - live send path with the version in provenance and tracing `TRACE_OK`;
  - score, state and policy fingerprint unchanged;
  - fault fallback;
  - pre-existing rows not rewritten.
- **Affected regressions:** 412 passed (promotion, review alerts, pause, tracing, noise reduction, continuous engine,
  same-chat isolation, top-600 labels, PDM markout, collector, batching, two triggers).
- **Freeze gate** (`a56ec8c`): pass.
- **Local renders:** [`LOCAL_EXAMPLES.md`](LOCAL_EXAMPLES.md), generated by `render_examples.py`: TWLO, CF, PBR, PANW
  and XYZ, existing vs compact, rendered as of each original render instant.
- **Natural delivery:** see the section below, produced by `verify_natural.py`.

## Rollback

Restore the previous renderer without replaying or disabling tracing:
1. In `Promoter._release`, change `self._render_review(s, q, now)` back to
   `render_review(q, now, self.policy.version)`. Optionally remove the `template_version` provenance key.
2. Commit and push.
3. Run `python -m talonx_opportunity declare-change promotion --class UI_ONLY --reason "rollback to render_review"`.
4. Run `python -m talonx_opportunity restart promotion`.

`_traced_client` / `TracedTransport` stay as they are, outbox rows are never edited or resent, review delivery stays
enabled, and VR stays blocked.

## Natural delivery (live; separate from the fixture verification): **PASS**

This is the first naturally occurring review alert after deployment. Evidence:
[`NATURAL_VERIFICATION_2026-10-09.json`](NATURAL_VERIFICATION_2026-10-09.json), sanitised, with no chat or Telegram
message identifiers.

**KKR**, reference `OPPORTUNITY_ENGINE:2026-10-09:KKR:GAP_UP`:

| Time | UTC | ET |
|---|---|---|
| Market data | 16:39:00Z | 12:39 |
| Detected | 16:55:00Z | 12:55 |
| Written | 16:55:16Z | 12:55 |
| Telegram API acknowledgement (audit only, not in the message) | 16:55:17Z | 12:55 |

**Checks:**
- The delivered text is **byte-identical** to the message re-derived from the generation-time records with the deployed
  renderer, as of its render instant.
- `template_version = RESEARCH_REVIEW_COMPACT_V1`.
- `SENT`, one attempt, unique dedup key.
- Trace `TRACE_OK` with 0 hidden retries.
- The historical price is disclosed as "$92.41 at 12:39 ET · 15-min delayed feed · data 16 min old when written".
- SEC context reads "No matching SEC/insider record found in the checked sources. News not checked."
- The session close shows as 16:00 ET, as the calendar gives.
- There is no Repeat line, because KKR had no earlier confirmed delivery.
- VR entry control: `BLOCKED`.

No message was manufactured or resent, and no rate limit was changed.
