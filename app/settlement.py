"""Shared stocks supplement, rather than replace, the legacy society ledger."""
from datetime import timezone, timedelta
from sqlalchemy import select
from .models import SettlementState, SeedlingState
STOCKS=("water","ore","rare_ore","components","medicines","cargo","infrastructure","housing","mood")
CORE=("food","materials","development","knowledge","treasury","reputation")

def state(db,channel):
    row=db.get(SettlementState,channel)
    if row is None:
        row=SettlementState(channel_id=channel);db.add(row);db.flush()
    return row

def seedling(db,p):
    row=db.get(SeedlingState,(p.channel_id,p.twitch_uid))
    if row is None:
        row=SeedlingState(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row);db.flush()
    return row

def tick(row,s,current):
    last=row.last_tick
    if last.tzinfo is None:last=last.replace(tzinfo=timezone.utc)
    elapsed=max(0,int((current-last).total_seconds()//14400))
    if not elapsed:return
    steps=min(6,elapsed);demand=max(1,min(10,s.population//4+1))
    row.water=max(0,row.water-steps*demand)
    s.food=max(0,s.food-steps*demand)
    if row.water==0 or s.food==0:row.mood=max(0,row.mood-steps)
    row.last_tick=last+timedelta(seconds=elapsed*14400)

def pressures(row,s,exposure=0):
    values={}
    if row.water<max(2,s.population):values["water shortage"]=-.04
    if row.housing<s.population:values["housing pressure"]=-.03
    if row.mood<35:values["community morale"]=-.04
    if row.infrastructure==0 and s.population>4:values["habitat decline"]=-.03
    if s.treasury<max(1,s.population//2):values["market disruption"]=-.02
    if exposure>=40:values["Siro exposure"]=-min(.12,exposure/800)
    return values

def produce(row,s,action,efficiency=1.0):
    """Optional supply chains. No free conversion when inputs are absent.

    Existing personal rewards remain separate. Poor conditions reduce the shared
    production yield from two to one, never consume more than current stock.
    """
    units=2 if efficiency>=.85 else 1
    note=[]
    def add(key,amount):
        setattr(row,key,getattr(row,key)+amount);note.append(f"{key.replace('_',' ')} {amount:+d}")
    def consume(key):
        if getattr(row,key)<1:return False
        add(key,-1);return True
    if action in {"water","scan"}:add("water",units+1)
    elif action in {"farm","harvest","forage"}:
        if consume("water"):s.food+=units;note.append(f"food +{units}")
        else:note.append("dry fields: no irrigated surplus; use water work")
    elif action in {"mine","scavenge"}:add("ore",units)
    elif action=="rare":add("rare_ore",1)
    elif action in {"make","craft","machine","work"}:
        if consume("ore"):add("components",units)
        else:note.append("workshop awaiting shared ore; mine to supply it")
    elif action in {"build","repair","project"}:
        if consume("components"):
            add("infrastructure",units)
            if row.infrastructure//5>(row.infrastructure-units)//5:add("housing",1)
        else:note.append("habitat awaiting shared components")
    elif action=="research":
        if consume("components"):add("medicines",units)
    elif action in {"cargo","spaceport"}:
        if consume("components"):add("cargo",units)
    elif action=="delivery":
        if consume("cargo"):s.reputation+=units;note.append(f"reputation +{units}")
    elif action in {"market","business","businesscontract"}:
        if consume("cargo"):s.treasury+=units;note.append(f"treasury +{units}")
    elif action=="eat" and s.food>0:
        s.food-=1;note.append("food -1 (community meal)")
    elif action=="sleep" and row.medicines>0:add("medicines",-1)
    return "; ".join(note)
