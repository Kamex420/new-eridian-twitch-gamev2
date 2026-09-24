# New Eridian v2 — Unified Items Update

The in-game society remains **New Eridian**. This package includes the preceding crafting progression, starter-market, material acquisition and passive needs recovery changes.

## Install

1. Create a branch from the repository containing the preceding update. Copy each complete file to its exact path using this page. Create **app/item_identity.py** and **test_item_identity.py**. If the preceding update has not been installed, also create app/crafting_progression.py and the other files marked NEW.
2. Keep all unlisted repository files, including **app/data/seed_catalog.json** and **legacy_discord_options.json**. Do not replace main.py with this HTML page.
3. Take a database backup before deployment. Deploy all runtime changes together; avoid running old and new app versions against the database simultaneously during conversion.
4. On startup the application merges existing player inventories automatically. It repeats the same safe check on player access and account linking. Players do not run a conversion command.
5. Rerun the existing Discord registrar so option labels show the new names without “SEED:”. Existing command URLs and IDs remain valid. The included Twitch templates retain the preceding update; use the deployment URL and world ID already used by your working commands.

No GitHub push, Railway deployment, production migration or live command registration was performed here.

## Exact conversion table

Existing new-item stock is added to converted stock. Example: 8 old Circuit Boards + 3 catalog Circuit Boards = **11 Circuit Boards**. This preserves item count, not historic SC purchase price. Players receive their full converted stock regardless of current unlocks; using recipes still requires their listed station, tier and skill.

| Previous item | Unified item | Quantity conversion | Buy SC/unit | NPC sell SC/unit |
| --- | --- | --- | ---: | ---: |
| Rare Ore | Argentite Ore | 1 → 1 | 24 | 8 |
| Ore | Hematite Ore | 1 → 1 | 6 | 2 |
| Wood | Lumber | 1 → 1 | 4 | No buyback |
| Water | Murky Water (1000ml) | 1 → 1 | 4 | No buyback |
| Stone | Stone | 1 → 1 | 4 | No buyback |
| Herbs | Herbs | 1 → 1 | 4 | No buyback |
| Planks | Wood Planks | 1 → 1 | 2 | No buyback |
| Cut Stone | Stone Block | 1 → 1 | 4 | No buyback |
| Cloth | Fabric | 1 → 1 | 20 | No buyback |
| Antiseptic | Antiseptics | 1 → 1 | 12 | No buyback |
| Circuit Board | Circuit Board | 1 → 1 | 84 | No buyback |
| Power Cell | Power Cell | 1 → 1 | 7 | No buyback |

There are **53 distinct Seed Industries listings** after removing duplicates. Canonical catalog material prices remain; Circuit Board and Power Cell use the existing ingredient-plus-labor pricing calculation. Converted manufactured supplies have no NPC buyback, preventing cheap alternate supply routes from creating a resale loop. Hematite retains the old Ore buy/sell prices. Argentite uses its existing 24 SC rare-ore purchase price and inherits the old 8 SC fixed buyback. The dynamic market still uses the prior ore and rare-ore sale formulas. Order payments use canonical replacement costs, so aliases cannot quote different values.

## One stock, all commands

- Old input names such as wood, cloth, circuit_board, ore and rare_ore remain accepted as aliases. They cannot create another inventory balance.
- /mine produces Hematite Ore. /rare prospects Argentite Ore: Harvesting Lv.3, three actions per unit, shared 20-second cooldown. Purchases through the old rare_ore alias also require Lv.3 and cost 24 SC.
- Random extraction/frontier bonus finds award Mineral Samples instead of bypassing rare-ore prospecting. Other three rare ores remain distinct.
- Old Circuit Board/Power Cell /make requests resolve to the canonical recipe. Duplicate old recipes are removed from the legacy browse menus. Recipe history is retained for tier progress.
- Training tasks that manufacture merged materials use the canonical recipe's input quantities, output batch, station, tier and required skill. These completed manufacturing batches count toward workshop tiers; gathering and non-manufacturing training do not.
- Inventories, catalogs, training, crafting, trading, account linking and resource-change messages share the same identities. “SEED:” and “SEED ·” item/category prefixes are removed. Seed Industries keeps its business name.
- Distinct supplies without a matching catalog identity remain: Crops, Components, Cargo, Biofiber, Alloy Plate, Sealant, Precision Lens, Medicine, Storage Jar, Preserved Food, Rations and unique equipment/quality gear. A generic medical supply is not arbitrarily exchanged for one specific treatment; Alloy Plate is not silently turned into a specific metal.

## Persistence and rollback

Conversion runs inside a database transaction. The player row is locked before inventory aggregation; source quantities are zeroed only in the same transaction that adds destination quantities. Repeating conversion cannot award them again. Account linking converts both sides before combining them. There are no new tables, dropped tables, player resets, or changes to account IDs, XP, SC, equipment quality or needs.

Hematite and Argentite use the existing ore and rare_ore database columns internally, preserving mining, dynamic trade, account merge and overlay compatibility. Those are storage names only; the catalog reads the same quantities. Other converted materials use their canonical catalog IDs. Old zero-balance inventory rows are retained.

Rolling back application code alone does not undo conversions to canonical item IDs. If a rollback is needed, use a migration-aware rollback or restore the pre-deployment backup, accounting for any subsequent play. Do not deploy the old code against a converted database as an undo procedure.

## Verification

**303 tests passed** with one third-party Starlette/AnyIO deprecation warning. Full output: TEST_RESULTS.txt.

Coverage includes every mapped item's old-plus-new balances, repeated conversion, persistence, transaction rollback, separate players, linked accounts, legacy aliases, canonical crafting consumption, market deduplication/prices, rare prospecting gates/cooldown, and ingredient reachability. Existing route, command, needs, workshop and colony tests remain included. Python compilation and Discord registrar dry run pass.

Tests used temporary SQLite databases. Production PostgreSQL/concurrent traffic, Railway, and live Discord/Twitch delivery were not exercised. This page contains complete replacement files, not snippets.
