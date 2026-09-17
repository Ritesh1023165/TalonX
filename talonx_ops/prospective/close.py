"""
Evening one-command close (Task 114 B7): final checkpoint + V2
reconciliation + base EOD reconciliation + evidence + report + graceful
shutdown.  NEVER flattens a legitimate open V2 position; NEVER deletes
``v2_lane.db``.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from talonx_ops.prospective import CAMPAIGN_STARTING_CASH
from talonx_ops.prospective.checkpoint import capture, eod_state
from talonx_ops.prospective.paths import V2_DB_PATH, V2_STATUS_PATH, atomic_write, now_pair


@dataclass
class CloseResult:
    verdict: str                       # PASS | PASS_WITH_FINDINGS | FAIL | NOT_DUE_YET
    v2_reconciliation: dict[str, Any] = field(default_factory=dict)
    base_reconciliation: dict[str, Any] = field(default_factory=dict)
    asserts: dict[str, str] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    shutdown: dict[str, Any] = field(default_factory=dict)
    final_checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _v2_reconcile() -> tuple[dict[str, Any], dict[str, str], list[str]]:
    findings: list[str] = []
    asserts: dict[str, str] = {}
    p = Path(V2_DB_PATH)
    if not p.exists():
        return {"error": "no v2_lane.db"}, {"v2_ledger_present": "FAIL"}, ["v2_lane.db missing"]
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
        cash = None if cash is None else float(cash[0])
        buys = con.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'").fetchone()[0]
        sells = con.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'").fetchone()[0]
        n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
        n_unres = con.execute("SELECT COUNT(*) FROM positions WHERE status='EXIT_UNRESOLVED'").fetchone()[0]
        n_closed = con.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED'").fetchone()[0]
        realized = con.execute(
            "SELECT COALESCE(SUM(realized_pnl_usd),0) FROM positions WHERE status='CLOSED'").fetchone()[0] or 0.0
        open_cost = con.execute(
            "SELECT COALESCE(SUM(position_cost),0) FROM positions WHERE status='OPEN'").fetchone()[0] or 0.0
        # Package 1 Settlement Integrity: an EXIT_UNRESOLVED position's
        # cash debit at entry is never returned (mark_exit_unresolved
        # never touches cash) -- its cost basis must be included here or
        # this reconciliation fabricates a cash-loss mismatch purely
        # because that cost was omitted from the expected-cash formula.
        unresolved_cost = con.execute(
            "SELECT COALESCE(SUM(position_cost),0) FROM positions "
            "WHERE status='EXIT_UNRESOLVED'").fetchone()[0] or 0.0
        dup_buy = con.execute("SELECT episode_id,COUNT(*) c FROM trades WHERE action='BUY' "
                              "GROUP BY episode_id HAVING c>1").fetchall()
        dup_pos = con.execute("SELECT episode_id,COUNT(*) c FROM positions "
                              "GROUP BY episode_id HAVING c>1").fetchall()
        stale_entered = con.execute(
            "SELECT p.episode_id FROM positions p JOIN processed_episodes e "
            "ON p.episode_id=e.episode_id WHERE e.disposition='SKIPPED_ENTRY_STALE'").fetchall()
        # Package 4 P4-H: whole-share and positive-finite-cost-basis
        # invariants -- reuses this SAME reconciliation/account-block
        # mechanism (LEDGER_MISMATCH) rather than a parallel safety
        # system, per Package 4's own explicit instruction.
        non_whole = con.execute(
            "SELECT episode_id, shares FROM positions WHERE shares IS NOT NULL "
            "AND shares != CAST(shares AS INTEGER)").fetchall()
        bad_cost = con.execute(
            "SELECT episode_id, position_cost FROM positions WHERE status IN ('OPEN','EXIT_UNRESOLVED') "
            "AND (position_cost IS NULL OR position_cost <= 0)").fetchall()
    finally:
        con.close()

    rec = {"cash": cash, "buys": int(buys), "sells": int(sells), "open": int(n_open),
           "closed": int(n_closed), "exit_unresolved": int(n_unres),
           "realized_pnl_usd": round(realized, 2), "open_cost_usd": round(open_cost, 2),
           "exit_unresolved_cost_usd": round(unresolved_cost, 2),
           "starting_cash": CAMPAIGN_STARTING_CASH}

    def _a(name, ok, why=""):
        asserts[name] = "PASS" if ok else "FAIL"
        if not ok:
            findings.append(f"{name}: {why}")

    _a("buys_eq_sells_plus_open_plus_unresolved", buys == sells + n_open + n_unres,
       f"{buys} != {sells}+{n_open}+{n_unres}")
    _a("cash_plus_open_cost_reconciles",
       cash is not None and
       abs((cash + open_cost + unresolved_cost) - (CAMPAIGN_STARTING_CASH + realized)) <= 1.0,
       f"cash {cash} + open_cost {open_cost} + unresolved_cost {unresolved_cost} != "
       f"{CAMPAIGN_STARTING_CASH} + realized {realized}")
    _a("no_negative_cash", cash is not None and cash >= 0, f"cash {cash}")
    _a("whole_share_positions", not non_whole,
       str([(d[0], d[1]) for d in non_whole]))
    _a("positive_finite_position_cost", not bad_cost,
       str([(d[0], d[1]) for d in bad_cost]))
    _a("no_duplicate_buy_episode_id", not dup_buy, str([d[0] for d in dup_buy]))
    _a("no_duplicate_position_episode_id", not dup_pos, str([d[0] for d in dup_pos]))
    _a("no_stale_episode_entered", not stale_entered, str([s[0] for s in stale_entered]))
    try:
        s = json.loads(Path(V2_STATUS_PATH).read_text())
        _a("no_illegal_eod_flatten", not s.get("eod_forced_flatten"), "eod_forced_flatten=true")
        _a("real_capital_off", not s.get("real_capital"), "real_capital=true")
        _a("shorts_off", not s.get("shorts"), "shorts=true")
    except Exception:  # noqa: BLE001
        asserts["v2_status_readable"] = "FAIL"
        findings.append("v2 status file unreadable at close")
    return rec, asserts, findings


def _base_reconcile() -> dict[str, Any]:
    try:
        from dataclasses import asdict
        from talonx_ops.eod_reconciliation import run_and_persist
        return asdict(run_and_persist())
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _record_v2_reconciliation_blocks(asserts: dict[str, str], findings: list[str]) -> list[str]:
    """Package 2 Durable Account Blocks: connects `_v2_reconcile()`'s own
    VERIFIED results to a persisted, enforced account block -- this is
    what closes OPS-015's own described gap for V2 specifically
    (detection already existed; nothing was connected to admission
    enforcement). Only ever called with ALREADY-COMPUTED asserts from
    `_v2_reconcile()` above -- this function performs no reconciliation
    of its own, it only persists a block for a genuine, already-verified
    failure.

    Opens its own minimal WRITE connection (a plain ``sqlite3.connect``,
    NOT ``V2Store``'s constructor) so this step never triggers V2Store's
    own unrelated schema-migration/WAL-verification/portfolio-seed side
    effects on a production ledger this function does not own the
    lifecycle of -- it writes ONLY the additive account_blocks/
    block_clearances tables (``CREATE TABLE IF NOT EXISTS``) plus the
    block row(s) themselves, inside one short transaction."""
    from talonx_ops import account_blocks
    from talonx_v2.store import V2_ACCOUNT_ID

    p = Path(V2_DB_PATH)
    if not p.exists():
        return []
    to_record: list[tuple[str, str, str]] = []
    if asserts.get("cash_plus_open_cost_reconciles") == "FAIL":
        detail = next((f for f in findings if f.startswith("cash_plus_open_cost_reconciles")),
                      "cash_plus_open_cost_reconciles: FAIL")
        to_record.append((account_blocks.REASON_LEDGER_MISMATCH, "cash_plus_open_cost_reconciles", detail))
    if asserts.get("no_negative_cash") == "FAIL":
        detail = next((f for f in findings if f.startswith("no_negative_cash")), "no_negative_cash: FAIL")
        to_record.append((account_blocks.REASON_CASH_DEFICIT, "no_negative_cash", detail))
    # Package 4 P4-H: the two new whole-share/cost-basis invariants
    # reuse the SAME LEDGER_MISMATCH mechanism -- never a parallel
    # safety system.
    if asserts.get("whole_share_positions") == "FAIL":
        detail = next((f for f in findings if f.startswith("whole_share_positions")),
                      "whole_share_positions: FAIL")
        to_record.append((account_blocks.REASON_LEDGER_MISMATCH, "whole_share_positions", detail))
    if asserts.get("positive_finite_position_cost") == "FAIL":
        detail = next((f for f in findings if f.startswith("positive_finite_position_cost")),
                      "positive_finite_position_cost: FAIL")
        to_record.append((account_blocks.REASON_LEDGER_MISMATCH, "positive_finite_position_cost", detail))
    if not to_record:
        return []

    con = sqlite3.connect(str(p), isolation_level=None)
    recorded: list[str] = []
    try:
        con.execute(f"PRAGMA busy_timeout={30_000}")
        # executescript() implicitly commits/ends any open transaction on
        # this connection (a stdlib sqlite3 quirk) -- so the additive
        # CREATE TABLE IF NOT EXISTS DDL must run BEFORE BEGIN IMMEDIATE,
        # never inside the transaction it would otherwise silently close.
        con.executescript(account_blocks.SCHEMA)
        con.execute("BEGIN IMMEDIATE")
        for reason_type, reference, detail in to_record:
            bid = account_blocks.record_block(
                con, account_id=V2_ACCOUNT_ID, reason_type=reason_type,
                reference=reference, detail=detail)
            recorded.append(bid)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return recorded


def _experimental_external_zero(ck: dict) -> tuple[bool, str]:
    exp = ck.get("experimental", {})
    if exp.get("override_active"):
        return False, "experimental external-send override ACTIVE"
    if exp.get("sent_today"):
        return False, f"experimental sent_today={exp.get('sent_today')}"
    return True, "0 external sends; override blocked"


def run_close(session_dir: str | Path, *, force: bool = False,
              do_shutdown: bool = True, now: datetime | None = None) -> CloseResult:
    now = now or datetime.now(timezone.utc)
    sd = Path(session_dir)
    sd.mkdir(parents=True, exist_ok=True)

    es = eod_state(now)
    if es["state"] == "NOT_DUE_YET" and not force:
        return CloseResult(verdict="NOT_DUE_YET", asserts={"eod_state": es["state"]},
                           findings=[es["reason"]])

    ck = capture(now=now)
    atomic_write(sd / "eod_final_checkpoint.json", json.dumps(ck, indent=2, default=str))

    v2_rec, asserts, findings = _v2_reconcile()
    blocks_recorded = _record_v2_reconciliation_blocks(asserts, findings)
    if blocks_recorded:
        findings.append(
            f"account block(s) recorded for V2 due to the above reconciliation "
            f"failure(s): {blocks_recorded} -- new admissions blocked until "
            f"auditable clearance (Package 2)")
    base_rec = _base_reconcile()
    ext_ok, ext_why = _experimental_external_zero(ck)
    asserts["experimental_external_sends_zero"] = "PASS" if ext_ok else "FAIL"
    if not ext_ok:
        findings.append(ext_why)

    # cross-lane contamination: Original paper ledger must be inert
    try:
        import pathlib as _p
        odb = _p.Path.home() / ".talonx" / "paper_trading.db"
        oc = sqlite3.connect(f"file:{odb}?mode=ro", uri=True)
        o_pos = oc.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        o_tr = oc.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0]
        oc.close()
        asserts["no_cross_lane_contamination"] = "PASS" if (o_pos == 0 and o_tr == 0) else "PARTIAL"
        if o_pos or o_tr:
            findings.append(f"Original paper ledger not inert (pos {o_pos}, trades {o_tr}) -- "
                            "expected 0/0 for a V2 campaign; investigate if V2 caused it")
    except Exception as exc:  # noqa: BLE001
        asserts["no_cross_lane_contamination"] = "UNKNOWN"

    # official dispatch
    od = ck.get("official_dispatch", {})
    asserts["official_dispatch_healthy"] = "FAIL" if od.get("telegram_failures_today") else "PASS"

    # base reconciliation
    b_status = base_rec.get("status")
    if b_status == "PARTIAL":
        findings.append("base eod_reconciliation PARTIAL (typically: no PIV reader) -- "
                        f"mismatches={base_rec.get('mismatches')}")
    asserts["base_reconciliation"] = {"RECONCILED": "PASS", "PARTIAL": "PARTIAL",
                                      "MISMATCH": "FAIL"}.get(b_status, "UNKNOWN")

    # preserve V2 ledger evidence (copy, never move/delete)
    try:
        shutil.copy2(V2_DB_PATH, sd / "v2_lane.db.eod-copy")
        shutil.copy2(V2_STATUS_PATH, sd / "v2_service_status.eod.json")
        asserts["v2_ledger_preserved_copy"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        asserts["v2_ledger_preserved_copy"] = "FAIL"
        findings.append(f"could not copy v2_lane.db evidence: {exc}")

    # D6: lane-scoped candidate/evaluation accounting snapshot (Original /
    # Experimental / V2 kept separate; off-counter dispositions recorded;
    # in-flight work listed; the historical 94-gap NOT reported as resolved).
    try:
        from talonx_ops.prospective.lane_accounting import build_lane_accounting
        la = build_lane_accounting(v2_db=V2_DB_PATH)
        atomic_write(sd / "lane_accounting_eod.json", json.dumps(la, indent=2, default=str))
        asserts["lane_accounting_snapshot"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        asserts["lane_accounting_snapshot"] = "PARTIAL"
        findings.append(f"lane accounting snapshot incomplete: {exc}")

    shutdown: dict[str, Any] = {"performed": False}
    if do_shutdown:
        from talonx_ops.prospective.proc import stop_stack
        shutdown = stop_stack(sd)
        shutdown["performed"] = True
        # an OPEN V2 position must still be OPEN in the ledger after shutdown
        try:
            con = sqlite3.connect(f"file:{V2_DB_PATH}?mode=ro", uri=True)
            still_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
            con.close()
            shutdown["open_v2_positions_preserved"] = int(still_open) == v2_rec.get("open", 0)
        except Exception:  # noqa: BLE001
            shutdown["open_v2_positions_preserved"] = None

        # Task 117 Phase 0 (4.3): the close must NOT report a clean PASS while
        # required stack children are still running.  Residuals are a finding
        # and feed the exit status -- never silently swallowed.
        residual = shutdown.get("residual_talonx_processes") or []
        shutdown["shutdown_clean"] = not residual
        if residual:
            asserts["controlled_shutdown_complete"] = "PARTIAL"
            findings.append(
                f"controlled shutdown incomplete: {len(residual)} residual TalonX "
                f"process(es) after grace -- "
                + ", ".join(f"pid {r.get('pid')} ({str(r.get('cmd',''))[:40]})" for r in residual[:6])
                + " -- operator must run the base-stack teardown separately")
        else:
            asserts["controlled_shutdown_complete"] = "PASS"

    fails = [k for k, v in asserts.items() if v == "FAIL"]
    partials = [k for k, v in asserts.items() if v == "PARTIAL"]
    if fails:
        verdict = "FAIL"
    elif partials or findings:
        verdict = "PASS_WITH_FINDINGS"
    else:
        verdict = "PASS"

    return CloseResult(verdict=verdict, v2_reconciliation=v2_rec, base_reconciliation=base_rec,
                       asserts=asserts, findings=findings, shutdown=shutdown, final_checkpoint=ck)


def render_report(res: CloseResult, session_dir: str | Path) -> str:
    ck = res.final_checkpoint
    tp = now_pair()
    fn = ck.get("funnel", {})
    f4 = fn.get("form4", {}) or {}
    cl = fn.get("clusters", {}) or {}
    tm = fn.get("terminal", {}) or {}
    v2 = res.v2_reconciliation
    lines = [
        f"# Prospective V2 session -- final report",
        f"generated: {tp['utc']} ({tp['europe_london']} Europe/London)",
        f"session dir: {session_dir}",
        "",
        f"## Verdict: {res.verdict}",
        "",
        "## Runtime health",
        f"- V2 service health: {ck.get('service_health', {}).get('health')} "
        f"(tick {ck.get('service_health', {}).get('tick')}, "
        f"heartbeat {ck.get('service_health', {}).get('heartbeat_age_s')}s)",
        f"- market feed: {ck.get('market', {}).get('state')} "
        f"(coverage {ck.get('market', {}).get('coverage_ratio')})",
        f"- Intelligence processing log age: {ck.get('intelligence', {}).get('processing_log_age_s')}s; "
        f"newest insider event {ck.get('intelligence', {}).get('newest_insider_event_utc')}",
        f"- release: HEAD {ck.get('release', {}).get('head_short')} "
        f"(v1 fp ok={ck.get('release', {}).get('v1_fingerprint_ok')}, "
        f"v2 fp ok={ck.get('release', {}).get('v2_fingerprint_ok')})",
        "",
        "## V2 near-miss funnel",
        f"- Form 4 code-P records (window / today): "
        f"{f4.get('code_p_records_window')} / {f4.get('code_p_records_today')}",
        f"- distinct issuers with code-P (window / today): "
        f"{f4.get('distinct_issuers_window')} / {f4.get('distinct_issuers_today')}",
        f"- single-insider near-miss issuers: {cl.get('single_insider_near_miss_count')} "
        f"{cl.get('single_insider_near_miss_issuers')}",
        f"- >=2-distinct-insider clusters: {cl.get('clusters_ge2_distinct_insiders')} "
        f"{cl.get('cluster_symbols')}",
        f"- stale historical clusters (skipped): {cl.get('stale_historical_clusters')}",
        f"- fresh eligible clusters: {cl.get('fresh_eligible_clusters')}",
        f"- V2 signals / BUY / SELL: {tm.get('signals')} / {tm.get('buys')} / {tm.get('sells')}",
        f"- interpretation: {fn.get('interpretation')}",
        "",
        "## Paper account (V2 campaign ledger)",
        f"- starting cash: {v2.get('starting_cash')}",
        f"- current cash: {v2.get('cash')}",
        f"- open positions: {v2.get('open')} / 20   (open cost {v2.get('open_cost_usd')})",
        f"- closed positions: {v2.get('closed')}   realized P&L {v2.get('realized_pnl_usd')}",
        f"- EXIT_UNRESOLVED: {v2.get('exit_unresolved')}",
        "",
        "## EOD asserts",
    ]
    for k, v in res.asserts.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Findings"]
    lines += [f"- {f}" for f in res.findings] or ["- none"]
    lines += ["", "## Shutdown", f"- {json.dumps(res.shutdown, default=str)}"]
    lines += ["", "## Campaign", f"- day {ck.get('campaign', {}).get('campaign_day')} "
              f"(started {ck.get('campaign', {}).get('start_date')}); "
              "prospective sample still SAMPLE_INSUFFICIENT until real prospective trades accumulate",
              "- ledger preserved; carries forward. No profitability inference from zero-trade days."]
    return "\n".join(lines)
