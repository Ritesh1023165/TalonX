# Throughput Profile & the Gemini Model Tradeoff (read before scaling)

This document exists because Module 3's Gemini model choice was NOT a
one-time decision — over the course of building it we hit three dead ends
in a row (a retired model, a zero-quota model, a newly-restricted model)
before landing on the current configuration. Model availability and
quotas on Google's free tier are a moving target; the goal here is that
the next person (or future you) can read this instead of re-discovering
the same failure modes from scratch.

## 1. Current effective throughput, per module

| Module | Component | Effective throughput | Hard cap in code? | Tune via |
|---|---|---|---|---|
| 1 | SEC EDGAR client | 8 req/sec, 4 concurrent (token bucket) | Yes | `TALONX_SEC_RPS`, `TALONX_SEC_CONCURRENCY` |
| 1 | News ingestion (NewsAPI/RSS) | Unthrottled locally — one call per ticker per ingestion cycle, backoff-retry only | No | `TALONX_NEWS_MAX_RETRIES` (retries, not rate) |
| 1 | News ingestion — Reddit (optional) | 60 req/min (token bucket), one search call per subreddit per ticker per cycle | Yes | `TALONX_REDDIT_RPM` |
| 1 | Market data — yfinance fallback | 1 batched poll every 12s (this deployment; default 5s) covering ALL tracked tickers in a single call | Yes (poll interval) | `TALONX_YF_POLL_INTERVAL` |
| 1 | Market data — Polygon WebSocket | Real-time push, bounded by your Polygon plan tier, not by this code | No local cap | Polygon-side (plan tier) |
| 2 | Quant scanner — bar PROCESSING | No artificial cap — processes each BAR event synchronously as it arrives off Redis; sub-millisecond `pandas_ta` compute per bar | No | n/a |
| 2 | Quant scanner — signal OUTPUT (what actually reaches Redis) | Per-ticker: locked out for `TALONX_QUANT_LOSS_LOCKOUT_SECONDS` (default 75 min) after a losing paper trade, and `TALONX_QUANT_COOLDOWN_SECONDS` (default 20 min) after any signal. Globally: at most `TALONX_QUANT_THROTTLE_MAX_SIGNALS` (default 3) published per `TALONX_QUANT_THROTTLE_WINDOW_SECONDS` (default 60s), ranked by (confluence score, volume surge ratio) — see [modules/quant.md](modules/quant.md), §5 below | Yes (both) | `TALONX_QUANT_COOLDOWN_SECONDS`, `TALONX_QUANT_LOSS_LOCKOUT_SECONDS`, `TALONX_QUANT_THROTTLE_*` |
| 3 | talonx_brain (Gemini) | **5 requests/minute (~0.083 req/sec)**, token-bucket paced | Yes — see §2 | `TALONX_BRAIN_GEMINI_RPM` |
| 4 | talonx_core (correlate + decide) | No artificial cap on PROCESSING — in-memory dict lookups and comparisons, no external calls, sub-millisecond per message. In practice bounded entirely by how fast Modules 2/3 feed it | No (processing); per-ticker cooldown only (see [modules/core.md](modules/core.md)) | `TALONX_CORE_TICKER_COOLDOWN` |
| 5 | talonx_dispatch — audit trail write | No artificial cap, sub-millisecond local SQLite insert per alert | No | n/a |
| 5 | talonx_dispatch — Telegram push | No PROACTIVE rate limiter (unlike Reddit/Gemini) — deliberately: by the time an alert reaches here it's already gated by talonx_core's cooldown AND upstream-bottlenecked by talonx_brain's ~5/min, so the realistic push rate is already well under Telegram's own flood-control limits (~1 msg/sec to one chat). Reactive retry (respecting Telegram's own `RetryAfter` hint) handles the rest | No | `TALONX_DISPATCH_TELEGRAM_MAX_RETRIES` |

**Module 3 is the bottleneck of the entire pipeline by 2+ orders of
magnitude** — it's the only component paying for LLM inference against a
free-tier quota, while everything upstream can produce `QuantSignal`s far
faster than Module 3 can research them. Module 2's own cooldown/throttle
(above) narrows that gap somewhat — capping output at 3/min globally
means Module 3 is no longer asked to research every raw threshold
breach — but it's a noise filter, not a rate-matching mechanism; it
wasn't tuned against Module 3's ~5/min Gemini limit and can still
outpace it. Under a burst (many tickers
crossing thresholds around the same time, e.g. a correlated market move),
reports queue up behind the rate limiter rather than being dropped or
erroring — expect multi-minute delay between signal and report during a
burst, not a failure. Module 4 inherits this same lag downstream of it:
since it only alerts once BOTH halves of a pair have arrived, its
effective alert rate is capped by however fast talonx_brain can produce
reports, not by anything talonx_core itself does. One caveat worth
knowing if you scale the ticker list up significantly: Redis Pub/Sub
(used for `talonx:signals:quant` and `talonx:reports:brain`) is not a
durable queue — if a subscriber falls far enough behind, Redis can drop
it under its `client-output-buffer-limit pubsub` setting. At 5 req/min
this has not been observed to matter in testing, but if you outgrow it,
Redis Streams (consumer groups, replayable) would be the fix, not this
rate limiter.

## 2. Current Gemini configuration (as of Aug 2026) and why

```
TALONX_BRAIN_GEMINI_MODEL          (unset -> default "gemini-flash-latest")
TALONX_BRAIN_GEMINI_RPM            (unset -> default 5)
TALONX_BRAIN_GEMINI_TEMPERATURE    (unset -> default 0.2)
TALONX_BRAIN_GEMINI_MAX_TOKENS     (unset -> default 2048)
TALONX_BRAIN_GEMINI_MAX_RETRIES    (unset -> default 3)
TALONX_BRAIN_GEMINI_BACKOFF_BASE   (unset -> default 2.0 seconds)
TALONX_BRAIN_GEMINI_BACKOFF_MAX    (unset -> default 30.0 seconds)
TALONX_BRAIN_RETRIEVAL_TOP_K       (unset -> default 6 chunks/signal)
```

**How we got here** (chronology, so the same dead ends aren't repeated):
1. Started with `gemini-1.5-pro` (the original module spec's model) —
   retired from the API entirely (`404 NOT_FOUND`).
2. Tried `gemini-2.5-pro` — a real, listed model, but the free tier grants
   literal **zero** quota for Pro models (`limit: 0` in the 429 response
   body); requires a billing-enabled Google Cloud project.
3. Tried `gemini-2.5-flash` — appears in `client.models.list()`, but
   returns `404 ... no longer available to new users` (an API-key-age
   restriction, not a real deprecation — confusing because it's still
   "listed").
4. Landed on `gemini-flash-latest` — Google's own alias for "current
   recommended Flash model." Verified working with a live call; at time
   of writing it resolves to `gemini-3.6-flash`, which DOES carry free
   quota, but only **5 requests/minute** (confirmed from the live 429
   body: `quotaValue: '5'`, metric
   `generate_content_free_tier_requests`).
5. Added the token-bucket rate limiter in `llm.py` (`_TokenBucket`) so
   Module 3 paces itself under that quota proactively, instead of
   retrying into repeated 429s under any real signal volume.
6. Tried overriding `TALONX_BRAIN_GEMINI_MODEL` to a pinned
   `gemini-2.5-flash-lite` for lower latency/cost — same "no longer
   available to new users" 404 as `gemini-2.5-flash`. The whole 2.5
   generation appears restricted for this key, not just the Flash tier.
   `gemini-flash-lite-latest` (the Lite-tier alias) worked.
7. **And one more wall, distinct from all of the above**: after extended
   same-day testing on `gemini-flash-lite-latest` (resolved to
   `gemini-3.5-flash-lite`), hit `429 RESOURCE_EXHAUSTED` with
   `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
   `limit: 500` — a PER-DAY cap, not the per-minute one steps 4-5 already
   handle. `_TokenBucket` paces requests/minute; it has no concept of a
   daily budget, so nothing in `llm.py` protects against this one. The
   quota is scoped per-model (not per-project), so a different model has
   its own separate 500/day allowance — but the real fix, given how many
   separate free-tier walls this chronology has now hit, was to stop
   depending on Gemini's free tier being reliably available for active
   development at all: `llm.py` now supports a second provider
   (`TALONX_BRAIN_LLM_PROVIDER=ollama`, §4 below) with no quota of any
   kind.

**Aliases verified working against this key** (live-tested, not just
"listed" — `client.models.list()` returning a name is NOT the same as it
actually accepting a `generateContent` call, as steps 3 and 6 above
show):

| Alias | Tier | Verified | Notes |
|---|---|---|---|
| `gemini-flash-latest` | Flash | Yes | Current default. Resolved to `gemini-3.6-flash` at last check; 5 req/min free tier. |
| `gemini-flash-lite-latest` | Flash-Lite | Yes | Lower latency/cost than Flash; free-tier RPM not yet separately confirmed — verify with `client.models.list()` + https://ai.dev/rate-limit before assuming it matches Flash's 5/min. |
| `gemini-pro-latest` | Pro | **No** — not yet tested | Free tier grants zero quota for Pro (see step 2); requires billing enabled first (§3). Confirm with a live call before relying on it, same as every other row here. |

**Verdicts aren't fully deterministic between runs.** `gemini_temperature`
defaults to `0.2` (low but nonzero). Observed live: the identical
`rsi_overbought_volume_surge` AAPL signal, with effectively the same 6
filing + 3 news citations retrieved, produced `verdict: "bullish"`
(confidence 0.4) on one run and `verdict: "bearish"` (confidence 0.85) on
a re-run moments later — a finely-balanced call (bearish technical signal,
mixed bullish/bearish context) can genuinely land either way at this
temperature. This is expected model sampling behavior, not a bug. If you
need reproducible verdicts (e.g. for backtesting), set
`TALONX_BRAIN_GEMINI_TEMPERATURE=0` — note this makes the model more
deterministic but not necessarily "more correct."

**Pinned model name vs. alias — the tradeoff that matters most:**
- **Pinned** (e.g. `gemini-3.5-flash`, `gemini-3.1-pro-preview`):
  reproducible behavior forever, but WILL eventually 404 when Google
  retires or restricts it — as happened twice above — silently, the next
  time the process restarts.
- **Alias** (`gemini-flash-latest`, `gemini-pro-latest`): survives that
  churn automatically (Google keeps it pointed at something current), but
  isn't reproducible — the underlying model, and therefore latency/quality/
  cost, can shift between runs without any code change on our side.
- **Current choice: alias.** We're optimizing for "keeps working without
  maintenance" over "pinned reproducibility." Revisit this if you need the
  latter — e.g. a backtested/audited research pipeline where consistent
  model behavior across runs matters more than zero-maintenance.

**Flash vs. Pro:**
- Flash: faster, cheaper, available on the free tier. For this module's
  actual job — grounding or challenging a technical signal against a
  handful of retrieved filing excerpts — Flash has been sufficient in
  testing (the `insufficient_context` verdicts observed were the
  *correct* call given genuinely irrelevant retrieved context, not a
  reasoning-quality miss).
- Pro: deeper reasoning, likely better at synthesizing across more/longer
  excerpts or more nuanced multi-document analysis — but zero free-tier
  quota, so it's a hard requirement to enable billing first.

**Free tier vs. paid:** the observed 5 req/min free-tier cap is the
tightest constraint in the whole pipeline (see §1). Paid tiers raise
per-model RPM substantially (varies by model and plan — check
https://ai.google.dev/gemini-api/docs/rate-limits for current numbers,
don't trust the figures in this document to still be accurate) and unlock
Pro models entirely.

## 3. Upgrade path: moving to a faster/Pro model later

1. **Enable billing** on the Google Cloud project backing your
   `GEMINI_API_KEY` (console.cloud.google.com → link a billing account to
   the project tied to your AI Studio key). This is what unlocks nonzero
   Pro quota and typically raises Flash RPM too.
2. **Re-verify what's actually available and its quota** under the new
   plan — don't assume, check:
   ```powershell
   python -c "from talonx_brain.config import BrainConfig; from google import genai; c = genai.Client(api_key=BrainConfig().gemini_api_key); [print(m.name) for m in c.models.list() if 'generateContent' in (m.supported_actions or [])]"
   ```
   Cross-reference actual per-model limits at https://ai.dev/rate-limit —
   these differ by plan tier and change over time.
3. **Set `TALONX_BRAIN_GEMINI_MODEL`** in `.env` at the repo root:
   - `gemini-pro-latest` — alias, recommended default if you want "current
     best Pro model, zero maintenance," mirroring the Flash choice made
     here.
   - Or a pinned snapshot (e.g. `gemini-3.1-pro-preview`) if you need
     reproducible behavior instead — see the pinned-vs-alias tradeoff in
     §2; you'll need to revisit this when it eventually gets retired.
4. **Raise `TALONX_BRAIN_GEMINI_RPM`** to match the new plan's actual
   limit, set slightly under the real quota (not exactly at it) to leave
   headroom for any other usage on the same key. This is the step that
   actually unlocks more throughput — changing the model alone does
   nothing while the rate limiter is still capped at 5.
5. **Optionally revisit** `TALONX_BRAIN_GEMINI_MAX_TOKENS` (Pro models may
   benefit from more headroom for deeper reasoning) and
   `TALONX_BRAIN_GEMINI_TEMPERATURE`.
6. **Re-run the validation flow before trusting it in production**: fire
   `send_test_signal.py --ticker <TICKER-WITH-INGESTED-FILINGS>` (see
   [running.md](running.md)) and confirm a `ResearchReport` publishes to
   `talonx:reports:brain` with the new model before assuming the upgrade
   worked.

## 4. Local alternative: Ollama (no API key, no quota)

`llm.py` supports a second, fully local LLM provider via
[Ollama](https://ollama.com) — a thin wrapper (`OllamaResearchChain`) over
`langchain-ollama`, sharing the exact same `generate(signal, citations) ->
_LLMFindings` interface as `GeminiResearchChain` (`_BaseResearchChain` in
`llm.py`). `consumer.py` and `run_talonx.py` never branch on which
provider is active — `build_research_chain()` (the factory in `llm.py`) is
the one place that does, picking based on `TALONX_BRAIN_LLM_PROVIDER`.

**Setup:**
```powershell
# 1. Install Ollama (Windows installer, runs as a background service)
#    https://ollama.com/download

# 2. Pull a model that supports tool calling (needed for
#    with_structured_output(_LLMFindings) -- see "model choice" below)
ollama pull llama3.1

# 3. Confirm the service is up and the model is present
ollama list

# 4. Point talonx_brain at it
pip install -r talonx_brain\requirements.txt   # now also installs langchain-ollama
```
In `.env` at the repo root:
```
TALONX_BRAIN_LLM_PROVIDER=ollama
```
No `GEMINI_API_KEY` needed for this path — `GeminiResearchChain`'s API-key
check in `llm.py` only runs when the `gemini` provider is selected.

**Config knobs** (all in `talonx_brain/config.py`, `TALONX_BRAIN_OLLAMA_*`
env vars — kept fully separate from `TALONX_BRAIN_GEMINI_*` on purpose, so
switching providers back and forth can never accidentally reinterpret one
provider's tuned values as the other's):
```
TALONX_BRAIN_OLLAMA_BASE_URL       (unset -> default "http://localhost:11434")
TALONX_BRAIN_OLLAMA_MODEL          (unset -> default "llama3.1")
TALONX_BRAIN_OLLAMA_TEMPERATURE    (unset -> default 0.2)
TALONX_BRAIN_OLLAMA_MAX_RETRIES    (unset -> default 3)
TALONX_BRAIN_OLLAMA_BACKOFF_BASE   (unset -> default 2.0 seconds)
TALONX_BRAIN_OLLAMA_BACKOFF_MAX    (unset -> default 30.0 seconds)
```

**No rate limiter.** `GeminiResearchChain` self-throttles with a
`_TokenBucket` to respect Google's free-tier quota; `OllamaResearchChain`
passes `bucket=None` to `_BaseResearchChain` — there's no cloud quota to
pace against, only your own machine's throughput. If signals arrive faster
than your hardware can generate reports, they simply queue up as pending
`asyncio.Task`s the same way any slow consumer would; nothing paces them
proactively today.

**Model choice.** Default is `llama3.1` (8B) — small enough for a typical
dev machine's CPU (or GPU, if Ollama detects one) and supports the
tool-calling method `langchain-ollama`'s `with_structured_output()` uses by
default to force the `_LLMFindings` schema. Any Ollama model with tool-
calling support works (e.g. `qwen2.5`, `mistral-nemo`) — a model WITHOUT
tool-calling support will fail structured-output calls with an error from
`with_structured_output()`, not silently degrade. Larger models are slower
per-request but reason more thoroughly; this hasn't been benchmarked
against Gemini's output quality for this specific grounding/challenging
task — treat it as a starting point to tune, not a verified equivalence.

**Tradeoffs vs. Gemini** (why this isn't just a strict upgrade):
- **For:** zero API key, zero quota of any kind (no per-minute OR per-day
  wall — see §2 step 7, the whole reason this provider exists), zero
  marginal cost, works offline, no risk of a model being retired/restricted
  out from under you.
- **Against:** uses your machine's CPU/GPU/RAM instead of Google's
  infrastructure — throughput and latency depend entirely on local
  hardware, and generation quality for a Flash-tier cloud model vs. a
  similarly-sized local model hasn't been directly compared here. Running
  Modules 1+2+3+4 together (`run_talonx.py`) while Ollama is also
  generating reports adds real local resource contention that a cloud
  provider doesn't.
- **Reasonable default:** Ollama for active local development and testing
  (where you'd otherwise burn through Gemini's free-tier quota fastest,
  as this whole section documents happening); Gemini (or a paid Gemini
  tier, §3) if you want cloud-hosted throughput independent of your own
  machine, e.g. for a longer-running or higher-ticker-count deployment.

## 5. `talonx_quant` noise filters: why, and what changed

Live log analysis surfaced two distinct alert-chatter problems, both
downstream of `talonx_quant` publishing a `QuantSignal` for literally
every bar a threshold condition held:

1. **Ticker-level duplication** — the same ticker alerting twice within a
   ~10-minute window as *different* indicators fired off the same
   underlying price move (e.g. an RSI+volume setup, then an unrelated
   MACD cross a few minutes later on the same name).
2. **Micro-burst clustering** — 8 separate signals across multiple
   tickers within 49 seconds, several of them technically-real but
   economically-meaningless crossovers (a $0.03 moving-average drift on a
   $500 stock, ~0.006% — nowhere near a real trend change).

Each was unfiltered noise reaching `talonx_brain`, which meant real LLM
calls (and real Gemini free-tier quota, §2) spent on setups nobody
would act on.

A LATER live paper-trading review found a different, more expensive
problem than noise: a 0.33 profit factor and 25% win rate, with 3
consecutive SMCI losses driving 93% of session losses — signals that
were individually well-formed but fired on routine-sized bars with no
real conviction behind them, then got re-entered again and again on a
name that had just proven it was chopping/declining. Four more filters
were added on top of the original noise filters below to address that.

**Eight filters total, layered in this order** ([modules/quant.md](modules/quant.md)
has the mechanics of each):

| # | Filter | Fixes | Where |
|---|---|---|---|
| 1 | Edge-triggering | A condition re-firing every bar it stays true (the underlying cause of most repeat alerts, ticker-duplication included) | `strategy.py` |
| 2 | Hysteresis (min spread) | Micro-crossovers with no real economic significance (the $0.03 MSFT case) | `strategy.py` |
| 3 | ATR-move gate | A signal firing on a routine, average-sized bar rather than a genuine directional move | `strategy.py` |
| 4 | Confluence score | Low-conviction single-indicator setups with no corroborating evidence (MACD cross / RSI extreme / volume surge) | `strategy.py` (computed) / `consumer.py` (filtered) |
| 5 | Risk/reward filter | Setups whose ATR-scaled upside doesn't justify the ATR-scaled downside | `strategy.py` (computed) / `consumer.py` (filtered) |
| 6 | Post-loss lockout | Repeat re-entry into a ticker that just closed a losing trade — the exact SMCI pattern above | `consumer.py` |
| 7 | Per-ticker cooldown | The remaining ticker-duplication case: genuinely different signal types firing close together in time | `consumer.py` |
| 8 | Batch throttle | Bursts across MANY tickers at once (a market-wide move) — global cap, ranked by (confluence, volume) | `consumer.py` |

Plus (Phase 2) the session-aware pre-market volume/liquidity/news-catalyst
gates and the 15-min 200-SMA trend gate — see
[modules/quant.md](modules/quant.md).

**Why this order:** 1-3 run inside `strategy.py` itself, before a
candidate signal exists at all — cheapest place to filter, and they
address *why* a signal would be spurious in the first place, not just how
often. 6-8 run in `consumer.py`, after candidates exist: post-loss
lockout and cooldown remove same-ticker repeats (for two different
reasons — a proven loss vs. any prior signal at all), and the throttle is
a last-resort global cap for exactly the cross-ticker burst scenario
nothing upstream addresses (each individual signal in an 8-in-49-seconds
burst can be perfectly legitimate on its own — the problem is the
aggregate rate, which only a cross-ticker view can see). Filter 4/5
(confluence + risk/reward) deliberately runs BEFORE filter 6/7's cooldown
lock is armed, even though it's listed after ATR/hysteresis — a
candidate that gets filtered out for low conviction must not still burn
the ticker's cooldown slot and block a later, better signal.

**The batch throttle's tradeoff, worth restating:** "rank by conviction,
keep the top N" cannot be done without buffering candidates for the full
window first — there's no way to know a signal is top-3 until you've seen
everything else that arrived in its window. Default window is 60s
(`TALONX_QUANT_THROTTLE_WINDOW_SECONDS`), so a signal can be delayed by
up to a minute before it's published or dropped. This was a deliberate
choice over a lower-latency micro-batch design (rank+release every
10-15s against a rolling cap) — the tradeoff there is real, ranking
would only compare candidates within each short batch rather than the
full minute, so an earlier lower-conviction signal could beat a
later higher-conviction one in the same minute. Revisit if the added
latency turns out to matter more than whole-minute ranking accuracy in
practice.

**Suppression is counted, not silent** — `QuantScanner`'s in-memory
counters (`signals_suppressed_cooldown`, `.signals_suppressed_throttle`,
`.signals_suppressed_loss_lockout`, `.signals_suppressed_low_confluence`,
`.signals_suppressed_low_risk_reward`, `.signals_suppressed_trend_gate`,
`.signals_suppressed_premarket_liquidity`) each track how much their
filter is actually removing, and all of them log a line per suppression
event plus persist a `(ticker, reason, count)` row when a
`QuantStateStore` is configured, for `generate_eod_report.py`'s
signal-funnel section, AND increment a Redis
`metrics:{date}:quant:failed_*` counter for the Streamlit dashboard's
Daily Funnel & Metrics tab (see [modules/dispatch.md](modules/dispatch.md)).
If noise is still getting through, or too much is being dropped, these
are the first thing to check — or run
`python scripts\ticker_funnel_report.py <TICKER>` for a live, per-ticker
breakdown.

## 6. yfinance session degradation and self-healing

A long-running `talonx_ingest.market_data.yfinance_poll.YFinancePoller`
can get its cached `yfinance` session stuck: Yahoo's undocumented API
occasionally returns a malformed/throttled response, and a bare dict-key
access deep in `yfinance` itself (`scrapers/quote.py`'s exchange-timezone
lookup) raises a plain `KeyError` instead of a clean, retryable exception.
Because `_fetch_snapshots` already catches every per-symbol exception and
just returns fewer events, a cycle where **every** symbol fails looked
identical to a healthy cycle to the outer retry loop — no backoff ever
engaged, and the process needed a manual restart to recover.

Fixed by treating a cycle where ≥50% of symbols fail
(`TALONX_YF_DEGRADED_FAILURE_RATE`) as a real failure — same backoff a
hard exception gets — and, after 3 consecutive degraded/failed cycles
(`TALONX_YF_SESSION_RESET_AFTER`), proactively resetting `yfinance`'s
cached session/crumb (`_reset_yfinance_session()`), reproducing the same
"fresh process" effect a manual restart used to provide. See
[troubleshooting.md](troubleshooting.md) for the exact symptom to look
for in logs.
