"""Private notifications: "Only you can see this" popups and a place to find them later.

Discord only allows a private (ephemeral) message as part of an interaction, so
notifications are kept in a small per-citizen inbox and shown privately the next
time that citizen uses any command or button. Each player chooses what pops up:

  important (default)  queue results, pauses and warnings they need to act on
  all                  also one-time tips and milestones
  off                  nothing pops up; everything stays in the inbox

Warnings are raised when the information is actually needed (a queue that will
run out of Energy or ingredients, a first mining failure, low Comfort), rather
than being repeated in every reply. `/menu` → Notifications lists recent items.
"""
import json
import logging
import requests
from datetime import timedelta
from sqlalchemy import Column, String, Integer, Text, DateTime, select, update, delete
from .db import Base

POPUP_MODES = {'important': 'Queue results, pauses and warnings', 'all': 'Everything, including tips and milestones',
               'off': 'Nothing pops up; check Notifications in /menu'}
KEEP = 40            # notifications kept per citizen
POPUP_LIMIT = 5      # items in one popup; the rest wait in the inbox
ICONS = {'queue': '⏱️', 'warning': '⚠️', 'tip': '💡', 'milestone': '🏆', 'info': '📬'}

# One-time explanations shown the first time a situation happens.
TIPS = {
    'comfort_low': '🛋️ **Comfort is low.** Below 20 Comfort, work is slower (−10% success, −1 Morale per task); below 10 it stops. '
                   'Relax (+20), sleep, or use a bed, seat, bath or clothing item.',
    'mining_failed': '⛏️ **Mining can fail.** A failed attempt still costs needs but gives 1 Stone Dust. Higher Harvesting, matching gear '
                     'and Determination raise your chance. Stone Dust sells, and some recipes use it.',
    'blocked': '⛔ **Tasks need enough Energy, Nutrition and Social (20+) and Comfort (10+).** Nothing is spent when a task is blocked. '
               '/life → Recover does every recovery that is ready.',
    'first_queue': '⏱️ **Queues work while you are away.** One attempt every 10 seconds. They pause (not fail) when needs or items run '
                   'short and resume by themselves. /settings → Autorecover: On lets them recover too.',
    'sleep_wait': '🛏️ **Sleep is on a 30-minute timer.** It refills Energy and Comfort to 100. Between sleeps, relax and use comfort items.',
}


class InboxItem(Base):
    __tablename__ = 'player_inbox_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    important = Column(Integer, nullable=False, default=1)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    seen = Column(Integer, nullable=False, default=0)


class InboxPrefs(Base):
    __tablename__ = 'player_inbox_prefs_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    popups = Column(String(12), nullable=False, default='important')
    tips = Column(Text, nullable=False, default='[]')


def install(m):
    InboxItem.__table__.create(m.engine, checkfirst=True)
    InboxPrefs.__table__.create(m.engine, checkfirst=True)


def prefs(db, channel, uid, create=False):
    row = db.get(InboxPrefs, (channel, uid))
    if row is None and create:
        row = InboxPrefs(channel_id=channel, canonical_uid=uid, popups='important', tips='[]')
        db.add(row)
        db.flush()
    return row


def popup_mode(db, channel, uid):
    row = prefs(db, channel, uid)
    return row.popups if row is not None and row.popups in POPUP_MODES else 'important'


def add(m, db, channel, uid, kind, text, important=True, seen=False):
    db.add(InboxItem(channel_id=channel, canonical_uid=uid, kind=kind, important=int(bool(important)),
                     text=text[:1500], created_at=m.now(), seen=int(bool(seen))))
    db.flush()
    ids = [r for r in db.scalars(select(InboxItem.id).where(InboxItem.channel_id == channel, InboxItem.canonical_uid == uid)
                                   .order_by(InboxItem.id.desc()).offset(KEEP))]
    if ids:
        db.execute(delete(InboxItem).where(InboxItem.id.in_(ids)))


def tip(m, db, channel, uid, key):
    """Queue a one-time explanation; returns True the first time only."""
    row = prefs(db, channel, uid, create=True)
    seen = json.loads(row.tips)
    if key in seen or key not in TIPS:
        return False
    row.tips = json.dumps(seen + [key])
    add(m, db, channel, uid, 'tip', TIPS[key], important=False)
    return True


def pending(db, channel, uid):
    mode = popup_mode(db, channel, uid)
    if mode == 'off':
        return []
    query = select(InboxItem).where(InboxItem.channel_id == channel, InboxItem.canonical_uid == uid, InboxItem.seen == 0)
    if mode == 'important':
        query = query.where(InboxItem.important == 1)
    return list(db.scalars(query.order_by(InboxItem.id)))


def unread_count(db, channel, uid):
    return len(list(db.scalars(select(InboxItem.id).where(InboxItem.channel_id == channel, InboxItem.canonical_uid == uid,
                                                         InboxItem.seen == 0))))


def mark_seen(db, ids):
    if ids:
        db.execute(update(InboxItem).where(InboxItem.id.in_(ids)).values(seen=1))


def mark_all_seen(db, channel, uid):
    db.execute(update(InboxItem).where(InboxItem.channel_id == channel, InboxItem.canonical_uid == uid).values(seen=1))


def popup_embed(items, more=0):
    lines = [f"{ICONS.get(i.kind, '📬')} {i.text}" for i in items]
    if more:
        lines.append(f'…and {more} more in /menu → Notifications.')
    return {'title': '📬 For you', 'description': '\n\n'.join(lines)[:4000], 'color': 0x5865F2,
            'footer': {'text': 'Only you can see this · change what pops up in /settings'}}


def _canonical(m, db, discord_uid):
    ident = db.execute(select(m.Identity).where(m.Identity.channel_id == m.DISCORD_WORLD_ID, m.Identity.provider == 'discord',
                                                m.Identity.provider_uid == str(discord_uid))).scalar_one_or_none()
    return ident.canonical_uid if ident else 'discord:' + str(discord_uid)


def deliver(m, payload, discord_uid):
    """Send unseen notifications as a private follow-up to this interaction."""
    app_id, token = str(payload.get('application_id') or ''), str(payload.get('token') or '')
    if not app_id or not token or not discord_uid:
        return False
    with m.SessionLocal() as db:
        uid = _canonical(m, db, discord_uid)
        p = db.execute(select(m.Player).where(m.Player.channel_id == m.DISCORD_WORLD_ID, m.Player.twitch_uid == uid)).scalar_one_or_none()
        if p is not None:
            m.extras.touch(m, db, p)      # welcome-back summary and reminders
            db.commit()
        items = pending(db, m.DISCORD_WORLD_ID, uid)
        if not items:
            return False
        shown, more = items[:POPUP_LIMIT], max(0, len(items) - POPUP_LIMIT)
        embed = popup_embed(shown, more)
        embed['description'] = m.discord_command_copy(embed['description'])[:4000]
        body = {'embeds': [embed], 'flags': 64, 'allowed_mentions': {'parse': []}}
        try:
            response = requests.post(f'https://discord.com/api/v10/webhooks/{app_id}/{token}', json=body, timeout=8)
        except requests.RequestException:
            logging.getLogger(__name__).warning('Private notification follow-up failed; kept for next time')
            return False
        if not 200 <= response.status_code < 300:
            logging.getLogger(__name__).warning('Private notification follow-up rejected (HTTP %s)', response.status_code)
            return False
        mark_seen(db, [i.id for i in shown])
        db.commit()
        return True


def inbox_text(m, db, p):
    rows = list(db.scalars(select(InboxItem).where(InboxItem.channel_id == p.channel_id, InboxItem.canonical_uid == p.twitch_uid)
                           .order_by(InboxItem.id.desc()).limit(12)))
    mode = popup_mode(db, p.channel_id, p.twitch_uid)
    lines = ['📬 NOTIFICATIONS', f'Popups: **{mode}** — {POPUP_MODES[mode]}.', '']
    if not rows:
        lines.append('Nothing yet. Queue results, warnings and tips will appear here.')
    for r in rows:
        age = m.now() - m.as_utc(r.created_at)
        when = f'{int(age.total_seconds() // 60)}m ago' if age < timedelta(hours=1) else f'{int(age.total_seconds() // 3600)}h ago' if age < timedelta(days=2) else f'{age.days}d ago'
        lines.append(f"{'🔵 ' if not r.seen else ''}{ICONS.get(r.kind, '📬')} {r.text.splitlines()[0][:220]} · *{when}*")
    return '\n'.join(lines)


# ---------------------------------------------------------------- when information is needed

def queue_warnings(m, db, p, task, count):
    """Short warnings for a queue that will not finish as it stands; [] when it will."""
    tq = m.task_queue
    if task not in tq.choices(m) or count <= 0:
        return []
    costs, energy, _ = tq.specification(m, task)
    life = m.life_state(db, p)
    need = m.finish_forecast(energy, count)
    short = [f'{k.title()} {getattr(life, k)}/{v}' for k, v in need.items() if getattr(life, k) < v]
    out = []
    if short:
        fix = 'auto-recover will top them up' if m.qol.autorecover_on(db, p.channel_id, p.twitch_uid) else \
              'relax or eat first, or turn on /settings → Autorecover'
        out.append(f"Needs won't last all {count} attempts ({', '.join(short)}). It will pause; {fix}.")
    for key, n in costs.items():
        have = m.material_amount(db, p, key)
        if have < n * count:
            source = m.material_source(key).split(' or ')[0].split(';')[0].rstrip('. ')
            out.append(f'{m.resource_name(key)}: enough for {have // n} of {count} attempts. Get more: {source}.')
    return out


def after_command(m, discord_uid, name, command, options, result):
    """Raise warnings and one-time tips from what just happened; they pop up privately."""
    with m.SessionLocal() as db:
        uid = _canonical(m, db, discord_uid)
        channel = m.DISCORD_WORLD_ID
        p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == uid)).scalar_one_or_none()
        if p is None:
            return
        text = str(result or '')
        if command == 'queue':
            row = db.get(m.task_queue.TaskQueue, (channel, uid))
            fresh = row is not None and row.state == 'running' and row.total == row.remaining
            if fresh and not list(db.scalars(select(InboxItem.id).where(InboxItem.channel_id == channel, InboxItem.canonical_uid == uid,
                                                                           InboxItem.kind == 'warning', InboxItem.seen == 0))):
                for warning in queue_warnings(m, db, p, row.task, row.remaining):
                    add(m, db, channel, uid, 'warning', warning)
                tip(m, db, channel, uid, 'first_queue')
        if 'MINING FAILED' in text or ('Stone Dust' in text and 'FAILED' in text):
            tip(m, db, channel, uid, 'mining_failed')
        if 'TASK BLOCKED' in text:
            tip(m, db, channel, uid, 'blocked')
        if 'sleep again in' in text:
            tip(m, db, channel, uid, 'sleep_wait')
        if m.life_state(db, p).comfort < m.COMFORT_SLOW:
            tip(m, db, channel, uid, 'comfort_low')
        m.extras.goal_completed(m, db, p, text)
        db.commit()
