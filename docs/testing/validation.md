# Validation record

The mining update passed 576 full-suite tests before this timing fix. The Discord acknowledgement fix then passed **50 focused tests**, covering response ordering, delivery retries, error replies, signed channel capture and background queues. Live Railway and Discord delivery were not exercised. The raw outputs are preserved in [results.txt](results.txt).

## Coverage

| Area | Evidence |
| --- | --- |
| Existing behavior | All prior 509 repository and gameplay tests remain included |
| Module ownership | ORM models have one canonical `app.models` identity; no private legacy loader modules are imported |
| Registrar isolation | Dry-run catalog loading leaves a fresh database path absent |
| Production source boundary | A subprocess imports the app from a temporary directory containing only `app/` and `scripts/` |
| Persistent compatibility | Old-schema migration, one-for-one item conversion, repeat conversion and linked balances |
| Queue behavior | Limits, needs/material pauses, passive recovery, failure counting, cooldowns and cancellation |
| Mining failure rewards | All ores and Coal, extraction machines, legacy mining routes, chance modifiers, rare progress preservation, blocked attempts, queue and completion-message totals |
| Autonomous completion | Ten-second due times, idle background execution, durable notification, mention whitelist, captured channel, retry/restart, worker claims and Twitch transport mocks |
| Work options | Success yields and failed-attempt costs for every configured method; resource uses and specialist gates |
| Coal | Mining autocomplete, personal inventory, source hint, branch practice classification and unchanged shop price |
| Queue outcome totals | Every gatherable material, all catalog recipes producing multiple items per batch, mixed success/failure, bonus yield, pause/reset, old history and summary rollback |
| Queue integrity | Concurrent workers, worker lifecycle, and rollback of effects plus counters after a simulated failure |
| Player interfaces | Discord dispatch/autocomplete, Twitch output limits, ore picker and task discovery |

The registrar dry run emits 49 command definitions. Python compilation and whitespace validation succeed. Catalog JSON and the historical Discord option fixture were compared byte-for-byte with the pre-cleanup source.

## Limits

Tests used temporary SQLite databases. The source-only subprocess check verifies the Dockerfile's Python import boundary, not a built container image. A Docker image build, live PostgreSQL concurrency, Railway deployment and live Discord/Twitch delivery were not exercised. Notification HTTP calls were mocked; tests did not send real messages. A local test pass therefore establishes repository consistency, not a claim that production was deployed or validated.

The catalog and migration fixtures are preserved evidence. The current option contract is stored separately in `tests/contracts/discord_options.json`; historical fixtures are not rewritten to match new behavior.

## Compact message validation

Full suite: 584 passed. The final navigation test file passed all 7 tests,
including two added checks for expiration and signed component routing.
One existing Starlette/AnyIO deprecation warning remains. Outbound messaging
is mocked; no live Discord or Railway deployment was tested. Tests verify
complete long-response preservation, compact queue totals and forecasts,
private read-only navigation, expired views and short replies without buttons.


## Queue reliability release

The full regression run passed **613 tests**. The final focused run validates
queue faults, Discord acknowledgements and message layouts after the final copy
cleanup; its exact output is recorded in `results.txt`. Python compilation and
`git diff --check` pass. The catalog and historical Discord fixture retain their
previous SHA-256 hashes.

New fault-injection checks cover pause/resume episodes, same-attempt needs stops,
completion at low needs, missing materials, cooldown copy independence, retries
and circuit breaking, outbox rollback, duplicate concurrent Discord interactions,
partial-command rollback, formatting failure, consumed-to-zero inventory,
secondary rewards, driver normalization, unavailable database health, default
admin-key rejection and plain-text alert fallback. Existing catalog acquisition,
crafting, economy, linking and overlay/API route-contract tests also pass.

One existing Starlette/AnyIO deprecation warning remains. The production limits
and delivery guarantees are documented in [Reliability review](../reliability.md).
