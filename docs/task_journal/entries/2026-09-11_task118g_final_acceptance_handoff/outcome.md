1. **Verdict**: **PRE_EOD_ACCEPTANCE_COMPLETE.** Checked 2026-09-11T16:25:28Z — market close is 20:00 UTC (3h35m away); this is a verified pre-close acceptance snapshot, not a claim of monitoring through close.

2. **SHAs**: release `5c0b3f3ccfef45ff8438e75f8f614b738deefc9a` (code, unchanged this task) → docs **`d4177b3`**. Research `dd1d619` → this commit. Both pushed.

3. **Final readiness / NUE / attribution**: **43/43 live**. NUE: 142 1-minute bars (fresh, 16:20:00Z), **and** confirmed genuine subsequent evaluation (22 `LOW_VOLATILITY` rows today — real gate evaluation, not a buffer flag). No exact NUE completion timestamp was preserved; reported as "first observed READY at 16:20:50Z," with an arithmetic estimate (~15:57Z) explicitly labelled as inference, not fact. **Accurate attribution**: 30→41/43 from **ordinary startup preseed** (not the new code); 41→42/43 from **Task 118F's recovery sweep** (directly logged, 1 symbol, 2.6s); 42→43/43 from **subsequent live accumulation** (NUE). The sweep is credited with exactly the one symbol its own log proves, not all 13. Confirmed **zero** historical alerts/entries/exits emitted anywhere in the restart/sweep window (15:51–15:53Z). This is a bounded, once-per-startup sweep — not continuous mid-session recovery, and none is claimed.

4. **Per-lane outcomes**: Original 0 published/0 pushed today (correct — LOW_VOLATILITY-dominated). Intelligence: `SENT: 6` card rows = **1** actual message (unchanged, no resend). V2: 0 signals today. Experimental: 5 entries, 4 exits (all recovery-affected), 1 still open (SPCX).

5. **SPCX/V2/obligations**: SPCX **still open**, fresh mark $148.61 (16:20:00Z, ~2 min old) → **unrealized +$6.45 (+0.258%)**. Realized total reconfirmed exactly **−$324.4662160270568**. V2: cash $300,000, 0 positions, tick 13 fresh, ABCL stale episode unchanged, no pending intents, fingerprint `11107198c5b81237` unchanged.

6. **EOD**: not due. **Required: `python -m talonx_ops.prospective close` at/after 2026-09-11T20:00:00Z, complete by 21:30:00Z.** No shutdown performed; Redis untouched throughout.

7. **Corrections / unresolved**: dated corrections appended (originals preserved) to `PRIORITY2_ORIGINAL_WARMUP.md` (release — the provider-transient conclusion stands; the separate application-side retry defect Task 118F found is now cross-linked) and `TASK118E_READINESS_SPCX_DECISION.md` (research — its "no action taken" decision is now superseded by Task 118F's deployed fix). Heartbeat-lapse locus and "45 candidates" source remain **unresolved**, no new evidence found.

8. **Next-session readiness / next action**: candidate release `5c0b3f3`, effective config unchanged, warmup-sweep observable acceptance criteria documented. Next XNYS session verified via `talonx_v2.calendar.is_session`: **Monday 2026-09-14**. One next research action (unchanged from Task 118E/F, not re-opened): track pre-entry volatility on new **live** 39-name-scope entries going forward — the only genuinely unused data this programme has; no further backtest/re-slice proposed.

9. **Links**: `docs/research/{TASK118G_FINAL_ACCEPTANCE,SESSION_2026-09-11_OUTCOMES,NEXT_SESSION_HANDOFF}.md` (research, this commit); `docs/audits/task118a_priority_hotfixes_2026-09-11/PRIORITY2_ORIGINAL_WARMUP.md` (release, `d4177b3`).

**Operational acceptance** (43/43 readiness, full continuity, no defects) and **profitability evidence** (SPCX's swing to positive unrealized and the volatility-return sensitivity agreement are both explicitly not profitability confirmation) remain separate.
