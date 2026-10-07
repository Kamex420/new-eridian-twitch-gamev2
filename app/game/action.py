"""The work action route (/api/v1/action/{action}) used by /work, training and chat commands.
"""
import random
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from .. import crafting_progression, practice, seed_content, task_yields
from ..commands import command as colony_command
from ..db import SessionLocal
from ..models import SkillBranch
from ..needs import (
    COMFORT_FIXES_DISCORD, COMFORT_FIXES_TWITCH, duration_text, productivity, SLEEP_COOLDOWN_SECONDS,
    TASK_NEED_MINIMUM)
from ..seed_skills import LEGACY_BRANCH, TASKS as SEED_TASKS
from ..settlement import produce as colony_produce, state as colony_state
from ..models import QualityGear, StatusEffect
from .base import app, out, platform_response
from .rules import ACTION_SKILLS, DELIVERY_DUCKS, EVENTS, JOBS, QUALITY_TIERS, SKILL_LABELS
from .players import (
    bonus_active, business_for, business_xp_needed, clamp100, degrade_gear, duck_bond, duck_rank, gain_business_xp,
    grant_random_bonus, lvl, player, resource_name, skill_xp, society, specialization_for, story_contribute,
    tutorial_advance, world)
from .life import (
    concise_action_modifiers, daily_variety_note, failure_fix_text, important_progress_notes, life_modifier_text,
    life_state, player_preference, spend_life_for_action, task_energy, task_need_gate)
from .world import (
    add_status, directive_note, exposure_tick, gear_familiarity_use, goal_progress, maybe_lore_discovery,
    maybe_world_encounter, near_milestone_note, society_tier, society_tier_index)
from .cooldowns_materials import (
    action_display_name, check_cooldown, craft_record, determination_clear, determination_fail, item,
    material_amount, material_change, material_source, missing_material_sources, progress_daily)
from .colony_events import event_note, log_action, maybe_start_auto_event, resolve_expired_event
from .accounts import achieve, rare_outcome
from .routes_player import equipment_count
from .routes_crafting import craft_missing_materials, life_change_summary, task_readiness_warning
from .. import main      # app.main: names from later modules and settings changed at runtime

def rare_ore_to_prospect(db,p):
    """Prospecting (/work task:rare, !rare) treats every rare ore alike: it continues an ore already being
    prospected, otherwise the rare ore you have least of. /mine picks a specific one."""
    ores=sorted(crafting_progression.RARE,key=seed_content.item_label)
    progress=[k for k in ores if item(db,p.channel_id,p.twitch_uid,'prospect:'+k)>0]
    if progress:return progress[0]
    return min(ores,key=lambda k:(material_amount(db,p,k),seed_content.item_label(k)))

@app.get("/api/v1/action/{action}")
@colony_command
def action(action:str,channel:str,uid:str,name:str="Citizen",msg:str="",provider:str="twitch"):
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name);s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w);event_was_active=bool(w.active_event);skill=ACTION_SKILLS.get(action);owned_business=business_for(db,p)
        if not skill and action not in {"eat","sleep"}:raise HTTPException(404,"Unknown action")
        if skill:
            blocked=task_need_gate(db,p,action,provider)
            if blocked:return PlainTextResponse(blocked) if provider=="discord" else out(blocked)
        if action=='rare':
            result=crafting_progression.rare_gather(main,db,p,rare_ore_to_prospect(db,p),provider)
            return platform_response(provider,result,result.replace('\n',' | '))
        if action in SEED_TASKS:
            cfg=SEED_TASKS[action]
            if lvl(skill_xp(p,skill))<cfg['unlock']:
                return out(f"🔒 {cfg['label']} requires {SKILL_LABELS[skill]} level {cfg['unlock']}. Nothing spent.")
            missing=craft_missing_materials(db,p,cfg['cost'])
            if missing:return out("🔒 Still needed: "+", ".join(missing)+'. Nothing spent.'+missing_material_sources(db,p,cfg['cost'],provider))
        workshop_tag=None
        if action in SEED_TASKS:
            rid=main.MERGED_TRAINING.get(action)
            if rid:
                blocked=crafting_progression.recipe_gate(main,db,p,rid,provider)
                if blocked:return out(blocked)
                r=seed_content.RECIPES[rid];req=r['requirement'].get('Skill','SK_CRAFTING')
                if seed_content.level_for(main,db,p,req)<seed_content.required_level(r):
                    return out(f'🔒 {seed_content.skill_name(req)} Lv.{seed_content.required_level(r)} required. Train lower-level recipes. Nothing spent.')
            workshop_tag=None if rid else crafting_progression.TRAINING_STATIONS.get(SEED_TASKS[action]['branch'])
        elif action in {'craft','machine','work','cargo'}:
            workshop_tag=crafting_progression.SURVIVAL
        if workshop_tag:
            station_block=crafting_progression.station_gate(main,db,p,[workshop_tag],crafting_progression.STATIONS[workshop_tag]['tier'],provider)
            if station_block:return out(station_block)
        selected_food=(msg[5:] if action=="eat" and (msg or "").startswith("food:") else "")
        if selected_food not in {"","meal_kit","emergency"}:selected_food=seed_content.find_item(selected_food)
        foods=main.edible_inventory(db,p) if action=="eat" else []
        if selected_food:
            if selected_food not in {"meal_kit","emergency"}|set(seed_content.EDIBLE):
                return out("⚠️ Unknown food. Open /eat and choose from your food list. Nothing spent.")
            if selected_food=="emergency":
                if not main.emergency_food_available(db,p,foods):return out("⚠️ Emergency food requires Nutrition below 20 and no edible items. Open /eat to see your food. Nothing spent.")
            elif not any(row["key"]==selected_food and row["qty"]>0 for row in foods):
                return out("⚠️ You no longer own that food. Open /eat for your current inventory. Nothing spent.")
        if selected_food in seed_content.EDIBLE and life_state(db,p).nutrition>=100:
            return out("ℹ️ Nutrition is already full. Your food was kept.")
        advanced=(msg or "").startswith("mode:")
        mode=(msg.split(":",1)[1].split("|",1)[0] if advanced else "")
        if mode and (action,mode) not in task_yields.YIELDS:
            return out('Choose a supported option for this task. Nothing was spent.')
        equipment=task_yields.EQUIPMENT.get((action,mode))
        if equipment and equipment_count(db,p,equipment)<=0:
            return out(f"🔒 {action_display_name(action,mode)} requires a {resource_name(equipment)} (kept, not consumed). Get it: {material_source(equipment,provider)} Nothing was spent.")
        if mode=="expedite" and material_amount(db,p,"power_cell")<=0:return out(f"🔒 Expedited Spaceport Operations require 1 Power Cell (consumed on success). Get it: {material_source('power_cell',provider)} Nothing was spent.")
        if action=="craft" and p.ore<=0:return out("⚙️ Hematite Ore: need 1, have 0, missing 1. Use /mine to choose an ore, or buy Hematite Ore from Seed Industries. Nothing was spent.")
        if action=="delivery" and p.cargo<=0:return out(f"🦆 Cargo: need 1, have 0, missing 1. Use {'/cargo' if provider=='discord' else '!cargo'} first.")
        if action=="eat" and not any(row["qty"]>0 for row in foods):
            emergency_life=life_state(db,p)
            if emergency_life.nutrition>=TASK_NEED_MINIMUM:
                message=(f"🍲 {p.display_name}, you have no food, but you are not starving. "
                         f"Emergency meals are reserved for Nutrition below {TASK_NEED_MINIMUM}. "
                         f"Use {'/farm action:Harvest Pumpkins, /gather (Berries, Corn, Tomato…) or /make category:Food & Drink' if provider=='discord' else '!harvest or !gather'} before your next meal.")
                return out(message)
        if action in {"business","businesscontract","businessinvest"} and not owned_business:return out(f"🏢 {p.display_name}, register a business first with {'/business action:Start' if provider=='discord' else '!businessstart'}.")
        if action=="businessinvest" and p.sc<(25+10*owned_business.level):return out(f"🏢 {p.display_name}, this business investment costs {25+10*owned_business.level} SC. You currently have {p.sc} SC.")
        wait=check_cooldown(db,p,action)
        if wait and action=="sleep":
            comfort_fix=COMFORT_FIXES_DISCORD if provider=="discord" else COMFORT_FIXES_TWITCH
            relax="/relax" if provider=="discord" else "!relax"
            return out(f"⏱️ {p.display_name}, you can sleep again in {duration_text(wait)}. Sleep fully restores Energy and Comfort once every {duration_text(SLEEP_COOLDOWN_SECONDS)}. "
                       f"Until then, recover Energy with {relax} and Comfort with {comfort_fix}. Nothing was spent.")
        if wait:return out(f"⏱️ {p.display_name}, {action_display_name(action,mode)} is ready in {duration_text(wait)}.")
        life_bonus,life_notes,life=main.life_modifiers(db,p,skill)
        clock,pw,world_bonus,world_notes=main.world_rule_bundle(db,p,s,action,skill,provider)
        life_bonus+=world_bonus;life_notes.extend(world_notes)
        life_before=(life.energy,life.nutrition,life.social,life.comfort)
        yield_config=task_yields.config(action,mode)
        spend_life_for_action(life,action,task_energy(action,mode))
        db.commit()
        job_bonus=1 if action in JOBS.get(p.job,("",set()))[1] else 0
        tier_bonus=society_tier(s)[2]
        spec_bonus=1 if skill and specialization_for(db,p,skill) else 0
        timed_sc=2 if skill and bonus_active(db,p,"seed_dividend") else 0
        timed_contribution=1 if skill and bonus_active(db,p,"civic_recognition") else 0
        timed_xp=1 if skill and bonus_active(db,p,"accelerated_learning") else 0
        crate_bonus=1 if skill in {"logistics","commerce"} and action!="businessinvest" and item(db,channel,c,"crate")>0 else 0
        # Additive SC bonuses are capped so late-game systems stay rewarding
        # without multiplying routine work into runaway income.
        bonus=min(5,job_bonus+tier_bonus+spec_bonus+timed_sc+crate_bonus);contribution_gain=1+timed_contribution;xp_gain=1+timed_xp
        branch_bonus=0
        if action in SEED_TASKS:
            branch=db.get(SkillBranch,(channel,c,SEED_TASKS[action]['branch']))
            branch_bonus=min(.05,max(0,lvl(branch.xp if branch else 0)-1)*.005)
            if branch_bonus:life_notes.append(f"Branch practice +{branch_bonus*100:g}%")
        relevant=bool(w.active_event and skill in {EVENTS[w.active_event]["primary"],EVENTS[w.active_event]["support"]})
        chance_used=[None];determination_used=[0]
        def fail(txt):
            p.actions+=1;db.commit();auto="" if event_was_active else maybe_start_auto_event(db,w,current_uid=c)
            injury=""
            if skill and random.random()<.04:
                effect=random.choice([("sore_back",15,-3,"A rough shift has left you sore."),("bent_tool",10,-2,"A tool needs a little attention."),("rattled",10,-2,"That failure shook your confidence.")])
                add_status(db,p,*effect);injury=f" 🩹 {effect[0].replace('_',' ').title()} {effect[2]:+d}% for {effect[1]}m."
            exposure=exposure_tick(db,p,pw,action,skill,clock) if skill else ""
            encounter=maybe_world_encounter(db,p,skill,clock,False) if skill else ""
            grit=determination_fail(db,p,skill)
            pref=player_preference(db,p)
            modifier_note=(life_modifier_text(provider,life_notes,chance_used[0]) if pref.result_style=="detailed" else concise_action_modifiers(provider,life_notes,chance_used[0],failed=True))
            improvement=failure_fix_text(skill,life_notes,chance_used[0],provider)
            mining_failure=action in {'mine','scavenge','train_ore_mining'}
            if mining_failure:material_change(db,p,crafting_progression.STONE_DUST,1);db.commit()
            reward_note=" No ore was recovered. +1 Stone Dust (crafting ingredient)." if mining_failure else " No task rewards were earned."
            message=txt+reward_note+grit+injury+exposure+encounter+modifier_note+life_change_summary(life_before,life,provider)+task_readiness_warning(life,provider)+improvement+(" "+auto if auto else "")
            if provider=="discord":message="❌ TASK FAILED\n\nWHY\n"+message.replace(" | ","\n")+"\n\nNEXT\n• Retry after the 5-second work cooldown. Determination improves the next matching attempt."
            log_action(db,channel,c,action,message);return PlainTextResponse(message) if provider=="discord" else out(message)
        def passed(base):
            determination_used[0]=main.determination_bonus(db,p,skill)
            if determination_used[0]:life_notes.append(f"Determination +{int(determination_used[0]*100)}%")
            chance_used[0]=min(.92,max(.10,main.success_chance(db,p,skill,base)+(0.05 if relevant else 0)+life_bonus+branch_bonus+determination_used[0]))
            roll=random.random()
            p._practice_quality=1.2 if roll<chance_used[0]*.25 else 1.0
            return roll<chance_used[0]
        if action in SEED_TASKS:
            cfg=dict(SEED_TASKS[action])
            if action in main.MERGED_TRAINING:
                cfg['output']=seed_content.production_balance.current_outputs(main,db,p,main.MERGED_TRAINING[action])
            if not passed(.72):return fail(f"{cfg['label']} did not succeed. All task materials were kept.")
            for key,qty in cfg['cost'].items():material_change(db,p,key,-qty)
            for key,qty in cfg['output'].items():material_change(db,p,key,qty)
            if action in main.MERGED_TRAINING:   # a training task that runs a catalog recipe crafts it (a Seedling's too)
                craft_record(db,p,main.MERGED_TRAINING[action]);main.extras.goal_crafted(main,db,p,main.MERGED_TRAINING[action])
            shared=colony_state(db,channel);old_infrastructure=shared.infrastructure
            for key,qty in cfg['shared'].items():setattr(shared,key,min(100,getattr(shared,key)+qty) if key=='mood' else getattr(shared,key)+qty)
            housing_gain=shared.infrastructure//5-old_infrastructure//5
            shared.housing+=housing_gain
            for key,qty in cfg['society'].items():setattr(s,key,getattr(s,key)+qty)
            if cfg['branch']=='first_aid':
                db.query(StatusEffect).filter_by(channel_id=channel,canonical_uid=c,effect='sore_back').delete()
                life.comfort=clamp100(life.comfort+5)
            if cfg['skill']=='medicine' and cfg['unlock']==5:pw.siro_exposure=max(0,pw.siro_exposure-5)
            xp_gain=main.gain_skill(p,skill,xp_gain);main.gain_branch(db,p,cfg['branch'],xp_gain)
            p.sc+=2+bonus;p.contribution+=contribution_gain
            changes=[f"-{v} {resource_name(k)}" for k,v in cfg['cost'].items()]+[f"+{v} {resource_name(k)}" for k,v in cfg['output'].items()]
            changes += [f"shared {k.replace('_',' ')} +{v}" for k,v in cfg['shared'].items()]
            changes += [f"society {k.title()} +{v}" for k,v in cfg['society'].items()]
            if housing_gain:changes.append(f"shared housing +{housing_gain}")
            base=f"✅ {p.display_name} completes {cfg['label']}. +{xp_gain} {SKILL_LABELS[skill]} XP and branch XP | +{2+bonus} SC | +{contribution_gain} Contribution | "+"; ".join(changes)
        elif action=="businessinvest":
            investment_cost=25+10*owned_business.level
            p.sc-=investment_cost;xp_gain=main.gain_skill(p,"commerce",xp_gain);p.contribution+=1+timed_contribution;s.treasury+=3;s.development+=1;gain_business_xp(owned_business,3)
            base=f"🏢 {p.display_name} invests in {owned_business.name} (-{investment_cost} SC). +{xp_gain} Commerce XP | +{1+timed_contribution} Contribution | +3 Business XP | New Eridian gains +3 Treasury/+1 Development."
        elif action in {"farm","harvest","forage"}:
            if not passed(.68):return fail(f"🌱 {p.display_name} has a rough farming shift.")
            xp_gain=main.gain_skill(p,"cultivation",xp_gain);p.sc+=2+bonus;p.contribution+=contribution_gain;s.food+=1
            # Personal harvest quantities are defined by task_yields.
            base=f"🌾 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Farming XP | +{2+bonus} SC | +{contribution_gain} Contribution | New Eridian gains +1 Food."
        elif action in {"water","scan"}:
            if not passed(.68):return fail(f"💧 {p.display_name} cannot stabilize the environmental readings.")
            xp_gain=main.gain_skill(p,"environmental",xp_gain);p.sc+=2+bonus;p.contribution+=contribution_gain
            if action=="water":
                hydro=mode=="hydroponics";s.food+=2 if hydro else 1
                # Hydroponic personal output is awarded with the other yields.
                society_gain="+2 Food" if hydro else "+1 Food"
            else:
                s.knowledge+=1;society_gain="+1 Knowledge"
            base=f"💧 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Processing XP | +{2+bonus} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."
        elif action in {"mine","scavenge"}:
            if not passed(.68):return fail(f"⛏️ {p.display_name} comes back empty-handed.")
            sc_gain=2+bonus;xp_gain=main.gain_skill(p,"extraction",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain
            p.ore+=1;s.materials+=1
            base=f"⛏️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Harvesting XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +1 Materials."
        elif action=="research":
            if not passed(.68):return fail(f"🔬 {p.display_name} gets inconclusive results.")
            field=mode=="field_analysis";knowledge_gain=2 if field else 1;sc_gain=(4 if field else 2)+bonus
            xp_gain=main.gain_skill(p,"research",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;s.knowledge+=knowledge_gain;base=f"🔬 {p.display_name} completes {'Field Analysis' if field else 'research'}. +{xp_gain} Research XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{knowledge_gain} Knowledge."+(" Siro Sampler activity bonus included." if field else "")
        elif action in {"craft","machine","work"}:
            if not passed(.66):return fail(f"⚙️ {p.display_name} cannot get fabrication within tolerance.")
            xp_gain=main.gain_skill(p,"fabrication",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain
            if action=="work":
                s.treasury+=1;society_gain="+1 Treasury"
            else:
                s.development+=1;society_gain="+1 Development"
            if action=="craft":p.ore-=1;p.components+=1
            base=f"⚙️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Crafting XP | +{3+bonus} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."
        elif action in {"repair","project","build"}:
            if not passed(.66):return fail(f"🏗️ {p.display_name} cannot bring the infrastructure back within tolerance.")
            xp_gain=main.gain_skill(p,"infrastructure",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain;s.development+=1
            base=f"🏗️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Engineering XP | +{3+bonus} SC | +{contribution_gain} Contribution | New Eridian gains +1 Development."
        elif action in {"cargo","delivery","spaceport"}:
            preferred=player_preference(db,p).assigned_duck
            duck=preferred if preferred in DELIVERY_DUCKS and random.random()<.70 else random.choice(DELIVERY_DUCKS)
            if not passed(.68):return fail(f"🦆 {p.display_name} hits a logistics delay. {duck} circles back with a deeply judgmental quack.")
            xp_gain=main.gain_skill(p,"logistics",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain
            if action=="delivery":
                s.reputation+=1;society_gain="+1 Reputation"
            elif action=="spaceport" and mode=="expedite":
                material_change(db,p,"power_cell",-1);p.sc+=3;s.reputation+=1;s.treasury+=2;society_gain="+2 Treasury/+1 Reputation; -1 Power Cell"
            else:
                s.treasury+=1;society_gain="+1 Treasury"
            if action=="cargo":p.cargo+=1
            elif action=="delivery":p.cargo-=1;society_gain+="; -1 personal Cargo"
            bond=duck_bond(db,p,duck,2 if action=="delivery" else 1)
            fleet_bonus=1 if bond.xp>=50 else 0
            if fleet_bonus:p.sc+=fleet_bonus
            duck_note=random.choice([
                f" {duck} escorts the run.",
                f" {duck} handles the last stretch without incident.",
                f" {duck} arrives exactly when nobody expected.",
                f" {duck} inspects the cargo and apparently approves.",
            ])
            advanced_sc=3 if action=="spaceport" and mode=="expedite" else 0
            base=f"🦆 {p.display_name} completes {action_display_name(action,mode)} with {duck}. +{xp_gain} Logistics XP | +{3+bonus+fleet_bonus+advanced_sc} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."+duck_note+f" Fleet bond: {duck_rank(bond.xp)} ({bond.xp} XP)."
        elif action in {"explore","survey"}:
            if not passed(.64):return fail(f"🧭 {p.display_name} returns with little useful frontier data.")
            survey_bonus=action=="survey";sc_gain=(5 if survey_bonus else 3)+bonus;knowledge_gain=2 if survey_bonus else 1
            xp_gain=main.gain_skill(p,"frontier",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;s.knowledge+=knowledge_gain;base=f"🧭 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Frontier Operations XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{knowledge_gain} Knowledge."+(" Sensor survey bonus included." if survey_bonus else "")
        elif action in {"market","business","businesscontract"}:
            b=owned_business if action in {"business","businesscontract"} else None
            if not passed(.70):return fail(f"🏪 {p.display_name} finds no profitable contract this cycle.")
            if action=="businesscontract":
                sc_gain=5+min(8,b.level)+bonus;gain_business_xp(b,2);s.reputation+=2;business_note=f" {b.name} secured a Level {b.level} contract and gained +2 Business XP ({b.xp}/{business_xp_needed(b.level)})."
            else:
                analysis=action=="market" and mode=="analyze";sc_gain=(6 if analysis else 4)+bonus;s.treasury+=2 if analysis else 1;business_note=" Market Analyzer activity bonus included." if analysis else ""
                if b:gain_business_xp(b,1);business_note=f" {b.name} advances to {b.xp}/{business_xp_needed(b.level)} XP."
            xp_gain=main.gain_skill(p,"commerce",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;base=f"🏪 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Commerce XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{2 if action=='businesscontract' or (action=='market' and mode=='analyze') else 1} {'Reputation' if action=='businesscontract' else 'Treasury'}.{business_note}"
        elif action=="eat":
            food_key=selected_food or next((row["key"] for row in foods if row["qty"]>0),"emergency")
            if food_key in seed_content.EDIBLE:
                before=life.nutrition
                material_change(db,p,food_key,-1)
                life.nutrition=clamp100(life.nutrition+seed_content.nutrition(food_key))
                recovery_note=""
                if before<TASK_NEED_MINIMUM and life.nutrition<TASK_NEED_MINIMUM:
                    life.nutrition=25;recovery_note=" Recovery Protocol raised Nutrition above the work minimum."
                favor=""
                if main.prepared_food(food_key):
                    main.grant_rockys_favor(db,p,10);life.morale=clamp100(life.morale+2)
                    favor=" Prepared meal: +2 Morale and Rocky's Favor (+3 percentage points success) for 10 minutes; time stacks."
                festival=""
                from ..seasonal import FESTIVAL_ITEMS
                treat=FESTIVAL_ITEMS.get(food_key)
                if treat:
                    comfort_before=life.comfort;life.comfort=clamp100(life.comfort+treat['comfort']);life.morale=clamp100(life.morale+treat['morale'])
                    festival=f" Festival treat: Comfort {comfort_before}→{life.comfort}, +{treat['morale']} Morale."
                base=f"🍲 {p.display_name} eats {resource_name(food_key)} (−1). Nutrition {before}→{life.nutrition}."+favor+festival+recovery_note
            elif food_key=="meal_kit":
                kits=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==c,QualityGear.item_key=="meal_kit",QualityGear.qty>0)).scalars().all()
                kit=max(kits,key=lambda row:list(QUALITY_TIERS).index(row.quality))
                nutrition_before=life.nutrition;morale_before=life.morale
                life.nutrition=clamp100(life.nutrition+75+int(QUALITY_TIERS[kit.quality]["special"]*100));life.morale=clamp100(life.morale+5)
                kit.qty-=1
                base=f"🍲 {p.display_name} eats a {kit.quality} Meal Kit (-1 Meal Kit). Nutrition {nutrition_before}→{life.nutrition}; Morale {morale_before}→{life.morale}."
            else:
                restored=max(0,40-life.nutrition);life.nutrition=max(40,life.nutrition);life.morale=clamp100(life.morale+1)
                base=(f"🍲 Seed Industries Recovery Protocol: {p.display_name} receives an emergency community meal. "
                      f"+{restored} Nutrition (now {life.nutrition}/100)/+1 Morale. No food or SC was required. "
                      "Emergency meals are only available below 20 Nutrition when you have no food.")
        elif action=="sleep":
            sleep_gain=100-life.energy;comfort_gain=100-life.comfort
            life.energy=100;life.comfort=100;life.morale=clamp100(life.morale+3)
            pw.siro_exposure=max(0,pw.siro_exposure-8)
            base=(f"🛏️ {p.display_name} clocks out for the cycle. Energy 100/100 (+{sleep_gain}); Comfort 100/100 (+{comfort_gain}); +3 Morale; Siro exposure reduced by up to 8. "
                  f"Next sleep in {duration_text(SLEEP_COOLDOWN_SECONDS)}: Comfort drains as you work, so keep it up with {COMFORT_FIXES_DISCORD if provider=='discord' else COMFORT_FIXES_TWITCH}.")
        else:raise HTTPException(404,"Unknown action")
        if action=="craft":base=base.replace(" completes craft."," completes craft (-1 Hematite Ore).")
        if action=="delivery":base=base.replace(" completes delivery."," completes delivery (-1 Cargo).")
        base+=task_yields.apply(main,db,p,action,mode)
        if crate_bonus:base+=" Trade Crate: +1 SC included."
        settlement_before=society_tier_index(s)
        shared=colony_state(db,channel)
        production_action="private_meal" if action=="eat" and "emergency community meal" not in base else ("healthy_sleep" if action=="sleep" and pw.siro_exposure==0 else action)
        production=colony_produce(shared,s,production_action,productivity(life,pw.siro_exposure))
        if production:base+=" Settlement production: "+production+"."
        if skill:   # work and training tasks sometimes turn up an item from the same line of work (eat and sleep never do)
            found=practice.find(main,db,p,skill,SEED_TASKS[action]['branch'] if action in SEED_TASKS else LEGACY_BRANCH.get(action))
            if found:base+=" | "+found+"."
        if action=="sleep" and "medicines -1" in production:pw.siro_exposure=max(0,pw.siro_exposure-10)
        p.actions+=1;p.successes+=1;db.commit()
        note=progress_daily(db,p,action)
        enote=event_note(db,s,w,p,action)
        anote=achieve(db,p)
        lore=rare_outcome(db,p,s,skill);db.commit();personal_bonus=grant_random_bonus(db,p,.04 if action=="businesscontract" else 0) if skill else ""
        pnote=main.project_contribute(db,p,skill,1) if skill else ""
        gnote=goal_progress(db,p,action,skill,project=bool(pnote))
        storynote=story_contribute(db,p,skill) if skill else ""
        wearnote=degrade_gear(db,p,skill) if skill else ""
        tutorialnote=tutorial_advance(db,p,"action") if skill else ""
        if pnote:tutorialnote+=tutorial_advance(db,p,"society")
        encounter=maybe_world_encounter(db,p,skill,clock,True) if skill else ""
        lore_note=maybe_lore_discovery(db,p,skill,clock) if skill else ""
        exposure=exposure_tick(db,p,pw,action,skill,clock) if skill else ""
        auto="" if event_was_active else maybe_start_auto_event(db,w,current_uid=c)
        preference=player_preference(db,p)
        modifier_note=((life_modifier_text(provider,life_notes,chance_used[0]) if preference.result_style=="detailed" else concise_action_modifiers(provider,life_notes,chance_used[0])) if skill and chance_used[0] is not None else "")
        variety_note=daily_variety_note(db,p,skill,clock) if skill else ""
        directive_progress=directive_note(db,p,s,skill,clock) if skill else ""
        familiarity_note=gear_familiarity_use(db,p,skill) if skill else ""
        milestone_note=near_milestone_note(db,p,skill) if skill else ""
        # Routine action cards contain the outcome and only exceptional progress.
        # Full needs, modifiers, world state, and meters stay in their dedicated hubs.
        exceptional=enote+important_progress_notes(note,pnote,storynote,encounter,exposure,anote,tutorialnote,personal_bonus,wearnote)+variety_note+directive_progress+familiarity_note+milestone_note+lore_note
        determination_note=determination_clear(db,p,skill) if determination_used[0] else ""
        message=base+determination_note+lore+exceptional+modifier_note+task_readiness_warning(life,provider)+(" "+auto if auto else "")
        if provider=="discord":message="✅ TASK COMPLETE\n\nRESULT\n"+message.replace(" | ","\n")
        log_action(db,channel,c,action,message)
        return PlainTextResponse(message) if provider=="discord" else out(message)
