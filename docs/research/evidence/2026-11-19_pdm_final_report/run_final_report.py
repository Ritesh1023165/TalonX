"""PDM_V1 final report, run ONCE after the endpoint (owner 'go' 2026-11-19), plus the decision metrics required by the
approved rules (docs/research/preregistration/2026-10-24_decision_rules_v2_forward_and_pdm.md, Study 2).
Method fixed before reading: whole-session bootstrap of the alert-level mean (sessions resampled with replacement,
B=10,000, seed 20261119); primary 95% interval, 90% shown as sensitivity; session-positive share = fraction of
sessions whose own mean cost-adjusted markout > 0; mean without the top 5 alerts. No study state is modified."""
import json, random, statistics, sys
from datetime import datetime, timezone
from pathlib import Path
from talonx_paperperf import post_delivery_markout as P

REPO = Path(__file__).resolve().parents[4]
OPP = REPO / "results" / "opportunity"
now = datetime.now(timezone.utc)
act = P.load_activation(REPO / "docs/research/protocols/POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json",
                        require_integrity=True, repo=REPO)
store = P.Store(REPO / "results" / "post_delivery_markout")
rep = P.final_report(store, act, now, outbox_path=OPP / "promotion_signal_notifications.db",
                     promotion_path=OPP / "promotion.db", repo=REPO)
out = {"run_utc": now.isoformat(), "final_report": rep, "decision_metrics": {}}
if "status" not in rep:                                   # completion checks passed
    rnd = random.Random(20261119)
    for seg in rep:
        rows = store.q("SELECT o.session, r.gross, r.cost_adjusted FROM observations o JOIN results r USING(obs_id) "
                       "WHERE o.segment=? AND o.state IN (%s)" % ",".join("?" * len(P.SELECTED)),
                       (seg, *sorted(P.SELECTED)))
        dm = {}
        for key in ("gross", "cost_adjusted"):
            xs = [(r["session"], r[key]) for r in rows if r[key] is not None]
            by = {}
            for s, v in xs:
                by.setdefault(s, []).append(v)
            sess = sorted(by)
            boot = []
            for _ in range(10000):
                pick = [rnd.choice(sess) for _ in sess]
                vals = [v for s in pick for v in by[s]]
                boot.append(statistics.fmean(vals))
            boot.sort()
            q = lambda p: boot[int(p * (len(boot) - 1))]
            vals = sorted((v for _, v in xs), reverse=True)
            dm[key] = {"n": len(xs), "sessions": len(sess), "mean": statistics.fmean(v for _, v in xs),
                       "ci95": [q(0.025), q(0.975)], "ci90": [q(0.05), q(0.95)],
                       "session_positive_share": sum(statistics.fmean(by[s]) > 0 for s in sess) / len(sess),
                       "mean_without_top5": statistics.fmean(vals[5:]) if len(vals) > 5 else None}
        out["decision_metrics"][seg] = dm
dst = REPO / "results" / "post_delivery_markout" / "final_report_20261119.json"
dst.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
