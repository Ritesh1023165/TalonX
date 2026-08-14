# `talonx_brain` — Module 3: Deep Research Agent & RAG Engine

```
talonx:signals:quant (Redis)
    → parse + validate each message as QuantSignal
    → cache-first: brain_cache:{ticker} in Redis has a FRESH entry?
        yes → skip retrieval AND the LLM call entirely, republish it
              (from_cache=True) -- this is the actual LLM-spend reduction
        no  → acquire lock:brain:{ticker} (distributed lock -- guards
              against a cache stampede if this ever runs as more than one
              process); lost the race? wait briefly for the winner's
              cache write, else generate anyway rather than block forever
    → retrieve top-K relevant chunks from ChromaDB's "sec_filings"
      collection, scoped to the signal's ticker (same store, same
      embedding model Module 1 wrote it with)
    → ALSO retrieve top-K relevant chunks from the "news_feed" collection,
      same ticker scope (optional -- TALONX_BRAIN_INCLUDE_NEWS, on by
      default; see retriever.py)
    → zero chunks retrieved at all (cold start)? bypass the LLM entirely,
      publish an INSUFFICIENT_CONTEXT report immediately
    → otherwise, build a structured RAG prompt (technical trigger + filing
      excerpts + news excerpts) and run it through the configured LLM
      provider (TALONX_BRAIN_LLM_PROVIDER, "gemini" by default or "ollama"
      for a local model -- see below) with a structured-output schema
      (verdict / confidence / summary / key findings / risk factors)
        LLM call fails? → stale (expired) brain_cache entry exists?
                            yes → republish it, flagged is_stale=True
                            no  → publish a DEGRADED report instead
                                  (verdict=neutral, confidence=0.0,
                                  is_degraded=True)
    → assemble a ResearchReport (LLM findings + the original QuantSignal +
      citation objects for every retrieved chunk, filing or news)
    → cache the result (brain_cache:{ticker}, unless it's degraded or
      itself a stale republish) and publish to Redis (talonx:reports:brain)

talonx:filings:events (Redis, published by talonx_ingest.pipeline)
    → NewFilingIngestedEvent for ticker X → DELETE brain_cache:X outright
      (not just marked stale -- a new filing genuinely invalidates old
      analysis, so it shouldn't be resurrected as a stale fallback either)
```

- **`retriever.py`** — unlike `talonx_quant`, this module is NOT
  self-contained at the code level: it imports
  `talonx_ingest.storage.vector_store.VectorStore` directly rather than
  re-declaring a Chroma client, because retrieval must run through the
  exact embedding function and persist directory Module 1 used to write
  each store — a mismatch there would silently return meaningless
  similarity scores, not just an error. It only inherits Module 1's
  `TALONX_CHROMA_*` / `TALONX_NEWS_CHROMA_COLLECTION` settings; there's no
  separate copy to drift out of sync. Queries `sec_filings` and
  `news_feed` independently (`ContextRetriever`, `TALONX_BRAIN_RETRIEVAL_TOP_K`
  and `TALONX_BRAIN_NEWS_TOP_K` respectively) and concatenates the
  results — filings first, then news — rather than re-ranking across
  collections by distance, since cosine distance is only comparable
  within one collection (same embedding model, same query), and filing
  text vs. news text have very different length/style profiles. Set
  `TALONX_BRAIN_INCLUDE_NEWS=false` to disable the news half and fall
  back to filings-only.
- **`llm.py`** — asks the LLM for a deliberately narrow structured output
  (verdict, confidence, summary, key findings, risk factors) rather than
  the full `ResearchReport` — ticker, the triggering signal, citation
  objects, model name, and timestamps are all assembled by Python code
  that already has them exactly right, instead of asking the model to
  echo data it could get wrong. Two provider implementations share one
  retry/backoff loop (`_BaseResearchChain.generate()`) and the same
  `generate(signal, citations) -> _LLMFindings` interface, so
  `consumer.py` never has to know which one is active:
  - **`GeminiResearchChain`** (default, `TALONX_BRAIN_LLM_PROVIDER=gemini`
    or unset) — cloud, via `langchain-google-genai`. Self-throttles with a
    token-bucket rate limiter (`TALONX_BRAIN_GEMINI_RPM`, default 5/min --
    match it to your actual quota) so a burst of signals paces itself
    under the free tier's per-MINUTE quota instead of retrying into
    repeated 429s. There's also a separate, unrelated free-tier quota this
    doesn't protect against — see [performance.md](../performance.md).
  - **`OllamaResearchChain`** (`TALONX_BRAIN_LLM_PROVIDER=ollama`) — local,
    via `langchain-ollama`, talking to a locally-running `ollama serve`.
    No API key, no rate limiter (nothing to throttle against — see
    [performance.md](../performance.md) for full setup and tradeoffs).
- **`consumer.py`** — same reconnect-with-backoff Redis listener shape as
  `talonx_quant.consumer`, subscribed to BOTH `talonx:signals:quant`
  (research trigger) and `talonx:filings:events` (cache invalidation --
  the publish side already existed in `talonx_ingest.pipeline`, this
  module just added the subscriber). Per-signal orchestration is
  cache-first → retrieve → generate → publish (see `cache.py` above), with
  an LLM failure falling back to a stale cache entry, then a degraded
  report, rather than just dropping the signal -- see the diagram. A
  failure that isn't otherwise handled (a genuinely broken payload, etc.)
  is logged and skipped rather than killing the listener.
- Publishes a `verdict` of `"insufficient_context"` (distinct from
  `"neutral"`) when retrieval comes back empty -- **bypassing the LLM
  call entirely** rather than spending a call asking the model to notice
  it has nothing to work with.
- **`cache.py`** — `BrainCache`, the Redis-backed qualitative cache
  (`brain_cache:{ticker}`) behind the cache-first flow in the diagram
  above. The one non-obvious design point: an "expired" entry still needs
  to be usable as a fallback (see below), but Redis's own `EX` TTL just
  DELETES a key once it elapses -- so every entry embeds its OWN logical
  `expires_at` inside the JSON payload and is written under a much longer
  Redis-level safety-net TTL (`TALONX_BRAIN_CACHE_SAFETY_TTL`, default
  6h); reads compare `now` against the embedded timestamp, not Redis's
  remaining TTL. `expires_at` at write time is the SOONER of a base TTL
  (`TALONX_BRAIN_CACHE_BASE_TTL`, default 2h) or the next daily
  market-open/close boundary (`TALONX_BRAIN_MARKET_TZ`, default
  `America/New_York`, via `zoneinfo` so EST/EDT is handled automatically;
  `TALONX_BRAIN_MARKET_OPEN_HOUR`/`_CLOSE_HOUR`, default 9/16) -- so
  cached research never outlives the trading session it was generated
  for. No holiday/weekend trading-calendar awareness -- see
  [../roadmap.md](../roadmap.md). The distributed lock
  (`lock:brain:{ticker}`, `TALONX_BRAIN_CACHE_LOCK_TTL`) and its bounded
  wait (`TALONX_BRAIN_CACHE_LOCK_WAIT_SECONDS`, default 20s) only matter
  if `talonx_brain.run` is ever scaled to more than one process -- today's
  single-process consumer always acquires it immediately.
  `TALONX_BRAIN_CACHE_ENABLED=false` disables caching entirely (an escape
  hatch for debugging prompt changes, where a stale hit would be actively
  misleading).
- Wired into `run_talonx.py` as a third continuous task (see
  [orchestrator.md](orchestrator.md)) -- but OPTIONALLY: on the `gemini`
  provider, if `GEMINI_API_KEY` isn't set, the orchestrator logs a
  warning and runs Modules 1+2 without it rather than crashing (this
  check doesn't apply to the `ollama` provider, which has no API key to
  check). Run it standalone instead ([../running.md](../running.md)) if
  you want it decoupled from the other two.

## Long-term (fundamentals) research chain

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for
`build_long_term_research_chain` — moat rating, capital-allocation
assessment, DCF fair value per share, and a 0-10 quality score, plus the
horizon-aware cache TTL (90-day flat cap for long-term entries, no
market-hours-boundary math).
