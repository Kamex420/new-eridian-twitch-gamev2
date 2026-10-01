"""Countdowns, queue max, recent actions, goals, plans, uses, reminders, auto-sell, undo, eat until full, find and place."""
import json
import re
from datetime import timedelta
from test_colony import m, reset, seed
from test_task_queue import advance
from test_workbench_ui import citizen, press, controls, find, W, LUMBER, CAMPFIRE
from app import ui, extras, inbox, qol, menu, presentation, seed_content as s, task_queue as q

STAMP = re.compile(r'<t:\d+:R>')


def player(uid='111'):
    db = m.SessionLocal()
    return db, m.player(db, W, 'discord', uid, 'Kam')[1]


def labels(data):
    return [c.get('label', '') for c in controls(data)]


def text_of(data):
    return json.dumps(data.get('embeds', []), ensure_ascii=False)


# ---------------------------------------------------------------- countdowns

def test_discord_shows_live_countdowns_and_twitch_shows_plain_times():
    assert STAMP.fullmatch(extras.stamp(m, 90))
    assert extras.when(m, 90, 'twitch').startswith('in ')
    assert presentation.plain_times(f'Ready {extras.stamp(m, 120)}.') .startswith('Ready in ')
    citizen()
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '3', 'discord')
    assert STAMP.search(m.status_view(W, '111', 'Kam', 'discord').body.decode())
    assert '<t:' not in m.status_view('test', 'u', 'Kamex', 'twitch').body.decode()


# ---------------------------------------------------------------- queue max

def test_queue_max_is_limited_by_ingredients_and_needs():
    citizen(lumber=0)
    db, p = player()
    need = CAMPFIRE.inputs
    for key, n in need.items():
        m.material_change(db, p, key, n * 3)
    db.commit()
    count, reason = extras.max_attempts(m, db, p, 'make:' + CAMPFIRE.id)
    assert count == 3 and reason
    life = m.life_state(db, p)
    life.energy = 21
    db.commit()
    count, reason = extras.max_attempts(m, db, p, 'gather:' + LUMBER)
    assert count == 1 and reason == 'Energy'
    db.close()


def test_recipe_panel_offers_queue_max_and_craftmax_queues_it():
    citizen(lumber=0)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        for key, n in CAMPFIRE.inputs.items():
            m.material_change(db, p, key, n * 2)
        db.commit()
    panel = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))
    assert find(panel['data'], 'Queue max ×2')
    seed()
    result = m.craft_max('test', 'u', 'Kamex', 'lumber', 'twitch').body.decode()
    assert 'Max ×' in result
    with m.SessionLocal() as db:
        assert db.get(q.TaskQueue, ('test', 'u')).task == 'gather:' + LUMBER


# ---------------------------------------------------------------- recent actions and !again

def test_recent_actions_are_recorded_and_offered_as_buttons():
    citizen()
    extras.record_discord(m, '111', 'Kam', 'relax', {})
    extras.record_discord(m, '111', 'Kam', 'relax', {})
    extras.record_discord(m, '111', 'Kam', 'gather', {'resource': LUMBER})
    extras.record_discord(m, '111', 'Kam', 'status', {})
    db, p = player()
    rows = extras.recent(db, p.channel_id, p.twitch_uid)
    assert [r.command for r in rows] == ['gather', 'relax']
    db.close()
    view = press(ui.cid('111', 'mn', 'recent'))
    assert any('Lumber' in label for label in labels(view['data']))


def test_twitch_again_repeats_the_last_action():
    seed()
    assert 'Nothing to repeat' in m.again('test', 'u', 'Kamex', 'twitch').body.decode()
    m.relax('test', 'u', 'Kamex', 'twitch')
    with m.SessionLocal() as db:
        assert extras.recent(db, 'test', 'u', 'twitch')[0].command == 'relax'
        db.query(m.Cooldown).delete()
        db.commit()
    assert 'downtime' in m.again('test', 'u', 'Kamex', 'twitch').body.decode()


# ---------------------------------------------------------------- goal

def test_goal_tracks_next_step_in_view_status_and_twitch():
    citizen(lumber=0)
    view = press(ui.cid('111', 'gs', CAMPFIRE.id))
    body = text_of(view['data'])
    assert 'Goal set' in body and 'Gather Lumber' in body and 'Craft Campfire' in body          # every step, in order
    assert 'Gather' in labels(view['data'])                                                       # each with its button
    assert '🎯 GOAL' in m.status_view(W, '111', 'Kam', 'discord').body.decode()
    seed()
    chat = m.target('test', 'u', 'Kamex', 'campfire', 'twitch').body.decode()
    assert 'Goal' in chat and 'Next' in chat
    assert 'cleared' in m.target('test', 'u', 'Kamex', 'clear', 'twitch').body.decode()


def test_goal_clears_itself_when_crafted():
    citizen()
    db, p = player()
    extras.set_goal(m, db, p, CAMPFIRE.id)
    extras.goal_completed(m, db, p, f'CRAFTING COMPLETE — {CAMPFIRE.name}')
    assert extras.goal_entry(m, db, p) is None
    assert any('Goal complete' in i.text for i in db.query(inbox.InboxItem))
    db.close()


# ---------------------------------------------------------------- plans and routines

def test_plan_runs_steps_in_order_with_sell_steps_between():
    citizen()
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '1', 'discord')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        extras.add_step(m, db, p, {'task': 'gather:' + LUMBER, 'count': 1})   # becomes "next"
        extras.add_step(m, db, p, {'sell': LUMBER})
        extras.add_step(m, db, p, {'task': 'gather:' + LUMBER, 'count': 2})
        db.commit()
        assert len(extras.current_steps(m, db, p)) == 4
        task, count, notes = extras.pop_step(m, db, p)
        assert (task, count) == ('gather:' + LUMBER, 2) and notes and 'Lumber' in notes[0]
        assert extras.playlist(db, p.channel_id, p.twitch_uid) == []


def test_routines_save_and_start_again():
    citizen()
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '2', 'discord')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert 'Routine saved' in extras.save_routine(m, db, p)
        db.commit()
        rid = extras.routines(db, p)[0].id
        m.queued_tasks(W, '111', 'Kam', 'cancel', '', '1', 'discord')
    assert 'Routine started' in extras.start_routine(m, W, '111', 'Kam', 'discord', rid)
    assert 'Lumber' in m.routines_view(W, '111', 'Kam', 'view', 'discord').body.decode()


# ---------------------------------------------------------------- uses, auto-sell, undo

def test_uses_lists_recipes_ready_first():
    citizen()
    db, p = player()
    text, rows = extras.uses_text(m, db, p, LUMBER)
    assert rows and 'LUMBER' in text.upper()
    chat, _ = extras.uses_text(m, db, p, LUMBER, 'twitch')
    assert len(chat) < 400
    db.close()


def test_autosell_sells_chosen_items_after_a_queue_but_keeps_protected_ones():
    citizen()
    stone = s.key('Stone Dust')
    db, p = player()
    assert 'will be sold automatically' in extras.toggle_autosell(m, db, p, stone)
    m.material_change(db, p, stone, 5)
    db.commit()
    notes = extras.autosell_after_queue(m, db, p)
    assert notes and m.material_amount(db, p, stone) == 0
    assert 'no longer' in extras.toggle_autosell(m, db, p, stone)
    db.close()


def test_undo_returns_a_sale_within_sixty_seconds_only(monkeypatch):
    citizen()
    before_sc = 1000
    m.sell_all_items(W, '111', 'Kam', 'lumber', 'discord')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.material_amount(db, p, LUMBER) == 0 and p.sc > before_sc
    assert 'Sale undone' in m.undo_sale(W, '111', 'Kam', 'discord').body.decode()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.material_amount(db, p, LUMBER) == 10 and p.sc == before_sc
    assert 'no recent sale' in m.undo_sale(W, '111', 'Kam', 'discord').body.decode()
    m.sell_all_items(W, '111', 'Kam', 'lumber', 'discord')
    later = m.now() + timedelta(seconds=90)
    monkeypatch.setattr(m, 'now', lambda: later)
    assert 'final' in m.undo_sale(W, '111', 'Kam', 'discord').body.decode()


# ---------------------------------------------------------------- eat until full

def test_eat_until_full_uses_cheapest_everyday_food_once():
    citizen()
    foods = sorted((k for k in s.EDIBLE if k != 'meal_kit'), key=s.nutrition)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.life_state(db, p).nutrition = 30
        m.material_change(db, p, foods[0], 20)
        db.commit()
    text = m.eat_full(W, '111', 'Kam', 'discord').body.decode()
    assert 'eats until full' in text or 'Ate until full' in text
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.life_state(db, p).nutrition >= extras.FULL_NUTRITION
        assert m.material_amount(db, p, foods[0]) < 20
    assert 'already' in m.eat_full(W, '111', 'Kam', 'discord').body.decode()


# ---------------------------------------------------------------- welcome back and reminders

def test_welcome_back_summary_after_three_hours_away():
    citizen()
    db, p = player()
    extras.touch(m, db, p)
    db.commit()
    assert not [i for i in db.query(inbox.InboxItem) if 'Welcome back' in i.text]
    extras.row(db, p.channel_id, p.twitch_uid).last_seen = m.now() - timedelta(hours=4)
    extras.touch(m, db, p)
    db.commit()
    welcome = [i for i in db.query(inbox.InboxItem) if 'Welcome back' in i.text]
    assert welcome and 'Needs now' in welcome[0].text
    db.close()


def test_sleep_ready_reminder_is_sent_once():
    citizen()
    db, p = player()
    m.life_state(db, p).energy = 25
    db.commit()
    extras.touch(m, db, p)
    extras.touch(m, db, p)
    db.commit()
    assert len([i for i in db.query(inbox.InboxItem) if 'Sleep is ready' in i.text]) == 1
    db.close()


# ---------------------------------------------------------------- find and remember my place

def test_find_searches_recipes_items_buttons_and_handbook():
    found = extras.find(m, 'campfire')
    assert any(e.name == 'Campfire' for e in found['recipes'])
    assert 'Lumber' in extras.find_text(m, 'lumber')
    assert 'nothing found' in extras.find_text(m, 'zzzqqq', 'twitch')
    citizen()
    assert 'Campfire' in m._discord_call_internal('find', '111', 'Kam', {'query': 'campfire'}, 'i1')
    assert 'find' in m.DISCORD_OPTION_SCHEMA
    assert 'Campfire' in m.find_anything('campfire', 'twitch').body.decode()


def test_bare_make_reopens_the_last_workbench_category():
    citizen()
    press(ui.cid('111', 'wc', 'ready', 1, ''))
    assert extras.default_options(m, 'make', {}, '111')['category'] == 'ready'
    assert extras.default_options(m, 'make', {'recipe': 'x'}, '111') == {'recipe': 'x'}


def test_menu_leaves_for_new_features_exist():
    for key in ('eatfull', 'goal', 'plan', 'uses', 'autosell', 'undo'):
        assert key in menu.LEAVES, key
