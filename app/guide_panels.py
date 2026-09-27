"""The eight how-to-play panels for the Discord guide channel, as coloured ANSI blocks.

Each panel is one Discord message: a ```ansi code block with a boxed green title,
a bold white introduction, cyan section headings, orange command lines with a
plain description under each, and a green flow line at the end. The colours are
ANSI escape codes, which cannot be typed in Discord and are often lost when
copied, so moderators post the panels with `/mod action:Post guide panels`.
`docs/discord-guide-panels.txt` holds the same text for manual pasting.
"""
import logging
import os
import textwrap
import time
import requests

ESC = '\x1b'
WIDTH = 58
TITLE, INTRO, HEADING, COMMAND, TEXT, FLOW = (ESC + '[1;32m', ESC + '[1;37m', ESC + '[1;36m', ESC + '[0;33m', ESC + '[0m', ESC + '[1;32m')

# (title, intro, [(heading, [(command, description), ...]), ...], flow line)
PANELS = [
    ('Start here!',
     'New Eridian v2 is a Twitch + Discord community life game on Avesta. Build your citizen, learn skills, make useful supplies and help the settlement grow.',
     [('YOUR FIRST STEPS', [
         ('/menu', 'Every part of the game as buttons. Pick an area, then what to do.'),
         ('/start', 'Create or load your citizen.'),
         ('/job', 'Choose a profession. Matching work earns a job bonus.'),
         ('/status', 'Your needs, queue, cooldowns and next step.'),
         ('/guide', 'The best thing to do next, and why.')]),
      ('PLAYING ON TWITCH TOO?', [
          ('/link → Code', 'Get a code with !link in Twitch, then enter it here to merge your citizens.')])],
     'RECOVER → WORK → GATHER → MAKE → IMPROVE → CONTRIBUTE'),
    ('Needs & recovery',
     'Every task uses Energy, Nutrition and Comfort. Work stops when Energy, Nutrition or Social drop below 20, or Comfort below 10.',
     [('RECOVER', [
         ('/life → Action: Relax', '+25 Energy and +20 Comfort, every 30 seconds.'),
         ('/life → Action: Sleep', 'Energy and Comfort to 100, every 30 minutes.'),
         ('/life → Action: Eat', 'Pick a food. With no food and low Nutrition, a free emergency meal.'),
         ('/life → Action: Games', '+25 Social, no partner needed.'),
         ('/life → Action: Recover', 'Every recovery that is ready, in one press.')]),
      ('HANDS-FREE', [
          ('/use', 'Beds, seats, baths and clothing restore Comfort and are kept.'),
          ('/settings → Autorecover: On', 'Paused queues recover by themselves, then carry on.')])],
     'EAT → REST → STAY COMFORTABLE → KEEP WORKING'),
    ('Gathering & work',
     'Raw materials come from gathering and mining. Every success gives items and practice in its skill.',
     [('COLLECT', [
         ('/gather', 'Lumber, Berries, Herbs, Stone and every other natural material.'),
         ('/mine', 'Pick an ore or Coal. Mine once or queue up to 10 attempts.')]),
      ('JOBS', [
          ('/work', 'Farming, scanning, research, cargo, deliveries, spaceport and scouting.'),
          ('/training', 'See every skill and which tasks train it.')]),
      ('GOOD TO KNOW', [
          ('Mining can fail', 'A failed attempt gives Stone Dust instead of ore.'),
          ('Rare ores', 'Need Harvesting level 3 and three good prospecting steps per ore.')])],
     'GATHER → MINE → WORK → LEVEL UP'),
    ('Crafting',
     'The Workbench lists every recipe from easiest to hardest, with what you have and what you still need.',
     [('THE WORKBENCH', [
         ('/make', 'Categories, then recipes. Preview first; nothing is spent until you craft.'),
         ('/make → Category: Ready now', 'Everything you can craft this moment.'),
         ('/make → Category: Favourites', 'Star up to 10 recipes to keep them on top.'),
         ('🧺 Fetch missing', 'On a recipe you cannot make yet: gathers what is missing, then crafts it.'),
         ('🎯 Set goal', 'Pin a recipe. /status shows the next step all the way down the ingredient tree.')]),
      ('WORKSTATIONS & TIERS', [
          ('/workshop', 'Unlock a station once for a fee, or own the matching machine.'),
          ('Personal tiers', 'Unlock at 25, 100 and 250 crafted batches.')])],
     'GATHER → PREVIEW → CRAFT → UNLOCK → TIER UP'),
    ('Queues',
     'A queue repeats one task up to 10 times, one attempt every 10 seconds, even while you are away.',
     [('RUN A QUEUE', [
         ('Queue 5 / Queue 10', 'On any mine, gather or recipe panel. See the totals, then press Start.'),
         ('/queue', 'Progress, items gained and used, and why it paused.'),
         ('/queue → Action: Queue next', 'Line up one more task to start when this one ends.'),
         ('Queue max', 'As many attempts as your items and needs allow, up to 10.'),
         ('➕ Add to plan', 'Chain up to 6 more steps, including "sell all". Save a plan as a routine.')]),
      ('ALERTS', [
          ('/settings → Alerts', 'Channel mention, direct message, private, quiet or off.'),
          ('/settings → Popups', 'Private "only you can see this" notes at your next command.'),
          ('Pauses', 'Low needs or missing items pause it. It resumes by itself.')])],
     'QUEUE → WALK AWAY → GET PINGED → REPEAT'),
    ('Money & trade',
     'Seed Coin (SC) is your personal currency. Earn it by selling what you make and by taking orders.',
     [('SEED INDUSTRIES', [
         ('/seedindustries', 'Buy starter supplies and sell anything you have made.'),
         ('→ Action: Sell all of one item', 'Sell a whole stack at once.'),
         ('→ Action: Clear out surplus', 'Preview first. Keeps 20 of each and anything your favourites use.'),
         ('→ Action: View Production Orders', 'Three daily contracts that pay well for crafted goods.'),
         ('↩️ Undo', 'Take back a sale within 60 seconds. Auto-sell junk when queues finish: /menu → Bag.')]),
      ('YOUR THINGS', [
          ('/inventory', 'Search, sort by value, or show what your ready recipes use.'),
          ('/home and /business', 'Upgrade your Habitat and run your own company.')])],
     'MAKE → SELL → SAVE → UPGRADE'),
    ('Holidays & festival foods',
     'Every holiday has a festival that opens 30 days before it and runs until 7 days after.',
     [('FESTIVAL FOODS', [
         ('/world → Section: Holidays', "What is on now, what is next, and each festival's foods."),
         ('Crafting', 'Free at the Survival Workbench from gathered ingredients, only during the festival.'),
         ('Eating', 'Nutrition plus extra Comfort and Morale.'),
         ('Keeping', 'They stack, sell and keep all year. Stock up before it ends.')]),
      ('COMING UP', [
          ('🎃 Halloween · opens October 1', 'Pumpkin Bites, Moon Tart and Candy Herb Mix.')])],
     'GATHER → COOK → FEAST → STOCK UP'),
    ('Command list',
     'Every command, grouped. /menu shows all of them as buttons.',
     [('YOU', [('/status  /me  /inventory  /settings', 'Needs, profile, skills, items and preferences.'),
              ('/find', 'Search recipes, items, buttons and the handbook for anything.')]),
      ('DO THINGS', [('/life  /work  /gather  /mine  /use', 'Recover, work, collect and use items.'),
                     ('/make  /workshop  /catalog  /queue', 'Craft, unlock stations, look things up, automate.')]),
      ('TRADE & COMMUNITY', [('/seedindustries  /market  /home  /business', 'Money, prices, your Habitat and company.'),
                             ('/social  /world  /district  /shift  /ducks', 'Friends, the settlement, events and holidays.')]),
      ('HELP', [('/guide  /seed  /start  /link  /job  /specialize', 'Next steps, the handbook and your setup.'),
                ('/mod', 'Moderators: events, logs, account lookups, these panels.')])],
     'STUCK? /menu HAS A BUTTON FOR EVERYTHING'),
]


def _wrap(text, width=WIDTH):
    return textwrap.wrap(text, width) or ['']


def box(title):
    inner = max(24, len(title) + 8)
    pad = inner - len(title)
    left, right = pad // 2, pad - pad // 2
    return [TITLE + '╭' + '─' * inner + '╮', TITLE + '│' + ' ' * left + title + ' ' * right + '│', TITLE + '╰' + '─' * inner + '╯']


def render(panel):
    title, intro, sections, flow = panel
    lines = box(title)
    lines += [INTRO + line for line in _wrap(intro)]
    for heading, rows in sections:
        lines.append(HEADING + heading)
        for command, description in rows:
            lines += [COMMAND + line for line in _wrap(command)]
            lines += [TEXT + line for line in _wrap(description)]
    lines.append(FLOW + flow)
    return '```ansi\n' + '\n'.join(lines) + '\n```'


def messages():
    return [render(panel) for panel in PANELS]


def post(channel_id, token=None):
    """Post every panel to a Discord channel as the bot. Returns how many were sent."""
    token = (token or os.getenv('DISCORD_BOT_TOKEN', '')).strip()
    if not token or not str(channel_id).isdigit():
        return 0
    sent = 0
    for text in messages():
        for _ in range(3):
            response = requests.post(f'https://discord.com/api/v10/channels/{channel_id}/messages',
                                     headers={'Authorization': 'Bot ' + token},
                                     json={'content': text, 'allowed_mentions': {'parse': []}}, timeout=10)
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
