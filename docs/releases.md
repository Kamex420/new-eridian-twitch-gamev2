# Release notes

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
