"""Colony votes: every Avesta day the colony votes on what happens next.

Each ballot has three choices: two society projects (what gets built next) and one festival (a day of
celebration with a work bonus). Anyone can vote once per ballot from Twitch (!vote 1) or Discord (/vote),
and can change their mind until the day ends. The first vote on a ballot pays a little SC and season points.

When the Avesta day ends the ballot closes:
  * a project winner becomes the next society project. If the current project is already finished it
    starts straight away; otherwise it is queued and starts the moment the current one completes.
  * a festival winner runs for the whole next Avesta day: +5% success on its aptitudes, a party on the map.

Finished projects stay in the town as landmarks on the stream map, and everyone who helped build one is
credited (it counts towards the Project Veteran trophy). No votes? The colony picks at random.
"""
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, DateTime, select, func
from .db import Base

VOTE_SC, VOTE_POINTS = 3, 5
FESTIVAL_BONUS = 0.05
# project key -> (emoji, district on the map, one line on what it does for the colony)
PROJECT_INFO = {
    'greenhouse_expansion': ('🌿', 'agricultural_district', 'more greenhouse rows for the farms'),
    'spaceport_pad': ('🚀', 'spaceport_quarter', 'a bigger landing pad for supply shuttles'),
    'research_annex': ('🔬', 'research_block', 'a new wing for the Research Block'),
    'irrigation_grid': ('💧', 'agricultural_district', 'pipes and pumps that water every field'),
    'recreation_hall': ('🎳', 'commons', 'a hall for games, music and meetings'),
    'deepway_terminal': ('🚇', 'industrial_ward', 'a freight tunnel to the deep mines'),
    'community_kitchen': ('🍲', 'residential_ring', 'a shared kitchen where everyone eats together'),
    'clinic_expansion': ('🏥', 'residential_ring', 'more beds and a pharmacy at the clinic'),
    'fire_station': ('🚒', 'industrial_ward', 'a fire station and safety crew'),
}
# festival key -> (emoji, name, what it does, aptitudes it boosts)
FESTIVALS = {
    'harvest_fair': ('🌽', 'Harvest Fair', 'Farming and cooking +5% · a feast in the Commons', {'cultivation', 'cooking'}),
    'starlight_night': ('🌠', 'Starlight Night', 'Research and frontier work +5% · lanterns over town', {'research', 'frontier'}),
    'market_fair': ('🎪', 'Market Fair', 'Commerce and logistics +5% · a busy market', {'commerce', 'logistics'}),
    'maker_expo': ('🛠️', 'Maker Expo', 'Crafting and repairs +5% · workshops open to all', {'fabrication', 'infrastructure'}),
    'rock_festival': ('🪨', 'Festival of Rocks', 'Mining +5% · Rocky leads a parade', {'extraction'}),
    'wellness_day': ('🧘', 'Wellness Day', 'Medicine, water and safety work +5% · a quiet day', {'medicine', 'environmental', 'emergency'}),
}


class Ballot(Base):
    __tablename__ = 'colony_ballots_v1'
    world = Column(String(64), primary_key=True)
    day = Column(Integer, primary_key=True)
    options = Column(String(400), nullable=False)          # ["project:clinic_expansion", "project:…", "festival:…"]
    winner = Column(String(48), nullable=False, default='')
    votes = Column(Integer, nullable=False, default=0)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class Cast(Base):
    __tablename__ = 'colony_ballot_votes_v1'
    world = Column(String(64), primary_key=True)
    day = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    choice = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ColonyPlan(Base):
    __tablename__ = 'colony_plan_v1'
    world = Column(String(64), primary_key=True)
    next_project = Column(String(48), nullable=False, default='')
    festival = Column(String(32), nullable=False, default='')
    festival_day = Column(Integer, nullable=False, default=0)
    built = Column(String(2000), nullable=False, default='[]')   # [{"key", "day", "at", "helpers"}]
    run = Column(Integer, nullable=False, default=1)              # which build of the current project this is


class ProjectHelp(Base):
    __tablename__ = 'colony_project_help_v1'
    world = Column(String(64), primary_key=True)
    run = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    project = Column(String(48), nullable=False)
    amount = Column(Integer, nullable=False, default=0)
    finished = Column(Integer, nullable=False, default=0)


def _now():
    return datetime.now(timezone.utc)


def install(m):
    """Wrap the society project so votes can queue the next one and helpers are credited."""
    original_current, original_contribute = m.current_project, m.project_contribute

    def current_project(db, channel, day):
        row = original_current(db, channel, day)
        if enabled(m):
            advance(m, db, row, day)
        return row

    def project_contribute(db, p, skill, amount=1):
        note = original_contribute(db, p, skill, amount)
        if note and enabled(m):
            try:
                credit(m, db, p, amount)
            except Exception:
                pass
        return note
    current_project.__wrapped__, project_contribute.__wrapped__ = original_current, original_contribute
    m.current_project, m.project_contribute = current_project, project_contribute


def enabled(m):
    from . import community
    return community.ENABLED


def plan(m, db, world=None):
    world = world or m.DISCORD_WORLD_ID
    row = db.get(ColonyPlan, world)
    if row is None:
        row = ColonyPlan(world=world, next_project='', festival='', festival_day=0, built='[]', run=1)
        db.add(row)
        db.flush()
    return row


def label(option):
    kind, key = option.split(':', 1)
    if kind == 'project':
        from . import main as m
        cfg = m.project_cfg(key)
        emoji, place, text = PROJECT_INFO.get(key, ('🏗️', 'commons', 'a new building for the colony'))
        return emoji, cfg[1], f'Build next: {text} (goal {cfg[2]})'
    emoji, name, text, _ = FESTIVALS[key]
    return emoji, name, f'Festival tomorrow: {text}'


def _stable(seed, n):
    import hashlib
    return int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16) % max(1, n)


def ballot(m, db, day=None, world=None):
    """Today's ballot (created on first look)."""
    world = world or m.DISCORD_WORLD_ID
    day = day or m.world_clock(db, world)['day']
    row = db.get(Ballot, (world, day))
    if row is None:
        current = db.execute(select(m.SocietyProject).where(m.SocietyProject.channel_id == world)).scalar_one_or_none()
        skip = {current.project_key if current else '', plan(m, db, world).next_project}
        projects = [k for k, *_ in m.PROJECTS if k not in skip]
        first = projects[_stable(f'{world}:{day}:p1', len(projects))]
        rest = [k for k in projects if k != first]
        second = rest[_stable(f'{world}:{day}:p2', len(rest))]
        fests = list(FESTIVALS)
        fest = fests[_stable(f'{world}:{day}:f', len(fests))]
        options = [f'project:{first}', f'project:{second}', f'festival:{fest}']
        order = _stable(f'{world}:{day}:order', 3)
        options = options[order:] + options[:order]
        row = Ballot(world=world, day=day, options=json.dumps(options), winner='', votes=0)
        db.add(row)
        db.flush()
    return row


def tally(db, row):
    counts = dict(db.execute(select(Cast.choice, func.count()).where(Cast.world == row.world, Cast.day == row.day).group_by(Cast.choice)).all())
    return [counts.get(i, 0) for i in range(1, len(json.loads(row.options)) + 1)]


def cast(m, db, p, choice, provider='twitch'):
    world = m.DISCORD_WORLD_ID
    sync(m, db)
    row = ballot(m, db)
    options = json.loads(row.options)
    pick = _match(options, choice)
    if pick is None:
        return view(m, db, p, provider, prefix='🗳️ Pick 1, 2 or 3. ')
    found = db.get(Cast, (world, row.day, p.channel_id, p.twitch_uid))
    first = found is None
    if first:
        db.add(Cast(world=world, day=row.day, channel_id=p.channel_id, canonical_uid=p.twitch_uid, choice=pick, created_at=_now()))
        p.sc += VOTE_SC
        row.votes += 1
        from . import seasons
        reward = seasons.add(m, db, p, VOTE_POINTS, kind='votes')
    else:
        found.choice = pick
        reward = ''
    db.flush()
    emoji, name, _ = label(options[pick - 1])
    counts = tally(db, row)
    standing = ' · '.join(f'{i + 1} {label(o)[1]} {c}' for i, (o, c) in enumerate(zip(options, counts)))
    left = _left(m, db)
    if provider != 'discord':
        return (f"🗳️ {'Voted' if first else 'Changed to'} {emoji} {name}" + (f' +{VOTE_SC} SC' if first else '') + f' | {standing} | closes in {left}')[:200]
    return (f"🗳️ **{'Vote counted' if first else 'Vote changed'}: {emoji} {name}**" + (f' · +{VOTE_SC} SC, +{VOTE_POINTS} season points' if first else '')
            + f'\nNow: {standing}\nThe ballot closes in {left}, when the Avesta day ends.' + (f'\n{reward}' if reward else ''))


def _match(options, choice):
    text = str(choice or '').strip().casefold()
    if text.isdigit() and 1 <= int(text) <= len(options):
        return int(text)
    if not text:
        return None
    for i, o in enumerate(options, 1):
        name = label(o)[1].casefold()
        if text in name or text == o.split(':', 1)[1]:
            return i
    return None


def _left(m, db):
    clock = m.world_clock(db, m.DISCORD_WORLD_ID)
    seconds = max(0, m.AVESTA_DAY_SECONDS - clock['seconds'])
    return f'{seconds // 3600}h {seconds % 3600 // 60}m' if seconds >= 3600 else f'{seconds // 60}m'


def view(m, db, p=None, provider='discord', prefix=''):
    sync(m, db)
    row = ballot(m, db)
    options, counts = json.loads(row.options), tally(db, row)
    mine = db.get(Cast, (row.world, row.day, p.channel_id, p.twitch_uid)) if p else None
    total = sum(counts) or 1
    cmd = '/vote choice:' if provider == 'discord' else '!vote '
    if provider != 'discord':
        body = ' · '.join(f'{i}) {label(o)[0]} {label(o)[1]} {c}' for i, (o, c) in enumerate(zip(options, counts), 1))
        return (prefix + f'🗳️ Day {row.day} vote: {body} | {cmd}1-3 · closes in {_left(m, db)}')[:200]
    lines = [prefix + f'🗳️ **COLONY VOTE · Avesta Day {row.day}**', 'What should New Eridian do next? The ballot closes when the day ends.', '']
    for i, (o, c) in enumerate(zip(options, counts), 1):
        emoji, name, text = label(o)
        mark = ' ✅ your vote' if mine and mine.choice == i else ''
        bar = '▰' * round(c / total * 10) + '▱' * (10 - round(c / total * 10))
        lines.append(f'**{i}. {emoji} {name}** — {c} vote{"s" if c != 1 else ""} {bar}{mark}\n   {text}')
    lines += ['', f'Closes in {_left(m, db)}. First vote on a ballot: +{VOTE_SC} SC and +{VOTE_POINTS} season points.']
    lines.append(status_line(m, db))
    return '\n'.join(x for x in lines if x is not None)


def status_line(m, db):
    pl = plan(m, db)
    bits = []
    if pl.next_project:
        bits.append(f"Next project (voted): {label('project:' + pl.next_project)[1]}")
    fest = festival_today(m, db)
    if fest:
        bits.append(f'Today: {FESTIVALS[fest][0]} {FESTIVALS[fest][1]}')
    built = json.loads(pl.built or '[]')
    if built:
        bits.append(f'{len(built)} projects built')
    return ' · '.join(bits)


# ---------------------------------------------------------------- closing ballots and building

def sync(m, db):
    """Close every past ballot and apply its winner."""
    if not enabled(m):
        return []
    world = m.DISCORD_WORLD_ID
    today = m.world_clock(db, world)['day']
    done = []
    for row in db.execute(select(Ballot).where(Ballot.world == world, Ballot.day < today, Ballot.resolved_at.is_(None)).order_by(Ballot.day)).scalars().all():
        done.append(resolve(m, db, row, today))
    return done


def resolve(m, db, row, today):
    options, counts = json.loads(row.options), tally(db, row)
    if any(counts):
        best = max(counts)
        leaders = [i for i, c in enumerate(counts) if c == best]
        if len(leaders) > 1:        # a tie goes to whichever reached the top count first
            first = {}
            for c in db.execute(select(Cast).where(Cast.world == row.world, Cast.day == row.day).order_by(Cast.created_at)).scalars():
                first.setdefault(c.choice - 1, c.created_at)
            leaders.sort(key=lambda i: first.get(i) or _now())
        pick = leaders[0]
    else:
        pick = _stable(f'{row.world}:{row.day}:none', len(options))
    row.winner, row.resolved_at = options[pick], _now()
    kind, key = row.winner.split(':', 1)
    emoji, name, text = label(row.winner)
    pl = plan(m, db, row.world)
    total = sum(counts)
    how = f'{counts[pick]} of {total} votes' if total else 'no votes, so the colony picked'
    from . import stream_overlay
    if kind == 'project':
        # Twitch and Discord can keep separate society projects: the vote queues the winner for each of them.
        for current in db.execute(select(m.SocietyProject)).scalars().all():
            plan(m, db, current.channel_id).next_project = key
            advance(m, db, current, today)
        pl.next_project = pl.next_project if db.execute(select(m.SocietyProject).where(m.SocietyProject.channel_id == row.world)).first() else key
        stream_overlay.highlight(db, row.world, 'vote', f'The colony voted: {name} is next!', f'{emoji} {text} ({how}).', emoji='🗳️')
    else:
        pl.festival, pl.festival_day = key, row.day + 1
        stream_overlay.highlight(db, row.world, 'vote', f'The colony voted: {name}!', f'{emoji} {text.split(": ", 1)[-1]} ({how}).', emoji='🗳️')
    return row.winner


def advance(m, db, row, day):
    """Start the voted project once the current one is finished; the finished one becomes a landmark."""
    pl = db.get(ColonyPlan, row.channel_id)
    if pl is None or not pl.next_project or row.progress < row.goal:
        return False
    built = json.loads(pl.built or '[]')
    helpers = db.execute(select(func.count()).select_from(ProjectHelp).where(ProjectHelp.world == row.channel_id, ProjectHelp.run == pl.run)).scalar() or 0
    db.execute(ProjectHelp.__table__.update().where(ProjectHelp.world == row.channel_id, ProjectHelp.run == pl.run).values(finished=1))
    built.append({'key': row.project_key, 'day': day, 'at': _now().isoformat(), 'helpers': helpers})
    pl.built = json.dumps(built[-40:])
    cfg = m.project_cfg(pl.next_project)
    row.project_key, row.progress, row.goal, row.started_day = cfg[0], 0, cfg[2], day
    pl.next_project, pl.run = '', pl.run + 1
    from . import stream_overlay
    stream_overlay.highlight(db, row.channel_id, 'project', f'Construction starts: {cfg[1]}',
                             f"Voted by the colony. Helps: {', '.join(m.SKILL_LABELS.get(s, s) for s in sorted(cfg[3]))}.", emoji='🏗️')
    return True


def credit(m, db, p, amount):
    pl = plan(m, db, p.channel_id)
    row = db.execute(select(m.SocietyProject).where(m.SocietyProject.channel_id == p.channel_id)).scalar_one_or_none()
    key = row.project_key if row else ''
    found = db.get(ProjectHelp, (pl.world, pl.run, p.channel_id, p.twitch_uid))
    if found is None:
        found = ProjectHelp(world=pl.world, run=pl.run, channel_id=p.channel_id, canonical_uid=p.twitch_uid, project=key, amount=0, finished=0)
        db.add(found)
    found.amount += amount
    if row and row.progress >= row.goal:
        found.finished = 1
        db.execute(ProjectHelp.__table__.update().where(ProjectHelp.world == pl.world, ProjectHelp.run == pl.run).values(finished=1))


def projects_helped(db, p):
    return db.execute(select(func.count()).select_from(ProjectHelp).where(ProjectHelp.channel_id == p.channel_id, ProjectHelp.canonical_uid == p.twitch_uid,
                                                                          ProjectHelp.finished == 1)).scalar() or 0


def votes_cast(db, p):
    return db.execute(select(func.count()).select_from(Cast).where(Cast.channel_id == p.channel_id, Cast.canonical_uid == p.twitch_uid)).scalar() or 0


# ---------------------------------------------------------------- festivals

_festival_cache = {}


def festival_today(m, db):
    world = m.DISCORD_WORLD_ID
    pl = db.get(ColonyPlan, world)
    if not pl or not pl.festival:
        return ''
    day = m.world_clock(db, world)['day']
    return pl.festival if pl.festival_day == day else ''


def success_bonus(m, db, skill):
    if not enabled(m) or not skill:
        return 0, []
    fest = festival_today(m, db)
    if fest and skill in FESTIVALS[fest][3]:
        return FESTIVAL_BONUS, [f'{FESTIVALS[fest][0]} {FESTIVALS[fest][1]} +{round(FESTIVAL_BONUS * 100)}%']
    return 0, []


def overlay(m, db):
    sync(m, db)
    row = ballot(m, db)
    options, counts = json.loads(row.options), tally(db, row)
    pl = plan(m, db)
    fest = festival_today(m, db)
    built = []
    for b in json.loads(pl.built or '[]'):
        emoji, place, text = PROJECT_INFO.get(b['key'], ('🏗️', 'commons', ''))
        built.append({'key': b['key'], 'name': m.project_cfg(b['key'])[1], 'emoji': emoji, 'place': place, 'day': b.get('day'), 'helpers': b.get('helpers', 0)})
    current = db.execute(select(m.SocietyProject).where(m.SocietyProject.channel_id == m.DISCORD_WORLD_ID)).scalar_one_or_none()
    return {'day': row.day, 'closes_in': _left(m, db), 'total': sum(counts),
            'options': [{'n': i, 'kind': o.split(':')[0], 'emoji': label(o)[0], 'name': label(o)[1], 'text': label(o)[2], 'votes': c}
                        for i, (o, c) in enumerate(zip(options, counts), 1)],
            'next_project': m.project_cfg(pl.next_project)[1] if pl.next_project else '',
            'festival': {'key': fest, 'emoji': FESTIVALS[fest][0], 'name': FESTIVALS[fest][1], 'text': FESTIVALS[fest][2]} if fest else None,
            'built': built,
            'building': {'key': current.project_key, 'place': PROJECT_INFO.get(current.project_key, ('', 'commons'))[1],
                         'emoji': PROJECT_INFO.get(current.project_key, ('🏗️',))[0],
                         'percent': round(min(100, current.progress / max(1, current.goal) * 100))} if current else None}


def week_winners(m, db, since):
    rows = db.execute(select(Ballot).where(Ballot.world == m.DISCORD_WORLD_ID, Ballot.resolved_at >= since).order_by(Ballot.day)).scalars().all()
    return [(r.day, label(r.winner), r.votes) for r in rows if r.winner]


def built_since(m, db, since):
    out = []
    for b in [b for pl in db.execute(select(ColonyPlan)).scalars() for b in json.loads(pl.built or '[]')]:
        try:
            at = datetime.fromisoformat(b.get('at'))
        except (TypeError, ValueError):
            continue
        if at >= since:
            out.append((m.project_cfg(b['key'])[1], PROJECT_INFO.get(b['key'], ('🏗️',))[0], b.get('helpers', 0)))
    return out
