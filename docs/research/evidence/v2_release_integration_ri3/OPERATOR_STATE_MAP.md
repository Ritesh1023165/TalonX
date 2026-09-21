# RI3-A — before implementation

Starting branch: `feature/task131-option-a-integration`; SHA
`b67aa133a3343a8e16a3727e4b6a22f3e24b46ed`; clean status; no later commits.
Process inspection: CIM denied access; Get-Process succeeded, showing only
Node tooling, no Python/Redis/TalonX-named process. No runtime was launched.

| Operator question | Current source | Authoritative? | Visible/correct before RI-3 | Action |
|---|---|---|---|---|
| Running / inputs healthy? | service status, authoritative_read_model, market_health, prospective proc/checkpoint; /ping | Heartbeat/data telemetry yes; PID alone no | Separate data health exists; V2 dashboard trusts heartbeat alone | Verify process identity; preserve independent feed axis |
| Which campaign / starting cash? | RI-1 campaign table | Yes | Dashboard/performance hardcode $300k | Read identity and nullable starting cash |
| Settled/reserved/available cash? | portfolio.cash; PENDING count times allocation (service._capacity_rejection) | Yes | Cash visible; available incorrectly equals cash | Same accepted reservation semantics |
| Positions / obligations / capacity? | positions | Yes | OPEN detail; unresolved count only; allocated/capacity omit unresolved | Include unresolved cost and slots; separate lifecycle groups |
| Pending/recovery/cutover? | pending_entry_intents; campaign_cutover_log; calendar deadline | Yes | Partial status-file pending list | Durable intent details and actual Session-3 close |
| Settled / realized P&L? | CLOSED positions persisted realized_pnl_usd | Yes | Present, correct persisted source | Preserve; remove misleading blanket fee description |
| Blocked / why / clearance? | account_blocks, block_clearances; prospective clearance CLI | Yes | CLI only | Read-only details; preserve explicit operator/reason/evidence workflow |
| Reconciliation? | prospective close assertions/evidence; paper_performance arithmetic | Yes with scope | Arithmetic assumes $300k; absent evidence not clearly distinguished | Campaign-aware arithmetic; separately label persisted/not-run evidence |
| Telegram flowing / configured? | v2_alert_outbox; ops_notification_outbox; Intelligence delivery; notify resolver | Yes within each producer scope | V2 partial; no unified logical/physical view | Counts, retry/failure timestamps, safe config metadata, no credential output |
| Company event routing? | Intelligence TelegramSenderAdapter | Materiality gate yes; destination bypass no | Direct shared TelegramClient | Resolve TRADE_EVENT; processing failures to bounded OPERATIONS |
| Degraded health routing? | V2 source state; Intelligence poll failures | Yes | RI-2 producer gap | Bounded hour-deduplicated operational events |
| Intraday isolation? | DispatchAgent direct TelegramClient | No release boundary | Shared primary credentials possible | Research-only default-off transport boundary |
| Reads safe? | Dashboard mode=ro; V2 run --mode status | Dashboard mostly; status no | Status constructs V2Store and V2Service | Status exits before any writable constructor |

Evidence reused: Package 1–5 READMEs, Package-2 acceptance review, RI-1/RI-2
READMEs; authoritative product sessions 9–13 and OPS-002/003/012–025.
This map was written before source changes. No historical audit restarted.
