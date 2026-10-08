"""Quiet hours: DM queue alerts wait during a daily window in the citizen's own time zone, then arrive as one message."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
import pytest
from test_colony import m, reset
from test_task_queue import due
from test_workbench_ui import citizen, press, controls, W, LUMBER
from app import quiet_hours as qh, discord_queue_worker as w, queue_notifications as n, task_queue as q, inbox, layout_v2, ui

UTC = timezone.utc
GATHER = 'gather:' + LUMBER
LONDON = qh.zone('Europe/London')
needs_tzdata = pytest.mark.skipif(LONDON is None, reason='this Python has no time-zone database (zoneinfo cannot load Europe/London)')


class Clock:
    """m.now(), moved by hand."""
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at

    def go(self, at):
        self.at = at


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime(2026, 1, 15, 23, 30, tzinfo=UTC))          # a winter night: London is on UTC
    monkeypatch.setattr(m, 'now', c)
    return c


def player(uid='111'):
    db = m.SessionLocal()
    return db, m.player(db, W, 'discord', uid, 'Kam')[1]


def set_quiet(tz='UTC', start='23:00', end='08:00', uid='111'):
    db, p = player(uid)
    with db:
        text = qh.set_hours(db, p, tz, start, end)
        db.commit()
        return text


def quiet_row(uid='discord:111'):
    with m.SessionLocal() as db:
        return qh.row(db, W, uid)


def finish_queue(count=1, uid='111'):
    """Run a short queue to the end: one completion alert in the outbox."""
    assert 'TASK QUEUE' in m.queued_tasks(W, uid, 'Kam', 'start', GATHER, count, 'discord').body.decode()
    for _ in range(count):
        due()
        q.tick()


def notices():
    with m.SessionLocal() as db:
        return sorted(db.query(n.Notice).all(), key=lambda x: x.id)


def held():
    with m.SessionLocal() as db:
        return sorted(r.notice_id for r in db.query(qh.HeldAlert))


def dm_client(closed=False, fail=None):
    """A Discord client whose DM channel counts what is posted."""
    room = MagicMock(spec=discord.DMChannel)
    room.id = 789
    room.send = AsyncMock(return_value=SimpleNamespace(id=1))
    opening = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'closed')) if closed else AsyncMock(return_value=room)
    user = SimpleNamespace(create_dm=opening)
    http = SimpleNamespace(request=AsyncMock(return_value={'id': '1'}, side_effect=fail))
    return SimpleNamespace(get_user=lambda _: user, get_channel=lambda _: None, http=http, room=room)


def deliver(client):
    asyncio.run(w.deliver(client))


def held_three(clock, step=1):
    """Three completion alerts made during quiet hours, `step` minutes apart, held by the worker."""
    citizen()
    set_quiet('Europe/London' if LONDON else 'UTC')
    for _ in range(3):
        finish_queue()
        clock.go(clock.at + timedelta(minutes=step))
    client = dm_client()
    deliver(client)
    assert not client.http.request.await_count and len(held()) == 3
    return [x.id for x in notices()]


# ---------------------------------------------------------------- parsing and validation

@needs_tzdata
@pytest.mark.parametrize('text,stored', [('Europe/London', 'Europe/London'), ('europe/london', 'Europe/London'),
                                         ('America/New York', 'America/New_York'), ('Asia/Kolkata', 'Asia/Kolkata')])
def test_iana_names(text, stored):
    assert qh.parse_zone(text) == (stored, '')


@pytest.mark.parametrize('text,stored', [('UTC+2', 'UTC+2'), ('+5:30', 'UTC+5:30'), ('-5', 'UTC-5'), ('GMT-3', 'UTC-3'), ('UTC', 'UTC'),
                                         ('gmt', 'UTC'), ('UTC+0', 'UTC'), ('+0545', 'UTC+5:45'), ('UTC−4', 'UTC-4'), ('+14', 'UTC+14')])
def test_fixed_offsets(text, stored):
    assert qh.parse_zone(text) == (stored, '')
    assert qh.zone(stored).utcoffset(None) == qh._offset(text)


@pytest.mark.parametrize('text', ['', 'Mars/Olympus', '../etc/passwd', '+15', '-13', '+5:75', 'five', 'x' * 60])
def test_bad_time_zones_change_nothing(text):
    name, problem = qh.parse_zone(text)
    assert name == '' and problem.startswith('🌙') and problem.endswith('Nothing changed.')


@needs_tzdata
def test_a_near_miss_suggests_the_zone():
    assert 'Did you mean Europe/London?' in qh.parse_zone('Europe/Lodnon')[1]
    assert 'Did you mean Europe/London?' in qh.parse_zone('London')[1]


def test_without_a_time_zone_database_an_offset_is_suggested(monkeypatch):
    def missing(name):
        raise qh.zoneinfo.ZoneInfoNotFoundError(name)
    monkeypatch.setattr(qh, '_names', lambda: {})
    monkeypatch.setattr(qh, 'ZoneInfo', missing)
    name, problem = qh.parse_zone('Europe/London')
    assert name == '' and 'no time-zone database' in problem and 'UTC+1' in problem and problem.endswith('Nothing changed.')
    assert qh.parse_zone('UTC+1') == ('UTC+1', '')                               # offsets still work


@pytest.mark.parametrize('text,minutes', [('23', 1380), ('23:00', 1380), ('8', 480), ('08:30', 510), ('0', 0), ('23:59', 1439), (' 7:05 ', 425)])
def test_times(text, minutes):
    assert qh.parse_time(text) == minutes


@pytest.mark.parametrize('text', ['24', '23:60', '7pm', '', '-1', '1:5', '12:345', 'noon'])
def test_bad_times(text):
    assert qh.parse_time(text) is None


@pytest.mark.parametrize('tz,start,end,why', [('UTC', '23:00', '23', 'both 23:00'), ('UTC', '25', '08', 'Start must be'),
                                              ('UTC', '23', '8pm', 'End must be'), ('Nowhere/City', '23', '08', 'not a time zone'),
                                              ('+99', '23', '08', 'UTC-12 to UTC+14')])
def test_invalid_settings_change_nothing(clock, tz, start, end, why):
    citizen()
    text = set_quiet(tz, start, end)
    assert why in text and text.endswith('Nothing changed.') and quiet_row() is None
    set_quiet('UTC', '22:00', '06:00')
    assert set_quiet(tz, start, end).endswith('Nothing changed.')
    assert qh.describe(quiet_row()) == '22:00–06:00 (UTC)'


def test_setting_changing_and_repeating(clock):
    citizen()
    assert set_quiet('UTC+2', '23', '7').startswith('🌙 Quiet hours set: 23:00–07:00 (UTC+2).')
    assert 'already 23:00–07:00 (UTC+2). Nothing changed.' in set_quiet('+2', '23:00', '07:00')
    assert set_quiet('UTC', '22:30', '06:00').startswith('🌙 Quiet hours changed: 22:30–06:00 (UTC) (was 23:00–07:00 (UTC+2)).')
    row = quiet_row()
    assert (row.tz, row.start_min, row.end_min) == ('UTC', 1350, 360)


# ---------------------------------------------------------------- the window

def at(h, mi=0, s=0, day=15, month=1):
    return datetime(2026, month, day, h, mi, s, tzinfo=UTC)


def test_window_across_midnight_and_its_edges():
    night = SimpleNamespace(tz='UTC', start_min=23 * 60, end_min=8 * 60)
    assert not qh.inside(night, at(22, 59, 59)) and qh.inside(night, at(23)) and qh.inside(night, at(3))
    assert qh.inside(night, at(7, 59, 59)) and not qh.inside(night, at(8)) and not qh.inside(night, at(12))
    assert qh.window_end(night, at(23, 30)) == at(8, day=16)                  # tonight's window ends tomorrow
    assert qh.window_end(night, at(3)) == at(8)                               # after midnight: this morning
    assert qh.window_end(night, at(12)) == at(8, day=16)                      # outside: the next window's end
    day = SimpleNamespace(tz='UTC+2', start_min=9 * 60, end_min=17 * 60)       # 07:00–15:00 UTC
    assert not qh.inside(day, at(6, 59)) and qh.inside(day, at(7)) and qh.inside(day, at(14, 59)) and not qh.inside(day, at(15))
    assert qh.window_end(day, at(10)) == at(15)


@needs_tzdata
def test_daylight_saving_time_in_london():
    night = SimpleNamespace(tz='Europe/London', start_min=23 * 60, end_min=8 * 60)
    assert qh.window_end(night, at(23, 30)) == at(8, day=16)                                  # winter: 08:00 GMT
    assert qh.window_end(night, at(22, 30, month=7, day=1)) == at(7, month=7, day=2)          # summer: 08:00 BST = 07:00 UTC
    assert qh.inside(night, at(22, 30, month=7, day=1)) and not qh.inside(night, at(22, 30))  # 23:30 BST, but 22:30 GMT
    # The clocks go forward during the night of 28–29 March 2026: 23:30 GMT, and the window ends at 08:00 BST.
    assert qh.window_end(night, at(23, 30, month=3, day=28)) == at(7, month=3, day=29)
    assert not qh.inside(night, at(7, 30, month=3, day=29))                                   # 08:30 BST
    # And back on 25 October 2026: 23:30 BST the evening before, the window ends at 08:00 GMT.
    assert qh.window_end(night, at(22, 30, month=10, day=24)) == at(8, month=10, day=25)
    assert qh.inside(night, at(7, 30, month=10, day=25))                                      # 07:30 GMT


@needs_tzdata
def test_a_window_inside_the_repeated_hour_ends_the_same_night():
    # 01:00–01:30 London on 25 October 2026 happens twice; at the second 01:15 (GMT) it ends at 01:30 GMT, not a day later.
    short = SimpleNamespace(tz='Europe/London', start_min=60, end_min=90)
    second = at(1, 15, month=10, day=25)
    assert qh.inside(short, second) and qh.window_end(short, second) == at(1, 30, month=10, day=25)


# ---------------------------------------------------------------- holding

@pytest.mark.parametrize('now,end', [(at(23, 30), at(8, day=16)), (at(22, 30, month=7, day=1), at(7, month=7, day=2))])
def test_a_dm_alert_in_quiet_hours_waits_without_spending_an_attempt(clock, now, end):
    if LONDON is None:
        pytest.skip('this Python has no time-zone database')
    clock.go(now)
    citizen()
    set_quiet('Europe/London')
    finish_queue()
    client = dm_client()
    deliver(client)
    deliver(client)
    note, = notices()
    assert not client.http.request.await_count and not client.room.send.await_count
    assert note.state == 'pending' and note.attempts == 0 and note.error == ''
    assert m.as_utc(note.next_at) == end and held() == [note.id]
    with m.SessionLocal() as db:
        assert m.as_utc(db.get(qh.HeldAlert, note.id).held_at) == now


def test_alerts_outside_quiet_hours_go_out_as_usual(clock):
    clock.go(at(12))
    citizen()
    set_quiet('UTC')
    finish_queue()
    client = dm_client()
    deliver(client)
    note, = notices()
    assert client.http.request.await_count == 1 and note.state == 'sent' and held() == []
    assert quiet_row() is not None


# ---------------------------------------------------------------- release

def test_three_held_alerts_arrive_as_one_dm(clock):
    ids = held_three(clock)
    clock.go(at(8, 0, 5, day=16))
    client = dm_client()
    deliver(client)
    deliver(client)
    assert client.http.request.await_count == 1 and not client.room.send.await_count       # one DM, once
    route, = client.http.request.await_args.args
    body = client.http.request.await_args.kwargs['json']
    words = layout_v2.text_of(body)
    assert route.url.endswith('/channels/789/messages')
    assert words.startswith('3 queue alerts waited for the end of your quiet hours.') and qh.TITLE in words
    assert words.count('✅ **Completed** · Gather Lumber · 1/1 attempts · 1 succeeded, 0 failed · gained Lumber') == 3
    assert body['nonce'] == ('q' + min(ids))[:25] and body['allowed_mentions']['users'] == []
    assert {'Queue', 'Status', 'Notifications'} <= {c.get('label') for c in layout_v2.controls(body)}
    assert all(x.state == 'sent' and x.attempts == 1 for x in notices()) and held() == []


def test_a_long_summary_points_to_notifications():
    batch = [SimpleNamespace(id=f'{i:032d}', recipient='111', content='TASK QUEUE — COMPLETED\nGather Lumber\nAttempts completed: 1/1; remaining: 0.',
                             kind='completed', created_at=at(23)) for i in range(qh.SHOWN + 4)]
    data, first = qh.summary(batch)
    text = data['embeds'][0]['description']
    assert first.startswith(f'{qh.SHOWN + 4} queue alerts') and text.endswith('…and 4 more in /menu → Notifications.')
    assert len(text) <= 4000 and layout_v2.convert(data) is not None


def test_a_single_held_alert_is_the_normal_alert_with_a_moon_line(clock):
    citizen()
    set_quiet('UTC')
    finish_queue()
    deliver(dm_client())
    note, = notices()
    clock.go(at(8, day=16))
    client = dm_client()
    deliver(client)
    body = client.http.request.await_args.kwargs['json']
    assert client.http.request.await_count == 1
    assert layout_v2.text_of(body).startswith('Your queue has finished. 🌙 Held during your quiet hours.')
    assert body['nonce'] == note.id[:25] and {'Repeat ×1', 'Status', 'Queue'} <= {c.get('label') for c in layout_v2.controls(body)}
    assert notices()[0].state == 'sent' and held() == []


def test_a_failed_release_retries_every_alert_together_and_sends_once(clock):
    ids = held_three(clock)
    clock.go(at(8, day=16))
    client = dm_client(fail=[OSError('network down'), {'id': '1'}])
    deliver(client)
    rows = notices()
    assert all(x.state == 'pending' and x.attempts == 1 and 'network' in x.error for x in rows)
    assert held() == ids                                            # still one message when it retries
    deliver(client)                                                 # not due yet: the backoff
    assert client.http.request.await_count == 1
    clock.go(at(8, 0, 31, day=16))
    deliver(client)
    deliver(client)
    assert client.http.request.await_count == 2                     # one refused, one accepted: the summary arrived once
    assert layout_v2.text_of(client.http.request.await_args.kwargs['json']).startswith('3 queue alerts')
    assert all(x.state == 'sent' and x.attempts == 2 for x in notices()) and held() == []


def test_a_release_that_keeps_failing_ends_failed_and_is_not_held(clock):
    held_three(clock)
    clock.go(at(8, day=16))
    client = dm_client(fail=OSError('network down'))
    for i in range(5):
        deliver(client)
        clock.go(clock.at + timedelta(minutes=11))
    assert client.http.request.await_count == 5 and all(x.state == 'failed' and x.attempts == 5 for x in notices()) and held() == []


@pytest.mark.parametrize('step', [1, 0])
def test_closed_dms_put_each_held_alert_in_notifications(clock, step):
    held_three(clock, step)
    with m.SessionLocal() as db:
        db.add(inbox.InboxItem(channel_id=W, canonical_uid='discord:111', kind='queue', text='newer', created_at=at(23, 50), seen=1))
        db.commit()
        assert inbox.unread_count(db, W, 'discord:111') == 0          # DM alerts count as seen
    clock.go(at(8, day=16))
    client = dm_client(closed=True)
    deliver(client)
    assert not client.http.request.await_count and not client.room.send.await_count
    with m.SessionLocal() as db:
        unread = [i.text for i in db.query(inbox.InboxItem).filter_by(seen=0)]
        assert len(unread) == 3 and all('Queue finished' in t for t in unread)   # each alert's own notification, not the newest item
    assert all(x.state == 'sent' for x in notices()) and held() == []


def test_two_workers_cannot_both_send_the_summary(clock):
    held_three(clock)
    clock.go(at(8, day=16))
    client = dm_client()

    async def both():
        await asyncio.gather(w.deliver(client), w.deliver(client))
    asyncio.run(both())
    assert client.http.request.await_count == 1 and all(x.state == 'sent' for x in notices())


def test_a_second_release_claim_gets_nothing(clock):
    ids = held_three(clock)
    clock.go(at(8, day=16))
    first = qh.claim_release(W, '111')
    assert sorted(x.id for x in first) == ids and qh.claim_release(W, '111') == []
    assert w.claim(ids[0]) is None                                # nor can the ordinary claim take one


# ---------------------------------------------------------------- changing the setting

def test_turning_off_releases_held_alerts_at_once(clock):
    held_three(clock)
    data = press(ui.cid('111', 'qo'))['data']
    words = json.dumps(data, ensure_ascii=False)
    assert 'Quiet hours off' in words and '3 held alerts are on their way now, as one message.' in words
    assert quiet_row() is None and all(m.as_utc(x.next_at) == clock.at for x in notices())
    client = dm_client()
    deliver(client)
    assert client.http.request.await_count == 1 and all(x.state == 'sent' for x in notices())
    assert 'already off. Nothing changed.' in json.dumps(press(ui.cid('111', 'qo'))['data'], ensure_ascii=False)


def test_moving_the_window_releases_at_once_or_keeps_holding(clock):
    held_three(clock)
    assert 'They are on now, until <t:' in set_quiet('UTC', '22:00', '10:00')         # still inside: wait for the new end
    assert all(m.as_utc(x.next_at) == at(10, day=16) for x in notices())
    assert '3 held alerts are on their way now' in set_quiet('UTC', '09:00', '17:00')  # outside now
    client = dm_client()
    deliver(client)
    assert client.http.request.await_count == 1 and held() == []


def test_extending_quiet_hours_holds_again_at_the_old_end(clock):
    held_three(clock)
    with m.SessionLocal() as db:
        row = qh.row(db, W, 'discord:111')
        row.end_min = 10 * 60                                        # changed without the form: the next due check re-holds
        db.commit()
    clock.go(at(8, day=16))
    client = dm_client()
    deliver(client)
    assert not client.http.request.await_count and all(m.as_utc(x.next_at) == at(10, day=16) and x.attempts == 0 for x in notices())
    clock.go(at(10, day=16))
    deliver(client)
    assert client.http.request.await_count == 1


def test_a_superseded_pause_alert_is_not_in_the_summary(clock):
    citizen()
    set_quiet('UTC')
    with m.SessionLocal() as db:
        m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1]).energy = 19
        db.commit()
    m.queued_tasks(W, '111', 'Kam', 'start', GATHER, 1, 'discord')
    due()
    q.tick()
    deliver(dm_client())
    pause, = notices()
    assert 'PAUSED' in pause.content and held() == [pause.id]
    with m.SessionLocal() as db:
        m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1]).energy = 100
        db.commit()
    due()
    q.tick()                                                         # resumes and finishes: the pause alert is superseded
    with m.SessionLocal() as db:
        assert db.get(n.Notice, pause.id).state == 'superseded'
    assert held() == []                                               # its held row is gone with it
    deliver(dm_client())
    clock.go(at(8, day=16))
    client = dm_client()
    deliver(client)
    words = layout_v2.text_of(client.http.request.await_args.kwargs['json'])
    assert client.http.request.await_count == 1 and 'Your queue has finished.' in words and 'paused' not in words.lower()
    with m.SessionLocal() as db:
        assert db.get(n.Notice, pause.id).state == 'superseded'


def test_repair_leaves_held_alerts_alone(clock):
    ids = held_three(clock)
    before = [(x.id, x.state, x.attempts, x.next_at) for x in notices()]
    w.repair_recent()
    assert [(x.id, x.state, x.attempts, x.next_at) for x in notices()] == before and held() == ids


# ---------------------------------------------------------------- only DM alerts

def test_channel_mentions_are_not_held(clock):
    citizen()
    set_quiet('UTC')
    m.settings(W, '111', 'Kam', provider='discord', alerts='mention')
    finish_queue()
    with m.SessionLocal() as db:
        note = db.query(n.Notice).one()
        note.message_channel = '456'
        db.commit()
    room = MagicMock(spec=discord.TextChannel)
    room.id = 456
    room.send = AsyncMock(return_value=SimpleNamespace(id=1))
    client = SimpleNamespace(get_channel=lambda _: room, http=SimpleNamespace(request=AsyncMock(return_value={'id': '1'})))
    deliver(client)
    assert client.http.request.await_count == 1 and notices()[0].state == 'sent' and held() == []
    assert layout_v2.text_of(client.http.request.await_args.kwargs['json']).startswith('<@111> Your queue has finished.')


def test_twitch_alerts_are_not_held(clock, monkeypatch):
    with m.SessionLocal() as db:
        m.player(db, W, 'twitch', 'tw', 'Tw')
        db.add(qh.QuietHours(channel_id=W, canonical_uid='tw', tz='UTC', start_min=23 * 60, end_min=8 * 60))
        db.commit()
    m.queued_tasks(W, 'tw', 'Tw', 'start', GATHER, 1, 'twitch')
    due()
    q.tick()
    sent = []
    monkeypatch.setattr(n, 'send', lambda row: sent.append(row.id))
    deliver(dm_client())                                              # the Discord worker never touches it
    n.deliver('twitch')
    note, = notices()
    assert note.provider == 'twitch' and sent == [note.id] and note.state == 'sent' and held() == []


def test_private_alerts_still_pop_up(clock):
    citizen()
    set_quiet('UTC')
    m.settings(W, '111', 'Kam', provider='discord', alerts='private')
    finish_queue()
    with m.SessionLocal() as db:
        assert db.query(n.Notice).count() == 0 and inbox.unread_count(db, W, 'discord:111') == 1


# ---------------------------------------------------------------- linked accounts

def test_account_linking_keeps_the_targets_quiet_hours():
    with m.SessionLocal() as db:
        db.add_all([qh.QuietHours(channel_id=W, canonical_uid='src', tz='UTC', start_min=1, end_min=2),
                    qh.QuietHours(channel_id=W, canonical_uid='dst', tz='UTC+2', start_min=3, end_min=4),
                    qh.QuietHours(channel_id=W, canonical_uid='lone', tz='UTC-5', start_min=5, end_min=6)])
        db.commit()
        q.merge_accounts(db, W, 'src', 'dst')
        q.merge_accounts(db, W, 'lone', 'new')
        db.commit()
    with m.SessionLocal() as db:
        assert qh.row(db, W, 'src') is None and qh.row(db, W, 'dst').tz == 'UTC+2'
        assert qh.row(db, W, 'lone') is None and qh.row(db, W, 'new').tz == 'UTC-5'


# ---------------------------------------------------------------- Discord screens

def form(tz, start, end, uid='111'):
    boxes = [('value', tz), ('start', start), ('end', end)]
    payload = {'type': 5, 'data': {'custom_id': ui.cid(uid, 'md', 'quiet'), 'components': [
        {'type': 1, 'components': [{'type': 4, 'custom_id': k, 'value': v}]} for k, v in boxes]},
        'member': {'user': {'id': uid, 'username': 'Kam'}}, 'message': {'flags': 64}}
    return ui.handle_modal(payload)


def labels(data):
    return [c.get('label') for c in controls(data)]


def boxes(answer):
    return {c['custom_id']: c.get('value', '') for r in answer['data']['components'] for c in r['components']}


def test_the_settings_form_sets_quiet_hours(clock):
    citizen()
    area = press(ui.cid('111', 'mn', 'settings'))['data']
    assert 'Quiet hours' in labels(area) and 'Turn off quiet hours' not in labels(area)
    opened = press(ui.cid('111', 'mo', 'quiet'))
    assert opened['type'] == 9 and boxes(opened) == {'value': '', 'start': '', 'end': ''}
    data = form('europe/london' if LONDON else 'UTC', '23', '8:00')['data']
    words = json.dumps(data, ensure_ascii=False)
    zone = 'Europe/London' if LONDON else 'UTC'
    assert f'🌙 **Quiet hours set:** 23:00–08:00 ({zone}).' in words and 'They are on now, until <t:' in words
    assert f'• **Quiet hours:** 23:00–08:00 ({zone}) — 🌙 on now' in words
    assert {'Turn off quiet hours', 'Quiet hours', 'Back', 'Menu'} <= set(labels(data))
    assert boxes(press(ui.cid('111', 'mo', 'quiet'))) == {'value': zone, 'start': '23:00', 'end': '08:00'}    # filled in
    assert 'Turn off quiet hours' in labels(press(ui.cid('111', 'mn', 'settings'))['data'])


@pytest.mark.parametrize('tz,start,end,why', [('Mars/Base', '23', '08', 'not a time zone'), ('UTC', '23', '23:00', 'no quiet window'),
                                              ('UTC', 'late', '08', 'Start must be'), ('UTC', '23', '8.75', 'End must be')])
def test_the_form_refuses_bad_input(clock, tz, start, end, why):
    citizen()
    data = form(tz, start, end)['data']
    words = json.dumps(data, ensure_ascii=False)
    assert why in words and 'Nothing changed.' in words and quiet_row() is None
    assert '• **Quiet hours:** off' in words and {'Back', 'Menu'} <= set(labels(data))


def test_turn_off_button(clock):
    citizen()
    form('UTC', '23', '08')
    data = press(ui.cid('111', 'qo'))['data']
    assert '🌙 **Quiet hours off:** DM alerts arrive as they happen again.' in json.dumps(data, ensure_ascii=False)
    assert quiet_row() is None and 'Turn off quiet hours' not in labels(data) and {'Back', 'Menu'} <= set(labels(data))


def test_settings_status_and_delivery_texts(clock, monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'fake')
    monkeypatch.setattr(m.app.state, 'discord_queue', None, raising=False)
    citizen()
    view = m.settings(W, '111', 'Kam', provider='discord').body.decode()
    assert '• Quiet hours: off' in view
    set_quiet('UTC')
    view = m.settings(W, '111', 'Kam', provider='discord').body.decode()
    end = int(at(8, day=16).timestamp())
    assert f'• Quiet hours: 23:00–08:00 (UTC) — 🌙 on now: DM alerts wait and arrive as one message at <t:{end}:t>.' in view
    assert 'Alerts: direct message · 🌙 Quiet hours 23:00–08:00, on now · Auto-recover' in m.status_view(W, '111', 'Kam', 'discord').body.decode()
    m.queued_tasks(W, '111', 'Kam', 'start', GATHER, 2, 'discord')
    db, p = player()
    with db:
        status = q.status(db, p, db.get(q.TaskQueue, (W, p.twitch_uid)))
        assert f'🌙 Quiet hours are on now, 23:00–08:00 (UTC): DM alerts wait and arrive as one message at <t:{end}:t>.' in status
    clock.go(at(12, day=16))
    db, p = player()
    with db:
        line = n.delivery_status(db, db.get(q.TaskQueue, (W, p.twitch_uid)))
        assert line.endswith(f'🌙 Quiet hours 23:00–08:00 (UTC): DM alerts wait and arrive as one message at <t:{int(at(8, day=17).timestamp())}:t>.')
    clock.go(at(23, 30, day=16))
    for _ in range(2):
        due()
        q.tick()
    deliver(dm_client())
    db, p = player()
    with db:
        assert f'🌙 Held for your quiet hours: this alert arrives at <t:{int(at(8, day=17).timestamp())}:t>' in \
            q.status(db, p, db.get(q.TaskQueue, (W, p.twitch_uid)))
    m.settings(W, '111', 'Kam', provider='discord', alerts='mention')
    assert 'They only affect direct-message alerts' in m.settings(W, '111', 'Kam', provider='discord').body.decode()


def test_twitch_settings_mention_quiet_hours_as_a_discord_option():
    assert 'quiet hours for DMs) are Discord options' in m.settings('test', 'tw', provider='twitch', text='alerts dm').body.decode()
