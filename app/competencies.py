
"""Preserve earned XP with faster, shared skill thresholds; accumulate fractional practice."""
FIELDS={"cultivation":"farm_xp","environmental":"environmental_xp","extraction":"mining_xp","fabrication":"fabrication_xp","infrastructure":"infrastructure_xp","research":"research_xp","logistics":"delivery_xp","frontier":"explore_xp","commerce":"commerce_xp"}
FIELDS.update(cooking="cooking_xp",medicine="medicine_xp",emergency="emergency_xp")
def level(x):
    for i,bound in enumerate((5,12,22,35),1):
        if x<bound:return i
    return 5+(x-35)//15

def practice_gain(base, matching, living, project, quality=1.0):
    return max(.25,base*(1+.25*matching+.15*project)*living*quality)

def rank(x):
    lv=level(x)
    return "Specialist" if lv>=10 else "Proficient" if lv>=5 else "Practiced" if lv>=3 else "Apprentice"

def next_level_xp(x):
    return next((n for n in (5,12,22,35) if n>x),35+(max(0,x-35)//15+1)*15)
