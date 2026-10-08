"""Everyday work gets what /work tasks get (game.colony_events.work_counts), Seedling Contribution is capped at 25 a
day (autonomy.CONTRIBUTION_CAP), rare ores need a Mineral Extractor and come from /mine (crafting_progression), and
the 11 advanced parts nothing used make holiday showpieces (seasonal.FESTIVAL_SHOWPIECES)."""
import pytest
from sqlalchemy import select
from test_colony import m, reset, seed
from test_work_counts import citizen, gather, STONE, BERRY, WATER
from app import seed_content as s, crafting_progression as cp, autonomy, task_queue, seasonal, trophies

ORE = next(k for k, v in s.GATHER.items() if v['branch'] == 'ore_mining' and k not in cp.RARE and s.ITEMS[k]['name'] == 'Hematite Ore')
RARE = next(k for k in sorted(cp.RARE) if s.ITEMS[k]['name'] != 'Argentite Ore')     # Argentite also holds the old rare_ore stock


def contract(db, p, action, target=3):
    d = m.daily(db, p)
    d.action, d.target, d.progress, d.complete = action, target, 0, False
    db.commit()
    return d


# ---------------------------------------------------------------- 1. daily contracts

def test_mining_counts_for_a_mine_contract():
    with m.SessionLocal() as db:
        p = citizen(db)
        d = contract(db, p, 'mine', 2)
        gather(db, p, ORE)                       # random.random is 0.5 in tests: the mining roll succeeds
        assert d.progress == 1
        done = gather(db, p, ORE)
        assert d.complete and 'Daily complete' in done


def test_workbench_crafting_counts_for_a_make_contract():
    with m.SessionLocal() as db:
        p = citizen(db)
        d = contract(db, p, 'make', 1)
        key = next(k for k in s.MACHINE_RECIPES if s.ITEMS[k]['name'] == 'Basic Workbench')
        rid = next(k for k, r in s.RECIPES.items() if key in r['outputs'])
        for k, n in s.RECIPES[rid]['inputs'].items():
            m.material_change(db, p, k, n)
        db.query(m.Cooldown).delete()
        assert 'CRAFTING COMPLETE' in s.craft(db, p, rid, 'discord')
        assert d.complete


def test_gathering_plants_does_not_count_for_a_mine_contract():
    with m.SessionLocal() as db:
        p = citizen(db)
        d = contract(db, p, 'mine')
        gather(db, p, BERRY)
        assert d.progress == 0


# ---------------------------------------------------------------- 2. who counts as active

def active(db):
    return set(db.scalars(select(m.RealActivity.canonical_uid)))


def test_real_gathering_counts_as_active_and_shows_in_the_feed():
    with m.SessionLocal() as db:
        p = citizen(db)
        gather(db, p, STONE)
        assert active(db) == {p.twitch_uid} and m.active_player_count(db, 'test') == 1
        assert db.scalars(select(m.ActionLog.action)).all() == ['gather']


def test_seedlings_and_queues_do_not_count_as_active():
    with m.SessionLocal() as db:
        p = citizen(db)
        for var, value in ((autonomy.ACTING, True), (task_queue.actor_context, ('test', p.twitch_uid))):
            token = var.set(value)
            try:
                gather(db, p, STONE)
                m.log_action(db, 'test', p.twitch_uid, 'train_pottery', 'Seedling practice')
            finally:
                var.reset(token)
        assert active(db) == set()
        assert len(db.scalars(select(m.ActionLog)).all()) == 4        # still in the activity feed


def test_event_size_counts_players_not_seedlings():
    seed('a', name='Ann')
    seed('b', name='Bo')
    with m.SessionLocal() as db:
        a = m.player(db, 'test', 'twitch', 'a', 'Ann')[1]
        b = m.player(db, 'test', 'twitch', 'b', 'Bo')[1]
        gather(db, a, STONE)
        token = autonomy.ACTING.set(True)
        try:
            gather(db, b, STONE)
        finally:
            autonomy.ACTING.reset(token)
        assert m.active_player_count(db, 'test') == 1


# ---------------------------------------------------------------- 3. the smaller rewards

def test_three_kinds_of_gathering_complete_daily_variety():
    with m.SessionLocal() as db:
        p = citizen(db)
        assert 'Daily Variety 1/3' in gather(db, p, STONE)
        gather(db, p, BERRY)
        sc = p.sc
        assert 'Daily Variety complete' in gather(db, p, WATER)
        assert p.sc >= sc + 6


def test_modern_work_can_turn_up_encounters_lore_and_bonuses(monkeypatch):
    calls = []
    for name in ('maybe_world_encounter', 'maybe_lore_discovery', 'grant_random_bonus'):
        from app.game import colony_events
        monkeypatch.setattr(colony_events, name, lambda *a, name=name, **k: calls.append(name) or '')
    monkeypatch.setattr(m, 'rare_outcome', lambda *a: calls.append('rare_outcome') or '')
    monkeypatch.setattr(m, 'achieve', lambda *a: calls.append('achieve') or '')
    with m.SessionLocal() as db:
        gather(db, citizen(db), STONE)
    assert set(calls) == {'maybe_world_encounter', 'maybe_lore_discovery', 'grant_random_bonus', 'rare_outcome', 'achieve'}


# ---------------------------------------------------------------- Seedling Contribution cap

def test_a_seedling_keeps_at_most_25_contribution_a_day(monkeypatch):
    with m.SessionLocal() as db:
        p = citizen(db)
        before = p.contribution
        assert autonomy.keep_contribution(db, p, 0) == 0
        p.contribution += 20
        assert autonomy.keep_contribution(db, p, 20) == 0
        p.contribution += 8
        assert autonomy.keep_contribution(db, p, 8) == 3                 # 5 more fit under 25
        assert p.contribution == before + 25 and autonomy.contribution_room(db, p) == 0
        tomorrow = m.now() + m.timedelta(days=1)
        monkeypatch.setattr(m, 'now', lambda: tomorrow)
        assert autonomy.contribution_room(db, p) == 25


def test_a_seedling_step_over_the_cap_earns_no_contribution():
    from test_autonomy import away
    seed()
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        db.add(autonomy.SeedlingContribution(channel_id='test', canonical_uid=p.twitch_uid, day=autonomy._today(), amount=25))
        db.commit()
        before = p.contribution
    away()
    autonomy.live_one('test', 'u', force=True)
    with m.SessionLocal() as db:
        assert m.player(db, 'test', 'twitch', 'u', 'Kamex')[1].contribution == before
        assert m.society(db, 'test').materials + m.society(db, 'test').food > 0      # the colony still grows


# ---------------------------------------------------------------- rare ores

def test_rare_ores_are_locked_without_an_extractor_everywhere():
    with m.SessionLocal() as db:
        p = citizen(db)
        assert s.gather(db, p, RARE, 'twitch') == cp.RARE_LOCK
        assert 'needs a Mineral Extractor' in m.ore_choice_rows(db, p)[-1][0]
    view = m.mining('test', 'u', provider='twitch').body.decode()
    assert 'Rare (needs a Mineral Extractor)' in view


def test_either_extractor_unlocks_rare_ores_in_mine():
    with m.SessionLocal() as db:
        p = citizen(db)
        m.material_change(db, p, cp.SMALL_EXTRACTOR, 1)
        db.commit()
        assert cp.extractor(db, p) == cp.SMALL_EXTRACTOR
        assert not any('🔒' in label for label, _ in m.ore_choice_rows(db, p))
    text = m.mining('test', 'u', ore=s.ITEMS[RARE]['name'], action='mine', provider='twitch').body.decode()
    assert text.startswith('RUNNING: Mine ' + s.ITEMS[RARE]['name']), text          # the same /mine queue as any ore
    with m.SessionLocal() as db:
        p = citizen(db)
        db.query(task_queue.TaskQueue).delete()
        gather(db, p, RARE)
        assert m.material_amount(db, p, RARE) == 1
        m.material_change(db, p, cp.FRONTIERS_EXTRACTOR, 1)
        db.query(m.Cooldown).delete()
        db.commit()
        assert cp.extractor(db, p) == cp.FRONTIERS_EXTRACTOR
        gather(db, p, RARE)
        assert m.material_amount(db, p, RARE) == 3


def test_the_small_extractor_needs_no_rare_ores_to_build():
    def raws(k, seen=()):
        if k in s.GATHER:
            return {k}
        rid = s.ACQUISITION.get(k)
        return set().union(*[raws(i, seen + (k,)) for i in s.RECIPES[rid]['inputs']]) if rid and k not in seen else set()
    needed = set().union(*[raws(k) for k in s.RECIPES[s.ACQUISITION[cp.SMALL_EXTRACTOR]]['inputs']])
    assert not needed & cp.RARE


def test_rare_mining_counts_for_events_and_contracts():
    with m.SessionLocal() as db:
        p = citizen(db)
        m.material_change(db, p, cp.SMALL_EXTRACTOR, 1)
        w = m.world(db, 'test')
        m.start_event(db, w, 'mining', 'test')
        d = contract(db, p, 'mine')
        text = gather(db, p, RARE)
        assert 'Mining Boom: Primary response +1' in text and d.progress == 1


# ---------------------------------------------------------------- holiday showpieces

PARTS = ('Actuator', 'Aramid Fabric', 'Blade Guard', 'Board Computer', 'Ceramic Shield Tile', 'Fortified Glass', 'Kerosene',
         'Piston', 'Quantum Processor', 'Teak Parquet', 'White Paint')


def test_every_unused_part_makes_a_holiday_showpiece():
    shows = {k: v for k, v in seasonal.FESTIVAL_CRAFT_ITEMS.items() if v['showpiece']}
    used = {s.ITEMS[i]['name'] for v in shows.values() for i in s.RECIPES[v['recipe']]['inputs']}
    assert set(PARTS) <= used
    for name in PARTS:
        key = next(k for k in s.ACTIVE if s.ITEMS[k]['name'] == name and s.ACQUISITION.get(k))
        assert s.PURPOSE[key]['mode'] == 'ingredient', name          # no longer only "analyze surplus"
    assert {v['holiday'] for v in shows.values()} == set(seasonal.FESTIVAL_FOODS)


def test_showpieces_are_extra_not_needed_for_the_feast_hat():
    for holiday in seasonal.FESTIVAL_FOODS:
        needed = seasonal.festival_items(holiday)
        assert not any(seasonal.FESTIVAL_CRAFT_ITEMS.get(k, {}).get('showpiece') for k in needed), holiday
    assert 'SHOWPIECES (optional' in seasonal.holiday_message() or not seasonal.holidays_active_for()


def test_a_showpiece_crafts_during_its_festival(monkeypatch):
    monkeypatch.setattr(seasonal, 'festival_open', lambda recipe, today=None: True)
    key = 'fest_pop_up_skeleton'
    row = seasonal.FESTIVAL_CRAFT_ITEMS[key]
    assert row['holiday'] == 'Halloween' and row['showpiece']
    with m.SessionLocal() as db:
        p = citizen(db)
        for k, n in s.RECIPES[row['recipe']]['inputs'].items():
            m.material_change(db, p, k, n)
        db.query(m.Cooldown).delete()
        assert 'CRAFTING COMPLETE' in s.craft(db, p, row['recipe'], 'discord')
        assert m.material_amount(db, p, key) == 1
