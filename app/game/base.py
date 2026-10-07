"""Imports, settings from the environment, the FastAPI app, small helpers and the database setup.
"""
from ..models import AccountLink, Identity
from .. import main      # app.main: names from later modules and settings changed at runtime

import sys


import os, random, secrets, string, math, re, hashlib, json, time, urllib.request
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from starlette.concurrency import run_in_threadpool
from .. import discord_deferred, message_layout, discord_execution, ui, layout_v2
from .. import notice as fan_notice
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, UniqueConstraint, select, inspect, func, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./new_eridian.db")
GAME_NAME=os.getenv("GAME_NAME","New Eridian")
GAME_TITLE=os.getenv("GAME_TITLE","New Eridian v2")
ADMIN_KEY=os.getenv("ADMIN_KEY","change-me")

MOD_KEY=os.getenv("MOD_KEY","").strip()

def valid_admin_key(value):
    return bool(main.ADMIN_KEY and main.ADMIN_KEY!='change-me' and secrets.compare_digest(str(value).encode(),main.ADMIN_KEY.encode()))

def valid_mod_key(value):
    """StreamElements moderator commands (events, next day, live, challenges, recap, modlog) carry MOD_KEY, so
    ADMIN_KEY (character merges) never has to be stored in the chat bot. ADMIN_KEY still works for older commands."""
    return bool(main.MOD_KEY and secrets.compare_digest(str(value).encode(),main.MOD_KEY.encode())) or valid_admin_key(value)

# StreamElements user level of the channel's broadcaster (Twitch moderators are 500, super moderators 1000).
TWITCH_OWNER_LEVEL=1500

def twitch_owner_ok(key,level):
    """Moderator tools on Twitch are the channel owner's alone: the StreamElements command must carry MOD_KEY
    and be run by the broadcaster. The level comes from the URL, so MOD_KEY staying secret is what makes it hold."""
    try:level=int(level)
    except (TypeError,ValueError):level=0
    return valid_mod_key(key) and level>=TWITCH_OWNER_LEVEL

OWNER_ONLY_TEXT="⛔ Only the game owner can use moderator tools (owner access required)."

import logging
_SECRET_QUERY=re.compile(r'([?&](?:k|key)=)[^&\s"]*')

class _RedactKeys(logging.Filter):
    """Request logs never show the game key (k=) or the admin/moderator key (key=) from StreamElements URLs."""
    def filter(self,record):
        if isinstance(record.args,tuple) and record.args:
            record.args=tuple(_SECRET_QUERY.sub(r'\1***',a) if isinstance(a,str) else a for a in record.args)
        elif isinstance(record.msg,str):
            record.msg=_SECRET_QUERY.sub(r'\1***',record.msg)
        return True

logging.getLogger("uvicorn.access").addFilter(_RedactKeys())

DISCORD_PUBLIC_KEY=os.getenv("DISCORD_PUBLIC_KEY","")
DISCORD_GAME_CHANNEL_ID=os.getenv("DISCORD_GAME_CHANNEL_ID","")
DISCORD_WORLD_ID=os.getenv("DISCORD_WORLD_ID","new-eridian")
os.environ.setdefault("DISCORD_WORLD_ID_ON_START",DISCORD_WORLD_ID)   # what Railway set; a world merge can change the one in use
AVESTA_DAY_SECONDS=max(3600,int(os.getenv("AVESTA_DAY_SECONDS","21600")))
_OWNER_RAW=os.getenv("DISCORD_OWNER_USER_IDS","")
DISCORD_OWNER_USER_IDS=set(re.findall(r"\d{15,25}",_OWNER_RAW))
def parse_discord_emoji_map(raw):
    """
    DISCORD_EMOJI_MAP supports either:
      delivery=<:ne_delivery:123456789>
    or the easier shorthand:
      delivery=ne_delivery:123456789
    """
    result={}
    for entry in raw.split("|"):
        if "=" not in entry:continue
        key,custom=entry.split("=",1)
        key=key.strip().lower();custom=custom.strip()
        if not key or not custom:continue
        if (custom.startswith("<:") or custom.startswith("<a:")) and custom.endswith(">"):
            result[key]=custom
            continue
        # shorthand: emoji_name:emoji_id
        if re.fullmatch(r"[A-Za-z0-9_]{2,32}:\d{15,25}",custom):
            name,emoji_id=custom.split(":",1)
            result[key]=f"<:{name}:{emoji_id}>"
    return result
DISCORD_EMOJI_MAP=parse_discord_emoji_map(os.getenv("DISCORD_EMOJI_MAP",""))
DISCORD_EMOJI_KEYS=sorted(DISCORD_EMOJI_MAP)
def env_int(name,default,minimum=1):
    try:return max(minimum,int(os.getenv(name,str(default))))
    except (TypeError,ValueError):return default
AUTO_EVENTS_ENABLED=os.getenv("AUTO_EVENTS_ENABLED","true").lower() not in {"0","false","no","off"}
AUTO_EVENT_ACTIONS=env_int("AUTO_EVENT_ACTIONS",12)
AUTO_EVENT_MINUTES=env_int("AUTO_EVENT_MINUTES",10)
AUTO_EVENT_COOLDOWN_MINUTES=env_int("AUTO_EVENT_COOLDOWN_MINUTES",30)
from ..db import engine, SessionLocal, Base
app=FastAPI(title="New Eridian v2 Unified API",version="7.0.0")

def now(): return datetime.now(timezone.utc)
PLACEHOLDER_NAME="Citizen"   # the name a call without one gets; never stored over a real name
def clean(v): return ((v or PLACEHOLDER_NAME).strip()[:30] or PLACEHOLDER_NAME)
def out(s):
    from ..commands import context
    if context.get() is not None:return PlainTextResponse(s)
    from ..presentation import chat_fold, fit
    return PlainTextResponse(fit(chat_fold(s)))
def chat_line(text):
    """One Twitch chat line from a multi-line card: blank lines dropped and
    section headers folded in, e.g. 'OUTPUT' + '• Campfire ×1' -> 'Output: Campfire ×1'."""
    parts=[];header=""
    for line in (l.strip() for l in str(text).splitlines()):
        if not line:continue
        if len(line)<=24 and re.fullmatch(r"[A-Z][A-Z &/]*[A-Z]",line):header=line.title();continue
        parts.append(f"{header}: {line.lstrip('• ')}" if header else line);header=""
    return " | ".join(parts)
def platform_response(provider,discord_text,twitch_text):
    return PlainTextResponse(discord_text) if provider=="discord" else out(twitch_text)

from ..models import *
from ..commands import command as colony_command, capture as colony_capture, transaction as game_transaction
from ..settlement import state as colony_state, seedling as colony_seedling, tick as colony_tick, pressures as colony_pressures, produce as colony_produce
from ..needs import productivity
from ..competencies import practice_gain, level as competency_level
from .. import item_identity
from .. import seed_content
from .. import crafting_progression
from .. import task_yields
from .. import practice
from .. import workbench
from ..seed_skills import LABELS as SEED_LABELS, HUBS as SEED_HUBS, TASKS as SEED_TASKS, TREE as SEED_TREE, NEW_JOBS, NEW_SPECS, LEGACY_BRANCH, CRAFT_PRACTICE
from ..models import SkillBranch
from ..occupations import matches as occupation_matches
from ..seedlings import describe as routine_description
from ..progression import announce
from sqlalchemy.orm import object_session


Base.metadata.create_all(engine)

from ..migrations import migrate_schema
migrate_schema()

def backfill_account_links():
    """Protect accounts linked before v5.2 with the new one-to-one ledger."""
    with SessionLocal() as db:
        rows=db.execute(select(Identity).where(Identity.provider=="discord").order_by(Identity.id)).scalars().all()
        for row in rows:
            if row.canonical_uid.startswith("discord:"):continue
            by_discord=db.execute(select(AccountLink).where(AccountLink.channel_id==row.channel_id,AccountLink.discord_uid==row.provider_uid)).scalar_one_or_none()
            by_twitch=db.execute(select(AccountLink).where(AccountLink.channel_id==row.channel_id,AccountLink.twitch_uid==row.canonical_uid)).scalar_one_or_none()
            if not by_discord and not by_twitch:db.add(AccountLink(channel_id=row.channel_id,twitch_uid=row.canonical_uid,discord_uid=row.provider_uid))
        db.commit()

backfill_account_links()
