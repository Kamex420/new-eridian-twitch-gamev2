"""Seedlings that live on their own: daily schedules, moods, thoughts and a diary.

Each citizen's Seedling follows a schedule across the four Avesta phases
(Morning, Day, Evening, Night). Every block is Work, Free time, Social or Sleep.
While the player is not playing, a background loop lets the Seedling act about
once every AUTONOMY_MINUTES: it works, eats when hungry, sleeps when tired,
practises a hobby, or meets a friend in the Commons. Every choice goes through
the ordinary game commands, so the same costs, cooldowns, gates and rewards
apply as when the player presses the button themselves.

A Work turn is thought through (work_plan), and the reason is kept (plan) and
quoted in the diary: the goal's next step it can do itself comes first; then it
alternates collecting with practice. Practice is the best training task it can
do now (its trade's skills, its weakest branch, tasks that make something,
only from materials it has plenty of and never ones the goal is saving), or
else fetching what such a task is short of, by gathering it or by making it
with another training task. Collecting is its job's materials, the one it has
least of first, its job task, and now and then a material it has none of.

Moods come from needs, the weather, company and how the day is going. They
nudge success chances a little (Inspired +3% … Miserable −4%) and give the
Seedling a voice: a short thought in its own words (on Discord, when the game has
an API key, Claude writes the day's thought and a diary paragraph in its attitude:
see "in its own words" below). Everything it does is written to a diary, which the player reads when they come back and which the
stream narrator and the Avesta map overlay show live.

The Seedling steps aside whenever the player is active (any command in the last
AWAY_MINUTES) or has a queue running, and it never crafts recipes, sells, buys
or uses festival food. Players can switch autonomy off at any time.
"""
import contextvars
import hashlib
import json
import logging
import os
import random
import re
from datetime import timedelta
from sqlalchemy import Column, String, Integer, DateTime, select, delete
from .db import Base, SessionLocal
from . import ai, needs, runtime
from .models import Identity, LifeRelationship, Player, SkillBranch, Society
from .settlement import seedling as colony_seedling

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
    'farmer': ('Pumpkin', 'Corn', 'Tomato', 'act:farm', 'Berries', 'Pumpkin Seeds', 'Herbs'),
    'cultivator': ('Pumpkin', 'Corn', 'Tomato', 'act:farm', 'Berries', 'Pumpkin Seeds', 'Herbs'),
    'cook': ('Berries', 'Herbs', 'Mushroom', 'Corn', 'Nuts', 'Tomato', 'Raw Algae'),
    'harvester': ('Lumber', 'Berries', 'Flaxa', 'Herbs', 'Stone', 'Clay', 'Murky Water (1000ml)'),
    'miner': ('Hematite Ore', 'Coal', 'Stone', 'Chalcopyrite Ore', 'Clay'),
    'explorer': ('Lumber', 'Stone', 'Nuts', 'act:explore', 'Mushroom', 'Smelly Fungus', 'Fragile Fungus'),
    'technician': ('Lumber', 'Stone', 'Clay', 'act:repair', 'Coal'), 'engineer': ('Stone', 'Clay', 'Lumber', 'act:repair', 'Coal'),
    'artisan': ('Clay', 'Lumber', 'Flaxa', 'Stone', 'Murky Water (1000ml)'),
    'processor': ('Murky Water (1000ml)', 'Raw Algae', 'act:water', 'Clay'),
    'researcher': ('Herbs', 'act:research', 'Tube Fungus', 'act:scan', 'Web Fungus'), 'medic': ('Herbs', 'Golden Cap', 'act:scan', 'Flaxa'),
    'pharmacist': ('Herbs', 'Golden Cap', 'Web Fungus', 'act:research'), 'firefighter': ('Murky Water (1000ml)', 'Stone', 'act:repair'),
    'safety_officer': ('Murky Water (1000ml)', 'Stone', 'act:repair'), 'courier': ('act:cargo', 'act:delivery', 'Lumber', 'act:spaceport'),
    'merchant': ('act:market', 'Berries', 'act:market', 'Lumber'),
}
NO_JOB_WORK = ('Berries', 'Lumber', 'Stone', 'Herbs', 'Clay', 'Flaxa')
PLENTY = 2           # practice only uses materials the Seedling has at least twice what the task takes
CURIOUS = .15        # chance a collecting turn goes after a natural material it has none of
JOB_HOBBY = {'farmer': 'gardening', 'cultivator': 'gardening', 'miner': 'rockwatching', 'technician': 'mechanics', 'engineer': 'mechanics',
             'researcher': 'research', 'courier': 'collecting', 'explorer': 'exploration', 'merchant': 'trading', 'cook': 'cooking',
             'harvester': 'gardening', 'processor': 'scanning', 'artisan': 'collecting', 'medic': 'research', 'pharmacist': 'research'}
HOBBY_PLACE = {'gardening': 'agricultural_district', 'exploration': 'frontier_edge', 'mechanics': 'industrial_ward', 'research': 'research_block',
               'games': 'commons', 'rockwatching': 'frontier_edge', 'cooking': 'residential_ring', 'collecting': 'market_concourse',
               'trading': 'market_concourse', 'scanning': 'research_block'}
# Job tasks: (news desk, place, what they did).
TASKS = {
    'farm': ('FARMING', 'agricultural_district', 'tended the fields'), 'harvest': ('FARMING', 'agricultural_district', 'brought in the harvest'),
    'water': ('UTILITIES', 'agricultural_district', 'ran the water treatment checks'),
    'repair': ('INFRASTRUCTURE', 'industrial_ward', 'carried out repairs on the settlement'), 'research': ('RESEARCH', 'research_block', 'logged a research session'),
    'scan': ('RESEARCH', 'research_block', 'completed a Siro scan'), 'cargo': ('LOGISTICS', 'spaceport_quarter', 'packed cargo for shipment'),
    'delivery': ('LOGISTICS', 'spaceport_quarter', 'sent a delivery duck across New Eridian'), 'spaceport': ('LOGISTICS', 'spaceport_quarter', 'worked the spaceport docks'),
    'explore': ('FRONTIER', 'frontier_edge', 'scouted the land past the wall'), 'market': ('TRADE', 'market_concourse', 'worked the market stalls'),
}
PLACE_OF_BRANCH = {'ore_mining': 'frontier_edge', 'stone_quarrying': 'frontier_edge', 'wood_harvesting': 'frontier_edge',
                   'botanical_harvesting': 'agricultural_district', 'water_collection': 'agricultural_district'}
# Where each skill's training tasks happen on the map.
PLACE_OF_SKILL = {'cultivation': 'agricultural_district', 'extraction': 'frontier_edge', 'infrastructure': 'industrial_ward',
                  'environmental': 'industrial_ward', 'fabrication': 'industrial_ward', 'cooking': 'residential_ring',
                  'medicine': 'research_block', 'emergency': 'commons', 'research': 'research_block', 'logistics': 'spaceport_quarter',
                  'frontier': 'frontier_edge', 'commerce': 'market_concourse'}
# Needs are looked after before they get low enough to stop work.
LOW = {'nutrition': 45, 'energy': 35, 'comfort': 30, 'social': 30}
WHEN = {'Morning': 'this morning', 'Day': 'today', 'Evening': 'this evening', 'Night': 'tonight'}
EMOJI = {'harvest': '🌾', 'gather': '🧺', 'mine': '⛏️', 'eat': '🍲', 'sleep': '🛏️', 'relax': '🛋️', 'games': '🎲', 'hangout': '🤝', 'hi': '👋', 'hobby': '🎨',
         'walk': '🌿', 'recover': '🩹', 'queue': '⏱️', 'rest': '😴', 'farm': '🌱', 'water': '💧', 'repair': '🔧', 'research': '🔬', 'scan': '📡',
         'cargo': '📦', 'delivery': '🦆', 'spaceport': '🚀', 'explore': '🧭', 'market': '🪙', 'train': '🎓'}
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
    'Training': ['Practice makes perfect. Mostly.', 'One more round of {task}.', 'Getting better at {task}, slowly.',
                 'Rocky says every expert started as a beginner.', 'Hands busy, head learning.'],
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
    plan = Column(String(200), nullable=False, default='')      # why it chose its current step, in its own words


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

# A Seedling keeps at most this much Contribution a day (UTC) for its citizen; anything more is taken back after the
# step, so the leaderboard mostly reflects playing yourself. Colony stats, items and XP are not capped.
CONTRIBUTION_CAP = 25


class SeedlingContribution(Base):
    """Contribution a citizen's Seedling kept each day (see CONTRIBUTION_CAP)."""
    __tablename__ = 'seedling_contribution_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    day = Column(String(10), primary_key=True)
    amount = Column(Integer, nullable=False, default=0)


def _today():
    from datetime import timezone
    return runtime.now().astimezone(timezone.utc).date().isoformat()


def contribution_room(db, p):
    """How much more Contribution this citizen's Seedling may keep today."""
    found = db.get(SeedlingContribution, (p.channel_id, p.twitch_uid, _today()))
    return max(0, CONTRIBUTION_CAP - (found.amount if found else 0))


def keep_contribution(db, p, gained):
    """Count what one Seedling step earned toward today's cap and take back anything over it. Returns what was taken."""
    if gained <= 0:
        return 0
    key = (p.channel_id, p.twitch_uid, _today())
    found = db.get(SeedlingContribution, key)
    if found is None:
        found = SeedlingContribution(channel_id=key[0], canonical_uid=key[1], day=key[2], amount=0)
        db.add(found)
    kept = min(gained, max(0, CONTRIBUTION_CAP - found.amount))
    found.amount += kept
    p.contribution -= gained - kept
    return gained - kept


# ---------------------------------------------------------------- state

def install(m):
    from .game.base import app
    SeedlingLife.__table__.create(runtime.engine, checkfirst=True)
    SeedlingDiary.__table__.create(runtime.engine, checkfirst=True)
    SeedlingContribution.__table__.create(runtime.engine, checkfirst=True)
    add_columns(runtime.engine)
    try:
        import asyncio
        from discord.ext import tasks
    except Exception:
        return

    @tasks.loop(seconds=60, reconnect=True)
    async def timer():
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logging.getLogger(__name__).error('Seedling autonomy pass failed; retrying')

    async def start():
        app.state.autonomy_worker = timer.start()

    async def stop():
        timer.stop()
    app.add_event_handler('startup', start)
    app.add_event_handler('shutdown', stop)


def add_columns(engine):
    """Columns added after the table first shipped: additive, existing Seedlings keep everything."""
    from sqlalchemy import inspect, text
    with engine.begin() as conn:
        have = {c['name'] for c in inspect(conn).get_columns(SeedlingLife.__tablename__)}
        if 'plan' not in have:
            conn.execute(text(f"ALTER TABLE {SeedlingLife.__tablename__} ADD COLUMN plan VARCHAR(200) NOT NULL DEFAULT ''"))


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


def friend_of(db, p):
    rel = db.execute(select(LifeRelationship).where(LifeRelationship.channel_id == p.channel_id,
                                                      (LifeRelationship.uid_a == p.twitch_uid) | (LifeRelationship.uid_b == p.twitch_uid))
                     .order_by(LifeRelationship.familiarity.desc()).limit(1)).scalar_one_or_none()
    if rel is None:
        return None
    other = rel.uid_b if rel.uid_a == p.twitch_uid else rel.uid_a
    return db.execute(select(Player).where(Player.channel_id == p.channel_id, Player.twitch_uid == other)).scalar_one_or_none()


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


def mood_modifier(db, p, clock=None):
    """Success-chance change from the Seedling's mood, for world_rule_bundle."""
    from .game.life import life_state
    from .game.world import world_clock
    try:
        life = life_state(db, p)
        clock = clock or world_clock(db, p.channel_id)
        found = row(db, p.channel_id, p.twitch_uid)
        key, reason = mood_of(life, clock.get('condition_key', ''), found.failures if found else 0)
    except Exception:
        return 0, []
    emoji, label, bonus = MOODS[key]
    if not bonus:
        return 0, []
    return bonus, [f'{emoji} {label} mood {round(bonus * 100):+d}%']


def refresh_mood(db, p, found, clock=None, life=None):
    from .game.life import life_state
    from .game.world import world_clock
    life = life or life_state(db, p)
    clock = clock or world_clock(db, p.channel_id)
    key, reason = mood_of(life, clock.get('condition_key', ''), found.failures)
    friend = friend_of(db, p) if key == 'lonely' else None
    found.mood = key
    found.thought = thought_for(key, p.display_name, found.place, friend.display_name if friend else '', clock.get('condition', ''),
                                f"{p.twitch_uid}:{clock.get('day')}:{clock.get('phase')}")
    return key, reason


# ---------------------------------------------------------------- deciding what to do

def identity_for(db, p):
    ident = db.execute(select(Identity).where(Identity.channel_id == p.channel_id, Identity.canonical_uid == p.twitch_uid)
                       .order_by(Identity.id)).scalars().first()
    if ident is not None:
        return ident.provider, ident.provider_uid
    if p.twitch_uid.startswith('discord:'):
        return 'discord', p.twitch_uid.split(':', 1)[1]
    return 'twitch', p.twitch_uid


def favourite_hobby(db, p, found):
    from .game.players import hobby_points
    from .game.rules import HOBBIES
    if found.hobby:
        return found.hobby
    points = {h: hobby_points(db, p, h) for h in HOBBIES}
    best = max(points, key=points.get) if points and max(points.values()) > 0 else JOB_HOBBY.get(p.job, 'games')
    found.hobby = best
    return best


# ---------------------------------------------------------------- deciding what to do

def ready(db, p, action):
    from .game.cooldowns_materials import action_wait
    return not action_wait(db, p, action)


def needs_plan(db, p, life, block):
    """Look after the lowest need first, before it gets low enough to stop work. None when all are fine."""
    low = sorted((getattr(life, k) / LOW[k], k) for k in LOW if getattr(life, k) < LOW[k])
    for _, need in low:
        why = f"My {need.title()} is down to {getattr(life, need)}. Looking after it before it stops my work."
        if need == 'nutrition' and ready(db, p, 'eat'):
            return {'kind': 'eat', 'need': need, 'call': ('eat_full', {}), 'why': why}
        if need == 'energy':
            if ready(db, p, 'sleep'):
                return {'kind': 'sleep', 'need': need, 'call': ('action', {'action': 'sleep'}), 'why': why}
            if ready(db, p, 'relax'):
                return {'kind': 'relax', 'need': need, 'call': ('relax', {}), 'why': why}
        if need == 'comfort':
            if ready(db, p, 'relax'):
                return {'kind': 'relax', 'need': need, 'call': ('relax', {}), 'why': why}
            if life.comfort < 20 and ready(db, p, 'sleep'):
                return {'kind': 'sleep', 'need': need, 'call': ('action', {'action': 'sleep'}), 'why': why}
        if need == 'social':
            friendly = social_plan(db, p)
            if friendly is not None:
                return dict(friendly, need=need, why=f"I have not talked to anyone in a while (Social {life.social}). Going to see {clean_name(friendly['friend'])}.")
            if ready(db, p, 'games'):
                return {'kind': 'games', 'need': need, 'call': ('games', {}), 'why': why}
    if low and needs.blocked_needs(life):
        return {'kind': 'recover', 'need': low[0][1], 'call': ('recover_needs', {}), 'why': f"My {low[0][1].title()} is too low to work. Recovering first."}
    return None


def gather_key(name):
    from . import seed_content as s, crafting_progression as cp
    key = s.find_item(name)
    return key if key in s.GATHER and key not in cp.RARE else None


# ---------------------------------------------------------------- thinking a Work turn through

class Mind:
    """What the Seedling knows while it decides: its bag, branch levels, trade and what the goal is saving."""

    def __init__(self, db, p):
        from .game.players import lvl
        self.db, self.p = db, p
        self.stock = {}
        self.levels = {r.branch: lvl(r.xp) for r in db.scalars(select(SkillBranch).where(
            SkillBranch.channel_id == p.channel_id, SkillBranch.canonical_uid == p.twitch_uid))}
        self.goal, self.saving = None, set()
        self.gates = {}

    def have(self, key):
        from .game.cooldowns_materials import material_amount
        if key not in self.stock:
            self.stock[key] = material_amount(self.db, self.p, key)
        return self.stock[key]

    def name(self, key):
        from .game.players import resource_name
        return resource_name(key)

    def trade(self, cfg):
        from .occupations import matches
        return matches(self.p.job, cfg['skill'])

    def unlocked(self, key):
        from .game.players import lvl, skill_xp
        from .seed_skills import TASKS as SEED_TASKS
        cfg = SEED_TASKS[key]
        return lvl(skill_xp(self.p, cfg['skill'])) >= cfg['unlock']

    def open(self, key):
        """The task's recipe, workstation and recipe skill are open to this citizen (the checks the task itself makes)."""
        from . import crafting_progression as cp, seed_content as s
        from .seed_skills import TASKS as SEED_TASKS
        if key not in self.gates:
            db, p = self.db, self.p
            rid = runtime.MERGED_TRAINING.get(key)
            if rid:
                r = s.RECIPES[rid]
                ok = not cp.recipe_gate(db, p, rid, 'discord') and \
                    s.level_for(db, p, r['requirement'].get('Skill', 'SK_CRAFTING')) >= s.required_level(r)
            else:
                tag = cp.TRAINING_STATIONS.get(SEED_TASKS[key]['branch'])
                ok = not (tag and cp.station_gate(db, p, [tag], cp.STATIONS[tag]['tier'], 'discord'))
            self.gates[key] = ok
        return self.gates[key]

    def plenty(self, cfg):
        return all(self.have(k) >= n * PLENTY for k, n in cfg['cost'].items())

    def spares(self, cfg):
        """Never spend what the goal is saving."""
        return not any(self.name(k) in self.saving for k in cfg['cost'])

    def level(self, cfg):
        return self.levels.get(cfg['branch'], 1)


def task_label(key):
    from .seed_skills import TASKS as SEED_TASKS
    return SEED_TASKS[key]['label']


def made_by(cfg):
    """What a training task makes, in words ('Wood Planks'), or ''."""
    from .game.players import resource_name
    return ' and '.join(resource_name(k) for k in cfg['output'])


def good_for(cfg):
    """Why a training task is worth doing, in a few words."""
    from .game.players import resource_name
    from .game.rules import SKILL_LABELS
    if cfg['cost'] and cfg['output']:
        return f"it turns my spare {' and '.join(resource_name(k) for k in cfg['cost'])} into {made_by(cfg)}"
    if cfg['output']:
        return f'it makes {made_by(cfg)}'
    if cfg['shared']:
        return f"it adds {' and '.join(k.replace('_', ' ') for k in cfg['shared'])} to the shared stores"
    if cfg['society']:
        return f"it raises New Eridian's {' and '.join(k.title() for k in cfg['society'])}"
    return f"it keeps my {SKILL_LABELS[cfg['skill']]} sharp"


def a_or_an(word):
    return ('an ' if word[:1].lower() in 'aeiou' else 'a ') + word


# Job tasks as the Seedling thinks of them (TASKS says what it did, for the news).
DOING = {'farm': 'tending the fields', 'harvest': 'bringing in the harvest', 'water': 'running the water treatment checks',
         'repair': 'carrying out repairs on the settlement', 'research': 'logging a research session', 'scan': 'running a Siro scan',
         'cargo': 'packing cargo for shipment', 'delivery': 'sending a delivery duck across New Eridian', 'spaceport': 'working the spaceport docks',
         'explore': 'scouting the land past the wall', 'market': 'working the market stalls'}


def goal_plan(db, p, mind):
    """(collecting step, training step) from the goal's walkthrough: the first of each the Seedling can do by itself.
    Collecting is gathering or mining a material, harvesting or cargo work. Either can be None."""
    from . import extras
    from .game.players import resource_name
    from .game.routes_crafting import craft_missing_materials
    from .seed_skills import TASKS as SEED_TASKS
    try:
        e, steps = extras.walkthrough(db, p)
    except Exception:
        return None, None
    if e is None:
        return None, None
    mind.goal = e.name
    try:
        from . import workbench as wb
        crafts, raw = extras.plan(wb.Context(db, p), e)
        mind.saving = {resource_name(k) for k in set(e.inputs) | set(raw) | {k for sub, _ in crafts for k in sub.inputs}}
    except Exception:
        pass
    collect = train = None
    for st in steps:
        act = st.get('action') or {}
        do, task = act.get('do'), act.get('task', '')
        kind, _, key = task.partition(':')
        if collect is None and do == 'queue' and kind in {'gather', 'mine'} and gather_key(resource_name(key)):
            collect = {'kind': 'gather', 'item': key, 'goal': True,
                       'why': f"My goal is {e.name}, and it still needs {resource_name(key)}. Collecting some."}
        elif collect is None and do == 'cmd' and act.get('leaf') in {'w_farm_harvest', 'w_cargo'}:
            job = 'harvest' if act['leaf'] == 'w_farm_harvest' else 'cargo'
            collect = {'kind': job, 'call': ('action', {'action': job}), 'goal': True,
                       'why': f"My goal is {e.name}, and next it needs: {st['name']}."}
        elif train is None and (do == 'train' or (do == 'queue' and kind == 'work')):
            key = task if do == 'train' else key
            if key in SEED_TASKS and ready(db, p, key) and mind.unlocked(key) and mind.open(key) and \
                    not craft_missing_materials(db, p, SEED_TASKS[key]['cost']):
                cfg = SEED_TASKS[key]
                train = {'kind': 'train', 'task': key, 'skill': cfg['skill'], 'goal': True, 'call': ('action', {'action': key}),
                         'why': f"My goal is {e.name}, and the way there includes {cfg['label']} practice. Practising it now."}
    return collect, train


def practice_plan(db, p, mind, trade_only=False, turn=0):
    """The best training task to do now: my trade's skills first, my weakest branch first, tasks that make
    something, only from materials I have plenty of and never what the goal is saving. Equal choices take turns."""
    from .seed_skills import TASKS as SEED_TASKS
    ranked, size = [], len(SEED_TASKS)
    for index, (key, cfg) in enumerate(SEED_TASKS.items()):
        if (trade_only and not mind.trade(cfg)) or not mind.unlocked(key) or not mind.spares(cfg) or not mind.plenty(cfg):
            continue
        score = (40 if mind.trade(cfg) else 0) + 3 * max(0, 8 - mind.level(cfg)) + (10 if cfg['output'] else 0)
        ranked.append((-score, (index - turn) % size, key))
    for _, _, key in sorted(ranked):
        if ready(db, p, key) and mind.open(key):
            cfg = SEED_TASKS[key]
            why = f"Practising {cfg['label']} (Lv {mind.level(cfg)}): {good_for(cfg)}."
            if not trade_only and p.job in JOB_WORK and not mind.trade(cfg):
                why = 'My own trade has nothing I can practise right now, so I am p' + why[1:]
            return {'kind': 'train', 'task': key, 'skill': cfg['skill'], 'call': ('action', {'action': key}), 'why': why}
    return None


def supply_plan(db, p, mind):
    """Fetch what a training task of my trade is short of: gather it, or make it with another training task I can do."""
    from .seed_skills import TASKS as SEED_TASKS
    trade = sorted((k for k, cfg in SEED_TASKS.items() if mind.trade(cfg) and mind.unlocked(k) and mind.spares(cfg)),
                   key=lambda k: mind.level(SEED_TASKS[k]))
    for key in trade:
        cfg = SEED_TASKS[key]
        short = [(k, n * PLENTY) for k, n in cfg['cost'].items() if mind.have(k) < n * PLENTY]
        if not short or not mind.open(key):
            continue
        for k, need in short:
            step = fetch(db, p, mind, k, depth=2)
            if step:
                step['why'] = f"{cfg['label']} needs {mind.name(k)} and I have {mind.have(k)} of {need}. " + step['why']
                return step
    return None


def fetch(db, p, mind, key, depth):
    """A step that brings in `key`: gathering it, or the training task that makes it (one more level down when short)."""
    from .seed_skills import TASKS as SEED_TASKS
    natural = gather_key(mind.name(key))
    if natural:
        return {'kind': 'gather', 'item': natural, 'why': f"Collecting {mind.name(key)} first."}
    for task, cfg in SEED_TASKS.items():
        if key not in cfg['output'] or not mind.unlocked(task) or not mind.spares(cfg) or not mind.open(task):
            continue
        if mind.plenty(cfg) and ready(db, p, task):
            return {'kind': 'train', 'task': task, 'skill': cfg['skill'], 'call': ('action', {'action': task}),
                    'why': f"Making it with {cfg['label']} first."}
        if depth > 1:
            for k, n in cfg['cost'].items():
                if mind.have(k) < n * PLENTY:
                    step = fetch(db, p, mind, k, depth - 1)
                    if step:
                        step['why'] = f"{cfg['label']} makes it, but needs {mind.name(k)}. " + step['why']
                        return step
    return None


def collect_plan(db, p, found, mind):
    """My job's materials, the one I have least of first, or my job task; now and then something I have none of."""
    from .game.players import resource_name
    if random.random() < CURIOUS:
        from . import seed_content as s, crafting_progression as cp
        owned = s.stock(db, p)
        new = [k for k in s.GATHER if k not in cp.RARE and not owned.get(k)]
        if new:
            key = new[found.cycle % len(new)]
            found.cycle += 1
            return {'kind': 'gather', 'item': key, 'why': f"I have never brought back {resource_name(key)}. Time to find some."}
    options = JOB_WORK.get(p.job, NO_JOB_WORK)
    keys = {o: gather_key(o) for o in options if not o.startswith('act:')}
    materials = [k for k in keys.values() if k]
    role = job_title(p)
    for _ in range(len(options)):
        choice = options[found.cycle % len(options)]
        found.cycle += 1
        if choice.startswith('act:'):
            act = choice[4:]
            return {'kind': act, 'call': ('action', {'action': act}), 'why': f"As {a_or_an(role)}, today I am {DOING[act]}."}
        if keys.get(choice):
            # A gathering turn: the job material I have least of (the rotation's own pick on a tie).
            key = min(materials, key=lambda k: (mind.have(k), k != keys[choice]))
            have = f'I only have {mind.have(key)}' if mind.have(key) else 'I have none'
            return {'kind': 'gather', 'item': key, 'why': (f"As {a_or_an(role)}, I bring in {resource_name(key)}, and {have}." if p.job in JOB_WORK
                                                          else f"Everyone can use {resource_name(key)}, and {have}.")}
    return {'kind': 'gather', 'item': gather_key('Lumber'), 'why': 'Lumber is always useful.'}


def work_plan(db, p, found):
    """Think the Work turn through: collecting and practice take turns, and the goal's own steps come first in each.
    The step carries 'why': the reason, in the Seedling's own words."""
    mind = Mind(db, p)
    collect, train = goal_plan(db, p, mind)
    if (found.activity or '').startswith(('Gathering', 'Working')):          # collected last time: now practise
        # The goal's training, else my trade's, else fetch what my trade's training is short of, else any training I can do.
        step = (train or practice_plan(db, p, mind, True, found.cycle) or supply_plan(db, p, mind)
                or practice_plan(db, p, mind, False, found.cycle))
        if step:
            return step
    return collect or train or colony_step(db, p, mind) or collect_plan(db, p, found, mind)


# ---------------------------------------------------------------- helping New Eridian
# Seedlings answer a live event in any waking hour (its Primary skill first, then Support). On some collecting turns
# (LEAN) they help today's Society Directive, or once it is done the society stat the colony is lowest on. Their work
# counts like anyone's (main.work_counts); they never start an automatic event.
LEAN = .35
STAT_SKILLS = {'food': ('cultivation',), 'materials': ('extraction', 'environmental'), 'development': ('infrastructure', 'fabrication'),
               'knowledge': ('research', 'medicine'), 'treasury': ('commerce',), 'reputation': ('logistics',)}
SKILL_ACT = {'cultivation': 'farm', 'environmental': 'water', 'infrastructure': 'repair', 'research': 'research',
             'commerce': 'market', 'frontier': 'explore', 'logistics': 'cargo'}


def skill_step(db, p, mind, skill):
    """A step that counts as `skill` work: gathering a material of that kind, a training task, or the job task."""
    from .game.players import resource_name
    from .seed_skills import TASKS as SEED_TASKS
    from . import seed_content as s, crafting_progression as cp
    natural = [k for k, v in s.GATHER.items() if k not in cp.RARE and v['branch'] != 'ore_mining'      # no mining roll
               and s.GATHER_SKILL.get(v['branch'], 'extraction') == skill]
    if natural:
        key = min(natural, key=lambda k: (mind.have(k), k))
        return {'kind': 'gather', 'item': key, 'skill': skill, 'doing': f'bringing in {resource_name(key)}'}
    for key, cfg in SEED_TASKS.items():
        if cfg['skill'] == skill and mind.unlocked(key) and mind.spares(cfg) and mind.plenty(cfg) and mind.open(key) and ready(db, p, key):
            return {'kind': 'train', 'task': key, 'skill': skill, 'call': ('action', {'action': key}), 'doing': f"practising {cfg['label']}"}
    act = SKILL_ACT.get(skill)
    if act == 'cargo' and p.cargo > 0:
        act = 'delivery'                       # a delivery also raises Reputation; packing cargo prepares one
    if act and ready(db, p, act):
        return {'kind': act, 'skill': skill, 'call': ('action', {'action': act}), 'doing': DOING[act]}
    return None


def _label(skill):
    from .game.rules import SKILL_LABELS
    return SKILL_LABELS.get(skill, skill.title())


def event_step(db, p, mind=None):
    """Answer the live event: Primary work first, Support work when the Seedling can do no Primary work."""
    from .game.players import as_utc, world
    from .game.rules import EVENTS
    w = world(db, p.channel_id)
    if not w.active_event or (w.event_ends and as_utc(w.event_ends) <= runtime.now()):
        return None
    cfg, mind = EVENTS[w.active_event], mind or Mind(db, p)
    for skill in (cfg['primary'], cfg['support']):
        step = skill_step(db, p, mind, skill)
        if step:
            step['colony'] = 'event'
            step['why'] = f"The {cfg['name']} is on and {_label(skill)} work counts, so I am {step.pop('doing')}."
            return step
    return None


def colony_step(db, p, mind):
    """Now and then (LEAN): today's Society Directive, my trade's skills first; once it is done, the weakest stat."""
    from .game import players
    from .game.world import directive_for, world_clock
    if random.random() >= LEAN:
        return None
    from .occupations import matches
    row, cfg = directive_for(db, p.channel_id, world_clock(db, p.channel_id)['day'])
    if not row.complete:
        for skill in sorted(cfg[2], key=lambda k: (not matches(p.job, k), k)):
            step = skill_step(db, p, mind, skill)
            if step:
                step['colony'] = 'directive'
                step['why'] = f"Today's Society Directive is {cfg[1]} and {_label(skill)} work counts, so I am {step.pop('doing')}."
                return step
    society = players.society(db, p.channel_id)
    stat = min(STAT_SKILLS, key=lambda f: (getattr(society, f), f))
    for skill in sorted(STAT_SKILLS[stat], key=lambda k: (not matches(p.job, k), k)):
        step = skill_step(db, p, mind, skill)
        if step:
            step['colony'] = 'weakest'
            step['why'] = (f"New Eridian is lowest on {stat.title()} ({getattr(society, stat)}), so I am "
                           f"{step.pop('doing')} to help.")
            return step
    return None


def plan(db, p, found, life, clock):
    """What the Seedling does now: a dict with 'kind', 'why', and 'call' or 'item' for game actions."""
    block = schedule_of(found)[clock['phase']]
    if block == 'sleep' and ready(db, p, 'sleep') and (life.energy < 90 or life.comfort < 90):
        return {'kind': 'sleep', 'call': ('action', {'action': 'sleep'}),
                'why': f"It is my time to sleep, and I could use it (Energy {life.energy}, Comfort {life.comfort})."}
    step = needs_plan(db, p, life, block)
    if step is not None:
        return step
    if block == 'sleep':
        return {'kind': 'rest', 'why': 'Sleep time, but I am rested. A quiet hour at home.'}
    step = event_step(db, p)                  # an event needs everyone awake, even on free time
    if step is not None:
        return step
    if block == 'work':
        return work_plan(db, p, found)
    if block == 'social':
        step = social_plan(db, p)
        return dict(step, why=f"Time for friends: catching up with {clean_name(step['friend'])}.") if step else \
            {'kind': 'games', 'call': ('games', {}), 'why': 'Time for friends. A game in the Commons it is.'}
    preferred = colony_seedling(db, p).preferred_activity
    roll = random.random()
    if roll < .55:
        hobby = favourite_hobby(db, p, found)
        return {'kind': 'hobby', 'hobby': hobby, 'call': ('hobby', {'hobby': hobby}), 'why': f'Free time: an hour of {hobby}.'}
    if roll < .75:
        return {'kind': 'walk', 'call': ('walk', {}), 'why': 'Free time: a walk past the habitat blocks.'}
    if preferred == 'games' or roll < .88:
        return {'kind': 'games', 'call': ('games', {}), 'why': 'Free time: a game in the Commons.'}
    return {'kind': 'relax', 'call': ('relax', {}), 'why': 'Free time: feet up for a while.'}


def social_plan(db, p):
    friend = friend_of(db, p)
    if friend is None:
        others = db.execute(select(Player).where(Player.channel_id == p.channel_id, Player.twitch_uid != p.twitch_uid,
                                                   Player.last_seen >= runtime.now() - timedelta(days=ACTIVE_DAYS)).limit(20)).scalars().all()
        if not others or not ready(db, p, 'hi'):
            return None
        friend = random.choice(others)
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    if ready(db, p, 'hangout'):
        return {'kind': 'hangout', 'friend': friend.display_name, 'call': ('hangout', {'target': friend.display_name})}
    if ready(db, p, 'hi'):
        return {'kind': 'hi', 'friend': friend.display_name, 'call': ('hi', {'target': friend.display_name})}
    return None


# ---------------------------------------------------------------- what actually changed

NEEDS = ('energy', 'nutrition', 'social', 'comfort', 'morale')
LEGACY = ('crops', 'ore', 'rare_ore', 'components', 'cargo')


def snapshot(db, p):
    from . import task_queue
    from .game.life import life_state
    from .competencies import FIELDS
    life = life_state(db, p)
    branches = {r.branch: r.xp for r in db.scalars(select(SkillBranch).where(SkillBranch.channel_id == p.channel_id,
                                                                                 SkillBranch.canonical_uid == p.twitch_uid))}
    return {'stock': dict(task_queue.inventory_snapshot(db, p)), 'sc': p.sc, 'legacy': {k: getattr(p, k) for k in LEGACY},
            'needs': {k: getattr(life, k) for k in NEEDS}, 'xp': {k: getattr(p, f) for k, f in FIELDS.items()}, 'branches': branches}


def changes(before, after):
    from .game.players import resource_name
    from .game.rules import SKILL_LABELS
    gained = {k: n - before['stock'].get(k, 0) for k, n in after['stock'].items() if n > before['stock'].get(k, 0)}
    used = {k: before['stock'][k] - after['stock'].get(k, 0) for k in before['stock'] if after['stock'].get(k, 0) < before['stock'][k]}
    for k in LEGACY:
        delta = after['legacy'][k] - before['legacy'][k]
        if delta > 0 and resource_name(k) not in {resource_name(x) for x in gained}:
            gained[k] = delta
    practice = {}
    for k, v in after['xp'].items():
        if v > before['xp'].get(k, 0):
            practice[SKILL_LABELS.get(k, k.title())] = v - before['xp'].get(k, 0)
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


def job_title(p):
    from .game.rules import JOBS
    if p.job in JOBS:
        return JOBS[p.job][0]
    from .seed_skills import NEW_JOBS
    return NEW_JOBS.get(p.job, ('Citizen',))[0]


def items_text(items, limit=3):
    from .game.players import resource_name
    parts = [f'{n} {resource_name(k)}' for k, n in sorted(items.items(), key=lambda kv: -kv[1])[:limit]]
    return ', '.join(parts[:-1]) + (' and ' if len(parts) > 1 else '') + parts[-1] if parts else ''


def need_text(delta, keys):
    return ', '.join(f'{k.title()} {delta[k][0]}→{delta[k][1]}' for k in keys if k in delta)


def report(p, step, change, clock, reason=''):
    """(desk, headline, story, place, emoji) written like a news report, from what actually changed."""
    from .game.players import resource_name
    from .game.rules import HOBBIES
    from .seed_skills import TASKS as SEED_TASKS
    name, kind = clean_name(p.display_name), step['kind']
    when, day = WHEN.get(clock.get('phase'), 'today'), clock.get('day', 1)
    if kind == 'gather':
        from . import seed_content as s
        branch = s.GATHER.get(step['item'], {}).get('branch', '')
        place = PLACE_OF_BRANCH.get(branch, 'frontier_edge')
        desk, emoji = ('MINING', '⛏️') if branch == 'ore_mining' else ('SUPPLY', '🧺')
        item = resource_name(step['item'])
    elif kind in TASKS:
        desk, place, _ = TASKS[kind]
        emoji = EMOJI.get(kind, '💼')
    elif kind == 'train':
        cfg = SEED_TASKS.get(step.get('task'), {})
        desk, place, emoji, label = 'TRAINING', PLACE_OF_SKILL.get(cfg.get('skill'), 'industrial_ward'), '🎓', cfg.get('label', 'a skill')
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
    if kind == 'gather' or kind in TASKS or kind == 'train':
        role = job_title(p)
        if got or sc > 0 or prac:
            what = items_text(got)
            head = (f'{name} brings in {what}' if what else f'{name} earns {sc} SC' if sc > 0
                    else f"{name}: {TASKS[kind][2] if kind in TASKS else 'a good shift'}")
            doing = f'gathered {what}' if kind == 'gather' else f"{TASKS[kind][2]}" + (f' and brought back {what}' if what else '') if kind in TASKS else ''
            if kind == 'train':
                head, doing = (f'{name} makes {what}' if what else f'{name} trains {label}'), f'practised {label}' + (f' and made {what}' if what else '')
            if kind == 'gather' and step['item'] not in got:
                verb = 'went mining for' if desk == 'MINING' else 'went out for'
                doing, head = f'{verb} {item} but only turned up {what}', f'{name} digs up {what}'
            goal = " for their goal" if step.get('goal') else ''
            return desk, head, f'{dateline}{role} {name} {doing} {when}{goal}{earned}.', place, emoji
        doing = f'went out for {item}' if kind == 'gather' else f'practised {label}' if kind == 'train' else TASKS[kind][2]
        why = f' {reason}' if reason else ''
        cost = (' The shift cost ' + (', '.join(spent[:-1]) + ' and ' if len(spent) > 1 else '') + spent[-1] + '.') if spent else ''
        if kind == 'train':
            return desk, f'A tough lesson for {name}', f'{dateline}{role} {name} {doing} {when} but it did not work out.{why}{cost}', place, emoji
        return desk, f'Empty-handed shift for {name}', f'{dateline}{role} {name} {doing} {when} but came back with nothing.{why}{cost}', place, emoji
    if kind == 'eat':
        eaten = items_text(change['used']) or 'an emergency ration'
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
        hobby = (HOBBIES.get(step.get('hobby', ''), ('a hobby',))[0])
        found = items_text(got)
        return desk, f'{name} makes time for {hobby.lower()}', (f"{dateline}{name} spent time on {hobby.lower()} {when}. {need_text(nd, ('morale',)) or 'Morale up'}."
                                                               + (f' Found {found}.' if found else '')), place, emoji
    if kind == 'walk':
        found = items_text(got)
        return desk, f'{name} walks the frontier', f"{dateline}{name} took a long walk beyond the habitat blocks {when}." + (f' Found {found}.' if found else '') + (f' {need_text(nd, ("morale",))}.' if 'morale' in nd else ''), place, emoji
    return 'COLONY', f'{name} rests at home', f'{dateline}{name} rested at home {when}.', place, emoji


def blocked(text, change):
    """Nothing changed at all: a cooldown or a gate. The Seedling tries again shortly instead of reporting."""
    return not change['gained'] and not change['used'] and not change['needs'] and change['sc'] == 0 and not change['practice']


# ---------------------------------------------------------------- the worker

def tick():
    """Let every due Seedling do one thing."""
    from .game.players import as_utc
    now = runtime.now()
    with SessionLocal() as db:
        recent = db.execute(select(Player.channel_id, Player.twitch_uid).where(Player.last_seen >= now - timedelta(days=ACTIVE_DAYS))).all()
        known = {(r.channel_id, r.canonical_uid): r for r in db.scalars(select(SeedlingLife))}
        due = []
        for channel, uid in recent:
            found = known.get((channel, uid))
            if found is None:
                found = row(db, channel, uid, create=True)
                found.next_at = now + timedelta(seconds=random.randint(30, AUTONOMY_MINUTES * 60))
            elif found.enabled and (found.next_at is None or as_utc(found.next_at) <= now):
                due.append((as_utc(found.next_at) if found.next_at else now - timedelta(days=365), channel, uid))
        db.commit()
    # Longest-waiting first: in database order the same first Seedlings were due again every pass, and with more
    # than BATCH x AUTONOMY_MINUTES active players the rest never got a turn.
    due.sort(key=lambda d: d[0])
    for _, channel, uid in due[:BATCH]:
        try:
            live_one(channel, uid)
        except Exception:
            logging.getLogger(__name__).exception('Seedling step failed for one citizen; it will try again later')
            with SessionLocal() as db:
                found = db.get(SeedlingLife, (channel, uid))
                if found is not None:
                    found.next_at = runtime.now() + timedelta(minutes=AUTONOMY_MINUTES)
                    db.commit()


def game_command(name):
    """The game command a step names (step['call']), imported from the module that defines it."""
    from .game.action import action
    from .game.routes_extra import eat_full, recover_needs
    from .game.routes_life_social import games, hangout, hi, hobby, relax, walk
    return {'action': action, 'eat_full': eat_full, 'games': games, 'hangout': hangout, 'hi': hi, 'hobby': hobby,
            'recover_needs': recover_needs, 'relax': relax, 'walk': walk}[name]


def perform(channel, uid, provider, provider_uid, name, step):
    """Run the step through the ordinary game code. Returns the game's reply text."""
    from . import task_queue
    token = ACTING.set(True)
    try:
        if step['kind'] == 'gather':
            from . import seed_content as s
            import contextlib
            # Take the world lock like any command, unless this already runs inside it ("Let it decide").
            lock = task_queue.atomic(channel) if task_queue.connection_context.get() is None else contextlib.nullcontext()
            with lock:
                with SessionLocal() as db:
                    p = db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == uid)).scalar_one()
                    text = s.gather(db, p, step['item'], 'discord')
                    db.commit()
                    return text
        fn_name, kwargs = step['call']
        if fn_name == 'action':
            kwargs = dict(kwargs, msg=f'auto-{uid}-{runtime.now().timestamp()}')
        response = game_command(fn_name)(channel=channel, uid=provider_uid, name=name, provider=provider, **kwargs)
        return response.body.decode() if hasattr(response, 'body') else str(response)
    finally:
        ACTING.reset(token)


def live_one(channel, uid, force=False):
    """One autonomous step for one Seedling. Returns the news story, or '' when it stepped aside."""
    from . import task_queue
    from .game.life import life_state
    from .game.players import as_utc
    from .game.world import world_clock
    with SessionLocal() as db:
        p = db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == uid)).scalar_one_or_none()
        found = row(db, channel, uid, create=True)
        found.next_at = runtime.now() + timedelta(seconds=AUTONOMY_MINUTES * 60 + random.randint(-60, 60))
        if p is None or (not found.enabled and not force):
            db.commit()
            return ''
        clock = world_clock(db, channel)
        life = life_state(db, p)
        queue = db.get(task_queue.TaskQueue, (channel, uid))
        last_seen = p.last_seen
        step = None
        if queue is not None and queue.state in task_queue.ACTIVE:
            if queue.state == 'paused' and needs.blocked_needs(life):
                step = {'kind': 'recover', 'call': ('recover_needs', {}), 'queue': True,       # get a paused queue going again
                        'why': 'My queue stopped because my needs are low. Recovering so it can carry on.'}
            else:
                label = task_queue.choices().get(queue.task, queue.task)
                changed = found.activity != f'Queue: {label}'
                found.activity, found.place, found.emoji = f'Queue: {label}', task_place(queue.task), '⏱️'
                refresh_mood(db, p, found, clock, life)
                if changed:
                    name = clean_name(p.display_name)
                    diary(db, p, found.place, '⏱️', f"{PLACES[found.place][0].upper()}, Day {clock['day']} — {job_title(p)} {name} is working "
                          f"through a queue: {label} ({queue.total - queue.remaining}/{queue.total} done).", desk='WORK', headline=f'{name} starts a {label} queue')
                db.commit()
                return ''
        if step is None:
            if not force and last_seen and runtime.now() - as_utc(last_seen) < timedelta(minutes=AWAY_MINUTES):
                refresh_mood(db, p, found, clock, life)       # the player is here: the Seedling follows them
                db.commit()
                return ''
            step = plan(db, p, found, life, clock)
        before = snapshot(db, p)
        contribution_before = p.contribution
        provider, provider_uid = identity_for(db, p)
        name = p.display_name
        db.commit()
    result = perform(channel, uid, provider, provider_uid, name, step) if (step.get('call') or step['kind'] == 'gather') else ''
    with SessionLocal() as db:
        p = db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == uid)).scalar_one()
        p.last_seen = last_seen            # autonomous steps do not count as the player being active
        keep_contribution(db, p, p.contribution - contribution_before)
        found = row(db, channel, uid, create=True)
        clock = world_clock(db, channel)
        change = changes(before, snapshot(db, p))
        if step['kind'] != 'rest' and blocked(result, change):
            found.activity = 'Waiting: ' + (clean_reason(result) or 'getting ready')[:100]
            found.next_at = runtime.now() + timedelta(minutes=2)
            refresh_mood(db, p, found, clock)
            db.commit()
            return ''
        productive = bool(change['gained'] or change['sc'] > 0 or change['practice'])
        if step['kind'] in {'gather', 'train'} or step['kind'] in TASKS:
            found.successes, found.failures = (found.successes + 1, 0) if productive else (found.successes, found.failures + 1)
        reason = '' if productive else clean_reason(result)
        for raw in {p.display_name, p.display_name.replace('_', '')}:
            reason = reason.replace(raw, clean_name(p.display_name))     # the game's text uses the full display name
        desk, headline, story, place, emoji = report(p, step, change, clock, reason)
        if step.get('why'):
            found.plan = step['why'][:200]
            story += f' “{step["why"]}”'          # the news quotes its reasoning
        if step.get('queue'):
            story += ' The paused queue can carry on.'
        found.place, found.emoji = place, emoji
        found.activity = activity_label(step, productive)
        found.updated_at = runtime.now()
        refresh_mood(db, p, found, clock)
        if step['kind'] != 'rest' or found.activity != 'Resting at home':
            diary(db, p, place, emoji, story, desk=desk, headline=headline)
        if change['gained'] or change['used'] or change['sc']:
            record_haul(db, p, change)
        db.commit()
        return story


def activity_label(step, ok):
    from .game.players import resource_name
    from .seed_skills import TASKS as SEED_TASKS
    kind = step['kind']
    if kind == 'gather':
        return f"Gathering {resource_name(step['item'])}"
    labels = {'eat': 'Eating', 'sleep': 'Sleeping', 'rest': 'Resting at home', 'relax': 'Relaxing', 'recover': 'Recovering',
              'walk': 'Out for a walk', 'games': 'Playing games', 'hangout': f"With {clean_name(step.get('friend', 'a friend'))}",
              'hi': f"Saying hi to {clean_name(step.get('friend', 'someone'))}", 'hobby': f"Hobby: {step.get('hobby', '').title()}"}
    if kind == 'train':
        return f"Training: {SEED_TASKS[step['task']]['label']}"
    return labels.get(kind, f'Working: {kind.title()}')


def task_place(task):
    kind, _, key = task.partition(':')
    from .seed_skills import TASKS as TRAINING
    if kind == 'work' and key in TRAINING:
        return PLACE_OF_SKILL.get(TRAINING[key]['skill'], 'industrial_ward')
    if kind in {'mine', 'gather'}:
        from . import seed_content as s
        return PLACE_OF_BRANCH.get(s.GATHER.get(key, {}).get('branch', ''), 'frontier_edge')
    return 'industrial_ward'


def record_haul(db, p, change):
    db.add(SeedlingHaul(channel_id=p.channel_id, canonical_uid=p.twitch_uid, gained=json.dumps(change['gained']), used=json.dumps(change['used']),
                        sc=int(change['sc']), created_at=runtime.now()))
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


def diary(db, p, place, emoji, text, autonomous=True, desk='COLONY', headline=''):
    db.add(SeedlingDiary(channel_id=p.channel_id, canonical_uid=p.twitch_uid, name=clean_name(p.display_name)[:64], place=place, emoji=emoji,
                         desk=desk[:24], headline=(headline or text)[:160], text=text[:400], autonomous=int(autonomous), created_at=runtime.now()))
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


# ---- in its own words (optional, Discord only)
# With an ANTHROPIC_API_KEY (app/ai.py), a Seedling that has a diary entry today gets, once a day, a thought and a diary
# paragraph in its attitude. write_words makes the API call, so it must run outside the game lock (the menu's Overview and
# Diary views call it before the /seedling command takes the lock); words only reads what was written, so the command, the
# slash /seedling and the ticket buttons (all inside the lock) can show it. The stored thought column is never changed.

WORDS_ENTRIES = 8              # today's diary entries the words are written from
WORDS_THOUGHT_CHARS = 160
WORDS_DIARY_CHARS = 600
# Stable on every call (no names or numbers in it, so the provider can reuse it); everything about the Seedling is in the prompt.
WORDS_SYSTEM = (
    'You write in-character lines for a Seedling, a small settler living its own day in New Eridian on the planet Avesta. '
    'Reply with exactly two lines and nothing else:\n'
    'THOUGHT: <at most 15 words, first person, in its attitude>\n'
    "DIARY: <2 or 3 sentences, first person, only about today's entries given>\n"
    'Never invent items, numbers or people; use only the names given. Keep it family-friendly. '
    'No hashtags, and no emojis beyond one.')
_WORDS_LABEL = re.compile(r'^[\s>*_#`\-•]*(THOUGHT|DIARY)\s*[*_`]*\s*[:：]\s*[*_`]*\s*', re.I)


def words_key(p, day=None):
    """Where today's words are kept (ai_text_v1): one per Seedling per UTC day."""
    return f'seedling:{p.channel_id}:{p.twitch_uid}:{day or ai.today()}'


def _short(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'


def parse_words(text):
    """(thought, diary) from the model's "THOUGHT: …" and "DIARY: …" lines (extra spaces, bullets, bold and a wrapped diary
    are fine), or ('', '') when either is missing: then the Seedling keeps its template thought."""
    found, current = {}, ''
    for line in str(text or '').splitlines():
        label = _WORDS_LABEL.match(line)
        if label:
            current = label[1].lower()
            if current in found:
                current = ''                    # a second THOUGHT or DIARY: the first one stands
            else:
                found[current] = [line[label.end():]]
        elif current and line.strip():
            found[current].append(line)
    out = []
    for name, limit in (('thought', WORDS_THOUGHT_CHARS), ('diary', WORDS_DIARY_CHARS)):
        value = ' '.join(' '.join(found.get(name, [])).replace('*', '').replace('`', '').split()).strip(' "“”')
        out.append(_short(value, limit))
    return tuple(out) if all(out) else ('', '')


def words(db, p):
    """(thought, diary) written earlier today for this Seedling, or ('', ''). Only reads, so it is safe inside the game lock."""
    try:
        if not ai.enabled('seedling'):
            return '', ''
        return parse_words(ai.kept(db, words_key(p)))
    except Exception:
        logging.getLogger(__name__).exception('Seedling words could not be read; showing the template text')
        return '', ''


def day_start():
    return runtime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def words_prompt(db, p, today):
    """What Claude is told: who the Seedling is, its attitude, mood and surroundings, and today's entries (oldest first)."""
    from . import looks
    found = row(db, p.channel_id, p.twitch_uid)
    mood, weather = (found.mood if found is not None else '') or 'content', ''
    try:
        from .game.life import life_state
        from .game.world import world_clock
        clock = world_clock(db, p.channel_id)
        weather = clock.get('condition', '')
        mood = mood_of(life_state(db, p), clock.get('condition_key', ''), found.failures if found is not None else 0)[0]
    except Exception:
        logging.getLogger(__name__).warning('Seedling words: mood and weather unavailable; using what is stored')
    style = looks.row(db, p)
    attitude = looks.ATTITUDE.get(style.attitude) if style is not None else None
    phrase = looks.CATCHPHRASES.get(style.catchphrase, '') if style is not None else ''
    place = PLACES.get(found.place if found is not None else '', PLACES['residential_ring'])[0]
    lines = [f'Seedling: {_short(clean_name(p.display_name), 40)}',
             f'Attitude: {attitude[0]} ({attitude[1]})' if attitude else 'Attitude: none chosen (plain and friendly)',
             f'Catchphrase: "{phrase}"' if phrase else 'Catchphrase: none',
             f'Mood: {MOODS.get(mood, MOODS["content"])[1]}',
             f"Right now: {_short(found.activity, 60) if found is not None else 'settling in'} at {place}",
             f'Weather: {_short(weather, 40) or "unknown"}', '', "Today's diary entries, oldest first:"]
    for e in today:
        body = e.text.split(' — ', 1)[-1]
        story = e.headline if body in e.headline else f'{e.headline} — {body}'
        where = PLACES[e.place][0] if e.place in PLACES else ''
        lines.append('- ' + _short(story, 220) + (f' ({where})' if where else ''))
    return '\n'.join(lines)


def write_words(db, p):
    """Write today's words if this Seedling has a diary entry today and none were written yet (once a day, through
    ai.written). Returns whether words are kept for today. It makes an API call, so call it outside the game lock (ai refuses
    inside it). Never raises; commits the session (the spent call and the kept text)."""
    try:
        if not ai.enabled('seedling') or ai.locked():
            return False
        key = words_key(p)
        if ai.kept(db, key):
            return True
        today = entries(db, p, WORDS_ENTRIES, day_start())
        if not today:
            return False
        text = ai.written(db, 'seedling', key, WORDS_SYSTEM, words_prompt(db, p, list(reversed(today))), max_tokens=200, timeout=10)
        db.commit()             # also frees the SQLite write lock before the command takes the game lock
        return bool(text)
    except Exception:
        logging.getLogger(__name__).exception('Seedling words could not be written; showing the template text')
        db.rollback()
        return False


def view_text(db, p, provider='discord'):
    from .game.life import life_state
    from .game.world import world_clock
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    clock = world_clock(db, p.channel_id)
    life = life_state(db, p)
    key, reason = refresh_mood(db, p, found, clock, life)
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
             f'💭 *"{words(db, p)[0] or found.thought}"*', '',
             'RIGHT NOW', f"{found.emoji} {found.activity} · {place[1]} {place[0]}"]
    if found.plan:
        lines.append(f'🧠 Thinking: {found.plan}')
    lines += [
             f"{clock['phase_emoji']} {clock['phase']} on Avesta: **{BLOCKS[now_block][1]}** time", '',
             'SCHEDULE', f'{preset_name(found)} — {sched}', '',
             'AUTONOMY', ('On: while you are away, your Seedling follows this schedule and lives by the normal game rules '
                          f'(about one action every {AUTONOMY_MINUTES} minutes). At work it thinks first: your goal\'s next step it can do itself, '
                          'then it takes turns collecting for its job (what it has least of, now and then something new) and training its skills '
                          '(making things from materials it has plenty of, never ones your goal needs). '
                          'It eats, rests and sleeps before its needs get low, and it steps aside while you play.')
             if found.enabled else 'Off: your Seedling waits for you.']
    from . import looks
    styled = looks.describe(looks.row(db, p))
    lines += ['', 'LOOKS & PERSONALITY', ' · '.join(styled) if styled else 'Its original look. Make it yours with /customize: skin, hair, outfit, accessory, attitude and catchphrase.']
    recent = entries(db, p, 3)
    if recent:
        lines += ['', 'LATEST REPORTS'] + [f'{e.emoji} **{e.headline}** — {e.text.split(" — ", 1)[-1]}' for e in recent]
    return '\n'.join(lines)


def diary_text(db, p, provider='discord'):
    from .game.players import as_utc
    rows = entries(db, p, 10 if provider == 'discord' else 3)
    if provider != 'discord':
        return '📓 ' + (' | '.join(f'{e.headline}: {e.text.split(" — ", 1)[-1]}' for e in rows) if rows else f"{p.display_name}'s diary is empty so far.")
    lines = [f'📓 DIARY — {p.display_name.upper()}']
    own = words(db, p)[1]
    if own:
        lines += ['TODAY, IN ITS OWN WORDS', f'*{own}*', '', 'REPORTS']
    lines += ['News from your Seedling\'s day, newest first.', '']
    for e in rows:
        lines.append(f'{e.emoji} **{e.headline}** · <t:{int(as_utc(e.created_at).timestamp())}:R>\n{e.text}')
    if not rows:
        lines.append('Nothing yet. With autonomy on, your Seedling reports here as it lives its day.')
    return '\n'.join(lines)


def away_lines(db, p, since, limit=3):
    """Reports written since `since`, for the welcome-back summary."""
    from .game.players import resource_name
    rows = [e for e in entries(db, p, 40, since) if e.autonomous]
    if not rows:
        return []
    gathered = [e for e in rows if e.desk in {'SUPPLY', 'MINING'} or 'brings in' in e.headline]
    gained, used, sc, _ = haul_since(db, p, since)
    lines = ['📓 **While you were away:**']
    # Exact totals first: every item it brought in, what it earned and what it ate.
    if gained:
        items = sorted(gained.items(), key=lambda kv: (-kv[1], resource_name(kv[0])))
        lines.append(f"🧺 **Collected {sum(gained.values())} items** on {len(gathered)} trip{'s' if len(gathered) != 1 else ''}:")
        lines += [f'• {n} × {resource_name(k)}' for k, n in items]
    if sc > 0:
        lines.append(f'🪙 **Earned {sc} SC**')
    if used:
        lines.append('🍲 Used: ' + ', '.join(f'{n} × {resource_name(k)}' for k, n in sorted(used.items(), key=lambda kv: -kv[1])))
    shown = [f'{e.emoji} {e.headline}' for e in rows[:limit]]
    extra = len(rows) - len(shown)
    lines += ['', '**Latest:**'] + shown if gained or sc > 0 or used else shown
    return lines + ([f'…and {extra} more in your diary.'] if extra > 0 else [])


def status_line(db, p):
    found = row(db, p.channel_id, p.twitch_uid, create=True)
    key, _ = refresh_mood(db, p, found)
    emoji, label, _ = MOODS[key]
    return f'{emoji} {label} · {found.emoji} {found.activity} · 💭 "{found.thought}"'


# ---------------------------------------------------------------- the stream

def say_context(db, source_ids):
    """The shared things Seedlings talk about: time, weather, holiday, the society and the market."""
    from .game.players import market_demand, resource_name
    from .game.rules import SOCIETY_TIERS
    from .game.world import society_tier, world_clock
    context = {'phase': '', 'condition': '', 'holiday': '', 'bucket': int(runtime.now().timestamp() // 600), 'extra': []}
    try:
        clock = world_clock(db, source_ids[0])
        context.update(phase=clock.get('phase', ''), condition=clock.get('condition_key', ''))
        a, b = market_demand(source_ids[0], clock.get('day'))
        context['extra'].append(f'Heard {resource_name(a)} is selling high today.')
    except Exception:
        pass
    try:
        from . import seasonal
        active = seasonal.holidays_active_for(runtime.now().date())
        if active:
            context['holiday'] = active[0]['name']
    except Exception:
        pass
    try:
        rows = list(db.scalars(select(Society).where(Society.channel_id.in_(source_ids))))
        stats = {f: sum(getattr(r, f) for r in rows) for f in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation')}
        low = min(stats, key=stats.get)
        tier = society_tier(Society(**stats))
        index = SOCIETY_TIERS.index(tier)
        if index + 1 < len(SOCIETY_TIERS):
            context['extra'].append(f'We need more {low} to become a {SOCIETY_TIERS[index + 1][0]}.')
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
            'item': activity.partition('Gathering ')[2] or 'material', 'task': activity.partition('Training: ')[2] or 'this'}
    lines = [s.get('thought') or '', s.get('plan') or '']
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


def districts(db, source_ids):
    """How far each district has grown, from the society's tier and stats."""
    from .game.rules import SOCIETY_TIERS
    from .game.world import society_tier
    import math
    rows = list(db.scalars(select(Society).where(Society.channel_id.in_(source_ids))))
    stats = {f: sum(getattr(s, f) for s in rows) for f in ('food', 'materials', 'development', 'knowledge', 'treasury', 'reputation', 'population')}
    total = Society(**stats)
    tier = society_tier(total)
    index = next((i for i, t in enumerate(SOCIETY_TIERS) if t[0] == tier[0]), 0)
    out = {}
    for key, (stat, needs_tier) in GROWTH.items():
        if stat is None:
            level = 2 + index * 2
        elif stat == 'population':
            level = 1 + min(11, stats['population'] // 2)
        else:
            level = 1 + min(11, int(math.sqrt(max(0, stats[stat]) / 15)))
        out[key] = {'name': PLACES[key][0], 'unlocked': index >= needs_tier, 'level': level,
                    'unlocks_at': SOCIETY_TIERS[needs_tier][0], 'stat': stat or 'tier'}
    return {'tier_index': index, 'tier_name': tier[0], 'districts': out, 'population': stats['population']}


def overlay_data(db, source_ids):
    from .game.players import as_utc
    since = runtime.now() - timedelta(days=ACTIVE_DAYS)
    players = list(db.scalars(select(Player).where(Player.channel_id.in_(source_ids), Player.last_seen >= since)
                              .order_by(Player.last_seen.desc()).limit(40)))
    lives = {(r.channel_id, r.canonical_uid): r for r in db.scalars(select(SeedlingLife).where(SeedlingLife.channel_id.in_(source_ids)))}
    seedlings = []
    for p in players:
        found = lives.get((p.channel_id, p.twitch_uid))
        place = found.place if found is not None and found.place in PLACES else 'residential_ring'
        mood = found.mood if found is not None and found.mood in MOODS else 'content'
        seedlings.append({'id': hashlib.sha1(f'{p.channel_id}:{p.twitch_uid}'.encode()).hexdigest()[:10], 'name': clean_name(p.display_name),
                          'place': place, 'place_name': PLACES[place][0], 'activity': found.activity if found else 'Settling in', 'job': p.job or '',
                          'emoji': found.emoji if found else '🏠', 'mood': MOODS[mood][1], 'mood_emoji': MOODS[mood][0],
                          'thought': found.thought if found else '', 'plan': found.plan if found else ''})
    context = say_context(db, source_ids)
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
                  'place': PLACES.get(e.place, ('', ''))[0], 'at': as_utc(e.created_at).isoformat()} for e in rows]
    return {'seedlings': seedlings, 'narration': narration, 'places': {k: v[0] for k, v in PLACES.items()}, **districts(db, source_ids)}
