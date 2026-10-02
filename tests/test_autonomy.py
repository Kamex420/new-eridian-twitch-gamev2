"""Autonomous Seedlings: schedules, moods, thoughts, the diary, and the map and narrator overlays."""
import json
from datetime import timedelta
from types import SimpleNamespace
from test_colony import m, reset, client, seed
from test_workbench_ui import citizen, press, controls, W
from test_task_queue import enqueue
from app import autonomy as a, ui

UID = 'u'


def away(uid=UID, channel='test', minutes=40):
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=channel, twitch_uid=uid).one()
        p.last_seen = m.now() - timedelta(minutes=minutes)
        db.query(m.Cooldown).delete()
        db.commit()


def set_life(uid=UID, channel='test', **values):
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=channel, twitch_uid=uid).one()
        life = m.life_state(db, p)
        for k, v in values.items():
            setattr(life, k, v)
        db.commit()


def life_row(uid=UID, channel='test'):
    with m.SessionLocal() as db:
        found = db.get(a.SeedlingLife, (channel, uid))
        db.expunge_all()
        return found


def diary(uid=UID, channel='test'):
    with m.SessionLocal() as db:
        return [e.text for e in db.query(a.SeedlingDiary).filter_by(channel_id=channel, canonical_uid=uid).order_by(a.SeedlingDiary.id)]


# ---------------------------------------------------------------- schedules and moods

def test_schedule_presets_and_custom_phases():
    seed()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert 'Night owl' in a.set_preset(db, p, 'night_owl')
        found = a.row(db, p.channel_id, p.twitch_uid)
        assert a.schedule_of(found)['Morning'] == 'sleep' and a.preset_name(found) == 'Night owl'
        a.set_phase(db, p, 'Morning', 'work')
        assert a.preset_name(found) == 'Custom' and a.schedule_of(found)['Morning'] == 'work'
        assert 'Nothing changed' in a.set_preset(db, p, 'nonsense')


def test_moods_follow_needs_weather_and_failures():
    life = SimpleNamespace(energy=90, nutrition=90, social=90, comfort=90, morale=90)
    assert a.mood_of(life)[0] == 'inspired'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'morale': 50}))[0] == 'content'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'nutrition': 30}))[0] == 'hungry'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'energy': 30, 'social': 20}))[0] == 'stressed'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'energy': 10}))[0] == 'miserable'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'morale': 50}), 'dust_winds')[0] == 'uneasy'
    assert a.mood_of(SimpleNamespace(**{**vars(life), 'morale': 50}), '', failures=3)[0] == 'stressed'
    assert a.thought_for('lonely', friend='Astra', seed='x') in {t.format(friend='Astra') for t in a.THOUGHTS['lonely']}
    assert all(len(lines) >= 5 for lines in a.THOUGHTS.values())


def test_mood_changes_success_chance():
    seed()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        bonus, notes = a.mood_modifier(m, db, p)
        assert bonus == .03 and 'Inspired' in notes[0]
        m.life_state(db, p).energy = 5
        db.commit()
        assert a.mood_modifier(m, db, p)[0] == -.04
        s = m.society(db, p.channel_id)
        *_, parts = m.world_rule_bundle(db, p, s, 'farm', 'cultivation')
        assert any('Miserable mood' in x for x in parts)


# ---------------------------------------------------------------- living on its own

def test_seedling_steps_aside_while_the_player_is_active():
    seed()
    assert a.live_one(m, 'test', UID) == ''
    assert diary() == []


def test_seedling_works_its_job_when_away_and_keeps_last_seen():
    seed()
    client.get('/api/v1/job', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'job': 'farmer'})
    away()
    with m.SessionLocal() as db:
        before = db.query(m.Player).one().last_seen
    text = a.live_one(m, 'test', UID)
    assert text and 'Kamex' in text
    found = life_row()
    assert found.place == 'agricultural_district' and found.activity.startswith(('Gathering', 'Working'))
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        assert m.as_utc(p.last_seen) == m.as_utc(before)     # autonomy is not the player being active
        assert sum(m.task_queue.inventory_snapshot(m, db, p).values()) > 0 or p.crops > 0   # real materials were gathered
    assert len(diary()) == 1 and ('brings in' in text or 'gathered' in text or 'tended' in text)


def test_needs_come_first():
    seed()
    away()
    set_life(nutrition=20)
    a.live_one(m, 'test', UID)
    assert life_row().activity == 'Eating'
    away()
    set_life(nutrition=90, energy=10)
    a.live_one(m, 'test', UID)
    assert life_row().activity == 'Sleeping'


def test_free_time_social_and_sleep_blocks(monkeypatch):
    seed()
    seed(uid='v', name='Astra')
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(twitch_uid=UID).one()
        found = a.row(db, 'test', UID, create=True)
        clock = {'phase': 'Evening', 'condition_key': ''}
        life = m.life_state(db, p)
        found.schedule = json.dumps({'Morning': 'sleep', 'Day': 'free', 'Evening': 'social', 'Night': 'sleep'})
        assert a.plan(m, db, p, found, life, clock)['kind'] in {'hi', 'hangout'}
        clock['phase'] = 'Day'
        monkeypatch.setattr(a.random, 'random', lambda: .1)
        assert a.plan(m, db, p, found, life, clock)['kind'] == 'hobby'
        clock['phase'] = 'Night'
        life.energy = life.comfort = 100
        assert a.plan(m, db, p, found, life, clock)['kind'] == 'rest'


def test_a_running_queue_is_the_seedlings_work():
    enqueue(count=3)                            # a Discord citizen: discord:u
    away('discord:u')
    assert a.live_one(m, 'test', 'discord:u') == ''
    found = life_row('discord:u')
    assert found.activity.startswith('Queue:') and found.emoji == '⏱️'
    assert any('queue' in t for t in diary('discord:u'))


def test_autonomy_off_and_the_worker_pass():
    seed()
    away()
    a.tick(m)                                  # first pass creates the row with a staggered start
    found = life_row()
    assert found is not None and found.enabled
    with m.SessionLocal() as db:
        a.set_enabled(db, db.query(m.Player).one(), False)
        db.commit()
    assert a.live_one(m, 'test', UID) == ''
    with m.SessionLocal() as db:
        a.set_enabled(db, db.query(m.Player).one(), True)
        db.get(a.SeedlingLife, ('test', UID)).next_at = m.now() - timedelta(minutes=1)
        db.commit()
    a.tick(m)
    assert len(diary()) == 1


def test_autonomous_actions_are_not_the_players_again_action():
    seed()
    client.get('/api/v1/relax', params={'channel': 'test', 'uid': UID, 'name': 'Kamex'})
    away()
    a.live_one(m, 'test', UID)
    from app import extras
    with m.SessionLocal() as db:
        assert [r.command for r in extras.recent(db, 'test', UID, 'twitch')] == ['relax']


def test_diary_is_capped_and_welcome_back_uses_it():
    seed()
    since = m.now() - timedelta(minutes=5)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        for i in range(a.DIARY_KEEP + 5):
            a.diary(m, db, p, 'commons', '🎲', f'entry {i}')
        db.commit()
        assert db.query(a.SeedlingDiary).count() == a.DIARY_KEEP
        lines = a.away_lines(m, db, p, since)
    assert lines[0].startswith('📓') and 'more in your diary' in lines[-1]


# ---------------------------------------------------------------- commands and buttons

def test_twitch_commands():
    seed()
    view = client.get('/api/v1/seedling', params={'channel': 'test', 'uid': UID, 'name': 'Kamex'}).text
    assert 'Kamex' in view and 'Autonomy on' in view
    assert 'Socialite' in client.get('/api/v1/schedule', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'preset': 'socialite'}).text
    assert 'off' in client.get('/api/v1/autonomy', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'state': 'off'}).text
    assert 'diary' in client.get('/api/v1/diary', params={'channel': 'test', 'uid': UID, 'name': 'Kamex'}).text


def test_routine_command_starts_saved_routines_on_the_shared_route():
    seed()
    text = client.get('/api/v1/routine', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'n': '1'}).text
    assert 'saved routines' in text


def test_discord_seedling_screens():
    citizen()
    view = press(ui.cid('111', 'mv', 'sl_view'))['data']
    labels = [c.get('label') for c in controls(view)]
    assert {'Let it decide', 'Diary', 'Schedule', 'Autonomy off'} <= set(labels)
    editor = press(ui.cid('111', 'lp'))['data']
    assert len([c for c in controls(editor) if c['type'] == 3]) == 4
    press(ui.cid('111', 'lp', 'Evening'), values=['free'])
    assert a.schedule_of(life_row('discord:111', W))['Evening'] == 'free'
    decide = next(c for c in controls(view) if c.get('label') == 'Let it decide')
    result = json.dumps(press(decide['custom_id']), ensure_ascii=False)
    assert 'Seedling' in result and diary('discord:111', W)
    assert 'seedling' in m.DISCORD_OPTION_SCHEMA
    assert 'SEEDLING' in m.status_view(W, '111', 'Kam', 'discord').body.decode()


# ---------------------------------------------------------------- the stream

def test_overlay_map_and_narrator():
    seed()
    away()
    a.live_one(m, 'test', UID)
    data = client.get('/api/v1/overlay', params={'channel': 'test'}).json()
    me = next(s for s in data['seedlings'] if s['name'] == 'Kamex')
    assert me['place'] in a.PLACES and me['mood'] and me['activity']
    assert data['narration'] and 'Kamex' in data['narration'][0]['text']
    for panel in ('map', 'narrator'):
        page = client.get(f'/obs/{panel}', params={'channel': 'test'})
        assert page.status_code == 200 and '/api/v1/overlay' in page.text
    assert '/obs/map' in client.get('/obs', params={'channel': 'test'}).text
    assert len(me['lines']) >= 3 and me['lines'][0] == me['thought'] and 'condition_key' in data
    assert 'job' in me
    assert 0 <= data['hour'] < 24 and data['phase'] in {'Morning', 'Day', 'Evening', 'Night'}


def test_seedlings_talk_about_their_work_friends_and_holidays():
    context = {'phase': 'Night', 'condition': 'dust_winds', 'holiday': 'Halloween', 'bucket': 1, 'extra': ['Heard Corn is selling high today.']}
    me = {'id': 'a', 'name': 'Kam', 'place': 'agricultural_district', 'activity': 'Gathering Corn', 'thought': 'Good day on Avesta.'}
    friend = {'id': 'b', 'name': 'Mira', 'place': 'agricultural_district', 'activity': 'Relaxing', 'thought': ''}
    lines = a.chatter(me, [me, friend], context)
    assert lines[0] == 'Good day on Avesta.' and len(lines) == 6 and len(set(lines)) == 6
    assert any('Corn' in line for line in lines) and any('Mira' in line for line in lines)
    assert any(line in a.SAY_HOLIDAY['Halloween'] for line in lines)
    later = a.chatter(me, [me, friend], {**context, 'bucket': 2})
    assert later[0] == lines[0] and all(len(line) <= 60 for line in lines + later)


def test_map_page_has_the_camera_walking_holidays_and_weather():
    page = client.get('/obs/map', params={'channel': 'test'}).text
    for feature in ('function look(', 'function route(', 'function scaffold(', 'function decorate(', 'function sky(', 'function liveTown(',
                    "'Christmas'", "'Halloween'", 'good_growing', 'dust_winds', "Q.get('holiday')", "Q.get('camera')",
                    'function lightAt(', 'function shadows(', "Q.get('hour')", 'd.hour'):
        assert feature in page, feature


def test_merge_moves_the_seedling_and_diary():
    seed()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        a.row(db, 'test', UID, create=True).schedule = 'workaholic'
        a.diary(m, db, p, 'commons', '🎲', 'hello')
        a.merge(db, 'test', UID, 'w')
        db.commit()
        assert db.get(a.SeedlingLife, ('test', 'w')).schedule == 'workaholic'
        assert db.query(a.SeedlingDiary).filter_by(canonical_uid='w').count() == 1


# ---------------------------------------------------------------- news reports, real materials, needs, growth

def test_work_gathers_real_materials_and_reports_them_as_news():
    seed()
    client.get('/api/v1/job', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'job': 'miner'})
    away()
    story = a.live_one(m, 'test', UID)
    assert story.startswith('FRONTIER EDGE, Day ') and 'Kamex' in story
    with m.SessionLocal() as db:
        entry = db.query(a.SeedlingDiary).one()
        assert entry.desk in {'MINING', 'SUPPLY'} and entry.headline
        assert 'TASK FAILED' not in entry.text and 'WHY' not in entry.text and '**' not in entry.text


def test_goal_materials_come_first():
    seed()
    from app import workbench as wb, extras
    campfire = next(e for e in wb.index(m) if e.name == 'Campfire')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        extras.set_goal(m, db, p, campfire.id)
        db.commit()
        step = a.work_plan(m, db, p, a.row(db, 'test', UID, create=True))
        assert step['kind'] == 'gather' and step.get('goal') and m.resource_name(step['item']) == 'Lumber'


def test_needs_are_tended_before_they_stop_work():
    seed()
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        life = m.life_state(db, p)
        life.energy = 30                     # above the work limit of 20, but low
        assert a.needs_plan(m, db, p, life, 'work')['kind'] in {'sleep', 'relax'}
        life.energy, life.nutrition = 90, 40
        assert a.needs_plan(m, db, p, life, 'work')['kind'] == 'eat'
        life.nutrition, life.social = 90, 20
        assert a.needs_plan(m, db, p, life, 'work')['kind'] in {'games', 'hi', 'hangout'}
        life.social = 90
        assert a.needs_plan(m, db, p, life, 'work') is None


def test_a_paused_queue_gets_its_needs_recovered():
    enqueue(count=3)
    with m.SessionLocal() as db:
        row = db.get(m.task_queue.TaskQueue, ('test', 'discord:u'))
        row.state = 'paused'
        db.commit()
    away('discord:u')
    set_life('discord:u', energy=5)
    story = a.live_one(m, 'test', 'discord:u')
    assert 'paused queue can carry on' in story


def test_names_and_reasons_are_cleaned_for_the_news():
    assert a.clean_name('Kamex [New Eridian Official]') == 'Kamex'
    assert a.clean_name('Siris_Sin (Autarch)') == 'Siris_Sin'
    assert a.clean_reason('**TASK FAILED**\nWHY\n⛏️ Deschroyer comes back empty-handed.') == 'Deschroyer comes back empty-handed.'
    assert a.clean_reason('❌ Research failed · Astra gets inconclusive results. +0 rewards') == 'Astra gets inconclusive results.'


def test_the_map_grows_with_the_society():
    seed()
    with m.SessionLocal() as db:
        early = a.districts(m, db, ['test', W])
        assert early['tier_index'] == 0 and not early['districts']['spaceport_quarter']['unlocked']
        assert early['districts']['agricultural_district']['unlocked']
        s = m.society(db, W)
        s.food = s.materials = s.development = s.knowledge = s.treasury = s.reputation = 2500
        db.commit()
        grown = a.districts(m, db, ['test', W])
    assert grown['tier_index'] == 3 and grown['districts']['spaceport_quarter']['unlocked']
    assert grown['districts']['agricultural_district']['level'] > early['districts']['agricultural_district']['level']


def test_welcome_back_adds_up_exactly_what_the_seedling_collected():
    seed()
    client.get('/api/v1/job', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'job': 'miner'})
    since = m.now() - timedelta(minutes=1)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        start = dict(m.seed_content.stock(m, db, p)); start_sc = p.sc
    for _ in range(6):
        away()
        with m.SessionLocal() as db:                  # keep needs up so every step is a work step
            p = db.query(m.Player).one(); life = m.life_state(db, p)
            life.energy = life.nutrition = life.comfort = life.social = 95; db.commit()
        a.live_one(m, 'test', UID, force=True)
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        end = m.seed_content.stock(m, db, p)
        real = {k: n - start.get(k, 0) for k, n in end.items() if n > start.get(k, 0)}
        gained, used, sc, steps = a.haul_since(db, p, since)
        lines = a.away_lines(m, db, p, since)
    assert gained and {k: gained[k] for k in real} == real            # the totals match what landed in the bag
    text = '\n'.join(lines)
    assert f'Collected {sum(gained.values())} items' in text
    for k, n in gained.items():
        assert f'{n} × {m.resource_name(k)}' in text


# ---------------------------------------------------------------- thinking a Work turn through

def back_from_collecting(job, uid=UID):
    """A Seedling whose last step was collecting, so this Work turn is a practice turn."""
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(twitch_uid=uid).one()
        p.job = job
        a.row(db, p.channel_id, uid, create=True).activity = 'Gathering Stone'
        db.commit()


def test_a_seedling_takes_turns_collecting_and_training_and_says_why():
    seed()
    client.get('/api/v1/job', params={'channel': 'test', 'uid': UID, 'name': 'Kamex', 'job': 'miner'})
    away()
    first = a.live_one(m, 'test', UID, force=True)
    assert life_row().activity.startswith('Gathering') and '“As a Miner, I bring in' in first      # the material it has least of
    away()
    second = a.live_one(m, 'test', UID, force=True)
    found = life_row()
    assert found.activity.startswith('Training: ') and found.place == 'frontier_edge'               # Harvesting practice
    assert found.plan.startswith('Practising ') and f'“{found.plan}”' in second
    with m.SessionLocal() as db:
        assert db.query(a.SeedlingDiary).order_by(a.SeedlingDiary.id.desc()).first().desk == 'TRAINING'
        assert '🧠 Thinking: Practising' in a.view_text(m, db, db.query(m.Player).one())
    away()
    assert life_row().activity.startswith('Training') and a.live_one(m, 'test', UID, force=True)
    assert life_row().activity.startswith('Gathering')                                             # and back to collecting


def test_practice_uses_plenty_of_its_own_materials_and_never_what_the_goal_is_saving():
    seed()
    back_from_collecting('processor')
    water = m.seed_content.find_item('Murky Water (1000ml)')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        found = a.row(db, 'test', UID)
        step = a.work_plan(m, db, p, found)          # no water: fetch it for Water Treatment
        assert step['kind'] == 'gather' and step['item'] == water
        assert step['why'].startswith('Water Treatment needs Murky Water (1000ml) and I have 0 of 2.')
        m.material_change(db, p, water, 5)
        step = a.work_plan(m, db, p, found)
        assert step['task'] == 'train_water_treatment' and step['why'].startswith('Practising Water Treatment')
        mind = a.Mind(m, db, p)
        mind.saving = {'Murky Water (1000ml)'}
        assert a.practice_plan(m, db, p, mind, trade_only=True) is None


def test_a_missing_material_is_made_with_another_training_task_or_gathered_for_it():
    from test_colony import ready_for
    ready_for('train_stone_processing')            # the Masonry workstation is open; 1 Stone in the bag
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        p.job = 'artisan'
        mind = a.Mind(m, db, p)
        step = a.supply_plan(m, db, p, mind)        # Masonry needs Stone Blocks; Stone Processing needs 2 Stone first
        assert step['kind'] == 'gather' and m.resource_name(step['item']) == 'Stone'
        assert step['why'] == ('Masonry needs Stone Block and I have 0 of 4. Stone Processing makes it, but needs Stone. '
                               'Collecting Stone first.')
        m.material_change(db, p, step['item'], 3)
        step = a.supply_plan(m, db, p, a.Mind(m, db, p))
        assert step['task'] == 'train_stone_processing' and step['why'].endswith('Making it with Stone Processing first.')


def test_with_a_goal_it_collects_and_trains_for_it_in_turn():
    seed()
    from app import workbench as wb, extras
    nitric = next(e for e in wb.index(m) if e.name == 'Nitric Acid')
    with m.SessionLocal() as db:
        p = db.query(m.Player).one()
        extras.set_goal(m, db, p, nitric.id)
        db.commit()
        found = a.row(db, 'test', UID, create=True)
        collect = a.work_plan(m, db, p, found)
        assert collect['kind'] == 'gather' and collect['goal'] and collect['why'].startswith('My goal is Nitric Acid, and it still needs ')
        found.activity = 'Gathering Lumber'
        train = a.work_plan(m, db, p, found)                  # a practice turn: the goal's own training
        assert train['kind'] == 'train' and train['goal'] and 'the way there includes' in train['why']
