"""Every task gives XP, and sometimes an item from the same line of work.
Life and social actions (eat, sleep, relax, hangouts…) never find anything."""
import pytest
from test_colony import m, reset, seed, client, ready_for
from app import practice, seed_skills

NAMES = sorted({n for pools in (practice.BRANCH, practice.SKILL) for items in pools.values() for n in items}, key=len, reverse=True)


@pytest.fixture
def finds(monkeypatch):
    monkeypatch.setattr(practice, 'ENABLED', True)
    monkeypatch.setattr(practice, 'CHANCE', 1.0)       # every success finds something, so each test sees one


def found_in(text):
    """The item a reply says was found, or None."""
    at = text.find('🎁 Lucky find (')
    if at < 0:
        return None
    rest = text[text.index('): +1 ', at) + 6:]
    return next((n for n in NAMES if rest.startswith(n)), rest)


def call(path, **params):
    return client.get(path, params=dict(channel='test', uid='u', provider='discord', **params)).text


@pytest.mark.parametrize('action', ['harvest', 'water', 'mine', 'rare', 'craft', 'repair', 'research', 'cargo', 'explore',
                                    'market', 'train_wood_harvesting', 'train_chemistry', 'train_pottery',
                                    'train_pharmacy', 'train_advanced_cooking', 'train_fire_suppression'])
def test_a_task_can_turn_up_an_item_from_its_own_line_of_work(action, finds, monkeypatch):
    monkeypatch.setattr(m.random, 'random', lambda: 0.0)
    ready_for(action)
    text = call('/api/v1/action/' + action)
    name = found_in(text)
    branch = m.SEED_TASKS[action]['branch'] if action in m.SEED_TASKS else m.LEGACY_BRANCH.get(action)
    assert name in practice.pool(m.ACTION_SKILLS[action], branch), text
    assert f'🎁 Lucky find ({m.SKILL_LABELS[m.ACTION_SKILLS[action]]}): +1 {name}' in text


def test_the_find_lands_in_the_bag(finds, monkeypatch):
    monkeypatch.setattr(m.random, 'random', lambda: 0.0)
    ready_for('train_chemistry')
    key = practice.key(m, 'Salt')
    monkeypatch.setattr(m.random, 'choice', lambda items: 'Salt' if 'Salt' in items else items[0])
    with m.SessionLocal() as db:
        before = m.material_amount(db, db.query(m.Player).one(), key)
    assert found_in(call('/api/v1/action/train_chemistry')) == 'Salt'
    with m.SessionLocal() as db:
        assert m.material_amount(db, db.query(m.Player).one(), key) == before + 1


def test_finds_are_occasional(monkeypatch):
    monkeypatch.setattr(practice, 'ENABLED', True)
    ready_for('harvest')                                                  # every roll is 0.5: the task works, the 15% find does not
    text = call('/api/v1/action/harvest')
    assert 'TASK COMPLETE' in text and found_in(text) is None


def test_failed_tasks_and_life_and_social_actions_never_find_anything(finds, monkeypatch):
    monkeypatch.setattr(m.random, 'random', lambda: 0.999)
    ready_for('mine')
    text = call('/api/v1/action/mine')
    assert 'TASK FAILED' in text and found_in(text) is None
    monkeypatch.setattr(m.random, 'random', lambda: 0.0)
    for path in ('/api/v1/action/eat', '/api/v1/action/sleep', '/api/v1/relax', '/api/v1/walk', '/api/v1/games'):
        assert found_in(call(path)) is None, path


def test_gathering_crafting_and_item_work_find_things_too(finds):
    seed(provider='discord')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        clay = m.seed_content.find_item('Clay')
        text = m.seed_content.gather(m, db, p, clay, 'discord')
        assert found_in(text) in practice.pool('extraction', 'stone_quarrying'), text


def test_gear_repair_and_building_give_engineering_xp(finds):
    seed(provider='discord')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        m.add_quality_gear(db, p, next(iter(m.QUALITY_RECIPES)), 'Standard')
        gear = db.query(m.QualityGear).one()
        gear.condition, item, xp = 40, gear.item_key, p.infrastructure_xp
        db.commit()
    text = call('/api/v1/gearrepair', item=item)
    assert 'Engineering and Maintenance & Repair XP' in text and found_in(text)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert p.infrastructure_xp > xp
        build = next(k for k in m.seed_content.ACTIVE if m.seed_content.PURPOSE[k]['mode'] == 'build')
        m.material_change(db, p, build, 1)
        db.commit()
        result = m.seed_content.use(m, db, p, build, 'discord')
    assert 'Engineering XP' in result and found_in(result) in practice.pool('infrastructure', 'maintenance_repair')


def test_every_find_is_a_real_item_and_every_skill_has_some():
    for name in {n for pools in (practice.BRANCH, practice.SKILL) for items in pools.values() for n in items}:
        key = practice.key(m, name)
        assert key == 'cargo' or key in m.seed_content.ACTIVE, name
        assert m.resource_name(key) == name
    assert set(practice.SKILL) == set(seed_skills.LABELS)
    assert set(practice.BRANCH) <= {t['branch'] for t in seed_skills.TASKS.values()}
