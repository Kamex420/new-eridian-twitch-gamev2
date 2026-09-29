"""Every command reachable by buttons: amounts, pages, pop-up forms, the public panel and moderator tools."""
import json
from test_colony import m, reset
from test_workbench_ui import citizen, press, controls, W, LUMBER
from app import ui, menu


def labels(data):
    return [c.get('label') or c.get('placeholder', '') for c in controls(data)]


def button(data, prefix):
    return next(c for c in controls(data) if (c.get('label') or '').startswith(prefix))


def text_of(data):
    return json.dumps(data, ensure_ascii=False)


def submit(custom_id, value, uid='111', flags=64, permissions='0'):
    payload = {'type': 5, 'data': {'custom_id': custom_id, 'components': [{'type': 1, 'components': [
        {'type': 4, 'custom_id': 'value', 'value': value}]}]},
        'member': {'user': {'id': uid, 'username': 'Kam'}, 'permissions': permissions}, 'message': {'flags': flags}}
    return ui.handle_modal(m, payload)


def moderator_press(custom_id, uid='111', values=None):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': uid, 'username': 'Kam'}, 'permissions': str(0x20)}, 'message': {'flags': 64}}
    return ui.handle_component(m, payload)


def test_every_slash_command_option_has_a_button():
    """Each choice of every player command is reachable from /menu."""
    reached = {}
    for key, leaf in menu.LEAVES.items():
        if leaf['kind'] == 'nav':
            continue
        command, options = m.discord_legacy_route(leaf['cmd'], leaf['opts'])
        reached.setdefault(command, set()).update(f'{k}={v}' for k, v in options.items())
        if leaf.get('option'):
            reached[command].add(leaf['option'] + '=*')
    expected = {
        'seedindustries': {'action=buy', 'action=sell', 'action=sellall', 'action=browse', 'action=fulfill', 'action=clearout'},
        'market': {'action=view', 'action=work', 'action=analyze'},
        'workshop': {'action=unlock', 'station=*'},
        'repair': {'target=society', 'target=gear'},
        'inventory': {'sort=name', 'sort=category', 'show=favorites', 'show=sellable', 'search=*'},
        'business': {'action=start', 'name=*'},
        'link': {'code=*'}, 'find': {'query=*'}, 'guide': {'goal=*'}, 'training': {'skill=*'}, 'catalog': {'category=*'},
        'eventstart': {'event=*'}, 'linklookup': {'player=*'},
    }
    for command, needed in expected.items():
        assert needed <= reached.get(command, set()), (command, needed - reached.get(command, set()))
    for area, (_, _, _, children) in menu.AREAS.items():
        assert len(children) <= 20, area


def test_buy_with_pages_amount_buttons_and_a_custom_amount():
    citizen()
    pick = press(ui.cid('111', 'mk', 'buy'))['data']
    select = pick['components'][0]['components'][0]
    assert len(select['options']) <= 25 and select['options'][-1]['value'].startswith('__page:')
    page2 = press(select['custom_id'], values=['__page:2'])['data']
    assert 'Page 2' in text_of(page2)
    item = select['options'][0]['value']
    amounts = press(select['custom_id'], values=[item])['data']
    assert {'Buy 1', 'Buy 5', 'Buy 10', 'Buy 25', 'Other amount…'} <= set(labels(amounts))
    bought = press(button(amounts, 'Buy 5')['custom_id'])['data']
    assert 'bought 5' in text_of(bought) and 'Browse shop' in labels(bought)    # stays in Trade
    form = press(ui.cid('111', 'mo', 'buy', item))
    assert form['type'] == 9
    assert 'bought 3' in text_of(submit(form['data']['custom_id'], '3')['data'])
    assert 'whole number' in text_of(submit(form['data']['custom_id'], '999')['data'])
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.material_amount(db, p, item) == 8


def test_sell_some_offers_only_amounts_you_have():
    citizen(lumber=7)
    amounts = press(ui.cid('111', 'mp', 'sellsome'), values=[LUMBER])['data']
    assert 'Sell 1' in labels(amounts) and 'Sell 5' in labels(amounts) and 'Sell all 7' in labels(amounts)
    assert 'Sell 10' not in labels(amounts)
    press(button(amounts, 'Sell 5')['custom_id'])
    with m.SessionLocal() as db:
        p = m.player(db, W, 'discord', '111', 'Kam')[1]
        assert m.material_amount(db, p, LUMBER) == 2


def test_forms_search_find_link_and_start_a_business():
    citizen()
    assert press(ui.cid('111', 'mo', 'find'))['type'] == 9
    assert 'Campfire' in text_of(submit(ui.cid('111', 'md', 'find'), 'campfire')['data'])
    assert 'Lumber' in text_of(submit(ui.cid('111', 'md', 'search'), 'lum')['data'])
    assert 'Invalid or expired code' in text_of(submit(ui.cid('111', 'md', 'link'), 'NOPE')['data'])
    assert 'registered' in text_of(submit(ui.cid('111', 'md', 'bstart'), 'Rocky Repairs')['data'])
    assert 'belongs to another citizen' in text_of(submit(ui.cid('222', 'md', 'find'), 'x'))


def test_views_behind_dropdowns():
    citizen()
    assert 'Training' in text_of(press(ui.cid('111', 'mp', 'browse'), values=['training'])['data'])
    assert 'Crafting' in text_of(press(ui.cid('111', 'mp', 'trainskill'), values=['crafting'])['data'])
    assert press(ui.cid('111', 'mk', 'unlock'))['data']['components'][0]['components'][0]['options']
    assert 'Repair gear' in labels(press(ui.cid('111', 'mn', 'work'))['data'])


def test_public_panel_opens_each_citizens_own_private_menu():
    citizen('222')
    panel = ui.public_panel(m)
    ids = [c['custom_id'] for c in controls(panel)]
    assert ids and all(i.startswith('ne|*|') for i in ids)
    payload = {'type': 3, 'data': {'custom_id': ui.cid('*', 'mn', 'home')}, 'member': {'user': {'id': '222', 'username': 'Ana'}},
               'message': {'flags': 0}}
    result = ui.handle_component(m, payload)
    assert result['type'] == 4 and result['data']['flags'] == 64
    assert all('|222|' in c['custom_id'] for c in controls(result['data']))
    payload['data']['custom_id'] = ui.cid('*', 't', 'abc')
    assert 'Open your own menu' in text_of(ui.handle_component(m, payload))


def test_moderator_tools_are_hidden_and_refused_for_players():
    citizen()
    assert 'Moderator' not in labels(press(ui.cid('111', 'mn', 'home'))['data'])
    assert 'Moderator' in labels(moderator_press(ui.cid('111', 'mn', 'home'))['data'])
    denied = press(ui.cid('111', 'mv', 'm_modlog'))['data']
    assert 'Moderator access is required' in text_of(denied)
    assert 'No moderator actions' in text_of(moderator_press(ui.cid('111', 'mv', 'm_modlog'))['data'])
    confirm = moderator_press(ui.cid('111', 'mp', 'm_eventstart'), values=['food'])['data']
    started = moderator_press(button(confirm, 'Confirm')['custom_id'])['data']
    assert 'Moderator access' not in text_of(started)
    assert 'could not be posted' in m._discord_call_internal('menupanel', '111', 'Kam', {}, 'i')


def test_slash_replies_offer_the_areas_next_buttons():
    citizen()
    rows = menu.after_rows(m, 'relax', {}, '111')
    assert len(rows) == 2 and 'Again' in labels({'components': rows})
    assert 'Relax' not in [c['label'] for c in rows[0]['components']]


def _deferred_reply(monkeypatch, command, options, sent):
    payload = {'id': f'{command}-{len(sent)}-{sorted(options.items())}', 'application_id': 'a', 'token': 't', 'channel_id': '5',
               'member': {'user': {'id': '111', 'username': 'Kam'}, 'permissions': str(0x20)}}
    m.discord_deferred.finish(m, payload, command, '111', 'Kam', options)
    return sent[-1]


def test_every_slash_reply_has_valid_unique_buttons(monkeypatch):
    """Discord rejects repeated custom_ids, which left /queue stuck on "thinking…"."""
    citizen()
    sent = []
    monkeypatch.setattr(m.discord_deferred, 'edit_original', lambda app, token, data: sent.append(data) or True)
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    m.queued_tasks(W, '111', 'Kam', 'start', 'gather:' + LUMBER, '5', 'discord')
    cases = [(name, {}) for name in m.DISCORD_OPTION_SCHEMA if name not in {'link', 'eventstart', 'eventstop', 'find'}]
    cases += [('find', {'query': 'lumber'}), ('queue', {'action': 'view'}), ('make', {'category': 'ready'}),
              ('life', {'action': 'relax'}), ('seedindustries', {'action': 'orders'})]
    for command, options in cases:
        data = _deferred_reply(monkeypatch, command, options, sent)
        rows = data.get('components') or []
        ids = [c['custom_id'] for r in rows for c in r['components'] if 'custom_id' in c]
        assert len(ids) == len(set(ids)), (command, ids)
        assert len(rows) <= 5 and all(0 < len(r['components']) <= 5 for r in rows), command


def test_rejected_reply_is_resent_without_buttons(monkeypatch):
    calls = []

    class Response:
        def __init__(self, code):
            self.status_code, self.text = code, 'Invalid Form Body'

    def patch(url, json, timeout):
        calls.append(json)
        return Response(400 if 'components' in json else 200)
    monkeypatch.setattr(m.discord_deferred.requests, 'patch', patch)
    assert m.discord_deferred.edit_original('a', 't', {'content': 'hi', 'components': [{'type': 1, 'components': []}]})
    assert len(calls) == 2 and 'components' not in calls[1] and calls[1]['content'] == 'hi'


def test_tidy_removes_repeats_and_empty_rows():
    data = {'components': [ui.row(ui.button('A', 'ne|1|qv'), ui.button('B', 'ne|1|qd')), ui.row(ui.button('A again', 'ne|1|qv')),
                           ui.row(ui.button('C', 'ne|1|st'))]}
    rows = ui.tidy(data)['components']
    assert [[c['label'] for c in r['components']] for r in rows] == [['A', 'B'], ['C']]
