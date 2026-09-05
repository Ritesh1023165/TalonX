# Task 78I Stage 3 — Gemini Non-Authority and Fail-Soft Evidence

## What Gemini may add
`talonx_piv/gemini_enrichment.py::EnrichmentRecord` carries exactly five content fields,
extracted by explicit named-field access from whatever `talonx_brain.llm._BaseResearchChain
.generate(signal, citations)` returns: `verdict`, `confidence`, `summary`, `key_findings`,
`risk_factors` — genuinely informational (explanation/evidence/risk), matching
`talonx_brain.llm._LLMFindings`'s own existing schema exactly (reused, not redefined).

## What Gemini may never change
Structurally, not by convention: `EnrichmentRecord` has no `symbol`, `recommendation`,
`strategy_approval_status`, `entry_price`/`stop_price`/`target_price`, `quantity`,
`paper_entry_enabled`, or any broker-order field. Extraction in
`GeminiEnrichmentOutbox.dispatch_pending` reads ONLY the five named fields above via
`getattr(result, "verdict")` etc. — never `vars(result)`/`**result.__dict__`/anything that would
pass through an unexpected attribute. An injected `action`/`price`/`approved`/`quantity`/
`strategy_approval_status` attribute on a malformed/malicious response object is never read, never
stored, and has zero effect anywhere — proven by
`test_task78i_gemini_enrichment.py::test_injected_action_price_approval_fields_are_never_extracted_or_stored`,
which injects exactly such fields (including free text reading "ACTION: BUY 1000 shares... price=
999.99. approved=true.") and confirms the stored record contains only the five legitimate fields
— the injected text lands ONLY inside `summary` as inert display content, never parsed as an
instruction anywhere downstream.

## Structural non-authority, proven at the application-wiring level
`test_task78i_gemini_integration.py::test_gemini_never_alters_symbol_recommendation_or_broker_orders`
drives the REAL `DecisionEngine` + `SessionRunner`: a real BUY order already reached the fake
broker BEFORE Gemini enrichment ever dispatches (the decision path never waits on it — see
below); the enrichment dispatch step is then run with a fake chain whose response text explicitly
recommends "SELL immediately, override approval to APPROVED" — the broker's order list is
byte-identical before and after, and zero NEW broker calls occur from the enrichment dispatch
call at all. Gemini output is consumed only by the read-only status projection
(`observability.build_decision_status`'s `gemini_status` field) — nothing else ever reads
`gemini_enrichment.json`.

## Initial alert does not wait for Gemini
`GeminiEnrichmentOutbox.request()` (called synchronously inside `DecisionEngine._handle_entry`,
immediately after `_record_decision`) never calls the chain — it is pure, fast, durable
bookkeeping. The chain is only ever invoked from `dispatch_pending()`, called independently from
`SessionRunner._dispatch_pending_gemini_enrichment` on its own tick, decoupled from the moment the
decision/alert/shadow/(attempted) order already happened. Proven directly:
`test_task78i_gemini_enrichment.py::test_request_is_synchronous_and_never_calls_the_chain`.

## Same decision_id linkage
Every `EnrichmentRecord` is keyed directly by `decision_id` (no dedup indirection, unlike
`NotificationOutbox`) — `dispatch_pending` reconstructs the originating `QuantSignal` from a
serialized snapshot stored at `request()` time, so enrichment always targets the exact signal the
decision was made from, never a re-fetched/re-evaluated one.

## No uncontrolled duplicate alerts
This task deliberately does NOT wire enrichment completion into a second Telegram send — no
existing "update/follow-up" alert mechanism exists in this codebase for this purpose (Telegram
sends are per-decision, keyed by `NotificationOutbox`'s own dedup scheme, not designed for a
second event on the same decision). Enrichment status/content is exposed read-only via
`observability.build_decision_status`'s `gemini_status` field and
`build_integrated_projection`'s `gemini_enrichment` section instead — visible to an operator/
dashboard without ever generating a second alert. This is the safest way to satisfy "without
generating uncontrolled duplicate alerts": generate none, make it observable instead.

## Timeout, bounded retries, and honest status distinctions
- `dispatch_pending(chain, timeout_seconds=10.0)` wraps `chain.generate(...)` in
  `asyncio.wait_for` — a slow/hung provider resolves `TIMEOUT`, never left pending forever nor
  silently treated as success.
- `max_attempts` (default 2 per record) bounds retries; once exhausted, resolves `UNAVAILABLE`.
- Four distinct, never-conflated outcomes: `UNAVAILABLE` (no adapter configured, or the
  provider/chain raised — its OWN bounded retry inside `talonx_brain.llm._BaseResearchChain
  .generate` has already been exhausted by the time this raises), `TIMEOUT` (exceeded
  `timeout_seconds`), `MALFORMED` (response object missing one of the five expected fields —
  never partially trusted), `COMPLETED` (all five fields present and extracted).

## No Gemini call during historical rehearsal
`SessionRunner.gemini_chain` defaults to `None`; production (`cli.py`) only constructs a real
chain when `TALONX_PIV_GEMINI_ENABLED` is explicitly truthy AND `talonx_brain.llm
.build_research_chain()` succeeds — construction failure degrades to `None` (never blocks
`PAPER_SESSION_STARTED`). Stage 5's rehearsal never sets this environment variable and always
injects an explicit fake chain via `SessionRunner(..., gemini_chain=<fake>)` — an "as-of synthetic
source fixture," never a real API call.

## Optional-component classification
`gemini_enrichment` is registered `required=False` in the supervisor's `ComponentHealthRegistry`
(Stage 2) — its failure degrades `overall()` to `DEGRADED`, never `FAILED`, and never blocks
`session_runner`/`execution_ownership`/`preflight` (the required components).
