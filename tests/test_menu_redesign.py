"""The menu redesign (docs/menu-redesign.md): Do this next, More screens with Also here and Not yet, one-button
switches, one Sell flow, Looks under You, and older buttons that keep working."""
import json
from collections import Counter
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, press, controls, find, W, LUMBER
from app import ask, menu, ui, seed_content as s, task_queue as q
from app.game.cooldowns_materials import daily


def labels(data):
    return [c.get('label') for c in controls(data)]


def text_of(data):
    return json.dumps(data, ensure_ascii=False)


def area(key, *rest):
    return press(ui.cid('111', 'mn', key, *rest))['data']


def have(key):
    with m.SessionLocal() as db:
        return m.material_amount(db, m.player(db, W, 'discord', '111', 'Kam')[1], key)


def next_step():
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        step = menu.home_next(db, p)
        db.commit()
        return step


def finish_daily():
    with m.SessionLocal() as db:
        daily(db, m.player(db, W, 'discord', '111', 'Kam')[1]).complete = True
        db.commit()


def make_queue(state, result=''):
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '5', 'discord')
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        row.state, row.result = state, result
        db.commit()


def lower_needs(**values):
    with m.SessionLocal() as db:
        life = m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        for k, v in values.items():
            setattr(life, k, v)
        db.commit()


# ---------------------------------------------------------------- Home and Do this next

def test_home_leads_with_a_green_do_this_next_button_and_has_no_status():
    citizen()
    home = area('home')
    first_row = home['components'][0]['components']
    assert len(first_row) == 1 and first_row[0]['style'] == 3                    # the first button, green
    assert 'Do this next' in text_of(home)
    assert {'Work', 'Craft', 'Life', 'Bag & Shop', 'Town', 'You', 'Help', 'Notifications', 'Do again'} <= set(labels(home))
    assert 'Status' not in labels(home)                                           # Full status is in You > More
    assert 'Full status' in labels(area('me', 'more'))


def test_do_this_next_takes_the_first_step_that_applies():
    citizen()
    assert next_step()['label'] == 'Daily contract' and next_step()['view'] == ('mv', 'me_daily')
    finish_daily()
    assert next_step()['label'] == 'Find a goal'
    make_queue('completed')
    step = next_step()
    assert step['label'] == 'Repeat last queue' and step['do'] == {'do': 'cmd', 'leaf': 'repeat'}
    make_queue('paused', 'You need Energy to continue.')
    step = next_step()
    assert step['label'] == 'Fix my queue' and step['view'] == ('qv',) and 'You need Energy' in step['line']
    lower_needs(energy=0)
    step = next_step()
    assert step['label'] == 'Recover' and step['do'] == {'do': 'recover'}         # a blocked need comes before a paused queue


def test_do_this_next_lines_name_the_button_in_the_card_and_not_beside_it():
    citizen()
    step = next_step()
    assert step['line'].startswith('➡️ **Do this next** — ') and step['beside'].startswith('➡️ ') and '**' not in step['beside']


def test_repeat_last_queue_from_home_runs_the_repeat():
    citizen()
    finish_daily()
    make_queue('completed')
    home = area('home')
    repeat = find(home, 'Repeat last queue')
    assert repeat['style'] == 3 and repeat['custom_id'].startswith('ne|111|t|')


# ---------------------------------------------------------------- More: Also here and Not yet

def test_work_more_lists_extras_and_locked_jobs_with_a_way_to_get_each():
    citizen()
    more_label = next(label for label in labels(area('work')) if label.startswith('More'))
    assert more_label.startswith('More · ') and more_label.endswith(' locked')
    more = area('work', 'more')
    body = text_of(more)
    assert more['embeds'][0]['author']['name'] == '🏠 Menu › ⛏️ Work › More'
    assert 'also here' in body.lower() and 'Fix the town' in body and 'not yet' in body.lower()     # headings show as Also Here / Not Yet
    assert 'Hydroponics' in body and 'needs a Small Water Filter' in body
    how = find(more, 'Hydroponics')
    assert how['custom_id'].endswith('|fd|where do I get a Small Water Filter')
    assert 'Small Water Filter' in text_of(press(how['custom_id'])['data'])        # Find, with the question already asked
    assert labels(more)[-2:] == ['Back', 'Menu']


def test_a_locked_button_moves_to_its_own_place_once_the_citizen_can_use_it():
    citizen()
    assert 'Hydroponics' not in text_of(press(ui.cid('111', 'mk', 'farm'))['data'])
    with m.SessionLocal() as db:
        m.material_change(db, m.player(db, W, 'discord', '111', 'Kam')[1], s.key('Small Water Filter'), 1)
        db.commit()
    assert 'Hydroponics' in text_of(press(ui.cid('111', 'mk', 'farm'))['data'])
    assert 'Hydroponics' not in text_of(area('work', 'more'))


def test_switches_and_situational_buttons_hide_and_are_never_listed_as_locked():
    citizen()
    assert not any(label.startswith('More') for label in labels(area('queue')))          # nothing locked, nothing extra
    assert not {'Stop queue', 'Repeat last', 'Clear what runs next'} & set(labels(area('queue')))
    town = area('community')
    assert 'Event' not in labels(town) and 'Stream challenge' not in labels(town)         # only while one runs
    assert 'not yet' not in text_of(area('community', 'more')).lower()
    assert 'Recover' not in labels(area('life')) and 'Recover' not in text_of(area('life', 'more'))


def test_home_and_business_lists_the_business_buttons_as_locked_until_you_start_one():
    citizen()
    assert {'Your home', 'Upgrade home', 'Your business', 'Start a business'} <= set(labels(area('property')))
    more = area('property', 'more')
    body = text_of(more)
    assert 'also here' not in body.lower() and 'not yet' in body.lower() and 'start a business first' in body
    assert labels(more).count('Start a business') == 1                                    # one fix for the three locked buttons
    assert 'More · 3 locked' in labels(area('property'))


def test_every_area_with_something_behind_it_has_a_more_button_and_a_back_button():
    citizen()
    for key in ('craft', 'life', 'trade', 'community', 'me', 'settings'):
        assert any(label.startswith('More') for label in labels(area(key))), key
        more = area(key, 'more')
        assert more['embeds'][0]['author']['name'].endswith('› More'), key
        assert labels(more)[-2:] == ['Back', 'Menu'], key


@pytest.mark.parametrize('key,expected', [('trade', 'Always keep'), ('me', 'Full status'), ('craft', 'Item list'), ('life', 'Cooldowns'),
                                          ('community', 'Weather & time')])
def test_more_screens_hold_the_less_used_buttons(key, expected):
    citizen()
    assert expected in labels(area(key, 'more'))
    assert expected not in labels(area(key))


def test_every_how_to_get_it_question_is_understood_by_find():
    citizen()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        for key, (what, question) in menu.HOW.items():
            result = ask.answer(db, p, question)
            assert result.intent != 'unknown' and result.answered, (key, question)


# ---------------------------------------------------------------- one button for on and off

@pytest.mark.parametrize('name', ['Auto-recover', 'Activity feed', 'Results'])
def test_a_switch_is_one_button_that_shows_its_state_and_flips_it(name):
    citizen()

    def state():
        return next(label for label in labels(area('settings')) if label.startswith(name + ': '))
    before = state()
    assert before.split(': ')[1] in {'On', 'Off', 'Shown', 'Hidden', 'Short', 'Full'}
    press(find(area('settings'), name + ': ')['custom_id'])
    assert state() != before
    press(find(area('settings'), name + ': ')['custom_id'])
    assert state() == before


def test_older_on_and_off_tickets_still_work():
    citizen()
    result = press(ui.cid('111', 't', ui.issue('111', {'do': 'cmd', 'leaf': 'auto_off'})))['data']
    assert 'Auto-recover: Off' in labels(result)
    result = press(ui.cid('111', 't', ui.issue('111', {'do': 'cmd', 'leaf': 'auto_on'})))['data']
    assert 'Auto-recover: On' in labels(result)


def test_a_switch_without_a_screen_session_opens_the_screen_it_lives_on():
    for key, screen in (('auto', 'settings'), ('feed', 'settings'), ('results', 'settings'), ('sl_auto', 'seedling')):
        button = menu._button('111', key)                 # a Find answer has no session to read the state in
        assert button['label'] == menu.LEAVES[key]['label'] and button['custom_id'] == ui.cid('111', 'mn', screen), key


def test_do_this_next_falls_back_to_choosing_a_goal_when_a_check_fails():
    step = menu.home_next(None, None)
    assert step['label'] == 'Find a goal' and step['view'] == ('wc', 'ready', 1, '') and 'choose a goal' in step['line']


# ---------------------------------------------------------------- older buttons

@pytest.mark.parametrize('old,expected', [('farming', 'FARM'), ('science', 'OTHER JOBS'), ('logistics', 'OTHER JOBS'), ('frontier', 'OTHER JOBS'),
                                          ('stations', 'CRAFT · MORE'), ('social', 'FRIENDS'), ('bag', 'INVENTORY'), ('account', 'SETTINGS')])
def test_removed_areas_open_what_replaced_them_instead_of_home(old, expected):
    citizen()
    body = text_of(area(old)).upper()
    assert expected in body and 'NEW ERIDIAN — ' not in body


def test_merged_buttons_open_their_replacement():
    citizen()
    assert 'YOU · MORE' in text_of(press(ui.cid('111', 'mk', 'me_more'))['data']).upper()
    assert 'TRAIN SKILLS' in text_of(press(ui.cid('111', 'mk', 'training'))['data']).upper()
    assert 'SELL' in text_of(press(ui.cid('111', 'mk', 'sellsome'))['data']).upper()


def test_the_public_panel_uses_the_new_names_and_settings_replaces_account():
    panel = ui.public_panel()
    names = labels(panel)
    assert {'Menu', 'Status', 'Work', 'Craft', 'Life', 'Bag & Shop', 'Town', 'You', 'Ask or search', 'Settings'} <= set(names)
    assert 'Bag & Trade' not in text_of(panel) and 'Colony' not in text_of(panel) and 'Account' not in text_of(panel)
    assert find(panel, 'Settings')['custom_id'] == ui.cid('*', 'mn', 'settings')


# ---------------------------------------------------------------- Bag & Shop

def test_my_bag_keeps_sort_and_filter_and_search_under_it():
    citizen()
    bag = press(ui.cid('111', 'mv', 'inventory'))['data']
    assert {'Sort & filter…', 'Search bag'} <= set(labels(bag))


def test_sell_is_one_flow_pick_an_item_then_how_many_and_sell_all_can_be_undone():
    citizen(lumber=12)
    amounts = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    got = labels(amounts)
    assert {'Sell 1', 'Sell 5', 'Sell 10', 'Sell all 12', 'Other amount…', 'Sell it after my queue'} <= set(got) and 'Sell 25' not in got
    result = press(find(amounts, 'Sell all 12')['custom_id'])['data']
    assert have(LUMBER) == 0 and 'Undo sale (60s)' in labels(result)
    press(find(result, 'Undo sale')['custom_id'])
    assert have(LUMBER) == 12


def test_sell_an_exact_amount():
    citizen(lumber=12)
    amounts = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    press(find(amounts, 'Sell 5')['custom_id'])
    assert have(LUMBER) == 7


# ---------------------------------------------------------------- Looks

def test_looks_sits_under_you_with_pickers_grouped_by_what_they_change():
    citizen()
    assert {'Looks', 'Settings', 'Job & role', 'My Seedling'} <= set(labels(area('me')))
    assert {'Body…', 'Clothes…', 'Voice…', 'My look'} <= set(labels(area('looks')))
    body = press(ui.cid('111', 'mk', 'lk_body'))['data']
    select = body['components'][0]['components'][0]
    assert [o['value'] for o in select['options']] == ['lk_skin', 'lk_hair', 'lk_hair_colour']
    skin = press(select['custom_id'], values=['lk_skin'])['data']                          # opens the skin tone picker
    picker = skin['components'][0]['components'][0]
    assert picker['custom_id'] == ui.cid('111', 'mp', 'lk_skin') and len(picker['options']) > 3
    hats = text_of(area('looks', 'more'))
    assert 'not yet' in hats.lower() and 'Wear a hat' in hats and 'Pin a badge' in hats


# ---------------------------------------------------------------- the shape of the whole menu

def test_nothing_is_more_than_two_taps_below_home():
    depth, frontier = {'home': 0}, ['home']
    while frontier:
        following = []
        for key in frontier:
            for child in menu.AREAS[key][3]:
                if child in menu.AREAS and child not in depth:
                    depth[child] = depth[key] + 1
                    following.append(child)
        frontier = following
    assert set(depth) == set(menu.AREAS) and max(depth.values()) == 2 and len(menu.AREAS) == 16


def test_no_two_buttons_share_a_name():
    names = Counter()
    seen = {}
    for key, (_, title, _, children) in menu.AREAS.items():
        names[title] += 1
        seen.setdefault(title, set()).add('area:' + key)
        for child in list(children) + menu.MORE.get(key, []):
            if child not in menu.AREAS:
                label = menu.LEAVES[child]['label'].rstrip('…')
                seen.setdefault(label, set()).add(child)
    assert {label: keys for label, keys in seen.items() if len(keys) > 1} == {}


def test_removed_areas_and_merged_leaves_are_all_aliased_and_every_old_leaf_is_kept():
    removed = {'farming', 'science', 'logistics', 'frontier', 'stations', 'social', 'bag', 'account'}
    assert removed == set(menu.AREA_ALIAS) and not removed & set(menu.AREAS)
    for key in ('sellsome', 'c_vote_pick', 'me_more', 'auto_on', 'auto_off', 'feed_on', 'feed_off', 'display_compact', 'display_detailed',
                'sl_on', 'sl_off', 'sl_custom', 'quiet_off', 'w_farm_tend', 'w_scan', 'w_survey', 'bstart', 'undo'):
        assert key in menu.LEAVES, key
