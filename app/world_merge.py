"""Merge two worlds into one, once, with a preview first.

Twitch commands name the Twitch channel's ID as their world and Discord used DISCORD_WORLD_ID, so a deployment
where the two differ ran two separate games: no shared characters, and !link codes made on Twitch could never be
claimed on Discord. This folds the source world (the old DISCORD_WORLD_ID, which holds the shared colony state)
into the target world (the Twitch channel ID) and then makes the target the main world:

  citizens        every source citizen moves over; one with a character in both worlds is merged into one with
                  the same code as /link (stats, items, skills, home, business, queues, Seedling life combined)
  colony          the source keeps its clock, event, project, story, votes, seasons and challenges; the society
                  stats and settlement stockpiles of both worlds are added together (as the overlay showed them)
  project help    Twitch citizens' unpaid help on their own world's project counts toward the main project
  history         logs, highlights, journals and event history from both worlds are kept

Everything runs in one transaction under the game lock. The preview runs the whole merge and rolls it back.
Afterwards the game uses the target as its main world at once, and remembers that across restarts (world_aliases_v1),
even before DISCORD_WORLD_ID is changed on Railway.
"""
import json
import os
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint, case, select, text, and_, or_, func
from .db import Base
from . import runtime
from .db import SessionLocal
from .models import Identity
from .models import Player
from .models import Society
from .models import World

WORLD_COLUMNS = ('channel_id', 'world')
UID_COLUMNS = ('canonical_uid', 'twitch_uid', 'uid_a', 'uid_b')            # citizen ids (renamed when merging citizens)
PERSON_COLUMNS = UID_COLUMNS + ('provider_uid', 'discord_uid', 'recipient')  # anything that identifies a person
# On a key collision these counters are added together instead of one row simply winning.
SUMS = {
    'societies': ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation', 'population'),
    'settlement_state_v7': ('water', 'ore', 'rare_ore', 'components', 'medicines', 'cargo', 'infrastructure', 'housing'),
    'community_meals_v54': ('contributions',),
    'colony_project_help_v1': ('amount',),
    'season_scores_v1': ('points', 'contribution', 'xp', 'events', 'votes', 'trophies'),
    'week_scores_v1': ('points', 'contribution', 'xp', 'items', 'actions', 'events', 'votes'),
    'hobby_progress_v55': ('points',), 'duck_bonds_v55': ('xp',), 'gear_familiarity_v600': ('uses',), 'find_unanswered_v1': ('times',),
    'collection_v54': ('qty',), 'collection_progress_v1': ('qty',), 'relationship_memories_v600': ('interactions',),
    'account_name_history_v541': ('seen_count',), 'extra_items_v4': ('qty',),
}
# World-wide rows with no natural key: two sets of them would both look current, so the target must not have any.
NO_DUPLICATES = ('seasons_v1', 'live_challenges_v1')


class WorldAlias(Base):
    __tablename__ = 'world_aliases_v1'
    source = Column(String(64), primary_key=True)
    target = Column(String(64), nullable=False)
    merged_at = Column(DateTime(timezone=True), nullable=False)
    summary = Column(Text, nullable=False, default='')


class _Preview(Exception):
    def __init__(self, report):
        self.report = report


def world_tables():
    return [t for t in Base.metadata.sorted_tables if any(c in t.c for c in WORLD_COLUMNS)]


def natural_keys(table):
    """Column sets that must stay unique and include a world column (the surrogate id is not one)."""
    keys = []
    pk = tuple(c.name for c in table.primary_key.columns)
    if pk and pk != ('id',):
        keys.append(pk)
    for con in table.constraints:
        if isinstance(con, UniqueConstraint) and con.columns:
            keys.append(tuple(c.name for c in con.columns))
    keys += [tuple(c.name for c in i.columns) for i in table.indexes if i.unique]
    keys += [(c.name,) for c in table.columns if c.unique]
    found = []
    for key in keys:
        if any(c in WORLD_COLUMNS for c in key) and key not in found:
            found.append(key)
    return found


def owner_column(table):
    """The column that says which world a citizen row belongs to."""
    return 'channel_id' if 'channel_id' in table.c else 'world'


def _pk(table, row):
    return {c.name: row[c.name] for c in table.primary_key.columns}


def _where(table, values):
    return and_(*[table.c[k] == v for k, v in values.items()])


def _moved(row, source, target):
    return {k: (target if k in WORLD_COLUMNS and v == source else v) for k, v in row.items()}


def _belongs(table, source):
    return or_(*[table.c[c] == source for c in WORLD_COLUMNS if c in table.c])


def _absorb(db, table, winner, loser, note):
    """Add the loser's counters into the winner, then delete the loser."""
    sums = {c: winner[c] + loser[c] for c in SUMS.get(table.name, ()) if c in table.c
            and isinstance(winner[c], int) and isinstance(loser[c], int)}
    if sums:
        db.execute(table.update().where(_where(table, _pk(table, winner))).values(**sums))
    db.execute(table.delete().where(_where(table, _pk(table, loser))))
    note[table.name] = note.get(table.name, 0) + 1


def blockers(db, source, target):
    found = []
    if not source or not target or source == target:
        found.append('Choose two different worlds: source (the old Discord world) and target (the Twitch channel ID).')
        return found
    if len(target) > 64:
        found.append('The target world name is longer than 64 characters.')
    if db.get(WorldAlias, source) is not None:
        found.append(f'World {source} was already merged.')
    if db.execute(select(Society.id).where(Society.channel_id == source)).first() is None:
        found.append(f'World {source} does not exist, so there is nothing to merge.')
    for name in NO_DUPLICATES:
        table = Base.metadata.tables.get(name)
        if table is None:
            continue
        mine = db.execute(select(func.count()).select_from(table).where(table.c.world == source)).scalar()
        theirs = db.execute(select(func.count()).select_from(table).where(table.c.world == target)).scalar()
        if mine and theirs:
            found.append(f'Both worlds have rows in {name} (seasons or stream challenges). That usually means DISCORD_WORLD_ID was '
                         'changed before merging; it needs a manual look before anything is merged.')
    return found


def citizen_pairs(db, source, target):
    """(source uid, target uid) for every person with a character in both worlds."""
    pairs = {}
    here = set(db.execute(select(Player.twitch_uid).where(Player.channel_id == source)).scalars())
    there = set(db.execute(select(Player.twitch_uid).where(Player.channel_id == target)).scalars())
    for uid in here & there:
        pairs[uid] = uid
    # The same Twitch or Discord account mapped to two different characters (a link made while the worlds were one).
    ids = {}
    for row in db.execute(select(Identity).where(Identity.channel_id.in_((source, target)))).scalars():
        ids.setdefault((row.provider, row.provider_uid), {})[row.channel_id] = row.canonical_uid
    problems = []
    for (provider, uid), worlds in ids.items():
        mine, theirs = worlds.get(source), worlds.get(target)
        if mine and theirs and mine != theirs and mine in here and theirs in there:
            if pairs.get(mine, theirs) != theirs:
                problems.append(f'{provider} account {uid} maps to more than one character')
            pairs[mine] = theirs
    return pairs, problems


def names(db, channel, uids):
    rows = db.execute(select(Player.twitch_uid, Player.display_name).where(Player.channel_id == channel,
                                                                               Player.twitch_uid.in_(list(uids) or ['']))).all()
    return {u: n for u, n in rows}


def rename_citizen(db, source, old, new):
    """Give a source-world citizen a temporary id so it can move next to its target-world character."""
    for table in world_tables():
        owner = owner_column(table)
        for col in UID_COLUMNS:
            if col in table.c:
                db.execute(table.update().where(and_(table.c[owner] == source, table.c[col] == old)).values(**{col: new}))


def carry_project_help(db, source, target):
    """Unpaid help on the target world's own project (which is replaced by the main project) moves to the main project's run."""
    from .votes import ColonyPlan, ProjectHelp
    main = db.get(ColonyPlan, source)
    if main is None:
        return 0
    table = ProjectHelp.__table__
    moved = 0
    for row in db.execute(select(table).where(table.c.world == target, table.c.finished == 0, table.c.run != main.run)).mappings().all():
        key = {'world': target, 'run': main.run, 'channel_id': row['channel_id'], 'canonical_uid': row['canonical_uid']}
        existing = db.execute(select(table).where(_where(table, key))).mappings().first()
        if existing:
            db.execute(table.update().where(_where(table, key)).values(amount=existing['amount'] + row['amount']))
            db.execute(table.delete().where(_where(table, _pk(table, row))))
        else:
            db.execute(table.update().where(_where(table, _pk(table, row))).values(run=main.run))
        moved += 1
    return moved


def resolve_collisions(db, source, target, kept_main, kept_target):
    """Before relabelling: a source row whose key would equal a target row's. World rows (no person in the key): the
    source (main world) row wins and target counters are added in. Person rows: the target row wins."""
    for table in world_tables():
        keys = natural_keys(table)
        if not keys:
            continue
        rows = db.execute(select(table).where(or_(*[table.c[c].in_((source, target)) for c in WORLD_COLUMNS if c in table.c]))).mappings().all()
        mine = [dict(r) for r in rows if any(r.get(c) == source for c in WORLD_COLUMNS if c in table.c)]
        theirs = [dict(r) for r in rows if not any(r.get(c) == source for c in WORLD_COLUMNS if c in table.c)]
        gone = set()
        for key in keys:
            index = {tuple(r[c] for c in key): r for r in theirs}
            world_level = not any(c in PERSON_COLUMNS for c in key)
            for r in mine:
                other = index.get(tuple(_moved(r, source, target)[c] for c in key))
                if other is None:
                    continue
                ids = (tuple(_pk(table, r).values()), tuple(_pk(table, other).values()))
                if ids[0] in gone or ids[1] in gone:
                    continue
                if world_level:
                    _absorb(db, table, r, other, kept_main)
                    gone.add(ids[1])
                else:
                    _absorb(db, table, other, r, kept_target)
                    gone.add(ids[0])


def relabel(db, source, target):
    moved = {}
    for table in world_tables():
        cols = [c for c in WORLD_COLUMNS if c in table.c]
        values = {c: case((table.c[c] == source, target), else_=table.c[c]) for c in cols}
        count = db.execute(table.update().where(_belongs(table, source)).values(**values)).rowcount or 0
        if count:
            moved[table.name] = count
    return moved


def adopt_leftovers(db, target, old, new, note):
    """After the /link merge, rows it does not know about still carry the old id: move them, or add them into a twin."""
    for table in world_tables():
        owner = owner_column(table)
        for col in [c for c in UID_COLUMNS if c in table.c]:
            rows = db.execute(select(table).where(and_(table.c[owner] == target, table.c[col] == old))).mappings().all()
            keys = [k for k in natural_keys(table) if col in k]
            for row in rows:
                row = dict(row)
                wanted = dict(row, **{col: new})
                twin = None
                for key in keys:
                    twin = db.execute(select(table).where(_where(table, {c: wanted[c] for c in key}))).mappings().first()
                    if twin is not None:
                        break
                if twin is not None:
                    _absorb(db, table, dict(twin), row, note)
                else:
                    db.execute(table.update().where(_where(table, _pk(table, row))).values(**{col: new}))


def counts(db, channel):
    return {'citizens': db.execute(select(func.count()).select_from(Player).where(Player.channel_id == channel)).scalar()}


def run(m, source, target, apply=False):
    """The merge, inside the game lock. Without apply it runs everything and rolls it back, returning the report."""
    from . import task_queue
    source, target = str(source or '').strip(), str(target or '').strip()
    previous = runtime.DISCORD_WORLD_ID
    try:
        with task_queue.atomic(target) as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text('SET LOCAL statement_timeout = 0'))      # large worlds: relabelling the action log
            with SessionLocal() as db:
                problems = blockers(db, source, target)
                pairs, pair_problems = citizen_pairs(db, source, target) if not problems else ({}, [])
                problems += [f'Citizens: {p}. This needs a manual look.' for p in pair_problems]
                report = {'source': source, 'target': target, 'blocked': problems}
                if problems:
                    raise _Preview(report)
                before = {'source': counts(db, source), 'target': counts(db, target)}
                both = [{'source_uid': s, 'target_uid': t, 'source_name': names(db, source, [s]).get(s),
                         'target_name': names(db, target, [t]).get(t)} for s, t in sorted(pairs.items())]
                w_source = db.execute(select(World).where(World.channel_id == source)).scalar_one_or_none()
                w_target = db.execute(select(World).where(World.channel_id == target)).scalar_one_or_none()
                ended = w_target.active_event if w_target is not None and w_target.active_event else ''
                db.flush()
                temporary = {}
                for s, t in pairs.items():
                    if s == t:
                        temporary[s] = ('merged:' + s)[:96]
                        rename_citizen(db, source, s, temporary[s])
                help_moved = carry_project_help(db, source, target)
                kept_main, kept_target = {}, {}
                resolve_collisions(db, source, target, kept_main, kept_target)
                moved = relabel(db, source, target)
                db.expire_all()
                leftovers = {}
                for s, t in pairs.items():
                    old = temporary.get(s, s)
                    runtime.merge_accounts(db, target, old, t)
                    db.flush()
                    db.expire_all()
                    adopt_leftovers(db, target, old, t, leftovers)
                after = counts(db, target)
                report.update({
                    'before': before,
                    'after': {'citizens': after['citizens'], 'main_world': target},
                    'citizens_in_both_worlds': both,
                    'rows_moved': moved,
                    'combined_world_rows': kept_main,
                    'replaced_duplicate_rows': kept_target,
                    'rows_added_into_merged_citizens': leftovers,
                    'project_help_moved_to_main_project': help_moved,
                    'notes': [n for n in (
                        f'The source world {source} keeps its clock, current event, project, story, votes, seasons and stream challenge.',
                        'Society stats and settlement stockpiles of both worlds are added together.',
                        f"The target world's own event ({ended}) ends without results." if ended else '',
                        "Today's market demand, weather and daily directive are re-rolled, because they are picked from the world's name.",
                        f'Afterwards the game uses {target} as its main world straight away; set DISCORD_WORLD_ID={target} on Railway too.',
                    ) if n],
                })
                if not apply:
                    raise _Preview(report)
                from datetime import datetime, timezone
                db.add(WorldAlias(source=source, target=target, merged_at=datetime.now(timezone.utc),
                                  summary=json.dumps({k: report[k] for k in ('before', 'after', 'rows_moved')})[:8000]))
                db.flush()
                if previous == source:
                    switch(m, target)
                db.commit()
        settle(source, target)
        report['merged'] = True
        return report
    except _Preview as preview:
        if runtime.DISCORD_WORLD_ID != previous:
            switch(m, previous)
        preview.report['merged'] = False
        return preview.report
    except Exception:
        if runtime.DISCORD_WORLD_ID != previous:
            switch(m, previous)
        raise


def switch(m, world):
    """Make `world` the main world in this process (the lock key does not depend on it)."""
    m.DISCORD_WORLD_ID = world
    os.environ['DISCORD_WORLD_ID'] = world


def settle(source, target):
    """Forget what this process cached about the merged-away world."""
    from .game.overlay_state import _overlay_cache
    from .game.players import _demand_day
    from . import world_guard
    world_guard._known.discard(source)
    world_guard._known.add(target)
    _overlay_cache.clear()
    _demand_day[0] = 0.0
    for note in [w for w in runtime.RUNTIME_WARNINGS if 'separate worlds' in w or 'different world' in w or 'share one world' in w]:
        runtime.RUNTIME_WARNINGS.discard(note)
    if os.getenv('DISCORD_WORLD_ID_ON_START', source) != target:
        runtime.RUNTIME_WARNINGS.add(f'World {source} was merged into {target}, and the game now uses {target}. Set DISCORD_WORLD_ID={target} '
                               'on Railway so the setting matches (the game keeps using it either way).')


def apply_alias(m):
    """At startup: if DISCORD_WORLD_ID names a world that was merged away, use the world it was merged into."""
    try:
        with SessionLocal() as db:
            alias = db.get(WorldAlias, runtime.DISCORD_WORLD_ID)
    except Exception:
        return
    if alias is not None and alias.target != runtime.DISCORD_WORLD_ID:
        old = runtime.DISCORD_WORLD_ID
        switch(m, alias.target)
        runtime.RUNTIME_WARNINGS.add(f'DISCORD_WORLD_ID on Railway is still {old}, which was merged into {alias.target}. The game uses '
                               f'{alias.target}; set DISCORD_WORLD_ID={alias.target} on Railway so the setting matches.')


def install(m):
    from .game.base import app, valid_admin_key
    from .game.cooldowns_materials import audit_moderator
    from fastapi.responses import JSONResponse
    WorldAlias.__table__.create(runtime.engine, checkfirst=True)
    apply_alias(m)

    @app.get('/api/v1/admin/world-merge')
    def world_merge(source: str = '', target: str = '', key: str = '', confirm: int = 0):
        """Preview (and with confirm=1, run) merging world `source` into world `target`. Needs ADMIN_KEY."""
        if not valid_admin_key(key):
            return JSONResponse({'ok': False, 'error': 'Invalid game-admin key.'}, status_code=403)
        report = run(m, source, target, apply=bool(confirm))
        if report.get('merged'):
            with SessionLocal() as db:
                audit_moderator(db, target, 'game admin', 'world-merge', f'{source} into {target}')
        elif not report.get('blocked'):
            report['apply'] = 'Nothing has changed yet. Repeat this address with &confirm=1 to merge.'
        return JSONResponse({'ok': not report.get('blocked'), **report}, status_code=200 if not report.get('blocked') else 409)
