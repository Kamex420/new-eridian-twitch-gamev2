"""Routes and helpers for crafting: recipes, /make and equipment crafting.
"""
from fastapi.responses import PlainTextResponse
from .. import (
    crafting_progression, item_identity, practice, seed_content, workbench)
from ..commands import command as colony_command, transaction as game_transaction
from ..db import SessionLocal
from ..needs import (
    blocked_needs, COMFORT_BLOCK, COMFORT_SLOW, cost_text as need_cost_text, productivity, STANDARD_ENERGY)
from ..occupations import matches as occupation_matches
from ..seed_skills import CRAFT_PRACTICE
from ..settlement import produce as colony_produce, state as colony_state
from .base import app, chat_line, out, platform_response
from .rules import (
    CRAFT_PAY, ITEM_EFFECTS, QUALITY_RECIPES, QUALITY_TIERS, RECIPE_TIERS, RECIPES, SKILL_LABELS, SOCIETY_TIERS)
from .players import lvl, player, requirement_text, resource_name, society, story_contribute, tutorial_advance, world
from .life import (
    add_quality_gear, important_progress_notes, life_state, quality_gear_special, quality_roll,
    spend_life_for_action, task_need_gate)
from .world import goal_progress, journal_add, need_fix, society_tier_index
from .cooldowns_materials import (
    craft_output_key, craft_record, determination_clear, material_amount, material_change, missing_material_sources,
    progress_daily, unique_bonus_owned)
from .colony_events import event_note, resolve_expired_event
from .accounts import achieve
from .. import main      # app.main: names from later modules and settings changed at runtime

def normalize_craft_category(value):
    """Workbench category key ('' = overview); unknown values return ''."""
    return workbench.normalize_category(value) or ""

def craft_item_name(key):
    if key in QUALITY_RECIPES:return QUALITY_RECIPES[key]["name"]
    found=workbench.entry(main,key)
    return found.name if found else resource_name(craft_output_key(key))

@app.get("/api/v1/recipes")
@game_transaction
def recipes(channel:str="new-eridian",provider:str="twitch",category:str=""):
    """Public Workbench listing without a citizen: categories or one category's recipes."""
    key=workbench.normalize_category(category)
    if key is None:return out("⚙️ Unknown Workbench category. Categories: "+", ".join(label for _,_,label,_ in workbench.CATEGORIES)+".")
    with SessionLocal() as db:
        ctx=workbench.Context(main,db,None,provider)
        if key:
            rows=workbench.in_category(main,key)
            emoji,label,description=workbench.CATEGORY_INFO[key]
            if provider!="discord":return out(f"{emoji} {label}: "+" · ".join(f"{e.name} T{e.tier}" for e in rows[:12])+" | !make <recipe> crafts.")
            text=f"{emoji} {label}\n{description}\n{len(rows)} recipes, easiest first\n\n"+"\n".join(f"• {e.name} ×{e.quantity} — T{e.tier} · {workbench.station_label(e)} · {e.skill} Lv{e.level}" for e in rows[:40])
            return PlainTextResponse(text+("\n…use /make for every page and your personal status." if len(rows)>40 else ""))
        counts=workbench.category_counts(ctx)
        text="🛠️ Workbench categories (recipes · easiest tier)\n"+"\n".join(f"{emoji} {label} — {counts.get(k,(0,0,1))[0]} · from T{counts.get(k,(0,0,1))[2]}" for k,emoji,label,_ in workbench.CATEGORIES)
        return platform_response(provider,text+"\n\nUse /make for your personal readiness.",text.replace("\n"," | "))

def craft_recipe_key(value):
    """Canonical recipe id for a name, id or retired legacy recipe key."""
    found=workbench.resolve(main,None,None,value)
    return found.id if found else (value or "").lower().strip().replace("-","_").replace(" ","_")

def craft_missing_materials(db,p,costs):
    missing=[]
    for key,amount in costs.items():
        have=material_amount(db,p,key)
        if have<amount:missing.append(f"{resource_name(key)}: need {amount}, have {have}, missing {amount-have}")
    return missing

def craft_reward(db,p,s,kind,recipe=""):
    cfg=CRAFT_PAY[kind];job_bonus=1 if p.job=="technician" or occupation_matches(p.job,CRAFT_PRACTICE.get(recipe,("fabrication",None))[0]) else 0
    xp=2 if quality_gear_special(db,p,"assembly_bench")>0 else 1
    p.sc+=cfg["sc"]+job_bonus;p.contribution+=cfg["contribution"];p.actions+=1;p.successes+=1
    s.development+=cfg["development"];xp=main.gain_skill(p,"fabrication",xp)
    colony_produce(colony_state(db,p.channel_id),s,"make",productivity(life_state(db,p)))
    extra=""
    if recipe in CRAFT_PRACTICE:
        extra_skill,branch=CRAFT_PRACTICE[recipe]
        extra_xp=main.gain_skill(p,extra_skill,1)
        main.gain_branch(db,p,branch,extra_xp)
        extra=f" · +{extra_xp} {SKILL_LABELS[extra_skill]} XP ({branch.replace('_',' ').title()})"
    found=practice.find(main,db,p,"fabrication")
    return {"extra":extra,"sc":cfg["sc"]+job_bonus,"xp":xp,"contribution":cfg["contribution"],"development":cfg["development"],"job_bonus":job_bonus,
            "found":f"\n• {found}" if found else ""}

def craft_system_notes(db,p,s):
    w=world(db,p.channel_id);resolve_expired_event(db,s,w)
    event=event_note(db,s,w,p,"machine")
    project=main.project_contribute(db,p,"fabrication",1)
    story=story_contribute(db,p,"fabrication")
    return event+important_progress_notes(project,story)

def task_readiness_warning(life,provider="discord"):
    blocked=[(label,value,need_fix(field,provider)) for field,label,value,_ in blocked_needs(life)]
    low_comfort=not any(label=="Comfort" for label,_,_ in blocked) and life.comfort<COMFORT_SLOW
    if not blocked and not low_comfort:return ""
    if provider=="discord":
        text=("\n\n⚠️ RECOVERY NEEDED BEFORE MORE WORK\n"+"\n".join(f"• {label} is now {value}/100. Use {fix}." for label,value,fix in blocked)) if blocked else ""
        if low_comfort:text+=("\n\n" if not text else "\n")+f"⚠️ LOW COMFORT\n• Comfort is {life.comfort}/100: −10% success and −1 Morale per task. Work stops below {COMFORT_BLOCK}. Use {need_fix('comfort',provider)}."
        return text
    parts=[f"{label} {value} → {fix}" for label,value,fix in blocked]
    if low_comfort:parts.append(f"Comfort {life.comfort} is low (stops below {COMFORT_BLOCK}) → {need_fix('comfort',provider)}")
    return (" | Next task blocked: " if blocked else " | Warning: ")+", ".join(parts)

def life_change_summary(before,life,provider="discord"):
    fields=[("⚡ Energy",before[0],life.energy),("🍲 Nutrition",before[1],life.nutrition),("🤝 Social",before[2],life.social)]
    if len(before)>3:fields.append(("🏠 Comfort",before[3],life.comfort))
    changed=[f"{label} {old}→{new}" for label,old,new in fields if old!=new]
    if not changed:return ""
    return ("\n\nNEEDS\n• "+" · ".join(changed)) if provider=="discord" else " | Needs: "+", ".join(changed)

WORKBENCH_ACTIONS={"preview","craft","queue","fetch","favorite"}

def make_text_arguments(recipe,category,page):
    """Twitch passes free text: '!make parts 2', '!make Iron Plate' or '!make sr_123'."""
    text=(recipe or "").strip()
    if not text or category:return text,category,page
    if workbench.normalize_category(text) is not None:return "",text,page
    head,_,tail=text.rpartition(" ")
    if tail.isdigit() and head and workbench.normalize_category(head) is not None:return "",head,int(tail)
    return text,category,page

@app.get("/api/v1/make")
@colony_command
def make(channel:str,uid:str,name:str="Citizen",recipe:str="",provider:str="twitch",category:str="",page:int=1,station:str="",action:str="craft",count:int=1):
    module=main
    recipe,category,page=make_text_arguments(recipe,category,page)
    cat=workbench.normalize_category(category)
    if cat is None:
        return out("⚙️ Unknown Workbench category. Choose: "+", ".join(label for _,_,label,_ in workbench.CATEGORIES)+". Nothing spent.")
    action=(action or "craft").strip().lower()
    if action not in WORKBENCH_ACTIONS:return out("⚙️ Choose Preview, Craft, Queue, Fetch missing or Favourite. Nothing spent.")
    station_tag=workbench.find_station(station)
    if station_tag is None:return out("⚙️ Unknown workstation. Pick one from the Workstation list. Nothing spent.")
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name)
        ctx=workbench.Context(module,db,p,provider)
        if not recipe:
            text=workbench.category_text(ctx,cat,page,station_tag) if cat else workbench.home_text(ctx)
            return platform_response(provider,text,chat_line(text))
        found=workbench.resolve(module,db,p,recipe,cat);note="";suggestions=[]
        if found is None:
            gathered=item_identity.RETIRED_GATHERED.get((recipe or "").strip().lower().replace(" ","_"))
            if gathered:return out(f"🌿 {resource_name(recipe)} is now {resource_name(gathered)}, a natural resource. Collect it with {seed_content.source_hint(gathered,provider)} Nothing spent.")
            found,note,suggestions=main.qol.fuzzy_recipe(module,db,p,recipe,cat)
        if found is None:
            return out(f"⚙️ Unknown recipe.{main.qol.did_you_mean(suggestions)} Open {'/make' if provider=='discord' else '!make'} and choose a category, then a recipe. Nothing spent.")
        def noted(text):
            if not note:return text
            return text+"\n\n"+note if provider=="discord" else note+"\n"+text
        if action=="preview":
            text=noted(workbench.preview_text(ctx,found))
            return platform_response(provider,text,chat_line(text))
        if action=="favorite":
            text=noted(main.qol.set_favorite(module,db,p,found.id));db.commit()
            if provider=="discord":text+="\n\n"+workbench.preview_text(workbench.Context(module,db,p,provider),found)
            return platform_response(provider,text,chat_line(text))
        if action=="fetch":
            text,_=main.qol.fetch_plan(ctx,found,max(1,min(10,int(count or 1))))
            return platform_response(provider,noted(text),noted(text))
        if action=="queue":
            return main.queued_tasks(channel,uid,name,"start","make:"+found.id,count,provider)
        life=life_state(db,p);blocked=task_need_gate(db,p,"make",provider,life)
        if blocked:return platform_response(provider,blocked,blocked)
        tier_before=ctx.tier
        if found.kind=="seed":
            result=seed_content.craft(module,db,p,found.id,provider)
            if "CRAFTING COMPLETE" in result:
                hint=main.qol.action_hint(module,db,p,provider,tier_before)
                result=result+hint if provider=="discord" else (hint.strip()+"\n"+result if hint else result)
            result=noted(result)
            return platform_response(provider,result,chat_line(result))
        response=craft_legacy(db,p,channel,found.id,provider,life)
        if provider=="discord":
            body=response.body.decode()
            if "CRAFTING COMPLETE" in body:body+=main.qol.action_hint(module,db,p,provider,tier_before)
            return PlainTextResponse(noted(body))
        return response

def craft_legacy(db,p,channel,recipe,provider,life):
    """New Eridian equipment without a catalog twin; ingredients are catalog items."""
    station_block=crafting_progression.legacy_gate(main,db,p,recipe,provider)
    if station_block:return out(station_block)
    if recipe in QUALITY_RECIPES:
        r=QUALITY_RECIPES[recipe];costs=r["cost"]
        if unique_bonus_owned(db,p,recipe):return out(f"🛑 {p.display_name} already owns {r['name']}. Passive-bonus equipment is limited to one of each item. Nothing spent.")
        missing=craft_missing_materials(db,p,costs)
        if missing:return out(f"⚙️ {p.display_name} cannot craft {r['name']}. Missing requirements: "+"; ".join(missing)+". Nothing spent."+missing_material_sources(db,p,costs,provider))
        for key,amount in costs.items():material_change(db,p,key,-amount)
        quality_bonus=int(quality_gear_special(db,p,"precision_tools")*100)
        quality=quality_roll(lvl(p.fabrication_xp),quality_bonus)
        add_quality_gear(db,p,recipe,quality)
        p._practice_quality={"Standard":1.0,"Fine":1.15,"Excellent":1.3,"Masterwork":1.5}.get(quality,1.1)
        rewards=craft_reward(db,p,society(db,channel),"quality",recipe)
        craft_record(db,p,recipe,quality);main.extras.goal_crafted(main,db,p,recipe)
        spend_life_for_action(life,"make")
        tier=QUALITY_TIERS[quality]
        effects=[]
        for skill,mult in r["skills"].items():effects.append(f"+{int(tier['skill']*mult*100)}% {SKILL_LABELS[skill]}")
        if tier["special"]>0:effects.append(f"+{int(tier['special']*100)}% {r['special']}")
        if quality_bonus:effects.append(f"Precision Tools improved the quality roll by {quality_bonus} points")
        db.commit();system_notes=craft_system_notes(db,p,society(db,channel))
        detail=", ".join(effects) if effects else r["special"]
        journal_add(db,p,f"Crafted {quality} {r['name']}.")
        goal_note=progress_daily(db,p,"make")+goal_progress(db,p,"make","fabrication",crafted=True)+tutorial_advance(db,p,"craft")
        milestone=achieve(db,p);determination_note=determination_clear(db,p,"fabrication")
        updates=important_progress_notes(goal_note,milestone)+system_notes+determination_note
        text=(f"🛠️ CRAFTING COMPLETE — {p.display_name}\n\n"
              f"OUTPUT\n• {quality} {r['name']} · Condition 100%\n• {detail}\n\n"
              f"USED\n{requirement_text(costs)}\n\n"
              f"CHANGE\n• {need_cost_text(STANDARD_ENERGY)}\n"
              f"• +{rewards['xp']} Crafting XP{rewards['extra']} · +{rewards['sc']} SC · +{rewards['contribution']} Contribution"
              +(f" · Matching job bonus included" if rewards['job_bonus'] else "")+rewards['found']+
              f"\n• New Eridian +{rewards['development']} Development"
              +updates+task_readiness_warning(life,provider))
        return PlainTextResponse(text) if provider=="discord" else out(chat_line(text))
    costs=RECIPES[recipe]
    society_state=society(db,channel);tier_index=society_tier_index(society_state);required=RECIPE_TIERS.get(recipe,0)
    if tier_index<required:return out(f"🔒 {resource_name(recipe)} unlocks at society tier {SOCIETY_TIERS[required][0]}. Nothing spent.")
    if unique_bonus_owned(db,p,recipe):return out(f"🛑 {p.display_name} already owns {resource_name(recipe)}. Passive-bonus equipment is limited to one of each item. Nothing spent.")
    missing=craft_missing_materials(db,p,costs)
    if missing:return out("⚙️ Still needed: "+", ".join(missing)+". Nothing spent."+missing_material_sources(db,p,costs,provider))
    for key,amount in costs.items():material_change(db,p,key,-amount)
    material_change(db,p,recipe,1)
    rewards=craft_reward(db,p,society_state,"core",recipe);craft_record(db,p,recipe);main.extras.goal_crafted(main,db,p,recipe)
    spend_life_for_action(life,"make");db.commit();system_notes=craft_system_notes(db,p,society_state)
    goal_note=progress_daily(db,p,"make")+goal_progress(db,p,"make","fabrication",crafted=True)+tutorial_advance(db,p,"craft")
    milestone=achieve(db,p);determination_note=determination_clear(db,p,"fabrication")
    updates=important_progress_notes(goal_note,milestone)+system_notes+determination_note
    text=(f"⚙️ CRAFTING COMPLETE — {p.display_name}\n\n"
          f"OUTPUT\n• {resource_name(recipe)} ×1 · {ITEM_EFFECTS.get(recipe,'Equipment')}\n\n"
          f"USED\n{requirement_text(costs)}\n\n"
          f"CHANGE\n• {need_cost_text(STANDARD_ENERGY)}\n"
          f"• +{rewards['xp']} Crafting XP{rewards['extra']} · +{rewards['sc']} SC"
          +(f" · +{rewards['contribution']} Contribution" if rewards['contribution'] else "")+
          (f" · Matching job bonus included" if rewards['job_bonus'] else "")+rewards['found']+
          f"\n• New Eridian +{rewards['development']} Development"
          +updates+task_readiness_warning(life,provider))
    return PlainTextResponse(text) if provider=="discord" else out(chat_line(text))
