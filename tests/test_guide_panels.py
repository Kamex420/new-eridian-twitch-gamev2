"""The coloured guide panels and the moderator command that posts them."""
from types import SimpleNamespace
from test_colony import m, reset
from app import guide_panels as g


def test_every_ansi_panel_fits_one_message():
    panels = g.messages()
    assert len(panels) == len(g.PANELS) == 12
    for text in panels:
        assert text.startswith('```ansi\n') and text.endswith('\n```') and len(text) <= 2000
        assert g.TITLE + '╭' in text and g.HEADING in text and g.COMMAND in text and g.FLOW in text
        assert all(len(line.split('m', 1)[-1]) <= g.WIDTH + 2 for line in text.splitlines()[4:-1] if line.startswith(g.ESC))


def test_posting_needs_a_token_and_sends_every_panel(monkeypatch):
    assert g.post('123', token='') == 0
    sent = []
    monkeypatch.setattr(g.time, 'sleep', lambda s: None)
    monkeypatch.setattr(g.requests, 'post', lambda url, **kw: sent.append((url, kw['json']['content'])) or SimpleNamespace(status_code=200))
    assert g.post('123', token='x') == len(g.PANELS)
    assert all(url.endswith('/channels/123/messages') for url, _ in sent)


def test_mod_command_posts_the_panels(monkeypatch):
    monkeypatch.setattr(g, 'post', lambda channel: len(g.PANELS))
    assert m.discord_legacy_route('mod', {'action': 'guidepanels'}) == ('guidepanels', {})
    assert f'Posted all {len(g.PANELS)}' in m._discord_call_internal('mod', 'u', 'Mod', {'action': 'guidepanels'}, 'i')


def test_the_command_list_explains_the_reply_colours_and_lists_the_new_commands():
    text = g.messages()[-1]
    assert 'COLOR MEANING' in text and 'GREEN = success and growth' in text and 'MAGENTA = social, story and lore' in text
    for command in ('/vote', '/challenge', '/season', '/trophies', '/seedling'):
        assert command in text


def test_the_holiday_panel_names_the_next_festival_when_posted():
    from app import seasonal
    text = next(t for t in g.messages() if 'Holidays & festival foods' in t)
    assert seasonal.next_holiday_window()['name'] in text
