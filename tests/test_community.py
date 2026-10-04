"""Colony votes, stream challenges, seasons, trophies and the weekly recap."""
import json
from datetime import timedelta
import pytest
from test_colony import m, reset, client
from app import votes, live_events as le, seasons, trophies, recap, community, seed_content as s

W = m.DISCORD_WORLD_ID


@pytest.fixture(autouse=True)
def enabled(reset, monkeypatch):
    monkeypatch.setattr(community, 'ENABLED', True)
    monkeypatch.setattr(m, 'ADMIN_KEY', 'test-admin-key')
    le._chatters.clear()
    trophies._last.clear()


def call(path, uid='u1', name='Nova', provider='twitch', **params):
    return client.get(path, params={'channel': W, 'uid': uid, 'name': name, 'provider': provider, **params}).text


def player(uid='u1', provider='twitch'):
    db = m.SessionLocal()
    canon = m.resolve(db, W, provider, uid)
    return db, db.query(m.Player).filter_by(channel_id=W, twitch_uid=canon).one()


def ready():
    with m.SessionLocal() as db:
        db.query(m.Cooldown).delete(); db.commit()


def next_day():
    with m.SessionLocal() as db:
        clock = db.query(m.WorldClock).filter_by(channel_id=W).one()
        clock.anchor_at = m.as_utc(clock.anchor_at) - timedelta(seconds=m.AVESTA_DAY_SECONDS)
        db.commit()


def highlights(kind):
    with m.SessionLocal() as db:
        return [h.title for h in db.query(m.stream_overlay.StreamHighlight).filter_by(kind=kind)]


# ---------------------------------------------------------------- colony votes

def test_ballot_has_two_projects_and_a_festival_and_the_first_vote_pays_once():
    call('/api/v1/start')
    text = call('/api/v1/vote')
    assert text.startswith('🗳️ Day 1 vote: 1)') and '!vote 1-3' in text and len(text.encode()) <= 200
    with m.SessionLocal() as db:
        options = json.loads(votes.ballot(m, db).options)
    assert sorted(o.split(':')[0] for o in options) == ['festival', 'project', 'project']
    db, p = player(); sc = p.sc; db.close()
    first = call('/api/v1/vote', choice='2')
    assert 'Voted' in first and f'+{votes.VOTE_SC} SC' in first
    again = call('/api/v1/vote', choice='3')
    assert 'Changed to' in again and 'SC' not in again.split('|')[0]
    db, p = player()
    assert p.sc == sc + votes.VOTE_SC + trophies.TROPHIES['civic_duty']['sc']          # the Civic Duty trophy came with the first vote
    assert db.query(votes.Cast).one().choice == 3
    db.close()
    discord = call('/api/v1/vote', provider='discord')
    assert 'COLONY VOTE' in discord and '1.' in discord and '3.' in discord


def test_a_voted_project_is_queued_then_built_and_its_helpers_are_credited():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        options = json.loads(votes.ballot(m, db).options)
    pick = next(i for i, o in enumerate(options, 1) if o.startswith('project:'))
    winner = options[pick - 1].split(':')[1]
    call('/api/v1/vote', choice=str(pick))
    call('/api/v1/vote', uid='u2', name='Astra', choice=str(pick))
    next_day()
    with m.SessionLocal() as db:
        votes.sync(m, db); db.commit()
        plan = votes.plan(m, db)
        assert plan.next_project == winner
        current = m.current_project(db, W, m.world_clock(db, W)['day'])
        first_key = current.project_key
        assert first_key != winner                         # the running project finishes first
        skill = sorted(m.project_cfg(first_key)[3])[0]
        p = db.query(m.Player).filter_by(channel_id=W).first()
        current.progress = current.goal - 1; db.commit()
        assert 'Project complete' in m.project_contribute(db, p, skill, 1)
        db.commit()
        now = m.current_project(db, W, m.world_clock(db, W)['day'])
        assert now.project_key == winner and now.progress == 0
        built = json.loads(votes.plan(m, db).built)
        assert built[-1]['key'] == first_key and built[-1]['helpers'] == 1
        assert votes.projects_helped(db, p) == 1
        db.commit()
    assert any('The colony voted' in t for t in highlights('vote'))
    assert any('Construction starts' in t for t in highlights('project'))
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert data['vote']['built'][-1]['key'] == first_key and data['vote']['building']['key'] == winner


def test_a_voted_festival_runs_the_next_day_with_a_bonus():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        options = json.loads(votes.ballot(m, db).options)
    pick = next(i for i, o in enumerate(options, 1) if o.startswith('festival:'))
    key = options[pick - 1].split(':')[1]
    call('/api/v1/vote', choice=str(pick))
    next_day()
    with m.SessionLocal() as db:
        votes.sync(m, db); db.commit()
        assert votes.festival_today(m, db) == key
        skill = sorted(votes.FESTIVALS[key][3])[0]
        p = db.query(m.Player).filter_by(channel_id=W).first()
        bonus, notes = community.success_modifier(m, db, p, skill)
        assert bonus == votes.FESTIVAL_BONUS and votes.FESTIVALS[key][1] in notes[0]
    assert client.get('/api/v1/overlay', params={'channel': W}).json()['vote']['festival']['key'] == key
    next_day()
    with m.SessionLocal() as db:
        assert votes.festival_today(m, db) == ''          # one day only


def test_a_finished_building_pays_every_helper_boosts_the_society_and_gives_a_lasting_perk():
    call('/api/v1/start')
    call('/api/v1/start', uid='u2', name='Astra')
    with m.SessionLocal() as db:
        current = m.current_project(db, W, m.world_clock(db, W)['day'])
        key = current.project_key
        skill = sorted(m.project_cfg(key)[3])[0]
        a, b = db.query(m.Player).filter_by(channel_id=W).order_by(m.Player.id).all()
        before_sc, before_dev = (a.sc, b.sc), m.society(db, W).development
        assert community.success_modifier(m, db, a, skill)[0] == 0
        m.project_contribute(db, b, skill, 2)
        current.progress = current.goal - 1; db.commit()
        assert 'Built! 2 helpers paid' in m.project_contribute(db, a, skill, 1)
        db.commit()
        assert a.sc - before_sc[0] >= votes.HELPER_SC + 1 and b.sc - before_sc[1] >= votes.HELPER_SC + 2   # the finisher also gets the usual reward
        assert m.society(db, W).development == before_dev + votes.BUILT_STATS['development']
        assert votes.projects_helped(db, a) == 1 and votes.projects_helped(db, b) == 1
        assert votes.buildings(m, db, W) == {key: 1}
        bonus, notes = votes.building_bonus(m, db, a, skill)
        assert bonus == votes.PERK and m.project_cfg(key)[1] in notes[0]
        assert community.success_modifier(m, db, a, skill)[0] >= votes.PERK
        # Building it again and again stacks up to the cap; finishing twice never pays twice.
        built = json.loads(votes.plan(m, db).built)
        assert len(built) == 1
        assert votes.complete(m, db, current) == 0
        plan = votes.plan(m, db)
        plan.built = json.dumps(built * 5); db.commit()
        assert votes.building_bonus(m, db, a, skill)[0] == votes.PERK_CAP
    assert any('is built!' in t for t in highlights('project'))
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).first()
        text = votes.view(m, db, p)
        assert 'Built so far' in text and 'How it works' in text


def test_a_festival_gives_everyone_one_gift_and_restarts_an_idle_building_site():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        options = json.loads(votes.ballot(m, db).options)
        current = m.current_project(db, W, m.world_clock(db, W)['day'])
        current.progress = current.goal                       # the site is finished and nothing is queued
        finished = current.project_key
        db.commit()
    pick = next(i for i, o in enumerate(options, 1) if o.startswith('festival:'))
    best = next(i for i, o in enumerate(options, 1) if o.startswith('project:'))
    call('/api/v1/vote', choice=str(pick))
    call('/api/v1/vote', uid='u2', name='Astra', choice=str(best))
    next_day()
    with m.SessionLocal() as db:
        votes.sync(m, db); db.commit()
        fest = votes.festival_today(m, db)
        now = m.current_project(db, W, m.world_clock(db, W)['day'])
        assert now.project_key == options[best - 1].split(':')[1] and now.progress == 0
        assert finished in votes.buildings(m, db, W)
        p = db.query(m.Player).filter_by(channel_id=W, twitch_uid='u1').one()
        sc = p.sc
        gift = votes.festival_gift(m, db, p)
        assert votes.FESTIVALS[fest][1] in gift and p.sc == sc + votes.FESTIVAL_GIFTS[fest][0]
        assert votes.festival_gift(m, db, p) == ''              # once a day
        db.commit()
        assert 'won' in votes.last_result(m, db)
        assert 'Last vote' in votes.view(m, db, p, provider='twitch') or len(votes.view(m, db, p, provider='twitch').encode()) <= 200
    ready()
    reply = call('/api/v1/relax', uid='u2', name='Astra')
    assert 'gift' in reply, reply


def test_nobody_voting_still_picks_and_ties_go_to_the_first_to_the_top():
    call('/api/v1/start')
    call('/api/v1/vote', uid='a', name='A', choice='3')
    call('/api/v1/vote', uid='b', name='B', choice='1')
    next_day()
    with m.SessionLocal() as db:
        winners = votes.sync(m, db)
        options = json.loads(db.get(votes.Ballot, (W, 1)).options)
        assert winners == [options[2]]
        votes.ballot(m, db)                                  # nobody votes on day 2
        db.commit()
    next_day()
    with m.SessionLocal() as db:
        assert len(votes.sync(m, db)) == 1


# ---------------------------------------------------------------- stream challenges

def test_live_only_with_chatters_or_a_moderator():
    with m.SessionLocal() as db:
        assert not le.is_live(m, db)
        le.seen_on_twitch('a'); le.seen_on_twitch('b')
        assert le.is_live(m, db)                              # two people using Twitch commands
        le.set_live(m, db, 'off')
        assert not le.is_live(m, db)
        le._chatters.clear(); le.set_live(m, db, 'on')
        assert le.is_live(m, db)
    denied = client.get('/api/v1/admin/live', params={'state': 'on', 'level': 100, 'key': 'test-admin-key'}).text
    assert 'Only the game owner' in denied
    moderator = client.get('/api/v1/admin/live', params={'state': 'on', 'level': 500, 'key': 'test-admin-key'}).text
    assert 'Only the game owner' in moderator                    # a Twitch moderator is not the channel owner
    ok = client.get('/api/v1/admin/live', params={'state': 'auto', 'level': 1500, 'key': 'test-admin-key'}).text
    assert 'automatic' in ok


def test_a_live_stream_starts_challenges_by_itself(monkeypatch):
    with m.SessionLocal() as db:
        le.set_live(m, db, 'on')
        st = le.state(m, db); st.next_at = m.now() - timedelta(seconds=1)
        le.tick(m, db)
        row = le.active(m, db)
        assert row is not None and row.started_by == 'auto'
        assert m.as_utc(st.next_at) > m.as_utc(row.ends_at)       # the next one waits for a gap after this one
        db.commit()
    assert any(h for h in highlights('challenge_start'))


def gather_lumber(uid, name='Nova', n=1):
    out = []
    for _ in range(n):
        ready()
        out.append(call('/api/v1/seed-supplies', uid=uid, name=name, mode='gather', item='lumber'))
    return out


def test_chat_fills_the_goal_and_everyone_who_helped_is_paid(monkeypatch):
    monkeypatch.setattr(trophies, 'check', lambda *a, **k: [])      # trophy rewards would blur the exact payouts
    call('/api/v1/start', uid='a', name='Ann'); call('/api/v1/start', uid='b', name='Bo')
    started = client.get('/api/v1/admin/challenge', params={'action': 'start', 'event': 'lumber_drive', 'level': 1500, 'key': 'test-admin-key'}).text
    assert 'Lumber Drive' in started and 'Goal' in started
    with m.SessionLocal() as db:
        row = le.active(m, db); row.goal = 3; db.commit()
        db_a, a = player('a'); sc_a, contrib_a = a.sc, a.contribution; lumber_a = m.material_amount(db_a, a, s.key('Lumber')); db_a.close()
        db_b, b = player('b'); sc_b = b.sc; db_b.close()
    first = gather_lumber('a', 'Ann', 2)
    assert '🪵 1/3 (+1)' in first[0] and all(len(x.encode()) <= 200 for x in first)
    last = gather_lumber('b', 'Bo')[0]
    assert 'Lumber Drive WON' in last
    with m.SessionLocal() as db:
        assert db.query(le.Challenge).one().state == 'won'
    db, a = player('a')
    paid = le.WIN_SC + 2 * le.PER_UNIT_SC + le.MVP_SC
    assert a.sc == sc_a + paid and a.contribution >= contrib_a + le.WIN_CONTRIBUTION
    assert m.material_amount(db, a, s.key('Lumber')) == lumber_a + 2 + le.CHALLENGES['lumber_drive'][8]['Lumber']
    assert le.participations(db, a) == 1 and le.wins(db, a) == 1
    db.close()
    db, b = player('b')
    assert b.sc == sc_b + le.WIN_SC + le.PER_UNIT_SC
    db.close()
    assert any('Lumber Drive complete' in t for t in highlights('challenge_win'))
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert data['challenge']['state'] == 'won' and data['challenge']['top'][0]['name'] == 'Ann'


def test_time_running_out_still_thanks_the_helpers_and_seedlings_do_not_count(monkeypatch):
    monkeypatch.setattr(trophies, 'check', lambda *a, **k: [])
    call('/api/v1/start', uid='a', name='Ann')
    client.get('/api/v1/admin/challenge', params={'action': 'start', 'event': 'lumber_drive', 'level': 1500, 'key': 'test-admin-key'})
    token = m.autonomy.ACTING.set(True)
    try:
        gather_lumber('a', 'Ann')
    finally:
        m.autonomy.ACTING.reset(token)
    with m.SessionLocal() as db:
        assert le.active(m, db).progress == 0                  # a Seedling acting alone does not count
    gather_lumber('a', 'Ann')
    db, a = player('a'); sc = a.sc; db.close()
    with m.SessionLocal() as db:
        row = le.active(m, db); row.ends_at = m.now() - timedelta(seconds=1); db.commit()
        le.tick(m, db); db.commit()
        assert db.query(le.Challenge).one().state == 'lost'
    db, a = player('a')
    assert a.sc == sc + le.LOSE_SC
    db.close()
    assert highlights('challenge_fail')


def test_stopping_a_challenge_and_its_status_views():
    call('/api/v1/start')
    assert 'No stream challenge' in call('/api/v1/challenge')
    client.get('/api/v1/admin/challenge', params={'action': 'start', 'event': 'dust_storm', 'level': 1500, 'key': 'test-admin-key'})
    chat = call('/api/v1/challenge')
    assert chat.startswith('🌪️ Dust Storm: 0/') and len(chat.encode()) <= 200
    assert 'STREAM CHALLENGE: DUST STORM' in call('/api/v1/challenge', provider='discord')
    stopped = client.get('/api/v1/admin/challenge', params={'action': 'stop', 'level': 1500, 'key': 'test-admin-key'}).text
    assert 'stopped' in stopped
    with m.SessionLocal() as db:
        assert db.query(le.Challenge).one().state == 'cancelled'


def test_a_skills_challenge_boosts_its_work_while_it_runs():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        le.start(m, db, 'siro_surge', 'test'); db.commit()
        p = db.query(m.Player).filter_by(channel_id=W).first()
        assert community.success_modifier(m, db, p, 'research')[0] == le.BOARD_BONUS
        assert community.success_modifier(m, db, p, 'commerce')[0] == 0


# ---------------------------------------------------------------- seasons

def test_points_come_from_play_and_unlock_rewards_as_they_go():
    call('/api/v1/start')
    gather_lumber('u1')
    with m.SessionLocal() as db:
        season = seasons.current(m, db)
        p = db.query(m.Player).filter_by(channel_id=W).first()
        row = db.get(seasons.SeasonScore, (season.id, p.channel_id, p.twitch_uid))
        assert row.points >= 1
        week = db.get(seasons.WeekScore, (seasons.week_key(), p.channel_id, p.twitch_uid))
        assert week.actions >= 1 and week.items >= 1
        sc = p.sc
        note = seasons.add(m, db, p, seasons.TIERS[2][3])
        assert 'Bronze' in note and 'Silver' in note and 'Gold' in note
        assert p.sc == sc + seasons.GOLD_SC
        titles = {t.title_key for t in db.query(m.PlayerTitle).filter_by(canonical_uid=p.twitch_uid)}
        theme = seasons.THEME[season.theme]
        assert {'season_' + theme[0], 'season_' + theme[0] + '_gold'} <= titles
        assert seasons.hats_of(db, p) == ([theme[4]], theme[4])        # the season hat goes straight on
        db.commit()
    overview = call('/api/v1/seasons')
    assert 'Season 1' in overview and '(#1)' in overview and len(overview.encode()) <= 200
    # Discord views (a Discord account is its own citizen unless linked)
    assert 'LEADERBOARD' in call('/api/v1/seasons', uid='d1', name='Dee', provider='discord', section='top')
    assert 'REWARDS' in call('/api/v1/seasons', uid='d1', name='Dee', provider='discord', section='rewards')
    assert 'Week 1' in call('/api/v1/seasons', uid='d1', name='Dee', provider='discord', section='story')
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert data['season']['top'][0]['name'] == 'Nova'
    assert next(x for x in data['seedlings'] if x['name'] == 'Nova').get('hat') == theme[4]


def test_community_milestones_pay_everyone_who_scored():
    call('/api/v1/start', uid='a', name='Ann'); call('/api/v1/start', uid='b', name='Bo')
    with m.SessionLocal() as db:
        a = db.query(m.Player).filter_by(display_name='Ann').one(); b = db.query(m.Player).filter_by(display_name='Bo').one()
        seasons.add(m, db, b, 1)
        sc_b = b.sc
        seasons.add(m, db, a, seasons.MILESTONES[0][0])
        assert b.sc == sc_b + seasons.MILESTONE_SC
        assert seasons.current(m, db).milestones == 1
        db.commit()
    assert any('Community milestone' in t for t in highlights('season'))
    assert client.get('/api/v1/overlay', params={'channel': W}).json()['season']['decor'] == ['banners']


def test_a_season_ends_with_champions_and_only_points_reset(monkeypatch):
    for uid, name in [('a', 'Ann'), ('b', 'Bo'), ('c', 'Cy'), ('d', 'Di')]:
        call('/api/v1/start', uid=uid, name=name)
    with m.SessionLocal() as db:
        season = seasons.current(m, db)
        people = {p.display_name: p for p in db.query(m.Player).filter_by(channel_id=W)}
        for name, pts in [('Ann', 90), ('Bo', 70), ('Cy', 50), ('Di', 30)]:
            seasons.add(m, db, people[name], pts)
        sc = {n: p.sc for n, p in people.items()}
        items = {n: m.material_amount(db, p, s.key('Lumber')) for n, p in people.items()}
        season.ends_at = m.now() - timedelta(seconds=1)
        db.commit()
    with m.SessionLocal() as db:
        new = seasons.current(m, db)
        db.commit()
        assert new.number == 2 and new.theme == seasons.THEMES[1][0]
        people = {p.display_name: p for p in db.query(m.Player).filter_by(channel_id=W)}
        assert people['Ann'].sc == sc['Ann'] + seasons.CHAMPION_SC[0] and people['Di'].sc == sc['Di']
        assert all(m.material_amount(db, p, s.key('Lumber')) == items[n] for n, p in people.items())
        ranks = {r.canonical_uid: r.rank for r in db.query(seasons.SeasonResult)}
        assert ranks[people['Ann'].twitch_uid] == 1 and ranks[people['Di'].twitch_uid] == 4
        assert seasons.hats_of(db, people['Ann'])[0] == ['crown'] and seasons.hats_of(db, people['Bo'])[0] == ['laurel']
        titles = {(t.canonical_uid, t.title_key) for t in db.query(m.PlayerTitle)}
        assert (people['Ann'].twitch_uid, 'season1_champion') in titles and (people['Cy'].twitch_uid, 'season1_finalist') in titles
        assert seasons.rank_of(db, new, people['Ann'])[0] is None         # a fresh leaderboard
        assert 'S1 #1' in seasons.history_text(m, db, people['Ann'])
    assert any('Season 1 is over' in t for t in highlights('season'))
    assert any('Season 2 begins' in t for t in highlights('season'))


def test_hats_can_be_worn_and_taken_off():
    call('/api/v1/start')
    assert 'No cosmetic hats' in call('/api/v1/hat')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).first()
        seasons.give_hat(db, p, 'party'); seasons.give_hat(db, p, 'crown'); db.commit()
    assert 'Party hat' in call('/api/v1/hat', hat='party')
    assert 'job hat' in call('/api/v1/hat', hat='job')
    assert "don't have" in call('/api/v1/hat', hat='wizard')


# ---------------------------------------------------------------- trophies

def test_finding_every_ore_unlocks_a_trophy_with_a_title_and_an_alert():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).first()
        for k in s.GATHER:
            if m.resource_name(k).endswith(' Ore'):
                m.material_change(db, p, k, 1)
        sc = p.sc
        notes = trophies.check(m, db, p, force=True)
        assert any('Ore Hunter' in n for n in notes)
        assert p.sc >= sc + trophies.TROPHIES['ore_hunter']['sc']
        assert db.query(m.PlayerTitle).filter_by(canonical_uid=p.twitch_uid, title_key='ore_hunter').one()
        assert trophies.check(m, db, p, force=True) == []           # once only
        db.commit()
    assert any('Ore Hunter' in t for t in highlights('trophy'))
    db, p = player()
    assert '✅ 💎 **Ore Hunter**' in trophies.view(m, db, p, 'discord', 'collections')
    db.close()
    assert 'Ore Hunter' in call('/api/v1/badge', badge='ore hunter')
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert next(x for x in data['seedlings'] if x['name'] == 'Nova')['badge'] == '💎'
    assert 'Trophy' not in call('/api/v1/achievements')           # trophies are listed under /trophies, not as achievements


def test_eating_and_finding_are_remembered_from_commands():
    call('/api/v1/start')
    ready()
    call('/api/v1/action/eat', msg='food:' + s.key('Berries'))
    gather_lumber('u1')
    with m.SessionLocal() as db:
        kinds = {(f.kind, f.key) for f in db.query(trophies.Found)}
    assert ('ate', s.key('Berries')) in kinds and ('item', s.key('Lumber')) in kinds


def test_festival_feasts_come_from_the_craft_ledger():
    from app import seasonal
    call('/api/v1/start')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).first()
        for food in seasonal.FESTIVAL_FOODS['Halloween']:
            db.add(m.CraftLedger(channel_id=p.channel_id, canonical_uid=p.twitch_uid, recipe='fr_' + seasonal._slug(food[0]), qty=1, best_quality=''))
        db.flush()
        assert any('Halloween Feast' in n for n in trophies.check(m, db, p, force=True))


def test_trophies_count_votes_challenges_and_show_on_the_profile():
    call('/api/v1/start')
    call('/api/v1/vote', uid='d1', provider='discord', choice='1')
    profile = call('/api/v1/profile', uid='d1', provider='discord')
    assert '🏅 Trophies' in profile and '🗳️' in profile and 'Season 1' in profile
    chat = call('/api/v1/trophies')
    assert chat.startswith('🏅 Nova:') and len(chat.encode()) <= 200


# ---------------------------------------------------------------- weekly recap

def test_the_recap_has_every_section_and_posts_once_a_week(monkeypatch):
    call('/api/v1/start', uid='a', name='Ann')
    gather_lumber('a', 'Ann', 2)
    call('/api/v1/vote', uid='a', name='Ann', choice='1')
    with m.SessionLocal() as db:
        title, sections, plain = recap.build(m, db)
    names = [h for h, _ in sections]
    assert title.startswith('📰 New Eridian Weekly')
    for want in ('🏆 Top contributors', '🎒 Biggest hauls', '🏛️ Society', '🏁 Season'):
        assert want in names
    assert any(h.startswith('🏅 Trophies') for h in names) and any(h.startswith('👋 New citizens') for h in names)
    assert '**Ann**' in plain
    sent = []

    class Reply:
        status_code = 200
    monkeypatch.setattr('requests.post', lambda url, **kw: sent.append((url, kw['json'])) or Reply())
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'token'); monkeypatch.setenv('RECAP_CHANNEL_ID', '123456789012345678')
    with m.SessionLocal() as db:
        ok, text = recap.post(m, db)
        db.commit()
        assert ok and len(sent) == 1 and '123456789012345678' in sent[0][0]
        from app import layout_v2
        body = sent[0][1]
        assert layout_v2.is_v2(body) and title in layout_v2.text_of(body)              # one card in the newer layout
        assert all(name in layout_v2.text_of(body) for name in names)
        assert recap.post(m, db)[0] is False and len(sent) == 1        # once a week
        assert recap.post(m, db, force=True)[0] and len(sent) == 2
    preview = client.get('/api/v1/recap').text
    assert 'Top contributors' in preview
    assert client.get('/api/v1/recap', params={'provider': 'twitch'}).text.startswith('📰 This week so far')


def test_the_recap_is_due_on_sunday_evening_only():
    from datetime import datetime, timezone
    assert recap.due(datetime(2026, 10, 4, recap.RECAP_HOUR, 5, tzinfo=timezone.utc))          # a Sunday
    assert not recap.due(datetime(2026, 10, 4, max(0, recap.RECAP_HOUR - 1), tzinfo=timezone.utc))
    assert not recap.due(datetime(2026, 10, 3, 23, tzinfo=timezone.utc))


def test_funny_seedling_moments_prefer_mishaps_one_per_seedling():
    call('/api/v1/start', uid='a', name='Ann')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W).first()
        for text in ['FARMS, Day 1 — Ann tended the fields.', 'COMMONS, Day 1 — Ann tripped over Rocky and argued with a duck.',
                     'COMMONS, Day 1 — Ann dozed off during games.']:
            m.autonomy.diary(m, db, p, 'commons', '🌱', text)
        db.commit()
        moments = recap.funny(m, db, recap.week_start(), seasons.week_key())
    assert len(moments) == 1 and 'Rocky' in moments[0][1]


# ---------------------------------------------------------------- Discord

def test_discord_commands_and_moderator_tools():
    for name in ('vote', 'season', 'challenge', 'trophies'):
        assert name in m.DISCORD_REGISTERED and name in m.DISCORD_PRIVATE_COMMANDS
    text = m._discord_call_internal('vote', '111', 'Disco', {'choice': 1}, 'i1')
    assert 'Vote counted' in text
    assert 'SEASON 1' in m._discord_call_internal('season', '111', 'Disco', {}, 'i2')
    assert 'TROPHIES' in m._discord_call_internal('trophies', '111', 'Disco', {}, 'i3')
    command, options = m.discord_legacy_route('mod', {'action': 'challengestart', 'challenge': 'harvest_rush'})
    assert (command, options) == ('challengestart', {'challenge': 'harvest_rush'})
    assert 'Harvest Rush' in m._discord_call_internal(command, '111', 'Mod', options, 'i4')
    assert 'HARVEST RUSH' in m._discord_call_internal('challenge', '111', 'Disco', {}, 'i5')
    assert 'stopped' in m._discord_call_internal('challengestop', '111', 'Mod', {}, 'i6')
    assert 'LIVE' in m._discord_call_internal('liveon', '111', 'Mod', {}, 'i7')
    assert 'Weekly' in m._discord_call_internal('recappreview', '111', 'Mod', {}, 'i8')
    mod = next(c for c in m.DISCORD_COMMAND_CATALOG if c['name'] == 'mod')
    actions = {c['value'] for c in mod['options'][0]['choices']}
    assert community.MOD <= actions and len(actions) <= 25


def test_everything_is_off_when_the_switch_is(monkeypatch):
    monkeypatch.setattr(community, 'ENABLED', False)
    call('/api/v1/start')
    gather_lumber('u1')
    with m.SessionLocal() as db:
        assert db.query(seasons.SeasonScore).count() == 0 and db.query(trophies.Found).count() == 0
    data = client.get('/api/v1/overlay', params={'channel': W}).json()
    assert 'vote' not in data and 'season' not in data


def test_a_voted_project_also_starts_on_the_twitch_channel_project():
    call('/api/v1/start')
    with m.SessionLocal() as db:
        twitch = m.current_project(db, 'twitch-123', 1)
        twitch.progress = twitch.goal; db.commit()
        options = json.loads(votes.ballot(m, db).options)
    pick = next(i for i, o in enumerate(options, 1) if o.startswith('project:'))
    call('/api/v1/vote', choice=str(pick))
    next_day()
    with m.SessionLocal() as db:
        votes.sync(m, db); db.commit()
        assert db.query(m.SocietyProject).filter_by(channel_id='twitch-123').one().project_key == options[pick - 1].split(':')[1]
