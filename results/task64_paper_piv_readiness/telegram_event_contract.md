# Telegram Event Contract

Telegram is a best-effort projection of authoritative local JSONL telemetry. Every message starts `PAPER / NO REAL CAPITAL` and includes timestamp, event, and applicable symbol, correlation ID, price, quantity, reason, and status. Supported events include STARTUP, preflight, session start, data readiness, signal/order/fill/position/exit lifecycle, stale data, broker error, kill switch, flatten, and summary.

The event bus catches delivery exceptions, records failure counters, and never changes readiness, strategy processing, broker operations, state, or exits. Dedupe keys prevent repeated Telegram delivery while preserving local event records.
