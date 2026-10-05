"""Find answers questions: how do I make…, where do I get…, what is … used for, how do I level…, what does … mean,
why can't I…, what should I do next. Plain words are still a search, and what it cannot answer is counted for the owner."""
import json
import pytest
from test_colony import m, reset, seed
from test_workbench_ui import citizen, press, controls, W, LUMBER, CAMPFIRE
from test_buttons_everywhere import submit, moderator_press
from test_layout_v2 import assert_valid
from app import ask, ui, extras, seed_content as s, workbench as wb, layout_v2 as v2


def labels(data):
    return [c.get('label') or c.get('placeholder', '') for c in controls(data)]


def button(data, prefix):
    return next(c for c in controls(data) if (c.get('label') or '').startswith(prefix))


def text_of(data):
    """The card's text, case-folded: Discord shows a card's first line as a Title Case heading."""
    return json.dumps(data, ensure_ascii=False).casefold()


def answer(query, uid='111', provider='discord'):
    with m.SessionLocal() as db:
        p = ask.existing_player(m, db, W, 'discord', uid) if uid else None
        result = ask.answer(m, db, p, query, provider)
        db.commit()
        return result


def asked(query, uid='111'):
    """The Find box in /menu, as a player types it."""
    return submit(ui.cid(uid, 'md', 'find'), query, uid=uid)['data']


# ---------------------------------------------------------------- reading the question

@pytest.mark.parametrize('query, intent, subject', [
    ('How do I make Iron Nails?', 'make', 'iron nails'),
    ('how 2 craft a campfire', 'make', 'campfire'),
    ('recipe for wood planks', 'make', 'wood planks'),
    ('Where do I get coal??', 'get', 'coal'),
    ('i need salt', 'get', 'salt'),
    ("what's clay used for", 'uses', 'clay'),
    ('what can I make with lumber', 'uses', 'lumber'),
    ('how do i level up chemistry', 'level', 'chemistry'),
    ('how do I get chemistry xp', 'level', 'chemistry'),
    ('what does morale mean', 'define', 'morale'),
    ("why can't I craft the campfire", 'why', 'campfire'),
    ('why is iron plate locked', 'why', 'iron plate'),
    ('why cant i work', 'needs', ''),
    ('what should I do next?', 'next', ''),
    ("I'm stuck", 'next', ''),
])
def test_question_shapes_are_recognised(query, intent, subject):
    assert ask.parse(query)[0] == (intent, subject)


def test_a_plain_word_is_not_a_question():
    assert ask.parse('campfire') == [] and ask.parse('iron nails') == []


def test_subjects_survive_typos_plurals_and_old_names():
    nails = s.key('Iron Nails')
    assert ask.find_item('nail')[0] == nails
    assert ask.find_item('components')[0] == nails              # an old New Eridian name
    assert ask.find_recipe(m, 'campfir')[0].name == 'Campfire'
    assert ask.find_skill(m, 'chemestry')[0][2] == 'Chemistry'
    assert ask.find_skill(m, 'processing')[0][1] is None         # a main skill, not a specialty
    assert 'Seed Coin' in ask.find_term(m, 'sc')[0][0]


# ---------------------------------------------------------------- answers, with the player's own bag and levels

def test_how_do_i_make_shows_the_recipe_what_is_missing_and_a_goal_button():
    citizen(lumber=0)
    data = asked('how do I make a campfire?')
    text = text_of(data)
    assert 'how to make campfire' in text and 'lumber 0/2' in text and 'missing' in text and '2 lumber' in text
    assert 'Set as goal' in labels(data) and 'Campfire' in labels(data) and 'Ask another' in labels(data)
    goal = press(button(data, 'Set as goal')['custom_id'])['data']
    assert 'campfire' in text_of(goal)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert extras.goal_entry(m, db, p).name == 'Campfire'
    assert 'Set as goal' not in labels(asked('how do I make a campfire'))    # already the goal


def test_a_ready_recipe_says_so():
    citizen(lumber=10)
    result = answer('how do I make campfire')
    assert 'Ready to craft' in result.text
    result = answer("why can't I craft a campfire")
    assert 'NOTHING IS STOPPING YOU' in result.text


def test_a_gathered_item_is_answered_with_how_to_gather_it_even_when_asked_how_to_make_it():
    citizen(lumber=0)
    data = asked('how do I make lumber')
    assert 'where to get lumber' in text_of(data) and 'best way' in text_of(data)
    pressed = press(button(data, 'Gather ×1')['custom_id'])
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.material_amount(db, p, LUMBER) > 0
    assert pressed


def test_where_do_i_get_names_lucky_finds_and_the_best_route():
    result = answer('where do i get clay')
    assert 'WHERE TO GET CLAY' in result.text and 'Lucky finds' in result.text and 'Stone Quarrying' in result.text


def test_what_is_it_used_for_lists_recipes_ready_ones_first():
    citizen(lumber=10)
    result = answer('what is lumber used for')
    assert 'WHAT IS LUMBER FOR' in result.text and '✅ **Campfire**' in result.text
    assert result.text.index('✅') < result.text.index('❌') if '❌' in result.text else True
    assert any(a['kind'] == 'recipe' for a in result.actions)


def test_how_do_i_level_a_skill_offers_start_for_a_ready_task_and_the_training_screen():
    citizen()
    data = asked('how do I level wood harvesting')
    text = text_of(data)
    assert 'how to level wood harvesting' in text and 'harvesting specialty' in text
    assert 'Start Wood Harvesting' in labels(data) and 'Train Harvesting' in labels(data)
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        before = p.actions
    press(button(data, 'Start Wood Harvesting')['custom_id'])
    with m.SessionLocal() as db:
        assert m.player(db, W, 'discord', '111', 'Kam')[1].actions == before + 1
    assert 'train harvesting' in text_of(press(button(data, 'Train Harvesting')['custom_id'])['data'])


def test_a_locked_skill_says_what_it_still_needs():
    citizen()
    result = answer('how do I level chemistry')
    assert 'Processing Lv3' in result.text and 'Medical Fabricator' in result.text
    assert not any(a['kind'] == 'start' for a in result.actions)


def test_how_do_i_level_up_lists_every_skill():
    citizen()
    result = answer('how do i level up')
    assert 'HOW DO I LEVEL UP' in result.text and 'Medicine' in result.text and 'Farming' in result.text


def test_what_does_it_mean_answers_from_the_handbook_and_the_game_rules():
    assert 'Inspired' in answer('what does morale mean', uid=None).text
    assert "+3 percentage points" in answer("what is rocky's favor", uid=None).text
    assert 'Personal currency' in answer('what is SC', uid=None).text
    item = answer('what is a campfire', uid=None)
    assert 'CAMPFIRE' in item.text and 'Get it' in item.text


def test_why_cant_i_lists_every_reason_not_only_the_first():
    citizen(lumber=0)
    result = answer('why is iron plate locked')
    assert "WHY CAN'T I MAKE IRON PLATE" in result.text
    assert 'craft a' in result.text and 'Missing:' in result.text           # the workstation's machine and the ingredients
    assert '/workshop' not in result.text                                     # crafting the machine, not paying to unlock


def test_why_cant_i_work_points_at_the_low_need():
    citizen()
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        m.life_state(db, p).energy = 5
        db.commit()
    result = answer('why cant i work')
    assert "WHY CAN'T I WORK" in result.text and 'Energy 5/100' in result.text
    citizen()
    assert 'NEEDS ARE FINE' in answer('why cant i work').text


def test_what_should_i_do_next_follows_the_goal_first():
    citizen(lumber=0)
    assert 'Right now' in answer('what should I do next').text
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        extras.start_goal(m, db, p, CAMPFIRE.id)
        db.commit()
    result = answer('what now')
    assert 'Your goal, Campfire' in result.text and any(a['kind'] == 'goalview' for a in result.actions)


# ---------------------------------------------------------------- plain search, suggestions and the owner's log

def test_a_plain_word_is_still_the_search_with_its_buttons():
    citizen()
    data = asked('campfire')
    assert 'results for' in text_of(data) and 'Campfire' in labels(data)
    defined = answer('morale', uid=None).text
    assert 'MORALE' in defined


def test_questions_about_buttons_fall_back_to_the_search():
    assert 'Shopping list' in answer('how do I use the shopping list').text


def test_a_question_it_cannot_answer_suggests_close_names_and_is_counted_without_the_asker(monkeypatch):
    citizen()
    assert 'how to make campfire pie' in text_of(asked('how do I make campfyre pie please'))   # a typo still finds it
    data = asked('how do I tame a dragon?')
    assert "couldn't answer" in text_of(data) and 'questions find understands' in text_of(data)
    asked('How do I tame a dragon')
    asked('how do i make iron nails')                     # answered: never counted
    with m.SessionLocal() as db:
        rows = db.query(ask.FindQuestion).all()
        assert [(r.question, r.times) for r in rows] == [('how do i tame a dragon', 2)]
        assert not any('111' in (r.question + r.channel_id) for r in rows)
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {'111'})
    log = text_of(moderator_press(ui.cid('111', 'mv', 'm_asklog'))['data'])
    assert 'unanswered find questions' in log and '2× “how do i tame a dragon”' in log
    citizen('222')
    assert 'only the game owner' in text_of(moderator_press(ui.cid('222', 'mv', 'm_asklog'), uid='222')['data'])
    assert 'how do i tame a dragon' in m._discord_call_internal('asklog', '111', 'Kam', {}, 'i9')


def test_the_log_keeps_the_newest_questions_only(monkeypatch):
    monkeypatch.setattr(ask, 'LOG_KEEP', 3)
    with m.SessionLocal() as db:
        for i in range(5):
            ask.log(m, db, W, f'mystery question {i}')
            db.commit()
        assert sorted(r.question for r in db.query(ask.FindQuestion).all()) == ['mystery question 2', 'mystery question 3',
                                                                                 'mystery question 4']


# ---------------------------------------------------------------- the same answers on Discord and Twitch

def test_discord_slash_command_and_twitch_chat_answer_questions():
    citizen(lumber=0)
    text = m._discord_call_internal('find', '111', 'Kam', {'query': 'how do I make a campfire'}, 'i1')
    assert 'HOW TO MAKE CAMPFIRE' in text and 'Missing: 2 Lumber' in text
    seed()                                                     # a Twitch citizen in the test channel
    chat = m.find_anything('how do I make campfire', 'twitch', 'test', 'u', 'Kamex').body.decode()
    assert chat.startswith('🛠️ Campfire') and '!target Campfire' in chat and '\n' not in chat
    assert 'Campfire' in m.find_anything('campfire', 'twitch').body.decode()            # plain words, as before
    assert '!find' in m.find_anything('', 'twitch').body.decode()
    assert 'Morale' in m.find_anything('what does morale mean', 'twitch').body.decode()
    with m.SessionLocal() as db:                                                          # asking never creates a citizen
        assert ask.existing_player(m, db, 'test', 'twitch', 'nobody') is None
    m.find_anything('where do i get coal', 'twitch', 'test', 'nobody', 'Nobody')
    with m.SessionLocal() as db:
        assert ask.existing_player(m, db, 'test', 'twitch', 'nobody') is None


def test_every_answer_fits_discord_buttons_and_chat():
    citizen()
    for query in ('how do I make iron nails', 'where do I get coal', 'what is clay used for', 'how do I level medicine',
                  'what does comfort mean', "why can't I make iron plate", 'what should I do next', 'how do I level up',
                  'how do I tame a dragon', 'campfire', 'where do I get iron', 'how do I make money'):
        data = asked(query)
        assert data['components'] and assert_valid(v2.convert(data)), query        # Discord's newer layout accepts it
        chat = m.find_anything(query, 'twitch', W, '111', 'Kam').body.decode()
        assert len(chat.encode()) <= 400, (query, chat)


def test_when_several_things_fit_it_asks_which_one_with_a_button_each():
    citizen()
    data = asked('where do I get iron')
    assert 'which one did you mean' in text_of(data)
    choice = button(data, 'Iron Ingot')
    again = press(choice['custom_id'])['data']
    assert 'where to get iron ingot' in text_of(again)
    with m.SessionLocal() as db:                         # a helpful "which one?" is not an unanswered question
        assert db.query(ask.FindQuestion).count() == 0


def test_how_do_i_make_money_explains_seed_coin_and_opens_its_guide():
    citizen()
    data = asked('how do I make money?')
    assert 'how do i earn seed coin' in text_of(data) and 'Earn SC guide' in labels(data)
    assert 'seed coin' in m.find_anything('how do i get sc', 'twitch', W, '111', 'Kam').body.decode().casefold()


def test_on_the_lite_twitch_game_crafting_answers_point_to_discord(monkeypatch):
    seed()
    monkeypatch.setattr(m.twitch_lite, 'ENABLED', True)
    chat = m.find_anything('how do I make campfire', 'twitch', 'test', 'u', 'Kamex').body.decode()
    assert 'on Discord' in chat and '!make' not in chat and '!target' not in chat
    assert 'on Discord' in m.find_anything('where do I get iron ingot', 'twitch', 'test', 'u', 'Kamex').body.decode()
    assert '!training' in m.find_anything('how do I level wood harvesting', 'twitch', 'test', 'u', 'Kamex').body.decode()
