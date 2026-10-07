"""One identity per overlapping item; old command keys remain input aliases.

Every legacy New Eridian material, tool and training product now resolves to a
SEED catalog item. Quantity conversion is 1:1, independent of SC price, and is
repeat-safe. Four catalog items keep using their established player columns so
old mining, farming, trade, account merging and overlays share one stock:
Hematite Ore (ore), Argentite Ore (rare_ore), Pumpkin (crops) and Iron Nails
(components). Players see them as ordinary items; the columns are storage only.
Argentite is one of the four rare ores, priced and mined like the others.
Cargo stays a logistics token; it has no catalog counterpart.
"""
from . import seed_content as s
from . import runtime
from .models import ExtraItem
from .models import Player
from sqlalchemy import select

K=s.key
ALIASES = {
    # Earlier consolidation.
    'rare_ore':'sd_1035602738', 'ore':'sd_559614005', 'wood':'sd_1000004', 'water':'sd_817726320',
    'stone':'sd_1566791299', 'herbs':'sd_2055185252', 'planks':'sd_1000007',
    'cut_stone':'sd_2080163520', 'cloth':'sd_433254052',
    'antiseptic':'sd_98228772', 'circuit_board':'sd_3000011',
    'power_cell':'sd_733736927',
    # Legacy raw goods and manufactured parts.
    'crops':K('Pumpkin'), 'components':K('Iron Nails'), 'biofiber':K('Flaxa'),
    'alloy_plate':K('Iron Plate'), 'sealant':K('Mortar'), 'precision_lens':K('Glass'),
    # Legacy supplies and tools with a direct catalog twin.
    'ration':K('Dried Berries'), 'water_filter':K('Small Water Filter'),
    'sensor':K('Resource Scanner'), 'crate':K('Storage Platform'),
    # Legacy training products.
    'preserved_food':K('Quito Pumpkin Paste'), 'storage_jar':K('Ceramic Basin'),
    'furniture':K('Garden Chair'), 'workwear':K('Seed Industries Long Sleeve Top'),
    'medicine':K('Painkillers'),
}
FIELD_ITEMS = {ALIASES['ore']:'ore', ALIASES['rare_ore']:'rare_ore',
               ALIASES['crops']:'crops', ALIASES['components']:'components'}
# Legacy recipe keys whose product is now a catalog item craft that item's
# easiest catalog recipe, with its station, tier and skill gates.
LEGACY_OUTPUTS = {'component':'components','biofiber':'biofiber','alloy_plate':'alloy_plate',
                  'circuit_board':'circuit_board','power_cell':'power_cell','sealant':'sealant',
                  'precision_lens':'precision_lens','ration':'ration','crate':'crate',
                  'water_filter':'water_filter','sensor':'sensor'}
RETIRED_RECIPES = {old:s.ACQUISITION[ALIASES[item]] for old,item in LEGACY_OUTPUTS.items() if s.ACQUISITION.get(ALIASES[item])}
# Retired recipes whose product is now simply gathered (Biofiber -> Flaxa).
RETIRED_GATHERED = {old:ALIASES[item] for old,item in LEGACY_OUTPUTS.items() if ALIASES[item] in s.GATHER}
# Training tasks that would otherwise share a recipe get their own catalog dish.
TRAINING_RECIPES = {'train_advanced_cooking':s.ACQUISITION[K('Forager Stew')]}

def canonical(key):return ALIASES.get(key,key)

def canonical_costs(costs):
    merged={}
    for key,qty in costs.items():
        key=canonical(key);merged[key]=merged.get(key,0)+qty
    return merged

# Item rows that still need converting: an old key, or a catalog item stored in a player column.
MIGRATING=frozenset(ALIASES)|frozenset(FIELD_ITEMS)

def migrate_player(m,db,p):
    """Caller owns commit. Lock account before merging; zero source atomically.

    Re-running, restarting, or linking a migrated account cannot award twice.
    No negative balances are manufactured or silently discarded.
    Every request runs this, so a citizen with nothing to convert costs one read and no lock.
    """
    db.flush()
    owned=lambda:list(db.execute(select(ExtraItem).where(ExtraItem.channel_id==p.channel_id,ExtraItem.canonical_uid==p.twitch_uid)).scalars())
    if not any(r.item in MIGRATING and r.qty for r in owned()):return
    db.execute(select(Player.id).where(Player.id==p.id).with_for_update()).scalar_one()
    db.refresh(p)
    rows=owned()     # read again under the lock
    by_key={r.item:r for r in rows}
    for old,new in ALIASES.items():
        row=by_key.get(old)
        if row is None or row.qty==0:continue
        if new in FIELD_ITEMS:
            field=FIELD_ITEMS[new];setattr(p,field,getattr(p,field)+row.qty)
        else:
            target=by_key.get(new)
            if target is None:
                target=ExtraItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item=new,qty=0)
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
    for row in db.execute(select(ExtraItem).where(ExtraItem.channel_id==p.channel_id,ExtraItem.canonical_uid==p.twitch_uid,ExtraItem.qty>0)).scalars():
        key=canonical(row.item);result[key]=result.get(key,0)+row.qty
    for key,field in FIELD_ITEMS.items():
        if getattr(p,field):result[key]=result.get(key,0)+getattr(p,field)
    return result

def configure(m):
    # One market listing per identity. Keep canonical acquisition prices; merged
    # manufactured parts are buy-only to avoid gather/craft/NPC cash loops.
    from . import crafting_progression
    from .game.rules import PART_RECIPES, SEED_INDUSTRIES
    from .seed_skills import TASKS as SEED_TASKS
    for old,new in ALIASES.items():
        old_listing=SEED_INDUSTRIES.pop(old,None)
        if new not in SEED_INDUSTRIES and old_listing:
            SEED_INDUSTRIES[new]={**old_listing,'sell':0,'category':'training'}
    for old in ('circuit_board','power_cell'):
        new=ALIASES[old]
        SEED_INDUSTRIES[new]={'buy':crafting_progression.VALUES[new],'sell':0,'category':'seed','purpose':s.purpose(new)['label']}
    # The established Ore sale channel remains, backed by the same Hematite.
    SEED_INDUSTRIES[ALIASES['ore']].update(buy=6,sell=2)
    # Training tasks read and write catalog identities only.
    for cfg in SEED_TASKS.values():
        cfg['cost']=canonical_costs(cfg['cost']);cfg['output']=canonical_costs(cfg['output'])
    # Training remains available but uses the canonical recipe's ingredients,
    # quantities, machine, tier and skill gates when it makes a manufactured item.
    m.MERGED_TRAINING={}
    for action,cfg in SEED_TASKS.items():
        outputs=[k for k in cfg['output'] if k not in s.GATHER]
        rid=TRAINING_RECIPES.get(action) or (s.ACQUISITION.get(outputs[0]) if outputs else None)
        if rid:
            runtime.MERGED_TRAINING[action]=rid
            cfg['cost']=dict(s.RECIPES[rid]['inputs']);cfg['output']=dict(s.RECIPES[rid]['outputs'])

    for cfg in SEED_TASKS.values():
        for key in cfg['cost']:
            key=canonical(key)
            if key in s.ACTIVE and key not in SEED_INDUSTRIES:
                SEED_INDUSTRIES[key]={'buy':crafting_progression.VALUES[key],'sell':0,'category':'training','purpose':s.PURPOSE[key]['label']}
    for old,rid in RETIRED_RECIPES.items():
        if old in PART_RECIPES:PART_RECIPES[old]=dict(s.RECIPES[rid]['inputs'])
