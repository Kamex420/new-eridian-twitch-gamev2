"""Passive recovery uses elapsed time; saved legacy timestamps remain compatible.

Work costs are defined here so every command, queue forecast and message uses
the same numbers. Comfort drains at the same rate as Energy; /sleep refills it
but is on a long timer, which makes relaxing, furniture, baths and clothing
worth using between sleeps.
"""
import os
from datetime import timedelta, timezone
FIELDS=("energy", "nutrition", "social", "comfort", "morale")
TICK_SECONDS=900
RECOVERY_CAP=60
RECOVERY_PER_TICK=1
RECOVERY_HELP="Life needs recover +1 every 15 real minutes, up to 60/100, including while away. Food, sleep and social activities recover faster."

# Work costs. Heavy work spends more Energy; Comfort drains 1 per Energy spent.
STANDARD_ENERGY=2
HEAVY_ENERGY=3
NUTRITION_PER_TASK=1
COMFORT_PER_ENERGY=1
RELAX_COMFORT=20
HEAVY_ACTIONS=frozenset({"mine","rare","repair","project","explore","survey","machine","work"})

# Minimum needs before an attempt. Comfort has a warning band before it blocks.
TASK_NEED_MINIMUM=20
COMFORT_SLOW=20
COMFORT_BLOCK=10


def _env_minutes(name, default):
    try:return max(1,int(os.getenv(name, str(default))))
    except (TypeError, ValueError):return default


SLEEP_COOLDOWN_SECONDS=_env_minutes("SLEEP_COOLDOWN_MINUTES", 30)*60
COMFORT_FIXES_DISCORD="/relax, or /use a bed, seat, bath, clothing item or Comfort Pack"
COMFORT_FIXES_TWITCH="!relax or !use <bed, seat, bath or clothing item>"


def work_energy(action):
    return HEAVY_ENERGY if action in HEAVY_ACTIONS else STANDARD_ENERGY


def comfort_cost(energy):
    return max(0,int(energy))*COMFORT_PER_ENERGY


def cost_text(energy=STANDARD_ENERGY, sep=" · ", minus="−"):
    """One wording for every receipt, preview and forecast."""
    return sep.join((f"{minus}{energy} Energy", f"{minus}{NUTRITION_PER_TASK} Nutrition", f"{minus}{comfort_cost(energy)} Comfort"))


def duration_text(seconds):
    seconds=max(0,int(seconds))
    if seconds<60:return f"{seconds}s"
    minutes,rest=divmod(seconds,60)
    if minutes<60:return f"{minutes}m {rest:02d}s" if rest else f"{minutes}m"
    hours,minutes=divmod(minutes,60)
    return f"{hours}h {minutes:02d}m"


def decay(row, current):
    """Compatibility name: replace passive decay with bounded recharge.

    Advance the clock even at the cap, so elapsed time cannot be banked and
    spent repeatedly. Preserve partial ticks and never lower needs above 60.
    No rewards, inventory spending or player actions are awarded by recovery.
    """
    last=row.last_decay_at
    if last.tzinfo is None:last=last.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    elapsed=max(0,int((current-last).total_seconds()//TICK_SECONDS))
    if not elapsed:return False
    for key in FIELDS:
        value=getattr(row,key)
        if value<RECOVERY_CAP:
            setattr(row,key,min(RECOVERY_CAP,value+elapsed*RECOVERY_PER_TICK))
    row.last_decay_at=last+timedelta(seconds=elapsed*TICK_SECONDS)
    row.updated_at=current
    return True

def productivity(life, exposure=0):
    score=1.0
    for key in FIELDS:
        value=getattr(life,key)
        if value<20:score-=.15 if key=="comfort" else .10
        elif value<35:score-=.05
    score-=min(.20,exposure/500)
    return max(.35,min(1.0,score))

def urgency(life):return {key:100-getattr(life,key) for key in FIELDS}

def mood(life):
    if min(life.nutrition,life.energy)<20:return "Recovering"
    if life.comfort<20 or life.morale<20:return "Stressed"
    if life.social<35:return "Lonely"
    return "Inspired" if min(life.morale,life.comfort)>=80 else "Steady"


def blocked_needs(life):
    """(field, label, value, minimum) for every need that stops work."""
    rows=[(key,key.title(),getattr(life,key),TASK_NEED_MINIMUM) for key in ("energy","nutrition","social") if getattr(life,key)<TASK_NEED_MINIMUM]
    if life.comfort<COMFORT_BLOCK:rows.append(("comfort","Comfort",life.comfort,COMFORT_BLOCK))
    return rows


def finish_forecast(energy, count):
    """Starting needs that let `count` attempts run without any recovery."""
    count=max(1,int(count))
    return {"energy":TASK_NEED_MINIMUM+energy*(count-1),
            "nutrition":TASK_NEED_MINIMUM+NUTRITION_PER_TASK*(count-1),
            "social":TASK_NEED_MINIMUM,
            "comfort":COMFORT_BLOCK+comfort_cost(energy)*(count-1)}
