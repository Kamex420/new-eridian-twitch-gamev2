"""Compact views preserve details and never dispatch gameplay on navigation."""
import json
from test_colony import m, reset
from app import message_layout as layout


def test_long_response_keeps_every_line_in_details():
    text = 'INVENTORY\n' + '\n'.join(f'Unique resource {i}: {i+1}' for i in range(150))
    data = m._discord_json_message(text, ephemeral=True, message_type='inventory')['data']
    assert data['flags'] == 64
    card = data['embeds'][0]
    assert sum(len(f['value']) for f in card['fields']) <= 850
    custom = data['components'][0]['components'][0]['custom_id']
    token = custom.split(':')[1]
    with m.SessionLocal() as db:
        pages = json.loads(db.get(layout.MessagePages, token).pages)
    all_details = '\n'.join(p['description'] for p in pages[1:])
    assert all_details == m.discord_command_copy(text)
    assert all(len(p['description']) <= 850 for p in pages[1:])


def test_buttons_are_read_only_and_private(monkeypatch):
    data = m._discord_json_message('RESULT\n' + 'Some details\n'*80)['data']
    custom = data['components'][0]['components'][0]['custom_id']
    def forbidden(*args):
        raise AssertionError('Navigation must never execute game commands')
    monkeypatch.setattr(m, '_discord_call_internal', forbidden)
    response = layout.open_page(m, {'data': {'custom_id': custom}})
    assert response['type'] == 4 and response['data']['flags'] == 64
    response = layout.open_page(m, {'data': {'custom_id': custom}, 'message': {'flags':64}})
    assert response['type'] == 7 and 'flags' not in response['data']
    assert 'Details' in response['data']['embeds'][0]['title']


def test_expired_and_invalid_buttons():
    for custom in ['invalid', 'page:'+'a'*32+':99999']:
        result = layout.open_page(m, {'data': {'custom_id': custom}})
        assert result['data']['flags'] == 64 and 'expired' in result['data']['content']


def test_queue_overview_retains_results_and_forecast():
    text = '''TASK QUEUE — RUNNING
Mine Aurite Ore
Attempts completed: 9/10; remaining: 1.
Succeeded: 3; failed: 1. Prospecting steps without ore: 5.

TOTAL ITEMS GAINED
Stone Dust ×1, Aurite Ore ×3

TOTAL ITEMS USED
None
For 1 remaining attempt: up to 3 Energy, 1 Nutrition and 1 Comfort.
To finish without recovery, start with at least 20 Energy, 20 Nutrition and 20 Social.
Current needs: Energy 88/100; Nutrition 95/100; Social 100/100; Comfort 96/100.
'''
    result = m._discord_json_message(text, message_type='queue')['data']
    card = result['embeds'][0]
    rendered = json.dumps(card, ensure_ascii=False)
    for value in ('9/10', 'failed: 1', 'Stone Dust ×1', 'Aurite Ore ×3', 'Energy 88/20'):
        assert value in rendered
    assert 'TOTAL ITEMS USED' not in rendered
    assert card['footer']['text']=="New Eridian v2 • May Rocky's wisdom guide you."
    assert card['title'] == 'Queue · Running'


def test_short_reply_needs_no_pages():
    data = m._discord_json_message('Choose an ore first.', ephemeral=True)['data']
    assert 'components' not in data and data['flags'] == 64


def test_expiry_is_checked_even_before_cleanup():
    from datetime import timedelta
    data = m._discord_json_message('DETAILS\n'+'line\n'*80)['data']
    custom = data['components'][0]['components'][0]['custom_id']
    with m.SessionLocal() as db:
        row = db.get(layout.MessagePages, custom.split(':')[1])
        row.expires_at = m.now() - timedelta(seconds=1)
        db.commit()
    assert 'expired' in layout.open_page(m, {'data':{'custom_id':custom}})['data']['content']


def test_signed_button_routes_without_running_gameplay(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from nacl.signing import SigningKey
    from starlette.background import BackgroundTasks
    key = SigningKey.generate()
    monkeypatch.setattr(m, 'DISCORD_PUBLIC_KEY', key.verify_key.encode().hex())
    monkeypatch.setattr(m, 'DISCORD_GAME_CHANNEL_ID', '')
    data = m._discord_json_message('DETAILS\n'+'line\n'*80)['data']
    custom = data['components'][0]['components'][0]['custom_id']
    payload = {'type':3, 'data':{'custom_id':custom}, 'message':{'flags':64}}
    body = json.dumps(payload).encode()
    async def get_body(): return body
    async def get_json(): return payload
    request = SimpleNamespace(headers={'X-Signature-Ed25519':key.sign(b'123'+body).signature.hex(), 'X-Signature-Timestamp':'123'}, body=get_body, json=get_json)
    def forbidden(*args): raise AssertionError('Button dispatched gameplay')
    monkeypatch.setattr(m, '_discord_call_internal', forbidden)
    result = asyncio.run(m.discord_interactions(request, BackgroundTasks()))
    assert result['type'] == 7
