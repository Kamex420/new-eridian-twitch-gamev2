"""Routes: life status, display style, hi, hangout, relationships, relax, walk, games, hobby, tutorial, story and
titles.
"""
import random
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from ..commands import command as colony_command, transaction as game_transaction
from ..db import SessionLocal
from ..needs import duration_text, RELAX_COMFORT, TASK_NEED_MINIMUM
from ..models import LifeRelationship, Player, PlayerTitle, RelationshipMemory
from .base import app, out
from .rules import HOBBIES, TITLE_DEFS
from .players import clamp100, hobby_row, player, refresh_titles, story_state, tutorial_advance, tutorial_text
from .life import hobby_rank, life_state, player_preference
from .world import (
    collection_add, exposure_tick, find_player_name, goal_progress, life_status_text, maybe_world_encounter,
    player_world, relationship_add, relationship_label, relationship_memory, relationship_pair, world_clock)
from .cooldowns_materials import check_cooldown, item_add
from .colony_events import log_action

@app.get("/api/v1/life")
@colony_command
def life_status(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        note=tutorial_advance(db,p,"life")
        base=life_status_text(db,p,"discord" if provider=="discord" else "twitch")+note
        return PlainTextResponse(base) if provider=="discord" else out(base)

@app.get("/api/v1/display")
@game_transaction
def display_style(channel:str,uid:str,name:str="Citizen",style:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pref=player_preference(db,p);choice=(style or "").strip().lower()
        if choice:
            if choice not in {"compact","detailed"}:return out("🎨 Display style must be compact or detailed.")
            pref.result_style=choice;db.commit()
        explanation=("Compact shows the outcome, rewards, and only actionable/exceptional notes." if pref.result_style=="compact" else
                     "Detailed also shows every active modifier and the final success chance after each work action.")
        if provider=="discord":explanation="Discord action cards always show a compact receipt. Active bonuses are listed under /me section:Bonuses; this preference is retained for plain-text results."
        return out(f"🎨 Result style: {pref.result_style.title()}. {explanation} Colors: 🟢 success/growth · 🟡 actions/rewards · 🔵 information · 🔴 blockers/danger · 🟣 social/story · ⚪ supporting detail.")

@app.get("/api/v1/hi")
@colony_command
def hi(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);target_p,error=find_player_name(db,channel,target)
        if error:return out("👋 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🪞 You greet yourself. Rocky declines to comment.")
        wait=check_cooldown(db,p,"hi")
        if wait:return out(f"⏱️ {p.display_name}, hi is ready in {duration_text(wait)}.")
        me=life_state(db,p);them=life_state(db,target_p)
        before_social=me.social;before_target=them.social
        clock=world_clock(db,channel);extra=1 if clock["phase"]=="Evening" else 0
        me.social=clamp100(me.social+12+extra);me.morale=clamp100(me.morale+1+extra)
        them.social=clamp100(them.social+10);them.morale=clamp100(them.morale+1)
        rel=relationship_add(db,channel,p.twitch_uid,target_p.twitch_uid,3);db.commit()
        memory=relationship_memory(db,channel,p.twitch_uid,target_p.twitch_uid,"Said hi")
        msg=f"👋 {p.display_name} says hi to {target_p.display_name}. +{me.social-before_social} Social; {target_p.display_name} +{them.social-before_target} Social. Morale improved. Relationship: {relationship_label(rel.familiarity)} ({rel.familiarity})."
        if memory.interactions in {5,10,25,50}:msg+=f" 💜 Shared memory milestone: {memory.interactions} activities together."
        msg+=tutorial_advance(db,p,"social")
        log_action(db,channel,p.twitch_uid,"hi",msg)
        return out(msg)

@app.get("/api/v1/hangout")
@colony_command
def hangout(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);target_p,error=find_player_name(db,channel,target)
        if error:return out("🤝 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🪨 Solo Rocky contemplation is /hobby rockwatching, not a hangout.")
        wait=check_cooldown(db,p,"hangout")
        if wait:return out(f"⏱️ {p.display_name}, hangout is ready in {duration_text(wait)}.")
        me=life_state(db,p);them=life_state(db,target_p);social_gain=30;morale_gain=random.randint(3,6)
        clock=world_clock(db,channel)
        if clock["phase"]=="Evening":social_gain+=2;morale_gain+=1
        me.social=clamp100(me.social+social_gain);me.morale=clamp100(me.morale+morale_gain)
        them.social=clamp100(them.social+max(5,social_gain-2));them.morale=clamp100(them.morale+max(2,morale_gain-1))
        rel=relationship_add(db,channel,p.twitch_uid,target_p.twitch_uid,8);db.commit()
        memory=relationship_memory(db,channel,p.twitch_uid,target_p.twitch_uid,"Hung out")
        scene=random.choice(["trade Avesta stories","watch delivery traffic cross New Eridian","debate Rocky's wisdom","compare suspicious crop yields","spend a cycle doing almost nothing productive"])
        msg=f"🤝 {p.display_name} and {target_p.display_name} {scene}. +{social_gain} Social/+{morale_gain} Morale. Relationship: {relationship_label(rel.familiarity)} ({rel.familiarity})."+goal_progress(db,p,"hangout",None,social=True)
        if memory.interactions in {5,10,25,50}:msg+=f" 💜 Shared memory milestone: {memory.interactions} activities together."
        log_action(db,channel,p.twitch_uid,"hangout",msg);return out(msg)

@app.get("/api/v1/relationships")
@game_transaction
def relationships(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel)).scalars().all()
        mine=[r for r in rows if p.twitch_uid in {r.uid_a,r.uid_b}]
        mine=sorted(mine,key=lambda r:r.familiarity,reverse=True)[:10]
        if not mine:
            next_step=("/social action:Say Hi player:<name> or /social action:Hang Out player:<name>" if provider=="discord" else "!hi <name> or !hangout <name>")
            return out(f"🤝 No relationships yet. Use {next_step}.")
        parts=[]
        for r in mine:
            other=r.uid_b if r.uid_a==p.twitch_uid else r.uid_a
            op=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==other)).scalar_one_or_none()
            a,b=relationship_pair(p.twitch_uid,other);memory=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==channel,RelationshipMemory.uid_a==a,RelationshipMemory.uid_b==b)).scalar_one_or_none()
            memory_text=f" · {memory.interactions} shared activities · last: {memory.last_activity}" if memory else ""
            parts.append(f"{op.display_name if op else 'Former Citizen'} — {relationship_label(r.familiarity)} ({r.familiarity}){memory_text}")
        if provider=="discord":return PlainTextResponse("🤝 Relationships\n\n"+"\n".join("• "+x for x in parts))
        return out("🤝 "+" | ".join(parts))

@app.get("/api/v1/relax")
@colony_command
def relax(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"relax")
        if wait:return out(f"⏱️ {p.display_name}, relax is ready in {duration_text(wait)}.")
        life=life_state(db,p);eg=25;mg=random.randint(4,7)
        life.energy=clamp100(life.energy+eg);life.morale=clamp100(life.morale+mg);life.comfort=clamp100(life.comfort+RELAX_COMFORT);db.commit()
        msg=f"🛋️ {p.display_name} takes real downtime. +{eg} Energy, +{mg} Morale, +{RELAX_COMFORT} Comfort (capped at 100)."
        log_action(db,channel,p.twitch_uid,"relax",msg);return out(msg)

@app.get("/api/v1/walk")
@colony_command
def walk(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"walk")
        if wait:return out(f"⏱️ {p.display_name}, walk is ready in {duration_text(wait)}.")
        life=life_state(db,p);clock=world_clock(db,channel);pw=player_world(db,p);life.energy=clamp100(life.energy-2);life.morale=clamp100(life.morale+(7 if clock["phase"]=="Evening" else 5));life.exploration_hobby+=1
        found=random.random()<.35
        if found:item_add(db,channel,p.twitch_uid,"wild_fibers",1)
        db.commit();msg=f"🌿 {p.display_name} walks beyond the habitat blocks. +{7 if clock['phase']=='Evening' else 5} Morale (capped at 100), -2 Energy, +1 Exploration hobby."+(" Found Wild Fibers x1." if found else "")
        msg+=exposure_tick(db,p,pw,"walk","frontier",clock)+maybe_world_encounter(db,p,"frontier",clock,True)+goal_progress(db,p,"walk","frontier")
        log_action(db,channel,p.twitch_uid,"walk",msg);return out(msg)

@app.get("/api/v1/games")
@colony_command
def games(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"games")
        if wait:return out(f"⏱️ {p.display_name}, games is ready in {duration_text(wait)}.")
        life=life_state(db,p);old_social=life.social;rolled_social=25;mg=random.randint(4,8)
        life.social=clamp100(life.social+rolled_social)
        recovery_note=""
        if old_social<TASK_NEED_MINIMUM and life.social<TASK_NEED_MINIMUM:
            life.social=25;recovery_note=" Recovery Protocol raised Social above the work minimum."
        sg=life.social-old_social;life.morale=clamp100(life.morale+mg);life.games_hobby+=1;db.commit()
        scene=random.choice(["wins a tiny card tournament","loses badly and demands a rematch","finds a game nobody remembers installing","claims the rules were different last cycle"])
        msg=f"🎲 {p.display_name} {scene}. +{sg} Social, +{mg} Morale, +1 Games hobby."+recovery_note
        msg+=goal_progress(db,p,"games",None,social=True)
        log_action(db,channel,p.twitch_uid,"games",msg);return out(msg)

@app.get("/api/v1/hobby")
@colony_command
def hobby(channel:str,uid:str,name:str="Citizen",hobby:str="",provider:str="twitch"):
    key=(hobby or "").lower().strip()
    if key not in HOBBIES:return out("🎯 Hobbies: "+", ".join(HOBBIES)+".")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"hobby")
        if wait:return out(f"⏱️ {p.display_name}, hobby is ready in {duration_text(wait)}.")
        life=life_state(db,p);row=hobby_row(db,p,key);row.points+=1;mg=random.randint(4,7);life.morale=clamp100(life.morale+mg)
        found=""
        finds={"gardening":("healthy_cutting",.30),"collecting":("old_label",.18),"scanning":("siro_spore_vial",.10),"mechanics":("damaged_circuit",.18),"rockwatching":("normal_rock",.10),"exploration":("wild_fibers",.20)}
        if key in finds and random.random()<finds[key][1]:
            item,chance=finds[key];name2,first,set_note=collection_add(db,p,item,1);found=f" Found {name2}."+set_note
        elif key=="cooking" and p.crops>0 and random.random()<.25:
            life.nutrition=clamp100(life.nutrition+15);found=" Prepared a surprisingly good snack: +15 Nutrition (capped at 100)."
        elif key=="trading" and random.random()<.20:
            p.sc+=2;found=" Spotted a tiny arbitrage opportunity: +2 SC."
        rank,_=hobby_rank(row.points);db.commit()
        msg=f"🎯 {p.display_name} spends time on {HOBBIES[key][0]}. +{mg} Morale. Hobby progress {row.points} ({rank}).{found}"
        log_action(db,channel,p.twitch_uid,"hobby",msg);return out(msg)



@app.get("/api/v1/tutorial")
@game_transaction
def tutorial(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);return out(tutorial_text(db,p,provider))

@app.get("/api/v1/story")
@game_transaction
def story(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);row,cfg=story_state(db,channel,clock);vals=[row.track_a,row.track_b,row.track_c];total=sum(vals)
        tracks=" | ".join(f"{cfg['tracks'][i][0]} {vals[i]}" for i in range(3));state=("RESOLVED — "+row.outcome) if row.resolved else f"{total}/{cfg['goal']}"
        if provider=="discord":return PlainTextResponse(f"📖 Weekly Avesta Story — {cfg['name']}\n\n{cfg['text']}\n\nProgress: {state}\n"+"\n".join(f"• {cfg['tracks'][i][0]}: {vals[i]}" for i in range(3))+"\n\nSuccessful matching actions automatically shape the outcome.")
        return out(f"📖 {cfg['name']} | {state} | {tracks} | {cfg['text']}")

@app.get("/api/v1/titles")
@game_transaction
def titles(channel:str,uid:str,name:str="Citizen",title:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);refresh_titles(db,p)
        rows=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==channel,PlayerTitle.canonical_uid==p.twitch_uid).order_by(PlayerTitle.unlocked_at)).scalars().all()
        q=(title or "").strip().lower()
        if q:
            match=next((x for x in rows if x.title_key==q or TITLE_DEFS.get(x.title_key,"").lower()==q),None)
            if not match:return out("🏷️ You have not unlocked that title. Use !titles on Twitch or /me section:Titles on Discord.")
            for x in rows:x.equipped=False
            match.equipped=True;db.commit();return out(f"🏷️ Equipped title: {TITLE_DEFS[match.title_key]}.")
        parts=[("⭐ " if x.equipped else "")+TITLE_DEFS.get(x.title_key,x.title_key) for x in rows]
        return out("🏷️ Titles | "+(" | ".join(parts) if parts else "No titles yet."))
