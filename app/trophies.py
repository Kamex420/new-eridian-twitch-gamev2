"""Collections and trophies: long-term goals with a badge to show for each.

Trophies come in six groups:

  Collections  find every ore, every natural material, 10 or 50 different items, eat 10 or 25 foods,
               finish each curio set and all ten curios
  Crafting     master a craft category (12 different recipes, or all of them in a small one), and five of them
  Festivals    craft every festival food of a holiday
  Colony       vote, help finish society projects, finish First Steps, reach Lv 3 in every aptitude,
               a Seedling with 50 good days of its own
  Stream       take part in 1, 10 and 25 stream challenges, win 5
  Seasons      reach Gold in a season, finish in a season's top three

Each trophy pays SC (the big ones also a title), adds season points, pops an alert on stream with its badge,
and shows on the profile. Citizens pin one badge (!badge) that appears next to their name on the stream map.

Progress is read from saved state (inventory, the craft ledger, curios, votes, challenges, seasons) plus a
record of every item a citizen has ever found and every food they have eaten, kept from each command's
before/after snapshot. Nothing here changes how any command works.
"""
import time
from sqlalchemy import Column, String, Integer, DateTime, select, func
from datetime import datetime, timezone
from .db import Base

TROPHY_POINTS = 25
CHECK_EVERY = 45          # seconds between full checks for one citizen (a new find checks at once)
PREFIX = 'trophy:'
CATEGORY_NEED = 12

CATEGORY_LOOK = {'decor': ('🖼️', 'Decor'), 'parts': ('⚙️', 'Parts'), 'clothing': ('🧥', 'Clothing'), 'materials': ('🧱', 'Materials'),
                 'food': ('🥘', 'Cooking'), 'storage': ('📦', 'Storage'), 'seating': ('🪑', 'Seating'), 'medicine': ('💊', 'Medicine'),
                 'tables': ('🪵', 'Tables'), 'machines': ('🏭', 'Machines'), 'equipment': ('🧰', 'Equipment'), 'building': ('🏠', 'Building'),
                 'bathroom': ('🛁', 'Bathroom'), 'beds': ('🛏️', 'Beds'), 'seeds': ('🌱', 'Seeds')}
GROUPS = [('collections', '🧺', 'Collections'), ('crafting', '🛠️', 'Crafting'), ('festivals', '🎉', 'Festivals'),
          ('colony', '🏛️', 'Colony'), ('stream', '📺', 'Stream'), ('seasons', '🏁', 'Seasons')]


class Found(Base):
    """Every item a citizen has ever held, and every food they have eaten."""
    __tablename__ = 'trophy_found_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    kind = Column(String(8), primary_key=True)        # item or ate
    key = Column(String(64), primary_key=True)
    at = Column(DateTime(timezone=True), nullable=False)


class Showcase(Base):
    __tablename__ = 'trophy_showcase_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    badge = Column(String(48), nullable=False, default='')


def _now():
    return datetime.now(timezone.utc)


# key -> dict(emoji, name, text, group, sc, title, need, have(ctx))
TROPHIES = {}


def trophy(key, emoji, name, text, group, sc, need, have, title='', hat=''):
    TROPHIES[key] = dict(key=key, emoji=emoji, name=name, text=text, group=group, sc=sc, need=need, have=have, title=title, hat=hat)


def _build(m):
    if TROPHIES:
        return
    from . import seasonal
    s = m.seed_content
    ores = sorted(k for k in s.GATHER if m.resource_name(k).endswith(' Ore'))
    natural = sorted(s.GATHER)
    trophy('first_finds', '🔎', 'First Finds', 'Find 10 different items', 'collections', 10, 10, lambda c: len(c['found']))
    trophy('treasure_hunter', '🎒', 'Treasure Hunter', 'Find 50 different items', 'collections', 30, 50, lambda c: len(c['found']))
    trophy('ore_hunter', '💎', 'Ore Hunter', 'Find every ore on Avesta: ' + ', '.join(m.resource_name(k).replace(' Ore', '') for k in ores),
           'collections', 40, len(ores), lambda c, ores=ores: len(c['found'] & set(ores)), title='ore_hunter')
    trophy('wild_harvest', '🧺', 'Wild Harvest', f'Find all {len(natural)} natural materials', 'collections', 60, len(natural),
           lambda c, natural=natural: len(c['found'] & set(natural)), title='wildlander')
    trophy('taste_tester', '🍽️', 'Taste Tester', 'Eat 10 different foods', 'collections', 20, 10, lambda c: len(c['ate']))
    trophy('gourmet', '👨‍🍳', 'Gourmet', 'Eat 25 different foods', 'collections', 50, 25, lambda c: len(c['ate']), title='gourmet')
    for key, (name, items, *_) in m.COLLECTION_SETS.items():
        trophy('set_' + key, '🗃️', name, f'Complete the {name} curio set', 'collections', 20, len(items),
               lambda c, key=key, items=items: len(items) if key in c['claimed'] else len(c['curios'] & set(items)))
    trophy('curator', '🏛️', 'Curator', f'Find all {len(m.COLLECTIBLES)} curios', 'collections', 50, len(m.COLLECTIBLES),
           lambda c: len(c['curios'] & set(m.COLLECTIBLES)), title='curator')

    counts = {}
    for e in m.workbench.index(m):
        counts.setdefault(e.category, set()).add(e.id)
    for cat, ids in sorted(counts.items()):
        emoji, label = CATEGORY_LOOK.get(cat, ('🛠️', cat.title()))
        need = min(CATEGORY_NEED, len(ids))
        trophy('craft_' + cat, emoji, f'{label} Master', f'Craft {need} different {label.lower()} recipes', 'crafting', 30, need,
               lambda c, ids=ids: len(c['crafted'] & ids))
    cats = sorted(counts)
    trophy('grand_artisan', '🏅', 'Grand Artisan', 'Master five craft categories', 'crafting', 80, 5,
           lambda c, cats=cats: sum(1 for k in cats if 'craft_' + k in c['owned']), title='grand_artisan')

    emoji_of = {name: emoji for name, _, _, emoji in seasonal.HOLIDAY_WINDOWS}
    for holiday, rows in seasonal.FESTIVAL_FOODS.items():
        recipes = {'fr_' + seasonal._slug(r[0]) for r in rows}
        trophy('feast_' + seasonal._slug(holiday), emoji_of.get(holiday, '🎉'), f'{holiday} Feast',
               f"Craft every {holiday} festival food: {', '.join(r[0] for r in rows)}", 'festivals', 25, len(recipes),
               lambda c, recipes=recipes: len(c['crafted'] & recipes))

    trophy('civic_duty', '🗳️', 'Civic Duty', 'Vote in a colony vote', 'colony', 5, 1, lambda c: c['votes'])
    trophy('town_council', '📜', 'Town Council', 'Vote in 15 colony votes', 'colony', 30, 15, lambda c: c['votes'], title='town_councillor')
    trophy('builder', '🏗️', 'Builder', 'Help finish a society project', 'colony', 15, 1, lambda c: c['projects'])
    trophy('project_veteran', '🏢', 'Project Veteran', 'Help finish 3 society projects', 'colony', 40, 3, lambda c: c['projects'], title='project_veteran')
    trophy('settled_in', '🎓', 'Settled In', 'Finish First Steps', 'colony', 5, 1, lambda c: c['first_steps'])
    trophy('all_rounder', '🎯', 'All-Rounder', 'Reach Lv 3 in every aptitude', 'colony', 60, len(c_fields()), lambda c: c['levels3'], title='all_rounder')
    trophy('seedling_whisperer', '🌱', 'Seedling Whisperer', 'Your Seedling has 50 good days on its own', 'colony', 25, 50, lambda c: c['seedling'])

    trophy('crowd_worker', '⚡', 'Crowd Worker', 'Take part in a stream challenge', 'stream', 10, 1, lambda c: c['events'])
    trophy('stream_regular', '📺', 'Stream Regular', 'Take part in 10 stream challenges', 'stream', 30, 10, lambda c: c['events'])
    trophy('stream_legend', '🎬', 'Stream Legend', 'Take part in 25 stream challenges', 'stream', 60, 25, lambda c: c['events'], title='stream_legend', hat='halo')
    trophy('team_player', '🤝', 'Team Player', 'Win 5 stream challenges', 'stream', 25, 5, lambda c: c['event_wins'])

    trophy('golden_season', '🥇', 'Golden Season', 'Reach Gold in a season', 'seasons', 0, 1, lambda c: c['gold'])
    trophy('podium', '👑', 'Podium Finish', "Finish in a season's top three", 'seasons', 0, 1, lambda c: c['podium'])


def c_fields():
    from .competencies import FIELDS
    return list(FIELDS)


TITLES = {'ore_hunter': 'Ore Hunter', 'wildlander': 'Wildlander', 'gourmet': 'Gourmet', 'curator': 'Curator', 'grand_artisan': 'Grand Artisan',
          'town_councillor': 'Town Councillor', 'project_veteran': 'Project Veteran', 'all_rounder': 'All-Rounder', 'stream_legend': 'Stream Legend'}


def install(m):
    for key, label in TITLES.items():
        m.TITLE_DEFS.setdefault(key, label)


# ---------------------------------------------------------------- what a citizen has

def record(m, db, p, before, after):
    """Remember newly found items and newly eaten foods. Returns True when something is new."""
    if not before or not after:
        return False
    b, a = before.get('Resources', {}), after.get('Resources', {})
    new = [('item', k) for k, v in a.items() if v > b.get(k, 0) and k not in {'sc', 'contribution'} and not str(k).startswith('gear:')]
    nb, na = before.get('Needs', {}), after.get('Needs', {})
    if na.get('nutrition', 0) > nb.get('nutrition', 0):
        new += [('ate', k) for k in b if a.get(k, 0) < b.get(k, 0) and k in m.seed_content.EDIBLE]
    added = False
    for kind, key in dict.fromkeys(new):
        key = str(key)[:64]
        if db.get(Found, (p.channel_id, p.twitch_uid, kind, key)) is None:
            db.add(Found(channel_id=p.channel_id, canonical_uid=p.twitch_uid, kind=kind, key=key, at=_now()))
            added = True
    if added:
        db.flush()
    return added


def context(m, db, p):
    from . import votes, live_events, seasons, onboarding, autonomy
    from .competencies import FIELDS, level
    rows = db.execute(select(Found.kind, Found.key).where(Found.channel_id == p.channel_id, Found.canonical_uid == p.twitch_uid)).all()
    held = {k for k, v in m.task_queue.inventory_snapshot(m, db, p).items() if v > 0 and not str(k).startswith('gear:')}
    crafted = {r for r, in db.execute(select(m.CraftLedger.recipe).where(m.CraftLedger.channel_id == p.channel_id, m.CraftLedger.canonical_uid == p.twitch_uid,
                                                                        m.CraftLedger.qty > 0)).all()}
    curios = {k for k, in db.execute(select(m.CollectionItem.item_key).where(m.CollectionItem.channel_id == p.channel_id,
                                                                            m.CollectionItem.canonical_uid == p.twitch_uid, m.CollectionItem.qty > 0)).all()}
    claimed = {k for k, in db.execute(select(m.CollectionSetClaim.set_key).where(m.CollectionSetClaim.channel_id == p.channel_id,
                                                                                m.CollectionSetClaim.canonical_uid == p.twitch_uid)).all()}
    steps = db.get(onboarding.FirstSteps, (p.channel_id, p.twitch_uid))
    life = autonomy.row(db, p.channel_id, p.twitch_uid)
    best = db.execute(select(func.max(seasons.SeasonScore.tier)).where(seasons.SeasonScore.channel_id == p.channel_id,
                                                                     seasons.SeasonScore.canonical_uid == p.twitch_uid)).scalar() or 0
    top = db.execute(select(func.min(seasons.SeasonResult.rank)).where(seasons.SeasonResult.channel_id == p.channel_id,
                                                                     seasons.SeasonResult.canonical_uid == p.twitch_uid)).scalar()
    return {'found': {k for kind, k in rows if kind == 'item'} | held, 'ate': {k for kind, k in rows if kind == 'ate'}, 'crafted': crafted,
            'curios': curios, 'claimed': claimed, 'owned': owned(db, p), 'votes': votes.votes_cast(db, p), 'projects': votes.projects_helped(db, p),
            'first_steps': int(bool(steps and steps.finished)),
            'levels3': sum(level(getattr(p, f)) >= 3 for f in FIELDS.values()), 'seedling': life.successes if life else 0,
            'events': live_events.participations(db, p), 'event_wins': live_events.wins(db, p),
            'gold': int(best >= 3), 'podium': int(bool(top and top <= 3))}


def owned(db, p):
    return {c[len(PREFIX):] for c, in db.execute(select(m_ach().code).where(m_ach().channel_id == p.channel_id, m_ach().canonical_uid == p.twitch_uid,
                                                                           m_ach().code.like(PREFIX + '%'))).all()}


def m_ach():
    from .models import Achievement
    return Achievement


# ---------------------------------------------------------------- unlocking

_last = {}


def check(m, db, p, force=False):
    """Unlock every trophy now earned. Returns the notes to show."""
    _build(m)
    key = (p.channel_id, p.twitch_uid)
    if not force and time.monotonic() - _last.get(key, 0) < CHECK_EVERY:
        return []
    _last[key] = time.monotonic()
    if len(_last) > 5000:
        _last.clear()
    ctx = context(m, db, p)
    notes = []
    for _ in range(2):                  # a second pass catches trophies that count other trophies
        for t in TROPHIES.values():
            if t['key'] in ctx['owned']:
                continue
            if min(t['have'](ctx), t['need']) >= t['need']:
                notes.append(unlock(m, db, p, t))
                ctx['owned'].add(t['key'])
    return notes


def unlock(m, db, p, t):
    from . import stream_overlay, seasons
    db.add(m_ach()(channel_id=p.channel_id, canonical_uid=p.twitch_uid, code=PREFIX + t['key']))
    db.add(Found(channel_id=p.channel_id, canonical_uid=p.twitch_uid, kind='trophy', key=t['key'], at=_now()))
    p.sc += t['sc']
    extra = []
    if t['title'] and m.unlock_title(db, p, t['title']):
        extra.append(f"the {m.TITLE_DEFS.get(t['title'], t['title'])} title")
    if t['hat'] and seasons.give_hat(db, p, t['hat']):
        extra.append(f"the {seasons.HATS[t['hat']][1]}")
    seasons.add(m, db, p, TROPHY_POINTS, kind='trophies')
    show = db.get(Showcase, (p.channel_id, p.twitch_uid))
    if show is None:
        db.add(Showcase(channel_id=p.channel_id, canonical_uid=p.twitch_uid, badge=t['key']))
    stream_overlay.highlight(db, p.channel_id, 'trophy', f"{p.display_name} earned {t['emoji']} {t['name']}", t['text'][:200], p.display_name, emoji=t['emoji'])
    db.flush()
    got = ', '.join(([f"+{t['sc']} SC"] if t['sc'] else []) + extra)
    return f"🏅 Trophy: {t['emoji']} {t['name']}" + (f' ({got})' if got else '')


def from_command(m, db, p, fn_name, before, after):
    new = record(m, db, p, before, after)
    busy = fn_name in {'make', 'craft', 'workshop', 'claim_collection', 'collection', 'vote', 'profile', 'achievements'}
    return check(m, db, p, force=new or busy)


# ---------------------------------------------------------------- views

def progress(m, db, p):
    _build(m)
    ctx = context(m, db, p)
    return ctx, [(t, min(t['have'](ctx), t['need'])) for t in TROPHIES.values()]


def badge_of(db, p):
    show = db.get(Showcase, (p.channel_id, p.twitch_uid))
    return TROPHIES.get(show.badge) if show and show.badge else None


def pin(m, db, p, choice, provider='twitch'):
    _build(m)
    mine = owned(db, p)
    text = str(choice or '').strip().casefold()
    cmd = '/trophies badge:' if provider == 'discord' else '!badge '
    if not text:
        current = badge_of(db, p)
        have = [TROPHIES[k] for k in TROPHIES if k in mine]
        if not have:
            return f'🏅 No trophies yet, so no badge to pin. {("/trophies" if provider == "discord" else "!trophies")} shows what to aim for.'
        return (f"🏅 Pinned: {current['emoji']} {current['name'] if current else 'none'} · yours: " if current else '🏅 Yours: ') + \
            ', '.join(f"{t['emoji']} {t['name']}" for t in have[:12]) + f' · {cmd}<name> to pin one'
    if text in {'off', 'none'}:
        show = db.get(Showcase, (p.channel_id, p.twitch_uid))
        if show:
            show.badge = ''
        return '🏅 Badge unpinned. Your name shows on its own.'
    match = next((t for k, t in TROPHIES.items() if k in mine and (text == k or text in t['name'].casefold())), None)
    if not match:
        return f"🏅 You haven't earned a trophy called \"{choice}\". Nothing changed."
    show = db.get(Showcase, (p.channel_id, p.twitch_uid))
    if show is None:
        db.add(Showcase(channel_id=p.channel_id, canonical_uid=p.twitch_uid, badge=match['key']))
    else:
        show.badge = match['key']
    return f"🏅 Pinned {match['emoji']} {match['name']}. It shows next to your name on the stream map and your profile."


def view(m, db, p, provider='discord', group=''):
    check(m, db, p, force=True)
    ctx, rows = progress(m, db, p)
    done = [t for t, n in rows if t['key'] in ctx['owned']]
    pinned = badge_of(db, p)
    if provider != 'discord':
        close = sorted(((n / t['need'], t, n) for t, n in rows if t['key'] not in ctx['owned'] and n > 0), key=lambda x: -x[0])[:2]
        return (f"🏅 {p.display_name}: {len(done)}/{len(rows)} trophies" + (f" · badge {pinned['emoji']}" if pinned else '')
                + (' · ' + ' '.join(t['emoji'] for t in done[-8:]) if done else '')
                + (' · next: ' + ', '.join(f"{t['name']} {n}/{t['need']}" for _, t, n in close) if close else '') + ' · !badge')[:200]
    groups = [g for g in GROUPS if not group or g[0] == group]
    lines = [f'🏅 **TROPHIES · {len(done)}/{len(rows)}**' + (f" · pinned badge {pinned['emoji']} {pinned['name']}" if pinned else '')]
    for key, emoji, label in groups:
        mine = [(t, n) for t, n in rows if t['group'] == key]
        if not mine:
            continue
        got = sum(1 for t, _ in mine if t['key'] in ctx['owned'])
        lines += ['', f'{emoji} **{label.upper()}** {got}/{len(mine)}']
        shown = mine if group else sorted(mine, key=lambda x: (x[0]['key'] in ctx['owned'], -(x[1] / x[0]['need'])))[:6]
        for t, n in shown:
            if t['key'] in ctx['owned']:
                lines.append(f"✅ {t['emoji']} **{t['name']}** — {t['text']}")
            else:
                reward = f" · +{t['sc']} SC" if t['sc'] else ''
                lines.append(f"▫️ {t['emoji']} {t['name']} — {t['text']} · **{n}/{t['need']}**{reward}" + (' + title' if t['title'] else ''))
        if not group and len(mine) > len(shown):
            lines.append(f'…and {len(mine) - len(shown)} more (pick {label} to see them all)')
    lines += ['', 'Pin a badge with /trophies badge:<name>; it shows next to your name on the stream map.']
    return '\n'.join(lines)


def profile_line(m, db, p):
    _build(m)
    mine = owned(db, p)
    if not mine:
        return ''
    pinned = badge_of(db, p)
    badges = ' '.join(TROPHIES[k]['emoji'] for k in TROPHIES if k in mine)
    return f"🏅 Trophies {len(mine)}/{len(TROPHIES)}: {badges}" + (f" · pinned {pinned['emoji']} {pinned['name']}" if pinned else '')


def badges_for(db, keys):
    """{(channel, uid): badge emoji} for the overlay."""
    if not keys or not TROPHIES:
        return {}
    rows = db.execute(select(Showcase).where(Showcase.canonical_uid.in_([u for _, u in keys]), Showcase.badge != '')).scalars()
    return {(r.channel_id, r.canonical_uid): TROPHIES[r.badge]['emoji'] for r in rows if (r.channel_id, r.canonical_uid) in keys and r.badge in TROPHIES}


def week_unlocks(m, db, since):
    """[(name, emoji, trophy)] unlocked since a time, newest first."""
    _build(m)
    rows = db.execute(select(Found).where(Found.kind == 'trophy', Found.at >= since).order_by(Found.at.desc())).scalars().all()
    out = []
    for r in rows:
        p = db.execute(select(m.Player).where(m.Player.channel_id == r.channel_id, m.Player.twitch_uid == r.canonical_uid)).scalar_one_or_none()
        t = TROPHIES.get(r.key)
        if p and t:
            out.append((p.display_name, t['emoji'], t['name']))
    return out
