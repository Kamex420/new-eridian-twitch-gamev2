"""The owner's own emoji (Discord application emojis) in place of a few unicode ones on Discord cards.

Just before a message in Discord's newer layout leaves (layout_v2), `apply` swaps:

* the ✅ of a finished-task heading ('### ✅ Crafted Iron Nails') for the next of two emoji,
  and the ❌ of a failed-task heading ('### ❌ Mining failed') for the next of two others,
  taking turns so neighbouring receipts look different;
* every 🦆 and 🪨 in the text, and on buttons and menu choices, for the duck and Rocky emoji.

Which emoji is set in PICKS. The names must match the Emojis page of the Discord Developer Portal
(the application's own emoji); case does not matter. An emoji that is not found there is simply not
used: the unicode one stays.

The ✅, ❌, 🔒 and 🔑 marks that start list items and legends are never touched: layout_v2 reads them
to colour cards and lay lists out, and the Twitch chat gets the same game text, where a custom emoji
would show as raw code. Labels never change either (Discord shows custom emoji only on a button's or
choice's emoji slot, not inside its label).

Discord's emoji list is fetched with the bot token and cached for ten minutes. A send never waits for
it: when the cache is missing or old, one background thread refreshes it and the message uses what is
cached right now (nothing yet on the very first message after a restart; the startup hook warms it up).
A failed refresh keeps the old list and logs one warning. With no bot token or application id
configured (DISCORD_BOT_TOKEN, DISCORD_APPLICATION_ID; as in tests) nothing is fetched and nothing changes.
"""
import copy
import logging
import os
import re
import threading
import time
import requests

log = logging.getLogger(__name__)

# Edit this to change the emoji. Names must match the emoji names on the Discord Developer Portal's Emojis page.
# 'done' and 'failed' are task-done and task-failed headings (they alternate); a unicode emoji maps to its stand-in.
PICKS = {
    'done': ['seemsgoodmelisa', 'JohnShades'],
    'failed': ['andyevillaugh', 'JJhydrate'],
    '🦆': ['duck'],
    '🪨': ['Rocky'],
}

TTL = 600           # seconds a fetched list is used before the next background refresh
RETRY = 60          # seconds before trying again after a failed refresh
TIMEOUT = 8
URL = 'https://discord.com/api/v10/applications/{app}/emojis'
TEXT = 10           # a text display (layout_v2.TEXT)
BUTTON = 2
HEADING = re.compile(r'^(### )(✅|❌)(?= )')
HEADINGS = {'✅': 'done', '❌': 'failed'}
SWAPPED = ('🦆', '🪨')

_LOCK = threading.Lock()
_table = {}                 # name.lower() -> (name, id, animated)
_next_try = 0.0             # time.monotonic() before which no refresh starts
_running = False            # True while the one background refresh is in flight
_turns = {}                 # 'done' / 'failed' -> how many headings have taken a turn


# ---------------------------------------------------------------- the emoji list

def _credentials():
    """(application id, bot token), read now so they can change after import; ('', '') when either is missing."""
    app, token = os.getenv('DISCORD_APPLICATION_ID', '').strip(), os.getenv('DISCORD_BOT_TOKEN', '').strip()
    return (app, token) if app and token else ('', '')


def refresh():
    """Fetch the application's emoji now (blocking). Keeps the old list and logs a warning when it fails."""
    global _table, _next_try
    app, token = _credentials()
    if not app:
        return False
    try:
        response = requests.get(URL.format(app=app), headers={'Authorization': 'Bot ' + token}, timeout=TIMEOUT)
        if response.status_code != 200:
            raise ValueError(f'HTTP {response.status_code}')
        items = response.json().get('items')
        if not isinstance(items, list):
            raise ValueError('no emoji list in the answer')
        found = {}
        for item in items:
            name, ident = str((item or {}).get('name') or ''), str((item or {}).get('id') or '')
            if name and ident.isdigit():
                found[name.lower()] = (name, ident, bool(item.get('animated')))
    except Exception as exc:
        log.warning('Custom emoji list not refreshed (%s); keeping the last one', exc if isinstance(exc, ValueError) else type(exc).__name__)
        _next_try = time.monotonic() + RETRY
        return False
    _table, _next_try = found, time.monotonic() + TTL
    return True


def _background():
    global _running
    try:
        refresh()
    finally:
        with _LOCK:
            _running = False


def warm_up():
    """Start the one background refresh when the list is missing or old. Never waits, never raises."""
    global _running
    if time.monotonic() < _next_try or not _credentials()[0]:
        return
    with _LOCK:
        if _running or time.monotonic() < _next_try:
            return
        _running = True
    try:
        threading.Thread(target=_background, name='custom-emoji', daemon=True).start()
    except Exception:
        with _LOCK:
            _running = False
        log.warning('Custom emoji list could not be refreshed in the background')


def set_table(names):
    """Use this list (name -> id, or name -> (id, animated)) as fresh; tests and tools use it instead of Discord."""
    global _table, _next_try
    _table = {name.lower(): (name, *(v if isinstance(v, tuple) else (v, False))) for name, v in names.items()}
    _next_try = time.monotonic() + TTL


def reset():
    """Forget the list, any refresh in flight and every turn taken, as at a restart."""
    global _table, _next_try, _running
    _table, _next_try, _running = {}, 0.0, False
    _turns.clear()


def reset_turns():
    """Start the done and failed headings' alternation over."""
    _turns.clear()


def install(m):
    from .game.base import app

    async def start():
        warm_up()
    app.add_event_handler('startup', start)


# ---------------------------------------------------------------- swapping

def _tag(name, table):
    """'<:name:id>' ('<a:name:id>' when animated) for a name found in the list, else None."""
    found = table.get(str(name).lower())
    return None if not found else f'<{"a" if found[2] else ""}:{found[0]}:{found[1]}>'


def _pick(kind, table):
    """The next emoji for a heading: round-robin over the configured names that exist; None when none do."""
    names = [n for n in PICKS.get(kind, ()) if str(n).lower() in table]
    if not names:
        return None
    with _LOCK:
        turn = _turns[kind] = _turns.get(kind, -1) + 1
    return _tag(names[turn % len(names)], table)


def _text(content, table):
    lines = content.split('\n')
    for i, line in enumerate(lines):
        match = HEADING.match(line)
        if match:
            pick = _pick(HEADINGS[match[2]], table)
            if pick:
                lines[i] = match[1] + pick + line[match.end():]
    content = '\n'.join(lines)
    for mark in SWAPPED:
        tag = mark in content and next(filter(None, (_tag(n, table) for n in PICKS.get(mark, ()))), None)
        if tag:
            content = content.replace(mark, tag)
    return content


def _emoji(holder, table):
    """A button's or choice's `emoji` slot: a bare 🦆 or 🪨 becomes the custom emoji's id."""
    emoji = holder.get('emoji')
    if not isinstance(emoji, dict) or emoji.get('id') or emoji.get('name') not in SWAPPED:
        return
    for name in PICKS.get(emoji['name'], ()):
        found = table.get(str(name).lower())
        if found:
            holder['emoji'] = {'id': found[1], 'name': found[0], 'animated': found[2]}
            return


def _walk(node, table):
    if not isinstance(node, dict):
        return
    if node.get('type') == TEXT and isinstance(node.get('content'), str):
        node['content'] = _text(node['content'], table)
    if node.get('type') == BUTTON:
        _emoji(node, table)
    for option in node.get('options') or []:
        if isinstance(option, dict):
            _emoji(option, table)
    _walk(node.get('accessory'), table)
    for child in node.get('components') or []:
        _walk(child, table)


def apply(payload):
    """A copy of a newer-layout message with the custom emoji in; anything else comes back as it is.

    The message passed in is never changed. Without a fetched emoji list the copy is the same message.
    """
    from . import layout_v2
    if not isinstance(payload, dict) or not layout_v2.is_v2(payload):
        return payload
    warm_up()
    table = _table
    out = copy.deepcopy(payload)
    if table:
        for node in out.get('components') or []:
            _walk(node, table)
    return out
