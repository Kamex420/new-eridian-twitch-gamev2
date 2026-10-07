# app/main.py, part 2: rules
# Game rules as data: jobs, events, skills, recipes, gear, world conditions, projects, directives, story arcs,
# markets.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

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
# Sleep fully restores Energy and Comfort, so it runs on a long timer; Comfort
# otherwise comes from /relax and comfort items (beds, seats, baths, clothing).
from .needs import SLEEP_COOLDOWN_SECONDS
ACTION_COOLDOWNS["sleep"]=SLEEP_COOLDOWN_SECONDS
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
# Legacy parts are retired: each now IS a catalog item (see item_identity) and
# is crafted with that item's catalog recipe. The keys stay so historical
# manufacturing ledgers keep counting toward personal tiers and achievements.
PART_RECIPES={
    "component":{"ore":1},
    "biofiber":{"crops":2},
    "alloy_plate":{"ore":2},
    "circuit_board":{"components":1,"rare_ore":1},
    "power_cell":{"components":2,"cargo":1},
    "sealant":{"crops":1,"components":1},
    "precision_lens":{"rare_ore":1,"alloy_plate":1},
}
CRAFT_OUTPUT_KEYS={"component":"components"}
_I=seed_content.key  # readable catalog references for the tables below
# Legacy equipment without a catalog twin stays an upgrade, built from catalog parts.
RECIPES={
    "toolkit":{_I("Iron Plate"):2,_I("Iron Nails"):4,_I("Wood Planks"):2},
    "siro_sampler":{_I("Glass"):2,_I("Iron Rod"):2,_I("Antiseptics"):2},
    "duck_crate":{_I("Wood Planks"):6,_I("Iron Nails"):6,_I("Flaxa"):2},
    "spaceport_manifest":{_I("Circuit Board"):1,_I("Power Cell"):1,_I("Wood Planks"):2},
}
RECIPE_TIERS={"toolkit":0,"siro_sampler":2,"duck_crate":3,"spaceport_manifest":4}
# Passive equipment bonuses. Water Filter, Sensor and Crate are now the catalog
# Small Water Filter, Resource Scanner and Storage Platform (same bonuses).
SKILL_EQUIPMENT={"environmental":"water_filter","research":"siro_sampler","logistics":"duck_crate","commerce":"spaceport_manifest"}
ITEM_EFFECTS={
    "toolkit":"+2 percentage points to the success chance for Crafting/Infrastructure; keep one",
    "sensor":"+2 percentage points to the success chance for Extraction/Research/Frontier; unlocks Advanced Survey",
    "crate":"+1 SC on successful Logistics/Commerce actions",
    "water_filter":"+2 percentage points to the Environmental success chance; unlocks Hydroponics",
    "siro_sampler":"+2 percentage points to the Research success chance; unlocks Field Analysis; keep one",
    "duck_crate":"+2 percentage points to the Logistics success chance; keep one",
    "spaceport_manifest":"+2 percentage points to the Commerce success chance; keep one",
}
UNIQUE_CORE_ITEMS=set(RECIPES)

QUALITY_TIERS={
    "Crude":{"skill":.01,"special":.00},
    "Standard":{"skill":.02,"special":.02},
    "Refined":{"skill":.03,"special":.04},
    "Precision":{"skill":.04,"special":.07},
    "Masterwork":{"skill":.05,"special":.10},
}

# Quality gear remains the specialist upgrade system; every ingredient is a
# catalog item that a matching-tier player can gather or manufacture.
QUALITY_RECIPES={
    # Agriculture
    "cultivator":{"name":"Field Hoe","category":"agriculture","cost":{_I("Iron Plate"):2,_I("Wood Planks"):2,_I("Iron Nails"):2},"skills":{"cultivation":1},"special":"crop yield"},
    "soil_scanner":{"name":"Soil Scanner","category":"agriculture","cost":{_I("Iron Plate"):2,_I("Ceramic Tiles"):2,_I("Argentite Ore"):1},"skills":{"cultivation":1,"research":1},"special":"crop yield"},
    "irrigation_controller":{"name":"Irrigation Controller","category":"agriculture","cost":{_I("Iron Rod"):2,_I("Iron Plate"):1,_I("Flaxa"):2,_I("Clean Water (750ml)"):2},"skills":{"cultivation":1,"environmental":1},"special":"Agriculture/Irrigation success"},
    "cultivation_rig":{"name":"Agriculture Rig","category":"agriculture","cost":{_I("Iron Plate"):3,_I("Iron Bolt"):4,_I("Wood Planks"):4,_I("Argentite Ore"):1},"skills":{"cultivation":2},"special":"Farming XP"},

    # Extraction
    "mining_pick":{"name":"Reinforced Mining Pick","category":"extraction","cost":{_I("Iron Plate"):2,_I("Iron Rod"):2,_I("Wood Planks"):1},"skills":{"extraction":1},"special":"mining success"},
    "ore_scanner":{"name":"Ore Scanner","category":"extraction","cost":{_I("Iron Plate"):2,_I("Glass"):2,_I("Argentite Ore"):1},"skills":{"extraction":1,"research":1},"special":"rare-find chance"},
    "reinforced_drill":{"name":"Reinforced Drill","category":"extraction","cost":{_I("Iron Rod"):4,_I("Iron Bolt"):4,_I("Iron Plate"):2,_I("Argentite Ore"):1},"skills":{"extraction":2},"special":"material yield"},
    "geological_analyzer":{"name":"Geological Analyzer","category":"extraction","cost":{_I("Iron Plate"):3,_I("Glass"):2,_I("Iron Bolt"):4,_I("Argentite Ore"):2},"skills":{"extraction":1,"research":2},"special":"rare-find chance"},

    # Crafting / Infrastructure
    "precision_tools":{"name":"Precision Tools","category":"fabrication","cost":{_I("Iron Plate"):2,_I("Iron Nails"):4,_I("Iron Rod"):2},"skills":{"fabrication":2},"special":"craft quality"},
    "assembly_bench":{"name":"Portable Assembly Bench","category":"fabrication","cost":{_I("Iron Plate"):4,_I("Wood Planks"):4,_I("Iron Bolt"):4,_I("Argentite Ore"):1},"skills":{"fabrication":2,"infrastructure":1},"special":"Crafting XP"},
    "repair_kit":{"name":"Advanced Repair Kit","category":"infrastructure","cost":{_I("Iron Nails"):6,_I("Iron Plate"):2,_I("Stone Block"):2,_I("Clay"):2},"skills":{"infrastructure":1},"special":"repair success"},
    "structural_scanner":{"name":"Structural Scanner","category":"infrastructure","cost":{_I("Iron Plate"):3,_I("Glass"):2,_I("Iron Bolt"):2,_I("Argentite Ore"):1},"skills":{"infrastructure":1,"research":1},"special":"Infrastructure Repair success"},
    "emergency_patch_kit":{"name":"Emergency Patch Kit","category":"infrastructure","cost":{_I("Iron Nails"):6,_I("Iron Plate"):2,_I("Clay"):2,_I("Flaxa"):2},"skills":{"infrastructure":1},"special":"event repair"},

    # Research / Environmental
    "field_microscope":{"name":"Field Microscope","category":"research","cost":{_I("Glass"):3,_I("Iron Plate"):2,_I("Circuit Board"):1},"skills":{"research":1},"special":"research success"},
    "sample_analyzer":{"name":"Sample Analyzer","category":"research","cost":{_I("Glass"):2,_I("Circuit Board"):1,_I("Copper Wire"):2,_I("Argentite Ore"):1},"skills":{"research":2},"special":"Research XP"},
    "siro_array":{"name":"Siro Detection Array","category":"research","cost":{_I("Circuit Board"):2,_I("Glass"):4,_I("Copper Wire"):4,_I("Argentite Ore"):2},"skills":{"research":2,"environmental":1},"special":"Siro-event success"},

    # Logistics / Commerce
    "cargo_harness":{"name":"Cargo Harness","category":"logistics","cost":{_I("Fabric"):2,_I("Iron Plate"):1,_I("Iron Nails"):4},"skills":{"logistics":1},"special":"delivery success"},
    "routing_tablet":{"name":"Routing Tablet","category":"logistics","cost":{_I("Glass"):2,_I("Copper Wire"):2,_I("Iron Plate"):2,_I("Argentite Ore"):1},"skills":{"logistics":2},"special":"delivery success"},
    "merchant_ledger":{"name":"Merchant Ledger","category":"commerce","cost":{_I("Wood Planks"):4,_I("Fabric"):2,_I("Circuit Board"):1},"skills":{"commerce":1},"special":"SC reward"},
    "market_analyzer":{"name":"Market Analyzer","category":"commerce","cost":{_I("Circuit Board"):2,_I("Glass"):2,_I("Copper Wire"):2,_I("Argentite Ore"):1},"skills":{"commerce":2,"research":1},"special":"market success"},

    # Frontier
    "survival_pack":{"name":"Survival Pack","category":"frontier","cost":{_I("Fabric"):3,_I("Flaxa"):4,_I("Dried Berries"):2},"skills":{"frontier":1},"special":"exploration success"},
    "navigation_unit":{"name":"Navigation Unit","category":"frontier","cost":{_I("Glass"):2,_I("Copper Wire"):2,_I("Fabric"):2,_I("Argentite Ore"):1},"skills":{"frontier":2},"special":"survey success"},
    "expedition_kit":{"name":"Expedition Kit","category":"frontier","cost":{_I("Fabric"):4,_I("Power Cell"):1,_I("Glass"):2,_I("Dried Berries"):2,_I("Argentite Ore"):1},"skills":{"frontier":2,"logistics":1},"special":"exploration finds"},

    # Life consumables (quality scales their recovery)
    "meal_kit":{"name":"Prepared Meal Kit","category":"life","cost":{_I("Pumpkin"):3,_I("Herbs"):2,_I("Clean Water (750ml)"):1,_I("Flaxa"):1},"skills":{},"special":"nutrition recovery"},
    "recreation_set":{"name":"Recreation Set","category":"life","cost":{_I("Wood Planks"):6,_I("Flaxa"):2,_I("Stone Block"):1},"skills":{},"special":"social/morale recovery"},
    "comfort_pack":{"name":"Habitat Comfort Pack","category":"life","cost":{_I("Rough Flaxa Cushion"):2,_I("Fabric"):2},"skills":{},"special":"comfort recovery"},
    'chef_tools':dict(name="Chef's Tools",category='life',cost={_I("Iron Plate"):2,_I("Iron Rod"):1,_I("Wood Planks"):2},skills={'cooking':1},special='Cooking success'),
    'medical_bag':dict(name='Medical Bag',category='life',cost={_I("Fabric"):3,_I("Bandage"):2,_I("Antiseptics"):2},skills={'medicine':1},special='Medicine success'),
    'fire_gear':dict(name='Fire Safety Gear',category='life',cost={_I("Fabric"):4,_I("Iron Plate"):2,_I("Clean Water (750ml)"):2},skills={'emergency':1},special='Emergency Response success'),
}
assert all(k in seed_content.ACTIVE for r in (*RECIPES.values(),*(q["cost"] for q in QUALITY_RECIPES.values())) for k in r),"Legacy gear must use catalog items"

UNIQUE_QUALITY_ITEMS={key for key,recipe in QUALITY_RECIPES.items() if recipe["skills"]}
LIFE_GEAR=("meal_kit","recreation_set","comfort_pack")
ACTION_COOLDOWNS["rare_prospect"]=20

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
# /market sells the five resources backed by player columns. Crops are Pumpkins
# and Components are Iron Nails; prices stay below Seed Industries purchase
# prices even on the best demand day (x1.6), so buying to resell never profits.
MARKET_BASE={"crops":2,"ore":3,"rare_ore":10,"components":1,"cargo":6}
SEED_INDUSTRIES={
    # key: fixed NPC buy price, fixed NPC sell price, and why it exists
    "cargo":{"buy":12,"sell":5,"purpose":"Logistics token for deliveries, Spaceport and business work"},
}
# Catalog starter stock is buy-only; catalog buyback is added centrally.
SEED_INDUSTRIES.update({k:dict(v) for k,v in crafting_progression.STARTER_MARKET.items()})

# Seed Industries pays less than the NPC replacement cost of an order, so
# buying every input can never create an arbitrage loop. Citizens profit by
# gathering and manufacturing the inputs themselves.
PRODUCTION_ORDERS={
    "greenhouse_liners":{"name":"Greenhouse Liner Batch","cost":{_I("Ceramic Tiles"):5,_I("Flaxa"):4},"tier":0,"purpose":"Reinforce greenhouse beds against Avesta dust."},
    "maintenance_stock":{"name":"Maintenance Stock","cost":{_I("Iron Plate"):2,_I("Iron Nails"):5},"tier":0,"purpose":"Restock New Eridian's public repair lockers."},
    "field_rations":{"name":"Field Ration Lot","cost":{_I("Dried Berries"):3},"tier":0,"purpose":"Supply field crews working beyond the habitat ring."},
    "lab_controls":{"name":"Laboratory Control Set","cost":{_I("Circuit Board"):1,_I("Glass"):2},"tier":1,"purpose":"Replace unstable controls in the Research Block."},
    "water_renewal":{"name":"Water Renewal Kit","cost":{_I("Small Water Filter"):1,_I("Clean Water (750ml)"):5},"tier":1,"purpose":"Keep settlement water systems within tolerance."},
    "spaceport_cells":{"name":"Spaceport Power Reserve","cost":{_I("Power Cell"):1,_I("Copper Wire"):2},"tier":2,"purpose":"Maintain emergency power at the Spaceport."},
    "research_samples":{"name":"Siro Analysis Package","cost":{"siro_sampler":1,_I("Glass"):2},"tier":2,"purpose":"Expand the Siro monitoring archive."},
    "duck_fleet_crates":{"name":"Delivery Fleet Refit","cost":{"duck_crate":1,_I("Power Cell"):1},"tier":3,"purpose":"Refit the delivery fleet's most judgmental cargo units."},
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
