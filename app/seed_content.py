
"""Versioned SEED content and explicit New Eridian gameplay adaptations.
Inventory IDs are namespaced; old materials, XP and account links are untouched.
"""
import json, math, copy
from . import production_balance, station_tiers
from .needs import cost_text as need_cost
from pathlib import Path

DATA=json.loads((Path(__file__).parent/'data/seed_catalog.json').read_text())
from . import seasonal as _seasonal
from . import runtime
from .models import SkillBranch
from .settlement import state as colony_state
from sqlalchemy import select
import sys
_seasonal.extend_catalog(DATA,station_tiers.SURVIVAL)
ITEMS=DATA['items']; RECIPES=copy.deepcopy(DATA['recipes']); GATHER={k:dict(v) for k,v in DATA['gather'].items()}
# Gameplay classification: coal is mined; the imported catalog stays historical.
GATHER['sd_183031416']['branch']='ore_mining'
MAIN={'SK_FARMING':'cultivation','SK_HARVESTING':'extraction','SK_ENGINEERING':'infrastructure',
      'SK_PROCESSING':'environmental','SK_CRAFTING':'fabrication','SK_COOKING':'cooking','SK_MEDICINE':'medicine','SK_EMERGENCY_RESPONSE':'emergency'}
BRANCHES={
 'cultivation':['seed_cultivation'], 'extraction':['wood_harvesting','water_collection','stone_quarrying','botanical_harvesting','ore_mining'],
 'infrastructure':['maintenance','mechanical_engineering','electronics'],
 'environmental':['water_treatment','wood_processing','food_processing','stone_processing','metalworking','textile_processing','chemistry','glassworking'],
 'fabrication':['masonry','pottery','carpentry','tailoring'], 'cooking':['food_preservation','advanced_cooking'],
 'medicine':['pharmacy','first_aid','wound_care','burn_care','cardiology','gastroenterology','infectiology','ophthalmology','physiotherapy','nephrology','neurology','dentistry','traumatology']}
SKILLS={**{k:(v,None) for k,v in MAIN.items()},**{'SK_'+b.upper():(main,b) for main,bs in BRANCHES.items() for b in bs}}
SKILLS['SK_MAINTENANCE']=('infrastructure','maintenance_repair')
ACTIVE=set(GATHER)|{k for r in RECIPES.values() for k in (*r['inputs'],*r['outputs'])}
EDIBLE={k:v for k,v in ITEMS.items() if k in ACTIVE and v['consumable'] is not None and not v['remedy'] and not v['ailment_risk'] and v['properties'].get('Food',0)>0}

def nutrition(key):return max(1,min(100,round(EDIBLE[key]['properties']['Food']*50)))
KEY_BY_NAME={}
for _key in sorted(ACTIVE):KEY_BY_NAME.setdefault(ITEMS[_key]['name'].casefold(),[]).append(_key)

def key(name):
    """The catalog key for a uniquely named obtainable item (for readable tables)."""
    rows=KEY_BY_NAME.get(name.casefold(),[])
    if len(rows)!=1:raise KeyError(f'{name!r} is not a unique obtainable catalog item')
    return rows[0]
def skill_name(key):return DATA['skills'].get(key,{}).get('Name','Crafting')
def required_level(r):return max(1,1+math.ceil(r['requirement'].get('Level',0)/10))
def station(r):
    from . import crafting_progression as cp
    rid=next(k for k,v in RECIPES.items() if v is r or v==r)
    return cp.station_names(rid)
def find_item(value):
    from . import item_identity
    value=item_identity.canonical(value.casefold().replace(' ','_')) if value not in ACTIVE else value
    if value in ACTIVE:return value
    matches=[k for k in ACTIVE if value.casefold().replace('_',' ') == ITEMS[k]['name'].casefold()]
    return matches[0] if len(matches)==1 else value

def find_recipe(value):
    if value in RECIPES:return value
    matches=[k for k,r in RECIPES.items() if value.casefold() in (r['name'].casefold(),r['source'].casefold())]
    return matches[0] if len(matches)==1 else None

def level_for(db,p,skill):
    from .game.players import lvl, skill_xp
    main,branch=SKILLS.get(skill,('fabrication',None))
    if not branch:return lvl(skill_xp(p,main))
    row=db.execute(select(SkillBranch).where(SkillBranch.channel_id==p.channel_id,SkillBranch.canonical_uid==p.twitch_uid,SkillBranch.branch==branch)).scalar_one_or_none()
    return lvl(row.xp if row else 0)

def base_tier(recipe):
    """Personal tier a recipe itself needs: its station tier or skill band."""
    return max(min(4,required_level(RECIPES[recipe])),station_tiers.station_tier(RECIPES,recipe))

def acquisition_routes():
    """Pick the easiest finite route to every item; never loop around cycles.

    A route is ranked by the progression it demands: the highest personal tier
    anywhere in its chain, then the number of crafting steps, then skill level.
    An input always ranks strictly before its output (same or lower tier and
    fewer steps), so the chosen routes cannot form a cycle.
    """
    best={key:(0,0,0,'') for key in GATHER}
    routes={key:None for key in GATHER}
    changed=True
    while changed:
        changed=False
        for rid in sorted(RECIPES):
            recipe=RECIPES[rid]
            if not set(recipe['inputs'])<=best.keys():continue
            tier=max([base_tier(rid)]+[best[k][0] for k in recipe['inputs']])
            depth=1+max([best[k][1] for k in recipe['inputs']],default=0)
            candidate=(tier,depth,required_level(recipe),rid)
            for output in recipe['outputs']:
                if output in GATHER:continue
                if output not in best or candidate<best[output]:
                    best[output]=candidate;routes[output]=rid;changed=True
    return routes,best

ACQUISITION,_ROUTE_COST=acquisition_routes()
ITEM_TIER={k:max(1,v[0]) for k,v in _ROUTE_COST.items()}
ITEM_STEPS={k:v[1] for k,v in _ROUTE_COST.items()}

def recipe_progress(recipe):
    """(effective tier, steps from raw materials, skill level) for sorting and labels."""
    r=RECIPES[recipe]
    tier=max([base_tier(recipe)]+[ITEM_TIER[k] for k in r['inputs']])
    steps=1+max([ITEM_STEPS[k] for k in r['inputs']],default=0)
    return tier,steps,required_level(r)

def source_hint(key,provider='discord'):
    if key in GATHER:
        is_ore=GATHER[key]['branch']=='ore_mining'
        command=(f'/mine ore:{item_label(key)} action:Mine' if is_ore else f'/gather resource:{item_label(key)}') if provider=='discord' else (f'!mine {key} 1' if is_ore else f'!gather {key}')
        from . import crafting_progression as cp
        return f"{command} → {GATHER[key]['amount']} per action; no ingredients or skill unlock." if key not in cp.RARE else command+' → '+cp.rare_hint(key)
    rid=ACQUISITION.get(key)
    if not rid:return 'No acquisition route configured; report this item.'
    r=RECIPES[rid]
    command=f'/make recipe:{rid}' if provider=='discord' else f'!make {rid}'
    inputs=', '.join(f'{item_label(k)} ×{n}' for k,n in r['inputs'].items()) or 'no ingredients'
    from . import crafting_progression as cp
    return f"{command} → {r['outputs'][key]}+ per batch from {inputs} · {station(r)} (Tier {cp.recipe_tier(rid)}) · {skill_name(r['requirement'].get('Skill'))} Lv.{required_level(r)}."

def acquisition_plan(key,amount=1):
    """Gross base requirements and dependency order for a fresh batch (surplus kept)."""
    base={};steps=[];surplus={}
    def visit(item,needed):
        reused=min(needed,surplus.get(item,0));needed-=reused
        surplus[item]=surplus.get(item,0)-reused
        if not needed:return
        if item in GATHER:
            batches=math.ceil(needed/GATHER[item]['amount'])
            base[item]=base.get(item,0)+batches
            surplus[item]+=batches*GATHER[item]['amount']-needed
            return
        rid=ACQUISITION[item];r=RECIPES[rid]
        batches=math.ceil(needed/r['outputs'][item])
        for ingredient,n in r['inputs'].items():visit(ingredient,n*batches)
        for output,n in r['outputs'].items():surplus[output]=surplus.get(output,0)+n*batches
        surplus[item]-=needed
        steps.append((rid,batches))
    visit(key,amount)
    return base,steps

def gather_menu(page=1,provider='discord'):
    rows=[k for k in filtered_keys(gather_only=True) if GATHER[k]['branch']!='ore_mining']
    size=8 if provider=='discord' else 3
    pages=max(1,math.ceil(len(rows)/size));page=max(1,min(int(page),pages))
    lines=[f'🌿 GATHER MATERIALS · {page}/{pages} · {len(rows)} resources',
           'No ingredients or skill unlock required. For ores, use /mine.' if provider=='discord' else '1 per action. Use !mine for ores.']
    for key in rows[(page-1)*size:page*size]:
        lines.append(f"• {item_label(key)} ×{GATHER[key]['amount']}"+(f' ({key})' if provider!='discord' else ''))
    lines += (['Select Resource and type its name. Change Page to see every resource.',
               f'Costs per gather: {need_cost(2,", ")}; work needs and the 5-second cooldown apply.',
               'Old material names use the same stock as their catalog replacements. /catalog Item shows the exact ingredient.']
              if provider=='discord' else [f'!gather <id> collects; !gatherpage {min(page+1,pages)} next. Costs {need_cost(2,"/","")}.'])
    return '\n'.join(lines)

def preview(db,p,key):
    from .game.cooldowns_materials import material_amount
    from .game.players import requirement_text
    from . import crafting_progression as cp
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    outputs=production_balance.current_outputs(db,p,key)
    chosen=production_balance.selected_station(db,p,key)
    lines=[f"🛠️ {r['name']}", '', 'ONE BATCH',requirement_text(outputs),production_balance.quote(db,p,key), '', 'MATERIALS']
    lines += ['BATCH OPTIONS · '+ '; '.join(cp.STATIONS[tag]['name']+': '+requirement_text(production_balance.outputs_at(sys.modules[__name__],cp,key,tag)) for tag in cp.tags(key))]
    lines += ['Selected station: '+(cp.STATIONS[chosen]['name'] if chosen else 'Locked; output shown is the base batch.')]
    lines += [f"• {item_label(k)}: {material_amount(db,p,k)}/{v}\n  Get it: {source_hint(k)}" for k,v in r['inputs'].items()] or ['• No ingredients; extraction uses your work cooldown.']
    lines += ['',f"SKILL · {skill_name(req)} Lv.{required_level(r)} · Yours: {level_for(db,p,req)}",cp.unlock_text(db,p,key), '', 'Use /make and select this recipe to craft one batch.', 'Use /gather for natural materials; /catalog to look up ingredients.']
    if any(k in GATHER and GATHER[k]['branch']=='ore_mining' for k in r['outputs']):lines+=['MINING · Uses your work success chance. Failure gives 1 Stone Dust instead of ore.']
    if any(k in cp.RARE for k in r['outputs']):lines+=['RARE EXTRACTION · '+cp.rare_hint(next(k for k in r['outputs'] if k in cp.RARE))]
    return '\n'.join(lines)

def craft(db,p,key,provider):
    from . import extras
    from .game.colony_events import work_counts
    from .game.cooldowns_materials import check_cooldown, craft_record, determination_clear, material_amount, material_change
    from .game.life import life_state, spend_life_for_action
    from .game.players import requirement_text
    from .game.routes_crafting import craft_missing_materials
    from .game.training_and_items import gain_branch
    from . import crafting_progression as cp
    blocked=cp.recipe_gate(db,p,key,provider)
    if blocked:return blocked
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    if level_for(db,p,req)<required_level(r):return f"🔒 {r['name']} needs {skill_name(req)} Lv.{required_level(r)}. Train this branch with /training. Nothing spent."
    rare_output=next((k for k in r['outputs'] if k in cp.RARE),None)
    if rare_output:
        bonus=int(any(material_amount(db,p,k)>0 and key in recipes for k,recipes in MACHINE_RECIPES.items()))
        before=material_amount(db,p,rare_output)
        result=cp.rare_gather(db,p,rare_output,provider,bonus)
        if material_amount(db,p,rare_output)>before:extras.goal_crafted(db,p,key);db.commit()   # the third step recovers the ore
        return result
    missing=craft_missing_materials(db,p,r['inputs'])
    if missing:
        hints=[f'• {item_label(k)}: {source_hint(k,provider)}' for k,n in r['inputs'].items() if material_amount(db,p,k)<n]
        return '🛑 Materials needed — nothing spent\n'+ '\n'.join('• '+s for s in missing)+'\nHOW TO GET THEM\n'+'\n'.join(hints)
    wait=check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ The workshop will be ready in {wait}s. Nothing spent.'
    mining_detail=''
    if any(k in GATHER and GATHER[k]['branch']=='ore_mining' for k in r['outputs']):
        success,mining_detail=cp.mining_roll(db,p,provider)
        if not success:return cp.mining_failure(db,p,provider,mining_detail)
        determination_clear(db,p,'extraction')
    owned=stock(db,p)
    workshop_bonus=int(any(owned.get(machine,0)>0 and key in recipes for machine,recipes in MACHINE_RECIPES.items()))
    for k,v in r['inputs'].items():material_change(db,p,k,-v)
    outputs=production_balance.current_outputs(db,p,key)
    chosen=production_balance.selected_station(db,p,key)
    for k,v in outputs.items():material_change(db,p,k,v)
    # Keep Pharmacy practice separate from healing practice; a declared minigame rule.
    xp=[];line=None
    for sk in dict.fromkeys(r['xp'].get('TrainedSkills') or [req]):
        if sk not in SKILLS:continue
        if sk=='SK_MEDICINE' and req=='SK_PHARMACY':continue
        main,branch=SKILLS[sk];line=line or (main,branch)
        amount=1+workshop_bonus if branch else runtime.gain_skill(p,main,1+workshop_bonus)
        if branch:gain_branch(db,p,branch,amount)
        xp.append(f'+{amount} {skill_name(sk)} XP')
    from . import practice
    found=practice.find(db,p,*(line or ('fabrication',None)))
    life=life_state(db,p);spend_life_for_action(life,'make')
    # Every successful catalog craft (button, chat, queue attempt) passes here: crafting the goal completes it.
    p.actions+=1;p.successes+=1;craft_record(db,p,key);extras.goal_crafted(db,p,key)
    from . import stream_overlay
    stream_overlay.station_used(db,p.channel_id,chosen or (cp.tags(key) or [''])[0]);db.commit()   # the map builds each workstation the first time it is used
    colony=work_counts(db,p,SKILLS.get(req,('fabrication',None))[0],contract='make',action='make',
                         detail='made '+', '.join(f"{item_label(k)} ×{v}" for k,v in outputs.items()))
    return ('✅ CRAFTING COMPLETE\n\nOUTPUT\n'+ '\n'.join(f"• {item_label(k)} ×{v}" for k,v in outputs.items())+
      (f'\n\n{colony}' if colony else '')+'\n\nUSED\n'+(requirement_text(r['inputs']) or 'No ingredients')+'\n\nPRACTICE\n'+', '.join(xp)+(f'\n{found}' if found else '')+
      '\n\nWorkshop: '+(cp.STATIONS[chosen]['name'] if chosen else station(r))+(' · Owned workstation: +1 practice per trained skill included.' if workshop_bonus else '')+'\n'+need_cost(2)+mining_detail)

# The work a gathering trip counts as for New Eridian: wild plants feed the colony, water keeps it running.
GATHER_SKILL={'botanical_harvesting':'cultivation','water_collection':'environmental'}

def gather(db,p,key,provider):
    from .game.colony_events import work_counts
    from .game.cooldowns_materials import check_cooldown, determination_clear, material_change
    from .game.life import life_state, spend_life_for_action, task_need_gate
    from .game.training_and_items import gain_branch
    if key not in GATHER:return '🛑 Choose a natural resource from /gather. Manufactured parts must be crafted.'
    from . import crafting_progression as cp
    if key in cp.RARE:return cp.rare_gather(db,p,key,provider)
    life=life_state(db,p);blocked=task_need_gate(db,p,'make',provider,life)
    if blocked:return blocked
    wait=check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ Gathering will be ready in {wait}s. Nothing spent.'
    detail=''
    if GATHER[key]['branch']=='ore_mining':
        success,detail=cp.mining_roll(db,p,provider)
        if not success:return cp.mining_failure(db,p,provider,detail)
        determination_clear(db,p,'extraction')
    cfg=GATHER[key];material_change(db,p,key,cfg['amount']);xp=runtime.gain_skill(p,'extraction',1);gain_branch(db,p,cfg['branch'],xp)
    from . import practice
    found=practice.find(db,p,'extraction',cfg['branch'])
    spend_life_for_action(life,'make');p.actions+=1;p.successes+=1;db.commit()
    mined=cfg['branch']=='ore_mining'
    colony=work_counts(db,p,GATHER_SKILL.get(cfg['branch'],'extraction'),contract='mine' if mined else None,
                         action='mine' if mined else 'gather',detail=f"{'mined' if mined else 'gathered'} {ITEMS[key]['name']} ×{cfg['amount']}")
    return f"✅ GATHERING COMPLETE\n\nOUTPUT\n• {ITEMS[key]['name']} ×{cfg['amount']}\n\n"+(f"{colony}\n\n" if colony else "")+f"PRACTICE\n+{xp} Harvesting and {cfg['branch'].replace('_',' ').title()} XP\n"+(f"{found}\n" if found else "")+need_cost(2)+detail

# New Eridian adaptations: one primary category per obtainable item.
CATEGORIES={
 'food':'Food','drinks':'Drinks & Water','seeds':'Seeds & Saplings',
 'raw':'Raw Materials & Ores','processed':'Processed Materials','parts':'Components',
 'medicine':'Medicine & Clinic Supplies','clothing':'Clothing & Accessories',
 'machines':'Machines & Workstations','storage':'Storage & Shelves',
 'seating':'Chairs, Sofas & Benches','beds':'Beds & Camping',
 'bathroom':'Bathroom & Washing','tables':'Tables & Counters',
 'decor':'Decor, Lighting & Recreation','building':'Building Parts','tools':'Tools & Logistics'}

def item_label(key):
    name=ITEMS[key]['name']
    variants=sorted(k for k in ACTIVE if ITEMS[k]['name']==name)
    return name if len(variants)<2 else f"{name} · Variant {variants.index(key)+1}"

def category_of(key):
    v=ITEMS[key];cats=set(v['categories']);src=v['source']
    if 'CAT_MAIN_REMEDIES' in cats:return 'medicine'
    if 'CAT_MAIN_SEEDS' in cats:return 'seeds'
    if 'CAT_MAIN_CLOTHING' in cats:return 'clothing'
    if 'CAT_MAIN_TOOLS' in cats or src=='DELIVERY_DRONE' or 'CAT_MAIN_VENDING_MACHINES' in cats:return 'tools'
    if 'CAT_MAIN_MACHINES' in cats:return 'machines'
    if 'CAT_MAIN_ATTACHMENT' in cats:return 'building'
    if 'CAT_SUB_CONSUMABLE_DRINKS' in cats or src.endswith('_WATER'):return 'drinks'
    if 'CAT_SUB_CONSUMABLE_FOOD' in cats:return 'food'
    if 'CAT_SUB_MATERIALS_COMPONENTS' in cats:return 'parts'
    if 'CAT_SUB_MATERIALS_PROCESSED' in cats:return 'processed'
    if 'CAT_MAIN_MATERIALS' in cats:return 'raw'
    if cats & {'CAT_SUB_FURNITURE_CONTAINERS','CAT_SUB_FURNITURE_SHELVES'}:return 'storage'
    if cats & {'CAT_SUB_FURNITURE_CHAIR','CAT_SUB_FURNITURE_SOFA','CAT_SUB_FURNITURE_BENCHES'}:return 'seating'
    if 'CAT_SUB_FURNITURE_BEDS' in cats or src.endswith('_TENT'):return 'beds'
    if cats & {'CAT_SUB_FURNITURE_SINKS','CAT_SUB_FURNITURE_SHOWERS','CAT_SUB_FURNITURE_TOILETS','CAT_SUB_FURNITURE_BATHTUBS'}:return 'bathroom'
    if cats & {'CAT_SUB_FURNITURE_TABLES','CAT_SUB_FURNITURE_COUNTERS'}:return 'tables'
    return 'decor'

CATEGORY={k:category_of(k) for k in ACTIVE}
BATCH_CATEGORIES={k:('processed' if ITEMS[k]['source'].startswith('GMT_MATERIAL_') else CATEGORY[k]) for k in ACTIVE}
BATCH_DEMAND=production_balance.apply_batches(RECIPES,BATCH_CATEGORIES)

# Player-facing groups shared by /make, /catalog and /use. Catalog kinds merge:
# raw + processed -> Materials & Ores, food + drinks -> Food & Drink, tools -> equipment.
DISPLAY_CATEGORIES = (
    ('materials', '🧱', 'Materials & Ores', 'Raw resources, ores, ingots, blocks, glass and chemicals.'),
    ('parts', '⚙️', 'Components', 'Planks, plates, nails, wire, boards and other parts.'),
    ('food', '🍲', 'Food & Drink', 'Meals, preserves, drinks and clean water. Prepared food adds Rocky\'s Favor.'),
    ('medicine', '💊', 'Medicine & Clinic', 'Medicines and clinic supplies for shared Medicines.'),
    ('seeds', '🌱', 'Seeds & Farming', 'Seeds for garden batches.'),
    ('equipment', '🧰', 'Tools & Equipment', 'Tools, bonus equipment and quality gear upgrades.'),
    ('machines', '🏭', 'Machines & Workstations', 'Owning a machine grants its workstation access.'),
    ('building', '🏗️', 'Building Parts', 'Structural pieces that add shared Infrastructure.'),
    ('beds', '🛏️', 'Beds & Camping', 'Rest items: +Energy and +Comfort, kept after use.'),
    ('seating', '🪑', 'Chairs & Sofas', 'Seating: +Comfort and +Social, kept after use.'),
    ('bathroom', '🛁', 'Bathroom & Washing', 'Washing fixtures: +Comfort and +Morale.'),
    ('clothing', '👕', 'Clothing', 'Outfits: +Comfort and +Morale, kept after use.'),
    ('storage', '📦', 'Storage & Shelves', 'Crates, chests and shelves for delivery packing.'),
    ('tables', '🍽️', 'Tables & Counters', 'Tables for hosting meals: +Social and +Morale.'),
    ('decor', '🖼️', 'Decor & Recreation', 'Lighting, art and recreation: +Morale and +Social.'),
)
DISPLAY_INFO = {key: (emoji, label, text) for key, emoji, label, text in DISPLAY_CATEGORIES}
SEED_TO_DISPLAY = {'raw': 'materials', 'processed': 'materials', 'parts': 'parts', 'food': 'food',
                     'drinks': 'food', 'medicine': 'medicine', 'seeds': 'seeds', 'tools': 'equipment',
                     'machines': 'machines', 'building': 'building', 'beds': 'beds', 'seating': 'seating',
                     'bathroom': 'bathroom', 'clothing': 'clothing', 'storage': 'storage', 'tables': 'tables',
                     'decor': 'decor'}
# Old /make and !make category names keep working.
DISPLAY_ALIASES = {
    'raw': 'materials', 'raw_materials': 'materials', 'materials': 'materials', 'processed': 'materials',
    'components': 'parts', 'basic_components': 'parts', 'advanced_components': 'parts', 'basic': 'parts', 'advanced': 'parts',
    'final_products': 'equipment', 'products': 'equipment', 'equipment': 'equipment', 'core': 'equipment', 'tools': 'equipment',
    'gear': 'equipment', 'agriculture': 'equipment', 'extraction': 'equipment', 'fabrication': 'equipment',
    'infrastructure': 'equipment', 'research': 'equipment', 'logistics': 'equipment', 'commerce': 'equipment',
    'frontier': 'equipment', 'life': 'equipment', 'drinks': 'food', 'furniture': 'seating',
    **{'seed_' + k: v for k, v in SEED_TO_DISPLAY.items()},
    **{k: v for k, v in SEED_TO_DISPLAY.items()},
    **{k: k for k in DISPLAY_INFO},
}
DISPLAY_HOME_WORDS = {'', 'home', 'tree', 'all', 'overview', 'workbench'}


def display_category(value):
    """Shared category key, '' for "all/overview", or None when unknown."""
    key = str(value or '').strip().casefold().replace('-', '_').replace(' ', '_').replace('&', 'and')
    if key in DISPLAY_HOME_WORDS:
        return ''
    if key in DISPLAY_ALIASES:
        return DISPLAY_ALIASES[key]
    by_label = {label.casefold().replace(' ', '_').replace('&', 'and'): k for k, (_, label, _) in DISPLAY_INFO.items()}
    return by_label.get(key)

DISPLAY_CATEGORY={k:SEED_TO_DISPLAY[CATEGORY[k]] for k in ACTIVE}

USED_BY={k:[r for r in RECIPES if k in RECIPES[r]['inputs']] for k in ACTIVE}
SOURCE_KEYS={v['source']:k for k,v in ITEMS.items()}
def source_key(s):return SOURCE_KEYS[s]
SEED_CROPS={'CORN':'GMT_PRODUCT_FOOD_CORN','PUMPKIN':'GMT_PRODUCT_FOOD_PUMPKIN',
 'TOMATO':'GMT_PRODUCT_FOOD_TOMATO','FLAXA':'GMT_MATERIAL_RAW_FLAXA','WHEAT':'GMT_MATERIAL_RAW_WHEAT',
 'HERBS':'GMT_MATERIAL_RAW_HERBS','LUMBER':'GMT_MATERIAL_RAW_LUMBER'}

# Keep individual machine names, while matching the extraction tag alias.
def machine_tags(key):
    tags=set(ITEMS[key]['tags'])
    if 'TAG_MACHINE_EXTRACTION_ORE' in tags:tags.add('TAG_MACHINE_EXTRACTOR')
    return tags
MACHINE_RECIPES={k:[rid for rid,r in RECIPES.items() if machine_tags(k)&set(r['machines'])] for k in ACTIVE if CATEGORY[k]=='machines'}

def purpose(key):
    """The same rule drives descriptions, ownership suggestions and execution."""
    v=ITEMS[key];cat=CATEGORY[key];src=v['source']
    if key in EDIBLE:return dict(mode='eat',label=f'Eat: +{nutrition(key)} Nutrition; consumes 1. Use /eat.',consume=True)
    if cat=='medicine':
        batches=[sum(r['inputs'].values())/r['outputs'][key] for r in RECIPES.values() if key in r['outputs']]
        units=max(1,min(8,math.ceil(min(batches,default=1))))
        return dict(mode='clinic',label=f'Supply clinic: consumes 1; +{units} shared Medicines, +1 Contribution, +1 Medicine XP.',consume=True,units=units)
    if cat=='seeds':
        output=source_key(SEED_CROPS[src.removeprefix('GMT_SEED_')])
        return dict(mode='plant',label=f"Garden batch: 1 seed + 1 Clean Water → 3 {ITEMS[output]['name']}; +1 Farming and Seed Cultivation XP.",consume=True,output=output)
    if src=='GMT_MATERIAL_PROCESSED_WATER':return dict(mode='recover',label='Drink: consumes 1; +10 Energy, +10 Comfort.',consume=True,boost={'energy':10,'comfort':10})
    if src=='GMT_PRODUCT_TOOL_SCANNER_BATTERY':return dict(mode='ingredient',label='Scanner battery: consumed by /use Resource Scanner to find 2 Hematite Ore and earn Research XP.',consume=False)
    if src=='GMT_PRODUCT_TOOL_RESOURCE_SCANNER':return dict(mode='scan',label='Scan: keeps scanner; consumes 1 Power Cell → 2 Hematite Ore, +1 Research XP. Costs work needs.',consume=False)
    if src=='DELIVERY_DRONE' or cat=='storage' or 'BACKPACK' in src:return dict(mode='pack',label='Pack delivery: keeps item; 1 personal Cargo → 2 shared Cargo, +1 Logistics XP. Costs work needs.',consume=False)
    if 'CAT_MAIN_VENDING_MACHINES' in v['categories']:return dict(mode='vend',label='Stock vending machine: keeps machine; 1 Crop → 1 SC, +1 Commerce XP. Costs work needs.',consume=False)
    if cat=='machines':return dict(mode='workshop',label='Owning this machine grants matching workshop access after its tier unlock, plus +1 base practice per trained skill/branch. Bonus capped at +1; machine kept. /workshop shows access and tiers.',consume=False)
    if cat=='building' or src.endswith(('_MORTAR','_STONE_TILES')):return dict(mode='build',label='Build: consumes 1; +1 shared Infrastructure, +1 Engineering XP. Every 5 Infrastructure adds 1 housing space. Costs work needs.',consume=True)
    if cat=='beds':return dict(mode='recover',label='Rest: keeps item; +40 Energy, +25 Comfort, +5 Morale.',consume=False,boost={'energy':40,'comfort':25,'morale':5})
    if cat=='seating':return dict(mode='recover',label='Relax: keeps item; +20 Comfort, +10 Social.',consume=False,boost={'comfort':20,'social':10})
    if cat=='bathroom':return dict(mode='wash',label='Wash: keeps fixture; consumes 1 Clean Water; +30 Comfort, +5 Morale.',consume=False,boost={'comfort':30,'morale':5})
    if cat=='tables':return dict(mode='meal',label='Host meal: keeps table; consumes 1 Crop; +25 Social, +8 Morale.',consume=False,boost={'social':25,'morale':8})
    if cat=='clothing':return dict(mode='recover',label='Refresh outfit: keeps clothing; +15 Comfort, +5 Morale. No stacking passive bonus.',consume=False,boost={'comfort':15,'morale':5})
    if cat=='decor':return dict(mode='recover',label='Enjoy recreation or surroundings: keeps item; +12 Morale, +8 Social.',consume=False,boost={'morale':12,'social':8})
    if USED_BY[key]:return dict(mode='ingredient',label=f'Ingredient in {len(USED_BY[key])} recipe(s). /catalog shows what you can make with it.',consume=False)
    return dict(mode='research',label='Analyze surplus: consumes 1; +1 Research XP and +1 society Knowledge. Costs work needs.',consume=True)

PURPOSE={k:purpose(k) for k in ACTIVE}
for _key,_row in _seasonal.FESTIVAL_ITEMS.items():
    PURPOSE[_key]=dict(PURPOSE[_key],label=f"Festival food: +{nutrition(_key)} Nutrition, +{_row['comfort']} Comfort, +{_row['morale']} Morale; consumes 1. Use /eat.")

def stock(db,p):
    from . import item_identity
    return item_identity.stock(db,p)

def category_choices():
    return [{'name':f'{emoji} {label} ({sum(v==k for v in DISPLAY_CATEGORY.values())})','value':k} for k,emoji,label,_ in DISPLAY_CATEGORIES]

def filtered_keys(category='',owned=False,inventory=None,gather_only=False):
    keys=GATHER if gather_only else ACTIVE
    category=display_category(category) or ''
    return sorted((k for k in keys if (not category or DISPLAY_CATEGORY[k]==category) and (not owned or (inventory or {}).get(k,0)>0)),key=lambda k:(ITEMS[k]['name'].casefold(),k))

def recipe_category(key):return CATEGORY[next(iter(RECIPES[key]['outputs']))]

# Override the first release's flat browser. Every item stays reachable via pages.
def catalog(db,p,item='',page=1,owned=False,category=''):
    from .game.players import requirement_text
    from . import crafting_progression as cp
    if category and display_category(category) is None:return '🛑 Choose a category from the list. Nothing spent.'
    category=display_category(category) or ''
    inv=stock(db,p)
    if item:
        if item not in ACTIVE:return '🛑 Choose an obtainable item from the catalog.'
        if category and DISPLAY_CATEGORY[item]!=category:return 'ℹ️ This item is in '+DISPLAY_INFO[DISPLAY_CATEGORY[item]][1]+'. Change Category to inspect it.'
        v=ITEMS[item];lines=[f"🟦 {item_label(item)}",DISPLAY_INFO[DISPLAY_CATEGORY[item]][1],f"Owned: {inv.get(item,0)}",'', 'USE',PURPOSE[item]['label']]
        if PURPOSE[item]['mode'] not in {'eat','ingredient','workshop'}:lines+=['Select /use Item to perform this action. Recovery caps at 100. Item uses share a 20-second cooldown. XP values are base practice; needs and jobs may modify them.']
        lines+=['','HOW TO OBTAIN',source_hint(item)]
        if item not in GATHER:
            base,steps=acquisition_plan(item)
            plan=[f'Gather {item_label(k)}: {n} action(s).'+(' Needs a Mineral Extractor.' if k in cp.RARE else '') for k,n in sorted(base.items())]
            plan += [f"Make {RECIPES[rid]['name']}: {n} batch(es) · {rid} · Tier {cp.recipe_tier(rid)} · {station(RECIPES[rid])} · {skill_name(RECIPES[rid]['requirement'].get('Skill'))} Lv.{required_level(RECIPES[rid])}" for rid,n in steps]
            pages=max(1,math.ceil(len(plan)/6));plan_page=max(1,min(int(page),pages))
            lines+=['',f'ACQUISITION PLAN · {plan_page}/{pages} — for 1 item from scratch',*plan[(plan_page-1)*6:plan_page*6],
                    'Follow the steps in order; reuse inventory to reduce gathering. Surplus is kept. Change Page for more steps.',
                    'Skill locks: practice lower-level recipes or use /training. /workshop shows station access and tier requirements.']
        made=[r for r in RECIPES.values() if item in r['outputs']]
        if made:
            lines+=['','MAKE IT']
            for r in made[:3]:lines += [f"• {r['name']} → {production_balance.current_outputs(db,p,next(k for k,v in RECIPES.items() if v is r))[item]} with current access",requirement_text(r['inputs']) or 'Extraction; no ingredients',f"Tier {cp.recipe_tier(next(k for k,v in RECIPES.items() if v is r))} · {skill_name(r['requirement'].get('Skill'))} Lv.{required_level(r)} · {station(r)}"]
            if len(made)>3:lines+=['More variants appear in /make Recipe search.']
        if USED_BY[item]:
            users=[RECIPES[r]['name'] for r in USED_BY[item]]
            pages=max(1,math.ceil(len(users)/10));page=max(1,min(int(page),pages))
            lines+=['',f'USED IN · {page}/{pages} ({len(users)} recipes)',*['• '+x for x in sorted(users)[(page-1)*10:page*10]],'Keep Item selected and change Page to see every use.']
        if PURPOSE[item]['mode']=='workshop':
            names=sorted(RECIPES[r]['name'] for r in MACHINE_RECIPES[item]);pages=max(1,math.ceil(len(names)/10));page=max(1,min(int(page),pages))
            lines+=['',f'WORKSHOP RECIPES · {page}/{pages}',*['• '+x for x in names[(page-1)*10:page*10]],'Keep Item selected and change Page for all matching recipes.']
        return '\n'.join(lines)
    if not category:
        lines=['🟦 Item Categories','Choose Category to see every item in that group.','']
        for key,emoji,label,_ in DISPLAY_CATEGORIES:lines.append(f"• {emoji} {label}: {len(filtered_keys(key,owned,inv))}")
        lines+=['','Owned filters to your inventory. Page shows the rest of a category.','/make uses the same categories (recipes easiest first). /use shows owned usable items.']
        return '\n'.join(lines)
    rows=filtered_keys(category,owned,inv);pages=max(1,math.ceil(len(rows)/12));page=max(1,min(int(page),pages))
    lines=[f'{DISPLAY_INFO[category][0]} {DISPLAY_INFO[category][1]} · {page}/{pages}',f'{len(rows)} '+('owned item types' if owned else 'items total')+' · 12 per page','']
    lines += [f"• {item_label(k)} ×{inv.get(k,0)}" for k in rows[(page-1)*12:page*12]] or ['No owned items in this category.']
    lines+=['',f'Keep Category selected; change Page (1–{pages}) to see all items.','Select Item for its use, costs and crafting ingredients.']
    return '\n'.join(lines)

def choices(db,p,query='',gather_only=False,category='',owned=False,usable=False):
    """Item dropdowns: name, owned count, then how to get it or what it does."""
    inv=stock(db,p);keys=filtered_keys(category,owned,inv,gather_only)
    if gather_only:keys=[k for k in keys if GATHER[k]['branch']!='ore_mining']
    if usable:keys=[k for k in keys if PURPOSE[k]['mode'] not in {'ingredient','workshop'}]
    def label(k):
        if usable:return f"{item_label(k)} ×{inv.get(k,0)} — {PURPOSE[k]['label']}"
        if gather_only:return f"🌿 {item_label(k)} ×{inv.get(k,0)} · +{GATHER[k]['amount']} per gather · {need_cost(2,', ')}"
        how='gather' if k in GATHER else 'craft'
        return f"{item_label(k)} ×{inv.get(k,0)} · {DISPLAY_INFO[DISPLAY_CATEGORY[k]][1]} · {how}"
    return [(label(k),k) for k in keys]

def use_menu(db,p,category='',page=1):
    inv=stock(db,p);keys=[k for k in filtered_keys(category,True,inv) if PURPOSE[k]['mode'] not in {'ingredient','workshop'}]
    pages=max(1,math.ceil(len(keys)/6));page=max(1,min(int(page),pages))
    lines=[f'🎒 ITEM MENU — Uses · {page}/{pages}',f'{len(keys)} owned usable item types','']
    for key in keys[(page-1)*6:page*6]:lines += [f"• {ITEMS[key]['name']} ×{inv[key]}",PURPOSE[key]['label']]
    if not keys:lines+=['You do not own any usable items in this category.']
    return '\n'.join(lines+['','Select Category to filter; change Page to see every item. Select Item to use it.','Ingredients are used by /make. Owned machines improve matching recipe practice automatically.'])

# Item work practises a skill; a lucky find comes from the same line of work.
WORK_LINE={'plant':('cultivation','seed_cultivation'),'scan':('research',None),'pack':('logistics',None),
           'vend':('commerce',None),'build':('infrastructure','maintenance_repair'),'research':('research',None)}

def use(db,p,key,provider):
    from .game.colony_events import work_counts
    from .game.cooldowns_materials import check_cooldown, material_amount, material_change
    from .game.life import life_state, spend_life_for_action, task_need_gate
    from .game.players import requirement_text
    from .game.routes_crafting import craft_missing_materials
    from .game.training_and_items import gain_branch
    if key not in ACTIVE:return '🛑 Unknown item. Nothing spent.'
    cfg=PURPOSE[key];mode=cfg['mode'];name=item_label(key)
    if material_amount(db,p,key)<1:return f'🛑 You do not own {name}. Nothing spent.'
    if mode in {'ingredient','workshop','eat'}:return 'ℹ️ '+cfg['label']+' Nothing spent.'
    water=source_key('GMT_MATERIAL_PROCESSED_WATER');cost={key:1} if cfg['consume'] else {}
    if mode in {'plant','wash'}:cost[water]=cost.get(water,0)+1
    if mode=='scan':cost[source_key('GMT_PRODUCT_TOOL_SCANNER_BATTERY')]=1
    if mode in {'meal','vend'}:cost['crops']=1
    if mode=='pack':cost['cargo']=1
    life=life_state(db,p)
    if cfg.get('boost') and not any(getattr(life,f)<100 for f in cfg['boost']):return 'ℹ️ These needs are already full. Nothing spent; no cooldown started.'
    work=mode in {'plant','scan','pack','vend','build','research'}
    if work:
        blocked=task_need_gate(db,p,'make',provider,life)
        if blocked:return blocked
    missing=craft_missing_materials(db,p,cost)
    if missing:return '🛑 Still needed: '+', '.join(missing)+'. Nothing spent.'
    wait=check_cooldown(db,p,'seed_use')
    if wait:return f'⏳ Item use ready in {wait}s. Nothing spent.'
    for k,n in cost.items():material_change(db,p,k,-n)
    changes=[]
    for field,amount in cfg.get('boost',{}).items():
        before=getattr(life,field);setattr(life,field,min(100,before+amount));changes.append(f'{field.title()} {before}→{getattr(life,field)}')
    shared=colony_state(db,p.channel_id)
    if mode=='clinic':
        shared.medicines+=cfg['units'];p.contribution+=1;xp=runtime.gain_skill(p,'medicine',1)
        changes+=[f"+{cfg['units']} shared Medicines",'+1 Contribution',f'+{xp} Medicine XP']
    if mode=='plant':
        material_change(db,p,cfg['output'],3);xp=runtime.gain_skill(p,'cultivation',1);gain_branch(db,p,'seed_cultivation',xp)
        changes += [f"+3 {ITEMS[cfg['output']]['name']}",f'+{xp} Farming and Seed Cultivation XP']
    if mode=='scan':
        material_change(db,p,source_key('GMT_MATERIAL_ORE_HEMATITE'),2);xp=runtime.gain_skill(p,'research',1);changes += ['+2 Hematite Ore',f'+{xp} Research XP']
    if mode=='pack':shared.cargo+=2;xp=runtime.gain_skill(p,'logistics',1);changes += ['+2 shared Cargo',f'+{xp} Logistics XP']
    if mode=='vend':p.sc+=1;xp=runtime.gain_skill(p,'commerce',1);changes += ['+1 SC',f'+{xp} Commerce XP']
    if mode=='build':
        before=shared.infrastructure;shared.infrastructure+=1;housing=shared.infrastructure//5-before//5;shared.housing+=housing;changes+=['+1 shared Infrastructure']
        if housing:changes+=['+1 housing space']
        xp=runtime.gain_skill(p,'infrastructure',1);gain_branch(db,p,'maintenance_repair',xp);changes+=[f'+{xp} Engineering XP']
    if mode=='research':
        xp=runtime.gain_skill(p,'research',1);changes += [f'+{xp} Research XP']   # +1 Knowledge comes from work_counts
    if work:
        from . import practice
        line=WORK_LINE.get(mode)
        found=practice.find(db,p,*line) if line else ''
        if found:changes.append(found)
        spend_life_for_action(life,'make');changes+=[need_cost(2)]
    p.actions+=1;p.successes+=1;db.commit()
    skill={'clinic':'medicine'}.get(mode) or (WORK_LINE[mode][0] if work else None)
    colony=work_counts(db,p,skill,grow=work,action='use',detail=f'used {name}') if skill else ''
    return '\n'.join([f'✅ {name} — Complete','','RESULT',*['• '+x for x in changes],*(['',colony] if colony else []),'','USED',requirement_text(cost) if cost else 'No items were consumed.',*(['The selected durable item was kept.'] if not cfg['consume'] else [])])
