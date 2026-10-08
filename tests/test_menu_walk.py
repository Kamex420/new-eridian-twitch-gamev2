"""Walk the whole menu as the game owner: every area and its More screen, every list, and the choices in each list
open a working screen in both Discord layouts (never "no longer available", always within Discord's limits)."""
import json
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, W, LUMBER
from test_layout_v2 import assert_valid
from app import menu, ui, layout_v2 as v2, seed_content as s

GONE = 'no longer available'


def press(custom_id, values=None, newer=False):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)},
               'message': {'flags': 64 | (v2.FLAG if newer else 0)}}
    return ui.handle_component(payload)


def walk(components):
    for c in components or []:
        yield c
        if isinstance(c.get('accessory'), dict):
            yield c['accessory']
        yield from walk(c.get('components'))


def checked(custom_id, values=None, newer=False):
    """Press a control and check the answer is a working screen Discord accepts."""
    answer = press(custom_id, values, newer)
    data = answer.get('data') or {}
    text = json.dumps(data, ensure_ascii=False)
    assert GONE not in text, (custom_id, values)
    if newer and data.get('flags', 0) & v2.FLAG:
        assert_valid(data)
    else:
        rows = data.get('components') or []
        assert len(rows) <= 5, custom_id
        ids = [c['custom_id'] for c in walk(rows) if 'custom_id' in c]
        assert len(ids) == len(set(ids)), custom_id
        assert all(len(c.get('label', '')) <= 80 for c in walk(rows)), custom_id
    return data


def select_values(data):
    menus = [c for c in walk(data.get('components')) if c.get('type') == 3]
    return [o['value'] for o in menus[0]['options'] if not str(o['value']).startswith('__page:')] if menus else []


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    citizen(lumber=40)
    citizen('222')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        p.sc, p.crops, p.cargo = 5000, 5, 2
        for name in ('Pumpkin', 'Stone', 'Iron Nails'):
            m.material_change(db, p, s.key(name), 5)
        db.commit()


@pytest.mark.parametrize('newer', [False, True])
def test_every_area_and_more_screen_opens(owner, newer):
    for area in menu.AREAS:
        checked(ui.cid('111', 'mn', area), newer=newer)
        if area != 'home':
            checked(ui.cid('111', 'mn', area, 'more'), newer=newer)


@pytest.mark.parametrize('newer', [False, True])
def test_every_list_opens_and_its_choices_work(owner, newer):
    for key, item in menu.LEAVES.items():
        if item['kind'] != 'pick' or key in menu.HIDDEN:
            continue
        values = select_values(checked(ui.cid('111', 'mk', key), newer=newer))
        grouped = str(item['pick']).startswith('leaves:')
        if grouped:
            assert values, key                     # a grouped list always has its entries
        for value in values if grouped else values[:2]:
            checked(ui.cid('111', 'mp', key), [value], newer=newer)


@pytest.mark.parametrize('choice, said', [('m_liveon', 'Stream is LIVE'), ('m_liveoff', 'Stream is offline'), ('m_liveauto', 'utomatic')])
def test_the_stream_live_list_runs_the_chosen_setting(owner, choice, said):
    data = checked(ui.cid('111', 'mp', 'm_live'), [choice])
    assert said in json.dumps(data, ensure_ascii=False)


def test_a_grouped_list_runs_only_its_own_entries(owner):
    # A value that is not one of the list's own entries is refused, not run (Stream live… cannot start a recap post).
    data = press(ui.cid('111', 'mp', 'm_live'), ['m_recappost'])
    assert GONE in json.dumps(data, ensure_ascii=False)


def test_other_amount_asks_for_what_seed_industries_allows():
    from test_buttons_everywhere import submit
    citizen(lumber=40)
    form = press(ui.cid('111', 'mo', 'sell', LUMBER))
    box = form['data']['components'][0]['components'][0]
    assert form['type'] == 9 and '1–25' in box['label'] and box['max_length'] == 2
    refused = json.dumps(submit(form['data']['custom_id'], '30')['data'], ensure_ascii=False)
    assert 'from 1 to 25' in refused and 'Sell all' in refused
    submit(form['data']['custom_id'], '25')
    with m.SessionLocal() as db:
        assert m.material_amount(db, m.player(db, W, 'discord', '111', 'Kam')[1], LUMBER) == 15
