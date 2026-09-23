

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


def main():
    if '--dry-run' in sys.argv:
        print(json.dumps(commands, ensure_ascii=False, indent=2))
        return
    app_id = os.getenv('DISCORD_APPLICATION_ID', '').strip()
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    guild_id = os.getenv('DISCORD_GUILD_ID', '').strip()
    if not app_id or not token or not guild_id:
        raise RuntimeError('Set DISCORD_APPLICATION_ID, DISCORD_BOT_TOKEN and DISCORD_GUILD_ID on this game service.')
    eat = next(c for c in commands if c['name'] == 'eat')
    if not any(o['name'] == 'food' and o.get('autocomplete') for o in eat.get('options', [])):
        raise RuntimeError('OLD DEPLOYMENT: app/command_catalog.py lacks /eat Food. Deploy the latest GitHub commit.')
    source = Path(__file__).resolve().with_name('main.py')
    functions = {n.name for n in ast.parse(source.read_text()).body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if 'item_command_menu' not in functions:
        raise RuntimeError('OLD DEPLOYMENT: root main.py lacks the food menu. Deploy the latest GitHub commit.')
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
    for command in commands:
        if command['name'] not in saved or signature(saved[command['name']]) != signature(command):
            raise RuntimeError(f"Verification failed for /{command['name']}. No global commands were deleted.")
    print(f'CONFIRMED: all {len(commands)} server commands match the current catalog.', flush=True)
    print('CONFIRMED: server /eat has Food autocomplete.', flush=True)
    names = {c['name'] for c in commands}
    removed = 0
    for command in api('GET', base + '/commands'):
        if command['name'] in names and command.get('type', 1) == 1:
            api('DELETE', base + '/commands/' + command['id'])
            removed += 1
            print(f"DELETED: duplicate global /{command['name']}.", flush=True)
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
