"""Keep levels: how many of an item bulk and automatic selling always leaves, and restocking back up to it."""
import json
from types import SimpleNamespace
import pytest
from test_colony import m, reset, seed, client
from test_task_queue import advance
from test_workbench_ui import citizen, press, controls, find, W, LUMBER, CAMPFIRE
from test_buttons_everywhere import submit
from test_layout_v2 import assert_valid
from app import ui, qol, extras, keep_levels as keep, seed_content as s, task_queue as q, queue_notifications as n
from app import layout_v2 as v2, twitch_lite as lite, workbench as wb

IRON_PLATE = s.key('Iron Plate')
STONE_DUST = s.key('Stone Dust')
STONE = s.key('Stone')
GLASS = s.key('Glass')
ARGENTITE = s.key('Argentite Ore')


def player(uid='111'):
    db = m.SessionLocal()
    return db, m.player(db, W, 'discord', uid, 'Kam')[1]


def give(key, amount, uid='111'):
    with m.SessionLocal() as db:
        m.material_change(db, m.player(db, W, 'discord', uid, 'Kam')[1], key, amount)
        db.commit()


def set_keep(key, amount, uid='111'):
    with m.SessionLocal() as db:
        text = keep.set_level(db, m.player(db, W, 'discord', uid, 'Kam')[1], key, amount)
        db.commit()
        return text


def have(key, uid='111'):
    with m.SessionLocal() as db:
        return m.material_amount(db, m.player(db, W, 'discord', uid, 'Kam')[1], key)


def kept(key, uid='111'):
    with m.SessionLocal() as db:
        return keep.keep_for(db, m.player(db, W, 'discord', uid, 'Kam')[1], key)


def rows_of(uid='111'):
    """A Discord citizen's keep levels."""
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid, 'Kam')[1]
        return keep.levels(db, p.channel_id, p.twitch_uid)


def raw_rows(canonical):
    with m.SessionLocal() as db:
        return keep.levels(db, W, canonical)


def sc(uid='111'):
    with m.SessionLocal() as db:
        return m.player(db, W, 'discord', uid, 'Kam')[1].sc


def labels(data):
    return [c.get('label') or c.get('placeholder', '') for c in controls(data)]


def text_of(data):
    return json.dumps(data, ensure_ascii=False)


def queue_row(channel=W, uid=None):
    with m.SessionLocal() as db:
        rows = db.query(q.TaskQueue).filter(q.TaskQueue.channel_id == channel).all()
        return rows[0] if rows else None


# ---------------------------------------------------------------- setting levels

def test_set_update_and_clear_a_keep_level():
    citizen()
    assert set_keep(IRON_PLATE, 30) == '🛡️ Keep level set: always keep 30 Iron Plate (you have 0, 30 short).'
    assert kept(IRON_PLATE) == 30
    assert 'already keep 30 Iron Plate. Nothing changed.' in set_keep(IRON_PLATE, 30)
    assert 'Keep level changed: always keep 50 Iron Plate (was 30' in set_keep(IRON_PLATE, 50)
    assert kept(IRON_PLATE) == 50
    assert 'Keep level removed' in set_keep(IRON_PLATE, 0)
    assert kept(IRON_PLATE) == 0 and rows_of('111') == {}
    assert set_keep(IRON_PLATE, 0) == '🛡️ Iron Plate has no keep level. Nothing changed.'


@pytest.mark.parametrize('amount', [-1, 10000, '2.5', 'abc', '', None])
def test_invalid_amounts_change_nothing(amount):
    citizen()
    set_keep(IRON_PLATE, 30)
    assert set_keep(IRON_PLATE, amount) == '🛡️ ' + keep.AMOUNT_RULE
    assert kept(IRON_PLATE) == 30


def test_unknown_and_non_catalog_items_and_the_cap():
    citizen()
    assert 'not a catalog item' in set_keep('nonsense_item', 5) and 'Nothing changed' in set_keep('cargo', 5)
    assert 'Cargo is not a catalog item' in set_keep('cargo', 5)
    assert 'Choose an item first' in set_keep('', 5)
    assert rows_of('111') == {}
    chat = m.keep_level(W, 'tw', 'Kam', 'zzqqxx 5', 'twitch').body.decode()
    assert chat.startswith('🛡️ No item called "zzqqxx"') and 'Nothing changed' in chat
    assert 'not a catalog item' in m.keep_level(W, 'tw', 'Kam', 'cargo 5', 'twitch').body.decode()
    assert 'not a catalog item' in m.keep_level(W, 'tw', 'Kam', 'cargo', 'twitch').body.decode()
    for bad in ('iron plate 10000', 'iron plate -3', 'iron plate 2.5'):
        assert 'whole number from 1 to 9999' in m.keep_level(W, 'tw', 'Kam', bad, 'twitch').body.decode(), bad
    keys = sorted(s.ACTIVE)[:keep.MAX_LEVELS + 1]
    for key in keys[:-1]:
        assert 'Keep level set' in set_keep(key, 1)
    assert set_keep(keys[-1], 1) == (f'🛡️ You already have 25 keep levels. Remove one before adding {m.resource_name(keys[-1])}. '
                                     'Nothing changed.')
    assert len(rows_of('111')) == keep.MAX_LEVELS and keys[-1] not in rows_of('111')
    assert 'changed' in set_keep(keys[0], 2)                      # changing one at the cap still works


def test_an_alias_and_its_catalog_name_are_one_keep_level():
    citizen()
    assert 'always keep 30 Iron Plate' in set_keep('alloy_plate', 30)
    assert kept(IRON_PLATE) == 30 and kept('alloy_plate') == 30
    assert 'changed' in set_keep(IRON_PLATE, 40)
    assert rows_of('111') == {IRON_PLATE: 40}
    m.keep_level(W, '111', 'Kam', 'Alloy Plate 20', 'discord')
    assert rows_of('111') == {IRON_PLATE: 20}


# ---------------------------------------------------------------- bulk and automatic selling

@pytest.mark.parametrize('level,sold', [(20, 30), (50, 0), (80, 0)])
def test_sell_all_leaves_the_keep_level(level, sold):
    citizen(lumber=50)
    set_keep(LUMBER, level)
    before = sc()
    price = qol.sell_price(LUMBER)
    receipt = m.sell_all_items(W, '111', 'Kam', 'lumber', 'discord').body.decode()
    assert have(LUMBER) == 50 - sold and sc() == before + sold * price
    if sold:
        assert f'sold {sold} Lumber to Seed Industries for {sold * price} SC ({price} each), keeping {level} (your keep level)' in receipt
        assert 'Sale undone' in m.undo_sale(W, '111', 'Kam', 'discord').body.decode()      # undo works as before
        assert have(LUMBER) == 50 and sc() == before
    else:
        assert f'Nothing to sell: you have 50 Lumber and your keep level keeps {level}' in receipt


def test_sell_all_without_a_keep_level_still_sells_everything():
    citizen(lumber=50)
    assert 'sold all 50 Lumber' in m.sell_all_items(W, '111', 'Kam', 'lumber', 'discord').body.decode()
    assert have(LUMBER) == 0


def test_clearout_uses_the_keep_level_instead_of_twenty_either_way():
    citizen(lumber=0)
    for key in (STONE_DUST, GLASS, STONE):
        give(key, 45)
    set_keep(STONE_DUST, 5)          # below the usual 20
    set_keep(GLASS, 30)              # above it
    preview = m.clearout(W, '111', 'Kam', '', 'discord').body.decode()
    assert 'or beyond your keep level where you set one' in preview
    assert 'Stone Dust ×40' in preview and 'keeps 5 (your keep level)' in preview
    assert 'Glass ×15' in preview and 'keeps 30 (your keep level)' in preview
    assert 'Stone ×25' in preview                                   # no keep level: still 20
    db, p = player()
    with db:
        assert '(or your keep level)' in qol.clearout(db, p, 'twitch')      # the Twitch preview says so too
    m.clearout(W, '111', 'Kam', 'confirm', 'discord')
    assert (have(STONE_DUST), have(GLASS), have(STONE)) == (5, 30, 20)


def test_clearout_still_protects_favourite_ingredients_below_a_keep_level():
    citizen(lumber=50)
    give(STONE_DUST, 45)
    db, p = player()
    with db:
        qol.set_favorite(db, p, CAMPFIRE.id, True)
        db.commit()
    set_keep(LUMBER, 5)
    preview = m.clearout(W, '111', 'Kam', '', 'discord').body.decode()
    assert 'Lumber' not in preview.split('WOULD SELL')[1]
    m.clearout(W, '111', 'Kam', 'confirm', 'discord')
    assert have(LUMBER) == 50 and have(STONE_DUST) == qol.CLEAROUT_RESERVE


def test_autosell_after_a_queue_leaves_the_keep_level():
    citizen(lumber=10)
    db, p = player()
    with db:
        extras.toggle_autosell(db, p, LUMBER)
        db.commit()
    set_keep(LUMBER, 8)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '1', 'discord')
    advance()
    assert queue_row().state == 'completed'
    assert have(LUMBER) == 8                                          # 10 + 1 gathered, 3 auto-sold
    with m.SessionLocal() as db:
        assert 'keeping 8 (your keep level)' in db.query(n.Notice).one().content


def test_autosell_skips_an_item_at_its_keep_level():
    citizen(lumber=10)
    db, p = player()
    with db:
        extras.toggle_autosell(db, p, LUMBER)
        db.commit()
    set_keep(LUMBER, 50)
    db, p = player()
    with db:
        assert extras.autosell_after_queue(db, p) == [] and m.material_amount(db, p, LUMBER) == 10


def test_routine_sell_step_leaves_the_keep_level():
    citizen(lumber=10)
    set_keep(LUMBER, 4)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '1', 'discord')
    db, p = player()
    with db:
        extras.add_step(db, p, {'sell': LUMBER})
        db.commit()
    advance()                                                          # completes, then runs the plan's "sell all" step
    assert have(LUMBER) == 4
    with m.SessionLocal() as db:
        assert 'keeping 4 (your keep level)' in db.query(n.Notice).one().content


def test_selling_a_chosen_amount_is_not_limited():
    citizen(lumber=10)
    set_keep(LUMBER, 30)
    assert 'sold 6 Lumber' in m.seed_industries(W, '111', 'Kam', 'sell', 'lumber', 6, 'discord').body.decode()
    assert have(LUMBER) == 4


# ---------------------------------------------------------------- restock

def shortfall(key, uid='111'):
    db, p = player(uid)
    with db:
        return next(r for r in keep.shortfalls(db, p) if r['key'] == key)


def test_restock_a_gathered_item_starts_an_ordinary_queue_once():
    citizen(lumber=0)
    set_keep(LUMBER, 5)
    r = shortfall(LUMBER)
    assert (r['kind'], r['task'], r['attempts'], r['short']) == ('queue', 'gather:' + LUMBER, 5, 5)
    text = keep.restock(W, '111', 'Kam', 'discord', LUMBER)
    assert text.startswith('🛡️ Restocking Lumber (have 0 / keep 5): ') and 'TASK QUEUE' in text
    row = queue_row()
    assert (row.task, row.total, row.state) == ('gather:' + LUMBER, 5, 'running')
    busy = keep.restock(W, '111', 'Kam', 'discord', LUMBER)
    assert busy.startswith('⏱️ Your queue is still running (Gather Lumber)') and busy.endswith('Nothing changed.')
    assert queue_row().total == 5 and queue_row().remaining == 5


def test_restock_respects_the_ten_attempt_queue_maximum():
    citizen(lumber=0)
    set_keep(LUMBER, 30)
    r = shortfall(LUMBER)
    assert r['attempts'] == 10 and r['capped']
    assert '10 is the queue maximum' in keep.route_text(r)
    keep.restock(W, '111', 'Kam', 'discord', LUMBER)
    assert queue_row().total == 10


def test_restock_a_crafted_item_starts_the_craft_queue():
    citizen(lumber=10)
    set_keep(CAMPFIRE.output, 2)
    r = shortfall(CAMPFIRE.output)
    assert r['kind'] == 'recipe' and r['recipe'] == CAMPFIRE.id and not r['blocked'] and (r['batches'], r['count']) == (2, 2)
    text = keep.restock(W, '111', 'Kam', 'discord', CAMPFIRE.output)
    assert 'TASK QUEUE' in text
    row = queue_row()
    assert row.task == 'make:' + CAMPFIRE.id and row.total == 2 and row.state == 'running'


def test_restock_queues_only_the_batches_the_ingredients_cover():
    citizen(lumber=4)                                                  # 2 Lumber a Campfire: 2 batches of the 5 needed
    set_keep(CAMPFIRE.output, 5)
    r = shortfall(CAMPFIRE.output)
    assert not r['blocked'] and (r['batches'], r['count'], r['more']) == (5, 2, 'Lumber')
    text = keep.restock(W, '111', 'Kam', 'discord', CAMPFIRE.output)
    assert 'ingredients cover 2 of 5 batches; the rest needs more Lumber' in text and 'TASK QUEUE' in text
    row = queue_row()
    assert row.task == 'make:' + CAMPFIRE.id and row.total == 2


def no_tickets(data):
    return all('|t|' not in str(c.get('custom_id')) and c.get('style') != 3 for c in controls(data))


def test_restock_never_starts_a_craft_whose_ingredients_are_missing():
    citizen(lumber=0)
    set_keep(CAMPFIRE.output, 2)
    r = shortfall(CAMPFIRE.output)
    assert r['blocked'] == '❌ need 2 Lumber' and r['view'] == ('fm', CAMPFIRE.id, 2)
    text = keep.restock(W, '111', 'Kam', 'discord', CAMPFIRE.output)
    assert text.startswith('🛡️ Restock Campfire is blocked: craft Campfire ×2 · ❌ need 2 Lumber — fetch the ingredients first.')
    assert 'FETCH INGREDIENTS' in text and text.endswith('Nothing changed.') and queue_row() is None
    advance()
    assert queue_row() is None
    screen = press(ui.cid('111', 'kv'))['data']
    assert 'need 2 Lumber — fetch the ingredients first' in text_of(screen['embeds'])
    assert 'Restock Campfire' not in labels(screen) and no_tickets(screen)        # no one-time ticket, nothing green
    fetch = find(screen, 'Fetch for Campfire')
    assert fetch['custom_id'] == ui.cid('111', 'fm', CAMPFIRE.id, 2) and fetch['style'] == 2
    assert 'Fetch Ingredients · Campfire ×2 batches' in text_of(press(fetch['custom_id'])['data']['embeds'])   # the existing fetch screen


def test_restock_never_starts_a_craft_at_a_locked_workstation():
    citizen(lumber=0)
    set_keep(IRON_PLATE, 5)
    r = shortfall(IRON_PLATE)
    e = wb.entry(r['recipe'])
    assert r['blocked'] == '🔑 unlock Metalworking Bench 15 SC' and r['view'] == ('wr', e.id, e.category, 1, '')
    text = keep.restock(W, '111', 'Kam', 'discord', IRON_PLATE)
    assert text.startswith('🛡️ Restock Iron Plate is blocked: craft Iron Plate ×1 · 🔑 unlock Metalworking Bench 15 SC — open the recipe to unlock.')
    assert text.endswith('Nothing changed.') and queue_row() is None
    screen = press(ui.cid('111', 'kv'))['data']
    assert 'Restock Iron Plate' not in labels(screen) and no_tickets(screen)
    recipe = find(screen, 'Iron Plate recipe')
    assert recipe['custom_id'] == ui.cid('111', 'wr', e.id, e.category, 1, '') and recipe['style'] == 2
    assert any(label.startswith('Unlock Metalworking Bench') for label in labels(press(recipe['custom_id'])['data']))


def test_restock_never_mines_a_rare_ore_without_a_mineral_extractor():
    citizen(lumber=0)
    set_keep(ARGENTITE, 3)
    r = shortfall(ARGENTITE)
    assert r['kind'] == 'queue' and r['blocked'] == '🔒 rare ores need a Mineral Extractor in your bag' and r['view'] is None
    text = keep.restock(W, '111', 'Kam', 'discord', ARGENTITE)
    assert text.startswith('🛡️ Restock Argentite Ore is blocked: Mine ×10') and 'Mineral Extractor' in text
    assert text.endswith('Nothing changed.') and queue_row() is None
    screen = press(ui.cid('111', 'kv'))['data']
    assert not any('Argentite' in label for label in labels(screen)[1:]) and no_tickets(screen)   # no button, only the text


def test_a_blocked_restock_leaves_a_running_queue_alone():
    citizen(lumber=0)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '3', 'discord')
    set_keep(IRON_PLATE, 5)
    assert keep.restock(W, '111', 'Kam', 'discord', IRON_PLATE).endswith('Nothing changed.')
    row = queue_row()
    assert (row.task, row.total, row.remaining) == ('gather:' + LUMBER, 3, 3)


def test_low_needs_alone_do_not_block_a_restock():
    citizen(lumber=0)
    with m.SessionLocal() as db:
        m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1]).energy = 0
        db.commit()
    set_keep(LUMBER, 5)
    assert shortfall(LUMBER)['blocked'] == ''
    keep.restock(W, '111', 'Kam', 'discord', LUMBER)
    row = queue_row()
    assert row.task == 'gather:' + LUMBER and row.total == 5           # it waits for Energy, then carries on by itself


def test_restock_without_an_item_skips_blocked_rows():
    citizen(lumber=0)
    set_keep(IRON_PLATE, 5)                                             # blocked, and first by name
    db, p = player()
    with db:
        assert keep.restock_plan(db, p, 'twitch').startswith('🛡️ Restock Iron Plate: have 0 / keep 5, short 5 → craft Iron Plate ×1 · 🔑')
    assert 'is blocked' in keep.restock(W, '111', 'Kam', 'discord') and queue_row() is None   # only blocked rows: it explains
    set_keep(LUMBER, 5)
    db, p = player()
    with db:
        assert keep.restock_plan(db, p, 'twitch').startswith('🛡️ Restock Lumber: have 0 / keep 5, short 5 → Gather ×5. !keep restock go')
        assert keep._pick(keep.shortfalls(db, p))['key'] == LUMBER
    assert keep.restock(W, '111', 'Kam', 'discord').startswith('🛡️ Restocking Lumber')
    assert queue_row().task == 'gather:' + LUMBER


def test_twitch_restock_go_on_a_blocked_row_points_to_fetching():
    seed()
    reply = chat('campfire 2')
    assert 'always keep 2 Campfire' in reply
    blocked = chat('restock go')
    assert blocked.startswith('🛡️ Restock Campfire is blocked: craft Campfire ×2 · ❌ need 2 Lumber — fetch the ingredients first.')
    assert '!fetchgo Campfire 2 starts it.' in blocked and blocked.endswith('Nothing changed.')
    with m.SessionLocal() as db:
        assert db.get(q.TaskQueue, ('test', 'u')) is None


def test_restock_a_bought_item_buys_the_shortfall_only_with_enough_sc():
    citizen(lumber=0)
    give(GLASS, 2)
    set_keep(GLASS, 10)
    r = shortfall(GLASS)
    assert (r['kind'], r['short']) == ('buy', 8)
    cost = r['price'] * 8
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', '111', 'Kam')[1].sc = cost - 1
        db.commit()
    poor = keep.restock(W, '111', 'Kam', 'discord', GLASS)
    assert poor == f'🪙 Restocking 8 Glass costs {cost} SC and you have {cost - 1} SC: earn 1 more SC first. Nothing spent.'
    assert have(GLASS) == 2 and sc() == cost - 1
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', '111', 'Kam')[1].sc = 1000
        db.commit()
    bought = keep.restock(W, '111', 'Kam', 'discord', GLASS)
    assert 'bought 8 Glass' in bought and have(GLASS) == 10 and sc() == 1000 - cost
    assert queue_row() is None


def none_route_item():
    db, p = player()
    with db:
        ctx = wb.Context(db, p)
        return next(k for k in sorted(s.ACTIVE) if not k.startswith('fest_') and k not in s.GATHER
                    and qol.fetch_routes(ctx, SimpleNamespace(inputs={k: 1}), 1)[0]['kind'] == 'none')


def test_restock_explains_where_an_item_comes_from_when_it_cannot_be_started():
    citizen()
    key = none_route_item()
    set_keep(key, 3)
    text = keep.restock(W, '111', 'Kam', 'discord', key)
    assert 'cannot be restocked automatically' in text and m.material_source(key, 'discord') in text and text.endswith('Nothing changed.')
    assert have(key) == 0 and queue_row() is None


def test_restock_with_nothing_short():
    citizen(lumber=10)
    assert 'no keep levels yet' in keep.restock(W, '111', 'Kam', 'discord')
    set_keep(LUMBER, 5)
    assert 'Everything is at or above its keep level' in keep.restock(W, '111', 'Kam', 'discord')
    assert 'at or above your keep level of 5' in keep.restock(W, '111', 'Kam', 'discord', LUMBER)
    assert 'Glass has no keep level' in keep.restock(W, '111', 'Kam', 'discord', GLASS)
    assert queue_row() is None


# ---------------------------------------------------------------- linked accounts

def add_levels(uid, levels):
    with m.SessionLocal() as db:
        for key, amount in levels.items():
            db.add(keep.KeepLevel(channel_id=W, canonical_uid=uid, item_key=key, amount=amount))
        db.commit()


def test_account_linking_keeps_the_targets_levels_and_moves_the_rest():
    add_levels('dst', {IRON_PLATE: 30, LUMBER: 5})
    add_levels('src', {IRON_PLATE: 99, GLASS: 10})
    with m.SessionLocal() as db:
        q.merge_accounts(db, W, 'src', 'dst')                          # the account-linking hook
        db.commit()
    assert raw_rows('dst') == {IRON_PLATE: 30, LUMBER: 5, GLASS: 10} and raw_rows('src') == {}


def test_account_linking_stays_within_the_cap():
    target = sorted(s.ACTIVE)[:keep.MAX_LEVELS - 1]
    source = sorted(s.ACTIVE)[keep.MAX_LEVELS - 1:keep.MAX_LEVELS + 2]
    add_levels('dst', {k: 1 for k in target})
    add_levels('src', {k: 2 for k in source})
    with m.SessionLocal() as db:
        keep.merge(db, W, 'src', 'dst')
        db.commit()
    merged = raw_rows('dst')
    assert len(merged) == keep.MAX_LEVELS and merged[source[0]] == 2 and raw_rows('src') == {}


# ---------------------------------------------------------------- Twitch

def chat(text=''):
    reply = m.keep_level('test', 'u', 'Kamex', text, 'twitch').body.decode()
    assert '\n' not in reply and len(reply.encode()) <= 380, reply
    return reply


def test_twitch_keep_lists_sets_clears_and_restocks():
    seed()
    assert chat().startswith('🛡️ No keep levels yet. !keep <item> <amount>')
    assert chat('lumber 5') == '🛡️ Keep level set: always keep 5 Lumber (you have 0, 5 short).'
    assert 'always keep 30 Iron Plate' in chat('iron plate 30')
    listed = chat()
    assert listed.startswith('🛡️ Keep 2/25: Iron Plate 0/30⚠️ · Lumber 0/5⚠️') and 'Short: Iron Plate, Lumber → !keep restock' in listed
    assert chat('iron plate') == '🛡️ Iron Plate: have 0 / keep 30 ⚠️ | !keep Iron Plate 0 removes it.'
    assert 'Keep level removed' in chat('iron plate 0')
    assert 'Keep level removed' in chat('lumber off') and 'No keep levels yet' in chat()
    chat('lumber 5')
    assert 'Keep level removed' in chat('remove lumber')
    chat('lumber 5')
    assert chat('restock') == '🛡️ Restock Lumber: have 0 / keep 5, short 5 → Gather ×5. !keep restock go starts it.'
    started = chat('restock go')
    assert started.startswith('🛡️ Restocking Lumber (have 0 / keep 5): ')
    with m.SessionLocal() as db:
        row = db.get(q.TaskQueue, ('test', 'u'))
        assert row.task == 'gather:' + LUMBER and row.total == 5
    assert chat('restock go').startswith('⏱️ Your queue is still running')
    assert 'Which item?' in chat('30')


def test_twitch_lite_points_keep_levels_to_discord(monkeypatch):
    monkeypatch.setattr(lite, 'ENABLED', True)
    text = client.get('/api/v1/keep', params={'channel': 'tw-chan', 'uid': 'u1', 'name': 'Nova', 'text': 'lumber 5'}).text
    assert text.startswith('🔒 Keep levels is part of the full game on Discord')
    with m.SessionLocal() as db:
        assert db.query(keep.KeepLevel).count() == 0


# ---------------------------------------------------------------- Discord

def last_row(data):
    return [c['label'] for c in [r for r in data['components'] if r.get('components')][-1]['components']]


def test_discord_keep_screen_select_amounts_custom_remove_and_restock():
    citizen(lumber=10)
    set_keep(LUMBER, 20)
    more = press(ui.cid('111', 'mn', 'trade', 'more'))['data']                      # Bag & Shop > More > Always keep
    assert 'Always keep' in labels(more)
    screen = press(find(more, 'Always keep')['custom_id'])['data']
    body = text_of(screen['embeds'])
    assert 'Keep Levels · 1/25' in body and '⚠️ Lumber — have 10 / keep 20' in body and 'Gather ×10' in body
    select = screen['components'][0]['components'][0]
    assert select['custom_id'] == ui.cid('111', 'ki') and LUMBER in [o['value'] for o in select['options']]
    assert 'Restock Lumber' in labels(screen) and last_row(screen)[-2:] == ['Back', 'Menu']
    assert_valid(v2.convert(ui.tidy(dict(screen))))

    item = press(select['custom_id'], values=[LUMBER])['data']
    assert {'Keep 10', 'Keep 25', 'Keep 50', 'Keep 100', 'Custom…', 'Remove', 'Restock Lumber'} <= set(labels(item))
    assert last_row(item)[-2:] == ['Back', 'Menu']
    changed = press(find(item, 'Keep 25')['custom_id'])['data']
    assert 'always keep 25 Lumber (was 20' in text_of(changed) and kept(LUMBER) == 25

    form = press(ui.cid('111', 'mo', 'keep', LUMBER))
    assert form['type'] == 9
    assert 'always keep 40 Lumber' in text_of(submit(form['data']['custom_id'], '40')['data']) and kept(LUMBER) == 40
    assert 'whole number from 1 to 9999' in text_of(submit(form['data']['custom_id'], 'lots')['data']) and kept(LUMBER) == 40

    item = press(select['custom_id'], values=[LUMBER])['data']
    restock = find(item, 'Restock Lumber')['custom_id']
    result = press(restock)['data']
    assert 'Restocking Lumber' in text_of(result) and queue_row().task == 'gather:' + LUMBER
    assert 'already used' in press(restock)['data']['content']        # a one-time ticket
    removed = press(find(item, 'Remove')['custom_id'])['data']
    assert 'Keep level removed' in text_of(removed) and kept(LUMBER) == 0


def test_discord_sell_all_mentions_the_keep_level():
    citizen(lumber=10)
    set_keep(LUMBER, 4)
    amounts = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    assert 'Always keep is 4: Sell all leaves that many' in text_of(amounts)
    press(find(amounts, 'Sell all 6')['custom_id'])                                    # the whole stack minus the keep level
    assert have(LUMBER) == 4


def test_discord_buy_restock_is_greyed_out_without_enough_sc():
    citizen(lumber=0)
    set_keep(GLASS, 10)
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', '111', 'Kam')[1].sc = 0
        db.commit()
    screen = press(ui.cid('111', 'kv'))['data']
    b = find(screen, 'Restock Glass')
    assert b.get('disabled') and '|t|' not in b['custom_id']
