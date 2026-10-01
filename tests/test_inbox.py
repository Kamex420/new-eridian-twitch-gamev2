"""Private notifications: the inbox, popups, warnings when needed, and the short queue status."""
import json
from types import SimpleNamespace
from test_colony import m, reset
from test_task_queue import enqueue, advance
from test_workbench_ui import citizen, press, controls, W
from app import inbox, ui, layout_v2, task_queue as q, queue_notifications as n


def uid():
    return 'discord:111'


def test_queue_events_go_to_the_inbox_and_private_mode_skips_the_ping():
    enqueue(count=1)
    m.settings('test', 'u', provider='discord', alerts='private')
    q.control(m, 'test', 'u', 'Kamex', 'discord', 'cancel')
    with m.SessionLocal() as db:
        items = list(db.query(inbox.InboxItem))
        assert len(items) == 1 and items[0].seen == 0 and 'Queue cancelled' in items[0].text
        assert db.query(n.Notice).count() == 0


def test_pinged_events_are_already_seen():
    enqueue(count=1)
    advance()
    with m.SessionLocal() as db:
        item = db.query(inbox.InboxItem).one()
        assert item.seen == 1 and 'Queue finished' in item.text and db.query(n.Notice).count() == 1


def test_popups_respect_the_player_setting(monkeypatch):
    citizen()
    posts = []
    monkeypatch.setattr(inbox.requests, 'post', lambda url, json, timeout: posts.append((url, json)) or SimpleNamespace(status_code=200))
    with m.SessionLocal() as db:
        inbox.add(m, db, W, uid(), 'warning', 'Something important')
        inbox.add(m, db, W, uid(), 'tip', 'A tip', important=False)
        db.commit()
    payload = {'application_id': 'a', 'token': 't'}
    assert inbox.deliver(m, payload, '111')
    body = posts[-1][1]
    assert body['flags'] & 64 and 'Something important' in layout_v2.text_of(body)   # private
    assert 'A tip' not in layout_v2.text_of(body)                      # 'important' hides tips
    assert not inbox.deliver(m, payload, '111')                        # already shown
    m.settings(W, '111', 'Kam', provider='discord', popups='all')
    assert inbox.deliver(m, payload, '111') and 'A tip' in layout_v2.text_of(posts[-1][1])
    with m.SessionLocal() as db:
        inbox.add(m, db, W, uid(), 'warning', 'Later'); db.commit()
    m.settings(W, '111', 'Kam', provider='discord', popups='off')
    assert not inbox.deliver(m, payload, '111')


def test_popups_use_the_new_layout_unless_it_is_off(monkeypatch):
    citizen()
    posts = []
    monkeypatch.setattr(inbox.requests, 'post', lambda url, json, timeout: posts.append(json) or SimpleNamespace(status_code=200))
    payload = {'application_id': 'a', 'token': 't'}
    for enabled in (True, False):
        monkeypatch.setattr(layout_v2, 'ENABLED', enabled)
        with m.SessionLocal() as db:
            inbox.add(m, db, W, uid(), 'warning', f'Notice {enabled}'); db.commit()
        assert inbox.deliver(m, payload, '111')
        assert layout_v2.is_v2(posts[-1]) is enabled and ('embeds' in posts[-1]) is (not enabled)
        assert f'Notice {enabled}' in layout_v2.text_of(posts[-1])


def test_starting_a_short_queue_warns_when_it_is_needed():
    citizen(lumber=0)
    with m.SessionLocal() as db:
        life = m.life_state(db, m.player(db, W, 'discord', '111', 'Kam')[1]); life.energy = 25; db.commit()
    m._discord_call_internal('mine', '111', 'Kam', {'ore': q.ores().__iter__().__next__(), 'action': 'mine', 'count': 10}, 'i')
    inbox.after_command(m, '111', 'Kam', 'queue', {}, '')
    with m.SessionLocal() as db:
        texts = [i.text for i in db.query(inbox.InboxItem)]
    assert any("won't last" in t for t in texts) and any('Queues work while you are away' in t for t in texts)


def test_one_time_tips_only_once():
    citizen()
    with m.SessionLocal() as db:
        assert inbox.tip(m, db, W, uid(), 'blocked') and not inbox.tip(m, db, W, uid(), 'blocked')


def test_short_queue_status_and_details_button():
    citizen()
    m._discord_call_internal('queue', '111', 'Kam', {'action': 'start', 'task': 'gather:' + m.seed_content.key('Lumber'), 'count': 5}, 'i')
    data = press(ui.cid('111', 'qv'))['data']
    short = json.dumps(data, ensure_ascii=False)
    assert 'For 5 remaining' not in short and 'Only one task type' not in short
    details = press(ui.cid('111', 'qd'))['data']
    assert 'For 5 remaining' in json.dumps(details, ensure_ascii=False)


def test_inbox_view_marks_everything_read():
    citizen()
    with m.SessionLocal() as db:
        inbox.add(m, db, W, uid(), 'warning', 'Read me'); db.commit()
    text = m._discord_call_internal('inbox', '111', 'Kam', {}, 'i')
    assert 'Read me' in text
    with m.SessionLocal() as db:
        assert inbox.unread_count(db, W, uid()) == 0
