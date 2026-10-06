"""Players are shown by their names: level-up lines name people and hobbies, never account ids or internal keys, and
nobody is left called "Citizen" (the placeholder a call without a name gets).

A relationship levels up between two citizens. Its line used to read "Relationship 621372225 Lv. 1 → Lv. 2",
with the other citizen's account id, and hobbies read "Hobby gardening". commands.snapshot now labels them
"Relationship with blake1215" and "Gardening hobby" (labels()), and repair() rewrites lines stored before this
fix wherever they are shown again: the activity feed, stream highlights, journals, the latest milestone on
status screens, and inboxes.
"""
import json
import logging
import re

from sqlalchemy import select, or_

log = logging.getLogger(__name__)

RELATIONSHIP = re.compile(r'\bRelationship (discord:\d+|\d{4,})\b')
HOBBY = re.compile(r'\bHobby ([a-z_]+)\b')
FORMER = 'a former citizen'


def relationship_label(name):
    return f'Relationship with {name or FORMER}'


def hobby_label(m, key):
    return f'{m.HOBBIES[key][0]} hobby' if key in m.HOBBIES else f'Hobby {key}'


def labels(m, db, p, keys):
    """{rank key: what players read} for snapshot's "Relationship <uid>" and "Hobby <key>" ranks."""
    partners = [k.split(' ', 1)[1] for k in keys if k.startswith('Relationship ')]
    names = {}
    if partners:
        names = dict(db.execute(select(m.Player.twitch_uid, m.Player.display_name).where(
            m.Player.channel_id == p.channel_id, m.Player.twitch_uid.in_(partners))).all())
    found = {}
    for key in keys:
        if key.startswith('Relationship '):
            found[key] = relationship_label(names.get(key.split(' ', 1)[1]))
        elif key.startswith('Hobby '):
            found[key] = hobby_label(m, key.split(' ', 1)[1])
    return found


def readable(m, text, names):
    """The same text with account ids replaced by names and hobby keys by their labels."""
    if not isinstance(text, str) or ('Relationship ' not in text and 'Hobby ' not in text):
        return text
    text = RELATIONSHIP.sub(lambda x: relationship_label(names.get(x.group(1))), text)
    return HOBBY.sub(lambda x: hobby_label(m, x.group(1)) if x.group(1) in m.HOBBIES else x.group(0), text)


def _deep(m, value, names):
    if isinstance(value, str):
        return readable(m, value, names)
    if isinstance(value, list):
        return [_deep(m, v, names) for v in value]
    if isinstance(value, dict):
        return {k: _deep(m, v, names) for k, v in value.items()}
    return value


def repair(m):
    """Rewrite level-up lines stored before names were used. Safe to run again: fixed lines no longer match."""
    from .models import JournalEntry, SeedlingState
    from .stream_overlay import StreamHighlight
    from .inbox import InboxItem
    from .activity_feed import FeedState
    fixed = 0
    try:
        with m.SessionLocal() as db:
            names = dict(db.execute(select(m.Player.twitch_uid, m.Player.display_name)).all())
            for model, columns in ((StreamHighlight, ('title', 'detail')), (JournalEntry, ('entry',)),
                                   (SeedlingState, ('last_progress',)), (InboxItem, ('text',))):
                cols = [getattr(model, c) for c in columns]
                rows = db.execute(select(model).where(or_(*[c.like('%Relationship %') for c in cols],
                                                          *[c.like('%Hobby %') for c in cols]))).scalars().all()
                for row in rows:
                    for column, col in zip(columns, cols):
                        old = getattr(row, column)
                        new = readable(m, old, names)
                        if new != old:
                            limit = getattr(col.type, 'length', None)
                            setattr(row, column, new[:limit] if limit else new)
                            fixed += 1
            for row in db.execute(select(FeedState)).scalars().all():
                lines = json.loads(row.lines or '[]')
                new = _deep(m, lines, names)
                if new != lines:
                    row.lines = json.dumps(new, ensure_ascii=False)
                    fixed += 1
            db.commit()
    except Exception:
        log.exception('Could not rewrite stored level-up lines with names; new lines use names either way')
    if fixed:
        log.info('Rewrote %s stored level-up lines to use names instead of account ids', fixed)
    return fixed


def restore_names(m):
    """Give citizens stuck with the placeholder name "Citizen" back the last real name their accounts used.

    Background work once looked citizens up without a name, and each lookup renamed them "Citizen"; their Seedlings
    then kept the placeholder. The names every account used are kept in AccountNameHistory."""
    from .models import Identity, AccountNameHistory
    fixed = 0
    try:
        with m.SessionLocal() as db:
            stuck = db.execute(select(m.Player).where(m.Player.display_name == m.PLACEHOLDER_NAME)).scalars().all()
            for p in stuck:
                accounts = db.execute(select(Identity.provider, Identity.provider_uid).where(
                    Identity.channel_id == p.channel_id, Identity.canonical_uid == p.twitch_uid)).all()
                best = None
                for provider, uid in accounts:
                    for row in db.execute(select(AccountNameHistory).where(
                            AccountNameHistory.channel_id == p.channel_id, AccountNameHistory.provider == provider,
                            AccountNameHistory.provider_uid == uid, AccountNameHistory.display_name != m.PLACEHOLDER_NAME)).scalars():
                        if best is None or row.last_seen > best.last_seen:
                            best = row
                if best is not None:
                    p.display_name = best.display_name[:30]
                    fixed += 1
            db.commit()
    except Exception:
        log.exception('Could not restore names of citizens called "Citizen"; they get theirs back on their next command')
    if fixed:
        log.info('Restored the names of %s citizens who were shown as "Citizen"', fixed)
    return fixed
