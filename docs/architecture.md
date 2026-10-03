# Architecture

The application now has one canonical Python package. Earlier releases stored implementations at the repository root and used `app/` wrappers to load them under private module names. Those wrappers and the dynamic loader have been removed. Models, functions and mutable state now have ordinary `app.*` module identities.[^1]

## Ownership

| Module | Main responsibility |
| --- | --- |
| `main.py` | ASGI application, HTTP/Discord adapters, existing gameplay orchestration and OBS rendering |
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

The large `main.py` remains an orchestration module. Moving individual handlers into new packages while also changing their globals would create a separate behavioral refactor. This release removes duplicated ownership and organizes the repository without silently rewriting the established game loop. That boundary is intentional, not a claim that every handler has been decomposed.

[^1]: Canonical implementations: [`app/`](../app/). The removed loader was `app/_compat.py`.
[^2]: Registrar: [`scripts/register_discord_commands.py`](../scripts/register_discord_commands.py). Import isolation and the container file layout are covered by `tests/test_repository.py`.
