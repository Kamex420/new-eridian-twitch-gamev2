# New Eridian v2 — materials, test repairs and passive life recovery

This package replaces the previous Material Acquisition Update. It includes all of that update plus passive recovery and corrected tests. Based on repository commit e8168e8e0a13101c7fe34e9c48083a4222951d92, still the current remote main when checked. The society remains New Eridian.

## Gameplay changes

- Energy, Nutrition, Social, Comfort and Morale each recover 1 point per 15 real minutes, up to 60/100. Recovery includes time away and is applied when the citizen is next accessed. It also progresses during play.
- This replaces passive time decay. Action costs remain. Needs above 60 are preserved, not reduced. Food, sleep and social activities remain the faster recovery options, including recovery above 60.
- From zero, 5 hours restores 20 points (the work gate), 8 hours restores 32, and 15 hours restores 60. A shorter absence may still leave a depleted player below the work gate.
- Recovery does not spend food, SC or shared stocks and grants no XP, rewards or actions. Partial 15-minute intervals carry forward; polling cannot repeat credit or bank extra credit at the cap.
- Existing saved life timestamps are reused; no schema change or player reset. Previously elapsed time may provide recovery on the first access after deployment.
- The material update adds exact sources, complete /gather pages, catalog acquisition plans and Twitch gathering/lookup templates. All 651 active SEED items and all 665 recipes have reachable supply paths. See MATERIAL_ACQUISITION.md for details.

## Install together

1. Open COPY_FILES.html for complete files and Copy buttons. Work on a branch based on your current repository. This package targets the base commit above; compare newer edits before replacing files.
2. Replace these FIVE runtime files, preserving exact paths:
   - main.py (root)
   - needs.py (root; app/needs.py remains the existing compatibility wrapper)
   - app/seed_content.py
   - app/command_catalog.py
   - app/twitch_help.py
3. Add/update test_colony.py, test_material_acquisition.py, discord_options.json and the supplied documentation/test report. Keep legacy_discord_options.json as historical evidence. Keep all other repository files and app/data/seed_catalog.json.
4. Deploy the combined change using your existing Railway workflow. Keep DATABASE_URL and the current world ID. No database reset, new environment variable or scheduled job is required.
5. Rerun the existing register_discord_commands.py in the same registration scope to publish /gather Page. The new recovery rule alone does not require registration.
6. Add/update the five material-related Twitch entries at the end of streamelements_chat_installer_TEMPLATE.txt: !gather, !gatherpage, !catalog, !training and !make. Replace YOUR-API-DOMAIN and use the SAME world/channel value as your existing working commands. Use !command edit for commands already installed. Do not reinstall unrelated entries.
7. Check /me → Life Needs, /gather → Page, /catalog → Item and a crafting preview. After an absence, verify needs have recovered; reopening the same view immediately must not add points again.

No remote commit or deployment was performed. The GitHub integration previously rejected branch creation with HTTP 403. These are complete local replacement files.

## Test repairs and verification

The prior 33 failures are resolved without removing the relevant tests:
- Training success tests supply the selected task's materials and required level. Separate tests confirm missing materials and insufficient levels still block tasks without starting cooldowns.
- Harvesting, crafting and mentoring notification tests cross real current level thresholds. Their response/persistence assertions remain.
- API compatibility still requires every historical route and its ordered parameters; extra parameters must be optional.
- Current Discord options are compared with the reviewed discord_options.json snapshot. The historical snapshot is retained unchanged.

Full suite: 228 passed; one third-party Starlette/AnyIO deprecation warning. Includes 35 material-acquisition tests and recovery checks for elapsed time, cap, partial ticks, clock reversal, repeated access, durable persistence, and both platforms. Python compilation and git diff whitespace checks pass.

Tests use SQLite. Live Railway/PostgreSQL, Discord/Twitch delivery and concurrent production load were not exercised.
