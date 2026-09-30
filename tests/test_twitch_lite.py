"""Twitch plays a lite version; the full game (crafting, queues, trading, homes, settings) is on Discord."""
import pytest
from test_colony import m, reset, client
from app import twitch_lite as lite, onboarding

C = 'twitch-channel'


@pytest.fixture(autouse=True)
def on(reset, monkeypatch):
    monkeypatch.setattr(lite, 'ENABLED', True)
    monkeypatch.setenv('DISCORD_INVITE_URL', 'https://discord.gg/neweridian')


def twitch(path, **params):
    return client.get(path, params={'channel': C, 'uid': 'u1', 'name': 'Nova', **params}).text


@pytest.mark.parametrize('path,params,feature', [
    ('/api/v1/make', {'recipe': 'campfire'}, 'Crafting'), ('/api/v1/craftmax', {'recipe': 'lumber'}, 'Crafting queues'),
    ('/api/v1/queue', {'action': 'start', 'task': 'gather:x'}, 'Queues'), ('/api/v1/sellall', {'item': 'lumber'}, 'Selling'),
    ('/api/v1/seedindustries', {}, 'Trading'), ('/api/v1/home', {}, 'Homes'), ('/api/v1/business', {}, 'Businesses'),
    ('/api/v1/settings', {}, 'Settings'), ('/api/v1/schedule', {'preset': 'workaholic'}, 'Seedling schedules'),
    ('/api/v1/hat', {'hat': 'crown'}, 'Hats'), ('/api/v1/seed-supplies', {'mode': 'catalog', 'item': 'lumber'}, 'The full catalog'),
    ('/api/v1/mining', {'ore': 'hematite', 'action': 'mine', 'count': '5'}, 'Mining queues')])
def test_the_full_game_features_point_twitch_players_to_discord(path, params, feature):
    text = twitch(path, **params)
    assert text.startswith(f'🔒 {feature} is part of the full game on Discord') and 'discord.gg/neweridian' in text
    assert len(text.encode()) <= 200
    with m.SessionLocal() as db:
        assert db.query(m.Player).count() == 0                  # nothing ran


def test_the_lite_game_still_plays_on_twitch():
    assert 'Welcome to New Eridian' in twitch('/api/v1/start')
    for path, params in [('/api/v1/status', {}), ('/api/v1/seed-supplies', {'mode': 'gather', 'item': 'lumber'}),
                         ('/api/v1/mining', {'ore': 'hematite', 'action': 'mine', 'count': '1'}), ('/api/v1/action/relax', {}),
                         ('/api/v1/profile', {}), ('/api/v1/seedling', {}), ('/api/v1/vote', {}), ('/api/v1/society', {}),
                         ('/api/v1/job', {})]:
        assert not twitch(path, **params).startswith('🔒'), path


def test_discord_keeps_everything():
    text = client.get('/api/v1/make', params={'channel': C, 'uid': 'd1', 'name': 'Dee', 'provider': 'discord'}).text
    assert not text.startswith('🔒')
    assert not m._discord_call_internal('make', '111', 'Dee', {}, 'i1').startswith('🔒')


def test_first_steps_and_the_handbook_send_crafting_to_discord():
    welcome = twitch('/api/v1/start')
    assert 'Crafting is on Discord' in welcome and len(welcome.encode()) <= 200 + 50
    assert onboarding._cmd('craft', 'twitch').startswith('on Discord: /make')
    assert onboarding._cmd('gather', 'twitch') == '!gather lumber'
    assert onboarding._cmd('craft', 'discord') == '/make recipe:Campfire'
    help_text = client.get('/api/v1/seed', params={'topic': 'property'}).text
    assert 'full game on Discord' in help_text


def test_the_switch_gives_twitch_the_full_game_again(monkeypatch):
    monkeypatch.setattr(lite, 'ENABLED', False)
    assert not twitch('/api/v1/make').startswith('🔒')
    assert onboarding._cmd('craft', 'twitch') == '!make campfire'


def test_with_a_key_set_only_requests_carrying_it_can_act_as_a_player(monkeypatch):
    monkeypatch.setenv('TWITCH_API_KEY', 'secret-123')
    missing = twitch('/api/v1/start')
    assert 'missing the game key' in missing
    with m.SessionLocal() as db:
        assert db.query(m.Player).count() == 0
    assert 'Welcome to New Eridian' in twitch('/api/v1/start', k='secret-123')
    assert 'missing the game key' in twitch('/api/v1/start', k='wrong')
    # Pretending to be Discord (to get around the lite version or act as someone) needs the key too.
    assert 'missing the game key' in client.get('/api/v1/make', params={'channel': C, 'uid': '111', 'provider': 'discord'}).text
    assert 'missing the game key' in client.get('/api/v1/link/claim', params={'channel': C, 'discord_uid': '111', 'code': 'ABC'}).text
    # Reads without a player stay open: overlays, the society, the recap.
    assert client.get('/api/v1/overlay', params={'channel': C}).status_code == 200
    assert 'missing' not in client.get('/api/v1/society', params={'channel': C}).text
    # Discord plays through the bot, which never uses these addresses.
    assert not m._discord_call_internal('status', '111', 'Dee', {}, 'i1').startswith('⛔')


def test_the_command_list_is_complete_and_every_player_command_carries_the_key():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'integrations/twitch/ALL_COMMANDS.txt').read_text(encoding='utf-8')
    adds = re.findall(r'^!command add (!\S+) (.*)$', text, re.M)
    names = [n for n, _ in adds]
    assert len(names) == len(set(names))
    for must in ('!start', '!gather', '!mine', '!farm', '!eat', '!relax', '!status', '!seedling', '!vote', '!challenge', '!live', '!chstart'):
        assert must in names
    for name, response in adds:
        if 'uid=' in response:
            assert '&k=YOUR_API_KEY' in response, name
        if '/admin/' in response:
            assert 'key=YOUR_ADMIN_KEY' in response and names.index(name) > names.index('!customize'), name   # moderator commands last
