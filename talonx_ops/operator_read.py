"""RI-3 operator projection. SQLite mode=ro; no stores, delivery or migrations."""
from __future__ import annotations

import json
import os
import sqlite3
import re
import math
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from talonx_ops.notify import DESTINATIONS, resolve_destination_config


def _destination_fingerprint(cfg):
    """Return a non-reversible binding between validation evidence and config."""
    if not (cfg.bot_token and cfg.chat_id):
        return None
    import hashlib
    return hashlib.sha256((cfg.bot_token + '\\0' + cfg.chat_id).encode('utf-8')).hexdigest()


def notification_validation_view(path, configs):
    """Read explicit, sanitized RI-4 validation evidence; fail closed on errors."""
    output = {destination: False for destination in DESTINATIONS}
    if not path:
        return output
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        if record.get('schema_version') != 1 or record.get('kind') != 'ri4_controlled_telegram_validation':
            return output
        for destination in ("TRADE_EVENT", "OPERATIONS"):
            item = (record.get('destinations') or {}).get(destination) or {}
            output[destination] = (
                item.get('state') == 'SENT'
                and item.get('configuration_fingerprint') == _destination_fingerprint(configs[destination])
            )
    except (OSError, ValueError, TypeError):
        return output
    return output


def read_tables(path, names):
    """One consistent read transaction; missing tables remain explicitly unknown."""
    result = {name: None for name in names}
    if not Path(path).is_file():
        return result
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in names:
                if name in existing:
                    result[name] = [dict(r) for r in con.execute('SELECT * FROM "' + name + '"')]
    except sqlite3.Error:
        return {name: None for name in names}
    return result


def runtime_view(status, *, now, process_probe=None):
    def probe(pid, created):
        import psutil
        try:
            p = psutil.Process(int(pid))
            return p.is_running() and abs(p.create_time() - float(created)) < 0.01
        except (psutil.Error, TypeError, ValueError):
            return False
    age = None
    try:
        ts = datetime.fromisoformat(status['heartbeat_utc'].replace('Z', '+00:00'))
        age = (now - ts).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    identity_known = status.get('process_id') is not None and status.get('process_created_at') is not None
    alive = (process_probe or probe)(status.get('process_id'), status.get('process_created_at')) if identity_known else None
    fresh = age is not None and 0 <= age < float(status.get('heartbeat_ttl_s', 180))
    source = status.get('source') or {}
    degraded = source.get('degraded') or source.get('ok') is False or status.get('pricing_unavailable_recent')
    state = ('STOPPED' if alive is False else 'UNKNOWN' if alive is None else
             'DEGRADED' if not fresh or degraded else 'STARTING' if not status.get('last_tick_utc') else 'RUNNING')
    return dict(state=state, process_verified=alive, last_heartbeat=status.get('heartbeat_utc'),
                heartbeat_age_s=age, stale_heartbeat=not fresh,
                last_market_event=status.get('last_market_event_utc'),
                last_source_poll=source.get('last_ok_utc'),
                data_state='DEGRADED' if degraded else status.get('data_state', 'UNKNOWN'),
                provider_failures=bool(degraded), redis_health=status.get('redis_health', 'UNKNOWN'),
                delivery_activated=status.get('delivery_enabled') if fresh and alive else None,
                operations_delivery_activated=status.get('operations_delivery_enabled') if fresh and alive else None)


def notification_view(v2_rows, ops_rows, intel_rows=None, validation_path=None):
    configs = {d: resolve_destination_config(d) for d in DESTINATIONS}
    validation = notification_validation_view(
        validation_path if validation_path is not None else os.environ.get('TALONX_NOTIFY_VALIDATION_PATH'), configs)
    output = {}
    for d, cfg in configs.items():
        rows = [r for r in (v2_rows or []) + (ops_rows or []) if r.get('destination', 'TRADE_EVENT') == d]
        if d == 'TRADE_EVENT':
            rows += intel_rows or []
        counts = {s: 0 for s in ('PENDING', 'SENT', 'FAILED', 'EXPIRED', 'RETRY', 'HELD', 'AMBIGUOUS')}
        for r in rows:
            state = r.get('state', 'UNKNOWN')
            counts[state] = counts.get(state, 0) + 1
        failed = [r for r in rows if r.get('state') in ('FAILED', 'RETRY', 'AMBIGUOUS') or r.get('last_error')]
        prefix = 'TALONX_NOTIFY_' + d
        dedicated = all(os.environ.get(prefix + suffix, '').strip() for suffix in ('_BOT_TOKEN', '_CHAT_ID'))
        configured = bool(cfg.bot_token and cfg.chat_id) or (d == 'RESEARCH' and dedicated)
        shared = [other for other, c in configs.items() if other != d and cfg.chat_id and c.chat_id == cfg.chat_id]
        output[d] = dict(logical_routing_configured=True, enabled=cfg.enabled,
                         physical_destination_configured=configured,
                         configuration_reason=cfg.reason,
                         credential_source='DEDICATED' if dedicated else 'LEGACY_OR_MIXED' if configured else 'UNCONFIGURED',
                         shares_chat_with=shared, configuration_scope='observer process environment; runtime may differ',
                         real_delivery_validated=validation[d], counts=counts,
                         sources_available=dict(v2=v2_rows is not None, operations=ops_rows is not None,
                                                intelligence=intel_rows is not None),
                         last_success=max((r.get('sent_at_utc') or '' for r in rows if r.get('state') == 'SENT'), default='') or None,
                         last_failure=max((r.get('updated_at_utc') or r.get('last_attempt_at_utc') or '' for r in failed), default='') or None)
        # Never return raw error, payload, token, chat id or transport reference.
    return output


def operator_snapshot(db_path, *, now=None, status=None, notify_path=None, intel_path=None, process_probe=None, reconciliation_path=None, validation_path=None):
    now = now or datetime.now(timezone.utc)
    tables = read_tables(db_path, ('campaign', 'portfolio', 'positions', 'pending_entry_intents',
                                  'account_blocks', 'block_clearances', 'campaign_cutover_log', 'v2_alert_outbox'))
    campaign = (tables['campaign'] or [{}])[0]
    cash = (tables['portfolio'] or [{}])[0].get('cash')
    if cash is not None and not math.isfinite(cash):
        cash = None
    positions = tables['positions']
    intents = tables['pending_entry_intents']
    pending = [r for r in intents or [] if r['status'] == 'PENDING']
    allocation = campaign.get('per_position_allocation_usd')
    reserved = len(pending) * allocation if allocation is not None and intents is not None else None
    groups = {s: [p for p in positions or [] if p['status'] == s] for s in ('OPEN', 'EXIT_UNRESOLVED', 'CLOSED')}
    obligations = groups['OPEN'] + groups['EXIT_UNRESOLVED']
    cost = sum(p['position_cost'] for p in obligations) if positions is not None and all(p.get('position_cost') is not None for p in obligations) else None
    realized = sum(p['realized_pnl_usd'] for p in groups['CLOSED']) if positions is not None and all(p.get('realized_pnl_usd') is not None for p in groups['CLOSED']) else None
    start = campaign.get('starting_cash_usd')
    expected = start - cost + realized if all(x is not None and math.isfinite(x) for x in (start, cost, realized)) else None
    recon = 'UNKNOWN' if expected is None or cash is None else 'CASH_DEFICIT' if cash < 0 else 'LEDGER_MISMATCH' if abs(cash - expected) > 1.0 else 'HEALTHY'
    active = [b for b in tables['account_blocks'] or [] if b['status'] == 'ACTIVE']
    for r in intents or []:
        r['campaign_id'] = campaign.get('campaign_id')
        r['reserved_capital'] = allocation if r['status'] == 'PENDING' else 0
        r['recovery_state'] = r['status']
        try:
            from talonx_v2.calendar import recovery_deadline_session, session_close_utc
            deadline = session_close_utc(recovery_deadline_session(date.fromisoformat(r['target_entry_session']), 3))
            r['recovery_deadline_utc'] = deadline.isoformat()
            if r['status'] == 'PENDING':
                r['recovery_state'] = ('DEADLINE_PASSED_AWAITING_SERVICE' if now > deadline else
                                       'WAITING_FOR_ENTRY_SESSION' if now.date() < date.fromisoformat(r['target_entry_session']) else 'WAITING_FOR_PRICE_RECOVERY')
        except (ValueError, KeyError, TypeError):
            r['recovery_deadline_utc'] = None
            if r['status'] == 'PENDING':
                r['recovery_state'] = 'UNKNOWN'
    ops = read_tables(notify_path or os.environ.get('TALONX_NOTIFY_DB_PATH', 'notifications.db'), ('ops_notification_outbox',))
    intel = read_tables(intel_path, ('intelligence_delivery',)) if intel_path else {}
    delivery = notification_view(tables['v2_alert_outbox'], ops['ops_notification_outbox'], intel.get('intelligence_delivery'), validation_path=validation_path)
    runtime = runtime_view(status or {}, now=now, process_probe=process_probe)
    for item in delivery.values():
        item['real_delivery_validation_state'] = 'VALIDATED' if item['real_delivery_validated'] else 'NOT_VALIDATED'
    attention = []
    if active:
        attention.append('ACCOUNT_BLOCKED')
    if groups['EXIT_UNRESOLVED'] and not any(b['reason_type'] == 'EXIT_UNRESOLVED' for b in active):
        attention.append('EXIT_UNRESOLVED')
    if recon in ('CASH_DEFICIT', 'LEDGER_MISMATCH') and not any(b['reason_type'] == recon for b in active):
        attention.append('RECONCILIATION_FAILED')
    if any(any(d['counts'][s] for s in ('FAILED', 'RETRY', 'AMBIGUOUS')) for d in delivery.values()):
        attention.append('TELEGRAM_DELIVERY_FAILING')
    if runtime['provider_failures']:
        attention.append('PROVIDER_DATA_DEGRADED')
    if runtime['stale_heartbeat']:
        attention.append('STALE_HEARTBEAT')
    result = dict(campaign=campaign or {'provenance': 'UNKNOWN_LEGACY'},
                account=dict(starting_capital=start, settled_cash=cash, reserved_capital=reserved,
                             available_capital=cash-reserved if cash is not None and reserved is not None else None,
                             allocation_cap=allocation, allocated_capital=cost,
                             obligation_slots=len(obligations), reserved_slots=len(pending),
                             capacity_used=len(obligations)+len(pending), capacity_limit=20,
                             realized_pnl=realized, blocked=bool(active) if tables['account_blocks'] is not None else None),
                positions=groups, entry_intents=intents, blocks=tables['account_blocks'],
                clearance_history=tables['block_clearances'], cutover_history=tables['campaign_cutover_log'],
                clearance_action='Use python -m talonx_ops.prospective clear-block --help; operator, reason and evidence required. No dashboard clearance.',
                reconciliation=dict(state=recon, basis='Current read-only ledger arithmetic; not a persisted EOD run',
                                    checked_at=now.isoformat(), expected_cash=expected,
                                    persisted_run_state='NOT_RUN_OR_NOT_AVAILABLE', last_persisted_run=None,
                                    outstanding_obligations=len(groups['EXIT_UNRESOLVED'])),
                notifications=delivery, runtime=runtime, needs_attention=attention)

    path = reconciliation_path or os.environ.get("TALONX_V2_RECONCILIATION_PATH")
    if path:
        try:
            evidence = json.loads(Path(path).read_text(encoding="utf-8"))
            rec = evidence.get("v2_reconciliation", {})
            if rec.get("campaign_id") == campaign.get("campaign_id") and campaign.get("campaign_id"):
                assertions = evidence.get("asserts", {})
                keys = ("cash_plus_open_cost_reconciles", "no_negative_cash")
                ledger_checks = ("buys_eq_sells_plus_open_plus_unresolved", "whole_share_positions",
                                 "positive_finite_position_cost", "no_duplicate_buy_episode_id",
                                 "no_duplicate_position_episode_id", "no_stale_episode_entered")
                state = ("CASH_DEFICIT" if assertions.get(keys[1]) == "FAIL" else
                         "LEDGER_MISMATCH" if any(assertions.get(k) == "FAIL" for k in
                                                  (keys[0],) + ledger_checks
                                                  + ("corporate_action_adjustments_consistent",
                                                     "dividend_accounting_consistent")) else
                         "HEALTHY" if all(assertions.get(k) == "PASS" for k in keys + ledger_checks) else "UNKNOWN")
                result["reconciliation"].update(
                    persisted_run_state=state, evidence_reference=str(path),
                    last_persisted_run=evidence.get("reconciled_at_utc"),
                    persisted_run_is_historical=True)
        except (OSError, ValueError, TypeError):
            result["reconciliation"]["persisted_run_state"] = "UNKNOWN"
    return redact_output(result)


def redact_output(value):
    """Defense in depth for historic exception strings containing Telegram URLs."""
    secrets = [v for k, v in os.environ.items() if v and ('BOT_TOKEN' in k or k == 'TELEGRAM_CHAT_ID' or k.endswith('_CHAT_ID'))]
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items() if k.lower() not in ('bot_token', 'chat_id')}
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, '[REDACTED]')
            return re.sub(r'(?:bot)?[0-9]{6,}:[A-Za-z0-9_-]{20,}', '[REDACTED]', item)
        return item
    return clean(value)
