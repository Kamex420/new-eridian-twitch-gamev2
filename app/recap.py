"""The weekly recap: every Sunday the bot posts the week in New Eridian to Discord.

  🏆 Top contributors      the week's season points, Contribution and actions
  🎒 Biggest hauls         the most items brought in (by hand and by Seedlings), and the single biggest Seedling haul
  🏛️ Society               the tier, progress to the next one and how every stat moved this week
  🗳️ Votes and projects    what the colony voted for and what it finished building
  ⚡ Stream challenges      how many were won, who helped most
  🏅 Trophies              who earned what
  🏁 Season                the chapter, days left and the top three
  🌱 Seedling moments      the funniest things the Seedlings did on their own
  👋 New citizens          who arrived this week

When the optional Claude features are on (app/ai.py), the recap opens with "📖 This week on Avesta", a short story
written from the facts below. It is written once a week (and again only if the kept one is old, see STORY_FRESH), never
inside the game lock: the community timer calls prepare() before taking the lock, and the owner's menu preview writes it
too; everything else just reads the kept story, and a recap without one is exactly the recap without the feature.

It posts to RECAP_CHANNEL_ID (or DISCORD_GAME_CHANNEL_ID) on Sundays from RECAP_HOUR (UTC, default 18), once a
week. Moderators can preview it or post it now (/mod or !recap post), and GET /api/v1/recap shows it as text.
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, DateTime, select, func
from .db import Base, SessionLocal
from . import ai, runtime
from .models import Player
from .models import Society

RECAP_HOUR = min(23, max(0, int(os.getenv('RECAP_HOUR', '18'))))
FUNNY = ('fail', 'empty', 'nothing', 'slip', 'trip', 'nap', 'dozed', 'argu', 'rocky', 'duck', 'spill', 'lost', 'forgot', 'sneez', 'hum',
         'dance', 'sing', 'wander', 'chat', 'gossip', 'rumor', 'rumour', 'too tired', 'hungry', 'snack', 'games', 'joke', 'laugh')
COLOUR = 0x7EE3B0

STORY_HEADING = '📖 This week on Avesta'
STORY_FRESH = timedelta(hours=6)     # a kept story older than this was written from other numbers: it is written again
STORY_RETRY = timedelta(minutes=10)  # the timer asks Claude again no sooner than this after a try that gave nothing
STORY_FIELD = 1000                   # the story's longest length (a Discord field holds 1024 characters)
EMBED_LIMIT = 6000                   # Discord: all the characters of one embed
STORY_SYSTEM = (
    'You write the short weekly story that opens the Sunday recap for the players of New Eridian, a young settlement on '
    'the planet Avesta. Write one warm, gentle story of 90 to 130 words, in two or three short paragraphs. '
    'Use only the facts given in the message. Keep every name and number exactly as given. Do not invent events, '
    'people, places or numbers; if the week was quiet, say so kindly. '
    'Plain text only: no headings, no lists, no markdown, no @mentions, no hashtags and no links.')
_asked = {}                          # story key -> when the timer last asked Claude for it (this process only)


class RecapPost(Base):
    __tablename__ = 'weekly_recaps_v1'
    world = Column(String(64), primary_key=True)
    week = Column(String(10), primary_key=True)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    stats = Column(String(400), nullable=False, default='{}')     # society stats when it was posted, for next week's changes
    sent = Column(Integer, nullable=False, default=0)


def _now():
    return datetime.now(timezone.utc)


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def channel_id():
    return (os.getenv('RECAP_CHANNEL_ID', '') or os.getenv('DISCORD_GAME_CHANNEL_ID', '')).strip()


def week_start(when=None):
    when = when or _now()
    return (when - timedelta(days=when.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _names(db, pairs):
    out = {}
    from .autonomy import clean_name
    for channel, uid in pairs:
        p = db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == uid)).scalar_one_or_none()
        out[(channel, uid)] = clean_name(p.display_name) if p else 'Citizen'
    return out


def _stats(db):
    from .game.players import society
    s = society(db, runtime.DISCORD_WORLD_ID)
    return {k: getattr(s, k) for k in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation', 'population')}


def story_key(when=None):
    """Where the week's story is kept (ai.AiText): one per world and week, shared by the preview and the post."""
    return f'recap:{runtime.DISCORD_WORLD_ID}:{week_start(when).strftime("%Y-%m-%d")}'


def kept_story(db, when=None):
    """This week's story if it was written recently enough (STORY_FRESH) to match the numbers beside it, else ''."""
    row = db.get(ai.AiText, story_key(when))
    if row is None or runtime.now() - _utc(row.created_at) > STORY_FRESH:
        return ''
    return row.text


def plain_facts(title, sections):
    """The week's sections as plain text for Claude: no Markdown bold, italics or code marks."""
    def plain(text):
        text = re.sub(r'\*\*|__|~~|`', '', text)
        return re.sub(r'\*([^*\n]+)\*', r'\1', text)
    return plain(title) + '\n\n' + '\n\n'.join(f'{plain(h)}\n{plain(t)}' for h, t in sections)


def _fit(text):
    """The story cut at the end of a sentence to fit one Discord field."""
    text = (text or '').strip()
    if len(text) <= STORY_FIELD:
        return text
    head = text[:STORY_FIELD]
    end = max(head.rfind('. '), head.rfind('! '), head.rfind('? '), head.rfind('\n'))
    if end > STORY_FIELD // 2:
        return head[:end + 1].strip()
    return head.rsplit(' ', 1)[0].rstrip(' ,;:') + '…'


def story(db, when, title, sections, write=False):
    """The week's story: the kept one, or with write=True one written now from `sections` (the week's real numbers and
    names). Writing is one API call and only happens outside the game lock; a failed call leaves ''."""
    found = kept_story(db, when)
    if found or not write or ai.locked() or not ai.enabled('recap'):
        return _fit(found)
    old = db.get(ai.AiText, story_key(when))
    if old is not None:                         # kept, but from an earlier day's numbers: write it again
        db.delete(old)
        db.flush()
    prompt = 'The week in New Eridian, as it was recorded:\n\n' + plain_facts(title, sections)
    return _fit(ai.written(db, 'recap', story_key(when), STORY_SYSTEM, prompt, max_tokens=350, timeout=20))


def prepare(when=None):
    """Write this week's story ahead of the Sunday post. The community timer calls this BEFORE it takes the game lock
    (an API call inside it would hold up every player); the locked recap.tick() then only reads the kept story.
    Returns whether a try was made. A try that gave nothing is not repeated for STORY_RETRY."""
    from . import seasons
    when = when or _now()
    if not due(when) or not channel_id() or not os.getenv('DISCORD_BOT_TOKEN', '').strip() or not ai.enabled('recap') or ai.locked():
        return False
    key, now = story_key(when), runtime.now()
    if key in _asked and now - _asked[key] < STORY_RETRY:
        return False
    with SessionLocal() as db:
        row = db.get(RecapPost, (runtime.DISCORD_WORLD_ID, seasons.week_key(when)))
        if (row and row.sent) or kept_story(db, when):
            return False
        _asked[key] = now
        build(db, when, write=True)
        db.commit()
    return True


def build(db, when=None, write=False):
    """The recap as (title, [(section heading, text)], plain text).

    The week's story (STORY_HEADING) comes first when one was kept. With write=True a missing one is written now, but only
    where the game lock is not held (ai.locked()); everywhere else, and when Claude is off, the recap is the one without it."""
    from .game.players import resource_name
    from .game.rules import SOCIETY_TIERS
    from .game.world import society_tier
    from . import seasons, votes, live_events, trophies, autonomy
    when = when or _now()
    since = week_start(when)
    week = seasons.week_key(when)
    sections = []

    top = db.execute(select(seasons.WeekScore).where(seasons.WeekScore.week == week, seasons.WeekScore.points > 0)
                     .order_by(seasons.WeekScore.points.desc()).limit(5)).scalars().all()
    names = _names(db, [(r.channel_id, r.canonical_uid) for r in top])
    medal = ['🥇', '🥈', '🥉', '4.', '5.']
    if top:
        sections.append(('🏆 Top contributors', '\n'.join(
            f'{medal[i]} **{names[(r.channel_id, r.canonical_uid)]}** — {r.points:,} pts · {r.contribution:+,} Contribution · {r.actions:,} actions'
            for i, r in enumerate(top))))
    else:
        sections.append(('🏆 Top contributors', 'A quiet week. Be the first name here next Sunday!'))

    hauls = db.execute(select(seasons.WeekScore).where(seasons.WeekScore.week == week, seasons.WeekScore.items > 0)
                       .order_by(seasons.WeekScore.items.desc()).limit(3)).scalars().all()
    names.update(_names(db, [(r.channel_id, r.canonical_uid) for r in hauls if (r.channel_id, r.canonical_uid) not in names]))
    lines = [f'{["🥇", "🥈", "🥉"][i]} **{names[(r.channel_id, r.canonical_uid)]}** brought in {r.items:,} items' for i, r in enumerate(hauls)]
    best, best_n = None, 0
    for h in db.execute(select(autonomy.SeedlingHaul).where(autonomy.SeedlingHaul.created_at >= since)).scalars():
        gained = json.loads(h.gained or '{}')
        n = sum(v for v in gained.values() if isinstance(v, int) and v > 0)
        if n > best_n:
            best, best_n = (h, gained), n
    if best:
        who = _names(db, [(best[0].channel_id, best[0].canonical_uid)])[(best[0].channel_id, best[0].canonical_uid)]
        items = ', '.join(f'{v} {resource_name(k)}' for k, v in sorted(best[1].items(), key=lambda x: -x[1])[:3] if v > 0)
        lines.append(f"🌱 Biggest Seedling haul: **{who}'s** Seedling came home with {items}.")
    sections.append(('🎒 Biggest hauls', '\n'.join(lines) or 'No hauls recorded this week.'))

    stats = _stats(db)
    total = Society(**stats)
    tier = society_tier(total)
    core = {k: stats[k] for k in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation')}
    low = min(core, key=core.get)
    nxt = next((t for t in SOCIETY_TIERS if t[1] > core[low]), None)
    last = db.execute(select(RecapPost).where(RecapPost.world == runtime.DISCORD_WORLD_ID, RecapPost.week != week)
                      .order_by(RecapPost.posted_at.desc())).scalars().first()
    before = json.loads(last.stats) if last else {}
    icon = {'food': '🌾', 'materials': '⛏️', 'development': '⚙️', 'knowledge': '🔬', 'treasury': '🪙', 'reputation': '⭐', 'population': '👥'}
    moved = ' · '.join(f"{icon[k]} {v:,}" + (f" ({v - before[k]:+,})" if k in before and v != before[k] else '') for k, v in stats.items())
    if nxt:
        pct = round(core[low] / max(1, nxt[1]) * 100)
        bar = '▰' * (pct // 10) + '▱' * (10 - pct // 10)
        society = f'**{tier[0]}** → {nxt[0]} {bar} {pct}% (weakest: {low.title()} {core[low]:,}/{nxt[1]:,})\n{moved}'
    else:
        society = f'**{tier[0]}**, the top tier!\n{moved}'
    sections.append(('🏛️ Society', society))

    lines = [f'Day {d}: {e} **{n}** ({v} vote{"s" if v != 1 else ""})' for d, (e, n, _), v in votes.week_winners(db, since)[-5:]]
    lines += [f'{e} Finished **{n}** with {h} helper{"s" if h != 1 else ""}' for n, e, h in votes.built_since(db, since)]
    if lines:
        sections.append(('🗳️ Votes and projects', '\n'.join(lines)))

    live = live_events.week_summary(db, since)
    if live:
        text = f"{live['won']} of {live['count']} challenges won by {live['people']} people."
        if live['best']:
            text += f" Biggest win: {live['best'][0]} (goal {live['best'][1]})."
        if live['top']:
            text += '\nMost helpful: ' + ' · '.join(f'{medal[i]} {n} ({a})' for i, (n, a) in enumerate(live['top']))
        sections.append(('⚡ Stream challenges', text))

    got = trophies.week_unlocks(db, since)
    if got:
        text = '\n'.join(f'{e} **{n}** earned {t}' for n, e, t in got[:6]) + (f'\n…and {len(got) - 6} more' if len(got) > 6 else '')
        sections.append((f'🏅 Trophies ({len(got)})', text))

    season = seasons.current(db)
    s = seasons.info(season)
    podium = seasons.standings(db, season, 3)
    text = f"{s['emoji']} **{s['name']}** · chapter {s['chapter']}/{s['chapters']} · {s['days_left']} days left\n📖 {s['story']}"
    if podium:
        text += '\n' + ' · '.join(f'{medal[i]} {n} {r.points:,}' for i, (r, n) in enumerate(podium))
    sections.append(('🏁 Season', text))

    moments = funny(db, since, week)
    if moments:
        sections.append(('🌱 Seedling moments', '\n'.join(f'{e} *{t}*' for e, t in moments)))

    new = db.execute(select(Player).where(Player.created_at >= since).order_by(Player.created_at)).scalars().all()
    if new:
        who = ', '.join(autonomy.clean_name(p.display_name) for p in new[:10]) + (f' and {len(new) - 10} more' if len(new) > 10 else '')
        sections.append((f'👋 New citizens ({len(new)})', f'Welcome {who}!'))

    end = min(when, since + timedelta(days=6))
    title = f"📰 New Eridian Weekly · {since.strftime('%b %d')} – {end.strftime('%b %d')}"
    tale = story(db, when, title, sections, write)
    if tale:
        sections.insert(0, (STORY_HEADING, tale))
    plain = title + '\n\n' + '\n\n'.join(f'{h}\n{t}' for h, t in sections)
    return title, sections, plain


def funny(db, since, week, n=3):
    from .autonomy import SeedlingDiary
    rows = db.execute(select(SeedlingDiary).where(SeedlingDiary.created_at >= since, SeedlingDiary.autonomous == 1)
                      .order_by(SeedlingDiary.id.desc()).limit(400)).scalars().all()
    scored = []
    for r in rows:
        text = (r.text or '').split(' — ', 1)[-1].strip()
        low = text.casefold()
        score = sum(word in low for word in FUNNY) + (1 if r.desk in {'LIFE', 'SOCIAL', 'COMMONS'} else 0)
        if score:
            tie = int(hashlib.sha1(f'{week}:{r.id}'.encode()).hexdigest()[:6], 16)
            scored.append((score, tie, r, text))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked, seen = [], set()
    for _, _, r, text in scored:
        if r.canonical_uid in seen:
            continue
        seen.add(r.canonical_uid)
        picked.append((r.emoji or '🌱', (text[:177] + '…') if len(text) > 180 else text))
        if len(picked) >= n:
            break
    return picked


def embed(title, sections):
    fields = [{'name': h[:256], 'value': (t[:1021] + '…') if len(t) > 1024 else t, 'inline': False} for h, t in sections[:25]]
    footer = {'text': 'Posted every Sunday · /season · /trophies · /vote'}
    size = len(title[:256]) + len(footer['text']) + sum(len(f['name']) + len(f['value']) for f in fields)
    if size > EMBED_LIMIT and fields and fields[0]['name'] == STORY_HEADING[:256]:
        fields = fields[1:]             # Discord refuses an embed over 6000 characters: the story is the part that can go
    return {'title': title[:256], 'color': COLOUR, 'fields': fields, 'footer': footer, 'timestamp': _now().isoformat()}


def post(db, force=False, when=None):
    """Post this week's recap (once a week unless forced). Returns (ok, message)."""
    from . import seasons
    import requests
    when = when or _now()
    week = seasons.week_key(when)
    row = db.get(RecapPost, (runtime.DISCORD_WORLD_ID, week))
    if row and row.sent and not force:
        return False, f'The recap for {week} was already posted.'
    title, sections, plain = build(db, when)
    token, target = os.getenv('DISCORD_BOT_TOKEN', '').strip(), channel_id()
    ok = False
    if token and target.isdigit():
        try:
            from . import layout_v2
            body = layout_v2.new_message({'embeds': [embed(title, sections)], 'allowed_mentions': {'parse': []}})
            r = requests.post(f'https://discord.com/api/v10/channels/{target}/messages', headers={'Authorization': 'Bot ' + token},
                              json=body, timeout=10)
            ok = 200 <= r.status_code < 300
            if not ok:
                logging.getLogger(__name__).warning('Weekly recap not accepted by Discord: %s', r.status_code)
        except Exception:
            logging.getLogger(__name__).warning('Weekly recap post failed')
    if row is None:
        row = RecapPost(world=runtime.DISCORD_WORLD_ID, week=week, posted_at=_now(), stats='{}', sent=0)
        db.add(row)
    row.posted_at, row.stats, row.sent = _now(), json.dumps(_stats(db)), int(ok or row.sent)
    if ok:
        return True, f'📰 Posted the weekly recap for {week}.'
    return False, '⚠️ The recap could not be posted. Set RECAP_CHANNEL_ID (or DISCORD_GAME_CHANNEL_ID) and DISCORD_BOT_TOKEN, and check the bot can post there.'


def due(when=None):
    when = when or _now()
    return when.weekday() == 6 and when.hour >= RECAP_HOUR


def tick(db):
    """Called by the community worker: post on Sunday once, when a channel is set."""
    from . import seasons
    if not due() or not channel_id() or not os.getenv('DISCORD_BOT_TOKEN', '').strip():
        return None
    row = db.get(RecapPost, (runtime.DISCORD_WORLD_ID, seasons.week_key()))
    if row and row.sent:
        return None
    return post(db)


def chat_line(db):
    from . import seasons
    week = seasons.week_key()
    top = db.execute(select(seasons.WeekScore).where(seasons.WeekScore.week == week, seasons.WeekScore.points > 0)
                     .order_by(seasons.WeekScore.points.desc()).limit(3)).scalars().all()
    names = _names(db, [(r.channel_id, r.canonical_uid) for r in top])
    if not top:
        return '📰 This week so far: nobody on the board yet. The recap posts to Discord on Sunday.'
    return '📰 This week so far: ' + ' | '.join(f"{['🥇', '🥈', '🥉'][i]} {names[(r.channel_id, r.canonical_uid)]} {r.points:,}" for i, r in enumerate(top)) + ' · full recap on Discord Sunday'
