# Validation record

The buttons-everywhere update adds `tests/test_buttons_everywhere.py`: every player command option is reachable from `/menu`, buying through pages, amount buttons and a custom-amount form, selling only amounts you own, the search, find, link and business forms, dropdown views, the public panel opening a private menu per player, moderator tools hidden and refused for players, and the extra reply row.

The planning-and-convenience update passed **888 tests**, including `tests/test_extras.py`: live countdown timestamps (plain text on Twitch), queue max limited by ingredients and needs, recent actions and `!again`, goals with next steps and self-clearing, plans with sell steps run by the queue worker, routines, item uses, welcome-back and one-time reminders, auto-sell that keeps protected ingredients, 60-second sale undo, eat until full, `/find` on both platforms and the remembered Workbench place.

The private-notification update passed **868 tests**, including `tests/test_inbox.py`: queue events reach the inbox, private alerts skip the channel ping, pinged events are already read, popups follow the Important/All/Off setting and are sent once as ephemeral follow-ups, starting a short queue warns immediately, tips show once, the short queue status hides requirements behind Details, and the inbox view marks items read.

The button-menu update passed **857 tests**. It adds `tests/test_menu.py`: every area opens within Discord limits (≤5 rows, ≤25 buttons, custom IDs ≤100), every leaf maps to a real command and options, every view button renders, action buttons run once and bring back their area, choice lists run or confirm (selling needs Confirm), social choices offer activities, and replies carry Again/area/Menu buttons.

The message-readability update passed **787 tests**, including `tests/test_presentation.py` (8 tests): small task receipts without footer or fields, one-line notices, title-cased information cards with bold labels and sections, short titles for long first lines, level-up notes kept out of titles, formatted need/item/practice changes, one-line Twitch task replies, and Details pages for very long views.

The Comfort, festival-food and command-menu update passed **779 tests**. It adds `tests/test_festivals_and_commands.py` (17 tests): all 27 festival foods are edible, sellable Survival Workbench recipes from gathered ingredients; recipes lock outside their window and craft inside it; eating adds the festival Comfort bonus; Comfort costs equal Energy and relax restores +20; the registered menu has 31 commands; every grouped command translates to its original handler; and game text is rewritten to the grouped commands.

The quality-of-life update passed **759 tests**. New coverage in `tests/test_quality_of_life.py` (27 tests): the status view on both platforms, Recover now, favourites (idempotent buttons, cap, ⭐ markers), Ready now on Discord and Twitch, fetch plans that queue a gather and chain the craft, buying missing ingredients, next queues starting on completion and clearing on cancel, Repeat from `/queue`, alerts and the Discord view, recovery estimates, auto-recover (relax, games, cheapest food), quiet/off/DM alert modes including the DM fallback, sell all, clear-out protection of favourite ingredients, inventory search/sort/filters, fuzzy names, next-step hints and tier-up notes. The registrar dry run emits 51 command definitions. Discord and Twitch deliveries were mocked; live delivery and Railway were not exercised.

The Workbench, Comfort and catalog-item update passed **729 tests** (one environment-specific source-boundary test deselected locally because the sandbox installs dependencies through `PYTHONPATH`). New coverage in `tests/test_workbench_ui.py`: easiest-first ordering in every category, Discord label and custom_id limits, read-only navigation, single-use Craft and Start buttons, other-citizen and expired-button rejection, queue plans, slash panels and Twitch pages within 380 bytes. The registrar dry run emits 49 command definitions, each under Discord's size limits. Live Discord and Twitch delivery were not exercised.

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


## Discord.py queue sender

Full regression: **628 passed**, with two dependency deprecation warnings
(Starlette/AnyIO and Python 3.12 audioop). Two additional recovery/lifecycle tests
were then added; the final focused Discord.py file passed all 17 tests before
final diagnostic copy cleanup. The final combined Discord.py/autonomy run passed **64 tests**; output is recorded in results.

Coverage includes real async send arguments, channel fetching, allowed mentions,
DM rejection, embed fallback, missing/invalid/wrong-app tokens, concurrent leases,
rate-limit retry, visible permission errors, recent failed/missing notice repair,
orphaned event repair, suppression of older/sent notices, and an end-to-end timer
that produces the second channel message. Outbound Discord calls are mocked;
no live Railway or Discord session was used.
