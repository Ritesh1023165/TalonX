# Research-review alert template `RESEARCH_REVIEW_COMPACT_V2`: deployment record (2026-10-09)

**Change type: presentation only, owner-approved visual layout.**
- *Unchanged:* strategy, scoring, eligibility, universe, rate limits, routing, retries, tracing, deduplication and paper
  accounting.
- *Not authorised:* bearish alerts or short trades. The DOWN rendering exists for formatting only; the promotion
  policy remains long-only.

| Item | Value |
|---|---|
| Template | `RESEARCH_REVIEW_COMPACT_V2`, replacing V1 (deployed 2026-10-09 16:53:33Z). |
| Code commit | `643c22a` on `feature/continuous-opportunity-engine`, pushed; the live checkout was fast-forwarded. The runtime records `643c22aece4c-dirty` only because of the unrelated, preserved `forward_alpha_validation.md` modification. |
| Declaration | #51 `UI_ONLY`, decided `RULE:CONFIG_KEY_MAPPED+DECLARED`. The only changed config key was `promotion_src`. |
| Deployed | **2026-10-09 20:30:42Z = 21:30:42 Europe/London (BST)**. Only promotion was restarted. |
| Loaded version | `0f06331c662f` → **`de24a9891031`**. RUNNING, `PAPER_SIGNAL`, `signal_delivery=RESEARCH_REVIEW` (boundary 2026-10-07 22:42:55Z, unchanged), `suppressed_pending_at_start=0`. |
| Owner | One logical process: venv shim 20388 → worker 23548. |
| Outbox | 1,449 rows, all `SENT`, before and after deployment. There were no queued rows, so nothing was re-rendered, replayed or suppressed, and no dedup key is duplicated. |
| Tracing | Trace store active: 67 traces, last 19:40:58Z. `_traced_client` is unchanged. |
| VR | `BLOCKED` |
| Post-delivery study | `verify_integrity` = [] before and after. Config file sha256 `f7f012fd…` unchanged; config hash `6c4512675f685bac…`; protocol `c812a3e65e4018a5`. The collector task is unchanged (Ready). |
| Policy fingerprint | PROMOTION_V1 `4926c12e5eace04e` (unchanged) |

## Layout

The approved order, in plain text with `parse_mode=None`:

```
🔎 RESEARCH OPPORTUNITY — UNVALIDATED
{SYMBOL} · 🟢 ▲ UP +x.xx% | 🔴 ▼ DOWN −x.xx% | ⚪ ▬ UNCHANGED 0.00% | ❔ DIRECTION UNKNOWN
Previous close: {prev_close | UNKNOWN}

📊 Why flagged            (bullets: move vs 20-day ATR · volume since 04:00 ET vs ADV20 · position vs prior-day range)
💵 Historical price: {price} at {data time} ET      • {n}-min delayed feed · not a live quote
🕒 Data {age} old when written                      • Detected {t} ET · written {t} ET
📄 SEC context: …                                   (neutral wording; Form 144 = proposed-sale notice; news not checked)
⏱️ Scope: Today’s session, closing {exchange-calendar close} ET. No entry, exit or holding rule.
🧮 Rule score: {s}/100; not a probability.
🔁 Earlier alert for {SYMBOL} delivered {date}      (only when an earlier outbox row is SENT)

⚠️ This policy’s evaluated paper results were negative after costs.
For review only · not a buy instruction · no order placed

🏷️ Policy …
🌐 Universe …
🔖 Reference {promotion_id}
```

**Direction.**
- It is the recorded `gap_pct`: the change against the prior close in the generation-time features.
- It is never taken from the score or the BULLISH setup label.
- A change of exactly 0, including negative zero, shows as UNCHANGED 0.00%.
- A nonzero change with |x| < 0.005% shows as `UP <0.01%` or `DOWN <0.01%`.
- None, non-numeric, NaN or inf shows as ❔ DIRECTION UNKNOWN.

**Fallback chain:** full render → evidence-free render (UNKNOWN fields) → `render_review_minimal`. The minimal form
keeps the UNVALIDATED header, "not a live quote", "not a probability", the negative disclosure and "For review only ·
not a buy instruction · no order placed".

## Verification

- **Fixtures:** `tests/test_review_alert_compact_template.py`, 41 tests. They cover:
  - up, down, zero, negative zero, below-precision, missing and invalid moves, plus the FLEX example;
  - the recorded direction overriding a conflicting BULLISH label;
  - section order and the optional 🔁 line;
  - missing and partial evidence;
  - SEC and Form 144 wording;
  - delay, DST and the half-day close;
  - plain text and length;
  - live send path with `template_version` in provenance and `TRACE_OK`;
  - score, state and policy fingerprint unchanged;
  - single and double render faults, each sending exactly once.
- **Affected regressions:** 430 passed (promotion, review alerts, pause, tracing, noise reduction, continuous engine,
  isolation, top-600 labels, PDM markout, collector, batching, two triggers).
- **Freeze gate** (`a56ec8c`): pass.
- **Local renders:** [`EXAMPLES.md`](EXAMPLES.md), from `render_v2_examples.py`.
  - UP uses the real KKR record.
  - DOWN and UNCHANGED are **synthetic**: only `gap_pct` is overridden, so the other lines keep KKR's real values and
    the examples are not internally consistent. They demonstrate formatting only and were never sent.
- **Natural delivery: `DEPLOYED_AWAITING_NATURAL_DELIVERY`.** Deployment was after the 16:00 ET (20:00Z) close, and
  promotion admits REGULAR-phase setups only. The next opportunity is Monday 2026-10-12 from 13:30Z (14:30 BST).
  Use `../alert_template_deploy_2026-10-09/verify_natural.py`: set `DEPLOY_UTC` to 2026-10-09T20:30:42Z and expect
  `template_version` `RESEARCH_REVIEW_COMPACT_V2`. No event was created and nothing was replayed.

## Rollback

Restore V1 while keeping tracing and delivery:
1. `git revert 643c22a`. This restores the V1 `render_review_compact` and `REVIEW_TEMPLATE_VERSION`.
2. Commit and push.
3. Run `python -m talonx_opportunity declare-change promotion --class UI_ONLY --reason "rollback to RESEARCH_REVIEW_COMPACT_V1"`.
4. Run `python -m talonx_opportunity restart promotion`.

`_traced_client` / `TracedTransport`, routing and dedup are untouched by the revert. Outbox rows are never edited or
resent, review delivery stays enabled, and VR stays blocked.
