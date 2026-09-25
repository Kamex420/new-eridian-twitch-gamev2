"""HTTP and Discord adapters for the New Eridian game domain.

This module composes persistence, command handling and the ASGI application.
Domain modules under app/ own needs, item identities and queue transactions.
Stable routes and storage identifiers preserve existing clients and saves;
see docs/architecture.md for boundaries and compatibility decisions.
"""
import sys


import os, random, secrets, string, math, re, hashlib, json, urllib.request
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse, HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, UniqueConstraint, select, inspect, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./new_eridian.db")
GAME_NAME=os.getenv("GAME_NAME","New Eridian")
GAME_TITLE=os.getenv("GAME_TITLE","New Eridian v2")
ADMIN_KEY=os.getenv("ADMIN_KEY","change-me")
DISCORD_PUBLIC_KEY=os.getenv("DISCORD_PUBLIC_KEY","")
DISCORD_GAME_CHANNEL_ID=os.getenv("DISCORD_GAME_CHANNEL_ID","")
DISCORD_WORLD_ID=os.getenv("DISCORD_WORLD_ID","new-eridian")
AVESTA_DAY_SECONDS=max(3600,int(os.getenv("AVESTA_DAY_SECONDS","21600")))
DISCORD_MOD_ROLE_IDS={x.strip() for x in os.getenv("DISCORD_MOD_ROLE_IDS","").split(",") if x.strip()}
_OWNER_RAW=os.getenv("DISCORD_OWNER_USER_IDS","")
DISCORD_OWNER_USER_IDS=set(re.findall(r"\d{15,25}",_OWNER_RAW))
def parse_discord_emoji_map(raw):
    """
    DISCORD_EMOJI_MAP supports either:
      delivery=<:ne_delivery:123456789>
    or the easier shorthand:
      delivery=ne_delivery:123456789
    """
    result={}
    for entry in raw.split("|"):
        if "=" not in entry:continue
        key,custom=entry.split("=",1)
        key=key.strip().lower();custom=custom.strip()
        if not key or not custom:continue
        if (custom.startswith("<:") or custom.startswith("<a:")) and custom.endswith(">"):
            result[key]=custom
            continue
        # shorthand: emoji_name:emoji_id
        if re.fullmatch(r"[A-Za-z0-9_]{2,32}:\d{15,25}",custom):
            name,emoji_id=custom.split(":",1)
            result[key]=f"<:{name}:{emoji_id}>"
    return result
DISCORD_EMOJI_MAP=parse_discord_emoji_map(os.getenv("DISCORD_EMOJI_MAP",""))
DISCORD_EMOJI_KEYS=sorted(DISCORD_EMOJI_MAP)
def env_int(name,default,minimum=1):
    try:return max(minimum,int(os.getenv(name,str(default))))
    except (TypeError,ValueError):return default
AUTO_EVENTS_ENABLED=os.getenv("AUTO_EVENTS_ENABLED","true").lower() not in {"0","false","no","off"}
AUTO_EVENT_ACTIONS=env_int("AUTO_EVENT_ACTIONS",12)
AUTO_EVENT_MINUTES=env_int("AUTO_EVENT_MINUTES",10)
AUTO_EVENT_COOLDOWN_MINUTES=env_int("AUTO_EVENT_COOLDOWN_MINUTES",30)
from .db import engine, SessionLocal, Base
app=FastAPI(title="New Eridian v2 Unified API",version="7.0.0")

def now(): return datetime.now(timezone.utc)
def clean(v): return ((v or "Citizen").strip()[:30] or "Citizen")
def out(s):
    from .commands import context
    if context.get() is not None:return PlainTextResponse(s)
    b=s.encode()
    if len(b)<=380: return PlainTextResponse(s)
    b=b[:377]
    while True:
        try: return PlainTextResponse(b.decode()+"…")
        except UnicodeDecodeError: b=b[:-1]
def platform_response(provider,discord_text,twitch_text):
    return PlainTextResponse(discord_text) if provider=="discord" else out(twitch_text)

from .models import *
from .commands import command as colony_command, capture as colony_capture
from .settlement import state as colony_state, seedling as colony_seedling, tick as colony_tick, pressures as colony_pressures, produce as colony_produce
from .needs import productivity
from .competencies import practice_gain, level as competency_level
from . import item_identity
from . import seed_content as seed_content
from . import crafting_progression as crafting_progression
from .seed_skills import LABELS as SEED_LABELS, HUBS as SEED_HUBS, TASKS as SEED_TASKS, TREE as SEED_TREE, NEW_JOBS, NEW_SPECS, LEGACY_BRANCH, CRAFT_PRACTICE
from .models import SkillBranch
from .occupations import matches as occupation_matches
from .seedlings import describe as routine_description
from .progression import announce
from sqlalchemy.orm import object_session


Base.metadata.create_all(engine)

from .migrations import migrate_schema
migrate_schema()

def backfill_account_links():
    """Protect accounts linked before v5.2 with the new one-to-one ledger."""
    with SessionLocal() as db:
        rows=db.execute(select(Identity).where(Identity.provider=="discord").order_by(Identity.id)).scalars().all()
        for row in rows:
            if row.canonical_uid.startswith("discord:"):continue
            by_discord=db.execute(select(AccountLink).where(AccountLink.channel_id==row.channel_id,AccountLink.discord_uid==row.provider_uid)).scalar_one_or_none()
            by_twitch=db.execute(select(AccountLink).where(AccountLink.channel_id==row.channel_id,AccountLink.twitch_uid==row.canonical_uid)).scalar_one_or_none()
            if not by_discord and not by_twitch:db.add(AccountLink(channel_id=row.channel_id,twitch_uid=row.canonical_uid,discord_uid=row.provider_uid))
        db.commit()

backfill_account_links()

JOBS={
# Keep the legacy key so existing citizens retain their profession after the
# Keep old stored profession values compatible with the new Farmer label.
"cultivator":("Farmer",{"farm","harvest","water","forage"}),
"farmer":("Farmer",{"farm","harvest","water","forage"}),
"miner":("Miner",{"mine","rare","scavenge"}),
"technician":("Technician",{"make","craft","build","work","machine","repair","project"}),
"researcher":("Researcher",{"research","scan"}),
"courier":("Courier",{"cargo","delivery","spaceport"}),
"explorer":("Explorer",{"explore","survey"}),
"merchant":("Merchant",{"market","business","businesscontract","businessinvest"})
}
EVENTS={
"siro":{"name":"Siro Bloom","emoji":"☣️","action":"research","primary":"research","support":"environmental","goal":10,"minutes":20,"penalty":{"reputation":5,"knowledge":3},"reward":{"knowledge":8,"reputation":5},"objective":"Contain the Siro bloom"},
"food":{"name":"Food Crisis","emoji":"🌾","action":"harvest","primary":"cultivation","support":"environmental","goal":12,"minutes":20,"penalty":{"food":8,"reputation":3},"reward":{"food":10,"reputation":4},"objective":"Stabilize New Eridian's food stores"},
"mining":{"name":"Mining Boom","emoji":"⛏️","action":"mine","primary":"extraction","support":"logistics","goal":12,"minutes":20,"penalty":{"materials":6,"treasury":5},"reward":{"materials":10,"treasury":5},"objective":"Secure the exposed ore seam"},
"delivery":{"name":"Delivery Surge","emoji":"🦆","action":"delivery","primary":"logistics","support":"commerce","goal":8,"minutes":20,"penalty":{"treasury":8,"reputation":3},"reward":{"treasury":10,"reputation":5},"objective":"Clear the delivery backlog"},
"market":{"name":"Market Boom","emoji":"🏪","action":"market","primary":"commerce","support":"logistics","goal":10,"minutes":20,"penalty":{"treasury":12},"reward":{"treasury":15},"objective":"Meet market demand"},
"water":{"name":"Water Treatment Emergency","emoji":"💧","action":"water","primary":"environmental","support":"infrastructure","goal":10,"minutes":18,"penalty":{"food":6,"development":4},"reward":{"food":8,"development":6},"objective":"Restore clean-water flow"},
"machine":{"name":"Infrastructure Breakdown","emoji":"🔧","action":"repair","primary":"infrastructure","support":"fabrication","goal":10,"minutes":18,"penalty":{"development":7,"materials":5},"reward":{"development":9,"materials":6},"objective":"Repair the failed systems"},
"spaceport":{"name":"Spaceport Rush","emoji":"🚀","action":"spaceport","primary":"logistics","support":"commerce","goal":8,"minutes":20,"penalty":{"treasury":10,"reputation":4},"reward":{"treasury":12,"reputation":6},"objective":"Process the Spaceport rush"}
}

ACTION_SKILLS={
    "farm":"cultivation","harvest":"cultivation","forage":"cultivation",
    "water":"environmental","scan":"environmental",
    "mine":"extraction","rare":"extraction","scavenge":"extraction",
    "craft":"fabrication","machine":"fabrication","work":"fabrication",
    "repair":"infrastructure","project":"infrastructure","build":"infrastructure",
    "research":"research",
    "cargo":"logistics","delivery":"logistics","spaceport":"logistics",
    "explore":"frontier","survey":"frontier",
    "market":"commerce","business":"commerce","businesscontract":"commerce","businessinvest":"commerce",
}
ACTION_COOLDOWNS={action_name:5 for action_name in (*ACTION_SKILLS,"eat","sleep")}
ACTION_COOLDOWNS.update({"hi":20,"hangout":60,"relax":30,"walk":20,"games":30,"hobby":30})
SKILL_LABELS=dict(SEED_LABELS)
SKILL_ACTIONS={
    "cultivation":["harvest","farm","forage"],"environmental":["water","scan"],
    "extraction":["mine","scavenge","rare"],"fabrication":["work","machine","craft"],
    "infrastructure":["repair","project"],"research":["research"],
    "logistics":["cargo","spaceport","delivery"],"frontier":["explore","survey"],
    "commerce":["businesscontract","market","business"],
}
SPECIALIZATIONS={
    "cultivation":{"crop_geneticist":"Crop Geneticist","hydroponics_operator":"Hydroponics Operator"},
    "environmental":{"water_specialist":"Water Systems Specialist","biosphere_warden":"Biosphere Warden"},
    "extraction":{"deep_core_prospector":"Deep-Core Prospector","rare_materials_surveyor":"Rare Materials Surveyor"},
    "fabrication":{"precision_fabricator":"Precision Fabricator","machine_integrator":"Machine Integrator"},
    "infrastructure":{"habitat_engineer":"Habitat Engineer","utility_architect":"Utility Architect"},
    "research":{"siro_analyst":"Siro Analyst","materials_researcher":"Materials Researcher"},
    "logistics":{"spaceport_coordinator":"Spaceport Coordinator","delivery_fleet_operator":"Delivery Fleet Operator"},
    "frontier":{"pathfinder":"Avesta Pathfinder","field_surveyor":"Frontier Field Surveyor"},
    "commerce":{"market_broker":"Market Broker","business_steward":"Business Steward"},
}
# Keep old action and XP keys for saved characters and Twitch routes.
SPECIALIZATIONS.update(NEW_SPECS)
for _key,_task in SEED_TASKS.items():
    ACTION_SKILLS[_key]=_task['skill']
    ACTION_COOLDOWNS[_key]=5
    SKILL_ACTIONS.setdefault(_task['skill'],[]).append(_key)
for _key,(_label,_skill,_routine) in NEW_JOBS.items():
    JOBS[_key]=(_label,{a for a,sk in ACTION_SKILLS.items() if sk==_skill}|({'make'} if _skill in {'cooking','fabrication','infrastructure','environmental'} else set()))
EVENTS.update({
 'fire':dict(name='Fire Emergency',emoji='🔥',action='train_fire_suppression',primary='emergency',support='medicine',goal=10,minutes=18,penalty={'development':6,'food':4},reward={'development':8,'reputation':5},objective='Contain the fire and support the clinic'),
 'clinic':dict(name='Clinic Supply Shortage',emoji='🩺',action='train_pharmacy',primary='medicine',support='cooking',goal=10,minutes=18,penalty={'reputation':4,'food':4},reward={'knowledge':6,'reputation':5},objective='Supply medicines and nutritious food')
})
SOCIETY_TIERS=[("Outpost",0,0),("Settlement",300,1),("Township",900,1),("City",2400,2),("Regional Hub",6000,3)]
PART_RECIPES={
    "component":{"ore":1},
    "biofiber":{"crops":2},
    "alloy_plate":{"ore":2},
    "circuit_board":{"components":1,"rare_ore":1},
    "power_cell":{"components":2,"cargo":1},
    "sealant":{"crops":1,"components":1},
    "precision_lens":{"rare_ore":1,"alloy_plate":1},
}
PART_EFFECTS={
    "component":"Standard mechanical Component used throughout equipment assembly",
    "biofiber":"Agricultural composite used in packs, filters, and cargo equipment",
    "alloy_plate":"Refined structure used in tools, machinery, and protective equipment",
    "circuit_board":"Control electronics used in scanners, research gear, and commerce equipment",
    "power_cell":"Cargo-fed energy storage used in logistics and frontier equipment",
    "sealant":"Crop-based industrial seal used in habitats, filters, and repair equipment",
    "precision_lens":"Rare-material optics used in scanners and advanced research equipment",
}
CRAFT_OUTPUT_KEYS={"component":"components"}
RECIPES={
    "toolkit":{"alloy_plate":1,"components":1},
    "sensor":{"circuit_board":1,"precision_lens":1},
    "ration":{"crops":2},
    "crate":{"biofiber":1,"alloy_plate":1},
    "water_filter":{"biofiber":1,"sealant":1,"components":1},
    "siro_sampler":{"circuit_board":1,"precision_lens":1,"components":1},
    "duck_crate":{"biofiber":2,"alloy_plate":1,"sealant":1},
    "spaceport_manifest":{"circuit_board":1,"power_cell":1,"biofiber":1},
}
RECIPE_TIERS={"toolkit":0,"sensor":0,"ration":0,"crate":0,"water_filter":1,"siro_sampler":2,"duck_crate":3,"spaceport_manifest":4}
SKILL_EQUIPMENT={"environmental":"water_filter","research":"siro_sampler","logistics":"duck_crate","commerce":"spaceport_manifest"}
ITEM_EFFECTS={
    "toolkit":"+2 percentage points to the success chance for Crafting/Infrastructure; keep one",
    "sensor":"+2 percentage points to the success chance for Extraction/Research/Frontier; keep one",
    "crate":"+1 SC on successful Logistics/Commerce actions; keep one",
    "ration":"Eat for +3 percentage points to the success chance for 10 minutes; time stacks",
    "water_filter":"+2 percentage points to the Environmental success chance; keep one",
    "siro_sampler":"+2 percentage points to the Research success chance; keep one",
    "duck_crate":"+2 percentage points to the Logistics success chance; keep one",
    "spaceport_manifest":"+2 percentage points to the Commerce success chance; keep one",
}
UNIQUE_CORE_ITEMS=set(RECIPES)-{"ration"}

QUALITY_TIERS={
    "Crude":{"skill":.01,"special":.00},
    "Standard":{"skill":.02,"special":.02},
    "Refined":{"skill":.03,"special":.04},
    "Precision":{"skill":.04,"special":.07},
    "Masterwork":{"skill":.05,"special":.10},
}

QUALITY_RECIPES={
    # Agriculture
    "cultivator":{"name":"Field Hoe","category":"agriculture","cost":{"ore":2,"components":1},"skills":{"cultivation":1},"special":"crop yield"},
    "soil_scanner":{"name":"Soil Scanner","category":"agriculture","cost":{"components":2,"rare_ore":1},"skills":{"cultivation":1,"research":1},"special":"crop yield"},
    "irrigation_controller":{"name":"Irrigation Controller","category":"agriculture","cost":{"components":3,"crops":1},"skills":{"cultivation":1,"environmental":1},"special":"Agriculture/Irrigation success"},
    "cultivation_rig":{"name":"Agriculture Rig","category":"agriculture","cost":{"components":4,"rare_ore":1},"skills":{"cultivation":2},"special":"Farming XP"},

    # Extraction
    "mining_pick":{"name":"Reinforced Mining Pick","category":"extraction","cost":{"ore":2,"components":1},"skills":{"extraction":1},"special":"mining success"},
    "ore_scanner":{"name":"Ore Scanner","category":"extraction","cost":{"components":2,"rare_ore":1},"skills":{"extraction":1,"research":1},"special":"rare-find chance"},
    "reinforced_drill":{"name":"Reinforced Drill","category":"extraction","cost":{"components":4,"rare_ore":1},"skills":{"extraction":2},"special":"material yield"},
    "geological_analyzer":{"name":"Geological Analyzer","category":"extraction","cost":{"components":4,"rare_ore":2},"skills":{"extraction":1,"research":2},"special":"rare-find chance"},

    # Crafting / Infrastructure
    "precision_tools":{"name":"Precision Tools","category":"fabrication","cost":{"ore":2,"components":2},"skills":{"fabrication":2},"special":"craft quality"},
    "assembly_bench":{"name":"Portable Assembly Bench","category":"fabrication","cost":{"components":4,"rare_ore":1},"skills":{"fabrication":2,"infrastructure":1},"special":"Crafting XP"},
    "repair_kit":{"name":"Advanced Repair Kit","category":"infrastructure","cost":{"ore":1,"components":2},"skills":{"infrastructure":1},"special":"repair success"},
    "structural_scanner":{"name":"Structural Scanner","category":"infrastructure","cost":{"components":3,"rare_ore":1},"skills":{"infrastructure":1,"research":1},"special":"Infrastructure Repair success"},
    "emergency_patch_kit":{"name":"Emergency Patch Kit","category":"infrastructure","cost":{"components":3},"skills":{"infrastructure":1},"special":"event repair"},

    # Research / Environmental
    "field_microscope":{"name":"Field Microscope","category":"research","cost":{"components":2,"rare_ore":1},"skills":{"research":1},"special":"research success"},
    "sample_analyzer":{"name":"Sample Analyzer","category":"research","cost":{"components":3,"rare_ore":1},"skills":{"research":2},"special":"Research XP"},
    "siro_array":{"name":"Siro Detection Array","category":"research","cost":{"components":4,"rare_ore":2},"skills":{"research":2,"environmental":1},"special":"Siro-event success"},

    # Logistics / Commerce
    "cargo_harness":{"name":"Cargo Harness","category":"logistics","cost":{"components":2,"crops":1},"skills":{"logistics":1},"special":"delivery success"},
    "routing_tablet":{"name":"Routing Tablet","category":"logistics","cost":{"components":3,"rare_ore":1},"skills":{"logistics":2},"special":"delivery success"},
    "merchant_ledger":{"name":"Merchant Ledger","category":"commerce","cost":{"components":2,"crops":1},"skills":{"commerce":1},"special":"SC reward"},
    "market_analyzer":{"name":"Market Analyzer","category":"commerce","cost":{"components":4,"rare_ore":1},"skills":{"commerce":2,"research":1},"special":"market success"},

    # Frontier
    "survival_pack":{"name":"Survival Pack","category":"frontier","cost":{"components":2,"crops":2},"skills":{"frontier":1},"special":"exploration success"},
    "navigation_unit":{"name":"Navigation Unit","category":"frontier","cost":{"components":3,"rare_ore":1},"skills":{"frontier":2},"special":"survey success"},
    "expedition_kit":{"name":"Expedition Kit","category":"frontier","cost":{"components":4,"crops":2,"rare_ore":1},"skills":{"frontier":2,"logistics":1},"special":"exploration finds"},

    # Life
    "meal_kit":{"name":"Prepared Meal Kit","category":"life","cost":{"crops":3,"components":1},"skills":{},"special":"nutrition recovery"},
    "recreation_set":{"name":"Recreation Set","category":"life","cost":{"components":2,"crops":1},"skills":{},"special":"social/morale recovery"},
    "comfort_pack":{"name":"Habitat Comfort Pack","category":"life","cost":{"components":3,"crops":1},"skills":{},"special":"comfort recovery"},
}

# Every advanced equipment category now requires at least one manufactured part.
# Existing raw-resource costs remain, so parts add progression rather than
# replacing the value of farming, mining, fabrication, and delivery work.
QUALITY_RECIPES.update({
    'chef_tools':dict(name="Chef's Tools",category='life',cost={'components':2,'wood':1},skills={'cooking':1},special='Cooking success'),
    'medical_bag':dict(name='Medical Bag',category='life',cost={'cloth':2,'medicine':1},skills={'medicine':1},special='Medicine success'),
    'fire_gear':dict(name='Fire Safety Gear',category='life',cost={'cloth':2,'components':2},skills={'emergency':1},special='Emergency Response success'),
})
QUALITY_ASSEMBLY_PARTS={
    "agriculture":{"biofiber":1,"alloy_plate":1},
    "extraction":{"alloy_plate":1,"precision_lens":1},
    "fabrication":{"alloy_plate":1,"circuit_board":1},
    "infrastructure":{"alloy_plate":1,"sealant":1},
    "research":{"circuit_board":1,"precision_lens":1},
    "logistics":{"power_cell":1,"alloy_plate":1},
    "commerce":{"circuit_board":1,"biofiber":1},
    "frontier":{"precision_lens":1,"power_cell":1},
    "life":{"biofiber":1,"sealant":1},
}
for _recipe in QUALITY_RECIPES.values():
    for _part,_amount in QUALITY_ASSEMBLY_PARTS[_recipe["category"]].items():
        _recipe["cost"][_part]=_recipe["cost"].get(_part,0)+_amount

UNIQUE_QUALITY_ITEMS={key for key,recipe in QUALITY_RECIPES.items() if recipe["skills"]}

# Crafting is browsed by production stage, never by overlapping aptitude.
# An item's skill effects remain metadata on the item, not extra categories.
ACTION_COOLDOWNS["rare_prospect"]=20

RAW_MATERIAL_KEYS=("crops","ore","rare_ore","cargo","wood","water","stone","herbs")
BASIC_COMPONENT_KEYS=("component","biofiber","alloy_plate")
ADVANCED_COMPONENT_KEYS=("circuit_board","power_cell","sealant","precision_lens")
FINAL_PRODUCT_KEYS=tuple(RECIPES)+tuple(QUALITY_RECIPES)

CRAFT_STAGE_ITEMS={
    "raw_materials":RAW_MATERIAL_KEYS,
    "basic_components":BASIC_COMPONENT_KEYS,
    "advanced_components":ADVANCED_COMPONENT_KEYS,
    "final_products":FINAL_PRODUCT_KEYS,
}
CRAFT_CATEGORY_INFO={
    "raw_materials":("⛏️","Raw Materials","Gathered or delivered inputs. These are acquired, not fabricated."),
    "basic_components":("🔩","Basic Components","First-stage parts made directly from raw materials."),
    "advanced_components":("⚙️","Advanced Components","Specialized parts assembled from raw materials and basic components."),
    "final_products":("🧰","Final Products","Usable supplies and equipment assembled from manufactured components."),
}
CRAFT_CATEGORIES=tuple(CRAFT_CATEGORY_INFO)
CRAFT_BROWSE_OPTIONS=CRAFT_CATEGORIES+("tree",)
CRAFT_CATEGORY_ALIASES={
    "raw":"raw_materials","materials":"raw_materials",
    "components":"basic_components","basic":"basic_components",
    "advanced":"advanced_components","core":"final_products","products":"final_products","equipment":"final_products",
    # Old aptitude categories remain accepted, but all route to the one
    # canonical Final Products list instead of duplicating its items.
    "agriculture":"final_products","extraction":"final_products","fabrication":"final_products",
    "infrastructure":"final_products","research":"final_products","logistics":"final_products",
    "commerce":"final_products","frontier":"final_products","life":"final_products",
}

_catalog_items=[item for items in CRAFT_STAGE_ITEMS.values() for item in items]
assert len(_catalog_items)==len(set(_catalog_items)),"Every crafting item must belong to exactly one production stage"

LIFE_HOBBIES=("gardening","exploration","mechanics","research","games","rockwatching","cooking","collecting","trading","scanning")

WORLD_PHASES=[
    ("Morning",0,6,"🌅"),("Day",6,15,"☀️"),("Evening",15,19,"🌇"),("Night",19,24,"🌙")
]
WORLD_CONDITIONS=[
    ("clear_skies","Clear Avesta Skies","Routine operations are running smoothly."),
    ("good_growing","Good Growing Weather","Agriculture is especially productive today."),
    ("spore_drift","Light Siro Drift","Outdoor work carries a little more Siro exposure."),
    ("dust_winds","Dust Winds","Frontier and extraction work are harder, but unusual finds are more common."),
    ("busy_spaceport","Busy Spaceport","Logistics and commerce demand is elevated."),
    ("water_watch","Water Watch","Processing work matters more than usual."),
    ("quiet_cycle","Quiet Cycle","Social and recovery activities are especially effective."),
    ("sensor_noise","Sensor Noise","Research is challenging, but odd readings are turning up everywhere."),
]
DISTRICTS={
    "residential_ring":"Residential Ring",
    "agricultural_district":"Agricultural District",
    "industrial_ward":"Industrial Ward",
    "research_block":"Research Block",
    "market_concourse":"Market Concourse",
    "spaceport_quarter":"Spaceport Quarter",
    "frontier_edge":"Frontier Edge",
}
SHIFT_ROLES={
    "off_duty":"Off Duty","field_duty":"Field Duty","spaceport_duty":"Spaceport Duty",
    "lab_duty":"Lab Duty","maintenance":"Maintenance","trade_duty":"Trade Duty","survey_duty":"Survey Duty",
}
SHIFT_ROLES.update(kitchen_duty="Kitchen Duty",clinic_duty="Clinic Duty",safety_duty="Safety Duty")
PROJECTS=[
    ("greenhouse_expansion","Greenhouse Expansion",180,{"cultivation","environmental"}),
    ("spaceport_pad","Spaceport Pad Upgrade",225,{"logistics","infrastructure"}),
    ("research_annex","Research Annex",210,{"research","environmental"}),
    ("irrigation_grid","Irrigation Grid",200,{"environmental","infrastructure","cultivation"}),
    ("recreation_hall","Recreation Hall",160,{"commerce","infrastructure"}),
    ("deepway_terminal","Deepway Terminal",260,{"infrastructure","logistics"}),
]
PROJECTS.extend([
    ('community_kitchen','Community Kitchen',160,{'cooking','cultivation','fabrication'}),
    ('clinic_expansion','Clinic Expansion',180,{'medicine','infrastructure','environmental'}),
    ('fire_station','Fire Station',180,{'emergency','infrastructure','logistics'}),
])
PERSONAL_GOALS=[
    ("work_5","Complete 5 work actions",5,"action"),
    ("social_3","Complete 3 social activities",3,"social"),
    ("craft_1","Craft 1 item",1,"craft"),
    ("explore_4","Complete 4 Frontier actions",4,"frontier"),
    ("help_project_4","Contribute 4 times to the society project",4,"project"),
]
COLLECTIBLES={
    "strange_seed":"Strange Seed","mineral_sample":"Unusual Mineral Sample",
    "damaged_circuit":"Damaged Circuit Board","old_label":"Old Avesta Shipping Label",
    "siro_spore_vial":"Sealed Siro Spore Vial","machine_fragment":"Unknown Machine Fragment",
    "duck_tag":"Delivery Fleet Tag","normal_rock":"Definitely Normal Rock",
    "wild_fibers":"Wild Fibers","healthy_cutting":"Healthy Cutting",
}
NPCS=[
    ("Mara","a greenhouse technician"),
    ("Kepler","a Spaceport dispatcher"),
    ("Tamsin","a market clerk"),
    ("Orin","a maintenance worker"),
    ("Vela","a field researcher"),
    ("Nix","a frontier surveyor"),
]
DELIVERY_DUCKS=["Hueburt","Colora","Prisma","Pastelle","Asimov"]
RUMORS=[
    "Someone swears one of the greenhouse rows changed color overnight.",
    "A Spaceport worker says a cargo manifest arrived before the cargo did.",
    "There is an argument in the Market Concourse over whether Rocky counts as infrastructure.",
    "A researcher claims today's Siro readings are normal. Nobody asked what normal means.",
    "A delivery fleet tag was found nowhere near a delivery route.",
    "Someone at Deepway Terminal keeps leaving perfectly stacked stones on the benches.",
    "The Research Block logged a signal that repeats every seventeen minutes.",
    "A greenhouse worker insists a crop was harvested twice. The crop has declined to comment.",
]

DIRECTIVES=[
    ("food_reserve","Food Reserve",{"cultivation","environmental"},"food",8,"Strengthen New Eridian's food reserve."),
    ("material_drive","Material Drive",{"extraction","fabrication"},"materials",8,"Build a dependable stock of construction material."),
    ("maintenance_push","Maintenance Push",{"infrastructure","fabrication"},"development",8,"Clear the settlement maintenance queue."),
    ("knowledge_survey","Knowledge Survey",{"research","frontier","environmental"},"knowledge",8,"Turn field observations into useful records."),
    ("trade_window","Trade Window",{"commerce","logistics"},"treasury",8,"Use today's traffic to reinforce the treasury."),
    ("community_outreach","Community Outreach",{"logistics","commerce","infrastructure"},"reputation",8,"Show nearby settlements that New Eridian is reliable."),
]

DIRECTIVES.extend([
    ('clinic_stock','Clinic Stock',{'medicine','environmental'},'knowledge',8,'Supply the community clinic.'),
    ('kitchen_shift','Kitchen Shift',{'cooking','cultivation'},'food',8,'Prepare the community food reserve.'),
    ('fire_prevention','Fire Prevention',{'emergency','infrastructure'},'development',8,'Inspect and protect New Eridian buildings.'),
])
LORE_FRAGMENTS={
    "first_irrigation":"The oldest irrigation junction bears hand-cut marks from New Eridian's first growing cycle.",
    "rocky_marker":"A carefully stacked stone marker predates the path around it. Rocky's influence is disputed.",
    "silent_manifest":"A faded manifest lists a shipment whose origin field is completely blank.",
    "siro_chime":"A damaged sensor emits a soft chime seconds before local Siro readings change.",
    "duck_route":"A scratched fleet tag maps a shortcut no current dispatcher recognizes.",
    "deepway_echo":"Deepway maintenance notes mention an echo that answers in groups of three.",
    "greenhouse_song":"An early greenhouse log describes seedlings leaning toward an inaudible rhythm.",
    "avesta_glass":"A mineral sliver is transparent at sunset and opaque under laboratory light.",
    "old_eridian_stamp":"A supply seal carries an Eridian mark older than the settlement registry.",
    "borrowed_signal":"A receiver log labels one recurring transmission: NOT OURS—DO NOT REPLY.",
    "pastelle_note":"A dispatch note praises Pastelle for a delivery completed before it was assigned.",
    "quiet_foundation":"The Recreation Hall plans reserve an empty room with no listed purpose.",
}
ENCOUNTERS=[
    ("strange_seed","A strange seed is wedged into a drainage grate."),
    ("mineral_sample","A mineral sample catches the light in a way ordinary ore should not."),
    ("damaged_circuit","A damaged circuit board is half-buried beside a service path."),
    ("old_label","An old shipping label still has part of an unreadable destination code."),
    ("siro_spore_vial","A sealed sample vial is marked SIRO — FIELD USE ONLY."),
    ("machine_fragment","An unfamiliar machine fragment looks too clean to have been here long."),
    ("duck_tag","A scratched delivery fleet tag turns up under a cargo rail."),
    ("normal_rock","Rocky has provided a Definitely Normal Rock."),
]


HOBBIES={
    "gardening":("Gardening","cultivation"),"exploration":("Exploration","frontier"),
    "mechanics":("Mechanics","fabrication"),"research":("Research","research"),
    "games":("Games","commerce"),"rockwatching":("Rockwatching","extraction"),
    "cooking":("Cooking","cooking"),"collecting":("Collecting","frontier"),
    "trading":("Trading","commerce"),"scanning":("Scanning","environmental"),
}
COLLECTION_SETS={
    "field_naturalist":("Field Naturalist",{"strange_seed","wild_fibers","healthy_cutting","siro_spore_vial"},25,3,"Trail Naturalist"),
    "avesta_salvager":("Avesta Salvager",{"damaged_circuit","machine_fragment","old_label","duck_tag"},30,3,"Salvage Hound"),
    "rock_archive":("Rock Archive",{"mineral_sample","normal_rock"},15,2,"Rock Keeper"),
}
TITLE_DEFS={
    "new_eridian_local":"New Eridian Local","green_thumb":"Green Thumb","deep_delver":"Deep Delver",
    "machine_whisperer":"Machine Whisperer","siro_watcher":"Siro Watcher","duck_wranger":"Duck Wrangler",
    "trailwise":"Trailwise","market_regular":"Market Regular","community_builder":"Community Builder",
    "friend_of_eridian":"Friend of New Eridian","master_crafter":"Master Crafter","rock_keeper":"Rock Keeper",
    "trail_naturalist":"Trail Naturalist","salvage_hound":"Salvage Hound","fleet_friend":"Fleet Friend",
    "production_runner":"Production Runner","industry_coordinator":"Industry Coordinator","master_supplier":"Master Supplier",
}
STORY_ARCS=[
    {"key":"whispering_rows","name":"The Whispering Rows","text":"Unusual growth is spreading through greenhouse rows. Is it adaptation, contamination, or something stranger?","tracks":[("Farming Response",{"cultivation","environmental"}),("Research Response",{"research"}),("Supply Response",{"logistics","commerce"})],"goal":240},
    {"key":"signal_below","name":"The Signal Below","text":"A repeating signal is being detected beneath New Eridian infrastructure.","tracks":[("Investigate",{"research","frontier"}),("Stabilize",{"infrastructure","fabrication"}),("Secure Supply",{"extraction","logistics"})],"goal":240},
    {"key":"missing_manifest","name":"The Missing Manifest","text":"A Spaceport manifest references cargo nobody remembers ordering.","tracks":[("Trace Cargo",{"logistics","commerce"}),("Analyze Contents",{"research","environmental"}),("Search Routes",{"frontier","extraction"})],"goal":240},
    {"key":"siro_tide","name":"The Siro Tide","text":"Siro levels are rising in irregular waves around the settlement.","tracks":[("Contain",{"environmental","infrastructure"}),("Study",{"research"}),("Keep Society Moving",{"logistics","cultivation","commerce"})],"goal":240},
]
MARKET_BASE={"crops":2,"ore":3,"rare_ore":10,"components":5,"cargo":6}
SEED_INDUSTRIES={
    # key: fixed NPC buy price, fixed NPC sell price, and why it exists
    "crops":{"buy":4,"sell":1,"purpose":"Food, Biofiber, Sealant, and Rations"},
    "ore":{"buy":6,"sell":2,"purpose":"Components and Alloy Plates"},
    "rare_ore":{"buy":18,"sell":8,"purpose":"Circuit Boards and Precision Lenses"},
    "components":{"buy":10,"sell":4,"purpose":"Electronics, Power Cells, and equipment assembly"},
    "cargo":{"buy":12,"sell":5,"purpose":"Power Cells and delivery work"},
    "biofiber":{"buy":8,"sell":3,"purpose":"Packs, filters, crates, and life equipment"},
    "alloy_plate":{"buy":10,"sell":4,"purpose":"Tools, machinery, and structural equipment"},
    "circuit_board":{"buy":22,"sell":9,"purpose":"Scanners, research gear, and market equipment"},
    "power_cell":{"buy":28,"sell":11,"purpose":"Logistics and frontier equipment"},
    "sealant":{"buy":11,"sell":4,"purpose":"Filters, repairs, habitats, and life equipment"},
    "precision_lens":{"buy":26,"sell":10,"purpose":"Advanced scanners and research equipment"},
}

# New starter stock is buy-only; existing legacy buyback prices remain unchanged.
SEED_INDUSTRIES.update({k:dict(v) for k,v in crafting_progression.STARTER_MARKET.items()})
for _key,_price in {'wood':4,'water':4,'stone':4,'herbs':4,'planks':12,'preserved_food':8,'cut_stone':12,'cloth':20,'antiseptic':12,'storage_jar':12,'medicine':16}.items():
    SEED_INDUSTRIES[_key]=dict(buy=_price,sell=0,purpose='Training supply; see /training for its production route.',category='training')

# Seed Industries pays less than the NPC replacement cost of an order, so
# buying every input can never create an arbitrage loop. Citizens profit by
# gathering and manufacturing the inputs themselves.
PRODUCTION_ORDERS={
    "greenhouse_liners":{"name":"Greenhouse Liner Batch","cost":{"biofiber":2,"sealant":1},"tier":0,"purpose":"Reinforce greenhouse beds against Avesta dust."},
    "maintenance_stock":{"name":"Maintenance Stock","cost":{"alloy_plate":2,"components":1},"tier":0,"purpose":"Restock New Eridian's public repair lockers."},
    "field_rations":{"name":"Field Ration Lot","cost":{"ration":3},"tier":0,"purpose":"Supply field crews working beyond the habitat ring."},
    "lab_controls":{"name":"Laboratory Control Set","cost":{"circuit_board":1,"precision_lens":1},"tier":1,"purpose":"Replace unstable controls in the Research Block."},
    "water_renewal":{"name":"Water Renewal Kit","cost":{"water_filter":1,"sealant":1},"tier":1,"purpose":"Keep settlement water systems within tolerance."},
    "spaceport_cells":{"name":"Spaceport Power Reserve","cost":{"power_cell":1,"biofiber":1},"tier":2,"purpose":"Maintain emergency power at the Spaceport."},
    "research_samples":{"name":"Siro Analysis Package","cost":{"siro_sampler":1,"precision_lens":1},"tier":2,"purpose":"Expand the Siro monitoring archive."},
    "duck_fleet_crates":{"name":"Delivery Fleet Refit","cost":{"duck_crate":1,"power_cell":1},"tier":3,"purpose":"Refit the delivery fleet's most judgmental cargo units."},
}

CRAFT_PAY={
    "components":{"sc":1,"contribution":0,"development":1},
    "core":{"sc":2,"contribution":1,"development":1},
    "quality":{"sc":3,"contribution":1,"development":2},
}
DUCK_PERSONALITY={
    "Hueburt":"steady and stubborn","Colora":"fast and dramatic","Prisma":"curious about every crate",
    "Pastelle":"calm under pressure","Asimov":"suspiciously efficient",
}
DUO_ACTIVITIES={"walk":35,"games":35,"research":90,"delivery":90,"explore":90}

def resource_name(key):
    key=item_identity.canonical(key)
    if key in seed_content.ITEMS:return seed_content.item_label(key) if key in seed_content.ACTIVE else seed_content.ITEMS[key]['name']
    return {"sc":"SC","crops":"Crop","ore":"Hematite Ore","rare_ore":"Argentite Ore","components":"Component","cargo":"Cargo","biofiber":"Biofiber","alloy_plate":"Alloy Plate","circuit_board":"Circuit Board","power_cell":"Power Cell","sealant":"Sealant","precision_lens":"Precision Lens"}.get(key,key.replace("_"," ").title())
def requirement_text(costs):
    """Preview quantities; deductions are reserved for completed transactions."""
    return ", ".join(f"{amount} {resource_name(key)}" for key,amount in costs.items())

def cost_text(costs):
    return "("+", ".join(f"-{amount} {resource_name(key)}" for key,amount in costs.items())+")"
BONUS_TYPES={
    "rockys_favor":("🪨 Rocky's Favor","+3% success chance"),
    "seed_dividend":("🪙 SEED Dividend","+2 SC on successful skilled actions"),
    "civic_recognition":("⭐ Civic Recognition","+1 Contribution on successful skilled actions"),
    "accelerated_learning":("🧬 Accelerated Learning","+1 base aptitude practice on successful skilled actions; conditions affect banked XP"),
}

def record_account_name(db,channel,provider,provider_uid,name):
    provider=(provider or "").lower().strip()
    provider_uid=str(provider_uid or "").strip()
    display=clean(name)
    if not provider or not provider_uid:return
    row=db.execute(select(AccountNameHistory).where(
        AccountNameHistory.channel_id==channel,
        AccountNameHistory.provider==provider,
        AccountNameHistory.provider_uid==provider_uid,
        AccountNameHistory.display_name==display
    )).scalar_one_or_none()
    if row:
        row.last_seen=now();row.seen_count+=1
    else:
        db.add(AccountNameHistory(channel_id=channel,provider=provider,provider_uid=provider_uid,display_name=display))

def account_name_rows(db,channel,provider,provider_uid):
    return db.execute(select(AccountNameHistory).where(
        AccountNameHistory.channel_id==channel,
        AccountNameHistory.provider==provider,
        AccountNameHistory.provider_uid==str(provider_uid)
    ).order_by(AccountNameHistory.first_seen.asc())).scalars().all()

def account_name_summary(db,channel,provider,provider_uid,fallback=""):
    rows=account_name_rows(db,channel,provider,provider_uid)
    if not rows:
        return clean(fallback) if fallback else "not observed since name-history tracking began", []
    latest=max(rows,key=lambda r:as_utc(r.last_seen))
    old=[r.display_name for r in rows if r.display_name.lower()!=latest.display_name.lower()]
    return latest.display_name,old

def owner_link_lookup(db,channel,query=""):
    links=db.execute(select(AccountLink).where(AccountLink.channel_id==channel).order_by(AccountLink.linked_at.desc())).scalars().all()
    q=(query or "").strip().lower()
    matches=[]
    for link in links:
        p=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==link.twitch_uid)).scalar_one_or_none()
        tw_cur,tw_old=account_name_summary(db,channel,"twitch",link.twitch_uid,p.display_name if p else "")
        dc_cur,dc_old=account_name_summary(db,channel,"discord",link.discord_uid,"")
        hay=[tw_cur,dc_cur,str(link.twitch_uid),str(link.discord_uid)]+tw_old+dc_old
        if q and not any(q in (x or "").lower() for x in hay):continue
        matches.append((link,tw_cur,tw_old,dc_cur,dc_old))
    if not matches:
        return "🔐 No linked account pair matched that name or ID." if q else "🔐 No linked Twitch/Discord pairs found."
    if q:
        matches=matches[:5]
    else:
        matches=matches[:10]
    lines=["🔐 LINKED ACCOUNT LOOKUP"]
    for link,tw_cur,tw_old,dc_cur,dc_old in matches:
        lines.append(f"\nTwitch: {tw_cur} | Discord: {dc_cur}")
        lines.append(f"IDs: Twitch {link.twitch_uid} | Discord {link.discord_uid}")
        if tw_old:lines.append("Previous Twitch names: "+", ".join(tw_old[-6:]))
        if dc_old:lines.append("Previous Discord names: "+", ".join(dc_old[-6:]))
        lines.append("Linked: "+as_utc(link.linked_at).strftime("%Y-%m-%d"))
    lines.append("\nName history starts when v5.4.1 sees an account; names from before then may be unavailable.")
    return "\n".join(lines)[:1850]


def hobby_row(db,p,hobby):
    row=db.execute(select(HobbyProgress).where(HobbyProgress.channel_id==p.channel_id,HobbyProgress.canonical_uid==p.twitch_uid,HobbyProgress.hobby==hobby)).scalar_one_or_none()
    if not row:
        legacy={"gardening":"gardening","exploration":"exploration_hobby","mechanics":"mechanics","research":"research_hobby","games":"games_hobby","rockwatching":"rockwatching"}
        life=life_state(db,p);start=getattr(life,legacy[hobby],0) if hobby in legacy else 0
        row=HobbyProgress(channel_id=p.channel_id,canonical_uid=p.twitch_uid,hobby=hobby,points=start);db.add(row);db.commit();db.refresh(row)
    return row

def hobby_points(db,p,hobby):return hobby_row(db,p,hobby).points

def unlock_title(db,p,key):
    if key not in TITLE_DEFS:return False
    row=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==p.channel_id,PlayerTitle.canonical_uid==p.twitch_uid,PlayerTitle.title_key==key)).scalar_one_or_none()
    if row:return False
    db.add(PlayerTitle(channel_id=p.channel_id,canonical_uid=p.twitch_uid,title_key=key,equipped=False));db.commit();return True

def refresh_titles(db,p):
    unlock_title(db,p,"new_eridian_local")
    checks=[("green_thumb",p.farm_xp),("deep_delver",p.mining_xp),("machine_whisperer",p.fabrication_xp),("siro_watcher",p.research_xp),("trailwise",p.explore_xp),("market_regular",p.commerce_xp)]
    for key,xp in checks:
        if xp>=150:unlock_title(db,p,key)
    if p.contribution>=150:unlock_title(db,p,"community_builder")
    rels=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id)).scalars().all()
    if any(p.twitch_uid in {x.uid_a,x.uid_b} and x.familiarity>=180 for x in rels):unlock_title(db,p,"friend_of_eridian")
    q=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.quality=="Masterwork",QualityGear.qty>0)).scalars().all()
    if q:unlock_title(db,p,"master_crafter")
    orders=db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==p.channel_id,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all()
    if len(orders)>=1:unlock_title(db,p,"production_runner")
    if len(orders)>=10:unlock_title(db,p,"industry_coordinator")
    if len(orders)>=30:unlock_title(db,p,"master_supplier")

def equipped_title(db,p):
    refresh_titles(db,p)
    row=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==p.channel_id,PlayerTitle.canonical_uid==p.twitch_uid,PlayerTitle.equipped==True)).scalar_one_or_none()
    return TITLE_DEFS.get(row.title_key,"") if row else ""

def check_collection_sets(db,p):
    owned={r.item_key for r in db.execute(select(CollectionItem).where(CollectionItem.channel_id==p.channel_id,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.qty>0)).scalars().all()}
    rewards=[]
    for key,(name,items,sc,contrib,title) in COLLECTION_SETS.items():
        if not items.issubset(owned):continue
        claimed=db.execute(select(CollectionSetClaim).where(CollectionSetClaim.channel_id==p.channel_id,CollectionSetClaim.canonical_uid==p.twitch_uid,CollectionSetClaim.set_key==key)).scalar_one_or_none()
        if claimed:continue
        db.add(CollectionSetClaim(channel_id=p.channel_id,canonical_uid=p.twitch_uid,set_key=key));p.sc+=sc;p.contribution+=contrib
        title_key=next((k for k,v in TITLE_DEFS.items() if v==title),None)
        if title_key:unlock_title(db,p,title_key)
        rewards.append(f"📚 Set complete: {name}! +{sc} SC/+{contrib} Contribution; title unlocked: {title}.")
    db.commit();return " "+" ".join(rewards) if rewards else ""

def story_week(clock):return max(0,(clock["day"]-1)//28)

def story_state(db,channel,clock=None):
    clock=clock or world_clock(db,channel);wk=story_week(clock)
    row=db.execute(select(WeeklyStory).where(WeeklyStory.channel_id==channel,WeeklyStory.week_index==wk)).scalar_one_or_none()
    if not row:
        cfg=STORY_ARCS[_stable_index(f"{channel}:{wk}:story",len(STORY_ARCS))]
        row=WeeklyStory(channel_id=channel,week_index=wk,arc_key=cfg["key"]);db.add(row);db.commit();db.refresh(row)
    cfg=next(x for x in STORY_ARCS if x["key"]==row.arc_key)
    return row,cfg

def story_contribute(db,p,skill):
    if not skill:return ""
    clock=world_clock(db,p.channel_id);row,cfg=story_state(db,p.channel_id,clock)
    if row.resolved:return ""
    tracks=[row.track_a,row.track_b,row.track_c];matched=[]
    for i,(_,skills) in enumerate(cfg["tracks"]):
        if skill in skills:matched.append(i)
    if not matched:return ""
    idx=random.choice(matched);tracks[idx]+=1;row.track_a,row.track_b,row.track_c=tracks;total=sum(tracks)
    note=f" 📖 {cfg['name']} +1 ({total}/{cfg['goal']})."
    if total>=cfg["goal"]:
        winner=max(range(3),key=lambda i:tracks[i]);track_name=cfg["tracks"][winner][0];row.resolved=True
        row.outcome=f"New Eridian resolved {cfg['name']} through {track_name}."
        soc=society(db,p.channel_id);rewards=[("Farming/Processing",("food",30)),("Research",("knowledge",30)),("Logistics/Commerce",("treasury",30))]
        # Arc-independent reward keyed to winning track: development + reputation plus a themed stat.
        if winner==0:soc.development+=20;soc.food+=20
        elif winner==1:soc.knowledge+=30
        else:soc.treasury+=20;soc.reputation+=20
        note+=f" ✅ Story resolved: {track_name}! Society receives a major boost."
    db.commit();return note

def market_demand(channel,day):
    keys=list(MARKET_BASE);primary=keys[_stable_index(f"{channel}:{day}:market",len(keys))];secondary=keys[_stable_index(f"{channel}:{day}:market2",len(keys))]
    if secondary==primary:secondary=keys[(keys.index(primary)+1)%len(keys)]
    return primary,secondary

def market_multiplier(channel,day,resource):
    a,b=market_demand(channel,day)
    return 1.6 if resource==a else 1.3 if resource==b else 1.0

def duck_bond(db,p,duck,gain=0):
    row=db.execute(select(DuckBond).where(DuckBond.channel_id==p.channel_id,DuckBond.canonical_uid==p.twitch_uid,DuckBond.duck==duck)).scalar_one_or_none()
    if not row:row=DuckBond(channel_id=p.channel_id,canonical_uid=p.twitch_uid,duck=duck,xp=0);db.add(row)
    if gain:row.xp+=gain
    if row.xp>=100:unlock_title(db,p,"fleet_friend")
    db.commit();return row

def duck_rank(xp):
    if xp>=100:return "Trusted Handler"
    if xp>=50:return "Fleet Regular"
    if xp>=20:return "Familiar Face"
    if xp>=5:return "Recognized"
    return "New Contact"

def degrade_gear(db,p,skill):
    if not skill:return ""
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
    candidates=[x for x in rows if skill in QUALITY_RECIPES.get(x.item_key,{}).get("skills",{}) and x.condition>0]
    if not candidates:return ""
    row=max(candidates,key=lambda x:QUALITY_TIERS.get(x.quality,QUALITY_TIERS["Standard"])["skill"])
    familiarity=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==p.channel_id,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==row.item_key)).scalar_one_or_none()
    _,wear_reduction=gear_familiarity_rank(familiarity.uses if familiarity else 0)
    if random.random()>(.35-wear_reduction):return ""
    loss=random.randint(1,3);row.condition=max(0,row.condition-loss);db.commit()
    return f" 🔧 {row.item_name} condition {row.condition}%." if row.condition in {75,50,25,10,0} else ""

def tutorial_row(db,p):
    row=db.execute(select(TutorialProgress).where(TutorialProgress.channel_id==p.channel_id,TutorialProgress.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:row=TutorialProgress(channel_id=p.channel_id,canonical_uid=p.twitch_uid);db.add(row);db.commit();db.refresh(row)
    return row

def tutorial_text(db,p,provider):
    row=tutorial_row(db,p);prefix='/' if provider=='discord' else '!'
    if provider=="discord":
        steps=[("Check the living world","/world"),("Choose a job","/job"),("Complete a work action","/guide"),
               ("Check your life needs","/me section:Life Needs"),("Craft your first useful item","/make"),("Meet another citizen","/social"),("Help New Eridian","/society")]
    else:
        steps=[("Check the living world","!world"),("Choose a job","!job"),("Complete a work action","!guide"),
               ("Check your life needs","!life"),("Craft your first useful item","!make"),("Meet another citizen","!hi <name>"),("Help New Eridian","!projectstatus")]
    idx=min(row.step,len(steps)-1)
    return f"🧭 First Days {row.step}/{len(steps)} | Next: {steps[idx][0]} — {steps[idx][1]}" if not row.completed else "🧭 First Days complete. Your path is now your own."

def tutorial_advance(db,p,kind):
    row=tutorial_row(db,p);expected=["world","job","action","life","craft","social","society"]
    if row.completed:return ""
    if row.step<len(expected) and expected[row.step]==kind:
        row.step+=1
        if row.step>=len(expected):row.completed=True;p.sc+=20;p.contribution+=5;note=" 🎓 First Days complete! +20 SC/+5 Contribution."
        else:note=f" 🎓 First Days {row.step}/{len(expected)}."
        db.commit();return note
    return ""

def society(db,c):
    s=db.execute(select(Society).where(Society.channel_id==c)).scalar_one_or_none()
    if not s: s=Society(channel_id=c,name=GAME_NAME); db.add(s); db.commit(); db.refresh(s)
    shared=colony_state(db,c);colony_tick(shared,s,now());db.commit()
    return s
def world(db,c):
    w=db.execute(select(World).where(World.channel_id==c)).scalar_one_or_none()
    if not w: w=World(channel_id=c); db.add(w); db.commit(); db.refresh(w)
    return w
def resolve(db,c,provider,uid):
    if 'task_queue' in globals() and task_queue.actor_context.get()==(c,uid):return uid
    r=db.execute(select(Identity).where(Identity.channel_id==c,Identity.provider==provider,Identity.provider_uid==uid)).scalar_one_or_none()
    if r:return r.canonical_uid
    canon=uid if provider=="twitch" else "discord:"+uid
    db.add(Identity(channel_id=c,provider=provider,provider_uid=uid,canonical_uid=canon));db.commit();return canon
def player(db,c,provider,uid,name):
    canon=resolve(db,c,provider,uid)
    p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==canon)).scalar_one_or_none()
    if not p:
        p=Player(channel_id=c,twitch_uid=canon,display_name=clean(name));db.add(p);society(db,c).population+=1;db.commit();db.refresh(p)
    item_identity.migrate_player(sys.modules[__name__],db,p)
    record_account_name(db,c,provider,uid,name)
    p.display_name=clean(name);p.last_seen=now();db.commit()
    life_state(db,p)
    colony_capture(db,p)
    return canon,p
def lvl(x):
    return competency_level(x)
def as_utc(dt):
    if dt is None:return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
def skill_xp(p,skill):
    from .competencies import FIELDS
    return getattr(p,FIELDS[skill])

def gain_skill(p,skill,amount=1):
    from .competencies import FIELDS
    db=object_session(p);field=FIELDS[skill];old=lvl(getattr(p,field))
    if db is not None:
        st=colony_seedling(db,p);life=life_state(db,p)
        project=db.execute(select(SocietyProject).where(SocietyProject.channel_id==p.channel_id)).scalars().first()
        project_match=bool(project and project.progress<project.goal and skill in project_cfg(project.project_key)[3]) if project else False
        quality=getattr(p,"_practice_quality",1.0)
        living=productivity(life,player_world(db,p).siro_exposure)*(1.10 if min(life.energy,life.nutrition,life.social,life.comfort,life.morale)>=80 else 1.0)
        gain=practice_gain(amount,occupation_matches(p.job,skill),living,project_match,quality)
        practice=json.loads(st.practice);total=practice.get(skill,0.0)+gain
        amount=int(total);practice[skill]=round(total-amount,6);st.practice=json.dumps(practice)
        from .commands import context
        ctx=context.get()
        if ctx is not None:ctx["practice"].append(f"{p.display_name} {SKILL_LABELS[skill]} +{gain:.2f} ({amount} XP banked)")
    setattr(p,field,getattr(p,field)+amount)
    if db is not None:
        from .commands import context
        ctx=context.get() or {}
        branch=LEGACY_BRANCH.get(ctx.get("params",{}).get("action"))
        if branch:gain_branch(db,p,branch,amount)
    if skill in {"fabrication","infrastructure"}:p.industry_xp+=amount
    new=lvl(getattr(p,field))
    if db is not None and new>old:
        announce(db,p,f"LEVEL UP: {p.display_name} — {SKILL_LABELS[skill]} aptitude Lv. {old} → Lv. {new}",now())
    return amount

def specialization_for(db,p,skill):
    return db.execute(select(Specialization).where(Specialization.channel_id==p.channel_id,Specialization.canonical_uid==p.twitch_uid,Specialization.skill==skill)).scalar_one_or_none()
def business_for(db,p):
    return db.execute(select(Business).where(Business.channel_id==p.channel_id,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
def active_bonuses(db,p):
    return db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.expires_at>now()).order_by(TimedBonus.expires_at)).scalars().all()
def bonus_active(db,p,bonus):
    return db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.bonus==bonus,TimedBonus.expires_at>now())).scalar_one_or_none() is not None
def grant_random_bonus(db,p,bonus_chance=0):
    business=business_for(db,p);chance=(.08 if business else .04)+bonus_chance
    if random.random()>=chance:return ""
    bonus=random.choice(list(BONUS_TYPES));row=db.execute(select(TimedBonus).where(TimedBonus.channel_id==p.channel_id,TimedBonus.canonical_uid==p.twitch_uid,TimedBonus.bonus==bonus)).scalar_one_or_none();start=now()
    if not row:row=TimedBonus(channel_id=p.channel_id,canonical_uid=p.twitch_uid,bonus=bonus,expires_at=start,times_received=0);db.add(row)
    if as_utc(row.expires_at)>start:start=as_utc(row.expires_at)
    row.expires_at=start+timedelta(minutes=10);row.times_received+=1;db.commit();label,effect=BONUS_TYPES[bonus]
    owner_note=f" {business.name}'s trade network improved the discovery chance." if business else ""
    return f" ⚡ {p.display_name} activated {label}: {effect} for 10 more minutes.{owner_note}"
def bonuses_text(db,p,provider="twitch"):
    rows=active_bonuses(db,p)
    if not rows:return f"⚡ {p.display_name} has no active bonuses. Successful actions can activate one; business owners have double the chance."
    details=[]
    for row in rows:
        seconds=max(0,int((as_utc(row.expires_at)-now()).total_seconds()));label,effect=BONUS_TYPES.get(row.bonus,(row.bonus.replace("_"," ").title(),"Personal bonus"));details.append((label,effect,seconds,row.times_received))
    if provider=="discord":return f"⚡ {p.display_name} — Active Bonuses\n\n"+"\n\n".join(f"{label}\n{effect}\nTime remaining: {seconds//60}:{seconds%60:02d} · Activated {times}x" for label,effect,seconds,times in details)+"\n\nActivating the same bonus again adds another 10 minutes."
    return "⚡ "+" | ".join(f"{label} {seconds//60}:{seconds%60:02d} ({effect})" for label,effect,seconds,_ in details)
def citizen_title(p):
    skills={key:skill_xp(p,key) for key in SKILL_LABELS};strongest=max(skills,key=skills.get);return f"{JOBS.get(p.job,('Settler',set()))[0]} · {SKILL_LABELS[strongest]} specialist"
def business_xp_needed(level):
    return 25 + (max(1,int(level))*15)

def home_upgrade_cost(tier):
    tier=max(1,int(tier))
    # Long-term but smoother than the old quadratic jump.
    return 100 + 60*(tier**2), max(2,tier*2)

def gain_business_xp(b,amount):
    old=b.level;b.xp+=amount
    while b.xp>=business_xp_needed(b.level):b.xp-=business_xp_needed(b.level);b.level+=1
    db=object_session(b)
    if db is not None and b.level>old:
        p=db.execute(select(Player).where(Player.channel_id==b.channel_id,Player.twitch_uid==b.canonical_uid)).scalar_one_or_none()
        if p:announce(db,p,f"LEVEL UP: {b.name} occupation business Lv. {old} → Lv. {b.level}",now())
def success_chance(db,p,skill,base=.68,cap=.86):
    """Intrinsic chance before situational modifiers; deliberately capped."""
    spec_bonus=.03 if specialization_for(db,p,skill) else 0
    equipment=SKILL_EQUIPMENT.get(skill);equipment_bonus=.02 if equipment and item(db,p.channel_id,p.twitch_uid,equipment)>0 else 0
    if skill in {"fabrication","infrastructure"} and item(db,p.channel_id,p.twitch_uid,"toolkit")>0:equipment_bonus+=.02
    if skill in {"extraction","research","frontier"} and item(db,p.channel_id,p.twitch_uid,"sensor")>0:equipment_bonus+=.02
    timed_bonus=.03 if bonus_active(db,p,"rockys_favor") else 0
    level_bonus=min(.12,(lvl(skill_xp(p,skill))-1)*.015)
    return min(cap,base+level_bonus+spec_bonus+equipment_bonus+timed_bonus)

def clamp100(value):
    return max(0,min(100,int(value)))

from .needs import decay as decay_needs, RECOVERY_HELP

def life_state(db,p):
    row=db.execute(select(LifeState).where(LifeState.channel_id==p.channel_id,LifeState.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=LifeState(channel_id=p.channel_id,canonical_uid=p.twitch_uid,last_decay_at=now(),updated_at=now())
        db.add(row);db.commit();db.refresh(row)
    if decay_needs(row,now()):db.commit()
    return row

def life_label(value,kind):
    if value>=80:return "Excellent"
    if value>=60:return "Good"
    if value>=35:return "Stable"
    if value>=20:return {"energy":"Tired","nutrition":"Hungry","social":"Lonely","comfort":"Uncomfortable","morale":"Low"}.get(kind,"Low")
    return {"energy":"Exhausted","nutrition":"Starving","social":"Isolated","comfort":"Distressed","morale":"Demoralized"}.get(kind,"Critical")

TASK_NEED_MINIMUM=20
def task_need_gate(db,p,action,provider="twitch",life=None):
    """Return a clear blocking response when core life needs are too low."""
    life=life or life_state(db,p)
    blocked=[]
    if life.energy<TASK_NEED_MINIMUM:
        blocked.append(("⚡","Energy",life.energy,"/sleep or /relax","!sleep or !relax"))
    if life.nutrition<TASK_NEED_MINIMUM:
        blocked.append(("🍲","Nutrition",life.nutrition,"/eat (an emergency meal is free if you have no food)","!eat (an emergency meal is free if you have no food)"))
    if life.social<TASK_NEED_MINIMUM:
        blocked.append(("🤝","Social",life.social,"/games or /social","!games, !hi, or !hangout"))
    if not blocked:return ""
    if provider=="discord" and action=="gearrepair":shown="/repair target:Personal Quality Gear"
    else:shown=guide_command(action,"discord") if provider=="discord" and action in ACTION_SKILLS else (("/" if provider=="discord" else "!")+action)
    if provider=="discord":
        lines=[]
        for emoji,label,value,discord_fix,_ in blocked:
            lines.append(f"• {emoji} {label}: {value}/100 — requires {TASK_NEED_MINIMUM}. Fix it with {discord_fix}.")
        return (f"⛔ TASK BLOCKED — {p.display_name}, {shown} did not start.\n\n"
                "WHY\n"+"\n".join(lines)+
                "\n\nWHAT HAPPENED\nNo resources were consumed, no rewards were rolled, and no cooldown started.\n\n"
                "Fix every need listed above, then try the task again. Check /me section:Life Needs for your full status.")
    details="; ".join(f"{label} {value}/100 (need {TASK_NEED_MINIMUM}): {twitch_fix}" for _,label,value,_,twitch_fix in blocked)
    return f"⛔ TASK BLOCKED: {shown} did not start. {details}. Nothing was consumed, no rewards were rolled, and no cooldown started."

def hobby_rank(points):
    if points>=100:return ("Enthusiast III",.03)
    if points>=50:return ("Enthusiast II",.02)
    if points>=15:return ("Enthusiast I",.01)
    return ("Beginner",0)

def quality_gear_special(db,p,item_key):
    rows=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==item_key,QualityGear.qty>0,QualityGear.condition>0
    )).scalars().all()
    if not rows:return 0
    best=max(rows,key=lambda row:QUALITY_TIERS.get(row.quality,QUALITY_TIERS["Standard"])["special"])
    value=QUALITY_TIERS.get(best.quality,QUALITY_TIERS["Standard"])["special"]
    return value if best.condition>=25 else value/2

def quality_roll(fabrication_level,quality_bonus_points=0):
    roll=max(1,random.randint(1,100)-max(0,int(quality_bonus_points)));lvl=max(0,int(fabrication_level))
    if lvl>=30:
        return "Masterwork" if roll<=15 else "Precision" if roll<=65 else "Refined" if roll<=95 else "Standard"
    if lvl>=15:
        return "Masterwork" if roll<=5 else "Precision" if roll<=30 else "Refined" if roll<=80 else "Standard"
    if lvl>=5:
        return "Refined" if roll<=5 else "Standard" if roll<=35 else "Crude"
    return "Standard" if roll>65 else "Crude"

def add_quality_gear(db,p,key,quality):
    recipe=QUALITY_RECIPES[key]
    existing=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==key,
        QualityGear.qty>0
    )).scalars().first()
    if existing:return existing
    row=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==key,
        QualityGear.quality==quality
    )).scalar_one_or_none()
    if row:row.qty+=1;row.condition=max(row.condition,100)
    else:db.add(QualityGear(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=key,item_name=recipe["name"],quality=quality,qty=1,condition=100))
    db.commit()

def quality_gear_modifier(db,p,skill):
    if not skill:return 0,[]
    total=0;notes=[]
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
    best={}
    for row in rows:
        recipe=QUALITY_RECIPES.get(row.item_key)
        if not recipe or skill not in recipe["skills"]:continue
        tier=QUALITY_TIERS.get(row.quality,QUALITY_TIERS["Standard"])
        bonus=tier["skill"]*recipe["skills"][skill]
        if row.condition<25:bonus=max(.01,bonus/2)
        if bonus>best.get(row.item_key,(0,None))[0]:best[row.item_key]=(bonus,row)
    for bonus,row in best.values():
        total+=bonus
        notes.append(f"{row.item_name} {row.quality} +{int(bonus*100)}%")
    return min(.08,total),notes

def life_modifiers(db,p,skill):
    life=life_state(db,p);total=0;notes=[]
    if life.energy<15:total-=.12;notes.append("Exhausted -12%")
    elif life.energy<30:total-=.05;notes.append("Tired -5%")
    elif life.energy>=85:total+=.02;notes.append("Well Rested +2%")
    if life.nutrition<20:total-=.08;notes.append("Hungry -8%")
    elif life.nutrition>=85:total+=.02;notes.append("Well Fed +2%")
    if life.morale<20:total-=.07;notes.append("Demoralized -7%")
    elif life.morale>=85:total+=.02;notes.append("Inspired +2%")
    if life.social==0:
        penalty=.15 if skill in {"commerce","logistics"} else .10;total-=penalty;notes.append(f"Severe Isolation -{int(penalty*100)}%")
    elif life.social<20:
        penalty=.10 if skill in {"commerce","logistics"} else .05;total-=penalty;notes.append(f"Social Isolation -{int(penalty*100)}%")
    elif life.social<35 and skill in {"commerce","logistics"}:total-=.05;notes.append("Lonely -5%")
    elif life.social>=80 and skill in {"commerce","logistics"}:total+=.03;notes.append("Connected +3%")
    if life.comfort<20:total-=.10;notes.append("Need pressure: poor Comfort -10%; reduced productivity")
    elif life.comfort<35:total-=.04;notes.append("Need pressure: low Comfort -4%")
    elif life.comfort>=85:total+=.01;notes.append("Comfortable +1%")

    # Hobby perks are small and permanent.
    hobby_map={
        "cultivation":["gardening","cooking"],"environmental":["scanning","research"],
        "extraction":["rockwatching","exploration"],"fabrication":["mechanics"],"infrastructure":["mechanics"],
        "research":["research","scanning"],"logistics":["games","trading"],
        "frontier":["exploration","collecting"],"commerce":["trading","games"],
    }
    if skill in hobby_map:
        choices=[(h,hobby_points(db,p,h)) for h in hobby_map[skill]]
        hobby_name,points=max(choices,key=lambda x:x[1]);rank,bonus=hobby_rank(points)
        if bonus:total+=bonus;notes.append(f"{HOBBIES[hobby_name][0]} {rank} +{int(bonus*100)}%")

    gear_bonus,gear_notes=quality_gear_modifier(db,p,skill)
    total+=gear_bonus;notes.extend(gear_notes)
    return max(-.20,min(.12,total)),notes,life

def spend_life_for_action(life,action):
    if action in {"eat","sleep"}:return
    heavy=action in {"mine","rare","repair","project","explore","survey","machine","work"}
    social_action=action in {"market","business","businesscontract","businessinvest","delivery","spaceport"}
    life.energy=clamp100(life.energy-(3 if heavy else 2))
    life.nutrition=clamp100(life.nutrition-1)
    life.comfort=clamp100(life.comfort-1)
    if life.comfort<20:life.morale=clamp100(life.morale-1)
    if social_action:life.social=clamp100(life.social+1)
    life.updated_at=now()

def life_modifier_text(provider,notes,chance=None):
    if not notes:return ""
    if provider=="discord":
        suffix=f"\nFinal success chance: {int(chance*100)}%" if chance is not None else ""
        return "\n\n🧬 Active life modifiers\n"+"\n".join("• "+x for x in notes)+suffix
    compact=", ".join(notes[:4])
    suffix=f" | Chance {int(chance*100)}%" if chance is not None else ""
    return f" | Life: {compact}{suffix}"

def concise_action_modifiers(provider,notes,chance,failed=False):
    """Routine results show only actionable penalties; full detail lives in hubs."""
    penalties=[note for note in notes if re.search(r"-\d+%",note)]
    if not failed and not penalties:return ""
    shown=penalties[:4]
    chance_text=f"Final chance: {int(chance*100)}%" if chance is not None else ""
    if provider=="discord":
        rows=[*("• "+note for note in shown)]
        if chance_text:rows.append("• "+chance_text)
        return "\n\nWHY THIS RESULT\n"+"\n".join(rows) if rows else ""
    parts=shown+([chance_text] if chance_text else [])
    return " | "+", ".join(parts) if parts else ""

def failure_fix_text(skill,notes,chance,provider):
    fixes=[];joined=" ".join(notes).lower()
    if any(x in joined for x in ("tired","exhausted")):fixes.append("Recover Energy with /sleep or /relax.")
    if "hungry" in joined:fixes.append("Recover Nutrition with /eat.")
    if any(x in joined for x in ("lonely","isolation")):fixes.append("Recover Social with /games or /social.")
    if any(x in joined for x in ("demoralized","poor comfort")):fixes.append("Use /relax, /games, or a crafted life item.")
    if not fixes and skill:
        fixes.append(f"Train {SKILL_LABELS[skill]}, equip matching gear, or choose its Lv.10 specialization.")
    chance_line=f"The success roll missed at a final {int((chance or 0)*100)}% chance; even prepared work is never guaranteed."
    if provider=="discord":return "\n\nHOW TO IMPROVE\n• "+chance_line+"\n"+"\n".join("• "+x for x in fixes[:2])
    return " | "+chance_line+" "+" ".join(fixes[:2])

def important_progress_notes(*notes):
    """Keep alerts and completions in action results; routine meters stay in hubs."""
    kept=[]
    for note in notes:
        if not note:continue
        low=note.lower()
        if any(word in low for word in ("complete", "activated", "unlocked", "event", "encounter", "siro exposure", "broke")):
            kept.append(note)
    return "".join(kept)

def player_preference(db,p):
    row=db.execute(select(PlayerPreference).where(PlayerPreference.channel_id==p.channel_id,PlayerPreference.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=PlayerPreference(channel_id=p.channel_id,canonical_uid=p.twitch_uid)
        db.add(row);db.commit();db.refresh(row)
    return row

def daily_variety_note(db,p,skill,clock):
    """Reward three different aptitudes once per Avesta day; never a streak."""
    if not skill:return ""
    row=db.execute(select(DailyVariety).where(DailyVariety.channel_id==p.channel_id,DailyVariety.canonical_uid==p.twitch_uid,DailyVariety.avesta_day==clock["day"])).scalar_one_or_none()
    if not row:
        row=DailyVariety(channel_id=p.channel_id,canonical_uid=p.twitch_uid,avesta_day=clock["day"],skills="",claimed=False);db.add(row)
    if row.claimed:return ""
    skills={x for x in row.skills.split(",") if x};before=len(skills);skills.add(skill);row.skills=",".join(sorted(skills))
    if len(skills)>=3 and not row.claimed:
        row.claimed=True;p.sc+=6;life=life_state(db,p);life.morale=clamp100(life.morale+4);db.commit()
        return " 🌈 Daily Variety complete: 3 aptitudes, +6 SC/+4 Morale."
    db.commit()
    return f" 🌈 Daily Variety {len(skills)}/3 aptitudes." if len(skills)>before else ""

def directive_for(db,channel,day):
    row=db.execute(select(DirectiveProgress).where(DirectiveProgress.channel_id==channel,DirectiveProgress.avesta_day==day)).scalar_one_or_none()
    if not row:
        cfg=DIRECTIVES[_stable_index(f"{channel}:{day}:directive",len(DIRECTIVES))]
        goal=max(10,min(24,10+2*active_player_count(db,channel)))
        row=DirectiveProgress(channel_id=channel,avesta_day=day,directive_key=cfg[0],progress=0,goal=goal,complete=False);db.add(row);db.commit();db.refresh(row)
    cfg=next((x for x in DIRECTIVES if x[0]==row.directive_key),DIRECTIVES[0])
    return row,cfg

def directive_note(db,p,s,skill,clock):
    if not skill:return ""
    row,cfg=directive_for(db,p.channel_id,clock["day"])
    if row.complete or skill not in cfg[2]:return ""
    part=db.execute(select(DirectiveParticipant).where(DirectiveParticipant.channel_id==p.channel_id,DirectiveParticipant.canonical_uid==p.twitch_uid,DirectiveParticipant.avesta_day==clock["day"])).scalar_one_or_none()
    if not part:
        part=DirectiveParticipant(channel_id=p.channel_id,canonical_uid=p.twitch_uid,avesta_day=clock["day"],contributions=0);db.add(part)
    row.progress=min(row.goal,row.progress+1);part.contributions+=1
    personal=""
    if part.contributions<=3:p.sc+=1;personal=" +1 SC participation."
    if row.progress>=row.goal:
        row.complete=True;setattr(s,cfg[3],getattr(s,cfg[3])+cfg[4]);p.contribution+=2
        db.commit();return f" 📣 {cfg[1]} COMPLETE {row.progress}/{row.goal}: New Eridian +{cfg[4]} {cfg[3].title()}; +2 Contribution.{personal}"
    db.commit();return f" 📣 {cfg[1]} {row.progress}/{row.goal}.{personal}"

def set_event_aftermath(db,channel,cfg,result):
    from .events import incident_effect
    incident_effect(colony_state(db,channel),cfg["primary"],result)
    positive=result=="success";modifier=3 if positive else (-1 if result=="partial" else -2)
    description=(f"Successful {cfg['name']} response is supporting related work." if positive else
                 f"Recovery from {cfg['name']} is complicating related work.")
    db.add(SocietyAftermath(channel_id=channel,event_name=cfg["name"],result=result,
                            skills=",".join(sorted({cfg["primary"],cfg["support"]})),modifier=modifier,
                            description=description,expires_at=now()+timedelta(minutes=60)))
    db.commit()

def aftermath_modifier(db,channel,skill):
    rows=db.execute(select(SocietyAftermath).where(SocietyAftermath.channel_id==channel,SocietyAftermath.expires_at>now())).scalars().all()
    matching=[r for r in rows if skill in set(r.skills.split(","))]
    if not matching:return 0,[]
    # Only the newest relevant aftermath applies; effects never stack.
    row=max(matching,key=lambda x:as_utc(x.expires_at));return row.modifier/100,[f"{row.event_name} aftermath {row.modifier:+d}%"]

def gear_familiarity_rank(uses):
    if uses>=50:return "Trusted",.15
    if uses>=25:return "Practiced",.10
    if uses>=10:return "Familiar",.05
    return "New",0

def gear_familiarity_use(db,p,skill):
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0,QualityGear.condition>0)).scalars().all()
    relevant=[r for r in rows if skill in QUALITY_RECIPES.get(r.item_key,{}).get("skills",{})]
    notes=[]
    for gear in relevant:
        row=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==p.channel_id,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==gear.item_key)).scalar_one_or_none()
        if not row:row=GearFamiliarity(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=gear.item_key,uses=0);db.add(row)
        old=gear_familiarity_rank(row.uses)[0];row.uses+=1;new=gear_familiarity_rank(row.uses)[0]
        if old!=new:notes.append(f" 🛠️ {gear.item_name} familiarity: {new} ({row.uses} uses); wear chance reduced.")
    db.commit();return "".join(notes)

def relationship_memory(db,channel,a,b,activity):
    a,b=relationship_pair(a,b)
    row=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==channel,RelationshipMemory.uid_a==a,RelationshipMemory.uid_b==b)).scalar_one_or_none()
    if not row:row=RelationshipMemory(channel_id=channel,uid_a=a,uid_b=b,interactions=0);db.add(row)
    row.interactions+=1;row.last_activity=activity[:48];row.last_at=now();db.commit()
    return row

def near_milestone_note(db,p,skill):
    if not skill:return ""
    from .competencies import next_level_xp
    xp=skill_xp(p,skill);threshold=next_level_xp(xp)
    if threshold and threshold-xp<=3:return f" 🔔 {SKILL_LABELS[skill]} is {threshold-xp} XP from its next milestone."
    return ""

def maybe_lore_discovery(db,p,skill,clock):
    if not skill or random.random()>=.035:return ""
    owned={x.lore_key for x in db.execute(select(LoreDiscovery).where(LoreDiscovery.channel_id==p.channel_id,LoreDiscovery.canonical_uid==p.twitch_uid)).scalars().all()}
    available=[x for x in LORE_FRAGMENTS if x not in owned]
    if not available:return ""
    key=available[_stable_index(f"{p.twitch_uid}:{clock['day']}:{p.actions}:{skill}",len(available))]
    db.add(LoreDiscovery(channel_id=p.channel_id,canonical_uid=p.twitch_uid,lore_key=key));db.commit()
    journal_add(db,p,"Lore: "+LORE_FRAGMENTS[key]);return f" 📜 Lore discovered ({len(owned)+1}/{len(LORE_FRAGMENTS)}): {LORE_FRAGMENTS[key]}"

def relationship_pair(a,b):
    return tuple(sorted((str(a),str(b))))

def relationship_label(points):
    if points>=300:return "Close Companion"
    if points>=180:return "Trusted Friend"
    if points>=90:return "Friend"
    if points>=35:return "Familiar"
    if points>=10:return "Acquaintance"
    return "Stranger"

def effective_relationship(db,row):
    memory=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==row.channel_id,RelationshipMemory.uid_a==row.uid_a,RelationshipMemory.uid_b==row.uid_b)).scalar_one_or_none()
    weeks=max(0,int((now()-as_utc(memory.last_at)).total_seconds()//604800)) if memory else 0
    return max(0,row.familiarity-min(row.familiarity//2,weeks*5))

def relationship_add(db,channel,a,b,amount):
    a,b=relationship_pair(a,b)
    row=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel,LifeRelationship.uid_a==a,LifeRelationship.uid_b==b)).scalar_one_or_none()
    if not row:row=LifeRelationship(channel_id=channel,uid_a=a,uid_b=b,familiarity=0);db.add(row)
    if amount>0:
        people=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid.in_([a,b]))).scalars().all()
        if any(life_state(db,person).social<20 for person in people):amount=max(1,amount//2)
        shared=colony_state(db,channel);shared.mood=min(100,shared.mood+1)
    row.familiarity=max(0,row.familiarity+amount);db.commit();return row

def find_player_name(db,channel,target):
    wanted=(target or "").strip()
    if not wanted:return None,"Type a player's name."
    if wanted.startswith('citizen:') and wanted[8:].isdigit():
        row=db.execute(select(Player).where(Player.channel_id==channel,Player.id==int(wanted[8:]))).scalar_one_or_none()
        return (row,None) if row else (None,"That citizen is no longer available. Select a player again.")
    matches=[p for p in db.execute(select(Player).where(Player.channel_id==channel)).scalars().all() if p.display_name.casefold()==wanted.casefold()]
    if not matches:
        # unique prefix fallback makes Twitch names easier without risky fuzzy matching
        prefix=[p for p in db.execute(select(Player).where(Player.channel_id==channel)).scalars().all() if p.display_name.casefold().startswith(wanted.casefold())]
        if len(prefix)==1:return prefix[0],None
        if len(prefix)>1:return None,"That name matches multiple players. Type more of the name."
        return None,f"No New Eridian player named '{wanted}' was found. They need to use /start or !start first."
    if len(matches)>1:return None,"More than one player has that display name. Use a more specific name."
    return matches[0],None

def life_status_text(db,p,provider):
    life=life_state(db,p);_,notes,_=life_modifiers(db,p,None)
    blocked=[]
    if life.energy<TASK_NEED_MINIMUM:blocked.append(f"⚡ Energy {life.energy}/100 → /sleep or /relax")
    if life.nutrition<TASK_NEED_MINIMUM:blocked.append(f"🍲 Nutrition {life.nutrition}/100 → /eat (free emergency meal if you have no food)")
    if life.social<TASK_NEED_MINIMUM:blocked.append(f"🤝 Social {life.social}/100 → /games or /social")
    if provider=="discord":
        effects="\n".join("• "+n for n in notes) if notes else "• No active life penalties."
        readiness=("⛔ WORK BLOCKED\n"+"\n".join("• "+x for x in blocked)+
                   f"\nRaise every listed need to {TASK_NEED_MINIMUM} or higher before working, crafting, or repairing gear."
                   if blocked else
                   f"✅ READY FOR WORK\nEnergy, Nutrition, and Social are each at least {TASK_NEED_MINIMUM}.")
        return (f"🌱 {p.display_name} — Seedling Life\n\n"
                f"⚡ Energy: {life.energy}/100 · {life_label(life.energy,'energy')}\n"
                f"🍲 Nutrition: {life.nutrition}/100 · {life_label(life.nutrition,'nutrition')}\n"
                f"🤝 Social: {life.social}/100 · {life_label(life.social,'social')}\n"
                f"🏠 Comfort: {life.comfort}/100 · {life_label(life.comfort,'comfort')}\n"
                f"✨ Morale: {life.morale}/100 · {life_label(life.morale,'morale')}\n\n"
                f"TASK READINESS\n{readiness}\n\n"
                f"PASSIVE RECOVERY\n{RECOVERY_HELP}\n\nACTIVE EFFECTS\n{effects}\n\nUse /guide, /social, /relax, /walk, /games, or /hobby.")
    readiness=("Work BLOCKED: "+"; ".join(x.replace("/","!") for x in blocked)) if blocked else f"Work READY (core needs {TASK_NEED_MINIMUM}+)"
    return (f"🌱 {p.display_name} | ⚡{life.energy} Energy · 🍲{life.nutrition} Nutrition · 🤝{life.social} Social · "
            f"🏠{life.comfort} Comfort · ✨{life.morale} Morale | Recharge +1/15min to 60 | {readiness}"+(" | "+", ".join(notes[:3]) if notes else ""))


def _stable_index(text,count):
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12],16)%count

def world_clock(db,channel,s=None):
    s=s or society(db,channel)
    row=db.execute(select(WorldClock).where(WorldClock.channel_id==channel)).scalar_one_or_none()
    if not row:
        row=WorldClock(channel_id=channel,anchor_at=now(),anchor_day=max(1,s.day))
        db.add(row);db.commit();db.refresh(row)
    elapsed=max(0,(now()-as_utc(row.anchor_at)).total_seconds())
    day=max(1,row.anchor_day+int(elapsed//AVESTA_DAY_SECONDS))
    sec=int(elapsed%AVESTA_DAY_SECONDS);hour=(sec/AVESTA_DAY_SECONDS)*24
    phase=next((p for p in WORLD_PHASES if p[1]<=hour<p[2]),WORLD_PHASES[-1])
    if s.day!=day:
        s.day=day;db.commit()
    condition=WORLD_CONDITIONS[_stable_index(f"{channel}:{day}:condition",len(WORLD_CONDITIONS))]
    return {"day":day,"seconds":sec,"hour":hour,"phase":phase[0],"phase_emoji":phase[3],
            "condition_key":condition[0],"condition":condition[1],"condition_text":condition[2]}

def player_world(db,p):
    row=db.execute(select(PlayerWorld).where(PlayerWorld.channel_id==p.channel_id,PlayerWorld.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=PlayerWorld(channel_id=p.channel_id,canonical_uid=p.twitch_uid)
        db.add(row);db.commit();db.refresh(row)
    return row

def phase_action_modifier(clock,action,skill):
    phase=clock["phase"];bonus=0;notes=[]
    if phase=="Morning":
        if skill in {"cultivation","environmental"}:bonus+=.03;notes.append("Morning field conditions +3%")
    elif phase=="Day":
        if skill in {"commerce","logistics","fabrication","infrastructure"}:bonus+=.03;notes.append("Day-shift activity +3%")
    elif phase=="Evening":
        if skill in {"commerce","logistics"}:bonus+=.02;notes.append("Evening traffic +2%")
    elif phase=="Night":
        if skill in {"research","frontier","extraction"}:bonus+=.03;notes.append("Night operations +3%")
        if skill in {"cultivation","environmental"}:bonus-=.06;notes.append("Low-light field work -6%")
    return bonus,notes

def condition_action_modifier(clock,action,skill):
    key=clock["condition_key"];bonus=0;notes=[]
    if key=="good_growing" and skill=="cultivation":bonus+=.04;notes.append("Good Growing Weather +4%")
    elif key=="spore_drift" and skill in {"research","environmental"}:bonus+=.03;notes.append("Siro monitoring opportunity +3%")
    elif key=="dust_winds" and skill in {"frontier","extraction"}:bonus-=.04;notes.append("Dust Winds -4%")
    elif key=="busy_spaceport" and skill in {"logistics","commerce"}:bonus+=.04;notes.append("Busy Spaceport +4%")
    elif key=="water_watch" and skill=="environmental":bonus+=.04;notes.append("Water Watch priority +4%")
    elif key=="sensor_noise" and skill=="research":bonus-=.03;notes.append("Sensor Noise -3%")
    return bonus,notes

def district_modifier(pw,skill):
    bonuses={
        "agricultural_district":"cultivation","industrial_ward":"fabrication","research_block":"research",
        "market_concourse":"commerce","spaceport_quarter":"logistics","frontier_edge":"frontier",
    }
    if bonuses.get(pw.district)==skill:return .01,[f"{DISTRICTS[pw.district]} resident +1%"]
    return 0,[]

def shift_modifier(pw,day,skill):
    if pw.shift_day!=day:return 0,[]
    mapping={"kitchen_duty":"cooking","clinic_duty":"medicine","safety_duty":"emergency","field_duty":"cultivation","spaceport_duty":"logistics","lab_duty":"research",
             "maintenance":"infrastructure","trade_duty":"commerce","survey_duty":"frontier"}
    if mapping.get(pw.shift_role)==skill:return .02,[f"{SHIFT_ROLES[pw.shift_role]} +2%"]
    return 0,[]

def active_statuses(db,p):
    rows=db.execute(select(StatusEffect).where(StatusEffect.channel_id==p.channel_id,StatusEffect.canonical_uid==p.twitch_uid)).scalars().all()
    result=[]
    for row in rows:
        if now()>=as_utc(row.expires_at):db.delete(row)
        else:result.append(row)
    db.commit();return result

def add_status(db,p,effect,minutes,modifier,description):
    row=db.execute(select(StatusEffect).where(StatusEffect.channel_id==p.channel_id,StatusEffect.canonical_uid==p.twitch_uid,StatusEffect.effect==effect)).scalar_one_or_none()
    if not row:
        row=StatusEffect(channel_id=p.channel_id,canonical_uid=p.twitch_uid,effect=effect,expires_at=now(),modifier=modifier,description=description);db.add(row)
    row.expires_at=max(now(),as_utc(row.expires_at))+timedelta(minutes=minutes);row.modifier=modifier;row.description=description
    db.commit();return row

def status_modifier(db,p):
    rows=active_statuses(db,p);total=sum(r.modifier for r in rows)/100
    return total,[f"{r.effect.replace('_',' ').title()} {r.modifier:+d}%" for r in rows if r.modifier]

def trait_data(db,p):
    traits=[];bonus_by_skill={}
    checks=[
        ("Green Thumb","cultivation",p.farm_xp,50),("Deep Delver","extraction",p.mining_xp,50),
        ("Machine Whisperer","fabrication",p.fabrication_xp,50),("Habitat Hand","infrastructure",p.infrastructure_xp,50),
        ("Siro Watcher","research",p.research_xp,50),("Duck Wrangler","logistics",p.delivery_xp,50),
        ("Trailwise","frontier",p.explore_xp,50),("Market Regular","commerce",p.commerce_xp,50),
        ("Waterwise","environmental",p.environmental_xp,50),
    ]
    for name,skill,xp,need in checks:
        if xp>=need:traits.append(name);bonus_by_skill[skill]=bonus_by_skill.get(skill,0)+.01
    return traits,bonus_by_skill

def collection_add(db,p,key,qty=1):
    name=COLLECTIBLES.get(key,key.replace("_"," ").title())
    row=db.execute(select(CollectionItem).where(CollectionItem.channel_id==p.channel_id,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.item_key==key)).scalar_one_or_none()
    first=not bool(row)
    if not row:
        row=CollectionItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=key,item_name=name,qty=0);db.add(row)
    row.qty+=qty;db.commit()
    set_note=check_collection_sets(db,p)
    return name,first,set_note

def journal_add(db,p,entry):
    db.add(JournalEntry(channel_id=p.channel_id,canonical_uid=p.twitch_uid,entry=entry[:220]))
    db.commit()

def current_project(db,channel,day):
    row=db.execute(select(SocietyProject).where(SocietyProject.channel_id==channel)).scalar_one_or_none()
    if not row:
        key,name,goal,skills=PROJECTS[_stable_index(f"{channel}:{day}:project",len(PROJECTS))]
        row=SocietyProject(channel_id=channel,project_key=key,progress=0,goal=goal,started_day=day,completed=0)
        db.add(row);db.commit();db.refresh(row)
    return row

def project_cfg(key):
    return next((x for x in PROJECTS if x[0]==key),PROJECTS[0])

def project_contribute(db,p,skill,amount=1):
    clock=world_clock(db,p.channel_id);row=current_project(db,p.channel_id,clock["day"]);cfg=project_cfg(row.project_key)
    if skill not in cfg[3] or row.progress>=row.goal:return ""
    row.progress=min(row.goal,row.progress+amount)
    note=f" 🏗️ {cfg[1]} {row.progress}/{row.goal}."
    if row.progress>=row.goal:
        row.completed+=1
        p.sc+=8;p.contribution+=3
        journal_add(db,p,f"Helped complete the society project {cfg[1]} on Avesta Day {clock['day']}.")
        note+=f" ✅ Project complete! {p.display_name} receives +8 SC/+3 Contribution."
    db.commit();return note

def goal_for(db,p):
    clock=world_clock(db,p.channel_id);day=clock["day"]
    row=db.execute(select(PlayerGoal).where(PlayerGoal.channel_id==p.channel_id,PlayerGoal.canonical_uid==p.twitch_uid,PlayerGoal.day==day)).scalar_one_or_none()
    if not row:
        g=PERSONAL_GOALS[_stable_index(f"{p.twitch_uid}:{day}:goal",len(PERSONAL_GOALS))]
        row=PlayerGoal(channel_id=p.channel_id,canonical_uid=p.twitch_uid,day=day,goal_key=g[0],progress=0,claimed=False);db.add(row);db.commit();db.refresh(row)
    return row,next(g for g in PERSONAL_GOALS if g[0]==row.goal_key)

def goal_progress(db,p,action,skill,social=False,crafted=False,project=False):
    # v5.6: Daily Contract is the single daily objective system.
    # Keep this compatibility hook so old calls do not break.
    return ""

def shortages(s):
    results=[]
    if s.food<20:results.append(("Food Shortage","cultivation",.03))
    if s.materials<20:results.append(("Material Shortage","extraction",.03))
    if s.development<20:results.append(("Maintenance Backlog","infrastructure",.03))
    if s.knowledge<20:results.append(("Knowledge Gap","research",.03))
    if s.treasury<20:results.append(("Treasury Pressure","commerce",.03))
    return results

def shortage_modifier(s,skill):
    for label,target,bonus in shortages(s):
        if target==skill:return bonus,[f"{label}: needed work +{int(bonus*100)}%"]
    return 0,[]

def maybe_world_encounter(db,p,skill,clock,success=True):
    chance=.10 if success else .05
    if clock["condition_key"] in {"dust_winds","sensor_noise","spore_drift"}:chance+=.05
    if random.random()>=chance:return ""
    key,text=ENCOUNTERS[_stable_index(f"{p.twitch_uid}:{clock['day']}:{p.actions}:{random.randint(0,9999)}",len(ENCOUNTERS))]
    name,first,set_note=collection_add(db,p,key,1)
    if first:journal_add(db,p,f"Found first {name}.")
    npc=""
    if random.random()<.35:
        who,job=random.choice(NPCS);npc=f" {who}, {job}, points it out."
    return f" 🔎 Encounter: {text}{npc} Collected: {name}."+set_note

def exposure_tick(db,p,pw,action,skill,clock):
    outdoor=skill in {"cultivation","environmental","extraction","frontier","logistics"}
    if not outdoor:return ""
    chance=.03
    if clock["phase"]=="Night":chance+=.05
    if clock["condition_key"]=="spore_drift":chance+=.12
    if random.random()<chance:
        gain=random.randint(2,6);pw.siro_exposure=clamp100(pw.siro_exposure+gain);db.commit()
        if pw.siro_exposure>=70:add_status(db,p,"siro_fatigue",30,-8,"High Siro exposure is reducing action effectiveness.")
        elif pw.siro_exposure>=40:add_status(db,p,"spore_irritation",20,-4,"Siro exposure is making outdoor work uncomfortable.")
        return f" ☣️ Siro exposure +{gain} ({pw.siro_exposure}/100)."
    return ""

def housing_status_text(shared,s,provider="discord",detailed=False):
    shortage=max(0,s.population-shared.housing)
    repair="/repair target:society" if provider=="discord" else "!repair"
    overview=f"Shared housing: {shared.housing} spaces for {s.population} citizens"
    if not shortage:return overview+" — enough housing; no housing penalty."
    overview+=f" — short by {shortage}. Success chance -3% (3 percentage points)."
    if not detailed:
        return overview+f" Help: {repair}; repairs need shared Components."
    needed=5-(shared.infrastructure%5)
    rows=[overview,
          f"Help: use {repair}. Each successful supplied repair uses 1 shared Component and adds 1–2 Infrastructure, depending on needs.",
          f"Every 5 Infrastructure adds 1 housing space. Next space: {needed} more Infrastructure; shared Components available: {shared.components}."]
    if shared.components<1:
        craft="/make recipe:component" if provider=="discord" else "!make component"
        mine="/mine" if provider=="discord" else "!mine"
        rows.append(f"Supply the society first: {mine} adds shared Ore; {craft} uses your personal Hematite Ore and converts available shared Ore into shared Components.")
    rows.append("This is society-wide housing capacity. Upgrading your personal Habitat does not add shared housing spaces.")
    return "\n".join(rows)


def world_rule_bundle(db,p,s,action,skill,provider="discord"):
    clock=world_clock(db,p.channel_id,s);pw=player_world(db,p)
    parts=[];total=0
    for fn,args in [
        (phase_action_modifier,(clock,action,skill)),
        (condition_action_modifier,(clock,action,skill)),
        (district_modifier,(pw,skill)),
        (shift_modifier,(pw,clock["day"],skill)),
        (shortage_modifier,(s,skill)),
    ]:
        b,n=fn(*args);total+=b;parts.extend(n)
    traits,tbonus=trait_data(db,p)
    if skill and tbonus.get(skill):
        total+=tbonus[skill];parts.append(f"{next((t for t in traits if True), 'Trait')} +{int(tbonus[skill]*100)}%")
    sb,snotes=status_modifier(db,p);total+=sb;parts.extend(snotes)
    ab,anotes=aftermath_modifier(db,p.channel_id,skill);total+=ab;parts.extend(anotes)
    shared=colony_state(db,p.channel_id);colony_tick(shared,s,now())
    pressure=colony_pressures(shared,s,pw.siro_exposure)
    for label,value in pressure.items():
        total+=value
        if label=="housing pressure":
            parts.append(housing_status_text(shared,s,provider))
        elif label=="habitat decline":
            repair="/repair target:society" if provider=="discord" else "!repair"
            parts.append(f"Society infrastructure shortage: 0 Infrastructure for {s.population} citizens. Success chance -3% (3 percentage points). Help: {repair}; needs shared Components.")
        else:parts.append(f"Society condition: {label} {round(value*100):+d}%")
    if occupation_matches(p.job,skill):total+=.02;parts.append("Occupation match +2%")
    if skill in {"logistics","research","commerce","infrastructure"}:
        relations=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==p.channel_id,((LifeRelationship.uid_a==p.twitch_uid)|(LifeRelationship.uid_b==p.twitch_uid)))).scalars().all()
        best=max((effective_relationship(db,r) for r in relations),default=0)
        if best>=35 and life_state(db,p).social>=35:
            synergy=min(.04,best/3000);total+=synergy;parts.append(f"Trusted cooperation +{round(synergy*100)}%")
    return clock,pw,max(-.30,min(.15,total)),parts

def society_tier(s):
    core=min(s.food,s.materials,s.development,s.knowledge,s.treasury,s.reputation)
    current=SOCIETY_TIERS[0]
    for tier in SOCIETY_TIERS:
        if core>=tier[1]:current=tier
    return current
def society_tier_index(s):
    """Zero-based society rank used for recipe unlock requirements."""
    return SOCIETY_TIERS.index(society_tier(s))
def active_player_count(db,channel):
    cutoff=now()-timedelta(minutes=30)
    action_users=set(db.execute(select(ActionLog.canonical_uid).where(ActionLog.channel_id==channel,ActionLog.created_at>=cutoff)).scalars().all())
    if action_users:return len(action_users)
    return max(1,len(db.execute(select(Player).where(Player.channel_id==channel,Player.last_seen>=cutoff)).scalars().all()))
def scaled_event_goal(base,active):
    return max(6,int(math.ceil(base*min(2.0,1+.15*max(0,active-1)))))
def unique_activity_chatters(db,w,current_uid=None):
    if not w.activity_window_started_at:return 1 if current_uid else 0
    users=set(db.execute(select(ActionLog.canonical_uid).where(ActionLog.channel_id==w.channel_id,ActionLog.created_at>=as_utc(w.activity_window_started_at))).scalars().all())
    if current_uid:users.add(current_uid)
    return len(users)
def scaled_auto_event_actions(unique_chatters):
    return int(math.ceil(AUTO_EVENT_ACTIONS*min(2.0,1+.25*max(0,unique_chatters-1))))
ACTION_COOLDOWNS['seed_use']=20

def check_cooldown(db,p,action_name):
    row=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid,Cooldown.action==action_name)).scalar_one_or_none()
    seconds=ACTION_COOLDOWNS.get(action_name,5)
    if row and as_utc(row.ready_at)>now():
        remaining=max(1,int(math.ceil((as_utc(row.ready_at)-now()).total_seconds())))
        if remaining>seconds:row.ready_at=now()+timedelta(seconds=seconds);db.commit();return seconds
        return remaining
    if not row:row=Cooldown(channel_id=p.channel_id,canonical_uid=p.twitch_uid,action=action_name,ready_at=now());db.add(row)
    row.ready_at=now()+timedelta(seconds=seconds);db.commit();return 0
def cooldowns_text(db,p,provider="twitch"):
    rows=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid)).scalars().all()
    active=sorted((r.action,min(ACTION_COOLDOWNS.get(r.action,5),max(1,int(math.ceil((as_utc(r.ready_at)-now()).total_seconds()))))) for r in rows if as_utc(r.ready_at)>now())
    rules="Standard work, /eat, and /sleep: 5s. Social and recovery actions: 20–60s. /make: no cooldown."
    if not active:return "⏱️ No active cooldowns. Tasks still require sufficient needs and materials. "+rules
    if provider=="discord":return f"⏱️ {p.display_name} — Active Cooldowns\n\n"+"\n".join(f"• {guide_command(a,'discord')} — {seconds}s" for a,seconds in active[:15])+"\n\n"+rules
    return "⏱️ Cooldowns: "+" | ".join(f"{guide_command(a,'twitch')} {seconds}s" for a,seconds in active[:10])+" | Work/eat/sleep: 5s; social/recovery: 20–60s; !make: none"
def action_wait(db,p,action_name):
    row=db.execute(select(Cooldown).where(Cooldown.channel_id==p.channel_id,Cooldown.canonical_uid==p.twitch_uid,Cooldown.action==action_name)).scalar_one_or_none()
    return min(ACTION_COOLDOWNS.get(action_name,5),max(0,int(math.ceil((as_utc(row.ready_at)-now()).total_seconds())))) if row and as_utc(row.ready_at)>now() else 0
DISCORD_ACTION_ROUTES={
    "farm":"/farm action:Tend Fields","forage":"/farm action:Tend Fields",
    "harvest":"/farm action:Harvest Crops","water":"/farm action:Irrigate",
    "scavenge":"/mine","machine":"/make","work":"/make","craft":"/make","fabricate":"/make",
    "repair":"/repair target:Society Infrastructure","project":"/repair target:Society Infrastructure","build":"/repair target:Society Infrastructure",
    "survey":"/explore operation:Advanced Survey","market":"/market action:Commerce Work",
    "business":"/business action:Work","businesscontract":"/business action:Contract","businessinvest":"/business action:Invest",
    "hi":"/social action:Say Hi player:<name>","hangout":"/social action:Hang Out player:<name>",
    "mentor":"/social action:Mentor player:<name>","duo":"/social player:<name>",
    "gearrepair":"/repair target:Personal Quality Gear item:<item>",
    "sell":"/market action:Sell Resources resource:<resource> amount:<amount>",
}
ACTION_DISPLAY_NAMES={
    "farm":"Tend Fields","forage":"Tend Fields","harvest":"Harvest Crops","water":"Irrigate",
    "scan":"Environmental Scan","mine":"Mining","rare":"Argentite Prospecting","scavenge":"Mining",
    "craft":"Crafting","machine":"Crafting","work":"Crafting",
    "repair":"Society Infrastructure Repair","project":"Society Infrastructure Repair","build":"Society Infrastructure Repair",
    "cargo":"Cargo Preparation","delivery":"Delivery","spaceport":"Spaceport Operations",
    "explore":"Frontier Scout","survey":"Advanced Survey","market":"Commerce Work",
    "business":"Business Work","businesscontract":"Business Contract","businessinvest":"Business Investment",
    "research":"Research",
}
def guide_command(action_name,provider):
    if action_name in SEED_TASKS:
        cfg=SEED_TASKS[action_name]
        return f"/training skill:{cfg['hub']} task:{action_name}" if provider=="discord" else f"!training {cfg['hub']} {action_name}"
    if provider!="discord":
        twitch_routes={
            "duo_walk":"!duo <name> walk","duo_games":"!duo <name> games",
            "duo_research":"!duo <name> research","duo_delivery":"!duo <name> delivery",
            "duo_explore":"!duo <name> explore",
        }
        return twitch_routes.get(action_name,"!"+action_name)
    return DISCORD_ACTION_ROUTES.get(action_name,"/"+action_name)
def action_display_name(action_name,mode=""):
    if action_name in SEED_TASKS:return SEED_TASKS[action_name]["label"]
    if mode=="hydroponics":return "Hydroponics"
    if mode=="field_analysis":return "Field Analysis"
    if mode=="expedite":return "Expedited Spaceport Operations"
    if mode=="analyze":return "Market Analysis"
    return ACTION_DISPLAY_NAMES.get(action_name,action_name.replace("_"," ").title())
def guide_action(db,p,skill,provider):
    if skill in {"cooking","medicine","emergency","fabrication"}:
        hub=next(h for h,k in SEED_HUBS.items() if k==skill)
        return (f"/training skill:{hub}" if provider=="discord" else f"!training {hub}",0)
    business_exists=db.execute(select(Business).where(Business.channel_id==p.channel_id,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none() is not None
    choices=[]
    for action_name in SKILL_ACTIONS[skill]:
        if action_name in SEED_TASKS and (lvl(skill_xp(p,skill))<SEED_TASKS[action_name]["unlock"] or any(material_amount(db,p,k)<v for k,v in SEED_TASKS[action_name]["cost"].items())):continue
        if action_name=="craft" and p.ore<=0:continue
        if action_name=="delivery" and p.cargo<=0:continue
        if action_name in {"business","businesscontract","businessinvest"} and not business_exists:continue
        choices.append((action_wait(db,p,action_name),action_name))
    if not choices:choices=[(action_wait(db,p,SKILL_ACTIONS[skill][0]),SKILL_ACTIONS[skill][0])]
    wait,action_name=min(choices,key=lambda x:(x[0],SKILL_ACTIONS[skill].index(x[1])))
    return guide_command(action_name,provider),wait
def audit_moderator(db,channel,moderator,action_name,detail):
    db.add(ModeratorAudit(channel_id=channel,moderator=moderator,action=action_name,detail=detail[:500]));db.commit()
def live(w):
    return bool(w.active_event and w.event_ends and now()<as_utc(w.event_ends))
def item(db,c,u,name):
    name=item_identity.canonical(name)
    if name in item_identity.FIELD_ITEMS:
        p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==u)).scalar_one_or_none()
        return getattr(p,item_identity.FIELD_ITEMS[name]) if p else 0
    r=db.execute(select(ExtraItem).where(ExtraItem.channel_id==c,ExtraItem.canonical_uid==u,ExtraItem.item==name)).scalar_one_or_none()
    return r.qty if r else 0
def item_add(db,c,u,name,d):
    name=item_identity.canonical(name)
    if name in item_identity.FIELD_ITEMS:
        p=db.execute(select(Player).where(Player.channel_id==c,Player.twitch_uid==u)).scalar_one()
        result=material_change(db,p,name,d);db.commit();return result
    r=db.execute(select(ExtraItem).where(ExtraItem.channel_id==c,ExtraItem.canonical_uid==u,ExtraItem.item==name)).scalar_one_or_none()
    if not r:r=ExtraItem(channel_id=c,canonical_uid=u,item=name,qty=0);db.add(r)
    r.qty=max(0,r.qty+d);db.commit();return r.qty
PLAYER_MATERIAL_FIELDS={"crops","ore","rare_ore","components","cargo"}
def material_amount(db,p,key):
    key=item_identity.FIELD_ITEMS.get(item_identity.canonical(key),item_identity.canonical(key))
    if key in PLAYER_MATERIAL_FIELDS:return max(0,int(getattr(p,key)))
    return item(db,p.channel_id,p.twitch_uid,key)
def material_change(db,p,key,delta):
    key=item_identity.FIELD_ITEMS.get(item_identity.canonical(key),item_identity.canonical(key))
    if key in PLAYER_MATERIAL_FIELDS:
        setattr(p,key,max(0,int(getattr(p,key))+int(delta)));return getattr(p,key)
    row=db.execute(select(ExtraItem).where(
        ExtraItem.channel_id==p.channel_id,
        ExtraItem.canonical_uid==p.twitch_uid,
        ExtraItem.item==key
    )).scalar_one_or_none()
    if not row:
        row=ExtraItem(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item=key,qty=0);db.add(row)
    row.qty=max(0,row.qty+int(delta));return row.qty
def craft_output_key(recipe):return CRAFT_OUTPUT_KEYS.get(recipe,recipe)
def craft_output_amount(db,p,recipe):return material_amount(db,p,craft_output_key(recipe))

def material_source(key,provider='discord'):
    """Exact legacy inventory sources, distinct from namespaced items."""
    key=item_identity.canonical(key)
    if key in seed_content.ACTIVE:return seed_content.source_hint(key,provider)
    work={'crops':('farm action:harvest','harvest'),'ore':('mine','mine'),
          'rare_ore':('rare','rare'),'cargo':('cargo','cargo')}
    if key in work:return ('/'+work[key][0] if provider=='discord' else '!'+work[key][1])+' — successful work adds personal supplies.'
    recipe='component' if key=='components' else key
    if recipe in PART_RECIPES or recipe in RECIPES:
        return (f'/make recipe:{recipe}' if provider=='discord' else f'!make {recipe}')+' — '+requirement_text(PART_RECIPES.get(recipe) or RECIPES[recipe])
    for task,cfg in SEED_TASKS.items():
        if key in cfg['output']:
            command=f"/training skill:{cfg['hub']} task:{task}" if provider=='discord' else f"!training {cfg['hub']} {task}"
            return command+' — '+(requirement_text(cfg['cost']) or 'no ingredients')+f"; {SKILL_LABELS[cfg['skill']]} Lv.{cfg['unlock']}."
    return 'Inspect the item in /catalog.'

def missing_material_sources(db,p,cost,provider):
    return '\nHOW TO GET THEM\n'+'\n'.join(f'• {resource_name(k)}: {material_source(k,provider)}' for k,n in cost.items() if material_amount(db,p,k)<n)

def craft_record(db,p,recipe,quality=""):
    row=db.execute(select(CraftLedger).where(
        CraftLedger.channel_id==p.channel_id,CraftLedger.canonical_uid==p.twitch_uid,CraftLedger.recipe==recipe
    )).scalar_one_or_none()
    if not row:row=CraftLedger(channel_id=p.channel_id,canonical_uid=p.twitch_uid,recipe=recipe,qty=0,best_quality="");db.add(row)
    row.qty+=1
    if quality:
        ranks=list(QUALITY_TIERS)
        if not row.best_quality or ranks.index(quality)>ranks.index(row.best_quality):row.best_quality=quality
    return row

def determination_row(db,p,skill):
    row=db.execute(select(Determination).where(
        Determination.channel_id==p.channel_id,Determination.canonical_uid==p.twitch_uid,Determination.skill==skill
    )).scalar_one_or_none()
    if not row:row=Determination(channel_id=p.channel_id,canonical_uid=p.twitch_uid,skill=skill,stacks=0);db.add(row)
    return row
def determination_bonus(db,p,skill):
    if not skill:return 0
    return min(3,determination_row(db,p,skill).stacks)*.04
def determination_fail(db,p,skill):
    if not skill:return ""
    row=determination_row(db,p,skill);row.stacks=min(3,row.stacks+1);db.commit()
    return f" 🔥 Determination {row.stacks}/3: next {SKILL_LABELS[skill]} attempt gains +{row.stacks*4} percentage points."
def determination_clear(db,p,skill):
    if not skill:return ""
    row=determination_row(db,p,skill)
    if row.stacks<=0:return ""
    used=row.stacks;row.stacks=0;db.commit();return f" ✅ Determination +{used*4}% was used and reset after success."

def available_production_orders(channel,day,tier_index):
    eligible=[(key,data) for key,data in PRODUCTION_ORDERS.items() if data["tier"]<=tier_index]
    return sorted(eligible,key=lambda row:_stable_index(f"{channel}:{day}:{row[0]}:order",10**9))[:min(3,len(eligible))]
def replacement_value(key):
    key=item_identity.canonical(key)
    if key in SEED_INDUSTRIES:return SEED_INDUSTRIES[key]["buy"]
    if key in RECIPES:return sum(replacement_value(part)*qty for part,qty in RECIPES[key].items())+CRAFT_PAY["core"]["sc"]
    if key in PART_RECIPES:return sum(replacement_value(part)*qty for part,qty in PART_RECIPES[key].items())+CRAFT_PAY["components"]["sc"]
    if key in QUALITY_RECIPES:return sum(replacement_value(part)*qty for part,qty in QUALITY_RECIPES[key]["cost"].items())+CRAFT_PAY["quality"]["sc"]
    raise KeyError(f"No economy value for {key}")
def production_order_numbers(data):
    replacement=sum(replacement_value(key)*amount for key,amount in data["cost"].items())
    reward=max(8,int(math.floor(replacement*.75)))
    units=sum(data["cost"].values())
    tier=max(0,int(data.get("tier",0)))
    return {"replacement":replacement,"sc":reward,"contribution":1+tier,"development":2+tier}
def order_completed(db,p,day,key):
    return db.execute(select(ProductionOrderCompletion).where(
        ProductionOrderCompletion.channel_id==p.channel_id,
        ProductionOrderCompletion.canonical_uid==p.twitch_uid,
        ProductionOrderCompletion.avesta_day==day,
        ProductionOrderCompletion.order_key==key
    )).scalar_one_or_none() is not None
def unique_bonus_owned(db,p,key):
    if key in UNIQUE_CORE_ITEMS:
        return material_amount(db,p,key)>0
    if key in UNIQUE_QUALITY_ITEMS:
        return db.execute(select(QualityGear).where(
            QualityGear.channel_id==p.channel_id,
            QualityGear.canonical_uid==p.twitch_uid,
            QualityGear.item_key==key,
            QualityGear.qty>0
        )).scalars().first() is not None
    return False
def daily(db,p):
    k=now().strftime("%Y-%m-%d")
    d=db.execute(select(Daily).where(Daily.channel_id==p.channel_id,Daily.canonical_uid==p.twitch_uid,Daily.day_key==k)).scalar_one_or_none()
    if not d:
        a=random.choice(["harvest","mine","research","make","delivery","explore","water","repair","train_fire_safety","train_seed_cultivation","train_ore_mining"]);t=random.choice([3,4,5])
        d=Daily(channel_id=p.channel_id,canonical_uid=p.twitch_uid,day_key=k,action=a,target=t,reward_sc=t*3);db.add(d);db.commit();db.refresh(d)
    return d
def progress_daily(db,p,a):
    d=daily(db,p)
    if d.action=="craft" and a=="make":a="craft" # finish legacy contracts created before /make consolidation
    if d.complete or d.action!=a:return ""
    d.progress+=1
    if d.progress>=d.target:
        d.progress=d.target;d.complete=True;p.sc+=d.reward_sc;p.contribution+=1;db.commit()
        return f" 📋 Daily complete! +{d.reward_sc} SC/+1 Contribution."
    db.commit();return f" 📋 Daily {d.progress}/{d.target}."
def stat_changes_text(changes,sign="+"):
    labels={"food":"Food","materials":"Materials","development":"Development","knowledge":"Knowledge","treasury":"Treasury","reputation":"Reputation"}
    return ", ".join(f"{sign}{v} {labels[k]}" for k,v in changes.items())
def ensure_event_instance(w):
    if not w.event_instance:w.event_instance=secrets.token_hex(8)
    if not w.event_started_at:w.event_started_at=now()
    if not w.event_started_by:w.event_started_by="legacy/automatic"
def event_contributors(db,w):
    if not w.event_instance:return []
    rows=db.execute(select(EventContribution).where(EventContribution.channel_id==w.channel_id,EventContribution.event_instance==w.event_instance)).scalars().all()
    return sorted(rows,key=lambda r:(r.primary_successes*2+r.support_successes,r.primary_successes),reverse=True)
def leader_text(rows,limit=3):
    return ", ".join(f"{r.display_name} {r.primary_successes}P/{r.support_successes}S" for r in rows[:limit]) or "No contributors yet"
def record_event_history(db,w,result,outcome,ended_by="system"):
    ensure_event_instance(w);cfg=EVENTS[w.active_event];rows=event_contributors(db,w)
    db.add(EventHistory(channel_id=w.channel_id,event_instance=w.event_instance,event_key=w.active_event,event_name=cfg["name"],result=result,progress=w.event_progress,goal=w.event_goal,participants=len(rows),started_by=w.event_started_by or "automatic",ended_by=ended_by,outcome=outcome[:500],started_at=w.event_started_at,ended_at=now()))
def clear_event(w):
    w.active_event=None;w.event_progress=0;w.event_goal=0;w.event_ends=None;w.event_support_successes=0;w.last_event_end=now();w.event_instance=None;w.event_started_at=None;w.event_started_by=None;w.event_active_players=1
def finish_event(db,s,w,ended_by="system"):
    ensure_event_instance(w);cfg=EVENTS[w.active_event];tier=society_tier(s);mult=1+.15*tier[2]
    rewards={field:int(math.ceil(value*mult)) for field,value in cfg["reward"].items()}
    for field,value in rewards.items():setattr(s,field,getattr(s,field)+value)
    rows=event_contributors(db,w)
    for row in rows:
        participant=db.execute(select(Player).where(Player.channel_id==w.channel_id,Player.twitch_uid==row.canonical_uid)).scalar_one_or_none()
        if participant:
            units=max(1,row.primary_successes+int(math.ceil(row.support_successes/2)))
            participant.sc+=min(25,units*2);participant.contribution+=min(8,units)
    if rows:
        winner=db.execute(select(Player).where(Player.channel_id==w.channel_id,Player.twitch_uid==rows[0].canonical_uid)).scalar_one_or_none()
        if winner:winner.sc+=5;winner.contribution+=2
    outcome=f"{stat_changes_text(rewards)}; leaders: {leader_text(rows)}"
    record_event_history(db,w,"success",outcome,ended_by);set_event_aftermath(db,w.channel_id,cfg,"success")
    msg=f"✅ {cfg['emoji']} {cfg['name']} COMPLETE! New Eridian {stat_changes_text(rewards)}. {len(rows)} participants rewarded. Leaders: {leader_text(rows)}. Aftermath: +3% related work for 60 minutes."
    clear_event(w);db.commit();return msg
def resolve_expired_event(db,s,w,ended_by="timer"):
    if not w.active_event or not w.event_ends or now()<as_utc(w.event_ends):return ""
    cfg=EVENTS[w.active_event];pct=(w.event_progress/w.event_goal) if w.event_goal else 0
    if pct>=1:return finish_event(db,s,w,ended_by)
    factor=.5 if pct>=.75 else 1
    applied={}
    for field,value in cfg["penalty"].items():
        deduction=(value+1)//2 if factor==.5 else value
        old=getattr(s,field);actual=min(old,deduction);setattr(s,field,old-actual);applied[field]=actual
    protection="75% partial protection: " if factor==.5 else ""
    msg=f"⌛ {cfg['emoji']} {cfg['name']} FAILED at {w.event_progress}/{w.event_goal}. {protection}{stat_changes_text(applied,'−')}."
    aftermath_result="partial" if factor==.5 else "failed"
    record_event_history(db,w,aftermath_result,stat_changes_text(applied,"−"),ended_by);set_event_aftermath(db,w.channel_id,cfg,aftermath_result)
    msg+=f" Aftermath: {'−1%' if factor==.5 else '−2%'} related work for 60 minutes."
    clear_event(w);db.commit();return msg
def start_event(db,w,event_key,started_by="automatic"):
    cfg=EVENTS[event_key];active=active_player_count(db,w.channel_id);goal=scaled_event_goal(cfg["goal"],active)
    w.heartbeat=now();w.active_event=event_key;w.event_progress=0;w.event_goal=goal;w.event_support_successes=0;w.event_ends=now()+timedelta(minutes=cfg["minutes"]);w.event_instance=secrets.token_hex(8);w.event_started_at=now();w.event_started_by=started_by;w.event_active_players=active;w.activity_since_event=0;w.activity_window_started_at=None;db.commit()
    primary=SKILL_LABELS.get(cfg["primary"],cfg["primary"].title());support=SKILL_LABELS.get(cfg["support"],cfg["support"].title())
    return f"🚨 {cfg['emoji']} {cfg['name']} STARTED! {cfg['objective']}. Primary: {primary}; support: {support} (2 successes = +1). Goal {goal}, scaled for {active} active citizens."
def auto_event_status(db,w):
    if not AUTO_EVENTS_ENABLED:return "Automatic events are disabled."
    if w.active_event:return "An event is already active."
    unique=unique_activity_chatters(db,w);target=scaled_auto_event_actions(max(1,unique))
    time_need=AUTO_EVENT_MINUTES
    if w.activity_window_started_at:
        time_need=max(0,int(math.ceil(AUTO_EVENT_MINUTES-(now()-as_utc(w.activity_window_started_at)).total_seconds()/60)))
    cooldown_need=0
    if w.last_event_end:
        cooldown_need=max(0,int(math.ceil(AUTO_EVENT_COOLDOWN_MINUTES-(now()-as_utc(w.last_event_end)).total_seconds()/60)))
    if not w.activity_window_started_at:return f"Automatic event meter: 0/{target} actions; the {AUTO_EVENT_MINUTES}m activity timer starts with the next action."
    return f"Automatic event meter: {w.activity_since_event or 0}/{target} actions from {unique} unique chatter{'s' if unique!=1 else ''}; activity timer {time_need}m; event cooldown {cooldown_need}m."
def maybe_start_auto_event(db,w,add_activity=True,current_uid=None):
    if not AUTO_EVENTS_ENABLED or w.active_event:return ""
    if add_activity:
        if not w.activity_window_started_at:w.activity_window_started_at=now()
        w.activity_since_event=(w.activity_since_event or 0)+1
    unique=max(1,unique_activity_chatters(db,w,current_uid));target=scaled_auto_event_actions(unique)
    enough_actions=(w.activity_since_event or 0)>=target
    enough_time=bool(w.activity_window_started_at and now()-as_utc(w.activity_window_started_at)>=timedelta(minutes=AUTO_EVENT_MINUTES))
    cooldown_over=not w.last_event_end or now()-as_utc(w.last_event_end)>=timedelta(minutes=AUTO_EVENT_COOLDOWN_MINUTES)
    if enough_actions and enough_time and cooldown_over:
        return start_event(db,w,random.choice(list(EVENTS)),"automatic activity trigger")
    db.commit();return ""
def cancel_event(db,w,ended_by="moderator"):
    if not w.active_event:return "🚨 No active event to cancel."
    cfg=EVENTS[w.active_event];record_event_history(db,w,"cancelled","No penalty applied",ended_by);clear_event(w);db.commit();return f"🛑 {cfg['emoji']} {cfg['name']} cancelled by {ended_by}. No penalty applied."
def event_note(db,s,w,p,a):
    if not w.active_event:return ""
    expired=resolve_expired_event(db,s,w)
    if expired:return " "+expired
    ensure_event_instance(w);cfg=EVENTS[w.active_event];skill=ACTION_SKILLS.get(a)
    contribution=db.execute(select(EventContribution).where(EventContribution.channel_id==w.channel_id,EventContribution.event_instance==w.event_instance,EventContribution.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not contribution:contribution=EventContribution(channel_id=w.channel_id,event_instance=w.event_instance,canonical_uid=p.twitch_uid,display_name=p.display_name,primary_successes=0,support_successes=0);db.add(contribution)
    contribution.display_name=p.display_name
    if skill==cfg["primary"]:contribution.primary_successes+=1;w.event_progress+=1;note=f" Primary response +1 ({w.event_progress}/{w.event_goal})."
    elif skill==cfg["support"]:
        contribution.support_successes+=1
        w.event_support_successes+=1
        if w.event_support_successes>=2:w.event_support_successes=0;w.event_progress+=1;note=f" Support pair +1 ({w.event_progress}/{w.event_goal})."
        else:note=f" Support logged 1/2 ({w.event_progress}/{w.event_goal})."
    else:return ""
    if w.event_progress>=w.event_goal:return " "+finish_event(db,s,w,"completed by "+p.display_name)
    db.commit();return f" {cfg['emoji']} {cfg['name']}:{note}"
def log_action(db,channel,canonical_uid,action_name,response):
    row=ActionLog(channel_id=channel,canonical_uid=canonical_uid,action=action_name,response=response[:1000]);db.add(row);db.commit()
    from .commands import context
    ctx=context.get()
    if ctx is not None:ctx["log_id"]=row.id
def rare_outcome(db,p,s,skill):
    if not skill:return ""
    chance=min(.14,.02+lvl(skill_xp(p,skill))*.006+(.02 if specialization_for(db,p,skill) else 0))
    if random.random()>=chance:return ""
    if skill=="cultivation":p.crops+=1;s.food+=1;return " 🌿 Rare yield: a resilient Avesta cultivar adds +1 Crop/+1 Food."
    if skill=="environmental":s.knowledge+=2;return " 💧 Rare reading: an unusual biosphere pattern adds +2 Knowledge."
    if skill=="extraction":item_add(db,p.channel_id,p.twitch_uid,"mineral_sample",1);s.materials+=1;return " 💎 Rare find: +1 Mineral Sample/+1 Materials. Prospect rare ores with /gather."
    if skill=="fabrication":p.components+=1;s.development+=1;return " ⚙️ Precision result: +1 Component/+1 Development."
    if skill=="infrastructure":s.development+=2;return " 🏗️ Rocky-approved reinforcement: +2 Development."
    if skill=="research":s.knowledge+=2;return " ☣️ Rare Siro signature archived: +2 Knowledge."
    if skill=="logistics":p.cargo+=1;s.treasury+=1;return " 🦆 The delivery fleet recovers lost cargo: +1 Cargo/+1 Treasury."
    if skill=="frontier":item_add(db,p.channel_id,p.twitch_uid,"mineral_sample",1);s.knowledge+=1;return " 🧭 Frontier cache: +1 Mineral Sample/+1 Knowledge. Prospect rare ores with /gather."
    if skill=="commerce":p.sc+=3;s.treasury+=1;return " 🏪 Exceptional contract: +3 SC/+1 Treasury."
    return ""

def merge_accounts(db,channel,source_uid,target_uid):
    """Merge an unlinked Discord character into its Twitch character exactly once."""
    if not source_uid or source_uid==target_uid:return False
    source=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==source_uid)).scalar_one_or_none()
    target=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==target_uid)).scalar_one_or_none()

    for account in (source,target):
        if account:item_identity.migrate_player(sys.modules[__name__],db,account)
    if source and not target:
        source.twitch_uid=target_uid
        target=source
    elif source and target:
        additive=["sc","contribution","farm_xp","mining_xp","industry_xp","research_xp","delivery_xp","explore_xp","environmental_xp","fabrication_xp","infrastructure_xp","commerce_xp","cooking_xp","medicine_xp","emergency_xp","crops","ore","rare_ore","components","cargo","actions","successes"]
        for field in additive:setattr(target,field,getattr(target,field)+getattr(source,field))
        if target.job=="settler" and source.job!="settler":target.job=source.job
        if as_utc(source.created_at)<as_utc(target.created_at):target.created_at=source.created_at
        if as_utc(source.last_seen)>as_utc(target.last_seen):target.last_seen=source.last_seen
        if source.last_job_change and (not target.last_job_change or as_utc(source.last_job_change)>as_utc(target.last_job_change)):target.last_job_change=source.last_job_change
        db.delete(source)
        s=society(db,channel);s.population=max(0,s.population-1)

    for row in db.execute(select(SkillBranch).where(SkillBranch.channel_id==channel,SkillBranch.canonical_uid==source_uid)).scalars().all():
        target_branch=db.get(SkillBranch,(channel,target_uid,row.branch))
        if target_branch:target_branch.xp+=row.xp;db.delete(row)
        else:row.canonical_uid=target_uid

    # Stack extra inventory items by item name.
    for row in db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==target_uid,ExtraItem.item==row.item)).scalar_one_or_none()
        if existing:existing.qty+=row.qty;db.delete(row)
        else:row.canonical_uid=target_uid

    # Preserve the best home tier.
    source_home=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==source_uid)).scalar_one_or_none()
    target_home=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==target_uid)).scalar_one_or_none()
    if source_home:
        if target_home:target_home.tier=max(target_home.tier,source_home.tier);db.delete(source_home)
        else:source_home.canonical_uid=target_uid

    # Keep the Twitch business identity, but preserve the higher level and combined XP.
    source_business=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==source_uid)).scalars().first()
    target_business=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==target_uid)).scalars().first()
    if source_business:
        if target_business:
            target_business.level=max(target_business.level,source_business.level);target_business.xp+=source_business.xp
            while target_business.xp>=business_xp_needed(target_business.level):
                target_business.xp-=business_xp_needed(target_business.level);target_business.level+=1
            db.delete(source_business)
        else:source_business.canonical_uid=target_uid

    # Union achievements without duplicating them.
    target_codes={r.code for r in db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==target_uid)).scalars().all()}
    for row in db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==source_uid)).scalars().all():
        if row.code in target_codes:db.delete(row)
        else:row.canonical_uid=target_uid;target_codes.add(row.code)

    # Preserve one daily contract per day, using the furthest progress.
    for row in db.execute(select(Daily).where(Daily.channel_id==channel,Daily.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Daily).where(Daily.channel_id==channel,Daily.canonical_uid==target_uid,Daily.day_key==row.day_key)).scalar_one_or_none()
        if existing:
            if existing.action==row.action:
                existing.progress=max(existing.progress,row.progress);existing.complete=existing.complete or row.complete
            db.delete(row)
        else:row.canonical_uid=target_uid

    # Preserve active cooldowns, specializations, and historical event contributions.
    for row in db.execute(select(Cooldown).where(Cooldown.channel_id==channel,Cooldown.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Cooldown).where(Cooldown.channel_id==channel,Cooldown.canonical_uid==target_uid,Cooldown.action==row.action)).scalar_one_or_none()
        if existing:
            if as_utc(row.ready_at)>as_utc(existing.ready_at):existing.ready_at=row.ready_at
            db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==target_uid,Specialization.skill==row.skill)).scalar_one_or_none()
        if existing:db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(EventContribution).where(EventContribution.channel_id==channel,EventContribution.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(EventContribution).where(EventContribution.channel_id==channel,EventContribution.event_instance==row.event_instance,EventContribution.canonical_uid==target_uid)).scalar_one_or_none()
        if existing:
            existing.primary_successes+=row.primary_successes;existing.support_successes+=row.support_successes;db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(TimedBonus).where(TimedBonus.channel_id==channel,TimedBonus.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(TimedBonus).where(TimedBonus.channel_id==channel,TimedBonus.canonical_uid==target_uid,TimedBonus.bonus==row.bonus)).scalar_one_or_none()
        if existing:
            if as_utc(row.expires_at)>as_utc(existing.expires_at):existing.expires_at=row.expires_at
            existing.times_received+=row.times_received;db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(Determination).where(Determination.channel_id==channel,Determination.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(Determination).where(Determination.channel_id==channel,Determination.canonical_uid==target_uid,Determination.skill==row.skill)).scalar_one_or_none()
        if existing:existing.stacks=max(existing.stacks,row.stacks);db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==target_uid,CraftLedger.recipe==row.recipe)).scalar_one_or_none()
        if existing:
            existing.qty+=row.qty
            ranks=list(QUALITY_TIERS)
            if row.best_quality and (not existing.best_quality or ranks.index(row.best_quality)>ranks.index(existing.best_quality)):existing.best_quality=row.best_quality
            db.delete(row)
        else:row.canonical_uid=target_uid
    for row in db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(ProductionOrderCompletion).where(
            ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==target_uid,
            ProductionOrderCompletion.avesta_day==row.avesta_day,ProductionOrderCompletion.order_key==row.order_key
        )).scalar_one_or_none()
        if existing:db.delete(row)
        else:row.canonical_uid=target_uid

    # Merge Seedling Life data so Twitch/Discord remain one character after linking.
    source_life=db.execute(select(LifeState).where(LifeState.channel_id==channel,LifeState.canonical_uid==source_uid)).scalar_one_or_none()
    target_life=db.execute(select(LifeState).where(LifeState.channel_id==channel,LifeState.canonical_uid==target_uid)).scalar_one_or_none()
    if source_life:
        if target_life:
            for field in ("energy","nutrition","social","comfort","morale"):
                setattr(target_life,field,max(getattr(target_life,field),getattr(source_life,field)))
            for field in ("gardening","exploration_hobby","mechanics","research_hobby","games_hobby","rockwatching"):
                setattr(target_life,field,getattr(target_life,field)+getattr(source_life,field))
            db.delete(source_life)
        else:source_life.canonical_uid=target_uid
    for row in db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==source_uid)).scalars().all():
        existing=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==target_uid,QualityGear.item_key==row.item_key,QualityGear.quality==row.quality)).scalar_one_or_none()
        if existing:
            existing.qty+=row.qty;existing.condition=max(existing.condition,row.condition);db.delete(row)
        else:row.canonical_uid=target_uid
    # Delete old pairs before inserting their canonical aggregate (unique-safe).
    rels=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel)).scalars().all()
    combined={}
    for row in rels:
        a=target_uid if row.uid_a==source_uid else row.uid_a
        b=target_uid if row.uid_b==source_uid else row.uid_b
        if a!=b:
            pair=tuple(sorted((a,b)));combined[pair]=combined.get(pair,0)+row.familiarity
        db.delete(row)
    db.flush()
    for (a,b),points in combined.items():db.add(LifeRelationship(channel_id=channel,uid_a=a,uid_b=b,familiarity=points))

    old_state=db.get(SeedlingState,(channel,source_uid))
    new_state=db.get(SeedlingState,(channel,target_uid))
    if old_state:
        if new_state:
            history=json.loads(new_state.occupation_history)+json.loads(old_state.occupation_history)
            new_state.occupation_history=json.dumps(history)
            fractions=json.loads(new_state.practice)
            for key,value in json.loads(old_state.practice).items():fractions[key]=fractions.get(key,0)+value
            new_state.practice=json.dumps(fractions)
            if not new_state.last_progress:new_state.last_progress=old_state.last_progress
            db.delete(old_state)
        else:old_state.canonical_uid=target_uid

    if 'task_queue' in globals():task_queue.merge_accounts(sys.modules[__name__],db,channel,source_uid,target_uid)

    # Redirect every related identity/history row, then remove obsolete link codes.
    for row in db.execute(select(Identity).where(Identity.channel_id==channel,Identity.canonical_uid==source_uid)).scalars().all():row.canonical_uid=target_uid
    for row in db.execute(select(ActionLog).where(ActionLog.channel_id==channel,ActionLog.canonical_uid==source_uid)).scalars().all():row.canonical_uid=target_uid
    for row in db.execute(select(LinkCode).where(LinkCode.channel_id==channel,LinkCode.canonical_uid==source_uid)).scalars().all():db.delete(row)
    db.commit()
    return bool(source)
def achieve(db,p):
    notes=[]
    order_count=len(db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==p.channel_id,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all())
    crafted={r.recipe:r for r in db.execute(select(CraftLedger).where(CraftLedger.channel_id==p.channel_id,CraftLedger.canonical_uid==p.twitch_uid)).scalars().all()}
    all_parts=set(PART_RECIPES).issubset(crafted)
    masterwork=any(r.best_quality=="Masterwork" for r in crafted.values())
    tests=[
        ("getting_established",p.actions>=10,"Getting Established"),
        ("society_builder",p.contribution>=50,"Society Builder"),
        ("seed_saver",p.sc>=250,"Seed Coin Saver"),
        ("component_catalog",all_parts,"Complete Component Catalog"),
        ("first_production_order",order_count>=1,"First Production Order"),
        ("production_partner",order_count>=10,"Seed Industries Production Partner"),
        ("master_supplier",order_count>=30,"Master Supplier"),
        ("masterwork_made",masterwork,"First Masterwork"),
    ]
    for code,ok,label in tests:
        if not ok:continue
        r=db.execute(select(Achievement).where(Achievement.channel_id==p.channel_id,Achievement.canonical_uid==p.twitch_uid,Achievement.code==code)).scalar_one_or_none()
        if not r:db.add(Achievement(channel_id=p.channel_id,canonical_uid=p.twitch_uid,code=code));db.commit();notes.append("🏆 "+label)
    return (" "+" | ".join(notes)) if notes else ""

@app.get("/health")
def health():return {"ok":True,"game":GAME_TITLE,"society":GAME_NAME,"version":"7.0.0"}

@app.get("/api/v1/start")
def start(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        discord=f"🌱 {p.display_name} — Citizen Ready\n\n🪙 Starting balance: {p.sc} SC\n💼 Next: choose a job with /job\n🧭 Need direction? Use /guide"
        twitch=f"🌱 {p.display_name} is ready in New Eridian with {p.sc} SC. Next: !job to choose work, then !guide for your best action."
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/profile")
@colony_command
def profile(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        job_name=JOBS.get(p.job,("Settler",set()))[0];b=business_for(db,p);active=len(active_bonuses(db,p));identity=citizen_title(p)
        discord=(f"🌱 Seedling {p.display_name} — {identity}\n\n"
                 f"💼 Occupation / Job: {job_name}\n🪙 Seed Coin: {p.sc} SC\n⭐ Contribution: {p.contribution}\n\n"
                 f"🌿 Life: Farming L{lvl(p.farm_xp)} · Processing L{lvl(p.environmental_xp)}\n"
                 f"🏭 Production: Harvesting L{lvl(p.mining_xp)} · Crafting L{lvl(p.fabrication_xp)} · Engineering L{lvl(p.infrastructure_xp)}\n"
                 f"🍳 Care: Cooking L{lvl(p.cooking_xp)} · Medicine L{lvl(p.medicine_xp)} · Emergency Response L{lvl(p.emergency_xp)}\n"
                 f"🛰️ Operations: Research L{lvl(p.research_xp)} · Logistics L{lvl(p.delivery_xp)} · Frontier L{lvl(p.explore_xp)} · Commerce L{lvl(p.commerce_xp)}\n\n"
                 +(f"\n🏢 Business: {b.name} · Level {b.level}" if b else "\n🏢 Business: Not registered")+f"\n⚡ Active bonuses: {active}\n\nUse /progress section:Skills & Level Unlocks for XP details or /guide for your personal next step.")
        title=equipped_title(db,p);display=f"{p.display_name}"+(f" — {title}" if title else "")
        discord=discord.replace(f"👤 {p.display_name}",f"👤 {display}")+"\n\n"+tutorial_text(db,p,provider)
        twitch=f"👤 {display} | {identity} | 🪙{p.sc} SC | ⭐{p.contribution} | 🏢{b.name+' L'+str(b.level) if b else 'No business'} | ⚡{active} bonuses | 🌱{lvl(p.farm_xp)} 💧{lvl(p.environmental_xp)} ⛏️{lvl(p.mining_xp)} ⚙️{lvl(p.fabrication_xp)} 🏗️{lvl(p.infrastructure_xp)} 🔬{lvl(p.research_xp)} 📦{lvl(p.delivery_xp)} 🧭{lvl(p.explore_xp)} 🏪{lvl(p.commerce_xp)}"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/skills")
@colony_command
def skills(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        specs={r.skill:SPECIALIZATIONS.get(r.skill,{}).get(r.choice,r.choice) for r in db.execute(select(Specialization).where(Specialization.channel_id==channel,Specialization.canonical_uid==p.twitch_uid)).scalars()}
        rows=[f"• {label}: Lv. {lvl(skill_xp(p,key))} · {skill_xp(p,key)} XP"+(f" · {specs[key]}" if key in specs else "") for key,label in SKILL_LABELS.items()]
        text=f"🧬 {p.display_name} — Skills\n\n"+"\n".join(rows)
        text+="\n\nThe eight skill families use the names in your reference screenshots. Research, Logistics, Frontier Operations and Commerce remain minigame skills. Existing XP is preserved; new skills and branch practice start at zero."
        text+="\nLevel 2: 5 XP; level 3: 12 XP; level 4: 22 XP; level 5: 35 XP; then 15 XP per level. Open /training and select Skill to view branches, requirements, jobs and your branch levels. Choose Task only when ready to work. Specializations unlock at main skill level 10; specialist medical branches require Medicine 5."
        return PlainTextResponse(text) if provider=="discord" else out("Skills | "+" · ".join(rows))


@app.get("/api/v1/specialize")
@colony_command
def specialize(channel:str,uid:str,name:str="Citizen",path:str="",provider:str="twitch"):
    path=path.lower().strip().replace(" ","_")
    if ":" not in path:return out("🧬 Choose skill:path. Example: research:siro_analyst. Use /specialize choices in Discord.")
    skill,choice=path.split(":",1)
    if skill not in SPECIALIZATIONS or choice not in SPECIALIZATIONS[skill]:return out("⛔ Unknown specialization path.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if lvl(skill_xp(p,skill))<10:return out(f"🔒 {SKILL_LABELS[skill]} Lv. 10 required. You are Lv. {lvl(skill_xp(p,skill))}.")
        existing=specialization_for(db,p,skill)
        if existing:return out(f"🧬 {SKILL_LABELS[skill]} is already specialized as {SPECIALIZATIONS[skill][existing.choice]}.")
        db.add(Specialization(channel_id=channel,canonical_uid=p.twitch_uid,skill=skill,choice=choice));db.commit()
        return out(f"🧬 {p.display_name} specialized as {SPECIALIZATIONS[skill][choice]}. Matching actions gain +3% success and +1 SC.")

@app.get("/api/v1/cooldowns")
def cooldowns(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);text=cooldowns_text(db,p,provider);return PlainTextResponse(text) if provider=="discord" else out(text)

@app.get("/api/v1/bonuses")
def bonuses(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);text=bonuses_text(db,p,provider);return PlainTextResponse(text) if provider=="discord" else out(text)

def guide_material_step(key,provider):
    prefix="/" if provider=="discord" else "!"
    routes={
        "crops":f"{prefix}farm action:Harvest Crops" if provider=="discord" else "!harvest",
        "ore":f"{prefix}mine","rare_ore":f"{prefix}rare","components":("/make recipe:component" if provider=="discord" else "!make component"),
        "cargo":f"{prefix}cargo",
    }
    return routes.get(key,f"/make recipe:{key}" if provider=="discord" else f"!make {key}")

def guide_three_steps(db,p,s,w,clock,provider):
    prefix="/" if provider=="discord" else "!";life=life_state(db,p);steps=[]
    if life.comfort<20:steps.append(f"Use {prefix}sleep to restore Comfort; poor Comfort reduces output and morale.")
    if life.energy<TASK_NEED_MINIMUM:steps.append(f"Use {prefix}sleep to raise Energy to at least {TASK_NEED_MINIMUM}.")
    if life.nutrition<TASK_NEED_MINIMUM:steps.append(f"Use {prefix}eat; emergency food is available if you own none.")
    if life.social<TASK_NEED_MINIMUM:steps.append(f"Use {prefix}games to raise Social to at least {TASK_NEED_MINIMUM}.")
    if len(steps)<3 and w.active_event:
        cfg=EVENTS[w.active_event];cmd,_=guide_action(db,p,cfg["primary"],provider);steps.append(f"Help {cfg['name']} with {cmd}.")
    tier_index=society_tier_index(s)
    for order_key,data in available_production_orders(p.channel_id,clock["day"],tier_index):
        if len(steps)>=3:break
        if order_completed(db,p,clock["day"],order_key):continue
        missing=[key for key,amount in data["cost"].items() if material_amount(db,p,key)<amount]
        if missing:
            key=missing[0];steps.append(f"Prepare {resource_name(key)} for {data['name']}: {guide_material_step(key,provider)}.")
        else:
            cmd=f"{prefix}seedindustries action:Fulfill item:{order_key}" if provider=="discord" else f"{prefix}seedindustries fulfill {order_key}"
            steps.append(f"Deliver the ready {data['name']} with {cmd}.")
        break
    d=daily(db,p)
    if len(steps)<3 and not d.complete:steps.append(f"Advance the Daily Contract with {guide_command(d.action,provider)} ({d.progress}/{d.target}).")
    directive,dcfg=directive_for(db,p.channel_id,clock["day"])
    if len(steps)<3 and not directive.complete:
        best=min(dcfg[2],key=lambda sk:action_wait(db,p,SKILL_ACTIONS[sk][0]));cmd,_=guide_action(db,p,best,provider)
        steps.append(f"Support today's {dcfg[1]} with {cmd} ({directive.progress}/{directive.goal}).")
    if len(steps)<3:
        stats={"Food":s.food,"Materials":s.materials,"Development":s.development,"Knowledge":s.knowledge,"Treasury":s.treasury,"Reputation":s.reputation};weak=min(stats,key=stats.get)
        route={"Food":guide_command("harvest",provider),"Materials":guide_command("mine",provider),"Development":guide_command("repair",provider),"Knowledge":guide_command("research",provider),"Treasury":guide_command("market",provider),"Reputation":guide_command("spaceport",provider)}[weak]
        steps.append(f"Strengthen New Eridian's lowest stat, {weak} ({stats[weak]}), with {route}.")
    if len(steps)<3:steps.append(f"Review production demand with {prefix}seedindustries action:Orders" if provider=="discord" else "Review production demand with !seedindustries orders.")
    return steps[:3]

@app.get("/api/v1/guide")
@colony_command
def guide(channel:str,uid:str,name:str="Citizen",goal:str="auto",provider:str="twitch"):
    goal=goal.lower().strip().replace(" ","_") or "auto"
    aliases={"money":"seed_coin","coins":"seed_coin","skill":"aptitude","skills":"aptitude","craft":"crafting"}
    goal=aliases.get(goal,goal)
    valid={"auto","event","daily","seed_coin","society","aptitude","crafting","home","business","life","story","market"}
    if goal not in valid:return out("🧭 Guide goals: auto, event, daily, seed_coin, society, aptitude, crafting, home, business, life, story, market.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);s=society(db,channel);clock=world_clock(db,channel,s);w=world(db,channel);resolve_expired_event(db,s,w)
        prefix="/" if provider=="discord" else "!"
        lines=[f"🧭 {p.display_name} — New Eridian Field Guide"]
        event_lines=[]
        if w.active_event:
            cfg=EVENTS[w.active_event];seconds=max(0,int((as_utc(w.event_ends)-now()).total_seconds()));primary,pwait=guide_action(db,p,cfg["primary"],provider);support,swait=guide_action(db,p,cfg["support"],provider)
            pstate="ready" if not pwait else f"{pwait}s cooldown";sstate="ready" if not swait else f"{swait}s cooldown"
            event_lines=[f"🚨 NOW: {cfg['name']} — {w.event_progress}/{w.event_goal}, {seconds//60}:{seconds%60:02d} left.",f"Best help: {primary} ({SKILL_LABELS[cfg['primary']]}, +1 progress, {pstate}).",f"Support: {support} ({SKILL_LABELS[cfg['support']]}, 2 successes = +1, {sstate})."]
        life=life_state(db,p)
        blocked_core=[]
        if life.energy<TASK_NEED_MINIMUM:blocked_core.append(("Energy",life.energy,f"{prefix}sleep or {prefix}relax"))
        if life.nutrition<TASK_NEED_MINIMUM:blocked_core.append(("Nutrition",life.nutrition,f"{prefix}eat; it provides a free emergency meal if you have no food"))
        social_fix=(f"{prefix}games or {prefix}social" if provider=="discord" else "!games, !hi <name>, or !hangout <name>")
        if life.social<TASK_NEED_MINIMUM:blocked_core.append(("Social",life.social,social_fix))
        selected=goal
        if goal=="auto":
            d=daily(db,p)
            critical=min(life.energy,life.nutrition,life.social,life.comfort,life.morale)<25
            selected="life" if critical else ("event" if w.active_event else ("daily" if not d.complete else "story"))
        elif goal!="life" and blocked_core:
            lines.append(f"⛔ {goal.replace('_',' ').title()} guidance is paused because your core needs block tasks.")
            selected="life"
        if selected=="life":
            if blocked_core:
                lines.append(f"🏠 Work, crafting, and gear repair require Energy, Nutrition, and Social at {TASK_NEED_MINIMUM} or higher.")
                lines.extend(f"• {label} {value}/100: use {fix}." for label,value,fix in blocked_core)
                lines.append("Raise every need listed above, then retry your task. Blocked attempts consume nothing and start no cooldown.")
            else:
                needs={"Energy":life.energy,"Nutrition":life.nutrition,"Social":life.social,"Comfort":life.comfort,"Morale":life.morale};low=min(needs,key=needs.get)
                routes={"Energy":f"{prefix}sleep or {prefix}relax","Nutrition":f"{prefix}eat","Social":social_fix,"Comfort":f"{prefix}relax","Morale":f"{prefix}walk or {prefix}hobby"}
                lines.extend([f"✅ Your core needs are high enough for tasks.",f"🏠 {low} is your lowest life need at {needs[low]}/100. Use {routes[low]} to improve it."])
        elif selected=="story":
            row,cfg=story_state(db,channel,clock);vals=[row.track_a,row.track_b,row.track_c];best=min(range(3),key=lambda i:vals[i]);skills=cfg["tracks"][best][1];skill=min(skills,key=lambda x:skill_xp(p,x));cmd,wait=guide_action(db,p,skill,provider)
            lines.extend([f"📖 Weekly story: {cfg['name']} — {sum(vals)}/{cfg['goal']}.",f"The least-supported path is {cfg['tracks'][best][0]}. Try {cmd} "+("now." if not wait else f"in {wait}s.")])
        elif selected=="market":
            a,b=market_demand(channel,clock["day"]);market_view=f"{prefix}market action:View Prices" if provider=="discord" else f"{prefix}marketboard";market_sell=f"{prefix}market action:Sell Resources" if provider=="discord" else "!sell <resource> <amount>";npc_view=f"{prefix}seedindustries";lines.extend([f"🏪 Highest rotating demand today: {resource_name(a)} (60% premium); {resource_name(b)} (30% premium).",f"Check {market_view}, then use {market_sell}. Use {npc_view} for fixed-price components."])
        elif selected=="event":
            lines.extend(event_lines or ["✅ No emergency is active. Work on your daily contract or New Eridian's weakest stat.",f"Next: {prefix}guide goal:daily" if provider=="discord" else "Next: !guide daily"])
        elif selected=="daily":
            d=daily(db,p);cmd=guide_command(d.action,provider);wait=action_wait(db,p,d.action)
            if d.complete:lines.extend(["📋 Today's contract is complete.",f"Next: {prefix}guide goal:society" if provider=="discord" else "Next: !guide society"])
            else:lines.extend([f"📋 Daily: {action_display_name(d.action)} {d.progress}/{d.target}.",f"Do {cmd} next"+(f" when its {wait}s cooldown ends." if wait else " now.")+f" Reward: {d.reward_sc} SC +1 Contribution."])
        elif selected=="seed_coin":
            job_actions=[a for a in JOBS.get(p.job,("",set()))[1] if a in ACTION_SKILLS and a not in {"build","businessinvest"}]
            owned_business=business_for(db,p)
            job_actions=[a for a in job_actions if not (
                (a in SEED_TASKS and (lvl(skill_xp(p,SEED_TASKS[a]["skill"]))<SEED_TASKS[a]["unlock"] or any(material_amount(db,p,k)<v for k,v in SEED_TASKS[a]["cost"].items()))) or
                (a in {"business","businesscontract"} and not owned_business) or
                (a=="delivery" and p.cargo<=0) or
                (a=="survey" and item(db,channel,p.twitch_uid,"sensor")<=0) or
                (a=="craft" and p.ore<=0) or
                (provider=="discord" and a in {"work","machine","craft"})
            )]
            ranked=sorted((action_wait(db,p,a),a) for a in job_actions)
            if ranked:wait,a=ranked[0];reason=f"your {JOBS[p.job][0]} job adds +1 SC"
            else:
                a="market";wait=action_wait(db,p,a);reason="it has strong base pay"
            contract_view=f"{prefix}progress section:Daily Contract" if provider=="discord" else f"{prefix}contracts";lines.extend([f"🪙 You have {p.sc} SC. Do {guide_command(a,provider)} "+("now" if not wait else f"in {wait}s")+f"; {reason}.",f"Use {contract_view} for today's bonus, and {prefix}job to change your paid specialty."])
        elif selected=="society":
            stats={"food":s.food,"materials":s.materials,"development":s.development,"knowledge":s.knowledge,"treasury":s.treasury,"reputation":s.reputation};weak=min(stats,key=stats.get)
            routes={"food":("cultivation","harvest"),"materials":("extraction","mine"),"development":("infrastructure","repair"),"knowledge":("research","research"),"treasury":("commerce","market"),"reputation":("logistics","spaceport")};skill,a=routes[weak];wait=action_wait(db,p,a);tier=society_tier(s);next_tier=next((x for x in SOCIETY_TIERS if x[1]>min(stats.values())),None)
            lines.extend([f"🏗️ Priority: {weak.title()} is lowest at {stats[weak]}. Do {guide_command(a,provider)} "+("now." if not wait else f"in {wait}s."),f"Tier: {tier[0]}. "+(f"Reach {next_tier[1]} in every major stat for {next_tier[0]}." if next_tier else "Regional Hub is fully unlocked.")])
        elif selected=="aptitude":
            skill=min(SKILL_LABELS,key=lambda x:skill_xp(p,x));cmd,wait=guide_action(db,p,skill,provider);level=lvl(skill_xp(p,skill))
            lines.extend([f"🧬 Lowest aptitude: {SKILL_LABELS[skill]} Lv. {level} ({skill_xp(p,skill)} XP).",f"Train it with {cmd} "+("now." if not wait else f"in {wait}s.")+(f" At Lv. 10, use {prefix}specialize." if level<10 else f" Use {prefix}specialize if you have not chosen a path.")])
        elif selected=="crafting":
            if p.ore<=0:step=f"Start with {prefix}mine to obtain Hematite Ore."
            elif p.components<=0:step=("Use /make recipe:component to turn 1 Hematite Ore into 1 Component." if provider=="discord" else "Use !make component to turn 1 Hematite Ore into 1 Component.")
            else:step=("Open /make category:tree" if provider=="discord" else "Open !recipes tree")+" and follow Raw Materials → Basic Components → Advanced Components → Final Products."
            lines.append(f"{prefix}workshop shows personal recipe tiers, manufacturing progress and exact station access. {prefix}seedindustries sells starter inputs; {prefix}catalog explains ingredient sources.")
            lines.extend([f"⚙️ Production route: Crops {p.crops} · Hematite Ore {p.ore} · Components {p.components} · Argentite Ore {p.rare_ore} · Cargo {p.cargo}.",step])
        elif selected=="home":
            h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none();tier=h.tier if h else 1;cost,component_cost=home_upgrade_cost(tier)
            lines.extend(habitat_upgrade_plan(p,tier,provider))
        elif selected=="business":
            b=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
            if b:
                business_routes=f"Best income: {prefix}business action:Contract. Growth: {prefix}business action:Invest. Routine work: {prefix}business action:Work." if provider=="discord" else f"Best income: {prefix}businesscontract. Growth: {prefix}businessinvest. Routine work: {prefix}businesswork."
                lines.extend([f"🏢 {p.display_name}, {b.name} is Level {b.level} with {b.xp}/{business_xp_needed(b.level)} XP.",business_routes])
            else:
                business_start_command=f"{prefix}business action:Start" if provider=="discord" else f"{prefix}businessstart"
                lines.extend([f"🏢 A business costs 75 SC; you have {p.sc}.",(f"Earn {75-p.sc} more SC with "+("/guide goal:seed_coin" if provider=="discord" else "!guide seed_coin")+f", then use {business_start_command}." if p.sc<75 else f"✅ You can afford to start now. Use {business_start_command}.")])
        if selected!="event" and event_lines:lines.extend(["",*event_lines])
        steps=guide_three_steps(db,p,s,w,clock,provider)
        lines.extend(["","🧬 TASK COST FORECAST","• Standard work and /make: -2 Energy/-1 Nutrition/-1 Comfort. Heavy extraction, frontier, and repair work: -3 Energy/-1 Nutrition/-1 Comfort.",f"• Current readiness: Energy {life.energy} · Nutrition {life.nutrition} · Social {life.social}. Each must begin at {TASK_NEED_MINIMUM}+."])
        if goal=="auto":lines.extend(["","NEXT THREE STEPS",*[f"{i}. {step}" for i,step in enumerate(steps,1)]])
        if not w.active_event:lines.extend(["",f"⚡ {auto_event_status(db,w)}"])
        result="\n".join(lines) if provider=="discord" else (f"🧭 {p.display_name} | "+" | ".join(lines[1:lines.index("🧬 TASK COST FORECAST")-1]))
        return PlainTextResponse(result) if provider=="discord" else out(result)

@app.get("/api/v1/inventory")
def inventory(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name)
        toolkit=item(db,channel,c,"toolkit");sensor=item(db,channel,c,"sensor");ration=item(db,channel,c,"ration");crate=item(db,channel,c,"crate")
        next_step="/mine for Hematite Ore" if p.ore<=0 else ("/make recipe:Component" if p.components<=0 else ("/cargo before a delivery" if p.cargo<=0 else "/seedindustries action:Orders"))
        discord=(f"🎒 {p.display_name} — Inventory\n\n📦 RESOURCES\n🌾 Crops: {p.crops}\n⛏️ Hematite Ore: {p.ore}\n💎 Argentite Ore: {p.rare_ore}\n⚙️ Components: {p.components}\n🦆 Cargo: {p.cargo}\n\n🧰 EQUIPMENT & SUPPLIES\nToolkit: {toolkit} · Sensor: {sensor} · Ration: {ration} · Crate: {crate}\n\nPersonal suggestion: use {next_step}.")
        twitch=f"🎒 {p.display_name} | Resources: Crops {p.crops}, Hematite Ore {p.ore}, Argentite Ore {p.rare_ore}, Components {p.components}, Cargo {p.cargo} | Gear: Toolkit {toolkit}, Sensor {sensor}, Ration {ration}, Crate {crate}"
        owned=db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==p.twitch_uid,ExtraItem.qty>0)).scalars().all()
        basic_rows=[f"{craft_item_name(key)}: {craft_output_amount(db,p,key)}" for key in BASIC_COMPONENT_KEYS if key not in item_identity.RETIRED_RECIPES]
        advanced_rows=[f"{craft_item_name(key)}: {craft_output_amount(db,p,key)}" for key in ADVANCED_COMPONENT_KEYS if key not in item_identity.RETIRED_RECIPES]
        discord+="\n\n🔩 BASIC COMPONENTS\n"+"\n".join("• "+x for x in basic_rows)
        discord+="\n\n⚙️ ADVANCED COMPONENTS\n"+"\n".join("• "+x for x in advanced_rows)
        discord+="\n\nACTIVE ITEM EFFECTS\n"+"\n".join(f"{r.item.replace('_',' ').title()} x{r.qty}: {ITEM_EFFECTS[r.item]}" for r in owned if r.item in ITEM_EFFECTS)
        extra=[r for r in owned if r.item in {k for cfg in SEED_TASKS.values() for k in (*cfg['cost'],*cfg['output'])} and r.item not in seed_content.ACTIVE and r.item not in {'ration','biofiber','alloy_plate','circuit_board','components','precision_lens'}]
        if extra:
            discord+="\n\nTRAINING SUPPLIES\n"+"\n".join(f"• {resource_name(r.item)} ×{r.qty}" for r in extra)
            twitch+=' | Training supplies: '+', '.join(f"{resource_name(r.item)} {r.qty}" for r in extra)
        seed_stock=[r for r in owned if r.item in seed_content.ITEMS]
        if seed_stock:
            discord+="\n\nSUPPLIES\n"+"\n".join(f"• {resource_name(r.item)} ×{r.qty}" for r in seed_stock[:10])
            discord+=f"\n{len(seed_stock)} item types. /catalog owned:True shows your full stock."
            twitch+=f" | Supplies: {len(seed_stock)} types; use /catalog in Discord"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/job")
@colony_command
def job(channel:str,uid:str,name:str="Citizen",job:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);job=job.lower().strip()
        if job not in JOBS:return out("💼 Jobs: "+", ".join(k for k in JOBS if k!="cultivator"))
        st=colony_seedling(db,p)
        history=json.loads(st.occupation_history)
        if p.job!=job:history.append({"from":p.job,"to":job,"at":now().isoformat()})
        st.occupation_history=json.dumps(history)
        p.job=job;p.last_job_change=now();db.commit();note=tutorial_advance(db,p,"job");return out(f"💼 {p.display_name} has occupation {JOBS[job][0]}. Matching work earns bonus SC, practice and +2% success."+note)

@app.get("/api/v1/contracts")
def contracts(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);d=daily(db,p);st="COMPLETE" if d.complete else f"{d.progress}/{d.target}"
        cmd=guide_command(d.action,provider)
        discord=f"📋 {p.display_name} — Daily Contract\n\nTask: {cmd}\nProgress: {st}\nReward: {d.reward_sc} SC + 1 Contribution"+("\n\n✅ Contract complete." if d.complete else f"\n\nNext: use {cmd}.")
        twitch=f"📋 Daily Contract | {cmd} {st} | Reward {d.reward_sc} SC +1 Contribution"+(" | Complete!" if d.complete else "")
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/achievements")
def achievements(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);achieve(db,p)
        rows=db.execute(select(Achievement).where(Achievement.channel_id==channel,Achievement.canonical_uid==p.twitch_uid)).scalars().all()
        names=[r.code.replace("_"," ").title() for r in rows]
        order_count=len(db.execute(select(ProductionOrderCompletion).where(ProductionOrderCompletion.channel_id==channel,ProductionOrderCompletion.canonical_uid==p.twitch_uid)).scalars().all())
        crafted={r.recipe for r in db.execute(select(CraftLedger).where(CraftLedger.channel_id==channel,CraftLedger.canonical_uid==p.twitch_uid)).scalars().all()}
        progress=[f"Actions: {min(p.actions,10)}/10",f"Contribution: {min(p.contribution,50)}/50",f"Seed Coin: {min(p.sc,250)}/250 SC",f"Component catalog: {len(set(PART_RECIPES)&crafted)}/{len(PART_RECIPES)}",f"Production Orders: {order_count}/1 · {order_count}/10 · {order_count}/30"]
        discord=(f"🏆 {p.display_name} — Achievements & Milestones\n\nUNLOCKED\n"+
                 ("\n".join(f"• {x}" for x in names) if names else "• None yet")+
                 "\n\nACTIVE PROGRESS\n"+"\n".join(f"• {x}" for x in progress)+
                 "\n\nMilestone titles unlock at 1, 10, and 30 completed Production Orders. Crafting every Basic Component and producing a Masterwork have their own achievements.")
        return platform_response(provider,discord,"🏆 "+(", ".join(names) if names else "No achievements yet."))

def habitat_upgrade_plan(p,tier,provider):
    cost,components=home_upgrade_cost(tier)
    missing_sc=max(0,cost-p.sc);missing_components=max(0,components-p.components)
    upgrade="/home action:upgrade" if provider=="discord" else "!homeup"
    lines=[f"🏠 Habitat Tier {tier} → Tier {tier+1}",
           f"Upgrade cost: {cost} SC and {components} Components.",
           f"You have: {p.sc} SC and {p.components} Components."]
    missing=[]
    if missing_sc:missing.append(f"{missing_sc} SC")
    if missing_components:missing.append(f"{missing_components} Components")
    if not missing:
        lines.append(f"✅ Ready to upgrade. Use {upgrade}.")
        return lines
    lines.append("Still needed: "+" and ".join(missing)+".")
    if missing_sc:
        earn="/guide goal:seed_coin" if provider=="discord" else "!guide seed_coin"
        lines.append(f"Earn the remaining {missing_sc} SC: use {earn}.")
    if missing_components:
        ore=max(0,missing_components-p.ore)
        if ore:lines.append(f"Gather {ore} more Hematite Ore with {'/mine' if provider=='discord' else '!mine'}.")
        craft="/make recipe:component" if provider=="discord" else "!make component"
        lines.append(f"Craft {missing_components} Components with {craft} ({missing_components} crafts; 1 Hematite Ore each).")
    lines.append(f"Then use {upgrade}. Nothing spent yet.")
    return lines

@app.get("/api/v1/home")
def home(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if not h:h=Home(channel_id=channel,canonical_uid=p.twitch_uid);db.add(h);db.commit()
        plan=habitat_upgrade_plan(p,h.tier,provider)
        return platform_response(provider,"\n".join(plan)," | ".join(plan))


@app.get("/api/v1/home/upgrade")
@colony_command
def homeup(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);h=db.execute(select(Home).where(Home.channel_id==channel,Home.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if not h:h=Home(channel_id=channel,canonical_uid=p.twitch_uid);db.add(h);db.commit()
        cost,component_cost=home_upgrade_cost(h.tier)
        if p.sc<cost or p.components<component_cost:
            plan=habitat_upgrade_plan(p,h.tier,provider)
            return platform_response(provider,"⚠️ Upgrade not ready\n\n"+"\n".join(plan)," | ".join(plan))
        spent=cost_text({"sc":cost,"components":component_cost})
        p.sc-=cost;p.components-=component_cost;h.tier+=1;db.commit();return out(f"🏠 Habitat upgraded to Tier {h.tier}! {spent}")

@app.get("/api/v1/business")
def business(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);b=db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none()
        if b:
            contract_pay=5+min(8,b.level);investment_cost=25+10*b.level;discord=f"🏢 {p.display_name} — {b.name}\n\nBusiness level: {b.level}\nProgress: {b.xp}/{business_xp_needed(b.level)} XP\nCurrent contract base pay: {contract_pay} SC before personal bonuses\nCurrent investment cost: {investment_cost} SC\nPersonal bonus chance: 8% per successful action\n\n/business action:Work — routine operation\n/business action:Contract — higher pay and +2 Business XP\n/business action:Invest — +3 Business XP and society growth"
            twitch=f"🏢 {p.display_name} owns {b.name} L{b.level} ({b.xp}/{business_xp_needed(b.level)} XP) | Contract base {contract_pay} SC | !businesswork · !businesscontract · !businessinvest"
        else:
            discord="🏢 No business registered.\n\nCost: 75 SC\nNext: use /business action:Start and choose a name."
            twitch="🏢 No business yet. A business costs 75 SC. Use !businessstart <name>."
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/business/start")
def business_start(channel:str,uid:str,name:str="Citizen",business_name:str="New Venture",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if db.execute(select(Business).where(Business.channel_id==channel,Business.canonical_uid==p.twitch_uid)).scalar_one_or_none():return out("🏢 You already own a business.")
        if p.sc<75:return out("🏢 Starting a business costs 75 SC.")
        p.sc-=75;b=Business(channel_id=channel,canonical_uid=p.twitch_uid,name=clean(business_name));db.add(b);db.commit();return out(f"🏢 {b.name} registered. (-75 SC)")

def normalize_craft_category(value):
    key=(value or "").lower().strip().replace("-","_").replace(" ","_")
    if key.startswith('seed_') and key[5:] in seed_content.CATEGORIES:return key
    if key in CRAFT_BROWSE_OPTIONS:return key
    return CRAFT_CATEGORY_ALIASES.get(key,"")

def craft_item_name(key):
    if key in QUALITY_RECIPES:return QUALITY_RECIPES[key]["name"]
    return resource_name(craft_output_key(key))

def craft_recipe_stage(key):
    for stage,items in CRAFT_STAGE_ITEMS.items():
        if key in items:return stage
    return ""

def craft_tree_text(provider="discord"):
    if provider!="discord":
        return "⚙️ Production Tree | Raw: crops, ore, rare_ore, cargo → Basic: component, biofiber, alloy_plate → Advanced: circuit_board, power_cell, sealant, precision_lens → Final products | Use !make <stage> or !make <recipe>"
    sections=[]
    for stage in CRAFT_CATEGORIES:
        emoji,label,description=CRAFT_CATEGORY_INFO[stage]
        names=" · ".join(craft_item_name(key) for key in CRAFT_STAGE_ITEMS[stage])
        sections.append(f"{emoji} {label.upper()}\n{names}\n{description}")
    return PlainTextResponse(
        "🌳 NEW ERIDIAN PRODUCTION TREE\n\n"+
        "\n\n↓ MANUFACTURE INTO ↓\n\n".join(sections)+
        "\n\nEvery item has one catalog stage. Equipment may support several aptitudes, but it appears only once under Final Products. "
        "Simple supplies can finish from raw or basic inputs; complex equipment uses advanced components."
        "\n\nSelect a recipe alongside Production Tree to preview its exact dependency chain without crafting."
    )

def craft_dependency_text(recipe,provider="discord"):
    import sys
    catalog={**PART_RECIPES,**RECIPES,**{key:data['cost'] for key,data in QUALITY_RECIPES.items()}}
    if recipe not in catalog:return platform_response(provider,"Unknown recipe. Select a recipe from autocomplete.","Unknown recipe.")
    ordered=[];seen=set();raw={};units={}
    def visit(key,amount=1,path=()):
        key='component' if key=='components' else key
        if key in path:raise ValueError('Cyclic crafting dependency: '+key)
        if key not in catalog:
            raw[key]=raw.get(key,0)+amount
            return
        units[key]=units.get(key,0)+amount
        for ingredient,qty in catalog[key].items():visit(ingredient,amount*qty,path+(key,))
        if key not in seen:seen.add(key);ordered.append(key)
    visit(recipe)
    lines=[f"• {requirement_text({part:qty*units[key] for part,qty in catalog[key].items()})} → {units[key]} {craft_item_name(key)}" for key in ordered]
    station_tag=crafting_progression.legacy_station(sys.modules[__name__],recipe)
    station_info=crafting_progression.STATIONS[station_tag]
    message=(f"🌳 {craft_item_name(recipe)} — PRODUCTION TREE\n\nBUILD ORDER\n"+'\n'.join(lines)+
             '\n\nBASE INPUTS TO GATHER OR PREPARE\n'+requirement_text(raw)+
             f"\n\nWORKSTATION: {station_info['name']} · {crafting_progression.tier_hint(station_info['tier'])}. Use /workshop."+
             '\n\nPreview only: nothing spent. Reuse owned parts; Seed Industries sells its listed inputs. Wood comes from /training skill:harvesting, Cloth from /training skill:processing, and Medicine from /training skill:medicine. Training supplies are prepared separately before this build order.'+
             f'\nCraft the final step with /make recipe:{recipe}.')
    return platform_response(provider,message,f"🌳 {craft_item_name(recipe)} | "+' | '.join(lines))

@app.get("/api/v1/recipes")
def recipes(channel:str="new-eridian",provider:str="twitch",category:str=""):
    category=normalize_craft_category(category)
    with SessionLocal() as db:
        society_state=society(db,channel);tier=society_tier(society_state);tier_index=society_tier_index(society_state)
        if category=="tree":return craft_tree_text(provider)
        if category in CRAFT_CATEGORIES:
            emoji,label,description=CRAFT_CATEGORY_INFO[category]
            if category=="raw_materials":
                text="\n".join(f"• {craft_item_name(key)} — {material_source(key,provider)}" for key in RAW_MATERIAL_KEYS)
                text+='\n\nOld and new item names share one inventory balance. Use /gather and /catalog for exact sources.'
            else:
                lines=[]
                for key,item_name,cost,effect,need in craft_category_rows(category):
                    lock=f" · unlocks at {SOCIETY_TIERS[need][0]}" if need is not None and need>tier_index else ""
                    lines.append(f"• {item_name} (`{key}`) — {requirement_text(cost)} · {effect}{lock}")
                text="\n".join(lines)
            if provider=="discord":return PlainTextResponse(f"{emoji} {label}\n\n{description}\n\n{text}\n\nUse /make category:Production Tree to see the full chain.")
            return out(f"{emoji} {label} | "+", ".join(CRAFT_STAGE_ITEMS[category])+" | Use !make <recipe>.")
        if provider=="discord":
            stages="\n".join(f"• {emoji} **{label}** — {description}" for emoji,label,description in CRAFT_CATEGORY_INFO.values())
            return PlainTextResponse(f"⚙️ New Eridian Crafting — {tier[0]}\n\nPRODUCTION STAGES\n{stages}\n\nUse /make category:Production Tree for the complete item tree.")
        return out("⚙️ Crafting stages: raw_materials, basic_components, advanced_components, final_products | Tree: !make tree")

def craft_recipe_key(value):
    alias=(value or '').lower().strip().replace(' ','_')
    if alias in item_identity.RETIRED_RECIPES:return item_identity.RETIRED_RECIPES[alias]
    source=seed_content.find_recipe(value or '')
    if source:return source
    key=(value or "").lower().strip().replace("-","_").replace(" ","_")
    if key in PART_RECIPES or key in RECIPES or key in QUALITY_RECIPES:return key
    plain=(value or "").lower().strip()
    for recipe,data in QUALITY_RECIPES.items():
        if plain==data["name"].lower():return recipe
    return key

def craft_category_rows(category):
    if category in {"basic_components","advanced_components"}:
        keys=[k for k in CRAFT_STAGE_ITEMS[category] if k not in item_identity.RETIRED_RECIPES]
        return [(key,craft_item_name(key),PART_RECIPES[key],PART_EFFECTS[key],0) for key in keys]
    if category=="final_products":
        core=[(key,craft_item_name(key),RECIPES[key],ITEM_EFFECTS[key],RECIPE_TIERS[key]) for key in RECIPES]
        quality=[(key,data["name"],data["cost"],f"Quality-scaled {data['special']}",None) for key,data in QUALITY_RECIPES.items()]
        return core+quality
    return []

def craft_missing_materials(db,p,costs):
    missing=[]
    for key,amount in costs.items():
        have=material_amount(db,p,key)
        if have<amount:missing.append(f"{resource_name(key)}: need {amount}, have {have}, missing {amount-have}")
    return missing

def craft_reward(db,p,s,kind,recipe=""):
    cfg=CRAFT_PAY[kind];job_bonus=1 if p.job=="technician" or occupation_matches(p.job,CRAFT_PRACTICE.get(recipe,("fabrication",None))[0]) else 0
    xp=2 if quality_gear_special(db,p,"assembly_bench")>0 else 1
    p.sc+=cfg["sc"]+job_bonus;p.contribution+=cfg["contribution"];p.actions+=1;p.successes+=1
    s.development+=cfg["development"];xp=gain_skill(p,"fabrication",xp)
    colony_produce(colony_state(db,p.channel_id),s,"make",productivity(life_state(db,p)))
    extra=""
    if recipe in CRAFT_PRACTICE:
        extra_skill,branch=CRAFT_PRACTICE[recipe]
        extra_xp=gain_skill(p,extra_skill,1)
        gain_branch(db,p,branch,extra_xp)
        extra=f" · +{extra_xp} {SKILL_LABELS[extra_skill]} XP ({branch.replace('_',' ').title()})"
    return {"extra":extra,"sc":cfg["sc"]+job_bonus,"xp":xp,"contribution":cfg["contribution"],"development":cfg["development"],"job_bonus":job_bonus}

def craft_system_notes(db,p,s):
    w=world(db,p.channel_id);resolve_expired_event(db,s,w)
    event=event_note(db,s,w,p,"machine")
    project=project_contribute(db,p,"fabrication",1)
    story=story_contribute(db,p,"fabrication")
    return event+important_progress_notes(project,story)

def task_readiness_warning(life,provider="discord"):
    blocked=[]
    if life.energy<TASK_NEED_MINIMUM:blocked.append(("Energy",life.energy,"/sleep" if provider=="discord" else "!sleep"))
    if life.nutrition<TASK_NEED_MINIMUM:blocked.append(("Nutrition",life.nutrition,"/eat" if provider=="discord" else "!eat"))
    if life.social<TASK_NEED_MINIMUM:blocked.append(("Social",life.social,"/games" if provider=="discord" else "!games"))
    if not blocked:return ""
    if provider=="discord":return "\n\n⚠️ RECOVERY NEEDED BEFORE MORE WORK\n"+"\n".join(f"• {label} is now {value}/100. Use {fix}." for label,value,fix in blocked)
    return " | Next task blocked: "+", ".join(f"{label} {value} → {fix}" for label,value,fix in blocked)

def life_change_summary(before,life,provider="discord"):
    fields=[("⚡ Energy",before[0],life.energy),("🍲 Nutrition",before[1],life.nutrition),("🤝 Social",before[2],life.social)]
    changed=[f"{label} {old}→{new}" for label,old,new in fields if old!=new]
    if not changed:return ""
    return ("\n\nNEEDS\n• "+" · ".join(changed)) if provider=="discord" else " | Needs: "+", ".join(changed)

def craft_menu(db,p,channel,provider,category=""):
    society_state=society(db,channel);tier=society_tier(society_state);tier_index=society_tier_index(society_state)
    category=normalize_craft_category(category)
    if category=="tree":return craft_tree_text(provider)
    if provider!="discord":
        if not category:
            return out("⚙️ Production: raw_materials → basic_components → advanced_components → final_products | Tree: !make tree | Craft: !make <recipe>")
        if category=="raw_materials":
            return out(f"⛏️ Raw Materials | Crops {p.crops} · Hematite Ore {p.ore} · Argentite Ore {p.rare_ore} · Cargo {p.cargo} | Gather through work or buy from Seed Industries")
        rows=craft_category_rows(category)
        ready=[key for key,_,cost,_,need in rows if (need is None or tier_index>=need) and not unique_bonus_owned(db,p,key) and not craft_missing_materials(db,p,cost) and not crafting_progression.legacy_gate(sys.modules[__name__],db,p,key,provider)]
        return out(f"⚙️ {CRAFT_CATEGORY_INFO[category][1]} | Ready: {', '.join(ready) or 'none'} | All: {', '.join(key for key,_,_,_,_ in rows)}")

    materials=f"🌾 Crops {p.crops} · ⛏️ Hematite Ore {p.ore} · 💎 Argentite Ore {p.rare_ore} · 📦 Cargo {p.cargo}"
    basic=" · ".join(f"{craft_item_name(key)} {craft_output_amount(db,p,key)}" for key in BASIC_COMPONENT_KEYS)
    advanced=" · ".join(f"{craft_item_name(key)} {craft_output_amount(db,p,key)}" for key in ADVANCED_COMPONENT_KEYS)
    if not category:
        category_lines=[]
        for key in CRAFT_CATEGORIES:
            emoji,label,_=CRAFT_CATEGORY_INFO[key]
            if key=="raw_materials":
                category_lines.append(f"• {emoji} **{label}** — {sum(material_amount(db,p,x) for x in RAW_MATERIAL_KEYS)} total on hand · acquired, not crafted")
                continue
            rows=craft_category_rows(key);ready=0;locked=0;owned_unique=0
            for recipe_key,_,cost,_,need in rows:
                if unique_bonus_owned(db,p,recipe_key):owned_unique+=1
                elif need is not None and tier_index<need:locked+=1
                elif not craft_missing_materials(db,p,cost) and not crafting_progression.legacy_gate(sys.modules[__name__],db,p,recipe_key,provider):ready+=1
            tail=f"Materials available for {ready} / {len(rows)} recipes"
            if locked:tail+=f" · {locked} tier-locked"
            if owned_unique:tail+=f" · {owned_unique} unique item owned"
            category_lines.append(f"• {emoji} **{label}** — {tail}")
        return PlainTextResponse(
            f"⚙️ {p.display_name}'s Fabricator\n\nPRODUCTION TREE\nRaw Materials → Basic Components → Advanced Components → Final Products\n\n"
            f"RAW MATERIALS\n{materials}\n\nBASIC COMPONENTS\n{basic}\n\nADVANCED COMPONENTS\n{advanced}\n\n"
            "CHOOSE ONE STAGE\n"+"\n".join(category_lines)+
            "\n\nUse /make category:Production Tree for the complete item tree. Every item appears in one stage only."
        )

    emoji,label,description=CRAFT_CATEGORY_INFO[category]
    if category=="raw_materials":
        routes='\n'.join(f'• {resource_name(k)}: {material_source(k,provider)}' for k in RAW_MATERIAL_KEYS)
        routes+='\n\n/gather lists every natural resource; /catalog Item gives exact sources and a build plan.'
        return PlainTextResponse(f"{emoji} {label}\n\n{description}\n\nON HAND\n{materials}\n\nHOW TO OBTAIN\n{routes}\n\nNext stage: /make category:basic_components")
    lines=[]
    for key,item_name,cost,effect,need in craft_category_rows(category):
        if unique_bonus_owned(db,p,key):
            status="✅ OWNED · PASSIVE LIMIT 1"
        elif need is not None and tier_index<need:
            status=f"🔒 Unlocks at {SOCIETY_TIERS[need][0]}"
        else:
            missing=craft_missing_materials(db,p,cost)
            status=("❌ Need "+", ".join(missing)) if missing else "✅ READY"
        station_block=crafting_progression.legacy_gate(sys.modules[__name__],db,p,key,provider)
        if station_block:status=station_block
        lines.append(f"• {status} — **{item_name}** (`{key}`)\n  Station: {crafting_progression.STATIONS[crafting_progression.legacy_station(sys.modules[__name__],key)]['name']} · /workshop for access and tier\n  Required: {requirement_text(cost)} · {effect}\n  On hand: {requirement_text({k:material_amount(db,p,k) for k in cost})}")
    footer=("Basic Components stack and feed Advanced Components or simple Final Products." if category=="basic_components" else
            "Advanced Components combine specialized materials and unlock complex Final Products." if category=="advanced_components" else
            "Passive-bonus equipment is limited to one of each item; consumable Rations can stack. Quality gear rolls Crude through Masterwork.")
    return PlainTextResponse(
        f"{emoji} {label} Fabricator\n\n{description}\n\n"
        "AVAILABLE RECIPES\n"+"\n".join(lines)+
        "\n\nCraft with /make recipe:<recipe>. "+footer
    )

@app.get("/api/v1/make")
@colony_command
def make(channel:str,uid:str,name:str="Citizen",recipe:str="",provider:str="twitch",category:str="",page:int=1):
    import sys
    if category and not normalize_craft_category(category):
        return out("⚙️ Unknown crafting category. Choose a category from /make, including the item categories. Nothing spent.")
    category=normalize_craft_category(category)
    recipe_category=normalize_craft_category(recipe)
    recipe=craft_recipe_key(recipe)
    if not category and recipe_category:
        category=recipe_category;recipe=""
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name)
        if category.startswith('seed_'):
            import sys
            if not recipe:
                result=seed_content.recipe_menu(sys.modules[__name__],db,p,category[5:],page)
                return platform_response(provider,result,result.replace('\n',' | '))
            if recipe not in seed_content.RECIPES or seed_content.recipe_category(recipe)!=category[5:]:
                return out('ℹ️ That recipe is not in this category. Choose a Recipe from the filtered suggestions. Nothing spent.')
        if not recipe:
            result=craft_menu(db,p,channel,provider,category)
            if not category and provider=='discord':return PlainTextResponse(result.body.decode()+"\n\nRECIPES\nChoose a Category to browse every recipe by Page, or search Recipe by item name. /catalog shows ingredients; /gather collects natural materials. Use /workshop for required station access and recipe tiers.")
            return result
        if recipe in seed_content.RECIPES:
            if category and category!='tree' and not category.startswith('seed_'):return out('ℹ️ Choose the matching category, leave Category blank, or use Production Tree to preview. Nothing spent.')
            import sys
            module=sys.modules[__name__]
            if category=='tree':return platform_response(provider,seed_content.preview(module,db,p,recipe),seed_content.preview(module,db,p,recipe))
            blocked=task_need_gate(db,p,'make',provider,life_state(db,p))
            if blocked:return platform_response(provider,blocked,blocked)
            result=seed_content.craft(module,db,p,recipe,provider)
            return platform_response(provider,result,result.replace('\n',' | '))
        if category=="tree":return craft_dependency_text(recipe,provider)
        life=life_state(db,p);blocked=task_need_gate(db,p,"make",provider,life)
        if blocked:return PlainTextResponse(blocked) if provider=="discord" else out(blocked)
        if recipe not in PART_RECIPES and recipe not in RECIPES and recipe not in QUALITY_RECIPES:
            return out(f"⚙️ Unknown recipe. Open {'/make' if provider=='discord' else '!make'} with no options, then choose a crafting category.")
        actual_category=craft_recipe_stage(recipe)
        if category and category!=actual_category:
            return out(f"⚙️ {craft_item_name(recipe)} appears once, under {CRAFT_CATEGORY_INFO[actual_category][1]}.")
        station_block=crafting_progression.legacy_gate(sys.modules[__name__],db,p,recipe,provider)
        if station_block:return out(station_block)
        if recipe in QUALITY_RECIPES:
            r=QUALITY_RECIPES[recipe];costs=r["cost"]
            if unique_bonus_owned(db,p,recipe):return out(f"🛑 {p.display_name} already owns {r['name']}. Passive-bonus equipment is limited to one of each item.")
            missing=craft_missing_materials(db,p,costs)
            if missing:return out(f"⚙️ {p.display_name} cannot craft {r['name']}. Missing requirements: "+"; ".join(missing)+"."+missing_material_sources(db,p,costs,provider))
            for key,amount in costs.items():material_change(db,p,key,-amount)
            quality_bonus=int(quality_gear_special(db,p,"precision_tools")*100)
            quality=quality_roll(lvl(p.fabrication_xp),quality_bonus)
            add_quality_gear(db,p,recipe,quality)
            p._practice_quality={"Standard":1.0,"Fine":1.15,"Excellent":1.3,"Masterwork":1.5}.get(quality,1.1)
            rewards=craft_reward(db,p,society(db,channel),"quality",recipe)
            craft_record(db,p,recipe,quality)
            spend_life_for_action(life,"make")
            tier=QUALITY_TIERS[quality]
            effects=[]
            for skill,mult in r["skills"].items():effects.append(f"+{int(tier['skill']*mult*100)}% {SKILL_LABELS[skill]}")
            if tier["special"]>0:effects.append(f"+{int(tier['special']*100)}% {r['special']}")
            if quality_bonus:effects.append(f"Precision Tools improved the quality roll by {quality_bonus} points")
            db.commit();system_notes=craft_system_notes(db,p,society(db,channel))
            detail=", ".join(effects) if effects else r["special"]
            journal_add(db,p,f"Crafted {quality} {r['name']}.")
            goal_note=progress_daily(db,p,"make")+goal_progress(db,p,"make","fabrication",crafted=True)+tutorial_advance(db,p,"craft")
            milestone=achieve(db,p);determination_note=determination_clear(db,p,"fabrication")
            updates=important_progress_notes(goal_note,milestone)+system_notes+determination_note
            text=(f"🛠️ CRAFTING COMPLETE — {p.display_name}\n\n"
                  f"OUTPUT\n• {quality} {r['name']} · Condition 100%\n• {detail}\n\n"
                  f"CHANGE\n• {cost_text(costs)[1:-1]} · -2 Energy · -1 Nutrition · -1 Comfort\n"
                  f"• +{rewards['xp']} Crafting XP{rewards['extra']} · +{rewards['sc']} SC · +{rewards['contribution']} Contribution"
                  +(f" · Matching job bonus included" if rewards['job_bonus'] else "")+
                  f"\n• New Eridian +{rewards['development']} Development"
                  +updates+task_readiness_warning(life,provider))
            return PlainTextResponse(text) if provider=="discord" else out(text.replace("\n"," | "))
        costs=PART_RECIPES.get(recipe) or RECIPES[recipe]
        society_state=society(db,channel);tier_index=society_tier_index(society_state);required=RECIPE_TIERS.get(recipe,0)
        if tier_index<required:return out(f"🔒 {recipe.replace('_',' ').title()} unlocks at society tier {SOCIETY_TIERS[required][0]}.")
        if unique_bonus_owned(db,p,recipe):return out(f"🛑 {p.display_name} already owns {resource_name(recipe)}. Passive-bonus equipment is limited to one of each item.")
        missing=craft_missing_materials(db,p,costs)
        if missing:return out("⚙️ Still needed: "+", ".join(missing)+"."+missing_material_sources(db,p,costs,provider))
        for key,amount in costs.items():material_change(db,p,key,-amount)
        output_key=craft_output_key(recipe);material_change(db,p,output_key,1)
        kind="components" if recipe in PART_RECIPES else "core";rewards=craft_reward(db,p,society_state,kind,recipe);craft_record(db,p,recipe)
        spend_life_for_action(life,"make");db.commit();system_notes=craft_system_notes(db,p,society_state)
        goal_note=progress_daily(db,p,"make")+goal_progress(db,p,"make","fabrication",crafted=True)+tutorial_advance(db,p,"craft")
        purpose=PART_EFFECTS.get(recipe,ITEM_EFFECTS.get(recipe,"Stackable crafting material"))
        milestone=achieve(db,p);determination_note=determination_clear(db,p,"fabrication")
        updates=important_progress_notes(goal_note,milestone)+system_notes+determination_note
        text=(f"⚙️ CRAFTING COMPLETE — {p.display_name}\n\n"
              f"OUTPUT\n• {resource_name(output_key)} x1 · {purpose}\n\n"
              f"CHANGE\n• {cost_text(costs)[1:-1]} · -2 Energy · -1 Nutrition · -1 Comfort\n"
              f"• +{rewards['xp']} Crafting XP{rewards['extra']} · +{rewards['sc']} SC"
              +(f" · +{rewards['contribution']} Contribution" if rewards['contribution'] else "")+
              (f" · Matching job bonus included" if rewards['job_bonus'] else "")+
              f"\n• New Eridian +{rewards['development']} Development"
              +updates+task_readiness_warning(life,provider))
        return PlainTextResponse(text) if provider=="discord" else out(text.replace("\n"," | "))


@app.get("/api/v1/life")
@colony_command
def life_status(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        note=tutorial_advance(db,p,"life")
        base=life_status_text(db,p,"discord" if provider=="discord" else "twitch")+note
        return PlainTextResponse(base) if provider=="discord" else out(base)

@app.get("/api/v1/display")
def display_style(channel:str,uid:str,name:str="Citizen",style:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pref=player_preference(db,p);choice=(style or "").strip().lower()
        if choice:
            if choice not in {"compact","detailed"}:return out("🎨 Display style must be compact or detailed.")
            pref.result_style=choice;db.commit()
        explanation=("Compact shows the outcome, rewards, and only actionable/exceptional notes." if pref.result_style=="compact" else
                     "Detailed also shows every active modifier and the final success chance after each work action.")
        return out(f"🎨 Result style: {pref.result_style.title()}. {explanation} Colors: 🟢 success/growth · 🟡 actions/rewards · 🔵 information · 🔴 blockers/danger · 🟣 social/story · ⚪ supporting detail.")

@app.get("/api/v1/hi")
@colony_command
def hi(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);target_p,error=find_player_name(db,channel,target)
        if error:return out("👋 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🪞 You greet yourself. Rocky declines to comment.")
        wait=check_cooldown(db,p,"hi")
        if wait:return out(f"⏱️ {p.display_name}, hi is ready in {wait}s.")
        me=life_state(db,p);them=life_state(db,target_p)
        before_social=me.social;before_target=them.social
        clock=world_clock(db,channel);extra=1 if clock["phase"]=="Evening" else 0
        me.social=clamp100(me.social+12+extra);me.morale=clamp100(me.morale+1+extra)
        them.social=clamp100(them.social+10);them.morale=clamp100(them.morale+1)
        rel=relationship_add(db,channel,p.twitch_uid,target_p.twitch_uid,3);db.commit()
        memory=relationship_memory(db,channel,p.twitch_uid,target_p.twitch_uid,"Said hi")
        msg=f"👋 {p.display_name} says hi to {target_p.display_name}. +{me.social-before_social} Social; {target_p.display_name} +{them.social-before_target} Social. Morale improved. Relationship: {relationship_label(rel.familiarity)} ({rel.familiarity})."
        if memory.interactions in {5,10,25,50}:msg+=f" 💜 Shared memory milestone: {memory.interactions} activities together."
        msg+=tutorial_advance(db,p,"social")
        log_action(db,channel,p.twitch_uid,"hi",msg)
        return out(msg)

@app.get("/api/v1/hangout")
@colony_command
def hangout(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);target_p,error=find_player_name(db,channel,target)
        if error:return out("🤝 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🪨 Solo Rocky contemplation is /hobby rockwatching, not a hangout.")
        wait=check_cooldown(db,p,"hangout")
        if wait:return out(f"⏱️ {p.display_name}, hangout is ready in {wait}s.")
        me=life_state(db,p);them=life_state(db,target_p);social_gain=30;morale_gain=random.randint(3,6)
        clock=world_clock(db,channel)
        if clock["phase"]=="Evening":social_gain+=2;morale_gain+=1
        me.social=clamp100(me.social+social_gain);me.morale=clamp100(me.morale+morale_gain)
        them.social=clamp100(them.social+max(5,social_gain-2));them.morale=clamp100(them.morale+max(2,morale_gain-1))
        rel=relationship_add(db,channel,p.twitch_uid,target_p.twitch_uid,8);db.commit()
        memory=relationship_memory(db,channel,p.twitch_uid,target_p.twitch_uid,"Hung out")
        scene=random.choice(["trade Avesta stories","watch delivery traffic cross New Eridian","debate Rocky's wisdom","compare suspicious crop yields","spend a cycle doing almost nothing productive"])
        msg=f"🤝 {p.display_name} and {target_p.display_name} {scene}. +{social_gain} Social/+{morale_gain} Morale. Relationship: {relationship_label(rel.familiarity)} ({rel.familiarity})."+goal_progress(db,p,"hangout",None,social=True)
        if memory.interactions in {5,10,25,50}:msg+=f" 💜 Shared memory milestone: {memory.interactions} activities together."
        log_action(db,channel,p.twitch_uid,"hangout",msg);return out(msg)

@app.get("/api/v1/relationships")
def relationships(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel)).scalars().all()
        mine=[r for r in rows if p.twitch_uid in {r.uid_a,r.uid_b}]
        mine=sorted(mine,key=lambda r:r.familiarity,reverse=True)[:10]
        if not mine:
            next_step=("/social action:Say Hi player:<name> or /social action:Hang Out player:<name>" if provider=="discord" else "!hi <name> or !hangout <name>")
            return out(f"🤝 No relationships yet. Use {next_step}.")
        parts=[]
        for r in mine:
            other=r.uid_b if r.uid_a==p.twitch_uid else r.uid_a
            op=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==other)).scalar_one_or_none()
            a,b=relationship_pair(p.twitch_uid,other);memory=db.execute(select(RelationshipMemory).where(RelationshipMemory.channel_id==channel,RelationshipMemory.uid_a==a,RelationshipMemory.uid_b==b)).scalar_one_or_none()
            memory_text=f" · {memory.interactions} shared activities · last: {memory.last_activity}" if memory else ""
            parts.append(f"{op.display_name if op else 'Former Citizen'} — {relationship_label(r.familiarity)} ({r.familiarity}){memory_text}")
        if provider=="discord":return PlainTextResponse("🤝 Relationships\n\n"+"\n".join("• "+x for x in parts))
        return out("🤝 "+" | ".join(parts))

@app.get("/api/v1/relax")
@colony_command
def relax(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"relax")
        if wait:return out(f"⏱️ {p.display_name}, relax is ready in {wait}s.")
        life=life_state(db,p);eg=25;mg=random.randint(4,7)
        life.energy=clamp100(life.energy+eg);life.morale=clamp100(life.morale+mg);life.comfort=clamp100(life.comfort+10);db.commit()
        msg=f"🛋️ {p.display_name} takes real downtime. +{eg} Energy, +{mg} Morale, +10 Comfort (capped at 100)."
        log_action(db,channel,p.twitch_uid,"relax",msg);return out(msg)

@app.get("/api/v1/walk")
@colony_command
def walk(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"walk")
        if wait:return out(f"⏱️ {p.display_name}, walk is ready in {wait}s.")
        life=life_state(db,p);clock=world_clock(db,channel);pw=player_world(db,p);life.energy=clamp100(life.energy-2);life.morale=clamp100(life.morale+(7 if clock["phase"]=="Evening" else 5));life.exploration_hobby+=1
        found=random.random()<.35
        if found:item_add(db,channel,p.twitch_uid,"wild_fibers",1)
        db.commit();msg=f"🌿 {p.display_name} walks beyond the habitat blocks. +{7 if clock['phase']=='Evening' else 5} Morale (capped at 100), -2 Energy, +1 Exploration hobby."+(" Found Wild Fibers x1." if found else "")
        msg+=exposure_tick(db,p,pw,"walk","frontier",clock)+maybe_world_encounter(db,p,"frontier",clock,True)+goal_progress(db,p,"walk","frontier")
        log_action(db,channel,p.twitch_uid,"walk",msg);return out(msg)

@app.get("/api/v1/games")
@colony_command
def games(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"games")
        if wait:return out(f"⏱️ {p.display_name}, games is ready in {wait}s.")
        life=life_state(db,p);old_social=life.social;rolled_social=25;mg=random.randint(4,8)
        life.social=clamp100(life.social+rolled_social)
        recovery_note=""
        if old_social<TASK_NEED_MINIMUM and life.social<TASK_NEED_MINIMUM:
            life.social=25;recovery_note=" Recovery Protocol raised Social above the work minimum."
        sg=life.social-old_social;life.morale=clamp100(life.morale+mg);life.games_hobby+=1;db.commit()
        scene=random.choice(["wins a tiny card tournament","loses badly and demands a rematch","finds a game nobody remembers installing","claims the rules were different last cycle"])
        msg=f"🎲 {p.display_name} {scene}. +{sg} Social, +{mg} Morale, +1 Games hobby."+recovery_note
        msg+=goal_progress(db,p,"games",None,social=True)
        log_action(db,channel,p.twitch_uid,"games",msg);return out(msg)

@app.get("/api/v1/hobby")
@colony_command
def hobby(channel:str,uid:str,name:str="Citizen",hobby:str="",provider:str="twitch"):
    key=(hobby or "").lower().strip()
    if key not in HOBBIES:return out("🎯 Hobbies: "+", ".join(HOBBIES)+".")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);wait=check_cooldown(db,p,"hobby")
        if wait:return out(f"⏱️ {p.display_name}, hobby is ready in {wait}s.")
        life=life_state(db,p);row=hobby_row(db,p,key);row.points+=1;mg=random.randint(4,7);life.morale=clamp100(life.morale+mg)
        found=""
        finds={"gardening":("healthy_cutting",.30),"collecting":("old_label",.18),"scanning":("siro_spore_vial",.10),"mechanics":("damaged_circuit",.18),"rockwatching":("normal_rock",.10),"exploration":("wild_fibers",.20)}
        if key in finds and random.random()<finds[key][1]:
            item,chance=finds[key];name2,first,set_note=collection_add(db,p,item,1);found=f" Found {name2}."+set_note
        elif key=="cooking" and p.crops>0 and random.random()<.25:
            life.nutrition=clamp100(life.nutrition+15);found=" Prepared a surprisingly good snack: +15 Nutrition (capped at 100)."
        elif key=="trading" and random.random()<.20:
            p.sc+=2;found=" Spotted a tiny arbitrage opportunity: +2 SC."
        rank,_=hobby_rank(row.points);db.commit()
        msg=f"🎯 {p.display_name} spends time on {HOBBIES[key][0]}. +{mg} Morale. Hobby progress {row.points} ({rank}).{found}"
        log_action(db,channel,p.twitch_uid,"hobby",msg);return out(msg)



@app.get("/api/v1/tutorial")
def tutorial(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);return out(tutorial_text(db,p,provider))

@app.get("/api/v1/story")
def story(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);row,cfg=story_state(db,channel,clock);vals=[row.track_a,row.track_b,row.track_c];total=sum(vals)
        tracks=" | ".join(f"{cfg['tracks'][i][0]} {vals[i]}" for i in range(3));state=("RESOLVED — "+row.outcome) if row.resolved else f"{total}/{cfg['goal']}"
        if provider=="discord":return PlainTextResponse(f"📖 Weekly Avesta Story — {cfg['name']}\n\n{cfg['text']}\n\nProgress: {state}\n"+"\n".join(f"• {cfg['tracks'][i][0]}: {vals[i]}" for i in range(3))+"\n\nSuccessful matching actions automatically shape the outcome.")
        return out(f"📖 {cfg['name']} | {state} | {tracks} | {cfg['text']}")

@app.get("/api/v1/titles")
def titles(channel:str,uid:str,name:str="Citizen",title:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);refresh_titles(db,p)
        rows=db.execute(select(PlayerTitle).where(PlayerTitle.channel_id==channel,PlayerTitle.canonical_uid==p.twitch_uid).order_by(PlayerTitle.unlocked_at)).scalars().all()
        q=(title or "").strip().lower()
        if q:
            match=next((x for x in rows if x.title_key==q or TITLE_DEFS.get(x.title_key,"").lower()==q),None)
            if not match:return out("🏷️ You have not unlocked that title. Use !titles on Twitch or /me section:Titles on Discord.")
            for x in rows:x.equipped=False
            match.equipped=True;db.commit();return out(f"🏷️ Equipped title: {TITLE_DEFS[match.title_key]}.")
        parts=[("⭐ " if x.equipped else "")+TITLE_DEFS.get(x.title_key,x.title_key) for x in rows]
        return out("🏷️ Titles | "+(" | ".join(parts) if parts else "No titles yet."))

@app.get("/api/v1/marketboard")
def marketboard(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);a,b=market_demand(channel,clock["day"])
        prices={k:max(1,int(v*market_multiplier(channel,clock["day"],k))) for k,v in MARKET_BASE.items()}
        line=" | ".join(f"{resource_name(k)} {prices[k]} SC"+(" 🔥" if k==a else " ↑" if k==b else "") for k in prices)
        return out(f"🏪 Day {clock['day']} Market | {line} | 🔥 highest demand, ↑ elevated demand")

@app.get("/api/v1/sell")
@colony_command
def sell(channel:str,uid:str,name:str="Citizen",resource:str="",amount:int=1,provider:str="twitch"):
    key=(resource or "").lower().strip().replace(" ","_");amount=max(1,min(25,int(amount or 1)))
    key=item_identity.FIELD_ITEMS.get(seed_content.find_item(resource),key)
    if key not in MARKET_BASE:return out("🏪 Sellable: crops, ore, rare_ore, components, cargo.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel)
        if getattr(p,key)<amount:return out(f"🏪 You only have {getattr(p,key)} {resource_name(key)}.")
        unit=max(1,int(MARKET_BASE[key]*market_multiplier(channel,clock["day"],key)));pay=unit*amount
        setattr(p,key,getattr(p,key)-amount);p.sc+=pay;gain_skill(p,"commerce",max(1,amount//3));
        db.add(MarketSale(channel_id=channel,canonical_uid=p.twitch_uid,avesta_day=clock["day"],resource=key,qty=amount,sc_earned=pay));db.commit()
        return out(f"🏪 Sold {amount} {resource_name(key)} for {pay} SC ({unit} each). Day {clock['day']} demand applied.")

@app.get('/api/v1/workshop')
@colony_command
def workshop(channel:str,uid:str,name:str='Citizen',action:str='view',station:str='',page:int=1,provider:str='twitch'):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        result=crafting_progression.workshop(sys.modules[__name__],db,p,action,station,page,provider)
        return platform_response(provider,result,result.replace('\n',' | '))

def market_item_label(key):
    return resource_name(key)

@app.get("/api/v1/seedindustries")
@colony_command
def seed_industries(channel:str,uid:str,name:str="Citizen",action:str="browse",item_name:str="",amount:int=1,provider:str="twitch",page:int=1,category:str="all"):
    action=(action or "browse").lower().strip();key=(item_name or "").lower().strip().replace(" ","_");amount=max(1,min(25,int(amount or 1)))
    if action not in {"browse","buy","sell","orders","fulfill","starters"}:return out("🏭 Seed Industries actions: browse, buy, sell, orders, fulfill, starters.")
    if action=='starters':
        result=crafting_progression.starter_routes(page,provider)
        return platform_response(provider,result,result.replace('\n',' | '))
    if category not in {'all','legacy','seed','training','rare'}:return out('Choose a valid market category. Nothing spent.')
    if key not in SEED_INDUSTRIES:
        key=seed_content.find_item(item_name or '')
    key=item_identity.canonical(key)
    if action=='browse':
        rows=sorted((k for k,v in SEED_INDUSTRIES.items() if category=='all' or v.get('category','legacy')==category),key=market_item_label)
        size=8 if provider=='discord' else 3;pages=max(1,math.ceil(len(rows)/size));page=max(1,min(page,pages))
        category_label={'all':'All Supplies','legacy':'General Materials & Parts','seed':'Starter Supplies','training':'Training Supplies','rare':'Rare Ores'}[category]
        lines=[f'🏭 SEED INDUSTRIES · {category_label} · Page {page}/{pages}', 'Starter supplies; buying saves work but costs SC.']
        for k in rows[(page-1)*size:page*size]:
            v=SEED_INDUSTRIES[k];sale=f"sell {v['sell']}" if v['sell'] else 'no buyback'
            lines.append(f"• {market_item_label(k)}: buy {v['buy']} SC · {sale}"+(f' · {k}' if provider!='discord' else ''))
        lines+=['Select Starter Routes for each branch. Buy + Item + Amount (1–25) purchases supplies. Page/Category browse all stock. New starter supplies have no NPC buyback. Rare ore purchases require Harvesting Lv.3.' if provider=='discord' else '!seedpage <page>; !seedbuy <id> <qty>. Rare: Harvesting Lv3.']
        result='\n'.join(lines)
        return platform_response(provider,result,result.replace('\n',' | '))
    if action in {"orders","fulfill"}:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);tier_index=society_tier_index(society(db,channel));orders=available_production_orders(channel,clock["day"],tier_index)
            if action=="orders":
                rows=[]
                for order_key,data in orders:
                    numbers=production_order_numbers(data);done=order_completed(db,p,clock["day"],order_key);missing=craft_missing_materials(db,p,data["cost"])
                    state="✅ COMPLETED" if done else ("❌ NEED "+", ".join(missing) if missing else "✅ READY TO DELIVER")
                    rows.append(f"• {state} — **{data['name']}** (`{order_key}`)\n  Deliver: {requirement_text(data['cost'])}\n  Reward: {numbers['sc']} SC · {numbers['contribution']} Contribution · {numbers['development']} Development · Crafting/Commerce practice (base 2/1; adjusted by conditions)\n  Purpose: {data['purpose']}")
                discord=(f"🏭 SEED INDUSTRIES — DAY {clock['day']} PRODUCTION ORDERS\n\n"
                         "Three rotating contracts connect gathering, manufacturing, and New Eridian's needs. Each may be completed once per citizen per Avesta day.\n\n"+
                         "\n\n".join(rows)+"\n\nUse /seedindustries action:Fulfill item:<order key>. Buying every input costs more than the order pays; manufacturing creates the profit.")
                twitch=f"🏭 Day {clock['day']} Orders | "+" | ".join(f"{key}: {requirement_text(data['cost'])} → {production_order_numbers(data)['sc']} SC" for key,data in orders)
                return platform_response(provider,discord,twitch)
            match=next(((order_key,data) for order_key,data in orders if order_key==key),None)
            if not match:return out("🏭 That order is not active today. View today's production orders first.")
            order_key,data=match
            if order_completed(db,p,clock["day"],order_key):return out(f"🏭 {data['name']} is already complete for Avesta Day {clock['day']}.")
            missing=craft_missing_materials(db,p,data["cost"])
            if missing:return out(f"🏭 {data['name']} still needs "+", ".join(missing)+(". Use /guide goal:crafting for a production route." if provider=="discord" else ". Use !guide crafting for a production route."))
            for material,qty in data["cost"].items():material_change(db,p,material,-qty)
            numbers=production_order_numbers(data);p.sc+=numbers["sc"];p.contribution+=numbers["contribution"];p.actions+=1;p.successes+=1
            gain_skill(p,"fabrication",2);gain_skill(p,"commerce",1);society(db,channel).development+=numbers["development"]
            db.add(ProductionOrderCompletion(channel_id=channel,canonical_uid=p.twitch_uid,avesta_day=clock["day"],order_key=order_key));db.commit()
            journal_add(db,p,f"Completed Seed Industries order: {data['name']}.");milestone=achieve(db,p)
            text=(f"✅ PRODUCTION ORDER COMPLETE — {data['name']}\n\n"
                  f"DELIVERED\n• {cost_text(data['cost'])[1:-1]}\n\n"
                  f"REWARDS\n• +{numbers['sc']} SC · +{numbers['contribution']} Contribution\n"
                  f"• +2 Crafting XP · +1 Commerce XP\n• New Eridian +{numbers['development']} Development\n\n"
                  f"WHY IT MATTERED\n• {data['purpose']}\n\nNEXT\n• View the remaining Day {clock['day']} orders or continue your daily contract."+milestone)
            return PlainTextResponse(text) if provider=="discord" else out(text.replace("\n"," | "))
    if key not in SEED_INDUSTRIES:return out("🏭 Seed Industries trades: "+", ".join(resource_name(k) for k in SEED_INDUSTRIES)+".")
    listing=SEED_INDUSTRIES[key]
    if category!='all' and listing.get('category','legacy')!=category:return out('That item is in another market category. Nothing spent.')
    if action=='sell' and not listing['sell']:return out('Seed Industries supplies this starter item but does not buy it back. Nothing spent.')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if action=="buy":
            if key in crafting_progression.RARE and lvl(skill_xp(p,'extraction'))<3:
                return out('Rare ore purchases require Harvesting Lv.3 (12 XP). Gather common materials or use /mine first. Nothing spent.')
            total=listing["buy"]*amount
            if p.sc<total:return out(f"🏭 {p.display_name} needs {total} SC to buy {amount} {resource_name(key)}. Current balance: {p.sc} SC.")
            p.sc-=total;material_change(db,p,key,amount);db.commit()
            return out(f"🏭 {p.display_name} bought {amount} {resource_name(key)} from Seed Industries for {total} SC. Balance: {p.sc} SC. Use: {listing['purpose']}.")
        owned=material_amount(db,p,key)
        if owned<amount:return out(f"🏭 {p.display_name} only has {owned} {resource_name(key)}.")
        total=listing["sell"]*amount;material_change(db,p,key,-amount);p.sc+=total;gain_skill(p,"commerce",max(1,amount//3));db.commit()
        return out(f"🏭 {p.display_name} sold {amount} {resource_name(key)} to Seed Industries for {total} SC. Balance: {p.sc} SC. +{max(1,amount//3)} Commerce XP.")

@app.get("/api/v1/duo")
@colony_command
def duo(channel:str,uid:str,name:str="Citizen",target:str="",activity:str="walk",provider:str="twitch"):
    act=(activity or "walk").lower().strip();
    if act not in DUO_ACTIVITIES:return out("🤝 Duo activities: walk, games, research, delivery, explore.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);other,error=find_player_name(db,channel,target)
        if error:return out("🤝 "+error)
        if other.twitch_uid==p.twitch_uid:return out("🤝 Duo activities require another citizen.")
        a,b=sorted((p.twitch_uid,other.twitch_uid))
        rel=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel,LifeRelationship.uid_a==a,LifeRelationship.uid_b==b)).scalar_one_or_none()
        familiarity=effective_relationship(db,rel) if rel else 0;need=DUO_ACTIVITIES[act]
        if familiarity<need:return out(f"🤝 {act.title()} requires a relationship score of {need}. Your current score is {familiarity}.")
        wait=check_cooldown(db,p,"duo_"+act)
        if wait:return out(f"⏱️ Duo {act} is ready in {wait}s.")
        lp,lo=life_state(db,p),life_state(db,other);reward=""
        if act=="walk":lp.morale=clamp100(lp.morale+8);lo.morale=clamp100(lo.morale+6);gain_skill(p,"frontier",1);reward="+8 Morale; Frontier practice"
        elif act=="games":lp.social=clamp100(lp.social+10);lo.social=clamp100(lo.social+8);reward="+10 Social"
        elif act=="research":gain_skill(p,"research",2);gain_skill(other,"research",1);society(db,channel).knowledge+=2;reward="Research practice for both; +2 Knowledge"
        elif act=="delivery":
            if p.cargo<=0:return out("📦 You need 1 Cargo for a duo delivery.")
            p.cargo-=1;p.sc+=8;other.sc+=3;gain_skill(p,"logistics",2);society(db,channel).reputation+=2;reward="+8 SC; Logistics practice; partner +3 SC"
        elif act=="explore":gain_skill(p,"frontier",2);gain_skill(other,"frontier",1);reward="Frontier practice for both"
        before_relationship=rel.familiarity if rel else 0
        updated_relationship=relationship_add(db,channel,p.twitch_uid,other.twitch_uid,6);relationship_gain=updated_relationship.familiarity-before_relationship
        memory=relationship_memory(db,channel,p.twitch_uid,other.twitch_uid,"Duo "+act.title());db.commit();
        milestone=f" Shared memory milestone: {memory.interactions} activities together." if memory.interactions in {5,10,25,50} else ""
        return out(f"🤝 {p.display_name} and {other.display_name} complete a duo {act}. {reward}. Relationship +{relationship_gain}.{milestone}")

@app.get("/api/v1/ducks")
def ducks(channel:str,uid:str,name:str="Citizen",duck:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pref=player_preference(db,p);wanted=(duck or "").strip().title()
        if wanted:
            if wanted not in DELIVERY_DUCKS:return out("🦆 Choose: "+", ".join(DELIVERY_DUCKS)+".")
            pref.assigned_duck=wanted;db.commit();return out(f"🦆 {wanted} is now {p.display_name}'s preferred delivery partner. Assignment changes flavor and bond focus, not base pay or success chance.")
        parts=[]
        for duck in DELIVERY_DUCKS:
            row=duck_bond(db,p,duck,0);assigned=" ⭐ ASSIGNED" if pref.assigned_duck==duck else "";parts.append(f"{duck}: {duck_rank(row.xp)} ({row.xp} XP){assigned} — {DUCK_PERSONALITY[duck]}")
        footer="\n\nAssigning a duck focuses future Logistics bond gains without changing success chance." if provider=="discord" else " | Assign a preferred duck for future Logistics runs"
        return PlainTextResponse("🦆 Delivery Fleet Bonds\n\n"+"\n".join("• "+x for x in parts)+footer) if provider=="discord" else out("🦆 "+" | ".join(parts)+footer)

@app.get("/api/v1/gear")
def gear(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0).order_by(QualityGear.item_name)).scalars().all()
        if not rows:return out("🛠️ No quality gear yet. Use /make to browse and craft equipment.")
        def gear_line(x):
            fam=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==channel,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==x.item_key)).scalar_one_or_none();uses=fam.uses if fam else 0;rank,reduction=gear_familiarity_rank(uses)
            return f"{x.quality} {x.item_name} x{x.qty} — {x.condition}% · {rank} familiarity ({uses} uses, -{int(reduction*100)}pp wear)"
        return PlainTextResponse("🛠️ Quality Gear\n\n"+"\n".join("• "+gear_line(x) for x in rows)) if provider=="discord" else out("🛠️ "+" | ".join(gear_line(x) for x in rows[:10]))

@app.get("/api/v1/gearrepair")
@colony_command
def gearrepair(channel:str,uid:str,name:str="Citizen",item:str="",provider:str="twitch"):
    key=(item or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);life=life_state(db,p);blocked=task_need_gate(db,p,"gearrepair",provider,life)
        if blocked:return PlainTextResponse(blocked) if provider=="discord" else out(blocked)
        rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
        row=next((x for x in rows if f"gear_{x.id}"==key or x.item_key==key or x.item_name.lower()==(item or "").lower()),None)
        if not row:return out("🔧 Gear not found. Use "+("/inventory section:gear" if provider=="discord" else "!gear")+" to see your equipment.")
        if row.condition>=100:return out("🔧 That item is already at full condition. Nothing spent.")
        cost=max(1,(100-row.condition+19)//20)
        if p.components<cost:return out(f"🔧 Repair needs {cost} Components. You have {p.components}.")
        p.components-=cost;row.condition=100;spend_life_for_action(life,"repair");db.commit()
        text=f"🔧 Repaired {row.quality} {row.item_name} to 100% (-{cost} Components, -3 Energy, -1 Nutrition)."+task_readiness_warning(life,provider)
        return PlainTextResponse(text) if provider=="discord" else out(text)

@app.get("/api/v1/use")
@colony_command
def use_item(channel:str,uid:str,name:str="Citizen",item:str="",provider:str="twitch"):
    source_item=seed_content.find_item(item or '')
    if source_item in seed_content.ACTIVE:
        if source_item in seed_content.EDIBLE:return action('eat',channel,uid,name,msg='food:'+source_item,provider=provider)
        import sys
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            result=seed_content.use(sys.modules[__name__],db,p,source_item,provider)
            return platform_response(provider,result,result.replace('\n',' | '))
    key=(item or "").lower().strip().replace(" ","_")
    if key in {'furniture','workwear','medicine'}:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            if material_amount(db,p,key)<1:return out(f"You own no {resource_name(key)}. Open /training for crafting sources. Nothing spent.")
            life=life_state(db,p);material_change(db,p,key,-1)
            boosts={'furniture':{'comfort':35,'morale':5},'workwear':{'comfort':20,'energy':10},'medicine':{'comfort':10}}[key]
            for field,qty in boosts.items():setattr(life,field,clamp100(getattr(life,field)+qty))
            if key=='medicine':player_world(db,p).siro_exposure=max(0,player_world(db,p).siro_exposure-10)
            db.commit();return out(f"Used 1 {resource_name(key)}. "+', '.join(f"+{v} {k.title()} (cap 100)" for k,v in boosts.items())+('; Siro exposure reduced by up to 10.' if key=='medicine' else ''))
    if key not in {"meal_kit","recreation_set","comfort_pack"}:return out("🎒 Usable life gear: meal_kit, recreation_set, comfort_pack.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key==key,QualityGear.qty>0)).scalars().all()
        if not rows:return out("🎒 You do not have that life item. Craft it with /make.")
        row=max(rows,key=lambda x:list(QUALITY_TIERS).index(x.quality));tier=QUALITY_TIERS[row.quality];boost=10+int(tier["special"]*100);life=life_state(db,p)
        before={field:getattr(life,field) for field in ("nutrition","energy","social","comfort","morale")}
        if key=="meal_kit":life.nutrition=clamp100(life.nutrition+65+boost);life.morale=clamp100(life.morale+5)
        elif key=="recreation_set":life.social=clamp100(life.social+18+boost);life.morale=clamp100(life.morale+12)
        else:life.comfort=clamp100(life.comfort+22+boost);life.energy=clamp100(life.energy+8)
        changes=" · ".join(f"{field.title()} {before[field]}→{getattr(life,field)}/100" for field in before if before[field]!=getattr(life,field))
        row.qty-=1;db.commit();return out(f"🎒 Used {row.quality} {row.item_name}. {changes or 'Needs already full'}; item consumed.")

@app.get("/api/v1/world")
@colony_command
def world_status(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        s=society(db,channel);clock=world_clock(db,channel,s);proj=current_project(db,channel,clock["day"]);pcfg=project_cfg(proj.project_key)
        storyrow,storycfg=story_state(db,channel,clock)
        rumor=RUMORS[_stable_index(f"{channel}:{clock['day']}:rumor",len(RUMORS))]
        low=shortages(s);shared=colony_state(db,channel)
        short=", ".join(x[0] for x in low) if low else "No core-resource shortages"
        if shared.housing<s.population:short+="; "+housing_status_text(shared,s,provider)
        discord=(f"{clock['phase_emoji']} Avesta Day {clock['day']} — {clock['phase']}\n\n"
                 f"World condition: {clock['condition']}\n{clock['condition_text']}\n\n"
                 f"Society project: {pcfg[1]} {proj.progress}/{proj.goal}\n"
                 f"Society pressure: {short}\n\n"
                 f"Weekly story: {storycfg['name']} {storyrow.track_a+storyrow.track_b+storyrow.track_c}/{storycfg['goal']}\n\n"
                 f"Rumor: {rumor}\n\nDay phases change action bonuses. Night outdoor work can increase Siro exposure.")
        if uid:
            _,pp=player(db,channel,provider,uid,name);discord+=tutorial_advance(db,pp,"world");twitch_note=tutorial_advance(db,pp,"world")
        else:twitch_note=""
        twitch=f"{clock['phase_emoji']} Day {clock['day']} {clock['phase']} | {clock['condition']} | Story {storycfg['name']} {storyrow.track_a+storyrow.track_b+storyrow.track_c}/{storycfg['goal']} | Project {pcfg[1]} {proj.progress}/{proj.goal} | {short} | Rumor: {rumor}"+twitch_note
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/rumor")
def rumor(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);base=RUMORS[_stable_index(f"{channel}:{clock['day']}:{clock['phase']}",len(RUMORS))]
        who,job=NPCS[_stable_index(f"{channel}:{clock['day']}:npc",len(NPCS))]
        return out(f"🗣️ {who}, {job}: {base}")

@app.get("/api/v1/collection")
def collection(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(CollectionItem).where(CollectionItem.channel_id==channel,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.qty>0).order_by(CollectionItem.item_name)).scalars().all()
        if not rows:return out("🧳 Collection empty. Explore, work, and watch for unusual encounters.")
        claimed={x.set_key for x in db.execute(select(CollectionSetClaim).where(CollectionSetClaim.channel_id==channel,CollectionSetClaim.canonical_uid==p.twitch_uid)).scalars().all()}
        set_lines=[f"{name}: {'COMPLETE' if key in claimed else str(sum(1 for i in items if i in {r.item_key for r in rows}))+'/'+str(len(items))}" for key,(name,items,_,__,___) in COLLECTION_SETS.items()]
        if provider=="discord":return PlainTextResponse("🧳 Collection\n\n"+"\n".join(f"• {r.item_name} x{r.qty}" for r in rows[:25])+"\n\nSETS\n"+"\n".join("• "+x for x in set_lines))
        return out("🧳 "+p.display_name+" | "+" | ".join(f"{r.item_name} x{r.qty}" for r in rows[:10]))

@app.get("/api/v1/traits")
def traits(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);items,_=trait_data(db,p)
        return out("🧬 "+p.display_name+" | "+(", ".join(items) if items else "No earned traits yet. Reach 50 XP in an aptitude to begin earning them."))

@app.get("/api/v1/district")
def district(channel:str,uid:str,name:str="Citizen",district:str="",provider:str="twitch"):
    key=(district or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pw=player_world(db,p)
        if not key:return out("🏘️ Districts: "+", ".join(DISTRICTS))
        if key not in DISTRICTS:return out("🏘️ Unknown district. Options: "+", ".join(DISTRICTS))
        pw.district=key;db.commit();journal_add(db,p,f"Moved residence to {DISTRICTS[key]}.")
        return out(f"🏘️ {p.display_name} now lives in the {DISTRICTS[key]}. Matching work receives a small local familiarity bonus.")

@app.get("/api/v1/shift")
@colony_command
def shift(channel:str,uid:str,name:str="Citizen",role:str="",provider:str="twitch"):
    key=(role or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);pw=player_world(db,p)
        if not key:return out("🕒 Shift roles: "+", ".join(SHIFT_ROLES))
        if key not in SHIFT_ROLES:return out("🕒 Unknown role. Options: "+", ".join(SHIFT_ROLES))
        pw.shift_role=key;pw.shift_day=clock["day"];db.commit()
        bonus_note="No shift bonus while off duty." if key=="off_duty" else "Matching work gets +2 percentage points to the success chance today."
        return out(f"🕒 {p.display_name} takes {SHIFT_ROLES[key]} for Avesta Day {clock['day']}. {bonus_note}")

@app.get("/api/v1/conditions")
def conditions(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pw=player_world(db,p);rows=active_statuses(db,p)
        bits=[f"Siro exposure {pw.siro_exposure}/100"]+[f"{r.effect.replace('_',' ').title()} ({r.modifier:+d}%)" for r in rows]
        return out("🩺 "+p.display_name+" | "+" | ".join(bits))

@app.get("/api/v1/goal")
def personal_goal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    # /goal now shows the same Daily Contract as /contracts instead of
    # maintaining a second overlapping daily objective.
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);d=daily(db,p)
        state="COMPLETE" if d.complete else f"{d.progress}/{d.target}"
        cmd=("/" if provider=="discord" else "!")+d.action
        discord=f"🎯 {p.display_name} — Daily Goal\n\nTask: {cmd}\nProgress: {state}\nReward: {d.reward_sc} SC + 1 Contribution"+("\n\n✅ Complete for today." if d.complete else f"\n\nNext: use {cmd}.")
        twitch=f"🎯 Daily Goal | {cmd} {state} | Reward {d.reward_sc} SC +1 Contribution"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/projectstatus")
@colony_command
def projectstatus(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);row=current_project(db,channel,clock["day"]);cfg=project_cfg(row.project_key)
        skills=", ".join(SKILL_LABELS[x] for x in sorted(cfg[3]))
        return out(f"🏗️ {cfg[1]} | {row.progress}/{row.goal} | Useful aptitudes: {skills} | Completed projects: {row.completed}")

@app.get("/api/v1/bulletin")
def bulletin(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);proj=current_project(db,channel,clock["day"]);cfg=project_cfg(proj.project_key)
        directive,dcfg=directive_for(db,channel,clock["day"])
        aftermath=db.execute(select(SocietyAftermath).where(SocietyAftermath.channel_id==channel,SocietyAftermath.expires_at>now()).order_by(SocietyAftermath.expires_at.desc())).scalars().first()
        tasks=[
            f"Daily Directive: {dcfg[1]} {directive.progress}/{directive.goal} — use {', '.join(SKILL_LABELS[x] for x in sorted(dcfg[2]))}",
            f"Society Project: contribute with {', '.join(SKILL_LABELS[x] for x in cfg[3])}",
            f"World Condition: {clock['condition']} — {clock['condition_text']}",
            f"Community: bring a Crop to the shared meal with {'/meal' if provider=='discord' else '!meal'}",
        ]
        if aftermath:tasks.append(f"Event Aftermath: {aftermath.event_name} {aftermath.modifier:+d}% related work until it expires")
        if provider=="discord":return PlainTextResponse("📌 New Eridian Bulletin\n\n"+"\n".join("• "+x for x in tasks))
        return out("📌 "+" | ".join(tasks))

@app.get("/api/v1/meal")
@colony_command
def meal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel)
        if p.crops<=0:return out("🍲 You need 1 Crop to contribute to the community meal.")
        row=db.execute(select(CommunityMeal).where(CommunityMeal.channel_id==channel,CommunityMeal.day==clock["day"])).scalar_one_or_none()
        if not row:row=CommunityMeal(channel_id=channel,day=clock["day"],contributions=0,completed=False);db.add(row)
        p.crops-=1;row.contributions+=1;life=life_state(db,p);life.social=clamp100(life.social+10);life.morale=clamp100(life.morale+3);life.nutrition=clamp100(life.nutrition+25)
        msg=f"🍲 {p.display_name} shares 1 Crop. Meal progress {row.contributions}/12. +25 Nutrition/+10 Social/+3 Morale (capped at 100)."
        if row.contributions>=12 and not row.completed:
            row.completed=True;add_status(db,p,"community_fed",45,4,"A completed community meal is helping you feel prepared.");msg+=" 🎉 Community meal complete! You gain Community Fed +4% for 45 min."
        db.commit();journal_add(db,p,f"Contributed to the community meal on Day {clock['day']}.");return out(msg)

@app.get("/api/v1/mentor")
@colony_command
def mentor(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);pw=player_world(db,p)
        if pw.mentor_day==clock["day"]:return out("🧑‍🏫 You have already mentored someone today.")
        target_p,error=find_player_name(db,channel,target)
        if error:return out("🧑‍🏫 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🧑‍🏫 Mentoring yourself is called reading your own notes.")
        fields=[(key,skill_xp(target_p,key)) for key in SKILL_LABELS]
        skill=min(fields,key=lambda x:x[1])[0];mentored_gain=gain_skill(target_p,skill,2);p.contribution+=2;pw.mentor_day=clock["day"];db.commit()
        journal_add(db,p,f"Mentored {target_p.display_name} in {SKILL_LABELS[skill]}.")
        return out(f"🧑‍🏫 {p.display_name} mentors {target_p.display_name}. {target_p.display_name} gains +{mentored_gain} {SKILL_LABELS[skill]} competency XP; mentor gains +2 Contribution.")

@app.get("/api/v1/journal")
def journal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(JournalEntry).where(JournalEntry.channel_id==channel,JournalEntry.canonical_uid==p.twitch_uid).order_by(JournalEntry.created_at.desc()).limit(8)).scalars().all()
        if not rows:return out("📓 Journal is empty. Important discoveries and milestones will appear here.")
        if provider=="discord":return PlainTextResponse("📓 Journal\n\n"+"\n".join("• "+r.entry for r in rows))
        return out("📓 "+" | ".join(r.entry for r in rows[:5]))

@app.get("/api/v1/link/create")
def link_create(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        c=resolve(db,channel,provider,uid);record_account_name(db,channel,provider,uid,name);code="".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
        db.add(LinkCode(channel_id=channel,canonical_uid=c,code=code,expires_at=now()+timedelta(minutes=15)));db.commit()
        return out(f"🔗 Link code {code}. In Discord use /link {code} within 15 minutes.")

@app.get("/api/v1/link/claim")
def link_claim(channel:str,discord_uid:str,name:str="Citizen",code:str=""):
    with SessionLocal() as db:
        record_account_name(db,channel,"discord",discord_uid,name)
        r=db.execute(select(LinkCode).where(LinkCode.channel_id==channel,LinkCode.code==code.upper())).scalar_one_or_none()
        if not r or as_utc(r.expires_at)<now():return out("⛔ Invalid or expired code.")
        discord_link=db.execute(select(AccountLink).where(AccountLink.channel_id==channel,AccountLink.discord_uid==discord_uid)).scalar_one_or_none()
        twitch_link=db.execute(select(AccountLink).where(AccountLink.channel_id==channel,AccountLink.twitch_uid==r.canonical_uid)).scalar_one_or_none()
        if discord_link and discord_link.twitch_uid!=r.canonical_uid:return out("⛔ This Discord account is already permanently linked to another Twitch character.")
        if twitch_link and twitch_link.discord_uid!=discord_uid:return out("⛔ This Twitch character is already permanently linked to another Discord account.")
        x=db.execute(select(Identity).where(Identity.channel_id==channel,Identity.provider=="discord",Identity.provider_uid==discord_uid)).scalar_one_or_none()
        orphan_uid="discord:"+discord_uid
        orphan=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==orphan_uid)).scalar_one_or_none()
        # Prefer a legacy Discord-only row so accounts linked before v5.1.1 can relink once and recover it.
        source_uid=orphan_uid if orphan else (x.canonical_uid if x else orphan_uid)
        merged=merge_accounts(db,channel,source_uid,r.canonical_uid)
        if x:x.canonical_uid=r.canonical_uid
        else:db.add(Identity(channel_id=channel,provider="discord",provider_uid=discord_uid,canonical_uid=r.canonical_uid))
        if not discord_link and not twitch_link:db.add(AccountLink(channel_id=channel,twitch_uid=r.canonical_uid,discord_uid=discord_uid))
        db.delete(r);db.commit()
        return out("✅ Discord and Twitch linked. Both characters' stats and progress were merged." if merged else "✅ Discord linked to your Twitch New Eridian character.")

@app.get("/api/v1/society")
@colony_command
def soc(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);tier=society_tier(s)
        personal=f"{clean(viewer)}, your society currently needs the most help with {min({'Food':s.food,'Materials':s.materials,'Development':s.development,'Knowledge':s.knowledge,'Treasury':s.treasury,'Reputation':s.reputation},key=lambda k:{'Food':s.food,'Materials':s.materials,'Development':s.development,'Knowledge':s.knowledge,'Treasury':s.treasury,'Reputation':s.reputation}[k])}.\n\n" if viewer else ""
        discord=(f"🏙️ {s.name} — Society Status\n\n{personal}🏛️ Tier: {tier[0]}\n👥 Population: {s.population}\n\n"
                 f"📦 CORE RESOURCES\n🌾 Food: {s.food} · ⛏️ Materials: {s.materials}\n🏗️ Development: {s.development} · 🔬 Knowledge: {s.knowledge}\n"
                 f"🪙 Treasury: {s.treasury} · ⭐ Reputation: {s.reputation}\n\n💰 Tier pay bonus: +{tier[2]} SC\nUse /society section:Next Tier Progress to see the next tier.")
        discord+="\n\nSHARED HOUSING\n"+housing_status_text(colony_state(db,channel),s,provider,True)
        twitch=f"🏙️ {s.name} — {tier[0]} | 🌾{s.food} Food · ⛏️{s.materials} Materials · 🏗️{s.development} Development · 🔬{s.knowledge} Knowledge · 🪙{s.treasury} Treasury · ⭐{s.reputation} Reputation · 👥{s.population} | Tier bonus +{tier[2]} SC"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/event")
def event(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);expired=resolve_expired_event(db,s,w)
        if expired:return out(expired)
        if not w.active_event:return out("🚨 No active live event.")
        cfg=EVENTS[w.active_event];seconds=max(0,int((as_utc(w.event_ends)-now()).total_seconds()));pct=int((w.event_progress/w.event_goal)*100) if w.event_goal else 0;leaders=event_contributors(db,w)
        penalty=stat_changes_text(cfg["penalty"],"−")
        if provider=="discord":
            return PlainTextResponse(f"🚨 {cfg['emoji']} {cfg['name']}\n\n"+(f"{clean(viewer)}, New Eridian needs your response.\n\n" if viewer else "")+f"📊 STATUS\nProgress: {w.event_progress}/{w.event_goal} ({pct}%)\nTime remaining: {seconds//60}:{seconds%60:02d}\n\n🎯 HOW TO HELP\nPrimary: {SKILL_LABELS[cfg['primary']]} — each success adds +1\nSupport: {SKILL_LABELS[cfg['support']]} — {w.event_support_successes}/2 toward +1\n\n⚠️ Full failure penalty: {penalty}\n🏅 Leaders: {leader_text(leaders)}\n\nUse /guide goal:event for your personal best available command.")
        primary=SKILL_LABELS.get(cfg["primary"],cfg["primary"].title());support=SKILL_LABELS.get(cfg["support"],cfg["support"].title())
        return out(f"🚨 {cfg['emoji']} {cfg['name']} {pct}% | {w.event_progress}/{w.event_goal} | {seconds//60}:{seconds%60:02d} | Primary {primary} | Support {support} {w.event_support_successes}/2 | Penalty {penalty} | Leaders {leader_text(leaders)}")

@app.get("/api/v1/eventhistory")
def eventhistory(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        rows=db.execute(select(EventHistory).where(EventHistory.channel_id==channel).order_by(EventHistory.ended_at.desc()).limit(5)).scalars().all()
        if not rows:return out("📜 No completed event history yet.")
        lines=[f"{r.result.upper()} · {r.event_name} {r.progress}/{r.goal} · {r.participants} participants · started {r.started_by} · ended {r.ended_by}" for r in rows]
        return PlainTextResponse("📜 New Eridian Event History\n"+"\n".join(lines)) if provider=="discord" else out("📜 "+" | ".join(lines[:3]))

@app.get("/api/v1/leaderboard")
def leaderboard(channel:str,provider:str="twitch",uid:str="",name:str="Citizen"):
    with SessionLocal() as db:
        viewer=None
        if uid:_,viewer=player(db,channel,provider,uid,name)
        all_players=db.execute(select(Player).where(Player.channel_id==channel).order_by(Player.contribution.desc(),Player.id)).scalars().all()
        if not all_players:return out("🏆 No citizens ranked yet.")
        lines=[f"{i}. {p.display_name} — {p.contribution} contribution" for i,p in enumerate(all_players[:10],1)]
        personal=""
        if viewer:
            rank=next((i for i,p in enumerate(all_players,1) if p.twitch_uid==viewer.twitch_uid),len(all_players));personal=f"\n\n{viewer.display_name}, you are ranked #{rank} with {viewer.contribution} Contribution."
        return PlainTextResponse("🏆 New Eridian Contributors\n\n"+"\n".join(lines)+personal) if provider=="discord" else out("🏆 "+" | ".join(lines[:5]))

@app.get("/api/v1/overlay")
def overlay_state(channel:str):
    """Rich JSON contract for the New Eridian v2 OBS Browser Source."""
    with SessionLocal() as db:
        source_ids=list(dict.fromkeys([DISCORD_WORLD_ID,channel]))

        # New Eridian's shared world is authoritative for Avesta state.
        s=society(db,DISCORD_WORLD_ID)
        clock=world_clock(db,DISCORD_WORLD_ID,s)
        w=world(db,DISCORD_WORLD_ID)
        resolve_expired_event(db,s,w)

        # Combine society telemetry when Twitch and Discord have separate legacy rows.
        sources=[s]
        if channel!=DISCORD_WORLD_ID:
            other=db.execute(select(Society).where(Society.channel_id==channel)).scalar_one_or_none()
            if other:
                resolve_expired_event(db,other,world(db,channel))
                sources.append(other)

        stats={field:sum(getattr(source,field) for source in sources)
               for field in ("food","materials","development","knowledge","treasury","reputation","population")}
        total=Society(**stats)
        tier=society_tier(total)
        core_stats={k:stats[k] for k in ("food","materials","development","knowledge","treasury","reputation")}
        core=min(core_stats.values())
        next_tier=next((x for x in SOCIETY_TIERS if x[1]>core),None)
        target=next_tier[1] if next_tier else max(1,SOCIETY_TIERS[-1][1])
        bottleneck_key=min(core_stats,key=core_stats.get)
        bottleneck_labels={
            "food":"Food","materials":"Materials","development":"Development",
            "knowledge":"Knowledge","treasury":"Treasury","reputation":"Reputation"
        }

        # Society project.
        project=current_project(db,DISCORD_WORLD_ID,clock["day"])
        pcfg=project_cfg(project.project_key)
        project_data={
            "key":project.project_key,
            "name":pcfg[1],
            "progress":project.progress,
            "goal":project.goal,
            "percent":min(100,round((project.progress/max(1,project.goal))*100,1)),
            "skills":[SKILL_LABELS.get(x,x.title()) for x in sorted(pcfg[3])],
            "completed":project.completed,
        }

        # Weekly community story.
        storyrow,storycfg=story_state(db,DISCORD_WORLD_ID,clock)
        story_values=[storyrow.track_a,storyrow.track_b,storyrow.track_c]
        story_total=sum(story_values)
        story_tracks=[
            {"name":storycfg["tracks"][i][0],"value":story_values[i]}
            for i in range(3)
        ]
        story_data={
            "key":storycfg["key"],
            "name":storycfg["name"],
            "text":storycfg["text"],
            "progress":story_total,
            "goal":storycfg["goal"],
            "percent":min(100,round((story_total/max(1,storycfg["goal"]))*100,1)),
            "resolved":bool(storyrow.resolved),
            "outcome":storyrow.outcome or "",
            "tracks":story_tracks,
        }

        # Current market demand.
        primary_market,secondary_market=market_demand(DISCORD_WORLD_ID,clock["day"])
        market_prices={
            k:max(1,int(v*market_multiplier(DISCORD_WORLD_ID,clock["day"],k)))
            for k,v in MARKET_BASE.items()
        }
        market_data={
            "primary":{"key":primary_market,"name":resource_name(primary_market),"price":market_prices[primary_market]},
            "secondary":{"key":secondary_market,"name":resource_name(secondary_market),"price":market_prices[secondary_market]},
            "prices":market_prices,
        }

        # Shortage pressure and current rumor.
        pressure=[x[0] for x in shortages(total)]
        rumor=RUMORS[_stable_index(f"{DISCORD_WORLD_ID}:{clock['day']}:rumor",len(RUMORS))]

        # Recent activity feed.
        recent=db.execute(
            select(ActionLog)
            .where(ActionLog.channel_id.in_(source_ids))
            .order_by(ActionLog.created_at.desc(),ActionLog.id.desc())
            .limit(5)
        ).scalars().all()
        recent_uids=list({x.canonical_uid for x in recent})
        name_map={}
        if recent_uids:
            players=db.execute(
                select(Player).where(
                    Player.channel_id.in_(source_ids),
                    Player.twitch_uid.in_(recent_uids)
                )
            ).scalars().all()
            for p in players:
                name_map.setdefault(p.twitch_uid,p.display_name)
        activity=[]
        for row in recent:
            message=(row.response or "").replace("\r"," ").replace("\n"," · ").strip()
            message=re.sub(r"\s+"," ",message)
            activity.append({
                "name":name_map.get(row.canonical_uid,"Citizen"),
                "action":row.action.replace("_"," ").title(),
                "message":message[:260],
                "at":as_utc(row.created_at).isoformat(),
            })

        cutoff=now()-timedelta(minutes=30)
        active_uids=set(db.execute(
            select(ActionLog.canonical_uid).where(
                ActionLog.channel_id.in_(source_ids),
                ActionLog.created_at>=cutoff
            )
        ).scalars().all())

        event_data=None
        if w.active_event:
            cfg=EVENTS[w.active_event]
            leaders=event_contributors(db,w)
            event_data={
                "key":w.active_event,
                "name":cfg["name"],
                "emoji":cfg["emoji"],
                "action":cfg["action"],
                "progress":w.event_progress,
                "goal":w.event_goal,
                "percent":min(100,round((w.event_progress/max(1,w.event_goal))*100,1)),
                "seconds_remaining":max(0,int((as_utc(w.event_ends)-now()).total_seconds())),
                "primary":SKILL_LABELS.get(cfg["primary"],cfg["primary"].title()),
                "support":SKILL_LABELS.get(cfg["support"],cfg["support"].title()),
                "support_progress":w.event_support_successes,
                "active_players":w.event_active_players,
                "leaders":[
                    {"name":r.display_name,"primary":r.primary_successes,"support":r.support_successes}
                    for r in leaders[:3]
                ],
            }

        # v6.0+ engagement telemetry. These are deliberately summarized at
        # society level so the stream overlay stays useful without exposing a
        # citizen's private inventory or requiring a viewer identity.
        directive,dcfg=directive_for(db,DISCORD_WORLD_ID,clock["day"])
        directive_participants=db.execute(
            select(DirectiveParticipant).where(
                DirectiveParticipant.channel_id.in_(source_ids),
                DirectiveParticipant.avesta_day==clock["day"]
            )
        ).scalars().all()
        directive_data={
            "key":directive.directive_key,
            "name":dcfg[1],
            "description":dcfg[5],
            "progress":directive.progress,
            "goal":directive.goal,
            "percent":min(100,round((directive.progress/max(1,directive.goal))*100,1)),
            "complete":bool(directive.complete),
            "skills":[SKILL_LABELS.get(x,x.title()) for x in sorted(dcfg[2])],
            "reward":f"+{dcfg[4]} {dcfg[3].title()}",
            "participants":len({x.canonical_uid for x in directive_participants}),
        }

        aftermath_rows=db.execute(
            select(SocietyAftermath).where(
                SocietyAftermath.channel_id.in_(source_ids),
                SocietyAftermath.expires_at>now()
            ).order_by(SocietyAftermath.expires_at.desc())
        ).scalars().all()
        aftermath_data=None
        if aftermath_rows:
            aftermath=aftermath_rows[0]
            aftermath_data={
                "event":aftermath.event_name,
                "result":aftermath.result,
                "modifier":aftermath.modifier,
                "description":aftermath.description,
                "skills":[SKILL_LABELS.get(x,x.title()) for x in aftermath.skills.split(",") if x],
                "seconds_remaining":max(0,int((as_utc(aftermath.expires_at)-now()).total_seconds())),
            }

        variety_rows=db.execute(
            select(DailyVariety).where(
                DailyVariety.channel_id.in_(source_ids),
                DailyVariety.avesta_day==clock["day"]
            )
        ).scalars().all()
        prefs=db.execute(
            select(PlayerPreference).where(PlayerPreference.channel_id.in_(source_ids))
        ).scalars().all()
        familiarity=db.execute(
            select(GearFamiliarity).where(GearFamiliarity.channel_id.in_(source_ids))
        ).scalars().all()
        memories=db.execute(
            select(RelationshipMemory).where(RelationshipMemory.channel_id.in_(source_ids))
        ).scalars().all()
        lore=db.execute(
            select(LoreDiscovery).where(LoreDiscovery.channel_id.in_(source_ids))
        ).scalars().all()
        engagement_data={
            "variety_active":len({x.canonical_uid for x in variety_rows}),
            "variety_complete":len({x.canonical_uid for x in variety_rows if x.claimed}),
            "fleet_assigned":len({x.canonical_uid for x in prefs if x.assigned_duck}),
            "familiar_gear":sum(1 for x in familiarity if x.uses>=10),
            "trusted_gear":sum(1 for x in familiarity if x.uses>=50),
            "relationship_memories":len(memories),
            "lore_found":len({x.lore_key for x in lore}),
            "lore_total":len(LORE_FRAGMENTS),
        }

        return {
            "ok":True,
            "game":s.name,
            "tier":tier[0],
            "tier_bonus":tier[2],
            "next_tier":next_tier[0] if next_tier else None,
            "tier_target":target,
            "tier_percent":100 if not next_tier else min(100,round((core/max(1,target))*100,1)),
            "bottleneck":{
                "key":bottleneck_key,
                "name":bottleneck_labels[bottleneck_key],
                "value":core_stats[bottleneck_key],
                "target":target,
                "percent":min(100,round((core_stats[bottleneck_key]/max(1,target))*100,1)),
            },
            "day":clock["day"],
            "phase":clock["phase"],
            "phase_emoji":clock["phase_emoji"],
            "condition":clock["condition"],
            "condition_text":clock["condition_text"],
            "stats":stats,
            "project":project_data,
            "story":story_data,
            "market":market_data,
            "pressure":pressure,
            "rumor":rumor,
            "event":event_data,
            "directive":directive_data,
            "aftermath":aftermath_data,
            "engagement":engagement_data,
            "colony":{source.channel_id:{"water":colony_state(db,source.channel_id).water,"ore":colony_state(db,source.channel_id).ore,"components":colony_state(db,source.channel_id).components,"housing":colony_state(db,source.channel_id).housing,"mood":colony_state(db,source.channel_id).mood,"pressures":colony_pressures(colony_state(db,source.channel_id),source)} for source in sources},
            "activity":activity,
            "active_players":len(active_uids),
            "last_action":activity[0] if activity else None,
            "updated_at":now().isoformat(),
            "world_sources":source_ids,
            "primary_world":DISCORD_WORLD_ID,
            "overlay_version":"6.3.1",
        }


@app.get("/overlay",response_class=HTMLResponse)
def overlay_page(panel:str="",channel:str="new-eridian"):
    # Preserve every previously shared /overlay?channel=...&panel=... URL, but
    # serve the smaller OBS-only document instead of loading the full dashboard.
    # This prevents OBS transforms and Windows display scaling from activating
    # the dashboard's mobile stack inside an individual Browser Source.
    selected=(panel or "").lower().strip()
    if selected in {"society","today","event","ops","activity","telemetry","signal"}:
        return standalone_obs_panel(selected,channel)
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Eridian v2 · Stream Telemetry</title>
<style>
:root{
  color-scheme:dark;
  --bg:rgba(7,10,31,.88);
  --bg2:rgba(15,12,43,.93);
  --line:rgba(147,154,255,.34);
  --line2:rgba(89,218,255,.30);
  --text:#fffaf0;
  --muted:#aca9c9;
  --ivory:#fff8e8;
  --green:#7ee3b0;
  --green2:#b8f4d0;
  --violet:#bd91ff;
  --cyan:#70ddff;
  --amber:#ffd27a;
  --danger:#ff7484;
  --shadow:0 18px 52px rgba(0,0,0,.48),0 0 28px rgba(75,54,183,.12);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text)}
body{padding:26px}
.hidden{display:none!important}

.hud{position:relative;width:100%;height:100%;isolation:isolate}
.hud:before{
  content:"";position:absolute;inset:-26px;z-index:-2;pointer-events:none;opacity:.50;
  background:
    radial-gradient(circle at 5% 8%,rgba(65,143,255,.25) 0 3%,rgba(44,73,189,.14) 8%,transparent 18%),
    radial-gradient(ellipse at 79% 13%,rgba(210,126,255,.18),rgba(100,70,225,.12) 12%,transparent 28%),
    radial-gradient(circle at 18% 42%,rgba(65,166,255,.10) 0 1px,transparent 2px),
    radial-gradient(circle at 67% 33%,rgba(255,247,225,.18) 0 1px,transparent 2px),
    linear-gradient(180deg,rgba(5,7,31,.17),rgba(14,8,47,.05) 55%,rgba(7,10,31,.22));
  background-size:auto,auto,113px 89px,149px 127px,auto;
}
.hud:after{
  content:"";position:absolute;left:-26px;right:-26px;bottom:-26px;height:13%;z-index:-1;pointer-events:none;
  background:linear-gradient(155deg,transparent 0 10%,rgba(12,13,35,.44) 11% 22%,transparent 23%),linear-gradient(25deg,rgba(7,9,25,.55),rgba(30,22,65,.26));
  clip-path:polygon(0 52%,8% 39%,15% 58%,24% 34%,34% 69%,46% 43%,56% 65%,68% 39%,78% 57%,88% 28%,100% 48%,100% 100%,0 100%);
}
.card{
  position:absolute;
  overflow:hidden;
  background:
    radial-gradient(circle at 90% 0,rgba(125,72,220,.13),transparent 42%),
    linear-gradient(145deg,rgba(8,13,39,.94),rgba(24,15,54,.91));
  border:1px solid var(--line);
  border-radius:16px;
  box-shadow:var(--shadow);
  backdrop-filter:blur(12px);
}
.card:before{
  content:"";
  position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(120deg,rgba(255,248,226,.055),transparent 35%);
}
.eyebrow{
  font-size:10px;font-weight:800;letter-spacing:.20em;text-transform:uppercase;
  color:var(--green2);
}
.muted{color:var(--muted)}
.mini{font-size:11px}
.dot{
  display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--green);box-shadow:0 0 12px rgba(152,215,155,.7);
  margin-right:7px;vertical-align:1px
}

/* Society command card */
.society{left:0;top:0;width:410px;padding:18px 20px 17px}
.society-title{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-top:5px}
.society h1{
  font-family:Georgia,"Times New Roman",serif;font-size:31px;line-height:1;margin:0;letter-spacing:.025em;
  color:var(--ivory);text-shadow:0 0 8px rgba(255,248,232,.55),0 0 24px rgba(181,124,255,.32)
}
.tier-chip{
  border:1px solid var(--line2);background:rgba(142,211,150,.08);
  color:var(--green2);font-size:11px;font-weight:800;padding:5px 8px;border-radius:999px
}
.world-line{display:flex;gap:9px;align-items:center;margin-top:10px;color:#d7d5df;font-size:12px;flex-wrap:wrap}
.sep{opacity:.35}
.condition{margin-top:11px;padding-top:10px;border-top:1px solid rgba(255,255,255,.07)}
.condition strong{font-size:13px}
.condition p{margin:3px 0 0;color:var(--muted);font-size:11px;line-height:1.35}
.priority{margin-top:12px}
.row-head{display:flex;justify-content:space-between;gap:12px;align-items:center;font-size:11px}
.row-head strong{font-size:12px}
.progress{
  height:7px;margin-top:7px;background:rgba(255,255,255,.07);
  border-radius:999px;overflow:hidden
}
.progress i{
  display:block;height:100%;width:0;
  background:linear-gradient(90deg,var(--green),var(--violet));
  border-radius:999px;transition:width .55s ease
}

/* Today's goals / v6 engagement systems */
.today{left:0;bottom:122px;width:410px;padding:16px 18px}
.today-grid{display:grid;grid-template-columns:1fr;gap:9px;margin-top:9px}
.today .module{background:rgba(8,11,36,.40);border-color:rgba(130,155,255,.13)}
.directive-title{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.directive-title strong{font-size:12px;color:var(--ivory)}
.directive-title span{font-size:10px;color:var(--cyan);font-weight:800}
.system-pulse{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}
.pulse-stat{padding:7px 8px;border:1px solid rgba(112,221,255,.10);border-radius:8px;background:rgba(4,8,29,.28)}
.pulse-stat b{display:block;font-size:13px;color:var(--ivory)}
.pulse-stat small{display:block;margin-top:2px;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.08em}
.system-detail{margin-top:7px;color:var(--muted);font-size:9px;line-height:1.3}
.aftermath{margin-top:9px;padding-top:9px;border-top:1px solid rgba(255,255,255,.07);font-size:10px;line-height:1.35;color:var(--muted)}
.aftermath.good b{color:var(--green2)}
.aftermath.bad b{color:#ff9aa6}
.brand-motto{margin-top:10px;color:#8f86bb;font:600 11px/1.2 Georgia,"Times New Roman",serif;letter-spacing:.05em}

/* Center live event */
.event{
  top:0;left:50%;transform:translateX(-50%);
  width:620px;padding:17px 20px 16px;border-color:rgba(255,116,132,.36)
}
.event .eyebrow{color:#ff9aa6}
.event-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:4px}
.event-title h2{font-size:21px;margin:0}
.timer{font-size:19px;font-weight:850;color:#fff}
.event-meta{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:#cac8d3}
.event-meta b{color:#fff}
.event .progress i{background:linear-gradient(90deg,var(--danger),var(--amber))}
.leaders{margin-top:9px;font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Operations card */
.ops{right:0;top:0;width:505px;padding:17px 19px}
.ops-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}
.module{padding:11px 12px;border:1px solid rgba(255,255,255,.07);background:rgba(7,9,13,.22);border-radius:11px}
.module h3{font-size:12px;margin:0 0 4px}
.module .value{font-size:11px;color:var(--muted);line-height:1.35}
.module .pct{font-size:11px;font-weight:800;color:#fff}
.module .progress{height:5px;margin-top:8px}
.story-tracks{
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:9px
}
.story-path{min-width:0}
.story-path-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:4px;
  font-size:9px;
  line-height:1.2
}
.story-path-name{
  color:#d9d8e2;
  font-weight:750;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap
}
.story-path-meta{
  color:var(--muted);
  white-space:nowrap
}
.story-path.leader .story-path-name{color:var(--green2)}
.story-path.leader .story-path-meta{color:var(--green2)}
.story-leader-tag{
  display:inline-block;
  margin-left:5px;
  padding:2px 5px;
  border:1px solid rgba(152,215,155,.30);
  border-radius:999px;
  background:rgba(152,215,155,.08);
  color:var(--green2);
  font-size:7px;
  font-weight:850;
  letter-spacing:.08em;
  vertical-align:1px
}
.story-path-bar{
  height:5px;
  overflow:hidden;
  border-radius:999px;
  background:rgba(255,255,255,.07)
}
.story-path-bar i{
  display:block;
  height:100%;
  width:0;
  border-radius:999px;
  background:var(--cyan);
  transition:width .45s ease
}
.story-path.leader .story-path-bar i{
  background:linear-gradient(90deg,var(--green),var(--green2))
}
.story-summary{
  margin-top:7px;
  font-size:8px;
  color:var(--muted);
  line-height:1.3
}
.market-hot{color:var(--amber)!important}
.rumor{
  margin-top:10px;border-top:1px solid rgba(255,255,255,.07);padding-top:9px;
  font-size:10px;line-height:1.35;color:var(--muted)
}

/* Activity feed */
.activity{
  right:0;bottom:122px;width:505px;padding:15px 17px 14px;
  transition:opacity .25s,transform .25s
}
.activity-head{display:flex;justify-content:space-between;align-items:center}
.activity-list{margin-top:8px;display:flex;flex-direction:column;gap:7px}
.activity-item{
  display:grid;
  grid-template-columns:7px minmax(0,1fr);
  gap:9px;
  align-items:start;
  padding:7px 8px;
  background:rgba(8,10,14,.24);
  border-radius:9px;
  min-width:0;
  overflow:hidden
}
.activity-item:first-child{background:rgba(152,215,155,.07)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--violet);margin-top:5px}
.activity-item:first-child .pulse{background:var(--green);box-shadow:0 0 9px rgba(152,215,155,.6)}
.activity-copy{
  min-width:0;
  max-width:100%;
  overflow:hidden
}
.activity-top{
  display:flex;
  align-items:baseline;
  flex-wrap:wrap;
  gap:3px 8px;
  min-width:0;
  max-width:100%
}
.activity-who{
  min-width:0;
  max-width:100%;
  font-size:10px;
  font-weight:800;
  color:#fff;
  overflow-wrap:anywhere;
  word-break:break-word
}
.activity-action{
  min-width:0;
  max-width:100%;
  font-size:9px;
  color:var(--cyan);
  text-transform:uppercase;
  letter-spacing:.08em;
  margin-left:0;
  overflow-wrap:anywhere;
  word-break:break-word
}
.activity-age{
  margin-left:auto;font-size:9px;color:var(--muted);white-space:nowrap
}
.activity-msg{
  min-width:0;
  max-width:100%;
  font-size:10px;
  color:var(--muted);
  line-height:1.35;
  margin-top:3px;
  white-space:normal;
  overflow-wrap:anywhere;
  word-break:break-word;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  overflow:hidden
}

/* Bottom telemetry rail */
.telemetry{
  left:0;right:0;bottom:0;height:102px;
  display:grid;grid-template-columns:repeat(6,minmax(0,1fr)) 115px 165px;
  gap:1px;padding:0;overflow:hidden
}
.stat,.population,.next{
  position:relative;padding:13px 14px;background:rgba(9,11,15,.24)
}
.stat small,.population small,.next small{
  display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.12em
}
.stat strong,.population strong,.next strong{display:block;font-size:21px;margin-top:5px;line-height:1}
.stat .tiny{font-size:9px;color:var(--muted);margin-top:6px}
.stat .progress{height:4px;margin-top:6px}
.population strong{font-size:24px;color:var(--cyan)}
.next strong{font-size:16px;color:var(--green2);margin-top:7px}
.next .tiny{font-size:9px;color:var(--muted);margin-top:7px;line-height:1.3}

/* Connection state / setup */
.signal{
  position:absolute;left:0;bottom:116px;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);padding:6px 9px;background:rgba(12,14,18,.6);border-radius:8px
}
.signal.bad .dot{background:var(--danger);box-shadow:0 0 10px rgba(255,116,132,.6)}
.setup{
  position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  width:520px;padding:24px;background:var(--bg2);border:1px solid var(--line);
  border-radius:16px;box-shadow:var(--shadow)
}
.setup h1{font-size:24px;margin:6px 0 12px}
.setup input{
  width:100%;padding:12px 13px;border:1px solid rgba(255,255,255,.12);
  border-radius:9px;background:#11131a;color:white;font-size:15px;outline:none
}
.setup button{
  margin-top:10px;padding:11px 15px;border:0;border-radius:9px;
  background:linear-gradient(90deg,var(--green),var(--violet));color:#14151a;font-weight:850;cursor:pointer
}

@media(max-width:1450px){
  body{padding:18px}
  .society{width:350px}
  .today{width:350px;bottom:108px}
  .ops,.activity{width:430px}
  .event{width:520px}
  .telemetry{grid-template-columns:repeat(6,minmax(0,1fr)) 95px 135px;height:92px}
  .activity{bottom:108px}
  .signal{bottom:102px}
}

/* Layout editor ---------------------------------------------------------- */
.panel-hidden{display:none!important}
.layout-edit .movable{
  cursor:grab;
  outline:1px dashed rgba(152,215,155,.46);
  outline-offset:3px;
}
.layout-edit .movable.dragging{
  cursor:grabbing;
  outline-color:var(--green2);
  box-shadow:0 18px 52px rgba(0,0,0,.5),0 0 0 2px rgba(152,215,155,.12);
  user-select:none;
}
.drag-grip{
  display:none;
  position:absolute;
  right:9px;top:8px;
  z-index:4;
  min-width:30px;height:28px;
  align-items:center;justify-content:center;
  border:1px solid rgba(255,255,255,.12);
  border-radius:7px;
  background:rgba(8,10,14,.72);
  color:var(--muted);
  font-size:15px;
  line-height:1;
  pointer-events:none;
}
.layout-edit .movable .drag-grip{display:flex}

.layout-launch{
  display:none;
  position:absolute;
  right:0;bottom:116px;
  z-index:1000;
  border:1px solid var(--line);
  border-radius:10px;
  background:rgba(18,20,27,.92);
  color:#fff;
  padding:9px 12px;
  font:700 11px/1 system-ui,sans-serif;
  letter-spacing:.04em;
  cursor:pointer;
}
.editor-enabled .layout-launch{display:block}

.layout-panel{
  display:none;
  position:absolute;
  right:0;bottom:164px;
  z-index:1001;
  width:286px;
  padding:14px;
  border:1px solid var(--line);
  border-radius:14px;
  background:rgba(18,20,27,.97);
  box-shadow:var(--shadow);
}
.layout-panel.open{display:block}
.layout-panel h3{margin:0 0 4px;font-size:14px}
.layout-panel p{margin:0 0 11px;color:var(--muted);font-size:10px;line-height:1.35}
.layout-actions{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
.layout-actions button,.panel-toggle{
  border:1px solid rgba(255,255,255,.11);
  border-radius:8px;
  background:rgba(255,255,255,.055);
  color:#fff;
  min-height:34px;
  padding:7px 9px;
  font:700 10px/1 system-ui,sans-serif;
  cursor:pointer;
}
.layout-actions button:hover,.panel-toggle:hover{background:rgba(255,255,255,.10)}
.panel-toggle-row{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding:6px 0;
  border-top:1px solid rgba(255,255,255,.06);
}
.panel-toggle-row span{font-size:10px;color:#d8d7df}
.panel-toggle[aria-pressed="true"]{color:var(--green2);border-color:rgba(152,215,155,.35)}
.panel-toggle[aria-pressed="false"]{color:#ff9aa6;border-color:rgba(255,116,132,.28)}
.edit-note{
  margin-top:10px!important;
  padding-top:9px;
  border-top:1px solid rgba(255,255,255,.07);
}

/* When a saved free-position layout is restored, these classes let JS
   override the original anchor rules without fighting right/bottom/transform. */
.free-position{
  right:auto!important;
  bottom:auto!important;
  transform:none!important;
}

/* Editor must remain usable at common OBS canvas sizes. */
@media(max-width:1450px){
  .layout-launch{bottom:102px}
  .layout-panel{bottom:146px}
}


/* Single-panel OBS source mode ------------------------------------------ */
/* Use ?panel=society, ?panel=ops, etc. to make each card its own OBS
   Browser Source so OBS can move/resize every panel independently. */
body.single-panel{
  padding:0!important;
  overflow:hidden!important;
  background:transparent!important;
}
body.single-panel .hud{
  width:100%;
  height:100%;
}
body.single-panel .movable[data-panel]{
  display:none!important;
}
body.single-panel .movable[data-panel].panel-selected{
  display:block!important;
  position:absolute!important;
  left:0!important;
  top:0!important;
  right:auto!important;
  bottom:auto!important;
  transform:none!important;
  margin:0!important;
  max-width:100%!important;
}
body.single-panel .panel-selected.society{width:min(410px,100%)!important}
body.single-panel .panel-selected.today{width:min(410px,100%)!important}
body.single-panel .panel-selected.event{width:min(620px,100%)!important}
body.single-panel .panel-selected.ops{width:min(505px,100%)!important}
body.single-panel .panel-selected.activity{width:min(505px,100%)!important}
body.single-panel .panel-selected.telemetry{
  width:100%!important;
  height:auto!important;
  grid-template-columns:repeat(6,minmax(0,1fr)) 115px 165px!important
}
body.single-panel .panel-selected.signal{
  width:auto!important;
  display:inline-block!important
}
body.single-panel .layout-launch,
body.single-panel .layout-panel{
  display:none!important
}
body.single-panel .drag-grip{display:none!important}

/* Compact individual source variants */
body.single-panel.panel-telemetry .hud{min-height:102px}
body.single-panel.panel-signal .hud{min-height:36px}

/* Mobile dashboard ------------------------------------------------------- */
/* On phones, the overlay becomes a normal stacked dashboard instead of
   shrinking the 16:9 OBS layout. Saved desktop positions are ignored. */
@media(max-width:820px){
  html,body{
    width:100%;
    min-height:100%;
    height:auto;
    overflow-x:hidden;
    overflow-y:auto;
    background:#0c0e12;
  }
  body{
    padding:10px;
  }
  .hud{
    position:relative;
    width:100%;
    height:auto;
    display:flex;
    flex-direction:column;
    gap:10px;
    min-width:0;
  }

  .card,
  .society,
  .today,
  .event,
  .ops,
  .activity,
  .telemetry,
  .signal{
    position:relative!important;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    transform:none!important;
    width:100%!important;
    max-width:100%!important;
    height:auto!important;
    min-width:0;
    margin:0;
  }

  .card{
    border-radius:13px;
    box-shadow:0 10px 28px rgba(0,0,0,.32);
  }

  .society{order:1;padding:16px}
  .today{order:2;padding:15px 16px}
  .event{order:3;padding:15px 16px}
  .ops{order:4;padding:15px}
  .activity{order:5;padding:14px}
  .telemetry{
    order:6;
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:1px;
    overflow:hidden;
    padding:0;
  }
  .signal{
    order:7;
    display:block;
    padding:8px 10px;
    border:1px solid rgba(255,255,255,.07);
    background:rgba(12,14,18,.78);
    border-radius:9px;
  }

  .society h1{font-size:24px}
  .society-title{align-items:center}
  .tier-chip{font-size:10px}
  .world-line{
    font-size:11px;
    gap:6px;
  }

  .event-title{
    align-items:flex-start;
    gap:10px;
  }
  .event-title h2{
    font-size:18px;
    min-width:0;
    overflow-wrap:anywhere;
  }
  .timer{font-size:16px;white-space:nowrap}
  .event-meta{
    gap:8px 12px;
    font-size:10px;
  }
  .leaders{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
    line-height:1.4;
  }

  .ops-grid{
    grid-template-columns:1fr;
    gap:8px;
  }
  .module{
    min-width:0;
    padding:10px 11px;
  }
  .story-path-head{
    font-size:10px;
  }
  .story-path-name{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
  }
  .story-summary{
    font-size:9px;
  }

  .module .value,
  .rumor,
  .condition p,
  .next .tiny{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
    overflow-wrap:anywhere;
    word-break:normal;
  }

  .activity-msg{
    white-space:normal;
    overflow:hidden;
    text-overflow:clip;
    overflow-wrap:anywhere;
    word-break:break-word;
    display:-webkit-box;
    -webkit-box-orient:vertical;
    -webkit-line-clamp:2;
    line-clamp:2;
  }

  .activity-list{gap:6px}
  .activity-item{
    grid-template-columns:7px minmax(0,1fr);
    padding:8px;
  }
  .activity-action{
    display:block;
    margin:3px 0 0;
  }

  .stat,
  .population,
  .next{
    min-width:0;
    padding:11px 10px;
  }
  .stat strong,
  .population strong{
    font-size:18px;
  }
  .next strong{font-size:14px}
  .stat .tiny,
  .population .tiny,
  .next .tiny{
    font-size:8px;
  }

  /* Layout editing stays available, but mobile uses automatic stacking.
     Visibility toggles still work; free-position dragging is desktop-only. */
  .layout-launch{
    position:relative!important;
    order:8;
    display:none;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    width:100%;
    min-height:44px;
    margin:0;
    padding:11px 12px;
  }
  .editor-enabled .layout-launch{display:block}

  .layout-panel{
    position:relative!important;
    order:9;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    width:100%;
    max-width:100%;
    margin:0;
    padding:14px;
  }

  .layout-actions{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:8px;
  }
  .layout-actions button,
  .panel-toggle{
    min-height:44px;
    font-size:11px;
  }
  .panel-toggle-row{
    min-height:52px;
  }

  /* Do not show drag handles in auto-stacked mobile mode. */
  .layout-edit .movable{cursor:default;outline:none}
  .layout-edit .movable .drag-grip{display:none}

  .setup{
    position:relative;
    left:auto;
    top:auto;
    transform:none;
    width:100%;
    max-width:100%;
    margin:16px 0;
    padding:18px;
  }
  .setup h1{font-size:21px}
  .setup input,
  .setup button{
    min-height:44px;
    font-size:16px;
  }
}

@media(max-width:460px){
  body{padding:8px}
  .hud{gap:8px}
  .telemetry{
    grid-template-columns:1fr!important;
  }
  .society-title{
    align-items:flex-start;
    flex-direction:column;
    gap:8px;
  }
  .world-line{
    flex-direction:column;
    align-items:flex-start;
  }
  .world-line .sep{display:none}
  .event-title{
    flex-direction:column;
  }
  .layout-actions{
    grid-template-columns:1fr;
  }
}

/* OBS-safe final override for the legacy single-panel telemetry URL.
   Keep it after every mobile rule so transformed Browser Sources cannot turn
   the rail into a clipped one-column stack. */
body.single-panel.panel-telemetry .telemetry.panel-selected{
  width:100%!important;
  height:150px!important;
  display:grid!important;
  grid-template-columns:repeat(6,minmax(0,1fr)) minmax(72px,.75fr) minmax(105px,1.1fr)!important;
}
</style>
</head>
<body>
<main id="hud" class="hud hidden">
  <section class="card society movable" data-panel="society"><span class="drag-grip">⠿</span>
    <div class="eyebrow"><span class="dot"></span>SOCIETY TELEMETRY</div>
    <div class="society-title">
      <h1>NEW ERIDIAN</h1>
      <span id="tier-chip" class="tier-chip">CONNECTING</span>
    </div>
    <div class="world-line">
      <span>Avesta Day <b id="day">—</b></span><span class="sep">•</span>
      <span id="phase">—</span><span class="sep">•</span>
      <span><b id="active-players">0</b> active</span>
    </div>
    <div class="condition">
      <strong id="condition">Waiting for world signal…</strong>
      <p id="condition-text"></p>
    </div>
    <div class="brand-motto">May Rocky's wisdom guide you…</div>
  </section>

  <section class="card today movable" data-panel="today"><span class="drag-grip">⠿</span>
    <div class="eyebrow">✦ TODAY IN NEW ERIDIAN</div>
    <div class="today-grid">
      <div class="module">
        <div class="directive-title">
          <strong id="directive-name">Loading directive…</strong>
          <span id="directive-progress">0/0</span>
        </div>
        <div id="directive-description" class="value"></div>
        <div class="progress"><i id="directive-bar"></i></div>
        <div id="directive-skills" class="value" style="margin-top:6px"></div>
      </div>
    </div>
    <div class="system-pulse">
      <div class="pulse-stat"><b id="variety-count">0</b><small>Variety done</small></div>
      <div class="pulse-stat"><b id="lore-count">0/0</b><small>Lore found</small></div>
      <div class="pulse-stat"><b id="fleet-count">0</b><small>Fleet assigned</small></div>
    </div>
    <div id="system-detail" class="system-detail"></div>
    <div id="aftermath" class="aftermath hidden"></div>
  </section>

  <section id="event" class="card event movable hidden" data-panel="event"><span class="drag-grip">⠿</span>
    <div class="eyebrow">⚠ LIVE SOCIETY EVENT</div>
    <div class="event-title">
      <h2 id="event-name">Event</h2>
      <div id="event-time" class="timer">00:00</div>
    </div>
    <div class="progress"><i id="event-bar"></i></div>
    <div class="event-meta">
      <span>Progress <b id="event-progress">0/0</b></span>
      <span>Primary <b id="event-primary">—</b></span>
      <span>Support <b id="event-support">—</b></span>
    </div>
    <div id="event-leaders" class="leaders"></div>
  </section>

  <section class="card ops movable" data-panel="ops"><span class="drag-grip">⠿</span>
    <div class="eyebrow">AVESTA OPERATIONS</div>
    <div class="ops-grid">
      <div class="module">
        <div class="row-head"><h3>🏗️ Society Project</h3><span id="project-pct" class="pct">0%</span></div>
        <div id="project-name" class="value">Loading…</div>
        <div class="progress"><i id="project-bar"></i></div>
        <div id="project-skills" class="value" style="margin-top:6px"></div>
      </div>
      <div class="module">
        <div class="row-head"><h3>📖 Weekly Story</h3><span id="story-pct" class="pct">0%</span></div>
        <div id="story-name" class="value">Loading…</div>
        <div class="progress"><i id="story-bar"></i></div>
        <div id="story-tracks" class="story-tracks"></div>
        <div id="story-summary" class="story-summary"></div>
      </div>
      <div class="module">
        <h3>💰 Market Signal</h3>
        <div id="market-primary" class="value market-hot">Loading…</div>
        <div id="market-secondary" class="value"></div>
      </div>
      <div class="module">
        <h3>📡 Society Pressure</h3>
        <div id="pressure" class="value">Scanning…</div>
      </div>
    </div>
    <div id="rumor" class="rumor"></div>
  </section>

  <section class="card activity movable" data-panel="activity"><span class="drag-grip">⠿</span>
    <div class="activity-head">
      <div class="eyebrow">RECENT CITIZEN ACTIVITY</div>
      <span id="activity-count" class="mini muted">—</span>
    </div>
    <div id="activity-list" class="activity-list"></div>
  </section>

  <section id="telemetry" class="card telemetry movable" data-panel="telemetry"><span class="drag-grip">⠿</span></section>

  <div id="signal" class="signal movable" data-panel="signal"><span class="drag-grip">⠿</span><span class="dot"></span><span id="signal-text">Connecting to New Eridian…</span></div>

  <button id="layout-launch" class="layout-launch" type="button">⚙ EDIT OVERLAY</button>
  <aside id="layout-panel" class="layout-panel" aria-label="Overlay layout editor">
    <h3>Overlay Layout</h3>
    <p>Unlock the layout, then drag any visible panel. Changes are saved automatically in this browser source.</p>
    <div class="layout-actions">
      <button id="layout-lock" type="button">🔓 Unlock</button>
      <button id="layout-reset" type="button">↺ Reset layout</button>
      <button id="layout-close" type="button">Done</button>
    </div>
    <div id="panel-toggles"></div>
    <p class="edit-note">OBS/Desktop: right-click the Browser Source → <b>Interact</b> to move panels. On mobile the dashboard auto-stacks to fit the screen; visibility toggles still work.</p>
  </aside>
</main>

<section id="setup" class="setup hidden">
  <div class="eyebrow">NEW ERIDIAN v2 · OBS SETUP</div>
  <h1>Connect society telemetry</h1>
  <div class="muted mini">Enter the Twitch channel ID used by the game.</div>
  <input id="channel" placeholder="Example: new-eridian">
  <button id="connect">Open overlay</button>
</section>

<script>
const $=s=>document.querySelector(s);
const params=new URLSearchParams(location.search);
const channel=params.get('channel');
const panelMode=(params.get('panel')||'').toLowerCase().trim();
const VALID_PANELS=new Set(['society','today','event','ops','activity','telemetry','signal']);
const statMeta={
  food:['🌾','Food'],materials:['⛏️','Materials'],development:['⚙️','Development'],
  knowledge:['🔬','Knowledge'],treasury:['🪙','Treasury'],reputation:['⭐','Reputation']
};
let lastStamp='';

function esc(v){
  return String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function fmtTime(n){
  n=Math.max(0,Number(n)||0);
  const m=Math.floor(n/60),s=n%60;
  return m+':'+String(s).padStart(2,'0');
}
function pct(v,max){return Math.max(0,Math.min(100,(Number(v)||0)/Math.max(1,Number(max)||1)*100))}
function setBar(id,value){$(id).style.width=Math.max(0,Math.min(100,Number(value)||0))+'%'}
function ago(iso){
  const sec=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));
  if(!Number.isFinite(sec))return 'time unavailable';
  if(sec<10)return 'just now';
  if(sec<60)return sec+'s ago';
  if(sec<3600)return Math.floor(sec/60)+'m ago';
  if(sec<86400)return Math.floor(sec/3600)+'h ago';
  return Math.floor(sec/86400)+'d ago';
}

function renderStats(d){
  const target=d.tier_target||1;
  const cards=Object.entries(statMeta).map(([key,[icon,label]])=>{
    const value=d.stats&&d.stats[key]!=null?d.stats[key]:0;
    return `<div class="stat">
      <small>${icon} ${label}</small>
      <strong>${Number(value).toLocaleString()}</strong>
      <div class="tiny">${d.next_tier?`${Math.min(value,target).toLocaleString()} / ${Number(target).toLocaleString()} to ${esc(d.next_tier)}`:'Maximum tier'}</div>
      <div class="progress"><i style="width:${d.next_tier?pct(value,target):100}%"></i></div>
    </div>`;
  }).join('');
  $('#telemetry').innerHTML=cards+
    `<div class="population"><small>👥 Population</small><strong>${Number(d.stats&&d.stats.population||0).toLocaleString()}</strong><div class="tiny muted">${Number(d.active_players||0)} active / 30m</div></div>`+
    `<div class="next"><small>Society Tier</small><strong>${esc(d.tier||'—')}</strong><div class="tiny">${d.next_tier?`Next: ${esc(d.next_tier)}<br>${Number(d.tier_target).toLocaleString()} each`:'Regional Hub reached'}<br>Tier bonus: ${Number(d.tier_bonus||0)?('+'+Number(d.tier_bonus||0)+' SC on success'):'None'}</div></div>`;
}

function conciseActivityMessage(x){
  const msg=String(x&&x.message||'').replace(/\s+/g,' ').trim();
  if(!msg)return 'Action completed';

  // Keep the useful mechanical result and drop long flavor/lore sentences.
  const signed=[];
  const rewardRe=/([+-]\d+\s+(?:[A-Za-z][A-Za-z /_-]*?))(?=(?:[,.;]|\/|\s+[+-]\d+|$))/g;
  let m;
  while((m=rewardRe.exec(msg))!==null && signed.length<4){
    let part=m[1].trim()
      .replace(/\s+/g,' ')
      .replace(/\bXP\b/i,'XP');
    if(!signed.includes(part))signed.push(part);
  }

  // Some action outputs use compact slash-separated rewards.
  if(!signed.length){
    const compact=msg.match(/[+-]\d+\s+[A-Za-z][A-Za-z ]*(?:\s*\/\s*[+-]\d+\s+[A-Za-z][A-Za-z ]*)+/);
    if(compact)return compact[0].replace(/\s*\/\s*/g,' · ');
  }

  if(signed.length)return signed.join(' · ');

  const low=msg.toLowerCase();
  if(low.includes('failed') || low.includes('failure'))return 'No reward · action failed';
  if(low.includes('no rewards') || low.includes('+0 rewards'))return 'No rewards';
  if(low.includes('completed') || low.includes('completes'))return 'Completed successfully';

  // Last-resort short status. Never dump the whole response into the HUD.
  return 'Action completed';
}

function renderActivity(d){
  const rows=d.activity||[];
  $('#activity-count').textContent=rows.length?`${rows.length} latest`:'No activity';
  $('#activity-list').innerHTML=rows.slice(0,3).map((x,i)=>`
    <div class="activity-item">
      <span class="pulse"></span>
      <div class="activity-copy">
        <div class="activity-top">
          <span class="activity-who">${esc(x.name)}</span>
          <span class="activity-action">${esc(x.action)}</span>
          <span class="activity-age">${ago(x.at)}</span>
        </div>
        <div class="activity-msg" title="${esc(x.message)}">${esc(conciseActivityMessage(x))}</div>
      </div>
    </div>`).join('') || `<div class="mini muted">Waiting for citizen activity…</div>`;
}

function renderEvent(d){
  const eventPanel=$('#event');
  eventPanel.dataset.available=d.event?'1':'0';
  if(!d.event){eventPanel.classList.add('hidden');return}
  const e=d.event;
  if(VALID_PANELS.has(panelMode)){
    if(panelMode==='event')eventPanel.classList.remove('hidden');
  }else if(!isPanelUserHidden('event')){
    eventPanel.classList.remove('hidden');
  }
  $('#event-name').textContent=(e.emoji||'🚨')+' '+e.name;
  $('#event-time').textContent=fmtTime(e.seconds_remaining);
  $('#event-progress').textContent=e.progress+'/'+e.goal;
  $('#event-primary').textContent=e.primary;
  $('#event-support').textContent=e.support+' '+e.support_progress+'/2';
  setBar('#event-bar',e.percent);
  const leaders=(e.leaders||[]).map((x,i)=>`${i+1}. ${x.name} · ${x.primary}P/${x.support}S`).join('   ');
  $('#event-leaders').textContent=leaders?('Top responders · '+leaders):'Awaiting first responders…';
}

function renderOps(d){
  const p=d.project||{},st=d.story||{},m=d.market||{};
  $('#project-name').textContent=(p.name||'No active project')+' · '+(p.progress||0)+'/'+(p.goal||0);
  $('#project-pct').textContent=Math.round(p.percent||0)+'%';
  $('#project-skills').textContent=(p.skills||[]).length?'Useful: '+p.skills.join(' · '):'';
  setBar('#project-bar',p.percent||0);

  $('#story-name').textContent=(st.name||'No active story')+' · '+(st.progress||0)+'/'+(st.goal||0);
  $('#story-pct').textContent=Math.round(st.percent||0)+'%';
  setBar('#story-bar',st.percent||0);
  const tracks=st.tracks||[];
  const trackTotal=tracks.reduce((sum,x)=>sum+(Number(x.value)||0),0);
  const maxTrack=Math.max(0,...tracks.map(x=>Number(x.value)||0));
  const leaderCount=tracks.filter(x=>(Number(x.value)||0)===maxTrack && maxTrack>0).length;

  function storyIcon(name){
    const n=String(name||'').toLowerCase();
    if(n.includes('investig')||n.includes('analy')||n.includes('study'))return '🔬';
    if(n.includes('stabil')||n.includes('contain')||n.includes('infrastructure'))return '🏗️';
    if(n.includes('supply')||n.includes('cargo')||n.includes('moving'))return '📦';
    if(n.includes('agriculture')||n.includes('cultivation')||n.includes('growth'))return '🌱';
    if(n.includes('search')||n.includes('route'))return '🧭';
    if(n.includes('trace'))return '📡';
    return '◆';
  }

  $('#story-tracks').innerHTML=tracks.map(x=>{
    const value=Number(x.value)||0;
    const influence=trackTotal?Math.round((value/trackTotal)*100):0;
    const leader=value===maxTrack && maxTrack>0;
    const tag=leader ? `<span class="story-leader-tag">${leaderCount>1?'TIED':'LEADING'}</span>` : '';
    return `<div class="story-path${leader?' leader':''}">
      <div class="story-path-head">
        <span class="story-path-name">${storyIcon(x.name)} ${esc(x.name)}${tag}</span>
        <span class="story-path-meta">${value} pts · ${influence}%</span>
      </div>
      <div class="story-path-bar"><i style="width:${influence}%"></i></div>
    </div>`;
  }).join('');

  if(trackTotal){
    const leaderNames=tracks
      .filter(x=>(Number(x.value)||0)===maxTrack)
      .map(x=>x.name);
    $('#story-summary').textContent=
      (leaderNames.length===1?'Current leading path: ':'Current leaders: ')+leaderNames.join(' / ');
  }else{
    $('#story-summary').textContent='No story influence recorded yet.';
  }

  $('#market-primary').textContent=m.primary?`🔥 ${m.primary.name}: ${m.primary.price} SC`:'No market signal';
  $('#market-secondary').textContent=m.secondary?`↑ ${m.secondary.name}: ${m.secondary.price} SC`:'';
  $('#pressure').textContent=(d.pressure||[]).length?(d.pressure.join(' · ')):'No critical shortages';
  $('#rumor').textContent=d.rumor?('🗣️ '+d.rumor):'';
}

function renderToday(d){
  const q=d.directive||{},g=d.engagement||{},a=d.aftermath;
  $('#directive-name').textContent=(q.complete?'✓ ':'')+(q.name||'Daily Directive');
  $('#directive-progress').textContent=(q.progress||0)+'/'+(q.goal||0);
  $('#directive-description').textContent=q.description||'New Eridian is setting today\'s shared priority.';
  $('#directive-skills').textContent=(q.skills||[]).length
    ? 'Useful: '+q.skills.join(' · ')+' · Reward '+(q.reward||'society progress')
    : '';
  setBar('#directive-bar',q.percent||0);

  $('#variety-count').textContent=Number(g.variety_complete||0).toLocaleString();
  $('#lore-count').textContent=Number(g.lore_found||0)+'/'+Number(g.lore_total||0);
  $('#fleet-count').textContent=Number(g.fleet_assigned||0).toLocaleString();
  $('#system-detail').textContent='Gear familiarity: '+Number(g.familiar_gear||0)+' familiar / '+
    Number(g.trusted_gear||0)+' trusted · '+Number(g.relationship_memories||0)+' shared memories';

  const host=$('#aftermath');
  if(!a){host.className='aftermath hidden';host.textContent='';return}
  host.className='aftermath '+(Number(a.modifier)>=0?'good':'bad');
  const sign=Number(a.modifier)>=0?'+':'';
  host.innerHTML='<b>Event aftermath '+sign+Number(a.modifier)+'%</b> · '+
    esc((a.skills||[]).join(' / '))+' · '+esc(fmtTime(a.seconds_remaining))+' remaining<br>'+esc(a.description||'');
}



function initSinglePanelMode(){
  if(!VALID_PANELS.has(panelMode))return false;
  document.body.classList.add('single-panel','panel-'+panelMode);

  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    const selected=panel.dataset.panel===panelMode;
    panel.classList.toggle('panel-selected',selected);
    panel.classList.toggle('panel-hidden',!selected);
    if(selected){
      panel.classList.remove('free-position');
      panel.style.left='';
      panel.style.top='';
    }
  });

  // Event still hides naturally when no live event exists.
  return true;
}

/* -----------------------------------------------------------------------
   Movable / toggleable OBS layout
   Add ?edit=1 to the overlay URL to expose the editor.
   Layout and visibility are persisted in this Browser Source via localStorage.
------------------------------------------------------------------------ */
const LAYOUT_KEY='new-eridian-v2-overlay-layout-v2';
const PANEL_LABELS={
  society:'Society / World',
  today:'Today / New Systems',
  event:'Live Event',
  ops:'Operations',
  activity:'Recent Activity',
  telemetry:'Society Stats',
  signal:'Connection Signal'
};
let layoutState={positions:{},hidden:{},locked:true};
let dragState=null;

function readLayout(){
  try{
    const saved=JSON.parse(localStorage.getItem(LAYOUT_KEY)||'{}');
    if(saved && typeof saved==='object'){
      layoutState.positions=saved.positions&&typeof saved.positions==='object'?saved.positions:{};
      layoutState.hidden=saved.hidden&&typeof saved.hidden==='object'?saved.hidden:{};
      layoutState.locked=saved.locked!==false;
    }
  }catch(e){}
}
function saveLayout(){
  try{localStorage.setItem(LAYOUT_KEY,JSON.stringify(layoutState))}catch(e){}
}
function isPanelUserHidden(id){return !!layoutState.hidden[id]}

function getHudRect(){return $('#hud').getBoundingClientRect()}
function applyPanelPosition(panel,pos){
  if(!pos)return;
  const hud=getHudRect();
  const w=panel.offsetWidth||1,h=panel.offsetHeight||1;
  const maxX=Math.max(0,hud.width-w),maxY=Math.max(0,hud.height-h);
  const x=Math.max(0,Math.min(maxX,(Number(pos.x)||0)*hud.width));
  const y=Math.max(0,Math.min(maxY,(Number(pos.y)||0)*hud.height));
  panel.classList.add('free-position');
  panel.style.left=x+'px';
  panel.style.top=y+'px';
}
function applyLayout(){
  if(VALID_PANELS.has(panelMode))return;
  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    const id=panel.dataset.panel;
    panel.classList.toggle('panel-hidden',isPanelUserHidden(id));
    applyPanelPosition(panel,layoutState.positions[id]);
  });
  $('#hud').classList.toggle('layout-edit',!layoutState.locked);
  $('#layout-lock').textContent=layoutState.locked?'🔓 Unlock':'🔒 Lock';
  renderPanelToggles();
}
function capturePanelPosition(panel,left,top){
  const hud=getHudRect();
  layoutState.positions[panel.dataset.panel]={
    x:hud.width?left/hud.width:0,
    y:hud.height?top/hud.height:0
  };
  saveLayout();
}
function renderPanelToggles(){
  const host=$('#panel-toggles');
  if(!host)return;
  host.innerHTML='';
  Object.entries(PANEL_LABELS).forEach(([id,label])=>{
    const row=document.createElement('div');
    row.className='panel-toggle-row';
    const name=document.createElement('span');
    name.textContent=label;
    const btn=document.createElement('button');
    btn.type='button';
    btn.className='panel-toggle';
    const visible=!isPanelUserHidden(id);
    btn.setAttribute('aria-pressed',visible?'true':'false');
    btn.textContent=visible?'Visible':'Hidden';
    btn.addEventListener('click',()=>{
      layoutState.hidden[id]=!layoutState.hidden[id];
      saveLayout();
      applyLayout();
      // If there is no active event, keep its data-driven hidden state too.
      if(id==='event' && $('#event').dataset.available!=='1')$('#event').classList.add('hidden');
    });
    row.append(name,btn);
    host.appendChild(row);
  });
}
function resetLayout(){
  layoutState={positions:{},hidden:{},locked:false};
  saveLayout();
  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    panel.classList.remove('free-position','panel-hidden');
    panel.style.left='';
    panel.style.top='';
  });
  applyLayout();
  if($('#event').dataset.available!=='1')$('#event').classList.add('hidden');
}
function beginDrag(e){
  if(window.matchMedia('(max-width:820px)').matches)return;
  if(layoutState.locked)return;
  const panel=e.target.closest('.movable[data-panel]');
  if(!panel || e.button!==0)return;
  if(e.target.closest('button,input,a'))return;
  const hud=getHudRect(),r=panel.getBoundingClientRect();
  dragState={
    panel,
    pointerId:e.pointerId,
    dx:e.clientX-r.left,
    dy:e.clientY-r.top
  };
  panel.classList.add('dragging','free-position');
  panel.style.left=(r.left-hud.left)+'px';
  panel.style.top=(r.top-hud.top)+'px';
  if(panel.setPointerCapture)panel.setPointerCapture(e.pointerId);
  e.preventDefault();
}
function moveDrag(e){
  if(!dragState || e.pointerId!==dragState.pointerId)return;
  const panel=dragState.panel,hud=getHudRect();
  const maxX=Math.max(0,hud.width-panel.offsetWidth);
  const maxY=Math.max(0,hud.height-panel.offsetHeight);
  const left=Math.max(0,Math.min(maxX,e.clientX-hud.left-dragState.dx));
  const top=Math.max(0,Math.min(maxY,e.clientY-hud.top-dragState.dy));
  panel.style.left=left+'px';
  panel.style.top=top+'px';
  capturePanelPosition(panel,left,top);
}
function endDrag(e){
  if(!dragState || e.pointerId!==dragState.pointerId)return;
  dragState.panel.classList.remove('dragging');
  if(dragState.panel.releasePointerCapture)dragState.panel.releasePointerCapture(e.pointerId);
  dragState=null;
}
function initLayoutEditor(){
  if(VALID_PANELS.has(panelMode))return;
  readLayout();
  const editor=params.get('edit')==='1';
  if(editor)$('#hud').classList.add('editor-enabled');

  $('#layout-launch').addEventListener('click',()=>{
    $('#layout-panel').classList.toggle('open');
  });
  $('#layout-close').addEventListener('click',()=>{
    $('#layout-panel').classList.remove('open');
  });
  $('#layout-lock').addEventListener('click',()=>{
    layoutState.locked=!layoutState.locked;
    saveLayout();
    applyLayout();
  });
  $('#layout-reset').addEventListener('click',()=>{
    if(confirm('Reset all panel positions and visibility?'))resetLayout();
  });

  $('#hud').addEventListener('pointerdown',beginDrag);
  $('#hud').addEventListener('pointermove',moveDrag);
  $('#hud').addEventListener('pointerup',endDrag);
  $('#hud').addEventListener('pointercancel',endDrag);

  window.addEventListener('resize',()=>{
    document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
      applyPanelPosition(panel,layoutState.positions[panel.dataset.panel]);
    });
  });

  applyLayout();
}

async function refresh(){
  try{
    const r=await fetch('/api/v1/overlay?channel='+encodeURIComponent(channel),{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d.ok)throw new Error('Overlay unavailable');

    $('#tier-chip').textContent=d.tier||'—';
    $('#day').textContent=d.day!=null?d.day:'—';
    $('#phase').textContent=(d.phase_emoji||'')+' '+(d.phase||'');
    $('#active-players').textContent=d.active_players!=null?d.active_players:0;
    $('#condition').textContent=d.condition||'Unknown condition';
    $('#condition-text').textContent=d.condition_text||'';
    renderOps(d);
    renderToday(d);
    renderEvent(d);
    renderStats(d);
    renderActivity(d);

    $('#signal').classList.remove('bad');
    $('#signal-text').textContent='LIVE SIGNAL · updated just now';
    lastStamp=d.updated_at||'';
  }catch(e){
    $('#signal').classList.add('bad');
    $('#signal-text').textContent='SIGNAL INTERRUPTED · retrying';
  }
}

if(channel){
  $('#hud').classList.remove('hidden');
  initSinglePanelMode();
  initLayoutEditor();
  refresh();
  setInterval(refresh,3500);
  setInterval(()=>{
    if(lastStamp && !$('#signal').classList.contains('bad'))
      $('#signal-text').textContent='LIVE SIGNAL · '+ago(lastStamp);
  },1000);
}else{
  $('#setup').classList.remove('hidden');
  $('#connect').onclick=()=>{
    const v=$('#channel').value.trim();
    if(v)location.href='/overlay?channel='+encodeURIComponent(v);
  };
  $('#channel').addEventListener('keydown',e=>{
    if(e.key==='Enter')$('#connect').click();
  });
}
</script>
</body>
</html>"""


@app.get("/obs/{panel}",response_class=HTMLResponse)
def standalone_obs_panel(panel:str,channel:str="new-eridian"):
    valid={"society","today","event","ops","activity","telemetry","signal"}
    panel=(panel or "").lower().strip()
    if panel not in valid:
        raise HTTPException(status_code=404,detail="Unknown OBS panel")

    panel_json=json.dumps(panel)
    channel_json=json.dumps(channel)

    html=r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Eridian v2 OBS Panel</title>
<style>
:root{color-scheme:dark;--line:rgba(147,154,255,.36);--line2:rgba(89,218,255,.30);--text:#fffaf0;--muted:#aca9c9;--green:#7ee3b0;--green2:#b8f4d0;--violet:#bd91ff;--cyan:#70ddff;--amber:#ffd27a;--danger:#ff7484;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text);-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}body{padding:4px}#root{width:100%;height:100%}
.card{width:100%;max-width:100%;overflow:hidden;background:radial-gradient(circle at 90% 0,rgba(125,72,220,.12),transparent 42%),linear-gradient(145deg,rgba(8,13,39,.98),rgba(24,15,54,.96));border:1px solid rgba(147,154,255,.48);border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.34);padding:18px 20px}
.eyebrow{font-size:12px;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--green2)}.muted{color:var(--muted)}.small{font-size:12px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}.wrap{flex-wrap:wrap}
h1,h2,h3,p{margin:0}h1{font-family:Georgia,"Times New Roman",serif;font-size:31px;line-height:1.05;color:#fff8e8;text-shadow:0 0 3px rgba(255,248,232,.38)}h2{font-size:24px}
.progress{height:8px;margin-top:9px;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.08)}.progress i{display:block;height:100%;width:0;border-radius:999px;background:linear-gradient(90deg,var(--green),var(--violet))}
.chip{padding:5px 9px;border:1px solid var(--line2);border-radius:999px;background:rgba(152,215,155,.08);color:var(--green2);font-size:12px;font-weight:800}
.sep{opacity:.35}.worldline{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px;font-size:13px}.condition{margin-top:13px;padding-top:12px;border-top:1px solid rgba(255,255,255,.09)}.condition strong{font-size:15px}.condition p{margin-top:5px;font-size:12px;color:var(--muted);line-height:1.4}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.module{min-width:0;padding:12px;border:1px solid rgba(255,255,255,.09);background:rgba(7,9,13,.28);border-radius:10px}.module h3{font-size:14px;margin-bottom:5px}.value{font-size:12px;color:var(--muted);line-height:1.4;overflow-wrap:anywhere}.rumor{margin-top:11px;padding-top:10px;border-top:1px solid rgba(255,255,255,.09);font-size:11px;line-height:1.4;color:var(--muted)}
.storypaths{display:flex;flex-direction:column;gap:8px;margin-top:9px}.pathhead{display:flex;justify-content:space-between;gap:8px;font-size:11px}.pathname{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pathmeta{white-space:nowrap;color:var(--muted)}.path.lead .pathname,.path.lead .pathmeta{color:var(--green2)}.pathbar{height:6px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden;margin-top:4px}.pathbar i{display:block;height:100%;background:var(--cyan)}.path.lead .pathbar i{background:var(--green2)}
.activity-list{display:flex;flex-direction:column;gap:9px;margin-top:11px}.activity{display:grid;grid-template-columns:8px minmax(0,1fr);gap:10px;min-width:0;padding:9px 10px;border-radius:9px;background:rgba(7,9,13,.30)}.pulse{width:8px;height:8px;border-radius:50%;background:var(--violet);margin-top:5px}.activity:first-child .pulse{background:var(--green)}.top{display:flex;gap:8px;flex-wrap:wrap;min-width:0}.who{font-size:12px;font-weight:850;overflow-wrap:anywhere}.action{font-size:11px;color:var(--cyan);letter-spacing:.07em;text-transform:uppercase;overflow-wrap:anywhere}.age{margin-left:auto;font-size:11px;color:var(--muted);white-space:nowrap}.msg{font-size:12px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr)) 120px 170px;gap:1px;padding:0;overflow:hidden}.stat,.pop,.tier{min-width:0;padding:13px 12px;background:rgba(8,10,14,.28)}.stat small,.pop small,.tier small{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.stat strong,.pop strong{display:block;font-size:23px;margin-top:5px}.tier strong{display:block;font-size:18px;color:var(--green2);margin-top:6px}.tiny{font-size:10px;color:var(--muted);margin-top:6px}
.event .eyebrow{color:#ff9aa6}.timer{font-size:23px;font-weight:850}.eventmeta{display:flex;gap:14px;flex-wrap:wrap;margin-top:11px;font-size:12px;color:var(--muted)}.eventmeta b{color:#fff}
.signal{display:inline-flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid rgba(255,255,255,.11);border-radius:9px;background:rgba(12,14,18,.94);font-size:11px;letter-spacing:.10em;text-transform:uppercase;color:var(--muted)}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px rgba(152,215,155,.48)}.bad .dot{background:var(--danger)}
/* A standalone OBS source should keep its intended card layout even if OBS
   reports a narrow CSS viewport before the source is transformed on canvas. */
body.panel-ops .grid2{grid-template-columns:1fr 1fr!important}
body.panel-today .grid2{grid-template-columns:repeat(3,minmax(0,1fr))!important}
/* OBS can report a narrow CSS viewport even after the source is transformed
   wide on the canvas. The telemetry rail must always remain one horizontal
   row; otherwise OBS stretches a mobile stack and clips everything after Food. */
body.panel-telemetry{padding:0!important}
body.panel-telemetry #root{min-width:0}
body.panel-telemetry .stats{
  width:100%;height:150px;
  grid-template-columns:repeat(6,minmax(0,1fr)) minmax(72px,.75fr) minmax(105px,1.1fr)!important;
  border-radius:12px
}
body.panel-telemetry .stat,
body.panel-telemetry .pop,
body.panel-telemetry .tier{padding:10px 9px}
body.panel-telemetry .tiny{white-space:normal;line-height:1.2}
</style>
</head>
<body class="panel-__BODY_CLASS__">
<div id="root"><section class="card"><div class="eyebrow">New Eridian Signal</div><div class="value" style="margin-top:6px">Connecting to Avesta telemetry…</div></section></div>
<script>
const PANEL=__PANEL__;
const CHANNEL=__CHANNEL__;
const root=document.getElementById('root');
const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const pct=(v,max)=>Math.max(0,Math.min(100,(Number(v)||0)/Math.max(1,Number(max)||1)*100));
const bar=value=>`<div class="progress"><i style="width:${Math.max(0,Math.min(100,Number(value)||0))}%"></i></div>`;
const fmtTime=n=>{n=Math.max(0,Number(n)||0);return Math.floor(n/60)+':'+String(n%60).padStart(2,'0')};
const ago=iso=>{const sec=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));if(sec<10)return 'just now';if(sec<60)return sec+'s ago';if(sec<3600)return Math.floor(sec/60)+'m ago';if(sec<86400)return Math.floor(sec/3600)+'h ago';return Math.floor(sec/86400)+'d ago'};

function concise(msg){
  msg=String(msg||'').replace(/\s+/g,' ').trim();
  const found=[]; const re=/([+-]\d+\s+(?:[A-Za-z][A-Za-z /_-]*?))(?=(?:[,.;]|\/|\s+[+-]\d+|$))/g; let m;
  while((m=re.exec(msg))!==null&&found.length<4){const x=m[1].trim().replace(/\s+/g,' ');if(!found.includes(x))found.push(x)}
  if(found.length)return found.join(' · '); if(/fail/i.test(msg))return 'No reward · action failed'; return 'Action completed';
}
function renderSociety(d){root.innerHTML=`<section class="card"><div class="eyebrow">Society Telemetry</div><div class="row" style="margin-top:5px"><h1>NEW ERIDIAN</h1><span class="chip">${esc(d.tier)}</span></div><div class="worldline"><span>Avesta Day <b>${d.day}</b></span><span class="sep">•</span><span>${esc((d.phase_emoji||'')+' '+(d.phase||''))}</span><span class="sep">•</span><span><b>${d.active_players||0}</b> active</span></div><div class="condition"><strong>${esc(d.condition||'Unknown condition')}</strong><p>${esc(d.condition_text||'')}</p></div><div class="value" style="margin-top:9px;color:#8f86bb;font-family:Georgia,serif">May Rocky's wisdom guide you…</div></section>`}
function renderToday(d){const q=d.directive||{},g=d.engagement||{},a=d.aftermath;const after=a?`<div class="rumor"><b style="color:${Number(a.modifier)>=0?'var(--green2)':'var(--danger)'}">Event aftermath ${Number(a.modifier)>=0?'+':''}${Number(a.modifier)}%</b> · ${esc((a.skills||[]).join(' / '))} · ${fmtTime(a.seconds_remaining)} remaining<br>${esc(a.description||'')}</div>`:'';root.innerHTML=`<section class="card"><div class="eyebrow">✦ Today in New Eridian</div><div class="module" style="margin-top:10px"><div class="row"><h3>${q.complete?'✓ ':''}${esc(q.name||'Daily Directive')}</h3><b class="small" style="color:var(--cyan)">${q.progress||0}/${q.goal||0}</b></div><div class="value">${esc(q.description||'')}</div>${bar(q.percent||0)}<div class="value" style="margin-top:5px">Useful: ${esc((q.skills||[]).join(' · '))} · Reward ${esc(q.reward||'society progress')}</div></div><div class="grid2" style="grid-template-columns:repeat(3,1fr)"><div class="module"><h3>${Number(g.variety_complete||0)}</h3><div class="value">Variety done</div></div><div class="module"><h3>${Number(g.lore_found||0)}/${Number(g.lore_total||0)}</h3><div class="value">Lore found</div></div><div class="module"><h3>${Number(g.fleet_assigned||0)}</h3><div class="value">Fleet assigned</div></div></div><div class="value" style="margin-top:7px">Gear familiarity: ${Number(g.familiar_gear||0)} familiar / ${Number(g.trusted_gear||0)} trusted · ${Number(g.relationship_memories||0)} shared memories</div>${after}</section>`}
function renderEvent(d){const e=d.event;if(!e){root.innerHTML=`<section class="card event"><div class="eyebrow">Live Society Event</div><h2 style="margin-top:6px">No active event</h2><p class="value" style="margin-top:5px">New Eridian is currently stable.</p></section>`;return}root.innerHTML=`<section class="card event"><div class="eyebrow">⚠ Live Society Event</div><div class="row" style="margin-top:5px"><h2>${esc((e.emoji||'🚨')+' '+e.name)}</h2><span class="timer">${fmtTime(e.seconds_remaining)}</span></div>${bar(e.percent)}<div class="eventmeta"><span>Progress <b>${e.progress}/${e.goal}</b></span><span>Primary <b>${esc(e.primary)}</b></span><span>Support <b>${esc(e.support)}</b></span></div></section>`}
function renderOps(d){const p=d.project||{},st=d.story||{},m=d.market||{},tracks=st.tracks||[],total=tracks.reduce((a,x)=>a+(Number(x.value)||0),0),max=Math.max(0,...tracks.map(x=>Number(x.value)||0));const paths=tracks.map(x=>{const value=Number(x.value)||0,share=total?Math.round(value/total*100):0,lead=value===max&&max>0;return `<div class="path${lead?' lead':''}"><div class="pathhead"><span class="pathname">${esc(x.name)}${lead?' · LEADING':''}</span><span class="pathmeta">${value} · ${share}%</span></div><div class="pathbar"><i style="width:${share}%"></i></div></div>`}).join('');root.innerHTML=`<section class="card"><div class="eyebrow">Avesta Operations</div><div class="grid2"><div class="module"><h3>🏗️ Society Project</h3><div class="value">${esc(p.name||'None')} · ${p.progress||0}/${p.goal||0}</div>${bar(p.percent||0)}<div class="value" style="margin-top:5px">${esc((p.skills||[]).join(' · '))}</div></div><div class="module"><h3>📖 Weekly Story · ${Math.round(st.percent||0)}%</h3><div class="value">${esc(st.name||'None')} · ${st.progress||0}/${st.goal||0}</div>${bar(st.percent||0)}<div class="storypaths">${paths}</div></div><div class="module"><h3>💰 Market Signal</h3><div class="value" style="color:var(--amber)">🔥 ${esc(m.primary&&m.primary.name||'None')}${m.primary?' · '+m.primary.price+' SC':''}</div><div class="value">${m.secondary?'↑ '+esc(m.secondary.name)+' · '+m.secondary.price+' SC':''}</div></div><div class="module"><h3>📡 Society Pressure</h3><div class="value">${esc((d.pressure||[]).join(' · ')||'No critical shortages')}</div></div></div><div class="rumor">${d.rumor?'🗣️ '+esc(d.rumor):''}</div></section>`}
function renderActivity(d){const rows=(d.activity||[]).slice(0,5);root.innerHTML=`<section class="card"><div class="row"><div class="eyebrow">Recent Citizen Activity</div><span class="small muted">${rows.length} latest</span></div><div class="activity-list">${rows.length?rows.map(x=>`<div class="activity"><span class="pulse"></span><div style="min-width:0"><div class="top"><span class="who">${esc(x.name)}</span><span class="action">${esc(x.action)}</span><span class="age">${ago(x.at)}</span></div><div class="msg">${esc(concise(x.message))}</div></div></div>`).join(''):'<div class="value">Waiting for citizen activity…</div>'}</div></section>`}
function renderTelemetry(d){const meta={food:['🌾','Food'],materials:['⛏️','Materials'],development:['⚙️','Development'],knowledge:['🔬','Knowledge'],treasury:['🪙','Treasury'],reputation:['⭐','Reputation']},target=d.tier_target||1;const stats=Object.entries(meta).map(([key,[icon,label]])=>{const value=d.stats&&d.stats[key]||0;return `<div class="stat"><small>${icon} ${label}</small><strong>${Number(value).toLocaleString()}</strong><div class="tiny">${d.next_tier?`${Math.min(value,target)}/${target} to ${esc(d.next_tier)}`:'Maximum tier'}</div>${bar(d.next_tier?pct(value,target):100)}</div>`}).join('');const bonus=Number(d.tier_bonus||0);root.innerHTML=`<section class="card stats">${stats}<div class="pop"><small>👥 Population</small><strong>${Number(d.stats&&d.stats.population||0).toLocaleString()}</strong><div class="tiny">${d.active_players||0} active / 30m</div></div><div class="tier"><small>Society Tier</small><strong>${esc(d.tier||'—')}</strong><div class="tiny">${d.next_tier?'Next: '+esc(d.next_tier)+' · '+d.tier_target+' each':'Regional Hub reached'}<br>Tier bonus: ${bonus?('+'+bonus+' SC on success'):'None'}</div></div></section>`}
function renderSignal(ok=true){root.innerHTML=`<div class="signal${ok?'':' bad'}"><span class="dot"></span>${ok?'LIVE SIGNAL · NEW ERIDIAN':'SIGNAL INTERRUPTED · RETRYING'}</div>`}
function render(d){if(PANEL==='society')renderSociety(d);else if(PANEL==='today')renderToday(d);else if(PANEL==='event')renderEvent(d);else if(PANEL==='ops')renderOps(d);else if(PANEL==='activity')renderActivity(d);else if(PANEL==='telemetry')renderTelemetry(d);else renderSignal(true)}
async function refresh(){try{const response=await fetch('/api/v1/overlay?channel='+encodeURIComponent(CHANNEL),{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);const data=await response.json();if(!data.ok)throw new Error('No overlay data');render(data)}catch(err){if(PANEL==='signal')renderSignal(false);else root.innerHTML=`<section class="card"><div class="eyebrow" style="color:var(--danger)">Signal Interrupted</div><div class="value" style="margin-top:6px">Retrying New Eridian telemetry…</div></section>`}}
refresh();setInterval(refresh,3500);
</script>
</body></html>"""
    html=(html.replace("__BODY_CLASS__",panel)
              .replace("__PANEL__",panel_json)
              .replace("__CHANNEL__",channel_json))
    return HTMLResponse(html)

@app.get("/api/v1/tick")
def tick(channel:str):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);w.heartbeat=now();expired=resolve_expired_event(db,s,w)
        if expired:return out(expired)
        started=maybe_start_auto_event(db,w,add_activity=False)
        if started:return out(started)
        db.commit();return out("")


@app.get("/api/v1/wallet")
def wallet(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        return out(f"🪙 {p.display_name} has {p.sc} SC | ⭐ Contribution {p.contribution}")

@app.get("/api/v1/progress")
@colony_command
def progress(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);tier=society_tier(s);core=min(s.food,s.materials,s.development,s.knowledge,s.treasury,s.reputation)
        next_tier=next((x for x in SOCIETY_TIERS if x[1]>core),None)
        target=next_tier[1] if next_tier else SOCIETY_TIERS[-1][1]
        unlock=f"Next: {next_tier[0]} at {target} in every major stat" if next_tier else "Maximum society tier reached"
        stats={"Food":s.food,"Materials":s.materials,"Development":s.development,"Knowledge":s.knowledge,"Treasury":s.treasury,"Reputation":s.reputation};weak=min(stats,key=stats.get)
        if next_tier:
            rows="\n".join(f"• {label}: {value}/{target}" for label,value in stats.items());next_text=f"Next tier: {next_tier[0]}\nRequirement: {target} in every major stat\nCurrent bottleneck: {weak} ({stats[weak]}/{target})"
        else:rows="\n".join(f"• {label}: {value}" for label,value in stats.items());next_text="✅ Maximum society tier reached."
        discord=f"🏗️ New Eridian — Tier Progress\n\n"+(f"{clean(viewer)}, your most useful target is {weak}.\n\n" if viewer else "")+f"Current tier: {tier[0]}\nTier bonus: {('+'+str(tier[2])+' SC on success') if tier[2] else 'None'}\n\n{rows}\n\n{next_text}\n\nUse /guide goal:society for your best matching action."
        twitch=f"🏗️ New Eridian — {tier[0]} | F{s.food} M{s.materials} D{s.development} K{s.knowledge} T{s.treasury} R{s.reputation} | {unlock} | Bottleneck {weak} {stats[weak]} | Tier bonus {tier[2] if tier[2] else 'None'}"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/rocky")
def rocky(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    sayings=[
        "A strong society grows one harvest at a time.",
        "Never underestimate a farmer.",
        "A delivery duck always remembers.",
        "Respect the Siro, but do not invite it inside.",
        "Development without food is expensive architecture.",
        "Sometimes the rock chooses you.",
        "May Rocky's wisdom guide you."
    ]
    return out(f"🪨 Rocky's Wisdom for {clean(name)}: {random.choice(sayings)}")

@app.get("/api/v1/siro")
def siro(channel:str):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
        if w.active_event=="siro":
            return out(f"☣️ SIRO ALERT | Containment {w.event_progress}/{w.event_goal}. Use !research.")
        return out("☣️ Siro report: levels are manageable. Sensors remain active around New Eridian.")

@app.get("/api/v1/admin/event/{event}/{state}")
def admin_event(event:str,state:str,channel:str,level:int=0,key:str=""):
    if key!=ADMIN_KEY:
        return out("⛔ Invalid game-admin key.")
    if level<500:
        return out("⛔ Moderator access required.")
    if event not in EVENTS or state not in {"on","off"}:
        return out("⛔ Unknown event.")
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
        if state=="on":
            if w.active_event:return out("⛔ An event is already active. Stop it before starting another.")
            result=start_event(db,w,event,"StreamElements moderator");audit_moderator(db,channel,"StreamElements level "+str(level),"eventstart",event);return out(result)
        result=cancel_event(db,w,"StreamElements moderator");audit_moderator(db,channel,"StreamElements level "+str(level),"eventstop",event);return out(result)

@app.get("/api/v1/admin/day/next")
def next_day(channel:str,level:int=0,key:str=""):
    if key!=ADMIN_KEY or level<500:
        return out("⛔ Moderator access required.")
    with SessionLocal() as db:
        s=society(db,channel);clock=db.execute(select(WorldClock).where(WorldClock.channel_id==channel)).scalar_one_or_none()
        if not clock:clock=WorldClock(channel_id=channel,anchor_at=now(),anchor_day=s.day);db.add(clock)
        clock.anchor_at=as_utc(clock.anchor_at)-timedelta(seconds=AVESTA_DAY_SECONDS)
        db.commit();state=world_clock(db,channel,s);audit_moderator(db,channel,"StreamElements level "+str(level),"daynext",f"day {state['day']}")
        return out(f"🌅 Avesta Day {state['day']} begins in New Eridian.")


@app.get("/api/v1/action/{action}")
@colony_command
def action(action:str,channel:str,uid:str,name:str="Citizen",msg:str="",provider:str="twitch"):
    with SessionLocal() as db:
        c,p=player(db,channel,provider,uid,name);s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w);event_was_active=bool(w.active_event);skill=ACTION_SKILLS.get(action);owned_business=business_for(db,p)
        if not skill and action not in {"eat","sleep"}:raise HTTPException(404,"Unknown action")
        if skill:
            blocked=task_need_gate(db,p,action,provider)
            if blocked:return PlainTextResponse(blocked) if provider=="discord" else out(blocked)
        if action=='rare':
            result=crafting_progression.rare_gather(sys.modules[__name__],db,p,item_identity.ALIASES['rare_ore'],provider)
            return platform_response(provider,result,result.replace('\n',' | '))
        if action in SEED_TASKS:
            cfg=SEED_TASKS[action]
            if lvl(skill_xp(p,skill))<cfg['unlock']:
                return out(f"🔒 {cfg['label']} requires {SKILL_LABELS[skill]} level {cfg['unlock']}. Nothing spent.")
            missing=craft_missing_materials(db,p,cfg['cost'])
            if missing:return out("🔒 Still needed: "+", ".join(missing)+'. Nothing spent.'+missing_material_sources(db,p,cfg['cost'],provider))
        workshop_tag=None
        if action in SEED_TASKS:
            rid=MERGED_TRAINING.get(action)
            if rid:
                blocked=crafting_progression.recipe_gate(sys.modules[__name__],db,p,rid,provider)
                if blocked:return out(blocked)
                r=seed_content.RECIPES[rid];req=r['requirement'].get('Skill','SK_CRAFTING')
                if seed_content.level_for(sys.modules[__name__],db,p,req)<seed_content.required_level(r):
                    return out(f'🔒 {seed_content.skill_name(req)} Lv.{seed_content.required_level(r)} required. Train lower-level recipes. Nothing spent.')
            workshop_tag=None if rid else crafting_progression.TRAINING_STATIONS.get(SEED_TASKS[action]['branch'])
        elif action in {'craft','machine','work','cargo'}:
            workshop_tag=crafting_progression.SURVIVAL
        if workshop_tag:
            station_block=crafting_progression.station_gate(sys.modules[__name__],db,p,[workshop_tag],crafting_progression.STATIONS[workshop_tag]['tier'],provider)
            if station_block:return out(station_block)
        selected_food=(msg[5:] if action=="eat" and (msg or "").startswith("food:") else "")
        foods=edible_inventory(db,p) if action=="eat" else []
        if selected_food:
            if selected_food not in {"crops","ration","meal_kit","emergency"}|set(seed_content.EDIBLE):
                return out("⚠️ Unknown food. Open /eat and choose from your food list. Nothing spent.")
            if selected_food=="emergency":
                if not emergency_food_available(db,p,foods):return out("⚠️ Emergency food requires Nutrition below 20 and no edible items. Open /eat to see your food. Nothing spent.")
            elif not any(row["key"]==selected_food and row["qty"]>0 for row in foods):
                return out("⚠️ You no longer own that food. Open /eat for your current inventory. Nothing spent.")
        if selected_food in seed_content.EDIBLE and life_state(db,p).nutrition>=100:
            return out("ℹ️ Nutrition is already full. Your food was kept.")
        advanced=(msg or "").startswith("mode:")
        mode=(msg.split(":",1)[1].split("|",1)[0] if advanced else "")
        make_prefix="/make" if provider=="discord" else "!make"
        final_products="/make category:final_products" if provider=="discord" else "!make final_products"
        advanced_components="/make category:advanced_components" if provider=="discord" else "!make advanced_components"
        if mode=="hydroponics" and item(db,channel,c,"water_filter")<=0:return out(f"🔒 Hydroponics requires a Water Filter. Craft one with {final_products}.")
        if mode=="field_analysis" and item(db,channel,c,"siro_sampler")<=0:return out(f"🔒 Field Analysis requires a Siro Sampler. Craft one with {final_products}.")
        if action=="survey" and item(db,channel,c,"sensor")<=0:return out(f"🔒 Advanced Survey requires a Sensor. Craft one with {final_products}.")
        if mode=="expedite" and material_amount(db,p,"power_cell")<=0:return out(f"🔒 Expedited Spaceport Operations require 1 Power Cell. Manufacture one with {advanced_components}.")
        if mode=="analyze" and not unique_bonus_owned(db,p,"market_analyzer"):return out(f"🔒 Market Analysis requires a Market Analyzer. Craft one with {final_products}.")
        if action=="craft" and p.ore<=0:return out("⚙️ Hematite Ore: need 1, have 0, missing 1. Use /mine to choose an ore, or buy Hematite Ore from Seed Industries. Nothing was spent.")
        if action=="delivery" and p.cargo<=0:return out(f"🦆 Cargo: need 1, have 0, missing 1. Use {'/cargo' if provider=='discord' else '!cargo'} first.")
        if action=="eat" and not any(row["qty"]>0 for row in foods):
            emergency_life=life_state(db,p)
            if emergency_life.nutrition>=TASK_NEED_MINIMUM:
                message=(f"🍲 {p.display_name}, you have no Crop, Ration, or Meal Kit, but you are not starving. "
                         f"Emergency meals are reserved for Nutrition below {TASK_NEED_MINIMUM}. "
                         f"Use {'/farm action:Harvest Crops or /seedindustries' if provider=='discord' else '!harvest or !seedindustries'} before your next meal.")
                return out(message)
        if action in {"business","businesscontract","businessinvest"} and not owned_business:return out(f"🏢 {p.display_name}, register a business first with {'/business action:Start' if provider=='discord' else '!businessstart'}.")
        if action=="businessinvest" and p.sc<(25+10*owned_business.level):return out(f"🏢 {p.display_name}, this business investment costs {25+10*owned_business.level} SC. You currently have {p.sc} SC.")
        wait=check_cooldown(db,p,action)
        if wait:return out(f"⏱️ {p.display_name}, {action_display_name(action,mode)} is ready in {wait}s.")
        life_bonus,life_notes,life=life_modifiers(db,p,skill)
        clock,pw,world_bonus,world_notes=world_rule_bundle(db,p,s,action,skill,provider)
        life_bonus+=world_bonus;life_notes.extend(world_notes)
        life_before=(life.energy,life.nutrition,life.social)
        spend_life_for_action(life,action)
        db.commit()
        job_bonus=1 if action in JOBS.get(p.job,("",set()))[1] else 0
        tier_bonus=society_tier(s)[2]
        spec_bonus=1 if skill and specialization_for(db,p,skill) else 0
        timed_sc=2 if skill and bonus_active(db,p,"seed_dividend") else 0
        timed_contribution=1 if skill and bonus_active(db,p,"civic_recognition") else 0
        timed_xp=1 if skill and bonus_active(db,p,"accelerated_learning") else 0
        crate_bonus=1 if skill in {"logistics","commerce"} and action!="businessinvest" and item(db,channel,c,"crate")>0 else 0
        # Additive SC bonuses are capped so late-game systems stay rewarding
        # without multiplying routine work into runaway income.
        bonus=min(5,job_bonus+tier_bonus+spec_bonus+timed_sc+crate_bonus);contribution_gain=1+timed_contribution;xp_gain=1+timed_xp
        branch_bonus=0
        if action in SEED_TASKS:
            branch=db.get(SkillBranch,(channel,c,SEED_TASKS[action]['branch']))
            branch_bonus=min(.05,max(0,lvl(branch.xp if branch else 0)-1)*.005)
            if branch_bonus:life_notes.append(f"Branch practice +{branch_bonus*100:g}%")
        relevant=bool(w.active_event and skill in {EVENTS[w.active_event]["primary"],EVENTS[w.active_event]["support"]})
        chance_used=[None];determination_used=[0]
        def fail(txt):
            p.actions+=1;db.commit();auto="" if event_was_active else maybe_start_auto_event(db,w,current_uid=c)
            injury=""
            if skill and random.random()<.04:
                effect=random.choice([("sore_back",15,-3,"A rough shift has left you sore."),("bent_tool",10,-2,"A tool needs a little attention."),("rattled",10,-2,"That failure shook your confidence.")])
                add_status(db,p,*effect);injury=f" 🩹 {effect[0].replace('_',' ').title()} {effect[2]:+d}% for {effect[1]}m."
            exposure=exposure_tick(db,p,pw,action,skill,clock) if skill else ""
            encounter=maybe_world_encounter(db,p,skill,clock,False) if skill else ""
            grit=determination_fail(db,p,skill)
            pref=player_preference(db,p)
            modifier_note=(life_modifier_text(provider,life_notes,chance_used[0]) if pref.result_style=="detailed" else concise_action_modifiers(provider,life_notes,chance_used[0],failed=True))
            improvement=failure_fix_text(skill,life_notes,chance_used[0],provider)
            message=txt+" No task rewards were earned."+grit+injury+exposure+encounter+modifier_note+life_change_summary(life_before,life,provider)+task_readiness_warning(life,provider)+improvement+(" "+auto if auto else "")
            if provider=="discord":message="❌ TASK FAILED\n\nWHY\n"+message.replace(" | ","\n")+"\n\nNEXT\n• Retry after the 5-second work cooldown. Determination improves the next matching attempt."
            log_action(db,channel,c,action,message);return PlainTextResponse(message) if provider=="discord" else out(message)
        def passed(base):
            determination_used[0]=determination_bonus(db,p,skill)
            if determination_used[0]:life_notes.append(f"Determination +{int(determination_used[0]*100)}%")
            chance_used[0]=min(.92,max(.10,success_chance(db,p,skill,base)+(0.05 if relevant else 0)+life_bonus+branch_bonus+determination_used[0]))
            roll=random.random()
            p._practice_quality=1.2 if roll<chance_used[0]*.25 else 1.0
            return roll<chance_used[0]
        if action in SEED_TASKS:
            cfg=SEED_TASKS[action]
            if not passed(.72):return fail(f"{cfg['label']} did not succeed. All task materials were kept.")
            for key,qty in cfg['cost'].items():material_change(db,p,key,-qty)
            for key,qty in cfg['output'].items():material_change(db,p,key,qty)
            if action in MERGED_TRAINING:craft_record(db,p,MERGED_TRAINING[action])
            shared=colony_state(db,channel);old_infrastructure=shared.infrastructure
            for key,qty in cfg['shared'].items():setattr(shared,key,min(100,getattr(shared,key)+qty) if key=='mood' else getattr(shared,key)+qty)
            housing_gain=shared.infrastructure//5-old_infrastructure//5
            shared.housing+=housing_gain
            for key,qty in cfg['society'].items():setattr(s,key,getattr(s,key)+qty)
            if cfg['branch']=='first_aid':
                db.query(StatusEffect).filter_by(channel_id=channel,canonical_uid=c,effect='sore_back').delete()
                life.comfort=clamp100(life.comfort+5)
            if cfg['skill']=='medicine' and cfg['unlock']==5:pw.siro_exposure=max(0,pw.siro_exposure-5)
            xp_gain=gain_skill(p,skill,xp_gain);gain_branch(db,p,cfg['branch'],xp_gain)
            p.sc+=2+bonus;p.contribution+=contribution_gain
            changes=[f"-{v} {resource_name(k)}" for k,v in cfg['cost'].items()]+[f"+{v} {resource_name(k)}" for k,v in cfg['output'].items()]
            changes += [f"shared {k.replace('_',' ')} +{v}" for k,v in cfg['shared'].items()]
            changes += [f"society {k.title()} +{v}" for k,v in cfg['society'].items()]
            if housing_gain:changes.append(f"shared housing +{housing_gain}")
            base=f"✅ {p.display_name} completes {cfg['label']}. +{xp_gain} {SKILL_LABELS[skill]} XP and branch XP | +{2+bonus} SC | +{contribution_gain} Contribution | "+"; ".join(changes)
        elif action=="businessinvest":
            investment_cost=25+10*owned_business.level
            p.sc-=investment_cost;xp_gain=gain_skill(p,"commerce",xp_gain);p.contribution+=1+timed_contribution;s.treasury+=3;s.development+=1;gain_business_xp(owned_business,3)
            base=f"🏢 {p.display_name} invests in {owned_business.name} (-{investment_cost} SC). +{xp_gain} Commerce XP | +{1+timed_contribution} Contribution | +3 Business XP | New Eridian gains +3 Treasury/+1 Development."
        elif action in {"farm","harvest","forage"}:
            if not passed(.68):return fail(f"🌱 {p.display_name} has a rough farming shift.")
            xp_gain=gain_skill(p,"cultivation",xp_gain);p.sc+=2+bonus;p.contribution+=contribution_gain;s.food+=1
            if action=="harvest":p.crops+=1
            base=f"🌾 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Farming XP | +{2+bonus} SC | +{contribution_gain} Contribution | New Eridian gains +1 Food."
        elif action in {"water","scan"}:
            if not passed(.68):return fail(f"💧 {p.display_name} cannot stabilize the environmental readings.")
            xp_gain=gain_skill(p,"environmental",xp_gain);p.sc+=2+bonus;p.contribution+=contribution_gain
            if action=="water":
                hydro=mode=="hydroponics";s.food+=2 if hydro else 1
                if hydro:p.crops+=1
                society_gain="+2 Food; +1 personal Crop" if hydro else "+1 Food"
            else:
                s.knowledge+=1;society_gain="+1 Knowledge"
            base=f"💧 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Processing XP | +{2+bonus} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."
        elif action in {"mine","scavenge"}:
            if not passed(.68):return fail(f"⛏️ {p.display_name} comes back empty-handed.")
            sc_gain=2+bonus;xp_gain=gain_skill(p,"extraction",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain
            p.ore+=1;s.materials+=1
            base=f"⛏️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Harvesting XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +1 Materials."
        elif action=="research":
            if not passed(.68):return fail(f"🔬 {p.display_name} gets inconclusive results.")
            field=mode=="field_analysis";knowledge_gain=2 if field else 1;sc_gain=(4 if field else 2)+bonus
            xp_gain=gain_skill(p,"research",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;s.knowledge+=knowledge_gain;base=f"🔬 {p.display_name} completes {'Field Analysis' if field else 'research'}. +{xp_gain} Research XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{knowledge_gain} Knowledge."+(" Siro Sampler activity bonus included." if field else "")
        elif action in {"craft","machine","work"}:
            if not passed(.66):return fail(f"⚙️ {p.display_name} cannot get fabrication within tolerance.")
            xp_gain=gain_skill(p,"fabrication",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain
            if action=="work":
                s.treasury+=1;society_gain="+1 Treasury"
            else:
                s.development+=1;society_gain="+1 Development"
            if action=="craft":p.ore-=1;p.components+=1
            base=f"⚙️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Crafting XP | +{3+bonus} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."
        elif action in {"repair","project","build"}:
            if not passed(.66):return fail(f"🏗️ {p.display_name} cannot bring the infrastructure back within tolerance.")
            xp_gain=gain_skill(p,"infrastructure",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain;s.development+=1
            base=f"🏗️ {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Engineering XP | +{3+bonus} SC | +{contribution_gain} Contribution | New Eridian gains +1 Development."
        elif action in {"cargo","delivery","spaceport"}:
            preferred=player_preference(db,p).assigned_duck
            duck=preferred if preferred in DELIVERY_DUCKS and random.random()<.70 else random.choice(DELIVERY_DUCKS)
            if not passed(.68):return fail(f"🦆 {p.display_name} hits a logistics delay. {duck} circles back with a deeply judgmental quack.")
            xp_gain=gain_skill(p,"logistics",xp_gain);p.sc+=3+bonus;p.contribution+=contribution_gain
            if action=="delivery":
                s.reputation+=1;society_gain="+1 Reputation"
            elif action=="spaceport" and mode=="expedite":
                material_change(db,p,"power_cell",-1);p.sc+=3;s.reputation+=1;s.treasury+=2;society_gain="+2 Treasury/+1 Reputation; -1 Power Cell"
            else:
                s.treasury+=1;society_gain="+1 Treasury"
            if action=="cargo":p.cargo+=1
            elif action=="delivery":p.cargo-=1;society_gain+="; -1 personal Cargo"
            bond=duck_bond(db,p,duck,2 if action=="delivery" else 1)
            fleet_bonus=1 if bond.xp>=50 else 0
            if fleet_bonus:p.sc+=fleet_bonus
            duck_note=random.choice([
                f" {duck} escorts the run.",
                f" {duck} handles the last stretch without incident.",
                f" {duck} arrives exactly when nobody expected.",
                f" {duck} inspects the cargo and apparently approves.",
            ])
            advanced_sc=3 if action=="spaceport" and mode=="expedite" else 0
            base=f"🦆 {p.display_name} completes {action_display_name(action,mode)} with {duck}. +{xp_gain} Logistics XP | +{3+bonus+fleet_bonus+advanced_sc} SC | +{contribution_gain} Contribution | New Eridian gains {society_gain}."+duck_note+f" Fleet bond: {duck_rank(bond.xp)} ({bond.xp} XP)."
        elif action in {"explore","survey"}:
            if not passed(.64):return fail(f"🧭 {p.display_name} returns with little useful frontier data.")
            survey_bonus=action=="survey";sc_gain=(5 if survey_bonus else 3)+bonus;knowledge_gain=2 if survey_bonus else 1
            xp_gain=gain_skill(p,"frontier",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;s.knowledge+=knowledge_gain;base=f"🧭 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Frontier Operations XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{knowledge_gain} Knowledge."+(" Sensor survey bonus included." if survey_bonus else "")
        elif action in {"market","business","businesscontract"}:
            b=owned_business if action in {"business","businesscontract"} else None
            if not passed(.70):return fail(f"🏪 {p.display_name} finds no profitable contract this cycle.")
            if action=="businesscontract":
                sc_gain=5+min(8,b.level)+bonus;gain_business_xp(b,2);s.reputation+=2;business_note=f" {b.name} secured a Level {b.level} contract and gained +2 Business XP ({b.xp}/{business_xp_needed(b.level)})."
            else:
                analysis=action=="market" and mode=="analyze";sc_gain=(6 if analysis else 4)+bonus;s.treasury+=2 if analysis else 1;business_note=" Market Analyzer activity bonus included." if analysis else ""
                if b:gain_business_xp(b,1);business_note=f" {b.name} advances to {b.xp}/{business_xp_needed(b.level)} XP."
            xp_gain=gain_skill(p,"commerce",xp_gain);p.sc+=sc_gain;p.contribution+=contribution_gain;base=f"🏪 {p.display_name} completes {action_display_name(action,mode)}. +{xp_gain} Commerce XP | +{sc_gain} SC | +{contribution_gain} Contribution | New Eridian gains +{2 if action=='businesscontract' or (action=='market' and mode=='analyze') else 1} {'Reputation' if action=='businesscontract' else 'Treasury'}.{business_note}"
        elif action=="eat":
            food_key=selected_food or next((row["key"] for key in ("ration","crops","meal_kit",*seed_content.EDIBLE) for row in foods if row["key"]==key and row["qty"]>0),"emergency")
            if food_key in seed_content.EDIBLE:
                before=life.nutrition
                material_change(db,p,food_key,-1)
                life.nutrition=clamp100(life.nutrition+seed_content.nutrition(food_key))
                base=f"🍲 {p.display_name} eats {resource_name(food_key)} (−1). Nutrition {before}→{life.nutrition}."
            elif food_key=="meal_kit":
                kits=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==c,QualityGear.item_key=="meal_kit",QualityGear.qty>0)).scalars().all()
                kit=max(kits,key=lambda row:list(QUALITY_TIERS).index(row.quality))
                nutrition_before=life.nutrition;morale_before=life.morale
                life.nutrition=clamp100(life.nutrition+75+int(QUALITY_TIERS[kit.quality]["special"]*100));life.morale=clamp100(life.morale+5)
                kit.qty-=1
                base=f"🍲 {p.display_name} eats a {kit.quality} Meal Kit (-1 Meal Kit). Nutrition {nutrition_before}→{life.nutrition}; Morale {morale_before}→{life.morale}."
            elif food_key=="ration":
                row=db.execute(select(ExtraItem).where(ExtraItem.channel_id==channel,ExtraItem.canonical_uid==c,ExtraItem.item=="ration")).scalar_one();row.qty-=1
                boost=db.execute(select(TimedBonus).where(TimedBonus.channel_id==channel,TimedBonus.canonical_uid==c,TimedBonus.bonus=="rockys_favor")).scalar_one_or_none()
                if not boost:boost=TimedBonus(channel_id=channel,canonical_uid=c,bonus="rockys_favor",expires_at=now(),times_received=0);db.add(boost)
                boost.expires_at=max(now(),as_utc(boost.expires_at))+timedelta(minutes=10);boost.times_received+=1
                life.nutrition=clamp100(life.nutrition+70);life.morale=clamp100(life.morale+5)
                base=f"🍲 {p.display_name} eats a Ration (-1 Ration). +70 Nutrition (capped at 100)/+5 Morale. Rocky's Favor: +3 percentage points to the success chance; +10 minutes (time stacks)."
            elif food_key=="crops":
                old_nutrition=life.nutrition;p.crops-=1;life.nutrition=clamp100(life.nutrition+35)
                recovery_note=""
                if old_nutrition<TASK_NEED_MINIMUM and life.nutrition<TASK_NEED_MINIMUM:
                    life.nutrition=25;recovery_note=" Recovery Protocol raised Nutrition above the work minimum."
                gained=life.nutrition-old_nutrition;life.morale=clamp100(life.morale+1)
                base=f"🍲 {p.display_name} eats a Crop (-1 Crop). +{gained} Nutrition/+1 Morale. Craft Rations for a stronger meal bonus."+recovery_note
            else:
                restored=max(0,40-life.nutrition);life.nutrition=max(40,life.nutrition);life.morale=clamp100(life.morale+1)
                base=(f"🍲 Seed Industries Recovery Protocol: {p.display_name} receives an emergency community meal. "
                      f"+{restored} Nutrition (now {life.nutrition}/100)/+1 Morale. No Crop, Ration, or SC was required. "
                      "Emergency meals are only available below 20 Nutrition when you have no food.")
        elif action=="sleep":
            sleep_gain=100-life.energy;comfort_gain=100-life.comfort
            life.energy=100;life.comfort=100;life.morale=clamp100(life.morale+3)
            pw.siro_exposure=max(0,pw.siro_exposure-8)
            base=f"🛏️ {p.display_name} clocks out for the cycle. Energy 100/100 (+{sleep_gain}); Comfort 100/100 (+{comfort_gain}); +3 Morale; Siro exposure reduced by up to 8."
        else:raise HTTPException(404,"Unknown action")
        if action=="craft":base=base.replace(" completes craft."," completes craft (-1 Hematite Ore).")
        if action=="delivery":base=base.replace(" completes delivery."," completes delivery (-1 Cargo).")
        if crate_bonus:base+=" Trade Crate: +1 SC included."
        settlement_before=society_tier_index(s)
        shared=colony_state(db,channel)
        production_action="private_meal" if action=="eat" and "emergency community meal" not in base else ("healthy_sleep" if action=="sleep" and pw.siro_exposure==0 else action)
        production=colony_produce(shared,s,production_action,productivity(life,pw.siro_exposure))
        if production:base+=" Settlement production: "+production+"."
        if action=="sleep" and "medicines -1" in production:pw.siro_exposure=max(0,pw.siro_exposure-10)
        p.actions+=1;p.successes+=1;db.commit()
        note=progress_daily(db,p,action)
        enote=event_note(db,s,w,p,action)
        anote=achieve(db,p)
        lore=rare_outcome(db,p,s,skill);db.commit();personal_bonus=grant_random_bonus(db,p,.04 if action=="businesscontract" else 0) if skill else ""
        pnote=project_contribute(db,p,skill,1) if skill else ""
        gnote=goal_progress(db,p,action,skill,project=bool(pnote))
        storynote=story_contribute(db,p,skill) if skill else ""
        wearnote=degrade_gear(db,p,skill) if skill else ""
        tutorialnote=tutorial_advance(db,p,"action") if skill else ""
        if pnote:tutorialnote+=tutorial_advance(db,p,"society")
        encounter=maybe_world_encounter(db,p,skill,clock,True) if skill else ""
        lore_note=maybe_lore_discovery(db,p,skill,clock) if skill else ""
        exposure=exposure_tick(db,p,pw,action,skill,clock) if skill else ""
        auto="" if event_was_active else maybe_start_auto_event(db,w,current_uid=c)
        preference=player_preference(db,p)
        modifier_note=((life_modifier_text(provider,life_notes,chance_used[0]) if preference.result_style=="detailed" else concise_action_modifiers(provider,life_notes,chance_used[0])) if skill and chance_used[0] is not None else "")
        variety_note=daily_variety_note(db,p,skill,clock) if skill else ""
        directive_progress=directive_note(db,p,s,skill,clock) if skill else ""
        familiarity_note=gear_familiarity_use(db,p,skill) if skill else ""
        milestone_note=near_milestone_note(db,p,skill) if skill else ""
        # Routine action cards contain the outcome and only exceptional progress.
        # Full needs, modifiers, world state, and meters stay in their dedicated hubs.
        exceptional=enote+important_progress_notes(note,pnote,storynote,encounter,exposure,anote,tutorialnote,personal_bonus,wearnote)+variety_note+directive_progress+familiarity_note+milestone_note+lore_note
        determination_note=determination_clear(db,p,skill) if determination_used[0] else ""
        message=base+determination_note+lore+exceptional+modifier_note+task_readiness_warning(life,provider)+(" "+auto if auto else "")
        if provider=="discord":message="✅ TASK COMPLETE\n\nRESULT\n"+message.replace(" | ","\n")
        log_action(db,channel,c,action,message)
        return PlainTextResponse(message) if provider=="discord" else out(message)



# ============================================================
# Discord Interactions Webhook
# ============================================================

SEED_HELP_TOPICS={
"start":"""🌱 START HERE

/seed — Opens this handbook. Choose a topic to learn every command in that group.
/guide — Reads your character, cooldowns, daily contract, society needs, and live event, then recommends your best next command. Choose a goal for focused directions.
/start — Creates your citizen if needed or loads the existing one. Use this first when joining.

BEST FIRST STEPS
1. /start
2. /job
3. /guide

Standard work, /eat, and /sleep use a 5-second cooldown. Rare prospecting uses a shared 20-second cooldown. Social and recovery actions use 20–60 seconds depending on the activity. Browsing spends nothing. Workshop crafting uses a 5-second workshop cooldown; legacy /make recipes have no cooldown. Crafting requires the listed workstation, personal tier and skill. /workshop shows unlocks; /seedindustries sells starter supplies. Check exact remaining times with /me section:Cooldowns.""",
"character":"""👤 CHARACTER & PROGRESSION

/me — One personal hub for Overview, Life Needs, Bonuses, Cooldowns, Traits, Relationships, Journal, Tutorial, Titles, and Display Style. Compact results are default; Detailed adds every modifier and final success chance.
/progress — One progression hub for Skills, Daily Contract, Achievements, and Collection.\n/training — Eight skill families with branch levels, tasks, owned supplies, and job guidance. Cooking, Medicine and Emergency Response join Farming, Harvesting, Engineering, Processing and Crafting. Research, Logistics, Frontier Operations and Commerce remain. Level 2 needs 5 XP; level 5 needs 35 XP; later levels need 15 XP each. Advanced tasks unlock at levels 3–5.
/inventory — Resources and supplies; choose Quality Gear to inspect equipment condition.
/job — Select a profession. Actions matching your job earn +1 extra SC; changing jobs does not erase XP.
/specialize — At aptitude Lv. 10, permanently choose a path. Matching actions gain +3% success and +1 SC.
/link — Claims the six-character code from Twitch !link. Compatible progress merges once; the link is permanent and one-to-one.

BEST USE: /guide goal:aptitude for training or /guide goal:seed_coin for income.""",
"property":"""🏠 HOME, BUSINESS & CRAFTING

/home action:View — Shows Habitat tier and exact next-upgrade cost.
/home action:Upgrade — Spends the displayed SC and Components. Habitat tier is personal, not society tier.
/business action:View — Shows company level, XP, contract pay, and current investment cost.
/business action:Start — Registers one permanent business for 75 SC.
/business action:Work — Routine Commerce operation and +1 Business XP on success.
/business action:Contract — Higher-paying Commerce action and +2 Business XP on success.
/business action:Invest — Costs 25 + (10 × current Business Level) SC and gives +3 Business XP, +1 Contribution, +3 Treasury, and +1 Development.
/make — Uses one production tree: Raw Materials → Basic Components → Advanced Components → Final Products. Each item appears in one stage only.
/seedindustries — Fixed-price NPC exchange plus three rotating daily Production Orders. Orders consume manufactured goods and reward SC, Contribution, Development, Crafting XP, and Commerce XP.

CRAFTING ROUTE
/farm action:Harvest Crops and /mine → gather Crops and Hematite Ore
/make recipe:Component → turn 1 Hematite Ore into 1 Component
/cargo → prepare Cargo for Power Cells
/make category:Production Tree → view the complete item chain
/make category:Basic Components → make Component, Biofiber, and Alloy Plate
/make category:Advanced Components → make Circuit Board, Power Cell, Sealant, and Precision Lens
/make category:Final Products → browse all usable supplies and equipment once
/make → assemble finished equipment from those parts

Passive-bonus equipment is unique: you may own only one of each item. Consumables and basic components can stack.
Relevant successful actions build gear familiarity. At 10/25/50 uses it reduces wear chance by 5/10/15 percentage points without adding success or pay.

ECONOMY RULE
Basic components pay 1 SC, finished supplies pay 2 SC, and quality gear pays 3 SC before the Technician bonus. Production Orders pay 75% of the NPC replacement cost, so buying every input loses SC while gathering and manufacturing creates profit.

BEST USE: /guide goal:crafting, /guide goal:home, or /guide goal:business.""",
"life":"""🌿 LIFE & SOCIAL SYSTEMS

/me section:Life Needs — Energy, Nutrition, Social, Comfort, Morale, and active effects.
/eat — Opens your food list with owned quantities. Select Food to consume one Crop, Ration, or Meal Kit. A Ration gives +70 Nutrition, +5 Morale, and 10 minutes of +3 percentage-point success; a Crop gives +35 Nutrition and +1 Morale. A Meal Kit restores Nutrition based on quality and +5 Morale. If Nutrition is below 20 and you own no food, a free emergency meal restores Nutrition to 40. All needs cap at 100.
/sleep — Fully restores Energy and Comfort to 100 at any time of day; reduces Siro exposure by up to 8.
/relax — Restores Energy, Morale, and Comfort.
/walk — Improves Morale and Exploration hobby progress.
/games — Free solo activity: +25 Social, +4–8 Morale, and Games hobby progress. No partner or item required.
/social — One hub for saying hi, hanging out, mentoring, and relationship-gated duo activities.
/hobby — Practices the selected hobby.

Greetings, hangouts, and duo activities build persistent Relationship Memories. /me section:Relationships shows the activity count and most recent shared activity.

TASK READINESS
Energy, Nutrition, and Social must each be 20 or higher to work, craft with /make, or repair personal gear with /repair. Below 20, the task does not start: no materials are consumed, no rewards are rolled, and no cooldown begins.
• Low Energy: /sleep or /relax
• Low Nutrition (hunger): /eat. With no food, it requests a free emergency meal and restores Nutrition to 40.
• Low Social: /games or /social

Comfort and Morale affect success chance but do not hard-block tasks. Recovery and information commands remain available while work is blocked. This recovery loop always provides a way back into work without requiring work first.""",
"production":"""🏭 WORK ACTIONS

/farm — Farming work: 2 SC before bonuses, +1 Contribution, base society Food plus available shared production, and condition-dependent aptitude practice on success.
/farm action:Harvest Crops — Farming work that gives a personal Crop.
/farm action:Irrigate — Processing work that adds society Food.
/farm action:Hydroponics — Requires a Water Filter and improves Food while producing a Crop.
/scan — Processing work that adds +1 society Knowledge.
/mine — Choose an ore and view its requirements, then select Mine. Count starts a queue of 1–10 attempts. Rare ores require three prospecting steps per ore. /queue shows progress, total needs and missing materials; it pauses and resumes automatically.
/rare — Prospect Argentite Ore. Harvesting Lv.3 required; three actions per ore, with a shared 20-second prospecting cooldown.
/training — Choose a skill, view branches and inventory requirements, then choose Task to work. Includes Cooking, Medicine and Emergency Response, their jobs, and level unlocks.\n/make — The complete Crafting system. Components, finished supplies, quality gear, Crafting XP, SC, and Development all live here.
/repair target:Society Infrastructure — Engineering work; adds +1 Development.
/research — Research work that raises Knowledge. Primary response for Siro Bloom.

FAILURE PROTECTION
A failed skilled task gives one Determination stack. Each stack adds +4 percentage points to the next attempt in that aptitude, up to +12%. A success uses and clears the stacks. Blocked attempts do not create Determination.

Old work routes remain compatible on Twitch/API, including !craft and !machine, but Discord uses /make as the single Crafting system.""",
"operations":"""🛰️ LOGISTICS, FRONTIER & COMMERCE

/cargo — Prepares 1 personal Cargo and adds +1 society Treasury. Use before /delivery.
/delivery — Opens your Cargo supply preview; choose Send Delivery. Requires 1 personal Cargo, consumed only on success; adds +1 Reputation, and advances delivery-fleet bond XP.
/spaceport — Standard Logistics work or Expedited Operations that consume 1 Power Cell for stronger Treasury, Reputation, and SC rewards.
/explore — Scout normally or use a Sensor for an Advanced Survey with stronger Knowledge and SC rewards.
/research — Standard research or Siro Sampler Field Analysis with stronger Knowledge and SC rewards.
/business — All company-specific viewing and actions live under one command.
/market — One hub for viewing prices, selling resources, Commerce work, and Market Analyzer activity.
/seedindustries — Buys and sells a fixed list of raw materials and manufactured parts. Its buy price is always higher than its sell price.
/ducks — Shows delivery-fleet bonds and can assign a preferred partner. Assignment focuses appearances and bond XP, not success chance or base pay.

BEST USE: /cargo → /delivery for the delivery loop; /market for society Treasury; /business action:Work to level your company.""",
"society":"""🏙️ SOCIETY, WORLD & EVENTS

/world — One hub for world overview, Conditions & Siro, Daily Bulletin, Rumor, Weekly Story, Society Project, and Market.
/society — One hub for society Overview, Next Tier Progress, and Contribution Leaderboard.
/holiday — Active festivals and the next holiday start time.
/event — One hub for Active Event and Recent Event History.
/guide goal:event — Recommends your best available response during an event.

EVENT RULES
Primary success = +1 progress.
Two support successes = +1 progress.
0–74% at expiry = full penalty.
75–99% = half penalty, rounded up.
100% = rewards and no penalty.

DAILY ENGAGEMENT
Successful work in three different aptitudes completes optional Daily Variety for +6 SC/+4 Morale. The Daily Bulletin also shows a shared Society Directive; each citizen earns at most +3 SC from participation, and completion adds +8 to one society stat. Event success creates +3% related aftermath for 60 minutes; partial/full failures create -1%/-2%. Aftermath never stacks.

BEST USE: /guide goal:event during emergencies and /guide goal:society between events.""",
"other":"""🍲 PERSONAL ACTIONS

/district — Chooses your home district.
/shift — Chooses today's role bonus.
/meal — Shows owned Crops; choose Share a Crop to contribute one to the community meal.
/use — Lists owned life items and quantities; select Item to consume one.
/repair — Choose Society Infrastructure work or Personal Quality Gear repair.
/linklookup — Owner-only lookup for connected Discord/Twitch identities.

Use /me for personal information, /progress for personal progression, and /world for shared world information.""",
"moderator":"""🛡️ MODERATOR CONTROLS

/eventstart — Starts one selected event immediately. Existing automatic-event timing is safely reset. Moderator permission required.
/eventstop — Cancels the active event with no failure penalty. This is cancellation, not success. Moderator permission required.
/modlog — Shows recent event-control records, including the moderator and action. Moderator permission required.

Eligible moderators need Administrator, Manage Server, Manage Messages, or a role listed in DISCORD_MOD_ROLE_IDS.""",
"terms":"""📖 NEW ERIDIAN TERMS

SC / Seed Coin — Personal currency used for businesses and Habitat upgrades.
Contribution — Personal society-service score used by the leaderboard.
XP — Stored aptitude practice. Successful tasks improve relevant aptitudes; occupation, living conditions, project work and outcome quality affect gain. Fractional practice carries forward. Lv. 10 unlocks specialization.
Aptitude — A skill family such as Farming, Research, or Logistics. Its level improves success chance. Commerce is an aptitude, not a crafting category.
Occupation / Job — Your profession. Matching work pays +1 SC, improves practice by 25%, and adds +2% success.
Specialization — Permanent Lv. 10 path giving matching actions +3% success and +1 SC.
Society stats — Shared Food, Materials, Development, Knowledge, Treasury, and Reputation.
Shared housing — Society-wide spaces for citizens. Fewer spaces than citizens gives -3 percentage points to task success. Supplied society repairs add Infrastructure; every 5 Infrastructure adds 1 space. Personal Habitat upgrades do not expand shared housing. See /society for current capacity and supply needs.
Society tier — Based on the lowest of all six stats. Higher tiers add modest SC pay and unlock recipes.
Primary event role — Each successful matching action adds +1 progress.
Support event role — Every two matching successes add +1 progress.
Cooldown — Standard work, /eat, and /sleep use 5 seconds. Social and recovery actions use 20–60 seconds. /make has no cooldown. Linked Twitch/Discord accounts share cooldowns.
Task readiness — Energy, Nutrition, and Social must each be at least 20 for work, /make crafting, and personal gear repair. A blocked attempt spends nothing and starts no cooldown. Recovery commands remain usable; /eat supplies an emergency meal when a starving player has no food.
Task cost — Standard work and /make use 2 Energy/1 Nutrition. Heavy extraction, frontier, and repair tasks use 3 Energy/1 Nutrition. All five life needs recharge by 1 per 15 real minutes, up to 60/100, including while away. Needs above 60 are not reduced. Food, sleep and social activities recover faster. Work also costs 1 Comfort; critical Comfort reduces morale, output and success. Results warn when recovery is required.
Personal bonus — Temporary success, SC, Contribution, or XP boost. Each activation lasts 10 minutes; matching time stacks.
Basic component — First-stage manufactured part made directly from raw material: Component, Biofiber, or Alloy Plate.
Advanced component — Specialized manufactured part made from raw materials and basic components: Circuit Board, Power Cell, Sealant, or Precision Lens.
Passive-bonus equipment — Held equipment that changes success, pay, or another outcome. Only one copy of each such item may be owned.
Seed Industries — NPC supplier and surplus buyer with fixed prices. It is a fallback when a production chain is missing one material, not the rotating player market.
Production Order — One of three rotating daily Seed Industries contracts. Each is completed once per citizen per Avesta day and pays less than buying all inputs.
Determination — Failure protection. Matching failures add +4 percentage points to the next aptitude attempt, up to +12%; success resets it.
Activity unlock — Equipment can open stronger command options: Water Filter Hydroponics, Siro Sampler Field Analysis, Sensor Survey, Power Cell Spaceport Expedite, Market Analyzer Analysis, and Recreation Set social recovery.
Automatic-event meter — Counts real game actions and unique command users before randomly starting an event.
Daily Variety — Optional once-per-Avesta-day reward for successful work in three different aptitudes. It has no streak.
Society Directive — Shared daily work priority shown in the Daily Bulletin and /guide.
Gear familiarity — Use milestones that reduce gear wear chance without changing its success bonus.
Relationship Memory — Persistent count and latest shared activity between two citizens.
Event Aftermath — Non-stacking 60-minute modifier created by a finished event.
Result style — Compact keeps routine cards short; Detailed adds every modifier and final success chance.
Discoverable lore — Rare unique journal entries found during successful skilled work.""",
}

def discord_seed_help(topic="overview",name="Citizen"):
    topic=(topic or "overview").lower()
    greeting=f"📖 {clean(name)} — New Eridian Handbook\n\n"
    if topic in SEED_HELP_TOPICS:
        extra="\n\nSUPPLIES\n/catalog Category lists every item through numbered Pages; select Item for exact uses and ingredients. /gather collects natural resources. /make has matching categories and recipe Pages. Production Tree previews without spending. /use lists owned items with their costs and effects; durable items are kept. /eat lists owned edible foods." if topic in {'property','production','terms'} else ''
        return greeting+SEED_HELP_TOPICS[topic]+extra
    return (greeting+"🌱 Choose a /seed topic for complete explanations:\n\n"
            "🧭 Start Here — first steps and /guide\n👤 Character — stats, jobs, XP, linking\n"
            "🏠 Property — home, business, crafting\n🌿 Life Systems — needs, recovery, social actions\n"
            "🏭 Production — mining, industry, research\n🛰️ Operations — logistics, frontier, commerce\n"
            "🏙️ Society — tiers and events\n🍲 Other — eat and sleep\n🛡️ Moderator — event controls\n"
            "📖 Terms — definitions for SC, XP, Contribution, aptitudes, tiers, and event roles\n\n"
            "Not sure what to do? Use /guide. Standard work/eat/sleep use 5 seconds, social/recovery use 20–60 seconds, and /make has no cooldown.")

def twitch_pages(content, page, command):
    """Page by UTF-8 bytes to fit StreamElements' 400-byte response limit."""
    chunks=[];current=""
    for word in content.split():
        candidate=(current+" "+word).strip()
        if len(candidate.encode())>265:
            if current:chunks.append(current)
            current=word
        else:current=candidate
    if current:chunks.append(current)
    chunks=chunks or ["No entries."]
    try:index=max(1,min(len(chunks),int(page or "1")))
    except ValueError:index=1
    suffix=f" | Next: {command} {index+1}" if index<len(chunks) else ""
    return out(f"[{index}/{len(chunks)}] {chunks[index-1]}{suffix}")

@app.get("/api/v1/seed")
def twitch_seed(topic:str="overview",page:str="1"):
    topic=(topic or "overview").lower().strip()
    if topic not in SEED_HELP_TOPICS:
        return out("New Eridian: !start then !job then !guide. Handbook: !seed start, character, property, life, production, operations, society, other, moderator, terms. Example: !seed property 2. Work/eat/sleep: 5s; social/recovery: 20–60s; !make: none.")
    from .twitch_help import TOPICS
    content=TOPICS[topic]
    return twitch_pages(content,page,f"!seed {topic}")

@app.get("/api/v1/admin/modlog")
def twitch_modlog(channel:str,level:int=0,key:str="",page:str="1"):
    if not ADMIN_KEY or ADMIN_KEY=="change-me" or key!=ADMIN_KEY or level<500:
        return out("⛔ Moderator access and a configured game-admin key required.")
    with SessionLocal() as db:
        rows=db.execute(select(ModeratorAudit).where(ModeratorAudit.channel_id==channel).order_by(ModeratorAudit.created_at.desc()).limit(10)).scalars().all()
        content=" | ".join(f"{r.action}: {r.detail} ({r.moderator})" for r in rows) or "No moderator actions recorded."
        return twitch_pages(content,page,"!modlog")

DISCORD_PUBLIC_COMMANDS = {
    "society", "event", "eventstart", "eventstop", "holiday",
    "farm",
    "mine", "rare",
    "research", "scan",
    "repair",
    "cargo", "delivery", "spaceport",
    "explore", "market",
    "eat", "sleep", "social", "walk", "relax", "games", "hobby",
    "district", "shift", "meal", "use",
}

DISCORD_PRIVATE_COMMANDS = {
    "seed", "guide", "start", "me", "progress", "inventory", "job",
    "home", "business", "make", "seedindustries", "link", "specialize", "modlog",
    "world", "linklookup", "ducks", "training", "catalog", "gather"
}

def discord_message_status(content):
    lower=content.lower()
    if content.startswith(("❌","⛔","⚠️","🔒","🛑")) or any(term in lower for term in
        ("+0 rewards", "empty-handed", "cannot ", "still needed:", "still needs ", "need ore first", "no cargo ready", "you only have", "gear not found")):
        return "failure"
    if content.startswith(("⏱️","⏳")) or re.search(r"is ready in \d+s",lower):return "cooldown"
    if content.startswith("✅") or any(term in lower for term in
        ("task complete", "crafting complete", " completes ", " upgraded to ", " sold ", " bought ")):
        return "success"
    return "info"

def discord_message_category(command):
    groups={
        "handbook":{"seed"},"guide":{"guide"},"character":{"start","me","progress","inventory","job","specialize","link"},
        "life":{"social","relax","walk","games","hobby","world","district","shift","meal","ducks","use"},"business":{"business","seedindustries","market"},
        "society":{"society"},"event":{"event","eventstart","eventstop"},"moderator":{"modlog","linklookup"},
        "action":set(ACTION_SKILLS)|{"farm","fabricate","eat","sleep"},
    }
    return next((group for group,names in groups.items() if command in names),"default")
def _discord_clean_piece(value,limit=1024):
    text=str(value or "").strip()
    if len(text)<=limit:return text
    return text[:max(0,limit-1)].rstrip()+"…"

def _discord_nonempty_lines(content):
    return [x.strip() for x in str(content or "").replace("\r","").split("\n") if x.strip()]

def _discord_split_result(content):
    """Split older combined action strings on known New Eridian v2 system markers."""
    text=str(content or "").replace("\r","").strip()
    if not text:return []
    markers=[
        " Trade Crate:", " Fleet bond:", " 🦆 Fleet bond:",
        " 📖 ", " 🏗️ ", " 🎯 ", " 🔎 Encounter:",
        " ☣️ Siro exposure", " 🧳 ", " 📓 ",
        " 🧬 Active life modifiers", " 🌅 ", " ☀️ ", " 🌇 ", " 🌙 ",
        " 🩹 ", " ✅ ", " 🎓 ", " 🏆 ", " 🌈 ", " 📣 ", " 🔔 ", " 📜 ", " 🛠️ "
    ]
    text=text.replace(" | ","\n")
    for marker in markers:
        text=text.replace(marker,"\n"+marker.strip())
    text=re.sub(r"\s*(🔎\s*Encounter:|🧳\s*Collected:)",r"\n\1",text)
    return [x.strip() for x in text.split("\n") if x.strip()]

def _discord_embed_color(status):
    if status=="failure":return 0xED4245
    if status=="cooldown":return 0xFEE75C
    if status=="success":return 0x57F287
    if status=="action":return 0xFEE75C
    if status=="social":return 0xEB459E
    if status=="detail":return 0x99AAB5
    return 0x3498DB

def _discord_embed(title,description="",status="info"):
    e={
        "title":_discord_clean_piece(title,256),
        "color":_discord_embed_color(status),
        "fields":[],
        "footer":{"text":"New Eridian v2 • May Rocky's wisdom guide you."},
    }
    if description:
        e["description"]=_discord_clean_piece(description,1800)
    return e

def _discord_add_field(embed,name,lines,inline=False):
    if isinstance(lines,str):lines=[lines]
    clean=[]
    for line in lines or []:
        line=str(line or "").strip()
        if not line:continue
        if line.startswith("•"):line=line[1:].strip()
        if line not in clean:clean.append(line)
    if not clean:return
    # Split fields at line boundaries so instructions are not cut at 1024 chars.
    chunks=[];current=""
    for line in clean:
        line="• "+line
        while len(line)>1000:
            if current:chunks.append(current);current=""
            split=line.rfind(" ",0,1000)
            if split<1:split=1000
            chunks.append(line[:split]);line=line[split:].lstrip()
        if current and len(current)+1+len(line)>1000:
            chunks.append(current);current=""
        current=(current+"\n"+line).strip()
    if current:chunks.append(current)
    for i,value in enumerate(chunks):
        embed["fields"].append({"name":_discord_clean_piece(name+(" (continued)" if i else ""),256),
                                "value":value,"inline":False})


def _discord_action_name(command):
    names={
        "fabricate":"FABRICATION SHIFT",
        "farm":"FARMING SHIFT","harvest":"HARVEST","forage":"FORAGING",
        "water":"WATER TREATMENT","scan":"PROCESSING SCAN",
        "mine":"MINING SHIFT","rare":"RARE MATERIAL SEARCH","scavenge":"SCAVENGE RUN",
        "craft":"CRAFTING SHIFT","machine":"MACHINE OPERATION","repair":"REPAIR",
        "project":"PROJECT WORK","work":"WORK SHIFT","research":"RESEARCH",
        "cargo":"CARGO PREP","delivery":"DELIVERY","spaceport":"SPACEPORT SHIFT",
        "explore":"EXPEDITION","survey":"SURVEY","market":"MARKET SHIFT",
        "businesswork":"BUSINESS SHIFT","business":"BUSINESS SHIFT",
        "businesscontract":"BUSINESS CONTRACT","businessinvest":"BUSINESS INVESTMENT",
        "eat":"MEAL","sleep":"REST CYCLE","walk":"WALK","games":"GAMES","relax":"RELAX",
        "hobby":"HOBBY","hi":"GREETING","hangout":"HANGOUT","duo":"DUO ACTIVITY",
        "meal":"COMMUNITY MEAL","mentor":"MENTORING","sell":"MARKET SALE",
        "gearrepair":"GEAR REPAIR","use":"ITEM USED","training":"SKILL TRAINING",
    }
    return names.get(command,(command or "NEW ERIDIAN").replace("_"," ").upper())

def _discord_command_title(command):
    titles={
        "training":"🌱 SKILL TRAINING","holiday":"🎉 HOLIDAY CALENDAR",
        "seed":"📘 NEW ERIDIAN v2 HANDBOOK","guide":"🧭 GUIDE","start":"🌱 CITIZEN READY",
        "me":"👤 CITIZEN PROFILE","skills":"🧬 APTITUDES","inventory":"🎒 INVENTORY",
        "job":"🧰 PROFESSION","contracts":"📋 DAILY CONTRACT","achievements":"🏆 ACHIEVEMENTS",
        "home":"🏠 HABITAT","business":"🏢 BUSINESS","make":"🛠️ FABRICATOR","seedindustries":"🏭 SEED INDUSTRIES",
        "life":"❤️ LIFE STATUS","relationships":"🤝 RELATIONSHIPS","world":"🌎 AVESTA WORLD",
        "rumor":"🗣️ NEW ERIDIAN RUMOR","collection":"🧳 COLLECTION","traits":"🧬 TRAITS",
        "district":"🏘️ DISTRICT","shift":"🕒 SHIFT","conditions":"☣️ CONDITIONS",
        "goal":"🎯 DAILY GOAL","projectstatus":"🏗️ SOCIETY PROJECT","bulletin":"📌 BULLETIN",
        "journal":"📓 JOURNAL","tutorial":"🎓 FIRST DAYS","story":"📖 WEEKLY STORY",
        "titles":"🏷️ TITLES","marketboard":"💰 MARKET DEMAND","ducks":"🦆 DELIVERY FLEET",
        "gear":"⚙️ EQUIPMENT","cooldowns":"⏱️ COOLDOWNS","bonuses":"✨ BONUSES",
        "specialize":"⭐ SPECIALIZATION","status":"🏛️ NEW ERIDIAN","progress":"📈 SOCIETY PROGRESS",
        "society":"🏛️ NEW ERIDIAN SOCIETY","event":"🚨 SOCIETY EVENT",
        "link":"🔗 ACCOUNT LINK","linklookup":"🔐 LINKED ACCOUNT LOOKUP","modlog":"🛡️ MODERATOR LOG",
    }
    return titles.get(command,"🌱 NEW ERIDIAN v2")

def _discord_progress_embed(content,status):
    lines=_discord_nonempty_lines(content)
    embed=_discord_embed("📈 SOCIETY PROGRESS","🏗️ New Eridian — Tier Progress",status)
    rewards=[];progress=[];notes=[]
    for line in lines:
        low=line.lower()
        if "new eridian — tier progress" in low:continue
        if "success bonus:" in low:
            rewards.append(line)
        elif line.startswith("• ") and any(k in line for k in ("Food:","Materials:","Development:","Knowledge:","Treasury:","Reputation:")):
            progress.append(line)
        elif line.startswith("Current tier:") or line.startswith("Next tier:") or line.startswith("Requirement:"):
            progress.append(line)
        elif "most useful target" in low or "bottleneck:" in low or line.startswith("Use /guide"):
            notes.append(line)
        elif "maximum society tier" in low:
            progress.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟨 REWARDS",rewards)
    _discord_add_field(embed,"🟦 PROGRESS",progress)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_world_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Avesta world state"
    embed=_discord_embed("🌎 AVESTA WORLD",first,status)
    condition=[];society=[];story=[];notes=[]
    for line in lines[1:]:
        low=line.lower()
        if line.startswith("World condition:"):
            condition.append(line.replace("World condition:","").strip())
        elif line.startswith("Society project:") or line.startswith("Society pressure:"):
            society.append(line)
        elif line.startswith("Weekly story:"):
            story.append(line.replace("Weekly story:","").strip())
        elif line.startswith("Rumor:"):
            notes.append(line)
        elif "day phases change" in low or "night outdoor" in low:
            notes.append(line)
        elif condition and len(condition)<2:
            condition.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟦 CONDITION",condition)
    _discord_add_field(embed,"🟦 SOCIETY",society)
    _discord_add_field(embed,"🟪 STORY",story)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_life_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Citizen life status"
    embed=_discord_embed("❤️ LIFE STATUS",first,status)
    needs=[];effects=[];notes=[];mode=""
    for line in lines[1:]:
        if line.upper()=="ACTIVE EFFECTS":
            mode="effects";continue
        if any(line.startswith(x) for x in ("⚡","🍲","🤝","🏠","✨")) and "/100" in line:
            needs.append(line)
        elif line.startswith("Use /"):
            notes.append(line)
        elif mode=="effects":
            effects.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟦 NEEDS",needs)
    _discord_add_field(embed,"⚪ ACTIVE EFFECTS",effects or ["No active life penalties."])
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_event_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Live event"
    if "No active live event" in first:
        return _discord_embed("🚨 LIVE EVENT","No active live event.",status)
    embed=_discord_embed("🚨 LIVE EVENT",first,status)
    event_status=[];help_lines=[];risk=[];notes=[];mode=""
    for line in lines[1:]:
        upper=line.upper()
        if upper=="📊 STATUS":mode="status";continue
        if upper=="🎯 HOW TO HELP":mode="help";continue
        if line.startswith("⚠️") or line.startswith("🏅"):
            risk.append(line);continue
        if line.startswith("Use /guide"):
            notes.append(line);continue
        if "needs your response" in line.lower():
            notes.append(line);continue
        if mode=="status":event_status.append(line)
        elif mode=="help":help_lines.append(line)
        else:notes.append(line)
    _discord_add_field(embed,"🟦 STATUS",event_status)
    _discord_add_field(embed,"🟨 HOW TO HELP",help_lines)
    _discord_add_field(embed,"🟥 RISK & LEADERS",risk)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_status_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "New Eridian society status"
    embed=_discord_embed("🏛️ NEW ERIDIAN",first,status)
    overview=[];resources=[];notes=[];mode=""
    for line in lines[1:]:
        if line=="📦 CORE RESOURCES":mode="resources";continue
        if mode=="resources":
            # Core resource lines contain two stats separated by a middle dot.
            resources.extend([x.strip() for x in line.split("·") if x.strip()])
        elif line.startswith("Use /progress"):
            notes.append(line)
        elif "your society currently needs" in line.lower():
            notes.append(line)
        else:
            overview.append(line)
    _discord_add_field(embed,"🟦 OVERVIEW",overview)
    _discord_add_field(embed,"🟨 RESOURCES",resources)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_action_embed(content,command,status):
    pieces=_discord_split_result(content)
    title_prefix="🟩" if status=="success" else "🟥" if status=="failure" else "🟨" if status=="cooldown" else "🟦"
    title=title_prefix+" "+_discord_action_name(command)
    embed=_discord_embed(title,"",status)

    rewards=[];society=[];fleet=[];progress=[];discovery=[];world=[];mods=[];notes=[];risk=[];guidance=[];needs=[]
    modifier_mode=False;section_mode=""
    summary=""
    has_practice=any(x.startswith(("Aptitude practice:","Competency practice:")) for x in pieces)
    if command=="training":
        match=re.search(r" completes ([^\n]+?)\.\s*\+",content)
        if match:embed["title"]=title_prefix+" "+match.group(1)+(" • Complete" if status=="success" else "")

    for i,piece in enumerate(pieces):
        low=piece.lower()
        upper=piece.strip("• ").upper()

        # These are routing markers from the plain-text action response. They
        # should organize the embed, never appear as unexplained Notes.
        if upper in {"✅ TASK COMPLETE","❌ TASK FAILED","RESULT"}:
            continue
        if upper in {"WHY THIS RESULT","🧬 ACTIVE LIFE MODIFIERS"}:
            modifier_mode=True;section_mode="mods";continue
        if upper=="WHY":section_mode="risk";continue
        if upper=="HOW TO IMPROVE":section_mode="guidance";continue
        if upper=="NEXT":section_mode="guidance";continue

        if piece.startswith("Needs:"):needs.append(piece[6:].strip());continue
        if piece.startswith("Resources:"):
            for change in piece[10:].split(","):
                match=re.fullmatch(r"\s*(sc|contribution)\s*([+-]\d+)\s*",change,re.I)
                if match:
                    label="SC" if match[1].lower()=="sc" else "Contribution"
                    value=f"{match[2]} {label}"
                    if value not in rewards:rewards.append(value)
                else:rewards.append(change.strip())
            continue
        if piece.startswith("Settlement:"):
            if not society:society.append(piece[11:].strip())
            continue
        if piece.startswith(("Aptitude practice:","Competency practice:")):
            progress.append(piece.split(":",1)[1].strip());continue
        if piece.startswith("shared ") or piece.startswith("society "):
            society.extend(x.strip().capitalize() for x in piece.split(";") if x.strip());continue
        if "LEVEL UP" in piece:
            progress.append(piece);continue
        if section_mode=="risk":
            risk.append(piece);continue
        if section_mode=="guidance":
            guidance.append(piece);continue

        if "active life modifiers" in low:
            modifier_mode=True
            continue
        if modifier_mode:
            if piece.startswith("•") or "success chance" in low or re.search(r"[+-]\d+%",piece):
                mods.append(piece)
                continue
            modifier_mode=False

        # Break the main success sentence away from inline mechanical rewards.
        if not summary:
            # Example: "🦆 Name completes delivery with Prisma. +1 Logistics XP"
            m=re.match(r"^(.*?\.)\s*(\+\d+(?:\.\d+)? .+ XP(?: and branch XP)?)?$",piece)
            if m:
                summary=m.group(1).strip()
                if m.group(2):
                    xp=m.group(2).strip()
                    if not has_practice:progress.append(xp.replace(" and branch XP",""))
                    if "and branch XP" in xp:
                        amount=xp.split()[0]
                        progress.append(f"{amount} branch XP")
                continue
            summary=piece
            continue

        # Split society line from flavor that may trail after the period.
        if "new eridian gains" in low:
            m=re.match(r"^(.*?New Eridian gains [^.]+\.)(.*)$",piece,re.I)
            if m:
                society.append(m.group(1).strip())
                tail=m.group(2).strip()
                if tail:
                    if any(d.lower() in tail.lower() for d in ("hueburt","colora","prisma","pastelle","asimov")):
                        fleet.append(tail)
                    else:notes.append(tail)
            else:society.append(piece)
            continue

        if "fleet bond:" in low or any(d.lower() in low for d in ("hueburt","colora","prisma","pastelle","asimov")):
            fleet.append(piece);continue
        if piece.startswith("📖") or "story progress" in low or "the signal below" in low:
            progress.append(piece.lstrip("📖 ").strip());continue
        if piece.startswith(("🌈","📣","🔔","🛠️")):
            progress.append(piece.lstrip("🌈📣🔔🛠️ ").strip());continue
        if piece.startswith("📜") or "lore discovered" in low:
            discovery.append(piece.lstrip("📜 ").strip());continue
        if piece.startswith("🏗️") or piece.startswith("🎯") or "daily goal" in low or "project" in low and ("progress" in low or "complete" in low):
            progress.append(piece.lstrip("🏗️🎯 ").strip());continue
        if "encounter:" in low or piece.startswith("🔎") or "collected:" in low or "added to collection" in low or piece.startswith("🧳"):
            discovery.append(piece.replace("🔎 Encounter:","").lstrip("🔎🧳 ").strip());continue
        if piece.startswith(("🌅","☀️","🌇","🌙")) or any(x in low for x in ("dust winds","siro drift","good growing weather","busy spaceport","water watch","sensor noise","quiet cycle","clear avesta skies")):
            world.append(piece);continue
        if piece.startswith("☣️") or piece.startswith("🩹") or "siro exposure" in low:
            world.append(piece);continue
        if "final chance" in low or "final success chance" in low or re.search(r"[+-]\d+%",piece):
            mods.append(piece);continue
        if "trade crate:" in low or piece.startswith("+") or any(k in piece for k in (" XP"," SC","Contribution")):
            rewards.append(piece);continue
        if "+0 rewards" in low:
            rewards.append("No rewards earned.");continue
        notes.append(piece)

    embed["description"]=_discord_clean_piece(summary or "Action processed.",1400)
    _discord_add_field(embed,"🟥 WHY IT FAILED",risk)
    _discord_add_field(embed,"🟨 HOW TO IMPROVE",guidance)
    _discord_add_field(embed,"🟨 REWARDS",rewards,inline=True)
    _discord_add_field(embed,"🟦 NEED CHANGES",needs)
    _discord_add_field(embed,"🟦 SOCIETY",society,inline=True)
    _discord_add_field(embed,"🟪 FLEET",fleet)
    _discord_add_field(embed,"🟦 PROGRESS",progress)
    _discord_add_field(embed,"🟪 DISCOVERY",discovery)
    _discord_add_field(embed,"🟦 WORLD",world,inline=True)
    _discord_add_field(embed,"🟦 SUCCESS CHANCE",mods)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_generic_embed(content,command,status):
    lines=_discord_nonempty_lines(content)
    title=_discord_command_title(command)
    if not lines:
        return _discord_embed(title,"No information available.",status)

    # Keep the first useful line prominent, then compact the rest.
    first=lines[0]
    embed=_discord_embed(title,first,status)
    rest=lines[1:]

    # Preserve simple all-caps/label sections when the endpoint already provides them.
    sections=[];current_name="📌 Details";current=[]
    for line in rest:
        if ((line.isupper() and re.match(r"^[A-Z][A-Z &/—-]*$",line)) or line.endswith(":")) and len(line)<=48 and not re.match(r"^[+−\-]?\d",line):
            if current:sections.append((current_name,current))
            current_name=line.strip(":")
            current=[]
        else:
            current.append(line)
    if current:sections.append((current_name,current))

    if not sections and rest:
        sections=[("📌 Details",rest)]

    for name,vals in sections:
        if not name.startswith(("📌","💰","📊","✨","🏛️","🌎","📖","🏗️","🎯","🦆","🧬","☣️","🧳","🤝","⚙️","🎒","🏆","📋")):
            name="📌 "+name.title()
        _discord_add_field(embed,name,vals)

    return embed

def _discord_pretty_embed(content,command,status):
    if content.startswith(("🍽️ FOOD MENU","🎒 ITEM MENU")):return _discord_generic_embed(content,command,"info")
    action_commands=set(ACTION_SKILLS)|{
        "farm","fabricate",
        "eat","sleep","businesswork","businesscontract","businessinvest",
        "walk","games","relax","hobby","hi","hangout","duo","meal","mentor",
        "sell","gearrepair","use"
    }

    if content.startswith(("✅ TASK COMPLETE","❌ TASK FAILED")):
        return _discord_action_embed(content,command,status)
    if command=="progress":return _discord_progress_embed(content,status)
    if command=="world":return _discord_world_embed(content,status)
    if command=="life":return _discord_life_embed(content,status)
    if command=="event":return _discord_event_embed(content,status)
    if command=="status":return _discord_status_embed(content,status)
    if command in action_commands and not (command in {"business","market"} and status=="info"):
        return _discord_action_embed(content,command,status)
    return _discord_generic_embed(content,command,status)

def _discord_split_personal_details(content: str):
    """
    For public Discord action commands, keep shared game results public while
    moving the player's personal success-calculation details to an ephemeral
    follow-up message.
    """
    text=str(content or "")
    marker="🧬 Active life modifiers"
    if marker not in text:
        return text,None

    public,private=text.split(marker,1)
    public=public.rstrip()
    private=private.strip()

    if not private:
        return text,None

    # Normalize the private section into short readable lines.
    lines=[]
    for raw in private.replace("\r","").split("\n"):
        line=raw.strip()
        if not line:continue
        if line.startswith("•"):
            line=line[1:].strip()
        lines.append(line)

    return public,"\n".join(lines)


def _discord_private_details_embed(private_text: str, command: str):
    lines=[x.strip().lstrip("•").strip() for x in str(private_text or "").splitlines() if x.strip()]
    chance=[]
    modifiers=[]
    for line in lines:
        if line.lower().startswith("final success chance:"):
            chance.append(line)
        else:
            modifiers.append(line)

    embed=_discord_embed(
        "◻️ YOUR ACTION DETAILS",
        "Personal modifiers used for this action.",
        "detail"
    )
    _discord_add_field(embed,"🧬 Modifiers",modifiers or ["No active modifiers."])
    _discord_add_field(embed,"🎯 Result Calculation",chance or ["No success roll details available."])
    embed["footer"]={"text":"Only you can see this • New Eridian v2"}
    return embed


def _discord_send_ephemeral_followup(application_id: str, interaction_token: str, private_text: str, command: str):
    """Send an ephemeral interaction follow-up using Discord's webhook token."""
    if not application_id or not interaction_token or not private_text:
        return
    url=f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
    payload={
        "embeds":[_discord_private_details_embed(private_text,command)],
        "flags":64,
        "allowed_mentions":{"parse":[]},
    }
    try:
        request=urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type":"application/json",
                "User-Agent":"New-Eridian-v2/6.3.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(request,timeout=8) as response:
            response.read()
    except Exception as exc:
        # The public command must still succeed even if Discord rejects a
        # private follow-up. Railway logs preserve the reason for debugging.
        print("Discord ephemeral follow-up error:",command,repr(exc))



# The published flat option schema is also used to validate requests.
from .command_catalog import commands as DISCORD_COMMAND_CATALOG
DISCORD_OPTION_SCHEMA = {row["name"]: row.get("options", []) for row in DISCORD_COMMAND_CATALOG}

def discord_command_copy(content):
    """Render registered command choices as readable menu instructions.

    Only command spans are changed; citizen names, item IDs and prose elsewhere
    retain their original spelling. Running this twice is harmless.
    """
    aliases = dict(DISCORD_ACTION_ROUTES)
    aliases.update({"skills":"/progress section:skills", "contracts":"/progress section:daily",
        "achievements":"/progress section:achievements", "collection":"/progress section:collection",
        "life":"/me section:life", "bonuses":"/me section:bonuses", "cooldowns":"/me section:cooldowns",
        "traits":"/me section:traits", "relationships":"/me section:relationships",
        "journal":"/me section:journal", "tutorial":"/me section:tutorial",
        "titles":"/me section:titles", "display":"/me section:display",
        "homeup":"/home action:upgrade", "homeupgrade":"/home action:upgrade",
        "businessstart":"/business action:start", "businesswork":"/business action:work",
        "gear":"/inventory section:gear", "recipes":"/make",
        "marketboard":"/market action:view", "projectstatus":"/world section:project",
        "eventhistory":"/event section:history", "leaderboard":"/society section:leaderboard",
        "conditions":"/world section:conditions", "story":"/world section:story",
        "bulletin":"/world section:bulletin", "rumor":"/world section:rumor"})
    text=str(content or "")
    # Match whole commands only; never substrings, URLs, fractions or backticks.
    pattern=r"(?<![\w`:/])/([a-z][a-z0-9_]*)(?![\w`])"
    text=re.sub(pattern,lambda m:aliases.get(m[1],m[0]) if m[1] not in DISCORD_OPTION_SCHEMA else m[0],text)
    choice_aliases={
        ("home","action","view"):"view",("home","action","upgrade"):"upgrade",
        ("business","action","view"):"view",("business","action","start"):"start",
        ("seedindustries","action","orders"):"orders",("seedindustries","action","fulfill"):"fulfill",
        ("explore","operation","advanced survey"):"survey",("progress","section","skills"):"skills",
    }
    matches=list(re.finditer(pattern,text))
    for match in reversed(matches):
        command=match[1]
        if command not in DISCORD_OPTION_SCHEMA:continue
        # Option values are confined to this command's sentence/line, before the next command.
        end=next((m.start() for m in matches if m.start()>match.start()),len(text))
        span=text[match.end():end]
        fields={row["name"]:row for row in DISCORD_OPTION_SCHEMA[command]}
        for field,row in fields.items():
            labels={str(c["value"]):c["name"] for c in row.get("choices",[])}
            candidates={key:label for key,label in labels.items()}
            candidates.update({label:label for label in labels.values()})
            for (cmd,opt,alias),value in choice_aliases.items():
                if cmd==command and opt==field and value in labels:candidates[alias]=labels[value]
            if field=="recipe":
                candidates.update({key:craft_item_name(key) for key in (*PART_RECIPES,*RECIPES,*QUALITY_RECIPES)})
                candidates.update({label:label for label in list(candidates.values())})
            # Longest label first, so e.g. Skills & Level Unlocks is not partially consumed.
            known="|".join(re.escape(k) for k in sorted(candidates,key=len,reverse=True))
            value_pattern=("(?:"+known+r")(?![\w])|" if known else "")+r"<[^>\n]+>|[A-Za-z0-9_]+"
            option_pattern=r"\b"+re.escape(field)+r":("+value_pattern+r")"
            def render(m):
                value=m[1]
                label=next((v for k,v in candidates.items() if k.casefold()==value.casefold()),None)
                if label is None:
                    label=value if value.startswith("<") else value.replace("_"," ").title()
                return field.replace("_"," ").title()+": **"+label+"**"
            span=re.sub(option_pattern,render,span,flags=re.I)
        # The arrow separates the command to type from the dropdowns to choose.
        if re.match(r"\s*[A-Z][A-Za-z ]*: \*\*",span):span=" → "+span.lstrip()
        text=text[:match.start()]+"`/"+command+"`"+span+text[end:]
    return text


def _discord_json_message(content: str, ephemeral: bool = False, message_type: str = ""):
    content=discord_command_copy(content)
    command=(message_type or "").lower()
    status=discord_message_status(content)
    category=discord_message_category(command)
    keys=[f"{command}_{status}",command,status,category,"default"]
    custom=next((DISCORD_EMOJI_MAP[key] for key in keys if key in DISCORD_EMOJI_MAP),"")

    # IMPORTANT: Discord renders this as a true embed because the interaction
    # response uses the "embeds" array instead of plain "content".
    embed=_discord_pretty_embed(content,command,status)

    # Colored badges remain visible even when a mobile client hides embed borders.
    # Scope social color to the actual view, not a mention of "story" in a guide.
    tone=status
    menu=content.startswith(("🍽️ FOOD MENU","🎒 ITEM MENU"))
    first_line=content.splitlines()[0].lower() if content else ""
    if status=="info":
        if menu or command in {"make","guide"}:
            tone="action"
        elif command in {"social","hobby","ducks"} or any(word in first_line for word in ("weekly story","relationships","journal","lore")):
            tone="social"
    embed["color"]=_discord_embed_color(tone)
    badge={"success":"🟩","failure":"🟥","cooldown":"🟨","action":"🟨","social":"🟪","detail":"◻️"}.get(tone,"🟦")
    embed["title"]=_discord_clean_piece(badge+" "+re.sub(r"^[🟩🟥🟨🟦🟪]\s*","",embed.get("title","New Eridian v2")),256)
    for field in embed.get("fields",[]):
        field["inline"]=False
        name=field["name"]
        lower=name.lower()
        if any(word in lower for word in ("failed","danger","blocked","warning","risk")):mark="🟥"
        elif any(word in lower for word in ("reward","next","improve","action","recipe","supplies","cost")):mark="🟨"
        elif any(word in lower for word in ("story","lore","social","fleet","discovery","relationship","journal")):mark="🟪"
        elif any(word in lower for word in ("progress","growth","level","achievement")):mark="🟩"
        elif any(word in lower for word in ("detail","note","modifier")):mark="◻️"
        else:mark="🟦"
        name=re.sub(r"^[^\w]+", "", name)
        field["name"]=_discord_clean_piece(mark+" "+(name.capitalize() if name.isupper() else name),256)

    if custom:
        existing=embed.get("description","")
        embed["description"]=_discord_clean_piece((custom+" "+existing).strip(),1800)

    # Never let readable labels push an otherwise valid message over embed limits.
    # Reserve room for an explicit notice rather than silently dropping text.
    budget=5700-len(embed.get("title",""))-len(embed.get("description",""))-len(embed.get("footer",{}).get("text",""))
    kept=[];omitted=False
    for field in embed.get("fields",[]):
        size=len(field["name"])+len(field["value"])
        if len(kept)>=24 or size>budget:
            omitted=True;break
        kept.append(field);budget-=size
    if omitted:
        kept.append({"name":"More detail", "value":"This view is long. Choose a specific section, crafting category, or handbook topic to see its full details.", "inline":False})
    embed["fields"]=kept
    data={"embeds":[embed]}
    if ephemeral:
        data["flags"]=64
    return {"type":4,"data":data}

DISCORD_PERSONAL_DETAIL_COMMANDS=set(ACTION_SKILLS)|{
    "farm","fabricate",
    "businesswork","businesscontract","businessinvest",
    "duo","meal","mentor","sell","gearrepair","use"
}

def _discord_user(payload: dict):
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    uid = str(user.get("id") or "")
    name = (
        member.get("nick")
        or user.get("global_name")
        or user.get("username")
        or "Citizen"
    )
    return uid, name

DISCORD_HUB_SELECTORS={"seed":"topic","guide":"goal","me":"section","progress":"section",
 "inventory":"section","home":"action","business":"action","make":"category",
 "seedindustries":"action","world":"section","society":"section","event":"section",
 "social":"action","farm":"action","research":"operation","repair":"target",
 "spaceport":"operation","explore":"operation","market":"action"}

def _discord_flat_payload(payload):
    data=dict(payload.get("data") or {})
    options=data.get("options") or []
    branch=next((opt for opt in options if opt.get("type")==1),None)
    if branch:
        selector=DISCORD_HUB_SELECTORS.get(data.get("name"))
        if selector:
            value=branch.get("name","")
            if data.get("name")=="make" and value in {"browse","craft"}:value=""
            data["options"]=[{"name":selector,"value":value}]+list(branch.get("options") or [])
    return {**payload,"data":data}

def _discord_options(payload: dict):
    payload=_discord_flat_payload(payload)
    data = payload.get("data") or {}
    result = {}
    for opt in data.get("options") or []:
        result[opt.get("name")] = opt.get("value")
    return result

def _discord_autocomplete_choices(rows,query=""):
    q=str(query or "").lower().strip()
    choices=[]
    seen=set()
    for label,value in rows:
        label=str(label or "").strip()
        value=str(value or "").strip()
        if not label or not value or value in seen:continue
        if q and q not in label.lower() and q not in value.lower():continue
        choices.append({"name":label[:100],"value":value[:100]})
        seen.add(value)
        if len(choices)>=25:break
    return {"type":8,"data":{"choices":choices}}

def _discord_existing_player(payload):
    uid,name=_discord_user(payload)
    if not uid:return None,None,None
    with SessionLocal() as db:
        ident=db.execute(
            select(Identity).where(
                Identity.channel_id==DISCORD_WORLD_ID,
                Identity.provider=="discord",
                Identity.provider_uid==uid
            )
        ).scalar_one_or_none()
        canonical=ident.canonical_uid if ident else "discord:"+uid
        p=db.execute(
            select(Player).where(
                Player.channel_id==DISCORD_WORLD_ID,
                Player.twitch_uid==canonical
            )
        ).scalar_one_or_none()
        return uid,name,p

def _discord_player_autocomplete(payload,query=""):
    uid,_=_discord_user(payload)
    with SessionLocal() as db:
        identity=db.execute(select(Identity).where(Identity.channel_id==DISCORD_WORLD_ID,Identity.provider=='discord',Identity.provider_uid==uid)).scalar_one_or_none()
        own_uid=identity.canonical_uid if identity else 'discord:'+uid
        rows=db.execute(
            select(Player)
            .where(Player.channel_id==DISCORD_WORLD_ID)
            .order_by(Player.display_name)
        ).scalars().all()
        data=[]
        for p in rows:
            if uid and p.twitch_uid==own_uid:continue
            if (payload.get('data') or {}).get('name')=='social':
                duplicate=sum(other.display_name.casefold()==p.display_name.casefold() for other in rows)>1
                label=f"{p.display_name} · citizen #{p.id}" if duplicate else p.display_name
                data.append((label,f'citizen:{p.id}'))
            else:data.append((p.display_name,p.display_name))
        return _discord_autocomplete_choices(data,query)

def _discord_title_autocomplete(payload,query=""):
    _,_,p=_discord_existing_player(payload)
    if not p:return {"type":8,"data":{"choices":[]}}
    with SessionLocal() as db:
        rows=db.execute(
            select(PlayerTitle)
            .where(
                PlayerTitle.channel_id==DISCORD_WORLD_ID,
                PlayerTitle.canonical_uid==p.twitch_uid
            )
            .order_by(PlayerTitle.unlocked_at)
        ).scalars().all()
        data=[]
        for row in rows:
            label=TITLE_DEFS.get(row.title_key,row.title_key.replace("_"," ").title())
            if row.equipped:label="⭐ "+label
            data.append((label,row.title_key))
        return _discord_autocomplete_choices(data,query)

def _discord_gear_autocomplete(payload,query=""):
    _,_,p=_discord_existing_player(payload)
    if not p:return {"type":8,"data":{"choices":[]}}
    with SessionLocal() as db:
        rows=db.execute(
            select(QualityGear)
            .where(
                QualityGear.channel_id==DISCORD_WORLD_ID,
                QualityGear.canonical_uid==p.twitch_uid,
                QualityGear.qty>0
            )
            .order_by(QualityGear.item_name)
        ).scalars().all()
        data=[
            (f"{x.quality} {x.item_name} ×{x.qty} — repair {(100-x.condition+19)//20} Components (own {p.components})",f"gear_{x.id}")
            for x in rows if x.condition<100
        ]
        return _discord_autocomplete_choices(data,query)

def _discord_make_autocomplete(payload:dict):
    options=(payload.get("data") or {}).get("options") or []
    values={str(opt.get("name") or ""):opt.get("value") for opt in options}
    focused=next((opt for opt in options if opt.get("focused")),{})
    if focused.get("name")!="recipe":return {"type":8,"data":{"choices":[]}}
    category=normalize_craft_category(values.get("category"))
    query=str(focused.get("value") or "").lower().strip()

    if category.startswith('seed_'):
        rows=[]
    elif category in CRAFT_CATEGORIES:
        rows=craft_category_rows(category)
    else:
        rows=[]
        for craft_category in CRAFT_CATEGORIES:
            rows.extend(craft_category_rows(craft_category))

    data=[]
    with SessionLocal() as db:
        society_state=society(db,DISCORD_WORLD_ID);tier_index=society_tier_index(society_state)
        uid,_=_discord_user(payload)
        ident=db.execute(select(Identity).where(Identity.channel_id==DISCORD_WORLD_ID,Identity.provider=="discord",Identity.provider_uid==uid)).scalar_one_or_none() if uid else None
        canonical=ident.canonical_uid if ident else ("discord:"+uid if uid else "")
        current_player=db.execute(select(Player).where(Player.channel_id==DISCORD_WORLD_ID,Player.twitch_uid==canonical)).scalar_one_or_none() if canonical else None
        for key,item_name,cost,_,need in rows:
            lock=""
            if current_player and unique_bonus_owned(db,current_player,key):
                lock=" ✅ OWNED · LIMIT 1"
            elif need is not None and tier_index<need:
                lock=f" 🔒 {SOCIETY_TIERS[need][0]}"
            if current_player and crafting_progression.legacy_gate(sys.modules[__name__],db,current_player,key):lock+=' 🔒 WORKSHOP/TIER'
            data.append((f"{item_name} — "+("; ".join(f"{resource_name(k)} {material_amount(db,current_player,k)}/{v}" for k,v in cost.items()) if current_player else requirement_text(cost))+lock,key))
        # Recipe search spans both catalogs; source recipes appear first for named searches.
        source_rows=[]
        seed_stock=seed_content.stock(sys.modules[__name__],db,current_player)
        for key,r in seed_content.RECIPES.items():
            if category in CRAFT_CATEGORIES or len(source_rows)>=25:break
            if category.startswith('seed_') and seed_content.recipe_category(key)!=category[5:]:continue
            if query and query not in (r['name']+' '+r['source']).casefold():continue
            req=r['requirement'].get('Skill','SK_CRAFTING')
            stock='; '.join(f"{resource_name(k)} {seed_stock.get(k,0)}/{v}" for k,v in r['inputs'].items()) or 'no ingredients'
            source_rows.append((f"{seed_content.item_label(next(iter(r['outputs'])))} · T{crafting_progression.recipe_tier(key)} {seed_content.station(r)} — {stock} · {seed_content.skill_name(req)} Lv.{seed_content.required_level(r)}",key))
        data=(source_rows+data) if query else (data+source_rows)
    return _discord_autocomplete_choices(data,query)

def _discord_autocomplete(payload:dict):
    import sys
    payload=_discord_flat_payload(payload)
    data=payload.get("data") or {}
    command=str(data.get("name") or "").lower()
    options=data.get("options") or []
    focused=next((opt for opt in options if opt.get("focused")),{})
    option=str(focused.get("name") or "").lower()
    query=str(focused.get("value") or "")
    selected=_discord_options(payload)
    if command=='mine' and option=='ore':
        return _discord_autocomplete_choices([(seed_content.item_label(k),k) for k in task_queue.ores()],query)
    if command=='queue' and option=='task':
        return _discord_autocomplete_choices([(label,key) for key,label in task_queue.choices(sys.modules[__name__]).items()],query)
    if command=='social' and option=='player' and selected.get('action')=='group_games':return _discord_autocomplete_choices([])
    if command=='me' and option=='title' and selected.get('section') not in {None,'','titles'}:return _discord_autocomplete_choices([])
    if command=='repair' and option=='item' and selected.get('target')=='society':return _discord_autocomplete_choices([])

    if command=='workshop' and option=='station':
        return _discord_autocomplete_choices([(f"{v['name']} · Tier {v['tier']} · {v['cost']} SC once",k) for k,v in crafting_progression.STATIONS.items()],query)
    if command in {'catalog','gather'} and option in {'item','resource'}:
        import sys
        _,_,p=_discord_existing_player(payload)
        with SessionLocal() as db:
            return _discord_autocomplete_choices(seed_content.choices(sys.modules[__name__],db,p,gather_only=command=='gather',category=selected.get('category',''),owned=bool(selected.get('owned',False))),query)
    if command=='training' and option=='task':
        hub=selected.get('skill')
        _,_,p=_discord_existing_player(payload)
        rows=[]
        with SessionLocal() as db:
            for key,cfg in SEED_TASKS.items():
                if cfg['hub']!=hub:continue
                stock='; '.join(f"{resource_name(k)} {material_amount(db,p,k) if p else 0}/{v}" for k,v in cfg['cost'].items()) or 'no item needed'
                lock=f" · requires level {cfg['unlock']}" if not p or lvl(skill_xp(p,cfg['skill']))<cfg['unlock'] else ''
                rows.append((cfg['label']+' — '+stock+lock,key))
        return _discord_autocomplete_choices(rows,query)
    if command=="eat" and option=="food":
        _,_,p=_discord_existing_player(payload)
        if not p:return _discord_autocomplete_choices([])
        with SessionLocal() as db:
            foods=edible_inventory(db,p)
            rows=[(f"{row['name']} ×{row['qty']} — {row['effect']}",row['key']) for row in foods if row['qty']>0]
            if emergency_food_available(db,p,foods):rows.append(("Emergency Meal — free; restores Nutrition to 40","emergency"))
            return _discord_autocomplete_choices(rows,query)

    if command=="seedindustries" and option=="item":
        values=_discord_options(payload);mode=values.get("action","browse")
        with SessionLocal() as db:
            if mode=="fulfill":
                state=society(db,DISCORD_WORLD_ID);clock=world_clock(db,DISCORD_WORLD_ID)
                rows=[(data["name"],key) for key,data in available_production_orders(DISCORD_WORLD_ID,clock["day"],society_tier_index(state))]
            elif mode in {"buy","sell"}:
                rows=[(f"{market_item_label(key)} — {data[mode]} SC each",key) for key,data in SEED_INDUSTRIES.items() if data.get(mode,0)>0 and (values.get("category","all")=="all" or data.get("category","legacy")==values["category"])]
            else:rows=[]
        return _discord_autocomplete_choices(rows,query)

    if command=="use" and option=="item":
        _,_,p=_discord_existing_player(payload)
        if not p:return _discord_autocomplete_choices([])
        with SessionLocal() as db:
            owned=owned_life_items(db,p)
            import sys
            source=seed_content.choices(sys.modules[__name__],db,p,category=selected.get('category',''),owned=True,usable=True)
            legacy=[] if selected.get('category') else [(f"{QUALITY_RECIPES[key]['name']} ×{sum(row.qty for row in rows)} — consumes 1; best quality first",key) for key,rows in owned.items() if rows]+[(f'{resource_name(key)} ×{material_amount(db,p,key)} — consumes 1',key) for key in ('furniture','workwear','medicine') if material_amount(db,p,key)>0]
            return _discord_autocomplete_choices(source+legacy,query)

    if command=="make" and option=="recipe":
        return _discord_make_autocomplete(payload)

    if option=="player" and command=="social":
        return _discord_player_autocomplete(payload,query)

    if command=="linklookup" and option=="player":
        if not _discord_is_owner(payload):
            return {"type":8,"data":{"choices":[]}}
        return _discord_player_autocomplete(payload,query)

    if command in {"titles","me"} and option=="title":
        return _discord_title_autocomplete(payload,query)

    if command=="repair" and option=="item":
        return _discord_gear_autocomplete(payload,query)

    return {"type":8,"data":{"choices":[]}}

def _discord_allowed_channel(payload: dict):
    if not DISCORD_GAME_CHANNEL_ID:
        return True
    return str(payload.get("channel_id") or "") == str(DISCORD_GAME_CHANNEL_ID)

def _discord_is_moderator(payload:dict):
    member=payload.get("member") or {}
    try:permissions=int(member.get("permissions") or "0")
    except (TypeError,ValueError):permissions=0
    # Administrator, Manage Server, or Manage Messages.
    if permissions & (0x8|0x20|0x2000):return True
    return bool(DISCORD_MOD_ROLE_IDS.intersection({str(r) for r in member.get("roles") or []}))

def _discord_is_owner(payload:dict):
    uid,_=_discord_user(payload)
    return bool(DISCORD_OWNER_USER_IDS) and str(uid) in DISCORD_OWNER_USER_IDS

def _discord_validate_options(command,options):
    options=dict(options or {})
    if command not in DISCORD_OPTION_SCHEMA:return options,""
    schema={field['name']:field for field in DISCORD_OPTION_SCHEMA[command]}
    if command=='seedindustries' and not options.get('action') and (options.get('category') or options.get('page')):options['action']='browse'
    if command=='make' and options.get('category'):
        options['category']=normalize_craft_category(options['category']) or options['category']
    if command=='me' and not options.get('section'):
        if options.get('title'):options['section']='titles'
        elif options.get('style'):options['section']='display'
    if command=='repair' and options.get('item') and not options.get('target'):options['target']='gear'
    for key,value in options.items():
        if key not in schema:return options,f"⚠️ /{command} does not have an option named {key}. Choose from the current command menu. Nothing spent."
        if value is None or value=='':continue
        field=schema[key]
        if field.get('type')==4:
            if isinstance(value,bool) or not isinstance(value,int) or not field.get('min_value',1)<=value<=field.get('max_value',25):
                return options,f"⚠️ {key.title()} must be a whole number from {field.get('min_value',1)} to {field.get('max_value',25)}. Nothing spent."
        if field.get('choices'):
            match=next((choice for choice in field['choices'] if str(value).lower() in {str(choice['value']).lower(),choice['name'].lower()}),None)
            if not match:return options,f"⚠️ Choose a valid {key} for /{command}: "+', '.join(c['name'] for c in field['choices'])+'. Nothing spent.'
            options[key]=match['value']
        if isinstance(value,str) and field.get('min_length') and not value.strip():return options,f"⚠️ {key.title()} cannot be blank. Nothing spent."
        if isinstance(value,str) and len(value)>field.get('max_length',6000):return options,f"⚠️ {key.title()} is too long. Nothing spent."
    for key,field in schema.items():
        if field.get('required') and not options.get(key):
            return options,f"ℹ️ Choose {key} from /{command}'s options first."
    restrictions={
        'me':('section',{'title':{'titles'},'style':{'display'}}),
        'business':('action',{'name':{'start'}}),
        'repair':('target',{'item':{'gear'}}),
        'market':('action',{'resource':{'sell'},'amount':{'sell'}}),
        'seedindustries':('action',{'item':{'buy','sell','fulfill'},'amount':{'buy','sell'},'category':{'browse','buy','sell'},'page':{'browse','starters'}}),
        'social':('action',{'player':{'hi','hangout','mentor','duo_walk','duo_games','duo_research','duo_delivery','duo_explore'}}),
    }
    if command in restrictions:
        selector,fields=restrictions[command]
        for field,allowed in fields.items():
            if options.get(field) is not None and options.get(field)!='' and options.get(selector) not in allowed:
                return options,f"ℹ️ {field.title()} is used with /{command} {selector}:"+' or '.join(sorted(allowed))+f". Choose that {selector}, or remove {field}. Nothing spent."
    required={
        ('market','sell'):('resource',),('seedindustries','buy'):('item',),
        ('seedindustries','sell'):('item',),('seedindustries','fulfill'):('item',),

    }
    selector='target' if command=='repair' else 'action'
    needed=list(required.get((command,options.get(selector)),()))
    if command=='social' and options.get('action') not in {None,'','group_games'}:needed.append('player')
    for field in needed:
        if not options.get(field):return options,f"ℹ️ Select {field} to continue with /{command} {selector}:{options.get(selector)}. Nothing spent."
    if command=='make' and options.get('recipe') and options.get('category')=='raw_materials':
        return options,"ℹ️ Raw Materials are gathered or bought. Select Basic Components, Advanced Components, Final Products, or Production Tree for a recipe. Nothing spent."
    return options,""

def gain_branch(db,p,branch,amount):
    row=db.get(SkillBranch,(p.channel_id,p.twitch_uid,branch))
    if not row:
        row=SkillBranch(channel_id=p.channel_id,canonical_uid=p.twitch_uid,branch=branch,xp=0);db.add(row)
    row.xp+=amount

@app.get('/api/v1/training')
@colony_command
def training(channel:str,uid:str,name:str='Citizen',skill:str='',task:str='',provider:str='twitch',text:str=''):
    if text and not skill and not task:
        parts=text.split()
        skill=parts[0] if parts else ''
        task=parts[1] if len(parts)>1 else ''
        if len(parts)>2:return out('Use !training <skill> <task>, or just !training <skill> to browse. Nothing spent.')
    hub=(skill or '').lower().strip()
    if task:
        cfg=SEED_TASKS.get(task)
        if not cfg or cfg['hub']!=hub:return out('Choose a Skill first, then one of its Task options. Nothing spent.')
        return action(task,channel,uid,name,provider=provider)
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if hub not in SEED_HUBS:
            return PlainTextResponse('🎒 ITEM MENU — SKILL TRAINING\nChoose Skill, then browse its tasks.\n'+'\n'.join(f"• {SKILL_LABELS[key]} — Lv. {lvl(skill_xp(p,key))}" for key in SEED_HUBS.values())+'\nBrowsing spends nothing. Task selections perform work. Existing /make recipes and work commands still function.')
        key=SEED_HUBS[hub];level=lvl(skill_xp(p,key))
        rows=db.execute(select(SkillBranch).where(SkillBranch.channel_id==channel,SkillBranch.canonical_uid==p.twitch_uid)).scalars().all();branch_xp={r.branch:r.xp for r in rows}
        lines=[f"🎒 ITEM MENU — {SKILL_LABELS[key]}",f"Main skill: level {level} · {skill_xp(p,key)} XP",'Task materials are personal inventory. Consumed only on success; failures keep them. Every attempt spends needs and starts a 5-second cooldown.']
        for action_key,cfg in SEED_TASKS.items():
            if cfg['hub']!=hub:continue
            xp=branch_xp.get(cfg['branch'],0);lock=f"LOCKED: {SKILL_LABELS[key]} {cfg['unlock']} required" if level<cfg['unlock'] else 'Available'
            cost='; '.join(f"{resource_name(k)}: need {v}, own {material_amount(db,p,k)}" for k,v in cfg['cost'].items()) or 'No items required'
            if action_key in MERGED_TRAINING:
                rid=MERGED_TRAINING[action_key];r=seed_content.RECIPES[rid]
                lock+=f"; {crafting_progression.unlock_text(sys.modules[__name__],db,p,rid)}; {seed_content.skill_name(r['requirement'].get('Skill'))} Lv.{seed_content.required_level(r)}"
            outputs=', '.join(f"{v} {resource_name(k)}" for k,v in cfg['output'].items())
            benefits=', '.join(f"shared {k} +{v}" for k,v in cfg['shared'].items())
            benefits+=(', ' if benefits and cfg['society'] else '')+', '.join(f"society {k} +{v}" for k,v in cfg['society'].items())
            tag=None if action_key in MERGED_TRAINING else crafting_progression.TRAINING_STATIONS.get(cfg['branch'])
            if tag:cost+=f". Station: {crafting_progression.STATIONS[tag]['name']} · Tier {crafting_progression.STATIONS[tag]['tier']}; /workshop"
            lines.append(f"• {cfg['label']} — branch Lv. {lvl(xp)} ({xp} XP); {lock}\n  {cost}. Output: {outputs or benefits or cfg['effect']}."+(f" {benefits}." if outputs and benefits else '')+(f" {cfg['effect']}" if cfg['effect'] else ''))
        jobs=[label for label,sk,_ in NEW_JOBS.values() if sk==key]
        if key=='cultivation':jobs=['Farmer']
        lines.append('Matching jobs: '+', '.join(jobs)+'. Use /job. Main skill levels improve success; branch levels add up to 5 percentage points to matching task success. Lv.10 specialization adds its existing bonuses.')
        lines.append('Sources: Lumber, Murky Water, Stone and Herbs → Harvesting; Wood Planks, Stone Block, Fabric, Antiseptics and Preserved Food → Processing; Storage Jars → Crafting; Medicine → Medicine; Components → Engineering or /make; Crops → Farming or /farm.')
        lines.append('Select Task to perform work. Browsing spends nothing.')
        text='\n'.join(lines)
        return PlainTextResponse(text) if provider=='discord' else out(text.replace('\n',' | '))

def edible_inventory(db,p):
    kits=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key=="meal_kit",QualityGear.qty>0)).scalars().all()
    best=max(kits,key=lambda row:list(QUALITY_TIERS).index(row.quality)) if kits else None
    kit_gain=75+int(QUALITY_TIERS[best.quality]["special"]*100) if best else 0
    return [
        {"key":"crops","name":"Crop","qty":p.crops,"effect":"+35 Nutrition, +1 Morale"},
        {"key":"ration","name":"Ration","qty":item(db,p.channel_id,p.twitch_uid,"ration"),"effect":"+70 Nutrition, +5 Morale; +3 percentage points to the success chance for 10 minutes"},
        {"key":"meal_kit","name":"Meal Kit","qty":sum(row.qty for row in kits),
         "effect":f"+{kit_gain} Nutrition, +5 Morale; uses your best quality ({best.quality})" if best else "Nutrition and Morale recovery; strength depends on quality"},
    ] + [{"key":key,"name":cfg['name'],"qty":material_amount(db,p,key),"effect":f"+{seed_content.nutrition(key)} Nutrition"}
         for key,cfg in seed_content.EDIBLE.items() if material_amount(db,p,key)>0]


def emergency_food_available(db,p,foods=None):
    return life_state(db,p).nutrition<TASK_NEED_MINIMUM and not any(row["qty"]>0 for row in (foods or edible_inventory(db,p)))


def owned_life_items(db,p):
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0,
        QualityGear.item_key.in_(["meal_kit","recreation_set","comfort_pack"]))).scalars().all()
    return {key:[row for row in rows if row.item_key==key] for key in ("meal_kit","recreation_set","comfort_pack")}


def item_command_menu(command,uid,name):
    """Read supplies without executing a task or starting its cooldown."""
    with SessionLocal() as db:
        _,p=player(db,DISCORD_WORLD_ID,"discord",uid,name)
        shared=colony_state(db,p.channel_id)
        lines=["🍽️ FOOD MENU" if command=="eat" else "🎒 ITEM MENU",f"{p.display_name} — /{command}"]
        if command=="eat":
            foods=edible_inventory(db,p);life=life_state(db,p)
            lines += [f"Nutrition: {life.nutrition}/100", "YOUR FOOD"]
            lines += [f"• {row['name']} ×{row['qty']} — {row['effect']}" for row in foods]
            if emergency_food_available(db,p,foods):
                lines.append("• Emergency Meal — available free: restores Nutrition to 40; no item consumed.")
            elif not any(row["qty"]>0 for row in foods):
                lines.append("No food owned. Gather Crops with /farm action:harvest, or craft a Ration with /make recipe:ration. Free emergency food becomes available below 20 Nutrition.")
            lines += ["CHOOSE FOOD", "Run /eat again and select Food. The suggestions show owned quantities. One selected item is consumed. Recovery caps at 100; Meal Kit uses your highest quality first."]
        elif command=="use":
            lines.append("ORIGINAL CONSUMABLES")
            for key,rows in owned_life_items(db,p).items():
                effect={"meal_kit":"Nutrition + Morale","recreation_set":"Social + Morale","comfort_pack":"Comfort + Energy"}[key]
                quality=", ".join(f"{r.quality} ×{r.qty}" for r in rows) or "none owned"
                lines.append(f"• {QUALITY_RECIPES[key]['name']} ×{sum(r.qty for r in rows)} — {effect}; {quality}.")
            for key,effect in [('furniture','+35 Comfort, +5 Morale'),('workwear','+20 Comfort, +10 Energy'),('medicine','+10 Comfort; reduces Siro exposure by up to 10')]:
                lines.append(f"• {resource_name(key)} ×{material_amount(db,p,key)} — consumes 1; {effect}.")
            lines.append("These consumables use one item, starting with the highest quality. Item rules appear in the menu above. Recovery caps at 100.")
        elif command=="delivery":
            lines += [f"• Personal Cargo ×{p.cargo} — requires 1; consumed only on success. Failure keeps it.",
                      f"• Shared Cargo ×{shared.cargo} — optional extra society production, separate from your inventory.",
                      "Prepare personal Cargo with /cargo. When ready, use /delivery action:send."]
        elif command=="meal":
            lines += [f"• Personal Crop ×{p.crops} — sharing consumes 1 Crop.",
                      "Gather Crops with /farm action:harvest. Choose /meal action:share to contribute; use /eat for personal food recovery."]
        elif command=="repair":
            lines += [f"• Shared Components ×{shared.components} — society repairs can consume 1 on success to add shared Infrastructure.",
                      f"• Personal Components ×{p.components} — used for personal gear repairs.",
                      "Society work: /repair target:society. Without shared Components, base work rewards still apply but no extra Infrastructure or housing is produced.",
                      "PERSONAL GEAR"]
            rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
            for row in rows:
                cost=max(1,(100-row.condition+19)//20) if row.condition<100 else 0
                lines.append(f"• {row.quality} {row.item_name} ×{row.qty} — {row.condition}% condition; {cost} personal Components to repair.")
            if not rows:lines.append("No quality gear owned. Craft equipment with /make.")
            lines.append("Choose /repair target:gear, then Item. Each selection repairs one quality entry; the dropdown shows cost and stock.")
        elif command in {"research","farm","spaceport","explore","market"}:
            configs={
                "research":("siro_sampler","Siro Sampler","operation","standard","field_analysis",False),
                "farm":("water_filter","Water Filter","action","tend","hydroponics",False),
                "spaceport":("power_cell","Power Cell","operation","standard","expedite",True),
                "explore":("sensor","Sensor","operation","scout","survey",False),
                "market":("market_analyzer","Market Analyzer","action","work","analyze",False),
            }
            key,label,option,normal,advanced,consumed=configs[command]
            qty=(sum(r.qty for r in db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key==key,QualityGear.qty>0)).scalars()) if key=="market_analyzer" else material_amount(db,p,key))
            rule="consumes 1 only on success; kept on failure" if consumed else "requires ownership; not consumed"
            lines += [f"• {label} ×{qty} — advanced task {rule}.",
                      f"Standard task: /{command} {option}:{normal} — no personal item required.",
                      f"Advanced task: /{command} {option}:{advanced}.",
                      f"Get the required item with /make recipe:{key}."]
            if command=="farm":lines.append("Other choices: /farm action:harvest for Crops, or /farm action:irrigate for Processing work.")
            if command=="market":
                lines += ["YOUR SELLABLE RESOURCES"]+[f"• {resource_name(key)} ×{getattr(p,key)}" for key in MARKET_BASE]
                lines.append("Use /market action:view for prices, or /market action:sell and select Resource + Amount. Sales consume the quantity selected.")
        elif command=="social":
            owned=owned_life_items(db,p)
            lines += [f"• Recreation Set ×{sum(r.qty for r in owned['recreation_set'])} — /social action:group_games consumes 1, highest quality first.",
                      f"• Personal Cargo ×{p.cargo} — Duo Delivery consumes 1; select a relationship partner.",
                      "Greetings, hangouts and most duo activities need no item. Select Action and a Player for relationship activities. /games restores Social free without an item or partner."]
        lines.append("Browsing only: no task performed, no items spent, no cooldown started.")
        return "\n".join(lines)


@app.get("/api/v1/seed-supplies")
@colony_command
def seed_supplies(channel:str,uid:str,name:str='Citizen',mode:str='catalog',item:str='',page:int=1,owned:bool=False,provider:str='twitch',category:str=''):
    import sys
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);module=sys.modules[__name__]
        item=seed_content.find_item(item)
        if mode=='gather' and item:result=seed_content.gather(module,db,p,item,provider)
        elif mode=='gather':result=seed_content.gather_menu(page,provider)
        elif mode=='catalog':
            if provider!='discord' and item in seed_content.ACTIVE:
                result=seed_content.item_label(item)+' | '+seed_content.source_hint(item,provider)
            else:result=seed_content.catalog(module,db,p,item,page,owned,category)
        else:result='🛑 Choose catalog or gather. Nothing spent.'
        return platform_response(provider,result,result.replace('\n',' | '))

def _discord_call_internal(command: str, uid: str, name: str, options: dict, interaction_id: str):
    options,error=_discord_validate_options(command,options)
    if error:return error
    # Reuse the same game functions the Twitch API uses.
    channel = DISCORD_WORLD_ID
    if command=='use':
        import sys
        with SessionLocal() as db:
            _,p=player(db,channel,'discord',uid,name)
            category=str(options.get('category') or '')
            if not options.get('item'):
                menu=seed_content.use_menu(sys.modules[__name__],db,p,category,int(options.get('page') or 1))
                return menu if category else menu+'\n\n'+item_command_menu('use',uid,name)
            chosen=seed_content.find_item(str(options['item']))
            if category and seed_content.CATEGORY.get(chosen)!=category:return 'ℹ️ That item is not in this category. Nothing spent.'
    if command=='mine' and options.get('action')=='mine' and not options.get('ore'):return 'Choose Ore before selecting Mine. No queue was started.'
    if command=='queue' and options.get('action')=='start' and not options.get('task'):return 'Choose Task before selecting Start. No queue was started.'
    selectors={"eat":"food","use":"item","delivery":"action","meal":"action", "repair":"target",
               "research":"operation","farm":"action","spaceport":"operation","explore":"operation","market":"action","social":"action"}
    if command in selectors and (not options.get(selectors[command]) or
            (command in {"delivery","meal"} and options.get("action")=="view") or
            (command=="repair" and options.get("target")=="gear" and not options.get("item"))):
        return item_command_menu(command,uid,name)
    if command=="eat":
        return action("eat",channel,uid,name,msg="food:"+str(options["food"]),provider="discord").body.decode()

    if command=='mine':
        return mining(channel,uid,name,str(options.get('ore') or ''),str(options.get('action') or 'view'),int(options.get('count') or 1),'discord').body.decode()
    if command=='queue':
        return queued_tasks(channel,uid,name,str(options.get('action') or 'view'),str(options.get('task') or ''),int(options.get('count') or 1),'discord').body.decode()
    if command=='workshop':
        return workshop(channel,uid,name,str(options.get('action') or 'view'),str(options.get('station') or ''),int(options.get('page') or 1),'discord').body.decode()
    if command in {'catalog','gather'}:
        return seed_supplies(channel,uid,name,command,str(options.get('item') or options.get('resource') or ''),int(options.get('page') or 1),bool(options.get('owned',False)),'discord',str(options.get('category') or '')).body.decode()
    if command == "holiday":
        from .seasonal import holiday_message
        return holiday_message()
    if command == "training":
        return training(channel,uid,name,str(options.get('skill') or ''),str(options.get('task') or ''),'discord').body.decode()
    if command == "seed":
        return discord_seed_help(str(options.get("topic") or "overview"),name)
    if command == "start":
        return start(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "guide":
        return guide(channel=channel,uid=uid,name=name,goal=str(options.get("goal") or "auto"),provider="discord").body.decode("utf-8")
    if command == "me":
        section=str(options.get("section") or "overview").lower()
        if section=="display":return display_style(channel=channel,uid=uid,name=name,style=str(options.get("style") or ""),provider="discord").body.decode("utf-8")
        if section=="life":return life_status(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="bonuses":return bonuses(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="cooldowns":return cooldowns(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="traits":return traits(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="relationships":return relationships(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="journal":return journal(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="tutorial":return tutorial(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="titles":return titles(channel=channel,uid=uid,name=name,title=str(options.get("title") or ""),provider="discord").body.decode("utf-8")
        return profile(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "progress":
        section=str(options.get("section") or "skills").lower()
        if section=="daily":return contracts(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="achievements":return achievements(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="collection":return collection(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return skills(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "inventory":
        if str(options.get("section") or "all").lower()=="gear":
            return gear(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return inventory(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "job":
        return job(channel=channel, uid=uid, name=name, job=str(options.get("job") or ""), provider="discord").body.decode("utf-8")
    if command == "home":
        if str(options.get("action") or "view").lower()=="upgrade":
            return homeup(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return home(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "business":
        business_action=str(options.get("action") or "view").lower()
        if business_action=="start":
            return business_start(channel=channel,uid=uid,name=name,business_name=str(options.get("name") or "New Venture"),provider="discord").body.decode("utf-8")
        if business_action in {"work","contract","invest"}:
            action_name={"work":"business","contract":"businesscontract","invest":"businessinvest"}[business_action]
            return action(action=action_name,channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
        return business(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "make":
        return make(
            channel=channel, uid=uid, name=name,
            recipe=str(options.get("recipe") or ""),
            category=str(options.get("category") or ""),
            page=int(options.get("page") or 1),provider="discord"
        ).body.decode("utf-8")
    if command == "seedindustries":
        return seed_industries(
            channel=channel,uid=uid,name=name,
            action=str(options.get("action") or "browse"),
            item_name=str(options.get("item") or ""),
            amount=int(options.get("amount") or 1),provider="discord",page=int(options.get("page") or 1),category=str(options.get("category") or "all")
        ).body.decode("utf-8")
    if command == "farm":
        farm_action=str(options.get("action") or "tend").lower()
        action_name={"tend":"farm","harvest":"harvest","irrigate":"water","hydroponics":"water"}.get(farm_action,"farm")
        marker="mode:hydroponics" if farm_action=="hydroponics" else f"discord-{interaction_id}"
        return action(action=action_name,channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "research":
        operation=str(options.get("operation") or "standard").lower();marker="mode:field_analysis" if operation=="field_analysis" else f"discord-{interaction_id}"
        return action(action="research",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "spaceport":
        operation=str(options.get("operation") or "standard").lower();marker="mode:expedite" if operation=="expedite" else f"discord-{interaction_id}"
        return action(action="spaceport",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "explore":
        operation=str(options.get("operation") or "scout").lower();action_name="survey" if operation=="survey" else "explore"
        return action(action=action_name,channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
    if command == "repair":
        if str(options.get("target") or "society").lower()=="gear":
            return gearrepair(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
        return action(action="repair",channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
    if command == "market":
        market_action=str(options.get("action") or "view").lower()
        if market_action=="view":return marketboard(channel=channel,provider="discord").body.decode("utf-8")
        if market_action=="sell":return sell(channel=channel,uid=uid,name=name,resource=str(options.get("resource") or ""),amount=int(options.get("amount") or 1),provider="discord").body.decode("utf-8")
        marker="mode:analyze" if market_action=="analyze" else f"discord-{interaction_id}"
        return action(action="market",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "social":
        if not options.get("action"):
            return "🤝 Choose /social action:Say Hi, Hang Out, Mentor, a Duo activity, or Use Recreation Set. Select player for relationship activities. For free solo Social recovery, use /games (+25 Social)."
        social_action=str(options.get("action") or "hi").lower();target=str(options.get("player") or "")
        if social_action=="hi":return hi(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="hangout":return hangout(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="mentor":return mentor(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="group_games":return use_item(channel=channel,uid=uid,name=name,item="recreation_set",provider="discord").body.decode("utf-8")
        if social_action.startswith("duo_"):
            return duo(channel=channel,uid=uid,name=name,target=target,activity=social_action[5:],provider="discord").body.decode("utf-8")
        return "⛔ Unknown social activity."
    if command == "hi":
        return hi(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "hangout":
        return hangout(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "relax":
        return relax(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "walk":
        return walk(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "games":
        return games(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "hobby":
        return hobby(channel=channel,uid=uid,name=name,hobby=str(options.get("hobby") or ""),provider="discord").body.decode("utf-8")
    if command == "world":
        section=str(options.get("section") or "overview").lower()
        if section=="conditions":return conditions(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="rumor":return rumor(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="bulletin":return bulletin(channel=channel,provider="discord").body.decode("utf-8")
        if section=="story":return story(channel=channel,provider="discord").body.decode("utf-8")
        if section=="project":return projectstatus(channel=channel,provider="discord").body.decode("utf-8")
        if section=="market":return marketboard(channel=channel,provider="discord").body.decode("utf-8")
        return world_status(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "district":
        return district(channel=channel,uid=uid,name=name,district=str(options.get("district") or ""),provider="discord").body.decode("utf-8")
    if command == "shift":
        return shift(channel=channel,uid=uid,name=name,role=str(options.get("role") or ""),provider="discord").body.decode("utf-8")
    if command == "meal":
        return meal(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "mentor":
        return mentor(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "sell":
        return sell(channel=channel,uid=uid,name=name,resource=str(options.get("resource") or ""),amount=int(options.get("amount") or 1),provider="discord").body.decode("utf-8")
    if command == "duo":
        return duo(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),activity=str(options.get("activity") or "walk"),provider="discord").body.decode("utf-8")
    if command == "ducks":
        return ducks(channel=channel,uid=uid,name=name,duck=str(options.get("duck") or ""),provider="discord").body.decode("utf-8")
    if command == "gearrepair":
        return gearrepair(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
    if command == "use":
        return use_item(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
    if command == "linklookup":
        with SessionLocal() as db:
            return owner_link_lookup(db,channel,str(options.get("player") or ""))
    if command == "link":
        return link_claim(
            channel=channel,
            discord_uid=uid,
            name=name,
            code=str(options.get("code") or "")
        ).body.decode("utf-8")
    if command == "specialize":
        return specialize(channel=channel,uid=uid,name=name,path=str(options.get("path") or ""),provider="discord").body.decode("utf-8")
    if command == "society":
        section=str(options.get("section") or "overview").lower()
        if section=="progress":return progress(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
        if section=="leaderboard":return leaderboard(channel=channel,provider="discord",uid=uid,name=name).body.decode("utf-8")
        return soc(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
    if command == "event":
        if str(options.get("section") or "status").lower()=="history":
            return eventhistory(channel=channel,provider="discord").body.decode("utf-8")
        return event(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
    if command == "modlog":
        with SessionLocal() as db:
            rows=db.execute(select(ModeratorAudit).where(ModeratorAudit.channel_id==channel).order_by(ModeratorAudit.created_at.desc()).limit(10)).scalars().all()
            return "🛡️ No moderator actions recorded." if not rows else "🛡️ Moderator Log\n"+"\n".join(f"{r.moderator}: {r.action} — {r.detail}" for r in rows)
    if command == "eventstart":
        event_key=str(options.get("event") or "").lower()
        if event_key not in EVENTS:return "⛔ Unknown event."
        with SessionLocal() as db:
            s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
            if w.active_event:return "⛔ An event is already active. Use /eventstop first."
            actor=f"{name} ({uid})";result=start_event(db,w,event_key,actor);audit_moderator(db,channel,actor,"eventstart",event_key);return result
    if command == "eventstop":
        with SessionLocal() as db:
            actor=f"{name} ({uid})";w=world(db,channel);event_key=w.active_event or "none";result=cancel_event(db,w,actor);audit_moderator(db,channel,actor,"eventstop",event_key);return result

    action_name = {"farm":"farm","fabricate":"machine"}.get(command,command)
    return action(
        action=action_name,
        channel=channel,
        uid=uid,
        name=name,
        msg=f"discord-{interaction_id}",
        provider="discord"
    ).body.decode("utf-8")

@app.post("/discord/interactions")
async def discord_interactions(request: Request, background_tasks: BackgroundTasks):
    if not DISCORD_PUBLIC_KEY:
        raise HTTPException(status_code=500, detail="DISCORD_PUBLIC_KEY is not configured")

    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = await request.body()

    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except (BadSignatureError, ValueError):
        raise HTTPException(status_code=401, detail="invalid request signature")

    payload = await request.json()

    # Discord endpoint validation / ping.
    if payload.get("type") == 1:
        return {"type": 1}

    # Discord sends type 4 while a user is opening/searching an autocomplete option.
    if payload.get("type") == 4:
        if not _discord_allowed_channel(payload):
            return {"type":8,"data":{"choices":[]}}
        return _discord_autocomplete(payload)

    # Application command.
    if payload.get("type") != 2:
        return _discord_json_message("Unsupported Discord interaction.", ephemeral=True)

    if not _discord_allowed_channel(payload):
        return _discord_json_message(
            "🌱 New Eridian commands are only available in the designated game channel.",
            ephemeral=True
        )

    command = ((payload.get("data") or {}).get("name") or "").lower()
    uid, name = _discord_user(payload)
    options = _discord_options(payload)
    interaction_id = str(payload.get("id") or "")

    if not uid:
        return _discord_json_message("Could not identify your Discord account.", ephemeral=True)

    if command not in (DISCORD_PUBLIC_COMMANDS | DISCORD_PRIVATE_COMMANDS):
        return _discord_json_message("Unknown New Eridian command.", ephemeral=True)

    if command in {"eventstart","eventstop","modlog"} and not _discord_is_moderator(payload):
        return _discord_json_message("⛔ Moderator access is required for event controls.", ephemeral=True, message_type="moderator")

    if command == "linklookup" and not _discord_is_owner(payload):
        return _discord_json_message(
            f"⛔ Owner access is required for linked-account lookup. "
            f"Detected Discord ID: {uid} | Owner IDs loaded: {len(DISCORD_OWNER_USER_IDS)}. "
            f"Make sure Railway DISCORD_OWNER_USER_IDS contains this exact numeric ID, then redeploy.",
            ephemeral=True,
            message_type="moderator"
        )

    try:
        result = _discord_call_internal(command, uid, name, options, interaction_id)
    except Exception as exc:
        # Keep the public Discord response clean; Railway logs will contain the traceback.
        print("Discord command error:", command, repr(exc))
        return _discord_json_message(
            "⚠️ New Eridian hit a system error while processing that command.",
            ephemeral=True,
            message_type=command
        )

    if result.startswith(("🍽️ FOOD MENU","🎒 ITEM MENU")):
        return _discord_json_message(result,ephemeral=True,message_type=command)

    # Commands that are already private keep their full response private.
    if command in DISCORD_PRIVATE_COMMANDS:
        return _discord_json_message(
            result,
            ephemeral=True,
            message_type=command
        )

    # Public action results stay visible to the channel, but personal
    # modifiers/success-chance calculations are sent only to the player.
    if command in DISCORD_PERSONAL_DETAIL_COMMANDS:
        public_result,private_details=_discord_split_personal_details(result)
        if private_details:
            background_tasks.add_task(
                _discord_send_ephemeral_followup,
                str(payload.get("application_id") or ""),
                str(payload.get("token") or ""),
                private_details,
                command,
            )
        return _discord_json_message(
            public_result,
            ephemeral=False,
            message_type=command
        )

    return _discord_json_message(
        result,
        ephemeral=False,
        message_type=command
    )


@app.get("/api/v1/settlement")
def settlement_status(channel:str):
    """Additional JSON view; existing society/overlay fields are untouched."""
    from .settlement import CORE, STOCKS
    with SessionLocal() as db:
        s=society(db,channel);shared=colony_state(db,channel);colony_tick(shared,s,now());db.commit()
        return {"schema_version":7,"name":s.name,"resources":{k:getattr(s,k) for k in CORE}|{k:getattr(shared,k) for k in STOCKS},"pressures":colony_pressures(shared,s),"population":s.population}

@app.get("/api/v1/routine")
def routine(channel:str,uid:str,name:str="Citizen",provider:str="twitch",goal:str="",preferred:str=""):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);st=colony_seedling(db,p)
        if goal:
            if goal not in {"settlement","recovery","occupation"}:raise HTTPException(400,"goal must be settlement, recovery or occupation")
            st.goal=goal
        if preferred:
            if preferred not in {"games","walk","relax"}:raise HTTPException(400,"preferred must be games, walk or relax")
            st.preferred_activity=preferred
        project=current_project(db,channel,world_clock(db,channel)["day"])
        result=routine_description(life_state(db,p),p.job,project=project.progress<project.goal,goal=st.goal,preferred=st.preferred_activity)
        from .competencies import rank
        from .occupations import OCCUPATIONS
        result["competencies"]={key:{"xp":skill_xp(p,key),"level":lvl(skill_xp(p,key)),"rank":rank(skill_xp(p,key))} for key in SKILL_LABELS}
        result["occupation_profile"]=OCCUPATIONS.get(p.job,{})
        result["exposure"]=player_world(db,p).siro_exposure
        result.update({"occupation":p.job,"goal":st.goal,"occupation_history":json.loads(st.occupation_history),"last_progress":st.last_progress})
        db.commit();return result

@app.post("/api/v1/admin/routine/step")
def routine_step(channel:str,uid:str,name:str="Citizen",provider:str="twitch",key:str=""):
    """Explicit operator-driven single step; never background offline reward spam."""
    if ADMIN_KEY=="change-me" or not secrets.compare_digest(key,ADMIN_KEY):raise HTTPException(403,"Admin key required")
    choice=routine(channel,uid,name,provider)["next_action"]
    if choice in ACTION_SKILLS or choice in {"eat","sleep"}:return action(choice,channel,uid,name,provider=provider)
    return {"games":games,"walk":walk,"relax":relax}[choice](channel,uid,name,provider=provider)


# Configure identities after all route/function definitions, before accepting work.
item_identity.configure(sys.modules[__name__])
with SessionLocal() as _identity_db:
    for _identity_player in _identity_db.execute(select(Player)).scalars():
        item_identity.migrate_player(sys.modules[__name__],_identity_db,_identity_player)
    _identity_db.commit()


from . import task_queue

@app.get('/api/v1/queue')
def queued_tasks(channel:str,uid:str,name:str='Citizen',action:str='view',task:str='',count:str='1',provider:str='twitch'):
    try:count=int(str(count).strip() or '1')
    except ValueError:return out('Count must be a whole number from 1 to 10. No queue was changed.')
    text=task_queue.control(sys.modules[__name__],channel,uid,name,provider,action,task,count)
    short=task_queue.short_status(sys.modules[__name__],channel,uid,name,provider) if provider!='discord' and text.startswith('TASK QUEUE') else text.replace('\n',' | ')
    return platform_response(provider,text,short)

@app.get('/api/v1/mining')
def mining(channel:str,uid:str,name:str='Citizen',ore:str='',action:str='view',count:str='1',provider:str='twitch'):
    try:count=int(str(count).strip() or '1')
    except ValueError:return out('Count must be a whole number from 1 to 10. Nothing was spent.')
    module=sys.modules[__name__];key=seed_content.find_item(ore)
    if action not in {'view','mine'}:return out('Choose View Requirements or Mine. Nothing was spent.')
    if not 1<=count<=10:return out('Count must be from 1 to 10. Nothing was spent.')
    if not ore:
        lines=['MINING — CHOOSE AN ORE','Select Ore to inspect its requirements, then choose Mine. Count queues up to 10 attempts of that ore.']
        for k in sorted(task_queue.ores(),key=seed_content.item_label):
            rule='Harvesting Lv.3; three steps per ore; 3 Energy, 1 Nutrition and 1 Comfort per step; 20-second shared cooldown' if k in crafting_progression.RARE else 'No skill unlock or tools required; 2 Energy, 1 Nutrition and 1 Comfort; 5-second shared gathering cooldown'
            lines.append(seed_content.item_label(k)+': '+rule+'.')
        text='\n'.join(lines)
    elif key not in task_queue.ores():text='Choose an ore from /mine. Other natural resources are listed under /gather. Nothing was spent.'
    elif action=='mine':return queued_tasks(channel,uid,name,'start','mine:'+key,count,provider)
    else:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            rule='Harvesting level 3; three prospecting steps per ore; shared 20-second cooldown. No materials or tools required.\n' if key in crafting_progression.RARE else 'No skill unlock, materials or tools required; shared 5-second gathering cooldown.\n'
            text=seed_content.item_label(key)+' — MINING REQUIREMENTS\n'+rule+task_queue.requirements(module,db,p,'mine:'+key,count)+'\nSelect Mine to start. Use /queue to check progress or cancel.'
    return platform_response(provider,text,text.replace('\n',' | '))

task_queue.install(sys.modules[__name__])
DISCORD_PRIVATE_COMMANDS.add('queue')


@app.get('/api/v1/queue-tasks')
def queue_task_menu(query:str='',page:int=1,provider:str='twitch'):
    entries=sorted(((key,label) for key,label in task_queue.choices(sys.modules[__name__]).items() if query.casefold() in (key+' '+label).casefold()),key=lambda row:row[1])
    size=8 if provider=='discord' else 2;pages=max(1,math.ceil(len(entries)/size));page=max(1,min(page,pages))
    lines=[f'QUEUE TASKS · Page {page}/{pages}']+[f'{label}: {key}' for key,label in entries[(page-1)*size:page*size]]
    if not entries:lines.append('No matching tasks. Try a resource, recipe or activity name.')
    lines.append('!queueadd <task ID> <1–10>; !queuetaskpage <page>. One task type at a time.')
    text='\n'.join(lines)
    return platform_response(provider,text,text.replace('\n',' | '))


# Extension registration happens after core routes and models are available.
from .fun_systems import install as install_fun_systems
from .seasonal import install as install_seasonal
install_fun_systems(app)
install_seasonal(app)
