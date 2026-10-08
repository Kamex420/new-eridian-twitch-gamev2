"""Everyday work builds New Eridian and wins events (main.work_counts).

Gathering, mining, Workbench crafting, item jobs, sales and Production Orders used to skip the event, the society
stats and Contribution, so a Mining Boom ended 0/16 while three Seedlings mined ore. Each success now counts by
its skill, from a button, chat, a queue or a Seedling. Only real players fill the automatic event meter."""
import pytest
from sqlalchemy import select
from test_colony import m, reset, seed
from app import seed_content as s, autonomy, task_queue

STONE = next(k for k, v in s.GATHER.items() if v['branch'] == 'stone_quarrying')
BERRY = next(k for k, v in s.GATHER.items() if v['branch'] == 'botanical_harvesting')
WATER = next(k for k, v in s.GATHER.items() if v['branch'] == 'water_collection')


def state(db):
    return m.society(db, 'test'), m.world(db, 'test')


def citizen(db):
    seed()
    return m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]


def gather(db, p, key):
    db.query(m.Cooldown).delete()
    return s.gather(db, p, key, 'twitch')


def start(db, key, goal=None):
    w = m.world(db, 'test')
    m.start_event(db, w, key, 'test')
    if goal:
        w.event_goal = goal
        db.commit()
    return w


def test_gathering_grows_the_colony_and_the_leaderboard():
    with m.SessionLocal() as db:
        p = citizen(db)
        soc, _ = state(db)
        food, materials, contribution = soc.food, soc.materials, p.contribution
        assert 'NEW ERIDIAN\n+1 Food · +1 Contribution' in gather(db, p, BERRY)
        assert '+1 Materials · +1 Contribution' in gather(db, p, STONE)
        assert '+1 Materials' in gather(db, p, WATER)
        db.refresh(soc)
        assert (soc.food, soc.materials, p.contribution) == (food + 1, materials + 2, contribution + 3)


def test_mining_and_quarrying_win_a_mining_boom():
    with m.SessionLocal() as db:
        p = citizen(db)
        w = start(db, 'mining', goal=2)
        assert 'Mining Boom: Primary response +1 (1/2)' in gather(db, p, STONE)
        treasury = m.society(db, 'test').treasury
        done = gather(db, p, STONE)
        assert 'Mining Boom COMPLETE' in done and 'Kamex 2P/0S' in done
        db.refresh(w)
        assert w.active_event is None and m.society(db, 'test').treasury > treasury


def test_wild_food_and_cooking_answer_a_food_crisis():
    with m.SessionLocal() as db:
        p = citizen(db)
        start(db, 'food', goal=50)
        assert 'Food Crisis: Primary response +1' in gather(db, p, BERRY)
        assert 'Food Crisis: Support logged 1/2' in gather(db, p, WATER)     # environmental supports


def test_a_workbench_craft_adds_development_and_answers_a_breakdown():
    with m.SessionLocal() as db:
        p = citizen(db)
        key = next(k for k in s.MACHINE_RECIPES if s.ITEMS[k]['name'] == 'Basic Workbench')
        rid = next(k for k, r in s.RECIPES.items() if key in r['outputs'])
        assert s.SKILLS[s.RECIPES[rid]['requirement'].get('Skill', 'SK_CRAFTING')][0] == 'infrastructure'
        for k, n in s.RECIPES[rid]['inputs'].items():
            m.material_change(db, p, k, n)
        start(db, 'machine', goal=50)
        development, contribution = m.society(db, 'test').development, p.contribution
        db.query(m.Cooldown).delete()
        result = s.craft(db, p, rid, 'discord')
        assert 'CRAFTING COMPLETE' in result and '+1 Development · +1 Contribution' in result
        assert 'Infrastructure Breakdown: Primary response +1' in result
        assert m.society(db, 'test').development == development + 1 and p.contribution == contribution + 1


def test_selling_counts_for_a_market_boom():
    seed()
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        m.material_change(db, p, BERRY, 5)
        start(db, 'market', goal=50)
    text = m.sell('test', 'u', 'Kamex', s.ITEMS[BERRY]['name'], 1, 'twitch').body.decode()
    assert 'sold 1' in text and 'Market Boom: Primary response +1' in text


def test_work_that_does_not_match_the_event_lists_nobody_as_a_helper():
    with m.SessionLocal() as db:
        p = citizen(db)
        w = start(db, 'delivery')
        gather(db, p, STONE)
        assert db.execute(select(m.EventContribution)).first() is None
        assert w.event_progress == 0


@pytest.fixture
def auto_events(monkeypatch):
    monkeypatch.setattr(m, 'AUTO_EVENTS_ENABLED', True)     # tests turn them off by default (test_colony)


def test_seedlings_help_events_but_never_start_one(auto_events):
    with m.SessionLocal() as db:
        p = citizen(db)
        w = start(db, 'mining', goal=50)
        token = autonomy.ACTING.set(True)
        try:
            assert 'Mining Boom: Primary response +1' in gather(db, p, STONE)
        finally:
            autonomy.ACTING.reset(token)
        m.clear_event(w)
        w.last_event_end = m.now() - m.timedelta(days=1)
        db.commit()
        token = autonomy.ACTING.set(True)
        try:
            gather(db, p, STONE)
        finally:
            autonomy.ACTING.reset(token)
        db.refresh(w)
        assert not w.activity_since_event                    # the meter waits for a real player
        gather(db, p, STONE)
        db.refresh(w)
        assert w.activity_since_event == 1


def test_queued_work_does_not_fill_the_event_meter(auto_events):
    with m.SessionLocal() as db:
        p = citizen(db)
        token = task_queue.actor_context.set(('test', p.twitch_uid))
        try:
            assert '+1 Contribution' in gather(db, p, STONE)       # still grows the colony
        finally:
            task_queue.actor_context.reset(token)
        assert not m.world(db, 'test').activity_since_event


def test_real_players_working_start_an_automatic_event(auto_events, monkeypatch):
    monkeypatch.setattr(m, 'AUTO_EVENT_ACTIONS', 2)
    with m.SessionLocal() as db:
        p = citizen(db)
        w = m.world(db, 'test')
        w.activity_window_started_at = m.now() - m.timedelta(minutes=m.AUTO_EVENT_MINUTES + 1)
        db.commit()
        gather(db, p, STONE)
        assert 'STARTED!' in gather(db, p, STONE)
        db.refresh(w)
        assert w.active_event


def test_the_handbook_says_everyday_work_counts():
    from app import knowledge
    text = ' '.join(what + ' ' + how for what, how in knowledge.CONTRIBUTION)
    assert 'gather' in text.lower() and 'craft' in text.lower()
