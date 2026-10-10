

"""Compatibility response adapter shared by HTTP and internal Discord calls.

Decorators keep original signatures. Existing routes and slash command dispatch
continue to call the same functions; no separate platform simulation exists.
"""
from functools import wraps
from inspect import signature
from contextvars import ContextVar
from fastapi.responses import PlainTextResponse
from .progression import notices
from . import runtime
from .db import SessionLocal
from .models import ActionLog
from .models import Player
from .settlement import pressures as colony_pressures
from .settlement import seedling as colony_seedling
from .settlement import state as colony_state
from sqlalchemy import select
context=ContextVar("colony_command",default=None)

def transaction(fn):
    """Wrap an endpoint without changing its response text or public signature."""
    sig=signature(fn)
    @wraps(fn)
    def wrapped(*args,**kwargs):
        from . import main as m
        bound=sig.bind(*args,**kwargs);bound.apply_defaults()
        queue=getattr(m,'task_queue',None)
        if queue is not None and queue.connection_context.get() is None:
            with queue.atomic(bound.arguments.get('channel')):
                return fn(*args,**kwargs)
        return fn(*args,**kwargs)
    return wrapped


def command(fn):
    from . import task_queue
    from .game.cooldowns_materials import guide_command
    from .game.life import life_state
    from .game.players import resource_name, society
    from .game.rules import ACTION_SKILLS, SKILL_LABELS
    from .game.world import world_clock
    from .progression import announce
    from .seedlings import describe as routine_description
    sig=signature(fn)
    @wraps(fn)
    def wrapped(*args,**kwargs):
        from . import main as m
        bound=sig.bind(*args,**kwargs);bound.apply_defaults();params=bound.arguments
        queue=getattr(m,'task_queue',None)
        if queue is not None and queue.connection_context.get() is None:
            with queue.atomic(params.get('channel')):
                return wrapped(*args,**kwargs)
        token=context.set({"name":fn.__name__,"params":params,"before":None,"uid":None,"practice":[]})
        nt=notices.set([])
        try:
            response=fn(*args,**kwargs)
            if not isinstance(response,PlainTextResponse):return response
            ctx=context.get();extra=[];prefix=list(dict.fromkeys(notices.get()));step_note=''
            if ctx["uid"]:
                with SessionLocal() as db:
                    p=db.execute(select(Player).where(Player.channel_id==params.get("channel"),Player.twitch_uid==ctx["uid"])).scalar_one_or_none()
                    if p:
                        after=snapshot(db,p);before=ctx["before"]
                        if before:
                            for section in ("Needs","Resources","Competency","Settlement"):
                                changed=[f"{SKILL_LABELS.get(k,k) if section=='Competency' else (task_queue.total_label(k) if k.startswith('gear:') else resource_name(k)) if section=='Resources' else k} {v-before[section].get(k,0):+d}" for k in sorted(after[section].keys()|before[section].keys()) for v in [after[section].get(k,0)] if v!=before[section].get(k,0)]
                                if section=="Competency" and ctx["practice"]:
                                    extra.append("Aptitude practice: "+"; ".join(ctx["practice"]))
                                elif changed:extra.append(("Aptitudes" if section=="Competency" else section)+": "+", ".join(changed))
                            # Browsing views and refusals spend nothing; "Needs: unchanged" would only be noise there.
                            if not any(x.startswith("Needs:") for x in extra) and fn.__name__ not in {"profile","skills","life_status","guide","job","make","workshop","seed_supplies","training","seed_industries","use_item","inventory","sell_all_items","clearout"}:
                                extra.insert(0,"Needs: unchanged")
                        if before:
                            for label,new in after["Ranks"].items():
                                old=before["Ranks"].get(label,1)
                                if new>old:
                                    shown=after.get("Labels",{}).get(label,label)    # a name, never an account id
                                    notice=f"LEVEL UP: {shown} Lv. {old} → Lv. {new}"
                                    announce(db,p,notice,runtime.now());prefix.append(notice)
                        try:
                            from . import onboarding
                            step_note=onboarding.after_command(db,p,fn.__name__,params,ctx["before"],after)
                            if step_note and params.get("provider")=="discord":extra.append(step_note)
                            elif fn.__name__=="guide":
                                path=onboarding.status(db,p,params.get("provider") or "twitch")
                                if path:extra.insert(0,path)
                        except Exception:
                            pass    # the first-steps path never gets in the way of a command
                        try:
                            from . import community
                            cnote,tnote=community.after_command(db,p,fn.__name__,params,ctx["before"],after)
                            if cnote and params.get("provider")=="discord":extra.append(cnote)
                            if tnote and params.get("provider")!="discord":step_note=" | ".join(x for x in (step_note,tnote) if x)
                            if fn.__name__=="profile":extra.extend(community.profile_lines(db,p))
                        except Exception:
                            pass    # community features never get in the way of a command
                        st=colony_seedling(db,p)
                        if fn.__name__ in {"profile","skills","life_status","guide"}:
                            if st.last_progress:prefix.append("Latest "+st.last_progress)
                            life=life_state(db,p);project=runtime.current_project(db,p.channel_id,world_clock(db,p.channel_id)["day"]);routine=routine_description(life,p.job,project=project.progress<project.goal,goal=st.goal,preferred=st.preferred_activity)
                            task=routine["next_action"]
                            if task in ACTION_SKILLS and params.get("provider")=="discord":shown=guide_command(task,"discord")
                            else:shown=("/" if params.get("provider")=="discord" else "!")+task
                            extra.append(f"Routine: {routine['mood']} · {shown} · {routine['reason']}")
                        db.commit()
            if fn.__name__ in {"soc","world_status","progress","projectstatus"}:
                with SessionLocal() as db:
                    settlement=society(db,params["channel"]);shared=colony_state(db,params["channel"])
                    extra.append(f"Settlement stocks: Water {shared.water}, Ore {shared.ore}, Components {shared.components}, Medicines {shared.medicines}, Cargo {shared.cargo}, Housing {shared.housing}/{settlement.population}, Mood {shared.mood}")
                    pressure=colony_pressures(shared,settlement)
                    if pressure:extra.append("Pressure: "+", ".join(pressure))
            text=response.body.decode()
            if ctx.get("log_id"):
                with SessionLocal() as db:
                    log=db.get(ActionLog,ctx["log_id"])
                    if log:log.response=(" | ".join(prefix+[text]+extra))[:1000]
                    db.commit()
            if params.get("provider")=="discord":
                return PlainTextResponse("\n".join(prefix)+("\n\n" if prefix else "")+text+("\n\n"+"\n".join(extra) if extra else ""),status_code=response.status_code)
            # One tidy chat line: tasks become a short receipt (see presentation).
            from . import presentation, extras
            from .autonomy import ACTING
            try:
                if not ACTING.get():extras.remember_twitch(fn.__name__,params,ctx.get("uid"))
            except Exception:pass
            name=params.get("action") if fn.__name__=="action" else fn.__name__
            text=presentation.chat("\n".join(prefix+[text]+extra),name)
            if step_note:
                # The first-steps note survives the one-line chat receipt; the receipt gives way if the line gets too long.
                while len(step_note.encode())>120:step_note=step_note[:-2].rstrip()+"…"
                room=200-len((" | "+step_note).encode())
                receipt=text.replace("\n"," ")
                while len(receipt.encode())>room and receipt:receipt=receipt[:-2]+"…"
                text=receipt.rstrip("…")+("…" if len(receipt)<len(text.replace("\n"," ")) else "")+" | "+step_note
            return PlainTextResponse(text,status_code=response.status_code)
        finally:
            context.reset(token);notices.reset(nt)
    return wrapped

def snapshot(db,p):
    from . import task_queue
    from .game.world import society_tier_index
    from .models import LifeState, Society, Home, HobbyProgress, DuckBond, LifeRelationship
    from . import main as m
    from .settlement import state, CORE, STOCKS
    from .competencies import FIELDS
    from .needs import FIELDS as NEEDS
    from sqlalchemy import select
    life=db.execute(select(LifeState).where(LifeState.channel_id==p.channel_id,LifeState.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    s=db.execute(select(Society).where(Society.channel_id==p.channel_id)).scalar_one()
    shared=state(db,p.channel_id)
    ranks={"Society growth":society_tier_index(s)+1}
    home=db.execute(select(Home).where(Home.channel_id==p.channel_id,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    ranks["Habitat"]=home.tier if home else 1
    for row in db.execute(select(HobbyProgress).where(HobbyProgress.channel_id==p.channel_id,HobbyProgress.canonical_uid==p.twitch_uid)).scalars():
        ranks["Hobby "+row.hobby]=sum(row.points>=n for n in (15,50,100))+1
    for row in db.execute(select(DuckBond).where(DuckBond.channel_id==p.channel_id,DuckBond.canonical_uid==p.twitch_uid)).scalars():
        ranks["Fleet bond "+row.duck]=sum(row.xp>=n for n in (5,20,50,100))+1
    for rel in db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id,((LifeRelationship.uid_a==p.twitch_uid)|(LifeRelationship.uid_b==p.twitch_uid)))).scalars():
        partner=rel.uid_b if rel.uid_a==p.twitch_uid else rel.uid_a
        ranks["Relationship "+partner]=sum(rel.familiarity>=n for n in (10,35,90,180,300))+1
    from .readable_names import labels
    return {"Ranks":ranks,"Labels":labels(db,p,ranks),"Needs":{k:getattr(life,k) for k in NEEDS} if life else {},
            "Resources":task_queue.inventory_snapshot(db,p)|{k:getattr(p,k) for k in ("sc","contribution")},
            "Competency":{k:getattr(p,v) for k,v in FIELDS.items()},
            "Settlement":{k:getattr(s,k) for k in CORE}|{k:getattr(shared,k) for k in STOCKS}}

def capture(db,p):
    ctx=context.get()
    if ctx is not None and ctx["before"] is None:
        ctx["uid"]=p.twitch_uid;ctx["before"]=snapshot(db,p)
