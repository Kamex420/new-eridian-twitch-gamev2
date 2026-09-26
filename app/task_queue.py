"""Persistent, bounded work queues. Each attempt and its counter commit together."""
import asyncio, logging, json, hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from sqlalchemy import Column,String,Integer,DateTime,Text,select,text
from .db import Base, connection_context
from . import seed_content as s, crafting_progression as cp, task_yields, queue_notifications

class TaskQueue(Base):
    """One saved task per canonical citizen and world; remaining counts attempts.

    Paused rows stay active so a second task cannot replace them accidentally.
    Completed/cancelled rows retain their last result until the next queue starts.
    """
    __tablename__='task_queues_v1'
    channel_id=Column(String(64),primary_key=True)
    canonical_uid=Column(String(96),primary_key=True)
    task=Column(String(96),nullable=False)
    total=Column(Integer,nullable=False)
    remaining=Column(Integer,nullable=False)
    state=Column(String(20),nullable=False,default='running')
    result=Column(Text,nullable=False,default='Waiting for the first attempt.')
    next_at=Column(DateTime(timezone=True),nullable=False)

class QueueTotals(Base):
    """Separate additive table preserves existing queues without guessing history."""
    __tablename__ = 'task_queue_totals_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    progress = Column(Integer, nullable=False, default=0)
    gained = Column(Text, nullable=False, default='{}')
    used = Column(Text, nullable=False, default='{}')


class QueueHealth(Base):
    """Additive retry state; existing queue rows and counters are unchanged."""
    __tablename__ = 'queue_health_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    failures = Column(Integer, nullable=False, default=0)


def lock_world(conn, channel):
    # A transaction-scoped lock also protects shared society balances on Postgres.
    # SQLite's BEGIN IMMEDIATE provides the corresponding single-writer boundary.
    if channel and conn.dialect.name == 'postgresql':
        key = int.from_bytes(hashlib.blake2b(channel.encode(), digest_size=8).digest(), 'big', signed=True)
        conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def need_reason(m, db, p):
    life = m.life_state(db, p)
    fixes = {'energy': ('Energy', '/sleep'), 'nutrition': ('Nutrition', '/eat'), 'social': ('Social', '/games')}
    return '\n'.join(f'{label}: {getattr(life, key)}/100; need {m.TASK_NEED_MINIMUM}. Use {command}.'
                      for key, (label, command) in fixes.items() if getattr(life, key) < m.TASK_NEED_MINIMUM)


def inventory_snapshot(m, db, p):
    """Canonical inventory quantities, including quality gear, excluding counters.

    Compare each attempt inside its transaction so unrelated work between ticks
    cannot enter the queue totals. Values are actual net changes per attempt.
    """
    stock = m.item_identity.stock(m, db, p)
    stock = {k: v for k, v in stock.items() if not k.startswith('prospect:')}
    for field in m.PLAYER_MATERIAL_FIELDS - {'ore', 'rare_ore'}:
        stock[field] = getattr(p, field)
    for gear in db.execute(select(m.QualityGear).where(
            m.QualityGear.channel_id == p.channel_id,
            m.QualityGear.canonical_uid == p.twitch_uid)).scalars():
        stock['gear:' + gear.quality + ':' + gear.item_key] = gear.qty
    return stock


def total_label(m, key):
    if key.startswith('gear:'):
        _, quality, item = key.split(':', 2)
        return quality + ' ' + m.QUALITY_RECIPES[item]['name']
    return m.resource_name(key)


def totals_text(m, db, row, short=False):
    totals = db.get(QueueTotals, (row.channel_id, row.canonical_uid))
    completed = row.total - row.remaining
    succeeded = totals.succeeded if totals else 0
    failed = totals.failed if totals else 0
    progress = totals.progress if totals else 0
    unknown = completed - succeeded - failed - progress
    text = f'Succeeded: {succeeded}; failed: {failed}.'
    if progress:
        text += f' Prospecting steps without ore: {progress}.'
    if unknown:
        text += f' Earlier attempts without recorded totals: {unknown}.'
    gained = json.loads(totals.gained) if totals else {}
    used = json.loads(totals.used) if totals else {}
    def listing(values):
        return ', '.join(f'{total_label(m, k)} ×{v}' for k, v in sorted(values.items())) or 'None'
    text += (' | Items gained: ' if short else '\n\nTOTAL ITEMS GAINED\n') + listing(gained)
    if not short:
        text += '\n\nTOTAL ITEMS USED\n' + listing(used)
        if unknown:
            text += '\nTotals cover only attempts recorded after this update; existing inventory is unchanged.'
    return text


actor_context=ContextVar('queue_actor',default=None)
cooldown_wait=ContextVar('queue_cooldown_wait',default=0)
ACTIVE={'running','paused'}
ATTEMPT_SECONDS=10

def ores():return {k for k,v in s.GATHER.items() if v['branch']=='ore_mining'}

def choices(m):
    result={f'mine:{k}':'Mine '+s.item_label(k) for k in sorted(ores())}
    result.update({f'gather:{k}':'Gather '+s.item_label(k) for k in sorted(s.GATHER) if k not in ores()})
    # Monetary investments, social targets and recovery are deliberately manual.
    result.update({f'work:{k}':m.action_display_name(k) for k in m.ACTION_SKILLS if k not in {'businessinvest','hi','hangout','mentor','duo','mine','rare','scavenge'}})
    result.update({f'work:{a}@{mode}':m.action_display_name(a,mode) for a,mode in task_yields.YIELDS if mode})
    result.update({f'make:{k}':'Make '+r['name'] for k,r in s.RECIPES.items()})
    result.update({f'make:{k}':'Make '+m.craft_item_name(k) for k in (*m.PART_RECIPES,*m.RECIPES,*m.QUALITY_RECIPES) if k not in m.item_identity.RETIRED_RECIPES})
    return result

def normalize(m,value):
    if value in choices(m):return value
    if value in m.ACTION_SKILLS:return {'mine':'mine:'+m.item_identity.ALIASES['ore'],'rare':'mine:'+m.item_identity.ALIASES['rare_ore']}.get(value,'work:'+value)
    return value

def specification(m,task):
    kind,target=task.split(':',1);cost={};energy=2;cooldown=5
    if kind in {'mine','gather'}:
        if target in cp.RARE:energy=3;cooldown=20
    elif kind=='make':
        if target in s.RECIPES:
            cost=s.RECIPES[target]['inputs']
            if any(k in cp.RARE for k in s.RECIPES[target]['outputs']):energy=3;cooldown=20
        else:cost=m.PART_RECIPES.get(target) or m.RECIPES.get(target) or m.QUALITY_RECIPES[target]['cost']
    else:
        if target in {'repair','project','explore','survey','machine','work'}:energy=3
        if target in m.SEED_TASKS:cost=m.SEED_TASKS[target]['cost']
        elif target=='craft':cost={'ore':1}
        elif target=='delivery':cost={'cargo':1}
    if kind=='work':
        action,mode=task_yields.split(target)
        cfg=task_yields.config(action,mode)
        if cfg:energy=cfg[0]
        if mode=='expedite':cost={'power_cell':1}
    return cost,energy,max(ATTEMPT_SECONDS,cooldown)

def requirements(m,db,p,task,count):
    costs,energy,_=specification(m,task);life=m.life_state(db,p)
    noun='attempt' if count==1 else 'attempts'
    lines=[f'For {count} remaining {noun}: up to {energy*count} Energy, {count} Nutrition and {count} Comfort.',
           f'To finish without recovery, start with at least {20+energy*(count-1)} Energy, {20+count-1} Nutrition and 20 Social.',
           f'Current needs: Energy {life.energy}/100; Nutrition {life.nutrition}/100; Social {life.social}/100; Comfort {life.comfort}/100.',
           'Every attempt requires Energy, Nutrition and Social of at least 20. Comfort affects performance but does not block work.']
    for key,n in costs.items():
        have=m.material_amount(db,p,key)
        lines.append(f'{m.resource_name(key)}: have {have}; need {n} for the next attempt (missing {max(0,n-have)}); up to {n*count} for the queue (missing {max(0,n*count-have)}). Get it: {m.material_source(key)}')
    if not costs:lines.append('Consumable materials: none required.')
    lines.append(f'Morale may also fall by up to {count} if Comfort drops below 20; recover Comfort with /sleep.')
    kind,target=task.split(':',1)
    if kind=='make' and target in s.RECIPES:
        r=s.RECIPES[target];req=r['requirement'].get('Skill','SK_CRAFTING')
        lines.append(f"Requires {s.station(r)}, tier {cp.recipe_tier(target)}, and {s.skill_name(req)} level {s.required_level(r)}. Use /workshop and /training.")
    if kind=='make' and target not in s.RECIPES:
        tag=cp.legacy_station(m,target);station=cp.STATIONS[tag]
        lines.append(f"Requires {station['name']} and tier {station['tier']}. Use /workshop for access.")
    if kind=='work' and target=='survey':
        have=m.material_amount(db,p,'sensor')
        lines.append(f'Sensor: need 1, have {have}, missing {max(0,1-have)}. This equipment is kept. Get it: '+m.material_source('sensor'))
    if kind=='work' and target in m.SEED_TASKS:
        cfg=m.SEED_TASKS[target]
        lines.append(f"Requires {m.SKILL_LABELS[cfg['skill']]} level {cfg['unlock']}. Use /training to see the task's skill and workstation requirements.")
    if kind=='work':
        action,mode=task_yields.split(target)
        detail=task_yields.requirements(m,action,mode)
        if detail:lines.append(detail)
    if kind in {'mine','gather'} and target in ores():lines.append('Mining uses your work success chance. Failure spends needs and one attempt, gives 1 Stone Dust, and gives no ore.')
    if target in cp.RARE:lines.append('Requires Harvesting level 3. Each queued attempt is one prospecting step; three successful steps produce one ore. Failed attempts give 1 Stone Dust and keep saved progress.')
    lines.append('These are task costs, excluding other activities, passive recovery and incident effects. Failed attempts count; blocked attempts do not.')
    return '\n'.join(lines)

def status(m,db,p,row):
    if row is None:return 'You have no task queue. Use /queue action:Start, choose Task, and set Count from 1 to 10. Only one task type can be queued at a time.'
    name=choices(m).get(row.task,row.task)
    text=f'TASK QUEUE — {row.state.upper()}\n{name}\nAttempts completed: {row.total-row.remaining}/{row.total}; remaining: {row.remaining}.\nOnly one task type can be queued at a time; maximum 10 attempts.\nThe worker checks your task every 10 seconds, even when nobody sends a message. Longer task cooldowns still apply.'
    text+='\n'+totals_text(m,db,row)
    health=db.get(QueueHealth,(row.channel_id,row.canonical_uid))
    if health and health.failures and row.state in ACTIVE:
        wait=max(0,int((m.as_utc(row.next_at)-m.now()).total_seconds()))
        text+=f'\n\nRETRY STATUS\nTemporary system error ({health.failures}/3). Retrying in about {wait}s; the interrupted attempt was not spent.'
    if row.state in {'paused','error'}:text+='\n\nPAUSE REASON\n'+row.result
    if row.remaining and row.state in ACTIVE:
        text+='\n\n'+requirements(m,db,p,row.task,row.remaining)+'\n\nThe queue resumes automatically when needs and requirements are met. Use /sleep, /eat or /games to recover faster; /queue action:Cancel stops the remaining attempts.'
    text+='\n'+queue_notifications.delivery_status(db,row)
    return text

@contextmanager
def atomic(m, channel=None):
    """Keep nested handler commits inside one outer database transaction."""
    with m.engine.connect() as conn:
        if conn.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:conn.begin()
        lock_world(conn, channel)
        token=connection_context.set(conn)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback();raise
        finally:connection_context.reset(token)

def control(m,channel,uid,name,provider,action='view',task='',count=1):
    if connection_context.get() is None:
        with atomic(m,channel):return control(m,channel,uid,name,provider,action,task,count)
    with m.SessionLocal() as db:
        _,p=m.player(db,channel,provider,uid,name)
        # Serialize competing starts even when no queue row exists yet.
        db.execute(select(m.Player.id).where(m.Player.id==p.id).with_for_update()).scalar_one()
        row=db.execute(select(TaskQueue).where(TaskQueue.channel_id==channel,TaskQueue.canonical_uid==p.twitch_uid).with_for_update()).scalar_one_or_none()
        if action=='start':
            if not 1<=count<=10:return 'Count must be a whole number from 1 to 10. No queue was changed.'
            task=normalize(m,task)
            if task not in choices(m):return 'Choose a valid Task from /queue. No queue was changed.'
            if row and row.state in ACTIVE:return 'You already have a queue. Only one task type can be queued at a time. Cancel it before starting another.\n'+status(m,db,p,row)
            totals=db.get(QueueTotals,(channel,p.twitch_uid))
            if totals is not None:db.delete(totals);db.flush()
            db.add(QueueTotals(channel_id=channel,canonical_uid=p.twitch_uid))
            health=db.get(QueueHealth,(channel,p.twitch_uid))
            if health:health.failures=0
            if row is None:
                row=TaskQueue(channel_id=channel,canonical_uid=p.twitch_uid);db.add(row)
            row.task=task;row.total=count;row.remaining=count;row.state='running';row.result='Waiting for the first attempt.';row.next_at=m.now()+timedelta(seconds=ATTEMPT_SECONDS)
            queue_notifications.start(m,db,p,provider,uid)
            reason=need_reason(m,db,p)
            if reason:
                row.state='paused';row.result=reason
                queue_notifications.stopped(m,db,p,row,'paused',reason)
        elif action=='cancel':
            if row and row.state in ACTIVE|{'error'}:
                row.state='cancelled';row.result='Remaining attempts cancelled. Completed work was kept.'
                queue_notifications.stopped(m,db,p,row,'cancelled',row.result)
        elif action!='view':return 'Choose View, Start or Cancel. No queue was changed.'
        db.commit();return status(m,db,p,row)

def run_one(m,channel,uid):
    # Existing handlers commit internally. Binding their sessions to this outer
    # transaction makes gameplay changes and queue progress one atomic commit.
    with m.engine.connect() as conn:
        if conn.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:conn.begin()
        lock_world(conn, channel)
        token=connection_context.set(conn)
        try:
            with m.SessionLocal() as db:
                p=db.execute(select(m.Player).where(m.Player.channel_id==channel,m.Player.twitch_uid==uid).with_for_update()).scalar_one_or_none()
                row=db.execute(select(TaskQueue).where(TaskQueue.channel_id==channel,TaskQueue.canonical_uid==uid).with_for_update()).scalar_one_or_none()
                if not p or not row or row.state not in ACTIVE or m.as_utc(row.next_at)>m.now():conn.rollback();return
                if row.task not in choices(m):
                    row.state='cancelled';row.result='This task is no longer available. Choose a new task.'
                    queue_notifications.stopped(m,db,p,row,'cancelled',row.result)
                    db.commit();conn.commit();return
                previous_state=row.state
                cp.mining_outcome.set(None)
                cooldown_wait.set(0)
                before=p.actions;success_before=p.successes
                stock_before=inventory_snapshot(m,db,p)
                kind,target=row.task.split(':',1)
                blocked=need_reason(m,db,p)
                if blocked:result=blocked
                elif kind in {'mine','gather'}:result=s.gather(m,db,p,target,'discord')
                else:
                    actor_token=actor_context.set((channel,uid))
                    try:
                        if kind=='make':result=m.make(channel,uid,p.display_name,target,'discord').body.decode()
                        else:
                            action,mode=task_yields.split(target)
                            result=m.action(action,channel,uid,p.display_name,msg='mode:'+mode if mode else '',provider='discord').body.decode()
                    finally:actor_context.reset(actor_token)
                db.refresh(p)
                attempted=p.actions>before
                if attempted:
                    row.remaining-=1
                    totals=db.get(QueueTotals,(channel,uid))
                    if totals is None:
                        totals=QueueTotals(channel_id=channel,canonical_uid=uid,
                                           succeeded=0,failed=0,progress=0,gained='{}',used='{}')
                        db.add(totals)
                    rare_target = target if target in cp.RARE else next(
                        (k for k in s.RECIPES.get(target,{}).get('outputs',{}) if k in cp.RARE), None)
                    if p.successes>success_before:totals.succeeded+=1
                    elif rare_target and cp.mining_outcome.get()!='failed':totals.progress+=1
                    else:totals.failed+=1
                    # Nested handlers may update inventory in another Session.
                    db.flush();db.expire_all()
                    stock_after=inventory_snapshot(m,db,p)
                    gained=json.loads(totals.gained);used=json.loads(totals.used)
                    for key in stock_before.keys() | stock_after.keys():
                        delta=stock_after.get(key,0)-stock_before.get(key,0)
                        if delta>0:gained[key]=gained.get(key,0)+delta
                        elif delta<0:used[key]=used.get(key,0)-delta
                    totals.gained=json.dumps(gained);totals.used=json.dumps(used)
                row.state='completed' if row.remaining==0 else ('running' if attempted or cooldown_wait.get()>0 else 'paused')
                row.result=result[:4000]
                if row.remaining and attempted:
                    reason=need_reason(m,db,p)
                    if reason:row.state='paused';row.result=reason
                if attempted and previous_state=='paused':
                    queue_notifications.dismiss_pause(db,db.get(queue_notifications.Destination,(channel,uid)))
                if row.state=='paused' and (previous_state!='paused' or attempted):
                    queue_notifications.stopped(m,db,p,row,'paused',row.result)
                health=db.get(QueueHealth,(channel,uid))
                if health:health.failures=0
                row.next_at=m.now()+timedelta(seconds=ATTEMPT_SECONDS)
                if row.state=='completed':
                    db.flush()
                    queue_notifications.complete(m,db,p,row,totals_text(m,db,row))
                db.commit()
            conn.commit()
        except BaseException:
            conn.rollback();raise
        finally:connection_context.reset(token)

def tick(m):
    with m.SessionLocal() as db:
        keys=list(db.execute(select(TaskQueue.channel_id,TaskQueue.canonical_uid).where(TaskQueue.state.in_(ACTIVE),TaskQueue.next_at<=m.now()).order_by(TaskQueue.next_at).limit(100)))
    for channel,uid in keys:
        try:run_one(m,channel,uid)
        except Exception as exc:
            logging.getLogger(__name__).error('Queue attempt rolled back (%s); recording bounded retry',type(exc).__name__)
            try:record_failure(m,channel,uid)
            except Exception:logging.getLogger(__name__).error('Queue database unavailable; retry state could not be saved')

def record_failure(m,channel,uid):
    """Retries only rolled-back work, with a three-error circuit breaker."""
    with atomic(m,channel):
        with m.SessionLocal() as db:
            row=db.get(TaskQueue,(channel,uid))
            if not row or row.state not in ACTIVE or m.as_utc(row.next_at)>m.now():return
            health=db.get(QueueHealth,(channel,uid))
            if health is None:
                health=QueueHealth(channel_id=channel,canonical_uid=uid,failures=0);db.add(health)
            health.failures+=1
            row.next_at=m.now()+timedelta(seconds=min(120,10*2**health.failures))
            row.result='A system error interrupted this attempt. No progress from this attempt was saved.'
            if health.failures>=3:
                row.state='error'
                row.result+=' The queue has stopped after three errors. Completed attempts are kept. Try a new queue after the issue is resolved.'
                p=db.execute(select(m.Player).where(m.Player.channel_id==channel,m.Player.twitch_uid==uid)).scalar_one()
                queue_notifications.stopped(m,db,p,row,'error',row.result)
            db.commit()


def install(m):
    TaskQueue.__table__.create(m.engine,checkfirst=True)
    QueueTotals.__table__.create(m.engine,checkfirst=True)
    QueueHealth.__table__.create(m.engine,checkfirst=True)
    queue_notifications.install(m)
    async def loop():
        stop=m.app.state.queue_stop
        while not stop.is_set():
            try:await asyncio.to_thread(tick,m)
            except Exception:logging.getLogger(__name__).exception('Queue polling failed; retrying')
            try:await asyncio.wait_for(stop.wait(),timeout=2)
            except asyncio.TimeoutError:pass
    async def start():
        m.app.state.queue_stop=asyncio.Event()
        m.app.state.queue_worker=asyncio.create_task(loop())
    async def stop():
        task=getattr(m.app.state,'queue_worker',None)
        if task:
            m.app.state.queue_stop.set()
            await task
    m.app.add_event_handler('startup',start);m.app.add_event_handler('shutdown',stop)


def merge_accounts(m,db,channel,source_uid,target_uid):
    source=db.get(TaskQueue,(channel,source_uid));target=db.get(TaskQueue,(channel,target_uid))
    if source is None:return
    queue_notifications.merge(db,channel,source_uid,target_uid,target is None or (source.state in ACTIVE and target.state not in ACTIVE))
    source_health=db.get(QueueHealth,(channel,source_uid))
    target_health=db.get(QueueHealth,(channel,target_uid))
    keep_health=target is None or (source.state in ACTIVE and target.state not in ACTIVE)
    if keep_health:
        if target_health:db.delete(target_health);db.flush()
        if source_health:source_health.canonical_uid=target_uid
    elif source_health:db.delete(source_health)
    source_totals=db.get(QueueTotals,(channel,source_uid))
    target_totals=db.get(QueueTotals,(channel,target_uid))
    keep_source=target is None or (source.state in ACTIVE and target.state not in ACTIVE)
    if source_totals is not None:
        if keep_source:
            if target_totals is not None:db.delete(target_totals);db.flush()
            source_totals.canonical_uid=target_uid
        else:db.delete(source_totals)
    elif keep_source and target_totals is not None:db.delete(target_totals)
    if target is None:source.canonical_uid=target_uid;return
    if source.state in ACTIVE and target.state not in ACTIVE:
        for field in ('task','total','remaining','state','result','next_at'):setattr(target,field,getattr(source,field))
    elif source.state in ACTIVE:
        target.result+='\nAccount linking kept this queue. The other account\'s remaining queue was cancelled; completed work was kept.'
    db.delete(source)


def short_status(m,channel,uid,name,provider):
    with m.SessionLocal() as db:
        _,p=m.player(db,channel,provider,uid,name);row=db.get(TaskQueue,(channel,p.twitch_uid))
        if row is None:return 'No queue. !queueadd <task ID> <1–10>; !queuecancel stops it. Only one task type at a time.'
        _,energy,_=specification(m,row.task);n=row.remaining
        text=f'{row.state.upper()}: {choices(m).get(row.task,row.task)} | {row.total-n}/{row.total} attempts done. '
        text+=totals_text(m,db,row,short=True)+' '
        if n and row.state in ACTIVE:
            life=m.life_state(db,p)
            text+=f'Finish without recovery: Energy {20+energy*(n-1)}, Nutrition {20+n-1}, Social 20. Now: {life.energy}/{life.nutrition}/{life.social}. '
            if row.state=='paused':text+='Paused: '+row.result.replace('\n',' ')[:95]+'. '
        return text+'One task type; max 10. !queuecancel. /queue shows full requirements.'
