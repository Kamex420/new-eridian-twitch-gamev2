"""Festival foods as real items, the Comfort rate, and the grouped Discord commands."""
from datetime import date
import pytest
from test_colony import m, reset, seed
from app import seasonal, seed_content as s, workbench as wb, command_catalog, needs

BITES = 'fest_pumpkin_bites'
BITES_RECIPE = 'fr_pumpkin_bites'


def festival(monkeypatch, open_now):
    today = date.today()
    window = (today, today) if open_now else (date(today.year + 5, 1, 1), date(today.year + 5, 1, 2))
    monkeypatch.setattr(seasonal, 'festival_window', lambda holiday, today=None: window)


def stock_up(uid='u'):
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'discord', uid, 'Kamex')[1]
        for name, qty in seasonal.FESTIVAL_ITEMS[BITES]['inputs'].items():
            m.material_change(db, p, s.key(name), qty)
        db.commit()


def test_every_festival_food_is_a_real_edible_item():
    assert len(seasonal.FESTIVAL_ITEMS) == 27
    for key, row in seasonal.FESTIVAL_ITEMS.items():
        assert key in s.EDIBLE and key in s.ACTIVE and s.ITEMS[key]['name'] == row['name']
        e = wb.entry(m, row['recipe'])
        assert e.category == 'food' and e.tags == (seasonal.SURVIVAL_TAG,) and e.tier == 1
        assert m.SEED_INDUSTRIES[key]['sell'] > 0
        assert all(k in s.GATHER for k in e.inputs)


def test_festival_recipe_is_locked_outside_its_window(monkeypatch):
    festival(monkeypatch, False)
    seed(provider='discord'); stock_up()
    result = m.make('test', 'u', 'Kamex', BITES_RECIPE, 'discord', action='craft').body.decode()
    assert 'festival recipe' in result and 'Nothing spent' in result
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        ctx = wb.Context(m, db, p)
        assert ctx.status(wb.entry(m, BITES_RECIPE)).code == 'locked'
        assert s.stock(m, db, p).get(BITES, 0) == 0


def test_festival_food_crafts_in_season_and_eating_adds_comfort(monkeypatch):
    festival(monkeypatch, True)
    seed(provider='discord'); stock_up()
    assert 'CRAFTING COMPLETE' in m.make('test', 'u', 'Kamex', 'Pumpkin Bites', 'discord', action='craft').body.decode()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert s.stock(m, db, p).get(BITES) == 1
        life = m.life_state(db, p); life.comfort = 50; life.nutrition = 30; db.commit()
    eaten = m.action('eat', 'test', 'u', msg='food:' + BITES, provider='discord').body.decode()
    assert 'Festival treat' in eaten
    with m.SessionLocal() as db:
        life = m.life_state(db, db.query(m.Player).one())
        assert life.comfort == 50 + seasonal.FESTIVAL_ITEMS[BITES]['comfort']


def test_holiday_calendar_lists_festival_foods():
    text = seasonal.holiday_message()
    assert 'Festival foods' in text and 'real items' in text
    halloween = seasonal.holiday_message(now=__import__('datetime').datetime(2026, 10, 20))
    assert 'Pumpkin Bites' in halloween and '/make recipe:fr_pumpkin_bites' in halloween
    assert seasonal.festival_open(BITES_RECIPE, date(2026, 10, 20)) and not seasonal.festival_open(BITES_RECIPE, date(2026, 6, 1))


def test_comfort_costs_match_energy_and_relax_restores_more():
    assert needs.comfort_cost(2) == 2 and needs.comfort_cost(3) == 3
    assert needs.finish_forecast(2, 10)['comfort'] == 28
    seed()
    with m.SessionLocal() as db:
        m.life_state(db, db.query(m.Player).one()).comfort = 40; db.commit()
    m.relax('test', 'u')
    with m.SessionLocal() as db:
        assert m.life_state(db, db.query(m.Player).one()).comfort == 40 + needs.RELAX_COMFORT


def test_discord_menu_is_grouped():
    names = {c['name'] for c in command_catalog.commands}
    assert len(names) == 34 and {'life', 'work', 'mod', 'menu', 'find', 'seedling'} <= names
    assert not names & command_catalog.RETIRED
    assert {c['name'] for c in command_catalog.legacy_commands} == command_catalog.RETIRED


@pytest.mark.parametrize('command,options,legacy', [
    ('life', {'action': 'relax'}, ('relax', {})),
    ('life', {'action': 'eat', 'food': 'x'}, ('eat', {'food': 'x'})),
    ('life', {}, ('me', {'section': 'life'})),
    ('work', {'task': 'farm_harvest'}, ('farm', {'action': 'harvest'})),
    ('work', {}, ('training', {})),
    ('mod', {'action': 'eventstart', 'event': 'siro'}, ('eventstart', {'event': 'siro'})),
    ('world', {'section': 'holidays'}, ('holiday', {})),
    ('me', {'section': 'skills'}, ('progress', {'section': 'skills'})),
    ('world', {'section': 'market'}, ('world', {'section': 'market'})),
])
def test_grouped_commands_run_the_original_handlers(command, options, legacy):
    assert m.discord_legacy_route(command, options) == legacy


def test_grouped_commands_work_end_to_end():
    seed('u', provider='discord')
    assert '+25 Energy' in m._discord_call_internal('life', 'u', 'Kamex', {'action': 'relax'}, 'i1')
    assert 'Pumpkin' in m._discord_call_internal('work', 'u', 'Kamex', {'task': 'farm_harvest'}, 'i2')
    assert 'HOLIDAY CALENDAR' in m._discord_call_internal('world', 'u', 'Kamex', {'section': 'holidays'}, 'i3')


def test_game_text_points_at_the_grouped_commands():
    text = m.discord_command_copy('Use /relax or /sleep. Try /farm action:Harvest Pumpkins or /progress section:daily.')
    assert '/relax' not in text and '/farm' not in text and '/progress' not in text
    assert text.count('`/life`') == 2 and '`/work`' in text and '`/me`' in text
