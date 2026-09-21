# SessionReadinessValidator Contract

`talonx_piv.readiness.SessionReadinessValidator` is strategy-neutral and evaluates each symbol/session independently. It accepts timezone-aware raw one-minute timestamps only. The expected ET timestamps are 09:30 through 09:59 inclusive. Before 10:00:00 ET the status is `PENDING`; at or after 10:00 it is final: `READY` only when all 30 timestamps and therefore all six constituent five-minute buckets are complete, otherwise `DATA_NOT_READY`.

`DATA_NOT_READY` means zero evaluation requiring opening state, zero candidate, order, or trade for that symbol-session. No interpolation, forward-fill, or synthetic data is permitted. Other symbols continue independently and a new session uses a new readiness key, allowing next-session recovery.

Telemetry fields are `symbol`, `session`, `status`, `evaluated_at`, `expected_minutes`, `observed_minutes`, `missing_minutes`, `missing_5m_buckets`, `reason`, and immutable `synthetic_data_used=false`.
