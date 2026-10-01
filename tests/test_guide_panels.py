"""The coloured guide panels and the moderator command that posts them."""
from types import SimpleNamespace
from test_colony import m, reset
from app import guide_panels as g


def test_every_ansi_panel_fits_one_message():
    panels = g.messages()
    assert len(panels) == len(g.PANELS) == 16
    for text in panels:
        assert text.startswith('```ansi\n') and text.endswith('\n```') and len(text) <= 2000
        assert g.TITLE + '╭' in text and g.HEADING in text and g.COMMAND in text and g.FLOW in text
        assert all(len(line.split('m', 1)[-1]) <= g.WIDTH + 2 for line in text.splitlines()[4:-1] if line.startswith(g.ESC))


def test_posting_needs_a_token_and_sends_every_panel(monkeypatch):
    assert g.post('123', token='') == 0
    sent = []
    monkeypatch.setattr(g.time, 'sleep', lambda s: None)
    monkeypatch.setattr(g.requests, 'post', lambda url, **kw: sent.append((url, kw['json'])) or SimpleNamespace(status_code=200))
    assert g.post('123', token='x') == len(g.PANELS)
    assert all(url.endswith('/channels/123/messages') for url, _ in sent)
    from app import layout_v2
    assert all(layout_v2.is_v2(body) and body['allowed_mentions'] == {'parse': []} for _, body in sent)   # cards, like every reply
    sent.clear()
    monkeypatch.setattr(layout_v2, 'ENABLED', False)
    assert g.post('123', token='x') == len(g.PANELS)
    assert [body['content'] for _, body in sent] == g.messages()                                        # the coloured blocks


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


def test_newcomer_panels_come_first_and_start_from_zero():
    titles = [panel[0] for panel in g.PANELS]
    assert titles[:4] == ['New here? Read this first', 'Words you will see', 'Your first 10 minutes', 'Questions new players ask']
    assert g.PANELS[:len(g.NEWCOMER_PANELS)] == g.NEWCOMER_PANELS
    first, words, steps, faq = g.messages()[:4]
    assert 'SEED by Klang Games' in first and 'You do not need to know SEED' in first and '!start' in first and '/start' in first
    for term in ('Avesta', 'Seedling', 'SC · Seed Coin', 'Seed Industries', 'Contribution', 'Queue'):
        assert term in words
    # The welcome kit and the Campfire recipe the walkthrough relies on.
    from app import onboarding
    assert onboarding.WELCOME_KIT == {'Lumber': 2, 'Berries': 4} and '2 Lumber and 4 Berries' in steps
    for command in ('/start', '/job', '/gather', '/make', '/life', 'Queue 5', '/seedling', '/guide', '!start'):
        assert command in steps
    assert 'Settled In' in steps and '/find' in faq


def test_every_panel_is_a_valid_card():
    from app import layout_v2
    for panel, body in zip(g.PANELS, g.bodies()):
        box = body['components'][0]
        texts = [c['content'] for c in box['components'] if c['type'] == layout_v2.TEXT]
        assert box['type'] == layout_v2.CONTAINER and len(box['components']) + 1 <= layout_v2.MAX_COMPONENTS
        assert sum(map(len, texts)) <= layout_v2.MAX_TEXT
        assert texts[0].startswith('## ' + panel[0]) and panel[3] in texts[-1].replace('`', '')
    first = layout_v2.text_of(g.bodies()[0])
    assert '`/start`' in first and '**Twitch chat · the lite version**' in first
    last = layout_v2.text_of(g.bodies()[-1])
    assert '🟩 Green: success and growth' in last and '`/vote`' in last
