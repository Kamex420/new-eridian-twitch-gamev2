"""Verify acknowledgement occurs before command execution, without live sends."""
import asyncio
import pytest
import json
from types import SimpleNamespace
from nacl.signing import SigningKey
from starlette.background import BackgroundTasks
from test_colony import m,reset
from app import discord_deferred as d


@pytest.mark.parametrize('command,private',[('mine',True),('queue',True),('farm',False),('make',True),('eat',True),('sleep',False)])
def test_acknowledges_without_running_database_work(monkeypatch,command,private):
    key=SigningKey.generate();monkeypatch.setattr(m,'DISCORD_PUBLIC_KEY',key.verify_key.encode().hex())
    monkeypatch.setattr(m,'DISCORD_GAME_CHANNEL_ID','')
    payload={'type':2,'id':'123','application_id':'app','token':'fake','channel_id':'678',
             'member':{'user':{'id':'456','username':'Player'}},'data':{'name':command}}
    body=json.dumps(payload).encode();stamp='123';signature=key.sign(stamp.encode()+body).signature.hex()
    async def get_body():return body
    async def get_json():return payload
    request=SimpleNamespace(headers={'X-Signature-Ed25519':signature,'X-Signature-Timestamp':stamp},body=get_body,json=get_json)
    calls=[]
    def execute(*args):calls.append(m.task_queue.queue_notifications.origin_channel.get());return 'MINING — CHOOSE AN ORE'
    monkeypatch.setattr(m,'_discord_call_internal',execute)
    delivered=[];monkeypatch.setattr(d,'edit_original',lambda *args:delivered.append(args))
    tasks=BackgroundTasks()
    result=asyncio.run(m.discord_interactions(request,tasks))
    assert result=={'type':5,'data':{'flags':64} if private else {}}
    assert calls==[] and delivered==[]
    asyncio.run(tasks())
    assert calls==['678'] and len(delivered)==1
    assert m.task_queue.queue_notifications.origin_channel.get()==''


def test_delivery_retry_does_not_repeat_command(monkeypatch):
    calls=[];attempts=[]
    monkeypatch.setattr(m,'_discord_call_internal',lambda *args:calls.append(1) or 'Queue started')
    def patch(*args,**kwargs):
        attempts.append(kwargs);return SimpleNamespace(status_code=500 if len(attempts)==1 else 200)
    monkeypatch.setattr(d.requests,'patch',patch);monkeypatch.setattr(d.time,'sleep',lambda _:None)
    d.finish(m,{'application_id':'app','token':'fake','channel_id':'123'},'queue','456','Player',{})
    assert len(calls)==1 and len(attempts)==2
    assert 'flags' not in attempts[0]['json']


def test_game_error_gets_an_error_reply(monkeypatch):
    def fail(*args):raise RuntimeError('private database details')
    monkeypatch.setattr(m,'_discord_call_internal',fail)
    delivered=[];monkeypatch.setattr(d,'edit_original',lambda *args:delivered.append(args))
    d.finish(m,{'application_id':'app','token':'fake'},'mine','456','Player',{})
    assert len(delivered)==1
    assert 'Check /queue' in delivered[0][2]['content']
    assert 'private database details' not in str(delivered)
