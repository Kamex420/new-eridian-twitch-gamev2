"""The goal: completed where it is crafted (buttons, queues, chat, Seedlings), progress since it was set, one private
note when it can be crafted, the shopping-list links both ways, and one plan per screen."""
import json
from datetime import timedelta
from test_colony import m, reset, seed
from test_task_queue import advance, due
from test_workbench_ui import citizen, press, controls, find, W, LUMBER, CAMPFIRE
from test_layout_v2 import assert_valid
from app import ui, extras, inbox, workbench as wb, seed_content as s, task_queue as q, shopping_list as shop, queue_notifications as qn
from app import autonomy as a, layout_v2 as v2

TOILET = next(e for e in wb.index() if e.name == 'Crude Wood Toilet')
PLANKS = wb.entry(m.MERGED_TRAINING['train_wood_processing'])          # Wood Planks: the Wood Processing task crafts it
CARPENTRY = s.key('Carpentry Station')
MUSHROOM = next(e for e in wb.index() if e.name == 'Mushroom')
SAUTEED = next(e for e in wb.index() if e.name == 'Sauteed Mushrooms')   # "Mushroom" is in its name
ORE_SCANNER = wb.entry('ore_scanner')


def player(uid='111'):
    db = m.SessionLocal()
    return db, m.player(db, W, 'discord', uid, 'Kam')[1]


def stock(items, uid='111', channel=W, provider='discord'):
    """Set how many of each item a citizen has."""
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, 'Kam')[1]
        for key, n in items.items():
            m.material_change(db, p, key, n - m.material_amount(db, p, key))
        db.commit()


def set_goal(recipe, uid='111', channel=W, provider='discord'):
    with m.SessionLocal() as db:
        text = extras.set_goal(db, m.player(db, channel, provider, uid, 'Kam')[1], recipe)
        db.commit()
        return text


def goal(uid='111', channel=W, provider='discord'):
    with m.SessionLocal() as db:
        e = extras.goal_entry(db, m.player(db, channel, provider, uid, 'Kam')[1])
        return e.id if e else None


def progress_row(uid='111', channel=W, provider='discord'):
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, 'Kam')[1]
        found = db.get(extras.GoalProgress, (p.channel_id, p.twitch_uid))
        return (found.recipe_id, found.start_steps, found.ready_alerted) if found else None


def notes(kind=None, uid='111', channel=W, provider='discord'):
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, 'Kam')[1]
        rows = db.query(inbox.InboxItem).filter_by(channel_id=p.channel_id, canonical_uid=p.twitch_uid).order_by(inbox.InboxItem.id)
        return [r.text for r in rows if kind is None or r.kind == kind]


def screen_text(data):
    return v2.text_of(data).replace('**', '')


def chat_line(uid='111'):
    """The Twitch goal line (what !target shows) for a citizen."""
    with m.SessionLocal() as db:
        text = extras.goal_text(db, m.player(db, W, 'discord', uid, 'Kam')[1], 'twitch')
        db.commit()
        return text


def labels(data):
    return [c.get('label', '') for c in controls(data)]


def rows_ok(data):
    rows = [r for r in data['components'] if r.get('components')]
    ids = [c['custom_id'] for r in rows for c in r['components'] if 'custom_id' in c]
    return (len(rows) <= 5 and all(0 < len(r['components']) <= 5 for r in rows) and len(ids) == len(set(ids))
            and all(len(i) <= 100 for i in ids) and [c['label'] for c in rows[-1]['components']][-2:] == ['Back', 'Menu'])


# ---------------------------------------------------------------- completion where the craft happens

def test_crafting_the_goal_with_its_button_completes_it_once():
    citizen()
    set_goal(CAMPFIRE.id)
    preview = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))['data']
    assert press(find(preview, 'Craft 1 batch')['custom_id'])['type'] == 7
    assert goal() is None and progress_row() is None
    assert [t for t in notes('milestone') if 'Goal complete' in t] == ['🎯 **Goal complete: Campfire!** Pick a new one from any recipe.']
    m.make(W, '111', 'Kam', CAMPFIRE.id, 'discord')                         # another Campfire: no goal, nothing more
    assert len([t for t in notes() if 'Goal complete' in t]) == 1


def test_a_queue_that_crafts_the_goal_completes_it():
    """BUG 1: a goal crafted by a queue stayed set (completion only read interactive receipts)."""
    citizen()
    set_goal(CAMPFIRE.id)
    assert 'TASK QUEUE' in m.queued_tasks(W, '111', 'Kam', 'start', 'make:' + CAMPFIRE.id, '1', 'discord').body.decode()
    advance()
    db, p = player()
    assert m.material_amount(db, p, CAMPFIRE.output) == 1 and db.get(q.TaskQueue, (p.channel_id, p.twitch_uid)).state == 'completed'
    db.close()
    assert goal() is None and progress_row() is None and any('Goal complete: Campfire' in t for t in notes('milestone'))


def test_crafting_new_eridian_equipment_that_is_the_goal_completes_it():
    """The equipment without a catalog twin (quality gear and core equipment) is crafted by its own path, and can be a goal."""
    citizen(lumber=0)
    table = next(k for k in s.MACHINE_RECIPES if 'TAG_MACHINE_CRAFTING_TABLE_V1' in s.machine_tags(k))
    for recipe, machine in (('recreation_set', CARPENTRY), ('toolkit', table)):           # quality gear, core equipment
        e = wb.entry(recipe)
        assert e.kind == 'legacy' and (recipe in m.QUALITY_RECIPES) == (recipe == 'recreation_set')
        stock({machine: 1, **e.inputs})
        set_goal(recipe)
        assert 'CRAFTING COMPLETE' in m.make(W, '111', 'Kam', recipe, 'discord').body.decode()
        assert goal() is None and progress_row() is None and any(f'Goal complete: {e.name}' in t for t in notes('milestone'))


def test_a_rare_ore_recipe_completes_when_its_ore_is_recovered():
    """A recipe with a rare-ore output mines it (one roll, like any ore) and completes the goal when the ore comes up."""
    citizen()
    argentite = wb.entry('sr_2069171276')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.craft_record(db, p, CAMPFIRE.id).qty = 100                         # personal Tier 3
        m.material_change(db, p, s.key('Small Mineral Extractor'), 1)       # unlocks rare ores
        db.commit()
    set_goal(argentite.id)
    due()
    text = m.make(W, '111', 'Kam', argentite.id, 'discord').body.decode()
    assert 'RARE ORE MINED' in text and goal() is None, text


def test_a_seedling_crafting_its_owners_goal_completes_it(monkeypatch):
    """Seedlings never press Craft, but a training task that runs a catalog recipe crafts it (Wood Processing makes Wood
    Planks) through the ordinary command: when that recipe is the goal, the Seedling completes it. Its own planning never
    picks a task that spends what the goal needs, so the plan is chosen here; the rest is the real autonomous turn."""
    seed()
    stock({CARPENTRY: 1, LUMBER: 5}, 'u', 'test', 'twitch')
    set_goal(PLANKS.id, 'u', 'test', 'twitch')
    step = {'kind': 'train', 'task': 'train_wood_processing', 'skill': 'environmental', 'call': ('action', {'action': 'train_wood_processing'}),
            'why': 'Practising Wood Processing.'}
    monkeypatch.setattr(a, 'plan', lambda *args: dict(step))
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        p.last_seen = m.now() - timedelta(minutes=40)                        # away: the Seedling acts
        db.commit()
    a.live_one('test', 'u')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert m.material_amount(db, p, PLANKS.output) > 0                    # the Seedling's task made it
        assert 'Practising Wood Processing.' in db.query(a.SeedlingDiary).one().text
    assert goal('u', 'test', 'twitch') is None and any('Goal complete: Wood Planks' in t for t in notes('milestone', 'u', 'test', 'twitch'))


def test_a_receipt_naming_the_goal_does_not_complete_it():
    """BUG 2: 57 recipe names sit inside other names ("Mushroom" in "Sauteed Mushrooms"), so any receipt mentioning the goal
    cleared it. Crafting Sauteed Mushrooms leaves the goal Mushroom set, and so does the old text hook."""
    citizen()
    stock({CAMPFIRE.output: 1, MUSHROOM.output: 3})                           # a Campfire opens the Sauteed Mushrooms station
    set_goal(MUSHROOM.id)
    receipt = m.make(W, '111', 'Kam', SAUTEED.id, 'discord').body.decode()
    assert 'CRAFTING COMPLETE' in receipt and MUSHROOM.name in receipt
    inbox.after_command('111', 'Kam', 'make', {'recipe': SAUTEED.id}, receipt)
    with m.SessionLocal() as db:
        extras.goal_completed(db, m.player(db, W, 'discord', '111', 'Kam')[1], receipt)      # kept, does nothing
        db.commit()
    assert goal() == MUSHROOM.id and not [t for t in notes() if 'Goal complete' in t]


def test_failed_and_refused_attempts_do_not_complete_the_goal(monkeypatch):
    citizen(lumber=0)
    stock({CARPENTRY: 1})
    set_goal(PLANKS.id)
    assert 'nothing spent' in m.make(W, '111', 'Kam', PLANKS.id, 'discord').body.decode().casefold()     # refused: no Lumber
    stock({LUMBER: 5})
    monkeypatch.setattr(m.random, 'random', lambda: 0.99)
    assert 'TASK FAILED' in m.action('train_wood_processing', W, '111', 'Kam', provider='discord').body.decode()
    m.queued_tasks(W, '111', 'Kam', 'start', 'work:train_wood_processing', '1', 'discord')
    advance()                                                                                       # a failed queue attempt
    db, p = player()
    row = db.get(q.TaskQueue, (p.channel_id, p.twitch_uid))
    assert row.remaining == 0 and 'TASK FAILED' in row.result and m.material_amount(db, p, PLANKS.output) == 0
    db.close()
    assert goal() == PLANKS.id and not [t for t in notes() if 'Goal complete' in t]
    monkeypatch.setattr(m.random, 'random', lambda: 0.5)
    m.queued_tasks(W, '111', 'Kam', 'start', 'work:train_wood_processing', '1', 'discord')
    advance()                                                                                       # this one succeeds
    assert goal() is None and len([t for t in notes() if 'Goal complete: Wood Planks' in t]) == 1


# ---------------------------------------------------------------- progress since the goal was set

def test_progress_counts_steps_done_since_the_goal_was_set():
    citizen(lumber=0)
    set_goal(CAMPFIRE.id)
    db, p = player()
    steps = extras.walkthrough(db, p)[1]
    db.close()
    assert [st['name'] for st in steps] == ['Gather Lumber ×2', 'Craft Campfire'] and progress_row() == (CAMPFIRE.id, 2, 0)
    view = press(ui.cid('111', 'gv'))['data']
    assert '░░░░░░░░░░ 0 of 2 steps done · ❌ need 2 Lumber' in screen_text(view)
    stock({LUMBER: 2})
    view = press(ui.cid('111', 'gv'))['data']
    assert '█████░░░░░ 1 of 2 steps done · ✅ ready' in screen_text(view) and 'Last Step' in screen_text(view)
    assert chat_line().startswith('🎯 Goal Campfire 1/2 steps | Next: Craft Campfire')


def test_progress_rises_when_more_steps_remain_than_at_the_start():
    citizen()                                                               # 10 Lumber: only the craft is left
    set_goal(CAMPFIRE.id)
    assert progress_row() == (CAMPFIRE.id, 1, 1)                            # ready when set: no ready note follows
    assert chat_line().startswith('🎯 Goal Campfire 0/1 step | ')
    stock({LUMBER: 0})                                                       # spent elsewhere: two steps again
    assert '0 of 2 steps done' in screen_text(press(ui.cid('111', 'gv'))['data'])
    assert progress_row() == (CAMPFIRE.id, 2, 1)                            # the start rose; done never goes below 0


def test_a_goal_set_before_progress_was_kept_gets_its_row_when_shown():
    citizen(lumber=0)
    db, p = player()
    extras.row(db, p.channel_id, p.twitch_uid, create=True).goal = CAMPFIRE.id       # the old way: no progress row
    db.commit()
    db.close()
    assert progress_row() is None
    assert chat_line().startswith('🎯 Goal Campfire 0/2 steps | Next: Gather Lumber ×2 (need 2)')
    assert progress_row() == (CAMPFIRE.id, 2, 0)


def test_twitch_target_shows_steps_done():
    seed()                                                                  # a Twitch citizen without Lumber
    line = m.target('test', 'u', 'Kamex', 'campfire', 'twitch').body.decode()
    assert line.startswith('🎯 Goal set: **Campfire**. ') and '🎯 Goal Campfire 0/2 steps | Next: Gather Lumber ×2 (need 2) | Then: Craft Campfire' in line
    stock({LUMBER: 2}, 'u', 'test', 'twitch')
    assert m.target('test', 'u', 'Kamex', '', 'twitch').body.decode().startswith('🎯 Goal Campfire 1/2 steps | Next: Craft Campfire')


def test_setting_the_same_goal_again_keeps_its_progress():
    citizen(lumber=0)
    set_goal(CAMPFIRE.id)
    stock({LUMBER: 2})
    set_goal(CAMPFIRE.id)
    assert progress_row() == (CAMPFIRE.id, 2, 0)
    assert 'Goal set' in set_goal(TOILET.id) and progress_row()[0] == TOILET.id


# ---------------------------------------------------------------- the ready note

def test_a_queue_that_gathers_the_last_ingredient_raises_one_private_note():
    citizen(lumber=0)
    set_goal(CAMPFIRE.id)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '4', 'discord')
    advance()
    assert notes('goal') == []                                              # 1 of 2 Lumber: not yet
    advance()
    ready = '**Your goal Campfire is ready to craft.** /menu → Craft → My goal.'
    assert notes('goal') == [ready] and progress_row()[2] == 1
    advance(); advance()                                                    # still ready: never again for this goal
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert not extras.goal_ready_check(db, p)
        assert [i.text for i in inbox.pending(db, p.channel_id, p.twitch_uid) if i.kind == 'goal'] == [ready]   # pops up ('important')
        assert inbox.popup_embed(inbox.pending(db, p.channel_id, p.twitch_uid))['description'].count('🎯 ' + ready) == 1
        inbox.prefs(db, p.channel_id, p.twitch_uid, create=True).popups = 'all'
        assert [i.text for i in inbox.pending(db, p.channel_id, p.twitch_uid) if i.kind == 'goal'] == [ready]
        inbox.prefs(db, p.channel_id, p.twitch_uid).popups = 'off'
        assert inbox.pending(db, p.channel_id, p.twitch_uid) == []            # off: nothing pops up…
        assert '🎯 **Your goal Campfire is ready to craft.**' in inbox.inbox_text(db, p)      # …it waits in Notifications
        assert not [n for n in db.query(qn.Notice) if 'ready to craft' in n.content]             # and no DM
        db.commit()
    assert notes('goal') == [ready]


def test_the_note_rearms_only_when_the_goal_is_set_again():
    citizen(lumber=0)
    set_goal(CAMPFIRE.id)
    stock({LUMBER: 2})
    inbox.after_command('111', 'Kam', 'gather', {}, '')                  # after an interactive command
    assert len(notes('goal')) == 1
    set_goal(CAMPFIRE.id)                                                   # the same goal again: unchanged
    inbox.after_command('111', 'Kam', 'gather', {}, '')
    assert len(notes('goal')) == 1
    press(ui.cid('111', 'gc'))
    stock({LUMBER: 0})
    press(ui.cid('111', 'gs', CAMPFIRE.id))                                 # cleared and set again: armed
    stock({LUMBER: 2})
    with m.SessionLocal() as db:                                            # the check on each Discord interaction (before popups)
        extras.touch(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        db.commit()
    inbox.after_command('111', 'Kam', 'gather', {}, '')
    assert len(notes('goal')) == 2


def test_a_goal_set_while_ready_gets_no_note():
    citizen()
    press(ui.cid('111', 'gs', CAMPFIRE.id))
    inbox.after_command('111', 'Kam', 'gs', {}, '')
    assert notes('goal') == []


# ---------------------------------------------------------------- the goal and the shopping list

def test_the_goal_screen_adds_the_goal_to_the_shopping_list():
    citizen(lumber=0)
    view = press(ui.cid('111', 'gs', CAMPFIRE.id))['data']
    add = find(view, 'Add to shopping list')
    assert add['custom_id'] == ui.cid('111', 'la', CAMPFIRE.id) and add['emoji'] == {'name': '🛒'}
    entry = press(add['custom_id'])['data']
    assert 'Added to your shopping list: 1 Campfire' in screen_text(entry)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert [(r.recipe_id, r.want) for r in shop.entries(db, p)] == [(CAMPFIRE.id, 1)]
    assert find(entry, 'My goal')['custom_id'] == ui.cid('111', 'gv')            # it is the goal: back to it
    again = press(ui.cid('111', 'gv'))['data']
    listed = find(again, 'On shopping list')
    assert listed['label'] == 'On shopping list · want 1' and listed['custom_id'] == ui.cid('111', 'li', CAMPFIRE.id)
    assert 'Already on your shopping list' in screen_text(press(ui.cid('111', 'la', CAMPFIRE.id))['data'])


def test_a_shopping_list_entry_sets_the_goal():
    citizen(lumber=0)
    with m.SessionLocal() as db:
        shop.set_entry(db, m.player(db, W, 'discord', '111', 'Kam')[1], TOILET.id, 2)
        db.commit()
    entry = press(ui.cid('111', 'li', TOILET.id))['data']
    button = find(entry, 'Set as goal')
    assert button['custom_id'] == ui.cid('111', 'gs', TOILET.id) and button['emoji'] == {'name': '🎯'}
    view = press(button['custom_id'])['data']
    assert 'Goal set: Crude Wood Toilet' in screen_text(view) and goal() == TOILET.id
    db, p = player()
    steps = extras.walkthrough(db, p)[1]
    db.close()
    assert progress_row() == (TOILET.id, len(steps), 0) and f'0 of {len(steps)} steps done' in screen_text(view)
    assert find(view, 'On shopping list')['label'] == 'On shopping list · want 2'


def test_the_changed_screens_keep_discords_limits():
    citizen(lumber=0)
    stock({s.key('Metalworking Bench'): 1, s.key('Basic Anvil'): 1})
    deep = press(ui.cid('111', 'gs', ORE_SCANNER.id))['data']                # two rows of step buttons, then the tools
    assert labels(deep)[-6:] == ['Goal recipe', 'Add to shopping list', 'Refresh', 'Clear goal', 'Back', 'Menu']
    screens = [deep, press(ui.cid('111', 'gv'))['data'], press(ui.cid('111', 'la', ORE_SCANNER.id))['data'],
               press(ui.cid('111', 'li', ORE_SCANNER.id))['data'], press(ui.cid('111', 'li', TOILET.id))['data']]
    for data in screens:
        assert rows_ok(data) and assert_valid(v2.convert(ui.tidy(json.loads(json.dumps(data)))))
    for e in wb.index():                                                    # every recipe fits a 20-digit Discord id
        for verb in ('gs', 'la', 'li'):
            ui.cid('9' * 20, verb, e.id)


# ---------------------------------------------------------------- one plan per screen

def test_each_goal_screen_plans_the_goal_once(monkeypatch):
    citizen(lumber=0)
    real, calls = extras.walkthrough, []
    monkeypatch.setattr(extras, 'walkthrough', lambda *args, **kw: calls.append(1) or real(*args, **kw))

    def count(fn):
        calls.clear()
        fn()
        return len(calls)
    assert count(lambda: press(ui.cid('111', 'gs', ORE_SCANNER.id))) == 1                  # set, store the start, show
    assert count(lambda: press(ui.cid('111', 'gv'))) == 1
    assert count(lambda: m.target(W, '111', 'Kam', '', 'discord')) == 1
    assert count(lambda: m.status_view(W, '111', 'Kam', 'discord')) == 1
    seed()                                                                                  # Twitch: set, then the line
    assert count(lambda: m.target('test', 'u', 'Kamex', 'ore scanner', 'twitch')) == 1
    assert count(lambda: m.target('test', 'u', 'Kamex', '', 'twitch')) == 1
    assert count(lambda: m.status_view('test', 'u', 'Kamex', 'twitch')) == 1


# ---------------------------------------------------------------- account linking

def test_linking_moves_the_progress_with_the_goal():
    def link(source_uid, target_uid='111'):
        with m.SessionLocal() as db:
            source, target = (m.player(db, W, 'discord', u, 'Kam')[1].twitch_uid for u in (source_uid, target_uid))
            q.merge_accounts(db, W, source, target)
            db.commit()
            assert db.get(extras.GoalProgress, (W, source)) is None
            found = db.get(extras.GoalProgress, (W, target))
            return (found.recipe_id, found.start_steps) if found else None
    citizen(lumber=0)
    citizen('222', lumber=0)
    set_goal(CAMPFIRE.id, '222')
    assert link('222') == (CAMPFIRE.id, 2) and goal() == CAMPFIRE.id        # the target had none: it moves with the goal
    citizen('333', lumber=0)
    set_goal(TOILET.id, '333')
    assert link('333') == (CAMPFIRE.id, 2) and goal() == CAMPFIRE.id        # both have one: the target's wins
    citizen('444', lumber=0)
    citizen('555', lumber=0)
    with m.SessionLocal() as db:                                            # a progress row alone (no other goal state) moves too
        p = m.player(db, W, 'discord', '444', 'Kam')[1]
        db.add(extras.GoalProgress(channel_id=W, canonical_uid=p.twitch_uid, recipe_id=TOILET.id, start_steps=3, set_at=m.now()))
        db.commit()
    assert link('444', '555') == (TOILET.id, 3)
