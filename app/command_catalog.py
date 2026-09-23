
"""Shared Discord command catalog: registration and runtime validation use this file."""

def cmd(name, description, options=None):
    d = {"name": name, "description": description}
    if options:
        d["options"] = options
    return d

STRING = 3

commands = [
    cmd("seed","Open the New Eridian v2 handbook",[{
        "type":STRING,"name":"topic","description":"What do you want explained?","required":False,
        "choices":[
            {"name":"Start Here","value":"start"},{"name":"Character & Progression","value":"character"},
            {"name":"Home, Business & Crafting","value":"property"},{"name":"Life & Social","value":"life"},
            {"name":"Work Actions","value":"production"},{"name":"Logistics, Frontier & Commerce","value":"operations"},
            {"name":"Society & World","value":"society"},{"name":"Other Player Actions","value":"other"},
            {"name":"Moderator Controls","value":"moderator"},{"name":"Terms & Definitions","value":"terms"}
        ]
    }]),
    cmd("guide","Tell me what to do next and why",[{
        "type":STRING,"name":"goal","description":"What are you trying to accomplish?","required":False,
        "choices":[
            {"name":"Best thing to do now","value":"auto"},{"name":"Help the active event","value":"event"},
            {"name":"Daily Contract","value":"daily"},
            {"name":"Earn Seed Coin","value":"seed_coin"},{"name":"Advance New Eridian","value":"society"},
            {"name":"Train an aptitude","value":"aptitude"},{"name":"Gather and craft","value":"crafting"},
            {"name":"Habitat","value":"home"},{"name":"Business","value":"business"},
            {"name":"Fix life needs","value":"life"},{"name":"Weekly Story","value":"story"},
            {"name":"Market","value":"market"}
        ]
    }]),
    cmd("start","Create your citizen or load your existing linked character"),

    cmd("me","View your citizen and personal systems",[{
        "type":STRING,"name":"section","description":"Which part of your citizen?","required":False,
        "choices":[
            {"name":"Overview","value":"overview"},{"name":"Life Needs","value":"life"},
            {"name":"Bonuses","value":"bonuses"},{"name":"Cooldowns","value":"cooldowns"},
            {"name":"Traits","value":"traits"},{"name":"Relationships","value":"relationships"},
            {"name":"Journal","value":"journal"},{"name":"First Days Tutorial","value":"tutorial"},
            {"name":"Titles","value":"titles"},{"name":"Display Style & Color Key","value":"display"}
        ]
    },{
        "type":STRING,"name":"title","description":"Optional unlocked title to equip when section is Titles","required":False,
        "autocomplete":True
    },{
        "type":STRING,"name":"style","description":"Action result detail when section is Display Style","required":False,
        "choices":[{"name":"Compact","value":"compact"},{"name":"Detailed","value":"detailed"}]
    }]),

    cmd("progress","View personal progression",[{
        "type":STRING,"name":"section","description":"Which progression system?","required":False,
        "choices":[
            {"name":"Skills & Level Unlocks","value":"skills"},{"name":"Daily Contract","value":"daily"},
            {"name":"Achievements","value":"achievements"},{"name":"Collection","value":"collection"}
        ]
    }]),

    cmd("inventory","View resources and equipment",[{
        "type":STRING,"name":"section","description":"What do you want to inspect?","required":False,
        "choices":[{"name":"Everything","value":"all"},{"name":"Quality Gear","value":"gear"}]
    }]),

    cmd("job","Choose your profession bonus",[{
        "type":STRING,"name":"job","description":"Profession","required":True,
        "choices":[
            {"name":"Farmer","value":"farmer"},{"name":"Miner","value":"miner"},
            {"name":"Technician","value":"technician"},{"name":"Researcher","value":"researcher"},
            {"name":"Courier","value":"courier"},{"name":"Explorer","value":"explorer"},
            {"name":"Merchant","value":"merchant"}
        ]
    }]),

    cmd("specialize","Choose a permanent Lv.10 aptitude path",[{
        "type":STRING,"name":"path","description":"Specialization path","required":True,
        "choices":[
            {"name":"Agriculture — Crop Geneticist","value":"cultivation:crop_geneticist"},
            {"name":"Agriculture — Hydroponics Operator","value":"cultivation:hydroponics_operator"},
            {"name":"Environmental — Water Systems Specialist","value":"environmental:water_specialist"},
            {"name":"Environmental — Biosphere Warden","value":"environmental:biosphere_warden"},
            {"name":"Extraction — Deep-Core Prospector","value":"extraction:deep_core_prospector"},
            {"name":"Extraction — Rare Materials Surveyor","value":"extraction:rare_materials_surveyor"},
            {"name":"Fabrication — Precision Fabricator","value":"fabrication:precision_fabricator"},
            {"name":"Fabrication — Machine Integrator","value":"fabrication:machine_integrator"},
            {"name":"Infrastructure — Habitat Engineer","value":"infrastructure:habitat_engineer"},
            {"name":"Infrastructure — Utility Architect","value":"infrastructure:utility_architect"},
            {"name":"Research — Siro Analyst","value":"research:siro_analyst"},
            {"name":"Research — Materials Researcher","value":"research:materials_researcher"},
            {"name":"Logistics — Spaceport Coordinator","value":"logistics:spaceport_coordinator"},
            {"name":"Logistics — Delivery Fleet Operator","value":"logistics:delivery_fleet_operator"},
            {"name":"Frontier — Avesta Pathfinder","value":"frontier:pathfinder"},
            {"name":"Frontier — Field Surveyor","value":"frontier:field_surveyor"},
            {"name":"Commerce — Market Broker","value":"commerce:market_broker"},
            {"name":"Commerce — Business Steward","value":"commerce:business_steward"}
        ]
    }]),

    cmd("home","View or upgrade your Habitat",[{
        "type":STRING,"name":"action","description":"Habitat action","required":False,
        "choices":[{"name":"View Habitat","value":"view"},{"name":"Upgrade Habitat","value":"upgrade"}]
    }]),

    cmd("business","Manage your New Eridian business",[{
        "type":STRING,"name":"action","description":"Business action","required":False,
        "choices":[
            {"name":"View Business","value":"view"},{"name":"Start Business","value":"start"},
            {"name":"Work","value":"work"},{"name":"Contract","value":"contract"},
            {"name":"Invest","value":"invest"}
        ]
    },{
        "type":STRING,"name":"name","description":"Business name (only used when starting)","required":False
    }]),

    cmd("make","Build through one clear production tree, from raw inputs to final products",[{
        "type":STRING,"name":"category","description":"Production stage or complete item tree","required":False,
        "choices":[
            {"name":"Production Tree","value":"tree"},
            {"name":"Raw Materials","value":"raw_materials"},
            {"name":"Basic Components","value":"basic_components"},
            {"name":"Advanced Components","value":"advanced_components"},
            {"name":"Final Products","value":"final_products"}
        ]
    },{
        "type":STRING,"name":"recipe","description":"Select a recipe by display name","required":False,"autocomplete":True
    }]),

    cmd("seedindustries","Browse or trade fixed-price materials with Seed Industries",[
        {"type":STRING,"name":"action","description":"Trade materials or manage production orders","required":False,
         "choices":[{"name":"Browse Market","value":"browse"},{"name":"Buy","value":"buy"},{"name":"Sell","value":"sell"},{"name":"View Production Orders","value":"orders"},{"name":"Fulfill Production Order","value":"fulfill"}]},
        {"type":STRING,"name":"item","description":"Material, component, or production-order key","required":False,
         "choices":[
            {"name":"Crops","value":"crops"},{"name":"Ore","value":"ore"},{"name":"Rare Ore","value":"rare_ore"},
            {"name":"Components","value":"components"},{"name":"Cargo","value":"cargo"},{"name":"Biofiber","value":"biofiber"},
            {"name":"Alloy Plate","value":"alloy_plate"},{"name":"Circuit Board","value":"circuit_board"},
            {"name":"Power Cell","value":"power_cell"},{"name":"Sealant","value":"sealant"},
            {"name":"Precision Lens","value":"precision_lens"},
            {"name":"Order: Greenhouse Liner Batch","value":"greenhouse_liners"},{"name":"Order: Maintenance Stock","value":"maintenance_stock"},
            {"name":"Order: Field Ration Lot","value":"field_rations"},{"name":"Order: Laboratory Control Set","value":"lab_controls"},
            {"name":"Order: Water Renewal Kit","value":"water_renewal"},{"name":"Order: Spaceport Power Reserve","value":"spaceport_cells"},
            {"name":"Order: Siro Analysis Package","value":"research_samples"},{"name":"Order: Delivery Fleet Refit","value":"duck_fleet_crates"}
         ]},
        {"type":4,"name":"amount","description":"Quantity (1-25)","required":False}
    ]),

    cmd("world","View shared Avesta and New Eridian information",[{
        "type":STRING,"name":"section","description":"World information","required":False,
        "choices":[
            {"name":"Overview","value":"overview"},{"name":"Conditions & Siro","value":"conditions"},
            {"name":"Daily Bulletin","value":"bulletin"},{"name":"Rumor","value":"rumor"},
            {"name":"Weekly Story","value":"story"},{"name":"Society Project","value":"project"},
            {"name":"Market","value":"market"}
        ]
    }]),

    cmd("society","View New Eridian's shared progression",[{
        "type":STRING,"name":"section","description":"Society information","required":False,
        "choices":[
            {"name":"Overview","value":"overview"},{"name":"Next Tier Progress","value":"progress"},
            {"name":"Contribution Leaderboard","value":"leaderboard"}
        ]
    }]),

    cmd("event","View live or recent society events",[{
        "type":STRING,"name":"section","description":"Event information","required":False,
        "choices":[{"name":"Active Event","value":"status"},{"name":"Recent Event History","value":"history"}]
    }]),

    cmd("district","Choose your New Eridian home district",[{
        "type":STRING,"name":"district","description":"Home district","required":True,
        "choices":[
            {"name":"Residential Ring","value":"residential_ring"},{"name":"Agricultural District","value":"agricultural_district"},
            {"name":"Industrial Ward","value":"industrial_ward"},{"name":"Research Block","value":"research_block"},
            {"name":"Market Concourse","value":"market_concourse"},{"name":"Spaceport Quarter","value":"spaceport_quarter"},
            {"name":"Frontier Edge","value":"frontier_edge"}
        ]
    }]),
    cmd("shift","Choose today's optional shift role",[{
        "type":STRING,"name":"role","description":"Shift role","required":True,
        "choices":[
            {"name":"Off Duty","value":"off_duty"},{"name":"Field Duty","value":"field_duty"},
            {"name":"Spaceport Duty","value":"spaceport_duty"},{"name":"Lab Duty","value":"lab_duty"},
            {"name":"Maintenance","value":"maintenance"},{"name":"Trade Duty","value":"trade_duty"},
            {"name":"Survey Duty","value":"survey_duty"}
        ]
    }]),

    cmd("social","All relationship actions in one place",[
        {"type":STRING,"name":"action","description":"Social activity","required":True,
         "choices":[{"name":"Say Hi","value":"hi"},{"name":"Hang Out","value":"hangout"},{"name":"Mentor","value":"mentor"},
                    {"name":"Duo Walk","value":"duo_walk"},{"name":"Duo Games","value":"duo_games"},{"name":"Duo Research","value":"duo_research"},
                    {"name":"Duo Delivery","value":"duo_delivery"},{"name":"Duo Explore","value":"duo_explore"},{"name":"Use Recreation Set","value":"group_games"}]},
        {"type":STRING,"name":"player","description":"Citizen required for relationship actions","required":False,"autocomplete":True}
    ]),

    cmd("relax","Recover Energy, Morale, and Comfort"),
    cmd("walk","Take a walk for Morale and exploration hobby progress"),
    cmd("games","Play games for Social and Morale"),
    cmd("hobby","Practice a hobby",[{
        "type":STRING,"name":"hobby","description":"Hobby","required":True,
        "choices":[
            {"name":"Gardening","value":"gardening"},{"name":"Exploration","value":"exploration"},
            {"name":"Mechanics","value":"mechanics"},{"name":"Research","value":"research"},
            {"name":"Games","value":"games"},{"name":"Rockwatching","value":"rockwatching"},
            {"name":"Cooking","value":"cooking"},{"name":"Collecting","value":"collecting"},
            {"name":"Trading","value":"trading"},{"name":"Scanning","value":"scanning"}
        ]
    }]),
    cmd("meal","Contribute 1 Crop to the community meal"),
    cmd("eat","Eat a Crop or Ration to restore Nutrition"),
    cmd("sleep","Rest to restore Energy and reduce Siro exposure"),
    cmd("use","Use a crafted life item",[{
        "type":STRING,"name":"item","description":"Life item","required":True,
        "choices":[{"name":"Meal Kit","value":"meal_kit"},{"name":"Recreation Set","value":"recreation_set"},{"name":"Comfort Pack","value":"comfort_pack"}]
    }]),

    cmd("ducks","View fleet bonds or assign a preferred delivery partner",[{
        "type":STRING,"name":"duck","description":"Optional preferred delivery partner","required":False,
        "choices":[{"name":"Hueburt","value":"Hueburt"},{"name":"Colora","value":"Colora"},{"name":"Prisma","value":"Prisma"},{"name":"Pastelle","value":"Pastelle"},{"name":"Asimov","value":"Asimov"}]
    }]),
    cmd("link","Link and merge this Discord citizen with Twitch",[{
        "type":STRING,"name":"code","description":"Six-character code from Twitch !link","required":True
    }]),
    cmd("linklookup","Owner-only linked-account lookup",[{
        "type":STRING,"name":"player","description":"Select a player or enter a provider ID","required":False,"autocomplete":True
    }]),

    cmd("eventstart","Start a society event (moderators only)",[{
        "type":STRING,"name":"event","description":"Event","required":True,
        "choices":[
            {"name":"Siro Bloom","value":"siro"},{"name":"Food Crisis","value":"food"},
            {"name":"Mining Boom","value":"mining"},{"name":"Delivery Surge","value":"delivery"},
            {"name":"Market Boom","value":"market"},{"name":"Water Treatment Emergency","value":"water"},
            {"name":"Infrastructure Breakdown","value":"machine"},{"name":"Spaceport Rush","value":"spaceport"}
        ]
    }]),
    cmd("eventstop","Cancel the active event without penalty (moderators only)"),
    cmd("modlog","View moderator event-control records (moderators only)"),

    # Clear work actions. Redundant legacy Discord commands are intentionally omitted.
    cmd("agriculture","Agriculture hub: tend, harvest, or use Water Filter hydroponics",[
        {"type":STRING,"name":"action","description":"Agriculture activity","required":False,
         "choices":[{"name":"Tend Fields","value":"tend"},{"name":"Harvest Crops","value":"harvest"},{"name":"Irrigate","value":"irrigate"},{"name":"Hydroponics (Water Filter)","value":"hydroponics"}]}
    ]),
    cmd("scan","Environmental survey that supports society Knowledge"),
    cmd("mine","Standard Extraction work that gives personal Ore"),
    cmd("rare","Risky Rare Ore search with higher reward"),
    cmd("research","Research or use a Siro Sampler for advanced field analysis",[
        {"type":STRING,"name":"operation","description":"Research operation","required":False,
         "choices":[{"name":"Standard Research","value":"standard"},{"name":"Field Analysis (Siro Sampler)","value":"field_analysis"}]}
    ]),
    cmd("repair","Repair society infrastructure or personal quality gear",[
        {"type":STRING,"name":"target","description":"What needs repair?","required":False,
         "choices":[{"name":"Society Infrastructure","value":"society"},{"name":"Personal Quality Gear","value":"gear"}]},
        {"type":STRING,"name":"item","description":"Owned gear key when target is Personal Quality Gear","required":False,"autocomplete":True}
    ]),
    cmd("cargo","Prepare 1 personal Cargo"),
    cmd("delivery","Consume 1 Cargo for Logistics work and fleet progress"),
    cmd("spaceport","Standard logistics or a Power Cell expedition",[
        {"type":STRING,"name":"operation","description":"Spaceport operation","required":False,
         "choices":[{"name":"Standard Operations","value":"standard"},{"name":"Expedite (-1 Power Cell)","value":"expedite"}]}
    ]),
    cmd("explore","Scout or use a Sensor for an advanced survey",[
        {"type":STRING,"name":"operation","description":"Frontier operation","required":False,
         "choices":[{"name":"Scout","value":"scout"},{"name":"Advanced Survey (Sensor)","value":"survey"}]}
    ]),
    cmd("market","Market hub: prices, selling, work, or Market Analyzer activity",[
        {"type":STRING,"name":"action","description":"Market action","required":False,
         "choices":[{"name":"View Prices","value":"view"},{"name":"Sell Resources","value":"sell"},{"name":"Commerce Work","value":"work"},{"name":"Analyze Market (Market Analyzer)","value":"analyze"}]},
        {"type":STRING,"name":"resource","description":"Resource to sell","required":False,
         "choices":[{"name":"Crops","value":"crops"},{"name":"Ore","value":"ore"},{"name":"Rare Ore","value":"rare_ore"},{"name":"Components","value":"components"},{"name":"Cargo","value":"cargo"}]},
        {"type":4,"name":"amount","description":"Amount to sell (1-25)","required":False}
    ]),
]
# Flat slash options: selector first, then its relevant optional inputs.
for command in commands:
    for option in command.get("options",[]):
        if option["name"]=="amount":option.update(min_value=1,max_value=25)
        if command["name"]=="business" and option["name"]=="name":option.update(min_length=1,max_length=30)
        if command["name"]=="seedindustries" and option["name"]=="item":
            option.pop("choices",None)
            option.update(autocomplete=True,description="Choose action first: trade material or today's production order")
        if command["name"]=="social" and option["name"]=="action":option["required"]=False
        if command["name"]=="make" and option["name"]=="category":
            order=["basic_components","advanced_components","final_products","raw_materials","tree"]
            option["choices"].sort(key=lambda choice:order.index(choice["value"]))
        if command["name"]=="make" and option["name"]=="recipe":
            option["description"]="Optional: select to craft; with Production Tree, preview only"

for command in commands:
    if command["name"]=="sleep":command["description"]="Fully restore Energy and Comfort to 100; reduce Siro exposure"
    if command["name"]=="eat":command["description"]="Eat: Crop +35 Nutrition, Ration +70; emergency recovery if starving without food"
    if command["name"]=="games":command["description"]="Free solo recovery: +25 Social, +4–8 Morale; no partner needed"
    if command["name"]=="use":
        command["options"][0].pop("choices",None)
        command["options"][0].update(autocomplete=True,description="Select an owned consumable; craft more with /make")

