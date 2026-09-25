# New Eridian v2

A persistent Discord and Twitch settlement game. The game is **New Eridian v2**; its in-game society is **New Eridian**.

Players gather and mine materials, manufacture items at matching workstations, improve skills, and contribute to shared settlement systems. Linked accounts share inventory and progression. A saved queue can repeat one task up to ten times, pausing when needs or requirements prevent work.

## Repository map

| Location | Responsibility |
| --- | --- |
| `app/` | Application, gameplay systems, persistence and command adapters |
| `app/data/seed_catalog.json` | Item and recipe catalog |
| `scripts/` | Discord registration utility |
| `tests/` | Gameplay, migration, queue and interface regression tests |
| `tests/fixtures/` | Historical contracts and save schema; evidence rather than runtime configuration |
| `tests/contracts/` | Current Discord option contract |
| `integrations/twitch/` | StreamElements command definitions |
| `docs/` | Architecture, behavioral references and release evidence |
| Root configuration | Python dependencies, container build, deployment descriptors and test configuration |

## Technical notes

- [Architecture](docs/architecture.md) describes ownership and runtime boundaries.
- [Persistence](docs/persistence.md) explains item conversion, account linking and queue transactions.
- [Gameplay](docs/gameplay.md) records mining, crafting and needs behavior.
- [Release notes](docs/releases.md) describe the combined feature update and repository cleanup.
- [Validation](docs/testing/validation.md) records coverage and verification limits.
- [Deployment reference](docs/reference/deployment.md) documents entry points and configuration semantics.
- [Market and workstations](docs/reference/market-and-workstations.md) records current prices and access fees.

Repository documentation describes the software; file-copy and branch replacement instructions are distributed separately.
