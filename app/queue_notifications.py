"""Durable completion outbox, delivered independently of requests and gameplay.

Queue completion and its immutable notification commit together. Delivery leases
avoid competing workers sending concurrently. Discord nonces suppress immediate
retry duplicates; a crash after remote acceptance can still cause a duplicate
outside the platform's deduplication window. No gameplay action is retried here.
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import timedelta
from contextvars import ContextVar
import requests
from sqlalchemy import Column, String, Text, Integer, DateTime, select, update
from .db import Base
from . import runtime
from .db import SessionLocal
from .models import Identity

origin_channel=ContextVar('queue_origin_channel',default='')

class Destination(Base):
    __tablename__='queue_destinations_v1'
    channel_id=Column(String(64),primary_key=True)
    canonical_uid=Column(String(96),primary_key=True)
    run_id=Column(String(32),nullable=False)
    provider=Column(String(16),nullable=False)
    recipient=Column(String(96),nullable=False)
    message_channel=Column(String(64),nullable=False,default='')

class Notice(Base):
    __tablename__='queue_notifications_v1'
    id=Column(String(32),primary_key=True)
    provider=Column(String(16),nullable=False)
    recipient=Column(String(96),nullable=False)
    message_channel=Column(String(64),nullable=False,default='')
    channel_id=Column(String(64),nullable=False)
    content=Column(Text,nullable=False)
    state=Column(String(16),nullable=False,default='pending')
    attempts=Column(Integer,nullable=False,default=0)
    next_at=Column(DateTime(timezone=True),nullable=False)
    error=Column(String(200),nullable=False,default='')


class NoticeTask(Base):
    """The queue each alert describes, so its Repeat button restarts exactly that task."""
    __tablename__='queue_notice_tasks_v1'
    notice_id=Column(String(32),primary_key=True)
    task=Column(String(96),nullable=False)
    total=Column(Integer,nullable=False)


class NoticeEvent(Base):
    """Additive event metadata supports old completion notices without migration."""
    __tablename__='queue_notice_events_v1'
    notice_id=Column(String(32),primary_key=True)
    run_id=Column(String(32),nullable=False,index=True)
    kind=Column(String(16),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)


def dismiss_pause(db, dest):
    if dest is None:return
    ids=select(NoticeEvent.notice_id).where(NoticeEvent.run_id==dest.run_id,NoticeEvent.kind=='paused')
    db.execute(update(Notice).where(Notice.id.in_(ids),Notice.state=='pending').values(state='superseded'))
    from . import quiet_hours
    quiet_hours.forget_superseded(db,ids)      # a pause held for quiet hours is never sent now


def destination(db,p):
    dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    if dest is None:
        identity=db.execute(select(Identity).where(Identity.channel_id==p.channel_id,
            Identity.canonical_uid==p.twitch_uid,Identity.provider=='discord')).scalars().first()
        if identity:start(db,p,'discord',identity.provider_uid)
        else:start(db,p,'twitch',p.twitch_uid)
        db.flush();dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    return dest


def stopped(db,p,queue,kind,reason='',following=''):
    from .game.life import life_state
    from .progression import announce
    dest=destination(db,p)
    dismiss_pause(db,dest)
    from .task_queue import choices, totals_text
    from . import qol
    mode=qol.alert_mode(db,p.channel_id,p.twitch_uid)
    title={'paused':'PAUSED','cancelled':'CANCELLED','error':'STOPPED','completed':'COMPLETED'}[kind]
    content=(f'TASK QUEUE — {title}\n{choices().get(queue.task,queue.task)}\n'
             f'Attempts completed: {queue.total-queue.remaining}/{queue.total}; remaining: {queue.remaining}.\n'
             +totals_text(db,queue))
    if reason:content+='\n\nPAUSE REASON\n'+reason
    if kind=='paused':
        content+='\n\nNEXT\nRemaining attempts are saved. The queue resumes automatically when requirements are met.'
        life=life_state(db,p);eta=qol.resume_eta(life)
        if eta and len(qol.needs.blocked_needs(life))>1:content+=f' Passive recovery clears every blocking need in about {qol.eta_text(eta)}.'
    if following:content+='\n\nNEXT\n'+following
    if kind=='error':content+='\n\nNEXT\nAutomatic retries stopped. Check /queue before starting another queue.'
    if kind=='completed' and queue.total>=3:
        from . import stream_overlay
        stream_overlay.queue_finished(db,p,queue)
    # Completion retains the historical run ID to deduplicate pre-update rows.
    notice_id=dest.run_id if kind=='completed' else uuid.uuid4().hex
    if db.get(Notice,notice_id) is None:
        # Alert preferences decide whether a chat message is sent; the journal
        # and /queue keep every result either way.
        pinged=mode in {'mention','dm'} or (mode=='quiet' and kind!='paused')
        from . import inbox
        inbox.add(db,p.channel_id,p.twitch_uid,'queue',inbox_text(db,queue,kind,reason,following),seen=pinged)
        if pinged:
            target=dest.message_channel
            # Direct messages for every alert except an explicit channel mention, so alerts never fill the channel.
            if mode in {'dm','quiet'} and dest.provider=='discord':target=DM_PREFIX+(dest.message_channel or os.getenv('DISCORD_GAME_CHANNEL_ID',''))
            db.add(Notice(id=notice_id,provider=dest.provider,recipient=dest.recipient,
                          channel_id=p.channel_id,message_channel=target,content=content,next_at=runtime.now()))
            db.add(NoticeEvent(notice_id=notice_id,run_id=dest.run_id,kind=kind,created_at=runtime.now()))
            info=db.get(NoticeTask,notice_id)
            if info is None:db.add(NoticeTask(notice_id=notice_id,task=queue.task,total=queue.total))
            else:info.task,info.total=queue.task,queue.total
        announce(db,p,content[:1800],runtime.now())


DM_PREFIX='dm|'


def dm_closed(notice,at=None):
    """The player's DMs are closed: keep the alert private instead of posting it in the game channel.
    Its notification (saved when the alert was made) is marked unread, so it pops up privately the
    next time they use a command or button. `at`: when the alert was made (an alert held for quiet
    hours is older than the newest notification), so its own notification is the one marked; one not
    marked yet, so several held alerts mark one each."""
    from . import inbox
    with SessionLocal() as db:
        uid=inbox._canonical(db,str(notice.recipient))
        query=select(inbox.InboxItem).where(inbox.InboxItem.channel_id==notice.channel_id,inbox.InboxItem.canonical_uid==uid,
                                            inbox.InboxItem.kind=='queue')
        if at is not None:query=query.where(inbox.InboxItem.created_at<=at,inbox.InboxItem.seen==1)
        row=db.execute(query.order_by(inbox.InboxItem.id.desc())).scalars().first()
        if row is not None:row.seen=0
        db.commit()


def inbox_text(db,queue,kind,reason='',following=''):
    """One or two lines for the private inbox and popups."""
    from .game.players import resource_name
    from .task_queue import choices, QueueTotals
    import json as _json
    name=choices().get(queue.task,queue.task)
    head={'paused':'⏸️ **Queue paused**','cancelled':'⏹️ **Queue cancelled**','error':'⛔ **Queue stopped**','completed':'✅ **Queue finished**'}[kind]
    text=f'{head}: {name} · {queue.total-queue.remaining}/{queue.total}'
    totals=db.get(QueueTotals,(queue.channel_id,queue.canonical_uid))
    gained=_json.loads(totals.gained) if totals else {}
    if gained:text+=' · gained '+', '.join(f'{resource_name(k)} ×{v}' for k,v in sorted(gained.items())[:4])
    if kind=='paused' and reason:text+='\n'+reason.split('\n')[0][:200]+' It resumes by itself.'
    if following:text+='\n'+following
    return text


def needs_blocked(db,p):
    from .game.life import life_state
    from .needs import blocked_needs
    return bool(blocked_needs(life_state(db,p)))


def start(db,p,provider,uid):
    row=db.get(Destination,(p.channel_id,p.twitch_uid))
    if row is not None:dismiss_pause(db,row)
    if row is None:
        row=Destination(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row)
    row.run_id=uuid.uuid4().hex;row.provider=provider;row.recipient=uid
    row.message_channel=origin_channel.get() or os.getenv('DISCORD_GAME_CHANNEL_ID','') if provider=='discord' else ''


def complete(db,p,queue,summary,following=''):
    stopped(db,p,queue,'completed',following=following)


def renew(db,row):
    """A new run for a chained queue, keeping where its alerts are delivered."""
    if row is None:return
    dismiss_pause(db,row)
    row.run_id=uuid.uuid4().hex


def delivery_status(db,queue):
    from .game.base import app
    from . import qol, quiet_hours
    mode=qol.alert_mode(db,queue.channel_id,queue.canonical_uid)
    if mode=='off':return 'Queue alerts are off (/settings or !settings alerts dm turns them back on). Your results are saved here.'
    dest=db.get(Destination,(queue.channel_id,queue.canonical_uid))
    notice=None
    if dest:
        notice=db.execute(select(Notice).join(NoticeEvent,Notice.id==NoticeEvent.notice_id).where(
            NoticeEvent.run_id==dest.run_id,Notice.state!='superseded').order_by(NoticeEvent.created_at.desc())).scalars().first()
        notice=notice or db.get(Notice,dest.run_id)
    if notice and notice.state=='sent':return 'Queue notification sent.'
    if notice and notice.state=='failed':return 'Queue notification could not be delivered. '+notice.error+'. Your results are saved here and in your journal.'
    if dest and dest.provider=='discord' and not os.getenv('DISCORD_BOT_TOKEN','').strip():
        return 'Queue notification could not be delivered: DISCORD_BOT_TOKEN is missing on the server. Your results are saved.'
    sender=getattr(app.state,'discord_queue',None)
    if dest and dest.provider=='discord' and sender and sender.state in {'invalid_token','wrong_application','connection_error','stopped'}:
        reason={'wrong_application':'the bot token does not match DISCORD_APPLICATION_ID','invalid_token':'the Discord bot token was rejected','connection_error':'Discord authentication is temporarily unavailable','stopped':'the Discord sender is stopped'}[sender.state]
        return 'Queue notification could not be delivered: '+reason+'. Your results are saved.'
    if notice:
        held=quiet_hours.held_line(db,notice)
        return held or 'Queue notification is waiting for delivery. Your results are saved.'
    quiet=''
    if mode in {'dm','quiet'} and dest is not None and dest.provider=='discord':
        quiet=quiet_hours.delivery_line(db,queue.channel_id,queue.canonical_uid,runtime.now())
        quiet=' '+quiet if quiet else ''
    if mode=='quiet':return 'Quiet alerts: a direct message when the queue finishes or stops, not when it pauses.'+quiet
    if mode=='private':return 'Private alerts: results appear only to you, the next time you use a command or button.'
    if mode=='dm':return 'You will get a direct message when the queue pauses or stops (in your Notifications instead if your DMs are closed).'+quiet
    return 'You will be @mentioned in the game channel when the queue pauses or stops, if delivery is configured.'


def merge(db,channel,source,target,keep_source):
    src=db.get(Destination,(channel,source));dst=db.get(Destination,(channel,target))
    if keep_source:
        if dst:db.delete(dst);db.flush()
        if src:src.canonical_uid=target
    elif src:db.delete(src)


class DeliveryError(Exception):
    def __init__(self,reason,permanent=False,delay=30):
        super().__init__(reason);self.permanent=permanent;self.delay=delay


def post(url,headers,payload):
    try:response=requests.post(url,headers=headers,json=payload,timeout=8)
    except requests.RequestException:raise DeliveryError('Notification network request failed') from None
    if response.status_code==429:
        try:delay=max(1,min(3600,float(response.json().get('retry_after',30))))
        except (ValueError,TypeError):delay=30
        raise DeliveryError('Notification rate limited',delay=delay)
    if not 200<=response.status_code<300:
        raise DeliveryError(f'Notification HTTP {response.status_code}',permanent=response.status_code in {400,401,403,404})
    try:return response.json()
    except ValueError:raise DeliveryError('Invalid notification response') from None


def send(notice):
    """Legacy synchronous transport; the production poller selects Twitch only.

    Discord production delivery lives in discord_queue_worker.send_notice.
    """
    provider=notice.provider;recipient=notice.recipient
    if provider=='discord':
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        if not token:raise DeliveryError('DISCORD_BOT_TOKEN is missing')
        if not notice.message_channel:raise DeliveryError('Discord game channel is missing')
        headers={'Authorization':'Bot '+token}
        try:payload=runtime._discord_json_message(notice.content,message_type='queue')['data']
        except Exception:payload={}
        kind='paused' if 'QUEUE — PAUSED' in notice.content else 'cancelled' if 'QUEUE — CANCELLED' in notice.content else 'stopped after an error' if 'QUEUE — STOPPED' in notice.content else 'finished'
        payload.update({'content':f'<@{recipient}> Your queue has {kind}.' if kind in {'paused','finished'} else f'<@{recipient}> Your queue was {kind}.',
                        'allowed_mentions':{'parse':[],'users':[recipient]},
                        'nonce':notice.id[:25],'enforce_nonce':True})
        url='https://discord.com/api/v10/channels/'+notice.message_channel+'/messages'
        if not payload.get('embeds'):payload['content']+='\n'+notice.content[:1800]
        try:result=post(url,headers,payload)
        except DeliveryError as exc:
            # Some channels permit text but disallow embeds. Deliver the stop
            # reason and totals in plain text before declaring delivery failed.
            if str(exc)!='Notification HTTP 403' or not payload.get('embeds'):raise
            payload.pop('embeds',None);payload.pop('components',None)
            payload['content']+='\n'+notice.content[:1800]
            result=post(url,headers,payload)
        if not result.get('id'):raise DeliveryError('Discord did not confirm message delivery')
        return
    if provider!='twitch':raise DeliveryError('Unsupported notification platform',permanent=True)
    try:channels=json.loads(os.getenv('TWITCH_QUEUE_CHANNELS','{}'))
    except ValueError:raise DeliveryError('TWITCH_QUEUE_CHANNELS is invalid',permanent=True)
    broadcaster=channels.get(notice.channel_id) if isinstance(channels,dict) else None
    token=os.getenv('TWITCH_BOT_ACCESS_TOKEN','');client=os.getenv('TWITCH_CLIENT_ID','');sender=os.getenv('TWITCH_BOT_USER_ID','')
    if not all((broadcaster,token,client,sender)):raise DeliveryError('Twitch notification configuration is missing')
    headers={'Authorization':'Bearer '+token,'Client-Id':client}
    # Twitch IDs, rather than display names, resolve the intended recipient.
    try:
        response=requests.get('https://api.twitch.tv/helix/users',headers=headers,params={'id':recipient},timeout=8)
        response.raise_for_status();login=response.json()['data'][0]['login']
    except (requests.RequestException,ValueError,KeyError,IndexError):raise DeliveryError('Twitch recipient lookup failed') from None
    from .presentation import plain_times
    text='@'+login+' '+plain_times(notice.content).replace('\n',' | ')
    if len(text)>490:text=text[:440]+'… Use !queue for the full totals.'
    result=post('https://api.twitch.tv/helix/chat/messages',headers,
        {'broadcaster_id':str(broadcaster),'sender_id':sender,'message':text,'for_source_only':True})
    if not result.get('data') or not result['data'][0].get('is_sent'):
        raise DeliveryError('Twitch did not send the notification')


def deliver(provider=None):
    with SessionLocal() as db:
        query=select(Notice.id).where(Notice.state.in_(['pending','sending']),Notice.next_at<=runtime.now())
        if provider:query=query.where(Notice.provider==provider)
        ids=list(db.scalars(query.limit(50)))
    for notice_id in ids:
        with SessionLocal() as db:
            claimed=db.execute(update(Notice).where(Notice.id==notice_id,Notice.state.in_(['pending','sending']),
                Notice.next_at<=runtime.now()).values(state='sending',next_at=runtime.now()+timedelta(seconds=120),attempts=Notice.attempts+1))
            db.commit()
            if claimed.rowcount!=1:continue
            row=db.get(Notice,notice_id)
            try:send(row)
            except DeliveryError as exc:
                row.state='failed' if exc.permanent or row.attempts>=5 else 'pending'
                row.error=str(exc);row.next_at=runtime.now()+timedelta(seconds=max(exc.delay,min(600,30*2**(row.attempts-1))))
            except Exception:
                # Do not print credentials, URLs, response bodies or player text.
                row.state='failed' if row.attempts>=5 else 'pending';row.error='Unexpected notification error'
                row.next_at=runtime.now()+timedelta(seconds=60)
            else:row.state='sent';row.error=''
            db.commit()


def install(m):
    from .game.base import app
    Destination.__table__.create(runtime.engine,checkfirst=True);Notice.__table__.create(runtime.engine,checkfirst=True);NoticeEvent.__table__.create(runtime.engine,checkfirst=True)
    NoticeTask.__table__.create(runtime.engine,checkfirst=True)
    async def loop():
        while not app.state.notification_stop.is_set():
            try:await asyncio.to_thread(deliver,'twitch')
            except Exception:logging.getLogger(__name__).error('Notification worker will retry')
            try:await asyncio.wait_for(app.state.notification_stop.wait(),timeout=2)
            except asyncio.TimeoutError:pass
    async def start_worker():
        app.state.notification_stop=asyncio.Event()
        app.state.notification_worker=asyncio.create_task(loop())
    async def stop_worker():
        app.state.notification_stop.set();await app.state.notification_worker
    app.add_event_handler('startup',start_worker);app.add_event_handler('shutdown',stop_worker)
    from . import discord_queue_worker
    discord_queue_worker.install(m)
