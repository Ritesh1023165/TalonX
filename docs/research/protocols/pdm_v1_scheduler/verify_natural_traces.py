"""Read-only, sanitised verification of natural traced promotion sends (no pricing, no bars/quotes, no raw IDs)."""
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\workspace\TalonX")
from talonx_opportunity.delivery_trace import make_trace_lookup  # noqa: E402
from talonx_paperperf import vr_live  # noqa: E402

OPP = r"C:\workspace\TalonX\results\opportunity"
OB, TR = OPP + r"\promotion_signal_notifications.db", OPP + r"\promotion_delivery_trace.db"
DEPLOY = "2026-10-09T13:36:12"
TOL = 2.0


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def dt(s):
    return datetime.fromisoformat(s) if s else None


tr = ro(TR)
traces = tr.execute("SELECT attempt_id, payload_sha256, send_start_utc, response_utc, outcome, error_class, "
                    "message_id, server_date_utc, chat_ref, network_retries, rate_limit_retries, "
                    "definite_error_retries, trace_state, recorded_utc FROM traces ORDER BY send_start_utc").fetchall()
ob = ro(OB)
rows = ob.execute("SELECT event_id, payload_text, state, attempts, sent_at_utc, dedup_key, created_at_utc, "
                  "transport_ref FROM ops_notification_outbox WHERE created_at_utc >= ?", (DEPLOY,)).fetchall()
import hashlib  # noqa: E402
by_hash = {}
for r in rows:
    by_hash.setdefault(hashlib.sha256(r[1].encode("utf-8")).hexdigest(), []).append(r)
look = make_trace_lookup(OB, TR)
out = {"traces": len(traces), "post_deploy_outbox_rows": len(rows),
       "outbox_states": dict(Counter(r[2] for r in rows)), "items": []}
problems = []
for i, t in enumerate(traces, 1):
    (aid, h, s0, r0, outc, ecls, mid, sd, ref, nr, rr, dr, ts, rec) = t
    m = by_hash.get(h, [])
    it = {"n": i, "outcome": outc, "trace_state": ts, "message_id_present": mid is not None,
          "chat_ref_hashed": bool(ref) and len(ref) == 12 and not ref.lstrip("-").isdigit(),
          "retries": {"network": nr, "rate_limit": rr, "definite": dr}, "outbox_matches": len(m)}
    if len(m) == 1:
        ev, _, st, att, sent, dk, cr, _tref = m[0]
        s0d, r0d, sdd, sentd = dt(s0), dt(r0), dt(sd), dt(sent)
        it.update(outbox_state=st, outbox_attempts=att,
                  order_send_le_response=s0d <= r0d,
                  server_date_1s_precision=sdd is not None and sdd.microsecond == 0,
                  server_within_tol=sdd is not None and sdd - timedelta(seconds=TOL) <= r0d
                  <= sdd + timedelta(seconds=1 + TOL),
                  sent_at_ge_response_minus_tol=sentd is not None and sentd >= r0d - timedelta(seconds=TOL),
                  created_le_send_start=dt(cr) <= s0d,
                  response_minus_send_ms=round((r0d - s0d).total_seconds() * 1000),
                  server_minus_response_s=round((sdd - r0d).total_seconds(), 3) if sdd else None,
                  sent_at_minus_response_ms=round((sentd - r0d).total_seconds() * 1000) if sentd else None)
        lk = look(ev)
        it["lookup_state"] = None if lk is None else lk.get("trace_state")
        it["lookup_hidden_retries"] = None if lk is None else lk.get("hidden_retries")
        it["lookup_ambiguous_prior"] = None if lk is None else lk.get("ambiguous_prior_attempt")
        for k in ("order_send_le_response", "server_date_1s_precision", "server_within_tol",
                  "sent_at_ge_response_minus_tol", "created_le_send_start", "message_id_present", "chat_ref_hashed"):
            if not it[k]:
                problems.append(f"trace{i}:{k}")
        if it["lookup_state"] != "TRACE_OK":
            problems.append(f"trace{i}:lookup={it['lookup_state']}")
    else:
        problems.append(f"trace{i}:outbox_matches={len(m)}")
    out["items"].append(it)
sent_rows = [r for r in rows if r[2] == "SENT"]
out["sent_rows_without_trace"] = sum(1 for r in sent_rows
                                     if hashlib.sha256(r[1].encode("utf-8")).hexdigest()
                                     not in {t[1] for t in traces})
out["dedup_keys_duplicated"] = sum(1 for v in Counter(r[5] for r in rows).values() if v > 1)
out["traces_per_payload_max"] = max(Counter(t[1] for t in traces).values() or [0])
ctl = vr_live.entry_control()
out["vr_entry_control"] = ctl["state"]
w = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, text=True).stdout
out["clock"] = {k: v.strip() for k, v in (l.split(":", 1) for l in w.splitlines() if ":" in l)
                if k.strip() in ("Stratum", "Root Dispersion", "Last Successful Sync Time", "Source")}
out["clock_tolerance_s"] = TOL
if out["sent_rows_without_trace"]:
    problems.append("sent_rows_without_trace")
if out["dedup_keys_duplicated"]:
    problems.append("dedup_dup")
if ctl["state"] != "BLOCKED":
    problems.append("VR_NOT_BLOCKED")
out["problems"] = problems
out["verdict"] = ("NO_NATURAL_ALERTS" if not traces else ("PASS" if not problems else "FAIL"))
print(json.dumps(out, indent=1, default=str))
