"""Pure needs policy. Four-hour ticks preserve remainder; catch-up is bounded."""
from datetime import timedelta, timezone
FIELDS=("energy", "nutrition", "social", "comfort", "morale")
RATES={"energy":1,"nutrition":1,"social":1,"comfort":2,"morale":1}
TICK_SECONDS=14400
MAX_TICKS=6

def decay(row, current):
    last=row.last_decay_at
    if last.tzinfo is None: last=last.replace(tzinfo=timezone.utc)
    elapsed=max(0,int((current-last).total_seconds()//TICK_SECONDS))
    if not elapsed:return False
    steps=min(MAX_TICKS,elapsed)
    for key,rate in RATES.items():setattr(row,key,max(0,min(100,getattr(row,key)-steps*rate)))
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
