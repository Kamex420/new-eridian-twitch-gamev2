# Release notes

## Every task practises a skill, with lucky finds

- **Every task gives XP now.** Gear repair gives Engineering and Maintenance & Repair practice, building with `/use` gives Engineering practice, and supplying the clinic gives Medicine practice. Everything else already did.
- **Lucky finds.** After a successful task there is a 15% chance (25% after an especially good result) of finding one common item from the same line of work: a Harvester turns up Clay or Coal, a cook Salt or Tomatoes, a medic Herbs or Golden Cap, a trader a spare Cargo. Training tasks find items from their own branch. The reply says "🎁 Lucky find (Skill): +1 Item", and queues and autonomous Seedlings find things the same way.
- Life and social actions (eating, sleeping, relaxing, games, hangouts) and buying or selling never find anything, and a failed attempt finds nothing either.

## Goals walk you through skill levels too

A goal that needs a skill level now shows how to get it, step by step, instead of only pointing at the training list.
- **The training task that practises the skill**, with how many tries it takes (for example "Do Chemistry ×8: practises Chemistry to Lv 2, makes Antiseptics at the Medical Fabricator").
- **Everything that task needs first**: its own skill level (the same way, one level down, such as Water Treatment for Processing Lv 3), the machine for its workstation with everything the machine needs, and its ingredients, gathered or crafted, never bought.
- **The training list says what each task makes and where.** Chemistry, for example, makes Antiseptics at the Medical Fabricator, so it no longer looks like it needs a Chemistry Station. A missing workstation reads "craft its machine, or unlock it in /workshop".

## Fan project notice

The game now says plainly that it is a free, unofficial fan project made by Kamex, not affiliated with Klang Games (the makers of SEED), with nothing to buy.
- **Help → About** (also `/seed topic:About`, and `!seed about` on Twitch) shows the full notice: who made it, that it is unofficial and free, that SEED's names, items and lore belong to Klang Games, and how a rights holder can ask for changes.
- Every Discord card's footer now reads "New Eridian v2 · a fan project by Kamex".
- A short version is in the first newcomer guide panel, on the pinned game panel and in a new player's first welcome.

## A quieter game channel

The game posts far less in the Discord channel, so nobody needs to mute it.
- **Replies are private.** Life and work commands (`/relax`, `/eat`, `/work`, `/recover`…) now answer only the player who used them, like the menus already did. Moderator event announcements stay public, and Share still posts a card for everyone on purpose.
- **Queue alerts come by direct message.** Pauses and finishes are a DM by default instead of a channel @mention. If a player's DMs are closed, the alert waits privately in their Notifications rather than going to the channel. Quiet alerts are DMs too. Anyone who wants channel mentions can still choose them in `/settings`; players still on the old default were moved to DMs once.
- **The activity feed updates every 20 minutes instead of every minute.** It keeps editing one message while nobody else posts, and big moments (events, challenges, votes, tier-ups) still go out at once.

## Goals make everything themselves

The goal no longer tells you to pay SC to unlock a workstation. When something on the way needs a workstation you cannot use yet, the goal walks you through crafting that station's machine (owning it opens the workstation), with every material and part the machine needs, all the way down. The steps run in the order you do them: collect the materials, craft each machine and part after its own ingredients, then craft the goal. The goal's header says which machine it needs. Unlocking for SC stays available in Workshops for anyone who prefers it.

## Menus that lead the way

The menus are simpler, and the goal now walks you through everything it needs.
- **Your goal walks you through it.** The Goal view lists every step still needed, in order, with a button beside each one: Gather or Mine (runs a queue), Buy, Craft the parts, **Train** for a skill level, **Craft** toward a personal tier, **Help** the colony reach its tier, or see when a festival opens. If a step costs more SC than you have, its button shows how to earn SC. After any step, the result has a 🎯 Goal button back to the walkthrough.
- **Home starts with your next step.** The top of `/menu` shows one next step and its button: get blocked needs back up, the next of your first steps, your goal's next step, or choose a goal.
- **Six areas instead of eighteen.** Work (the Queue moved here), Craft, Life, Bag & Trade (the Bag moved here), Colony (World and Community together) and You (profile, Seedling, Settings and Account; hats and badges moved to Choices). Status, Notifications, Recent and Help sit in a row below.
- **Buttons say what they do.** No more rows of "Open": each button names its place or action (Work, Relax, Status, Browse, View, Craft, Train, Unlock), and the line beside it says what it does. Areas are blue, actions green and views grey.
- **The same navigation everywhere.** Each menu screen shows where you are (🏠 Menu › ⛏️ Work › 🌾 Farming) above its title, and every screen ends with 🏠 Menu in the same place, including Workbench, queue, status and Details pages.

## Buttons never time out

Pressing a button or sending a form no longer shows Discord's "This interaction failed".
- Discord gives a press 3 seconds to be acknowledged. The game used to work out the whole answer first, which could take longer on a busy or distant database. Now every press is acknowledged at once and the answer follows right after.
- On your private panel, the panel changes in place as before. A press on a shared message (the pinned game panel, a channel alert) answers privately under "thinking…", so a shared message never changes for everyone.
- Buttons that open a form still open it straight away.
- If something goes wrong, you get a private note that nothing was spent, instead of a press that silently does nothing.

## Discord's newer layout for every message

Every message the game sends on Discord now uses Discord's newer message layout (Components V2) instead of embeds, so it is easier to read and everything looks the same.
- **One card per message.** The colour strip stays. The title is a heading, and each section sits under a divider line.
- **A button beside each item.** Menus (every area of `/menu`), choice lists (foods, hobbies, the colony vote, settings…), Workbench categories and recipe pages, and a skill's tasks in the Item Menu show each item with its own button beside it: Open, an action such as Relax or Vote, or Start for a task. Discord allows 40 parts per message and a button beside an item takes three, so lists of up to about ten items get a button beside every item; on longer lists (the main menu, the Workbench categories) the first items do, and the rest keep their buttons in a row below.
- **Lists stand out.** Each item's name is bold and its details sit in a quote under it. Legends, how-to-use lines and notes after a list are small grey text.
- **Everything in the same style.** Slash command replies, button and menu answers, Details pages, private popups, one-line notices, queue alerts (the ping is the card's first line), the activity feed, the weekly recap, the pinned game panel and the guide panels.
- **Showing less.** The Item Menu no longer repeats where every material comes from (that is in `/catalog` and every recipe preview). Workbench pages list 8 recipes, so each fits with its button. Every menu button now has a line saying what it does (farming, research and logistics tasks, world and profile views).
- **Safety net.** Button and form answers are acknowledged at once and sent right after, like slash command replies, so if Discord refuses the newer layout the answer is sent the old way instead (or, for a message already in the newer layout, without its buttons). Queue alerts fall back the same way.
- **Older messages.** A message sent before this update keeps its old look when its buttons are pressed, because Discord cannot switch a message between layouts. Running the command again gives the new look. The activity feed starts a new message after a restart for the same reason.
- **Switching it off.** `DISCORD_COMPONENTS_V2=false` sends new messages as embeds again (the guide panels as their coloured text). Messages already in the newer layout keep it.

`app/layout_v2.py` rebuilds each message where it leaves for Discord; screens name the items that get a button beside them (`ui.with_items`). `tests/test_layout_v2.py` checks every slash command's reply, every menu area and every choice list against Discord's limits (40 components, 4,000 characters, unique button IDs), plus the buttons beside items, the fallbacks and the switch.

## Guide panels for brand-new players

Four new panels come first in the guide channel, for someone who has never played SEED or New Eridian:
- **New here? Read this first.** What kind of game this is, that the Seedling keeps living while you are away, what SEED is (and that you do not need to know it), and Twitch (lite) versus Discord (full game).
- **Words you will see.** Avesta, New Eridian, Seedling, Avesta day, needs, skills, job, SC, Seed Industries, Workbench, queue and Contribution.
- **Your first 10 minutes.** A numbered walkthrough that completes every First Step: /start, /job, gather Lumber, craft a Campfire from the welcome kit, eat Berries, Queue 5, meet your Seedling. Twitch players get the same start in chat.
- **Questions new players ask.** Playing every day, mistakes, cost, watching the stream, friends, and where to get help.

The old first panel, "Start here!", is now **Jump in**, so there is only one place to start. `/mod` → Post guide panels here posts all 16. `docs/discord-guide-panels.md` and `.txt` are regenerated, and `tests/test_guide_panels.py` checks the new panels come first, fit one message each, and match the welcome kit.

## One world for Twitch and Discord: the world merge

When `DISCORD_WORLD_ID` is not the Twitch channel's ID, Twitch and Discord run as two separate worlds: no shared characters, and `!link` codes made on Twitch can never be claimed on Discord. `/health` now points to a one-time merge instead of telling you to change the setting (changing it alone hides every Discord character).

**How to merge.**
1. Open `/api/v1/admin/world-merge?source=<old DISCORD_WORLD_ID>&target=<Twitch channel ID>&key=<ADMIN_KEY>`. It shows a preview and changes nothing: how many citizens each world has, who has a character in both, and what moves.
2. Add `&confirm=1` to run it. Do it while not streaming: commands wait while it runs.
3. Set `DISCORD_WORLD_ID` to the Twitch channel ID on Railway. The game already uses it from step 2 on, and keeps doing so after restarts even if you forget; `/health` reminds you until the setting matches.

**What it does.**
- Every Discord citizen moves into the Twitch world. A person with a character in both worlds is merged into one with the `/link` code: SC, XP, items, skills, home, business, queues and Seedling life combined.
- The old Discord world keeps its clock, current event, project, story, votes, seasons and stream challenge. Society stats and settlement stockpiles of both worlds are added together, as the overlay already showed them. Unpaid help on the Twitch world's own project counts toward the main project.
- Logs, highlights, journals and event history from both worlds are kept.
- Today's market demand, weather and directive are re-rolled once, because they are picked from the world's name.
- After the merge, `!link` works.

**Safety.** The preview runs the whole merge and rolls it back. Everything happens in one transaction under the game lock, so a failure changes nothing. A second merge of the same world is refused, and so is a target that already has its own seasons or stream challenges. The game lock's key no longer depends on the world name, so switching worlds while commands wait is safe. The admin duplicate and merge tools read the main world at call time.

**Tests.** `tests/test_world_merge.py` covers the preview, the merge, the restart behaviour, refusals and a failed merge. The same scenario runs on PostgreSQL in `tests/test_postgres.py`. A stress run on PostgreSQL (a few hundred mixed Discord and Twitch commands, then the merge) kept every citizen, and left total SC, items and XP unchanged.

## Hardening: keys, the market, locking, overlays, Seedlings and database growth

**Do this after deploying.**
1. On Railway, set new values for `TWITCH_API_KEY` and `ADMIN_KEY`, and add `MOD_KEY`. The old setup typed both keys into public Twitch chat, so treat the old ones as known.
2. Re-enter the StreamElements commands from `integrations/twitch/ALL_COMMANDS.txt` **in the StreamElements dashboard** (Chatbot → Chat commands → Custom commands), never with `!command add` in chat. Player commands take `TWITCH_API_KEY`; the moderator commands at the end take `MOD_KEY`. `ADMIN_KEY` stays on Railway.
3. Check `/health?key=<MOD_KEY>` for setup warnings (missing Twitch key, SQLite on Railway, the public database proxy, or a Twitch channel that is not `DISCORD_WORLD_ID`).

**Keys.**
- `ALL_COMMANDS.txt` is now laid out for the dashboard (name, response, user level, cooldowns) and warns against chat. The six superseded paste-in-chat files are gone.
- `MOD_KEY` runs the moderator commands (events, next day, live, challenges, recap, modlog). `ADMIN_KEY` still works for them, and is the only key for the merge tools.
- Request logs show `k=***` and `key=***` instead of the keys.
- Startup logs and `/health` warn when `TWITCH_API_KEY` is not set.

**Market.** A demand-day sale price never reaches what Seed Industries charges for the item. Before, buying Hematite or Chalcopyrite at 6 SC and selling it back at 7 paid on every round trip (plus Commerce XP), and the rare ores paid up to 4 SC each.

**One game lock.** PostgreSQL now uses a single advisory lock for the whole game, the same boundary SQLite already had. Votes, seasons, challenges, the market day and the overlay write the main world whichever channel a request names; with a lock per channel, an overlay refresh and a command could, for example, end the same expired event twice.

**Worlds and the overlay.**
- Reads without a player (society, events, tick, settlement, recap) must name a world that exists, unless they carry the game key. Before, any made-up channel created a society, a world and settlement rows.
- The overlay shows the main world for an unknown channel, and its cache drops its oldest entry instead of emptying when full (cycling channel names forced a fresh computation on every poll).
- Channel names longer than 64 characters are refused instead of failing in PostgreSQL.
- `/obs/<panel>?channel=` no longer lets `</script>` in the channel name inject a script into the page.

**Seedlings.** The worker serves the longest-waiting Seedlings first. With more than 200 active players, the rest never got a turn (in a 400-player simulation, 192 never acted).

**Database growth.** An hourly cleanup deletes action-log rows older than 14 days (`ACTION_LOG_DAYS`), Discord receipts older than 2 days, link codes expired a day ago, and journal entries older than 90 days (`JOURNAL_DAYS`) beyond each citizen's newest 20. New indexes cover the overlay's 24-hour leaders, the journal and the cleanup.

**Speed.** The PostgreSQL pool is 20 + 30 overflow (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`) instead of 5 + 10. The overlay computation is shared for 5 seconds instead of 2. The item migration check no longer locks and reloads the citizen on every command when there is nothing to convert, and only citizens with old item rows are visited at startup. `!status` stops after the first few ready recipes. The Discord player menu and name lookups no longer load and compare every player on each keystroke.

**Setup checks.** A `!link` code from another world explains that `DISCORD_WORLD_ID` must equal the Twitch channel ID. `/health` also reports the Seedling worker.

**Business names** keep only letters, numbers, spaces and `' & . -` (no links, mentions, markdown or emoji). Optional `BLOCKED_WORDS` refuses names containing listed words, ignoring spacing tricks. Business level ups on the stream overlay no longer show the business name.

**Smaller changes.**
- A mentor must have a higher level than the learner in the skill being taught, so a fresh second account cannot give its main free XP daily.
- Selling, undoing and selling again no longer repeats the level-up announcement.
- `!again`, `!craftmax` and `!uses` run inside the game transaction like other commands.
- `docs/reference/deployment.mb` is now `deployment.md` (the README link works), with the keys and new settings documented.

**Tests.** `tests/test_hardening.py` covers every change above. `tests/test_postgres.py` runs the game against PostgreSQL when `TEST_POSTGRES_URL` names a throwaway database: concurrent commands, the single lock, the channel guard, indexes and the cleanup. `.github/workflows/tests.yml` runs the whole suite with a PostgreSQL service on every push.

## Fix: the "Cast your vote" button counts your pick

In `/menu` → Community, choosing an option from **Cast your vote** replied "Choice must be a whole number from 1 to 3" and no vote was counted. Dropdowns send their value as text, and the check only accepted numbers. Number options now accept digits sent as text, so the vote counts straight away. Any other dropdown with a number option is fixed too.

## Colony votes now have real outcomes

**When a project wins the vote,** it is built next, right after the current project finishes. Finishing it:
- turns it into a landmark on the map;
- pays everyone who helped: 5 SC plus 1 SC per point given (up to 30 SC), plus 10 season points plus 1 per point given;
- gives the society +10 Development and +5 Reputation;
- adds a **lasting perk**: +2% success for everyone on the skills the building covers. Building the same thing again adds another +2%, up to +6% in total.

Each build is recorded once, so nobody is paid twice.

**When a festival wins,** it runs the next Avesta day:
- work in its skills gets +5%;
- everyone's first action that day comes with a gift: SC, plus festival goods (Berries, Herbs, Clay or Stone).

If the building site is idle when a festival wins, construction restarts with the project that got the most votes on that ballot, so it never stalls.

**Seeing it.** `/vote` on Discord shows:
- the last vote's result;
- every building finished so far, with its perk;
- a one-line "How it works".

`!vote` on Twitch adds the last result when it fits in the chat line.

## A game key for Twitch commands, and one complete command list

- **Game key.** With `TWITCH_API_KEY` set on Railway, every request that acts as a player must carry it (`k=` in the StreamElements command). Without the key, nobody can:
  - act as another player by calling the game's web addresses directly;
  - use `provider=discord` to get around the Twitch-lite version;
  - claim someone's link code.

  Discord is unaffected (it plays through the bot). Reads without a player stay open: the overlays, the society and the recap. A command missing the key replies "⛔ This command is missing the game key…" so a moderator knows to update it. Nothing changes until the key is set.
- **`integrations/twitch/ALL_COMMANDS.txt`.** Every StreamElements command the game needs, in paste order:
  1. getting started;
  2. gathering, mining and work;
  3. needs and life;
  4. your Seedling;
  5. society, events and community;
  6. the optional "full game on Discord" pointers;
  7. the moderator commands, last.

  Every player command includes `k=YOUR_API_KEY`. `integrations/twitch/build_all_commands.py` regenerates it. The older command files also carry the key now, and say they are superseded.

## A livelier Discord channel, Twitch as the lite version, and Seedling looks

### 📣 A livelier channel
Why the channel felt empty: every button in `/menu` and on the pinned game panel answers privately ("Only you can see this"), and so do most slash commands and the popups. Discord only lets a bot show a button reply to the presser or to everyone, and private keeps each player's buttons their own. The result was that the channel showed only queue alerts and a few public commands.
- **Live activity feed.** The bot posts what everyone is doing in one compact message. The message includes:
  - who gathered, mined or crafted what, from Twitch and Discord;
  - level ups, trophies, new citizens and finished queues;
  - events, stream challenges, vote results, projects and seasons;
  - a line for Seedlings working on their own.
- **How often.** It updates about every minute (`FEED_SECONDS`). Big moments (a challenge starting, a vote result, a new tier) go out straight away.
- **No spam.** While nobody else talks, the bot keeps editing the same message, up to 15 lines within 30 minutes. Once someone posts, the next update starts a new message below.
- **Buttons on every feed message.** "My menu", "Status" and "Community" open the presser's own menu, so the feed is also a way in.
- **Where it posts.** `/mod` → **Activity feed: post here** picks the channel; the game channel (`DISCORD_GAME_CHANNEL_ID`) is the default, or set `DISCORD_FEED_CHANNEL_ID`. **Activity feed: off** stops it.
- **Privacy.** Players can keep themselves out of the feed with `/settings feed:off`, or `/menu` → Settings.
- **📣 Share button.** It appears on private cards: profile, Seedling, trophies, season, and your Seedling's look. It posts a public copy to the channel, marked "📣 Name shared their …".

### 🎮 Twitch is the lite version; Discord has the full game
- **On Twitch:** start, link, status and profile, gathering, mining (one at a time), jobs and work, eating and resting, your Seedling and diary, the society and events, votes, stream challenges, seasons and trophies.
- **Discord only:**
  - crafting and workshops, queues and routines;
  - trading (Seed Industries, selling, market prices), homes and businesses;
  - gear and item use, the full catalog and collections;
  - settings and Seedling schedules, titles, districts, shifts and specializations;
  - hats, badges and Seedling looks, duos, mentoring and the journal.
- **What Twitch players see.** A Discord-only command typed on Twitch does nothing and replies with where it is and the invite, e.g. "🔒 Crafting is part of the full game on Discord: join discord.gg/… and use /make. On Twitch: !gather !mine !work !eat !status !vote". Set `DISCORD_INVITE_URL` so the invite shows.
- **Updated for Twitch:**
  - First Steps point crafting and queues to Discord.
  - The Twitch handbook (`!seed`) and the stream overlays' "how to play" tips are updated.
  - The guide panels say Twitch is the lite version.
- **Switching it off.** `TWITCH_LITE=false` gives Twitch the full game again.

### 🎨 Seedling looks and personality
- **`/customize`** (or `/menu` → My Seedling → Looks & personality) lets players choose:
  - skin tone: 14, including four Avesta colours;
  - hair style (9, including bald) and hair colour (12);
  - outfit colour, or "follows its mood";
  - an accessory: glasses, sunglasses, scarf, bow tie, backpack, flower or headphones;
  - headwear: its job hat, or no hat so the hair shows;
  - an attitude: cheerful, grumpy, shy, bold, dreamy, sarcastic, curious, chill, dramatic or wise;
  - a catchphrase from a curated list, so nothing unkind reaches the stream.
- **On the stream map.** The Seedling is drawn with its look. The attitude flavours its speech bubbles ("Hmph. …", "Behold! …"), and it says its catchphrase now and then.
- **Resetting.** "Back to its original look" resets any choice.
- **Cosmetic only.** None of it changes how well it works.
- **Map fix.** With names shown, neighbouring name labels now alternate height so they never overlap.

### Setup
- **Discord.** There's a new `/customize` command, a `feed` option on `/settings`, and new `/mod` actions (Activity feed: post here / off). Commands re-register on deploy as usual.
- **Database.** New tables are created automatically: `activity_feed_v1`, `activity_feed_events_v1`, `activity_feed_privacy_v1` and `seedling_looks_v1`.
- **Environment.** Set `DISCORD_INVITE_URL` (used in the Twitch replies). Optional: `DISCORD_FEED_CHANNEL_ID`, `FEED_SECONDS`, `TWITCH_LITE`.

## Discord guide panels, refreshed

- **Twelve panels** now (up from eight), written for players: what to do and where to find it, without every number.
  - New: **Your Seedling**, **Society & world**, **Votes & stream challenges** and **Seasons & trophies**.
  - Rewritten: Start here (with the First Steps and welcome kit), Needs & recovery, Gathering & work, Crafting, Queues and Money & trade.
- **The command list** includes `/vote`, `/challenge`, `/season` and `/trophies`, and ends with a **COLOR MEANING** key: what the colour strip on every game reply means.
- **Holidays panel.** Its "Coming up" part is worked out when the panels are posted, so the festival and its date are always current.
- **Posting.** A moderator posts them with `/mod` → Post guide panels here. `docs/discord-guide-panels.txt` (coloured) and `docs/discord-guide-panels.md` (plain) have the same text for pasting by hand.

## Colony votes, stream challenges, seasons, trophies and a weekly recap

### 🗳️ Colony votes
- **A new ballot every Avesta day** with three choices: two society projects and one festival.
  - Vote from Twitch (`!vote 1`, `!vote 2`, `!vote 3`, or a name), Discord (`/vote`), or `/menu` → 🎪 Community → Cast your vote.
  - You can change your vote until the day ends. Your first vote on a ballot pays +3 SC and +5 season points.
- **When the day ends, the winner happens:**
  - **Projects.** A project winner becomes the next society project. It starts immediately if the current project is finished; otherwise it starts the moment the current one completes. Before this, a finished project never changed.
  - **Landmarks.** A finished project stays on the stream map as a landmark in its district (🏥 clinic in the Homes, 🌿 greenhouse in the Farms, 🎳 hall in the Commons, and so on). The project being built shows as scaffolding with a crane and a % sign.
  - **Festivals.** A festival winner (Harvest Fair, Starlight Night, Market Fair, Maker Expo, Festival of Rocks, Wellness Day) runs the whole next day. It gives +5% success on its aptitudes, a party and bunting in the Commons, and a badge in the map header.
  - **Ties and empty ballots.** A tie goes to the choice that reached the top count first. With no votes, the colony picks at random.
- **Credit for builders.** Everyone who helped build a project is credited, and it counts toward the Builder and Project Veteran trophies.

### ⚡ Stream challenges (only while live)
- **12 short challenges.** Each lasts 5–10 minutes and has one shared goal, sized to how many people are chatting:
  - 🌪️ Dust Storm, 🌾 Harvest Rush, ⛏️ Ore Seam, 🪵 Lumber Drive, ☣️ Siro Surge, 🚚 Supply Convoy
  - 🍲 Feast Prep, 🦆 Lost Duck, 🪙 Market Rush, ⚡ Power Surge, 🏥 Clinic Rush, ☄️ Meteor Shower
- **What counts.** Every command that does the right kind of work adds to the goal, e.g. repairs for the Dust Storm or gathered crops for the Harvest Rush. Seedlings acting on their own do not count.
- **Chat replies.** Your contribution is shown in chat, e.g. "🪵 7/12 (+1)".
- **Work bonus.** While a work challenge runs, its aptitudes get +5% success.
- **Rewards on a win.** Everyone who helped gets:
  - +10 SC, plus 2 SC per point they added (up to +20);
  - +2 Contribution;
  - the challenge's materials;
  - season points.

  The top helper gets +15 SC as MVP, and the society gets a stat boost.
- **Rewards on a loss.** Helpers still get a small thank-you (+4 SC).
- **When the stream counts as live:**
  - a moderator switched it on (`!live on`, or `/mod` → Stream is live);
  - or the Twitch API says so (optional: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_CHANNEL_LOGIN`);
  - or two or more people used Twitch commands in the last 15 minutes.

  `!live off` stops challenges. While live, a challenge starts about every 25 minutes (`LIVE_EVENT_GAP_MINUTES`). Moderators can also start or stop one with `!chstart [name]`, `!chstop`, or the `/mod` actions.
- **On stream:**
  - a Hub slide that takes every other turn while a challenge runs (the map stays uncluttered);
  - a ticker item and alerts;
  - a new **Stream challenge bar** Browser Source (`/obs/challenge`, 900×110) that slides in, counts down and celebrates.

### 🏁 Seasons
- **Five-week seasons** (`SEASON_DAYS`, default 35), each with a theme and a story told one chapter a week:
  - 🌅 First Light
  - ⚙️ Iron and Dust
  - 🔮 Siro Mysteries
  - 🚀 Starport
  - ❄️ Deep Frost
  - 🎉 Founders' Jubilee
- **Season points** come from everything players already do:
  - 3 per Contribution;
  - 1 per aptitude XP (up to 30 per command);
  - stream challenges, votes and trophies.

  A Seedling working on its own earns its player half.
- **Rewards unlock as soon as they are earned:**
  - 🥉 Bronze (150): the season title, e.g. "Dawnbringer".
  - 🥈 Silver (500): the season hat for your Seedling on the stream map (flower crown, horned dust helm, wizard hat, astronaut helmet, frost beanie, party hat).
  - 🥇 Gold (1,200): a golden title, +50 SC and a trophy.
- **Community milestones** (2,500 / 7,500 / 15,000 points together):
  - season bunting over the town, then lanterns on every street, then a monument in the Commons;
  - each pays +10 SC to everyone who scored.
- **End of season:**
  - 🥇 gets "Season N Champion", a 👑 crown and 150 SC;
  - 🥈 and 🥉 get "Season N Finalist", a 🌿 laurel and 100 or 75 SC;
  - results are archived (shown on the profile as "Past seasons");
  - **only season points reset**. Stats, items, titles and hats all stay.
- **Commands:** `!season` (plus `top`, `rewards`, `story`), `!hat <name>` or `!hat job`; `/season`; `/menu` → Community.
- **On stream:** a Season slide on the Hub and a ticker line.

### 🏅 Collections and trophies
- **48 trophies in six groups:**
  - **Collections:** every ore, every natural material, 10 or 50 different items, 10 or 25 different foods eaten, each curio set, all ten curios.
  - **Crafting:** master each of the 15 craft categories (12 different recipes), and five of them for Grand Artisan.
  - **Festivals:** craft every festival food of a holiday (9 holidays).
  - **Colony:** vote once or 15 times, help finish 1 or 3 projects, finish First Steps, reach Lv 3 in every aptitude, a Seedling with 50 good days.
  - **Stream:** take part in 1, 10 or 25 stream challenges (the last gives a halo hat), win 5.
  - **Seasons:** reach Gold, finish in the top three.
- **Rewards.** Each trophy pays SC and +25 season points; the big ones also give a title (Ore Hunter, Wildlander, Gourmet, Curator, Grand Artisan, Town Councillor, Project Veteran, All-Rounder, Stream Legend).
- **Where they show:**
  - a trophy alert on stream with its badge;
  - the badges on the profile;
  - one pinned badge (`!badge <name>`, `/trophies badge:`) next to your name on the stream map and in the map caption.
- **Progress is counted from what you have and do.** The game now remembers every item a citizen has found and every food they have eaten.
- **Commands:** `!trophies`, `!badge`; `/trophies` (with a group to see it in full); `/menu` → Community. Trophies no longer appear in the old achievements list, which now points to `/trophies`.

### 📰 Weekly recap
- **Every Sunday from 18:00 UTC** (`RECAP_HOUR`), the bot posts one embed to `RECAP_CHANNEL_ID` (or `DISCORD_GAME_CHANNEL_ID`) covering:
  - top contributors (season points, Contribution and actions);
  - biggest hauls, and the single biggest Seedling haul;
  - the society tier with a progress bar and how every stat moved since last week;
  - vote winners and finished projects;
  - stream challenges won and the most helpful people;
  - trophies earned;
  - the season chapter and podium;
  - three funny Seedling moments from the diaries;
  - new citizens.
- **Once a week.** It posts once per week, and a restart never posts it twice.
- **Moderator controls:** preview it or post it now with `/mod` → Weekly recap. `GET /api/v1/recap` shows it as text; `!recap` shows this week's top three in chat.

### Setup
- **Discord.** There are four new slash commands (`/vote`, `/season`, `/challenge`, `/trophies`) and new `/mod` actions. Commands are re-registered by the container start command as usual.
- **Twitch.** The StreamElements lines are in `integrations/twitch/community_commands_ready.txt` (the moderator lines need your `ADMIN_KEY`).
- **Database.** The new tables are created automatically:
  - `colony_ballots_v1`, `colony_ballot_votes_v1`, `colony_plan_v1`, `colony_project_help_v1`;
  - `live_state_v1`, `live_challenges_v1`, `live_challenge_entries_v1`;
  - `seasons_v1`, `season_scores_v1`, `season_results_v1`, `week_scores_v1`, `wardrobe_v1`;
  - `trophy_found_v1`, `trophy_showcase_v1`, `weekly_recaps_v1`.
- **Optional environment variables:**
  - `RECAP_CHANNEL_ID`, `RECAP_HOUR`
  - `SEASON_DAYS`
  - `LIVE_EVENT_GAP_MINUTES`, `LIVE_EVENT_FIRST_MINUTES`, `LIVE_AUTO_CHATTERS`, `LIVE_EVENTS_AUTO`
  - `TWITCH_CLIENT_SECRET`, `TWITCH_CHANNEL_LOGIN`
- **Map fix.** A speech bubble near the edge of the map no longer spills out of the frame.

## First steps, a welcome kit, and new citizens greeted on stream

- **First steps (replaces "First Days").** Six small goals teach the game:
  1. 🧺 Gather something.
  2. 🔥 Craft something (a Campfire is easiest).
  3. 🍲 Eat.
  4. 💼 Choose a job.
  5. ⏱️ Start a queue.
  6. 🌱 Meet your Seedling.

  They count in **any order** and however the player does them: Twitch, Discord slash commands, buttons or a queue. The old First Days only counted steps in one fixed order and paid nothing until the end.

  Each step pays at once (+10–15 SC; crafting also gives 2 Lumber, eating 2 Berries), and the reply names the next step. On Twitch this is one short line, for example "🎓 3/6 +10 SC · next: !job". On Discord it gives the step name and the next command.

  Finishing all six gives +25 SC, +5 Contribution and the new **Settled In** title.

  Where it shows:
  - "What next?" (`/guide`) and the profile show the checklist.
  - The `/menu` home screen shows the next step.

  Players who already had 25 or more actions are marked finished and never see it.
- **Welcome kit.** `!start` / `/start` gives a new citizen, once:
  - 2 Lumber (enough for a first Campfire) and 4 Berries;
  - a Seedling that moves into the Residential Ring and writes its first diary entry ("Nova arrives in New Eridian");
  - a welcome message saying they are now on the stream map, with the checklist.
- **Greeted on stream.** When someone joins while the map is open:
  - a "🌱 Welcome to New Eridian, NAME!" banner shows (without [tags]);
  - the camera finds their Seedling, which says "Hi everyone! I just moved in. 👋";
  - for five minutes they stand first in their district, so they are never folded into "+N".
- **Startup safety.** After all modules load, any missing table is created, so a new table can never be missing in production.

## Welcome back: exact totals of what your Seedling collected

The "While you were away" message now adds up everything your Seedling did on its own since you were last active:
- **Collected N items on M trips**, with every item and its exact count (for example "• 6 × Stone · • 4 × Murky Water (1000ml)").
- **Earned N SC**.
- **Used**: what it ate or spent, with counts.

Below that come the three latest reports, and "…and N more in your diary".

Each autonomous step's exact gains, use and SC are now stored in a new table, `seedling_haul_v1`, which keeps each Seedling's last 400 steps. That keeps the totals exact even though a report headline names at most three items. Accounts merged by `/link` or the admin merge carry these records across. Steps from before this update were not recorded, so the first summary after the update only counts steps from then on.

## Simpler menus: only the buttons you can use, each in one place

`/menu` is reorganised so every screen is short and every button works. Nothing was removed; every action is still one or two taps away.

- **Only what you can do right now.** A button appears only when you can use it, and it appears as soon as that changes. Each screen lists the hidden ones with the reason, for example "🔒 Not available right now: Eat (you have no food) · Delivery (needs Cargo: Prepare cargo first)". The rules are the same checks the commands make:
  - food to eat, and a Pumpkin to share a meal;
  - the equipment for Hydroponics, Field Analysis, Survey and Market analysis;
  - Cargo for Delivery, and a Power Cell for Expedite;
  - Harvesting Lv 3 to prospect;
  - quality gear to repair;
  - something usable, sellable or ownable;
  - today's production orders;
  - a title to equip;
  - a business, for its actions;
  - a running queue to cancel, and a finished one to repeat;
  - a sale in the last 60 seconds to undo;
  - an active event to stop.
- **Switches instead of pairs.** Autonomy, auto-recover and compact/detailed results show one button, the one that changes the current setting. Start business disappears once you own one, and Account (Link Twitch) disappears once linked.
- **Dropdowns instead of button walls.**
  - Queue alerts (5 modes) and Notifications (3 modes) are one dropdown each, with the current setting marked.
  - Bag's six sort and filter views plus Quality gear are under **Sort & filter…**.
  - World and Me keep their main views as buttons, with the rest under **More…**.
  - Help's topics are under **Handbook**.
- **Shorter areas.**
  - Work groups its trade tasks into Farming, Research, Logistics and Frontier.
  - Trade moves Habitat and business into **Home & Business**.
  - Social sits inside Life.
  - Craft keeps Workbench, Ready now, Favourites, Goal and Workshops; every category is in the Workbench's category dropdown.
- **One home per button.** Buttons no longer repeat across areas: selling is only in Trade, eating only in Life, and Status and Notifications only on Home. No area has more than 15 buttons, down from 20, so the result screen after an action shows all of its area's buttons. Previously the last few (such as Repair, Training and Train a skill after a Work action) were cut off.

## Admin tools to find and merge duplicate characters

When someone plays on both Twitch and Discord without linking the accounts, they end up as two characters with the same name. Two admin endpoints fix this without losing anything. Both need the game's `ADMIN_KEY`.

- **Find duplicates:** `/api/v1/admin/duplicates?channel=new-eridian&key=ADMIN_KEY` lists every name held by more than one character (ignoring capitals and [tags]). For each copy it shows the ID (`uid`), whether it is a Twitch or Discord character, SC, contribution, actions, XP, and when it was created and last seen.
- **Merge:** `/api/v1/admin/merge?channel=new-eridian&keep=UID&merge=UID&key=ADMIN_KEY`
  - On its own, it only shows a preview of the combined character.
  - Adding `&confirm=1` applies the merge. It uses the same code as `/link`:
    - SC, contribution, actions, XP and skills are added together.
    - Items and quality gear stack.
    - The best home and business level are kept, and achievements, dailies, cooldowns, event contributions, crafting history, queues, Seedling life and relationships are combined.
    - Both the Twitch and Discord IDs then point at the kept character, and a Twitch + Discord pair becomes a permanent link.
  - Society stats are not touched. Population drops by one, because the duplicate was being counted as an extra citizen.
  - The merge is recorded in the moderator log.

Players can still do this themselves: `!link` on Twitch gives a code, and `/link CODE` on Discord merges the two characters in the same way.

## Weather changes through the day; every overlay option on the setup page

- **Weather changes every phase.** Avesta's weather used to be picked once per Avesta day (every 6 real hours) and often repeated on the next day, so it barely changed during a stream. It now changes with every phase (Morning, Day, Evening, Night), which is about every 90 minutes of real time with the default day length, and it never repeats back to back. Every weather type comes up about equally often. The weather's game effects (bonuses and harder work) follow the current weather as before. The map announces each change with a banner, for example "🌧️ Good Growing Weather rolling in", and switches its rain, dust, spores, fireflies or glitches.
- **Options as controls on `/obs`.** Every overlay's options are now drop-downs, number boxes and checkboxes on the setup page. Only options that differ from the default go into the URL. The preview updates live, and the choices are saved with your width and height. **Reset all** restores the defaults.
  - Hub: layout, seconds per slide, and which slides to show.
  - Map: layout, quality, camera close-ups, names, stats panel, Seedlings per district, and seconds per caption. It also has preview-only settings for time of day, weather and holiday; a warning appears while one is set, so you remember to clear it before going live.
  - Ticker: scroll speed.
  - Alerts: seconds on screen, chime sound, which alert types to hide, and demo alerts.
  - News: number of older headlines and seconds per story.
  - How to play: seconds per tip.
- **Checked end to end.** Every option was tested in a browser against its overlay, along with a weather and phase change arriving mid-stream, and every overlay page loads without script errors.

## Map: full-width caption when the Wide layout is used in a smaller source

With `&layout=wide` (or "Wide (full map)" on the setup page) in a source narrower than 800 px or less wide than 3:2, for example 400×400:
- The caption spans the whole width of the map, with larger text.
- The header wraps onto two lines instead of cutting off.
- The town is fitted above the caption, so no buildings sit behind it.

The map switches between these layouts if OBS resizes the source.

## A bigger town in square sources; stats move to the Hub

- **The map switches layout when OBS resizes it.** OBS often opens a Browser Source at its default size and resizes it a moment later. The map used to keep the layout it chose first, so a 400×400 source showed the full-screen layout with a tiny town. It now switches layout after a resize.
- **Closer camera in the card layout.** In square and side-column sources, the camera stays close on whoever is speaking for three turns out of four (2.4× zoom), and shows the whole town on the fourth. Buildings, Seedlings and district badges now read at 400×400.
- **The society stat panel is off the map.** The Hub shows the society stats. Add `&stats=1` to the map URL to bring the panel back.

## Choose your own panel sizes; the map background fills any shape

- **Your own sizes on `/obs`.** Every panel on the setup page now has its own **Width** and **Height** boxes, and the map and Hub also have a **Layout** menu:
  - Map: Automatic, Card or Wide.
  - Hub: Automatic, Compact, Tall, Wide or Strip.

  The live preview redraws at exactly that size, the URL gains `&layout=` when you pick one, and **Reset** returns to the recommended size. Your choices are remembered in that browser. Type the same numbers into the Browser Source's Width and Height in OBS (Properties), rather than dragging its corners.
- **The map background fills the whole source.** Square, tall and very wide sources used to show flat bands above and below the 16:9 scene, with a hard-edged vignette. The sky, stars, hills and vignette now reach every edge, whatever the shape.

## The Hub shows every word

Hub slides no longer cut text off with "…". Long lines wrap onto the next line, and each slide shrinks its text until everything fits the source. If a slide still would not fit (for example three long news stories in a small box), it drops whole list entries from the end rather than cutting words. Every slide was checked at 340×176, 520×260, 640×360, 340×440 and 1440×120, with no text cut off or hidden and none smaller than 11 px.

## Polish pass across every overlay

Every overlay page was checked in a browser: every Hub slide in all four layouts (640×360, 340×176, 340×440, 1440×120), every panel at its recommended size, and the map at 340×250 up to 1920×1080. The checks looked for text leaving its box, overlaps and script errors, and everything found was fixed:

- **Hub.**
  - A slide with nothing to show (for example `&slides=event` with no live event) now shows an "All quiet on Avesta" card, instead of staying on "Connecting to Avesta…" or showing an empty panel.
  - In a roomy source such as a tall side column, slides now grow to fill the space. In a tight one, they shrink until they fit.
  - Stat labels no longer wrap.
  - Join commands in the strip layout are proper command chips.
- **Older panels** (Society, Today, Event, Ops, Activity, Telemetry) shrink to fit their Browser Source. Today's aftermath line was being cut off at 420×280.
- **Map.**
  - Speech bubbles keep off other Seedlings as well as names and panels, and prefer short tails that never cross a name.
  - A group of Seedlings that would stand on a neighbouring district's name nudges sideways or steps down, but stays inside its own district.
  - The small column card shows three Seedlings per district plus "+N", and its badges are a touch smaller, so everything has room.

## Fix: the map stuck on "Connecting to Avesta…"

The previous update broke `/obs/map` for every source wider than 560 px. A code comment had been placed in the middle of a line and silently disabled the rest of it. The town drew, but the header, Seedlings and captions never loaded. It is fixed. A new test fails if code ever ends up behind a comment again, and every overlay page was loaded in a browser at several sizes with no script errors.

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
