"""READ-ONLY reconciliation of one ingestion cycle against its published universe (2026-10-09). Writes JSON only."""
import json
import sqlite3
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "talonx_opportunity").is_dir())
sys.path.insert(0, str(REPO))
WID = sys.argv[1]
OUT = Path(sys.argv[3])

m = sqlite3.connect(f"file:{REPO / 'results/opportunity/market.db'}?mode=ro", uri=True, timeout=10)
m.execute("BEGIN")                                                  # one read transaction: one consistent generation
GEN = m.execute("SELECT generation FROM ingestion_state WHERE window_id=?", (WID,)).fetchone()[0]   # the latest
g = m.execute("SELECT generation, as_of_utc, cycle_utc, dtu_cycle_utc, symbols_changed FROM snapshot_generations "
              "WHERE window_id=? AND generation=?", (WID, GEN)).fetchone()
act = m.execute("SELECT cycle_utc, n_active, counts_json, symbols_json, fallback_reason, policy_fp FROM dtu_active "
                "WHERE window_id=? AND cycle_utc=?", (WID, g[3])).fetchone()
snap = {r[0]: (r[1], r[2], r[3]) for r in m.execute("SELECT symbol, state, reason, core_rank FROM dtu_snapshot WHERE "
                                                      "window_id=?", (WID,))}
lst = m.execute("SELECT cycle_utc, symbols_json FROM dtu_active WHERE window_id=? AND symbols_json IS NOT NULL AND "
                "cycle_utc <= ? ORDER BY cycle_utc DESC LIMIT 1", (WID, g[3])).fetchone()   # stored only on change
sv = m.execute("SELECT snapshot_version, policy_fp FROM dtu_snapshots WHERE window_id=?", (WID,)).fetchone()
cyc = m.execute("SELECT at_utc, phase, as_of_utc, fetched_symbols, bars, failed_symbols, batches, failed_batches, note "
                "FROM cycles WHERE window_id=? AND as_of_utc = ? ORDER BY at_utc DESC LIMIT 1", (WID, g[1])).fetchone()
st = m.execute("SELECT as_of_utc, cycle_utc, phase, symbols, incomplete_json, generation FROM ingestion_state WHERE "
               "window_id=?", (WID,)).fetchone()
aggs = {r[0]: (json.loads(r[1]), r[2], r[3]) for r in m.execute(
    "SELECT symbol, agg_json, watermark_utc, generation FROM aggregates WHERE window_id=?", (WID,))}
m.rollback()

from talonx_premarket import __main__ as M  # noqa: E402  (log parse only; no network)
V = set(M._v2_scope(None))
C = {s for s, r in snap.items() if r[0] == "ACTIVE_CORE"}
requested = set(json.loads(lst[1]))
P = requested - C - V
counts = json.loads(act[2])
written_this_gen = {s for s, a in aggs.items() if a[2] == GEN}
with_bars = {s for s in requested if ((aggs.get(s) or ({},))[0].get("bars") or 0) > 0}
from datetime import datetime, timedelta  # noqa: E402
_asof = datetime.fromisoformat(g[1])
fresh15 = {s for s in with_bars if datetime.fromisoformat(str(aggs[s][0].get("last_t")).replace("Z", "+00:00")) >= _asof - timedelta(minutes=15)}
agg_keys = sorted({k for s in list(requested)[:5] for k in (aggs.get(s) or ({},))[0].keys()})
res = {
    "window_id": WID, "generation": GEN, "snapshot": {"version": sv[0], "policy_fp": sv[1]},
    "generation_row": dict(zip(("generation", "data_as_of_utc", "ingestion_cycle_utc", "dtu_cycle_utc", "symbols_changed"), g)),
    "fetch_list_source": {"stored_at_cycle_utc": lst[0], "rule": "symbols_json is written only when the fetch list changes; the list in force is the latest non-null row at or before the cycle (same rule as universe_tiers.latest_active)"},
    "dtu_active_row": {"cycle_utc": act[0], "n_active": act[1], "label_counts": counts, "fallback": act[4],
                       "policy_fp": act[5]},
    "membership": {"C_core": len(C), "V_v2_scope": len(V), "C_and_V": len(C & V), "C_minus_V": len(C - V),
                   "V_minus_C": sorted(V - C), "P_protected_or_shared_additions": sorted(P),
                   "union_C_V_P": len(C | V | P), "V_minus_C_snapshot_state": {s: snap.get(s) for s in sorted(V - C)}},
    "fetch_scheduling": {"requested_this_cycle": len(requested), "requested_eq_union": requested == (C | V | P),
                         "requested_minus_union": sorted(requested - (C | V | P)),
                         "union_minus_requested": sorted((C | V | P) - requested)},
    "response": {"cycle_row": dict(zip(("at_utc", "phase", "as_of_utc", "fetched_symbols", "bars", "failed_symbols",
                                         "batches", "failed_batches", "note"), cyc)),
                 "aggregates_written_in_this_generation": len(written_this_gen & requested)},
    "data_freshness": {"ingestion_state_generation": st[5], "incomplete_symbols": len(json.loads(st[4] or "[]")),
                       "requested_with_any_bar_so_far": len(with_bars),
                       "requested_with_no_bar_yet_premarket": len(requested - with_bars),
                       "requested_with_a_bar_starting_in_last_15min_before_as_of": len(fresh15), "bar_timestamp_convention": "bar t = interval START (1-min); as_of = end of the last complete minute",
                       "watermark_at_as_of": sum(1 for s in requested if (aggs.get(s) or (0, ""))[1][:16] >= g[1][:16]),
                       "aggregate_fields_sample": agg_keys,
                       "note": "no premarket bar yet != missing subscription: the symbol was requested and its "
                               "watermark advanced; thin names simply have not traded since 04:00 ET"},
    "label_explanation": ("dtu_active counts are per-symbol RESOLVED STATES, not set memberships: resolve() gives "
                          "V2_EXECUTION_SCOPE (OPERATOR_ADDED) precedence over ACTIVE_CORE, so the V names inside the "
                          "Core are labelled OPERATOR_ADDED and only the rest are labelled ACTIVE_CORE"),
}
OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1)[:4000])
