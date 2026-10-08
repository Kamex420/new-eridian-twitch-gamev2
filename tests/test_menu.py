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
