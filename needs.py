

"""Passive recovery uses elapsed time; saved legacy timestamps remain compatible."""
from datetime import timedelta, timezone
FIELDS=("energy", "nutrition", "social", "comfort", "morale")
TICK_SECONDS=900
RECOVERY_CAP=60
RECOVERY_PER_TICK=1
RECOVERY_HELP="Life needs recover +1 every 15 real minutes, up to 60/100, including while away. Food, sleep and social activities recover faster."

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
