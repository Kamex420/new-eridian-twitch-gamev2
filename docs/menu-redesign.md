# Menu redesign

Status: **approved** by Kamex on 2026-10-08. All six decisions are recorded at the end ("Decisions for you").

## In short

- **24 areas become 16**, and nothing is more than two taps below Home (Home → area → sub-area).
- **Home keeps 6 areas**, with **Do this next** as the first, green button at the very top.
- **Every area shows 5–7 main buttons.** Everything else sits behind one **More** button: less-used options under
  "Also here", and locked ones under "Not yet", each with the reason and a **How to get it** button.
- **On/off pairs become one button** that shows the current state (Auto-recover: On), so they never clutter a screen.
- **Plainer names**, and no two buttons share a name.
- Slash commands, rules, cooldowns and one-time tickets are unchanged. Only the buttons and their layout change.

## What the review found

Home already has six area lines (Work, Craft, Life, Bag & Trade, Colony, You) and a Next step button, so Home itself
needs only a small change. The clutter is one level down:

| Area today | Buttons | Problem |
|---|---|---|
| Work | 11 | 4 tiny sub-areas (Farming, Research, Logistics, Frontier) with 2–4 buttons each |
| Life | 13 | most buttons on one screen; Social is a sub-area of 3 |
| Bag & Trade | 15 | plus Bag (8) and Home & Business (7): 30 options in one corner |
| Colony | 13 | two different "More…" dropdowns and a separate "Season more…" |
| You | 9 | 4 sub-areas, and Looks is 3 levels deep (You › My Seedling › Looks & personality) |

Other things that make it harder than it needs to be:

- **Same name, different thing:** "Notifications" is both the inbox and a setting; "Leaderboard" is both top helpers
  and the season top ten; "Workshops" is an area and a view inside it; "Research" is an area and a job inside it;
  "Overview" is the town and the Seedling; "More…" opens two different dropdowns; 🏠 means Menu, Home & Business and
  Habitat.
- **On/off pairs take two buttons:** Auto-recover, Autonomy, Compact/Detailed results, Show/Hide in the feed, Quiet
  hours on/off.
- **Locked options are easy to miss:** they disappear and are listed on one 🔒 line at the bottom of the card.
- **Next step is styled like everything else** and sits below the needs and queue lines.
- **Duplicates:** Catalog is in Craft and in Bag; Sell some and Sell all of… are two flows for one job; Colony vote
  and Cast your vote are two buttons for one ballot.

## Home

```
🏠 NEW ERIDIAN — Kamex
➡️ Gather Pumpkin Seeds · for your goal: Campfire        [ Do this next ]
⚡ 72 · 🍲 40 · 💬 55 · 🛋️ 80 · 🪙 1,240 SC              [ Life ]   (only while a need is under 50)
▶️ Running: Gather Stone · 3/10 done · finishes in 12 min  [ Queue ]
📋 Today's contract: Harvest Pumpkins 0/3 · 9 SC         [ Harvest ]   (only while it is not done and not the Do this next pick)

⛏️ Work — gather, mine, farm, train skills, daily contract, queues  [ Work ]
🛠️ Craft — your goal, recipes, shopping list              [ Craft ]
❤️ Life — eat, sleep, rest, friends                       [ Life ]
🎒 Bag & Shop — what you own, buy, sell, your home        [ Bag & Shop ]
🏘️ Town — event, vote, season, trophies, news             [ Town ]
👤 You — profile, Seedling, looks, settings               [ You ]

[ 📖 Help ]  [ 📬 Notifications (3) ]  [ 🔁 Do again ]  [ 🛡️ Moderator ]
```

The Life, Queue and contract buttons sit beside their lines in Discord's newer layout only; the older layout keeps its
rows. Queue opens Queue status (a paused queue already has **Fix my queue** for that). Life opens the Life area. The
contract's button is the one the Daily contract screen has (a grey **Daily contract** when the contract has no button
of its own). Notifications shows how many are unread, `(99+)` past 99.

Moderator shows only for the owner, as today. The **Status** button leaves Home: Home's own header already shows
needs, SC, the queue and the next step. Full Status moves to You › More, and the public game panel keeps its Status
button.

### Do this next

The button already exists (`home_next`, labelled Next step). The redesign moves it to the top line, makes it green,
renames it, and has the line say what and why. The button can read "Do this next" or name the action when it is short
("Recover", "Campfire").

It picks the first of these that applies. 1, 3, 4 and 7 exist today; 2, 5 and 6 are new and up to you.

1. A need blocks work → **Recover**.
2. *(new)* Your queue is paused → **Fix my queue**: opens Queue status, which shows why it paused.
3. First steps not finished → that step (+SC shown).
4. You have a goal → the goal's next step.
5. *(new)* Today's daily contract isn't done → a green button that does the task itself (Mine, Harvest, Irrigate, Train Fire Safety…; `menu.DAILY_LEAF` lists them). The Daily contract screen has the same button beside its Task line. Home shows the contract under the queue line whenever it is not done and this is not the pick; when it is, Help › What next? leaves out the guide's own "Daily:" lines (Do this next, right under its heading, already says it).
6. *(new)* Your last queue finished and nothing is running → **Repeat last queue**.
7. Otherwise → **Find a goal**.

## How "More" works

Every hidden button is one of three kinds, and each kind is handled one way:

| Kind | Example | Where it goes |
|---|---|---|
| **Switch** (on/off, or one-or-the-other) | Auto-recover, Stop queue vs Repeat last | One button showing the current state. Never in More, never listed as locked. |
| **Locked** (needs an item, tool, business or festival) | Hydroponics: needs a Small Water Filter | More › **Not yet**, with the reason and **How to get it** |
| **Extra** (works, used less) | Fix the town, Weather & time | More › **Also here** |

The More button shows what is inside, e.g. **More · 4 to unlock**. Not yet lists the ones you can fix right now first (another button fixes it, then an item to get, then the rest). When a locked option becomes usable it moves to its
own spot automatically (the same `can()` checks as today). The "🔒 Not available right now" line goes away.

**How to get it** opens Find with the question already asked ("how do I get a Small Water Filter?"), so it uses the
no-AI Find you already have. For reasons that aren't an item (start a business first, Halloween only), it opens the
place that fixes it, or shows no button.

Example, Work › More:

```
🏠 Menu › ⛏️ Work › More
ALSO HERE
🔧 Fix the town — repair settlement systems (Engineering)        [ Fix ]
NOT YET
💎 Mine rare ore — needs a Mineral Extractor                     [ How to get it ]
🧪 Hydroponics — needs a Small Water Filter                      [ How to get it ]
🗺️ Survey — needs a Resource Scanner                             [ How to get it ]
🪛 Fix a tool — you have no quality gear yet                     [ How to get it ]
[ ◀️ Back ]  [ 🏠 Menu ]
```

## The six areas

Main buttons are listed in order. Buttons marked *(only when…)* are switches.

### ⛏️ Work
- **Main:** Gather · Mine · Farm · Other jobs · Train skills · Queue status · Daily contract
- **Farm:** one list of Tend fields, Harvest, Irrigate, Hydroponics, each with what it gives and a button.
- **Other jobs:** one list of Scan, Research, Field analysis, Cargo, Delivery, Spaceport, Spaceport rush, Scout,
  Survey, each with what it gives.
- **More:** Fix the town · Fix a tool, plus locked jobs (Mine rare ore, Hydroponics, Field analysis, Survey,
  Spaceport rush, Delivery when you have no Cargo).
- **Queue** (no longer a Work button; older buttons and tickets still open it, and its Back goes to Work): Queue status ·
  Repeat last *(only when finished)* · Stop queue *(only while running)* · What runs next · Clear what runs next *(only when
  something is planned)* · Queue rules. The queue screen itself has a grey **What runs next** button on its second row,
  beside Queue rules.
- **Daily contract** (moved here from You): its screen shows Work's buttons, crumb and Back.

Replaces the Farming, Research, Logistics and Frontier sub-areas.

### 🛠️ Craft
- **Main:** My goal · Ready to craft · All recipes · Shopping list · Favourites
- **More:** Workstations · Unlock a station · Item list (with its by-category dropdown)

Replaces the Workshops sub-area. Item list lives only here (it is removed from the bag).

### ❤️ Life
- **Main:** Recover *(only when a need blocks work, which is the only time it does anything)* · Eat · Eat until full ·
  Sleep · Relax · Games · Friends · Trick-or-treat *(only during Halloween)*
- **Friends** opens the citizen list directly; choosing one shows Say hi, Hang out, Mentor and the duo activities, as
  today.
- **More:** Walk · Hobby · Share a meal · Needs · Cooldowns, plus locked Group games (needs a Recreation Set).

Replaces the Social sub-area. Relationships moves to You.

### 🎒 Bag & Shop
- **Main:** My bag · Use · Buy · Sell · Orders · Home & business
- **My bag** opens the inventory with Sort & filter, Search bag, Sell, Use and Buy under it (Sell and Use only when there is something to sell or use).
- **Sell** is one flow: pick an item, then Sell 1 / 5 / 10 / 25 / all N / other amount. It keeps today's keep-level
  note and the "Sell it after my queue" button. Undo sale stays on the result of every sale, where it is needed.
- **More:** Sell extras · Shop by category · Starter shopping · Best prices today · Trade for SC · What can I make
  with…? · Auto-sell · Always keep · Deliver an order, plus locked Market analysis (needs a Market Analyzer).
- **🏡 Home & business** (sub-area): Your home · Upgrade home · Your business · Start a business *(only without
  one)* · Business work · Contract · Invest. Without a business, the last three are in its More as locked.

Replaces the Bag sub-area.

### 🏘️ Town
- **Main:** Event *(only while one runs)* · Stream challenge *(only while one runs)* · Today's vote · Season ·
  Trophies · Town news
- **Today's vote** opens the ballot itself: each option with its vote count and a Vote button (one screen instead of
  two).
- **More:** Weather & time · Town's next tier · Top helpers · News & story… (bulletin, rumor, story, project,
  society, market, holidays, past events) · Season details… (top ten, rewards, story, my hats) · Trophy group…

Wear a hat and Pin a badge move to You › Looks.

### 👤 You
- **Main:** Profile · Skills · My Seedling · Looks · Job & role · Settings (the Daily contract moved to Work)
- **More:** Achievements · Full status · Collection · Bonuses · Traits · Relationships · Journal · Titles · Tutorial
- **🌱 My Seedling:** Overview · Let it decide · Diary · Schedule (presets and Custom… in one list) · Lives on its
  own: On/Off
- **🎨 Looks** (moved up from My Seedling; everything cosmetic in one place): My look · Body… (skin tone, hair style,
  hair colour) · Clothes… (outfit colour, accessory, headwear) · Voice… (attitude, catchphrase) · Wear a hat ·
  Pin a badge · Show a title. Hat, badge and title go to its More as locked until you have one.
- **🧭 Job & role** (was Choices): Job · District · Shift · Delivery partner · Specialize
- **⚙️ Settings:** Queue alerts · Pop-ups after commands · Quiet hours · Auto-recover: On/Off · Activity feed:
  Shown/Hidden · Results: Short/Full · Link Twitch *(only until linked)*. More: Start / load citizen.

Replaces the Account sub-area (Link Twitch moves into Settings).

### Help, Do again, Moderator

- **Help:** What next? · Guide for… · Ask or search · Handbook · About (only Find is renamed).
- **Do again** is today's Recent actions, renamed.
- **Moderator** keeps its buttons; only you see it. Its lines sit under three headings: EVENTS, POSTS and RECORDS (`menu.GROUPS`).

## Renames

| Today | Proposed | Why |
|---|---|---|
| Next step | Do this next | your wording; says it's an action |
| Recent actions | Do again | says what the screen is for |
| Bag & Trade | Bag & Shop | "trade" reads like player-to-player |
| Colony | Town | the hints already say "the town" |
| Choices | Job & role | says what's inside |
| Looks & personality | Looks | shorter; the personality pickers sit under Voice… |
| Home & Business (🏠) | Home & business (🏡) | 🏠 means Menu only |
| Prospect | Mine rare ore | |
| Expedite | Spaceport rush | |
| Repair society / Repair gear | Fix the town / Fix a tool | |
| Cancel queue | Stop queue | |
| Plan & routines / Clear next | What runs next / Clear what runs next | |
| Details & requirements | Queue rules | |
| Goal / Ready now / Workbench | My goal / Ready to craft / All recipes | |
| Workshops (view) | Workstations | the area of the same name goes away |
| Catalog | Item list | |
| Inventory | My bag | |
| Sell some + Sell all of… | Sell | one flow |
| Clear out | Sell extras | |
| Keep levels | Always keep | |
| Browse shop | Shop by category | |
| Starter routes | Starter shopping | it's what to buy for each skill |
| Today's demand | Best prices today | |
| Commerce work | Trade for SC | |
| With a citizen | Friends | |
| Recreation Set | Group games | names the activity, not the item |
| Colony vote + Cast your vote | Today's vote | one screen |
| Overview (Colony) | Town news | was a duplicate name |
| Conditions | Weather & time | |
| Next tier | Town's next tier | |
| Leaderboard (Colony) / Leaderboard (season) | Top helpers / Season top ten | were duplicate names |
| Season more… | Season details… | "More" now means one thing |
| Equip title | Show a title | |
| Notifications (setting) | Pop-ups after commands | was a duplicate of the inbox |
| Auto-recover on / off | Auto-recover: On/Off | one button |
| Autonomy on / off | Lives on its own: On/Off | one button |
| Compact / Detailed results | Results: Short/Full | one button |
| Show me / Hide me from the feed | Activity feed: Shown/Hidden | one button |
| Quiet hours / Turn off quiet hours | Quiet hours | one button: sets them when off, offers Change or Turn off when on |
| Schedule preset / Custom schedule | Schedule | one list |
| Find | Ask or search | |

## Where each of today's 24 areas goes

| Area today | After |
|---|---|
| home, recent, work, queue, craft, life, help, mod, settings, seedling, looks | kept (some renamed or moved) |
| trade, community, me, choices, property | kept, renamed: Bag & Shop, Town, You, Job & role, Home & business |
| farming | Work › Farm (a list) |
| science, logistics, frontier | Work › Other jobs (one list) |
| stations | Craft › More |
| social | Life › Friends (opens the citizen list) |
| bag | Bag & Shop › My bag (opens the inventory) |
| account | You › Settings › Link Twitch |

16 areas remain, and each gets a generated More screen (not a separate area).

## Keeping old buttons working

- **Area keys stay the same** where an area is kept (`trade`, `community`, `me`, `choices`…); only titles change.
  The posted game panel keeps working without being reposted (its Account button gets an alias).
- **Removed area keys get aliases** (like today's `MERGED`): `mn|farming` opens Work › Farm, `mn|bag` opens My bag,
  `mn|account` opens Settings, and so on, instead of silently falling back to Home.
- **Merged leaves keep their old keys** as aliases (`sellsome` → `sell`, `c_vote_pick` → the vote, `auto_off` → the
  Auto-recover switch, …).
- Grouped dropdowns (`leaves:`) can only hold views today; Looks' Body…, Clothes… and Voice… need them to open pickers
  too (a small change in `navigate`).

Text that names today's menu paths and needs updating when this is built:

- `app/ui.py` `public_panel` (Bag & Trade, Colony, Account, and its description lines)
- `app/game/training_and_items.py:248` and `app/game/routes_market.py:38` ("/menu → Bag & Trade")
- `app/twitch_lite.py:33–34` ("/menu → Bag & Trade → Bag")
- `app/looks.py:3, 157` ("You → My Seedling → Looks & personality")
- `app/activity_feed.py:215` (a "Community" button)
- `docs/gameplay.md:136`, plus a player-facing entry in `docs/releases.md`

Tests that open removed areas by key: `tests/test_back_button.py`, `tests/test_layout_v2.py`,
`tests/test_menu_guidance.py` (`farming`) and `tests/test_keep_levels.py` (`bag`). Around 15 test files touch the
menu in some way.

## Decisions for you

Answered by Kamex on 2026-10-08.

1. **Names:** Town or keep Colony? Bag & Shop or keep Bag & Trade?
   → **Society** (replaces Colony; the first build used Town by mistake, fixed the same day) and **Bag & Shop**
   (replaces Bag & Trade).
2. **Status off Home** (still in You › More and on the public panel): OK?
   → **Yes.**
3. **Do this next:** which of the new checks to add: paused queue, daily contract, repeat last queue (all, some or
   none)?
   → **All three** (paused queue, daily contract, repeat last queue).
4. **How to get it** buttons in More, using Find: yes or no?
   → **Yes.**
5. **Looks moves up to You**, with hats, badges and titles joining it: OK?
   → **Yes.**
6. **Merges:** Sell some + Sell all into one Sell; Colony vote + Cast your vote into Today's vote: OK?
   → **Yes**, both merges.

## Building it (after approval)

One session: restructure `AREAS`/`LEAVES`/`WHEN` in `app/menu.py`, add the More screen and the single-button
switches, extend `home_next`, add the aliases, update the text listed above and the tests, then the usual
branch → full test suite → Tests workflow → main. Implementation goes to Sonnet, with an Opus review of the
result and the player-facing text.
