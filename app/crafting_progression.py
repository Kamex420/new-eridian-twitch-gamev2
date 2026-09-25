"""New Eridian workshop access, personal recipe tiers and starter supply prices.

Community access is a permanent permit for ONE named station, not free access
all machines. Owning the matching machine also grants access, after tier unlock.
"""
import math
from contextvars import ContextVar
from . import seed_content as s

TIERS=((1,'Starter',0),(2,'Skilled',25),(3,'Industrial',100),(4,'Advanced',250))
FEES={1:15,2:45,3:120,4:300}
SURVIVAL='TAG_MACHINE_SURVIVAL_WORKBENCH'
TAG_TIERS={
 SURVIVAL:1,'TAG_MACHINE_CRAFTING_TABLE_V1':1,'TAG_MACHINE_CRAFTING_TABLE_V2':2,'TAG_MACHINE_CRAFTING_TABLE_V3':3,
 'TAG_MACH_SIMPLE_CARPENTRY_STATION':1,'TAG_MACHINE_ADVANCED_CARPENTRY_STATION':2,
 'TAG_MACHINE_BASIC_FURNACE':1,'TAG_MACHINE_BASIC_ANVIL':1,'TAG_MACHINE_METALWORKING_BENCH':1,
 'TAG_MACHINE_MASONRY':1,'TAG_MACHINE_KILN':1,'TAG_MACHINE_POTTERY_STATION':1,
 'TAG_MACHINE_FOOD_PROCESSOR':1,'TAG_MACHINE_CAMPFIRE':1,'TAG_MACHINE_STOVE':2,'TAG_MACHINE_OVEN':2,
 'TAG_MACHINE_SEED_SEPARATOR':1,'TAG_MACH_PROD_WATER_FILTRATION_SMALL':1,'TAG_MACH_EXT_WATER':1,
 'TAG_MACHINE_MEDICAL_FABRICATOR':1,'TAG_MACHINE_TAILORING_BENCH':2,'TAG_MACHINE_WEAVING_LOOM':1,
 'TAG_MACHINE_CHEMISTRY_STATION':2,'TAG_MACHINE_MILLING_MACHINE':2,'TAG_MACHINE_MINERAL_SEPARATOR':2,
 'TAG_MACHINE_METAL_LATHE':3,'TAG_MACHINE_ROLLING_MILL':3,'TAG_MACHINE_WIRE_DRAWER':2,
 'TAG_MACHINE_TABLE_SAW':3,'TAG_MACHINE_ELECTRONICS_TABLE':3,'TAG_MACHINE_FURNACE':3,
 'TAG_MACHINE_STONE_GRINDER':3,'TAG_MACH_PROD_WATER_FILTRATION':2,'TAG_MACHINE_EXTRACTOR':3,
 'TAG_MACHINE_GROWBOX':4,'TAG_MACHINE_3D_PRINTER':4,'TAG_MACHINE_PLAXIN_SYNTHESIZER':4,
}
STATIONS={tag:{'name':next((s.ITEMS[k]['name'] for k in sorted(s.MACHINE_RECIPES) if tag in s.machine_tags(k)),tag.replace('TAG_MACHINE_','').replace('TAG_MACH_','').replace('_',' ').title()),
              'tier':tier,'cost':0 if tag==SURVIVAL else FEES[tier]} for tag,tier in TAG_TIERS.items()}
STATIONS['TAG_MACHINE_EXTRACTOR']['name']='Mineral Extractor'
# Catalog entries without machine tags get explicit appropriate workstations.
OVERRIDES={'sr_1501328773':['TAG_MACHINE_STOVE'],'sr_1187763008':['TAG_MACHINE_CRAFTING_TABLE_V3'],
           'sr_26415128':['TAG_MACHINE_GROWBOX']}

def tags(recipe):return OVERRIDES.get(recipe, s.RECIPES[recipe]['machines'])
def recipe_tier(recipe):return max(min(4,s.required_level(s.RECIPES[recipe])),min(STATIONS[t]['tier'] for t in tags(recipe)))
def station_names(recipe):return ' or '.join(STATIONS[t]['name'] for t in tags(recipe))
def permit_key(tag):return 'workshop:'+tag

def manufactured_batches(m,db,p):
    valid={k for k,r in s.RECIPES.items() if r['inputs']}|set(m.PART_RECIPES)|set(m.RECIPES)|set(m.QUALITY_RECIPES)
    return sum(row.qty for row in db.execute(m.select(m.CraftLedger).where(m.CraftLedger.channel_id==p.channel_id,m.CraftLedger.canonical_uid==p.twitch_uid)).scalars() if row.recipe in valid)

def personal_tier(m,db,p):
    count=manufactured_batches(m,db,p)
    return max(t for t,_,n in TIERS if count>=n)

def station_owned(m,db,p,tag):
    return any(tag in s.machine_tags(k) and m.material_amount(db,p,k)>0 for k in s.MACHINE_RECIPES)

def has_access(m,db,p,tag):
    return tag==SURVIVAL or m.material_amount(db,p,permit_key(tag))>0 or station_owned(m,db,p,tag)

def tier_hint(tier):
    _,name,count=TIERS[tier-1]
    return f'Tier {tier} {name}: {count} completed manufacturing batches'

def station_gate(m,db,p,station_tags,tier,provider='discord'):
    current=personal_tier(m,db,p);count=manufactured_batches(m,db,p)
    if current<tier:return f'🔒 {tier_hint(tier)} required; you have {count}. Make lower-tier recipes to progress. Nothing spent.'
    available=[t for t in station_tags if current>=STATIONS[t]['tier']]
    if any(has_access(m,db,p,t) for t in available):return ''
    prefix='/workshop action:unlock station:' if provider=='discord' else '!workshopunlock '
    choices=' OR '.join(f"{STATIONS[t]['name']} ({STATIONS[t]['cost']} SC once): {prefix}{t}" for t in available)
    return f'🔒 Required workstation: {choices}. Own the matching machine instead to avoid the fee. Nothing spent.'

def recipe_gate(m,db,p,recipe,provider='discord'):
    blocked=station_gate(m,db,p,tags(recipe),recipe_tier(recipe),provider)
    if blocked:return blocked
    if any(k in RARE for k in s.RECIPES[recipe]['outputs']) and m.lvl(m.skill_xp(p,'extraction'))<RARE_LEVEL:
        return '🔒 Rare ores require Harvesting Lv.3 (12 XP). Gather common materials or use /mine first. Nothing spent.'
    return ''

def unlock_text(m,db,p,recipe):
    tier=recipe_tier(recipe);count=manufactured_batches(m,db,p)
    status=recipe_gate(m,db,p,recipe)
    return f'{tier_hint(tier)} · Yours: {count}\nWORKSTATION · {station_names(recipe)}\n'+(status or 'Station and tier ready.')

def workshop(m,db,p,action='view',station='',page=1,provider='discord'):
    if action not in {'view','unlock'}:return 'Choose View or Unlock. Nothing spent.'
    station=station.strip()
    if station.upper() in STATIONS:station=station.upper()
    if station not in STATIONS:
        matches=[k for k,v in STATIONS.items() if v['name'].casefold()==station.casefold()]
        if len(matches)==1:station=matches[0]
    if action=='unlock':
        if station not in STATIONS:return 'Choose a station from /workshop. Nothing spent.'
        cfg=STATIONS[station]
        if personal_tier(m,db,p)<cfg['tier']:return f"🔒 {tier_hint(cfg['tier'])} required. Nothing spent."
        if has_access(m,db,p,station):return f"{cfg['name']}: access already available. Nothing spent."
        if p.sc<cfg['cost']:return f"Need {cfg['cost']} SC for {cfg['name']}; you have {p.sc}. Nothing spent."
        p.sc-=cfg['cost'];m.material_change(db,p,permit_key(station),1);db.commit()
        return f"✅ {cfg['name']} unlocked permanently for {cfg['cost']} SC. Balance: {p.sc} SC. Recipes still require their listed skill and tier."
    count=manufactured_batches(m,db,p);tier=personal_tier(m,db,p)
    rows=[station] if station in STATIONS else sorted(STATIONS,key=lambda t:(STATIONS[t]['tier'],STATIONS[t]['name']))
    size=6 if provider=='discord' else 2;pages=max(1,math.ceil(len(rows)/size));page=max(1,min(page,pages))
    lines=[f'WORKSHOPS · Tier {tier} · {count} manufacturing batches · Page {page}/{pages}']
    for tag in rows[(page-1)*size:page*size]:
        cfg=STATIONS[tag];state='READY' if tier>=cfg['tier'] and has_access(m,db,p,tag) else 'TIER LOCKED' if tier<cfg['tier'] else 'UNLOCK'
        lines.append(f"{cfg['name']} · T{cfg['tier']} · {state} · {cfg['cost']} SC once"+(f' · {tag}' if provider!='discord' else ''))
    if provider=='discord':
        lines+=['','TIERS',*[tier_hint(t) for t,_,_ in TIERS],
                'Only manufacturing recipes with ingredients count. Gathering, extraction, purchases and non-manufacturing training do not count.',
                'Select Station and Unlock to purchase permanent access. Owning a matching machine also gives access; tier rules still apply.',
                'Recipe previews show skill levels, tier and exact station. Survival Workbench is free.']
    else:lines+=['!workshoppage <page>; !workshopunlock <station ID>. Tiers: 0/25/100/250 batches.']
    return '\n'.join(lines)

RARE_NAMES={'Argentite Ore':24,'Bauxite Ore':24,'Aurite Ore':36,'Rutile Ore':32}
RARE={k for k in s.GATHER if s.ITEMS[k]['name'] in RARE_NAMES}
RARE_LEVEL=3
RARE_STEPS=3

def rare_hint(key):
    return 'Harvesting Lv.3; 3 successful prospecting actions per ore; failure gives 1 Stone Dust. Each: 3 Energy, 1 Nutrition, 1 Comfort; 20s cooldown.'

STONE_DUST='sd_1903724340'
mining_outcome=ContextVar('mining_outcome',default=None)

def mining_roll(m,db,p,provider):
    """Use the work-task chance model before needs are spent; never roll a wait."""
    bonus,notes,life=m.life_modifiers(db,p,'extraction')
    society=m.society(db,p.channel_id)
    world=m.world(db,p.channel_id)
    m.resolve_expired_event(db,society,world)
    _,_,world_bonus,world_notes=m.world_rule_bundle(db,p,society,'mine','extraction',provider)
    world=m.world(db,p.channel_id)
    relevant=bool(world.active_event and 'extraction' in {m.EVENTS[world.active_event]['primary'],m.EVENTS[world.active_event]['support']})
    determination=m.determination_bonus(db,p,'extraction')
    chance=min(.92,max(.10,m.success_chance(db,p,'extraction',.68)+bonus+world_bonus+determination+(.05 if relevant else 0)))
    notes+=world_notes
    if determination:notes.append(f'Determination +{determination*100:g}%')
    if relevant:notes.append('Relevant event +5%')
    success=m.random.random()<chance
    mining_outcome.set('success' if success else 'failed')
    return success,m.life_modifier_text(provider,notes,chance)

def mining_failure(m,db,p,provider,detail,rare=False):
    """A failed roll costs needs and one attempt, but preserves ore progress."""
    m.material_change(db,p,STONE_DUST,1)
    life=m.life_state(db,p);m.spend_life_for_action(life,'rare' if rare else 'make')
    p.actions+=1
    grit=m.determination_fail(db,p,'extraction');db.commit()
    return ('❌ MINING FAILED\n\nOUTPUT\n• Stone Dust ×1\nNo ore was recovered.'+
            (' Saved prospecting progress was kept.' if rare else '')+
            f"\n−{3 if rare else 2} Energy · −1 Nutrition · −1 Comfort"+
            f"\nCooldown: {20 if rare else 5} seconds. Stone Dust is a crafting ingredient."+grit+detail)

def rare_gather(m,db,p,key,provider='discord',workshop_bonus=0):
    if m.lvl(m.skill_xp(p,'extraction'))<RARE_LEVEL:
        return '🔒 Rare ores require Harvesting Lv.3 (12 XP). Gather common materials or use /mine first. Nothing spent.'
    life=m.life_state(db,p);blocked=m.task_need_gate(db,p,'make',provider,life)
    if blocked:return blocked
    wait=m.check_cooldown(db,p,'rare_prospect')
    if wait:return f'⏳ Prospecting will be ready in {wait}s. Nothing spent.'
    success,detail=mining_roll(m,db,p,provider)
    if not success:return mining_failure(m,db,p,provider,detail,rare=True)
    m.determination_clear(db,p,'extraction')
    progress_key='prospect:'+key;progress=m.material_amount(db,p,progress_key)+1
    complete=progress>=RARE_STEPS
    m.material_change(db,p,progress_key,-m.material_amount(db,p,progress_key))
    if not complete:m.material_change(db,p,progress_key,progress)
    mining_outcome.set('success' if complete else 'progress')
    if complete:m.material_change(db,p,key,1)
    xp=m.gain_skill(p,'extraction',1+workshop_bonus);m.gain_branch(db,p,'ore_mining',xp)
    m.spend_life_for_action(life,'rare');p.actions+=1;p.successes+=int(complete);db.commit()
    return (f"{'✅ ORE RECOVERED' if complete else '⛏️ PROSPECTING'} · {s.item_label(key)}\n"
            f"Progress: {progress}/3 · {'+1 ore; progress resets.' if complete else 'No ore yet; progress saved.'}\n"
            f'+{xp} Harvesting/Ore Mining XP · −3 Energy · −1 Nutrition · −1 Comfort · 20s cooldown'+detail)

# Price all catalog materials from existing base-resource values plus processing
# labor. No-input extraction never makes ores free. These new supplies have no
# NPC buyback, so starter trades cannot create a buy/craft/sell cash loop.
def starter_market():
    prices={k:RARE_NAMES.get(s.ITEMS[k]['name'],6 if s.GATHER[k]['branch']=='ore_mining' else 4) for k in s.GATHER}
    # Moving Coal into the mining menu does not change its established price.
    prices['sd_183031416']=4
    for _ in range(len(s.RECIPES)):
        changed=False
        for rid,r in s.RECIPES.items():
            if not r['inputs'] or not set(r['inputs'])<=prices.keys():continue
            cost=sum(prices[k]*n for k,n in r['inputs'].items())+4+2*s.required_level(r)
            for k,n in r['outputs'].items():
                if k in s.GATHER:continue
                value=max(2,math.ceil(cost/n))
                if k not in prices or value<prices[k]:prices[k]=value;changed=True
        if not changed:break
    global VALUES
    VALUES=dict(prices)
    selected=set(s.GATHER);starters={}
    skills={r['requirement'].get('Skill','SK_CRAFTING') for r in s.RECIPES.values()}
    for skill in sorted(skills):
        options=[(rid,r) for rid,r in s.RECIPES.items() if r['requirement'].get('Skill','SK_CRAFTING')==skill and r['inputs'] and set(r['inputs'])<=prices.keys()]
        if not options:continue
        rid,r=min(options,key=lambda pair:(s.required_level(pair[1]),recipe_tier(pair[0]),sum(prices[k]*n for k,n in pair[1]['inputs'].items()),pair[0]))
        starters[skill]=rid;selected.update(r['inputs'])
    return {k:dict(buy=prices[k],sell=0,purpose='Starter supply; '+s.PURPOSE[k]['label'],category='rare' if k in RARE else 'seed') for k in selected},starters

STARTER_MARKET,BRANCH_STARTERS=starter_market()

LEGACY_STATIONS={'component':SURVIVAL,'biofiber':SURVIVAL,'alloy_plate':'TAG_MACHINE_METALWORKING_BENCH',
 'circuit_board':'TAG_MACHINE_ELECTRONICS_TABLE','power_cell':'TAG_MACHINE_ELECTRONICS_TABLE',
 'sealant':'TAG_MACHINE_CHEMISTRY_STATION','precision_lens':'TAG_MACHINE_METALWORKING_BENCH',
 'ration':'TAG_MACHINE_CAMPFIRE','toolkit':'TAG_MACHINE_CRAFTING_TABLE_V1',
 'sensor':'TAG_MACHINE_ELECTRONICS_TABLE','crate':'TAG_MACH_SIMPLE_CARPENTRY_STATION',
 'water_filter':'TAG_MACH_PROD_WATER_FILTRATION_SMALL','siro_sampler':'TAG_MACHINE_MEDICAL_FABRICATOR',
 'duck_crate':'TAG_MACH_SIMPLE_CARPENTRY_STATION','spaceport_manifest':'TAG_MACHINE_ELECTRONICS_TABLE',
 'meal_kit':'TAG_MACHINE_STOVE','recreation_set':'TAG_MACH_SIMPLE_CARPENTRY_STATION','comfort_pack':'TAG_MACHINE_TAILORING_BENCH'}
def legacy_station(m,recipe):
    if recipe in LEGACY_STATIONS:return LEGACY_STATIONS[recipe]
    cfg=m.QUALITY_RECIPES.get(recipe,{})
    if recipe=='chef_tools':return 'TAG_MACHINE_METALWORKING_BENCH'
    if recipe=='medical_bag':return 'TAG_MACHINE_TAILORING_BENCH'
    if recipe=='fire_gear':return 'TAG_MACHINE_TAILORING_BENCH'
    return {'agriculture':'TAG_MACHINE_CRAFTING_TABLE_V1','extraction':'TAG_MACHINE_METALWORKING_BENCH','fabrication':'TAG_MACHINE_METALWORKING_BENCH','infrastructure':'TAG_MACHINE_CRAFTING_TABLE_V2','research':'TAG_MACHINE_ELECTRONICS_TABLE','logistics':'TAG_MACHINE_CRAFTING_TABLE_V2','commerce':'TAG_MACHINE_ELECTRONICS_TABLE','frontier':'TAG_MACHINE_TAILORING_BENCH'}.get(cfg.get('category'),'TAG_MACHINE_CRAFTING_TABLE_V2')

def legacy_gate(m,db,p,recipe,provider='discord'):
    tag=legacy_station(m,recipe)
    return station_gate(m,db,p,[tag],STATIONS[tag]['tier'],provider)

TRAINING_STATIONS={'mechanical_engineering':SURVIVAL,'electronics':'TAG_MACHINE_ELECTRONICS_TABLE',
 'wood_processing':'TAG_MACH_SIMPLE_CARPENTRY_STATION','food_processing':'TAG_MACHINE_FOOD_PROCESSOR',
 'stone_processing':'TAG_MACHINE_MASONRY','metalworking':'TAG_MACHINE_METALWORKING_BENCH',
 'textile_processing':'TAG_MACHINE_WEAVING_LOOM','chemistry':'TAG_MACHINE_CHEMISTRY_STATION',
 'glassworking':'TAG_MACHINE_KILN','pottery':'TAG_MACHINE_POTTERY_STATION',
 'carpentry':'TAG_MACH_SIMPLE_CARPENTRY_STATION','tailoring':'TAG_MACHINE_TAILORING_BENCH',
 'food_preservation':'TAG_MACHINE_FOOD_PROCESSOR','advanced_cooking':'TAG_MACHINE_STOVE',
 'pharmacy':'TAG_MACHINE_MEDICAL_FABRICATOR'}


def starter_routes(page=1,provider='discord'):
    rows=sorted(BRANCH_STARTERS.items(),key=lambda pair:s.skill_name(pair[0]))
    size=3 if provider=='discord' else 1
    pages=math.ceil(len(rows)/size);page=max(1,min(page,pages))
    lines=[f'STARTER ROUTES · {page}/{pages}']
    for skill,rid in rows[(page-1)*size:page*size]:
        r=s.RECIPES[rid];cost=sum(STARTER_MARKET[k]['buy']*n for k,n in r['inputs'].items())
        inputs=', '.join(f"{s.item_label(k)} ×{n}" for k,n in r['inputs'].items())
        lines += [f"{s.skill_name(skill)}: {r['name']} · {rid}",f"Buy {inputs} — {cost} SC total.",
                  f"Tier {recipe_tier(rid)} · {station_names(rid)} · {s.skill_name(skill)} Lv.{s.required_level(r)}"]
    if provider=='discord':lines += ['Gather/manufacture instead to save SC. Materials only: station access is separate. Select Buy + Item to purchase each input; /workshop shows exact unlocks. Change Page for every branch.']
    else:lines+=['!seedstarters <page>; station access separate.']
    return '\n'.join(lines)
