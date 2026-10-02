"""Force merge: combine two characters into one, as the owner, from /menu → Moderator → Force merge.

The merge itself is the one `/link` and GET /api/v1/admin/merge already use (`merge_accounts`): stats, XP, items, skills,
homes, businesses, achievements, queues and Seedling life are combined, both sets of Twitch/Discord IDs point at the kept
character, and a Twitch + Discord pair becomes a permanent link. This module is the shared preview-and-apply core that the
endpoint and the button both call (`load`, `apply`), plus the owner-only Discord screens around it.

Flow: pick the character to KEEP, pick the one to MERGE INTO it (the first is left out of the list), then a preview of both
characters and the combined result. Nothing changes until ✔️ Confirm merge, a one-time ticket that carries the two characters'
ids. Everything is checked on the server at every step, including when the ticket is claimed: the presser must be an owner
(DISCORD_OWNER_USER_IDS), both characters must still exist and be the ones previewed, and the merge runs inside the same
game lock and transaction as every other action, so a failure changes nothing. It is irreversible and says so; the
moderator log records "owner <discord id> via /menu". No new table.
"""
from types import SimpleNamespace
from sqlalchemy import select, func
from . import ui

PAGE = 23                                   # dropdown rows per page, leaving room for Previous / Next
DENIED = '⛔ Owner access is required for Force merge.'


# ---------------------------------------------------------------- the core both the endpoint and the button call

class Refused(Exception):
    """A merge that cannot happen. `error` and `status` are the endpoint's answer; `kind` ('same', 'missing') picks /menu's words."""

    def __init__(self, kind, error, status):
        super().__init__(error)
        self.kind, self.error, self.status = kind, error, status


def load(m, db, channel, keep, merge):
    """Both characters (by uid) with their summaries and the combined totals, or Refused. Changes nothing."""
    if keep == merge:
        raise Refused('same', 'keep and merge are the same character.', 400)
    a = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == keep)).scalar_one_or_none()
    b = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == merge)).scalar_one_or_none()
    if not a or not b:
        raise Refused('missing', 'Both characters must exist in this channel (use the uid values from /api/v1/admin/duplicates).', 404)
    before = [m._player_summary(db, channel, a), m._player_summary(db, channel, b)]
    combined = {k: before[0][k] + before[1][k] for k in ('sc', 'contribution', 'actions', 'xp')}
    return SimpleNamespace(keep=a, merge=b, before=before, combined=combined)


def apply(m, db, channel, pair, actor):
    """Merge `pair.merge` into `pair.keep` (what `load` returned), link a Twitch + Discord pair, log it as `actor`.
    The caller holds the game transaction. Returns {'character': the merged summary, 'expected': the combined totals}."""
    keep, merge, before = pair.keep.twitch_uid, pair.merge.twitch_uid, pair.before
    m.merge_accounts(db, channel, merge, keep)
    # A Twitch + Discord pair becomes a permanent link, exactly as if the player had used /link.
    ids = db.execute(select(m.Identity).where(m.Identity.channel_id == channel, m.Identity.canonical_uid == keep)).scalars().all()
    tw = [i.provider_uid for i in ids if i.provider == 'twitch']
    dc = [i.provider_uid for i in ids if i.provider == 'discord']
    if len(dc) == 1 and not db.execute(select(m.AccountLink).where(m.AccountLink.channel_id == channel, m.AccountLink.discord_uid == dc[0])).scalar_one_or_none() \
       and not db.execute(select(m.AccountLink).where(m.AccountLink.channel_id == channel, m.AccountLink.twitch_uid == keep)).scalar_one_or_none():
        db.add(m.AccountLink(channel_id=channel, twitch_uid=keep, discord_uid=dc[0]))
    m.audit_moderator(db, channel, actor, 'merge', f"{before[1]['name']} ({merge}) into {before[0]['name']} ({keep})")
    db.commit()
    p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == keep)).scalar_one()
    return {'character': m._player_summary(db, channel, p), 'expected': pair.combined}


# ---------------------------------------------------------------- what the screens say about a character

def _ids(m, db, channel, uid):
    """['Twitch tw-555', 'Discord 9001']: every platform id that points at this character."""
    rows = db.execute(select(m.Identity).where(m.Identity.channel_id == channel, m.Identity.canonical_uid == uid)
                      .order_by(m.Identity.provider, m.Identity.provider_uid)).scalars().all()
    found = [f'{r.provider.capitalize()} {r.provider_uid}' for r in rows]
    return found or [f'Discord {uid[8:]}' if uid.startswith('discord:') else f'Twitch {uid}']


def _platforms(m, db, channel, uids):
    """{uid: 'Twitch+Discord'} for a page of characters, from one query."""
    kinds = {}
    for r in db.execute(select(m.Identity).where(m.Identity.channel_id == channel, m.Identity.canonical_uid.in_(uids))).scalars():
        kinds.setdefault(r.canonical_uid, set()).add(r.provider.capitalize())
    return {u: '+'.join(sorted(kinds.get(u) or {'Discord' if u.startswith('discord:') else 'Twitch'})) for u in uids}


def _queue(m, db, channel, uid):
    return db.get(m.task_queue.TaskQueue, (channel, uid))


def _queue_line(m, row):
    if row is None:
        return 'none'
    label = m.task_queue.choices(m).get(row.task, row.task)
    return f'{label} · {row.state} · {row.remaining} of {row.total} attempts left' if row.state in m.task_queue.ACTIVE else f'{label} · {row.state}'


def _queue_after(m, kq, mq, keep_name, merge_name):
    """What the existing merge does with the two queues (task_queue.merge_accounts), in words."""
    active = m.task_queue.ACTIVE
    if mq is not None and mq.state in active:
        if kq is None or kq.state not in active:
            return f"{merge_name}'s running queue moves to {keep_name}"
        return f"both are running: {keep_name}'s continues, {merge_name}'s remaining attempts are cancelled (finished work is kept)"
    return f"{keep_name}'s queue stays as it is" if kq is not None else 'none'


def _stock(m, db, p):
    return m.item_identity.stock(m, db, p)


def _facts(m, db, channel, p, summary):
    stock = _stock(m, db, p)
    return SimpleNamespace(name=p.display_name, uid=p.twitch_uid, ids=_ids(m, db, channel, p.twitch_uid), summary=summary, stock=stock,
                           queue=_queue(m, db, channel, p.twitch_uid))


def _kind(n):
    return f"{n} kind{'' if n == 1 else 's'}"


def _line(f, queue):
    s = f.summary
    return [f"• {' · '.join(f.ids)}", f"• {s['sc']} SC · {s['xp']} XP · {s['actions']} actions · {s['contribution']} contribution",
            f"• {sum(f.stock.values())} items ({_kind(len(f.stock))}) · queue: {queue}"]


def preview_text(m, db, channel, pair):
    k, g = (_facts(m, db, channel, p, s) for p, s in ((pair.keep, pair.before[0]), (pair.merge, pair.before[1])))
    stock = {key: k.stock.get(key, 0) + g.stock.get(key, 0) for key in k.stock.keys() | g.stock.keys()}
    c, ids = pair.combined, list(dict.fromkeys(k.ids + g.ids))
    link = any(i.startswith('Twitch') for i in ids) and sum(i.startswith('Discord') for i in ids) == 1
    lines = ['🧬 FORCE MERGE — PREVIEW',
             f'⚠️ This cannot be undone. **{g.name}** is deleted and **{k.name}** survives. Nothing changes until you press Confirm merge.', '',
             f'**KEEP** — {k.name}'] + _line(k, _queue_line(m, k.queue)) + ['', f'**MERGE INTO IT** — {g.name}'] + _line(g, _queue_line(m, g.queue)) + [
             '', f'**AFTER THE MERGE** — {k.name} survives',
             f"• {c['sc']} SC · {c['xp']} XP · {c['actions']} actions · {c['contribution']} contribution",
             f'• {sum(stock.values())} items ({_kind(len(stock))}) · queue: {_queue_after(m, k.queue, g.queue, k.name, g.name)}',
             f"• {' and '.join(ids)} will all point at {k.name}." + (' A Twitch + Discord pair becomes a permanent link.' if link else ''),
             '• Skills, homes, businesses, achievements and Seedling life are combined; the moderator log records who did it.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- the screens (owner only, checked on every one)

def _nav(owner, *fallback):
    return ui.row(ui.back_button(owner, *fallback), ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))


def _card(m, owner, text, rows, where='Force merge'):
    from .menu import crumb
    return ui.with_crumb(ui.message(m, text, rows, 'moderator'), crumb('mod', where))


def _stop(m, owner, text, rows):
    """A refusal card: what is wrong, and that nothing changed."""
    return _card(m, owner, f'🧬 FORCE MERGE\n{text} Nothing changed.', rows)


def refusal(m, owner, text, *fallback):
    """A refusal card: why, that nothing changed, and Back / Menu."""
    return _stop(m, owner, text, [_nav(owner, *(fallback or ('mn', 'mod')))])


def _id(raw):
    """A row id from a custom_id, select value or ticket field: plain ASCII digits that fit a 32-bit column, else None.
    Checked before any query, so a forged huge number is refused instead of reaching the database."""
    raw = str(raw if raw is not None else '').strip()
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 9 else None


def _character(db, m, channel, raw):
    """The Player with this row id, or None (not a usable number, or no such character)."""
    pid = _id(raw)
    return None if pid is None else db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.id == pid)).scalar_one_or_none()


def _listing(m, db, channel, skip=None):
    rows = db.execute(select(m.Player.id, m.Player.twitch_uid, m.Player.display_name, m.Player.sc, m.Player.actions)
                      .where(m.Player.channel_id == channel, *([m.Player.id != skip] if skip else []))
                      .order_by(func.lower(m.Player.display_name), m.Player.id)).all()
    return rows


def _picker(m, db, owner, channel, verb, args, page, title, lead, skip=None, up=('mn', 'mod')):
    rows = _listing(m, db, channel, skip)
    if not rows:
        return refusal(m, owner, 'There is no other character to choose.', *up)
    pages = max(1, -(-len(rows) // PAGE)) if len(rows) > 25 else 1
    page = max(1, min(page, pages))
    shown = rows if pages == 1 else rows[(page - 1) * PAGE:page * PAGE]
    kinds = _platforms(m, db, channel, [r.twitch_uid for r in shown])
    options = [ui.option(f'{r.display_name} · #{r.id}', r.id, f'{kinds[r.twitch_uid]} · {r.sc} SC · {r.actions} actions') for r in shown]
    if pages > 1:
        lead += f'\nPage {page} of {pages}.'
        if page > 1:
            options.insert(0, ui.option(f'◀ Previous page ({page - 1}/{pages})', f'__page:{page - 1}'))
        if page < pages:
            options.append(ui.option(f'Next page ({page + 1}/{pages}) ▶', f'__page:{page + 1}'))
    menu = ui.select(ui.cid(owner, verb, *args), 'Choose a character…' if pages == 1 else f'Choose a character… (page {page}/{pages})', options)
    return _card(m, owner, f'🧬 FORCE MERGE — {title}\n{lead}', [menu, _nav(owner, *up)])


def _page(values):
    value = str((values or [''])[0])
    return (_id(value.split(':', 1)[1]) or 1) if value.startswith('__page:') else 0


def view(m, db, p, owner, verb, args, values):
    """Step 1 (xk): choose the character to keep. Step 2 and the preview (xm|keep[|merge]). Owner only, every time."""
    if not ui.is_owner(m):
        from .menu import nav
        return _stop(m, owner, DENIED, [nav(owner, 'mod', 'mod')])
    channel = m.DISCORD_WORLD_ID
    if verb == 'xk' and not (values and not _page(values)):
        return _picker(m, db, owner, channel, 'xk', (), max(1, _page(values)), 'step 1 of 3: who survives?',
                       'Choose the character to KEEP. Its name stays and the other character is merged into it.\n'
                       'Owner only. Nothing changes until you press Confirm merge on the preview.')
    keep = _character(db, m, channel, values[0] if verb == 'xk' else args[0] if args else '')
    if keep is None:
        return refusal(m, owner, 'That character no longer exists. Choose again.', 'xk')
    if verb == 'xk':
        args, values = [str(keep.id)], []
    page = _page(values)
    if len(args) < 2 and (page or not values):
        return _picker(m, db, owner, channel, 'xm', (keep.id,), max(1, page), 'step 2 of 3: who is merged in?',
                       f'Keeping **{keep.display_name}** ({" · ".join(_ids(m, db, channel, keep.twitch_uid))}).\n'
                       'Choose the character to MERGE INTO it. That character is deleted; everything it has is added to the kept one.',
                       skip=keep.id, up=('xk',))
    gone = _character(db, m, channel, args[1] if len(args) > 1 else values[0])
    if gone is None:
        return refusal(m, owner, 'That character no longer exists. Choose again.', 'xm', keep.id)
    return preview(m, db, owner, channel, keep, gone)


def preview(m, db, owner, channel, keep, gone):
    if keep.id == gone.id or keep.twitch_uid == gone.twitch_uid:
        return refusal(m, owner, f'{keep.display_name} and {gone.display_name} are already the same character, so there is nothing to merge.', 'xk')
    try:
        pair = load(m, db, channel, keep.twitch_uid, gone.twitch_uid)
    except Refused as e:
        return refusal(m, owner, 'One of the two characters no longer exists (it may already have been merged).' if e.kind == 'missing' else e.error, 'xk')
    ticket = ui.issue(m, owner, {'do': 'forcemerge', 'keep': keep.id, 'keep_uid': keep.twitch_uid, 'merge': gone.id, 'merge_uid': gone.twitch_uid})
    rows = [ui.row(ui.button('Confirm merge', ui.cid(owner, 't', ticket), style=4, emoji='✔️'),
                   ui.button('Swap', ui.cid(owner, 'xm', gone.id, keep.id), emoji='🔁'),
                   ui.back_button(owner, 'xm', keep.id), ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))]
    return _card(m, owner, preview_text(m, db, channel, pair), rows)


def run(m, uid, action):
    """✔️ Confirm merge, claimed once. Runs inside the game transaction; every check is repeated here."""
    owner = str(uid)
    channel = m.DISCORD_WORLD_ID
    done = ui.row(ui.button('Moderator', ui.cid(owner, 'mn', 'mod'), emoji='🛡️'), ui.button('Merge another', ui.cid(owner, 'xk'), emoji='🧬'))
    if not ui.is_owner(m):
        return _stop(m, owner, DENIED, [ui.row(ui.button('Moderator', ui.cid(owner, 'mn', 'mod'), emoji='🛡️')), _nav(owner, 'mn', 'mod')])
    with m.SessionLocal() as db:
        keep, gone = (_character(db, m, channel, action.get(k)) for k in ('keep', 'merge'))
        if keep is None or gone is None:
            return _stop(m, owner, 'One of the two characters no longer exists (it may already have been merged).', [done, _nav(owner, 'mn', 'mod')])
        if (keep.twitch_uid, gone.twitch_uid) != (action.get('keep_uid'), action.get('merge_uid')):
            return _stop(m, owner, 'One of the two characters changed since the preview (an account was linked or merged). Open Force merge again.',
                         [done, _nav(owner, 'mn', 'mod')])
        if keep.twitch_uid == gone.twitch_uid:
            return _stop(m, owner, 'Those are already the same character.', [done, _nav(owner, 'mn', 'mod')])
        pair = load(m, db, channel, keep.twitch_uid, gone.twitch_uid)
        names = (pair.before[1]['name'], pair.before[0]['name'])
        result = apply(m, db, channel, pair, f'owner {owner} via /menu')
        s = result['character']
        p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == keep.twitch_uid)).scalar_one()
        stock = _stock(m, db, p)
        linked = db.execute(select(m.AccountLink).where(m.AccountLink.channel_id == channel, m.AccountLink.twitch_uid == p.twitch_uid)).scalar_one_or_none()
        text = '\n'.join([f"🧬 FORCE MERGE — DONE\nMerged **{names[0]}** into **{names[1]}**. {names[0]} is gone; {names[1]} survives.", '',
                          f"**{s['name']}** now has",
                          f"• {s['sc']} SC · {s['xp']} XP · {s['actions']} actions · {s['contribution']} contribution",
                          f'• {sum(stock.values())} items ({_kind(len(stock))}) · queue: {_queue_line(m, _queue(m, db, channel, p.twitch_uid))}',
                          f"• {' · '.join(_ids(m, db, channel, p.twitch_uid))} all point at {s['name']}."
                          + (' Twitch and Discord are now permanently linked.' if linked is not None else ''),
                          f'• Logged in the moderator log as owner {owner} via /menu.'])
    return _card(m, owner, text, [done, _nav(owner, 'mn', 'mod')])
