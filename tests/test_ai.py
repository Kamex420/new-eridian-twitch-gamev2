"""The optional Claude API helper (app/ai.py): off without a key, inside its daily limits, never failing the game,
and never letting a reply ping anyone. No test reaches the network: ai._post is replaced."""
import logging
import pytest
from test_colony import m, reset
from app import ai

KEY = 'sk-ant-test-not-a-real-key'


@pytest.fixture
def calls(monkeypatch):
    """Turn the features on with a fake key and record each request instead of sending it."""
    sent = []
    monkeypatch.setenv('ANTHROPIC_API_KEY', KEY)
    for name in ('ANTHROPIC_MODEL', 'AI_FEATURES', 'AI_DAILY_LIMIT', 'AI_FIND_PER_PLAYER'):
        monkeypatch.delenv(name, raising=False)

    def post(payload, timeout):
        sent.append(payload)
        return {'content': [{'type': 'text', 'text': f'Answer {len(sent)}'}]}
    monkeypatch.setattr(ai, '_post', post)
    return sent


def write(**kw):
    with m.SessionLocal() as db:
        text = ai.write(db, kw.pop('feature', 'find'), kw.pop('system', 'You help.'), kw.pop('prompt', 'Hi'), **kw)
        db.commit()
        return text


def test_off_without_a_key(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(ai, '_post', lambda *a: pytest.fail('no call without a key'))
    assert not ai.enabled('find') and write() == ''
    with m.SessionLocal() as db:
        assert ai.used(db) == 0 and 'off' in ai.status_line(db) and 'ANTHROPIC_API_KEY' in ai.status_line(db)


def test_a_call_sends_the_model_and_a_cached_system_prompt(calls):
    assert write(system='x' * ai.CACHE_MIN_CHARS, prompt='How do I make Iron Nails?', max_tokens=200) == 'Answer 1'
    payload = calls[0]
    assert payload['model'] == ai.DEFAULT_MODEL and payload['max_tokens'] == 200
    assert payload['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert payload['messages'] == [{'role': 'user', 'content': 'How do I make Iron Nails?'}]
    write(system='short')
    assert 'cache_control' not in calls[1]['system'][0]                 # too short to cache


def test_the_daily_limits_hold(calls, monkeypatch):
    monkeypatch.setenv('AI_DAILY_LIMIT', '3')
    assert [write(scope='find:a', per_scope=2) for _ in range(3)] == ['Answer 1', 'Answer 2', '']    # the player's two
    assert write(scope='find:b', per_scope=2) == 'Answer 3'                                          # another player
    assert write(scope='find:c', per_scope=2) == '' and len(calls) == 3                              # the game's three
    with m.SessionLocal() as db:
        assert ai.used(db) == 3 and ai.used(db, 'find:a') == 2 and '3 of 3 calls today' in ai.status_line(db)


def test_features_can_be_switched_off_one_by_one(calls, monkeypatch):
    monkeypatch.setenv('AI_FEATURES', 'recap, seedling')
    assert write(feature='find') == '' and write(feature='recap') == 'Answer 1'
    assert ai.enabled('seedling') and not ai.enabled('find')


def test_a_failing_or_slow_api_answers_without_ai_and_never_logs_the_key(calls, monkeypatch, caplog):
    def broken(payload, timeout):
        raise TimeoutError(f'gave up after {timeout}s')
    monkeypatch.setattr(ai, '_post', broken)
    with caplog.at_level(logging.WARNING):
        assert write() == ''
    assert KEY not in caplog.text and 'TimeoutError' in caplog.text
    monkeypatch.setattr(ai, '_post', lambda payload, timeout: {'content': 'not a list of blocks'})
    assert write() == ''
    with m.SessionLocal() as db:
        assert ai.used(db) == 2                                          # attempts count toward the limit


def test_replies_never_ping_or_invite():
    raw = '## Heading\nHi @everyone and @here, <@123456789> <@&42> <#77> join discord.gg/abc https://discord.com/invite/xyz ok'
    text = ai.clean(raw)
    assert '@everyone' not in text and '@here' not in text and '<@' not in text and '<#' not in text
    assert 'discord.gg' not in text and 'invite' not in text and not text.startswith('#') and text.endswith('ok')
    assert len(ai.clean('word ' * 1000)) <= ai.LIMIT_TEXT


def test_a_kept_text_is_written_once(calls):
    with m.SessionLocal() as db:
        first = ai.written(db, 'recap', 'recap:2026-10-05', 'Write it.', 'The week.')
        db.commit()
    with m.SessionLocal() as db:
        assert ai.written(db, 'recap', 'recap:2026-10-05', 'Write it.', 'The week.') == first == 'Answer 1'
    assert len(calls) == 1


def test_nothing_is_kept_when_nothing_was_written(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    with m.SessionLocal() as db:
        assert ai.written(db, 'recap', 'recap:w', 'Write it.', 'The week.') == '' and ai.kept(db, 'recap:w') == ''


def test_no_call_inside_the_game_lock(calls):
    from app.db import connection_context
    token = connection_context.set(object())               # what task_queue.atomic sets while it holds the lock
    try:
        assert ai.locked() and write() == ''
    finally:
        connection_context.reset(token)
    assert not calls and write() == 'Answer 1'
    with m.SessionLocal() as db:
        assert ai.used(db) == 1                              # the refused call spent nothing
