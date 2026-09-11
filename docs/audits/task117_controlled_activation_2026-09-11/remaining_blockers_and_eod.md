# Remaining blockers & EOD handoff — 2026-09-11 controlled activation

## Remaining blockers

None found during this activation. Carried forward from prior sessions
(non-blocking, unrelated to today's activation): S1–S3 timestamp anomaly
(unresolved, isolated, 3 historical records). No new defects surfaced during
startup, backup, migration, backlog expiry, delivery configuration, or the
connectivity-test send.

## EOD — operator-driven, not automatic

Today's XNYS regular session: open 13:30 UTC, close 20:00 UTC
(`talonx_v2.calendar.is_session` confirmed 2026-09-11 is a trading day).
**EOD reconciliation is operator-driven** — the checkpoint daemon (spawned by
`start`) runs 30-minute CRITICAL-only checkpoints and does **not** perform
EOD reconciliation or flatten positions. The required operator action:

```
python -m talonx_ops.prospective close
```
run **at or after** verified market close (20:00 UTC / 21:00 BST), targeting
completion before **close + 90 minutes** (21:30 UTC / 22:30 BST). This:
- writes `eod_session_report`, `lane_accounting_eod.json`
  (`build_lane_accounting`), reconciliation JSON;
- then performs an **ownership-safe** `stop_stack` (reaps only the pid-tree
  members verified by create-time + cmdline; releases the single-writer lock
  only when no residual remains).

**No recurring job was created.** If this session is still active when close
approaches and no further operator turn happens before then, the canonical
close must still be run manually — **the checkpoint daemon will not do it**.
Positions, entry intents, and delivery history at that point are exactly what
`prospective close` reconciles and preserves; nothing is flattened
automatically.

## If returning before close

Required operator action and deadline: run `python -m talonx_ops.prospective
close` at/after **2026-09-11T20:00:00Z**, complete by **2026-09-11T21:30:00Z**.
Until then the session is expected to keep running unattended at frozen SHA
`a540f40a2b9770a8cd7b90a1da06f3898be93bba` — no code changes were made while
it is running, and none should be, per this release's own constraint.
