"""Hardening: keys, the market, world locking, overlay safety, Seedling fairness, table growth and setup checks."""
import logging
import pytest
from test_colony import m, reset, client

W = m.DISCORD_WORLD_ID


# ---------------------------------------------------------------- keys

def test_moderator_commands_take_the_moderator_key_and_merges_still_need_the_admin_key(monkeypatch):
    monkeypatch.setattr(m, 'ADMIN_KEY', 'admin-secret')
    monkeypatch.setattr(m, 'MOD_KEY', 'mod-secret')
    started = client.get('/api/v1/admin/event/siro/on', params={'channel': W, 'level': 500, 'key': 'mod-secret'}).text
    assert 'STARTED' in started
    assert 'Invalid' in client.get('/api/v1/admin/event/siro/off', params={'channel': W, 'level': 500, 'key': 'wrong'}).text
    # ADMIN_KEY keeps working for moderator commands added before MOD_KEY existed.
    assert 'Invalid' not in client.get('/api/v1/admin/event/siro/off', params={'channel': W, 'level': 500, 'key': 'admin-secret'}).text
    merge = client.get('/api/v1/admin/merge', params={'channel': W, 'keep': 'a', 'merge': 'b', 'key': 'mod-secret'})
    assert merge.status_code == 403
    assert client.get('/api/v1/admin/duplicates', params={'channel': W, 'key': 'mod-secret'}).status_code == 403


def test_request_logs_hide_the_game_and_admin_keys():
    record = logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ('1.2.3.4', 'GET', '/api/v1/start?channel=c&uid=1&k=sekrit&name=x', '1.1', 200), None)
    admin = logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                              ('1.2.3.4', 'GET', '/api/v1/admin/day/next?channel=c&key=hunter2', '1.1', 200), None)
    for rec in (record, admin):
        assert m._RedactKeys().filter(rec)
    assert 'sekrit' not in record.getMessage() and 'k=***' in record.getMessage() and 'name=x' in record.getMessage()
    assert 'hunter2' not in admin.getMessage() and 'key=***' in admin.getMessage()


def test_health_warns_when_the_twitch_key_is_missing(monkeypatch):
    for name in ('queue_worker', 'notification_worker', 'discord_notification_worker', 'autonomy_worker'):
        monkeypatch.setattr(m.app.state, name, None, raising=False)     # other tests stop the workers
    monkeypatch.setattr(m, 'MOD_KEY', 'mod-secret')
    monkeypatch.delenv('TWITCH_API_KEY', raising=False)
    assert any('TWITCH_API_KEY' in w for w in m.health('mod-secret')['warnings'])
    assert 'warnings' not in m.health() and m.health()['warnings_count'] >= 1     # details need a key
    monkeypatch.setenv('TWITCH_API_KEY', 'set')
    assert not any('TWITCH_API_KEY' in w for w in m.health('mod-secret')['warnings'])


def test_health_warns_about_sqlite_on_a_hosted_platform(monkeypatch):
    monkeypatch.setenv('RAILWAY_ENVIRONMENT', 'production')
    assert any('DATABASE_URL' in w for w in m.config_warnings())
    monkeypatch.delenv('RAILWAY_ENVIRONMENT')
    assert not any('DATABASE_URL' in w for w in m.config_warnings())


# ---------------------------------------------------------------- market

def test_no_item_sells_for_as_much_as_it_costs_on_any_demand_day():
    for key, listing in m.SEED_INDUSTRIES.items():
        if not listing.get('buy') or not listing.get('sell'):
            continue
        for day in range(1, 120):
            assert m.demand_price(key, day) < listing['buy'], (key, day)


def test_buying_and_selling_back_on_a_demand_day_loses_sc(monkeypatch):
    hematite = m.seed_content.find_item('hematite ore')
    day = next(d for d in range(1, 400) if m.market_demand(W, d)[0] == hematite)
    monkeypatch.setattr(m, 'demand_day', lambda: day)
    assert m.SEED_INDUSTRIES[hematite]['sell'] < m.sale_price(hematite) < m.SEED_INDUSTRIES[hematite]['buy']   # still a demand bonus
    m.start(W, '111', 'Trader', 'discord')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).one(); p.sc = 150; db.commit()
    for _ in range(5):
        m.seed_industries(W, '111', 'Trader', 'buy', 'hematite ore', 25, 'discord')
        m.seed_industries(W, '111', 'Trader', 'sell', 'hematite ore', 25, 'discord')
    with m.SessionLocal() as db:
        assert db.query(m.Player).filter_by(channel_id=W).one().sc < 150


# ---------------------------------------------------------------- worlds and the overlay

def rows(table):
    with m.SessionLocal() as db:
        return db.query(table).count()


def test_reads_for_a_world_nobody_started_create_nothing():
    before = (rows(m.Society), rows(m.World))
    for path in ('/api/v1/society', '/api/v1/tick', '/api/v1/settlement', '/api/v1/event', '/api/v1/progress'):
        text = client.get(path, params={'channel': 'junk-world-never-started'}).text
        assert 'has not started' in text, path
    assert (rows(m.Society), rows(m.World)) == before


def test_a_player_command_founds_a_world_and_reads_then_work(monkeypatch):
    monkeypatch.delenv('TWITCH_API_KEY', raising=False)
    assert 'has not started' in client.get('/api/v1/society', params={'channel': 'fresh-world-1'}).text
    client.get('/api/v1/start', params={'channel': 'fresh-world-1', 'uid': 'p1', 'name': 'Founder'})
    assert 'has not started' not in client.get('/api/v1/society', params={'channel': 'fresh-world-1'}).text


def test_the_game_key_lets_streamelements_read_a_new_world(monkeypatch):
    monkeypatch.setenv('TWITCH_API_KEY', 'game-key')
    assert 'has not started' in client.get('/api/v1/society', params={'channel': 'fresh-world-2', 'k': 'nope'}).text
    assert 'has not started' not in client.get('/api/v1/society', params={'channel': 'fresh-world-2', 'k': 'game-key'}).text


def test_channel_names_longer_than_the_database_column_are_refused():
    text = client.get('/api/v1/start', params={'channel': 'x' * 65, 'uid': 'p1', 'name': 'Long'}).text
    assert 'too long' in text
    assert rows(m.Player) == 0


def test_the_overlay_for_an_unknown_channel_shows_the_main_world_without_flushing_the_cache(monkeypatch):
    monkeypatch.setattr(m, 'OVERLAY_CACHE_SECONDS', 60)
    m._overlay_cache.clear()
    main = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert main['ok']
    for i in range(60):
        assert client.get('/api/v1/overlay', params={'channel': f'junk-overlay-{i}'}).json()['ok']
    assert list(m._overlay_cache) == [W]                 # every unknown channel shared the main world's entry
    assert rows(m.Society) == 1


def test_the_overlay_cache_drops_its_oldest_entry_instead_of_emptying(monkeypatch):
    monkeypatch.setattr(m, 'OVERLAY_CACHE_SECONDS', 60)
    m._overlay_cache.clear()
    for i in range(52):
        m._overlay_cache[f'w{i}'] = (i, {'ok': True})
    m.overlay_state(W)
    assert W in m._overlay_cache and 'w0' not in m._overlay_cache and 'w51' in m._overlay_cache
    assert len(m._overlay_cache) <= 50


def test_every_world_shares_one_lock_key():
    from app import task_queue
    seen = []

    class Conn:
        class dialect:
            name = 'postgresql'

        def execute(self, statement, params):
            seen.append(params['key'])

    for channel in (W, '123456', None, 'other'):
        task_queue.lock_world(Conn(), channel)
    assert len(set(seen)) == 1


# ---------------------------------------------------------------- overlay pages

@pytest.mark.parametrize('path', ['/obs/alerts', '/obs/ticker', '/obs/leaders', '/obs/society', '/obs/telemetry', '/overlay', '/obs'])
def test_a_channel_name_cannot_inject_script_into_an_overlay_page(path):
    attack = '</script><script>alert(document.domain)</script>'
    html = client.get(path, params={'channel': attack}).text
    assert '<script>alert(' not in html
    assert '</script><script>' not in html.split('<script', 1)[-1].split('</script>', 1)[0]


def test_the_overlay_page_still_knows_its_channel():
    html = client.get('/obs/alerts', params={'channel': 'a<b>&c'}).text
    assert 'const CHANNEL="a'+'\\u003cb\\u003e\\u0026c"' in html


# ---------------------------------------------------------------- Seedlings

def test_every_seedling_gets_a_turn_when_there_are_more_than_one_batch_can_serve(monkeypatch):
    from datetime import timedelta
    from app import autonomy as a
    clock = [m.now()]
    monkeypatch.setattr(m, 'now', lambda: clock[0])
    with m.SessionLocal() as db:
        for i in range(a.BATCH * a.AUTONOMY_MINUTES * 2):
            db.add(m.Player(channel_id='c', twitch_uid=f'u{i:03d}', display_name=f'u{i}', last_seen=clock[0]))
        db.commit()
    served = set()

    def step(m_, channel, uid, force=False):
        served.add(uid)
        with m.SessionLocal() as db:
            a.row(db, channel, uid, create=True).next_at = m.now() + timedelta(minutes=a.AUTONOMY_MINUTES)
            db.commit()
    monkeypatch.setattr(a, 'live_one', step)
    for _ in range(a.AUTONOMY_MINUTES * 4 + 2):
        a.tick(m)
        clock[0] += timedelta(minutes=1)
        with m.SessionLocal() as db:
            db.query(m.Player).update({m.Player.last_seen: clock[0]}); db.commit()
    assert len(served) == a.BATCH * a.AUTONOMY_MINUTES * 2


# ---------------------------------------------------------------- table growth

def test_hot_queries_have_indexes():
    from sqlalchemy import inspect
    found = {i['name'] for t in ('action_logs_v5', 'journal_v54', 'discord_command_receipts_v1', 'link_codes_v4')
             for i in inspect(m.engine).get_indexes(t)}
    assert {'ix_action_logs_channel_created', 'ix_journal_owner_created', 'ix_command_receipts_created', 'ix_link_codes_expires'} <= found


def test_cleanup_removes_old_rows_and_keeps_recent_ones(monkeypatch):
    from datetime import timedelta
    from app import maintenance
    from app.discord_execution import CommandReceipt
    monkeypatch.setattr(maintenance, 'BATCH', 7)          # several batches
    now = m.now()
    with m.SessionLocal() as db:
        for i in range(30):
            db.add(m.ActionLog(channel_id=W, canonical_uid='u', action='farm', response='x', created_at=now - timedelta(days=30)))
        db.add(m.ActionLog(channel_id=W, canonical_uid='u', action='farm', response='today', created_at=now))
        db.add(CommandReceipt(interaction_id='old', fingerprint='f', result='r', created_at=now - timedelta(days=5)))
        db.add(CommandReceipt(interaction_id='new', fingerprint='f', result='r', created_at=now))
        db.add(m.LinkCode(channel_id=W, canonical_uid='u', code='OLD111', expires_at=now - timedelta(days=3)))
        db.add(m.LinkCode(channel_id=W, canonical_uid='u', code='NEW111', expires_at=now + timedelta(minutes=10)))
        for i in range(30):      # an old, long journal: the newest 20 stay
            db.add(m.JournalEntry(channel_id=W, canonical_uid='u', entry=f'old {i}', created_at=now - timedelta(days=200, minutes=30 - i)))
        db.add(m.JournalEntry(channel_id=W, canonical_uid='quiet', entry='only entry', created_at=now - timedelta(days=400)))
        db.commit()
    done = maintenance.prune(m)
    assert done == {'action_logs': 30, 'command_receipts': 1, 'link_codes': 1, 'journal': 10}
    with m.SessionLocal() as db:
        assert [r.response for r in db.query(m.ActionLog)] == ['today']
        assert [r.interaction_id for r in db.query(CommandReceipt)] == ['new']
        assert [r.code for r in db.query(m.LinkCode)] == ['NEW111']
        kept = sorted(r.entry for r in db.query(m.JournalEntry).filter_by(canonical_uid='u'))
        assert kept == sorted(f'old {i}' for i in range(10, 30))
        assert db.query(m.JournalEntry).filter_by(canonical_uid='quiet').count() == 1


# ---------------------------------------------------------------- setup checks

def test_a_link_code_from_another_world_explains_the_setting(monkeypatch):
    monkeypatch.setattr(m, 'RUNTIME_WARNINGS', set())
    text = client.get('/api/v1/link/create', params={'channel': '998877', 'uid': 'tw1', 'name': 'Streamer'}).text
    code = text.split('Link code ')[1].split('.')[0]
    reply = m._discord_call_internal('link', 'd1', 'Streamer', {'code': code}, 'i-link-1')
    assert 'different New Eridian world' in reply
    assert any('DISCORD_WORLD_ID=998877' in w for w in m.config_warnings())


def test_twitch_commands_for_another_channel_raise_a_health_warning(monkeypatch):
    monkeypatch.setattr(m, 'RUNTIME_WARNINGS', set())
    monkeypatch.setenv('TWITCH_API_KEY', 'game-key')
    client.get('/api/v1/start', params={'channel': '554433', 'uid': 'tw2', 'name': 'Viewer', 'k': 'game-key'})
    assert any('DISCORD_WORLD_ID=554433' in w for w in m.config_warnings())
    monkeypatch.setattr(m, 'RUNTIME_WARNINGS', set())
    client.get('/api/v1/start', params={'channel': W, 'uid': 'tw3', 'name': 'Viewer', 'k': 'game-key'})
    assert not m.RUNTIME_WARNINGS


def test_health_warns_about_the_public_database_proxy(monkeypatch):
    from sqlalchemy import create_engine
    fake = create_engine('postgresql+psycopg://u:p@roundhouse.proxy.rlwy.net:12345/railway')
    monkeypatch.setattr(m, 'engine', fake)
    assert any('public proxy' in w for w in m.config_warnings())


# ---------------------------------------------------------------- business names

@pytest.mark.parametrize('raw,expected', [
    ('Rocky & Sons', 'Rocky & Sons'), ('  Big   Ore  Co. ', 'Big Ore Co.'), ("Nova's Diner", "Nova's Diner"),
    ('**bold** <@123> https://evil.example/x', 'bold 123 httpsevil.examplex'), ('Café Ñandú', 'Café Ñandú'),
    ('🔥🔥🔥', None), ('<@&999>', '&999'), ('x' * 40, 'x' * 30)])
def test_business_names_keep_only_plain_text(raw, expected):
    assert m.safe_business_name(raw) == expected


def test_blocked_words_are_refused_even_with_spacing_tricks(monkeypatch):
    monkeypatch.setenv('BLOCKED_WORDS', 'badword, other one')
    for name in ('My Badword Shop', 'b.a.d-w o r d', 'OTHERONE inc'):
        assert m.safe_business_name(name) is None, name
    assert m.safe_business_name('Good Shop') == 'Good Shop'


def test_a_refused_business_name_costs_nothing(monkeypatch):
    monkeypatch.setenv('BLOCKED_WORDS', 'badword')
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', 'b1', 'Owner'); p.sc = 100; db.commit()
    text = client.get('/api/v1/business/start', params={'channel': W, 'uid': 'b1', 'provider': 'discord', 'business_name': 'badword'}).text
    assert 'Choose another business name' in text
    with m.SessionLocal() as db:
        assert db.query(m.Business).count() == 0 and db.query(m.Player).one().sc == 100


def test_business_level_ups_on_stream_never_show_the_business_name():
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', 'b2', 'Owner')
        b = m.Business(channel_id=W, canonical_uid=p.twitch_uid, name='Secret Name')
        db.add(b); db.flush()
        m.gain_business_xp(b, 500); db.commit()
        details = [h.title + ' ' + h.detail for h in db.query(m.stream_overlay.StreamHighlight)]
    assert details and not any('Secret Name' in d for d in details)


# ---------------------------------------------------------------- smaller fixes

def test_mentors_must_outrank_the_learner_in_that_skill():
    from app.competencies import FIELDS
    for uid, name in (('m1', 'Main'), ('a1', 'Alt')):
        with m.SessionLocal() as db:
            m.player(db, 'test', 'twitch', uid, name); db.commit()
    with m.SessionLocal() as db:
        main = db.query(m.Player).filter_by(twitch_uid='m1').one()
        for field in FIELDS.values():
            setattr(main, field, 40)
        db.commit()
    refused = m.mentor('test', 'a1', 'Alt', 'Main', 'twitch').body.decode()
    assert 'need a higher level' in refused
    with m.SessionLocal() as db:
        assert db.query(m.Player).filter_by(twitch_uid='m1').one().contribution == 0
        assert db.query(m.PlayerWorld).filter_by(canonical_uid='a1').one().mentor_day != m.world_clock(db, 'test')['day']
    assert 'mentors' in m.mentor('test', 'm1', 'Main', 'Alt', 'twitch').body.decode()


def test_selling_undoing_and_selling_again_announces_a_level_up_once():
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', 's1', 'Seller')
        m.gain_skill(p, 'commerce', 8); db.commit()
        assert m.lvl(p.commerce_xp) >= 2
        p.commerce_xp = 0; db.commit()                     # an undo took the XP back
        m.gain_skill(p, 'commerce', 8); db.commit()
        ups = db.query(m.JournalEntry).filter(m.JournalEntry.entry.like('LEVEL UP%Commerce%')).count()
        highlights = db.query(m.stream_overlay.StreamHighlight).filter_by(kind='level').count()
    assert ups == 1 and highlights == 1


def test_player_names_are_still_found_case_insensitively_and_by_unique_prefix():
    for uid, name in (('n1', 'NovaStar'), ('n2', 'Émile'), ('n3', 'Nova_Two')):
        with m.SessionLocal() as db:
            m.player(db, 'test', 'twitch', uid, name); db.commit()
    with m.SessionLocal() as db:
        assert m.find_player_name(db, 'test', 'novastar')[0].twitch_uid == 'n1'
        assert m.find_player_name(db, 'test', 'émile')[0].twitch_uid == 'n2'
        assert m.find_player_name(db, 'test', 'nova_t')[0].twitch_uid == 'n3'       # '_' is not a wildcard
        assert m.find_player_name(db, 'test', 'nova')[0] is None                      # two matches
        assert m.find_player_name(db, 'test', '%')[0] is None


def test_the_player_menu_marks_duplicate_names():
    for uid, name in (('111', 'Twin'), ('222', 'twin'), ('333', 'Solo')):
        with m.SessionLocal() as db:
            m.player(db, W, 'discord', uid, name); db.commit()
    payload = {'member': {'user': {'id': '999'}}, 'data': {'name': 'social'}}
    labels = [c['name'] for c in m._discord_player_autocomplete(payload)['data']['choices']]
    assert 'Solo' in labels and sum('· citizen #' in label for label in labels) == 2
