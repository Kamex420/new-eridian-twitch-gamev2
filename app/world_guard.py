"""Requests that name a world nobody has started are turned away before they create rows.

Reads without a player (the society, events, the recap, the overlay) carry no key, so before this anyone could
name any channel and the game would create a society, a world and settlement rows for it, and cycling channel
names emptied the overlay cache. Now a world is created only by a player command (which carries the game key
when TWITCH_API_KEY is set); other requests must name a world that exists, the main world (DISCORD_WORLD_ID)
or one listed in GAME_CHANNELS. The overlay shows the main world for an unknown channel instead.
"""
import os
import secrets
from . import runtime
from .db import SessionLocal
from .models import Society
from sqlalchemy import select

MAX_CHANNEL = 64      # the channel_id columns are VARCHAR(64); longer names failed on Postgres with an error
NOT_STARTED = '🌱 New Eridian has not started in this channel yet. Type !start to found the colony, then try again.'
_known = set()


def listed():
    extra = {c.strip() for c in os.getenv('GAME_CHANNELS', '').split(',') if c.strip()}
    return {runtime.DISCORD_WORLD_ID} | extra


def cached(channel):
    return channel in _known or channel in listed()


def known(channel):
    """True when the world exists already (looked up once, then remembered)."""
    channel = str(channel or '')
    if not channel or len(channel) > MAX_CHANNEL:
        return False
    if cached(channel):
        return True
    with SessionLocal() as db:
        found = db.execute(select(Society.id).where(Society.channel_id == channel)).first() is not None
    if found:
        _known.add(channel)
    return found


def trusted(params):
    """The request carries the game key (so StreamElements sent it), or it acts as a player."""
    key = os.getenv('TWITCH_API_KEY', '').strip()
    if key and secrets.compare_digest(str(params.get('k') or '').encode(), key.encode()):
        return True
    return bool(params.get('uid') or params.get('discord_uid'))


def checked(path):
    return path.startswith('/api/v1/') and not path.startswith(('/api/v1/admin/', '/api/v1/overlay'))


def note_split_world(channel, params):
    """StreamElements commands name the Twitch channel's ID. When that is not DISCORD_WORLD_ID, Twitch and Discord
    are two separate games and !link codes can never be claimed, so /health says how to fix it."""
    if channel in listed() or str(params.get('provider') or 'twitch').lower() == 'discord':
        return
    key = os.getenv('TWITCH_API_KEY', '').strip()
    if key and params.get('uid') and secrets.compare_digest(str(params.get('k') or '').encode(), key.encode()):
        runtime.RUNTIME_WARNINGS.add(f'Twitch commands use channel {channel} but DISCORD_WORLD_ID is {runtime.DISCORD_WORLD_ID}: Twitch and Discord '
                               f'are separate worlds and !link codes cannot be claimed. Merge them (do not only set DISCORD_WORLD_ID={channel}: '
                               f'that hides every Discord character): open /api/v1/admin/world-merge?source={runtime.DISCORD_WORLD_ID}&target={channel}'
                               '&key=<ADMIN_KEY> to preview, then add &confirm=1.')


def quick_problem(path, params):
    """(problem, needs_lookup): a problem found without the database, or whether the channel must be looked up."""
    channel = params.get('channel')
    if channel is None or not checked(path):
        return None, False
    if len(runtime.RUNTIME_WARNINGS) < 20:
        note_split_world(channel, params)
    if len(channel) > MAX_CHANNEL:
        return 'That channel name is too long. Nothing changed.', False
    if trusted(params) or cached(channel):
        return None, False
    return None, True


def lookup_problem(params):
    return None if known(params.get('channel')) else NOT_STARTED
