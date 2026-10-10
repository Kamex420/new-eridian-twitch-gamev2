"""Menu flow, third group: Orders has a Deliver button beside each order, Buy opens categories first and then a category's
items (each with a Buy button) with a few "for my goal" items on top, and Skills has a Train button beside each trainable skill."""
import time
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, W, LUMBER, CAMPFIRE
import test_menu_polish as polish
from app import crafting_progression as cp, extras, menu, shopping_list, ui, workbench as wb, layout_v2 as v2, seed_content as s
from app.game import cooldowns_materials as cm, routes_market
from app.game.training_and_items import training_skills
from app.game.world import society_tier_index, world_clock


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    ui.HISTORY.clear()
    citizen(lumber=0)
    with m.SessionLocal() as db:
        p = polish.player(db)
        p.sc = 5000
        db.commit()


def screen(custom_id, newer=False, values=None):
    return polish.shown(custom_id, values, newer=newer)


def press_on(message, custom_id, values=None):
    """Press a control on a message with this id (Back remembers the screens a message showed)."""
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)}, 'message': {'id': message, 'flags': 64}}
    return ui.handle_component(payload)['data']


def said(data):
    return v2.text_of(data)


def sections(data):
    """(text, the button beside it) for each line with a button beside it, in the newer layout."""
    return [(s_['components'][0]['content'], s_['accessory']) for s_ in polish.walk(data['components']) if s_.get('type') == v2.SECTION]


def button_by_id(data, custom_id):
    return next((b for b in polish.buttons(data) if b['custom_id'] == custom_id), None)


def select_of(data):
    return next((c for c in polish.walk(data['components']) if c.get('type') == 3), None)


def option_values(data):
    return [o['value'] for o in select_of(data)['options']]


def back_of(data):
    return next(b['custom_id'] for b in polish.buttons(data) if b['label'] == 'Back')


def rows_of(data):
    return [[c.get('label') for c in r['components']] for r in data['components']]


# ---------------------------------------------------------------- 1. Orders: a Deliver button beside each order

def today(db):
    """Today's production orders: [(key, order)]."""
    return cm.available_production_orders(W, world_clock(db, W)['day'], society_tier_index(m.society(db, W)))


def give(order):
    with m.SessionLocal() as db:
        p = polish.player(db)
        for material, amount in order['cost'].items():
            m.material_change(db, p, material, amount)
        db.commit()


def complete(key):
    with m.SessionLocal() as db:
        p = polish.player(db)
        db.add(cm.ProductionOrderCompletion(channel_id=W, canonical_uid=p.twitch_uid, avesta_day=world_clock(db, W)['day'], order_key=key))
        db.commit()


def orders():
    with m.SessionLocal() as db:
        return today(db)


def deliver_id(key):
    return ui.cid('111', 'mp', 'fulfill', '=' + key)


def test_each_order_has_a_deliver_button_beside_its_line(owner):
    found = orders()
    assert len(found) == 3
    data = screen(ui.cid('111', 'mv', 'orders'), newer=True)
    beside = sections(data)
    assert [b['custom_id'] for _, b in beside if b['label'] == 'Deliver'] == [deliver_id(k) for k, _ in found]
    for (key, order), (line, b) in zip(found, beside):
        assert f"**{order['name']}** (" in line and f'`{key}`' in line          # each button sits beside its own order
        assert b['style'] == 2                                                   # nothing in the bag yet: grey, but still pressable
    assert not [b for b in polish.buttons(data) if b['label'].startswith('Deliver:')]      # the old layout's copies are gone


def test_a_deliver_button_is_green_when_the_order_can_be_delivered(owner):
    (first, order), (second, _), _ = orders()
    give(order)
    beside = {b['custom_id']: b for _, b in sections(screen(ui.cid('111', 'mv', 'orders'), newer=True))}
    assert beside[deliver_id(first)]['style'] == 3 and beside[deliver_id(second)]['style'] == 2


def test_a_delivered_order_has_no_button(owner):
    (first, _), (second, _), (third, _) = orders()
    complete(first)
    newer = screen(ui.cid('111', 'mv', 'orders'), newer=True)
    beside = sections(newer)
    assert [b['custom_id'] for _, b in beside] == [deliver_id(second), deliver_id(third)]
    assert 'COMPLETED' in said(newer) and button_by_id(newer, deliver_id(first)) is None
    old = screen(ui.cid('111', 'mv', 'orders'))
    assert button_by_id(old, deliver_id(first)) is None and button_by_id(old, deliver_id(second)) is not None
    for key in (second, third):
        complete(key)
    done = screen(ui.cid('111', 'mv', 'orders'), newer=True)
    assert not [b for b in polish.buttons(done) if b['label'].startswith('Deliver')]       # all done: no buttons, the screen still opens


def test_the_deliver_button_opens_the_confirm_and_confirming_delivers(owner):
    (key, order), _, _ = orders()
    give(order)
    asked = screen(deliver_id(key))
    assert 'Confirm' in said(asked) and f"**{order['name']}**" in said(asked)
    with m.SessionLocal() as db:
        before = polish.player(db).sc
    confirm = next(b for b in polish.buttons(asked) if b['label'] == 'Confirm')
    assert 'Production order delivered' in said(ui.handle_component(
        {'type': 3, 'data': {'custom_id': confirm['custom_id'], 'values': []}, 'member': {'user': {'id': '111', 'username': 'Kam'}}, 'message': {'flags': 64}})['data'])
    with m.SessionLocal() as db:
        assert polish.player(db).sc > before
        assert cm.order_completed(db, polish.player(db), world_clock(db, W)['day'], key)
    assert not [b for _, b in sections(screen(ui.cid('111', 'mv', 'orders'), newer=True)) if b['custom_id'] == deliver_id(key)]


def test_a_grey_deliver_button_still_opens_the_confirm_and_delivering_without_everything_spends_nothing(owner):
    (key, order), _, _ = orders()
    asked = screen(deliver_id(key))
    assert 'Confirm' in said(asked)
    confirm = next(b for b in polish.buttons(asked) if b['label'] == 'Confirm')
    answer = ui.handle_component({'type': 3, 'data': {'custom_id': confirm['custom_id'], 'values': []},
                                  'member': {'user': {'id': '111', 'username': 'Kam'}}, 'message': {'flags': 64}})['data']
    assert 'still needs' in said(answer)
    with m.SessionLocal() as db:
        assert not cm.order_completed(db, polish.player(db), world_clock(db, W)['day'], key)


def test_the_old_layout_has_a_row_of_deliver_buttons_with_the_order_names(owner):
    found = orders()
    data = screen(ui.cid('111', 'mv', 'orders'))
    rows = rows_of(data)
    assert rows[0] == [f"Deliver: {order['name']}" for _, order in found]
    assert [b['custom_id'] for b in data['components'][0]['components']] == [deliver_id(k) for k, _ in found]
    assert 'My bag' in rows[1] and rows[-1][-2:] == ['Back', 'Menu'] and len(rows) <= 5
    assert all(len(label) <= 80 for row in rows for label in row)


def test_every_order_the_game_can_roll_finds_its_line(owner, monkeypatch):
    from app.game import routes_market
    for key, order in cm.PRODUCTION_ORDERS.items():
        one = [(key, order)]
        monkeypatch.setattr(cm, 'available_production_orders', lambda *a: one)
        monkeypatch.setattr(routes_market, 'available_production_orders', lambda *a: one)
        old = screen(ui.cid('111', 'mv', 'orders'))
        assert [i['match'] for i in old['_items']] == [f"**{order['name']}** ("], key           # its line is in the text
        data = screen(ui.cid('111', 'mv', 'orders'), newer=True)
        (line, b), = sections(data)
        assert f"**{order['name']}** (" in line and f'`{key}`' in line and b['custom_id'] == deliver_id(key)


def test_more_orders_than_fit_beside_their_lines_keep_a_button_in_the_rows(owner, monkeypatch):
    from app.game import routes_market
    every = list(cm.PRODUCTION_ORDERS.items())[:6]
    monkeypatch.setattr(cm, 'available_production_orders', lambda *a: every)
    monkeypatch.setattr(routes_market, 'available_production_orders', lambda *a: every)
    data = screen(ui.cid('111', 'mv', 'orders'), newer=True)
    beside = sections(data)
    assert 0 < len(beside) <= 6
    for (key, order), (line, b) in zip(every, beside):
        assert f"**{order['name']}** (" in line and b['custom_id'] == deliver_id(key)
    reachable = {b['custom_id'] for _, b in beside} | {b['custom_id'] for b in polish.buttons(data) if b['label'].startswith('Deliver:')}
    assert reachable == {deliver_id(k) for k, _ in every}


def test_the_orders_text_is_unchanged_and_the_slash_command_still_works(owner):
    (key, order), _, _ = orders()
    text = m._discord_call_internal('seedindustries', '111', 'Kam', {'action': 'orders'}, '')
    assert order['name'] in text and 'Deliver:' in text
    give(order)
    assert 'PRODUCTION ORDER COMPLETE' in m._discord_call_internal('seedindustries', '111', 'Kam', {'action': 'fulfill', 'item': key}, '')


def test_the_orders_view_points_to_the_deliver_buttons_instead_of_the_command(owner):
    orders()
    for newer in (True, False):
        text = said(screen(ui.cid('111', 'mv', 'orders'), newer=newer))
        assert menu.FULFILL_BY_BUTTON in text, newer
        assert '/seedindustries' not in text and 'Fulfill Production Order' not in text, newer
        assert 'Buying every input costs more than the order pays; manufacturing creates the profit.' in text      # the rest of the sentence stays


def test_the_orders_view_keeps_the_command_line_once_every_order_is_delivered(owner):
    for key, _ in orders():
        complete(key)
    data = screen(ui.cid('111', 'mv', 'orders'), newer=True)
    assert not [b for b in polish.buttons(data) if b['label'].startswith('Deliver')]
    assert menu.FULFILL_BY_BUTTON not in said(data) and '/seedindustries' in said(data)      # no button to point to


def test_the_typed_orders_command_still_says_to_use_the_fulfill_command(owner):
    orders()
    text = m._discord_call_internal('seedindustries', '111', 'Kam', {'action': 'orders'}, '')
    assert routes_market.FULFILL_BY_COMMAND == 'Use /seedindustries action:Fulfill item:<order key>.'
    assert routes_market.FULFILL_BY_COMMAND in text and menu.FULFILL_BY_BUTTON not in text
    assert text.endswith(routes_market.FULFILL_BY_COMMAND + ' Buying every input costs more than the order pays; manufacturing creates the profit.')


# ---------------------------------------------------------------- 2. Buy: categories, then a category's items

def categories():
    return menu.buy_categories()


def open_buttons(data):
    return {b['custom_id']: b for _, b in sections(data) if b['label'] == 'Open'}


def open_id(key=''):
    return ui.cid('111', 'mk', 'buy', *([key] if key else []))


def test_the_categories_cover_everything_for_sale_once_and_small_ones_are_folded_into_other(owner):
    everything = [k for k, _ in menu.buy_items()]
    listed = [k for c in categories() for k in c[4]]
    assert sorted(listed) == sorted(everything) and len(set(listed)) == len(listed)
    assert categories()[-1][0] == 'other' and 'other' not in s.DISPLAY_INFO
    for key, emoji, label, text, keys in categories()[:-1]:
        assert len(keys) >= menu.BUY_MIN_CATEGORY and key in s.DISPLAY_INFO and (emoji, label) == s.DISPLAY_INFO[key][:2]
    order = [c[0] for c in categories()[:-1]]
    assert order == [k for k, *_ in s.DISPLAY_CATEGORIES if k in order]                  # in the catalog's order
    assert 'cargo' in categories()[-1][4]                                                # no category: Other
    small = {i for i in everything if s.DISPLAY_CATEGORY.get(i) not in {c[0] for c in categories()}}       # in a category with fewer than three, or none
    assert len(small) > 1 and small <= set(categories()[-1][4]) and not any(set(c[4]) & small for c in categories()[:-1])


@pytest.mark.parametrize('newer', [False, True])
def test_buy_opens_the_categories_not_a_dropdown_of_everything(owner, newer):
    data = screen(open_id(), newer=newer)
    assert select_of(data) is None and 'Choose a category, then an item and how many.' in said(data)
    for key, emoji, label, text, keys in categories():
        assert f'**{emoji} {label}** — {len(keys)} items' in said(data)
    assert [b['custom_id'] for b in polish.buttons(data) if b['label'] not in {'Back', 'Menu'}] == [open_id(c[0]) for c in categories()]
    assert 'Bag & Shop › Buy' in (said(data) if newer else data['embeds'][0]['author']['name'])        # where it sits


def test_each_category_has_an_open_button_beside_its_line_and_the_old_layout_has_them_in_rows(owner):
    newer = screen(open_id(), newer=True)
    assert list(open_buttons(newer)) == [open_id(c[0]) for c in categories()]
    assert all(b['style'] == 2 for b in open_buttons(newer).values())                    # grey: it only opens a list
    for (line, b), (key, emoji, label, _, keys) in zip(sections(newer), categories()):
        assert line.startswith(f'**{emoji} {label}**') and b['custom_id'] == open_id(key)
    old = screen(open_id())
    assert len(old['components']) <= 5
    assert [b['custom_id'] for b in old['components'][0]['components']] == list(open_buttons(newer))
    assert old['components'][0]['components'][0]['label'] == f'{categories()[0][2]} ({len(categories()[0][4])})'
    assert [b['label'] for b in old['components'][-1]['components']] == ['Back', 'Menu']
    assert back_of(old) == ui.cid('111', 'bk', 'mn', 'trade')


def test_a_category_lists_its_items_with_the_buy_choices(owner):
    for key, emoji, label, text, keys in categories():
        data = screen(open_id(key))
        select = select_of(data)
        assert select['custom_id'] == ui.cid('111', 'mp', 'buy', key)
        assert sum((option_values(d) for d in pages_of(key, newer=False)), []) == keys        # this category's items, in the Buy list's order
        assert f'Buy · {label}' in said(data)
        assert back_of(data) == ui.cid('111', 'bk', 'mk', 'buy')           # Back: the categories
        assert data['embeds'][0]['author']['name'].endswith(f'Bag & Shop › Buy › {label}')
    labels = [o['label'] for o in select_of(screen(open_id('food')))['options']]
    assert 'Berries — 4 SC · you have 0' in labels


def pages_of(key, newer=True):
    """[(the screen of each page of a Buy category, the items on it)], reached by pressing its Next ▶ button."""
    shown, data = [], polish.shown(open_id(key), newer=newer)
    while True:
        shown.append(data)
        nxt = next((b for b in polish.buttons(data) if b['label'] == 'Next ▶'), None)
        if nxt is None:
            return shown
        data = polish.shown(nxt['custom_id'], newer=newer)


def page_items(data):
    """The items a page's dropdown lists (the old layout) or its Buy buttons stand for (the newer one)."""
    if select_of(data) is not None:
        return option_values(data)
    return [b['custom_id'].rsplit('|=', 1)[1] for _, b in sections(data) if b['label'] == 'Buy']


def test_a_category_of_eleven_or_fewer_is_one_page_with_a_green_buy_button_beside_each_item(owner):
    small = [c for c in categories() if len(c[4]) <= menu.BUY_ONE_PAGE]
    assert {c[0] for c in small} >= {'parts', 'food', 'other'}
    for key, emoji, label, text, keys in small:
        data = screen(open_id(key), newer=True)
        assert [b['custom_id'] for _, b in sections(data)] == [ui.cid('111', 'mp', 'buy', key, '=' + k) for k in keys]
        assert all(b['label'] == 'Buy' and b['style'] == 3 for _, b in sections(data)) and select_of(data) is None
        heads = [o['label'].split(' — ')[0] for o in select_of(screen(open_id(key)))['options']]
        assert [line.split('**')[1] for line, _ in sections(data)] == heads                   # each button sits beside its own item
        assert 'Page ' not in said(data) and not [b for b in polish.buttons(data) if 'Previous' in b['label'] or 'Next' in b['label']]
        assert [b['label'] for b in polish.buttons(data) if b['label'] != 'Buy'] == ['Back', 'Menu']


def test_a_larger_category_pages_in_even_parts_of_at_most_ten_with_previous_and_next_buttons(owner):
    materials = next(c for c in categories() if c[0] == 'materials')[4]
    assert len(materials) == 23
    shown = pages_of('materials')
    assert [len(page_items(d)) for d in shown] == [8, 8, 7]                                    # ceil(23/10) = 3 pages, ceil(23/3) = 8 each
    assert sum((page_items(d) for d in shown), []) == materials                                # in the Buy list's order, none twice
    for number, data in enumerate(shown, 1):
        assert f'Page {number} of 3.' in said(data) and select_of(data) is None
        assert [b['custom_id'] for _, b in sections(data)] == [ui.cid('111', 'mp', 'buy', 'materials', '=' + k) for k in page_items(data)]
        assert all(b['label'] == 'Buy' and b['style'] == 3 for _, b in sections(data))
        assert [b['label'] for b in polish.buttons(data) if b['label'] != 'Buy'] == \
            (['◀ Previous'] if number > 1 else []) + (['Next ▶'] if number < 3 else []) + ['Back', 'Menu']
    previous = next(b for b in polish.buttons(shown[1]) if b['label'] == '◀ Previous')
    assert previous['custom_id'] == ui.cid('111', 'mp', 'buy', 'materials', '=__page:1') and previous['style'] == 2
    assert back_of(shown[2]) == ui.cid('111', 'bk', 'mk', 'buy')                               # Back: the categories


def test_every_page_of_every_buy_category_converts_with_every_item_beside_its_button(owner):
    for key, emoji, label, text, keys in categories():
        old = pages_of(key, newer=False)
        shown = []
        for number, page in enumerate(old, 1):                                                 # the old layout's answer, converted as the endpoint does
            data = v2.convert(page)
            assert data is not None, (key, number)
            shown.append(data)
        assert sum((page_items(d) for d in shown), []) == keys, key
        for number, data in enumerate(shown, 1):
            beside = [b for _, b in sections(data) if b['label'] == 'Buy']
            assert len(beside) == len(page_items(data)) <= 11 and select_of(data) is None, (key, number)       # all kept: no dropdown left over
            assert len(beside) <= (menu.BUY_ONE_PAGE if len(old) == 1 else menu.BUY_PER_PAGE), (key, number)
        for page in old:                                                                       # the old layout: a dropdown and one bottom row
            assert len(page['components']) == 2 and select_of(page) is not None
            assert not [o for o in select_of(page)['options'] if o['value'].startswith('__page:')]


def test_the_largest_pages_the_game_could_ever_show_still_convert(owner, monkeypatch):
    everything = [k for k, _ in menu.buy_items()]
    for count in (11, 12, 20, 21, 30, 48):
        monkeypatch.setattr(menu, 'buy_categories', lambda c=count: [('materials', '🧱', 'Materials & Ores', 'Raw resources.', everything[:c])])
        shown = pages_of('materials')
        assert all(select_of(d) is None for d in shown), count                                 # every item kept its Buy button, so no dropdown is left
        assert sum((page_items(d) for d in shown), []) == everything[:count], count
        assert len(shown) == (1 if count <= 11 else -(-count // 10)) and max(len(page_items(d)) for d in shown) <= 11, count
        pages = len(shown)
        assert [len(page_items(d)) for d in shown] == [min(-(-count // pages), count - i * -(-count // pages)) for i in range(pages)], count     # ceil(n/pages) each


def test_a_buy_button_opens_the_amount_screen_and_back_returns_to_the_category(owner):
    key = 'parts'
    item = next(c for c in categories() if c[0] == key)[4][0]
    press_on('1', open_id())
    items = press_on('1', open_id(key))
    assert select_of(items)['custom_id'] == ui.cid('111', 'mp', 'buy', key)
    amount = press_on('1', ui.cid('111', 'mp', 'buy', key, '=' + item))
    assert {'Buy 1', 'Buy 5', 'Buy 10', 'Buy 25', 'Other amount…'} <= set(polish.labels(amount))
    assert back_of(amount) == ui.cid('111', 'bk', 'mk', 'buy', key)          # with nothing to go back to: the item's category
    again = press_on('1', back_of(amount))                                   # the message remembers its screens: back to the category
    assert select_of(again)['custom_id'] == ui.cid('111', 'mp', 'buy', key) and 'Components' in said(again)
    top = press_on('1', back_of(again))                                      # then the categories
    assert select_of(top) is None and 'Materials & Ores' in said(top)
    assert 'Bag & Shop' in said(press_on('1', back_of(top)))                 # then Bag & Shop
    fresh = press_on('2', back_of(amount))                                   # a message that remembers nothing: the fallback, the item's category
    assert select_of(fresh)['custom_id'] == ui.cid('111', 'mp', 'buy', key)


def test_buying_from_a_category_spends_sc_and_stays_in_bag_and_shop(owner):
    item = next(c for c in categories() if c[0] == 'food')[4][0]
    amount = screen(ui.cid('111', 'mp', 'buy', 'food', '=' + item))
    bought = screen(next(b for b in polish.buttons(amount) if b['label'] == 'Buy 5')['custom_id'])
    assert 'bought 5' in said(bought) and 'My bag' in polish.labels(bought)
    with m.SessionLocal() as db:
        assert m.material_amount(db, polish.player(db), item) == 5
    form = ui.handle_component({'type': 3, 'data': {'custom_id': ui.cid('111', 'mo', 'buy', item), 'values': []},
                                'member': {'user': {'id': '111', 'username': 'Kam'}}, 'message': {'flags': 64}})
    assert form['type'] == 9


def test_older_buy_buttons_without_a_category_still_work(owner):
    item = next(c for c in categories() if c[0] == 'food')[4][0]
    for custom_id, values in ((ui.cid('111', 'mp', 'buy'), [item]), (ui.cid('111', 'mp', 'buy', '=' + item), None)):
        amount = screen(custom_id, values=values)
        assert {'Buy 1', 'Buy 5'} <= set(polish.labels(amount)) and back_of(amount) == ui.cid('111', 'bk', 'mk', 'buy', 'food')
    old_page = screen(ui.cid('111', 'mp', 'buy'), values=['__page:2'])           # the old dropdown's page: the categories now
    assert select_of(old_page) is None and 'Materials & Ores' in said(old_page)
    for unknown in ('nonsense', 'FOOD'):
        assert select_of(screen(open_id(unknown))) is None and 'Materials & Ores' in said(screen(open_id(unknown)))
    assert 'Materials & Ores' in said(screen(ui.cid('111', 'mp', 'buy', 'nonsense'), values=['__page:2']))


@pytest.mark.parametrize('newer', [False, True])
def test_every_category_screen_opens_and_every_item_reaches_the_amount_screen(owner, newer):
    for key, emoji, label, text, keys in categories():
        screen(open_id(key), newer=newer)
        for item in keys:
            custom_id = ui.cid('111', 'mp', 'buy', key, '=' + item)
            assert len(custom_id) <= 100
            assert 'How many?' in said(screen(custom_id, newer=newer))


def test_paging_keeps_the_category_the_dropdown_and_the_choices(owner, monkeypatch):
    everything = [k for k, _ in menu.buy_items()]
    assert len(everything) > 25
    monkeypatch.setattr(menu, 'buy_categories', lambda: [('materials', '🧱', 'Materials & Ores', 'Raw resources.', everything)])
    first = screen(open_id('materials'))
    select = select_of(first)
    assert select['custom_id'] == ui.cid('111', 'mp', 'buy', 'materials') and 'Page 1 of 5.' in said(first)       # 48 items: 5 pages of 10, 10, 10, 10, 8
    assert option_values(first) == everything[:10] and not [o for o in select['options'] if o['value'].startswith('__page:')]
    assert not [b for b in polish.buttons(first) if b['label'] == '◀ Previous']
    second = screen(next(b['custom_id'] for b in polish.buttons(first) if b['label'] == 'Next ▶'))
    assert 'Page 2 of 5.' in said(second) and select_of(second)['custom_id'] == select['custom_id']      # the page keeps the category
    assert option_values(second) == everything[10:20]
    third = screen(ui.cid('111', 'mp', 'buy', 'materials', '=__page:5'))                                 # a button from any page
    assert option_values(third) == everything[40:] and 'Page 5 of 5.' in said(third)
    assert not [b for b in polish.buttons(third) if b['label'] == 'Next ▶'] and [b for b in polish.buttons(third) if b['label'] == '◀ Previous']
    assert 'Page 5 of 5.' in said(screen(ui.cid('111', 'mp', 'buy', 'materials', '=__page:99')))        # a page that does not exist: the last
    assert 'Page 1 of 5.' in said(screen(ui.cid('111', 'mp', 'buy', 'materials', '=__page:0')))
    assert option_values(screen(select['custom_id'], values=['__page:2'])) == everything[10:20]          # and the dropdown's own value still pages
    assert back_of(third) == ui.cid('111', 'bk', 'mk', 'buy')
    item = everything[15]
    assert {'Buy 1', 'Buy 5'} <= set(polish.labels(screen(select_of(second)['custom_id'], values=[item])))     # a choice reaches the amount screen
    assert {'Buy 1', 'Buy 5'} <= set(polish.labels(screen(ui.cid('111', 'mp', 'buy', 'materials', '=' + item))))


# ---- Buy: the items the goal and the shopping list still miss

def set_goal(name=CAMPFIRE.name, listed=()):
    with m.SessionLocal() as db:
        p = polish.player(db)
        if name:
            extras.set_goal(db, p, wb.resolve(db, p, name).id)
        for recipe, amount in listed:
            shopping_list.set_entry(db, p, wb.resolve(db, p, recipe).id, amount)
        db.commit()


def lumber_buy(owner_id='111'):
    return ui.cid(owner_id, 'mp', 'buy', '=' + LUMBER)


def test_with_no_goal_and_no_list_the_categories_are_all_there_is(owner):
    data = screen(open_id(), newer=True)
    assert 'goal' not in said(data).lower() and 'shopping list' not in said(data).lower()
    assert [b['label'] for _, b in sections(data)] == ['Open'] * len(categories())
    assert rows_of(screen(open_id()))[0][0] == f'{categories()[0][2]} ({len(categories()[0][4])})'


def test_the_goal_is_listed_first_with_a_green_buy_button_for_each_missing_item(owner):
    set_goal()
    for newer in (True, False):
        data = screen(open_id(), newer=newer)
        assert 'for my goal' in said(data).lower() and 'goal & list' not in said(data).lower()
        assert '**Lumber** — 4 SC · missing 2 · you have 0' in said(data)
        assert said(data).index('Lumber') < said(data).index('Materials & Ores')
    newer = screen(open_id(), newer=True)
    first_line, first_button = sections(newer)[0]
    assert first_line.startswith('**Lumber**') and first_button['custom_id'] == lumber_buy() and first_button['style'] == 3 and first_button['label'] == 'Buy'
    assert [b['label'] for _, b in sections(newer)][1:] == ['Open'] * len(categories())
    old = screen(open_id())
    assert old['components'][0]['components'][0]['custom_id'] == lumber_buy() and old['components'][0]['components'][0]['label'] == 'Buy Lumber'
    assert len(old['components']) <= 5 and old['components'][1]['components'][0]['custom_id'] == open_id(categories()[0][0])
    amount = screen(lumber_buy())
    assert {'Buy 1', 'Buy 5'} <= set(polish.labels(amount)) and 'Lumber' in said(amount)


def test_the_heading_follows_what_is_set_and_the_group_goes_when_nothing_is_missing(owner):
    set_goal(name='', listed=[(CAMPFIRE.name, 3)])
    assert 'for my shopping list' in said(screen(open_id(), newer=True)).lower()
    assert '**Lumber** — 4 SC · missing 6 · you have 0' in said(screen(open_id(), newer=True))
    set_goal()
    both = said(screen(open_id(), newer=True))
    assert 'for my goal & list' in both.lower() and '**Lumber** — 4 SC · missing 8 · you have 0' in both       # one plan: 2 for the goal + 6 for the list
    with m.SessionLocal() as db:
        m.material_change(db, polish.player(db), LUMBER, 8)
        db.commit()
    done = screen(open_id(), newer=True)
    assert 'goal' not in said(done).lower() and 'Lumber**' not in said(done)


def test_the_list_matches_what_the_shopping_list_screen_would_buy(owner):
    others = [e for e in wb.index() if e.name in {'Iron Plate', 'Wood Planks', 'Table Lamp'}]
    set_goal(name='', listed=[(CAMPFIRE.name, 4)] + [(e.name, 3) for e in others])
    with m.SessionLocal() as db:
        p = polish.player(db)
        mine = {k: n for k, n, _, _ in menu.buy_needs(db, p)[0]}
        theirs = {x.key: x.missing for x in shopping_list.overview(db, p).buy}
    assert mine and mine == theirs


def test_the_goal_alone_matches_its_plan(owner):
    set_goal()
    with m.SessionLocal() as db:
        p = polish.player(db)
        ctx = wb.Context(db, p)
        raw = extras.full_plan(ctx, wb.entry(CAMPFIRE.id))[1]
        assert {k: n for k, n, _, _ in menu.buy_needs(db, p)[0]} == {k: n for k, n in raw.items() if m.SEED_INDUSTRIES[k]['buy']}


def test_at_most_five_items_are_listed_most_missing_first_and_the_rest_are_counted(owner, monkeypatch):
    keys = [k for k, _ in menu.buy_items()][:8]
    monkeypatch.setattr(extras, 'list_plan', lambda ctx, wanted, goal=None: ([], {k: 2 + (i % 3) * 5 for i, k in enumerate(keys)}, set(), [], {}))
    set_goal()
    with m.SessionLocal() as db:
        rows = menu.buy_needs(db, polish.player(db))[0]
    assert [n for _, n, _, _ in rows] == sorted((n for _, n, _, _ in rows), reverse=True) and rows[0][1] == 12      # most missing first
    newer = screen(open_id(), newer=True)
    assert [b['label'] for _, b in sections(newer)].count('Buy') == 5 and '…and 3 more for them in the categories below.' in said(newer)
    shown = [line for line, b in sections(newer) if b['label'] == 'Buy']
    assert [int(line.split('missing ')[1].split(' ')[0]) for line in shown] == [n for _, n, _, _ in rows[:5]]
    old = screen(open_id())
    assert len(old['components'][0]['components']) == 5 and len(old['components']) <= 5


def test_rare_ore_you_cannot_buy_yet_is_not_offered(owner, monkeypatch):
    rare = next(iter(cp.RARE))
    monkeypatch.setattr(extras, 'list_plan', lambda ctx, wanted, goal=None: ([], {rare: 3, LUMBER: 2}, set(), [], {}))
    set_goal()
    with m.SessionLocal() as db:
        p = polish.player(db)
        assert [k for k, _, _, _ in menu.buy_needs(db, p)[0]] == [LUMBER]
        m.material_change(db, p, s.key('Small Mineral Extractor'), 1)
        db.commit()
    with m.SessionLocal() as db:
        assert {k for k, _, _, _ in menu.buy_needs(db, polish.player(db))[0]} == {LUMBER, rare}


def test_the_goal_group_is_cheap_and_never_builds_the_goal_or_list_screens(owner, monkeypatch):
    """With a goal and a 3-recipe list the group costs a few milliseconds (measured over every recipe as the goal: worst about 7 ms);
    the shopping list screen's own overview costs ~0.5 s, so the group must never call it, or the goal's walkthrough."""
    deep = sorted(wb.index(), key=lambda e: -len(e.inputs))
    set_goal(deep[0].name, [(deep[1].name, 3), (deep[2].name, 2), (deep[3].name, 1)])
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError('a heavy screen plan was built'))
    monkeypatch.setattr(extras, 'walkthrough', boom)
    monkeypatch.setattr(shopping_list, 'overview', boom)
    with m.SessionLocal() as db:
        p = polish.player(db)
        assert menu.buy_goal(db, p, '111') is not None
        started = time.perf_counter()
        for _ in range(10):
            menu.buy_goal(db, p, '111')
        assert (time.perf_counter() - started) / 10 < 0.05           # the limit for keeping the group at all
    assert 'for my goal' in said(screen(open_id(), newer=True)).lower()


def test_nothing_is_planned_when_neither_goal_nor_list_is_set(owner, monkeypatch):
    monkeypatch.setattr(extras, 'list_plan', lambda *a, **k: (_ for _ in ()).throw(AssertionError('planned')))
    monkeypatch.setattr(wb, 'Context', lambda *a, **k: (_ for _ in ()).throw(AssertionError('context built')))
    with m.SessionLocal() as db:
        assert menu.buy_goal(db, polish.player(db), '111') is None


def test_a_failing_plan_leaves_the_categories_without_the_goal_group(owner, monkeypatch):
    set_goal()
    monkeypatch.setattr(extras, 'list_plan', lambda *a, **k: 1 / 0)
    data = screen(open_id(), newer=True)
    assert 'goal' not in said(data).lower() and [b['label'] for _, b in sections(data)] == ['Open'] * len(categories())


def test_the_buy_button_of_the_bag_opens_the_categories(owner):
    bag = screen(ui.cid('111', 'mv', 'inventory'))
    assert button_by_id(bag, open_id()) is not None
    assert select_of(screen(open_id())) is None


# ---------------------------------------------------------------- 3. Skills: a Train button beside each trainable skill

def skills():
    with m.SessionLocal() as db:
        return training_skills(db, polish.player(db))


def train_id(hub):
    return ui.cid('111', 'mp', 'trainskill', '=' + hub)


def test_each_trainable_skill_has_a_train_button_beside_its_line(owner):
    found = skills()
    assert len(found) == 8
    data = screen(ui.cid('111', 'mv', 'me_skills'), newer=True)
    beside = sections(data)
    assert [b['custom_id'] for _, b in beside] == [train_id(hub) for hub, *_ in found]
    for (hub, label, level, ready, total), (line, b) in zip(found, beside):
        assert line.startswith(f'• **{label}:**') and b['label'] == 'Train'
        assert b['style'] == (3 if ready else 2)                       # green while a task is ready now
    assert {b['style'] for _, b in beside} == {2, 3}
    assert not [b for b in polish.buttons(data) if b['label'].startswith('Train ')]       # the old layout's copies are gone


def test_the_skills_reply_has_no_setup_notes_or_training_steps(owner):
    text = m._discord_call_internal('me', '111', 'Kam', {'section': 'skills'}, '')
    assert 'Skills' in text and '15 XP per level' in text and 'Specializations unlock' in text
    assert 'reference screenshots' not in text and '/training' not in text
    shown = said(screen(ui.cid('111', 'mv', 'me_skills'), newer=True))
    assert '15 XP per level' in shown and 'reference screenshots' not in shown and '/training' not in shown


def test_skills_with_no_training_have_no_button(owner):
    data = screen(ui.cid('111', 'mv', 'me_skills'), newer=True)
    plain = said(data)
    for label in ('Research', 'Logistics', 'Frontier Operations', 'Commerce'):
        assert f'**{label}:**' in plain
        assert not [line for line, _ in sections(data) if f'**{label}:**' in line]
    assert len(sections(data)) == 8


def test_a_train_button_opens_that_skills_tasks(owner):
    for hub, label, *_ in skills():
        opened = screen(train_id(hub))
        assert label in said(opened) and [b for b in polish.buttons(opened) if b['label'] == 'All skills']
        assert polish.buttons(opened) and any(b['custom_id'].split('|')[2] == 't' for b in polish.buttons(opened))     # each task has a Start button
    data = screen(train_id('farming'), newer=True)
    assert 'Farming' in said(data)


def test_the_old_layout_has_train_buttons_in_rows_of_five_then_the_areas(owner):
    found = skills()
    data = screen(ui.cid('111', 'mv', 'me_skills'))
    rows = rows_of(data)
    assert rows[0] == [f'Train {label}' for _, label, *_ in found[:5]] and rows[1] == [f'Train {label}' for _, label, *_ in found[5:]]
    assert [b['custom_id'] for r in data['components'][:2] for b in r['components']] == [train_id(hub) for hub, *_ in found]
    assert 'Profile' in rows[2] and rows[-1] == ['Back', 'Menu'] and len(rows) <= 5
    assert all(len(label) <= 80 for row in rows for label in row)
    assert [b['style'] for r in data['components'][:2] for b in r['components']] == [3 if ready else 2 for *_, ready, _ in found]


def test_in_text_order_keeps_only_lines_that_exist_and_puts_them_in_order():
    data = {'embeds': [{'description': 'a **Two** b\n**One** c\n• **Three:**'}]}
    items = [{'match': '**One**'}, {'match': '**Missing**'}, {'match': '**Three:**'}, {'match': '**Two**'}]
    assert [i['match'] for i in menu.in_text_order(data, items)] == ['**Two**', '**One**', '**Three:**']
    assert menu.in_text_order({'embeds': []}, items) == items
