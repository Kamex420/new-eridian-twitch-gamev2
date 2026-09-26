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


def destination(m,db,p):
    dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    if dest is None:
        identity=db.execute(select(m.Identity).where(m.Identity.channel_id==p.channel_id,
            m.Identity.canonical_uid==p.twitch_uid,m.Identity.provider=='discord')).scalars().first()
        if identity:start(m,db,p,'discord',identity.provider_uid)
        else:start(m,db,p,'twitch',p.twitch_uid)
        db.flush();dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    return dest


def stopped(m,db,p,queue,kind,reason=''):
    dest=destination(m,db,p)
    dismiss_pause(db,dest)
    from .task_queue import choices, totals_text
    title={'paused':'PAUSED','cancelled':'CANCELLED','error':'STOPPED','completed':'COMPLETED'}[kind]
    content=(f'TASK QUEUE — {title}\n{choices(m).get(queue.task,queue.task)}\n'
             f'Attempts completed: {queue.total-queue.remaining}/{queue.total}; remaining: {queue.remaining}.\n'
             +totals_text(m,db,queue))
    if reason:content+='\n\nPAUSE REASON\n'+reason
    if kind=='paused':content+='\n\nNEXT\nRemaining attempts are saved. The queue resumes automatically when requirements are met.'
    if kind=='error':content+='\n\nNEXT\nAutomatic retries stopped. Check /queue before starting another queue.'
    # Completion retains the historical run ID to deduplicate pre-update rows.
    notice_id=dest.run_id if kind=='completed' else uuid.uuid4().hex
    if db.get(Notice,notice_id) is None:
        db.add(Notice(id=notice_id,provider=dest.provider,recipient=dest.recipient,
                      channel_id=p.channel_id,message_channel=dest.message_channel,content=content,next_at=m.now()))
        db.add(NoticeEvent(notice_id=notice_id,run_id=dest.run_id,kind=kind,created_at=m.now()))
        m.announce(db,p,content[:1800],m.now())


def start(m,db,p,provider,uid):
    row=db.get(Destination,(p.channel_id,p.twitch_uid))
    if row is not None:dismiss_pause(db,row)
    if row is None:
        row=Destination(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row)
    row.run_id=uuid.uuid4().hex;row.provider=provider;row.recipient=uid
    row.message_channel=origin_channel.get() or os.getenv('DISCORD_GAME_CHANNEL_ID','') if provider=='discord' else ''


def complete(m,db,p,queue,summary):
    stopped(m,db,p,queue,'completed')


def delivery_status(db,queue,m=None):
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
    runtime=getattr(m.app.state,'discord_queue',None) if m is not None else None
    if dest and dest.provider=='discord' and runtime and runtime.state in {'invalid_token','wrong_application','connection_error','stopped'}:
        reason={'wrong_application':'the bot token does not match DISCORD_APPLICATION_ID','invalid_token':'the Discord bot token was rejected','connection_error':'Discord authentication is temporarily unavailable','stopped':'the Discord sender is stopped'}[runtime.state]
        return 'Queue notification could not be delivered: '+reason+'. Your results are saved.'
    if notice:
        return 'Queue notification is waiting for delivery. Your results are saved.'
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


def send(m,notice):
    """Legacy synchronous transport; the production poller selects Twitch only.

    Discord production delivery lives in discord_queue_worker.send_notice.
    """
    provider=notice.provider;recipient=notice.recipient
    if provider=='discord':
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        if not token:raise DeliveryError('DISCORD_BOT_TOKEN is missing')
        if not notice.message_channel:raise DeliveryError('Discord game channel is missing')
        headers={'Authorization':'Bot '+token}
        try:payload=m._discord_json_message(notice.content,message_type='queue')['data']
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
    text='@'+login+' '+notice.content.replace('\n',' | ')
    if len(text)>490:text=text[:440]+'… Use !queue for the full totals.'
    result=post('https://api.twitch.tv/helix/chat/messages',headers,
        {'broadcaster_id':str(broadcaster),'sender_id':sender,'message':text,'for_source_only':True})
    if not result.get('data') or not result['data'][0].get('is_sent'):
        raise DeliveryError('Twitch did not send the notification')


def deliver(m,provider=None):
    with m.SessionLocal() as db:
        query=select(Notice.id).where(Notice.state.in_(['pending','sending']),Notice.next_at<=m.now())
        if provider:query=query.where(Notice.provider==provider)
        ids=list(db.scalars(query.limit(50)))
    for notice_id in ids:
        with m.SessionLocal() as db:
            claimed=db.execute(update(Notice).where(Notice.id==notice_id,Notice.state.in_(['pending','sending']),
                Notice.next_at<=m.now()).values(state='sending',next_at=m.now()+timedelta(seconds=120),attempts=Notice.attempts+1))
            db.commit()
            if claimed.rowcount!=1:continue
            row=db.get(Notice,notice_id)
            try:send(m,row)
            except DeliveryError as exc:
                row.state='failed' if exc.permanent or row.attempts>=5 else 'pending'
                row.error=str(exc);row.next_at=m.now()+timedelta(seconds=max(exc.delay,min(600,30*2**(row.attempts-1))))
            except Exception:
                # Do not print credentials, URLs, response bodies or player text.
                row.state='failed' if row.attempts>=5 else 'pending';row.error='Unexpected notification error'
                row.next_at=m.now()+timedelta(seconds=60)
            else:row.state='sent';row.error=''
            db.commit()


def install(m):
    Destination.__table__.create(m.engine,checkfirst=True);Notice.__table__.create(m.engine,checkfirst=True);NoticeEvent.__table__.create(m.engine,checkfirst=True)
    async def loop():
        while not m.app.state.notification_stop.is_set():
            try:await asyncio.to_thread(deliver,m,'twitch')
            except Exception:logging.getLogger(__name__).error('Notification worker will retry')
            try:await asyncio.wait_for(m.app.state.notification_stop.wait(),timeout=2)
            except asyncio.TimeoutError:pass
    async def start_worker():
        m.app.state.notification_stop=asyncio.Event()
        m.app.state.notification_worker=asyncio.create_task(loop())
    async def stop_worker():
        m.app.state.notification_stop.set();await m.app.state.notification_worker
    m.app.add_event_handler('startup',start_worker);m.app.add_event_handler('shutdown',stop_worker)
    from . import discord_queue_worker
    discord_queue_worker.install(m)
