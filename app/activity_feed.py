"""The live activity feed: what everyone is doing, posted in the game channel for all to see.

Discord only lets a bot answer a button privately or publicly, and the game menu answers privately so each
player's buttons stay their own. That keeps the channel tidy but empty. The feed brings the life back:
every FEED_SECONDS (and at once for big moments) the bot posts what happened, in one compact message:

  ⛏️ Kamex mined 4 Hematite Ore · gathered 6 Lumber       what players brought in (Twitch and Discord)
  ⬆️ Astra levelled up — Crafting Lv. 2 → Lv. 3            level ups, trophies, new citizens, finished queues
  ⚡ Dust Storm! Everyone repair the walls                  events, stream challenges, votes, projects, seasons
  🌱 3 Seedlings worked on their own and brought in 12 items

While nobody else talks, the bot keeps adding to the same message (edited in place, up to MAX_LINES and
KEEP_MINUTES), so the feed never floods the channel; once someone posts, the next update starts a new
message below. Each feed message carries "My menu" and "Status" buttons that open the presser's own menu.

Moderators choose the channel with /mod → Activity feed: post here (or set DISCORD_FEED_CHANNEL_ID; the
game channel is the default) and can switch it off. Players can hide their own activity with
/settings feed:off. Nothing is recorded for the feed while it has no channel.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, select, update, delete
from .db import Base
from . import layout_v2
from . import runtime
from .db import SessionLocal
from .models import Player

# How often the feed updates. It edits its own message when nobody else has posted since (edits do not
# notify anyone), so a calm channel gets one message that grows; big moments go out at once.
FEED_SECONDS = max(20, int(os.getenv('FEED_SECONDS', '1200')))        # 20 minutes
MAX_LINES = 15           # lines in one feed message before a new one starts
KEEP_MINUTES = 30        # a feed message older than this is not edited any more
FLUSH_LINES = 10         # lines added in one update; the rest are summed up
URGENT = {'challenge_start', 'event_start', 'tier', 'vote', 'season', 'project', 'challenge_win'}
COLOUR = 0x7EE3B0
VERBS = {'make': ('🔨', 'crafted'), 'craftmax': ('🔨', 'crafted'), 'mining': ('⛏️', 'mined'), 'seed_supplies': ('🧺', 'gathered'),
         'seed_industries': ('🛒', 'bought'), 'action': ('💼', 'brought in'), 'queued_tasks': ('⏱️', 'brought in')}
log = logging.getLogger(__name__)


class FeedState(Base):
    __tablename__ = 'activity_feed_v1'
    world = Column(String(64), primary_key=True)
    channel = Column(String(32), nullable=False, default='')        # '' = the default (env) channel
    enabled = Column(Integer, nullable=False, default=1)
    message_id = Column(String(32), nullable=False, default='')
    message_at = Column(DateTime(timezone=True), nullable=True)
    lines = Column(Text, nullable=False, default='[]')
    last_highlight = Column(Integer, nullable=False, default=0)
    last_flush = Column(DateTime(timezone=True), nullable=True)


class FeedEvent(Base):
    __tablename__ = 'activity_feed_events_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    world = Column(String(64), nullable=False, index=True)
    channel_id = Column(String(64), nullable=False)
    canonical_uid = Column(String(96), nullable=False)
    name = Column(String(80), nullable=False)
    verb = Column(String(24), nullable=False)
    items = Column(String(1000), nullable=False, default='{}')
    seedling = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


class FeedPrivacy(Base):
    """Players who keep their activity out of the feed."""
    __tablename__ = 'activity_feed_privacy_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    hidden = Column(Integer, nullable=False, default=1)


def _now():
    return datetime.now(timezone.utc)


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def state(db):
    row = db.get(FeedState, runtime.DISCORD_WORLD_ID)
    if row is None:
        row = FeedState(world=runtime.DISCORD_WORLD_ID, channel='', enabled=1, message_id='', lines='[]', last_highlight=_top_highlight(db))
        db.add(row)
        db.flush()
    return row


def _top_highlight(db):
    from .stream_overlay import StreamHighlight
    from sqlalchemy import func
    return db.execute(select(func.coalesce(func.max(StreamHighlight.id), 0))).scalar() or 0


def channel_of(db):
    row = db.get(FeedState, runtime.DISCORD_WORLD_ID)
    if row is not None and not row.enabled:
        return ''
    chosen = (row.channel if row is not None else '') or os.getenv('DISCORD_FEED_CHANNEL_ID', '') or runtime.DISCORD_GAME_CHANNEL_ID
    return str(chosen or '').strip()


# ---------------------------------------------------------------- recording

def hidden(db, p):
    row = db.get(FeedPrivacy, (p.channel_id, p.twitch_uid))
    return bool(row and row.hidden)


def set_hidden(db, p, value):
    row = db.get(FeedPrivacy, (p.channel_id, p.twitch_uid))
    if row is None:
        row = FeedPrivacy(channel_id=p.channel_id, canonical_uid=p.twitch_uid, hidden=int(value))
        db.add(row)
    row.hidden = int(value)
    return ('🙈 Your activity is hidden from the channel feed. Your level ups and trophies stay private too.' if value
            else '📣 Your activity shows in the channel feed again.')


def record(db, p, fn_name, params, before, after, acting=False):
    """Note what a command brought in, for the next feed update."""
    from .game.players import resource_name
    if not before or not after or not channel_of(db) or hidden(db, p):
        return
    b, a = before.get('Resources', {}), after.get('Resources', {})
    gained = {}
    for k, v in a.items():
        n = v - b.get(k, 0)
        if n > 0 and k not in {'sc', 'contribution'} and not str(k).startswith('gear:'):
            label = resource_name(k)
            gained[label] = gained.get(label, 0) + n
    if not gained:
        return
    verb = 'seedling' if acting else fn_name if fn_name in VERBS else 'action'
    from .autonomy import clean_name
    db.add(FeedEvent(world=runtime.DISCORD_WORLD_ID, channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=clean_name(p.display_name)[:80],
                     verb=verb, items=json.dumps(gained)[:1000], seedling=int(bool(acting)), created_at=_now()))


# ---------------------------------------------------------------- building an update

def _items(items, limit=3):
    top = sorted(items.items(), key=lambda kv: -kv[1])
    text = ', '.join(f'{n} {name}' for name, n in top[:limit])
    return text + (f' and {len(top) - limit} more' if len(top) > limit else '')


def _highlight_line(h):
    title, detail = h.title, (h.detail or '').strip()
    if h.kind in {'queue'}:
        return f'{h.emoji} {title}: {detail}' if detail else f'{h.emoji} {title}'
    bold = h.kind in URGENT or h.kind in {'trophy', 'achievement', 'join'}
    head = f'**{title}**' if bold else title
    return f'{h.emoji} {head}' + (f' — {detail}' if detail else '')


def build(db, st):
    """(new lines, urgent?, highest highlight id, event ids) for everything since the last update."""
    from .stream_overlay import StreamHighlight
    hidden_names = {n for n, in db.execute(select(Player.display_name).join(
        FeedPrivacy, (FeedPrivacy.channel_id == Player.channel_id) & (FeedPrivacy.canonical_uid == Player.twitch_uid))
        .where(FeedPrivacy.hidden == 1)).all()}
    highlights = db.execute(select(StreamHighlight).where(StreamHighlight.id > st.last_highlight).order_by(StreamHighlight.id).limit(40)).scalars().all()
    top = max([h.id for h in highlights], default=st.last_highlight)
    shown = [h for h in highlights if not (h.name and h.name in hidden_names)]
    urgent = any(h.kind in URGENT for h in shown)
    lines = [_highlight_line(h) for h in sorted(shown, key=lambda h: (h.kind not in URGENT, h.id))]

    events = db.execute(select(FeedEvent).where(FeedEvent.world == runtime.DISCORD_WORLD_ID).order_by(FeedEvent.id)).scalars().all()
    people, seedlings = {}, {}
    for e in events:
        items = json.loads(e.items or '{}')
        if e.seedling:
            got = seedlings.setdefault(e.name, {})
        else:
            got = people.setdefault((e.channel_id, e.canonical_uid), {'name': e.name, 'verbs': {}})['verbs'].setdefault(e.verb, {})
        for k, n in items.items():
            got[k] = got.get(k, 0) + n
    for who in sorted(people.values(), key=lambda w: -sum(sum(v.values()) for v in w['verbs'].values())):
        parts = [f"{VERBS.get(verb, ('💼', 'brought in'))[1]} {_items(items)}" for verb, items in who['verbs'].items()]
        emoji = VERBS.get(next(iter(who['verbs'])), ('💼',))[0]
        lines.append(f"{emoji} **{who['name']}** " + ' · '.join(parts))
    if seedlings:
        total = sum(sum(v.values()) for v in seedlings.values())
        names = ', '.join(sorted(seedlings)[:3]) + (f' and {len(seedlings) - 3} more' if len(seedlings) > 3 else '')
        lines.append(f"🌱 {len(seedlings)} Seedling{'s' if len(seedlings) != 1 else ''} worked on their own and brought in {total} items ({names})")
    if len(lines) > FLUSH_LINES:
        extra = len(lines) - FLUSH_LINES + 1
        lines = lines[:FLUSH_LINES - 1] + [f'…and {extra} more things happened. Open your menu to join in!']
    return lines, urgent, top, [e.id for e in events]


# ---------------------------------------------------------------- delivery

def _api(method, path, token, **kw):
    import requests
    return requests.request(method, 'https://discord.com/api/v10' + path, headers={'Authorization': 'Bot ' + token}, timeout=10, **kw)


def payload(lines):
    from . import ui
    body = '\n'.join(lines)
    while len(body) > 4000:
        lines = lines[1:]
        body = '\n'.join(lines)
    data = {'embeds': [{'title': '📣 New Eridian · live', 'description': body, 'color': COLOUR,
                        'footer': {'text': 'Press My menu to play (only you see your menu) · Twitch: type !start'}}],
            'components': [ui.row(ui.button('My menu', ui.cid(ui.PUBLIC, 'mn', 'home'), style=1, emoji='🏠'),
                                  ui.button('Status', ui.cid(ui.PUBLIC, 'st'), emoji='📊'),
                                  ui.button('Town', ui.cid(ui.PUBLIC, 'mn', 'community'), emoji='🏘️'))],
            'allowed_mentions': {'parse': []}}
    return layout_v2.new_message(data)      # Discord's newer layout when it is on


def tick(force=False):
    """Post (or extend) the feed when it is due. Safe to call from several workers: one claims each update."""
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    with SessionLocal() as db:
        target = channel_of(db)
        if not token or not target.isdigit():
            return None
        st = state(db)
        lines, urgent, top, ids = build(db, st)
        if not lines:
            if top != st.last_highlight:
                st.last_highlight = top
            db.commit()
            return None
        now = _now()
        due = force or urgent or st.last_flush is None or now - _utc(st.last_flush) >= timedelta(seconds=FEED_SECONDS)
        if not due:
            db.commit()
            return None
        # Claim this update so two workers never post the same lines.
        claimed = db.execute(update(FeedState).where(FeedState.world == st.world, FeedState.last_highlight == st.last_highlight,
                                                     (FeedState.last_flush.is_(None)) | (FeedState.last_flush == st.last_flush))
                             .values(last_flush=now, last_highlight=top)).rowcount
        if not claimed:
            db.rollback()
            return None
        db.execute(delete(FeedEvent).where(FeedEvent.id.in_(ids)))
        db.commit()
        stamp = f'<t:{int(now.timestamp())}:t>'
        new = [f'{stamp} {line}' for line in lines]
        old = json.loads(st.lines or '[]')
        message_id, message_at, channel = st.message_id, st.message_at, target
    ok, message_id, all_lines = deliver(token, channel, message_id, message_at, old, new)
    with SessionLocal() as db:
        st = state(db)
        if ok:
            if message_id != st.message_id:
                st.message_at = _now()
            st.message_id, st.lines = message_id, json.dumps(all_lines)
        db.commit()
    return ok


# Messages posted before this process started may be in the other layout (embeds or Discord's newer one),
# and Discord cannot switch a message between them, so the feed only edits messages it posted since starting.
STARTED = datetime.now(timezone.utc)


def deliver(token, channel, message_id, message_at, old, new):
    """Edit the last feed message while it is still the newest in the channel; otherwise post a new one."""
    try:
        if message_id and message_at and _utc(message_at) >= STARTED and _now() - _utc(message_at) < timedelta(minutes=KEEP_MINUTES) \
                and len(old) + len(new) <= MAX_LINES:
            info = _api('GET', f'/channels/{channel}', token)
            if info.status_code == 200 and str(info.json().get('last_message_id') or '') == message_id:
                lines = old + new
                r = _api('PATCH', f'/channels/{channel}/messages/{message_id}', token, json=payload(lines))
                if 200 <= r.status_code < 300:
                    return True, message_id, lines
        r = _api('POST', f'/channels/{channel}/messages', token, json=payload(new))
        if 200 <= r.status_code < 300:
            return True, str(r.json().get('id') or ''), new
        log.warning('Activity feed not accepted by Discord (HTTP %s)', r.status_code)
    except Exception:
        log.warning('Activity feed delivery failed')
    return False, message_id, old


# ---------------------------------------------------------------- moderator controls

def here(db, channel):
    st = state(db)
    if not str(channel or '').isdigit():
        return '⚠️ Run this from the channel the feed should use.'
    st.channel, st.enabled, st.message_id, st.lines = str(channel), 1, '', '[]'
    return ('📣 The activity feed now posts in this channel: what everyone gathers, crafts and levels up, plus events, challenges and votes. '
            f'It updates about every {FEED_SECONDS} seconds and keeps editing the same message while the channel is quiet. '
            'Players can hide their own activity with /settings feed:off.')


def off(db):
    st = state(db)
    st.enabled = 0
    db.execute(delete(FeedEvent).where(FeedEvent.world == runtime.DISCORD_WORLD_ID))
    return '🔕 The activity feed is off. /mod → Activity feed: post here turns it back on.'
