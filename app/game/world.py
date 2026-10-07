"""Society Directive, event aftermath, relationships, the world clock and weather, statuses, society projects, goals,
shortages, encounters, housing and society tiers.
"""
import hashlib
import math
import random
from datetime import timedelta
from sqlalchemy import func, select
from ..needs import (
    blocked_needs, COMFORT_BLOCK, COMFORT_FIXES_DISCORD, COMFORT_FIXES_TWITCH, COMFORT_SLOW,
    cost_text as need_cost_text, duration_text, HEAVY_ENERGY, RECOVERY_HELP, SLEEP_COOLDOWN_SECONDS, TASK_NEED_MINIMUM)
from ..occupations import matches as occupation_matches
from ..settlement import pressures as colony_pressures, state as colony_state, tick as colony_tick
from ..models import RealActivity
from ..models import (
    ActionLog, CollectionItem, DirectiveParticipant, DirectiveProgress, GearFamiliarity, JournalEntry,
    LifeRelationship, LoreDiscovery, Player, PlayerGoal, PlayerWorld, QualityGear, RelationshipMemory,
    SocietyAftermath, SocietyProject, StatusEffect, WorldClock)
from .base import AVESTA_DAY_SECONDS
from .rules import (
    COLLECTIBLES, DIRECTIVES, DISTRICTS, ENCOUNTERS, LORE_FRAGMENTS, NPCS, PERSONAL_GOALS, PROJECTS, QUALITY_RECIPES,
    SHIFT_ROLES, SKILL_LABELS, SOCIETY_TIERS, WORLD_CONDITIONS, WORLD_PHASES)
from .players import as_utc, check_collection_sets, clamp100, skill_xp, society
from .life import life_label, life_state
from .. import main      # app.main: names from later modules and settings changed at runtime

def directive_for(db,channel,day):
    row=db.execute(select(DirectiveProgress).where(DirectiveProgress.channel_id==channel,DirectiveProgress.avesta_day==day)).scalar_one_or_none()
    if not row:
        cfg=DIRECTIVES[_stable_index(f"{channel}:{day}:directive",len(DIRECTIVES))]
        goal=max(10,min(24,10+2*active_player_count(db,channel)))
        row=DirectiveProgress(channel_id=channel,avesta_day=day,directive_key=cfg[0],progress=0,goal=goal,complete=False);db.add(row);db.commit();db.refresh(row)
    cfg=next((x for x in DIRECTIVES if x[0]==row.directive_key),DIRECTIVES[0])
    return row,cfg

def directive_note(db,p,s,skill,clock):
    if not skill:return ""
    row,cfg=directive_for(db,p.channel_id,clock["day"])
    if row.complete or skill not in cfg[2]:return ""
    part=db.execute(select(DirectiveParticipant).where(DirectiveParticipant.channel_id==p.channel_id,DirectiveParticipant.canonical_uid==p.twitch_uid,DirectiveParticipant.avesta_day==clock["day"])).scalar_one_or_none()
    if not part:
        part=DirectiveParticipant(channel_id=p.channel_id,canonical_uid=p.twitch_uid,avesta_day=clock["day"],contributions=0);db.add(part)
    row.progress=min(row.goal,row.progress+1);part.contributions+=1
    personal=""
    if part.contributions<=3:p.sc+=1;personal=" +1 SC participation."
    if row.progress>=row.goal:
        row.complete=True;setattr(s,cfg[3],getattr(s,cfg[3])+cfg[4]);p.contribution+=2
        db.commit();return f" 📣 {cfg[1]} COMPLETE {row.progress}/{row.goal}: New Eridian +{cfg[4]} {cfg[3].title()}; +2 Contribution.{personal}"
    db.commit();return f" 📣 {cfg[1]} {row.progress}/{row.goal}.{personal}"

def set_event_aftermath(db,channel,cfg,result):
    from ..events import incident_effect
    incident_effect(colony_state(db,channel),cfg["primary"],result)
    positive=result=="success";modifier=3 if positive else (-1 if result=="partial" else -2)
    description=(f"Successful {cfg['name']} response is supporting related work." if positive else
                 f"Recovery from {cfg['name']} is complicating related work.")
    db.add(SocietyAftermath(channel_id=channel,event_name=cfg["name"],result=result,
                            skills=",".join(sorted({cfg["primary"],cfg["support"]})),modifier=modifier,
                            description=description,expires_at=main.now()+timedelta(minutes=60)))
    db.commit()

def aftermath_modifier(db,channel,skill):
    rows=db.execute(select(SocietyAftermath).where(SocietyAftermath.channel_id==channel,SocietyAftermath.expires_at>main.now())).scalars().all()
    matching=[r for r in rows if skill in set(r.skills.split(","))]
    if not matching:return 0,[]
    # Only the newest relevant aftermath applies; effects never stack.
    row=max(matching,key=lambda x:as_utc(x.expires_at));return row.modifier/100,[f"{row.event_name} aftermath {row.modifier:+d}%"]

def gear_familiarity_rank(uses):
    if uses>=50:return "Trusted",.15
    if uses>=25:return "Practiced",.10
    if uses>=10:return "Familiar",.05
    return "New",0

def gear_familiarity_use(db,p,skill):
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0,QualityGear.condition>0)).scalars().all()
    relevant=[r for r in rows if skill in QUALITY_RECIPES.get(r.item_key,{}).get("skills",{})]
    notes=[]
    for gear in relevant:
        row=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==p.channel_id,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==gear.item_key)).scalar_one_or_none()
        if not row:row=GearFamiliarity(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=gear.item_key,uses=0);db.add(row)
        old=gear_familiarity_rank(row.uses)[0];row.uses+=1;new=gear_familiarity_rank(row.uses)[0]
        if old!=new:notes.append(f" 🛠️ {gear.item_name} familiarity: {new} ({row.uses} uses); wear chance reduced.")
    db.commit();return "".join(notes)

def relationship_memory(db,channel,a,b,activity):
    a,b=relationship_pair(a,b)
    row=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==channel,RelationshipMemory.uid_a==a,RelationshipMemory.uid_b==b)).scalar_one_or_none()
    if not row:row=RelationshipMemory(channel_id=channel,uid_a=a,uid_b=b,interactions=0);db.add(row)
    row.interactions+=1;row.last_activity=activity[:48];row.last_at=main.now();db.commit()
    return row

def near_milestone_note(db,p,skill):
    if not skill:return ""
    from ..competencies import next_level_xp
    xp=skill_xp(p,skill);threshold=next_level_xp(xp)
    if threshold and threshold-xp<=3:return f" 🔔 {SKILL_LABELS[skill]} is {threshold-xp} XP from its next milestone."
    return ""

def maybe_lore_discovery(db,p,skill,clock):
    if not skill or random.random()>=.035:return ""
    owned={x.lore_key for x in db.execute(select(LoreDiscovery).where(LoreDiscovery.channel_id==p.channel_id,LoreDiscovery.canonical_uid==p.twitch_uid)).scalars().all()}
    available=[x for x in LORE_FRAGMENTS if x not in owned]
    if not available:return ""
    key=available[_stable_index(f"{p.twitch_uid}:{clock['day']}:{p.actions}:{skill}",len(available))]
    db.add(LoreDiscovery(channel_id=p.channel_id,canonical_uid=p.twitch_uid,lore_key=key));db.commit()
    journal_add(db,p,"Lore: "+LORE_FRAGMENTS[key]);return f" 📜 Lore discovered ({len(owned)+1}/{len(LORE_FRAGMENTS)}): {LORE_FRAGMENTS[key]}"

def relationship_pair(a,b):
    return tuple(sorted((str(a),str(b))))

def relationship_label(points):
    if points>=300:return "Close Companion"
    if points>=180:return "Trusted Friend"
    if points>=90:return "Friend"
    if points>=35:return "Familiar"
    if points>=10:return "Acquaintance"
    return "Stranger"

def effective_relationship(db,row):
    memory=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==row.channel_id,RelationshipMemory.uid_a==row.uid_a,RelationshipMemory.uid_b==row.uid_b)).scalar_one_or_none()
    weeks=max(0,int((main.now()-as_utc(memory.last_at)).total_seconds()//604800)) if memory else 0
    return max(0,row.familiarity-min(row.familiarity//2,weeks*5))

def relationship_add(db,channel,a,b,amount):
    a,b=relationship_pair(a,b)
    row=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel,LifeRelationship.uid_a==a,LifeRelationship.uid_b==b)).scalar_one_or_none()
    if not row:row=LifeRelationship(channel_id=channel,uid_a=a,uid_b=b,familiarity=0);db.add(row)
    if amount>0:
        people=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid.in_([a,b]))).scalars().all()
        if any(life_state(db,person).social<20 for person in people):amount=max(1,amount//2)
        shared=colony_state(db,channel);shared.mood=min(100,shared.mood+1)
    row.familiarity=max(0,row.familiarity+amount);db.commit();return row

def find_player_name(db,channel,target):
    wanted=(target or "").strip()
    if not wanted:return None,"Type a player's name."
    if wanted.startswith('citizen:') and wanted[8:].isdigit():
        row=db.execute(select(Player).where(Player.channel_id==channel,Player.id==int(wanted[8:]))).scalar_one_or_none()
        return (row,None) if row else (None,"That citizen is no longer available. Select a player again.")
    # The database narrows by lower-case name first (the whole player list was loaded twice per lookup); casefold
    # keeps the exact matching rules. SQLite's lower() only knows ASCII, so a miss falls back to the full list.
    lowered=func.lower(Player.display_name)
    candidates=db.execute(select(Player).where(Player.channel_id==channel,lowered.startswith(wanted.lower(),autoescape=True))).scalars().all() if wanted.isascii() else []
    if not candidates:candidates=db.execute(select(Player).where(Player.channel_id==channel)).scalars().all()
    matches=[p for p in candidates if p.display_name.casefold()==wanted.casefold()]
    if not matches:
        # unique prefix fallback makes Twitch names easier without risky fuzzy matching
        prefix=[p for p in candidates if p.display_name.casefold().startswith(wanted.casefold())]
        if len(prefix)==1:return prefix[0],None
        if len(prefix)>1:return None,"That name matches multiple players. Type more of the name."
        return None,f"No New Eridian player named '{wanted}' was found. They need to use /start or !start first."
    if len(matches)>1:return None,"More than one player has that display name. Use a more specific name."
    return matches[0],None

NEED_EMOJI={"energy":"⚡","nutrition":"🍲","social":"🤝","comfort":"🏠","morale":"✨"}

def sleep_status(db,p,provider="discord"):
    """Plain wording for the long sleep timer, reused by every recovery hint."""
    wait=main.action_wait(db,p,"sleep") if p is not None else 0
    command="/sleep" if provider=="discord" else "!sleep"
    if not wait:return f"{command} (ready now)"
    # Discord timestamps count down on their own; chat gets plain text.
    return f"{command} (ready <t:{int(main.now().timestamp()+wait)}:R>)" if provider=="discord" else f"{command} (ready in {duration_text(wait)})"

def need_fix(field,provider="discord",db=None,p=None):
    """The recovery route for one need, identical in gates, guides and queues."""
    discord=provider=="discord"
    sleep=sleep_status(db,p,provider) if db is not None else ("/sleep" if discord else "!sleep")
    return {
        "energy":(f"/relax or {sleep}" if discord else f"!relax or {sleep}"),
        "nutrition":("/eat (a free emergency meal if you own no food)" if discord else "!eat (free emergency meal if you own no food)"),
        "social":("/games or /social" if discord else "!games, !hi <name> or !hangout <name>"),
        "comfort":((COMFORT_FIXES_DISCORD if discord else COMFORT_FIXES_TWITCH)+f", or {sleep}"),
        "morale":("/walk, /hobby or /games" if discord else "!walk, !hobby or !games"),
    }[field]

def comfort_status_line(life):
    if life.comfort<COMFORT_BLOCK:return f"🏠 Comfort {life.comfort}/100 blocks work below {COMFORT_BLOCK}."
    if life.comfort<COMFORT_SLOW:return f"🏠 Comfort {life.comfort}/100 is low: −10% success and −1 Morale per task until it reaches {COMFORT_SLOW}; work stops below {COMFORT_BLOCK}."
    return ""

def life_status_text(db,p,provider):
    life=life_state(db,p);_,notes,_=main.life_modifiers(db,p,None)
    blocked=[f"{NEED_EMOJI[field]} {label} {value}/100 (needs {minimum}) → {need_fix(field,provider,db,p)}" for field,label,value,minimum in blocked_needs(life)]
    warning=comfort_status_line(life) if life.comfort>=COMFORT_BLOCK else ""
    rules=(f"Work, crafting and gear repair need Energy, Nutrition and Social of {TASK_NEED_MINIMUM}+ and Comfort of {COMFORT_BLOCK}+. "
           f"Every task costs {need_cost_text()} (heavy work: {need_cost_text(HEAVY_ENERGY)}). Comfort drains at the same rate as Energy.")
    if provider=="discord":
        effects="\n".join("• "+n for n in notes) if notes else "• No active life penalties."
        readiness=("⛔ WORK BLOCKED\n"+"\n".join("• "+x for x in blocked)
                   if blocked else
                   "✅ READY FOR WORK"+("\n• "+warning if warning else ""))
        return (f"🌱 {p.display_name} — Seedling Life\n\n"
                f"⚡ Energy: {life.energy}/100 · {life_label(life.energy,'energy')}\n"
                f"🍲 Nutrition: {life.nutrition}/100 · {life_label(life.nutrition,'nutrition')}\n"
                f"🤝 Social: {life.social}/100 · {life_label(life.social,'social')}\n"
                f"🏠 Comfort: {life.comfort}/100 · {life_label(life.comfort,'comfort')}\n"
                f"✨ Morale: {life.morale}/100 · {life_label(life.morale,'morale')}\n\n"
                f"TASK READINESS\n{readiness}\n{rules}\n\n"
                f"RECOVERY\n• Energy: {need_fix('energy',provider,db,p)}\n• Comfort: {need_fix('comfort',provider,db,p)}\n"
                f"• Sleep fully restores Energy and Comfort once every {duration_text(SLEEP_COOLDOWN_SECONDS)}.\n• {RECOVERY_HELP}\n\n"
                f"ACTIVE EFFECTS\n{effects}")
    readiness=("Work BLOCKED: "+"; ".join(blocked)) if blocked else f"Work READY"+(f" ({warning})" if warning else "")
    return (f"🌱 {p.display_name} | ⚡{life.energy} Energy · 🍲{life.nutrition} Nutrition · 🤝{life.social} Social · "
            f"🏠{life.comfort} Comfort · ✨{life.morale} Morale | {readiness} | Sleep: {sleep_status(db,p,provider)} | Recharge +1/15min to 60"+(" | "+", ".join(notes[:3]) if notes else ""))


def _stable_index(text,count):
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12],16)%count

_WEATHER_TRACK={}
def weather_index(channel,day,phase_index):
    """Weather changes with every phase (four times an Avesta day) and never repeats back to back:
    one continuous track where each phase steps 1..n-1 places on from the one before. Steps are cached per world."""
    n=len(WORLD_CONDITIONS);slot=max(0,day*len(WORLD_PHASES)+phase_index)
    track=_WEATHER_TRACK.setdefault(channel,[_stable_index(f"{channel}:weather",n)])
    while len(track)<=slot:
        k=len(track);track.append((track[-1]+1+_stable_index(f"{channel}:{k}:weather-step",n-1))%n)
    return track[slot]

def world_clock(db,channel,s=None):
    s=s or society(db,channel)
    row=db.execute(select(WorldClock).where(WorldClock.channel_id==channel)).scalar_one_or_none()
    if not row:
        row=WorldClock(channel_id=channel,anchor_at=main.now(),anchor_day=max(1,s.day))
        db.add(row);db.commit();db.refresh(row)
    elapsed=max(0,(main.now()-as_utc(row.anchor_at)).total_seconds())
    day=max(1,row.anchor_day+int(elapsed//AVESTA_DAY_SECONDS))
    sec=int(elapsed%AVESTA_DAY_SECONDS);hour=(sec/AVESTA_DAY_SECONDS)*24
    phase=next((p for p in WORLD_PHASES if p[1]<=hour<p[2]),WORLD_PHASES[-1])
    if s.day!=day:
        s.day=day;db.commit()
    condition=WORLD_CONDITIONS[weather_index(channel,day,WORLD_PHASES.index(phase))]
    return {"day":day,"seconds":sec,"hour":hour,"phase":phase[0],"phase_emoji":phase[3],
            "condition_key":condition[0],"condition":condition[1],"condition_text":condition[2]}

def player_world(db,p):
    row=db.execute(select(PlayerWorld).where(PlayerWorld.channel_id==p.channel_id,PlayerWorld.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=PlayerWorld(channel_id=p.channel_id,canonical_uid=p.twitch_uid)
        db.add(row);db.commit();db.refresh(row)
    return row

def phase_action_modifier(clock,action,skill):
    phase=clock["phase"];bonus=0;notes=[]
    if phase=="Morning":
        if skill in {"cultivation","environmental"}:bonus+=.03;notes.append("Morning field conditions +3%")
    elif phase=="Day":
        if skill in {"commerce","logistics","fabrication","infrastructure"}:bonus+=.03;notes.append("Day-shift activity +3%")
    elif phase=="Evening":
        if skill in {"commerce","logistics"}:bonus+=.02;notes.append("Evening traffic +2%")
    elif phase=="Night":
        if skill in {"research","frontier","extraction"}:bonus+=.03;notes.append("Night operations +3%")
        if skill in {"cultivation","environmental"}:bonus-=.06;notes.append("Low-light field work -6%")
    return bonus,notes

def condition_action_modifier(clock,action,skill):
    key=clock["condition_key"];bonus=0;notes=[]
    if key=="good_growing" and skill=="cultivation":bonus+=.04;notes.append("Good Growing Weather +4%")
    elif key=="spore_drift" and skill in {"research","environmental"}:bonus+=.03;notes.append("Siro monitoring opportunity +3%")
    elif key=="dust_winds" and skill in {"frontier","extraction"}:bonus-=.04;notes.append("Dust Winds -4%")
    elif key=="busy_spaceport" and skill in {"logistics","commerce"}:bonus+=.04;notes.append("Busy Spaceport +4%")
    elif key=="water_watch" and skill=="environmental":bonus+=.04;notes.append("Water Watch priority +4%")
    elif key=="sensor_noise" and skill=="research":bonus-=.03;notes.append("Sensor Noise -3%")
    return bonus,notes

def district_modifier(pw,skill):
    bonuses={
        "agricultural_district":"cultivation","industrial_ward":"fabrication","research_block":"research",
        "market_concourse":"commerce","spaceport_quarter":"logistics","frontier_edge":"frontier",
    }
    if bonuses.get(pw.district)==skill:return .01,[f"{DISTRICTS[pw.district]} resident +1%"]
    return 0,[]

def shift_modifier(pw,day,skill):
    if pw.shift_day!=day:return 0,[]
    mapping={"kitchen_duty":"cooking","clinic_duty":"medicine","safety_duty":"emergency","field_duty":"cultivation","spaceport_duty":"logistics","lab_duty":"research",
             "maintenance":"infrastructure","trade_duty":"commerce","survey_duty":"frontier"}
    if mapping.get(pw.shift_role)==skill:return .02,[f"{SHIFT_ROLES[pw.shift_role]} +2%"]
    return 0,[]

def active_statuses(db,p):
    rows=db.execute(select(StatusEffect).where(StatusEffect.channel_id==p.channel_id,StatusEffect.canonical_uid==p.twitch_uid)).scalars().all()
    result=[]
    for row in rows:
        if main.now()>=as_utc(row.expires_at):db.delete(row)
        else:result.append(row)
    db.commit();return result

def add_status(db,p,effect,minutes,modifier,description):
    row=db.execute(select(StatusEffect).where(StatusEffect.channel_id==p.channel_id,StatusEffect.canonical_uid==p.twitch_uid,StatusEffect.effect==effect)).scalar_one_or_none()
    if not row:
        row=StatusEffect(channel_id=p.channel_id,canonical_uid=p.twitch_uid,effect=effect,expires_at=main.now(),modifier=modifier,description=description);db.add(row)
    row.expires_at=max(main.now(),as_utc(row.expires_at))+timedelta(minutes=minutes);row.modifier=modifier;row.description=description
    db.commit();return row

def status_modifier(db,p):
    rows=active_statuses(db,p);total=sum(r.modifier for r in rows)/100
    return total,[f"{r.effect.replace('_',' ').title()} {r.modifier:+d}%" for r in rows if r.modifier]

def trait_data(db,p):
    traits=[];bonus_by_skill={}
    checks=[
        ("Green Thumb","cultivation",p.farm_xp,50),("Deep Delver","extraction",p.mining_xp,50),
        ("Machine Whisperer","fabrication",p.fabrication_xp,50),("Habitat Hand","infrastructure",p.infrastructure_xp,50),
        ("Siro Watcher","research",p.research_xp,50),("Duck Wrangler","logistics",p.delivery_xp,50),
        ("Trailwise","frontier",p.explore_xp,50),("Market Regular","commerce",p.commerce_xp,50),
        ("Waterwise","environmental",p.environmental_xp,50),
    ]
    for name,skill,xp,need in checks:
        if xp>=need:traits.append(name);bonus_by_skill[skill]=bonus_by_skill.get(skill,0)+.01
    return traits,bonus_by_skill

def collection_add(db,p,key,qty=1):
    name=COLLECTIBLES.get(key,key.replace("_"," ").title())
    row=db.execute(select(CollectionItem).where(CollectionItem.channel_id==p.channel_id,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.item_key==key)).scalar_one_or_none()
    first=not bool(row)
    if not row:
        row=CollectionItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=key,item_name=name,qty=0);db.add(row)
    row.qty+=qty;db.commit()
    set_note=check_collection_sets(db,p)
    return name,first,set_note

def journal_add(db,p,entry):
    db.add(JournalEntry(channel_id=p.channel_id,canonical_uid=p.twitch_uid,entry=entry[:220]))
    db.commit()

def current_project(db,channel,day):
    row=db.execute(select(SocietyProject).where(SocietyProject.channel_id==channel)).scalar_one_or_none()
    if not row:
        key,name,goal,skills=PROJECTS[_stable_index(f"{channel}:{day}:project",len(PROJECTS))]
        row=SocietyProject(channel_id=channel,project_key=key,progress=0,goal=goal,started_day=day,completed=0)
        db.add(row);db.commit();db.refresh(row)
    return row

def project_cfg(key):
    return next((x for x in PROJECTS if x[0]==key),PROJECTS[0])

def project_contribute(db,p,skill,amount=1):
    clock=world_clock(db,p.channel_id);row=main.current_project(db,p.channel_id,clock["day"]);cfg=project_cfg(row.project_key)
    if skill not in cfg[3] or row.progress>=row.goal:return ""
    row.progress=min(row.goal,row.progress+amount)
    note=f" 🏗️ {cfg[1]} {row.progress}/{row.goal}."
    if row.progress>=row.goal:
        row.completed+=1
        p.sc+=8;p.contribution+=3
        journal_add(db,p,f"Helped complete the society project {cfg[1]} on Avesta Day {clock['day']}.")
        note+=f" ✅ Project complete! {p.display_name} receives +8 SC/+3 Contribution."
    db.commit();return note

def goal_for(db,p):
    clock=world_clock(db,p.channel_id);day=clock["day"]
    row=db.execute(select(PlayerGoal).where(PlayerGoal.channel_id==p.channel_id,PlayerGoal.canonical_uid==p.twitch_uid,PlayerGoal.day==day)).scalar_one_or_none()
    if not row:
        g=PERSONAL_GOALS[_stable_index(f"{p.twitch_uid}:{day}:goal",len(PERSONAL_GOALS))]
        row=PlayerGoal(channel_id=p.channel_id,canonical_uid=p.twitch_uid,day=day,goal_key=g[0],progress=0,claimed=False);db.add(row);db.commit();db.refresh(row)
    return row,next(g for g in PERSONAL_GOALS if g[0]==row.goal_key)

def goal_progress(db,p,action,skill,social=False,crafted=False,project=False):
    # v5.6: Daily Contract is the single daily objective system.
    # Keep this compatibility hook so old calls do not break.
    return ""

def shortages(s):
    results=[]
    if s.food<20:results.append(("Food Shortage","cultivation",.03))
    if s.materials<20:results.append(("Material Shortage","extraction",.03))
    if s.development<20:results.append(("Maintenance Backlog","infrastructure",.03))
    if s.knowledge<20:results.append(("Knowledge Gap","research",.03))
    if s.treasury<20:results.append(("Treasury Pressure","commerce",.03))
    return results

def shortage_modifier(s,skill):
    for label,target,bonus in shortages(s):
        if target==skill:return bonus,[f"{label}: needed work +{int(bonus*100)}%"]
    return 0,[]

def maybe_world_encounter(db,p,skill,clock,success=True):
    chance=.10 if success else .05
    if clock["condition_key"] in {"dust_winds","sensor_noise","spore_drift"}:chance+=.05
    if random.random()>=chance:return ""
    key,text=ENCOUNTERS[_stable_index(f"{p.twitch_uid}:{clock['day']}:{p.actions}:{random.randint(0,9999)}",len(ENCOUNTERS))]
    name,first,set_note=collection_add(db,p,key,1)
    if first:journal_add(db,p,f"Found first {name}.")
    npc=""
    if random.random()<.35:
        who,job=random.choice(NPCS);npc=f" {who}, {job}, points it out."
    return f" 🔎 Encounter: {text}{npc} Collected: {name}."+set_note

def exposure_tick(db,p,pw,action,skill,clock):
    outdoor=skill in {"cultivation","environmental","extraction","frontier","logistics"}
    if not outdoor:return ""
    chance=.03
    if clock["phase"]=="Night":chance+=.05
    if clock["condition_key"]=="spore_drift":chance+=.12
    if random.random()<chance:
        gain=random.randint(2,6);pw.siro_exposure=clamp100(pw.siro_exposure+gain);db.commit()
        if pw.siro_exposure>=70:add_status(db,p,"siro_fatigue",30,-8,"High Siro exposure is reducing action effectiveness.")
        elif pw.siro_exposure>=40:add_status(db,p,"spore_irritation",20,-4,"Siro exposure is making outdoor work uncomfortable.")
        return f" ☣️ Siro exposure +{gain} ({pw.siro_exposure}/100)."
    return ""

def housing_status_text(shared,s,provider="discord",detailed=False):
    shortage=max(0,s.population-shared.housing)
    repair="/repair target:society" if provider=="discord" else "!repair"
    overview=f"Shared housing: {shared.housing} spaces for {s.population} citizens"
    if not shortage:return overview+" — enough housing; no housing penalty."
    overview+=f" — short by {shortage}. Success chance -3% (3 percentage points)."
    if not detailed:
        return overview+f" Help: {repair}; repairs need shared settlement parts."
    needed=5-(shared.infrastructure%5)
    rows=[overview,
          f"Help: use {repair}. Each successful supplied repair uses 1 shared settlement part and adds 1–2 Infrastructure, depending on needs.",
          f"Every 5 Infrastructure adds 1 housing space. Next space: {needed} more Infrastructure; shared settlement parts available: {shared.components}."]
    if shared.components<1:
        craft="/make" if provider=="discord" else "!make"
        mine="/mine" if provider=="discord" else "!mine"
        rows.append(f"Supply the society first: {mine} adds shared Ore; any {craft} crafting turns available shared Ore into shared settlement parts.")
    rows.append("This is society-wide housing capacity. Upgrading your personal Habitat does not add shared housing spaces.")
    return "\n".join(rows)


def world_rule_bundle(db,p,s,action,skill,provider="discord"):
    clock=world_clock(db,p.channel_id,s);pw=player_world(db,p)
    parts=[];total=0
    for fn,args in [
        (phase_action_modifier,(clock,action,skill)),
        (condition_action_modifier,(clock,action,skill)),
        (district_modifier,(pw,skill)),
        (shift_modifier,(pw,clock["day"],skill)),
        (shortage_modifier,(s,skill)),
    ]:
        b,n=fn(*args);total+=b;parts.extend(n)
    traits,tbonus=trait_data(db,p)
    if skill and tbonus.get(skill):
        total+=tbonus[skill];parts.append(f"{next((t for t in traits if True), 'Trait')} +{int(tbonus[skill]*100)}%")
    sb,snotes=status_modifier(db,p);total+=sb;parts.extend(snotes)
    mb,mnotes=main.autonomy.mood_modifier(main,db,p,clock);total+=mb;parts.extend(mnotes)
    ab,anotes=aftermath_modifier(db,p.channel_id,skill);total+=ab;parts.extend(anotes)
    cb,cnotes=main.community.success_modifier(main,db,p,skill);total+=cb;parts.extend(cnotes)
    shared=colony_state(db,p.channel_id);colony_tick(shared,s,main.now())
    pressure=colony_pressures(shared,s,pw.siro_exposure)
    for label,value in pressure.items():
        total+=value
        if label=="housing pressure":
            parts.append(housing_status_text(shared,s,provider))
        elif label=="habitat decline":
            repair="/repair target:society" if provider=="discord" else "!repair"
            parts.append(f"Society infrastructure shortage: 0 Infrastructure for {s.population} citizens. Success chance -3% (3 percentage points). Help: {repair}; needs shared settlement parts.")
        else:parts.append(f"Society condition: {label} {round(value*100):+d}%")
    if occupation_matches(p.job,skill):total+=.02;parts.append("Occupation match +2%")
    if skill in {"logistics","research","commerce","infrastructure"}:
        relations=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id,((LifeRelationship.uid_a==p.twitch_uid)|(LifeRelationship.uid_b==p.twitch_uid)))).scalars().all()
        best=max((effective_relationship(db,r) for r in relations),default=0)
        if best>=35 and life_state(db,p).social>=35:
            synergy=min(.04,best/3000);total+=synergy;parts.append(f"Trusted cooperation +{round(synergy*100)}%")
    return clock,pw,max(-.30,min(.15,total)),parts

def society_tier(s):
    core=min(s.food,s.materials,s.development,s.knowledge,s.treasury,s.reputation)
    current=SOCIETY_TIERS[0]
    for tier in SOCIETY_TIERS:
        if core>=tier[1]:current=tier
    return current
def society_tier_index(s):
    """Zero-based society rank used for recipe unlock requirements."""
    return SOCIETY_TIERS.index(society_tier(s))
def active_player_count(db,channel):
    """Citizens who played themselves in the last 30 minutes (Seedlings and queues do not count)."""
    cutoff=main.now()-timedelta(minutes=30)
    action_users=set(db.execute(select(RealActivity.canonical_uid).where(RealActivity.channel_id==channel,RealActivity.last_at>=cutoff)).scalars().all())
    if action_users:return len(action_users)
    return max(1,len(db.execute(select(Player).where(Player.channel_id==channel,Player.last_seen>=cutoff)).scalars().all()))
def scaled_event_goal(base,active):
    return max(6,int(math.ceil(base*min(2.0,1+.15*max(0,active-1)))))
def unique_activity_chatters(db,w,current_uid=None):
    if not w.activity_window_started_at:return 1 if current_uid else 0
    users=set(db.execute(select(RealActivity.canonical_uid).where(RealActivity.channel_id==w.channel_id,RealActivity.last_at>=as_utc(w.activity_window_started_at))).scalars().all())
    if current_uid:users.add(current_uid)
    return len(users)
def scaled_auto_event_actions(unique_chatters):
    return int(math.ceil(main.AUTO_EVENT_ACTIONS*min(2.0,1+.25*max(0,unique_chatters-1))))
