"""Quiet hours: a daily window, in the citizen's own time zone, when queue DMs wait.

A citizen sets a window such as 23:00–08:00 Europe/London (an IANA name, DST-correct through the
standard library's zoneinfo, or a fixed offset such as UTC+2; it may cross midnight). Only direct-message
queue alerts wait: channel mentions, Twitch alerts, the inbox and private popups behave as always.

Holding happens in the Discord worker, before an alert is claimed (`check`), so it never spends a delivery
attempt or a lease: a due DM alert whose recipient is inside the window gets next_at = the window's end
(UTC) and a row in the held table. When a held alert is due and its recipient is outside quiet hours, every
due DM alert of that recipient is claimed together (`claim_release`: one conditional update per row, as
claim() does) and goes out as one summary DM, or as the normal alert with a 🌙 line when it is the only
one. Success marks them all sent; a failure applies the worker's retry policy to each; closed DMs mark each
one unread in Notifications. Turning quiet hours off, or moving the window so the citizen is outside it,
makes held alerts due at once. A pause alert superseded while held is dropped with its held row.

Two additive tables: the setting (no row: off) and the held alerts. Everything is stored in UTC.
"""
import difflib
import functools
import re
import zoneinfo
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from sqlalchemy import Column, String, Integer, DateTime, select, update, delete, or_
from .db import Base
from .queue_notifications import Notice, NoticeEvent, DM_PREFIX
from . import runtime
from .db import SessionLocal
from .models import Identity

TITLE = '🌙 While your quiet hours were on'
HELD_LINE = '🌙 Held during your quiet hours.'
SHOWN = 15                 # alerts listed in one summary; the rest are counted
TEXT_ROOM = 3000           # characters of alert lines in one summary (Discord allows 4000 in a message)
OFFSET = re.compile(r'(?:UTC|GMT)?\s*([+\-])\s*(\d{1,2})(?:[:.]?(\d{2}))?', re.I)
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+)*')
TIME = re.compile(r'(\d{1,2})(?:[:.](\d{2}))?')
TIME_RULE = 'a 24-hour time such as 23 or 23:00 (00:00–23:59)'
KINDS = {'completed': ('✅', 'Completed'), 'paused': ('⏸️', 'Paused'), 'cancelled': ('⏹️', 'Cancelled'), 'error': ('⛔', 'Stopped')}


class QuietHours(Base):
    """One row per citizen with quiet hours; a missing row means they are off."""
    __tablename__ = 'player_quiet_hours_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    tz = Column(String(48), nullable=False)
    start_min = Column(Integer, nullable=False)
    end_min = Column(Integer, nullable=False)


class HeldAlert(Base):
    """A DM alert waiting for the end of its recipient's quiet hours (its outbox row keeps the time)."""
    __tablename__ = 'quiet_held_alerts_v1'
    notice_id = Column(String(32), primary_key=True)
    channel_id = Column(String(64), nullable=False)
    recipient = Column(String(96), nullable=False, index=True)
    held_at = Column(DateTime(timezone=True), nullable=False)


def install(m):
    QuietHours.__table__.create(runtime.engine, checkfirst=True)
    HeldAlert.__table__.create(runtime.engine, checkfirst=True)


def row(db, channel, uid):
    return db.get(QuietHours, (channel, uid))


def merge(db, channel, source, target):
    """Account linking: the target's quiet hours win; otherwise the source's move over."""
    src = db.get(QuietHours, (channel, source))
    if src is None:
        return
    if db.get(QuietHours, (channel, target)) is None:
        src.canonical_uid = target
    else:
        db.delete(src)


# ---------------------------------------------------------------- time zones and the window

def _offset(text):
    """A fixed offset ('UTC', 'UTC+2', '+5:30', '-5', 'GMT-3') as a timedelta; None when `text` is not one."""
    t = str(text or '').strip().replace('−', '-')
    if t.casefold() in {'utc', 'gmt', 'z'}:
        return timedelta(0)
    match = OFFSET.fullmatch(t)
    if not match or int(match[3] or 0) > 59:
        return None
    delta = timedelta(hours=int(match[2]), minutes=int(match[3] or 0))
    return -delta if match[1] == '-' else delta


def offset_name(delta):
    """'UTC', 'UTC+2', 'UTC-3', 'UTC+5:30'."""
    if not delta:
        return 'UTC'
    minutes = abs(int(delta.total_seconds())) // 60
    h, mi = divmod(minutes, 60)
    return f"UTC{'-' if delta < timedelta(0) else '+'}{h}" + (f':{mi:02d}' if mi else '')


@functools.lru_cache(maxsize=1)
def _names():
    """{casefolded IANA name: name} from the server's time-zone database; {} when it has none."""
    try:
        found = zoneinfo.available_timezones()
    except Exception:
        found = set()
    return {n.casefold(): n for n in found}


@functools.lru_cache(maxsize=512)
def zone(name):
    """The tzinfo of a stored time zone, or None when this server cannot load it."""
    delta = _offset(name)
    if delta is not None:
        return timezone(delta) if delta else timezone.utc
    try:
        return ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _suggest(text):
    names = _names()
    city = text.casefold().rsplit('/', 1)[-1]
    same = sorted(n for n in names.values() if n.rsplit('/', 1)[-1].casefold() == city)
    if same:
        return same[0]
    close = difflib.get_close_matches(text.casefold(), list(names), n=1, cutoff=0.75)
    return names[close[0]] if close else ''


def parse_zone(text):
    """(stored name, '') for an IANA name or a fixed offset, or ('', why not) — a refusal ends 'Nothing changed.'."""
    raw = str(text or '').strip()
    if not raw:
        return '', '🌙 Enter a time zone, such as Europe/London or UTC+2. Nothing changed.'
    delta = _offset(raw)
    if delta is not None:
        if not -timedelta(hours=12) <= delta <= timedelta(hours=14):
            return '', '🌙 Offsets run from UTC-12 to UTC+14. Nothing changed.'
        return offset_name(delta), ''
    if OFFSET.fullmatch(raw.replace('−', '-')):
        return '', f'🌙 "{raw[:20]}" is not a valid offset: minutes run from 00 to 59, e.g. UTC+5:30. Nothing changed.'
    name = raw.replace(' ', '_')
    names = _names()
    found = names.get(name.casefold()) if NAME.fullmatch(name) and len(name) <= 48 else None
    if found:
        return found, ''
    if not names and NAME.fullmatch(name) and len(name) <= 48:
        try:
            ZoneInfo(name)                     # no list of names, but the zone itself may still load
            return name, ''
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            pass
        return '', (f'🌙 This server has no time-zone database, so "{raw[:48]}" cannot be used. Use an offset instead, '
                    'e.g. UTC+1 (and change it when your clocks change). Nothing changed.')
    hint = _suggest(name) if names else ''
    return '', (f'🌙 "{raw[:48]}" is not a time zone I know. Use a name such as Europe/London or America/New_York, '
                'or an offset such as UTC+2.' + (f' Did you mean {hint}?' if hint else '') + ' Nothing changed.')


def parse_time(text):
    """Minutes after midnight for 'HH' or 'HH:MM' on a 24-hour clock, else None."""
    match = TIME.fullmatch(str(text or '').strip())
    if not match:
        return None
    h, mi = int(match[1]), int(match[2] or 0)
    return h * 60 + mi if h < 24 and mi < 60 else None


def clock(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def describe(r):
    return f'{clock(r.start_min)}–{clock(r.end_min)} ({r.tz})'


def _inside(r, at, tz):
    local = at.astimezone(tz)
    t = local.hour * 60 + local.minute + (local.second + local.microsecond / 1e6) / 60
    s, e = r.start_min, r.end_min
    return s <= t < e if s < e else (t >= s or t < e)


def inside(r, now):
    """Whether `now` (UTC) falls in the citizen's window, by their own wall clock. A zone this server cannot
    load holds nothing, so alerts are never stuck."""
    tz = zone(r.tz) if r is not None else None
    return tz is not None and _inside(r, now, tz)


def window_end(r, now):
    """The next time (UTC) the window ends after `now`: the end of the current window, or of the next one.

    Built from the local date and wall clock, so a daylight-saving change in between is counted; at a
    repeated or skipped local hour the earliest moment that is really outside the window wins."""
    tz = zone(r.tz) or timezone.utc
    local = now.astimezone(tz)
    h, mi = divmod(r.end_min, 60)
    found = sorted({datetime.combine(local.date() + timedelta(days=d), time(h, mi), tzinfo=tz).replace(fold=f).astimezone(timezone.utc)
                    for d in range(3) for f in (0, 1)})
    found = [at for at in found if at > now]
    return next((at for at in found if not _inside(r, at, tz)), found[0])


def stamp(at):
    return f'<t:{int(at.timestamp())}:t>'


# ---------------------------------------------------------------- who an alert is for

def citizen_of(m, db, channel, recipient):
    """The canonical citizen a Discord user id belongs to in this world."""
    ident = db.execute(select(Identity.canonical_uid).where(Identity.channel_id == channel, Identity.provider == 'discord',
                                                              Identity.provider_uid == str(recipient))).scalars().first()
    return ident or 'discord:' + str(recipient)


def recipients(m, db, channel, uid):
    """Every Discord user id that is this citizen."""
    found = set(db.scalars(select(Identity.provider_uid).where(Identity.channel_id == channel, Identity.provider == 'discord',
                                                                 Identity.canonical_uid == uid)))
    if uid.startswith('discord:'):
        found.add(uid.split(':', 1)[1])
    return found


def _held_ids(m, db, channel, uid):
    """This citizen's held alerts that are still waiting."""
    who = recipients(m, db, channel, uid)
    if not who:
        return []
    return list(db.scalars(select(HeldAlert.notice_id).join(Notice, Notice.id == HeldAlert.notice_id).where(
        HeldAlert.channel_id == channel, HeldAlert.recipient.in_(who), Notice.state == 'pending')))


def _reschedule(m, db, channel, uid):
    """Held alerts follow the new setting: due at once when the citizen is outside quiet hours (the worker then
    sends them as one message), else at the new window's end. Returns how many go out now."""
    ids = _held_ids(m, db, channel, uid)
    if not ids:
        return 0
    now = runtime.now()
    r = row(db, channel, uid)
    when = window_end(r, now) if r is not None and inside(r, now) else now
    db.execute(update(Notice).where(Notice.id.in_(ids), Notice.state == 'pending').values(next_at=when)
               .execution_options(synchronize_session=False))
    return len(ids) if when == now else 0


def forget(db, ids):
    """Held rows of alerts that were sent, failed for good or superseded."""
    ids = list(ids)
    if ids:
        db.execute(delete(HeldAlert).where(HeldAlert.notice_id.in_(ids)).execution_options(synchronize_session=False))


def forget_superseded(db, ids):
    """A held pause alert that was superseded (the queue resumed or was replaced) is never sent: drop its held row."""
    gone = list(db.scalars(select(Notice.id).where(Notice.id.in_(ids), Notice.state == 'superseded')))
    forget(db, gone)


# ---------------------------------------------------------------- setting it

def _mode_note(db, p):
    from . import qol
    mode = qol.alert_mode(db, p.channel_id, p.twitch_uid)
    if mode in {'dm', 'quiet'}:
        return ''
    return f' They only affect direct-message alerts; yours are set to {qol.ALERT_LABELS[mode]} (/settings alerts:dm).'


def _on_the_way(released):
    if not released:
        return ''
    return ' 1 held alert is on its way now.' if released == 1 else f' {released} held alerts are on their way now, as one message.'


def set_hours(m, db, p, tz, start, end):
    """Set or change quiet hours. Returns the message; a refusal ends 'Nothing changed.' and changes nothing."""
    name, problem = parse_zone(tz)
    if problem:
        return problem
    begin, finish = parse_time(start), parse_time(end)
    if begin is None:
        return f'🌙 Start must be {TIME_RULE}. Nothing changed.'
    if finish is None:
        return f'🌙 End must be {TIME_RULE}. Nothing changed.'
    if begin == finish:
        return f'🌙 Start and end are both {clock(begin)}, so there would be no quiet window. Nothing changed.'
    current = row(db, p.channel_id, p.twitch_uid)
    if current is not None and (current.tz, current.start_min, current.end_min) == (name, begin, finish):
        return f'🌙 Your quiet hours are already {describe(current)}. Nothing changed.'
    if current is None:
        current = QuietHours(channel_id=p.channel_id, canonical_uid=p.twitch_uid, tz=name, start_min=begin, end_min=finish)
        db.add(current)
        text = f'🌙 Quiet hours set: {describe(current)}.'
    else:
        was = describe(current)
        current.tz, current.start_min, current.end_min = name, begin, finish
        text = f'🌙 Quiet hours changed: {describe(current)} (was {was}).'
    db.flush()
    now = runtime.now()
    text += ' DM alerts in that window wait and arrive as one message when it ends.'
    if inside(current, now):
        text += f' They are on now, until {stamp(window_end(current, now))}.'
    return text + _on_the_way(_reschedule(m, db, p.channel_id, p.twitch_uid)) + _mode_note(db, p)


def turn_off(m, db, p):
    """Quiet hours off; anything held goes out now, as one message."""
    current = row(db, p.channel_id, p.twitch_uid)
    if current is None:
        return '🌙 Quiet hours are already off. Nothing changed.'
    db.delete(current)
    db.flush()
    return '🌙 Quiet hours off: DM alerts arrive as they happen again.' + _on_the_way(_reschedule(m, db, p.channel_id, p.twitch_uid))


# ---------------------------------------------------------------- what the citizen sees

def settings_line(db, channel, uid, mode, now):
    """The quiet-hours line of the Discord settings screen."""
    r = row(db, channel, uid)
    if r is None:
        return ('• Quiet hours: off — a daily window when DM alerts wait, then arrive as one message '
                '(/menu → You → Settings → Quiet hours).')
    if zone(r.tz) is None:
        return f'• Quiet hours: {describe(r)} — this server cannot load that time zone, so nothing is held. Choose an offset such as UTC+1.'
    text = f'• Quiet hours: {describe(r)} — '
    if inside(r, now):
        text += f'🌙 on now: DM alerts wait and arrive as one message at {stamp(window_end(r, now))}.'
    else:
        text += f'DM alerts in that window wait and arrive as one message when it ends (next at {stamp(window_end(r, now))}).'
    if mode not in {'dm', 'quiet'}:
        text += ' They only affect direct-message alerts.'
    return text


def short(db, channel, uid, now):
    """'🌙 Quiet hours 23:00–08:00' (', on now') for the status screen, or ''."""
    r = row(db, channel, uid)
    if r is None:
        return ''
    return f'🌙 Quiet hours {clock(r.start_min)}–{clock(r.end_min)}' + (', on now' if inside(r, now) else '')


def delivery_line(db, channel, uid, now):
    """The sentence queue status adds for DM alerts, or ''."""
    r = row(db, channel, uid)
    if r is None or zone(r.tz) is None:
        return ''
    at = stamp(window_end(r, now))
    if inside(r, now):
        return f'🌙 Quiet hours are on now, {describe(r)}: DM alerts wait and arrive as one message at {at}.'
    return f'🌙 Quiet hours {describe(r)}: DM alerts wait and arrive as one message at {at}.'


def held_line(m, db, notice):
    """For a waiting alert that is held: when it arrives. '' when it is not held."""
    from .game.players import as_utc
    if db.get(HeldAlert, notice.id) is None:
        return ''
    return (f'🌙 Held for your quiet hours: this alert arrives at {stamp(as_utc(notice.next_at))}, with any others as one message. '
            'Your results are saved.')


# ---------------------------------------------------------------- the Discord worker

def check(m, notice_id):
    """What the Discord worker does with one due alert, before any claim:
      'send'                  the usual claim and send (not a DM, or nothing to hold or release)
      None                    nothing now (held until the window ends, or no longer due)
      (channel, recipient)    release every due DM alert of that recipient as one message
    Holding is a conditional update of next_at, so it spends no attempt and no lease, and only one worker
    can hold a given due alert."""
    from .game.players import as_utc
    with SessionLocal() as db:
        notice = db.get(Notice, notice_id)
        if notice is None or notice.provider != 'discord' or not str(notice.message_channel or '').startswith(DM_PREFIX):
            return 'send'
        now = runtime.now()
        if notice.state not in ('pending', 'sending') or as_utc(notice.next_at) > now:
            return None
        channel, recipient = notice.channel_id, str(notice.recipient)
        r = row(db, channel, citizen_of(m, db, channel, recipient))
        if r is not None and inside(r, now):
            held = db.execute(update(Notice).where(Notice.id == notice_id, Notice.provider == 'discord', Notice.state.in_(['pending', 'sending']),
                                                   Notice.next_at <= now).values(state='pending', next_at=window_end(r, now))
                              .execution_options(synchronize_session=False))
            if held.rowcount == 1 and db.get(HeldAlert, notice_id) is None:
                db.add(HeldAlert(notice_id=notice_id, channel_id=channel, recipient=recipient, held_at=now))
            db.commit()
            return None
        waiting = db.execute(select(HeldAlert.notice_id).join(Notice, Notice.id == HeldAlert.notice_id).where(
            HeldAlert.channel_id == channel, HeldAlert.recipient == recipient, Notice.state.in_(['pending', 'sending']),
            Notice.next_at <= now).limit(1)).first()
        return (channel, recipient) if waiting else 'send'


def claim_release(m, channel, recipient):
    """Claim every due DM alert of one recipient together, for one message.

    One conditional update per row (state pending/sending and due, as claim() does), in id order so two
    workers lock rows in the same order, and one commit: a row is claimed by exactly one worker, which then
    owns its lease. Held rows of alerts that can no longer be sent (superseded, sent, failed) are dropped.
    Returns detached snapshots, oldest alert first."""
    from .game.players import as_utc
    with SessionLocal() as db:
        stale = list(db.scalars(select(HeldAlert.notice_id).outerjoin(Notice, Notice.id == HeldAlert.notice_id).where(
            HeldAlert.channel_id == channel, HeldAlert.recipient == recipient,
            or_(Notice.id.is_(None), Notice.state.notin_(['pending', 'sending'])))))
        forget(db, stale)
        now = runtime.now()
        ids = list(db.scalars(select(Notice.id).where(Notice.provider == 'discord', Notice.channel_id == channel, Notice.recipient == recipient,
                                                      Notice.message_channel.startswith(DM_PREFIX), Notice.state.in_(['pending', 'sending']),
                                                      Notice.next_at <= now).order_by(Notice.id)))
        claimed = []
        for notice_id in ids:
            result = db.execute(update(Notice).where(Notice.id == notice_id, Notice.provider == 'discord', Notice.state.in_(['pending', 'sending']),
                                                     Notice.next_at <= now).values(state='sending', next_at=now + timedelta(seconds=120),
                                                                                    attempts=Notice.attempts + 1)
                                .execution_options(synchronize_session=False))
            if result.rowcount == 1:
                claimed.append(notice_id)
        db.commit()
        batch = []
        for notice_id in claimed:
            n_ = db.get(Notice, notice_id)
            event = db.get(NoticeEvent, notice_id)
            batch.append(SimpleNamespace(**{k: getattr(n_, k) for k in ('id', 'recipient', 'message_channel', 'content', 'attempts', 'provider', 'channel_id')},
                                         kind=event.kind if event else '', created_at=as_utc(event.created_at) if event else None))
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(batch, key=lambda x: (x.created_at or far, x.id))


def _after(lines, header):
    """The line after a section header in an alert's saved text, or ''."""
    for i, line in enumerate(lines[:-1]):
        if line.strip() == header:
            return lines[i + 1].strip()
    return ''


def brief(notice):
    """One alert on one line: kind, task, attempts, key totals and when it happened (from its saved text)."""
    lines = str(notice.content or '').splitlines()
    head = lines[0] if lines else ''
    kind = notice.kind or next((k for k, word in (('paused', 'PAUSED'), ('cancelled', 'CANCELLED'), ('error', 'STOPPED'),
                                                  ('completed', 'COMPLETED')) if word in head), '')
    icon, word = KINDS.get(kind, ('📬', 'Queue update'))
    parts = [f'{icon} **{word}**']
    if len(lines) > 1 and lines[1].strip():
        parts.append(lines[1].strip()[:60])
    text = '\n'.join(lines)
    done = re.search(r'Attempts completed: (\d+)/(\d+)', text)
    if done:
        parts.append(f'{done[1]}/{done[2]} attempts')
    tally = re.search(r'Succeeded: (\d+); failed: (\d+)', text)
    if tally:
        parts.append(f'{tally[1]} succeeded, {tally[2]} failed')
    gained = _after(lines, 'TOTAL ITEMS GAINED')
    if gained and gained != 'None':
        parts.append('gained ' + (gained if len(gained) <= 70 else gained[:69].rsplit(',', 1)[0] + '…'))
    if kind == 'paused':
        reason = _after(lines, 'PAUSE REASON')
        if reason:
            parts.append(reason[:80])
    if notice.created_at is not None:
        parts.append(stamp(notice.created_at))
    return ' · '.join(parts)


def summary(m, batch):
    """(message data, first line) for several held alerts: one card, its lines kept within Discord's limits."""
    from . import ui
    from .notice import FOOTER
    lines, used = [], 0
    for notice in batch:
        line = brief(notice)
        if len(lines) >= SHOWN or used + len(line) > TEXT_ROOM:
            break
        lines.append(line)
        used += len(line) + 1
    more = len(batch) - len(lines)
    if more:
        lines.append(f'…and {more} more in /menu → Notifications.')
    owner = str(batch[0].recipient)
    first = f'{len(batch)} queue alerts waited for the end of your quiet hours.'
    embed = {'title': TITLE, 'description': '\n'.join(lines)[:4000], 'color': 0x5865F2, 'footer': {'text': FOOTER}}
    rows = [ui.row(ui.button('Queue', ui.cid(owner, 'qv'), emoji='📋'), ui.button('Status', ui.cid(owner, 'st'), emoji='📊'),
                   ui.button('Notifications', ui.cid(owner, 'mv', 'inbox'), emoji='📬'))] if owner.isdigit() else []
    return {'embeds': [embed], 'components': rows}, first
