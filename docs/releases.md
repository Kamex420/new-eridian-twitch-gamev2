# Release notes

## Map and Hub fit a side column

The map and the Hub now adapt to the shape of their Browser Source. You can put them in a streamer's side column, next to a game capture, instead of over it.

**Recommended for a layout with a 340 px column beside the game** (they replace the Join card and the Avesta Operations panel; the Hub rotates through both):
- **Map: 340×250**, top of the column. It switches to a *card*:
  - The header, the town, and the caption (who is talking and what they say) are stacked, and none covers another.
  - District names become large icon badges, and Seedlings are drawn bigger.
  - Speech bubbles are off, because the caption carries the words.
  - The camera spends two of every three turns close up on the speaker.
  - The stat panel appears below the caption when the card is at least 380 px tall, or with `&stats=1`.
- **Hub: 340×176**, right below. It switches to a *compact* layout with type at about 15 px at 1080p. Any slide that would still overflow shrinks until it fits.

**Other layouts:**
- `&layout=tall` suits a column taller than it is wide, for example 340×440.
- `&layout=strip` suits a band such as 1440×120 under a game window. Every slide is laid out in one row: six stat tiles, the market's top items, the leaders, the queues, the Seedlings, two headlines, or four join commands.
- Layouts are chosen automatically from the source size. `&layout=` forces one: `compact`, `tall`, `strip` or `wide` for the Hub, and `card` or `wide` for the map.

## No more clipping on the map

An automated check measured every name tag, speech bubble, bar and panel on `/obs/map` at 960×540 and 1920×1080. It covered the wide shot, 16 camera turns with close-ups, a level-up banner and a holiday night. Everything it found is fixed. The check now passes with no overlaps.

- **The whole town fits.** The wide shot now sizes itself from the buildings actually drawn, so the tallest tower no longer runs under the header and the front houses no longer hide behind the caption.
- **Caption card and banners live in the empty corners.**
  - The caption is now a card in the bottom-right corner, which is outside the town.
  - Banners such as "🏗️ Market grew to LV 13" sit top-right, in the sky.
  - The stat panel stays top-left. None of them cover a building.
- **Hats clear the name tags.** Seedlings stand a little lower under each district name, so tall hats (chef, top hat) no longer poke into the name.
- **Smarter speech bubbles.**
  - A bubble tries about 50 spots around the speaker: above at several heights, to either side, and below. It takes the closest one that covers no district name, bar or panel and stays on screen. Its tail is also kept clear of names.
  - Bubbles stay the same size on screen in close-ups, and now scale around the speaker, so they no longer drift away from them when zoomed.
  - There is no bubble for a Seedling who is off-screen, behind a panel or hidden in a "+N" group. A Seedling who sets off walking stops talking.
- **Close-ups.** District names that would be cut off by the frame or slide under a bar or panel fade out during a zoom, and come back on the wide shot. Names are no longer rebuilt every few seconds, which used to flash hidden ones back in.
- **Card panels fit their source.** Leaders, Working, Join and News shrink to fit their Browser Source when a live event adds rows, instead of being cut off at the bottom.

## A professional look for every overlay

- **One design system.** Every OBS page now uses one set of colours, corner radii, shadows and motion timing: the Hub, map, ticker, alerts, news, leaders, working, join and setup pages, plus the older Society, Today, Event, Ops, Activity, Telemetry and Signal panels and `/overlay`.
- **Real fonts.** Headings use Fredoka (rounded, friendly, readable on stream) and text uses Inter. Both load from Google Fonts, so they look the same on every PC. The old serif headings are gone.
- **Smooth transitions.** Panels share one easing curve and timing. The Hub slides the old slide out to the left before the next slides in, and its title fades in. Alerts pop in and ease out. News stories, leader rows, queue rows and join tips all fade up the same way.
- **The news ticker is a TV-style lower third.** A "LIVE · NEW ERIDIAN NEWS" station block sits on the left. Every item in the crawl starts with a coloured section tag: EVENT, WEATHER, NEWS, SOCIETY, TODAY, MARKET, HOLIDAY, PROJECT, AT WORK, REPORT, RUMOR or JOIN. The Avesta clock and day sit on the right. The ticker sizes itself from the source height, and 1920×56 is now recommended.
- **Map stat panel.** A small card in the top-left corner shows:
  - the tier and its progress toward the next one
  - the six society stats as meters, with the weakest one highlighted
  - what opens next, for example "Next: 🔬 Research opens at Township"

  `&stats=0` hides it.
- **Seedling characters.**
  - Each job wears something recognisable: straw hats for farmers, helmets with lamps for miners, hard hats for engineers and technicians, a fire helmet for firefighters, goggles for researchers, a medic cap, a chef's hat, a top hat for merchants, a cap for couriers, a ranger hat for explorers, and a bandana for processors and artisans.
  - Seedlings have arms that swing as they walk. Their eyes look where they are going, and they show their back when walking away.
  - While standing, they now and then wave at a neighbour or look around.
  - The overlay's `seedlings[].job` carries the job.
- **Quality presets.**
  - `&quality=high` adds soft light bloom at night, shimmering water on the lake, waving flags on the market hall and spaceport tower, and drop shadows under district labels.
  - `&quality=low` drops weather particles, building and cloud shadows, window glows, crowds and idle animations, for slower streaming PCs.
  - Measured on a 960×540 map at night: low about 3%, normal about 5%, high about 6% of one CPU core.

## Speech bubbles show the whole line

Map speech bubbles no longer cut lines off with "…". The full line wraps onto as many rows as it needs (up to about 200 units wide) and the bubble grows upward to fit. Near the left and right edges of the town the bubble slides sideways to stay on screen, and its tail still points at the speaker.

## The map follows the time of day

Morning, Day and Evening used to look almost the same on `/obs/map`: only a faint tint and the corners of the sky changed. The light now follows the actual Avesta hour (the overlay reports `hour`, 0–24), changing smoothly through the day:

- **Pre-dawn** is blue, **dawn** is pink, the **morning** is golden, and **midday** is bright and clear.
- The **afternoon** is warm, **sunset** is orange, **dusk** is purple, and **night** is deep blue with stars.

Other changes:

- **Sun and moon.** The sun rises on the left, crosses the sky and sets on the right, glowing orange when it is low. The moon follows it across the sky at night.
- **Building shadows** fall away from the sun: long and to the right at sunrise, short at noon, long and to the left before sunset.
- **Lights.** Windows and street lamps switch on gradually as it gets dark. Street lamps cast pools of light on the road.
- **Header.** The header shows the Avesta clock, for example "Day 2 · 17:00 Evening".
- **Phase banners.** A banner marks each phase change: "🌅 Dawn breaks over New Eridian", "☀️ Full daylight on Avesta", "🌇 The sun is setting" and "🌙 Night falls, the lights come on".
- **Preview.** Add `&hour=18` to the map URL to see any time of day (`&phase=Evening` still works).

## Map fixes: one speech bubble per line, and a caption bar that always fits

- **Speech bubbles pop up once.** A bubble used to replay its pop-in every few seconds, whenever the map re-sorted which Seedling stands in front. Now each line pops up once over the speaker, stays about five seconds and fades away. A Seedling never has the same line twice in its set.
- **Caption bar.** The name and activity sit on the first line, and anything too long ends in "…". What the Seedling says goes on the line below and wraps to a second line instead of running out of the bar. Text is sized from both the width and the height of the source, so it fits at any Browser Source size (checked at 640×360, 800×600, 960×540, 1280×720, 1920×540 and 1920×1080). The header and banners use the same sizing.

## The Avesta map comes alive

`/obs/map` is now a town you can watch. No OBS changes are needed.

- **Bigger town.** The outer ring road and empty ground are gone, and the town is drawn about 15% larger, so buildings and labels read better on stream.
- **Seedlings walk and talk.** Seedlings are little people (mood-coloured shirt, their initial, what they are doing) who walk along the streets from district to district, then stand under the district name. Every caption turn, the Seedling being named also speaks in a speech bubble.
- **More to say.** Each Seedling now has several lines, refreshed every ten minutes: its mood (twice as many thoughts per mood), what it is doing (the item it is gathering, its hobby, its job), where it is, the time of day, the weather, the market's top demand, what the society needs for its next tier, a holiday, and greetings to other Seedlings in the same district. The overlay's `seedlings[].lines` carries them.
- **Construction.** When a district levels up, scaffolding and a crane go up where the new buildings will stand, then the buildings rise about seven seconds later. A banner announces it ("Market grew to LV 9", "Research is open for building!", "New Eridian is now a City!") and the camera moves in.
- **Camera.** The view slowly zooms in on the Seedling who is speaking, then drifts back to the wide shot on the next turn. `&camera=0` keeps a fixed wide shot.
- **The town follows the numbers.** Fields turn dry when food is short and golden when food is plentiful (green in good growing weather). Chimney smoke grows with Industry and the Seedlings working there. At night, more windows light up as the population grows. Shoppers crowd the market with its level, today's demand and the Seedlings there.
- **Sky and weather.** The sky changes through dawn, day, dusk and night, with a sun, a moon and stars, drifting clouds and cloud shadows. Each weather has its own look:
  - Good Growing Weather: rain.
  - Dust Winds: a dust storm.
  - Light Siro Drift: spores.
  - Water Watch: overcast.
  - Busy Spaceport: shuttles taking off.
  - Quiet Cycle: fireflies at night.
  - Sensor Noise: sensor glitches, plus an aurora at night.
- **Holidays.** During each holiday's festival (from 30 days before until 7 days after), the town decorates itself. Bunting is strung along the streets (lit at night), and a centrepiece stands on the square in front of the Commons:
  - Christmas: a lit tree with presents, and snow.
  - Halloween: carved pumpkins by every street lamp, a giant jack-o'-lantern and a scarecrow, bats at night and falling leaves by day.
  - Thanksgiving: a feast table, hay bales, pumpkins and leaves.
  - Independence Day and Memorial Day: a flag.
  - New Year: a countdown ball and a "Happy <year>!" sign.
  - Valentine's Day: a heart arch and floating hearts.
  - Father's Day: a grill.
  - Labor Day: a thank-you sign.

  Fireworks go off in the evening and at night on the holiday itself, and in the days around New Year and Independence Day. Festival-goers fill the Commons, the header shows "🎃 Halloween in 12 days" or "🎄 Merry Christmas!", and Seedlings talk about the holiday.
- **Preview options.** Streamers can check a look ahead of time with `&holiday=christmas`, `&phase=Night` or `&weather=dust_winds`. `&days=3` previews a festival that is three days before its holiday.

## The Avesta map is a living town

`/obs/map` now draws New Eridian as an isometric town on a street grid instead of flat zones. Each district has its own buildings: houses with pitched roofs (apartment towers and domes as Homes levels up), striped fields, barns and greenhouses, factories with smoking chimneys and tanks, labs with dishes and a glass dome, a market hall with awning stalls, a spaceport with a control tower, landing pads and a rocket, frontier mine headframes and tents, a Commons with a fountain and statue, and a park with a lake. The town grows with the society: every level adds buildings (they rise into place, never disappear), roads get paved and lit as tiers go up, and districts that are not open yet show wild ground with survey stakes and the tier that opens them. At night windows and street lamps light up. District names sit in the middle of each district, and the Seedlings in a district line up under its name as coloured initials (mood colour, with what they are doing), so nothing overlaps; the caption bar still names each Seedling in turn. Options: `&names=1` adds names under the initials, `&per=6` shows more per district, `&seconds=7`, `&bg=0`. Same 960×540 Browser Source, no new setup needed.

## One rotating Hub panel instead of many

`/obs/hub` (640×360) rotates through everything the separate panels show: Society, Society stats, Today (directive, aftermath, festival), Live event, Project & story, Market, Leaders, Working now, Seedlings and News, and how to join, every 12 seconds. Slides with nothing to show are skipped, and a live event takes every other slide until it ends. `&seconds=` sets the pace; `&slides=society,event,news` picks and orders slides. The `/obs` setup page now leads with the recommended four sources (Hub, Map, Ticker, Alerts); the individual panels stay available. Leader and queue names drop bracketed tags.

## The Avesta map is readable on stream

`/obs/map` is rebuilt for broadcast at 16:9 (960×540 Browser Source). The view is zoomed onto the settlement; district labels use short names (Farms, Industry, Market, Research, Spaceport, Frontier, Homes, Commons) in large type sized to fit; Seedling tokens are twice as big with shorter names, at most five per place plus a "+N" badge; a header bar shows tier, population, day and who is working; and one large caption bar at the bottom rotates through each Seedling (mood, place, activity and thought) instead of small bubbles. The bars scale with the source, so the map stays legible when OBS shrinks it; half the stream width or more is recommended. Options: `&names=0`, `&per=5`, `&seconds=7`, `&bg=0`.

## No more "key resources"; Argentite is one rare ore among four

**Inventory.** The KEY RESOURCES block is gone. Pumpkin, Hematite Ore, Argentite Ore, Iron Nails and Cargo are listed with everything else under ITEMS, sorted by quantity (they keep their stock; only the special treatment went). The Twitch `!inv` line shows your five largest stacks.

**One way to sell.** The old five-resource market (`/market action:Sell`, the Sell raw goods button) is retired: everything sells to Seed Industries (`/seedindustries action:Sell`, `/menu` → Trade → Sell some / Sell all of…, `!sellall`). `!sell <item> [amount]` still works and now sells any item there. Daily market demand now applies to real natural materials: each Avesta day two of them sell for +60% and +30% (at least +1 SC) in every sale path. `/market action:Today's demand` and `!marketboard` show them; the overlay's Market Signal and the ticker follow.

**Argentite.** Argentite Ore is priced, bought and prospected exactly like Aurite, Bauxite and Rutile. Prospecting (`/work task:Prospect`, `!rare`) continues a rare ore you have already started, otherwise the rare ore you have least of; `/mine` still picks any specific ore.

## New Eridian News, a growing map, and Seedlings that gather and look after themselves

**News reports.** Every Seedling step is a news report built from what actually changed (items gained or used, Seed Coin, practice, needs before and after), never from the raw reply text: a desk (FARMING, SUPPLY, MINING, RESEARCH, TRADE, LOGISTICS, HEALTH, COMMUNITY, LEISURE), a headline ("Kamex brings in 1 Pumpkin") and a dated story ("AGRICULTURAL DISTRICT, Day 4 — Farmer Kamex gathered 1 Pumpkin this morning, earning +1 Harvesting practice."). Names drop bracketed tags. Failed shifts say what went wrong in the game's own words and what they cost. `/obs/narrator` is now a New Eridian News broadcast (LIVE bar, desk tag, headline, typed story, recent headlines). The ticker and the activity panel show the same plain facts; the activity panel shows the reply's own sentence instead of "Action completed".

**Real materials.** Working Seedlings gather real materials for their job through the normal gather code (farmers: Pumpkin, Corn, Tomato, Berries; miners: Hematite Ore, Coal, Stone…; technicians: Lumber, Stone, Clay…), alternating with job tasks (farming, repairs, research, cargo, market). When the player has a goal, materials the goal still needs come first.

**Needs first.** A Seedling eats below 45 Nutrition, rests or sleeps below 35 Energy or 30 Comfort, and finds company below 30 Social, before needs reach the work limit. A paused queue blocked by needs is recovered so it can carry on. Steps that change nothing (a cooldown) are retried two minutes later instead of being reported.

**A map that grows.** `/obs/map` is now a textured Avesta landscape with a river, craters, boulders and scrub. New Eridian starts as an Outpost behind a palisade; Industrial Ward and Market Concourse settle at Settlement, the Research Block at Township and the Spaceport at City (until then they are marked survey sites). Each district fills with its own buildings as its society stat grows (food → fields and greenhouses, materials → factories with smoke, knowledge → labs and turning dishes, treasury → market stalls, reputation → landing pads, population → homes and habitat domes, development → mine headframes and camps), and the wall and roads widen with each tier. Windows light up at night.

## Living Seedlings: schedules, moods, a diary, and the Avesta map

**Autonomy.** Every Seedling follows a daily schedule across the four Avesta phases (Morning, Day, Evening, Night), each set to Work, Free time, Social or Sleep. Presets: Balanced, Workaholic, Night owl, Socialite and Homebody, or a custom schedule with one dropdown per phase. While its player is away, a Seedling acts about once every `AUTONOMY_MINUTES` (default 10): it works its job's tasks, eats when hungry, sleeps when tired, practises its favourite hobby, walks, plays games, or says hi and hangs out with friends. Everything goes through the normal commands, so the same costs, cooldowns, gates and rewards apply. It never crafts, buys, sells or eats festival food; it steps aside while the player is active (10 minutes) or a queue runs; and it only runs for citizens seen in the last 3 days. Players switch it off with `/seedling autonomy:Off` or `!autonomy off`.

**Moods and thoughts.** Moods come from needs, morale, the weather and how the day is going: Inspired (+3% success), Content (+1%), Tired, Hungry, Lonely, Uneasy (−1%), Stressed (−2%) and Miserable (−4%). Each Seedling voices a short thought ("I miss Astra.", "This dust winds makes my skin crawl."). Mood appears in `/status`, `/seedling` and the stream map.

**Diary.** Everything a Seedling does is written as a line of story ("As dawn breaks over Avesta, Kamex tends the fields in the Agricultural District."). `/seedling section:Diary`, `/menu` → My Seedling → Diary, or `!diary`. The welcome-back popup now includes "While you were away".

**Commands.** `/seedling` (34 slash commands), `/menu` → 🌱 My Seedling (Overview, Let it decide, Diary, Schedule preset, Custom schedule, Autonomy on/off). Twitch: `!seedling`, `!diary`, `!schedule <preset>`, `!autonomy on|off` (`integrations/twitch/seedling_commands_ready.txt`).

**Stream.** `/obs/map` draws New Eridian on Avesta: the Commons and seven districts, each Seedling as a token coloured by mood that glides between places as it moves, day/night tint, Siro drift and dust particles, and thought bubbles. `/obs/narrator` types out the colony's story line by line. The ticker also carries narration. Guide panels 2 and 8 changed.

**Fix.** `!routine <n>` shared its URL with an older endpoint and never started saved routines; it does now.

## Stream overlay: live alerts, ticker, leaders and more

**Live alerts** (`/obs/alerts`). An animated pop-up for each notable moment: a new citizen, a level up, an achievement, a finished queue (3+ attempts), a society event starting, completing, failing or being called off, a new society tier, a completed project, a resolved weekly story and a finished daily directive. Big moments get a glow and sparks. Transparent when idle. Options: `&test=1` loops demo alerts for positioning, `&sound=1` plays a soft chime, `&seconds=7`, `&hide=queue,join`. The full `/overlay` dashboard shows the alerts top-centre automatically (`&alerts=0` turns them off).

**News ticker** (`/obs/ticker`). A scrolling crawl of the live event, recent highlights, the daily directive, market demand, any festival, the project, who is working and how to join.

**Leaders** (`/obs/leaders`), **Working now** (`/obs/working`, live queue progress bars) and **How to play** (`/obs/join`, rotating chat commands, plus your Discord invite when `DISCORD_INVITE_URL` is set).

**Setup page** (`/obs?channel=…`). Every panel with its URL, a Copy button, the Browser Source size and a live preview.

The activity panel gains action icons and slides new entries in. Highlights are kept in `stream_highlights_v1` (last 120) and society milestones are tracked in `stream_state_v1`; both are created automatically. `/api/v1/overlay` adds `highlights`, `leaders`, `working`, `festival` and `join` without changing existing fields (`overlay_version` 6.4.0).

## Every command is a button

Everything a slash command can do can now be done with buttons from `/menu`; the commands still work as before.

**New buttons.** Trade gains **Browse shop** (by category), **Buy** (item → Buy 1 / 5 / 10 / 25 / Other amount…), **Sell some** (Sell 1 / 5 / 10 / all, only amounts you have), **Sell raw goods** (crops, ore, rare ore, components, cargo) and **Start business** (a pop-up asks for the name). Work gains **Repair society**, **Repair gear** (pick a tool) and **Train a skill**. Craft → **Workshops** holds the station list, **Unlock station** (pick → confirm) and **Catalog by category**. Bag gains **Search bag** (pop-up), **By name**, **By category**, **Favourite ingredients** and **Sellable**. Help gains **Guide for…** (every /guide goal) and **Find** (pop-up). A new **Account** area has **Start / load citizen** and **Link Twitch** (a pop-up for the code from `!link`).

**Pop-up forms.** Anything that needs typing (search, a link code, a business name, a custom amount) opens a Discord pop-up form instead of a slash option.

**Long lists page.** Dropdowns with more than 25 choices (the 48 Seed Industries supplies, stations, big inventories) get Previous / Next page entries.

**Moderator area.** Moderators see 🛡️ **Moderator** on the Home screen: Start event (pick → confirm), Stop event, Moderator log, Account lookup (owners), Post guide panels, **Post game panel** and moderator help. Players never see it, and the buttons refuse anyone without moderator rights.

**Public game panel.** `/mod action:Post game button panel here` (or Moderator → Post game panel) posts a message anyone can press: Menu, Status, Life, Work, Craft, Queue, Bag, Trade, Find and Account. Each press opens that player's own private menu, so nobody needs to type a command. Pin it in the game channel.

**Richer replies.** Every slash-command reply now carries a row of that area's next actions above the Again / area / Menu row.

## Planning, repeating and tidying up

**Live countdowns.** Discord replies show times as live timestamps that count down on their own ("ready in 4 minutes"): sleep, cooldowns, passive recovery and when a queue finishes. Twitch gets plain "in 4m" text.

**Queue max.** Recipe, mine and gather panels gain **📦 Queue max ×N**: the most attempts your ingredients and needs allow (up to 10; auto-recover lifts the needs limit). Twitch: `!craftmax <recipe or resource>`.

**Recent actions and !again.** `/menu` → 🕘 Recent lists your last ten actions as one-tap repeat buttons. On Twitch, `!again` repeats your last task, craft, gather, food or item.

**Goal tracker.** 🎯 **Set goal** on any recipe pins it. The Goal view (`/menu` → Craft → Goal) shows ingredients ready, everything still to collect all the way down the ingredient tree, the sub-crafts on the way, and a **▶️ Fetch next** button that gathers, crafts or buys the next piece. `/status` shows the goal's next step; the goal clears itself (with a 🏆 note) when you craft it. Twitch: `!target <recipe>`, `!target`, `!target clear`.

**Plans and routines.** While a queue runs, queue buttons become **➕ Add to plan**: up to six later steps run one after another. Selling can be a step too ("Sell it after my queue" on the sell confirmation). **💾 Save plan as routine** keeps up to five routines to start again with one tap (`/menu` → Queue → Plan & routines). Twitch: `!routines`, `!routines save`, `!routine <n>`, `!routine delete <n>`.

**What can I make with this?** `/menu` → Bag → What can I make with… lists every recipe that uses an item, ready ones first. Twitch: `!uses <item>`.

**Welcome back and reminders.** After 3 hours away, a private summary shows queue results, needs, the daily contract, any festival and your goal's next step. One-off notes arrive when sleep is ready while you are tired, a festival opens, a new daily contract starts or your goal becomes craftable. All go through the private popups and `/menu` → Notifications.

**Auto-sell.** `/menu` → Bag → Auto-sell picks items (Stone Dust, surplus) to sell automatically whenever a queue finishes; ingredients of favourites and queued recipes are always kept. Twitch: `!autosell <item>` toggles, `!autosell` lists.

**Undo last sale.** Sell-all and clear-out results carry an **↩️ Undo** button for 60 seconds: items, Seed Coin and the Commerce practice go back. Twitch: `!undo`.

**Eat until full.** `/menu` → Life → Eat until full eats the cheapest everyday food until Nutrition reaches 80, in one go on one cooldown. Festival foods and Meal Kits are never used. Twitch: `!eatfull`.

**/find.** Search recipes, items, menu buttons and handbook topics at once; results are buttons. Twitch: `!find <word>`. The Discord menu now has 33 commands.

**Remember my place.** A bare `/make` reopens the Workbench category and page you last used.

New state lives in three additive tables (`player_extras_v1`, `player_recent_actions_v1`, `player_routines_v1`), merged when accounts are linked. Guide panels 4, 5, 6 and 8 changed. StreamElements lines for the new Twitch commands are in `integrations/twitch/quality_of_life_2_commands_ready.txt`.

## Private notifications and a short queue status

**Popups.** Queue results, pauses and warnings are kept in a per-citizen inbox (`player_inbox_v1`) and shown as a private "Only you can see this" message the next time that player uses any command or button (Discord only allows private messages as part of an interaction). `/settings popups:` chooses **Important** (default: queue results, pauses, warnings), **All** (also one-time tips) or **Off**. Queue alerts gain a **Private** mode: no channel ping, just the popup.

**When it's needed.** Starting a queue that will run out of needs or ingredients raises a warning right away ("Needs won't last all 10 attempts (Energy 30/38)…", "Pumpkin: enough for 4 of 10 attempts…"). One-time explanations appear the first time a player hits low Comfort, a mining failure, a blocked task, the sleep timer, or starts their first queue.

**Where to find everything.** `/menu` → 📬 Notifications lists the last 12 items and marks them read. The queue status is now short: progress, results, items gained and used (when there are any), the next queue, and a ⚠️ Heads up section only when something will stop the queue. Every requirement and rule moved behind **📘 Details & requirements** on the queue panel (also in `/menu` → Queue).

## Buttons for everything: /menu

`/menu` opens one window with a button for every area: Status, Life & Recovery, Work, Craft, Queue, Bag, Trade, World, Me, Social, Settings and Help. Pressing an area shows a button for each of its actions and views, with a one-line explanation of each:

| Area | Buttons |
| --- | --- |
| Life & Recovery | Relax, Sleep, Eat (food list), Games, Walk, Hobby (list), Share meal, Recover, Needs, Cooldowns |
| Work | Mine (ore list → Mine ×1 / Queue 5 / Queue 10), Gather (material list → same), all 14 work tasks, Training |
| Craft | Workbench, Ready now, Favourites, Workshops, Catalog and all 15 categories |
| Queue | Queue status, Repeat last, Cancel, Clear next, Status |
| Bag | Inventory, By value, For ready recipes, Quality gear, Use item (list), Eat (list), Sell all of… (list → Confirm), Clear out |
| Trade | Seed Industries, Starter routes, Orders, Deliver order (list → Confirm), Prices, Commerce work, Market analysis, Habitat, Upgrade home, Business, Business work, Contract, Invest |
| World | Overview, Conditions, Society, Next tier, Leaderboard, Event, Past events, Holidays, Project, Story, Bulletin, Rumor, Market |
| Me | Profile, Skills, Daily contract, Achievements, Collection, Bonuses, Traits, Relationships, Journal, Tutorial, Titles, Choices (Job, District, Shift, Delivery partner, Title, Specialize → Confirm, result style) |
| Social | With a citizen (list → Say hi, Hang out, Mentor, five duo activities), Games, Recreation Set, Share meal, Relationships |
| Settings | Alert modes, Auto-recover on/off, Favourites, Status |
| Help | What next?, Tutorial, Holidays and every handbook topic |

After an action the result appears with the same area's buttons again, plus Back and Menu, so repeating or moving on is one tap. Every slash-command reply also gets a row with 🔁 Again (for tasks), its area, and 🏠 Menu. Buttons run the same commands as the slash commands. Action buttons are single-use tickets; menus, lists and views spend nothing; irreversible choices (selling a stack, delivering an order, specializing) ask for confirmation. The Discord menu now has 32 commands.

## Readable, compact messages

Every Discord reply and Twitch line now goes through one presentation layer (`app/presentation.py`), which picks one of three shapes:

- **Task receipts** (work, crafting, gathering, eating, relaxing, selling, buying, unlocking) are small: a ✅/❌ title, what you got and spent (`**+3** Pumpkin · **+2** 🪙 SC · −2 Lumber`), needs spent (`⚡ −3 Energy · 🍲 −1 Nutrition · 🛋️ −3 Comfort`), practice (`📈 Farming +1 XP`), and at most a few lines for a failure reason, a level up, an encounter or a next-step hint. No footer and no Details button. Background numbers (society production, success chance, modifiers) stay out of the receipt.
- **Notices** (cooldowns, refusals, confirmations) are a single coloured line.
- **Information** (status, profile, guides, menus, previews, the handbook) keeps its full text: a short title-cased title, an intro with **bold labels**, and titled sections. Views longer than about 2,500 characters or 40 lines continue on Details pages.

Twitch uses the same rules: a task is one short line (`✅ Harvest Pumpkins · +3 Pumpkin · … · 📈 Farming +1 XP`); other replies fold headings into their first line, with empty pieces and "Needs: unchanged" removed. Workbench category pages show each recipe name in bold with its ingredients underneath, and queue alerts have state icons (▶️ ⏸️ ✅ ⏹️ ⛔). Failed work (for example "No task rewards were earned") is now coloured and labelled as a failure.

## Comfort, festival foods and a shorter Discord menu

### Comfort drains half as fast

Every task now costs as much Comfort as Energy: 2 for standard work, 3 for heavy work (it was double). `/relax` restores +20 Comfort (was +10). A full Comfort bar lasts roughly twice as many tasks. The rate is one constant, `COMFORT_PER_ENERGY` in `app/needs.py`, and the relax amount is `RELAX_COMFORT`.

### Festival foods are real items

The three festival recipes for each of the nine holidays (27 in total) are now catalog items. They are crafted at the free Survival Workbench from gathered ingredients, and only while that holiday's festival runs (30 days before to 7 days after, UTC). Outside the window the recipe shows 🔒 with its dates. The items keep, stack and sell all year. Eating one gives Nutrition plus bonus Comfort and Morale, and counts as prepared food (Rocky's Favor). The holiday calendar lists each festival's foods with ingredients and effects.

### A shorter Discord command list

51 slash commands became 31. Grouped commands run the original handlers, so rules, cooldowns and receipts are unchanged:

| New | Replaces |
| --- | --- |
| `/life action:` Relax, Sleep, Eat (+ Food), Games, Walk, Hobby (+ Hobby), Share meal, Recover | `/relax` `/sleep` `/eat` `/games` `/walk` `/hobby` `/meal` |
| `/work task:` every farming, scanning, research, logistics, spaceport and frontier option | `/farm` `/scan` `/rare` `/research` `/cargo` `/delivery` `/spaceport` `/explore` |
| `/mod action:` Start event, Stop event, Moderator log, Linked-account lookup | `/eventstart` `/eventstop` `/modlog` `/linklookup` |
| `/world section:` Society, Next tier, Leaderboard, Event, Event history, Holidays | `/society` `/event` `/holiday` |
| `/me section:` Skills, Daily contract, Achievements, Collection | `/progress` |

Game messages that mention a retired command are rewritten to the new one (for example "/relax" shows as `/life` → Action: Relax). Registration on deploy removes the retired commands from the server. Twitch commands are unchanged. [Discord guide panels](discord-guide-panels.md) has eight ready-to-post how-to-play messages.

## Quality-of-life update

Fourteen connected improvements aimed at the gather → check needs → craft → queue → wait loop. They share one additive preferences table (`player_preferences_v1`), so favourites, alert mode, auto-recovery and the follow-up queue show up consistently in every view.

### One place to look

- **`/status` and `!status`** show needs (with what blocks work and when passive recovery clears it), sleep readiness, the current or last queue with its remaining time and follow-up, active cooldowns, the top ready recipes (favourites first), a concrete next step and your settings. The Discord panel has Refresh, Ready now, Favourites, Workbench, Queue, Repeat and (when blocked) Recover now. The old `!status` society summary is now `!society`.
- **Next-step hints.** Craft and gather receipts for citizens below personal Tier 3 end with a Next step (a ready favourite, a ready recipe, or what to gather). Reaching a new personal tier is announced on the receipt that crossed it.

### Crafting

- **Ready now** and **Favourites** are listed before the fifteen Workbench categories (`/make category:`, the category menu, `!make ready`, `!make favs`). Ready now lists every recipe you can craft this moment, favourites first.
- **Favourites**: ⭐ Favourite / Unfavourite on every recipe preview, `/make action:Favourite`, `!fav <recipe>`. Up to 10. Starred recipes carry ⭐ in lists and dropdowns.
- **Fetch missing ingredients**: ❌ recipes have a 🧺 Fetch missing button (`/make action:Fetch missing`, `!fetch <recipe> [batches]`). The plan lists every shortfall with its best source: a gather or mine queue (ore attempts include spare attempts for failures), the recipe that makes it, or its Seed Industries price. One press starts the gather queue and queues the craft next; if a queue is already running it becomes the next queue instead. Buy missing buys every purchasable shortfall at once. `!fetchgo` starts the plan on Twitch.
- **Fuzzy names**: misspelled or partial recipe and item names resolve when the match is clear (`!make iron plat`, `!gather lumbr`, `!sellall ston dust`); otherwise the reply suggests up to three names. Nothing is spent on a suggestion.

### Queues

- **Repeat**: completion, cancellation and stop alerts carry 🔁 Repeat ×N, which opens the same queue's plan with Start. `/queue action:Repeat last` and `!queuerepeat` start it directly.
- **Next queue**: one follow-up slot starts automatically when the current queue completes (`/queue action:Queue next`, `!queuenext <task> <count>`, or the Queue next button that replaces Start while a queue is active). The completion alert says what started next. Cancelling a queue clears its next queue; Clear next removes it.
- **Recovery estimates**: pause reasons and alerts say when passive recovery clears each blocking need (rounded up to the minute) and when sleep is ready.
- **Auto-recover** (off by default; `/settings autorecover:On`, `!settings autorecover on`): before a queue pauses for low needs it runs the ordinary recovery commands that are ready — /relax, /sleep, a durable comfort item, your cheapest food (never Meal Kits; the emergency meal when you have none) and /games — then continues. Their normal cooldowns and effects apply, and pause alerts list what was tried. **Recover now** (`/status` button, pause-alert button, `!recover`) does the same once, on demand.
- **Alert preferences** (`/settings alerts:`, `!settings alerts`): channel mention (default), direct message (Discord; falls back to the channel when DMs are closed), quiet (finish and stop alerts only) or off. Results are always kept in `/queue`, `/status` and the journal.

### Inventory and selling

- **Inventory search**: `/inventory search: sort: show: page:` and `!inv <words>` find items by name or category; sort by quantity, name, sale value or category; show everything, items used in recipes ready now, items used by favourites, or sellable items. Each row shows its category, sale price and how many recipes use it.
- **Sell all**: `/seedindustries action:Sell all of one item` and `!sellall <item>` sell a whole stack at the listed price, with a note when a favourite uses it.
- **Clear-out**: `/seedindustries action:Clear out surplus materials` and `!clearout` preview selling Materials & Ores beyond 20 of each. Ingredients of favourites and of the current or next queued recipe are never included. Discord confirms with a single-use Sell button; Twitch with `!clearout confirm`.

### Deployment

Discord commands are re-registered by the container start command; `/status` and `/settings` are new and `/make`, `/queue`, `/inventory` and `/seedindustries` have new choices or options. New additive tables (`player_preferences_v1`, `queue_notice_tasks_v1`) are created automatically. Add the new StreamElements commands from `integrations/twitch/` (`!status` now points to `/api/v1/status`; the society view moved to `!society`).

## Workbench, Comfort and catalog-only items

### Crafting through the Workbench

`/make` (and `!make` on Twitch) opens a Workbench with fifteen categories shared with `/catalog` and `/use`. Each category lists recipes from easiest to most complex: the personal tier the whole ingredient chain needs, then skill level, then crafting steps from raw materials. A recipe preview shows owned/needed ingredients and where to get each one, the batch size, workstation, tier, skill, needs cost and cooldown before anything is spent.

In Discord the Workbench is a set of dropdowns and buttons: pick a category, page through it, filter by workstation, open a recipe, then Unlock its workstation, Craft 1 batch or queue 1–10 batches. Queues show their totals first and start only when Start is pressed. `/mine`, `/gather` and `/queue` gained the same buttons. Spending buttons are single-use tickets: double clicks, retries and old messages cannot spend twice, and only the citizen who opened a panel can use it.

Every dropdown label follows one pattern: status (✅ ready, ❌ missing, 🔑 workstation fee, 🔒 locked), name and amount, then the cost or blocker. Work options show yield per success plus Energy and Comfort per attempt; the queue list shows common ores before rare ones and marks locked rare ores.

### Comfort and sleep

Every task costs twice as much Comfort as Energy (a standard task: 2 Energy, 1 Nutrition, 4 Comfort). Below 20 Comfort, work has −10% success and costs 1 Morale per task; below 10 it stops. Sleep still restores Energy and Comfort to 100, but only once every 30 minutes (`SLEEP_COOLDOWN_MINUTES`). Between sleeps, Comfort comes from `/relax`, owned beds, seats, baths and clothing through `/use`, and the Habitat Comfort Pack.

### Catalog items everywhere

All legacy items now resolve to SEED catalog items, and duplicate stock is merged one-for-one into a single balance: Crops = Pumpkin, Components = Iron Nails, plus Biofiber, Alloy Plate, Sealant, Precision Lens, Ration, Water Filter, Sensor, Crate and the training products (see the [gameplay reference](gameplay.md#catalog-items-replace-legacy-items)). Old names still work as command input. Legacy recipes open the matching catalog recipe with its workstation, tier and skill gates. Specialist quality gear remains an upgrade system; its crafting and repair ingredients are catalog items. Farming, markets, orders, meals, repairs and Habitat upgrades use the same catalog stock. Because Iron Nails are crafted 15 per batch, Nails costs are five times the old Component amounts (Habitat upgrades, gear repair) and Nails sell at the catalog price.

### Deployment

Re-register Discord commands after deploying (`python -m scripts.register_discord_commands`): option descriptions and choices changed, and `/make` has new Action, Count and Workstation options. The additive `ui_tickets_v1` table is created automatically. The current option contract is regenerated in `tests/contracts/discord_options.json`.

## Discord mining acknowledgement

`/mine` and `/queue` acknowledge the interaction before running database work. A background thread executes the command and edits the original private response. Delivery retries never rerun the command. Original-channel completion mentions are unchanged. Other synchronous command handlers run in a thread pool so they do not block the ASGI event loop.

## Mining failure rewards

Mining uses work success rolls and grants one Stone Dust on failure. Rare-ore failures preserve saved progress and require three successful prospecting steps per ore. Common mining, Coal, rare extraction, machine extraction and legacy mining/training routes share this behavior. Queue summaries and channel notifications include the failure reward. This package also contains the automatic queue, channel mention, Coal and task-yield updates.

## Automatic queues, channel mentions and task yields

Queues check work every ten seconds independently of chat activity. Completion produces a durable channel notification that mentions the initiating player. Resource options now expose their success yields and Energy costs, including improved farming, research, exploration, spaceport, commerce and business outputs. Coal is classified as a mining resource without changing the catalog file or its existing price. This update includes the earlier cumulative queue outcome fix.

## Queue outcome totals

Queue status now reports successful attempts, failed attempts, and total inventory gained and used across the queue. Actual quantities include recipe batch sizes and bonus material yields. Rare-ore prospecting steps without an ore reward are reported separately from failures. Pauses and cooldown waits do not count as attempts.

Totals persist with the queue and commit atomically with gameplay changes. Viewing results does not award items again. Older attempts whose outcomes were not recorded are explicitly marked as unrecorded; existing player inventory is preserved.

## Mining, queues and repository consolidation

This release combines the previously uncommitted mining/queue update with repository cleanup. It does not require an intermediate deployment.

### Player-facing changes

- Ore selection and requirements are available through `/mine`; `/gather` lists non-ore materials.
- One persistent queue can repeat a selected task up to ten attempts, with automatic pauses and recovery-based resumption.
- Forecasts show remaining needs costs and material shortfalls. Grammar and requirement wording were revised across the affected flows.
- Prior unified-item conversion, crafting workstations, personal recipe tiers and slow passive recovery remain included.

### Structural changes

The `app/` package now contains the implementations previously stored at the root. Wrapper modules and the private dynamic loader are gone. The registrar lives in `scripts/`; tests, historical fixtures, current contracts and Twitch definitions each have dedicated locations.

The duplicate installer Dockerfile, duplicate dependency list and superseded balance patch script were removed. Overlapping conversational update/setup documents were replaced with architecture, persistence, gameplay, deployment-reference and validation notes. Their historical versions remain in Git history; they are not active documentation.

The container copies only application and operational code. Cache files, local databases and environment files are excluded from version control and container context. The ASGI target, health route and deployment descriptors remain compatible with the existing service.

### Compatibility

All existing regression tests remain present. The catalog JSON and historical Discord option evidence are preserved byte-for-byte. Storage names, item conversion rules and player progress are unchanged by the move. Supplemental and seasonal routes are registered after core application initialization, as before.

### Known limits

`app/main.py` remains large; this cleanup resolves source ownership and file organization, not every possible architectural refactor. Live Railway, Discord, Twitch and PostgreSQL deployment behavior have not been exercised here. Automated validation details are recorded separately.[^1]

[^1]: [Validation record](testing/validation.md) and [raw test results](testing/results.txt).

## Compact Discord messages

Discord responses now open as compact cards with outcome, rewards, needs and
blockers ahead of background information. Queue cards summarize attempts,
successes, failures, prospecting steps, actual item totals and needs required
to finish. Empty item sections and repeated instruction sheets no longer fill
the overview. New Eridian remains the society name.

Long responses retain their complete command text in small Details pages.
Browsing is private and read-only; it never reruns a command. On private cards,
Previous, Next and Overview update the same message. Public cards open a private
copy so another player's view is not changed. Completion alerts still @mention
the player in the game channel and now use the same compact card styling.

## Queue reliability and action receipts

Queues now record durable stop events for completion, unmet needs or materials,
cancellation, and repeated internal errors. Needs are checked after each saved
attempt, so a player receives the pause alert without waiting for another
attempt. A pause retains its remaining work and resumes after recovery. Only
state transitions create alerts; background checks do not repeatedly ping the
player. A pending pause alert is superseded when its queue resumes or is replaced.

Unexpected attempts roll back and retry with backoff. Three consecutive errors
stop that queue and create an error alert. Completing an attempt, updating its
totals and recording its stop event share one transaction. Delivery failures do
not replay gameplay. Discord can fall back to a plain-text alert when embeds
are forbidden. Missing credentials or channel permissions remain delivery errors.

Discord slash commands acknowledge before database work. Saved interaction
receipts prevent repeat deliveries of the same interaction from applying the
command twice. Formatting failure falls back to the saved result. Shared
transaction handling also covers HTTP game endpoints, account linking and
shared-world balances. PostgreSQL URLs select the installed psycopg driver;
connection/statement/lock timeouts bound database waits. Health checks now verify
the database and detect stopped workers. Administrative routes reject unset or
placeholder keys.

Action receipts show the action outcome, inventory/currency changes, needs
changes, practice and immediate recovery requirements. Secondary items and
consumed-to-zero items are included. General world conditions, permanent item
bonuses, handbook text and repeated guidance are omitted from action receipts;
their dedicated views remain available. No unsolicited modifier follow-up is
sent after an action. Queue and informational views retain private detail pages.

## Discord.py channel alert patch

Queue scheduling now uses `discord.ext.tasks`. Discord delivery uses an
independent asynchronous outbox worker and `await channel.send`, producing a
second channel message with the initiating player's mention. Twitch delivery
uses a separate filtered worker, preventing both senders from claiming the same
Discord notice. Saved deadlines, attempts, totals and transactional stop events
retain their existing behavior.

Missing credentials no longer consume Discord delivery attempts. Authentication
state and concrete channel errors are exposed through health/queue views and
logs. Login checks the configured application identity. A startup recovery scan
repairs recent current-run stop alerts after deployment, without replaying sent
messages or granting gameplay rewards again. DMs remain disabled.
