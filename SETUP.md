# Colony simulation update 7.0.0

See `REFACTOR_DEPLOYMENT.md` for this update. Upload the complete `app` folder; `main.py` alone is no longer sufficient. Existing deployment settings and commands below remain supported.


# New Eridian — Complete Custom API Setup

This project is the persistent backend for the Twitch/StreamElements SEED-style game.

## What is now saved per viewer
- Twitch user ID + display name
- Chosen job
- Seed Coin (SC)
- Society Contribution + citizen rank
- Farming / Mining / Industry / Research / Delivery / Exploration XP
- Skill levels derived from XP
- Crops / Ore / Rare Ore / Components / Cargo inventory
- Total actions and successes

## What is saved for New Eridian
- Food
- Materials
- Development
- Knowledge
- Treasury
- Reputation
- Population
- Avesta day
- Siro incident
- Food crisis
- Mining boom
- Delivery surge
- Market boom

## Actual gameplay dependencies
- `!craft` requires Ore and consumes it.
- `!build` requires a Component and consumes it.
- `!cargo` prepares Cargo.
- `!delivery` requires Cargo and consumes it only on success.
- `!market` sells the viewer's most valuable available item.
- Jobs give +1 bonus SC on matching work.
- Skill levels slightly improve success chances.
- `!rare` gets a better find chance as Mining level rises.
- World events change rewards instead of being flavor-only.

## Why `$(msgid)` is included
StreamElements makes a GET request for `$(customapi)`. The backend stores the Twitch message ID for reward-producing actions. If the same request is retried, the API returns the original reply instead of paying the reward twice.

## Deploy

You need a public HTTPS URL because StreamElements calls the API from its proxy.

### Recommended: Railway + PostgreSQL
1. Create a Railway project from this folder/repository.
2. Add a PostgreSQL database service.
3. Set `DATABASE_URL` on the API service to the PostgreSQL connection URL.
   - If Railway gives a URL beginning `postgresql://`, change it to `postgresql+psycopg://`.
4. Set `ADMIN_KEY` to a long random string (30+ characters).
5. Set `GAME_NAME=New Eridian`.
6. Deploy the API.
7. Open `https://YOUR-DOMAIN/health`. It should return `{"ok":true,...}`.

You may also deploy the Dockerfile anywhere that supports Python + a persistent PostgreSQL database.

### Local test
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows, or cp .env.example .env
# load the env variables, then:
uvicorn app.main:app --reload
```

The default local database is SQLite. Production should use PostgreSQL or another persistent storage setup.

## Connect StreamElements

Open `streamelements_commands.csv`.

Replace:
- `https://YOUR-API-DOMAIN` with your deployed HTTPS address.
- `YOUR_ADMIN_KEY` with the exact ADMIN_KEY from the server.

Then create/edit the custom commands in StreamElements Dashboard → Chatbot → Custom Commands.

Example `!harvest` response:
```text
$(customapi https://YOUR-DOMAIN/api/v1/action/harvest?channel=$(channel.provider_id)&uid=$(sender.twitchid)&name=$(queryescape $(sender))&msg=$(msgid))
```

Official StreamElements behavior relevant to this project:
- `$(customapi)` uses GET only.
- It has a 15-second timeout.
- It displays only the first 400 bytes of the response.
- It cannot send custom headers.
- `$(sender.twitchid)` provides a stable Twitch user ID.
- `$(queryescape)` safely encodes dynamic query parameters.

The backend intentionally returns short plain-text responses below that limit.

## First live test
Run these from Twitch:
1. `!start`
2. `!job cultivator`
3. `!harvest`
4. `!me`
5. `!inventory`
6. `!mine`
7. `!craft`
8. `!build`
9. `!status`
10. `!progress`

Then use a second Twitch account and confirm `!me` shows a different character.

## Moderator event test
1. `!sirostart`
2. `!event`
3. `!research`
4. `!siroend`
5. `!event`

## Security note
StreamElements custom API commands cannot send private headers. The moderator event commands therefore include `ADMIN_KEY` in the URL. Treat it as a low-privilege game-control secret only—never reuse a password, API token, or account credential there. Keep those commands Moderator-only in StreamElements.

Viewer gameplay endpoints do not require a secret because viewers are expected to call them through chat, and all state-changing actions are rate-limited by StreamElements cooldowns plus message-ID deduplication.

## Backups
For PostgreSQL, use your host/database provider's automated backups. The game data is entirely in the database; the application container itself is disposable.
