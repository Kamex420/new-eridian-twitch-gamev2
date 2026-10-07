# Architecture

The application now has one canonical Python package. Earlier releases stored implementations at the repository root and used `app/` wrappers to load them under private module names. Those wrappers and the dynamic loader have been removed. Models, functions and mutable state now have ordinary `app.*` module identities.[^1]

## Ownership

| Module | Main responsibility |
| --- | --- |
| `main.py` | ASGI entry point and facade: imports the modules in `game/` in order and offers their names as `app.main.<name>` |
| `game/` | The game behind `app.main`, one module per topic (see below) |
| `db.py`, `models.py`, `migrations.py` | Database engine, ORM records and additive schema migration |
| `commands.py` | Shared response context and before/after state summaries |
| `seed_content.py` | Catalog lookup, acquisition graph, gathering, recipe execution and item uses |
| `item_identity.py` | Canonical aliases, one-for-one inventory conversion and market consolidation |
| `crafting_progression.py` | Workstation access, manufacturing tiers, rare prospecting and starter prices |
| `task_queue.py` | Saved queue state, worker lifecycle and transactional execution |
| `needs.py` | Elapsed-time recovery and productivity effects |
| `competencies.py`, `progression.py`, `seed_skills.py` | Skill vocabulary, practice and progression |
| `practice.py` | Lucky finds: the item lists by training branch and main skill, and the occasional find after a successful task |
| `settlement.py`, `seedlings.py`, `occupations.py`, `events.py` | Shared simulation, citizen routines, jobs and incidents |
| `command_catalog.py`, `twitch_help.py` | Platform command definitions and help text |
| `fun_systems.py`, `seasonal.py` | Supplemental activities and calendar flavor |
| `inbox.py` | Private notifications: per-citizen inbox, popups after the next interaction, warnings and one-time tips |
| `extras.py` | Planning and convenience: live countdowns, queue max, recent actions and `!again`, goals (and the planner the shopping list shares; progress since the goal was set, its one ready note, and completion where the craft is recorded), plans and routines, item uses, welcome-back and reminders, auto-sell, undo, eat until full, `/find` and the remembered Workbench place |
| `stream_overlay.py` | Stream highlights feed, overlay extras (leaders, working queues, festival, join tips) and the OBS pages: Hub, the Avesta map, a low-poly SEED-style colony with the Kernel at its centre (its light model, facet helpers, forest horizon and Kernel are `LOWPOLY_JS`), ticker, alerts, stream challenge, leaders, working, join, news and the setup page |
| `autonomy.py` | Autonomous Seedlings: schedules, the background worker that lets each Seedling act through ordinary commands, how it thinks a Work turn through (the goal's next step, then turns of collecting and training, with its reason kept and quoted), moods and their success modifier, thoughts, the diary, and the map/narrator overlay data |
| `ask.py` | Find's questions: recognises how-to/where/what-for/level/meaning/why/next questions, matches their subject (typos, plurals, old names) and answers from game data with the asker's bag and levels; counts unanswered questions for the owner (`/mod action:asklog`) |
| `readable_names.py` | Level-up labels that name the other citizen and the hobby instead of ids and keys, and a startup pass that rewrites lines stored before that |
| `knowledge.py` | Find's answers beyond items: society stats, Contribution, needs, tiers, housing and the clinic from the game's rules, and a search over the handbook, commands, menu and guide panels |
| `halloween.py` | Trick-or-treat: 5 doors a day during the Halloween festival, its treats and tricks |
| `menu.py` | The /menu button tree: areas, their action and view buttons, choice lists and follow-up buttons on every reply |
| `ui.py` | Buttons, dropdowns and one-time tickets for every panel; ◀️ Back and 🏠 Menu on every screen, with each message's screen history for Back (`HISTORY`, `go_back`) |
| `presentation.py` | How every Discord card and Twitch line looks: task receipts, notices and information cards |
| `layout_v2.py` | Discord's newer message layout (Components V2): rebuilds every message as one card just before it is sent, puts a button beside each list item a screen names (`ui.with_items`), and keeps every edit in the layout its message already has |
| `notice.py` | The fan-project notice (a free, unofficial fan project by Kamex, not affiliated with Klang Games): the card footer, Help → About, `!seed about`, the first guide panel, the pinned panel and the first welcome all use it. |
| `qol.py` | Status view, favourites, follow-up queues, alert and auto-recovery preferences, recovery estimates, fetch plans, bulk selling, inventory search and fuzzy names |
| `keep_levels.py` | Keep levels: how many of an item bulk and automatic selling always leaves, and restocking back up to it through the ordinary queue, craft queue or purchase |
| `shopping_list.py` | Shopping list: up to 10 recipes in the amounts of their output wanted, planned together with the goal's planner and one shared pool (combined materials, Fetch next, Buy all missing) |
| `quiet_hours.py` | Quiet hours: a daily window in the citizen's time zone (IANA or UTC offset) when DM queue alerts are held by the Discord worker, then released as one summary DM |
| `force_merge.py` | Force merge: the preview-and-apply core of the admin character merge (shared by `GET /api/v1/admin/merge` and the owner-only /menu → Moderator → Force merge button) and that button's screens: pick the character to keep, pick the one merged into it, preview, one-time Confirm |

## Runtime boundaries

`app.main:app` remains the ASGI entry point. Importing `app.main` composes the runtime, initializes existing database tables, applies additive migrations, configures unified items, creates the queue table and registers extension routes. The queue worker starts with the application's startup lifecycle, not merely with an import.

Importing the package itself or the command catalog no longer starts the game or opens a saved world. This lets the registrar inspect command definitions independently.[^2]

HTTP and Discord adapters use the same game functions. Twitch definitions refer to those HTTP routes; the definitions are outside the runtime package because they belong to the chat integration rather than gameplay execution.

## Scope of this cleanup

The game code that used to be one 8,000-line `main.py` is now a package of ordinary modules, `app/game/`, one per topic. `app/main.py` is a facade: it imports them in the order listed in `app/game/__init__.py` (`MODULES`) and offers every name they define as `app.main.<name>`, so the feature modules (`m.<name>`), the routes and the tests are unchanged.

Rules for editing a game module:

- Import what you use from an earlier module (`from .world import world_clock`), from `..models`, or from other `app` modules (`from .. import seed_content`).
- Read a name from a **later** module through the facade: `main.<name>` (`from .. import main`). The modules import each other only in load order, so this avoids circular imports.
- Some names are changed on `app.main` while the game runs, by tests (`monkeypatch.setattr(m, 'now', ...)`) or by feature modules (`votes.install` wraps `project_contribute`; a world merge changes `DISCORD_WORLD_ID`). Code reads these through `main` too: `main.now()`, `main.project_contribute(...)`, `main.DISCORD_WORLD_ID`. They are listed below; when you add a setting tests will change, read it as `main.<name>`.
- Pass `main` (not the module itself) to feature modules that take `m`: `seed_content.stock(main, db, p)`.
- A new module goes into `MODULES` at the point where everything it imports is already loaded.

| Module | Contents |
|---|---|
| `game/base.py` | Imports, settings from the environment, the FastAPI app, small helpers and the database setup. |
| `game/rules.py` | Game rules as data: jobs, events, skills, recipes, gear, world conditions, projects, directives, story arcs, markets. |
| `game/players.py` | Names and accounts, titles, collections, the weekly story, market demand, ducks, gear wear, the tutorial, society/world/player lookups, skills and bonuses. |
| `game/life.py` | Needs and life state, quality gear, success modifiers and progress notes. |
| `game/world.py` | Society Directive, event aftermath, relationships, the world clock and weather, statuses, society projects, goals, shortages, encounters, housing and society tiers. |
| `game/cooldowns_materials.py` | Cooldowns, action names and routes, materials and the bag, determination, Production Orders, daily contracts. |
| `game/colony_events.py` | Live events (start, progress, finish, fail, automatic events) and work_counts: what everyday work does for New Eridian. |
| `game/accounts.py` | Rare outcomes, merging duplicate accounts, achievements and configuration warnings. |
| `game/routes_player.py` | Routes: health, start, profile, skills, cooldowns, bonuses, guide, inventory, job, contracts, achievements, home and business. |
| `game/routes_crafting.py` | Routes and helpers for crafting: recipes, /make and equipment crafting. |
| `game/routes_life_social.py` | Routes: life status, display style, hi, hangout, relationships, relax, walk, games, hobby, tutorial, story and titles. |
| `game/routes_market.py` | Routes: market board, selling, workshops, Seed Industries, duo work, ducks, gear and using items. |
| `game/routes_world.py` | Routes: world status, rumors, collection, traits, districts, shifts, goals, projects, bulletin, meals, mentoring, journal, account links, society, events and the leaderboard. |
| `game/overlay_state.py` | The stream overlay data (/api/v1/overlay). |
| `game/overlay_page.py` | The stream overlay page (/overlay): one large HTML/JS template. |
| `game/routes_obs_admin.py` | Routes: OBS setup and panels, tick, wallet, progress, Rocky, Siro and admin tools. |
| `game/action.py` | The work action route (/api/v1/action/{action}) used by /work, training and chat commands. |
| `game/handbook.py` | The in-game handbook (SEED_HELP_TOPICS), Twitch help pages and the moderator log. |
| `game/discord_embeds.py` | Discord command lists and the classic embed builders. |
| `game/discord_commands.py` | Discord command schema, legacy routes and copy, JSON messages, autocomplete and option checks. |
| `game/training_and_items.py` | Training tasks, food and item menus, and the gather/catalog route. |
| `game/discord_interactions.py` | Discord command dispatch (_discord_call_internal) and the interactions webhook. |
| `game/routines_queue.py` | Routes: settlement, routines, the task queue and mining. |
| `game/wiring.py` | Installs the feature modules (ask, inbox, extras, overlay, Seedlings, onboarding, ...) into this module. |
| `game/routes_extra.py` | Routes: status, settings, favorites, fetch, sell-all, recover, trick-or-treat, find, again, craft max, targets, routines, uses, autosell, keep levels, shopping, Seedlings; then fun systems and seasons. |

The split was made mechanically from the single file and checked against it: the same names with the same values, the same routes in the same order. Names read through `main` because they change at runtime: `now`, `engine`, `ADMIN_KEY`, `MOD_KEY`, `DISCORD_WORLD_ID`, `DISCORD_GAME_CHANNEL_ID`, `DISCORD_PUBLIC_KEY`, `DISCORD_OWNER_USER_IDS`, `RUNTIME_WARNINGS`, `OVERLAY_CACHE_SECONDS`, `AUTO_EVENTS_ENABLED`, `AUTO_EVENT_ACTIONS`, `MERGED_TRAINING`, `current_project`, `project_contribute`, `merge_accounts`, `world_rule_bundle`, `success_chance`, `seed_industries`, `life_modifiers`, `gain_skill`, `determination_bonus`, `demand_day`, `_discord_call_internal`, `_discord_json_message`.

## Dependencies on app.main

Most systems in `app/` receive app.main as `m` and read whatever they need from it (`m.society(...)`, `m.SKILL_LABELS`). That works, but it hides what a system really depends on. The goal is for each system to depend explicitly on the few things it needs. This is being done gradually, one system per change; `menu`, `extras`, `autonomy` and `ui` come last.

- **The record.** `tests/contracts/main_dependencies.json` lists, per file, every name it reads from app.main (`m.<name>` in `app/`, `main.<name>` in `app/game/`). `tests/test_main_dependencies.py` fails when the code and the record differ, in either direction, so a new dependency is always deliberate and a removed one shrinks the record. `python -m scripts.main_dependencies` shows the map; `--write` updates the record.
- **Converting a system.** Import each name from the module that defines it: models from `app/models.py`, sessions from `app/db.py`, game names from `app/game/<module>.py` (the table above says which), other systems directly. The game loads most systems while it starts up, so imports from `app.game` go inside the functions that use them; a top-level one would make importing that system first loop back into the half-loaded game. Then drop the `m` parameter from its functions and update the callers. Add the system to `EXPLICIT` in the test, which also checks it still imports on its own.
- **Values that change at runtime.** Tests swap the clock and some settings on app.main, a world merge changes the main world, and `votes.install` wraps `project_contribute`; a direct import would keep the old value. Converted systems read these through `app/runtime.py` (`runtime.now()`), which looks them up on app.main at call time. Add an accessor there when a converted system needs another one.
- **`install(m)`** stays the one wiring hook every system has, even when it no longer needs `m`.

Converted so far: `halloween`, `readable_names`.

[^1]: Canonical implementations: [`app/`](../app/). The removed loader was `app/_compat.py`.
[^2]: Registrar: [`scripts/register_discord_commands.py`](../scripts/register_discord_commands.py). Import isolation and the container file layout are covered by `tests/test_repository.py`.
