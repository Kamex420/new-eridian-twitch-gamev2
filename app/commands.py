
"""Compatibility response adapter shared by HTTP and internal Discord calls.

Decorators keep original signatures. Existing routes and slash command dispatch
continue to call the same functions; no separate platform simulation exists.
"""
from functools import wraps
from inspect import signature
from contextvars import ContextVar
from fastapi.responses import PlainTextResponse
from .progression import notices
context=ContextVar("colony_command",default=None)

def command(fn):
    sig=signature(fn)
    @wraps(fn)
    def wrapped(*args,**kwargs):
        from . import main as m
        bound=sig.bind(*args,**kwargs);bound.apply_defaults();params=bound.arguments
        token=context.set({"name":fn.__name__,"params":params,"before":None,"uid":None,"practice":[]})
        nt=notices.set([])
        try:
            response=fn(*args,**kwargs)
            if not isinstance(response,PlainTextResponse):return response
            ctx=context.get();extra=[];prefix=list(dict.fromkeys(notices.get()))
            if ctx["uid"]:
                with m.SessionLocal() as db:
                    p=db.execute(m.select(m.Player).where(m.Player.channel_id==params.get("channel"),m.Player.twitch_uid==ctx["uid"])).scalar_one_or_none()
                    if p:
                        after=snapshot(db,p);before=ctx["before"]
                        if before:
                            for section in ("Needs","Resources","Competency","Settlement"):
                                changed=[f"{k} {v-before[section].get(k,v):+d}" for k,v in after[section].items() if v!=before[section].get(k,v)]
                                if section=="Competency" and ctx["practice"]:
                                    extra.append("Aptitude practice: "+"; ".join(ctx["practice"]))
                                elif changed:extra.append(("Aptitudes" if section=="Competency" else section)+": "+", ".join(changed))
                            if not any(x.startswith("Needs:") for x in extra) and fn.__name__ not in {"profile","skills","life_status","guide","job"}:
                                extra.insert(0,"Needs: unchanged")
                        if before:
                            for label,new in after["Ranks"].items():
                                old=before["Ranks"].get(label,1)
                                if new>old:
                                    notice=f"LEVEL UP: {label} Lv. {old} → Lv. {new}"
                                    m.announce(db,p,notice,m.now());prefix.append(notice)
                        st=m.colony_seedling(db,p)
                        if fn.__name__ in {"profile","skills","life_status","guide"}:
                            if st.last_progress:prefix.append("Latest "+st.last_progress)
                            life=m.life_state(db,p);project=m.current_project(db,p.channel_id,m.world_clock(db,p.channel_id)["day"]);routine=m.routine_description(life,p.job,project=project.progress<project.goal,goal=st.goal,preferred=st.preferred_activity)
                            task=routine["next_action"]
                            if task in m.ACTION_SKILLS and params.get("provider")=="discord":shown=m.guide_command(task,"discord")
                            else:shown=("/" if params.get("provider")=="discord" else "!")+task
                            extra.append(f"Routine: {routine['mood']} · {shown} · {routine['reason']}")
                        db.commit()
            if fn.__name__ in {"soc","world_status","progress","projectstatus"}:
                with m.SessionLocal() as db:
                    settlement=m.society(db,params["channel"]);shared=m.colony_state(db,params["channel"])
                    extra.append(f"Settlement stocks: Water {shared.water}, Ore {shared.ore}, Components {shared.components}, Medicines {shared.medicines}, Cargo {shared.cargo}, Housing {shared.housing}/{settlement.population}, Mood {shared.mood}")
                    pressure=m.colony_pressures(shared,settlement)
                    if pressure:extra.append("Pressure: "+", ".join(pressure))
            text=response.body.decode()
            if ctx.get("log_id"):
                with m.SessionLocal() as db:
                    log=db.get(m.ActionLog,ctx["log_id"])
                    if log:log.response=(" | ".join(prefix+[text]+extra))[:1000]
                    db.commit()
            if params.get("provider")=="discord":
                return PlainTextResponse("\n".join(prefix)+("\n\n" if prefix else "")+text+("\n\n"+"\n".join(extra) if extra else ""),status_code=response.status_code)
            # StreamElements limits bytes, not Unicode characters.
            text=" | ".join(prefix+[text]+extra)
            encoded=text.encode("utf-8")
            if len(encoded)>380:
                text=encoded[:377].decode("utf-8",errors="ignore")+"…"
            return PlainTextResponse(text,status_code=response.status_code)
        finally:
            context.reset(token);notices.reset(nt)
    return wrapped

def snapshot(db,p):
    from .models import LifeState, Society, Home, HobbyProgress, DuckBond, LifeRelationship
    from . import main as m
    from .settlement import state, CORE, STOCKS
    from .competencies import FIELDS
    from .needs import FIELDS as NEEDS
    from sqlalchemy import select
    life=db.execute(select(LifeState).where(LifeState.channel_id==p.channel_id,LifeState.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    s=db.execute(select(Society).where(Society.channel_id==p.channel_id)).scalar_one()
    shared=state(db,p.channel_id)
    ranks={"Colony growth":m.society_tier_index(s)+1}
    home=db.execute(select(Home).where(Home.channel_id==p.channel_id,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    ranks["Habitat"]=home.tier if home else 1
    for row in db.execute(select(HobbyProgress).where(HobbyProgress.channel_id==p.channel_id,HobbyProgress.canonical_uid==p.twitch_uid)).scalars():
        ranks["Hobby "+row.hobby]=sum(row.points>=n for n in (15,50,100))+1
    for row in db.execute(select(DuckBond).where(DuckBond.channel_id==p.channel_id,DuckBond.canonical_uid==p.twitch_uid)).scalars():
        ranks["Fleet bond "+row.duck]=sum(row.xp>=n for n in (5,20,50,100))+1
    for rel in db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id,((LifeRelationship.uid_a==p.twitch_uid)|(LifeRelationship.uid_b==p.twitch_uid)))).scalars():
        partner=rel.uid_b if rel.uid_a==p.twitch_uid else rel.uid_a
        ranks["Relationship "+partner]=sum(rel.familiarity>=n for n in (10,35,90,180,300))+1
    return {"Ranks":ranks,"Needs":{k:getattr(life,k) for k in NEEDS} if life else {},
            "Resources":{k:getattr(p,k) for k in ("sc","crops","ore","rare_ore","components","cargo","contribution")},
            "Competency":{k:getattr(p,v) for k,v in FIELDS.items()},
            "Settlement":{k:getattr(s,k) for k in CORE}|{k:getattr(shared,k) for k in STOCKS}}

def capture(db,p):
    ctx=context.get()
    if ctx is not None and ctx["before"] is None:
        ctx["uid"]=p.twitch_uid;ctx["before"]=snapshot(db,p)
