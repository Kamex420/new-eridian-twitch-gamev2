
"""Shared Discord command catalog: registration and runtime validation use this file.

Dropdown labels follow one pattern everywhere: what you get, what it costs in
needs, and what it requires. Work labels are generated from the same yield and
need tables the game uses, so a label can never disagree with the result.
"""
from . import task_yields as _yields
from .needs import SLEEP_COOLDOWN_SECONDS as _SLEEP, duration_text as _duration
W=_yields.choice_name

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

    cmd("make","Workbench: pick a category, then a recipe (easiest first); preview, craft or queue it",[{
        "type":STRING,"name":"category","description":"Recipe category; lists run from easiest to most complex","required":False,
        "choices":[]
    },{
        "type":STRING,"name":"recipe","description":"Recipe (✅ ready ❌ missing 🔑 unlock 🔒 locked); shows a preview first","required":False,"autocomplete":True
    },{
        "type":STRING,"name":"action","description":"What to do with the selected recipe (default: Preview)","required":False,
        "choices":[{"name":"Preview requirements (spends nothing)","value":"preview"},{"name":"Craft 1 batch now","value":"craft"},{"name":"Queue batches (set Count)","value":"queue"}]
    },{
        "type":4,"name":"count","description":"Batches to queue, 1–10 (Queue only)","required":False,"min_value":1,"max_value":10
    },{
        "type":STRING,"name":"station","description":"Optional: only show recipes for one workstation","required":False,"autocomplete":True
    },{
        "type":4,"name":"page","description":"Page of the category (10 recipes per page)","required":False,"min_value":1,"max_value":1000
    }]),

    cmd("seedindustries","Browse or trade fixed-price materials with Seed Industries",[
        {"type":STRING,"name":"action","description":"Trade materials or manage production orders","required":False,
         "choices":[{"name":"Browse Market","value":"browse"},{"name":"Buy","value":"buy"},{"name":"Sell","value":"sell"},{"name":"View Production Orders","value":"orders"},{"name":"Fulfill Production Order","value":"fulfill"}]},
        {"type":STRING,"name":"item","description":"Material, component, or production-order key","required":False,
         "choices":[
            {"name":"Crops","value":"crops"},{"name":"Hematite Ore","value":"ore"},{"name":"Argentite Ore","value":"rare_ore"},
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
    cmd("meal","Contribute 1 Pumpkin to the community meal"),
    cmd("eat","Eat food to restore Nutrition"),
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
    cmd("farm","Farming hub: tend, harvest, irrigate, or run hydroponics with a Small Water Filter",[
        {"type":STRING,"name":"action","description":"Farming activity","required":False,
         "choices":[{"name":W("Tend Fields","farm"),"value":"tend"},{"name":W("Harvest Pumpkins","harvest"),"value":"harvest"},{"name":W("Irrigate","water"),"value":"irrigate"},{"name":W("Hydroponics","water","hydroponics","needs Small Water Filter"),"value":"hydroponics"}]}
    ]),
    cmd("scan","Environmental survey that supports society Knowledge"),
    cmd("mine","Standard Extraction work that gives personal Hematite Ore"),
    cmd("rare","Prospect a rare ore: Harvesting Lv3, three actions per ore, 20-second cooldown"),
    cmd("research","Research or use a Siro Sampler for advanced field analysis",[
        {"type":STRING,"name":"operation","description":"Research operation","required":False,
         "choices":[{"name":W("Standard Research","research"),"value":"standard"},{"name":W("Field Analysis","research","field_analysis","needs Siro Sampler"),"value":"field_analysis"}]}
    ]),
    cmd("repair","Repair society infrastructure or personal quality gear",[
        {"type":STRING,"name":"target","description":"What needs repair?","required":False,
         "choices":[{"name":"Society Infrastructure","value":"society"},{"name":"Personal Quality Gear","value":"gear"}]},
        {"type":STRING,"name":"item","description":"Owned gear (Personal Quality Gear): condition and Iron Nails needed","required":False,"autocomplete":True}
    ]),
    cmd("cargo","Prepare 1 personal Cargo"),
    cmd("delivery","Consume 1 Cargo for Logistics work and fleet progress"),
    cmd("spaceport","Standard logistics or a Power Cell expedition",[
        {"type":STRING,"name":"operation","description":"Spaceport operation","required":False,
         "choices":[{"name":W("Standard","spaceport"),"value":"standard"},{"name":W("Expedite","spaceport","expedite","uses 1 Power Cell"),"value":"expedite"}]}
    ]),
    cmd("explore","Scout, or run an Advanced Survey with a Resource Scanner",[
        {"type":STRING,"name":"operation","description":"Frontier operation","required":False,
         "choices":[{"name":W("Scout","explore"),"value":"scout"},{"name":W("Survey","survey","","needs Resource Scanner"),"value":"survey"}]}
    ]),
    cmd("market","Market hub: today's demand, commerce work, or Market Analyzer activity",[
        {"type":STRING,"name":"action","description":"Market action","required":False,
         "choices":[{"name":"Today's demand (spends nothing)","value":"view"},{"name":W("Commerce","market"),"value":"work"},{"name":W("Analyze","market","analyze","needs Market Analyzer"),"value":"analyze"}]}
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

for command in commands:
    if command["name"]=="sleep":command["description"]=f"Fully restore Energy and Comfort to 100 (once every {_duration(_SLEEP)}); reduce Siro exposure"
    if command["name"]=="relax":command["description"]="Recover +25 Energy, +20 Comfort, +4–7 Morale (30s cooldown)"
    if command["name"]=="games":command["description"]="Free solo recovery: +25 Social, +4–8 Morale; no partner needed"
    if command["name"]=="use":
        command["options"][0].pop("choices",None)
        command["options"][0].update(autocomplete=True,description="Select an owned consumable; craft more with /make")


# Inventory-first commands: bare commands browse; explicit selections perform work.
for command in commands:
    if command["name"]=="eat":
        command["description"]="View your food and quantities, then choose one item to eat"
        command["options"]=[{"type":STRING,"name":"food","description":"Owned food, strongest first, with its exact effect; blank = food menu","required":False,"autocomplete":True}]
    if command["name"]=="use":
        command["description"]="View usable items and quantities, or choose one to consume"
        command["options"][0]["required"]=False
    if command["name"] in {"delivery","meal"}:
        label,value=("Send Delivery (uses 1 Cargo on success)","send") if command["name"]=="delivery" else ("Share a Pumpkin (+25 Nutrition, +10 Social)","share")
        command["options"]=[{"type":STRING,"name":"action","description":"View supplies first, or choose an action to spend the listed item","required":False,"choices":[{"name":"View Supplies","value":"view"},{"name":label,"value":value}]}]

# SEED-aligned skills share one training menu; no duplicate work commands.
from .seed_skills import LABELS, HUBS, NEW_JOBS, NEW_SPECS
for command in commands:
    if command['name']=='job':
        command['options'][0]['choices'] += [{'name':label,'value':key} for key,(label,skill,task) in NEW_JOBS.items()]
    if command['name']=='specialize':
        for choice in command['options'][0]['choices']:
            skill=choice['value'].split(':')[0]
            choice['name']=LABELS[skill]+' — '+choice['name'].split(' — ',1)[-1]
        for skill,paths in NEW_SPECS.items():
            command['options'][0]['choices'] += [{'name':LABELS[skill]+' — '+label,'value':skill+':'+key} for key,label in paths.items()]
    if command['name']=='eventstart':
        command['options'][0]['choices'] += [{'name':'Fire Emergency','value':'fire'},{'name':'Clinic Supply Shortage','value':'clinic'}]
    if command['name']=='farm':command['description']='Farming: tend fields, harvest Pumpkins, irrigate, or run hydroponics'
    if command['name']=='mine':command['description']='Harvesting: mine Hematite Ore and shared ore'
    if command['name']=='scan':command['description']='Processing survey that supports society Knowledge'
    if command['name']=='repair':command['description']='Engineering: repair society infrastructure or personal gear'
commands.append(cmd('training','Browse skills, branch levels, supplies and jobs; select Task to work',[
    {'type':STRING,'name':'skill','description':'Choose a main skill to view its branches and requirements','required':False,
     'choices':[{'name':LABELS[key],'value':hub} for hub,key in HUBS.items()]},
    {'type':STRING,'name':'task','description':'Choose Skill first; each task shows status, owned/needed items and output','required':False,'autocomplete':True}
]))

for command in commands:
    if command['name']=='shift':
        command['options'][0]['choices'] += [{'name':label,'value':key} for key,label in [('kitchen_duty','Kitchen Duty'),('clinic_duty','Clinic Duty'),('safety_duty','Safety Duty')]]
    if command['name']=='farm':command['options'][0]['description']='Farming activity'

commands.append(cmd('holiday','See active holidays and when the next holiday event starts'))

# Searchable source catalog; selectors browse until an explicit work item is chosen.
commands.append(cmd('catalog','Find items, recipes, ingredients and your quantities',[
    {'type':STRING,'name':'item','description':'Search an item to inspect its recipes and gathering sources','required':False,'autocomplete':True},
    {'type':4,'name':'page','description':'Page of items, 12 per page','required':False,'min_value':1,'max_value':1000},
    {'type':5,'name':'owned','description':'Show only items you own','required':False}
]))
commands.append(cmd('gather','Collect natural materials for cooking, processing and crafting',[
    {'type':STRING,'name':'resource','description':'Type a material name to search all resources; selecting it gathers it','required':False,'autocomplete':True},
    {'type':4,'name':'page','description':'Browse every raw resource; leave Resource blank to view only','required':False,'min_value':1,'max_value':1000}
]))

# Shared item families: all catalog items have one category; full lists use pages.
from .seed_content import category_choices
for command in commands:
    if command['name'] in {'catalog','use'}:
        command['options'].insert(0,{'type':STRING,'name':'category','description':'Choose a category; Page shows every item across numbered pages','required':False,'choices':category_choices()})
    if command['name']=='use':
        command['description']='Browse owned items and exact effects; consume supplies or use durable equipment'
        command['options'].append({'type':4,'name':'page','description':'Page of owned usable items','required':False,'min_value':1,'max_value':1000})
        for opt in command['options']:
            if opt['name']=='item':opt['description']='Owned item; its description shows what is consumed and what is kept'
    if command['name']=='catalog':command['description']='Browse ALL items by category and page; inspect their uses and recipes'
    if command['name']=='make':
        from .workbench import CATEGORIES as WORKBENCH_CATEGORIES
        next(o for o in command['options'] if o['name']=='category')['choices']=[{'name':f'{emoji} {label}','value':key} for key,emoji,label,_ in WORKBENCH_CATEGORIES]


commands.append(cmd('workshop','View recipe tiers and unlock access to a named crafting station',[
    {'type':STRING,'name':'action','description':'View progress or purchase permanent station access','required':False,'choices':[{'name':'View Workshops','value':'view'},{'name':'Unlock Station','value':'unlock'}]},
    {'type':STRING,'name':'station','description':'Workstation: ✅ ready · 🔑 one-time fee · 🔒 tier lock','required':False,'autocomplete':True},
    {'type':4,'name':'page','description':'Page of all stations','required':False,'min_value':1,'max_value':1000}
]))
for command in commands:
    if command['name']=='seedindustries':
        command['options'] += [
            {'type':STRING,'name':'category','description':'Filter starter stock; leave All for every item','required':False,'choices':[{'name':label,'value':value} for value,label in [('all','All Supplies'),('legacy','General Materials & Parts'),('seed','Starter Supplies'),('training','Training Supplies'),('rare','Rare Ores')]]},
            {'type':4,'name':'page','description':'Market page; browse only','required':False,'min_value':1,'max_value':1000}]

for command in commands:
    if command['name']=='seedindustries':
        next(o for o in command['options'] if o['name']=='action')['choices'].append({'name':'Starter Routes by Branch','value':'starters'})


for command in commands:
    if command['name']=='mine':
        command['description']='Choose ore or Coal, inspect requirements, and queue up to 10 mining attempts'
        command['options']=[
            {'type':STRING,'name':'ore','description':'Ore or Coal (shows owned, costs and locks); View Requirements spends nothing','required':False,'autocomplete':True},
            {'type':STRING,'name':'action','description':'Viewing requirements spends nothing','required':False,'choices':[{'name':'View Requirements','value':'view'},{'name':'Mine','value':'mine'}]},
            {'type':4,'name':'count','description':'Attempts (1–10); rare ores need three successful prospecting attempts per ore','required':False,'min_value':1,'max_value':10}]
commands.append(cmd('queue','View, start or cancel one task queue; maximum 10 attempts of one task type',[
    {'type':STRING,'name':'action','description':'Queue automatically pauses and resumes as requirements change','required':False,'choices':[{'name':'View','value':'view'},{'name':'Start','value':'start'},{'name':'Cancel','value':'cancel'}]},
    {'type':STRING,'name':'task','description':'One task, resource or recipe for the whole queue (type to search)','required':False,'autocomplete':True},
    {'type':4,'name':'count','description':'Number of attempts, including failures; blocked attempts do not count','required':False,'min_value':1,'max_value':10}]))

# Choice labels expose base yields; bonuses remain additional rewards.
for command in commands:
    if command['name'] in {'farm','research','spaceport','explore','market'}:
        command['options'][0]['description']='Choose work: yield per success · Energy and Comfort spent per attempt'
    if command['name']=='business':
        for option in command.get('options',[]):
            if option['name']=='action':
                for choice in option.get('choices',[]):
                    if choice['value']=='work':choice['name']=W('Work','business','','business required')
                    if choice['value']=='contract':choice['name']=W('Contract','businesscontract','','business required')

# Quality-of-life: one status view, personal settings, and options that connect
# favourites, Ready now, fetching ingredients, follow-up queues and bulk selling.
commands.append(cmd('status','Needs, queue, cooldowns, ready recipes and your next step in one view'))
commands.append(cmd('seedling','Your Seedling: mood, thoughts, what it is doing, its daily schedule and diary',[
    {'type':STRING,'name':'section','description':'What to show','required':False,
     'choices':[{'name':'Overview: mood, thought and what it is doing','value':'overview'},{'name':'Diary: what it did while you were away','value':'diary'}]},
    {'type':STRING,'name':'schedule','description':'Daily schedule across Morning, Day, Evening and Night','required':False,
     'choices':[{'name':'Balanced: work the day, friends in the evening','value':'balanced'},{'name':'Workaholic: work dawn to dusk','value':'workaholic'},
                {'name':'Night owl: sleep mornings, work nights','value':'night_owl'},{'name':'Socialite: a little work, a lot of company','value':'socialite'},
                {'name':'Homebody: mornings and evenings for hobbies','value':'homebody'}]},
    {'type':STRING,'name':'autonomy','description':'Let your Seedling live its schedule while you are away','required':False,
     'choices':[{'name':'On','value':'on'},{'name':'Off','value':'off'}]}]))
commands.append(cmd('find','Search recipes, items, buttons and the handbook for anything',[
    {'type':STRING,'name':'query','description':'A word or name, e.g. campfire, lumber or comfort','required':True,'max_length':60}]))
commands.append(cmd('settings','Queue alerts and auto-recovery; leave options blank to view them',[
    {'type':STRING,'name':'alerts','description':'How queue alerts reach you','required':False,
     'choices':[{'name':'Direct message (default)','value':'dm'},{'name':'Channel @mention (everyone sees it)','value':'mention'},
                {'name':'Private: only you see it, at your next command','value':'private'},
                {'name':'Quiet: finish/stop only, no pause alerts','value':'quiet'},{'name':'Off: check /status','value':'off'}]},
    {'type':STRING,'name':'autorecover','description':'Paused queues try relax, games, cheapest food, comfort items or sleep','required':False,
     'choices':[{'name':'On','value':'on'},{'name':'Off','value':'off'}]},
    {'type':STRING,'name':'popups','description':'Private "only you can see this" notifications at your next command','required':False,
     'choices':[{'name':'Important: queue results, pauses and warnings','value':'important'},{'name':'All: also tips and milestones','value':'all'},
                {'name':'Off: keep them in /menu → Notifications','value':'off'}]},
    {'type':STRING,'name':'feed','description':'Show your gathering, crafting, level ups and trophies in the channel activity feed','required':False,
     'choices':[{'name':'On: show my activity','value':'on'},{'name':'Off: keep my activity private','value':'off'}]}]))
for command in commands:
    if command['name']=='make':
        from .workbench import VIEWS
        category=next(o for o in command['options'] if o['name']=='category')
        category['choices']=[{'name':f'{emoji} {label}','value':key} for key,emoji,label,_ in VIEWS]+category['choices']
        action=next(o for o in command['options'] if o['name']=='action')
        action['choices']+=[{'name':'Fetch missing ingredients (plan first)','value':'fetch'},{'name':'Favourite / unfavourite','value':'favorite'}]
        next(o for o in command['options'] if o['name']=='count')['description']='Batches to queue or fetch for, 1–10'
    if command['name']=='queue':
        action=command['options'][0]
        action['choices']+=[{'name':'Queue next (runs after the current queue)','value':'next'},{'name':'Repeat last queue','value':'repeat'},{'name':'Clear next queue','value':'clearnext'}]
    if command['name']=='seedindustries':
        next(o for o in command['options'] if o['name']=='action')['choices']+=[
            {'name':'Sell all of one item','value':'sellall'},{'name':'Clear out surplus materials (preview first)','value':'clearout'}]
    if command['name']=='inventory':
        command['options']+=[
            {'type':STRING,'name':'search','description':'Find items by name or category','required':False},
            {'type':STRING,'name':'sort','description':'Order the list','required':False,
             'choices':[{'name':'Quantity','value':'quantity'},{'name':'Name','value':'name'},{'name':'Sale value','value':'value'},{'name':'Category','value':'category'}]},
            {'type':STRING,'name':'show','description':'Filter the list','required':False,
             'choices':[{'name':'Everything','value':'all'},{'name':'Used in recipes ready now','value':'ready'},
                        {'name':'Used by favourites','value':'favorites'},{'name':'Sellable','value':'sellable'}]},
            {'type':4,'name':'page','description':'Page of the list (15 per page)','required':False,'min_value':1,'max_value':1000}]

# ---------------------------------------------------------------- simplified menu
# Related commands are grouped so the Discord / menu stays short. The retired
# commands keep their handlers: a grouped command is translated to the original
# command and options before it runs (see LEGACY_ROUTES in main), so rules,
# receipts and cooldowns are unchanged. Their definitions stay available for
# validating those translated calls, but are no longer registered with Discord.
RETIRED={'relax','sleep','eat','games','walk','hobby','meal',
         'farm','scan','rare','research','cargo','delivery','spaceport','explore',
         'eventstart','eventstop','modlog','linklookup','society','event','holiday','progress'}
_by_name={c['name']:c for c in commands}
LIFE_ACTIONS=[('Relax','relax'),('Sleep','sleep'),('Eat','eat'),('Games','games'),('Walk','walk'),
              ('Hobby','hobby'),('Share meal','meal'),('Recover','recover')]
WORK_TASKS=[(W('Tend Fields','farm'),'farm_tend'),(W('Harvest Pumpkins','harvest'),'farm_harvest'),(W('Irrigate','water'),'farm_irrigate'),
            (W('Hydroponics','water','hydroponics','needs Small Water Filter'),'farm_hydroponics'),(W('Scan','scan'),'scan'),
            ('Rare prospecting · Harvesting Lv3','rare'),(W('Standard Research','research'),'research'),
            (W('Field Analysis','research','field_analysis','needs Siro Sampler'),'field_analysis'),(W('Prepare Cargo','cargo'),'cargo'),
            (W('Delivery','delivery','','uses 1 Cargo'),'delivery'),(W('Spaceport','spaceport'),'spaceport'),
            (W('Expedite Spaceport','spaceport','expedite','uses 1 Power Cell'),'expedite'),(W('Scout','explore'),'scout'),
            (W('Survey','survey','','needs Resource Scanner'),'survey')]
MOD_ACTIONS=[('Start event','eventstart'),('Stop event','eventstop'),('Moderator log','modlog'),('Linked-account lookup (owner)','linklookup'),('Post guide panels here','guidepanels'),('Post game button panel here','menupanel')]
MOD_ACTIONS+=[('Stream challenge: start','challengestart'),('Stream challenge: stop','challengestop'),('Stream is live: on','liveon'),
              ('Stream is live: off','liveoff'),('Stream live: automatic','liveauto'),('Weekly recap: preview','recappreview'),('Weekly recap: post now','recappost'),
              ('Activity feed: post here','feedhere'),('Activity feed: off','feedoff')]
from .live_events import CHALLENGES as _CHALLENGES
from . import looks as _looks
PROGRESS_SECTIONS=[('Skills & Level Unlocks','skills'),('Daily Contract','daily'),('Achievements','achievements'),('Collection','collection')]
WORLD_SECTIONS=[('Society Overview','society'),('Society Next Tier','society_progress'),('Contribution Leaderboard','leaderboard'),
                ('Active Event','event'),('Event History','event_history'),('Holidays & Festival Foods','holidays')]

new_commands=[
    cmd('life','Relax, sleep, eat, play games, walk, hobbies, meals or one-press recovery',[
        {'type':STRING,'name':'action','description':'Relax +25 Energy/+20 Comfort · Sleep fills both · Games +25 Social · blank shows needs','required':False,'choices':[{'name':n,'value':v} for n,v in LIFE_ACTIONS]},
        {'type':STRING,'name':'food','description':'Eat: owned food, strongest first, with its exact effect','required':False,'autocomplete':True},
        dict(_by_name['hobby']['options'][0],required=False,description='Hobby: which one to practice')]),
    cmd('work','Farming, research, logistics and frontier work in one list',[
        {'type':STRING,'name':'task','description':'Yield per success · Energy and Comfort per attempt; blank lists every skill','required':False,
         'choices':[{'name':n[:100],'value':v} for n,v in WORK_TASKS]}]),
    cmd('mod','Moderator and owner tools: events, moderator log, linked accounts',[
        {'type':STRING,'name':'action','description':'Moderator tool','required':True,'choices':[{'name':n,'value':v} for n,v in MOD_ACTIONS]},
        dict(_by_name['eventstart']['options'][0],required=False,description='Start event: which event'),
        dict(_by_name['linklookup']['options'][0],description='Linked-account lookup: player or provider ID'),
        {'type':STRING,'name':'challenge','description':'Start stream challenge: which one (blank = random)','required':False,
         'choices':[{'name':f'{v[0]} {v[1]}','value':k} for k,v in _CHALLENGES.items()]}]),
    cmd('vote','Colony vote: what New Eridian builds or celebrates next (blank shows the ballot)',[
        {'type':4,'name':'choice','description':'Your vote: 1, 2 or 3 (you can change it until the day ends)','required':False,'min_value':1,'max_value':3}]),
    cmd('season','This season: your points and rank, the leaderboard, rewards, story and hats',[
        {'type':STRING,'name':'section','description':'What to show','required':False,
         'choices':[{'name':'Overview: your points, rank and next reward','value':'overview'},{'name':'Leaderboard','value':'top'},
                    {'name':'Rewards: titles, hats and milestones','value':'rewards'},{'name':'Story so far','value':'story'},{'name':'My hats','value':'hats'}]},
        {'type':STRING,'name':'hat','description':'Wear a cosmetic hat on the stream map (job = your job hat)','required':False,'max_length':30}]),
    cmd('challenge','The live stream challenge: goal, time left, top helpers and how to help'),
    cmd('customize','Your Seedling: skin tone, hair, outfit, accessory, attitude and catchphrase (blank shows its look)',
        [{'type':STRING,'name':field,'description':description,'required':False,
          'choices':[{'name':n,'value':v} for n,v in _looks.choices(field)]}
         for field,description in [('skin','Skin tone'),('hair','Hair style'),('hair_colour','Hair colour'),('outfit','Outfit colour (or follow its mood)'),
                                   ('accessory','Accessory'),('headwear','Job hat, or no hat to show your hair'),('attitude','Attitude: how it talks on stream'),('catchphrase','A catchphrase it says now and then')]]),
    cmd('trophies','Collections and trophies: what you have, what is close, and your pinned badge',[
        {'type':STRING,'name':'group','description':'Show one group in full','required':False,
         'choices':[{'name':'Collections','value':'collections'},{'name':'Crafting','value':'crafting'},{'name':'Festivals','value':'festivals'},
                    {'name':'Colony','value':'colony'},{'name':'Stream','value':'stream'},{'name':'Seasons','value':'seasons'}]},
        {'type':STRING,'name':'badge','description':'Pin a trophy badge next to your name on the stream map','required':False,'max_length':40}]),
]
for command in commands:
    if command['name']=='me':
        command['options'][0]['choices']+=[{'name':n,'value':v} for n,v in PROGRESS_SECTIONS]
        command['description']='Your citizen: profile, needs, progress, skills, achievements and more'
    if command['name']=='world':
        command['options'][0]['choices']+=[{'name':n,'value':v} for n,v in WORLD_SECTIONS]
        command['description']='Avesta and New Eridian: society, events, holidays, market and news'
new_commands.insert(0,cmd('menu','Every area of the game as buttons: pick one, then pick what to do'))
legacy_commands=[c for c in commands if c['name'] in RETIRED]
commands=[c for c in commands if c['name'] not in RETIRED]+new_commands
