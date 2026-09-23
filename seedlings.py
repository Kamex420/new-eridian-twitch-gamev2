"""Priority selection is pure: polling never performs work or awards resources."""
from .occupations import occupation_task
from .needs import urgency, mood

def priority(life,job,project=False,goal="settlement",preferred="games"):
    if life.nutrition<20:return "eat","Critical hunger: seek food"
    if life.energy<20:return "sleep","Critical fatigue: recover"
    if life.comfort<20:return "sleep","Habitat discomfort: recover"
    if life.morale<25:return "relax","Low morale: recovery before work"
    if life.social<35:return "games","Restore cooperation and social wellbeing"
    if goal=="recovery" and min(life.energy,life.comfort)<80:return "sleep","Personal recovery goal"
    if job not in {"settler",""}:return occupation_task(job),"Occupation routine"
    if project:return "project","Support the colony project"
    return preferred,"Personal leisure"

def describe(life,job,project=False,goal="settlement",preferred="games"):
    task,reason=priority(life,job,project,goal,preferred)
    return {"mood":mood(life),"urgency":urgency(life),"next_action":task,"reason":reason}
