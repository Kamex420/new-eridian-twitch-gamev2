"""Button menus for the whole game: one window with every area, then each area's actions.

`/menu` opens Home: a button per area (Life, Work, Craft, Queue…). An area shows
a button for each of its actions and views; actions that need a choice (which
food, which ore, which citizen) open a dropdown first. After any action the
result is shown with the same area's buttons again, plus Back and Home, so the
next step is always one tap away.

Every button runs the same command a slash command would (through the Discord
dispatcher), so rules, cooldowns and receipts are identical. Buttons that
spend something carry one-time tickets (see ui.issue); views and menus spend
nothing and carry their target in the custom_id:

  mn|<area>            open an area
  mv|<leaf>            run a view
  mk|<leaf>            open a leaf's choice list
  mp|<leaf>            a choice from that list (select value)
  ma|<leaf>|<value>    amount buttons for a chosen item (buy, sell)
  mo|<leaf>            a pop-up form (search, link code, business name, custom amount)
"""
import secrets
from . import ui, workbench as wb

# Areas: key -> (emoji, title, one-line description, children). Children are
# area keys or leaf keys; the order is the button order.
AREAS = {
    'home': ('🏠', 'New Eridian', 'Pick an area. Menus and views spend nothing; action buttons do their task once.',
             ['status', 'inbox', 'recent', 'find', 'life', 'work', 'craft', 'queue', 'bag', 'trade', 'world', 'me', 'social', 'settings',
              'account', 'help', 'mod']),
    'recent': ('🔁', 'Recent actions', 'Your last ten actions. Tap one to do it again.', []),
    'life': ('❤️', 'Life & Recovery', 'Keep Energy, Nutrition, Social and Comfort up so work never stops.',
             ['relax', 'sleep', 'eat', 'eatfull', 'games', 'walk', 'hobby', 'meal', 'recover', 'needs', 'cooldowns']),
    'work': ('⛏️', 'Work', 'Mine, gather or pick a job. Each success gives items and practice.',
             ['mine', 'gather', 'w_farm_tend', 'w_farm_harvest', 'w_farm_irrigate', 'w_farm_hydroponics', 'w_scan', 'w_rare',
              'w_research', 'w_field_analysis', 'w_cargo', 'w_delivery', 'w_spaceport', 'w_expedite', 'w_scout', 'w_survey', 'repair',
              'gearrepair', 'training', 'trainskill']),
    'craft': ('🛠️', 'Craft', 'Open the Workbench, a category, what is ready now, or your favourites.',
              ['workbench', 'ready', 'favs', 'goal', 'stations'] + ['c_' + key for key, *_ in wb.CATEGORIES]),
    'stations': ('🏭', 'Workshops', 'Workstations and personal tiers. Unlock a station once, or own its machine.',
                 ['workshop', 'unlock', 'catalogcat']),
    'queue': ('⏱️', 'Queue', 'Your automatic task queue. Check it, repeat it or stop it.',
              ['qstatus', 'qdetails', 'plan', 'repeat', 'cancel', 'clearnext', 'status']),
    'bag': ('🎒', 'Bag', 'Everything you own. Use it, eat it, sell it or sort it.',
            ['inventory', 'search', 'by_value', 'by_name', 'by_category', 'favitems', 'sellable', 'ready_items', 'gear', 'uses', 'use', 'eat',
             'eatfull', 'sell', 'clearout', 'autosell', 'undo', 'catalog', 'catalogcat']),
    'trade': ('🪙', 'Trade', 'Seed Industries, production orders, market work, your Habitat and business.',
              ['market', 'browse', 'buy', 'sellsome', 'sell', 'starters', 'orders', 'fulfill', 'prices', 'rawsell', 'commerce', 'analyze',
               'habitat', 'homeup', 'business', 'bstart', 'bwork', 'bcontract', 'binvest']),
    'world': ('🌎', 'World', 'Avesta, New Eridian, events, holidays and news.',
              ['wd_overview', 'wd_conditions', 'wd_society', 'wd_society_progress', 'wd_leaderboard', 'wd_event',
               'wd_event_history', 'wd_holidays', 'wd_project', 'wd_story', 'wd_bulletin', 'wd_rumor', 'wd_market']),
    'me': ('👤', 'Me', 'Your citizen. Profile, skills, progress and personal choices.',
           ['me_overview', 'me_skills', 'me_daily', 'me_achievements', 'me_collection', 'me_bonuses', 'me_traits',
            'me_relationships', 'me_journal', 'me_tutorial', 'me_titles', 'choices']),
    'choices': ('🧭', 'Choices', 'Job, district, shift, delivery partner, title, specialization and display style.',
                ['job', 'district', 'shift', 'duck', 'title', 'specialize', 'display_compact', 'display_detailed']),
    'social': ('🤝', 'Social', 'Spend time with other citizens, or recover Social on your own.',
               ['friend', 'games', 'recreation', 'meal', 'me_relationships']),
    'settings': ('⚙️', 'Settings', 'How queue alerts reach you and whether queues recover by themselves.',
                 ['alerts_mention', 'alerts_dm', 'alerts_private', 'alerts_quiet', 'alerts_off', 'auto_on', 'auto_off',
                  'popups_important', 'popups_all', 'popups_off', 'inbox', 'favs', 'status']),
    'help': ('📖', 'Help', 'What to do next, and the full handbook by topic.',
             ['guide', 'guidegoal', 'find', 'me_tutorial', 'wd_holidays'] + ['h_' + t for t in ('start', 'character', 'property', 'life', 'production',
                                                                          'operations', 'society', 'other', 'terms')]),
    'account': ('🔗', 'Account', 'Create your citizen, or link your Twitch citizen: type !link in Twitch chat, then enter the code here.',
                ['start', 'link', 'me_overview', 'me_tutorial', 'guide']),
    'mod': ('🛡️', 'Moderator', 'Events, the moderator log, account lookups and the channel panels. Moderators only.',
            ['m_eventstart', 'm_eventstop', 'm_modlog', 'm_lookup', 'm_guidepanels', 'm_menupanel', 'h_moderator']),
}
# Areas only moderators see on the Home screen.
MOD_AREAS = {'mod'}
# Commands a menu button may only run for moderators (linklookup: owners).
MOD_COMMANDS = {'eventstart', 'eventstop', 'modlog', 'guidepanels', 'menupanel', 'linklookup'}

# Leaves: key -> dict(label, emoji, kind, cmd, opts, hint[, pick, then]).
#   kind 'do'   spends or changes something: a one-time ticket button
#   kind 'view' reads only
#   kind 'nav'  an existing panel control (Workbench, queue); 'nav' holds its custom_id parts
#   kind 'pick' opens a dropdown from `pick`; `then` says what a choice does:
#        'do' runs it, 'confirm' asks first, 'panel' opens a mine/gather panel,
#        'social' opens actions with that citizen
LEAVES = {}


def leaf(key, label, emoji, kind, cmd='', opts=None, hint='', **extra):
    LEAVES[key] = dict(label=label, emoji=emoji, kind=kind, cmd=cmd, opts=opts or {}, hint=hint, **extra)


leaf('status', 'Status', '📊', 'view', 'status', hint='needs, queue, cooldowns and what to do next')
leaf('inbox', 'Notifications', '📬', 'view', 'inbox', hint='queue results, warnings and tips sent only to you')
leaf('qdetails', 'Details & requirements', '📘', 'nav', nav=('qd',), hint='every requirement and rule for your queue')
# Life
leaf('relax', 'Relax', '🛋️', 'do', 'relax', hint='+25 Energy, +20 Comfort')
leaf('sleep', 'Sleep', '🛏️', 'do', 'sleep', hint='Energy and Comfort to 100 (long cooldown)')
leaf('eat', 'Eat', '🍲', 'pick', 'eat', pick='food', then='do', option='food', hint='choose a food you own')
leaf('games', 'Games', '🎲', 'do', 'games', hint='+25 Social')
leaf('walk', 'Walk', '🌿', 'do', 'walk', hint='Morale and exploration')
leaf('hobby', 'Hobby', '🎨', 'pick', 'hobby', pick='hobby', then='do', option='hobby', hint='practice a hobby')
leaf('meal', 'Share meal', '🎃', 'do', 'meal', {'action': 'share'}, hint='1 Pumpkin: +25 Nutrition, +10 Social')
leaf('recover', 'Recover', '🩹', 'do', 'recover', hint='every recovery that is ready, at once')
leaf('eatfull', 'Eat until full', '🍽️', 'do', 'eatfull', hint='cheapest everyday food until Nutrition reaches 80')
leaf('needs', 'Needs', '❤️', 'view', 'me', {'section': 'life'}, hint='your needs and how to fix them')
leaf('cooldowns', 'Cooldowns', '⏱️', 'view', 'me', {'section': 'cooldowns'}, hint='what is ready and when')
# Work
leaf('mine', 'Mine', '⛏️', 'pick', 'mine', pick='ore', then='panel', hint='choose an ore; mine once or queue')
leaf('gather', 'Gather', '🌿', 'pick', 'gather', pick='resource', then='panel', hint='choose a material; gather once or queue')
WORK = [('farm_tend', 'Tend fields', '🌱'), ('farm_harvest', 'Harvest', '🎃'), ('farm_irrigate', 'Irrigate', '💧'),
        ('farm_hydroponics', 'Hydroponics', '🧪'), ('scan', 'Scan', '📡'), ('rare', 'Prospect', '💎'), ('research', 'Research', '🔬'),
        ('field_analysis', 'Field analysis', '🧫'), ('cargo', 'Cargo', '📦'), ('delivery', 'Delivery', '🦆'),
        ('spaceport', 'Spaceport', '🚀'), ('expedite', 'Expedite', '⚡'), ('scout', 'Scout', '🧭'), ('survey', 'Survey', '🗺️')]
for _task, _label, _emoji in WORK:
    leaf('w_' + _task, _label, _emoji, 'do', 'work', {'task': _task}, hint='')
leaf('training', 'Training', '🎓', 'view', 'training', hint='skills, branches and what each task trains')
leaf('trainskill', 'Train a skill', '🎯', 'pick', 'training', pick='field:training:skill', then='view', option='skill',
     hint='one skill: its tasks and what they need')
leaf('repair', 'Repair society', '🔧', 'do', 'repair', {'target': 'society'}, hint='fix settlement systems (Engineering)')
leaf('gearrepair', 'Repair gear', '🪛', 'pick', 'repair', {'target': 'gear'}, pick='gear', then='do', option='item',
     hint='restore a quality tool with Iron Nails')
# Craft
leaf('workbench', 'Workbench', '🛠️', 'nav', nav=('wh',), hint='every category and what to start with')
leaf('ready', 'Ready now', '✅', 'nav', nav=('wc', 'ready', 1, ''), hint='everything you can craft right now')
leaf('favs', 'Favourites', '⭐', 'nav', nav=('wc', 'favorites', 1, ''), hint='your starred recipes')
leaf('workshop', 'Workshops', '🏭', 'view', 'workshop', hint='stations, tiers and unlock fees')
leaf('goal', 'Goal', '🎯', 'nav', nav=('gv',), hint='your pinned recipe and everything still needed for it')
leaf('catalog', 'Catalog', '📚', 'view', 'catalog', hint='every item and where it comes from')
leaf('catalogcat', 'Catalog by category', '🗂️', 'pick', 'catalog', pick='field:catalog:category', then='view', option='category',
     hint='items of one category and where they come from')
leaf('unlock', 'Unlock station', '🔓', 'pick', 'workshop', {'action': 'unlock'}, pick='station', then='confirm', option='station',
     hint='pay once to use a workstation')
for _key, _emoji, _label, _ in wb.CATEGORIES:
    leaf('c_' + _key, _label, _emoji, 'nav', nav=('wc', _key, 1, ''), hint='')
# Queue
leaf('qstatus', 'Queue status', '📋', 'nav', nav=('qv',), hint='progress, totals and why it paused')
leaf('repeat', 'Repeat last', '🔁', 'do', 'queue', {'action': 'repeat'}, hint='run your last queue again')
leaf('cancel', 'Cancel queue', '⏹️', 'do', 'queue', {'action': 'cancel'}, hint='stop the remaining attempts', style=4)
leaf('clearnext', 'Clear next', '⏭️', 'nav', nav=('cn',), hint='remove the follow-up queue')
leaf('plan', 'Plan & routines', '🗺️', 'nav', nav=('pv',), hint='steps after this queue, and saved routines')
# Bag
leaf('inventory', 'Inventory', '🎒', 'view', 'inventory', hint='everything you own')
leaf('by_value', 'By value', '💰', 'view', 'inventory', {'sort': 'value'}, hint='most valuable first')
leaf('by_name', 'By name', '🔤', 'view', 'inventory', {'sort': 'name'}, hint='A to Z')
leaf('by_category', 'By category', '🗂️', 'view', 'inventory', {'sort': 'category'}, hint='grouped by category')
leaf('favitems', 'Favourite ingredients', '⭐', 'view', 'inventory', {'show': 'favorites'}, hint='what your favourite recipes use')
leaf('sellable', 'Sellable', '🏷️', 'view', 'inventory', {'show': 'sellable'}, hint='what Seed Industries buys')
leaf('search', 'Search bag', '🔍', 'modal', 'inventory', modal=('Search your bag', 'Item name or part of it', 'e.g. iron'), option='search',
     hint='find an item you own')
leaf('ready_items', 'For ready recipes', '✅', 'view', 'inventory', {'show': 'ready'}, hint='items your ready recipes use')
leaf('gear', 'Quality gear', '⚙️', 'view', 'inventory', {'section': 'gear'}, hint='condition and repairs')
leaf('use', 'Use item', '🧰', 'pick', 'use', pick='use', then='do', option='item', hint='beds, seats, baths, tools and more')
leaf('sell', 'Sell all of…', '🏷️', 'pick', 'seedindustries', {'action': 'sellall'}, pick='sell', then='confirm', option='item',
     hint='sell a whole stack')
leaf('clearout', 'Clear out', '🧹', 'view', 'seedindustries', {'action': 'clearout'}, hint='sell surplus materials (preview first)')
leaf('uses', 'What can I make?', '🔍', 'pick', 'catalog', pick='owned', then='uses', option='item', hint='recipes that use an item you own')
leaf('autosell', 'Auto-sell', '🤖', 'nav', nav=('av',), hint='items sold automatically when a queue finishes')
leaf('undo', 'Undo sale', '↩️', 'do', 'undo', hint=f'take back your last sale (within 60 seconds)')
# Trade
leaf('market', 'Seed Industries', '🏭', 'view', 'seedindustries', hint='buy supplies and sell your goods')
leaf('browse', 'Browse shop', '🛒', 'pick', 'seedindustries', {'action': 'browse'}, pick='field:seedindustries:category', then='view',
     option='category', hint='supplies by category with prices')
leaf('buy', 'Buy', '🛍️', 'pick', 'seedindustries', {'action': 'buy'}, pick='buy', then='amount', option='item',
     hint='choose an item, then how many')
leaf('sellsome', 'Sell some', '💵', 'pick', 'seedindustries', {'action': 'sell'}, pick='sell', then='amount', option='item',
     hint='sell part of a stack')
leaf('rawsell', 'Sell raw goods', '📦', 'pick', 'market', {'action': 'sell'}, pick='field:market:resource', then='amount', option='resource',
     hint='crops, ore, rare ore, components or cargo at market price')
leaf('bstart', 'Start business', '🏗️', 'modal', 'business', {'action': 'start'}, modal=('Start a business', 'Business name', 'e.g. Rocky Repairs'),
     option='name', max_length=30, hint='found your company (costs SC)')
leaf('starters', 'Starter routes', '🧭', 'view', 'seedindustries', {'action': 'starters'}, hint='what to buy for each skill')
leaf('orders', 'Orders', '📋', 'view', 'seedindustries', {'action': 'orders'}, hint="today's production orders")
leaf('fulfill', 'Deliver order', '📦', 'pick', 'seedindustries', {'action': 'fulfill'}, pick='order', then='confirm', option='item',
     hint='hand in a production order')
leaf('prices', 'Prices', '📈', 'view', 'market', {'action': 'view'}, hint='day-by-day market prices')
leaf('commerce', 'Commerce work', '🏪', 'do', 'market', {'action': 'work'}, hint='earn SC trading')
leaf('analyze', 'Market analysis', '📊', 'do', 'market', {'action': 'analyze'}, hint='needs a Market Analyzer')
leaf('habitat', 'Habitat', '🏠', 'view', 'home', hint='your home and its next upgrade')
leaf('homeup', 'Upgrade home', '🔨', 'do', 'home', {'action': 'upgrade'}, hint='costs SC and Iron Nails')
leaf('business', 'Business', '🏢', 'view', 'business', hint='your company')
leaf('bwork', 'Business work', '💼', 'do', 'business', {'action': 'work'}, hint='')
leaf('bcontract', 'Contract', '📝', 'do', 'business', {'action': 'contract'}, hint='')
leaf('binvest', 'Invest', '💹', 'do', 'business', {'action': 'invest'}, hint='')
# World
for _section, _label, _emoji in [('overview', 'Overview', '🌎'), ('conditions', 'Conditions', '☁️'), ('society', 'Society', '🏛️'),
                                 ('society_progress', 'Next tier', '📈'), ('leaderboard', 'Leaderboard', '🏆'), ('event', 'Event', '🚨'),
                                 ('event_history', 'Past events', '📜'), ('holidays', 'Holidays', '🎉'), ('project', 'Project', '🏗️'),
                                 ('story', 'Story', '📖'), ('bulletin', 'Bulletin', '📰'), ('rumor', 'Rumor', '👂'), ('market', 'Market', '🪙')]:
    leaf('wd_' + _section, _label, _emoji, 'view', 'world', {'section': _section}, hint='')
# Me
for _section, _label, _emoji in [('overview', 'Profile', '👤'), ('skills', 'Skills', '📈'), ('daily', 'Daily contract', '📋'),
                                 ('achievements', 'Achievements', '🏆'), ('collection', 'Collection', '🗃️'), ('bonuses', 'Bonuses', '⚡'),
                                 ('traits', 'Traits', '🧬'), ('relationships', 'Relationships', '💞'), ('journal', 'Journal', '📓'),
                                 ('tutorial', 'Tutorial', '🎓'), ('titles', 'Titles', '🏅')]:
    leaf('me_' + _section, _label, _emoji, 'view', 'me', {'section': _section}, hint='')
leaf('job', 'Job', '💼', 'pick', 'job', pick='choices:job', then='do', option='job', hint='profession bonus')
leaf('district', 'District', '🏘️', 'pick', 'district', pick='choices:district', then='do', option='district', hint='home district')
leaf('shift', 'Shift', '🕐', 'pick', 'shift', pick='choices:shift', then='do', option='role', hint="today's shift role")
leaf('duck', 'Delivery partner', '🦆', 'pick', 'ducks', pick='choices:ducks', then='do', option='duck', hint='preferred duck')
leaf('title', 'Equip title', '🏅', 'pick', 'me', {'section': 'titles'}, pick='title', then='do', option='title', hint='show off a title')
leaf('specialize', 'Specialize', '🎯', 'pick', 'specialize', pick='choices:specialize', then='confirm', option='path',
     hint='permanent Lv.10 path')
leaf('display_compact', 'Compact results', '📏', 'do', 'me', {'section': 'display', 'style': 'compact'}, hint='')
leaf('display_detailed', 'Detailed results', '📜', 'do', 'me', {'section': 'display', 'style': 'detailed'}, hint='')
# Social
leaf('friend', 'With a citizen', '🤝', 'pick', 'social', pick='player', then='social', option='player',
     hint='say hi, hang out, mentor or do a duo activity')
leaf('recreation', 'Recreation Set', '🎳', 'do', 'social', {'action': 'group_games'}, hint='group games with your set')
SOCIAL = [('hi', 'Say hi', '👋'), ('hangout', 'Hang out', '☕'), ('mentor', 'Mentor', '🎓'), ('duo_walk', 'Duo walk', '🚶'),
          ('duo_games', 'Duo games', '🎲'), ('duo_research', 'Duo research', '🔬'), ('duo_delivery', 'Duo delivery', '🦆'),
          ('duo_explore', 'Duo explore', '🧭')]
for _action, _label, _emoji in SOCIAL:
    leaf('s_' + _action, _label, _emoji, 'do', 'social', {'action': _action}, hint='')
# Settings
for _mode, _label, _emoji in [('mention', 'Alerts: mention', '🔔'), ('dm', 'Alerts: DM', '✉️'), ('private', 'Alerts: private', '🔒'),
                              ('quiet', 'Alerts: quiet', '🔕'), ('off', 'Alerts: off', '🚫')]:
    leaf('alerts_' + _mode, _label, _emoji, 'do', 'settings', {'alerts': _mode}, hint='')
for _mode, _label, _emoji in [('important', 'Popups: important', '📬'), ('all', 'Popups: all', '📣'), ('off', 'Popups: off', '📭')]:
    leaf('popups_' + _mode, _label, _emoji, 'do', 'settings', {'popups': _mode}, hint='')
leaf('auto_on', 'Auto-recover on', '🩹', 'do', 'settings', {'autorecover': 'on'}, hint='paused queues recover by themselves')
leaf('auto_off', 'Auto-recover off', '✋', 'do', 'settings', {'autorecover': 'off'}, hint='')
# Help
leaf('guide', 'What next?', '🧭', 'view', 'guide', hint='your best next step and why')
leaf('guidegoal', 'Guide for…', '🗺️', 'pick', 'guide', pick='field:guide:goal', then='view', option='goal',
     hint='step-by-step help for one goal (SC, crafting, home…)')
leaf('find', 'Find', '🔎', 'modal', 'find', modal=('Find anything', 'Recipe, item, button or topic', 'e.g. campfire'), option='query',
     hint='search recipes, items, buttons and the handbook')
# Account
leaf('start', 'Start / load citizen', '🌱', 'view', 'start', hint='create your citizen or see where you are')
leaf('link', 'Link Twitch', '🔗', 'modal', 'link', modal=('Link your Twitch citizen', 'Code from !link in Twitch chat', 'e.g. AB12CD'),
     option='code', max_length=12, hint='enter the code from !link in Twitch chat')
# Moderator
leaf('m_eventstart', 'Start event', '🚨', 'pick', 'eventstart', pick='field:eventstart:event', then='confirm', option='event',
     hint='begin a society event')
leaf('m_eventstop', 'Stop event', '🛑', 'do', 'eventstop', style=4, hint='cancel the active event without a penalty')
leaf('m_modlog', 'Moderator log', '📜', 'view', 'modlog', hint='the last ten moderator actions')
leaf('m_lookup', 'Account lookup', '🔍', 'pick', 'linklookup', pick='player_name', then='view', option='player',
     hint='linked accounts of a citizen (owners)')
leaf('m_guidepanels', 'Post guide panels', '📖', 'do', 'guidepanels', hint='the eight how-to-play panels, in this channel')
leaf('m_menupanel', 'Post game panel', '🎛️', 'do', 'menupanel', hint='a button panel anyone can press to open their menu')
leaf('h_moderator', 'Moderator help', '📖', 'view', 'seed', {'topic': 'moderator'}, hint='')
for _topic, _label in [('start', 'Start here'), ('character', 'Character'), ('property', 'Home & crafting'), ('life', 'Life'),
                       ('production', 'Work'), ('operations', 'Logistics'), ('society', 'Society'), ('other', 'Other'), ('terms', 'Terms')]:
    leaf('h_' + _topic, _label, '📖', 'view', 'seed', {'topic': _topic}, hint='')

PARENT = {}
for _area, (_, _, _, _children) in AREAS.items():
    for _child in _children:
        PARENT.setdefault(_child, _area)
PARENT.update({'s_' + _action: 'social' for _action, _, _ in SOCIAL})   # shown after choosing a citizen
# The area a slash command belongs to, for the "back to area" button on replies.
COMMAND_AREA = {}
for _key, _leaf in LEAVES.items():
    if _leaf['cmd']:
        COMMAND_AREA.setdefault(_leaf['cmd'], PARENT.get(_key, 'home'))
COMMAND_AREA.update({'link': 'account', 'start': 'account', 'eventstart': 'mod', 'eventstop': 'mod', 'modlog': 'mod',
                     'linklookup': 'mod', 'guidepanels': 'mod', 'menupanel': 'mod', 'eatfull': 'life', 'undo': 'bag', 'find': 'help', 'make': 'craft', 'workshop': 'craft', 'catalog': 'craft', 'queue': 'queue', 'mine': 'work', 'gather': 'work',
                     'farm': 'work', 'scan': 'work', 'rare': 'work', 'research': 'work', 'cargo': 'work', 'delivery': 'work',
                     'spaceport': 'work', 'explore': 'work', 'repair': 'work', 'training': 'work', 'society': 'world',
                     'event': 'world', 'holiday': 'world', 'progress': 'me', 'seed': 'help', 'guide': 'help',
                     'eat': 'life', 'relax': 'life', 'sleep': 'life', 'games': 'life', 'walk': 'life', 'hobby': 'life',
                     'meal': 'life', 'recover': 'life', 'use': 'bag', 'inventory': 'bag', 'status': 'home', 'settings': 'settings'})
# Slash commands whose replies offer "Again" (they perform a task and can simply be repeated).
REPEATABLE = {'eatfull', 'relax', 'sleep', 'games', 'walk', 'meal', 'recover', 'farm', 'scan', 'rare', 'research', 'cargo', 'delivery',
              'spaceport', 'explore', 'repair', 'hobby', 'eat', 'use'}


# ---------------------------------------------------------------- building blocks

def _button(m, owner, key, compact=False):
    if key in AREAS:
        emoji, title, _, _ = AREAS[key]
        return ui.button(title, ui.cid(owner, 'mn', key), style=1, emoji=emoji)
    item = LEAVES[key]
    if item['kind'] == 'do':
        ticket = ui.issue(m, owner, {'do': 'cmd', 'leaf': key})
        return ui.button(item['label'], ui.cid(owner, 't', ticket), style=item.get('style', 3), emoji=item['emoji'])
    if item['kind'] == 'nav':
        return ui.button(item['label'], ui.cid(owner, *item['nav']), emoji=item['emoji'])
    if item['kind'] == 'modal':
        return ui.button(item['label'], ui.cid(owner, 'mo', key), emoji=item['emoji'])
    verb = 'mk' if item['kind'] == 'pick' else 'mv'
    return ui.button(item['label'], ui.cid(owner, verb, key), emoji=item['emoji'])


def grid(m, owner, keys, rows=4):
    """Buttons five per row, at most `rows` rows."""
    buttons = [_button(m, owner, key) for key in keys][:rows * 5]
    return [ui.row(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]


def nav(owner, area):
    back = PARENT.get(area, 'home') if area != 'home' else None
    buttons = []
    if back and back != 'home':
        emoji, title, _, _ = AREAS[back]
        buttons.append(ui.button('Back: ' + title, ui.cid(owner, 'mn', back), emoji='◀️'))
    if area != 'home':
        buttons.append(ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))
    return ui.row(*buttons) if buttons else None


def children_of(m, area):
    """An area's buttons; moderator tools only appear for moderators."""
    keys = AREAS[area][3]
    if area == 'home' and not ui.is_moderator(m):
        keys = [k for k in keys if k not in MOD_AREAS]
    return keys


def area_text(m, db, p, area):
    emoji, title, text, _ = AREAS[area]
    children = children_of(m, area)
    lines = [f'{emoji} {title.upper()}', text, '']
    if area == 'home' and p is not None:
        life = m.life_state(db, p)
        lines = [f'{emoji} NEW ERIDIAN — {p.display_name}',
                 f'⚡ {life.energy} · 🍲 {life.nutrition} · 💬 {life.social} · 🛋️ {life.comfort} · 🪙 {p.sc} SC',
                 m.qol.queue_summary(m, db, p, 'discord')[0].split('\n')[0], '', text, '']
    for key in children:
        if key in AREAS:
            e, t, d, _ = AREAS[key]
            lines.append(f'{e} **{t}** — {d}')
        else:
            item = LEAVES[key]
            if item['hint']:
                lines.append(f"{item['emoji']} **{item['label']}** — {item['hint']}")
    return '\n'.join(lines).rstrip()


def area_components(m, owner, area):
    rows = grid(m, owner, children_of(m, area))
    return rows + [nav(owner, area)]


def reply(m, text, command, rows):
    """A result card (with Details pages when long) followed by menu rows; five rows at most."""
    data = m._discord_json_message(text, message_type=command)['data']
    own = [r for r in (data.get('components') or []) if r and r.get('components')]
    extra = [r for r in rows if r and r.get('components')]
    # Keep the result's own controls (e.g. Details) and the navigation row; drop grid rows if needed.
    data['components'] = own + (extra if len(own) + len(extra) <= 5 else extra[-(5 - len(own)):])
    data.pop('flags', None)
    return data


# ---------------------------------------------------------------- choice lists

def choices(m, db, p, source, uid):
    """(label, value) rows for a leaf's dropdown, at most 25."""
    if source == 'food':
        foods = m.edible_inventory(db, p)
        rows = [(f"{r['name']} ×{r['qty']} — {r['effect']}", r['key']) for r in foods if r['qty'] > 0]
        if m.emergency_food_available(db, p, foods):
            rows.append(('Emergency meal — free; restores Nutrition to 40', 'emergency'))
        return rows
    if source == 'hobby':
        return [(c['name'], c['value']) for c in m.DISCORD_OPTION_SCHEMA['hobby'][0]['choices']]
    if source == 'use':
        rows = m.seed_content.choices(m, db, p, owned=True, usable=True)
        owned = m.owned_life_items(db, p)
        rows += [(m.QUALITY_RECIPES[k]['name'] + f" ×{sum(r.qty for r in v)}", k) for k, v in owned.items() if v]
        return rows
    if source == 'ore':
        return m.ore_choice_rows(db, p)
    if source == 'resource':
        return [row for row in m.seed_content.choices(m, db, p, gather_only=True) if row[1] not in m.task_queue.ores()]
    if source == 'sell':
        stock = m.seed_content.stock(m, db, p)
        rows = [(k, n, m.qol.sell_price(m, k)) for k, n in stock.items() if n > 0 and m.qol.sell_price(m, k)]
        rows.sort(key=lambda r: -r[1] * r[2])
        return [(f'{m.resource_name(k)} ×{n} — {n * price} SC', k) for k, n, price in rows]
    if source == 'owned':
        stock = m.seed_content.stock(m, db, p)
        return [(f'{m.resource_name(k)} ×{n}', k) for k, n in sorted(stock.items(), key=lambda kv: -kv[1]) if n > 0 and k in m.seed_content.ACTIVE]
    if source == 'order':
        clock = m.world_clock(db, p.channel_id)
        orders = m.available_production_orders(p.channel_id, clock['day'], m.society_tier_index(m.society(db, p.channel_id)))
        return [(data['name'], key) for key, data in orders]
    if source == 'player':
        found = m._discord_player_autocomplete({'member': {'user': {'id': uid}}, 'data': {'name': 'social'}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source == 'title':
        rows = db.execute(m.select(m.PlayerTitle).where(m.PlayerTitle.channel_id == p.channel_id,
                                                        m.PlayerTitle.canonical_uid == p.twitch_uid)).scalars().all()
        return [(m.TITLE_DEFS.get(r.title_key, r.title_key.replace('_', ' ').title()), r.title_key) for r in rows]
    if source.startswith('field:'):
        _, command, field = source.split(':', 2)
        return [(c['name'], c['value']) for f in m.DISCORD_OPTION_SCHEMA.get(command, []) if f['name'] == field for c in f.get('choices', [])]
    if source == 'buy':
        stock = m.seed_content.stock(m, db, p)
        rows = [(k, d) for k, d in m.SEED_INDUSTRIES.items() if d.get('buy', 0) > 0]
        rows.sort(key=lambda kv: (kv[1].get('category', 'legacy') != 'seed', m.market_item_label(kv[0])))
        return [(f"{m.market_item_label(k)} — {d['buy']} SC · you have {stock.get(k, 0)}", k) for k, d in rows]
    if source == 'gear':
        found = m._discord_gear_autocomplete({'member': {'user': {'id': uid}}, 'data': {}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source == 'station':
        return list(m.workbench.station_rows(wb.Context(m, db, p), ''))
    if source == 'player_name':
        found = m._discord_player_autocomplete({'member': {'user': {'id': uid}}, 'data': {'name': 'linklookup'}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source.startswith('choices:'):
        command = source.split(':', 1)[1]
        return [(c['name'], c['value']) for c in m.DISCORD_OPTION_SCHEMA[command][0]['choices']]
    return []


PAGE = 23   # dropdown rows per page, leaving room for Previous / Next


def pick_view(m, db, p, owner, key, page=1):
    item = LEAVES[key]
    everything = choices(m, db, p, item['pick'], owner)
    pages = max(1, -(-len(everything) // PAGE)) if len(everything) > 25 else 1
    page = max(1, min(page, pages))
    rows = everything[:25] if pages == 1 else everything[(page - 1) * PAGE:page * PAGE]
    area = PARENT.get(key, 'home')
    text = f"{item['emoji']} {item['label'].upper()}\n{item['hint'].capitalize() or 'Choose one.'}"
    if not rows:
        empty = {'food': 'You have no food. Harvest, gather or craft some first.', 'use': 'You own nothing usable yet.',
                 'sell': 'You have nothing Seed Industries buys.', 'player': 'No other citizens yet.',
                 'title': 'You have not unlocked a title yet.', 'order': 'No production orders today.'}
        return text + '\n\n' + empty.get(item['pick'], 'Nothing to choose from right now.'), [nav(owner, area)]
    options = [ui.option(label, value) for label, value in rows]
    if pages > 1:
        text += f'\nPage {page} of {pages}.'
        if page > 1:
            options.insert(0, ui.option(f'◀ Previous page ({page - 1}/{pages})', f'__page:{page - 1}'))
        if page < pages:
            options.append(ui.option(f'Next page ({page + 1}/{pages}) ▶', f'__page:{page + 1}'))
    menu = ui.select(ui.cid(owner, 'mp', key), 'Choose…' if pages == 1 else f'Choose… (page {page}/{pages})', options)
    return text, [menu, ui.row(ui.button('Back: ' + AREAS[area][1], ui.cid(owner, 'mn', area), emoji='◀️'),
                               ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))]


def options_for(key, value=None):
    item = LEAVES[key]
    options = dict(item['opts'])
    if value is not None and item.get('option'):
        options[item['option']] = value
    return item['cmd'], options


# ---------------------------------------------------------------- navigation (spends nothing)

def navigate(m, db, p, owner, verb, args, values, name):
    """Handle mn/mv/mk/mp controls. Returns message data, or None when the choice must run as an action."""
    if verb == 'mn':
        area = args[0] if args and args[0] in AREAS else 'home'
        if area == 'recent':
            actions = m.extras.recent(db, p.channel_id, p.twitch_uid)
            text = '🔁 RECENT ACTIONS\nTap one to do it again. Each button works once; the result brings fresh buttons.\n\n' + (
                '\n'.join(f'• {a.label} · <t:{int(m.as_utc(a.created_at).timestamp())}:R>' for a in actions) or 'Nothing yet. Actions you take appear here.')
            return ui.message(m, text, ui.recent_components(m, db, p, owner), 'menu')
        return ui.message(m, area_text(m, db, p, area), area_components(m, owner, area), 'menu')
    key = args[0] if args else ''
    if key not in LEAVES:
        return ui.message(m, 'That button is no longer available. Here is the menu.', area_components(m, owner, 'home'), 'menu')
    item = LEAVES[key]
    area = PARENT.get(key, 'home')
    if verb == 'mv':
        command, options = options_for(key)
        return show(m, db, p, owner, command, options, area, name, key)
    if verb == 'mk':
        text, rows = pick_view(m, db, p, owner, key)
        return ui.message(m, text, rows, 'menu')
    if verb == 'mp' and values and str(values[0]).startswith('__page:'):
        text, rows = pick_view(m, db, p, owner, key, int(values[0].split(':', 1)[1] or 1))
        return ui.message(m, text, rows, 'menu')
    if verb == 'ma':
        return amount_view(m, db, p, owner, key, args[1] if len(args) > 1 else '')
    if verb == 'mp':
        value = values[0] if values else ''
        then = item.get('then')
        if then == 'amount':
            return amount_view(m, db, p, owner, key, value)
        if then == 'view':
            command, options = options_for(key, value)
            return show(m, db, p, owner, command, options, area, name, key)
        if then == 'confirm':
            ticket = ui.issue(m, owner, {'do': 'cmd', 'leaf': key, 'value': value})
            label = dict((v, l) for l, v in choices(m, db, p, item['pick'], owner)).get(value, value)
            text = f"{item['emoji']} CONFIRM\n{item['label'].rstrip('…')} **{label}**?\nNothing happens until you press Confirm."
            later = None
            if key == 'sell':
                later = ui.button('Sell it after my queue', ui.cid(owner, 't', ui.issue(m, owner, {'do': 'sellstep', 'item': value})), emoji='🗺️')
            return ui.message(m, text, [ui.row(ui.button('Confirm', ui.cid(owner, 't', ticket), style=3, emoji='✔️'), later,
                                               ui.button('Back', ui.cid(owner, 'mk', key), emoji='◀️'),
                                               ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))], 'menu')
        if then == 'panel':
            if item['pick'] == 'ore':
                command, options = 'mine', {'ore': value}
                return show(m, db, p, owner, command, options, area, name, key)
            text = m._discord_call_internal('catalog', owner, name, {'item': value}, '')
            return reply(m, text, 'catalog', ui.work_components(m, owner, 'gather:' + value) + [nav(owner, area)])
        if then == 'uses':
            text, rows = m.extras.uses_text(m, db, p, value)
            return ui.message(m, text, ui.uses_components(owner, rows), 'catalog')
        if then == 'social':
            label = dict((v, l) for l, v in choices(m, db, p, 'player', owner)).get(value, 'that citizen')
            buttons = [ui.button(LEAVES['s_' + a]['label'], ui.cid(owner, 't', ui.issue(m, owner, {'do': 'cmd', 'leaf': 's_' + a, 'value': value})),
                                 style=3, emoji=LEAVES['s_' + a]['emoji']) for a, _, _ in SOCIAL]
            text = f'🤝 WITH {label.upper()}\nPick an activity. Each one builds your relationship and restores Social.'
            return ui.message(m, text, [ui.row(*buttons[:5]), ui.row(*buttons[5:]), nav(owner, 'social')], 'menu')
        return None   # 'do': run it as an action
    return None


AMOUNTS = (1, 5, 10, 25)


def amount_view(m, db, p, owner, key, value):
    """How many? Buttons for 1, 5, 10, 25, All (when selling) and a custom amount."""
    item = LEAVES[key]
    command, options = options_for(key, value)
    label = dict((v, l) for l, v in choices(m, db, p, item['pick'], owner)).get(value) or m.resource_name(value)
    selling = options.get('action') == 'sell'
    have = (getattr(p, value, 0) if command == 'market' else m.material_amount(db, p, value)) if selling else 0
    buttons = []
    for n in AMOUNTS:
        if selling and n > have:
            continue
        ticket = ui.issue(m, owner, {'do': 'cmd', 'leaf': key, 'value': value, 'amount': n})
        buttons.append(ui.button(f'{"Sell" if selling else "Buy"} {n}', ui.cid(owner, 't', ticket), style=3, emoji=item['emoji']))
    if selling and have and have not in AMOUNTS:
        ticket = ui.issue(m, owner, {'do': 'cmd', 'leaf': key, 'value': value, 'amount': have})
        buttons.append(ui.button(f'Sell all {have}', ui.cid(owner, 't', ticket), style=3, emoji=item['emoji']))
    other = ui.button('Other amount…', ui.cid(owner, 'mo', key, value), emoji='✏️')
    text = f"{item['emoji']} {item['label'].rstrip('…').upper()}\n**{label}**\nHow many? Each button works once." + (
        f'\nYou have {have}.' if selling else '')
    if selling and not have:
        text += '\nYou have none of this to sell.'
    return ui.message(m, text, [ui.row(*buttons[:5]), ui.row(other, ui.button('Back', ui.cid(owner, 'mk', key), emoji='◀️'),
                                                            ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))], 'menu')


def modal(owner, key, args=()):
    """The pop-up form for a leaf (response type 9), or None."""
    item = LEAVES.get(key)
    if item is None:
        return None
    if item.get('then') == 'amount':
        value = args[0] if args else ''
        return ui.modal(ui.cid(owner, 'md', key, value), 'How many?', 'Amount (1–100)', 'e.g. 12', 1, 3)
    if item['kind'] != 'modal':
        return None
    title, label, placeholder = item['modal']
    return ui.modal(ui.cid(owner, 'md', key), title, label, placeholder, 1, item.get('max_length', 60))


def submit(m, db, p, owner, name, key, args, value):
    """A submitted form: message data to show, or a {'do': ...} action to run once."""
    item = LEAVES.get(key)
    if item is None:
        return None
    if item.get('then') == 'amount':
        if not value.isdigit() or not 1 <= int(value) <= 100:
            return ui.message(m, '✏️ Enter a whole number from 1 to 100. Nothing was spent.', [nav(owner, PARENT.get(key, 'home'))], 'menu')
        return {'do': 'cmd', 'leaf': key, 'value': args[0] if args else '', 'amount': int(value)}
    command, options = options_for(key, value)
    if key == 'find':
        return ui.message(m, m.extras.find_text(m, value[:60]), ui.find_components(m, owner, value[:60]), 'find')
    if item['kind'] == 'modal' and command in {'inventory'}:
        return show(m, db, p, owner, command, options, PARENT.get(key, 'home'), name, key)
    return {'do': 'cmd', 'leaf': key, 'value': value}


def _denied(m, command):
    if command not in MOD_COMMANDS:
        return ''
    if command == 'linklookup':
        return '' if ui.is_owner(m) else '⛔ Owner access is required for linked-account lookup.'
    return '' if ui.is_moderator(m) else '⛔ Moderator access is required for this tool.'


def show(m, db, p, owner, command, options, area, name, key=''):
    """Run a view command and show it with its own panel (if any) and this area's buttons."""
    denied = _denied(m, m.discord_legacy_route(command, options)[0])
    if denied:
        return ui.message(m, denied, [nav(owner, area)], 'moderator')
    text = m._discord_call_internal(command, owner, name, options, '')
    legacy, legacy_options = m.discord_legacy_route(command, options)
    panel = ui.slash_panel(m, legacy, owner, name, legacy_options, text)
    if panel is not None:
        rows = [r for r in panel.get('components', []) if r.get('components')]
        panel['components'] = rows[:4] + [nav(owner, area)]
        return panel
    return reply(m, text, legacy, grid(m, owner, children_of(m, area), rows=3) + [nav(owner, area)])


# ---------------------------------------------------------------- actions (one-time tickets)

def run(m, uid, name, action, token=''):
    """Run a menu action; returns message data with the result and the area's buttons again."""
    if 'raw' in action:
        command, options = action['raw']
        area = COMMAND_AREA.get(m.discord_legacy_route(command, options)[0], 'home')
    else:
        key = action['leaf']
        command, options = options_for(key, action.get('value'))
        if action.get('amount'):
            options['amount'] = int(action['amount'])
        area = PARENT.get(key, 'home')
        if key.startswith('s_'):
            area = 'social'
    legacy, legacy_options = m.discord_legacy_route(command, options)
    denied = _denied(m, legacy)
    if denied:
        return reply(m, denied, 'moderator', [nav(uid, area) or ui.row(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))])
    text = m._discord_call_internal(command, uid, name, options, 'menu-' + (token or secrets.token_hex(8)))
    panel = ui.slash_panel(m, legacy, uid, name, legacy_options, text)
    if panel is not None:
        rows = [r for r in panel.get('components', []) if r.get('components')]
        panel['components'] = rows[:4] + [nav(uid, area) or ui.row(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))]
        return panel
    rows = grid(m, uid, children_of(m, area), rows=3) + [nav(uid, area) or ui.row(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))]
    if legacy == 'seedindustries' and legacy_options.get('action') in {'sellall'} and 'sold' in text:
        rows = [ui.row(ui.button('Undo sale (60s)', ui.cid(uid, 't', ui.issue(m, uid, {'do': 'undo'})), style=4, emoji='↩️'),
                       ui.button('Sell another', ui.cid(uid, 'mk', 'sell'), emoji='🏷️'), ui.button('Auto-sell', ui.cid(uid, 'av'), emoji='🧹')), rows[-1]]
    return reply(m, text, legacy, rows)


def after_command(m, command, options, uid):
    """The button row added under every slash command reply: Again, its area, and Menu."""
    legacy, legacy_options = m.discord_legacy_route(command, options)
    buttons = []
    if legacy in REPEATABLE and not (legacy == 'eat' and not legacy_options.get('food')) and not (legacy == 'use' and not legacy_options.get('item')):
        ticket = ui.issue(m, uid, {'do': 'cmd', 'raw': [command, dict(options or {})]})
        buttons.append(ui.button('Again', ui.cid(uid, 't', ticket), style=3, emoji='🔁'))
    if legacy == 'seedindustries' and legacy_options.get('action') == 'sellall':
        buttons.append(ui.button('Undo sale (60s)', ui.cid(uid, 't', ui.issue(m, uid, {'do': 'undo'})), style=4, emoji='↩️'))
    area = COMMAND_AREA.get(legacy, 'home')
    if area != 'home':
        emoji, title, _, _ = AREAS[area]
        buttons.append(ui.button(title, ui.cid(uid, 'mn', area), emoji=emoji))
    buttons.append(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))
    return ui.row(*buttons)


def after_rows(m, command, options, uid, room=2):
    """Rows under a slash reply: the area's most-used buttons, then Again / area / Menu."""
    last = after_command(m, command, options, uid)
    if room < 2:
        return [last]
    legacy = m.discord_legacy_route(command, options)[0]
    area = COMMAND_AREA.get(legacy, 'home')
    keys = [k for k in children_of(m, area) if k not in MOD_AREAS and not (k in LEAVES and LEAVES[k]['cmd'] == legacy and LEAVES[k]['kind'] != 'pick')]
    quick = grid(m, uid, keys[:5], rows=1)
    return quick + [last]


def home_text(m, uid, name):
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', uid, name)[1]
        text = area_text(m, db, p, 'home')
        db.commit()
        return text
