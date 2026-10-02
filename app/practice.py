"""Lucky finds: work, training, gathering, crafting and repairs sometimes turn up an item from the
same line of work (a Harvester finds Clay, a cook finds Salt, a medic finds Herbs).

Only tasks find things. Life and social actions (eat, sleep, relax, games, hangouts, meals with
friends) and buying or selling never do. A find is one common item, so it adds variety without
replacing gathering or crafting.
"""
import random

ENABLED = True      # tests that check exact item totals switch finds off; tests/test_practice_finds.py turns them on
CHANCE = 0.15       # per successful task
GREAT_RESULT = 0.10 # extra chance when the task went especially well

# The task's own line of work first (its training branch), then its main skill.
BRANCH = {
    'seed_cultivation': ('Pumpkin Seeds', 'Corn', 'Tomato', 'Berries'),
    'wood_harvesting': ('Lumber', 'Nuts', 'Mushroom'),
    'water_collection': ('Murky Water (1000ml)', 'Raw Algae'),
    'stone_quarrying': ('Stone', 'Clay', 'Stone Dust'),
    'botanical_harvesting': ('Herbs', 'Flaxa', 'Berries', 'Golden Cap'),
    'ore_mining': ('Coal', 'Stone', 'Clay', 'Hematite Ore'),
    'maintenance_repair': ('Iron Nails', 'Wood Planks', 'Stone Block'),
    'mechanical_engineering': ('Iron Nails', 'Iron Plate'),
    'electronics': ('Iron Nails', 'Iron Plate'),
    'water_treatment': ('Murky Water (1000ml)', 'Salt', 'Raw Algae'),
    'wood_processing': ('Lumber', 'Wood Planks'),
    'food_processing': ('Pumpkin', 'Berries', 'Salt'),
    'stone_processing': ('Stone', 'Stone Dust', 'Clay'),
    'metalworking': ('Coal', 'Hematite Ore', 'Iron Nails'),
    'textile_processing': ('Flaxa', 'Fabric'),
    'chemistry': ('Salt', 'Herbs', 'Smelly Fungus'),
    'glassworking': ('Stone Dust', 'Coal', 'Stone'),
    'masonry': ('Stone', 'Clay', 'Stone Block'),
    'pottery': ('Clay', 'Murky Water (1000ml)'),
    'carpentry': ('Lumber', 'Wood Planks'),
    'tailoring': ('Flaxa', 'Fabric'),
    'food_preservation': ('Salt', 'Berries', 'Pumpkin'),
    'advanced_cooking': ('Herbs', 'Tomato', 'Corn', 'Salt'),
    'pharmacy': ('Herbs', 'Golden Cap'),
    'first_aid': ('Flaxa', 'Herbs'),
    'fire_suppression': ('Murky Water (1000ml)',),
    'fire_safety': ('Iron Nails', 'Stone Dust'),
}
SKILL = {
    'cultivation': ('Pumpkin Seeds', 'Herbs', 'Corn', 'Tomato', 'Berries', 'Flaxa'),
    'extraction': ('Stone', 'Clay', 'Coal', 'Lumber', 'Herbs', 'Stone Dust'),
    'environmental': ('Murky Water (1000ml)', 'Raw Algae', 'Salt', 'Clay'),
    'fabrication': ('Wood Planks', 'Iron Nails', 'Stone Block', 'Fabric'),
    'infrastructure': ('Iron Nails', 'Iron Plate', 'Wood Planks', 'Stone Block'),
    'research': ('Tube Fungus', 'Web Fungus', 'Golden Cap', 'Hematite Ore', 'Herbs'),
    'logistics': ('Cargo', 'Lumber', 'Iron Nails'),
    'frontier': ('Nuts', 'Mushroom', 'Berries', 'Smelly Fungus', 'Fragile Fungus', 'Stone'),
    'commerce': ('Cargo', 'Salt', 'Berries'),
    'cooking': ('Herbs', 'Berries', 'Corn', 'Tomato', 'Salt'),
    'medicine': ('Herbs', 'Flaxa', 'Golden Cap', 'Antiseptics'),
    'emergency': ('Murky Water (1000ml)', 'Flaxa', 'Herbs'),
}
_KEYS = {}


def key(m, name):
    """The bag key for a find's item name."""
    if name == 'Cargo':
        return 'cargo'
    if name not in _KEYS:
        _KEYS[name] = m.seed_content.find_item(name)
    return _KEYS[name]


def pool(skill, branch=None):
    return BRANCH.get(branch) or SKILL.get(skill) or ()


def find(m, db, p, skill, branch=None):
    """After a task succeeds: sometimes add one related item to the bag. Returns the line to show, or ''."""
    items = pool(skill, branch)
    if not ENABLED or not items:
        return ''
    chance = CHANCE + (GREAT_RESULT if getattr(p, '_practice_quality', 1.0) > 1.0 else 0)
    if random.random() >= chance:
        return ''
    item = key(m, random.choice(items))
    m.material_change(db, p, item, 1)
    return f"🎁 Lucky find ({m.SKILL_LABELS.get(skill, skill)}): +1 {m.resource_name(item)}"
