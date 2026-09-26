from collections import Counter
from datetime import timedelta
import math
import pytest
from test_colony import m,reset,client
from app import seed_content as s,crafting_progression as cp


def citizen(db):
    return m.player(db,'test','discord','new','Citizen')[1]


def provision_tier(db,p,tier):
    count=cp.TIERS[tier-1][2]
    if count:db.add(m.CraftLedger(channel_id=p.channel_id,canonical_uid=p.twitch_uid,recipe='component',qty=count,best_quality=''))
    db.commit()


def test_all_recipes_have_real_stations_and_progress_without_circular_gates():
    assert all(cp.tags(k) and set(cp.tags(k))<=cp.STATIONS.keys() for k in s.RECIPES)
    assert all(any(tag in s.machine_tags(k) for k in s.MACHINE_RECIPES) for tag in cp.STATIONS)
    available=set(s.GATHER)  # all become gatherable through common Harvesting practice
    trainable={'SK_HARVESTING'}|{'SK_'+v['branch'].upper() for v in s.GATHER.values()}
    executable=set()
    for tier,_,_ in cp.TIERS:
        while True:
            before=(len(available),len(trainable),len(executable))
            for rid,r in s.RECIPES.items():
                req=r['requirement'].get('Skill','SK_CRAFTING')
                if cp.recipe_tier(rid)<=tier and set(r['inputs'])<=available and (s.required_level(r)==1 or req in trainable):
                    executable.add(rid);available.update(r['outputs'])
                    trainable.update(sk for sk in (r['xp'].get('TrainedSkills') or [req]) if sk in s.SKILLS and not (sk=='SK_MEDICINE' and req=='SK_PHARMACY'))
            if before==(len(available),len(trainable),len(executable)):break
        # Each tier has a repeatable manufacturing route to earn the next tier.
        assert any(s.RECIPES[k]['inputs'] for k in executable)
    assert executable==set(s.RECIPES),[(k,s.RECIPES[k]['name']) for k in set(s.RECIPES)-executable]
    assert available==s.ACTIVE


def test_market_covers_raw_inputs_and_every_branch_starter_with_positive_prices():
    assert set(s.GATHER)<=cp.STARTER_MARKET.keys()
    assert {m.item_identity.canonical(k) for task in m.SEED_TASKS.values() for k in task['cost']}<=m.SEED_INDUSTRIES.keys()
    assert len(cp.RARE)==4
    for skill,rid in cp.BRANCH_STARTERS.items():
        assert set(s.RECIPES[rid]['inputs'])<=cp.STARTER_MARKET.keys(),skill
    for k,v in cp.STARTER_MARKET.items():
        assert v['buy']>0 and v['sell']==0
    for k in cp.RARE:assert cp.STARTER_MARKET[k]['buy']>=4*6
    # Legacy stock is preserved; catalog ore buyback reflects the new economy.
    assert {k:(m.SEED_INDUSTRIES[m.item_identity.canonical(k)]['buy'],m.SEED_INDUSTRIES[m.item_identity.canonical(k)]['sell']) for k in ('crops','ore','rare_ore','components','cargo')}=={'crops':(4,1),'ore':(6,4),'rare_ore':(24,16),'components':(10,4),'cargo':(12,5)}


@pytest.mark.parametrize('tag',sorted(cp.STATIONS))
def test_each_station_unlock_charges_once_and_persists(tag):
    with m.SessionLocal() as db:
        p=citizen(db);provision_tier(db,p,4);p.sc=1000;db.commit()
        before=p.sc;fee=cp.STATIONS[tag]['cost']
        cp.workshop(m,db,p,'unlock',tag)
        assert p.sc==before-fee
        assert cp.has_access(m,db,p,tag)
        cp.workshop(m,db,p,'unlock',tag)
        assert p.sc==before-fee
    with m.SessionLocal() as db:
        p=citizen(db);assert cp.has_access(m,db,p,tag)


def test_station_tier_and_money_gates_preserve_balance():
    with m.SessionLocal() as db:
        p=citizen(db);p.sc=1000;db.commit()
        tag='TAG_MACHINE_CRAFTING_TABLE_V3'
        assert 'Tier 3' in cp.workshop(m,db,p,'unlock',tag)
        assert p.sc==1000 and not cp.has_access(m,db,p,tag)
        p.sc=0
        assert 'Need 15 SC' in cp.workshop(m,db,p,'unlock','TAG_MACHINE_CRAFTING_TABLE_V1')
        assert not cp.has_access(m,db,p,'TAG_MACHINE_CRAFTING_TABLE_V1')


def test_owned_correct_machine_grants_access_but_not_tier_bypass():
    with m.SessionLocal() as db:
        p=citizen(db)
        tag='TAG_MACHINE_CRAFTING_TABLE_V3'
        machine=next(k for k in s.MACHINE_RECIPES if tag in s.machine_tags(k))
        m.material_change(db,p,machine,1);db.commit()
        assert cp.has_access(m,db,p,tag)
        assert 'Tier 3' in cp.station_gate(m,db,p,[tag],3)
        provision_tier(db,p,3)
        assert not cp.station_gate(m,db,p,[tag],3)
        assert not cp.has_access(m,db,p,'TAG_MACHINE_PLAXIN_SYNTHESIZER')
        pump=s.source_key('GMT_MACHINE_WATER_PUMP') if 'GMT_MACHINE_WATER_PUMP' in s.SOURCE_KEYS else next(k for k in s.MACHINE_RECIPES if s.ITEMS[k]['name']=='Water Pump')
        assert 'TAG_MACHINE_EXTRACTOR' not in s.machine_tags(pump)


def test_seed_recipe_needs_station_before_consuming_materials():
    with m.SessionLocal() as db:
        p=citizen(db);key=s.source_key('GMT_MATERIAL_PROCESSED_WATER');rid=s.ACQUISITION[key]
        for k,n in s.RECIPES[rid]['inputs'].items():m.material_change(db,p,k,n)
        db.commit();before=s.stock(m,db,p).copy()
        assert 'Required workstation' in s.craft(m,db,p,rid,'discord')
        assert s.stock(m,db,p)==before and db.query(m.Cooldown).count()==0
        p.sc=15;cp.workshop(m,db,p,'unlock',cp.tags(rid)[0]);db.commit()
        assert 'CRAFTING COMPLETE' in s.craft(m,db,p,rid,'discord')
        assert m.material_amount(db,p,key)>0


def test_free_survival_bench_bootstraps_without_any_station_purchase():
    with m.SessionLocal() as db:
        p=citizen(db)
        key=next(k for k in s.MACHINE_RECIPES if s.ITEMS[k]['name']=='Basic Workbench')
        rid=next(k for k,r in s.RECIPES.items() if key in r['outputs'])
        assert cp.tags(rid)==[cp.SURVIVAL]
        for k,n in s.RECIPES[rid]['inputs'].items():
            for _ in range(n):
                db.query(m.Cooldown).delete();s.gather(m,db,p,k,'discord')
        db.query(m.Cooldown).delete()
        assert 'CRAFTING COMPLETE' in s.craft(m,db,p,rid,'discord')
        assert cp.has_access(m,db,p,'TAG_MACHINE_CRAFTING_TABLE_V1')


@pytest.mark.parametrize('key',sorted(cp.RARE))
def test_rare_ores_require_level_and_three_persistent_efforts(key):
    with m.SessionLocal() as db:
        p=citizen(db)
        assert 'Harvesting Lv.3' in s.gather(m,db,p,key,'discord')
        assert db.query(m.Cooldown).count()==0
        p.mining_xp=12;life=m.life_state(db,p);before=life.energy;db.commit()
        for i in range(1,4):
            if i>1:
                db.query(m.Cooldown).delete();db.commit() # simulate cooldown elapsed
            result=s.gather(m,db,p,key,'discord')
            assert f'{i}/3' in result
            assert m.material_amount(db,p,key)==int(i==3)
            assert m.material_amount(db,p,'prospect:'+key)==(i if i<3 else 0)
            assert 'ready in' in s.gather(m,db,p,key,'discord')
        assert life.energy==before-9
        assert cp.manufactured_batches(m,db,p)==0
    with m.SessionLocal() as db:
        p=citizen(db);assert m.material_amount(db,p,key)==1


def test_rare_cooldown_shared_across_ores_and_extractor_route():
    with m.SessionLocal() as db:
        p=citizen(db);p.mining_xp=12;p.sc=1000;provision_tier(db,p,4)
        cp.workshop(m,db,p,'unlock','TAG_MACHINE_EXTRACTOR')
        first,second=sorted(cp.RARE)[:2]
        assert 'PROSPECTING' in s.gather(m,db,p,first,'discord')
        rid=next(k for k,r in s.RECIPES.items() if second in r['outputs'])
        assert 'ready in' in s.craft(m,db,p,rid,'discord')
        assert m.material_amount(db,p,second)==0


def test_rare_market_requires_level_and_buyback_pays_exactly():
    key=next(k for k in cp.RARE if s.ITEMS[k]['name']=='Rutile Ore')
    with m.SessionLocal() as db:
        p=citizen(db);p.sc=1000;db.commit()
    assert 'Harvesting Lv.3' in m.seed_industries('test','new',action='buy',item_name=key,provider='discord').body.decode()
    with m.SessionLocal() as db:
        p=citizen(db);assert p.sc==1000;p.mining_xp=12;db.commit()
    price=m.SEED_INDUSTRIES[key]['buy']
    result=m.seed_industries('test','new',action='buy',item_name=key,amount=2,provider='discord').body.decode()
    assert f'{price*2} SC' in result
    with m.SessionLocal() as db:
        p=citizen(db);assert p.sc==1000-price*2 and m.material_amount(db,p,key)==2
    assert 'sold 1 Rutile Ore' in m.seed_industries('test','new',action='sell',item_name=key,provider='discord').body.decode()
    with m.SessionLocal() as db:
        p=citizen(db);assert p.sc==1000-price*2+m.SEED_INDUSTRIES[key]['sell'] and m.material_amount(db,p,key)==1


def test_market_pages_cover_all_stock_without_mutation():
    texts=[m.seed_industries('test','new',page=i,provider='discord').body.decode() for i in range(1,math.ceil(len(m.SEED_INDUSTRIES)/8)+1)]
    for k in m.SEED_INDUSTRIES:assert any(m.market_item_label(k)+':' in text for text in texts)
    with m.SessionLocal() as db:assert db.query(m.ExtraItem).count()==0


def test_tier_boundaries_and_gathering_cannot_count_as_manufacturing():
    with m.SessionLocal() as db:
        p=citizen(db)
        row=m.CraftLedger(channel_id='test',canonical_uid=p.twitch_uid,recipe='component',qty=0,best_quality='');db.add(row)
        for count,tier in [(0,1),(24,1),(25,2),(99,2),(100,3),(249,3),(250,4)]:
            row.qty=count;db.commit();assert cp.personal_tier(m,db,p)==tier
        extraction=next(k for k,r in s.RECIPES.items() if not r['inputs'])
        db.add(m.CraftLedger(channel_id='test',canonical_uid=p.twitch_uid,recipe=extraction,qty=10000,best_quality=''));row.qty=0;db.commit()
        assert cp.personal_tier(m,db,p)==1


def test_starter_routes_show_each_branch_ingredients_and_exact_total():
    pages=[cp.starter_routes(i) for i in range(1,math.ceil(len(cp.BRANCH_STARTERS)/3)+1)]
    for skill,rid in cp.BRANCH_STARTERS.items():
        r=s.RECIPES[rid];total=sum(cp.STARTER_MARKET[k]['buy']*n for k,n in r['inputs'].items())
        assert any(rid in page and f'{total} SC total' in page for page in pages)


def test_legacy_and_training_manufacturing_cannot_bypass_station_locks():
    with m.SessionLocal() as db:
        p=citizen(db);p.ore=100;p.sc=1000
        m.material_change(db,p,'wood',10);db.commit()
    blocked=m.make('test','new',recipe='alloy_plate',provider='discord').body.decode()
    assert 'Required workstation' in blocked
    blocked=m.action('train_wood_processing','test','new',provider='discord').body.decode()
    assert 'Required workstation' in blocked
    with m.SessionLocal() as db:
        p=citizen(db)
        assert p.ore==100 and m.material_amount(db,p,'wood')==10
        assert db.query(m.Cooldown).count()==0


def test_new_discord_dispatch_and_market_category_filter():
    before=m.DISCORD_WORLD_ID
    m.DISCORD_WORLD_ID='test'
    try:
        assert 'WORKSHOPS' in m._discord_call_internal('workshop','new','Citizen',{},'1')
        assert 'STARTER ROUTES' in m._discord_call_internal('seedindustries','new','Citizen',{'action':'starters','page':2},'2')
        text=m._discord_call_internal('seedindustries','new','Citizen',{'category':'rare','page':1},'3')
        assert 'Aurite Ore' in text and 'Bauxite Ore' in text
        payload={'data':{'name':'seedindustries','options':[{'name':'action','value':'sell'},{'name':'item','value':'','focused':True}]}}
        choices=m._discord_autocomplete(payload)['data']['choices']
        assert all(m.SEED_INDUSTRIES[c['value']]['sell']>0 for c in choices)
    finally:m.DISCORD_WORLD_ID=before


def test_every_legacy_recipe_has_a_corresponding_station():
    for recipe in set(m.PART_RECIPES)|set(m.RECIPES)|set(m.QUALITY_RECIPES):
        assert cp.legacy_station(m,recipe) in cp.STATIONS
    assert cp.legacy_station(m,'meal_kit')=='TAG_MACHINE_STOVE'
    assert cp.legacy_station(m,'sensor')=='TAG_MACHINE_ELECTRONICS_TABLE'


def test_all_owned_machine_recipe_bonuses_match_real_station_tags():
    for machine,recipes in s.MACHINE_RECIPES.items():
        for recipe in recipes:assert set(cp.tags(recipe)) & s.machine_tags(machine)
