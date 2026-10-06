

from datetime import date, datetime, timedelta, timezone
import hashlib

HOLIDAY_WINDOWS = [
    ("New Year", 1, 1, "🎆"),
    ("Valentine's Day", 2, 14, "💝"),
    ("Memorial Day", 5, 31, "🇺🇸"),
    ("Father's Day", 6, 21, "👔"),
    ("Independence Day", 7, 4, "🇺🇸"),
    ("Labor Day", 9, 1, "🛠️"),
    ("Halloween", 10, 31, "🎃"),
    ("Thanksgiving", 11, 27, "🦃"),
    ("Christmas", 12, 25, "🎄"),
]

DAY_TEXT = {
    "New Year": [
        "The colony rings the new year with fireworks and hopeful new plans.",
        "A sparkling midnight toast leaves the whole settlement buzzing.",
        "The skies glow with celebratory lights and fresh promises.",
    ],
    "Valentine's Day": [
        "Cupid's lanterns drift through the market square today.",
        "The colony is full of sweet gifts and warm compliments.",
        "A little romance fills the air across the settlement.",
    ],
    "Memorial Day": [
        "The community pauses to honor the past and celebrate the future.",
        "Flags are raised with pride and a solemn sense of gratitude.",
        "A respectful tone settles over the settlement as voices gather.",
    ],
    "Father's Day": [
        "The colony gives thanks to the builders, mentors, and steady hands.",
        "Strong examples and wise guidance are celebrated across the day.",
        "A proud, warm mood settles into the homes and workshops.",
    ],
    "Independence Day": [
        "Fireworks crackle over the settlement while the market hums with pride.",
        "The colony celebrates freedom, courage, and bold new beginnings.",
        "Red, white, and bright energy ripples through every district.",
    ],
    "Labor Day": [
        "The worker’s pride of the colony is on full display today.",
        "Every workshop shines with gratitude for a hard day’s work.",
        "The settlement celebrates the effort behind every achievement.",
    ],
    "Halloween": [
        "The settlement is full of lantern glow, strange rumors, and cheerful chaos.",
        "A playful chill runs through the docks and market streets.",
        "Nightfall brings pumpkins, spooky laughs, and hidden treasure.",
    ],
    "Thanksgiving": [
        "Warm food, shared thanks, and a grateful colony fill the air.",
        "Friends and neighbors gather to celebrate abundance and kindness.",
        "The settlement is full of hearty meals and grateful hearts.",
    ],
    "Christmas": [
        "The colony glows with ornaments, gifts, and a cheerful winter mood.",
        "Holiday lights brighten the streets and warm the hearts of everyone.",
        "The settlement shares music, joy, and generous spirit today.",
    ],
}

SPECIAL_RECIPES = {
    "New Year": ["firework tea", "midnight pastry", "spark cider"],
    "Valentine's Day": ["rose tart", "sweet berry cake", "heart tea"],
    "Memorial Day": ["patriotic stew", "field lunch", "memorial loaf"],
    "Father's Day": ["grill basket", "mentor roast", "campfire pie"],
    "Independence Day": ["patriot pie", "spark grill", "red-white-blue jam"],
    "Labor Day": ["builder stew", "overtime pie", "welders’ bread"],
    "Halloween": ["pumpkin bites", "moon tart", "candy herb mix"],
    "Thanksgiving": ["harvest feast", "gourd roast", "gratitude pie"],
    "Christmas": ["holiday spiced tea", "winter roast", "gift cookie"],
}


# Festival foods are real catalog items: crafted at the free Survival Workbench
# from gathered ingredients, but only while their holiday's festival runs. The
# items themselves never expire; they can be eaten, sold or stored all year.
# (name, description, ingredients by catalog name, Food value, Comfort, Morale)
FESTIVAL_FOODS = {
    "New Year": [
        ("Firework Tea", "Herbal tea with a crackle of berry sweetness, brewed for the midnight toast.", {"Herbs": 2, "Berries": 1}, 0.4, 10, 5),
        ("Midnight Pastry", "A flaky corn pastry filled with berries, shared as the year turns.", {"Corn": 2, "Berries": 2}, 0.7, 12, 6),
        ("Spark Cider", "Fizzy pressed-berry cider that tastes like a fresh start.", {"Berries": 3, "Herbs": 1}, 0.5, 10, 6),
    ],
    "Valentine's Day": [
        ("Rose Tart", "A delicate berry tart with a nutty crust, baked to share.", {"Berries": 2, "Corn": 1, "Nuts": 1}, 0.6, 12, 6),
        ("Sweet Berry Cake", "Soft corn cake layered with sweet berries.", {"Berries": 3, "Corn": 2}, 0.8, 14, 7),
        ("Heart Tea", "A warming herb tea said to steady nervous hearts.", {"Herbs": 2, "Berries": 1}, 0.4, 10, 5),
    ],
    "Memorial Day": [
        ("Patriotic Stew", "A hearty tomato, corn and mushroom stew served to every table.", {"Tomato": 2, "Corn": 1, "Mushroom": 1}, 0.8, 12, 6),
        ("Field Lunch", "A simple packed lunch for a quiet day of remembrance.", {"Corn": 1, "Tomato": 1, "Nuts": 1}, 0.6, 10, 5),
        ("Memorial Loaf", "Dense corn bread baked from an old settlement recipe.", {"Corn": 3, "Nuts": 1}, 0.7, 10, 6),
    ],
    "Father's Day": [
        ("Grill Basket", "Charred corn, mushrooms and tomatoes, straight off the grill.", {"Corn": 2, "Mushroom": 2, "Tomato": 1}, 0.9, 14, 7),
        ("Mentor Roast", "Herb-roasted pumpkin and mushroom, a dish for thanking a mentor.", {"Pumpkin": 2, "Mushroom": 1, "Herbs": 1}, 0.8, 12, 6),
        ("Campfire Pie", "Berry pie with a rustic corn crust, baked in the embers.", {"Berries": 2, "Corn": 2, "Nuts": 1}, 0.8, 12, 6),
    ],
    "Independence Day": [
        ("Patriot Pie", "A bright berry pie for fireworks night.", {"Berries": 2, "Corn": 2}, 0.7, 12, 6),
        ("Spark Grill", "Grilled corn and tomato skewers with a herb glaze.", {"Corn": 2, "Tomato": 2, "Herbs": 1}, 0.8, 12, 6),
        ("Red-White-Blue Jam", "Three-layer berry jam, sweet enough for the whole parade.", {"Berries": 3}, 0.5, 10, 6),
    ],
    "Labor Day": [
        ("Builder Stew", "A filling pumpkin stew that keeps crews working.", {"Pumpkin": 2, "Mushroom": 1, "Tomato": 1}, 0.8, 12, 6),
        ("Overtime Pie", "Pumpkin pie with a nut crust, saved for the last shift.", {"Pumpkin": 2, "Corn": 1, "Nuts": 1}, 0.8, 12, 6),
        ("Welders' Bread", "Herbed corn bread tough enough to survive a toolbox.", {"Corn": 3, "Herbs": 1}, 0.7, 10, 5),
    ],
    "Halloween": [
        ("Pumpkin Bites", "Roasted pumpkin nuggets rolled in crushed nuts.", {"Pumpkin": 2, "Nuts": 1}, 0.6, 10, 6),
        ("Moon Tart", "A pale pumpkin and berry tart with a crescent crust.", {"Pumpkin": 1, "Berries": 2, "Corn": 1}, 0.7, 12, 7),
        ("Candy Herb Mix", "Candied herbs and dried berries handed out at every door.", {"Herbs": 2, "Berries": 2}, 0.5, 10, 7),
    ],
    "Thanksgiving": [
        ("Harvest Feast", "A full table: pumpkin, corn, tomato and mushroom, meant for sharing.", {"Pumpkin": 2, "Corn": 2, "Tomato": 1, "Mushroom": 1}, 1.0, 18, 9),
        ("Gourd Roast", "Slow-roasted pumpkin with herbs.", {"Pumpkin": 3, "Herbs": 1}, 0.8, 12, 6),
        ("Gratitude Pie", "Pumpkin and berry pie baked to say thank you.", {"Pumpkin": 2, "Berries": 1, "Corn": 1}, 0.8, 12, 7),
    ],
    "Christmas": [
        ("Holiday Spiced Tea", "Warm herb tea with berry spice for long winter shifts.", {"Herbs": 2, "Berries": 1}, 0.4, 12, 5),
        ("Winter Roast", "Pumpkin and mushroom roast with herbs, the centrepiece of the feast.", {"Pumpkin": 2, "Mushroom": 2, "Herbs": 1}, 0.9, 16, 8),
        ("Gift Cookie", "Nutty corn cookies wrapped as gifts for neighbours.", {"Corn": 2, "Nuts": 1, "Berries": 1}, 0.6, 12, 7),
    ],
}


# Festival keepsakes: decorations and costumes crafted at the Survival Workbench while their festival runs, from everyday
# materials. (name, description, inputs or a list of alternative inputs, kind) — kind 'decor' (use it: +Morale, +Social,
# kept) or 'clothing' (wear it: +Comfort, +Morale, kept). A holiday's Feast trophy (and its hat) needs every food and keepsake.
FESTIVAL_CRAFTS = {
    "New Year": [
        ("Confetti Popper", "A paper tube of bright confetti, saved for the stroke of midnight.", {"Flaxa": 2, "Berries": 1}, "decor"),
        ("Sparkler Crown", "A twisted wire crown studded with tiny sparklers.", {"Iron Nails": 2, "Flaxa": 1}, "clothing"),
    ],
    "Valentine's Day": [
        ("Heart Garland", "A string of cloth hearts to hang over a doorway.", {"Fabric": 1, "Berries": 2}, "decor"),
        ("Rose Bouquet", "Herb-scented roses tied with a ribbon.", {"Herbs": 3, "Flaxa": 1}, "decor"),
    ],
    "Memorial Day": [
        ("Poppy Wreath", "A wreath of red paper poppies to remember those who came before.", {"Flaxa": 3, "Berries": 2}, "decor"),
        ("Remembrance Lantern", "A clay lantern that holds a single small flame.", {"Clay": 2, "Herbs": 1}, "decor"),
    ],
    "Father's Day": [
        ("Grill Apron", "A sturdy apron with a pocket for every grilling tool.", {"Fabric": 2}, "clothing"),
        ("Fishing Rod", "A simple wooden rod and line for a quiet afternoon by the water.", {"Lumber": 2, "Flaxa": 1}, "decor"),
    ],
    "Independence Day": [
        ("Star Bunting", "Red, white and blue bunting for the front porch.", {"Fabric": 1, "Flaxa": 2, "Berries": 1}, "decor"),
        ("Paper Firework", "A harmless paper firework that bursts into streamers.", {"Flaxa": 2, "Coal": 1}, "decor"),
    ],
    "Labor Day": [
        ("Tool Belt", "A sturdy belt with a loop for every tool.", {"Fabric": 1, "Iron Nails": 2}, "clothing"),
        ("Workers' Banner", "A banner thanking everyone who keeps New Eridian running.", {"Fabric": 1, "Lumber": 1}, "decor"),
    ],
    "Halloween": [
        ("Jack-o'-lantern Mask", "A carved pumpkin mask with a soft cloth lining. Crafting one turns your Seedling into a pumpkin head on the stream map.",
         [{"Pumpkin": 2, "Fabric": 2}, {"Pumpkin": 2, "Synthetic Fabric": 1}], "clothing"),
        ("Spooky Lantern", "A clay lantern with a carved face that flickers in the dark.", {"Clay": 2, "Pumpkin": 1, "Herbs": 1}, "decor"),
        ("Scarecrow Doll", "A little straw scarecrow in a patched shirt.", {"Lumber": 1, "Flaxa": 2, "Corn": 2}, "decor"),
    ],
    "Thanksgiving": [
        ("Harvest Wreath", "Corn husks, nuts and dried leaves woven into a wreath.", {"Corn": 2, "Nuts": 2, "Flaxa": 1}, "decor"),
        ("Gratitude Table Runner", "A woven runner for the big shared table.", {"Fabric": 2, "Berries": 1}, "decor"),
    ],
    "Christmas": [
        ("Holiday Stocking", "A cosy knitted stocking, waiting to be filled.", {"Fabric": 2, "Berries": 1}, "decor"),
        ("Pine Wreath", "A fresh pine wreath with berry clusters and a ribbon.", {"Lumber": 1, "Herbs": 3, "Berries": 1}, "decor"),
    ],
}


def _slug(text):
    return ''.join(c if c.isalnum() else '_' for c in text.lower()).strip('_').replace('__', '_')


FESTIVAL_ITEMS = {}      # item key -> details
FESTIVAL_RECIPES = {}    # recipe id -> holiday
for _holiday, _rows in FESTIVAL_FOODS.items():
    for _name, _text, _inputs, _food, _comfort, _morale in _rows:
        _key = 'fest_' + _slug(_name)
        FESTIVAL_ITEMS[_key] = dict(name=_name, holiday=_holiday, description=_text, inputs=_inputs,
                                    food=_food, comfort=_comfort, morale=_morale, recipe='fr_' + _slug(_name))
        FESTIVAL_RECIPES['fr_' + _slug(_name)] = _holiday
FESTIVAL_CRAFT_ITEMS = {}   # item key -> details (keepsakes; FESTIVAL_ITEMS stays the foods)
for _holiday, _rows in FESTIVAL_CRAFTS.items():
    for _name, _text, _inputs, _kind in _rows:
        _key = 'fest_' + _slug(_name)
        _ways = _inputs if isinstance(_inputs, list) else [_inputs]
        _recipes = ['fr_' + _slug(_name) + (f'_{n + 1}' if n else '') for n in range(len(_ways))]
        FESTIVAL_CRAFT_ITEMS[_key] = dict(name=_name, holiday=_holiday, description=_text, ways=_ways, kind=_kind,
                                          recipe=_recipes[0], recipes=_recipes)
        for _rid in _recipes:
            FESTIVAL_RECIPES[_rid] = _holiday


def festival_items(holiday):
    """{item key: [recipe ids]} for every food and keepsake of a holiday."""
    found = {k: [v['recipe']] for k, v in FESTIVAL_ITEMS.items() if v['holiday'] == holiday}
    found.update({k: list(v['recipes']) for k, v in FESTIVAL_CRAFT_ITEMS.items() if v['holiday'] == holiday})
    return found


SURVIVAL_TAG = 'TAG_MACHINE_SURVIVAL_WORKBENCH'


def extend_catalog(data, survival_tag=SURVIVAL_TAG):
    """Add festival foods and recipes to the loaded catalog before it is indexed."""
    by_name = {}
    for key in data['gather']:
        by_name.setdefault(data['items'][key]['name'], key)
    for key, row in FESTIVAL_ITEMS.items():
        data['items'][key] = {
            'name': row['name'], 'description': row['description'] + f" Festival food from {row['holiday']}.",
            'properties': {'Volume': 0.1, 'Food': row['food']},
            'tags': ['TAG_RESOURCE_HAULABLE', 'TAG_RESOURCE_PRODUCEABLE', 'TAG_FOOD', 'TAG_RESOURCE_CONSUMABLE', 'TAG_FESTIVAL'],
            'categories': ['CAT_MAIN_CONSUMABLE', 'CAT_SUB_CONSUMABLE_FOOD'],
            'aging': None, 'consumable': {}, 'ailment_risk': None, 'remedy': None,
            'source': 'FESTIVAL_' + key[5:].upper()}
        data['recipes'][row['recipe']] = {
            'name': row['name'], 'inputs': {by_name[n]: q for n, q in row['inputs'].items()}, 'outputs': {key: 1},
            'machines': [survival_tag], 'timing': {}, 'requirement': {'Skill': 'SK_COOKING', 'Level': 0},
            'xp': {'TrainedSkills': ['SK_COOKING'], 'ExperienceMultiplier': 1.0},
            'source': 'SCH_FESTIVAL_' + key[5:].upper()}
    produced = {k for r in data['recipes'].values() for k in r['outputs']}
    def item_key(name):                     # keepsakes also use crafted materials (Fabric, Iron Nails…)
        if name in by_name:
            return by_name[name]
        return sorted(k for k, v in data['items'].items() if v['name'] == name and k in produced)[0]
    for key, row in FESTIVAL_CRAFT_ITEMS.items():
        data['items'][key] = {
            'name': row['name'], 'description': row['description'] + f" Festival keepsake from {row['holiday']}.",
            'properties': {'Volume': 0.2}, 'tags': ['TAG_RESOURCE_HAULABLE', 'TAG_RESOURCE_PRODUCEABLE', 'TAG_FESTIVAL'],
            'categories': ['CAT_MAIN_CLOTHING'] if row['kind'] == 'clothing' else ['CAT_MAIN_FURNITURE', 'CAT_SUB_FURNITURE_DECOR'],
            'aging': None, 'consumable': None, 'ailment_risk': None, 'remedy': None,
            'source': 'FESTIVAL_' + key[5:].upper()}
        for rid, inputs in zip(row['recipes'], row['ways']):
            data['recipes'][rid] = {
                'name': row['name'], 'inputs': {item_key(n): q for n, q in inputs.items()}, 'outputs': {key: 1},
                'machines': [survival_tag], 'timing': {}, 'requirement': {'Skill': 'SK_CRAFTING', 'Level': 0},
                'xp': {'TrainedSkills': ['SK_CRAFTING'], 'ExperienceMultiplier': 1.0},
                'source': 'SCH_FESTIVAL_' + rid[3:].upper()}


def festival_window(holiday, today=None):
    """(start, end) of the current or next festival for a holiday."""
    today = today or datetime.now(timezone.utc).date()
    for year in (today.year - 1, today.year, today.year + 1):
        day = _holiday_date_for(holiday, year)
        if day + timedelta(days=7) >= today:
            return day - timedelta(days=30), day + timedelta(days=7)
    day = _holiday_date_for(holiday, today.year + 1)
    return day - timedelta(days=30), day + timedelta(days=7)


def festival_open(recipe, today=None):
    """True unless `recipe` is a festival recipe outside its festival window."""
    holiday = FESTIVAL_RECIPES.get(recipe)
    if holiday is None:
        return True
    today = today or datetime.now(timezone.utc).date()
    start, end = festival_window(holiday, today)
    return start <= today <= end


def festival_lock_text(recipe, today=None):
    holiday = FESTIVAL_RECIPES[recipe]
    start, end = festival_window(holiday, today)
    return f'{holiday} festival recipe: craftable {start.isoformat()} to {end.isoformat()} (UTC).'


def _nth_weekday_of_month(year, month, weekday, occurrence):
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    first_occurrence = first + timedelta(days=offset)
    return first_occurrence + timedelta(days=7 * (occurrence - 1))


def _holiday_date_for(name, year):
    if name == "Memorial Day":
        last = date(year, 5, 31)
        return last - timedelta(days=last.weekday())
    if name == "Father's Day":
        return _nth_weekday_of_month(year, 6, 6, 3)
    if name == "Labor Day":
        return _nth_weekday_of_month(year, 9, 0, 1)
    if name == "Thanksgiving":
        return _nth_weekday_of_month(year, 11, 3, 4)
    for label, month, day, emoji in HOLIDAY_WINDOWS:
        if label == name:
            return date(year, month, day)
    return None


def holidays_active_for(today=None):
    today = today or datetime.now(timezone.utc).date()
    active = []
    for label, _, _, emoji in HOLIDAY_WINDOWS:
        for year in (today.year - 1, today.year, today.year + 1):
            holiday_date = _holiday_date_for(label, year)
            if holiday_date is None:
                continue
            start = holiday_date - timedelta(days=30)
            end = holiday_date + timedelta(days=7)
            if start <= today <= end:
                active.append({
                    "name": label,
                    "emoji": emoji,
                    "holiday_date": holiday_date,
                    "start": start,
                    "end": end,
                    "days_until_holiday": (holiday_date - today).days,
                    "days_after_holiday": (today - holiday_date).days,
                })
    return active


def next_holiday_window(today=None):
    """Next unopened festival window, including the next calendar year."""
    today = today or datetime.now(timezone.utc).date()
    upcoming = []
    for year in (today.year, today.year + 1):
        for label, _, _, emoji in HOLIDAY_WINDOWS:
            holiday = _holiday_date_for(label, year)
            start = holiday - timedelta(days=30)
            if start > today:
                upcoming.append(dict(name=label, emoji=emoji, holiday_date=holiday,
                                     start=start, end=holiday + timedelta(days=7)))
    return min(upcoming, key=lambda row: row['start'])


def holiday_message(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(timezone.utc).date()
    def stamp(day, style='F'):
        seconds = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        return f'<t:{seconds}:{style}>'
    lines = ['🎉 HOLIDAY CALENDAR']
    active = holidays_active_for(today)
    if active:
        lines.append('ACTIVE NOW')
        for row in sorted(active, key=lambda row: row['end']):
            end = row['end'] + timedelta(days=1)
            lines.append(f"{row['emoji']} {row['name']} — ends {stamp(end)} ({stamp(end, 'R')})")
    else:
        lines.append('No holiday event is active right now.')
    row = next_holiday_window(today)
    lines += ['NEXT HOLIDAY EVENT', f"{row['emoji']} {row['name']}",
              f"Starts {stamp(row['start'])} ({stamp(row['start'], 'R')})",
              f"Holiday date: {row['holiday_date'].isoformat()}",
              f"Window: {row['start'].isoformat()} through {row['end'].isoformat()} (UTC dates).",
              'Festival foods: ' + ', '.join(food[0] for food in FESTIVAL_FOODS[row['name']]) + '.',
              'Festival keepsakes: ' + ', '.join(c[0] for c in FESTIVAL_CRAFTS.get(row['name'], [])) + '.',
              'Festivals begin 30 days before the holiday at 00:00 UTC and include the 7 days after it. Discord timestamps show your local time.',
              'Festival foods are real items: craft them from gathered ingredients at the free Survival Workbench while their festival runs. '
              'Eating one gives Nutrition plus bonus Comfort and Morale; they keep, sell and stack all year.']
    for row in sorted(active, key=lambda row: row['end']):
        lines += ['', f"{row['emoji']} {row['name'].upper()} FESTIVAL FOODS"]
        for name, _, inputs, food, comfort, morale in FESTIVAL_FOODS[row['name']]:
            key = 'fest_' + _slug(name)
            uses = ', '.join(f'{n} ×{q}' for n, q in inputs.items())
            lines.append(f"• {name} — {uses} → +{max(1, round(food * 50))} Nutrition, +{comfort} Comfort, +{morale} Morale · /make recipe:{FESTIVAL_ITEMS[key]['recipe']}")
        lines += [f"{row['emoji']} {row['name'].upper()} FESTIVAL KEEPSAKES"]
        for name, _, inputs, kind in FESTIVAL_CRAFTS.get(row['name'], []):
            key = 'fest_' + _slug(name)
            ways = ' or '.join(', '.join(f'{n} ×{q}' for n, q in way.items()) for way in (inputs if isinstance(inputs, list) else [inputs]))
            lines.append(f"• {name} ({'wear it' if kind == 'clothing' else 'decoration'}) — {ways} · /make recipe:{FESTIVAL_CRAFT_ITEMS[key]['recipe']}")
        lines.append('Craft every festival food and keepsake of a holiday for its Feast trophy and holiday hat.')
    return '\n'.join(lines)


def festive_message_for(channel: str = "new-eridian", today=None):
    today = today or datetime.now(timezone.utc).date()
    active = holidays_active_for(today)
    if not active:
        return {"active": False, "message": "🌱 New Eridian is between festivals."}

    pick = sorted(active, key=lambda x: abs((today - x["holiday_date"]).days))[0]
    label = pick["name"]
    lines = DAY_TEXT[label]
    hash_seed = hashlib.sha256(f"{channel}:{label}:{today.isoformat()}".encode()).hexdigest()
    idx = int(hash_seed[:8], 16) % len(lines)
    recipe = [row[0] for row in FESTIVAL_FOODS[label]][int(hash_seed[-1], 16) % len(FESTIVAL_FOODS[label])]
    return {
        "active": True,
        "name": label,
        "emoji": pick["emoji"],
        "holiday_date": pick["holiday_date"].isoformat(),
        "start": pick["start"].isoformat(),
        "end": pick["end"].isoformat(),
        "days_until_holiday": pick["days_until_holiday"],
        "days_after_holiday": pick["days_after_holiday"],
        "message": f"{pick['emoji']} {label}: {lines[idx]}",
        "special_recipe": recipe,
        "special_recipe_craftable": True,
        "special_recipe_id": FESTIVAL_ITEMS.get('fest_' + _slug(recipe), {}).get('recipe', ''),
        "special_recipe_note": "Festival food: craft it at the Survival Workbench while the festival runs.",
        "holiday": pick["holiday_date"].isoformat(),
        "days_to_holiday": pick["days_until_holiday"],
    }


def install(app):
    @app.get("/api/v1/season")
    def season(channel: str = "new-eridian"):
        return festive_message_for(channel)

    return app


__all__ = ["festive_message_for", "holidays_active_for", "next_holiday_window", "holiday_message", "install",
           "FESTIVAL_ITEMS", "FESTIVAL_RECIPES", "FESTIVAL_CRAFTS", "FESTIVAL_CRAFT_ITEMS", "festival_items", "extend_catalog",
           "festival_open", "festival_lock_text"]
