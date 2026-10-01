"""Discord's newer layout (Components V2): every reply is one container that is easy to scan."""
import json
from types import SimpleNamespace
import pytest
from test_colony import m, reset
from test_workbench_ui import citizen, press, W, LUMBER
from app import layout_v2 as v2, presentation, ui

ITEM_MENU = """🎒 ITEM MENU — Engineering
Main skill: level 12 · 150 XP
Each attempt costs −2 Energy · −1 Nutrition · −2 Comfort and starts a 5-second cooldown. Materials are used only on success; failures keep them.
✅ ready · ❌ missing items · 🔒 level, tier or workstation lock
✅ Maintenance & Repair — branch Lv 9 (100 XP)
  Uses: Iron Nails 4/1
  Gives: shared infrastructure +1
🔒 Mechanical Engineering — branch Lv 2 (5 XP) · unlock Basic Anvil 15 SC
  Uses: Iron Ingot 95/1 · recipe: Iron Nails at Basic Anvil (T1, Metalworking Lv1)
  Gives: 15 Iron Nails; shared components +1
Matching jobs: Engineer. Use /job. Main skill levels improve success; branch levels add up to 5 percentage points to matching task success.
Sources: Lumber → Harvesting or /gather; ores → /mine; every manufactured item → /make.
Select Task to perform work. Browsing spends nothing."""


def row(*labels, prefix='b'):
    return {'type': 1, 'components': [{'type': 2, 'style': 2, 'label': x, 'custom_id': f'ne|1|{prefix}{i}'} for i, x in enumerate(labels)]}


def walk(components):
    for c in components or []:
        yield c
        yield from walk(c.get('components'))


def assert_valid(data):
    """What Discord accepts for a Components V2 message."""
    assert data['flags'] & v2.FLAG and 'embeds' not in data and 'content' not in data
    every = list(walk(data['components']))
    assert len(every) <= v2.MAX_COMPONENTS
    texts = [c['content'] for c in every if c['type'] == v2.TEXT]
    assert texts and all(t.strip() for t in texts) and sum(map(len, texts)) <= v2.MAX_TEXT
    ids = [c['custom_id'] for c in every if 'custom_id' in c]
    assert len(ids) == len(set(ids))
    rows = [c for c in every if c['type'] == v2.ROW]
    assert len(rows) <= 5 and all(0 < len(r['components']) <= 5 for r in rows)
    for c in data['components']:
        assert c['type'] in {v2.CONTAINER, v2.ROW} and (c['type'] != v2.CONTAINER or c['components'])
    return True


def info_card(text=ITEM_MENU, color=0x5865F2):
    embed, _ = presentation.info(None, text, 'info')
    embed['color'] = color
    embed['footer'] = {'text': 'New Eridian v2 • footer'}
    return embed


def test_lists_get_bold_names_details_in_quotes_and_notes_as_subtext():
    text = v2.block(info_card()['description'])
    lines = text.splitlines()
    assert '✅ **Maintenance & Repair** — branch Lv 9 (100 XP)' in lines
    assert '🔒 **Mechanical Engineering** — branch Lv 2 (5 XP) · unlock Basic Anvil 15 SC' in lines
    assert '> Uses: Iron Nails 4/1' in lines and '> Gives: 15 Iron Nails; shared components +1' in lines
    assert '**Main skill:** level 12 · 150 XP' in lines                       # short facts stay as they are
    for note in ('-# Each attempt costs', '-# ✅ ready · ❌ missing items', '-# Matching jobs: Engineer.', '-# Sources:', '-# Select Task'):
        assert any(x.startswith(note) for x in lines), note
    # Three groups: rules, the list, then notes.
    assert text.count('\n\n') == 2


def test_text_that_is_not_a_list_is_left_alone():
    text = '**Energy:** 54\n✅ Ready for work\nComfort below 20 slows work.'
    assert v2.block(text) == text
    assert v2.block('Pick one from the menu below.') == '-# Pick one from the menu below.'


def test_a_card_becomes_one_container_with_its_buttons_inside():
    embed = info_card()
    embed['fields'] = [{'name': 'Next Step', 'value': 'Craft a Campfire.', 'inline': False}]
    data = v2.convert({'embeds': [embed], 'components': [row('Gather', 'Mine')], 'flags': 64, 'allowed_mentions': {'parse': []}})
    assert_valid(data)
    assert data['flags'] == v2.FLAG | 64 and data['allowed_mentions'] == {'parse': []}
    box = data['components'][0]
    assert box['type'] == v2.CONTAINER and box['accent_color'] == 0x5865F2
    kinds = [c['type'] for c in box['components']]
    assert kinds == [v2.TEXT, v2.SEPARATOR, v2.TEXT, v2.SEPARATOR, v2.ROW]      # sections under dividers, buttons last
    assert box['components'][0]['content'].startswith('### 🎒 Item Menu — Engineering\n')
    assert box['components'][2]['content'].startswith('**Next Step**\nCraft a Campfire.')
    assert box['components'][2]['content'].endswith('-# New Eridian v2 • footer')
    assert [b['label'] for b in box['components'][-1]['components']] == ['Gather', 'Mine']


def test_short_receipts_stay_in_one_block():
    data = v2.convert({'embeds': [{'title': '✅ Gathered Lumber', 'description': '**+2** Lumber\n⚡ −2 Energy', 'color': 0x57F287}]})
    assert_valid(data)
    box = data['components'][0]
    assert [c['type'] for c in box['components']] == [v2.TEXT]
    assert box['components'][0]['content'] == '### ✅ Gathered Lumber\n**+2** Lumber\n⚡ −2 Energy'


def test_shared_cards_name_who_shared_them():
    data = v2.convert({'embeds': [{'title': 'Profile', 'description': 'Level 3', 'author': {'name': '📣 Kam shared their profile'}}]})
    assert data['components'][0]['components'][0]['content'].startswith('-# 📣 Kam shared their profile\n### Profile')
    assert data['flags'] == v2.FLAG                                           # public: no private flag


def test_limits_compact_the_card_and_only_give_up_when_allowed():
    many = {'title': 'Big', 'description': 'Intro', 'footer': {'text': 'f'},
            'fields': [{'name': f'Part {i}', 'value': f'Line {i}'} for i in range(12)]}
    rows = [row(*'ABCDE', prefix=f'r{n}') for n in range(5)]
    data = v2.convert({'embeds': [many], 'components': rows})
    assert_valid(data)                                                        # dividers dropped to fit 40 components
    assert v2.SEPARATOR not in [c['type'] for c in data['components'][0]['components'][:-6]]
    huge = {'embeds': [{'title': 'Huge', 'description': 'x' * 5000}], 'components': [row('A')]}
    assert v2.convert(huge) is None                                           # a new message can stay in the old layout
    forced = v2.convert(huge, force=True)                                     # an edit of a new-layout message cannot
    assert assert_valid(forced) and forced['components'][0]['components'][0]['content'].endswith('…')


def test_answers_follow_the_message_they_change(monkeypatch):
    card = {'embeds': [{'title': 'Status', 'description': 'All good', 'color': 1}], 'components': [row('Menu')]}
    new = v2.respond({'type': 4, 'data': dict(card, flags=64)}, {'message': {'flags': 0}})
    assert assert_valid(new['data']) and new['data']['flags'] == v2.FLAG | 64
    notice = {'type': 4, 'data': {'content': 'Nothing was spent.', 'flags': 64}}
    assert v2.respond(notice, {}) == notice                                   # one-line notices stay plain text
    old = {'type': 7, 'data': dict(card)}
    assert v2.respond(old, {'message': {'flags': 64}}) == old                 # an old-layout message keeps it
    update = v2.respond({'type': 7, 'data': dict(card)}, {'message': {'flags': 64 | v2.FLAG}})
    assert assert_valid(update['data']) and update['data']['flags'] == v2.FLAG
    text_update = v2.respond({'type': 7, 'data': {'content': 'Expired.'}}, {'message': {'flags': v2.FLAG}})
    assert_valid(text_update['data'])                                         # even plain text, once a message is new-layout
    for other in ({'type': 6}, {'type': 9, 'data': {'custom_id': 'x'}}):
        assert v2.respond(other, {}) == other
    monkeypatch.setattr(v2, 'ENABLED', False)
    assert v2.respond({'type': 4, 'data': dict(card)}, {})['data'] == card    # switched off: new replies use embeds
    assert v2.is_v2(v2.respond({'type': 7, 'data': dict(card)}, {'message': {'flags': v2.FLAG}})['data'])


def test_deferred_edits(monkeypatch):
    card = {'embeds': [{'title': 'Queue', 'description': 'Started'}], 'components': [row('Status')], 'flags': 64}
    edit = v2.edit(card, {'type': 2})
    assert assert_valid(edit) and edit['flags'] == v2.FLAG                            # the flag goes on the edit itself
    assert v2.edit({'content': 'Could not be completed.'}, {'type': 2}) is None
    assert v2.edit(card, {'type': 3, 'message': {'flags': 64}}) is None        # a button on an old-layout message
    assert v2.is_v2(v2.edit({'content': 'Failed.'}, {'type': 3, 'message': {'flags': v2.FLAG}}))
    monkeypatch.setattr(v2, 'ENABLED', False)
    assert v2.edit(card, {'type': 2}) is None


class Reply:
    def __init__(self, code):
        self.status_code, self.text = code, 'Invalid Form Body'

    def json(self):
        return {}


def test_a_refused_new_layout_falls_back(monkeypatch):
    sent = []
    monkeypatch.setattr(m.discord_deferred.time, 'sleep', lambda s: None)
    card = {'embeds': [{'title': 'Queue', 'description': 'Started'}], 'components': [row('Status')]}
    monkeypatch.setattr(m.discord_deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(400 if v2.is_v2(json) else 200))
    token = ui.INTERACTION.set({'type': 2})
    try:
        assert m.discord_deferred.edit_original('a', 't', card)
        assert [v2.is_v2(x) for x in sent] == [True, False] and sent[1]['embeds'] == card['embeds']
        sent.clear()
        # A message already in the new layout cannot go back: drop its buttons instead.
        monkeypatch.setattr(m.discord_deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(400 if len(sent) == 1 else 200))
        ui.INTERACTION.set({'type': 3, 'message': {'flags': v2.FLAG | 64}})
        assert m.discord_deferred.edit_original('a', 't', card)
        assert len(sent) == 2 and all(v2.is_v2(x) for x in sent)
        assert not [c for c in walk(sent[1]['components']) if c['type'] == v2.ROW]
    finally:
        ui.INTERACTION.reset(token)


def test_every_slash_reply_is_valid_in_the_new_layout(monkeypatch):
    """Each command's real reply, as it leaves for Discord."""
    citizen()
    sent = []
    monkeypatch.setattr(m.discord_deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(200))
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '5', 'discord')
    cases = [(name, {}) for name in m.DISCORD_OPTION_SCHEMA if name not in {'link', 'eventstart', 'eventstop', 'find'}]
    cases += [('find', {'query': 'lumber'}), ('queue', {'action': 'view'}), ('make', {'category': 'ready'}),
              ('make', {'category': 'components'}), ('life', {'action': 'relax'}), ('seedindustries', {'action': 'orders'}),
              ('training', {'skill': 'engineering'}), ('inventory', {})]
    for command, options in cases:
        payload = {'type': 2, 'id': f'{command}-{len(sent)}-{sorted(options.items())}', 'application_id': 'a', 'token': 't',
                   'channel_id': '5', 'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)}}
        m.discord_deferred.finish(m, payload, command, '111', 'Kam', options)
        data = sent[-1]
        if v2.is_v2(data):
            assert_valid(data)
        else:
            assert 'content' in data and not data.get('embeds'), (command, data)   # plain text replies only


def test_buttons_and_details_pages_on_new_layout_messages_stay_in_it():
    citizen()
    payload = {'type': 3, 'data': {'custom_id': ui.cid('111', 'mn', 'home'), 'values': []},
               'member': {'user': {'id': '111', 'username': 'Kam'}}, 'message': {'flags': 64 | v2.FLAG}}
    answer = v2.respond(ui.handle_component(m, payload), payload)
    assert answer['type'] == 7
    assert_valid(answer['data'])
    data = m._discord_json_message('DETAILS\n' + 'line\n' * 80)['data']
    custom = data['components'][0]['components'][0]['custom_id']
    page = {'type': 3, 'data': {'custom_id': custom}, 'message': {'flags': 64 | v2.FLAG}}
    answer = v2.respond(m.message_layout.open_page(m, page), page)
    assert answer['type'] == 7
    assert assert_valid(answer['data']) and 'line' in v2.text_of(answer['data'])


def test_text_of_reads_both_layouts():
    card = {'embeds': [{'title': 'T', 'description': 'D', 'fields': [{'name': 'N', 'value': 'V'}], 'footer': {'text': 'F'}}]}
    assert all(x in v2.text_of(card) for x in 'TDNVF')
    assert all(x in v2.text_of(v2.convert(card)) for x in 'TDNVF')
