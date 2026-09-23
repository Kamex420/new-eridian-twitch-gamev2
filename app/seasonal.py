
from datetime import date, timedelta
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
    today = today or date.today()
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


def festive_message_for(channel: str = "new-eridian", today=None):
    today = today or date.today()
    active = holidays_active_for(today)
    if not active:
        return {"active": False, "message": "🌱 New Eridian is between festivals."}

    pick = sorted(active, key=lambda x: abs((today - x["holiday_date"]).days))[0]
    label = pick["name"]
    lines = DAY_TEXT[label]
    hash_seed = hashlib.sha256(f"{channel}:{label}:{today.isoformat()}".encode()).hexdigest()
    idx = int(hash_seed[:8], 16) % len(lines)
    recipe = SPECIAL_RECIPES[label][int(hash_seed[-1], 16) % len(SPECIAL_RECIPES[label])]
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
        "special_recipe_craftable": False,
        "special_recipe_note": "Festival flavor only; available crafting recipes are listed in /make.",
        "holiday": pick["holiday_date"].isoformat(),
        "days_to_holiday": pick["days_until_holiday"],
    }


def install(app):
    @app.get("/api/v1/season")
    def season(channel: str = "new-eridian"):
        return festive_message_for(channel)

    return app


__all__ = ["festive_message_for", "holidays_active_for", "install"]
