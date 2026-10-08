"""Button menus for the whole game: one window with every area, then each area's actions.

`/menu` opens Home: a green Do this next button, then six areas (Work, Craft, Life, Bag & Shop, Society, You). An area
shows its 5-7 main buttons and one More button for everything else: less-used options under "Also here" and the
ones you cannot use yet under "Not yet", each with the reason and a How to get it button. Actions that need a
choice (which food, which ore, which citizen) open a dropdown first. After any action the result is shown with the
same area's buttons again, plus Back and Home, so the next step is always one tap away.

Every button runs the same command a slash command would (through the Discord
dispatcher), so rules, cooldowns and receipts are identical. Buttons that
spend something carry one-time tickets (see ui.issue); views and menus spend
nothing and carry their target in the custom_id:

  mn|<area>            open an area
  mn|<area>|more       open the area's More screen (generated from MORE and the availability rules)
  mv|<leaf>            run a view
  mk|<leaf>            open a leaf's choice list
  mp|<leaf>            a choice from that list (select value)
  ma|<leaf>|<value>    amount buttons for a chosen item (buy, sell)
  mo|<leaf>            a pop-up form (search, link code, business name, custom amount)

Buttons from older messages keep working: removed areas and merged leaves are listed in AREA_ALIAS and
LEAF_ALIAS, and every leaf an old one-time ticket can name stays in LEAVES (hidden from the screens).
"""
import secrets
from sqlalchemy import select
from . import runtime, ui, workbench as wb
from .db import SessionLocal
from .models import AccountLink, PlayerTitle

# Areas: key -> (emoji, title, description, main buttons). Children are area keys or leaf keys; the order is
# the button order. Everything else of an area is in MORE (see below). 16 areas; nothing is more than two taps
# below Home (Home > area > sub-area).
AREAS = {
    'home': ('🏠', 'New Eridian', 'Pick an area. Menus and views spend nothing; green buttons do their task once.',
             ['work', 'craft', 'life', 'trade', 'community', 'me', 'help', 'inbox', 'recent', 'mod']),
    'recent': ('🔁', 'Do again', 'Your last ten actions. Tap one to do it again.', []),
    'work': ('⛏️', 'Work', 'Gather and mine materials, farm, do other jobs, train your skills and run queues.',
             ['gather', 'mine', 'w_rare', 'farm', 'jobs', 'trainskill', 'queue']),
    'queue': ('⏱️', 'Queue', 'Work that runs by itself while you watch. Check it, plan it, repeat it or stop it.',
              ['qstatus', 'repeat', 'cancel', 'plan', 'clearnext', 'qdetails']),
    'craft': ('🛠️', 'Craft', 'Your goal walks you through every step; your shopping list plans several recipes at once. All recipes has every recipe.',
              ['goal', 'ready', 'workbench', 'shopping', 'favs']),
    'life': ('❤️', 'Life', 'Keep Energy, Nutrition, Social and Comfort up so work never stops.',
             ['recover', 'eat', 'eatfull', 'sleep', 'relax', 'games', 'friend', 'trick']),
    'trade': ('🎒', 'Bag & Shop', 'What you own, buying and selling with Seed Industries, orders, and your home and business.',
              ['inventory', 'use', 'buy', 'sell', 'orders', 'property']),
    'property': ('🏡', 'Home & business', 'Your home and your company.',
                 ['habitat', 'homeup', 'business', 'bstart', 'bwork', 'bcontract', 'binvest']),
    'community': ('🏘️', 'Society', 'Everything New Eridian does together: the active event, the vote, the stream challenge, the season, trophies and news.',
                  ['wd_event', 'c_challenge', 'c_vote', 'c_season', 'c_trophies', 'wd_overview']),
    'me': ('👤', 'You', 'Your citizen, your Seedling, how it looks and your settings.',
           ['me_overview', 'me_skills', 'me_daily', 'seedling', 'looks', 'choices', 'settings']),
    'seedling': ('🌱', 'My Seedling', 'Your Seedling lives its own day: mood, thoughts, schedule and diary.',
                 ['sl_view', 'sl_decide', 'sl_diary', 'sl_schedule', 'sl_auto']),
    'looks': ('🎨', 'Looks', 'How your Seedling looks on the stream map and how it talks. Purely cosmetic.',
              ['lk_view', 'lk_body', 'lk_clothes', 'lk_voice', 'c_hat', 'c_badge', 'title']),
    'choices': ('🧭', 'Job & role', 'Job, district, shift, delivery partner and specialization.',
                ['job', 'district', 'shift', 'duck', 'specialize']),
    'settings': ('⚙️', 'Settings', 'How alerts and pop-ups reach you, quiet hours, auto-recover, results, the activity feed, and your Twitch link.',
                 ['alerts', 'popups', 'quiet', 'auto', 'feed', 'results', 'link']),
    'help': ('📖', 'Help', 'What to do next, a guide for any goal, search, the handbook, and who made the game.',
             ['guide', 'guidegoal', 'find', 'h_topics', 'h_about']),
    'mod': ('🛡️', 'Moderator', 'Events, the moderator log, account lookups and the channel panels. Game owner only.',
            ['m_eventstart', 'm_eventstop', 'm_chalstart', 'm_chalstop', 'm_live', 'm_recap', 'm_recappost', 'm_feed', 'm_modlog', 'm_asklog', 'm_lookup', 'm_force',
             'm_guidepanels', 'm_menupanel', 'h_moderator']),
}
# The short line beside an area's button on Home (and on the area lists): what is inside.
BLURB = {'work': 'gather, mine, farm, train skills, queues', 'craft': 'your goal, recipes, shopping list',
         'life': 'eat, sleep, rest, friends', 'trade': 'what you own, buy, sell, your home', 'community': 'event, vote, season, trophies, news',
         'me': 'profile, Seedling, looks, settings', 'queue': 'check it, repeat it, stop it, plan what runs next',
         'property': 'your home and your business', 'seedling': 'mood, schedule, diary', 'looks': 'skin, hair, clothes, voice, hats, badges',
         'choices': 'job, district, shift, partner', 'settings': 'alerts, pop-ups, quiet hours, switches, Twitch link',
         'help': 'what to do next, guides, search, handbook',
         'recent': 'your last ten actions, tap one to repeat it', 'mod': 'events, logs, lookups, panels (owner only)'}
# The More screen of an area (generated; not an area of its own): the less-used buttons ("Also here"). A button
# in the area's main list or in MORE that the citizen cannot use right now moves to "Not yet" with its reason;
# switches (TOGGLES) just hide.
MORE = {
    'work': ['repair', 'gearrepair'],
    'craft': ['workshop', 'unlock', 'catalog', 'catalogcat'],
    'life': ['walk', 'hobby', 'meal', 'needs', 'cooldowns', 'recreation'],
    'trade': ['clearout', 'browse', 'starters', 'prices', 'commerce', 'uses', 'autosell', 'keep', 'fulfill', 'analyze'],
    'community': ['wd_conditions', 'wd_society_progress', 'wd_leaderboard', 'wd_more', 'c_season_more', 'c_trophy_groups'],
    'me': ['me_achievements', 'status', 'me_collection', 'me_bonuses', 'me_traits', 'me_relationships', 'me_journal', 'me_titles', 'me_tutorial'],
    'settings': ['start'],
}
# Lists of jobs: one dropdown-like screen of the leaves below (each with what it gives and a button). A job the
# citizen cannot do yet is not on the list; it is under Not yet in the area's More.
JOBS = {
    'farm': ['w_farm_tend', 'w_farm_harvest', 'w_farm_irrigate', 'w_farm_hydroponics'],
    'jobs': ['w_scan', 'w_research', 'w_field_analysis', 'w_cargo', 'w_delivery', 'w_spaceport', 'w_expedite', 'w_scout', 'w_survey'],
}
# Buttons on older messages (and the public game panel) for areas that no longer exist: area -> (verb, args).
AREA_ALIAS = {'farming': ('mk', ['farm']), 'science': ('mk', ['jobs']), 'logistics': ('mk', ['jobs']), 'frontier': ('mk', ['jobs']),
              'stations': ('mn', ['craft', 'more']), 'social': ('mk', ['friend']), 'bag': ('mv', ['inventory']), 'account': ('mn', ['settings'])}
# Leaves merged into another (or into a More screen): the old key opens the new place.
LEAF_ALIAS = {'training': ('mk', ['trainskill']), 'sellsome': ('mk', ['sell']), 'c_vote_pick': ('mv', ['c_vote']), 'me_more': ('mn', ['me', 'more'])}
# Leaves no screen lists any more: older buttons and tickets still name them, so they stay, but Find does not offer them.
HIDDEN = {'sellsome', 'c_vote_pick', 'me_more', 'auto_on', 'auto_off', 'feed_on', 'feed_off', 'display_compact', 'display_detailed',
          'sl_on', 'sl_off', 'sl_custom', 'quiet_off'}
# Areas only the game owner sees on the Home screen (moderator tools are owner-only).
MOD_AREAS = {'mod'}
# Leaves only owners see and can use (Force merge: the screens and its ticket check ownership again every time).
OWNER_ONLY = {'m_force'}
# Commands a menu button may only run for the game owner (the Discord IDs in DISCORD_OWNER_USER_IDS).
MOD_COMMANDS = {'eventstart', 'eventstop', 'modlog', 'asklog', 'guidepanels', 'menupanel', 'linklookup',
                'challengestart', 'challengestop', 'liveon', 'liveoff', 'liveauto', 'recappreview', 'recappost', 'feedhere', 'feedoff'}

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


leaf('status', 'Full status', '📊', 'view', 'status', hint='needs, queue, cooldowns and what to do next')
leaf('inbox', 'Notifications', '📬', 'view', 'inbox', hint='queue results, warnings and tips sent only to you')
leaf('qdetails', 'Queue rules', '📘', 'nav', nav=('qd',), hint='every requirement and rule for your queue')
# Life
leaf('relax', 'Relax', '🛋️', 'do', 'relax', hint='+25 Energy, +20 Comfort')
leaf('sleep', 'Sleep', '🛏️', 'do', 'sleep', hint='Energy and Comfort to 100 (long cooldown)')
leaf('eat', 'Eat', '🍲', 'pick', 'eat', pick='food', then='do', option='food', hint='choose a food you own')
leaf('games', 'Games', '🎲', 'do', 'games', hint='+25 Social')
leaf('walk', 'Walk', '🌿', 'do', 'walk', hint='Morale and exploration')
leaf('hobby', 'Hobby', '🎨', 'pick', 'hobby', pick='hobby', then='do', option='hobby', hint='practice a hobby')
leaf('meal', 'Share a meal', '🍲', 'do', 'meal', {'action': 'share'}, hint='1 Pumpkin: +25 Nutrition, +10 Social')
leaf('trick', 'Trick-or-treat', '🎃', 'do', 'trick', hint='Halloween: knock on a door for a treat or a trick, 5 times a day')
leaf('recover', 'Recover', '🩹', 'do', 'recover', hint='every recovery that is ready, at once')
leaf('eatfull', 'Eat until full', '🍽️', 'do', 'eatfull', hint='cheapest everyday food until Nutrition reaches 80')
leaf('needs', 'Needs', '❤️', 'view', 'me', {'section': 'life'}, hint='your needs and how to fix them')
leaf('cooldowns', 'Cooldowns', '⏱️', 'view', 'me', {'section': 'cooldowns'}, hint='what is ready and when')
# Work
leaf('mine', 'Mine', '⛏️', 'pick', 'mine', pick='ore', then='panel', hint='choose an ore; mine once or queue')
leaf('gather', 'Gather', '🌿', 'pick', 'gather', pick='resource', then='panel', hint='choose a material; gather once or queue')
WORK = [('farm_tend', 'Tend fields', '🌱'), ('farm_harvest', 'Harvest', '🎃'), ('farm_irrigate', 'Irrigate', '💧'),
        ('farm_hydroponics', 'Hydroponics', '🧪'), ('scan', 'Scan', '📡'), ('rare', 'Mine rare ore', '💎'), ('research', 'Research', '🔬'),
        ('field_analysis', 'Field analysis', '🧫'), ('cargo', 'Cargo', '📦'), ('delivery', 'Delivery', '🦆'),
        ('spaceport', 'Spaceport', '🚀'), ('expedite', 'Spaceport rush', '⚡'), ('scout', 'Scout', '🧭'), ('survey', 'Survey', '🗺️')]
for _task, _label, _emoji in WORK:
    leaf('w_' + _task, _label, _emoji, 'do', 'work', {'task': _task}, hint='')
# One button for training: every skill with its level, then a skill's tasks, each with its own Start button.
leaf('trainskill', 'Train skills', '🎓', 'pick', 'training', pick='skills', then='view', option='skill',
     hint='pick a skill to see every task that trains it, each with a Start button')
leaf('repair', 'Fix infrastructure', '🔧', 'do', 'repair', {'target': 'society'}, hint='repair settlement systems (Engineering)')
leaf('gearrepair', 'Fix a tool', '🪛', 'pick', 'repair', {'target': 'gear'}, pick='gear', then='do', option='item',
     hint='restore a quality tool with Iron Nails')
# Craft
leaf('workbench', 'All recipes', '🛠️', 'nav', nav=('wh',), hint='every category and what to start with')
leaf('ready', 'Ready to craft', '✅', 'nav', nav=('wc', 'ready', 1, ''), hint='everything you can craft right now')
leaf('favs', 'Favourites', '⭐', 'nav', nav=('wc', 'favorites', 1, ''), hint='your starred recipes')
leaf('workshop', 'Workstations', '🏭', 'view', 'workshop', hint='stations, tiers and unlock fees')
leaf('goal', 'My goal', '🎯', 'nav', nav=('gv',), hint='your pinned recipe and everything still needed for it')
leaf('shopping', 'Shopping list', '🛒', 'nav', nav=('lv',),
     hint='several recipes in the amounts you want, planned together: what is missing, buy it all, fetch next')
leaf('catalog', 'Item list', '📚', 'view', 'catalog', hint='every item and where it comes from')
leaf('catalogcat', 'Item list by category', '🗂️', 'pick', 'catalog', pick='field:catalog:category', then='view', option='category',
     hint='items of one category and where they come from')
leaf('unlock', 'Unlock a station', '🔓', 'pick', 'workshop', {'action': 'unlock'}, pick='station', then='confirm', option='station',
     hint='pay once to use a workstation')
# Craft categories are all in the Workbench's category dropdown (one place instead of fifteen buttons).
# Queue
leaf('qstatus', 'Queue status', '📋', 'nav', nav=('qv',), hint='progress, totals and why it paused')
leaf('repeat', 'Repeat last', '🔁', 'do', 'queue', {'action': 'repeat'}, hint='run your last queue again')
leaf('cancel', 'Stop queue', '⏹️', 'do', 'queue', {'action': 'cancel'}, hint='stop the remaining attempts', style=4)
leaf('clearnext', 'Clear what runs next', '⏭️', 'nav', nav=('cn',), hint='remove the follow-up queue')
leaf('plan', 'What runs next', '🗺️', 'nav', nav=('pv',), hint='steps after this queue, and saved routines')
# Bag
leaf('inventory', 'My bag', '🎒', 'view', 'inventory', hint='everything you own, with sorting and search')
leaf('by_value', 'By value', '💰', 'view', 'inventory', {'sort': 'value'}, hint='most valuable first')
leaf('by_name', 'By name', '🔤', 'view', 'inventory', {'sort': 'name'}, hint='A to Z')
leaf('by_category', 'By category', '🗂️', 'view', 'inventory', {'sort': 'category'}, hint='grouped by category')
leaf('favitems', 'Favourite ingredients', '⭐', 'view', 'inventory', {'show': 'favorites'}, hint='what your favourite recipes use')
leaf('sellable', 'Sellable', '🏷️', 'view', 'inventory', {'show': 'sellable'}, hint='what Seed Industries buys')
leaf('search', 'Search bag', '🔍', 'modal', 'inventory', modal=('Search your bag', 'Item name or part of it', 'e.g. iron'), option='search',
     hint='find an item you own')
leaf('ready_items', 'For ready recipes', '✅', 'view', 'inventory', {'show': 'ready'}, hint='items your ready recipes use')
leaf('gear', 'Quality gear', '⚙️', 'view', 'inventory', {'section': 'gear'}, hint='condition and repairs')
leaf('use', 'Use', '🧰', 'pick', 'use', pick='use', then='do', option='item', hint='beds, seats, baths, tools and more')
leaf('sell', 'Sell', '🏷️', 'pick', 'seedindustries', {'action': 'sell'}, pick='sell', then='amount', option='item',
     hint='choose an item, then sell 1, 5, 10, 25, all of it or your own amount')
leaf('clearout', 'Sell extras', '🧹', 'view', 'seedindustries', {'action': 'clearout'}, hint='sell surplus materials (preview first)')
leaf('uses', 'What can I make with…?', '🔍', 'pick', 'catalog', pick='owned', then='uses', option='item', hint='recipes that use an item you own')
leaf('autosell', 'Auto-sell', '🤖', 'nav', nav=('av',), hint='items sold automatically when a queue finishes')
leaf('keep', 'Always keep', '🛡️', 'nav', nav=('kv',), hint='how many of an item selling always leaves you, and restocking back up to it')
leaf('undo', 'Undo sale', '↩️', 'do', 'undo', hint=f'take back your last sale (within 60 seconds)')
# Trade
leaf('market', 'Seed Industries', '🏭', 'view', 'seedindustries', hint='buy supplies and sell your goods')
leaf('browse', 'Shop by category', '🛒', 'pick', 'seedindustries', {'action': 'browse'}, pick='field:seedindustries:category', then='view',
     option='category', hint='supplies by category with prices')
leaf('buy', 'Buy', '🛍️', 'pick', 'seedindustries', {'action': 'buy'}, pick='buy', then='amount', option='item',
     hint='choose an item, then how many')
leaf('sellsome', 'Sell', '💵', 'pick', 'seedindustries', {'action': 'sell'}, pick='sell', then='amount', option='item')   # older messages: now Sell
leaf('bstart', 'Start a business', '🏗️', 'modal', 'business', {'action': 'start'}, modal=('Start a business', 'Business name', 'e.g. Rocky Repairs'),
     option='name', max_length=30, hint='found your company (costs SC)')
leaf('starters', 'Starter shopping', '🧭', 'view', 'seedindustries', {'action': 'starters'}, hint='what to buy for each skill')
leaf('orders', 'Orders', '📋', 'view', 'seedindustries', {'action': 'orders'}, hint="today's production orders")
leaf('fulfill', 'Deliver an order', '📦', 'pick', 'seedindustries', {'action': 'fulfill'}, pick='order', then='confirm', option='item',
     hint='hand in a production order')
leaf('prices', 'Best prices today', '📈', 'view', 'market', {'action': 'view'}, hint='two materials Seed Industries pays extra for today')
leaf('commerce', 'Trade for SC', '🏪', 'do', 'market', {'action': 'work'}, hint='earn SC trading')
leaf('analyze', 'Market analysis', '📊', 'do', 'market', {'action': 'analyze'}, hint='needs a Market Analyzer')
leaf('habitat', 'Your home', '🛖', 'view', 'home', hint='your home and its next upgrade')
leaf('homeup', 'Upgrade home', '🔨', 'do', 'home', {'action': 'upgrade'}, hint='costs SC and Iron Nails')
leaf('business', 'Your business', '🏢', 'view', 'business', hint='your company')
leaf('bwork', 'Business work', '💼', 'do', 'business', {'action': 'work'}, hint='')
leaf('bcontract', 'Contract', '📝', 'do', 'business', {'action': 'contract'}, hint='')
leaf('binvest', 'Invest', '💹', 'do', 'business', {'action': 'invest'}, hint='')
# World
for _section, _label, _emoji in [('overview', 'Society news', '🌎'), ('conditions', 'Weather & time', '☁️'), ('society', 'Society stats', '🏛️'),
                                 ('society_progress', 'Next society tier', '📈'), ('leaderboard', 'Top helpers', '🏆'), ('event', 'Event', '🚨'),
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
leaf('title', 'Show a title', '🏅', 'pick', 'me', {'section': 'titles'}, pick='title', then='do', option='title', hint='show off a title')
leaf('specialize', 'Specialize', '🎯', 'pick', 'specialize', pick='choices:specialize', then='confirm', option='path',
     hint='permanent Lv.10 path')
leaf('display_compact', 'Results: Short', '📏', 'do', 'me', {'section': 'display', 'style': 'compact'})
leaf('display_detailed', 'Results: Full', '📜', 'do', 'me', {'section': 'display', 'style': 'detailed'})
# Social
leaf('friend', 'Friends', '🤝', 'pick', 'social', pick='player', then='social', option='player',
     hint='say hi, hang out, mentor or do a duo activity')
leaf('recreation', 'Group games', '🎳', 'do', 'social', {'action': 'group_games'}, hint='group games with your Recreation Set')
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
leaf('auto_on', 'Auto-recover: On', '🩹', 'do', 'settings', {'autorecover': 'on'})
leaf('auto_off', 'Auto-recover: Off', '✋', 'do', 'settings', {'autorecover': 'off'})
# Help
leaf('guide', 'What next?', '🧭', 'view', 'guide', hint='your best next step and why')
leaf('guidegoal', 'Guide for…', '🗺️', 'pick', 'guide', pick='field:guide:goal', then='view', option='goal',
     hint='step-by-step help for one goal (SC, crafting, home…)')
leaf('find', 'Ask or search', '🔎', 'modal', 'find', modal=('Find or ask anything', 'A word or a question', 'e.g. how do I make Iron Nails?'),
     option='query', max_length=100, hint='search, or ask: how do I make…, where do I get…, how do I level…')
# My Seedling
leaf('sl_view', 'Overview', '🌱', 'view', 'seedling', hint='mood, thought, where it is and what it is doing')
leaf('sl_decide', 'Let it decide', '🎲', 'do', 'seedlingstep', hint='your Seedling picks its next step itself, right now')
leaf('sl_diary', 'Diary', '📓', 'view', 'seedling', {'section': 'diary'}, hint='what it did while you were away')
leaf('sl_schedule', 'Schedule', '🗓️', 'pick', 'seedling', pick='schedule', then='do', option='schedule',
     hint='balanced, workaholic, night owl, socialite, homebody or your own')
leaf('sl_custom', 'Custom schedule', '🧩', 'nav', nav=('lp',))
leaf('lk_view', 'My look', '🪞', 'view', 'customize', hint='everything you have chosen')
for _field, _label, _emoji, _hint in [('skin', 'Skin tone', '🎨', 'fourteen tones, including Avesta colours'),
                                      ('hair', 'Hair style', '💇', 'short, long, curly, bun, spiky and more'),
                                      ('hair_colour', 'Hair colour', '🌈', 'natural and bright colours'),
                                      ('outfit', 'Outfit colour', '👕', 'a colour, or follow its mood'),
                                      ('accessory', 'Accessory', '👓', 'glasses, scarf, bow tie, backpack…'),
                                      ('headwear', 'Headwear', '🧢', 'its job hat, or no hat so its hair shows'),
                                      ('attitude', 'Attitude', '💬', 'how it talks in its speech bubbles'),
                                      ('catchphrase', 'Catchphrase', '🗯️', 'something it says now and then on stream')]:
    leaf('lk_' + _field, _label, _emoji, 'pick', 'customize', pick=f'field:customize:{_field}', then='do', option=_field, hint=_hint)
leaf('sl_on', 'Lives on its own: On', '🌱', 'do', 'seedling', {'autonomy': 'on'})
leaf('sl_off', 'Lives on its own: Off', '✋', 'do', 'seedling', {'autonomy': 'off'})
# Account
leaf('start', 'Start / load citizen', '🌱', 'view', 'start', hint='create your citizen or see where you are')
leaf('link', 'Link Twitch', '🔗', 'modal', 'link', modal=('Link your Twitch citizen', 'Code from !link in Twitch chat', 'e.g. AB12CD'),
     option='code', max_length=12, hint='enter the code from !link in Twitch chat')
# Moderator
leaf('m_eventstart', 'Start event', '🚨', 'pick', 'eventstart', pick='field:eventstart:event', then='confirm', option='event',
     hint='begin a society event')
leaf('m_eventstop', 'Stop event', '🛑', 'do', 'eventstop', style=4, hint='cancel the active event without a penalty')
leaf('m_modlog', 'Moderator log', '📜', 'view', 'modlog', hint='the last ten moderator actions')
leaf('m_asklog', 'Unanswered questions', '❓', 'view', 'asklog', hint='what players asked Find that it could not answer')
leaf('m_lookup', 'Account lookup', '🔍', 'pick', 'linklookup', pick='player_name', then='view', option='player',
     hint='linked accounts of a citizen (owners)')
leaf('m_force', 'Force merge', '🧬', 'nav', nav=('xk',), hint='merge two characters into one, irreversibly (owners)')
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
leaf('m_feed', 'Channel feed…', '📣', 'pick', 'feedhere', pick='leaves:m_feedhere,m_feedoff', then='leaf', hint='a live feed of what everyone does, in a channel')
leaf('m_feedhere', 'Post the feed here', '📣', 'do', 'feedhere', hint='this channel shows what everyone gathers, crafts and unlocks')
leaf('m_feedoff', 'Feed off', '🔕', 'do', 'feedoff', hint='stop the activity feed')
leaf('feed_on', 'Activity feed: Shown', '📣', 'do', 'settings', {'feed': 'on'})
leaf('feed_off', 'Activity feed: Hidden', '🙈', 'do', 'settings', {'feed': 'off'})
leaf('h_moderator', 'Moderator help', '📖', 'view', 'seed', {'topic': 'moderator'}, hint='')
# Community
leaf('c_vote', "Today's vote", '🗳️', 'view', 'vote', hint='vote for what New Eridian builds or celebrates next; change it any time today')
leaf('c_vote_pick', "Today's vote", '✅', 'pick', 'vote', pick='ballot', then='do', option='choice')
leaf('c_challenge', 'Stream challenge', '⚡', 'view', 'challenge', hint='the live shared goal and how to help')
leaf('c_season', 'Season', '🏁', 'view', 'season', hint='your season points, rank and next reward')
leaf('c_season_more', 'Season details…', '🏆', 'pick', 'season', pick='leaves:c_season_top,c_season_rewards,c_season_story,c_hats', then='leaf',
     hint='top ten, rewards, story and hats')
leaf('c_season_top', 'Season top ten', '🏆', 'view', 'season', {'section': 'top'}, hint='the top ten this season')
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
leaf('h_about', 'About', 'ℹ️', 'view', 'seed', {'topic': 'about'}, hint='a free, unofficial fan project made by Kamex')

# Grouped choices: one dropdown instead of a row of similar buttons. 'leaves:' lists views to pick from.
leaf('inv_views', 'Sort & filter…', '🗂️', 'pick', 'inventory', pick='leaves:by_value,by_name,by_category,favitems,sellable,ready_items,gear', then='leaf',
     hint='by value, name or category; favourites, sellable, ready-recipe items or gear')
leaf('wd_more', 'News & story…', '📰', 'pick', 'world', pick='leaves:wd_bulletin,wd_rumor,wd_story,wd_project,wd_society,wd_market,wd_holidays,wd_event_history',
     then='leaf', hint='bulletin, rumor, story, project, society, market, holidays and past events')
leaf('me_more', 'More…', '📓', 'pick', 'me', pick='leaves:me_collection,me_bonuses,me_traits,me_relationships,me_journal,me_titles,me_tutorial',
     then='leaf')    # older messages only: You now has a More screen
leaf('h_topics', 'Handbook', '📚', 'pick', 'seed', pick='leaves:h_start,h_character,h_property,h_life,h_production,h_operations,h_society,h_other,h_terms,me_tutorial,wd_holidays',
     then='leaf', hint='every topic of the handbook')
leaf('alerts', 'Queue alerts', '🔔', 'pick', 'settings', pick='alerts', then='do', option='alerts', hint='how you hear that a queue paused or finished')
leaf('popups', 'Pop-ups after commands', '📬', 'pick', 'settings', pick='popups', then='do', option='popups', hint='what pops up for you after commands')
leaf('quiet', 'Quiet hours', '🌙', 'modal', 'settings', hint='a daily window in your time zone when DM alerts wait, then arrive as one message')
leaf('quiet_off', 'Turn off quiet hours', '☀️', 'nav', nav=('qo',), hint='DM alerts arrive as they happen again; anything held comes now')

# Lists of jobs (see JOBS): each job with what it gives and a button; a choice runs it like the old one-job buttons did.
leaf('farm', 'Farm', '🌾', 'pick', 'work', pick='jobs:farm', then='do', option='task', hint='tend, harvest and water the fields')
leaf('jobs', 'Other jobs', '🔭', 'pick', 'work', pick='jobs:jobs', then='do', option='task',
     hint='scans, research, cargo, deliveries, the spaceport, scouting and surveys')
# Grouped pickers: one button opens a list of other pickers (Looks).
leaf('lk_body', 'Body…', '🧍', 'pick', 'customize', pick='leaves:lk_skin,lk_hair,lk_hair_colour', then='leaf', hint='skin tone, hair style and hair colour')
leaf('lk_clothes', 'Clothes…', '👕', 'pick', 'customize', pick='leaves:lk_outfit,lk_accessory,lk_headwear', then='leaf', hint='outfit colour, accessory and headwear')
leaf('lk_voice', 'Voice…', '💬', 'pick', 'customize', pick='leaves:lk_attitude,lk_catchphrase', then='leaf', hint='attitude and catchphrase')
# Switches: one button that shows the current state and flips it (no separate on and off buttons). `flip` holds the
# older do-leaf each state runs; SWITCH_STATE (below) says whether the setting is on.
leaf('auto', 'Auto-recover', '🩹', 'switch', 'settings', words=('On', 'Off'), flip={True: 'auto_off', False: 'auto_on'}, hint='paused queues recover by themselves')
leaf('feed', 'Activity feed', '📣', 'switch', 'settings', words=('Shown', 'Hidden'), flip={True: 'feed_off', False: 'feed_on'},
     hint='whether your gathering, crafting and trophies appear in the channel feed')
leaf('results', 'Results', '📏', 'switch', 'me', words=('Short', 'Full'), flip={True: 'display_detailed', False: 'display_compact'},
     hint='short results, or full results with every detail')
leaf('sl_auto', 'Lives on its own', '🌱', 'switch', 'seedling', words=('On', 'Off'), flip={True: 'sl_off', False: 'sl_on'},
     hint='it lives its schedule while you are away; off, it waits for you')

# Every button gets a line that explains it, so the newer layout can put the button beside it.
_HINTS = {
    'w_farm_tend': 'gives 1 Pumpkin + 1 Pumpkin Seeds', 'w_farm_harvest': 'gives 3 Pumpkins + 1 Pumpkin Seeds',
    'w_farm_irrigate': 'gives 3 Pumpkins + 1 Murky Water', 'w_farm_hydroponics': 'gives 4 Pumpkins + 1 Raw Algae; needs a Small Water Filter',
    'w_scan': 'an environmental scan', 'w_rare': 'mine a rare ore (needs a Mineral Extractor)', 'w_research': 'gives 1 Stone',
    'w_field_analysis': 'gives 2 Stone + 1 Herbs; needs a Siro Sampler', 'w_cargo': 'prepare Cargo for deliveries',
    'w_delivery': 'deliver Cargo (used on success)', 'w_spaceport': 'gives 1 Cargo + 1 Lumber',
    'w_expedite': 'gives 2 Cargo + 2 Lumber; uses 1 Power Cell', 'w_scout': 'gives 1 Stone + 1 Berries',
    'w_survey': 'gives 2 Stone + 1 Clay + 1 Coal; needs a Resource Scanner',
    'bwork': 'gives 1 Cargo', 'bcontract': 'gives 2 Cargo + 1 Lumber', 'binvest': 'put SC into your company',
    'wd_overview': 'the day, weather, project and news', 'wd_conditions': 'weather and time of day, and the work they favour',
    'wd_society': 'the settlement and its stats', 'wd_society_progress': 'what it takes to reach the next tier',
    'wd_leaderboard': 'who has helped New Eridian most', 'wd_event': 'the active event and how to help', 'wd_event_history': 'past events',
    'wd_holidays': 'festivals now and next', 'wd_project': 'the society project', 'wd_story': 'the colony story so far',
    'wd_bulletin': 'news from the settlement', 'wd_rumor': 'what people are whispering', 'wd_market': "today's prices and demand",
    'me_overview': 'your citizen at a glance', 'me_skills': 'every skill and its level', 'me_daily': "today's contract",
    'me_achievements': 'milestones you have reached', 'me_collection': 'what you have collected', 'me_bonuses': 'boosts active now',
    'me_traits': "your citizen's traits", 'me_relationships': 'friends and how close you are', 'me_journal': 'your recent story',
    'me_tutorial': 'the tutorial steps', 'me_titles': 'titles you have unlocked',
    'h_moderator': 'how the moderator tools work',
}
for _key, _hint in _HINTS.items():
    if _key in LEAVES and not LEAVES[_key]['hint']:
        LEAVES[_key]['hint'] = _hint
# In Discord's newer layout Home shows these as a compact row; the rest get a button beside their line.
HOME_COMPACT = {'inbox', 'recent', 'help', 'mod'}
# The word on the button beside each choice in a list; otherwise Open for views and Choose for the rest.
VERBS = {'gather': 'Gather', 'mine': 'Mine', 'trainskill': 'Train', 'guidegoal': 'Guide', 'catalogcat': 'Browse', 'eat': 'Eat', 'hobby': 'Practice', 'gearrepair': 'Fix', 'unlock': 'Unlock', 'use': 'Use', 'sell': 'Sell', 'buy': 'Buy',
         'sellsome': 'Sell', 'fulfill': 'Deliver', 'title': 'Show', 'c_vote_pick': 'Vote', 'c_hat': 'Wear', 'c_badge': 'Pin',
         'farm': 'Do it', 'jobs': 'Do it', 'lk_body': 'Change', 'lk_clothes': 'Change', 'lk_voice': 'Change', 'sl_schedule': 'Use',
         'm_eventstart': 'Start', 'm_chalstart': 'Start', 'm_live': 'Set', 'm_feed': 'Do it'}
# The word on the button beside a line of a More screen (otherwise Do it, Open, Choose or Enter by kind).
MORE_VERBS = {'repair': 'Fix', 'gearrepair': 'Fix', 'unlock': 'Unlock', 'catalogcat': 'Browse', 'walk': 'Walk', 'hobby': 'Practice', 'meal': 'Share',
              'recreation': 'Play', 'clearout': 'Preview', 'browse': 'Browse', 'commerce': 'Work', 'fulfill': 'Deliver', 'analyze': 'Analyze',
              'bstart': 'Start', 'bwork': 'Work', 'bcontract': 'Work', 'binvest': 'Invest'}
# How to get what a locked button needs: key -> (what, the question Find answers). The button opens Find with the
# question already asked. Reasons that are not an item (no business yet, Halloween only, nothing to sell) have no
# entry: HOW_GO sends the ones with a fix elsewhere to that button; the rest show no button.
HOW = {'w_rare': ('a Small Mineral Extractor', 'where do I get a Small Mineral Extractor'),
       'w_farm_hydroponics': ('a Small Water Filter', 'where do I get a Small Water Filter'),
       'w_field_analysis': ('a Siro Sampler', 'where do I get a Siro Sampler'),
       'w_survey': ('a Resource Scanner', 'where do I get a Resource Scanner'),
       'w_expedite': ('a Power Cell', 'where do I get a Power Cell'),
       'gearrepair': ('quality gear', 'how do I make a Field Hoe'),
       'analyze': ('a Market Analyzer', 'where do I get a Market Analyzer'),
       'recreation': ('a Recreation Set', 'where do I get a Recreation Set')}
HOW_GO = {'w_delivery': 'jobs', 'bwork': 'bstart', 'bcontract': 'bstart', 'binvest': 'bstart', 'eat': 'farm', 'eatfull': 'farm', 'meal': 'farm',
          'sell': 'gather', 'clearout': 'gather', 'uses': 'gather', 'use': 'workbench', 'c_hat': 'c_season', 'c_badge': 'c_trophies'}

PARENT = {}
for _area, (_, _, _, _children) in AREAS.items():
    for _child in _children:
        PARENT.setdefault(_child, _area)
for _area, _keys in MORE.items():
    for _child in _keys:
        PARENT.setdefault(_child, _area)
for _group in JOBS.values():
    for _child in _group:
        PARENT.setdefault(_child, 'work')
PARENT.update({'s_' + _action: 'life' for _action, _, _ in SOCIAL})   # shown after choosing a citizen
# Leaves no screen lists any more (older buttons and tickets still name them) belong to the area that replaced them.
PARENT.update({'sellsome': 'trade', 'inv_views': 'trade', 'search': 'trade', 'market': 'trade', 'undo': 'trade', 'c_vote_pick': 'community',
               'me_more': 'me', 'auto_on': 'settings', 'auto_off': 'settings', 'feed_on': 'settings', 'feed_off': 'settings',
               'display_compact': 'settings', 'display_detailed': 'settings', 'quiet_off': 'settings', 'sl_on': 'seedling',
               'sl_off': 'seedling', 'sl_custom': 'seedling'})
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
COMMAND_AREA.update({'seedling': 'seedling', 'seedlingstep': 'seedling', 'link': 'settings', 'start': 'settings', 'eventstart': 'mod', 'eventstop': 'mod', 'modlog': 'mod', 'asklog': 'mod',
                     'linklookup': 'mod', 'guidepanels': 'mod', 'menupanel': 'mod', 'eatfull': 'life', 'trick': 'life', 'undo': 'trade', 'find': 'help', 'make': 'craft', 'workshop': 'craft', 'catalog': 'craft', 'queue': 'queue', 'mine': 'work', 'gather': 'work',
                     'farm': 'work', 'scan': 'work', 'rare': 'work', 'research': 'work', 'cargo': 'work', 'delivery': 'work',
                     'spaceport': 'work', 'explore': 'work', 'repair': 'work', 'training': 'work', 'society': 'community',
                     'event': 'community', 'holiday': 'community', 'world': 'community', 'progress': 'me', 'seed': 'help', 'guide': 'help',
                     'eat': 'life', 'relax': 'life', 'sleep': 'life', 'games': 'life', 'walk': 'life', 'hobby': 'life',
                     'meal': 'life', 'recover': 'life', 'use': 'trade', 'inventory': 'trade', 'status': 'home', 'settings': 'settings'})
# Slash commands whose replies offer "Again" (they perform a task and can simply be repeated).
REPEATABLE = {'eatfull', 'relax', 'sleep', 'games', 'walk', 'meal', 'recover', 'farm', 'scan', 'rare', 'research', 'cargo', 'delivery',
              'spaceport', 'explore', 'repair', 'hobby', 'eat', 'use'}


# ---------------------------------------------------------------- what this citizen can do right now

class Ctx:
    """What one citizen has and can do, read once per screen. Every rule mirrors the check the command itself
    makes, so a hidden button is one the game would refuse, and it reappears as soon as the citizen can use it."""
    def __init__(self, db, p, uid):
        self.db, self.p, self.uid, self._cache = db, p, uid, {}

    def get(self, name, make):
        if name not in self._cache:
            try:
                self._cache[name] = make()
            except Exception:
                self._cache[name] = True    # if a check itself fails, show the button and let the command explain
        return self._cache[name]

    def equipment(self, action, mode=''):
        from . import task_yields
        from .game.routes_player import equipment_count
        key = task_yields.EQUIPMENT.get((action, mode))
        return self.get('eq:' + str(key), lambda: equipment_count(self.db, self.p, key) > 0)

    def has(self, source):
        return self.get('has:' + source, lambda: bool(choices(self.db, self.p, source, self.uid)))

    def queue(self):
        from . import task_queue
        return self.get('queue', lambda: self.db.get(task_queue.TaskQueue, (self.p.channel_id, self.p.twitch_uid)))

    def prefs(self):
        from . import qol
        return self.get('prefs', lambda: qol.prefs(self.db, self.p.channel_id, self.p.twitch_uid))

    def business(self):
        from .game.players import business_for
        return self.get('business', lambda: business_for(self.db, self.p) is not None)

    def autonomy_on(self):
        def read():
            from . import autonomy
            row = autonomy.row(self.db, self.p.channel_id, self.p.twitch_uid)
            return row is None or bool(row.enabled)
        return self.get('autonomy', read)

    def sale_to_undo(self):
        def read():
            import json
            from datetime import datetime
            from . import extras
            from .game.players import as_utc
            row = extras.row(self.db, self.p.channel_id, self.p.twitch_uid)
            sale = json.loads(row.last_sale) if row is not None and row.last_sale else None
            return bool(sale) and (runtime.now() - as_utc(datetime.fromisoformat(sale['at']))).total_seconds() <= extras.UNDO_SECONDS
        return self.get('undo', read)

    def quiet_on(self):
        from . import quiet_hours
        return self.get('quiet', lambda: quiet_hours.row(self.db, self.p.channel_id, self.p.twitch_uid) is not None)

    def feed_hidden(self):
        from . import activity_feed
        return self.get('feed', lambda: activity_feed.hidden(self.db, self.p))

    def challenge_active(self):
        from . import live_events
        return self.get('challenge', lambda: live_events.active(self.db) is not None)

    def event_active(self):
        from .game.players import world
        return self.get('event', lambda: bool(world(self.db, self.p.channel_id).active_event))

    def linked(self):
        def read():
            p = self.p
            return self.db.execute(select(AccountLink).where(AccountLink.channel_id == p.channel_id,
                                                             AccountLink.twitch_uid == p.twitch_uid)).scalars().first() is not None
        return self.get('linked', read)


def _food(c):
    from .game.training_and_items import edible_inventory
    return c.get('food', lambda: any(r['qty'] > 0 for r in edible_inventory(c.db, c.p)))


def _emergency_meal(c):
    from .game.training_and_items import emergency_food_available
    return c.get('emergency', lambda: emergency_food_available(c.db, c.p))


def _queue_active(c):
    from . import task_queue
    q = c.queue()
    return q is not None and q.state in task_queue.ACTIVE


def _planned(c):
    from . import extras
    pref = c.prefs()
    return bool((pref is not None and pref.next_task) or c.get('steps', lambda: extras.playlist(c.db, c.p.channel_id, c.p.twitch_uid)))


def _trick_open(c):
    from . import halloween
    return halloween.open_now() and halloween.tries_left(c.db, c.p) > 0


def _has_recreation_set(c):
    from .game.training_and_items import owned_life_items
    return c.get('rec', lambda: bool(owned_life_items(c.db, c.p).get('recreation_set')))


def _has_power_cell(c):
    from .game.cooldowns_materials import material_amount
    return c.get('cell', lambda: material_amount(c.db, c.p, 'power_cell') > 0)


def _rare_unlocked(c):
    from . import crafting_progression
    return crafting_progression.rare_unlocked(c.db, c.p)


def _result_style(c):
    from .game.life import player_preference
    return player_preference(c.db, c.p).result_style


def _needs_blocked(c):
    from .game.life import life_state
    from .needs import blocked_needs
    return c.get('blocked', lambda: bool(blocked_needs(life_state(c.db, c.p))))


# Whether each switch's setting is on (the first word of its button: Auto-recover: On).
SWITCH_STATE = {'auto': lambda c: bool(c.prefs() is not None and c.prefs().autorecover),
                'feed': lambda c: not c.feed_hidden(),
                'results': lambda c: _result_style(c) == 'compact',
                'sl_auto': lambda c: c.autonomy_on()}


# key -> (can the citizen use it now?, why not). Keys not listed are always available.
WHEN = {
    'eat': (lambda c: _food(c) or _emergency_meal(c), 'you have no food'),
    'eatfull': (_food, 'you have no food'),
    'meal': (lambda c: c.p.crops > 0, 'needs 1 Pumpkin'),
    'trick': (_trick_open, 'Halloween festival only, 5 doors a day'),
    'recreation': (_has_recreation_set, 'needs a Recreation Set'),
    'w_farm_hydroponics': (lambda c: c.equipment('water', 'hydroponics'), 'needs a Small Water Filter'),
    'w_field_analysis': (lambda c: c.equipment('research', 'field_analysis'), 'needs a Siro Sampler'),
    'w_survey': (lambda c: c.equipment('survey'), 'needs a Resource Scanner'),
    'analyze': (lambda c: c.equipment('market', 'analyze'), 'needs a Market Analyzer'),
    'w_delivery': (lambda c: c.p.cargo > 0, 'needs Cargo: do the Cargo job first (Other jobs)'),
    'w_expedite': (_has_power_cell, 'needs a Power Cell'),
    'w_rare': (_rare_unlocked, 'needs a Mineral Extractor'),
    'gearrepair': (lambda c: c.has('gear'), 'you have no quality gear'),
    'use': (lambda c: c.has('use'), 'you own nothing usable yet'),
    'sell': (lambda c: c.has('sell'), 'you have nothing Seed Industries buys'),
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
    'recover': (_needs_blocked, 'no need is blocking your work'),
    'wd_event': (lambda c: c.event_active(), 'no event is running'),
    'c_challenge': (lambda c: c.challenge_active(), 'no stream challenge is running'),
    'm_eventstart': (lambda c: not c.event_active(), 'an event is already running'),
    'm_eventstop': (lambda c: c.event_active(), 'no event is running'),
    'm_chalstart': (lambda c: not c.challenge_active(), 'a stream challenge is running'),
    'm_chalstop': (lambda c: c.challenge_active(), 'no stream challenge is running'),
    'c_hat': (lambda c: c.has('hats'), 'no cosmetic hats yet: reach Silver this season or win a holiday Feast'),
    'c_badge': (lambda c: c.has('badges'), 'no trophies yet'),
    'link': (lambda c: not c.linked(), 'already linked'),
}
# Switches: the hidden side is just the current state (a queue that is running has no Repeat last, a Halloween button
# is only there during Halloween), so it hides and is never listed under Not yet in More.
TOGGLES = {'bstart', 'm_eventstart', 'm_eventstop', 'link', 'm_chalstart', 'm_chalstop', 'cancel', 'repeat', 'clearnext', 'recover', 'trick',
           'wd_event', 'c_challenge'}


def can(ctx, key):
    rule = WHEN.get(key)
    if rule is None or ctx is None or ctx.p is None:
        return True
    return ctx.get('can:' + key, lambda: bool(rule[0](ctx)))


def context(uid, db=None, p=None):
    return Ctx(db, p, uid) if db is not None and p is not None else None


def with_context(uid, fn, name='Citizen'):
    """For callers without a session: open one, read what the citizen can do, and close it."""
    from .game.players import player
    with SessionLocal() as db:
        p = player(db, runtime.DISCORD_WORLD_ID, 'discord', uid, name)[1]
        result = fn(Ctx(db, p, uid))
        db.commit()
        return result


# ---------------------------------------------------------------- building blocks

def _switch_on(owner, ctx, key):
    """Whether a switch's setting is on now (a failing read counts as on, like every other check on a screen)."""
    state = SWITCH_STATE[key]
    return bool(ctx.get('switch:' + key, lambda: bool(state(ctx))))


def _button(owner, key, compact=False, ctx=None):
    if key in AREAS:
        emoji, title, _, _ = AREAS[key]
        return ui.button(title, ui.cid(owner, 'mn', key), style=1, emoji=emoji)
    item = LEAVES[key]
    if item['kind'] == 'switch' and ctx is None:
        # A screen with no session of its own (a Find answer) opens the screen the switch lives on.
        return ui.button(item['label'], ui.cid(owner, 'mn', PARENT.get(key, 'settings')), emoji=item['emoji'])
    if item['kind'] == 'switch':
        # One button that shows the state (Auto-recover: On) and does the opposite when pressed.
        on = _switch_on(owner, ctx, key)
        ticket = ui.issue(owner, {'do': 'cmd', 'leaf': item['flip'][on]})
        return ui.button(f"{item['label']}: {item['words'][0 if on else 1]}", ui.cid(owner, 't', ticket), emoji=item['emoji'])
    if key == 'quiet' and ctx is not None and ctx.quiet_on():
        return ui.button('Quiet hours: On', ui.cid(owner, 'mn', 'settings', 'quiet'), emoji=item['emoji'])    # Change or Turn off
    if item['kind'] == 'do':
        ticket = ui.issue(owner, {'do': 'cmd', 'leaf': key})
        return ui.button(item['label'], ui.cid(owner, 't', ticket), style=item.get('style', 3), emoji=item['emoji'])
    if item['kind'] == 'nav':
        return ui.button(item['label'], ui.cid(owner, *item['nav']), emoji=item['emoji'])
    if item['kind'] == 'modal':
        return ui.button(item['label'], ui.cid(owner, 'mo', key), emoji=item['emoji'])
    verb = 'mk' if item['kind'] == 'pick' else 'mv'
    return ui.button(item['label'], ui.cid(owner, verb, key), emoji=item['emoji'])


def grid(owner, keys, rows=4, ctx=None, extra=()):
    """Buttons five per row, at most `rows` rows; `extra` buttons (More) always keep their place at the end."""
    extra = [b for b in extra if b]
    buttons = [_button(owner, key, ctx=ctx) for key in keys][:rows * 5 - len(extra)] + extra
    return [ui.row(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]


def nav(owner, area, up=None):
    """◀️ Back and 🏠 Menu under a screen in `area`. Back returns to the screen shown before; on a
    message's first screen it goes up to `up` (an area screen: its parent; a screen inside one: the area)."""
    if area == 'home' and up is None:
        return None
    return ui.row(ui.back_button(owner, 'mn', up or PARENT.get(area, 'home')), ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))


def children_of(area, ctx=None):
    """An area's main buttons: moderator tools only for the game owner, and (given a citizen) only what they can use now."""
    keys = AREAS[area][3]
    if area == 'home' and not ui.is_moderator():
        keys = [k for k in keys if k not in MOD_AREAS]
    if not ui.is_owner():
        keys = [k for k in keys if k not in OWNER_ONLY]
    return [k for k in keys if can(ctx, k)]


def _members(area):
    """Every button an area owns, in the order it shows them: its main list, the jobs behind Farm and Other jobs (Work),
    then its More list."""
    keys = list(AREAS[area][3])
    if area == 'work':
        keys += [k for group in JOBS.values() for k in group]
    return list(dict.fromkeys(keys + MORE.get(area, [])))


def more_split(area, ctx):
    """(Also here, Not yet) for an area's More screen: the extras the citizen can use, and (key, reason) for every button
    of the area they cannot use yet. Switches are never listed: their hidden side is just the current state."""
    if ctx is None:
        return [], []
    also = [k for k in MORE.get(area, []) if can(ctx, k)]
    locked = [(k, WHEN[k][1]) for k in _members(area) if k in WHEN and k not in TOGGLES and k not in MOD_AREAS and not can(ctx, k)]
    return also, locked


def more_button(owner, area, ctx):
    """The area's More button, saying what is inside (More · 4 locked); None when there is nothing behind it."""
    also, locked = more_split(area, ctx)
    if not also and not locked:
        return None
    return ui.button('More' + (f' · {len(locked)} locked' if locked else ''), ui.cid(owner, 'mn', area, 'more'), emoji='➕')


def area_rows(owner, area, ctx, rows=3):
    """An area's main buttons and its More button, for the screens that show an action's result."""
    return grid(owner, children_of(area, ctx), rows=rows, ctx=ctx, extra=[more_button(owner, area, ctx)])


def _line(key):
    """The line that explains a button: '🧪 **Hydroponics** — gives 4 Pumpkins…' (an area uses its short blurb)."""
    if key in AREAS:
        e, t, d, _ = AREAS[key]
        return f'{e} **{t}** — {BLURB.get(key, d)}'
    item = LEAVES[key]
    return f"{item['emoji']} **{item['label']}** — {item['hint']}" if item['hint'] else ''


def area_text(db, p, area, ctx=None):
    emoji, title, text, _ = AREAS[area]
    ctx = ctx or context(p.twitch_uid if p is not None else '', db, p)
    children = children_of(area, ctx)
    lines = [f'{emoji} {title.upper()}', text, '']
    if area == 'home' and p is not None:
        # Home: the next step first, then needs and queue, then the areas (the description is left out: the lines say it).
        from . import qol
        from .game.life import life_state
        life = life_state(db, p)
        step = (ctx.get('home_next', lambda: home_next(db, p)) if ctx is not None else home_next(db, p))
        lines = [f'{emoji} NEW ERIDIAN — {p.display_name}', step['line'],
                 f'⚡ {life.energy} · 🍲 {life.nutrition} · 💬 {life.social} · 🛋️ {life.comfort} · 🪙 {p.sc} SC',
                 qol.queue_summary(db, p, 'discord')[0].split('\n')[0], '']
    lines += [x for x in (_line(key) for key in children) if x]
    return '\n'.join(lines).rstrip()


def area_components(owner, area, ctx=None):
    rows = grid(owner, children_of(area, ctx), ctx=ctx, extra=[more_button(owner, area, ctx)])
    return rows + [nav(owner, area)]


def area_items(area, ctx, rows):
    """Each button of an area beside the line that explains it (see ui.with_items).

    The button carries the name (Work, Relax, Full status…), so beside it the line keeps only its
    emoji and what it does. Areas are blue, actions green, views and switches grey.
    """
    keys = children_of(area, ctx)
    buttons = [c for r in rows[:-1] if r for c in r.get('components') or []]
    items = []
    for key, b in zip(keys, buttons):
        leaf_ = LEAVES.get(key)
        if leaf_ is not None and not leaf_['hint']:
            continue                                     # no line to put it beside
        emoji, label, about = (AREAS[key][0], AREAS[key][1], BLURB.get(key, AREAS[key][2])) if leaf_ is None else (leaf_['emoji'], leaf_['label'], leaf_['hint'])
        if area == 'home' and key in HOME_COMPACT:
            items.append({'match': f'**{label}**', 'compact': True})
            continue
        beside = {k: v for k, v in b.items() if k != 'emoji'}
        beside['style'] = 1 if leaf_ is None else (beside.get('style', 3) if leaf_['kind'] == 'do' else 2)
        items.append({'match': f'**{label}**', 'button': beside, 'text': f'{emoji} {about[:1].upper()}{about[1:]}'})
    return items


def crumb(area, tail=''):
    """Where a screen sits in the menu: '🏠 Menu › ⛏️ Work › More'."""
    chain = []
    while area in AREAS and area != 'home' and area not in chain:
        chain.append(area)
        area = PARENT.get(area, 'home')
    return ' › '.join(['🏠 Menu'] + [f'{AREAS[a][0]} {AREAS[a][1]}' for a in reversed(chain)] + ([tail] if tail else []))


def _how(owner, key, ctx, seen):
    """(button beside the line, button for the old layout) that helps with a locked button, or (None, None): a Find
    question for a missing item ("where do I get a Small Water Filter"), else the button that fixes it. One button per
    custom_id: Discord refuses a message that repeats one."""
    label = LEAVES[key]['label'].rstrip('…')
    if key in HOW:
        cid_ = ui.cid(owner, 'fd', HOW[key][1])
        beside, loose = ui.button('How to get it', cid_, style=1), ui.button(f'{label}: how to get it', cid_, style=1, emoji='❓')
    elif HOW_GO.get(key) in LEAVES:
        loose = dict(_button(owner, HOW_GO[key], ctx=ctx), style=1)
        beside = {k: v for k, v in loose.items() if k != 'emoji'}
        beside['label'] = LEAVES[HOW_GO[key]]['label'].rstrip('…')
    else:
        return None, None
    if loose['custom_id'] in seen:
        return None, None
    seen.add(loose['custom_id'])
    return beside, loose


def more_message(db, p, owner, area, ctx=None):
    """An area's More screen: the extras (Also here) and the locked buttons (Not yet) with the reason for each and a
    button that helps. Generated from MORE and the same availability checks the main buttons use."""
    ctx = ctx or context(owner, db, p)
    emoji, title, _, _ = AREAS[area]
    also, locked = more_split(area, ctx)
    lines, items, rows, seen = [f'{emoji} {title.upper()} · MORE'], [], [], set()
    if not also and not locked:
        lines.append('Nothing else here right now.')
    if also:
        lines.append('ALSO HERE')
    for key in also:
        item = LEAVES[key]
        b = _button(owner, key, ctx=ctx)
        rows.append(b)
        beside = {k: v for k, v in b.items() if k != 'emoji'}
        beside['label'] = MORE_VERBS.get(key) or {'do': 'Do it', 'modal': 'Enter', 'pick': 'Choose'}.get(item['kind'], 'Open')
        beside['style'] = beside.get('style', 3) if item['kind'] == 'do' else 2
        items.append({'match': f"**{item['label']}**", 'button': beside})
        lines.append(_line(key))
    if locked:
        lines += ['', 'NOT YET'] if also else ['NOT YET']
    for key, why in locked:
        item = LEAVES[key]
        lines.append(f"{item['emoji']} **{item['label']}** — {why}")
        beside, loose = _how(owner, key, ctx, seen)
        if beside is not None:
            rows.append(loose)
            items.append({'match': f"**{item['label']}**", 'button': beside})
    grid_rows = [ui.row(*rows[i:i + 5]) for i in range(0, min(len(rows), 20), 5)]
    data = ui.message('\n'.join(lines), grid_rows + [nav(owner, area, area)], 'menu', items)
    return ui.with_crumb(data, crumb(area, 'More'))


def quiet_choice(db, p, owner):
    """Quiet hours when they are already set: Change them or Turn them off (one button in Settings does both jobs)."""
    from . import quiet_hours
    found = quiet_hours.row(db, p.channel_id, p.twitch_uid)
    if found is None:
        text = '🌙 QUIET HOURS\nQuiet hours are off. Set a daily window in your time zone when DM alerts wait, then arrive as one message.'
        buttons = [ui.button('Set quiet hours', ui.cid(owner, 'mo', 'quiet'), style=1, emoji='🌙')]
    else:
        text = (f'🌙 QUIET HOURS\nOn: {quiet_hours.clock(found.start_min)}–{quiet_hours.clock(found.end_min)} ({found.tz}). '
                'DM alerts wait until the window ends, then arrive as one message.')
        buttons = [ui.button('Change', ui.cid(owner, 'mo', 'quiet'), style=1, emoji='✏️'),
                   ui.button('Turn off', ui.cid(owner, 'qo'), emoji='☀️')]
    data = ui.message(text, [ui.row(*buttons), nav(owner, 'settings', 'settings')], 'settings')
    return ui.with_crumb(data, crumb('settings', '🌙 Quiet hours'))


def vote_panel(db, p, owner, text, where):
    """Today's vote: the ballot with a Vote button for each option (beside it in the newer layout), or None to show it plainly."""
    import json
    from . import votes
    if not votes.enabled():
        return None
    items, buttons = [], []
    for i, option in enumerate(json.loads(votes.ballot(db).options), 1):
        pick = ui.pick_button(ui.cid(owner, 'mp', 'c_vote_pick'), str(i), 'Vote', style=3)
        if pick is None:
            return None
        items.append({'match': f'**{i}. ', 'button': pick})
        buttons.append(dict(pick, label=wb.clip(f'Vote {i}: {votes.label(option)[1]}', 80)))
    data = ui.message(text, [ui.row(*buttons), nav(owner, 'community', 'community')], 'vote', items)
    return ui.with_crumb(data, where)


ONBOARDING_LEAF = {'gather': 'gather', 'eat': 'eat', 'job': 'job', 'queue': 'queue', 'seedling': 'seedling'}


FIND_GOAL = 'choose a goal: open any recipe and press 🎯 Set goal; the goal then walks you through every step'


def _step(text, **how):
    return dict(how, line=f'➡️ **Do this next** — {text}', beside=f'➡️ {text[:1].upper()}{text[1:]}')


def home_next(db, p):
    """The one thing to do next, for the top of Home. It takes the first of these that applies: a need blocks work,
    the queue is paused, the first steps are not finished, you have a goal, today's contract is not done, your last
    queue finished, or else choosing a goal. A dict with 'line' (the card line), 'beside' (the same without the label,
    for beside the button), 'label', and what the button does (home_button)."""
    try:
        return _home_next(db, p)
    except Exception:    # a check that fails must not take Home down: fall back to choosing a goal
        try:
            db.rollback()
        except Exception:
            pass
        return _step(FIND_GOAL, view=('wc', 'ready', 1, ''), label='Find a goal')


def _home_next(db, p):
    from . import extras, onboarding, task_queue
    from .game.cooldowns_materials import action_display_name, daily
    from .game.life import life_state
    from .needs import blocked_needs
    step = _step
    if blocked_needs(life_state(db, p)):
        return step('recover your needs: work and crafting wait until they are back up', do={'do': 'recover'}, label='Recover')
    q = db.get(task_queue.TaskQueue, (p.channel_id, p.twitch_uid))
    if q is not None and q.state == 'paused':
        why = (q.result or 'requirements not met').splitlines()[0][:80]
        return step(f'your queue paused: {why}', view=('qv',), label='Fix my queue')
    first = onboarding.row(db, p) if onboarding.ENABLED else None
    if first is not None and not first.finished:
        key = onboarding.next_step(first)
        _, goal, _, _, sc, _ = onboarding.INFO[key]
        text = f'{goal} · first steps {len(onboarding.done_of(first))}/{len(onboarding.STEPS)}, +{sc} SC'
        if key == 'craft':
            from . import crafting_progression as cp
            e = next((x for x in wb.index() if x.name == 'Campfire' and cp.SURVIVAL in x.tags), None)
            if e is not None:
                return step(text, view=('wr', e.id, e.category, 1, ''), label='Campfire')
            return step(text, view=('wh',), label='All recipes')
        leaf_ = ONBOARDING_LEAF[key]
        return step(text, key=leaf_, label=AREAS[leaf_][1] if leaf_ in AREAS else LEAVES[leaf_]['label'])
    e, steps = extras.walkthrough(db, p)
    if steps:
        return step(f"{steps[0]['name']} · for your goal: {e.name}", step=steps[0], label='Do this next')
    try:
        d = daily(db, p)
    except Exception:    # two screens made today's contract at the same moment: read the one that won
        db.rollback()
        d = daily(db, p)
    if not d.complete:
        return step(f"today's contract: {action_display_name(d.action)} {d.progress}/{d.target} · {d.reward_sc} SC",
                    view=('mv', 'me_daily'), label='Daily contract')
    if q is not None and q.state == 'completed':
        return step(f"your last queue finished: {task_queue.choices().get(q.task, q.task)} ×{q.total}", do={'do': 'cmd', 'leaf': 'repeat'},
                    label='Repeat last queue')
    return step(FIND_GOAL, view=('wc', 'ready', 1, ''), label='Find a goal')


def home_button(owner, step):
    """The green button for home_next's step (a one-time ticket when it does something)."""
    if 'step' in step:
        b = ui.step_button(owner, step['step'], first=True)
        if b is not None:
            b['label'], b['style'] = step['label'], 3
        return b
    if 'do' in step:
        return ui.button(step['label'], ui.cid(owner, 't', ui.issue(owner, step['do'])), style=3)
    if 'key' in step:
        b = dict(_button(owner, step['key']))
        b.pop('emoji', None)
        b['label'], b['style'] = step['label'], 3
        return b
    return ui.button(step['label'], ui.cid(owner, *step['view']), style=3)


def area_message(db, p, owner, area, ctx=None):
    """An area's card: each button beside the line that explains it (in Discord's newer layout)."""
    ctx = ctx or context(owner, db, p)
    rows = area_components(owner, area, ctx)
    text = area_text(db, p, area, ctx)
    items = area_items(area, ctx, rows)
    if area == 'home' and p is not None:
        rows, items = with_next(db, p, owner, ctx, rows, items)
    data = ui.message(text, rows, 'menu', items)
    return ui.with_crumb(data, crumb(area)) if area != 'home' else dict(data, _home=True)


def with_next(db, p, owner, ctx, rows, items):
    """Home's Do this next button: beside its line in the newer layout, the first row in the old one."""
    step = ctx.get('home_next', lambda: home_next(db, p)) if ctx is not None else home_next(db, p)
    b = home_button(owner, step)
    if b is None:
        return rows, items
    return [ui.row(b)] + [r for r in rows if r], [{'match': '**Do this next**', 'button': b, 'text': step['beside']}] + items


def reply(text, command, rows):
    """A result card (with Details pages when long) followed by menu rows; five rows at most."""
    data = runtime._discord_json_message(text, message_type=command)['data']
    own = [r for r in (data.get('components') or []) if r and r.get('components')]
    extra = [r for r in rows if r and r.get('components')]
    # Keep the result's own controls (e.g. Details) and the navigation row; drop grid rows if needed.
    data['components'] = own + (extra if len(own) + len(extra) <= 5 else extra[-(5 - len(own)):])
    data.pop('flags', None)
    return data


# ---------------------------------------------------------------- choice lists

def choices(db, p, source, uid):
    """(label, value) rows for a leaf's dropdown, at most 25."""
    from . import inbox, qol, seasons, seed_content, task_queue, trophies, votes, workbench
    from .game.cooldowns_materials import available_production_orders
    from .game.discord_commands import DISCORD_OPTION_SCHEMA, _discord_gear_autocomplete, _discord_player_autocomplete, ore_choice_rows
    from .game.players import resource_name, society
    from .game.routes_market import market_item_label
    from .game.rules import QUALITY_RECIPES, SEED_INDUSTRIES, TITLE_DEFS
    from .game.training_and_items import edible_inventory, emergency_food_available, owned_life_items, training_skills
    from .game.world import society_tier_index, world_clock
    if source == 'food':
        foods = edible_inventory(db, p)
        rows = [(f"{r['name']} ×{r['qty']} — {r['effect']}", r['key']) for r in foods if r['qty'] > 0]
        if emergency_food_available(db, p, foods):
            rows.append(('Emergency meal — free; restores Nutrition to 40', 'emergency'))
        return rows
    if source == 'hobby':
        return [(c['name'], c['value']) for c in DISCORD_OPTION_SCHEMA['hobby'][0]['choices']]
    if source == 'use':
        rows = seed_content.choices(db, p, owned=True, usable=True)
        owned = owned_life_items(db, p)
        rows += [(QUALITY_RECIPES[k]['name'] + f" ×{sum(r.qty for r in v)}", k) for k, v in owned.items() if v]
        return rows
    if source == 'ore':
        return ore_choice_rows(db, p)
    if source == 'resource':
        return [row for row in seed_content.choices(db, p, gather_only=True) if row[1] not in task_queue.ores()]
    if source == 'sell':
        stock = seed_content.stock(db, p)
        rows = [(k, n, qol.sell_price(k)) for k, n in stock.items() if n > 0 and qol.sell_price(k)]
        rows.sort(key=lambda r: -r[1] * r[2])
        return [(f'{resource_name(k)} ×{n} — {n * price} SC', k) for k, n, price in rows]
    if source == 'owned':
        stock = seed_content.stock(db, p)
        return [(f'{resource_name(k)} ×{n}', k) for k, n in sorted(stock.items(), key=lambda kv: -kv[1]) if n > 0 and k in seed_content.ACTIVE]
    if source == 'order':
        clock = world_clock(db, p.channel_id)
        orders = available_production_orders(p.channel_id, clock['day'], society_tier_index(society(db, p.channel_id)))
        return [(data['name'], key) for key, data in orders]
    if source == 'player':
        found = _discord_player_autocomplete({'member': {'user': {'id': uid}}, 'data': {'name': 'social'}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source == 'title':
        rows = db.execute(select(PlayerTitle).where(PlayerTitle.channel_id == p.channel_id,
                                                    PlayerTitle.canonical_uid == p.twitch_uid)).scalars().all()
        return [(TITLE_DEFS.get(r.title_key, r.title_key.replace('_', ' ').title()), r.title_key) for r in rows]
    if source == 'skills':
        return [(f'{label} — Lv {level} · {ready} of {total} task{"s" if total != 1 else ""} ready now', hub)
                for hub, label, level, ready, total in training_skills(db, p)]
    if source.startswith('field:'):
        _, command, field = source.split(':', 2)
        return [(c['name'], c['value']) for f in DISCORD_OPTION_SCHEMA.get(command, []) if f['name'] == field for c in f.get('choices', [])]
    if source == 'buy':
        stock = seed_content.stock(db, p)
        rows = [(k, d) for k, d in SEED_INDUSTRIES.items() if d.get('buy', 0) > 0]
        rows.sort(key=lambda kv: (kv[1].get('category', 'legacy') != 'seed', market_item_label(kv[0])))
        return [(f"{market_item_label(k)} — {d['buy']} SC · you have {stock.get(k, 0)}", k) for k, d in rows]
    if source == 'gear':
        found = _discord_gear_autocomplete({'member': {'user': {'id': uid}}, 'data': {}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source == 'station':
        return list(workbench.station_rows(wb.Context(db, p), ''))
    if source == 'player_name':
        found = _discord_player_autocomplete({'member': {'user': {'id': uid}}, 'data': {'name': 'linklookup'}}, '')
        return [(c['name'], c['value']) for c in found['data']['choices']]
    if source.startswith('jobs:'):
        # A list of jobs: the ones the citizen can do now, each with what it gives. The rest are in the area's More under Not yet.
        ctx = Ctx(db, p, uid)
        return [(f"{LEAVES[k]['emoji']} {LEAVES[k]['label']} — {LEAVES[k]['hint']}", LEAVES[k]['opts']['task'])
                for k in JOBS[source.split(':', 1)[1]] if can(ctx, k)]
    if source == 'schedule':
        return choices(db, p, 'field:seedling:schedule', uid) + [('Custom… — choose Work, Free time, Social or Sleep for each part of the day', 'custom')]
    if source.startswith('leaves:'):
        return [(f"{LEAVES[k]['emoji']} {LEAVES[k]['label']}" + (f" — {LEAVES[k]['hint']}" if LEAVES[k]['hint'] else ''), k)
                for k in source.split(':', 1)[1].split(',') if k in LEAVES]
    if source == 'alerts':
        pref = qol.prefs(db, p.channel_id, p.twitch_uid)
        now = pref.alerts if pref is not None and pref.alerts in qol.ALERT_MODES else qol.DEFAULT_ALERTS
        return [(f"{qol.ALERT_LABELS[k].capitalize()}{' (current)' if k == now else ''} — {d}", k) for k, d in qol.ALERT_MODES.items()]
    if source == 'popups':
        now = inbox.popup_mode(db, p.channel_id, p.twitch_uid)
        return [(f"{k.capitalize()}{' (current)' if k == now else ''} — {d}", k) for k, d in inbox.POPUP_MODES.items()]
    if source == 'ballot':
        import json
        row = votes.ballot(db)
        counts = votes.tally(db, row)
        return [(f"{i}. {votes.label(o)[0]} {votes.label(o)[1]} — {c} vote{'s' if c != 1 else ''}", str(i))
                for i, (o, c) in enumerate(zip(json.loads(row.options), counts), 1)]
    if source == 'hats':
        owned, worn = seasons.hats_of(db, p)
        return [(f"{seasons.HATS[h][0]} {seasons.HATS[h][1]}{' (wearing)' if h == worn else ''}", h) for h in owned if h in seasons.HATS] + \
            ([('💼 My job hat', 'job')] if owned else [])
    if source == 'badges':
        trophies._build()
        mine = trophies.owned(db, p)
        return [(f"{t['emoji']} {t['name']}", k) for k, t in trophies.TROPHIES.items() if k in mine]
    if source.startswith('choices:'):
        command = source.split(':', 1)[1]
        return [(c['name'], c['value']) for c in DISCORD_OPTION_SCHEMA[command][0]['choices']]
    return []


PAGE = 23   # dropdown rows per page, leaving room for Previous / Next


def pick_view(db, p, owner, key, page=1):
    item = LEAVES[key]
    everything = choices(db, p, item['pick'], owner)
    pages = max(1, -(-len(everything) // PAGE)) if len(everything) > 25 else 1
    page = max(1, min(page, pages))
    rows = everything[:25] if pages == 1 else everything[(page - 1) * PAGE:page * PAGE]
    area = PARENT.get(key, 'home')
    text = f"{item['emoji']} {item['label'].upper()}\n{item['hint'].capitalize() or 'Choose one.'}"
    if not rows:
        empty = {'food': 'You have no food. Harvest, gather or craft some first.', 'use': 'You own nothing usable yet.',
                 'sell': 'You have nothing Seed Industries buys.', 'player': 'No other citizens yet.',
                 'title': 'You have not unlocked a title yet.', 'order': 'No production orders today.'}
        return text + '\n\n' + empty.get(item['pick'], 'Nothing to choose from right now.'), [nav(owner, area, area)]
    options = [ui.option(label, value) for label, value in rows]
    if pages > 1:
        text += f'\nPage {page} of {pages}.'
        if page > 1:
            options.insert(0, ui.option(f'◀ Previous page ({page - 1}/{pages})', f'__page:{page - 1}'))
        if page < pages:
            options.append(ui.option(f'Next page ({page + 1}/{pages}) ▶', f'__page:{page + 1}'))
    menu = ui.select(ui.cid(owner, 'mp', key), 'Choose…' if pages == 1 else f'Choose… (page {page}/{pages})', options)
    return text, [menu, nav(owner, area, area)]


def pick_message(db, p, owner, key, page=1):
    """A choice list: in the newer layout each choice gets its own button when the list fits on one card."""
    text, rows = pick_view(db, p, owner, key, page)
    item = LEAVES[key]
    select = next((r['components'][0] for r in rows if r and r.get('components') and r['components'][0].get('type') == 3), None)
    items = []
    if select is not None and not any(str(o['value']).startswith('__page:') for o in select['options']):
        then = item.get('then')
        verb = VERBS.get(key) or ('View' if then in {'view', 'leaf', 'uses'} else 'Meet' if then == 'social' else 'Choose')
        for o in select['options']:
            runs = then == 'do' or grouped_action(key, o['value'])      # actions are green, everything else grey
            b = ui.pick_button(select['custom_id'], o['value'], verb, style=3 if runs else 2)
            if b is None:
                items = []
                break
            head, sep, tail = o['label'].partition(' — ')
            items.append({'line': f'**{head}**' + (f' — {tail}' if sep else ''), 'button': b})
    data = ui.message(text, rows, 'menu', items, [select['custom_id']] if items else ())
    return ui.with_crumb(data, crumb(PARENT.get(key, 'home'), item['label'].rstrip('…')))


def grouped_action(key, value):
    """Whether `value` is an action listed in the grouped list `key` (Stream live… holds Stream is live, offline and
    Automatic): choosing it runs that action. Only the list's own entries count, so a stray value runs nothing."""
    item = LEAVES.get(key) or {}
    pick = str(item.get('pick', ''))
    return (item.get('then') == 'leaf' and pick.startswith('leaves:') and value in pick.split(':', 1)[1].split(',')
            and LEAVES.get(value, {}).get('kind') == 'do')


def options_for(key, value=None):
    item = LEAVES[key]
    options = dict(item['opts'])
    if value is not None and item.get('option'):
        options[item['option']] = value
    return item['cmd'], options


# ---------------------------------------------------------------- navigation (spends nothing)

def navigate(db, p, owner, verb, args, values, name):
    """Handle mn/mv/mk/mp controls. Returns message data, or None when the choice must run as an action."""
    from . import extras
    from .game.players import as_utc
    args = list(args)
    if verb == 'mn':
        if args and args[0] in AREA_ALIAS:
            # An area that no longer exists (an older message, the public game panel): open what replaced it.
            alias_verb, alias_args = AREA_ALIAS[args[0]]
            return navigate(db, p, owner, alias_verb, list(alias_args), values, name)
        area = args[0] if args and args[0] in AREAS else 'home'
        sub = args[1] if len(args) > 1 else ''
        if sub == 'more' and area != 'home':
            return more_message(db, p, owner, area)
        if sub == 'quiet' and area == 'settings':
            return quiet_choice(db, p, owner)
        if area == 'recent':
            actions = extras.recent(db, p.channel_id, p.twitch_uid)
            text = '🔁 DO AGAIN\nTap one to do it again. Each button works once; the result brings fresh buttons.\n\n' + (
                '\n'.join(f'• {a.label} · <t:{int(as_utc(a.created_at).timestamp())}:R>' for a in actions) or 'Nothing yet. Actions you take appear here.')
            rows = ui.recent_components(db, p, owner)
            buttons = [c for r in rows[:-1] for c in r['components']]
            items = [{'match': f'{a.label} · <t:', 'button': dict(b, label='Again')} for a, b in zip(actions, buttons)]
            return ui.message(text, rows, 'menu', items)
        return area_message(db, p, owner, area)
    key = args[0] if args else ''
    if key in LEAF_ALIAS and verb in {'mv', 'mk'}:
        # A leaf merged into another (Training, Sell some, Cast your vote, More…): open its replacement.
        return navigate(db, p, owner, LEAF_ALIAS[key][0], list(LEAF_ALIAS[key][1]), values, name)
    if key == 'sellsome':
        key = 'sell'                       # its choices and amounts are Sell's now
        args = ['sell'] + args[1:]
    if key not in LEAVES:
        return ui.message('That button is no longer available. Here is the menu.', area_components(owner, 'home', context(owner, db, p)), 'menu')
    item = LEAVES[key]
    area = PARENT.get(key, 'home')
    if key in OWNER_ONLY:
        return ui.extra_view(db, p, owner, 'xk', [], [], name)
    if verb == 'mv':
        command, options = options_for(key)
        return show(db, p, owner, command, options, area, name, key)
    if verb == 'mk':
        return pick_message(db, p, owner, key)
    if verb == 'mp' and values and str(values[0]).startswith('__page:'):
        return pick_message(db, p, owner, key, int(values[0].split(':', 1)[1] or 1))
    if verb == 'ma':
        return amount_view(db, p, owner, key, args[1] if len(args) > 1 else '')
    if verb == 'mp':
        value = values[0] if values else ''
        then = item.get('then')
        if then == 'amount':
            return amount_view(db, p, owner, key, value)
        if then == 'view':
            command, options = options_for(key, value)
            if key == ui.TRAIN_PICK:
                options.update(ui.training_options(value))      # 'medicine~2': the skill's second page of tasks
            return show(db, p, owner, command, options, area, name, key)
        if then == 'leaf' and value in LEAVES and LEAVES[value]['kind'] == 'view':
            command, options = options_for(value)
            return show(db, p, owner, command, options, area, name, value)
        if then == 'leaf' and value in LEAVES and LEAVES[value]['kind'] == 'pick':
            return pick_message(db, p, owner, value)             # Looks: Body…, Clothes… and Voice… open pickers
        if then == 'confirm':
            ticket = ui.issue(owner, {'do': 'cmd', 'leaf': key, 'value': value})
            label = dict((v, l) for l, v in choices(db, p, item['pick'], owner)).get(value, value)
            text = f"{item['emoji']} CONFIRM\n{item['label'].rstrip('…')} **{label}**?\nNothing happens until you press Confirm."
            return ui.message(text, [ui.row(ui.button('Confirm', ui.cid(owner, 't', ticket), style=3, emoji='✔️'),
                                               ui.back_button(owner, 'mk', key),
                                               ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))], 'menu')
        if then == 'panel':
            if item['pick'] == 'ore':
                command, options = 'mine', {'ore': value}
                return show(db, p, owner, command, options, area, name, key)
            text = runtime._discord_call_internal('catalog', owner, name, {'item': value}, '')
            return reply(text, 'catalog', ui.work_components(owner, 'gather:' + value) + [nav(owner, area, area)])
        if then == 'uses':
            text, rows = extras.uses_text(db, p, value)
            return ui.message(text, ui.uses_components(owner, rows), 'catalog')
        if then == 'social':
            label = dict((v, l) for l, v in choices(db, p, 'player', owner)).get(value, 'that citizen')
            buttons = [ui.button(LEAVES['s_' + a]['label'], ui.cid(owner, 't', ui.issue(owner, {'do': 'cmd', 'leaf': 's_' + a, 'value': value})),
                                 style=3, emoji=LEAVES['s_' + a]['emoji']) for a, _, _ in SOCIAL]
            text = f'🤝 WITH {label.upper()}\nPick an activity. Each one builds your relationship and restores Social.'
            return ui.message(text, [ui.row(*buttons[:5]), ui.row(*buttons[5:]), nav(owner, 'life', 'life')], 'menu')
        return None   # 'do': run it as an action
    return None


AMOUNTS = (1, 5, 10, 25)
MAX_AMOUNT = 25    # Seed Industries buys and sells at most 25 at a time (the slash command's limit too)


def amount_view(db, p, owner, key, value):
    """How many? Buttons for 1, 5, 10, 25 and your own amount. Selling also offers Sell all (it leaves what your keep level
    keeps) and Sell it after my queue."""
    from . import keep_levels
    from .game.cooldowns_materials import material_amount
    from .game.players import resource_name
    item = LEAVES[key]
    command, options = options_for(key, value)
    label = dict((v, l) for l, v in choices(db, p, item['pick'], owner)).get(value) or resource_name(value)
    selling = options.get('action') == 'sell'
    have = (getattr(p, value, 0) if command == 'market' else material_amount(db, p, value)) if selling else 0
    kept = keep_levels.keep_for(db, p, value) if selling else 0
    buttons = []
    for n in AMOUNTS:
        if selling and n > have:
            continue
        ticket = ui.issue(owner, {'do': 'cmd', 'leaf': key, 'value': value, 'amount': n})
        buttons.append(ui.button(f'{"Sell" if selling else "Buy"} {n}', ui.cid(owner, 't', ticket), style=3, emoji=item['emoji']))
    everything = have - kept
    if selling and everything > 0 and (kept or everything not in AMOUNTS):
        ticket = ui.issue(owner, {'do': 'cmd', 'leaf': key, 'value': value})        # no amount: sell the whole stack
        buttons.append(ui.button(f'Sell all {everything}', ui.cid(owner, 't', ticket), style=3, emoji=item['emoji']))
    other = ui.button('Other amount…', ui.cid(owner, 'mo', key, value), emoji='✏️')
    later = ui.button('Sell it after my queue', ui.cid(owner, 't', ui.issue(owner, {'do': 'sellstep', 'item': value})), emoji='🗺️') if selling and have else None
    text = f"{item['emoji']} {item['label'].rstrip('…').upper()}\n**{label}**\nHow many? Each button works once." + (
        f'\nYou have {have}.' if selling else '')
    if selling and not have:
        text += '\nYou have none of this to sell.'
    if kept:
        text += f'\n🛡️ Always keep is {kept}, so Sell all leaves that many; the other buttons sell exactly what you choose.'
    return ui.message(text, [ui.row(*buttons[:5]), ui.row(other, later, ui.back_button(owner, 'mk', key),
                                                            ui.button('Menu', ui.cid(owner, 'mn', 'home'), emoji='🏠'))], 'menu')


def modal(owner, key, args=()):
    """The pop-up form for a leaf (response type 9), or None."""
    item = LEAVES.get(key)
    if item is None:
        return None
    if key == 'quiet':
        return ui.quiet_form(owner)
    if key == 'keep' and args:
        return ui.modal(ui.cid(owner, 'md', key, args[0]), 'Keep how many?', 'Amount to always keep (0 removes it)', 'e.g. 30', 1, 4)
    if key == 'shopping':
        if args:
            return ui.modal(ui.cid(owner, 'md', key, args[0]), 'Want how many?', 'How many to have (0 removes it)', 'e.g. 30', 1, 3)
        return ui.modal(ui.cid(owner, 'md', key), 'Add to your shopping list', 'Recipe', 'e.g. Iron Plate', 1, 60,
                        more=[ui.text_box('amount', 'How many to have (blank: one batch)', 'e.g. 30', 0, 3, required=False)])
    if item.get('then') == 'amount':
        value = args[0] if args else ''
        return ui.modal(ui.cid(owner, 'md', key, value), 'How many?', f'Amount (1–{MAX_AMOUNT})', 'e.g. 12', 1, len(str(MAX_AMOUNT)))
    if item['kind'] != 'modal':
        return None
    title, label, placeholder = item['modal']
    return ui.modal(ui.cid(owner, 'md', key), title, label, placeholder, 1, item.get('max_length', 60))


def submit(db, p, owner, name, key, args, value, fields=None):
    """A submitted form: message data to show, or a {'do': ...} action to run once. `fields`: every text box of the form."""
    from . import ask, keep_levels, shopping_list
    item = LEAVES.get(key)
    if item is None:
        return None
    if key == 'keep':
        # A keep level only changes the citizen's own setting, so it needs no one-time ticket.
        return ui.keep_message(db, p, owner, keep_levels.set_level(db, p, args[0] if args else '', value))
    if key == 'quiet':
        # Quiet hours too: three boxes (time zone, start, end); a refusal changes nothing.
        from . import quiet_hours
        fields = fields or {}
        note = quiet_hours.set_hours(db, p, value, fields.get('start', ''), fields.get('end', ''))
        db.flush()
        return ui.quiet_message(db, p, owner, note)
    if key == 'shopping':
        # So does the shopping list: a recipe's amount (Custom…), or a recipe and an amount (Add recipe…).
        shop = shopping_list
        note = shop.set_entry(db, p, args[0], value) if args else shop.add_typed(db, p, value, (fields or {}).get('amount', ''))
        db.flush()
        return ui.shopping_message(db, p, owner, note)
    if item.get('then') == 'amount':
        if not value.strip().isdecimal() or not 1 <= int(value) <= MAX_AMOUNT:
            hint = ' For more, use Sell all.' if options_for(key)[1].get('action') == 'sell' else ' For more, buy again.'
            return ui.message(f'✏️ Enter a whole number from 1 to {MAX_AMOUNT}.{hint} Nothing was spent.',
                              [nav(owner, PARENT.get(key, 'home'), PARENT.get(key, 'home'))], 'menu')
        value = value.strip()
        return {'do': 'cmd', 'leaf': key, 'value': args[0] if args else '', 'amount': int(value)}
    command, options = options_for(key, value)
    if key == 'find':
        query = value[:ask.MAX_QUERY]
        return ui.message(ask.reply(db, p, query), ui.find_components(owner, query, db, p), 'find')
    if item['kind'] == 'modal' and command in {'inventory'}:
        return show(db, p, owner, command, options, PARENT.get(key, 'home'), name, key)
    return {'do': 'cmd', 'leaf': key, 'value': value}


def _denied(command):
    if command not in MOD_COMMANDS:
        return ''
    if command == 'linklookup':
        return '' if ui.is_owner() else '⛔ Owner access is required for linked-account lookup.'
    return '' if ui.is_moderator() else '⛔ Only the game owner can use this tool.'


def show(db, p, owner, command, options, area, name, key=''):
    """Run a view command and show it with its own panel (if any) and this area's buttons."""
    from .game.discord_commands import discord_legacy_route
    denied = _denied(discord_legacy_route(command, options)[0])
    if denied:
        return ui.message(denied, [nav(owner, area, area)], 'moderator')
    text = runtime._discord_call_internal(command, owner, name, options, '')
    legacy, legacy_options = discord_legacy_route(command, options)
    where = crumb(area, LEAVES[key]['label'].rstrip('…') if key in LEAVES else '')
    if key == 'c_vote':
        voted = vote_panel(db, p, owner, text, where)
        if voted is not None:
            return voted
    panel = ui.slash_panel(legacy, owner, name, legacy_options, text)
    bottom = nav(owner, area, area)
    shared = ui.share_button(owner, legacy, legacy_options)
    if shared:
        bottom = ui.row(shared, *((bottom or {}).get('components') or []))
    if panel is not None:
        rows = [r for r in panel.get('components', []) if r.get('components')]
        panel['components'] = rows[:4] + [bottom]
        return ui.with_crumb(panel, where)
    # Every view of the bag keeps Sort & filter and Search under it.
    tools = [ui.row(_button(owner, 'inv_views'), _button(owner, 'search'))] if legacy == 'inventory' else []
    data = reply(text, legacy, tools + area_rows(owner, area, context(owner, db, p), rows=3 - len(tools)) + [bottom])
    return ui.with_crumb(ui.add_list_items(data, owner, legacy, legacy_options, name), where)


# ---------------------------------------------------------------- actions (one-time tickets)

def run(uid, name, action, token=''):
    """Run a menu action; returns message data with the result and the area's buttons again."""
    from .game.discord_commands import discord_legacy_route
    if 'raw' in action:
        command, options = action['raw']
        area = COMMAND_AREA.get(discord_legacy_route(command, options)[0], 'home')
    else:
        key = action['leaf']
        if key == 'sl_schedule' and action.get('value') == 'custom':
            # The schedule list's last choice: one dropdown per part of the day.
            return with_context(uid, lambda c: ui.schedule_editor(c.db, c.p, uid), name)
        command, options = options_for(key, action.get('value'))
        if action.get('amount'):
            options['amount'] = int(action['amount'])
        elif key == 'sell':
            options['action'] = 'sellall'               # Sell all N: the whole stack, minus what the keep level keeps
        area = PARENT.get(key, 'home')
        if key.startswith('s_'):
            area = 'life'
    legacy, legacy_options = discord_legacy_route(command, options)
    denied = _denied(legacy)
    if denied:
        return reply(denied, 'moderator', [nav(uid, area, area)])
    text = runtime._discord_call_internal(command, uid, name, options, 'menu-' + (token or secrets.token_hex(8)))
    panel = ui.slash_panel(legacy, uid, name, legacy_options, text)
    if panel is not None:
        rows = [r for r in panel.get('components', []) if r.get('components')]
        panel['components'] = rows[:4] + [nav(uid, area, area)]
        return panel
    rows = with_context(uid, lambda c: area_rows(uid, area, c, rows=3), name) + [nav(uid, area, area)]
    if legacy == 'seedindustries' and legacy_options.get('action') == 'sellall' and 'sold' in text:
        rows = [ui.row(ui.button('Undo sale (60s)', ui.cid(uid, 't', ui.issue(uid, {'do': 'undo'})), style=4, emoji='↩️'),
                       ui.button('Sell another', ui.cid(uid, 'mk', 'sell'), emoji='🏷️'), ui.button('Auto-sell', ui.cid(uid, 'av'), emoji='🧹'),
                       ui.button('Always keep', ui.cid(uid, 'kv'), emoji='🛡️')), rows[-1]]
    leaf_ = LEAVES.get(action.get('leaf', ''))
    return ui.with_crumb(reply(text, legacy, rows), crumb(area, leaf_['label'].rstrip('…') if leaf_ else ''))


def after_command(command, options, uid):
    """The button row added under every slash command reply: Again, its area, and Menu."""
    from .game.discord_commands import discord_legacy_route
    legacy, legacy_options = discord_legacy_route(command, options)
    buttons = []
    if legacy in REPEATABLE and not (legacy == 'eat' and not legacy_options.get('food')) and not (legacy == 'use' and not legacy_options.get('item')):
        ticket = ui.issue(uid, {'do': 'cmd', 'raw': [command, dict(options or {})]})
        buttons.append(ui.button('Again', ui.cid(uid, 't', ticket), style=3, emoji='🔁'))
    if legacy == 'seedindustries' and legacy_options.get('action') == 'sellall':
        buttons.append(ui.button('Undo sale (60s)', ui.cid(uid, 't', ui.issue(uid, {'do': 'undo'})), style=4, emoji='↩️'))
    buttons.append(ui.share_button(uid, legacy, legacy_options))
    area = COMMAND_AREA.get(legacy, 'home')
    if area != 'home':
        emoji, title, _, _ = AREAS[area]
        buttons.append(ui.button(title, ui.cid(uid, 'mn', area), emoji=emoji))
    buttons.append(ui.button('Menu', ui.cid(uid, 'mn', 'home'), emoji='🏠'))
    return ui.row(*[b for b in buttons if b])


# Replies whose own rows already lead on (a skill's Start buttons and its pages): only Again / area / Menu under them.
OWN_ROWS = {'training'}


def after_rows(command, options, uid, room=2):
    """Rows under a slash reply: the area's most-used buttons, then Again / area / Menu."""
    from .game.discord_commands import discord_legacy_route
    last = after_command(command, options, uid)
    legacy = discord_legacy_route(command, options)[0]
    if room < 2 or legacy in OWN_ROWS:
        return [last]
    area = COMMAND_AREA.get(legacy, 'home')
    visible = with_context(uid, lambda c: children_of(area, c))
    keys = [k for k in visible if k not in MOD_AREAS and not (k in LEAVES and (LEAVES[k]['kind'] == 'switch' or LEAVES[k]['cmd'] == legacy and LEAVES[k]['kind'] != 'pick'))]
    quick = grid(uid, keys[:5], rows=1)
    return quick + [last]


def home_text(uid, name):
    from .game.players import player
    with SessionLocal() as db:
        p = player(db, runtime.DISCORD_WORLD_ID, 'discord', uid, name)[1]
        text = area_text(db, p, 'home')
        db.commit()
        return text
