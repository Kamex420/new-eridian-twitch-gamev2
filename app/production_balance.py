"""New Eridian batch sizes and workshop efficiency, separate from source data.

Demand is measured from ingredient quantities and distinct consuming recipes.
Extraction without inputs keeps its original yield, including rare ore rules.
"""

BULK_CATEGORIES={'raw','processed','parts','seeds','medicine'}

def apply_batches(recipes,categories):
    demand={}
    for recipe in recipes.values():
        for key,amount in recipe['inputs'].items():
            count,largest=demand.get(key,(0,0))
            demand[key]=(count+1,max(largest,amount))
    for recipe in recipes.values():
        if not recipe['inputs']:continue
        for key in recipe['outputs']:
            count,largest=demand.get(key,(0,0))
            recipe['outputs'][key]=(15 if largest>=20 or count>=20 else 10 if largest>=5 or count>=5 else 5) if categories[key] in BULK_CATEGORIES else 1
    return demand


def outputs_at(s,cp,recipe,tag):
    row=s.RECIPES[recipe]
    bonus=2*(cp.STATIONS[tag]['tier']-1)
    return {key:min(20,n+bonus) if row['inputs'] and s.BATCH_CATEGORIES[key] in BULK_CATEGORIES else n for key,n in row['outputs'].items()}


def selected_station(db,p,recipe):
    from . import crafting_progression, seed_content
    cp=crafting_progression;s=seed_content
    available=[tag for tag in cp.tags(recipe) if cp.STATIONS[tag]['tier']<=cp.personal_tier(db,p) and cp.has_access(db,p,tag)]
    if not available:return None
    return max(available,key=lambda tag:(sum(outputs_at(s,cp,recipe,tag).values()),cp.STATIONS[tag]['tier'],tag))


def current_outputs(db,p,recipe):
    from . import crafting_progression, seed_content
    tag=selected_station(db,p,recipe)
    return outputs_at(seed_content,crafting_progression,recipe,tag) if tag else dict(seed_content.RECIPES[recipe]['outputs'])


def quote(db,p,recipe):
    from . import seed_content
    from .game.rules import SEED_INDUSTRIES
    row=seed_content.RECIPES[recipe]
    output=current_outputs(db,p,recipe)
    sale=sum(SEED_INDUSTRIES.get(k,{}).get('sell',0)*n for k,n in output.items())
    inputs=sum(SEED_INDUSTRIES.get(k,{}).get('sell',0)*n for k,n in row['inputs'].items())
    return f'NPC sale: {sale} SC per batch · input resale value: {inputs} SC · added value: {sale-inputs:+} SC.'


def configure_market():
    """Every catalog item has buyback; buy/sell spread prevents instant resale profit."""
    from . import crafting_progression, seed_content
    from .game.rules import SEED_INDUSTRIES
    for key in seed_content.ACTIVE:
        buy=crafting_progression.VALUES[key]
        sell=max(1,buy*7//10)
        buy=max(buy,sell+1)
        previous=SEED_INDUSTRIES.get(key,{})
        SEED_INDUSTRIES[key]=dict(buy=buy if previous else 0,sell=sell,
            category='rare' if key in crafting_progression.RARE else previous.get('category','seed'),
            purpose=seed_content.PURPOSE[key]['label'])
