# Persistence and compatibility

Existing table names, player identifiers, route signatures and catalog IDs remain compatibility contracts. Moving Python source files does not rename database tables or reset saves. The database engine still uses `DATABASE_URL` and existing migrations remain additive.[^1]

## Item identities

Twelve overlapping legacy item types map to canonical catalog items. Conversion adds quantities one-for-one to existing destination stock, then zeros source quantities within the same transaction. Repeated conversion cannot award the same stock again. Hematite and Argentite remain backed by the existing `ore` and `rare_ore` player columns; their public names and catalog IDs refer to those same balances.[^2]

The catalog JSON is unchanged by this cleanup. Historical `legacy_discord_options.json`, route fixtures and the old SQL schema are retained under `tests/fixtures/`; they are evidence for regression tests, not live command definitions.

## Queue transactions

One `task_queues_v1` row belongs to a player within a world. Active state stores the exact task, total attempts, remaining attempts, next eligible time and most recent result. A failed attempt counts; a blocked attempt does not.

The additive `task_queue_totals_v1` table stores successes, failures, prospecting-only steps, and JSON maps of item gains and spending. No existing queue columns are changed. Each attempt compares canonical material and quality-equipment inventory inside the same transaction; positive and negative per-attempt changes are accumulated separately. Internal prospecting counters are excluded. These are net inventory changes per attempt, including bonus yields, rather than numbers inferred from message text.

Starting a new queue resets its totals. Cancellation preserves completed totals. Account linking transfers or discards the summary with its corresponding queue. Legacy attempts are not backfilled from the last result, because that result cannot establish earlier outcomes.

The worker binds gameplay sessions to an outer transaction because existing handlers commit internally. Gameplay effects and the queue counter then commit together. PostgreSQL row locks serialize attempts for a player; SQLite uses `BEGIN IMMEDIATE`. A simulated failure after a handler's internal commit verifies that inventory, needs, cooldowns and queue progress roll back together.[^3]

The worker executes at most one eligible attempt per player per polling pass. Downtime therefore does not produce a burst of accumulated actions. Needs and requirements are checked again before each attempt; materials are not reserved at queue creation.

## Linked accounts

Inventory conversion occurs before account balances are combined. Account linking retains at most one active queue. An active target-account queue takes priority when both accounts have one; otherwise the source queue transfers. Completed work remains part of the merged balances, and queue status records cancellation of a conflicting queue.

## Rollback semantics

The filesystem cleanup is independent of the database format. Earlier item conversion is not reversed by restoring older source files: a version that still expects separate legacy stock cannot safely interpret a converted save as though conversion never occurred. Queue records are additive, but an application without the worker will not process them. A data-aware rollback or a database snapshot is required when reversing persistent migrations, with the usual consequence that restoring a snapshot loses later changes.

[^1]: [`app/migrations.py`](../app/migrations.py) and [`app/models.py`](../app/models.py).
[^2]: Exact mappings and migration logic: [`app/item_identity.py`](../app/item_identity.py).
[^3]: Transaction tests: [`tests/test_task_queue.py`](../tests/test_task_queue.py). PostgreSQL execution has not been validated against a live deployment in this release.

## Completion delivery

`queue_destinations_v1` records a unique queue run ID, original player identity, platform and Discord channel. The channel comes from the verified Discord interaction and is scoped to that request. Linking accounts moves this destination with its active queue.

Completion inserts one immutable `queue_notifications_v1` outbox row in the same transaction as the final rewards and counters. A separate lifecycle worker sends notifications; network requests never hold up the work scheduler. A conditional update claims a two-minute delivery lease. Retry attempts are bounded at five, with backoff and rate-limit delays; invalid credentials or permissions become terminal failures. An expired lease can be reclaimed after a process restart.

Discord messages use an explicit user mention whitelist, disabling role and everyone mentions, with a stable nonce for retry deduplication. Remote send and database acknowledgement cannot be made atomic: a crash after acceptance may duplicate a notification outside Discord's deduplication window; it cannot duplicate game rewards. No interaction tokens are stored, and no completion DMs are sent.
