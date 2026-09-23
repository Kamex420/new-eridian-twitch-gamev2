
"""SEED screenshot vocabulary with original New Eridian v2 task rules.
Stable legacy keys retain existing XP. Branch practice starts at zero.
"""
LABELS = {'cultivation':'Farming','extraction':'Harvesting','infrastructure':'Engineering',
          'environmental':'Processing','fabrication':'Crafting','cooking':'Cooking',
          'medicine':'Medicine','emergency':'Emergency Response','research':'Research',
          'logistics':'Logistics','frontier':'Frontier Operations','commerce':'Commerce'}
HUBS = {'farming':'cultivation','harvesting':'extraction','engineering':'infrastructure',
        'processing':'environmental','crafting':'fabrication','cooking':'cooking',
        'medicine':'medicine','emergency':'emergency'}
TASKS = {}
def task(hub, branch, label, cost=None, output=None, shared=None, society=None, unlock=1, effect=''):
    key='train_'+branch
    TASKS[key]=dict(hub=hub,skill=HUBS[hub],branch=branch,label=label,cost=cost or {},
                    output=output or {},shared=shared or {},society=society or {},unlock=unlock,effect=effect)

task('farming','seed_cultivation','Seed Cultivation',output={'crops':1},society={'food':1})
for key,label,output in [('wood_harvesting','Wood Harvesting',{'wood':2}),('water_collection','Water Collection',{'water':2}),('stone_quarrying','Stone Quarrying',{'stone':2}),('botanical_harvesting','Botanical Harvesting',{'herbs':1,'biofiber':1}),('ore_mining','Ore Mining',{'ore':1})]:
    task('harvesting',key,label,output=output,shared={'ore':1} if key=='ore_mining' else {'water':1} if key=='water_collection' else {})
task('engineering','maintenance_repair','Maintenance & Repair',{'components':1},shared={'infrastructure':1},effect='Adds shared Infrastructure; every 5 adds housing.')
task('engineering','mechanical_engineering','Mechanical Engineering',{'ore':2},output={'components':1},shared={'components':1})
task('engineering','electronics','Electronics',{'components':1,'alloy_plate':1},output={'circuit_board':1},society={'knowledge':1},unlock=3)
for key,label,cost,out,shared,unlock in [
 ('water_treatment','Water Treatment',{'water':1},{},{'water':3},1),
 ('wood_processing','Wood Processing',{'wood':2},{'planks':1},{},1),
 ('food_processing','Food Processing',{'crops':1},{'preserved_food':1},{},1),
 ('stone_processing','Stone Processing',{'stone':2},{'cut_stone':1},{},1),
 ('metalworking','Metalworking',{'ore':2},{'alloy_plate':1},{},1),
 ('textile_processing','Textile Processing',{'biofiber':2},{'cloth':1},{},1),
 ('chemistry','Chemistry',{'herbs':1,'water':1},{'antiseptic':1},{},3),
 ('glassworking','Glassworking',{'stone':2,'components':1},{'precision_lens':1},{},3)]:
    task('processing',key,label,cost,out,shared,unlock=unlock)
task('crafting','masonry','Masonry',{'cut_stone':2},shared={'infrastructure':1},effect='Adds shared Infrastructure; every 5 adds housing.')
task('crafting','pottery','Pottery',{'stone':1,'water':1},output={'storage_jar':1},effect='Storage Jars are used for Food Preservation.')
task('crafting','carpentry','Carpentry',{'planks':2},output={'furniture':1},effect='Furniture is used with /use to restore Comfort and Morale.')
task('crafting','tailoring','Tailoring',{'cloth':2},output={'workwear':1},effect='Workwear is used with /use to restore Comfort and Energy.')
task('cooking','food_preservation','Food Preservation',{'preserved_food':1,'storage_jar':1},output={'ration':2})
task('cooking','advanced_cooking','Advanced Cooking',{'crops':2,'herbs':1},output={'ration':3},unlock=3)
task('medicine','pharmacy','Pharmacy',{'herbs':2,'water':1},output={'medicine':1},shared={'medicines':1})
task('medicine','first_aid','First Aid',{'biofiber':1},society={'reputation':1},effect='Removes your Sore Back status and restores 5 Comfort.')
for branch,label in [('wound_care','Wound Care'),('burn_care','Burn Care'),('cardiology','Cardiology'),('gastroenterology','Gastroenterology'),('infectiology','Infectiology'),('ophthalmology','Ophthalmology'),('physiotherapy','Physiotherapy'),('nephrology','Nephrology'),('neurology','Neurology'),('dentistry','Dentistry'),('traumatology','Traumatology')]:
    task('medicine',branch,label,{'medicine':1,'antiseptic':1},shared={'medicines':2},society={'knowledge':1},unlock=5,effect='Specialist clinic work supplies shared Medicines; lowers your Siro exposure by 5.')
task('emergency','fire_suppression','Fire Suppression',{'water':2},shared={'mood':2},society={'reputation':1},effect='Containment drill; during a Fire Emergency, each success also advances the event.')
task('emergency','fire_safety','Fire Safety',shared={'mood':1},society={'development':1},effect='Prevention inspections; no item required.')
TREE={key:[(t['branch'],t['label'],t['unlock']) for t in TASKS.values() if t['skill']==key] for key in LABELS}
NEW_JOBS={
 'harvester':('Harvester','extraction','train_wood_harvesting'),
 'processor':('Processing Operator','environmental','train_water_treatment'),
 'engineer':('Engineer','infrastructure','train_mechanical_engineering'),
 'artisan':('Artisan','fabrication','train_pottery'),
 'cook':('Cook','cooking','train_food_preservation'),
 'medic':('Medic','medicine','train_first_aid'),
 'pharmacist':('Pharmacist','medicine','train_pharmacy'),
 'firefighter':('Firefighter','emergency','train_fire_suppression'),
 'safety_officer':('Fire Safety Officer','emergency','train_fire_safety'),
}
NEW_SPECS={'cooking':{'preservation_specialist':'Preservation Specialist','head_chef':'Head Chef'},
           'medicine':{'field_medic':'Field Medic','clinical_pharmacist':'Clinical Pharmacist'},
           'emergency':{'fire_warden':'Fire Warden','response_coordinator':'Response Coordinator'}}
LEGACY_BRANCH={'farm':'seed_cultivation','harvest':'seed_cultivation','forage':'seed_cultivation',
 'mine':'ore_mining','rare':'ore_mining','scavenge':'ore_mining','water':'water_treatment','scan':'water_treatment',
 'repair':'maintenance_repair','project':'maintenance_repair','build':'maintenance_repair'}
CRAFT_PRACTICE={'ration':('cooking','food_preservation'),'meal_kit':('cooking','advanced_cooking'),
 'component':('infrastructure','mechanical_engineering'),'circuit_board':('infrastructure','electronics'),
 'alloy_plate':('environmental','metalworking'),'biofiber':('environmental','textile_processing'),
 'precision_lens':('environmental','glassworking'),'sealant':('environmental','chemistry')}
