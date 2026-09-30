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
             ['status', 'seedling', 'inbox', 'recent', 'find', 'life', 'work', 'craft', 'queue', 'bag', 'trade', 'world', 'community', 'me', 'settings', 'help',
              'account', 'mod']),
    'recent': ('🔁', 'Recent actions', 'Your last ten actions. Tap one to do it again.', []),
    'life': ('❤️', 'Life & Recovery', 'Keep Energy, Nutrition, Social and Comfort up so work never stops.',
             ['relax', 'sleep', 'eat', 'eatfull', 'recover', 'games', 'walk', 'hobby', 'meal', 'social', 'needs', 'cooldowns']),
    'social': ('🤝', 'Social', 'Spend time with other citizens.', ['friend', 'recreation', 'me_relationships']),
    'work': ('⛏️', 'Work', 'Gather and mine for materials, or do your trade. Each success gives items and practice.',
             ['gather', 'mine', 'w_rare', 'farming', 'science', 'logistics', 'frontier', 'repair', 'gearrepair', 'training', 'trainskill']),
    'farming': ('🌾', 'Farming', 'Tend, harvest and water the fields.', ['w_farm_tend', 'w_farm_harvest', 'w_farm_irrigate', 'w_farm_hydroponics']),
    'science': ('🔬', 'Research', 'Scans and research.', ['w_scan', 'w_research', 'w_field_analysis']),
    'logistics': ('📦', 'Logistics', 'Cargo, deliveries and the spaceport.', ['w_cargo', 'w_delivery', 'w_spaceport', 'w_expedite']),
    'frontier': ('🧭', 'Frontier', 'Scouting and surveys past the wall.', ['w_scout', 'w_survey']),
    'craft': ('🛠️', 'Craft', 'Open the Workbench (every category), what is ready now, your favourites or your goal.',
              ['workbench', 'ready', 'favs', 'goal', 'stations']),
    'stations': ('🏭', 'Workshops', 'Workstations and personal tiers. Unlock a station once, or own its machine.',
                 ['workshop', 'unlock', 'catalogcat']),
    'queue': ('⏱️', 'Queue', 'Your automatic task queue. Check it, repeat it or stop it.',
              ['qstatus', 'qdetails', 'plan', 'repeat', 'cancel', 'clearnext']),
    'bag': ('🎒', 'Bag', 'Everything you own. Look through it, use it, or see what it makes. Selling is under Trade.',
            ['inventory', 'inv_views', 'search', 'use', 'uses', 'autosell', 'catalog']),
    'trade': ('🪙', 'Trade', 'Buy and sell with Seed Industries, production orders, market work, and your home and business.',
              ['market', 'buy', 'sellsome', 'sell', 'clearout', 'undo', 'browse', 'starters', 'orders', 'fulfill', 'prices', 'commerce', 'analyze', 'property']),
    'property': ('🏠', 'Home & Business', 'Your Habitat and your company.', ['habitat', 'homeup', 'business', 'bstart', 'bwork', 'bcontract', 'binvest']),
    'world': ('🌎', 'World', 'Avesta, New Eridian, events, holidays and news.',
              ['wd_overview', 'wd_conditions', 'wd_society_progress', 'wd_event', 'wd_leaderboard', 'wd_more']),
    'community': ('🎪', 'Community', 'Vote on what the colony does next, join the stream challenge, climb the season and collect trophies.',
                  ['c_vote', 'c_vote_pick', 'c_challenge', 'c_season', 'c_season_more', 'c_hat', 'c_trophies', 'c_trophy_groups', 'c_badge']),
    'me': ('👤', 'Me', 'Your citizen. Profile, skills, progress and personal choices.',
           ['me_overview', 'me_skills', 'me_daily', 'me_achievements', 'choices', 'me_more']),
    'choices': ('🧭', 'Choices', 'Job, district, shift, delivery partner, title, specialization and display style.',
                ['job', 'district', 'shift', 'duck', 'title', 'specialize', 'display_compact', 'display_detailed']),
    'settings': ('⚙️', 'Settings', 'How queue alerts and notifications reach you, and whether queues recover by themselves.',
                 ['alerts', 'popups', 'auto_on', 'auto_off']),
    'help': ('📖', 'Help', 'What to do next, a guide for any goal, search, and the handbook.', ['guide', 'guidegoal', 'find', 'h_topics']),
    'seedling': ('🌱', 'My Seedling', 'Your Seedling lives its own day: mood, thoughts, schedule, diary and autonomy.',
                 ['sl_view', 'sl_decide', 'sl_diary', 'sl_schedule', 'sl_custom', 'sl_on', 'sl_off']),
    'account': ('🔗', 'Account', 'Create your citizen, or link your Twitch citizen: type !link in Twitch chat, then enter the code here.',
                ['start', 'link']),
    'mod': ('🛡️', 'Moderator', 'Events, the moderator log, account lookups and the channel panels. Moderators only.',
            ['m_eventstart', 'm_eventstop', 'm_chalstart', 'm_chalstop', 'm_live', 'm_recap', 'm_recappost', 'm_modlog', 'm_lookup', 'm_guidepanels',
             'm_menupanel', 'h_moderator']),
}
# Areas only moderators see on the Home screen.
MOD_AREAS = {'mod'}
# Commands a menu button may only run for moderators (linklookup: owners).
MOD_COMMANDS = {'eventstart', 'eventstop', 'modlog', 'guidepanels', 'menupanel', 'linklookup',
                'challengestart', 'challengestop', 'liveon', 'liveoff', 'liveauto', 'recappreview', 'recappost'}

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
# Craft categories are all in the Workbench's category dropdown (one place instead of fifteen buttons).
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
leaf('bstart', 'Start business', '🏗️', 'modal', 'business', {'action': 'start'}, modal=('Start a business', 'Business name', 'e.g. Rocky Repairs'),
     option='name', max_length=30, hint='found your company (costs SC)')
leaf('starters', 'Starter routes', '🧭', 'view', 'seedindustries', {'action': 'starters'}, hint='what to buy for each skill')
leaf('orders', 'Orders', '📋', 'view', 'seedindustries', {'action': 'orders'}, hint="today's production orders")
leaf('fulfill', 'Deliver order', '📦', 'pick', 'seedindustries', {'action': 'fulfill'}, pick='order', then='confirm', option='item',
     hint='hand in a production order')
leaf('prices', "Today's demand", '📈', 'view', 'market', {'action': 'view'}, hint='two materials Seed Industries pays extra for today')
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
# My Seedling
leaf('sl_view', 'Overview', '🌱', 'view', 'seedling', hint='mood, thought, where it is and what it is doing')
leaf('sl_decide', 'Let it decide', '🎲', 'do', 'seedlingstep', hint='your Seedling picks its next step itself, right now')
leaf('sl_diary', 'Diary', '📓', 'view', 'seedling', {'section': 'diary'}, hint='what it did while you were away')
leaf('sl_schedule', 'Schedule preset', '🗓️', 'pick', 'seedling', pick='field:seedling:schedule', then='do', option='schedule',
     hint='balanced, workaholic, night owl, socialite or homebody')
leaf('sl_custom', 'Custom schedule', '🧩', 'nav', nav=('lp',), hint='choose Work, Free time, Social or Sleep for each phase')
leaf('sl_on', 'Autonomy on', '🌱', 'do', 'seedling', {'autonomy': 'on'}, hint='it lives its schedule while you are away')
leaf('sl_off', 'Autonomy off', '✋', 'do', 'seedling', {'autonomy': 'off'}, hint='it waits for you')
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
leaf('m_guidepanels', 'Post guide panels', '📖', 'do', 'guidepanels', hint='the how-to-play panels, in this channel')
leaf('m_menupanel', 'Post game panel', '🎛️', 'do', 'menupanel', hint='a button panel anyone can press to open their menu')
leaf('m_chalstart', 'Start stream challenge', '⚡', 'pick', 'challengestart', pick='field:mod:challenge', then='confirm', option='challenge',
     hint='a 5–10 minute shared goal for chat (normally automatic while live)')
leaf('m_chalstop', 'Stop stream challenge', '🛑', 'do', 'challengestop', style=4, hint='call off the running challenge, no rewards or penalties')
leaf('m_live', 'Stream live…', '📡', 'pick', 'liveon', pick='leaves:m_liveon,m_liveoff,m_liveauto', then='leaf', hint='on, off or automatic (from chat activity)')
leaf('m_liveon', 'Stream is live', '🔴', 'do', 'liveon', hint='stream challenges start every ~25 minutes')
leaf('m_liveoff', 'Stream is offline', '⚫', 'do', 'liveoff', hint='no stream challenges')
leaf('m_liveauto', 'Automatic', '🔁', 'do', 'liveauto', hint='live when people use Twitch commands')
leaf('m_recap', 'Weekly recap preview', '📰', 'view', 'recappreview', hint='what Sunday\'s post will say')
leaf('m_recappost', 'Post weekly recap now', '📣', 'do', 'recappost', hint='posts to the recap channel')
leaf('h_moderator', 'Moderator help', '📖', 'view', 'seed', {'topic': 'moderator'}, hint='')
# Community
leaf('c_vote', 'Colony vote', '🗳️', 'view', 'vote', hint="today's ballot and how it is going")
leaf('c_vote_pick', 'Cast your vote', '✅', 'pick', 'vote', pick='ballot', then='do', option='choice', hint='pick a project or festival; change it any time today')
leaf('c_challenge', 'Stream challenge', '⚡', 'view', 'challenge', hint='the live shared goal and how to help')
leaf('c_season', 'Season', '🏁', 'view', 'season', hint='your season points, rank and next reward')
leaf('c_season_more', 'Season more…', '🏆', 'pick', 'season', pick='leaves:c_season_top,c_season_rewards,c_season_story,c_hats', then='leaf',
     hint='leaderboard, rewards, story and hats')
leaf('c_season_top', 'Leaderboard', '🏆', 'view', 'season', {'section': 'top'}, hint='the top ten this season')
leaf('c_season_rewards', 'Rewards', '🎁', 'view', 'season', {'section': 'rewards'}, hint='titles, hats and milestones')
leaf('c_season_story', 'Story so far', '📖', 'view', 'season', {'section': 'story'}, hint='one chapter a week')
leaf('c_hats', 'My hats', '🎩', 'view', 'season', {'section': 'hats'}, hint='cosmetic hats you own')
leaf('c_hat', 'Wear a hat', '🎩', 'pick', 'season', pick='hats', then='do', option='hat', hint='your Seedling wears it on the stream map')
leaf('c_trophies', 'Trophies', '🏅', 'view', 'trophies', hint='collections and trophies, closest first')
leaf('c_trophy_groups', 'Trophy group…', '🗂️', 'pick', 'trophies', pick='field:trophies:group', then='view', option='group', hint='one group in full')
leaf('c_badge', 'Pin a badge', '📌', 'pick', 'trophies', pick='badges', then='do', option='badge', hint='shows next to your name on the stream map')
for _topic, _label in [('start', 'Start here'), ('character', 'Character'), ('property', 'Home & crafting'), ('life', 'Life'),
                       ('production', 'Work'), ('operations', 'Logistics'), ('society', 'Society'), ('other', 'Other'), ('terms', 'Terms')]:
    leaf('h_' + _topic, _label, '📖', 'view', 'seed', {'topic': _topic}, hint='')

# Grouped choices: one dropdown instead of a row of similar buttons. 'leaves:' lists views to pick from.
leaf('inv_views', 'Sort & filter…', '🗂️', 'pick', 'inventory', pick='leaves:by_value,by_name,by_category,favitems,sellable,ready_items,gear', then='leaf',
     hint='by value, name or category; favourites, sellable, ready-recipe items or gear')
leaf('wd_more', 'More…', '📰', 'pick', 'world', pick='leaves:wd_society,wd_project,wd_story,wd_bulletin,wd_rumor,wd_market,wd_holidays,wd_event_history',
     then='leaf', hint='society, project, story, bulletin, rumor, market, holidays and past events')
leaf('me_more', 'More…', '📓', 'pick', 'me', pick='leaves:me_collection,me_bonuses,me_traits,me_relationships,me_journal,me_titles,me_tutorial',
     then='leaf', hint='collection, bonuses, traits, relationships, journal, titles and tutorial')
leaf('h_topics', 'Handbook', '📚', 'pick', 'seed', pick='leaves:h_start,h_character,h_property,h_life,h_production,h_operations,h_society,h_other,h_terms,me_tutorial,wd_holidays',
     then='leaf', hint='every topic of the handbook')
leaf('alerts', 'Queue alerts', '🔔', 'pick', 'settings', pick='alerts', then='do', option='alerts', hint='how you hear that a queue paused or finished')
leaf('popups', 'Notifications', '📬', 'pick', 'settings', pick='popups', then='do', option='popups', hint='what pops up for you after commands')

PARENT = {}
for _area, (_, _, _, _children) in AREAS.items():
    for _child in _children:
        PARENT.setdefault(_child, _area)
PARENT.update({'s_' + _action: 'social' for _action, _, _ in SOCIAL})   # shown after choosing a citizen
# Views inside a grouped dropdown belong to that dropdown's area; the single-mode setting buttons live on in Settings' dropdowns.
for _key, _item in list(LEAVES.items()):
    if str(_item.get('pick', '')).startswith('leaves:'):
        for _inner in _item['pick'].split(':', 1)[1].split(','):
            PARENT.setdefault(_inner, PARENT.get(_key, 'home'))
for _key in LEAVES:
    if _key.startswith(('alerts_', 'popups_')):
        PARENT.setdefault(_key, 'settings')
# The area a slash command belongs to, for the "back to area" button on replies.
COMMAND_AREA = {}
for _key, _leaf in LEAVES.items():
    if _leaf['cmd']:
        COMMAND_AREA.setdefault(_leaf['cmd'], PARENT.get(_key, 'home'))
COMMAND_AREA.update({'seedling': 'seedling', 'seedlingstep': 'seedling', 'link': 'account', 'start': 'account', 'eventstart': 'mod', 'eventstop': 'mod', 'modlog': 'mod',
                     'linklookup': 'mod', 'guidepanels': 'mod', 'menupanel': 'mod', 'eatfull': 'life', 'undo': 'bag', 'find': 'help', 'make': 'craft', 'workshop': 'craft', 'catalog': 'craft', 'queue': 'queue', 'mine': 'work', 'gather': 'work',
                     'farm': 'work', 'scan': 'work', 'rare': 'work', 'research': 'work', 'cargo': 'work', 'delivery': 'work',
                     'spaceport': 'work', 'explore': 'work', 'repair': 'work', 'training': 'work', 'society': 'world',
                     'event': 'world', 'holiday': 'world', 'progress': 'me', 'seed': 'help', 'guide': 'help',
                     'eat': 'life', 'relax': 'life', 'sleep': 'life', 'games': 'life', 'walk': 'life', 'hobby': 'life',
                     'meal': 'life', 'recover': 'life', 'use': 'bag', 'inventory': 'bag', 'status': 'home', 'settings': 'settings'})
# Slash commands whose replies offer "Again" (they perform a task and can simply be repeated).
REPEATABLE = {'eatfull', 'relax', 'sleep', 'games', 'walk', 'meal', 'recover', 'farm', 'scan', 'rare', 'research', 'cargo', 'delivery',
              'spaceport', 'explore', 'repair', 'hobby', 'eat', 'use'}


# ---------------------------------------------------------------- what this citizen can do right now

class Ctx:
    """What one citizen has and can do, read once per screen. Every rule mirrors the check the command itself
    makes, so a hidden button is one the game would refuse, and it reappears as soon as the citizen can use it."""
    def __init__(self, m, db, p, uid):
        self.m, self.db, self.p, self.uid, self._cache = m, db, p, uid, {}

    def get(self, name, make):
        if name not in self._cache:
            try:
                self._cache[name] = make()
            except Exception:
                self._cache[name] = True    # if a check itself fails, show the button and let the command explain
        return self._cache[name]

    def equipment(self, action, mode=''):
        from . import task_yields
        key = task_yields.EQUIPMENT.get((action, mode))
        return self.get('eq:' + str(key), lambda: self.m.equipment_count(self.db, self.p, key) > 0)

    def has(self, source):
        return self.get('has:' + source, lambda: bool(choices(self.m, self.db, self.p, source, self.uid)))

    def queue(self):
        return self.get('queue', lambda: self.db.get(self.m.task_queue.TaskQueue, (self.p.channel_id, self.p.twitch_uid)))

    def prefs(self):
        return self.get('prefs', lambda: self.m.qol.prefs(self.db, self.p.channel_id, self.p.twitch_uid))

    def business(self):
        return self.get('business', lambda: self.m.business_for(self.db, self.p) is not None)

    def autonomy_on(self):
        def read():
            row = self.m.autonomy.row(self.db, self.p.channel_id, self.p.twitch_uid)
            return row is None or bool(row.enabled)
        return self.get('autonomy', read)

    def sale_to_undo(self):
        def read():
            import json
            from datetime import datetime
            row = self.m.extras.row(self.db, self.p.channel_id, self.p.twitch_uid)
            sale = json.loads(row.last_sale) if row is not None and row.last_sale else None
            return bool(sale) and (self.m.now() - self.m.as_utc(datetime.fromisoformat(sale['at']))).total_seconds() <= self.m.extras.UNDO_SECONDS
        return self.get('undo', read)

    def challenge_active(self):
        return self.get('challenge', lambda: self.m.live_events.active(self.m, self.db) is not None)

    def event_active(self):
        return self.get('event', lambda: bool(self.m.world(self.db, self.p.channel_id).active_event))

    def linked(self):
        def read():
            m, p = self.m, self.p
            return self.db.execute(m.select(m.AccountLink).where(m.AccountLink.channel_id == p.channel_id,
                                                                 m.AccountLink.twitch_uid == p.twitch_uid)).scalars().first() is not None
        return self.get('linked', read)


def _food(c):
    return c.get('food', lambda: any(r['qty'] > 0 for r in c.m.edible_inventory(c.db, c.p)))


def _queue_active(c):
    q = c.queue()
    return q is not None and q.state in c.m.task_queue.ACTIVE


def _planned(c):
    pref = c.prefs()
    return bool((pref is not None and pref.next_task) or c.get('steps', lambda: c.m.extras.playlist(c.db, c.p.channel_id, c.p.twitch_uid)))


# key -> (can the citizen use it now?, why not). Keys not listed are always available.
WHEN = {
    'eat': (lambda c: _food(c) or c.get('emergency', lambda: c.m.emergency_food_available(c.db, c.p)), 'you have no food'),
    'eatfull': (_food, 'you have no food'),
    'meal': (lambda c: c.p.crops > 0, 'needs 1 Pumpkin'),
    'recreation': (lambda c: c.get('rec', lambda: bool(c.m.owned_life_items(c.db, c.p).get('recreation_set'))), 'needs a Recreation Set'),
    'w_farm_hydroponics': (lambda c: c.equipment('water', 'hydroponics'), 'needs a Small Water Filter'),
    'w_field_analysis': (lambda c: c.equipment('research', 'field_analysis'), 'needs a Siro Sampler'),
    'w_survey': (lambda c: c.equipment('survey'), 'needs a Resource Scanner'),
    'analyze': (lambda c: c.equipment('market', 'analyze'), 'needs a Market Analyzer'),
    'w_delivery': (lambda c: c.p.cargo > 0, 'needs Cargo: Prepare cargo first'),
    'w_expedite': (lambda c: c.get('cell', lambda: c.m.material_amount(c.db, c.p, 'power_cell') > 0), 'needs a Power Cell'),
    'w_rare': (lambda c: c.m.lvl(c.m.skill_xp(c.p, 'extraction')) >= c.m.crafting_progression.RARE_LEVEL, 'needs Harvesting Lv 3'),
    'gearrepair': (lambda c: c.has('gear'), 'you have no quality gear'),
    'use': (lambda c: c.has('use'), 'you own nothing usable yet'),
    'sell': (lambda c: c.has('sell'), 'you have nothing Seed Industries buys'),
    'sellsome': (lambda c: c.has('sell'), 'you have nothing Seed Industries buys'),
    'clearout': (lambda c: c.has('sell'), 'you have nothing to sell'),
    'undo': (lambda c: c.sale_to_undo(), 'only for 60 seconds after a sale'),
    'fulfill': (lambda c: c.has('order'), 'no production orders today'),
    'uses': (lambda c: c.has('owned'), 'you own no materials yet'),
    'title': (lambda c: c.has('title'), 'no titles unlocked yet'),
    'bstart': (lambda c: not c.business(), 'you already own a business'),
    'bwork': (lambda c: c.business(), 'start a business first'),
    'bcontract': (lambda c: c.business(), 'start a business first'),
    'binvest': (lambda c: c.business(), 'start a business first'),
    'cancel': (_queue_active, 'no queue is running'),
    'repeat': (lambda c: c.queue() is not None and not _queue_active(c), 'no finished queue to repeat'),
    'clearnext': (_planned, 'nothing is planned after this queue'),
    'auto_on': (lambda c: not (c.prefs() is not None and c.prefs().autorecover), 'auto-recover is already on'),
    'auto_off': (lambda c: bool(c.prefs() is not None and c.prefs().autorecover), 'auto-recover is already off'),
    'sl_on': (lambda c: not c.autonomy_on(), 'autonomy is already on'),
    'sl_off': (lambda c: c.autonomy_on(), 'autonomy is already off'),
    'display_compact': (lambda c: c.m.player_preference(c.db, c.p).result_style != 'compact', 'already compact'),
    'display_detailed': (lambda c: c.m.player_preference(c.db, c.p).result_style == 'compact', 'already detailed'),
    'm_eventstart': (lambda c: not c.event_active(), 'an event is already running'),
    'm_eventstop': (lambda c: c.event_active(), 'no event is running'),
    'm_chalstart': (lambda c: not c.challenge_active(), 'a stream challenge is running'),
    'm_chalstop': (lambda c: c.challenge_active(), 'no stream challenge is running'),
    'c_hat': (lambda c: c.has('hats'), 'no cosmetic hats yet: reach Silver this season'),
    'c_badge': (lambda c: c.has('badges'), 'no trophies yet'),
    'link': (lambda c: not c.linked(), 'already linked'),
    'account': (lambda c: not c.linked(), 'already linked'),
}
# Toggles and one-way switches: the hidden side is just the current state, so it is not listed as unavailable.
TOGGLES = {'auto_on', 'auto_off', 'sl_on', 'sl_off', 'display_compact', 'display_detailed', 'bstart', 'm_eventstart', 'm_eventstop', 'link', 'account',
           'm_chalstart', 'm_chalstop'}


def can(ctx, key):
    rule = WHEN.get(key)
    if rule is None or ctx is None or ctx.p is None:
        return True
    return ctx.get('can:' + key, lambda: bool(rule[0](ctx)))


def context(m, uid, db=None, p=None):
    return Ctx(m, db, p, uid) if db is not None and p is not None else None


def with_context(m, uid, fn, name='Citizen'):
    """For callers without a session: open one, read what the citizen can do, and close it."""
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', uid, name)[1]
        result = fn(Ctx(m, db, p, uid))
        db.commit()
        return result


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


def children_of(m, area, ctx=None):
    """An area's buttons: moderator tools only for moderators, and (given a citizen) only what they can use now."""
    keys = AREAS[area][3]
    if area == 'home' and not ui.is_moderator(m):
        keys = [k for k in keys if k not in MOD_AREAS]
    return [k for k in keys if can(ctx, k)]


def unavailable(m, area, ctx):
    """(label, reason) for this area's buttons hidden right now, so nothing seems to vanish without a reason."""
    if ctx is None:
        return []
    out = []
    for k in AREAS[area][3]:
        if k in TOGGLES or k in MOD_AREAS or can(ctx, k):
            continue
        out.append((AREAS[k][1] if k in AREAS else LEAVES[k]['label'], WHEN[k][1]))
    return out


def area_text(m, db, p, area, ctx=None):
    emoji, title, text, _ = AREAS[area]
    ctx = ctx or context(m, p.twitch_uid if p is not None else '', db, p)
    children = children_of(m, area, ctx)
    lines = [f'{emoji} {title.upper()}', text, '']
    if area == 'home' and p is not None:
        life = m.life_state(db, p)
        lines = [f'{emoji} NEW ERIDIAN — {p.display_name}',
                 f'⚡ {life.energy} · 🍲 {life.nutrition} · 💬 {life.social} · 🛋️ {life.comfort} · 🪙 {p.sc} SC',
                 m.qol.queue_summary(m, db, p, 'discord')[0].split('\n')[0], '', text, '']
        path = m.onboarding.line(m, db, p, 'discord')
        if path:
            lines.insert(3, path.replace('🧭 First steps', '🧭 **First steps**') + ' · Help → What next? has the checklist')
    for key in children:
        if key in AREAS:
            e, t, d, _ = AREAS[key]
            lines.append(f'{e} **{t}** — {d}')
        else:
            item = LEAVES[key]
            if item['hint']:
                lines.append(f"{item['emoji']} **{item['label']}** — {item['hint']}")
    locked = unavailable(m, area, ctx)
    if locked:
        lines += ['', '🔒 Not available right now: ' + ' · '.join(f'{label} ({why})' for label, why in locked)]
    return '\n'.join(lines).rstrip()


def area_components(m, owner, area, ctx=None):
    rows = grid(m, owner, children_of(m, area, ctx))
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
    if source.startswith('leaves:'):
        return [(f"{LEAVES[k]['emoji']} {LEAVES[k]['label']}" + (f" — {LEAVES[k]['hint']}" if LEAVES[k]['hint'] else ''), k)
                for k in source.split(':', 1)[1].split(',') if k in LEAVES]
    if source == 'alerts':
        pref = m.qol.prefs(db, p.channel_id, p.twitch_uid)
        now = pref.alerts if pref is not None else 'mention'
        return [(f"{m.qol.ALERT_LABELS[k].capitalize()}{' (current)' if k == now else ''} — {d}", k) for k, d in m.qol.ALERT_MODES.items()]
    if source == 'popups':
        now = m.inbox.popup_mode(db, p.channel_id, p.twitch_uid)
        return [(f"{k.capitalize()}{' (current)' if k == now else ''} — {d}", k) for k, d in m.inbox.POPUP_MODES.items()]
    if source == 'ballot':
        import json
        row = m.votes.ballot(m, db)
        counts = m.votes.tally(db, row)
        return [(f"{i}. {m.votes.label(o)[0]} {m.votes.label(o)[1]} — {c} vote{'s' if c != 1 else ''}", str(i))
                for i, (o, c) in enumerate(zip(json.loads(row.options), counts), 1)]
    if source == 'hats':
        owned, worn = m.seasons.hats_of(db, p)
        return [(f"{m.seasons.HATS[h][0]} {m.seasons.HATS[h][1]}{' (wearing)' if h == worn else ''}", h) for h in owned if h in m.seasons.HATS] + \
            ([('💼 My job hat', 'job')] if owned else [])
    if source == 'badges':
        m.trophies._build(m)
        mine = m.trophies.owned(db, p)
        return [(f"{t['emoji']} {t['name']}", k) for k, t in m.trophies.TROPHIES.items() if k in mine]
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
        ctx = context(m, owner, db, p)
        return ui.message(m, area_text(m, db, p, area, ctx), area_components(m, owner, area, ctx), 'menu')
    key = args[0] if args else ''
    if key not in LEAVES:
        return ui.message(m, 'That button is no longer available. Here is the menu.', area_components(m, owner, 'home', context(m, owner, db, p)), 'menu')
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
        if then == 'leaf' and value in LEAVES and LEAVES[value]['kind'] == 'view':
            command, options = options_for(value)
            return show(m, db, p, owner, command, options, area, name, value)
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
    return reply(m, text, legacy, grid(m, owner, children_of(m, area, context(m, owner, db, p)), rows=3) + [nav(owner, area)])


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
    visible = with_context(m, uid, lambda c: children_of(m, area, c), name)
    rows = grid(m, uid, visible, rows=3) + [nav(uid, area) or ui.row(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))]
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
    visible = with_context(m, uid, lambda c: children_of(m, area, c))
    keys = [k for k in visible if k not in MOD_AREAS and not (k in LEAVES and LEAVES[k]['cmd'] == legacy and LEAVES[k]['kind'] != 'pick')]
    quick = grid(m, uid, keys[:5], rows=1)
    return quick + [last]


def home_text(m, uid, name):
    with m.SessionLocal() as db:
        p = m.player(db, m.DISCORD_WORLD_ID, 'discord', uid, name)[1]
        text = area_text(m, db, p, 'home')
        db.commit()
        return text
