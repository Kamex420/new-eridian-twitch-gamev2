"""Batch output, station access, market accounting and historical-data contracts."""
import copy
from test_colony import m,reset,seed
from app import seed_content as s,crafting_progression as cp,production_balance as b

def test_all_manufactured_outputs_have_declared_batch_sizes():
    for rid,row in s.RECIPES.items():
        if not row['inputs']:
            assert row['outputs']==s.DATA['recipes'][rid]['outputs']
            continue
        for tag in cp.tags(rid):
            for k,n in b.outputs_at(s,cp,rid,tag).items():
                assert 5<=n<=20 if s.BATCH_CATEGORIES[k] in b.BULK_CATEGORIES else n==1

def test_demand_sets_batch_size():
    recipes={'r':{'inputs':{},'outputs':{}},'a':{'inputs':{'common':20,'occasional':5,'small':1},'outputs':{'finished':4}},
             'b':{'inputs':{'base':1},'outputs':{'common':1,'occasional':1,'small':1}}}
    b.apply_batches(recipes,{'common':'parts','occasional':'parts','small':'parts','finished':'machines'})
    assert recipes['a']['outputs']=={'finished':1}
    assert recipes['b']['outputs']=={'common':15,'occasional':10,'small':5}

def test_station_selection_and_actual_inventory_match_preview():
    seed()
    variants=[rid for rid,r in s.RECIPES.items() if r['name']=='Wood Planks']
    variants.sort(key=lambda rid:cp.STATIONS[cp.tags(rid)[0]]['tier'])
    basic_rid,rid=variants[0],variants[-1]
    tags=[cp.tags(basic_rid)[0],cp.tags(rid)[0]]
    with m.SessionLocal() as db:
        p=db.query(m.Player).one()
        db.add(m.CraftLedger(channel_id=p.channel_id,canonical_uid=p.twitch_uid,recipe='component',qty=250,best_quality=''))
        m.material_change(db,p,cp.permit_key(tags[0]),1);db.commit()
        basic=b.current_outputs(m,db,p,basic_rid)
        assert b.selected_station(m,db,p,rid) is None
        m.material_change(db,p,cp.permit_key(tags[-1]),1);db.commit()
        advanced=b.current_outputs(m,db,p,rid)
        assert sum(advanced.values())>sum(basic.values())
        assert cp.STATIONS[b.selected_station(m,db,p,rid)]['tier']==cp.STATIONS[tags[-1]]['tier']
        # Raise only the recipe skill check; real access, inputs and reward code run.
        for k,n in s.RECIPES[rid]['inputs'].items():m.material_change(db,p,k,n*2)
        db.commit()
        before={k:m.material_amount(db,p,k) for k in set(advanced)|s.RECIPES[rid]['inputs'].keys()}
        from unittest.mock import patch
        with patch.object(s,'level_for',return_value=100):result=s.craft(m,db,p,rid,'discord')
        assert 'CRAFTING COMPLETE' in result
        for k in before:
            assert m.material_amount(db,p,k)-before[k]==advanced.get(k,0)-s.RECIPES[rid]['inputs'].get(k,0)
        for k,n in advanced.items():assert f'{s.item_label(k)} ×{n}' in result

def test_catalog_buyback_and_no_instant_resale_profit():
    assert s.ACTIVE<=cp.VALUES.keys()
    for k in s.ACTIVE:
        row=m.SEED_INDUSTRIES[k]
        assert row['sell']>0
        if row['buy']:assert row['buy']>row['sell']
    assert all(m.SEED_INDUSTRIES[k]['buy']>0 for k in s.GATHER)

def test_sell_only_item_cannot_be_bought_for_free():
    seed()
    key=next(k for k in s.ACTIVE if not m.SEED_INDUSTRIES[k]['buy'])
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();before=p.sc
    text=m.seed_industries('test','u',action='buy',item_name=key,amount=1).body.decode()
    assert 'does not stock' in text
    with m.SessionLocal() as db:
        p=db.query(m.Player).one();assert p.sc==before and m.material_amount(db,p,key)==0
