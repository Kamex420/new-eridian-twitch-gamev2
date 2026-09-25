# Validation record

The mining failure and Stone Dust update passes **576 tests**. The raw result is preserved in [results.txt](results.txt). One warning originates from the third-party Starlette/AnyIO test client; no tests were skipped.

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
