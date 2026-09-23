import os, tempfile, json, inspect, sqlite3, subprocess, sys
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

_tmp=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+str(Path(_tmp.name)/'game.db')
os.environ['AUTO_EVENTS_ENABLED']='false'
from app import main as m
from app.needs import decay, productivity
from app.settlement import produce, pressures
from app.seedlings import priority
from app.competencies import practice_gain
client=TestClient(m.app)

@pytest.fixture(autouse=True)
def reset():
    m.Base.metadata.drop_all(m.engine);m.Base.metadata.create_all(m.engine)
    m.migrate_schema()

def seed(uid='u',provider='twitch',name='Kamex'):
    with m.SessionLocal() as db:
        _,p=m.player(db,'test',provider,uid,name)
        p.sc=10000;p.crops=p.ore=p.components=p.cargo=p.rare_ore=100
        life=m.life_state(db,p)
        for k in ('energy','nutrition','comfort','social','morale'):setattr(life,k,100)
        db.commit()
    return uid

def test_legacy_route_contract():
    expected=json.loads((Path(__file__).parent/'legacy_routes.json').read_text())
    routes={r.path:r for r in m.app.routes}
    for path,(method,args) in expected.items():
        assert path in routes and method.upper() in routes[path].methods
        assert list(inspect.signature(routes[path].endpoint).parameters)==args

@pytest.mark.parametrize('hours,expected',[(3,0),(4,1),(9,2),(10000,6)])
def test_decay_capped_and_idempotent(hours,expected):
    current=m.now();row=SimpleNamespace(**{k:80 for k in ('energy','nutrition','social','comfort','morale')},last_decay_at=current-timedelta(hours=hours))
    decay(row,current)
    assert row.energy==80-expected and row.comfort==80-expected*2
    before=row.comfort;decay(row,current);assert row.comfort==before

def test_needs_reduce_real_output():
    good=SimpleNamespace(energy=80,nutrition=80,comfort=80,social=80,morale=80)
    low=SimpleNamespace(energy=80,nutrition=80,comfort=5,social=80,morale=5)
    def run(life):
        row=SimpleNamespace(water=10);s=SimpleNamespace(food=0)
        produce(row,s,'harvest',productivity(life));return s.food
    assert run(low)<run(good)
    assert practice_gain(1,False,productivity(low),False)<practice_gain(1,True,productivity(good),True)

@pytest.mark.parametrize('action',list(m.ACTION_SKILLS)+['eat','sleep'])
def test_all_actions_success_paths(action,monkeypatch):
    seed(provider='discord');monkeypatch.setattr(m.random,'random',lambda:0.0)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        db.add(m.Business(channel_id='test',canonical_uid=p.twitch_uid,name='Test Business'))
        m.item_add(db,'test',p.twitch_uid,'sensor',1)
        db.commit()
    r=client.get('/api/v1/action/'+action,params=dict(channel='test',uid='u',provider='discord'))
    assert r.status_code==200,r.text
    assert 'TASK COMPLETE' in r.text,r.text
    assert 'Needs:' in r.text or action=='sleep'

@pytest.mark.parametrize('provider',['twitch','discord'])
def test_levelup_visible_and_persistent(provider,monkeypatch):
    seed(provider=provider);monkeypatch.setattr(m.random,'random',lambda:0)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.farm_xp=9;p.job='farmer';db.commit()
    r=client.get('/api/v1/action/harvest',params=dict(channel='test',uid='u',provider=provider))
    assert 'LEVEL UP' in r.text and '1 → Lv. 2' in r.text
    if provider=='twitch':assert len(r.text)<=500
    status=client.get('/api/v1/profile',params=dict(channel='test',uid='u',provider=provider))
    assert 'LEVEL UP' in status.text
    if provider=='discord':
        payload=m._discord_json_message(r.text,message_type='agriculture')
        assert 'LEVEL UP' in json.dumps(payload)

def test_failed_action_no_production(monkeypatch):
    seed(provider='discord');monkeypatch.setattr(m.random,'random',lambda:0.999)
    with m.SessionLocal() as db:before=db.query(m.Player).one().farm_xp
    r=client.get('/api/v1/action/harvest',params=dict(channel='test',uid='u',provider='discord'))
    assert 'TASK FAILED' in r.text and 'Needs:' in r.text
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().farm_xp==before
        assert db.get(m.SettlementState,'test').water==20

def test_blocked_action_preserves_inputs():
    seed(provider='discord')
    with m.SessionLocal() as db:
        db.query(m.LifeState).one().energy=5;db.commit()
    r=client.get('/api/v1/action/craft',params=dict(channel='test',uid='u',provider='discord'))
    assert 'BLOCKED' in r.text
    with m.SessionLocal() as db:
        assert db.query(m.Player).one().ore==100
        assert db.query(m.Cooldown).count()==0

def test_crafting_levelup_and_inputs():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.fabrication_xp=9;p.job='technician';db.commit()
    r=client.get('/api/v1/make',params=dict(channel='test',uid='u',recipe='component',provider='discord'))
    assert r.status_code==200 and 'LEVEL UP' in r.text,r.text
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.ore==99 and p.components==101

def test_mentor_notifies_target():
    seed('u',name='Mentor');seed('v',name='Learner')
    with m.SessionLocal() as db:
        p=db.query(m.Player).filter_by(twitch_uid='v').one()
        for field in ('farm_xp','mining_xp','fabrication_xp','research_xp','delivery_xp','explore_xp','commerce_xp'):setattr(p,field,9)
        db.commit()
    r=m.mentor('test','u','Mentor','Learner','twitch')
    assert 'LEVEL UP' in r.body.decode()
    assert 'LEVEL UP' in m.profile('test','v','Learner','twitch').body.decode()

def test_supply_chain_and_shortages():
    with m.SessionLocal() as db:
        s=m.society(db,'test');row=m.colony_state(db,'test')
        produce(row,s,'work');assert row.components==0
        produce(row,s,'mine');produce(row,s,'work');assert row.components==2 and row.ore==1
        produce(row,s,'repair');assert row.infrastructure==2 and row.components==1
        row.water=0;s.population=10
        assert 'water shortage' in pressures(row,s)

def test_routine_no_rewards_on_poll_and_auth():
    seed()
    for _ in range(3):assert client.get('/api/v1/routine',params=dict(channel='test',uid='u')).status_code==200
    with m.SessionLocal() as db:assert db.query(m.Player).one().actions==0
    assert client.post('/api/v1/admin/routine/step',params=dict(channel='test',uid='u')).status_code==403
    life=SimpleNamespace(nutrition=0,energy=0,comfort=0,morale=0,social=0)
    assert priority(life,'farmer')[0]=='eat'
    life.nutrition=100;assert priority(life,'farmer')[0]=='sleep'

def test_account_merge_preserves_new_state_and_duplicate_relationships():
    seed('u');seed('v');seed('third')
    with m.SessionLocal() as db:
        for uid in ('u','v'):
            p=db.query(m.Player).filter_by(twitch_uid=uid).one()
            st=m.colony_seedling(db,p);st.practice='{"cultivation":0.4}'
            m.relationship_add(db,'test',uid,'third',10)
        db.commit();m.merge_accounts(db,'test','v','u')
        assert db.query(m.Player).count()==2
        assert json.loads(db.get(m.SeedlingState,('test','u')).practice)['cultivation']==.8
        rel=db.query(m.LifeRelationship).one();assert rel.familiarity==20
        assert db.get(m.SeedlingState,('test','v')) is None

def test_incident_failure_impacts_shared_state():
    with m.SessionLocal() as db:
        s=m.society(db,'test');w=m.world(db,'test');m.start_event(db,w,'water')
        w.event_ends=m.now()-timedelta(seconds=1);db.commit()
        before=m.colony_state(db,'test').water
        assert 'FAILED' in m.resolve_expired_event(db,s,w)
        assert m.colony_state(db,'test').water<before
        assert db.query(m.EventHistory).count()==1

def test_legacy_save_migration_twice(tmp_path):
    path=tmp_path/'legacy.db';con=sqlite3.connect(path)
    con.executescript((Path(__file__).parent/'legacy_schema.sql').read_text())
    # Old row with every non-null column populated; balances must survive startup.
    columns=con.execute('PRAGMA table_info(players)').fetchall()
    values={row[1]:0 for row in columns}
    values.update(id=1,channel_id='old',twitch_uid='original',display_name='Veteran',job='farmer',sc=1234,farm_xp=97,created_at='2026-01-01 00:00:00',last_seen='2026-01-01 00:00:00',last_job_change=None)
    con.execute('INSERT INTO players ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',list(values.values()));con.commit();con.close()
    code='from app import main as m; m.migrate_schema(); m.migrate_schema(); s=m.SessionLocal(); p=s.query(m.Player).one(); assert (p.sc,p.farm_xp,p.twitch_uid)==(1234,97,"original"); assert s.query(m.SimulationVersion).count()==1'
    subprocess.run([sys.executable,'-c',code],env=os.environ|{'DATABASE_URL':'sqlite:///'+str(path)},check=True,capture_output=True)

@pytest.mark.parametrize('command',list(m.DISCORD_OPTION_SCHEMA))
def test_discord_commands_dispatch(command):
    seed('u',provider='discord')
    text=m._discord_call_internal(command,'u','Kamex',{},'test-interaction')
    assert isinstance(text,str) and text

@pytest.mark.parametrize('path',['/api/v1/overlay','/overlay','/obs/society','/api/v1/society','/api/v1/world','/api/v1/guide'])
def test_overlay_and_status_contracts(path):
    seed()
    r=client.get(path,params=dict(channel='test',uid='u',provider='twitch'))
    assert r.status_code==200
    if path=='/api/v1/overlay':assert isinstance(r.json(),dict)

def test_low_comfort_has_success_penalty_and_morale_cost():
    seed()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();life=m.life_state(db,p)
        high=m.life_modifiers(db,p,'extraction')[0]
        life.comfort=5
        low,notes,_=m.life_modifiers(db,p,'extraction')
        assert low<high and any('Comfort' in n for n in notes)
        old=life.morale;m.spend_life_for_action(life,'mine');assert life.morale<old

def test_social_cooperation_fades_without_erasing_relationship():
    seed();seed('friend',name='Friend')
    with m.SessionLocal() as db:
        rel=m.relationship_add(db,'test','u','friend',100)
        memory=m.relationship_memory(db,'test','u','friend','Walk')
        memory.last_at=m.now()-timedelta(days=70);db.commit()
        assert m.effective_relationship(db,rel)==50 and rel.familiarity==100

def test_sleep_fully_restores_energy_and_comfort():
    seed()
    with m.SessionLocal() as db:
        life=db.query(m.LifeState).one();life.energy=0;life.comfort=0;db.commit()
    m.action('sleep','test','u')
    with m.SessionLocal() as db:
        life=db.query(m.LifeState).one();assert life.energy==100 and life.comfort==100

def test_emergency_meal_remains_recoverable():
    seed()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.crops=0;m.life_state(db,p).nutrition=0;db.commit()
    r=m.action('eat','test','u')
    assert 'emergency' in r.body.decode().lower()
    with m.SessionLocal() as db:assert db.query(m.LifeState).one().nutrition>=20

def test_discord_option_contract_unchanged():
    assert m.DISCORD_OPTION_SCHEMA==json.loads((Path(__file__).parent/'legacy_discord_options.json').read_text())

def test_colony_levelup_and_action_log(monkeypatch):
    seed();monkeypatch.setattr(m.random,'random',lambda:0)
    with m.SessionLocal() as db:
        s=m.society(db,'test');threshold=m.SOCIETY_TIERS[1][1]
        for k in ('food','materials','development','knowledge','treasury','reputation'):setattr(s,k,threshold)
        s.food=threshold-1;db.commit()
    r=m.action('harvest','test','u')
    assert 'LEVEL UP: Colony growth' in r.body.decode()
    with m.SessionLocal() as db:assert 'LEVEL UP: Colony growth' in db.query(m.ActionLog).one().response

def test_admin_routine_step_obeys_cooldown(monkeypatch):
    seed();monkeypatch.setattr(m,'ADMIN_KEY','local-test-key')
    m.job('test','u',job='farmer')
    monkeypatch.setattr(m.random,'random',lambda:0)
    params=dict(channel='test',uid='u',key='local-test-key')
    assert client.post('/api/v1/admin/routine/step',params=params).status_code==200
    second=client.post('/api/v1/admin/routine/step',params=params)
    assert 'ready in' in second.text
    with m.SessionLocal() as db:assert db.query(m.Player).one().actions==1

def test_multiple_hobby_rank_jump_notified():
    seed()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();h=m.hobby_row(db,p,'games');h.points=14;db.commit()
    r=m.hobby('test','u',hobby='games')
    assert 'LEVEL UP' in r.body.decode()
