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


def test_a_goal_that_needs_a_workstation_has_an_unlock_button_and_comes_back():
    citizen(lumber=0)
    player_sc(500)
    e = first('station')
    view = press(ui.cid('111', 'gs', e.id))['data']
    assert assert_valid(v2.convert(view))
    steps = beside(view)
    unlock = steps['Unlock']['accessory']
    assert unlock['custom_id'].startswith('ne|111|t|') and unlock['style'] == 3          # does it once, green
    assert 'Unlock' in steps['Unlock']['components'][0]['content'] and 'SC once' in steps['Unlock']['components'][0]['content']
    done = ui.run_ticket(m, '111', 'Kam', ui.claim(m, '111', unlock['custom_id'].split('|')[3])[0])
    assert 'unlocked permanently' in v2.text_of(done)
    ids = [c.get('custom_id') for c in v2.controls(done)]
    assert ui.cid('111', 'gv') in ids and ui.cid('111', 'mn', 'home') in ids          # back to the goal, and the menu
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert not any(st['name'].startswith('Unlock') for st in extras.walkthrough(m, db, p)[1])


def test_a_step_you_cannot_afford_shows_how_to_earn_sc():
    citizen(lumber=0)
    player_sc(3)
    e = first('station')
    view = press(ui.cid('111', 'gs', e.id))['data']
    earn = beside(view)['Earn SC']
    assert earn['accessory']['custom_id'] == ui.cid('111', 'mp', 'guidegoal', '=seed_coin')
    assert 'you need' in earn['components'][0]['content']
    guide = press(earn['accessory']['custom_id'])
    assert guide['type'] == 7 and 'Guide' in v2.text_of(guide['data'])


def test_skill_and_tier_locks_lead_to_training_and_crafting():
    citizen(lumber=0)
    e = first(test=lambda ctx, e: e.kind == 'seed' and ctx.level(e.skill_key) < e.level)
    view = press(ui.cid('111', 'gs', e.id))['data']
    steps = beside(view)
    train = steps['Train']['accessory']['custom_id']
    assert '|mp|trainskill|=' in train
    tasks = press(train)
    assert tasks['type'] == 7 and any(c.get('label') == 'Start' for c in v2.controls(v2.convert(tasks['data'])))
    if 'Craft' in steps:                                                                 # a tier lock: craft anything ready
        assert steps['Craft']['accessory']['custom_id'] in {ui.cid('111', 'wc', 'ready', 1, '')} or '|t|' in steps['Craft']['accessory']['custom_id']


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
