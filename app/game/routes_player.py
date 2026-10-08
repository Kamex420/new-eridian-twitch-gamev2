"""Routes: health, start, profile, skills, cooldowns, bonuses, guide, inventory, job, contracts, achievements, home
and business.
"""
import json
import os
import re
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text as sql_text
from .. import item_identity, seed_content, workbench
from ..commands import command as colony_command, transaction as game_transaction
from ..db import SessionLocal
from ..needs import (
    blocked_needs, COMFORT_BLOCK, COMFORT_SLOW, cost_text as need_cost_text, duration_text, HEAVY_ENERGY,
    SLEEP_COOLDOWN_SECONDS, STANDARD_ENERGY, TASK_NEED_MINIMUM)
from ..seed_skills import TASKS as SEED_TASKS
from ..settlement import seedling as colony_seedling
from ..models import Achievement, Business, CraftLedger, Home, ProductionOrderCompletion, QualityGear, Specialization
from .base import app, GAME_NAME, GAME_TITLE, out, platform_response, valid_mod_key
from .rules import (
    ACTION_SKILLS, EVENTS, ITEM_EFFECTS, JOBS, PART_RECIPES, QUALITY_RECIPES, SKILL_ACTIONS, SKILL_LABELS,
    SOCIETY_TIERS, SPECIALIZATIONS)
from .players import (
    active_bonuses, as_utc, bonuses_text, business_for, business_xp_needed, citizen_title, cost_text, equipped_title,
    home_upgrade_cost, lvl, market_demand, player, resource_name, skill_xp, society, specialization_for, story_state,
    tutorial_advance, tutorial_text, world)
from .life import life_state
from .world import directive_for, need_fix, sleep_status, society_tier, society_tier_index, world_clock
from .cooldowns_materials import (
    action_display_name, action_wait, available_production_orders, cooldowns_text, daily, guide_action,
    guide_command, material_amount, material_source, order_completed)
from .colony_events import auto_event_status, resolve_expired_event
from .accounts import achieve, config_warnings, parts_crafted
from .. import main      # app.main: names from later modules and settings changed at runtime

@app.get("/health")
def health(key:str=""):
    try:
        with main.engine.connect() as conn:conn.execute(sql_text('SELECT 1'))
        workers={}
        for name in ('queue_worker','notification_worker','discord_notification_worker','autonomy_worker'):
            worker=getattr(app.state,name,None)
            workers[name]='running' if worker is not None and not worker.done() else 'not started' if worker is None else 'stopped'
        if 'stopped' in workers.values():raise RuntimeError('worker stopped')
    except Exception:
        raise HTTPException(status_code=503,detail='Game service is temporarily unavailable') from None
    return {"ok":True,"game":GAME_TITLE,"society":GAME_NAME,"version":"7.0.0","workers":workers,"discord_queue_sender":getattr(getattr(app.state,"discord_queue",None),"state","not started"),
            # Details only with a moderator or admin key: they say how the game is set up.
            **({"warnings":config_warnings()} if valid_mod_key(key) else {"warnings_count":len(config_warnings()),"warnings_detail":"add ?key=MOD_KEY"})}

@app.get("/api/v1/start")
@game_transaction
def start(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    from .. import onboarding
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if onboarding.welcome(db,p):
            text=onboarding.welcome_text(db,p,provider);db.commit()
            return platform_response(provider,text,text)
        discord=f"🌱 {p.display_name} — Citizen Ready\n\n🪙 Starting balance: {p.sc} SC\n💼 Next: choose a job with /job\n🧭 Need direction? Use /guide"
        twitch=f"🌱 {p.display_name} is ready in New Eridian with {p.sc} SC. Next: !job to choose work, then !guide for your best action."
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/profile")
@colony_command
def profile(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        job_name=JOBS.get(p.job,("Settler",set()))[0];b=business_for(db,p);active=len(active_bonuses(db,p));identity=citizen_title(p)
        discord=(f"🌱 Seedling {p.display_name} — {identity}\n\n"
                 f"💼 Occupation / Job: {job_name}\n🪙 Seed Coin: {p.sc} SC\n⭐ Contribution: {p.contribution}\n\n"
                 f"🌿 Life: Farming L{lvl(p.farm_xp)} · Processing L{lvl(p.environmental_xp)}\n"
                 f"🏭 Production: Harvesting L{lvl(p.mining_xp)} · Crafting L{lvl(p.fabrication_xp)} · Engineering L{lvl(p.infrastructure_xp)}\n"
                 f"🍳 Care: Cooking L{lvl(p.cooking_xp)} · Medicine L{lvl(p.medicine_xp)} · Emergency Response L{lvl(p.emergency_xp)}\n"
                 f"🛰️ Operations: Research L{lvl(p.research_xp)} · Logistics L{lvl(p.delivery_xp)} · Frontier L{lvl(p.explore_xp)} · Commerce L{lvl(p.commerce_xp)}\n\n"
                 +(f"\n🏢 Business: {b.name} · Level {b.level}" if b else "\n🏢 Business: Not registered")+f"\n⚡ Active bonuses: {active}\n\nUse /progress section:Skills & Level Unlocks for XP details or /guide for your personal next step.")
        title=equipped_title(db,p);display=f"{p.display_name}"+(f" — {title}" if title else "")
        discord=discord.replace(f"👤 {p.display_name}",f"👤 {display}")+"\n\n"+tutorial_text(db,p,provider)
        twitch=f"👤 {display} | {identity} | 🪙{p.sc} SC | ⭐{p.contribution} | 🏢{b.name+' L'+str(b.level) if b else 'No business'} | ⚡{active} bonuses | 🌱{lvl(p.farm_xp)} 💧{lvl(p.environmental_xp)} ⛏️{lvl(p.mining_xp)} ⚙️{lvl(p.fabrication_xp)} 🏗️{lvl(p.infrastructure_xp)} 🔬{lvl(p.research_xp)} 📦{lvl(p.delivery_xp)} 🧭{lvl(p.explore_xp)} 🏪{lvl(p.commerce_xp)}"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/skills")
@colony_command
def skills(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        specs={r.skill:SPECIALIZATIONS.get(r.skill,{}).get(r.choice,r.choice) for r in db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==p.twitch_uid)).scalars()}
        rows=[f"• {label}: Lv. {lvl(skill_xp(p,key))} · {skill_xp(p,key)} XP"+(f" · {specs[key]}" if key in specs else "") for key,label in SKILL_LABELS.items()]
        text=f"🧬 {p.display_name} — Skills\n\n"+"\n".join(rows)
        text+="\n\nThe eight skill families use the names in your reference screenshots. Research, Logistics, Frontier Operations and Commerce remain minigame skills. Existing XP is preserved; new skills and branch practice start at zero."
        text+="\nLevel 2: 5 XP; level 3: 12 XP; level 4: 22 XP; level 5: 35 XP; then 15 XP per level. Open /training and select Skill to view branches, requirements, jobs and your branch levels. Choose Task only when ready to work. Specializations unlock at main skill level 10; specialist medical branches require Medicine 5."
        return PlainTextResponse(text) if provider=="discord" else out("Skills | "+" · ".join(rows))


@app.get("/api/v1/specialize")
@colony_command
def specialize(channel:str,uid:str,name:str="Citizen",path:str="",provider:str="twitch"):
    path=path.lower().strip().replace(" ","_")
    if ":" not in path:return out("🧬 Choose skill:path. Example: research:siro_analyst. Use /specialize choices in Discord.")
    skill,choice=path.split(":",1)
    if skill not in SPECIALIZATIONS or choice not in SPECIALIZATIONS[skill]:return out("⛔ Unknown specialization path.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if lvl(skill_xp(p,skill))<10:return out(f"🔒 {SKILL_LABELS[skill]} Lv. 10 required. You are Lv. {lvl(skill_xp(p,skill))}.")
        existing=specialization_for(db,p,skill)
        if existing:return out(f"🧬 {SKILL_LABELS[skill]} is already specialized as {SPECIALIZATIONS[skill][existing.choice]}.")
        db.add(Specialization(channel_id=channel,canonical_uid=p.twitch_uid,skill=skill,choice=choice));db.commit()
        return out(f"🧬 {p.display_name} specialized as {SPECIALIZATIONS[skill][choice]}. Matching actions gain +3% success and +1 SC.")

@app.get("/api/v1/cooldowns")
@game_transaction
def cooldowns(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);text=cooldowns_text(db,p,provider);return PlainTextResponse(text) if provider=="discord" else out(text)

@app.get("/api/v1/bonuses")
@game_transaction
def bonuses(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);text=bonuses_text(db,p,provider);return PlainTextResponse(text) if provider=="discord" else out(text)

def guide_material_step(key,provider):
    """The first command for a missing material: the same route shown in /catalog."""
    return material_source(key,provider).split(" — ")[0].split(" → ")[0]

def guide_three_steps(db,p,s,w,clock,provider):
    prefix="/" if provider=="discord" else "!";life=life_state(db,p);steps=[]
    for field,label,value,minimum in blocked_needs(life):
        steps.append(f"Raise {label} ({value}) to at least {minimum}: {need_fix(field,provider,db,p)}.")
    if COMFORT_BLOCK<=life.comfort<COMFORT_SLOW:steps.append(f"Comfort {life.comfort} is low (−10% success; work stops below {COMFORT_BLOCK}): {need_fix('comfort',provider,db,p)}.")
    if len(steps)<3 and w.active_event:
        cfg=EVENTS[w.active_event];cmd,_=guide_action(db,p,cfg["primary"],provider);steps.append(f"Help {cfg['name']} with {cmd}.")
    tier_index=society_tier_index(s)
    for order_key,data in available_production_orders(p.channel_id,clock["day"],tier_index):
        if len(steps)>=3:break
        if order_completed(db,p,clock["day"],order_key):continue
        missing=[key for key,amount in data["cost"].items() if material_amount(db,p,key)<amount]
        if missing:
            key=missing[0];steps.append(f"Prepare {resource_name(key)} for {data['name']}: {guide_material_step(key,provider)}.")
        else:
            cmd=f"{prefix}seedindustries action:Fulfill item:{order_key}" if provider=="discord" else f"{prefix}seedindustries fulfill {order_key}"
            steps.append(f"Deliver the ready {data['name']} with {cmd}.")
        break
    d=daily(db,p)
    if len(steps)<3 and not d.complete:steps.append(f"Advance the Daily Contract with {guide_command(d.action,provider)} ({d.progress}/{d.target}).")
    directive,dcfg=directive_for(db,p.channel_id,clock["day"])
    if len(steps)<3 and not directive.complete:
        best=min(dcfg[2],key=lambda sk:action_wait(db,p,SKILL_ACTIONS[sk][0]));cmd,_=guide_action(db,p,best,provider)
        steps.append(f"Support today's {dcfg[1]} with {cmd} ({directive.progress}/{directive.goal}).")
    if len(steps)<3:
        stats={"Food":s.food,"Materials":s.materials,"Development":s.development,"Knowledge":s.knowledge,"Treasury":s.treasury,"Reputation":s.reputation};weak=min(stats,key=stats.get)
        route={"Food":guide_command("harvest",provider),"Materials":guide_command("mine",provider),"Development":guide_command("repair",provider),"Knowledge":guide_command("research",provider),"Treasury":guide_command("market",provider),"Reputation":guide_command("spaceport",provider)}[weak]
        steps.append(f"Strengthen New Eridian's lowest stat, {weak} ({stats[weak]}), with {route}.")
    if len(steps)<3:steps.append(f"Review production demand with {prefix}seedindustries action:Orders" if provider=="discord" else "Review production demand with !seedindustries orders.")
    return steps[:3]

@app.get("/api/v1/guide")
@colony_command
def guide(channel:str,uid:str,name:str="Citizen",goal:str="auto",provider:str="twitch"):
    goal=goal.lower().strip().replace(" ","_") or "auto"
    aliases={"money":"seed_coin","coins":"seed_coin","skill":"aptitude","skills":"aptitude","craft":"crafting"}
    goal=aliases.get(goal,goal)
    valid={"auto","event","daily","seed_coin","society","aptitude","crafting","home","business","life","story","market"}
    if goal not in valid:return out("🧭 Guide goals: auto, event, daily, seed_coin, society, aptitude, crafting, home, business, life, story, market.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);s=society(db,channel);clock=world_clock(db,channel,s);w=world(db,channel);resolve_expired_event(db,s,w)
        prefix="/" if provider=="discord" else "!"
        lines=[f"🧭 {p.display_name} — New Eridian Field Guide"]
        event_lines=[]
        if w.active_event:
            cfg=EVENTS[w.active_event];seconds=max(0,int((as_utc(w.event_ends)-main.now()).total_seconds()));primary,pwait=guide_action(db,p,cfg["primary"],provider);support,swait=guide_action(db,p,cfg["support"],provider)
            pstate="ready" if not pwait else f"{pwait}s cooldown";sstate="ready" if not swait else f"{swait}s cooldown"
            event_lines=[f"🚨 NOW: {cfg['name']} — {w.event_progress}/{w.event_goal}, {seconds//60}:{seconds%60:02d} left.",f"Best help: {primary} ({SKILL_LABELS[cfg['primary']]}, +1 progress, {pstate}).",f"Support: {support} ({SKILL_LABELS[cfg['support']]}, 2 successes = +1, {sstate})."]
        life=life_state(db,p)
        blocked_core=[(label,value,need_fix(field,provider,db,p)) for field,label,value,_ in blocked_needs(life)]
        social_fix=need_fix("social",provider)
        selected=goal
        if goal=="auto":
            d=daily(db,p)
            critical=min(life.energy,life.nutrition,life.social,life.comfort,life.morale)<25
            selected="life" if critical else ("event" if w.active_event else ("daily" if not d.complete else "story"))
        elif goal!="life" and blocked_core:
            lines.append(f"⛔ {goal.replace('_',' ').title()} guidance is paused because your core needs block tasks.")
            selected="life"
        if selected=="life":
            if blocked_core:
                lines.append(f"🏠 Work, crafting, and gear repair require Energy, Nutrition, and Social at {TASK_NEED_MINIMUM}+ and Comfort at {COMFORT_BLOCK}+.")
                lines.extend(f"• {label} {value}/100: use {fix}." for label,value,fix in blocked_core)
                lines.append("Raise every need listed above, then retry your task. Blocked attempts consume nothing and start no cooldown.")
            else:
                needs={"Energy":life.energy,"Nutrition":life.nutrition,"Social":life.social,"Comfort":life.comfort,"Morale":life.morale};low=min(needs,key=needs.get)
                routes={label:need_fix(label.lower(),provider,db,p) for label in needs}
                lines.extend([f"✅ Your core needs are high enough for tasks.",f"🏠 {low} is your lowest life need at {needs[low]}/100. Use {routes[low]} to improve it."])
        elif selected=="story":
            row,cfg=story_state(db,channel,clock);vals=[row.track_a,row.track_b,row.track_c];best=min(range(3),key=lambda i:vals[i]);skills=cfg["tracks"][best][1];skill=min(skills,key=lambda x:skill_xp(p,x));cmd,wait=guide_action(db,p,skill,provider)
            lines.extend([f"📖 Weekly story: {cfg['name']} — {sum(vals)}/{cfg['goal']}.",f"The least-supported path is {cfg['tracks'][best][0]}. Try {cmd} "+("now." if not wait else f"in {wait}s.")])
        elif selected=="market":
            a,b=market_demand(channel,clock["day"]);market_view=f"{prefix}market action:View Prices" if provider=="discord" else f"{prefix}marketboard";market_sell=f"{prefix}market action:Sell Resources" if provider=="discord" else "!sell <resource> <amount>";npc_view=f"{prefix}seedindustries";lines.extend([f"🏪 Highest rotating demand today: {resource_name(a)} (60% premium); {resource_name(b)} (30% premium).",f"Check {market_view}, then use {market_sell}. Use {npc_view} for fixed-price components."])
        elif selected=="event":
            lines.extend(event_lines or ["✅ No emergency is active. Work on your daily contract or New Eridian's weakest stat.",f"Next: {prefix}guide goal:daily" if provider=="discord" else "Next: !guide daily"])
        elif selected=="daily":
            d=daily(db,p);cmd=guide_command(d.action,provider);wait=action_wait(db,p,d.action)
            if d.complete:lines.extend(["📋 Today's contract is complete.",f"Next: {prefix}guide goal:society" if provider=="discord" else "Next: !guide society"])
            else:lines.extend([f"📋 Daily: {action_display_name(d.action)} {d.progress}/{d.target}.",f"Do {cmd} next"+(f" when its {wait}s cooldown ends." if wait else " now.")+f" Reward: {d.reward_sc} SC +1 Contribution."])
        elif selected=="seed_coin":
            job_actions=[a for a in JOBS.get(p.job,("",set()))[1] if a in ACTION_SKILLS and a not in {"build","businessinvest"}]
            owned_business=business_for(db,p)
            job_actions=[a for a in job_actions if not (
                (a in SEED_TASKS and (lvl(skill_xp(p,SEED_TASKS[a]["skill"]))<SEED_TASKS[a]["unlock"] or any(material_amount(db,p,k)<v for k,v in SEED_TASKS[a]["cost"].items()))) or
                (a in {"business","businesscontract"} and not owned_business) or
                (a=="delivery" and p.cargo<=0) or
                (a=="survey" and equipment_count(db,p,"sensor")<=0) or
                (a=="craft" and p.ore<=0) or
                (provider=="discord" and a in {"work","machine","craft"})
            )]
            ranked=sorted((action_wait(db,p,a),a) for a in job_actions)
            if ranked:wait,a=ranked[0];reason=f"your {JOBS[p.job][0]} job adds +1 SC"
            else:
                a="market";wait=action_wait(db,p,a);reason="it has strong base pay"
            contract_view=f"{prefix}progress section:Daily Contract" if provider=="discord" else f"{prefix}contracts";lines.extend([f"🪙 You have {p.sc} SC. Do {guide_command(a,provider)} "+("now" if not wait else f"in {wait}s")+f"; {reason}.",f"Use {contract_view} for today's bonus, and {prefix}job to change your paid specialty."])
        elif selected=="society":
            stats={"food":s.food,"materials":s.materials,"development":s.development,"knowledge":s.knowledge,"treasury":s.treasury,"reputation":s.reputation};weak=min(stats,key=stats.get)
            routes={"food":("cultivation","harvest"),"materials":("extraction","mine"),"development":("infrastructure","repair"),"knowledge":("research","research"),"treasury":("commerce","market"),"reputation":("logistics","spaceport")};skill,a=routes[weak];wait=action_wait(db,p,a);tier=society_tier(s);next_tier=next((x for x in SOCIETY_TIERS if x[1]>min(stats.values())),None)
            lines.extend([f"🏗️ Priority: {weak.title()} is lowest at {stats[weak]}. Do {guide_command(a,provider)} "+("now." if not wait else f"in {wait}s."),f"Tier: {tier[0]}. "+(f"Reach {next_tier[1]} in every major stat for {next_tier[0]}." if next_tier else "Regional Hub is fully unlocked.")])
        elif selected=="aptitude":
            skill=min(SKILL_LABELS,key=lambda x:skill_xp(p,x));cmd,wait=guide_action(db,p,skill,provider);level=lvl(skill_xp(p,skill))
            lines.extend([f"🧬 Lowest aptitude: {SKILL_LABELS[skill]} Lv. {level} ({skill_xp(p,skill)} XP).",f"Train it with {cmd} "+("now." if not wait else f"in {wait}s.")+(f" At Lv. 10, use {prefix}specialize." if level<10 else f" Use {prefix}specialize if you have not chosen a path.")])
        elif selected=="crafting":
            lines.extend(workbench.guide_lines(db,p,provider))
        elif selected=="home":
            h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none();tier=h.tier if h else 1;cost,component_cost=home_upgrade_cost(tier)
            lines.extend(habitat_upgrade_plan(p,tier,provider))
        elif selected=="business":
            b=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
            if b:
                business_routes=f"Best income: {prefix}business action:Contract. Growth: {prefix}business action:Invest. Routine work: {prefix}business action:Work." if provider=="discord" else f"Best income: {prefix}businesscontract. Growth: {prefix}businessinvest. Routine work: {prefix}businesswork."
                lines.extend([f"🏢 {p.display_name}, {b.name} is Level {b.level} with {b.xp}/{business_xp_needed(b.level)} XP.",business_routes])
            else:
                business_start_command=f"{prefix}business action:Start" if provider=="discord" else f"{prefix}businessstart"
                lines.extend([f"🏢 A business costs 75 SC; you have {p.sc}.",(f"Earn {75-p.sc} more SC with "+("/guide goal:seed_coin" if provider=="discord" else "!guide seed_coin")+f", then use {business_start_command}." if p.sc<75 else f"✅ You can afford to start now. Use {business_start_command}.")])
        if selected!="event" and event_lines:lines.extend(["",*event_lines])
        steps=guide_three_steps(db,p,s,w,clock,provider)
        lines.extend(["","🧬 TASK COST FORECAST",f"• Standard work and /make: {need_cost_text(STANDARD_ENERGY,'/','-')}. Heavy extraction, frontier, and repair work: {need_cost_text(HEAVY_ENERGY,'/','-')}. Comfort drains at the same rate as Energy.",
                      f"• Current readiness: Energy {life.energy} · Nutrition {life.nutrition} · Social {life.social} (each {TASK_NEED_MINIMUM}+) · Comfort {life.comfort} ({COMFORT_BLOCK}+; below {COMFORT_SLOW} slows work).",
                      f"• Sleep: {sleep_status(db,p,provider)}. It fully restores Energy and Comfort once every {duration_text(SLEEP_COOLDOWN_SECONDS)}."])
        if goal=="auto":lines.extend(["","NEXT THREE STEPS",*[f"{i}. {step}" for i,step in enumerate(steps,1)]])
        if not w.active_event:lines.extend(["",f"⚡ {auto_event_status(db,w)}"])
        result="\n".join(lines) if provider=="discord" else (f"🧭 {p.display_name} | "+" | ".join(lines[1:lines.index("🧬 TASK COST FORECAST")-1]))
        return PlainTextResponse(result) if provider=="discord" else out(result)

@app.get("/api/v1/inventory")
@game_transaction
def inventory(channel:str,uid:str,name:str="Citizen",provider:str="twitch",search:str="",sort:str="",show:str="",page:int=1,text:str=""):
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name)
        if text:search,sort,show,page=main.qol.parse_inventory_text(text)
        if search or sort or show or page>1:
            result=main.qol.inventory_text(db,p,provider,search,sort or "quantity",show or "all",page)
            return platform_response(provider,result,result)
        equipment=[(key,equipment_count(db,p,key)) for key in ITEM_EFFECTS]
        owned_equipment=[f"{resource_name(key)} ×{qty}: {ITEM_EFFECTS[key]}" for key,qty in equipment if qty]
        stock=seed_content.stock(db,p)
        if p.cargo>0:stock['cargo']=p.cargo
        gear_keys={item_identity.canonical(k) for k,_ in equipment}
        # One list: Pumpkin, Hematite Ore, Argentite Ore and Iron Nails are ordinary items like any other.
        supplies=sorted(((k,n) for k,n in stock.items() if (k in seed_content.ACTIVE or k=='cargo') and k not in gear_keys),key=lambda row:(-row[1],resource_name(row[0])))
        gear=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
        next_step=workbench.next_step(db,p,provider)
        discord=(f"🎒 {p.display_name} — Inventory\n\n🪙 {p.sc} SC"+
                 "\n\n🧰 EQUIPMENT\n"+("\n".join("• "+x for x in owned_equipment) if owned_equipment else "• None yet. Equipment appears under /make category:equipment.")+
                 "\n\n🗃️ ITEMS\n"+("\n".join(f"• {resource_name(k)} ×{n}" for k,n in supplies[:15]) if supplies else "• None yet. /gather collects natural materials.")+
                 (f"\n{len(supplies)} item types. /inventory search:<name> or /catalog owned:True lists the rest." if len(supplies)>15 else "")+
                 f"\n\n⚙️ QUALITY GEAR\n• {sum(g.qty for g in gear)} item(s). /inventory section:Quality Gear shows condition."+
                 "\n\n🔎 /inventory search:<name> sort:value show:ready finds and sorts everything you own."+
                 f"\n\nSuggested next step: {next_step}")
        twitch=(f"🎒 {p.display_name} | {p.sc} SC | "+(", ".join(f"{resource_name(k)} {n}" for k,n in supplies[:5]) or "No items yet")+
                (" | Gear: "+", ".join(f"{resource_name(k)} {q}" for k,q in equipment if q) if owned_equipment else "")+
                f" | {len(supplies)} item types | !inv <search|value|ready> for more")
        return platform_response(provider,discord,twitch)

def equipment_count(db,p,key):
    """Owned copies of an equipment requirement, whether catalog item or quality gear."""
    if key in QUALITY_RECIPES:
        return sum(row.qty for row in db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key==key,QualityGear.qty>0)).scalars())
    return material_amount(db,p,key)

@app.get("/api/v1/job")
@colony_command
def job(channel:str,uid:str,name:str="Citizen",job:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);job=job.lower().strip()
        if job not in JOBS:return out("💼 Jobs: "+", ".join(k for k in JOBS if k!="cultivator"))
        st=colony_seedling(db,p)
        history=json.loads(st.occupation_history)
        if p.job!=job:history.append({"from":p.job,"to":job,"at":main.now().isoformat()})
        st.occupation_history=json.dumps(history)
        p.job=job;p.last_job_change=main.now();db.commit();note=tutorial_advance(db,p,"job");return out(f"💼 {p.display_name} has occupation {JOBS[job][0]}. Matching work earns bonus SC, practice and +2% success."+note)

@app.get("/api/v1/contracts")
@game_transaction
def contracts(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);d=daily(db,p);st="COMPLETE" if d.complete else f"{d.progress}/{d.target}"
        cmd=guide_command(d.action,provider)
        discord=f"📋 {p.display_name} — Daily Contract\n\nTask: {cmd}\nProgress: {st}\nReward: {d.reward_sc} SC + 1 Contribution"+("\n\n✅ Contract complete." if d.complete else f"\n\nNext: use {cmd}.")
        twitch=f"📋 Daily Contract | {cmd} {st} | Reward {d.reward_sc} SC +1 Contribution"+(" | Complete!" if d.complete else "")
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/achievements")
@game_transaction
def achievements(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);achieve(db,p)
        rows=db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==p.twitch_uid)).scalars().all()
        trophy_count=sum(1 for r in rows if r.code.startswith("trophy:"))
        names=[r.code.replace("_"," ").title() for r in rows if not r.code.startswith("trophy:")]
        order_count=len(db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all())
        crafted={r.recipe for r in db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==p.twitch_uid)).scalars().all()}
        parts_done=parts_crafted(crafted)
        progress=[f"Actions: {min(p.actions,10)}/10",f"Contribution: {min(p.contribution,50)}/50",f"Seed Coin: {min(p.sc,250)}/250 SC",f"Component catalog: {parts_done}/{len(PART_RECIPES)} (Iron Nails, Flaxa, Iron Plate, Circuit Board, Power Cell, Mortar, Glass)",f"Production Orders: {order_count}/1 · {order_count}/10 · {order_count}/30"]
        discord=(f"🏆 {p.display_name} — Achievements & Milestones\n\nUNLOCKED\n"+
                 ("\n".join(f"• {x}" for x in names) if names else "• None yet")+
                 "\n\nACTIVE PROGRESS\n"+"\n".join(f"• {x}" for x in progress)+
                 "\n\nMilestone titles unlock at 1, 10, and 30 completed Production Orders. Crafting every component in the catalog list above and producing a Masterwork have their own achievements."
                 +(f"\n\n🏅 Trophies: {trophy_count} earned. /trophies shows every collection and trophy." if trophy_count else "\n\n🏅 Collections and trophies: /trophies"))
        return platform_response(provider,discord,"🏆 "+(", ".join(names) if names else "No achievements yet."))

def habitat_upgrade_plan(p,tier,provider):
    cost,nails=home_upgrade_cost(tier)
    missing_sc=max(0,cost-p.sc);missing_nails=max(0,nails-p.components)
    upgrade="/home action:upgrade" if provider=="discord" else "!homeup"
    lines=[f"🏠 Habitat Tier {tier} → Tier {tier+1}",
           f"Upgrade cost: {cost} SC and {nails} Iron Nails.",
           f"You have: {p.sc} SC and {p.components} Iron Nails."]
    missing=[]
    if missing_sc:missing.append(f"{missing_sc} SC")
    if missing_nails:missing.append(f"{missing_nails} Iron Nails")
    if not missing:
        lines.append(f"✅ Ready to upgrade. Use {upgrade}.")
        return lines
    lines.append("Still needed: "+" and ".join(missing)+".")
    if missing_sc:
        earn="/guide goal:seed_coin" if provider=="discord" else "!guide seed_coin"
        lines.append(f"Earn the remaining {missing_sc} SC: use {earn}.")
    if missing_nails:
        lines.append(f"Iron Nails: {material_source('components',provider)}")
    lines.append(f"Then use {upgrade}. Nothing spent yet.")
    return lines

@app.get("/api/v1/home")
@game_transaction
def home(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if not h:h=Home(channel_id=channel,canonical_uid=p.twitch_uid);db.add(h);db.commit()
        plan=habitat_upgrade_plan(p,h.tier,provider)
        return platform_response(provider,"\n".join(plan)," | ".join(plan))


@app.get("/api/v1/home/upgrade")
@colony_command
def homeup(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if not h:h=Home(channel_id=channel,canonical_uid=p.twitch_uid);db.add(h);db.commit()
        cost,nail_cost=home_upgrade_cost(h.tier)
        if p.sc<cost or p.components<nail_cost:
            plan=habitat_upgrade_plan(p,h.tier,provider)
            return platform_response(provider,"⚠️ Upgrade not ready\n\n"+"\n".join(plan)," | ".join(plan))
        spent=cost_text({"sc":cost,"components":nail_cost})
        p.sc-=cost;p.components-=nail_cost;h.tier+=1;db.commit();return out(f"🏠 Habitat upgraded to Tier {h.tier}! {spent}")

@app.get("/api/v1/business")
@game_transaction
def business(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);b=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if b:
            contract_pay=5+min(8,b.level);investment_cost=25+10*b.level;discord=f"🏢 {p.display_name} — {b.name}\n\nBusiness level: {b.level}\nProgress: {b.xp}/{business_xp_needed(b.level)} XP\nCurrent contract base pay: {contract_pay} SC before personal bonuses\nCurrent investment cost: {investment_cost} SC\nPersonal bonus chance: 8% per successful action\n\n/business action:Work — routine operation\n/business action:Contract — higher pay and +2 Business XP\n/business action:Invest — +3 Business XP and society growth"
            twitch=f"🏢 {p.display_name} owns {b.name} L{b.level} ({b.xp}/{business_xp_needed(b.level)} XP) | Contract base {contract_pay} SC | !businesswork · !businesscontract · !businessinvest"
        else:
            discord="🏢 No business registered.\n\nCost: 75 SC\nNext: use /business action:Start and choose a name."
            twitch="🏢 No business yet. A business costs 75 SC. Use !businessstart <name>."
        return platform_response(provider,discord,twitch)

_BUSINESS_NAME_DROP=re.compile(r"[^\w '&.\-]")

def blocked_words():
    """BLOCKED_WORDS on Railway: comma-separated words no business name may contain (spaces and symbols ignored)."""
    return [w for w in (re.sub(r"[\W_]","",x.casefold()) for x in os.getenv("BLOCKED_WORDS","").split(",")) if w]

def safe_business_name(raw):
    """Letters, numbers, spaces and ' & . - only (no links, mentions, markdown or emoji), at most 30 characters.
    None when nothing readable is left or it contains a word from BLOCKED_WORDS."""
    text=" ".join(_BUSINESS_NAME_DROP.sub("",str(raw or "")).replace("_"," ").split())[:30].strip()
    if not any(ch.isalnum() for ch in text):return None
    squashed=re.sub(r"[\W_]","",text.casefold())
    if any(word in squashed for word in blocked_words()):return None
    return text

@app.get("/api/v1/business/start")
@game_transaction
def business_start(channel:str,uid:str,name:str="Citizen",business_name:str="New Venture",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none():return out("🏢 You already own a business.")
        if p.sc<75:return out("🏢 Starting a business costs 75 SC.")
        safe=safe_business_name(business_name)
        if safe is None:return out("🏢 Choose another business name: letters, numbers and spaces (no links, mentions or symbols). Nothing spent.")
        p.sc-=75;b=Business(channel_id=channel,canonical_uid=p.twitch_uid,name=safe);db.add(b);db.commit();return out(f"🏢 {b.name} registered. (-75 SC)")
