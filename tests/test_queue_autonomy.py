"""Clock, outbox and personal-yield checks; network delivery is always mocked."""
from datetime import timedelta
from types import SimpleNamespace
import threading
import pytest
from test_colony import m, reset, seed
from test_task_queue import enqueue, advance, ORE, RARE
from app import task_queue as q, queue_notifications as n, task_yields as y, discord_queue_worker as dw


def test_ten_second_schedule_without_messages(monkeypatch):
    clock=[m.now()];monkeypatch.setattr(m,'now',lambda:clock[0])
    enqueue(count=2);start=clock[0]
    for seconds,expected in [(9,0),(10,1),(19,1),(20,2)]:
        clock[0]=start+timedelta(seconds=seconds)
        q.run_one(m,'test','discord:u')
        with m.SessionLocal() as db:assert db.query(m.Player).one().actions==expected


def test_background_worker_finishes_and_notifies_without_requests(monkeypatch):
    from fastapi.testclient import TestClient
    clock=[m.now()];monkeypatch.setattr(m,'now',lambda:clock[0])
    enqueue(count=1);sent=threading.Event();texts=[]
    async def login(runtime):runtime.client=SimpleNamespace(close=_nothing);runtime.state='ready';return True
    async def _nothing():pass
    async def send(module,client,notice):texts.append(notice.content);sent.set()
    monkeypatch.setattr(dw.Runtime,'login',login);monkeypatch.setattr(dw,'send_notice',send)
    clock[0]+=timedelta(seconds=10)
    with TestClient(m.app):assert sent.wait(8)
    assert len(texts)==1 and 'QUEUE — COMPLETED' in texts[0] and 'Hematite Ore ×1' in texts[0]
    with m.SessionLocal() as db:assert db.query(n.Notice).one().state=='sent'


def test_rare_cooldown_wait_does_not_spend_attempt(monkeypatch):
    clock=[m.now()];monkeypatch.setattr(m,'now',lambda:clock[0])
    enqueue('mine:'+RARE,3)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12;db.commit()
    for seconds,expected in [(10,1),(10,1),(10,2)]:
        clock[0]+=timedelta(seconds=seconds);q.run_one(m,'test','discord:u')
        with m.SessionLocal() as db:assert db.query(m.Player).one().actions==expected


def test_notifications_retry_without_repeating_rewards(monkeypatch):
    enqueue(count=1);advance();calls=[]
    def fail(module,notice):calls.append(notice.id);raise n.DeliveryError('temporary')
    monkeypatch.setattr(n,'send',fail);n.deliver(m)
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one();assert row.state=='pending';row.next_at=m.now()-timedelta(seconds=1);db.commit()
    monkeypatch.setattr(n,'send',lambda module,notice:calls.append(notice.id));n.deliver(m);n.deliver(m)
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='sent'
        assert db.query(m.Player).one().ore==101
    assert len(calls)==2 and calls[0]==calls[1]


def test_new_queue_keeps_previous_notification_snapshot():
    enqueue(count=1);advance()
    q.control(m,'test','u','Citizen','discord','start','gather:'+y.STONE,2)
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one()
        assert 'Hematite Ore ×1' in row.content and row.recipient=='u'
        assert row.id!=db.query(n.Destination).one().run_id


def test_cancel_sends_cancellation_not_completion():
    enqueue(count=2);advance();q.control(m,'test','u','Citizen','discord','cancel')
    with m.SessionLocal() as db:
        assert db.query(n.NoticeEvent).one().kind=='cancelled'
        assert 'QUEUE — CANCELLED' in db.query(n.Notice).one().content


def test_discord_channel_mention_and_nonce(monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN','test-only')
    calls=[]
    def post(url,headers,payload):
        calls.append((url,payload));return {'id':'123'}
    monkeypatch.setattr(n,'post',post)
    n.send(m,SimpleNamespace(provider='discord',recipient='456',content='Done',id='a'*32,message_channel='789'))
    assert len(calls)==1 and calls[0][0].endswith('/channels/789/messages')
    assert calls[0][1]['content'].startswith('<@456>')
    assert calls[0][1]['allowed_mentions']=={'parse':[],'users':['456']}
    assert calls[0][1]['enforce_nonce'] is True


def test_discord_channel_permission_failure_is_reported_without_gameplay_loss(monkeypatch):
    enqueue(count=1);advance()
    def denied(module,row):raise n.DeliveryError('Notification HTTP 403',permanent=True)
    monkeypatch.setattr(n,'send',denied);n.deliver(m)
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='failed'
        p=db.query(m.Player).one();assert p.ore==101
        assert 'could not be delivered' in q.status(m,db,p,db.query(q.TaskQueue).one())


@pytest.mark.parametrize('action,mode',list(y.YIELDS))
@pytest.mark.parametrize('success',[True,False])
def test_option_yields_energy_and_failure(action,mode,success,monkeypatch):
    seed(provider='discord');monkeypatch.setattr(m.random,'random',lambda:0.5 if success else 0.99)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        if action in {'business','businesscontract'}:
            db.add(m.Business(channel_id='test',canonical_uid=p.twitch_uid,name='Test Business'));db.commit()
        equipment=y.EQUIPMENT.get((action,mode))
        if equipment:
            if equipment in m.QUALITY_RECIPES:m.add_quality_gear(db,p,equipment,'Standard')
            else:m.material_change(db,p,equipment,1)
        if mode=='expedite':m.material_change(db,p,'power_cell',1)
        db.commit();before={k:m.material_amount(db,p,k) for k in y.config(action,mode)[1]}
    text=m.action(action,'test','u',msg='mode:'+mode if mode else '',provider='discord').body.decode()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert p.actions==1,text
        assert p.successes==int(success),text
        for k,qty in y.config(action,mode)[1].items():assert m.material_amount(db,p,k)-before[k]==(qty if success else 0),text
        assert m.life_state(db,p).energy==100-y.config(action,mode)[0]


def test_specialist_modes_can_be_queued_and_keep_requirements(monkeypatch):
    enqueue('work:water@hydroponics',2)
    advance()
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).one().state=='paused'
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.material_change(db,p,'water_filter',1);db.commit()
    monkeypatch.setattr(m.random,'random',lambda:0.5)
    advance();advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        assert row.state=='completed' and p.crops==108
        assert 'Crop ×8' in q.status(m,db,p,row)


def test_byproducts_are_real_useful_catalog_materials():
    for energy,outputs in y.YIELDS.values():
        assert energy>=2
        for key in outputs:
            if key in {'crops','cargo'}:continue
            assert key in m.seed_content.ACTIVE
            assert any(key in r['inputs'] for r in m.seed_content.RECIPES.values()) or key in m.seed_content.EDIBLE or m.seed_content.PURPOSE[key]['mode']=='plant'


def test_notification_workers_claim_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    enqueue(count=1);advance();calls=[]
    monkeypatch.setattr(n,'send',lambda module,row:calls.append(row.id))
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:n.deliver(m),range(2)))
    assert len(calls)==1


def test_rate_limit_and_permission_errors_are_classified(monkeypatch):
    monkeypatch.setattr(n.requests,'post',lambda *a,**k:SimpleNamespace(status_code=429,json=lambda:{'retry_after':45}))
    with pytest.raises(n.DeliveryError) as error:n.post('https://example.invalid',{}, {})
    assert error.value.delay==45 and not error.value.permanent
    monkeypatch.setattr(n.requests,'post',lambda *a,**k:SimpleNamespace(status_code=403))
    with pytest.raises(n.DeliveryError) as error:n.post('https://example.invalid',{}, {})
    assert error.value.permanent


def test_twitch_completion_uses_configured_channel_and_verified_login(monkeypatch):
    for key,value in {'TWITCH_QUEUE_CHANNELS':'{"test":"123"}','TWITCH_BOT_ACCESS_TOKEN':'fake',
                      'TWITCH_CLIENT_ID':'client','TWITCH_BOT_USER_ID':'456'}.items():monkeypatch.setenv(key,value)
    calls=[]
    monkeypatch.setattr(n.requests,'get',lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'data':[{'login':'player'}]}))
    monkeypatch.setattr(n,'post',lambda url,headers,payload:calls.append(payload) or {'data':[{'is_sent':True}]})
    n.send(m,SimpleNamespace(provider='twitch',recipient='789',content='Complete',id='a'*32,channel_id='test'))
    assert calls[0]['broadcaster_id']=='123' and calls[0]['message']=='@player Complete'


def test_notification_retry_after_worker_restart(monkeypatch):
    enqueue(count=1);advance()
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one();row.state='sending';row.next_at=m.now()-timedelta(seconds=1);db.commit()
    calls=[];monkeypatch.setattr(n,'send',lambda module,row:calls.append(row.id));n.deliver(m)
    assert len(calls)==1
    with m.SessionLocal() as db:assert db.query(n.Notice).one().state=='sent'


def test_queue_remembers_origin_channel_across_requests():
    token=n.origin_channel.set('123456')
    try:enqueue(count=1)
    finally:n.origin_channel.reset(token)
    advance()
    with m.SessionLocal() as db:
        notice=db.query(n.Notice).one()
        assert notice.message_channel=='123456' and notice.recipient=='u'
    assert n.origin_channel.get()==''


def test_signed_discord_command_captures_the_real_channel(monkeypatch):
    import json
    from nacl.signing import SigningKey
    from test_colony import client
    key=SigningKey.generate();monkeypatch.setattr(m,'DISCORD_PUBLIC_KEY',key.verify_key.encode().hex())
    monkeypatch.setattr(m,'DISCORD_GAME_CHANNEL_ID','')
    monkeypatch.setattr(m.discord_deferred,'edit_original',lambda *args:True)
    payload={'application_id':'app','token':'test-token','type':2,'id':'10','channel_id':'98765','member':{'user':{'id':'12345','username':'Player'}},
             'data':{'name':'queue','options':[{'name':'action','value':'start'},
                                             {'name':'task','value':'mine:'+ORE},{'name':'count','value':1}]}}
    body=json.dumps(payload).encode();stamp='1234';signature=key.sign(stamp.encode()+body).signature.hex()
    response=client.post('/discord/interactions',content=body,
        headers={'X-Signature-Ed25519':signature,'X-Signature-Timestamp':stamp,'Content-Type':'application/json'})
    assert response.status_code==200,response.text
    with m.SessionLocal() as db:
        dest=db.query(n.Destination).one()
        assert dest.message_channel=='98765' and dest.recipient=='12345'
    assert n.origin_channel.get()==''


def test_coal_is_mined_with_common_material_rules_and_existing_price():
    assert y.COAL in q.ores() and 'mine:'+y.COAL in q.choices(m)
    assert 'gather:'+y.COAL not in q.choices(m)
    assert m.seed_content.source_hint(y.COAL).startswith('/mine ore:')
    assert m.crafting_progression.STARTER_MARKET[y.COAL]['buy']==4
    results=m._discord_autocomplete({'data':{'name':'mine','options':[{'name':'ore','focused':True,'value':'Coal'}]},
                                    'member':{'user':{'id':'u'}}})
    assert any(row['value']==y.COAL for row in results['data']['choices'])
    enqueue('mine:'+y.COAL,2);advance();advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert m.material_amount(db,p,y.COAL)==2
        assert 'Coal ×2' in q.status(m,db,p,db.query(q.TaskQueue).one())
