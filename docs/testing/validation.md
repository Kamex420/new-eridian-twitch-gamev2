# Validation record

The combined mining/queue update and source-layout cleanup pass **332 tests**. The raw result is preserved in [results.txt](results.txt). One warning originates from the third-party Starlette/AnyIO test client; no tests were skipped.

## Coverage

| Area | Evidence |
| --- | --- |
| Existing behavior | All prior 329 gameplay, route, command, inventory and queue tests remain included |
| Module ownership | ORM models have one canonical `app.models` identity; no private legacy loader modules are imported |
| Registrar isolation | Dry-run catalog loading leaves a fresh database path absent |
| Production source boundary | A subprocess imports the app from a temporary directory containing only `app/` and `scripts/` |
| Persistent compatibility | Old-schema migration, one-for-one item conversion, repeat conversion and linked balances |
| Queue behavior | Limits, needs/material pauses, passive recovery, failure counting, cooldowns and cancellation |
| Queue integrity | Concurrent workers, worker lifecycle, and rollback of effects plus counters after a simulated failure |
| Player interfaces | Discord dispatch/autocomplete, Twitch output limits, ore picker and task discovery |

The registrar dry run emits 49 command definitions. Python compilation and whitespace validation succeed. Catalog JSON and the historical Discord option fixture were compared byte-for-byte with the pre-cleanup source.

## Limits

Tests used temporary SQLite databases. The source-only subprocess check verifies the Dockerfile's Python import boundary, not a built container image. A Docker image build, live PostgreSQL concurrency, Railway deployment and live Discord/Twitch delivery were not exercised. A local test pass therefore establishes repository consistency, not a claim that production was deployed or validated.

The catalog and migration fixtures are preserved evidence. The current option contract is stored separately in `tests/contracts/discord_options.json`; historical fixtures are not rewritten to match new behavior.
