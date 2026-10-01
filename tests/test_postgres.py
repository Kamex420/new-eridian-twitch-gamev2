"""The production database is PostgreSQL; the rest of the suite runs on SQLite, which serialises every write and so
cannot show locking problems. Set TEST_POSTGRES_URL to a throwaway database whose name contains "test" (CI does)
to run the game against PostgreSQL: concurrent commands, the single game lock, the channel guard, indexes and
the hourly cleanup. The database's tables are dropped first."""
import os
import subprocess
import sys
from pathlib import Path
import pytest

URL = os.getenv('TEST_POSTGRES_URL', '')
pytestmark = pytest.mark.skipif(not URL, reason='TEST_POSTGRES_URL is not set')

CHECK = r'''
import os, threading, time
from datetime import timedelta
from sqlalchemy import create_engine, inspect, text
url = os.environ['DATABASE_URL']
with create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1)).begin() as c:
    c.execute(text('DROP SCHEMA public CASCADE')); c.execute(text('CREATE SCHEMA public'))
import app.main as m
from fastapi.testclient import TestClient
from app import task_queue, maintenance
from app.discord_execution import CommandReceipt
client = TestClient(m.app)
W = m.DISCORD_WORLD_ID
params = lambda uid, **x: {'channel': W, 'uid': uid, 'name': 'Citizen' + uid, 'k': 'game-key', **x}

for i in range(8):
    assert 'Welcome' in client.get('/api/v1/start', params=params(str(i))).text

errors = []
def play(uid):
    for _ in range(5):
        for path, extra in (('/api/v1/action/farm', {'msg': 'x'}), ('/api/v1/status', {}), ('/api/v1/overlay', {}),
                            ('/api/v1/seed-supplies', {'mode': 'gather', 'item': 'lumber'}), ('/api/v1/vote', {'choice': '1'})):
            r = client.get(path, params=params(uid, **extra))
            if r.status_code != 200 or 'could not be completed' in r.text:
                errors.append((path, r.status_code, r.text[:120]))
threads = [threading.Thread(target=play, args=(str(i),)) for i in range(8)]
[t.start() for t in threads]; [t.join() for t in threads]
assert not errors, errors[:3]

# One lock for the whole game: a transaction naming another channel waits for the main world's.
held = threading.Event()
def hold():
    with task_queue.atomic(m, 'some-twitch-channel'):
        held.set(); time.sleep(1.0)
t = threading.Thread(target=hold); t.start(); held.wait()
start = time.monotonic()
with task_queue.atomic(m, W):
    waited = time.monotonic() - start
t.join()
assert waited > 0.7, waited

# Channel names longer than the column are refused instead of failing in the database.
assert 'too long' in client.get('/api/v1/start', params={**params('9'), 'channel': 'x' * 65}).text
# Keyless reads of a world nobody started create nothing.
with m.SessionLocal() as db:
    before = db.query(m.Society).count()
assert 'has not started' in client.get('/api/v1/society', params={'channel': 'junk-pg-world'}).text
assert client.get('/api/v1/overlay', params={'channel': 'junk-pg-world'}).json()['ok']
with m.SessionLocal() as db:
    assert db.query(m.Society).count() == before

names = {i['name'] for t in ('action_logs_v5', 'journal_v54', 'discord_command_receipts_v1', 'link_codes_v4')
         for i in inspect(m.engine).get_indexes(t)}
assert {'ix_action_logs_channel_created', 'ix_journal_owner_created', 'ix_command_receipts_created', 'ix_link_codes_expires'} <= names

now = m.now()
with m.SessionLocal() as db:
    db.query(m.ActionLog).delete(); db.query(m.JournalEntry).delete()
    for i in range(30):
        db.add(m.ActionLog(channel_id=W, canonical_uid='u', action='farm', response='old', created_at=now - timedelta(days=30)))
    db.add(m.ActionLog(channel_id=W, canonical_uid='u', action='farm', response='new', created_at=now))
    db.add(CommandReceipt(interaction_id='old', fingerprint='f', result='r', created_at=now - timedelta(days=5)))
    db.add(m.LinkCode(channel_id=W, canonical_uid='u', code='OLDPG1', expires_at=now - timedelta(days=3)))
    for i in range(25):
        db.add(m.JournalEntry(channel_id=W, canonical_uid='u', entry=f'e{i}', created_at=now - timedelta(days=200, minutes=25 - i)))
    db.commit()
maintenance.BATCH = 7
done = maintenance.prune(m)
assert done == {'action_logs': 30, 'command_receipts': 1, 'link_codes': 1, 'journal': 5}, done
print('POSTGRES OK')
'''


def test_the_game_on_postgresql(tmp_path):
    name = URL.rsplit('/', 1)[-1].split('?')[0]
    assert 'test' in name, 'TEST_POSTGRES_URL must name a throwaway database (its name must contain "test"): its tables are dropped'
    env = os.environ | {'DATABASE_URL': URL, 'TWITCH_API_KEY': 'game-key', 'AUTO_EVENTS_ENABLED': 'false'}
    result = subprocess.run([sys.executable, '-c', CHECK], cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0 and 'POSTGRES OK' in result.stdout, result.stdout[-2000:] + result.stderr[-4000:]


MERGE = r'''
import os, sys
sys.path.insert(0, 'tests')
from sqlalchemy import create_engine, text
url = os.environ['DATABASE_URL']
with create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1)).begin() as c:
    c.execute(text('DROP SCHEMA public CASCADE')); c.execute(text('CREATE SCHEMA public'))
import app.main as m
from fastapi.testclient import TestClient
from world_merge_scenario import build, verify, snapshot
client = TestClient(m.app)
S, T = m.DISCORD_WORLD_ID, '27074041'
build(m, client, S, T)
before = snapshot(m, S, T)
preview = client.get('/api/v1/admin/world-merge', params={'source': S, 'target': T, 'key': 'admin-secret'}).json()
assert preview['ok'] and not preview['merged'] and preview['after']['citizens'] == 6, preview
assert snapshot(m, S, T) == before and m.DISCORD_WORLD_ID == S
done = client.get('/api/v1/admin/world-merge', params={'source': S, 'target': T, 'key': 'admin-secret', 'confirm': 1}).json()
assert done['merged'], done
verify(m, client, S, T)
print('MERGE OK')
'''


def test_the_world_merge_on_postgresql():
    name = URL.rsplit('/', 1)[-1].split('?')[0]
    assert 'test' in name, 'TEST_POSTGRES_URL must name a throwaway database (its name must contain "test"): its tables are dropped'
    env = os.environ | {'DATABASE_URL': URL, 'TWITCH_API_KEY': 'game-key', 'ADMIN_KEY': 'admin-secret', 'AUTO_EVENTS_ENABLED': 'false',
                        'DISCORD_WORLD_ID': 'new-eridian', 'DISCORD_WORLD_ID_ON_START': 'new-eridian'}
    result = subprocess.run([sys.executable, '-c', MERGE], cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0 and 'MERGE OK' in result.stdout, result.stdout[-2000:] + result.stderr[-4000:]
