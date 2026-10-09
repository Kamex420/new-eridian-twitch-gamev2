"""The how-to-play panels for the Discord guide channel, as coloured ANSI blocks.

Each panel is one Discord message: a ```ansi code block with a boxed green title,
a bold white introduction, cyan section headings, orange command lines with a
plain description under each, and a green flow line at the end. The command list
ends with what the colour strip on every game reply means. The colours are
ANSI escape codes, which cannot be typed in Discord and are often lost when
copied. `/mod action:Post guide panels` posts each panel as a card in Discord's
newer layout like every other game message (`card`), or as these coloured
blocks when that layout is switched off. `docs/discord-guide-panels.txt` holds
the coloured blocks for manual pasting.

The panels are for players: what to do and where to find it, not every number.
The first NEWCOMER_PANELS are for someone who has never played SEED or New Eridian:
what the game is, the words it uses, a first ten minutes and common questions.
"""
import logging
import os
import re
import textwrap
import time
import requests

ESC = '\x1b'
WIDTH = 58
TITLE, INTRO, HEADING, COMMAND, TEXT, FLOW = (ESC + '[1;32m', ESC + '[1;37m', ESC + '[1;36m', ESC + '[0;33m', ESC + '[0m', ESC + '[1;32m')


def _coming_up():
    """Festivals open now and the next one, worked out when the panels are posted."""
    from datetime import datetime, timezone
    from . import seasonal
    today = datetime.now(timezone.utc).date()
    rows = []
    for f in seasonal.holidays_active_for(today)[:2]:
        foods = ', '.join(food[0] for food in seasonal.FESTIVAL_FOODS.get(f['name'], []))
        rows.append((f"{f['emoji']} {f['name']} · open now until {f['end'].strftime('%B')} {f['end'].day}", foods + '.'))
    nxt = seasonal.next_holiday_window(today)
    foods = ', '.join(food[0] for food in seasonal.FESTIVAL_FOODS.get(nxt['name'], []))
    rows.append((f"{nxt['emoji']} {nxt['name']} · opens {nxt['start'].strftime('%B')} {nxt['start'].day}", foods + '.'))
    return rows


# What the colour strip on game replies means (the embed colours in main._discord_embed_color).
LEGEND = [('GREEN', ESC + '[1;32m', 'success and growth'), ('YELLOW', ESC + '[1;33m', 'actions and rewards'),
          ('BLUE', ESC + '[1;34m', 'information and status'), ('RED', ESC + '[1;31m', 'blockers and danger'),
          ('MAGENTA', ESC + '[1;35m', 'social, story and lore'), ('GRAY', ESC + '[0;37m', 'supporting detail')]

# (title, intro, [(heading, rows), ...], flow line[, legend]). rows is a list of (command, description),
# or a function returning one (called when the panels are posted, so dates stay current).
# The newcomer panels come first: someone who has never played SEED or New Eridian reads them top to bottom.
NEWCOMER_PANELS = [
    ('New here? Read this first',
     'Never played SEED or New Eridian? Start with these four panels. The game is free, and you play it by typing in Twitch chat or here on Discord.',
     [('WHAT IS THIS GAME?', [
         ('A relaxed colony life game', 'You are a settler in New Eridian, a young town on the planet Avesta. Gather materials, learn skills, craft things, sell them and help the town grow.'),
         ('Play at your own pace', 'A few minutes a day is plenty. There is no game over: your citizen, items and skills are kept.')]),
      ('IT KEEPS GOING WITHOUT YOU', [
          ('Your Seedling', 'Your citizen is a little person on the stream map. When you stop playing it carries on: it works, eats, sleeps, makes friends and writes you a diary.')]),
      ('WHAT IS SEED?', [
          ('SEED by Klang Games', "A life-sim MMO about humanity's new home on Avesta. New Eridian borrows its world and its items, but has its own rules. You do not need to know SEED."),
          ('A free fan project by Kamex', 'Unofficial: not made, endorsed or sponsored by Klang Games. Nothing to buy, ever.')]),
      ('WHERE YOU PLAY', [
          ('Twitch chat · the lite version', 'Type !start while you watch the stream.'),
          ('Discord · the full game', 'Type /start here. Crafting, queues and trading are only on Discord.')])],
     'READ ON → /start → PLAY AT YOUR OWN PACE'),
    ('Words you will see',
     'A short dictionary. All of these come up in your first hour.',
     [('THE WORLD', [
         ('Avesta', 'The planet. Humanity moved here from Earth.'),
         ('New Eridian', 'Our town. Everyone who plays builds it together.'),
         ('Seedling', 'Your citizen. It has moods and thoughts, and it keeps living while you are away.'),
         ('Avesta day', 'Game time: Morning, Day, Evening and Night. Each day brings a new colony vote.')]),
      ('YOU', [
          ('Needs', 'Energy, Nutrition, Comfort and Social. Tasks use them up; eating and resting fill them again.'),
          ('Skills', 'Every task gives practice in a skill. Higher levels unlock more.'),
          ('Job', 'Your profession. Work that matches it gets a bonus.')]),
      ('MONEY & MAKING', [
          ('SC · Seed Coin', 'Your money. Earned by selling, filling orders and helping out.'),
          ('Seed Industries', 'The company that sells supplies and buys what you make.'),
          ('Workbench', 'Where you craft. Some recipes need a station or machine.'),
          ('Queue', 'One task repeated up to 10 times while you do something else.'),
          ('Contribution', 'Credit for helping the town grow.')])],
     'LEARN THE WORDS → THE REST IS EASY'),
    ('Your first 10 minutes',
     'Follow these in order. Steps 2–7 each pay SC, and finishing them all gives a bonus and the Settled In title.',
     [('ON DISCORD', [
         ('1 · /start', 'Make your citizen. You get 2 Lumber and 4 Berries.'),
         ('2 · /job', 'Pick a profession. Any is fine; you can change it later.'),
         ('3 · /gather → Lumber', 'Your first material.'),
         ('4 · /make → Ready to craft → Campfire', 'Your first craft. The welcome kit has the Lumber it needs.'),
         ('5 · /life → Eat → Berries', 'Food keeps your Nutrition up.'),
         ('6 · /gather → Lumber → Queue 5', 'Five gathers in a row while you read on.'),
         ('7 · /seedling', 'Meet the one who plays while you are away.')]),
      ('ON TWITCH', [
          ('!start  !job farmer  !gather lumber', 'Make your citizen, pick a job and gather in chat.'),
          ('!eat  !seedling', 'Eat, then meet your Seedling. Crafting and queues are on Discord.')]),
      ('WHAT NEXT?', [
          ('/guide', 'Always tells you the best next step, and why.')])],
     'START → GATHER → CRAFT → EAT → QUEUE → MEET YOUR SEEDLING'),
    ('Questions new players ask',
     'Short answers to what new players ask most.',
     [('ABOUT PLAYING', [
         ('Do I have to play every day?', 'No. Nothing bad happens while you are away. Needs slowly refill on their own, and your Seedling keeps living for 3 days after you last played.'),
         ('Can I mess something up?', 'Hard to. Menus and previews never spend anything, and a sale can be undone for 60 seconds.'),
         ('Does it cost money?', 'No. Everything is earned by playing.'),
         ('Do I need to watch the stream?', 'No. Discord works any time. Stream challenges only run while live, and they pay extra.'),
         ('Can I play with friends?', 'Yes. Everyone lives in the same town, votes together and works on the same projects and events.')]),
      ('STUCK?', [
          ('/guide  /menu  /find', 'Your next step, every button, or search and ask anything.'),
          ('Ask in chat', 'Other players and the mods can help.')])],
     'NO RUSH · NO WRONG WAY · HAVE FUN'),
]

PANELS = NEWCOMER_PANELS + [
    ('Jump in',
     'New Eridian is a Twitch + Discord life game on the planet Avesta. Build your citizen, learn skills, craft useful things and help the settlement grow.',
     [('JUMP IN', [
         ('/start', 'Create your citizen. You get a welcome kit and your Seedling moves into town.'),
         ('/menu', 'Every part of the game as buttons. Pick an area, then what to do.'),
         ('🎛️ Pinned game panel', 'Press any button on it to open your own private menu.'),
         ('/status', 'Your needs, queue, cooldowns and next step in one view.'),
         ('/guide', 'The best thing to do next, and why.')]),
      ('FIRST STEPS · each one pays SC', [
          ('Gather · craft · eat · job · queue · Seedling', 'Do them in any order. Finish all six for bonus SC and the Settled In title.')]),
      ('PLAYING ON TWITCH TOO?', [
          ('/link', 'Type !link in Twitch chat, then enter the code here. Both accounts become one citizen.'),
          ('Twitch is the lite version', 'Crafting, queues, trading, homes and customizing your Seedling are here on Discord.')])],
     'RECOVER → WORK → GATHER → MAKE → IMPROVE → CONTRIBUTE'),
    ('Needs & recovery',
     'Every task uses Energy, Nutrition and Comfort. Low needs stop work, so keep them topped up.',
     [('RECOVER', [
         ('/life → Relax', '+Energy and +Comfort. Ready again after 30 seconds.'),
         ('/life → Sleep', 'Energy and Comfort back to full. Once every 30 minutes.'),
         ('/life → Eat', 'Pick a food. Cooked food fills you up more than raw.'),
         ('/life → Games', '+Social, no partner needed.'),
         ('/life → Recover', 'Every recovery that is ready, in one press.')]),
      ('HANDS-FREE', [
          ('/use', 'Beds, seats, baths and clothing restore Comfort and are kept.'),
          ('/settings → Autorecover: On', 'Paused queues recover by themselves, then carry on.')])],
     'EAT → REST → STAY COMFORTABLE → KEEP WORKING'),
    ('Your Seedling',
     'Your Seedling is you on the stream map. It has moods and thoughts, and it keeps living while you are away.',
     [('LOOK AFTER IT', [
         ('/seedling', 'Its mood, what it is thinking, where it is and what it is doing.'),
         ('/seedling → Diary', 'What it did while you were away, with everything it gathered.'),
         ('/seedling → Schedule', 'Balanced, workaholic, night owl, socialite or homebody.'),
         ('/customize', 'Skin tone, hair, outfit, accessory, attitude and a catchphrase. Your look shows on the stream map.')]),
      ('GOOD TO KNOW', [
          ('Autonomy', 'After 10 minutes without a command it works, eats, sleeps and meets friends on its own. At work it thinks it through: your goal first, then it takes turns collecting and training its skills, and its diary says why. It never crafts recipes, buys or sells.'),
          ('Mood', 'A happy Seedling works a little better; a miserable one a little worse.'),
          ('Autonomy off', '/seedling → Lives on its own: Off makes it wait for you.')])],
     'PLAY → WALK AWAY → READ THE DIARY'),
    ('Gathering & work',
     'Raw materials come from gathering and mining. Every success gives items and practice in its skill.',
     [('COLLECT', [
         ('/gather', 'Lumber, Berries, Herbs, Stone and every other natural material.'),
         ('/mine', 'Pick an ore or Coal. Mine once or queue it.')]),
      ('JOBS', [
          ('/job', 'Pick a profession. Work that matches it gets a bonus.'),
          ('/work', 'Farming, scanning, research, cargo, deliveries, spaceport and scouting.'),
          ('/training', 'Every skill and which tasks train it.')]),
      ('GOOD TO KNOW', [
          ('Mining can fail', 'A failed attempt gives Stone Dust instead of ore.'),
          ('Rare ores', 'Mine them with /mine once a Mineral Extractor is in your bag.'),
          ('Time of day', 'Morning, Day, Evening and Night each favour different work. /world shows the current phase.')])],
     'GATHER → MINE → WORK → LEVEL UP'),
    ('Crafting',
     'The Workbench lists every recipe from easiest to hardest, with what you have and what you still need.',
     [('THE WORKBENCH', [
         ('/make', 'Categories, then recipes. Nothing is spent until you press Craft.'),
         ('/make → Ready to craft', 'Everything you can craft this moment.'),
         ('/make → Favourites', 'Star recipes to keep them on top.'),
         ('🧺 Fetch missing', 'Gathers what a recipe still needs, then crafts it.'),
         ('🎯 Set goal', 'Pin a recipe. /status shows the next step toward it.')]),
      ('WORKSTATIONS', [
          ('/workshop', 'Unlock a station once, or own the matching machine.'),
          ('Personal tiers', 'The more batches you craft, the better your results get.')])],
     'GATHER → PREVIEW → CRAFT → UNLOCK → TIER UP'),
    ('Queues',
     'A queue repeats one task up to 10 times and keeps going while you are away.',
     [('RUN A QUEUE', [
         ('Queue 5 / Queue 10 / Queue max', 'On any mine, gather or recipe panel. See the totals, then Start.'),
         ('/queue', 'Progress, items gained and used, and why it paused.'),
         ('/queue → Queue next', 'Line up the next task to start when this one ends.'),
         ('➕ Add to plan', 'Chain more steps, even "sell all". Save a plan as a routine.')]),
      ('ALERTS', [
          ('/settings → Alerts', 'A DM by default. Or a channel mention, private, quiet or off.'),
          ('Pauses', 'Low needs or missing items pause a queue. It resumes by itself.')])],
     'QUEUE → WALK AWAY → GET PINGED → REPEAT'),
    ('Money & trade',
     'Seed Coin (SC) is your money. Earn it by selling what you make and by filling orders.',
     [('SEED INDUSTRIES', [
         ('/seedindustries', 'Buy starter supplies and sell what you have.'),
         ('→ Sell all of one item', 'Sell a whole stack at once.'),
         ('→ Clear out surplus', 'Preview first. Keeps what your favourites and queues need.'),
         ('→ Production Orders', 'Daily contracts that pay well for crafted goods.'),
         ('↩️ Undo', 'Take back a sale within 60 seconds.')]),
      ('YOUR THINGS', [
          ('/inventory', 'Search, sort by value, or see what your recipes use.'),
          ('/home  /business', 'Upgrade your Habitat and run your own company.')])],
     'MAKE → SELL → SAVE → UPGRADE'),
    ('Society & world',
     'Everyone builds New Eridian together. Your work fills the settlement and helps it level up.',
     [('THE SETTLEMENT', [
         ('/world', 'The day, phase, weather, society project, story and rumors.'),
         ('Society tiers', 'Outpost → Settlement → Township → City → Regional Hub. The weakest society stat decides the tier.'),
         ('Society project', 'Work in its skills to build it. New districts open on the map as the town grows.')]),
      ('EVENTS & DAILY', [
          ('/world → Active event', 'A timed emergency. Work in the listed skills to fill it before time runs out.'),
          ('/me → Daily contract', 'One task a day for SC and Contribution.')])],
     'WORK → CONTRIBUTE → GROW THE TOWN'),
    ('Votes & stream challenges',
     'Chat and Discord decide what the colony does next, and every stream brings shared goals.',
     [('COLONY VOTE · every Avesta day', [
         ('/vote', 'Two projects and a festival. Pick one; change it until the day ends.'),
         ('Projects', 'The winner is built next and stays on the stream map as a landmark.'),
         ('Festivals', 'The winner runs the next day and boosts its kind of work.')]),
      ('STREAM CHALLENGES · live only', [
          ('/challenge', 'A 5–10 minute shared goal, like "Dust storm! Repair the walls".'),
          ('How to help', 'Do the work it names, on Twitch or Discord. Everyone who helps is paid; the top helper gets a bonus.')])],
     'VOTE → WATCH IT HAPPEN → JOIN THE CHALLENGE'),
    ('Seasons & trophies',
     'Long-term goals: climb this season, collect trophies, and show them off on stream.',
     [('SEASONS · five weeks each', [
         ('/season', 'Your points, rank and next reward. Everything you do earns points.'),
         ('Bronze · Silver · Gold', 'A season title, a hat for your Seedling on the map, then a golden title.'),
         ('Season end', 'The top three win champion titles. Only season points reset; you keep everything else.')]),
      ('TROPHIES', [
          ('/trophies', 'Collections to finish: every ore, craft categories, festival foods, curios and more.'),
          ('/trophies → Badge', 'Pin a trophy badge next to your name on the stream map.'),
          ('Weekly recap', 'Every Sunday: top players, biggest hauls and funny Seedling moments.')])],
     'PLAY → EARN POINTS → UNLOCK → SHOW OFF'),
    ('Holidays & festival foods',
     'Every holiday has a festival that opens 30 days before it and runs until 7 days after.',
     [('FESTIVAL FOODS', [
         ('/world → Holidays', "What is on now, what is next, and each festival's foods."),
         ('Crafting', 'At the Survival Workbench from gathered ingredients, only during the festival.'),
         ('Keeping', 'They stack, sell and keep all year. Stock up before it ends.')]),
      ('COMING UP', _coming_up)],
     'GATHER → COOK → FEAST → STOCK UP'),
    ('Command list',
     'Every command, grouped. /menu shows all of them as buttons.',
     [('YOU', [('/status  /me  /seedling  /customize  /inventory  /settings', 'Needs, profile, your Seedling and its look, items and preferences.')]),
      ('DO THINGS', [('/life  /work  /gather  /mine  /use', 'Recover, work, collect and use items.'),
                     ('/make  /workshop  /catalog  /queue', 'Craft, unlock stations, look things up, automate.')]),
      ('TRADE & COMMUNITY', [('/seedindustries  /market  /home  /business', 'Money, prices, your Habitat and company.'),
                             ('/vote  /challenge  /season  /trophies', 'Colony votes, stream challenges, seasons and trophies.'),
                             ('/social  /world  /district  /shift  /ducks', 'Friends, the settlement, events and holidays.')]),
      ('HELP', [('/guide  /find  /seed  /start  /link  /job', 'Next steps, search or ask, the handbook and your setup.'),
                ('/mod', 'Moderators: events, stream challenges, the recap and these panels.')])],
     'STUCK? /menu HAS A BUTTON FOR EVERYTHING', LEGEND),
]


def _wrap(text, width=WIDTH):
    return textwrap.wrap(text, width) or ['']


def box(title):
    inner = max(24, len(title) + 8)
    pad = inner - len(title)
    left, right = pad // 2, pad - pad // 2
    return [TITLE + '╭' + '─' * inner + '╮', TITLE + '│' + ' ' * left + title + ' ' * right + '│', TITLE + '╰' + '─' * inner + '╯']


def render(panel):
    title, intro, sections, flow, *legend = panel
    lines = box(title)
    lines += [INTRO + line for line in _wrap(intro)]
    for heading, rows in sections:
        lines.append(HEADING + heading)
        for command, description in (rows() if callable(rows) else rows):
            lines += [COMMAND + line for line in _wrap(command)]
            lines += [TEXT + line for line in _wrap(description)]
    lines.append(FLOW + flow)
    if legend:
        lines += ['', HEADING + '── COLOR MEANING ' + '─' * 14, '']
        lines += [colour + f'{name} = {meaning}' for name, colour, meaning in legend[0]]
    return '```ansi\n' + '\n'.join(lines) + '\n```'


def messages():
    return [render(panel) for panel in PANELS]


# ---------------------------------------------------------------- Discord's newer layout

LEGEND_SQUARES = {'GREEN': '🟩', 'YELLOW': '🟨', 'BLUE': '🟦', 'RED': '🟥', 'MAGENTA': '🟪', 'GRAY': '⬜'}


def _commands(text):
    """Commands as inline code, like every other game message: 'Type /start here' -> 'Type `/start` here'."""
    return re.sub(r'(?<![\w/`])([/!][a-z]\w*)', r'`\1`', text)


def _label(command):
    """'/life → Relax' -> '`/life` → Relax'; a label without commands is bold."""
    if re.search(r'(?<![\w/`])[/!][a-z]', command):
        return _commands(command)
    return f'**{command}**'


def card(panel):
    """One panel as a card like every other game message: heading, sections under dividers, the flow line last."""
    from . import layout_v2
    title, intro, sections, flow, *legend = panel
    blocks = [f'## {title}\n{_commands(intro)}']
    for heading, rows in sections:
        lines = [f'**{heading}**'] + [f'{_label(command)} — {_commands(description)}' for command, description in (rows() if callable(rows) else rows)]
        blocks.append('\n'.join(lines))
    tail = [f'**{_commands(flow)}**']
    if legend:
        tail += ['', '**Colour meaning** (the strip on every game reply)']
        tail += [f'{LEGEND_SQUARES.get(name, "▫️")} {name.capitalize()}: {meaning}' for name, _, meaning in legend[0]]
    blocks.append('\n'.join(tail))
    return layout_v2.card(blocks)


def bodies():
    """What `post` sends: cards in the newer layout when it is on, else the coloured text blocks."""
    from . import custom_emoji, layout_v2
    if layout_v2.ENABLED:
        return [custom_emoji.apply(dict(card(panel), allowed_mentions={'parse': []})) for panel in PANELS]
    return [{'content': text, 'allowed_mentions': {'parse': []}} for text in messages()]


def post(channel_id, token=None):
    """Post every panel to a Discord channel as the bot. Returns how many were sent."""
    token = (token or os.getenv('DISCORD_BOT_TOKEN', '')).strip()
    if not token or not str(channel_id).isdigit():
        return 0
    sent = 0
    for body in bodies():
        for _ in range(3):
            response = requests.post(f'https://discord.com/api/v10/channels/{channel_id}/messages',
                                     headers={'Authorization': 'Bot ' + token}, json=body, timeout=10)
            if response.status_code == 429:
                try:
                    time.sleep(min(5.0, float(response.json().get('retry_after', 1))))
                except (ValueError, TypeError):
                    time.sleep(1)
                continue
            break
        if not 200 <= response.status_code < 300:
            logging.getLogger(__name__).error('Guide panel post failed (HTTP %s)', response.status_code)
            break
        sent += 1
        time.sleep(0.4)
    return sent


if __name__ == '__main__':
    print('\n\n'.join(messages()))
