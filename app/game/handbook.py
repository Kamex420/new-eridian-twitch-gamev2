"""The in-game handbook (SEED_HELP_TOPICS), Twitch help pages and the moderator log.
"""
from sqlalchemy import select
from .. import notice as fan_notice
from ..commands import transaction as game_transaction
from ..db import SessionLocal
from ..needs import duration_text, SLEEP_COOLDOWN_SECONDS
from ..models import ModeratorAudit
from .base import app, clean, out, OWNER_ONLY_TEXT, twitch_owner_ok
from .. import main      # app.main: names from later modules and settings changed at runtime

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

Standard work, /eat, /make and /gather use a 5-second cooldown. Rare ore mining uses a shared 20-second cooldown. Social and recovery actions use 20–60 seconds depending on the activity. /sleep fully restores Energy and Comfort but only once every 30 minutes. Browsing spends nothing. Crafting requires the listed workstation, personal tier and skill; /make previews all of it before you spend anything. /workshop shows unlocks; /seedindustries sells starter supplies. Check exact remaining times with /me section:Cooldowns.""",
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
/home action:Upgrade — Spends the displayed SC and Iron Nails. Habitat tier is personal, not society tier.
/business action:View — Shows company level, XP, contract pay, and current investment cost.
/business action:Start — Registers one permanent business for 75 SC.
/business action:Work — Routine Commerce operation and +1 Business XP on success.
/business action:Contract — Higher-paying Commerce action and +2 Business XP on success.
/business action:Invest — Costs 25 + (10 × current Business Level) SC and gives +3 Business XP, +1 Contribution, +3 Treasury, and +1 Development.
/make — The Workbench. Choose a category (Materials & Ores, Components, Food & Drink, Medicine, Tools & Equipment, Machines, furniture groups, Clothing, Decor), then a recipe. Every list runs from the easiest recipe to the most complex: first by the personal tier the whole chain needs, then skill level, then crafting steps. A recipe opens as a preview (ingredients have/need, workstation, tier, skill, where to get each ingredient) with buttons to Craft 1 batch, Unlock its workstation, or Queue up to 10 batches.
/seedindustries — Fixed-price NPC exchange plus three rotating daily Production Orders. Orders consume manufactured goods and reward SC, Contribution, Development, Crafting XP, and Commerce XP.

CRAFTING ROUTE
/gather and /mine → Lumber, Stone, Clay, Flaxa, Hematite Ore and other raw materials
/make → Survival Workbench recipes are free; unlock more workstations with /workshop (15 SC each at Tier 1)
Hematite Ore → Raw Iron → Iron Ingot → Iron Plate / Iron Nails / Iron Rod (Metalworking Bench)
Lumber → Wood Planks (Carpentry Station) · Stone → Stone Block (Masonry Bench)
/make category:Tools & Equipment → Toolkit, quality gear and other bonus equipment, all built from those catalog parts

All items are SEED catalog items. Old names still work and share the same stock: Crops = Pumpkin, Components = Iron Nails, Alloy Plate = Iron Plate, Biofiber = Flaxa, Sealant = Mortar, Precision Lens = Glass, Ration = Dried Berries, Water Filter = Small Water Filter, Sensor = Resource Scanner, Crate = Storage Platform.
Passive-bonus equipment is unique: you may own only one of each item. Consumables and materials stack.
Relevant successful actions build gear familiarity. At 10/25/50 uses it reduces wear chance by 5/10/15 percentage points without adding success or pay.

ECONOMY RULE
Workbench equipment pays 2 SC and quality gear pays 3 SC before the Technician bonus; catalog recipes pay in output and practice. Production Orders pay 75% of the NPC replacement cost, so buying every input loses SC while gathering and manufacturing creates profit.

BEST USE: /guide goal:crafting, /guide goal:home, or /guide goal:business.""",
"life":"""🌿 LIFE & SOCIAL SYSTEMS

/me section:Life Needs — Energy, Nutrition, Social, Comfort, Morale, and active effects.
/eat — Opens your food list, strongest first, with owned quantities. Raw food (Pumpkin, Berries, Corn…) gives +10 Nutrition; prepared food from /make (Roasted Pumpkin, Dried Berries, stews…) gives +15 to +50 plus +2 Morale and 10 minutes of Rocky's Favor (+3 percentage-point success). A Meal Kit restores Nutrition based on quality and +5 Morale. If Nutrition is below 20 and you own no food, a free emergency meal restores Nutrition to 40. All needs cap at 100.
/sleep — Fully restores Energy and Comfort to 100; reduces Siro exposure by up to 8. Available once every 30 minutes.
/relax — +25 Energy, +20 Comfort and Morale (30-second cooldown).
/use — Beds (+Energy/+Comfort), seats (+Comfort/+Social), baths (+Comfort/+Morale), clothing (+Comfort/+Morale) and a Comfort Pack restore Comfort between sleeps.
/walk — Improves Morale and Exploration hobby progress.
/games — Free solo activity: +25 Social, +4–8 Morale, and Games hobby progress. No partner or item required.
/social — One hub for saying hi, hanging out, mentoring, and relationship-gated duo activities.
/hobby — Practices the selected hobby.

Greetings, hangouts, and duo activities build persistent Relationship Memories. /me section:Relationships shows the activity count and most recent shared activity.

TASK READINESS
Energy, Nutrition, and Social must each be 20 or higher, and Comfort 10 or higher, to work, craft with /make, or repair personal gear with /repair. Otherwise the task does not start: no materials are consumed, no rewards are rolled, and no cooldown begins.
• Low Energy: /relax, or /sleep when it is ready
• Low Nutrition (hunger): /eat. With no food, it requests a free emergency meal and restores Nutrition to 40.
• Low Social: /games or /social
• Low Comfort: /relax, or /use a bed, seat, bath, clothing item or Comfort Pack; /sleep when ready

COMFORT
Every task costs as much Comfort as Energy (a standard task: −2 Energy, −1 Nutrition, −2 Comfort). Below 20 Comfort, work is slower (−10% success, −1 Morale per task); below 10 it stops. Sleep refills Comfort but runs on a 30-minute timer, so furniture, baths, clothing and relaxing keep you working in between.

Recovery and information commands remain available while work is blocked. This recovery loop always provides a way back into work without requiring work first.""",
"production":"""🏭 WORK ACTIONS

/farm — Farming work: 2 SC before bonuses, +1 Contribution, base society Food plus available shared production, and condition-dependent aptitude practice on success.
/farm action:Harvest Pumpkins — Farming work that gives 3 Pumpkins and a Pumpkin Seed.
/farm action:Irrigate — Processing work that adds society Food and 3 Pumpkins.
/farm action:Hydroponics — Requires a Small Water Filter (a /make machine) and improves Food while producing 4 Pumpkins.
/scan — Processing work that adds +1 society Knowledge.
/mine — Choose an ore and view its requirements, then select Mine. Count starts a queue of 1–10 attempts. Rare ores (Argentite, Aurite, Bauxite, Rutile) are in the same list once you have a Mineral Extractor in your bag: the Small one brings up 1 ore a success, the Frontiers Expedition one 2. /queue shows progress, total needs and missing materials; it pauses and resumes automatically.
/rare — Mine the rare ore you have least of (Argentite, Aurite, Bauxite or Rutile; /mine picks a specific one). Needs a Small or Frontiers Expedition Mineral Extractor in your bag; shared 20-second cooldown.
/training — Choose a skill, view branches and inventory requirements, then choose Task to work. Includes Cooking, Medicine and Emergency Response, their jobs, and level unlocks.\n/make — The Workbench: every recipe by category, easiest first, with previews, Craft and Queue buttons.
/repair target:Society Infrastructure — Engineering work; adds +1 Development.
/research — Research work that raises Knowledge. Primary response for Siro Bloom.

FAILURE PROTECTION
A failed skilled task gives one Determination stack. Each stack adds +4 percentage points to the next attempt in that aptitude, up to +12%. A success uses and clears the stacks. Blocked attempts do not create Determination.

Old work routes remain compatible on Twitch/API, including !craft and !machine, but Discord uses /make as the single Crafting system.""",
"operations":"""🛰️ LOGISTICS, FRONTIER & COMMERCE

/cargo — Prepares 1 personal Cargo and adds +1 society Treasury. Use before /delivery.
/delivery — Opens your Cargo supply preview; choose Send Delivery. Requires 1 personal Cargo, consumed only on success; adds +1 Reputation, and advances delivery-fleet bond XP.
/spaceport — Standard Logistics work or Expedited Operations that consume 1 Power Cell for stronger Treasury, Reputation, and SC rewards.
/explore — Scout normally or use a Resource Scanner for an Advanced Survey with stronger Knowledge and SC rewards.
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

COMMUNITY
/vote — Every Avesta day the colony votes on the next society project or a festival. The first vote on a ballot pays 3 SC. A voted project starts when the current one is finished and stays on the stream map as a landmark; a voted festival gives +5% to its work for the next day.
/challenge — Stream challenges happen only while the stream is live: 5–10 minutes, one shared goal, rewards for everyone who helps and a bonus for the top helper.
/season — Five-week seasons with a weekly story. Points come from Contribution, aptitude XP, challenges, votes and trophies. Bronze, Silver and Gold unlock a title, a hat for your Seedling and a golden title; the top three win champion titles. Only season points reset.
/trophies — Collections and trophies (every ore, craft categories, festival foods, curios, colony and stream milestones). Pin a badge that shows next to your name on the stream map.
Every Sunday the bot posts a weekly recap: top contributors, biggest hauls, society progress and the funniest Seedling moments.

BEST USE: /guide goal:event during emergencies and /guide goal:society between events.""",
"other":"""🍲 PERSONAL ACTIONS

/district — Chooses your home district.
/shift — Chooses today's role bonus.
/meal — Shows owned Pumpkins; choose Share a Crop to contribute one Pumpkin to the community meal.
/life action:Trick-or-treat — During the Halloween festival, knock on up to 5 doors a day for a treat (ingredients, SC or a festival food) or a harmless trick. Twitch: !trick.
/use — Lists owned usable items with exact effects; select Item to use it (durable items are kept).
/repair — Choose Society Infrastructure work or Personal Quality Gear repair.
/linklookup — Owner-only lookup for connected Discord/Twitch identities.

Use /me for personal information, /progress for personal progression, and /world for shared world information.""",
"moderator":"""🛡️ MODERATOR CONTROLS

/eventstart — Starts one selected event immediately. Existing automatic-event timing is safely reset. Owner only.
/eventstop — Cancels the active event with no failure penalty. This is cancellation, not success. Owner only.
/modlog — Shows recent event-control records, including who did it and the action. Owner only.
/mod action:asklog — Questions players asked /find that it could not answer, most asked first (never who asked). Owner only.

/mod — Stream challenge start/stop, Stream is live on/off/automatic, and Weekly recap preview/post now.

Only the game owner can use these: the Discord accounts in DISCORD_OWNER_USER_IDS, and on Twitch the broadcaster. Server permissions and roles do not grant them.""",
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
Cooldown — Standard work, /eat, /make and /gather use 5 seconds. Social and recovery actions use 20–60 seconds. /sleep is available once every 30 minutes. Linked Twitch/Discord accounts share cooldowns.
Task readiness — Energy, Nutrition, and Social must each be at least 20, and Comfort at least 10, for work, /make crafting, and personal gear repair. A blocked attempt spends nothing and starts no cooldown. Recovery commands remain usable; /eat supplies an emergency meal when a starving player has no food.
Task cost — Standard work and /make use 2 Energy/1 Nutrition/2 Comfort. Heavy extraction, frontier, and repair tasks use 3 Energy/1 Nutrition/3 Comfort. Comfort drains at the same rate as Energy; below 20 it lowers success and Morale. All five life needs recharge by 1 per 15 real minutes, up to 60/100, including while away. Needs above 60 are not reduced. Food, sleep and social activities recover faster. Results warn when recovery is required.
Personal bonus — Temporary success, SC, Contribution, or XP boost. Each activation lasts 10 minutes; matching time stacks.
Workbench — /make. Every recipe grouped by category and listed easiest first. Personal tier, skill level and crafting steps decide the order.
Catalog item — Every material, part, food and tool is a SEED catalog item. Old names (Crops, Components, Alloy Plate, Biofiber, Sealant, Precision Lens, Ration, Water Filter, Sensor, Crate) now mean Pumpkin, Iron Nails, Iron Plate, Flaxa, Mortar, Glass, Dried Berries, Small Water Filter, Resource Scanner and Storage Platform.
Passive-bonus equipment — Held equipment that changes success, pay, or another outcome. Only one copy of each such item may be owned.
Seed Industries — NPC supplier and surplus buyer with fixed prices. It is a fallback when a production chain is missing one material, not the rotating player market.
Production Order — One of three rotating daily Seed Industries contracts. Each is completed once per citizen per Avesta day and pays less than buying all inputs.
Determination — Failure protection. Matching failures add +4 percentage points to the next aptitude attempt, up to +12%; success resets it.
Activity unlock — Equipment can open stronger command options: Small Water Filter Hydroponics, Siro Sampler Field Analysis, Resource Scanner Survey, Power Cell Spaceport Expedite, Market Analyzer Analysis, and Recreation Set social recovery.
Automatic-event meter — Counts real game actions and unique command users before randomly starting an event.
Daily Variety — Optional once-per-Avesta-day reward for successful work in three different aptitudes. It has no streak.
Society Directive — Shared daily work priority shown in the Daily Bulletin and /guide.
Gear familiarity — Use milestones that reduce gear wear chance without changing its success bonus.
Relationship Memory — Persistent count and latest shared activity between two citizens.
Event Aftermath — Non-stacking 60-minute modifier created by a finished event.
Result style — Compact keeps routine cards short; Detailed adds every modifier and final success chance.
Discoverable lore — Rare unique journal entries found during successful skilled work.""",
}

SEED_HELP_TOPICS["about"]=fan_notice.FULL

def discord_seed_help(topic="overview",name="Citizen"):
    topic=(topic or "overview").lower()
    greeting=f"📖 {clean(name)} — New Eridian Handbook\n\n"
    if topic=="about":return greeting+SEED_HELP_TOPICS[topic]
    if topic in SEED_HELP_TOPICS:
        extra="\n\nSUPPLIES\n/catalog Category lists every item through numbered Pages; select Item for exact uses and ingredients. /gather collects natural resources. /make uses the same categories, lists recipes easiest first and previews before spending. /use lists owned items with their costs and effects; durable items are kept. /eat lists owned edible foods." if topic in {'property','production','terms'} else ''
        return greeting+SEED_HELP_TOPICS[topic]+extra
    return (greeting+"🌱 Choose a /seed topic for complete explanations:\n\n"
            "🧭 Start Here — first steps and /guide\n👤 Character — stats, jobs, XP, linking\n"
            "🏠 Property — home, business, crafting\n🌿 Life Systems — needs, recovery, social actions\n"
            "🏭 Production — mining, industry, research\n🛰️ Operations — logistics, frontier, commerce\n"
            "🏙️ Society — tiers and events\n🍲 Other — eat and sleep\n🛡️ Moderator — event controls\n"
            "📖 Terms — definitions for SC, XP, Contribution, aptitudes, tiers, and event roles\n"
            "ℹ️ About — a free fan project by Kamex\n\n"
            "Not sure what to do? Use /guide. Standard work, /eat and /make use 5 seconds, social/recovery use 20–60 seconds, and /sleep is available once every 30 minutes.")

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
        return out(f"New Eridian: !start then !job then !guide. Handbook: !seed start, character, property, life, production, operations, society, other, moderator, terms, about. Example: !seed property 2. Work, !eat, !make, !gather: 5s; social/recovery: 20–60s; !sleep: once per {duration_text(SLEEP_COOLDOWN_SECONDS)}.")
    from ..twitch_help import TOPICS
    content=main.twitch_lite.topic(topic,TOPICS[topic])
    return twitch_pages(content,page,f"!seed {topic}")

@app.get("/api/v1/admin/modlog")
@game_transaction
def twitch_modlog(channel:str,level:int=0,key:str="",page:str="1"):
    if not twitch_owner_ok(key,level):
        return out(OWNER_ONLY_TEXT)
    with SessionLocal() as db:
        rows=db.execute(select(ModeratorAudit).where(ModeratorAudit.channel_id==channel).order_by(ModeratorAudit.created_at.desc()).limit(10)).scalars().all()
        content=" | ".join(f"{r.action}: {r.detail} ({r.moderator})" for r in rows) or "No moderator actions recorded."
        return twitch_pages(content,page,"!modlog")
