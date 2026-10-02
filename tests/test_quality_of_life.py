"""Status, favourites, Ready now, fetching, follow-up queues, alerts, recovery, selling and search."""
import asyncio
import json
import re
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
from test_colony import m, reset, seed
from test_task_queue import enqueue, advance, ORE
from test_workbench_ui import citizen, press, controls, find, W, LUMBER, CAMPFIRE
from app import ui, qol, workbench as wb, seed_content as s, task_queue as q, queue_notifications as n
from app import discord_queue_worker as w

STONE_DUST = s.key('Stone Dust')


def player(uid='111'):
    db = m.SessionLocal()
    return db, m.player(db, W, 'discord', uid, 'Kam')[1]


def set_life(uid='111', channel=W, provider='discord', **values):
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, 'Kam')[1]
        life = m.life_state(db, p)
        for key, value in values.items():
            setattr(life, key, value)
        db.commit()


def labels(data):
    return [c.get('label', '') for c in controls(data)]


# ---------------------------------------------------------------- status

def test_status_shows_needs_queue_ready_recipes_and_next_step():
    citizen()
    text = m.status_view(W, '111', 'Kam', 'discord').body.decode()
    for heading in ('NEEDS', 'QUEUE', 'READY TO CRAFT', 'NEXT STEP', 'SETTINGS'):
        assert heading in text
    assert 'Campfire' in text and 'No queue yet' in text
    chat = m.status_view(W, '111', 'Kam', 'twitch').body.decode()
    assert len(chat.encode()) <= 380 and 'Queue:' in chat


def test_status_panel_offers_recover_only_when_blocked():
    citizen()
    panel = ui.slash_panel(m, 'status', '111', 'Kam', {}, '📊 STATUS\nbody')
    assert {'Refresh', 'Ready now', 'Favourites', 'Workbench', 'Queue'} <= set(labels(panel))
    assert 'Recover now' not in labels(panel)
    set_life(energy=5)
    panel = press(ui.cid('111', 'st'))
    assert 'Recover now' in labels(panel['data'])
    assert 'Passive recovery reaches 20' in json.dumps(panel['data']['embeds'][0], ensure_ascii=False)


def test_recover_now_uses_ordinary_recovery_actions_once():
    citizen()
    set_life(energy=5, social=5)
    panel = press(ui.cid('111', 'st'))
    recover = find(panel['data'], 'Recover now')['custom_id']
    result = press(recover)
    assert 'Relaxed' in json.dumps(result, ensure_ascii=False) and 'Played games' in json.dumps(result, ensure_ascii=False)
    db, p = player()
    with db:
        life = m.life_state(db, p)
        assert life.energy >= 20 and life.social >= 20
    assert 'already used' in press(recover)['data']['content']


# ---------------------------------------------------------------- favourites and Ready now

def test_favourite_button_sets_state_idempotently_and_marks_lists():
    citizen()
    star = ui.cid('111', 'fv', CAMPFIRE.id, 1, CAMPFIRE.category, 1, '')
    first = press(star)
    assert 'added to favourites' in json.dumps(first['data']['embeds'][0], ensure_ascii=False)
    assert 'Unfavourite' in labels(first['data'])
    assert 'already a favourite' in json.dumps(press(star)['data']['embeds'][0], ensure_ascii=False)
    db, p = player()
    with db:
        assert qol.favorite_ids(m, db, p) == [CAMPFIRE.id]
        ctx = wb.Context(m, db, p)
        assert wb.choice_label(ctx, CAMPFIRE).startswith('✅⭐')
        assert wb.in_view(ctx, 'favorites') == [CAMPFIRE]
        assert wb.in_view(ctx, 'ready')[0] == CAMPFIRE
    press(ui.cid('111', 'fv', CAMPFIRE.id, 0, '', 1, ''))
    db, p = player()
    with db:
        assert qol.favorite_ids(m, db, p) == []


def test_favourites_are_capped():
    citizen()
    db, p = player()
    with db:
        ids = [e.id for e in wb.index(m)][:qol.MAX_FAVORITES + 1]
        for rid in ids[:-1]:
            qol.set_favorite(m, db, p, rid, True)
        assert 'Remove one' in qol.set_favorite(m, db, p, ids[-1], True)
        assert len(qol.favorite_ids(m, db, p)) == qol.MAX_FAVORITES


def test_ready_now_view_lists_only_ready_recipes_on_every_platform():
    citizen()
    view = press(ui.cid('111', 'sc'), values=['ready'])
    text = json.dumps(view['data']['embeds'][0], ensure_ascii=False)
    assert 'Ready Now' in text and 'Campfire' in text
    db, p = player()
    with db:
        ctx = wb.Context(m, db, p)
        assert all(ctx.status(e).code == 'ready' for e in wb.in_view(ctx, 'ready'))
    assert wb.normalize_category('Ready now') == 'ready' and wb.normalize_category('favs') == 'favorites'
    with m.SessionLocal() as db:
        m.material_change(db, m.player(db, W, 'twitch', 'tw', 'Kam')[1], LUMBER, 10)
        db.commit()
    chat = m.make(W, 'tw', 'Kam', 'ready', 'twitch').body.decode()
    assert 'Ready now' in chat and 'Campfire' in chat and len(chat.encode()) <= 380
    empty = m.make(W, 'tw', 'Kam', 'favs', 'twitch').body.decode()
    assert '!fav' in empty


def test_make_slash_options_include_views_and_actions():
    make = next(c for c in m.DISCORD_COMMAND_CATALOG if c['name'] == 'make')
    category = next(o for o in make['options'] if o['name'] == 'category')
    assert [c['value'] for c in category['choices']][:2] == ['ready', 'favorites']
    action = next(o for o in make['options'] if o['name'] == 'action')
    assert {'fetch', 'favorite'} <= {c['value'] for c in action['choices']}
    citizen()
    result = m._discord_call_internal('make', '111', 'Kam', {'recipe': CAMPFIRE.id, 'action': 'favorite'}, '')
    assert 'added to favourites' in result


# ---------------------------------------------------------------- fetch missing ingredients

def test_fetch_plan_gathers_then_crafts_via_one_ticket():
    citizen(lumber=0)
    preview = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))
    fetch = find(preview['data'], 'Fetch missing')['custom_id']
    plan = press(fetch)
    text = json.dumps(plan['data']['embeds'][0], ensure_ascii=False)
    assert 'Lumber' in text and 'Then make Campfire' in text
    start = next(c for c in controls(plan['data']) if '→ craft' in c.get('label', ''))
    result = press(start['custom_id'])
    assert 'Next queue set' in json.dumps(result, ensure_ascii=False)
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.task == 'gather:' + LUMBER and row.state == 'running'
        pref = db.query(qol.Preferences).one()
        assert pref.next_task == 'make:' + CAMPFIRE.id and pref.next_count == 1


def test_fetch_route_for_twitch_plans_and_starts():
    citizen(lumber=0)
    plan = m.fetch_ingredients(W, '111', 'Kam', 'Campfire', 0, 'plan', 'twitch').body.decode()
    assert 'Lumber' in plan and '!fetchgo' in plan
    started = m.fetch_ingredients(W, '111', 'Kam', 'campfir', 0, 'start', 'twitch').body.decode()
    assert 'queued to craft next' in started


def test_buy_missing_buys_only_the_shortfall():
    citizen(lumber=0)
    db, p = player()
    with db:
        ctx = wb.Context(m, db, p)
        assert [r['key'] for r in qol.fetch_routes(ctx, CAMPFIRE, 1) if r['price']] == [LUMBER]
        sc = p.sc
        qol.buy_missing(m, db, p, CAMPFIRE, 1)
    db, p = player()
    with db:
        ctx = wb.Context(m, db, p)
        assert p.sc < sc
        assert not [r for r in qol.fetch_routes(ctx, CAMPFIRE, 1) if r['price']]


# ---------------------------------------------------------------- follow-up and repeat queues

def test_next_queue_starts_when_the_current_one_completes():
    enqueue(count=1)
    note = m.queued_tasks('test', 'u', action='next', task='mine:' + ORE, count='2', provider='discord').body.decode()
    assert 'Next queue set' in note
    advance()
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.state == 'running' and row.total == 2 and row.remaining == 2
        notice = db.query(n.Notice).one()
        assert 'COMPLETED' in notice.content and 'Starting your next queue' in notice.content
        assert db.query(qol.Preferences).one().next_task == ''
    advance(); advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().state == 'completed'
        assert db.query(m.Player).one().actions == 3


def test_start_while_busy_suggests_next_and_cancel_clears_it():
    enqueue(count=5)
    busy = m.queued_tasks('test', 'u', action='start', task='work:harvest', count='1', provider='discord').body.decode()
    assert 'Queue next' in busy
    m.queued_tasks('test', 'u', action='next', task='work:harvest', count='1', provider='discord')
    cancelled = m.queued_tasks('test', 'u', action='cancel', provider='discord').body.decode()
    assert 'next queue' in cancelled.lower()
    with m.SessionLocal() as db:
        assert db.query(qol.Preferences).one().next_task == ''


def test_repeat_restarts_the_last_queue_and_is_offered_everywhere():
    enqueue(count=1)
    advance()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        buttons = labels({'components': ui.queue_components(m, db, p, '123')})
        assert 'Repeat ×1' in buttons
        notice = db.query(n.Notice).one()
    alert = ui.alert_components(m, SimpleNamespace(id=notice.id, recipient='123', content=notice.content))
    assert 'Repeat ×1' in labels({'components': alert})
    again = m.queued_tasks('test', 'u', action='repeat', provider='discord').body.decode()
    assert 'RUNNING' in again
    busy = m.queued_tasks('test', 'u', action='repeat', provider='discord').body.decode()
    assert 'still active' in busy
    assert 'no earlier queue' in m.queued_tasks('test', 'someone', action='repeat', provider='twitch').body.decode()


def test_queue_plan_offers_queue_next_when_busy():
    citizen()
    press(find(press(ui.cid('111', 'qp', 'gather:' + LUMBER, 2))['data'], 'Start queue')['custom_id'])
    plan = press(ui.cid('111', 'qp', 'gather:' + LUMBER, 3))
    button = find(plan['data'], 'Add to plan ×3')
    result = press(button['custom_id'])
    assert 'Next queue set' in json.dumps(result, ensure_ascii=False)
    status = press(ui.cid('111', 'qv'))
    assert 'Clear next' in labels(status['data'])
    cleared = press(ui.cid('111', 'cn'))
    assert 'Next queue cleared' in json.dumps(cleared['data']['embeds'][0], ensure_ascii=False)


# ---------------------------------------------------------------- recovery estimates and auto-recover

def test_pause_reason_estimates_passive_recovery():
    enqueue(count=2)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        life = m.life_state(db, p)
        life.energy = 15
        life.last_decay_at = m.now()
        db.commit()
    advance()
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.state == 'paused'
        stamp = re.search(r'Passive recovery reaches 20 <t:(\d+):R>', row.result)
        assert stamp and abs(int(stamp.group(1)) - m.now().timestamp() - 75 * 60) < 120
        assert 'resumes automatically' in db.query(n.Notice).one().content


def test_auto_recover_keeps_the_queue_running():
    enqueue(count=2)
    m.settings('test', 'u', provider='discord', autorecover='on')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        m.life_state(db, p).energy = 5
        db.commit()
    advance()
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.state == 'running' and row.remaining == 1
        assert m.life_state(db, db.query(m.Player).one()).energy >= 20
        assert db.query(n.Notice).count() == 0


def test_auto_recover_eats_the_cheapest_food_and_notes_failures():
    seed(provider='discord')
    db = m.SessionLocal()
    with db:
        p = db.query(m.Player).one()
        foods = sorted(s.EDIBLE, key=s.nutrition)
        m.material_change(db, p, foods[-1], 1)
        m.material_change(db, p, foods[0], 1)
        m.life_state(db, p).nutrition = 5
        db.commit()
        cheapest = min(m.edible_inventory(db, p), key=lambda r: (r['gain'], r['name']))['key']
        before = s.stock(m, db, p).get(cheapest, 0)
        notes = qol.recover(m, db, p, 'test', p.twitch_uid)
        db.expire_all()
        assert any(x.startswith('Ate ') for x in notes)
        assert s.stock(m, db, p).get(cheapest, 0) == before - 1


# ---------------------------------------------------------------- alert preferences

def test_quiet_and_off_alerts_skip_messages_but_keep_results():
    enqueue(count=2)
    m.settings('test', 'u', provider='discord', alerts='quiet')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        m.life_state(db, p).energy = 19
        db.commit()
    advance()
    with m.SessionLocal() as db:
        assert db.query(q.TaskQueue).one().state == 'paused'
        assert db.query(n.Notice).count() == 0
    m.settings('test', 'u', provider='discord', alerts='off')
    m.queued_tasks('test', 'u', action='cancel', provider='discord')
    with m.SessionLocal() as db:
        assert db.query(n.Notice).count() == 0
        assert 'alerts are off' in q.status(m, db, db.query(m.Player).one(), db.query(q.TaskQueue).one())


def test_dm_alerts_are_marked_and_twitch_cannot_choose_dm():
    assert 'Discord option' in m.settings('test', 'tw', provider='twitch', text='alerts dm').body.decode()
    enqueue(count=1)
    m.settings('test', 'u', provider='discord', alerts='dm')
    advance()
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().message_channel.startswith(n.DM_PREFIX)


def _notice(channel_id):
    return SimpleNamespace(id='b' * 32, recipient='123', message_channel=channel_id,
                           content='TASK QUEUE — COMPLETED\nMine Coal\nAttempts completed: 1/1; remaining: 0.')


def _http():
    return SimpleNamespace(request=AsyncMock(return_value={'id': '1'}))


def test_dm_delivery_sends_privately_and_closed_dms_stay_out_of_the_channel(monkeypatch):
    from app import layout_v2
    dm = MagicMock(spec=discord.DMChannel)
    dm.id = 789
    dm.send = AsyncMock(return_value=SimpleNamespace(id=1))
    user = SimpleNamespace(create_dm=AsyncMock(return_value=dm))
    client = SimpleNamespace(get_user=lambda _: user, get_channel=lambda _: None, http=_http())
    asyncio.run(w.send_notice(m, client, _notice(n.DM_PREFIX + '456')))
    route, = client.http.request.call_args.args
    body = client.http.request.call_args.kwargs['json']
    assert route.url.endswith('/channels/789/messages') and not dm.send.await_count
    assert layout_v2.text_of(body).startswith('Your queue has finished.') and body['allowed_mentions']['users'] == []

    # Closed DMs: nothing is posted in the channel; the alert waits, unread, in the player's Notifications.
    enqueue(count=1)
    advance()
    with m.SessionLocal() as db:
        notice = db.query(n.Notice).one()
        uid = db.query(q.TaskQueue).one().canonical_uid
        assert notice.message_channel.startswith(n.DM_PREFIX)                       # DM is the default
        assert m.inbox.unread_count(db, notice.channel_id, uid) == 0                 # a DM counts as seen
        row = SimpleNamespace(id=notice.id, recipient='123', message_channel=n.DM_PREFIX + '456',
                              content=notice.content, channel_id=notice.channel_id)
    monkeypatch.setattr(m.inbox, '_canonical', lambda m_, db_, discord_uid: uid)   # Discord user 123 is that citizen
    room = MagicMock(spec=discord.TextChannel)
    room.id = 456
    room.send = AsyncMock(return_value=SimpleNamespace(id=2))
    closed = SimpleNamespace(create_dm=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='x'), 'closed')))
    client = SimpleNamespace(get_user=lambda _: closed, get_channel=lambda _: room, http=_http())
    asyncio.run(w.send_notice(m, client, row))
    assert not client.http.request.await_count and not room.send.await_count
    with m.SessionLocal() as db:
        assert m.inbox.unread_count(db, row.channel_id, uid) == 1


def test_alert_buttons_reach_the_discord_view():
    enqueue(count=1)
    advance()
    with m.SessionLocal() as db:
        notice = db.query(n.Notice).one()
        notice.recipient = '123'
        db.commit()
        row = SimpleNamespace(id=notice.id, recipient='123', message_channel='456', content=notice.content)
    from app import layout_v2
    room = MagicMock(spec=discord.TextChannel)
    room.id = 456
    room.send = AsyncMock(return_value=SimpleNamespace(id=1))
    client = SimpleNamespace(get_channel=lambda _: room, http=_http())
    asyncio.run(w.send_notice(m, client, row))
    body = client.http.request.call_args.kwargs['json']
    assert {'Repeat ×1', 'Status', 'Queue'} <= {c.get('label') for c in layout_v2.controls(body)}


# ---------------------------------------------------------------- selling and inventory

def test_sell_all_and_clearout_protect_favourite_ingredients():
    citizen(lumber=50)
    db, p = player()
    with db:
        m.material_change(db, p, STONE_DUST, 45)
        qol.set_favorite(m, db, p, CAMPFIRE.id, True)
        db.commit()
    preview = m.clearout(W, '111', 'Kam', '', 'discord').body.decode()
    assert 'Stone Dust ×25' in preview and 'Lumber' not in preview.split('WOULD SELL')[1]
    panel = ui.slash_panel(m, 'seedindustries', '111', 'Kam', {'action': 'clearout'}, preview)
    sell = find(panel, 'Sell for')['custom_id']
    press(sell)
    db, p = player()
    with db:
        have = s.stock(m, db, p)
        assert have.get(STONE_DUST) == qol.CLEAROUT_RESERVE and have.get(LUMBER) == 50
    result = m.sell_all_items(W, '111', 'Kam', 'lumbr', 'discord').body.decode()
    assert 'sold all 50 Lumber' in result and 'favourite Campfire uses Lumber' in result
    assert 'Nothing to clear out' in m.clearout(W, '111', 'Kam', 'confirm', 'twitch').body.decode()


def test_inventory_search_sort_and_filters():
    citizen(lumber=30)
    db, p = player()
    with db:
        m.material_change(db, p, STONE_DUST, 5)
        db.commit()
    found = m.inventory(W, '111', 'Kam', 'discord', search='lumb').body.decode()
    assert 'Lumber ×30' in found and 'Stone Dust' not in found
    ready = m.inventory(W, '111', 'Kam', 'discord', show='ready').body.decode()
    assert 'Lumber' in ready
    chat = m.inventory(W, '111', 'Kam', 'twitch', text='value').body.decode()
    assert chat.startswith('🎒') and len(chat.encode()) <= 380
    assert qol.parse_inventory_text('ore value 2') == ('ore', 'value', 'all', 2)
    assert 'Inventory' in m.inventory(W, '111', 'Kam', 'discord').body.decode()


# ---------------------------------------------------------------- fuzzy names and hints

def test_fuzzy_names_resolve_or_suggest():
    citizen()
    crafted = m.make(W, '111', 'Kam', 'campfir', 'twitch').body.decode()
    assert 'matched Campfire' in crafted
    unknown = m.make(W, '111', 'Kam', 'zzqqxx', 'twitch').body.decode()
    assert 'Unknown recipe' in unknown and 'matched' not in unknown
    _, suggestions = qol.match('iron', {'iron plate': 1, 'iron nails': 2, 'glass': 3})
    assert suggestions == ['iron nails', 'iron plate']
    assert qol.match('glas', {'iron plate': 1, 'glass': 3})[0] == 3
    gathered = m.seed_supplies(W, '111', 'Kam', 'gather', 'lumbr', provider='discord').body.decode()
    assert 'GATHERING COMPLETE' in gathered


def test_newcomer_craft_receipt_suggests_a_next_step():
    citizen()
    result = m.make(W, '111', 'Kam', CAMPFIRE.id, 'discord', action='craft').body.decode()
    assert 'CRAFTING COMPLETE' in result and 'NEXT STEP' in result
    card = m._discord_json_message(result, message_type='make')['data']
    assert '💡' in json.dumps(card, ensure_ascii=False)


def test_tier_up_is_announced(monkeypatch):
    citizen()
    real = wb.Context.__init__

    def init(self, *args, **kwargs):
        real(self, *args, **kwargs)
        self.tier = 2
    monkeypatch.setattr(wb.Context, '__init__', init)
    db, p = player()
    with db:
        assert 'Personal Tier 2' in qol.action_hint(m, db, p, 'discord', tier_before=1)


def test_settings_view_and_twitch_text():
    citizen()
    view = m.settings(W, '111', 'Kam', provider='discord').body.decode()
    assert 'Alerts: direct message' in view and 'Auto-recover: off' in view
    chat = m.settings('test', 'tw', provider='twitch', text='autorecover on').body.decode()
    assert 'Auto-recover on' in chat
    assert 'Nothing changed' in m.settings('test', 'tw', provider='twitch', text='volume 11').body.decode()


def test_old_default_alerts_move_to_direct_messages_once():
    from sqlalchemy import text
    with m.SessionLocal() as db:
        db.execute(text('DELETE FROM simulation_schema_versions WHERE version=:v'), {'v': qol.QUIET_MARKER})
        qol.prefs(db, W, 'a', create=True).alerts = 'mention'          # the old default
        db.commit()
        assert qol.alert_mode(db, W, 'new') == 'dm'                     # the new default
    qol.quiet_channel_once(m)
    with m.SessionLocal() as db:
        assert qol.alert_mode(db, W, 'a') == 'dm'
        qol.prefs(db, W, 'a').alerts = 'mention'                        # chosen again afterwards: kept
        db.commit()
    qol.quiet_channel_once(m)
    with m.SessionLocal() as db:
        assert qol.alert_mode(db, W, 'a') == 'mention'


def test_quiet_alerts_are_direct_messages_too():
    enqueue(count=1)
    with m.SessionLocal() as db:
        queue = db.query(q.TaskQueue).one()
        qol.prefs(db, queue.channel_id, queue.canonical_uid, create=True).alerts = 'quiet'
        db.commit()
    advance()
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().message_channel.startswith(n.DM_PREFIX)
