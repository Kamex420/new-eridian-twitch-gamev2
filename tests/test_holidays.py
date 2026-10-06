"""Halloween trick-or-treat (5 doors a day) and holiday hats from the Feast trophies."""
import json
from datetime import date
import pytest
from sqlalchemy import select
from test_colony import m, reset, seed
from test_workbench_ui import citizen, press, controls, W
from test_layout_v2 import assert_valid
from app import halloween, seasons, trophies, seasonal, ui, menu, layout_v2 as v2
from app.stream_overlay import StreamHighlight


@pytest.fixture
def festival(monkeypatch):
    monkeypatch.setattr(halloween, 'open_now', lambda today=None: True)


def knock(roll=None, uid='u'):
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', uid, 'Kamex')[1]
        text = halloween.trick(m, db, p, 'twitch', roll=roll)
        db.commit()
        return text


def labels(data):
    return [c.get('label') or '' for c in controls(data)]


# ---------------------------------------------------------------- trick-or-treat

def test_five_doors_a_day_then_the_lights_go_out(festival):
    seed()
    replies = [knock(0.9) for _ in range(5)]
    assert '4 doors left today' in replies[0] and 'That was your last door today' in replies[4]
    assert 'porch lights are off' in knock(0.9)
    with m.SessionLocal() as db:
        assert db.get(halloween.TrickOrTreat, ('test', 'u', m.now().date().isoformat())).tries == 5


def test_the_count_starts_again_the_next_day(festival, monkeypatch):
    seed()
    for _ in range(5):
        knock(0.9)
    later = m.now() + m.timedelta(days=1)
    monkeypatch.setattr(m, 'now', lambda: later)
    assert '4 doors left today' in knock(0.9)


@pytest.mark.parametrize('roll, expect', [(0.1, 'TRICK'), (0.25, 'BIG TREAT'), (0.4, 'SC'), (0.9, 'TREAT')])
def test_every_outcome_gives_what_it_says(festival, roll, expect):
    seed()
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        before_sc, before_morale = p.sc, m.life_state(db, p).morale
        m.life_state(db, p).morale = 50
        db.commit()
    text = knock(roll)
    assert expect in text
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        if expect == 'TRICK':
            assert m.life_state(db, p).morale == 51
        if expect == 'SC':
            assert 2 <= p.sc - before_sc <= 5
        if expect == 'BIG TREAT':
            foods = [k for k, v in seasonal.FESTIVAL_ITEMS.items() if v['holiday'] == 'Halloween']
            assert sum(m.material_amount(db, p, k) for k in foods) == 1
            assert db.execute(select(StreamHighlight).where(StreamHighlight.kind == 'holiday')).scalars().first() is not None


def test_closed_outside_the_halloween_festival(monkeypatch):
    seed()
    monkeypatch.setattr(halloween, 'open_now', lambda today=None: False)
    text = knock()
    assert 'opens with the Halloween festival' in text
    with m.SessionLocal() as db:
        assert db.execute(select(halloween.TrickOrTreat)).first() is None          # a closed door uses no try


def test_the_festival_window_is_october_into_november():
    assert halloween.open_now(date(2026, 10, 6)) and halloween.open_now(date(2026, 11, 7))
    assert not halloween.open_now(date(2026, 9, 20)) and not halloween.open_now(date(2026, 11, 20))


def test_discord_slash_command_menu_button_and_twitch(festival):
    citizen()
    text = m._discord_call_internal('life', '111', 'Kam', {'action': 'trick'}, 'i1')
    assert 'goes door to door' in text and '4 doors left today' in text
    panel = ui.slash_panel(m, 'trick', '111', 'Kam', {}, text)
    assert 'Knock again' in labels(panel) and assert_valid(v2.convert(panel))
    again = press(next(c for c in controls(panel) if c.get('label') == 'Knock again')['custom_id'])
    assert '3 doors left today' in json.dumps(again, ensure_ascii=False)
    life = press(ui.cid('111', 'mn', 'life'))['data']
    assert 'Trick-or-treat' in labels(life)
    seed()
    chat = m.trick_or_treat('test', 'u', 'Kamex', 'twitch').body.decode()
    assert 'door to door' in chat and '\n' not in chat and len(chat.encode()) <= 400


def test_the_menu_button_hides_once_the_doors_are_used_up(festival):
    citizen()
    for _ in range(5):
        m._discord_call_internal('life', '111', 'Kam', {'action': 'trick'}, 'i')
    assert 'Trick-or-treat' not in labels(press(ui.cid('111', 'mn', 'life'))['data'])


# ---------------------------------------------------------------- holiday hats

def test_every_holiday_feast_trophy_wins_a_hat():
    trophies._build(m)
    for holiday in seasonal.FESTIVAL_FOODS:
        t = trophies.TROPHIES['feast_' + seasonal._slug(holiday)]
        assert t['hat'] in seasons.HATS and seasons.HATS[t['hat']][1] in t['text'], holiday


def test_crafting_every_halloween_food_wins_the_witch_hat():
    seed()
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        for recipe, holiday in seasonal.FESTIVAL_RECIPES.items():
            if holiday == 'Halloween':
                m.craft_record(db, p, recipe)
        db.commit()
        notes = trophies.check(m, db, p, force=True)
        db.commit()
        assert any('Halloween Feast' in n and 'Witch hat' in n for n in notes)
        assert 'witch' in seasons.hats_of(db, p)[0]
        assert 'Witch hat' in seasons.wear(db, p, 'witch')


def test_a_feast_won_before_hats_existed_still_gets_its_hat():
    seed()
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        db.add(trophies.m_ach()(channel_id='test', canonical_uid='u', code=trophies.PREFIX + 'feast_christmas'))
        db.commit()
        notes = trophies.check(m, db, p, force=True)
        db.commit()
        assert any('Santa hat' in n for n in notes) and 'santa' in seasons.hats_of(db, p)[0]
        assert not any('Santa hat' in n for n in trophies.check(m, db, p, force=True))     # only once


def test_the_map_draws_every_hat():
    from fastapi.testclient import TestClient
    page = TestClient(m.app).get('/obs/map').text
    for key in seasons.HOLIDAY_HATS.values():
        assert f"'{key}'" in page and f"k==='{key}'" in page, key


def test_every_holiday_theme_has_a_detailed_scene():
    """Each theme in the map's HOLIDAYS table draws its own scene on the crossing (stream_overlay.decorate)."""
    import re
    from fastapi.testclient import TestClient
    page = TestClient(m.app).get('/obs/map').text
    themes = set(re.findall(r"\],'([a-z]+)'\]", page[page.index('const HOLIDAYS='):page.index('const HOLIDAYS=') + 1200]))
    assert {'halloween', 'christmas', 'feast', 'newyear', 'valentine', 'flag', 'grill', 'labor'} <= themes
    for theme in themes:
        name = {'newyear': 'NewYear'}.get(theme, theme.title())
        assert f'function scene{name}(' in page and f'{theme}:scene{name}' in page, theme
    assert 'id="festlights"' in page          # night lights are drawn above the darkness
