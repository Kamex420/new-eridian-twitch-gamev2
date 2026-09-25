"""Guard the playable supply graph, not just the presence of catalog labels."""
from collections import Counter
import math
import pytest
from test_colony import m, reset, seed
from app import seed_content as s
from app import crafting_progression as cp


def test_every_active_item_has_a_finite_production_plan():
    assert set(s.ACQUISITION) == s.ACTIVE
    for key in s.ACTIVE:
        base,steps=s.acquisition_plan(key)
        inventory=Counter({k:n*s.GATHER[k]['amount'] for k,n in base.items()})
        for rid,batches in steps:
            recipe=s.RECIPES[rid]
            for k,n in recipe['inputs'].items():
                assert inventory[k]>=n*batches, (key,rid,k)
                inventory[k]-=n*batches
            inventory.update({k:n*batches for k,n in recipe['outputs'].items()})
        assert inventory[key]>=1,key


def test_all_recipes_unlock_from_beginner_gathering_and_practice():
    # An available repeatable recipe can train its declared skill to later levels.
    available=set(s.GATHER)
    trainable={'SK_HARVESTING'}|{'SK_'+v['branch'].upper() for v in s.GATHER.values()}
    executable=set()
    while True:
        before=(len(available),len(trainable),len(executable))
        for rid,r in s.RECIPES.items():
            req=r['requirement'].get('Skill','SK_CRAFTING')
            if set(r['inputs'])<=available and (s.required_level(r)==1 or req in trainable):
                executable.add(rid);available.update(r['outputs'])
                for sk in r['xp'].get('TrainedSkills') or [req]:
                    if sk in s.SKILLS and not (sk=='SK_MEDICINE' and req=='SK_PHARMACY'):
                        trainable.add(sk)
        if before==(len(available),len(trainable),len(executable)):break
    assert executable==set(s.RECIPES)
    assert available==s.ACTIVE


def test_legacy_and_training_ingredients_are_obtainable():
    available={'crops','ore','rare_ore','cargo'}  # harvest, mine, rare, cargo
    recipes=[(cost,{m.craft_output_key(k):1}) for k,cost in {**m.PART_RECIPES,**m.RECIPES}.items()]
    recipes += [(r['cost'],{k:1}) for k,r in m.QUALITY_RECIPES.items()]
    recipes += [(r['cost'],r['output']) for r in m.SEED_TASKS.values()]
    available={m.item_identity.canonical(k) for k in available}|set(s.GATHER)
    recipes += [(r['inputs'],r['outputs']) for r in s.RECIPES.values()]
    recipes=[({m.item_identity.canonical(k):n for k,n in cost.items()}, {m.item_identity.canonical(k):n for k,n in output.items()}) for cost,output in recipes]
    while True:
        before=len(available)
        for cost,output in recipes:
            if set(cost)<=available:available.update(output)
        if before==len(available):break
    assert {k for cost,_ in recipes for k in cost} <= available
    assert {k for _,output in recipes for k in output} <= available


@pytest.mark.parametrize('key',sorted(set(s.GATHER)-cp.RARE))
def test_each_raw_material_is_gatherable_by_a_new_citizen(key):
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','new','New Citizen')
        before=m.material_amount(db,p,key)
        result=s.gather(m,db,p,key,'discord')
        assert 'GATHERING COMPLETE' in result,result
        assert m.material_amount(db,p,key)==before+s.GATHER[key]['amount']
        assert s.source_hint(key).startswith('/mine ore:' if s.GATHER[key]['branch']=='ore_mining' else '/gather resource:')


def test_gather_pages_and_search_cover_every_non_ore_resource():
    pages=[s.gather_menu(p) for p in range(1,math.ceil(len(s.GATHER)/8)+1)]
    for key in (k for k in s.GATHER if s.GATHER[k]['branch']!='ore_mining'):
        assert any(s.item_label(key) in page for page in pages)
        found=m._discord_autocomplete_choices(s.choices(m,None,None,gather_only=True),s.item_label(key))
        assert key in {r['value'] for r in found['data']['choices']}
    for page in range(1,math.ceil(len(s.GATHER)/3)+1):
        assert len(s.gather_menu(page,'twitch').replace('\n',' | ').encode())<=380


def test_catalog_and_preview_explain_exact_sources_without_spending():
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','new','Citizen')
        key=s.source_key('GMT_MATERIAL_PROCESSED_WATER')
        text=s.catalog(m,db,p,key)
        assert 'HOW TO OBTAIN' in text and 'ACQUISITION PLAN' in text
        assert 'Murky Water' in text
        rid=s.ACQUISITION[key]
        preview=s.preview(m,db,p,rid)
        assert 'Get it: /gather resource:' in preview
        assert s.stock(m,db,p)=={}
        p.sc=15
        cp.workshop(m,db,p,'unlock','TAG_MACH_PROD_WATER_FILTRATION_SMALL')
        missing=s.craft(m,db,p,rid,'discord')
        assert 'HOW TO GET THEM' in missing and '/gather resource:' in missing


def test_gather_then_craft_clean_water_without_admin_grants(monkeypatch):
    monkeypatch.setattr(m.random,'random',lambda:0)
    for _ in range(5):
        m.action('harvest','test','new','Citizen',provider='discord')
        with m.SessionLocal() as db:
            db.query(m.Cooldown).delete();db.commit()
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','new','Citizen')
        key=s.source_key('GMT_MATERIAL_PROCESSED_WATER')
        assert 'unlocked' in cp.workshop(m,db,p,'unlock','TAG_MACH_PROD_WATER_FILTRATION_SMALL')
        base,steps=s.acquisition_plan(key)
        for raw,times in base.items():
            for _ in range(times):
                db.query(m.Cooldown).delete()
                assert 'GATHERING COMPLETE' in s.gather(m,db,p,raw,'discord')
        for rid,times in steps:
            for _ in range(times):
                db.query(m.Cooldown).delete()
                assert 'CRAFTING COMPLETE' in s.craft(m,db,p,rid,'discord')
        assert m.material_amount(db,p,key)>=1


def test_gather_blocked_needs_and_invalid_input_spend_nothing():
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','new','Citizen')
        life=m.life_state(db,p);life.energy=0;db.commit()
        result=s.gather(m,db,p,next(iter(s.GATHER)),'discord')
        assert 'GATHERING COMPLETE' not in result
        assert s.stock(m,db,p)=={}
        assert 'Choose a natural resource' in s.gather(m,db,p,'invalid','discord')
        assert s.stock(m,db,p)=={}


def test_legacy_raw_browser_and_missing_training_sources():
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','new','Citizen')
        result=m.craft_menu(db,p,'test','discord','raw_materials').body.decode()
        for key in m.RAW_MATERIAL_KEYS:
            assert m.resource_name(key) in result
            assert m.material_source(key) in result
        assert '/gather resource:Murky Water' in m.material_source('water')
        assert m.material_source('water','twitch').startswith('!gather sd_817726320')
        assert '/make recipe:' in m.material_source('cloth')


def test_discord_gather_pages_and_twitch_template_contracts():
    import csv,inspect
    from pathlib import Path
    from app.command_catalog import commands
    command=next(c for c in commands if c['name']=='gather')
    assert {'resource','page'} <= {o['name'] for o in command['options']}
    rows={r['command']:r['response'] for r in csv.DictReader((Path(__file__).resolve().parents[1] / 'integrations/twitch/commands.csv').open(encoding='utf-8-sig'))}
    assert 'mode=gather' in rows['!gather'] and '${1:}' in rows['!gather']
    assert 'page=$(1)' in rows['!gatherpage']
    assert 'mode=catalog' in rows['!catalog']
    assert 'text=' in rows['!training']
    assert {'mode','item','page'} <= set(inspect.signature(m.seed_supplies).parameters)
