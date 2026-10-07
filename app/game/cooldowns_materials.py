"""Cooldowns, action names and routes, materials and the bag, determination, Production Orders, daily contracts.
"""
import math
import random
from datetime import timedelta
from sqlalchemy import select
from .. import crafting_progression, item_identity, seed_content
from ..needs import duration_text, SLEEP_COOLDOWN_SECONDS
from ..seed_skills import HUBS as SEED_HUBS, TASKS as SEED_TASKS
from ..models import (
    Business, Cooldown, CraftLedger, Daily, Determination, ExtraItem, ModeratorAudit, Player,
    ProductionOrderCompletion, QualityGear)
from .rules import (
    ACTION_COOLDOWNS, CRAFT_OUTPUT_KEYS, CRAFT_PAY, PRODUCTION_ORDERS, QUALITY_RECIPES, QUALITY_TIERS, RECIPES,
    SEED_INDUSTRIES, SKILL_ACTIONS, SKILL_LABELS, UNIQUE_CORE_ITEMS, UNIQUE_QUALITY_ITEMS)
from .players import as_utc, lvl, requirement_text, resource_name, skill_xp
from .world import _stable_index
from .. import main      # app.main: names from later modules and settings changed at runtime

ACTION_COOLDOWNS['seed_use']=20

def check_cooldown(db,p,action_name):
    row=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid,Cooldown.action==action_name)).scalar_one_or_none()
    seconds=ACTION_COOLDOWNS.get(action_name,5)
    if row and as_utc(row.ready_at)>main.now():
        remaining=max(1,int(math.ceil((as_utc(row.ready_at)-main.now()).total_seconds())))
        if remaining>seconds:row.ready_at=main.now()+timedelta(seconds=seconds);db.commit();remaining=seconds
        if 'task_queue' in vars(main):main.task_queue.cooldown_wait.set(remaining)
        return remaining
    if not row:row=Cooldown(channel_id=p.channel_id,canonical_uid=p.twitch_uid,action=action_name,ready_at=main.now());db.add(row)
    row.ready_at=main.now()+timedelta(seconds=seconds);db.commit();return 0
COOLDOWN_LABELS={"seed_work":("/make, /gather and common /mine","!make, !gather and !mine"),"seed_use":("/use","!use"),
    "rare_prospect":("Rare ore mining (/mine)","rare ore mining")}

def cooldown_label(action_name,provider):
    if action_name in COOLDOWN_LABELS:return COOLDOWN_LABELS[action_name][0 if provider=="discord" else 1]
    return guide_command(action_name,"discord" if provider=="discord" else "twitch")

def cooldown_rules(provider="discord"):
    prefix="/" if provider=="discord" else "!"
    return (f"Work, {prefix}eat, {prefix}make and {prefix}gather: 5s. Rare ores: 20s. Item {prefix}use: 20s. "
            f"Social and recovery: 20–60s. {prefix}sleep: {duration_text(SLEEP_COOLDOWN_SECONDS)} (fully restores Energy and Comfort).")

def cooldowns_text(db,p,provider="twitch"):
    rows=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid)).scalars().all()
    active=sorted((r.action,min(ACTION_COOLDOWNS.get(r.action,5),max(1,int(math.ceil((as_utc(r.ready_at)-main.now()).total_seconds()))))) for r in rows if as_utc(r.ready_at)>main.now())
    rules=cooldown_rules(provider)
    if not active:return "⏱️ No active cooldowns. Tasks still require sufficient needs and materials. "+rules
    if provider=="discord":return f"⏱️ {p.display_name} — Active Cooldowns\n\n"+"\n".join(f"• {cooldown_label(a,provider)} — {duration_text(seconds)}" for a,seconds in active[:15])+"\n\n"+rules
    return "⏱️ Cooldowns: "+" | ".join(f"{cooldown_label(a,provider)} {duration_text(seconds)}" for a,seconds in active[:10])+" | "+rules
def action_wait(db,p,action_name):
    row=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid,Cooldown.action==action_name)).scalar_one_or_none()
    return min(ACTION_COOLDOWNS.get(action_name,5),max(0,int(math.ceil((as_utc(row.ready_at)-main.now()).total_seconds())))) if row and as_utc(row.ready_at)>main.now() else 0
DISCORD_ACTION_ROUTES={
    "farm":"/farm action:Tend Fields","forage":"/farm action:Tend Fields",
    "harvest":"/farm action:Harvest Pumpkins","water":"/farm action:Irrigate",
    "scavenge":"/mine","machine":"/make","work":"/make","craft":"/make","fabricate":"/make",
    "repair":"/repair target:Society Infrastructure","project":"/repair target:Society Infrastructure","build":"/repair target:Society Infrastructure",
    "survey":"/explore operation:Advanced Survey","market":"/market action:Commerce Work",
    "business":"/business action:Work","businesscontract":"/business action:Contract","businessinvest":"/business action:Invest",
    "hi":"/social action:Say Hi player:<name>","hangout":"/social action:Hang Out player:<name>",
    "mentor":"/social action:Mentor player:<name>","duo":"/social player:<name>",
    "gearrepair":"/repair target:Personal Quality Gear item:<item>",
    "sell":"/market action:Sell Resources resource:<resource> amount:<amount>",
}
ACTION_DISPLAY_NAMES={
    "farm":"Tend Fields","forage":"Tend Fields","harvest":"Harvest Pumpkins","water":"Irrigate",
    "scan":"Environmental Scan","mine":"Mining","rare":"Rare-ore Prospecting","scavenge":"Mining",
    "craft":"Crafting","machine":"Crafting","work":"Crafting",
    "repair":"Society Infrastructure Repair","project":"Society Infrastructure Repair","build":"Society Infrastructure Repair",
    "cargo":"Cargo Preparation","delivery":"Delivery","spaceport":"Spaceport Operations",
    "explore":"Frontier Scout","survey":"Advanced Survey","market":"Commerce Work",
    "business":"Business Work","businesscontract":"Business Contract","businessinvest":"Business Investment",
    "research":"Research",
}
def guide_command(action_name,provider):
    if action_name in SEED_TASKS:
        cfg=SEED_TASKS[action_name]
        return f"/training skill:{cfg['hub']} task:{action_name}" if provider=="discord" else f"!training {cfg['hub']} {action_name}"
    if provider!="discord":
        twitch_routes={
            "duo_walk":"!duo <name> walk","duo_games":"!duo <name> games",
            "duo_research":"!duo <name> research","duo_delivery":"!duo <name> delivery",
            "duo_explore":"!duo <name> explore",
        }
        return twitch_routes.get(action_name,"!"+action_name)
    return DISCORD_ACTION_ROUTES.get(action_name,"/"+action_name)
def action_display_name(action_name,mode=""):
    if action_name in SEED_TASKS:return SEED_TASKS[action_name]["label"]
    if mode=="hydroponics":return "Hydroponics"
    if mode=="field_analysis":return "Field Analysis"
    if mode=="expedite":return "Expedited Spaceport Operations"
    if mode=="analyze":return "Market Analysis"
    return ACTION_DISPLAY_NAMES.get(action_name,action_name.replace("_"," ").title())
def guide_action(db,p,skill,provider):
    if skill in {"cooking","medicine","emergency","fabrication"}:
        hub=next(h for h,k in SEED_HUBS.items() if k==skill)
        return (f"/training skill:{hub}" if provider=="discord" else f"!training {hub}",0)
    business_exists=db.execute(select(Business).where(Business.channel_id==p.channel_id,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none() is not None
    choices=[]
    for action_name in SKILL_ACTIONS[skill]:
        if action_name in SEED_TASKS and (lvl(skill_xp(p,skill))<SEED_TASKS[action_name]["unlock"] or any(material_amount(db,p,k)<v for k,v in SEED_TASKS[action_name]["cost"].items())):continue
        if action_name=="craft" and p.ore<=0:continue
        if action_name=="delivery" and p.cargo<=0:continue
        if action_name in {"business","businesscontract","businessinvest"} and not business_exists:continue
        choices.append((action_wait(db,p,action_name),action_name))
    if not choices:choices=[(action_wait(db,p,SKILL_ACTIONS[skill][0]),SKILL_ACTIONS[skill][0])]
    wait,action_name=min(choices,key=lambda x:(x[0],SKILL_ACTIONS[skill].index(x[1])))
    return guide_command(action_name,provider),wait
def audit_moderator(db,channel,moderator,action_name,detail):
    db.add(ModeratorAudit(channel_id=channel,moderator=moderator,action=action_name,detail=detail[:500]));db.commit()
def live(w):
    return bool(w.active_event and w.event_ends and main.now()<as_utc(w.event_ends))
def item(db,c,u,name):
    name=item_identity.canonical(name)
    if name in item_identity.FIELD_ITEMS:
        p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==u)).scalar_one_or_none()
        return getattr(p,item_identity.FIELD_ITEMS[name]) if p else 0
    r=db.execute(select(ExtraItem).where(ExtraItem.channel_id==c,ExtraItem.canonical_uid==u,ExtraItem.item==name)).scalar_one_or_none()
    return r.qty if r else 0
def item_add(db,c,u,name,d):
    name=item_identity.canonical(name)
    if name in item_identity.FIELD_ITEMS:
        p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==u)).scalar_one()
        result=material_change(db,p,name,d);db.commit();return result
    r=db.execute(select(ExtraItem).where(ExtraItem.channel_id==c,ExtraItem.canonical_uid==u,ExtraItem.item==name)).scalar_one_or_none()
    if not r:r=ExtraItem(channel_id=c,canonical_uid=u,item=name,qty=0);db.add(r)
    r.qty=max(0,r.qty+d);db.commit();return r.qty
PLAYER_MATERIAL_FIELDS={"crops","ore","rare_ore","components","cargo"}
def material_amount(db,p,key):
    key=item_identity.FIELD_ITEMS.get(item_identity.canonical(key),item_identity.canonical(key))
    if key in PLAYER_MATERIAL_FIELDS:return max(0,int(getattr(p,key)))
    return item(db,p.channel_id,p.twitch_uid,key)
def material_change(db,p,key,delta):
    key=item_identity.FIELD_ITEMS.get(item_identity.canonical(key),item_identity.canonical(key))
    if key in PLAYER_MATERIAL_FIELDS:
        setattr(p,key,max(0,int(getattr(p,key))+int(delta)));return getattr(p,key)
    row=db.execute(select(ExtraItem).where(
        ExtraItem.channel_id==p.channel_id,
        ExtraItem.canonical_uid==p.twitch_uid,
        ExtraItem.item==key
    )).scalar_one_or_none()
    if not row:
        row=ExtraItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item=key,qty=0);db.add(row)
    row.qty=max(0,row.qty+int(delta));return row.qty
def craft_output_key(recipe):return CRAFT_OUTPUT_KEYS.get(recipe,recipe)
def craft_output_amount(db,p,recipe):return material_amount(db,p,craft_output_key(recipe))

def material_source(key,provider='discord'):
    """Exact sources: catalog items, legacy equipment recipes, or Cargo work."""
    key=item_identity.canonical(key)
    if key==item_identity.ALIASES['crops']:
        farm='/farm action:Harvest Pumpkins' if provider=='discord' else '!harvest'
        return farm+' (3 per success) or '+seed_content.source_hint(key,provider)
    if key in seed_content.ACTIVE:return seed_content.source_hint(key,provider)
    if key=='cargo':return ('/cargo' if provider=='discord' else '!cargo')+' — successful Cargo Preparation adds 1 personal Cargo.'
    if key in RECIPES or key in QUALITY_RECIPES:
        cost=RECIPES[key] if key in RECIPES else QUALITY_RECIPES[key]['cost']
        station=crafting_progression.STATIONS[crafting_progression.legacy_station(main,key)]
        return (f'/make recipe:{key}' if provider=='discord' else f'!make {key}')+f" — {requirement_text(cost)}; {station['name']} (Tier {station['tier']})."
    for task,cfg in SEED_TASKS.items():
        if key in cfg['output']:
            command=f"/training skill:{cfg['hub']} task:{task}" if provider=='discord' else f"!training {cfg['hub']} {task}"
            return command+' — '+(requirement_text(cfg['cost']) or 'no ingredients')+f"; {SKILL_LABELS[cfg['skill']]} Lv.{cfg['unlock']}."
    return 'Inspect the item in /catalog.'

def missing_material_sources(db,p,cost,provider):
    return '\nHOW TO GET THEM\n'+'\n'.join(f'• {resource_name(k)}: {material_source(k,provider)}' for k,n in cost.items() if material_amount(db,p,k)<n)

def craft_record(db,p,recipe,quality=""):
    row=db.execute(select(CraftLedger).where(
        CraftLedger.channel_id==p.channel_id,CraftLedger.canonical_uid==p.twitch_uid,CraftLedger.recipe==recipe
    )).scalar_one_or_none()
    if not row:row=CraftLedger(channel_id=p.channel_id,canonical_uid=p.twitch_uid,recipe=recipe,qty=0,best_quality="");db.add(row)
    row.qty+=1
    if quality:
        ranks=list(QUALITY_TIERS)
        if not row.best_quality or ranks.index(quality)>ranks.index(row.best_quality):row.best_quality=quality
    return row

def determination_row(db,p,skill):
    row=db.execute(select(Determination).where(
        Determination.channel_id==p.channel_id,Determination.canonical_uid==p.twitch_uid,Determination.skill==skill
    )).scalar_one_or_none()
    if not row:row=Determination(channel_id=p.channel_id,canonical_uid=p.twitch_uid,skill=skill,stacks=0);db.add(row)
    return row
def determination_bonus(db,p,skill):
    if not skill:return 0
    return min(3,determination_row(db,p,skill).stacks)*.04
def determination_fail(db,p,skill):
    if not skill:return ""
    row=determination_row(db,p,skill);row.stacks=min(3,row.stacks+1);db.commit()
    return f" 🔥 Determination {row.stacks}/3: next {SKILL_LABELS[skill]} attempt gains +{row.stacks*4} percentage points."
def determination_clear(db,p,skill):
    if not skill:return ""
    row=determination_row(db,p,skill)
    if row.stacks<=0:return ""
    used=row.stacks;row.stacks=0;db.commit();return f" ✅ Determination +{used*4}% was used and reset after success."

def available_production_orders(channel,day,tier_index):
    eligible=[(key,data) for key,data in PRODUCTION_ORDERS.items() if data["tier"]<=tier_index]
    return sorted(eligible,key=lambda row:_stable_index(f"{channel}:{day}:{row[0]}:order",10**9))[:min(3,len(eligible))]
def replacement_value(key):
    """NPC replacement cost: purchase price, else catalog appraisal, else parts."""
    key=item_identity.canonical(key)
    if SEED_INDUSTRIES.get(key,{}).get("buy"):return SEED_INDUSTRIES[key]["buy"]
    if key in crafting_progression.VALUES:return crafting_progression.VALUES[key]
    if key in RECIPES:return sum(replacement_value(part)*qty for part,qty in RECIPES[key].items())+CRAFT_PAY["core"]["sc"]
    if key in QUALITY_RECIPES:return sum(replacement_value(part)*qty for part,qty in QUALITY_RECIPES[key]["cost"].items())+CRAFT_PAY["quality"]["sc"]
    raise KeyError(f"No economy value for {key}")
def production_order_numbers(data):
    replacement=sum(replacement_value(key)*amount for key,amount in data["cost"].items())
    reward=max(8,int(math.floor(replacement*.75)))
    units=sum(data["cost"].values())
    tier=max(0,int(data.get("tier",0)))
    return {"replacement":replacement,"sc":reward,"contribution":1+tier,"development":2+tier}
def order_completed(db,p,day,key):
    return db.execute(select(ProductionOrderCompletion).where(
        ProductionOrderCompletion.channel_id==p.channel_id,
        ProductionOrderCompletion.canonical_uid==p.twitch_uid,
        ProductionOrderCompletion.avesta_day==day,
        ProductionOrderCompletion.order_key==key
    )).scalar_one_or_none() is not None
def unique_bonus_owned(db,p,key):
    if key in UNIQUE_CORE_ITEMS:
        return material_amount(db,p,key)>0
    if key in UNIQUE_QUALITY_ITEMS:
        return db.execute(select(QualityGear).where(
            QualityGear.channel_id==p.channel_id,
            QualityGear.canonical_uid==p.twitch_uid,
            QualityGear.item_key==key,
            QualityGear.qty>0
        )).scalars().first() is not None
    return False
def daily(db,p):
    k=main.now().strftime("%Y-%m-%d")
    d=db.execute(select(Daily).where(Daily.channel_id==p.channel_id,Daily.canonical_uid==p.twitch_uid,Daily.day_key==k)).scalar_one_or_none()
    if not d:
        a=random.choice(["harvest","mine","research","make","delivery","explore","water","repair","train_fire_safety","train_seed_cultivation","train_ore_mining"]);t=random.choice([3,4,5])
        d=Daily(channel_id=p.channel_id,canonical_uid=p.twitch_uid,day_key=k,action=a,target=t,reward_sc=t*3);db.add(d);db.commit();db.refresh(d)
    return d
def progress_daily(db,p,a):
    d=daily(db,p)
    if d.action=="craft" and a=="make":a="craft" # finish legacy contracts created before /make consolidation
    if d.complete or d.action!=a:return ""
    d.progress+=1
    if d.progress>=d.target:
        d.progress=d.target;d.complete=True;p.sc+=d.reward_sc;p.contribution+=1;db.commit()
        return f" 📋 Daily complete! +{d.reward_sc} SC/+1 Contribution."
    db.commit();return f" 📋 Daily {d.progress}/{d.target}."
