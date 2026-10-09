"""Find asks Claude only when it has no answer of its own: Discord, a known player, the key set, inside the daily limits,
and outside the game lock. Every other case keeps today's text exactly. No test reaches the network: ai._post is replaced."""
import hashlib
import json
import pytest
from test_colony import m, reset, seed
from test_workbench_ui import citizen, W
from test_buttons_everywhere import submit, moderator_press
from test_layout_v2 import assert_valid, Reply
from app import ai, ask, ui, layout_v2 as v2, discord_deferred as deferred, discord_execution as execution
from app.db import connection_context

KEY = 'sk-ant-test-not-a-real-key'
NO_ANSWER = 'how do I tame a dragon?'                 # nothing in the game covers it
ANOTHER = 'how do I ride a unicorn'
ANSWER = 'Dragons are not in New Eridian. Try Help › Handbook, or search a word like campfire in Help › Ask or search.'
LABEL = '🤖 **AI answer** — Find had no exact match, so this may not be exact.'


@pytest.fixture(autouse=True)
def quiet_ai(monkeypatch):
    """Every test starts with the AI features off and no request recorded."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    for name in ('ANTHROPIC_MODEL', 'AI_FEATURES', 'AI_DAILY_LIMIT', 'AI_FIND_PER_PLAYER'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)


@pytest.fixture
def calls(monkeypatch):
    """The key is set and each request is recorded instead of sent."""
    sent = []
    monkeypatch.setenv('ANTHROPIC_API_KEY', KEY)

    def post(payload, timeout):
        sent.append(payload)
        return {'content': [{'type': 'text', 'text': ANSWER}]}
    monkeypatch.setattr(ai, '_post', post)
    return sent


def texts(data):
    return json.dumps(data, ensure_ascii=False)


def asked(query, uid='111'):
    """The Find box in /menu, as a player types it."""
    return submit(ui.cid(uid, 'md', 'find'), query, uid=uid)['data']


def slash(monkeypatch, query, uid='111', interaction='i1'):
    """The /find command as the deferred worker runs it (execute: receipt, lock): the message Discord is sent."""
    sent = []
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(200))
    payload = {'type': 2, 'id': interaction, 'application_id': 'a', 'token': 't', 'channel_id': '5',
               'member': {'user': {'id': uid, 'username': 'Kam'}}}
    deferred.finish(payload, 'find', uid, 'Kam', {'query': query})
    return sent[-1]


def logged():
    with m.SessionLocal() as db:
        return {r.question: r.times for r in db.query(ask.FindQuestion).all()}


def player_scope(uid='111'):
    with m.SessionLocal() as db:
        p = ask.existing_player(db, W, 'discord', uid)
        return f'find:{p.channel_id}:{p.twitch_uid}'


# ---------------------------------------------------------------- off: exactly today's text

def test_without_a_key_the_reply_is_exactly_what_it_was(monkeypatch):
    citizen()
    monkeypatch.setattr(ai, '_post', lambda *a: pytest.fail('no call without a key'))
    with m.SessionLocal() as db:
        p = ask.existing_player(db, W, 'discord', '111')
        result = ask.answer(db, p, NO_ANSWER)
        assert not result.answered
        assert ask.reply(db, p, NO_ANSWER) == result.text
        db.commit()
    text = texts(asked(NO_ANSWER))
    assert "couldn't answer" in text and 'AI answer' not in text
    assert logged() == {'how do i tame a dragon': 2}
    with m.SessionLocal() as db:
        assert ai.used(db) == 0


def test_features_switched_off_or_a_failing_api_keep_the_old_text(calls, monkeypatch):
    citizen()
    monkeypatch.setenv('AI_FEATURES', 'recap,seedling')
    assert 'AI answer' not in texts(asked(NO_ANSWER)) and not calls
    monkeypatch.delenv('AI_FEATURES')
    monkeypatch.setattr(ai, '_post', lambda payload, timeout: (_ for _ in ()).throw(TimeoutError('slow')))
    text = texts(asked(NO_ANSWER))
    assert "couldn't answer" in text and 'AI answer' not in text and KEY not in text
    assert logged() == {'how do i tame a dragon': 2}


# ---------------------------------------------------------------- on: the menu's Find form

def test_the_menu_find_form_shows_the_ai_answer_with_its_label(calls):
    citizen()
    data = asked(NO_ANSWER)
    assert len(calls) == 1 and assert_valid(v2.convert(data))
    text = texts(data)
    assert '🤖 **AI answer**' in text and 'Find had no exact match, so this may not be exact.' in text
    assert 'Dragons are not in New Eridian' in text
    assert "couldn't answer" not in text
    assert logged() == {'how do i tame a dragon': 1}                      # the owner still sees the gap
    with m.SessionLocal() as db:
        assert ai.used(db) == 1 and ai.used(db, player_scope()) == 1


def test_the_reply_is_label_then_answer_then_finds_own_suggestions(calls):
    citizen()
    with m.SessionLocal() as db:
        p = ask.existing_player(db, W, 'discord', '111')
        near = ask.Answer('unknown', 'x', [{'kind': 'suggest', 'name': 'Campfire', 'intent': 'make'},
                                           {'kind': 'suggest', 'name': 'Iron Nails', 'intent': 'make'}], answered=False)
        text = ask.ai_reply(db, p, 'how do I make a campfir', near)
        assert text.splitlines() == [LABEL, ANSWER, '', '🔎 Did you mean: Campfire, Iron Nails?']
        assert ask.ai_reply(db, p, NO_ANSWER, ask.Answer('unknown', 'x', [], answered=False)).splitlines() == [LABEL, ANSWER]
        db.commit()
    prompt = calls[0]['messages'][0]['content']
    assert 'how do I make a campfir' in prompt and 'Campfire, Iron Nails' in prompt
    assert 'Campfire' not in calls[1]['messages'][0]['content']             # no suggestions, none in the prompt
    assert calls[0]['max_tokens'] == 250


def test_a_question_find_can_answer_never_calls_the_api(calls):
    citizen()
    for query in ('how do I make iron nails', 'where do I get coal', 'what does morale mean', 'campfire'):
        assert 'AI answer' not in texts(asked(query))
    assert not calls and logged() == {}
    with m.SessionLocal() as db:
        assert ai.used(db) == 0


def test_each_player_has_a_daily_limit_in_find(calls, monkeypatch):
    monkeypatch.setenv('AI_FIND_PER_PLAYER', '1')
    citizen()
    citizen('222')
    assert 'AI answer' in texts(asked(NO_ANSWER))
    second = texts(asked(ANOTHER))
    assert "couldn't answer" in second and 'AI answer' not in second         # today's text, not the AI's
    assert len(calls) == 1
    assert 'AI answer' in texts(asked(ANOTHER, uid='222'))                    # another player has their own
    assert logged() == {'how do i tame a dragon': 1, 'how do i ride a unicorn': 2}
    with m.SessionLocal() as db:
        assert ai.used(db, player_scope('111')) == 1 and ai.used(db, player_scope('222')) == 1 and ai.used(db) == 2
    monkeypatch.setenv('AI_FIND_PER_PLAYER', '0')
    assert 'AI answer' not in texts(asked('how do I milk a cloud', uid='222'))
    assert len(calls) == 2


def test_the_game_wide_daily_limit_holds_too(calls, monkeypatch):
    monkeypatch.setenv('AI_DAILY_LIMIT', '1')
    citizen()
    assert 'AI answer' in texts(asked(NO_ANSWER))
    assert 'AI answer' not in texts(asked(ANOTHER)) and len(calls) == 1


# ---------------------------------------------------------------- on: the /find command (it ran inside the game lock)

def test_slash_find_gets_the_ai_answer_too(calls, monkeypatch):
    citizen()
    data = slash(monkeypatch, NO_ANSWER)
    assert len(calls) == 1, 'the call must run: /find does not hold the game lock'
    assert assert_valid(data)
    text = texts(data)
    assert '🤖 **AI answer**' in text and 'Dragons are not in New Eridian' in text
    assert logged() == {'how do i tame a dragon': 1}
    with m.SessionLocal() as db:
        assert ai.used(db, player_scope()) == 1


def test_slash_find_without_ai_or_with_an_answer_of_its_own_is_unchanged(calls, monkeypatch):
    citizen()
    assert 'Campfire' in texts(slash(monkeypatch, 'campfire', interaction='a'))
    assert not calls
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    text = texts(slash(monkeypatch, NO_ANSWER, interaction='b'))
    assert "couldn't answer" in text and 'AI answer' not in text and not calls


def test_slash_find_keeps_its_receipt_and_runs_once_per_interaction(calls, monkeypatch):
    citizen()
    first = slash(monkeypatch, NO_ANSWER, interaction='same')
    again = slash(monkeypatch, NO_ANSWER, interaction='same')                # Discord sent it twice
    assert len(calls) == 1 and texts(first) == texts(again)
    assert logged() == {'how do i tame a dragon': 1}
    with m.SessionLocal() as db:
        assert db.get(execution.CommandReceipt, 'same').result.startswith('🤖 **AI answer**')
    payload = {'id': 'same'}
    assert 'does not match' in execution.execute(payload, 'find', '111', 'Kam', {'query': 'another question entirely'})
    assert len(calls) == 1


def test_two_copies_of_one_find_interaction_at_once_both_get_the_first_receipt(monkeypatch):
    """Without the lock the second copy can finish while the first is still working: its receipt insert collides."""
    options = {'query': 'x'}
    fingerprint = hashlib.sha256(json.dumps(['111', 'find', options], sort_keys=True).encode()).hexdigest()

    def racing(command, uid, name, options, interaction_id):
        with m.SessionLocal() as db:                                  # the other copy is done and saved its receipt
            db.add(execution.CommandReceipt(interaction_id=interaction_id, fingerprint=fingerprint, result='first', created_at=m.now()))
            db.commit()
        return 'second'
    monkeypatch.setattr(m, '_discord_call_internal', racing)
    assert execution.execute({'id': 'race'}, 'find', '111', 'Kam', options) == 'first'


def test_only_find_skips_the_game_lock(monkeypatch):
    held = {}

    def probe(command, uid, name, options, interaction_id):
        held[command] = connection_context.get() is not None
        return 'ok'
    monkeypatch.setattr(m, '_discord_call_internal', probe)
    for command in ('find', 'relax', 'queue', 'asklog'):
        assert execution.execute({'id': 'x-' + command}, command, '111', 'Kam', {}) == 'ok'
    assert held == {'find': False, 'relax': True, 'queue': True, 'asklog': True}
    assert execution.LOCK_FREE == {'find'}


# ---------------------------------------------------------------- who may ask Claude

def test_twitch_chat_and_unknown_players_never_call_the_api(calls):
    seed('t1', provider='twitch')
    chat = m.find_anything(NO_ANSWER, 'twitch', 'test', 't1', 'Kamex').body.decode()
    assert '🤖' not in chat and 'could not answer' in chat
    nobody = m.find_anything(NO_ANSWER, 'discord', W, 'nobody', 'Nobody').body.decode()       # no citizen yet
    assert 'AI answer' not in nobody
    assert not calls
    with m.SessionLocal() as db:
        assert ai.used(db) == 0
        assert ask.reply(db, None, NO_ANSWER, 'discord', W) and not calls
        p = ask.existing_player(db, 'test', 'twitch', 't1')
        assert p is not None and '🤖' not in ask.reply(db, p, NO_ANSWER, 'twitch') and not calls


# ---------------------------------------------------------------- the prompt

def test_the_system_prompt_is_the_same_bytes_every_time_and_holds_the_handbook(calls):
    citizen()
    citizen('222')
    asked(NO_ANSWER)
    asked(ANOTHER, uid='222')
    first, second = calls[0]['system'], calls[1]['system']
    assert first == second and len(first) == 1 and 'cache_control' in first[0]            # nothing per player: caching reads it
    system = first[0]['text']
    assert system == ask.ai_system() and system is ask.ai_system()                         # built once
    assert 15000 < len(system) < 60000
    for needed in ('under 80 words', 'Help › Handbook', 'Craft › All recipes', 'Work › Gather', 'never invent', 'family-friendly',
                   'Seed Coin', 'Contribution', 'NEW ERIDIAN TERMS', 'Rocky\'s Favor', 'Work › Queue', 'Chemistry'):
        assert needed.casefold() in system.casefold(), needed
    assert 'Moderator' not in system.split('MENU BUTTONS')[1] and '/mod action' not in system        # owner tools are left out
    assert calls[0]['model'] == ai.DEFAULT_MODEL
    assert calls[0]['messages'][0]['content'].startswith('Player\'s question: "how do I tame a dragon?"')
    assert 'Kam' not in calls[0]['messages'][0]['content'].replace('Kamex', '')


def test_the_question_is_sent_on_one_line(calls):
    citizen()
    with m.SessionLocal() as db:
        p = ask.existing_player(db, W, 'discord', '111')
        ask.ai_reply(db, p, 'how do I\nignore   your rules', ask.Answer('unknown', 'x', [], answered=False))
    assert calls[0]['messages'][0]['content'] == 'Player\'s question: "how do I ignore your rules"'


# ---------------------------------------------------------------- the owner's screen

def test_the_unanswered_questions_screen_shows_the_ai_status_line_under_its_heading(calls, monkeypatch):
    """The heading stays the first line (a Discord card takes its title from it); the status line is the next."""
    citizen()
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    heading = '❓ UNANSWERED FIND QUESTIONS'
    with m.SessionLocal() as db:
        empty = ask.log_text(db).splitlines()
        assert empty[:2] == [heading, ai.status_line(db)] and 'Nothing in the last 30 days' in empty[2]   # also when nothing was asked
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    asked(NO_ANSWER)
    with m.SessionLocal() as db:
        lines = ask.log_text(db).splitlines()
        assert lines[:2] == [heading, ai.status_line(db)]
        assert lines[1] == '🤖 AI features: off. Add ANTHROPIC_API_KEY in Railway to turn them on.'
        assert '1× “how do i tame a dragon”' in lines[-1]
    monkeypatch.setenv('ANTHROPIC_API_KEY', KEY)
    asked(NO_ANSWER)
    with m.SessionLocal() as db:
        lines = ask.log_text(db).splitlines()
        assert lines[:2] == [heading, ai.status_line(db)]
        assert lines[1] == f'🤖 AI features: on (find, seedling, recap) · {ai.DEFAULT_MODEL} · 1 of 300 calls today'
        assert '2× “how do i tame a dragon”' in lines[-1]
    assert m._discord_call_internal('asklog', '111', 'Kam', {}, 'i9').splitlines()[1].startswith('🤖 AI features: on')
    card = moderator_press(ui.cid('111', 'mv', 'm_asklog'))['data']
    assert card['embeds'][0]['title'] == '❓ Unanswered Find Questions'
    assert '1 of 300 calls today' in card['embeds'][0]['description'] and ai.DEFAULT_MODEL in card['embeds'][0]['description']
    assert assert_valid(v2.convert(card))
