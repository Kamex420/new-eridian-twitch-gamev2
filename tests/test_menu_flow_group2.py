"""Menu flow, second group: What next? drops the contract text Do this next already says, Home has Queue, Life and the
contract beside their lines, Work lists Queue status and the Daily contract, the queue screen has What runs next, and
Notifications shows how many are waiting."""
import json
import pytest
from test_colony import m, reset, client
from test_workbench_ui import citizen, press, LUMBER
from test_layout_v2 import assert_valid
import test_menu_polish as polish
import test_menu_redesign as redesign
from app import inbox, menu, qol, ui, layout_v2 as v2
from app.game import cooldowns_materials as cm


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    citizen(lumber=40)
    with m.SessionLocal() as db:
        p = polish.player(db)
        p.sc, p.crops, p.cargo = 5000, 5, 2
        db.commit()


def home(newer=False):
    return polish.shown(ui.cid('111', 'mn', 'home'), newer=newer)


def sections(data):
    return [c for c in polish.walk(data['components']) if c.get('type') == v2.SECTION]


def accessories(data):
    """label -> the button beside a line, in the newer layout."""
    return {s['accessory']['label']: s['accessory'] for s in sections(data)}


def needs_section(data):
    """The section of the needs line (⚡ 100 · 🍲 100 …), or None when no button sits beside it."""
    return next((s for s in sections(data) if '⚡' in s['components'][0]['content']), None)


def back(data):
    """The custom_id of the Back button."""
    return next(b['custom_id'] for b in polish.buttons(data) if b['label'] == 'Back')


def description(data):
    return data['embeds'][0]['description']


def guide():
    return press(ui.cid('111', 'mv', 'guide'))['data']


def lower(**needs):
    redesign.lower_needs(**needs)


# ---------------------------------------------------------------- 1. What next? drops the contract text Do this next already says

RAW = ("🧭 Kam — New Eridian Field Guide\n📋 Daily: Mining 0/3.\nDo /mine next now. Reward: 9 SC +1 Contribution.\n\n🧬 TASK COST FORECAST\n"
       "• Standard work.\n\nNEXT THREE STEPS\n1. Prepare Dried Berries.\n2. Advance the Daily Contract with /mine (0/3).\n3. Support today's Trade Window.")
DAILY_STEP = {'topic': 'daily'}


def test_trim_guide_removes_the_daily_pair_only_when_do_this_next_is_the_contract():
    out = menu.trim_guide(RAW, DAILY_STEP)
    assert '📋 Daily:' not in out and 'Do /mine next' not in out and 'Reward: 9 SC' not in out
    assert out.startswith('🧭 Kam — New Eridian Field Guide\n\n🧬 TASK COST FORECAST')                 # the heading stays the title
    assert '2. Advance the Daily Contract with /mine (0/3).' in out and 'NEXT THREE STEPS' in out      # the list is left alone
    assert menu.trim_guide(RAW, {}) == RAW and menu.trim_guide(RAW, {'topic': 'goal'}) == RAW         # any other step: unchanged


def test_trim_guide_matches_the_text_after_presentation_and_a_cooldown_wording():
    formatted = "📋 **Daily:** Mining 0/3.\nDo `/mine` next when its 40s cooldown ends. Reward: 9 SC +1 Contribution.\n\nMore"
    assert menu.trim_guide(formatted, DAILY_STEP) == '\nMore'
    for text in ('Anything else\n📋 Daily: Mining 0/3.',                                 # no Do line after it
                 "📋 Today's contract is complete.\nNext: /guide goal:society",          # the guide's finished-contract text
                 '📋 Daily: Mining 0/3.\nSomething else', '', 'no contract here'):
        assert menu.trim_guide(text, DAILY_STEP) == text


@pytest.mark.parametrize('newer', [False, True])
def test_what_next_says_the_contract_once_when_it_is_the_do_this_next_pick(owner, newer):
    polish.set_daily('mine')
    assert redesign.next_step()['topic'] == 'daily'
    data = guide()
    said = description(data)
    assert said.split('\n')[0].startswith("➡️ **Do this next** — today's contract: Mining 0/3")      # right under the heading
    assert 'Daily:' not in said and 'Reward:' not in said and '/mine' not in said                     # the guide's own pair is gone
    assert 'Advance the Daily Contract' in json.dumps(data['embeds'], ensure_ascii=False)             # the list below keeps it
    assert v2.text_of(polish.shown(ui.cid('111', 'mv', 'guide'), newer=newer)).count('Mining 0/3') == 1


def test_what_next_keeps_the_guides_contract_lines_when_do_this_next_says_something_else(owner):
    polish.set_daily('mine')
    redesign.make_queue('paused', 'You need Energy to continue.')
    assert redesign.next_step()['label'] == 'Fix my queue' and 'topic' not in redesign.next_step()
    said = description(guide())
    assert 'Daily:' in said and 'Reward: 9 SC' in said and 'Do `/mine` next' in said                # the contract is still told here


def test_a_contract_with_no_button_is_still_the_daily_step(owner):
    polish.set_daily('no_such_task')
    step = redesign.next_step()
    assert step['label'] == 'Daily contract' and step['topic'] == 'daily'


def test_what_next_is_untouched_once_the_contract_is_done(owner):
    polish.set_daily('mine')
    redesign.finish_daily()
    said = description(guide())
    assert said.split('\n')[0].startswith('➡️ **Do this next** — choose a goal')
    assert 'Daily:' not in said and 'Weekly story' in said                                           # the guide moves on to the story


def test_the_embed_branch_of_what_next_is_trimmed_too(owner, monkeypatch):
    polish.set_daily('mine')
    pair = "📋 **Daily:** Mining 0/3.\nDo `/mine` next now. Reward: 9 SC +1 Contribution."
    with m.SessionLocal() as db:
        p = polish.player(db)
        line = menu.home_step(db, p, menu.context('111', db, p))['line']
        for body, expected in ((pair, line), (pair + '\n\nMore text', line + '\nMore text')):
            monkeypatch.setattr(ui, 'slash_panel', lambda *a, _body=body, **k: {'embeds': [{'description': _body}], 'components': []})
            data = menu.show(db, p, '111', 'guide', {}, 'help', 'Kam', 'guide')
            assert data['embeds'][0]['description'] == expected
        monkeypatch.setattr(menu, 'home_step', lambda *a: {'line': 'x', 'beside': 'x', 'label': 'x', 'view': ('qv',)})
        data = menu.show(db, p, '111', 'guide', {}, 'help', 'Kam', 'guide')                            # not the contract: nothing removed
        assert data['embeds'][0]['description'] == 'x\n' + pair + '\n\nMore text'


def test_the_slash_guide_and_the_twitch_text_are_unchanged(owner):
    polish.set_daily('mine')
    text = m._discord_call_internal('guide', '111', 'Kam', {}, '')
    assert '📋 Daily: Mining 0/3.' in text and 'Do /mine next now.' in text
    assert client.get('/api/v1/guide', params=dict(channel='test', uid='u', provider='twitch')).status_code == 200


# ---------------------------------------------------------------- 2. Home: Queue and Life beside their lines

@pytest.mark.parametrize('state, said', [(None, 'No queue yet'), ('running', 'Running'), ('completed', 'Last queue completed'),
                                         ('cancelled', 'Last queue cancelled')])
def test_home_has_a_grey_queue_button_beside_the_queue_line_whatever_the_queue_did(owner, state, said):
    redesign.finish_daily()
    if state:
        redesign.make_queue(state)
    data = home(newer=True)
    queue = next(s for s in sections(data) if said in s['components'][0]['content'])
    assert queue['accessory']['label'] == 'Queue' and queue['accessory']['style'] == 2
    assert queue['accessory']['custom_id'] == ui.cid('111', 'qv') and queue['accessory']['emoji']['name'] == '⏱️'
    assert 'button below' not in v2.text_of(data)                       # that hint made the line small print, where no button can sit
    assert 'Refresh' in polish.labels(polish.shown(queue['accessory']['custom_id']))        # it opens Queue status


def test_a_paused_queue_has_fix_my_queue_and_no_second_button_to_the_same_screen(owner):
    redesign.make_queue('paused', 'You need Energy to continue.')
    data = home(newer=True)
    found = accessories(data)
    assert found['Fix my queue']['custom_id'] == ui.cid('111', 'qv') and 'Queue' not in found
    assert 'Paused' in v2.text_of(data)


def test_the_life_button_shows_only_while_a_need_is_under_50(owner):
    for need in ('energy', 'nutrition', 'social', 'comfort'):
        lower(energy=100, nutrition=100, social=100, comfort=100)
        lower(**{need: 50})
        assert needs_section(home(newer=True)) is None, need
        lower(**{need: 49})
        life = needs_section(home(newer=True))['accessory']
        assert life['label'] == 'Life' and life['style'] == 1, need                                      # blue, like an area button
        assert life['custom_id'].startswith(ui.cid('111', 'mn', 'life'))
        assert polish.checked(life['custom_id'])['embeds'][0]['title'].startswith('❤️'), need            # it opens Life
    lower(energy=100, nutrition=100, social=100, comfort=100, morale=10)
    assert needs_section(home(newer=True)) is None                                                       # Morale is not one of the four


def test_the_life_area_line_keeps_its_own_button_next_to_the_one_by_the_needs(owner):
    lower(energy=10)
    redesign.finish_daily()
    life = [b for label, b in ((s['accessory']['label'], s['accessory']) for s in sections(home(newer=True))) if label == 'Life']
    assert len(life) == 2 and len({b['custom_id'] for b in life}) == 2          # Discord refuses a repeated custom_id
    assert all(b['custom_id'].split('|')[2:5][:2] == ['mn', 'life'] for b in life)


def test_every_home_item_finds_exactly_one_line_and_in_the_order_of_the_lines(owner):
    lower(energy=10)                                                             # Do this next is Recover: Life, Queue and the contract all show
    polish.set_daily('harvest')
    assert redesign.next_step()['label'] == 'Recover'
    data = polish.shown(ui.cid('111', 'mn', 'home'))
    lines = description(data).split('\n')
    matches = [i['match'] for i in data['_items']]
    assert matches[0] == '**Do this next**' and matches[3] == "Today's contract" and matches[4] == '**Work**' and len(matches) == 4 + 6 + 4
    positions = []
    for item in data['_items']:
        found = [i for i, line in enumerate(lines) if item['match'] in line]
        assert len(found) == 1, (item['match'], found)
        positions.append(found[0])
    assert positions == sorted(positions)                                       # the newer layout finds items in the order they are listed


@pytest.mark.parametrize('state', [None, 'running', 'paused', 'completed'])
def test_home_stays_valid_in_both_layouts_with_every_extra_line_and_button(owner, state):
    lower(energy=10, social=30)
    polish.set_daily('harvest')
    if state:
        redesign.make_queue(state, 'You need Energy to continue.')
    found = polish.labels(home())
    assert len(home()['components']) <= 5 and 'Queue' not in found and found.count('Life') == 1      # the old layout: no rows added for them
    newer = home(newer=True)
    assert assert_valid(newer)
    shown = accessories(newer)
    assert {'Recover', 'Queue', 'Harvest', 'Work', 'You'} <= set(shown) and len([s for s in sections(newer) if s['accessory']['label'] == 'Life']) == 2


def test_the_old_layout_home_keeps_its_rows(owner):
    lower(energy=10)
    polish.set_daily('mine')
    rows = [[b['label'] for b in r['components']] for r in home()['components']]
    assert rows[0] == ['Recover'] and rows[1] == ['Work', 'Craft', 'Life', 'Bag & Shop', 'Society'] and rows[2][:1] == ['You']


# ---------------------------------------------------------------- 3. Work: Queue status; the queue screen: What runs next

def test_work_lists_queue_status_and_the_daily_contract_in_this_order():
    assert menu.AREAS['work'][3] == ['gather', 'mine', 'w_rare', 'farm', 'jobs', 'trainskill', 'qstatus', 'me_daily']
    assert 'queue' not in menu.AREAS['work'][3] and 'me_daily' not in menu.AREAS['me'][3]
    assert menu.LEAVES['qstatus']['nav'] == ('qv',)
    assert len(menu.AREAS['work'][3]) + 1 <= 4 * 5                                   # the grid keeps four rows of five, More included
    assert 'daily contract' in menu.AREAS['work'][2] and 'daily contract' in menu.BLURB['work'] and 'train skills' in menu.BLURB['work']


def test_the_queue_area_stays_and_goes_back_to_work():
    assert 'queue' in menu.AREAS and menu.PARENT['queue'] == 'work'
    assert menu.PARENT['qstatus'] == 'work' and menu.PARENT['me_daily'] == 'work'
    assert {menu.PARENT[k] for k in ('repeat', 'cancel', 'plan', 'clearnext', 'qdetails')} == {'queue'}
    assert menu.crumb('queue') == '🏠 Menu › ⛏️ Work › ⏱️ Queue'
    assert menu.nav('111', 'queue')['components'][0]['custom_id'] == ui.cid('111', 'bk', 'mn', 'work')


@pytest.mark.parametrize('newer', [False, True])
def test_work_screen_has_queue_status_and_the_daily_contract(owner, newer):
    data = polish.shown(ui.cid('111', 'mn', 'work'), newer=newer)
    found = polish.labels(data)
    assert 'Queue status' in found and 'Daily contract' in found and 'Queue' not in found
    assert found.index('Train skills') < found.index('Queue status') < found.index('Daily contract')
    if newer:
        assert polish.beside(data, 'totals and why it paused')['custom_id'] == ui.cid('111', 'qv')
        assert polish.beside(data, "Today's contract")['custom_id'] == ui.cid('111', 'mv', 'me_daily')
    assert 'Refresh' in polish.labels(polish.shown(ui.cid('111', 'qv'), newer=newer))               # Queue status opens the queue screen


def test_the_old_queue_area_button_still_opens_and_its_back_goes_to_work(owner):
    data = polish.shown(ui.cid('111', 'mn', 'queue'))
    assert data['embeds'][0]['author']['name'] == '🏠 Menu › ⛏️ Work › ⏱️ Queue'
    assert {'Queue status', 'What runs next', 'Queue rules'} <= set(polish.labels(data))
    assert back(data) == ui.cid('111', 'bk', 'mn', 'work')


def queue_rows():
    with m.SessionLocal() as db:
        return ui.queue_components(db, polish.player(db), '111')


def rows_of(rows):
    return [[b['label'] for b in r['components']] for r in rows]


def test_what_runs_next_is_on_the_second_row_beside_queue_rules_with_or_without_a_queue(owner):
    rows = queue_rows()                                                       # no queue yet
    assert rows_of(rows) == [['Gather', 'Mine', 'Refresh', 'Status'], ['What runs next']]
    redesign.make_queue('running')
    rows = queue_rows()
    assert rows_of(rows) == [['Stop queue', 'Refresh', 'Status'], ['What runs next', 'Queue rules']]
    button = rows[1]['components'][0]
    assert button['custom_id'] == ui.cid('111', 'pv') and button['style'] == 2 and button['emoji']['name'] == '🗺️'
    assert 'Back' in polish.labels(polish.shown(button['custom_id']))        # it opens What runs next


@pytest.mark.parametrize('newer', [False, True])
def test_the_queue_status_screen_shows_what_runs_next(owner, newer):
    assert 'What runs next' in polish.labels(polish.shown(ui.cid('111', 'qv'), newer=newer))
    redesign.make_queue('running')
    assert 'What runs next' in polish.labels(polish.shown(ui.cid('111', 'qv'), newer=newer))


def test_no_queue_button_is_lost_to_the_five_per_row_cap(owner):
    redesign.make_queue('error', 'Something stopped it.')
    lower(energy=0)
    with m.SessionLocal() as db:
        assert qol.set_next(db, polish.player(db), 'gather:' + LUMBER, 2)[0]
        db.commit()
    found = rows_of(queue_rows())
    assert len(found) == 2 and all(len(r) <= 5 for r in found)
    assert sorted(sum(found, [])) == sorted(['Repeat ×5', 'Stop queue', 'Recover now', 'Refresh', 'Clear what runs next', 'Status',
                                              'What runs next', 'Queue rules'])         # six on the first row used to lose Status
    assert found[0][:2] == ['Repeat ×5', 'Stop queue'] and 'Status' in found[1]
    assert 'Status' in polish.labels(polish.shown(ui.cid('111', 'qv')))


def test_every_queue_state_keeps_its_buttons_within_two_rows_of_five(owner):
    for state in (None, 'running', 'paused', 'completed', 'cancelled', 'error'):
        if state:
            redesign.make_queue(state)
        rows = queue_rows()
        assert len(rows) == 2 and all(0 < len(r['components']) <= 5 for r in rows), state
        assert 'What runs next' in sum(rows_of(rows), []), state


# ---------------------------------------------------------------- 4. Daily contract: Work, and Home

def test_the_daily_contract_screen_is_works_screen(owner):
    polish.set_daily('mine')
    data = polish.daily_screen()
    assert data['embeds'][0]['author']['name'] == '🏠 Menu › ⛏️ Work › Daily contract'
    found = polish.labels(data)
    assert {'Gather', 'Mine', 'Train skills', 'Queue status'} <= set(found) and 'Skills' not in found and found[-2:] == ['Back', 'Menu']
    assert data['components'][0]['components'][0]['label'] == 'Mine'                  # the task button stays first
    assert back(data) == ui.cid('111', 'bk', 'mn', 'work')
    assert 'Daily contract' not in polish.labels(polish.shown(ui.cid('111', 'mn', 'me')))
    assert 'Daily contract' in polish.labels(polish.shown(ui.cid('111', 'mn', 'work')))


def contract_line(data):
    return next((x for x in description(data).split('\n') if "Today's contract" in x), None)


def test_home_shows_the_contract_under_the_queue_line_when_do_this_next_is_something_else(owner):
    polish.set_daily('harvest')
    redesign.make_queue('paused', 'You need Energy to continue.')
    lines = description(polish.shown(ui.cid('111', 'mn', 'home'))).split('\n')
    queue = next(i for i, x in enumerate(lines) if 'Paused' in x)
    assert lines[queue + 1].replace('**', '') == "📋 Today's contract: Harvest Pumpkins 0/3 · 9 SC"
    assert lines[0].startswith('➡️ **Do this next** — your queue paused')
    button = accessories(home(newer=True))['Harvest']
    assert button['style'] == 3 and button['custom_id'].startswith('ne|111|t|')           # the button the Daily contract screen has
    assert polish.task_button(polish.daily_screen(), False)['label'] == 'Harvest'
    polish.no_cooldowns()
    polish.press_as_owner(button['custom_id'])
    assert polish.progress() == (1, False)


def test_home_leaves_the_contract_line_off_when_it_is_the_do_this_next_pick_or_done(owner):
    polish.set_daily('mine')
    data = polish.shown(ui.cid('111', 'mn', 'home'))
    assert contract_line(data) is None and description(data).count("today's contract") == 1       # only the Do this next line says it
    redesign.finish_daily()
    assert contract_line(polish.shown(ui.cid('111', 'mn', 'home'))) is None
    assert "Today's contract" not in v2.text_of(home(newer=True))


def test_a_contract_with_no_button_gets_a_grey_daily_contract_button_on_home(owner):
    polish.set_daily('no_such_task')
    redesign.make_queue('paused', 'You need Energy to continue.')
    found = accessories(home(newer=True))
    assert found['Daily contract']['style'] == 2 and found['Daily contract']['custom_id'] == ui.cid('111', 'mv', 'me_daily')
    line = contract_line(home())
    assert line.replace('**', '').startswith("📋 Today's contract: ") and line.endswith(' 0/3 · 9 SC')


def test_a_failing_contract_check_never_takes_home_down(owner, monkeypatch):
    polish.set_daily('mine')
    redesign.make_queue('paused', 'You need Energy to continue.')

    def broken(db, p):
        raise RuntimeError('boom')
    monkeypatch.setattr(cm, 'daily', broken)
    data = polish.shown(ui.cid('111', 'mn', 'home'))
    assert contract_line(data) is None and 'Paused' in description(data) and data['embeds'][0]['title'] == '🏠 New Eridian — Kam'
    assert assert_valid(polish.shown(ui.cid('111', 'mn', 'home'), newer=True))


def test_home_reads_the_contract_once_per_screen(owner, monkeypatch):
    polish.set_daily('harvest')
    redesign.make_queue('paused', 'You need Energy to continue.')
    calls = []
    real = menu.home_contract
    monkeypatch.setattr(menu, 'home_contract', lambda *a: calls.append(1) or real(*a))
    polish.shown(ui.cid('111', 'mn', 'home'))
    assert len(calls) == 1                                                       # the text and the buttons share one read


# ---------------------------------------------------------------- 5. Notifications (N)

def notify(count):
    with m.SessionLocal() as db:
        p = polish.player(db)
        for i in range(count):
            inbox.add(db, p.channel_id, p.twitch_uid, 'info', f'note {i}')
        db.commit()


def notification_label(cached=None):
    with m.SessionLocal() as db:
        ctx = menu.context('111', db, polish.player(db))
        if cached is not None:
            ctx._cache['unread'] = cached                                          # what Ctx.get holds for this screen
        return menu._button('111', 'inbox', ctx=ctx)['label']


@pytest.mark.parametrize('count, label', [(0, 'Notifications'), (3, 'Notifications (3)'), (99, 'Notifications (99)'),
                                          (100, 'Notifications (99+)'), (150, 'Notifications (99+)')])
def test_the_notifications_button_shows_how_many_are_waiting(owner, count, label, monkeypatch):
    if count <= 3:
        notify(count)
    else:                                                                       # the inbox keeps only the newest few dozen: say how many
        monkeypatch.setattr(inbox, 'unread_count', lambda db, channel, uid: count)
    assert notification_label() == label
    assert label in polish.labels(home()) and label in polish.labels(home(newer=True))
    plain = menu._button('111', 'inbox')                                       # no citizen read: no count
    assert plain['label'] == 'Notifications' and plain['custom_id'] == ui.cid('111', 'mv', 'inbox')


def test_read_notifications_stop_counting(owner):
    notify(3)
    assert notification_label() == 'Notifications (3)'
    polish.shown(ui.cid('111', 'mv', 'inbox'))                                  # opening them marks them read
    assert notification_label() == 'Notifications'


def test_a_failed_count_is_none_and_a_non_number_counts_as_none(owner, monkeypatch):
    assert notification_label(cached=True) == 'Notifications'                    # Ctx.get keeps True when a check fails
    assert notification_label(cached='many') == 'Notifications'
    assert notification_label(cached=7) == 'Notifications (7)'

    def broken(db, channel, uid):
        raise RuntimeError('boom')
    monkeypatch.setattr(inbox, 'unread_count', broken)
    assert notification_label() == 'Notifications' and 'Notifications' in polish.labels(home())


def test_the_count_is_read_once_per_screen(owner, monkeypatch):
    notify(2)
    calls = []
    real = inbox.unread_count
    monkeypatch.setattr(inbox, 'unread_count', lambda *a: calls.append(1) or real(*a))
    home()
    assert len(calls) == 1


def test_find_knows_where_the_moved_buttons_are_now():
    from app import ask
    lines = ask._menu_map().split('\n')
    work = next(x for x in lines if x.startswith('Work: '))
    you = next(x for x in lines if x.startswith('You: '))
    assert 'Queue status' in work and 'Daily contract' in work and 'Daily contract' not in you
    queue = next(x for x in lines if x.startswith('Work › Queue status'))
    assert all(label in queue for label in ('Repeat last', 'Stop queue', 'What runs next', 'Clear what runs next', 'Queue rules'))
