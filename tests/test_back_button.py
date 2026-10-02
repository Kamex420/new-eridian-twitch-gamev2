"""◀️ Back on every screen: the screen this message showed before, step by step; on a message's
first screen, one level up."""
from test_colony import m, reset
from test_workbench_ui import citizen, W
from test_layout_v2 import assert_valid
from app import ui, layout_v2 as v2, workbench as wb


def press(custom_id, message='M1', uid='111', values=None):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': uid, 'username': 'Kam'}}, 'message': {'flags': 64, 'id': message}}
    return ui.handle_component(m, payload)


def where(answer):
    return answer['data']['embeds'][0]['author']['name']


def ids(answer):
    return [c.get('custom_id') for r in answer['data']['components'] if r.get('components') for c in r['components']]


def back(answer):
    return next(i for i in ids(answer) if i.split('|')[2] == 'bk')


def test_back_returns_to_each_screen_before_in_turn():
    citizen()
    ui.HISTORY.clear()
    press(ui.cid('111', 'mn', 'home'))
    press(ui.cid('111', 'mn', 'work'))
    farming = press(ui.cid('111', 'mn', 'farming'))
    assert where(farming) == '🏠 Menu › ⛏️ Work › 🌾 Farming'
    work = press(back(farming))
    assert work['type'] == 7 and where(work) == '🏠 Menu › ⛏️ Work'
    home = press(back(work))
    assert ui.cid('111', 'mn', 'work') in ids(home) and not any('›' in str(e.get('author')) for e in home['data'].get('embeds') or [])


def test_every_screen_ends_with_back_then_menu():
    citizen()
    e = next(x for x in wb.index(m) if x.kind == 'seed')
    for custom_id in (ui.cid('111', 'mn', 'farming'), ui.cid('111', 'mn', 'work'), ui.cid('111', 'wh'), ui.cid('111', 'wc', 'parts', 1, ''),
                      ui.cid('111', 'wr', e.id, e.category, 1, ''), ui.cid('111', 'qv'), ui.cid('111', 'st'),
                      ui.cid('111', 'mk', 'sell'), ui.cid('111', 'gv'), ui.cid('111', 'qp', 'make:' + e.id, 5)):
        answer = press(custom_id, message=custom_id)
        last = [r for r in answer['data']['components'] if r.get('components')][-1]['components']
        assert [c['label'] for c in last[-2:]] == ['Back', 'Menu'], custom_id
        assert sum(i.split('|')[2] == 'bk' for i in ids(answer)) == 1, custom_id           # one Back per screen
        assert assert_valid(v2.convert(answer['data']))


def test_after_an_action_back_returns_to_the_screen_it_was_done_from():
    citizen()
    e = next(x for x in wb.index(m) if x.kind == 'seed' and x.inputs)
    recipe = press(ui.cid('111', 'wr', e.id, e.category, 1, ''), message='M3')
    craft = next(c for r in recipe['data']['components'] for c in r.get('components', []) if str(c.get('label', '')).startswith('Craft'))
    result = press(craft['custom_id'], message='M3')
    again = press(back(result), message='M3')
    assert where(again).endswith('› ' + e.name)                                           # the recipe again


def test_on_a_first_screen_back_goes_one_level_up():
    citizen()
    e = next(x for x in wb.index(m) if x.kind == 'seed')
    recipe = press(ui.cid('111', 'wr', e.id, e.category, 1, ''), message='fresh')
    assert back(recipe) == ui.cid('111', 'bk', 'wc', e.category, 1, '')
    listing = press(back(recipe), message='fresh')
    assert listing['type'] == 7 and 'Workbench ›' in where(listing) and e.name not in where(listing)
    farming = press(ui.cid('111', 'mn', 'farming'), message='other')
    assert where(press(back(farming), message='other')) == '🏠 Menu › ⛏️ Work'           # an area: up to its parent


def test_the_home_menu_has_back_once_there_is_somewhere_to_go_back_to():
    citizen()
    home = press(ui.cid('111', 'mn', 'home'), message='M5')
    assert not any(i.split('|')[2] == 'bk' for i in ids(home))
    press(ui.cid('111', 'mn', 'trade'), message='M5')
    home = press(ui.cid('111', 'mn', 'home'), message='M5')
    assert where(press(back(home), message='M5')).endswith('Trade')
