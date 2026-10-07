"""The few values that change on app.main while the game runs, read at call time.

Tests swap the clock (monkeypatch.setattr(m, 'now', ...)) and some settings, a world merge changes the main world,
and votes.install wraps project_contribute. A system that imported one of these directly would keep the old one, so
systems that otherwise import what they need read these here instead. Add an accessor when a converted system needs
another one; docs/architecture.md lists them all.
"""


def _main():
    from . import main
    return main


def now():
    """The game clock: app.main.now(), which tests may replace."""
    return _main().now()


# Names tests or other systems replace on app.main while the game runs; runtime.<name> reads the current one.
SWAPPABLE = frozenset({
    'now', 'engine', 'ADMIN_KEY', 'MOD_KEY', 'DISCORD_WORLD_ID', 'DISCORD_GAME_CHANNEL_ID', 'DISCORD_PUBLIC_KEY',
    'DISCORD_OWNER_USER_IDS', 'RUNTIME_WARNINGS', 'OVERLAY_CACHE_SECONDS', 'AUTO_EVENTS_ENABLED', 'AUTO_EVENT_ACTIONS',
    'MERGED_TRAINING', 'current_project', 'project_contribute', 'merge_accounts', 'world_rule_bundle', 'success_chance',
    'seed_industries', 'life_modifiers', 'gain_skill', 'determination_bonus', 'demand_day', '_discord_call_internal',
    '_discord_json_message'})


def __getattr__(name):
    if name in SWAPPABLE:
        return getattr(_main(), name)
    raise AttributeError(f'app.runtime has no {name!r}: import it from the module that defines it (docs/architecture.md)')
