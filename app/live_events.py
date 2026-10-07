"""Stream challenges: short shared goals that only happen while the stream is live.

While the channel is live a challenge starts every LIVE_EVENT_GAP_MINUTES or so (moderators can also start
one): "Dust storm! Repair the walls", "Harvest rush", "Ore seam spotted" and more. Each lasts 5–10 minutes,
has one shared goal sized to how many people are chatting, and shows as a goal bar on the stream map, the
Hub, the ticker and the alerts. Every command that does the right kind of work counts: repairs for the dust
storm, gathered crops for the harvest rush, and so on. Seedlings acting on their own do not count: this is for
the people in chat.

  Win:  every participant gets SC (more for doing more), +2 Contribution, the challenge's materials and
        season points; the top helper gets an MVP bonus; the society gets a boost.
  Lose: participants still get a small thank-you, and the colony's mood dips a little.

Live means: a moderator switched it on (!live on, for up to LIVE_MANUAL_HOURS), or the Twitch API says the
channel is live (TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET and TWITCH_CHANNEL_LOGIN set), or at least
LIVE_AUTO_CHATTERS different people used Twitch commands in the last LIVE_WINDOW_MINUTES. !live off stops it.
"""
import os
import random
import time
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, DateTime, select, func
from .db import Base
from . import runtime
from .models import Player
from .settlement import state as colony_state

GAP_MINUTES = max(3, int(os.getenv('LIVE_EVENT_GAP_MINUTES', '25')))
FIRST_MINUTES = max(1, int(os.getenv('LIVE_EVENT_FIRST_MINUTES', '5')))
AUTO_CHATTERS = max(1, int(os.getenv('LIVE_AUTO_CHATTERS', '2')))
WINDOW_MINUTES = 15
MANUAL_HOURS = 8
AUTO_START = os.getenv('LIVE_EVENTS_AUTO', 'true').lower() not in {'0', 'false', 'no', 'off'}
RESULT_SECONDS = 25              # the result stays on the overlay this long
WIN_SC, PER_UNIT_SC, MAX_UNIT_SC, WIN_CONTRIBUTION, WIN_POINTS = 10, 2, 20, 2, 20
MVP_SC, LOSE_SC, LOSE_POINTS = 15, 4, 5

# key: emoji, title, call to action (shown on stream), how to help (chat), measure, goal per chatter, base goal,
#      minutes, material reward {name: qty}, society reward {field: n}, board skills (+5% while it runs)
# measure: ('skills', {...}) one per command that raises one of these aptitudes;
#          ('items', {...}) the number of these materials brought in.
CHALLENGES = {
    'dust_storm': ('🌪️', 'Dust Storm', 'Everyone repair the walls before the storm hits', '!repair or any crafting',
                   ('skills', {'infrastructure', 'fabrication'}), 4, 8, 8, {'Stone': 2}, {'development': 6}),
    'harvest_rush': ('🌾', 'Harvest Rush', 'The crops are ripe. Bring the harvest in before the frost', '!harvest, !farm or !gather berries',
                     ('items', {'Pumpkin', 'Corn', 'Tomato', 'Berries', 'Herbs', 'Mushroom', 'Nuts', 'Flaxa'}), 5, 10, 7, {'Berries': 3}, {'food': 8}),
    'ore_seam': ('⛏️', 'Ore Seam Spotted', 'A rich seam opened at the Frontier Edge. Mine it fast', '!mine or !gather stone',
                 ('items', {'Stone', 'Coal', 'Hematite Ore', 'Chalcopyrite Ore', 'Bauxite Ore', 'Argentite Ore', 'Aurite Ore', 'Rutile Ore', 'Clay'}), 4, 8, 7,
                 {'Coal': 2}, {'materials': 8}),
    'lumber_drive': ('🪵', 'Lumber Drive', 'Winter is coming. Stack the woodpiles', '!gather lumber',
                     ('items', {'Lumber'}), 5, 10, 6, {'Lumber': 3}, {'materials': 6}),
    'siro_surge': ('☣️', 'Siro Surge', 'The Siro readings are spiking. Scan and study them', '!research or !scan',
                   ('skills', {'research', 'environmental'}), 3, 6, 8, {'Herbs': 2}, {'knowledge': 8}),
    'supply_convoy': ('🚚', 'Supply Convoy', 'A convoy is at the gates. Unload and deliver everything', '!cargo, !delivery or !spaceport',
                      ('skills', {'logistics'}), 3, 6, 7, {'Lumber': 2}, {'treasury': 8}),
    'feast_prep': ('🍲', 'Feast Prep', 'Guests arrive tonight. Cook up a feast', '!make any food or !eat',
                   ('skills', {'cooking', 'cultivation'}), 3, 6, 8, {'Berries': 3}, {'food': 6, 'reputation': 3}),
    'lost_duck': ('🦆', 'Lost Duck', 'A delivery duck wandered off into the wilds. Search the frontier', '!explore or !survey',
                  ('skills', {'frontier'}), 3, 5, 7, {'Nuts': 2}, {'reputation': 6}),
    'market_rush': ('🪙', 'Market Rush', 'Traders from the ridge are in town. Buy, sell and do business', '!market or !business',
                    ('skills', {'commerce'}), 3, 5, 6, {'Berries': 2}, {'treasury': 10}),
    'power_surge': ('⚡', 'Power Surge', 'The grid is flickering. Fix the machines', '!repair or !make parts',
                    ('skills', {'fabrication', 'infrastructure'}), 4, 8, 6, {'Clay': 2}, {'development': 8}),
    'clinic_rush': ('🏥', 'Clinic Rush', 'A cold is going round. Brew remedies and help out', '!make medicine or !research',
                    ('skills', {'medicine', 'research'}), 3, 5, 8, {'Herbs': 3}, {'reputation': 5, 'knowledge': 3}),
    'meteor_shower': ('☄️', 'Meteor Shower', 'Meteors are falling near the colony. Find the fragments', '!explore, !mine or !scan',
                      ('skills', {'frontier', 'extraction', 'environmental'}), 4, 8, 7, {'Stone': 3}, {'knowledge': 5, 'materials': 4}),
}
BOARD_BONUS = 0.05


class LiveState(Base):
    __tablename__ = 'live_state_v1'
    world = Column(String(64), primary_key=True)
    manual = Column(String(8), nullable=False, default='auto')       # on, off or auto
    manual_until = Column(DateTime(timezone=True), nullable=True)
    next_at = Column(DateTime(timezone=True), nullable=True)
    last_key = Column(String(32), nullable=False, default='')
    live_since = Column(DateTime(timezone=True), nullable=True)


class Challenge(Base):
    __tablename__ = 'live_challenges_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    world = Column(String(64), nullable=False, index=True)
    key = Column(String(32), nullable=False)
    goal = Column(Integer, nullable=False)
    progress = Column(Integer, nullable=False, default=0)
    state = Column(String(12), nullable=False, default='active')      # active, won, lost, cancelled
    started_by = Column(String(80), nullable=False, default='')
    started_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class Entry(Base):
    __tablename__ = 'live_challenge_entries_v1'
    challenge_id = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    name = Column(String(80), nullable=False, default='')
    amount = Column(Integer, nullable=False, default=0)


def _now():
    return datetime.now(timezone.utc)


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- is the stream live?

_chatters = {}          # uid -> last Twitch command (monotonic seconds)
_api = {'at': 0.0, 'live': None, 'token': '', 'token_until': 0.0}


def seen_on_twitch(uid):
    _chatters[str(uid)] = time.monotonic()
    if len(_chatters) > 2000:
        cut = time.monotonic() - WINDOW_MINUTES * 60
        for k in [k for k, v in _chatters.items() if v < cut]:
            _chatters.pop(k, None)


def chatters():
    cut = time.monotonic() - WINDOW_MINUTES * 60
    return sum(1 for v in _chatters.values() if v >= cut)


def twitch_api_live():
    """True/False from the Twitch API when it is configured, else None. Cached for two minutes."""
    cid, secret, login = (os.getenv(k, '').strip() for k in ('TWITCH_CLIENT_ID', 'TWITCH_CLIENT_SECRET', 'TWITCH_CHANNEL_LOGIN'))
    if not (cid and secret and login):
        return None
    if time.monotonic() - _api['at'] < 120:
        return _api['live']
    _api['at'] = time.monotonic()
    try:
        import requests
        if not _api['token'] or time.monotonic() > _api['token_until']:
            r = requests.post('https://id.twitch.tv/oauth2/token', data={'client_id': cid, 'client_secret': secret, 'grant_type': 'client_credentials'}, timeout=8)
            data = r.json()
            _api['token'], _api['token_until'] = data.get('access_token', ''), time.monotonic() + int(data.get('expires_in', 3600)) - 60
        r = requests.get('https://api.twitch.tv/helix/streams', params={'user_login': login}, timeout=8,
                         headers={'Client-Id': cid, 'Authorization': 'Bearer ' + _api['token']})
        _api['live'] = bool(r.json().get('data'))
    except Exception:
        logging.getLogger(__name__).warning('Twitch live check failed')
        _api['live'] = None
    return _api['live']


def state(m, db):
    world = runtime.DISCORD_WORLD_ID
    row = db.get(LiveState, world)
    if row is None:
        row = LiveState(world=world, manual='auto', last_key='')
        db.add(row)
        db.flush()
    return row


def is_live(m, db):
    row = state(m, db)
    if row.manual == 'off' and row.manual_until and _now() < _utc(row.manual_until):
        return False
    if row.manual == 'on' and row.manual_until and _now() < _utc(row.manual_until):
        return True
    api = twitch_api_live()
    if api is not None:
        return api
    return chatters() >= AUTO_CHATTERS


def set_live(m, db, value, who='moderator'):
    row = state(m, db)
    value = str(value or '').strip().casefold()
    if value not in {'on', 'off', 'auto'}:
        return f"📡 Stream mode is {row.manual}{' (live now)' if is_live(m, db) else ''}. Use on, off or auto."
    row.manual = value
    row.manual_until = _now() + timedelta(hours=MANUAL_HOURS) if value != 'auto' else None
    if value == 'on':
        row.next_at, row.live_since = _now() + timedelta(minutes=FIRST_MINUTES), _now()
        return f'📡 Stream is LIVE. The first stream challenge starts in about {FIRST_MINUTES} minutes (and one every ~{GAP_MINUTES} after). Auto-off in {MANUAL_HOURS}h.'
    if value == 'off':
        cancel(m, db, who, quiet=True)
        return '📡 Stream is offline. No stream challenges until it goes live again.'
    return f'📡 Stream mode is automatic: live when {AUTO_CHATTERS}+ people use Twitch commands within {WINDOW_MINUTES} minutes (or the Twitch API says so).'


# ---------------------------------------------------------------- running challenges

def active(m, db):
    return db.execute(select(Challenge).where(Challenge.world == runtime.DISCORD_WORLD_ID, Challenge.state == 'active').order_by(Challenge.id.desc())).scalars().first()


def goal_for(key, people):
    c = CHALLENGES[key]
    return max(c[6], c[6] + c[5] * max(0, people - 1))


def start(m, db, key='', who='auto'):
    from . import stream_overlay
    if expire(m, db):
        return None, '⛔ A stream challenge is already running. Stop it first.'
    st = state(m, db)
    if not key:
        pool = [k for k in CHALLENGES if k != st.last_key]
        key = random.choice(pool)
    if key not in CHALLENGES:
        return None, '⛔ Unknown challenge. Options: ' + ', '.join(CHALLENGES)
    c = CHALLENGES[key]
    people = max(1, chatters())
    row = Challenge(world=runtime.DISCORD_WORLD_ID, key=key, goal=goal_for(key, people), progress=0, state='active', started_by=who[:80],
                    started_at=_now(), ends_at=_now() + timedelta(minutes=c[7]))
    db.add(row)
    st.last_key = key
    st.next_at = row.ends_at + timedelta(minutes=GAP_MINUTES + random.randint(-5, 5))
    db.flush()
    stream_overlay.highlight(db, runtime.DISCORD_WORLD_ID, 'challenge_start', f'{c[1]}! {c[2]}', f'Goal {row.goal} in {c[7]} minutes. Help with {c[3]}.', emoji=c[0])
    return row, f'{c[0]} STREAM CHALLENGE · {c[1]}: {c[2]}! Goal {row.goal} in {c[7]} min. Help: {c[3]}.'


def cancel(m, db, who='moderator', quiet=False):
    row = active(m, db)
    if not row:
        return 'ℹ️ No stream challenge is running.'
    row.state, row.resolved_at = 'cancelled', _now()
    if not quiet:
        from . import stream_overlay
        c = CHALLENGES[row.key]
        stream_overlay.highlight(db, row.world, 'challenge_fail', f'{c[1]} called off', f'Stopped by {who}. No rewards or penalties.', emoji='🛑')
    return f'🛑 {CHALLENGES[row.key][1]} was stopped. No rewards or penalties.'


def expire(m, db):
    """Settle a challenge whose time is up. Returns the challenge still running, if any."""
    row = active(m, db)
    if row and _now() >= _utc(row.ends_at):
        finish(m, db, row, won=row.progress >= row.goal)
        return None
    return row


def tick(m, db):
    """Resolve an expired challenge and start the next one when the stream is live."""
    row = expire(m, db)
    if row or not AUTO_START:
        return
    st = state(m, db)
    live = is_live(m, db)
    if not live:
        st.live_since = None
        return
    if st.live_since is None:
        st.live_since = _now()
        if not st.next_at or _utc(st.next_at) < _now():
            st.next_at = _now() + timedelta(minutes=FIRST_MINUTES)
    if st.next_at and _now() >= _utc(st.next_at):
        start(m, db, '', 'auto')


def amount_for(m, key, before, after):
    from .game.players import resource_name
    measure = CHALLENGES[key][4]
    if measure[0] == 'skills':
        b, a = before.get('Competency', {}), after.get('Competency', {})
        return int(any(a.get(k, 0) > b.get(k, 0) for k in measure[1]))
    wanted = {k for k in (item_key(m, n) for n in measure[1]) if k}
    b, a = before.get('Resources', {}), after.get('Resources', {})
    return sum(max(0, v - b.get(k, 0)) for k, v in a.items() if k in wanted or resource_name(k) in measure[1])


def item_key(m, name):
    from . import seed_content
    try:
        return seed_content.key(name)
    except KeyError:
        return None


def from_command(m, db, p, before, after, provider='twitch'):
    """Count a player's own command towards the running challenge. Returns (discord note, chat note)."""
    row = active(m, db)
    if not row or not before or not after:
        return '', ''
    if _now() >= _utc(row.ends_at):
        tick(m, db)
        return '', ''
    n = amount_for(m, row.key, before, after)
    if n <= 0:
        return '', ''
    n = min(n, max(3, row.goal // 4))            # nobody finishes a shared goal alone in one go
    entry = db.get(Entry, (row.id, p.channel_id, p.twitch_uid))
    if entry is None:
        entry = Entry(challenge_id=row.id, channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=p.display_name[:80], amount=0)
        db.add(entry)
    entry.amount += n
    row.progress += n
    c = CHALLENGES[row.key]
    if row.progress >= row.goal:
        paid = finish(m, db, row, won=True)
        mine = paid.get((p.channel_id, p.twitch_uid), 0)
        return (f'{c[0]} **{c[1]} complete!** You helped with {entry.amount}. +{mine} SC and rewards for everyone who joined in.',
                f'{c[0]} {c[1]} WON! +{mine} SC')
    left = int((_utc(row.ends_at) - _now()).total_seconds())
    return (f'{c[0]} {c[1]}: {row.progress}/{row.goal} (+{n} from you) · {left // 60}:{left % 60:02d} left',
            f'{c[0]} {row.progress}/{row.goal} (+{n})')


def finish(m, db, row, won):
    """Pay everyone who took part. Returns {(channel, uid): SC paid}."""
    from .game.cooldowns_materials import material_change
    from .game.players import society
    from . import stream_overlay, seasons
    c = CHALLENGES[row.key]
    row.state, row.resolved_at = ('won' if won else 'lost'), _now()
    entries = db.execute(select(Entry).where(Entry.challenge_id == row.id, Entry.amount > 0).order_by(Entry.amount.desc())).scalars().all()
    paid = {}
    for rank, e in enumerate(entries):
        p = db.execute(select(Player).where(Player.channel_id == e.channel_id, Player.twitch_uid == e.canonical_uid)).scalar_one_or_none()
        if not p:
            continue
        if won:
            sc = WIN_SC + min(MAX_UNIT_SC, e.amount * PER_UNIT_SC) + (MVP_SC if rank == 0 else 0)
            p.sc += sc
            p.contribution += WIN_CONTRIBUTION
            for name, q in c[8].items():
                if item_key(m, name):
                    material_change(db, p, item_key(m, name), q)
            seasons.add(m, db, p, WIN_POINTS + e.amount, kind='events', contribution=WIN_CONTRIBUTION)
        else:
            sc = LOSE_SC
            p.sc += sc
            seasons.add(m, db, p, LOSE_POINTS, kind='events')
        paid[(e.channel_id, e.canonical_uid)] = sc
    s = society(db, row.world)
    shared = colony_state(db, row.world)
    if won:
        for field, n in c[9].items():
            setattr(s, field, getattr(s, field) + n)
        shared.mood = min(100, shared.mood + 3)
        top = entries[0].name if entries else ''
        reward = ', '.join(f'+{n} {f.title()}' for f, n in c[9].items())
        stream_overlay.highlight(db, row.world, 'challenge_win', f'{c[1]} complete!',
                                 f'{len(entries)} helped · {reward} for the colony' + (f' · MVP {top}' if top else ''), top, emoji=c[0])
    else:
        shared.mood = max(0, shared.mood - 2)
        stream_overlay.highlight(db, row.world, 'challenge_fail', f'{c[1]}: time ran out',
                                 f'{row.progress}/{row.goal}. {len(entries)} helped and still get a thank-you.', emoji='⌛')
    return paid


def board_bonus(m, db, skill):
    """+5% on the running challenge's aptitudes (skills challenges only)."""
    row = active(m, db)
    if not row or not skill:
        return 0, []
    measure = CHALLENGES[row.key][4]
    if measure[0] == 'skills' and skill in measure[1]:
        return BOARD_BONUS, [f'{CHALLENGES[row.key][0]} {CHALLENGES[row.key][1]} +{round(BOARD_BONUS * 100)}%']
    return 0, []


def participations(db, p):
    return db.execute(select(func.count()).select_from(Entry).join(Challenge, Challenge.id == Entry.challenge_id)
                      .where(Entry.channel_id == p.channel_id, Entry.canonical_uid == p.twitch_uid, Entry.amount > 0,
                             Challenge.state.in_(('won', 'lost')))).scalar() or 0


def wins(db, p):
    return db.execute(select(func.count()).select_from(Entry).join(Challenge, Challenge.id == Entry.challenge_id)
                      .where(Entry.channel_id == p.channel_id, Entry.canonical_uid == p.twitch_uid, Entry.amount > 0,
                             Challenge.state == 'won')).scalar() or 0


# ---------------------------------------------------------------- views

def view(m, db, p=None, provider='discord'):
    tick(m, db)
    row = active(m, db)
    live = is_live(m, db)
    if not row:
        st = state(m, db)
        if live and st.next_at and _utc(st.next_at) > _now():
            wait = int((_utc(st.next_at) - _now()).total_seconds() // 60) + 1
            when = f'The next stream challenge starts in about {wait} min.'
        elif live:
            when = 'A stream challenge starts soon.'
        else:
            when = 'Stream challenges only happen while the stream is live.'
        last = db.execute(select(Challenge).where(Challenge.world == runtime.DISCORD_WORLD_ID, Challenge.state.in_(('won', 'lost')))
                          .order_by(Challenge.id.desc())).scalars().first()
        tail = f" Last: {CHALLENGES[last.key][0]} {CHALLENGES[last.key][1]} {'won' if last.state == 'won' else 'missed'} ({last.progress}/{last.goal})." if last else ''
        return ('⚡ No stream challenge right now. ' if provider != 'discord' else '⚡ **No stream challenge right now.**\n') + when + tail
    c = CHALLENGES[row.key]
    left = max(0, int((_utc(row.ends_at) - _now()).total_seconds()))
    entries = db.execute(select(Entry).where(Entry.challenge_id == row.id).order_by(Entry.amount.desc())).scalars().all()
    mine = next((e.amount for e in entries if p and (e.channel_id, e.canonical_uid) == (p.channel_id, p.twitch_uid)), 0)
    if provider != 'discord':
        return (f'{c[0]} {c[1]}: {row.progress}/{row.goal} · {left // 60}:{left % 60:02d} left · you {mine} · help: {c[3]}')[:200]
    filled = round(min(1, row.progress / max(1, row.goal)) * 12)
    lines = [f'{c[0]} **STREAM CHALLENGE: {c[1].upper()}**', c[2] + '.', '',
             f"{'🟩' * filled}{'⬜' * (12 - filled)} **{row.progress}/{row.goal}** · {left // 60}:{left % 60:02d} left",
             f'How to help: {c[3]} in Twitch chat, or the same work on Discord',
             f'You: {mine}' + (' — keep going!' if mine else ' — jump in!')]
    if entries:
        lines.append('Top helpers: ' + ' · '.join(f"{['🥇', '🥈', '🥉'][i]} {e.name} {e.amount}" for i, e in enumerate(entries[:3])))
    lines.append(f'Win: +{WIN_SC} SC (+{PER_UNIT_SC} per point you add), +{WIN_CONTRIBUTION} Contribution, '
                 + ', '.join(f'{q} {n}' for n, q in c[8].items()) + f', season points; MVP +{MVP_SC} SC.')
    return '\n'.join(lines)


def overlay(m, db):
    tick(m, db)
    row = active(m, db)
    shown = row
    if not shown:
        recent = db.execute(select(Challenge).where(Challenge.world == runtime.DISCORD_WORLD_ID, Challenge.state.in_(('won', 'lost')))
                            .order_by(Challenge.id.desc())).scalars().first()
        if recent and recent.resolved_at and (_now() - _utc(recent.resolved_at)).total_seconds() < RESULT_SECONDS:
            shown = recent
    live = is_live(m, db)
    if not shown:
        return {'live': live, 'challenge': None}
    c = CHALLENGES[shown.key]
    entries = db.execute(select(Entry).where(Entry.challenge_id == shown.id, Entry.amount > 0).order_by(Entry.amount.desc())).scalars().all()
    from .autonomy import clean_name
    left = max(0, int((_utc(shown.ends_at) - _now()).total_seconds()))
    return {'live': live, 'challenge': {'id': shown.id, 'key': shown.key, 'emoji': c[0], 'title': c[1], 'text': c[2], 'how': c[3],
                                        'progress': shown.progress, 'goal': shown.goal, 'percent': round(min(100, shown.progress / max(1, shown.goal) * 100), 1),
                                        'seconds_left': left, 'minutes': c[7], 'state': shown.state, 'participants': len(entries),
                                        'top': [{'name': clean_name(e.name), 'amount': e.amount} for e in entries[:3]]}}


def week_summary(m, db, since):
    rows = db.execute(select(Challenge).where(Challenge.world == runtime.DISCORD_WORLD_ID, Challenge.started_at >= since,
                                              Challenge.state.in_(('won', 'lost')))).scalars().all()
    if not rows:
        return None
    won = [r for r in rows if r.state == 'won']
    ids = [r.id for r in rows]
    top = db.execute(select(Entry.name, func.sum(Entry.amount)).where(Entry.challenge_id.in_(ids)).group_by(Entry.channel_id, Entry.canonical_uid, Entry.name)
                     .order_by(func.sum(Entry.amount).desc()).limit(3)).all()
    people = db.execute(select(func.count(func.distinct(Entry.canonical_uid))).where(Entry.challenge_id.in_(ids))).scalar() or 0
    best = max(won, key=lambda r: r.goal, default=None)
    return {'count': len(rows), 'won': len(won), 'people': people, 'top': [(n, int(a)) for n, a in top],
            'best': (CHALLENGES[best.key][0] + ' ' + CHALLENGES[best.key][1], best.goal) if best else None}
