"""A Discord world and a Twitch world, as a deployment with DISCORD_WORLD_ID != the Twitch channel ID has them.

Used by tests/test_world_merge.py (SQLite) and tests/test_postgres.py (PostgreSQL), so it only needs the app module
and a test client. S is the old Discord world (the main one), T the Twitch channel's world.
"""
from sqlalchemy import select, func, inspect

KEY = 'game-key'
SC = {('S', 'discord:d1'): 100, ('S', 'discord:d2'): 50, ('S', 'discord:d3'): 30, ('S', 'dup'): 20,
      ('T', 't1'): 40, ('T', 't2'): 60, ('T', 't3'): 70, ('T', 'dup'): 25}


def start(client, channel, uid, name, provider):
    return client.get('/api/v1/start', params={'channel': channel, 'uid': uid, 'name': name, 'provider': provider, 'k': KEY}).text


def build(m, client, S, T):
    from app import votes, seasons, task_queue
    lumber = m.seed_content.find_item('lumber')
    for uid, name in (('d1', 'Ann'), ('d2', 'Bo'), ('d3', 'Cass')):
        start(client, S, uid, name, 'discord')
    start(client, S, 'dup', 'Dupe', 'twitch')          # a Twitch account that also got a character in the Discord world
    for uid, name in (('t1', 'Cy'), ('t2', 'Di'), ('t3', 'Cass'), ('dup', 'Dupe')):
        start(client, T, uid, name, 'twitch')
    world = {'S': S, 'T': T}
    with m.SessionLocal() as db:
        for (w, uid), sc in SC.items():
            p = db.execute(select(m.Player).where(m.Player.channel_id == world[w], m.Player.twitch_uid == uid)).scalar_one()
            p.sc = sc
        db.commit()
        for channel, uid, qty in ((S, 'dup', 5), (T, 'dup', 3), (S, 'discord:d1', 9)):   # exact stock (!start gives a welcome kit)
            m.item_add(db, channel, uid, lumber, qty - m.item(db, channel, uid, lumber))
        # Cass's Discord account was linked to her Twitch character back when the worlds were one.
        db.add(m.Identity(channel_id=T, provider='discord', provider_uid='d3', canonical_uid='t3'))
        db.add(m.AccountLink(channel_id=T, twitch_uid='t3', discord_uid='d3'))
        s_soc, t_soc = m.society(db, S), m.society(db, T)
        s_soc.food, s_soc.knowledge, t_soc.food, t_soc.knowledge = 10, 4, 5, 2
        m.colony_state(db, S).water, m.colony_state(db, T).water = 7, 3
        m.world(db, S)
        m.start_event(db, m.world(db, T), 'siro')     # only the Twitch world has an event running
        ballot = votes.ballot(db)
        for channel, uid, choice in ((S, 'discord:d1', 1), (T, 't1', 2), (S, 'dup', 1), (T, 'dup', 2)):
            db.add(votes.Cast(world=S, day=ballot.day, channel_id=channel, canonical_uid=uid, choice=choice, created_at=m.now()))
        season = seasons.current(db)
        for channel, uid, points in ((S, 'discord:d1', 10), (T, 't1', 5), (S, 'dup', 7), (T, 'dup', 4)):
            db.add(seasons.SeasonScore(season_id=season.id, channel_id=channel, canonical_uid=uid, points=points, contribution=0, xp=0,
                                       events=0, votes=0, trophies=0, tier=0, updated_at=m.now()))
        votes.plan(db, S).run, votes.plan(db, T).run = 3, 1
        db.add(votes.ProjectHelp(world=T, run=1, channel_id=T, canonical_uid='t1', project='x', amount=4, finished=0))
        db.add(votes.ProjectHelp(world=S, run=3, channel_id=S, canonical_uid='discord:d2', project='y', amount=2, finished=0))
        db.add(task_queue.TaskQueue(channel_id=S, canonical_uid='discord:d1', task='gather:' + lumber, total=3, remaining=2,
                                    state='paused', result='', next_at=m.now()))
        db.commit()


def world_rows(m, value):
    """How many rows in every world table name `value` in a world column."""
    from app.world_merge import world_tables, _belongs
    with m.SessionLocal() as db:
        return {t.name: n for t in world_tables() for n in [db.execute(select(func.count()).select_from(t).where(_belongs(t, value))).scalar()] if n}


def snapshot(m, S, T):
    return world_rows(m, S), world_rows(m, T)


def verify(m, client, S, T):
    """Everything a merge must have done. Returns nothing; asserts."""
    from app import votes, seasons, task_queue
    from app.world_merge import WorldAlias
    lumber = m.seed_content.find_item('lumber')
    assert world_rows(m, S) == {}, world_rows(m, S)                       # nothing is left in the old world
    assert m.DISCORD_WORLD_ID == T
    with m.SessionLocal() as db:
        players = {p.twitch_uid: p for p in db.execute(select(m.Player).where(m.Player.channel_id == T)).scalars()}
        assert set(players) == {'discord:d1', 'discord:d2', 't1', 't2', 't3', 'dup'}, set(players)
        assert players['dup'].sc == 45 and players['t3'].sc == 100 and players['discord:d1'].sc == 100
        assert m.item(db, T, 'dup', lumber) == 8 and m.item(db, T, 'discord:d1', lumber) == 9
        soc = db.execute(select(m.Society).where(m.Society.channel_id == T)).scalars().all()
        assert len(soc) == 1 and soc[0].food == 15 and soc[0].knowledge == 6 and soc[0].population == 6
        assert m.colony_state(db, T).water == 10
        assert m.world(db, T).active_event is None                       # the main world's state, not the Twitch world's event
        help = {r.canonical_uid: r for r in db.execute(select(votes.ProjectHelp).where(votes.ProjectHelp.world == T)).scalars()}
        assert help['t1'].run == 3 and help['t1'].amount == 4 and help['discord:d2'].run == 3
        assert votes.plan(db, T).run == 3
        scores = {r.canonical_uid: r.points for r in db.execute(select(seasons.SeasonScore)).scalars()}
        assert scores == {'discord:d1': 10, 't1': 5, 'dup': 11}, scores
        cast = db.execute(select(votes.Cast)).scalars().all()
        assert sorted((c.channel_id, c.canonical_uid) for c in cast) == [(T, 'discord:d1'), (T, 'dup'), (T, 't1')]
        assert all(c.world == T for c in cast)
        assert db.get(task_queue.TaskQueue, (T, 'discord:d1')).remaining == 2
        assert db.get(WorldAlias, S).target == T
        assert not any(i['name'] is None for i in inspect(m.engine).get_indexes('action_logs_v5'))
        # Discord players find their own characters, and Cass's Discord account plays her Twitch character.
        _, ann = m.player(db, m.DISCORD_WORLD_ID, 'discord', 'd1', 'Ann')
        canon, cass = m.player(db, m.DISCORD_WORLD_ID, 'discord', 'd3', 'Cass')
        assert ann.sc == 100 and canon == 't3' and cass.sc == 100
        db.commit()
    # !link works now: a code made on Twitch is claimed on Discord.
    code = client.get('/api/v1/link/create', params={'channel': T, 'uid': 't9', 'name': 'Nine', 'k': KEY}).text.split('Link code ')[1].split('.')[0]
    assert '✅' in m._discord_call_internal('link', 'd9', 'Nine', {'code': code}, 'merge-link-1')
