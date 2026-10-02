"""Discord dropdowns and buttons for the Workbench, mining, gathering and queues.

Navigation (menus, pages, Back) is read-only; its state travels in the
component's custom_id. Every button that spends something (Craft, Start queue,
Gather, Cancel queue) carries a one-time ticket stored in the database. The
first press claims the ticket atomically, so a double click, a Discord retry
or an old message can never spend twice. Only the citizen who opened a panel
can use it; anyone else is told to open their own.

custom_id grammar (max 100 characters):  ne|<owner id>|<verb>|<args...>
  wh                      Workbench overview
  wc|<cat>|<page>|<st>    category page (st = workstation code or '')
  wr|<id>|<cat>|<page>|<st>  recipe preview (the rest is the Back target)
  sc                      category menu (value = category)
  sr|<cat>|<page>|<st>    recipe menu (value = recipe id)
  ss|<cat>                workstation filter menu (value = code or 'all')
  qp|<task>|<count>       queue plan before starting
  sq|<task>               queue amount menu (value = 1–10)
  qv                      queue status
  st                      status dashboard
  fv|<id>|<on>|<cat>|<page>|<st>  set favourite on (1) or off (0), then show the recipe
  fm|<id>|<batches>       fetch-missing-ingredients plan
  cn                      clear the next (follow-up) queue
  kv                      keep levels
  ki[|<item>]             one item's keep level (item = select value or arg): amounts, Custom…, Remove, Restock
  ks|<item>|<amount>      set a keep level (0 removes it), then show keep levels
  lv                      shopping list
  li|<recipe>             one shopping-list entry: amounts, Custom…, Remove
  ls|<recipe>|<amount>    want that many of a recipe's output (0 removes it), then show the list
  la|<recipe>             add a recipe to the shopping list (one batch), then show its entry
  lx|done|all             clear the done entries, or the whole list
  qo                      turn quiet hours off, then show settings (the form is mo|quiet)
  mn|mv|mk|mp             game menu areas, views and choices (see menu.py)
  bk|<fallback...>        Back: the screen this message showed before, else the fallback address
  mo|<leaf>               open a leaf's pop-up form (Discord modal)
  md|<leaf>[|<arg>]       a submitted pop-up form (interaction type 5)
  t|<ticket>              one-time action

Owner '*' marks the public game panel posted in the channel: anyone may press
it, and each press opens that citizen's own private menu. Public buttons only
navigate; they never carry tickets.

Every screen has ◀️ Back next to 🏠 Menu. Each panel message remembers the screens it
showed (HISTORY), so Back steps through them in reverse; on a message's first screen
or after a restart, Back goes one level up (the fallback its custom_id carries).

Category keys include the personal views 'ready' and 'favorites'. Setting a
favourite or clearing the next queue is idempotent, so neither needs a ticket.
"""
import contextvars
import copy
import json
import secrets
import threading
from collections import OrderedDict
from datetime import timedelta
from sqlalchemy import Column, String, Text, DateTime, delete, update
from .db import Base
from . import workbench as wb, seed_content as s, qol

from .notice import FOOTER                     # "… · a fan project by Kamex • …"
PUBLIC = '*'
# The Discord interaction being answered, so menu actions can check moderator rights.
INTERACTION = contextvars.ContextVar('ne_interaction', default=None)


def is_moderator(m):
    payload = INTERACTION.get()
    return bool(payload) and m._discord_is_moderator(payload)


def is_owner(m):
    payload = INTERACTION.get()
    return bool(payload) and m._discord_is_owner(payload)
TICKET_HOURS = 24
PANEL_COMMANDS = {'make', 'mine', 'gather', 'queue', 'status', 'seedindustries', 'menu', 'find', 'seedling', 'seedlingstep'}


class UiTicket(Base):
    __tablename__ = 'ui_tickets_v1'
    id = Column(String(32), primary_key=True)
    owner = Column(String(32), nullable=False)
    action = Column(Text, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- components

def cid(owner, *parts):
    value = '|'.join(['ne', str(owner), *[str(p) for p in parts]])
    if len(value) > 100:
        raise ValueError('custom_id too long: ' + value)
    return value


def button(label, custom_id, style=2, disabled=False, emoji=None):
    row = {'type': 2, 'style': style, 'label': wb.clip(label, 80), 'custom_id': custom_id}
    if disabled:
        row['disabled'] = True
    if emoji:
        row['emoji'] = {'name': emoji}
    return row


def select(custom_id, placeholder, options):
    options = options[:25]
    return {'type': 1, 'components': [{'type': 3, 'custom_id': custom_id, 'placeholder': wb.clip(placeholder, 150),
                                       'min_values': 1, 'max_values': 1, 'options': options}]}


def option(label, value, description='', emoji=None, default=False):
    row = {'label': wb.clip(label, 100), 'value': str(value)[:100]}
    if description:
        row['description'] = wb.clip(description, 100)
    if emoji:
        row['emoji'] = {'name': emoji}
    if default:
        row['default'] = True
    return row


def row(*buttons):
    return {'type': 1, 'components': [b for b in buttons if b][:5]}


_PENDING = contextvars.ContextVar('ne_pending_tickets', default=None)


class ticket_batch:
    """Save every ticket a screen creates in one transaction instead of one each."""

    def __init__(self, m):
        self.m = m

    def __enter__(self):
        self.outer = _PENDING.get() is not None
        if not self.outer:
            self.token = _PENDING.set([])
        return self

    def __exit__(self, kind, value, traceback):
        if self.outer:
            return False
        rows = _PENDING.get()
        _PENDING.reset(self.token)
        if rows:
            m = self.m
            with m.SessionLocal() as db:
                if secrets.randbelow(20) == 0:      # tidy expired tickets now and then, not on every press
                    db.execute(delete(UiTicket).where(UiTicket.expires_at < m.now()))
                db.add_all(rows)
                db.commit()
        return False


def issue(m, owner, action):
    """Create a one-time ticket for a spending button."""
    token = secrets.token_hex(16)
    pending = _PENDING.get()
    if pending is not None:
        pending.append(UiTicket(id=token, owner=str(owner), action=json.dumps(action, sort_keys=True),
                                expires_at=m.now() + timedelta(hours=TICKET_HOURS)))
        return token
    with m.SessionLocal() as db:
        db.execute(delete(UiTicket).where(UiTicket.expires_at < m.now()))
        db.add(UiTicket(id=token, owner=str(owner), action=json.dumps(action, sort_keys=True),
                        expires_at=m.now() + timedelta(hours=TICKET_HOURS)))
        db.commit()
    return token


def claim(m, owner, token):
    """Atomically mark a ticket used. Returns its action, or a reason string."""
    with m.SessionLocal() as db:
        row_ = db.get(UiTicket, token)
        if row_ is None or m.as_utc(row_.expires_at) < m.now():
            return None, 'This button has expired. Open the menu again for a fresh one. Nothing was spent.'
        if row_.owner != str(owner):
            return None, 'This menu belongs to another citizen. Open your own with the same command. Nothing was spent.'
        result = db.execute(update(UiTicket).where(UiTicket.id == token, UiTicket.used_at.is_(None))
                            .values(used_at=m.now()))
        db.commit()
        if result.rowcount != 1:
            return None, 'That button was already used, so nothing was repeated. Use the newest buttons on the panel.'
        return json.loads(row_.action), ''


# ---------------------------------------------------------------- embeds

def embed_from_text(m, text, command='make'):
    """Panels use the same card shapes as every other reply (see presentation)."""
    from . import presentation
    text = (text or '').strip() or 'No information available.'
    embed, shape, _ = presentation.card(m, text, command)
    if shape == 'info':
        embed['footer'] = {'text': FOOTER}
    return embed


def tidy(data):
    """Make components valid for Discord: no repeated custom_id, no empty rows, 5 rows of 5 at most.

    Discord rejects a whole message with a repeated custom_id, which leaves a deferred
    reply stuck on "thinking…", so every outgoing message passes through here.
    """
    if not isinstance(data, dict) or not data.get('components'):
        return data
    seen, rows = set(), []
    for component_row in data['components']:
        kept = []
        for component in (component_row or {}).get('components') or []:
            key = component.get('custom_id') or component.get('url')
            # The same label and icon twice (e.g. two "📊 Status" buttons) only confuses.
            face = ('face', component.get('label'), (component.get('emoji') or {}).get('name')) if component.get('type') == 2 else None
            if key in seen or (face is not None and face in seen):
                continue
            seen.update({key, face} - {None})
            kept.append(component)
        if kept:
            rows.append(dict(component_row, components=kept[:5]))
    data['components'] = rows[:5]
    return data


def message(m, text, components, command='make', items=None, replaces=()):
    rows = [c for c in components if c and c.get('components')][:5]
    seen = set()
    for component_row in rows:
        for component in component_row['components']:
            # Discord rejects a message whose components repeat a custom_id.
            while component['custom_id'] in seen:
                component['custom_id'] = (component['custom_id'] + '|~')[:100]
            seen.add(component['custom_id'])
    data = {'embeds': [embed_from_text(m, text, command)], 'components': rows, 'allowed_mentions': {'parse': []}}
    return with_items(data, items, replaces)


def with_crumb(data, crumb):
    """Show where a screen sits in the menu ('🏠 Menu › ⛏️ Work') in small text above its title."""
    embeds = data.get('embeds') or []
    if crumb and embeds and isinstance(embeds[0], dict) and not embeds[0].get('author'):
        embeds[0]['author'] = {'name': crumb[:256]}
    return data


def with_items(data, items, replaces=()):
    """Name the list items that get their button beside them in Discord's newer layout.

    items: dicts with 'match' (text that finds the item's line in the card) or 'line'
    (a line to add), and the 'button' to put beside it; 'compact' items keep their
    button in the rows below and drop their line. replaces: custom_ids of controls the
    item buttons make redundant (a dropdown of the same items). layout_v2 reads these;
    the old layout ignores them, and neither is ever sent to Discord.
    """
    if items:
        data['_items'] = list(items)
        data['_replaces'] = [c for c in replaces if c]
    return data


def pick_button(select_id, value, label, style=2):
    """A button that stands for picking `value` from the dropdown `select_id` (see handle_component)."""
    custom_id = f'{select_id}|={value}'
    if '|' in str(value) or len(custom_id) > 100:
        return None
    return button(label, custom_id, style=style)


# ---------------------------------------------------------------- workbench views

def _code(station):
    code = wb.station_code(station) if station else -1
    return '' if code < 0 else str(code)


def category_menu(m, ctx, owner, current=''):
    counts = wb.category_counts(ctx)
    total, ready, _ = counts['ready']
    options = [option('Ready now', 'ready', f'{total} recipes you can craft right now · favourites first', '✅', current == 'ready')]
    total, ready, _ = counts['favorites']
    options.append(option('Favourites', 'favorites', f'{ready} ready of {total}/{qol.MAX_FAVORITES} starred recipes', '⭐', current == 'favorites'))
    for key, emoji, label, text in wb.CATEGORIES:
        total, ready, lowest = counts.get(key, (0, 0, 1))
        options.append(option(label, key, f'{ready} ready of {total} · from Tier {lowest} · {text}', emoji, key == current))
    return select(cid(owner, 'sc'), 'Choose a category (recipes listed easiest first)', options)


def home_components(m, ctx, owner):
    return [category_menu(m, ctx, owner)]


def home_items(ctx, owner):
    """Ready now, Favourites and every category, each with an Open button beside it."""
    keys = [('Ready now', 'ready'), ('Favourites', 'favorites')] + [(label, key) for key, _, label, _ in wb.CATEGORIES]
    return [{'match': f'**{label}**', 'button': button('Browse', cid(owner, 'wc', key, 1, ''))} for label, key in keys], [cid(owner, 'sc')]


def category_items(ctx, owner, category, page, station=''):
    """Each recipe on the page with an Open button (its preview) beside it, in the list's order."""
    rows = wb.in_view(ctx, category, station)
    page, pages, start, end = wb.page_bounds(len(rows), page)
    st = _code(station)
    items = [{'match': f'**{e.name}**', 'button': button('Craft' if ctx.status(e).code == 'ready' else 'View', cid(owner, 'wr', e.id, category, page, st),
                                                         style=3 if ctx.status(e).code == 'ready' else 2)}
             for e in rows[start:end]]
    return items, [cid(owner, 'sr', category, page, st)]


def training_items(m, db, p, owner, hub):
    """Each task of one skill with a Start button beside it; the button does the task once."""
    items = []
    for key, cfg in m.SEED_TASKS.items():
        if cfg['hub'] != hub:
            continue
        ready = m.training_choice_label(db, p, key, cfg)[:1] == '✅'
        ticket = issue(m, owner, {'do': 'train', 'skill': hub, 'task': key})
        items.append({'match': cfg['label'], 'button': button('Start', cid(owner, 't', ticket), style=3 if ready else 2)})
    return items


def list_items(m, owner, command, options, name='Citizen'):
    """(items, replaces) for list views that are not panels, else (None, ()). See with_items."""
    command, options = m.discord_legacy_route(command, options or {})
    if command == 'training' and options.get('skill') and not options.get('task'):
        hub = str(options['skill']).lower().strip()
        if hub in m.SEED_HUBS:
            with m.SessionLocal() as db:
                p = _player(m, db, owner, name)
                items = training_items(m, db, p, owner, hub)
                db.commit()
            return items, ()
    return None, ()


def add_list_items(m, data, owner, command, options, name='Citizen'):
    """Message data with its list items named (see list_items); unchanged for other views."""
    try:
        items, replaces = list_items(m, owner, command, options, name)
    except Exception:
        import logging
        logging.getLogger(__name__).error('List buttons could not be prepared: %s', command)
        return data
    return with_items(data, items, replaces) if items else data


def workbench_message(m, ctx, owner, text, category='', page=1, station='', command='make'):
    """The Workbench home or a category page, with a button beside each category or recipe."""
    if category:
        items, replaces = category_items(ctx, owner, category, page, station)
        return message(m, text, category_components(m, ctx, owner, category, page, station), command, items, replaces)
    items, replaces = home_items(ctx, owner)
    return message(m, text, home_components(m, ctx, owner), command, items, replaces)


def category_components(m, ctx, owner, category, page, station=''):
    rows = wb.in_view(ctx, category, station)
    page, pages, start, end = wb.page_bounds(len(rows), page)
    st = _code(station)
    components = []
    shown = rows[start:end]
    if shown:
        components.append(select(cid(owner, 'sr', category, page, st), f'Choose a recipe to preview (page {page}/{pages})',
                                 [option(f'{ctx.star(e)}{e.name} ×{ctx.batch_size(e)}', e.id, wb.option_description(ctx, e), ctx.status(e).emoji)
                                  for e in shown]))
    components.append(category_menu(m, ctx, owner, category))
    stations = sorted({t for e in wb.in_view(ctx, category) for t in e.tags},
                      key=lambda t: (wb.cp.STATIONS[t]['tier'], wb.cp.STATIONS[t]['name']))
    if len(stations) > 1:
        options = [option('All workstations', 'all', 'Show every recipe in this category', '🧭', not station)]
        for t in stations[:24]:
            info = wb.cp.STATIONS[t]
            state = 'ready' if t in ctx.access and info['tier'] <= ctx.tier else ('Tier ' + str(info['tier']) + ' lock' if info['tier'] > ctx.tier else f"unlock {info['cost']} SC")
            options.append(option(info['name'], wb.station_code(t), f"Tier {info['tier']} · {state}", None, t == station))
        components.append(select(cid(owner, 'ss', category), 'Filter by workstation', options))
    components.append(row(
        button('Previous', cid(owner, 'wc', category, page - 1, st), disabled=page <= 1, emoji='◀️'),
        button(f'Page {page}/{pages}', cid(owner, 'wc', category, page, st), disabled=True),
        button('Next', cid(owner, 'wc', category, page + 1, st), disabled=page >= pages, emoji='▶️'),
        button('Workbench', cid(owner, 'wh'), emoji='🛠️')))
    return components


def recipe_components(m, ctx, owner, e, category='', page=1, station=''):
    category = category or e.category
    st = _code(station)
    status = ctx.status(e)
    craft_ticket = issue(m, owner, {'do': 'craft', 'recipe': e.id, 'back': [category, page, st]})
    task = 'make:' + e.id
    craft_label = 'Craft 1 batch' if status.code == 'ready' else f'Craft 1 batch ({status.short})'
    unlock = None
    if status.code == 'station':
        tag = ctx.unlock_option(e)
        info = wb.cp.STATIONS[tag]
        ticket = issue(m, owner, {'do': 'unlock', 'station': tag, 'recipe': e.id, 'back': [category, page, st]})
        unlock = button(f"Unlock {info['name']} · {info['cost']} SC", cid(owner, 't', ticket), style=1,
                        disabled=ctx.p is not None and ctx.p.sc < info['cost'], emoji='🔑')
    buttons = row(
        unlock,
        button(craft_label, cid(owner, 't', craft_ticket), style=3, disabled=status.code not in {'ready', 'missing'}, emoji='🛠️'),
        button('Queue 5', cid(owner, 'qp', task, 5), disabled=status.code in {'locked', 'owned'}, emoji='⏱️'),
        button('Queue 10', cid(owner, 'qp', task, 10), disabled=status.code in {'locked', 'owned'}, emoji='⏱️'),
        back_button(owner, 'wc', category, page, st))
    amounts = select(cid(owner, 'sq', task), 'Queue a different number of batches (1–10)',
                     [option(f'Queue {n} batch' + ('es' if n > 1 else ''), n, f'Shows totals before starting · up to {n * ctx.batch_size(e)} {e.name}')
                      for n in range(1, 11)])
    starred = e.id in ctx.favorites
    most = 0
    if ctx.p is not None and status.code not in {'locked', 'owned'}:
        from . import extras as more
        most, _ = more.max_attempts(m, ctx.db, ctx.p, task)
    extras = row(
        button('Unfavourite' if starred else 'Favourite', cid(owner, 'fv', e.id, 0 if starred else 1, category, page, st), emoji='☆' if starred else '⭐'),
        button('Fetch missing', cid(owner, 'fm', e.id, 1), style=1, emoji='🧺') if status.code == 'missing' else None,
        button(f'Queue max ×{most}', cid(owner, 'qp', task, max(1, most)), disabled=not most, emoji='📦') if status.code not in {'locked', 'owned'} else None,
        button('Set goal', cid(owner, 'gs', e.id), emoji='🎯'),
        button('Status', cid(owner, 'st'), emoji='📊'))
    return [buttons, extras] + ([amounts] if status.code not in {'locked', 'owned'} else []) + [row(shopping_button(ctx, owner, e))]


def shopping_button(ctx, owner, e):
    """🛒 Add to list on a recipe preview, or its entry when the recipe is already on the shopping list. In a row of
    its own, where ◀️ Back and 🏠 Menu join it (the row above already has five buttons)."""
    from . import shopping_list as shop
    listed = ctx.db.get(shop.ShoppingEntry, (ctx.p.channel_id, ctx.p.twitch_uid, e.id)) if ctx.p is not None else None
    if listed is not None:
        return button(f'On shopping list · want {listed.want}', cid(owner, 'li', e.id), emoji='🛒')
    return button('Add to list', cid(owner, 'la', e.id), emoji='🛒')


def after_craft_components(m, ctx, owner, e, back):
    category, page, st = (back + ['', 1, ''])[:3]
    ticket = issue(m, owner, {'do': 'craft', 'recipe': e.id, 'back': [category, page, st]})
    return [row(button('Craft again', cid(owner, 't', ticket), style=3, emoji='🛠️'),
                button('Queue 5', cid(owner, 'qp', 'make:' + e.id, 5), emoji='⏱️'),
                button('Recipe', cid(owner, 'wr', e.id, category or e.category, page, st), emoji='📋'),
                button('Ready now', cid(owner, 'wc', 'ready', 1, ''), emoji='✅'),
                button('Workbench', cid(owner, 'wh'), emoji='🛠️'))]


# ---------------------------------------------------------------- queue views

def task_label(m, task):
    return m.task_queue.choices(m).get(task, task)


def queue_plan(m, db, p, owner, task, count):
    count = max(1, min(10, int(count)))
    kind, target = task.split(':', 1)
    e = wb.entry(m, target) if kind == 'make' else None
    if e is not None:
        ctx = wb.Context(m, db, p)
        text = wb.queue_plan_text(ctx, e, count)
        back = back_button(owner, 'wr', e.id, e.category, 1, '')
    else:
        text = (f'⏱️ QUEUE {count} × {task_label(m, task).upper()}\n' + m.task_queue.requirements(m, db, p, task, count) +
                '\n\nPress Start to begin. The queue works one attempt every 10 seconds, pauses when a need or item runs short, and resumes by itself.')
        back = None
    current = db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)) if p is not None else None
    if current is not None and current.state in m.task_queue.ACTIVE:
        ticket = issue(m, owner, {'do': 'plan', 'task': task, 'count': count})
        text += (f'\n\nYou already have a queue ({task_label(m, current.task)}). Press Add to plan to run this one '
                 'automatically after it (and after anything else you planned).')
        start = button(f'Add to plan ×{count}', cid(owner, 't', ticket), style=3, emoji='➕')
    else:
        ticket = issue(m, owner, {'do': 'queue', 'task': task, 'count': count})
        start = button(f'Start queue ×{count}', cid(owner, 't', ticket), style=3, emoji='▶️')
    return text, [row(start, back, button('Queue status', cid(owner, 'qv'), emoji='📋'))]


def queue_components(m, db, p, owner):
    row_ = db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)) if p is not None else None
    buttons = [button('Refresh', cid(owner, 'qv'), emoji='🔄')]
    if row_ is not None and row_.state in m.task_queue.ACTIVE | {'error'}:
        ticket = issue(m, owner, {'do': 'cancel'})
        buttons.insert(0, button('Cancel queue', cid(owner, 't', ticket), style=4, emoji='⏹️'))
    repeat = repeat_button(m, owner, row_)
    if repeat:
        buttons.insert(0, repeat)
    if p is not None and qol.next_task(db, p.channel_id, p.twitch_uid)[0]:
        buttons.append(button('Clear next', cid(owner, 'cn'), emoji='⏭️'))
    buttons.append(button('Status', cid(owner, 'st'), emoji='📊'))
    rows = [row(*buttons)]
    if row_ is not None:
        rows.append(row(button('Details & requirements', cid(owner, 'qd'), emoji='📘')))
    return rows


def repeat_button(m, owner, queue_row):
    """Repeat a finished queue: opens its plan, so nothing starts without Start."""
    if queue_row is None or queue_row.state in m.task_queue.ACTIVE or queue_row.task not in m.task_queue.choices(m):
        return None
    try:
        return button(f'Repeat ×{queue_row.total}', cid(owner, 'qp', queue_row.task, queue_row.total), style=1, emoji='🔁')
    except ValueError:
        return None


# ---------------------------------------------------------------- status, fetch and alerts

def status_components(m, db, p, owner):
    tq = m.task_queue
    queue_row = db.get(tq.TaskQueue, (p.channel_id, p.twitch_uid)) if p is not None else None
    first = [button('Refresh', cid(owner, 'st'), emoji='🔄'),
             button('Ready now', cid(owner, 'wc', 'ready', 1, ''), emoji='✅'),
             button('Favourites', cid(owner, 'wc', 'favorites', 1, ''), emoji='⭐'),
             button('Workbench', cid(owner, 'wh'), emoji='🛠️'),
             button('Queue', cid(owner, 'qv'), emoji='📋')]
    second = [repeat_button(m, owner, queue_row)]
    if p is not None and m.blocked_needs(m.life_state(db, p)):
        ticket = issue(m, owner, {'do': 'recover'})
        second.append(button('Recover now', cid(owner, 't', ticket), style=3, emoji='🩹'))
    return [row(*first)] + ([row(*second)] if any(second) else [])


def fetch_components(m, ctx, owner, e, batches, start):
    buttons = []
    if start:
        current = ctx.db.get(m.task_queue.TaskQueue, (ctx.p.channel_id, ctx.p.twitch_uid))
        label = task_label(m, start['task'])
        if current is not None and current.state in m.task_queue.ACTIVE:
            ticket = issue(m, owner, {'do': 'next', 'task': start['task'], 'count': start['count']})
            buttons.append(button(f"Queue next: {label} ×{start['count']}", cid(owner, 't', ticket), style=3, emoji='⏭️'))
        else:
            ticket = issue(m, owner, {'do': 'queue', 'task': start['task'], 'count': start['count'], 'then': start['then']})
            verb = f"{label} ×{start['count']}" + (' → craft' if start['then'] else '')
            buttons.append(button(verb, cid(owner, 't', ticket), style=3, emoji='▶️'))
    routes = qol.fetch_routes(ctx, e, batches)
    cost = sum(r['price'] * r['short'] for r in routes if r['price'])
    if cost:
        ticket = issue(m, owner, {'do': 'buy', 'recipe': e.id, 'batches': batches})
        buttons.append(button(f'Buy missing · {cost} SC', cid(owner, 't', ticket), style=1,
                              disabled=ctx.p is not None and ctx.p.sc < cost, emoji='🪙'))
    source = next((r for r in routes if r['kind'] == 'recipe'), None)
    if source:
        buttons.append(button(f"{source['recipe_name']} recipe", cid(owner, 'wr', source['recipe'], '', 1, ''), emoji='📋'))
    other = 5 if batches == 1 else 1
    navigation = [button(f'Plan for {other} batch' + ('es' if other > 1 else ''), cid(owner, 'fm', e.id, other), emoji='🔢'),
                  back_button(owner, 'wr', e.id, e.category, 1, '')]
    return [row(*buttons[:5]), row(*navigation)] if buttons else [row(*navigation)]


def alert_components(m, notice):
    """Buttons under a Discord queue alert: repeat it, check status, or recover now."""
    owner = str(notice.recipient)
    if not owner.isdigit():
        return []
    with m.SessionLocal() as db:
        info = db.get(m.task_queue.queue_notifications.NoticeTask, notice.id)
    buttons = []
    paused = 'QUEUE — PAUSED' in notice.content
    if info is not None and not paused and info.task in m.task_queue.choices(m):
        try:
            buttons.append(button(f'Repeat ×{info.total}', cid(owner, 'qp', info.task, info.total), style=1, emoji='🔁'))
        except ValueError:
            pass
    if paused and 'need ' in notice.content:
        ticket = issue(m, owner, {'do': 'recover'})
        buttons.append(button('Recover now', cid(owner, 't', ticket), style=3, emoji='🩹'))
    buttons += [button('Status', cid(owner, 'st'), emoji='📊'), button('Queue', cid(owner, 'qv'), emoji='📋')]
    return [row(*buttons)]


def work_components(m, owner, task):
    """Mine or gather a resource: one attempt now, or a queue with a plan first."""
    kind, target = task.split(':', 1)
    ticket = issue(m, owner, {'do': 'queue', 'task': task, 'count': 1} if kind == 'mine' else {'do': 'gather', 'item': target})
    verb = 'Mine' if kind == 'mine' else 'Gather'
    from . import extras as more
    most = more.max_for_owner(m, owner, task)
    return [row(button(f'{verb} ×1', cid(owner, 't', ticket), style=3, emoji='⛏️' if kind == 'mine' else '🌿'),
                button('Queue 5', cid(owner, 'qp', task, 5), emoji='⏱️'),
                button('Queue 10', cid(owner, 'qp', task, 10), emoji='⏱️'),
                button(f'Queue max ×{most}', cid(owner, 'qp', task, max(1, most)), disabled=not most, emoji='📦'),
                button('Queue status', cid(owner, 'qv'), emoji='📋'))]


# ---------------------------------------------------------------- slash commands

def slash_panel(m, command, uid, name, options, result):
    """Discord message data (embed + components) for panel commands, else None."""
    if command not in PANEL_COMMANDS:
        return None
    with m.SessionLocal() as db:
        p = _player(m, db, uid, name)
        if command == 'make':
            ctx = wb.Context(m, db, p)
            category = wb.normalize_category(options.get('category')) or ''
            station = wb.find_station(options.get('station')) or ''
            page = int(options.get('page') or 1)
            recipe = options.get('recipe')
            action = options.get('action') or 'preview'
            e = wb.resolve(m, db, p, recipe, category) if recipe else None
            if recipe and e is None:
                e = qol.fuzzy_recipe(m, db, p, recipe, category)[0]
            if e is None:
                return workbench_message(m, ctx, uid, result, category, page, station, command)
            elif action == 'preview':
                components = recipe_components(m, ctx, uid, e, category, page, station)
            elif action == 'queue':
                components = queue_components(m, db, p, uid)
            elif action == 'fetch':
                batches = max(1, min(10, int(options.get('count') or 1)))
                components = fetch_components(m, ctx, uid, e, batches, qol.fetch_plan(ctx, e, batches)[1])
            elif action == 'favorite':
                components = recipe_components(m, ctx, uid, e, category, page, station)
            else:
                components = after_craft_components(m, ctx, uid, e, [category or e.category, page, _code(station)])
            return message(m, result, components, command)
        if command == 'mine':
            ore = s.find_item(str(options.get('ore') or ''))
            if options.get('action') == 'mine' or ore not in m.task_queue.ores():
                return message(m, result, queue_components(m, db, p, uid) if options.get('action') == 'mine' else [], command)
            return message(m, result, work_components(m, uid, 'mine:' + ore), command)
        if command == 'gather':
            item = s.find_item(str(options.get('resource') or ''))
            if item not in s.GATHER or item in m.task_queue.ores():
                return None
            return message(m, result, work_components(m, uid, 'gather:' + item), command)
        if command == 'queue':
            return message(m, result, queue_components(m, db, p, uid), command)
        if command == 'status':
            return message(m, result, status_components(m, db, p, uid), command)
        if command == 'menu':
            from . import menu
            ctx = menu.context(m, uid, db, p)
            rows = menu.area_components(m, uid, 'home', ctx)
            items = menu.area_items(m, 'home', ctx, rows)
            rows, items = menu.with_next(m, db, p, uid, ctx, rows, items)
            return dict(message(m, result, rows, command, items), _home=True)
        if command == 'find':
            return message(m, result, find_components(m, uid, str(options.get('query') or '')), command)
        if command in {'seedling', 'seedlingstep'}:
            return message(m, result, seedling_components(m, db, p, uid), 'seedling')
        if command == 'seedindustries' and options.get('action') == 'clearout' and qol.clearout_plan(m, db, p):
            ticket = issue(m, uid, {'do': 'clearout'})
            total = sum(n * price for _, n, price in qol.clearout_plan(m, db, p))
            return message(m, result, [row(button(f'Sell for {total} SC', cid(uid, 't', ticket), style=3, emoji='🧹'),
                                           button('Status', cid(uid, 'st'), emoji='📊'))], command)
    return None


def _player(m, db, uid, name):
    return m.player(db, m.DISCORD_WORLD_ID, 'discord', uid, name)[1]


# ---------------------------------------------------------------- component interactions

def _user(payload):
    member = payload.get('member') or {}
    user = member.get('user') or payload.get('user') or {}
    name = member.get('nick') or user.get('global_name') or user.get('username') or 'Citizen'
    return str(user.get('id') or ''), name


def with_menu(data, owner=None):
    """Every screen ends with ◀️ Back and 🏠 Menu, together and last, so no screen is a dead end.
    The home menu gets Back too once its message has an earlier screen to go back to."""
    rows = [r for r in data.get('components') or [] if r and r.get('components')]
    ids = [str(c.get('custom_id') or '') for r in rows for c in r['components']]
    owner = next((i.split('|')[1] for i in ids if i.startswith('ne|')), owner)
    if not rows or owner is None:
        return data
    is_back = lambda c: str(c.get('custom_id') or '').split('|')[2:3] == ['bk']
    is_menu = lambda c: str(c.get('custom_id') or '').split('|')[2:] == ['mn', 'home']
    back = next((c for r in rows for c in r['components'] if is_back(c)), None)
    menu = next((c for r in rows for c in r['components'] if is_menu(c)), None)
    home = bool(data.get('_home'))
    if back is None and owner != PUBLIC and (not home or _earlier_screen(owner)):
        back = back_button(owner)
    if menu is None and not home:
        menu = button('Menu', cid(owner, 'mn', 'home'), emoji='🏠')
    tail = [c for c in (back, menu) if c is not None]
    if not tail:
        return data
    kept = [dict(r, components=[c for c in r['components'] if not is_back(c) and not is_menu(c)]) for r in rows]
    kept = [r for r in kept if r['components']]
    if kept and all(c.get('type') == 2 for c in kept[-1]['components']) and len(kept[-1]['components']) + len(tail) <= 5:
        kept[-1] = dict(kept[-1], components=kept[-1]['components'] + tail)
    elif len(kept) < 5:
        kept.append(row(*tail))
    else:
        return data                     # five full rows: leave the screen as it is
    data['components'] = kept
    return data


def _earlier_screen(owner):
    """Whether the message being pressed has shown a screen before this one (for Back on the home menu)."""
    payload = INTERACTION.get()
    if not payload:
        return False
    found = HISTORY.get((owner, str((payload.get('message') or {}).get('id') or '')))
    return bool(found and found['screens'])


# ---------------------------------------------------------------- Back: the screens a message showed

# Each panel message remembers the screens it showed, newest last, so ◀️ Back reopens the one
# before, step by step. Kept in memory: on a message's first screen, or after a restart, Back
# goes one level up instead (the fallback address its button carries).
HISTORY = OrderedDict()            # (owner, message id) -> {'screens': [(verb, args, values)…], 'on': bool}
HISTORY_KEEP = 5000                # messages remembered, the oldest forgotten first
HISTORY_DEPTH = 20                 # screens remembered per message
_HISTORY_LOCK = threading.Lock()   # presses are answered on worker threads
# Controls that only show a screen, so Back can show it again. Anything else (a one-time action,
# a toggle, setting a goal) leaves its result on the message, and Back returns to the screen before.
SCREENS = {'wh', 'wc', 'sc', 'ss', 'wr', 'sr', 'qp', 'sq', 'qv', 'qd', 'st', 'gv', 'pv', 'av', 'kv', 'ki', 'fu', 'fi', 'fd', 'fm',
           'mn', 'mv', 'mk', 'mp', 'ma', 'lp', 'lv', 'li'}


def back_button(owner, *fallback):
    """◀️ Back: the screen this message showed before; on its first screen, `fallback` (one level up), else the menu."""
    return button('Back', cid(owner, 'bk', *fallback), emoji='◀️')


def _history(payload, owner):
    key = (owner, str((payload.get('message') or {}).get('id') or ''))
    with _HISTORY_LOCK:
        found = HISTORY.get(key)
        if found is None:
            found = HISTORY[key] = {'screens': [], 'on': False}
            while len(HISTORY) > HISTORY_KEEP:
                HISTORY.popitem(last=False)
        HISTORY.move_to_end(key)
        return found


def _remember(payload, owner, verb, args, values, answer):
    """A screen shown in place joins its message's history; any other change to the message is a result."""
    if not isinstance(answer, dict) or answer.get('type') != 7:
        return answer                   # a private notice or a new message: this message did not change
    found = _history(payload, owner)
    if verb not in SCREENS:
        found['on'] = False
        return answer
    screen = (verb, list(args), list(values or []))
    if not (found['on'] and found['screens'] and found['screens'][-1] == screen):
        found['screens'] = (found['screens'] + [screen])[-HISTORY_DEPTH:]
    found['on'] = True
    return answer


def _left_screen(payload, owner):
    """A one-time action is about to replace the screen with its result."""
    if int((payload.get('message') or {}).get('flags', 0)) & 64:
        _history(payload, owner)['on'] = False


def go_back(m, payload, uid, name, owner, fallback):
    """◀️ Back: the screen before the one shown (or before an action's result), else the fallback."""
    found = _history(payload, owner)
    if found['on'] and found['screens']:
        found['screens'].pop()          # leave the screen being shown
    if found['screens']:
        verb, args, values = found['screens'][-1]
    elif fallback:
        verb, args, values = fallback[0], list(fallback[1:]), []
    else:
        verb, args, values = 'mn', ['home'], []
    with ticket_batch(m):
        try:
            answer = _navigate(m, payload, uid, name, owner, verb, args, values)
        except (IndexError, KeyError, ValueError):
            verb, args, values = 'mn', ['home'], []
            answer = _navigate(m, payload, uid, name, owner, verb, args, values)
    return _remember(payload, owner, verb, args, values, answer)


def _reply(data, payload, notice=False):
    """Update the panel in place when it is private; otherwise answer privately."""
    ephemeral = int((payload.get('message') or {}).get('flags', 0)) & 64
    data = with_menu(tidy(dict(data)))
    if ephemeral and not notice:
        return {'type': 7, 'data': data}
    data['flags'] = 64
    return {'type': 4, 'data': data}


# Private cards a player can post to the channel for everyone: command -> (what it is, sections that may be shared).
SHARE = {'me': ('profile', {'', 'overview'}), 'seedling': ('Seedling', {'', 'overview', 'diary'}),
         'trophies': ('trophies', {'', 'collections', 'crafting', 'festivals', 'colony', 'stream', 'seasons'}),
         'season': ('season', {'', 'overview', 'top', 'rewards', 'story'}), 'customize': ('Seedling’s look', {''})}


def share_button(owner, command, options):
    """A 📣 Share button for a card that can be shown to everyone, else None."""
    section = str((options or {}).get('section') or '')
    if command not in SHARE or section not in SHARE[command][1] or (options or {}).get('schedule') or (options or {}).get('autonomy') \
            or (options or {}).get('hat') or (options or {}).get('badge'):
        return None
    return button('Share', cid(owner, 'sh', command, section), emoji='📣')


def share(m, uid, name, args):
    """Post the card publicly in the channel, with who shared it."""
    command, section = (args[0] if args else ''), (args[1] if len(args) > 1 else '')
    if command not in SHARE or section not in SHARE[command][1]:
        return _notice('This card cannot be shared.')
    text = m._discord_call_internal(command, uid, name, {'section': section} if section else {}, '')
    data = dict(m._discord_json_message(text, message_type=command)['data'])
    for key in ('flags', 'components'):
        data.pop(key, None)
    if data.get('embeds'):
        data['embeds'][0]['author'] = {'name': f'📣 {name} shared their {SHARE[command][0]}'}
    else:
        data['content'] = f'📣 **{name}** shared their {SHARE[command][0]}\n' + str(data.get('content') or '')
    data['allowed_mentions'] = {'parse': []}
    return {'type': 4, 'data': data}   # no ephemeral flag: everyone in the channel sees it


def _notice(text):
    return {'type': 4, 'data': {'content': text, 'flags': 64, 'allowed_mentions': {'parse': []}}}


def handles(custom_id):
    return str(custom_id or '').startswith('ne|')


def handle_component(m, payload, schedule=None):
    """Answer a Workbench/queue component. `schedule(fn, *args)` defers spending work."""
    data = payload.get('data') or {}
    parts = str(data.get('custom_id') or '').split('|')
    uid, name = _user(payload)
    if len(parts) < 3 or parts[0] != 'ne':
        return _notice('This control is no longer available. Run the command again.')
    owner, verb, args = parts[1], parts[2], parts[3:]
    INTERACTION.set(payload)
    if owner == PUBLIC:
        # The public game panel: each press opens the presser's own private menu.
        if verb == 't':
            return _notice('Open your own menu first. Nothing was spent.')
        owner = uid
    if uid != owner:
        return _notice('This menu belongs to another citizen. Open your own with the same command. Nothing was spent.')
    values = data.get('values') or []
    if args and args[-1].startswith('='):
        # A button beside a list item (pick_button): the same as choosing it from the dropdown.
        values, args = [args[-1][1:]], args[:-1]
    if verb == 'sh':
        return share(m, uid, name, args)
    if verb == 'bk':
        if schedule is not None:
            schedule(_popups, m, payload, uid)
        return go_back(m, payload, uid, name, owner, args)
    if verb == 'mo':
        from . import menu
        form = menu.modal(owner, args[0] if args else '', args[1:], m)
        return form or _notice('This control is no longer available. Open /menu again.')
    if verb == 'mp':
        from . import menu
        item = menu.LEAVES.get(args[0] if args else '')
        if item is not None and item.get('then') == 'do':
            # Choosing from an action list (a food, a hobby…) performs it, like a slash command.
            action = {'do': 'cmd', 'leaf': args[0], 'value': values[0] if values else ''}
            _left_screen(payload, owner)
            if schedule is None:
                return _reply(run_ticket(m, uid, name, action, payload), payload)
            schedule(finish_ticket, m, payload, uid, name, action)
            return {'type': 6}
    if verb == 't':
        # Claiming is one conditional UPDATE, safe without the world lock, so the
        # press is acknowledged at once even while a queue attempt is running.
        action, reason = claim(m, owner, args[0] if args else '')
        if action is None:
            return _notice(reason)
        _left_screen(payload, owner)
        if schedule is None:
            return _reply(run_ticket(m, uid, name, action, payload), payload)
        schedule(finish_ticket, m, payload, uid, name, action)
        return {'type': 6}
    if schedule is not None:
        schedule(_popups, m, payload, uid)
    # Menus and views do not take the world lock: they only read, or change the
    # presser's own preferences. Game commands they show take it themselves.
    with ticket_batch(m):
        try:
            return _remember(payload, owner, verb, args, values, _navigate(m, payload, uid, name, owner, verb, args, values))
        except (IndexError, KeyError, ValueError):
            # Malformed or outdated custom_id: navigation is read-only, so just say so.
            return _notice('This control is no longer available. Run the command again.')


def _navigate(m, payload, uid, name, owner, verb, args, values):
    with m.SessionLocal() as db:
        p = _player(m, db, uid, name)
        ctx = wb.Context(m, db, p)
        db.commit()
        from .menu import crumb
        if verb == 'wh':
            return _reply(with_crumb(workbench_message(m, ctx, owner, wb.home_text(ctx)), crumb('craft', 'Workbench')), payload)
        if verb in {'wc', 'sc', 'ss'}:
            if verb == 'sc':
                category, page, station = (values[0] if values else ''), 1, ''
            elif verb == 'ss':
                category = args[0] if args else ''
                station = '' if not values or values[0] == 'all' else wb.station_from_code(values[0])
                page = 1
            else:
                category, page, station = args[0], int(args[1] or 1), wb.station_from_code(args[2]) if len(args) > 2 and args[2] else ''
            if category not in wb.VIEW_INFO:
                return _notice('Choose a category from the menu.')
            from . import extras as more
            more.remember_place(db, p, category, page, _code(station))
            db.commit()
            text = wb.category_text(ctx, category, page, station)
            return _reply(with_crumb(workbench_message(m, ctx, owner, text, category, page, station),
                                     crumb('craft', 'Workbench › ' + wb.VIEW_INFO[category][1] if isinstance(wb.VIEW_INFO.get(category), tuple) else 'Workbench')), payload)
        if verb in {'wr', 'sr'}:
            if verb == 'sr':
                recipe = values[0] if values else ''
                category, page, station = args[0], int(args[1] or 1), wb.station_from_code(args[2]) if len(args) > 2 and args[2] else ''
            else:
                recipe = args[0]
                category, page, station = (args[1] if len(args) > 1 else ''), int(args[2] or 1) if len(args) > 2 else 1, wb.station_from_code(args[3]) if len(args) > 3 and args[3] else ''
            e = wb.entry(m, recipe)
            if e is None:
                return _notice('That recipe is no longer available. Open /make again.')
            text = wb.preview_text(ctx, e)
            return _reply(with_crumb(message(m, text, recipe_components(m, ctx, owner, e, category, page, station)), crumb('craft', 'Workbench › ' + e.name)), payload)
        if verb in {'qp', 'sq'}:
            task = args[0]
            count = int(values[0]) if verb == 'sq' and values else int(args[1] if len(args) > 1 else 1)
            if task not in m.task_queue.choices(m):
                return _notice('That task is no longer available. Open the menu again.')
            text, components = queue_plan(m, db, p, owner, task, count)
            return _reply(message(m, text, components), payload)
        if verb == 'qv':
            text = m.task_queue.status(m, db, p, db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)))
            return _reply(message(m, text, queue_components(m, db, p, owner), 'queue'), payload)
        if verb in EXTRA_VERBS:
            data = extra_view(m, db, p, owner, verb, args, values, name)
            db.commit()
            return _reply(data, payload)
        if verb == 'qd':
            text = m.task_queue.status(m, db, p, db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)), detail=True)
            return _reply(message(m, text, queue_components(m, db, p, owner)[:1], 'queue'), payload)
        if verb == 'st':
            return _reply(message(m, qol.status_text(m, db, p), status_components(m, db, p, owner), 'status'), payload)
        if verb in {'mn', 'mv', 'mk', 'mp', 'ma'}:
            from . import menu
            data = menu.navigate(m, db, p, owner, verb, args, values, name)
            db.commit()
            return _reply(data, payload) if data is not None else _notice('This control is no longer available. Open /menu again.')
        if verb == 'lp':
            from . import autonomy
            note = ''
            if len(args) == 1 and values:
                note = autonomy.set_phase(db, p, args[0], values[0]) + '\n'
                db.commit()
            return _reply(schedule_editor(m, db, p, owner, note), payload)
        if verb == 'cn':
            qol.clear_next(db, p.channel_id, p.twitch_uid)
            db.commit()
            text = m.task_queue.status(m, db, p, db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)))
            return _reply(message(m, '⏭️ Next queue cleared.\n\n' + text, queue_components(m, db, p, owner), 'queue'), payload)
        if verb == 'fv':
            e = wb.entry(m, args[0])
            if e is None:
                return _notice('That recipe is no longer available. Open /make again.')
            note = qol.set_favorite(m, db, p, e.id, args[1] == '1')
            db.commit()
            ctx = wb.Context(m, db, p)
            category, page, station = (args[2] if len(args) > 2 else ''), int(args[3] or 1) if len(args) > 3 else 1, wb.station_from_code(args[4]) if len(args) > 4 and args[4] else ''
            text = note + '\n\n' + wb.preview_text(ctx, e)
            return _reply(message(m, text, recipe_components(m, ctx, owner, e, category, page, station)), payload)
        if verb == 'fm':
            e = wb.entry(m, args[0])
            if e is None:
                return _notice('That recipe is no longer available. Open /make again.')
            batches = max(1, min(10, int(args[1] if len(args) > 1 else 1)))
            text, start = qol.fetch_plan(ctx, e, batches)
            return _reply(message(m, text, fetch_components(m, ctx, owner, e, batches, start)), payload)
    return _notice('This control is no longer available. Run the command again.')


def run_ticket(m, uid, name, action, payload=None):
    """Perform one claimed action and return the updated panel."""
    channel = m.DISCORD_WORLD_ID
    kind = action.get('do')
    with ticket_batch(m):
        with m.task_queue.atomic(m, channel):
            data = _run(m, uid, name, action, kind, channel)
    if not isinstance(data, dict):
        return data
    if action.get('goal'):
        data = with_goal_button(data, uid)
    elif action.get('shop'):
        data = with_goal_button(data, uid, 'lv', 'Shopping list', '🛒')
    return with_menu(data)


def _run(m, uid, name, action, kind, channel):
    if kind == 'cmd':
        from . import menu
        return menu.run(m, uid, name, action)
    if kind in EXTRA_TICKETS:
        return extra_ticket(m, uid, name, action, kind, channel)
    if kind == 'craft':
        result = m.make(channel, uid, name, action['recipe'], 'discord', action='craft').body.decode()
    elif kind == 'queue':
        result = m.queued_tasks(channel, uid, name, 'start', action['task'], action['count'], 'discord').body.decode()
        follow = action.get('then')
        if follow and result.startswith('TASK QUEUE'):
            result = m.queued_tasks(channel, uid, name, 'next', follow['task'], follow['count'], 'discord').body.decode()
    elif kind == 'next':
        result = m.queued_tasks(channel, uid, name, 'next', action['task'], action['count'], 'discord').body.decode()
    elif kind == 'recover':
        result = m.recover_needs(channel, uid, name, 'discord').body.decode()
    elif kind == 'buy':
        with m.SessionLocal() as db:
            p = _player(m, db, uid, name)
            e = wb.entry(m, action['recipe'])
            result = qol.buy_missing(m, db, p, e, int(action.get('batches') or 1)) if e else 'That recipe is no longer available. Nothing spent.'
    elif kind == 'clearout':
        result = m.clearout(channel, uid, name, 'confirm', 'discord').body.decode()
    elif kind == 'cancel':
        result = m.queued_tasks(channel, uid, name, 'cancel', '', 1, 'discord').body.decode()
    elif kind == 'gather':
        result = m.seed_supplies(channel, uid, name, 'gather', action['item'], 1, False, 'discord').body.decode()
    elif kind == 'unlock':
        result = m.workshop(channel, uid, name, 'unlock', action['station'], 1, 'discord').body.decode()
    elif kind == 'train':
        result = m.training(channel, uid, name, action['skill'], action['task'], 'discord').body.decode()
    else:
        result = 'This button is no longer supported. Nothing was spent.'
    with m.SessionLocal() as db:
        p = _player(m, db, uid, name)
        ctx = wb.Context(m, db, p)
        if kind == 'craft':
            e = wb.entry(m, action['recipe'])
            components = after_craft_components(m, ctx, uid, e, list(action.get('back') or []))
        elif kind == 'unlock':
            e = wb.entry(m, action['recipe'])
            category, page, st = (list(action.get('back') or []) + ['', 1, ''])[:3]
            result = result + '\n\n' + wb.preview_text(ctx, e)
            components = recipe_components(m, ctx, uid, e, category, page, wb.station_from_code(st) if st != '' else '')
        elif kind == 'gather':
            components = work_components(m, uid, 'gather:' + action['item'])
        elif kind == 'buy':
            e = wb.entry(m, action['recipe'])
            result = result + '\n\n' + wb.preview_text(ctx, e)
            components = recipe_components(m, ctx, uid, e)
        elif kind == 'clearout':
            components = [row(button('Undo sale (60s)', cid(uid, 't', issue(m, uid, {'do': 'undo'})), style=4, emoji='↩️'))] + status_components(m, db, p, uid)[:1]
        elif kind == 'recover':
            components = status_components(m, db, p, uid)
        elif kind == 'train':
            again = issue(m, uid, {'do': 'train', 'skill': action['skill'], 'task': action['task']})
            tasks = pick_button(cid(uid, 'mp', 'trainskill'), action['skill'], 'Tasks')
            if tasks:
                tasks['emoji'] = {'name': '🎯'}
            components = [row(button('Again', cid(uid, 't', again), style=3, emoji='🔁'), tasks,
                              button('Menu', cid(uid, 'mn', 'home'), emoji='🏠'))]
        else:
            components = queue_components(m, db, p, uid)
        db.commit()
    return message(m, result, components, 'queue' if kind in {'queue', 'cancel', 'next'} else 'make')


def finish_ticket(m, payload, uid, name, action):
    origin = m.task_queue.queue_notifications.origin_channel
    token = origin.set(str(payload.get('channel_id') or ''))
    INTERACTION.set(payload)
    try:
        data = run_ticket(m, uid, name, action, payload)
    except Exception:
        import logging
        logging.getLogger(__name__).error('Workbench button action rolled back: %s', action.get('do'))
        data = {'content': 'This action could not be completed and nothing was spent. Open the menu again for a fresh button.',
                'embeds': [], 'components': [], 'allowed_mentions': {'parse': []}}
    finally:
        origin.reset(token)
    m.discord_deferred.edit_original(str(payload['application_id']), str(payload['token']), tidy(data))
    kind = action.get('do')
    command = 'queue' if kind in {'queue', 'next', 'cancel'} else (m.menu.options_for(action['leaf'])[0] if kind == 'cmd' and 'leaf' in action else '')
    _popups(m, payload, uid, command, json.dumps(data, ensure_ascii=False))


def _popups(m, payload, uid, command='', text=''):
    """Raise any warnings or tips from this interaction, then show waiting notifications privately."""
    try:
        if command or text:
            m.inbox.after_command(m, uid, 'Citizen', command, {}, text)
        m.inbox.deliver(m, payload, uid)
    except Exception:
        import logging
        logging.getLogger(__name__).error('Private notifications could not be delivered after a button')


# ---------------------------------------------------------------- pop-up forms (modals)

def text_box(custom_id, label, placeholder='', min_length=1, max_length=60, value='', required=True):
    """One text box of a pop-up form, in its own row."""
    field = {'type': 4, 'custom_id': custom_id, 'label': wb.clip(label, 45), 'style': 1, 'min_length': min_length if required else 0,
             'max_length': max_length, 'required': required}
    if placeholder:
        field['placeholder'] = wb.clip(placeholder, 100)
    if value:
        field['value'] = str(value)[:max_length]
    return {'type': 1, 'components': [field]}


def modal(custom_id, title, label, placeholder='', min_length=1, max_length=60, value='', more=()):
    """A Discord pop-up form with one text box (response type 9), and the `more` boxes (text_box) under it."""
    boxes = [text_box('value', label, placeholder, min_length, max_length, value)] + list(more)
    return {'type': 9, 'data': {'custom_id': custom_id, 'title': wb.clip(title, 45), 'components': boxes}}


def modal_fields(payload):
    """Every text box of a submitted form: {custom_id: text}."""
    return {str(component.get('custom_id')): str(component.get('value') or '').strip()
            for component_row in (payload.get('data') or {}).get('components') or []
            for component in component_row.get('components') or [] if component.get('custom_id')}


def modal_value(payload, field='value'):
    return modal_fields(payload).get(field, '')


def handle_modal(m, payload, schedule=None):
    """Answer a submitted pop-up form: a search shows results; an action runs once."""
    parts = str((payload.get('data') or {}).get('custom_id') or '').split('|')
    uid, name = _user(payload)
    if len(parts) < 4 or parts[0] != 'ne' or parts[2] != 'md':
        return _notice('This form is no longer available. Open /menu again.')
    owner, key, args = parts[1], parts[3], parts[4:]
    INTERACTION.set(payload)
    if owner not in {uid, PUBLIC}:
        return _notice('This form belongs to another citizen. Nothing was spent.')
    value = modal_value(payload)
    if not value:
        return _notice('Nothing was entered. Nothing was spent.')
    from . import menu
    with ticket_batch(m):
        with m.SessionLocal() as db:
            p = _player(m, db, uid, name)
            result = menu.submit(m, db, p, uid, name, key, args, value, modal_fields(payload))
            db.commit()
    if result is None:
        return _notice('This form is no longer available. Open /menu again.')
    _left_screen(payload, owner if owner != PUBLIC else uid)
    if 'do' in result:
        # Spending forms (link, start a business, buy an amount) run like a one-time button.
        if schedule is None:
            return _reply(run_ticket(m, uid, name, result, payload), payload)
        schedule(finish_ticket, m, payload, uid, name, result)
        return {'type': 6}
    return _reply(result, payload)


# ---------------------------------------------------------------- public game panel

def public_panel(m):
    """A message anyone can press: every button opens that citizen's own private menu."""
    from . import menu
    text = ('🌱 NEW ERIDIAN — PLAY WITH BUTTONS\n'
            'Press any button to open your own private menu. Nobody else sees it, and nothing is spent until you press an action.\n\n'
            '🏠 **Menu** — every part of the game, starting with your next step\n📊 **Status** — needs, queue and what to do next\n'
            '⛏️ **Work** — gather, mine, train and run queues\n🛠️ **Craft** — your goal walks you through it; every recipe\n'
            '❤️ **Life** — relax, sleep, eat, recover\n🪙 **Bag & Trade** — what you own, buying and selling\n'
            '🎪 **Colony** — events, the vote, the season and trophies\n👤 **You** — your citizen, Seedling and settings\n'
            '🔎 **Find** — search anything\n🔗 **Account** — start or link Twitch\n\n'
            'ℹ️ A free, unofficial fan project by Kamex. Not affiliated with Klang Games, the makers of SEED.')
    rows = [row(button('Menu', cid(PUBLIC, 'mn', 'home'), style=1, emoji='🏠'), button('Status', cid(PUBLIC, 'st'), style=1, emoji='📊'),
                button('Work', cid(PUBLIC, 'mn', 'work'), emoji='⛏️'), button('Craft', cid(PUBLIC, 'mn', 'craft'), emoji='🛠️'),
                button('Life', cid(PUBLIC, 'mn', 'life'), emoji='❤️')),
            row(button('Bag & Trade', cid(PUBLIC, 'mn', 'trade'), emoji='🪙'), button('Colony', cid(PUBLIC, 'mn', 'community'), emoji='🎪'),
                button('You', cid(PUBLIC, 'mn', 'me'), emoji='👤'), button('Find', cid(PUBLIC, 'mo', 'find'), emoji='🔎'),
                button('Account', cid(PUBLIC, 'mn', 'account'), emoji='🔗'))]
    items = [{'match': f"**{b['label']}**", 'button': {k: v for k, v in b.items() if k != 'emoji'}}
             for r in rows for b in r['components']]
    return message(m, text, rows, 'menu', items)


def post_public_panel(m, channel_id, token=None):
    """Post the public game panel as the bot. Returns True when Discord accepted it."""
    import os
    import requests
    token = (token or os.getenv('DISCORD_BOT_TOKEN', '')).strip()
    if not token or not str(channel_id).isdigit():
        return False
    from . import layout_v2
    data = layout_v2.new_message(public_panel(m))     # each button beside its line, in the newer layout
    try:
        response = requests.post(f'https://discord.com/api/v10/channels/{channel_id}/messages', headers={'Authorization': 'Bot ' + token},
                                 json=dict(data, allowed_mentions={'parse': []}), timeout=10)
    except requests.RequestException:
        return False
    return 200 <= response.status_code < 300


# ---------------------------------------------------------------- goal, plans, auto-sell, uses, find, recent (see extras.py)

EXTRA_VERBS = {'gv', 'gs', 'gc', 'pv', 'pc', 'rd', 'av', 'at', 'kv', 'ki', 'ks', 'fu', 'fi', 'fd', 'lv', 'li', 'ls', 'la', 'lx', 'qo'}
EXTRA_TICKETS = {'plan', 'sellstep', 'saveroutine', 'routine', 'undo', 'buyitem', 'restock', 'shopbuy'}


def _menu_row(owner, back=None):
    """◀️ Back (else up to `back`'s area) and 🏠 Menu."""
    return row(back_button(owner, 'mn', back[0]) if back else back_button(owner), button('Menu', cid(owner, 'mn', 'home'), emoji='🏠'))


def step_button(m, owner, step, first=False):
    """A goal step's button: a one-time ticket that does it (green), or the screen where it is done."""
    label = step['label'] or 'Open'
    if step['action'] is not None:
        return button(label, cid(owner, 't', issue(m, owner, dict(step['action'], goal=True))), style=3)
    if step['view']:
        return button(label, cid(owner, *step['view']), style=1 if first else 2)
    return None


def goal_message(m, db, p, owner, note=''):
    """The goal walkthrough: every step still needed, each with its button (beside it in the newer layout)."""
    from . import extras as more
    text = more.goal_text(m, db, p)
    if note:
        head, _, rest = text.partition('\n')
        text = head + '\n' + note + rest
    e, steps = more.walkthrough(m, db, p)
    if e is None:
        return message(m, text, goal_components(m, db, p, owner), 'goal')
    buttons, items, used = [], [], set()
    for i, st in enumerate(steps[:more.STEPS_SHOWN]):
        b = step_button(m, owner, st, first=i == 0)
        if b is not None and b['custom_id'] not in used:      # two steps that open the same list share one button
            used.add(b['custom_id'])
            buttons.append(b)
            items.append({'match': st['name'], 'button': b})
    recipe = ('wr', e.id, e.category, 1, '')
    tools = [button('Refresh', cid(owner, 'gv'), emoji='🔄'), button('Clear goal', cid(owner, 'gc'), style=4, emoji='✖️')]
    if not any(st['view'] == recipe for st in steps[:more.STEPS_SHOWN]):
        tools.insert(0, button('Goal recipe', cid(owner, *recipe), emoji='📋'))
    rows = [row(*buttons[i:i + 5]) for i in range(0, min(len(buttons), 10), 5)] + [row(*tools), _menu_row(owner, ('craft', 'Craft'))]
    from .menu import crumb
    return with_crumb(message(m, text, rows, 'goal', items), crumb('craft', '🎯 Goal'))


def with_goal_button(data, owner, verb='gv', label='Goal', emoji='🎯'):
    """Add 🎯 Goal (or another screen: 🛒 Shopping list) to a result reached from it, so the next step is one press away."""
    goal = cid(owner, verb)
    rows = [r for r in data.get('components') or [] if r and r.get('components')]
    if any(c.get('custom_id') == goal for r in rows for c in r['components']):
        return data
    back = button(label, goal, style=1, emoji=emoji)
    if rows and len(rows[-1]['components']) < 5 and all(c.get('type') == 2 for c in rows[-1]['components']):
        rows[-1] = dict(rows[-1], components=[back] + rows[-1]['components'])
    elif len(rows) < 5:
        rows.append(row(back))
    data['components'] = rows
    return data


def goal_components(m, db, p, owner):
    from . import extras as more
    e = more.goal_entry(m, db, p)
    if e is None:
        return [row(button('Ready now', cid(owner, 'wc', 'ready', 1, ''), emoji='✅'), button('Workbench', cid(owner, 'wh'), emoji='🛠️')),
                _menu_row(owner, ('craft', 'Craft'))]
    step, action = more.next_step(m, db, p)
    buttons = []
    if action is not None:
        buttons.append(button(wb.clip('Fetch next: ' + step, 80), cid(owner, 't', issue(m, owner, action)), style=3, emoji='▶️'))
    buttons += [button('Goal recipe', cid(owner, 'wr', e.id, e.category, 1, ''), emoji='📋'),
                button('Refresh', cid(owner, 'gv'), emoji='🔄'), button('Clear goal', cid(owner, 'gc'), style=4, emoji='✖️')]
    return [row(*buttons), _menu_row(owner, ('craft', 'Craft'))]


def plan_components(m, db, p, owner):
    from . import extras as more
    rows = []
    saved = more.routines(db, p)
    if saved:
        rows.append(row(*[button(f'Start #{i}', cid(owner, 't', issue(m, owner, {'do': 'routine', 'id': r.id})), style=3, emoji='▶️')
                          for i, r in enumerate(saved, 1)]))
        rows.append(row(*[button(f'Delete #{i}', cid(owner, 'rd', r.id), style=4, emoji='🗑️') for i, r in enumerate(saved, 1)]))
    rows.append(row(button('Save plan as routine', cid(owner, 't', issue(m, owner, {'do': 'saveroutine'})), style=1, emoji='💾'),
                    button('Clear plan', cid(owner, 'pc'), style=4, emoji='✖️'),
                    button('Queue status', cid(owner, 'qv'), emoji='📋')))
    rows.append(_menu_row(owner, ('queue', 'Queue')))
    return rows


def autosell_components(m, db, p, owner):
    from . import extras as more
    chosen = set(more.autosell_list(db, p))
    stock = m.seed_content.stock(m, db, p)
    keys = sorted({k for k, n in stock.items() if n > 0 and m.qol.sell_price(m, k)} | chosen, key=m.resource_name)[:25]
    rows = []
    if keys:
        rows.append(select(cid(owner, 'at'), 'Add or remove an item',
                           [option(('✅ ' if k in chosen else '') + m.resource_name(k), k, 'currently sold automatically' if k in chosen else
                                   f'you have {stock.get(k, 0)} · sells {m.qol.sell_price(m, k)} SC each') for k in keys]))
    rows.append(_menu_row(owner, ('bag', 'Bag')))
    return rows


def restock_button(m, p, owner, r):
    """Restock one short item (a one-time ticket); greyed out when the purchase costs more SC than you have. When a gate
    blocks it (keep_levels.shortfalls), the screen that fixes it instead: Fetch missing, or the recipe with its Unlock,
    spending nothing. None when nothing here helps (the screen says why or where it comes from)."""
    if r['kind'] == 'none':
        return None
    if r['blocked']:
        if not r['view']:
            return None
        if r['view'][0] == 'fm':
            return button(f"Fetch for {r['name']}", cid(owner, *r['view']), emoji='🧺')
        return button(f"{r['recipe_name']} recipe", cid(owner, *r['view']), emoji='📋')
    label = f"Restock {r['name']}"
    if r['kind'] == 'buy':
        cost = r['price'] * r['short']
        if p.sc < cost:
            return button(f'{label} · {cost} SC', cid(owner, 'ki', r['key']), disabled=True, emoji='🛡️')
        label += f' · {cost} SC'
    return button(label, cid(owner, 't', issue(m, owner, {'do': 'restock', 'item': r['key']})), style=3, emoji='🛡️')


def keep_message(m, db, p, owner, note=''):
    """Keep levels: each level with what you have, a dropdown of your items, and Restock beside each short item."""
    from . import keep_levels as keep
    from .menu import crumb
    kept = keep.levels(db, p.channel_id, p.twitch_uid)
    stock = s.stock(m, db, p)
    owned = sorted((k for k, n in stock.items() if n > 0 and k in s.ACTIVE and k not in kept), key=lambda k: (-stock[k], m.resource_name(k)))
    keys = (sorted(kept, key=lambda k: m.resource_name(k).casefold()) + owned)[:25]
    rows = []
    if not keys:
        note = (note + '\n' if note else '') + 'You own nothing yet: gather, mine or buy something, then choose it here.'
    else:
        rows.append(select(cid(owner, 'ki'), 'Choose an item to keep…',
                           [option(m.resource_name(k), k, f'have {stock.get(k, 0)} · keep {kept[k]}' if k in kept else
                                   f'have {stock.get(k, 0)} · no keep level', emoji='🛡️' if k in kept else None) for k in keys]))
    buttons, items = [], []
    for r in keep.shortfalls(m, db, p)[:10]:
        b = restock_button(m, p, owner, r)
        if b is not None:
            buttons.append(b)
            items.append({'match': f"⚠️ {r['name']} — have", 'button': b})
    rows += [row(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]
    rows.append(_menu_row(owner, ('bag', 'Bag')))
    return with_crumb(message(m, keep.screen_text(m, db, p, note), rows, 'inventory', items), crumb('bag', 'Keep levels'))


def keep_item_message(m, db, p, owner, key, note=''):
    """One item's keep level: quick amounts, Custom…, Remove and Restock. Setting a level spends nothing, so no tickets."""
    from . import keep_levels as keep
    from .menu import crumb
    key = m.item_identity.canonical(str(key or ''))
    if key not in s.ACTIVE:
        return keep_message(m, db, p, owner, '🛡️ Choose an item from the list. Nothing changed.')
    current = keep.keep_for(m, db, p, key)
    have = m.material_amount(db, p, key)
    amounts = [(n, f'Keep {n}') for n in keep.QUICK]
    if 0 < have <= keep.MAX_AMOUNT and have not in keep.QUICK:
        amounts.append((have, f'Keep {have} (all you have)'))
    first = [button(label, cid(owner, 'ks', key, n), style=1 if n == current else 2, emoji='🛡️') for n, label in amounts]
    second = [button('Custom…', cid(owner, 'mo', 'keep', key), emoji='✏️')]
    if current:
        second.append(button('Remove', cid(owner, 'ks', key, 0), style=4, emoji='✖️'))
    short = next((r for r in keep.shortfalls(m, db, p) if r['key'] == key), None)
    if short is not None:
        second.append(restock_button(m, p, owner, short))
    rows = [row(*first), row(*second), row(back_button(owner, 'kv'), button('Menu', cid(owner, 'mn', 'home'), emoji='🏠'))]
    return with_crumb(message(m, keep.item_text(m, db, p, key, note), rows, 'inventory'), crumb('bag', 'Keep levels › ' + m.resource_name(key)))


def quiet_form(m, owner):
    """The quiet-hours pop-up form: time zone, start and end, filled in with the current setting."""
    from . import quiet_hours as quiet, inbox
    tz = start = end = ''
    if m is not None:
        with m.SessionLocal() as db:
            r = quiet.row(db, m.DISCORD_WORLD_ID, inbox._canonical(m, db, owner))
            if r is not None:
                tz, start, end = r.tz, quiet.clock(r.start_min), quiet.clock(r.end_min)
    return modal(cid(owner, 'md', 'quiet'), 'Quiet hours', 'Time zone (e.g. Europe/London or UTC+2)', 'e.g. Europe/London', 1, 48, tz,
                 more=[text_box('start', 'Start (24-hour clock: HH or HH:MM)', 'e.g. 23:00', 1, 5, start),
                       text_box('end', 'End (24-hour clock: HH or HH:MM)', 'e.g. 08:00', 1, 5, end)])


def quiet_message(m, db, p, owner, note=''):
    """Settings after a quiet-hours change: what changed, every setting, and the Settings buttons (Quiet hours, Turn off…)."""
    from . import menu
    head, _, rest = qol.settings_text(m, db, p, 'discord').partition('\n')
    text = head + ('\n' + note if note else '') + '\n' + rest
    rows = menu.grid(m, owner, menu.children_of(m, 'settings', menu.context(m, owner, db, p)), rows=3) + [menu.nav(owner, 'settings', 'settings')]
    return with_crumb(message(m, text, rows, 'settings'), menu.crumb('settings', '🌙 Quiet hours'))


def shopping_entry_button(owner, x):
    """A shopping-list entry's button: change or remove it (the citizen's own setting, so no ticket); Remove for a
    recipe no longer in the catalog."""
    if x.entry is None:
        return button(f'Remove {x.recipe_id}', cid(owner, 'ls', x.recipe_id, 0), style=4, emoji='✖️')
    return button(f'{x.name} ×{x.want}', cid(owner, 'li', x.recipe_id), emoji='✅' if x.done else '✏️')


def shopping_message(m, db, p, owner, note=''):
    """The shopping list: each entry with its button beside it, the combined materials, the first steps, and Fetch next,
    Buy all missing (a one-time ticket, greyed out with its price when you cannot afford it), Add recipe…, Clear done
    and Clear list."""
    from . import shopping_list as shop
    from .menu import crumb
    info = shop.overview(m, db, p)
    buttons, items = [], []
    for x in info.items:
        b = shopping_entry_button(owner, x)
        buttons.append(b)
        items.append({'match': shop.entry_match(x), 'button': dict(b, label='Remove' if x.entry is None else 'Change')})
    rows = [row(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]
    tools = []
    if info.steps:
        first = info.steps[0]
        label = wb.clip('Fetch next: ' + shop.step_text(first), 80)
        if first['action'] is not None:
            tools.append(button(label, cid(owner, 't', issue(m, owner, dict(first['action'], shop=True))), style=3, emoji='▶️'))
        elif first['view']:
            tools.append(button(label, cid(owner, *first['view']), style=1, emoji='▶️'))
    if info.cost:
        label = f'Buy all missing · {info.cost} SC'
        tools.append(button(label, cid(owner, 't', issue(m, owner, {'do': 'shopbuy'})), style=3, emoji='🪙') if p.sc >= info.cost
                     else button(label, cid(owner, 'lv', 'buy'), disabled=True, emoji='🪙'))
    full = len(info.items) >= shop.MAX_ENTRIES
    tools.append(button(f'List full ({shop.MAX_ENTRIES})' if full else 'Add recipe…', cid(owner, 'mo', 'shopping'), disabled=full, emoji='➕'))
    if any(x.done for x in info.items):
        tools.append(button('Clear done', cid(owner, 'lx', 'done'), emoji='🧹'))
    if info.items:
        tools.append(button('Clear list', cid(owner, 'lx', 'all'), style=4, emoji='✖️'))
    rows += [row(*tools), row(button('Refresh', cid(owner, 'lv'), emoji='🔄'), *_menu_row(owner, ('craft', 'Craft'))['components'])]
    return with_crumb(message(m, shop.screen_text(m, db, p, note, info), rows, 'goal', items), crumb('craft', '🛒 Shopping list'))


def shopping_item_message(m, db, p, owner, recipe_id, note=''):
    """One entry: how many to have (one, two, five or ten batches), Custom…, Remove, its recipe and the list. Changing the
    list spends nothing, so no tickets."""
    from . import shopping_list as shop
    from .menu import crumb
    e = wb.entry(m, recipe_id)
    if e is None:
        return shopping_message(m, db, p, owner, '🛒 That recipe is no longer available: remove it from the list. Nothing changed.')
    per = max(1, wb.Context(m, db, p).batch_size(e))
    listed = db.get(shop.ShoppingEntry, (p.channel_id, p.twitch_uid, e.id))
    amounts = [1] if shop._unique(m, e) else list(dict.fromkeys(min(shop.MAX_WANT, per * k) for k in (1, 2, 5, 10)))
    first = [button(f'Want {n}' + (' (1 batch)' if n == per and per > 1 else ''), cid(owner, 'ls', e.id, n),
                    style=1 if listed is not None and n == listed.want else 2, emoji='🛒') for n in amounts]
    second = [button('Custom…', cid(owner, 'mo', 'shopping', e.id), emoji='✏️')]
    if listed is not None:
        second.append(button('Remove', cid(owner, 'ls', e.id, 0), style=4, emoji='✖️'))
    second += [button('Recipe', cid(owner, 'wr', e.id, e.category, 1, ''), emoji='📋'), button('Shopping list', cid(owner, 'lv'), style=1, emoji='🛒')]
    rows = [row(*first), row(*second), row(back_button(owner, 'lv'), button('Menu', cid(owner, 'mn', 'home'), emoji='🏠'))]
    return with_crumb(message(m, shop.item_text(m, db, p, e.id, note), rows, 'goal'), crumb('craft', '🛒 Shopping list › ' + e.name))


def uses_components(owner, rows_):
    buttons = [button(wb.clip(e.name, 80), cid(owner, 'wr', e.id, e.category, 1, ''), emoji='📋') for e in rows_[:5]]
    return ([row(*buttons)] if buttons else []) + [_menu_row(owner, ('bag', 'Bag'))]


def recent_components(m, db, p, owner):
    from . import extras as more
    actions = more.recent(db, p.channel_id, p.twitch_uid)
    buttons = [button(wb.clip(a.label, 80), cid(owner, 't', issue(m, owner, {'do': 'cmd', 'raw': [a.command, json.loads(a.options)]})), style=3, emoji='🔁')
               for a in actions]
    return [row(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)] + [_menu_row(owner)]


def find_components(m, owner, query):
    from . import extras as more, menu
    found = more.find(m, query)
    buttons = [button(wb.clip(e.name, 80), cid(owner, 'wr', e.id, e.category, 1, ''), emoji='📋') for e in found['recipes'][:3]]
    shown = {e.name for e in found['recipes'][:3]}
    buttons += [button(wb.clip(m.seed_content.ITEMS[k]['name'], 80), cid(owner, 'fi', k), emoji='📦')
                for k in found['items'] if m.seed_content.ITEMS[k]['name'] not in shown][:2]
    nav = [menu._button(m, owner, k) for k in found['menu'][:4]]
    nav += [button('Handbook: ' + t, cid(owner, 'mv', 'h_' + t), emoji='📖') for t in found['topics'][:1]]
    return [r for r in (row(*buttons[:5]), row(*nav[:5]), _menu_row(owner)) if r['components']]


def seedling_components(m, db, p, owner):
    from . import autonomy
    found = autonomy.row(db, p.channel_id, p.twitch_uid, create=True)
    toggle = ({'do': 'cmd', 'leaf': 'sl_off'}, 'Autonomy off', '✋', 4) if found.enabled else ({'do': 'cmd', 'leaf': 'sl_on'}, 'Autonomy on', '🌱', 3)
    return [row(button('Let it decide', cid(owner, 't', issue(m, owner, {'do': 'cmd', 'leaf': 'sl_decide'})), style=3, emoji='🎲'),
                button('Diary', cid(owner, 'mv', 'sl_diary'), emoji='📓'), button('Schedule', cid(owner, 'lp'), emoji='🗓️'),
                button(toggle[1], cid(owner, 't', issue(m, owner, toggle[0])), style=toggle[3], emoji=toggle[2])),
            row(button('Refresh', cid(owner, 'mv', 'sl_view'), emoji='🔄'), button('Menu', cid(owner, 'mn', 'home'), emoji='🏠'))]


def schedule_editor(m, db, p, owner, note=''):
    """One dropdown per Avesta phase: Work, Free time, Social or Sleep."""
    from . import autonomy
    found = autonomy.row(db, p.channel_id, p.twitch_uid, create=True)
    blocks = autonomy.schedule_of(found)
    clock = m.world_clock(db, p.channel_id)
    hours = {'Morning': '0–6', 'Day': '6–15', 'Evening': '15–19', 'Night': '19–24'}
    text = ('🗓️ SCHEDULE\n' + note + f"Current: **{autonomy.preset_name(found)}**. An Avesta day lasts {round(m.AVESTA_DAY_SECONDS / 3600, 1)} real hours; "
            f"it is {clock['phase']} now.\nNeeds come first: a hungry or exhausted Seedling eats or sleeps whatever the schedule says.\n\n"
            + '\n'.join(f"{ph} ({hours[ph]}h): {autonomy.BLOCKS[b][0]} **{autonomy.BLOCKS[b][1]}**" for ph, b in blocks.items()))
    rows = [select(cid(owner, 'lp', ph), f'{ph}: {autonomy.BLOCKS[b][1]}',
                   [option(label, key, emoji=emoji, default=key == b) for key, (emoji, label) in autonomy.BLOCKS.items()])
            for ph, b in blocks.items()]
    return message(m, text, rows + [row(back_button(owner, 'mn', 'seedling'),
                                        button('Menu', cid(owner, 'mn', 'home'), emoji='🏠'))], 'seedling')


def item_text(m, db, p, key):
    s_ = m.seed_content
    name = s_.ITEMS[key]['name'] if key in s_.ITEMS else m.resource_name(key)
    have = m.material_amount(db, p, key)
    price = m.qol.sell_price(m, key)
    lines = [f'📦 {name.upper()}', s_.ITEMS.get(key, {}).get('description', ''), '',
             f'**You have:** {have}', f'**Get it:** {m.material_source(key)}',
             f"**Use:** {s_.PURPOSE[key]['label']}" if key in s_.PURPOSE else '',
             f'**Sells for:** {price} SC each' if price else '']
    return '\n'.join(x for x in lines if x is not None)


def extra_view(m, db, p, owner, verb, args, values, name):
    from . import extras as more
    if verb in {'gv', 'gs', 'gc'}:
        note = ''
        if verb == 'gs':
            note = more.set_goal(m, db, p, args[0] if args else '') + '\n\n'
        if verb == 'gc':
            more.clear_goal(db, p)
            note = '🎯 Goal cleared.\n\n'
        db.flush()
        return goal_message(m, db, p, owner, note)
    if verb in {'pv', 'pc', 'rd'}:
        note = ''
        if verb == 'pc':
            more.clear_plan(db, p)
            note = '✖️ Plan cleared (the running queue continues).\n'
        if verb == 'rd':
            note = '🗑️ Routine deleted.\n' if more.delete_routine(db, p, args[0]) else ''
        db.flush()
        text = more.plan_text(m, db, p)
        return message(m, text.split('\n', 1)[0] + '\n' + note + text.split('\n', 1)[1], plan_components(m, db, p, owner), 'queue')
    if verb in {'av', 'at'}:
        note = more.toggle_autosell(m, db, p, values[0]) + '\n' if verb == 'at' and values else ''
        db.flush()
        text = more.autosell_text(m, db, p)
        return message(m, text.split('\n', 1)[0] + '\n' + note + text.split('\n', 1)[1], autosell_components(m, db, p, owner), 'inventory')
    if verb == 'ks':
        from . import keep_levels as keep
        note = keep.set_level(m, db, p, args[0] if args else '', args[1] if len(args) > 1 else '')
        db.flush()
        return keep_message(m, db, p, owner, note)
    if verb == 'ki':
        return keep_item_message(m, db, p, owner, values[0] if values else (args[0] if args else ''))
    if verb == 'kv':
        return keep_message(m, db, p, owner)
    if verb in {'lv', 'ls', 'lx'}:
        from . import shopping_list as shop
        note = ''
        if verb == 'ls':
            note = shop.set_entry(m, db, p, args[0] if args else '', args[1] if len(args) > 1 else '')
        if verb == 'lx':
            note = shop.clear(m, db, p, done_only=(args[0] if args else '') == 'done')
        db.flush()
        return shopping_message(m, db, p, owner, note)
    if verb == 'li':
        return shopping_item_message(m, db, p, owner, args[0] if args else '')
    if verb == 'qo':
        from . import quiet_hours
        note = quiet_hours.turn_off(m, db, p)
        db.flush()
        return quiet_message(m, db, p, owner, note)
    if verb == 'la':
        from . import shopping_list as shop
        recipe = args[0] if args else ''
        if db.get(shop.ShoppingEntry, (p.channel_id, p.twitch_uid, recipe)) is not None:
            return shopping_item_message(m, db, p, owner, recipe, '🛒 Already on your shopping list.')
        note = shop.set_entry(m, db, p, recipe)
        db.flush()
        if not note.startswith('🛒 Added'):
            return shopping_message(m, db, p, owner, note)
        return shopping_item_message(m, db, p, owner, recipe, note + ' Choose how many you want to have.')
    if verb == 'fu':
        text, rows_ = more.uses_text(m, db, p, args[0])
        return message(m, text, uses_components(owner, rows_), 'catalog')
    if verb == 'fi':
        key = args[0]
        return message(m, item_text(m, db, p, key), [row(button('What can I make with it?', cid(owner, 'fu', key), emoji='🔍')), _menu_row(owner)], 'catalog')
    if verb == 'fd':
        query = values[0] if values else (args[0] if args else '')
        return message(m, more.find_text(m, query), find_components(m, owner, query), 'find')
    return _notice('This control is no longer available.')['data']


def extra_ticket(m, uid, name, action, kind, channel):
    from . import extras as more
    with m.SessionLocal() as db:
        p = _player(m, db, uid, name)
        if kind == 'plan':
            text = more.add_step(m, db, p, {'task': action['task'], 'count': action['count']})
            db.commit()
            return message(m, text + '\n\n' + more.plan_text(m, db, p), plan_components(m, db, p, uid), 'queue')
        if kind == 'sellstep':
            text = more.add_step(m, db, p, {'sell': action['item']})
            db.commit()
            return message(m, text + '\n\n' + more.plan_text(m, db, p), plan_components(m, db, p, uid), 'queue')
        if kind == 'saveroutine':
            text = more.save_routine(m, db, p)
            db.commit()
            return message(m, text + '\n\n' + more.plan_text(m, db, p), plan_components(m, db, p, uid), 'queue')
        if kind == 'undo':
            text = more.undo_sale(m, db, p)
            db.commit()
            return message(m, text, [_menu_row(uid, ('bag', 'Bag'))], 'sell')
        if kind == 'buyitem':
            amount = int(action.get('amount') or 1)
            lines = []
            while amount > 0:
                lines.append(m.seed_industries(channel, uid, name, 'buy', action['item'], min(25, amount), 'discord').body.decode())
                amount -= 25
            db.expire_all()
            return (shopping_message if action.get('shop') else goal_message)(m, db, p, uid, '\n'.join(lines) + '\n\n')
        if kind == 'shopbuy':
            from . import shopping_list as shop
            text = shop.buy_all(m, db, p, 'discord')
            db.commit()
            return shopping_message(m, db, p, uid, text)
    if kind == 'routine':
        text = more.start_routine(m, channel, uid, name, 'discord', action['id'])
        with m.SessionLocal() as db:
            p = _player(m, db, uid, name)
            return message(m, text, queue_components(m, db, p, uid) + [_menu_row(uid, ('queue', 'Queue'))], 'queue')
    if kind == 'restock':
        from . import keep_levels as keep
        text = keep.restock(m, channel, uid, name, 'discord', action['item'])
        return message(m, text, [row(button('Keep levels', cid(uid, 'kv'), style=1, emoji='🛡️'), button('Queue status', cid(uid, 'qv'), emoji='📋')),
                                 _menu_row(uid, ('bag', 'Bag'))], 'queue' if 'TASK QUEUE' in text else 'inventory')
    return message(m, 'This button is no longer supported. Nothing was spent.', [_menu_row(uid)])
