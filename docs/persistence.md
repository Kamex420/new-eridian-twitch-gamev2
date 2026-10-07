# Persistence and compatibility

Existing table names, player identifiers, route signatures and catalog IDs remain compatibility contracts. Moving Python source files does not rename database tables or reset saves. The database engine still uses `DATABASE_URL` and existing migrations remain additive.[^1]

## Item identities

Every legacy item type maps to a canonical SEED catalog item (27 aliases, listed in `app/item_identity.py` and the [gameplay reference](gameplay.md#catalog-items-replace-legacy-items)). Conversion adds quantities one-for-one to existing destination stock, then zeros source quantities within the same transaction. Repeated conversion cannot award the same stock again. Hematite Ore, Argentite Ore, Pumpkin and Iron Nails are backed by the existing `ore`, `rare_ore`, `crops` and `components` player columns; any catalog stock of Pumpkin or Iron Nails is added to those columns once, so Crops/Pumpkin and Components/Iron Nails are a single balance. Owned legacy quality gear keeps its rows; only its crafting and repair ingredients changed to catalog items.[^2]

One-time Discord button tickets live in the additive `ui_tickets_v1` table (owner, action, used time, expiry). Claiming a ticket is a single conditional update, so a second press cannot spend twice. Expired rows are deleted when new tickets are issued.

The catalog JSON is unchanged by this cleanup. Historical `legacy_discord_options.json`, route fixtures and the old SQL schema are retained under `tests/fixtures/`; they are evidence for regression tests, not live command definitions.

## Queue transactions

One `task_queues_v1` row belongs to a player within a world. Active state stores the exact task, total attempts, remaining attempts, next eligible time and most recent result. A failed attempt counts; a blocked attempt does not.

The additive `task_queue_totals_v1` table stores successes, failures, prospecting-only steps, and JSON maps of item gains and spending. No existing queue columns are changed. Each attempt compares canonical material and quality-equipment inventory inside the same transaction; positive and negative per-attempt changes are accumulated separately. Internal prospecting counters are excluded. These are net inventory changes per attempt, including bonus yields, rather than numbers inferred from message text.

Starting a new queue resets its totals. Cancellation preserves completed totals. Account linking transfers or discards the summary with its corresponding queue. Legacy attempts are not backfilled from the last result, because that result cannot establish earlier outcomes.

The worker binds gameplay sessions to an outer transaction because existing handlers commit internally. Gameplay effects and the queue counter then commit together. PostgreSQL row locks serialize attempts for a player; SQLite uses `BEGIN IMMEDIATE`. A simulated failure after a handler's internal commit verifies that inventory, needs, cooldowns and queue progress roll back together.[^3]

The worker executes at most one eligible attempt per player per polling pass. Downtime therefore does not produce a burst of accumulated actions. Needs and requirements are checked again before each attempt; materials are not reserved at queue creation.

## Linked accounts

Inventory conversion occurs before account balances are combined. Account linking retains at most one active queue. An active target-account queue takes priority when both accounts have one; otherwise the source queue transfers. Completed work remains part of the merged balances, and queue status records cancellation of a conflicting queue.

Keep levels live in the additive `player_keep_levels_v1` table (world, citizen, canonical item key and amount; at most 25 per citizen), created at startup like the other additive tables. Item keys are stored canonically, so an old alias and its catalog item share one row. Linking keeps the target's levels; the source's levels for other items move across while the citizen stays within 25, and the rest are dropped.

Shopping lists live in the additive `player_shopping_list_v1` table (world, citizen, recipe ID, the amount of its output wanted and when it was added; at most 10 per citizen, in the order added), created at startup like the other additive tables. Progress is not stored: an entry is done when the citizen owns that many. Linking keeps the target's entries; the source's entries for other recipes move across after them while the list stays within 10, and the rest are dropped.

Questions `/find` could not answer live in the additive `find_unanswered_v1` table (world, the cleaned question, how many times it was asked, first and last time), created at startup. It holds no player or account ids. The newest 300 rows are kept; a world merge adds the counts of a question both worlds asked.

When each citizen last played themselves (not a Seedling or a queue acting for them) lives in the additive `real_activity_v1` table (world, citizen, last time), created at startup. Event goals, the Society Directive's goal and the automatic event meter count these citizens; the action log (`action_logs_v5`) still records every action, Seedlings' included, for the activity feed.

Contribution a Seedling kept each day lives in the additive `seedling_contribution_v1` table (world, citizen, UTC day, amount), created when Seedlings start. A Seedling keeps at most 25 a day; anything more is taken back after its step.

Rare ores no longer use prospecting progress: the old `prospect:<ore>` bag rows are cleared the next time that ore is mined.

Goal progress lives in the additive `player_goal_progress_v1` table (world, citizen, goal recipe ID, the walkthrough's step count when the goal was set, when it was set, and whether the one ready note went out); the goal itself stays in `player_extras_v1`. Setting a different goal replaces the row, clearing or completing the goal deletes it, and a goal set before the table existed gets its row the first time it is shown or checked (counting from then; a ready note the old reminder already sent is not repeated). A row for another recipe than the current goal is ignored. Linking keeps the target's row; the source's row moves when the target has none.

## Rollback semantics

The filesystem cleanup is independent of the database format. Earlier item conversion is not reversed by restoring older source files: a version that still expects separate legacy stock cannot safely interpret a converted save as though conversion never occurred. Queue records are additive, but an application without the worker will not process them. A data-aware rollback or a database snapshot is required when reversing persistent migrations, with the usual consequence that restoring a snapshot loses later changes.

[^1]: [`app/migrations.py`](../app/migrations.py) and [`app/models.py`](../app/models.py).
[^2]: Exact mappings and migration logic: [`app/item_identity.py`](../app/item_identity.py).
[^3]: Transaction tests: [`tests/test_task_queue.py`](../tests/test_task_queue.py). PostgreSQL execution has not been validated against a live deployment in this release.

## Completion delivery

`queue_destinations_v1` records a unique queue run ID, original player identity, platform and Discord channel. The channel comes from the verified Discord interaction and is scoped to that request. Linking accounts moves this destination with its active queue.

Completion inserts one immutable `queue_notifications_v1` outbox row in the same transaction as the final rewards and counters. A separate lifecycle worker sends notifications; network requests never hold up the work scheduler. A conditional update claims a two-minute delivery lease. Retry attempts are bounded at five, with backoff and rate-limit delays; invalid credentials or permissions become terminal failures. An expired lease can be reclaimed after a process restart.

Discord messages use an explicit user mention whitelist, disabling role and everyone mentions, with a stable nonce for retry deduplication. Remote send and database acknowledgement cannot be made atomic: a crash after acceptance may duplicate a notification outside Discord's deduplication window; it cannot duplicate game rewards. No interaction tokens are stored. Discord alerts go to the player's direct messages unless they chose channel mentions; when DMs are closed the alert waits in their Notifications instead of falling back to the channel, and quiet hours (below) can hold DM alerts.

### Message detail snapshots

`message_pages_v1` stores an opaque random ID, JSON display pages and a 24-hour
expiry. It is additive and created with the other SQLAlchemy tables. Snapshots
survive worker restarts and work across instances sharing the database. Expired
rows are removed when another long response is rendered. Navigation reads only
this table and never calls gameplay handlers. A stale button asks the player to
run the command again; pages are snapshots, not live queue status. Private
snapshot IDs are exposed only on the corresponding ephemeral response. Public
snapshots contain only the already-public command text.

## Reliability boundaries

The shared `app.db.SessionLocal` observes a transaction ContextVar. Nested
commits flush work into the outer transaction rather than independently saving
needs, rewards or bookkeeping. HTTP game endpoints and signed Discord commands
use the same boundary as queue attempts. A PostgreSQL advisory lock per world
orders these operations, including shared society updates and account merges;
SQLite uses its single-writer transaction. This favors consistency over parallel
writes inside one world. Pure HTML responses and health checks do not take the
world lock.

`queue_health_v1` tracks consecutive rolled-back attempts. Two retry delays
precede a terminal `error` state on the third failure. Successful processing
clears the streak. No failed transaction decrements attempts or retains rewards.
Health state follows the retained queue when accounts merge.

`queue_notice_events_v1` adds run ID, event kind and creation time to outbox
notices without altering existing columns. Pauses, cancellation, completion and
terminal errors commit with their immutable snapshots. The completion notice
retains the historical run-ID key. Other transitions use distinct notice IDs.
Pending obsolete pause notices become `superseded`; already-sent alerts remain
history. An alert already in flight can still arrive after recovery. At-least-once
remote delivery cannot guarantee exactly one visible message after a crash.

`discord_command_receipts_v1` stores interaction ID, a fingerprint of the actor,
command and options, saved result text and creation time. The receipt and command
commit together. Retransmission returns the saved response and never replays
its rewards. Receipt rows are retained; no interaction tokens are stored. A new
interaction ID represents a new command. Termination before a deferred background
command begins still requires a new user request; this is not a durable incoming
Discord job broker.

## Asynchronous channel delivery

The Discord.py worker claims only Discord notices with the existing conditional
SQL lease. Detached snapshots cross the thread/async boundary; a SQLAlchemy
session never remains open during a network send. The send has a 45-second bound
inside its 120-second lease. The library sends a stable nonce and enforces nonce
deduplication. A crash outside Discord's deduplication window still permits a
repeated alert; rewards are not replayed. Shutdown finishes the current delivery
before closing the client. Twitch claims only Twitch notices in production.

Successful authentication triggers one repair scan for current stopped queues
whose saved deadline is within the last 24 hours. Failed notices are requeued;
missing notices are reconstructed from saved totals. Already-sent notices are
left alone. This repair does not modify inventory, needs or queue counters.

### Quiet hours

`player_quiet_hours_v1` stores one row per citizen with quiet hours (world,
citizen, time zone, start and end as minutes after local midnight); no row means
they are off. Account linking keeps the target's row, otherwise the source's row
moves. `quiet_held_alerts_v1` records each held outbox notice (notice ID, world,
Discord recipient, when it was first held). Both tables are additive; no column of
`queue_notifications_v1` or any other table changes, and every time stays in UTC.

Holding happens in the Discord worker after a due notice is selected and before it
is claimed. A due DM notice whose recipient is inside their window is moved with a
conditional update (still pending or sending, still due) to `next_at` = the
window's end, so holding spends no attempt and takes no lease, and only one worker
can hold it. When a held notice is due again and its recipient is outside the
window, the worker claims every due DM notice of that recipient together: one
conditional update per row in ID order, the same conditions and two-minute lease
as the ordinary claim, and one commit. A row is claimed by exactly one worker, so
two passes or instances cannot both send it. The claimed notices go out as one
summary DM with its own stable nonce (derived from the first notice ID), or as the
ordinary alert when there is one. Success marks each sent and deletes its held
row; a failure applies the ordinary backoff and five-attempt limit to each and
keeps the held rows, so the retry is again one message; closed DMs mark each
notice's own notification unread. A pause notice superseded while held is never
claimed and its held row is deleted with it. Turning quiet hours off, or moving the
window so the recipient is outside it, sets held notices due at once.

Delivery stays at-least-once with the same limit as before: a crash after Discord
accepts the summary but before it is acknowledged can repeat that summary outside
Discord's nonce window. Holding and release add no other duplicate. Startup repair
leaves held notices alone because they are pending, not failed or missing.
