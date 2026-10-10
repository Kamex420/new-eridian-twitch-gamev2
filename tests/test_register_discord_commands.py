"""The Discord registrar verifies what Discord saved and reports every difference before failing."""
import copy

import pytest

from app.command_catalog import commands
from scripts import register_discord_commands as registrar


class FakeResponse:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.text = status, data, ''
        self.ok = status < 400

    def json(self):
        return self._data


class FakeDiscord:
    """Accepts the PUT, then returns `saved` as the server's commands; records every call."""

    def __init__(self, saved, app_id='42'):
        self.headers, self.calls, self.saved, self.app_id = {}, [], saved, app_id

    def request(self, method, url, timeout=None, json=None):
        path = url.split('/api/v10', 1)[1]
        self.calls.append((method, path))
        if path == '/oauth2/applications/@me':
            return FakeResponse({'id': self.app_id, 'name': 'Test app'})
        if method == 'PUT':
            return FakeResponse(json)
        if method == 'GET' and '/guilds/' in path:
            return FakeResponse(self.saved)
        if method == 'GET':
            return FakeResponse([])
        return FakeResponse(None, 204)


def run_registrar(monkeypatch, saved):
    fake = FakeDiscord(saved)
    monkeypatch.setattr(registrar.requests, 'Session', lambda: fake)
    for key, value in {'DISCORD_APPLICATION_ID': '42', 'DISCORD_BOT_TOKEN': 'token', 'DISCORD_GUILD_ID': '7'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(registrar.sys, 'argv', ['register_discord_commands'])
    return fake


def choice(saved, command, option, value):
    row = next(c for c in saved if c['name'] == command)
    opt = next(o for o in row['options'] if o['name'] == option)
    return next(c for c in opt['choices'] if c['value'] == value)


def test_every_mismatch_is_logged_with_its_path_and_escaped_values(monkeypatch, capsys):
    saved = copy.deepcopy(commands)
    choice(saved, 'make', 'category', 'parts')['name'] = '⚙ Components'  # variation selector dropped
    next(c for c in saved if c['name'] == 'vote')['description'] = 'Changed'
    saved = [c for c in saved if c['name'] != 'trophies']
    fake = run_registrar(monkeypatch, saved)
    with pytest.raises(RuntimeError, match=r'Verification failed for /make, /vote, /trophies\. No global'):
        registrar.main()
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith('MISMATCH')]
    vote = next(c for c in commands if c['name'] == 'vote')['description']
    assert lines == [
        "MISMATCH /make › option 'category' › choices › choice 'parts' › name: "
        "catalog '\\u2699\\ufe0f Components' | Discord '\\u2699 Components'",
        f"MISMATCH /vote › description: catalog {ascii(vote)} | Discord 'Changed'",
        "MISMATCH /trophies: catalog 'trophies' | Discord <missing>",
    ]
    assert not any(method == 'DELETE' for method, _ in fake.calls)


def test_differences_names_added_missing_and_reordered_rows():
    catalog = {'name': 'x', 'description': 'd', 'options': [
        {'type': 3, 'name': 'a', 'description': 'A', 'choices': [{'name': 'One', 'value': '1'},
                                                                 {'name': 'Two', 'value': '2'}]},
        {'type': 4, 'name': 'b', 'description': 'B', 'min_value': 1}]}
    saved = copy.deepcopy(catalog)
    saved['options'].reverse()
    saved['options'][1]['choices'] = [{'name': 'One', 'value': '1'}, {'name': 'Three', 'value': '3'}]
    del saved['options'][0]['min_value']
    assert registrar.differences(catalog, saved) == [
        ("/x › option 'a' › choices › choice '2'", {'name': 'Two', 'value': '2'}, registrar.MISSING),
        ("/x › option 'a' › choices › choice '3'", registrar.MISSING, {'name': 'Three', 'value': '3'}),
        ("/x › option 'b' › min_value", 1, registrar.MISSING),
        ('/x › order', ['a', 'b'], ['b', 'a']),
    ]
    assert registrar.differences(catalog, copy.deepcopy(catalog)) == []
