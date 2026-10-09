"""Every Discord result for a task that was performed starts with a heading, and the heading takes the owner's custom
emoji (app/custom_emoji.py swaps the mark of '### ✅ …' / '### ❌ …'). A task result with no heading gets no emoji, which
is how a failed Ore Mining started from a button went without one.

The audit runs each path as Discord does, with a fake emoji list and nothing sent anywhere:

* every task slash command the game offers (derived from the command catalog and the game's own task tables), through
  the routing the interactions webhook applies and then discord_deferred.finish, and again as a menu button
  ({'do': 'cmd', 'raw': …}, which is what the menu's action buttons and Again press);
* the buttons in ui.run_ticket that perform a task: training (the live bug), gathering and crafting, and Again;
* the alert a finished queue sends (discord_queue_worker), 🦆 and 🪨 in text, and what is not a task result.

random.random is forced (0.0 passes every roll, 0.999 misses every roll that can miss). The database is made once for
the module instead of before each test, and each case uses a new citizen, so the ~400 cases take seconds.
"""
import itertools
import re
from datetime import timedelta
import pytest
from test_colony import m
from test_layout_v2 import Reply
from app import (command_catalog, crafting_progression as cp, custom_emoji as ce, discord_deferred as deferred,
                 discord_queue_worker as worker, layout_v2 as v2, presentation, queue_notifications as notices,
                 seed_content as sc, task_queue as queue, task_yields, ui, workbench as wb)
from app.competencies import FIELDS
from app.game.cooldowns_materials import available_production_orders
from app.game.discord_commands import WORK_ROUTES, _discord_options, _discord_user, discord_legacy_route
from app.game.rules import ACTION_SKILLS
from app.game.world import society_tier_index, world_clock
from app.seed_skills import TASKS

W = m.DISCORD_WORLD_ID
DONE = {'seemsgoodmelisa': '11', 'JohnShades': '12'}
FAILED = {'andyevillaugh': '21', 'JJhydrate': '22', 'JJLUL': '23'}
FAKE = {**DONE, **FAILED, 'duck': '31', 'Rocky': '32'}
TAGS = {'done': {f'<:{n}:{i}>' for n, i in DONE.items()}, 'failed': {f'<:{n}:{i}>' for n, i in FAILED.items()}}
SUCCEED, FAIL = 0.0, 0.999
NUMBER = itertools.count(1000)
GENERIC = {'Task complete', 'Task failed'}      # the title of last resort: a path that ends with one needs a name of its own


@pytest.fixture(scope='module', autouse=True)
def world():
    """One clean database for the module, with the first-steps, community and lucky-find rewards off (as test_colony does)."""
    mp = pytest.MonkeyPatch()
    for key in ('DISCORD_BOT_TOKEN', 'DISCORD_APPLICATION_ID'):
        mp.delenv(key, raising=False)
    mp.setattr(m, 'OVERLAY_CACHE_SECONDS', 0)
    for system in (m.onboarding, m.community, m.practice, m.twitch_lite):
        mp.setattr(system, 'ENABLED', False)
    m.Base.metadata.drop_all(m.engine)
    m.Base.metadata.create_all(m.engine)
    m.migrate_schema()
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def emoji(monkeypatch):
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    ce.reset()
    ce.set_table(FAKE)
    yield
    ce.reset()


class Seen:
    """The text of every card the game built for the reply (presentation.card), as (text, command, shape)."""
    def __init__(self):
        self.cards = []

    def outcome(self):
        return 'failed' if any(re.search('FAILED', text[:160]) for text, _, _ in self.cards) else 'done'


@pytest.fixture
def seen(monkeypatch):
    spy = Seen()
    real = presentation.card

    def card(content, command=''):
        found = real(content, command)
        spy.cards.append((content, command, found[1]))
        return found
    monkeypatch.setattr(presentation, 'card', card)
    return spy


# ---------------------------------------------------------------- the message as Discord gets it

def lines(data):
    out = []

    def walk(nodes):
        for node in nodes or []:
            if node.get('type') == v2.TEXT:
                out.extend(node['content'].split('\n'))
            walk(node.get('components'))
    walk(data.get('components'))
    return out


def heading(data):
    return next((x for x in lines(data) if x.startswith('### ')), None)


def assert_heading(data, outcome, where, label=None):
    """The first heading is '### <custom emoji of the right list> <title>'; returns the title."""
    assert v2.is_v2(data), where
    found = heading(data)
    assert found, f'{where}: no heading; the card starts {lines(data)[:2]}'
    parts = re.fullmatch(r'### (<a?:\w+:\d+>) (.+)', found)
    assert parts, f'{where}: the heading has no custom emoji: {found!r}'
    assert parts[1] in TAGS[outcome], f'{where}: wanted a {outcome} emoji, got {found!r}'
    assert parts[2] not in GENERIC, f'{where}: only the generic title {found!r}'
    if label is not None:
        assert parts[2] == label, f'{where}: {found!r}'
    return parts[2]


def assert_plain(data, where):
    """No ✅/❌ heading took a custom emoji (menus, cooldowns and refusals are not task results)."""
    found = heading(data)
    assert not found or not re.match(r'### <a?:\w+:\d+>', found), f'{where}: {found!r}'


# ---------------------------------------------------------------- citizens and what they press

def citizen(task=None, partner=False, food='', gear=(), damaged=(), name='Kam', needs=70, stock=None, tools=True):
    """A citizen with what tasks ask for: crops, ore, cargo, a Business, a Sensor, an extractor, every kept tool (unless
    tools=False) and, for a training task, its workstation, level and materials. Needs sit at `needs`."""
    uid = str(next(NUMBER))
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', uid, name)
        p.sc = 10000
        p.crops = p.ore = p.components = p.cargo = p.rare_ore = 100
        life = m.life_state(db, p)
        for k in ('energy', 'nutrition', 'comfort', 'social', 'morale'):
            setattr(life, k, needs)
        db.add(m.Business(channel_id=W, canonical_uid=p.twitch_uid, name='Test Business'))
        m.item_add(db, W, p.twitch_uid, 'sensor', 1)
        m.material_change(db, p, cp.SMALL_EXTRACTOR, 1)
        m.material_change(db, p, 'power_cell', 5)
        for key in task_yields.EQUIPMENT.values() if tools else ():
            if key in m.QUALITY_RECIPES:
                db.add(m.QualityGear(channel_id=W, canonical_uid=p.twitch_uid, item_key=key, item_name=key, quality='Standard', qty=1))
            else:
                m.material_change(db, p, key, 1)
        for key in gear:
            db.add(m.QualityGear(channel_id=W, canonical_uid=p.twitch_uid, item_key=key, item_name=key, quality='Standard', qty=2))
        for key in damaged:
            db.add(m.QualityGear(channel_id=W, canonical_uid=p.twitch_uid, item_key=key, item_name=key, quality='Standard', qty=1, condition=40))
        for key, amount in (stock or {}).items():
            m.material_change(db, p, key, amount)
        if food:
            m.material_change(db, p, food, 3)
        if task in TASKS:
            cfg = TASKS[task]
            tag = cp.TRAINING_STATIONS.get(cfg['branch'])
            if tag:
                m.material_change(db, p, cp.permit_key(tag), 1)
                db.add(m.CraftLedger(channel_id=W, canonical_uid=p.twitch_uid, recipe='component', qty=250, best_quality=''))
            if task in m.MERGED_TRAINING:
                rid = m.MERGED_TRAINING[task]
                m.material_change(db, p, cp.permit_key(cp.tags(rid)[0]), 1)
                _, branch = sc.SKILLS[sc.RECIPES[rid]['requirement'].get('Skill', 'SK_CRAFTING')]
                if branch:
                    m.gain_branch(db, p, branch, 1000)
            setattr(p, FIELDS[cfg['skill']], next(x for x in range(1000) if m.lvl(x) >= cfg['unlock']))
            for key, amount in cfg['cost'].items():
                m.material_change(db, p, key, max(0, amount - m.material_amount(db, p, key)))
        db.commit()
    if partner:
        with m.SessionLocal() as db:
            m.player(db, W, 'discord', uid + '9', 'Pal' + uid)
            if partner == 'mentor':             # a mentor has to be better than the learner at their weakest skill
                p = m.player(db, W, 'discord', uid, name)[1]
                for field in FIELDS.values():
                    setattr(p, field, 500)
            db.commit()
    return uid


def cool_down():
    """Ready for the same task again: no cooldowns, and any gear repaired a moment ago worn down again."""
    with m.SessionLocal() as db:
        db.query(m.Cooldown).delete()
        db.query(m.QualityGear).filter(m.QualityGear.item_key == 'toolkit').update({'condition': 40})
        db.commit()


def capture(monkeypatch):
    sent = []
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(200))
    monkeypatch.setattr(deferred.requests, 'post', lambda url, json, timeout: sent.append(json) or Reply(200))
    return sent


def slash(monkeypatch, command, options, uid, name='Kam'):
    """/command as the interactions webhook hands it on (its options read, grouped commands routed) and as
    discord_deferred.finish answers it: the message Discord is sent."""
    sent = capture(monkeypatch)
    payload = {'type': 2, 'id': 'i' + str(next(NUMBER)), 'application_id': 'a', 'token': 't', 'channel_id': '5',
               'member': {'user': {'id': uid, 'username': name}},
               'data': {'name': command, 'options': [{'name': k, 'type': 3, 'value': v} for k, v in options.items()]}}
    user, shown = _discord_user(payload)
    routed, flat = discord_legacy_route(command, _discord_options(payload))
    deferred.finish(payload, routed, user, shown, flat)
    return sent[-1]


def press(monkeypatch, custom_id, uid):
    """A button on a private newer-layout message, answered as Discord's deferred worker does."""
    sent = capture(monkeypatch)
    payload = {'type': 3, 'id': 'b' + str(next(NUMBER)), 'application_id': 'a', 'token': 't', 'channel_id': '5',
               'data': {'custom_id': custom_id, 'values': []}, 'member': {'user': {'id': uid, 'username': 'Kam'}},
               'message': {'flags': 64 | v2.FLAG}}
    deferred.answer_later(payload)
    return sent[-1]


def ticket(uid, action):
    return ui.cid(uid, 't', ui.issue(uid, action))


def button(data, label):
    return next((b['custom_id'] for b in v2.controls(data) if (b.get('label') or '').startswith(label)), None)


# ---------------------------------------------------------------- the task slash commands, from the catalog

def choices(command, option):
    row = next(c for c in command_catalog.commands if c['name'] == command)
    return [c['value'] for o in row['options'] if o['name'] == option for c in o.get('choices', [])]


FOOD = next(k for k in sorted(sc.EDIBLE) if k in sc.GATHER)
USES = {}                                               # one item for each way an item is used (/use)
for _key in sorted(sc.ACTIVE):
    USES.setdefault(sc.PURPOSE[_key]['mode'], _key)
SUPPLIES = {sc.source_key('GMT_MATERIAL_PROCESSED_WATER'): 5, sc.source_key('GMT_PRODUCT_TOOL_SCANNER_BATTERY'): 5}
CAMPFIRE = next(e for e in wb.index() if e.name == 'Campfire' and cp.SURVIVAL in e.tags)


def case(command, options, **setup):
    return command, options, setup


CASES = [case('work', {'task': t}) for t in choices('work', 'task')]
for _action in choices('life', 'action'):
    if _action == 'eat':
        CASES.append(case('life', {'action': 'eat', 'food': sc.item_label(FOOD)}, food=FOOD))
    elif _action == 'hobby':
        CASES += [case('life', {'action': 'hobby', 'hobby': h}) for h in choices('life', 'hobby')]
    elif _action not in {'trick', 'recover'}:           # Halloween only; recover is its own test (it needs low needs)
        CASES.append(case('life', {'action': _action}))
CASES += [case('business', {'action': a}) for a in choices('business', 'action') if a not in {'view', 'start'}]
CASES += [case('market', {'action': a}) for a in choices('market', 'action') if a != 'view']
CASES += [case('repair', {'target': 'society'}), case('repair', {'target': 'gear', 'item': 'toolkit'}, damaged=['toolkit'])]
CASES += [case('social', {'action': a, 'player': 'PARTNER'}, partner='mentor' if a == 'mentor' else True)
          for a in choices('social', 'action') if a != 'group_games' and not a.startswith('duo_')]
CASES += [case('social', {'action': 'group_games'}, gear=['recreation_set'])]
CASES += [case('use', {'item': sc.item_label(key)}, stock={key: 3, **SUPPLIES}) for mode, key in USES.items()
          if mode not in {'ingredient', 'workshop', 'eat'}]
CASES += [case('training', {'skill': cfg['hub'], 'task': key}, task=key) for key, cfg in TASKS.items()]
CASES += [case('make', {'recipe': CAMPFIRE.name, 'action': 'craft'}, stock=CAMPFIRE.inputs)]
MENU_ONLY = [case('eatfull', {}, food=FOOD)]              # a menu button; the command is not in the slash catalog


def params(rows):
    return [pytest.param(*row, id=row[0] + ':' + ','.join(str(v)[:24] for v in row[1].values())) for row in rows]


SLASH, MENU = params(CASES), params(CASES + MENU_ONLY)


def expected(command, options, roll):
    """'failed' only for a task that rolls to succeed and is made to miss; everything else finishes."""
    routed, flat = discord_legacy_route(command, options)
    routed = presentation.action_command(routed, flat)
    rolls = (routed in ACTION_SKILLS and routed not in {'eat', 'sleep'}) or routed == 'training'
    rolls = rolls and not (routed == 'business' and flat.get('action') == 'invest') and flat.get('target') != 'gear'
    return 'failed' if roll == FAIL and rolls else 'done'


def prepare(options, setup):
    uid = citizen(**setup)
    return uid, dict(options, player='Pal' + uid) if options.get('player') == 'PARTNER' else options


@pytest.mark.parametrize('roll', [SUCCEED, FAIL], ids=['pass', 'miss'])
@pytest.mark.parametrize('command,options,setup', SLASH)
def test_a_task_slash_command_ends_with_the_emoji_heading(monkeypatch, seen, command, options, setup, roll):
    monkeypatch.setattr(m.random, 'random', lambda: roll)
    uid, options = prepare(options, setup)
    data = slash(monkeypatch, command, options, uid)
    outcome = expected(command, options, roll)
    assert seen.outcome() == outcome, (command, options, seen.cards[-1][0][:160])
    title = assert_heading(data, outcome, f'/{command} {options}')
    if command == 'training':               # the task's own name, never a generic title
        assert title == TASKS[options['task']]['label'] + (' failed' if outcome == 'failed' else '')
    if button(data, 'Again'):               # the Again button under the result runs the task once more
        cool_down()
        assert_heading(press(monkeypatch, button(data, 'Again'), uid), outcome, f'Again after /{command} {options}')


@pytest.mark.parametrize('roll', [SUCCEED, FAIL], ids=['pass', 'miss'])
@pytest.mark.parametrize('command,options,setup', MENU)
def test_a_menu_button_runs_the_same_task_with_the_same_heading(monkeypatch, seen, command, options, setup, roll):
    """What the menu's action buttons press: the command and its options as a one-time ticket (menu.run)."""
    monkeypatch.setattr(m.random, 'random', lambda: roll)
    uid, options = prepare(options, setup)
    data = press(monkeypatch, ticket(uid, {'do': 'cmd', 'raw': [command, options]}), uid)
    assert seen.outcome() == expected(command, options, roll)
    assert_heading(data, expected(command, options, roll), f'menu button for /{command} {options}')


def test_the_cases_cover_the_catalog():
    """A new task choice in the catalog fails here until it is run above."""
    skipped = {('life', 'trick'), ('life', 'recover'), ('business', 'view'), ('business', 'start'), ('market', 'view')}
    skipped |= {('social', a) for a in choices('social', 'action') if a.startswith('duo_')}
    ran = {(command, options.get('action') or options.get('task')) for command, options, _ in CASES}
    assert set(choices('work', 'task')) == set(WORK_ROUTES)
    for command, option in (('work', 'task'), ('life', 'action'), ('business', 'action'), ('market', 'action'), ('social', 'action')):
        for value in choices(command, option):
            assert (command, value) in ran | skipped, (command, value)
    assert {options['task'] for command, options, _ in CASES if command == 'training'} == set(TASKS)


def test_a_production_order_is_a_receipt(monkeypatch, seen):
    uid = citizen()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid, 'Kam')[1]
        key, order = available_production_orders(W, world_clock(db, W)['day'], society_tier_index(m.society(db, W)))[0]
        for material, amount in order['cost'].items():
            m.material_change(db, p, material, amount)
        db.commit()
    data = slash(monkeypatch, 'seedindustries', {'action': 'fulfill', 'item': key}, uid)
    assert_heading(data, 'done', 'production order', 'Production order delivered')


# ---------------------------------------------------------------- buttons that perform a task (ui.run_ticket)

@pytest.mark.parametrize('roll', [SUCCEED, FAIL], ids=['pass', 'miss'])
@pytest.mark.parametrize('task', list(TASKS))
def test_the_training_button_and_its_again_button(monkeypatch, seen, task, roll):
    """The live bug: a failed Ore Mining started from a button had no heading, so no emoji."""
    monkeypatch.setattr(m.random, 'random', lambda: roll)
    uid = citizen(task)
    outcome = 'failed' if roll == FAIL else 'done'
    label = TASKS[task]['label'] + (' failed' if outcome == 'failed' else '')
    data = press(monkeypatch, ticket(uid, {'do': 'train', 'skill': TASKS[task]['hub'], 'task': task}), uid)
    assert seen.outcome() == outcome
    assert_heading(data, outcome, f'Start {task}', label)
    assert 'TASK COMPLETE' not in '\n'.join(lines(data)) and 'TASK FAILED' not in '\n'.join(lines(data))
    cool_down()
    with m.SessionLocal() as db:        # a pass used up the materials; the player has them again
        p = m.player(db, W, 'discord', uid, 'Kam')[1]
        for key, amount in TASKS[task]['cost'].items():
            m.material_change(db, p, key, max(0, amount - m.material_amount(db, p, key)))
        db.commit()
    assert_heading(press(monkeypatch, button(data, 'Again'), uid), outcome, f'Again {task}', label)


@pytest.mark.parametrize('item', [k for k in sc.GATHER if k not in queue.ores()])
def test_the_gather_button_and_a_second_press(monkeypatch, seen, item):
    monkeypatch.setattr(m.random, 'random', lambda: SUCCEED)
    uid = citizen()
    data = press(monkeypatch, ticket(uid, {'do': 'gather', 'item': item}), uid)
    assert_heading(data, 'done', f'Gather {item}', 'Gathered ' + sc.item_label(item))
    cool_down()
    assert_heading(press(monkeypatch, button(data, 'Gather'), uid), 'done', f'Gather {item} again')


def test_the_craft_button(monkeypatch, seen):
    uid = citizen(stock=CAMPFIRE.inputs)
    data = press(monkeypatch, ticket(uid, {'do': 'craft', 'recipe': CAMPFIRE.id, 'back': []}), uid)
    assert_heading(data, 'done', 'Craft button', 'Crafted Campfire')


# ---------------------------------------------------------------- the alert a finished queue sends

def finished_alerts(roll, monkeypatch):
    monkeypatch.setattr(m.random, 'random', lambda: roll)
    uid = citizen()
    assert 'TASK QUEUE' in m.queued_tasks(W, uid, 'Kam', 'start', 'mine:' + sorted(queue.ores())[0], 2, 'discord').body.decode()
    for _ in range(4):
        with m.SessionLocal() as db:
            for row in db.query(queue.TaskQueue):
                row.next_at = m.now() - timedelta(seconds=1)
            for row in db.query(m.Cooldown):
                row.ready_at = m.now() - timedelta(seconds=1)
            db.commit()
        queue.tick()
    with m.SessionLocal() as db:
        found = [r.id for r in db.query(notices.Notice).filter(notices.Notice.recipient == uid)]
    assert found
    return [worker.claim(notice_id) for notice_id in found]


@pytest.mark.parametrize('roll', [SUCCEED, FAIL], ids=['pass', 'miss'])
def test_a_finished_queue_alert(monkeypatch, roll):
    for notice in finished_alerts(roll, monkeypatch):
        data, mention = worker.payload(notice)
        body = worker.v2_body(data, mention, notice, dm=True)
        assert_heading(body, 'done', 'queue alert', 'Queue completed')      # finished, whether or not every attempt hit


def test_alerts_that_are_not_a_finished_task_keep_their_marks():
    for state, mark in (('PAUSED', '⏸️'), ('CANCELLED', '⏹️'), ('STOPPED', '⛔')):
        notice = type('N', (), {'id': 'a' * 32, 'recipient': '1', 'message_channel': '', 'channel_id': W,
                                'content': f'TASK QUEUE — {state}\nMine Coal\nAttempts completed: 1/2; remaining: 1.\n'
                                           'PAUSE REASON\nEnergy: 18/100; need 20.'})()
        data, mention = worker.payload(notice)
        body = worker.v2_body(data, mention, notice)
        assert heading(body).startswith(f'### {mark} ') and '<:' not in heading(body)


# ---------------------------------------------------------------- 🦆 and 🪨 end to end

def test_the_duck_in_a_reply_is_the_duck_emoji(monkeypatch):
    uid = citizen()
    data = slash(monkeypatch, 'ducks', {'duck': 'Hueburt'}, uid)
    assert any(x.startswith('<:duck:31> Hueburt is now Kam') for x in lines(data)), lines(data)[:3]
    assert '🦆' not in '\n'.join(lines(data))


def test_rocky_in_a_reply_is_the_rocky_emoji(monkeypatch):
    uid = citizen(name='Solo')
    data = slash(monkeypatch, 'social', {'action': 'hangout', 'player': 'Solo'}, uid, name='Solo')
    assert any(x.startswith('<:Rocky:32> Solo Rocky contemplation') for x in lines(data)), lines(data)[:3]
    assert '🪨' not in '\n'.join(lines(data))


# ---------------------------------------------------------------- what is not a task result

NOT_RESULTS = [
    ('menu', 'training', {'skill': 'farming'}), ('menu', 'training', {}), ('menu', 'mine', {'action': 'view'}),
    ('menu', 'life', {'action': 'eat'}), ('menu', 'social', {'action': 'hi'}), ('menu', 'make', {'category': 'food'}),
    ('asks for a choice', 'mine', {'action': 'mine'}), ('asks for a choice', 'queue', {'action': 'start'}),
    ('queue starting', 'queue', {'action': 'start', 'task': 'mine:' + sorted(queue.ores())[0], 'count': 1}),
    ('trade', 'seedindustries', {'action': 'sell', 'item': 'Lumber', 'amount': 1}),
]


@pytest.mark.parametrize('why,command,options', NOT_RESULTS, ids=[f'{c}:{w}' for w, c, _ in NOT_RESULTS])
def test_menus_refusals_and_trades_take_no_task_emoji(monkeypatch, why, command, options):
    data = slash(monkeypatch, command, options, citizen())
    assert_plain(data, f'/{command} {options}')


def test_a_task_without_its_tool_is_a_refusal_not_a_result(monkeypatch):
    data = slash(monkeypatch, 'work', {'task': 'farm_hydroponics'}, citizen(tools=False))
    assert_plain(data, 'hydroponics') and 'requires' in '\n'.join(lines(data))


def test_recovering_is_a_card_with_its_own_title(monkeypatch):
    data = slash(monkeypatch, 'life', {'action': 'recover'}, citizen(needs=10))
    assert heading(data) == '### 🩹 Recovery'


def test_a_cooldown_is_not_a_task_result(monkeypatch):
    monkeypatch.setattr(m.random, 'random', lambda: SUCCEED)
    uid = citizen()
    assert_heading(slash(monkeypatch, 'work', {'task': 'scan'}, uid), 'done', 'first scan')
    second = slash(monkeypatch, 'work', {'task': 'scan'}, uid)
    assert_plain(second, 'second scan') and 'ready in' in '\n'.join(lines(second))


def test_a_task_that_is_blocked_is_not_a_task_result(monkeypatch):
    data = slash(monkeypatch, 'work', {'task': 'scan'}, citizen(needs=2))
    assert_plain(data, 'tired scan')
