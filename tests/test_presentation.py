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
