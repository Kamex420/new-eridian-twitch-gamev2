"""The /menu button tree: every area opens, every button fits Discord, actions run once."""
import json
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, press, controls, find, W, LUMBER
from app import menu, ui, seed_content as s


def open_area(area):
    return press(ui.cid('111', 'mn', area))['data']


@pytest.mark.parametrize('area', list(menu.AREAS))
def test_every_area_opens_within_discord_limits(area):
    citizen()
    data = open_area(area)
    assert data['embeds'][0].get('title')
    rows = data['components']
    assert 1 <= len(rows) <= 5
    for component in controls(data):
        assert len(component['custom_id']) <= 100 and len(component.get('label', '')) <= 80
    assert sum(len(r['components']) for r in rows) <= 25


def test_every_leaf_points_at_a_real_command():
    for key, item in menu.LEAVES.items():
        assert key in menu.PARENT, key
        if item['kind'] == 'nav':
            continue
        command, options = m.discord_legacy_route(item['cmd'], item['opts'])
        assert command in m.DISCORD_OPTION_SCHEMA or command in {'recover', 'menu', 'inbox', 'eatfull', 'undo', 'catalog', 'queuedetails', 'guidepanels', 'menupanel'}, key
        names = {o['name'] for o in m.DISCORD_OPTION_SCHEMA.get(command, [])}
        assert set(options) <= names, key


@pytest.mark.parametrize('key', [k for k, v in menu.LEAVES.items() if v['kind'] == 'view'])
def test_every_view_button_shows_a_card(key):
    citizen()
    data = press(ui.cid('111', 'mv', key))['data']
    assert data['embeds'] and len(data['components']) <= 5


def lower_needs(**values):
    with m.SessionLocal() as db:
        life = m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        for k, v in values.items():
            setattr(life, k, v)
        db.commit()


def test_action_buttons_work_once_and_offer_the_area_again():
    citizen(); lower_needs(energy=50, comfort=50)
    relax = find(open_area('life'), 'Relax')['custom_id']
    first = press(relax)['data']
    assert 'Relaxed' in json.dumps(first, ensure_ascii=False)
    assert 'Relax' in [c.get('label') for c in controls(first)]      # the area's buttons come back
    assert 'already used' in press(relax)['data']['content']


def test_choice_lists_run_or_confirm():
    citizen(lumber=10)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.material_change(db, p, s.key('Pumpkin'), 2); db.commit()
    lower_needs(nutrition=40)
    eat = press(ui.cid('111', 'mk', 'eat'))['data']
    select = eat['components'][0]['components'][0]
    result = press(select['custom_id'], values=[s.key('Pumpkin')])['data']
    assert 'Meal' in json.dumps(result, ensure_ascii=False)
    sell = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    assert 'Nothing happens until you press Confirm' in json.dumps(sell, ensure_ascii=False)
    with m.SessionLocal() as db:
        assert s.stock(m, db, m.player(db, W, 'discord', '111', 'Kam')[1]).get(LUMBER) == 10
    confirm = find(sell, 'Confirm')['custom_id']
    press(confirm)
    with m.SessionLocal() as db:
        assert s.stock(m, db, m.player(db, W, 'discord', '111', 'Kam')[1]).get(LUMBER, 0) == 0


def test_social_pick_offers_activities_with_that_citizen():
    citizen('111'); citizen('222')
    friend = press(ui.cid('111', 'mk', 'friend'))['data']
    value = friend['components'][0]['components'][0]['options'][0]['value']
    data = press(ui.cid('111', 'mp', 'friend'), values=[value])['data']
    labels = [c.get('label') for c in controls(data)]
    assert {'Say hi', 'Hang out', 'Mentor'} <= set(labels)


def test_menu_slash_command_and_reply_buttons():
    citizen()
    text = m._discord_call_internal('menu', '111', 'Kam', {}, 'i')
    panel = ui.slash_panel(m, 'menu', '111', 'Kam', {}, text)
    assert {'Life & Recovery', 'Work', 'Craft', 'Help'} <= {c.get('label') for c in controls(panel)}
    row = menu.after_command(m, 'relax', {}, '111')
    assert [c['label'] for c in row['components']] == ['Again', 'Life & Recovery', 'Menu']
    assert [c['label'] for c in menu.after_command(m, 'inventory', {}, '111')['components']] == ['Bag', 'Menu']
