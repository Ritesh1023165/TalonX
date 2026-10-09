# POST_DELIVERY_ALERT_MARKOUT_V1: activation preflight (nothing here has been executed)

**Package state.** Disabled. There is no store, no schedule and no wiring. `run()` returns `DISABLED` unless
`TALONX_PDM_ENABLED=1` **and** `TALONX_PDM_CONFIG` points to an approved config that passes `load_activation`.

## Approved config (template; `approved` deliberately false)

```json
{
  "approved": false,
  "approved_by": "",
  "approved_utc": "",
  "protocol_fingerprint": "c812a3e65e4018a5",
  "code_commit": "<commit approved for activation>",
  "first_session": "2026-10-19",
  "delivery_trace_policy": "REQUIRED"
}
```

`load_activation` refuses the config if:
- `approved` is not true, or `approved_by` is empty;
- the fingerprint differs from the code;
- `first_session` is not an XNYS session;
- `approved_utc` is not before `first_session` 00:00Z;
- the trace policy is missing.

## Checklist before the first session

1. The owner approves the formulas and values in the protocol, revision 2 (§2, §4, §6), and the fingerprint.
2. **Delivery trace:**
   - **either** wire `TracedTransport` into `talonx_opportunity.promotion.Promoter._drain_signal`, as a declared
     promotion deployment with a trace store path outside Git, and keep `REQUIRED`;
   - **or** set `NOT_AVAILABLE_ACCEPTED`, accepting that hidden client retries cannot be excluded.
3. Clock: `w32tm /query /status` shows NTP sync within the last 24 h (read-only).
4. Provider: bar and quote entitlement are live-verified (2026-10-09 probe). Re-check once off-hours on the activation
   eve with a non-study symbol.
5. Invocation: one off-hours run per trading day after close + 60 min and outside R5 (≥ 16:30 ET on half days). For
   example 21:30 UTC in EDT and 22:30 UTC in EST, through the existing scheduler. Each run is bounded by the
   acquirer's time budget. The deadline logic makes missed days safe.
6. Store: `results/post_delivery_markout/` (gitignored), created on the first enabled run only.
7. During collection, use `health()` only. `final_report()` is refused until 2026-11-17 22:00Z.
