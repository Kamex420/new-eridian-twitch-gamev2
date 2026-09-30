"""Twitch plays a lite version of New Eridian; Discord has the full game.

Twitch chat keeps what makes sense in a busy chat and what the stream is about: joining, gathering and
mining (one at a time), jobs and work, eating and resting, your profile and status, your Seedling, the
society, events, colony votes, stream challenges, seasons and trophies.

The deeper game lives on Discord, so there is a reason to join the server:

  crafting and the Workbench        queues and automation            trading with Seed Industries
  homes and businesses              gear and item use                the full catalog and collections
  settings, schedules and choices   hats, badges and Seedling looks  duos, mentoring and the journal

A Discord-only command typed on Twitch does nothing and answers with where to find it on Discord and the
invite (DISCORD_INVITE_URL). Linked players keep one citizen, so what they build on Discord counts on
Twitch too. Set TWITCH_LITE=false to give Twitch the full game again.
"""
import os
from fastapi.responses import PlainTextResponse

ENABLED = os.getenv('TWITCH_LITE', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}

# path -> (what it is, where to find it on Discord)
DISCORD_ONLY = {
    '/api/v1/make': ('Crafting', '/make'), '/api/v1/craftmax': ('Crafting queues', '/queue'),
    '/api/v1/fetch': ('Fetching ingredients', '/make'), '/api/v1/favorite': ('Favourite recipes', '/make'),
    '/api/v1/target': ('Crafting goals', '/make'), '/api/v1/goal': ('Crafting goals', '/make'),
    '/api/v1/recipes': ('Recipes', '/make'), '/api/v1/workshop': ('Workshops', '/workshop'), '/api/v1/uses': ('Item uses', '/find'),
    '/api/v1/queue': ('Queues', '/queue'), '/api/v1/queue-tasks': ('Queues', '/queue'), '/api/v1/routines': ('Routines', '/queue'),
    '/api/v1/routine': ('Routines', '/queue'), '/api/v1/again': ('Repeat last action', '/menu → Recent'),
    '/api/v1/seedindustries': ('Trading', '/seedindustries'), '/api/v1/sell': ('Selling', '/seedindustries'),
    '/api/v1/sellall': ('Selling', '/seedindustries'), '/api/v1/clearout': ('Selling', '/seedindustries'),
    '/api/v1/autosell': ('Auto-selling', '/menu → Bag'), '/api/v1/undo': ('Selling', '/seedindustries'),
    '/api/v1/marketboard': ('Market prices', '/market'),
    '/api/v1/business': ('Businesses', '/business'), '/api/v1/business/start': ('Businesses', '/business'),
    '/api/v1/home': ('Homes', '/home'), '/api/v1/home/upgrade': ('Homes', '/home'),
    '/api/v1/gear': ('Gear', '/inventory'), '/api/v1/gearrepair': ('Gear', '/repair'), '/api/v1/use': ('Using items', '/use'),
    '/api/v1/collection': ('Collections', '/me'),
    '/api/v1/settings': ('Settings', '/settings'), '/api/v1/schedule': ('Seedling schedules', '/seedling'),
    '/api/v1/autonomy': ('Seedling autonomy', '/seedling'), '/api/v1/display': ('Display settings', '/me'),
    '/api/v1/titles': ('Titles', '/me'), '/api/v1/specialize': ('Specializations', '/specialize'),
    '/api/v1/district': ('Districts', '/district'), '/api/v1/shift': ('Shifts', '/shift'), '/api/v1/ducks': ('Delivery partners', '/ducks'),
    '/api/v1/hat': ('Hats', '/season'), '/api/v1/badge': ('Badges', '/trophies'), '/api/v1/looks': ('Seedling looks', '/seedling'),
    '/api/v1/duo': ('Duos', '/social'), '/api/v1/mentor': ('Mentoring', '/social'), '/api/v1/journal': ('The journal', '/me'),
}
TWITCH_HERE = '!gather !mine !work !eat !status !vote'


def invite():
    link = os.getenv('DISCORD_INVITE_URL', '').strip()
    return link.replace('https://', '').replace('http://', '') if link else 'our Discord'


def gate_text(feature, where):
    text = f'🔒 {feature} is part of the full game on Discord: join {invite()} and use {where}. On Twitch: {TWITCH_HERE}'
    while len(text.encode()) > 200:
        text = text.rsplit(' ', 1)[0]
    return text


def blocked(path, params):
    """(feature, where) when this Twitch request is Discord-only, else None."""
    if not ENABLED or str(params.get('provider') or 'twitch').lower() == 'discord':
        return None
    if path in DISCORD_ONLY:
        return DISCORD_ONLY[path]
    if path == '/api/v1/seed-supplies' and str(params.get('mode') or '').lower() in {'catalog', 'buy', 'starters'}:
        return ('The full catalog', '/catalog')
    if path == '/api/v1/mining':
        try:
            count = int(params.get('count') or 1)
        except ValueError:
            count = 1
        if count > 1:
            return ('Mining queues', '/mine')
    return None


def key_problem(path, params):
    """With TWITCH_API_KEY set, every request that acts as a player must carry it as k=… (StreamElements commands do).

    Discord never plays through these addresses (it uses the bot), so without the key nobody can act as another
    player, use provider=discord to get around the lite version, or claim link codes. Reads without a player
    (overlays, the society, the recap) stay open. Admin addresses keep their own ADMIN_KEY."""
    import secrets
    key = os.getenv('TWITCH_API_KEY', '').strip()
    if not key or not path.startswith('/api/v1/') or path.startswith('/api/v1/admin/'):
        return None
    acts = bool(params.get('uid') or params.get('discord_uid')) or str(params.get('provider') or '').lower() == 'discord'
    if not acts or secrets.compare_digest(str(params.get('k') or '').encode(), key.encode()):
        return None
    return '⛔ This command is missing the game key. A moderator needs to update it from integrations/twitch/ALL_COMMANDS.txt.'


def install(m):
    @m.app.middleware('http')
    async def lite(request, call_next):
        problem = key_problem(request.url.path, request.query_params)
        if problem:
            return PlainTextResponse(problem)     # plain 200 so StreamElements shows the message instead of an error code
        found = blocked(request.url.path, request.query_params)
        if found:
            return PlainTextResponse(gate_text(*found))
        return await call_next(request)


# ---------------------------------------------------------------- Twitch copy that points to Discord

def step_command(key, twitch):
    """First Steps on Twitch: crafting and queues are done on Discord."""
    if not ENABLED:
        return twitch
    return {'craft': f'on Discord: /make ({invite()})', 'queue': f'on Discord: /queue ({invite()})'}.get(key, twitch)


TOPICS = {
    'property': 'Crafting, workshops, homes and businesses are part of the full game on Discord: /make, /workshop, /home, /business. '
                'On Twitch you gather and mine the materials: !gather <name>, !mine <ore>.',
    'operations': '!cargo prepares Cargo; !delivery consumes it on success. !spaceport: Logistics. !explore: Frontier. !market: Commerce work. '
                  'Buying, selling, production orders and market prices are on Discord: /seedindustries and /market.',
    'character': '!status: needs, cooldowns and what to do next. !me: citizen. !skills: your skills. !life: needs. !bonuses: active boosts. '
                 '!cooldowns: timers. !contracts: daily task. !achievements: progress. !trophies and !season: long-term goals. '
                 '!job farmer, miner, technician, researcher, courier, explorer, merchant, cook, medic and more. '
                 'Specializations, titles and customizing your Seedling are on Discord.',
    'life': 'Every task costs Energy, Nutrition and Comfort; work stops when they run low. !relax: +Energy and +Comfort. !sleep: back to full '
            '(every 30 minutes). !eat: pick a food. !games: +Social. !recover: every recovery that is ready. !eatfull: eat to 80 Nutrition. '
            'Using beds, seats and clothing, and auto-recovering queues, are on Discord.',
    'other': '!seedling: your Seedling now. !diary: what it did while you were away. !vote 1-3: the colony vote. !challenge: the stream '
             'challenge. !recap: this week’s leaders. !find <word>: search. !meal: share a Pumpkin. Queues, favourites, goals, '
             'auto-selling, schedules and your Seedling’s look are on Discord.',
}


def topic(key, text):
    if not ENABLED:
        return text
    if key in TOPICS:
        return TOPICS[key] + f' Join: {invite()}'
    if key == 'production':
        return ('!gather: natural materials; !gatherpage 2: more. !mine <ore>: mine once. !farm and !harvest: Farming. !water and !scan: '
                'Processing. !repair: Engineering. !research: Research. Queues (up to 10 in a row) and crafting are on Discord: /queue, /make.')
    return text


def join_tips():
    """How-to-play tips for the stream overlays when Twitch is lite."""
    return [['!start', 'Create your citizen and join New Eridian'], ['!gather lumber', 'Collect materials'],
            ['!mine hematite', 'Mine ore'], ['!farm', 'Work a job for SC and XP'], ['!relax', '+Energy and +Comfort'],
            ['!status', 'Needs and your next step'], ['!vote 1', "Vote on the colony's next project"],
            ['!seedling', 'Your Seedling on the map'], ['!challenge', 'Join the stream challenge'],
            ['Discord', 'Crafting, queues, trading and more: ' + invite()]]
