"""Routes: settlement, routines, the task queue and mining.
"""
import json
import math
from fastapi import HTTPException
from sqlalchemy import select
from .. import crafting_progression, item_identity, seed_content
from ..commands import transaction as game_transaction
from ..db import SessionLocal
from ..needs import cost_text as need_cost_text, HEAVY_ENERGY, STANDARD_ENERGY
from ..seedlings import describe as routine_description
from ..settlement import (
    pressures as colony_pressures, seedling as colony_seedling, state as colony_state, tick as colony_tick)
from ..models import ExtraItem, Player
from .base import app, out, platform_response, valid_admin_key
from .rules import ACTION_SKILLS, SKILL_LABELS
from .players import lvl, player, skill_xp, society
from .life import life_state
from .world import player_world, world_clock
from .routes_life_social import games, relax, walk
from .action import action
from .discord_embeds import DISCORD_PRIVATE_COMMANDS
from .training_and_items import seed_supplies
from .. import main      # app.main: names from later modules and settings changed at runtime

@app.get("/api/v1/settlement")
@game_transaction
def settlement_status(channel:str):
    """Additional JSON view; existing society/overlay fields are untouched."""
    from ..settlement import CORE, STOCKS
    with SessionLocal() as db:
        s=society(db,channel);shared=colony_state(db,channel);colony_tick(shared,s,main.now());db.commit()
        return {"schema_version":7,"name":s.name,"resources":{k:getattr(s,k) for k in CORE}|{k:getattr(shared,k) for k in STOCKS},"pressures":colony_pressures(shared,s),"population":s.population}

@app.get("/api/v1/routine")
@game_transaction
def routine(channel:str,uid:str,name:str="Citizen",provider:str="twitch",goal:str="",preferred:str="",n:str=""):
    if n:return main.routine_start(channel,uid,name,n,provider)   # !routine <number> starts a saved queue routine
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);st=colony_seedling(db,p)
        if goal:
            if goal not in {"settlement","recovery","occupation"}:raise HTTPException(400,"goal must be settlement, recovery or occupation")
            st.goal=goal
        if preferred:
            if preferred not in {"games","walk","relax"}:raise HTTPException(400,"preferred must be games, walk or relax")
            st.preferred_activity=preferred
        project=main.current_project(db,channel,world_clock(db,channel)["day"])
        result=routine_description(life_state(db,p),p.job,project=project.progress<project.goal,goal=st.goal,preferred=st.preferred_activity)
        from ..competencies import rank
        from ..occupations import OCCUPATIONS
        result["competencies"]={key:{"xp":skill_xp(p,key),"level":lvl(skill_xp(p,key)),"rank":rank(skill_xp(p,key))} for key in SKILL_LABELS}
        result["occupation_profile"]=OCCUPATIONS.get(p.job,{})
        result["exposure"]=player_world(db,p).siro_exposure
        result.update({"occupation":p.job,"goal":st.goal,"occupation_history":json.loads(st.occupation_history),"last_progress":st.last_progress})
        db.commit();return result

@app.post("/api/v1/admin/routine/step")
@game_transaction
def routine_step(channel:str,uid:str,name:str="Citizen",provider:str="twitch",key:str=""):
    """Explicit operator-driven single step; never background offline reward spam."""
    if not valid_admin_key(key):raise HTTPException(403,"Admin key required")
    choice=routine(channel,uid,name,provider)["next_action"]
    if choice in ACTION_SKILLS or choice in {"eat","sleep"}:return action(choice,channel,uid,name,provider=provider)
    return {"games":games,"walk":walk,"relax":relax}[choice](channel,uid,name,provider=provider)


# Configure identities after all route/function definitions, before accepting work.
item_identity.configure(main)
seed_content.production_balance.configure_market()
with SessionLocal() as _identity_db:
    # Only citizens who still hold old item rows (every citizen used to be visited on every start, ~3 queries each).
    _pending=_identity_db.execute(select(ExtraItem.channel_id,ExtraItem.canonical_uid).where(
        ExtraItem.item.in_(item_identity.MIGRATING),ExtraItem.qty!=0).distinct()).all()
    for _channel,_uid in _pending:
        _identity_player=_identity_db.execute(select(Player).where(Player.channel_id==_channel,Player.twitch_uid==_uid)).scalar_one_or_none()
        if _identity_player is not None:item_identity.migrate_player(_identity_db,_identity_player)
    _identity_db.commit()


from .. import task_queue, task_yields

@app.get('/api/v1/queue')
@game_transaction
def queued_tasks(channel:str,uid:str,name:str='Citizen',action:str='view',task:str='',count:str='1',provider:str='twitch'):
    try:count=int(str(count).strip() or '1')
    except ValueError:return out('Count must be a whole number from 1 to 10. No queue was changed.')
    text=task_queue.control(channel,uid,name,provider,action,task,count)
    short=task_queue.short_status(channel,uid,name,provider) if provider!='discord' and text.startswith('TASK QUEUE') else text.replace('\n',' | ')
    note=first_step_note(channel,uid,name,provider,'queue') if action=='start' else ''
    if note:text,short=text+'\n\n'+note,short+' | '+note
    return platform_response(provider,text,short)

def first_step_note(channel,uid,name,provider,key):
    """First-steps credit for commands outside the command wrapper (queue start, Seedling views)."""
    from .. import onboarding
    try:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            if key=='queue' and db.get(task_queue.TaskQueue,(p.channel_id,p.twitch_uid)) is None:return ''
            note=onboarding.mark(db,p,key,provider);db.commit();return note
    except Exception:
        return ''

@app.get('/api/v1/mining')
@game_transaction
def mining(channel:str,uid:str,name:str='Citizen',ore:str='',action:str='view',count:str='1',provider:str='twitch'):
    try:count=int(str(count).strip() or '1')
    except ValueError:return out('Count must be a whole number from 1 to 10. Nothing was spent.')
    module=main;key=seed_content.find_item(ore)
    if action not in {'view','mine'}:return out('Choose View Requirements or Mine. Nothing was spent.')
    if not 1<=count<=10:return out('Count must be from 1 to 10. Nothing was spent.')
    if provider!='discord':
        # Twitch mines once, right away, and understands short names ("!mine hematite"); queues are on Discord.
        if not ore.strip():
            common=[seed_content.item_label(k).replace(' Ore','').lower() for k in sorted(task_queue.ores(),key=seed_content.item_label) if k not in crafting_progression.RARE]
            rare=[seed_content.item_label(k).replace(' Ore','').lower() for k in sorted(crafting_progression.RARE,key=seed_content.item_label) if k in task_queue.ores()]
            return out('⛏️ !mine <ore>: '+', '.join(common)+(' · Rare (needs a Mineral Extractor): '+', '.join(rare) if rare else '')+' · Mining can fail (you get Stone Dust).')
        if action=='mine' and count==1 and main.twitch_lite.ENABLED:
            # Typos are forgiven when they clearly mean one ore ("hemetite" → Hematite Ore).
            found,suggestions=main.qol.fuzzy_item(ore.strip() if ' ore' in ore.lower() or ore.lower().strip()=='coal' else ore.strip()+' ore',set(task_queue.ores()))
            if found is None and len(suggestions)!=1:found,suggestions=main.qol.fuzzy_item(ore.strip(),set(task_queue.ores()))
            if found is None and len(suggestions)==1:found=next((k for k in task_queue.ores() if seed_content.item_label(k)==suggestions[0]),None)
            if found is None:return out('⛏️ No ore called "'+ore.strip()[:30]+'".'+main.qol.did_you_mean(suggestions)+' Type !mine to see them all. Nothing spent.')
            return seed_supplies(channel,uid,name,'gather',seed_content.item_label(found),1,False,provider)
    if not ore:
        lines=['MINING — CHOOSE AN ORE OR COAL','Mining can fail: each failure gives 1 Stone Dust instead of ore. Select Ore (including Coal) to inspect its requirements, then choose Mine. Count queues up to 10 attempts of that ore.']
        for k in sorted(task_queue.ores(),key=seed_content.item_label):
            rule=(f'Needs a Mineral Extractor in your bag (Small: 1 ore a success, Frontiers Expedition: 2); {need_cost_text(HEAVY_ENERGY)} per attempt; 20-second shared cooldown' if k in crafting_progression.RARE else f'No skill unlock or tools required; {need_cost_text(STANDARD_ENERGY)}; 5-second shared gathering cooldown')
            lines.append(seed_content.item_label(k)+': '+rule+'.')
        text='\n'.join(lines)
    elif key not in task_queue.ores():text='Choose an ore from /mine. Other natural resources are listed under /gather. Nothing was spent.'
    elif action=='mine':return queued_tasks(channel,uid,name,'start','mine:'+key,count,provider)
    else:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            rule='Needs a Mineral Extractor in your bag: a Small Mineral Extractor brings up 1 ore a success, a Frontiers Expedition Mineral Extractor 2. Failures give 1 Stone Dust; shared 20-second cooldown.\n' if key in crafting_progression.RARE else 'No skill unlock, materials or tools required; shared 5-second gathering cooldown.\n'
            text=seed_content.item_label(key)+' — MINING REQUIREMENTS\n'+rule+task_queue.requirements(db,p,'mine:'+key,count)+'\nSelect Mine to start. Use /queue to check progress or cancel.'
    return platform_response(provider,text,text.replace('\n',' | '))

task_queue.install(main)
DISCORD_PRIVATE_COMMANDS.add('queue')


@app.get('/api/v1/queue-tasks')
def queue_task_menu(query:str='',page:int=1,provider:str='twitch'):
    entries=sorted(((key,label) for key,label in task_queue.choices().items() if query.casefold() in (key+' '+label).casefold()),key=lambda row:row[1])
    size=8 if provider=='discord' else 2;pages=max(1,math.ceil(len(entries)/size));page=max(1,min(page,pages))
    lines=[f'QUEUE TASKS · Page {page}/{pages}']+[f'{label}: {key}' for key,label in entries[(page-1)*size:page*size]]
    if not entries:lines.append('No matching tasks. Try a resource, recipe or activity name.')
    lines.append('!queueadd <task ID> <1–10>; !queuetaskpage <page>. One task type at a time.')
    text='\n'.join(lines)
    return platform_response(provider,text,text.replace('\n',' | '))
