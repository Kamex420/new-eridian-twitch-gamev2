"""Seedlings help New Eridian (autonomy.event_step, colony_step): they answer live events in any waking hour, and
on some collecting turns help the Society Directive or the society stat the colony is lowest on."""
import pytest
from test_colony import m, reset, client, seed
from test_autonomy import away, life_row, UID
from app import autonomy as a, seed_content as s


def job(name):
    client.get('/api/v1/job', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'job': name})


def start(key, goal=50):
    with m.SessionLocal() as db:
        w = m.world(db, 'test')
        m.start_event(db, w, key, 'test')
        w.event_goal = goal
        db.commit()


def progress():
    with m.SessionLocal() as db:
        return m.world(db, 'test').event_progress


def plan_now():
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        return a.work_plan(m, db, p, a.row(db, 'test', UID, create=True))


@pytest.fixture
def lean(monkeypatch):
    monkeypatch.setattr(a, 'LEAN', 1.0)          # every collecting turn helps the colony


def directive(key, complete=False):
    with m.SessionLocal() as db:
        row, _ = m.directive_for(db, 'test', m.world_clock(db, 'test')['day'])
        row.directive_key, row.complete = key, complete
        db.commit()


def test_a_seedling_answers_a_mining_boom_and_moves_it():
    seed()
    job('farmer')                                  # not its trade: the event still comes first
    start('mining')
    away()
    story = a.live_one(m, 'test', UID, force=True)
    found = life_row()
    assert found.activity.startswith('Gathering') and 'The Mining Boom is on and Harvesting work counts' in found.plan
    assert progress() == 1 and 'Mining Boom' in story


def test_events_are_answered_on_free_time_but_not_in_bed(monkeypatch):
    seed()
    start('food')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        found = a.row(db, 'test', UID, create=True)
        life = m.life_state(db, p)
        clock = m.world_clock(db, 'test')
        monkeypatch.setattr(a, 'schedule_of', lambda f: {clock['phase']: 'free'})
        step = a.plan(m, db, p, found, life, clock)
        assert step['colony'] == 'event' and step['kind'] == 'gather' and step['skill'] == 'cultivation'
        monkeypatch.setattr(a, 'schedule_of', lambda f: {clock['phase']: 'sleep'})
        life.energy = life.comfort = 100
        assert a.plan(m, db, p, found, life, clock)['kind'] == 'rest'


def test_support_work_when_no_primary_work_is_possible(monkeypatch):
    seed()
    start('machine')                                # Primary Engineering, Support Crafting
    craft = {'kind': 'train', 'task': 'x', 'skill': 'fabrication', 'doing': 'practising Nail Making'}
    monkeypatch.setattr(a, 'skill_step', lambda m_, db, p, mind, skill: None if skill == 'infrastructure' else dict(craft))
    with m.SessionLocal() as db:
        step = a.event_step(m, db, db.query(m.Player).one())
    assert step['why'] == 'The Infrastructure Breakdown is on and Crafting work counts, so I am practising Nail Making.'


def test_the_society_directive_gets_help(lean):
    seed()
    job('miner')
    directive('food_reserve')
    step = plan_now()
    assert step['colony'] == 'directive' and step['skill'] in {'cultivation', 'environmental'}
    assert step['why'].startswith("Today's Society Directive is Food Reserve")


def test_a_seedlings_gathering_counts_for_the_directive(lean):
    seed()
    directive('material_drive')
    away()
    a.live_one(m, 'test', UID, force=True)
    with m.SessionLocal() as db:
        row, _ = m.directive_for(db, 'test', m.world_clock(db, 'test')['day'])
        assert row.progress == 1


def test_once_the_directive_is_done_the_weakest_stat_gets_help(lean):
    seed()
    directive('food_reserve', complete=True)
    with m.SessionLocal() as db:
        soc = m.society(db, 'test')
        for f in a.STAT_SKILLS:
            setattr(soc, f, 50)
        soc.materials = 3
        db.commit()
    step = plan_now()
    assert step['colony'] == 'weakest' and step['skill'] in {'extraction', 'environmental'}
    assert 'lowest on Materials (3)' in step['why']


def test_most_turns_still_follow_the_job():
    seed()
    job('miner')
    directive('food_reserve')
    assert 'colony' not in plan_now()             # LEAN: only some turns lean toward the colony
    assert a.LEAN < .5


def test_goal_materials_still_come_first(lean):
    seed()
    from app import workbench as wb, extras
    campfire = next(e for e in wb.index(m) if e.name == 'Campfire')
    with m.SessionLocal() as db:
        extras.set_goal(m, db, db.query(m.Player).one(), campfire.id)
        db.commit()
    step = plan_now()
    assert step.get('goal') and 'colony' not in step


def test_every_stat_and_event_skill_has_seedling_work():
    """Each skill a Seedling might be asked for can be gathered, practised or worked as a job task."""
    natural = {s.GATHER_SKILL.get(v['branch'], 'extraction') for v in s.GATHER.values()}
    trained = {cfg['skill'] for cfg in m.SEED_TASKS.values()}
    wanted = {k for skills in a.STAT_SKILLS.values() for k in skills} | {c['primary'] for c in m.EVENTS.values()}
    assert wanted <= natural | trained | set(a.SKILL_ACT)
