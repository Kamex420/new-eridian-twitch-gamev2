# Gameplay reference

## Mining and gathering

`/mine` exposes ore selection, a requirements preview, and a count from 1 to 10. Common ore attempts cost 2 Energy, 1 Nutrition and 1 Comfort, with the existing 5-second shared gathering cooldown. They require no tools or skill unlock.

Argentite, Bauxite, Rutile and Aurite require Harvesting level 3. One prospecting attempt costs 3 Energy, 1 Nutrition and 1 Comfort; all rare ores share a 20-second cooldown. Three saved prospecting steps produce one ore. A ten-attempt queue beginning with no saved progress produces three ores and one remaining prospecting step.[^1]

`/gather` browses non-ore resources. Older ore-gathering routes remain compatible with the same requirements. No alternate route skips rare-ore gates.

## Crafting and progression

Recipes require their corresponding bench or machine access, personal tier and listed skill. Personal tiers unlock at 0, 25, 100 and 250 completed manufacturing batches. Matching station ownership can replace a permanent access fee; it cannot bypass tier or skill requirements.

Ingredient-consuming manufacturing training uses the matching catalog recipe's inputs, output batch and access gates. Gathering, purchases and non-manufacturing training do not increase the manufacturing count. Recipe previews expose ingredient quantities, station, tier and skill requirements.[^2]

## Needs and queues

Energy, Nutrition and Social must each be at least 20 before an attempt. Comfort affects performance but does not block work. A task may finish below 20; its next attempt then pauses. Passive recovery adds one point to each need every 15 minutes, up to 60, including elapsed time away. Recovery never lowers a value already above that cap.

A queue contains one exact task/resource/recipe and at most ten attempts. Starting a second active queue is rejected even when its task matches. Failed attempts count; attempts blocked by needs, materials, ownership, skill, tier, workstation access or cooldown do not. Paused queues resume automatically after their requirements are met.

| Ten attempts | Base needs spent | Starting needs sufficient without recovery |
| --- | --- | --- |
| Common ore or ordinary crafting | 20 Energy, 10 Nutrition, 10 Comfort | 38 Energy, 29 Nutrition, 20 Social |
| Rare prospecting or heavy work | 30 Energy, 10 Nutrition, 10 Comfort | 47 Energy, 29 Nutrition, 20 Social |

Forecasts exclude other activities, passive recovery and incident effects. Morale can also fall when Comfort is below 20. Material budgets are upper bounds because unsuccessful work generally retains its ingredients. Requirement messages distinguish amounts needed, owned and missing, and include acquisition routes.

Queue status is private in Discord. Progress persists through restarts. The worker runs while the app is online, without posting unsolicited chat messages. Cancellation preserves completed work and stops remaining attempts.

[^1]: Rare prospecting: [`app/crafting_progression.py`](../app/crafting_progression.py).
[^2]: Acquisition graph and execution: [`app/seed_content.py`](../app/seed_content.py). Queue rules: [`app/task_queue.py`](../app/task_queue.py).
