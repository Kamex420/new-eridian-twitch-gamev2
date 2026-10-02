"""Shopping list: several recipes, each in the amount you want to have, planned together with one shared pool."""
import json
import math
from datetime import timedelta
import pytest
from test_colony import m, reset, seed, client
from test_workbench_ui import citizen, press, controls, find, W, LUMBER, CAMPFIRE
from test_buttons_everywhere import _deferred_reply
from test_layout_v2 import assert_valid, sections
from app import ui, menu, extras, shopping_list as shop, seed_content as s, task_queue as q, workbench as wb
from app import layout_v2 as v2, twitch_lite as lite

TOILET = next(e for e in wb.index(m) if e.name == 'Crude Wood Toilet')
STOOL = next(e for e in wb.index(m) if e.name == 'Crude Wood Stool')
PLATE = wb.entry(m, 'sr_1018791011')               # Iron Plate at the Metalworking Bench: the catalog's route to Iron Plate
ANVIL_PLATE = wb.entry(m, 'sr_153129547')          # Iron Plate at the Basic Anvil: another recipe for the same item
SAW = next(e for e in wb.index(m) if e.name == 'Circular Saw Blade')       # 5 Iron Plate a batch
STEEL_FRAME = next(e for e in wb.index(m) if e.name == 'Steel Frame')
IRON_INGOT = s.key('Iron Ingot')
ARGENTITE = s.key('Argentite Ore')
MACHINES = {s.key('Metalworking Bench'): 1, s.key('Basic Anvil'): 1}


def give(items, uid='111'):
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid, 'Kam')[1]
        for key, n in items.items():
            m.material_change(db, p, key, n)
        db.commit()


def set_sc(amount, uid='111'):
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', uid, 'Kam')[1].sc = amount
        db.commit()


def sc(uid='111'):
    with m.SessionLocal() as db:
        return m.player(db, W, 'discord', uid, 'Kam')[1].sc


def have(key, uid='111'):
    with m.SessionLocal() as db:
        return m.material_amount(db, m.player(db, W, 'discord', uid, 'Kam')[1], key)


def add(recipe, amount=None, uid='111'):
    with m.SessionLocal() as db:
        text = shop.set_entry(m, db, m.player(db, W, 'discord', uid, 'Kam')[1], recipe, amount)
        db.commit()
        return text


def listed(uid='111'):
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid, 'Kam')[1]
        return [(r.recipe_id, r.want) for r in shop.entries(db, p)]


def info(uid='111'):
    with m.SessionLocal() as db:
        return shop.overview(m, db, m.player(db, W, 'discord', uid, 'Kam')[1])


def plan(wanted, uid='111'):
    with m.SessionLocal() as db:
        ctx = wb.Context(m, db, m.player(db, W, 'discord', uid, 'Kam')[1])
        return extras.list_plan(ctx, wanted), ctx.batch_size


def material(key, uid='111'):
    return next(x for x in info(uid).materials if x.key == key)


def labels(data):
    return [c.get('label') or c.get('placeholder', '') for c in controls(data)]


def text_of(data):
    """A message's text and button labels, without the bold the cards add to 'Label: value' lines."""
    return (v2.text_of(data) + '\n' + '\n'.join(labels(data))).replace('**', '')


def rows_ok(data):
    rows = [r for r in data['components'] if r.get('components')]
    return len(rows) <= 5 and all(0 < len(r['components']) <= 5 for r in rows)


def last_row(data):
    return [c['label'] for c in [r for r in data['components'] if r.get('components')][-1]['components']]


def queue_row():
    with m.SessionLocal() as db:
        return db.query(q.TaskQueue).one_or_none()


# ---------------------------------------------------------------- changing the list

def test_add_update_remove_and_clear():
    citizen(lumber=0)
    assert add(CAMPFIRE.id, 3) == '🛒 Added to your shopping list: 3 Campfire (you have 0; 3 batches of 1).'
    assert add(CAMPFIRE.id, 5) == '🛒 Shopping list changed: want 5 Campfire (was 3; you have 0; 5 batches of 1).'
    assert add(CAMPFIRE.id, 5) == '🛒 You already want 5 Campfire. Nothing changed.'
    assert add(TOILET.id, '2') .startswith('🛒 Added to your shopping list: 2 Crude Wood Toilet')
    assert listed() == [(CAMPFIRE.id, 5), (TOILET.id, 2)]                  # list order: the order recipes were added
    for word in ('0', 'off', 'remove'):
        assert add(CAMPFIRE.id, word) == '🛒 Removed Campfire from your shopping list.'
        assert listed() == [(TOILET.id, 2)]
        add(CAMPFIRE.id, 1)
    assert add(STOOL.id, 0) == '🛒 Crude Wood Stool is not on your shopping list. Nothing changed.'
    with m.SessionLocal() as db:
        assert shop.clear(m, db, m.player(db, W, 'discord', '111', 'Kam')[1]) == '✖️ Shopping list cleared.'
        db.commit()
    assert listed() == []


def test_the_default_amount_is_one_batch_and_adding_again_without_one_changes_nothing():
    citizen(lumber=0)
    give(MACHINES)
    with m.SessionLocal() as db:
        per = wb.Context(m, db, m.player(db, W, 'discord', '111', 'Kam')[1]).batch_size(PLATE)
    assert per > 1
    assert add(PLATE.id) == f'🛒 Added to your shopping list: {per} Iron Plate (you have 0; 1 batch of {per}).'
    assert listed() == [(PLATE.id, per)]
    assert add(PLATE.id) == f'🛒 Iron Plate is already on your shopping list: you want {per}. Give an amount to change it. Nothing changed.'
    assert 'want 30 Iron Plate' in add(PLATE.id, 30) and listed() == [(PLATE.id, 30)]      # with an amount, adding again updates it


@pytest.mark.parametrize('amount', [-1, 1000, '2.5', 'abc', '1e3', ' 9999 '])
def test_invalid_amounts_change_nothing(amount):
    citizen()
    add(CAMPFIRE.id, 4)
    assert add(CAMPFIRE.id, amount) == '🛒 ' + shop.AMOUNT_RULE
    assert add(TOILET.id, amount) == '🛒 ' + shop.AMOUNT_RULE
    assert listed() == [(CAMPFIRE.id, 4)]


def test_unknown_recipes_the_cap_and_bonus_equipment_change_nothing():
    citizen()
    assert add('sr_nonsense', 3) == '🛒 That recipe is not available. Nothing changed.'
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert shop.add_typed(m, db, p, 'zzqqxx', 3) == '🛒 No recipe called "zzqqxx". Nothing changed.'
        assert 'Did you mean' in shop.add_typed(m, db, p, 'iron', 3)
        assert shop.entries(db, p) == []
    recipes = [e for e in wb.index(m) if e.kind == 'seed'][:shop.MAX_ENTRIES + 1]
    for e in recipes[:-1]:
        assert add(e.id, 2).startswith('🛒 Added'), e.name
    assert add(recipes[-1].id, 2) == (f'🛒 Your shopping list already has 10 recipes. Remove one before adding {recipes[-1].name}. '
                                      'Nothing changed.')
    assert len(listed()) == shop.MAX_ENTRIES and recipes[-1].id not in dict(listed())
    assert 'changed' in add(recipes[0].id, 3)                         # changing one at the cap still works
    add(recipes[0].id, 0)
    toolkit = wb.entry(m, 'toolkit')
    assert add('toolkit', 2) == '🛒 Toolkit is bonus equipment, limited to one of each, so the amount must be 1. Nothing changed.'
    assert add('toolkit', 1).startswith('🛒 Added') and dict(listed())[toolkit.id] == 1


# ---------------------------------------------------------------- done is stateless

def test_an_entry_is_done_once_you_have_enough_however_they_arrived_and_clear_done():
    citizen(lumber=0)
    add(CAMPFIRE.id, 2)
    add(TOILET.id, 1)
    assert [x.done for x in info().items] == [False, False]
    give({CAMPFIRE.output: 2})                                       # not crafted: still done
    items = info().items
    assert [(x.done, x.mark) for x in items] == [(True, '✅'), (False, '❌')]
    assert '✅ **Campfire** — have 2 / want 2 · done' in screen_text()
    give({CAMPFIRE.output: -1})
    assert not info().items[0].done                                  # back below the amount: not done any more
    give({CAMPFIRE.output: 1})
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert shop.clear(m, db, p, done_only=True) == '🧹 Cleared 1 done entry from your shopping list.'
        db.commit()
        assert shop.clear(m, db, p, done_only=True) == '🧹 Nothing on your shopping list is done yet. Nothing changed.'
    assert listed() == [(TOILET.id, 1)]


def screen_text(uid='111'):
    with m.SessionLocal() as db:
        return shop.screen_text(m, db, m.player(db, W, 'discord', uid, 'Kam')[1])


# ---------------------------------------------------------------- one plan, one pool

def test_two_entries_needing_the_same_ingredient_count_it_once():
    citizen(lumber=5)
    add(CAMPFIRE.id, 2)                                              # 4 Lumber
    add(TOILET.id, 3)                                                # 6 Lumber
    lumber = material(LUMBER)
    assert (lumber.need, lumber.have, lumber.missing) == (10, 5, 5)   # each alone would think 5 Lumber is enough or nearly
    (crafts, raw, _, rows, used), _ = plan([(CAMPFIRE, 2), (TOILET, 3)])
    assert raw == {LUMBER: 5} and used == {LUMBER: 5}
    assert [(c.id, n) for c, n, _ in crafts] == [(CAMPFIRE.id, 2), (TOILET.id, 3)] and [n for _, _, n in rows] == [2, 3]
    steps = info().steps
    assert steps[0]['name'] == 'Gather Lumber ×5' and steps[0]['action'] == {'do': 'queue', 'task': 'gather:' + LUMBER, 'count': 5}
    assert [st['name'] for st in steps[1:]] == ['Craft Campfire ×2', 'Craft Crude Wood Toilet ×3']
    assert all(st['detail'].startswith('on your shopping list') for st in steps[1:])


@pytest.mark.parametrize('order', ['plates first', 'blades first'])
def test_an_item_entry_and_a_recipe_using_that_item_plan_the_right_total(order):
    citizen(lumber=0)
    give(dict(MACHINES, **{IRON_INGOT: 10}))
    wanted = [(PLATE, 30), (SAW, 5)] if order == 'plates first' else [(SAW, 5), (PLATE, 30)]
    (crafts, raw, _, rows, _), batch_size = plan(wanted)
    per, saws = batch_size(PLATE), math.ceil(5 / batch_size(SAW))
    plates = dict((c.id, n) for c, n, _ in crafts)[PLATE.id]
    assert plates == math.ceil((30 + 5 * saws) / per)                 # 30 to have plus what the blades use, once
    assert raw == {} and dict((c.id, n) for c, n, _ in crafts)[SAW.id] == saws
    ingots = dict((c.id, n) for c, n, _ in crafts).get(s.ACQUISITION[IRON_INGOT], 0)
    assert ingots == 0                                                # 10 ingots owned cover every batch


def test_each_entry_is_made_with_its_own_recipe():
    citizen(lumber=0)
    give(dict(MACHINES, **{IRON_INGOT: 10}))
    assert ANVIL_PLATE.output == PLATE.output and ANVIL_PLATE.id != PLATE.id and s.ACQUISITION[PLATE.output] == PLATE.id
    (crafts, _, _, rows, _), batch_size = plan([(ANVIL_PLATE, 30)])
    assert [(c.id, n) for c, n, _ in crafts] == [(ANVIL_PLATE.id, math.ceil(30 / batch_size(ANVIL_PLATE)))]
    # A recipe that uses plates still gets them the catalog's way, from what the entry left over first.
    (crafts, _, _, _, _), batch_size = plan([(ANVIL_PLATE, 30), (SAW, 5)])
    made = dict((c.id, n) for c, n, _ in crafts)
    left = math.ceil(30 / batch_size(ANVIL_PLATE)) * batch_size(ANVIL_PLATE) - 30
    assert made[ANVIL_PLATE.id] == math.ceil(30 / batch_size(ANVIL_PLATE))
    assert made.get(PLATE.id, 0) == math.ceil(max(0, 5 * math.ceil(5 / batch_size(SAW)) - left) / batch_size(PLATE))


def test_combined_materials_say_need_have_missing_route_and_price():
    citizen(lumber=3)
    give({s.key('Stone'): 4})
    add(CAMPFIRE.id, 2)                                               # 4 Lumber
    add(TOILET.id, 1)                                                 # 2 Lumber
    add(next(e for e in wb.index(m) if e.name == 'Tent').id, 2)       # 2 Lumber, 2 Stone
    lumber, stone = material(LUMBER), material(s.key('Stone'))
    price = m.SEED_INDUSTRIES[LUMBER]['buy']
    assert (lumber.need, lumber.have, lumber.missing, lumber.price, lumber.cost, lumber.buyable) == (8, 3, 5, price, 5 * price, True)
    assert (stone.need, stone.have, stone.missing) == (2, 4, 0)
    whole = info()
    assert whole.cost == 5 * price and [x.key for x in whole.buy] == [LUMBER] and whole.unsold == []
    text = screen_text()
    assert f'❌ Lumber — need 8 / have 3 / missing 5 → gather ×5 · or buy for {5 * price} SC' in text
    assert '✅ Stone — need 2 / have 4' in text
    assert f'Buy all missing: {5 * price} SC for everything Seed Industries sells (you have 1000 SC).' in text


# ---------------------------------------------------------------- Fetch next

def test_fetch_next_is_the_first_steps_one_time_ticket_and_comes_back_to_the_list():
    citizen(lumber=0)
    add(CAMPFIRE.id, 1)
    screen = press(ui.cid('111', 'lv'))['data']
    fetch = find(screen, 'Fetch next')
    assert fetch['label'] == 'Fetch next: Gather Lumber ×2 (need 2)' and fetch['custom_id'].startswith('ne|111|t|') and fetch['style'] == 3
    with m.SessionLocal() as db:
        action = json.loads(db.get(ui.UiTicket, fetch['custom_id'].split('|')[3]).action)
    assert action == {'do': 'queue', 'task': 'gather:' + LUMBER, 'count': 2, 'shop': True}       # the goal's step, marked as from the list
    result = press(fetch['custom_id'])['data']
    assert queue_row().task == 'gather:' + LUMBER and queue_row().total == 2
    assert ui.cid('111', 'lv') in [c.get('custom_id') for c in controls(result)]                  # 🛒 back to the list
    assert 'already used' in press(fetch['custom_id'])['data']['content']


def test_fetch_next_opens_the_first_steps_screen_when_it_is_done_elsewhere():
    citizen(lumber=5)
    add(STOOL.id, 1)                                                  # a Tier 2 recipe: first reach Tier 2
    first = info().steps[0]
    assert first['action'] is None and first['view']
    fetch = find(press(ui.cid('111', 'lv'))['data'], 'Fetch next')
    assert fetch['custom_id'] == ui.cid('111', *first['view']) and '|t|' not in fetch['custom_id']


# ---------------------------------------------------------------- Buy all missing

def test_buy_all_missing_buys_only_the_shortfall_through_seed_industries_once(monkeypatch):
    citizen(lumber=5)
    add(CAMPFIRE.id, 2)
    add(TOILET.id, 3)
    price = m.SEED_INDUSTRIES[LUMBER]['buy']
    calls, real = [], m.seed_industries
    monkeypatch.setattr(m, 'seed_industries', lambda *a: calls.append(a[3:6]) or real(*a))
    screen = press(ui.cid('111', 'lv'))['data']
    buy = find(screen, 'Buy all missing')
    assert buy['label'] == f'Buy all missing · {5 * price} SC' and buy['custom_id'].startswith('ne|111|t|') and not buy.get('disabled')
    result = press(buy['custom_id'])['data']
    assert calls == [('buy', LUMBER, 5)]                              # the ordinary purchase, for the 5 missing only
    assert have(LUMBER) == 10 and sc() == 1000 - 5 * price
    assert f'Bought for your shopping list: 5 Lumber for {5 * price} SC. Balance: {1000 - 5 * price} SC.' in text_of(result)
    assert 'Buy all missing' not in ' '.join(labels(result))           # nothing left to buy
    assert 'already used' in press(buy['custom_id'])['data']['content']
    assert have(LUMBER) == 10 and len(calls) == 1


def test_buy_all_missing_is_greyed_out_with_its_price_when_you_cannot_afford_it():
    citizen(lumber=5)
    add(CAMPFIRE.id, 2)
    add(TOILET.id, 3)
    cost = 5 * m.SEED_INDUSTRIES[LUMBER]['buy']
    set_sc(cost - 1)
    buy = find(press(ui.cid('111', 'lv'))['data'], 'Buy all missing')
    assert buy['label'] == f'Buy all missing · {cost} SC' and buy.get('disabled') and '|t|' not in buy['custom_id']
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert shop.buy_all(m, db, p) == (f'🪙 Buying everything missing (5 Lumber) costs {cost} SC and you have {cost - 1} SC: '
                                          'earn 1 more SC first. Nothing spent.')
    assert have(LUMBER) == 5 and sc() == cost - 1


def test_what_cannot_be_bought_is_listed_with_where_it_comes_from(monkeypatch):
    citizen(lumber=0)
    monkeypatch.setitem(m.SEED_INDUSTRIES, LUMBER, dict(m.SEED_INDUSTRIES[LUMBER], buy=0))
    add(CAMPFIRE.id, 1)
    whole = info()
    assert whole.cost == 0 and [x.key for x in whole.unsold] == [LUMBER]
    screen = press(ui.cid('111', 'lv'))['data']
    assert 'Buy all missing' not in ' '.join(labels(screen))
    source = m.material_source(LUMBER).split(';')[0].rstrip('.')
    assert f'Not for sale: Lumber ({source}).' in screen_text()                   # the card shows /gather as its command chip
    assert 'Not for sale: Lumber (' in text_of(screen) and '❌ Lumber — need 2 / have 0 / missing 2 → gather ×2' in text_of(screen)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert shop.buy_all(m, db, p) == '🛒 Nothing missing on your list can be bought from Seed Industries. Nothing spent.'
    assert have(LUMBER) == 0 and sc() == 1000


def test_a_rare_ore_is_not_bought_without_harvesting_level_three():
    citizen(lumber=0)
    give(MACHINES)
    add('ore_scanner', 1)                                             # needs an Argentite Ore
    ore = material(ARGENTITE)
    assert ore.missing == 1 and ore.price and ore.locked and not ore.buyable
    assert 'needs Harvesting Lv 3' in shop.route_text(m, ore)
    whole = info()
    assert ARGENTITE not in [x.key for x in whole.buy] and ARGENTITE in [x.key for x in whole.unsold]
    assert whole.cost == sum(x.cost for x in whole.buy) > 0
    shop_buy = press(find(press(ui.cid('111', 'lv'))['data'], 'Buy all missing')['custom_id'])['data']
    assert 'Bought for your shopping list' in text_of(shop_buy) and have(ARGENTITE) == 0


# ---------------------------------------------------------------- recipes that left the catalog

def test_a_recipe_no_longer_in_the_catalog_is_shown_and_skipped():
    citizen(lumber=0)
    add(CAMPFIRE.id, 1)
    with m.SessionLocal() as db:
        db.add(shop.ShoppingEntry(channel_id=W, canonical_uid=m.player(db, W, 'discord', '111', 'Kam')[1].twitch_uid,
                                  recipe_id='sr_gone', want=3, added_at=m.now()))
        db.commit()
    whole = info()
    assert [x.recipe_id for x in whole.items] == [CAMPFIRE.id, 'sr_gone'] and whole.items[1].entry is None
    assert [st['name'] for st in whole.steps] == ['Gather Lumber ×2', 'Craft Campfire ×1']        # planned without it
    screen = press(ui.cid('111', 'lv'))['data']
    assert '❔ sr_gone — no longer available: remove it' in text_of(screen)
    remove = find(screen, 'Remove sr_gone')
    assert remove['custom_id'] == ui.cid('111', 'ls', 'sr_gone', 0)
    out = v2.convert(ui.tidy(dict(screen)))
    assert assert_valid(out) and [x['accessory']['label'] for x in sections(out)] == ['Change', 'Remove']
    with m.SessionLocal() as db:
        assert shop.clear(m, db, m.player(db, W, 'discord', '111', 'Kam')[1], done_only=True).endswith('Nothing changed.')
    assert 'Removed sr_gone' in text_of(press(remove['custom_id'])['data']) and listed() == [(CAMPFIRE.id, 1)]


# ---------------------------------------------------------------- linked accounts

def add_rows(uid, rows):
    with m.SessionLocal() as db:
        start = m.now()
        for i, (recipe, want) in enumerate(rows):
            db.add(shop.ShoppingEntry(channel_id=W, canonical_uid=uid, recipe_id=recipe, want=want, added_at=start + i * timedelta(seconds=1)))
        db.commit()


def raw_rows(uid):
    with m.SessionLocal() as db:
        return [(r.recipe_id, r.want) for r in shop._rows(db, W, uid)]


def test_account_linking_keeps_the_targets_entries_and_moves_the_rest_after_them():
    add_rows('src', [(TOILET.id, 9), (CAMPFIRE.id, 7), (STOOL.id, 4)])
    add_rows('dst', [(CAMPFIRE.id, 1), (PLATE.id, 30)])
    with m.SessionLocal() as db:
        q.merge_accounts(m, db, W, 'src', 'dst')                      # the account-linking hook
        db.commit()
    assert raw_rows('dst') == [(CAMPFIRE.id, 1), (PLATE.id, 30), (TOILET.id, 9), (STOOL.id, 4)] and raw_rows('src') == []


def test_account_linking_stays_within_the_cap():
    recipes = [e.id for e in wb.index(m) if e.kind == 'seed'][:shop.MAX_ENTRIES + 3]
    add_rows('dst', [(r, 1) for r in recipes[:shop.MAX_ENTRIES - 1]])
    add_rows('src', [(r, 2) for r in recipes[shop.MAX_ENTRIES - 2:]])
    with m.SessionLocal() as db:
        shop.merge(db, W, 'src', 'dst')
        db.commit()
    merged = raw_rows('dst')
    assert len(merged) == shop.MAX_ENTRIES and merged[-1] == (recipes[shop.MAX_ENTRIES - 1], 2) and raw_rows('src') == []
    assert dict(merged)[recipes[shop.MAX_ENTRIES - 2]] == 1           # the target's amount wins


# ---------------------------------------------------------------- Twitch

def chat(text=''):
    reply = m.shopping('test', 'u', 'Kamex', text, 'twitch').body.decode()
    assert '\n' not in reply and len(reply.encode()) <= 380, reply
    return reply


def test_twitch_shopping_lists_adds_removes_clears_and_buys():
    seed()
    assert chat().startswith('🛒 Your shopping list is empty. !shopping add <recipe> [amount]')
    assert chat('add campfire 2') == '🛒 Added to your shopping list: 2 Campfire (you have 0; 2 batches of 1).'
    assert chat('add crude wood toilet') .startswith('🛒 Added to your shopping list: 1 Crude Wood Toilet')
    assert chat('add campfir 3') == '🔎 “campfir” matched Campfire. 🛒 Shopping list changed: want 3 Campfire (was 2; you have 0; 3 batches of 1).'
    assert chat('add zzqqxx 3') == '🛒 No recipe called "zzqqxx". Nothing changed.'
    assert chat('add campfire 1000') == '🛒 ' + shop.AMOUNT_RULE
    assert chat('add table lamp 2').startswith('🛒 Added to your shopping list: 1 Table Lamp 2')     # a name ending in a number
    price = m.SEED_INDUSTRIES[LUMBER]['buy']
    summary = chat()
    assert summary.startswith('🛒 Shopping 0/3 done: Campfire 0/3 · Crude Wood Toilet 0/1 · Table Lamp 2 0/1 | Missing: ')
    assert '| Next: ' in summary
    assert chat('remove table lamp 2') == '🛒 Removed Table Lamp 2 from your shopping list.'
    assert chat() == (f'🛒 Shopping 0/2 done: Campfire 0/3 · Crude Wood Toilet 0/1 | Missing: 8 Lumber · buy for {8 * price} SC: '
                      '!shopping buy | Next: Gather Lumber ×8 (need 8) | !shopping add <recipe> [amount] · remove <recipe> · clear')
    assert chat('buy') == f'🛒 Buy all missing: 8 Lumber for {8 * price} SC from Seed Industries. !shopping buy confirm buys it.'
    assert chat('buy confirm') == f'🛒 Bought for your shopping list: 8 Lumber for {8 * price} SC. Balance: {10000 - 8 * price} SC.'
    assert chat('buy') == '🛒 Nothing missing on your list can be bought from Seed Industries.'
    assert 'Next: Craft Campfire ×3' in chat()
    assert chat('campfire off') == '🛒 Removed Campfire from your shopping list.'
    assert chat('clear done') == '🧹 Nothing on your shopping list is done yet. Nothing changed.'
    assert chat('clear') == '✖️ Shopping list cleared.' and chat().startswith('🛒 Your shopping list is empty.')


def test_twitch_lite_points_the_shopping_list_to_discord(monkeypatch):
    monkeypatch.setattr(lite, 'ENABLED', True)
    text = client.get('/api/v1/shopping', params={'channel': 'tw-chan', 'uid': 'u1', 'name': 'Nova', 'text': 'add campfire 2'}).text
    assert text.startswith('🔒 Shopping lists is part of the full game on Discord')
    with m.SessionLocal() as db:
        assert db.query(shop.ShoppingEntry).count() == 0 and db.query(m.Player).count() == 0


# ---------------------------------------------------------------- Discord

def three_entries():
    """One done (Campfire), one ready (Crude Wood Toilet) and one blocked (Steel Frame: Tier 3)."""
    citizen(lumber=10)
    give({CAMPFIRE.output: 1})
    add(CAMPFIRE.id, 1)
    add(TOILET.id, 2)
    add(STEEL_FRAME.id, 2)


def test_the_craft_area_opens_the_shopping_list_after_the_goal():
    citizen()
    assert menu.AREAS['craft'][3][:2] == ['goal', 'shopping']
    craft = press(ui.cid('111', 'mn', 'craft'))['data']
    assert find(craft, 'Shopping list')['custom_id'] == ui.cid('111', 'lv')
    empty = press(ui.cid('111', 'lv'))['data']
    assert 'Nothing listed yet' in text_of(empty) and labels(empty) == ['Add recipe…', 'Refresh', 'Back', 'Menu']
    assert empty['embeds'][0]['author']['name'] == '🏠 Menu › 🛠️ Craft › 🛒 Shopping list'


def test_the_discord_screen_has_a_button_by_each_entry_controls_back_and_menu():
    three_entries()
    screen = press(ui.cid('111', 'lv'))['data']
    body = text_of(screen)
    assert '✅ Campfire — have 1 / want 1 · done' in body
    assert '🛠️ Crude Wood Toilet — have 0 / want 2 → 2 batches · ready to craft' in body
    assert '🔒 Steel Frame — have 0 / want 2 → 1 batch · Tier 3' in body
    assert 'Materials · need / have / missing' in body and 'Next Steps · ' in body
    entries = [find(screen, f'{name} ×') for name in ('Campfire', 'Crude Wood Toilet', 'Steel Frame')]
    assert [b['custom_id'] for b in entries] == [ui.cid('111', 'li', e.id) for e in (CAMPFIRE, TOILET, STEEL_FRAME)]
    assert all('|t|' not in b['custom_id'] for b in entries)                    # changing the list spends nothing
    names = labels(screen)
    assert names[3].startswith('Fetch next: ') and names[4].startswith('Buy all missing · ')
    assert names[5:] == ['Add recipe…', 'Clear done', 'Clear list', 'Refresh', 'Back', 'Menu']
    assert last_row(screen)[-2:] == ['Back', 'Menu'] and rows_ok(screen)
    out = v2.convert(ui.tidy(dict(screen)))
    assert assert_valid(out)
    beside = sections(out)
    assert [x['accessory']['label'] for x in beside] == ['Change'] * 3
    assert [x['accessory']['custom_id'] for x in beside] == [b['custom_id'] for b in entries]
    assert beside[0]['components'][0]['content'].startswith('✅ **Campfire** — have 1 / want 1')
    # Clear done and Clear list change only the list.
    cleared = press(find(screen, 'Clear done')['custom_id'])['data']
    assert 'Cleared 1 done entry' in text_of(cleared) and [r for r, _ in listed()] == [TOILET.id, STEEL_FRAME.id]
    assert 'Shopping list cleared' in text_of(press(find(cleared, 'Clear list')['custom_id'])['data']) and listed() == []


def test_ten_long_entries_still_fit_one_discord_card():
    citizen(lumber=3)
    heavy = sorted([e for e in wb.index(m) if e.kind == 'seed' and len(e.inputs) >= 3], key=lambda e: -len(e.name))[:shop.MAX_ENTRIES]
    for e in heavy:
        add(e.id, 998)
    screen = press(ui.cid('111', 'ls', heavy[0].id, 999))['data']             # with a note above the list
    assert rows_ok(screen) and last_row(screen)[-2:] == ['Back', 'Menu'] and find(screen, 'List full').get('disabled')
    fields = screen['embeds'][0]['fields']
    assert [f['name'].split(' · ')[0] for f in fields] == ['Recipes', 'Materials', 'Next Steps']      # nothing cut off
    assert all(f'{e.name}** — have 0 / want' in fields[0]['value'] for e in heavy) and 'more.' in fields[1]['value']
    out = v2.convert(ui.tidy(dict(screen)))
    assert assert_valid(out) and len(sections(out)) >= 5                     # as many entry buttons beside their lines as fit
    with m.SessionLocal() as db:
        line = shop.chat_text(m, db, m.player(db, W, 'discord', '111', 'Kam')[1])
    assert len(line.encode()) <= 380 and ' more | Missing: ' in line and '| Next: ' in line      # Twitch: fewer names, same line


def test_an_entrys_screen_changes_its_amount_or_removes_it():
    citizen(lumber=0)
    add(CAMPFIRE.id, 1)
    item = press(ui.cid('111', 'li', CAMPFIRE.id))['data']
    assert ['Want 1', 'Want 2', 'Want 5', 'Want 10', 'Custom…', 'Remove', 'Recipe', 'Shopping list', 'Back', 'Menu'] == labels(item)
    assert find(item, 'Want 1')['style'] == 1 and rows_ok(item) and assert_valid(v2.convert(ui.tidy(dict(item))))
    assert 'want 5 Campfire (was 1' in text_of(press(find(item, 'Want 5')['custom_id'])['data']) and listed() == [(CAMPFIRE.id, 5)]
    form = press(find(item, 'Custom…')['custom_id'])
    assert form['type'] == 9 and len(form['data']['components']) == 1
    assert 'want 7 Campfire' in text_of(submit(form['data']['custom_id'], '7')['data']) and listed() == [(CAMPFIRE.id, 7)]
    assert shop.AMOUNT_RULE in text_of(submit(form['data']['custom_id'], 'lots')['data']) and listed() == [(CAMPFIRE.id, 7)]
    assert 'Removed Campfire' in text_of(press(find(item, 'Remove')['custom_id'])['data']) and listed() == []


def submit(custom_id, value, amount=None, uid='111'):
    boxes = [{'type': 1, 'components': [{'type': 4, 'custom_id': 'value', 'value': value}]}]
    if amount is not None:
        boxes.append({'type': 1, 'components': [{'type': 4, 'custom_id': 'amount', 'value': amount}]})
    payload = {'type': 5, 'data': {'custom_id': custom_id, 'components': boxes},
               'member': {'user': {'id': uid, 'username': 'Kam'}, 'permissions': '0'}, 'message': {'flags': 64}}
    return ui.handle_modal(m, payload)


def test_the_add_recipe_form_takes_a_name_and_an_amount():
    citizen(lumber=0)
    screen = press(ui.cid('111', 'lv'))['data']
    form = press(find(screen, 'Add recipe…')['custom_id'])
    assert form['type'] == 9 and [r['components'][0]['custom_id'] for r in form['data']['components']] == ['value', 'amount']
    assert form['data']['components'][1]['components'][0]['required'] is False
    md = form['data']['custom_id']
    added = text_of(submit(md, 'campfir', '3')['data'])
    assert '“campfir” matched Campfire' in added and 'Added to your shopping list: 3 Campfire' in added
    assert 'Added to your shopping list: 1 Crude Wood Toilet' in text_of(submit(md, 'crude wood toilet', '')['data'])    # blank: one batch
    assert 'No recipe called "zzqqxx". Nothing changed.' in text_of(submit(md, 'zzqqxx', '2')['data'])
    assert shop.AMOUNT_RULE in text_of(submit(md, 'campfire', '1000')['data'])
    assert shop.AMOUNT_RULE in text_of(submit(md, 'campfire', '-2')['data'])
    assert listed() == [(CAMPFIRE.id, 3), (TOILET.id, 1)]


def test_the_recipe_preview_adds_the_recipe_to_the_list(monkeypatch):
    citizen(lumber=0)
    preview = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))['data']
    assert last_row(preview) == ['Add to list', 'Back', 'Menu'] and rows_ok(preview)
    assert len([r for r in preview['components'][1]['components']]) == 5          # the Favourite row is unchanged
    added = press(find(preview, 'Add to list')['custom_id'])['data']
    assert 'Added to your shopping list: 1 Campfire' in text_of(added) and 'Choose how many you want to have' in text_of(added)
    assert 'Want 5' in labels(added) and listed() == [(CAMPFIRE.id, 1)]
    again = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))['data']
    on = find(again, 'On shopping list')
    assert on['label'] == 'On shopping list · want 1' and on['custom_id'] == ui.cid('111', 'li', CAMPFIRE.id)
    assert 'Already on your shopping list' in text_of(press(ui.cid('111', 'la', CAMPFIRE.id))['data']) and listed() == [(CAMPFIRE.id, 1)]
    # A preview with every button (Unlock in the first row) still fits, and so does the /make reply.
    station = press(ui.cid('111', 'wr', PLATE.id, PLATE.category, 1, ''))['data']
    assert labels(station)[0].startswith('Unlock ') and rows_ok(station) and 'Add to list' in labels(station)
    assert assert_valid(v2.convert(ui.tidy(dict(station))))
    sent = []
    monkeypatch.setattr(m.discord_deferred, 'edit_original', lambda app, token, data: sent.append(data) or True)
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    reply = _deferred_reply(monkeypatch, 'make', {'recipe': 'Campfire'}, sent)
    assert 'On shopping list · want 1' in labels(reply) and rows_ok(reply)
    reply = _deferred_reply(monkeypatch, 'make', {'recipe': 'Crude Wood Toilet'}, sent)
    assert 'Add to list' in labels(reply) and rows_ok(reply)


# ---------------------------------------------------------------- the goal is unchanged

# The goal walkthrough for Ore Scanner (Metalworking Bench and Basic Anvil owned, 1000 SC), captured from the code
# before the planner was shared with the shopping list (e1b2583): (mark, name, detail, button, action, view).
ORE_SCANNER_STEPS = [
    ('✅', 'Mine Hematite Ore ×3', 'need 2 · runs as a queue', 'Mine', {'do': 'queue', 'task': 'mine:sd_559614005', 'count': 3}, None),
    ('✅', 'Gather Lumber ×3', 'need 3 · runs as a queue', 'Gather', {'do': 'queue', 'task': 'gather:sd_1000004', 'count': 3}, None),
    ('✅', 'Gather Stone ×4', 'need 4 · runs as a queue', 'Gather', {'do': 'queue', 'task': 'gather:sd_1566791299', 'count': 4}, None),
    ('✅', 'Gather Clay ×1', 'need 1 · runs as a queue', 'Gather', {'do': 'queue', 'task': 'gather:sd_1663615028', 'count': 1}, None),
    ('🔒', 'Reach Harvesting Lv 3', 'you are Lv 1 · each training task gives practice', 'Train', None, ('mp', 'trainskill', '=harvesting')),
    ('❌', 'Mine Argentite Ore', 'need 1 · after Harvesting Lv 3', 'Mine', None, ('mp', 'mine', '=sd_1035602738')),
    ('❌', 'Craft Raw Iron ×2', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_86276024', 'materials', 1, '')),
    ('❌', 'Craft Iron Ingot ×1', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_535171027', 'materials', 1, '')),
    ('❌', 'Craft Iron Plate ×1', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_1018791011', 'parts', 1, '')),
    ('❌', 'Craft Basic Workbench', 'the machine for Masonry Bench: owning it opens its workstation · after the steps above', 'Recipe', None,
     ('wr', 'sr_1000723349', 'machines', 1, '')),
    ('❌', 'Craft Carpentry Station', 'the machine for Wood Planks: owning it opens its workstation · after the steps above', 'Recipe', None,
     ('wr', 'sr_1934414769', 'machines', 1, '')),
    ('❌', 'Craft Wood Planks ×1', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_509168879', 'parts', 1, '')),
    ('❌', 'Craft Masonry Bench', 'the machine for Glass: owning it opens its workstation · after the steps above', 'Recipe', None,
     ('wr', 'sr_1315724877', 'machines', 1, '')),
    ('❌', 'Craft Stone Dust ×1', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_1234567892', 'materials', 1, '')),
    ('🔒', 'Reach personal Tier 2', 'craft 25 more batches of anything made from ingredients · 0/25', 'Craft', None, ('wc', 'ready', 1, '')),
    ('✅', 'Gather Murky Water (1000ml) ×8', 'need 8 · runs as a queue', 'Gather', {'do': 'queue', 'task': 'gather:sd_817726320', 'count': 8}, None),
    ('❌', 'Do Water Treatment ×8', 'practises Processing to Lv 2 (5 more practice) · after the steps above', 'Train', None,
     ('mp', 'trainskill', '=processing')),
    ('❌', 'Craft Glass ×1', 'a part for your goal · after the steps above', 'Recipe', None, ('wr', 'sr_1533973357', 'materials', 1, '')),
    ('❌', 'Craft Ore Scanner', 'the goal · after the steps above', 'Recipe', None, ('wr', 'ore_scanner', 'equipment', 1, '')),
]


def test_the_goal_walkthrough_is_the_same_as_before_the_planner_was_shared():
    citizen(lumber=0)
    give(MACHINES)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        extras.set_goal(m, db, p, 'ore_scanner')
        db.commit()
        e, steps = extras.walkthrough(m, db, p)
        assert e.id == 'ore_scanner'
        assert [(st['mark'], st['name'], st['detail'], st['label'], st['action'], st['view']) for st in steps] == ORE_SCANNER_STEPS
        assert all(st['cost'] == 0 for st in steps) and [(st['name'], st['size']) for st in steps if st['size']] == [('Reach Harvesting Lv 3', 3), ('Do Water Treatment ×8', 8)]
        assert extras.goal_text(m, db, p, 'twitch') == ('🎯 Goal Ore Scanner 0/3 ingredients | Next: Mine Hematite Ore ×3 (need 2) | '
                                                       'Then: Gather Lumber ×3 → Gather Stone ×4 → Gather Clay ×1 | !target clear')
        # The goal and a one-entry shopping list share the planner: the same crafts and raw materials.
        ctx = wb.Context(m, db, p)
        crafts, raw, opened = extras.full_plan(ctx, e)
        listed_crafts, listed_raw, listed_opened, _, _ = extras.list_plan(ctx, [(e, 1)])
        assert [(c.id, n) for c, n, _ in crafts] == [(c.id, n) for c, n, _ in listed_crafts] and raw == listed_raw and opened == listed_opened
