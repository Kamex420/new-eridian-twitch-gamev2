"""Stream highlights, overlay extras and the new OBS panels."""
from test_colony import m, reset, client, seed
from app import stream_overlay as so, task_queue as q
from test_task_queue import enqueue, advance

W = m.DISCORD_WORLD_ID


def overlay():
    return client.get('/api/v1/overlay', params={'channel': 'test'}).json()


def titles():
    return [h['title'] for h in overlay()['highlights']]


def test_new_citizens_and_events_become_highlights():
    seed(uid='u', provider='twitch', name='Kamex')
    with m.SessionLocal() as db:
        w = m.world(db, W)
        m.start_event(db, w, 'food', 'test')
        m.cancel_event(db, w, 'mod')
    found = titles()
    assert 'Kamex arrived in New Eridian' in found
    assert any('has started' in t for t in found) and any('called off' in t for t in found)
    first = overlay()['highlights'][0]
    assert {'id', 'kind', 'emoji', 'title', 'detail', 'at'} <= set(first)


def test_level_ups_achievements_and_finished_queues_are_highlighted():
    seed(uid='u', provider='twitch', name='Kamex')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(twitch_uid='u').one()
        m.announce(db, p, 'LEVEL UP: Kamex — Crafting aptitude Lv. 1 → Lv. 2', m.now())
        so.highlight(db, p.channel_id, 'achievement', 'Kamex earned an achievement', 'First Masterwork', 'Kamex')
        db.commit()
    enqueue(count=3)
    for _ in range(4):
        advance()
    found = titles()
    assert 'Kamex levelled up' in found and 'Kamex earned an achievement' in found
    assert any('finished a queue' in t for t in found)


def test_overlay_reports_working_queues_leaders_and_join_tips():
    enqueue(count=5)
    data = overlay()
    assert data['working'] and data['working'][0]['total'] == 5
    assert data['leaders']['active_today'] is not None and 'contributors' in data['leaders']
    assert any(t[0] == '!start' for t in data['join']['tips'])
    assert data['overlay_version'] == '6.4.0' and 'stats' in data      # the old contract is intact


def test_society_milestones_are_announced_once():
    with m.SessionLocal() as db:
        so.watch(m, db, W, 'Outpost', {}, {}, {})
        so.watch(m, db, W, 'Settlement', {'key': 'kitchen', 'name': 'Community Kitchen', 'completed': True, 'goal': 160}, {}, {})
        so.watch(m, db, W, 'Settlement', {'key': 'kitchen', 'name': 'Community Kitchen', 'completed': True, 'goal': 160}, {}, {})
        db.commit()
        rows = [r.title for r in db.query(so.StreamHighlight)]
    assert rows.count('New Eridian is now a Settlement!') == 1
    assert rows.count('Project complete: Community Kitchen') == 1


def test_highlights_are_capped():
    with m.SessionLocal() as db:
        for i in range(so.KEEP + 15):
            so.highlight(db, W, 'join', f'citizen {i}')
        db.commit()
        assert db.query(so.StreamHighlight).count() == so.KEEP


def test_new_obs_panels_and_setup_page_are_served():
    for panel in so.PANELS:
        page = client.get(f'/obs/{panel}', params={'channel': 'test'})
        assert page.status_code == 200 and '/api/v1/overlay' in page.text
        assert client.get('/overlay', params={'panel': panel, 'channel': 'test'}).status_code == 200
    setup = client.get('/obs', params={'channel': '<b>x</b>'})
    assert setup.status_code == 200 and '<b>x</b>' not in setup.text and '/obs/alerts' in setup.text
    assert 'Live highlight alerts' in client.get('/overlay', params={'channel': 'test'}).text
    assert client.get('/obs/nope').status_code == 404


def test_hub_rotates_every_panel_and_setup_recommends_four_sources():
    page = client.get('/obs/hub', params={'channel': 'test'}).text
    for slide in ('society', 'stats', 'today', 'event', 'projects', 'market', 'leaders', 'working', 'seedlings', 'news', 'join'):
        assert f"['{slide}'," in page
    setup = client.get('/obs', params={'channel': 'test'}).text
    assert 'Recommended: four sources carry everything' in setup
    first = [so.SOURCES[i][0] for i in range(4)]
    assert first == ['hub', 'map', 'ticker', 'alerts']


def test_every_overlay_page_shares_the_fonts_and_design_tokens():
    from test_colony import client
    for path in ('/obs/hub', '/obs/map', '/obs/ticker', '/obs/alerts', '/obs/narrator', '/obs/leaders', '/obs/society', '/obs/telemetry', '/obs', '/overlay'):
        html = client.get(path, params={'channel': 'test'}).text
        assert 'family=Fredoka' in html and '--font-display' in html and '--ease' in html, path
        assert 'Georgia' not in html, path
    legacy = client.get('/obs/society', params={'channel': 'test'}).text
    assert 'h1{font-family:var(--font-display)' in legacy


def test_ticker_tags_every_item_and_the_map_has_stats_characters_and_quality():
    from test_colony import client
    ticker = client.get('/obs/ticker', params={'channel': 'test'}).text
    assert "WEATHER" in ticker and "MARKET" in ticker and 'id="clock"' in ticker
    page = client.get('/obs/map', params={'channel': 'test'}).text
    for feature in ('function statPanel(', 'const HAT=', 'function face(', 'function idle(', "Q.get('quality')", "Q.get('stats')", '.q-low', 'function flag(',
                    'function fitHome(', 'function tidyLabels(', 'function hushBubble(', 'function dropBubbleIfHidden('):
        assert feature in page, feature


def test_hub_and_map_adapt_to_side_columns_and_bands():
    from test_colony import client
    hub = client.get('/obs/hub', params={'channel': 'test'}).text
    for feature in ("'strip'", "'compact'", "'tall'", 'const STRIP=', 'function fit(', '.L-compact .hub', '.L-strip .hub'):
        assert feature in hub, feature
    page = client.get('/obs/map', params={'channel': 'test'}).text
    for feature in ('const CARD=', '.L-card .cap', 'place_(', 'closeUp'):
        assert feature in page, feature


def test_no_overlay_code_is_hidden_behind_a_line_comment():
    """A '//' comment in the middle of a minified line silently disables the rest of it (the map once stopped loading this way)."""
    import re
    from app import stream_overlay as o
    for name, (css, body) in o.PAGES.items():
        for line in body.split('\n'):
            for m in re.finditer(r'(?<![:\\])//(.*)$', line):   # not a URL and not the end of a /regex\//
                assert not re.search(r'\b(const|let|function|return)\b|[;{}]\s*[A-Za-z_$][\w$.]*\s*[=(]', m.group(1)), (name, line[:160])


def test_hub_never_cuts_text_off():
    """Long lines wrap and the slide shrinks (or drops trailing list entries) instead of ending in an ellipsis."""
    from test_colony import client
    hub = client.get('/obs/hub', params={'channel': 'test'}).text
    assert '.hub .grow,.hub .ell' in hub and 'text-overflow:clip' in hub
    assert 'lastElementChild.remove()' in hub and 'Math.ceil(W)+1' in hub


def test_setup_page_lets_the_streamer_set_any_size_and_layout():
    from test_colony import client
    page = client.get('/obs', params={'channel': 'test'}).text
    assert 'data-k="w"' in page and 'data-k="h"' in page and 'data-p="layout"' in page
    assert 'localStorage' in page and 'Any size you like' in page


def test_map_scenery_fills_any_source_shape():
    from test_colony import client
    page = client.get('/obs/map', params={'channel': 'test'}).text
    assert '#map{overflow:visible}' in page and 'gradientUnits="userSpaceOnUse"' in page and 'class="vig"' in page


def test_map_relayouts_on_resize_and_leaves_stats_to_the_hub():
    from test_colony import client
    page = client.get('/obs/map', params={'channel': 'test'}).text
    assert "if(wantCard()!==CARD||" in page and "L-narrow" in page and "if(Q.get('stats')!=='1')" in page


def test_setup_page_has_controls_for_every_overlay_option():
    import re
    from test_colony import client
    from app import stream_overlay as o
    page = client.get('/obs', params={'channel': 'test'}).text
    for key, (css, body) in o.PAGES.items():
        used = set(re.findall(r"Q\.get\('(\w+)'\)", body)) - {'phase', 'days'}   # phase/days: covered by hour and holiday
        offered = {opt['p'] for opt in o.OPTIONS.get(key, [])}
        assert used <= offered, (key, used - offered)
    assert page.count('data-p="') >= sum(len(v) for v in o.OPTIONS.values())


def test_map_greets_newcomers_and_keeps_them_visible():
    from test_colony import client
    page = client.get('/obs/map', params={'channel': 'test'}).text
    assert 'function welcomeNew(' in page and 'isNew(b)-isNew(a)' in page and 'I just moved in' in page


def test_every_overlay_script_parses():
    """A stray bracket stops a whole OBS page from loading; check every page's JavaScript with Node when it is installed."""
    import re, shutil, subprocess, tempfile, pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    from test_colony import client
    for panel in so.PANELS:
        html = client.get(f'/obs/{panel}', params={'channel': 'test'}).text
        for i, script in enumerate(re.findall(r'<script>(.*?)</script>', html, re.S)):
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
                f.write(script)
            result = subprocess.run([node, '--check', f.name], capture_output=True, text=True)
            assert result.returncode == 0, (panel, i, result.stderr[:400])
