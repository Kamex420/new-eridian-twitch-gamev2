"""No live Discord traffic: exercise async channel sends and durable delivery."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
import pytest
from test_colony import m,reset
from test_task_queue import enqueue,advance
from app import discord_queue_worker as w,queue_notifications as n,task_queue as q


def channel():
    obj=MagicMock(spec=discord.TextChannel)
    obj.send=AsyncMock(return_value=SimpleNamespace(id=123))
    return obj


def notice(text='TASK QUEUE — COMPLETED\nMine Coal\nAttempts completed: 1/1; remaining: 0.'):
    return SimpleNamespace(id='a'*32,recipient='123',message_channel='456',content=text)


def test_send_uses_real_channel_mention_and_not_a_dm():
    room=channel();client=SimpleNamespace(get_channel=lambda _:None,fetch_channel=AsyncMock(return_value=room))
    asyncio.run(w.send_notice(m,client,notice()))
    client.fetch_channel.assert_awaited_once_with(456)
    args=room.send.call_args.kwargs
    assert args['content']=='<@123> Your queue has finished.'
    assert args['silent'] is False
    assert args['nonce']=='a'*25
    assert args['allowed_mentions'].to_dict()=={'parse':[],'users':[123]}
    assert args['allowed_mentions'].replied_user is False
    assert isinstance(args['embeds'][0],discord.Embed)


def test_pause_message_includes_reason_and_recovery():
    room=channel();client=SimpleNamespace(get_channel=lambda _:room)
    text='TASK QUEUE — PAUSED\nMine Coal\nAttempts completed: 1/2; remaining: 1.\nPAUSE REASON\nEnergy: 18/100; need 20. Use /sleep.'
    asyncio.run(w.send_notice(m,client,notice(text)))
    args=room.send.call_args.kwargs
    assert 'paused' in args['content']
    assert '/sleep' in str(args['embeds'][0].to_dict())


def test_dm_channel_is_rejected():
    client=SimpleNamespace(get_channel=lambda _:MagicMock(spec=discord.DMChannel))
    with pytest.raises(n.DeliveryError,match='DMs are disabled'):
        asyncio.run(w.send_notice(m,client,notice()))


def test_forbidden_embeds_fall_back_to_text():
    room=channel();room.send.side_effect=[discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'No embed permission'),SimpleNamespace(id=1)]
    asyncio.run(w.send_notice(m,SimpleNamespace(get_channel=lambda _:room),notice()))
    assert room.send.await_count==2
    assert 'embeds' not in room.send.call_args.kwargs
    assert 'Attempts completed: 1/1' in room.send.call_args.kwargs['content']


def test_missing_token_preserves_pending_alerts(monkeypatch):
    enqueue(count=1);advance();runtime=w.Runtime(m)
    async def run():
        assert not await runtime.login()
        assert runtime.state=='missing_token'
    asyncio.run(run())
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one()
        assert row.attempts==0 and row.state=='pending'
        assert 'DISCORD_BOT_TOKEN is missing' in q.status(m,db,db.query(m.Player).one(),db.query(q.TaskQueue).one())


def test_async_outbox_sends_once_and_keeps_rewards(monkeypatch):
    enqueue(count=1);advance();sent=[]
    async def send(*args):sent.append(args[-1].id)
    monkeypatch.setattr(w,'send_notice',send)
    async def run():await w.deliver(m,object());await w.deliver(m,object())
    asyncio.run(run())
    assert len(sent)==1
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='sent'
        assert db.query(m.Player).one().ore==101


def test_two_async_workers_cannot_claim_one_notice_twice(monkeypatch):
    enqueue(count=1);advance();sent=[]
    async def send(*args):sent.append(args[-1].id);await asyncio.sleep(0)
    monkeypatch.setattr(w,'send_notice',send)
    async def run():await asyncio.gather(w.deliver(m,object()),w.deliver(m,object()))
    asyncio.run(run());assert len(sent)==1


def test_permission_failure_is_visible(monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN','fake')
    enqueue(count=1);advance()
    async def forbidden(*args):raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'permission denied')
    monkeypatch.setattr(w,'send_notice',forbidden);asyncio.run(w.deliver(m,object()))
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one()
        assert row.state=='failed' and 'Send Messages' in row.error
        assert 'Send Messages' in q.status(m,db,db.query(m.Player).one(),db.query(q.TaskQueue).one())


def test_recent_failed_alert_recovered_once_on_login():
    enqueue(count=1);advance()
    with m.SessionLocal() as db:row=db.query(n.Notice).one();row.state='failed';row.attempts=5;db.commit()
    w.repair_recent(m)
    with m.SessionLocal() as db:
        row=db.query(n.Notice).one();assert row.state=='pending' and row.attempts==0
        row.state='sent';db.commit()
    w.repair_recent(m)
    with m.SessionLocal() as db:assert db.query(n.Notice).one().state=='sent'


def test_old_failures_are_not_reposted():
    enqueue(count=1);advance()
    with m.SessionLocal() as db:
        db.query(q.TaskQueue).one().next_at=m.now()-timedelta(days=2)
        db.query(n.Notice).one().state='failed';db.commit()
    w.repair_recent(m)
    with m.SessionLocal() as db:assert db.query(n.Notice).one().state=='failed'


def test_missing_completion_notice_is_repaired_without_awarding_again():
    enqueue(count=1);advance()
    with m.SessionLocal() as db:db.query(n.Notice).delete();db.query(n.NoticeEvent).delete();db.commit()
    w.repair_recent(m)
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='pending'
        assert db.query(m.Player).one().ore==101


def test_twitch_worker_does_not_claim_discord_alerts(monkeypatch):
    enqueue(count=1);advance();calls=[]
    monkeypatch.setattr(n,'send',lambda *args:calls.append(args))
    n.deliver(m,provider='twitch')
    assert not calls
    with m.SessionLocal() as db:assert db.query(n.Notice).one().attempts==0


def test_invalid_token_is_visible_and_login_retries_are_throttled(monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN','fake')
    fake=SimpleNamespace(__aenter__=AsyncMock(),login=AsyncMock(side_effect=discord.LoginFailure('invalid')),close=AsyncMock())
    monkeypatch.setattr(w.discord,'Client',lambda **kwargs:fake)
    runtime=w.Runtime(m)
    async def run():
        assert not await runtime.login()
        assert runtime.state=='invalid_token'
        assert not await runtime.login()
    asyncio.run(run());assert fake.login.await_count==1 and fake.close.await_count==1


def test_wrong_application_token_is_not_used(monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN','fake');monkeypatch.setenv('DISCORD_APPLICATION_ID','111')
    fake=SimpleNamespace(__aenter__=AsyncMock(),login=AsyncMock(),close=AsyncMock(),user=SimpleNamespace(id=222))
    monkeypatch.setattr(w.discord,'Client',lambda **kwargs:fake)
    runtime=w.Runtime(m)
    assert not asyncio.run(runtime.login()) and runtime.state=='wrong_application'
    assert runtime.client is None


def test_rate_limited_send_retries_without_advancing_queue(monkeypatch):
    enqueue(count=1);advance();calls=[]
    async def send(*args):
        calls.append(1)
        if len(calls)==1:raise discord.HTTPException(SimpleNamespace(status=429,reason='Rate limited'),'try later')
    monkeypatch.setattr(w,'send_notice',send)
    asyncio.run(w.deliver(m,object()))
    with m.SessionLocal() as db:
        note=db.query(n.Notice).one();assert note.state=='pending'
        note.next_at=m.now()-timedelta(seconds=1);db.commit()
    asyncio.run(w.deliver(m,object()))
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='sent'
        assert db.query(m.Player).one().ore==101


def test_orphaned_event_does_not_block_recovery():
    enqueue(count=1);advance()
    with m.SessionLocal() as db:db.query(n.Notice).delete();db.commit()
    w.repair_recent(m)
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='pending'
        assert db.query(n.NoticeEvent).count()==1


def test_end_to_end_timer_posts_second_channel_message(monkeypatch):
    """Lifecycle, real queue tick, outbox, renderer and channel.send in one test."""
    import threading
    from fastapi.testclient import TestClient
    monkeypatch.setenv('DISCORD_BOT_TOKEN','fake')
    enqueue(count=1)
    sent=threading.Event();room=channel()
    async def send(**kwargs):sent.set();return SimpleNamespace(id=123)
    room.send=AsyncMock(side_effect=send)
    async def close():pass
    async def login(runtime):
        runtime.client=SimpleNamespace(get_channel=lambda _:room,close=close)
        runtime.state='ready';return True
    monkeypatch.setattr(w.Runtime,'login',login)
    with m.SessionLocal() as db:
        destination=db.query(n.Destination).one();destination.recipient='123';destination.message_channel='456'
        db.query(q.TaskQueue).one().next_at=m.now()-timedelta(seconds=1);db.commit()
    with TestClient(m.app):assert sent.wait(8)
    assert room.send.await_count==1
    assert room.send.call_args.kwargs['content']=='<@123> Your queue has finished.'
    with m.SessionLocal() as db:
        assert db.query(n.Notice).one().state=='sent'
        assert db.query(m.Player).one().ore==101
