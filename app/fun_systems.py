"""Fun, seasonal and community systems layered onto the legacy API."""
from datetime import date, timedelta
import calendar, hashlib, random
from sqlalchemy import Column, Integer, String, Boolean, Date, UniqueConstraint, select
from .db import Base, engine, SessionLocal
from .models import Player, Society

class DailyChallenge(Base):
    __tablename__ = "daily_challenges_v1"
    id=Column(Integer, primary_key=True); channel_id=Column(String(64), index=True, nullable=False)
    canonical_uid=Column(String(96), index=True, nullable=False); day=Column(Date, nullable=False)
    challenge=Column(String(48), nullable=False); target=Column(Integer, nullable=False)
    progress=Column(Integer, nullable=False, default=0); claimed=Column(Boolean, nullable=False, default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","day",name="uq_daily_fun"),)

class CollectionProgress(Base):
    __tablename__="collection_progress_v1"
    id=Column(Integer, primary_key=True); channel_id=Column(String(64), index=True, nullable=False)
    canonical_uid=Column(String(96), index=True, nullable=False); item=Column(String(64), nullable=False)
    qty=Column(Integer, nullable=False, default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","item",name="uq_collection_fun"),)

class Vote(Base):
    __tablename__="colony_votes_v1"
    id=Column(Integer, primary_key=True); channel_id=Column(String(64), index=True, nullable=False)
    canonical_uid=Column(String(96), nullable=False); day=Column(Integer, nullable=False); choice=Column(String(48), nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","day",name="uq_colony_vote"),)

class WorldMoment(Base):
    __tablename__="world_moments_v1"
    id=Column(Integer, primary_key=True); channel_id=Column(String(64), index=True, nullable=False)
    key=Column(String(48), nullable=False); active=Column(Boolean, nullable=False, default=True)
    text=Column(String(240), nullable=False); options=Column(String(240), nullable=False, default="")

Base.metadata.create_all(engine)

HOLIDAYS=(
 ("New Year",1,1,"🎆"),("Valentine's Day",2,14,"💝"),("Memorial Day",5,31,"🇺🇸"),
 ("Father's Day",6,21,"👔"),("Independence Day",7,4,"🇺🇸"),("Labor Day",9,1,"🛠️"),
 ("Halloween",10,31,"🎃"),("Thanksgiving",11,27,"🦃"),("Christmas",12,25,"🎄"),
)

def holiday_date(year, name, month, day):
    if name in {"Memorial Day"}: return date(year,5,31)-timedelta(days=(date(year,5,31).weekday()-0)%7)
    if name=="Father's Day": return date(year,6,1)+timedelta(days=(6-date(year,6,1).weekday())%7+14)
    if name=="Labor Day": return date(year,9,1)+timedelta(days=(0-date(year,9,1).weekday())%7)
    if name=="Thanksgiving": return date(year,11,1)+timedelta(days=(3-date(year,11,1).weekday())%7+21)
    return date(year,month,day)

def season_today(today=None):
    today=today or date.today(); candidates=[]
    for year in (today.year-1,today.year,today.year+1):
        for name,month,day,emoji in HOLIDAYS:
            holiday=holiday_date(year,name,month,day); start=holiday-timedelta(days=30); end=holiday+timedelta(days=7)
            if start<=today<=end: candidates.append((holiday-start, name, holiday, emoji, start, end))
    if not candidates:return None
    _,name,holiday,emoji,start,end=min(candidates,key=lambda x:x[2])
    return {"name":name,"holiday":holiday,"emoji":emoji,"start":start,"end":end,"days_to_holiday":(holiday-today).days}

def install(app):
    @app.get("/api/v1/season")
    def season(channel:str="new-eridian"):
        s=season_today()
        if not s:return {"active":False,"message":"🌱 New Eridian is between festivals."}
        return {"active":True,**{k:v.isoformat() if isinstance(v,date) else v for k,v in s.items()},"message":f"{s['emoji']} {s['name']} season is active!"}
    @app.get("/api/v1/fun/daily")
    def daily_fun(channel:str,uid:str,name:str="Citizen"):
        today=date.today()
        with SessionLocal() as db:
            row=db.execute(select(DailyChallenge).where(DailyChallenge.channel_id==channel,DailyChallenge.canonical_uid==uid,DailyChallenge.day==today)).scalar_one_or_none()
            if not row:
                options=[("work",3),("collect",2),("vote",1),("social",1)]; key,target=options[int(hashlib.sha256(f"{channel}:{uid}:{today}".encode()).hexdigest(),16)%len(options)]
                row=DailyChallenge(channel_id=channel,canonical_uid=uid,day=today,challenge=key,target=target);db.add(row);db.commit()
            state="CLAIMED" if row.claimed else f"{row.progress}/{row.target}"
            return f"📋 {name}'s daily challenge: {row.challenge} {state}. Reward: 🎁 10 SC + a collection find."
    @app.get("/api/v1/fun/collection")
    def fun_collection(channel:str,uid:str,name:str="Citizen"):
        with SessionLocal() as db:
            rows=db.execute(select(CollectionProgress).where(CollectionProgress.channel_id==channel,CollectionProgress.canonical_uid==uid).order_by(CollectionProgress.item)).scalars().all()
            owned={r.item:r.qty for r in rows}; sets=[("Avesta Wonders",{"crystal":3,"spore":2,"relic":1},"🏆 Wonder Seeker")]
            return "🧳 Collection | "+(" · ".join(f"{k} x{v}" for k,v in owned.items()) if owned else "Empty — explore, work, and watch for rare finds")
    @app.get("/api/v1/fun/vote")
    def fun_vote(channel:str,uid:str,choice:str="greenhouse"):
        if choice not in {"greenhouse","market","observatory"}:return "🗳️ Choose: greenhouse, market, observatory."
        day=date.today().toordinal()
        with SessionLocal() as db:
            row=db.execute(select(Vote).where(Vote.channel_id==channel,Vote.canonical_uid==uid,Vote.day==day)).scalar_one_or_none()
            if not row:db.add(Vote(channel_id=channel,canonical_uid=uid,day=day,choice=choice));db.commit()
            counts={x:len(db.execute(select(Vote).where(Vote.channel_id==channel,Vote.day==day,Vote.choice==x)).scalars().all()) for x in ("greenhouse","market","observatory")}
            return f"🗳️ Colony vote recorded: {choice}. Current totals: " + ", ".join(f"{k} {v}" for k,v in counts.items())
    @app.get("/api/v1/fun/moment")
    def fun_moment(channel:str,uid:str=""):
        s=season_today(); prefix=f"{s['emoji']} {s['name']}" if s else "🌍 Avesta"
        moments=["A strange signal appears in the sky.","Rocky has organized a suspicious parade.","A delivery duck challenges the colony to a race.","The market discovers a mysterious bonus crate."]
        return f"{prefix} | 🎲 World moment: {moments[hashlib.sha256(f'{channel}:{date.today()}'.encode()).digest()[0]%len(moments)]}"

install
