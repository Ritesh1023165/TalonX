"""Task 118E Part 5 -- ONE bounded, predeclared composition check.

PREDECLARED (written before any result is computed):
- Feature: 20-trading-day realized volatility (annualized stdev of daily
  log returns) of the issuer's OWN price series, using ONLY bars dated
  strictly BEFORE that issuer's first entry date in the respective
  population -- point-in-time correct by construction, no future data.
  Units: annualized %, computed as std(daily_log_return) * sqrt(252) * 100.
  Source: the same frozen local daily-bar CSVs used throughout Task 118
  (task95g_broad_cross_sectional/_daily, task107a_form4_feasibility/
  _prices) -- availability limited to whatever history exists before that
  entry date in those files.
- Sector/market-cap: EXPLICITLY OMITTED. No point-in-time sector or
  market-cap classification source was available in this bounded session;
  substituting a CURRENT classification and calling it point-in-time
  would violate this task's own instruction. Labelled as an unsupported,
  omitted feature, not silently dropped.
- Weighting: ISSUER-level, not trade-level (one observation per issuer,
  using that issuer's FIRST entry date in the population -- MSTR's 4
  trades in A count once, not four times).
- Comparison statistic: A's mean pre-entry volatility (its 6 issuers)
  vs. the distribution of mean pre-entry volatility of random 6-issuer
  draws (without replacement) from B's 101 issuers, 5000 draws, seed
  118118 (same seed family as the other Task 118D/E resampling).
  A's percentile rank within that null distribution is the reported
  statistic -- not a p-value, not a causal claim.
- Missing data: an issuer with insufficient pre-entry history (<20
  trading days of prior bars) is excluded and reported by name, not
  imputed.
"""
from __future__ import annotations
import csv
import json
import math
import random
import sqlite3
from datetime import date
from pathlib import Path

REPO_DATA = Path("C:/workspace/TalonX/results")
OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"
SEED = 118118
DRAWS = 5000
WINDOW_TD = 20

BAR_DIRS = [REPO_DATA / "task95g_broad_cross_sectional/_daily",
            REPO_DATA / "task107a_form4_feasibility/_prices"]


def load_closes(symbol: str) -> list[tuple[date, float]]:
    out: dict[date, float] = {}
    for d in BAR_DIRS:
        p = d / f"{symbol}.csv"
        if not p.exists():
            continue
        with open(p) as f:
            for row in csv.DictReader(f):
                try:
                    dt = date.fromisoformat(row["date"][:10])
                    out[dt] = float(row["close"])
                except (KeyError, ValueError):
                    continue
    return sorted(out.items())


def pre_entry_vol_pct(symbol: str, entry: date) -> float | None:
    closes = load_closes(symbol)
    prior = [(d, c) for d, c in closes if d < entry]
    if len(prior) < WINDOW_TD + 1:
        return None
    window = prior[-(WINDOW_TD + 1):]
    rets = [math.log(window[i][1] / window[i - 1][1]) for i in range(1, len(window))
            if window[i - 1][1] > 0 and window[i][1] > 0]
    if len(rets) < WINDOW_TD - 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    return math.sqrt(var) * math.sqrt(252) * 100.0


def first_entries(tag: str) -> dict[str, date]:
    if tag == "A":
        rows = list(csv.DictReader(open(REC / "trades.csv")))
        first: dict[str, date] = {}
        for r in rows:
            d = date.fromisoformat(r["eligible_entry_session"])
            sym = r["symbol"]
            if sym not in first or d < first[sym]:
                first[sym] = d
        return first
    con = sqlite3.connect(f"file:{OUT / f'replay_v2_lane_{tag}.db'}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT symbol, eligible_entry_session FROM processed_episodes WHERE disposition='ENTERED'")
    first = {}
    for sym, sess in cur.fetchall():
        d = date.fromisoformat(sess)
        if sym not in first or d < first[sym]:
            first[sym] = d
    return first


def main() -> int:
    A_entries = first_entries("A")
    B_entries = first_entries("B")

    A_vol: dict[str, float] = {}
    A_missing = []
    for sym, d in A_entries.items():
        v = pre_entry_vol_pct(sym, d)
        if v is None:
            A_missing.append(sym)
        else:
            A_vol[sym] = v

    B_vol: dict[str, float] = {}
    B_missing = []
    for sym, d in B_entries.items():
        v = pre_entry_vol_pct(sym, d)
        if v is None:
            B_missing.append(sym)
        else:
            B_vol[sym] = v

    print(f"A: {len(A_vol)}/{len(A_entries)} issuers with sufficient pre-entry history "
          f"(missing: {A_missing})")
    print(f"B: {len(B_vol)}/{len(B_entries)} issuers with sufficient pre-entry history "
          f"(missing: {len(B_missing)} symbols)")
    print("A pre-entry vol by issuer:", {k: round(v, 2) for k, v in A_vol.items()})

    A_mean = sum(A_vol.values()) / len(A_vol)
    B_syms = list(B_vol.keys())
    n_A = len(A_vol)

    rng = random.Random(SEED)
    draw_means = []
    for _ in range(DRAWS):
        sample = rng.sample(B_syms, n_A)
        draw_means.append(sum(B_vol[s] for s in sample) / n_A)

    draw_means_sorted = sorted(draw_means)
    rank = sum(1 for m in draw_means_sorted if m <= A_mean)
    percentile = rank / len(draw_means_sorted) * 100

    B_mean_all = sum(B_vol.values()) / len(B_vol)

    result = {
        "predeclared_feature": "20-trading-day pre-entry realized volatility, annualized %, "
                               "issuer-level (first entry date), point-in-time from local bar CSVs",
        "omitted_features": ["sector (no point-in-time source available this session)",
                             "market-cap tier (no point-in-time source available this session)"],
        "A_issuers_used": len(A_vol), "A_issuers_missing_data": A_missing,
        "B_issuers_used": len(B_vol), "B_issuers_missing_data_count": len(B_missing),
        "A_mean_pre_entry_vol_pct": A_mean,
        "B_mean_pre_entry_vol_pct_all_101": B_mean_all,
        "A_percentile_within_random_6_issuer_draws_of_B": percentile,
        "draws": DRAWS, "seed": SEED,
        "interpretation": (
            "A descriptive association only -- not a causal claim. A's percentile position "
            "in the null distribution of random-B-subset mean pre-entry volatility; a "
            "non-extreme percentile means insufficient evidence of a systematic volatility "
            "difference, not proof A and B are identically composed."
        ),
    }
    (REC / "composition_check.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
