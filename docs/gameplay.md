# Gameplay reference

## Mining and gathering

`/mine` exposes ore selection, a requirements preview, and a count from 1 to 10. Common ore attempts cost 2 Energy, 1 Nutrition and 2 Comfort, with the existing 5-second shared gathering cooldown. They require no tools or skill unlock.

Argentite, Bauxite, Rutile and Aurite require Harvesting level 3. One prospecting attempt costs 3 Energy, 1 Nutrition and 3 Comfort; all rare ores share a 20-second cooldown. Three successful prospecting steps produce one ore. With no failures, a ten-attempt queue beginning with no saved progress produces three ores and one remaining step. Failures produce Stone Dust instead, so ten attempts no longer guarantee three ores.[^1]

`/gather` browses non-ore resources. Older ore-gathering routes remain compatible with the same requirements. No alternate route skips rare-ore gates.

## Crafting and progression

`/make` opens the Workbench: fifteen categories (Materials & Ores, Components, Food & Drink, Medicine & Clinic, Seeds & Farming, Tools & Equipment, Machines & Workstations, Building Parts, Beds & Camping, Chairs & Sofas, Bathroom & Washing, Clothing, Storage & Shelves, Tables & Counters, Decor & Recreation). Each category lists recipes from easiest to most complex: the personal tier the whole ingredient chain needs, then skill level, then the number of crafting steps from raw materials. The same categories are used by `/catalog` and `/use`; old names such as `basic_components` or `final_products` still open the matching category.

Every recipe shows ✅ ready, ❌ missing ingredients, 🔑 workstation fee or 🔒 tier/skill lock, with the key blocker in the dropdown label. Selecting a recipe previews it without spending anything: ingredients as owned/needed with where to get each one, output per batch, workstation, tier, skill, needs cost and cooldown. In Discord the preview has buttons for Unlock, Craft 1 batch, Queue 5, Queue 10 and a 1–10 amount menu; a queue first shows its totals and starts only when Start is pressed. On Twitch, `!make` shows the categories, `!make parts 2` a page and `!make Iron Plate` crafts.

Recipes require their corresponding bench or machine access, personal tier and listed skill. Personal tiers unlock at 0, 25, 100 and 250 completed manufacturing batches. Matching station ownership can replace a permanent access fee; it cannot bypass tier or skill requirements.

Ingredient-consuming manufacturing training uses the matching catalog recipe's inputs, output batch and access gates. Gathering, purchases and non-manufacturing training do not increase the manufacturing count. Recipe previews expose ingredient quantities, station, tier and skill requirements.[^2]

## Needs and queues

Energy, Nutrition and Social must each be at least 20 before an attempt. Every task costs as much Comfort as Energy (a standard task: 2 Energy, 1 Nutrition, 2 Comfort). Below 20 Comfort, work has −10% success and costs 1 Morale per task; below 10 Comfort, work stops until Comfort recovers. A task may finish below these thresholds; its next attempt then pauses.

Sleep restores Energy and Comfort to 100 but can only be used once every 30 minutes (`SLEEP_COOLDOWN_MINUTES`). Between sleeps, Comfort comes from `/relax` (+20), owned beds, seats, baths and clothing through `/use` (kept after use) and the Habitat Comfort Pack (+40 Comfort). Passive recovery adds one point to each need every 15 minutes, up to 60, including elapsed time away. Recovery never lowers a value already above that cap.

A queue contains one exact task/resource/recipe and at most ten attempts. Starting a second active queue is rejected even when its task matches. Failed attempts count; attempts blocked by needs, materials, ownership, skill, tier, workstation access or cooldown do not. Paused queues resume automatically after their requirements are met.

Queue results show successes, failures, total items gained and total items used. A success uses the actual recipe or gathering yield; bonus items are included. Rare prospecting steps without ore are progress, not failures. The totals describe inventory changes already applied during each attempt, so viewing the queue never awards items twice. For queues begun before outcome tracking was installed, earlier attempts are marked as unrecorded.

| Ten attempts | Base needs spent | Starting needs sufficient without recovery |
| --- | --- | --- |
| Common ore or ordinary crafting | 20 Energy, 10 Nutrition, 20 Comfort | 38 Energy, 29 Nutrition, 20 Social, 28 Comfort |
| Rare prospecting or heavy work | 30 Energy, 10 Nutrition, 30 Comfort | 47 Energy, 29 Nutrition, 20 Social, 37 Comfort |

Forecasts exclude other activities, passive recovery and incident effects. Morale also falls by 1 per task while Comfort is below 20. Material budgets are upper bounds because unsuccessful work generally retains its ingredients. Requirement messages distinguish amounts needed, owned and missing, and include acquisition routes.

Queue status is private in Discord. Progress persists through restarts. The worker runs while the app is online, without posting unsolicited chat messages. Cancellation preserves completed work and stops remaining attempts.

[^1]: Rare prospecting: [`app/crafting_progression.py`](../app/crafting_progression.py).
[^2]: Acquisition graph and execution: [`app/seed_content.py`](../app/seed_content.py). Queue rules: [`app/task_queue.py`](../app/task_queue.py).

## Automatic work and useful task options

An active queue checks its next action every ten seconds while the service is running, independently of player messages. The first attempt is due ten seconds after starting. Needs and missing requirements pause the queue without consuming attempts. Rare-ore cooldowns still require twenty seconds between prospecting steps. Coal appears in `/mine`, awards one unit per successful attempt, and trains Ore Mining; its existing purchase price remains 4 SC.

On completion, cancellation, unmet requirements or a terminal error, the bot posts a result message in the originating Discord channel and mentions only the player who started the queue. The message includes success/failure counts and item totals. Twitch completion messages mention the player in the configured stream chat. Delivery failures never undo or repeat gameplay rewards; the journal and queue retain the result.

### Personal output per successful attempt

| Task | Output | Energy / Comfort per attempt | Additional requirement |
| --- | --- | --- | --- |
| Tend Fields | 1 Pumpkin + 1 Pumpkin Seeds | 2 / 4 | None |
| Harvest Pumpkins | 3 Pumpkin + 1 Pumpkin Seeds | 3 / 6 | None |
| Irrigate | 3 Pumpkin + 1 Murky Water | 4 / 8 | None |
| Hydroponics | 4 Pumpkin + 1 Raw Algae | 5 / 10 | Small Water Filter, kept |
| Standard Research | 1 Stone | 2 / 4 | None |
| Field Analysis | 2 Stone + 1 Herbs | 4 / 8 | Siro Sampler, kept |
| Standard Spaceport Operations | 1 Cargo + 1 Lumber | 2 / 4 | None |
| Expedited Spaceport Operations | 2 Cargo + 2 Lumber | 4 / 8 | 1 Power Cell consumed on success |
| Scout | 1 Stone + 1 Berries | 3 / 6 | None |
| Advanced Survey | 2 Stone + 1 Clay + 1 Coal | 5 / 10 | Resource Scanner, kept |
| Commerce Work / Business Work | 1 Cargo | 2 / 4 | Registered business for Business Work |
| Market Analysis / Business Contract | 2 Cargo + 1 Lumber | 4 / 8 | Market Analyzer / registered business |
| Forage | 2 Berries + 1 Herbs | 3 / 6 | None |

Higher-output methods trade more Energy for better yields. Failure still spends needs but grants none of these outputs. Existing random bonus yields are additional and included in queue totals. XP, society rewards and SC pay remain in place. Pumpkin Seeds have an existing planting use: one seed plus Clean Water yields three Pumpkins. Stone samples use the same Stone inventory as crafting; no duplicate item identities were introduced.

### Practice XP and lucky finds

Every task practises a skill: work, training tasks, gathering, mining and prospecting, crafting, production orders, item work (`/use` to plant, scan, pack, stock, build, analyse or supply the clinic) and gear repair (Engineering, Maintenance & Repair). After a successful task there is a 15% chance (25% after an especially good result) of a **lucky find**: one common item from the same line of work, added to the bag and shown as "🎁 Lucky find (Skill): +1 Item". Training tasks find items from their own branch (Chemistry finds Salt, Herbs or Smelly Fungus; Pottery finds Clay or Murky Water); other tasks use their main skill's list (`app/practice.py`). Failed attempts, life and social actions (eat, sleep, relax, games, hangouts), and buying or selling never find anything.

Specialist methods can be queued with task IDs such as `work:water@hydroponics`, `work:research@field_analysis`, `work:spaceport@expedite` and `work:market@analyze`. Equipment and consumable requirements are checked for every attempt. Repair targets and distinct manufacturing/clinic recipes retain their separate purposes; they are not ranked as interchangeable resource-harvesting methods.

## Mining success and Stone Dust

Common ores, Coal and rare prospecting now roll the same intrinsic and situational work success model: a 68% base, skill/equipment/specialization bonuses, life and world modifiers, relevant events and Determination, capped to a final 10–92% chance. Detailed mining calculations use the actual final chance; action receipts emphasize the outcome and changes. Skill level and conditions determine the final probability; 68% is not a fixed success rate.

A failed mining attempt awards one existing Stone Dust item, gives no ore or prospecting progress, spends the normal needs cost, starts the normal cooldown and consumes one queued attempt. It adds Determination and grants no success XP. Existing rare-ore progress is kept. Blocked attempts and cooldown waits grant no Stone Dust and spend no attempt. Stone Dust remains a catalog crafting ingredient with its existing recipes and item identity.

The same rule applies to extraction-machine recipes and legacy mining/training routes; machine recipes retain their successful batch sizes. Non-mining gathering and manufacturing recipes retain their existing rules. Queue results and completion mentions include Stone Dust totals. Rare steps that make progress without an ore remain separately reported as prospecting progress, alongside recovered-ore successes and failed rolls.

### Reading Discord cards

Cards show a compact overview. Select **Details** for the rest of a long view or action receipt,
then **Next**, **Previous** or **Overview** to navigate. Detail pages are private
and available for 24 hours. Run the command again to refresh changing information.
Queue needs use **current / needed to finish**, not current / maximum. The
forecast excludes other actions, incidents and passive recovery. Full material
sources, workstation requirements and mining rules remain in Details.


### Queue pauses and stops

Low Energy, Nutrition or Social pauses a queue and sends an alert (a direct message by default)
with the current value, required minimum and recovery command. Missing materials
or access also pauses it. Remaining attempts are saved, and recovery automatically
resumes the queue. Cooldown waits are not failures and do not produce pause alerts.
A last successful or failed attempt completes the queue even if needs are now low.

Completion and cancellation send their own alerts with recorded totals. Three
consecutive internal errors stop automatic retries and send a system-error alert;
completed work remains saved. A new queue can replace this stopped queue. Normal
mining/work failures are game outcomes and do not count as internal errors.

Action cards show this action's changes only. Inventory and currency include
secondary materials and items consumed to zero. Permanent bonuses, routine world
information and general instructions stay in their dedicated views. Recovery
warnings and new injuries or milestones remain relevant to the current action.

### Where alerts go

When your queue completes or pauses, you get a direct message by default. If your DMs
are closed, the alert waits privately in your Notifications instead; it is never posted
in the game channel unless you choose channel mentions in `/settings`. `/queue` shows
delivery errors when the bot cannot send the alert. The original private command
response is not the completion notification.


## Production batch and resale update

Catalog materials now produce demand-based batches of 5–20, including station efficiency; finished products produce one. /make recipe previews show the current output and NPC sale value. Seed Industries buys all obtainable catalog items. Newly listed finished goods are sell-only. See [Production economy](production-economy.md) for examples and price rules.

## Catalog items replace legacy items

Every item is a SEED catalog item. Old names still work in commands and share one stock with their catalog item, merged one-for-one: Crops = Pumpkin, Components = Iron Nails, Ore = Hematite Ore, Rare Ore = Argentite Ore, Biofiber = Flaxa, Alloy Plate = Iron Plate, Sealant = Mortar, Precision Lens = Glass, Ration = Dried Berries, Water Filter = Small Water Filter, Sensor = Resource Scanner, Crate = Storage Platform, Preserved Food = Quito Pumpkin Paste, Storage Jar = Ceramic Basin, Furniture = Garden Chair, Workwear = Seed Industries Long Sleeve Top and Medicine = Painkillers. Old recipe names such as `component` open the matching catalog recipe.

Specialist quality gear (for example the Mining Pick, Repair Kit or Comfort Pack) stays an upgrade system with its own bonuses, but every ingredient is now a catalog item (Iron Plate, Iron Nails, Wood Planks, Glass, Fabric and so on). Gear repair uses Iron Nails; Habitat upgrades use SC and Iron Nails.

## Discord menus and buttons

`/make`, `/mine`, `/gather` and `/queue` answer with dropdowns and buttons. Menus and page buttons only change the view and never spend anything. Buttons that spend (Craft, Unlock, Gather, Start queue, Stop queue) are single-use: a second click, a Discord retry or an old message cannot repeat the action, and only the citizen who opened the panel can press them. Spending buttons expire after 24 hours; run the command again for a fresh panel. Every dropdown label follows the same pattern: status emoji, name, amount, then cost or blocker.

In Discord's newer layout (the default, see `app/layout_v2.py`), list items carry their own button beside them instead: menu areas, choice lists, Workbench categories and recipe pages (8 recipes per page), and a skill's tasks (Start does the task once). A button beside a choice works exactly like picking it from the dropdown. Discord allows 40 parts per message, so on long lists only the first items get a button beside them and the rest keep their buttons in a row below.

`/menu` opens Home: a green **Do this next** button first, then six areas: Work (gather, mine, farm, other jobs, training, Queue status and the daily contract), Craft (your goal, ready recipes, all recipes, the shopping list), Life, Bag & Shop (your bag, buying and selling, your home and business), Society (the event, the vote, the season, trophies and news) and You (profile, skills, Seedling, looks, job and role, Settings). Help, Notifications (with the number waiting, 99+ past 99), Do again and (for the owner) Moderator sit in a row below. In the newer Discord layout Home also has a Queue button beside the queue line, a Life button beside the needs line while Energy, Nutrition, Social or Comfort is under 50, and a line for today's contract (with its button) under the queue line while it is not done and is not already the Do this next pick. Do this next picks the first that applies: recover blocked needs, fix a paused queue, the next first step, the goal's next step, today's daily contract (the button does the contract's task: Mine, Harvest, Train Fire Safety…), repeat your last queue, or choose a goal. Each area shows its main buttons and one **More** button (More · 3 to unlock when some are locked): less-used options under Also here, and the ones you cannot use yet under Not yet, closest to unlocking first, each with the reason and a How to get it button. On/off settings are one button that shows the state (Auto-recover: On). Each button names the place or action it leads to (areas blue, actions green, views grey), each menu screen shows where it sits (🏠 Menu › ⛏️ Work › More), and every screen ends with ◀️ Back and 🏠 Menu.

◀️ Back returns to the screen you were on before, step by step, like a browser's Back: each panel message remembers the screens it showed (`ui.HISTORY`, in memory). After a one-time action (Craft, Start, Sell…) Back returns to the screen the action was pressed on; on a Details page it returns to the screen's first page. On a message's first screen (straight after a slash command, or after the bot restarted) Back goes one level up instead: a recipe to its list, an area to the area above it, a screen inside an area to that area. The home menu gets Back once its message has shown another screen.

The goal (`/menu` → Craft → My goal, or 🎯 Set goal on any recipe) lists every step still needed, in order, with a button for each: gather or mine (as a queue), buy, craft the parts, craft the machine a workstation needs (owning it opens the station; the goal never asks you to unlock one for SC), reach a skill level (the training task that practises it, after its own level, its workstation's machine and its ingredients), reach a personal tier, help the colony reach its tier, or wait for a festival. Machines and parts come after their own ingredients, all the way down (`full_plan`). A step that costs more SC than you have offers the SC guide instead. Every result reached from the goal has a 🎯 Goal button back to it (`app/extras.py` `walkthrough`). The shopping list (below) plans several recipes the same way.

Progress counts steps, not ingredients: setting a goal stores how many steps its walkthrough had, and the goal screen shows a bar with "N of M steps done" (`!target` on Twitch: "N/M steps"), where N is that start less the steps still left. When more steps are left than at the start (you used some of the materials elsewhere), the start rises to match, so progress never goes below zero. Setting the goal it already is keeps its progress; a goal set before progress was kept starts counting the first time it is shown. The goal is planned once per screen.

When the goal's recipe becomes ready to craft (ingredients, workstation, tier and skill all met), one private 🎯 note says so: "Your goal Campfire is ready to craft. /menu → Craft → My goal." It is checked after each command and button, on each Discord interaction and after each queue attempt, from the recipe's status alone, and goes out once per goal setting (setting another goal, or clearing it and setting it again, arms it again; a goal that is ready when set gets none). Like other notifications it pops up privately on the next interaction under the important and all popup settings, waits in Notifications when popups are off, and is never a DM.

Crafting the goal completes it: it is cleared and one 🎯 Goal complete milestone goes to your inbox. This happens where the craft is recorded, so a Craft button, `!make`, a craft queue and a training task that runs the recipe (also a Seedling's) all count; a failed or refused attempt does not, and a receipt that only mentions the goal's name ("Mushroom" in "Sauteed Mushrooms") never does.

The goal screen has 🛒 Add to shopping list (one batch's output, then its entry; when the goal is already listed the button opens its entry instead), and every shopping-list entry has 🎯 Set as goal (🎯 Goal when it is the goal already), which sets the goal and opens it.

Every button press and form is acknowledged before any game work and answered right after (`discord_deferred.ack` and `answer_later`), so Discord never shows "This interaction failed" while the database is slow.


## Quality-of-life tools

These tools use the same game rules as manual play; none of them skips a cooldown, gate or cost.

### Status and hints

`/status` (`!status`) combines needs, work blockers with passive-recovery estimates, sleep readiness, the current or last queue with remaining time and its next queue, active cooldowns, up to three ready recipes (favourites first), one next step and your settings. Craft and gather receipts below personal Tier 3 end with a Next step; crossing a personal tier is announced on the receipt that crossed it.

### Favourites, Ready now and fetching

Up to 10 recipes can be starred from a preview (⭐ Favourite), with `/make action:Favourite` or `!fav <recipe>`. The Workbench lists **Ready now** (every recipe craftable this moment, favourites first) and **Favourites** before its categories.

A ❌ recipe's **Fetch missing** plan lists each shortfall and its source. Gatherable materials become a queue sized to the shortfall: ore attempts are padded for the 68% base success rate and rare ores for three prospecting steps per ore, up to the 10-attempt maximum. When that queue covers everything missing, the craft is queued next automatically. Purchasable shortfalls can be bought together; crafted ingredients link to their recipe.

### Follow-up queues, repeats and recovery

One next queue can wait behind the active queue and starts when it completes (not when it is cancelled or stops after errors; cancelling clears it). Completion, cancellation and stop alerts offer Repeat, which re-opens the same task and count. Pause reasons state when passive recovery (+1 per 15 minutes up to 60) clears each need, rounded up to the minute.

With **auto-recover** on, a queue that would pause for low needs first runs whichever recovery commands are ready: /relax for Energy or Comfort, /sleep if still needed, a durable comfort item, the lowest-Nutrition food you own (Meal Kits are never auto-eaten; the emergency meal is used only when you own no food), and /games for Social. Each command keeps its cooldown and effects. Recovery happens before the attempt, so recovery items never appear in the queue's item totals. **Recover now** runs one such round on request.

### Alerts

`/settings alerts:` chooses direct message (the default on Discord; closed DMs wait privately in Notifications instead of going to the channel), channel mention (posted in the game channel, where everyone sees it), quiet (a direct message for completion, cancellation and error alerts only) or off. Alert buttons: Repeat, Status and Queue, plus Recover now on need pauses.

### Quiet hours

`/menu` → You → Settings → 🌙 Quiet hours sets a daily window in your own time zone, for example 23:00–08:00 Europe/London: a pop-up form with the time zone (an IANA name such as `Europe/London`, which follows daylight saving, or an offset such as `UTC+2`, `+5:30` or `GMT-3`), the start and the end (`HH` or `HH:MM`, 24-hour clock; the window may cross midnight, and start and end must differ). Invalid input changes nothing. While the window is on, direct-message queue alerts wait instead of arriving; when it ends, everything that waited arrives as **one** DM, "🌙 While your quiet hours were on", listing each alert (completed, paused, stopped or cancelled, the task, attempts and totals). A single waiting alert arrives as the normal alert with "🌙 Held during your quiet hours". A pause that ends while it waits (the queue resumed) is not sent. ☀️ Turn off quiet hours, or moving the window so you are outside it, sends anything waiting straight away. Only DM alerts wait (the direct message and quiet alert modes): channel mentions, private popups, your Notifications and Twitch alerts are unchanged. `/settings`, `/status` and `/queue` show your quiet hours and when held alerts arrive.

### Inventory and selling

`/inventory` accepts search, sort (quantity, name, value, category), show (all, used in ready recipes, used by favourites, sellable) and page. `!inv` accepts the same words in any order, e.g. `!inv ore value 2`. Sell all sells a whole stack at the Seed Industries price, except what the item's keep level keeps. Clear-out sells Materials & Ores beyond 20 of each (or beyond the keep level, below), never touching ingredients of favourites or of the current or next queued recipe, and always shows a preview first.

### Shopping list

The shopping list plans several recipes at once: `/menu` → Craft → Shopping list, ➕ Add recipe… (a name and how many) or 🛒 Add to list on any recipe. Up to 10 recipes, each with how many of its output you want to *have*, 1–999 (one batch's output when you give no amount; adding a recipe again with an amount changes it; 0 removes it). An entry is done (✅) as soon as you own that many, however they arrived, and stays until you remove it; Clear done removes every done entry. A recipe that leaves the catalog stays listed as no longer available, with Remove, and is not planned.

One plan covers the whole list, with the goal's planner (`extras.list_plan`) and one pool of what you own. In list order each entry takes its output from the pool first and makes the rest with its own recipe (not another recipe for the same item); a batch's leftovers go back into the pool, and ingredients use the catalog's usual routes. Something several entries need therefore counts once against what you own: 30 Iron Plate plus Circular Saw Blades that use 5 plates plans 35 plates. The screen shows each entry (have / want → batches, or ✅), the raw materials across the list (need / have / missing, how to get each and its price), what buying everything Seed Industries sells would cost, and the first steps of the goal's walkthrough (`extras.list_walkthrough`). ▶️ Fetch next does the first step once (or opens where it is done), and its result has a 🛒 button back. 🪙 Buy all missing buys every missing material Seed Industries sells, through the ordinary purchase and only when you can afford all of it (greyed out with its price otherwise); a rare ore without Harvesting Lv 3 is not bought, and anything not for sale says where it comes from. Nothing else is done for you: every gate, cost and cooldown applies.

With the full game on Twitch, `!shopping` sums the list up on one line (entries have/want, missing materials, the next step), `!shopping add <recipe> [amount]` adds or changes one, `!shopping remove <recipe>` and `!shopping clear [done]` remove, `!shopping buy` shows the cost and `!shopping buy confirm` buys. In the lite version `!shopping` points to Discord, like goals.

### Keep levels

A keep level is how many of an item you always keep: `/menu` → Bag & Shop → More → Always keep (choose an item, then 10, 25, 50, 100, Custom… or Remove). Up to 25 items, 1–9999 each; an old item name and its catalog item are one keep level. Sell all, auto-sell after a queue and the "sell all" steps of plans and routines sell only what is above it, and their receipts say how many were kept. Clear-out uses the keep level instead of its usual 20, higher or lower, and still never sells favourite or queued ingredients. Selling a chosen amount is never limited, and Undo works as before.

Below a keep level the screen shows what is short and how it comes back, the same routes as Fetch missing: a gathering or mining queue (up to the 10-attempt maximum), a craft queue for its recipe, or buying the shortfall from Seed Industries when you have the SC. Restock starts it with the ordinary queue or purchase, so every gate, cost and cooldown applies and nothing starts while another queue is running. Items without such a route say where they come from. Restock only starts work that can progress now: a recipe missing its ingredients offers Fetch missing instead, a locked recipe or workstation opens the recipe (where Unlock is), and a rare ore without Harvesting Lv 3 says so; nothing starts. A recipe whose ingredients cover only some of the batches queues just those. Low needs and cooldowns do not hold Restock back: the queue waits them out.

With the full game on Twitch, `!keep` lists keep levels, `!keep <item> <amount>` sets one (`0` clears it), `!keep restock` shows the plan for the first short item and `!keep restock go` starts it. In the lite version `!keep` points to Discord, like the other trading commands.

### Names

Recipe and item names tolerate typos and partial names when one match is clearly best; otherwise replies suggest up to three names and nothing is spent.


## Festival foods

Each holiday festival (30 days before the holiday through 7 days after, UTC) unlocks three festival recipes at the Survival Workbench, made from gathered ingredients with Cooking practice. Outside the window the recipes are locked; the foods themselves never expire. Eating one gives its Nutrition, +10 to +18 Comfort and +5 to +9 Morale, and Rocky's Favor as prepared food. `/world section:Holidays & Festival Foods` (`!holiday` on Twitch) lists them.
