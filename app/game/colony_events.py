"""Live events (start, progress, finish, fail, automatic events) and work_counts: what everyday work does for New
Eridian.
"""
import math
import random
import secrets
from datetime import timedelta
from sqlalchemy import select
from ..models import ActionLog, EventContribution, EventHistory, Player
from .base import AUTO_EVENT_COOLDOWN_MINUTES, AUTO_EVENT_MINUTES
from .rules import ACTION_SKILLS, EVENTS, SKILL_LABELS
from .players import as_utc, society, story_contribute, world
from .life import important_progress_notes
from .world import (
    active_player_count, directive_note, scaled_auto_event_actions, scaled_event_goal, set_event_aftermath,
    society_tier, unique_activity_chatters, world_clock)
from .. import main      # app.main: names from later modules and settings changed at runtime

def stat_changes_text(changes,sign="+"):
    labels={"food":"Food","materials":"Materials","development":"Development","knowledge":"Knowledge","treasury":"Treasury","reputation":"Reputation"}
    return ", ".join(f"{sign}{v} {labels[k]}" for k,v in changes.items())
def ensure_event_instance(w):
    if not w.event_instance:w.event_instance=secrets.token_hex(8)
    if not w.event_started_at:w.event_started_at=main.now()
    if not w.event_started_by:w.event_started_by="legacy/automatic"
def event_contributors(db,w):
    if not w.event_instance:return []
    rows=db.execute(select(EventContribution).where(EventContribution.channel_id==w.channel_id,EventContribution.event_instance==w.event_instance)).scalars().all()
    return sorted(rows,key=lambda r:(r.primary_successes*2+r.support_successes,r.primary_successes),reverse=True)
def leader_text(rows,limit=3):
    return ", ".join(f"{r.display_name} {r.primary_successes}P/{r.support_successes}S" for r in rows[:limit]) or "No contributors yet"
def record_event_history(db,w,result,outcome,ended_by="system"):
    ensure_event_instance(w);cfg=EVENTS[w.active_event];rows=event_contributors(db,w)
    db.add(EventHistory(channel_id=w.channel_id,event_instance=w.event_instance,event_key=w.active_event,event_name=cfg["name"],result=result,progress=w.event_progress,goal=w.event_goal,participants=len(rows),started_by=w.event_started_by or "automatic",ended_by=ended_by,outcome=outcome[:500],started_at=w.event_started_at,ended_at=main.now()))
def clear_event(w):
    w.active_event=None;w.event_progress=0;w.event_goal=0;w.event_ends=None;w.event_support_successes=0;w.last_event_end=main.now();w.event_instance=None;w.event_started_at=None;w.event_started_by=None;w.event_active_players=1
def finish_event(db,s,w,ended_by="system"):
    ensure_event_instance(w);cfg=EVENTS[w.active_event];tier=society_tier(s);mult=1+.15*tier[2]
    rewards={field:int(math.ceil(value*mult)) for field,value in cfg["reward"].items()}
    for field,value in rewards.items():setattr(s,field,getattr(s,field)+value)
    rows=event_contributors(db,w)
    for row in rows:
        participant=db.execute(select(Player).where(Player.channel_id==w.channel_id,Player.twitch_uid==row.canonical_uid)).scalar_one_or_none()
        if participant:
            units=max(1,row.primary_successes+int(math.ceil(row.support_successes/2)))
            participant.sc+=min(25,units*2);participant.contribution+=min(8,units)
    if rows:
        winner=db.execute(select(Player).where(Player.channel_id==w.channel_id,Player.twitch_uid==rows[0].canonical_uid)).scalar_one_or_none()
        if winner:winner.sc+=5;winner.contribution+=2
    outcome=f"{stat_changes_text(rewards)}; leaders: {leader_text(rows)}"
    record_event_history(db,w,"success",outcome,ended_by);set_event_aftermath(db,w.channel_id,cfg,"success")
    msg=f"✅ {cfg['emoji']} {cfg['name']} COMPLETE! New Eridian {stat_changes_text(rewards)}. {len(rows)} participants rewarded. Leaders: {leader_text(rows)}. Aftermath: +3% related work for 60 minutes."
    from .. import stream_overlay
    stream_overlay.highlight(db,w.channel_id,"event_win",f"{cfg['name']} complete!",f"{len(rows)} citizens rewarded · New Eridian {stat_changes_text(rewards)}",emoji="🎉")
    clear_event(w);db.commit();return msg
def resolve_expired_event(db,s,w,ended_by="timer"):
    if not w.active_event or not w.event_ends or main.now()<as_utc(w.event_ends):return ""
    cfg=EVENTS[w.active_event];pct=(w.event_progress/w.event_goal) if w.event_goal else 0
    if pct>=1:return finish_event(db,s,w,ended_by)
    factor=.5 if pct>=.75 else 1
    applied={}
    for field,value in cfg["penalty"].items():
        deduction=(value+1)//2 if factor==.5 else value
        old=getattr(s,field);actual=min(old,deduction);setattr(s,field,old-actual);applied[field]=actual
    protection="75% partial protection: " if factor==.5 else ""
    msg=f"⌛ {cfg['emoji']} {cfg['name']} FAILED at {w.event_progress}/{w.event_goal}. {protection}{stat_changes_text(applied,'−')}."
    aftermath_result="partial" if factor==.5 else "failed"
    record_event_history(db,w,aftermath_result,stat_changes_text(applied,"−"),ended_by);set_event_aftermath(db,w.channel_id,cfg,aftermath_result)
    msg+=f" Aftermath: {'−1%' if factor==.5 else '−2%'} related work for 60 minutes."
    from .. import stream_overlay
    stream_overlay.highlight(db,w.channel_id,"event_fail",f"{cfg['name']} ended at {w.event_progress}/{w.event_goal}",("Partly protected: " if factor==.5 else "")+stat_changes_text(applied,"−"))
    clear_event(w);db.commit();return msg
def start_event(db,w,event_key,started_by="automatic"):
    cfg=EVENTS[event_key];active=active_player_count(db,w.channel_id);goal=scaled_event_goal(cfg["goal"],active)
    w.heartbeat=main.now();w.active_event=event_key;w.event_progress=0;w.event_goal=goal;w.event_support_successes=0;w.event_ends=main.now()+timedelta(minutes=cfg["minutes"]);w.event_instance=secrets.token_hex(8);w.event_started_at=main.now();w.event_started_by=started_by;w.event_active_players=active;w.activity_since_event=0;w.activity_window_started_at=None;db.commit()
    primary=SKILL_LABELS.get(cfg["primary"],cfg["primary"].title());support=SKILL_LABELS.get(cfg["support"],cfg["support"].title())
    from .. import stream_overlay
    stream_overlay.highlight(db,w.channel_id,"event_start",f"{cfg['name']} has started!",f"{primary} work counts, {support} helps. Goal {goal} in {cfg['minutes']} minutes.",emoji=cfg['emoji']);db.commit()
    return f"🚨 {cfg['emoji']} {cfg['name']} STARTED! {cfg['objective']}. Primary: {primary}; support: {support} (2 successes = +1). Goal {goal}, scaled for {active} active citizens."
def auto_event_status(db,w):
    if not main.AUTO_EVENTS_ENABLED:return "Automatic events are disabled."
    if w.active_event:return "An event is already active."
    unique=unique_activity_chatters(db,w);target=scaled_auto_event_actions(max(1,unique))
    time_need=AUTO_EVENT_MINUTES
    if w.activity_window_started_at:
        time_need=max(0,int(math.ceil(AUTO_EVENT_MINUTES-(main.now()-as_utc(w.activity_window_started_at)).total_seconds()/60)))
    cooldown_need=0
    if w.last_event_end:
        cooldown_need=max(0,int(math.ceil(AUTO_EVENT_COOLDOWN_MINUTES-(main.now()-as_utc(w.last_event_end)).total_seconds()/60)))
    if not w.activity_window_started_at:return f"Automatic event meter: 0/{target} actions; the {AUTO_EVENT_MINUTES}m activity timer starts with the next action."
    return f"Automatic event meter: {w.activity_since_event or 0}/{target} actions from {unique} unique chatter{'s' if unique!=1 else ''}; activity timer {time_need}m; event cooldown {cooldown_need}m."
def maybe_start_auto_event(db,w,add_activity=True,current_uid=None):
    if not main.AUTO_EVENTS_ENABLED or w.active_event:return ""
    if unattended():return ""   # Seedlings and queues never start an event nobody is around for
    if add_activity:
        if not w.activity_window_started_at:w.activity_window_started_at=main.now()
        w.activity_since_event=(w.activity_since_event or 0)+1
    unique=max(1,unique_activity_chatters(db,w,current_uid));target=scaled_auto_event_actions(unique)
    enough_actions=(w.activity_since_event or 0)>=target
    enough_time=bool(w.activity_window_started_at and main.now()-as_utc(w.activity_window_started_at)>=timedelta(minutes=AUTO_EVENT_MINUTES))
    cooldown_over=not w.last_event_end or main.now()-as_utc(w.last_event_end)>=timedelta(minutes=AUTO_EVENT_COOLDOWN_MINUTES)
    if enough_actions and enough_time and cooldown_over:
        return start_event(db,w,random.choice(list(EVENTS)),"automatic activity trigger")
    db.commit();return ""
def cancel_event(db,w,ended_by="moderator"):
    if not w.active_event:return "🚨 No active event to cancel."
    cfg=EVENTS[w.active_event];record_event_history(db,w,"cancelled","No penalty applied",ended_by)
    from .. import stream_overlay
    stream_overlay.highlight(db,w.channel_id,"event_cancel",f"{cfg['name']} was called off","No penalty applied.")
    clear_event(w);db.commit();return f"🛑 {cfg['emoji']} {cfg['name']} cancelled by {ended_by}. No penalty applied."
def event_note(db,s,w,p,a):return skill_event_note(db,s,w,p,ACTION_SKILLS.get(a))
def skill_event_note(db,s,w,p,skill):
    """Count one success of `skill` for the active event. Only citizens whose work matched are listed as helpers."""
    if not w.active_event:return ""
    expired=resolve_expired_event(db,s,w)
    if expired:return " "+expired
    ensure_event_instance(w);cfg=EVENTS[w.active_event]
    if skill not in (cfg["primary"],cfg["support"]):skill=EVENT_SKILL_ALIASES.get(skill,skill)
    if skill not in (cfg["primary"],cfg["support"]):return ""
    contribution=db.execute(select(EventContribution).where(EventContribution.channel_id==w.channel_id,EventContribution.event_instance==w.event_instance,EventContribution.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not contribution:contribution=EventContribution(channel_id=w.channel_id,event_instance=w.event_instance,canonical_uid=p.twitch_uid,display_name=p.display_name,primary_successes=0,support_successes=0);db.add(contribution)
    contribution.display_name=p.display_name
    if skill==cfg["primary"]:contribution.primary_successes+=1;w.event_progress+=1;note=f" Primary response +1 ({w.event_progress}/{w.event_goal})."
    elif skill==cfg["support"]:
        contribution.support_successes+=1
        w.event_support_successes+=1
        if w.event_support_successes>=2:w.event_support_successes=0;w.event_progress+=1;note=f" Support pair +1 ({w.event_progress}/{w.event_goal})."
        else:note=f" Support logged 1/2 ({w.event_progress}/{w.event_goal})."
    else:return ""
    if w.event_progress>=w.event_goal:return " "+finish_event(db,s,w,"completed by "+p.display_name)
    db.commit();return f" {cfg['emoji']} {cfg['name']}:{note}"
# Everyday work builds New Eridian. Each successful gather, mine, Workbench craft or item job (by hand, from a
# queue or by a Seedling) adds +1 Contribution and +1 to the society stat its skill builds, and counts for the
# active event, today's society project and the weekly story (work_counts).
WORK_STAT={"cultivation":"food","cooking":"food","extraction":"materials","environmental":"materials",
           "fabrication":"development","infrastructure":"development","medicine":"knowledge","research":"knowledge",
           "emergency":"reputation","logistics":"treasury","commerce":"treasury"}
# Work that also helps an event outside its own skill: meals stock the food stores; medicine helps contain Siro.
EVENT_SKILL_ALIASES={"cooking":"cultivation","medicine":"research"}
EVENT_WORK={"extraction":"/gather stone, wood or ore, or /mine","cultivation":"/gather wild plants, cook with /make, or farm with /work",
            "environmental":"/gather water, or environmental crafts with /make","infrastructure":"building crafts with /make, or /repair",
            "fabrication":"most /make crafts: parts, tools, furniture","research":"/work task:research, /work task:scan, or medicine with /make",
            "logistics":"/work task:cargo or delivery, or pack Cargo with /use","commerce":"sell with /seedindustries, Production Orders, or Commerce Work"}
def unattended():
    """True while a Seedling or a work queue acts for a citizen who may be away from the keyboard."""
    return bool(("autonomy" in vars(main) and main.autonomy.ACTING.get()) or
                ("task_queue" in vars(main) and main.task_queue.actor_context.get() is not None))
def work_counts(db,p,skill,grow=True):
    """What one successful job did for New Eridian, as a NEW ERIDIAN section ('' when nothing to say).
    grow=False when the job already pays the society its own way (sales, Production Orders, clinic supplies)."""
    s=society(db,p.channel_id);w=world(db,p.channel_id);lines=[]
    if grow:
        p.contribution+=1;stat=WORK_STAT.get(skill)
        if stat:setattr(s,stat,getattr(s,stat)+1)
        lines.append((f"+1 {stat.title()} · " if stat else "")+"+1 Contribution")
    was_active=bool(w.active_event)
    event=skill_event_note(db,s,w,p,skill).strip()
    progress=important_progress_notes(directive_note(db,p,s,skill,world_clock(db,p.channel_id)),
                                      main.project_contribute(db,p,skill,1),story_contribute(db,p,skill)).strip()
    auto="" if was_active or not main.AUTO_EVENTS_ENABLED else maybe_start_auto_event(db,w,current_uid=p.twitch_uid)
    lines+=[x for x in (event,progress,auto) if x]
    db.commit()
    return "NEW ERIDIAN\n"+"\n".join(lines) if lines else ""
def log_action(db,channel,canonical_uid,action_name,response):
    row=ActionLog(channel_id=channel,canonical_uid=canonical_uid,action=action_name,response=response[:1000]);db.add(row);db.commit()
    from ..commands import context
    ctx=context.get()
    if ctx is not None:ctx["log_id"]=row.id
