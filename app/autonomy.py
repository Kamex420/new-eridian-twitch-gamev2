"""Seedlings that live on their own: daily schedules, moods, thoughts and a diary.

Each citizen's Seedling follows a schedule across the four Avesta phases
(Morning, Day, Evening, Night). Every block is Work, Free time, Social or Sleep.
While the player is not playing, a background loop lets the Seedling act about
once every AUTONOMY_MINUTES: it works its job, eats when hungry, sleeps when
tired, practises a hobby, or meets a friend in the Commons. Every choice goes
through the ordinary game commands, so the same costs, cooldowns, gates and
rewards apply as when the player presses the button themselves.

Moods come from needs, the weather, company and how the day is going. They
nudge success chances a little (Inspired +3% … Miserable −4%) and give the
Seedling a voice: a short thought in its own words. Everything it does is
written to a diary, which the player reads when they come back and which the
stream narrator and the Avesta map overlay show live.

The Seedling steps aside whenever the player is active (any command in the last
AWAY_MINUTES) or has a queue running, and it never crafts, sells, buys or uses
festival food. Players can switch autonomy off at any time.
"""
import contextvars
import hashlib
import json
import logging
import os
import random
from datetime import timedelta
from sqlalchemy import Column, String, Integer, DateTime, select, delete
from .db import Base
from . import needs

AUTONOMY_MINUTES = max(2, int(os.getenv('AUTONOMY_MINUTES', '10')))   # one autonomous action this often
AWAY_MINUTES = 10              # the Seedling steps aside while its player is active
ACTIVE_DAYS = 3                # Seedlings of players seen within this many days keep living
DIARY_KEEP = 60
BATCH = 20                     # Seedlings handled per worker pass
ACTING = contextvars.ContextVar('ne_autonomous', default=False)

PHASES = ('Morning', 'Day', 'Evening', 'Night')
BLOCKS = {'work': ('💼', 'Work'), 'free': ('🎨', 'Free time'), 'social': ('🤝', 'Social'), 'sleep': ('🛏️', 'Sleep')}
PRESETS = {
    'balanced': ('Balanced', 'Work through the day, friends in the evening, sleep at night.', ('work', 'work', 'social', 'sleep')),
    'workaholic': ('Workaholic', 'Work from dawn until dusk. Sleep at night.', ('work', 'work', 'work', 'sleep')),
    'night_owl': ('Night owl', 'Sleep through the morning; work the evening and night.', ('sleep', 'free', 'work', 'work')),
    'socialite': ('Socialite', 'A little work, a lot of company.', ('free', 'work', 'social', 'social')),
    'homebody': ('Homebody', 'Work the day, keep mornings and evenings for hobbies.', ('free', 'work', 'free', 'sleep')),
}
DEFAULT_PRESET = 'balanced'

PLACES = {
    'residential_ring': ('Residential Ring', '🏠'), 'agricultural_district': ('Agricultural District', '🌾'),
    'industrial_ward': ('Industrial Ward', '🏭'), 'research_block': ('Research Block', '🔬'),
    'market_concourse': ('Market Concourse', '🪙'), 'spaceport_quarter': ('Spaceport Quarter', '🚀'),
    'frontier_edge': ('Frontier Edge', '🧭'), 'commons': ('The Commons', '⛲'),
}

# What each job does on its own, in turn. Only actions that cost needs, never stored materials.
JOB_WORK = {
    'farmer': ('farm', 'forage'), 'cultivator': ('farm', 'forage'), 'miner': ('mine', 'scavenge'),
    'technician': ('repair', 'scan'), 'engineer': ('repair', 'scan'), 'researcher': ('research', 'scan'),
    'courier': ('cargo', 'delivery', 'spaceport'), 'explorer': ('explore', 'scavenge'), 'merchant': ('market',),
    'harvester': ('forage', 'scavenge'), 'processor': ('water', 'scan'), 'artisan': ('scavenge', 'forage'),
    'cook': ('forage', 'farm'), 'medic': ('scan', 'research'), 'pharmacist': ('scan', 'research'),
    'firefighter': ('repair', 'water'), 'safety_officer': ('repair', 'water'),
}
NO_JOB_WORK = ('forage', 'scan')
JOB_HOBBY = {'farmer': 'gardening', 'cultivator': 'gardening', 'miner': 'rockwatching', 'technician': 'mechanics', 'engineer': 'mechanics',
             'researcher': 'research', 'courier': 'collecting', 'explorer': 'exploration', 'merchant': 'trading', 'cook': 'cooking',
             'harvester': 'gardening', 'processor': 'scanning', 'artisan': 'collecting', 'medic': 'research', 'pharmacist': 'research'}
HOBBY_PLACE = {'gardening': 'agricultural_district', 'exploration': 'frontier_edge', 'mechanics': 'industrial_ward', 'research': 'research_block',
               'games': 'commons', 'rockwatching': 'frontier_edge', 'cooking': 'residential_ring', 'collecting': 'market_concourse',
               'trading': 'market_concourse', 'scanning': 'research_block'}

# (emoji, place, narration lines). {n} = name, {f} = friend, {h} = hobby, {t} = task.
STORY = {
    'farm': ('🌱', 'agricultural_district', ['{n} tends the fields in the Agricultural District.', '{n} checks the soil row by row, humming to the crops.']),
    'forage': ('🍓', 'agricultural_district', ['{n} forages along the greenhouse edges.', '{n} picks through the wild patches beside the fields.']),
    'harvest': ('🎃', 'agricultural_district', ['{n} brings in the harvest.']),
    'water': ('💧', 'agricultural_district', ['{n} runs the water treatment checks.', '{n} flushes the irrigation lines.']),
    'mine': ('⛏️', 'frontier_edge', ['{n} works an ore seam at the Frontier Edge.', '{n} swings a pick into the rock past the wall.']),
    'scavenge': ('🧰', 'frontier_edge', ['{n} scavenges the scrap fields beyond the wall.', '{n} digs useful parts out of old wreckage.']),
    'repair': ('🔧', 'industrial_ward', ['{n} patches a hissing conduit in the Industrial Ward.', '{n} climbs into a maintenance shaft with a toolkit.']),
    'scan': ('📡', 'research_block', ['{n} sweeps the Siro scanners.', '{n} calibrates sensors on the Research Block roof.']),
    'research': ('🔬', 'research_block', ['{n} runs samples in the Research Block.', '{n} stares at readings nobody else can explain.']),
    'cargo': ('📦', 'spaceport_quarter', ['{n} packs cargo crates at the Spaceport Quarter.']),
    'delivery': ('🦆', 'spaceport_quarter', ['{n} sends a delivery duck off across New Eridian.']),
    'spaceport': ('🚀', 'spaceport_quarter', ['{n} guides a lander onto the pad.', '{n} works the spaceport loading docks.']),
    'explore': ('🧭', 'frontier_edge', ['{n} scouts the ridgeline past the Frontier Edge.', '{n} maps a gully nobody has named yet.']),
    'market': ('🪙', 'market_concourse', ['{n} haggles at the Market Concourse.', '{n} works a market stall, calling out prices.']),
    'eat': ('🍲', 'residential_ring', ['{n} sits down for a proper meal at home.', '{n} raids the pantry.']),
    'sleep': ('🛏️', 'residential_ring', ['{n} turns in for a long sleep.', '{n} falls asleep the moment their head hits the pillow.']),
    'rest': ('😴', 'residential_ring', ['{n} rests at home.', '{n} naps with the lights off.']),
    'relax': ('🛋️', 'residential_ring', ['{n} puts their feet up at home.', '{n} takes a slow, quiet break.']),
    'recover': ('🩹', 'residential_ring', ['{n} takes time to recover.']),
    'walk': ('🌿', 'frontier_edge', ['{n} takes a long walk beyond the habitat blocks.', '{n} wanders the edge of the settlement.']),
    'games': ('🎲', 'commons', ['{n} joins a card game in the Commons.', '{n} loses a board game and demands a rematch.']),
    'hangout': ('🤝', 'commons', ['{n} meets {f} in the Commons.', '{n} and {f} swap stories over tea.']),
    'hi': ('👋', 'commons', ['{n} stops to say hi to {f}.']),
    'hobby': ('🎨', 'commons', ['{n} spends some time on {h}.', '{n} loses track of time practising {h}.']),
    'queue': ('⏱️', 'industrial_ward', ['{n} keeps working through a queue: {t}.']),
    'idle': ('💭', 'residential_ring', ['{n} is at home, thinking.']),
}
PHASE_OPENERS = {'Morning': ['As dawn breaks over Avesta, ', 'Early in the morning, ', ''], 'Day': ['', 'Under the midday light, ', ''],
                 'Evening': ['As the evening settles in, ', 'In the warm evening light, ', ''], 'Night': ['Late into the night, ', 'Under the dark Avesta sky, ', '']}
WEATHER_NOTES = {'spore_drift': ' Siro spores drift past on the wind.', 'dust_winds': ' Dust winds rattle the shutters.',
                 'good_growing': ' The air smells green and alive.', 'quiet_cycle': ' The colony is unusually calm.',
                 'busy_spaceport': ' Landers roar overhead.', 'sensor_noise': ' Every screen in town flickers with odd readings.'}

MOODS = {
    'inspired': ('✨', 'Inspired', .03), 'content': ('🙂', 'Content', .01), 'tired': ('😴', 'Tired', -.01),
    'hungry': ('🍽️', 'Hungry', -.01), 'lonely': ('🫥', 'Lonely', -.01), 'uneasy': ('😟', 'Uneasy', -.01),
    'stressed': ('😣', 'Stressed', -.02), 'miserable': ('😞', 'Miserable', -.04),
}
THOUGHTS = {
    'inspired': ['Everything I touch today just works.', 'I could build a whole district before nightfall.', 'Rocky would be proud of me today.',
                 'Avesta is starting to feel like home.'],
    'content': ['Good day on Avesta.', 'The {place} is starting to feel like home.', 'Not bad for a colony at the edge of nowhere.',
                'Steady work, good company. That is enough.'],
    'tired': ['I could sleep for a whole Avesta day.', 'My eyes keep closing mid-task.', 'One more shift and I am done.'],
    'hungry': ['When did I last eat something real?', 'I would trade a day of pay for a warm meal.', 'My stomach is louder than the spaceport.'],
    'lonely': ['I have not talked to anyone in ages.', 'I miss {friend}.', 'The Commons would do me good.'],
    'uneasy': ['This {weather} makes my skin crawl.', 'Something about the air feels wrong today.', 'I keep checking the Siro readings.'],
    'stressed': ['Too much to do and not enough of me.', 'Nothing is going right today.', 'Why does everything break at once?'],
    'miserable': ['I need a break. A real one.', 'Is this colony even worth it?', 'I cannot keep going like this.'],
}


class SeedlingLife(Base):
    __tablename__ = 'seedling_life_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    enabled = Column(Integer, nullable=False, default=1)
    schedule = Column(String(120), nullable=False, default=DEFAULT_PRESET)
    place = Column(String(32), nullable=False, default='residential_ring')
    activity = Column(String(120), nullable=False, default='Settling in')
    emoji = Column(String(16), nullable=False, default='🏠')
    mood = Column(String(16), nullable=False, default='content')
    thought = Column(String(200), nullable=False, default='')
    hobby = Column(String(24), nullable=False, default='')
    successes = Column(Integer, nullable=False, default=0)
    failures = Column(Integer, nullable=False, default=0)
    cycle = Column(Integer, nullable=False, default=0)
    next_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class SeedlingDiary(Base):
    __tablename__ = 'seedling_diary_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    place = Column(String(32), nullable=False)
    emoji = Column(String(16), nullable=False)
    text = Column(String(400), nullable=False)
    autonomous = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


# ---------------------------------------------------------------- state

def install(m):
    SeedlingLife.__table__.create(m.engine, checkfirst=True)
    SeedlingDiary.__table__.create(m.engine, checkfirst=True)
    try:
        import asyncio
        from discord.ext import tasks
    except Exception:
        return

    @tasks.loop(seconds=60, reconnect=True)
    async def timer():
        try:
            await asyncio.to_thread(tick, m)
        except Exception:
            logging.getLogger(__name__).error('Seedling autonomy pass failed; retrying')

    async def start():
        m.app.state.autonomy_worker = timer.start()

    async def stop():
        timer.stop()
    m.app.add_event_handler('startup', start)
    m.app.add_event_handler('shutdown', stop)


def row(db, channel, uid, create=False):
    found = db.get(SeedlingLife, (channel, uid))
    if found is None and create:
        found = SeedlingLife(channel_id=channel, canonical_uid=uid, enabled=1, schedule=DEFAULT_PRESET, place='residential_ring',
                             activity='Settling in', emoji='🏠', mood='content', thought='', hobby='', successes=0, failures=0, cycle=0)
        db.add(found)
        db.flush()
    return found


def schedule_of(found):
    value = (found.schedule if found is not None else DEFAULT_PRESET) or DEFAULT_PRESET
    if value in PRESETS:
        return dict(zip(PHASES, PRESETS[value][2]))
    try:
        blocks = json.loads(value)
        return {ph: blocks.get(ph, 'free') if blocks.get(ph) in BLOCKS else 'free' for ph in PHASES}
    except ValueError:
        return dict(zip(PHASES, PRESETS[DEFAULT_PRESET][2]))


def preset_name(found):
    value = found.schedule if found is not None else DEFAULT_PRESET
    return PRESETS[value][0] if value in PRESETS else 'Custom'


def set_preset(db, p, key):
    if key not in PRESETS:
        return f"Choose a schedule: {', '.join(PRESETS)}. Nothing changed."
    row(db, p.channel_id, p.twitch_uid, create=True).schedule = key
    name, text, _ = PRESETS[key]
    return f'🗓️ Schedule set to **{name}**: {text}'


def set_phase(db, p, phase, block):
    if phase not in PHASES or block not in BLOCKS:
        return 'Choose a phase and an activity. Nothing changed.'
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    blocks = schedule_of(found)
    blocks[phase] = block
    match = next((k for k, v in PRESETS.items() if dict(zip(PHASES, v[2])) == blocks), None)
    found.schedule = match or json.dumps(blocks)
    return f'🗓️ {phase}: **{BLOCKS[block][1]}**.'


def set_enabled(db, p, on):
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    found.enabled = 1 if on else 0
    if on:
        return ('🌱 Autonomy **on**. While you are away, your Seedling follows its schedule: it works, eats, sleeps, '
                'practises hobbies and meets friends by itself, using the normal game rules.')
    return '✋ Autonomy **off**. Your Seedling waits for you and only does what you tell it.'


def friend_of(m, db, p):
    rel = db.execute(select(m.LifeRelationship).where(m.LifeRelationship.channel_id == p.channel_id,
                                                      (m.LifeRelationship.uid_a == p.twitch_uid) | (m.LifeRelationship.uid_b == p.twitch_uid))
                     .order_by(m.LifeRelationship.familiarity.desc()).limit(1)).scalar_one_or_none()
    if rel is None:
        return None
    other = rel.uid_b if rel.uid_a == p.twitch_uid else rel.uid_a
    return db.execute(select(m.Player).where(m.Player.channel_id == p.channel_id, m.Player.twitch_uid == other)).scalar_one_or_none()


# ---------------------------------------------------------------- mood and thoughts

def mood_of(life, condition_key='', failures=0):
    """(mood key, reason) from needs, morale, weather and how the day is going."""
    levels = {'energy': life.energy, 'nutrition': life.nutrition, 'social': life.social, 'comfort': life.comfort}
    low = sorted((v, k) for k, v in levels.items() if v < 35)
    if min(levels.values()) < 15 or life.morale < 15:
        worst = min(levels, key=levels.get)
        return 'miserable', f'{worst.title()} {levels[worst]}' if levels[worst] < 15 else f'Morale {life.morale}'
    if len(low) >= 2 or failures >= 3:
        return 'stressed', ', '.join(f'{k.title()} {v}' for v, k in low) if len(low) >= 2 else 'Nothing is working out'
    if low:
        value, key = low[0]
        return {'energy': 'tired', 'nutrition': 'hungry', 'social': 'lonely', 'comfort': 'stressed'}[key], f'{key.title()} {value}'
    if condition_key in {'spore_drift', 'dust_winds', 'sensor_noise'} and life.morale < 60:
        return 'uneasy', 'The weather'
    if life.morale >= 70 and min(levels.values()) >= 55:
        return 'inspired', f'Morale {life.morale}, every need looked after'
    return 'content', 'Needs are met'


def thought_for(mood, name='', place='', friend='', weather='', seed=''):
    options = THOUGHTS[mood]
    pick = options[int(hashlib.sha256(f'{seed}:{mood}'.encode()).hexdigest(), 16) % len(options)]
    return pick.format(place=PLACES.get(place, ('home', ''))[0], friend=friend or 'the others', weather=(weather or 'weather').lower())


def mood_modifier(m, db, p, clock=None):
    """Success-chance change from the Seedling's mood, for world_rule_bundle."""
    try:
        life = m.life_state(db, p)
        clock = clock or m.world_clock(db, p.channel_id)
        found = row(db, p.channel_id, p.twitch_uid)
        key, reason = mood_of(life, clock.get('condition_key', ''), found.failures if found else 0)
    except Exception:
        return 0, []
    emoji, label, bonus = MOODS[key]
    if not bonus:
        return 0, []
    return bonus, [f'{emoji} {label} mood {round(bonus * 100):+d}%']


def refresh_mood(m, db, p, found, clock=None, life=None):
    life = life or m.life_state(db, p)
    clock = clock or m.world_clock(db, p.channel_id)
    key, reason = mood_of(life, clock.get('condition_key', ''), found.failures)
    friend = friend_of(m, db, p) if key == 'lonely' else None
    found.mood = key
    found.thought = thought_for(key, p.display_name, found.place, friend.display_name if friend else '', clock.get('condition', ''),
                                f"{p.twitch_uid}:{clock.get('day')}:{clock.get('phase')}")
    return key, reason


# ---------------------------------------------------------------- deciding what to do

def identity_for(m, db, p):
    ident = db.execute(select(m.Identity).where(m.Identity.channel_id == p.channel_id, m.Identity.canonical_uid == p.twitch_uid)
                       .order_by(m.Identity.id)).scalars().first()
    if ident is not None:
        return ident.provider, ident.provider_uid
    if p.twitch_uid.startswith('discord:'):
        return 'discord', p.twitch_uid.split(':', 1)[1]
    return 'twitch', p.twitch_uid


def favourite_hobby(m, db, p, found):
    if found.hobby:
        return found.hobby
    points = {h: m.hobby_points(db, p, h) for h in m.HOBBIES}
    best = max(points, key=points.get) if points and max(points.values()) > 0 else JOB_HOBBY.get(p.job, 'games')
    found.hobby = best
    return best


def plan(m, db, p, found, life, clock):
    """What the Seedling does now: a dict with 'kind' and, for game actions, the call to make."""
    block = schedule_of(found)[clock['phase']]
    sleep_ready = not m.action_wait(db, p, 'sleep')
    # Needs come first, whatever the schedule says.
    if life.nutrition < 35:
        return {'kind': 'eat', 'call': ('eat_full', {})}
    if life.energy < 25 or life.comfort < 20:
        if sleep_ready:
            return {'kind': 'sleep', 'call': ('action', {'action': 'sleep'})}
        return {'kind': 'relax', 'call': ('relax', {})}
    if block == 'sleep':
        if sleep_ready and (life.energy < 90 or life.comfort < 90):
            return {'kind': 'sleep', 'call': ('action', {'action': 'sleep'})}
        return {'kind': 'rest'}
    if life.social < 25 and block != 'work':
        return social_plan(m, db, p) or {'kind': 'games', 'call': ('games', {})}
    if block == 'work':
        if needs.blocked_needs(life):
            return {'kind': 'recover', 'call': ('recover_needs', {})}
        jobs = JOB_WORK.get(p.job, NO_JOB_WORK)
        act = jobs[found.cycle % len(jobs)]
        found.cycle += 1
        return {'kind': act, 'call': ('action', {'action': act})}
    if block == 'social':
        return social_plan(m, db, p) or {'kind': 'games', 'call': ('games', {})}
    # Free time: a hobby most of the time, sometimes a walk or a rest.
    preferred = m.colony_seedling(db, p).preferred_activity
    roll = random.random()
    if roll < .55:
        hobby = favourite_hobby(m, db, p, found)
        return {'kind': 'hobby', 'hobby': hobby, 'call': ('hobby', {'hobby': hobby})}
    if roll < .75:
        return {'kind': 'walk', 'call': ('walk', {})}
    if preferred == 'games' or roll < .88:
        return {'kind': 'games', 'call': ('games', {})}
    return {'kind': 'relax', 'call': ('relax', {})}


def social_plan(m, db, p):
    friend = friend_of(m, db, p)
    if friend is None:
        others = db.execute(select(m.Player).where(m.Player.channel_id == p.channel_id, m.Player.twitch_uid != p.twitch_uid,
                                                   m.Player.last_seen >= m.now() - timedelta(days=ACTIVE_DAYS)).limit(20)).scalars().all()
        if not others:
            return None
        friend = random.choice(others)
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    if m.action_wait(db, p, 'hangout'):
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    return {'kind': 'hangout', 'friend': friend.display_name, 'call': ('hangout', {'target': friend.display_name})}


def failed(m, text):
    text = str(text or '').strip()
    return (not text or m.discord_message_status(text) in {'failure', 'cooldown'} or 'Nothing spent' in text or 'Nothing was spent' in text
            or text.startswith(('🔒', '⏱️', '⛔', '❌', '⚠️', 'ℹ️')))


def narrate(kind, name, clock, place='', friend='', hobby='', task='', ok=True, reason='', seed=''):
    emoji, default_place, lines = STORY.get(kind, STORY['idle'])
    rnd = random.Random(seed)
    line = rnd.choice(lines).format(n=name, f=friend or 'a neighbour', h=hobby or 'a hobby', t=task or 'a task')
    if not ok:
        line += ' ' + (reason if reason else 'It does not go to plan.')
    opener = rnd.choice(PHASE_OPENERS.get(clock.get('phase'), ['']))
    if opener:
        text = opener + (line if line.startswith(name) else line[0].lower() + line[1:])
    else:
        text = line
    if ok and rnd.random() < .35:
        text += WEATHER_NOTES.get(clock.get('condition_key', ''), '')
    return emoji, place or default_place, text


def short_reason(text):
    """The game's own words for what went wrong, e.g. 'It does not go well: Pax has a rough farming shift.'"""
    first = str(text or '').replace('\n', ' ').split(' | ')[0].split('. ')[0]
    first = first.split(' · ')[-1] if ' · ' in first else first
    first = first.lstrip('🔒⏱️⛔❌⚠️ℹ️✖️ ').replace('*', '').strip()
    return ('It does not go well: ' + first[:90].rstrip('.') + '.') if first else ''


# ---------------------------------------------------------------- the worker

def tick(m):
    """Let every due Seedling do one thing."""
    now = m.now()
    with m.SessionLocal() as db:
        recent = db.execute(select(m.Player.channel_id, m.Player.twitch_uid).where(m.Player.last_seen >= now - timedelta(days=ACTIVE_DAYS))).all()
        known = {(r.channel_id, r.canonical_uid): r for r in db.scalars(select(SeedlingLife))}
        due = []
        for channel, uid in recent:
            found = known.get((channel, uid))
            if found is None:
                found = row(db, channel, uid, create=True)
                found.next_at = now + timedelta(seconds=random.randint(30, AUTONOMY_MINUTES * 60))
            elif found.enabled and (found.next_at is None or m.as_utc(found.next_at) <= now):
                due.append((channel, uid))
        db.commit()
    for channel, uid in due[:BATCH]:
        try:
            live_one(m, channel, uid)
        except Exception:
            logging.getLogger(__name__).exception('Seedling step failed for one citizen; it will try again later')
            with m.SessionLocal() as db:
                found = db.get(SeedlingLife, (channel, uid))
                if found is not None:
                    found.next_at = m.now() + timedelta(minutes=AUTONOMY_MINUTES)
                    db.commit()


def live_one(m, channel, uid, force=False):
    """One autonomous step for one Seedling. Returns the diary text, or '' when it stepped aside."""
    with m.SessionLocal() as db:
        p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == uid)).scalar_one_or_none()
        found = row(db, channel, uid, create=True)
        found.next_at = m.now() + timedelta(seconds=AUTONOMY_MINUTES * 60 + random.randint(-60, 60))
        if p is None or (not found.enabled and not force):
            db.commit()
            return ''
        clock = m.world_clock(db, channel)
        life = m.life_state(db, p)
        queue = db.get(m.task_queue.TaskQueue, (channel, uid))
        last_seen = p.last_seen
        if queue is not None and queue.state in m.task_queue.ACTIVE:
            # A running queue is the Seedling's work right now; just say so.
            label = m.task_queue.choices(m).get(queue.task, queue.task)
            place = task_place(queue.task)
            changed = found.activity != f'Queue: {label}'
            found.activity, found.place, found.emoji = f'Queue: {label}', place, '⏱️'
            refresh_mood(m, db, p, found, clock, life)
            if changed:
                _, _, text = narrate('queue', p.display_name, clock, place, task=label, seed=f'{uid}:{m.now().isoformat()}')
                diary(m, db, p, place, '⏱️', text)
            db.commit()
            return ''
        if not force and last_seen and m.now() - m.as_utc(last_seen) < timedelta(minutes=AWAY_MINUTES):
            # The player is here: the Seedling follows them instead of acting.
            refresh_mood(m, db, p, found, clock, life)
            db.commit()
            return ''
        step = plan(m, db, p, found, life, clock)
        provider, provider_uid = identity_for(m, db, p)
        name = p.display_name
        db.commit()
    result = ''
    if step.get('call'):
        fn_name, kwargs = step['call']
        fn = getattr(m, fn_name)
        token = ACTING.set(True)
        try:
            if fn_name == 'action':
                kwargs = dict(kwargs, msg=f'auto-{uid}-{m.now().timestamp()}')
            response = fn(channel=channel, uid=provider_uid, name=name, provider=provider, **kwargs)
            result = response.body.decode() if hasattr(response, 'body') else str(response)
        finally:
            ACTING.reset(token)
    with m.SessionLocal() as db:
        p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == uid)).scalar_one()
        p.last_seen = last_seen            # autonomous steps do not count as the player being active
        found = row(db, channel, uid, create=True)
        ok = not step.get('call') or not failed(m, result)
        if step.get('call'):
            if ok:
                found.successes, found.failures = found.successes + 1, 0
            else:
                found.failures += 1
        kind = step['kind']
        place = HOBBY_PLACE.get(step.get('hobby', ''), '') if kind == 'hobby' else ''
        clock = m.world_clock(db, channel)
        emoji, place, text = narrate(kind, p.display_name, clock, place, step.get('friend', ''), (m.HOBBIES.get(step.get('hobby', ''), ('',))[0] or step.get('hobby', '')),
                                     ok=ok, reason=short_reason(result) if not ok else '', seed=f'{uid}:{m.now().isoformat()}')
        found.place, found.emoji = place, emoji
        found.activity = activity_label(kind, step, ok)
        found.updated_at = m.now()
        refresh_mood(m, db, p, found, clock)
        diary(m, db, p, place, emoji, text)
        db.commit()
        return text


def activity_label(kind, step, ok):
    labels = {'eat': 'Eating', 'sleep': 'Sleeping', 'rest': 'Resting at home', 'relax': 'Relaxing', 'recover': 'Recovering',
              'walk': 'Out for a walk', 'games': 'Playing games', 'hangout': f"With {step.get('friend', 'a friend')}",
              'hi': f"Saying hi to {step.get('friend', 'someone')}", 'hobby': f"Hobby: {step.get('hobby', '').title()}", 'idle': 'Thinking'}
    label = labels.get(kind, f'Working: {kind.title()}')
    return label if ok else label + ' · rough going'


def task_place(task):
    kind, _, key = task.partition(':')
    if kind == 'mine':
        return 'frontier_edge'
    if kind == 'gather':
        return 'agricultural_district' if any(w in key for w in ('berr', 'herb', 'corn', 'pumpkin', 'wheat')) else 'frontier_edge'
    return 'industrial_ward'


def diary(m, db, p, place, emoji, text, autonomous=True):
    db.add(SeedlingDiary(channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=p.display_name[:64], place=place, emoji=emoji,
                         text=text[:400], autonomous=int(autonomous), created_at=m.now()))
    db.flush()
    old = list(db.scalars(select(SeedlingDiary.id).where(SeedlingDiary.channel_id == p.channel_id, SeedlingDiary.canonical_uid == p.twitch_uid)
                          .order_by(SeedlingDiary.id.desc()).offset(DIARY_KEEP)))
    if old:
        db.execute(delete(SeedlingDiary).where(SeedlingDiary.id.in_(old)))


def merge(db, channel, source, target):
    src, dst = db.get(SeedlingLife, (channel, source)), db.get(SeedlingLife, (channel, target))
    if src is not None:
        if dst is None:
            db.add(SeedlingLife(channel_id=channel, canonical_uid=target, enabled=src.enabled, schedule=src.schedule, place=src.place,
                                activity=src.activity, emoji=src.emoji, mood=src.mood, thought=src.thought, hobby=src.hobby,
                                successes=0, failures=0, cycle=0))
        db.delete(src)
    for entry in db.scalars(select(SeedlingDiary).where(SeedlingDiary.channel_id == channel, SeedlingDiary.canonical_uid == source)):
        entry.canonical_uid = target


# ---------------------------------------------------------------- views

def entries(db, p, limit=10, since=None):
    query = select(SeedlingDiary).where(SeedlingDiary.channel_id == p.channel_id, SeedlingDiary.canonical_uid == p.twitch_uid)
    if since is not None:
        query = query.where(SeedlingDiary.created_at >= since)
    return list(db.scalars(query.order_by(SeedlingDiary.id.desc()).limit(limit)))


def view_text(m, db, p, provider='discord'):
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    clock = m.world_clock(db, p.channel_id)
    life = m.life_state(db, p)
    key, reason = refresh_mood(m, db, p, found, clock, life)
    emoji, label, bonus = MOODS[key]
    blocks = schedule_of(found)
    now_block = blocks[clock['phase']]
    place = PLACES.get(found.place, PLACES['residential_ring'])
    if provider != 'discord':
        return (f"🌱 {p.display_name}: {emoji} {label} — \"{found.thought}\" | {found.emoji} {found.activity} · {place[0]} | "
                f"{clock['phase']}: {BLOCKS[now_block][1]} ({preset_name(found)}) | Autonomy {'on' if found.enabled else 'off'} | !diary · !schedule <preset>")
    sched = ' · '.join(f"{ph} {BLOCKS[b][0]}" for ph, b in blocks.items())
    lines = [f'🌱 YOUR SEEDLING — {p.display_name.upper()}',
             f'{emoji} **{label}** · {reason}' + (f' · {round(bonus * 100):+d}% success' if bonus else ''),
             f'💭 *"{found.thought}"*', '',
             'RIGHT NOW', f"{found.emoji} {found.activity} · {place[1]} {place[0]}",
             f"{clock['phase_emoji']} {clock['phase']} on Avesta: **{BLOCKS[now_block][1]}** time", '',
             'SCHEDULE', f'{preset_name(found)} — {sched}', '',
             'AUTONOMY', ('On: while you are away, your Seedling follows this schedule and lives by the normal game rules '
                          f'(about one action every {AUTONOMY_MINUTES} minutes). It steps aside while you play or a queue runs.')
             if found.enabled else 'Off: your Seedling waits for you.']
    recent = entries(db, p, 3)
    if recent:
        lines += ['', 'LATELY'] + [f'{e.emoji} {e.text}' for e in recent]
    return '\n'.join(lines)


def diary_text(m, db, p, provider='discord'):
    rows = entries(db, p, 12 if provider == 'discord' else 3)
    if provider != 'discord':
        return '📓 ' + (' | '.join(e.text for e in rows) if rows else f'{p.display_name}\'s diary is empty so far.')
    lines = [f'📓 DIARY — {p.display_name.upper()}', 'What your Seedling has been doing, newest first.', '']
    for e in rows:
        lines.append(f'{e.emoji} {e.text} · <t:{int(m.as_utc(e.created_at).timestamp())}:R>')
    if not rows:
        lines.append('Nothing yet. With autonomy on, your Seedling writes here as it lives its day.')
    return '\n'.join(lines)


def away_lines(m, db, p, since, limit=3):
    """Diary lines written since `since`, for the welcome-back summary."""
    rows = [e for e in entries(db, p, 40, since) if e.autonomous]
    if not rows:
        return []
    shown = [f'{e.emoji} {e.text}' for e in rows[:limit]]
    extra = len(rows) - len(shown)
    return ['📓 **While you were away:**'] + shown + ([f'…and {extra} more in your diary.'] if extra > 0 else [])


def status_line(m, db, p):
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    key, _ = refresh_mood(m, db, p, found)
    emoji, label, _ = MOODS[key]
    return f'{emoji} {label} · {found.emoji} {found.activity} · 💭 "{found.thought}"'


# ---------------------------------------------------------------- the stream

def overlay_data(m, db, source_ids):
    since = m.now() - timedelta(days=ACTIVE_DAYS)
    players = list(db.scalars(select(m.Player).where(m.Player.channel_id.in_(source_ids), m.Player.last_seen >= since)
                              .order_by(m.Player.last_seen.desc()).limit(40)))
    lives = {(r.channel_id, r.canonical_uid): r for r in db.scalars(select(SeedlingLife).where(SeedlingLife.channel_id.in_(source_ids)))}
    seedlings = []
    for p in players:
        found = lives.get((p.channel_id, p.twitch_uid))
        place = found.place if found is not None and found.place in PLACES else 'residential_ring'
        mood = found.mood if found is not None and found.mood in MOODS else 'content'
        seedlings.append({'id': hashlib.sha1(f'{p.channel_id}:{p.twitch_uid}'.encode()).hexdigest()[:10], 'name': p.display_name,
                          'place': place, 'place_name': PLACES[place][0], 'activity': found.activity if found else 'Settling in',
                          'emoji': found.emoji if found else '🏠', 'mood': MOODS[mood][1], 'mood_emoji': MOODS[mood][0],
                          'thought': found.thought if found else ''})
    rows = list(db.scalars(select(SeedlingDiary).where(SeedlingDiary.channel_id.in_(source_ids)).order_by(SeedlingDiary.id.desc()).limit(14)))
    narration = [{'id': e.id, 'name': e.name, 'emoji': e.emoji, 'text': e.text, 'place': PLACES.get(e.place, ('', ''))[0],
                  'at': m.as_utc(e.created_at).isoformat()} for e in rows]
    return {'seedlings': seedlings, 'narration': narration, 'places': {k: v[0] for k, v in PLACES.items()}}
