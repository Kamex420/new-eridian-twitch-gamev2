# Deployment reference

| Concern | Current contract |
| --- | --- |
| ASGI object | `app.main:app` |
| Container build | Root `Dockerfile`; Python 3.12 image |
| Startup registration | `scripts.register_discord_commands` module |
| Health check | `/health` |
| Port | `PORT`, with container fallback 8000 |
| Persistence | `DATABASE_URL`; default local SQLite for development |
| Queue worker | FastAPI startup/shutdown lifecycle; no separate worker service |
| Registrar catalog | `app/command_catalog.py`; 49 command definitions |
| Twitch definitions | `integrations/twitch/ALL_COMMANDS.txt` (entered in the StreamElements dashboard) and `commands.csv` |

The Docker startup attempts command registration before starting Uvicorn. A registration failure is logged and does not prevent the HTTP service from starting. The registrar's dry-run mode emits the current catalog without modifying Discord or initializing the game database.

## Environment semantics

`DISCORD_APPLICATION_ID`, `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` identify the server command-registration target. `DISCORD_PUBLIC_KEY` verifies interactions. `DISCORD_WORLD_ID` associates Discord players with their saved world; Twitch command definitions carry the corresponding channel/world parameter. Changing that association can make existing progress appear to be missing even though its database rows remain intact.

Set `DISCORD_WORLD_ID` to the Twitch channel's numeric ID (what StreamElements sends as `$(channel.provider_id)`). If they differ, Twitch and Discord are two separate worlds and `!link` codes cannot be claimed; `/health` then shows a warning. If both worlds already have players, do not just change the setting (Discord characters would seem to disappear): merge the worlds first.

### Merging a Discord world into the Twitch world

`/api/v1/admin/world-merge?source=<old DISCORD_WORLD_ID>&target=<Twitch channel ID>&key=<ADMIN_KEY>` shows a preview and changes nothing: citizens on each side, people with a character in both worlds, and the rows that would move. Adding `&confirm=1` runs it, in one transaction under the game lock (commands wait a few seconds; run it while not streaming).

- Every citizen moves to the target world. Someone with a character in both (the same Twitch account, or a Discord account linked to a Twitch character earlier) is merged into one with the same code as `/link`.
- The source world keeps its clock, current event, project, story, votes, seasons and stream challenge; society stats and settlement stockpiles of both worlds are added together, as the overlay already showed them. Unpaid help on the target world's own project counts toward the main project.
- Today's market demand, weather and directive are re-rolled, because they are picked from the world's name.
- The game uses the target as its main world at once and remembers it across restarts (`world_aliases_v1`), so set `DISCORD_WORLD_ID` to the target on Railway at any time afterwards; `/health` reminds you until it matches.
- A second merge of the same world, or a target that already has its own seasons or stream challenges, is refused with an explanation.

`DISCORD_COMPONENTS_V2` (default `true`) sends every Discord message in Discord's newer layout (Components V2): command replies, button answers, Details pages, popups, notices, queue alerts, the activity feed, the weekly recap, the pinned game panel and the guide panels. Set it to `false` to send new messages as classic embeds again (the guide panels as their coloured text); messages already sent in the newer layout keep it when their buttons are pressed, because Discord cannot switch a message back. Changing it needs a restart, like every setting.

The game keeps the Discord channel quiet. Command replies are private to the player except moderator event announcements; set `DISCORD_PUBLIC_ACTIONS=true` to make life and work replies (`/relax`, `/eat`, `/work`…) public again. Queue alerts go by direct message unless a player chooses channel mentions in `/settings`, and closed DMs wait in the player's Notifications rather than going to the channel. `FEED_SECONDS` (default `1200`, 20 minutes) sets how often the activity feed updates; big moments (events, stream challenges, votes, tier-ups) still post at once; it edits its own message when nobody has posted since, so a calm channel gets one growing message.

`DISCORD_OWNER_USER_IDS` lists the game owner's Discord accounts. Moderator tools (events, stream challenges, live, the recap, the activity feed, the guide and game panels, the moderator log, account lookup and Force merge) are owner-only: server permissions and roles do not grant them, and `DISCORD_MOD_ROLE_IDS` is no longer read. On Twitch the same tools need StreamElements level 1500 (the broadcaster) and `MOD_KEY`. These values are environment configuration, not repository content. The game title defaults to New Eridian v2 and the society name to New Eridian.

## Keys

| Variable | Used by | Where it goes |
| --- | --- | --- |
| `TWITCH_API_KEY` | Every StreamElements command that acts as a player (`k=`) | Railway and the StreamElements dashboard |
| `MOD_KEY` | StreamElements moderator commands, for the broadcaster only (user level Broadcaster): events, next day, live, challenges, recap, modlog (`key=`) | Railway and the StreamElements dashboard |
| `ADMIN_KEY` | Admin tools only: `/api/v1/admin/duplicates`, `/api/v1/admin/merge`, the routine step | Railway only; never in StreamElements |

Enter the commands in the StreamElements dashboard (Chatbot → Chat commands → Custom commands), never by typing `!command add` in Twitch chat: chat is public and copied by chat-log sites, so a key typed there is public. If a key has been pasted in chat, set new values on Railway and update the commands. `ADMIN_KEY` still works for moderator commands added before `MOD_KEY` existed. Request logs replace `k=` and `key=` values with `***`.

The owner can also merge two characters without any key: `/menu` → Moderator → **Force merge** (visible and usable only to the Discord IDs in `DISCORD_OWNER_USER_IDS`, like every moderator tool). Choose the character to keep, then the one merged into it, check the preview and press Confirm merge. It is the same merge as `/api/v1/admin/merge` and `/link`, is irreversible, and is recorded in the moderator log as `owner <Discord ID> via /menu`.

Without `TWITCH_API_KEY` anyone can call the game API as any Twitch player; the startup log and `/health` warn about it.

## Optional settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `GAME_CHANNELS` | empty | Extra comma-separated worlds that keyless reads (society, events, overlay) may name before anyone has played there. Otherwise a world exists once a player command creates it. |
| `BLOCKED_WORDS` | empty | Comma-separated words no business name may contain (case, spaces and symbols ignored). Business names already keep only letters, numbers, spaces and `' & . -`. |
| `ACTION_LOG_DAYS` | 14 | The hourly cleanup deletes action-log rows older than this. The game reads 24 hours back. |
| `JOURNAL_DAYS` | 90 | Journal entries older than this are deleted, keeping each citizen's newest 20. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` | 20, 30, 15 | PostgreSQL connection pool. Keep size + overflow below the server's `max_connections`. |
| `OVERLAY_CACHE_SECONDS` | 5 | How long one overlay computation is shared by every OBS source. |

Use Railway's private database URL (`postgres.railway.internal`), not the public proxy (`*.proxy.rlwy.net`): a command makes about a hundred small queries, and each one is a network round trip. `/health` warns when the public proxy is in use.

`/health` lists setup warnings with `?key=<MOD_KEY or ADMIN_KEY>`; without a key it only counts them.

The complete environment reads remain in application source. This reference records the deployment-critical subset rather than inventing new defaults.[^1]

## Build and rollback boundary

Only `requirements.txt`, `app/` and `scripts/` are runtime image inputs. Test fixtures, documentation and chat definitions are excluded from the image. The source move introduces no destructive database migration; earlier item-conversion rollback limitations still apply.[^2]

[^1]: [`app/main.py`](../../app/main.py), [`app/db.py`](../../app/db.py), and [`scripts/register_discord_commands.py`](../../scripts/register_discord_commands.py).
[^2]: [Persistence and rollback semantics](../persistence.md).

## Background queues and completion messages

The ASGI lifespan starts separate work and notification workers. The service must remain running for autonomous work; a stopped or sleeping host cannot execute timers. Queue state persists through downtime and resumes without a catch-up burst. The default container command enables normal Uvicorn lifespan handling.

Discord channel notifications use the existing `DISCORD_BOT_TOKEN`. The bot requires View Channel, Send Messages and Embed Links in the originating game channel (and Send Messages in Threads if commands are used in a thread). New queues record the verified interaction channel. `DISCORD_GAME_CHANNEL_ID` is the fallback for queues whose original channel was not recorded. Only the initiating player is included in `allowed_mentions`.

Twitch notifications require `TWITCH_CLIENT_ID`, `TWITCH_BOT_USER_ID`, `TWITCH_BOT_ACCESS_TOKEN` (a user access token with `user:write:chat`), and `TWITCH_QUEUE_CHANNELS`, a JSON mapping from game-world keys to broadcaster numeric IDs. This outbound permission is separate from StreamElements custom-API requests. Missing configuration or revoked credentials are reflected in notification status; completion results remain stored.

The command registrar publishes the revised option labels during normal container startup. Schema additions create separate queue destination and notification tables; they do not rewrite player inventories.

References: [Discord message creation and allowed mentions](https://docs.discord.com/developers/resources/message), [Twitch chat delivery](https://dev.twitch.tv/docs/chat/send-receive-messages).

## Claude API features (optional)

Three features use the Claude API when `ANTHROPIC_API_KEY` is set: Find answers questions its own data can't (Discord
only, labelled as an AI answer), Seedlings get a thought and a diary paragraph in their own words once a day (Discord
only, written when the player opens Overview or Diary), and the Sunday recap opens with a short story. Without the key
each one shows exactly what it showed before. The API is billed per use through the Claude Console, separately from
any Claude plan: set a monthly spend limit there. Moderator › Unanswered questions (`/mod action:asklog`) shows under its
heading whether the features are on and today's call count.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | empty (features off) | The Claude Console API key. Read from the environment only; never logged or stored. |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | The model every feature uses. |
| `AI_FEATURES` | `find,seedling,recap` | Which features run; remove one to switch it off. |
| `AI_DAILY_LIMIT` | 300 | API calls per UTC day for the whole game. Past it, everything answers without AI until midnight UTC. |
| `AI_FIND_PER_PLAYER` | 10 | AI answers in Find per player per UTC day. |

No API call is made while the game lock is held (`app/ai.py` refuses), so a slow answer never holds up other players:
slash `/find` runs without the lock (`discord_execution.LOCK_FREE`), Seedling words are written before the `/seedling`
command takes it, and the community timer writes the recap story before it locks.

## Interaction response timing

Discord requires an initial response within three seconds. All supported slash commands return a deferred response immediately after signature and access validation, then update the original response using the request-local interaction token. The token is not persisted. Discord allows interaction-token responses for fifteen minutes.[^discord-timing]

Deferral operates only after the request reaches the running app. Startup failures, missing uploaded modules, sleeping hosts or an unreachable interaction endpoint still require deployment diagnosis. An in-flight deferred command is not durable across process termination; persistent queues already committed to the database still resume normally.

[^discord-timing]: [Discord interaction response documentation](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx).

## Runtime reliability

Plain `postgres://` and `postgresql://` URLs select `postgresql+psycopg`, matching
the installed driver. PostgreSQL connections have a 10-second connection and
lock timeout and a 30-second statement timeout. SQLite waits up to 30 seconds
for a writer. Command and queue transactions share one game-wide lock (a single
PostgreSQL advisory lock key, the same boundary SQLite's `BEGIN IMMEDIATE` gives):
votes, seasons, challenges, the market day and the overlay write the main world
whichever channel a request names. These bounds surface contention as a
retryable error rather than an indefinite wait.

An hourly cleanup deletes old action-log rows, Discord command receipts, expired
link codes and old journal entries in small batches outside the game lock.

`/health` probes the database and returns HTTP 503 for database failure or a
stopped worker. Queue views report undelivered stop alerts. The outbox still
needs the bot token and channel permissions listed above; a code update cannot
grant them. Alerts never use DMs. Text fallback supports channels that allow
messages but reject embeds. Unset/default administrative keys fail closed.

## Discord.py queue sender

`discord.py==2.6.4` is a runtime dependency. FastAPI startup launches a
`discord.ext.tasks.Loop` for queue scheduling and a separate Discord outbox
loop. The scheduler checks every two seconds and respects each queue's saved
10-second attempt deadline and longer cooldowns. It does not depend on chat
messages, an open Discord interaction, or a connected Twitch stream.

The sender authenticates `discord.Client` with `DISCORD_BOT_TOKEN`, resolves the
recorded channel through `get_channel`/`fetch_channel`, then awaits
`channel.send` with an explicit `<@user_id>` and a user-only mention whitelist.
It sends a new channel message. DMs, role pings and everyone pings are disabled.
The slash-command Interactions Endpoint stays unchanged. This client uses
asynchronous HTTP operations, without a gateway websocket or privileged intents;
a gateway "online" presence is not a delivery-readiness signal.

`/health` exposes `discord_queue_sender`: `ready`, `missing_token`,
`invalid_token`, `wrong_application`, `connection_error`, or `stopped`.
Railway logs report authentication, delivery and sanitized errors. The bot token
must belong to `DISCORD_APPLICATION_ID` when that value is configured. The bot
must be installed in the server and allowed to View Channel and Send Messages
(or Send Messages in Threads); Embed Links enables styled cards. Forbidden
embeds fall back to a text alert. Channel permissions still apply to that fallback.

A missing or rejected token leaves notices unclaimed. After authentication,
one recovery scan restores missing/failed alerts for the current stopped queue
runs from the previous 24 hours. Sent alerts and older history are not replayed.
Ongoing send failures retain bounded retries and become visible in `/queue`.

References: [discord.py task helpers](https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html),
[discord.py channel and client APIs](https://discordpy.readthedocs.io/en/stable/api.html).
