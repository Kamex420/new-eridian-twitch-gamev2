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

def preview(m,db,p,key):
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    lines=[f"🛠️ {r['name']}", '', 'ONE BATCH',m.requirement_text(r['outputs']), '', 'MATERIALS']
    lines += [f"• {ITEMS[k]['name']}: {m.material_amount(db,p,k)}/{v}" for k,v in r['inputs'].items()] or ['• No ingredients; extraction uses your work cooldown.']
    lines += ['',f"SKILL · {skill_name(req)} Lv.{required_level(r)} · Yours: {level_for(m,db,p,req)}",f"WORKSHOP · {station(r)}",'Community workshop access is included.', '', 'Use /make and select this recipe to craft one batch.', 'Use /gather for natural materials; /catalog to look up ingredients.']
    return '\n'.join(lines)

def craft(m,db,p,key,provider):
    r=RECIPES[key];req=r['requirement'].get('Skill','SK_CRAFTING')
    if level_for(m,db,p,req)<required_level(r):return f"🔒 {r['name']} needs {skill_name(req)} Lv.{required_level(r)}. Train this branch with /training. Nothing spent."
    missing=m.craft_missing_materials(db,p,r['inputs'])
    if missing:return '🛑 Materials needed\n'+ '\n'.join('• '+s for s in missing)+'\nUse /gather for natural inputs or /catalog to find recipes.'
    wait=m.check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ Workshop ready in {wait}s. Nothing spent.'
    for k,v in r['inputs'].items():m.material_change(db,p,k,-v)
    for k,v in r['outputs'].items():m.material_change(db,p,k,v)
    # Keep Pharmacy practice separate from healing practice; a declared minigame rule.
    xp=[]
    for sk in dict.fromkeys(r['xp'].get('TrainedSkills') or [req]):
        if sk not in SKILLS:continue
        if sk=='SK_MEDICINE' and req=='SK_PHARMACY':continue
        main,branch=SKILLS[sk]
        amount=1 if branch else m.gain_skill(p,main,1)
        if branch:m.gain_branch(db,p,branch,amount)
        xp.append(f'+{amount} {skill_name(sk)} XP')
    life=m.life_state(db,p);m.spend_life_for_action(life,'make')
    p.actions+=1;p.successes+=1;m.craft_record(db,p,key);db.commit()
    return ('✅ CRAFTING COMPLETE\n\nOUTPUT\n'+ '\n'.join(f"• {ITEMS[k]['name']} ×{v}" for k,v in r['outputs'].items())+
      '\n\nUSED\n'+(m.requirement_text(r['inputs']) or 'No ingredients')+'\n\nPRACTICE\n'+', '.join(xp)+
      '\n\nWorkshop: '+station(r)+'\n−2 Energy · −1 Nutrition · −1 Comfort')

def gather(m,db,p,key,provider):
    if key not in GATHER:return '🛑 Choose a natural resource from /gather. Manufactured parts must be crafted.'
    life=m.life_state(db,p);blocked=m.task_need_gate(db,p,'make',provider,life)
    if blocked:return blocked
    wait=m.check_cooldown(db,p,'seed_work')
    if wait:return f'⏳ Gathering ready in {wait}s. Nothing spent.'
    cfg=GATHER[key];m.material_change(db,p,key,cfg['amount']);xp=m.gain_skill(p,'extraction',1);m.gain_branch(db,p,cfg['branch'],xp)
    m.spend_life_for_action(life,'make');p.actions+=1;p.successes+=1;db.commit()
    return f"✅ GATHERING COMPLETE\n\nOUTPUT\n• {ITEMS[key]['name']} ×{cfg['amount']}\n\nPRACTICE\n+{xp} Harvesting and {cfg['branch'].replace('_',' ').title()} XP\n−2 Energy · −1 Nutrition · −1 Comfort"

def catalog(m,db,p,item='',page=1,owned=False):
    if item:
        if item not in ACTIVE:return '🛑 Choose an item from the catalog suggestions.'
        v=ITEMS[item];lines=[f"🔵 {v['name']}",f"Owned: {m.material_amount(db,p,item)}",'',v['description'][:450]]
        if item in EDIBLE:lines+=['',f'FOOD · +{nutrition(item)} Nutrition with /eat.']
        if v['remedy']:lines+=['','Medical crafting supply. Clinical treatment is not simulated for this item.']
        if item in GATHER:lines+=['',f'GATHER · /gather resource:{v["name"]} yields 1.']
        rs=[(k,r) for k,r in RECIPES.items() if item in r['outputs']]
        if rs:
            lines+=['','RECIPES']
            for k,r in rs[:5]:
                lines += [f"• {r['name']} → {r['outputs'][item]} per batch",'  '+(m.requirement_text(r['inputs']) or 'Extraction; no ingredients'),f"  {skill_name(r['requirement'].get('Skill'))} Lv.{required_level(r)} · {station(r)}"]
            if len(rs)>5:lines.append('More variants: search Recipe in /make.')
        if not rs and item not in GATHER:lines+=['','Not obtainable in the current minigame.']
        lines+=['','Type the item name in /make Recipe; choose Production Tree to preview before spending.']
        return '\n'.join(lines)
    rows=[(k,v) for k,v in ITEMS.items() if k in ACTIVE and (not owned or m.material_amount(db,p,k)>0)]
    rows.sort(key=lambda x:(x[1]['name'].casefold(),x[0]));pages=max(1,math.ceil(len(rows)/12));page=max(1,min(int(page),pages))
    lines=[f'🔵 SEED Supplies · {page}/{pages}',f'{len(rows)} '+('owned items' if owned else 'items to discover'),'',*[f"• {v['name']} ×{m.material_amount(db,p,k)}" for k,v in rows[(page-1)*12:page*12]],'',
       '/catalog Item: search a name for ingredients and sources.', '/catalog Owned: True shows only your supplies.', '/gather collects resources. /make crafts a batch.', '/eat lists food you own.']
    return '\n'.join(lines)

def choices(m,db,p,query='',gather_only=False):
    keys=GATHER if gather_only else ACTIVE
    return [(f"{ITEMS[k]['name']} · owned {m.material_amount(db,p,k) if p else 0}",k) for k in sorted(keys,key=lambda k:(ITEMS[k]['name'].casefold(),k))]
