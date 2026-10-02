# New Eridian v2

A persistent Discord and Twitch settlement game. The game is **New Eridian v2**; its in-game society is **New Eridian**.

Players gather and mine materials, manufacture items at matching workstations, improve skills, and contribute to shared settlement systems. Linked accounts share inventory and progression. A saved queue can repeat one task up to ten times, pausing when needs or requirements prevent work.

## Fan project notice

New Eridian v2 is a free-to-play fan project made by **Kamex**. It is unofficial: it is not made, endorsed, sponsored or approved by Klang Games, and it is not part of SEED. SEED, Avesta, New Eridian and the related names, characters, items and lore belong to Klang Games and their other owners; they appear here only in a free, non-commercial fan project, and all rights stay with them. There is nothing to buy and no real money is involved: Seed Coin (SC) and every item exist only in this game and have no real-world value. Rights holders who would like anything changed or removed can contact Kamex in the game's Discord.

In the game the notice is under Help → About (`/seed topic:About`, `!seed about` on Twitch), in the first newcomer guide panel, on the pinned game panel and in the first welcome, and every Discord card's footer reads "a fan project by Kamex". The text lives in `app/notice.py`.

## Repository map

| Location | Responsibility |
| --- | --- |
| `app/` | Application, gameplay systems, persistence and command adapters |
| `app/data/seed_catalog.json` | Item and recipe catalog |
| `scripts/` | Discord registration utility |
| `tests/` | Gameplay, migration, queue and interface regression tests |
| `tests/fixtures/` | Historical contracts and save schema; evidence rather than runtime configuration |
| `tests/contracts/` | Current Discord option contract |
| `integrations/twitch/` | StreamElements command definitions (`ALL_COMMANDS.txt`, entered in the StreamElements dashboard, never in chat) |
| `docs/` | Architecture, behavioral references and release evidence |
| Root configuration | Python dependencies, container build, deployment descriptors and test configuration |
| `.github/workflows/` | CI: the full test suite, plus the PostgreSQL check, on every push |

## Technical notes

- [Architecture](docs/architecture.md) describes ownership and runtime boundaries.
- [Persistence](docs/persistence.md) explains item conversion, account linking and queue transactions.
- [Gameplay](docs/gameplay.md) records mining, crafting and needs behavior.
- [Release notes](docs/releases.md) describe the combined feature update and repository cleanup.
- [Validation](docs/testing/validation.md) records coverage and verification limits.
- [Deployment reference](docs/reference/deployment.md) documents entry points, keys (`TWITCH_API_KEY`, `MOD_KEY`, `ADMIN_KEY`) and configuration semantics.
- [Market and workstations](docs/reference/market-and-workstations.md) records current prices and access fees.


