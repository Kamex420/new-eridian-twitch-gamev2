"""The game behind app.main, one module per topic. app/main.py imports them in MODULES order and offers every
name they define as app.main.<name>, which is how the feature modules (m.<name>) and the tests reach them.

A module imports what it needs from earlier modules. It reads names from later modules, and the settings and
functions that tests or other modules swap on app.main while the game runs, through `main` (main.now()).
Importing any of these modules loads the whole game, in order.
"""
MODULES = (
    'base',
    'rules',
    'players',
    'life',
    'world',
    'cooldowns_materials',
    'colony_events',
    'accounts',
    'routes_player',
    'routes_crafting',
    'routes_life_social',
    'routes_market',
    'routes_world',
    'overlay_state',
    'overlay_page',
    'routes_obs_admin',
    'action',
    'handbook',
    'discord_embeds',
    'discord_commands',
    'training_and_items',
    'discord_interactions',
    'routines_queue',
    'wiring',
    'routes_extra',
)

from .. import main  # noqa: E402,F401  (load app.main first: it imports the modules above in order)
