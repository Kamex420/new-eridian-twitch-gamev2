"""Second quality-of-life layer: planning, repeating, coming back and tidying up.

* Live countdowns — Discord timestamps (<t:…:R>) that count down on their own.
* Queue max — the most batches or attempts your items and needs allow.
* Recent actions — the last ten things you did, each one tap to repeat;
  `!again` repeats your last Twitch action.
* Goal — pin a recipe; the whole ingredient tree is tracked and "Fetch next"
  works through it.
* Plans and routines — queue several steps (including "sell all" steps) and
  save them under a name to start again later.
* What can I make with this? — recipes that use an item, ready ones first.
* Welcome back and reminders — a private summary after time away, and one-off
  notes when sleep is ready, a festival opens or a new daily contract starts.
* Auto-sell, undo, eat until full, /find and "remember my place".

Everything runs through the existing game functions: the same gates, costs,
cooldowns and receipts apply. New state lives in three additive tables.
"""
import json
import math
import re
from collections import defaultdict
from datetime import timedelta
from sqlalchemy import Column, String, Integer, Text, DateTime, select, delete
from .db import Base
from . import seed_content as s, workbench as wb, needs

WELCOME_AFTER = timedelta(hours=3)
UNDO_SECONDS = 60
RECENT_KEEP = 10
MAX_ROUTINES = 5
MAX_STEPS = 6
FULL_NUTRITION = 80


class Extras(Base):
    """Per-citizen state for these features; a missing row means defaults."""
    __tablename__ = 'player_extras_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    goal = Column(String(64), nullable=False, default='')
    autosell = Column(Text, nullable=False, default='[]')
    playlist = Column(Text, nullable=False, default='[]')
    last_seen = Column(DateTime(timezone=True), nullable=True)
    reminded = Column(Text, nullable=False, default='{}')
    workbench = Column(String(160), nullable=False, default='')
    last_sale = Column(Text, nullable=False, default='')


class RecentAction(Base):
    __tablename__ = 'player_recent_actions_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    platform = Column(String(8), nullable=False)
    command = Column(String(32), nullable=False)
    options = Column(Text, nullable=False)
    label = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class Routine(Base):
    __tablename__ = 'player_routines_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    steps = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


def install(m):
    for table in (Extras, RecentAction, Routine):
        table.__table__.create(m.engine, checkfirst=True)


def row(db, channel, uid, create=False):
    found = db.get(Extras, (channel, uid))
    if found is None and create:
        found = Extras(channel_id=channel, canonical_uid=uid, goal='', autosell='[]', playlist='[]', reminded='{}',
                       workbench='', last_sale='')
        db.add(found)
        db.flush()
    return found


def merge(db, channel, source, target):
    src = db.get(Extras, (channel, source))
    if src is None:
        return
    if db.get(Extras, (channel, target)) is None:
        src.canonical_uid = target
    else:
        db.delete(src)
    for table in (RecentAction, Routine):
        for item in db.scalars(select(table).where(table.channel_id == channel, table.canonical_uid == source)):
            item.canonical_uid = target


# ---------------------------------------------------------------- live countdowns

def stamp(m, seconds, style='R'):
    """A Discord timestamp that counts down by itself (e.g. 'in 4 minutes')."""
    return f'<t:{int(m.now().timestamp() + max(0, seconds))}:{style}>'


def when(m, seconds, provider='discord'):
    return stamp(m, seconds) if provider == 'discord' else 'in ' + needs.duration_text(seconds)


# ---------------------------------------------------------------- queue max

def max_attempts(m, db, p, task):
    """(attempts, what limits it): the most of `task` your items and needs allow, up to 10."""
    tq = m.task_queue
    if task not in tq.choices(m):
        return 0, 'unknown task'
    costs, energy, _ = tq.specification(m, task)
    limit, reason = 10, 'the 10-attempt maximum'
    for key, n in costs.items():
        enough = m.material_amount(db, p, key) // max(1, n)
        if enough < limit:
            limit, reason = enough, m.resource_name(key)
    if not m.qol.autorecover_on(db, p.channel_id, p.twitch_uid):
        life = m.life_state(db, p)
        comfort = needs.comfort_cost(energy)
        rows = [((life.energy - needs.TASK_NEED_MINIMUM) // energy + 1 if life.energy >= needs.TASK_NEED_MINIMUM else 0, 'Energy'),
                ((life.nutrition - needs.TASK_NEED_MINIMUM) // needs.NUTRITION_PER_TASK + 1 if life.nutrition >= needs.TASK_NEED_MINIMUM else 0, 'Nutrition'),
                ((life.comfort - needs.COMFORT_BLOCK) // comfort + 1 if life.comfort >= needs.COMFORT_BLOCK and comfort else (10 if not comfort else 0), 'Comfort'),
                (10 if life.social >= needs.TASK_NEED_MINIMUM else 0, 'Social')]
        for enough, label in rows:
            if enough < limit:
                limit, reason = enough, label
    return max(0, int(limit)), reason


def max_for_owner(m, owner, task):
    """Queue max for a Discord user id, opening its own session (for panels)."""
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', owner, 'Citizen')[1]
        count, _ = max_attempts(m, db, p, task)
        db.commit()
        return count


# ---------------------------------------------------------------- recent actions

RECORDABLE = {'relax', 'sleep', 'games', 'walk', 'hobby', 'meal', 'recover', 'eatfull', 'farm', 'scan', 'rare', 'research',
              'cargo', 'delivery', 'spaceport', 'explore', 'repair'}


def recordable(command, options):
    options = options or {}
    if command in RECORDABLE:
        return True
    return ((command == 'eat' and options.get('food')) or (command == 'use' and options.get('item'))
            or (command == 'make' and options.get('recipe') and options.get('action') == 'craft')
            or (command == 'gather' and options.get('resource')) or (command == 'mine' and options.get('action') == 'mine' and options.get('ore'))
            or (command == 'queue' and options.get('action') == 'start' and options.get('task'))
            or (command == 'market' and options.get('action') in {'work', 'analyze'})
            or (command == 'business' and options.get('action') in {'work', 'contract'}))


def label_for(m, command, options):
    options = options or {}
    for key, leaf in m.menu.LEAVES.items():
        if leaf['kind'] in {'do', 'view'} and m.discord_legacy_route(leaf['cmd'], leaf['opts']) == (command, options):
            return leaf['label']
    if command == 'make':
        e = wb.resolve(m, None, None, options.get('recipe', ''))
        return 'Craft ' + (e.name if e else options.get('recipe', ''))
    if command == 'gather':
        return 'Gather ' + m.resource_name(options.get('resource', ''))
    if command == 'mine':
        return f"Mine {m.resource_name(options.get('ore', ''))} ×{options.get('count', 1)}"
    if command == 'eat':
        return 'Eat ' + ('emergency meal' if options.get('food') == 'emergency' else m.resource_name(options.get('food', '')))
    if command == 'use':
        return 'Use ' + m.resource_name(options.get('item', ''))
    if command == 'queue':
        return f"Queue {m.task_queue.choices(m).get(options.get('task', ''), options.get('task', ''))} ×{options.get('count', 1)}"
    if command == 'farm':
        return {'tend': 'Tend fields', 'harvest': 'Harvest', 'irrigate': 'Irrigate', 'hydroponics': 'Hydroponics'}.get(options.get('action'), 'Farming')
    return command.replace('_', ' ').title()


def record(m, db, channel, uid, platform, command, options, label):
    options = {k: v for k, v in (options or {}).items() if v not in (None, '')}
    encoded = json.dumps(options, sort_keys=True)
    latest = db.scalars(select(RecentAction).where(RecentAction.channel_id == channel, RecentAction.canonical_uid == uid,
                                                   RecentAction.platform == platform).order_by(RecentAction.id.desc()).limit(1)).first()
    if latest is not None and latest.command == command and latest.options == encoded:
        latest.created_at = m.now()
        return
    db.add(RecentAction(channel_id=channel, canonical_uid=uid, platform=platform, command=command, options=encoded,
                        label=label[:120], created_at=m.now()))
    db.flush()
    old = list(db.scalars(select(RecentAction.id).where(RecentAction.channel_id == channel, RecentAction.canonical_uid == uid,
                                                        RecentAction.platform == platform).order_by(RecentAction.id.desc()).offset(RECENT_KEEP)))
    if old:
        db.execute(delete(RecentAction).where(RecentAction.id.in_(old)))


def record_discord(m, discord_uid, name, command, options):
    """Called after a Discord command or menu action ran."""
    if not recordable(command, options):
        return
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', discord_uid, name)[1]
        record(m, db, p.channel_id, p.twitch_uid, 'discord', command, options, label_for(m, command, options))
        db.commit()


def recent(db, channel, uid, platform='discord', limit=RECENT_KEEP):
    return list(db.scalars(select(RecentAction).where(RecentAction.channel_id == channel, RecentAction.canonical_uid == uid,
                                                      RecentAction.platform == platform).order_by(RecentAction.id.desc()).limit(limit)))


# Twitch: the functions whose last use !again repeats, and which calls qualify.
TWITCH_AGAIN = {'action', 'make', 'seed_supplies', 'relax', 'walk', 'games', 'hobby', 'use_item', 'recover_needs', 'eat_full'}
TWITCH_SKIP = {'channel', 'uid', 'name', 'provider', 'msg'}


def remember_twitch(m, fn_name, params, canonical):
    if fn_name not in TWITCH_AGAIN or not canonical:
        return
    if fn_name == 'make' and (not params.get('recipe') or params.get('action', 'craft') != 'craft'):
        return
    if fn_name == 'seed_supplies' and (params.get('mode') != 'gather' or not params.get('item')):
        return
    if fn_name == 'use_item' and not params.get('item'):
        return
    options = {k: v for k, v in params.items() if k not in TWITCH_SKIP and v not in (None, '')}
    if fn_name == 'action' and str(params.get('msg') or '').startswith(('mode:', 'food:')):
        options['msg'] = params['msg']
    label = options.get('action') or options.get('recipe') or options.get('item') or fn_name
    with m.SessionLocal() as db:
        record(m, db, params.get('channel'), canonical, 'twitch', fn_name, options, str(label))
        db.commit()


# ---------------------------------------------------------------- goal

def plan(ctx, e, batches=1):
    """Everything still needed for `batches` of `e`, expanding crafted ingredients.

    Returns (crafts in dependency order as (entry, batches), raw shortfalls {key: qty}).
    Uses the acquisition routes the catalog already ranks, so it cannot loop.
    """
    m = ctx.m
    avail = {}
    crafts, raw = [], defaultdict(int)

    def have(key):
        return avail.setdefault(key, ctx.have(key))

    def require(key, qty, depth):
        use = min(have(key), qty)
        avail[key] -= use
        short = qty - use
        if short <= 0:
            return
        route = s.ACQUISITION.get(key)
        sub = wb.entry(m, route) if route else None
        if sub is not None and sub.inputs and key not in s.GATHER and depth < 8:
            per = max(1, ctx.batch_size(sub))
            count = math.ceil(short / per)
            for k, n in sub.inputs.items():
                require(k, n * count, depth + 1)
            crafts.append((sub, count))
            avail[key] = avail.get(key, 0) + count * per - short
        else:
            raw[key] += short

    for key, n in e.inputs.items():
        require(key, n * batches, 0)
    merged = {}
    for sub, count in crafts:
        merged[sub.id] = (sub, merged.get(sub.id, (sub, 0))[1] + count)
    return list(merged.values()), dict(raw)


def goal_entry(m, db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    return wb.entry(m, found.goal) if found is not None and found.goal else None


def set_goal(m, db, p, recipe):
    e = wb.entry(m, recipe) if recipe else None
    if e is None:
        return 'That recipe is not available. Nothing changed.'
    row(db, p.channel_id, p.twitch_uid, create=True).goal = e.id
    return f'🎯 Goal set: **{e.name}**. /status and the Goal view track everything still needed.'


def clear_goal(db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    if found is not None:
        found.goal = ''


# The /training skill that raises a recipe's skill, by main skill (seed_content.SKILLS).
TRAINING_HUB = {'cultivation': 'farming', 'extraction': 'harvesting', 'infrastructure': 'engineering', 'environmental': 'processing',
                'fabrication': 'crafting', 'cooking': 'cooking', 'medicine': 'medicine', 'emergency': 'emergency'}
STEPS_SHOWN = 9          # each fits with its button beside it on one Discord card


def _step(mark, name, detail='', action=None, view=None, label='', cost=0):
    """One walkthrough step. `action`: a one-time ticket that does it. `view`: the custom_id parts of the
    screen where it is done (spends nothing). `label`: the button's word. `cost`: SC it spends."""
    return {'mark': mark, 'name': name, 'detail': detail, 'action': action, 'view': view, 'label': label, 'cost': cost}


def _train(skill_label, level, current, hub):
    return _step('🔒', f'Reach {skill_label} Lv {level}', f'you are Lv {current} · each training task gives practice',
                 view=('mp', 'trainskill', '=' + hub) if hub else ('mv', 'training'), label='Train')


def _locks(m, ctx, e):
    """Steps that open a locked recipe: a festival, a personal tier, a skill level, the colony's tier or a workstation."""
    from . import seasonal, crafting_progression as cp
    steps = []
    if not seasonal.festival_open(e.id):
        holiday = seasonal.FESTIVAL_RECIPES[e.id]
        start, _ = seasonal.festival_window(holiday)
        steps.append(_step('🔒', f'Wait for the {holiday} festival', f'{e.name} can only be crafted then · opens {start.isoformat()}',
                           view=('mv', 'wd_holidays'), label='Festivals'))
    base_tier = s.base_tier(e.id) if e.kind == 'seed' else cp.STATIONS[e.tags[0]]['tier']
    if ctx.tier < base_tier:
        need = cp.TIERS[base_tier - 1][2]
        steps.append(_step('🔒', f'Reach personal Tier {base_tier}', f'craft {need - ctx.batches} more batches of anything made from ingredients · '
                           f'{ctx.batches}/{need}', view=('wc', 'ready', 1, ''), label='Craft'))
    if e.kind == 'seed' and ctx.level(e.skill_key) < e.level:
        main = s.SKILLS.get(e.skill_key, ('fabrication', None))[0]
        steps.append(_train(e.skill, e.level, ctx.level(e.skill_key), TRAINING_HUB.get(main, '')))
    if e.kind == 'seed' and any(k in cp.RARE for k in s.RECIPES[e.id]['outputs']) and ctx.harvesting < cp.RARE_LEVEL:
        steps.append(_train('Harvesting', cp.RARE_LEVEL, ctx.harvesting, 'harvesting'))
    if e.kind == 'legacy':
        need = m.RECIPE_TIERS.get(e.id)
        if need and ctx.society_tier < need:
            steps.append(_step('🔒', f'New Eridian reaches {m.SOCIETY_TIERS[need][0]}', 'the whole colony unlocks this together',
                               view=('mv', 'wd_society_progress'), label='Help'))
    if not steps and not ctx.usable_tags(e):
        tag = ctx.unlock_option(e)
        if tag:
            cfg = cp.STATIONS[tag]
            steps.append(_step('🔑', f"Unlock {cfg['name']}", f"{cfg['cost']} SC once, or own its machine · needed for {e.name}",
                               action={'do': 'unlock', 'station': tag, 'recipe': e.id, 'back': [e.category, 1, '']}, label='Unlock',
                               cost=cfg['cost']))
    return steps


def _collect(m, ctx, key, qty, ores):
    """Steps that bring in a raw material the goal still needs."""
    from . import crafting_progression as cp
    name = m.resource_name(key)
    if key in s.GATHER:
        if key in cp.RARE and ctx.harvesting < cp.RARE_LEVEL:
            return [_train('Harvesting', cp.RARE_LEVEL, ctx.harvesting, 'harvesting'),
                    _step('❌', f'Mine {name}', f'need {qty} · after Harvesting Lv {cp.RARE_LEVEL}', view=('mp', 'mine', '=' + key), label='Mine')]
        attempts = min(10, m.qol._gather_attempts(key, qty))
        verb = 'Mine' if key in ores else 'Gather'
        return [_step('✅', f'{verb} {name} ×{attempts}', f'need {qty} · runs as a queue',
                      action={'do': 'queue', 'task': ('mine:' if key in ores else 'gather:') + key, 'count': attempts}, label=verb)]
    if key == m.item_identity.ALIASES.get('crops'):
        return [_step('✅', f'Harvest {name}', f'need {qty} · 3 per harvest', action={'do': 'cmd', 'leaf': 'w_farm_harvest'}, label='Harvest')]
    if key == 'cargo':
        return [_step('✅', 'Prepare Cargo', f'need {qty} · 1 per success', action={'do': 'cmd', 'leaf': 'w_cargo'}, label='Work')]
    for task, cfg in m.SEED_TASKS.items():
        if key in cfg['output']:
            level = m.lvl(m.skill_xp(ctx.p, cfg['skill']))
            if level < cfg['unlock']:
                return [_train(m.SKILL_LABELS[cfg['skill']], cfg['unlock'], level, cfg['hub'])]
            return [_step('✅', f"{cfg.get('label') or task.replace('_', ' ').title()} for {name}", f'need {qty} · a training task',
                          action={'do': 'train', 'skill': cfg['hub'], 'task': task}, label='Start')]
    price = (m.SEED_INDUSTRIES.get(key) or {}).get('buy', 0)
    if price:
        return [_step('✅', f'Buy {name} ×{qty}', f'{price * qty} SC from Seed Industries',
                      action={'do': 'buyitem', 'item': key, 'amount': qty}, label='Buy', cost=price * qty)]
    found = wb.entry(m, key)
    if found is not None:
        return [_step('❌', f'Craft {name} ×{qty}', 'see its recipe', view=('wr', found.id, found.category, 1, ''), label='Recipe')]
    return [_step('❌', f'Get {name} ×{qty}', m.material_source(key).split(';')[0])]


def walkthrough(m, db, p, provider='discord'):
    """(goal recipe, every step still needed to craft it, in order). Each step has a button: do it, or go where it is done.

    Order: materials to collect, then each part to craft (after whatever unlocks it), then the goal
    (after whatever unlocks it). A step that spends more SC than you will have shows how to earn it.
    """
    e = goal_entry(m, db, p)
    if e is None:
        return None, []
    ctx = wb.Context(m, db, p, provider)
    if ctx.status(e).code == 'owned':
        return e, [_step('✅', f'You already own {e.name}', 'bonus equipment is limited to one of each · clear the goal and pick another',
                         view=('gc',), label='Clear')]
    crafts, raw = plan(ctx, e)
    ores = m.task_queue.ores()
    steps = []
    for key, qty in raw.items():
        steps += _collect(m, ctx, key, qty, ores)
    for sub, count in crafts:
        steps += _locks(m, ctx, sub)
        if ctx.status(sub).code == 'ready':
            steps.append(_step('✅', f'Craft {sub.name} ×{count}', 'all its ingredients are ready · runs as a queue',
                               action={'do': 'queue', 'task': 'make:' + sub.id, 'count': min(10, count)}, label='Craft'))
        else:
            steps.append(_step('❌', f'Craft {sub.name} ×{count}', 'a part for your goal · after the steps above',
                               view=('wr', sub.id, sub.category, 1, ''), label='Recipe'))
    steps += _locks(m, ctx, e)
    if ctx.status(e).code == 'ready':
        steps.append(_step('✅', f'Craft {e.name}', 'the goal · everything is ready',
                           action={'do': 'craft', 'recipe': e.id, 'back': [e.category, 1, '']}, label='Craft'))
    else:
        steps.append(_step('❌', f'Craft {e.name}', 'the goal · after the steps above', view=('wr', e.id, e.category, 1, ''), label='Recipe'))
    # One step per button: a skill or station named twice is one step (the higher level).
    unique, seen = [], {}
    for st in steps:
        target = st['view'] or st['name']
        if target in seen:
            first = seen[target]
            if st['name'] != first['name'] and st['name'].rsplit(' ', 1)[-1].isdigit() and first['name'].rsplit(' ', 1)[-1].isdigit():
                if int(st['name'].rsplit(' ', 1)[-1]) > int(first['name'].rsplit(' ', 1)[-1]):
                    first.update(name=st['name'], detail=st['detail'])
            continue
        seen[target] = st
        unique.append(st)
    # SC: spending steps you cannot afford yet show how to earn the rest.
    left = p.sc
    for st in unique:
        if not st['cost']:
            continue
        if st['cost'] > left:
            st.update(detail=f"{st['detail']} · you need {st['cost'] - max(0, left)} more SC", action=None,
                      view=('mp', 'guidegoal', '=seed_coin'), label='Earn SC')
        left -= st['cost']
    return e, unique


def next_step(m, db, p, provider='discord'):
    """(description, action) for the goal's next step; action is a ticket action dict, or None when the
    step is done somewhere else (training, the colony, earning SC: see walkthrough)."""
    _, steps = walkthrough(m, db, p, provider)
    if not steps:
        return '', None
    first = steps[0]
    return first['name'] + (f" ({first['detail'].split(' · ')[0]})" if first['detail'] else ''), first['action']


def goal_text(m, db, p, provider='discord'):
    e, steps = walkthrough(m, db, p, provider)
    if e is None:
        how = 'Open a recipe and press 🎯 Set goal.' if provider == 'discord' else '!target <recipe name> sets one.'
        return f'🎯 No goal yet. {how} The goal then walks you through every step, with a button for each.'
    ctx = wb.Context(m, db, p, provider)
    total = len(e.inputs) or 1
    covered = sum(1 for k, n in e.inputs.items() if ctx.have(k) >= n)
    if provider != 'discord':
        step, _ = next_step(m, db, p, provider)
        later = ' → '.join(st['name'] for st in steps[1:4])
        return f'🎯 Goal {e.name} {covered}/{total} ingredients | Next: {step}' + (f' | Then: {later}' if later else '') + ' | !target clear'
    status = ctx.status(e)
    lines = [f'🎯 GOAL — {e.name.upper()}', f'{"█" * covered}{"░" * (total - covered)} {covered}/{total} ingredients ready · {status.emoji} {status.short}',
             '', f'STEPS · {len(steps)} TO GO' if len(steps) != 1 else 'LAST STEP']
    for i, st in enumerate(steps[:STEPS_SHOWN], 1):
        lines.append(f"`{i}` {st['mark']} {st['name']}" + (f" — {'next · ' if i == 1 else ''}{st['detail']}" if st['detail'] else ''))
    if len(steps) > STEPS_SHOWN:
        lines.append(f'…and {len(steps) - STEPS_SHOWN} more after these.')
    lines += ['', 'Each button does that step once, or opens where it is done. After a step, the result has a 🎯 Goal button back here.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- plans and routines

def playlist(db, channel, uid):
    found = row(db, channel, uid)
    return json.loads(found.playlist) if found is not None else []


def add_step(m, db, p, step):
    """Add a queue or sell step after everything already planned."""
    qol = m.qol
    if 'task' in step and not qol.next_task(db, p.channel_id, p.twitch_uid)[0] and not playlist(db, p.channel_id, p.twitch_uid):
        ok, text = qol.set_next(m, db, p, step['task'], step['count'])
        return text
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    steps = json.loads(found.playlist)
    if len(steps) >= MAX_STEPS:
        return f'Your plan already has {MAX_STEPS} later steps. Let some run first. Nothing changed.'
    steps.append(step)
    found.playlist = json.dumps(steps)
    db.flush()
    return f'➕ Added to your plan: {step_label(m, step)} (step {len(current_steps(m, db, p))} of your plan).'


def clear_plan(db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    if found is not None:
        found.playlist = '[]'


def step_label(m, step):
    if 'sell' in step:
        return 'Sell all ' + m.resource_name(step['sell'])
    return f"{m.task_queue.choices(m).get(step['task'], step['task'])} ×{step['count']}"


def pop_step(m, db, p):
    """The next queue step of the plan, running any 'sell all' steps on the way. Returns (task, count, notes)."""
    found = row(db, p.channel_id, p.twitch_uid)
    if found is None:
        return '', 0, []
    steps = json.loads(found.playlist)
    notes = []
    while steps:
        step = steps.pop(0)
        if 'sell' in step:
            notes.append(m.qol.sell_all(m, db, p, step['sell'], 'discord').split('. Balance')[0])
            continue
        found.playlist = json.dumps(steps)
        return step['task'], step['count'], notes
    found.playlist = '[]'
    return '', 0, notes


def current_steps(m, db, p):
    tq = m.task_queue
    queue = db.get(tq.TaskQueue, (p.channel_id, p.twitch_uid))
    steps = []
    if queue is not None and queue.state in tq.ACTIVE:
        steps.append({'task': queue.task, 'count': queue.total})
    task, count = m.qol.next_task(db, p.channel_id, p.twitch_uid)
    if task:
        steps.append({'task': task, 'count': count})
    return steps + playlist(db, p.channel_id, p.twitch_uid)


def routines(db, p):
    return list(db.scalars(select(Routine).where(Routine.channel_id == p.channel_id, Routine.canonical_uid == p.twitch_uid).order_by(Routine.id)))


def save_routine(m, db, p):
    steps = current_steps(m, db, p)
    if not steps:
        return 'Nothing to save: start a queue and add steps to your plan first.'
    saved = routines(db, p)
    if len(saved) >= MAX_ROUTINES:
        return f'You already have {MAX_ROUTINES} routines. Delete one first. Nothing saved.'
    name = ' → '.join(step_label(m, st) for st in steps)[:100]
    db.add(Routine(channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=name, steps=json.dumps(steps), created_at=m.now()))
    return f'💾 Routine saved: {name}. Start it any time from /menu → Work → Queue → Plan & routines.'


def delete_routine(db, p, routine_id):
    found = db.get(Routine, int(routine_id))
    if found is not None and found.canonical_uid == p.twitch_uid and found.channel_id == p.channel_id:
        db.delete(found)
        return True
    return False


def start_routine(m, channel, uid, name, provider, routine_id):
    """Start a saved routine: its first queue step now (or after the current queue), the rest planned."""
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, name)[1]
        found = db.get(Routine, int(routine_id))
        if found is None or found.canonical_uid != p.twitch_uid:
            return 'That routine no longer exists.'
        steps = json.loads(found.steps)
        queue = db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid))
        busy = queue is not None and queue.state in m.task_queue.ACTIVE
        db.commit()
    if busy:
        with m.SessionLocal() as db:
            p = m.player(db, channel, provider, uid, name)[1]
            notes = [add_step(m, db, p, st) for st in steps]
            db.commit()
        return '▶️ Your queue is busy, so the routine was added to your plan.\n' + '\n'.join(notes)
    first = next((i for i, st in enumerate(steps) if 'task' in st), None)
    if first is None:
        return 'This routine has no queue steps.'
    result = m.queued_tasks(channel, uid, name, 'start', steps[first]['task'], str(steps[first]['count']), provider).body.decode()
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, name)[1]
        for st in steps[first + 1:]:
            add_step(m, db, p, st)
        db.commit()
    return f'▶️ Routine started: {found.name}\n\n' + result


def plan_text(m, db, p):
    steps = current_steps(m, db, p)
    lines = ['🗺️ PLAN & ROUTINES', 'Queue several steps; each starts when the one before it finishes. "Sell all" steps run in between.', '', 'YOUR PLAN']
    lines += [f'{i}. {step_label(m, st)}' for i, st in enumerate(steps, 1)] or ['Nothing planned. Start a queue, then press ➕ Add to plan on another.']
    saved = routines(db, p)
    lines += ['', f'SAVED ROUTINES · {len(saved)}/{MAX_ROUTINES}'] + ([f'{i}. {r.name}' for i, r in enumerate(saved, 1)] or ['None yet. Save your current plan below.'])
    return '\n'.join(lines)


# ---------------------------------------------------------------- what can I make with this?

def uses_text(m, db, p, key, provider='discord'):
    ctx = wb.Context(m, db, p, provider)
    rows = [e for e in wb.index(m) if key in e.inputs]
    rows.sort(key=lambda e: (wb.STATUS_ORDER[ctx.status(e).code], e.sort_key))
    name = m.resource_name(key)
    if provider != 'discord':
        shown = ', '.join(f'{ctx.status(e).emoji}{e.name}' for e in rows[:8]) or 'nothing'
        return f'🔍 {name} ({ctx.have(key)}) is used in {len(rows)} recipes: {shown}', rows
    lines = [f'🔍 WHAT CAN I MAKE WITH {name.upper()}?', f'You have {ctx.have(key)}. It is used in {len(rows)} recipes, ready ones first.', '']
    lines += [f'{ctx.status(e).emoji} **{e.name}** — needs {e.inputs[key]} · {ctx.status(e).short}' for e in rows[:15]]
    if len(rows) > 15:
        lines.append(f'…and {len(rows) - 15} more.')
    if not rows:
        lines.append('No recipe uses it. Seed Industries buys it: /seedindustries.')
    return '\n'.join(lines), rows


# ---------------------------------------------------------------- auto-sell and undo

def autosell_list(db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    return json.loads(found.autosell) if found is not None else []


def toggle_autosell(m, db, p, key):
    key = m.item_identity.canonical(key)
    if not m.qol.sell_price(m, key):
        return f'Seed Industries does not buy {m.resource_name(key)}. Nothing changed.'
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    keys = json.loads(found.autosell)
    if key in keys:
        keys.remove(key)
        text = f'🧹 {m.resource_name(key)} will no longer be sold automatically.'
    else:
        keys.append(key)
        text = f'🧹 {m.resource_name(key)} will be sold automatically when a queue finishes (favourite and queued ingredients are kept).'
    found.autosell = json.dumps(keys[:20])
    return text


def autosell_after_queue(m, db, p):
    keys = autosell_list(db, p)
    if not keys:
        return []
    keep = m.qol.protected_items(m, db, p)
    notes = []
    for key in keys:
        if key in keep or m.material_amount(db, p, key) <= 0:
            continue
        notes.append(m.qol.sell_all(m, db, p, key, 'discord').split('. Balance')[0].replace('🏭 ', '🧹 Auto-'))
    return notes


def autosell_text(m, db, p):
    keys = autosell_list(db, p)
    lines = ['🧹 AUTO-SELL', 'Chosen items are sold to Seed Industries when a queue finishes. Ingredients of favourites and queued recipes are always kept.', '']
    lines += [f'• {m.resource_name(k)} (you have {m.material_amount(db, p, k)})' for k in keys] or ['Nothing chosen yet. Pick an item below; Stone Dust is a common choice.']
    return '\n'.join(lines)


def remember_sale(m, db, p, items, sc, xp):
    row(db, p.channel_id, p.twitch_uid, create=True).last_sale = json.dumps(
        {'items': items, 'sc': sc, 'xp': xp, 'at': m.now().isoformat()})


def undo_sale(m, db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    sale = json.loads(found.last_sale) if found is not None and found.last_sale else None
    if not sale:
        return '↩️ There is no recent sale to undo.'
    from datetime import datetime
    age = (m.now() - m.as_utc(datetime.fromisoformat(sale['at']))).total_seconds()
    if age > UNDO_SECONDS:
        found.last_sale = ''
        return f'↩️ Sales can only be undone within {UNDO_SECONDS} seconds. This one is final.'
    if p.sc < sale['sc']:
        return f"↩️ Undoing needs {sale['sc']} SC back and you have {p.sc}. Nothing changed."
    for key, qty in sale['items'].items():
        m.material_change(db, p, key, qty)
    p.sc -= sale['sc']
    from .competencies import FIELDS
    setattr(p, FIELDS['commerce'], max(0, getattr(p, FIELDS['commerce']) - sale['xp']))
    found.last_sale = ''
    db.commit()
    items = ', '.join(f'{m.resource_name(k)} ×{q}' for k, q in sale['items'].items())
    return f"↩️ Sale undone: {items} returned and {sale['sc']} SC taken back (with the Commerce practice it earned). Balance: {p.sc} SC."


# ---------------------------------------------------------------- eat until full

def eat_full(m, db, p, provider='discord'):
    life = m.life_state(db, p)
    if life.nutrition >= FULL_NUTRITION:
        return f'ℹ️ Nutrition is already {life.nutrition}/100. Your food was kept.'
    from .seasonal import FESTIVAL_ITEMS
    foods = [r for r in m.edible_inventory(db, p) if r['key'] != 'meal_kit' and r['key'] not in FESTIVAL_ITEMS and r['qty'] > 0]
    if not foods:
        if m.emergency_food_available(db, p, []):
            return m.action('eat', p.channel_id, p.twitch_uid, p.display_name, msg='food:emergency', provider=provider).body.decode()
        return '🍲 You have no everyday food (festival foods and Meal Kits are kept for you). Harvest, gather or craft some first.'
    wait = m.check_cooldown(db, p, 'eat')
    if wait:
        return f'⏱️ You can eat again in {wait}s.'
    before = life.nutrition
    eaten = defaultdict(int)
    for food in sorted(foods, key=lambda r: (r['gain'], r['name'])):
        while food['qty'] > 0 and life.nutrition < FULL_NUTRITION:
            m.material_change(db, p, food['key'], -1)
            food['qty'] -= 1
            life.nutrition = m.clamp100(life.nutrition + food['gain'])
            eaten[food['name']] += 1
            if m.prepared_food(food['key']):
                m.grant_rockys_favor(db, p, 10)
    db.commit()
    listed = ', '.join(f'{n} ×{q}' for n, q in eaten.items())
    return f'🍲 {p.display_name} eats until full: {listed}. Nutrition {before}→{life.nutrition}.'


# ---------------------------------------------------------------- welcome back and reminders

def touch(m, db, p):
    """On each Discord interaction: welcome-back summary and one-off reminders go to the inbox."""
    from . import inbox, seasonal
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    now = m.now()
    last = m.as_utc(found.last_seen) if found.last_seen else None
    reminded = json.loads(found.reminded or '{}')
    if last is not None and now - last >= WELCOME_AFTER:
        away = now - last
        hours = int(away.total_seconds() // 3600)
        lines = [f'👋 **Welcome back, {p.display_name}!** You were away {hours}h.' if hours < 48 else f'👋 **Welcome back, {p.display_name}!** You were away {away.days} days.']
        results = list(db.scalars(select(inbox.InboxItem).where(inbox.InboxItem.channel_id == p.channel_id, inbox.InboxItem.canonical_uid == p.twitch_uid,
                                                                  inbox.InboxItem.kind == 'queue', inbox.InboxItem.created_at >= last)))
        for item in results[-3:]:
            lines.append(item.text.splitlines()[0])
        inbox.mark_seen(db, [i.id for i in results])
        life = m.life_state(db, p)
        lines.append(f'Needs now: ⚡ {life.energy} · 🍲 {life.nutrition} · 💬 {life.social} · 🛋️ {life.comfort}' +
                     ('' if not needs.blocked_needs(life) else ' — /life → Recover gets you working.'))
        try:
            d = m.daily(db, p)
            lines.append(f"📋 Daily contract: {m.guide_command(d.action, 'discord')} {'✅ done' if d.complete else f'{d.progress}/{d.target}'}")
        except Exception:
            pass
        festivals = seasonal.holidays_active_for(now.date())
        if festivals:
            lines.append(f"🎉 {festivals[0]['name']} festival is on: festival foods can be crafted now.")
        step, _ = next_step(m, db, p)
        if step:
            lines.append('🎯 Goal next step: ' + step)
        lines += m.autonomy.away_lines(m, db, p, last)
        inbox.add(m, db, p.channel_id, p.twitch_uid, 'info', '\n'.join(lines))
    # Sleep is ready again while Energy or Comfort is low.
    life = m.life_state(db, p)
    if not m.action_wait(db, p, 'sleep') and min(life.energy, life.comfort) < 40:
        marker = str(getattr(db.execute(select(m.Cooldown).where(m.Cooldown.channel_id == p.channel_id, m.Cooldown.canonical_uid == p.twitch_uid,
                                                                  m.Cooldown.action == 'sleep')).scalar_one_or_none(), 'ready_at', 'never'))
        if reminded.get('sleep') != marker:
            reminded['sleep'] = marker
            inbox.add(m, db, p.channel_id, p.twitch_uid, 'info', '🛏️ **Sleep is ready.** It refills Energy and Comfort to 100: /life → Sleep.',
                      important=min(life.energy, life.comfort) < 20)
    for festival in seasonal.holidays_active_for(now.date()):
        key = f"{festival['name']}:{festival['holiday_date'].year}"
        if reminded.get('festival') != key:
            reminded['festival'] = key
            foods = ', '.join(food[0] for food in seasonal.FESTIVAL_FOODS[festival['name']])
            inbox.add(m, db, p.channel_id, p.twitch_uid, 'info', f"{festival['emoji']} **{festival['name']} festival is open!** Festival foods: {foods}. "
                      '/world → Holidays shows ingredients.', important=False)
        break
    try:
        d = m.daily(db, p)
        day_key = f'{d.action}:{getattr(d, "avesta_day", "")}:{d.target}'
        if reminded.get('daily') != day_key:
            if 'daily' in reminded:
                inbox.add(m, db, p.channel_id, p.twitch_uid, 'info', f"📋 **New daily contract:** {m.guide_command(d.action, 'discord')} ×{d.target} "
                          f'for {d.reward_sc} SC.', important=False)
            reminded['daily'] = day_key
    except Exception:
        pass
    goal = goal_entry(m, db, p)
    if goal is not None and wb.Context(m, db, p).status(goal).code == 'ready' and reminded.get('goal') != goal.id:
        reminded['goal'] = goal.id
        inbox.add(m, db, p.channel_id, p.twitch_uid, 'milestone', f'🎯 **Your goal {goal.name} is ready to craft!** /menu → Craft → Goal.')
    found.reminded = json.dumps(reminded)
    found.last_seen = now


def goal_completed(m, db, p, text):
    """Clear the goal when it was just crafted and celebrate once."""
    goal = goal_entry(m, db, p)
    if goal is None or 'CRAFTING COMPLETE' not in text or goal.name not in text:
        return
    from . import inbox
    clear_goal(db, p)
    inbox.add(m, db, p.channel_id, p.twitch_uid, 'milestone', f'🎯 **Goal complete: {goal.name}!** Pick a new one from any recipe.')


# ---------------------------------------------------------------- remember my place

def remember_place(db, p, category, page, station_code):
    if category:
        row(db, p.channel_id, p.twitch_uid, create=True).workbench = f'{category}|{page}|{station_code}'


def last_place(db, p):
    found = row(db, p.channel_id, p.twitch_uid)
    if found is None or not found.workbench:
        return None
    category, page, station = (found.workbench.split('|') + ['', '1', ''])[:3]
    return category, int(page or 1), station


def default_options(m, command, options, discord_uid):
    """A bare /make reopens the Workbench where you left it."""
    if command != 'make' or options:
        return options
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', discord_uid, 'Citizen')[1]
        place = last_place(db, p)
        db.commit()
    if not place or place[0] not in wb.VIEW_INFO:
        return options
    category, page, station = place
    result = {'category': category, 'page': page}
    tag = wb.station_from_code(station) if station else ''
    if tag:
        result['station'] = tag
    return result


# ---------------------------------------------------------------- find anything

def find(m, query, limit=5):
    """Search recipes, items, menu buttons and handbook topics."""
    q = ' '.join(str(query or '').casefold().split())
    if not q:
        return {'recipes': [], 'items': [], 'menu': [], 'topics': []}
    def score(text):
        text = text.casefold()
        return 0 if text == q else 1 if text.startswith(q) else 2 if q in text else None
    recipes, seen = [], set()
    for e in wb.index(m):
        sc = score(e.name)
        if sc is not None and e.name not in seen:
            seen.add(e.name)
            recipes.append((sc, e.sort_key, e))
    items = [(score(s.ITEMS[k]['name']), s.ITEMS[k]['name'], k) for k in s.ACTIVE if score(s.ITEMS[k]['name']) is not None]
    if not recipes and not items:
        near, _ = m.qol.match(q, m.qol.item_names())
        if near:
            items = [(3, s.ITEMS[near]['name'], near)]
    menu = []
    for key, leaf in m.menu.LEAVES.items():
        text = leaf['label'] + ' ' + leaf.get('hint', '')
        if q in text.casefold():
            menu.append(key)
    for key, (_, title, text, _) in m.menu.AREAS.items():
        if key != 'home' and q in (title + ' ' + text).casefold():
            menu.insert(0, key)
    topics = [t for t in ('start', 'character', 'property', 'life', 'production', 'operations', 'society', 'other', 'terms')
              if q in m.discord_seed_help(t).casefold()]
    return {'recipes': [e for _, _, e in sorted(recipes, key=lambda r: (r[0], r[1]))[:limit]],
            'items': [k for _, _, k in sorted(items)[:limit]], 'menu': list(dict.fromkeys(menu))[:limit], 'topics': topics[:3]}


def find_text(m, query, provider='discord'):
    found = find(m, query)
    if provider != 'discord':
        parts = []
        if found['recipes']:
            parts.append('Recipes: ' + ', '.join(e.name for e in found['recipes']))
        if found['items']:
            parts.append('Items: ' + ', '.join(s.ITEMS[k]['name'] for k in found['items']))
        if found['topics']:
            parts.append('Handbook: ' + ', '.join('!seed ' + t for t in found['topics']))
        return f'🔎 "{query}": ' + (' | '.join(parts) if parts else 'nothing found. Try a shorter word.')
    lines = [f'🔎 RESULTS FOR "{query.upper()}"']
    if found['recipes']:
        lines += ['', 'RECIPES'] + [f'• {e.name} — {e.skill} Lv{e.level} · {wb.station_label(e)}' for e in found['recipes']]
    if found['items']:
        lines += ['', 'ITEMS'] + [f"• {s.ITEMS[k]['name']} — {m.material_source(k).split(' or ')[0].split(';')[0]}" for k in found['items']]
    if found['menu']:
        labels = [m.menu.AREAS[k][1] if k in m.menu.AREAS else m.menu.LEAVES[k]['label'] for k in found['menu']]
        lines += ['', 'BUTTONS'] + ['• ' + x for x in labels]
    if found['topics']:
        lines += ['', 'HANDBOOK'] + [f'• /seed topic:{t}' for t in found['topics']]
    if len(lines) == 1:
        lines.append('Nothing found. Try a shorter word or another spelling.')
    else:
        lines += ['', 'Tap a button below to open a result.']
    return '\n'.join(lines)
