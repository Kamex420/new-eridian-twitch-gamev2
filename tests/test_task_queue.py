import json
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_colony import m,reset,seed,client
from app import task_queue as q,seed_content as s

ORE=m.item_identity.ALIASES['ore']
RARE=m.item_identity.ALIASES['rare_ore']

def due():
    with m.SessionLocal() as db:
        for row in db.query(q.TaskQueue):row.next_at=m.now()-timedelta(seconds=1)
        for row in db.query(m.Cooldown):row.ready_at=m.now()-timedelta(seconds=1)
        db.commit()

def advance():
    due();q.tick(m)

def enqueue(task='mine:'+ORE,count=3):
    seed(provider='discord')
    return m.queued_tasks('test','u',action='start',task=task,count=count,provider='discord').body.decode()

@pytest.mark.parametrize('count',[0,11,-1])
def test_queue_rejects_out_of_range_counts(count):
    assert '1 to 10' in enqueue(count=count)
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).count()==0

def test_mine_lists_all_ores_and_preview_spends_nothing():
    result=m.mining('test','u',provider='discord').body.decode()
    for k in q.ores():assert s.item_label(k) in result
    result=m.mining('test','u',ore=RARE,count=10,provider='discord').body.decode()
    assert '47 Energy' in result and '29 Nutrition' in result
    assert 'Harvesting level 3' in result
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).count()==0
        assert db.query(m.Player).one().actions==0

def test_queue_completes_and_does_not_repeat():
    enqueue(count=3)
    for _ in range(4):advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        assert p.ore==103 and p.actions==3
        assert row.remaining==0 and row.state=='completed'
        assert m.life_state(db,p).energy==94

def test_only_one_type_even_if_same_task_or_other_platform():
    enqueue(count=10)
    result=m.queued_tasks('test','u',action='start',task='work:harvest',count=1,provider='discord').body.decode()
    assert 'already have a queue' in result
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        db.add(m.Identity(channel_id='test',provider='twitch',provider_uid='linked',canonical_uid=p.twitch_uid));db.commit()
    assert 'already have a queue' in m.queued_tasks('test','linked',action='start',task='mine:'+ORE,count=2).body.decode()

@pytest.mark.parametrize('need',['energy','nutrition','social'])
def test_needs_pause_without_spending_then_resume(need):
    enqueue(count=2)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();setattr(m.life_state(db,p),need,19);db.commit()
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        assert row.state=='paused' and row.remaining==2 and p.ore==100
        assert need.capitalize() in row.result and '20' in row.result
        setattr(m.life_state(db,p),need,22);db.commit()
    advance()
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).one().remaining==1

def test_passive_recharge_automatically_resumes_queue():
    enqueue(count=1)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();life=m.life_state(db,p);life.energy=19;db.commit()
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();life=m.life_state(db,p);life.last_decay_at=m.now()-timedelta(minutes=16);db.commit()
    advance()
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).one().state=='completed'

def test_low_needs_mid_queue_stop_next_attempt():
    enqueue(count=3)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.life_state(db,p).energy=20;db.commit()
    advance();advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one();assert row.remaining==2 and row.state=='paused'
        assert db.query(m.Player).one().ore==101

def test_missing_materials_pause_crafting_then_resume_same_account():
    enqueue('make:component',2)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.ore=0;db.commit()
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        assert row.remaining==2 and row.state=='paused'
        assert 'have 0' in row.result and 'missing 1' in row.result
        p.ore=2;db.commit()
    advance();advance()
    with m.SessionLocal() as db:
        assert db.query(m.Player).count()==1
        p=db.query(m.Player).one();assert p.ore==0 and p.components==102
        assert db.query(q.TaskQueue).one().remaining==0

def test_failure_counts_as_attempt(monkeypatch):
    enqueue('work:harvest',2);monkeypatch.setattr(m.random,'random',lambda:0.99)
    advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one();assert row.remaining==1
        assert 'TASK FAILED' in row.result

def test_rare_steps_do_not_award_an_ore_each_attempt():
    enqueue('mine:'+RARE,3)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12;db.commit()
    advance()
    with m.SessionLocal() as db:assert db.query(m.Player).one().rare_ore==100
    advance();advance()
    with m.SessionLocal() as db:assert db.query(m.Player).one().rare_ore==101

def test_cooldown_and_two_workers_cannot_double_execute():
    enqueue(count=2);due()
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:q.run_one(m,'test','discord:u'),range(2)))
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().ore==101
        assert db.query(q.TaskQueue).one().remaining==1

def test_gameplay_and_queue_counter_rollback_together(monkeypatch):
    enqueue(count=2);due();original=s.gather
    def fail_after_commit(*args):
        original(*args);raise RuntimeError('simulated crash after handler commit')
    monkeypatch.setattr(s,'gather',fail_after_commit)
    with pytest.raises(RuntimeError):q.run_one(m,'test','discord:u')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.ore==100 and p.actions==0
        assert db.query(q.TaskQueue).one().remaining==2
        assert db.query(m.Cooldown).count()==0

def test_cancel_keeps_completed_work():
    enqueue();advance()
    m.queued_tasks('test','u',action='cancel',provider='discord');advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().state=='cancelled'
        assert db.query(m.Player).one().ore==101

def test_queue_survives_new_sessions_and_checks_skill_requirements():
    enqueue('mine:'+RARE,1);advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one();assert row.state=='paused' and row.remaining==1
        assert 'Harvesting Lv.3' in row.result
        p=db.query(m.Player).one();p.mining_xp=12;db.commit()
    advance()
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).one().state=='completed'

def test_discord_mine_dispatch_and_queue_options():
    text=m._discord_call_internal('mine','u','Citizen',{},'test')
    assert 'CHOOSE AN ORE' in text
    text=m._discord_call_internal('mine','u','Citizen',{'ore':ORE,'action':'mine','count':2},'test')
    assert 'TASK QUEUE' in text
    assert 'Count' in m._discord_call_internal('queue','u','Citizen',{'action':'start','task':'mine:'+ORE,'count':11},'test')


def test_queue_and_ore_autocomplete():
    for command,option in [('queue','task'),('mine','ore')]:
        result=m._discord_autocomplete({'data':{'name':command,'options':[{'name':option,'focused':True,'value':'Hematite'}]},'member':{'user':{'id':'u'}}})
        assert result['data']['choices']
        assert any(ORE in row['value'] for row in result['data']['choices'])


def test_linking_preserves_one_queue_and_keeps_completed_work():
    enqueue(count=3);advance()
    seed('t','twitch')
    m.queued_tasks('test','t',action='start',task='work:harvest',count=2)
    with m.SessionLocal() as db:
        m.merge_accounts(db,'test','discord:u','t');db.commit()
        rows=db.query(q.TaskQueue).all();assert len(rows)==1
        assert rows[0].canonical_uid=='t' and rows[0].task=='work:harvest'
        assert 'other account' in rows[0].result
        assert db.query(m.Player).one().ore==201


def test_worker_starts_and_stops_with_app(monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    enqueue(count=1);due();done=threading.Event();original=q.tick
    def tick(module):original(module);done.set()
    monkeypatch.setattr(q,'tick',tick)
    with TestClient(m.app):assert done.wait(5)
    with m.SessionLocal() as db:assert db.query(q.TaskQueue).one().state=='completed'


def test_twitch_status_retains_needs_forecast_within_limit():
    enqueue(count=10)
    text=m.queued_tasks('test','u',provider='discord').body.decode()
    assert '38 Energy' in text and '29 Nutrition' in text
    text=m.queued_tasks('test','u',provider='discord').body.decode()
    assert 'Only one task type' in text
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();db.add(m.Identity(channel_id='test',provider='twitch',provider_uid='linked',canonical_uid=p.twitch_uid));db.commit()
    text=m.queued_tasks('test','linked').body.decode()
    assert len(text.encode())<=380
    assert 'Energy 38' in text and 'Nutrition 29' in text and 'Social 20' in text


def test_empty_twitch_count_defaults_to_one_and_invalid_count_is_clear():
    r=client.get('/api/v1/mining',params={'channel':'test','uid':'u','action':'mine','ore':ORE,'count':''})
    assert r.status_code==200 and 'RUNNING' in r.text
    r=client.get('/api/v1/queue',params={'channel':'test','uid':'u','action':'start','task':'work:harvest','count':'two'})
    assert r.status_code==200 and 'whole number' in r.text


def test_twitch_task_discovery_and_requirements():
    r=client.get('/api/v1/queue-tasks',params={'query':'Hematite'})
    assert 'mine:'+ORE in r.text
    r=client.get('/api/v1/mining',params={'channel':'test','uid':'u','ore':RARE})
    assert 'Harvesting level 3' in r.text and 'three successful prospecting steps' in r.text

@pytest.mark.parametrize('key',sorted(s.GATHER))
def test_every_gatherable_has_exact_queue_totals(key):
    count=6 if key in m.crafting_progression.RARE else 3
    enqueue(('mine:' if key in q.ores() else 'gather:')+key,count)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12
        initial=m.material_amount(db,p,key);db.commit()
    for _ in range(count):advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        totals=db.query(q.QueueTotals).one()
        expected=2 if key in m.crafting_progression.RARE else count*s.GATHER[key]['amount']
        assert m.material_amount(db,p,key)-initial==expected
        assert json.loads(totals.gained)=={key:expected}
        assert totals.failed==0
        assert totals.succeeded==(2 if key in m.crafting_progression.RARE else count)
        assert totals.progress==(4 if key in m.crafting_progression.RARE else 0)
        assert f'{s.item_label(key)} ×{expected}' in q.status(m,db,p,row)


def test_mixed_failures_rewards_and_repeated_view(monkeypatch):
    enqueue('work:harvest',10)
    for i in range(10):
        monkeypatch.setattr(m.random,'random',lambda i=i:0.99 if i%2 else 0.5)
        advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one();totals=db.query(q.QueueTotals).one()
        assert (totals.succeeded,totals.failed,totals.progress)==(5,5,0)
        assert p.crops==110
        assert json.loads(totals.gained).get('crops')==10
        for _ in range(2):
            text=q.status(m,db,p,row)
            assert 'Succeeded: 5; failed: 5.' in text and 'Crop ×10' in text
        assert p.crops==110


def test_crafting_totals_spending_pause_and_restart():
    enqueue('make:component',3)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.ore=2;db.commit()
    advance();advance();advance()
    with m.SessionLocal() as db:
        row=db.query(q.TaskQueue).one();totals=db.query(q.QueueTotals).one()
        assert row.state=='paused' and row.remaining==1
        assert (totals.succeeded,totals.failed)==(2,0)
        assert json.loads(totals.gained)=={'components':2}
        assert json.loads(totals.used)=={ORE:2}
    q.control(m,'test','u','Citizen','discord','cancel')
    q.control(m,'test','u','Citizen','discord','start','mine:'+ORE,1)
    advance()
    with m.SessionLocal() as db:
        totals=db.query(q.QueueTotals).one()
        assert totals.succeeded==1 and json.loads(totals.gained)=={ORE:1}


def test_old_queue_history_is_not_invented():
    enqueue(count=3);advance()
    with m.SessionLocal() as db:
        db.query(q.QueueTotals).delete();db.commit()
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        text=q.status(m,db,p,row)
        assert 'Earlier attempts without recorded totals: 1' in text
        assert 'Succeeded: 1; failed: 0.' in text
        assert p.ore==102


def test_crash_rolls_back_summary_too(monkeypatch):
    enqueue();due()
    def broken(*args):raise RuntimeError('crash before commit')
    monkeypatch.setattr(q,'specification',broken)
    with pytest.raises(RuntimeError):q.run_one(m,'test','discord:u')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();totals=db.query(q.QueueTotals).one()
        assert p.ore==100 and totals.succeeded==0 and totals.gained=='{}'

@pytest.mark.parametrize('rid',[k for k,r in s.RECIPES.items() if r['inputs'] and any(v>1 for v in r['outputs'].values())])
def test_multi_output_recipe_queue_uses_actual_batch_yields(rid):
    from app import competencies
    cp=m.crafting_progression;r=s.RECIPES[rid]
    enqueue('make:'+rid,2)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        db.add(m.CraftLedger(channel_id='test',canonical_uid=p.twitch_uid,recipe='component',qty=250,best_quality=''))
        for tag in cp.tags(rid):m.material_change(db,p,cp.permit_key(tag),1)
        for field in competencies.FIELDS.values():setattr(p,field,10000)
        req=r['requirement'].get('Skill','SK_CRAFTING')
        _,branch=s.SKILLS[req]
        if branch:m.gain_branch(db,p,branch,10000)
        for key,n in r['inputs'].items():m.material_change(db,p,key,n*2)
        db.commit();before={key:m.material_amount(db,p,key) for key in r['outputs']}
    advance();advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one();totals=db.query(q.QueueTotals).one()
        assert row.state=='completed',row.result
        assert totals.succeeded==2
        for key,n in r['outputs'].items():
            assert m.material_amount(db,p,key)-before[key]==n*2
            assert json.loads(totals.gained)[key]==n*2


def test_bonus_items_are_counted_from_real_inventory(monkeypatch):
    enqueue('work:harvest',1);monkeypatch.setattr(m.random,'random',lambda:0.0)
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();totals=db.query(q.QueueTotals).one()
        assert totals.succeeded==1 and p.crops==103
        assert json.loads(totals.gained)['crops']==3
