"""The owner's custom (application) emoji on newer-layout Discord cards: which unicode emoji change, which never do,
and that a send never waits for the network."""
import copy
import logging
import threading
import time
from types import SimpleNamespace
import pytest
from app import custom_emoji as ce, layout_v2 as v2, discord_queue_worker as worker

ALL = {'seemsgoodmelisa': '111', 'JohnShades': '222', 'andyevillaugh': '333', 'JJhydrate': '444',
       'duck': '555', 'Rocky': '666'}
MELISA, JOHN, ANDY, JJ = '<:seemsgoodmelisa:111>', '<:JohnShades:222>', '<:andyevillaugh:333>', '<:JJhydrate:444>'
DUCK, ROCKY = '<:duck:555>', '<:Rocky:666>'


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """No token (so no thread, no network), an empty list and the alternation back at its start."""
    monkeypatch.delenv('DISCORD_BOT_TOKEN', raising=False)
    monkeypatch.delenv('DISCORD_APPLICATION_ID', raising=False)
    ce.reset()
    yield
    ce.reset()


def card(*texts, rows=()):
    return v2.card(list(texts), rows=list(rows))


def texts(data):
    return [c['content'] for c in data['components'][0]['components'] if c['type'] == v2.TEXT]


def button(label, emoji=None):
    b = {'type': 2, 'style': 2, 'label': label, 'custom_id': 'ne|1|' + label}
    if emoji:
        b['emoji'] = {'name': emoji}
    return b


def row(*buttons):
    return {'type': 1, 'components': list(buttons)}


# ---------------------------------------------------------------- task headings

def test_done_headings_take_turns():
    ce.set_table(ALL)
    got = [texts(ce.apply(card('### ✅ Crafted Iron Nails')))[0] for _ in range(4)]
    assert got == [f'### {e} Crafted Iron Nails' for e in (MELISA, JOHN, MELISA, JOHN)]


def test_failed_headings_take_turns():
    ce.set_table(ALL)
    got = [texts(ce.apply(card('### ❌ Mining failed')))[0] for _ in range(3)]
    assert got == [f'### {e} Mining failed' for e in (ANDY, JJ, ANDY)]


def test_done_and_failed_alternate_on_their_own_and_reset_starts_over():
    ce.set_table(ALL)
    assert texts(ce.apply(card('### ✅ A')))[0] == f'### {MELISA} A'
    assert texts(ce.apply(card('### ❌ B')))[0] == f'### {ANDY} B'
    assert texts(ce.apply(card('### ✅ C')))[0] == f'### {JOHN} C'
    ce.reset_turns()
    assert texts(ce.apply(card('### ✅ D')))[0] == f'### {MELISA} D'


def test_each_heading_line_in_one_block_takes_its_own_turn():
    ce.set_table(ALL)
    out = texts(ce.apply(card('### ✅ First\ndetails\n### ✅ Second\n### ❌ Third')))[0]
    assert out == f'### {MELISA} First\ndetails\n### {JOHN} Second\n### {ANDY} Third'


def test_only_heading_marks_change():
    ce.set_table(ALL)
    block = ('### ✅ Crafted Iron Nails\n✅ Iron Ingot — ready\n❌ Missing — none\n🔒 Locked\n🔑 Key\n'
             '## ✅ A bigger heading\n- ### ✅ in a list\n### ✅No space\nDone ✅ and failed ❌')
    out = texts(ce.apply(card(block)))[0].split('\n')
    assert out[0] == f'### {MELISA} Crafted Iron Nails'
    assert out[1:] == block.split('\n')[1:]


def test_failed_heading_leaves_a_done_mark_in_its_text_alone():
    ce.set_table(ALL)
    assert texts(ce.apply(card('### ❌ Mining failed ✅')))[0] == f'### {ANDY} Mining failed ✅'


# ---------------------------------------------------------------- duck and Rocky

def test_duck_and_rocky_in_any_text():
    ce.set_table(ALL)
    out = texts(ce.apply(card('### ✅ 🦆 Delivery done 🦆\n-# 🪨 Rocky says hi\n🪨🦆 and 🪨', 'Second 🦆')))
    assert out == [f'### {MELISA} {DUCK} Delivery done {DUCK}\n-# {ROCKY} Rocky says hi\n{ROCKY}{DUCK} and {ROCKY}',
                   f'Second {DUCK}']


def test_buttons_and_choices_get_the_custom_emoji_and_keep_their_labels():
    ce.set_table({'duck': '555', 'Rocky': ('666', True)})
    choices = {'type': 3, 'custom_id': 'pick', 'options': [
        {'label': 'Duck 🦆', 'value': 'd', 'emoji': {'name': '🦆'}},
        {'label': 'Rock', 'value': 'r', 'emoji': {'name': '🪨'}},
        {'label': 'Home', 'value': 'h', 'emoji': {'name': '🏠'}},
        {'label': 'Plain', 'value': 'p'}]}
    data = ce.apply(card('Body', rows=[row(button('Deliver 🦆', '🦆'), button('Menu', '🏠'), button('Rocks', '🪨'),
                                           dict(button('Custom'), emoji={'id': '9', 'name': 'mine'})), {'type': 1, 'components': [choices]}]))
    buttons = [c for c in v2.controls(data) if c['type'] == 2]
    assert [(b['label'], b.get('emoji')) for b in buttons[:4]] == [
        ('Deliver 🦆', {'id': '555', 'name': 'duck', 'animated': False}),
        ('Menu', {'name': '🏠'}),
        ('Rocks', {'id': '666', 'name': 'Rocky', 'animated': True}),
        ('Custom', {'id': '9', 'name': 'mine'})]
    options = choices['options']
    assert [(o['label'], o['emoji']) for o in options if 'emoji' in o] == [
        ('Duck 🦆', {'name': '🦆'}), ('Rock', {'name': '🪨'}), ('Home', {'name': '🏠'})]      # the input is not touched
    menu = next(c for c in v2.controls(data) if c['type'] == 3)
    assert [(o['label'], o.get('emoji')) for o in menu['options']] == [
        ('Duck 🦆', {'id': '555', 'name': 'duck', 'animated': False}),
        ('Rock', {'id': '666', 'name': 'Rocky', 'animated': True}),
        ('Home', {'name': '🏠'}), ('Plain', None)]


def test_a_section_buttons_emoji_is_swapped_too():
    ce.set_table(ALL)
    section = {'type': 9, 'components': [{'type': 10, 'content': 'Item 🦆'}], 'accessory': button('Ride', '🦆')}
    data = {'flags': v2.FLAG, 'components': [{'type': 17, 'components': [section]}]}
    out = ce.apply(data)['components'][0]['components'][0]
    assert out['components'][0]['content'] == f'Item {DUCK}'
    assert out['accessory']['emoji'] == {'id': '555', 'name': 'duck', 'animated': False}


# ---------------------------------------------------------------- what is not found

def test_an_emoji_that_is_not_found_stays_unicode():
    ce.set_table({'duck': '555'})
    data = card('### ✅ Done 🦆 🪨', rows=[row(button('Rocks', '🪨'))])
    out = ce.apply(data)
    assert texts(out) == ['### ✅ Done ' + DUCK + ' 🪨']
    assert out['components'][0]['components'][-1]['components'][0]['emoji'] == {'name': '🪨'}


def test_with_one_of_a_pair_found_that_one_is_used_every_time():
    ce.set_table({'JohnShades': '222', 'JJhydrate': '444'})
    done = [texts(ce.apply(card('### ✅ Done')))[0] for _ in range(3)]
    failed = [texts(ce.apply(card('### ❌ Failed')))[0] for _ in range(3)]
    assert done == [f'### {JOHN} Done'] * 3 and failed == [f'### {JJ} Failed'] * 3


def test_with_neither_of_a_pair_found_the_mark_stays():
    ce.set_table({'duck': '555'})
    assert texts(ce.apply(card('### ✅ Done\n### ❌ Failed'))) == ['### ✅ Done\n### ❌ Failed']


def test_no_list_at_all_changes_nothing():
    data = card('### ✅ Done 🦆 🪨', rows=[row(button('Deliver', '🦆'))])
    out = ce.apply(data)
    assert out == data and out is not data


def test_names_match_in_any_case_and_render_as_discord_spells_them():
    ce.set_table({'ROCKY': '666', 'Duck': ('555', True)})
    assert texts(ce.apply(card('🪨 🦆'))) == ['<:ROCKY:666> <a:Duck:555>']


def test_an_animated_emoji_renders_with_the_a_prefix():
    ce.set_table({'seemsgoodmelisa': ('111', True), 'JohnShades': '222'})
    got = [texts(ce.apply(card('### ✅ Done')))[0] for _ in range(2)]
    assert got == ['### <a:seemsgoodmelisa:111> Done', f'### {JOHN} Done']


# ---------------------------------------------------------------- what is left alone

def test_a_message_in_the_old_layout_comes_back_as_it_was():
    old = {'content': '### ✅ Done 🦆', 'embeds': [{'title': '✅ Done 🦆'}], 'components': [row(button('Duck', '🦆'))]}
    ce.set_table(ALL)
    assert ce.apply(old) is old and old['content'] == '### ✅ Done 🦆'
    assert ce.apply(None) is None and ce.apply('🦆') == '🦆'


def test_the_message_passed_in_is_never_changed():
    ce.set_table(ALL)
    data = card('### ✅ Done 🦆', rows=[row(button('Duck', '🦆'))])
    before = copy.deepcopy(data)
    out = ce.apply(data)
    assert data == before and out != data


# ---------------------------------------------------------------- the list from Discord

class Reply:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


ITEMS = {'items': [{'id': '555', 'name': 'duck', 'animated': False}, {'id': '666', 'name': 'Rocky', 'animated': True},
                   {'id': 'x', 'name': 'bad id'}, {'id': '7'}, {'id': '8', 'name': 'JohnShades'}]}


def configure(monkeypatch, reply):
    monkeypatch.setenv('DISCORD_BOT_TOKEN', ' secret ')
    monkeypatch.setenv('DISCORD_APPLICATION_ID', '42')
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(ce.requests, 'get', get)
    return calls


def test_refresh_reads_the_application_emoji_with_the_bot_token(monkeypatch):
    calls = configure(monkeypatch, Reply(200, ITEMS))
    assert ce.refresh() is True
    assert calls == [('https://discord.com/api/v10/applications/42/emojis', {'Authorization': 'Bot secret'}, ce.TIMEOUT)]
    assert texts(ce.apply(card('🦆 🪨 ### ✅ x'))) == [f'{DUCK} <a:Rocky:666> ### ✅ x']
    assert texts(ce.apply(card('### ✅ x'))) == ['### <:JohnShades:8> x']          # only the found one of the pair


@pytest.mark.parametrize('reply', [Reply(401, {}), Reply(200, ValueError('no json')), Reply(200, {'items': 'nope'}),
                                   Reply(200, []), OSError('down')])
def test_a_failed_refresh_keeps_the_old_list_and_warns_once(monkeypatch, caplog, reply):
    ce.set_table({'duck': '555'})
    configure(monkeypatch, reply)
    with caplog.at_level(logging.WARNING, logger=ce.log.name):
        assert ce.refresh() is False
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    assert 'secret' not in caplog.text
    assert texts(ce.apply(card('🦆'))) == [DUCK]


@pytest.mark.parametrize('env', [{}, {'DISCORD_APPLICATION_ID': '42'}])
def test_without_a_bot_token_nothing_starts(monkeypatch, env):
    def no_thread(*a, **k):
        pytest.fail('thread started')
    monkeypatch.setattr(ce, 'threading', SimpleNamespace(Thread=no_thread))
    monkeypatch.setattr(ce.requests, 'get', lambda *a, **k: pytest.fail('network used'))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert texts(ce.apply(card('### ✅ Done 🦆'))) == ['### ✅ Done 🦆']
    assert ce.refresh() is False


def test_a_stale_list_starts_one_background_refresh_and_the_send_does_not_wait(monkeypatch):
    configure(monkeypatch, Reply(200, ITEMS))
    started = []

    class Later:
        def __init__(self, target=None, **kw):
            started.append((target, kw))

        def start(self):
            pass                                    # never runs: the send must not depend on it
    monkeypatch.setattr(ce, 'threading', SimpleNamespace(Thread=Later))
    for _ in range(3):
        assert texts(ce.apply(card('🦆'))) == ['🦆']
    assert len(started) == 1 and started[0][1]['daemon'] is True


def test_the_background_refresh_fills_the_list_for_later_sends(monkeypatch):
    configure(monkeypatch, Reply(200, ITEMS))
    release = threading.Event()
    monkeypatch.setattr(ce.requests, 'get', lambda *a, **k: release.wait(5) and Reply(200, ITEMS))   # a slow Discord
    assert texts(ce.apply(card('🦆'))) == ['🦆']            # cold: used what was cached (nothing), without waiting
    release.set()
    deadline = time.time() + 5
    while (ce._running or not ce._table) and time.time() < deadline:
        time.sleep(0.01)
    assert texts(ce.apply(card('🦆'))) == [DUCK]
    assert not [t for t in threading.enumerate() if t.name == 'custom-emoji' and t.is_alive()]


def test_a_fresh_list_is_not_fetched_again_and_a_failure_waits_before_retrying(monkeypatch):
    def no_thread(*a, **k):
        pytest.fail('started a refresh')
    configure(monkeypatch, Reply(200, ITEMS))
    ce.refresh()
    monkeypatch.setattr(ce, 'threading', SimpleNamespace(Thread=no_thread))
    ce.apply(card('🦆'))                                   # fresh: nothing to do
    ce.reset()
    calls = configure(monkeypatch, Reply(500, {}))
    ce.refresh()
    ce.apply(card('🦆'))                                   # right after a failure: no new attempt yet
    assert len(calls) == 1


# ---------------------------------------------------------------- where it is hooked in

RECEIPT = {'embeds': [{'title': '✅ Crafted Iron Nails', 'description': 'Iron Nails ×4 🦆', 'color': 0x57F287}],
           'components': [row(button('Again', '🦆'))]}


def test_a_new_message_ends_with_the_custom_emoji_in_its_heading():
    ce.set_table(ALL)
    data = v2.new_message(copy.deepcopy(RECEIPT))
    assert v2.is_v2(data) and f'### {MELISA} Crafted Iron Nails' in v2.text_of(data)
    assert '✅' not in v2.text_of(data) and f'Iron Nails ×4 {DUCK}' in v2.text_of(data)
    assert v2.controls(data)[0]['emoji']['id'] == '555'
    assert f'### {JOHN} Crafted Iron Nails' in v2.text_of(v2.new_message(copy.deepcopy(RECEIPT)))


def test_a_failed_receipt_gets_the_failed_emoji():
    ce.set_table(ALL)
    data = v2.new_message({'embeds': [{'title': '❌ Mining failed', 'description': 'Nothing found.'}]})
    assert f'### {ANDY} Mining failed' in v2.text_of(data)


def test_answers_and_edits_get_it_too():
    ce.set_table(ALL)
    answer = v2.respond({'type': 4, 'data': copy.deepcopy(RECEIPT)})
    assert f'### {MELISA} Crafted Iron Nails' in v2.text_of(answer['data'])
    edited = v2.respond({'type': 7, 'data': copy.deepcopy(RECEIPT)}, {'message': {'flags': v2.FLAG}})
    assert f'### {JOHN} Crafted Iron Nails' in v2.text_of(edited['data'])
    assert f'### {MELISA} Crafted Iron Nails' in v2.text_of(v2.edit(copy.deepcopy(RECEIPT), {'message': {'flags': v2.FLAG}}))
    assert f'### {JOHN} Crafted Iron Nails' in v2.text_of(v2.edit(copy.deepcopy(RECEIPT)))


def test_a_message_that_stays_in_the_old_layout_is_not_touched():
    ce.set_table(ALL)
    answer = v2.respond({'type': 7, 'data': copy.deepcopy(RECEIPT)}, {'message': {'flags': 0}})
    assert answer['data']['embeds'][0]['title'] == '✅ Crafted Iron Nails' and 'flags' not in answer['data']
    assert v2.edit(copy.deepcopy(RECEIPT), {'message': {'flags': 0}}) is None


def test_queue_alerts_get_it():
    ce.set_table(ALL)
    body = worker.v2_body(copy.deepcopy(RECEIPT), '<@1> Your queue has finished.', SimpleNamespace(id='abc', recipient='1'))
    assert f'### {MELISA} Crafted Iron Nails' in v2.text_of(body) and body['allowed_mentions']['users'] == ['1']


def test_guide_panels_get_it(monkeypatch):
    from app import guide_panels
    ce.set_table(ALL)
    monkeypatch.setattr(guide_panels, 'card', lambda panel: card('Panel 🦆'))
    assert v2.text_of(guide_panels.bodies()[0]) == f'Panel {DUCK}'


# ---------------------------------------------------------------- no DISCORD_APPLICATION_ID on the game service

def answers(monkeypatch, replies):
    """Only the bot token is set; each GET gets the reply for its URL (and is recorded)."""
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'secret')
    monkeypatch.delenv('DISCORD_APPLICATION_ID', raising=False)
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(url)
        return replies[url]
    monkeypatch.setattr(ce.requests, 'get', get)
    return calls


def test_without_an_application_id_the_bot_asks_discord_for_it_once(monkeypatch):
    calls = answers(monkeypatch, {ce.ME: Reply(200, {'id': '42', 'name': 'New Eridian V2'}),
                                  ce.URL.format(app='42'): Reply(200, ITEMS)})
    assert ce.refresh() is True and ce.refresh() is True
    assert calls == [ce.ME, ce.URL.format(app='42'), ce.URL.format(app='42')]
    assert texts(ce.apply(card('🦆'))) == [DUCK]


@pytest.mark.parametrize('me', [Reply(401, {}), Reply(200, {'id': 'nope'}), Reply(200, {})])
def test_when_the_application_id_cannot_be_learned_the_refresh_fails_and_warns(monkeypatch, caplog, me):
    calls = answers(monkeypatch, {ce.ME: me})
    with caplog.at_level(logging.WARNING, logger=ce.log.name):
        assert ce.refresh() is False
    assert calls == [ce.ME] and 'secret' not in caplog.text
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_a_missing_bot_token_is_warned_about_once(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger=ce.log.name):
        for _ in range(3):
            ce.apply(card('🦆'))
            ce.refresh()
    assert [r.getMessage() for r in caplog.records] == ['Custom emoji are off: DISCORD_BOT_TOKEN is missing on this service']


def test_the_log_says_which_emoji_are_not_uploaded_yet_and_only_when_that_changes(monkeypatch, caplog):
    configure(monkeypatch, Reply(200, ITEMS))
    with caplog.at_level(logging.INFO, logger=ce.log.name):
        ce.refresh()
        ce.refresh()
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ['Custom emoji: 3 loaded from Discord; not uploaded yet: seemsgoodmelisa, andyevillaugh, JJhydrate']
    caplog.clear()
    every = [{'id': str(i), 'name': n} for i, n in enumerate(ALL, 1)]
    configure(monkeypatch, Reply(200, {'items': every}))
    with caplog.at_level(logging.INFO, logger=ce.log.name):
        ce.refresh()
    assert [r.getMessage() for r in caplog.records] == ['Custom emoji: 6 loaded from Discord; every emoji in PICKS is there']


def test_the_log_lines_reach_uvicorns_handler():
    assert ce.log.name.startswith('uvicorn.error.')
