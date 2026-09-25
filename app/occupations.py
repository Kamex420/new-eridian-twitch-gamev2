
"""Original New Eridian occupation design, not proprietary SEED mechanics."""
OCCUPATIONS={
 "farmer":dict(competencies=("cultivation","environmental"), task="harvest", output="food", dependency="water", trait="patient"),
 "miner":dict(competencies=("extraction",), task="mine", output="ore", dependency="infrastructure", trait="resilient"),
 "technician":dict(competencies=("fabrication","infrastructure"), task="work", output="components", dependency="ore", trait="methodical"),
 "researcher":dict(competencies=("research","environmental"), task="research", output="knowledge", dependency="components", trait="curious"),
 "courier":dict(competencies=("logistics",), task="cargo", output="cargo", dependency="components", trait="cooperative"),
 "explorer":dict(competencies=("frontier",), task="explore", output="knowledge", dependency="medicines", trait="adventurous"),
 "merchant":dict(competencies=("commerce",), task="market", output="treasury", dependency="cargo", trait="sociable"),
}
OCCUPATIONS["cultivator"]=OCCUPATIONS["farmer"]
def matches(job,skill):return skill in OCCUPATIONS.get(job,{}).get("competencies",())
def occupation_task(job):return OCCUPATIONS.get(job,{}).get("task","work")

from .seed_skills import NEW_JOBS
for key,(label,skill,task) in NEW_JOBS.items():
    OCCUPATIONS[key]=dict(competencies=(skill,),task=task,output=skill,dependency="supplies",trait="methodical")
