"""Personal yields for related work options; values are per successful attempt.

Natural byproducts use existing catalog identities and supply chains. Better
field methods cost more Energy; specialist methods retain equipment/input gates.
Manufacturing and clinic recipes keep their distinct inputs and products.
"""
from . import seed_content as s

SEEDS='sd_1319108988'
PUMPKIN='sd_1290053542'
ALGAE='sd_139726655'
STONE='sd_1566791299'
HERBS='sd_2055185252'
LUMBER='sd_1000004'
CLAY='sd_1663615028'
COAL='sd_183031416'
BERRIES='sd_1624184172'
WATER='sd_817726320'
# (action, mode): (Energy cost, item quantities)
YIELDS={
 ('farm',''):(2,{'crops':1,SEEDS:1}),
 ('harvest',''):(3,{'crops':2,PUMPKIN:1,SEEDS:1}),
 ('water',''):(4,{'crops':3,WATER:1}),
 ('water','hydroponics'):(5,{'crops':4,ALGAE:1}),
 ('forage',''):(3,{BERRIES:2,HERBS:1}),
 ('research',''):(2,{STONE:1}),
 ('research','field_analysis'):(4,{STONE:2,HERBS:1}),
 ('spaceport',''):(2,{'cargo':1,LUMBER:1}),
 ('spaceport','expedite'):(4,{'cargo':2,LUMBER:2}),
 ('explore',''):(3,{STONE:1,BERRIES:1}),
 ('survey',''):(5,{STONE:2,CLAY:1,COAL:1}),
 ('business',''):(2,{'cargo':1}),
 ('businesscontract',''):(4,{'cargo':2,LUMBER:1}),
 ('market',''):(2,{'cargo':1}),
 ('market','analyze'):(4,{'cargo':2,LUMBER:1}),
}
GROUPS=[ [('farm',''),('harvest',''),('water',''),('water','hydroponics')],
 [('research',''),('research','field_analysis')],
 [('spaceport',''),('spaceport','expedite')],
 [('explore',''),('survey','')],
 [('market',''),('market','analyze')],
 [('business',''),('businesscontract','')] ]
EQUIPMENT={('water','hydroponics'):'water_filter',('research','field_analysis'):'siro_sampler',
           ('survey',''):'sensor',('market','analyze'):'market_analyzer'}

def split(target):
    action,_,mode=target.partition('@')
    return action,mode

def config(action,mode=''):
    return YIELDS.get((action,mode))

def output_text(m,action,mode=''):
    cfg=config(action,mode)
    return ', '.join(f'{m.resource_name(k)} ×{n}' for k,n in cfg[1].items()) if cfg else ''

def requirements(m,action,mode=''):
    cfg=config(action,mode)
    if not cfg:return ''
    text=f'{cfg[0]} Energy per attempt; success yields '+output_text(m,action,mode)+'.'
    equipment=EQUIPMENT.get((action,mode))
    if equipment:text+=' Requires '+m.resource_name(equipment)+' (kept).'
    if mode=='expedite':text+=' Consumes 1 Power Cell on success.'
    return text

def alternatives(m,action,mode=''):
    group=next((g for g in GROUPS if (action,mode) in g),[])
    return '\n'.join(m.action_display_name(a,b)+': '+requirements(m,a,b) for a,b in group)

def apply(m,db,p,action,mode=''):
    cfg=config(action,mode)
    if not cfg:return ''
    for key,qty in cfg[1].items():m.material_change(db,p,key,qty)
    return ' Personal materials: '+output_text(m,action,mode)+'.'
