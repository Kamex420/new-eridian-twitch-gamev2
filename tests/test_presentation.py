"""Message shapes: small task receipts, one-line notices, full information cards."""
import json
from test_colony import m, reset, seed
from app import presentation as pr


def embed(text, command=''):
    return m._discord_json_message(text, message_type=command)['data']


def test_task_receipt_is_small_and_readable():
    seed(provider='discord')
    content = m.action('harvest', 'test', 'u', provider='discord').body.decode()
    data = embed(content, 'farm')
    card = data['embeds'][0]
    assert card['title'].startswith(('✅', '❌'))
    assert 'footer' not in card and 'fields' not in card and 'components' not in data
    assert len(card['description'].splitlines()) <= 7
    assert '−3 Energy' in card['description'] and 'Kam' not in card['description'].split('📈')[-1]


def test_notice_is_one_clean_line():
    card = embed('⏱️ Kamex, Harvest Pumpkins is ready in 5s.')['embeds'][0]
    assert card == {'description': '⏱️ Kamex, Harvest Pumpkins is ready in 5s.', 'color': pr.COLORS['cooldown']}


def test_information_card_has_title_sections_and_bold_labels():
    text = '🎒 KAM — INVENTORY\nSeed Coin: 50 SC\n\n📦 KEY RESOURCES\n• Pumpkin: 3\n• Lumber: 2\n\nTASK READINESS\n✅ READY FOR WORK\nAll needs are fine.'
    card = embed(text, 'inventory')['embeds'][0]
    assert card['title'] == '🎒 Kam — Inventory'
    assert card['description'] == '**Seed Coin:** 50 SC'
    names = [f['name'] for f in card['fields']]
    assert names == ['📦 Key Resources', 'Task Readiness']
    assert card['fields'][1]['value'].startswith('**✅ Ready for Work**')
    assert card['footer']['text'] == m.message_layout.FOOTER


def test_long_first_lines_become_a_short_title():
    card = embed('⛔ TASK BLOCKED — Kam, your task did not start because Energy is too low for any more work today.\nWHY\nEnergy 5/100.')['embeds'][0]
    assert card['title'] == '⛔ Task Blocked' and card['description'].startswith('Kam, your task')


def test_level_up_never_replaces_the_title():
    title, intro, _ = pr.sections('LEVEL UP: Kam — Commerce Lv. 1 → Lv. 2\n🏭 WORLD\nA line')
    assert title == '🏭 WORLD' and intro[-1].startswith('🎉')


def test_change_lines_are_formatted():
    assert pr.needs_line('comfort -2, energy -3, nutrition -1') == '⚡ −3 Energy · 🍲 −1 Nutrition · 🛋️ −2 Comfort'
    assert pr.resources_line('SC +2, Pumpkin +3, Lumber -2') == '**+3** Pumpkin · **+2** 🪙 SC · −2 Lumber'
    pr.SKILL_NAMES = ('Farming', 'Emergency Response')
    assert pr.practice_line('Kam Doe Emergency Response +1.00 (1 XP banked)') == '📈 Emergency Response +1 XP'


def test_twitch_task_reply_is_one_short_line():
    seed()
    line = m.action('harvest', 'test', 'u').body.decode()
    assert '\n' not in line and len(line.encode()) <= 200 and line.startswith(('✅', '❌'))
    assert 'Final chance' not in line and 'Society condition' not in line
    folded = pr.chat_fold('✅ GATHERING COMPLETE\n\nOUTPUT\n• Lumber ×1\n\nNeeds: unchanged')
    assert folded == '✅ GATHERING COMPLETE | Output: Lumber ×1'


def test_very_long_information_moves_to_details_pages():
    data = embed('📜 JOURNAL\n' + '\n'.join(f'Entry {i}: something happened' for i in range(90)))
    card = data['embeds'][0]
    assert len(card.get('description', '')) <= pr.OVERVIEW_CHARS and data['components']


# ---------------------------------------------------------------- titles for performed tasks

def test_a_training_task_gets_a_title_from_its_own_text():
    miss = '❌ TASK FAILED\n\nWHY\nOre Mining did not succeed. All task materials were kept.\n\nNeeds: energy -3'
    assert pr._receipt_title(miss, 'training', True) == '❌ Ore Mining failed'
    assert pr._receipt_title('✅ TASK COMPLETE\nKam completes Ore Mining.\n', 'training', False) == '✅ Ore Mining'
    # no name in the text: a plain label, never none
    assert pr._receipt_title('❌ TASK FAILED\n\nWHY\nNothing came of it.', 'training', True) == '❌ Task failed'
    assert pr._receipt_title('✅ TASK COMPLETE\nDone.', 'training', False) == '✅ Task complete'
    # a long sentence is not taken for a name
    assert pr._receipt_title('❌ TASK FAILED\n' + 'x' * 80 + ' did not succeed.', 'make', True) == '❌ Task failed'


def test_the_titled_receipt_drops_the_raw_task_line():
    card = pr.receipt('❌ TASK FAILED\n\nWHY\nOre Mining did not succeed. All task materials were kept.\n\nNeeds: energy -3', 'training', 'failure')
    assert card['title'] == '❌ Ore Mining failed' and 'TASK FAILED' not in card['description']
    assert card['description'].startswith('> Ore Mining did not succeed.')
    card = pr.receipt('✅ TASK COMPLETE\nThe lab hummed along.\n\nNeeds: energy -3', 'training', 'success')
    assert card['title'] == '✅ Task complete' and 'TASK COMPLETE' not in card['description']


def test_the_titles_that_already_existed_are_unchanged():
    assert pr._receipt_title('✅ TASK COMPLETE\nKam completes Harvest Pumpkins.', 'farm', False) == '✅ Harvest Pumpkins'
    assert pr._receipt_title('❌ TASK FAILED\nKam completes Harvest Pumpkins.', 'farm', True) == '❌ Harvest Pumpkins failed'
    assert pr._receipt_title('✅ TASK COMPLETE\nRested.', 'relax', False) == '✅ Relaxed'
    assert pr._receipt_title('❌ TASK FAILED\nRested.', 'relax', True) == '❌ Relaxed failed'
    assert pr._receipt_title('✅ GATHERING COMPLETE\n\nOUTPUT\n• Lumber ×1', 'gather', False) == '✅ Gathered Lumber'
    assert pr._receipt_title('⛏️ MINING FAILED\nThe vein was empty.', 'mine', True) == '❌ Mining failed'
    assert pr._receipt_title('✅ CRAFTING COMPLETE\n\nOUTPUT\n• Campfire ×1', 'make', False) == '✅ Crafted Campfire'
    # a command with a label of its own wins over the generic fallback
    assert pr._receipt_title('✅ TASK COMPLETE\nDid it.', 'relax', False) == '✅ Relaxed'
    # a trade or unlock is still a plain sentence
    assert pr._receipt_title('Bought 2 Lumber for 4 SC.', 'buyitem', False) == ''


def test_social_actions_are_titled_by_their_action():
    assert pr.action_command('social', {'action': 'hi'}) == 'hi'
    assert pr.action_command('social', {'action': 'hangout'}) == 'hangout'
    assert pr.action_command('social', {'action': 'group_games'}) == 'use'
    assert pr.action_command('social', {'action': 'duo_walk'}) == 'duo'
    assert pr.action_command('social', None) == 'social' and pr.action_command('social', {}) == 'social'
    assert pr.action_command('work', {'action': 'hi'}) == 'work' and pr.action_command('relax', None) == 'relax'


def test_twitch_chat_output_is_unchanged_by_the_fallback():
    # Twitch text never carries the Discord "TASK COMPLETE/FAILED" line, so the fallback never reaches it; these lines are
    # exactly what the chat produced before the fallback existed.
    assert pr.chat('✅ Kam completes Harvest Pumpkins. | Output: Pumpkin ×3 | Needs: energy -3', 'farm') == \
        '✅ Kam completes Harvest Pumpkins. | Output: Pumpkin ×3 | ⚡ −3 Energy'
    assert pr.chat('❌ Ore Mining did not succeed. All task materials were kept.', 'training') == \
        '❌ Ore Mining did not succeed. All task materials were kept.'
    assert pr.chat('✅ Kam completes Ore Mining. | Output: Hematite Ore ×2', 'training') == \
        '✅ Kam completes Ore Mining. | Output: Hematite Ore ×2'
