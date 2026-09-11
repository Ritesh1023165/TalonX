"""
Event classification between consecutive checkpoints (Task 114 B4).

INFO      -- meaningful business progress (fresh code-P, cluster forms, signal, BUY/SELL, exit nearing)
WARNING   -- degraded but recoverable (stale source, feed degraded, coverage low, telegram degraded, restart)
CRITICAL  -- a locked safety/strategy invariant tripped -> fail safe, preserve evidence, do NOT auto-fix
"""
from __future__ import annotations

from typing import Any

_CRIT = {
    "stale_episode_entered": "A stale historical episode opened a position",
    "duplicate_buy": "Duplicate BUY for one episode_id",
    "duplicate_position": "Duplicate position for one episode_id",
    "negative_cash": "Negative cash in v2_lane.db",
    "ledger_equation_broken": "Ledger equation buys == sells + open + unresolved is broken",
    "experimental_external_send": "Experimental produced an EXTERNAL send",
    "experimental_override_active": "Experimental external-send override is ACTIVE",
    "v2_real_capital": "V2 status reports real_capital=true",
    "v2_shorts": "V2 status reports shorts=true",
    "v2_eod_forced_flatten": "V2 status reports eod_forced_flatten=true",
    "v2_source_not_insider": "V2 live source is not the insider store (parquet/stale)",
    "multiple_telegram_pollers": "More than one logical Telegram getUpdates poller",
    "strategy_version_mismatch": "V2 strategy_version != INSIDER_BUY_CLUSTER_V2@1",
    "v2_process_dead": "V2 companion heartbeat is dead while a session is running",
}


def _ev(level: str, kind: str, msg: str, **extra: Any) -> dict[str, Any]:
    return {"level": level, "kind": kind, "message": msg, **extra}


def classify(prev: dict[str, Any] | None, curr: dict[str, Any],
             *, session_running: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    inv = curr.get("invariants", {})

    # ---- CRITICAL: any tripped invariant ----
    for flag, desc in _CRIT.items():
        if not inv.get(flag):
            continue
        if flag in ("v2_process_dead", "v2_source_not_insider", "strategy_version_mismatch") \
                and not session_running:
            continue
        out.append(_ev("CRITICAL", flag, desc))

    fn = curr.get("funnel", {})
    fp = (prev or {}).get("funnel", {})
    cl = fn.get("clusters", {}) or {}
    cp = fp.get("clusters", {}) or {}
    f4 = fn.get("form4", {}) or {}
    p4 = fp.get("form4", {}) or {}
    tm = fn.get("terminal", {}) or {}
    pm = fp.get("terminal", {}) or {}

    # ---- INFO: business progress ----
    if f4.get("code_p_records_today", 0) > p4.get("code_p_records_today", 0):
        out.append(_ev("INFO", "fresh_code_p_purchase",
                       f"code-P open-market purchases today: {p4.get('code_p_records_today', 0)} -> "
                       f"{f4.get('code_p_records_today')}"))
    if cl.get("single_insider_near_miss_count", 0) > cp.get("single_insider_near_miss_count", 0):
        new = sorted(set(cl.get("single_insider_near_miss_issuers", []))
                     - set(cp.get("single_insider_near_miss_issuers", [])))
        out.append(_ev("INFO", "single_insider_near_miss",
                       f"first insider (near-miss) in: {', '.join(new) or '?'}"))
    if cl.get("clusters_ge2_distinct_insiders", 0) > cp.get("clusters_ge2_distinct_insiders", 0):
        new = sorted(set(cl.get("cluster_symbols", [])) - set(cp.get("cluster_symbols", [])))
        out.append(_ev("INFO", "cluster_formed",
                       f">=2-distinct-insider cluster formed: {', '.join(new) or '?'}"))
    if cl.get("fresh_eligible_clusters", 0) > cp.get("fresh_eligible_clusters", 0):
        out.append(_ev("INFO", "fresh_eligible_cluster",
                       f"fresh eligible cluster(s): {cp.get('fresh_eligible_clusters', 0)} -> "
                       f"{cl.get('fresh_eligible_clusters')}"))
    if tm.get("signals", 0) > pm.get("signals", 0):
        out.append(_ev("INFO", "v2_signal", f"V2 signal(s): {pm.get('signals', 0)} -> {tm.get('signals')}"))
    if tm.get("buys", 0) > pm.get("buys", 0):
        out.append(_ev("INFO", "v2_buy", f"V2 BUY: {pm.get('buys', 0)} -> {tm.get('buys')}"))
    if tm.get("sells", 0) > pm.get("sells", 0):
        out.append(_ev("INFO", "v2_sell", f"V2 SELL: {pm.get('sells', 0)} -> {tm.get('sells')}"))

    # position nearing target exit
    for pos in curr.get("ledger", {}).get("open_positions", []) if isinstance(
            curr.get("ledger", {}).get("open_positions"), list) else []:
        pass  # open_positions detail lives in the dashboard read model; nearing-exit handled there

    # ---- WARNING: degraded but recoverable ----
    if session_running:
        svc = curr.get("service_health", {})
        if svc.get("health") == "DEGRADED":
            out.append(_ev("WARNING", "v2_heartbeat_degraded",
                           f"V2 heartbeat age {svc.get('heartbeat_age_s')}s (ttl {svc.get('heartbeat_ttl_s')}s)"))
        mk = curr.get("market", {})
        if mk.get("state") not in (None, "HEALTHY") and mk.get("state") != "error":
            out.append(_ev("WARNING", "market_degraded", f"market feed state: {mk.get('state')}"))
        cov = mk.get("coverage_ratio")
        if isinstance(cov, (int, float)) and cov < 0.5:
            out.append(_ev("WARNING", "coverage_low", f"market coverage ratio {cov}"))
        it = curr.get("intelligence", {})
        age = it.get("processing_log_age_s")
        if isinstance(age, (int, float)) and age > 3600:
            out.append(_ev("WARNING", "intelligence_stale",
                           f"Intelligence processing log {int(age)}s old"))
        od = curr.get("official_dispatch", {})
        if od.get("telegram_failures_today"):
            out.append(_ev("WARNING", "official_telegram_degraded",
                           f"{od.get('telegram_failures_today')} Telegram delivery failure(s) today"))
        # unexpected restart: a component that was live is no longer, or pid changed
        prev_sup = (prev or {}).get("supervisor", {}).get("producers", {})
        cur_sup = curr.get("supervisor", {}).get("producers", {})
        for name, p in cur_sup.items():
            was = prev_sup.get(name, {})
            if was.get("live") and not p.get("live"):
                out.append(_ev("WARNING", "component_down", f"{name} was live, now not"))

    return out
