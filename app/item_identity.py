"""One identity per overlapping item; old command keys remain input aliases.

Quantity conversion is 1:1, independent of SC price. Hematite uses the existing
players.ore column so old mining, trade, account merging and overlays share stock.
"""
from . import seed_content as s
ALIASES = {
    'rare_ore':'sd_1035602738', 'ore':'sd_559614005', 'wood':'sd_1000004', 'water':'sd_817726320',
    'stone':'sd_1566791299', 'herbs':'sd_2055185252', 'planks':'sd_1000007',
    'cut_stone':'sd_2080163520', 'cloth':'sd_433254052',
    'antiseptic':'sd_98228772', 'circuit_board':'sd_3000011',
    'power_cell':'sd_733736927',
}
FIELD_ITEMS = {ALIASES['ore']:'ore', ALIASES['rare_ore']:'rare_ore'}
RETIRED_RECIPES = {k:s.ACQUISITION[v] for k,v in ALIASES.items() if k in {'circuit_board','power_cell'}}

def canonical(key):return ALIASES.get(key,key)

def migrate_player(m,db,p):
    """Caller owns commit. Lock account before merging; zero source atomically.

    Re-running, restarting, or linking a migrated account cannot award twice.
    No negative balances are manufactured or silently discarded.
    """
    db.flush()
    db.execute(m.select(m.Player.id).where(m.Player.id==p.id).with_for_update()).scalar_one()
    db.refresh(p)
    rows=list(db.execute(m.select(m.ExtraItem).where(m.ExtraItem.channel_id==p.channel_id,m.ExtraItem.canonical_uid==p.twitch_uid)).scalars())
    by_key={r.item:r for r in rows}
    for old,new in ALIASES.items():
        row=by_key.get(old)
        if row is None or row.qty==0:continue
        if new in FIELD_ITEMS:
            field=FIELD_ITEMS[new];setattr(p,field,getattr(p,field)+row.qty)
        else:
            target=by_key.get(new)
            if target is None:
                target=m.ExtraItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item=new,qty=0)
                db.add(target);by_key[new]=target
            target.qty+=row.qty
        row.qty=0
    for key,field in FIELD_ITEMS.items():
        row=by_key.get(key)
        if row is not None and row.qty:
            setattr(p,field,getattr(p,field)+row.qty);row.qty=0
    db.flush()

def stock(m,db,p):
    if p is None:return {}
    result={}
    for row in db.execute(m.select(m.ExtraItem).where(m.ExtraItem.channel_id==p.channel_id,m.ExtraItem.canonical_uid==p.twitch_uid,m.ExtraItem.qty>0)).scalars():
        key=canonical(row.item);result[key]=result.get(key,0)+row.qty
    for key,field in FIELD_ITEMS.items():
        if getattr(p,field):result[key]=result.get(key,0)+getattr(p,field)
    return result

def configure(m):
    # One market listing per identity. Keep canonical acquisition prices; merged
    # manufactured parts are buy-only to avoid gather/craft/NPC cash loops.
    for old,new in ALIASES.items():
        old_listing=m.SEED_INDUSTRIES.pop(old,None)
        if new not in m.SEED_INDUSTRIES and old_listing:
            m.SEED_INDUSTRIES[new]={**old_listing,'sell':0,'category':'training'}
    for old in ('circuit_board','power_cell'):
        new=ALIASES[old]
        m.SEED_INDUSTRIES[new]={'buy':m.crafting_progression.VALUES[new],'sell':0,'category':'seed','purpose':s.purpose(new)['label']}
    # The established Ore sale channel remains, backed by the same Hematite.
    m.SEED_INDUSTRIES[ALIASES['ore']].update(buy=6,sell=2)
    m.SEED_INDUSTRIES[ALIASES['rare_ore']].update(buy=24,sell=8)
    # Training remains available but uses the canonical recipe's ingredients,
    # quantities, machine, tier and skill gates when it makes a merged product.
    m.MERGED_TRAINING={}
    for action,cfg in m.SEED_TASKS.items():
        outputs=[canonical(k) for k in cfg['output'] if k in ALIASES and canonical(k) not in s.GATHER]
        if outputs:
            rid=s.ACQUISITION[outputs[0]]
            if rid:
                m.MERGED_TRAINING[action]=rid
                cfg['cost']=dict(s.RECIPES[rid]['inputs']);cfg['output']=dict(s.RECIPES[rid]['outputs'])

    for cfg in m.SEED_TASKS.values():
        for key in cfg['cost']:
            key=canonical(key)
            if key in s.ACTIVE and key not in m.SEED_INDUSTRIES:
                m.SEED_INDUSTRIES[key]={'buy':m.crafting_progression.VALUES[key],'sell':0,'category':'training','purpose':s.PURPOSE[key]['label']}
    for old,rid in RETIRED_RECIPES.items():m.PART_RECIPES[old]=dict(s.RECIPES[rid]['inputs'])
