# Release notes

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
