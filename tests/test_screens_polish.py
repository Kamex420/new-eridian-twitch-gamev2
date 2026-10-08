"""Discord's button screens: no "type a slash command" lines, empty screens with a title and a way forward,
a shorter All recipes with Ready to craft first, and no paging on one-page lists. Twitch's texts stay as they were."""
import json
import re
import pytest
from test_colony import m, reset, seed
from test_workbench_ui import citizen, W, LUMBER, CAMPFIRE
from test_layout_v2 import assert_valid
from app import ui, qol, layout_v2 as v2, workbench as wb, seed_content as s, task_queue as q
from app.models import QualityGear

ORE = m.item_identity.ALIASES['ore']
# What the cards show for a typed command ("`/make` → Recipe: **Campfire**"), or a bare "/queue action:Start" in plain text.
COMMAND = re.compile(r'`/[a-z]|(?<![\w`/:])/[a-z]{3,}\b')
BOTH = pytest.mark.parametrize('newer', [False, True], ids=['old layout', 'new layout'])


def press(custom_id, values=None, newer=False):
    """Press a control on a message in the old or the newer layout; the answer is in that layout, as Discord gets it."""
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)},
               'message': {'flags': 64 | (v2.FLAG if newer else 0)}}
    return v2.respond(ui.handle_component(payload), payload)['data']


def screen(verb, newer=False, values=None):
    """A menu screen as the citizen sees it: its message data, checked for the layout it was sent in."""
    data = press(ui.cid('111', *verb.split('|')), values, newer)
    assert 'no longer available' not in v2.text_of(data), verb
    if newer:
        assert_valid(data)
    else:
        assert len(data['components']) <= 5 and all(len(r['components']) <= 5 for r in data['components'])
    return data


def words(data):
    return v2.text_of(data).replace('**', '')


def labels(data):
    return [c.get('label', '') for c in v2.controls(data)]


def button(data, label):
    return next(c for c in v2.controls(data) if c.get('label') == label)


def go(data, label, newer):
    """Press the button with this label, returning the screen it opens."""
    return press(button(data, label)['custom_id'], newer=newer)


def commands(data):
    return [line for line in v2.text_of(data).split('\n') if COMMAND.search(line)]


def sections(data):
    found = []

    def walk(components):
        for c in components or []:
            if c.get('type') == v2.SECTION:
                found.append(c)
            walk(c.get('components'))
    walk(data['components'])
    return found


def set_life(**values):
    with m.SessionLocal() as db:
        life = m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        for key, value in values.items():
            setattr(life, key, value)
        db.commit()


def first_recipe(code):
    with m.SessionLocal() as db:
        ctx = wb.Context(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        return next(e for e in wb.index() if ctx.status(e).code == code)


# ---------------------------------------------------------------- 2: no "type a slash command" lines

@BOTH
def test_menu_screens_name_no_command_to_type(newer):
    citizen(lumber=12)
    for verb in ('wh', 'wc|ready|1|', 'wc|favorites|1|', 'wc|parts|1|', 'wc|equipment|1|', 'gv', 'qv', 'qd', 'st', 'lv',
                 'mv|inventory', 'mv|by_value', 'mv|gear', 'mk|gather', 'mk|mine'):
        assert commands(screen(verb, newer)) == [], verb
    for code in ('ready', 'missing', 'station', 'locked'):
        e = first_recipe(code)
        for verb in (f'wr|{e.id}|{e.category}|1|', f'fm|{e.id}|1', f'qp|make:{e.id}|5'):
            assert commands(screen(verb, newer)) == [], (code, verb)
    for task in ('gather:' + LUMBER, 'mine:' + ORE, 'work:harvest'):
        assert commands(screen(f'qp|{task}|5', newer)) == [], task
    assert commands(screen('mp|mine', newer, [ORE])) == []


@BOTH
def test_my_bag_has_no_slash_lines_and_hides_empty_quality_gear(newer):
    citizen(lumber=12)
    data = screen('mv|inventory', newer)
    bag = words(data)
    assert 'Craft tools and equipment under All recipes › Tools & Equipment' in bag
    assert 'Quality Gear' not in bag and 'Suggested next step' not in bag and 'finds and sorts' not in bag
    assert 'Lumber ×12' in bag and {'Sort & filter…', 'Search bag'} <= set(labels(data))
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        db.add(QualityGear(channel_id=W, canonical_uid=p.twitch_uid, item_key='toolkit', item_name='Toolkit', quality='Standard', qty=2, condition=80))
        for i, key in enumerate(sorted(s.ACTIVE)[:20]):
            m.material_change(db, p, key, 1 + i)
        db.commit()
    data = screen('mv|inventory', newer)
    bag = words(data)
    assert 'Quality Gear' in bag and '2 item(s)' in bag and 'Sort & filter › Quality gear' in bag
    assert 'item types. Sort & filter and Search bag list the rest' in bag
    assert commands(data) == []
    # The plain-text route (the slash command's reply) agrees.
    assert COMMAND.search(m.inventory(W, '111', 'Kam', 'discord').body.decode()) is None


@BOTH
def test_filtered_bag_view_points_at_buttons_and_one_page_shows_no_paging(newer):
    citizen(lumber=12)
    data = screen('mv|by_value', newer)
    assert 'Sort & filter and Search bag change this list' in words(data) and 'Page 1/1' not in words(data) and commands(data) == []
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        for key in sorted(s.ACTIVE)[:40]:
            m.material_change(db, p, key, 3)
        db.commit()
    assert 'Page 1/' in words(screen('mv|by_value', newer))


@BOTH
def test_full_status_has_a_button_for_each_thing_it_mentions(newer):
    citizen(lumber=12)
    assert 'Sleep' not in labels(screen('st', newer))      # rested: Sleep's long cooldown is not offered
    set_life(energy=40, comfort=40)                       # Sleep only does something when you are tired
    data = screen('st', newer)
    text = words(data)
    assert 'Sleep: ready now' in text and 'Settings (below) changes these' in text and 'Campfire is ready at Survival Workbench.' in text
    assert {'Sleep', 'Settings', 'Craft Campfire'} <= set(labels(data)) and 'My goal' not in labels(data)
    # Settings opens the menu's Settings area; the next step crafts; Sleep sleeps once and then waits.
    settings = go(data, 'Settings', newer)
    assert 'Queue alerts' in labels(settings) and 'Settings' in words(settings)
    assert 'Campfire' in words(go(data, 'Craft Campfire', newer))
    assert 'Slept' in words(go(data, 'Sleep', newer))
    after = screen('st', newer)
    assert 'Sleep' not in labels(after) and re.search(r'Sleep: ready <t:\d+:R>', words(after))
    with m.SessionLocal() as db:
        assert s.stock(db, m.player(db, W, 'discord', '111', 'Kam')[1]).get(CAMPFIRE.output, 0) == 1


@BOTH
def test_full_status_when_blocked_says_what_is_low_and_offers_recover(newer):
    citizen(lumber=12)
    set_life(energy=5, comfort=8)
    data = screen('st', newer)
    text = words(data)
    assert commands(data) == [] and 'Energy: 5/100; need 20.' in text and 'Recover now (below)' in text
    assert 'Passive recovery reaches 20' in text and 'Recover now' in labels(data)
    # My goal gets a button once there is a goal, and the line points at it.
    press(ui.cid('111', 'gs', CAMPFIRE.id), newer=newer)
    data = screen('st', newer)
    assert 'My goal' in labels(data) and 'My goal (below) lists every step' in words(data) and commands(data) == []


@BOTH
def test_full_status_next_step_is_fetch_missing_when_only_gathering_is_left(newer):
    citizen(lumber=0)
    data = screen('st', newer)
    assert commands(data) == [] and 'Gather ' in words(data) and 'Fetch missing' in labels(data)
    assert not any(x.startswith('Craft ') for x in labels(data))
    assert 'FETCH INGREDIENTS' in words(go(data, 'Fetch missing', newer)).upper()


@BOTH
def test_queue_screens_use_buttons_instead_of_commands(newer):
    citizen(lumber=12)
    set_life(energy=5)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '3', 'discord')        # pauses at once: Energy is too low
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.state == 'paused' and 'Use /' in row.result                             # the stored reason still carries the command
    for verb in ('qv', 'qd', 'st'):
        data = screen(verb, newer)
        assert commands(data) == [], verb
        assert 'Energy: 5/100; need 20.' in words(data), verb
    assert {'Stop queue', 'Recover now'} <= set(labels(screen('qv', newer)))
    set_life(energy=100)
    detail = words(screen('qd', newer))
    assert 'Stop queue cancels the remaining attempts' in detail and 'Recover faster with Relax, Eat or Games in the Life menu' in detail
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        row.state, row.remaining = 'completed', 0
        db.commit()
    data = screen('qd', newer)
    assert 'Repeat this queue with the Repeat button.' in words(data) and commands(data) == []
    assert any(x.startswith('Repeat') for x in labels(screen('qv', newer)))


def test_queue_text_for_other_providers_keeps_its_commands():
    citizen(lumber=12)
    set_life(energy=5)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '3', 'discord')
    set_life(energy=100)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        row = db.query(q.TaskQueue).one()
        chat = q.status(db, p, row, True, provider='twitch')
        assert 'Use /' in q.status(db, p, row, provider='twitch') and '/queue action:Cancel stops' in chat
        assert 'Recover faster with /relax, /eat, /games' in chat
        assert 'Use /' not in q.status(db, p, row) and '/queue action:Cancel' not in q.status(db, p, row, True)
        assert 'or /sleep when it is ready' in q.requirements(db, p, 'gather:' + LUMBER, 3, 'twitch')
        assert '/sleep' not in q.requirements(db, p, 'gather:' + LUMBER, 3)


# ---------------------------------------------------------------- recipe screens

@BOTH
def test_recipe_preview_and_lists_drop_the_command_parentheses(newer):
    citizen(lumber=12)
    preview = words(screen(f'wr|{CAMPFIRE.id}|{CAMPFIRE.category}|1|', newer))
    assert 'Craft one batch now, or queue up to 10 batches with the buttons below.' in preview and 'Action' not in preview
    assert 'Open a recipe to see its full preview before crafting.' in words(screen('wc|ready|1|', newer))
    assert 'Open a recipe to see its full preview before crafting.' in words(screen('wc|equipment|1|', newer))
    assert '(or ' not in words(screen('wc|ready|1|', newer))


@BOTH
def test_recipe_sources_are_plain_words(newer):
    citizen(lumber=0)
    missing = first_recipe('missing')
    text = words(screen(f'wr|{missing.id}|{missing.category}|1|', newer))
    assert '— get it: gather ' in text and 'no ingredients or skill unlock' in text
    locked = first_recipe('station')
    preview = words(screen(f'wr|{locked.id}|{locked.category}|1|', newer))
    assert 'unlock once for' in preview and '(button below)' in preview and '/workshop' not in preview
    fetch = words(screen(f'fm|{missing.id}|1', newer))
    assert 'need ' in fetch and COMMAND.search(fetch) is None


def test_workstation_details_keep_the_command_for_chat_only():
    citizen(lumber=0)
    locked = first_recipe('station')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert '/workshop' not in wb.Context(db, p, 'discord').status(locked).detail
        assert 'with /workshop, or own the matching machine.' in wb.Context(db, p, 'twitch').status(locked).detail
    assert wb.plain_source('/gather resource:Flaxa → 1 per action; no ingredients or skill unlock.') == 'gather Flaxa → 1 per action; no ingredients or skill unlock.'
    assert wb.plain_source('/mine ore:Hematite Ore action:Mine → Needs a Mineral Extractor.') == 'mine Hematite Ore → Needs a Mineral Extractor.'
    assert wb.plain_source(f'/make recipe:{CAMPFIRE.id} → 1+ per batch') == 'craft Campfire → 1+ per batch'
    assert wb.plain_source('Inspect the item in /catalog.') == 'Look it up in the Item list.'


# ---------------------------------------------------------------- 3: empty screens

@BOTH
def test_my_goal_with_no_goal_has_a_title_and_set_goal_buttons(newer):
    citizen(lumber=12)
    data = screen('gv', newer)
    assert 'My Goal' in words(data) and 'No goal yet. Pick a recipe and the goal walks you through every step.' in words(data)
    if not newer:
        assert data['embeds'][0]['title'] == '🎯 My Goal'
    wanted = [button(data, x) for x in labels(data) if x.startswith('Set goal: ')]
    assert 1 <= len(wanted) <= 4 and 'Set goal: Campfire' in labels(data) and all(b['style'] == 3 for b in wanted)
    assert {'Ready to craft', 'All recipes'} <= set(labels(data))
    # Each one sets that goal and shows its walkthrough.
    chosen = go(data, 'Set goal: Campfire', newer)
    assert 'Goal set: Campfire' in words(chosen) and 'MY GOAL' in words(chosen).upper() and 'No goal yet' not in words(chosen)
    assert 'Clear goal' in labels(chosen) and not any(x.startswith('Set goal') for x in labels(chosen))
    cleared = go(chosen, 'Clear goal', newer)
    assert 'Goal cleared.' in words(cleared) and 'No goal yet' in words(cleared) and 'Set goal: Campfire' in labels(cleared)


@BOTH
def test_my_goal_buttons_fall_back_to_what_only_needs_gathering(newer):
    citizen(lumber=0)
    data = screen('gv', newer)
    goals = [x[len('Set goal: '):] for x in labels(data) if x.startswith('Set goal: ')]
    assert goals and len(goals) <= 4
    with m.SessionLocal() as db:
        ctx = wb.Context(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        assert not wb.start_here(ctx) and set(goals) <= {e.name for e in wb.gather_first(ctx, 8)}


@BOTH
def test_queue_status_with_no_queue_has_a_title_and_buttons_that_start_one(newer):
    citizen(lumber=12)
    data = screen('qv', newer)
    assert 'Queue Status' in words(data) and 'Nothing is queued. Pick a material or an ore to gather or mine up to 10 times in a row' in words(data)
    if not newer:
        assert data['embeds'][0]['title'] == '📋 Queue Status'
    assert {'Gather', 'Mine', 'Refresh', 'Status'} <= set(labels(data))
    gather, mine = go(data, 'Gather', newer), go(data, 'Mine', newer)
    assert 'no longer available' not in words(gather) + words(mine)
    assert LUMBER in json.dumps(gather) and ORE in json.dumps(mine)         # the pickers of the menu's Gather and Mine
    # With a queue the screen shows it instead, without the start buttons.
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '3', 'discord')
    running = screen('qv', newer)
    assert 'Queue' in words(running) and 'Nothing is queued' not in words(running)
    assert 'Gather' not in labels(running) and 'Mine' not in labels(running) and 'Stop queue' in labels(running)


# ---------------------------------------------------------------- 4: All recipes

@BOTH
def test_all_recipes_leads_with_ready_to_craft_and_is_shorter(newer):
    citizen(lumber=12)
    data = screen('wh', newer)
    text = words(data)
    lines = [x for x in text.split('\n') if x.strip()]
    ready = next(i for i, x in enumerate(lines) if x.startswith('✅ Ready to craft'))
    fav = next(i for i, x in enumerate(lines) if x.startswith('⭐ Favourites'))
    assert ready < fav < next(i for i, x in enumerate(lines) if 'Materials & Ores' in x)
    assert '4 recipes you can craft right now' in lines[ready] and 'Personal Tier 1' in ''.join(lines[:ready])
    assert re.search(r'Workstations unlocked: 1 of \d+ \(Survival Workbench is free\)\.', text) and '/workshop' not in text
    assert 'START HERE' not in text.upper() and 'Open a category' not in text and 'Every list runs from' not in text
    assert all(label in text for _, _, label, _ in wb.CATEGORIES)               # every category line stays (with its Browse button)
    assert commands(data) == [] and len(text) < 1800
    if newer:
        # Discord allows 40 components in a message, so the first ten lines get their Browse button beside them (as before),
        # Ready to craft and Favourites first, and the dropdown stays for the rest.
        beside = [(c['components'][0]['content'], c['accessory']['label']) for c in sections(data)]
        assert len(beside) >= 10 and all(label == 'Browse' for _, label in beside)
        assert 'Ready to craft' in beside[0][0] and 'Favourites' in beside[1][0] and 'Materials & Ores' in beside[2][0]


@BOTH
def test_all_recipes_shows_start_here_only_when_nothing_is_ready(newer):
    citizen(lumber=0)
    with m.SessionLocal() as db:
        assert wb.category_counts(wb.Context(db, m.player(db, W, 'discord', '111', 'Kam')[1]))['ready'][0] == 0
    data = screen('wh', newer)
    text = words(data)
    assert 'START HERE' in text.upper() and 'first, then craft it.' in text and 'Seed Industries sells starter supplies.' in text
    assert commands(data) == [] and '/gather' not in text and '/workshop' not in text
    assert '0 recipes you can craft right now' in text


def test_all_recipes_for_chat_is_unchanged():
    seed('u', 'twitch', 'Kamex')
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        m.material_change(db, p, LUMBER, 12)
        db.commit()
        text = wb.home_text(wb.Context(db, p, 'twitch'))
    assert text == ('🛠️ Workbench T1 (0 batches), ready/total: ready 4 · materials 0/60 · parts 0/88 · food 0/59 · medicine 0/43 · '
                    'seeds 0/14 · equipment 0/36 · machines 2/38 · building 0/30 · beds 0/20 · seating 0/50 · bathroom 1/26 · '
                    'clothing 0/72 · storage 1/58 · tables 0/40 · decor 0/122 | !make <category> [page] lists easiest first; !make <recipe> crafts one batch.')


# ---------------------------------------------------------------- 5: one-page lists show no paging

@BOTH
def test_a_one_page_list_has_no_paging_buttons(newer):
    citizen(lumber=12)
    data = screen('wc|ready|1|', newer)
    names = labels(data)
    assert 'All recipes' in names and not any(x in names for x in ('Previous', 'Next')) and not any(x.startswith('Page ') for x in names)
    assert 'Page 1/1' not in words(data) and 'Ready to Craft' in words(data)
    if not newer:
        assert 'page 1/1' not in json.dumps(data['components'])                    # nor in the recipe dropdown's placeholder
        assert data['embeds'][0]['title'] == '✅ Ready to Craft'
    empty = screen('wc|favorites|1|', newer)
    assert 'All recipes' in labels(empty) and 'Next' not in labels(empty) and 'Page 1/1' not in words(empty)


@BOTH
def test_a_list_with_several_pages_still_pages(newer):
    citizen(lumber=12)
    pages = wb.page_bounds(len(wb.in_category('parts')), 1)[1]
    assert pages > 1
    first = screen('wc|parts|1|', newer)
    assert f'Page 1/{pages}' in labels(first) and f'Page 1/{pages}' in words(first)
    assert button(first, 'Previous').get('disabled') and not button(first, 'Next').get('disabled') and 'All recipes' in labels(first)
    second = go(first, 'Next', newer)
    assert f'Page 2/{pages}' in labels(second) and not button(second, 'Previous').get('disabled')
    last = screen(f'wc|parts|{pages}|', newer)
    assert button(last, 'Next').get('disabled') and not button(last, 'Previous').get('disabled')
    # A workstation filter that leaves one page drops the paging again.
    with m.SessionLocal() as db:
        ctx = wb.Context(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        station = next(t for t in wb.cp.STATIONS if 0 < len(wb.in_view(ctx, 'parts', t)) <= wb.PAGE_SIZE)
    one = screen(f'wc|parts|1|{wb.station_code(station)}', newer)
    assert 'Next' not in labels(one) and not any(x.startswith('Page ') for x in labels(one)) and 'All recipes' in labels(one)


# ---------------------------------------------------------------- Twitch is untouched

def test_chat_texts_of_the_changed_screens_are_unchanged():
    seed('u', 'twitch', 'Kamex')
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        m.material_change(db, p, LUMBER, 12)
        db.commit()
        ctx = wb.Context(db, p, 'twitch')
        assert wb.category_text(ctx, 'ready', 1, '') == ('✅ Ready to craft 1/1: ✅Campfire T1 · ✅Crude Wood Toilet T1 · ✅Storage Platform T1 · '
                                                          '✅Survival Workbench T1 | ✅ready ❌missing 🔑unlock 🔒locked | !make <recipe name> crafts; last page.')
        assert wb.category_text(ctx, 'favorites', 1, '') == '⭐ Favourites: No favourites yet. !fav <recipe name> stars one.'
        assert ctx.status(next(e for e in wb.index() if e.name == 'Stone Block')).detail == \
            'Unlock Masonry Bench once for 15 SC with /workshop, or own the matching machine.'

    def say(function, *args, **kwargs):
        return function('test', 'u', 'Kamex', *args, **kwargs).body.decode()
    assert say(m.inventory, 'twitch') == ('🎒 Kamex | 10000 SC | Argentite Ore 100, Cargo 100, Hematite Ore 100, Iron Nails 100, Pumpkin 100 '
                                          '| 6 item types | !inv <search|value|ready> for more')
    assert say(m.inventory, 'twitch', search='lum') == '🎒 Kamex 1/1 ("lum"): Lumber 12 | worth 24 SC'
    assert say(m.status_view, 'twitch') == ('📊 Kamex | E100 N100 S100 C100 | Queue: No queue yet. !mine, !gather or !make can queue up to 10 attempts. '
                                            '| Sleep ready now | Ready: Campfire, Crude Wood Toilet, Storage Platform')
    assert say(m.target, '', 'twitch') == '🎯 No goal yet. !target <recipe name> sets one. The goal then walks you through every step, with a button for each.'
    assert say(m.queued_tasks, 'view', '', '1', 'twitch') == \
        'You have no task queue. Start one from /mine, /gather or /make with Queue 5 or Queue 10, or /queue action:Start.'
    assert say(m.gear, 'twitch') == '🛠️ No quality gear yet. Use /make to browse and craft equipment.'
    assert say(m.target, 'Campfire', 'twitch').startswith('🎯 Goal set: **Campfire**. /status and My goal track everything still needed. 🎯 Goal Campfire 0/1 step')
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        assert qol.queue_summary(db, p, 'twitch')[0] == 'No queue yet. !mine, !gather or !make can queue up to 10 attempts.'
        assert qol.next_step(db, p, 'twitch').startswith('✅ ') and '!make ' in qol.next_step(db, p, 'twitch')


def test_discord_gets_plain_words_for_the_same_lines():
    seed('d', 'discord', 'Kam')
    assert m.gear('test', 'd', 'Kam', 'discord').body.decode() == '🛠️ No quality gear yet. Craft equipment from All recipes.'
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'discord', 'd', 'Kam')[1]
        ctx = wb.Context(db, p, 'discord')
        assert qol.queue_summary(db, p, 'discord')[0] == 'No queue yet. Gather, Mine or a recipe can queue up to 10 attempts.'
        assert '/make recipe:' in qol.next_step(db, p, 'discord', ctx)          # receipts keep their hint; Full status uses next_step_plain
        assert '/' not in qol.next_step_plain(qol.next_pick(db, p, ctx), ctx)
    reason = ('Energy: 12/100; need 20. Use /relax or /sleep (ready now). Passive recovery reaches 20 <t:1:R>.\n'
              'Nutrition: 5/100; need 20. Use /eat (a free emergency meal if you own no food).')
    assert qol.without_fix(reason) == 'Energy: 12/100; need 20. Passive recovery reaches 20 <t:1:R>.\nNutrition: 5/100; need 20.'
