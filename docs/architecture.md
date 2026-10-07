# Architecture

The application now has one canonical Python package. Earlier releases stored implementations at the repository root and used `app/` wrappers to load them under private module names. Those wrappers and the dynamic loader have been removed. Models, functions and mutable state now have ordinary `app.*` module identities.[^1]

## Ownership

| Module | Main responsibility |
| --- | --- |
| `main.py` | ASGI application, HTTP/Discord adapters, existing gameplay orchestration and OBS rendering. Its code is split by topic into `main_parts/` (see below) |
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

The large `main.py` remains one orchestration module, but its code now lives in `app/main_parts/`, one file per topic. `main.py` runs the parts in file-name order inside its own namespace, so nothing about the module changed: every name is still `app.main.<name>`, feature modules reach it as `m.<name>`, tests monkeypatch it, and routes register in the same order. The parts are not importable modules; a part may use anything an earlier part defined. Edit the part that holds the code; add a numbered file for a new topic.

| Part | Contents |
|---|---|
| `01_base.py` | Imports, settings from the environment, the FastAPI app, small helpers and the database setup. |
| `02_rules.py` | Game rules as data: jobs, events, skills, recipes, gear, world conditions, projects, directives, story arcs, markets. |
| `03_players.py` | Names and accounts, titles, collections, the weekly story, market demand, ducks, gear wear, the tutorial, society/world/player lookups, skills and bonuses. |
| `04_life.py` | Needs and life state, quality gear, success modifiers and progress notes. |
| `05_world.py` | Society Directive, event aftermath, relationships, the world clock and weather, statuses, society projects, goals, shortages, encounters, housing and society tiers. |
| `06_cooldowns_materials.py` | Cooldowns, action names and routes, materials and the bag, determination, Production Orders, daily contracts. |
| `07_colony_events.py` | Live events (start, progress, finish, fail, automatic events) and work_counts: what everyday work does for New Eridian. |
| `08_accounts.py` | Rare outcomes, merging duplicate accounts, achievements and configuration warnings. |
| `09_routes_player.py` | Routes: health, start, profile, skills, cooldowns, bonuses, guide, inventory, job, contracts, achievements, home and business. |
| `10_routes_crafting.py` | Routes and helpers for crafting: recipes, /make and equipment crafting. |
| `11_routes_life_social.py` | Routes: life status, display style, hi, hangout, relationships, relax, walk, games, hobby, tutorial, story and titles. |
| `12_routes_market.py` | Routes: market board, selling, workshops, Seed Industries, duo work, ducks, gear and using items. |
| `13_routes_world.py` | Routes: world status, rumors, collection, traits, districts, shifts, goals, projects, bulletin, meals, mentoring, journal, account links, society, events and the leaderboard. |
| `14_overlay_state.py` | The stream overlay data (/api/v1/overlay). |
| `15_overlay_page.py` | The stream overlay page (/overlay): one large HTML/JS template. |
| `16_routes_obs_admin.py` | Routes: OBS setup and panels, tick, wallet, progress, Rocky, Siro and admin tools. |
| `17_action.py` | The work action route (/api/v1/action/{action}) used by /work, training and chat commands. |
| `18_handbook.py` | The in-game handbook (SEED_HELP_TOPICS), Twitch help pages and the moderator log. |
| `19_discord_embeds.py` | Discord command lists and the classic embed builders. |
| `20_discord_commands.py` | Discord command schema, legacy routes and copy, JSON messages, autocomplete and option checks. |
| `21_training_and_items.py` | Training tasks, food and item menus, and the gather/catalog route. |
| `22_discord_interactions.py` | Discord command dispatch (_discord_call_internal) and the interactions webhook. |
| `23_routines_queue.py` | Routes: settlement, routines, the task queue and mining. |
| `24_wiring.py` | Installs the feature modules (ask, inbox, extras, overlay, Seedlings, onboarding, ...) into this module. |
| `25_routes_extra.py` | Routes: status, settings, favorites, fetch, sell-all, recover, trick-or-treat, find, again, craft max, targets, routines, uses, autosell, keep levels, shopping, Seedlings; then fun systems and seasons. |

Moving handlers into real packages with their own globals would still be a separate behavioural refactor; the split only moves text, so the statements and their order are exactly those of the single file.

[^1]: Canonical implementations: [`app/`](../app/). The removed loader was `app/_compat.py`.
[^2]: Registrar: [`scripts/register_discord_commands.py`](../scripts/register_discord_commands.py). Import isolation and the container file layout are covered by `tests/test_repository.py`.
