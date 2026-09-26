"""Signed workshop dispatch and consistent footer regression coverage."""
import asyncio
import json
from types import SimpleNamespace
from nacl.signing import SigningKey
from starlette.background import BackgroundTasks
from test_colony import m, reset
from app import crafting_progression as cp, discord_deferred as deferred, command_catalog


def test_registered_commands_are_accepted():
    registered={c['name'] for c in command_catalog.commands}
    assert registered <= m.DISCORD_PUBLIC_COMMANDS | m.DISCORD_PRIVATE_COMMANDS


def test_signed_workshop_unlock_charges_once(monkeypatch):
    key=SigningKey.generate()
    monkeypatch.setattr(m,'DISCORD_PUBLIC_KEY',key.verify_key.encode().hex())
    monkeypatch.setattr(m,'DISCORD_GAME_CHANNEL_ID','')
    station=next(k for k,v in cp.STATIONS.items() if v['cost'] and v['tier']==1)
    cost=cp.STATIONS[station]['cost']
    with m.SessionLocal() as db:
        _,p=m.player(db,m.DISCORD_WORLD_ID,'discord','456','Player')
        p.sc=10000;db.commit()
    payload={'type':2,'id':'workshop-unlock-test','application_id':'app','token':'fake',
             'channel_id':'678','member':{'user':{'id':'456','username':'Player'}},
             'data':{'name':'workshop','options':[
                 {'name':'action','type':3,'value':'unlock'},
                 {'name':'station','type':3,'value':station}]}}
    body=json.dumps(payload).encode();stamp='123'
    signature=key.sign(stamp.encode()+body).signature.hex()
    async def get_body():return body
    async def get_json():return payload
    request=SimpleNamespace(headers={'X-Signature-Ed25519':signature,'X-Signature-Timestamp':stamp},body=get_body,json=get_json)
    delivered=[]
    monkeypatch.setattr(deferred,'edit_original',lambda *args:delivered.append(args[2]))
    for _ in range(2):
        tasks=BackgroundTasks()
        assert asyncio.run(m.discord_interactions(request,tasks))=={'type':5,'data':{'flags':64}}
        asyncio.run(tasks())
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert p.sc==10000-cost and cp.has_access(m,db,p,station)
    assert len(delivered)==2
    assert 'unlocked' in json.dumps(delivered[0]).lower()
    assert delivered[0]['embeds'][0]['footer']['text']==m.message_layout.FOOTER


def test_footer_on_short_queue_and_paginated_messages():
    for content in ['Workshop unlocked.', 'TASK QUEUE — COMPLETED\nMine Coal\nSucceeded: 1; failed: 0.', 'INVENTORY\n'+'Resource ×1\n'*100]:
        data=m._discord_json_message(content)['data']
        assert data['embeds'][0]['footer']['text']==m.message_layout.FOOTER
        if data.get('components'):
            custom=data['components'][0]['components'][0]['custom_id']
            detail=m.message_layout.open_page(m,{'data':{'custom_id':custom}})
            assert detail['data']['embeds'][0]['footer']['text']==m.message_layout.FOOTER
