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
