"""Keep levels: how many of an item a citizen always keeps.

A keep level ("keep 30 Iron Plate") is a floor for every bulk or automatic sale: Sell all,
clear-out, auto-sell after a queue and the "sell all" steps of plans and routines never sell
below it (`keep_for` is the one place that says how many are kept). Selling a chosen amount is
never limited, and undo works as before.

Restock lists every item below its level with the best way back up (the routes fetching
ingredients uses: a gathering or mining queue, a craft queue or a Seed Industries purchase) and
starts it through the ordinary queue, craft queue or purchase, so every gate, cost, cooldown and
the one-queue rule still apply. It only starts work that can progress now: a missing ingredient,
a locked recipe or workstation, or a rare ore without the Harvesting level is shown with the
screen that fixes it, and nothing starts (low needs and cooldowns are fine: a queue waits them
out). One additive table holds the levels, at most 25 per citizen.
"""
import re
from types import SimpleNamespace
from sqlalchemy import Column, String, Integer, select
from .db import Base
from . import seed_content as s, workbench as wb, crafting_progression as cp

MAX_LEVELS = 25
MAX_AMOUNT = 9999
QUICK = (10, 25, 50, 100)                      # Discord's amount buttons
REMOVE = {'0', 'off', 'clear', 'remove', 'none', 'delete'}
NUMBER = re.compile(r'[-+]?\d+(?:[.,]\d+)?')
AMOUNT_RULE = 'The amount must be a whole number from 1 to 9999 (0 removes the keep level). Nothing changed.'


class KeepLevel(Base):
    """One row per kept item; a missing row means no keep level."""
    __tablename__ = 'player_keep_levels_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    item_key = Column(String(64), primary_key=True)
    amount = Column(Integer, nullable=False)


def install(m):
    KeepLevel.__table__.create(m.engine, checkfirst=True)


def _rows(db, channel, uid):
    return list(db.scalars(select(KeepLevel).where(KeepLevel.channel_id == channel, KeepLevel.canonical_uid == uid)
                           .order_by(KeepLevel.item_key)))


def levels(db, channel, uid):
    """{item key: amount kept}."""
    return {r.item_key: r.amount for r in _rows(db, channel, uid)}


def merge(db, channel, source, target):
    """Account linking: the target's keep levels win; the source's other items move over while there is room."""
    moving = _rows(db, channel, source)
    if not moving:
        return
    have = {r.item_key for r in _rows(db, channel, target)}
    for row in moving:
        if row.item_key in have or len(have) >= MAX_LEVELS:
            db.delete(row)
        else:
            row.canonical_uid = target
            have.add(row.item_key)


# ---------------------------------------------------------------- the rule every bulk sale follows

def keep_for(m, db, p, key, default=0):
    """How many of `key` bulk and automatic selling leaves: the citizen's keep level, else `default`."""
    row = db.get(KeepLevel, (p.channel_id, p.twitch_uid, m.item_identity.canonical(key)))
    return row.amount if row is not None else default


def sellable(m, db, p, key, default=0):
    """How many of `key` Sell all, auto-sell and plan sell steps may sell: everything owned beyond what is kept."""
    return max(0, m.material_amount(db, p, key) - keep_for(m, db, p, key, default))


# ---------------------------------------------------------------- setting levels

def _not_catalog(m, key):
    """Why `key` (canonical) cannot have a keep level, or ''."""
    if not key:
        return '🛡️ Choose an item first. Nothing changed.'
    if key not in s.ACTIVE:
        return f'🛡️ {m.resource_name(key)} is not a catalog item, so it cannot have a keep level. Nothing changed.'
    return ''


def set_level(m, db, p, key, amount):
    """Set (1–9999), change or clear (0) one keep level. Returns the message; a refusal changes nothing."""
    key = m.item_identity.canonical(str(key or '').strip())
    name = m.resource_name(key)
    problem = _not_catalog(m, key)
    if problem:
        return problem
    try:
        amount = int(str(amount).strip())
    except (TypeError, ValueError):
        return '🛡️ ' + AMOUNT_RULE
    if not 0 <= amount <= MAX_AMOUNT:
        return '🛡️ ' + AMOUNT_RULE
    row = db.get(KeepLevel, (p.channel_id, p.twitch_uid, key))
    if amount == 0:
        if row is None:
            return f'🛡️ {name} has no keep level. Nothing changed.'
        db.delete(row)
        db.flush()
        return f'🛡️ Keep level removed: Sell all and clear-out can sell every {name} again.'
    have = m.material_amount(db, p, key)
    state = f'you have {have}' + (f', {amount - have} short' if have < amount else '')
    if row is None:
        if len(_rows(db, p.channel_id, p.twitch_uid)) >= MAX_LEVELS:
            return f'🛡️ You already have {MAX_LEVELS} keep levels. Remove one before adding {name}. Nothing changed.'
        db.add(KeepLevel(channel_id=p.channel_id, canonical_uid=p.twitch_uid, item_key=key, amount=amount))
        db.flush()
        return f'🛡️ Keep level set: always keep {amount} {name} ({state}).'
    if row.amount == amount:
        return f'🛡️ You already keep {amount} {name}. Nothing changed.'
    old, row.amount = row.amount, amount
    return f'🛡️ Keep level changed: always keep {amount} {name} (was {old}; {state}).'


# ---------------------------------------------------------------- restock

def shortfalls(m, db, p, provider='discord'):
    """Every item below its keep level with its best route back up (qol.fetch_routes), in name order.

    Each row also says whether restocking can start now, using the game's own gates: r['blocked'] is ''
    or what stops it, r['view'] the custom_id parts of the screen that fixes it (Fetch missing, or the
    recipe with its Unlock), and r['count'] the attempts or batches a restock queues."""
    want = levels(db, p.channel_id, p.twitch_uid)
    if not want:
        return []
    ctx = wb.Context(m, db, p, provider)
    rows = m.qol.fetch_routes(ctx, SimpleNamespace(inputs=want), 1)
    for r in rows:
        r.update(have=ctx.have(r['key']), keep=want[r['key']], blocked='', fix='', view=None, more='', count=r.get('attempts', 0))
        if r['kind'] == 'queue' and r['key'] in cp.RARE and ctx.harvesting < cp.RARE_LEVEL:
            r['blocked'] = f'🔒 rare ores require Harvesting Lv.{cp.RARE_LEVEL} (you are Lv {ctx.harvesting})'
        elif r['kind'] == 'recipe':
            e = wb.entry(m, r['recipe'])
            status = ctx.status(e)
            r['count'] = min(10, r['batches'])
            if status.code == 'missing':
                r.update(blocked=f'{status.emoji} {status.short}', fix='fetch', view=('fm', e.id, r['count']))
            elif status.code != 'ready':
                r.update(blocked=f'{status.emoji} {status.short}', fix='unlock' if status.code == 'station' else 'recipe',
                         view=('wr', e.id, e.category, 1, ''), detail=status.detail)
            else:
                # Only the batches today's ingredients cover (needs recover while the queue waits).
                allowed, short_of = m.extras.max_attempts(m, db, p, 'make:' + e.id, with_needs=False)
                if allowed <= 0:
                    r.update(blocked='🛑 this recipe cannot be queued', fix='recipe', view=('wr', e.id, e.category, 1, ''))
                elif allowed < r['count']:
                    r.update(count=allowed, more=short_of)
    return sorted(rows, key=lambda r: r['name'].casefold())


FIXES = {'fetch': 'fetch the ingredients first', 'unlock': 'open the recipe to unlock', 'recipe': 'open the recipe'}


def route_text(m, r, provider='discord'):
    """What restocking one short item does, and what blocks it."""
    if r['kind'] == 'queue':
        verb = 'Mine' if r['task'].startswith('mine:') else 'Gather'
        text = f"{verb} ×{r['attempts']}" + (' (10 is the queue maximum; restock again afterwards)' if r['capped'] else '')
    elif r['kind'] == 'recipe':
        text = f"craft {r['recipe_name']} ×{r['count']}"
        if r['more']:
            text += f" (ingredients cover {r['count']} of {min(10, r['batches'])} batches; the rest needs more {r['more']})"
        elif r['batches'] > 10:
            text += ' (10 is the queue maximum; restock again afterwards)'
    elif r['kind'] == 'buy':
        return f"buy {r['short']} for {r['price'] * r['short']} SC"
    else:
        return 'cannot be restocked automatically: ' + m.material_source(r['key'], provider).rstrip('.')
    if r['blocked']:
        fix = FIXES.get(r['fix'], '')
        if fix and provider != 'discord' and r['fix'] != 'fetch':
            fix = 'see !make ' + r['recipe_name']
        text += f" · {r['blocked']}" + (f' — {fix}' if fix else '')
    return text


def _pick(rows, key=''):
    """The row to restock: the one named, else the first that can start now, else the first (its reply explains)."""
    if key:
        return next((r for r in rows if r['key'] == key), None)
    return next((r for r in rows if r['kind'] != 'none' and not r['blocked']), rows[0] if rows else None)


def _not_short(m, db, p, key):
    """Why `key` (or nothing) needs no restock."""
    if not key:
        if not levels(db, p.channel_id, p.twitch_uid):
            return '🛡️ You have no keep levels yet, so there is nothing to restock.'
        return '✅ Everything is at or above its keep level. Nothing to restock.'
    name = m.resource_name(key)
    keep = keep_for(m, db, p, key)
    if not keep:
        return f'🛡️ {name} has no keep level. Set one first. Nothing changed.'
    return f'✅ You have {m.material_amount(db, p, key)} {name}, at or above your keep level of {keep}. Nothing to restock.'


def _blocked_reply(m, db, p, r, provider):
    """A restock that cannot start now: what blocks it and how to fix it. Nothing is started."""
    head = f"🛡️ Restock {r['name']} is blocked: {route_text(m, r, provider)}."
    tail = ' Nothing changed.'
    if r['fix'] == 'fetch':
        # The fetch-ingredients flow's own plan (and its !fetchgo hint on Twitch).
        plan, _ = m.qol.fetch_plan(wb.Context(m, db, p, provider), wb.entry(m, r['recipe']), r['count'])
        if provider == 'discord':
            return f'{head}\n\n{plan}\n\nNothing changed.'
        room = m.presentation.CHAT_LIMIT - len((head + ' ' + tail).encode())
        parts = plan.split(' | ')
        while len(parts) > 2 and len(' | '.join(parts).encode()) > room:
            parts.pop(-2)                                  # keep the plan's title and its closing !fetchgo hint
        return f"{head} {' | '.join(parts)}{tail}"
    if r.get('detail'):
        head += ' ' + r['detail'].rstrip('.') + '.'
    return head + tail


def restock_plan(m, db, p, provider='discord', key=''):
    """One line: what restocking the chosen (or first) short item would do."""
    key = m.item_identity.canonical(key) if key else ''
    rows = shortfalls(m, db, p, provider)
    r = _pick(rows, key)
    if r is None:
        return _not_short(m, db, p, key)
    text = f"🛡️ Restock {r['name']}: have {r['have']} / keep {r['keep']}, short {r['short']} → {route_text(m, r, provider)}."
    if r['kind'] == 'buy' and p.sc < r['price'] * r['short']:
        text += f" You have {p.sc} SC."
    elif r['kind'] != 'none' and not r['blocked']:
        text += ' !keep restock go starts it.' if provider != 'discord' else ' Press Restock to start it.'
    if len(rows) > 1:
        text += f' {len(rows)} items are below their keep level.'
    return text


def restock(m, channel, uid, name, provider='discord', key=''):
    """Start getting one item (the first short one that can start when none is named) back up to its keep level.

    Runs the ordinary queue, craft queue or Seed Industries purchase; never anything special, and nothing
    when a gate the queue cannot clear by itself blocks it."""
    tq = m.task_queue
    key = m.item_identity.canonical(key) if key else ''
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, name)[1]
        r = _pick(shortfalls(m, db, p, provider), key)
        if r is None:
            text = _not_short(m, db, p, key)
            db.commit()
            return text
        head = f"🛡️ Restocking {r['name']} (have {r['have']} / keep {r['keep']}): "
        if r['kind'] == 'none':
            db.commit()
            return f"🛡️ {r['name']} {route_text(m, r, provider)}. Nothing changed."
        if r['blocked']:
            text = _blocked_reply(m, db, p, r, provider)
            db.commit()
            return text
        if r['kind'] == 'buy':
            cost = r['price'] * r['short']
            if p.sc < cost:
                db.commit()
                return f"🪙 Restocking {r['short']} {r['name']} costs {cost} SC and you have {p.sc} SC: earn {cost - p.sc} more SC first. Nothing spent."
            text = m.qol.buy_missing(m, db, p, SimpleNamespace(inputs={r['key']: r['keep']}), 1, provider)
            db.commit()
            return head + text
        queue = db.get(tq.TaskQueue, (p.channel_id, p.twitch_uid))
        if queue is not None and queue.state in tq.ACTIVE:
            label = tq.choices(m).get(queue.task, queue.task)
            db.commit()
            return f"⏱️ Your queue is still running ({label}), so no restock was started. Restock {r['name']} when it finishes. Nothing changed."
        task = r['task'] if r['kind'] == 'queue' else 'make:' + r['recipe']
        if r['more']:
            head += f"ingredients cover {r['count']} of {min(10, r['batches'])} batches; the rest needs more {r['more']}. "
        count = r['count']
        db.commit()
    result = m.queued_tasks(channel, uid, name, 'start', task, str(count), provider).body.decode()
    return head + result


# ---------------------------------------------------------------- views

def mark(have, keep):
    return '✅' if have >= keep else '⚠️'


def screen_text(m, db, p, note=''):
    """The Discord keep-levels screen: every level with what you have, then what is short and how it comes back."""
    kept = levels(db, p.channel_id, p.twitch_uid)
    lines = [f'🛡️ KEEP LEVELS · {len(kept)}/{MAX_LEVELS}'] + ([note.strip()] if note else []) + [
        'Sell all, clear-out, auto-sell and "sell all" plan steps never sell below these amounts. Selling a chosen amount is not limited.', '']
    if not kept:
        lines.append('No keep levels yet. Pick an item below, for example keep 30 Iron Plate so selling never takes your last ones.')
    for key in sorted(kept, key=lambda k: m.resource_name(k).casefold()):
        have = m.material_amount(db, p, key)
        lines.append(f'{mark(have, kept[key])} {m.resource_name(key)} — have {have} / keep {kept[key]}')
    rows = shortfalls(m, db, p)
    if rows:
        lines += ['', 'RESTOCK'] + [f"• {r['name']}: short {r['short']} → {route_text(m, r)}" for r in rows]
    lines += ['', 'Choose an item below to add or change its keep level. Restock starts the work to get back up: '
                  'an ordinary queue, a craft queue or a Seed Industries purchase.']
    return '\n'.join(lines)


def item_text(m, db, p, key, note=''):
    """One item's keep level and how to change it."""
    name = m.resource_name(key)
    have = m.material_amount(db, p, key)
    keep = keep_for(m, db, p, key)
    lines = [f'🛡️ KEEP LEVEL · {name.upper()}'] + ([note.strip()] if note else [])
    lines.append(f'You have {have}. ' + (f'Keep level: {keep} {mark(have, keep)}' + (f' ({keep - have} short)' if have < keep else '')
                                         if keep else 'No keep level yet.'))
    lines += ['Sell all, clear-out, auto-sell and "sell all" plan steps leave at least this many. Choose an amount; Remove clears it.']
    r = next((r for r in shortfalls(m, db, p) if r['key'] == key), None)
    if r is not None:
        lines += ['', f"Restock: {route_text(m, r)}"]
    return '\n'.join(lines)


def list_text(m, db, p):
    """Twitch: every keep level and what is short, on one line."""
    kept = levels(db, p.channel_id, p.twitch_uid)
    if not kept:
        return '🛡️ No keep levels yet. !keep <item> <amount> keeps that many from Sell all, clear-out and auto-sell, e.g. !keep iron plate 30.'
    parts = []
    for key in sorted(kept, key=lambda k: m.resource_name(k).casefold()):
        have = m.material_amount(db, p, key)
        parts.append(f'{m.resource_name(key)} {have}/{kept[key]}{mark(have, kept[key])}')
    short = [r['name'] for r in shortfalls(m, db, p, 'twitch')]
    text = f'🛡️ Keep {len(kept)}/{MAX_LEVELS}: ' + ' · '.join(parts)
    text += f" | Short: {', '.join(short)} → !keep restock" if short else ' | Nothing is short.'
    return text + ' | !keep <item> <amount> · !keep <item> 0 clears'


def find_item(m, text):
    """(key, message) for a typed item name: aliases and exact names first, then close spellings."""
    key = s.find_item(text)
    if key in s.ACTIVE:
        return key, ''
    found, suggestions = m.qol.fuzzy_item(text)
    if found:
        return found, ''
    key = m.item_identity.canonical(key)
    if key == 'cargo' or key in m.QUALITY_RECIPES:
        return key, ''                              # a real item without a catalog identity: set_level explains
    return None, f'🛡️ No item called "{text[:40]}".' + m.qol.did_you_mean(suggestions) + ' Nothing changed.'


def command(m, channel, uid, name, provider, text=''):
    """!keep: blank lists; '<item> <amount>' sets (0 clears); 'restock [item]' plans; 'restock go [item]' starts it."""
    words = str(text or '').split()
    if words and words[0].casefold() == 'restock':
        rest = words[1:]
        go = bool(rest) and rest[0].casefold() in {'go', 'start'}
        wanted = ' '.join(rest[1:] if go else rest)
        key = ''
        if wanted:
            key, problem = find_item(m, wanted)
            if key is None:
                return problem
        if go:
            return restock(m, channel, uid, name, provider, key)
        with m.SessionLocal() as db:
            p = m.player(db, channel, provider, uid, name)[1]
            reply = restock_plan(m, db, p, provider, key)
            db.commit()
            return reply
    amount = None
    if words and words[-1].casefold() in REMOVE:
        amount, words = 0, words[:-1]
    elif words and NUMBER.fullmatch(words[-1]):
        amount, words = words[-1], words[:-1]
    elif len(words) > 1 and words[0].casefold() in REMOVE:
        amount, words = 0, words[1:]
    wanted = ' '.join(words)
    with m.SessionLocal() as db:
        p = m.player(db, channel, provider, uid, name)[1]
        if not wanted:
            if amount is not None:
                reply = '🛡️ Which item? !keep <item> <amount>, e.g. !keep iron plate 30. Nothing changed.'
            else:
                reply = list_text(m, db, p) if provider != 'discord' else screen_text(m, db, p)
            db.commit()
            return reply
        key, problem = find_item(m, wanted)
        if key is None:
            return problem
        if amount is None and _not_catalog(m, key):
            reply = _not_catalog(m, key)
        elif amount is None:
            keep, have = keep_for(m, db, p, key), m.material_amount(db, p, key)
            item = m.resource_name(key)
            reply = (f'🛡️ {item}: have {have} / keep {keep} {mark(have, keep)} | !keep {item} 0 removes it.' if keep else
                     f'🛡️ {item}: you have {have}, no keep level. !keep {item} <amount> sets one.')
        else:
            reply = set_level(m, db, p, key, amount)
        db.commit()
        return reply
