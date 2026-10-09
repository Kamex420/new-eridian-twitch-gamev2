"""Seedlings speaking in their own words (optional Claude feature, Discord only): the day's thought and diary paragraph are
written once, outside the game lock, from the Seedling's attitude and today's diary entries, and shown in the Overview and
the Diary. Everything without an API key, without a diary entry today or with a garbled reply is exactly what it was.
No test reaches the network: ai._post is replaced."""
import itertools
import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from test_colony import m, reset, client
from test_workbench_ui import citizen, W
from test_menu_walk import checked, press as press_screen, walk
from app import ai, autonomy as a, discord_execution, layout_v2 as v2, looks, ui
from app.db import connection_context

KEY = 'sk-ant-test-not-a-real-key'
UID = 'discord:111'
THOUGHT = 'Another rock, another sigh.'
DIARY = 'I hauled Lumber at the Frontier Edge and nobody said thanks. The wind was rude as well.'
GOOD = f'THOUGHT: {THOUGHT}\nDIARY: {DIARY}'
OVERVIEW = ui.cid('111', 'mv', 'sl_view')
DIARY_BUTTON = ui.cid('111', 'mv', 'sl_diary')


@pytest.fixture
def api(monkeypatch):
    """The feature on with a fake key; every request is recorded instead of sent, and answers `api.reply`."""
    api = SimpleNamespace(sent=[], reply=GOOD, outside_the_lock=[])
    monkeypatch.setenv('ANTHROPIC_API_KEY', KEY)
    for name in ('ANTHROPIC_MODEL', 'AI_FEATURES', 'AI_DAILY_LIMIT', 'AI_FIND_PER_PLAYER'):
        monkeypatch.delenv(name, raising=False)

    def post(payload, timeout):
        api.sent.append(payload)
        api.outside_the_lock.append(connection_context.get() is None and timeout == 10)
        return {'content': [{'type': 'text', 'text': api.reply}]}
    monkeypatch.setattr(ai, '_post', post)
    return api


@pytest.fixture
def no_api(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(ai, '_post', lambda *args: pytest.fail('no API call was expected'))


def seedling(uid='111', name='Kam', today=2, yesterday=0, attitude='grumpy', catchphrase='snacks'):
    """A Discord citizen whose Seedling has `today` diary entries from today and `yesterday` older ones."""
    citizen(uid)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid, name)[1]
        if attitude or catchphrase:
            looks.change(db, p, attitude=attitude, catchphrase=catchphrase)
        for i in range(yesterday):
            a.diary(db, p, 'commons', '🎲', f'{name} — played a game at the Commons (old {i})', headline=f'{name} plays games')
        db.flush()
        for entry in a.entries(db, p, 100):
            entry.created_at = m.now() - timedelta(days=2)
        for i in range(today):
            a.diary(db, p, 'frontier_edge', '🧺', f'{name} — hauled {i + 3} Lumber from the Frontier Edge', headline=f'{name} brings in Lumber')
        db.commit()


def text_of(answer):
    return json.dumps(answer, ensure_ascii=False)


def has_section(text):
    """Whether the Diary shows "TODAY, IN ITS OWN WORDS" (a Discord card shows it as "Today, in Its Own Words")."""
    return 'today, in its own words' in text.lower()


def stored_thought(uid=UID):
    with m.SessionLocal() as db:
        return a.row(db, W, uid, create=True).thought


def kept(uid=UID):
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', uid.split(':')[1], 'Kam')[1]
        return ai.kept(db, a.words_key(p))


INTERACTIONS = itertools.count(1)


def slash(**options):
    """What /seedling does: the whole command runs inside the game lock (discord_execution.execute), once per interaction."""
    return discord_execution.execute({'id': f'slash-{next(INTERACTIONS)}'}, 'seedling', '111', 'Kam', options)


# ---------------------------------------------------------------- off: nothing changes

def test_without_a_key_overview_and_diary_are_unchanged(no_api):
    seedling()
    overview = text_of(press_screen(OVERVIEW))
    diary = text_of(press_screen(DIARY_BUTTON))
    assert not has_section(diary) and 'Another rock' not in overview + diary
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        template = a.row(db, W, UID).thought
        assert template and template in a.view_text(db, p) and 'TODAY, IN ITS OWN WORDS' not in a.diary_text(db, p)
        assert f'*"{template}"*' in a.view_text(db, p) and ai.used(db) == 0


def test_switching_the_seedling_feature_off_hides_the_words(api, monkeypatch):
    seedling()
    press_screen(OVERVIEW)
    assert len(api.sent) == 1 and THOUGHT in text_of(press_screen(OVERVIEW))
    monkeypatch.setenv('AI_FEATURES', 'find,recap')
    assert THOUGHT not in text_of(press_screen(OVERVIEW)) and not has_section(text_of(press_screen(DIARY_BUTTON)))
    assert len(api.sent) == 1


# ---------------------------------------------------------------- on: one call, both screens

def test_the_menu_overview_and_diary_show_the_words_from_one_call(api):
    seedling()
    overview = text_of(press_screen(OVERVIEW))
    assert THOUGHT in overview and f'💭 *\\"{THOUGHT}\\"*' in overview
    diary = text_of(press_screen(DIARY_BUTTON))
    assert has_section(diary) and DIARY in diary
    assert diary.lower().index('today, in its own words') < diary.index('News from your Seedling')   # the paragraph is at the top
    assert 'brings in Lumber' in diary                                                           # the ordinary reports are still there
    press_screen(OVERVIEW)
    press_screen(DIARY_BUTTON)
    assert len(api.sent) == 1 and all(api.outside_the_lock)                                      # one call, made outside the game lock
    assert kept() == GOOD
    with m.SessionLocal() as db:
        assert ai.used(db) == 1 and f'seedling:{W}:{UID}:{ai.today()}' in {r.key for r in db.query(ai.AiText)}
    assert stored_thought() != THOUGHT                                                           # the stored thought is the template's


def test_a_menu_press_writes_before_the_lock_and_the_command_reads_inside_it(api, monkeypatch):
    """The lock question: the /seedling command a menu view runs takes the game lock itself (game_transaction), so the API call
    cannot be made there; menu.show makes it first, outside the lock, and the command only reads what was kept."""
    seedling()
    read_inside_lock = []
    real = a.words
    monkeypatch.setattr(a, 'words', lambda db, p: read_inside_lock.append(ai.locked()) or real(db, p))
    assert THOUGHT in text_of(press_screen(OVERVIEW))
    assert read_inside_lock == [True] and api.outside_the_lock == [True]


def test_the_words_are_kept_for_the_day_and_written_again_tomorrow(api, monkeypatch):
    seedling()
    press_screen(OVERVIEW)
    assert len(api.sent) == 1
    tomorrow = m.now() + timedelta(days=1)
    monkeypatch.setattr(m, 'now', lambda: tomorrow)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        a.diary(db, p, 'commons', '🎲', 'Kam — played a game at the Commons', headline='Kam plays games')
        db.commit()
    api.reply = 'THOUGHT: A fresh day.\nDIARY: I played a game at the Commons.'
    assert 'A fresh day.' in text_of(press_screen(OVERVIEW)) and len(api.sent) == 2


def test_slash_seedling_shows_kept_words_but_never_calls_the_api(api):
    seedling()
    first = slash()
    assert 'Another rock' not in first and not api.sent                       # nothing written yet today: the template, and no call
    assert f'💭 *"{stored_thought()}"*' in first
    press_screen(DIARY_BUTTON)                                                  # a menu press writes the words
    assert len(api.sent) == 1
    assert f'💭 *"{THOUGHT}"*' in slash()
    diary = slash(section='diary')
    assert 'TODAY, IN ITS OWN WORDS' in diary and DIARY in diary
    assert len(api.sent) == 1


def test_nothing_is_written_inside_the_game_lock(api):
    seedling()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        token = connection_context.set(object())                                # what task_queue.atomic sets while it holds the lock
        try:
            assert a.write_words(db, p) is False
        finally:
            connection_context.reset(token)
    assert not api.sent and kept() == ''
    with m.SessionLocal() as db:
        assert a.write_words(db, m.player(db, W, 'discord', '111', 'Kam')[1]) is True      # and outside it, it writes
    assert len(api.sent) == 1 and kept() == GOOD


def test_the_ticket_buttons_inside_the_lock_only_read(api):
    """Let it decide and the schedule buttons run inside the lock: they show kept words and never call the API."""
    seedling()
    decide = next(c for c in walk(press_screen(OVERVIEW)['data']['components']) if c.get('label') == 'Let it decide')
    api.sent.clear()
    result = text_of(press_screen(decide['custom_id']))
    assert 'Seedling' in result and not api.sent
    assert THOUGHT in result                                                    # the Overview written a moment ago is shown


# ---------------------------------------------------------------- when there is nothing to say, or it is garbled

def test_no_diary_entry_today_means_no_call(api):
    seedling(today=0)
    assert THOUGHT not in text_of(press_screen(OVERVIEW)) and not has_section(text_of(press_screen(DIARY_BUTTON)))
    assert not api.sent
    seedling(uid='222', today=0, yesterday=3)                                   # only yesterday's reports
    assert not has_section(text_of(_press('222', 'sl_diary'))) and 'plays games' in text_of(_press('222', 'sl_diary'))
    assert not api.sent
    with m.SessionLocal() as db:
        assert ai.used(db) == 0


def _press(uid, leaf):
    payload = {'type': 3, 'data': {'custom_id': ui.cid(uid, 'mv', leaf), 'values': []},
               'member': {'user': {'id': uid, 'username': 'Kam'}}, 'message': {'flags': 64}}
    return ui.handle_component(payload)


def test_a_garbled_reply_leaves_the_template_and_is_not_asked_for_again(api):
    seedling()
    api.reply = 'The Seedling seems happy today! It enjoyed its day.'
    overview = text_of(press_screen(OVERVIEW))
    diary = text_of(press_screen(DIARY_BUTTON))
    assert not has_section(diary) and 'seems happy' not in overview + diary
    assert f'💭 *\\"{stored_thought()}\\"*' in overview
    press_screen(OVERVIEW)
    assert len(api.sent) == 1                                                   # the day's budget is not spent on retries


@pytest.mark.parametrize('reply,expected', [
    (GOOD, (THOUGHT, DIARY)),
    (f'  THOUGHT:    {THOUGHT}   \n\n   DIARY:   {DIARY}  \n', (THOUGHT, DIARY)),
    (f'**THOUGHT:** *{THOUGHT}*\n**DIARY:** {DIARY}', (THOUGHT, DIARY)),
    (f'- THOUGHT: "{THOUGHT}"\n- DIARY: "{DIARY}"', (THOUGHT, DIARY)),
    (f'thought: {THOUGHT}\ndiary: {DIARY}', (THOUGHT, DIARY)),
    (f'DIARY: {DIARY}\nTHOUGHT: {THOUGHT}', (THOUGHT, DIARY)),                  # either order
    ('THOUGHT: Rocks.\nDIARY: I worked.\nThe rain came after.', ('Rocks.', 'I worked. The rain came after.')),   # a wrapped diary
    (f'THOUGHT: {THOUGHT}', ('', '')),
    (f'DIARY: {DIARY}', ('', '')),
    ('THOUGHT:\nDIARY: I worked.', ('', '')),
    ('', ('', '')),
    ('Just some words.', ('', '')),
])
def test_the_reply_is_parsed_from_its_two_lines(reply, expected):
    assert a.parse_words(reply) == expected


def test_long_replies_are_trimmed():
    thought, diary = a.parse_words('THOUGHT: ' + 'word ' * 100 + '\nDIARY: ' + 'Sentence here. ' * 100)
    assert len(thought) <= a.WORDS_THOUGHT_CHARS and thought.endswith('…') and len(diary) <= a.WORDS_DIARY_CHARS


# ---------------------------------------------------------------- Twitch, the stream and the stored thought stay as they are

def test_twitch_text_the_overlay_and_the_stored_thought_do_not_change(api):
    seedling()
    press_screen(OVERVIEW)
    press_screen(DIARY_BUTTON)
    assert kept() == GOOD
    template = stored_thought()
    assert template and template != THOUGHT
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        twitch = a.view_text(db, p, 'twitch') + a.diary_text(db, p, 'twitch')
    assert THOUGHT not in twitch and DIARY not in twitch and template in twitch
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    me = next(s for s in data['seedlings'] if s['name'] == 'Kam')
    assert me['thought'] == template and THOUGHT not in json.dumps(data) and DIARY not in json.dumps(data)
    assert stored_thought() == template and THOUGHT not in template
    http = client.get('/api/v1/seedling', params={'channel': W, 'uid': '111', 'name': 'Kam', 'provider': 'twitch'}).text
    assert THOUGHT not in http and 'TODAY, IN ITS OWN WORDS' not in client.get(
        '/api/v1/diary', params={'channel': W, 'uid': '111', 'name': 'Kam', 'provider': 'twitch'}).text
    assert len(api.sent) == 1


# ---------------------------------------------------------------- what Claude is told

def test_the_prompt_has_the_attitude_the_mood_and_todays_entries(api):
    seedling(today=2, yesterday=1)
    press_screen(OVERVIEW)
    (payload,) = api.sent
    prompt = payload['messages'][0]['content']
    assert 'Seedling: Kam' in prompt
    assert 'Attitude: Grumpy (complains, but always shows up)' in prompt and 'Catchphrase: "Snacks first."' in prompt
    assert 'Mood: ' in prompt and 'Right now: ' in prompt and 'Weather: ' in prompt
    assert 'Kam brings in Lumber — hauled 3 Lumber from the Frontier Edge (Frontier Edge)' in prompt
    assert 'hauled 4 Lumber' in prompt and 'old 0' not in prompt                 # today's entries only
    assert prompt.index('hauled 3 Lumber') < prompt.index('hauled 4 Lumber')     # oldest first
    assert payload['max_tokens'] == 200 and payload['system'][0]['text'] == a.WORDS_SYSTEM
    for rule in ('THOUGHT:', 'DIARY:', 'at most 15 words', '2 or 3 sentences', 'Never invent items, numbers or people', 'family-friendly'):
        assert rule in a.WORDS_SYSTEM


def test_the_prompt_takes_at_most_eight_entries_and_trims_them(api):
    seedling(today=0)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        for i in range(12):
            a.diary(db, p, 'commons', '🎲', f'Kam — entry number {i:02d} ' + 'and so on ' * 30, headline=f'Kam does thing {i:02d}')
        db.commit()
    press_screen(OVERVIEW)
    prompt = api.sent[0]['messages'][0]['content']
    entries = [line for line in prompt.splitlines() if line.startswith('- ')]
    assert len(entries) == 8 and 'thing 04' in entries[0] and 'thing 11' in entries[-1] and 'thing 03' not in prompt
    assert all(len(line) <= 260 for line in entries)


def test_the_system_prompt_is_the_same_for_every_seedling(api):
    seedling(attitude='shy', catchphrase='')
    seedling(uid='222', name='Zed', attitude='dramatic', catchphrase='hello')
    press_screen(OVERVIEW)
    _press('222', 'sl_view')
    assert len(api.sent) == 2 and api.sent[0]['system'] == api.sent[1]['system']
    assert 'Attitude: Shy' in api.sent[0]['messages'][0]['content'] and 'Catchphrase: none' in api.sent[0]['messages'][0]['content']
    assert 'Attitude: Dramatic' in api.sent[1]['messages'][0]['content'] and 'Zed brings in Lumber' in api.sent[1]['messages'][0]['content']
    assert 'Zed' not in api.sent[0]['messages'][0]['content']                     # each prompt has only its own Seedling's day


def test_a_seedling_without_an_attitude_is_described_plainly(api):
    seedling(attitude='', catchphrase='')
    press_screen(OVERVIEW)
    assert 'Attitude: none chosen' in api.sent[0]['messages'][0]['content']


def test_a_failing_api_shows_the_template(api, monkeypatch):
    seedling()

    def broken(payload, timeout):
        raise TimeoutError('too slow')
    monkeypatch.setattr(ai, '_post', broken)
    overview = text_of(press_screen(OVERVIEW))
    assert f'💭 *\\"{stored_thought()}\\"*' in overview and not has_section(text_of(press_screen(DIARY_BUTTON)))


# ---------------------------------------------------------------- both Discord layouts stay valid

@pytest.mark.parametrize('leaf', ['sl_view', 'sl_diary'])
@pytest.mark.parametrize('words', [True, False])
def test_both_discord_layouts_are_valid(monkeypatch, request, leaf, words):
    """The press answers in the classic layout (embed and buttons); Discord gets it converted to the newer one."""
    from test_layout_v2 import assert_valid
    if words:
        request.getfixturevalue('api')
    else:
        request.getfixturevalue('no_api')
    seedling()
    classic = checked(ui.cid('111', 'mv', leaf), newer=False)
    newer = v2.convert(classic)
    assert newer is not None and assert_valid(newer)
    again = checked(ui.cid('111', 'mv', leaf), newer=True)           # the press from a message already in the newer layout
    assert assert_valid(v2.respond({'type': 7, 'data': again}, {'message': {'flags': 64 | v2.FLAG}})['data'])
    for shown in (text_of(classic), text_of(newer)):
        if words:
            assert (THOUGHT in shown) if leaf == 'sl_view' else has_section(shown) and DIARY in shown
        else:
            assert THOUGHT not in shown and not has_section(shown)
