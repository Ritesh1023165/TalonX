# Broad universe

**Command:** `python -m talonx_premarket universe`, written to `results/premarket_research/universe.json` (gitignored; rebuild daily).

**Code:** `talonx_premarket/universe.py`. **Tests:** `test_universe_is_deterministic_auditable_and_broader_than_39`.

## Sources (free, already used by TalonX)

- **Alpaca `GET /v2/assets`** (`status=active&asset_class=us_equity`): symbol, name, exchange, tradable.
- **SEC `company_tickers.json`**: registrant ticker → CIK. This is the Intelligence lane's cached copy at `~/.talonx/intelligence/company_tickers.json`. The CIK is also the catalyst join key.

## Rules

The rules are applied in order, and the first match decides. Every symbol ends up either ELIGIBLE or EXCLUDED with exactly one reason code. The output is sorted by symbol, so it's deterministic and doesn't depend on input order.

| # | Rule | Reason code |
|---|---|---|
| 1 | `class == us_equity` | `NOT_US_EQUITY` |
| 2 | `status == active` | `INACTIVE` |
| 3 | `tradable` | `NOT_TRADABLE` |
| 4 | exchange in NYSE, NASDAQ, AMEX, ARCA, BATS (OTC excluded) | `NOT_LISTED_EXCHANGE` |
| 5 | symbol matches `^[A-Z]{1,5}(\.[A-Z])?$` (class shares such as `BRK.B` kept) | `MALFORMED_OR_NON_COMMON_SYMBOL` |
| 6 | name is not an ETF/ETN/fund/index/leveraged product | `FUND_ETF_ETN` |
| 7 | name is not a warrant | `WARRANT` |
| 8 | name is not a right | `RIGHT` |
| 9 | name is not a unit | `UNIT` |
| 10 | name is not a preferred | `PREFERRED` |
| 11 | name is not a note, debenture or `%` coupon | `NOTE_DEBT` |
| 12 | not "Depositary Shares" unless "American Depositary" (ADRs kept) | `DEPOSITARY_NON_ADR` |
| 13 | ticker is an SEC registrant (has a CIK) | `NOT_SEC_REGISTRANT_TICKER` |

There is deliberately **no** price, liquidity or market-cap filter at the universe level. Those are data-time hard gates (see SCORING.md), so the universe doesn't overfilter.

## Result (built 2026-09-23 from live Alpaca + SEC data)

| | Count |
|---|---|
| **TOTAL** (Alpaca active us_equity assets) | **14,373** |
| **ELIGIBLE** | **5,655** (145× the V2 39-name scope) |
| **EXCLUDED** | **8,718** |

**Eligible by exchange:** NASDAQ 3,391 · NYSE 1,997 · AMEX 246 · ARCA 20 · BATS 1.

**Excluded by reason:**

| Reason | Count |
|---|---|
| FUND_ETF_ETN | 5,968 |
| NOT_TRADABLE | 878 |
| MALFORMED_OR_NON_COMMON_SYMBOL | 447 |
| WARRANT | 410 |
| NOT_LISTED_EXCHANGE | 308 |
| UNIT | 274 |
| NOTE_DEBT | 167 |
| RIGHT | 126 |
| PREFERRED | 109 |
| NOT_SEC_REGISTRANT_TICKER | 26 |
| DEPOSITARY_NON_ADR | 5 |

All 39 V2 execution-scope symbols are ELIGIBLE. The V2 scope is read, never modified: the engine only labels each alert "in V2 39-name scope" or "outside V2 scope". V2 keeps executing on its own 39 names only.

**Known limitation:** name-based instrument typing is a transparent heuristic. An operating company whose legal name contains "Fund" or "Index" would be excluded, and a fund whose name avoids every keyword would be kept. Both are visible in `universe.json`, with the reason per symbol.
