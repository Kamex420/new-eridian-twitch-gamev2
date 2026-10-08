"""Seedling looks and personality: chosen on Discord, drawn on the stream map, heard in speech bubbles."""
import random
from test_colony import m, reset, client
from app import looks, menu, ui

W = m.DISCORD_WORLD_ID


def customize(uid='111', name='Kamex', **options):
    return m._discord_call_internal('customize', uid, name, options, 'i-' + '-'.join(options))


def test_choosing_a_look_and_a_personality():
    text = customize()
    assert 'LOOKS & PERSONALITY' in text and 'original random look' in text
    text = customize(skin='deep', hair='curly', hair_colour='pink', outfit='teal', accessory='glasses', attitude='grumpy', catchphrase='snacks')
    assert 'Updated:' in text and 'Skin tone → Deep' in text and 'Attitude → Grumpy' in text
    assert 'Catchphrase: **Snacks first.**' in text and '💬 Grumpy: complains, but always shows up. It sounds like:' in text
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kamex')[1]
        found = looks.row(db, p)
        assert (found.skin, found.hair, found.hair_colour, found.outfit, found.accessory) == ('deep', 'curly', 'pink', 'teal', 'glasses')
    assert 'back to its original look' in customize(skin='random')
    assert 'Choose a valid hair' in customize(hair='rainbow wig')              # Discord only offers the listed choices
    direct = client.get('/api/v1/looks', params={'channel': W, 'uid': '111', 'name': 'Kamex', 'provider': 'discord', 'hair': 'rainbow wig'}).text
    assert 'not an option' in direct


def test_the_stream_map_gets_the_look_and_the_voice():
    customize(skin='moss', hair='mohawk', hair_colour='teal', outfit='mood', accessory='backpack', attitude='dramatic', catchphrase='hello')
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kamex')[1]
        m.autonomy.row(db, p.channel_id, p.twitch_uid, create=True).thought = 'The fields look good today.'
        db.commit()
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    s = next(x for x in data['seedlings'] if x['name'] == 'Kamex')
    assert s['look'] == {'skin': looks.SKIN['moss'][1], 'hair': 'mohawk', 'hair_colour': looks.HAIR_COLOUR['teal'][1], 'accessory': 'backpack'}
    assert 'outfit' not in s['look']                            # "mood" keeps the mood colour
    assert 'Hello, chat!' in s['lines']
    starts, ends = looks.ATTITUDE['dramatic'][2], looks.ATTITUDE['dramatic'][3]
    assert any(line.startswith(tuple(x for x in starts if x)) or line.endswith(tuple(x for x in ends if x)) for line in s['lines'])


def test_voice_keeps_the_words_and_never_gets_too_long():
    r = random.Random(3)
    for attitude in looks.ATTITUDE:
        line = looks.voice('Kamex, want to share a meal?', attitude, '', r)
        assert 'Kamex, want to share a meal' in line and len(line) <= 150
    long = 'x' * 149
    assert looks.voice(long, 'dramatic', '', random.Random(1)) == long


def test_every_option_is_a_menu_dropdown_and_a_discord_choice():
    for field in looks.FIELDS:
        leaf = menu.LEAVES['lk_' + field]
        assert leaf['pick'] == f'field:customize:{field}' and menu.PARENT['lk_' + field] == 'looks'
        schema = next(o for o in m.DISCORD_OPTION_SCHEMA['customize'] if o['name'] == field)
        assert len(schema['choices']) == len(looks.choices(field)) <= 25 and schema['choices'][-1]['value'] == 'random'
        assert all(len(c['name']) <= 100 for c in schema['choices'])
    assert 'looks' in menu.AREAS['seedling'][3]


def test_a_look_can_be_shared_with_the_channel():
    customize(attitude='cheerful')
    member = {'member': {'user': {'id': '111', 'username': 'Kamex'}}}
    shared = ui.handle_component({'data': {'custom_id': ui.cid('111', 'sh', 'customize', '')}, **member})
    assert shared['type'] == 4 and 'flags' not in shared['data'] and 'shared their Seedling’s look' in shared['data']['embeds'][0]['author']['name']


def test_customizing_is_discord_only_when_twitch_is_lite(monkeypatch):
    monkeypatch.setattr(m.twitch_lite, 'ENABLED', True)
    text = client.get('/api/v1/looks', params={'channel': 'tw', 'uid': 'u1', 'name': 'Nova', 'skin': 'deep'}).text
    assert text.startswith('🔒 Seedling looks')
