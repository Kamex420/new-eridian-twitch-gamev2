# Reliability review

This release fixes verified queue, transaction, delivery and presentation gaps.
It does not certify the absence of every possible game or deployment bug.

| Area | Behavior now covered |
| --- | --- |
| Queue scheduling | Independent worker; one due attempt; cooldown waits spend nothing; no catch-up burst after downtime |
| Pauses | Immediate needs check after work, saved remaining attempts, automatic recovery, one alert per pause episode |
| Stops | Completion, cancellation, unavailable task and repeated internal errors create durable alerts |
| Faults | Rolled-back attempts retry with backoff; three consecutive errors stop automatic work |
| Accounting | Needs, inventory, counters and outbox transitions commit together; secondary and consumed-to-zero resources appear in receipts |
| Concurrency | Shared sessions and transaction-scoped world locks order queue work, game endpoints and account linking |
| Discord | Immediate acknowledgement; duplicate interaction receipts; saved-text fallback when rendering fails |
| Notifications | Independent leased outbox; bounded delivery retry; user-only mention whitelist; text fallback for rejected embeds |
| Database | PostgreSQL URL normalization, bounded waits, database/worker health reporting, additive tables |
| Privileged routes | Unset and placeholder administrative credentials are rejected |
| Presentation | Compact action receipts, immediate recovery warnings, dedicated information views and private pages for longer results |

## Operational limits

The automated suite uses SQLite and mocked outbound messages. Live PostgreSQL
locking, the deployed Railway container, real Discord/Twitch delivery and OBS
rendering were not exercised. Existing API/overlay route contracts and container
source imports are covered, but that does not replace deployment verification.

Workers require a running host and reachable database. A missing bot token or
missing channel access prevents alerts; queue results remain stored. Five failed
notification delivery attempts become terminal. The Discord.py sender performs
one recovery scan after login for failed or missing current-run stop alerts from
the previous 24 hours; sent alerts and older history are not replayed. A pending obsolete pause is suppressed,
but an alert already being sent may arrive after recovery.

A crash after Discord accepts a message but before local acknowledgement can
produce a duplicate alert beyond Discord's nonce deduplication window. This does
not replay game rewards. Incoming deferred requests are not a durable job queue:
a restart before command execution begins may require the player to request it
again. Persisted game queues resume normally. Saved Discord interaction IDs prevent
replayed requests from granting rewards twice; a newly issued command has a new ID.

The per-world transaction lock deliberately serializes writes. This is appropriate
for this game's shared balances; large-scale load testing is still outstanding.
Detail pages expire after 24 hours. Command receipts are retained and should be
included in database sizing and backup planning.

The Discord.py transport is tested with mocked text channels, including a complete
startup/timer/outbox/channel-send/shutdown lifecycle. Actual server delivery still
requires a valid bot token and channel permissions.
