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

# What each job works at: gathering real materials, or its job task. The Seedling rotates
# through these; when the player has a goal, materials the goal still needs come first.
JOB_WORK = {
    'farmer': ('Pumpkin', 'Corn', 'Tomato', 'Berries', 'act:farm'), 'cultivator': ('Pumpkin', 'Corn', 'Tomato', 'Berries', 'act:farm'),
    'cook': ('Berries', 'Herbs', 'Mushroom', 'Corn', 'Nuts'), 'harvester': ('Lumber', 'Berries', 'Flaxa', 'Herbs'),
    'miner': ('Hematite Ore', 'Coal', 'Stone', 'Chalcopyrite Ore', 'Bauxite Ore'), 'explorer': ('Lumber', 'Stone', 'Nuts', 'act:explore', 'Mushroom'),
    'technician': ('Lumber', 'Stone', 'Clay', 'act:repair'), 'engineer': ('Stone', 'Clay', 'Lumber', 'act:repair'),
    'artisan': ('Clay', 'Lumber', 'Flaxa', 'Stone'), 'processor': ('Murky Water (1000ml)', 'Raw Algae', 'act:water'),
    'researcher': ('Herbs', 'act:research', 'Tube Fungus', 'act:scan'), 'medic': ('Herbs', 'Golden Cap', 'act:scan'),
    'pharmacist': ('Herbs', 'Golden Cap', 'Web Fungus', 'act:research'), 'firefighter': ('Murky Water (1000ml)', 'Stone', 'act:repair'),
    'safety_officer': ('Murky Water (1000ml)', 'Stone', 'act:repair'), 'courier': ('act:cargo', 'act:delivery', 'Lumber', 'act:spaceport'),
    'merchant': ('act:market', 'Berries', 'act:market', 'Lumber'),
}
NO_JOB_WORK = ('Berries', 'Lumber', 'Stone', 'Herbs')
JOB_HOBBY = {'farmer': 'gardening', 'cultivator': 'gardening', 'miner': 'rockwatching', 'technician': 'mechanics', 'engineer': 'mechanics',
             'researcher': 'research', 'courier': 'collecting', 'explorer': 'exploration', 'merchant': 'trading', 'cook': 'cooking',
             'harvester': 'gardening', 'processor': 'scanning', 'artisan': 'collecting', 'medic': 'research', 'pharmacist': 'research'}
HOBBY_PLACE = {'gardening': 'agricultural_district', 'exploration': 'frontier_edge', 'mechanics': 'industrial_ward', 'research': 'research_block',
               'games': 'commons', 'rockwatching': 'frontier_edge', 'cooking': 'residential_ring', 'collecting': 'market_concourse',
               'trading': 'market_concourse', 'scanning': 'research_block'}
# Job tasks: (news desk, place, what they did).
TASKS = {
    'farm': ('FARMING', 'agricultural_district', 'tended the fields'), 'water': ('UTILITIES', 'agricultural_district', 'ran the water treatment checks'),
    'repair': ('INFRASTRUCTURE', 'industrial_ward', 'carried out repairs on the settlement'), 'research': ('RESEARCH', 'research_block', 'logged a research session'),
    'scan': ('RESEARCH', 'research_block', 'completed a Siro scan'), 'cargo': ('LOGISTICS', 'spaceport_quarter', 'packed cargo for shipment'),
    'delivery': ('LOGISTICS', 'spaceport_quarter', 'sent a delivery duck across New Eridian'), 'spaceport': ('LOGISTICS', 'spaceport_quarter', 'worked the spaceport docks'),
    'explore': ('FRONTIER', 'frontier_edge', 'scouted the land past the wall'), 'market': ('TRADE', 'market_concourse', 'worked the market stalls'),
}
PLACE_OF_BRANCH = {'ore_mining': 'frontier_edge', 'stone_quarrying': 'frontier_edge', 'wood_harvesting': 'frontier_edge',
                   'botanical_harvesting': 'agricultural_district', 'water_collection': 'agricultural_district'}
# Needs are looked after before they get low enough to stop work.
LOW = {'nutrition': 45, 'energy': 35, 'comfort': 30, 'social': 30}
WHEN = {'Morning': 'this morning', 'Day': 'today', 'Evening': 'this evening', 'Night': 'tonight'}
EMOJI = {'gather': '🧺', 'mine': '⛏️', 'eat': '🍲', 'sleep': '🛏️', 'relax': '🛋️', 'games': '🎲', 'hangout': '🤝', 'hi': '👋', 'hobby': '🎨',
         'walk': '🌿', 'recover': '🩹', 'queue': '⏱️', 'rest': '😴', 'farm': '🌱', 'water': '💧', 'repair': '🔧', 'research': '🔬', 'scan': '📡',
         'cargo': '📦', 'delivery': '🦆', 'spaceport': '🚀', 'explore': '🧭', 'market': '🪙'}
# District growth on the map: the society stat each district grows with, and the society tier that settles it.
GROWTH = {'commons': (None, 0), 'residential_ring': ('population', 0), 'agricultural_district': ('food', 0), 'frontier_edge': ('development', 0),
          'industrial_ward': ('materials', 1), 'market_concourse': ('treasury', 1), 'research_block': ('knowledge', 2), 'spaceport_quarter': ('reputation', 3)}

MOODS = {
    'inspired': ('✨', 'Inspired', .03), 'content': ('🙂', 'Content', .01), 'tired': ('😴', 'Tired', -.01),
    'hungry': ('🍽️', 'Hungry', -.01), 'lonely': ('🫥', 'Lonely', -.01), 'uneasy': ('😟', 'Uneasy', -.01),
    'stressed': ('😣', 'Stressed', -.02), 'miserable': ('😞', 'Miserable', -.04),
}
THOUGHTS = {
    'inspired': ['Everything I touch today just works.', 'I could build a whole district before nightfall.', 'Rocky would be proud of me today.',
                 'Avesta is starting to feel like home.', 'Give me a hammer and a reason. I am unstoppable.', 'I have ideas for days.',
                 'Someone write this day down. It is a good one.', 'I feel like I could outrun a dust wind.'],
    'content': ['Good day on Avesta.', 'The {place} is starting to feel like home.', 'Not bad for a colony at the edge of nowhere.',
                'Steady work, good company. That is enough.', 'Fed, rested and busy. Life is fine.', 'Nothing to complain about. Weird.',
                'I like the hum of this place.', 'One brick at a time, that is how colonies get built.'],
    'tired': ['I could sleep for a whole Avesta day.', 'My eyes keep closing mid-task.', 'One more shift and I am done.',
              'Is it bedtime yet? It feels like bedtime.', 'I yawned so hard I scared a duck.', 'Coffee. Or Siro tea. Anything.'],
    'hungry': ['When did I last eat something real?', 'I would trade a day of pay for a warm meal.', 'My stomach is louder than the spaceport.',
               'I can smell the kitchens from here.', 'Berries. I am thinking about berries.', 'Food first, heroics later.'],
    'lonely': ['I have not talked to anyone in ages.', 'I miss {friend}.', 'The Commons would do me good.',
               'Anyone want to grab a meal?', 'It is quiet out here. Too quiet.', 'Maybe {friend} is free later.'],
    'uneasy': ['This {weather} makes my skin crawl.', 'Something about the air feels wrong today.', 'I keep checking the Siro readings.',
               'Did anyone else hear that?', 'I will feel better indoors.', 'Stay close to the wall today.'],
    'stressed': ['Too much to do and not enough of me.', 'Nothing is going right today.', 'Why does everything break at once?',
                 'Deep breaths. Deep breaths.', 'I need five minutes. Just five.', 'Who scheduled all of this?'],
    'miserable': ['I need a break. A real one.', 'Is this colony even worth it?', 'I cannot keep going like this.',
                  'Someone tell me tomorrow is better.', 'I just want a warm bed and a hot meal.'],
}
# What Seedlings say on the stream map, beyond their mood: about what they are doing,
# where they are, the time of day, the weather, the society, the market, a holiday and each other.
SAY_DOING = {
    'Gathering': ['Another basket of {item} for the stores.', 'This {item} will not gather itself.', 'Good {item} out here today.',
                  'Somebody in New Eridian needs this {item}.', 'Almost a full load of {item}.'],
    'Eating': ['Mm. Real food.', 'Eating first. Saving the colony second.', 'Pass the salt, would you?', 'Best meal all week.'],
    'Sleeping': ['Zzz…', 'Five more minutes…', 'Dreaming of a bigger New Eridian.'],
    'Resting': ['Feet up, just for a bit.', 'A quiet hour at home.'],
    'Relaxing': ['Just watching the clouds go by.', 'This is what days off are for.', 'Recharging. Do not disturb.'],
    'Recovering': ['Patching myself up.', 'Back on my feet soon.'],
    'Out for a walk': ['Nice day for a walk.', 'Stretching my legs around the {place}.', 'I never noticed that building before.'],
    'Playing games': ['Best of three?', 'I am definitely winning this one.', 'Who taught you that move?'],
    'With': ['Did you hear about the signal below?', 'Tell me everything.', 'We should do this more often.'],
    'Saying hi': ['Hey there! How is the shift going?', 'Good to see a friendly face.', 'Long time no see!'],
    'Hobby': ['A little {hobby} clears the head.', 'Getting better at {hobby} every day.', 'Nobody bother me, it is {hobby} time.'],
    'Working': ['On the clock. Back soon.', 'Somebody has to keep this place running.', 'Nearly done with this shift.'],
    'Waiting': ['Waiting on things out of my hands.', 'Hurry up and wait, colony life.'],
}
SAY_PLACE = {
    'residential_ring': ['Home sweet home.', 'The neighbours are painting again.', 'More houses going up every week.'],
    'agricultural_district': ['The crops look thirsty.', 'Fresh soil smells like hope.', 'Watch where you step, new seedlings.'],
    'industrial_ward': ['Loud in here. Good loud.', 'The furnaces never sleep.', 'Mind the sparks.'],
    'research_block': ['The readings are strange today.', 'Do not touch anything glowing.', 'Science waits for no one.'],
    'market_concourse': ['Prices are moving fast today.', 'Fresh stock at the stalls!', 'I love a good bargain.'],
    'spaceport_quarter': ['Another shuttle on the pad.', 'One day I will fly out of here.', 'Cargo is stacking up fast.'],
    'frontier_edge': ['The wilds go on forever.', 'Stay inside the markers.', 'Found tracks out here. Big ones.'],
    'commons': ['Best spot in New Eridian.', 'The fountain is running again.', 'Everyone ends up at the Commons.'],
}
SAY_PHASE = {'Morning': ['Morning, Avesta!', 'Up early and ready.', 'First light is the best light.'],
             'Day': ['Middle of the day and going strong.', 'Hot one today.'],
             'Evening': ['Look at that sunset.', 'Winding down soon.', 'Lamps are coming on.'],
             'Night': ['The stars are out.', 'Quiet night in New Eridian.', 'Who is still up?']}
SAY_WEATHER = {
    'clear_skies': ['Not a cloud in the sky.', 'Perfect weather for work.'],
    'good_growing': ['Rain on the fields. The farmers will be happy.', 'Everything is growing like mad.'],
    'spore_drift': ['Masks on, the Siro is drifting.', 'Green specks everywhere today.'],
    'dust_winds': ['Dust in my teeth again.', 'Hold onto your hat, the wind is up.'],
    'busy_spaceport': ['Shuttles all day long.', 'The spaceport is packed.'],
    'water_watch': ['Save water, everyone.', 'Every drop counts today.'],
    'quiet_cycle': ['So calm today.', 'A good day to catch up with friends.'],
    'sensor_noise': ['The sensors keep beeping at nothing.', 'Research says the noise is normal. Sure.'],
}
SAY_HOLIDAY = {
    'New Year': ['Any resolutions?', 'Save me a spot for the fireworks!', 'This year New Eridian gets bigger.'],
    "Valentine's Day": ['Someone left flowers at the fountain.', 'Love is in the Avesta air.', 'Who is your valentine?'],
    'Memorial Day': ['We remember the first settlers.', 'Flags up across the colony.'],
    "Father's Day": ['Thanks to every mentor out there.', 'The grill is on at the Commons.'],
    'Independence Day': ['Fireworks tonight!', 'Red, white and blue everywhere.', 'Happy Independence Day!'],
    'Labor Day': ['A day off for the hardest workers.', 'Here is to every shift we ever pulled.'],
    'Halloween': ['Did that pumpkin just move?', 'Trick or treat!', 'I am going as a Siro spore.', 'Boo!'],
    'Thanksgiving': ['So thankful for this colony.', 'Save me some pie.', 'The feast is almost ready.'],
    'Christmas': ['Merry Christmas, New Eridian!', 'Look at the lights on the tree!', 'I wrapped a present for everyone.'],
}
SAY_TO = ['Hey {other}!', '{other}, over here!', 'Nice work today, {other}.', '{other}, race you to the Commons?', 'Morning, {other}.']


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
    """One news report per Seedling step: a desk (FARMING, SUPPLY, HEALTH…), a headline and the story."""
    __tablename__ = 'seedling_news_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    place = Column(String(32), nullable=False)
    emoji = Column(String(16), nullable=False)
    desk = Column(String(24), nullable=False, default='COLONY')
    headline = Column(String(160), nullable=False, default='')
    text = Column(String(400), nullable=False)
    autonomous = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


class SeedlingHaul(Base):
    """Exactly what one autonomous step brought in, spent and ate, so summaries can add it all up."""
    __tablename__ = 'seedling_haul_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    canonical_uid = Column(String(96), nullable=False, index=True)
    gained = Column(String(2000), nullable=False, default='{}')
    used = Column(String(2000), nullable=False, default='{}')
    sc = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


HAUL_KEEP = 400      # steps remembered per Seedling for totals (about four days of autonomy)


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


# ---------------------------------------------------------------- deciding what to do

def ready(m, db, p, action):
    return not m.action_wait(db, p, action)


def needs_plan(m, db, p, life, block):
    """Look after the lowest need first, before it gets low enough to stop work. None when all are fine."""
    low = sorted((getattr(life, k) / LOW[k], k) for k in LOW if getattr(life, k) < LOW[k])
    for _, need in low:
        if need == 'nutrition' and ready(m, db, p, 'eat'):
            return {'kind': 'eat', 'need': need, 'call': ('eat_full', {})}
        if need == 'energy':
            if ready(m, db, p, 'sleep'):
                return {'kind': 'sleep', 'need': need, 'call': ('action', {'action': 'sleep'})}
            if ready(m, db, p, 'relax'):
                return {'kind': 'relax', 'need': need, 'call': ('relax', {})}
        if need == 'comfort':
            if ready(m, db, p, 'relax'):
                return {'kind': 'relax', 'need': need, 'call': ('relax', {})}
            if life.comfort < 20 and ready(m, db, p, 'sleep'):
                return {'kind': 'sleep', 'need': need, 'call': ('action', {'action': 'sleep'})}
        if need == 'social':
            friendly = social_plan(m, db, p)
            if friendly is not None:
                return dict(friendly, need=need)
            if ready(m, db, p, 'games'):
                return {'kind': 'games', 'need': need, 'call': ('games', {})}
    if low and needs.blocked_needs(life):
        return {'kind': 'recover', 'need': low[0][1], 'call': ('recover_needs', {})}
    return None


def gather_key(m, name):
    from . import seed_content as s, crafting_progression as cp
    key = s.find_item(name)
    return key if key in s.GATHER and key not in cp.RARE else None


def goal_material(m, db, p):
    """A natural material the player's goal still needs, if any."""
    try:
        e = m.extras.goal_entry(m, db, p)
        if e is None:
            return None
        from . import workbench as wb
        _, raw = m.extras.plan(wb.Context(m, db, p), e)
        return next((gather_key(m, m.resource_name(k)) for k in raw if gather_key(m, m.resource_name(k))), None)
    except Exception:
        return None


def work_plan(m, db, p, found):
    wanted = goal_material(m, db, p)
    if wanted:
        return {'kind': 'gather', 'item': wanted, 'goal': True}
    options = JOB_WORK.get(p.job, NO_JOB_WORK)
    for _ in range(len(options)):
        choice = options[found.cycle % len(options)]
        found.cycle += 1
        if choice.startswith('act:'):
            act = choice[4:]
            return {'kind': act, 'call': ('action', {'action': act})}
        key = gather_key(m, choice)
        if key:
            return {'kind': 'gather', 'item': key}
    return {'kind': 'gather', 'item': gather_key(m, 'Lumber')}


def plan(m, db, p, found, life, clock):
    """What the Seedling does now: a dict with 'kind', and 'call' or 'item' for game actions."""
    block = schedule_of(found)[clock['phase']]
    if block == 'sleep' and ready(m, db, p, 'sleep') and (life.energy < 90 or life.comfort < 90):
        return {'kind': 'sleep', 'call': ('action', {'action': 'sleep'})}
    step = needs_plan(m, db, p, life, block)
    if step is not None:
        return step
    if block == 'sleep':
        return {'kind': 'rest'}
    if block == 'work':
        return work_plan(m, db, p, found)
    if block == 'social':
        return social_plan(m, db, p) or {'kind': 'games', 'call': ('games', {})}
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
        if not others or not ready(m, db, p, 'hi'):
            return None
        friend = random.choice(others)
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    if ready(m, db, p, 'hangout'):
        return {'kind': 'hangout', 'friend': friend.display_name, 'call': ('hangout', {'target': friend.display_name})}
    if ready(m, db, p, 'hi'):
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    return None


# ---------------------------------------------------------------- what actually changed

NEEDS = ('energy', 'nutrition', 'social', 'comfort', 'morale')
LEGACY = ('crops', 'ore', 'rare_ore', 'components', 'cargo')


def snapshot(m, db, p):
    from .competencies import FIELDS
    life = m.life_state(db, p)
    branches = {r.branch: r.xp for r in db.scalars(select(m.SkillBranch).where(m.SkillBranch.channel_id == p.channel_id,
                                                                                 m.SkillBranch.canonical_uid == p.twitch_uid))}
    return {'stock': dict(m.task_queue.inventory_snapshot(m, db, p)), 'sc': p.sc, 'legacy': {k: getattr(p, k) for k in LEGACY},
            'needs': {k: getattr(life, k) for k in NEEDS}, 'xp': {k: getattr(p, f) for k, f in FIELDS.items()}, 'branches': branches}


def changes(m, before, after):
    gained = {k: n - before['stock'].get(k, 0) for k, n in after['stock'].items() if n > before['stock'].get(k, 0)}
    used = {k: before['stock'][k] - after['stock'].get(k, 0) for k in before['stock'] if after['stock'].get(k, 0) < before['stock'][k]}
    for k in LEGACY:
        delta = after['legacy'][k] - before['legacy'][k]
        if delta > 0 and m.resource_name(k) not in {m.resource_name(x) for x in gained}:
            gained[k] = delta
    practice = {}
    for k, v in after['xp'].items():
        if v > before['xp'].get(k, 0):
            practice[m.SKILL_LABELS.get(k, k.title())] = v - before['xp'].get(k, 0)
    for k, v in after['branches'].items():
        if v > before['branches'].get(k, 0):
            practice[k.replace('_', ' ').title()] = practice.get(k.replace('_', ' ').title(), 0) + v - before['branches'].get(k, 0)
    needs_delta = {k: (before['needs'][k], after['needs'][k]) for k in NEEDS if after['needs'][k] != before['needs'][k]}
    return {'gained': gained, 'used': used, 'sc': after['sc'] - before['sc'], 'practice': practice, 'needs': needs_delta}


def clean_name(name):
    """'Kamex [New Eridian Official]' reads as 'Kamex' in the news."""
    import re
    return re.sub(r'\s*[\[(][^\])]*[\])]', '', str(name or '')).strip() or str(name or 'A citizen')


def clean_reason(text):
    """The game's own reason in one plain sentence, without headers, emoji or markup."""
    import re
    for line in str(text or '').replace(' | ', '\n').splitlines():
        line = re.sub(r'[*_`]', '', line).strip()
        line = re.sub(r'^[^\w(]+', '', line).strip()
        if not line or (line.upper() == line and not any(ch.isdigit() for ch in line)) or line[0] in '+-−0123456789':
            continue            # skip headers such as "TASK FAILED" or "WHY", and bare stat changes
        line = line.split(' · ')[-1]            # "Research failed · Astra gets inconclusive results" -> the story part
        return line.split('. ')[0].rstrip('.')[:120] + '.'
    return ''


def job_title(m, p):
    if p.job in m.JOBS:
        return m.JOBS[p.job][0]
    from .seed_skills import NEW_JOBS
    return NEW_JOBS.get(p.job, ('Citizen',))[0]


def items_text(m, items, limit=3):
    parts = [f'{n} {m.resource_name(k)}' for k, n in sorted(items.items(), key=lambda kv: -kv[1])[:limit]]
    return ', '.join(parts[:-1]) + (' and ' if len(parts) > 1 else '') + parts[-1] if parts else ''


def need_text(delta, keys):
    return ', '.join(f'{k.title()} {delta[k][0]}→{delta[k][1]}' for k in keys if k in delta)


def report(m, p, step, change, clock, reason=''):
    """(desk, headline, story, place, emoji) written like a news report, from what actually changed."""
    name, kind = clean_name(p.display_name), step['kind']
    when, day = WHEN.get(clock.get('phase'), 'today'), clock.get('day', 1)
    if kind == 'gather':
        from . import seed_content as s
        branch = s.GATHER.get(step['item'], {}).get('branch', '')
        place = PLACE_OF_BRANCH.get(branch, 'frontier_edge')
        desk, emoji = ('MINING', '⛏️') if branch == 'ore_mining' else ('SUPPLY', '🧺')
        item = m.resource_name(step['item'])
    elif kind in TASKS:
        desk, place, _ = TASKS[kind]
        emoji = EMOJI.get(kind, '💼')
    elif kind == 'hobby':
        desk, place, emoji = 'LEISURE', HOBBY_PLACE.get(step.get('hobby', ''), 'commons'), '🎨'
    elif kind in {'hangout', 'hi', 'games'}:
        desk, place, emoji = 'COMMUNITY', 'commons', EMOJI[kind]
    elif kind == 'walk':
        desk, place, emoji = 'LEISURE', 'frontier_edge', '🌿'
    else:
        desk, place, emoji = 'HEALTH', 'residential_ring', EMOJI.get(kind, '🏠')
    dateline = f"{PLACES[place][0].upper()}, Day {day} — "
    got, sc, prac, nd = change['gained'], change['sc'], change['practice'], change['needs']
    extras_ = []
    if sc > 0:
        extras_.append(f'{sc} SC')
    if prac:
        top = max(prac, key=prac.get)
        extras_.append(f'+{prac[top]} {top} practice')
    spent = [f"{a - b} {k.title()}" for k, (a, b) in nd.items() if k in ('energy', 'nutrition', 'comfort') and a > b]
    earned = (', earning ' + ' and '.join(extras_)) if extras_ else ''
    cost = need_text(nd, ('energy', 'nutrition', 'comfort'))
    if kind == 'gather' or kind in TASKS:
        role = job_title(m, p)
        if got or sc > 0 or prac:
            what = items_text(m, got)
            head = (f'{name} brings in {what}' if what else f'{name} earns {sc} SC' if sc > 0
                    else f"{name}: {TASKS[kind][2] if kind in TASKS else 'a good shift'}")
            doing = f'gathered {what}' if kind == 'gather' else f"{TASKS[kind][2]}" + (f' and brought back {what}' if what else '')
            if kind == 'gather' and step['item'] not in got:
                verb = 'went mining for' if desk == 'MINING' else 'went out for'
                doing, head = f'{verb} {item} but only turned up {what}', f'{name} digs up {what}'
            goal = " for their goal" if step.get('goal') else ''
            return desk, head, f'{dateline}{role} {name} {doing} {when}{goal}{earned}.', place, emoji
        doing = f'went out for {item}' if kind == 'gather' else TASKS[kind][2]
        why = f' {reason}' if reason else ''
        cost = (' The shift cost ' + (', '.join(spent[:-1]) + ' and ' if len(spent) > 1 else '') + spent[-1] + '.') if spent else ''
        return desk, f'Empty-handed shift for {name}', f'{dateline}{role} {name} {doing} {when} but came back with nothing.{why}{cost}', place, emoji
    if kind == 'eat':
        eaten = items_text(m, change['used']) or 'an emergency ration'
        return desk, f'{name} stops for a meal', f"{dateline}{name} ate {eaten} at home {when}. {need_text(nd, ('nutrition',)) or 'Nutrition topped up'}.", place, emoji
    if kind in {'sleep', 'relax', 'recover'}:
        verb = {'sleep': 'slept at home', 'relax': 'took a break at home', 'recover': 'took time to recover'}[kind]
        return desk, f"{name} {'gets some sleep' if kind == 'sleep' else 'takes a break'}", f"{dateline}{name} {verb} {when}. {need_text(nd, ('energy', 'comfort', 'nutrition', 'social')) or 'Feeling better'}.", place, emoji
    if kind in {'hangout', 'hi'}:
        friend = clean_name(step.get('friend', 'a neighbour'))
        verb = 'spent time with' if kind == 'hangout' else 'stopped to say hi to'
        return desk, f'{name} and {friend} meet in the Commons', f"{dateline}{name} {verb} {friend} {when}. {need_text(nd, ('social', 'morale')) or 'Spirits lifted'}.", place, emoji
    if kind == 'games':
        return desk, f'Games night for {name}', f"{dateline}{name} joined a game in the Commons {when}. {need_text(nd, ('social', 'morale')) or 'Good fun'}.", place, emoji
    if kind == 'hobby':
        hobby = (m.HOBBIES.get(step.get('hobby', ''), ('a hobby',))[0])
        found = items_text(m, got)
        return desk, f'{name} makes time for {hobby.lower()}', (f"{dateline}{name} spent time on {hobby.lower()} {when}. {need_text(nd, ('morale',)) or 'Morale up'}."
                                                               + (f' Found {found}.' if found else '')), place, emoji
    if kind == 'walk':
        found = items_text(m, got)
        return desk, f'{name} walks the frontier', f"{dateline}{name} took a long walk beyond the habitat blocks {when}." + (f' Found {found}.' if found else '') + (f' {need_text(nd, ("morale",))}.' if 'morale' in nd else ''), place, emoji
    return 'COLONY', f'{name} rests at home', f'{dateline}{name} rested at home {when}.', place, emoji


def blocked(m, text, change):
    """Nothing changed at all: a cooldown or a gate. The Seedling tries again shortly instead of reporting."""
    return not change['gained'] and not change['used'] and not change['needs'] and change['sc'] == 0 and not change['practice']


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


def perform(m, channel, uid, provider, provider_uid, name, step):
    """Run the step through the ordinary game code. Returns the game's reply text."""
    token = ACTING.set(True)
    try:
        if step['kind'] == 'gather':
            from . import seed_content as s
            import contextlib
            # Take the world lock like any command, unless this already runs inside it ("Let it decide").
            lock = m.task_queue.atomic(m, channel) if m.task_queue.connection_context.get() is None else contextlib.nullcontext()
            with lock:
                with m.SessionLocal() as db:
                    p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == uid)).scalar_one()
                    text = s.gather(m, db, p, step['item'], 'discord')
                    db.commit()
                    return text
        fn_name, kwargs = step['call']
        if fn_name == 'action':
            kwargs = dict(kwargs, msg=f'auto-{uid}-{m.now().timestamp()}')
        response = getattr(m, fn_name)(channel=channel, uid=provider_uid, name=name, provider=provider, **kwargs)
        return response.body.decode() if hasattr(response, 'body') else str(response)
    finally:
        ACTING.reset(token)


def live_one(m, channel, uid, force=False):
    """One autonomous step for one Seedling. Returns the news story, or '' when it stepped aside."""
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
        step = None
        if queue is not None and queue.state in m.task_queue.ACTIVE:
            if queue.state == 'paused' and needs.blocked_needs(life):
                step = {'kind': 'recover', 'call': ('recover_needs', {}), 'queue': True}      # get a paused queue going again
            else:
                label = m.task_queue.choices(m).get(queue.task, queue.task)
                changed = found.activity != f'Queue: {label}'
                found.activity, found.place, found.emoji = f'Queue: {label}', task_place(queue.task), '⏱️'
                refresh_mood(m, db, p, found, clock, life)
                if changed:
                    name = clean_name(p.display_name)
                    diary(m, db, p, found.place, '⏱️', f"{PLACES[found.place][0].upper()}, Day {clock['day']} — {job_title(m, p)} {name} is working "
                          f"through a queue: {label} ({queue.total - queue.remaining}/{queue.total} done).", desk='WORK', headline=f'{name} starts a {label} queue')
                db.commit()
                return ''
        if step is None:
            if not force and last_seen and m.now() - m.as_utc(last_seen) < timedelta(minutes=AWAY_MINUTES):
                refresh_mood(m, db, p, found, clock, life)       # the player is here: the Seedling follows them
                db.commit()
                return ''
            step = plan(m, db, p, found, life, clock)
        before = snapshot(m, db, p)
        provider, provider_uid = identity_for(m, db, p)
        name = p.display_name
        db.commit()
    result = perform(m, channel, uid, provider, provider_uid, name, step) if (step.get('call') or step['kind'] == 'gather') else ''
    with m.SessionLocal() as db:
        p = db.execute(select(m.Player).where(m.Player.channel_id == channel, m.Player.twitch_uid == uid)).scalar_one()
        p.last_seen = last_seen            # autonomous steps do not count as the player being active
        found = row(db, channel, uid, create=True)
        clock = m.world_clock(db, channel)
        change = changes(m, before, snapshot(m, db, p))
        if step['kind'] != 'rest' and blocked(m, result, change):
            found.activity = 'Waiting: ' + (clean_reason(result) or 'getting ready')[:100]
            found.next_at = m.now() + timedelta(minutes=2)
            refresh_mood(m, db, p, found, clock)
            db.commit()
            return ''
        productive = bool(change['gained'] or change['sc'] > 0 or change['practice'])
        if step['kind'] == 'gather' or step['kind'] in TASKS:
            found.successes, found.failures = (found.successes + 1, 0) if productive else (found.successes, found.failures + 1)
        reason = '' if productive else clean_reason(result)
        for raw in {p.display_name, p.display_name.replace('_', '')}:
            reason = reason.replace(raw, clean_name(p.display_name))     # the game's text uses the full display name
        desk, headline, story, place, emoji = report(m, p, step, change, clock, reason)
        if step.get('queue'):
            story += ' The paused queue can carry on.'
        found.place, found.emoji = place, emoji
        found.activity = activity_label(step, productive, m)
        found.updated_at = m.now()
        refresh_mood(m, db, p, found, clock)
        if step['kind'] != 'rest' or found.activity != 'Resting at home':
            diary(m, db, p, place, emoji, story, desk=desk, headline=headline)
        if change['gained'] or change['used'] or change['sc']:
            record_haul(m, db, p, change)
        db.commit()
        return story


def activity_label(step, ok, m=None):
    kind = step['kind']
    if kind == 'gather':
        return f"Gathering {m.resource_name(step['item']) if m else step['item']}"
    labels = {'eat': 'Eating', 'sleep': 'Sleeping', 'rest': 'Resting at home', 'relax': 'Relaxing', 'recover': 'Recovering',
              'walk': 'Out for a walk', 'games': 'Playing games', 'hangout': f"With {clean_name(step.get('friend', 'a friend'))}",
              'hi': f"Saying hi to {clean_name(step.get('friend', 'someone'))}", 'hobby': f"Hobby: {step.get('hobby', '').title()}"}
    return labels.get(kind, f'Working: {kind.title()}')


def task_place(task):
    kind, _, key = task.partition(':')
    if kind in {'mine', 'gather'}:
        from . import seed_content as s
        return PLACE_OF_BRANCH.get(s.GATHER.get(key, {}).get('branch', ''), 'frontier_edge')
    return 'industrial_ward'


def record_haul(m, db, p, change):
    db.add(SeedlingHaul(channel_id=p.channel_id, canonical_uid=p.twitch_uid, gained=json.dumps(change['gained']), used=json.dumps(change['used']),
                        sc=int(change['sc']), created_at=m.now()))
    db.flush()
    old = list(db.scalars(select(SeedlingHaul.id).where(SeedlingHaul.channel_id == p.channel_id, SeedlingHaul.canonical_uid == p.twitch_uid)
                          .order_by(SeedlingHaul.id.desc()).offset(HAUL_KEEP)))
    if old:
        db.execute(delete(SeedlingHaul).where(SeedlingHaul.id.in_(old)))


def haul_since(db, p, since):
    """({item: total gained}, {item: total used}, SC earned, steps) for this Seedling's autonomous steps since `since`."""
    gained, used, sc, steps = {}, {}, 0, 0
    query = select(SeedlingHaul).where(SeedlingHaul.channel_id == p.channel_id, SeedlingHaul.canonical_uid == p.twitch_uid)
    if since is not None:
        query = query.where(SeedlingHaul.created_at >= since)
    for row_ in db.scalars(query):
        steps += 1
        sc += row_.sc
        for k, n in json.loads(row_.gained or '{}').items():
            gained[k] = gained.get(k, 0) + int(n)
        for k, n in json.loads(row_.used or '{}').items():
            used[k] = used.get(k, 0) + int(n)
    return gained, used, sc, steps


def diary(m, db, p, place, emoji, text, autonomous=True, desk='COLONY', headline=''):
    db.add(SeedlingDiary(channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=clean_name(p.display_name)[:64], place=place, emoji=emoji,
                         desk=desk[:24], headline=(headline or text)[:160], text=text[:400], autonomous=int(autonomous), created_at=m.now()))
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
    for entry in db.scalars(select(SeedlingHaul).where(SeedlingHaul.channel_id == channel, SeedlingHaul.canonical_uid == source)):
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
                          f'(about one action every {AUTONOMY_MINUTES} minutes). Work gathers real materials for your job (or your goal); '
                          'it eats, rests and sleeps before its needs get low, and it steps aside while you play.')
             if found.enabled else 'Off: your Seedling waits for you.']
    from . import looks
    styled = looks.describe(looks.row(db, p))
    lines += ['', 'LOOKS & PERSONALITY', ' · '.join(styled) if styled else 'Its original look. Make it yours with /customize: skin, hair, outfit, accessory, attitude and catchphrase.']
    recent = entries(db, p, 3)
    if recent:
        lines += ['', 'LATEST REPORTS'] + [f'{e.emoji} **{e.headline}** — {e.text.split(" — ", 1)[-1]}' for e in recent]
    return '\n'.join(lines)


def diary_text(m, db, p, provider='discord'):
    rows = entries(db, p, 10 if provider == 'discord' else 3)
    if provider != 'discord':
        return '📓 ' + (' | '.join(f'{e.headline}: {e.text.split(" — ", 1)[-1]}' for e in rows) if rows else f"{p.display_name}'s diary is empty so far.")
    lines = [f'📓 DIARY — {p.display_name.upper()}', 'News from your Seedling\'s day, newest first.', '']
    for e in rows:
        lines.append(f'{e.emoji} **{e.headline}** · <t:{int(m.as_utc(e.created_at).timestamp())}:R>\n{e.text}')
    if not rows:
        lines.append('Nothing yet. With autonomy on, your Seedling reports here as it lives its day.')
    return '\n'.join(lines)


def away_lines(m, db, p, since, limit=3):
    """Reports written since `since`, for the welcome-back summary."""
    rows = [e for e in entries(db, p, 40, since) if e.autonomous]
    if not rows:
        return []
    gathered = [e for e in rows if e.desk in {'SUPPLY', 'MINING'} or 'brings in' in e.headline]
    gained, used, sc, _ = haul_since(db, p, since)
    lines = ['📓 **While you were away:**']
    # Exact totals first: every item it brought in, what it earned and what it ate.
    if gained:
        items = sorted(gained.items(), key=lambda kv: (-kv[1], m.resource_name(kv[0])))
        lines.append(f"🧺 **Collected {sum(gained.values())} items** on {len(gathered)} trip{'s' if len(gathered) != 1 else ''}:")
        lines += [f'• {n} × {m.resource_name(k)}' for k, n in items]
    if sc > 0:
        lines.append(f'🪙 **Earned {sc} SC**')
    if used:
        lines.append('🍲 Used: ' + ', '.join(f'{n} × {m.resource_name(k)}' for k, n in sorted(used.items(), key=lambda kv: -kv[1])))
    shown = [f'{e.emoji} {e.headline}' for e in rows[:limit]]
    extra = len(rows) - len(shown)
    lines += ['', '**Latest:**'] + shown if gained or sc > 0 or used else shown
    return lines + ([f'…and {extra} more in your diary.'] if extra > 0 else [])


def status_line(m, db, p):
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    key, _ = refresh_mood(m, db, p, found)
    emoji, label, _ = MOODS[key]
    return f'{emoji} {label} · {found.emoji} {found.activity} · 💭 "{found.thought}"'


# ---------------------------------------------------------------- the stream

def say_context(m, db, source_ids):
    """The shared things Seedlings talk about: time, weather, holiday, the society and the market."""
    context = {'phase': '', 'condition': '', 'holiday': '', 'bucket': int(m.now().timestamp() // 600), 'extra': []}
    try:
        clock = m.world_clock(db, source_ids[0])
        context.update(phase=clock.get('phase', ''), condition=clock.get('condition_key', ''))
        a, b = m.market_demand(source_ids[0], clock.get('day'))
        context['extra'].append(f'Heard {m.resource_name(a)} is selling high today.')
    except Exception:
        pass
    try:
        from . import seasonal
        active = seasonal.holidays_active_for(m.now().date())
        if active:
            context['holiday'] = active[0]['name']
    except Exception:
        pass
    try:
        rows = list(db.scalars(select(m.Society).where(m.Society.channel_id.in_(source_ids))))
        stats = {f: sum(getattr(r, f) for r in rows) for f in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation')}
        low = min(stats, key=stats.get)
        tier = m.society_tier(m.Society(**stats))
        index = m.SOCIETY_TIERS.index(tier)
        if index + 1 < len(m.SOCIETY_TIERS):
            context['extra'].append(f'We need more {low} to become a {m.SOCIETY_TIERS[index + 1][0]}.')
        else:
            context['extra'].append('Look how far New Eridian has come.')
    except Exception:
        pass
    return context


def chatter(s, everyone, context):
    """A handful of short lines for one Seedling on the stream map, varied every ten minutes."""
    r = random.Random(f"{s['id']}:{context['bucket']}")
    activity = s.get('activity') or ''
    fill = {'place': PLACES.get(s['place'], ('home', ''))[0], 'hobby': activity.partition('Hobby: ')[2].lower() or 'my hobby',
            'item': activity.partition('Gathering ')[2] or 'material'}
    lines = [s.get('thought') or '']
    doing = next((v for k, v in SAY_DOING.items() if activity.startswith(k)), None)
    if doing:
        lines.append(r.choice(doing).format(**fill))
    lines.append(r.choice(SAY_PLACE.get(s['place'], SAY_PLACE['commons'])))
    if context['holiday'] in SAY_HOLIDAY:
        lines.append(r.choice(SAY_HOLIDAY[context['holiday']]))
    others = [o['name'] for o in everyone if o['place'] == s['place'] and o['id'] != s['id']]
    if others:
        lines.append(r.choice(SAY_TO).format(other=r.choice(others)))
    pool = SAY_PHASE.get(context['phase'], []) + SAY_WEATHER.get(context['condition'], []) + context['extra']
    if pool:
        lines.append(r.choice(pool))
    lines = list(dict.fromkeys(line for line in lines if line))   # never the same line twice
    head, rest = lines[:1], lines[1:]
    r.shuffle(rest)
    return (head + rest)[:6]


def districts(m, db, source_ids):
    """How far each district has grown, from the society's tier and stats."""
    import math
    rows = list(db.scalars(select(m.Society).where(m.Society.channel_id.in_(source_ids))))
    stats = {f: sum(getattr(s, f) for s in rows) for f in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation', 'population')}
    total = m.Society(**stats)
    tier = m.society_tier(total)
    index = next((i for i, t in enumerate(m.SOCIETY_TIERS) if t[0] == tier[0]), 0)
    out = {}
    for key, (stat, needs_tier) in GROWTH.items():
        if stat is None:
            level = 2 + index * 2
        elif stat == 'population':
            level = 1 + min(11, stats['population'] // 2)
        else:
            level = 1 + min(11, int(math.sqrt(max(0, stats[stat]) / 15)))
        out[key] = {'name': PLACES[key][0], 'unlocked': index >= needs_tier, 'level': level,
                    'unlocks_at': m.SOCIETY_TIERS[needs_tier][0], 'stat': stat or 'tier'}
    return {'tier_index': index, 'tier_name': tier[0], 'districts': out, 'population': stats['population']}


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
        seedlings.append({'id': hashlib.sha1(f'{p.channel_id}:{p.twitch_uid}'.encode()).hexdigest()[:10], 'name': clean_name(p.display_name),
                          'place': place, 'place_name': PLACES[place][0], 'activity': found.activity if found else 'Settling in', 'job': p.job or '',
                          'emoji': found.emoji if found else '🏠', 'mood': MOODS[mood][1], 'mood_emoji': MOODS[mood][0],
                          'thought': found.thought if found else ''})
    context = say_context(m, db, source_ids)
    from . import looks
    styled = looks.for_players(db, {(p.channel_id, p.twitch_uid) for p in players})
    for p, s_ in zip(players, seedlings):
        found = styled.get((p.channel_id, p.twitch_uid))
        s_['lines'] = looks.flavour(chatter(s_, seedlings, context), found, context['bucket'])
        look = looks.overlay(found)
        if look:
            s_['look'] = look
    rows = list(db.scalars(select(SeedlingDiary).where(SeedlingDiary.channel_id.in_(source_ids)).order_by(SeedlingDiary.id.desc()).limit(14)))
    narration = [{'id': e.id, 'name': e.name, 'emoji': e.emoji, 'desk': e.desk, 'headline': e.headline, 'text': e.text,
                  'place': PLACES.get(e.place, ('', ''))[0], 'at': m.as_utc(e.created_at).isoformat()} for e in rows]
    return {'seedlings': seedlings, 'narration': narration, 'places': {k: v[0] for k, v in PLACES.items()}, **districts(m, db, source_ids)}
