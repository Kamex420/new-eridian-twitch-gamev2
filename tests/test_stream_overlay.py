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
        so.watch(db, W, 'Outpost', {}, {}, {})
        so.watch(db, W, 'Settlement', {'key': 'kitchen', 'name': 'Community Kitchen', 'completed': True, 'goal': 160}, {}, {})
        so.watch(db, W, 'Settlement', {'key': 'kitchen', 'name': 'Community Kitchen', 'completed': True, 'goal': 160}, {}, {})
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


# ---------------------------------------------------------------- the low-poly map, smaller Seedlings and an up-to-date overlay

def map_page():
    return client.get('/obs/map', params={'channel': 'test'}).text


def test_map_page_keeps_every_layer_and_id():
    page = map_page()
    for layer in ('sky0', 'sky1', 'sky2', 'stars', 'aurora', 'sun', 'skyclouds', 'hills', 'hills2', 'world', 'ground', 'shadows', 'city',
                  'festive', 'civic', 'crowd', 'shades', 'tint', 'haze', 'lights', 'labels', 'tokens', 'fx',
                  'wrap', 'stage', 'map', 'tier', 'hol', 'fest', 'info', 'toast', 'stats', 'cap'):
        assert f'id="{layer}"' in page, layer
    # the low-poly helpers: one light model shared by the ground, trees, rocks, water, the diorama's sides, the forest and the Kernel
    for helper in ('function shade(', 'function facetTile(', 'function lowPolyTree(', 'function facetRock(', 'function water(', 'function slab(',
                   'function forest(', 'function kernel(', 'function revolve(', 'const SUN=', 'function horizon('):
        assert helper in page, helper
    assert so.LOWPOLY_JS.strip() in page
    # the colony's look: lawn plots between concrete sidewalks with orange and purple plot lines, modules, farms of soil beds
    for part in ('function plots(', 'function plotLines(', 'function module_(', 'function domeHut(', 'function barrack(', 'function streetLamp(',
                 'function stringLights(', 'function neon(', 'function plaza(', "class:'crop'", 'const LAWN=', 'CONCRETE=[', "PLOT=['#e48a40','#9270dc']"):
        assert part in page, part


def test_seedlings_are_drawn_a_little_smaller():
    assert so.SEEDLING_SCALE == .72 and .7 <= so.SEEDLING_SCALE <= .75
    page = map_page()
    assert 'const SEEDLING_SCALE=0.72,TOKEN=CARD?1:SEEDLING_SCALE,TK=()=>TOKEN*TS' in page
    # tokens, their row spacing, the +N bubble and the speech bubble's head offsets all follow the token scale
    assert 'scale(${TK().toFixed(3)})' in page and '30*TK()' in page and 'Math.max(.85,z)' in page and 'const head=-38*z/k' in page



def test_the_column_card_keeps_seedlings_at_their_original_size():
    """The full map draws Seedlings at 0.72; the card (forced with &layout=card or picked from the size) keeps 1.0."""
    import re, shutil, subprocess
    page = map_page()
    line = re.search(r'^const SEEDLING_SCALE=.*$', page, re.M).group(0).split('   //')[0]
    assert 'TOKEN=CARD?1:SEEDLING_SCALE' in line and 'TK=()=>TOKEN*TS' in line
    assert page.index('const CARD=wantCard()') < page.index('const SEEDLING_SCALE=')   # the layout is known before the scale
    assert 'if(wantCard()!==CARD' in page and 'location.reload()' in page                # a resize that changes it reloads the page
    # nothing sizes a token from SEEDLING_SCALE directly: rows, the +N badge and bubbles all go through TK()
    assert page.count('SEEDLING_SCALE') == 3 and page.count('TK()') >= 10
    assert '.L-card .token .ini{font-size:11px}.L-card .token .label{font-size:11px;stroke-width:3.5px}' in page
    node = shutil.which('node')
    if node:
        for card, ts, want in ((True, 1, 1), (False, 1, .72), (True, 1.5, 1.5)):
            out = subprocess.run([node, '-e', f'const CARD={str(card).lower()};let TS={ts};{line};console.log(TK())'], capture_output=True, text=True)
            assert out.returncode == 0 and abs(float(out.stdout) - want) < 1e-9, (card, ts, out.stdout, out.stderr[:200])

def run_lowpoly(quality):
    """Run the map's low-poly helpers in Node with a stand-in for the SVG, and count the shapes each one draws."""
    import json, re, shutil, subprocess, tempfile, pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    page = map_page()
    rng_src = re.search(r'^function rng\(seed\).*$', page, re.M).group(0)
    js = (f'const QUALITY={json.dumps(quality)};const made=[];const el=(t,a,p)=>{{const e={{t,a:a||{{}},setAttribute(k,v){{this.a[k]=v}}}};made.push(e);return e}};'
          'const pts=p=>p.map(q=>q.join(",")).join(" ");' + rng_src + '\nconst N=20,TW=38,TH=19,OX=480,OY=64;const iso=(i,j)=>[OX+(i-j)*TW/2,OY+(i+j)*TH/2];\n'
          + so.LOWPOLY_JS + '\nconst count=f=>{const n=made.length;f();return made.length-n},r=rng("test"),g={};'
          'console.log(JSON.stringify({tile:count(()=>facetTile(g,2,3,["#7a9656","#8aa262"])),conifer:count(()=>lowPolyTree(g,100,100,r,"conifer")),'
          'broad:count(()=>lowPolyTree(g,100,100,r,"broad")),rock:count(()=>facetRock(g,100,100,5,r)),shrub:count(()=>shrub(g,100,100,4,r,"#55743a")),'
          'water:count(()=>water(g,100,100,40,20)),slab:count(()=>slab(g,-1.4,21.4)),forest:count(()=>forest(g,g)),'
          'snow:made.filter(e=>e.a["data-s"]).length,kernel:count(()=>kernel(g)),'
          'kparts:Object.fromEntries(["kring","kglow","kfoot","kdoor","kbody"].map(c=>[c,made.filter(e=>e.a.class===c).length])),'
          'shades:["top","left","right"].map(f=>shade("#808080",f))}))')
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
        f.write(js)
    result = subprocess.run([node, f.name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[:400]
    return json.loads(result.stdout)


def test_low_quality_draws_no_facets():
    page = map_page()
    assert "const FACETS=QUALITY!=='low',FINE=QUALITY==='high'" in page
    low, normal, high = run_lowpoly('low'), run_lowpoly('normal'), run_lowpoly('high')
    # low quality: one plain shape per tile, rock, shrub and pond, a single cone per conifer, three bands per side of the slab,
    # two flat tree lines on the horizon and a plainer Kernel, so the page stays as light as before
    assert low['tile'] == 1 and low['rock'] == 1 and low['shrub'] == 1 and low['water'] == 2 and low['conifer'] == 4 and low['broad'] == 3
    assert low['slab'] == 6 and low['forest'] == 8 and low['kernel'] <= 25 and low['kernel'] < normal['kernel'] <= 70
    assert normal['tile'] == 2 and high['tile'] == 4 and high['rock'] == 3 and high['water'] > 20 and high['slab'] > 40 and high['forest'] == 15
    for key in ('tile', 'conifer', 'broad', 'rock', 'shrub', 'water', 'slab', 'forest', 'kernel'):
        assert high[key] >= normal[key] > low[key] or high[key] >= normal[key] == low[key] == 1, key
    # one sun on the upper left: tops are lightest, left walls in between, right walls darkest
    light = [sum(int(v) for v in c[4:-1].split(',')) for c in high['shades']]
    assert light[0] > light[1] > light[2]



def test_the_mountains_are_gone_and_the_horizon_is_a_misty_forest():
    page = map_page()
    assert 'function mountains(' not in page and 'function ranges(' not in page and 'data-s' not in so.LOWPOLY_JS
    assert 'id="mistg"' in page and "for(const id of ['mist0','mist1'])" in page and "'data-l':l,'data-k':k" in so.LOWPOLY_JS
    for quality in ('low', 'normal', 'high'):
        assert run_lowpoly(quality)['snow'] == 0, quality      # no snow caps on any path


def test_the_kernel_stands_in_the_middle_with_its_ring_feet_and_door():
    page = map_page()
    assert "kernel(el('g',{id:'kernel'" in page and 'const KERNEL=[10.15,10.15]' in page
    assert "LOOK={commons:['🌱','The Kernel','#8ff3ff']" in page and '⛲' not in page    # the label reads THE KERNEL (uppercased when drawn)
    assert "const LABEL_AT={commons:[5,5]" in page and 'ROW_AT={commons:[12.5,12.5]}' in page   # its name floats behind the pod, its Seedlings gather in front
    assert '.q-high #kernel .kring{animation:kpulse' in page and "kg.style.setProperty('--glow'" in page   # pulses on high quality, brighter at night
    for quality in ('low', 'normal', 'high'):
        parts = run_lowpoly(quality)['kparts']
        assert parts['kfoot'] == 4 and parts['kdoor'] == 1 and parts['kbody'] == 1, (quality, parts)
        assert parts['kring'] >= 5 and parts['kglow'] >= 2, (quality, parts)   # the ring's visible arc, the hatch lights and the glows
    # the Kernel's middle stays free of buildings, and the walking paths reach its door
    assert "if(key==='commons'&&(i>a&&i<a+5&&j>b&&j<b+5||busy.has(i+','+j)))continue" in page
    assert "t.path=[KRAMP,...route('commons',k),[tx,ty]]" in page


def test_only_seedlings_new_during_the_session_step_out_of_the_kernel():
    import re, shutil, subprocess, pytest
    page = map_page()
    assert "if(fromKernel(s.id)){[t.x,t.y]=KDOOR;" in page and 'everSeen.add(s.id)' in page and 'spawnGlow()' in page
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    rule = re.search(r'^const fromKernel=.*?;', page, re.M).group(0)
    js = ('let first=true;const everSeen=new Set();' + rule + 'const out=[fromKernel("a")];everSeen.add("a");first=false;'
          'out.push(fromKernel("a"),fromKernel("b"));everSeen.add("b");out.push(fromKernel("b"));console.log(JSON.stringify(out))')
    out = subprocess.run([node, '-e', js], capture_output=True, text=True)
    # on the first render nobody spawns; later, someone already shown does not, a newcomer does, and only once
    assert out.returncode == 0 and out.stdout.strip() == '[false,false,true,false]', (out.stdout, out.stderr[:300])


def test_district_names_are_smaller_on_the_full_map_and_the_focus_option_is_offered():
    page = map_page()
    assert 'const LZ=CARD?1:.78' in page and 'z=LS*LZ' in page and "style:`font-size:${16*z}px`" in page
    setup = client.get('/obs', params={'channel': 'test'}).text
    assert 'data-p="focus"' in setup and "const FOCUS=CELLS[Q.get('focus')]" in page
    assert 'Kernel' in dict((k, t) for k, _, t, *_ in so.SOURCES)['map']

def test_every_panel_renders_and_the_setup_page_lists_it():
    setup = client.get('/obs', params={'channel': 'test'}).text
    listed = {key: (w, h) for key, title, text, w, h, params in so.SOURCES}
    assert so.PANELS <= set(listed)
    for key, (w, h) in listed.items():
        page = client.get(f'/obs/{key}', params={'channel': 'test'})
        assert page.status_code == 200 and '/api/v1/overlay' in page.text and '<script>' in page.text, key
        assert f'data-key="{key}" data-w="{w}" data-h="{h}"' in setup, key
    assert 'low-poly' in dict((k, t) for k, _, t, *_ in so.SOURCES)['map']


def _commands():
    import re
    from pathlib import Path
    from app import command_catalog
    text = (Path(__file__).parent.parent / 'integrations' / 'twitch' / 'ALL_COMMANDS.txt').read_text()
    return set(re.findall(r'^(![a-z0-9_]+)\s*$', text, re.M)), {'/' + c['name'] for c in command_catalog.commands}


def _named(text):
    import re
    return re.findall(r'(?<![\w/])([!/][a-z][a-z0-9_]*)', text)


def test_every_command_the_join_tips_name_exists(monkeypatch):
    twitch, discord = _commands()
    seen = []
    for lite in (False, True):
        monkeypatch.setattr(m.twitch_lite, 'ENABLED', lite)
        m._overlay_cache.clear()
        join = overlay()['join']
        for command, text in join['tips'] + [join['queue']]:
            for name in _named(command):
                assert name in (twitch if name[0] == '!' else discord), (lite, command)
                seen.append(name)
    assert '!start' in seen and '/menu' in seen and '/queue' in seen and '!shopping' in seen


def test_overlay_pages_only_name_commands_that_exist():
    """Hints written into the pages themselves (the ticker's vote and season, the working panel, the Hub, demo alerts)."""
    import re
    twitch, discord = _commands()
    for name, (css, body) in so.PAGES.items():
        for command in re.findall(r'(?:<b>|<code>|<b style="[^"]*">|[Tt]ype |with |\[\')(![a-z]+)', body):
            assert command in twitch, (name, command)


def test_newest_discord_features_are_named_but_never_shown_as_data(monkeypatch):
    import json
    from app import keep_levels, shopping_list, quiet_hours
    monkeypatch.setattr(m.twitch_lite, 'ENABLED', True)
    seed(uid='u', provider='twitch', name='Kamex')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(twitch_uid='u').one()
        assert 'Nothing changed' not in quiet_hours.set_hours(db, p, 'Europe/Berlin', '22:00', '07:00')
        key, problem = keep_levels.find_item('Iron Nails')
        assert key and 'Nothing changed' not in keep_levels.set_level(db, p, key, 37)
        assert 'Added to your shopping list' in shopping_list.add_typed(db, p, 'campfire', 3)
        db.commit()
        assert keep_levels.levels(db, p.channel_id, p.twitch_uid) and shopping_list.entries(db, p)
    data = overlay()
    tips = ' '.join(t[1] for t in data['join']['tips'])
    assert 'Shopping list' in tips and 'Always keep' in tips and 'Quiet hours' in tips
    page = client.get('/obs/join', params={'channel': 'test'}).text
    assert 'shopping lists, keep levels and quiet hours on Discord' in page
    def keys(v):
        if isinstance(v, dict):
            for k, x in v.items():
                yield k
                yield from keys(x)
        elif isinstance(v, list):
            for x in v:
                yield from keys(x)
    names = ' '.join(keys(data)).lower()
    for private in ('quiet', 'keep', 'shopping', 'merge', 'zone'):
        assert private not in names, private
    text = json.dumps({k: v for k, v in data.items() if k != 'join'}).lower()
    for private in ('europe/berlin', 'quiet hours', 'keep level', 'shopping list', 'force merge'):
        assert private not in text, private


# ---------------------------------------------------------------- workstations, live pieces and the SEED-style look on the map

def craft_survival_bench():
    """A real craft of the free Basic Workbench recipe, which uses the Survival Workbench."""
    from app import seed_content as s
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'discord', 'new', 'Citizen')[1]
        key = next(k for k in s.MACHINE_RECIPES if s.ITEMS[k]['name'] == 'Basic Workbench')
        rid = next(k for k, r in s.RECIPES.items() if key in r['outputs'])
        for k, n in s.RECIPES[rid]['inputs'].items():
            for _ in range(n):
                db.query(m.Cooldown).delete()
                s.gather(db, p, k, 'discord')
        db.query(m.Cooldown).delete()
        assert 'CRAFTING COMPLETE' in s.craft(db, p, rid, 'discord')
    return rid


def test_overlay_names_the_workstations_the_world_has_crafted_with():
    from app import crafting_progression as cp
    assert overlay()['stations'] == []
    craft_survival_bench()
    stations = overlay()['stations']
    assert [x['tag'] for x in stations] == [cp.SURVIVAL] and stations[0]['name'] == 'Survival Workbench' and stations[0]['at']
    craft_survival_bench()          # the same station again is not a second entry
    assert len(overlay()['stations']) == 1


def test_station_use_is_recorded_once_per_world_and_never_breaks_a_craft():
    with m.SessionLocal() as db:
        so.station_used(db, 'test', 'TAG_MACHINE_KILN')
        so.station_used(db, 'test', 'TAG_MACHINE_KILN')
        so.station_used(db, W, 'TAG_MACHINE_OVEN')
        so.station_used(db, 'test', '')
        db.commit()
        assert db.query(so.StreamStation).count() == 2
        so.station_used(None, 'test', 'TAG_MACHINE_LOOM')       # a broken session is swallowed, like highlight()
    assert [x['tag'] for x in overlay()['stations']] == ['TAG_MACHINE_KILN', 'TAG_MACHINE_OVEN'] or {x['tag'] for x in overlay()['stations']} == {'TAG_MACHINE_KILN', 'TAG_MACHINE_OVEN'}
    assert all(x['name'] for x in overlay()['stations'])


def test_a_world_with_older_crafts_gets_its_stations_from_the_crafting_ledger():
    from app import crafting_progression as cp
    with m.SessionLocal() as db:
        db.add(m.CraftLedger(channel_id=W, canonical_uid='old', recipe='component', qty=3, best_quality=''))
        db.add(m.CraftLedger(channel_id=W, canonical_uid='old', recipe='no_such_recipe', qty=1, best_quality=''))
        db.commit()
    assert [x['tag'] for x in overlay()['stations']] == [cp.SURVIVAL]


def test_a_queued_craft_names_its_workstation_for_the_map():
    from app import seed_content as s, crafting_progression as cp
    rid = next(k for k, r in s.RECIPES.items() if cp.tags(k) == ['TAG_MACHINE_KILN'])
    assert so.working_station('make:' + rid, set()) == 'TAG_MACHINE_KILN'
    assert so.working_station('mine:iron', set()) == '' and so.working_station('make:no_such_recipe', set()) == ''
    rid2 = next(k for k, r in s.RECIPES.items() if len(cp.tags(k)) > 1)
    tags = cp.tags(rid2)
    built = {tags[-1]}
    assert so.working_station('make:' + rid2, built) == tags[-1]       # a station the colony has built wins
    queue = enqueue(task='make:' + rid, count=2)
    assert overlay()['working'][0]['station'] == 'TAG_MACHINE_KILN', queue


def test_the_live_event_tells_the_map_how_long_it_lasts():
    seed(uid='u', provider='twitch', name='Kamex')
    with m.SessionLocal() as db:
        m.start_event(db, m.world(db, W), 'fire', 'test')
    event = overlay()['event']
    assert event['key'] == 'fire' and event['seconds_total'] == 18 * 60 and 0 < event['seconds_remaining'] <= event['seconds_total']
    assert {'progress', 'goal', 'support_progress', 'name', 'emoji'} <= set(event)


def test_station_table_is_documented_and_created_at_startup():
    import re
    from pathlib import Path
    docs = Path(__file__).resolve().parent.parent / 'docs' / 'persistence.md'
    assert 'stream_stations_v1' in docs.read_text()
    assert so.StreamStation.__table__.name == 'stream_stations_v1'


STATION_KEYS_RE = r"^ (?:'?)([0-9A-Z_]+)(?:'?):\{d:'(\w+)',fx:'(\w+)'"


def test_the_map_has_a_building_for_every_kind_of_workstation_and_the_live_pieces():
    import re
    from app import crafting_progression as cp
    page = map_page()
    rows = re.findall(STATION_KEYS_RE, so.STATIONS_JS, re.M)
    keys = {k for k, _, _ in rows}
    real = {re.sub(r'^TAG_MACH(INE)?_', '', t) for t in cp.STATIONS}
    assert len(rows) == len(keys) >= 30 and keys <= real          # every station has its own silhouette, and only real SEED stations
    assert {d for _, d, _ in rows} == {'industrial_ward', 'agricultural_district', 'residential_ring', 'research_block', 'frontier_edge'}
    assert {fx for _, _, fx in rows} <= {'sparks', 'steam', 'dust'}
    assert so.STATIONS_JS.strip() in page and so.TOWN_JS.strip() in page
    for part in ('function stationsTown(', 'function workRings(', 'function eventSite(', 'function projectSite(', 'function marketBoard(', 'function shortages(',
                 'function honours(', 'function crowns(', 'function atStations(', 'function fixture(', 'function townLife(', 'id="live"', 'townLife(d);',
                 'function contact(', 'function doorway(', 'const FIXTURES='):
        assert part in page, part
    # the districts keep their reserved slots: workstations take the first slots, landmarks the last
    for district in ('industrial_ward', 'agricultural_district', 'residential_ring', 'research_block', 'frontier_edge'):
        listed = re.search(district + r":\[([^\]]*)\]", so.TOWN_JS).group(1)
        assert 0 < len(re.findall("'", listed)) // 2 <= 12
    assert 'const RESERVE=3;' in page and "fixture('commons','project',-5" in page and "fixture('commons','statue',-8" in page


def test_the_map_looks_different_in_each_district_and_has_depth():
    page = map_page()
    for part in ("CREAM=", "METAL=", "TIMBER=", "LOOK.industrial_ward[2]", "LOOK.research_block[2]", "LOOK.spaceport_quarter[2]", "LOOK.frontier_edge[2]",
                 "LOOK.residential_ring[2]", "LOOK.agricultural_district[2]", "glass:'#8fd6e2'", "roofColor:CANVAS"):
        assert part in page, part
    assert 'Districts differ by what stands on their plots, not by colour' not in page and 'materials' in page
    assert "QUALITY!=='low'&&opt.rim!==0" in page and 'rgba(8,12,18' in page      # a rim on lit roof edges (not on low quality) and soft contact shadows
    assert "if(CASTERS.some(c=>!c[2].isConnected))" in page                          # a building that is taken down stops casting


def run_stations(quality):
    """Draw every workstation in Node with a stand-in for the SVG; returns {station: [shapes, height, puffs]}."""
    import json, re, shutil, subprocess, tempfile, pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    page = map_page()
    rng_src = re.search(r'^function rng\(seed\).*$', page, re.M).group(0)
    line = lambda pattern: re.search(pattern, page, re.M).group(0)
    box_src = page[page.index('const CASTERS=[]'):page.index('function centre(')]
    drum_src = re.search(r'function drum\(.*?\n(?=// Crates)', page, re.S).group(0)
    js = (f'const QUALITY={json.dumps(quality)};const made=[];const el=(t,a,p)=>{{const e={{t,a:a||{{}},setAttribute(k,v){{this.a[k]=v}}}};made.push(e);return e}};'
          + rng_src + '\nconst N=20,TW=38,TH=19,OX=480,OY=64;const iso=(i,j)=>[OX+(i-j)*TW/2,OY+(i+j)*TH/2];\n' + so.LOWPOLY_JS + '\n'
          + line(r'^function diamond\(.*$') + '\n' + line(r'^const pts=.*$') + '\n' + line(r'^const up=.*$') + '\n' + line(r"^const vr=rng\('lamps'\);$") + '\n'
          + box_src + '\n' + drum_src + '\n' + so.STATIONS_JS + '\nconst out={};\n'
          'for(const k in ST){const n=made.length,h=ST[k].draw({},3,4,"#ff9a76",{});out[k]=[made.length-n,h,made.slice(n).filter(e=>e.a.class==="puff").length]}\n'
          'console.log(JSON.stringify(out))')
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
        f.write(js)
    result = subprocess.run([node, f.name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[:600]
    return json.loads(result.stdout)


def test_every_workstation_draws_at_every_quality_with_a_modest_shape_count():
    low, normal, high = run_stations('low'), run_stations('normal'), run_stations('high')
    assert set(low) == set(normal) == set(high) and len(high) >= 30
    for key in high:
        assert all(isinstance(v[key][1], (int, float)) and v[key][1] > 0 for v in (low, normal, high)), key       # each says how tall it stands, for its ring
        assert 4 <= low[key][0] <= normal[key][0] <= high[key][0] <= 60, (key, low[key][0], normal[key][0], high[key][0])
    assert sum(v[0] for v in high.values()) / len(high) < 30                                                       # about 20 shapes each, not hundreds
    assert sum(v[2] for v in low.values()) == 0 and sum(v[2] for v in normal.values()) > 0                         # no smoke puffs on low quality


def test_words_and_districts_pick_the_workstation_a_seedling_or_queue_uses():
    import json, re, shutil, subprocess, tempfile, pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    start = so.TOWN_JS.index('const WORDS=')
    end = so.TOWN_JS.index('const standing=')
    js = so.TOWN_JS[start:end] + ('\nconst pick=(text,built)=>{for(const [re,ids] of WORDS)if(re.test(text)){const id=ids.find(i=>built.includes(i));if(id)return id}return ""};'
                                  'console.log(JSON.stringify([pick("Smelt Iron Ingot",["FURNACE","BASIC_FURNACE"]),pick("Working: Bake bread",["STOVE","OVEN"]),'
                                  'pick("Training: Pottery",["POTTERY_STATION","KILN"]),pick("Gathering Lumber",["TABLE_SAW"]),pick("Mine Hematite Ore",["EXTRACTOR"]),'
                                  'pick("Make Weave cloth",["TAILORING_BENCH"]),pick("Sleeping",["CAMPFIRE"])]))')
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
        f.write(js)
    result = subprocess.run([node, f.name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[:400]
    assert json.loads(result.stdout) == ['FURNACE', 'OVEN', 'POTTERY_STATION', 'TABLE_SAW', 'EXTRACTOR', 'TAILORING_BENCH', '']
