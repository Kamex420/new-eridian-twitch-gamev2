# New Eridian v2 — starter economy and workshop progression

Prepared from Kamex420/new-eridian-twitch-gamev2 main commit 28dcd45, with the previous material-acquisition, repaired-tests and passive-life-recovery updates retained. Society name: New Eridian. This update is prepared locally, not deployed.

## Install using the copy page

1. Work on one GitHub branch. Replace all runtime files from the page together: main.py, app/seed_content.py, app/command_catalog.py and app/twitch_help.py. CREATE the new app/crafting_progression.py. The page also includes needs.py to preserve the previous recharge policy.
2. Update test_colony.py, test_material_acquisition.py, discord_options.json and the documentation/report; CREATE test_crafting_progression.py. Keep legacy_discord_options.json as historical evidence. Keep every other repository file, especially app/data/seed_catalog.json and app/needs.py.
3. Deploy the complete branch through your existing Railway setup, keeping DATABASE_URL and your world ID. No database reset or new environment setting is required. Existing inventory and completed crafting history are retained.
4. Run the existing register_discord_commands.py in the same registration scope. This publishes /workshop and Seed Industries' Category, Page and Starter Routes options. Preview the definitions without changing Discord using --dry-run.
5. Add/update the new Twitch templates: !workshop, !workshopunlock, !workshoppage, !seedpage, !seedbuy and !seedstarters. The corrected !seedindustries entry is included. Retain !gather, !gatherpage, !catalog, !training and !make from the earlier update. Use your deployed API domain and the same channel/world ID as your existing working commands. Use !command edit for commands already installed.

GitHub previously rejected branch creation with HTTP 403. No remote write, registration or live deployment was performed in this task.

## Seed Industries

There are 60 stock listings. All 26 natural SEED resources are sold, including the four gated rare ores. Starter materials for 20 catalog crafting routes and all legacy training-task inputs are covered. Existing legacy prices and buyback values are unchanged.

- /seedindustries → Starter Routes by Branch shows the recommended starter recipe, complete batch inputs, exact purchase total, station, tier and skill level. Page reaches every route. Buying materials alone does not unlock the skill or station.
- Browse Market supports Category and Page. Buy uses Item and Amount (1–25). Autocomplete filters the chosen category; Sell only suggests items the market actually buys back.
- SEED items are labelled separately from legacy training supplies, so SEED Hematite Ore is not confused with legacy Ore, and SEED Lumber is not legacy Wood.
- Common raw supplies generally cost 4 SC per unit; common ores 6 SC. Processed starter prices are derived from input purchase costs plus processing labor, divided by output quantity and rounded up (minimum 2 SC). Large output batches therefore have lower per-unit prices.
- New starter stock is buy-only: Seed Industries does not buy it back. This prevents new buy/craft/sell cash loops. Existing legacy trade and production orders retain their original prices. Gathering and manufacturing your own supplies remain the cheaper route.

## Rare ores

Argentite, Bauxite, Aurite and Rutile require Harvesting level 3 (12 XP). Reach it by gathering common materials or mining. Each rare ore requires THREE prospecting actions; progress is saved separately for each ore.

Each attempt costs 3 Energy, 1 Nutrition and 1 Comfort, grants Harvesting/Ore Mining practice, and starts a shared 20-second prospecting cooldown. Only the third action yields one ore. Switching ores or using an extractor recipe does not bypass this cooldown or effort. Extractor crafting also requires the matching station and recipe tier; an owned matching machine retains its practice bonus.

NPC purchases require the same Harvesting level. Argentite and Bauxite cost 24 SC each, Rutile 32 SC and Aurite 36 SC. Purchases are an expensive alternative to prospecting. New rare ores have no NPC buyback. The existing legacy item named Rare Ore is a separate inventory item and retains its existing /rare and market rules.

## Recipe tiers and stations

| Personal tier | Completed manufacturing batches | Typical station access fee |
| --- | ---: | ---: |
| 1 — Starter | 0 | 15 SC |
| 2 — Skilled | 25 | 45 SC |
| 3 — Industrial | 100 | 120 SC |
| 4 — Advanced | 250 | 300 SC |

The Survival Workbench is free from the start. Its recipes can produce the first Basic Workbench without owning another station. Every SEED recipe has an explicit station; the three catalog recipes missing a station are assigned Stove (Tomato Soup), Advanced Workbench (Basic Vending Machine) and Hydroponic Growbox (Wheat).

Other stations require a ONE-TIME permanent community-access fee, or ownership of the matching machine. Fees are per named station, not per batch. A Basic Workbench does not stand in for an Electronics Workbench. If a recipe lists alternatives, access to one matching station is sufficient. Owning machinery does not bypass recipe tiers or skill requirements.

Personal tiers use existing completed /make manufacturing history. Each recipe execution with ingredient inputs counts as one batch regardless of output quantity. Legacy crafting recipes count too. Gathering, extraction, market purchases and /training do not count toward these tiers. Their normal skill progress remains. Past manufacturing batches count automatically.

The /make skill requirement remains separate from its personal tier and station. Legacy society-tier unlocks also remain in force. /workshop shows current progress, each tier threshold, station costs and access. /make category previews and /catalog show the required station and tier; blocked attempts explain the missing requirement without consuming inputs. Manufacturing /training tasks also use the relevant station. Natural gathering requires no workbench.

To start: gather Lumber and Stone → make a Basic Workbench at the free Survival Workbench → open /seedindustries Starter Routes for your chosen branch → unlock its station, acquire the listed inputs and train the listed skill. Keep making lower-tier recipes to reach the next personal tier.

## Previous changes retained

All five life needs recover +1 per 15 real minutes up to 60/100, including time away. Food, sleep and social activities recover faster. All 651 active SEED items and 665 recipes remain reachable; the graph checks now also include tier, station availability and skill progression.

## Verification

281 tests pass. Checks cover every catalog recipe's station mapping and tier/skill progression, the free starter-workbench path, all 37 station access purchases, exact fees and repeat-unlock protection, wrong/missing stations, ownership without tier bypass, rare-ore gates and persistent progress, shared prospecting cooldowns, starter coverage, market prices/quantities/no-buyback, Discord dispatch, full market pages, existing acquisition tests and passive life recovery. Python compilation, whitespace checks and Discord registration dry-run pass.

Tests use SQLite. Live Railway/PostgreSQL, live Discord/Twitch delivery and concurrent production load were not exercised. Price balance is based on the current code's economy and guarded trade rules, not live-player telemetry.
