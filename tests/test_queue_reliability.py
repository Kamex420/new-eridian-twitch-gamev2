"""Fault injection verifies durable state transitions and transaction boundaries."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from test_colony import m,reset,seed
from test_task_queue import enqueue,advance,due,ORE
from app import task_queue as q,queue_notifications as n,discord_execution as execution


def set_energy(value):
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.life_state(db,p).energy=value;db.commit()


def test_needs_pause_notifies_once_then_resumes_and_completes(monkeypatch):
    enqueue(count=2);set_energy(19)
    advance();advance();advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one()
        assert row.state=='paused' and row.remaining==2
        assert db.query(n.NoticeEvent).one().kind=='paused'
        note=db.query(n.Notice).one()
        assert 'Energy: 19/100; need 20' in note.content and '/sleep' in note.content
    sent=[];monkeypatch.setattr(n,'send',lambda mod,row:sent.append(row.content));n.deliver(m)
    set_energy(100);advance();advance();n.deliver(m)
    assert len(sent)==2 and 'PAUSED' in sent[0] and 'COMPLETED' in sent[1]
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().remaining==0
        assert db.query(m.Player).one().ore==102


def test_needs_pause_is_saved_in_same_attempt_not_next_tick():
    enqueue(count=2);set_energy(20);advance()
    with m.SessionLocal() as db:
        queue=db.query(q.TaskQueue).one()
        assert queue.state=='paused' and queue.remaining==1
        assert db.query(n.NoticeEvent).one().kind=='paused'
        assert db.query(m.Player).one().ore==101


def test_last_attempt_completes_even_if_needs_drop_low():
    enqueue(count=1);set_energy(20);advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().state=='completed'
        assert db.query(n.NoticeEvent).one().kind=='completed'


def test_new_pause_after_recovery_is_a_new_episode():
    enqueue(count=3);set_energy(19);advance()
    set_energy(20);advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().remaining==2
        assert db.query(n.NoticeEvent).count()==2
        assert db.query(n.Notice).filter_by(state='pending').count()==1
        assert db.query(n.Notice).filter_by(state='superseded').count()==1


def test_material_pause_keeps_attempt_and_notifies():
    enqueue('work:delivery',2)
    with m.SessionLocal() as db:p=db.query(m.Player).one();p.cargo=0;db.commit()
    advance();advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().remaining==2
        assert db.query(n.NoticeEvent).one().kind=='paused'
        assert 'Cargo' in db.query(n.Notice).one().content


def test_faults_rollback_and_stop_after_three_with_one_alert(monkeypatch):
    enqueue(count=2)
    def fail(module,db,p,*args):
        p.ore+=999;db.commit()
        raise RuntimeError('simulated failure after nested commit')
    monkeypatch.setattr(q.s,'gather',fail)
    for i in range(3):
        advance()
        with m.SessionLocal() as db:
            assert db.query(m.Player).one().ore==100
            assert db.query(q.TaskQueue).one().remaining==2
            assert db.query(q.QueueHealth).one().failures==i+1
    advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().state=='error'
        assert db.query(n.NoticeEvent).one().kind=='error'
        assert 'simulated failure' not in db.query(n.Notice).one().content


def test_error_retry_backoff_does_not_loop_each_tick(monkeypatch):
    enqueue(count=1);due();calls=[]
    def fail(*args):calls.append(1);raise RuntimeError('temporary')
    monkeypatch.setattr(q.s,'gather',fail)
    q.tick(m);q.tick(m)
    assert calls==[1]


def test_transient_error_recovery_resets_failure_streak(monkeypatch):
    enqueue(count=2);original=q.s.gather
    def fail(*args):raise RuntimeError('temporary')
    monkeypatch.setattr(q.s,'gather',fail);advance()
    monkeypatch.setattr(q.s,'gather',original);advance()
    with m.SessionLocal() as db:
        assert db.query(q.QueueHealth).one().failures==0
        assert db.query(q.TaskQueue).one().remaining==1
        assert db.query(n.Notice).count()==0


def test_outbox_failure_rolls_back_completed_work(monkeypatch):
    enqueue(count=1);original=n.complete
    def fail(*args):raise RuntimeError('outbox write failure')
    monkeypatch.setattr(n,'complete',fail);advance()
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().ore==100
        assert db.query(q.TaskQueue).one().remaining==1
    monkeypatch.setattr(n,'complete',original);advance()
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().ore==101
        assert db.query(n.Notice).count()==1


def test_duplicate_discord_interactions_execute_once_even_concurrently(monkeypatch):
    calls=[]
    def dispatch(*args):calls.append(1);return 'Saved result'
    monkeypatch.setattr(m,'_discord_call_internal',dispatch)
    def run(_):return execution.execute(m,{'id':'same-interaction'},'farm','u','Player',{})
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,range(2)))
    assert calls==[1] and results==['Saved result','Saved result']
    with m.SessionLocal() as db:assert db.query(execution.CommandReceipt).count()==1


def test_discord_rollback_does_not_leave_a_receipt_or_partial_rewards(monkeypatch):
    seed(provider='discord')
    def fail(*args):
        with m.SessionLocal() as db:
            p=db.query(m.Player).one();p.sc+=123;db.commit()
        raise RuntimeError('after commit')
    monkeypatch.setattr(m,'_discord_call_internal',fail)
    with pytest.raises(RuntimeError):execution.execute(m,{'id':'broken'},'farm','u','Player',{})
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().sc==10000
        assert db.query(execution.CommandReceipt).count()==0


def test_manual_action_rollback_restores_spent_needs(monkeypatch):
    seed(provider='discord')
    def fail(*args,**kwargs):raise RuntimeError('failure during rewards')
    monkeypatch.setattr(m,'gain_skill',fail)
    with pytest.raises(RuntimeError):m.action('harvest','test','u',provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert m.life_state(db,p).energy==100 and p.crops==100 and p.actions==0


def test_discord_receipt_shows_secondary_rewards_and_hides_background_info():
    seed(provider='discord')
    content=m.action('harvest','test','u',provider='discord').body.decode()
    data=m._discord_json_message(content,message_type='farm')['data']
    text=json.dumps(data,ensure_ascii=False)
    assert 'Pumpkin +1' in text and 'Pumpkin Seeds +1' in text and 'Crop +2' in text
    assert 'Final chance' not in text and 'Society condition' not in text and 'Daily Variety' not in text
    assert 'energy -3' in text


def test_used_up_material_is_in_receipt():
    seed(provider='discord')
    with m.SessionLocal() as db:p=db.query(m.Player).one();p.cargo=1;db.commit()
    content=m.action('delivery','test','u',provider='discord').body.decode()
    assert 'Cargo -1' in content
    data=m._discord_json_message(content,message_type='delivery')['data']
    assert 'Cargo -1' in json.dumps(data)


def test_postgres_url_uses_installed_driver():
    from app.db import normalize_url
    for url in ('postgres://user:pass@host/db','postgresql://user:pass@host/db'):
        assert normalize_url(url)=='postgresql+psycopg://user:pass@host/db'
    assert normalize_url('sqlite:///test.db')=='sqlite:///test.db'


def test_health_reports_unavailable_database_without_details(monkeypatch):
    from fastapi import HTTPException
    def fail():raise RuntimeError('private connection details')
    monkeypatch.setattr(m.engine,'connect',fail)
    with pytest.raises(HTTPException) as error:m.health()
    assert error.value.status_code==503 and 'private' not in error.value.detail


def test_cooldown_state_does_not_depend_on_english_copy(monkeypatch):
    enqueue(count=1)
    def waiting(*args):
        q.cooldown_wait.set(12)
        return 'This wording does not contain the old cooldown phrase.'
    monkeypatch.setattr(q.s,'gather',waiting);advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one()
        assert row.state=='running' and row.remaining==1
        assert db.query(n.Notice).count()==0


def test_pause_delivery_retry_never_repeats_attempts(monkeypatch):
    enqueue(count=2);set_energy(19);advance()
    def unavailable(*args):raise n.DeliveryError('temporary')
    monkeypatch.setattr(n,'send',unavailable);n.deliver(m)
    with m.SessionLocal() as db:
        notice=db.query(n.Notice).one();notice.next_at=m.now()-timedelta(seconds=1);db.commit()
    sent=[];monkeypatch.setattr(n,'send',lambda mod,row:sent.append(row.id));n.deliver(m);n.deliver(m)
    assert len(sent)==1
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().actions==0
        assert db.query(q.TaskQueue).one().remaining==2


def test_retrying_formatted_response_does_not_repeat_saved_action(monkeypatch):
    from app import discord_deferred as deferred
    calls=[];sent=[]
    monkeypatch.setattr(m,'_discord_call_internal',lambda *args:calls.append(1) or 'Saved reward')
    def formatting_error(*args,**kwargs):raise RuntimeError('formatting storage is unavailable')
    monkeypatch.setattr(m,'_discord_json_message',formatting_error)
    monkeypatch.setattr(deferred,'edit_original',lambda *args:sent.append(args[2]))
    for _ in range(2):deferred.finish(m,{'id':'same','application_id':'test','token':'fake'},'farm','u','Player',{})
    assert calls==[1] and all(row['content']=='Saved reward' for row in sent)


@pytest.mark.parametrize('key',['','change-me'])
def test_default_admin_credentials_cannot_mutate_world(monkeypatch,key):
    monkeypatch.setattr(m,'ADMIN_KEY',key)
    assert 'Invalid' in m.admin_event('siro','on','test',level=500,key=key).body.decode()
    assert 'required' in m.next_day('test',level=500,key=key).body.decode()
    with m.SessionLocal() as db:assert db.query(m.Society).count()==0


def test_stop_alert_falls_back_when_embeds_are_forbidden(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('DISCORD_BOT_TOKEN','fake')
    calls=[]
    def post(url,headers,payload):
        calls.append(json.loads(json.dumps(payload)))
        if len(calls)==1:raise n.DeliveryError('Notification HTTP 403',permanent=True)
        return {'id':'sent'}
    monkeypatch.setattr(n,'post',post)
    n.send(m,SimpleNamespace(provider='discord',recipient='123',message_channel='456',id='a'*32,
        content='TASK QUEUE — PAUSED\nMine Coal\nPAUSE REASON\nEnergy: 19/100; need 20. Use /sleep.'))
    assert len(calls)==2 and 'embeds' not in calls[1]
    assert '<@123>' in calls[1]['content'] and 'Use /sleep' in calls[1]['content']
    assert calls[1]['allowed_mentions']['users']==['123']
