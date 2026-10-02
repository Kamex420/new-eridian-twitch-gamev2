"""First steps: six small goals that teach the game in its first ten minutes.

Each step counts however the player does it (Twitch, Discord, a button or a queue) and in any
order. Finishing a step pays a small reward straight away and shows the next one. Finishing all
six unlocks the "Settled In" title and a bonus.

  gather   bring in any natural material          craft    craft anything (a Campfire is easiest)
  eat      eat something                          job      choose a job
  queue    start a queue                          seedling look at your Seedling

On !start, new citizens also get a welcome kit (the Lumber for a Campfire and some Berries), and their Seedling
moves in with a first diary entry, so the "it lives without me" hook lands on day one.

Progress is read from what actually changed (the command wrapper's before/after snapshot) or from
saved state, so nothing here changes how any command works. Citizens who were already playing when
this arrived are marked finished without a reward.
"""
import json
from datetime import timedelta
from sqlalchemy import Column, String, Integer, DateTime, select
from .db import Base

STEPS = ['gather', 'craft', 'eat', 'job', 'queue', 'seedling']
# key -> (emoji, goal, how on Discord, how on Twitch, SC reward, item reward {name: qty})
INFO = {
    'gather': ('🧺', 'Gather something', '/gather (Lumber is quick)', '!gather lumber', 10, {}),
    'craft': ('🔥', 'Craft something (a Campfire is easiest)', '/make recipe:Campfire', '!make campfire', 10, {'Lumber': 2}),
    'eat': ('🍲', 'Eat something', '/life action:eat', '!eat berries', 10, {'Berries': 2}),
    'job': ('💼', 'Choose a job', '/job', '!job', 10, {}),
    'queue': ('⏱️', 'Start a queue to work while you watch', '/queue action:start', '!craftmax lumber', 15, {}),
    'seedling': ('🌱', 'Meet your Seedling', '/seedling', '!seedling', 15, {}),
}
FINISH_SC, FINISH_CONTRIBUTION, TITLE = 25, 5, 'settled_in'
WELCOME_KIT = {'Lumber': 2, 'Berries': 4}
# Anyone who had played this much before the path existed counts as finished.
VETERAN_ACTIONS = 25
ENABLED = True     # switch the whole path off (tests that check exact SC and item totals do)


class FirstSteps(Base):
    __tablename__ = 'first_steps_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    done = Column(String(200), nullable=False, default='[]')
    finished = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


def install(m):
    m.TITLE_DEFS.setdefault(TITLE, 'Settled In')


def row(m, db, p, create=True):
    found = db.get(FirstSteps, (p.channel_id, p.twitch_uid))
    if found is None and create:
        veteran = (p.actions or 0) >= VETERAN_ACTIONS
        found = FirstSteps(channel_id=p.channel_id, canonical_uid=p.twitch_uid, done=json.dumps(STEPS if veteran else []),
                           finished=int(veteran), created_at=m.now())
        db.add(found)
        db.flush()
    return found


def done_of(found):
    return [s for s in json.loads(found.done or '[]') if s in STEPS]


def _cmd(key, provider):
    if provider == 'discord':
        return INFO[key][2]
    from . import twitch_lite
    return twitch_lite.step_command(key, INFO[key][3])     # crafting and queues are Discord-only when Twitch is lite


def next_step(found):
    left = [s for s in STEPS if s not in done_of(found)]
    return left[0] if left else None


def line(m, db, p, provider='discord'):
    """One line: progress and the next step, with that platform's command. Empty once finished."""
    if not ENABLED:
        return ''
    found = row(m, db, p)
    if found.finished:
        return ''
    nxt = next_step(found)
    return f"🧭 First steps {len(done_of(found))}/{len(STEPS)} · next: {INFO[nxt][1]} — {_cmd(nxt, provider)}"


def status(m, db, p, provider='discord'):
    """One line for chat, or a short checklist for Discord."""
    if not ENABLED:
        return ''
    found = row(m, db, p)
    if found.finished:
        return ''
    done = done_of(found)
    nxt = next_step(found)
    if provider != 'discord':
        return line(m, db, p, provider)
    lines = [f'🧭 **FIRST STEPS {len(done)}/{len(STEPS)}**']
    for s in STEPS:
        emoji, goal, _, _, sc, items = INFO[s]
        reward = f'+{sc} SC' + ''.join(f', +{n} {name}' for name, n in items.items())
        mark = '✅' if s in done else ('➡️' if s == nxt else '▫️')
        lines.append(f'{mark} {emoji} {goal}' + ('' if s in done else f' — `{_cmd(s, provider)}` · {reward}'))
    lines.append(f'Finish all six: +{FINISH_SC} SC, +{FINISH_CONTRIBUTION} Contribution and the **Settled In** title.')
    return '\n'.join(lines)


def complete(m, db, p, keys, provider='discord'):
    """Mark steps done, pay their rewards, and return the note to show (empty when nothing new)."""
    if not ENABLED:
        return ''
    found = row(m, db, p)
    if found.finished:
        return ''
    done = done_of(found)
    new = [k for k in dict.fromkeys(keys) if k in STEPS and k not in done]      # each step pays once
    if not new:
        return ''
    notes = []
    for k in new:
        emoji, goal, _, _, sc, items = INFO[k]
        p.sc += sc
        for name, n in items.items():
            m.material_change(db, p, m.seed_content.key(name), n)
        got = f'+{sc} SC' + ''.join(f', +{n} {name}' for name, n in items.items())
        notes.append(f'{emoji} {goal.split(" (")[0]} ✅ {got}')
        done.append(k)
    found.done = json.dumps(done)
    count = len(done)
    if count >= len(STEPS):
        found.finished = 1
        p.sc += FINISH_SC
        p.contribution += FINISH_CONTRIBUTION
        m.unlock_title(db, p, TITLE)
        if provider != 'discord':
            return f"🎓 First steps done! +{FINISH_SC} SC, Settled In title"
        return (f"🎓 First steps {count}/{len(STEPS)}! " + ' · '.join(notes)
                + f" — all done: +{FINISH_SC} SC, +{FINISH_CONTRIBUTION} Contribution and the Settled In title. You know the basics of New Eridian!")
    nxt = next_step(found)
    if provider != 'discord':
        paid = sum(INFO[k][4] for k in new)
        return f"🎓 {count}/{len(STEPS)} +{paid} SC · next: {_cmd(nxt, provider)}"
    return f"🎓 First steps {count}/{len(STEPS)}: " + ' · '.join(notes) + f" · Next: {INFO[nxt][1]} — {_cmd(nxt, provider)}"


def _gathered(m, before, after):
    """A natural material went up (gathering or mining, by hand or by a queue)."""
    b, a = before.get('Resources', {}), after.get('Resources', {})
    return any(a.get(k, 0) > b.get(k, 0) for k in a if k in m.seed_content.GATHER)


def _ate(m, before, after):
    b, a = before.get('Needs', {}), after.get('Needs', {})
    eaten = any(after['Resources'].get(k, 0) < before['Resources'].get(k, 0) for k in before.get('Resources', {}) if k in m.seed_content.EDIBLE)
    return a.get('nutrition', 0) > b.get('nutrition', 0) and eaten


def _crafted(m, db, p):
    return db.execute(select(m.CraftLedger).where(m.CraftLedger.channel_id == p.channel_id, m.CraftLedger.canonical_uid == p.twitch_uid,
                                                  m.CraftLedger.qty > 0)).scalars().first() is not None


def from_state(m, db, p):
    """Steps visible in saved state, whenever they happened."""
    keys = []
    if p.job and p.job != 'settler':
        keys.append('job')
    if db.get(m.task_queue.TaskQueue, (p.channel_id, p.twitch_uid)) is not None:
        keys.append('queue')
    if _crafted(m, db, p):
        keys.append('craft')
    return keys


def after_command(m, db, p, fn_name, params, before, after):
    """Called by the command wrapper after every command: what changed, plus saved state."""
    found = row(m, db, p)
    if found.finished:
        return ''
    keys = from_state(m, db, p)
    if before and after:
        if _gathered(m, before, after):
            keys.append('gather')
        if _ate(m, before, after):
            keys.append('eat')
    if fn_name in {'seedling_view', 'seedling_diary'}:
        keys.append('seedling')
    return complete(m, db, p, keys, params.get('provider') or 'twitch')


def mark(m, db, p, key, provider='twitch'):
    """For commands outside the wrapper (queue start, Seedling view)."""
    return complete(m, db, p, [key] + from_state(m, db, p), provider)


def welcome(m, db, p):
    """On !start / /start: a new citizen gets the welcome kit, their Seedling moves in and writes its first
    diary entry. Once per citizen; False (nothing given) for anyone who already had it or already plays."""
    found_steps = row(m, db, p)
    if found_steps.finished or 'kit' in json.loads(found_steps.done or '[]'):
        return False
    for name, n in WELCOME_KIT.items():
        m.material_change(db, p, m.seed_content.key(name), n)
    from . import autonomy
    found = autonomy.row(db, p.channel_id, p.twitch_uid, create=True)
    found.activity, found.emoji, found.place = 'Moving in', '📦', 'residential_ring'
    found.next_at = m.now() + timedelta(minutes=autonomy.AWAY_MINUTES)
    name = autonomy.clean_name(p.display_name)
    day = m.world_clock(db, p.channel_id)['day']
    autonomy.diary(m, db, p, 'residential_ring', '📦',
                   f'RESIDENTIAL RING, Day {day} — {name} arrived in New Eridian today and moved into a small home in the Residential Ring. '
                   f'Their Seedling unpacked a welcome kit: 2 Lumber, enough for a first Campfire, and 4 Berries.',
                   desk='ARRIVALS', headline=f'{name} arrives in New Eridian')
    found_steps.done = json.dumps(json.loads(found_steps.done or '[]') + ['kit'])
    return True


def _craft_hint():
    from . import twitch_lite
    return f' Crafting is on Discord: {twitch_lite.invite()}' if twitch_lite.ENABLED else ' Then !make campfire.'


def welcome_text(m, db, p, provider):
    kit = ', '.join(f'{n} {name}' for name, n in WELCOME_KIT.items())
    if provider != 'discord':
        return (f"🌱 Welcome to New Eridian, {p.display_name}! Your Seedling just moved in and you're on the stream map now. "
                f"Welcome kit: {kit}. First step: !gather lumber." + _craft_hint())
    return (f"🌱 **Welcome to New Eridian, {p.display_name}!**\nYour Seedling just moved into the Residential Ring, and you are now on the stream map.\n"
            f"🎁 Welcome kit: {kit}. That is enough for a Campfire and a snack.\n\n" + status(m, db, p, provider)
            + "\n\nℹ️ New Eridian v2 is a free, unofficial fan project by Kamex, not affiliated with Klang Games. Help → About has the details.")
