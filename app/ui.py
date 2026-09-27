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
  mn|mv|mk|mp             game menu areas, views and choices (see menu.py)
  t|<ticket>              one-time action

Category keys include the personal views 'ready' and 'favorites'. Setting a
favourite or clearing the next queue is idempotent, so neither needs a ticket.
"""
import copy
import json
import secrets
from datetime import timedelta
from sqlalchemy import Column, String, Text, DateTime, delete, update
from .db import Base
from . import workbench as wb, seed_content as s, qol

FOOTER = "New Eridian v2 • May Rocky's wisdom guide you."
TICKET_HOURS = 24
PANEL_COMMANDS = {'make', 'mine', 'gather', 'queue', 'status', 'seedindustries', 'menu'}


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


def issue(m, owner, action):
    """Create a one-time ticket for a spending button."""
    token = secrets.token_hex(16)
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


def message(m, text, components, command='make'):
    rows = [c for c in components if c and c.get('components')][:5]
    seen = set()
    for component_row in rows:
        for component in component_row['components']:
            # Discord rejects a message whose components repeat a custom_id.
            while component['custom_id'] in seen:
                component['custom_id'] = (component['custom_id'] + '|~')[:100]
            seen.add(component['custom_id'])
    return {'embeds': [embed_from_text(m, text, command)], 'components': rows, 'allowed_mentions': {'parse': []}}


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
        button('Back to list', cid(owner, 'wc', category, page, st), emoji='◀️'))
    amounts = select(cid(owner, 'sq', task), 'Queue a different number of batches (1–10)',
                     [option(f'Queue {n} batch' + ('es' if n > 1 else ''), n, f'Shows totals before starting · up to {n * ctx.batch_size(e)} {e.name}')
                      for n in range(1, 11)])
    starred = e.id in ctx.favorites
    extras = row(
        button('Unfavourite' if starred else 'Favourite', cid(owner, 'fv', e.id, 0 if starred else 1, category, page, st), emoji='☆' if starred else '⭐'),
        button('Fetch missing', cid(owner, 'fm', e.id, 1), style=1, emoji='🧺') if status.code == 'missing' else None,
        button('Status', cid(owner, 'st'), emoji='📊'))
    return [buttons, extras] + ([amounts] if status.code not in {'locked', 'owned'} else [])


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
        back = button('Back to recipe', cid(owner, 'wr', e.id, e.category, 1, ''), emoji='◀️')
    else:
        text = (f'⏱️ QUEUE {count} × {task_label(m, task).upper()}\n' + m.task_queue.requirements(m, db, p, task, count) +
                '\n\nPress Start to begin. The queue works one attempt every 10 seconds, pauses when a need or item runs short, and resumes by itself.')
        back = None
    current = db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)) if p is not None else None
    if current is not None and current.state in m.task_queue.ACTIVE:
        ticket = issue(m, owner, {'do': 'next', 'task': task, 'count': count})
        text += (f'\n\nYou already have a queue ({task_label(m, current.task)}). Press Queue next to run this one '
                 'automatically when it completes.')
        start = button(f'Queue next ×{count}', cid(owner, 't', ticket), style=3, emoji='⏭️')
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
                  button('Back to recipe', cid(owner, 'wr', e.id, e.category, 1, ''), emoji='◀️')]
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
    return [row(button(f'{verb} ×1', cid(owner, 't', ticket), style=3, emoji='⛏️' if kind == 'mine' else '🌿'),
                button('Queue 5', cid(owner, 'qp', task, 5), emoji='⏱️'),
                button('Queue 10', cid(owner, 'qp', task, 10), emoji='⏱️'),
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
                components = category_components(m, ctx, uid, category, page, station) if category else home_components(m, ctx, uid)
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
            return message(m, result, menu.area_components(m, uid, 'home'), command)
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


def _reply(data, payload, notice=False):
    """Update the panel in place when it is private; otherwise answer privately."""
    ephemeral = int((payload.get('message') or {}).get('flags', 0)) & 64
    if ephemeral and not notice:
        return {'type': 7, 'data': data}
    data = dict(data)
    data['flags'] = 64
    return {'type': 4, 'data': data}


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
    if uid != owner:
        return _notice('This menu belongs to another citizen. Open your own with the same command. Nothing was spent.')
    values = data.get('values') or []
    if verb == 'mp':
        from . import menu
        item = menu.LEAVES.get(args[0] if args else '')
        if item is not None and item.get('then') == 'do':
            # Choosing from an action list (a food, a hobby…) performs it, like a slash command.
            action = {'do': 'cmd', 'leaf': args[0], 'value': values[0] if values else ''}
            if schedule is None:
                return _reply(run_ticket(m, uid, name, action, payload), payload)
            schedule(finish_ticket, m, payload, uid, name, action)
            return {'type': 6}
    if verb == 't':
        with m.task_queue.atomic(m, m.DISCORD_WORLD_ID):
            action, reason = claim(m, owner, args[0] if args else '')
        if action is None:
            return _notice(reason)
        if schedule is None:
            return _reply(run_ticket(m, uid, name, action, payload), payload)
        schedule(finish_ticket, m, payload, uid, name, action)
        return {'type': 6}
    if schedule is not None:
        schedule(_popups, m, payload, uid)
    with m.task_queue.atomic(m, m.DISCORD_WORLD_ID):
        try:
            return _navigate(m, payload, uid, name, owner, verb, args, values)
        except (IndexError, KeyError, ValueError):
            # Malformed or outdated custom_id: navigation is read-only, so just say so.
            return _notice('This control is no longer available. Run the command again.')


def _navigate(m, payload, uid, name, owner, verb, args, values):
    with m.SessionLocal() as db:
        p = _player(m, db, uid, name)
        ctx = wb.Context(m, db, p)
        db.commit()
        if verb == 'wh':
            return _reply(message(m, wb.home_text(ctx), home_components(m, ctx, owner)), payload)
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
            text = wb.category_text(ctx, category, page, station)
            return _reply(message(m, text, category_components(m, ctx, owner, category, page, station)), payload)
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
            return _reply(message(m, text, recipe_components(m, ctx, owner, e, category, page, station)), payload)
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
        if verb == 'qd':
            text = m.task_queue.status(m, db, p, db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)), detail=True)
            return _reply(message(m, text, queue_components(m, db, p, owner)[:1], 'queue'), payload)
        if verb == 'st':
            return _reply(message(m, qol.status_text(m, db, p), status_components(m, db, p, owner), 'status'), payload)
        if verb in {'mn', 'mv', 'mk', 'mp'}:
            from . import menu
            data = menu.navigate(m, db, p, owner, verb, args, values, name)
            db.commit()
            return _reply(data, payload) if data is not None else _notice('This control is no longer available. Open /menu again.')
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
    with m.task_queue.atomic(m, channel):
        return _run(m, uid, name, action, kind, channel)


def _run(m, uid, name, action, kind, channel):
    if kind == 'cmd':
        from . import menu
        return menu.run(m, uid, name, action)
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
        elif kind in {'recover', 'clearout'}:
            components = status_components(m, db, p, uid)
        else:
            components = queue_components(m, db, p, uid)
        db.commit()
    return message(m, result, components, 'queue' if kind in {'queue', 'cancel', 'next'} else 'make')


def finish_ticket(m, payload, uid, name, action):
    origin = m.task_queue.queue_notifications.origin_channel
    token = origin.set(str(payload.get('channel_id') or ''))
    try:
        data = run_ticket(m, uid, name, action, payload)
    except Exception:
        import logging
        logging.getLogger(__name__).error('Workbench button action rolled back: %s', action.get('do'))
        data = {'content': 'This action could not be completed and nothing was spent. Open the menu again for a fresh button.',
                'embeds': [], 'components': [], 'allowed_mentions': {'parse': []}}
    finally:
        origin.reset(token)
    m.discord_deferred.edit_original(str(payload['application_id']), str(payload['token']), data)
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
