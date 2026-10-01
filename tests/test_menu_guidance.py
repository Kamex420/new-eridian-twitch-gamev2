"""The goal walks you through every step with a button for each; Home opens with the next step;
every screen shows where it is and ends with Menu."""
from test_colony import m, reset
from test_workbench_ui import citizen, press, W
from test_layout_v2 import assert_valid, sections
from app import ui, menu, extras, layout_v2 as v2, workbench as wb


def player_sc(sc):
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        p.sc = sc
        db.commit()


def first(code=None, test=None):
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        ctx = wb.Context(m, db, p)
        return next(e for e in wb.index(m) if (code is None or ctx.status(e).code == code) and (test is None or test(ctx, e)))


def beside(data):
    return {s['accessory']['label']: s for s in sections(v2.convert(data))}


def test_a_goal_that_needs_a_workstation_walks_through_making_its_machine():
    citizen(lumber=0)
    e = first('station')
    view = press(ui.cid('111', 'gs', e.id))['data']
    assert assert_valid(v2.convert(view))
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        key, machine = extras._machine(m, wb.Context(m, db, p), e)
        steps = extras.walkthrough(m, db, p)[1]
    names = [st['name'] for st in steps]
    assert f'Craft {machine.name}' in names and not any(n.startswith('Unlock') for n in names)    # made, not bought
    assert 'the machine for' in steps[names.index(f'Craft {machine.name}')]['detail']
    assert names.index(f'Craft {machine.name}') < names.index(f'Craft {e.name}')                   # the machine before the goal
    assert 'made in the steps below' in v2.text_of(view)
    # Once you own the machine, its step is gone and the goal can use the workstation.
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        m.material_change(db, p, key, 1)
        db.commit()
        names = [st['name'] for st in extras.walkthrough(m, db, p)[1]]
    assert f'Craft {machine.name}' not in names


def test_a_step_done_from_the_goal_comes_back_to_it():
    citizen(lumber=0)
    view = press(ui.cid('111', 'gs', first('station').id))['data']
    gather = next(s['accessory'] for s in sections(v2.convert(view)) if s['accessory']['label'] in {'Gather', 'Mine'})
    done = ui.run_ticket(m, '111', 'Kam', ui.claim(m, '111', gather['custom_id'].split('|')[3])[0])
    ids = [c.get('custom_id') for c in v2.controls(done)]
    assert ui.cid('111', 'gv') in ids and ui.cid('111', 'mn', 'home') in ids          # back to the goal, and the menu


def test_no_goal_asks_you_to_unlock_a_workstation():
    citizen(lumber=0)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        ctx = wb.Context(m, db, p)
        locked = [e for e in wb.index(m) if ctx.status(e).code == 'station'][:25]
    for e in locked:
        press(ui.cid('111', 'gs', e.id))
        with m.SessionLocal() as db:
            p = db.query(m.Player).one()
            assert not [st for st in extras.walkthrough(m, db, p)[1] if st['label'] in {'Unlock', 'Earn SC'}], e.name


def test_skill_and_tier_locks_lead_to_training_and_crafting():
    citizen(lumber=0)
    e = first(test=lambda ctx, e: e.kind == 'seed' and ctx.level(e.skill_key) < e.level)
    press(ui.cid('111', 'gs', e.id))
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        steps = extras.walkthrough(m, db, p)[1]
    train = next(st for st in steps if st['label'] == 'Train')
    assert train['view'][:2] == ('mp', 'trainskill') and train['name'].startswith('Reach ')
    tasks = press(ui.cid('111', *train['view']))
    assert tasks['type'] == 7 and any(c.get('label') == 'Start' for c in v2.controls(v2.convert(tasks['data'])))
    tier = [st for st in steps if st['name'].startswith('Reach personal Tier')]
    assert all(st['view'] == ('wc', 'ready', 1, '') for st in tier)                       # a tier: craft anything ready


def test_training_hubs_are_real_training_skills():
    with m.SessionLocal() as db:
        valid = {v for _, v in menu.choices(m, db, None, 'field:training:skill', '1')}
    assert set(extras.TRAINING_HUB.values()) <= valid


def test_home_opens_with_one_next_step():
    citizen()
    home = v2.convert(press(ui.cid('111', 'mn', 'home'))['data'])
    top = sections(home)[0]
    assert top['components'][0]['content'].startswith('➡️ **Next step** — ') and top['accessory']['style'] in {1, 3}
    # With the first steps done and a goal set, the next step is the goal's.
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        m.onboarding.row(m, db, p).finished = True
        db.commit()
    press(ui.cid('111', 'gs', first('station').id))
    top = sections(v2.convert(press(ui.cid('111', 'mn', 'home'))['data']))[0]
    assert 'for your goal' in top['components'][0]['content']


def test_every_screen_shows_where_it_is_and_ends_with_menu():
    citizen()
    farming = press(ui.cid('111', 'mn', 'farming'))['data']
    assert farming['embeds'][0]['author']['name'] == '🏠 Menu › ⛏️ Work › 🌾 Farming'
    assert v2.convert(farming)['components'][0]['components'][0]['content'].startswith('-# 🏠 Menu › ⛏️ Work › 🌾 Farming')
    for custom_id in (ui.cid('111', 'wc', 'parts', 1, ''), ui.cid('111', 'wh'), ui.cid('111', 'qv'), ui.cid('111', 'st')):
        data = press(custom_id)['data']
        last = [r for r in data['components'] if r.get('components')][-1]['components'][-1]
        assert last['custom_id'] == ui.cid('111', 'mn', 'home'), custom_id
