

"""Versioned SEED content and explicit New Eridian gameplay adaptations.
Inventory IDs are namespaced; old materials, XP and account links are untouched.
"""
import json, math
from pathlib import Path

DATA=json.loads((Path(__file__).parent/'data/seed_catalog.json').read_text())
ITEMS=DATA['items']; RECIPES=DATA['recipes']; GATHER=DATA['gather']
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
def skill_name(key):return DATA['skills'].get(key,{}).get('Name','Crafting')
def required_level(r):return max(1,1+math.ceil(r['requirement'].get('Level',0)/10))
def station(r):
    return ', '.join(t.removeprefix('TAG_MACHINE_').removeprefix('TAG_MACH_').replace('_',' ').title() for t in r['machines']) or 'Community workbench'
def find_item(value):
    if value in ACTIVE:return value
    matches=[k for k in ACTIVE if value.casefold().replace('_',' ') == ITEMS[k]['name'].casefold()]
    return matches[0] if len(matches)==1 else value

def find_recipe(value):
    if value in RECIPES:return value
    matches=[k for k,r in RECIPES.items() if value.casefold() in (r['name'].casefold(),r['source'].casefold())]
    return matches[0] if len(matches)==1 else None

def level_for(m,db,p,skill):
    main,branch=SKILLS.get(skill,('fabrication',None))
    if not branch:return m.lvl(m.skill_xp(p,main))
    row=db.execute(m.select(m.SkillBranch).where(m.SkillBranch.channel_id==p.channel_id,m.SkillBranch.canonical_uid==p.twitch_uid,m.SkillBranch.branch==branch)).scalar_one_or_none()
    return m.lvl(row.xp if row else 0)

def acquisition_routes():
    """Pick finite dependency paths; never send players around recipe cycles."""
    routes={key:None for key in GATHER}
    pending=sorted(RECIPES, key=lambda key:(required_level(RECIPES[key]),key))
    while True:
        additions={}
        for key in pending:
            recipe=RECIPES[key]
            if set(recipe['inputs']) <= routes.keys():
                for output in recipe['outputs']:
                    if output not in routes:additions.setdefault(output,key)
        if not additions:return routes
        routes.update(additions)

ACQUISITION=acquisition_routes()

def source_hint(key,provider='discord'):
    if key in GATHER:
        command=f'/gather resource:{item_label(key)}' if provider=='discord' else f'!gather {key}'
        return f"{command} → {GATHER[key]['amount']} per action; no ingredients or skill unlock."
    rid=ACQUISITION.get(key)
    if not rid:return 'No acquisition route configured; report this item.'
    r=RECIPES[rid]
    command=f'/make recipe:{rid}' if provider=='discord' else f'!make {rid}'
    inputs=', '.join(f'{item_label(k)} ×{n}' for k,n in r['inputs'].items()) or 'no ingredients'
    return f"{command} → {r['outputs'][key]} per batch; {inputs}; {skill_name(r['requirement'].get('Skill'))} Lv.{required_level(r)}."

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
    rows=filtered_keys(gather_only=True)
    size=8 if provider=='discord' else 3
    pages=max(1,math.ceil(len(rows)/size));page=max(1,min(int(page),pages))
    lines=[f'🌿 GATHER MATERIALS · {page}/{pages} · {len(rows)} resources',
           'No ingredients, SC, tools or skill unlock required.']
    for key in rows[(page-1)*size:page*size]:
        lines.append(f"• {item_label(key)} ×{GATHER[key]['amount']}"+(f' ({key})' if provider!='discord' else ''))
    lines += (['Select Resource and type its name. Change Page to see every resource.',
               'Costs: 2 Energy, 1 Nutrition, 1 Comfort; work needs and cooldown apply.',
               'Named SEED materials are separate from legacy Ore, Wood and Water. /catalog Item shows the exact ingredient.']
              if provider=='discord' else [f'!gather <id> collects; !gatherpage {min(page+1,pages)} next. Costs 2 Energy/1 Nutrition/1 Comfort.'])
    return '\n'.join(lines)

def preview(m,db,p,key):
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    lines=[f"🛠️ {r['name']}", '', 'ONE BATCH',m.requirement_text(r['outputs']), '', 'MATERIALS']
    lines += [f"• {item_label(k)}: {m.material_amount(db,p,k)}/{v}\n  Get it: {source_hint(k)}" for k,v in r['inputs'].items()] or ['• No ingredients; extraction uses your work cooldown.']
    lines += ['',f"SKILL · {skill_name(req)} Lv.{required_level(r)} · Yours: {level_for(m,db,p,req)}",f"WORKSHOP · {station(r)}",'Community workshop access is included.', '', 'Use /make and select this recipe to craft one batch.', 'Use /gather for natural materials; /catalog to look up ingredients.']
    return '\n'.join(lines)

def craft(m,db,p,key,provider):
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    if level_for(m,db,p,req)<required_level(r):return f"🔒 {r['name']} needs {skill_name(req)} Lv.{required_level(r)}. Train this branch with /training. Nothing spent."
    missing=m.craft_missing_materials(db,p,r['inputs'])
    if missing:
        hints=[f'• {item_label(k)}: {source_hint(k,provider)}' for k,n in r['inputs'].items() if m.material_amount(db,p,k)<n]
        return '🛑 Materials needed\n'+ '\n'.join('• '+s for s in missing)+'\nHOW TO GET THEM\n'+'\n'.join(hints)
    wait=m.check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ Workshop ready in {wait}s. Nothing spent.'
    owned=stock(m,db,p)
    workshop_bonus=int(any(owned.get(machine,0)>0 and key in recipes for machine,recipes in MACHINE_RECIPES.items()))
    for k,v in r['inputs'].items():m.material_change(db,p,k,-v)
    for k,v in r['outputs'].items():m.material_change(db,p,k,v)
    # Keep Pharmacy practice separate from healing practice; a declared minigame rule.
    xp=[]
    for sk in dict.fromkeys(r['xp'].get('TrainedSkills') or [req]):
        if sk not in SKILLS:continue
        if sk=='SK_MEDICINE' and req=='SK_PHARMACY':continue
        main,branch=SKILLS[sk]
        amount=1+workshop_bonus if branch else m.gain_skill(p,main,1+workshop_bonus)
        if branch:m.gain_branch(db,p,branch,amount)
        xp.append(f'+{amount} {skill_name(sk)} XP')
    life=m.life_state(db,p);m.spend_life_for_action(life,'make')
    p.actions+=1;p.successes+=1;m.craft_record(db,p,key);db.commit()
    return ('✅ CRAFTING COMPLETE\n\nOUTPUT\n'+ '\n'.join(f"• {item_label(k)} ×{v}" for k,v in r['outputs'].items())+
      '\n\nUSED\n'+(m.requirement_text(r['inputs']) or 'No ingredients')+'\n\nPRACTICE\n'+', '.join(xp)+
      '\n\nWorkshop: '+station(r)+(' · Owned workstation: +1 practice per trained skill included.' if workshop_bonus else '')+'\n−2 Energy · −1 Nutrition · −1 Comfort')

def gather(m,db,p,key,provider):
    if key not in GATHER:return '🛑 Choose a natural resource from /gather. Manufactured parts must be crafted.'
    life=m.life_state(db,p);blocked=m.task_need_gate(db,p,'make',provider,life)
    if blocked:return blocked
    wait=m.check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ Gathering ready in {wait}s. Nothing spent.'
    cfg=GATHER[key];m.material_change(db,p,key,cfg['amount']);xp=m.gain_skill(p,'extraction',1);m.gain_branch(db,p,cfg['branch'],xp)
    m.spend_life_for_action(life,'make');p.actions+=1;p.successes+=1;db.commit()
    return f"✅ GATHERING COMPLETE\n\nOUTPUT\n• {ITEMS[key]['name']} ×{cfg['amount']}\n\nPRACTICE\n+{xp} Harvesting and {cfg['branch'].replace('_',' ').title()} XP\n−2 Energy · −1 Nutrition · −1 Comfort"

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
USED_BY={k:[r for r in RECIPES if k in RECIPES[r]['inputs']] for k in ACTIVE}
SOURCE_KEYS={v['source']:k for k,v in ITEMS.items()}
def source_key(s):return SOURCE_KEYS[s]
SEED_CROPS={'CORN':'GMT_PRODUCT_FOOD_CORN','PUMPKIN':'GMT_PRODUCT_FOOD_PUMPKIN',
 'TOMATO':'GMT_PRODUCT_FOOD_TOMATO','FLAXA':'GMT_MATERIAL_RAW_FLAXA','WHEAT':'GMT_MATERIAL_RAW_WHEAT',
 'HERBS':'GMT_MATERIAL_RAW_HERBS','LUMBER':'GMT_MATERIAL_RAW_LUMBER'}

# Keep individual machine names, while matching the extraction tag alias.
def machine_tags(key):
    tags=set(ITEMS[key]['tags'])
    if 'CAT_SUB_MACHINES_EXTRACTORS' in ITEMS[key]['categories']:tags.add('TAG_MACHINE_EXTRACTOR')
    return tags
MACHINE_RECIPES={k:[rid for rid,r in RECIPES.items() if machine_tags(k)&set(r['machines'])] for k in ACTIVE if CATEGORY[k]=='machines'}

def purpose(key):
    """The same rule drives descriptions, ownership suggestions and execution."""
    v=ITEMS[key];cat=CATEGORY[key];src=v['source']
    if key in EDIBLE:return dict(mode='eat',label=f'Eat: +{nutrition(key)} Nutrition; consumes 1. Use /eat.',consume=True)
    if cat=='medicine':
        batches=[sum(r['inputs'].values())/r['outputs'][key] for r in RECIPES.values() if key in r['outputs']]
        units=max(1,min(8,math.ceil(min(batches,default=1))))
        return dict(mode='clinic',label=f'Supply clinic: consumes 1; +{units} shared Medicines, +1 Contribution.',consume=True,units=units)
    if cat=='seeds':
        output=source_key(SEED_CROPS[src.removeprefix('GMT_SEED_')])
        return dict(mode='plant',label=f"Garden batch: 1 seed + 1 Clean Water → 3 {ITEMS[output]['name']}; +1 Farming and Seed Cultivation XP.",consume=True,output=output)
    if src=='GMT_MATERIAL_PROCESSED_WATER':return dict(mode='recover',label='Drink: consumes 1; +10 Energy, +10 Comfort.',consume=True,boost={'energy':10,'comfort':10})
    if src=='GMT_PRODUCT_TOOL_SCANNER_BATTERY':return dict(mode='ingredient',label='Scanner battery: consumed by /use Resource Scanner to find 2 Hematite Ore and earn Research XP.',consume=False)
    if src=='GMT_PRODUCT_TOOL_RESOURCE_SCANNER':return dict(mode='scan',label='Scan: keeps scanner; consumes 1 SEED Power Cell → 2 Hematite Ore, +1 Research XP. Costs work needs.',consume=False)
    if src=='DELIVERY_DRONE' or cat=='storage' or 'BACKPACK' in src:return dict(mode='pack',label='Pack delivery: keeps item; 1 personal Cargo → 2 shared Cargo, +1 Logistics XP. Costs work needs.',consume=False)
    if 'CAT_MAIN_VENDING_MACHINES' in v['categories']:return dict(mode='vend',label='Stock vending machine: keeps machine; 1 Crop → 1 SC, +1 Commerce XP. Costs work needs.',consume=False)
    if cat=='machines':return dict(mode='workshop',label='Own this workstation for +1 base practice per trained skill/branch on matching SEED recipes. Bonus capped at +1; machine kept. Needs/job modifiers still apply.',consume=False)
    if cat=='building' or src.endswith(('_MORTAR','_STONE_TILES')):return dict(mode='build',label='Build: consumes 1; +1 shared Infrastructure. Every 5 Infrastructure adds 1 housing space. Costs work needs.',consume=True)
    if cat=='beds':return dict(mode='recover',label='Rest: keeps item; +40 Energy, +25 Comfort, +5 Morale.',consume=False,boost={'energy':40,'comfort':25,'morale':5})
    if cat=='seating':return dict(mode='recover',label='Relax: keeps item; +20 Comfort, +10 Social.',consume=False,boost={'comfort':20,'social':10})
    if cat=='bathroom':return dict(mode='wash',label='Wash: keeps fixture; consumes 1 Clean Water; +30 Comfort, +5 Morale.',consume=False,boost={'comfort':30,'morale':5})
    if cat=='tables':return dict(mode='meal',label='Host meal: keeps table; consumes 1 Crop; +25 Social, +8 Morale.',consume=False,boost={'social':25,'morale':8})
    if cat=='clothing':return dict(mode='recover',label='Refresh outfit: keeps clothing; +15 Comfort, +5 Morale. No stacking passive bonus.',consume=False,boost={'comfort':15,'morale':5})
    if cat=='decor':return dict(mode='recover',label='Enjoy recreation or surroundings: keeps item; +12 Morale, +8 Social.',consume=False,boost={'morale':12,'social':8})
    if USED_BY[key]:return dict(mode='ingredient',label=f'Ingredient in {len(USED_BY[key])} recipe(s). /catalog shows what you can make with it.',consume=False)
    return dict(mode='research',label='Analyze surplus: consumes 1; +1 Research XP and +1 society Knowledge. Costs work needs.',consume=True)

PURPOSE={k:purpose(k) for k in ACTIVE}

def stock(m,db,p):
    if not p:return {}
    return {r.item:r.qty for r in db.execute(m.select(m.ExtraItem).where(m.ExtraItem.channel_id==p.channel_id,m.ExtraItem.canonical_uid==p.twitch_uid,m.ExtraItem.qty>0)).scalars()}

def category_choices():
    return [{'name':f'{label} ({sum(v==k for v in CATEGORY.values())})','value':k} for k,label in CATEGORIES.items()]

def filtered_keys(category='',owned=False,inventory=None,gather_only=False):
    keys=GATHER if gather_only else ACTIVE
    return sorted((k for k in keys if (not category or CATEGORY[k]==category) and (not owned or (inventory or {}).get(k,0)>0)),key=lambda k:(ITEMS[k]['name'].casefold(),k))

def recipe_category(key):return CATEGORY[next(iter(RECIPES[key]['outputs']))]

def recipe_menu(m,db,p,category,page=1):
    rows=sorted((k for k in RECIPES if recipe_category(k)==category),key=lambda k:(RECIPES[k]['name'].casefold(),k))
    count=len(rows);pages=max(1,math.ceil(count/8));page=max(1,min(int(page),pages));inv=stock(m,db,p)
    lines=[f'🟦 {CATEGORIES[category]} Recipes · {page}/{pages}',f'{count} recipes · every recipe is included across these pages.','']
    for key in rows[(page-1)*8:page*8]:
        r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
        ready=all(inv.get(k,0)>=n for k,n in r['inputs'].items()) and level_for(m,db,p,req)>=required_level(r)
        lines += [f"{'✅' if ready else '🔒'} {item_label(next(iter(r['outputs'])))} ×{next(iter(r['outputs'].values()))}",f"  {skill_name(req)} Lv.{required_level(r)} · inspect with /catalog Item."]
    lines+=['',f'Choose Recipe to craft; Page {min(page+1,pages)} for more.','Choose Production Tree and Recipe for a free cost preview.']
    return '\n'.join(lines)

# Override the first release's flat browser. Every item stays reachable via pages.
def catalog(m,db,p,item='',page=1,owned=False,category=''):
    if category and category not in CATEGORIES:return '🛑 Choose a category from the list. Nothing spent.'
    inv=stock(m,db,p)
    if item:
        if item not in ACTIVE:return '🛑 Choose an obtainable item from the catalog.'
        if category and CATEGORY[item]!=category:return 'ℹ️ This item is in '+CATEGORIES[CATEGORY[item]]+'. Change Category to inspect it.'
        v=ITEMS[item];lines=[f"🟦 {item_label(item)}",CATEGORIES[CATEGORY[item]],f"Owned: {inv.get(item,0)}",'', 'USE',PURPOSE[item]['label']]
        if PURPOSE[item]['mode'] not in {'eat','ingredient','workshop'}:lines+=['Select /use Item to perform this action. Recovery caps at 100. Item uses share a 20-second cooldown. XP values are base practice; needs and jobs may modify them.']
        lines+=['','HOW TO OBTAIN',source_hint(item)]
        if item not in GATHER:
            base,steps=acquisition_plan(item)
            plan=[f'Gather {item_label(k)}: {n} action(s).' for k,n in sorted(base.items())]
            plan += [f"Make {RECIPES[rid]['name']}: {n} batch(es) · {rid} · {skill_name(RECIPES[rid]['requirement'].get('Skill'))} Lv.{required_level(RECIPES[rid])}" for rid,n in steps]
            pages=max(1,math.ceil(len(plan)/6));plan_page=max(1,min(int(page),pages))
            lines+=['',f'ACQUISITION PLAN · {plan_page}/{pages} — for 1 item from scratch',*plan[(plan_page-1)*6:plan_page*6],
                    'Follow the steps in order; reuse inventory to reduce gathering. Surplus is kept. Change Page for more steps.',
                    'Skill locks: practice lower-level recipes in that skill or use /training. Community workshops are included.']
        made=[r for r in RECIPES.values() if item in r['outputs']]
        if made:
            lines+=['','MAKE IT']
            for r in made[:3]:lines += [f"• {r['name']} → {r['outputs'][item]}",m.requirement_text(r['inputs']) or 'Extraction; no ingredients',f"{skill_name(r['requirement'].get('Skill'))} Lv.{required_level(r)} · {station(r)}"]
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
        lines=['🟦 SEED Item Categories','Choose Category to see every item in that group.','']
        for key,label in CATEGORIES.items():lines.append(f"• {label}: {len(filtered_keys(key,owned,inv))}")
        lines+=['','Owned filters to your inventory. Page shows the rest of a category.','/make uses the same SEED category filters. /use shows owned usable items.']
        return '\n'.join(lines)
    rows=filtered_keys(category,owned,inv);pages=max(1,math.ceil(len(rows)/12));page=max(1,min(int(page),pages))
    lines=[f'🟦 {CATEGORIES[category]} · {page}/{pages}',f'{len(rows)} '+('owned item types' if owned else 'items total')+' · 12 per page','']
    lines += [f"• {item_label(k)} ×{inv.get(k,0)}" for k in rows[(page-1)*12:page*12]] or ['No owned items in this category.']
    lines+=['',f'Keep Category selected; change Page (1–{pages}) to see all items.','Select Item for its use, costs and crafting ingredients.']
    return '\n'.join(lines)

def choices(m,db,p,query='',gather_only=False,category='',owned=False,usable=False):
    inv=stock(m,db,p);keys=filtered_keys(category,owned,inv,gather_only)
    if usable:keys=[k for k in keys if PURPOSE[k]['mode'] not in {'ingredient','workshop'}]
    return [(f"{item_label(k)} ×{inv.get(k,0)}"+((' — '+PURPOSE[k]['label']) if usable else ''),k) for k in keys]

def use_menu(m,db,p,category='',page=1):
    inv=stock(m,db,p);keys=[k for k in filtered_keys(category,True,inv) if PURPOSE[k]['mode'] not in {'ingredient','workshop'}]
    pages=max(1,math.ceil(len(keys)/6));page=max(1,min(int(page),pages))
    lines=[f'🎒 ITEM MENU — SEED Uses · {page}/{pages}',f'{len(keys)} owned usable item types','']
    for key in keys[(page-1)*6:page*6]:lines += [f"• {ITEMS[key]['name']} ×{inv[key]}",PURPOSE[key]['label']]
    if not keys:lines+=['No usable SEED items owned in this category.']
    return '\n'.join(lines+['','Select Category to filter; change Page to see every item. Select Item to use it.','Ingredients are used by /make. Owned machines improve matching recipe practice automatically.'])

def use(m,db,p,key,provider):
    if key not in ACTIVE:return '🛑 Unknown item. Nothing spent.'
    cfg=PURPOSE[key];mode=cfg['mode'];name=item_label(key)
    if m.material_amount(db,p,key)<1:return f'🛑 You do not own {name}. Nothing spent.'
    if mode in {'ingredient','workshop','eat'}:return 'ℹ️ '+cfg['label']+' Nothing spent.'
    water=source_key('GMT_MATERIAL_PROCESSED_WATER');cost={key:1} if cfg['consume'] else {}
    if mode in {'plant','wash'}:cost[water]=cost.get(water,0)+1
    if mode=='scan':cost[source_key('GMT_PRODUCT_TOOL_SCANNER_BATTERY')]=1
    if mode in {'meal','vend'}:cost['crops']=1
    if mode=='pack':cost['cargo']=1
    life=m.life_state(db,p)
    if cfg.get('boost') and not any(getattr(life,f)<100 for f in cfg['boost']):return 'ℹ️ These needs are already full. Nothing spent; no cooldown started.'
    work=mode in {'plant','scan','pack','vend','build','research'}
    if work:
        blocked=m.task_need_gate(db,p,'make',provider,life)
        if blocked:return blocked
    missing=m.craft_missing_materials(db,p,cost)
    if missing:return '🛑 Still needed: '+', '.join(missing)+'. Nothing spent.'
    wait=m.check_cooldown(db,p,'seed_use')
    if wait:return f'⏳ Item use ready in {wait}s. Nothing spent.'
    for k,n in cost.items():m.material_change(db,p,k,-n)
    changes=[]
    for field,amount in cfg.get('boost',{}).items():
        before=getattr(life,field);setattr(life,field,min(100,before+amount));changes.append(f'{field.title()} {before}→{getattr(life,field)}')
    shared=m.colony_state(db,p.channel_id)
    if mode=='clinic':shared.medicines+=cfg['units'];p.contribution+=1;changes+=[f"+{cfg['units']} shared Medicines",'+1 Contribution']
    if mode=='plant':
        m.material_change(db,p,cfg['output'],3);xp=m.gain_skill(p,'cultivation',1);m.gain_branch(db,p,'seed_cultivation',xp)
        changes += [f"+3 {ITEMS[cfg['output']]['name']}",f'+{xp} Farming and Seed Cultivation XP']
    if mode=='scan':
        m.material_change(db,p,source_key('GMT_MATERIAL_ORE_HEMATITE'),2);xp=m.gain_skill(p,'research',1);changes += ['+2 Hematite Ore',f'+{xp} Research XP']
    if mode=='pack':shared.cargo+=2;xp=m.gain_skill(p,'logistics',1);changes += ['+2 shared Cargo',f'+{xp} Logistics XP']
    if mode=='vend':p.sc+=1;xp=m.gain_skill(p,'commerce',1);changes += ['+1 SC',f'+{xp} Commerce XP']
    if mode=='build':
        before=shared.infrastructure;shared.infrastructure+=1;housing=shared.infrastructure//5-before//5;shared.housing+=housing;changes+=['+1 shared Infrastructure']
        if housing:changes+=['+1 housing space']
    if mode=='research':
        m.society(db,p.channel_id).knowledge+=1;xp=m.gain_skill(p,'research',1);changes += ['+1 society Knowledge',f'+{xp} Research XP']
    if work:m.spend_life_for_action(life,'make');changes+=['−2 Energy · −1 Nutrition · −1 Comfort']
    p.actions+=1;p.successes+=1;db.commit()
    return '\n'.join([f'✅ {name} — Complete','','RESULT',*['• '+x for x in changes],'','USED',m.requirement_text(cost) if cost else 'No items consumed.',*(['Selected durable item kept.'] if not cfg['consume'] else [])])
