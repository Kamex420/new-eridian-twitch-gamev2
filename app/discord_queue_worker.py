"""Discord.py channel alerts, independent of expiring interaction tokens.

Slash commands remain HTTP interactions. An authenticated discord.Client supplies
asynchronous REST channel operations; no gateway connection or privileged intent
is needed. A tasks.Loop drains only Discord outbox rows. Game work and Twitch
notifications have separate workers, so unavailable Discord cannot stop mining.
"""
import asyncio
import logging
import os
import time
from contextlib import suppress
from datetime import timedelta
from types import SimpleNamespace
import discord
from discord.ext import tasks
from sqlalchemy import select, update
from . import queue_notifications as n

log=logging.getLogger('uvicorn.error.discord_queue')


def claim(m,notice_id):
    with m.SessionLocal() as db:
        result=db.execute(update(n.Notice).where(n.Notice.id==notice_id,n.Notice.provider=='discord',
            n.Notice.state.in_(['pending','sending']),n.Notice.next_at<=m.now()).values(
                state='sending',next_at=m.now()+timedelta(seconds=120),attempts=n.Notice.attempts+1))
        db.commit()
        if result.rowcount!=1:return None
        row=db.get(n.Notice,notice_id)
        return SimpleNamespace(**{key:getattr(row,key) for key in
            ('id','recipient','message_channel','content','attempts','provider','channel_id')})


def pending(m):
    with m.SessionLocal() as db:
        return list(db.scalars(select(n.Notice.id).where(n.Notice.provider=='discord',
            n.Notice.state.in_(['pending','sending']),n.Notice.next_at<=m.now()).order_by(n.Notice.next_at).limit(10)))


def finish(m,notice,error=None):
    with m.SessionLocal() as db:
        row=db.get(n.Notice,notice.id)
        if not row or row.state!='sending' or row.attempts!=notice.attempts:return
        if error:
            row.state='failed' if error.permanent or row.attempts>=5 else 'pending'
            row.error=str(error)
            row.next_at=m.now()+timedelta(seconds=max(error.delay,min(600,30*2**(row.attempts-1))))
            log.warning('Discord queue alert %s: %s',row.state,row.error)
        else:
            row.state='sent';row.error=''
            log.info('Discord queue alert sent')
        db.commit()


def repair_recent(m):
    """One startup recovery of current stopped runs, not all historical alerts."""
    from .task_queue import TaskQueue,atomic
    with m.SessionLocal() as db:
        keys=list(db.execute(select(TaskQueue.channel_id,TaskQueue.canonical_uid).where(
            TaskQueue.state.in_(['paused','completed','cancelled','error']),
            TaskQueue.next_at>=m.now()-timedelta(hours=24))))
    for channel,uid in keys:
        with atomic(m,channel):
            with m.SessionLocal() as db:
                queue=db.get(TaskQueue,(channel,uid));dest=db.get(n.Destination,(channel,uid))
                if not dest or dest.provider!='discord' or queue.state not in {'paused','completed','cancelled','error'}:continue
                event=db.execute(select(n.NoticeEvent).where(n.NoticeEvent.run_id==dest.run_id,
                    n.NoticeEvent.kind==queue.state).order_by(n.NoticeEvent.created_at.desc())).scalars().first()
                notice=db.get(n.Notice,event.notice_id if event else dest.run_id)
                if notice and notice.state=='failed':
                    notice.state='pending';notice.attempts=0;notice.next_at=m.now();notice.error=''
                    if not notice.message_channel:notice.message_channel=dest.message_channel or os.getenv('DISCORD_GAME_CHANNEL_ID','')
                elif notice is None:
                    if event and event.notice_id==dest.run_id:
                        db.delete(event);db.flush()
                    player=db.execute(select(m.Player).where(m.Player.channel_id==channel,m.Player.twitch_uid==uid)).scalar_one_or_none()
                    if player:n.stopped(m,db,player,queue,queue.state,queue.result if queue.state!='completed' else '')
                db.commit()


def payload(m,notice):
    # Formatting may read/write snapshot pages, so callers run it off-loop.
    try:data=m._discord_json_message(notice.content,message_type='queue')['data']
    except Exception:data={}
    kind='paused' if 'QUEUE — PAUSED' in notice.content else 'cancelled' if 'QUEUE — CANCELLED' in notice.content else 'stopped after an error' if 'QUEUE — STOPPED' in notice.content else 'finished'
    mention=f'<@{notice.recipient}> Your queue '+('has ' if kind in {'paused','finished'} else 'was ')+kind+'.'
    return data,mention


async def send_notice(m,client,notice):
    channel_id=notice.message_channel or os.getenv('DISCORD_GAME_CHANNEL_ID','')
    if not str(channel_id).isdigit() or not str(notice.recipient).isdigit():
        raise n.DeliveryError('A numeric Discord channel and player ID are required',permanent=True)
    channel=client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    if not isinstance(channel,(discord.TextChannel,discord.Thread)):
        raise n.DeliveryError('Queue alerts require a server text channel or thread; DMs are disabled',permanent=True)
    data,mention=await asyncio.to_thread(payload,m,notice)
    allowed=discord.AllowedMentions(everyone=False,roles=False,users=[discord.Object(id=int(notice.recipient))],replied_user=False)
    args={'content':mention,'allowed_mentions':allowed,'silent':False,'nonce':notice.id[:25]}
    if data.get('embeds'):
        args['embeds']=[discord.Embed.from_dict(x) for x in data['embeds']]
        if data.get('components'):
            view=discord.ui.View(timeout=None)
            for row in data['components']:
                for item in row.get('components',[]):
                    if item.get('type')==2:view.add_item(discord.ui.Button(label=item['label'],style=discord.ButtonStyle(item['style']),custom_id=item['custom_id']))
            args['view']=view
    else:args['content']+='\n'+notice.content[:1800]
    try:await channel.send(**args)
    except discord.Forbidden:
        if 'embeds' not in args:raise
        args.pop('embeds',None);args.pop('view',None)
        args['content']=mention+'\n'+notice.content[:1800]
        await channel.send(**args)


async def deliver(m,client,stop=None):
    for notice_id in await asyncio.to_thread(pending,m):
        if stop is not None and stop.is_set():break
        notice=await asyncio.to_thread(claim,m,notice_id)
        if notice is None:continue
        error=None
        try:
            # Leave headroom within the lease even if Discord waits on a rate limit.
            await asyncio.wait_for(send_notice(m,client,notice),timeout=45)
        except n.DeliveryError as exc:error=exc
        except discord.Forbidden:error=n.DeliveryError('Discord denied channel access or Send Messages permission (403)',permanent=True)
        except discord.NotFound:error=n.DeliveryError('Discord game channel was not found (404)',permanent=True)
        except discord.HTTPException as exc:error=n.DeliveryError(f'Discord HTTP {exc.status}',permanent=exc.status in {400,401,403,404})
        except (TimeoutError,OSError):error=n.DeliveryError('Discord send timed out or the network is unavailable')
        except Exception:error=n.DeliveryError('Unexpected Discord queue delivery error')
        await asyncio.to_thread(finish,m,notice,error)


class Runtime:
    def __init__(self,m):
        self.m=m;self.client=None;self.state='starting';self.retry_at=0;self.repaired=False;self.stop=asyncio.Event()

    async def close_client(self):
        if self.client:
            client=self.client;self.client=None
            with suppress(Exception):await client.close()

    async def login(self):
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        if not token:
            if self.state!='missing_token':log.error('Queue channel pings disabled: DISCORD_BOT_TOKEN is missing')
            self.state='missing_token';return False
        if time.monotonic()<self.retry_at:return False
        client=discord.Client(intents=discord.Intents.none(),allowed_mentions=discord.AllowedMentions.none())
        self.client=client
        try:
            await client.__aenter__()
            await asyncio.wait_for(client.login(token),timeout=20)
        except discord.LoginFailure:
            self.state='invalid_token';log.error('Discord queue bot login failed: check DISCORD_BOT_TOKEN')
        except Exception:
            self.state='connection_error';log.error('Discord queue bot could not authenticate; retrying in 30 seconds')
        else:
            expected=os.getenv('DISCORD_APPLICATION_ID','').strip()
            if expected and str(client.user.id)!=expected:
                self.state='wrong_application';log.error('Discord queue bot token does not match DISCORD_APPLICATION_ID')
                await self.close_client();self.retry_at=time.monotonic()+30;return False
            self.state='ready';log.info('Discord.py queue channel sender authenticated')
            return True
        await self.close_client();self.retry_at=time.monotonic()+30;return False

    @tasks.loop(seconds=2,reconnect=True)
    async def polling(self):
        try:
            if self.client is None and not await self.login():return
            if not self.repaired:
                try:
                    await asyncio.to_thread(repair_recent,self.m);self.repaired=True
                except Exception:log.error('Recent alert recovery failed; normal pending delivery will continue')
            await deliver(self.m,self.client,self.stop)
        except Exception:log.error('Discord queue worker error; pending alerts will retry')

    async def start(self):
        return self.polling.start()

    async def close(self):
        self.stop.set();self.polling.stop()
        task=self.polling.get_task()
        if task:
            with suppress(asyncio.CancelledError):await task
        await self.close_client();self.state='stopped'


def install(m):
    async def start():
        runtime=Runtime(m);m.app.state.discord_queue=runtime
        m.app.state.discord_notification_worker=await runtime.start()
    async def stop():
        runtime=getattr(m.app.state,'discord_queue',None)
        if runtime:await runtime.close()
    m.app.add_event_handler('startup',start);m.app.add_event_handler('shutdown',stop)
