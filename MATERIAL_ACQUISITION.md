# New Eridian v2 — obtainable crafting materials

Based on Kamex420/new-eridian-twitch-gamev2 commit e8168e8e0a13101c7fe34e9c48083a4222951d92 (24 September 2026 review). New Eridian remains the society name.

## Findings and changes

All 651 active SEED catalog items have a finite route from 26 gatherable resources. All 665 recipes are reachable after gathering and repeatable skill practice; community workshops require no purchased machine. The older recipes, quality gear and training supplies also have obtainable ingredients. No new currencies, free manufactured goods or save migration are needed.

The gap was discoverability. This update adds exact sources to ingredient previews and missing-material messages, paged gathering lists, and a catalog acquisition plan with base gathering quantities and ordered crafting batches. Plans are for one item from scratch, keep surplus, and identify skill requirements; owned ingredients can reduce the work. /make Raw Materials now includes legacy Wood, Water, Stone and Herbs. Twitch templates add !gather, !gatherpage, !catalog, !training and !make.

## Install

For this combined package, follow COMBINED_UPDATE.md; it also includes needs.py, updated tests and current command snapshots.

1. Open COPY_FILES.html for complete file contents and Copy buttons. On GitHub, create a working branch from your current main. This update is based on the commit above; compare later edits before replacing files.
2. Replace all four runtime files together, keeping exact paths: main.py, app/seed_content.py, app/command_catalog.py, app/twitch_help.py. Keep all other repository files, including app/data/seed_catalog.json and the database configuration.
3. Add test_material_acquisition.py and this note. Merge/deploy the complete update through your normal Railway process. No database reset.
4. Run the existing register_discord_commands.py in the same Discord registration scope to add the /gather Page option.
5. Add/update the five Twitch commands at the end of streamelements_chat_installer_TEMPLATE.txt, or use the CSV entries. Replace YOUR-API-DOMAIN with your current domain and keep the same channel/world expression as your existing working commands. The templates retain the repository's $(channel.provider_id); if your installation uses a fixed world ID, use that same ID. Do not reinstall unrelated commands. Use !command edit instead of add when a command already exists.

GitHub rejected branch creation with HTTP 403 (Resource not accessible by integration). No remote branch, commit, pull request, live command registration or deployment was made by this task.

## Player instructions

- Discord: /gather with Resource blank lists materials. Select Page for more; type a resource's name in Resource to find it, then submit to collect it. Gathering needs no item, tool, SC or skill level, but work needs and cooldown still apply.
- /catalog → Item shows HOW TO OBTAIN and a paged ACQUISITION PLAN. /make → Production Tree + Recipe previews quantities and exact ingredient sources without spending.
- Twitch: !gather lists materials; !gatherpage 2 shows more. !gather Hematite Ore collects the named resource; !catalog Hematite Ore explains its source. Stable sd_... item IDs also work. !make sr_... crafts the exact recipe returned by lookup.
- Legacy supplies: Crops → /farm Harvest Crops; Ore → /mine; Rare Ore → /rare or Seed Industries; Cargo → /cargo. Wood/Water/Stone/Herbs → /training Harvesting with the matching task. Cloth → Processing/Textile Processing; Medicine → Medicine/Pharmacy.
- Personal SEED Hematite Ore is not legacy Ore, Lumber is not Wood, and Murky Water is not legacy Water or Clean Water. Match the exact recipe ingredient. Shared settlement stocks are also separate.
- If needs block work, use /sleep, /games, and /eat (emergency food is available when starving without food).

## Validation

35 acquisition tests pass. These cover all 651 item plans by replaying their inventory flows, all 665 recipes with beginner skill progression, all 26 real gathering handlers from new citizens, legacy/training ingredient reachability, full menu coverage, source messages, blocked gathering, and actual gathering → Clean Water crafting without granted supplies. Compilation and whitespace checks pass.

The 33 previously failing checks have now been corrected and pass in the combined update. Training tests provision their prerequisites; separate tests verify missing materials and skill locks still block tasks. Level-up tests now cross the current XP thresholds. The current Discord contract is saved separately from the historical snapshot. See COMBINED_UPDATE.md and TEST_RESULTS.txt for final validation.
