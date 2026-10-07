"""Transactional Discord command receipts prevent duplicate interaction rewards.

The receipt and gameplay commit together. A repeated signed interaction returns
its original text. A world transaction lock orders commands against queue work,
including shared society balances. Receipts intentionally do not store tokens.
"""
import hashlib
import json
import os
from sqlalchemy import Column, String, Text, DateTime
from .db import Base
from . import runtime
from .db import SessionLocal


class CommandReceipt(Base):
    __tablename__='discord_command_receipts_v1'
    interaction_id=Column(String(96),primary_key=True)
    fingerprint=Column(String(64),nullable=False)
    result=Column(Text,nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)


def execute(m,payload,command,uid,name,options):
    from . import task_queue
    interaction_id=str(payload.get('id') or '')
    fingerprint=hashlib.sha256(json.dumps([uid,command,options],sort_keys=True).encode()).hexdigest()
    with task_queue.atomic(m,runtime.DISCORD_WORLD_ID):
        with SessionLocal() as db:
            previous=db.get(CommandReceipt,interaction_id) if interaction_id else None
            if previous:
                if previous.fingerprint!=fingerprint:
                    return 'This interaction does not match its saved request. Run the command again.'
                return previous.result
            result=runtime._discord_call_internal(command,uid,name,options,interaction_id)
            if interaction_id:
                db.add(CommandReceipt(interaction_id=interaction_id,fingerprint=fingerprint,
                                      result=result,created_at=runtime.now()))
                db.commit()
            return result


# Replies everyone in the channel sees: only moderator announcements. Every other reply is
# private to the player, so the channel stays quiet (the activity feed sums up what players do,
# and Share posts a card on purpose). DISCORD_PUBLIC_ACTIONS=true makes life and work replies
# public again.
SHARED_REPLIES={'eventstart','eventstop'}
PUBLIC_ACTIONS=os.getenv('DISCORD_PUBLIC_ACTIONS','false').strip().lower() in {'1','true','yes','on'}


def private_response(m,command,options):
    from .game.discord_embeds import DISCORD_PRIVATE_COMMANDS
    if command in SHARED_REPLIES:return False
    if not PUBLIC_ACTIONS:return True
    return command in DISCORD_PRIVATE_COMMANDS or command=='mine' or (
        command=='eat' and not options.get('food')) or (command=='use' and not options.get('item'))
