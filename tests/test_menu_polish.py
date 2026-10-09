"""Menu polish: the Daily contract screen and Do this next do the contract's task, the bag has its own tools under it,
Moderator lines sit under three headings, and More says how many buttons are left to unlock, closest first."""
import ast
import inspect
import re
from datetime import timedelta
import pytest
from test_colony import m, reset, seed, client
from test_workbench_ui import citizen, W
from test_layout_v2 import assert_valid
from test_menu_walk import walk, checked, select_values
from test_menu_walk import press as press_as_owner
from app import menu, ui, layout_v2 as v2, seed_content as s, crafting_progression as cp, task_queue as q
from app.game import cooldowns_materials as cm

ORE = next(k for k, v in s.GATHER.items() if v['branch'] == 'ore_mining' and k not in cp.RARE and s.ITEMS[k]['name'] == 'Hematite Ore')

# Every contract the game can roll (cooldowns_materials.daily) and the word on the button that does its task.
BUTTONS = {'harvest': 'Harvest', 'mine': 'Mine', 'research': 'Research', 'make': 'Ready to craft', 'delivery': 'Deliver', 'explore': 'Scout',
           'water': 'Irrigate', 'repair': 'Fix infrastructure', 'train_fire_safety': 'Train Fire Safety',
           'train_seed_cultivation': 'Train Seed Cultivation', 'train_ore_mining': 'Train Ore Mining'}
# What the Moderator screen shows the owner when no event or challenge is running, in order.
MOD_BUTTONS = ['Start event', 'Start stream challenge', 'Stream live…', 'Weekly recap preview', 'Post weekly recap now', 'Channel feed…',
               'Post guide panels', 'Post game panel', 'Moderator log', 'Unanswered questions', 'Account lookup', 'Force merge', 'Moderator help']


# ---------------------------------------------------------------- helpers

@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    citizen(lumber=40)
    citizen('222')
    with m.SessionLocal() as db:
        p = player(db)
        p.sc, p.crops, p.cargo = 5000, 5, 2
        db.commit()


def player(db, uid='111'):
    return m.player(db, W, 'discord', uid, 'Kam')[1]


def set_daily(action, target=3):
    with m.SessionLocal() as db:
        d = cm.daily(db, player(db))
        d.action, d.target, d.progress, d.complete, d.reward_sc = action, target, 0, False, target * 3
        db.commit()


def progress():
    with m.SessionLocal() as db:
        d = cm.daily(db, player(db))
        return d.progress, d.complete


def no_cooldowns():
    with m.SessionLocal() as db:
        db.query(m.Cooldown).delete()
        db.commit()


def shown(custom_id, values=None, newer=False):
    """Press a control and check the answer is a working screen Discord accepts. The answer is built in the old layout;
    the interaction endpoint turns it into the newer one (layout_v2.respond), so `newer` does the same here."""
    data = checked(custom_id, values)
    if not newer:
        return data
    out = v2.convert(data)
    assert out is not None and assert_valid(out), custom_id
    return out


def buttons(data):
    return [c for c in v2.controls(data) if c.get('type') == 2]


def labels(data):
    return [c.get('label') for c in buttons(data)]


def beside(data, text):
    """The button beside the line that has `text`, in the newer layout."""
    for c in walk(data.get('components')):
        if c.get('type') == v2.SECTION and text in ' '.join(t.get('content', '') for t in c['components']):
            return c['accessory']
    return None


def task_button(data, newer):
    """What the Daily contract screen offers: beside its Task line in the newer layout, the first row in the old one."""
    return beside(data, 'Task:') if newer else data['components'][0]['components'][0]


def daily_screen(newer=False):
    return shown(ui.cid('111', 'mv', 'me_daily'), newer=newer)


def headings(data):
    lines = [x.strip().strip('*').strip() for x in v2.text_of(data).split('\n')]
    return [x for x in lines if x in {'Events', 'Posts', 'Records'}]


def press_as(uid, custom_id, newer=False):
    """Another citizen (no owner or moderator rights) presses a control."""
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': []}, 'member': {'user': {'id': uid, 'username': 'Ana'}, 'permissions': '0'},
               'message': {'flags': 64}}
    data = ui.handle_component(payload)['data']
    return v2.convert(data) if newer else data


# ---------------------------------------------------------------- 1. Daily contract: a button that does it

def rolled():
    source = inspect.getsource(cm.daily)
    return ast.literal_eval('[' + re.search(r'random\.choice\(\[(.*?)\]\)', source)[1] + ']')


def test_every_contract_the_game_rolls_has_a_button_and_this_test_knows_it():
    actions = rolled()
    assert 'mine' in actions and set(actions) == set(BUTTONS)
    for action in actions:
        assert menu.daily_leaf(action) in menu.LEAVES, action
    assert [menu.daily_leaf(a) for a in ('harvest', 'mine', 'research', 'make', 'craft', 'delivery', 'explore', 'water', 'repair')] == [
        'w_farm_harvest', 'mine', 'w_research', 'ready', 'ready', 'w_delivery', 'w_scout', 'w_farm_irrigate', 'repair']
    assert menu.daily_leaf('train_fire_safety') == 'trainskill' and menu.daily_leaf('delivery', has_cargo=False) == 'w_cargo'
    assert menu.daily_leaf('something_new') == ''
    for leaf_, _ in menu.DAILY_LEAF.values():
        assert menu.LEAVES[leaf_]['kind'] in {'do', 'pick', 'nav'}, leaf_


@pytest.mark.parametrize('newer', [False, True])
@pytest.mark.parametrize('action', list(BUTTONS))
def test_the_daily_screen_names_the_task_and_has_the_button_that_does_it(owner, action, newer):
    set_daily(action)
    data = daily_screen(newer)
    text = v2.text_of(data)
    assert cm.action_display_name(action) in text and 'Next: use' not in text and 'Contract complete' not in text
    button = task_button(data, newer)
    assert button is not None and button['label'] == BUTTONS[action] and button['style'] == 3
    assert button['custom_id'].startswith('ne|111|')                      # a real control of this citizen's menu
    shown(button['custom_id'], newer=newer)                              # pressing it opens a working screen (or does the task)


@pytest.mark.parametrize('action', ['harvest', 'research', 'delivery', 'explore', 'water', 'repair', 'train_fire_safety'])
def test_pressing_the_task_button_advances_the_contract(owner, action):
    set_daily(action, 5)
    no_cooldowns()
    button = task_button(daily_screen(), False)
    assert button['custom_id'].startswith('ne|111|t|')                    # a one-time ticket: it does the task itself
    press_as_owner(button['custom_id'])
    assert progress() == (1, False)


def test_the_mine_button_leads_to_mining_that_counts():
    citizen()
    set_daily('mine', 5)
    button = task_button(daily_screen(), False)
    assert button['custom_id'] == ui.cid('111', 'mk', 'mine')
    assert ORE in select_values(checked(button['custom_id']))
    panel = checked(ui.cid('111', 'mp', 'mine'), [ORE])
    press_as_owner(next(c for c in buttons(panel) if c.get('label') == 'Mine ×1')['custom_id'])
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        row.next_at = m.now() - timedelta(seconds=1)
        who = row.canonical_uid
        db.commit()
    q.run_one(W, who)                                                      # the queue's one attempt (random.random is 0.5: it succeeds)
    assert progress() == (1, False)


def test_a_delivery_without_cargo_offers_to_prepare_some_and_that_does_not_count(owner):
    with m.SessionLocal() as db:
        player(db).cargo = 0
        db.commit()
    set_daily('delivery')
    no_cooldowns()
    data = daily_screen()
    button = task_button(data, False)
    assert button['label'] == 'Prepare Cargo' and 'prepare some first' in v2.text_of(data)
    press_as_owner(button['custom_id'])
    with m.SessionLocal() as db:
        assert player(db).cargo == 1
    assert progress() == (0, False)                                        # only the delivery itself counts
    assert task_button(daily_screen(), False)['label'] == 'Deliver'


def test_a_training_contract_opens_the_skills_tasks_when_one_ticket_cannot_start_it(owner, monkeypatch):
    from app.game import training_and_items as ti
    real = ti.training_tasks
    monkeypatch.setattr(ti, 'training_tasks', lambda db, p, hub, provider='twitch': [dict(t, status='❌') for t in real(db, p, hub, provider)])
    set_daily('train_fire_safety')
    button = task_button(daily_screen(), False)
    assert button['label'] == 'Train Fire Safety' and button['custom_id'] == ui.cid('111', 'mp', 'trainskill', '=emergency')
    assert 'FIRE SAFETY' in v2.text_of(checked(button['custom_id'])).upper()


@pytest.mark.parametrize('newer', [False, True])
def test_a_finished_contract_has_no_button_and_says_it_is_done(owner, newer):
    set_daily('mine')
    with m.SessionLocal() as db:
        cm.daily(db, player(db)).complete = True
        db.commit()
    data = daily_screen(newer)
    # Work's own Mine (grey, a list) is there now; the green Mine that does the contract's task is not.
    assert 'Contract complete' in v2.text_of(data) and beside(data, 'Task:') is None
    assert not [b for b in buttons(data) if b.get('label') == 'Mine' and b.get('style') == 3]


@pytest.mark.parametrize('newer', [False, True])
def test_home_do_this_next_does_the_contract_task(owner, newer):
    set_daily('harvest')
    no_cooldowns()
    home = shown(ui.cid('111', 'mn', 'home'), newer=newer)
    assert "contract: Harvest Pumpkins 0/3" in v2.text_of(home)            # the card line stays
    button = beside(home, 'contract: Harvest Pumpkins') if newer else home['components'][0]['components'][0]
    assert button['label'] == 'Harvest' and button['style'] == 3 and button['custom_id'].startswith('ne|111|t|')
    press_as_owner(button['custom_id'])
    assert progress() == (1, False)


def test_home_keeps_its_old_button_for_a_contract_without_one(owner):
    set_daily('no_such_task')
    first = checked(ui.cid('111', 'mn', 'home'))['components'][0]['components'][0]
    assert first['label'] == 'Daily contract' and first['custom_id'] == ui.cid('111', 'mv', 'me_daily')


def test_the_twitch_contract_text_still_names_the_command(owner):
    seed()
    with m.SessionLocal() as db:
        d = m.daily(db, m.player(db, 'test', 'twitch', 'u', 'Kamex')[1])
        d.action, d.target, d.progress, d.complete, d.reward_sc = 'mine', 3, 0, False, 9
        db.commit()
    text = client.get('/api/v1/contracts', params=dict(channel='test', uid='u', provider='twitch')).text
    assert 'Daily Contract' in text and '!mine 0/3' in text and 'Reward 9 SC +1 Contribution' in text and 'Task' not in text


# ---------------------------------------------------------------- 6. My bag: useful buttons under the bag

@pytest.mark.parametrize('newer', [False, True])
def test_the_bag_has_its_own_tools_under_it_not_the_whole_area(owner, newer, monkeypatch):
    for key in ('sell', 'use'):
        monkeypatch.setitem(menu.WHEN, key, (lambda c: True, ''))
    for custom_id in (ui.cid('111', 'mv', 'inventory'), ui.cid('111', 'mv', 'by_name'), ui.cid('111', 'mv', 'sellable')):
        found = labels(shown(custom_id, newer=newer))
        start = found.index('Sort & filter…')
        assert found[start:start + 5] == ['Sort & filter…', 'Search bag', 'Sell', 'Use', 'Buy'] and found[-2:] == ['Back', 'Menu'], custom_id
        assert not {'My bag', 'Orders', 'Home & business'} & set(found) and not any(x.startswith('More') for x in found), custom_id


@pytest.mark.parametrize('newer', [False, True])
def test_sell_and_use_hide_when_there_is_nothing_to_sell_or_use(owner, newer, monkeypatch):
    for key in ('sell', 'use'):
        monkeypatch.setitem(menu.WHEN, key, (lambda c: False, 'nothing'))
    found = labels(shown(ui.cid('111', 'mv', 'inventory'), newer=newer))
    assert 'Sell' not in found and 'Use' not in found
    start = found.index('Sort & filter…')
    assert found[start:start + 3] == ['Sort & filter…', 'Search bag', 'Buy']


def test_the_bag_tools_open_working_screens(owner):
    for key in menu.BAG_TOOLS:
        if key == 'search':
            assert press_as_owner(menu._button('111', key)['custom_id'])['type'] == 9          # a pop-up form
        else:
            assert checked(menu._button('111', key)['custom_id']), key


# ---------------------------------------------------------------- 7. Moderator: three groups on one screen

def test_groups_match_the_areas_button_order():
    assert menu.GROUPS['mod'][0][0] == 'EVENTS' and [h for h, _ in menu.GROUPS['mod']] == ['EVENTS', 'POSTS', 'RECORDS']
    for area, groups in menu.GROUPS.items():
        assert [k for _, keys in groups for k in keys] == menu.AREAS[area][3], area


@pytest.mark.parametrize('newer', [False, True])
def test_the_moderator_screen_has_three_headings_and_the_buttons_follow_them(owner, newer):
    data = shown(ui.cid('111', 'mn', 'mod'), newer=newer)
    assert headings(data) == ['Events', 'Posts', 'Records']
    assert [x for x in labels(data) if x in MOD_BUTTONS] == MOD_BUTTONS and labels(data)[-2:] == ['Back', 'Menu']
    if newer:
        assert beside(data, 'Begin a society event')['label'] == 'Start event'          # buttons still sit beside their lines


@pytest.mark.parametrize('newer', [False, True])
def test_only_the_owner_gets_the_moderator_area_and_its_force_merge_line(owner, newer):
    assert 'Moderator' not in labels(press_as('222', ui.cid('222', 'mn', 'home'), newer))
    other = press_as('222', ui.cid('222', 'mn', 'mod'), newer)
    assert 'Force merge' not in labels(other) and 'merge two characters' not in v2.text_of(other).lower()
    assert headings(other) == ['Events', 'Posts', 'Records']               # the headings only group what is there


def test_a_heading_shows_only_when_one_of_its_buttons_does(monkeypatch):
    hidden = set(menu.GROUPS['mod'][1][1])
    monkeypatch.setattr(menu, 'can', lambda ctx, key: key not in hidden)
    lines = menu._listing('mod', menu.children_of('mod', object()))
    assert 'EVENTS' in lines and 'RECORDS' in lines and 'POSTS' not in lines
    assert menu._listing('work', ['gather', 'mine'])[0].startswith('🌿') and 'EVENTS' not in menu._listing('work', ['gather', 'mine'])


# ---------------------------------------------------------------- 8. More: to unlock, closest first

@pytest.mark.parametrize('newer', [False, True])
def test_more_says_how_many_buttons_are_left_to_unlock(owner, newer):
    work = shown(ui.cid('111', 'mn', 'work'), newer=newer)
    more = next(x for x in labels(work) if x.startswith('More'))
    with m.SessionLocal() as db:
        locked = menu.more_split('work', menu.context('111', db, player(db)))[1]
    assert locked and more == f'More · {len(locked)} to unlock' and 'locked' not in more
    assert 'More' in labels(shown(ui.cid('111', 'mn', 'me'), newer=newer))      # nothing locked behind it: just More


def test_the_not_yet_list_puts_what_you_can_fix_right_now_first(monkeypatch):
    lock = {'fulfill', 'analyze', 'sell', 'use'}
    monkeypatch.setattr(menu, 'can', lambda ctx, key: key not in lock)
    also, locked = menu.more_split('trade', object())
    # use and sell have a button that fixes them, analyze an item to get, fulfill neither; each group keeps the area's order
    assert [k for k, _ in locked] == ['use', 'sell', 'analyze', 'fulfill'] and 'clearout' in also


@pytest.mark.parametrize('newer', [False, True])
def test_the_more_screen_lists_locked_buttons_closest_first(owner, newer):
    with m.SessionLocal() as db:
        player(db).cargo = 0
        db.commit()
    text = v2.text_of(shown(ui.cid('111', 'mn', 'work', 'more'), newer=newer))
    order = ['Delivery', 'Mine rare ore', 'Hydroponics', 'Field analysis', 'Spaceport rush', 'Survey', 'Fix a tool']
    found = {x: text.find(f'**{x}**') for x in order if f'**{x}**' in text}
    assert len(found) >= 5 and next(iter(found)) == 'Delivery'             # Delivery: Other jobs fixes it, so it leads
    assert list(found) == sorted(found, key=found.get)


# ---------------------------------------------------------------- 9. What next? starts with Home's Do this next

def step_of():
    with m.SessionLocal() as db:
        return menu.home_next(db, player(db))


@pytest.mark.parametrize('newer', [False, True])
def test_what_next_starts_with_the_do_this_next_line_and_its_button(owner, newer):
    set_daily('harvest')
    no_cooldowns()
    step = step_of()
    data = shown(ui.cid('111', 'mv', 'guide'), newer=newer)
    text = v2.text_of(data)
    line = step['beside'] if newer else 'Do this next'                        # the newer layout drops the label: the button carries it
    assert 'Field Guide' in text and text.index('Field Guide') < text.index(line) < text.index('Next Three Steps')      # under the heading, above the guide
    assert 'Daily:' not in text                                            # the guide's own contract lines would say it twice
    button = beside(data, 'contract: Harvest Pumpkins') if newer else data['components'][0]['components'][0]
    assert button['label'] == 'Harvest' and button['style'] == 3 and button['custom_id'].startswith('ne|111|t|')
    if not newer:
        embed = data['embeds'][0]
        assert 'Field Guide' in embed['title'] and embed['description'].split('\n')[0] == step['line']    # the heading is still the title
        assert [c['label'] for c in data['components'][1]['components']][:2] == ['What next?', 'Guide for…']       # the Help buttons follow
    press_as_owner(button['custom_id'])                                    # it does the contract's task, as on Home
    assert progress() == (1, False)


def test_what_next_shows_the_line_without_a_row_when_the_step_has_no_button(owner, monkeypatch):
    set_daily('harvest')
    monkeypatch.setattr(menu, 'home_button', lambda owner, step: None)
    data = shown(ui.cid('111', 'mv', 'guide'))
    assert data['embeds'][0]['description'].split('\n')[0] == step_of()['line'] and data['components'][0]['components'][0]['label'] == 'What next?'
    assert beside(shown(ui.cid('111', 'mv', 'guide'), newer=True), 'Do this next') is None


def test_what_next_handles_a_panel_too(owner, monkeypatch):
    set_daily('harvest')
    panel = {'embeds': [{'title': 'Guide', 'description': 'body'}], 'components': [ui.row(ui.button('Details', ui.cid('111', 'mn', 'help')))]}
    monkeypatch.setattr(ui, 'slash_panel', lambda command, *args: dict(panel, components=list(panel['components'])) if command == 'guide' else None)
    data = checked(ui.cid('111', 'mv', 'guide'))
    assert data['embeds'][0]['description'] == step_of()['line'] + '\nbody'
    assert [[c['label'] for c in r['components']] for r in data['components']][1:] == [['Details', 'Back', 'Menu']]
    assert data['components'][0]['components'][0]['style'] == 3 and data['_items'][0]['match'] == '**Do this next**'


def test_the_next_line_goes_under_the_heading_or_at_the_top_when_there_is_none():
    line = '➡️ **Do this next** — x'
    assert menu.under_heading('🧭 Kam — New Eridian Field Guide\nbody', line) == f'🧭 Kam — New Eridian Field Guide\n{line}\nbody'
    assert menu.under_heading('🏠 LIFE\nbody', line) == f'🏠 LIFE\n{line}\nbody'
    assert menu.under_heading('LEVEL UP: Fabrication Lv. 1 → Lv. 2\n\n🧭 Guide\nbody', line) == f'LEVEL UP: Fabrication Lv. 1 → Lv. 2\n\n🧭 Guide\n{line}\nbody'   # notices stay first
    assert menu.under_heading('Nothing to guide you on.\nbody', line) == f'{line}\nNothing to guide you on.\nbody'
    assert menu.under_heading('• one\n• two', line) == f'{line}\n• one\n• two'
