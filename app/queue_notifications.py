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


def start(m,db,p,provider,uid):
    row=db.get(Destination,(p.channel_id,p.twitch_uid))
    if row is None:
        row=Destination(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row)
    row.run_id=uuid.uuid4().hex;row.provider=provider;row.recipient=uid
    row.message_channel=origin_channel.get() or os.getenv('DISCORD_GAME_CHANNEL_ID','') if provider=='discord' else ''


def complete(m,db,p,queue,summary):
    dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    if dest is None:
        # Upgrade of a running queue: prefer a verified Discord identity.
        identity=db.execute(select(m.Identity).where(m.Identity.channel_id==p.channel_id,
            m.Identity.canonical_uid==p.twitch_uid,m.Identity.provider=='discord')).scalars().first()
        if identity:start(m,db,p,'discord',identity.provider_uid)
        else:start(m,db,p,'twitch',p.twitch_uid)
        db.flush();dest=db.get(Destination,(p.channel_id,p.twitch_uid))
    from .task_queue import choices
    content=(f'New Eridian v2 — QUEUE COMPLETED\n{choices(m).get(queue.task,queue.task)}\n'
             f'Attempts completed: {queue.total}/{queue.total}\n{summary}')
    m.announce(db,p,content[:1800],m.now())
    if db.get(Notice,dest.run_id) is None:
        db.add(Notice(id=dest.run_id,provider=dest.provider,recipient=dest.recipient,
                      channel_id=p.channel_id,message_channel=dest.message_channel,content=content,next_at=m.now()))


def delivery_status(db,queue):
    if queue.state=='cancelled':return 'Cancelled queues do not send completion notifications.'
    dest=db.get(Destination,(queue.channel_id,queue.canonical_uid))
    notice=db.get(Notice,dest.run_id) if dest else None
    if notice:
        if notice.state=='sent':return 'Completion notification sent.'
        if notice.state=='failed':return 'Completion notification could not be delivered. Your results are saved here and in your journal.'
        return 'Completion notification is waiting for delivery. Your results are saved.'
    return 'Completion notification: you will be @mentioned in the game channel when delivery is configured. Results are also saved in your journal.'


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
    provider=notice.provider;recipient=notice.recipient
    if provider=='discord':
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        if not token:raise DeliveryError('DISCORD_BOT_TOKEN is missing')
        if not notice.message_channel:raise DeliveryError('Discord game channel is missing')
        headers={'Authorization':'Bot '+token}
        result=post('https://discord.com/api/v10/channels/'+notice.message_channel+'/messages',headers,
                    {'content':f'<@{recipient}> Your queue is finished!\n'+notice.content[:1850],
                     'allowed_mentions':{'parse':[],'users':[recipient]},
                     'nonce':notice.id[:25],'enforce_nonce':True})
        if not result.get('id'):raise DeliveryError('Discord did not confirm message delivery')
        return
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


def deliver(m):
    with m.SessionLocal() as db:
        ids=list(db.execute(select(Notice.id).where(Notice.state.in_(['pending','sending']),Notice.next_at<=m.now()).limit(50)).scalars())
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
    Destination.__table__.create(m.engine,checkfirst=True);Notice.__table__.create(m.engine,checkfirst=True)
    async def loop():
        while not m.app.state.notification_stop.is_set():
            try:await asyncio.to_thread(deliver,m)
            except Exception:logging.getLogger(__name__).error('Notification worker will retry')
            try:await asyncio.wait_for(m.app.state.notification_stop.wait(),timeout=2)
            except asyncio.TimeoutError:pass
    async def start_worker():
        m.app.state.notification_stop=asyncio.Event()
        m.app.state.notification_worker=asyncio.create_task(loop())
    async def stop_worker():
        m.app.state.notification_stop.set();await m.app.state.notification_worker
    m.app.add_event_handler('startup',start_worker);m.app.add_event_handler('shutdown',stop_worker)
