"""Find answers questions about everything else in the game: society stats, Contribution, needs, tiers, housing,
the clinic, and anything the handbook, the commands, the menu or the guide panels explain."""
import json
import pytest
from test_colony import m, reset, seed
from test_workbench_ui import citizen, press, controls, W
from test_buttons_everywhere import submit
from test_layout_v2 import assert_valid
from app import ask, knowledge, ui, layout_v2 as v2


def answer(query, provider='discord', uid='111', channel=W):
    with m.SessionLocal() as db:
        p = ask.existing_player(m, db, channel, 'discord' if channel == W else 'twitch', uid) if uid else None
        result = ask.answer(m, db, p, query, provider)
        db.commit()
        return result


def labels(data):
    return [c.get('label') or '' for c in controls(data)]


def text_of(data):
    return json.dumps(data, ensure_ascii=False).casefold()


def asked(query, uid='111'):
    return submit(ui.cid(uid, 'md', 'find'), query, uid=uid)['data']


# ---------------------------------------------------------------- society stats, read from the real rules

@pytest.mark.parametrize('query', ['how to build reputation', 'how do I get more rep?', 'how can I raise reputation', 'reputation'])
def test_reputation_questions_explain_what_raises_it(query):
    citizen()
    result = answer(query)
    assert result.intent == 'topic' and 'HOW TO RAISE REPUTATION' in result.text
    for way in ('Delivery', 'Business Contract', 'Community Outreach', 'First Aid'):
        assert way in result.text, way
    assert 'Reputation is the lowest' in result.text or 'Now:' in result.text


@pytest.mark.parametrize('stat, action, extra', [
    ('food', 'harvest', {}), ('materials', 'mine', {}), ('development', 'repair', {}), ('knowledge', 'research', {}),
    ('treasury', 'spaceport', {}), ('reputation', 'delivery', {}),
])
def test_every_listed_first_way_really_raises_its_stat(stat, action, extra):
    """The topic table must match the game: the first way listed for each stat raises it by the amount shown."""
    seed()
    first = knowledge.WORK[stat][0]
    assert first[3] == action
    with m.SessionLocal() as db:
        before = getattr(m.society(db, 'test'), stat)
    reply = m.action(action, 'test', 'u', 'Kamex', provider='twitch').body.decode()
    with m.SessionLocal() as db:
        after = getattr(m.society(db, 'test'), stat)
    assert after - before >= int(first[1].split(',')[0].split()[0].lstrip('+')), reply      # farming adds more with shared Water


def test_each_society_stat_has_an_answer_on_discord_and_twitch():
    citizen()
    for stat, (emoji, label) in knowledge.SOCIETY.items():
        query = f'how do I raise {label}' if stat not in {'food', 'materials'} else f'how do I raise colony {label}'
        card = answer(query)
        assert card.intent == 'topic' and f'HOW TO RAISE {label.upper()}' in card.text, stat
        chat = answer(query, 'twitch')
        assert chat.text.startswith(emoji) and len(chat.text.encode()) <= 380 and '\n' not in chat.text, stat


def test_food_and_materials_items_are_not_mistaken_for_the_colony_stats():
    citizen()
    assert answer('how do I get food').intent != 'topic'
    assert answer('how do I raise the colony food').intent == 'topic'


def test_contribution_lists_its_sources():
    citizen()
    result = answer('how do I get contribution?')
    assert 'HOW TO EARN CONTRIBUTION' in result.text
    for way in ('successful work task', 'event', 'Society Project', 'Society Directive', 'Production Orders', 'Mentoring'):
        assert way in result.text, way
    chat = answer('how to earn contribution', 'twitch')
    assert 'leaderboard' in chat.text and len(chat.text.encode()) <= 380


def test_needs_say_what_they_do_and_how_to_raise_them():
    citizen()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.life_state(db, p).energy = 15
        db.commit()
    result = answer('how do I get more energy')
    assert 'HOW TO RAISE ENERGY' in result.text and '15/100' in result.text and '/relax' in result.text
    assert 'Inspired' in answer('what does morale mean', uid=None).text
    assert 'HOW TO RAISE COMFORT' in answer('my comfort is low').text


def test_tiers_name_the_stat_holding_the_colony_back_with_a_button_to_raise_it():
    citizen()
    with m.SessionLocal() as db:
        s = m.society(db, W)
        for stat in knowledge.SOCIETY:
            setattr(s, stat, 400)
        s.knowledge = 120
        db.commit()
    data = asked('how do I get the next tier?')
    assert 'lowest: **knowledge 120**' in text_of(data)
    again = press(next(c for c in controls(data) if c.get('label') == 'Knowledge')['custom_id'])['data']
    assert 'how to raise knowledge' in text_of(again)


def test_housing_and_the_clinic():
    citizen()
    assert 'Maintenance & Repair' in answer('how do I add housing').text
    assert 'Pharmacy' in answer('how do I stock the clinic').text


def test_an_item_with_a_topic_word_in_its_name_is_still_the_item():
    citizen()
    pack = next((e for e in ask.wb.index(m) if e.name == 'Comfort Pack'), None)
    if pack is not None:
        assert answer('how do I make a comfort pack').intent == 'make'


# ---------------------------------------------------------------- everything else the game explains

@pytest.mark.parametrize('query, expected', [
    ('how do I change my job', '/job'),
    ('what is a season', '/season'),
    ('how do I make friends', '/social'),
    ('how do I start a business', '/business'),
    ('how do I upgrade my home', '/home'),
    ('how do cooldowns work', 'cooldown'),
    ('how does the weekly recap work', 'weekly recap'),
    ('how do votes work', '/vote'),
    ('what do ducks do', '/ducks'),
])
def test_questions_are_answered_from_the_handbook_commands_and_menu(query, expected):
    citizen()
    result = answer(query)
    assert result.answered and expected.casefold() in result.text.casefold(), result.text
    chat = answer(query, 'twitch')
    assert chat.answered and len(chat.text.encode()) <= 380, chat.text


def test_handbook_answers_have_buttons_to_their_pages_and_fit_discord():
    citizen()
    for query in ('how do I change my job', 'how to build reputation', 'how do I get contribution', 'what is a season',
                  'how do I get more energy', 'how do I get the next tier'):
        data = asked(query)
        assert assert_valid(v2.convert(data)), query
    assert 'Character' in labels(asked('how do I change my job'))          # 📖 the handbook page it came from
    assert 'Society guide' in labels(asked('how to build reputation'))


def test_nonsense_is_still_unanswered_and_counted():
    citizen()
    assert not answer('how do I tame a dragon').answered
    assert not answer('qwzx plorb').answered


def test_search_needs_the_question_s_own_words():
    """A passage that only shares a common verb is not an answer."""
    hits = knowledge.search(m, 'how do I change my job')
    assert hits and all('job' in (h.head + h.body).casefold() for _, h in hits)
