"""Persistent, bounded work queues. Each attempt and its counter commit together."""
import asyncio, logging, json, hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from sqlalchemy import Column,String,Integer,DateTime,Text,select,text
from .db import Base, connection_context
from discord.ext import tasks
from . import seed_content as s, crafting_progression as cp, task_yields, queue_notifications, needs, qol, keep_levels, shopping_list, quiet_hours
from . import runtime
from .db import SessionLocal
from .models import Player
from .models import QualityGear

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


GAME_LOCK = int.from_bytes(hashlib.blake2b(b'new-eridian game lock', digest_size=8).digest(), 'big', signed=True)


def lock_world(conn, channel=None):
    """One transaction-scoped lock for the whole game on Postgres, whichever channel a request names.

    Votes, seasons, the stream challenge, the market day and the overlay all write the main world
    (DISCORD_WORLD_ID) even when a request names another channel, so a lock per channel let two transactions
    change the same rows at once (an expired event could pay out twice). SQLite's BEGIN IMMEDIATE is the
    same single-writer boundary. The key is a constant: it must not change when a world merge switches the
    main world while requests are waiting. `channel` is kept for callers; it no longer picks the lock."""
    if conn.dialect.name == 'postgresql':
        conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': GAME_LOCK})


def need_reason(db, p):
    from .game.life import life_state
    life = life_state(db, p)
    return '\n'.join(qol.need_line(db, p, life, *row) for row in needs.blocked_needs(life))


def recovered_reason(db, p, channel, uid):
    """Blocking needs after opt-in auto-recovery; notes say what recovery did."""
    reason = need_reason(db, p)
    notes = []
    if reason and qol.autorecover_on(db, channel, uid):
        notes = qol.recover(db, p, channel, uid)
        if notes:
            db.expire_all()
            reason = need_reason(db, p)
    return reason, notes


def inventory_snapshot(db, p):
    """Canonical inventory quantities, including quality gear, excluding counters.

    Compare each attempt inside its transaction so unrelated work between ticks
    cannot enter the queue totals. Values are actual net changes per attempt.
    """
    from . import item_identity
    from .game.cooldowns_materials import PLAYER_MATERIAL_FIELDS
    stock = item_identity.stock(db, p)
    stock = {k: v for k, v in stock.items() if not k.startswith('prospect:')}
    # Player columns that back catalog items are already in the canonical stock.
    for field in PLAYER_MATERIAL_FIELDS - set(item_identity.FIELD_ITEMS.values()):
        stock[field] = getattr(p, field)
    for gear in db.execute(select(QualityGear).where(
            QualityGear.channel_id == p.channel_id,
            QualityGear.canonical_uid == p.twitch_uid)).scalars():
        stock['gear:' + gear.quality + ':' + gear.item_key] = gear.qty
    return stock


def total_label(key):
    from .game.players import resource_name
    from .game.rules import QUALITY_RECIPES
    if key.startswith('gear:'):
        _, quality, item = key.split(':', 2)
        return quality + ' ' + QUALITY_RECIPES[item]['name']
    return resource_name(key)


def totals_text(db, row, short=False, compact=False):
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
        return ', '.join(f'{total_label(k)} ×{v}' for k, v in sorted(values.items())) or 'None'
    if compact:
        # The short status leaves out empty sections.
        if gained:text += '\n\nTOTAL ITEMS GAINED\n' + listing(gained)
        if used:text += '\n\nTOTAL ITEMS USED\n' + listing(used)
        return text
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

def choices():
    from . import item_identity
    from .game.cooldowns_materials import action_display_name
    from .game.routes_crafting import craft_item_name
    from .game.rules import ACTION_SKILLS, PART_RECIPES, QUALITY_RECIPES, RECIPES
    result={f'mine:{k}':'Mine '+s.item_label(k) for k in sorted(ores())}
    result.update({f'gather:{k}':'Gather '+s.item_label(k) for k in sorted(s.GATHER) if k not in ores()})
    # Monetary investments, social targets and recovery are deliberately manual.
    result.update({f'work:{k}':action_display_name(k) for k in ACTION_SKILLS if k not in {'businessinvest','hi','hangout','mentor','duo','mine','rare','scavenge'}})
    result.update({f'work:{a}@{mode}':action_display_name(a,mode) for a,mode in task_yields.YIELDS if mode})
    result.update({f'make:{k}':'Make '+r['name'] for k,r in s.RECIPES.items()})
    retired=item_identity.RETIRED_RECIPES.keys()|item_identity.RETIRED_GATHERED.keys()
    result.update({f'make:{k}':'Make '+craft_item_name(k) for k in (*PART_RECIPES,*RECIPES,*QUALITY_RECIPES) if k not in retired})
    return result

def normalize(value):
    from . import item_identity, workbench
    from .game.rules import ACTION_SKILLS
    if value in choices():return value
    if value.startswith('make:'):
        # Biofiber is now gathered Flaxa rather than crafted.
        gathered=item_identity.RETIRED_GATHERED.get(value[5:].strip().casefold().replace(' ','_'))
        if gathered:return 'gather:'+gathered
        # Old recipe keys and item names (make:component, make:Iron Plate) resolve
        # to the Workbench recipe they now mean.
        found=workbench.resolve(None,None,value[5:])
        if found is not None:return 'make:'+found.id
    if value in ACTION_SKILLS:return {'mine':'mine:'+item_identity.ALIASES['ore'],'rare':'mine:'+item_identity.ALIASES['rare_ore']}.get(value,'work:'+value)
    return value

def specification(task):
    from . import item_identity
    from .game.life import task_energy
    from .game.rules import PART_RECIPES, QUALITY_RECIPES, RECIPES
    from .seed_skills import TASKS as SEED_TASKS
    kind,target=task.split(':',1);cost={};energy=2;cooldown=5
    if kind in {'mine','gather'}:
        if target in cp.RARE:energy=3;cooldown=20
    elif kind=='make':
        if target in s.RECIPES:
            cost=s.RECIPES[target]['inputs']
            if any(k in cp.RARE for k in s.RECIPES[target]['outputs']):energy=3;cooldown=20
        else:cost=PART_RECIPES.get(target) or RECIPES.get(target) or QUALITY_RECIPES[target]['cost']
    else:
        action,mode=task_yields.split(target)
        energy=task_energy(action,mode)
        if target in SEED_TASKS:cost=SEED_TASKS[target]['cost']
        elif target=='craft':cost={'ore':1}
        elif target=='delivery':cost={'cargo':1}
        if mode=='expedite':cost={item_identity.canonical('power_cell'):1}
    return cost,energy,max(ATTEMPT_SECONDS,cooldown)

def requirements(db,p,task,count,provider='discord'):
    """What a queue of `count` attempts of `task` needs. On Discord the pointers name menu screens (its queue screens have
    buttons); other providers keep the commands."""
    from .game.cooldowns_materials import material_amount, material_source as source_of
    from .workbench import plain_source
    discord=provider=='discord'
    material_source=lambda key:plain_source(source_of(key)) if discord else source_of(key)
    from .game.life import life_state
    from .game.players import resource_name
    from .game.routes_player import equipment_count
    from .game.rules import SKILL_LABELS
    from .seed_skills import TASKS as SEED_TASKS
    costs,energy,_=specification(task);life=life_state(db,p)
    noun='attempt' if count==1 else 'attempts'
    need=needs.finish_forecast(energy,count)
    lines=[f'For {count} remaining {noun}: up to {energy*count} Energy, {count} Nutrition and {needs.comfort_cost(energy)*count} Comfort ({needs.cost_text(energy,", ")} each).',
           f'To finish without recovery, start with at least {need["energy"]} Energy, {need["nutrition"]} Nutrition, {need["social"]} Social and {need["comfort"]} Comfort.',
           f'Current needs: Energy {life.energy}/100; Nutrition {life.nutrition}/100; Social {life.social}/100; Comfort {life.comfort}/100.',
           f'Every attempt requires Energy, Nutrition and Social of at least {needs.TASK_NEED_MINIMUM} and Comfort of at least {needs.COMFORT_BLOCK}. Comfort drains at the same rate as Energy; below {needs.COMFORT_SLOW} it also lowers success.']
    for key,n in costs.items():
        have=material_amount(db,p,key)
        lines.append(f'{resource_name(key)}: have {have}; need {n} for the next attempt (missing {max(0,n-have)}); up to {n*count} for the queue (missing {max(0,n*count-have)}). Get it: {material_source(key)}')
    if not costs:lines.append('Consumable materials: none required.')
    fixes='Relax in the Life menu or by using a bed, seat, bath, clothing item or Comfort Pack' if discord else needs.COMFORT_FIXES_DISCORD
    lines.append(f'Morale may also fall by up to {count} if Comfort drops below {needs.COMFORT_SLOW}; recover Comfort with {fixes}, or {"Sleep" if discord else "/sleep"} when it is ready.')
    kind,target=task.split(':',1)
    if kind=='make' and target in s.RECIPES:
        r=s.RECIPES[target];req=r['requirement'].get('Skill','SK_CRAFTING')
        lines.append(f"Requires {s.station(r)}, tier {cp.recipe_tier(target)}, and {s.skill_name(req)} level {s.required_level(r)}. "
                     +('Workstation access is under Craft › More › Workstations, and skills are trained under Work › Train skills.' if discord else 'Use /workshop and /training.'))
    if kind=='make' and target not in s.RECIPES:
        tag=cp.legacy_station(target);station=cp.STATIONS[tag]
        lines.append(f"Requires {station['name']} and tier {station['tier']}. "+('Workstation access is under Craft › More › Workstations.' if discord else 'Use /workshop for access.'))
    if kind=='work':
        action,mode=task_yields.split(target)
        equipment=task_yields.EQUIPMENT.get((action,mode))
        if equipment:
            have=equipment_count(db,p,equipment)
            lines.append(f'{resource_name(equipment)}: need 1, have {have}, missing {max(0,1-have)}. This equipment is kept. Get it: '+material_source(equipment))
    if kind=='work' and target in SEED_TASKS:
        cfg=SEED_TASKS[target]
        lines.append(f"Requires {SKILL_LABELS[cfg['skill']]} level {cfg['unlock']}. "
                     +("Train skills, in the Work menu, shows the task's skill and workstation requirements." if discord else "Use /training to see the task's skill and workstation requirements."))
    if kind=='work':
        action,mode=task_yields.split(target)
        detail=task_yields.requirements(action,mode)
        if detail:lines.append(detail)
    if kind in {'mine','gather'} and target in ores():lines.append('Mining uses your work success chance. Failure spends needs and one attempt, gives 1 Stone Dust, and gives no ore.')
    if target in cp.RARE:lines.append('Needs a Mineral Extractor in your bag: a Small one brings up 1 ore a success, a Frontiers Expedition one 2. Failed attempts give 1 Stone Dust.')
    lines.append('These are task costs, excluding other activities, passive recovery and incident effects. Failed attempts count; blocked attempts do not.')
    return '\n'.join(lines)

def status(db,p,row,detail=False,provider='discord'):
    """Queue status. The short view shows progress, results and only the warnings
    that apply; `detail` adds every requirement and rule (the Details button).
    On Discord the screen has buttons for everything, so its text names no commands to type."""
    from .game.players import as_utc
    discord=provider=='discord'
    if row is None:
        if discord:return '📋 QUEUE STATUS\nNothing is queued. Pick a material or an ore to gather or mine up to 10 times in a row, or queue a recipe from its page.'
        return 'You have no task queue. Start one from /mine, /gather or /make with Queue 5 or Queue 10, or /queue action:Start.'
    name=choices().get(row.task,row.task)
    text=f'TASK QUEUE — {row.state.upper()}\n{name}\nAttempts completed: {row.total-row.remaining}/{row.total}; remaining: {row.remaining}.'
    if row.state=='running' and row.remaining and row.task in choices():
        text+=f'\nFinishes about <t:{int(runtime.now().timestamp()+row.remaining*specification(row.task)[2])}:R>.'
    if detail:text+='\nOnly one task type can be queued at a time; maximum 10 attempts.\nThe worker checks your task every 10 seconds, even when nobody sends a message. Longer task cooldowns still apply.'
    text+='\n'+totals_text(db,row,compact=not detail)
    following=qol.next_label(db,row.channel_id,row.canonical_uid)
    if following:text+=f'\n\nNEXT QUEUE\n{following} starts automatically when this queue completes.'
    if detail and row.state not in ACTIVE:text+='\n\n'+('Repeat this queue with the Repeat button.' if discord else 'Repeat this queue with the Repeat button, /queue action:Repeat last, or !queuerepeat.')
    health=db.get(QueueHealth,(row.channel_id,row.canonical_uid))
    if health and health.failures and row.state in ACTIVE:
        wait=max(0,int((as_utc(row.next_at)-runtime.now()).total_seconds()))
        text+=f'\n\nRETRY STATUS\nTemporary system error ({health.failures}/3). Retrying in about {wait}s; the interrupted attempt was not spent.'
    if row.state in {'paused','error'}:text+='\n\nPAUSE REASON\n'+(qol.without_fix(row.result) if discord else row.result)
    if detail and row.remaining and row.state in ACTIVE:
        resumes='The queue resumes automatically when needs and requirements are met. '
        resumes+=('Recover faster with Relax, Eat or Games in the Life menu, or comfort items from Use (Sleep when it is ready); Stop queue cancels the remaining attempts.' if discord
                  else 'Recover faster with /relax, /eat, /games or comfort items (/sleep when ready); /queue action:Cancel stops the remaining attempts.')
        text+='\n\n'+requirements(db,p,row.task,row.remaining,provider)+'\n\n'+resumes
    elif row.remaining and row.state=='running':
        from .inbox import queue_warnings
        warnings=queue_warnings(db,p,row.task,row.remaining,provider)
        if warnings:text+='\n\n⚠️ HEADS UP\n'+'\n'.join('• '+w for w in warnings)
    delivery=queue_notifications.delivery_status(db,row,provider)
    if detail or not delivery.startswith(('You will be','Queue notification sent')):text+='\n'+delivery
    return text

@contextmanager
def atomic(channel=None):
    """Keep nested handler commits inside one outer database transaction."""
    with runtime.engine.connect() as conn:
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

def begin(db,p,row,task,count,target=None,renew=None):
    """Start `task` on the citizen's queue row.

    `target` is the (provider, uid) that alerts go to; `renew` instead keeps an
    existing alert destination, so a chained queue reports where the first did.
    """
    channel=p.channel_id
    totals=db.get(QueueTotals,(channel,p.twitch_uid))
    if totals is not None:db.delete(totals);db.flush()
    db.add(QueueTotals(channel_id=channel,canonical_uid=p.twitch_uid))
    health=db.get(QueueHealth,(channel,p.twitch_uid))
    if health:health.failures=0
    if row is None:
        row=TaskQueue(channel_id=channel,canonical_uid=p.twitch_uid);db.add(row)
    row.task=task;row.total=count;row.remaining=count;row.state='running';row.result='Waiting for the first attempt.';row.next_at=runtime.now()+timedelta(seconds=ATTEMPT_SECONDS)
    if renew is None:queue_notifications.start(db,p,*(target or ('twitch',p.twitch_uid)))
    else:queue_notifications.renew(db,renew)
    reason,notes=recovered_reason(db,p,channel,p.twitch_uid)
    if reason:
        row.state='paused';row.result=reason+('\nAuto-recover tried: '+'; '.join(notes)+'.' if notes else '')
        queue_notifications.stopped(db,p,row,'paused',row.result)
    return row


def control(channel,uid,name,provider,action='view',task='',count=1):
    from .game.players import player
    if connection_context.get() is None:
        with atomic(channel):return control(channel,uid,name,provider,action,task,count)
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        # Serialize competing starts even when no queue row exists yet.
        db.execute(select(Player.id).where(Player.id==p.id).with_for_update()).scalar_one()
        row=db.execute(select(TaskQueue).where(TaskQueue.channel_id==channel,TaskQueue.canonical_uid==p.twitch_uid).with_for_update()).scalar_one_or_none()
        prefix='/' if provider=='discord' else '!'
        if action=='repeat':
            if row is None:return f'You have no earlier queue to repeat. Start one with {prefix}queue, {prefix}mine or {prefix}make.'
            if row.state in ACTIVE:return 'Your queue is still active. Use Queue next to run another task after it. No queue was changed.\n'+status(db,p,row,provider=provider)
            action,task,count='start',row.task,row.total
        if action=='start':
            if not 1<=count<=10:return 'Count must be a whole number from 1 to 10. No queue was changed.'
            task=normalize(task)
            if task not in choices():return 'Choose a valid Task from /queue. No queue was changed.'
            if row and row.state in ACTIVE:
                hint='/queue action:Queue next' if provider=='discord' else '!queuenext <task ID> <1–10>'
                return f'You already have a queue. Only one task type can run at a time. Cancel it, or use {hint} to run this task after it.\n'+status(db,p,row,provider=provider)
            row=begin(db,p,row,task,count,target=(provider,uid))
        elif action=='next':
            if not row or row.state not in ACTIVE:return f'You have no active queue, so there is nothing to follow. Start this task with {prefix}queue action:Start instead.' if provider=='discord' else 'No active queue. Use !queueadd <task ID> <1–10> to start now.'
            ok,text=qol.set_next(db,p,task,count)
            if not ok:return text
            db.commit();return text+'\n\n'+status(db,p,row,provider=provider)
        elif action=='clearnext':
            cleared=qol.clear_next(db,channel,p.twitch_uid);db.commit()
            return ('⏭️ Next queue cleared.' if cleared else 'No next queue was set.')+('\n\n'+status(db,p,row,provider=provider) if row else '')
        note=''
        if action=='cancel':
            if row and row.state in ACTIVE|{'error'}:
                following=qol.next_label(db,channel,p.twitch_uid)
                row.state='cancelled';row.result='Remaining attempts cancelled. Completed work was kept.'
                from . import extras
                planned=extras.playlist(db,channel,p.twitch_uid)
                extras.clear_plan(db,p)
                if planned and not following:following=f'{len(planned)} planned steps'
                if following and (qol.clear_next(db,channel,p.twitch_uid) or planned):
                    note=f'⏭️ Your next queue ({following}) was cleared too.\n\n'
                    row.result+=' '+note.strip()
                queue_notifications.stopped(db,p,row,'cancelled',row.result)
        elif action not in {'view','start'}:return 'Choose View, Start, Queue next, Repeat last, Clear next or Cancel. No queue was changed.'
        db.commit();return note+status(db,p,row,provider=provider)

def run_one(channel,uid):
    # Existing handlers commit internally. Binding their sessions to this outer
    # transaction makes gameplay changes and queue progress one atomic commit.
    from .game import action as action_module
    from .game.players import as_utc
    from .game.routes_crafting import make
    with runtime.engine.connect() as conn:
        if conn.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:conn.begin()
        lock_world(conn, channel)
        token=connection_context.set(conn)
        try:
            with SessionLocal() as db:
                p=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==uid).with_for_update()).scalar_one_or_none()
                row=db.execute(select(TaskQueue).where(TaskQueue.channel_id==channel,TaskQueue.canonical_uid==uid).with_for_update()).scalar_one_or_none()
                if not p or not row or row.state not in ACTIVE or as_utc(row.next_at)>runtime.now():conn.rollback();return
                if row.task not in choices() and normalize(row.task) in choices():
                    # Queues saved with a retired legacy recipe continue with its catalog recipe.
                    row.task=normalize(row.task)
                if row.task not in choices():
                    row.state='cancelled';row.result='This task is no longer available. Choose a new task.'
                    queue_notifications.stopped(db,p,row,'cancelled',row.result)
                    db.commit();conn.commit();return
                previous_state=row.state
                recovery=[]
                if need_reason(db,p) and qol.autorecover_on(db,channel,uid):
                    recovery=qol.recover(db,p,channel,uid)
                    if recovery:db.expire_all()
                cp.mining_outcome.set(None)
                cooldown_wait.set(0)
                before=p.actions;success_before=p.successes
                stock_before=inventory_snapshot(db,p)
                kind,target=row.task.split(':',1)
                blocked=need_reason(db,p)
                actor_token=actor_context.set((channel,uid))     # also tells the game nobody may be watching
                try:
                    if blocked:result=blocked
                    elif kind in {'mine','gather'}:result=s.gather(db,p,target,'discord')
                    elif kind=='make':result=make(channel,uid,p.display_name,target,'discord').body.decode()
                    else:
                        action,mode=task_yields.split(target)
                        result=action_module.action(action,channel,uid,p.display_name,msg='mode:'+mode if mode else '',provider='discord').body.decode()
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
                    stock_after=inventory_snapshot(db,p)
                    gained=json.loads(totals.gained);used=json.loads(totals.used)
                    for key in stock_before.keys() | stock_after.keys():
                        delta=stock_after.get(key,0)-stock_before.get(key,0)
                        if delta>0:gained[key]=gained.get(key,0)+delta
                        elif delta<0:used[key]=used.get(key,0)-delta
                    totals.gained=json.dumps(gained);totals.used=json.dumps(used)
                    from . import extras
                    extras.goal_ready_check(db,p)   # the goal's one ready note, when this attempt brought in what it lacked
                row.state='completed' if row.remaining==0 else ('running' if attempted or cooldown_wait.get()>0 else 'paused')
                row.result=result[:4000]
                if row.remaining and attempted:
                    reason,notes=recovered_reason(db,p,channel,uid)
                    recovery+=notes
                    if reason:row.state='paused';row.result=reason
                if row.state=='paused' and recovery:
                    row.result+='\nAuto-recover tried: '+'; '.join(recovery)+'.'
                if attempted and previous_state=='paused':
                    queue_notifications.dismiss_pause(db,db.get(queue_notifications.Destination,(channel,uid)))
                if row.state=='paused' and (previous_state!='paused' or attempted):
                    queue_notifications.stopped(db,p,row,'paused',row.result)
                health=db.get(QueueHealth,(channel,uid))
                if health:health.failures=0
                row.next_at=runtime.now()+timedelta(seconds=ATTEMPT_SECONDS)
                if row.state=='completed':
                    db.flush()
                    from . import extras
                    notes=extras.autosell_after_queue(db,p)
                    task,count=qol.pop_next(db,channel,uid)
                    if not task:
                        task,count,sold=extras.pop_step(db,p)
                        notes+=sold
                    task=normalize(task) if task else ''
                    following='\n'.join(notes+([f'Starting your next queue: {choices()[task]} ×{count}.'] if task in choices() else []))
                    queue_notifications.complete(db,p,row,totals_text(db,row),following)
                    if task in choices():
                        db.flush()
                        begin(db,p,row,task,count,renew=db.get(queue_notifications.Destination,(channel,uid)))
                db.commit()
            conn.commit()
        except BaseException:
            conn.rollback();raise
        finally:connection_context.reset(token)

def tick():
    with SessionLocal() as db:
        keys=list(db.execute(select(TaskQueue.channel_id,TaskQueue.canonical_uid).where(TaskQueue.state.in_(ACTIVE),TaskQueue.next_at<=runtime.now()).order_by(TaskQueue.next_at).limit(100)))
    for channel,uid in keys:
        try:run_one(channel,uid)
        except Exception as exc:
            logging.getLogger(__name__).error('Queue attempt rolled back (%s); recording bounded retry',type(exc).__name__)
            try:record_failure(channel,uid)
            except Exception:logging.getLogger(__name__).error('Queue database unavailable; retry state could not be saved')

def record_failure(channel,uid):
    """Retries only rolled-back work, with a three-error circuit breaker."""
    from .game.players import as_utc
    with atomic(channel):
        with SessionLocal() as db:
            row=db.get(TaskQueue,(channel,uid))
            if not row or row.state not in ACTIVE or as_utc(row.next_at)>runtime.now():return
            health=db.get(QueueHealth,(channel,uid))
            if health is None:
                health=QueueHealth(channel_id=channel,canonical_uid=uid,failures=0);db.add(health)
            health.failures+=1
            row.next_at=runtime.now()+timedelta(seconds=min(120,10*2**health.failures))
            row.result='A system error interrupted this attempt. No progress from this attempt was saved.'
            if health.failures>=3:
                row.state='error'
                row.result+=' The queue has stopped after three errors. Completed attempts are kept. Try a new queue after the issue is resolved.'
                p=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==uid)).scalar_one()
                queue_notifications.stopped(db,p,row,'error',row.result)
            db.commit()


def install(m):
    from .game.base import app
    TaskQueue.__table__.create(runtime.engine,checkfirst=True)
    QueueTotals.__table__.create(runtime.engine,checkfirst=True)
    QueueHealth.__table__.create(runtime.engine,checkfirst=True)
    queue_notifications.install(m)
    qol.install(m)
    keep_levels.install(m)
    shopping_list.install(m)
    quiet_hours.install(m)
    @tasks.loop(seconds=2,reconnect=True)
    async def timer():
        try:await asyncio.to_thread(tick)
        except Exception:logging.getLogger(__name__).error('Queue timer failed; retrying')
    async def start():
        app.state.queue_worker=timer.start()
    async def stop():
        timer.stop()
        task=timer.get_task()
        if task:await task
    app.add_event_handler('startup',start);app.add_event_handler('shutdown',stop)


def merge_accounts(db,channel,source_uid,target_uid):
    qol.merge(db,channel,source_uid,target_uid)
    keep_levels.merge(db,channel,source_uid,target_uid)
    shopping_list.merge(db,channel,source_uid,target_uid)
    quiet_hours.merge(db,channel,source_uid,target_uid)
    from . import extras
    extras.merge(db,channel,source_uid,target_uid)
    from . import autonomy
    autonomy.merge(db,channel,source_uid,target_uid)
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


def short_status(channel,uid,name,provider):
    from .game.life import life_state
    from .game.players import player
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);row=db.get(TaskQueue,(channel,p.twitch_uid))
        if row is None:return 'No queue. !queueadd <task ID> <1–10>; !queuecancel stops it. Only one task type at a time.'
        _,energy,_=specification(row.task);n=row.remaining
        text=f'{row.state.upper()}: {choices().get(row.task,row.task)} | {row.total-n}/{row.total} attempts done. '
        text+=totals_text(db,row,short=True)+' '
        following=qol.next_label(db,channel,p.twitch_uid)
        if following:text+=f'Next: {following}. '
        if row.state not in ACTIVE:text+='!queuerepeat runs it again. '
        if n and row.state in ACTIVE:
            life=life_state(db,p)
            need=needs.finish_forecast(energy,n)
            text+=f'Finish without recovery: Energy {need["energy"]}, Nutrition {need["nutrition"]}, Social {need["social"]}, Comfort {need["comfort"]}. Now: {life.energy}/{life.nutrition}/{life.social}/{life.comfort}. '
            if row.state=='paused':text+='Paused: '+row.result.replace('\n',' ')[:95]+'. '
        return text+'One task type; max 10. !queuenext adds a follow-up; !queuecancel stops.'
