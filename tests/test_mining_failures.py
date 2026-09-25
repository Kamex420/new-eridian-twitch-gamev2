"""Mining failures award the existing Stone Dust item without awarding ore."""
import json
import pytest
from test_colony import m,reset,seed
from test_task_queue import enqueue,advance,ORE,RARE
from app import task_queue as q, crafting_progression as cp, seed_content as s

@pytest.mark.parametrize('key',sorted(q.ores()))
def test_all_mined_resources_fail_to_one_stone_dust(key,monkeypatch):
    enqueue('mine:'+key,1)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12;initial=m.material_amount(db,p,key);db.commit()
    monkeypatch.setattr(m.random,'random',lambda:0.99);advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();totals=db.query(q.QueueTotals).one();row=db.query(q.TaskQueue).one()
        assert m.material_amount(db,p,key)==initial
        assert m.material_amount(db,p,cp.STONE_DUST)==1
        assert (totals.succeeded,totals.failed,totals.progress)==(0,1,0)
        assert json.loads(totals.gained)=={cp.STONE_DUST:1}
        assert p.actions==1 and p.successes==0
        assert m.life_state(db,p).energy==100-(3 if key in cp.RARE else 2)
        assert 'Final success chance' in row.result
        assert 'Stone Dust ×1' in q.status(m,db,p,row)
        notice=db.query(q.queue_notifications.Notice).one()
        assert 'failed: 1' in notice.content and 'Stone Dust ×1' in notice.content


def test_rare_failures_preserve_successful_prospecting_steps(monkeypatch):
    enqueue('mine:'+RARE,4)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12;db.commit()
    for roll,progress in [(0.0,1),(0.99,1),(0.0,2),(0.0,0)]:
        monkeypatch.setattr(m.random,'random',lambda roll=roll:roll);advance()
        with m.SessionLocal() as db:
            p=db.query(m.Player).one();assert m.material_amount(db,p,'prospect:'+RARE)==progress
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();totals=db.query(q.QueueTotals).one()
        assert p.rare_ore==101 and m.material_amount(db,p,cp.STONE_DUST)==1
        assert (totals.succeeded,totals.failed,totals.progress)==(1,1,2)


def test_blocked_mining_never_grants_failure_reward(monkeypatch):
    enqueue(count=1);monkeypatch.setattr(m.random,'random',lambda:0.99)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.life_state(db,p).energy=19;db.commit()
    advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert p.actions==0 and m.material_amount(db,p,cp.STONE_DUST)==0
        assert db.query(q.TaskQueue).one().remaining==1


@pytest.mark.parametrize('action',['mine','scavenge','train_ore_mining'])
def test_legacy_mining_paths_also_give_dust(action,monkeypatch):
    seed(provider='discord');monkeypatch.setattr(m.random,'random',lambda:0.99)
    text=m.action(action,'test','u',provider='discord').body.decode()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert p.ore==100 and p.actions==1
        assert m.material_amount(db,p,cp.STONE_DUST)==1,text
    assert 'No task rewards were earned' not in text and 'Stone Dust' in text


@pytest.mark.parametrize('rid',[k for k,r in s.RECIPES.items() if any(i in q.ores() for i in r['outputs'])])
def test_machine_extraction_cannot_bypass_mining_failure(rid,monkeypatch):
    enqueue('make:'+rid,1)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=1000
        db.add(m.CraftLedger(channel_id='test',canonical_uid=p.twitch_uid,recipe='component',qty=250,best_quality=''))
        for tag in cp.tags(rid):m.material_change(db,p,cp.permit_key(tag),1)
        req=s.RECIPES[rid]['requirement'].get('Skill','SK_CRAFTING')
        from app.competencies import FIELDS
        main,branch=s.SKILLS[req];setattr(p,FIELDS[main],10000)
        if branch:m.gain_branch(db,p,branch,10000)
        db.commit()
    monkeypatch.setattr(m.random,'random',lambda:0.99);advance()
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();row=db.query(q.TaskQueue).one()
        assert row.state=='completed',row.result
        assert m.material_amount(db,p,cp.STONE_DUST)==1
        assert db.query(q.QueueTotals).one().failed==1


def test_mining_chance_uses_intrinsic_and_situational_modifiers(monkeypatch):
    seed(provider='discord')
    monkeypatch.setattr(m,'success_chance',lambda *args:0.68)
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        monkeypatch.setattr(m,'life_modifiers',lambda *args:(-0.10,['Low needs'],m.life_state(db,p)))
        monkeypatch.setattr(m,'world_rule_bundle',lambda *args:(None,None,0.02,['World +2%']))
        monkeypatch.setattr(m,'determination_bonus',lambda *args:0.03)
        monkeypatch.setattr(m.random,'random',lambda:0.62)
        assert cp.mining_roll(m,db,p,'discord')[0]
        monkeypatch.setattr(m.random,'random',lambda:0.64)
        assert not cp.mining_roll(m,db,p,'discord')[0]
