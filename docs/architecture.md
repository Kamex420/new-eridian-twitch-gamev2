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
| `settlement.py`, `seedlings.py`, `occupations.py`, `events.py` | Shared simulation, citizen routines, jobs and incidents |
| `command_catalog.py`, `twitch_help.py` | Platform command definitions and help text |
| `fun_systems.py`, `seasonal.py` | Supplemental activities and calendar flavor |

## Runtime boundaries

`app.main:app` remains the ASGI entry point. Importing `app.main` composes the runtime, initializes existing database tables, applies additive migrations, configures unified items, creates the queue table and registers extension routes. The queue worker starts with the application's startup lifecycle, not merely with an import.

Importing the package itself or the command catalog no longer starts the game or opens a saved world. This lets the registrar inspect command definitions independently.[^2]

HTTP and Discord adapters use the same game functions. Twitch definitions refer to those HTTP routes; the definitions are outside the runtime package because they belong to the chat integration rather than gameplay execution.

## Scope of this cleanup

The large `main.py` remains an orchestration module. Moving individual handlers into new packages while also changing their globals would create a separate behavioral refactor. This release removes duplicated ownership and organizes the repository without silently rewriting the established game loop. That boundary is intentional, not a claim that every handler has been decomposed.

[^1]: Canonical implementations: [`app/`](../app/). The removed loader was `app/_compat.py`.
[^2]: Registrar: [`scripts/register_discord_commands.py`](../scripts/register_discord_commands.py). Import isolation and the container file layout are covered by `tests/test_repository.py`.
