"""RI3-N: isolated operator fixture and boundary regressions. No production stores."""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ops.operator_read import operator_snapshot, runtime_view, notification_view
from talonx_ops.notify import resolve_destination_config
from talonx_ops.notify.outbox import NotifyStore
from talonx_ops.notify.producers import enqueue_degraded_health, record_intelligence_health
from talonx_v2 import paper
from talonx_v2.store import V2Store
from talonx_v2.config import V2Config
from test_ri1_campaign_identity import _decision, _pending_row

NOW = datetime(2026, 9, 18, 15, tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    # Imported config modules may load .env; all sends are also blocked by the network guard.
    for k in list(os.environ):
        if k.startswith('TALONX_NOTIFY_') or k.startswith('TELEGRAM_'):
            monkeypatch.delenv(k)
    monkeypatch.setenv('TALONX_NOTIFY_DB_PATH', str(tmp_path / 'ops.db'))
    monkeypatch.setenv('TALONX_V2_DB_PATH', str(tmp_path / 'v.db'))
    monkeypatch.setenv('TALONX_V2_STATUS_PATH', str(tmp_path / 'status.json'))

@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = V2Store(str(tmp_path/'v.db'), starting_cash=100000, campaign_id='RI3', strategy='INSIDER_V2', per_position_allocation_usd=10000)
    cfg = V2Config()
    for name in ('OPEN', 'UNRESOLVED', 'SETTLED'):
        paper.enter_position(store, _decision(name, name), entry_price=100,
                             entry_session=date(2026,9,8), config=cfg)
    pos = next(p for p in store.all_positions() if p['symbol']=='SETTLED')
    paper.close_position(store, pos, exit_price=110, exit_session=date(2026,9,18), config=cfg)
    pos = next(p for p in store.all_positions() if p['symbol']=='UNRESOLVED')
    store.mark_exit_unresolved(pos['position_id'], detail='missing exit price; evidence RI3-N')
    for name, state in [('PENDING','PENDING'),('CUTOVER','CANCELLED_CUTOVER'),('FILLED','FILLED'),('EXPIRED','EXPIRED_STALE')]:
        intent = _pending_row(store, episode_id=name, target_entry_session=date(2026,9,17))
        if state != 'PENDING':
            store.mark_entry_intent(intent['intent_id'], state)
    ops = NotifyStore(str(tmp_path/'ops.db'))
    for name, dest, state in [('retry','OPERATIONS','RETRY'),('sent','TRADE_EVENT','SENT')]:
        ops.enqueue(event_id=name,destination=dest,event_type='FIXTURE',producer='fixture',dedup_key=name,payload_text='fixture',provenance={})
        ops.update_outbox(name,state=state,attempts=1,last_error='fixture failure' if state=='RETRY' else None,sent=state=='SENT')
    status = dict(heartbeat_utc=NOW.isoformat(),heartbeat_ttl_s=180,process_id=123,process_created_at=1,
                  last_tick_utc=NOW.isoformat(),source={'ok':True},data_state='CURRENT',delivery_enabled=False)
    (tmp_path/'status.json').write_text(json.dumps(status))
    def read(**kw):
        return operator_snapshot(store.path, now=NOW, status=status, process_probe=lambda *a:True, **kw)
    return store, ops, read, status


def test_full_operator_fixture(fixture):
    store,ops,read,status=fixture
    view=read(); a=view['account']
    assert view['campaign']['campaign_id']=='RI3'
    assert view['campaign']['strategy']=='INSIDER_V2'
    assert view['campaign']['strategy_version']=='INSIDER_BUY_CLUSTER_V2@1'
    assert view['campaign']['execution_mode']=='PAPER'
    assert a['starting_capital']==100000
    assert a['settled_cash']==81000
    assert a['reserved_capital']==10000
    assert a['available_capital']==71000
    assert a['allocation_cap']==10000
    assert a['allocated_capital']==20000
    assert a['obligation_slots']==2 and a['capacity_used']==3
    assert a['realized_pnl']==1000
    assert [len(view['positions'][s]) for s in ('OPEN','EXIT_UNRESOLVED','CLOSED')]==[1,1,1]
    assert view['blocks'][0]['reason_type']=='EXIT_UNRESOLVED'
    assert 'RI3-N' in view['blocks'][0]['detail']
    assert view['blocks'][0]['reference'] and view['blocks'][0]['detected_at_utc']
    assert a['blocked']
    intents={i['episode_id']:i for i in view['entry_intents']}
    assert intents['PENDING']['recovery_state']=='WAITING_FOR_PRICE_RECOVERY'
    assert intents['PENDING']['recovery_deadline_utc']=='2026-09-21T20:00:00+00:00'
    assert intents['CUTOVER']['status']=='CANCELLED_CUTOVER'
    assert intents['FILLED']['reserved_capital']==0
    assert intents['EXPIRED']['recovery_state']=='EXPIRED_STALE'
    assert view['reconciliation']['state']=='HEALTHY'
    assert view['reconciliation']['outstanding_obligations']==1
    assert view['reconciliation']['persisted_run_state']=='NOT_RUN_OR_NOT_AVAILABLE'
    assert view['notifications']['OPERATIONS']['counts']['RETRY']==1
    assert view['notifications']['OPERATIONS']['last_failure']
    assert view['notifications']['TRADE_EVENT']['counts']['SENT']==1
    assert view['notifications']['TRADE_EVENT']['last_success']
    assert not view['notifications']['RESEARCH']['enabled']
    assert view['runtime']['state']=='RUNNING'
    assert set(view['needs_attention'])=={'ACCOUNT_BLOCKED','TELEGRAM_DELIVERY_FAILING'}
    if os.environ.get('TALONX_RI3_EVIDENCE_DIR'):
        (Path(os.environ['TALONX_RI3_EVIDENCE_DIR'])/'operator_fixture.json').write_text(json.dumps(view,indent=2),encoding='utf-8')

@pytest.mark.parametrize('cash,expected',[(80000,'LEDGER_MISMATCH'),(-1,'CASH_DEFICIT')])
def test_failed_reconciliation(fixture,cash,expected):
    store,_,read,_=fixture
    with store._conn() as c: c.execute('UPDATE portfolio SET cash=?',(cash,))
    assert read()['reconciliation']['state']==expected


def test_unknown_legacy_and_missing_database(fixture,tmp_path):
    store,_,read,_=fixture
    with store._conn() as c: c.execute('UPDATE campaign SET starting_cash_usd=NULL')
    assert read()['account']['starting_capital'] is None
    assert read()['reconciliation']['state']=='UNKNOWN'
    assert operator_snapshot(tmp_path/'missing.db')['account']['settled_cash'] is None
    assert not (tmp_path/'missing.db').exists()


def test_reads_never_mutate_or_send(fixture,monkeypatch):
    store,ops,read,_=fixture
    from talonx_dispatch.telegram_client import TelegramClient
    def forbidden(*a,**kw): raise AssertionError('side effect from operator read')
    monkeypatch.setattr(TelegramClient,'send',forbidden)
    monkeypatch.setattr(V2Store,'__init__',forbidden)
    monkeypatch.setattr(NotifyStore,'__init__',forbidden)
    def dump(path):
        with sqlite3.connect(path) as c: return '\n'.join(c.iterdump())
    before=[dump(store.path),dump(ops.path)]
    for _ in range(3): read()
    from talonx_ops.dashboard_read import DashboardReadModel
    DashboardReadModel(home=Path(store.path).parent,exp_home=Path(store.path).parent/'exp',
                       now=NOW,check_processes=False).v2_active_strategy()
    assert before==[dump(store.path),dump(ops.path)]

@pytest.mark.parametrize('alive,age,state',[(False,0,'STOPPED'),(True,0,'RUNNING'),(True,181,'DEGRADED'),(True,-30,'DEGRADED')])
def test_process_and_heartbeat(fixture,alive,age,state):
    status=dict(fixture[3],heartbeat_utc=(NOW-timedelta(seconds=age)).isoformat())
    assert runtime_view(status,now=NOW,process_probe=lambda *a:alive)['state']==state


def test_missing_identity_never_running_and_degraded_data(fixture):
    status=dict(fixture[3]); status.pop('process_id')
    assert runtime_view(status,now=NOW)['state']=='UNKNOWN'
    status=dict(fixture[3],source={'ok':False})
    v=runtime_view(status,now=NOW,process_probe=lambda *a:True)
    assert v['state']=='DEGRADED' and v['provider_failures']


def test_configuration_secrets_and_shared_physical_chat(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','123456:abcdefghijklmnopqrstuvwxyz')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','primary-chat')
    view=notification_view([],[])
    assert view['TRADE_EVENT']['shares_chat_with']==['OPERATIONS']
    assert view['OPERATIONS']['credential_source']=='LEGACY_OR_MIXED'
    assert 'abcdefghijklmnopqrstuvwxyz' not in json.dumps(view)
    assert 'primary-chat' not in json.dumps(view)
    monkeypatch.setenv('TALONX_NOTIFY_OPERATIONS_BOT_TOKEN','ops-token')
    monkeypatch.setenv('TALONX_NOTIFY_OPERATIONS_CHAT_ID','ops-chat')
    assert notification_view([],[])['OPERATIONS']['shares_chat_with']==[]
    assert not view['TRADE_EVENT']['real_delivery_validated']

@pytest.mark.parametrize('enabled,chat,expected',[('0','research',False),('1','primary',False),('1','research',True)])
def test_research_no_primary_fallback(monkeypatch,enabled,chat,expected):
    monkeypatch.setenv('TELEGRAM_CHAT_ID','primary')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','primary-token')
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_ENABLED',enabled)
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_BOT_TOKEN','research-token')
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_CHAT_ID',chat)
    assert resolve_destination_config('RESEARCH').enabled is expected


def test_research_cannot_reuse_primary_bot_in_a_different_chat(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','shared-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','primary')
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_ENABLED','1')
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_BOT_TOKEN','shared-token')
    monkeypatch.setenv('TALONX_NOTIFY_RESEARCH_CHAT_ID','research')
    assert not resolve_destination_config('RESEARCH').enabled


def test_intelligence_routes_trade_event(monkeypatch):
    import talonx_ops.notify as n
    from talonx_ingest.intelligence.delivery.pipeline import TelegramSenderAdapter
    calls=[]
    fake=type('Fake',(),{'is_configured':True})()
    monkeypatch.setattr(n,'telegram_client_for',lambda dest: calls.append(dest) or fake)
    assert TelegramSenderAdapter().configured
    assert calls==['TRADE_EVENT']


def test_health_dedup_and_intelligence_failure_operations(tmp_path,monkeypatch):
    ops=NotifyStore(str(tmp_path/'ops.db'))
    for _ in range(20): enqueue_degraded_health(ops,component='v2',condition='SOURCE_DEGRADED',now=NOW)
    assert len(ops.all_outbox())==1
    assert ops.all_outbox()[0]['destination']=='OPERATIONS'
    monkeypatch.setenv('TALONX_NOTIFY_OPERATIONS_ENABLED','1')
    for _ in range(10): record_intelligence_health(degraded=True,now=NOW)
    assert len(ops.all_outbox())==2
    assert all(r['destination']=='OPERATIONS' for r in ops.all_outbox())


def test_status_cli_does_not_create_db(tmp_path,capsys):
    from talonx_v2.run import main
    path=tmp_path/'absent.db'
    assert main(['--mode','status','--db',str(path),'--status-path',str(tmp_path/'absent.json')])==0
    assert not path.exists()
    assert json.loads(capsys.readouterr().out)['runtime']['state']=='UNKNOWN'


def test_dashboard_integrates_fixture(fixture,tmp_path,monkeypatch):
    from talonx_ops.dashboard_read import DashboardReadModel
    store,_,_,_=fixture
    view=DashboardReadModel(home=tmp_path,exp_home=tmp_path/'exp',now=NOW,check_processes=False).v2_active_strategy()
    assert view['ledger']['starting_campaign_cash']==100000
    assert view['ledger']['available_capital']==71000
    assert view['ledger']['allocated_capital']==20000
    assert view['ledger']['capacity']=='3/20'
    assert view['ledger']['unresolved_positions'][0]['symbol']=='UNRESOLVED'
    assert view['operator']['runtime']['state']=='STOPPED'
    assert view['ledger']['performance']['reconciliation']['status']=='EXACT'


def test_persisted_reconciliation_campaign_scope(fixture,tmp_path):
    path=tmp_path/'eod.json'
    path.write_text(json.dumps(dict(v2_reconciliation={'campaign_id':'RI3'},
        asserts={'cash_plus_open_cost_reconciles':'FAIL','no_negative_cash':'PASS'},reconciled_at_utc=NOW.isoformat())))
    view=fixture[2](reconciliation_path=path)
    assert view['reconciliation']['persisted_run_state']=='LEDGER_MISMATCH'
    assert view['reconciliation']['last_persisted_run']==NOW.isoformat()
    data=json.loads(path.read_text()); data['v2_reconciliation']['campaign_id']='OTHER'; path.write_text(json.dumps(data))
    assert fixture[2](reconciliation_path=path)['reconciliation']['persisted_run_state']=='NOT_RUN_OR_NOT_AVAILABLE'

def test_original_default_transport_is_research_only(tmp_path,monkeypatch):
    from talonx_dispatch.consumer import DispatchAgent
    from talonx_dispatch.store import AuditStore
    from talonx_watchlist.store import TickerWatchlistStore
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','primary-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','primary-chat')
    agent=DispatchAgent(store=AuditStore(tmp_path/'audit.db'),watchlist_store=TickerWatchlistStore(tmp_path/'watch.db'))
    assert not agent.telegram_client.is_configured
    assert agent.reply_listener.config.telegram_bot_token == "primary-token"
    assert agent.reply_listener.primary_only


def test_expired_pending_remains_reserved_until_writer_changes_it(fixture):
    store,_,_,status=fixture
    v=operator_snapshot(store.path,now=NOW+timedelta(days=10),status=status)
    pending=next(i for i in v['entry_intents'] if i['status']=='PENDING')
    assert pending['recovery_state']=='DEADLINE_PASSED_AWAITING_SERVICE'
    assert v['account']['reserved_capital']==10000
    assert store.entry_intent('PENDING')['status']=='PENDING'


def test_clearance_attempt_history_visible(fixture):
    store,_,read,_=fixture
    block=read()['blocks'][0]
    store.attempt_block_clearance(block_id=block['block_id'],operator_id='fixture-operator',
        reason='review',evidence_ref='fixture-evidence',allow=False,detail='still unresolved')
    view=read()
    assert view['account']['blocked']
    assert view['clearance_history'][0]['evidence_ref']=='fixture-evidence'
    assert view['clearance_history'][0]['outcome']=='REFUSED'


def test_persisted_fee_economics_not_rebuilt(tmp_path):
    store=V2Store(str(tmp_path/'fees.db'),starting_cash=100000,per_position_allocation_usd=10000)
    paper.enter_position(store,_decision(),entry_price=100,entry_session=date(2026,9,8),config=V2Config(),fee_fn=lambda n,p:5)
    pos=store.all_positions()[0]
    paper.close_position(store,pos,exit_price=110,exit_session=date(2026,9,18),config=V2Config(),fee_fn=lambda n,p:7)
    view=operator_snapshot(store.path)
    assert view['account']['realized_pnl']==99*110-7-(99*100+5)
    assert view['reconciliation']['state']=='HEALTHY'


def test_historic_token_error_redacted(fixture,monkeypatch):
    from talonx_ops.operator_read import redact_output
    token='123456:abcdefghijklmnopqrstuvwxyz'
    assert token not in json.dumps(redact_output({'last_error':'https://api.telegram.org/bot'+token+'/sendMessage'}))


def test_renderer_shows_end_to_end_fixture(fixture,tmp_path):
    import subprocess
    operator=fixture[2]()
    data=dict(operator=operator,ledger=dict(cash=81000,starting_campaign_cash=100000,reserved_capital=10000,available_capital=71000))
    input_path=tmp_path/'view.json'; input_path.write_text(json.dumps(data))
    script=r'''
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('dashboard_web_static/index.html','utf8');
const src=html.split('<script>')[1].split('</script>')[0];
new vm.Script(src); // compile the entire shipped script
const helpers=src.slice(src.indexOf('function pill'),src.indexOf('function renderOverview'));
const cost=src.slice(src.indexOf('function costLine'),src.indexOf('// Task 119A A1'));
const render=src.slice(src.indexOf('function renderV2(d)'),src.indexOf('function renderV2Discovery'));
const ctx={};vm.createContext(ctx);vm.runInContext(helpers+cost+render,ctx);
const result=ctx.renderV2(JSON.parse(fs.readFileSync(process.argv[1],'utf8')));
fs.writeFileSync(process.argv[2],result);
'''
    out=tmp_path/'render.html'
    proc=subprocess.run(['node','-e',script,str(input_path),str(out)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    rendered=out.read_text(encoding='utf-8')
    for text in ['RI3','EXIT_UNRESOLVED','CANCELLED_CUTOVER','71000','10000','OPERATIONS','RESEARCH','ACCOUNT_BLOCKED','WAITING_FOR_PRICE_RECOVERY']:
        assert text in rendered
    assert '$300,000 campaign ledger' not in rendered
    if os.environ.get('TALONX_RI3_EVIDENCE_DIR'):
        html=Path('dashboard_web_static/index.html').read_text(encoding='utf-8')
        style=html.split('<style>')[1].split('</style>')[0]
        (Path(os.environ['TALONX_RI3_EVIDENCE_DIR'])/'operator_fixture.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>RI3 isolated fixture</title><style>'+style+'</style>'+rendered,encoding='utf-8')

def test_live_tick_degraded_health_is_bounded(tmp_path,monkeypatch):
    from test_ri1_campaign_identity import _svc
    from talonx_v2.service import V2SourceError
    import talonx_ops.notify.worker as worker
    svc=_svc(tmp_path,tmp_path/'live.db',name='health',symbols=[])
    ops=NotifyStore(str(tmp_path/'ops.db')); svc._ops_notify_store=ops
    monkeypatch.setattr(worker,'drain',lambda *a,**kw:{'sent':0})
    def unavailable(**kw): raise V2SourceError('fixture degraded source')
    monkeypatch.setattr(svc,'_records',unavailable)
    for _ in range(3): svc.tick(as_of=date(2026,9,18))
    rows=ops.all_outbox()
    assert len(rows)==1
    assert rows[0]['destination']=='OPERATIONS' and rows[0]['event_type']=='DEGRADED_HEALTH'
    status=json.loads(svc.status_path.read_text())
    assert status['process_id']==os.getpid()
    assert status['process_created_at']>0
    assert status['operations_delivery_enabled']


def test_alternate_v2_readers_preserve_unresolved(fixture,monkeypatch):
    from talonx_v2.dashboard_read import build_section, eod_view
    store=fixture[0]
    def forbidden(*a,**kw): raise AssertionError('writable store connection used by reader')
    monkeypatch.setattr(store,'_conn',forbidden)
    view=build_section(store,as_of_session=NOW.date())
    assert view['occupied_capacity']==3
    assert len(view['unresolved_positions'])==1
    eod=eod_view(store,as_of_session=NOW.date())
    assert eod['obligation_slots']==2 and len(eod['exit_unresolved'])==1


def test_reconciliation_all_invariants_required(fixture,tmp_path):
    checks=('cash_plus_open_cost_reconciles','no_negative_cash',
            'buys_eq_sells_plus_open_plus_unresolved','whole_share_positions',
            'positive_finite_position_cost','no_duplicate_buy_episode_id',
            'no_duplicate_position_episode_id','no_stale_episode_entered')
    data=dict(v2_reconciliation={'campaign_id':'RI3'},asserts={k:'PASS' for k in checks})
    path=tmp_path/'eod.json'; path.write_text(json.dumps(data))
    assert fixture[2](reconciliation_path=path)['reconciliation']['persisted_run_state']=='HEALTHY'
    data['asserts']['whole_share_positions']='FAIL'; path.write_text(json.dumps(data))
    assert fixture[2](reconciliation_path=path)['reconciliation']['persisted_run_state']=='LEDGER_MISMATCH'


@pytest.mark.asyncio
async def test_primary_listener_preserves_ping_but_blocks_original_details(tmp_path):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    from talonx_dispatch.config import DispatchConfig
    class ForbiddenStore:
        def get_by_id(self,*a): raise AssertionError('Research lookup in primary destination')
    listener=TelegramReplyListener(ForbiddenStore(),DispatchConfig(telegram_chat_id='primary'),
                                   telegram_client=AsyncMock(),primary_only=True)
    listener._handle_ping=AsyncMock(); listener._reply=AsyncMock()
    await listener._handle_update(SimpleNamespace(message=SimpleNamespace(text='/ping',chat_id='primary')))
    listener._handle_ping.assert_awaited_once()
    await listener._handle_update(SimpleNamespace(message=SimpleNamespace(text='47',chat_id='primary')))
    assert 'dashboard' in listener._reply.call_args.args[0]
