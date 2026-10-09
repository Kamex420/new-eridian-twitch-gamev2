"""The weekly recap opens with a short story written by Claude (app/recap.py, app/ai.py): off without a key, written once
a week, never inside the game lock, and always inside Discord's limits. No test reaches the network: ai._post is replaced."""
import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from test_colony import m, reset, client
from test_community import call, gather_lumber
from test_workbench_ui import citizen
from test_buttons_everywhere import moderator_press
from app import ai, community, discord_execution, layout_v2, live_events as le, recap, seasons, task_queue, trophies, ui
from app.db import connection_context

W = m.DISCORD_WORLD_ID
STORY = ('Ann gathered lumber all week and the settlement kept growing. Neighbours waved across the fields, the evenings were '
         'calm, and everyone agreed that Avesta felt a little more like home. ') * 2
TOP = '🏆 Top contributors'


@pytest.fixture(autouse=True)
def enabled(reset, monkeypatch):
    monkeypatch.setattr(community, 'ENABLED', True)
    monkeypatch.setattr(m, 'ADMIN_KEY', 'test-admin-key')
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    le._chatters.clear()
    trophies._last.clear()
    recap._asked.clear()


@pytest.fixture
def claude(monkeypatch):
    """The recap's Claude features on with a fake key; every request is recorded instead of sent."""
    seen = SimpleNamespace(payloads=[], timeouts=[], locked=[], text=STORY.strip(), fail=False)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-test-not-a-real-key')
    for name in ('ANTHROPIC_MODEL', 'AI_FEATURES', 'AI_DAILY_LIMIT', 'AI_FIND_PER_PLAYER'):
        monkeypatch.delenv(name, raising=False)

    def post(payload, timeout):
        seen.payloads.append(payload)
        seen.timeouts.append(timeout)
        seen.locked.append(connection_context.get() is not None)      # whether the game lock was held for this call
        if seen.fail:
            raise TimeoutError('gave up')
        return {'content': [{'type': 'text', 'text': seen.text}]}
    monkeypatch.setattr(ai, '_post', post)
    return seen


@pytest.fixture
def discord(monkeypatch):
    """A Discord channel for the recap: each post is recorded as (url, body)."""
    sent = []

    class Reply:
        status_code = 200
    monkeypatch.setattr('requests.post', lambda url, **kw: sent.append((url, kw['json'])) or Reply())
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'token')
    monkeypatch.setenv('RECAP_CHANNEL_ID', '123456789012345678')
    return sent


def play():
    call('/api/v1/start', uid='a', name='Ann')
    gather_lumber('a', 'Ann', 2)


def size(body):
    return len(body['title']) + len(body['footer']['text']) + sum(len(f['name']) + len(f['value']) for f in body['fields'])


def preview(write=True):
    """The recap as the owner's menu preview builds it (no game lock held)."""
    with m.SessionLocal() as db:
        out = recap.build(db, write=write)
        db.commit()
        return out


def kept():
    with m.SessionLocal() as db:
        return ai.kept(db, recap.story_key())


# ---------------------------------------------------------------- off

@pytest.mark.parametrize('how', ['no key', 'recap switched off'])
def test_with_ai_off_the_recap_is_exactly_as_before(how, monkeypatch):
    if how == 'no key':
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    else:
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-test-not-a-real-key')
        monkeypatch.setenv('AI_FEATURES', 'find,seedling')
    monkeypatch.setattr(ai, '_post', lambda *a: pytest.fail('no call while the feature is off'))
    play()
    title, sections, plain = preview(write=False)
    again = preview(write=True)
    assert again[1] == sections and again[2] == plain                           # asking for a story changes nothing
    assert sections[0][0] == TOP and all(h != recap.STORY_HEADING for h, _ in sections)
    assert plain == title + '\n\n' + '\n\n'.join(f'{h}\n{t}' for h, t in sections)
    assert [f['name'] for f in recap.embed(title, sections)['fields']] == [h for h, _ in sections]
    with m.SessionLocal() as db:
        assert ai.used(db) == 0 and ai.kept(db, recap.story_key()) == ''
    monkeypatch.setattr(recap, 'due', lambda when=None: True)
    assert recap.prepare() is False                                               # nothing to write ahead of Sunday either


# ---------------------------------------------------------------- the story

def test_the_story_comes_first_and_is_written_from_the_weeks_real_names_and_numbers(claude):
    play()
    title, sections, plain = preview()
    assert sections[0] == (recap.STORY_HEADING, claude.text) and sections[1][0] == TOP
    assert recap.STORY_HEADING == '📖 This week on Avesta'
    assert plain.startswith(f'{title}\n\n{recap.STORY_HEADING}\n{claude.text}\n\n{TOP}')
    (payload,) = claude.payloads
    assert claude.timeouts == [20] and payload['max_tokens'] == 350 and payload['model'] == ai.DEFAULT_MODEL
    system = payload['system'][0]['text']
    assert system == recap.STORY_SYSTEM
    for rule in ('New Eridian', 'planet Avesta', '90 to 130 words', 'only the facts', 'Keep every name and number exactly',
                 'Do not invent', 'no headings', 'no @mentions', 'no hashtags'):
        assert rule in system, rule
    prompt = payload['messages'][0]['content']
    with m.SessionLocal() as db:
        row = db.query(seasons.WeekScore).filter_by(week=seasons.week_key()).order_by(seasons.WeekScore.points.desc()).first()
    assert row.points > 0 and 'Ann' in prompt and f'{row.points:,} pts' in prompt          # the real name and number
    assert recap.plain_facts(title, sections[1:]) in prompt and '**' not in prompt          # every section, as plain text
    assert all(h in prompt for h, _ in sections[1:]) and recap.STORY_HEADING not in prompt
    assert kept() == claude.text
    assert recap.story_key() == f'recap:{W}:{recap.week_start().strftime("%Y-%m-%d")}'


def test_preview_then_post_makes_one_api_call(claude, discord):
    play()
    preview()
    with m.SessionLocal() as db:
        title, sections, _ = recap.build(db, write=True)                           # a second preview reads what was kept
        ok, _ = recap.post(db, force=True)
        db.commit()
    assert ok and len(claude.payloads) == 1
    text = layout_v2.text_of(discord[0][1])
    assert claude.text in text and text.index(recap.STORY_HEADING) < text.index('Top contributors')
    assert recap.embed(title, sections)['fields'][0] == {'name': recap.STORY_HEADING, 'value': claude.text, 'inline': False}


def test_a_story_from_earlier_numbers_is_written_again(claude):
    play()
    preview()
    with m.SessionLocal() as db:
        row = db.get(ai.AiText, recap.story_key())
        row.created_at = m.now() - recap.STORY_FRESH - timedelta(minutes=1)         # previewed on Wednesday, posting Sunday
        db.commit()
        assert recap.build(db)[1][0][0] == TOP                                      # the locked recap never uses it
    claude.text = 'A new week of work, and Ann led it again.'
    assert preview()[1][0] == (recap.STORY_HEADING, claude.text) and len(claude.payloads) == 2
    assert kept() == claude.text
    preview()
    assert len(claude.payloads) == 2                                                # fresh again: kept


def test_an_api_failure_or_an_empty_reply_leaves_the_recap_without_a_story(claude, discord):
    claude.fail = True
    play()
    assert preview()[1][0][0] == TOP and kept() == ''
    with m.SessionLocal() as db:
        ok, _ = recap.post(db, force=True)
        db.commit()
    assert ok and recap.STORY_HEADING not in layout_v2.text_of(discord[0][1])         # it still posts
    claude.fail, claude.text = False, ''
    assert preview()[1][0][0] == TOP and kept() == ''
    claude.text = STORY.strip()
    assert preview()[1][0][0] == recap.STORY_HEADING and len(claude.payloads) == 3  # the next preview tries again


# ---------------------------------------------------------------- Discord's limits

def test_a_long_story_stays_inside_discords_limits(claude):
    claude.text = 'The settlers worked together through a long and happy week on Avesta. ' * 40         # 2800 characters
    play()
    title, sections, _ = preview()
    story = sections[0][1]
    assert recap.STORY_HEADING == sections[0][0] and 500 < len(story) <= recap.STORY_FIELD and story.endswith('.')
    body = recap.embed(title, sections)
    assert body['fields'][0]['value'] == story and all(len(f['value']) <= 1024 and len(f['name']) <= 256 for f in body['fields'])
    assert len(body['fields']) <= 25 and size(body) <= 6000


def test_the_embed_gives_up_the_story_before_it_passes_6000_characters():
    story = (recap.STORY_HEADING, 'x' * recap.STORY_FIELD)
    rest = [(f'Section {i}', 'y' * 1000) for i in range(5)]
    over = recap.embed('Title', [story] + rest)
    assert [f['name'] for f in over['fields']] == [h for h, _ in rest] and size(over) <= 6000
    fits = recap.embed('Title', [story] + rest[:3])
    assert fits['fields'][0]['name'] == recap.STORY_HEADING and size(fits) <= 6000
    plain = recap.embed('Title', rest)                                              # without a story nothing is dropped
    assert len(plain['fields']) == 5


# ---------------------------------------------------------------- the game lock

def test_the_timer_writes_the_story_before_the_lock_and_the_locked_post_reads_it(claude, discord, monkeypatch):
    play()
    monkeypatch.setattr(recap, 'due', lambda when=None: True)
    events, real = [], recap.tick

    def spy(db):
        events.append(('recap.tick', connection_context.get() is not None))
        return real(db)
    monkeypatch.setattr(recap, 'tick', spy)
    community.tick()
    assert len(claude.payloads) == 1 and claude.locked == [False]                   # the call happened, outside the lock
    assert events == [('recap.tick', True)]                                         # and the post read it inside
    text = layout_v2.text_of(discord[0][1])
    assert len(discord) == 1 and claude.text in text and text.index(recap.STORY_HEADING) < text.index('Top contributors')
    with m.SessionLocal() as db:
        assert db.get(recap.RecapPost, (W, seasons.week_key())).sent == 1
    community.tick()
    assert len(claude.payloads) == 1 and len(discord) == 1                          # posted once, written once


def test_the_same_call_inside_the_game_lock_is_refused_and_the_recap_goes_without_it(claude, discord, monkeypatch):
    play()
    monkeypatch.setattr(recap, 'due', lambda when=None: True)
    with task_queue.atomic(W):                                                      # what recap.tick() runs inside
        with m.SessionLocal() as db:
            assert recap.build(db, write=True)[1][0][0] == TOP
            assert recap.prepare() is False                                         # even the timer's step will not start here
    assert claude.payloads == [] and kept() == ''


def test_a_failing_story_does_not_stop_the_sunday_post_and_is_not_asked_again_at_once(claude, discord, monkeypatch):
    claude.fail = True
    play()
    monkeypatch.setattr(recap, 'due', lambda when=None: True)
    assert recap.prepare() is True and len(claude.payloads) == 1
    assert recap.prepare() is False and len(claude.payloads) == 1                   # the next timer pass leaves Claude alone
    recap._asked[recap.story_key()] -= recap.STORY_RETRY
    assert recap.prepare() is True and len(claude.payloads) == 2
    community.tick()                                                               # the timer posts the recap without a story
    assert len(discord) == 1 and recap.STORY_HEADING not in layout_v2.text_of(discord[0][1])
    assert recap.prepare() is False and len(claude.payloads) == 2                   # posted: nothing more to write


def test_the_timer_does_not_write_when_the_recap_cannot_post(claude, monkeypatch):
    play()
    monkeypatch.setattr(recap, 'due', lambda when=None: True)
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'token')
    monkeypatch.setenv('RECAP_CHANNEL_ID', '')
    monkeypatch.setenv('DISCORD_GAME_CHANNEL_ID', '')
    assert recap.prepare() is False                                                 # no channel: no post, so no story
    monkeypatch.setenv('RECAP_CHANNEL_ID', '123456789012345678')
    monkeypatch.setattr(recap, 'due', lambda when=None: False)
    assert recap.prepare() is False                                                 # not Sunday evening yet
    assert claude.payloads == []


def test_the_slash_preview_runs_inside_the_lock_and_shows_only_a_kept_story(claude):
    play()
    said = discord_execution.execute({'id': 'i1'}, 'recappreview', '111', 'Mod', {})
    assert 'Weekly' in said and recap.STORY_HEADING not in said and claude.payloads == []      # nothing kept yet: as today
    preview()
    said = discord_execution.execute({'id': 'i2'}, 'recappreview', '111', 'Mod', {})
    assert recap.STORY_HEADING in said and claude.text[:40] in said and len(claude.payloads) == 1


def test_the_menu_preview_writes_the_story_outside_the_lock_and_post_now_only_reads_it(claude, discord):
    citizen('111')
    play()
    shown = json.dumps(moderator_press(ui.cid('111', 'mv', 'm_recap'))['data'], ensure_ascii=False)
    assert claude.locked == [False] and len(claude.payloads) == 1                   # the menu holds no lock: it may write
    assert recap.STORY_HEADING in shown and claude.text[:40] in shown
    ui.run_ticket('111', 'Kam', {'do': 'cmd', 'leaf': 'm_recappost'})              # Post weekly recap now: runs in the lock
    assert len(claude.payloads) == 1 and len(discord) == 1
    assert claude.text in layout_v2.text_of(discord[0][1])                          # the preview's story, not a second call


def test_post_now_without_a_kept_story_posts_the_recap_without_one(claude, discord):
    citizen('111')
    play()
    moderator_press(ui.cid('111', 'mn', 'home'))                                    # sets who is pressing (the owner)
    ui.run_ticket('111', 'Kam', {'do': 'cmd', 'leaf': 'm_recappost'})
    assert claude.payloads == [] and len(discord) == 1
    assert recap.STORY_HEADING not in layout_v2.text_of(discord[0][1])
    assert 'Posted' in discord_execution.execute({'id': 'i9'}, 'recappost', '111', 'Kam', {})      # /mod recappost: also locked
    assert claude.payloads == [] and len(discord) == 2


def test_the_web_previews_hold_the_lock_so_they_only_read(claude):
    play()
    params = {'action': 'preview', 'key': 'test-admin-key', 'level': 1500}
    assert recap.STORY_HEADING not in client.get('/api/v1/recap').text
    assert recap.STORY_HEADING not in client.get('/api/v1/admin/recap', params=params).text
    assert claude.payloads == []
    preview()
    assert recap.STORY_HEADING in client.get('/api/v1/recap').text
    assert claude.text in client.get('/api/v1/admin/recap', params=params).text and len(claude.payloads) == 1


def test_the_twitch_line_is_unchanged(claude):
    play()
    with m.SessionLocal() as db:
        line = recap.chat_line(db)
    assert line.startswith('📰 This week so far: 🥇 Ann') and recap.STORY_HEADING not in line
    assert client.get('/api/v1/recap', params={'provider': 'twitch'}).text == line and claude.payloads == []
