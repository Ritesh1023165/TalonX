# Sentinel DTU universe visibility and operator overrides (2026-09-30)

- **Commits:** code 68d620e.
- **Deployment:** **Sentinel only**, at 2026-09-30T18:06:44Z.
  - Declaration #22, class OPERATIONS_ONLY.
  - Version `d60d6073cb2f` → `29c423cc9f4e`.
  - The Telegram offset is preserved (`next_offset` 920191872 before and after), so there is no replay.
- **Unchanged:** mutation mode stays **DRY_RUN**. No other component restarted; notifier, promotion, ingestion and
  discovery kept their PIDs.
- **Evidence files:** `pre_change.txt`, `post_change.txt`, `sample_outputs.txt`.
  - The samples ran against **live** DTU state with a **sandbox copy** of `operator_control.db`, so no real override
    was recorded.

## State model

| Concept | Source | Mutated by operators? |
|---|---|---|
| SYSTEM_STATE | `market.db` `dtu_snapshot`: ACTIVE_CORE, EVENT_ELIGIBLE, AUTO_EXCLUDED, STRUCTURALLY_EXCLUDED | **never** |
| OPERATOR_OVERRIDE | `operator_control.db` `operator_overrides` (current value), plus an append-only `override_requests` log: NONE, FORCE_ACTIVE, FORCE_ELIGIBLE, FORCE_EXCLUDED | yes, as PENDING while in DRY_RUN |
| EFFECTIVE_STATE | derived; see below | — |

**How the effective state is derived:**
- It comes from the **production** `universe_tiers.resolve()`. The Sentinel host injects it, so `talonx_ops` never
  imports the opportunity lane.
- "Active" = the latest `dtu_active` set, which is exactly what ingestion fetches and discovery evaluates.
- Therefore `FETCH_ELIGIBLE = DISCOVERY_ELIGIBLE = in that set`.

**Precedence:** unchanged. The existing `resolve()` order is:
1. Position or intent safety.
2. OPERATOR_EXCLUDED.
3. OPERATOR_ADDED / V2 scope.
4. Structural exclusions and floors.
5. Core.
6. Live promotion.
7. Lifecycle protection.
8. Event-eligible.

**`/universe move` adds its own safety hold:** FORCE_EXCLUDED or FORCE_ELIGIBLE on a symbol with an open position, a
pending intent or V2 scope is recorded as `HELD_PROTECTED` and **not** as a pending override.

## Command semantics

| Command | Meaning |
|---|---|
| `/universe active` | the effective active set now: Core + event-promoted + operator/V2 + protected, with no double counting |
| `/universe eligible` | system EVENT_ELIGIBLE **and not active now**; these names are reachable by the event tier |
| `/universe excluded` | system AUTO_EXCLUDED only. **Changed:** previously this showed every non-Core name |
| `/universe structural` | system STRUCTURALLY_EXCLUDED, kept separate |
| `/universe core` | the system D-1 Core. V2-scope Core names resolve as operator-added. |
| `/universe promoted` | resolved EVENT_PROMOTED: a live gap or 8-K promotion, or lifecycle protection |
| `/universe list` | an explanatory redirect listing operator intent. It never says "0 active". |
| `file` option | a CSV with the requested columns; unavailable fields are left out, never invented |

## Future ACTIVE contract and gaps

**FORCE_ACTIVE and FORCE_EXCLUDED:**
- They are mirrored, in the same transaction, into the legacy intent tables that the **existing** ACTIVE-mode gates
  already consume.
- A FORCE_ACTIVE move writes `operator_universe` ACTIVE; a FORCE_EXCLUDED move writes `symbol_exclusions` EXCLUDED.
  NONE clears both.
- In DRY_RUN the gates are exact identities, and a test proves it.

**FORCE_ELIGIBLE: architectural gap.**
- Neither the fetch gates nor `resolve()` can demote a Core or active symbol to event-tier-only.
- It is therefore recorded as intent only, and the reply says so.
- Activating it needs a reviewed change to `resolve()` and the gates, which is a STRATEGY_MATERIAL boundary for
  ingestion and discovery.

**Pre-existing, unrelated to this change:**
- The running promotion (`f0c3b237`) and notifier (`4f669052`) versions differ from the hashes computed from the
  current tree (`6a1a96dc`, `b46e428d`), with or without this change.
- They were not restarted, and this change touches none of their sources.
