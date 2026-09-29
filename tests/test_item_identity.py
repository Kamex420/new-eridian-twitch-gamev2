"""Real saved balances, not merely alias-table assertions.

Restored after an accidental overwrite (it had become a copy of
test_crafting_progression.py) and extended for the legacy -> SEED catalog items.
"""
import json
import pytest
from test_colony import m,reset,seed,client
from app import item_identity as ident, seed_content as s

K=s.key

@pytest.mark.parametrize('old,new',list(ident.ALIASES.items()))
def test_conversion_combines_existing_balances_one_for_one_and_repeats_safely(old,new):
    field=ident.FIELD_ITEMS.get(new)
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','old','Citizen')
        for column in set(ident.FIELD_ITEMS.values()):setattr(p,column,0)
        if field:setattr(p,field,7)
        # Emulate a pre-update save by writing raw rows, bypassing alias APIs.
        db.add(m.ExtraItem(channel_id='test',canonical_uid=p.twitch_uid,item=old,qty=8))
        db.add(m.ExtraItem(channel_id='test',canonical_uid=p.twitch_uid,item=new,qty=3));db.commit()
        ident.migrate_player(m,db,p);db.commit()
        expected=18 if field else 11
        assert m.material_amount(db,p,new)==expected
        assert m.material_amount(db,p,old)==expected
        ident.migrate_player(m,db,p);db.commit()
        assert m.material_amount(db,p,new)==expected
        assert s.stock(m,db,p)[new]==expected
        assert old not in s.stock(m,db,p)
        m.material_change(db,p,old,-2);db.commit()
        assert m.material_amount(db,p,new)==expected-2
        m.material_change(db,p,new,4);db.commit()
        assert m.material_amount(db,p,old)==expected+2
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','old','Citizen')
        assert m.material_amount(db,p,new)==expected+2


def test_every_legacy_item_is_a_catalog_item():
    assert set(ident.ALIASES.values())<=s.ACTIVE
    expected={'crops':'Pumpkin','components':'Iron Nails','biofiber':'Flaxa','alloy_plate':'Iron Plate',
              'sealant':'Mortar','precision_lens':'Glass','ration':'Dried Berries','water_filter':'Small Water Filter',
              'sensor':'Resource Scanner','crate':'Storage Platform','preserved_food':'Quito Pumpkin Paste',
              'storage_jar':'Ceramic Basin','furniture':'Garden Chair','workwear':'Seed Industries Long Sleeve Top',
              'medicine':'Painkillers'}
    assert {k:s.ITEMS[ident.ALIASES[k]]['name'] for k in expected}==expected
    assert {m.resource_name(k) for k in ('crops','components')}=={'Pumpkin','Iron Nails'}


def test_legacy_recipes_quality_gear_orders_and_training_use_only_catalog_items():
    legacy_only={'toolkit','siro_sampler','duck_crate','spaceport_manifest'}
    for cost in (*m.RECIPES.values(),*(q['cost'] for q in m.QUALITY_RECIPES.values())):
        assert set(cost)<=s.ACTIVE
    for order in m.PRODUCTION_ORDERS.values():
        assert set(order['cost'])<=s.ACTIVE|legacy_only
    for task in m.SEED_TASKS.values():
        assert set(task['cost'])<=s.ACTIVE and set(task['output'])<=s.ACTIVE
    for (action,mode),(energy,outputs) in m.task_yields.YIELDS.items():
        assert set(outputs)<=s.ACTIVE|{'cargo'}


def test_player_columns_back_their_catalog_items():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();stock=s.stock(m,db,p)
        assert stock[K('Pumpkin')]==p.crops==100
        assert stock[K('Iron Nails')]==p.components==100
        # Harvest yields go to the same Pumpkin stock (no separate "Crop").
        m.material_change(db,p,K('Pumpkin'),3);db.commit()
        assert p.crops==103 and m.material_amount(db,p,'crops')==103


def test_migration_rollback_is_atomic_and_scoped():
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','a','A')
        _,q=m.player(db,'test','discord','b','B')
        for person in (p,q):db.add(m.ExtraItem(channel_id='test',canonical_uid=person.twitch_uid,item='wood',qty=9))
        db.commit();ident.migrate_player(m,db,p);db.rollback()
        assert db.query(m.ExtraItem).filter_by(canonical_uid=p.twitch_uid,item='wood').one().qty==9
        ident.migrate_player(m,db,p);db.commit()
        assert db.query(m.ExtraItem).filter_by(canonical_uid=q.twitch_uid,item='wood').one().qty==9
        assert m.material_amount(db,p,'wood')==9


def test_account_link_combines_both_formats_without_double_award():
    with m.SessionLocal() as db:
        _,a=m.player(db,'test','discord','a','A');_,b=m.player(db,'test','twitch','b','B')
        a.ore=5;b.ore=7
        for person,key,qty in [(a,'wood',8),(a,ident.ALIASES['wood'],3),(b,'wood',2),(b,ident.ALIASES['wood'],4),(a,ident.ALIASES['ore'],6)]:
            db.add(m.ExtraItem(channel_id='test',canonical_uid=person.twitch_uid,item=key,qty=qty))
        db.commit();source=a.twitch_uid;target=b.twitch_uid
        m.merge_accounts(db,'test',source,target);db.commit()
        assert m.material_amount(db,b,'wood')==17
        assert m.material_amount(db,b,ident.ALIASES['ore'])==18
        m.merge_accounts(db,'test',source,target);db.commit()
        assert m.material_amount(db,b,'wood')==17
        assert b.ore==18


def test_all_market_keys_unique_and_legacy_buy_spends_same_stock():
    assert not set(ident.ALIASES)&set(m.SEED_INDUSTRIES)
    seed(provider='discord')
    for name in ('wood','Lumber',ident.ALIASES['wood']):
        response=m.seed_industries('test','u',action='buy',item_name=name,amount=2,provider='discord').body.decode()
        assert 'bought 2 Lumber' in response
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert m.material_amount(db,p,'wood')==6
        assert p.sc==10000-24
    for key in (ident.ALIASES['circuit_board'],ident.ALIASES['power_cell']):
        assert m.SEED_INDUSTRIES[key]['sell']<m.SEED_INDUSTRIES[key]['buy']


def test_market_sales_cannot_beat_seed_industries_purchase_prices():
    for key,base in m.MARKET_BASE.items():
        best=max(1,int(base*1.6))
        assert best<m.SEED_INDUSTRIES[ident.canonical(key)]['buy'],key


def test_legacy_recipe_aliases_cannot_bypass_tiers():
    seed(provider='discord')
    for old,rid in ident.RETIRED_RECIPES.items():
        assert m.craft_recipe_key(old)==rid
        response=m.make('test','u',recipe=old,provider='discord').body.decode()
        assert any(word in response.lower() for word in ('required','needs','needed')),response
        assert 'nothing spent' in response.lower()
        assert m.workbench.entry(m,old) is None
    response=m.make('test','u',recipe='biofiber',provider='discord').body.decode()
    assert 'Flaxa' in response and 'Nothing spent' in response


def test_training_uses_canonical_manufacturing_costs_and_locks():
    for action,rid in m.MERGED_TRAINING.items():
        assert m.SEED_TASKS[action]['cost']==s.RECIPES[rid]['inputs']
        assert m.SEED_TASKS[action]['output']==s.RECIPES[rid]['outputs']
    # Two cooking tasks keep two different dishes.
    assert m.MERGED_TRAINING['train_food_preservation']!=m.MERGED_TRAINING['train_advanced_cooking']
    seed(provider='discord')
    response=m.training('test','u',skill='engineering',task='train_electronics',provider='discord').body.decode()
    assert 'Nothing spent' in response


def test_display_labels_have_no_seed_prefix():
    assert 'SEED:' not in json.dumps(m.DISCORD_OPTION_SCHEMA)
    assert all(m.market_item_label(k)==m.resource_name(k) for k in m.SEED_INDUSTRIES)
    payload={'data':{'options':[{'name':'recipe','focused':True,'value':'Circuit'}]},'member':{'user':{'id':'u'}}}
    choices=m._discord_make_autocomplete(payload)['data']['choices']
    assert choices
    assert all('SEED' not in row['name'] for row in choices)


def test_old_rare_route_respects_new_progress_and_cooldown():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12;db.commit()
    first=m.action('rare','test','u',provider='discord').body.decode()
    assert 'PROSPECTING' in first and '1/3' in first
    second=m.action('rare','test','u',provider='discord').body.decode()
    assert 'ready in' in second
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.rare_ore==100
        # Argentite is one rare ore among four: prospecting picks the one this citizen has least of.
        progress={k:m.material_amount(db,p,'prospect:'+k) for k in m.crafting_progression.RARE}
        assert sorted(progress.values())==[0,0,0,1] and progress[ident.ALIASES['rare_ore']]==0


def test_prospecting_continues_the_rare_ore_already_started():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();p.mining_xp=12
        m.material_change(db,p,'prospect:'+ident.ALIASES['rare_ore'],1);db.commit()
        assert m.rare_ore_to_prospect(db,p)==ident.ALIASES['rare_ore']


def test_new_recipe_consumes_converted_legacy_circuit_boards():
    cp=m.crafting_progression
    circuit=ident.ALIASES['circuit_board']
    rid=next(k for k,r in s.RECIPES.items() if circuit in r['inputs'])
    r=s.RECIPES[rid]
    with m.SessionLocal() as db:
        _,p=m.player(db,'test','discord','u','Citizen')
        db.add(m.CraftLedger(channel_id='test',canonical_uid=p.twitch_uid,recipe='component',qty=250,best_quality=''))
        m.material_change(db,p,cp.permit_key(cp.tags(rid)[0]),1)
        req=r['requirement'].get('Skill','SK_CRAFTING');main,branch=s.SKILLS[req]
        if branch:m.gain_branch(db,p,branch,1000)
        else:
            from app.competencies import FIELDS
            setattr(p,FIELDS[main],1000)
        for k,n in r['inputs'].items():
            if k!=circuit:m.material_change(db,p,k,n)
        db.add(m.ExtraItem(channel_id='test',canonical_uid=p.twitch_uid,item='circuit_board',qty=r['inputs'][circuit]+5))
        db.commit();ident.migrate_player(m,db,p);db.commit()
        result=s.craft(m,db,p,rid,'discord')
        assert 'CRAFTING COMPLETE' in result,result
        assert m.material_amount(db,p,'circuit_board')==5
        for key,n in r['outputs'].items():assert m.material_amount(db,p,key)>=n


def test_rare_alias_purchase_is_gated_and_cannot_buy_at_retired_price():
    seed(provider='discord')
    response=m.seed_industries('test','u',action='buy',item_name='rare_ore',provider='discord').body.decode()
    assert 'Harvesting Lv.3' in response
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.sc==10000;p.mining_xp=12;db.commit()
    response=m.seed_industries('test','u',action='buy',item_name='rare_ore',amount=2,provider='discord').body.decode()
    assert '48 SC' in response
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.rare_ore==102


def test_merged_parts_have_one_economy_value_and_orders_pay_below_purchase():
    for old,new in ident.ALIASES.items():assert m.replacement_value(old)==m.replacement_value(new)
    for order in m.PRODUCTION_ORDERS.values():
        numbers=m.production_order_numbers(order)
        assert numbers['sc']<numbers['replacement']


def test_equipment_bonuses_and_unlocks_follow_the_catalog_twins():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        before=m.success_chance(db,p,'frontier')
        m.material_change(db,p,K('Resource Scanner'),1);db.commit()
        assert m.success_chance(db,p,'frontier')>before
    locked=m.action('water','test','u',msg='mode:hydroponics',provider='discord').body.decode()
    assert 'Small Water Filter' in locked and 'Nothing was spent' in locked
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.material_change(db,p,'water_filter',1);db.commit()
        assert m.equipment_count(db,p,K('Small Water Filter'))==1


def test_prepared_food_is_stronger_and_grants_rockys_favor():
    seed(provider='discord')
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();m.life_state(db,p).nutrition=10
        m.material_change(db,p,'ration',1);db.commit()
    text=m.action('eat','test','u',msg='food:'+K('Dried Berries'),provider='discord').body.decode()
    assert 'Dried Berries' in text and "Rocky's Favor" in text
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        assert m.life_state(db,p).nutrition==10+s.nutrition(K('Dried Berries'))
        assert m.bonus_active(db,p,'rockys_favor')
    with m.SessionLocal() as db:db.query(m.Cooldown).delete();db.commit()
    raw=m.action('eat','test','u',msg='food:crops',provider='discord').body.decode()
    assert 'Pumpkin' in raw
    with m.SessionLocal() as db:assert db.query(m.Player).one().crops==99


def test_inventory_has_no_key_resources_section():
    seed(provider='discord')
    text=m.inventory('test','u',provider='discord').body.decode()
    assert 'KEY RESOURCES' not in text.upper() and 'Argentite Ore' in text and 'Pumpkin' in text
    chat=m.inventory('test','u').body.decode()
    assert 'Supplies:' not in chat


def test_old_sell_command_uses_seed_industries_and_daily_demand():
    seed()
    text=m.sell('test','u','Kamex','rare_ore',2).body.decode()
    assert 'sold 2 Argentite Ore to Seed Industries' in text
    board=m.marketboard('test','discord').body.decode()
    a,b=m.market_demand(m.DISCORD_WORLD_ID,1)
    assert m.resource_name(a) in board and m.resource_name(b) in board
    assert m.sale_price(a)>m.SEED_INDUSTRIES[a]['sell']
