"""Quality-of-life systems shared by Discord, Twitch and the queue worker.

Everything here builds on the existing game functions rather than replacing
them: recovery calls the same /relax, /games, /eat, /sleep and /use handlers a
player would, selling uses Seed Industries prices, and fetching ingredients
starts ordinary queues. One per-citizen preferences row stores favourites,
alert mode, auto-recovery and the single follow-up queue slot, so every view
(status, Workbench, queue alerts, inventory, clear-out) reads the same choices.
"""
import difflib
import json
import math
from contextlib import contextmanager
from sqlalchemy import Column, String, Integer, Text, select
from .db import Base
from . import seed_content as s, crafting_progression as cp, workbench as wb, needs
from . import runtime
from .models import Cooldown

MAX_FAVORITES = 10
CLEAROUT_RESERVE = 20
NEWCOMER_TIER = 3          # next-step hints on action cards below Tier 3
MINING_SUCCESS_GUESS = 0.68  # base work success; fetch plans pad ore attempts by it
ALERT_MODES = {
    'dm': 'Direct message (the default); if your DMs are closed, it waits in your Notifications',
    'mention': 'Channel @mention: posted in the game channel, where everyone sees it',
    'private': 'No ping; shown only to you, the next time you use a command or button',
    'quiet': 'A direct message only when a queue finishes or stops; no pause alerts',
    'off': 'No alerts; check /status or /queue',
}
DEFAULT_ALERTS = 'dm'      # queue alerts never fill the game channel unless a player asks for channel mentions
QUIET_MARKER = 8           # simulation_schema_versions row: old default (channel mention) moved to DM once
ALERT_LABELS = {'mention': 'channel mention', 'dm': 'direct message', 'private': 'private popup', 'quiet': 'quiet (finish/stop only)', 'off': 'off'}
INVENTORY_SORTS = ('quantity', 'name', 'value', 'category')
INVENTORY_SHOWS = ('all', 'ready', 'favorites', 'sellable')
INVENTORY_PAGE = 15


class Preferences(Base):
    """Additive per-citizen settings; a missing row means every default."""
    __tablename__ = 'player_preferences_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    favorites = Column(Text, nullable=False, default='[]')
    alerts = Column(String(12), nullable=False, default=DEFAULT_ALERTS)
    autorecover = Column(Integer, nullable=False, default=0)
    next_task = Column(String(96), nullable=False, default='')
    next_count = Column(Integer, nullable=False, default=0)


def install(m):
    Preferences.__table__.create(runtime.engine, checkfirst=True)
    quiet_channel_once()


def quiet_channel_once():
    """Once per database: citizens still on the old default alert (a channel @mention) move to the new
    default (a direct message), so queue alerts stop filling the game channel. Anyone can choose
    channel mentions again in /settings; this never runs a second time."""
    from sqlalchemy import text as sql_text
    from sqlalchemy.exc import IntegrityError
    from .models import SimulationVersion
    try:
        with runtime.engine.begin() as conn:
            if conn.execute(sql_text('SELECT version FROM simulation_schema_versions WHERE version=:v'), {'v': QUIET_MARKER}).first():
                return
            conn.execute(sql_text("UPDATE player_preferences_v1 SET alerts=:new WHERE alerts='mention'"), {'new': DEFAULT_ALERTS})
            conn.execute(SimulationVersion.__table__.insert().values(version=QUIET_MARKER))
    except IntegrityError:
        pass                                   # another instance ran it at the same moment


def prefs(db, channel, uid, create=False):
    row = db.get(Preferences, (channel, uid))
    if row is None and create:
        row = Preferences(channel_id=channel, canonical_uid=uid, favorites='[]', alerts=DEFAULT_ALERTS,
                          autorecover=0, next_task='', next_count=0)
        db.add(row)
        db.flush()
    return row


def alert_mode(db, channel, uid):
    row = prefs(db, channel, uid)
    return row.alerts if row is not None and row.alerts in ALERT_MODES else DEFAULT_ALERTS


def autorecover_on(db, channel, uid):
    row = prefs(db, channel, uid)
    return bool(row is not None and row.autorecover)


def merge(db, channel, source, target):
    """Account linking keeps the target's settings and adds the source's favourites."""
    src = db.get(Preferences, (channel, source))
    if src is None:
        return
    dst = db.get(Preferences, (channel, target))
    if dst is None:
        src.canonical_uid = target
        return
    ids = json.loads(dst.favorites)
    ids += [i for i in json.loads(src.favorites) if i not in ids]
    dst.favorites = json.dumps(ids[:MAX_FAVORITES])
    if not dst.next_task and src.next_task:
        dst.next_task, dst.next_count = src.next_task, src.next_count
    db.delete(src)


@contextmanager
def acting_as(channel, uid):
    """Run ordinary game commands for a canonical citizen id (as queue attempts do)."""
    from . import task_queue
    tq = task_queue
    actor = tq.actor_context.set((channel, uid))
    wait = tq.cooldown_wait.set(0)
    try:
        yield
    finally:
        tq.cooldown_wait.reset(wait)
        tq.actor_context.reset(actor)


def _prefix(provider):
    return '/' if provider == 'discord' else '!'


# ---------------------------------------------------------------- favourites

def favorite_ids(db, p):
    row = prefs(db, p.channel_id, p.twitch_uid) if p is not None else None
    return [i for i in (json.loads(row.favorites) if row else []) if wb.entry(i) is not None]


def favorite_entries(db, p):
    return [wb.entry(i) for i in favorite_ids(db, p)]


def set_favorite(db, p, recipe, on=None):
    """Add (on=True), remove (on=False) or toggle (None). Returns the message."""
    e = wb.entry(recipe) if recipe else None
    if e is None:
        return 'That recipe is not available. Choose one from the Workbench. Nothing changed.'
    row = prefs(db, p.channel_id, p.twitch_uid, create=True)
    ids = [i for i in json.loads(row.favorites) if wb.entry(i) is not None]
    if on is None:
        on = e.id not in ids
    if on:
        if e.id in ids:
            return f'⭐ {e.name} is already a favourite.'
        if len(ids) >= MAX_FAVORITES:
            return f'⭐ You already have {MAX_FAVORITES} favourites. Remove one before adding {e.name}. Nothing changed.'
        ids.append(e.id)
        text = f'⭐ {e.name} added to favourites ({len(ids)}/{MAX_FAVORITES}). Favourites are listed first in the Workbench, Ready now and status.'
    else:
        if e.id not in ids:
            return f'☆ {e.name} is not a favourite. Nothing changed.'
        ids.remove(e.id)
        text = f'☆ {e.name} removed from favourites ({len(ids)}/{MAX_FAVORITES}).'
    row.favorites = json.dumps(ids)
    return text


def favorites_text(db, p, provider):
    ctx = wb.Context(db, p, provider)
    rows = favorite_entries(db, p)
    prefix = _prefix(provider)
    if not rows:
        how = ('Open a recipe in /make and press ⭐ Favourite, or use /make recipe:<name> action:Favourite.'
               if provider == 'discord' else '!fav <recipe name> stars a recipe.')
        return f'⭐ No favourite recipes yet. {how}'
    if provider != 'discord':
        return '⭐ Favourites: ' + ' · '.join(f'{ctx.status(e).emoji}{e.name}' for e in rows) + f' | {prefix}make <name> crafts; !fav <name> removes.'
    lines = [f'⭐ FAVOURITES · {len(rows)}/{MAX_FAVORITES}']
    lines += [f'{ctx.status(e).emoji} {e.name} ×{ctx.batch_size(e)} — {ctx.status(e).short}' for e in rows]
    lines += ['', '/make category:Favourites opens them in the Workbench.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- follow-up queue

def next_task(db, channel, uid):
    row = prefs(db, channel, uid)
    return (row.next_task, row.next_count) if row is not None and row.next_task else ('', 0)


def set_next(db, p, task, count):
    """Store the one follow-up queue. Returns (ok, message)."""
    from . import task_queue
    tq = task_queue
    task = tq.normalize(str(task or ''))
    if task not in tq.choices():
        return False, 'Choose a valid Task for the next queue. Nothing changed.'
    if not 1 <= int(count) <= 10:
        return False, 'Count must be a whole number from 1 to 10. Nothing changed.'
    row = prefs(db, p.channel_id, p.twitch_uid, create=True)
    replaced = row.next_task
    row.next_task, row.next_count = task, int(count)
    label = tq.choices().get(task, task)
    text = f'⏭️ Next queue set: {label} ×{count}. It starts automatically when the current queue completes.'
    if replaced and replaced != task:
        text += ' (Replaced the previous next queue.)'
    return True, text


def clear_next(db, channel, uid):
    row = prefs(db, channel, uid)
    if row is None or not row.next_task:
        return False
    row.next_task, row.next_count = '', 0
    return True


def pop_next(db, channel, uid):
    task, count = next_task(db, channel, uid)
    if task:
        clear_next(db, channel, uid)
    return task, count


def next_label(db, channel, uid):
    from . import task_queue
    task, count = next_task(db, channel, uid)
    return f'{task_queue.choices().get(task, task)} ×{count}' if task else ''


# ---------------------------------------------------------------- recovery

def passive_eta(life, value, target):
    """Seconds until passive recovery lifts `value` to `target`; None if it never will."""
    from .game.players import as_utc
    if value >= target:
        return 0
    if target > needs.RECOVERY_CAP:
        return None
    last = as_utc(life.last_decay_at)
    partial = max(0, (runtime.now() - last).total_seconds()) if last else 0
    return max(1, math.ceil((target - value) * needs.TICK_SECONDS / needs.RECOVERY_PER_TICK - partial))


def eta_text(seconds):
    """Estimates round up to the minute, so they never promise too early."""
    return needs.duration_text(seconds if seconds < 60 else math.ceil(seconds / 60) * 60)


def need_line(db, p, life, field, label, value, minimum, provider='discord'):
    from .game.world import need_fix
    text = f'{label}: {value}/100; need {minimum}. Use {need_fix(field, provider, db, p)}.'
    eta = passive_eta(life, value, minimum)
    if eta:
        # A timestamp stays correct wherever this text is shown later (queue status, alerts).
        text += f' Passive recovery reaches {minimum} <t:{int(runtime.now().timestamp() + eta)}:R>.' if provider == 'discord' else \
                f' Passive recovery reaches {minimum} in about {eta_text(eta)}.'
    return text


def resume_eta(life):
    """Longest passive wait among blocking needs: when a paused queue resumes on its own."""
    waits = [passive_eta(life, value, minimum) for _, _, value, minimum in needs.blocked_needs(life)]
    return None if any(w is None for w in waits) else max(waits, default=0)


def _cheapest_food(db, p):
    from .game.training_and_items import edible_inventory, emergency_food_available
    foods = [row for row in edible_inventory(db, p) if row['key'] != 'meal_kit' and row['qty'] > 0]
    if foods:
        return min(foods, key=lambda row: (row['gain'], row['name']))['key']
    return 'emergency' if emergency_food_available(db, p, []) else ''


def _comfort_item(db, p):
    """Best owned durable item that restores Comfort without consuming anything."""
    stock = s.stock(db, p)
    rows = [(cfg['boost'].get('comfort', 0), k) for k, cfg in s.PURPOSE.items()
            if cfg['mode'] == 'recover' and not cfg['consume'] and cfg.get('boost', {}).get('comfort') and stock.get(k, 0) > 0]
    return max(rows)[1] if rows else ''


def recover(db, p, channel, uid):
    """One round of recovery for every need that blocks work.

    Runs the ordinary recovery commands (never a special shortcut), so their
    cooldowns and effects apply. Returns short notes of what changed.
    """
    from .game.action import action
    from .game.cooldowns_materials import action_wait
    from .game.life import life_state
    from .game.players import resource_name
    from .game.routes_life_social import games, relax
    from .game.routes_market import use_item
    life = life_state(db, p)
    if not needs.blocked_needs(life):
        return []
    notes = []
    name = p.display_name

    def attempt(label, fn):
        before = {f: getattr(life_state(db, p), f) for f in needs.FIELDS}
        db.flush()
        fn()
        db.expire_all()
        after = life_state(db, p)
        changed = [f'{f.title()} {before[f]}→{getattr(after, f)}' for f in ('energy', 'nutrition', 'social', 'comfort')
                   if getattr(after, f) != before[f]]
        if changed:
            notes.append(f'{label}: ' + ', '.join(changed))
        return bool(changed)

    def blocked(field):
        return any(f == field for f, *_ in needs.blocked_needs(life_state(db, p)))

    with acting_as(channel, uid):
        if blocked('energy') or blocked('comfort'):
            if not action_wait(db, p, 'relax'):
                attempt('Relaxed', lambda: relax(channel, uid, name, provider='discord'))
            if (blocked('energy') or blocked('comfort')) and not action_wait(db, p, 'sleep'):
                attempt('Slept', lambda: action('sleep', channel, uid, name, provider='discord'))
            if blocked('comfort') and not action_wait(db, p, 'seed_use'):
                item = _comfort_item(db, p)
                if item:
                    attempt('Used ' + s.item_label(item), lambda: use_item(channel, uid, name, item=item, provider='discord'))
        if blocked('nutrition'):
            food = _cheapest_food(db, p)
            if food and not action_wait(db, p, 'eat'):
                label = 'Emergency meal' if food == 'emergency' else 'Ate ' + resource_name(food)
                attempt(label, lambda: action('eat', channel, uid, name, msg='food:' + food, provider='discord'))
        if blocked('social') and not action_wait(db, p, 'games'):
            attempt('Played games', lambda: games(channel, uid, name, provider='discord'))
    return notes


def recover_text(db, p, provider):
    """Manual one-press recovery (/status button, !recover)."""
    from .game.life import life_state
    life = life_state(db, p)
    if not needs.blocked_needs(life):
        return (f'✅ {p.display_name}, nothing blocks work right now. '
                f'Energy {life.energy} · Nutrition {life.nutrition} · Social {life.social} · Comfort {life.comfort}.')
    notes = recover(db, p, p.channel_id, p.twitch_uid)
    db.expire_all()
    life = life_state(db, p)
    left = needs.blocked_needs(life)
    lines = ['🩹 RECOVERY'] + (['• ' + n for n in notes] if notes else ['• Every recovery action is on cooldown right now.'])
    if left:
        lines += ['', 'STILL BLOCKED'] + ['• ' + need_line(db, p, life, *row, provider=provider) for row in left]
    else:
        lines += ['', '✅ Ready for work. Paused queues resume within 10 seconds.']
    return '\n'.join(lines) if provider == 'discord' else ' | '.join(x for x in lines if x)


# ---------------------------------------------------------------- next step

def next_step(db, p, provider, ctx=None):
    """One concrete suggestion: a ready favourite first, then the Workbench suggestion."""
    from .game.players import resource_name
    ctx = ctx or wb.Context(db, p, provider)
    prefix = _prefix(provider)
    for e in favorite_entries(db, p):
        if ctx.status(e).code == 'ready':
            how = f'/make recipe:{e.id}' if provider == 'discord' else f'!make {e.name}'
            return f'⭐ {e.name} is ready to craft: {how}'
    easy = wb.start_here(ctx, 1)
    if easy:
        e = easy[0]
        how = f'/make recipe:{e.id}' if provider == 'discord' else f'!make {e.name}'
        return f'✅ {e.name} is ready at {wb.station_label(e, ctx)}: {how}'
    for e in wb.gather_first(ctx, 1):
        missing = ', '.join(f'{n - ctx.have(k)} {resource_name(k)}' for k, n in e.inputs.items() if ctx.have(k) < n)
        how = f'/make recipe:{e.id} action:Fetch missing' if provider == 'discord' else f'!fetch {e.name}'
        return f'🧺 Gather {missing} for {e.name}: {how}'
    return f'Gather with {prefix}gather or {prefix}mine, then open {prefix}make.'


def action_hint(db, p, provider, tier_before=None):
    """Appended to manual craft and gather receipts: tier-ups for all, hints for newer citizens."""
    from . import task_queue
    if task_queue.actor_context.get() is not None:
        return ''   # queue attempts are summarised by the queue itself
    ctx = wb.Context(db, p, provider)
    text = ''
    if tier_before is not None and ctx.tier > tier_before:
        name = cp.TIERS[ctx.tier - 1][1]
        opened = sum(1 for e in wb.index() if (s.base_tier(e.id) if e.kind == 'seed' else cp.STATIONS[e.tags[0]]['tier']) == ctx.tier)
        text += f'\n\n🏆 Personal Tier {ctx.tier} {name} unlocked: {opened} more recipes are now within reach.'
    if ctx.tier < NEWCOMER_TIER and provider == 'discord':
        text += '\n\nNEXT STEP\n' + next_step(db, p, provider, ctx)
    return text


# ---------------------------------------------------------------- fetch missing ingredients

def _gather_attempts(key, short):
    per = s.GATHER[key]['amount']
    if key in cp.RARE:
        return math.ceil(3 * short / MINING_SUCCESS_GUESS)
    if s.GATHER[key]['branch'] == 'ore_mining':
        return math.ceil(short / (per * MINING_SUCCESS_GUESS))
    return math.ceil(short / per)


def fetch_routes(ctx, e, batches=1):
    """Every missing ingredient for `batches` batches with its best way to get it."""
    from . import task_queue
    from .game.players import resource_name
    from .game.rules import SEED_INDUSTRIES
    ores = task_queue.ores()
    rows = []
    for key, n in e.inputs.items():
        short = n * batches - ctx.have(key)
        if short <= 0:
            continue
        route = {'key': key, 'name': resource_name(key), 'short': short, 'kind': 'none', 'price': 0}
        listing = SEED_INDUSTRIES.get(key) or {}
        if listing.get('buy'):
            route['price'] = listing['buy']
        if key in s.GATHER:
            attempts = _gather_attempts(key, short)
            route.update(kind='queue', task=('mine:' if key in ores else 'gather:') + key,
                         attempts=min(10, attempts), capped=attempts > 10)
        else:
            source = next((x for x in wb.index() if x.output == key and ctx.status(x).code != 'locked'), None)
            if source is not None:
                route.update(kind='recipe', recipe=source.id, recipe_name=source.name,
                             batches=math.ceil(short / max(1, ctx.batch_size(source))))
            elif route['price']:
                route['kind'] = 'buy'
        rows.append(route)
    return rows


def fetch_plan(ctx, e, batches=1):
    """(text, start) where start is the queue to begin, with the craft chained after it."""
    from . import task_queue
    from .game.cooldowns_materials import material_source
    routes = fetch_routes(ctx, e, batches)
    discord = ctx.provider == 'discord'
    status = ctx.status(e)
    head = f'🧺 FETCH INGREDIENTS · {e.name} ×{batches} batch' + ('es' if batches > 1 else '')
    if status.code in {'locked', 'owned'}:
        return f'{head}\n{status.detail} Fetching ingredients will not unlock it.', None
    if not routes:
        return f'{head}\n✅ You already have every ingredient. Craft it or queue it from the recipe.', None
    lines = [head, '']
    for r in routes:
        if r['kind'] == 'queue':
            verb = 'Mine' if r['task'].startswith('mine:') else 'Gather'
            line = f"• {r['name']}: need {r['short']} more → {verb} ×{r['attempts']}"
            if r['capped']:
                line += ' (10 is the queue maximum; fetch again afterwards)'
        elif r['kind'] == 'recipe':
            line = f"• {r['name']}: need {r['short']} more → craft {r['recipe_name']} ×{r['batches']}"
        elif r['kind'] == 'buy':
            line = f"• {r['name']}: need {r['short']} more → buy from Seed Industries"
        else:
            line = f"• {r['name']}: need {r['short']} more → {material_source(r['key'], ctx.provider)}"
        if r['price']:
            line += f" · or buy for {r['price'] * r['short']} SC"
        lines.append(line)
    first = next((r for r in routes if r['kind'] == 'queue'), None)
    start = None
    if first:
        rest = [r for r in routes if r is not first]
        chain = not rest and not first['capped']
        start = {'task': first['task'], 'count': first['attempts'],
                 'then': {'task': 'make:' + e.id, 'count': batches} if chain else None}
        label = task_queue.choices().get(first['task'], first['task'])
        lines += ['', 'PLAN', f"1. {label} ×{first['attempts']}"]
        if chain:
            lines.append(f'2. Then make {e.name} ×{batches} automatically (queued next).')
        else:
            lines.append('Then fetch the remaining ingredients above before crafting.')
        if first['task'].startswith('mine:'):
            lines.append('Mining can fail (failures give Stone Dust), so the plan includes spare attempts.')
    cost = sum(r['price'] * r['short'] for r in routes if r['price'])
    if cost and all(r['price'] for r in routes):
        lines += ['', f'Or buy everything missing now for {cost} SC (you have {ctx.p.sc if ctx.p else 0} SC).']
    if not discord:
        text = ' | '.join(x.lstrip('• ') for x in lines if x)
        if start:
            text += f' | !fetchgo {e.name}' + (f' {batches}' if batches > 1 else '') + ' starts it.'
        return text, start
    return '\n'.join(lines), start


def buy_missing(db, p, e, batches, provider='discord'):
    """Buy every missing, purchasable ingredient for `batches` batches."""
    ctx = wb.Context(db, p, provider)
    routes = [r for r in fetch_routes(ctx, e, batches) if r['price']]
    if not routes:
        return 'Nothing missing can be bought from Seed Industries. Nothing spent.'
    lines = []
    db.flush()
    with acting_as(p.channel_id, p.twitch_uid):
        for r in routes:
            left = r['short']
            while left > 0:
                amount = min(25, left)
                lines.append(runtime.seed_industries(p.channel_id, p.twitch_uid, p.display_name, 'buy', r['key'], amount,
                                               provider).body.decode())
                left -= amount
                if 'bought' not in lines[-1]:
                    left = 0
    db.expire_all()
    return '\n'.join(lines)


# ---------------------------------------------------------------- bulk selling

def sell_price(key):
    """Seed Industries' price for one today, including daily demand."""
    from .game.players import sale_price
    return sale_price(key)


def protected_items(db, p):
    """Ingredients of favourites and of the current or next queued recipe are never cleared out."""
    from . import task_queue
    keep = set()
    for e in favorite_entries(db, p):
        keep |= set(e.inputs)
    tq = task_queue
    row = db.get(tq.TaskQueue, (p.channel_id, p.twitch_uid))
    tasks = [row.task] if row is not None and row.state in tq.ACTIVE else []
    tasks.append(next_task(db, p.channel_id, p.twitch_uid)[0])
    for task in tasks:
        if task and task.startswith('make:'):
            e = wb.entry(task[5:])
            if e is not None:
                keep |= set(e.inputs)
    return keep


def sell_all(db, p, key, provider):
    """Sell a whole stack, except what the item's keep level keeps (keep_levels.keep_for)."""
    from . import item_identity
    from .game.cooldowns_materials import material_amount, material_change
    from .game.players import resource_name
    from . import keep_levels
    key = item_identity.canonical(key)
    price = sell_price(key)
    name = resource_name(key)
    if not price:
        return f'🏭 Seed Industries does not buy {name}. Nothing sold.'
    owned = material_amount(db, p, key)
    if owned <= 0:
        return f'🏭 You have no {name}. Nothing sold.'
    keep = keep_levels.keep_for(db, p, key)
    count = max(0, owned - keep)
    if count <= 0:
        return f'🏭 Nothing to sell: you have {owned} {name} and your keep level keeps {keep}. Selling a chosen amount still works.'
    total = price * count
    material_change(db, p, key, -count)
    p.sc += total
    xp = max(1, count // 3)
    banked = runtime.gain_skill(p, 'commerce', xp)
    from . import extras
    extras.remember_sale(db, p, {key: count}, total, banked)
    note = ''
    users = [e.name for e in favorite_entries(db, p) if key in e.inputs]
    if users:
        note = f' Note: your favourite {users[0]} uses {name}.'
    db.commit()
    sold = f'{count} {name}' if keep else f'all {owned} {name}'
    kept = f', keeping {keep} (your keep level)' if keep else ''
    return f'🏭 {p.display_name} sold {sold} to Seed Industries for {total} SC ({price} each){kept}. Balance: {p.sc} SC. +{xp} Commerce XP.{note}'


def clearout_plan(db, p):
    """(key, amount, price) to sell: Materials & Ores beyond the keep level, or CLEAROUT_RESERVE where none is set."""
    from .game.players import resource_name
    from . import keep_levels
    keep = protected_items(db, p)
    rows = []
    for key, qty in sorted(s.stock(db, p).items(), key=lambda kv: resource_name(kv[0])):
        if key not in s.ACTIVE or s.DISPLAY_CATEGORY.get(key) != 'materials' or key in keep:
            continue
        price = sell_price(key)
        if not price:
            continue
        reserve = keep_levels.keep_for(db, p, key, CLEAROUT_RESERVE)
        if qty > reserve:
            rows.append((key, qty - reserve, price))
    return rows


def clearout(db, p, provider, confirm=False):
    from .game.cooldowns_materials import material_change
    from .game.players import resource_name
    from . import keep_levels
    rows = clearout_plan(db, p)
    total = sum(n * price for _, n, price in rows)
    rule = (f'Clear-out sells Materials & Ores beyond {CLEAROUT_RESERVE} of each, or beyond your keep level where you set one. '
            'It never sells ingredients of your favourites or of your current or next queued recipe.')
    if not rows:
        return '🧹 Nothing to clear out. ' + rule
    if not confirm:
        if provider != 'discord':
            items = ', '.join(f'{resource_name(k)} ×{n}' for k, n, _ in rows[:8]) + (' …' if len(rows) > 8 else '')
            return (f'🧹 Clear-out would sell {items} for {total} SC. !clearout confirm to sell. '
                    f'Keeps {CLEAROUT_RESERVE} of each (or your keep level); favourites protected.')
        lines = [f'🧹 CLEAR-OUT PREVIEW · {total} SC', rule, '', 'WOULD SELL']
        for k, n, price in rows[:20]:
            kept = keep_levels.keep_for(db, p, k, None)
            lines.append(f'• {resource_name(k)} ×{n} → {n * price} SC ({price} each)' +
                         (f' · keeps {kept} (your keep level)' if kept is not None else ''))
        if len(rows) > 20:
            lines.append(f'• …and {len(rows) - 20} more item types')
        lines += ['', 'Nothing has been sold yet. Press Sell to confirm.']
        return '\n'.join(lines)
    sold = []
    earned = 0
    for key, n, price in rows:
        material_change(db, p, key, -n)
        earned += n * price
        sold.append(f'{resource_name(key)} ×{n}')
    p.sc += earned
    xp = max(1, sum(n for _, n, _ in rows) // 3)
    banked = runtime.gain_skill(p, 'commerce', xp)
    from . import extras
    extras.remember_sale(db, p, {key: n for key, n, _ in rows}, earned, banked)
    db.commit()
    text = f'🧹 Cleared out {len(rows)} item types for {earned} SC. Balance: {p.sc} SC. +{xp} Commerce XP.'
    if provider == 'discord':
        return text + '\n\nSOLD\n' + '\n'.join('• ' + x for x in sold) + (f'\n\nKept {CLEAROUT_RESERVE} of each (or your keep level) '
                                                                           'and every favourite or queued ingredient.')
    return text


# ---------------------------------------------------------------- inventory search

def _inventory_rows(db, p):
    stock = dict(s.stock(db, p))
    rows = {k: n for k, n in stock.items() if n > 0 and k in s.ACTIVE}
    if getattr(p, 'cargo', 0):
        rows['cargo'] = p.cargo
    return rows


def parse_inventory_text(text):
    """Twitch free text: '!inv ore value 2' -> search, sort, show, page."""
    search, sort, show, page = [], 'quantity', 'all', 1
    for word in str(text or '').split():
        low = word.casefold()
        if low in INVENTORY_SORTS:
            sort = low
        elif low in INVENTORY_SHOWS or low in {'favs', 'favourites'}:
            show = 'favorites' if low in {'favs', 'favourites'} else low
        elif low.isdigit():
            page = int(low)
        else:
            search.append(word)
    return ' '.join(search), sort, show, page


def inventory_text(db, p, provider, search='', sort='quantity', show='all', page=1):
    from .game.players import resource_name
    sort = sort if sort in INVENTORY_SORTS else 'quantity'
    show = show if show in INVENTORY_SHOWS else 'all'
    rows = _inventory_rows(db, p)
    q = ' '.join(str(search or '').casefold().replace('_', ' ').split())

    def category(k):
        return s.DISPLAY_INFO[s.DISPLAY_CATEGORY[k]][1] if k in s.DISPLAY_CATEGORY else 'Logistics'

    if q:
        rows = {k: n for k, n in rows.items() if q in resource_name(k).casefold() or q in category(k).casefold() or q == k}
    if show in {'ready', 'favorites'}:
        ctx = wb.Context(db, p, provider)
        pool = favorite_entries(db, p) if show == 'favorites' else [e for e in wb.index() if ctx.status(e).code == 'ready']
        used = {k for e in pool for k in e.inputs}
        rows = {k: n for k, n in rows.items() if k in used}
    elif show == 'sellable':
        rows = {k: n for k, n in rows.items() if sell_price(k)}
    key = {'quantity': lambda kv: (-kv[1], resource_name(kv[0])),
           'name': lambda kv: resource_name(kv[0]).casefold(),
           'value': lambda kv: (-sell_price(kv[0]) * kv[1], resource_name(kv[0])),
           'category': lambda kv: (category(kv[0]), resource_name(kv[0]))}[sort]
    ordered = sorted(rows.items(), key=key)
    worth = sum(sell_price(k) * n for k, n in ordered)
    size = INVENTORY_PAGE if provider == 'discord' else 6
    page, pages, start, end = wb.page_bounds(len(ordered), page, size)
    shown = ordered[start:end]
    filters = ([f'"{search}"'] if q else []) + ([{'ready': 'used in recipes ready now', 'favorites': 'used by favourites', 'sellable': 'sellable'}[show]] if show != 'all' else [])
    if provider != 'discord':
        items = ', '.join(f'{resource_name(k)} {n}' for k, n in shown) or 'no matching items'
        more = f' | !inv {search + " " if search else ""}{page + 1} for more' if page < pages else ''
        return f'🎒 {p.display_name} {page}/{pages}' + (f' ({", ".join(filters)})' if filters else '') + f': {items} | worth {worth} SC{more}'
    lines = [f'🎒 INVENTORY · Page {page}/{pages} · sorted by {sort}' + (' · ' + ' · '.join(filters) if filters else ''),
             f'{len(ordered)} item types · {sum(n for _, n in ordered)} items · sells for {worth} SC in total · {p.sc} SC on hand', '']
    for k, n in shown:
        price = sell_price(k)
        uses = len(s.USED_BY.get(k, ()))
        parts = [category(k)] + ([f'sells {price} SC each'] if price else []) + ([f'used in {uses} recipes'] if uses else [])
        lines.append(f'• {resource_name(k)} ×{n} — ' + ' · '.join(parts))
    if not shown:
        lines.append('• No matching items.')
    lines += ['', 'Search, sort (quantity, name, value, category) and filter with /inventory options. '
              '/seedindustries action:Sell all sells one item; action:Clear out previews selling surplus materials.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- fuzzy names

def _norm(text):
    return ' '.join(str(text or '').casefold().replace('_', ' ').split())


def match(query, names):
    """names: {normalized: value}. Returns (value or None, suggestion names)."""
    q = _norm(query)
    if not q:
        return None, []
    if q in names:
        return names[q], []
    starts = sorted(n for n in names if n.startswith(q))
    if len(starts) == 1:
        return names[starts[0]], []
    contains = sorted(n for n in names if q in n)
    if len(contains) == 1:
        return names[contains[0]], []
    close = difflib.get_close_matches(q, list(names), n=3, cutoff=0.7)
    if close:
        # One clearly closest name wins (e.g. "campfir" -> Campfire, not Campfire Pie).
        best = difflib.SequenceMatcher(None, q, close[0]).ratio()
        second = difflib.SequenceMatcher(None, q, close[1]).ratio() if len(close) > 1 else 0
        if best >= 0.85 and best - second >= 0.1:
            return names[close[0]], []
    return None, (starts or contains or close)[:3]


_RECIPE_NAMES = None
_ITEM_NAMES = None


def recipe_names():
    global _RECIPE_NAMES
    if _RECIPE_NAMES is None:
        _RECIPE_NAMES = {}
        for e in wb.index():
            _RECIPE_NAMES.setdefault(_norm(e.name), e.name)
    return _RECIPE_NAMES


def item_names():
    global _ITEM_NAMES
    if _ITEM_NAMES is None:
        _ITEM_NAMES = {}
        for k in sorted(s.ACTIVE):
            _ITEM_NAMES.setdefault(_norm(s.ITEMS[k]['name']), k)
    return _ITEM_NAMES


def fuzzy_recipe(db, p, text, category=''):
    """(entry, note, suggestions) for a misspelled or partial recipe name."""
    name, suggestions = match(text, recipe_names())
    if name is None:
        return None, '', [recipe_names().get(x, x) for x in suggestions]
    e = wb.resolve(db, p, name, category) or wb.resolve(db, p, name)
    return e, (f'🔎 “{text}” matched {e.name}.' if e else ''), []


def fuzzy_item(text, allowed=None):
    """(key, suggestions) for an item name; `allowed` limits the candidates."""
    names = item_names()
    if allowed is not None:
        names = {n: k for n, k in names.items() if k in allowed}
    key, suggestions = match(text, names)
    return key, [s.ITEMS[names[x]]['name'] for x in suggestions if x in names]


def did_you_mean(suggestions):
    return (' Did you mean: ' + ', '.join(suggestions) + '?') if suggestions else ''


# ---------------------------------------------------------------- status dashboard

def queue_summary(db, p, provider):
    """(line, row) describing the current or last queue, its pace and what follows."""
    from . import task_queue
    tq = task_queue
    row = db.get(tq.TaskQueue, (p.channel_id, p.twitch_uid))
    prefix = _prefix(provider)
    following = next_label(db, p.channel_id, p.twitch_uid)
    if row is None:
        line = f'No queue yet. {prefix}mine, {prefix}gather or {prefix}make can queue up to 10 attempts.'
    else:
        label = tq.choices().get(row.task, row.task)
        done = row.total - row.remaining
        if row.state == 'running':
            _, _, interval = tq.specification(row.task) if row.task in tq.choices() else (0, 0, tq.ATTEMPT_SECONDS)
            left = row.remaining * interval
            finish = f'finishes <t:{int(runtime.now().timestamp() + left)}:R>' if provider == 'discord' else f'about {needs.duration_text(left)} left'
            line = f'▶️ Running: {label} · {done}/{row.total} done · {finish}'
        elif row.state == 'paused':
            reason = row.result.splitlines()[0] if row.result else 'requirements not met'
            line = f'⏸️ Paused: {label} · {done}/{row.total} done · {reason}'
        else:
            state = {'completed': 'Completed', 'cancelled': 'Cancelled', 'error': 'Stopped'}.get(row.state, row.state.title())
            repeat = 'Repeat it with the button below.' if provider == 'discord' else 'Repeat: !queuerepeat'
            line = f'✔️ Last queue {state.lower()}: {label} ×{row.total}. {repeat}'
    if following:
        line += f'\n⏭️ Next: {following}' if provider == 'discord' else f' → next {following}'
    return line, row


def _cooldowns(db, p, provider, limit=3):
    from .game.cooldowns_materials import action_wait, cooldown_label
    rows = db.execute(select(Cooldown).where(Cooldown.channel_id == p.channel_id, Cooldown.canonical_uid == p.twitch_uid)).scalars().all()
    active = sorted((action_wait(db, p, r.action), r.action) for r in rows if r.action != 'sleep' and action_wait(db, p, r.action))
    if provider == 'discord':
        return [f'{cooldown_label(a, provider)} ready <t:{int(runtime.now().timestamp() + w)}:R>' for w, a in active[:limit]]
    return [f'{cooldown_label(a, provider)} {needs.duration_text(w)}' for w, a in active[:limit]]


def status_text(db, p, provider='discord'):
    from . import autonomy, extras
    from .game.life import life_state
    from .game.world import comfort_status_line, sleep_status
    life = life_state(db, p)
    ctx = wb.Context(db, p, provider)
    blocked = needs.blocked_needs(life)
    queue_line, _ = queue_summary(db, p, provider)
    favs = favorite_entries(db, p)
    ready = [e for e in favs if ctx.status(e).code == 'ready']
    ready += [e for e in wb.start_here(ctx, 6) if e not in ready]
    ready = ready[:3]
    row = prefs(db, p.channel_id, p.twitch_uid)
    mode = alert_mode(db, p.channel_id, p.twitch_uid)
    auto = bool(row and row.autorecover)
    sleep = sleep_status(db, p, provider)
    if provider != 'discord':
        needs_part = f'E{life.energy} N{life.nutrition} S{life.social} C{life.comfort}'
        if blocked:
            needs_part += ' ⛔ ' + ', '.join(f'{label} {value}/{minimum}' for _, label, value, minimum in blocked) + ' → !recover'
        parts = [f'📊 {p.display_name}', needs_part, 'Queue: ' + queue_line.replace('\n', ' '), 'Sleep ' + sleep.split(' ', 1)[1].strip('()')]
        cds = _cooldowns(db, p, provider, 2)
        if cds:
            parts.append('CD: ' + ', '.join(cds))
        goal = extras.goal_entry(db, p)
        if goal is not None:
            parts.append(f'🎯 {goal.name}: ' + extras.next_step(db, p, provider)[0])
        if ready:
            parts.append('Ready: ' + ', '.join(('⭐' if e in favs else '') + e.name for e in ready))
        else:
            parts.append('Next: ' + next_step(db, p, provider, ctx))
        return ' | '.join(parts)
    from . import quiet_hours
    quiet = quiet_hours.short(db, p.channel_id, p.twitch_uid, runtime.now()) if mode in {'dm', 'quiet'} else ''
    quiet = f' · {quiet}' if quiet else ''
    lines = [f'📊 STATUS — {p.display_name}', '', 'NEEDS',
             f'⚡ Energy {life.energy} · 🍲 Nutrition {life.nutrition} · 🤝 Social {life.social} · 🏠 Comfort {life.comfort} · ✨ Morale {life.morale}']
    if blocked:
        lines.append('⛔ Work is blocked:')
        lines += ['• ' + need_line(db, p, life, *b) for b in blocked]
    else:
        lines.append('✅ Ready for work.' + (' ' + comfort_status_line(life) if life.comfort < needs.COMFORT_SLOW else ''))
    lines.append(f'🛏️ Sleep: {sleep}')
    lines += ['', 'SEEDLING', autonomy.status_line(db, p)]
    lines += ['', 'QUEUE', queue_line]
    cds = _cooldowns(db, p, provider)
    if cds:
        lines += ['', 'COOLDOWNS', ' · '.join(cds)]
    lines += ['', 'READY TO CRAFT']
    lines += [f"{'⭐' if e in favs else '✅'} {e.name} ×{ctx.batch_size(e)} — {wb.station_label(e, ctx)}" for e in ready] or ['• Nothing is ready yet.']
    goal = extras.goal_entry(db, p)
    if goal is not None:
        lines += ['', f'🎯 GOAL — {goal.name}', extras.next_step(db, p, provider)[0] + ' · /menu → Craft → My goal']
    lines += ['', 'NEXT STEP', next_step(db, p, provider, ctx),
              '', 'SETTINGS', f'Alerts: {ALERT_LABELS[mode]}{quiet} · Auto-recover: {"on" if auto else "off"} · Favourites: {len(favs)}/{MAX_FAVORITES} · /settings changes these.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- settings

def settings_text(db, p, provider, alerts='', autorecover='', text='', popups=''):
    words = str(text or '').casefold().split()
    if words:
        head, value = words[0], (words[1] if len(words) > 1 else '')
        if head in {'alerts', 'alert', 'pings', 'ping'}:
            alerts = value
        elif head in {'autorecover', 'auto', 'recover', 'auto-recover'}:
            autorecover = value
        else:
            return '⚙️ Settings: !settings alerts <mention|quiet|off> · !settings autorecover <on|off>. Nothing changed.'
    alerts = str(alerts or '').strip().casefold()
    autorecover = str(autorecover or '').strip().casefold()
    changed = []
    if alerts:
        if alerts not in ALERT_MODES:
            return '⚙️ Alerts must be mention, dm, private, quiet or off. Nothing changed.'
        if alerts in {'dm', 'private'} and provider != 'discord':
            return '⚙️ Direct-message and private alerts (and quiet hours for DMs) are Discord options. On Twitch choose mention, quiet or off. Nothing changed.'
        row = prefs(db, p.channel_id, p.twitch_uid, create=True)
        row.alerts = alerts
        changed.append(f'Alerts: {ALERT_LABELS[alerts]} — {ALERT_MODES[alerts]}.')
    if autorecover:
        if autorecover not in {'on', 'off', 'true', 'false', 'yes', 'no', '1', '0'}:
            return '⚙️ Auto-recover must be on or off. Nothing changed.'
        row = prefs(db, p.channel_id, p.twitch_uid, create=True)
        row.autorecover = int(autorecover in {'on', 'true', 'yes', '1'})
        changed.append('Auto-recover: ' + ('on — paused queues use /relax, /games, your cheapest food, comfort items and /sleep (when ready), then resume.'
                                            if row.autorecover else 'off — queues pause until you recover.'))
    from . import inbox
    popups = str(popups or '').strip().casefold()
    if popups:
        if popups not in inbox.POPUP_MODES:
            return '⚙️ Popups must be important, all or off. Nothing changed.'
        inbox.prefs(db, p.channel_id, p.twitch_uid, create=True).popups = popups
        changed.append(f'Popups: {popups} — {inbox.POPUP_MODES[popups]}.')
    db.commit()
    mode = alert_mode(db, p.channel_id, p.twitch_uid)
    auto = autorecover_on(db, p.channel_id, p.twitch_uid)
    popup = inbox.popup_mode(db, p.channel_id, p.twitch_uid)
    if provider != 'discord':
        current = f'Alerts {mode} · Auto-recover {"on" if auto else "off"}'
        return ('⚙️ ' + ' '.join(changed) + ' | ' if changed else '⚙️ ') + current + ' | !settings alerts <mention|quiet|off> · !settings autorecover <on|off>'
    lines = ['⚙️ SETTINGS'] + (['', 'CHANGED'] + ['• ' + x for x in changed] if changed else [])
    from . import quiet_hours
    lines += ['', 'CURRENT', f'• Alerts: {ALERT_LABELS[mode]} — {ALERT_MODES[mode]}',
              quiet_hours.settings_line(db, p.channel_id, p.twitch_uid, mode, runtime.now()),
              f'• Auto-recover: {"on" if auto else "off"} — when a queue pauses for low needs it tries relax, games, your cheapest food, a comfort item or sleep first.',
              f'• Popups: {popup} — {inbox.POPUP_MODES[popup]}. Popups are private ("only you can see this") and appear with your next command or button.',
              '', 'Change with /settings alerts:<choice> autorecover:<On/Off> popups:<choice>. Quiet hours: /menu → You → Settings.']
    return '\n'.join(lines)
