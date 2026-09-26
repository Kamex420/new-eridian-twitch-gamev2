# Gameplay reference

## Mining and gathering

`/mine` exposes ore selection, a requirements preview, and a count from 1 to 10. Common ore attempts cost 2 Energy, 1 Nutrition and 1 Comfort, with the existing 5-second shared gathering cooldown. They require no tools or skill unlock.

Argentite, Bauxite, Rutile and Aurite require Harvesting level 3. One prospecting attempt costs 3 Energy, 1 Nutrition and 1 Comfort; all rare ores share a 20-second cooldown. Three successful prospecting steps produce one ore. With no failures, a ten-attempt queue beginning with no saved progress produces three ores and one remaining step. Failures produce Stone Dust instead, so ten attempts no longer guarantee three ores.[^1]

`/gather` browses non-ore resources. Older ore-gathering routes remain compatible with the same requirements. No alternate route skips rare-ore gates.

## Crafting and progression

Recipes require their corresponding bench or machine access, personal tier and listed skill. Personal tiers unlock at 0, 25, 100 and 250 completed manufacturing batches. Matching station ownership can replace a permanent access fee; it cannot bypass tier or skill requirements.

Ingredient-consuming manufacturing training uses the matching catalog recipe's inputs, output batch and access gates. Gathering, purchases and non-manufacturing training do not increase the manufacturing count. Recipe previews expose ingredient quantities, station, tier and skill requirements.[^2]

## Needs and queues

Energy, Nutrition and Social must each be at least 20 before an attempt. Comfort affects performance but does not block work. A task may finish below 20; its next attempt then pauses. Passive recovery adds one point to each need every 15 minutes, up to 60, including elapsed time away. Recovery never lowers a value already above that cap.

A queue contains one exact task/resource/recipe and at most ten attempts. Starting a second active queue is rejected even when its task matches. Failed attempts count; attempts blocked by needs, materials, ownership, skill, tier, workstation access or cooldown do not. Paused queues resume automatically after their requirements are met.

Queue results show successes, failures, total items gained and total items used. A success uses the actual recipe or gathering yield; bonus items are included. Rare prospecting steps without ore are progress, not failures. The totals describe inventory changes already applied during each attempt, so viewing the queue never awards items twice. For queues begun before outcome tracking was installed, earlier attempts are marked as unrecorded.

| Ten attempts | Base needs spent | Starting needs sufficient without recovery |
| --- | --- | --- |
| Common ore or ordinary crafting | 20 Energy, 10 Nutrition, 10 Comfort | 38 Energy, 29 Nutrition, 20 Social |
| Rare prospecting or heavy work | 30 Energy, 10 Nutrition, 10 Comfort | 47 Energy, 29 Nutrition, 20 Social |

Forecasts exclude other activities, passive recovery and incident effects. Morale can also fall when Comfort is below 20. Material budgets are upper bounds because unsuccessful work generally retains its ingredients. Requirement messages distinguish amounts needed, owned and missing, and include acquisition routes.

Queue status is private in Discord. Progress persists through restarts. The worker runs while the app is online, without posting unsolicited chat messages. Cancellation preserves completed work and stops remaining attempts.

[^1]: Rare prospecting: [`app/crafting_progression.py`](../app/crafting_progression.py).
[^2]: Acquisition graph and execution: [`app/seed_content.py`](../app/seed_content.py). Queue rules: [`app/task_queue.py`](../app/task_queue.py).

## Automatic work and useful task options

An active queue checks its next action every ten seconds while the service is running, independently of player messages. The first attempt is due ten seconds after starting. Needs and missing requirements pause the queue without consuming attempts. Rare-ore cooldowns still require twenty seconds between prospecting steps. Coal appears in `/mine`, awards one unit per successful attempt, and trains Ore Mining; its existing purchase price remains 4 SC.

On completion, cancellation, unmet requirements or a terminal error, the bot posts a result message in the originating Discord channel and mentions only the player who started the queue. The message includes success/failure counts and item totals. Twitch completion messages mention the player in the configured stream chat. Delivery failures never undo or repeat gameplay rewards; the journal and queue retain the result.

### Personal output per successful attempt

| Task | Output | Energy per attempt | Additional requirement |
| --- | --- | --- | --- |
| Tend Fields | 1 Crop + 1 Pumpkin Seed | 2 | None |
| Harvest Crops | 2 Crops + 1 Pumpkin + 1 Pumpkin Seed | 3 | None |
| Irrigate | 3 Crops + 1 reclaimed Murky Water | 4 | None |
| Hydroponics | 4 Crops + 1 Raw Algae | 5 | Water Filter, kept |
| Standard Research | 1 Stone sample | 2 | None |
| Field Analysis | 2 Stone + 1 Herbs | 4 | Siro Sampler, kept |
| Standard Spaceport Operations | 1 Cargo + 1 Lumber from packaging | 2 | None |
| Expedited Spaceport Operations | 2 Cargo + 2 Lumber | 4 | 1 Power Cell consumed on success |
| Scout | 1 Stone + 1 Berries | 3 | None |
| Advanced Survey | 2 Stone + 1 Clay + 1 Coal | 5 | Sensor, kept |
| Commerce Work / Business Work | 1 Cargo | 2 | Registered business for Business Work |
| Market Analysis / Business Contract | 2 Cargo + 1 Lumber | 4 | Market Analyzer / registered business |
| Forage | 2 Berries + 1 Herbs | 3 | None |

Higher-output methods trade more Energy for better yields. Failure still spends needs but grants none of these outputs. Existing random bonus yields are additional and included in queue totals. XP, society rewards and SC pay remain in place. Pumpkin Seeds have an existing planting use: one seed plus Clean Water yields three Pumpkins. Stone samples use the same Stone inventory as crafting; no duplicate item identities were introduced.

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

Low Energy, Nutrition or Social pauses a queue and sends a channel @mention
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

### Channel pings

When your queue completes or pauses, a separate message @mentions you in the
same game channel. A pause message states the reason and recovery action.
The queue timer continues without new chat messages. `/queue` shows delivery
errors when the bot cannot send the alert; the original private command response
is not the completion notification. Discord notification settings can affect
push notifications even when the channel mention is delivered.


## Production batch and resale update

Catalog materials now produce demand-based batches of 5–20, including station efficiency; finished products produce one. /make recipe previews show the current output and NPC sale value. Seed Industries buys all obtainable catalog items. Newly listed finished goods are sell-only. See [Production economy](production-economy.md) for examples and price rules.
