"""First steps: six goals in any order, each rewarded at once; a welcome kit; veterans are left alone."""
import pytest
from test_colony import m, reset, client
from app import onboarding as ob, seed_content as s

C, UID = 'test', 'newbie'


@pytest.fixture(autouse=True)
def enabled(reset, monkeypatch):
    monkeypatch.setattr(ob, 'ENABLED', True)


def call(path, **params):
    return client.get(path, params={'channel': C, 'uid': UID, 'name': 'Nova', 'provider': 'twitch', **params}).text


def state():
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=C, twitch_uid=UID).one()
        found = ob.row(db, p)
        return p.sc, p.contribution, ob.done_of(found), bool(found.finished), m.material_amount(db, p, s.key('Lumber')), m.material_amount(db, p, s.key('Berries'))


def test_new_citizen_gets_a_welcome_kit_and_a_first_diary_entry():
    text = call('/api/v1/start')
    assert 'Welcome to New Eridian' in text and 'stream map' in text and 'gather' in text.lower()
    sc, _, done, finished, lumber, berries = state()
    assert (lumber, berries) == (2, 4) and done == [] and not finished
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=C, twitch_uid=UID).one()
        assert m.autonomy.entries(db, p, 5)[0].headline == 'Nova arrives in New Eridian'


def ready():
    with m.SessionLocal() as db:
        db.query(m.Cooldown).delete(); db.commit()


def test_six_steps_in_any_order_each_rewarded_then_a_title():
    call('/api/v1/start')
    sc0 = state()[0]
    # Out of order on purpose: job, craft (from the welcome kit), eat, queue, Seedling, and gathering last.
    assert '🎓 1/6 +10 SC' in call('/api/v1/job', job='miner')
    ready()
    assert '🎓 2/6' in call('/api/v1/make', recipe='campfire')
    ready()
    assert '🎓 3/6' in call('/api/v1/action/eat', msg='food:' + s.key('Berries'))
    queue = call('/api/v1/queue', action='start', task='gather:' + s.key('Lumber'), count='2')
    assert '🎓 4/6' in queue
    seedling = call('/api/v1/seedling')
    assert '🎓 5/6' in seedling and 'next: !gather lumber' in seedling       # the one left is named as next
    call('/api/v1/queue', action='cancel')
    ready()
    final = call('/api/v1/seed-supplies', mode='gather', item='lumber')
    sc, contribution, done, finished, *_ = state()
    assert finished and sorted(done) == sorted(ob.STEPS), (done, final)
    assert 'First steps done' in final and 'Settled In' in final
    assert sc >= sc0 + sum(v[4] for v in ob.INFO.values()) + ob.FINISH_SC
    with m.SessionLocal() as db:
        assert db.query(m.PlayerTitle).filter_by(channel_id=C, canonical_uid=UID, title_key='settled_in').one()
    assert '🎓' not in call('/api/v1/job', job='farmer')                  # finished: no more notes


def test_players_who_already_play_never_see_the_path():
    with m.SessionLocal() as db:
        p = m.player(db, C, 'twitch', 'vet', 'Veteran')[1]
        p.actions = 200
        db.query(ob.FirstSteps).filter_by(channel_id=C, canonical_uid='vet').delete()
        db.commit()
        assert ob.row(db, p).finished and ob.status(db, p) == '' and ob.line(db, p) == ''
        assert ob.complete(db, p, ['job']) == ''


def test_map_welcomes_new_citizens():
    page = client.get('/obs/map', params={'channel': C}).text
    assert 'function welcomeNew(' in page and 'Welcome to New Eridian' in page


def test_a_step_pays_only_once():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=C, twitch_uid=UID).one()
        sc = p.sc
        note = ob.complete(db, p, ['job', 'job', 'queue', 'queue'])
        assert note.count('Choose a job') == 1 and p.sc == sc + ob.INFO['job'][4] + ob.INFO['queue'][4]
        assert ob.complete(db, p, ['job']) == '' and len(ob.done_of(ob.row(db, p))) == 2


def test_twitch_reply_stays_one_short_line_with_the_step_note():
    call('/api/v1/start')
    reply = call('/api/v1/job', job='miner')
    assert '\n' not in reply and len(reply.encode()) <= 200 and '🎓 1/6' in reply and '!' in reply


def test_discord_shows_the_full_checklist_and_step_names():
    client.get('/api/v1/start', params={'channel': C, 'uid': 'd1', 'name': 'Nova', 'provider': 'discord'})
    job = client.get('/api/v1/job', params={'channel': C, 'uid': 'd1', 'name': 'Nova', 'provider': 'discord', 'job': 'miner'}).text
    assert 'First steps 1/6' in job and 'Choose a job ✅ +10 SC' in job and 'Next: Gather something' in job
    guide = client.get('/api/v1/guide', params={'channel': C, 'uid': 'd1', 'name': 'Nova', 'provider': 'discord'}).text
    assert 'FIRST STEPS 1/6' in guide and '✅ 💼 Choose a job' in guide and '➡️ 🧺 Gather something' in guide
