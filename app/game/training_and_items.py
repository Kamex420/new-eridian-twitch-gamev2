"""Training tasks, food and item menus, and the gather/catalog route.
"""
from datetime import timedelta
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from .. import crafting_progression, seed_content, task_yields, workbench
from ..commands import command as colony_command
from ..db import SessionLocal
from ..models import SkillBranch
from ..needs import cost_text as need_cost_text, STANDARD_ENERGY, TASK_NEED_MINIMUM
from ..seed_skills import HUBS as SEED_HUBS, NEW_JOBS, TASKS as SEED_TASKS
from ..settlement import state as colony_state
from ..models import QualityGear, TimedBonus
from .base import app, out, platform_response
from .rules import QUALITY_RECIPES, QUALITY_TIERS, SKILL_LABELS
from .players import as_utc, lvl, player, resource_name, skill_xp
from .life import life_state, task_energy
from .cooldowns_materials import action_display_name, material_amount, material_source
from .routes_player import equipment_count
from .routes_market import gear_repair_cost
from .action import action
from .discord_commands import training_choice_label
from .. import main      # app.main: names from later modules and settings changed at runtime

def gain_branch(db,p,branch,amount):
    row=db.get(SkillBranch,(p.channel_id,p.twitch_uid,branch))
    if not row:
        row=SkillBranch(channel_id=p.channel_id,canonical_uid=p.twitch_uid,branch=branch,xp=0);db.add(row)
    row.xp+=amount

TRAINING_ORDER={'✅':0,'❌':1,'🔒':2}   # what trains the skill right now leads the list
TRAINING_PAGE=8                         # tasks per Discord page: each fits with its Start button beside it

def training_tasks(db,p,hub,provider='twitch'):
    """One training skill's tasks, ready ones first, then missing items, then locked. Each: dict(key, cfg, status, head, uses, gives).
    status: ✅ ready · ❌ missing items · 🔒 level, tier or workstation lock (the same mark the Start button's colour follows)."""
    key=SEED_HUBS[hub];level=lvl(skill_xp(p,key))
    rows=db.execute(select(SkillBranch).where(SkillBranch.channel_id==p.channel_id,SkillBranch.canonical_uid==p.twitch_uid)).scalars().all();branch_xp={r.branch:r.xp for r in rows}
    ctx=workbench.Context(db,p,provider)
    found=[]
    for action_key,cfg in SEED_TASKS.items():
        if cfg['hub']!=hub:continue
        xp=branch_xp.get(cfg['branch'],0)
        status=training_choice_label(db,p,action_key,cfg)[:1]
        locks=[]
        if level<cfg['unlock']:locks.append(f"needs {SKILL_LABELS[key]} Lv{cfg['unlock']}")
        cost='; '.join(f"{resource_name(k)} {material_amount(db,p,k)}/{v}" for k,v in cfg['cost'].items()) or 'no items needed'
        where="";makes=""
        if action_key in main.MERGED_TRAINING:
            e=workbench.entry(main.MERGED_TRAINING[action_key]);st=ctx.status(e)
            where=f" · recipe: {e.name} at {workbench.station_label(e,ctx)} (T{e.tier}, {e.skill} Lv{e.level})"
            makes=f"makes {e.name} at the {workbench.station_label(e,ctx)} · "   # the task's name alone does not say it
            if st.code=='station':locks.append(f"needs the {workbench.station_label(e,ctx)} (craft its machine, or unlock it in /workshop)");status='🔒'
            elif st.code=='locked':locks.append(st.short);status='🔒'
        else:
            tag=crafting_progression.TRAINING_STATIONS.get(cfg['branch'])
            if tag:
                info=crafting_progression.STATIONS[tag];where=f" · station: {info['name']} (T{info['tier']})";makes=f"at the {info['name']} · "
                if tag not in ctx.access or info['tier']>ctx.tier:locks.append(f"unlock {info['name']}" if info['tier']<=ctx.tier else f"Tier {info['tier']}");status='🔒'
        batch_outputs=seed_content.production_balance.current_outputs(db,p,main.MERGED_TRAINING[action_key]) if action_key in main.MERGED_TRAINING else cfg['output']
        outputs=', '.join(f"{v} {resource_name(k)}" for k,v in batch_outputs.items())
        benefits=', '.join(f"shared {k} +{v}" for k,v in cfg['shared'].items())
        benefits+=(', ' if benefits and cfg['society'] else '')+', '.join(f"society {k} +{v}" for k,v in cfg['society'].items())
        result="; ".join(x for x in (outputs,benefits,cfg['effect']) if x)
        label=f"**{cfg['label']}**" if provider=='discord' else cfg['label']   # bold: the Start button finds its line by it
        found.append({'key':action_key,'cfg':cfg,'status':status,
                      'head':f"{status} {label} — {makes}branch Lv {lvl(xp)} ({xp} XP)"+(f" · {'; '.join(locks)}" if locks else ""),
                      'uses':f"  Uses: {cost}{where}",'gives':f"  Gives: {result or 'practice'}"})
    found.sort(key=lambda t:TRAINING_ORDER.get(t['status'],3))
    return found

def training_pages(count):
    return max(1,-(-count//TRAINING_PAGE))

def training_page_of(tasks,page):
    """(page, pages, the tasks on it) for Discord; page 0 means every task (Twitch, the API)."""
    if not page:return 1,1,tasks
    pages=training_pages(len(tasks));page=max(1,min(int(page),pages))
    return page,pages,tasks[(page-1)*TRAINING_PAGE:page*TRAINING_PAGE]

def training_skills(db,p):
    """[(hub, skill label, level, tasks ready now, tasks)] for every training skill."""
    rows=[]
    for hub,key in SEED_HUBS.items():
        tasks=training_tasks(db,p,hub,'discord')
        rows.append((hub,SKILL_LABELS[key],lvl(skill_xp(p,key)),sum(t['status']=='✅' for t in tasks),len(tasks)))
    return rows

def training_skill_line(label,level,ready,total):
    return f"**{label}** — Lv {level} · {ready} of {total} task{'s' if total!=1 else ''} ready now"

@app.get('/api/v1/training')
@colony_command
def training(channel:str,uid:str,name:str='Citizen',skill:str='',task:str='',provider:str='twitch',text:str='',page:int=0):
    if text and not skill and not task:
        parts=text.split()
        skill=parts[0] if parts else ''
        task=parts[1] if len(parts)>1 else ''
        if len(parts)>2:return out('Use !training <skill> <task>, or just !training <skill> to browse. Nothing spent.')
    hub=(skill or '').lower().strip()
    if task:
        cfg=SEED_TASKS.get(task)
        if not cfg or cfg['hub']!=hub:return out('Choose a Skill first, then one of its Task options. Nothing spent.')
        return action(task,channel,uid,name,provider=provider)
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if hub not in SEED_HUBS:
            if provider=='discord':
                return PlainTextResponse('🎓 TRAIN SKILLS\nPick a skill to see every task that trains it, each with a Start button.\n'+
                                         '\n'.join('• '+training_skill_line(label,level,ready,total) for _,label,level,ready,total in training_skills(db,p))+
                                         '\nBrowsing spends nothing. Each Start does its task once.')
            return PlainTextResponse('🎒 ITEM MENU — SKILL TRAINING\nChoose Skill, then browse its tasks.\n'+'\n'.join(f"• {SKILL_LABELS[key]} — Lv. {lvl(skill_xp(p,key))}" for key in SEED_HUBS.values())+'\nBrowsing spends nothing. Task selections perform work. Existing /make recipes and work commands still function.')
        key=SEED_HUBS[hub];level=lvl(skill_xp(p,key))
        tasks=training_tasks(db,p,hub,provider)
        page,pages,shown=training_page_of(tasks,page if provider=='discord' else 0)
        ready=sum(t['status']=='✅' for t in tasks)
        if provider=='discord':
            lead=(f"{ready} of {len(tasks)} tasks can train it now, listed first." if ready else
                  "nothing is ready yet: each task says what it still needs.")
            lines=[f"🎓 TRAIN {SKILL_LABELS[key].upper()}",f"Lv {level} · {skill_xp(p,key)} XP · {lead}",
                   "✅ ready · ❌ missing items · 🔒 level, tier or workstation lock"]
        else:
            lines=[f"🎒 ITEM MENU — {SKILL_LABELS[key]}",f"Main skill: level {level} · {skill_xp(p,key)} XP",
                   f"Each try costs {need_cost_text(STANDARD_ENERGY)} and has a 5-second cooldown. Materials are only used on success.",
                   "✅ ready · ❌ missing items · 🔒 level, tier or workstation lock"]
        lines+=['\n'.join((t['head'],t['uses'],t['gives'])) for t in shown]
        if pages>1:lines.append(f"Page {page} of {pages}: the buttons below show the other tasks.")
        if provider=='discord':
            lines.append(f"Each try costs {need_cost_text(STANDARD_ENERGY)} and has a 5-second cooldown. Materials are only used on success.")
        jobs=[label for label,sk,_ in NEW_JOBS.values() if sk==key]
        if key=='cultivation':jobs=['Farmer']
        # Kept short: where each material comes from is in /catalog and every recipe preview.
        lines.append('Matching jobs: '+', '.join(jobs)+' (/job). Branch levels add up to +5% success on their tasks.')
        lines.append('Press Start beside a task to do it once. Browsing spends nothing.' if provider=='discord'
                     else 'Do a task with !training <skill> <task>. Browsing spends nothing.')
        text='\n'.join(lines)
        return PlainTextResponse(text) if provider=='discord' else out(text.replace('\n',' | '))

def prepared_food(key):
    """Cooked or preserved catalog food (made at a workstation, not gathered raw)."""
    return key in seed_content.EDIBLE and key not in seed_content.GATHER

def grant_rockys_favor(db,p,minutes):
    boost=db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.bonus=="rockys_favor")).scalar_one_or_none()
    if not boost:boost=TimedBonus(channel_id=p.channel_id,canonical_uid=p.twitch_uid,bonus="rockys_favor",expires_at=main.now(),times_received=0);db.add(boost)
    boost.expires_at=max(main.now(),as_utc(boost.expires_at))+timedelta(minutes=minutes);boost.times_received+=1

def food_effect(key):
    text=f"+{seed_content.nutrition(key)} Nutrition"
    return text+(" · +2 Morale · Rocky's Favor 10m" if prepared_food(key) else "")

def edible_inventory(db,p):
    """Owned food, strongest first. Pumpkins (legacy Crops) are catalog food."""
    kits=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key=="meal_kit",QualityGear.qty>0)).scalars().all()
    best=max(kits,key=lambda row:list(QUALITY_TIERS).index(row.quality)) if kits else None
    kit_gain=75+int(QUALITY_TIERS[best.quality]["special"]*100) if best else 0
    stock=seed_content.stock(db,p)
    rows=[{"key":key,"name":resource_name(key),"qty":stock[key],"gain":seed_content.nutrition(key),"effect":food_effect(key)}
          for key in seed_content.EDIBLE if stock.get(key,0)>0]
    if best:rows.append({"key":"meal_kit","name":"Meal Kit","qty":sum(row.qty for row in kits),"gain":kit_gain,
                         "effect":f"+{kit_gain} Nutrition · +5 Morale; uses your best quality ({best.quality})"})
    return sorted(rows,key=lambda row:(-row["gain"],row["name"]))


def emergency_food_available(db,p,foods=None):
    return life_state(db,p).nutrition<TASK_NEED_MINIMUM and not any(row["qty"]>0 for row in (foods or edible_inventory(db,p)))


def owned_life_items(db,p):
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0,
        QualityGear.item_key.in_(["meal_kit","recreation_set","comfort_pack"]))).scalars().all()
    return {key:[row for row in rows if row.item_key==key] for key in ("meal_kit","recreation_set","comfort_pack")}


WORK_MENU_OPTIONS={
    "farm":("action",[("tend","farm",""),("harvest","harvest",""),("irrigate","water",""),("hydroponics","water","hydroponics")]),
    "research":("operation",[("standard","research",""),("field_analysis","research","field_analysis")]),
    "spaceport":("operation",[("standard","spaceport",""),("expedite","spaceport","expedite")]),
    "explore":("operation",[("scout","explore",""),("survey","survey","")]),
    "market":("action",[("work","market",""),("analyze","market","analyze")]),
}

def work_option_line(db,p,action_name,mode=""):
    """One consistent line per work option: yield, needs, requirement and readiness."""
    energy=task_energy(action_name,mode);cfg=task_yields.config(action_name,mode)
    yields=task_yields.output_text(action_name,mode) if cfg else "society progress and SC"
    needs=[]
    equipment=task_yields.EQUIPMENT.get((action_name,mode))
    if equipment:
        have=equipment_count(db,p,equipment)
        needs.append(f"{'✅' if have else '🔒'} {resource_name(equipment)} {have}/1 (kept)")
    if mode=="expedite":
        have=material_amount(db,p,"power_cell");needs.append(f"{'✅' if have else '🔒'} Power Cell {have}/1 (used on success)")
    ready=all(n.startswith("✅") for n in needs)
    return f"{'✅' if ready else '🔒'} {action_display_name(action_name,mode)} — {yields} · {need_cost_text(energy,', ')}"+(" · "+" · ".join(needs) if needs else "")

def item_command_menu(command,uid,name):
    """Read supplies without executing a task or starting its cooldown."""
    with SessionLocal() as db:
        _,p=player(db,main.DISCORD_WORLD_ID,"discord",uid,name)
        shared=colony_state(db,p.channel_id)
        lines=["🍽️ FOOD MENU" if command=="eat" else "🎒 ITEM MENU",f"{p.display_name} — /{command}"]
        if command=="eat":
            foods=edible_inventory(db,p);life=life_state(db,p)
            lines += [f"Nutrition: {life.nutrition}/100", "YOUR FOOD (strongest first)"]
            lines += [f"• {row['name']} ×{row['qty']} — {row['effect']}" for row in foods]
            if emergency_food_available(db,p,foods):
                lines.append("• Emergency Meal — available free: restores Nutrition to 40; no item consumed.")
            elif not foods:
                lines.append("No food owned. Harvest Pumpkins with /farm action:Harvest Pumpkins, gather Berries, Corn or Tomato with /gather, or cook with /make category:Food & Drink. Free emergency food becomes available below 20 Nutrition.")
            lines += ["CHOOSE FOOD", "Run /eat again and select Food. The suggestions show owned quantities and exact effects. One selected item is consumed. Prepared meals also grant 10 minutes of Rocky's Favor. Recovery caps at 100."]
        elif command=="use":
            lines.append("CRAFTED LIFE GEAR")
            for key,rows in owned_life_items(db,p).items():
                effect={"meal_kit":"+75 Nutrition, +5 Morale","recreation_set":"+28 Social, +12 Morale","comfort_pack":"+40 Comfort, +8 Energy"}[key]
                quality=", ".join(f"{r.quality} ×{r.qty}" for r in rows) or "none owned"
                lines.append(f"• {QUALITY_RECIPES[key]['name']} ×{sum(r.qty for r in rows)} — {effect} (more at higher quality); {quality}.")
            lines.append("These consumables use one item, starting with the highest quality. Recovery caps at 100.")
        elif command=="delivery":
            lines += [f"• Personal Cargo ×{p.cargo} — requires 1; consumed only on success. Failure keeps it.",
                      f"• Shared Cargo ×{shared.cargo} — optional extra society production, separate from your inventory.",
                      "Prepare personal Cargo with /cargo. When ready, use /delivery action:send."]
        elif command=="meal":
            lines += [f"• Personal Pumpkin ×{p.crops} — sharing consumes 1 Pumpkin.",
                      "Harvest Pumpkins with /farm action:Harvest Pumpkins. Choose /meal action:share to contribute; use /eat for personal food recovery."]
        elif command=="repair":
            lines += [f"• Shared settlement parts ×{shared.components} — society repairs can consume 1 on success to add shared Infrastructure.",
                      f"• Personal Iron Nails ×{p.components} — used for personal gear repairs (5 per 20% condition).",
                      "Society work: /repair target:society. Without shared parts, base work rewards still apply but no extra Infrastructure or housing is produced.",
                      "PERSONAL GEAR"]
            rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
            for row in rows:
                lines.append(f"• {row.quality} {row.item_name} ×{row.qty} — {row.condition}% condition; {gear_repair_cost(row.condition)} Iron Nails to repair.")
            if not rows:lines.append("No quality gear owned. Craft equipment with /make category:equipment.")
            lines.append("Choose /repair target:gear, then Item. Each selection repairs one quality entry; the dropdown shows cost and stock.")
        elif command in WORK_MENU_OPTIONS:
            option,choices=WORK_MENU_OPTIONS[command]
            lines.append("WORK OPTIONS · yield per success · needs per attempt")
            lines += [work_option_line(db,p,action_name,mode) for _,action_name,mode in choices]
            lines.append(f"Choose /{command} {option}:<option> to work. Failures still spend needs but keep materials and equipment.")
            for _,action_name,mode in choices:
                equipment=task_yields.EQUIPMENT.get((action_name,mode))
                if equipment and not equipment_count(db,p,equipment):
                    lines.append(f"Get {resource_name(equipment)}: {material_source(equipment,'discord')}")
            if command=="market":
                lines.append("Selling: /seedindustries action:Sell (or /menu → Bag & Trade → Sell some / Sell all of…). /market action:view shows which two materials are in demand today.")
        elif command=="social":
            owned=owned_life_items(db,p)
            lines += [f"• Recreation Set ×{sum(r.qty for r in owned['recreation_set'])} — /social action:group_games consumes 1, highest quality first.",
                      f"• Personal Cargo ×{p.cargo} — Duo Delivery consumes 1; select a relationship partner.",
                      "Greetings, hangouts and most duo activities need no item. Select Action and a Player for relationship activities. /games restores Social free without an item or partner."]
        lines.append("Browsing only: no task performed, no items spent, no cooldown started.")
        return "\n".join(lines)


@app.get("/api/v1/seed-supplies")
@colony_command
def seed_supplies(channel:str,uid:str,name:str='Citizen',mode:str='catalog',item:str='',page:int=1,owned:bool=False,provider:str='twitch',category:str=''):
    import sys
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);module=main
        typed=item;item=seed_content.find_item(item)
        if mode=='gather' and item and item not in seed_content.ACTIVE:
            found,suggestions=main.qol.fuzzy_item(typed,seed_content.GATHER)
            if found is None:return out('🛑 Unknown natural resource.'+main.qol.did_you_mean(suggestions)+(' Browse /gather.' if provider=='discord' else ' !gatherpage 1 lists them.')+' Nothing spent.')
            item=found
        if mode=='gather' and item:
            result=seed_content.gather(db,p,item,provider)
            if 'GATHERING COMPLETE' in result:result+=main.qol.action_hint(db,p,provider)
        elif mode=='gather':result=seed_content.gather_menu(page,provider)
        elif mode=='catalog':
            if provider!='discord' and item in seed_content.ACTIVE:
                result=seed_content.item_label(item)+' | '+seed_content.source_hint(item,provider)
            else:result=seed_content.catalog(db,p,item,page,owned,category)
        else:result='🛑 Choose catalog or gather. Nothing spent.'
        return platform_response(provider,result,result.replace('\n',' | '))
