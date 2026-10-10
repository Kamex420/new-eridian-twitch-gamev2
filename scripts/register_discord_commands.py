
"""Register current commands and remove matching global command duplicates safely."""
import ast
import json
import os
from pathlib import Path
import sys
import time

import requests
from app.command_catalog import commands


def signature(command):
    keys = ('name', 'type', 'required', 'autocomplete', 'choices', 'options',
            'min_value', 'max_value', 'min_length', 'max_length')
    def option(row):
        return {k: ([option(x) for x in row[k]] if k == 'options' else row[k])
                for k in keys if k in row and row[k] not in (False, None, [])}
    return (command['description'], [option(x) for x in command.get('options', [])])


class _Missing:
    def __repr__(self):
        return '<missing>'


MISSING = _Missing()


def differences(catalog, saved):
    """Every place where Discord's saved command differs from the catalog, as (path, catalog value, Discord value).

    Walks the fields signature() compares. Options are paired by name and choices by value, so one changed
    label shows up as its own path (/make › option 'category' › choices › choice 'parts' › name)."""
    found = []

    def compare(path, mine, theirs):
        if mine == theirs:
            return
        if isinstance(mine, dict) and isinstance(theirs, dict):
            for key in [*mine, *(k for k in theirs if k not in mine)]:
                compare(f'{path} › {key}', mine.get(key, MISSING), theirs.get(key, MISSING))
            return
        rows = isinstance(mine, list) and isinstance(theirs, list) and all(
            isinstance(r, dict) for r in mine + theirs)
        if rows and mine and theirs:
            key = 'value' if all('value' in r for r in mine + theirs) else 'name'
            label = 'choice' if key == 'value' else 'option'
            ids_mine, ids_theirs = [r.get(key) for r in mine], [r.get(key) for r in theirs]
            if len(set(map(repr, ids_mine))) == len(mine) and len(set(map(repr, ids_theirs))) == len(theirs):
                by_mine, by_theirs = dict(zip(ids_mine, mine)), dict(zip(ids_theirs, theirs))
                for ident in [*ids_mine, *(i for i in ids_theirs if i not in by_mine)]:
                    compare(f'{path} › {label} {ident!r}', by_mine.get(ident, MISSING), by_theirs.get(ident, MISSING))
                if [i for i in ids_mine if i in by_theirs] != [i for i in ids_theirs if i in by_mine]:
                    found.append((f'{path} › order', ids_mine, ids_theirs))
                return
        found.append((path, mine, theirs))

    mine, theirs = signature(catalog), signature(saved)
    name = '/' + catalog['name']
    compare(f'{name} › description', mine[0], theirs[0])
    compare(name, mine[1], theirs[1])
    if mine != theirs and not found:
        found.append((name, mine, theirs))
    return found


def main_functions():
    """Top-level function names of app.main, read without importing it (app.main offers those of app/game/*.py)."""
    app_dir = Path(__file__).resolve().parents[1] / 'app'
    sources = [app_dir / 'main.py', *sorted((app_dir / 'game').glob('*.py'))]
    return {n.name for source in sources for n in ast.parse(source.read_text(encoding='utf-8')).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def main():
    if '--dry-run' in sys.argv:
        print(json.dumps(commands, ensure_ascii=False, indent=2))
        return
    app_id = os.getenv('DISCORD_APPLICATION_ID', '').strip()
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    guild_id = os.getenv('DISCORD_GUILD_ID', '').strip()
    if not app_id or not token or not guild_id:
        raise RuntimeError('Set DISCORD_APPLICATION_ID, DISCORD_BOT_TOKEN and DISCORD_GUILD_ID on this game service.')
    life = next(c for c in commands if c['name'] == 'life')
    if not any(o['name'] == 'food' and o.get('autocomplete') for o in life.get('options', [])):
        raise RuntimeError('The deployed command catalog does not define /life Food autocomplete.')
    if 'item_command_menu' not in main_functions():
        raise RuntimeError('The deployed app/main.py does not implement the current food-menu contract.')
    session = requests.Session()
    session.headers.update(Authorization=f'Bot {token}')

    def api(method, path, **kwargs):
        for attempt in range(5):
            response = session.request(method, 'https://discord.com/api/v10' + path,
                                       timeout=30, **kwargs)
            if response.status_code != 429:
                break
            delay = float(response.json().get('retry_after', 1))
            if attempt == 4 or delay > 30:
                raise RuntimeError('Discord rate limit: cleanup is incomplete. Rerun registration after the limit clears.')
            time.sleep(max(0.1, delay))
        if not response.ok:
            raise RuntimeError(f'Discord {method} failed: HTTP {response.status_code}: {response.text[:1000]}')
        return response.json() if response.status_code != 204 else None

    application = api('GET', '/oauth2/applications/@me')
    if str(application['id']) != app_id:
        raise RuntimeError('Application ID and bot token belong to different applications. Nothing changed.')
    print(f"Registering {application['name']} | App {app_id} | Server {guild_id}", flush=True)
    base = f'/applications/{app_id}'
    server = f'{base}/guilds/{guild_id}/commands'
    api('PUT', server, json=commands)
    saved = {c['name']: c for c in api('GET', server) if c.get('type', 1) == 1}
    failed = []
    for command in commands:
        name = command['name']
        found = differences(command, saved[name]) if name in saved else [(f'/{name}', name, MISSING)]
        if found:
            failed.append('/' + name)
        # ascii() rather than repr(): repr() prints variation selectors (U+FE0F) and other marks as-is.
        for path, mine, theirs in found:
            print(f'MISMATCH {path}: catalog {ascii(mine)} | Discord {ascii(theirs)}', flush=True)
    if failed:
        raise RuntimeError(f"Verification failed for {', '.join(failed)}. No global commands were deleted.")
    print(f'CONFIRMED: all {len(commands)} server commands match the current catalog.', flush=True)
    print('CONFIRMED: server /life has Food autocomplete.', flush=True)
    names = {c['name'] for c in commands} | {'agriculture'}  # Retired command name.
    removed = 0
    for command in api('GET', base + '/commands'):
        if command['name'] in names and command.get('type', 1) == 1:
            api('DELETE', base + '/commands/' + command['id'])
            removed += 1
            print(f"DELETED: duplicate or retired global /{command['name']}.", flush=True)
    remaining = api('GET', base + '/commands')
    if any(c['name'] in names and c.get('type', 1) == 1 for c in remaining):
        raise RuntimeError('Global duplicates still exist. Check for another deployment registering them.')
    print(f'DONE: {len(commands)} server commands verified; {removed} global duplicates removed.', flush=True)
    print('Unrelated global commands were preserved. Managed commands are now server-only.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, requests.RequestException) as exc:
        sys.exit(str(exc))
