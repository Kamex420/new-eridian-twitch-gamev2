# New Eridian v2 — colony simulation update 7.0.0

This package implements an original SEED-inspired model for New Eridian. It does not use a SEED API, private game data, or proprietary simulation rules. New Eridian remains the settlement name; New Eridian v2 remains the game name.

## Install this update

For the combined material acquisition and passive recovery update, follow `COMBINED_UPDATE.md`. The original installation notes below describe the earlier simulation package.

1. Back up the deployed database with your database provider's backup/export facility. Keep the existing database and `DATABASE_URL`.
2. Unzip the download. Open `new-eridian-twitch-game-main/NEW_ERIDIAN_CUSTOM_API_COMPLETE`.
3. In your GitHub repository, replace **the complete `NEW_ERIDIAN_CUSTOM_API_COMPLETE/app` folder** with this package's `app` folder. Keep every new `.py` module beside `main.py`. Upload the included documentation and tests as well if you want the full repository to match.
4. Commit the files. Let the existing Railway deployment build, or redeploy it manually. The existing Dockerfile and `uvicorn app.main:app` command still work. Do not run the old `apply_balance_and_levelup_patch.py` script against this version.
5. Check `/health`: it should report version `7.0.0`. Existing API paths, StreamElements commands, Discord command names/options and OBS URLs remain valid. The Discord installer is unchanged; re-registering slash commands is not required for this update.
6. Test `/me`, `/guide`, `/job`, `/agriculture`, `/make`, `/sleep`, `/social` and your OBS source with a test account before inviting normal play.

**Do not paste only main.py.** It now imports the included modules. Do not replace the database, delete tables, or change `DATABASE_URL` to an empty database.

This package was edited and tested locally from your uploaded ZIP. It has not been pushed to GitHub or deployed to Railway.

## What changes in play

- Citizens are persistent Seedlings. Existing identities, linked accounts, balances, XP, jobs, inventory, relationships, projects and incident history are retained.
- Occupation/Job, Competency/Aptitude, Settlement/Society and SC/Settlement Currency are compatible vocabulary pairs. Existing command names and serialized database fields stay stable. There are still nine existing competency families; social growth uses the existing relationship system.
- All five life needs recover 1 point every 15 real minutes, up to 60/100, including while away. This replaces passive decay. Values above 60 are preserved. Partial ticks carry forward and repeated polling does not grant extra recovery. /eat, /sleep and social activities recover faster.
- Ordinary work costs 2 Energy, 1 Nutrition and 1 Comfort. Heavy work costs 3 Energy, 1 Nutrition and 1 Comfort. Work below 20 Comfort also costs 1 Morale. Existing Energy/Nutrition/Social readiness gates and free emergency food remain.
- Low Comfort reduces success by 10 percentage points below 20, or 4 below 35, before combined modifier caps. Needs and Siro exposure reduce training efficiency and supplementary settlement production. Good conditions preserve full production.
- `/sleep` still fully restores Energy and Comfort. Available settlement medicines can additionally reduce remaining exposure during sleep.
- Occupation-matching work adds 2 percentage points of success and improves practice gain by 25%, alongside the existing matching SC bonus.
- Successful tasks accumulate fractional competency practice. Conditions, occupation, active matching projects and outcome/craft quality affect gain. Whole points go into the **existing** XP fields; fractions are saved until the next task. A result can legitimately bank 0 whole XP while gaining fractional practice. Failed tasks retain Determination, without success XP or production.
- Existing levels and Lv. 10 specializations remain valid. `LEVEL UP` appears in action results, persists in the journal and latest-progress status, and is placed ahead of flavor text on Twitch. Mentoring also reports the learner's advancement.
- Relationships improve cooperation in Research, Logistics, Commerce and Infrastructure. Old unattended friendships lose effective cooperation gradually, capped at half their familiarity; earned history is retained. Social interaction improves shared mood. Low Social can reduce new relationship gains.
- Incidents retain their existing rewards, penalties, support ratios, timers and history. Their aftermath now also changes community mood and relevant shared stocks.

## Connected shared production

The existing Food, Materials, Development, Knowledge, Treasury and Reputation remain authoritative. New shared stock fields supplement them; personal Ore, Components and Cargo are separate from settlement stocks.

| Successful activity | Supplementary settlement effect |
| --- | --- |
| Irrigation or scan | +3 Water under good conditions, +2 under pressure |
| Agriculture | Uses 1 shared Water for +2 extra Food, or +1 under pressure |
| Mine/scavenge | +2 shared Ore, or +1 under pressure |
| Rare search | +1 shared Rare Ore |
| Fabrication/work/make | Uses 1 shared Ore for +2 Components, or +1 under pressure |
| Build/repair/project | Uses 1 shared Component for +2 Infrastructure, or +1 under pressure; every 5 Infrastructure adds a housing place |
| Research | Uses 1 shared Component for +2 Medicines, or +1 under pressure |
| Cargo/spaceport | Uses 1 shared Component for +2 shared Cargo, or +1 under pressure |
| Delivery | Uses 1 shared Cargo for extra Reputation |
| Market/business | Uses 1 shared Cargo for extra Treasury |
| Emergency community meal | Uses 1 settlement Food if available; emergency recovery remains possible when reserves are empty |

These are additional production chains. Missing shared inputs do not remove legacy command rewards, but prevent the supplementary conversion. Material production never consumes unavailable stock. Existing personal crafting recipes still consume their own listed inputs.

Settlement Food and Water have bounded four-hour upkeep, scaled by population and capped at six elapsed ticks per catch-up. Water scarcity, housing pressure, poor community mood, habitat shortages, market disruption and exposure affect work success. Existing food/material shortages still apply.

## Routines and future simulation

`/guide` and status views display a current routine recommendation: emergency food, rest/comfort, morale recovery, social recovery, occupation work, project support or leisure. No action is awarded simply for polling status.

Additional API endpoints:

- `GET /api/v1/settlement?channel=...`: structured shared stocks and pressures.
- `GET /api/v1/routine?channel=...&uid=...&provider=twitch`: mood, need urgency, occupation/history, goal and next action. Optional `goal` accepts `settlement`, `occupation`, `recovery`; `preferred` accepts `games`, `walk`, `relax`.
- `POST /api/v1/admin/routine/step`: operator-triggered single routine action through existing handlers and cooldowns. Requires a non-default `ADMIN_KEY` in the `key` parameter. Do not place that key in public chat or public overlay URLs.

There is no background bot population, automatic spending for offline players, external SEED integration or new election/government feature in this version. Operator-driven single steps provide the foundation for future simulation. Existing social standing, shared projects, reputation and relationships remain the civic layer.

## Architecture and compatibility

| File | Responsibility |
| --- | --- |
| `app/db.py` | Existing database configuration, engine, session and base |
| `app/models.py` | Unchanged legacy tables plus additive simulation tables and canonical aliases |
| `app/migrations.py` | Existing additive upgrades plus schema-version recording |
| `app/needs.py` | Passive recovery, need urgency, mood and productivity |
| `app/occupations.py` | Occupation competencies, preferred work and design associations |
| `app/competencies.py` | Compatible levels, rank labels and practice formula |
| `app/settlement.py` | Shared stock state, bounded upkeep, pressures and production |
| `app/seedlings.py` | Deterministic priority selection |
| `app/events.py` | Colony incident effects |
| `app/progression.py` | Persistent and request-local milestone notices |
| `app/commands.py` | Shared response adapter, actual deltas and notifications |
| `app/main.py` | Existing routes, command dispatch, recipes, world content and overlay |

This is a staged refactor: the simulation core is modular; legacy route handlers and large content/overlay definitions remain in `main.py` to reduce compatibility risk. Twitch and Discord share the same simulation functions. Existing handler transaction boundaries remain; concurrent production-load testing and a full transaction architecture rewrite are outside this package's verification.

New tables: `simulation_schema_versions`, `seedling_state_v7`, `settlement_state_v7`. Existing tables are not dropped, renamed or reset. New per-seedling and settlement state initializes lazily. Account merging preserves new practice/history and safely combines duplicate legacy relationship pairs.

## Verification and rollback

From `NEW_ERIDIAN_CUSTOM_API_COMPLETE`:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary SQLite databases. They cover the original route/signature contract, all core action success paths, registered Discord dispatch, both-platform level-up notices, fractional/need effects, crafting inputs, failures, emergency recovery, routines, incidents, overlays, relationship merging and repeatable migration of a seeded old-schema save.

PostgreSQL production execution, live Discord signature delivery, live Twitch/StreamElements calls and Railway deployment were not exercised here. The existing requirements and installer were preserved.

To roll back application code, restore the previous commit/package while keeping the database. The old application ignores the additive tables. If you also need to undo gameplay performed after deploying, restore a provider database backup deliberately; that loses the intervening play history.
