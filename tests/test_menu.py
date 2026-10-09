"""The /menu button tree: every area opens, every button fits Discord, actions run once."""
import json
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, press, controls, find, W, LUMBER
from app import menu, ui, seed_content as s


def open_area(area):
    return press(ui.cid('111', 'mn', area))['data']


@pytest.mark.parametrize('area', list(menu.AREAS))
def test_every_area_opens_within_discord_limits(area):
    citizen()
    data = open_area(area)
    assert data['embeds'][0].get('title')
    rows = data['components']
    assert 1 <= len(rows) <= 5
    for component in controls(data):
        assert len(component['custom_id']) <= 100 and len(component.get('label', '')) <= 80
    assert sum(len(r['components']) for r in rows) <= 25


def test_every_leaf_points_at_a_real_command():
    for key, item in menu.LEAVES.items():
        assert key in menu.PARENT, key
        if item['kind'] == 'nav':
            continue
        command, options = m.discord_legacy_route(item['cmd'], item['opts'])
        assert command in m.DISCORD_OPTION_SCHEMA or command in {'recover', 'menu', 'inbox', 'eatfull', 'undo', 'catalog', 'queuedetails', 'guidepanels', 'menupanel', 'seedlingstep', 'asklog', 'trick'} | m.community.MOD, key
        names = {o['name'] for o in m.DISCORD_OPTION_SCHEMA.get(command, [])}
        assert set(options) <= names, key


@pytest.mark.parametrize('key', [k for k, v in menu.LEAVES.items() if v['kind'] == 'view'])
def test_every_view_button_shows_a_card(key):
    citizen()
    data = press(ui.cid('111', 'mv', key))['data']
    assert data['embeds'] and len(data['components']) <= 5


def lower_needs(**values):
    with m.SessionLocal() as db:
        life = m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1])
        for k, v in values.items():
            setattr(life, k, v)
        db.commit()


def test_action_buttons_work_once_and_offer_the_area_again():
    citizen(); lower_needs(energy=50, comfort=50)
    relax = find(open_area('life'), 'Relax')['custom_id']
    first = press(relax)['data']
    assert 'Relaxed' in json.dumps(first, ensure_ascii=False)
    assert 'Relax' in [c.get('label') for c in controls(first)]      # the area's buttons come back
    assert 'already used' in press(relax)['data']['content']


def test_choice_lists_run_or_confirm():
    citizen(lumber=10)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.material_change(db, p, s.key('Pumpkin'), 2); db.commit()
    lower_needs(nutrition=40)
    eat = press(ui.cid('111', 'mk', 'eat'))['data']
    select = eat['components'][0]['components'][0]
    result = press(select['custom_id'], values=[s.key('Pumpkin')])['data']
    assert 'Meal' in json.dumps(result, ensure_ascii=False)
    sell = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    assert 'How many?' in json.dumps(sell, ensure_ascii=False)          # Sell is one flow: pick an item, then how many
    with m.SessionLocal() as db:
        assert s.stock(db, m.player(db, W, 'discord', '111', 'Kam')[1]).get(LUMBER) == 10
    press(find(sell, 'Sell 10')['custom_id'])
    with m.SessionLocal() as db:
        assert s.stock(db, m.player(db, W, 'discord', '111', 'Kam')[1]).get(LUMBER, 0) == 0


def test_social_pick_offers_activities_with_that_citizen():
    citizen('111'); citizen('222')
    friend = press(ui.cid('111', 'mk', 'friend'))['data']
    value = friend['components'][0]['components'][0]['options'][0]['value']
    data = press(ui.cid('111', 'mp', 'friend'), values=[value])['data']
    labels = [c.get('label') for c in controls(data)]
    assert {'Say hi', 'Hang out', 'Mentor'} <= set(labels)


def test_menu_slash_command_and_reply_buttons():
    citizen()
    text = m._discord_call_internal('menu', '111', 'Kam', {}, 'i')
    panel = ui.slash_panel('menu', '111', 'Kam', {}, text)
    assert {'Life', 'Work', 'Craft', 'Bag & Shop', 'Society', 'You', 'Help'} <= {c.get('label') for c in controls(panel)}
    row = menu.after_command('relax', {}, '111')
    assert [c['label'] for c in row['components']] == ['Again', 'Life', 'Menu']
    assert [c['label'] for c in menu.after_command('inventory', {}, '111')['components']] == ['Bag & Shop', 'Menu']


def test_todays_vote_shows_the_ballot_with_a_vote_button_for_each_option(monkeypatch):
    monkeypatch.setattr(m.community, 'ENABLED', True)
    citizen()
    ballot = press(find(open_area('community'), "Today's vote")['custom_id'])['data']
    votes = [c for c in controls(ballot) if c['label'].startswith('Vote ')]
    assert len(votes) == 3 and all(c['custom_id'].startswith('ne|111|mp|c_vote_pick|=') for c in votes)
    result = json.dumps(press(find(ballot, 'Vote 2')['custom_id'])['data'], ensure_ascii=False)
    assert 'Vote counted' in result and 'whole number' not in result
    with m.SessionLocal() as db:
        assert db.query(m.votes.Cast).one().choice == 2


def test_the_old_cast_your_vote_button_opens_the_ballot(monkeypatch):
    monkeypatch.setattr(m.community, 'ENABLED', True)
    citizen()
    ballot = press(ui.cid('111', 'mk', 'c_vote_pick'))['data']
    assert len([c for c in controls(ballot) if c['label'].startswith('Vote ')]) == 3


def test_every_availability_rule_runs_without_failing(monkeypatch):
    """Ctx.get shows a button when its check fails, so a broken check (a bad import, a renamed function) would hide
    nothing and say nothing. Run every rule with failures raised instead."""
    citizen()
    monkeypatch.setattr(menu.Ctx, 'get', lambda self, name, make: self._cache.setdefault(name, make()))
    answers = menu.with_context('111', lambda c: {key: bool(rule(c)) for key, (rule, _) in menu.WHEN.items()})
    assert set(answers) == set(menu.WHEN)


# ---------------------------------------------------------------- results: Again, the sale row, Friends

def last_row(data):
    return [c['label'] for c in data['components'][-1]['components']]


def again_action(data):
    """The action behind a result's Again button (reading it uses its ticket up), or None when there is no Again."""
    found = [c for c in controls(data) if c.get('label') == 'Again']
    assert len(found) <= 1
    return ui.claim('111', found[0]['custom_id'].split('|')[3])[0] if found else None


def do(**action):
    return menu.run('111', 'Kam', dict(action, do='cmd'))


def test_a_repeatable_result_leads_its_nav_row_with_a_green_again_for_the_same_action():
    citizen(); lower_needs(energy=50, comfort=50)
    first = press(find(open_area('life'), 'Relax')['custom_id'])['data']
    again = first['components'][-1]['components'][0]
    assert last_row(first) == ['Again', 'Back', 'Menu'] and again['style'] == 3 and again['emoji'] == {'name': '🔁'}   # no extra row
    second = press(again['custom_id'])['data']                       # Again runs the action once, and its result has a fresh Again
    assert last_row(second)[0] == 'Again' and second['components'][-1]['components'][0]['custom_id'] != again['custom_id']
    assert again_action(second) == {'do': 'cmd', 'leaf': 'relax'}      # only the keys the action had: no value, no amount
    assert 'already used' in press(again['custom_id'])['data']['content']


def test_again_repeats_a_leaf_action_with_its_value_and_a_raw_one_with_its_command():
    citizen()
    with m.SessionLocal() as db:
        m.material_change(db, m.player(db, W, 'discord', '111', 'Kam')[1], s.key('Pumpkin'), 3); db.commit()
    lower_needs(nutrition=40)
    hobby = m.DISCORD_OPTION_SCHEMA['hobby'][0]['choices'][0]['value']
    for action in ({'leaf': 'eat', 'value': s.key('Pumpkin')}, {'leaf': 'hobby', 'value': hobby}, {'raw': ['relax', {}]},
                   {'raw': ['eat', {'food': s.key('Pumpkin')}]}, {'raw': ['hobby', {'hobby': hobby}]}):
        assert again_action(do(**action)) == dict(action, do='cmd'), action


def test_again_repeats_a_leaf_amount_only_when_the_action_had_one(monkeypatch):
    monkeypatch.setattr(menu, 'REPEATABLE', menu.REPEATABLE | {'seedindustries'})      # no repeatable leaf has an amount today
    citizen(lumber=10)
    assert again_action(do(leaf='sell', value=LUMBER, amount=3)) == {'do': 'cmd', 'leaf': 'sell', 'value': LUMBER, 'amount': 3}
    assert again_action(do(leaf='sell', value=LUMBER)) == {'do': 'cmd', 'leaf': 'sell', 'value': LUMBER}


def test_again_is_not_offered_for_a_sale_or_for_eat_without_a_food_or_use_without_an_item():
    citizen(lumber=10)
    assert again_action(do(leaf='sell', value=LUMBER, amount=5)) is None
    for raw in (['eat', {}], ['use', {}]):
        assert again_action(do(raw=raw)) is None, raw
    assert not menu.repeatable('eat', {}) and not menu.repeatable('use', {}) and menu.repeatable('eat', {'food': 'x'}) and menu.repeatable('use', {'item': 'x'})


def test_a_slash_reply_and_a_menu_result_agree_on_when_again_is_offered():
    citizen()
    for command, options in [('relax', {}), ('eat', {}), ('eat', {'food': 'x'}), ('use', {}), ('use', {'item': 'x'}), ('inventory', {}),
                             ('seedindustries', {'action': 'sell', 'item': 'x'}), ('hobby', {})]:
        legacy, legacy_options = m.discord_legacy_route(command, options)
        row = menu.after_command(command, options, '111')
        assert ('Again' in [c['label'] for c in row['components']]) == menu.repeatable(legacy, legacy_options), (command, options)


def test_again_also_leads_the_nav_row_of_a_panel_and_gets_its_own_row_without_one(monkeypatch):
    citizen()
    panel = {'embeds': [{'title': 'Panel'}], 'components': [ui.row(ui.button(f'P{i}', ui.cid('111', 'mn', 'work', i))) for i in range(5)]}
    monkeypatch.setattr(ui, 'slash_panel', lambda *args: dict(panel, components=list(panel['components'])))
    data = do(raw=['relax', {}])
    assert last_row(data) == ['Again', 'Back', 'Menu'] and len(data['components']) == 5 and last_row({'components': data['components'][:1]}) == ['P0']
    monkeypatch.undo()
    monkeypatch.setattr(menu, 'nav', lambda *args, **kwargs: None)
    data = do(raw=['relax', {}])
    assert last_row(data) == ['Again'] and again_action(data) == {'do': 'cmd', 'raw': ['relax', {}]}


SALE_ROW = ['Undo sale (60s)', 'Sell another', 'Auto-sell', 'Always keep']


def test_every_successful_sale_gets_the_sale_row_and_a_refused_one_does_not():
    citizen(lumber=10)
    sell = press(ui.cid('111', 'mp', 'sell'), values=[LUMBER])['data']
    picked = press(find(sell, 'Sell 5')['custom_id'])['data']              # an amount from the amount picker
    assert [c['label'] for c in picked['components'][0]['components']] == SALE_ROW and 'sold 5' in json.dumps(picked, ensure_ascii=False)
    with m.SessionLocal() as db:                                           # a typed amount
        typed = menu.submit(db, m.player(db, W, 'discord', '111', 'Kam')[1], '111', 'Kam', 'sell', [LUMBER], '3')
    assert typed['amount'] == 3 and [c['label'] for c in menu.run('111', 'Kam', typed)['components'][0]['components']] == SALE_ROW
    assert [c['label'] for c in do(leaf='sell', value=LUMBER)['components'][0]['components']] == SALE_ROW      # Sell all: the rest (2)
    for refused in (do(leaf='sell', value=LUMBER, amount=5), do(leaf='sell', value=LUMBER)):      # nothing left: "only has 0", "Nothing sold"
        assert not {'Undo sale (60s)', 'Sell another'} & {c['label'] for c in controls(refused)}
    assert menu.sold('🏭 Kam sold 5 Lumber to Seed Industries for 10 SC.') and not menu.sold('🏭 You have no Lumber. Nothing sold.')


def test_a_friends_activity_gets_the_citizen_and_shows_that_citizens_activities_again(monkeypatch):
    citizen('111'); citizen('222')
    friends = press(ui.cid('111', 'mk', 'friend'))['data']
    who = friends['components'][0]['components'][0]['options'][0]['value']
    screen = press(ui.cid('111', 'mp', 'friend'), values=[who])['data']
    calls, real = [], m._discord_call_internal
    monkeypatch.setattr(m, '_discord_call_internal', lambda command, uid, name, options, interaction_id:
                        calls.append((command, dict(options))) or real(command, uid, name, options, interaction_id))
    result = press(find(screen, 'Say hi')['custom_id'])['data']
    assert calls == [('social', {'action': 'hi', 'player': who})]            # the command had no player before, and refused: "Select player"
    assert 'Select player' not in json.dumps(result, ensure_ascii=False) and 'says hi' in json.dumps(result, ensure_ascii=False)
    names = [c['label'] for c in controls(result)]
    assert names == [c['label'] for c in controls(screen)] == [label for _, label, _ in menu.SOCIAL] + ['Back', 'Menu']   # the Friends screen again
    assert not {'Sleep', 'Relax', 'Games', 'Friends'} & set(names)               # not the Life grid
    buttons = [c for c in controls(result) if c['custom_id'].split('|')[2] == 't']
    assert [ui.claim('111', c['custom_id'].split('|')[3])[0] for c in buttons] == [
        {'do': 'cmd', 'leaf': 's_' + a, 'value': who} for a, _, _ in menu.SOCIAL]      # fresh tickets, the same citizen


def test_a_friends_activity_keeps_the_activities_when_it_comes_back_as_a_panel(monkeypatch):
    citizen('111'); citizen('222')
    panel = {'embeds': [{'title': 'Panel'}], 'components': [ui.row(ui.button(f'P{i}', ui.cid('111', 'mn', 'work', i))) for i in range(3)]}
    monkeypatch.setattr(ui, 'slash_panel', lambda *args: dict(panel, components=list(panel['components'])))
    rows = [[c['label'] for c in r['components']] for r in do(leaf='s_hi', value='citizen:2')['components']]
    assert len(rows) == 5 and rows[:2] == [['P0'], ['P1']] and rows[2][0] == 'Say hi' and rows[3][0] == 'Duo research' and rows[4] == ['Back', 'Menu']
