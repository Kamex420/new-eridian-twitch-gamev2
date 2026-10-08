"""Merging the old Discord world into the Twitch channel's world (tests/world_merge_scenario.py builds both)."""
import pytest
from test_colony import m, reset, client
from world_merge_scenario import build, verify, snapshot, KEY
from app import world_merge

T = '27074041'


@pytest.fixture(autouse=True)
def setup(reset, monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_WORLD_ID', m.DISCORD_WORLD_ID)          # restored after each test
    monkeypatch.setenv('DISCORD_WORLD_ID', m.DISCORD_WORLD_ID)
    monkeypatch.setenv('DISCORD_WORLD_ID_ON_START', m.DISCORD_WORLD_ID)
    monkeypatch.setattr(m, 'ADMIN_KEY', 'admin-secret')
    monkeypatch.setattr(m, 'RUNTIME_WARNINGS', set())
    monkeypatch.setenv('TWITCH_API_KEY', KEY)


def merge(**params):
    return client.get('/api/v1/admin/world-merge', params={'key': 'admin-secret', **params})


def test_the_merge_needs_the_admin_key():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    assert merge(source=S, target=T, key='wrong').status_code == 403
    assert merge(source=S, target=T, key='wrong', confirm=1).status_code == 403
    assert m.DISCORD_WORLD_ID == S


def test_the_preview_reports_everything_and_changes_nothing():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    before = snapshot(m, S, T)
    report = merge(source=S, target=T).json()
    assert report['ok'] and report['merged'] is False and 'confirm=1' in report['apply']
    assert report['before'] == {'source': {'citizens': 4}, 'target': {'citizens': 4}}
    assert report['after']['citizens'] == 6
    assert sorted((c['source_uid'], c['target_uid']) for c in report['citizens_in_both_worlds']) == [('discord:d3', 't3'), ('dup', 'dup')]
    assert report['combined_world_rows']['societies'] == 1 and report['combined_world_rows']['settlement_state_v7'] == 1
    assert report['project_help_moved_to_main_project'] == 1
    assert any('siro' in n for n in report['notes'])                       # the Twitch world's event ends
    assert snapshot(m, S, T) == before                                       # nothing changed
    assert m.DISCORD_WORLD_ID == S


def test_the_merge_moves_everyone_into_one_world():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    report = merge(source=S, target=T, confirm=1).json()
    assert report['ok'] and report['merged'] is True
    verify(m, client, S, T)
    # /health reminds the streamer to make the Railway setting match.
    assert any(f'DISCORD_WORLD_ID={T}' in w for w in m.config_warnings())
    with m.SessionLocal() as db:
        assert db.query(m.ModeratorAudit).filter_by(action='world-merge').count() == 1


def test_a_second_merge_is_refused():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    assert merge(source=S, target=T, confirm=1).json()['merged']
    again = merge(source=S, target=T, confirm=1)
    assert again.status_code == 409 and any('already merged' in b for b in again.json()['blocked'])


def test_after_a_restart_the_old_setting_still_means_the_merged_world():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    merge(source=S, target=T, confirm=1)
    m.DISCORD_WORLD_ID = S                                                    # Railway still says the old world
    m.RUNTIME_WARNINGS.clear()
    world_merge.apply_alias(m)
    assert m.DISCORD_WORLD_ID == T
    assert any(f'DISCORD_WORLD_ID={T}' in w for w in m.config_warnings())
    with m.SessionLocal() as db:
        _, ann = m.player(db, m.DISCORD_WORLD_ID, 'discord', 'd1', 'Ann')
        assert ann.sc == 100
        db.commit()


@pytest.mark.parametrize('source,target,why', [('', T, 'two different'), ('same', 'same', 'two different'),
                                               ('nowhere', T, 'does not exist')])
def test_impossible_merges_are_refused(source, target, why):
    response = merge(source=source, target=target, confirm=1)
    assert response.status_code == 409 and any(why in b for b in response.json()['blocked'])


def test_a_target_with_its_own_season_needs_a_manual_look():
    from app import seasons
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    with m.SessionLocal() as db:
        seasons.current(db, world=T); db.commit()
    before = snapshot(m, S, T)
    response = merge(source=S, target=T, confirm=1)
    assert response.status_code == 409 and any('manual look' in b for b in response.json()['blocked'])
    assert snapshot(m, S, T) == before


def test_a_failed_merge_changes_nothing(monkeypatch):
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    before = snapshot(m, S, T)

    def broken(*args, **kwargs):
        raise RuntimeError('database went away')
    monkeypatch.setattr(m, 'merge_accounts', broken)
    with pytest.raises(RuntimeError):
        world_merge.run(m, S, T, apply=True)
    assert snapshot(m, S, T) == before and m.DISCORD_WORLD_ID == S


def test_play_carries_on_in_the_merged_world():
    S = m.DISCORD_WORLD_ID
    build(m, client, S, T)
    merge(source=S, target=T, confirm=1)
    with m.SessionLocal() as db:
        db.query(m.Cooldown).delete(); db.commit()
        actions = db.query(m.Player).filter_by(channel_id=T, twitch_uid='discord:d1').one().actions
    # Discord and Twitch commands, the overlay and the society view all use the one world.
    reply = m._discord_call_internal('gather', 'd1', 'Ann', {'resource': 'lumber'}, 'merge-play-1')
    assert reply and 'could not be completed' not in reply
    with m.SessionLocal() as db:
        assert db.query(m.Player).filter_by(channel_id=T, twitch_uid='discord:d1').one().actions == actions + 1   # Ann's own character acted
    assert client.get('/api/v1/status', params={'channel': T, 'uid': 't1', 'name': 'Cy', 'k': KEY}).status_code == 200
    assert client.get('/api/v1/overlay', params={'channel': S}).json()['ok']          # old overlay links still show the world
    assert 'has not started' in client.get('/api/v1/society', params={'channel': S}).text   # and nothing recreates the old one
    with m.SessionLocal() as db:
        assert db.query(m.Society).filter_by(channel_id=S).count() == 0
        assert db.query(m.Player).filter_by(channel_id=S).count() == 0
