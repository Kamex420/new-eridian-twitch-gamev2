"""Discord's newer layout (Components V2): every message is one card that is easy to scan,
with a button beside each list item where Discord's limits allow."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from starlette.background import BackgroundTasks
from test_colony import m, reset
from test_workbench_ui import citizen, press, W, LUMBER
from app import layout_v2 as v2, presentation, ui, menu, discord_deferred as deferred

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
        if isinstance(c.get('accessory'), dict):
            yield c['accessory']
        yield from walk(c.get('components'))


def assert_valid(data):
    """What Discord accepts for a Components V2 message."""
    assert data['flags'] & v2.FLAG and 'embeds' not in data and 'content' not in data
    assert not [k for k in data if k.startswith('_')]                          # private keys never leave
    every = list(walk(data['components']))
    assert len(every) <= v2.MAX_COMPONENTS
    texts = [c['content'] for c in every if c['type'] == v2.TEXT]
    assert texts and all(t.strip() for t in texts) and sum(map(len, texts)) <= v2.MAX_TEXT
    ids = [c['custom_id'] for c in every if 'custom_id' in c]
    assert len(ids) == len(set(ids)) and all(len(i) <= 100 for i in ids)
    rows = [c for c in every if c['type'] == v2.ROW]
    assert len(rows) <= 5 and all(0 < len(r['components']) <= 5 for r in rows)
    for c in every:
        if c['type'] == v2.SECTION:                                            # text with one button beside it
            assert 1 <= len(c['components']) <= 3 and all(t['type'] == v2.TEXT for t in c['components'])
            assert c['accessory']['type'] == 2
    for c in data['components']:
        assert c['type'] in {v2.CONTAINER, v2.ROW} and (c['type'] != v2.CONTAINER or c['components'])
    return True


def sections(data):
    return [c for c in walk(data['components']) if c['type'] == v2.SECTION]


def info_card(text=ITEM_MENU, color=0x5865F2):
    embed, _ = presentation.info(None, text, 'info')
    embed['color'] = color
    embed['footer'] = {'text': 'New Eridian v2 • footer'}
    return embed


def moderator(custom_id, values=None, flags=64):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)}, 'message': {'flags': flags}}
    return ui.handle_component(m, payload)


# ---------------------------------------------------------------- text

def test_lists_get_bold_names_details_in_quotes_and_notes_as_subtext():
    text = v2.block(info_card()['description'])
    lines = text.splitlines()
    assert '✅ **Maintenance & Repair** — branch Lv 9 (100 XP)' in lines
    assert '🔒 **Mechanical Engineering** — branch Lv 2 (5 XP) · unlock Basic Anvil 15 SC' in lines
    assert '> Uses: Iron Nails 4/1' in lines and '> Gives: 15 Iron Nails; shared components +1' in lines
    assert '**Main skill:** level 12 · 150 XP' in lines                       # short facts stay as they are
    for note in ('-# Each attempt costs', '-# ✅ ready · ❌ missing items', '-# Matching jobs: Engineer.', '-# Sources:', '-# Select Task'):
        assert any(x.startswith(note) for x in lines), note
    assert text.count('\n\n') == 2                                            # rules, the list, then notes


def test_text_that_is_not_a_list_is_left_alone():
    text = '**Energy:** 54\n✅ Ready for work\nComfort below 20 slows work.'
    assert v2.block(text) == text
    assert v2.block('Pick one from the menu below.') == '-# Pick one from the menu below.'


# ---------------------------------------------------------------- cards

def test_a_card_becomes_one_container_with_its_buttons_inside():
    embed = info_card()
    embed['fields'] = [{'name': 'Next Step', 'value': 'Craft a Campfire.', 'inline': False}]
    data = v2.convert({'embeds': [embed], 'components': [row('Gather', 'Mine')], 'flags': 64, 'allowed_mentions': {'parse': []}})
    assert_valid(data)
    assert data['flags'] == v2.FLAG | 64 and data['allowed_mentions'] == {'parse': []}
    box = data['components'][0]
    assert box['type'] == v2.CONTAINER and box['accent_color'] == 0x5865F2
    assert [c['type'] for c in box['components']] == [v2.TEXT, v2.SEPARATOR, v2.TEXT, v2.SEPARATOR, v2.ROW]
    assert box['components'][0]['content'].startswith('### 🎒 Item Menu — Engineering\n')
    assert box['components'][2]['content'].startswith('**Next Step**\nCraft a Campfire.')
    assert box['components'][2]['content'].endswith('-# New Eridian v2 • footer')
    assert [b['label'] for b in box['components'][-1]['components']] == ['Gather', 'Mine']


def test_short_receipts_stay_in_one_block_and_notices_become_cards():
    data = v2.convert({'embeds': [{'title': '✅ Gathered Lumber', 'description': '**+2** Lumber\n⚡ −2 Energy', 'color': 0x57F287}]})
    assert_valid(data)
    box = data['components'][0]
    assert [c['type'] for c in box['components']] == [v2.TEXT]
    assert box['components'][0]['content'] == '### ✅ Gathered Lumber\n**+2** Lumber\n⚡ −2 Energy'
    notice = v2.new_message({'content': 'Nothing was spent.', 'flags': 64})
    assert_valid(notice) and notice['flags'] == v2.FLAG | 64
    assert notice['components'][0]['accent_color'] == v2.NOTICE and v2.text_of(notice) == 'Nothing was spent.'


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
    huge = {'embeds': [{'title': 'Huge', 'description': 'x' * 5000}], 'components': [row('A')]}
    assert v2.convert(huge) is None                                           # a new message can stay in the old layout
    forced = v2.convert(huge, force=True)                                     # an edit of a new-layout message cannot
    assert assert_valid(forced) and forced['components'][0]['components'][0]['content'].endswith('…')


# ---------------------------------------------------------------- buttons beside items

def test_items_get_their_button_beside_them_and_replace_the_dropdown():
    menu_row = {'type': 1, 'components': [{'type': 3, 'custom_id': 'ne|1|pick', 'options': [{'label': 'A', 'value': 'a'}]}]}
    data = ui.with_items({'embeds': [{'title': 'List', 'description': 'Pick one.\n✅ **Alpha** — first\n╰ uses 1 Iron\n🔒 **Beta** — second', 'color': 1}],
                          'components': [menu_row, row('Back')]},
                         [{'match': '**Alpha**', 'button': ui.button('Open', 'ne|1|a')}, {'match': '**Beta**', 'button': ui.button('Open', 'ne|1|b')}],
                         ['ne|1|pick'])
    out = v2.convert(data)
    assert assert_valid(out)
    found = sections(out)
    assert [s['components'][0]['content'] for s in found] == ['✅ **Alpha** — first\n> uses 1 Iron', '🔒 **Beta** — second']
    assert [s['accessory']['custom_id'] for s in found] == ['ne|1|a', 'ne|1|b']
    assert 'ne|1|pick' not in [c.get('custom_id') for c in v2.controls(out)]       # the dropdown is replaced
    assert 'ne|1|b0' in [c.get('custom_id') for c in v2.controls(out)]             # other buttons stay
    # Text that does not match keeps the dropdown and no button moves.
    data['_items'][1]['match'] = '**Gamma**'
    out = v2.convert(data)
    assert not sections(out) and 'ne|1|pick' in [c.get('custom_id') for c in v2.controls(out)]
    # The old layout never sees the item list.
    assert '_items' not in v2.respond({'type': 7, 'data': dict(data)}, {'message': {'flags': 64}})['data']


def test_a_long_list_puts_as_many_buttons_beside_items_as_fit():
    lines = '\n'.join(f'• **Item {i}** — about item {i}' for i in range(20))
    buttons = [ui.button(f'Item {i}', f'ne|1|i{i}') for i in range(20)]
    data = ui.with_items({'embeds': [{'title': 'Many', 'description': lines}], 'components': [ui.row(*buttons[i:i + 5]) for i in range(0, 20, 5)]},
                         [{'match': f'**Item {i}**', 'button': dict(b, label='Open')} for i, b in enumerate(buttons)])
    out = v2.convert(data)
    assert assert_valid(out)
    beside = [s['accessory']['custom_id'] for s in sections(out)]
    rest = [c['custom_id'] for c in v2.controls(out) if c['custom_id'] not in beside]
    assert 5 <= len(beside) < 20 and beside == [f'ne|1|i{i}' for i in range(len(beside))]   # in order, as many as fit
    assert rest == [f'ne|1|i{i}' for i in range(len(beside), 20)]                           # the rest keep their buttons


def test_a_button_is_never_repeated_and_link_buttons_stay_put():
    link = {'type': 2, 'style': 5, 'label': 'Guide', 'url': 'https://example.com/guide'}
    data = ui.with_items({'embeds': [{'title': 'List', 'description': '✅ **Alpha** — first\n✅ **Beta** — second\n✅ **Gamma** — third'}],
                          'components': [{'type': 1, 'components': [link]}]},
                         [{'match': '**Alpha**', 'button': ui.button('Open', 'ne|1|same')},
                          {'match': '**Beta**', 'button': ui.button('Open', 'ne|1|same')},       # a repeat: shown as text
                          {'match': '**Gamma**', 'button': dict(link, label='Read')}])           # a link beside an item
    out = v2.convert(data)
    assert assert_valid(out)
    assert [s['accessory'].get('custom_id') for s in sections(out)] == ['ne|1|same', None]
    assert '**Beta**' in v2.text_of(out)
    assert [c.get('url') for c in v2.controls(out)].count(link['url']) == 2       # the row's link button is kept


def test_every_menu_area_and_choice_list_fits_with_buttons_beside_items():
    citizen()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        p.sc = 5000
        db.commit()
    for area in menu.AREAS:
        out = v2.convert(moderator(ui.cid('111', 'mn', area))['data'])
        assert assert_valid(out), area
        if area not in {'home', 'recent'}:
            assert sections(out), area
    for key, leaf in menu.LEAVES.items():
        if leaf['kind'] == 'pick':
            answer = moderator(ui.cid('111', 'mk', key))
            assert assert_valid(v2.convert(answer['data'])), key
    home = v2.convert(moderator(ui.cid('111', 'mn', 'home'))['data'])
    beside = {s['components'][0]['content'].split('**')[1] for s in sections(home)}
    assert {'Life & Recovery', 'Work', 'Craft', 'Bag', 'Trade'} <= beside
    assert {'Status', 'Settings'} <= {c['label'] for c in v2.controls(home)}      # quick buttons stay in a row
    assert 'Settings** —' not in v2.text_of(home)                                  # ...without their line


def test_menu_buttons_beside_lines():
    citizen()
    life = v2.convert(press(ui.cid('111', 'mn', 'life'))['data'])
    found = {s['components'][0]['content'].split('**')[1]: s['accessory'] for s in sections(life)}
    assert found['Relax']['label'] == 'Relax' and found['Relax']['custom_id'].startswith('ne|111|t|')   # actions keep their word
    assert found['Needs']['label'] == 'Open' and found['Needs']['style'] == 2                         # views say Open
    farming = v2.convert(press(ui.cid('111', 'mn', 'farming'))['data'])
    assert 'Tend fields** — gives 1 Pumpkin + 1 Pumpkin Seeds' in v2.text_of(farming)                 # every button has a line
    assert len(sections(farming)) == 3


def test_recent_actions_each_get_an_again_button():
    citizen()
    m.extras.record_discord(m, '111', 'Kam', 'gather', {'resource': LUMBER})
    m.extras.record_discord(m, '111', 'Kam', 'gather', {'resource': LUMBER})
    out = v2.convert(press(ui.cid('111', 'mn', 'recent'))['data'])
    assert assert_valid(out)
    again = [s['accessory'] for s in sections(out)]
    assert len(again) >= 1 and all(b['label'] == 'Again' and b['custom_id'].startswith('ne|111|t|') for b in again)


def test_choices_get_a_button_each_that_works_like_the_dropdown(monkeypatch):
    citizen()
    monkeypatch.setattr(m.community, 'ENABLED', True)
    ballot = v2.convert(press(ui.cid('111', 'mk', 'c_vote_pick'))['data'])
    assert assert_valid(ballot)
    votes = [s['accessory'] for s in sections(ballot)]
    assert [b['label'] for b in votes] == ['Vote'] * 3 and all(b['custom_id'].startswith('ne|111|mp|c_vote_pick|=') for b in votes)
    assert not [c for c in v2.controls(ballot) if c['type'] == 3]                                    # no dropdown left
    calls = []
    answer = ui.handle_component(m, {'type': 3, 'data': {'custom_id': votes[1]['custom_id']}, 'member': {'user': {'id': '111', 'username': 'Kam'}},
                                     'message': {'flags': 64 | v2.FLAG}}, lambda fn, *args: calls.append((fn, args)))
    assert answer == {'type': 6} and calls and calls[0][1][-1] == {'do': 'cmd', 'leaf': 'c_vote_pick', 'value': '2'}


def test_workbench_pages_open_each_recipe_from_beside_it():
    citizen()
    page = v2.convert(press(ui.cid('111', 'wc', 'parts', 1, ''))['data'])
    assert assert_valid(page)
    found = sections(page)
    assert len(found) == 8 and all(s['accessory']['label'] == 'Open' and '|wr|' in s['accessory']['custom_id'] for s in found)
    assert not [c for c in v2.controls(page) if c.get('custom_id', '').startswith('ne|111|sr|')]      # the recipe dropdown is replaced
    opened = press(found[0]['accessory']['custom_id'])
    assert opened['type'] == 7 and 'OUTPUT PER BATCH' in v2.text_of(opened['data']).upper()
    home = v2.convert(press(ui.cid('111', 'wh'))['data'])
    assert assert_valid(home) and sections(home)[0]['components'][0]['content'].startswith('✅ **Ready now**')


def test_a_skills_tasks_each_get_a_start_button():
    citizen()
    with m.SessionLocal() as db:
        view = menu.navigate(m, db, db.query(m.Player).one(), '111', 'mp', ['trainskill'], ['engineering'], 'Kam')
        db.commit()
    out = v2.convert(view)
    assert assert_valid(out)
    starts = [s['accessory'] for s in sections(out)]
    assert starts and all(b['label'] == 'Start' and b['custom_id'].startswith('ne|111|t|') for b in starts)
    assert 'Press Start beside a task' in v2.text_of(out)
    action, _ = ui.claim(m, '111', starts[0]['custom_id'].split('|')[3])
    assert action['do'] == 'train' and action['skill'] == 'engineering'
    result = ui.run_ticket(m, '111', 'Kam', action)
    assert {'Again', 'Tasks', 'Menu'} <= {c['label'] for c in v2.controls(result)}



# ---------------------------------------------------------------- where messages leave for Discord

def test_answers_follow_the_message_they_change(monkeypatch):
    card = {'embeds': [{'title': 'Status', 'description': 'All good', 'color': 1}], 'components': [row('Menu')]}
    new = v2.respond({'type': 4, 'data': dict(card, flags=64)}, {'message': {'flags': 0}})
    assert assert_valid(new['data']) and new['data']['flags'] == v2.FLAG | 64
    old = {'type': 7, 'data': dict(card)}
    assert v2.respond(old, {'message': {'flags': 64}}) == old                 # an old-layout message keeps it
    update = v2.respond({'type': 7, 'data': dict(card)}, {'message': {'flags': 64 | v2.FLAG}})
    assert assert_valid(update['data']) and update['data']['flags'] == v2.FLAG
    text_update = v2.respond({'type': 7, 'data': {'content': 'Expired.'}}, {'message': {'flags': v2.FLAG}})
    assert_valid(text_update['data'])
    for other in ({'type': 6}, {'type': 9, 'data': {'custom_id': 'x'}}):
        assert v2.respond(other, {}) == other
    monkeypatch.setattr(v2, 'ENABLED', False)
    assert v2.respond({'type': 4, 'data': dict(card)}, {})['data'] == card    # switched off: new replies use embeds
    assert v2.is_v2(v2.respond({'type': 7, 'data': dict(card)}, {'message': {'flags': v2.FLAG}})['data'])


def test_deferred_edits(monkeypatch):
    card = {'embeds': [{'title': 'Queue', 'description': 'Started'}], 'components': [row('Status')], 'flags': 64}
    edit = v2.edit(card, {'type': 2})
    assert assert_valid(edit) and edit['flags'] == v2.FLAG                     # the flag goes on the edit itself
    assert v2.is_v2(v2.edit({'content': 'Could not be completed.'}, {'type': 2}))
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
    monkeypatch.setattr(deferred.time, 'sleep', lambda s: None)
    card = {'embeds': [{'title': 'Queue', 'description': 'Started'}], 'components': [row('Status')]}
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(400 if v2.is_v2(json) else 200))
    token = ui.INTERACTION.set({'type': 2})
    try:
        assert deferred.edit_original('a', 't', card)
        assert [v2.is_v2(x) for x in sent] == [True, False] and sent[1]['embeds'] == card['embeds']
        sent.clear()
        # A message already in the new layout cannot go back: drop its buttons instead.
        monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(400 if len(sent) == 1 else 200))
        ui.INTERACTION.set({'type': 3, 'message': {'flags': v2.FLAG | 64}})
        assert deferred.edit_original('a', 't', card)
        assert len(sent) == 2 and all(v2.is_v2(x) for x in sent) and not v2.controls(sent[1])
    finally:
        ui.INTERACTION.reset(token)


def test_button_answers_are_acknowledged_then_sent_with_the_fallback(monkeypatch):
    payload = {'type': 3, 'application_id': 'a', 'token': 't', 'message': {'flags': 64 | v2.FLAG}}
    later = []
    update = {'type': 7, 'data': {'embeds': [{'title': 'Menu', 'description': 'Pick one'}], 'components': [row('Life')]}}
    assert deferred.defer(update, payload, lambda fn, *args: later.append((fn, args))) == {'type': 6}
    new = {'type': 4, 'data': {'content': 'Nothing was spent.', 'flags': 64}}
    assert deferred.defer(new, payload, lambda fn, *args: later.append((fn, args))) == {'type': 5, 'data': {'flags': 64}}
    assert deferred.defer({'type': 9, 'data': {}}, payload, later.append) == {'type': 9, 'data': {}}
    sent = []
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(200))
    for fn, args in later:
        fn(*args)
    assert all(v2.is_v2(x) for x in sent) and v2.text_of(sent[1]) == 'Nothing was spent.'
    # Without Discord's details (tests, odd payloads) the answer goes back directly, in its layout.
    assert m._discord_answer(update, {'type': 3, 'message': {'flags': 64}}, BackgroundTasks())['type'] == 7


def test_every_slash_reply_is_valid_in_the_new_layout(monkeypatch):
    """Each command's real reply, as it leaves for Discord."""
    citizen()
    sent = []
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json, timeout: sent.append(json) or Reply(200))
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '5', 'discord')
    cases = [(name, {}) for name in m.DISCORD_OPTION_SCHEMA if name not in {'link', 'eventstart', 'eventstop', 'find'}]
    cases += [('find', {'query': 'lumber'}), ('queue', {'action': 'view'}), ('make', {'category': 'ready'}),
              ('make', {'category': 'parts'}), ('life', {'action': 'relax'}), ('seedindustries', {'action': 'orders'}),
              ('training', {'skill': 'engineering'}), ('inventory', {})]
    for command, options in cases:
        payload = {'type': 2, 'id': f'{command}-{len(sent)}-{sorted(options.items())}', 'application_id': 'a', 'token': 't',
                   'channel_id': '5', 'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)}}
        deferred.finish(m, payload, command, '111', 'Kam', options)
        assert assert_valid(sent[-1]), command


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


def test_the_pinned_panel_is_posted_with_a_button_beside_each_line(monkeypatch):
    sent = []
    monkeypatch.setattr('requests.post', lambda url, **kw: sent.append(kw['json']) or SimpleNamespace(status_code=200))
    assert ui.post_public_panel(m, '123', token='x')
    body = sent[0]
    assert assert_valid(body) and not body['flags'] & v2.EPHEMERAL
    found = sections(body)
    assert len(found) == 10 and all(s['accessory']['label'] == 'Open' and s['accessory']['custom_id'].startswith('ne|*|') for s in found)


def test_text_of_reads_both_layouts():
    card = {'embeds': [{'title': 'T', 'description': 'D', 'fields': [{'name': 'N', 'value': 'V'}], 'footer': {'text': 'F'}}]}
    assert all(x in v2.text_of(card) for x in 'TDNVF')
    assert all(x in v2.text_of(v2.convert(card)) for x in 'TDNVF')
