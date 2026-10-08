"""Colony votes: every Avesta day the colony votes on what happens next.

Each ballot has three choices: two society projects (what gets built next) and one festival (a day of
celebration with a work bonus). Anyone can vote once per ballot from Twitch (!vote 1) or Discord (/vote),
and can change their mind until the day ends. The first vote on a ballot pays a little SC and season points.

When the Avesta day ends the ballot closes:
  * a project winner becomes the next society project. If the current project is already finished it
    starts straight away; otherwise it is queued and starts the moment the current one completes.
  * a festival winner runs for the whole next Avesta day: +5% success on its aptitudes, a party on the map.

The moment a project is finished:
  * it is built: a landmark appears in its district on the stream map and the feed and alerts announce it;
  * everyone who helped is paid (5 SC plus 1 SC per contribution, up to 30) and gets season points;
  * the society gains Development and Reputation;
  * it gives a lasting perk: +2% success for everyone on the project's aptitudes (up to +6% when the same
    building is built again);
  * the next voted project starts. If none is queued, the next ballot always restarts construction: a
    project winner starts, and if a festival wins, the best-placed project on that ballot starts too.

On a festival day everyone also gets a festival gift with their first action. Everyone who helped build a
project counts towards the Builder and Project Veteran trophies. No votes? The colony picks at random.
"""
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Integer, DateTime, select, func
from .db import Base
from . import runtime
from .models import Player
from .models import SocietyProject

VOTE_SC, VOTE_POINTS = 3, 5
FESTIVAL_BONUS = 0.05
PERK, PERK_CAP = 0.02, 0.06                # a finished building: +2% on its aptitudes, stacking to +6%
HELPER_SC, HELPER_SC_MAX, HELPER_POINTS = 5, 30, 10
BUILT_STATS = {'development': 10, 'reputation': 5}
# festival -> (SC, items) given once to everyone on the festival day, with their first action
FESTIVAL_GIFTS = {'harvest_fair': (5, {'Berries': 3}), 'starlight_night': (5, {'Herbs': 2}), 'market_fair': (15, {}),
                  'maker_expo': (5, {'Clay': 2}), 'rock_festival': (5, {'Stone': 3}), 'wellness_day': (5, {'Herbs': 2})}
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


class FestivalGift(Base):
    __tablename__ = 'colony_festival_gifts_v1'
    world = Column(String(64), primary_key=True)
    day = Column(Integer, primary_key=True)
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)


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
    from .game.world import world_clock
    original_current, original_contribute = runtime.current_project, runtime.project_contribute

    def current_project(db, channel, day):
        row = original_current(db, channel, day)
        if enabled():
            advance(db, row, day)
        return row

    def project_contribute(db, p, skill, amount=1):
        note = original_contribute(db, p, skill, amount)
        if note and enabled():
            try:
                credit(db, p, amount)
                row = db.execute(select(SocietyProject).where(SocietyProject.channel_id == p.channel_id)).scalar_one_or_none()
                if row is not None and row.progress >= row.goal:
                    paid = complete(db, row)
                    if paid:
                        note += f' 🏗️ Built! {paid} helpers paid.'
                    advance(db, row, world_clock(db, p.channel_id)['day'])
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Project completion failed')
        return note
    current_project.__wrapped__, project_contribute.__wrapped__ = original_current, original_contribute
    m.current_project, m.project_contribute = current_project, project_contribute


def enabled():
    from . import community
    return community.ENABLED


def plan(db, world=None):
    world = world or runtime.DISCORD_WORLD_ID
    row = db.get(ColonyPlan, world)
    if row is None:
        row = ColonyPlan(world=world, next_project='', festival='', festival_day=0, built='[]', run=1)
        db.add(row)
        db.flush()
    return row


def label(option):
    from .game.world import project_cfg
    kind, key = option.split(':', 1)
    if kind == 'project':
        from . import main as m
        cfg = project_cfg(key)
        emoji, place, text = PROJECT_INFO.get(key, ('🏗️', 'commons', 'a new building for the colony'))
        return emoji, cfg[1], f'Build next: {text} (goal {cfg[2]}). When built: {perk_text(key)}'
    emoji, name, text, _ = FESTIVALS[key]
    return emoji, name, f'Festival tomorrow: {text}'


def _stable(seed, n):
    import hashlib
    return int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16) % max(1, n)


def ballot(db, day=None, world=None):
    """Today's ballot (created on first look)."""
    from .game.rules import PROJECTS
    from .game.world import world_clock
    world = world or runtime.DISCORD_WORLD_ID
    day = day or world_clock(db, world)['day']
    row = db.get(Ballot, (world, day))
    if row is None:
        current = db.execute(select(SocietyProject).where(SocietyProject.channel_id == world)).scalar_one_or_none()
        skip = {current.project_key if current else '', plan(db, world).next_project}
        projects = [k for k, *_ in PROJECTS if k not in skip]
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


def cast(db, p, choice, provider='twitch'):
    world = runtime.DISCORD_WORLD_ID
    sync(db)
    row = ballot(db)
    options = json.loads(row.options)
    pick = _match(options, choice)
    if pick is None:
        return view(db, p, provider, prefix='🗳️ Pick 1, 2 or 3. ')
    found = db.get(Cast, (world, row.day, p.channel_id, p.twitch_uid))
    first = found is None
    if first:
        db.add(Cast(world=world, day=row.day, channel_id=p.channel_id, canonical_uid=p.twitch_uid, choice=pick, created_at=_now()))
        p.sc += VOTE_SC
        row.votes += 1
        from . import seasons
        reward = seasons.add(db, p, VOTE_POINTS, kind='votes')
    else:
        found.choice = pick
        reward = ''
    db.flush()
    emoji, name, _ = label(options[pick - 1])
    counts = tally(db, row)
    standing = ' · '.join(f'{i + 1} {label(o)[1]} {c}' for i, (o, c) in enumerate(zip(options, counts)))
    left = _left(db)
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


def _left(db):
    from .game.base import AVESTA_DAY_SECONDS
    from .game.world import world_clock
    clock = world_clock(db, runtime.DISCORD_WORLD_ID)
    seconds = max(0, AVESTA_DAY_SECONDS - clock['seconds'])
    return f'{seconds // 3600}h {seconds % 3600 // 60}m' if seconds >= 3600 else f'{seconds // 60}m'


def view(db, p=None, provider='discord', prefix=''):
    from .game.world import project_cfg
    sync(db)
    row = ballot(db)
    options, counts = json.loads(row.options), tally(db, row)
    mine = db.get(Cast, (row.world, row.day, p.channel_id, p.twitch_uid)) if p else None
    total = sum(counts) or 1
    cmd = '/vote choice:' if provider == 'discord' else '!vote '
    if provider != 'discord':
        body = ' · '.join(f'{i}) {label(o)[0]} {label(o)[1]} {c}' for i, (o, c) in enumerate(zip(options, counts), 1))
        text = prefix + f'🗳️ Day {row.day} vote: {body} | {cmd}1-3 · closes in {_left(db)}'
        last = last_result(db)
        return (text + (f' | {last}' if last and len((text + last).encode()) < 195 else ''))[:200]
    lines = [prefix + f"🗳️ **TODAY'S VOTE · Avesta Day {row.day}**", 'What should New Eridian do next? The ballot closes when the day ends.', '']
    for i, (o, c) in enumerate(zip(options, counts), 1):
        emoji, name, text = label(o)
        mark = ' ✅ your vote' if mine and mine.choice == i else ''
        bar = '▰' * round(c / total * 10) + '▱' * (10 - round(c / total * 10))
        lines.append(f'**{i}. {emoji} {name}** — {c} vote{"s" if c != 1 else ""} {bar}{mark}\n   {text}')
    lines += ['', f'Closes in {_left(db)}. First vote on a ballot: +{VOTE_SC} SC and +{VOTE_POINTS} season points.']
    last = last_result(db)
    if last:
        lines.append(last)
    lines.append(status_line(db))
    towns = buildings(db, runtime.DISCORD_WORLD_ID)
    if towns:
        lines.append('🏗️ Built so far: ' + ' · '.join(f"{PROJECT_INFO.get(k, ('🏗️',))[0]} {project_cfg(k)[1]}{f' ×{n}' if n > 1 else ''} ({perk_text(k).split(' for')[0]})" for k, n in towns.items()))
    lines.append('How it works: a project winner is built next and gives a lasting perk; a festival winner runs tomorrow with +5% and a gift for everyone.')
    return '\n'.join(x for x in lines if x is not None)


def status_line(db):
    pl = plan(db)
    bits = []
    if pl.next_project:
        bits.append(f"Next project (voted): {label('project:' + pl.next_project)[1]}")
    fest = festival_today(db)
    if fest:
        bits.append(f'Today: {FESTIVALS[fest][0]} {FESTIVALS[fest][1]}')
    built = json.loads(pl.built or '[]')
    if built:
        bits.append(f'{len(built)} projects built')
    return ' · '.join(bits)


# ---------------------------------------------------------------- closing ballots and building

def sync(db):
    """Close every past ballot and apply its winner."""
    from .game.world import world_clock
    if not enabled():
        return []
    world = runtime.DISCORD_WORLD_ID
    today = world_clock(db, world)['day']
    done = []
    for row in db.execute(select(Ballot).where(Ballot.world == world, Ballot.day < today, Ballot.resolved_at.is_(None)).order_by(Ballot.day)).scalars().all():
        done.append(resolve(db, row, today))
    return done


def resolve(db, row, today):
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
    pl = plan(db, row.world)
    total = sum(counts)
    how = f'{counts[pick]} of {total} votes' if total else 'no votes, so the colony picked'
    from . import stream_overlay
    if kind == 'project':
        # Twitch and Discord can keep separate society projects: the vote queues the winner for each of them.
        for current in db.execute(select(SocietyProject)).scalars().all():
            plan(db, current.channel_id).next_project = key
            advance(db, current, today)
        pl.next_project = pl.next_project if db.execute(select(SocietyProject).where(SocietyProject.channel_id == row.world)).first() else key
        stream_overlay.highlight(db, row.world, 'vote', f'The colony voted: {name} is next!', f'{emoji} {text} ({how}).', emoji='🗳️')
    else:
        pl.festival, pl.festival_day = key, row.day + 1
        stream_overlay.highlight(db, row.world, 'vote', f'The colony voted: {name}!', f'{emoji} {text.split(": ", 1)[-1]} ({how}).', emoji='🗳️')
        # Construction never stalls: an idle building site takes the best-placed project on this ballot.
        ranked = sorted((i for i, o in enumerate(options) if o.startswith('project:')), key=lambda i: -counts[i])
        if ranked:
            runner = options[ranked[0]].split(':', 1)[1]
            for current in db.execute(select(SocietyProject)).scalars().all():
                site = plan(db, current.channel_id)
                if current.progress >= current.goal and not site.next_project:
                    site.next_project = runner
                    advance(db, current, today)
    return row.winner


def perk_text(key):
    from .game.rules import SKILL_LABELS
    from .game.world import project_cfg
    skills = ', '.join(SKILL_LABELS.get(s, s) for s in sorted(project_cfg(key)[3]))
    return f'+{round(PERK * 100)}% {skills} success for everyone'


def complete(db, row):
    """A project was just finished: build it, pay everyone who helped, boost the society. Once per build.
    Returns how many helpers were paid (0 when this build was already recorded)."""
    from .game.players import society
    from .game.world import project_cfg, world_clock
    pl = plan(db, row.channel_id)
    built = json.loads(pl.built or '[]')
    # Recording a build moves the plan on to the next run, so this row is already built when the latest
    # entry is the same project, started the same day, in the previous run.
    if any(b.get('key') == row.project_key and b.get('start') == row.started_day and b.get('run') == pl.run - 1 for b in built):
        return 0
    helpers = db.execute(select(ProjectHelp).where(ProjectHelp.world == row.channel_id, ProjectHelp.run == pl.run, ProjectHelp.amount > 0)).scalars().all()
    from . import seasons, stream_overlay
    paid = 0
    for h in helpers:
        h.finished = 1
        p = db.execute(select(Player).where(Player.channel_id == h.channel_id, Player.twitch_uid == h.canonical_uid)).scalar_one_or_none()
        if p is None:
            continue
        p.sc += min(HELPER_SC_MAX, HELPER_SC + h.amount)
        seasons.add(db, p, HELPER_POINTS + h.amount)
        paid += 1
    s = society(db, row.channel_id)
    for field, n in BUILT_STATS.items():
        setattr(s, field, getattr(s, field) + n)
    day = world_clock(db, row.channel_id)['day']
    built.append({'key': row.project_key, 'day': day, 'at': _now().isoformat(), 'helpers': len(helpers), 'run': pl.run,
                  'start': row.started_day})
    pl.built = json.dumps(built[-40:])
    pl.run += 1
    cfg = project_cfg(row.project_key)
    emoji = PROJECT_INFO.get(row.project_key, ('🏗️',))[0]
    stream_overlay.highlight(db, row.channel_id, 'project', f'{cfg[1]} is built!',
                             f'{emoji} {paid} helpers paid · {perk_text(row.project_key)} · +10 Development, +5 Reputation', emoji=emoji)
    return paid


def advance(db, row, day):
    """Start the voted project once the current one is finished (building the finished one first if needed)."""
    from .game.rules import SKILL_LABELS
    from .game.world import project_cfg
    if row.progress < row.goal:
        return False
    complete(db, row)
    pl = db.get(ColonyPlan, row.channel_id)
    if pl is None or not pl.next_project:
        return False
    cfg = project_cfg(pl.next_project)
    row.project_key, row.progress, row.goal, row.started_day = cfg[0], 0, cfg[2], day
    pl.next_project = ''
    from . import stream_overlay
    stream_overlay.highlight(db, row.channel_id, 'project', f'Construction starts: {cfg[1]}',
                             f"Voted by the colony. Helps: {', '.join(SKILL_LABELS.get(s, s) for s in sorted(cfg[3]))}.", emoji='🏗️')
    return True


def credit(db, p, amount):
    pl = plan(db, p.channel_id)
    row = db.execute(select(SocietyProject).where(SocietyProject.channel_id == p.channel_id)).scalar_one_or_none()
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


def festival_today(db):
    from .game.world import world_clock
    world = runtime.DISCORD_WORLD_ID
    pl = db.get(ColonyPlan, world)
    if not pl or not pl.festival:
        return ''
    day = world_clock(db, world)['day']
    return pl.festival if pl.festival_day == day else ''


def buildings(db, channel):
    """{project key: times built} for a channel's town."""
    counts = {}
    for b in json.loads(plan(db, channel).built or '[]'):
        counts[b['key']] = counts.get(b['key'], 0) + 1
    return counts


def building_bonus(db, p, skill):
    """Lasting perks from finished buildings: +2% per build of a building that covers this aptitude, up to +6%."""
    from .game.world import project_cfg
    if not enabled() or not skill:
        return 0, []
    total, names = 0, []
    for key, n in buildings(db, p.channel_id).items():
        if skill in project_cfg(key)[3]:
            total += PERK * n
            names.append(project_cfg(key)[1])
    total = min(PERK_CAP, total)
    return (total, [f"🏗️ {', '.join(names)} +{round(total * 100)}%"]) if total else (0, [])


def festival_gift(db, p):
    """Everyone's first action on a festival day comes with a gift. Returns the note, or ''."""
    from . import seed_content
    from .game.cooldowns_materials import material_change
    from .game.world import world_clock
    fest = festival_today(db)
    if not fest:
        return ''
    day = world_clock(db, runtime.DISCORD_WORLD_ID)['day']
    if db.get(FestivalGift, (runtime.DISCORD_WORLD_ID, day, p.channel_id, p.twitch_uid)) is not None:
        return ''
    db.add(FestivalGift(world=runtime.DISCORD_WORLD_ID, day=day, channel_id=p.channel_id, canonical_uid=p.twitch_uid))
    sc, items = FESTIVAL_GIFTS.get(fest, (5, {}))
    p.sc += sc
    for name, n in items.items():
        try:
            material_change(db, p, seed_content.key(name), n)
        except KeyError:
            pass
    got = ', '.join([f'+{sc} SC'] + [f'+{n} {k}' for k, n in items.items()])
    return f'{FESTIVALS[fest][0]} {FESTIVALS[fest][1]} gift: {got}'


def last_result(db):
    row = db.execute(select(Ballot).where(Ballot.world == runtime.DISCORD_WORLD_ID, Ballot.resolved_at.is_not(None))
                     .order_by(Ballot.day.desc())).scalars().first()
    if row is None or not row.winner:
        return ''
    emoji, name, _ = label(row.winner)
    return f'Last vote: {emoji} {name} won ({row.votes} voter{"s" if row.votes != 1 else ""})'


def success_bonus(db, skill):
    if not enabled() or not skill:
        return 0, []
    fest = festival_today(db)
    if fest and skill in FESTIVALS[fest][3]:
        return FESTIVAL_BONUS, [f'{FESTIVALS[fest][0]} {FESTIVALS[fest][1]} +{round(FESTIVAL_BONUS * 100)}%']
    return 0, []


def overlay(db):
    from .game.world import project_cfg
    sync(db)
    row = ballot(db)
    options, counts = json.loads(row.options), tally(db, row)
    pl = plan(db)
    fest = festival_today(db)
    built = []
    for b in json.loads(pl.built or '[]'):
        emoji, place, text = PROJECT_INFO.get(b['key'], ('🏗️', 'commons', ''))
        built.append({'key': b['key'], 'name': project_cfg(b['key'])[1], 'emoji': emoji, 'place': place, 'day': b.get('day'), 'helpers': b.get('helpers', 0)})
    current = db.execute(select(SocietyProject).where(SocietyProject.channel_id == runtime.DISCORD_WORLD_ID)).scalar_one_or_none()
    return {'day': row.day, 'closes_in': _left(db), 'total': sum(counts),
            'options': [{'n': i, 'kind': o.split(':')[0], 'emoji': label(o)[0], 'name': label(o)[1], 'text': label(o)[2], 'votes': c}
                        for i, (o, c) in enumerate(zip(options, counts), 1)],
            'next_project': project_cfg(pl.next_project)[1] if pl.next_project else '',
            'festival': {'key': fest, 'emoji': FESTIVALS[fest][0], 'name': FESTIVALS[fest][1], 'text': FESTIVALS[fest][2]} if fest else None,
            'built': built,
            'building': {'key': current.project_key, 'place': PROJECT_INFO.get(current.project_key, ('', 'commons'))[1],
                         'emoji': PROJECT_INFO.get(current.project_key, ('🏗️',))[0],
                         'percent': round(min(100, current.progress / max(1, current.goal) * 100))} if current else None}


def week_winners(db, since):
    rows = db.execute(select(Ballot).where(Ballot.world == runtime.DISCORD_WORLD_ID, Ballot.resolved_at >= since).order_by(Ballot.day)).scalars().all()
    return [(r.day, label(r.winner), r.votes) for r in rows if r.winner]


def built_since(db, since):
    from .game.world import project_cfg
    out = []
    for b in [b for pl in db.execute(select(ColonyPlan)).scalars() for b in json.loads(pl.built or '[]')]:
        try:
            at = datetime.fromisoformat(b.get('at'))
        except (TypeError, ValueError):
            continue
        if at >= since:
            out.append((project_cfg(b['key'])[1], PROJECT_INFO.get(b['key'], ('🏗️',))[0], b.get('helpers', 0)))
    return out
