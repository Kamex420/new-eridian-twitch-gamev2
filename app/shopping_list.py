"""Shopping list: several recipes, each in the amount of its output a citizen wants to have, planned together.

A citizen lists up to 10 recipes, each with how many of its output they want to HAVE ("Iron Plate ×30,
Campfire ×1, Steel Frame ×2"). Progress is stateless: an entry is done (✅) once they own that many,
however the items arrived, and it stays on the list until removed (Clear done removes every done entry).
A recipe that leaves the catalog stays listed as no longer available, with Remove, and is not planned.

One plan covers the whole list (extras.list_plan: the goal's planner, with one shared pool). In list order
each entry's output comes from what you own first and then from that recipe itself, and an ingredient
several entries need counts once against what you own. The list shows what each entry still needs, the
raw materials across the whole list (need, have, missing, how to get each and what Seed Industries charges
for it) and the goal's ordered steps (extras.list_walkthrough); Fetch next does the first one once. Buy all
missing buys every missing material Seed Industries sells through the ordinary purchase (qol.buy_missing),
and only when you can afford all of it. Nothing here gathers, crafts or buys by itself, so every gate, cost,
cooldown and lock still applies. One additive table holds the lists.
"""
import math
import re
from datetime import timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import Column, String, Integer, DateTime, select
from .db import Base
from . import workbench as wb, crafting_progression as cp, extras
from . import runtime
from .db import SessionLocal

MAX_ENTRIES = 10
MAX_WANT = 999
STEPS_SHOWN = 4            # the screen is one card: entries, materials and the first steps
MATERIALS_SHOWN = 8
CARD_MARGIN = 150          # the card's section titles count against its overview limit too
REMOVE = {'0', 'off', 'remove', 'none', 'delete', 'clear'}
NUMBER = re.compile(r'[-+]?\d+(?:[.,]\d+)?')
AMOUNT_RULE = 'The amount must be a whole number from 1 to 999 (0 removes it). Nothing changed.'


class ShoppingEntry(Base):
    """One row per listed recipe: how many of its output the citizen wants to have."""
    __tablename__ = 'player_shopping_list_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    recipe_id = Column(String(64), primary_key=True)
    want = Column(Integer, nullable=False)
    added_at = Column(DateTime(timezone=True), nullable=False)


def install(m):
    ShoppingEntry.__table__.create(runtime.engine, checkfirst=True)


def _utc(when):
    return when if when is None or when.tzinfo else when.replace(tzinfo=timezone.utc)


def _rows(db, channel, uid):
    """A citizen's entries in list order (the order they were added)."""
    return list(db.scalars(select(ShoppingEntry).where(ShoppingEntry.channel_id == channel, ShoppingEntry.canonical_uid == uid)
                           .order_by(ShoppingEntry.added_at, ShoppingEntry.recipe_id)))


def entries(db, p):
    return _rows(db, p.channel_id, p.twitch_uid)


def merge(db, channel, source, target):
    """Account linking: the target's entries win; the source's other recipes move over after them while there is room."""
    moving = _rows(db, channel, source)
    if not moving:
        return
    kept = _rows(db, channel, target)
    listed = {r.recipe_id for r in kept}
    last = max((_utc(r.added_at) for r in kept), default=None)
    for row in moving:
        if row.recipe_id in listed or len(listed) >= MAX_ENTRIES:
            db.delete(row)
            continue
        row.canonical_uid = target
        listed.add(row.recipe_id)
        if last is not None:
            last = row.added_at = max(_utc(row.added_at), last + timedelta(microseconds=1))


# ---------------------------------------------------------------- changing the list

def _unique(e):
    """Bonus equipment is limited to one of each."""
    from .game.rules import UNIQUE_CORE_ITEMS, UNIQUE_QUALITY_ITEMS
    return e.kind == 'legacy' and (e.output in UNIQUE_CORE_ITEMS or e.output in UNIQUE_QUALITY_ITEMS)


def _amount(value):
    """None (no amount given), 0 (remove) or the whole number typed; ValueError when it is not one from 0 to 999."""
    text = str(value if value is not None else '').strip().casefold()
    if not text:
        return None
    if text in REMOVE:
        return 0
    want = int(text)
    if not 0 <= want <= MAX_WANT:
        raise ValueError(text)
    return want


def _batches(n):
    return f'{n} batch' + ('es' if n != 1 else '')


def set_entry(db, p, recipe_id, amount=None):
    """Add (no amount: one batch's output), change or remove (0) one recipe. Returns the message; a refusal changes nothing."""
    rows = entries(db, p)
    row = next((r for r in rows if r.recipe_id == recipe_id), None)
    e = wb.entry(recipe_id) if recipe_id else None
    try:
        want = _amount(amount)
    except ValueError:
        return '🛒 ' + AMOUNT_RULE
    name = e.name if e is not None else str(recipe_id or '')
    if want == 0:
        if row is None:
            return f'🛒 {name or "That recipe"} is not on your shopping list. Nothing changed.'
        db.delete(row)
        db.flush()
        return f'🛒 Removed {name} from your shopping list.'
    if e is None:
        return '🛒 That recipe is not available. Nothing changed.'
    ctx = wb.Context(db, p)
    per = max(1, ctx.batch_size(e))
    if want is None:
        if row is not None:
            return f'🛒 {e.name} is already on your shopping list: you want {row.want}. Give an amount to change it. Nothing changed.'
        want = min(MAX_WANT, per)
    if want > 1 and _unique(e):
        return f'🛒 {e.name} is bonus equipment, limited to one of each, so the amount must be 1. Nothing changed.'
    have = ctx.have(e.output)
    state = f'you have {have}' + (', done ✅' if have >= want else f'; {_batches(math.ceil((want - have) / per))} of {per}')
    if row is None:
        if len(rows) >= MAX_ENTRIES:
            return f'🛒 Your shopping list already has {MAX_ENTRIES} recipes. Remove one before adding {e.name}. Nothing changed.'
        now = runtime.now()
        last = max((_utc(r.added_at) for r in rows), default=None)
        if last is not None and now <= last:
            now = last + timedelta(microseconds=1)       # list order is the order recipes were added
        db.add(ShoppingEntry(channel_id=p.channel_id, canonical_uid=p.twitch_uid, recipe_id=e.id, want=want, added_at=now))
        db.flush()
        return f'🛒 Added to your shopping list: {want} {e.name} ({state}).'
    if row.want == want:
        return f'🛒 You already want {want} {e.name}. Nothing changed.'
    old, row.want = row.want, want
    db.flush()
    return f'🛒 Shopping list changed: want {want} {e.name} (was {old}; {state}).'


def clear(db, p, done_only=False):
    """Remove every entry, or only the done ones (unavailable recipes are never done)."""
    ctx = wb.Context(db, p)
    gone = 0
    for row in entries(db, p):
        e = wb.entry(row.recipe_id)
        if done_only and (e is None or ctx.have(e.output) < row.want):
            continue
        db.delete(row)
        gone += 1
    db.flush()
    if done_only:
        return f'🧹 Cleared {gone} done ' + ('entry' if gone == 1 else 'entries') + ' from your shopping list.' if gone else \
            '🧹 Nothing on your shopping list is done yet. Nothing changed.'
    return '✖️ Shopping list cleared.' if gone else '🛒 Your shopping list is already empty. Nothing changed.'


def find_recipe(db, p, text):
    """(recipe, note) for a typed name: exact names and ids first, then close spellings; (None, why) when none."""
    from . import qol
    text = str(text or '').strip()
    if not text:
        return None, '🛒 Which recipe? Type its name, e.g. Iron Plate. Nothing changed.'
    found = wb.resolve(db, p, text)
    if found is not None:
        return found, ''
    found, note, suggestions = qol.fuzzy_recipe(db, p, text)
    if found is not None:
        return found, note
    return None, f'🛒 No recipe called "{text[:40]}".' + qol.did_you_mean(suggestions) + ' Nothing changed.'


def listed_recipe(db, p, text):
    """The listed recipe a typed name means (its id or name; also one no longer in the catalog), else find_recipe's answer."""
    text = str(text or '').strip()
    rows = entries(db, p)
    for row in rows:
        e = wb.entry(row.recipe_id)
        if text.casefold() in {row.recipe_id.casefold()} | ({e.name.casefold()} if e else set()):
            return row.recipe_id, ''
    found, note = find_recipe(db, p, text)
    if found is None:
        return None, note
    twin = next((r.recipe_id for r in rows if (wb.entry(r.recipe_id) or SimpleNamespace(name='')).name == found.name), found.id)
    return twin, note


def add_typed(db, p, text, amount=None):
    """Add or change a recipe named in a form or chat; the note says what a close spelling matched."""
    found, note = find_recipe(db, p, text)
    if found is None:
        return note
    return (note + ' ' if note else '') + set_entry(db, p, found.id, amount)


def _split(db, p, words):
    """(recipe name, amount or None): a trailing number or 'off'/'remove' is the amount, unless the whole text names a
    recipe ("Table Lamp 2")."""
    text = ' '.join(words)
    if len(words) > 1 and (words[-1].casefold() in REMOVE or NUMBER.fullmatch(words[-1])) and wb.resolve(db, p, text) is None:
        return ' '.join(words[:-1]), words[-1]
    return text, None


# ---------------------------------------------------------------- the combined plan

def _state(ctx, item):
    """(mark, words) for an entry that is not done yet."""
    status = item.status
    if status.code == 'ready':
        return '🛠️', 'ready to craft'
    if status.code == 'station':
        _, machine = extras._machine(ctx, item.entry)
        if machine is not None:
            return '🔑', f'needs a {machine.name}: made in the steps'
    return status.emoji, status.short


def overview(db, p, provider='discord'):
    """Everything the list screens show: entries with progress, the raw materials across the list, the steps,
    and what buying the missing materials costs."""
    from . import qol
    from .game.players import resource_name
    ctx = wb.Context(db, p, provider)
    rows = [(r, wb.entry(r.recipe_id)) for r in entries(db, p)]
    wanted = [(e, r.want) for r, e in rows if e is not None]
    if wanted:
        steps, (_, raw, _, made, used) = extras.list_walkthrough(ctx, wanted)
    else:
        steps, raw, made, used = [], {}, [], {}
    batches = {e.id: n for e, _, n in made}
    items = []
    for r, e in rows:
        if e is None:
            items.append(SimpleNamespace(recipe_id=r.recipe_id, entry=None, name=r.recipe_id, want=r.want, have=0, done=False,
                                         batches=0, status=None, mark='❔', state='no longer available'))
            continue
        have = ctx.have(e.output)
        item = SimpleNamespace(recipe_id=r.recipe_id, entry=e, name=e.name, want=r.want, have=have, done=have >= r.want,
                               batches=batches.get(e.id, 0), status=ctx.status(e), mark='✅', state='done')
        if not item.done:
            item.mark, item.state = _state(ctx, item)
        items.append(item)
    routes = {r['key']: r for r in qol.fetch_routes(ctx, SimpleNamespace(inputs={k: ctx.have(k) + n for k, n in raw.items()}), 1)}
    materials = []
    for key in set(used) | set(raw):
        missing = raw.get(key, 0)
        route = routes.get(key)
        price = route['price'] if route else 0
        locked = key in cp.RARE and not ctx.rare_ok
        materials.append(SimpleNamespace(key=key, name=resource_name(key), need=used.get(key, 0) + missing, have=ctx.have(key),
                                         missing=missing, route=route, price=price, locked=locked,
                                         buyable=bool(missing and price and not locked), cost=price * missing))
    materials.sort(key=lambda x: (not x.missing, x.name.casefold()))
    buy = [x for x in materials if x.buyable]
    return SimpleNamespace(ctx=ctx, items=items, materials=materials, steps=steps, buy=buy, cost=sum(x.cost for x in buy),
                           unsold=[x for x in materials if x.missing and not x.buyable], sc=p.sc)


def route_text(x, provider='discord'):
    """How a missing material comes in, and what buying it costs."""
    from .game.cooldowns_materials import material_source
    r = x.route or {'kind': 'none'}
    if r['kind'] == 'queue':
        text = ('mine' if r['task'].startswith('mine:') else 'gather') + f" ×{r['attempts']}"
    elif r['kind'] == 'recipe':
        text = f"craft {r['recipe_name']} ×{r['batches']}"
    elif r['kind'] == 'buy':
        text = ''
    else:
        text = material_source(x.key, provider).split(';')[0].rstrip('.')
    if x.locked:
        text += f' · needs {cp.RARE_NEED}'
    if x.buyable:
        text += (' · or ' if text else '') + f'buy for {x.cost} SC'
    return text


def source(x, provider='discord'):
    """Where a material Seed Industries will not sell you comes from (material_source, first part)."""
    from .game.cooldowns_materials import material_source
    return material_source(x.key, provider).split(';')[0].rstrip('.')


def step_text(st):
    return st['name'] + (f" ({st['detail'].split(' · ')[0]})" if st['detail'] else '')


def entry_line(x):
    if x.entry is None:
        return f'❔ {x.recipe_id} — no longer available: remove it'
    line = f'{x.mark} **{x.name}** — have {x.have} / want {x.want}'
    if x.done:
        return line + ' · done'
    made = f'→ {_batches(x.batches)}' if x.batches else '→ left over from the other crafts'
    return f'{line} {made} · {x.state}'


def entry_match(x):
    """Text that finds an entry's line on the card (layout_v2 puts its button beside it)."""
    return f'{x.recipe_id} — no longer' if x.entry is None else f'— have {x.have} / want {x.want}'


def _materials(info, shown):
    """The MATERIALS section with its first `shown` materials (the missing ones first)."""
    if not info.materials:
        return []
    lines = ['', 'MATERIALS · need / have / missing']
    for x in info.materials[:shown]:
        lines.append(f'❌ {x.name} — need {x.need} / have {x.have} / missing {x.missing} → {route_text(x)}' if x.missing
                     else f'✅ {x.name} — need {x.need} / have {x.have}')
    if len(info.materials) > shown:
        lines.append(f'…and {len(info.materials) - shown} more.')
    if info.cost:
        lines.append(f'Buy all missing: {info.cost} SC for everything Seed Industries sells (you have {info.sc} SC).')
    if info.unsold:
        lines.append('Not for sale: ' + ' · '.join(f'{x.name} ({source(x)})' for x in info.unsold[:2]) +
                     (f' +{len(info.unsold) - 2} more' if len(info.unsold) > 2 else '') + '.')
    return lines


def screen_text(db, p, note='', info=None):
    """The Discord shopping list: entries, the combined materials, what buying costs and the first steps. It is one card:
    when everything does not fit (presentation's overview limits), fewer materials are listed."""
    from . import presentation
    info = info or overview(db, p)
    done = sum(x.done for x in info.items)
    head = [f'🛒 SHOPPING LIST · {len(info.items)}/{MAX_ENTRIES}'] + ([note.strip()] if note.strip() else [])
    if not info.items:
        return '\n'.join(head + ['Recipes you want, each in the amount you want to have, planned together: what several need '
                                 'counts once against what you own.', '',
                                 'Nothing listed yet. Press ➕ Add recipe…, or 🛒 Add to list on any recipe, then choose how many you want.'])
    head += ['Each recipe in the amount you want to have. One plan covers the whole list: what several need counts once.', '',
             f'RECIPES · {done}/{len(info.items)} DONE'] + [entry_line(x) for x in info.items]
    tail = []
    if info.steps:
        tail += ['', f'NEXT STEPS · {len(info.steps)} TO GO' if len(info.steps) != 1 else 'LAST STEP']
        for i, st in enumerate(info.steps[:STEPS_SHOWN], 1):
            tail.append(f"`{i}` {st['mark']} {st['name']}" + (f" — {'next · ' if i == 1 else ''}{st['detail']}" if st['detail'] else ''))
        if len(info.steps) > STEPS_SHOWN:
            tail.append(f'…and {len(info.steps) - STEPS_SHOWN} more after these.')
    elif done == len(info.items):
        tail += ['', '✅ Everything on your list is done. Clear done removes the finished entries.']
    tail += ['', 'The button by each entry changes or removes it. ▶️ Fetch next does the first step once.']
    chars, lines = presentation.OVERVIEW_CHARS - CARD_MARGIN, presentation.OVERVIEW_LINES - 6     # three sections
    for shown in range(min(MATERIALS_SHOWN, len(info.materials)), -1, -1):
        text = '\n'.join(head + _materials(info, shown) + tail)
        if len(text) <= chars and len([x for x in text.split('\n') if x.strip()]) <= lines:
            break
    return text


def item_text(db, p, recipe_id, note=''):
    """One entry: what you have and want, and how to change it."""
    e = wb.entry(recipe_id)
    row = next((r for r in entries(db, p) if r.recipe_id == recipe_id), None)
    lines = [f'🛒 SHOPPING LIST · {e.name.upper()}'] + ([note.strip()] if note.strip() else [])
    ctx = wb.Context(db, p)
    have, per = ctx.have(e.output), max(1, ctx.batch_size(e))
    if row is None:
        lines.append(f'You have {have}. Not on your shopping list: choose how many you want to have.')
    else:
        state = '✅ done' if have >= row.want else f'{_batches(math.ceil((row.want - have) / per))} of {per} to go'
        lines.append(f'You have {have}. You want {row.want} · {state}.')
    status = ctx.status(e)
    lines += [f'Recipe: {status.emoji} {status.short} · one batch makes {per}.',
              'Choose how many you want to have (up to 999); Remove takes it off the list.']
    return '\n'.join(lines)


def _chat_entry(x):
    if x.entry is None:
        return f'{x.recipe_id} (no longer available)'
    return f'{x.name} {x.have}/{x.want}' + ('✅' if x.done else '')


def chat_text(db, p):
    """Twitch: the whole list on one line: entries have/want, missing materials and the next step."""
    from . import presentation
    info = overview(db, p, 'twitch')
    if not info.items:
        return ('🛒 Your shopping list is empty. !shopping add <recipe> [amount] adds one, e.g. !shopping add iron plate 30; '
                'one plan then covers them all.')
    done = sum(x.done for x in info.items)
    missing = [x for x in info.materials if x.missing]
    shown = len(info.items)
    while True:
        names = ' · '.join(_chat_entry(x) for x in info.items[:shown]) + (f' +{len(info.items) - shown} more' if shown < len(info.items) else '')
        parts = [f'🛒 Shopping {done}/{len(info.items)} done: {names}']
        if missing:
            parts.append('Missing: ' + ', '.join(f'{x.missing} {x.name}' for x in missing[:4]) +
                         (f' +{len(missing) - 4} more' if len(missing) > 4 else '') +
                         (f' · buy for {info.cost} SC: !shopping buy' if info.cost else ''))
        if info.steps:
            parts.append('Next: ' + step_text(info.steps[0]))
        elif done == len(info.items):
            parts.append('All done: !shopping clear done')
        text = ' | '.join(parts + ['!shopping add <recipe> [amount] · remove <recipe> · clear'])
        if len(text.encode()) <= presentation.CHAT_LIMIT or shown <= 1:
            return text
        shown -= 1


# ---------------------------------------------------------------- buying everything missing

def _bought(info):
    return ', '.join(f'{x.missing} {x.name}' for x in info.buy)


def buy_preview(db, p, provider='twitch'):
    """What Buy all missing would buy and cost; nothing is bought."""
    info = overview(db, p, provider)
    if not info.items:
        return '🛒 Your shopping list is empty, so there is nothing to buy.'
    unsold = ' · '.join(f'{x.name} ({source(x, provider)})' for x in info.unsold[:3])
    tail = f' | Not for sale: {unsold}' if unsold else ''
    if not info.buy:
        return '🛒 Nothing missing on your list can be bought from Seed Industries.' + tail
    how = '!shopping buy confirm buys it.' if provider != 'discord' else 'Press Buy all missing to buy it.'
    if p.sc < info.cost:
        how = f'You have {p.sc} SC: earn {info.cost - p.sc} more first.'
    return f'🛒 Buy all missing: {_bought(info)} for {info.cost} SC from Seed Industries. {how}' + tail


def buy_all(db, p, provider='discord'):
    """Buy every missing material Seed Industries sells (the ordinary purchase), only when you can afford all of it."""
    from . import qol
    info = overview(db, p, provider)
    if not info.buy:
        return '🛒 Nothing missing on your list can be bought from Seed Industries. Nothing spent.'
    if p.sc < info.cost:
        return (f'🪙 Buying everything missing ({_bought(info)}) costs {info.cost} SC and you have {p.sc} SC: '
                f'earn {info.cost - p.sc} more SC first. Nothing spent.')
    before = p.sc
    shim = SimpleNamespace(inputs={x.key: x.have + x.missing for x in info.buy})
    receipts = qol.buy_missing(db, p, shim, 1, provider).split('\n')
    refused = [r for r in receipts if r and 'bought' not in r]
    text = f'🛒 Bought for your shopping list: {_bought(info)} for {before - p.sc} SC. Balance: {p.sc} SC.'
    return text + (' ' + refused[0] if refused else '')


# ---------------------------------------------------------------- Twitch and the route

def command(channel, uid, name, provider, text=''):
    """!shopping: blank sums the list up; 'add <recipe> [amount]' (0 removes), 'remove <recipe>', 'clear [done]',
    'buy' shows the cost and 'buy confirm' buys every missing material Seed Industries sells."""
    from .game.players import player
    words = str(text or '').split()
    verb = words[0].casefold() if words else ''
    rest = words[1:]
    with SessionLocal() as db:
        p = player(db, channel, provider, uid, name)[1]
        if not words:
            reply = chat_text(db, p) if provider != 'discord' else screen_text(db, p)
        elif verb == 'buy':
            confirm = bool(rest) and rest[0].casefold() in {'confirm', 'yes', 'go'}
            reply = buy_all(db, p, provider) if confirm else buy_preview(db, p, provider)
        elif verb == 'clear':
            reply = clear(db, p, done_only=bool(rest) and rest[0].casefold() == 'done')
        elif verb in {'remove', 'delete', 'rm', 'del'}:
            found, reply = listed_recipe(db, p, ' '.join(rest)) if rest else (None, '🛒 Which recipe? !shopping remove <recipe>. Nothing changed.')
            if found is not None:
                reply = (reply + ' ' if reply else '') + set_entry(db, p, found, 0)
        else:
            wanted, amount = _split(db, p, rest if verb == 'add' else words)
            if not wanted:
                reply = '🛒 Which recipe? !shopping add <recipe> [amount], e.g. !shopping add iron plate 30. Nothing changed.'
            elif amount is not None and str(amount).casefold() in REMOVE:
                found, reply = listed_recipe(db, p, wanted)
                if found is not None:
                    reply = (reply + ' ' if reply else '') + set_entry(db, p, found, 0)
            else:
                reply = add_typed(db, p, wanted, amount)
        db.commit()
        return reply
