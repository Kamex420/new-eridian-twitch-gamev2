"""Rare outcomes, merging duplicate accounts, achievements and configuration warnings.
"""
import json
import logging
import os
import random
from sqlalchemy import select
from .. import item_identity, seed_content
from ..models import SkillBranch
from ..models import (
    Achievement, ActionLog, Business, Cooldown, CraftLedger, Daily, Determination, EventContribution, ExtraItem,
    Home, Identity, LifeRelationship, LifeState, LinkCode, Player, ProductionOrderCompletion, QualityGear,
    SeedlingState, Specialization, TimedBonus)
from .rules import PART_RECIPES, QUALITY_TIERS
from .players import as_utc, business_xp_needed, lvl, skill_xp, society, specialization_for
from .cooldowns_materials import item_add
from .. import main      # app.main: names from later modules and settings changed at runtime

def rare_outcome(db,p,s,skill):
    if not skill:return ""
    chance=min(.14,.02+lvl(skill_xp(p,skill))*.006+(.02 if specialization_for(db,p,skill) else 0))
    if random.random()>=chance:return ""
    if skill=="cultivation":p.crops+=1;s.food+=1;return " 🌿 Rare yield: a resilient Avesta cultivar adds +1 Pumpkin/+1 Food."
    if skill=="environmental":s.knowledge+=2;return " 💧 Rare reading: an unusual biosphere pattern adds +2 Knowledge."
    if skill=="extraction":item_add(db,p.channel_id,p.twitch_uid,"mineral_sample",1);s.materials+=1;return " 💎 Rare find: +1 Mineral Sample/+1 Materials. Prospect rare ores with /mine."
    if skill=="fabrication":p.components+=5;s.development+=1;return " ⚙️ Precision result: +5 Iron Nails/+1 Development."
    if skill=="infrastructure":s.development+=2;return " 🏗️ Rocky-approved reinforcement: +2 Development."
    if skill=="research":s.knowledge+=2;return " ☣️ Rare Siro signature archived: +2 Knowledge."
    if skill=="logistics":p.cargo+=1;s.treasury+=1;return " 🦆 The delivery fleet recovers lost cargo: +1 Cargo/+1 Treasury."
    if skill=="frontier":item_add(db,p.channel_id,p.twitch_uid,"mineral_sample",1);s.knowledge+=1;return " 🧭 Frontier cache: +1 Mineral Sample/+1 Knowledge. Prospect rare ores with /mine."
    if skill=="commerce":p.sc+=3;s.treasury+=1;return " 🏪 Exceptional contract: +3 SC/+1 Treasury."
    return ""

def merge_accounts(db,channel,source_uid,target_uid):
    """Merge an unlinked Discord character into its Twitch character exactly once."""
    if not source_uid or source_uid==target_uid:return False
    source=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==source_uid)).scalar_one_or_none()
    target=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==target_uid)).scalar_one_or_none()

    for account in (source,target):
        if account:item_identity.migrate_player(db,account)
    if source and not target:
        source.twitch_uid=target_uid
        target=source
    elif source and target:
        additive=["sc","contribution","farm_xp","mining_xp","industry_xp","research_xp","delivery_xp","explore_xp","environmental_xp","fabrication_xp","infrastructure_xp","commerce_xp","cooking_xp","medicine_xp","emergency_xp","crops","ore","rare_ore","components","cargo","actions","successes"]
        for field in additive:setattr(target,field,getattr(target,field)+getattr(source,field))
        if target.job=="settler" and source.job!="settler":target.job=source.job
        if as_utc(source.created_at)<as_utc(target.created_at):target.created_at=source.created_at
        if as_utc(source.last_seen)>as_utc(target.last_seen):target.last_seen=source.last_seen
        if source.last_job_change and (not target.last_job_change or as_utc(source.last_job_change)>as_utc(target.last_job_change)):target.last_job_change=source.last_job_change
        db.delete(source)
        s=society(db,channel);s.population=max(0,s.population-1)

    for row in db.execute(select(SkillBranch).where(SkillBranch.channel_id==channel,SkillBranch.canonical_uid==source_uid)).scalars().all():
        target_branch=db.get(SkillBranch,(channel,target_uid,row.branch))
        if target_branch:target_branch.xp+=row.xp;db.delete(row)
        else:row.canonical_uid=target_uid

    # Stack extra inventory items by item name.
    for row in db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==target_uid,ExtraItem.item==row.item)).scalar_one_or_none()
        if existing:existing.qty+=row.qty;db.delete(row)
        else:row.canonical_uid=target_uid

    # Preserve the best home tier.
    source_home=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==source_uid)).scalar_one_or_none()
    target_home=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==target_uid)).scalar_one_or_none()
    if source_home:
        if target_home:target_home.tier=max(target_home.tier,source_home.tier);db.delete(source_home)
        else:source_home.canonical_uid=target_uid

    # Keep the Twitch business identity, but preserve the higher level and combined XP.
    source_business=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==source_uid)).scalars().first()
    target_business=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==target_uid)).scalars().first()
    if source_business:
        if target_business:
            target_business.level=max(target_business.level,source_business.level);target_business.xp+=source_business.xp
            while target_business.xp>=business_xp_needed(target_business.level):
                target_business.xp-=business_xp_needed(target_business.level);target_business.level+=1
            db.delete(source_business)
        else:source_business.canonical_uid=target_uid

    # Union achievements without duplicating them.
    target_codes={r.code for r in db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==target_uid)).scalars().all()}
    for row in db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==source_uid)).scalars().all():
        if row.code in target_codes:db.delete(row)
        else:row.canonical_uid=target_uid;target_codes.add(row.code)

    # Preserve one daily contract per day, using the furthest progress.
    for row in db.execute(select(Daily).where(Daily.channel_id==channel,Daily.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Daily).where(Daily.channel_id==channel,Daily.canonical_uid==target_uid,Daily.day_key==row.day_key)).scalar_one_or_none()
        if existing:
            if existing.action==row.action:
                existing.progress=max(existing.progress,row.progress);existing.complete=existing.complete or row.complete
            db.delete(row)
        else:row.canonical_uid=target_uid

    # Preserve active cooldowns, specializations, and historical event contributions.
    for row in db.execute(select(Cooldown).where(Cooldown.channel_id==channel,Cooldown.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Cooldown).where(Cooldown.channel_id==channel,Cooldown.canonical_uid==target_uid,Cooldown.action==row.action)).scalar_one_or_none()
        if existing:
            if as_utc(row.ready_at)>as_utc(existing.ready_at):existing.ready_at=row.ready_at
            db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==target_uid,Specialization.skill==row.skill)).scalar_one_or_none()
        if existing:db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(EventContribution).where(EventContribution.channel_id==channel,EventContribution.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(EventContribution).where(EventContribution.channel_id==channel,EventContribution.event_instance==row.event_instance,EventContribution.canonical_uid==target_uid)).scalar_one_or_none()
        if existing:
            existing.primary_successes+=row.primary_successes;existing.support_successes+=row.support_successes;db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(TimedBonus).where(TimedBonus.channel_id==channel,TimedBonus.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(TimedBonus).where(TimedBonus.channel_id==channel,TimedBonus.canonical_uid==target_uid,TimedBonus.bonus==row.bonus)).scalar_one_or_none()
        if existing:
            if as_utc(row.expires_at)>as_utc(existing.expires_at):existing.expires_at=row.expires_at
            existing.times_received+=row.times_received;db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(Determination).where(Determination.channel_id==channel,Determination.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Determination).where(Determination.channel_id==channel,Determination.canonical_uid==target_uid,Determination.skill==row.skill)).scalar_one_or_none()
        if existing:existing.stacks=max(existing.stacks,row.stacks);db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==target_uid,CraftLedger.recipe==row.recipe)).scalar_one_or_none()
        if existing:
            existing.qty+=row.qty
            ranks=list(QUALITY_TIERS)
            if row.best_quality and (not existing.best_quality or ranks.index(row.best_quality)>ranks.index(existing.best_quality)):existing.best_quality=row.best_quality
            db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(ProductionOrderCompletion).where(
            ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==target_uid,
            ProductionOrderCompletion.avesta_day==row.avesta_day,ProductionOrderCompletion.order_key==row.order_key
        )).scalar_one_or_none()
        if existing:db.delete(row)
        else:row.canonical_uid=target_uid

    # Merge Seedling Life data so Twitch/Discord remain one character after linking.
    source_life=db.execute(select(LifeState).where(LifeState.channel_id==channel,LifeState.canonical_uid==source_uid)).scalar_one_or_none()
    target_life=db.execute(select(LifeState).where(LifeState.channel_id==channel,LifeState.canonical_uid==target_uid)).scalar_one_or_none()
    if source_life:
        if target_life:
            for field in ("energy","nutrition","social","comfort","morale"):
                setattr(target_life,field,max(getattr(target_life,field),getattr(source_life,field)))
            for field in ("gardening","exploration_hobby","mechanics","research_hobby","games_hobby","rockwatching"):
                setattr(target_life,field,getattr(target_life,field)+getattr(source_life,field))
            db.delete(source_life)
        else:source_life.canonical_uid=target_uid
    for row in db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==target_uid,QualityGear.item_key==row.item_key,QualityGear.quality==row.quality)).scalar_one_or_none()
        if existing:
            existing.qty+=row.qty;existing.condition=max(existing.condition,row.condition);db.delete(row)
        else:row.canonical_uid=target_uid
    # Delete old pairs before inserting their canonical aggregate (unique-safe).
    rels=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel)).scalars().all()
    combined={}
    for row in rels:
        a=target_uid if row.uid_a==source_uid else row.uid_a
        b=target_uid if row.uid_b==source_uid else row.uid_b
        if a!=b:
            pair=tuple(sorted((a,b)));combined[pair]=combined.get(pair,0)+row.familiarity
        db.delete(row)
    db.flush()
    for (a,b),points in combined.items():db.add(LifeRelationship(channel_id=channel,uid_a=a,uid_b=b,familiarity=points))

    old_state=db.get(SeedlingState,(channel,source_uid))
    new_state=db.get(SeedlingState,(channel,target_uid))
    if old_state:
        if new_state:
            history=json.loads(new_state.occupation_history)+json.loads(old_state.occupation_history)
            new_state.occupation_history=json.dumps(history)
            fractions=json.loads(new_state.practice)
            for key,value in json.loads(old_state.practice).items():fractions[key]=fractions.get(key,0)+value
            new_state.practice=json.dumps(fractions)
            if not new_state.last_progress:new_state.last_progress=old_state.last_progress
            db.delete(old_state)
        else:old_state.canonical_uid=target_uid

    if 'task_queue' in vars(main):main.task_queue.merge_accounts(db,channel,source_uid,target_uid)

    # Redirect every related identity/history row, then remove obsolete link codes.
    for row in db.execute(select(Identity).where(Identity.channel_id==channel,Identity.canonical_uid==source_uid)).scalars().all():row.canonical_uid=target_uid
    for row in db.execute(select(ActionLog).where(ActionLog.channel_id==channel,ActionLog.canonical_uid==source_uid)).scalars().all():row.canonical_uid=target_uid
    for row in db.execute(select(LinkCode).where(LinkCode.channel_id==channel,LinkCode.canonical_uid==source_uid)).scalars().all():db.delete(row)
    db.commit()
    return bool(source)
def parts_crafted(crafted):
    """Component catalog progress: a legacy part counts once its catalog item was
    made by any of its recipes (or, for Flaxa, is now gathered)."""
    made={k for rid in crafted if rid in seed_content.RECIPES for k in seed_content.RECIPES[rid]['outputs']}
    return sum(old in crafted or old in item_identity.RETIRED_GATHERED or
               item_identity.ALIASES.get(item_identity.LEGACY_OUTPUTS.get(old,''),'') in made for old in PART_RECIPES)
def achieve(db,p):
    notes=[]
    order_count=len(db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==p.channel_id,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all())
    crafted={r.recipe:r for r in db.execute(select(CraftLedger).where(CraftLedger.channel_id==p.channel_id,CraftLedger.canonical_uid==p.twitch_uid)).scalars().all()}
    all_parts=parts_crafted(crafted)==len(PART_RECIPES)
    masterwork=any(r.best_quality=="Masterwork" for r in crafted.values())
    tests=[
        ("getting_established",p.actions>=10,"Getting Established"),
        ("society_builder",p.contribution>=50,"Society Builder"),
        ("seed_saver",p.sc>=250,"Seed Coin Saver"),
        ("component_catalog",all_parts,"Complete Component Catalog"),
        ("first_production_order",order_count>=1,"First Production Order"),
        ("production_partner",order_count>=10,"Seed Industries Production Partner"),
        ("master_supplier",order_count>=30,"Master Supplier"),
        ("masterwork_made",masterwork,"First Masterwork"),
    ]
    for code,ok,label in tests:
        if not ok:continue
        r=db.execute(select(Achievement).where(Achievement.channel_id==p.channel_id,Achievement.canonical_uid==p.twitch_uid,Achievement.code==code)).scalar_one_or_none()
        if not r:
            db.add(Achievement(channel_id=p.channel_id,canonical_uid=p.twitch_uid,code=code))
            from .. import stream_overlay
            stream_overlay.highlight(db,p.channel_id,"achievement",f"{p.display_name} earned an achievement",label,p.display_name)
            db.commit();notes.append("🏆 "+label)
    return (" "+" | ".join(notes)) if notes else ""

RUNTIME_WARNINGS=set()   # problems noticed while serving requests (e.g. a Twitch channel that is not DISCORD_WORLD_ID)

def config_warnings():
    """Setup problems worth fixing, shown by /health and logged at startup."""
    found=[]
    if not os.getenv("TWITCH_API_KEY","").strip():
        found.append("TWITCH_API_KEY is not set: anyone can call the game API as any Twitch player. Set it on Railway and put it in the StreamElements commands (k=...).")
    hosted=any(os.getenv(k) for k in ("RAILWAY_ENVIRONMENT","RAILWAY_PROJECT_ID","RENDER","RENDER_SERVICE_ID"))
    if hosted and main.engine.dialect.name=="sqlite":
        found.append("DATABASE_URL is not set: saves are in a SQLite file inside the container and are wiped on every redeploy. Attach a Postgres database.")
    host=main.engine.url.host or ""
    if main.engine.dialect.name=="postgresql" and (".proxy.rlwy.net" in host or host.endswith(".proxy.railway.app")):
        found.append("DATABASE_URL uses Railway's public proxy. A command makes about a hundred small queries, each a round trip over the internet: use the private URL (postgres.railway.internal) instead.")
    return found+sorted(main.RUNTIME_WARNINGS)

for _warning in config_warnings():logging.getLogger("uvicorn.error").warning("SETUP WARNING: %s",_warning)
