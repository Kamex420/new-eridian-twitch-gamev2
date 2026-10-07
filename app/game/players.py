"""Names and accounts, titles, collections, the weekly story, market demand, ducks, gear wear, the tutorial,
society/world/player lookups, skills and bonuses.
"""
import json
import math
import random
import time
from datetime import timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import object_session
from .. import crafting_progression, item_identity, seed_content
from ..commands import capture as colony_capture
from ..competencies import level as competency_level, practice_gain
from ..db import SessionLocal
from ..needs import productivity
from ..occupations import matches as occupation_matches
from ..progression import announce
from ..seed_skills import LEGACY_BRANCH
from ..settlement import seedling as colony_seedling, state as colony_state, tick as colony_tick
from ..models import (
    AccountLink, AccountNameHistory, Business, CollectionItem, CollectionSetClaim, DuckBond, GearFamiliarity,
    HobbyProgress, Identity, JournalEntry, LifeRelationship, Player, PlayerTitle, ProductionOrderCompletion,
    QualityGear, Society, SocietyProject, Specialization, TimedBonus, TutorialProgress, WeeklyStory, World)
from .base import clean, GAME_NAME, PLACEHOLDER_NAME
from .rules import (
    COLLECTION_SETS, JOBS, MARKET_BASE, QUALITY_RECIPES, QUALITY_TIERS, SEED_INDUSTRIES, SKILL_EQUIPMENT,
    SKILL_LABELS, STORY_ARCS, TITLE_DEFS)
from .. import main      # app.main: names from later modules and settings changed at runtime

def resource_name(key):
    key=item_identity.canonical(key)
    if key in seed_content.ITEMS:return seed_content.item_label(key) if key in seed_content.ACTIVE else seed_content.ITEMS[key]['name']
    if key in QUALITY_RECIPES:return QUALITY_RECIPES[key]["name"]
    if key.startswith("workshop:") and key[9:] in crafting_progression.STATIONS:return crafting_progression.STATIONS[key[9:]]["name"]+" access"
    if key.startswith("prospect:"):return "Prospecting progress ("+resource_name(key[9:])+")"
    return {"sc":"SC","cargo":"Cargo","toolkit":"Toolkit","siro_sampler":"Siro Sampler","duck_crate":"Duck Crate","spaceport_manifest":"Spaceport Manifest"}.get(key,key.replace("_"," ").title())
def requirement_text(costs):
    """Preview quantities; deductions are reserved for completed transactions."""
    return ", ".join(f"{amount} {resource_name(key)}" for key,amount in costs.items())

def cost_text(costs):
    return "("+", ".join(f"-{amount} {resource_name(key)}" for key,amount in costs.items())+")"
BONUS_TYPES={
    "rockys_favor":("🪨 Rocky's Favor","+3% success chance"),
    "seed_dividend":("🪙 SEED Dividend","+2 SC on successful skilled actions"),
    "civic_recognition":("⭐ Civic Recognition","+1 Contribution on successful skilled actions"),
    "accelerated_learning":("🧬 Accelerated Learning","+1 base aptitude practice on successful skilled actions; conditions affect banked XP"),
}

def record_account_name(db,channel,provider,provider_uid,name):
    provider=(provider or "").lower().strip()
    provider_uid=str(provider_uid or "").strip()
    display=clean(name)
    if not provider or not provider_uid:return
    row=db.execute(select(AccountNameHistory).where(
        AccountNameHistory.channel_id==channel,
        AccountNameHistory.provider==provider,
        AccountNameHistory.provider_uid==provider_uid,
        AccountNameHistory.display_name==display
    )).scalar_one_or_none()
    if row:
        row.last_seen=main.now();row.seen_count+=1
    else:
        db.add(AccountNameHistory(channel_id=channel,provider=provider,provider_uid=provider_uid,display_name=display))

def account_name_rows(db,channel,provider,provider_uid):
    return db.execute(select(AccountNameHistory).where(
        AccountNameHistory.channel_id==channel,
        AccountNameHistory.provider==provider,
        AccountNameHistory.provider_uid==str(provider_uid)
    ).order_by(AccountNameHistory.first_seen.asc())).scalars().all()

def account_name_summary(db,channel,provider,provider_uid,fallback=""):
    rows=account_name_rows(db,channel,provider,provider_uid)
    if not rows:
        return clean(fallback) if fallback else "not observed since name-history tracking began", []
    latest=max(rows,key=lambda r:as_utc(r.last_seen))
    old=[r.display_name for r in rows if r.display_name.lower()!=latest.display_name.lower()]
    return latest.display_name,old

def owner_link_lookup(db,channel,query=""):
    links=db.execute(select(AccountLink).where(AccountLink.channel_id==channel).order_by(AccountLink.linked_at.desc())).scalars().all()
    q=(query or "").strip().lower()
    matches=[]
    for link in links:
        p=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==link.twitch_uid)).scalar_one_or_none()
        tw_cur,tw_old=account_name_summary(db,channel,"twitch",link.twitch_uid,p.display_name if p else "")
        dc_cur,dc_old=account_name_summary(db,channel,"discord",link.discord_uid,"")
        hay=[tw_cur,dc_cur,str(link.twitch_uid),str(link.discord_uid)]+tw_old+dc_old
        if q and not any(q in (x or "").lower() for x in hay):continue
        matches.append((link,tw_cur,tw_old,dc_cur,dc_old))
    if not matches:
        return "🔐 No linked account pair matched that name or ID." if q else "🔐 No linked Twitch/Discord pairs found."
    if q:
        matches=matches[:5]
    else:
        matches=matches[:10]
    lines=["🔐 LINKED ACCOUNT LOOKUP"]
    for link,tw_cur,tw_old,dc_cur,dc_old in matches:
        lines.append(f"\nTwitch: {tw_cur} | Discord: {dc_cur}")
        lines.append(f"IDs: Twitch {link.twitch_uid} | Discord {link.discord_uid}")
        if tw_old:lines.append("Previous Twitch names: "+", ".join(tw_old[-6:]))
        if dc_old:lines.append("Previous Discord names: "+", ".join(dc_old[-6:]))
        lines.append("Linked: "+as_utc(link.linked_at).strftime("%Y-%m-%d"))
    lines.append("\nName history starts when v5.4.1 sees an account; names from before then may be unavailable.")
    return "\n".join(lines)[:1850]


def hobby_row(db,p,hobby):
    row=db.execute(select(HobbyProgress).where(HobbyProgress.channel_id==p.channel_id,HobbyProgress.canonical_uid==p.twitch_uid,HobbyProgress.hobby==hobby)).scalar_one_or_none()
    if not row:
        legacy={"gardening":"gardening","exploration":"exploration_hobby","mechanics":"mechanics","research":"research_hobby","games":"games_hobby","rockwatching":"rockwatching"}
        life=main.life_state(db,p);start=getattr(life,legacy[hobby],0) if hobby in legacy else 0
        row=HobbyProgress(channel_id=p.channel_id,canonical_uid=p.twitch_uid,hobby=hobby,points=start);db.add(row);db.commit();db.refresh(row)
    return row

def hobby_points(db,p,hobby):return hobby_row(db,p,hobby).points

def unlock_title(db,p,key):
    if key not in TITLE_DEFS:return False
    row=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==p.channel_id,PlayerTitle.canonical_uid==p.twitch_uid,PlayerTitle.title_key==key)).scalar_one_or_none()
    if row:return False
    db.add(PlayerTitle(channel_id=p.channel_id,canonical_uid=p.twitch_uid,title_key=key,equipped=False));db.commit();return True

def refresh_titles(db,p):
    unlock_title(db,p,"new_eridian_local")
    checks=[("green_thumb",p.farm_xp),("deep_delver",p.mining_xp),("machine_whisperer",p.fabrication_xp),("siro_watcher",p.research_xp),("trailwise",p.explore_xp),("market_regular",p.commerce_xp)]
    for key,xp in checks:
        if xp>=150:unlock_title(db,p,key)
    if p.contribution>=150:unlock_title(db,p,"community_builder")
    rels=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id)).scalars().all()
    if any(p.twitch_uid in {x.uid_a,x.uid_b} and x.familiarity>=180 for x in rels):unlock_title(db,p,"friend_of_eridian")
    q=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.quality=="Masterwork",QualityGear.qty>0)).scalars().all()
    if q:unlock_title(db,p,"master_crafter")
    orders=db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==p.channel_id,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all()
    if len(orders)>=1:unlock_title(db,p,"production_runner")
    if len(orders)>=10:unlock_title(db,p,"industry_coordinator")
    if len(orders)>=30:unlock_title(db,p,"master_supplier")

def equipped_title(db,p):
    refresh_titles(db,p)
    row=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==p.channel_id,PlayerTitle.canonical_uid==p.twitch_uid,PlayerTitle.equipped==True)).scalar_one_or_none()
    return TITLE_DEFS.get(row.title_key,"") if row else ""

def check_collection_sets(db,p):
    owned={r.item_key for r in db.execute(select(CollectionItem).where(CollectionItem.channel_id==p.channel_id,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.qty>0)).scalars().all()}
    rewards=[]
    for key,(name,items,sc,contrib,title) in COLLECTION_SETS.items():
        if not items.issubset(owned):continue
        claimed=db.execute(select(CollectionSetClaim).where(CollectionSetClaim.channel_id==p.channel_id,CollectionSetClaim.canonical_uid==p.twitch_uid,CollectionSetClaim.set_key==key)).scalar_one_or_none()
        if claimed:continue
        db.add(CollectionSetClaim(channel_id=p.channel_id,canonical_uid=p.twitch_uid,set_key=key));p.sc+=sc;p.contribution+=contrib
        title_key=next((k for k,v in TITLE_DEFS.items() if v==title),None)
        if title_key:unlock_title(db,p,title_key)
        rewards.append(f"📚 Set complete: {name}! +{sc} SC/+{contrib} Contribution; title unlocked: {title}.")
    db.commit();return " "+" ".join(rewards) if rewards else ""

def story_week(clock):return max(0,(clock["day"]-1)//28)

def story_state(db,channel,clock=None):
    clock=clock or main.world_clock(db,channel);wk=story_week(clock)
    row=db.execute(select(WeeklyStory).where(WeeklyStory.channel_id==channel,WeeklyStory.week_index==wk)).scalar_one_or_none()
    if not row:
        cfg=STORY_ARCS[main._stable_index(f"{channel}:{wk}:story",len(STORY_ARCS))]
        row=WeeklyStory(channel_id=channel,week_index=wk,arc_key=cfg["key"]);db.add(row);db.commit();db.refresh(row)
    cfg=next(x for x in STORY_ARCS if x["key"]==row.arc_key)
    return row,cfg

def story_contribute(db,p,skill):
    if not skill:return ""
    clock=main.world_clock(db,p.channel_id);row,cfg=story_state(db,p.channel_id,clock)
    if row.resolved:return ""
    tracks=[row.track_a,row.track_b,row.track_c];matched=[]
    for i,(_,skills) in enumerate(cfg["tracks"]):
        if skill in skills:matched.append(i)
    if not matched:return ""
    idx=random.choice(matched);tracks[idx]+=1;row.track_a,row.track_b,row.track_c=tracks;total=sum(tracks)
    note=f" 📖 {cfg['name']} +1 ({total}/{cfg['goal']})."
    if total>=cfg["goal"]:
        winner=max(range(3),key=lambda i:tracks[i]);track_name=cfg["tracks"][winner][0];row.resolved=True
        row.outcome=f"New Eridian resolved {cfg['name']} through {track_name}."
        soc=society(db,p.channel_id);rewards=[("Farming/Processing",("food",30)),("Research",("knowledge",30)),("Logistics/Commerce",("treasury",30))]
        # Arc-independent reward keyed to winning track: development + reputation plus a themed stat.
        if winner==0:soc.development+=20;soc.food+=20
        elif winner==1:soc.knowledge+=30
        else:soc.treasury+=20;soc.reputation+=20
        note+=f" ✅ Story resolved: {track_name}! Society receives a major boost."
    db.commit();return note

def demand_pool():
    """Natural materials Seed Industries buys: the items that can be in daily demand."""
    return sorted(k for k in seed_content.GATHER if (SEED_INDUSTRIES.get(k) or {}).get('sell',0)>0)

def market_demand(channel,day):
    keys=demand_pool() or list(MARKET_BASE)
    primary=keys[main._stable_index(f"{channel}:{day}:market",len(keys))];secondary=keys[main._stable_index(f"{channel}:{day}:market2",len(keys))]
    if secondary==primary:secondary=keys[(keys.index(primary)+1)%len(keys)]
    return primary,secondary

_demand_day=[0.0,1]
def demand_day():
    """Today's Avesta day for sale prices, read at most once a minute."""
    if time.monotonic()-_demand_day[0]>60:
        with SessionLocal() as db:_demand_day[1]=main.world_clock(db,main.DISCORD_WORLD_ID)["day"];db.commit()
        _demand_day[0]=time.monotonic()
    return _demand_day[1]

def demand_price(key,day):
    """Listed sale price, +60% or +30% (always at least +1 SC) while the item is in demand that day.

    Never as much as Seed Industries charges for the item, so buying it and selling it straight back always loses SC
    (otherwise a demand day would pay for every buy/sell round trip, with Commerce practice on top)."""
    listing=SEED_INDUSTRIES.get(key) or {}
    base=listing.get('sell',0)
    mult=market_multiplier(main.DISCORD_WORLD_ID,day,key)
    if not base or mult==1:return base
    boosted=max(base+1,math.ceil(base*mult))
    buy=listing.get('buy',0)
    return max(base,min(boosted,buy-1)) if buy else boosted

def sale_price(key):
    """What Seed Industries pays for one today."""
    try:return demand_price(key,main.demand_day())
    except Exception:return (SEED_INDUSTRIES.get(key) or {}).get('sell',0)

def market_multiplier(channel,day,resource):
    a,b=market_demand(channel,day)
    return 1.6 if resource==a else 1.3 if resource==b else 1.0

def duck_bond(db,p,duck,gain=0):
    row=db.execute(select(DuckBond).where(DuckBond.channel_id==p.channel_id,DuckBond.canonical_uid==p.twitch_uid,DuckBond.duck==duck)).scalar_one_or_none()
    if not row:row=DuckBond(channel_id=p.channel_id,canonical_uid=p.twitch_uid,duck=duck,xp=0);db.add(row)
    if gain:row.xp+=gain
    if row.xp>=100:unlock_title(db,p,"fleet_friend")
    db.commit();return row

def duck_rank(xp):
    if xp>=100:return "Trusted Handler"
    if xp>=50:return "Fleet Regular"
    if xp>=20:return "Familiar Face"
    if xp>=5:return "Recognized"
    return "New Contact"

def degrade_gear(db,p,skill):
    if not skill:return ""
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
    candidates=[x for x in rows if skill in QUALITY_RECIPES.get(x.item_key,{}).get("skills",{}) and x.condition>0]
    if not candidates:return ""
    row=max(candidates,key=lambda x:QUALITY_TIERS.get(x.quality,QUALITY_TIERS["Standard"])["skill"])
    familiarity=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==p.channel_id,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==row.item_key)).scalar_one_or_none()
    _,wear_reduction=main.gear_familiarity_rank(familiarity.uses if familiarity else 0)
    if random.random()>(.35-wear_reduction):return ""
    loss=random.randint(1,3);row.condition=max(0,row.condition-loss);db.commit()
    return f" 🔧 {row.item_name} condition {row.condition}%." if row.condition in {75,50,25,10,0} else ""

def tutorial_row(db,p):
    row=db.execute(select(TutorialProgress).where(TutorialProgress.channel_id==p.channel_id,TutorialProgress.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:row=TutorialProgress(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row);db.commit();db.refresh(row)
    return row

def tutorial_text(db,p,provider):
    from .. import onboarding
    steps_text=onboarding.status(main,db,p,provider)
    if steps_text:return steps_text
    row=tutorial_row(db,p);prefix='/' if provider=='discord' else '!'
    if provider=="discord":
        steps=[("Check the living world","/world"),("Choose a job","/job"),("Complete a work action","/guide"),
               ("Check your life needs","/me section:Life Needs"),("Craft your first useful item","/make"),("Meet another citizen","/social"),("Help New Eridian","/society")]
    else:
        steps=[("Check the living world","!world"),("Choose a job","!job"),("Complete a work action","!guide"),
               ("Check your life needs","!life"),("Craft your first useful item","!make"),("Meet another citizen","!hi <name>"),("Help New Eridian","!projectstatus")]
    idx=min(row.step,len(steps)-1)
    return f"🧭 First Days {row.step}/{len(steps)} | Next: {steps[idx][0]} — {steps[idx][1]}" if not row.completed else "🧭 First Days complete. Your path is now your own."

def tutorial_advance(db,p,kind):
    row=tutorial_row(db,p);expected=["world","job","action","life","craft","social","society"]
    if row.completed:return ""
    if row.step<len(expected) and expected[row.step]==kind:
        row.step+=1
        if row.step>=len(expected):row.completed=True;p.sc+=20;p.contribution+=5;note=" 🎓 First Days complete! +20 SC/+5 Contribution."
        else:note=f" 🎓 First Days {row.step}/{len(expected)}."
        db.commit();return note
    return ""

def society(db,c):
    s=db.execute(select(Society).where(Society.channel_id==c)).scalar_one_or_none()
    if not s: s=Society(channel_id=c,name=GAME_NAME); db.add(s); db.commit(); db.refresh(s)
    shared=colony_state(db,c);colony_tick(shared,s,main.now());db.commit()
    return s
def world(db,c):
    w=db.execute(select(World).where(World.channel_id==c)).scalar_one_or_none()
    if not w: w=World(channel_id=c); db.add(w); db.commit(); db.refresh(w)
    return w
def resolve(db,c,provider,uid):
    if 'task_queue' in vars(main) and main.task_queue.actor_context.get()==(c,uid):return uid
    r=db.execute(select(Identity).where(Identity.channel_id==c,Identity.provider==provider,Identity.provider_uid==uid)).scalar_one_or_none()
    if r:return r.canonical_uid
    canon=uid if provider=="twitch" else "discord:"+uid
    db.add(Identity(channel_id=c,provider=provider,provider_uid=uid,canonical_uid=canon));db.commit();return canon
def player(db,c,provider,uid,name):
    canon=resolve(db,c,provider,uid)
    p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==canon)).scalar_one_or_none()
    if not p:
        p=Player(channel_id=c,twitch_uid=canon,display_name=clean(name));db.add(p);society(db,c).population+=1
        from .. import stream_overlay
        stream_overlay.highlight(db,c,"join",f"{clean(name)} arrived in New Eridian","A new citizen joined. Type !start in chat to join them.",clean(name))
        db.commit();db.refresh(p)
    item_identity.migrate_player(main,db,p)
    # Background work and a few chat commands call without the viewer's name; they keep the name the citizen already has.
    if clean(name)!=PLACEHOLDER_NAME or not p.display_name:
        record_account_name(db,c,provider,uid,name)
        p.display_name=clean(name)
    p.last_seen=main.now();db.commit()
    main.life_state(db,p)
    colony_capture(db,p)
    return canon,p
def lvl(x):
    return competency_level(x)
def as_utc(dt):
    if dt is None:return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
def skill_xp(p,skill):
    from ..competencies import FIELDS
    return getattr(p,FIELDS[skill])

def gain_skill(p,skill,amount=1):
    from ..competencies import FIELDS
    db=object_session(p);field=FIELDS[skill];old=lvl(getattr(p,field))
    if db is not None:
        st=colony_seedling(db,p);life=main.life_state(db,p)
        project=db.execute(select(SocietyProject).where(SocietyProject.channel_id==p.channel_id)).scalars().first()
        project_match=bool(project and project.progress<project.goal and skill in main.project_cfg(project.project_key)[3]) if project else False
        quality=getattr(p,"_practice_quality",1.0)
        living=productivity(life,main.player_world(db,p).siro_exposure)*(1.10 if min(life.energy,life.nutrition,life.social,life.comfort,life.morale)>=80 else 1.0)
        gain=practice_gain(amount,occupation_matches(p.job,skill),living,project_match,quality)
        practice=json.loads(st.practice);total=practice.get(skill,0.0)+gain
        amount=int(total);practice[skill]=round(total-amount,6);st.practice=json.dumps(practice)
        from ..commands import context
        ctx=context.get()
        if ctx is not None:ctx["practice"].append(f"{p.display_name} {SKILL_LABELS[skill]} +{gain:.2f} ({amount} XP banked)")
    setattr(p,field,getattr(p,field)+amount)
    if db is not None:
        from ..commands import context
        ctx=context.get() or {}
        branch=LEGACY_BRANCH.get(ctx.get("params",{}).get("action"))
        if branch:main.gain_branch(db,p,branch,amount)
    if skill in {"fabrication","infrastructure"}:p.industry_xp+=amount
    new=lvl(getattr(p,field))
    if db is not None and new>old:
        message=f"LEVEL UP: {p.display_name} — {SKILL_LABELS[skill]} aptitude Lv. {old} → Lv. {new}"
        # Selling, undoing the sale and selling again would announce (and put on stream) the same level up again.
        if not db.execute(select(JournalEntry.id).where(JournalEntry.channel_id==p.channel_id,JournalEntry.canonical_uid==p.twitch_uid,
                                                        JournalEntry.entry==message[:220])).first():
            announce(db,p,message,main.now())
    return amount

def specialization_for(db,p,skill):
    return db.execute(select(Specialization).where(Specialization.channel_id==p.channel_id,Specialization.canonical_uid==p.twitch_uid,Specialization.skill==skill)).scalar_one_or_none()
def business_for(db,p):
    return db.execute(select(Business).where(Business.channel_id==p.channel_id,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
def active_bonuses(db,p):
    return db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.expires_at>main.now()).order_by(TimedBonus.expires_at)).scalars().all()
def bonus_active(db,p,bonus):
    return db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.bonus==bonus,TimedBonus.expires_at>main.now())).scalar_one_or_none() is not None
def grant_random_bonus(db,p,bonus_chance=0):
    business=business_for(db,p);chance=(.08 if business else .04)+bonus_chance
    if random.random()>=chance:return ""
    bonus=random.choice(list(BONUS_TYPES));row=db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.bonus==bonus)).scalar_one_or_none();start=main.now()
    if not row:row=TimedBonus(channel_id=p.channel_id,canonical_uid=p.twitch_uid,bonus=bonus,expires_at=start,times_received=0);db.add(row)
    if as_utc(row.expires_at)>start:start=as_utc(row.expires_at)
    row.expires_at=start+timedelta(minutes=10);row.times_received+=1;db.commit();label,effect=BONUS_TYPES[bonus]
    owner_note=f" {business.name}'s trade network improved the discovery chance." if business else ""
    return f" ⚡ {p.display_name} activated {label}: {effect} for 10 more minutes.{owner_note}"
def bonuses_text(db,p,provider="twitch"):
    rows=active_bonuses(db,p)
    if not rows:return f"⚡ {p.display_name} has no active bonuses. Successful actions can activate one; business owners have double the chance."
    details=[]
    for row in rows:
        seconds=max(0,int((as_utc(row.expires_at)-main.now()).total_seconds()));label,effect=BONUS_TYPES.get(row.bonus,(row.bonus.replace("_"," ").title(),"Personal bonus"));details.append((label,effect,seconds,row.times_received))
    if provider=="discord":return f"⚡ {p.display_name} — Active Bonuses\n\n"+"\n\n".join(f"{label}\n{effect}\nTime remaining: {seconds//60}:{seconds%60:02d} · Activated {times}x" for label,effect,seconds,times in details)+"\n\nActivating the same bonus again adds another 10 minutes."
    return "⚡ "+" | ".join(f"{label} {seconds//60}:{seconds%60:02d} ({effect})" for label,effect,seconds,_ in details)
def citizen_title(p):
    skills={key:skill_xp(p,key) for key in SKILL_LABELS};strongest=max(skills,key=skills.get);return f"{JOBS.get(p.job,('Settler',set()))[0]} · {SKILL_LABELS[strongest]} specialist"
def business_xp_needed(level):
    return 25 + (max(1,int(level))*15)

def home_upgrade_cost(tier):
    """(SC, Iron Nails). Nails replace legacy Components at 5 nails per component."""
    tier=max(1,int(tier))
    # Long-term but smoother than the old quadratic jump.
    return 100 + 60*(tier**2), 5*max(2,tier*2)

def gain_business_xp(b,amount):
    old=b.level;b.xp+=amount
    while b.xp>=business_xp_needed(b.level):b.xp-=business_xp_needed(b.level);b.level+=1
    db=object_session(b)
    if db is not None and b.level>old:
        p=db.execute(select(Player).where(Player.channel_id==b.channel_id,Player.twitch_uid==b.canonical_uid)).scalar_one_or_none()
        # The business's own name stays out of the announcement: level ups reach the stream overlay.
        if p:announce(db,p,f"LEVEL UP: {p.display_name}'s business Lv. {old} → Lv. {b.level}",main.now())
def success_chance(db,p,skill,base=.68,cap=.86):
    """Intrinsic chance before situational modifiers; deliberately capped."""
    spec_bonus=.03 if specialization_for(db,p,skill) else 0
    equipment=SKILL_EQUIPMENT.get(skill);equipment_bonus=.02 if equipment and main.item(db,p.channel_id,p.twitch_uid,equipment)>0 else 0
    if skill in {"fabrication","infrastructure"} and main.item(db,p.channel_id,p.twitch_uid,"toolkit")>0:equipment_bonus+=.02
    if skill in {"extraction","research","frontier"} and main.item(db,p.channel_id,p.twitch_uid,"sensor")>0:equipment_bonus+=.02
    timed_bonus=.03 if bonus_active(db,p,"rockys_favor") else 0
    level_bonus=min(.12,(lvl(skill_xp(p,skill))-1)*.015)
    return min(cap,base+level_bonus+spec_bonus+equipment_bonus+timed_bonus)

def clamp100(value):
    return max(0,min(100,int(value)))
