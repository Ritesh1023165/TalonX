# Rollback — Task 117 overnight release

**Corrected and superseded by `docs/audits/task117_final_activation_corrections/rollback.md`**
(wrong `~/.talonx\v2_lane.db` path below; corrected doc uses the real
`<REPO_ROOT>\v2_lane.db` path, prefers compatible-code rollback over any
DB restore, and never blindly restores over post-activation writes). Kept
here for history; follow the corrected doc.

## What this release changed (all reversible)

| area | change | reverse |
|---|---|---|
| `intelligence_delivery` table | additive columns `attempt_id`, `in_flight_since_utc`, `transport_message_id` (idempotent `ALTER TABLE` on first `DeliveryOutbox` open) | additive-only; ignored by the previous code. No column drop needed. To be strict: restore the `ingestion_ledger.db` pre-activation copy. |
| `schema_meta` keys | `last_digest_bucket`, `last_digest_sent_utc` written by `process_digest` | inert for older code; delete the two rows if desired |
| delivery pipeline / outbox / telegram_client / runner | new claim/recover/digest logic; `retry_ambiguous` param | `git checkout <PREV_SHA>` — pure code |
| `talonx_ops/prospective/lock.py` (new) + `proc.py` / `__main__.py` wiring | atomic single-writer lock + startup verdict | `git checkout <PREV_SHA>`; delete any stray `v2_lane.db.startlock` (safe: it is only an advisory lockfile) |
| `dashboard_read.py` + `dashboard_web_static/index.html` | new `card_delivery` / `official_telegram_last_send` read-model blocks + SPA cards + `?nows=1` affordance | `git checkout <PREV_SHA>` — read-only surface |
| `lane_accounting.py` | accounting-correction fields | `git checkout <PREV_SHA>` — output-shape only, no state written except `lane_accounting_eod.json` at `close` |
| `intelligence/service/service.py` | `--send` now also sets `deliver_intelligence_cards=True` | `git checkout <PREV_SHA>` |

**No strategy input changed.** V2 fingerprint `11107198c5b81237` before and
after. Frozen thresholds / holding period / sizing / execution scope untouched.
No production timestamp history was reinterpreted (Task E manifest: 0
VERIFIED_CORRECTION).

## Rollback procedure

1. **Stop cleanly (ownership-safe):**
   ```
   python -m talonx_ops.prospective close            # reconciles + ownership-safe stop_stack
   ```
   If a poll loop with `--send` is running, Ctrl-C it (it is cooperative:
   `CancelledError` is re-raised, an in-flight claim is left IN_FLIGHT and
   recovered to AMBIGUOUS on next start — never blind-resent).

2. **Confirm nothing owned is still alive:**
   ```
   python -m talonx_ops.prospective status
   ```
   Expect `NOT_STARTED`. Remove a stray startlock only if `status` shows no live
   owner: `del %USERPROFILE%\.talonx\v2_lane.db.startlock`.

3. **Restore mutable state (only if it was mutated):**
   ```
   copy v2_lane.db.pre_activation_<UTC>          %USERPROFILE%\.talonx\v2_lane.db
   copy ingestion_ledger.db.pre_activation_<UTC> %USERPROFILE%\.talonx\ingestion_ledger.db
   copy env.pre_activation_<UTC>                 %USERPROFILE%\.talonx\.env
   ```
   If `v2_lane.db` was absent before activation (Day-1), just delete it.

4. **Revert code:**
   ```
   git -C C:\workspace\TalonX checkout <PREV_SHA>
   ```
   `<PREV_SHA>` = the commit before the final Task 117 commit (recorded in
   `MORNING_HANDOFF.md`).

5. **Re-verify:**
   ```
   python -m talonx_ops.prospective preflight --expected-sha <PREV_SHA>
   ```

## Redis

Never flush or restart `talonx-redis`. Rollback does not touch Redis; `run_id
50c35db7f72366789f96c6f1e3718e8942494176` is retained. Any comingled
`metrics:*` keys are historical and read-only.

## Partial-start failure

`prospective start` already self-heals a partial start:
`FAILED_WITH_RESIDUALS` → automatic ownership-safe `stop_stack` +
`start_cleanup.json`. No manual rollback needed for a failed start; just read
`start_cleanup.json` and `start_verify.json`.
