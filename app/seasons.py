"""Seasons: five-week chapters of New Eridian with their own story, rewards and leaderboard.

Every season has a theme (First Light, Iron and Dust, Siro Mysteries, …) and a story told one chapter a
week. Citizens earn season points for everything they already do:

  3 points per Contribution, 1 per aptitude XP (up to 30 a command), plus bonuses for stream challenges,
  colony votes and trophies. A Seedling working on its own earns its player half.

Points unlock cosmetic rewards straight away (Bronze: a season title, Silver: the season hat for the stream
map, Gold: a golden title and a trophy). The whole colony shares three community milestones that decorate the
map (season banners, lanterns, then a monument in the Commons). When the season ends, the top three get a
champion title (and the winner a crown), results are archived, and only the season points reset: stats,
items, titles and hats all stay.

Weekly tallies (points, Contribution, items, actions) are kept alongside for the Sunday recap.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, DateTime, select, func
from .db import Base
from . import runtime
from .models import Player

SEASON_DAYS = max(7, int(os.getenv('SEASON_DAYS', '35')))
TIERS = [('bronze', '🥉', 'Bronze', 150), ('silver', '🥈', 'Silver', 500), ('gold', '🥇', 'Gold', 1200)]
MILESTONES = [(2500, 'banners', '🎏', 'Season banners fly over New Eridian'),
              (7500, 'lanterns', '🏮', 'Lanterns light every street'),
              (15000, 'monument', '🗿', 'A season monument rises in the Commons')]
MILESTONE_SC = 10          # paid to every citizen with season points when a milestone is reached
GOLD_SC = 50
CHAMPION_SC = (150, 100, 75)
MAX_CHAMPION_TITLES = 60   # champion title keys registered up front
ACTING_SHARE = 0.5         # a Seedling acting alone earns its player half

# key, emoji, name, colour, season hat, title, story (one chapter a week)
THEMES = [
    ('first_light', '🌅', 'Season of First Light', '#ffb86b', 'flower', 'Dawnbringer', [
        'After the long dusk, Avesta\'s sun climbs over the ridge. The greenhouses wake up and the colony gets to work.',
        'The first harvest of the season comes in. Mara swears the tomatoes are growing towards the Commons, not the sun.',
        'Warm days bring travellers from the ridge settlements. New Eridian is suddenly the place everyone wants to see.',
        'A dawn festival is planned. Every district wants its lights to be the first the sun touches.',
        'The Festival of First Light. The whole colony watches the sunrise together, and the season ends in gold.']),
    ('iron_dust', '⚙️', 'Season of Iron and Dust', '#d4a24c', 'viking', 'Dust Rider', [
        'Dust storms roll in from the flats. The Industrial Ward fires up every furnace to keep the walls strong.',
        'A deep ore seam opens under the Frontier Edge. Miners race each other to the richest veins.',
        'The storms get worse. Orin keeps a list of every wall that held and every one that did not.',
        'A great machine is pulled from the dust: nobody knows who built it, but it still turns on.',
        'The last storm passes. New Eridian stands, patched, proud and very, very dusty.']),
    ('siro_mysteries', '🔮', 'Season of Siro Mysteries', '#bd91ff', 'wizard', 'Siro Seer', [
        'The Siro readings glow at night. The Research Block sets up telescopes in the Commons.',
        'Spores drift into the greenhouses and some crops start to hum. Vela takes notes. Lots of notes.',
        'A repeating signal is traced to the old survey tunnels. Something is keeping time down there.',
        'The colony maps the signal together. Every district holds one piece of the puzzle.',
        'The mystery is solved: it was Rocky. Nobody can explain how. The season ends in wonder.']),
    ('starport', '🚀', 'Season of the Starport', '#70ddff', 'astronaut', 'Star Courier', [
        'The Spaceport gets word of a supply convoy arriving this season. Every pad needs to be ready.',
        'Kepler finds a cargo manifest for a ship that has not launched yet. The couriers get busy.',
        'The first convoy lands. The Market Concourse fills with things nobody on Avesta has seen before.',
        'A second, bigger convoy is on its way. The colony builds and hauls day and night.',
        'The skies fill with shuttles. New Eridian is officially on the star charts.']),
    ('deep_frost', '❄️', 'Season of Deep Frost', '#9fd0ff', 'beanie', 'Frostwalker', [
        'The cold season comes early. Pipes freeze, fires are lit, and every home needs more Lumber.',
        'The frost makes the rare ores easy to see. The brave go out to the Frontier Edge with lanterns.',
        'A long night settles in. The Commons becomes one big kitchen, and everyone brings something.',
        'The thaw starts in the Agricultural District. The first green shoots poke through the ice.',
        'Spring arrives. New Eridian made it through the frost together, and nobody lost a toe.']),
    ('jubilee', '🎉', "Founders' Jubilee", '#ff9ad5', 'party', 'Jubilee Star', [
        'New Eridian celebrates its founding. Every district builds a float for the Jubilee parade.',
        'The Market Fair opens with stalls from every job in the colony. Tamsin runs out of receipts.',
        'The Jubilee games begin: races, crafting contests and a very serious rock-stacking final.',
        'Old founders tell stories in the Commons. The Seedlings listen, and some of them take notes.',
        'The Jubilee parade. Fireworks, music and every Seedling in their best hat.']),
]
THEME = {t[0]: t for t in THEMES}
HATS = {'flower': ('🌼', 'Flower crown'), 'viking': ('⛑️', 'Horned dust helm'), 'wizard': ('🧙', 'Siro wizard hat'),
        'astronaut': ('👩‍🚀', 'Astronaut helmet'), 'beanie': ('🧶', 'Frost beanie'), 'party': ('🥳', 'Party hat'),
        'crown': ('👑', 'Champion crown'), 'laurel': ('🌿', 'Finalist laurel'), 'halo': ('😇', 'Stream halo'),
        'antlers': ('🦌', 'Festive antlers'),
        # Holiday hats: crafting every festival food of a holiday (its Feast trophy) wins its hat.
        'sparkle': ('🎆', 'New Year sparkle crown'), 'hearts': ('💝', 'Heart headband'), 'poppy': ('🌺', 'Poppy cap'),
        'fishing': ('🎣', 'Fishing bucket hat'), 'starhat': ('🎩', 'Star-spangled top hat'), 'goldhelm': ('⛑️', 'Golden hard hat'),
        'witch': ('🧹', 'Witch hat'), 'pilgrim': ('🦃', 'Pilgrim hat'), 'santa': ('🎅', 'Santa hat'),
        'jackmask': ('🎃', "Jack-o'-lantern mask")}
HOLIDAY_HATS = {'New Year': 'sparkle', "Valentine's Day": 'hearts', 'Memorial Day': 'poppy', "Father's Day": 'fishing',
                'Independence Day': 'starhat', 'Labor Day': 'goldhelm', 'Halloween': 'witch', 'Thanksgiving': 'pilgrim',
                'Christmas': 'santa'}


class Season(Base):
    __tablename__ = 'seasons_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    world = Column(String(64), nullable=False, index=True)
    number = Column(Integer, nullable=False, default=1)
    theme = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    closed = Column(Integer, nullable=False, default=0)
    milestones = Column(Integer, nullable=False, default=0)


class SeasonScore(Base):
    __tablename__ = 'season_scores_v1'
    season_id = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    points = Column(Integer, nullable=False, default=0)
    contribution = Column(Integer, nullable=False, default=0)
    xp = Column(Integer, nullable=False, default=0)
    events = Column(Integer, nullable=False, default=0)
    votes = Column(Integer, nullable=False, default=0)
    trophies = Column(Integer, nullable=False, default=0)
    tier = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SeasonResult(Base):
    __tablename__ = 'season_results_v1'
    season_id = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    rank = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False)
    tier = Column(Integer, nullable=False, default=0)


class WeekScore(Base):
    __tablename__ = 'week_scores_v1'
    week = Column(String(10), primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    points = Column(Integer, nullable=False, default=0)
    contribution = Column(Integer, nullable=False, default=0)
    xp = Column(Integer, nullable=False, default=0)
    items = Column(Integer, nullable=False, default=0)
    actions = Column(Integer, nullable=False, default=0)
    events = Column(Integer, nullable=False, default=0)
    votes = Column(Integer, nullable=False, default=0)


class Wardrobe(Base):
    __tablename__ = 'wardrobe_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    hats = Column(String(400), nullable=False, default='[]')
    hat = Column(String(24), nullable=False, default='')


def _now():
    return datetime.now(timezone.utc)


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def week_key(when=None):
    y, w, _ = (when or _now()).isocalendar()
    return f'{y}-W{w:02d}'


def install(m):
    from .game.rules import TITLE_DEFS
    for key, emoji, name, colour, hat, title, story in THEMES:
        TITLE_DEFS.setdefault('season_' + key, title)
        TITLE_DEFS.setdefault('season_' + key + '_gold', 'Golden ' + title)
    for n in range(1, MAX_CHAMPION_TITLES + 1):
        TITLE_DEFS.setdefault(f'season{n}_champion', f'Season {n} Champion')
        TITLE_DEFS.setdefault(f'season{n}_finalist', f'Season {n} Finalist')


# ---------------------------------------------------------------- the current season

def current(db, world=None):
    """The running season, closing any that ended (and opening the next)."""
    world = world or runtime.DISCORD_WORLD_ID
    row = db.execute(select(Season).where(Season.world == world).order_by(Season.id.desc())).scalars().first()
    if row is None:
        start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        row = Season(world=world, number=1, theme=THEMES[0][0], started_at=start, ends_at=start + timedelta(days=SEASON_DAYS), closed=0, milestones=0)
        db.add(row)
        db.flush()
        return row
    guard = 0
    while _now() >= _utc(row.ends_at) and guard < 20:
        guard += 1
        close(db, row)
        start = _utc(row.ends_at) if _now() - _utc(row.ends_at) < timedelta(days=SEASON_DAYS) else _now()
        theme = THEMES[row.number % len(THEMES)][0]
        row = Season(world=world, number=row.number + 1, theme=theme, started_at=start, ends_at=start + timedelta(days=SEASON_DAYS), closed=0, milestones=0)
        db.add(row)
        db.flush()
        from . import stream_overlay
        t = THEME[theme]
        stream_overlay.highlight(db, world, 'season', f'Season {row.number} begins: {t[2]}', t[6][0][:200], emoji=t[1])
    return row


def info(season):
    t = THEME.get(season.theme, THEMES[0])
    elapsed = max(0, (_now() - _utc(season.started_at)).days)
    chapter = min(len(t[6]) - 1, elapsed // 7)
    left = max(0, (_utc(season.ends_at) - _now()).total_seconds())
    return {'number': season.number, 'key': t[0], 'emoji': t[1], 'name': t[2], 'colour': t[3], 'hat': t[4], 'title': t[5],
            'chapter': chapter + 1, 'chapters': len(t[6]), 'story': t[6][chapter], 'days_left': int(left // 86400), 'hours_left': int(left // 3600),
            'ends_at': _utc(season.ends_at).isoformat()}


def _score(db, season, p, create=True):
    row = db.get(SeasonScore, (season.id, p.channel_id, p.twitch_uid))
    if row is None and create:
        row = SeasonScore(season_id=season.id, channel_id=p.channel_id, canonical_uid=p.twitch_uid, points=0, contribution=0, xp=0,
                          events=0, votes=0, trophies=0, tier=0, updated_at=_now())
        db.add(row)
        db.flush()
    return row


def _week(db, p, create=True):
    key = week_key()
    row = db.get(WeekScore, (key, p.channel_id, p.twitch_uid))
    if row is None and create:
        row = WeekScore(week=key, channel_id=p.channel_id, canonical_uid=p.twitch_uid, points=0, contribution=0, xp=0, items=0, actions=0, events=0, votes=0)
        db.add(row)
        db.flush()
    return row


def add(db, p, points, kind='', contribution=0, xp=0, items=0, actions=0):
    """Add season (and weekly) points. Returns a note when a reward tier is reached, else ''."""
    season = current(db)
    row, week = _score(db, season, p), _week(db, p)
    points = max(0, int(points))
    row.points += points
    row.contribution += max(0, contribution)
    row.xp += max(0, xp)
    row.updated_at = _now()
    week.points += points
    week.contribution += max(0, contribution)
    week.xp += max(0, xp)
    week.items += max(0, items)
    week.actions += max(0, actions)
    if kind in {'events', 'votes', 'trophies'}:
        setattr(row, kind, getattr(row, kind) + 1)
        if kind in {'events', 'votes'}:
            setattr(week, kind, getattr(week, kind) + 1)
    notes = [_reward(db, p, season, row, i) for i in range(row.tier, len(TIERS)) if row.points >= TIERS[i][3]]
    _milestones(db, season)
    return ' '.join(n for n in notes if n)


def _reward(db, p, season, row, index):
    from .game.players import unlock_title
    key, emoji, label, need = TIERS[index]
    if row.tier > index:
        return ''
    row.tier = index + 1
    t = THEME.get(season.theme, THEMES[0])
    from . import stream_overlay
    if key == 'bronze':
        unlock_title(db, p, 'season_' + t[0])
        got = f'the **{t[5]}** title'
    elif key == 'silver':
        give_hat(db, p, t[4])
        got = f'the {HATS[t[4]][0]} **{HATS[t[4]][1]}** for your Seedling on the stream map'
    else:
        unlock_title(db, p, 'season_' + t[0] + '_gold')
        p.sc += GOLD_SC
        got = f'the **Golden {t[5]}** title and +{GOLD_SC} SC'
    stream_overlay.highlight(db, p.channel_id, 'season', f'{p.display_name} reached {label} this season', f'{t[1]} {t[2]}: {got.replace("**", "")}',
                             p.display_name, emoji=emoji)
    return f'{emoji} Season {label}! You unlocked {got}.'


def _milestones(db, season):
    total = db.execute(select(func.coalesce(func.sum(SeasonScore.points), 0)).where(SeasonScore.season_id == season.id)).scalar() or 0
    reached = sum(total >= need for need, *_ in MILESTONES)
    if reached <= season.milestones:
        return
    from . import stream_overlay
    for need, key, emoji, text in MILESTONES[season.milestones:reached]:
        paid = 0
        for score in db.execute(select(SeasonScore).where(SeasonScore.season_id == season.id, SeasonScore.points > 0)).scalars():
            p = db.execute(select(Player).where(Player.channel_id == score.channel_id, Player.twitch_uid == score.canonical_uid)).scalar_one_or_none()
            if p:
                p.sc += MILESTONE_SC
                paid += 1
        stream_overlay.highlight(db, season.world, 'season', f'Community milestone: {text}!',
                                 f'The colony earned {need:,} season points together. {paid} citizens receive +{MILESTONE_SC} SC.', emoji=emoji)
    season.milestones = reached


def from_command(db, p, before, after, acting=False):
    """Season points from what a command changed."""
    if not before or not after:
        return ''
    b, a = before.get('Resources', {}), after.get('Resources', {})
    contribution = a.get('contribution', 0) - b.get('contribution', 0)
    xp = sum(max(0, v - before.get('Competency', {}).get(k, 0)) for k, v in after.get('Competency', {}).items())
    items = sum(max(0, v - b.get(k, 0)) for k, v in a.items() if k not in {'sc', 'contribution'} and not str(k).startswith('gear:'))
    points = max(0, contribution) * 3 + min(30, xp)
    if acting:
        points = int(points * ACTING_SHARE)
    if points <= 0 and items <= 0:
        return ''
    return add(db, p, points, contribution=contribution, xp=xp, items=items, actions=1)


# ---------------------------------------------------------------- hats

def hats_of(db, p):
    row = db.get(Wardrobe, (p.channel_id, p.twitch_uid))
    return (json.loads(row.hats or '[]') if row else []), (row.hat if row else '')


def give_hat(db, p, hat):
    row = db.get(Wardrobe, (p.channel_id, p.twitch_uid))
    if row is None:
        row = Wardrobe(channel_id=p.channel_id, canonical_uid=p.twitch_uid, hats='[]', hat='')
        db.add(row)
    owned = json.loads(row.hats or '[]')
    if hat not in owned:
        owned.append(hat)
        row.hats = json.dumps(owned)
        if not row.hat:
            row.hat = hat          # a first cosmetic hat goes straight on
        return True
    return False


def wear(db, p, choice, provider='twitch'):
    owned, worn = hats_of(db, p)
    cmd = '/season section:hats' if provider == 'discord' else '!hat'
    key = str(choice or '').strip().casefold().replace(' ', '_')
    if not key:
        if not owned:
            return (f'🎩 No cosmetic hats yet. Reach Silver this season for the season hat, or craft every festival food of a '
                    f'holiday for its holiday hat. {cmd} <name> wears one.')
        listing = ', '.join(f"{HATS[h][0]} {h}{' (on)' if h == worn else ''}" for h in owned if h in HATS)
        return f'🎩 Your hats: {listing}. {cmd} <name> to wear one, {cmd} job to go back to your job hat.'
    if key in {'job', 'off', 'none'}:
        row = db.get(Wardrobe, (p.channel_id, p.twitch_uid))
        if row:
            row.hat = ''
        return '🎩 Your Seedling wears its job hat again.'
    match = next((h for h in owned if h == key or HATS.get(h, ('', ''))[1].casefold() == key.replace('_', ' ')), None)
    if not match:
        return f"🎩 You don't have that hat. Yours: {', '.join(owned) or 'none yet'}. Nothing changed."
    db.get(Wardrobe, (p.channel_id, p.twitch_uid)).hat = match
    return f'🎩 Your Seedling now wears the {HATS[match][0]} {HATS[match][1]} on the stream map.'


def worn_hats(db, keys):
    """{(channel, uid): hat} for the overlay."""
    if not keys:
        return {}
    rows = db.execute(select(Wardrobe).where(Wardrobe.canonical_uid.in_([u for _, u in keys]), Wardrobe.hat != '')).scalars()
    return {(r.channel_id, r.canonical_uid): r.hat for r in rows if (r.channel_id, r.canonical_uid) in keys}


# ---------------------------------------------------------------- ending a season

def standings(db, season, limit=10):
    rows = db.execute(select(SeasonScore).where(SeasonScore.season_id == season.id, SeasonScore.points > 0)
                      .order_by(SeasonScore.points.desc(), SeasonScore.updated_at).limit(limit)).scalars().all()
    return [(r, _name(db, r.channel_id, r.canonical_uid)) for r in rows]


def _name(db, channel, uid):
    p = db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == uid)).scalar_one_or_none()
    from .autonomy import clean_name
    return clean_name(p.display_name) if p else 'Citizen'


def close(db, season):
    """Archive results, crown the top three, and leave everything else alone."""
    from .game.players import unlock_title
    from .game.rules import TITLE_DEFS
    if season.closed:
        return []
    rows = db.execute(select(SeasonScore).where(SeasonScore.season_id == season.id, SeasonScore.points > 0)
                      .order_by(SeasonScore.points.desc(), SeasonScore.updated_at)).scalars().all()
    winners = []
    from . import stream_overlay
    for rank, r in enumerate(rows, 1):
        db.merge(SeasonResult(season_id=season.id, channel_id=r.channel_id, canonical_uid=r.canonical_uid, rank=rank, points=r.points, tier=r.tier))
        if rank > 3:
            continue
        p = db.execute(select(Player).where(Player.channel_id == r.channel_id, Player.twitch_uid == r.canonical_uid)).scalar_one_or_none()
        if not p:
            continue
        TITLE_DEFS.setdefault(f'season{season.number}_champion', f'Season {season.number} Champion')
        TITLE_DEFS.setdefault(f'season{season.number}_finalist', f'Season {season.number} Finalist')
        unlock_title(db, p, f'season{season.number}_champion' if rank == 1 else f'season{season.number}_finalist')
        give_hat(db, p, 'crown' if rank == 1 else 'laurel')
        p.sc += CHAMPION_SC[rank - 1]
        winners.append((rank, p.display_name, r.points))
    season.closed = 1
    t = THEME.get(season.theme, THEMES[0])
    if winners:
        podium = ' · '.join(f"{['🥇', '🥈', '🥉'][k - 1]} {n} ({pts:,})" for k, n, pts in winners)
        stream_overlay.highlight(db, season.world, 'season', f'Season {season.number} is over: {t[2]}', podium[:240], emoji='🏁')
    return winners


# ---------------------------------------------------------------- views

def rank_of(db, season, p):
    row = _score(db, season, p, create=False)
    if row is None or row.points <= 0:
        return None, row
    ahead = db.execute(select(func.count()).select_from(SeasonScore).where(SeasonScore.season_id == season.id, SeasonScore.points > row.points)).scalar()
    return ahead + 1, row


def next_reward(row, season):
    t = THEME.get(season.theme, THEMES[0])
    tier = row.tier if row else 0
    if tier >= len(TIERS):
        return None
    key, emoji, label, need = TIERS[tier]
    what = {'bronze': f'the {t[5]} title', 'silver': f'the {HATS[t[4]][1]}', 'gold': f'the Golden {t[5]} title and +{GOLD_SC} SC'}[key]
    return emoji, label, need, what


def overview(db, p, provider='discord'):
    season = current(db)
    s = info(season)
    rank, row = rank_of(db, season, p)
    points = row.points if row else 0
    nxt = next_reward(row, season)
    total = db.execute(select(func.coalesce(func.sum(SeasonScore.points), 0)).where(SeasonScore.season_id == season.id)).scalar() or 0
    goal = next(((need, emoji, text) for need, key, emoji, text in MILESTONES if total < need), None)
    if provider != 'discord':
        parts = [f"{s['emoji']} Season {s['number']}: {s['name']} · {s['days_left']}d left",
                 f"You: {points:,} pts" + (f' (#{rank})' if rank else ''),
                 (f"next {nxt[0]} {nxt[1]} at {nxt[2]:,}" if nxt else 'all rewards unlocked'),
                 '!season top · !hat']
        return ' | '.join(parts)
    lines = [f"{s['emoji']} **SEASON {s['number']}: {s['name'].upper()}**",
             f"Chapter {s['chapter']}/{s['chapters']} · {s['days_left']} days left",
             f"📖 {s['story']}", '',
             f"**You:** {points:,} season points" + (f' · rank **#{rank}**' if rank else ' · not ranked yet')]
    if nxt:
        lines.append(f'Next reward: {nxt[0]} **{nxt[1]}** at {nxt[2]:,} points ({max(0, nxt[2] - points):,} to go): {nxt[3]}.')
    else:
        lines.append('🥇 Every season reward unlocked. Now chase the top three for a champion title!')
    lines.append('')
    lines.append(f'🤝 **Community:** {total:,} points together' + (f' · next milestone {goal[0]:,}: {goal[1]} {goal[2]}' if goal else ' · every milestone reached!'))
    lines.append('Points: 3 per Contribution, 1 per aptitude XP, plus stream challenges, colony votes and trophies. Only season points reset at the end; stats and items stay.')
    return '\n'.join(lines)


def top_text(db, p=None, provider='discord'):
    season = current(db)
    s = info(season)
    rows = standings(db, season, 10)
    if not rows:
        return f"{s['emoji']} Season {s['number']} leaderboard: nobody has scored yet. Every action counts!"
    medal = lambda i: ['🥇', '🥈', '🥉'][i] if i < 3 else f'{i + 1}.'
    if provider != 'discord':
        return f"{s['emoji']} Season {s['number']} top: " + ' | '.join(f'{medal(i)} {n} {r.points:,}' for i, (r, n) in enumerate(rows[:5]))
    lines = [f"{s['emoji']} **SEASON {s['number']} LEADERBOARD** · {s['days_left']} days left", '']
    lines += [f'{medal(i)} **{n}** — {r.points:,} pts' + (f" {TIERS[r.tier - 1][1]}" if r.tier else '') for i, (r, n) in enumerate(rows)]
    if p:
        rank, row = rank_of(db, season, p)
        lines += ['', f'You: #{rank} with {row.points:,} points.' if rank else 'You have not scored this season yet.']
    lines.append('Top three at the end: champion titles, a crown or laurel for your Seedling, and bonus SC.')
    return '\n'.join(lines)


def rewards_text(db, p, provider='discord'):
    season = current(db)
    t = THEME.get(season.theme, THEMES[0])
    row = _score(db, season, p, create=False)
    tier = row.tier if row else 0
    lines = [f'{t[1]} **SEASON {season.number} REWARDS**']
    for i, (key, emoji, label, need) in enumerate(TIERS):
        what = {'bronze': f'Title: {t[5]}', 'silver': f'Hat: {HATS[t[4]][0]} {HATS[t[4]][1]} (shows on the stream map)',
                'gold': f'Title: Golden {t[5]} · +{GOLD_SC} SC · a trophy'}[key]
        lines.append(f"{'✅' if tier > i else '▫️'} {emoji} **{label}** at {need:,} points — {what}")
    lines.append('🏁 End of season: 🥇 Champion title + 👑 crown + 150 SC · 🥈🥉 Finalist title + 🌿 laurel + 100/75 SC')
    lines.append('🤝 Community milestones: ' + ' · '.join(f'{emoji} {need:,}: {text}' for need, key, emoji, text in MILESTONES))
    owned, worn = hats_of(db, p)
    if owned:
        lines.append('🎩 Your hats: ' + ', '.join(f"{HATS[h][0]} {HATS[h][1]}{' (wearing)' if h == worn else ''}" for h in owned if h in HATS))
    text = '\n'.join(lines)
    return text if provider == 'discord' else text.replace('**', '')


def story_text(db, provider='discord'):
    season = current(db)
    s = info(season)
    t = THEME[s['key']]
    lines = [f"{s['emoji']} **{s['name'].upper()}** · the story so far"]
    for i, chapter in enumerate(t[6][:s['chapter']], 1):
        lines.append(f'**Week {i}.** {chapter}')
    if s['chapter'] < s['chapters']:
        lines.append(f"_Chapter {s['chapter'] + 1} arrives next week._")
    text = '\n'.join(lines)
    return text if provider == 'discord' else f"{s['emoji']} Week {s['chapter']}: {s['story']}"


def history_text(db, p):
    rows = db.execute(select(SeasonResult, Season).join(Season, Season.id == SeasonResult.season_id)
                      .where(SeasonResult.channel_id == p.channel_id, SeasonResult.canonical_uid == p.twitch_uid).order_by(Season.number)).all()
    if not rows:
        return ''
    return 'Past seasons: ' + ' · '.join(f'S{s.number} #{r.rank} ({r.points:,})' for r, s in rows[-4:])


def overlay(db):
    season = current(db)
    s = info(season)
    total = db.execute(select(func.coalesce(func.sum(SeasonScore.points), 0)).where(SeasonScore.season_id == season.id)).scalar() or 0
    goal = next((need for need, *_ in MILESTONES if total < need), MILESTONES[-1][0])
    s.update({'total': total, 'goal': goal, 'percent': round(min(100, total / max(1, goal) * 100), 1),
              'decor': [key for need, key, *_ in MILESTONES if total >= need],
              'top': [{'name': n, 'points': r.points} for r, n in standings(db, season, 5)]})
    return s
