"""Builds ALL_COMMANDS.txt: every StreamElements command the game needs, in paste order.

Run from the repository root:  python integrations/twitch/build_all_commands.py
Every command that acts as a player carries k=YOUR_API_KEY (the TWITCH_API_KEY set on Railway);
moderator commands carry key=YOUR_ADMIN_KEY and come last.
"""
from pathlib import Path

DOMAIN = 'https://new-eridian-twitch-game-production.up.railway.app'
PLAYER = 'channel=$(channel.provider_id)&uid=$(sender.twitchid)&name=$(queryescape $(sender))&k=YOUR_API_KEY'
REST = '${1:}'
ARG = lambda name: f'&{name}=$(queryescape {REST})'
MOD = 'channel=$(channel.provider_id)&level=$(sender.level)&key=YOUR_ADMIN_KEY'


def api(path, extra='', who=PLAYER):
    return f'$(customapi {DOMAIN}/api/v1/{path}?{who}{extra})'


def action(name):
    return api(f'action/{name}', '&msg=$(msgid)')


# (command, response, level, global cooldown, user cooldown)
SEED = ('🌱 NEW ERIDIAN · play from chat: !start !gather !mine !farm !eat !relax !status !me !seedling !vote !challenge · '
        'Full game (crafting, queues, trading): our Discord')
SECTIONS = [
    ('GETTING STARTED', [
        ('!seed', SEED, 100, 15, 30),
        ('!start', api('start'), 100, 0, 10),
        ('!link', api('link/create'), 100, 0, 30),
        ('!status', api('status'), 100, 0, 5),
        ('!me', api('profile'), 100, 0, 5),
        ('!skills', api('skills'), 100, 0, 5),
        ('!wallet', api('wallet'), 100, 0, 5),
        ('!job', api('job', ARG('job')), 100, 0, 5),
        ('!inventory', api('inventory', ARG('text')), 100, 0, 5),
        ('!inv', api('inventory', ARG('text')), 100, 0, 5),
        ('!find', api('find', ARG('query')), 100, 0, 5),
    ]),
    ('GATHERING, MINING AND WORK', [
        ('!gather', api('seed-supplies', '&mode=gather&item=$(queryescape ${1:})'), 100, 0, 3),
        ('!gatherpage', api('seed-supplies', '&mode=gather&page=$(1)'), 100, 0, 3),
        ('!mine', api('mining', '&action=mine&count=1&ore=$(queryescape ${1:})'), 100, 0, 3),
        ('!mineinfo', api('mining', '&ore=$(queryescape ${1:})'), 100, 0, 5),
        *[(f'!{a}', action(a), 100, 0, 3) for a in ('farm', 'harvest', 'forage', 'water', 'scan', 'research', 'rare', 'scavenge',
                                                      'craft', 'machine', 'build', 'repair', 'project', 'work', 'cargo', 'delivery',
                                                      'spaceport', 'explore', 'survey', 'market')],
        ('!training', api('training', ARG('text')), 100, 0, 5),
    ]),
    ('NEEDS AND LIFE', [
        ('!life', api('life'), 100, 0, 5),
        ('!eat', action('eat'), 100, 0, 3),
        ('!sleep', action('sleep'), 100, 0, 3),
        ('!relax', api('relax'), 100, 0, 3),
        ('!games', api('games'), 100, 0, 3),
        ('!walk', api('walk'), 100, 0, 3),
        ('!hobby', api('hobby', ARG('hobby')), 100, 0, 3),
        ('!hi', api('hi', ARG('target')), 100, 0, 5),
        ('!hangout', api('hangout', ARG('target')), 100, 0, 5),
        ('!meal', api('meal'), 100, 0, 5),
        ('!recover', api('recover'), 100, 0, 5),
        ('!eatfull', api('eatfull'), 100, 0, 5),
        ('!cooldowns', api('cooldowns'), 100, 0, 5),
        ('!bonus', api('bonuses'), 100, 0, 5),
    ]),
    ('YOUR SEEDLING', [
        ('!seedling', api('seedling'), 100, 0, 5),
        ('!diary', api('diary'), 100, 0, 5),
    ]),
    ('SOCIETY, EVENTS AND COMMUNITY', [
        ('!society', api('society', who='channel=$(channel.provider_id)'), 100, 5, 15),
        ('!progress', api('progress', who='channel=$(channel.provider_id)'), 100, 5, 15),
        ('!event', api('event', who='channel=$(channel.provider_id)'), 100, 5, 15),
        ('!eventhistory', api('eventhistory', who='channel=$(channel.provider_id)'), 100, 5, 15),
        ('!leaderboard', api('leaderboard'), 100, 5, 15),
        ('!contracts', api('contracts'), 100, 0, 5),
        ('!achievements', api('achievements'), 100, 0, 5),
        ('!siro', api('siro', who='channel=$(channel.provider_id)'), 100, 8, 60),
        ('!rocky', api('rocky'), 100, 8, 60),
        ('!vote', api('vote', ARG('choice')), 100, 0, 5),
        ('!challenge', api('challenge'), 100, 3, 10),
        ('!season', api('seasons', ARG('section')), 100, 0, 5),
        ('!trophies', api('trophies'), 100, 0, 10),
        ('!recap', api('recap', '&provider=twitch', who='channel=$(channel.provider_id)'), 100, 30, 60),
    ]),
]
# Part of the full game on Discord: on Twitch these answer with where to find it and the invite.
DISCORD_ONLY = [('!make', 'make', 'recipe'), ('!craftmax', 'craftmax', 'recipe'), ('!recipes', 'recipes', ''), ('!queue', 'queue', ''),
                ('!catalog', 'seed-supplies', 'item'), ('!workshop', 'workshop', ''), ('!fav', 'favorite', 'recipe'), ('!target', 'target', 'recipe'),
                ('!routines', 'routines', ''), ('!again', 'again', ''), ('!seedindustries', 'seedindustries', ''), ('!sellall', 'sellall', 'item'),
                ('!home', 'home', ''), ('!homeupgrade', 'home/upgrade', ''), ('!business', 'business', ''), ('!businessstart', 'business/start', ''),
                ('!settings', 'settings', 'text'), ('!schedule', 'schedule', 'preset'), ('!autonomy', 'autonomy', 'state'),
                ('!specialize', 'specialize', 'path'), ('!hat', 'hat', 'hat'), ('!badge', 'badge', 'badge'), ('!customize', 'looks', '')]
ADMIN = [('!sirostart', 'admin/event/siro/on', ''), ('!siroend', 'admin/event/siro/off', ''), ('!foodcrisis', 'admin/event/food/on', ''),
         ('!foodclear', 'admin/event/food/off', ''), ('!miningboom', 'admin/event/mining/on', ''), ('!miningclear', 'admin/event/mining/off', ''),
         ('!deliverysurge', 'admin/event/delivery/on', ''), ('!deliveryclear', 'admin/event/delivery/off', ''),
         ('!marketboom', 'admin/event/market/on', ''), ('!marketclear', 'admin/event/market/off', ''),
         ('!eventstart', 'admin/event/$(1)/on', ''), ('!eventstop', 'admin/event/siro/off', ''),
         ('!nextday', 'admin/day/next', ''), ('!modlog', 'admin/modlog', ''),
         ('!live', 'admin/live', '&state=$(queryescape $(1))'), ('!chstart', 'admin/challenge', '&action=start&event=$(queryescape ${1:})'),
         ('!chstop', 'admin/challenge', '&action=stop')]


def block(command, response, level, cd, usercd):
    return f'!command add {command} {response}\n!command options {command} -level {level} -cd {cd} -usercd {usercd}'


def build():
    out = ['# New Eridian: every StreamElements command the game needs, in paste order.',
           '# Paste one line at a time in Twitch chat as the broadcaster or a moderator, a couple of seconds apart.',
           '# A command that already exists answers "already exists": use "!command edit" instead of "!command add" for those.',
           '#',
           '# BEFORE PASTING: replace YOUR_API_KEY in every line with the TWITCH_API_KEY you set on Railway.',
           '# The moderator commands at the very end also need YOUR_ADMIN_KEY replaced with your ADMIN_KEY.',
           '# Never type either key in chat on its own.', '']
    for title, rows in SECTIONS:
        out += ['', f'# ==== {title} ====', '']
        out += [block(*row) + '\n' for row in rows]
    out += ['', '# ==== FULL GAME ON DISCORD (optional) ====',
            '# These do nothing on Twitch; they tell viewers where to find it on Discord, with your invite (DISCORD_INVITE_URL).', '']
    for command, path, arg in DISCORD_ONLY:
        extra = ('&mode=catalog' if path == 'seed-supplies' else '') + (ARG(arg) if arg else '')
        out.append(block(command, api(path, extra), 100, 0, 10) + '\n')
    out += ['', '# ==== MODERATOR COMMANDS: paste these last. Replace YOUR_ADMIN_KEY with your ADMIN_KEY. ====',
            '# !eventstart <siro|food|mining|delivery|market|water|machine|spaceport> · !eventstop ends whatever event is running',
            '# !live on|off|auto · !chstart [dust_storm|harvest_rush|ore_seam|lumber_drive|...] · !chstop', '']
    for command, path, extra in ADMIN:
        out.append(block(command, api(path, extra, who=MOD), 500, 5, 5) + '\n')
    return '\n'.join(out).rstrip() + '\n'


if __name__ == '__main__':
    target = Path(__file__).with_name('ALL_COMMANDS.txt')
    target.write_text(build(), encoding='utf-8')
    print('wrote', target)
