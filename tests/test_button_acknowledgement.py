"""Every press and form is acknowledged before any game work, so Discord never reports
"This interaction failed" (it allows 3 seconds); the answer follows right after."""
import json
import pytest
from nacl.signing import SigningKey
from test_colony import m, reset, client
from test_workbench_ui import citizen
from test_layout_v2 import assert_valid
from app import ui, menu, layout_v2 as v2, discord_deferred as deferred

PRIVATE = {'flags': 64 | v2.FLAG}
SHARED = {'flags': v2.FLAG}


class Reply:
    status_code, text = 200, ''

    def json(self):
        return {}


@pytest.fixture
def discord(monkeypatch):
    citizen()
    key = SigningKey.generate()
    monkeypatch.setattr(m, 'DISCORD_PUBLIC_KEY', key.verify_key.encode().hex())
    monkeypatch.setattr(m, 'DISCORD_GAME_CHANNEL_ID', '')
    sent = []
    monkeypatch.setattr(deferred.requests, 'patch', lambda url, json=None, timeout=None: sent.append(('edit', json)) or Reply())
    monkeypatch.setattr(deferred.requests, 'post', lambda url, json=None, timeout=None, **kw: sent.append(('new', json)) or Reply())

    def press(custom_id, message=PRIVATE, uid='111', kind=3, values=()):
        payload = {'type': kind, 'id': '1', 'application_id': 'app', 'token': 'tok', 'channel_id': '5',
                   'member': {'user': {'id': uid, 'username': 'Kam'}}, 'message': message,
                   'data': {'custom_id': custom_id, 'values': list(values), 'component_type': 2}}
        body = json.dumps(payload).encode()
        signature = key.sign(b'1' + body).signature.hex()
        before = len(sent)
        response = client.post('/discord/interactions', content=body,
                               headers={'X-Signature-Ed25519': signature, 'X-Signature-Timestamp': '1', 'Content-Type': 'application/json'})
        assert response.status_code == 200, response.text
        return response.json(), sent[before:]          # the test client runs the background work before returning
    return press


def test_a_press_on_a_private_panel_is_acknowledged_then_the_panel_changes(discord):
    ack, sent = discord(ui.cid('111', 'mn', 'work'))
    assert ack == {'type': 6}
    assert [k for k, _ in sent if k == 'edit'] == ['edit']
    edit = next(body for k, body in sent if k == 'edit')
    assert assert_valid(edit) and 'Work' in v2.text_of(edit)


def test_a_press_on_a_shared_message_answers_privately(discord):
    ack, sent = discord(ui.cid(ui.PUBLIC, 'mn', 'work'), message=SHARED)
    assert ack == {'type': 5, 'data': {'flags': 64}}                         # "thinking…", only for the presser
    edit = next(body for k, body in sent if k == 'edit')
    assert assert_valid(edit) and 'Work' in v2.text_of(edit)


def test_someone_elses_panel_gets_a_private_note_below_it(discord):
    ack, sent = discord(ui.cid('111', 'mn', 'work'), uid='222')
    assert ack == {'type': 6}
    assert [k for k, _ in sent] == ['new']
    note = sent[0][1]
    assert note['flags'] & 64 and 'belongs to another citizen' in v2.text_of(note)


def test_forms_still_open_at_once(discord):
    form = next(c['custom_id'] for area in menu.AREAS for c in v2.controls(
        v2.convert(ui.handle_component({'type': 3, 'data': {'custom_id': ui.cid('111', 'mn', area)},
                                           'member': {'user': {'id': '111', 'username': 'Kam'}}, 'message': {'flags': 64}})['data']) or {})
        if '|mo|' in str(c.get('custom_id')))
    ack, sent = discord(form)
    assert ack['type'] == 9 and not sent


def test_a_failure_is_reported_privately_and_nothing_else_runs(discord, monkeypatch):
    ran = []

    def broken(payload, schedule=None):
        schedule(lambda *a: ran.append(a))
        raise RuntimeError('boom')
    monkeypatch.setattr(ui, 'handle_component', broken)
    ack, sent = discord(ui.cid('111', 'mn', 'work'))
    assert ack == {'type': 6} and not ran
    assert [k for k, _ in sent] == ['new'] and 'nothing was spent' in v2.text_of(sent[0][1])


def test_an_action_button_does_its_work_after_the_acknowledgement(discord):
    ticket = ui.issue('111', {'do': 'cmd', 'leaf': 'relax'})
    ack, sent = discord(ui.cid('111', 't', ticket))
    assert ack == {'type': 6}
    assert [k for k, _ in sent][:1] == ['edit'] and '+25 Energy' in v2.text_of(sent[0][1])
    ack, sent = discord(ui.cid('111', 't', ticket))                          # a used button says so, privately
    assert ack == {'type': 6} and [k for k, _ in sent] == ['new']
