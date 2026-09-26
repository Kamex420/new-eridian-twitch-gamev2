"""Transactional Discord command receipts prevent duplicate interaction rewards.

The receipt and gameplay commit together. A repeated signed interaction returns
its original text. A world transaction lock orders commands against queue work,
including shared society balances. Receipts intentionally do not store tokens.
"""
import hashlib
import json
from sqlalchemy import Column, String, Text, DateTime
from .db import Base


class CommandReceipt(Base):
    __tablename__='discord_command_receipts_v1'
    interaction_id=Column(String(96),primary_key=True)
    fingerprint=Column(String(64),nullable=False)
    result=Column(Text,nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)


def execute(m,payload,command,uid,name,options):
    interaction_id=str(payload.get('id') or '')
    fingerprint=hashlib.sha256(json.dumps([uid,command,options],sort_keys=True).encode()).hexdigest()
    with m.task_queue.atomic(m,m.DISCORD_WORLD_ID):
        with m.SessionLocal() as db:
            previous=db.get(CommandReceipt,interaction_id) if interaction_id else None
            if previous:
                if previous.fingerprint!=fingerprint:
                    return 'This interaction does not match its saved request. Run the command again.'
                return previous.result
            result=m._discord_call_internal(command,uid,name,options,interaction_id)
            if interaction_id:
                db.add(CommandReceipt(interaction_id=interaction_id,fingerprint=fingerprint,
                                      result=result,created_at=m.now()))
                db.commit()
            return result


def private_response(m,command,options):
    return command in m.DISCORD_PRIVATE_COMMANDS or command=='mine' or (
        command=='eat' and not options.get('food')) or (command=='use' and not options.get('item'))
