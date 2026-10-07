"""Trick-or-treat: knock on New Eridian's doors during the Halloween festival, up to TRIES_PER_DAY times a day.

Each knock is a treat (an ingredient, a little SC, or now and then a Halloween festival food) or a harmless
trick (a joke and +1 Morale). It costs no needs and starts no cooldown; only the daily count limits it.
Discord: /life action:Trick-or-treat or Menu → Life → Trick-or-treat. Twitch: !trick.

Depends on: the game's bag (cooldowns_materials), needs (life), item names (players) and the clock (runtime); it reads
nothing else from app.main. The game imports this module while it loads, so those imports sit inside the functions.
"""
import random
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer

from .db import Base, engine
from . import seasonal, runtime, stream_overlay

HOLIDAY = 'Halloween'
TRIES_PER_DAY = 5
TRICK, BIG_TREAT, SC_TREAT = 0.20, 0.30, 0.45      # cumulative chances; the rest is an ingredient treat
INGREDIENTS = ('Pumpkin', 'Nuts', 'Berries', 'Corn', 'Herbs')
COSTUMES = ('a ghost', 'a witch', 'Rocky', 'a Siro spore', 'a pumpkin', 'an astronaut', 'a Duck Delivery Drone', 'a skeleton',
            'a very small vampire', 'a scarecrow')
TRICKS = (
    'A sheet-covered “ghost” leaps out. It is Rocky. Rocky is very pleased with himself.',
    'Your treat bag comes back full of pebbles. Rocky calls them gifts.',
    'Someone swapped your candy for Stone Dust. Classic.',
    'A Duck Delivery Drone honks, steals your hat, circles twice and drops it back on your head.',
    'The porch light flickers and something cackles… it was the Medical Fabricator rebooting.',
    'The door opens on a fog machine and nobody else. You hear giggling from the bushes.',
    'You get a pat on the head and a lecture about dental care. Dentistry trainees are everywhere tonight.',
    'Your costume gets stuck. You are a pumpkin now. Honestly, it suits you.',
)


class TrickOrTreat(Base):
    """How many doors a citizen knocked on each day (UTC). Old days are simply never read again."""
    __tablename__ = 'trick_or_treat_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    day = Column(String(10), primary_key=True)
    tries = Column(Integer, nullable=False, default=0)


def install(m=None):
    """The wiring hook every system has; this one needs nothing from app.main."""
    TrickOrTreat.__table__.create(engine, checkfirst=True)


def _today():
    return runtime.now().astimezone(timezone.utc).date()


def open_now(today=None):
    return any(f['name'] == HOLIDAY for f in seasonal.holidays_active_for(today))


def tries_left(db, p):
    row = db.get(TrickOrTreat, (p.channel_id, p.twitch_uid, _today().isoformat()))
    return TRIES_PER_DAY - (row.tries if row else 0)


def _closed_text(provider):
    start, _ = seasonal.festival_window(HOLIDAY, _today())
    where = '/world → Holidays' if provider == 'discord' else '!holiday'
    return (f'🎃 Trick-or-treating opens with the Halloween festival on {start.strftime("%B")} {start.day}. '
            f'Until then the doors stay shut. {where} shows what is on now.')


def trick(db, p, provider='discord', roll=None):
    """Knock on one door. `roll` (0–1) picks the outcome in tests."""
    from .game.players import resource_name
    from .game.life import life_state
    from .game.cooldowns_materials import material_change
    from .seed_content import find_item
    if not open_now(_today()):
        return _closed_text(provider)
    day = _today().isoformat()
    row = db.get(TrickOrTreat, (p.channel_id, p.twitch_uid, day))
    if row is None:
        row = TrickOrTreat(channel_id=p.channel_id, canonical_uid=p.twitch_uid, day=day, tries=0)
        db.add(row)
    if row.tries >= TRIES_PER_DAY:
        return (f'🎃 You have knocked on {TRIES_PER_DAY} doors today, and the porch lights are off. '
                'More doors open at midnight UTC (8 PM Eastern).')
    row.tries += 1
    left = TRIES_PER_DAY - row.tries
    costume = random.choice(COSTUMES)
    roll = random.random() if roll is None else roll
    head = f'🎃 {p.display_name} goes door to door dressed as {costume}.'
    if roll < TRICK:
        life = life_state(db, p)
        life.morale = min(100, life.morale + 1)
        body = f'🃏 **TRICK!** {random.choice(TRICKS)} (+1 Morale from laughing)'
    elif roll < BIG_TREAT:
        key = random.choice([k for k, v in seasonal.FESTIVAL_ITEMS.items() if v['holiday'] == HOLIDAY])
        material_change(db, p, key, 1)
        body = f'🍬 **BIG TREAT!** Someone hands over a whole {resource_name(key)}! (+1 {resource_name(key)})'
        stream_overlay.highlight(db, p.channel_id, 'holiday', f'{p.display_name} got a {resource_name(key)} trick-or-treating',
                                 f'Dressed as {costume}. Type !trick to knock on a door.', p.display_name, emoji='🎃')
    elif roll < SC_TREAT:
        sc = random.randint(2, 5)
        p.sc += sc
        body = f'🍬 **TREAT!** A shiny handful of coins: +{sc} SC.'
    else:
        name = random.choice(INGREDIENTS)
        key = find_item(name)
        amount = random.randint(1, 2)
        material_change(db, p, key, amount)
        body = f'🍬 **TREAT!** +{amount} {resource_name(key)}.'
    doors = f'{left} door{"s" if left != 1 else ""} left today' if left else 'That was your last door today'
    if provider != 'discord':
        return f'{head} {body.replace("**", "")} | {doors}.'
    return f'{head}\n{body}\n{doors} · {TRIES_PER_DAY} a day while the Halloween festival is on.'
