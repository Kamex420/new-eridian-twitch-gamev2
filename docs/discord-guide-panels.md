# Discord how-to-play panels

Eight messages for the game's guide channel. Paste each block (between the `---` lines) as its own message, in order. Each one is under Discord's 2,000-character message limit.

**Coloured version:** the same panels as Discord ANSI blocks (green title box, cyan headings, orange commands) are in [discord-guide-panels.txt](discord-guide-panels.txt). A moderator can post all eight with colours intact using `/mod action:Post guide panels here`; the source is `app/guide_panels.py`.

---

## 🌱 1 · Welcome to New Eridian

New Eridian is a settlement on Avesta that everyone here builds together. You gather and mine, craft at workstations, keep your citizen healthy, and help the whole society grow.

**Get started**
1. `/menu` opens everything as buttons: pick an area, then what to do. After each action the next buttons are right there.
2. `/start` creates your citizen, or loads your linked character.
3. `/job` picks a profession bonus. You can change it later.
4. `/status` shows your needs, queue, cooldowns, what you can craft now, and your next step.
5. `/guide` suggests the best thing to do next, and why.

**Playing on Twitch too?** Type `!link` in Twitch chat, then enter the code with `/link` here. Both accounts share one inventory and one set of progress.

Most replies have buttons. Menus and page buttons never spend anything. Buttons that spend (Craft, Start, Buy, Sell) work once and only for the citizen who opened them.

---

## ❤️ 2 · Needs and recovery

Every task uses **Energy**, **Nutrition** and **Comfort**. A standard task costs 2 Energy, 1 Nutrition and 2 Comfort; heavy work costs 3 Energy and 3 Comfort. Work stops when Energy, Nutrition or Social drops below 20, or Comfort below 10. Below 20 Comfort, work is slower.

**`/life`** is how you recover:
• **Relax**: +25 Energy, +20 Comfort (every 30 seconds)
• **Sleep**: Energy and Comfort to 100 (every 30 minutes)
• **Eat**: pick a food; with no food and low Nutrition you get a free emergency meal
• **Games**: +25 Social · **Walk** and **Hobby**: Morale
• **Recover**: does every recovery that's ready, in one press

Needs also recover by themselves: +1 every 15 minutes, up to 60.

Beds, seats, baths and clothing restore Comfort through `/use` and are kept after use.

`/settings autorecover:On` lets paused queues relax, eat, play games or sleep on their own, then carry on.

---

## ⛏️ 3 · Gathering, mining and work

• `/gather`: collect natural materials like Lumber, Berries, Herbs and Stone.
• `/mine`: pick an ore or Coal, check its requirements, then mine or queue up to 10 attempts. Mining can fail; a failure gives Stone Dust. Rare ores need Harvesting level 3 and three successful prospecting steps per ore.
• `/work`: every job in one list, including farming, scanning, research, cargo and deliveries, spaceport runs and scouting. Each choice shows what one success gives and what it costs.
• `/training`: browse the skills and see which tasks train each one.

Every success gives practice in its skill. Higher skill levels unlock better recipes and higher success chances.

---

## 🛠️ 4 · Crafting with /make

`/make` opens the **Workbench**. Categories list recipes from easiest to hardest.
• ✅ ready · ❌ missing ingredients · 🔑 workstation to unlock · 🔒 tier or skill lock
• **Ready now**: everything you can craft this moment.
• **Favourites**: press ⭐ on any recipe to keep up to 10 at the top of your lists and `/status`.

Open a recipe to see what you have and what you need, where to get each ingredient, and its batch size and cost. From there: **Craft 1 batch**, **Queue 5 / 10**, or, on a ❌ recipe, **🧺 Fetch missing**. Fetch plans the gathering, starts it, and queues the craft right after. It can also buy what's missing.

**Tiers:** you unlock personal tiers at 25, 100 and 250 crafted batches. `/workshop` shows your stations. Unlock one for a one-time fee, or own the matching machine instead. The Survival Workbench is free.

---

## ⏱️ 5 · Queues and alerts

A queue repeats one task up to 10 times, one attempt every 10 seconds, even while you're away. `/queue` shows progress, what the queue has gained and used, and why it paused.

• **Queue next**: line up one more task that starts automatically when the current one finishes.
• **Repeat**: finished queues offer 🔁 Repeat on the alert and in `/queue`.
• **Pauses**: low needs or missing materials pause the queue, and it resumes by itself. The alert says how long passive recovery will take and has a **Recover now** button.
• **Cancel** keeps completed work and clears the next queue.

**Alerts:** `/settings alerts:` lets you choose a channel @mention (the default), a direct message, **Quiet** (only when a queue finishes or stops) or **Off**.

---

## 🪙 6 · Money, market and inventory

Seed Coin (SC) is your personal currency.
• `/seedindustries`: buy starter supplies and sell anything you've made. **Sell all of one item** sells a whole stack. **Clear out surplus materials** shows a preview first, keeps 20 of each material, and never sells anything your favourites or queues need.
• Production orders: `/seedindustries action:View Production Orders` lists three daily contracts that pay well for crafted goods.
• `/market`: day-by-day prices and commerce work.
• `/inventory`: search by name, sort by quantity, name, value or category, and filter to items used in recipes you can make now, items used by your favourites, or sellable items.
• `/home` upgrades your Habitat; `/business` runs your own company.

---

## 🎉 7 · Holidays and festival foods

Every holiday has a festival that opens 30 days before it and runs until 7 days after. `/world section:Holidays & Festival Foods` shows what's on now and what's next.

Each festival has three **festival foods**. They're real items:
• Crafted at the free Survival Workbench from gathered ingredients (Pumpkin, Berries, Corn, Herbs and more), only while their festival runs.
• Eating one gives Nutrition **plus** extra Comfort and Morale.
• They stack, sell and keep all year, so stock up before the festival ends.

**Coming up:** 🎃 Halloween opens October 1: Pumpkin Bites, Moon Tart and Candy Herb Mix.

---

## 📖 8 · Command reference

**Everything as buttons** · `/menu`
**You** · `/status` · `/me` (profile, needs, skills, daily contract, achievements, titles) · `/inventory` · `/settings`
**Recover** · `/life` · `/use`
**Work** · `/gather` · `/mine` · `/work` · `/training` · `/repair`
**Craft** · `/make` · `/workshop` · `/catalog`
**Queue** · `/queue`
**Trade** · `/seedindustries` · `/market` · `/home` · `/business`
**Community** · `/social` · `/world` (society, events, holidays, news) · `/district` · `/shift` · `/ducks`
**Help** · `/guide` · `/seed` (full handbook) · `/start` · `/link` · `/job` · `/specialize`
**Moderators** · `/mod` (start or stop events, moderator log, linked-account lookup)

Stuck? `/menu` has a button for everything, and `/status` always shows your next step. Every reply ends with 🔁 Again and 🏠 Menu buttons.

---
