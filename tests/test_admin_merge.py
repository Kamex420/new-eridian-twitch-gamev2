"""Duplicate characters (a Twitch and a Discord 'Deschroyer' never linked) merge without losing or double-counting anything."""
from test_colony import m, reset, client
from app import seed_content as s

C = 'new-eridian'
LUMBER = s.key('Lumber')


def make_duplicates():
    with m.SessionLocal() as db:
        tw = m.player(db, C, 'twitch', 'tw-555', 'Deschroyer')[1]
        tw.sc, tw.contribution, tw.actions, tw.mining_xp = 300, 40, 25, 70
        m.material_change(db, tw, LUMBER, 12)
        dc = m.player(db, C, 'discord', '9001', 'deschroyer')[1]
        dc.sc, dc.contribution, dc.actions, dc.mining_xp = 120, 15, 9, 30
        m.material_change(db, dc, LUMBER, 5)
        db.commit()
        soc = m.society(db, C)
        return tw.twitch_uid, dc.twitch_uid, soc.population, {f: getattr(soc, f) for f in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation')}


def test_duplicates_are_found_and_merged_without_losing_stats(monkeypatch):
    monkeypatch.setattr(m, 'ADMIN_KEY', 'test-admin')
    keep, merge, population, society_before = make_duplicates()
    assert client.get('/api/v1/admin/duplicates', params={'channel': C, 'key': 'wrong'}).status_code == 403
    found = client.get('/api/v1/admin/duplicates', params={'channel': C, 'key': 'test-admin'}).json()['duplicates']
    group = next(g for g in found if g['name'].lower() == 'deschroyer')
    assert {c['uid'] for c in group['characters']} == {keep, merge}
    preview = client.get('/api/v1/admin/merge', params={'channel': C, 'key': 'test-admin', 'keep': keep, 'merge': merge}).json()
    assert preview['preview'] and preview['after']['sc'] == 420
    with m.SessionLocal() as db:                           # a preview changes nothing
        assert db.query(m.Player).filter_by(channel_id=C, twitch_uid=merge).one_or_none() is not None
    done = client.get('/api/v1/admin/merge', params={'channel': C, 'key': 'test-admin', 'keep': keep, 'merge': merge, 'confirm': 1}).json()
    assert done['merged'] and done['character']['sc'] == 420 and done['character']['actions'] == 34 and done['character']['contribution'] == 55
    with m.SessionLocal() as db:
        players = db.query(m.Player).filter_by(channel_id=C).all()
        assert [p.twitch_uid for p in players if p.display_name.lower() == 'deschroyer'] == [keep]
        p = players[[x.twitch_uid for x in players].index(keep)]
        assert p.mining_xp == 100 and m.material_amount(db, p, LUMBER) == 17
        soc = m.society(db, C)
        assert soc.population == population - 1
        assert {f: getattr(soc, f) for f in society_before} == society_before           # colony stats untouched
        assert db.query(m.AccountLink).filter_by(channel_id=C, twitch_uid=keep, discord_uid='9001').one()
        # Later commands from either account reach the one merged character; no new duplicate appears.
        assert m.player(db, C, 'discord', '9001', 'deschroyer')[1].twitch_uid == keep
        assert m.player(db, C, 'twitch', 'tw-555', 'Deschroyer')[1].twitch_uid == keep
        assert db.query(m.Player).filter_by(channel_id=C).count() == len(players)
