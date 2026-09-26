
"""Fun, seasonal and community systems layered onto the legacy API."""
from datetime import date, timedelta
import calendar, hashlib, random
from sqlalchemy import Column, Integer, String, Boolean, Date, UniqueConstraint, select
from .db import Base, engine, SessionLocal
from .commands import transaction
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

from .seasonal import HOLIDAY_WINDOWS as HOLIDAYS, _holiday_date_for, holidays_active_for


def holiday_date(year, name, month, day):
    return _holiday_date_for(name, year)


def season_today(today=None):
    active = holidays_active_for(today)
    if not active:
        return None
    pick = min(active, key=lambda row: abs(row["days_until_holiday"]))
    return {"name": pick["name"], "holiday": pick["holiday_date"],
            "emoji": pick["emoji"], "start": pick["start"], "end": pick["end"],
            "days_to_holiday": pick["days_until_holiday"]}

def install(app):
    @app.get("/api/v1/fun/daily")
    def daily_fun(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
        from . import main as m
        return m.contracts(channel=channel,uid=uid,name=name,provider=provider)

    @app.get("/api/v1/fun/collection")
    def fun_collection(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
        from . import main as m
        return m.collection(channel=channel,uid=uid,name=name,provider=provider)

    @app.get("/api/v1/fun/vote")
    @transaction
    def fun_vote(channel:str,uid:str,choice:str="greenhouse",provider:str="twitch"):
        from . import main as m
        if choice not in {"greenhouse","market","observatory"}:return "🗳️ Choose: greenhouse, market, observatory."
        day=date.today().toordinal()
        with SessionLocal() as db:
            uid=m.resolve(db,channel,provider,uid)
            row=db.execute(select(Vote).where(Vote.channel_id==channel,Vote.canonical_uid==uid,Vote.day==day)).scalar_one_or_none()
            if not row:
                row=Vote(channel_id=channel,canonical_uid=uid,day=day,choice=choice)
                db.add(row)
            else:
                row.choice=choice
            db.commit()
            counts={x:len(db.execute(select(Vote).where(Vote.channel_id==channel,Vote.day==day,Vote.choice==x)).scalars().all()) for x in ("greenhouse","market","observatory")}
            return f"🗳️ Community poll recorded: {row.choice} (advisory only). Current totals: " + ", ".join(f"{k} {v}" for k,v in counts.items())
    @app.get("/api/v1/fun/moment")
    def fun_moment(channel:str,uid:str=""):
        s=season_today(); prefix=f"{s['emoji']} {s['name']}" if s else "🌍 Avesta"
        moments=["A strange signal appears in the sky.","Rocky has organized a suspicious parade.","A delivery duck challenges the colony to a race.","The market discovers a mysterious bonus crate."]
        return f"{prefix} | 🎲 World moment: {moments[hashlib.sha256(f'{channel}:{date.today()}'.encode()).digest()[0]%len(moments)]}"

install
