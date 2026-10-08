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

def joined(threads, seconds=120):
    # A stuck thread fails this check in two minutes instead of hanging the run until CI's 30-minute limit.
    for t in threads:
        t.join(timeout=seconds)
    assert not any(t.is_alive() for t in threads), 'a thread did not finish within %ss' % seconds
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
threads = [threading.Thread(target=play, args=(str(i),), daemon=True) for i in range(8)]
[t.start() for t in threads]; joined(threads)
assert not errors, errors[:3]

# One lock for the whole game: a transaction naming another channel waits for the main world's.
held = threading.Event()
def hold():
    with task_queue.atomic('some-twitch-channel'):
        held.set(); time.sleep(1.0)
t = threading.Thread(target=hold, daemon=True); t.start(); assert held.wait(timeout=60), 'the lock holder never started'
start = time.monotonic()
with task_queue.atomic(W):
    waited = time.monotonic() - start
joined([t])
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

# Keep levels: the additive table, a Sell all that leaves the keep level, and the account-linking merge (a key change).
from app import keep_levels
lumber, glass = m.seed_content.key('Lumber'), m.seed_content.key('Glass')
with m.SessionLocal() as db:
    p = m.player(db, W, 'discord', 'keeper', 'Citizenkeeper')[1]
    m.material_change(db, p, lumber, 12); db.commit()
    keeper = p.twitch_uid
assert 'always keep 5 Lumber' in client.get('/api/v1/keep', params=params('keeper', text='lumber 5', provider='discord')).text
assert 'keeping 5' in client.get('/api/v1/sellall', params=params('keeper', item='lumber', provider='discord')).text
with m.SessionLocal() as db:
    assert m.material_amount(db, m.player(db, W, 'discord', 'keeper', 'Citizenkeeper')[1], lumber) == 5
    db.add_all([keep_levels.KeepLevel(channel_id=W, canonical_uid='pg-src', item_key=k, amount=a) for k, a in ((lumber, 9), (glass, 3))])
    db.commit()
    keep_levels.merge(db, W, 'pg-src', keeper); db.commit()
    assert keep_levels.levels(db, W, keeper) == {lumber: 5, glass: 3} and keep_levels.levels(db, W, 'pg-src') == {}

# Shopping list: the additive table, an entry set through the route, the combined plan, and the account-linking merge.
from app import shopping_list
assert 'Added to your shopping list: 2 Campfire' in client.get('/api/v1/shopping', params=params('keeper', text='add campfire 2', provider='discord')).text
assert 'want 3 Campfire (was 2' in client.get('/api/v1/shopping', params=params('keeper', text='add campfire 3', provider='discord')).text
assert 'SHOPPING LIST · 1/10' in client.get('/api/v1/shopping', params=params('keeper', provider='discord')).text
with m.SessionLocal() as db:
    campfire = shopping_list._rows(db, W, keeper)[0].recipe_id
    plate = m.workbench.entry('sr_1018791011').id
    db.add_all([shopping_list.ShoppingEntry(channel_id=W, canonical_uid='pg-src', recipe_id=r, want=n, added_at=m.now() - timedelta(days=1))
                for r, n in ((campfire, 9), (plate, 30))])
    db.commit()
    shopping_list.merge(db, W, 'pg-src', keeper); db.commit()
    assert [(r.recipe_id, r.want) for r in shopping_list._rows(db, W, keeper)] == [(campfire, 3), (plate, 30)]
    assert shopping_list._rows(db, W, 'pg-src') == []

# Goal progress: the additive table, the start stored when the route sets a goal, the progress line, the one ready note,
# completion by the craft itself, and the account-linking merge (a key change).
from app import extras
goal_params = lambda **x: params('goalpg', provider='discord', **x)
assert '0 of 2 steps done' in client.get('/api/v1/target', params=goal_params(recipe='campfire')).text
with m.SessionLocal() as db:
    p = m.player(db, W, 'discord', 'goalpg', 'Citizengoalpg')[1]
    goaler = p.twitch_uid
    found = db.get(extras.GoalProgress, (W, goaler))
    assert (found.recipe_id, found.start_steps, found.ready_alerted) == (campfire, 2, 0)
    m.material_change(db, p, lumber, 2 - m.material_amount(db, p, lumber)); db.commit()
    assert extras.goal_text(db, p, 'twitch').startswith('🎯 Goal Campfire 1/2 steps | Next: Craft Campfire')
    assert extras.goal_ready_check(db, p) and not extras.goal_ready_check(db, p); db.commit()
assert 'CRAFTING COMPLETE' in client.get('/api/v1/make', params=goal_params(recipe='campfire')).text
with m.SessionLocal() as db:
    assert extras.goal_entry(db, m.player(db, W, 'discord', 'goalpg', 'Citizengoalpg')[1]) is None
    assert db.get(extras.GoalProgress, (W, goaler)) is None
    db.add_all([extras.GoalProgress(channel_id=W, canonical_uid=uid, recipe_id=rid, start_steps=n, set_at=m.now(), ready_alerted=0)
                for uid, rid, n in (('pg-goal-src', plate, 7), ('pg-goal-other', campfire, 2))])
    db.commit()
    extras.merge(db, W, 'pg-goal-src', goaler); db.commit()             # the target has none: the source's row moves
    moved = db.get(extras.GoalProgress, (W, goaler))
    assert (moved.recipe_id, moved.start_steps) == (plate, 7) and db.get(extras.GoalProgress, (W, 'pg-goal-src')) is None
    extras.merge(db, W, 'pg-goal-other', goaler); db.commit()           # both have one: the target's wins
    assert db.get(extras.GoalProgress, (W, goaler)).recipe_id == plate and db.get(extras.GoalProgress, (W, 'pg-goal-other')) is None

# Quiet hours: the two additive tables, DM alerts held without spending an attempt, then released by two workers at
# once as one summary (one conditional claim per row, so neither worker can send what the other claimed).
import asyncio, json
from types import SimpleNamespace
from app import quiet_hours, discord_queue_worker as dqw, queue_notifications as qn
sent = []
async def request(route, json): sent.append(json); return {'id': '1'}
async def open_dm(): return SimpleNamespace(id=789)
dm_client = SimpleNamespace(get_user=lambda _: SimpleNamespace(create_dm=open_dm), get_channel=lambda _: None, http=SimpleNamespace(request=request))
now = m.now()
with m.SessionLocal() as db:
    p = m.player(db, W, 'discord', '4242', 'Citizen4242')[1]
    for i in range(3):
        db.add(qn.Notice(id=f'pgquiet{i:025d}', provider='discord', recipient='4242', channel_id=W, message_channel=qn.DM_PREFIX,
                         content='TASK QUEUE — COMPLETED\nGather Lumber\nAttempts completed: 1/1; remaining: 0.\nSucceeded: 1; failed: 0.', next_at=now))
        db.add(qn.NoticeEvent(notice_id=f'pgquiet{i:025d}', run_id=f'pgrun{i}', kind='completed', created_at=now))
    assert 'Quiet hours set' in quiet_hours.set_hours(db, p, 'UTC', f'{(now.hour - 1) % 24:02d}', f'{(now.hour + 2) % 24:02d}')
    db.commit()
asyncio.run(dqw.deliver(dm_client))
with m.SessionLocal() as db:
    rows = db.query(qn.Notice).filter(qn.Notice.recipient == '4242').all()
    assert not sent and all(r.state == 'pending' and r.attempts == 0 and r.next_at > m.now() for r in rows)
    assert db.query(quiet_hours.HeldAlert).count() == 3
    assert '3 held alerts are on their way' in quiet_hours.turn_off(db, m.player(db, W, 'discord', '4242', 'Citizen4242')[1])
    db.commit()
workers = [threading.Thread(target=lambda: asyncio.run(dqw.deliver(dm_client)), daemon=True) for _ in range(2)]
[t.start() for t in workers]; joined(workers)
assert len(sent) == 1 and '3 queue alerts waited' in json.dumps(sent[0], ensure_ascii=False), sent
with m.SessionLocal() as db:
    assert all(r.state == 'sent' and r.attempts == 1 for r in db.query(qn.Notice).filter(qn.Notice.recipient == '4242'))
    assert db.query(quiet_hours.HeldAlert).count() == 0 and quiet_hours.row(db, W, 'discord:4242') is None

# Force merge: the preview wrote nothing; a merge that fails half way is rolled back whole; then the owner's button confirms
# the same shared core inside the game transaction (one-time ticket, owner named in the moderator log).
from app import force_merge, ui
with m.SessionLocal() as db:
    a = m.player(db, W, 'twitch', 'pg-tw', 'Pgmerge')[1]; a.sc, a.actions = 300, 25
    m.material_change(db, a, lumber, 12)
    b = m.player(db, W, 'discord', '5151', 'pgmerge')[1]; b.sc, b.actions = 120, 9
    m.material_change(db, b, lumber, 5)
    db.commit()
    ids = (a.id, b.id)
with m.SessionLocal() as db:
    pair = force_merge.load(db, W, 'pg-tw', 'discord:5151')
    assert pair.combined['sc'] == 420 and db.query(m.Player).filter(m.Player.id.in_(ids)).count() == 2
real = m.merge_accounts
def boom(db, channel, source, target):
    real(db, channel, source, target); raise RuntimeError('boom')
m.merge_accounts = boom
try:
    with task_queue.atomic(W):
        with m.SessionLocal() as db:
            force_merge.apply(db, W, force_merge.load(db, W, 'pg-tw', 'discord:5151'), 'owner 6161 via /menu')
    raise AssertionError('the failing merge did not raise')
except RuntimeError:
    pass
finally:
    m.merge_accounts = real
with m.SessionLocal() as db:
    assert db.query(m.Player).filter(m.Player.id.in_(ids)).count() == 2 and db.query(m.ModeratorAudit).count() == 0
    assert db.query(m.AccountLink).filter_by(channel_id=W, twitch_uid='pg-tw').count() == 0
m.DISCORD_OWNER_USER_IDS = {'6161'}
press = lambda cid, values=(): ui.handle_component({'type': 3, 'data': {'custom_id': cid, 'values': list(values)}, 'message': {'flags': 64, 'id': 'pg'},
                                                       'member': {'user': {'id': '6161', 'username': 'Owner'}, 'permissions': str(0x20)}})
for forged in (ui.cid('6161', 'xm', '99999999999999999999', ids[1]), ui.cid('6161', 'xm', ids[0], '99999999999999999999')):
    assert 'That character no longer exists. Choose again. Nothing changed.' in press(forged)['data']['embeds'][0]['description']
assert 'step 2 of 3' in press(ui.cid('6161', 'xm', ids[0]), ['__page:99999999999999999999'])['data']['embeds'][0]['title']
shown = press(ui.cid('6161', 'xm', ids[0], ids[1]))
assert '420 SC' in shown['data']['embeds'][0]['description'] and 'cannot be undone' in shown['data']['embeds'][0]['description']
with m.SessionLocal() as db:
    assert db.query(m.Player).filter(m.Player.id.in_(ids)).count() == 2
ticket = next(c['custom_id'] for r in shown['data']['components'] for c in r['components'] if c.get('label') == 'Confirm merge')
done = press(ticket)
assert 'Merged **pgmerge** into **Pgmerge**' in done['data']['embeds'][0]['description']
assert 'already used' in str(press(ticket))
with m.SessionLocal() as db:
    kept = db.query(m.Player).filter(m.Player.id.in_(ids)).all()
    assert [(p.twitch_uid, p.sc, p.actions) for p in kept] == [('pg-tw', 420, 34)] and m.material_amount(db, kept[0], lumber) == 17
    assert db.query(m.AccountLink).filter_by(channel_id=W, twitch_uid='pg-tw', discord_uid='5151').count() == 1
    assert [(x.moderator, x.action) for x in db.query(m.ModeratorAudit)] == [('owner 6161 via /menu', 'merge')]

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
done = maintenance.prune()
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
